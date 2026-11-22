-- MyFA Post: posting suggestions, filling Blizzard's sell window, and checking your auctions for undercuts.
--
-- Within Blizzard's rules, always:
--   * MyFA never posts, buys or cancels by itself. Posting is your click on Blizzard's Post button; Cancel and Buy
--     are your clicks on MyFA buttons, one click for one action, as the game requires.
--   * Filling in the price, quantity and duration is the same as typing them yourself (Auctionator and TSM do it).
--   * Price checks are ordinary Auction House searches, sent one at a time with a pause between them, only when you
--     press Check prices, and they stop when the Auction House closes.
local ADDON, ns = ...

local GREEN, RED, MUTED, GOLDC, BLUE = "|cff6fd08a", "|cffe8786b", "|cffa9a59a", "|cffd9b45a", "|cff8fb8f0"
local SEARCH_GAP = 1.2      -- seconds between price checks
local SEARCH_TIMEOUT = 5    -- give up on one item after this long
local MAX_CHECKS = 40

ns.live = {}   -- [itemID] = { other = cheapest price from someone else, t = time } from searches you made

local function lowestOther(id)
    local l = ns.live[id]
    if l and time() - l.t < 900 then return l.other, "live", l end
    local realm = MyFA_DB.realms[ns.MarketKey()]
    local s = realm and realm.items and realm.items[id]
    if not s then return nil, nil end
    if s.x then return nil, "scan-only-you" end
    return s.o or s.m, "scan"
end
ns.LowestOther = lowestOther

local DURATION_FALLBACK = { [1] = "short", [2] = "medium", [3] = "long" }
function ns.DurationLabel(d)
    local g = ({ "AUCTION_DURATION_ONE", "AUCTION_DURATION_TWO", "AUCTION_DURATION_THREE" })[d]
    local text = g and _G[g]
    return (type(text) == "string" and text ~= "") and text or DURATION_FALLBACK[d] or tostring(d)
end

local function deposit(id, dur, qty, kind)
    local AH = C_AuctionHouse
    if AH and ns.IsCommodity(id) and AH.CalculateCommodityDeposit then
        local ok, d = pcall(AH.CalculateCommodityDeposit, id, dur, qty)
        if ok and type(d) == "number" then return d, true end
    end
    -- learned from your own posts for this duration, else the general rate
    return ns.EstimateDeposit(id, qty, kind, dur), false
end

local function sellRate(id)
    local t = MyFA_Targets
    local r = t and t.rates and t.rates[id]
    if r then return r end
    local st = ns.SellStats and ns.SellStats(id)
    if st and st.listings >= 2 then return math.max(0.15, st.rate) end
    return 0.6
end

local function bagCount(id)
    local c = MyFA_DB.chars[ns.CharKey()]
    return c and c.bags and c.bags[id] or 0
end

-- what you paid, if it's a flip
local function paid(id)
    for _, p in ipairs(ns.Positions()) do
        if p.id == id then return p.cost end
    end
end

