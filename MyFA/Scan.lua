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

-- Sales tracking, the way market trackers do it: compare each listing with the previous scan.
-- A listing that's gone although its time-left band says it couldn't have run out yet was bought
-- (unless the same seller relisted the same stack, which is a repost). One that could have run out
-- may have expired: counted fully only at the high end of the estimate.
local BAND_MIN = { [0] = 0, [1] = 1800, [2] = 7200, [3] = 43200 }   -- Short, Medium, Long, Very long
local MAX_GAP = 12 * 3600     -- 12h+ apart, any listing could have run out, so nothing proves a sale
local SALES_DAYS = 14

local function packSigs(sigs)
    local out = {}
    for itemID, set in pairs(sigs) do
        local parts = {}
        for sig, e in pairs(set) do parts[#parts + 1] = sig .. "=" .. e[1] .. "=" .. (e[2] or -1) end
        out[itemID] = table.concat(parts, ";")
    end
    return out
end

local function unpackSigs(str)
    local set = {}
    for sig, n, b in string.gmatch(str or "", "([^;=]+)=(%d+)=(%-?%d+)") do
        set[sig] = { tonumber(n), tonumber(b) }
    end
    return set
end

local function trackSales(realm, sigs, now)
    local prev, prevT = realm.prev, realm.prevT
    realm.prev, realm.prevT = packSigs(sigs), now
    if not prev or not prevT then return end
    local gap = now - prevT
    if gap <= 0 or gap > MAX_GAP then return end
    realm.lastGap = gap
    local today = ns.Today()
    realm.sd = realm.sd or {}
    realm.obs = realm.obs or {}
    realm.obs[today] = (realm.obs[today] or 0) + gap / 3600
    for itemID, packed in pairs(prev) do
        local before = unpackSigs(packed)
        local after = sigs[itemID] or {}
        -- new stacks per seller and size, to spot reposts
        local fresh = {}
        for sig, e in pairs(after) do
            local was = before[sig] and before[sig][1] or 0
            if e[1] > was then
                local owner, count = sig:match("^(.-):(%d+):")
                local key = (owner or "?") .. ":" .. (count or "0")
                fresh[key] = (fresh[key] or 0) + (e[1] - was)
            end
        end
        local early, maybe, value = 0, 0, 0
        for sig, e in pairs(before) do
            local gone = e[1] - (after[sig] and after[sig][1] or 0)
            if gone > 0 then
                local owner, count, buyout = sig:match("^(.-):(%d+):(%d+)$")
                count, buyout = tonumber(count) or 1, tonumber(buyout) or 0
                local key = (owner or "?") .. ":" .. count
                for _ = 1, gone do
                    if (fresh[key] or 0) > 0 then
                        fresh[key] = fresh[key] - 1            -- reposted at another price: not a sale
                    elseif e[2] and e[2] >= 0 and gap < (BAND_MIN[e[2]] or 0) then
                        early = early + count                  -- couldn't have expired: bought
                        value = value + buyout
                    else
                        maybe = maybe + count
                    end
                end
            end
        end
        if early > 0 or maybe > 0 then
            local d = realm.sd[itemID]
            if not d then d = {}; realm.sd[itemID] = d end
            local r = d[today]
            if not r then r = { 0, 0, 0 }; d[today] = r end
            r[1], r[2], r[3] = r[1] + early, r[2] + maybe, r[3] + value
        end
    end
    local cutoff = today - SALES_DAYS
    for itemID, d in pairs(realm.sd) do
        for day in pairs(d) do if day < cutoff then d[day] = nil end end
        if next(d) == nil then realm.sd[itemID] = nil end
    end
    for day in pairs(realm.obs) do if day < cutoff then realm.obs[day] = nil end end
end

local function finish(realmKey, byItem, auctions, others, sigs, gear)
    local realm = MyFA_DB.realms[realmKey] or { h = {} }
    MyFA_DB.realms[realmKey] = realm
    realm.h = realm.h or {}

    local items, count = {}, 0
    local today = ns.Today()
    for itemID, listings in pairs(byItem) do
        local s = summarize(listings)
        local o = others and others[itemID]
        if o == nil then s.x = true elseif o ~= s.m then s.o = o end  -- x: only you list it; o: cheapest from someone else
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
    if gear then
        realm.gear = {}
        for key, e in pairs(gear) do realm.gear[key] = e[1] end
        if ns.QueueGearStats then ns.QueueGearStats(gear) end
    end
    local gapBefore = realm.prevT and (time() - realm.prevT) or nil
    if sigs then trackSales(realm, sigs, time()) end
    realm.lastScan = time()
    realm.auctions = auctions
    realm.itemCount = count
    stopTicker()
    scan = { phase = "done", auctions = auctions, items = count, finished = time() }
    ns.scannedThisSession = true
    ns.Print(string.format("%sscan done: %d auctions, %d items. Next: type /reload so MyFA Desk can read it.",
        ns.AtNeutralAH() and "neutral Auction House " or "", auctions, count))
    if gapBefore and gapBefore <= 12 * 3600 then
        ns.Print(string.format("|cff6fd08asales measured|r over the %s since your last scan here.", ns.Duration(gapBefore)))
    else
        ns.Print("|cffa9a59atip: scan here again in 20 minutes to a few hours (under 12): comparing two scans shows what actually sells, which is what flips are judged on.|r")
    end
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
    local byItem, others, sigs, gear = {}, {}, {}, {}
    local mine = ns.MyNames()
    local timeLeft = AH.GetReplicateItemTimeLeft
    local itemLink = AH.GetReplicateItemLink
    local isGear = {}
    local index, used = 0, 0
    scan.phase, scan.total, scan.done = "reading", total, 0
    refresh()

    local function step()
        if myToken ~= token or scan.phase ~= "reading" then return end  -- cancelled meanwhile
        local last = math.min(index + BATCH, total) - 1
        for i = index, last do
            local _, _, count, _, _, _, _, _, _, buyout, _, _, _, owner, _, _, itemID = AH.GetReplicateItemInfo(i)
            if itemID and buyout and buyout > 0 and count and count > 0 then
                local list = byItem[itemID]
                if not list then list = {}; byItem[itemID] = list end
                local unit = math.floor(buyout / count)
                list[#list + 1] = { unit, count }
                -- cheapest listing that isn't yours, for the undercut check
                if not (owner and mine[owner]) and (not others[itemID] or unit < others[itemID]) then others[itemID] = unit end
                -- gear: cheapest listing per item and random suffix ("of the Eagle"), for the upgrade finder
                local g = isGear[itemID]
                if g == nil then g = ns.IsGearItem(itemID); isGear[itemID] = g end
                if g and itemLink then
                    local ok, link = pcall(itemLink, i)
                    local key = ok and link and ns.GearKey(link)
                    if key and (not gear[key] or unit < gear[key][1]) then gear[key] = { unit, link } end
                end
                -- this listing's identity and time-left band, to tell sold from expired next scan
                local band = -1
                if timeLeft then
                    local ok, b = pcall(timeLeft, i)
                    if ok and type(b) == "number" then band = b end
                end
                local set = sigs[itemID]
                if not set then set = {}; sigs[itemID] = set end
                local sig = string.gsub(owner or "?", "[:;=]", "") .. ":" .. count .. ":" .. buyout
                local e = set[sig]
                if e then e[1] = e[1] + 1; if band < e[2] then e[2] = band end else set[sig] = { 1, band } end
                used = used + 1
            end
        end
        index = last + 1
        scan.done = index
        if index < total then
            refresh()
            C_Timer.After(0, step)
        else
            finish(realmKey, byItem, used, others, sigs, gear)
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
