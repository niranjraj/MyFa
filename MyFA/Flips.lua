-- MyFA Flips: records what you buy on the Auction House (through any window or addon),
-- works out your cost for what you still own on every character, and alerts you when it's worth selling.
local ADDON, ns = ...

local DAY = 86400
local KEEP_DAYS = 90
local GREEN, MUTED = "|cff6fd08a", "|cffa9a59a"

-- recording ---------------------------------------------------------------------

-- a purchase we already have (same item, amount and price within a few days): don't record it twice
local function alreadyRecorded(itemID, qty, unit, when)
    for _, e in ipairs(MyFA_DB.ledger) do
        if e.k == "buy" and e.id == itemID and e.q == qty and not e.x
            and math.abs((e.u or 0) - unit) <= math.max(2, unit * 0.03)
            and math.abs((e.t or 0) - when) < 4 * DAY then
            return true
        end
    end
    return false
end

ns._alreadyRecorded = alreadyRecorded

-- how many of a purchase you haven't sold yet (sales close purchases oldest first)
local function left(e) return (e.q or 0) - (e.s or 0) end
ns.LotLeft = left

function ns.RecordBuy(itemID, qty, unit, manual, opts)
    if not (itemID and qty and qty > 0 and unit) then return end
    opts = opts or {}
    local when = opts.t or time()
    if opts.src == "mail" and alreadyRecorded(itemID, qty, unit, when) then return end
    table.insert(MyFA_DB.ledger, { t = when, k = "buy", id = itemID, q = qty, u = math.floor(unit), m = manual or nil,
                                   c = ns.CharKey(), src = opts.src })
    MyFA_DB.alerted[itemID] = nil
    ns.FillItemMeta(itemID)
    ns.Print(string.format("tracking %d %s bought at %s each%s. I'll alert you when it's worth selling.",
        qty, ns.ItemName(itemID), ns.Money(unit), opts.src == "mail" and " (from your Auction House mail)" or ""))
    MyFA_DB.lastBuyT = time()
    if ns.RefreshPanel then ns.RefreshPanel() end
end

function ns.ForgetFlip(itemID)
    local n = 0
    for _, e in ipairs(MyFA_DB.ledger) do
        if e.k == "buy" and e.id == itemID and not e.x then e.x = true; n = n + 1 end
    end
    MyFA_DB.alerted[itemID] = nil
    ns.Print(n > 0 and ("stopped tracking " .. ns.ItemName(itemID) .. ".") or ("not tracking " .. ns.ItemName(itemID) .. "."))
    if ns.RefreshPanel then ns.RefreshPanel() end
end

-- capture purchases made through any Auction House window -------------------------

local cap      -- commodity purchase in progress { id, q, u, total }
local itemCap  -- single-item buyout in progress { auction, id, u }

local function hook(tbl, name, fn)
    if tbl and type(tbl[name]) == "function" and hooksecurefunc then
        hooksecurefunc(tbl, name, fn)
    end
end

hook(C_AuctionHouse, "StartCommoditiesPurchase", function(itemID, qty)
    cap = { id = itemID, q = qty }
end)
hook(C_AuctionHouse, "ConfirmCommoditiesPurchase", function(itemID, qty)
    if cap and cap.id == itemID then cap.q = qty or cap.q end
end)
hook(C_AuctionHouse, "PlaceBid", function(auctionID, bid)
    local id
    if C_AuctionHouse.GetAuctionInfoByID then
        local ok, info = pcall(C_AuctionHouse.GetAuctionInfoByID, auctionID)
        if ok and info then
            id = (info.itemKey and info.itemKey.itemID) or info.itemID
            if not id and info.itemLink then id = tonumber(info.itemLink:match("item:(%d+)")) end
        end
    end
    itemCap = { auction = auctionID, id = id, u = bid }
end)