-- The posting plan for one item: price, quantity, duration, deposit, the lowest price worth posting at, and warnings.
function ns.PostPlan(id, desk)
    local kind = ns.AHKind()
    local cut = ns.CutRate(kind)
    local realm = MyFA_DB.realms[ns.MarketKey()]
    local s = realm and realm.items and realm.items[id]
    local other, source = lowestOther(id)
    local v = MyFA_DB.items[id] and MyFA_DB.items[id].v or 0
    local cost = paid(id)
    local risk = (kind == "home" and MyFA_Targets and MyFA_Targets.risk and MyFA_Targets.risk[id]) or 0
    local plan = { id = id, kind = kind, notes = {}, other = other, source = source, cost = cost }

    -- the floor: below this you lose money on a flip, or a vendor pays more
    local floor = math.ceil((v + risk) / (1 - cut))
    if cost then floor = math.max(floor, math.ceil((cost + risk) / (1 - cut))) end
    plan.floor = floor

    local price = other
    if not price and desk and desk.price and desk.price > 0 then price = desk.price end
    if not price and s then price = s.p or s.m end
    if source == "scan-only-you" then
        plan.notes[#plan.notes + 1] = "Only your own auctions were listed in the last scan, so there's no one to match."
    end
    if price and desk and desk.price and kind == "home" and price < desk.price * 0.8 then
        price = desk.price
        plan.notes[#plan.notes + 1] = "The lowest listing looks dumped. This is the usual price; post and wait, or hold."
    end
    if not price then
        plan.price = nil
        plan.notes[#plan.notes + 1] = "No price data yet. Press Check prices, or scan."
        return plan
    end
    if price < floor then
        plan.below = true
        plan.notes[#plan.notes + 1] = string.format("The lowest is %s, under your floor of %s%s. Posting at the floor means waiting.",
            ns.Money(price), ns.Money(floor), cost and " (what you paid, after the cut)" or " (vendor price, after the cut)")
        price = floor
    end
    plan.price = math.floor(price)

    -- how many: don't flood a market with more than about half of what's listed
    local have = bagCount(id)
    local qty = have
    if ns.IsCommodity(id) then
        local depth = s and s.q or 0
        local cap = math.max(MyFA_DB.items[id] and MyFA_DB.items[id].s or 20, math.floor(depth * 0.5))
        if have > cap and depth > 0 then
            qty = cap
            plan.notes[#plan.notes + 1] = string.format("Post %d now and the rest later: only %d are listed, so more would sit unsold.", cap, depth)
        end
    else
        qty = math.min(have, 1)
    end
    plan.qty, plan.have = qty, have

    -- how long: the longest duration whose deposit you can afford to lose, given how often it sells for you
    local p = sellRate(id)
    local proceeds = plan.price * math.max(qty, 1) * (1 - cut)
    local chosen
    for d = 3, 1, -1 do
        local dep = deposit(id, d, math.max(qty, 1), kind)
        if dep * (1 - p) <= 0.03 * proceeds then chosen = d; break end
    end
    plan.dur = chosen or 1
    plan.deposit = deposit(id, plan.dur, math.max(qty, 1), kind)
    plan.rate = p
    -- warn when the deposits you'd expect to lose eat into the profit
    local expectedLoss = plan.deposit * (1 - p) / p
    local margin = proceeds - (cost or 0) * math.max(qty, 1)
    if expectedLoss > 0.1 * math.max(margin, 1) then
        plan.warn = string.format("Deposit %s is high for something that sells about %d%% of the time: expect to lose about %s relisting it.%s",
            ns.Money(plan.deposit), math.floor(p * 100 + 0.5), ns.Money(expectedLoss),
            v > 0 and (" A vendor pays " .. ns.Money(v * math.max(qty, 1)) .. ".") or "")
    end
    return plan
end

function ns.PlanText(plan)
    if not plan.price then return plan.notes[1] or "No price yet." end
    return string.format("post %d at %s, %s", plan.qty, ns.Money(plan.price), ns.DurationLabel(plan.dur))
end

-- filling Blizzard's sell window (you press Post) --------------------------------------------------

local function findInBags(id)
    for bag = 0, (NUM_BAG_SLOTS or 4) + (NUM_REAGENTBAG_SLOTS or 0) do
        local ok, slots = pcall(C_Container.GetContainerNumSlots, bag)
        for slot = 1, (ok and slots or 0) do
            local info = C_Container.GetContainerItemInfo(bag, slot)
            if info and info.itemID == id and not info.isLocked then return bag, slot end
        end
    end
end

local function tryCall(obj, names, ...)
    if not obj then return false end
    for _, n in ipairs(names) do
        if type(obj[n]) == "function" then
            if pcall(obj[n], obj, ...) then return true end
        end
    end
    return false
end

local filling   -- { id, plan, frame } until Blizzard's own price search for that item comes back

local function applyPlan(f, plan)
    local okPrice = tryCall(f.PriceInput, { "SetAmount" }, plan.price) or tryCall(f, { "SetPrice", "SetUnitPrice" }, plan.price)
    local okQty = (plan.qty or 0) <= 1 or tryCall(f.QuantityInput, { "SetQuantity" }, plan.qty) or tryCall(f, { "SetQuantity" }, plan.qty)
    local dd = f.Duration or f.DurationDropdown or f.DurationDropDown
    local okDur = tryCall(dd, { "SetDuration", "SetValue", "SetSelectedValue" }, plan.dur) or tryCall(f, { "SetDuration" }, plan.dur)
    tryCall(f, { "UpdatePostButtonState", "UpdateTotalPrice", "OnQuantityChanged" })
    return okPrice, okQty, okDur
end

local function chatPlan(plan, filled)
    ns.Print(string.format("%s%s|r: %s. Deposit about %s.%s", GOLDC, ns.ItemName(plan.id), ns.PlanText(plan),
        ns.Money(plan.deposit or 0), filled and " Filled in: check it and press Post." or
        " Type these into your Auction House window and press Post."))
    for _, n in ipairs(plan.notes) do ns.Print(MUTED .. n .. "|r") end
    if plan.warn then ns.Print(RED .. plan.warn .. "|r") end
end

function ns.PrepareSell(entry)
    if not (AuctionHouseFrame and AuctionHouseFrame:IsShown()) then ns.Print("open the Auction House to post."); return end
    local id = entry.id
    local plan = ns.PostPlan(id, entry)
    if not plan.price then chatPlan(plan, false); return end
    local bag, slot = findInBags(id)
    if not bag then
        ns.Print(ns.ItemName(id) .. " isn't in this character's bags. " .. (entry.loc and ("It's here: " .. entry.loc .. ".") or ""))
        return
    end
    local commodity = ns.IsCommodity(id)
    local AHF = AuctionHouseFrame
    local f = commodity and AHF.CommoditiesSellFrame or AHF.ItemSellFrame
    local ok = f and ItemLocation and pcall(function()
        if AHF.SetDisplayMode and AuctionHouseFrameDisplayMode then
            AHF:SetDisplayMode(commodity and AuctionHouseFrameDisplayMode.CommoditiesSell or AuctionHouseFrameDisplayMode.ItemSell)
        end
        f:SetItem(ItemLocation:CreateFromBagAndSlot(bag, slot))
    end)
    if not ok then chatPlan(plan, false); return end
    local okPrice = applyPlan(f, plan)
    filling = { id = id, entry = entry, frame = f, until_ = time() + 6 }
    -- Blizzard's window looks up the price itself and overwrites it: apply ours again once it has
    C_Timer.After(0.5, function() if filling and filling.id == id then applyPlan(f, ns.PostPlan(id, entry)) end end)
    chatPlan(plan, okPrice)
end

-- price checks for your own auctions --------------------------------------------------------------

local queue, current, ev, waitTimer
local checking = false

local function readResults(id)
    local AH = C_AuctionHouse
    local other, mineAt
    if ns.IsCommodity(id) and AH.GetNumCommoditySearchResults then
        for i = 1, AH.GetNumCommoditySearchResults(id) or 0 do
            local r = AH.GetCommoditySearchResultInfo(id, i)
            if r then
                if (r.numOwnerItems or 0) > 0 and not mineAt then mineAt = r.unitPrice end
                if (r.numOwnerItems or 0) < (r.quantity or 0) and (not other or r.unitPrice < other) then other = r.unitPrice end
            end
        end
    elseif AH.MakeItemKey and AH.GetNumItemSearchResults then
        local key = AH.MakeItemKey(id)
        for i = 1, AH.GetNumItemSearchResults(key) or 0 do
            local r = AH.GetItemSearchResultInfo(key, i)
            local price = r and (r.buyoutAmount or r.bidAmount)
            if r and price then
                if r.containsOwnerItem and not mineAt then mineAt = price end
                if not r.containsOwnerItem and (not other or price < other) then other = price end
            end
        end
    end
    ns.live[id] = { other = other, mine = mineAt, t = time() }
end

local function stopChecks(msg)
    checking, queue, current = false, nil, nil
    if waitTimer then waitTimer:Cancel(); waitTimer = nil end
    if msg then ns.Print(msg) end
    if ns.RefreshPanel then ns.RefreshPanel() end
end

local step
step = function()
    if not checking then return end
    if not (AuctionHouseFrame and AuctionHouseFrame:IsShown()) then stopChecks("price check stopped: the Auction House closed."); return end
    current = table.remove(queue, 1)
    if not current then
        local n = 0
        for _, a in ipairs(ns.MyAuctions()) do if a.status == "undercut" then n = n + 1 end end
        stopChecks(n > 0 and string.format("price check done: %s%d of your auctions are undercut.|r See the Listed tab.", RED, n)
            or "price check done: none of your auctions are undercut.")
        return
    end
    local AH = C_AuctionHouse
    local ok = pcall(AH.SendSearchQuery, AH.MakeItemKey(current), { { sortOrder = (Enum.AuctionHouseSortOrder or {}).Price or 0, reverseSort = false } }, true)
    if not ok then stopChecks("price check stopped: the search didn't go through. Try again in a moment."); return end
    if waitTimer then waitTimer:Cancel() end
    waitTimer = C_Timer.NewTimer(SEARCH_TIMEOUT, function() C_Timer.After(0, step) end)
    if ns.RefreshPanel then ns.RefreshPanel() end
end

function ns.CheckPrices()
    if checking then stopChecks("price check stopped."); return end
    if not (AuctionHouseFrame and AuctionHouseFrame:IsShown()) then ns.Print("open the Auction House first."); return end
    if not (C_AuctionHouse and C_AuctionHouse.SendSearchQuery and C_AuctionHouse.MakeItemKey) then
        ns.Print("this client can't search the Auction House from an addon.")
        return
    end
    queue = {}
    local seen = {}
    for _, a in ipairs(ns.MyAuctions()) do
        if not seen[a.id] and #queue < MAX_CHECKS then seen[a.id] = true; queue[#queue + 1] = a.id end
    end
    if #queue == 0 then ns.Print("you have no auctions here. Open the Auction House's Auctions tab once so MyFA can see them."); return end
    checking = true
    ns.Print(string.format("checking prices for %d item%s, one search every %.1fs. Press Stop to end early.", #queue, #queue == 1 and "" or "s", SEARCH_GAP))
    step()
end
function ns.IsCheckingPrices() return checking, current, queue and #queue or 0 end

-- your auctions, with what the cheapest other seller asks ------------------------------------------

-- where most of the supply sits: the cheapest price level holding a fifth of all listed units
local function wallOf(s)
    if not (s and s.l and #s.l > 0) then return nil end
    local need = math.max(5, (s.q or 0) * 0.2)
    for _, lv in ipairs(s.l) do
        if lv[2] >= need then return lv[1] end
    end
    return s.l[#s.l][1]
end

-- how long you've been trying to sell an item here: back through relists to your last sale
local function listingHistory(id, charKey, kind, auctionsFirst)
    local chain, since, relists = {}, nil, 0
    for _, p in ipairs(MyFA_DB.posts) do
        if p.id == id and p.c == charKey and (p.a or "home") == kind then chain[#chain + 1] = p end
    end
    table.sort(chain, function(a, b) return (a.t or 0) > (b.t or 0) end)
    for _, p in ipairs(chain) do
        if p.r == "sold" then break end
        since = p.t
        if p.r == "expired" or p.r == "cancelled" then relists = relists + 1 end
    end
    if auctionsFirst and (not since or auctionsFirst < since) then since = auctionsFirst end
    return since, relists
end

function ns.MyAuctions()
    local key = ns.CharKey()
    local c = MyFA_DB.chars[key]
    local kind = ns.AHKind()
    local l = c and c.listed and c.listed[kind]
    local now = time()
    local out, byItem = {}, {}
    for _, a in ipairs(l and l.auctions or {}) do
        local g = byItem[a.id]
        if not g then
            g = { id = a.id, name = ns.ItemName(a.id), qty = 0, u = a.u, aids = {}, n = 0 }
            byItem[a.id] = g
            out[#out + 1] = g
        end
        g.qty = g.qty + (a.q or 1)
        g.n = g.n + 1
        if a.u and (not g.u or a.u > g.u) then g.u = a.u end   -- your highest price is the one that gets undercut first
        g.aids[#g.aids + 1] = { aid = a.aid, u = a.u, q = a.q }
        local seen = a.aid and l.first and l.first[a.aid]
        if seen and (not g.firstSeen or seen < g.firstSeen) then g.firstSeen = seen end
        if a.tl then
            local left = a.tl - (now - (l.t or now))
            if not g.left or left < g.left then g.left = math.max(0, left) end
        end
    end
    local realm = MyFA_DB.realms[ns.MarketKey()]
    local deskPrices = MyFA_Targets and MyFA_Targets.prices or {}
    for _, g in ipairs(out) do
        g.since, g.relists = listingHistory(g.id, key, kind, g.firstSeen)
        local other, source = lowestOther(g.id)
        g.other, g.source = other, source
        local s = realm and realm.items and realm.items[g.id]
        g.wall = wallOf(s)
        g.market = (kind == "home" and deskPrices[g.id]) or g.wall
        local plan = ns.PostPlan(g.id)
        g.floor, g.cost = plan.floor, plan.cost
        if other and g.u and other < g.u then
            if other >= (g.floor or 0) then
                g.status, g.repost = "undercut", other
            elseif g.wall and g.wall >= (g.floor or 0) then
                -- a few cheap ones, but most of the supply still sells above your floor
                g.status = "dump"
                g.repost = (g.u > g.wall * 1.15) and g.wall or nil
            else
                -- the market itself moved under what you paid
                g.status, g.repost = "fell", nil
            end
        elseif other or source == "scan-only-you" then
            g.status = "lowest"
        else
            g.status = "unknown"
        end
        -- far above where the item trades: it will just expire
        g.high = g.market and g.u and g.u > g.market * 1.5 and g.status ~= "lowest" or nil
        table.sort(g.aids, function(a, b) return (a.u or 0) > (b.u or 0) end)
    end
    local order = { fell = 0, undercut = 1, dump = 2, unknown = 3, lowest = 4 }
    table.sort(out, function(a, b)
        if a.status ~= b.status then return order[a.status] < order[b.status] end
        return (a.u or 0) * a.qty > (b.u or 0) * b.qty
    end)
    return out
end

-- one line of advice for an auction group, used by the panel tooltip and chat
function ns.AuctionAdvice(g)
    local lines = {}
    local up = g.since and ns.Duration(time() - g.since)
    lines[#lines + 1] = string.format("%d listed at %s each%s%s.", g.qty, ns.Money(g.u or 0),
        up and (", on the Auction House for " .. up) or ", listed before MyFA could see the post",
        (g.relists or 0) == 1 and " (relisted once)" or (g.relists or 0) > 1 and string.format(" (relisted %d times)", g.relists) or "")
    if g.left then lines[#lines + 1] = "Time left: " .. ns.Duration(g.left) .. (g.left <= 0 and " (expired: the mail is on its way)" or "") .. "." end
    if g.status == "undercut" then
        lines[#lines + 1] = "Someone lists it at " .. ns.Money(g.other) .. ". Buyers take theirs first."
        lines[#lines + 1] = "Cancel your auction (one per click), collect it from the mail and post again at " .. ns.Money(g.repost) .. "."
    elseif g.status == "dump" then
        lines[#lines + 1] = string.format("A few are dumped at %s, but most of the supply sits at %s. The cheap ones usually go fast.",
            ns.Money(g.other), ns.Money(g.wall))
        lines[#lines + 1] = g.repost and ("Yours is above that: repost at about " .. ns.Money(g.repost) .. ".")
            or "Yours is in that range: leave it."
        if g.other * 1.15 < g.wall * (1 - ns.CutRate(ns.AHKind())) then
            lines[#lines + 1] = "Buying the cheap ones and relisting them near " .. ns.Money(g.wall) .. " is a flip in itself."
        end
    elseif g.status == "fell" then
        lines[#lines + 1] = string.format("The market fell: most of the supply is now around %s%s.", ns.Money(g.wall or g.other),
            g.cost and (", under the " .. ns.Money(g.cost) .. " you paid") or ", under your floor")
        lines[#lines + 1] = "At " .. ns.Money(g.u or 0) .. " it won't sell, and every relist costs a deposit."
        lines[#lines + 1] = string.format("Either sell near %s and take the loss%s, or take it off the Auction House and hold it until the price recovers.",
            ns.Money(g.wall or g.other), g.cost and (" (about " .. ns.Money(((g.cost or 0) - (g.wall or g.other) * (1 - ns.CutRate(ns.AHKind()))) * g.qty) .. ")") or "")
        local usual = MyFA_Targets and MyFA_Targets.prices and MyFA_Targets.prices[g.id]
        if usual and g.wall and usual > g.wall * 1.2 then
            lines[#lines + 1] = "It usually trades around " .. ns.Money(usual) .. ", so holding may get some of it back."
        end
    elseif g.status == "lowest" then
        lines[#lines + 1] = g.other and ("You're the cheapest; next is " .. ns.Money(g.other) .. ". Leave it.") or "Only you list it. Leave it."
    else
        lines[#lines + 1] = "No price data for it yet. Press Check prices."
    end
    if g.high and g.status ~= "fell" and not g.repost then
        lines[#lines + 1] = string.format("Your price is %d times where it trades (%s): it will expire unsold.",
            math.floor(g.u / g.market + 0.5), ns.Money(g.market))
    end
    lines[#lines + 1] = "Prices from " .. (g.source == "live" and "a live search." or "your last scan. Check prices for live ones.")
    return lines
end

-- Cancel one auction: your click, one auction per click (the game requires that)
function ns.CancelOne(group)
    local a = group and group.aids and group.aids[1]
    if not a then return end
    if not (C_AuctionHouse and C_AuctionHouse.CancelAuction) then ns.Print("this client has no cancel function."); return end
    local cost = C_AuctionHouse.GetCancelCost and select(2, pcall(C_AuctionHouse.GetCancelCost, a.aid))
    local ok = pcall(C_AuctionHouse.CancelAuction, a.aid)
    if ok then
        ns.Print(string.format("cancelled %d %s (%s each). The deposit is lost%s; the items come back by mail. "
            .. "Then use Post on the Sell tab%s.", a.q or 1, ns.ItemName(group.id), ns.Money(a.u or 0),
            type(cost) == "number" and cost > 0 and (" and it costs " .. ns.Money(cost)) or "",
            group.repost and (" at " .. ns.Money(group.repost)) or ""))
    else
        ns.Print("couldn't cancel that auction. Try from the Auction House's Auctions tab.")
    end
end

-- events: results of any search (yours, Blizzard's or another addon's) keep prices fresh --------------

ev = CreateFrame("Frame")
for _, e in ipairs({ "COMMODITY_SEARCH_RESULTS_UPDATED", "ITEM_SEARCH_RESULTS_UPDATED", "AUCTION_HOUSE_CLOSED",
                     "OWNED_AUCTIONS_UPDATED" }) do
    pcall(ev.RegisterEvent, ev, e)
end
local warnedVisit = false
ev:SetScript("OnEvent", function(_, event, arg)
    if event == "AUCTION_HOUSE_CLOSED" then
        if checking then stopChecks() end
        filling, warnedVisit = nil, false
        return
    end
    if event == "OWNED_AUCTIONS_UPDATED" then
        if not warnedVisit then
            warnedVisit = true
            C_Timer.After(0.2, function()
                local n = 0
                local fell = 0
                for _, a in ipairs(ns.MyAuctions()) do
                    if a.status == "undercut" then n = n + 1 elseif a.status == "fell" then fell = fell + 1 end
                end
                if n > 0 then
                    ns.Print(string.format("%s%d of your auctions look undercut|r (from your last scan). Open MyFA's Listed tab, or press Check prices there for live prices.", RED, n))
                end
                if fell > 0 then
                    ns.Print(string.format("%s%d of your auctions are priced far above a market that fell under what you paid.|r See the Listed tab.", RED, fell))
                end
            end)
        end
        return
    end
    local id = arg
    if type(arg) == "table" then id = arg.itemID end
    if not id then return end
    readResults(id)
    if filling and filling.id == id and time() <= filling.until_ then
        local f = filling.frame
        local plan = ns.PostPlan(id, filling.entry)
        C_Timer.After(0.1, function() if plan.price then applyPlan(f, plan) end end)
        ns.Print(string.format("%slive price for %s: %s|r", MUTED, ns.ItemName(id), ns.PlanText(plan)))
        filling = nil
    end
    if checking and id == current then
        if waitTimer then waitTimer:Cancel(); waitTimer = nil end
        C_Timer.After(SEARCH_GAP, step)
    end
    if ns.RefreshPanel then ns.RefreshPanel() end
end)

-- exposed for the offline test harness
ns._readResults = readResults
