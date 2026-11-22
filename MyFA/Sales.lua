-- MyFA Sales: what happened to what you posted.
-- Records deposits when you post, reads "Auction successful", "Auction expired" and "Auction cancelled" mails
-- (plus "Auction won" for purchases), closes your flips with the real profit, and works out how often each item sells.
local ADDON, ns = ...

local DAY = 86400
local MAIL_DAYS = 30          -- Auction House mail lasts 30 days; used to work out when a mail was sent
local KEEP_SALES_DAYS = 365
local GREEN, RED, MUTED, GOLDC = "|cff6fd08a", "|cffe8786b", "|cffa9a59a", "|cffd9b45a"
local clock = GetTime or function() return time() end

-- deposit as a share of the vendor price when MyFA hasn't seen you post yet (8-hour posts, classic rule)
local DEFAULT_RATE = { home = 0.20, neutral = 1.00 }

local function hook(tbl, name, fn)
    if tbl and type(tbl[name]) == "function" and hooksecurefunc then
        hooksecurefunc(tbl, name, fn)
    end
end

local function vendorPrice(id)
    local meta = id and MyFA_DB.items[id]
    return meta and meta.v or 0
end

-- what's listed on the Auction House, per character and per Auction House -------------------------

function ns.AdjustListed(charKey, kind, id, delta)
    if not (id and delta and delta ~= 0) then return end
    local c = MyFA_DB.chars[charKey]
    if not c then return end
    c.listed = c.listed or {}
    local l = c.listed[kind or "home"]
    if not l then l = { items = {}, t = 0 }; c.listed[kind or "home"] = l end
    l.items[id] = math.max(0, (l.items[id] or 0) + delta)
    if l.items[id] == 0 then l.items[id] = nil end
end