local ev = CreateFrame("Frame")
for _, e in ipairs({ "COMMODITY_PRICE_UPDATED", "COMMODITY_PURCHASE_SUCCEEDED", "COMMODITY_PURCHASE_FAILED",
                     "AUCTION_HOUSE_PURCHASE_COMPLETED", "AUCTION_HOUSE_SHOW", "PLAYER_LOGIN" }) do
    pcall(ev.RegisterEvent, ev, e)
end
ev:SetScript("OnEvent", function(_, event, a1, a2)
    if event == "COMMODITY_PRICE_UPDATED" then
        if cap then cap.u, cap.total = a1, a2 end
    elseif event == "COMMODITY_PURCHASE_SUCCEEDED" then
        if cap and cap.u then
            local unit = (cap.total and cap.q and cap.q > 0) and (cap.total / cap.q) or cap.u
            ns.RecordBuy(cap.id, cap.q, unit)
        end
        cap = nil
    elseif event == "COMMODITY_PURCHASE_FAILED" then
        cap = nil
    elseif event == "AUCTION_HOUSE_PURCHASE_COMPLETED" then
        if itemCap and itemCap.id and (a1 == nil or a1 == itemCap.auction) then
            ns.RecordBuy(itemCap.id, 1, itemCap.u)
        end
        itemCap = nil
    elseif event == "AUCTION_HOUSE_SHOW" then
        C_Timer.After(1, function() ns.CheckFlips() end)
    elseif event == "PLAYER_LOGIN" then
        ns.ImportFromDesk()
        C_Timer.After(6, function() ns.CheckFlips() end)
    end
end)

-- flips added or removed in MyFA Desk arrive through Targets.lua --------------------------

function ns.ImportFromDesk()
    local t = MyFA_Targets
    if not (t and MyFA_DB) then return end
    MyFA_DB.imported = MyFA_DB.imported or {}
    MyFA_DB.forgotten = MyFA_DB.forgotten or {}
    local added = 0
    for _, e in ipairs(t.imports or {}) do
        if e.mid and e.id and e.q and e.u and not MyFA_DB.imported[e.mid] then
            table.insert(MyFA_DB.ledger, { t = e.t or time(), k = "buy", id = e.id, q = e.q, u = e.u, m = true, mid = e.mid })
            MyFA_DB.imported[e.mid] = true
            ns.FillItemMeta(e.id)
            added = added + 1
        end
    end
    local removed = 0
    for _, f in ipairs(t.forgets or {}) do
        if f.id and f.t and (MyFA_DB.forgotten[f.id] or 0) < f.t then
            for _, e in ipairs(MyFA_DB.ledger) do
                if e.k == "buy" and e.id == f.id and e.t <= f.t then e.x = true end
            end
            MyFA_DB.forgotten[f.id] = f.t
            MyFA_DB.alerted[f.id] = nil
            removed = removed + 1
        end
    end
    if added > 0 or removed > 0 then
        ns.Print(string.format("synced with MyFA Desk: %d flip%s added, %d removed.", added, added == 1 and "" or "s", removed))
    end
end

-- purchases since a character last opened the mailbox are still on their way there
local function inTransit(itemID, list)
    local n = 0
    for _, e in ipairs(list) do
        if e.src ~= "mail" and not e.m then
            local c = MyFA_DB.chars[e.c or ns.CharKey()]
            if not c or (e.t or 0) > (c.mailT or 0) then n = n + left(e) end
        end
    end
    return n
end

-- positions: what you still hold from your purchases ---------------------------------

local function cutRate()
    local t = MyFA_Targets
    return (t and t.cut) or 0.05
end

