-- MyFA Scan: full auction house scan via the replicate list (rate-limited by Blizzard to ~1 per 15 min).
local ADDON, ns = ...

local SCAN_COOLDOWN = 15 * 60
local BATCH = 1500          -- auctions processed per frame, keeps the game responsive
local MARKET_SHARE = 0.15   -- market value = avg unit price of the cheapest 15% of listed quantity
local LADDER_LEVELS = 8     -- cheapest distinct price levels kept per item

local scanning = false

local function setStatus(text)
    ns.scanStatus = text
    if ns.RefreshHeader then ns.RefreshHeader() end
end

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
    realm.lastScan = time()
    realm.auctions = auctions
    realm.itemCount = count
    scanning = false
    setStatus(nil)
    ns.Print(string.format("scan done: %d auctions, %d items. Type /reload to hand it to MyFA Desk.", auctions, count))
    if ns.RefreshPanel then ns.RefreshPanel() end
end

local function process()
    local AH = C_AuctionHouse
    local total = AH.GetNumReplicateItems() or 0
    local realmKey = ns.RealmKey()
    local byItem = {}
    local index, used = 0, 0

    local function step()
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
        if index < total then
            setStatus(string.format("Reading %d%%", math.floor(index / total * 100)))
            C_Timer.After(0, step)
        else
            finish(realmKey, byItem, used)
        end
    end

    if total == 0 then
        scanning = false
        setStatus(nil)
        ns.Print("the Auction House returned no data. Try again in a moment.")
        return
    end
    step()
end

ns.eventFrame:HookScript("OnEvent", function(self, event)
    if event == "REPLICATE_ITEM_LIST_UPDATE" and scanning then
        self:UnregisterEvent("REPLICATE_ITEM_LIST_UPDATE")
        setStatus("Reading auctions")
        C_Timer.After(0, process)
    end
end)

function ns.ScanCooldownLeft()
    local realm = MyFA_DB.realms[ns.RealmKey()]
    local last = realm and realm.lastScan or 0
    return math.max(0, SCAN_COOLDOWN - (time() - last))
end

function ns.StartScan()
    if scanning then ns.Print("a scan is already running."); return end
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
    scanning = true
    setStatus("Waiting for server")
    ns.eventFrame:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")
    C_AuctionHouse.ReplicateItems()
end

function ns.IsScanning() return scanning end

-- exposed for the offline test harness
ns._summarize = summarize