function ns.SnapshotOwnedAuctions()
    local AH = C_AuctionHouse
    if not (AH and AH.GetOwnedAuctions) then return end
    local ok, list = pcall(AH.GetOwnedAuctions)
    if not ok or type(list) ~= "table" then return end
    local active = (Enum and Enum.AuctionStatus and Enum.AuctionStatus.Active) or 0
    local items, auctions = {}, {}
    for _, a in ipairs(list) do
        local id = a.itemKey and a.itemKey.itemID
        if not id and a.itemLink then id = tonumber(a.itemLink:match("item:(%d+)")) end
        if id and (a.status == nil or a.status == active) then
            local q = a.quantity or 1
            items[id] = (items[id] or 0) + q
            ns.FillItemMeta(id)
            -- commodities report the price per unit; single items the price of the auction
            local unit = a.buyoutAmount and (ns.IsCommodity(id) and a.buyoutAmount or math.floor(a.buyoutAmount / math.max(q, 1)))
            auctions[#auctions + 1] = { aid = a.auctionID, id = id, q = q, u = unit, tl = a.timeLeftSeconds }
        end
    end
    local c = ns.Char()
    c.listed = c.listed or {}
    -- remember when each auction was first seen, for auctions posted where MyFA couldn't see the post
    local prev = c.listed[ns.AHKind()]
    local first = {}
    for _, a in ipairs(auctions) do
        if a.aid then first[a.aid] = (prev and prev.first and prev.first[a.aid]) or time() end
    end
    c.listed[ns.AHKind()] = { items = items, auctions = auctions, t = time(), first = first }
end

-- posting: record what you listed and what the deposit was ------------------------------------------

local pendingDeposit = {}   -- posts waiting for the gold change that tells us the deposit
local lastMoney

local function itemIDFrom(loc)
    if loc and C_Item and C_Item.GetItemID then
        local ok, id = pcall(C_Item.GetItemID, loc)
        if ok and id then return id end
    end
end

local function learnRate(p)
    local v = vendorPrice(p.id)
    local dep = p.dep or p.dc
    if not (dep and v > 0 and p.q and p.q > 0) then return end
    local r = dep / (v * p.q)
    for _, key in ipairs({ p.a .. ":" .. tostring(p.d), p.a }) do
        local old = MyFA_DB.depRate[key]
        MyFA_DB.depRate[key] = old and (old * 0.7 + r * 0.3) or r
    end
end

local function recordPost(loc, duration, qty, unit, commodity)
    local id = itemIDFrom(loc)
    if not id or not qty or qty <= 0 then return end
    local AH = C_AuctionHouse
    local p = { t = time(), id = id, q = qty, u = unit and math.floor(unit) or nil, d = duration,
                c = ns.CharKey(), a = ns.AHKind() }
    local ok, d
    if commodity and AH.CalculateCommodityDeposit then
        ok, d = pcall(AH.CalculateCommodityDeposit, id, duration, qty)
    elseif AH.CalculateItemDeposit then
        ok, d = pcall(AH.CalculateItemDeposit, loc, duration, qty)
    end
    if ok and type(d) == "number" and d > 0 then
        p.dc = d
        learnRate(p)
    else
        pendingDeposit[#pendingDeposit + 1] = { p = p, at = clock() }
    end
    ns.FillItemMeta(id)
    table.insert(MyFA_DB.posts, p)
    ns.AdjustListed(p.c, p.a, id, qty)
    if ns.RefreshPanel then ns.RefreshPanel() end
end

hook(C_AuctionHouse, "PostCommodity", function(loc, duration, qty, unitPrice)
    recordPost(loc, duration, qty, unitPrice, true)
end)
hook(C_AuctionHouse, "PostItem", function(loc, duration, qty, bid, buyout)
    recordPost(loc, duration, qty or 1, buyout or bid, false)
end)

-- the gold you lose right after posting is the deposit
local function onMoney()
    local now = GetMoney and GetMoney() or 0
    local drop = (lastMoney or now) - now
    lastMoney = now
    if drop <= 0 then return end
    while pendingDeposit[1] and clock() - pendingDeposit[1].at > 15 do table.remove(pendingDeposit, 1) end
    local e = table.remove(pendingDeposit, 1)
    if e then
        e.p.dep = drop
        learnRate(e.p)
    end
end

-- mail ------------------------------------------------------------------------------------------------

local function toPattern(fmt, fallback)
    local p = (type(fmt) == "string" and fmt ~= "") and fmt or fallback
    p = p:gsub("([%(%)%.%%%+%-%*%?%[%]%^%$])", "%%%1")
    p = p:gsub("%%%%s", "(.+)")
    return "^" .. p .. "$"
end
local EXPIRED = toPattern(AUCTION_EXPIRED_MAIL_SUBJECT, "Auction expired: %s")
local CANCELLED = toPattern(AUCTION_REMOVED_MAIL_SUBJECT, "Auction cancelled: %s")

local function idForName(name)
    if not name then return nil end
    for id, meta in pairs(MyFA_DB.items) do
        if meta.n == name then return id end
    end
end

-- each mail counts once: same kind and contents, sent within 10 minutes of a mail already counted
local function alreadySeen(kind, sig, sent, used)
    local key = kind .. "|" .. sig
    local list = MyFA_DB.mailSeen2[key]
    if list then
        for idx, s in ipairs(list) do
            local tag = key .. "#" .. idx
            if not used[tag] and math.abs(s - sent) <= 600 then
                used[tag] = true
                return true
            end
        end
    else
        list = {}
        MyFA_DB.mailSeen2[key] = list
    end
    list[#list + 1] = sent
    used[key .. "#" .. #list] = true
    return false
end

local function firstAttachment(i)
    for j = 1, (ATTACHMENTS_MAX_RECEIVE or 16) do
        local name, id, _, n = GetInboxItem(i, j)
        if id then return id, n or 1, name end
    end
end

-- outcomes --------------------------------------------------------------------------------------------

local batch   -- what one mailbox read found, printed as a short summary at the end

local function postLeft(p) return (p.q or 0) - (p.rq or 0) end

local function matchPost(o)
    local best
    for _, p in ipairs(MyFA_DB.posts) do
        if p.id == o.id and p.c == o.c and postLeft(p) > 0 and (p.t or 0) <= (o.t or 0) + 60 then
            if o.q and postLeft(p) == o.q then return p end
            best = best or p
        end
    end
    return best
end

function ns.EstimateDeposit(id, qty, kind, duration)
    kind = kind or "home"
    local rate = (duration and MyFA_DB.depRate[kind .. ":" .. tostring(duration)]) or MyFA_DB.depRate[kind] or DEFAULT_RATE[kind] or 0.2
    return math.floor(vendorPrice(id) * (qty or 1) * rate + 0.5)
end

-- o = { k = "sold"|"expired"|"cancelled", id, q, g = gross, cut, t, c, a }
function ns.RecordOutcome(o)
    o.c = o.c or ns.CharKey()
    o.t = o.t or time()
    local post = o.id and matchPost(o)
    if post then
        if not o.q then o.q = postLeft(post) end
        post.rq = (post.rq or 0) + o.q
        if postLeft(post) <= 0 then post.r = o.k end
        o.a = o.a or post.a
    end
    o.q = o.q or 1
    if o.k == "sold" then
        if not o.a then o.a = ((o.g or 0) > 0 and (o.cut or 0) / o.g > 0.1) and "neutral" or "home" end
        -- close what you bought, oldest first
        local lots = {}
        for _, e in ipairs(MyFA_DB.ledger) do
            if e.k == "buy" and e.id == o.id and o.id and not e.x and (e.t or 0) <= o.t + 60 and ns.LotLeft(e) > 0 then
                lots[#lots + 1] = e
            end
        end
        table.sort(lots, function(a, b) return (a.t or 0) < (b.t or 0) end)
        local need, cost, matched = o.q, 0, 0
        for _, e in ipairs(lots) do
            local take = math.min(need, ns.LotLeft(e))
            e.s = (e.s or 0) + take
            cost = cost + take * (e.u or 0)
            matched = matched + take
            need = need - take
            if need <= 0 then break end
        end
        o.mq, o.cost = matched > 0 and matched or nil, matched > 0 and cost or nil
        if o.id then MyFA_DB.alerted[o.id] = nil end
    else
        local dep = post and (post.dep or post.dc)
        if dep and post.q and post.q > 0 then
            o.lost = math.floor(dep * o.q / post.q + 0.5)
        else
            o.lost = ns.EstimateDeposit(o.id, o.q, o.a, post and post.d)
            o.est = true
        end
    end
    o.a = o.a or "home"
    if o.id then ns.AdjustListed(o.c, o.a, o.id, -o.q) end
    table.insert(MyFA_DB.sales, o)
    if batch then batch[#batch + 1] = o end
    return o
end

-- reading the mailbox ---------------------------------------------------------------------------------

local function readBuyer(i, itemName, bid, count, sent, used)
    local itemID, attached
    for j = 1, (ATTACHMENTS_MAX_RECEIVE or 16) do
        local name, id, _, n = GetInboxItem(i, j)
        if id and (name == itemName or not itemID) then itemID, attached = id, n end
    end
    itemID = itemID or idForName(itemName)
    count = (count and count > 0) and count or attached or 1
    if not itemID then return end
    local oldKey = string.format("%s|%d|%d|%d", itemName, bid, count, math.floor(sent / 900))  -- 1.5.2's key
    if alreadySeen("won", string.format("%s|%d|%d", itemName, bid, count), sent, used) then return end
    if MyFA_DB.mailSeen and MyFA_DB.mailSeen[oldKey] then return end
    ns.RecordBuy(itemID, count, bid / count, nil, { src = "mail", t = sent })
end

local function summarize(found)
    local sold, other, otherNet, lostN, lost = {}, 0, 0, 0, 0
    for _, o in ipairs(found) do
        if o.k == "sold" then
            if o.mq then sold[#sold + 1] = o else other = other + 1; otherNet = otherNet + (o.g or 0) - (o.cut or 0) end
        else
            lostN = lostN + 1
            lost = lost + (o.lost or 0)
        end
    end
    for n, o in ipairs(sold) do
        if n > 5 then ns.Print(string.format("...and %d more flips sold. /myfa profit for totals.", #sold - 5)); break end
        local net = (o.g or 0) - (o.cut or 0)
        local share = net * o.mq / o.q
        local profit = share - (o.cost or 0)
        local open = 0
        for _, p in ipairs(ns.Positions()) do if p.id == o.id then open = p.qty end end
        ns.Print(string.format("%sSOLD|r %d %s for %s after the cut: %s%s|r on your flip (paid %s each).%s",
            GREEN, o.q, ns.ItemName(o.id), ns.Money(net), profit >= 0 and (GREEN .. "+") or RED, ns.Money(profit),
            ns.Money(o.cost / o.mq), open > 0 and string.format(" %s%d still held.|r", MUTED, open) or " Flip closed."))
    end
    if other > 0 then
        ns.Print(string.format("sold %d other auction%s for %s after the cut.", other, other == 1 and "" or "s", ns.Money(otherNet)))
    end
    if lostN > 0 then
        ns.Print(string.format("%d auction%s expired or %s cancelled: about %s in deposits lost.",
            lostN, lostN == 1 and "" or "s", lostN == 1 and "was" or "were", ns.Money(lost)))
        -- items that keep coming back
        local warned = {}
        for _, o in ipairs(found) do
            if o.k ~= "sold" and o.id and not warned[o.id] then
                warned[o.id] = true
                local st = ns.SellStats(o.id)
                if st.listings >= 3 and st.rate < 0.4 then
                    ns.Print(string.format("%s%s has sold only %d%% of what you listed (%d tries). List it lower or stop listing it.|r",
                        GOLDC, ns.ItemName(o.id), math.floor(st.rate * 100 + 0.5), st.listings))
                end
            end
        end
    end
end

function ns.ReadAuctionMail()
    if not (GetInboxNumItems and GetInboxHeaderInfo and MyFA_DB) then return end
    local now, used = time(), {}
    batch = {}
    for i = 1, GetInboxNumItems() or 0 do
        local _, _, _, subject, _, _, daysLeft = GetInboxHeaderInfo(i)
        daysLeft = daysLeft or MAIL_DAYS
        -- the mail lasts 30 days, so this is when it was sent; stable across sessions for de-duplication
        local sent = math.min(now, math.floor(now + daysLeft * DAY - MAIL_DAYS * DAY))
        local invoiceType, itemName, bid, consignment, count
        if GetInboxInvoiceInfo then
            local ok, a, b, _, d, _, _, g, _, _, _, k = pcall(GetInboxInvoiceInfo, i)
            if ok then invoiceType, itemName, bid, consignment, count = a, b, d, g, k end
        end
        if invoiceType == "buyer" and itemName and bid and bid > 0 then
            readBuyer(i, itemName, bid, count, sent, used)
        elseif invoiceType == "seller" and itemName and bid and bid > 0 then
            -- "seller_temp_invoice" (money still on its way) is skipped: the final mail follows
            local sig = string.format("%s|%d|%s", itemName, bid, tostring(count or ""))
            if not alreadySeen("sold", sig, sent, used) then
                local id = idForName(itemName)
                ns.RecordOutcome({ k = "sold", id = id, n = id and nil or itemName, q = (count and count > 0) and count or nil,
                                   g = bid, cut = consignment or 0, t = sent })
            end
        elseif not invoiceType and subject then
            local kind = (subject:match(EXPIRED) and "expired") or (subject:match(CANCELLED) and "cancelled")
            if kind then
                local id, n, name = firstAttachment(i)
                id = id or idForName(subject:match(EXPIRED) or subject:match(CANCELLED))
                -- once you take the item out, the mail has nothing left to tell us; it was counted when it arrived
                if id then
                    local sig = string.format("%d|%d", id, n or 1)
                    if not alreadySeen(kind, sig, sent, used) then
                        ns.RecordOutcome({ k = kind, id = id, q = n or 1, t = sent })
                    end
                end
            end
        end
    end
    local found = batch
    batch = nil
    if #found > 0 then
        summarize(found)
        if ns.RefreshPanel then ns.RefreshPanel() end
    end
    -- forget old entries
    for key, list in pairs(MyFA_DB.mailSeen2) do
        for idx = #list, 1, -1 do
            if now - list[idx] > 40 * DAY then table.remove(list, idx) end
        end
        if #list == 0 then MyFA_DB.mailSeen2[key] = nil end
    end
    if MyFA_DB.mailSeen then
        for key, t in pairs(MyFA_DB.mailSeen) do
            if now - t > 40 * DAY then MyFA_DB.mailSeen[key] = nil end
        end
    end
end
ns.ReadPurchaseMail = ns.ReadAuctionMail  -- older name

-- stats -----------------------------------------------------------------------------------------------

-- how much of what you listed actually sold: units sold / units listed, plus deposits lost
function ns.SellStats(id)
    local st = { sold = 0, units = 0, listings = 0, lost = 0, rate = 0 }
    for _, o in ipairs(MyFA_DB.sales) do
        if o.id == id then
            st.units = st.units + (o.q or 0)
            st.listings = st.listings + 1
            if o.k == "sold" then st.sold = st.sold + (o.q or 0) else st.lost = st.lost + (o.lost or 0) end
        end
    end
    st.rate = st.units > 0 and st.sold / st.units or 0
    return st
end

function ns.CountOutcomes(kind)
    local n = 0
    for _, o in ipairs(MyFA_DB.sales) do if o.k == kind then n = n + 1 end end
    return n
end

-- totals since a time: net = sales after the cut, flip = profit on what you'd bought, own = sales of
-- things you crafted, farmed or looted, lost = deposits lost
function ns.ProfitSince(since)
    local r = { sales = 0, net = 0, flip = 0, own = 0, lost = 0, expired = 0 }
    for _, o in ipairs(MyFA_DB.sales) do
        if (o.t or 0) >= since then
            if o.k == "sold" then
                local net = (o.g or 0) - (o.cut or 0)
                r.sales = r.sales + 1
                r.net = r.net + net
                if o.mq and o.q and o.q > 0 then
                    r.flip = r.flip + net * o.mq / o.q - (o.cost or 0)
                    r.own = r.own + net * (o.q - o.mq) / o.q
                else
                    r.own = r.own + net
                end
            else
                r.lost = r.lost + (o.lost or 0)
                r.expired = r.expired + 1
            end
        end
    end
    r.total = r.flip + r.own - r.lost
    return r
end

function ns.PrintProfit()
    for _, span in ipairs({ { 7, "last 7 days" }, { 30, "last 30 days" } }) do
        local r = ns.ProfitSince(time() - span[1] * DAY)
        if r.sales == 0 and r.expired == 0 then
            ns.Print(span[2] .. ": no sales recorded yet. MyFA reads them from your mailbox.")
        else
            ns.Print(string.format("%s: %d sales for %s after the cut. Flip profit %s%s|r, own stock %s, deposits lost %s%s|r (%d expired or cancelled).",
                span[2], r.sales, ns.Money(r.net), r.flip >= 0 and GREEN or RED, ns.Money(r.flip), ns.Money(r.own),
                r.lost > 0 and RED or MUTED, ns.Money(r.lost), r.expired))
        end
    end
    ns.Print(MUTED .. "Own stock is what you crafted, farmed or looted. MyFA Desk's Profit tab splits it further.|r")
end

-- tidy up old records
local function prune()
    local now = time()
    for i = #MyFA_DB.posts, 1, -1 do
        if now - (MyFA_DB.posts[i].t or 0) > 40 * DAY then table.remove(MyFA_DB.posts, i) end
    end
    for i = #MyFA_DB.sales, 1, -1 do
        if now - (MyFA_DB.sales[i].t or 0) > KEEP_SALES_DAYS * DAY then table.remove(MyFA_DB.sales, i) end
    end
end

-- events ------------------------------------------------------------------------------------------------

local ev = CreateFrame("Frame")
for _, e in ipairs({ "PLAYER_LOGIN", "PLAYER_MONEY", "AUCTION_HOUSE_SHOW",
                     "OWNED_AUCTIONS_UPDATED", "AUCTION_HOUSE_AUCTION_CREATED" }) do
    pcall(ev.RegisterEvent, ev, e)
end
local function queryOwned()
    if C_AuctionHouse and C_AuctionHouse.QueryOwnedAuctions then pcall(C_AuctionHouse.QueryOwnedAuctions, {}) end
end
ev:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_LOGIN" then
        lastMoney = GetMoney and GetMoney() or 0
        prune()
    elseif event == "PLAYER_MONEY" then
        onMoney()
    elseif event == "AUCTION_HOUSE_SHOW" then
        C_Timer.After(1.5, queryOwned)
    elseif event == "AUCTION_HOUSE_AUCTION_CREATED" then
        C_Timer.After(1, queryOwned)
    elseif event == "OWNED_AUCTIONS_UPDATED" then
        ns.SnapshotOwnedAuctions()
        if ns.RefreshPanel then ns.RefreshPanel() end
    end
end)

-- exposed for the offline test harness
ns._recordPost = recordPost
ns._onMoney = onMoney
ns._toPattern = toPattern