function ns.Positions()
    if not MyFA_DB then return {} end
    local since = time() - KEEP_DAYS * DAY
    local buys = {}
    for _, e in ipairs(MyFA_DB.ledger) do
        if e.k == "buy" and not e.x and e.t >= since and e.id and e.q and e.u and left(e) > 0 then
            local list = buys[e.id]
            if not list then list = {}; buys[e.id] = list end
            list[#list + 1] = e
        end
    end
    local realm = MyFA_DB.realms[ns.RealmKey()]
    local scan = realm and realm.items or {}
    local desk = MyFA_Targets and MyFA_Targets.flips or {}
    local roi = MyFA_DB.settings.roi or 0.15
    local cut = cutRate()
    local risk = MyFA_Targets and MyFA_Targets.risk or {}
    local out = {}
    for itemID, list in pairs(buys) do
        local owned, parts = ns.Owned(itemID)
        local bought = 0
        for _, e in ipairs(list) do bought = bought + left(e) end
        local transit = inTransit(itemID, list)
        if transit > 0 then parts[#parts + 1] = { "on its way", "mail", transit } end
        local hold = math.min(owned + transit, bought)
        if hold > 0 then
            -- you sell your oldest first, so what you still hold is your newest purchases
            table.sort(list, function(a, b) return a.t > b.t end)
            local need, spent = hold, 0
            for _, e in ipairs(list) do
                local take = math.min(need, left(e))
                spent = spent + take * e.u
                need = need - take
                if need <= 0 then break end
            end
            local cost = spent / hold
            local s = scan[itemID]
            local now = s and s.m
            local d = desk[itemID]
            -- lowest listing price that clears your ROI, after the cut and the deposits you tend to lose on relists
            local target = math.ceil((cost * (1 + roi) + (risk[itemID] or 0)) / (1 - cut))
            if d and d.target and d.target > target then target = d.target end
            local net = now and (now * (1 - cut) - cost - (risk[itemID] or 0)) or nil
            out[#out + 1] = {
                id = itemID, name = ns.ItemName(itemID), qty = hold, cost = cost, now = now, target = target,
                pl = net and net * hold or nil, ready = now ~= nil and now >= target,
                where = ns.WhereText(parts, 3), parts = parts, since = list[#list].t, why = d and d.note or nil,
            }
        end
    end
    table.sort(out, function(a, b)
        if a.ready ~= b.ready then return a.ready end
        return (a.pl or -1e12) > (b.pl or -1e12)
    end)
    return out
end

-- alerts ------------------------------------------------------------------------------

local function alert(text)
    if RaidNotice_AddMessage and RaidWarningFrame then
        RaidNotice_AddMessage(RaidWarningFrame, text, ChatTypeInfo and ChatTypeInfo["RAID_WARNING"] or { r = 1, g = 0.82, b = 0 })
    end
    if PlaySound then
        pcall(PlaySound, (SOUNDKIT and (SOUNDKIT.RAID_WARNING or SOUNDKIT.READY_CHECK)) or 8959, "Master")
    end
end

function ns.CheckFlips(quiet)
    if not MyFA_DB or not MyFA_DB.settings.alerts then return end
    local ready = {}
    for _, p in ipairs(ns.Positions()) do
        local prev = MyFA_DB.alerted[p.id]
        if p.ready then
            local fresh = not prev or (p.now >= prev.p * 1.1) or (time() - prev.t > 12 * 3600)
            if fresh then
                ready[#ready + 1] = p
                MyFA_DB.alerted[p.id] = { p = p.now, t = time() }
            end
        elseif prev then
            MyFA_DB.alerted[p.id] = nil
        end
    end
    if #ready == 0 then return end
    local first = ready[1]
    alert(string.format("MyFA: sell %s now (+%s)", first.name, ns.Money(first.pl or 0)):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""))
    for _, p in ipairs(ready) do
        ns.Print(string.format("%sSELL|r %s x%d: lowest is %s, you paid %s each. +%s after the cut. %s(%s)|r",
            GREEN, p.name, p.qty, ns.Money(p.now), ns.Money(p.cost), ns.Money(p.pl or 0), MUTED, p.where))
        if p.why then ns.Print(MUTED .. p.why .. "|r") end
    end
    if ns.RefreshPanel then ns.RefreshPanel() end
end
