-- MyFA Scan: full auction house scan via the replicate list (Blizzard allows about one per 15 min).
-- States: waiting (asked the server, nothing back yet) -> reading (going through every auction) -> done,
-- or cancelled (Auction House closed, or the server never answered).
local ADDON, ns = ...

local SCAN_COOLDOWN = 15 * 60
local BATCH = 1500          -- auctions processed per frame, keeps the game responsive
local MARKET_SHARE = 0.15   -- market value = avg unit price of the cheapest 15% of listed quantity
local LADDER_LEVELS = 8     -- cheapest distinct price levels kept per item
local SERVER_TIMEOUT = 120  -- seconds to wait for the auction list before giving up

local clock = GetTime or function() return time() end

-- what the UI shows: { phase, started, done, total, auctions, items, finished, reason }
local scan = { phase = nil }
local token = 0
local ticker

function ns.ScanInfo() return scan end
function ns.IsScanning() return scan.phase == "waiting" or scan.phase == "reading" end

local function refresh()
    if ns.RefreshHeader then ns.RefreshHeader() end
end

local function stopTicker()
    if ticker then ticker:Cancel(); ticker = nil end
end

local function cancel(reason)
    if not ns.IsScanning() then return end
    token = token + 1
    stopTicker()
    ns.eventFrame:UnregisterEvent("REPLICATE_ITEM_LIST_UPDATE")
    scan = { phase = "cancelled", reason = reason, finished = time() }
    ns.Print(reason)
    refresh()
end
ns.CancelScan = cancel

local function summarize(listings)
    -- listings: array of {unitPrice, quantity}
    table.sort(listings, function(a, b) return a[1] < b[1] end)
    local total = 0
    for i = 1, #listings do total = total + listings[i][2] end

    local want = math.max(1, math.floor(total * MARKET_SHARE + 0.5))
    local taken, spent = 0, 0
    for i = 1, #listings do
        local take = math.min(listings[i][2], want - taken)
        spent = spent + take * listings[i][1]
        taken = taken + take
        if taken >= want then break end
    end

    local ladder, cum = {}, 0
    for i = 1, #listings do
        local price, qty = listings[i][1], listings[i][2]
        cum = cum + qty
        local last = ladder[#ladder]
        if last and last[1] == price then
            last[2] = cum
        elseif #ladder < LADDER_LEVELS then
            ladder[#ladder + 1] = { price, cum }
        else
            break
        end
    end

    return {
        m = listings[1][1],
        p = math.floor(spent / math.max(taken, 1) + 0.5),
        q = total,
        n = #listings,
        l = ladder,
    }
end

local function finish(realmKey, byItem, auctions)
    local realm = MyFA_DB.realms[realmKey] or { h = {} }
    MyFA_DB.realms[realmKey] = realm
    realm.h = realm.h or {}

    local items, count = {}, 0
    local today = ns.Today()
    for itemID, listings in pairs(byItem) do
        local s = summarize(listings)
        items[itemID] = s
        count = count + 1
        local h = realm.h[itemID]
        if not h then h = {}; realm.h[itemID] = h end
        if not h[today] or s.m < h[today] then h[today] = s.m end
        ns.FillItemMeta(itemID)
    end

    -- prune history older than HISTORY_DAYS
    local cutoff = today - ns.HISTORY_DAYS
    for _, h in pairs(realm.h) do
        for day in pairs(h) do
            if day < cutoff then h[day] = nil end
        end
    end

    realm.items = items
    realm.neutral = ns.AtNeutralAH() or nil
    realm.lastScan = time()
    realm.auctions = auctions
    realm.itemCount = count
    stopTicker()
    scan = { phase = "done", auctions = auctions, items = count, finished = time() }
    ns.scannedThisSession = true
    ns.Print(string.format("%sscan done: %d auctions, %d items. Next: type /reload so MyFA Desk can read it.",
        ns.AtNeutralAH() and "neutral Auction House " or "", auctions, count))
    refresh()
    if ns.RefreshPanel then ns.RefreshPanel() end
    if ns.CheckFlips then ns.CheckFlips() end
end

local function read()
    if scan.phase ~= "waiting" then return end
    ns.eventFrame:UnregisterEvent("REPLICATE_ITEM_LIST_UPDATE")
    local AH = C_AuctionHouse
    local total = AH.GetNumReplicateItems() or 0
    if total == 0 then
        cancel("the Auction House sent an empty list. Wait a moment and press Full scan again.")
        return
    end
    local myToken = token
    local realmKey = ns.MarketKey()  -- your faction's Auction House, or the neutral one
    local byItem = {}
    local index, used = 0, 0
    scan.phase, scan.total, scan.done = "reading", total, 0
    refresh()

    local function step()
        if myToken ~= token or scan.phase ~= "reading" then return end  -- cancelled meanwhile
        local last = math.min(index + BATCH, total) - 1
        for i = index, last do
            local _, _, count, _, _, _, _, _, _, buyout, _, _, _, _, _, _, itemID = AH.GetReplicateItemInfo(i)
            if itemID and buyout and buyout > 0 and count and count > 0 then
                local list = byItem[itemID]
                if not list then list = {}; byItem[itemID] = list end
                list[#list + 1] = { math.floor(buyout / count), count }
                used = used + 1
            end
        end
        index = last + 1
        scan.done = index
        if index < total then
            refresh()
            C_Timer.After(0, step)
        else
            finish(realmKey, byItem, used)
        end
    end
    step()
end

ns.eventFrame:HookScript("OnEvent", function(self, event)
    if event == "REPLICATE_ITEM_LIST_UPDATE" and scan.phase == "waiting" then
        C_Timer.After(0, read)
    end
end)

-- the event isn't always delivered: also watch the list size, and give up after SERVER_TIMEOUT
local lastCount, steady = 0, 0
local function watchServer()
    if scan.phase ~= "waiting" then return end
    local elapsed = clock() - scan.started
    local n = C_AuctionHouse.GetNumReplicateItems and C_AuctionHouse.GetNumReplicateItems() or 0
    if n > 0 and n == lastCount then steady = steady + 1 else steady = 0 end
    lastCount = n
    if n > 0 and steady >= 2 and elapsed >= 3 then
        read()
    elseif elapsed > SERVER_TIMEOUT then
        cancel("the server didn't send the auction list. Press Full scan again in a minute.")
    else
        refresh()
    end
end

function ns.ScanCooldownLeft()
    local realm = MyFA_DB.realms[ns.MarketKey()]
    local last = realm and realm.lastScan or 0
    return math.max(0, SCAN_COOLDOWN - (time() - last))
end

function ns.StartScan()
    if ns.IsScanning() then ns.Print("a scan is already running."); return end
    if not (AuctionHouseFrame and AuctionHouseFrame:IsShown()) then
        ns.Print("open the Auction House first.")
        return
    end
    if not (C_AuctionHouse and C_AuctionHouse.ReplicateItems) then
        ns.Print("this client has no full-scan API. Use a search-based scanner instead.")
        return
    end
    local left = ns.ScanCooldownLeft()
    if left > 0 then
        ns.Print(string.format("Blizzard allows one full scan every 15 min. Next scan in %d:%02d.", math.floor(left / 60), left % 60))
        return
    end
    token = token + 1
    scan = { phase = "waiting", started = clock() }
    lastCount, steady = 0, 0
    ns.eventFrame:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")
    C_AuctionHouse.ReplicateItems()
    stopTicker()
    ticker = C_Timer.NewTicker(1, watchServer)
    ns.Print("scan started. Keep the Auction House open; this takes a few seconds to a minute.")
    refresh()
end

-- the scan needs the Auction House open
local closer = CreateFrame("Frame")
closer:RegisterEvent("AUCTION_HOUSE_CLOSED")
closer:SetScript("OnEvent", function()
    if ns.IsScanning() then
        cancel("scan stopped because the Auction House closed. Reopen it and press Full scan.")
    end
end)

-- exposed for the offline test harness
ns._summarize = summarize
ns._watchServer = watchServer
