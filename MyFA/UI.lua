-- MyFA UI: targets panel beside the Auction House, Search/Buy actions, price tooltips.
local ADDON, ns = ...

local ROWS, ROW_H = 9, 40
local PANEL_W, PANEL_H = 460, 566
local GOLD = { 0.85, 0.71, 0.35 }
local GREEN = "|cff6fd08a"
local RED = "|cffe8796b"
local MUTED = "|cffa9a59a"
local BLUE = "|cff8fb8f0"
local GOLDC = "|cffe3bd62"
local GREY = "|cff9d9d9d"
local PURPLE = "|cffc39bf0"

local function tag(color, text) return color .. text .. "|r  " end

local function num(n)
    n = math.floor(n or 0)
    if BreakUpLargeNumbers then return BreakUpLargeNumbers(n) end
    local s = tostring(n)
    while true do
        local k
        s, k = s:gsub("^(-?%d+)(%d%d%d)", "%1,%2")
        if k == 0 then return s end
    end
end

local panel, rows, tabs = nil, {}, {}

-- what each tab is for, shown under the tab buttons
local TAB_HINT = {
    buys = "Cheap listings worth buying to resell. Right: your profit after reselling. Press Buy, then Confirm.",
    sells = "What to do with what you own. Post fills in Blizzard's sell window with MyFA's price; you press Post there.",
    crafts = "Recipes you know that make a profit. Right: profit per craft. Open a profession window to add recipes.",
    mine = "Things you bought, tracked until you sell them. Right: profit if you sold now. You get an alert when it's time.",
    listed = "Your auctions here. UNDERCUT means someone lists it cheaper. Check prices looks up live prices.",
    gear = "Gear on the Auction House that beats what you wear. Pick class and specs in MyFA Desk's Gear upgrades tab.",
}
local currentTab, offset = "buys", 0
local pending -- { id, qty, max, state = "starting"|"confirm"|"buying", unit, total }

-- helpers --------------------------------------------------------------------

local function targets()
    return MyFA_Targets
end

-- at a neutral Auction House the Buy and Sell lists are the neutral ones
local function list()
    if currentTab == "mine" then return ns.Positions() end
    if currentTab == "listed" then return ns.MyAuctions() end
    if currentTab == "gear" then return ns.GearList() end
    local t = targets()
    if t and ns.AtNeutralAH() and currentTab ~= "crafts" then
        return (t.neutral and t.neutral[currentTab]) or {}
    end
    return (t and t[currentTab]) or {}
end

local function qualityColor(id)
    local meta = MyFA_DB.items[id]
    local q = meta and meta.c
    if q and ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[q] then
        return ITEM_QUALITY_COLORS[q].hex
    end
    return "|cffffffff"
end

local function boughtSince(id, since)
    local n = 0
    for _, e in ipairs(MyFA_DB.ledger) do
        if e.k == "buy" and e.id == id and e.t >= (since or 0) then n = n + e.q end
    end
    return n
end

local function remaining(entry)
    local t = targets()
    return math.max(0, (entry.qty or 0) - boughtSince(entry.id, t and t.generated or 0))
end

local function isCommodity(id)
    if C_AuctionHouse and C_AuctionHouse.GetItemCommodityStatus and Enum and Enum.ItemCommodityStatus then
        local ok, st = pcall(C_AuctionHouse.GetItemCommodityStatus, id)
        if ok and st == Enum.ItemCommodityStatus.Commodity then return true end
        if ok and st == Enum.ItemCommodityStatus.Item then return false end
    end
    local meta = MyFA_DB.items[id]
    return meta ~= nil and (meta.s or 1) > 1
end

local function ahOpen()
    return AuctionHouseFrame and AuctionHouseFrame:IsShown()
end

local function age(ts)
    if not ts then return "never" end
    local m = math.floor((time() - ts) / 60)
    if m < 1 then return "just now" end
    if m < 60 then return m .. " min ago" end
    if m < 48 * 60 then return math.floor(m / 60) .. " h ago" end
    return math.floor(m / 1440) .. " days ago"
end

-- actions --------------------------------------------------------------------

function ns.SearchAH(name)
    if not ahOpen() then ns.Print("open the Auction House to search."); return end
    local ok = pcall(function()
        if AuctionHouseFrame.SetDisplayMode and AuctionHouseFrameDisplayMode then
            AuctionHouseFrame:SetDisplayMode(AuctionHouseFrameDisplayMode.Buy)
        end
        local bar = AuctionHouseFrame.SearchBar
        bar.SearchBox:SetText('"' .. name .. '"')
        bar:StartSearch()
    end)
    if not ok then ns.Print("couldn't drive the AH search box. Search for: " .. name) end
end

local function cancelPending(silent)
    if pending and pending.state ~= "buying" and C_AuctionHouse.CancelCommoditiesPurchase then
        pcall(C_AuctionHouse.CancelCommoditiesPurchase)
    end
    if pending and not silent then ns.Print("purchase cancelled.") end
    pending = nil
end

local function buyClicked(entry)
    if not ahOpen() then ns.Print("open the Auction House to buy."); return end
    if pending and pending.id == entry.id and pending.state == "confirm" then
        pending.state = "buying"
        C_AuctionHouse.ConfirmCommoditiesPurchase(pending.id, pending.qty)
        ns.RefreshPanel()
        return
    end
    if pending then cancelPending(true) end
    local qty = remaining(entry)
    if qty <= 0 then ns.Print("already bought the target amount."); return end
    pending = { id = entry.id, qty = qty, max = entry.max, state = "starting" }
    C_AuctionHouse.StartCommoditiesPurchase(entry.id, qty)
    ns.RefreshPanel()
end

local function onCommodityEvent(event, a1, a2)
    if not pending then return end
    if event == "COMMODITY_PRICE_UPDATED" and pending.state == "starting" then
        local unit, total = a1, a2
        if unit <= pending.max then
            pending.state, pending.unit, pending.total = "confirm", unit, total
        else
            ns.Print(string.format("%s is now %s each, above your max %s. Cancelled.",
                ns.ItemName(pending.id), ns.Money(unit), ns.Money(pending.max)))
            cancelPending(true)
        end
    elseif event == "COMMODITY_PRICE_UNAVAILABLE" then
        ns.Print("not enough " .. ns.ItemName(pending.id) .. " listed at that quantity. Lower the amount or Search.")
        cancelPending(true)
    elseif event == "COMMODITY_PURCHASE_SUCCEEDED" then
        -- Flips.lua records every Auction House purchase, including this one
        pending = nil
    elseif event == "COMMODITY_PURCHASE_FAILED" then
        ns.Print("purchase failed. Prices may have moved; try again.")
        pending = nil
    end
    ns.RefreshPanel()
end

-- layout ---------------------------------------------------------------------

local function makeButton(parent, text, w)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetSize(w, 22)
    b:SetText(text)
    return b
end

local function rowTooltip(self)
    local e = self.entry
    if not e then return end
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    if e.id and (C_Item and C_Item.GetItemInfo and C_Item.GetItemInfo(e.id)) then
        GameTooltip:SetItemByID(e.id)
    else
        GameTooltip:SetText(e.name or "?")
    end
    local steps = {}
    if currentTab == "buys" then
        if e.kind == "vendor" then
            steps = { "1. Press Buy, then Confirm (only offered at " .. ns.Money(e.max) .. " each or less).",
                      "2. Sell them to any vendor.", "Profit: " .. ns.Money(e.profit or 0) .. "." }
        elseif e.kind == "toneutral" or e.kind == "tohome" then
            local there = e.kind == "toneutral" and "a neutral Auction House (Gadgetzan, Booty Bay or Everlook)"
                or "your faction's Auction House"
            steps = { "1. Press Buy, then Confirm (only offered at " .. ns.Money(e.max) .. " each or less).",
                      "2. Take them to " .. there .. ", or mail them to a character parked there.",
                      "3. Post at about " .. ns.Money(e.sell or 0) .. " each.",
                      "Expected profit after that Auction House's cut and likely deposits: " .. ns.Money(e.profit or 0) .. "." }
        else
            steps = { "1. Press Buy. MyFA asks the server for the live price.",
                      "2. Press Confirm. It's only offered at " .. ns.Money(e.max) .. " each or less.",
                      "3. Post them again at about " .. ns.Money(e.sell or 0) .. " each" .. (e.kind == "raid" and " in raid week." or "."),
                      "Expected profit after the cut: " .. ns.Money(e.profit or 0) .. "." }
        end
        if e.sold_day then
            steps[#steps + 1] = string.format("Sells about %s a day on this market%s.",
                e.sold_day >= 10 and string.format("%d", e.sold_day) or string.format("%.1f", e.sold_day),
                e.profit_day and (", so about " .. ns.Money(e.profit_day) .. " profit a day") or "")
        elseif e.kind ~= "vendor" then
            steps[#steps + 1] = "Sales not measured yet: scan twice, at least 20 minutes apart, so MyFA can see what sells."
        end
    elseif currentTab == "sells" then
        if e.action == "ah" then
            local plan = e.plan or ns.PostPlan(e.id, e)
            if plan.price then
                steps = { "Press Post: MyFA puts the item in Blizzard's sell window and fills in:",
                          string.format("   price %s each, quantity %d, %s", ns.Money(plan.price), plan.qty, ns.DurationLabel(plan.dur)),
                          "Check it, then press Post in that window. MyFA never posts for you.",
                          string.format("Deposit about %s. Lowest worth posting at: %s.", ns.Money(plan.deposit or 0), ns.Money(plan.floor or 0)),
                          string.format("Price from %s.", plan.source == "live" and "a live search" or "your last scan") }
                for _, n in ipairs(plan.notes) do steps[#steps + 1] = n end
                if plan.warn then steps[#steps + 1] = "|cffe8786b" .. plan.warn .. "|r" end
            else
                steps = { "Post " .. (e.qty or 0) .. " at " .. ns.Money(e.price) .. " each. Match the lowest price; don't undercut." }
            end
        elseif e.action == "vendor" then steps = { "Sell to any vendor. The Auction House would pay less after the cut." }
        elseif e.action == "craft" then steps = { "Use it to craft " .. (e.into or "?") .. ". That's worth more than selling it raw. See the Craft tab." }
        else steps = { "Keep it for now. MyFA will move it to Sell when it's time." } end
        if e.loc then steps[#steps + 1] = "Where: " .. e.loc end
    elseif currentTab == "crafts" then
        steps = { "Mats cost " .. ns.Money(e.cost) .. ", the result sells for " .. ns.Money(e.value) .. " after the cut.",
                  "Craft it, then post it at today's lowest price." }
    elseif currentTab == "gear" then
        local spec = ns.GearSpecName()
        steps = { string.format("%s upgrade for %s%s.", e.slot or "Gear", spec or "your spec",
                                e.pct and string.format(": scores %d%% higher", e.pct) or ": fills an empty slot"),
                  e.replaces and ("Replaces: " .. e.replaces) or "Nothing worn there now.",
                  "If you swap: " .. (e.stats or "?"),
                  "Cheapest listing: " .. ns.Money(e.price or 0) .. ". Press Search, then buy it in the Auction House window." }
    elseif currentTab == "listed" then
        steps = ns.AuctionAdvice(e)
    elseif currentTab == "mine" then
        steps = { string.format("You paid %s each for %d.", ns.Money(e.cost), e.qty),
                  "Lowest now: " .. (e.now and ns.Money(e.now) or "not listed") .. ". MyFA alerts you at " .. ns.Money(e.target) .. ".",
                  e.ready and "Sell now: post at the lowest price." or "Keep it until the alert.",
                  "Where: " .. (e.where or "?"),
                  e.since and ("Bought " .. ns.Duration(time() - e.since) .. " ago.") or nil }
    end
    if #steps > 0 then
        GameTooltip:AddLine(" ")
        GameTooltip:AddLine("What to do", 0.89, 0.74, 0.38)
        for _, line in ipairs(steps) do GameTooltip:AddLine(line, 1, 1, 1, true) end
    end
    if e.why then
        GameTooltip:AddLine(" ")
        GameTooltip:AddLine(e.why, 0.8, 0.8, 0.8, true)
    end
    GameTooltip:Show()
end

local function buildRow(i)
    local r = CreateFrame("Button", nil, panel.list)
    r:SetSize(PANEL_W - 28, ROW_H)
    r:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_H)

    r.bg = r:CreateTexture(nil, "BACKGROUND")
    r.bg:SetAllPoints()
    r.bg:SetColorTexture(1, 1, 1, i % 2 == 0 and 0.035 or 0)

    r.hl = r:CreateTexture(nil, "HIGHLIGHT")
    r.hl:SetAllPoints()
    r.hl:SetColorTexture(GOLD[1], GOLD[2], GOLD[3], 0.08)

    r.icon = r:CreateTexture(nil, "ARTWORK")
    r.icon:SetSize(28, 28)
    r.icon:SetPoint("LEFT", 6, 0)

    r.name = r:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    r.name:SetPoint("TOPLEFT", r.icon, "TOPRIGHT", 8, -1)
    r.name:SetWidth(146)
    r.name:SetJustifyH("LEFT")
    r.name:SetWordWrap(false)

    r.detail = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    r.detail:SetPoint("BOTTOMLEFT", r.icon, "BOTTOMRIGHT", 8, 1)
    r.detail:SetWidth(212)
    r.detail:SetJustifyH("LEFT")
    r.detail:SetWordWrap(false)

    r.buy = makeButton(r, "Buy", 64)
    r.buy:SetPoint("RIGHT", -4, 0)
    r.search = makeButton(r, "Search", 64)
    r.search:SetPoint("RIGHT", r.buy, "LEFT", -4, 0)

    r.profit = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    r.profit:SetPoint("TOPRIGHT", r, "TOPRIGHT", -144, -7) -- same line as the name, clear of the buttons
    r.profit:SetJustifyH("RIGHT")

    r.search:SetScript("OnClick", function() if r.entry then ns.SearchAH(r.entry.name or ns.ItemName(r.entry.id)) end end)
    r.buy:SetScript("OnClick", function()
        if not r.entry then return end
        if currentTab == "sells" then ns.PrepareSell(r.entry)
        elseif currentTab == "listed" then ns.CancelOne(r.entry)
        else buyClicked(r.entry) end
    end)
    r:SetScript("OnEnter", rowTooltip)
    r:SetScript("OnLeave", function() GameTooltip:Hide() end)
    return r
end

local function updateRow(r, e)
    r.entry = e
    if not e then r:Hide(); return end
    r:Show()
    local icon = (C_Item and C_Item.GetItemIconByID and e.id) and C_Item.GetItemIconByID(e.id) or nil
    r.icon:SetTexture(icon or 134400)
    r.name:SetText(qualityColor(e.id) .. (e.name or ns.ItemName(e.id)) .. "|r")

    r.buy:Hide()
    r.search:Show()
    if currentTab == "buys" then
        local left = remaining(e)
        local kind = (e.kind == "vendor" and "  vendor flip") or (e.kind == "raid" and "  raid stock") or ""
        local label = (e.kind == "vendor" and tag(GREEN, "VENDOR")) or (e.kind == "raid" and tag(BLUE, "RAID"))
            or (e.kind == "snipe" and tag(RED, "SNIPE")) or (e.kind == "toneutral" and tag(PURPLE, "TO NEUTRAL"))
            or (e.kind == "tohome" and tag(PURPLE, "TO " .. string.upper(UnitFactionGroup("player") or "HOME") .. " AH")) or tag(GOLDC, "FLIP")
        local speed = e.sold_day and string.format("  %s~%s/day|r", MUTED, e.sold_day >= 10 and string.format("%d", e.sold_day) or string.format("%.1f", e.sold_day)) or ""
        r.detail:SetText(string.format("%sbuy x%d, max %s each%s", label, left, ns.Money(e.max), speed))
        r.profit:SetText(GREEN .. "+" .. ns.Money(e.profit or 0) .. "|r")
        if isCommodity(e.id) then
            r.buy:Show()
            r.buy:Enable()
            if left <= 0 then
                r.buy:SetText("Done"); r.buy:Disable()
            elseif pending and pending.id == e.id then
                if pending.state == "starting" then r.buy:SetText("..."); r.buy:Disable()
                elseif pending.state == "confirm" then r.buy:SetText("Confirm")
                else r.buy:SetText("Buying"); r.buy:Disable() end
            else
                r.buy:SetText("Buy")
            end
        end
    elseif currentTab == "sells" then
        local what
        if e.action == "vendor" then what = tag(GREY, "VENDOR") .. "sell to a vendor"
        elseif e.action == "craft" then what = tag(GREEN, "CRAFT") .. "into " .. (e.into or "?")
        elseif e.action == "hold" then what = tag(BLUE, "KEEP") .. ((e.hold == "raid") and "for raid week" or "price rising")
        else
            local plan = ns.PostPlan(e.id, e)
            e.plan = plan
            what = (plan.warn and tag(RED, "SELL") or tag(GOLDC, "SELL")) .. (plan.price and ns.PlanText(plan) or ("post at " .. ns.Money(e.price) .. " each"))
        end
        r.detail:SetText(e.plan and e.action == "ah" and what or string.format("%s  %s%s|r", what, MUTED, e.loc or ("x" .. (e.qty or 0))))
        r.profit:SetText(ns.Money(e.value or 0))
        if e.action ~= "ah" then
            r.search:Hide()
        elseif ahOpen() then
            r.buy:SetText("Post"); r.buy:Enable(); r.buy:Show()
        end
    elseif currentTab == "gear" then
        local up = e.pct and string.format("%s+%d%%|r", GREEN, e.pct) or (GREEN .. "empty slot|r")
        r.detail:SetText(string.format("%s%s|r  %s  %s", GOLDC, e.slot or "?", up,
            MUTED .. (e.replaces and ("over " .. e.replaces) or "") .. ((e.where or "") ~= "" and ("  at " .. e.where) or "") .. "|r"))
        r.profit:SetText(ns.Money(e.price or 0))
    elseif currentTab == "listed" then
        -- name line, right: what's going on; detail line: the price to act on and the timing
        local status, what
        if e.status == "undercut" then status, what = RED .. "UNDERCUT|r", "repost " .. ns.Money(e.repost)
        elseif e.status == "fell" then status, what = RED .. "PRICE FELL|r", "now ~" .. ns.Money(e.wall or e.other)
        elseif e.status == "dump" then status, what = GOLDC .. "CHEAP DUMP|r", e.repost and ("repost " .. ns.Money(e.repost)) or ("most at " .. ns.Money(e.wall))
        elseif e.status == "lowest" then status, what = GREEN .. "LOWEST|r", "x" .. e.qty .. " at " .. ns.Money(e.u or 0)
        else status, what = GREY .. "NO PRICE|r", "x" .. e.qty .. " at " .. ns.Money(e.u or 0) end
        if e.high and e.status ~= "fell" then status = RED .. "TOO HIGH|r" end
        local timing = {}
        if e.since then timing[#timing + 1] = "up " .. ns.Duration(time() - e.since) end
        if e.left then timing[#timing + 1] = ns.Duration(e.left) .. " left" end
        r.detail:SetText(what .. (#timing > 0 and ("  " .. MUTED .. table.concat(timing, " · ") .. "|r") or ""))
        r.profit:SetText(status)
        if (e.status == "undercut" or e.status == "fell" or e.repost or e.high) and ahOpen() then
            r.buy:SetText("Cancel"); r.buy:Enable(); r.buy:Show()
        end
    elseif currentTab == "mine" then
        local state
        if e.ready then
            state = tag(GREEN, "SELL NOW") .. "lowest " .. ns.Money(e.now)
        elseif e.now and e.pl and e.pl < 0 then
            state = tag(RED, "BELOW COST") .. "alert at " .. ns.Money(e.target)
        elseif e.now then
            state = tag(BLUE, "HOLD") .. "alert at " .. ns.Money(e.target)
        else
            state = tag(GREY, "NO PRICE") .. "not in last scan"
        end
        r.detail:SetText(string.format("%s  %sx%d, paid %s|r", state, MUTED, e.qty, ns.Money(e.cost)))
        if e.pl then
            r.profit:SetText((e.pl >= 0 and GREEN .. "+" or RED) .. ns.Money(e.pl) .. "|r")
        else
            r.profit:SetText("")
        end
    else -- crafts
        r.detail:SetText(string.format("%smats %s, sells %s", tag(GREEN, "CRAFT"), ns.Money(e.cost), ns.Money(e.value)))
        local p = e.profit or 0
        r.profit:SetText((p >= 0 and GREEN .. "+" or RED) .. ns.Money(p) .. "|r")
    end
    if pending and pending.id == e.id and pending.state == "confirm" then
        r.detail:SetText(string.format("%sConfirm x%d at %s each = %s|r", GREEN, pending.qty, ns.Money(pending.unit), ns.Money(pending.total)))
    end
end

local function nextStep()
    local t = targets()
    local realm = MyFA_DB.realms[ns.MarketKey()]
    local last = realm and realm.lastScan
    if not last then
        return ahOpen() and "Next: press Full scan to read every auction." or "Next: open the Auction House and press Full scan."
    end
    local deskScan = t and (ns.AtNeutralAH() and t.neutral and t.neutral.scan or t.scan)
    if not deskScan or deskScan < last - 5 then
        if ns.scannedThisSession then
            return GOLDC .. "Next: type /reload so MyFA Desk can read this scan.|r"
        end
        return GOLDC .. "Next: MyFA Desk is reading your scan. Type /reload again in a few seconds.|r"
            .. MUTED .. " (Desk must be running.)|r"
    end
    local ready = 0
    for _, p in ipairs(ns.Positions()) do if p.ready then ready = ready + 1 end end
    if ready > 0 then
        return GREEN .. string.format("%d of your flips %s ready to sell. Open My flips.|r", ready, ready == 1 and "is" or "are")
    end
    return "Up to date. " .. MUTED .. "Check Buy for deals and Sell for what to post.|r"
end

local function setBar(fraction, color, text)
    local b = panel.bar
    b:SetValue(math.max(0, math.min(1, tonumber(fraction) or 0)))
    b:SetStatusBarColor(color[1], color[2], color[3], 0.9)
    b.text:SetText(text)
    b:Show()
    panel.step:Hide()
end

function ns.RefreshHeader()
    if not panel then return end
    local t = targets()
    local realm = MyFA_DB.realms[ns.MarketKey()]
    local left = ns.ScanCooldownLeft and ns.ScanCooldownLeft() or 0
    local parts = { "Last scan " .. age(realm and realm.lastScan) }
    if ns.AtNeutralAH() then table.insert(parts, 1, PURPLE .. "Neutral AH, 15% cut|r" .. MUTED) end
    panel.title:SetText(ns.AtNeutralAH() and ("MyFA  " .. PURPLE .. "neutral|r") or "MyFA")
    parts[#parts + 1] = t and t.generated and ("targets " .. age(t.generated)) or "no targets yet"
    if left > 0 then parts[#parts + 1] = string.format("next scan in %d:%02d", math.floor(left / 60), left % 60) end
    panel.status:SetText(MUTED .. table.concat(parts, "  ·  ") .. "|r")

    if ns.IsScanning and ns.IsScanning() then
        panel.scan:SetText("Scanning"); panel.scan:Disable()
    elseif left > 0 then
        panel.scan:SetText(string.format("%d:%02d", math.floor(left / 60), left % 60)); panel.scan:Disable()
    else
        panel.scan:SetText("Full scan"); panel.scan:SetEnabled(ahOpen() and true or false)
    end

    local sc = ns.ScanInfo and ns.ScanInfo() or {}
    local clock = GetTime or time
    if sc.phase == "waiting" then
        local secs = math.floor(clock() - (sc.started or clock()))
        panel.bar.waiting = true
        setBar(panel.bar:GetValue(), GOLD, string.format("Asking the server for every auction...  %ds", secs))
    elseif sc.phase == "reading" then
        panel.bar.waiting = false
        local f = (sc.total or 0) > 0 and (sc.done or 0) / sc.total or 0
        setBar(f, GOLD, string.format("Reading auctions  %d%%   (%s of %s)", math.floor(f * 100), num(sc.done), num(sc.total)))
    elseif sc.phase == "done" and ns.scannedThisSession and time() - (sc.finished or 0) < 600
        and not (t and realm and ((ns.AtNeutralAH() and t.neutral and t.neutral.scan) or t.scan or 0) >= (realm.lastScan or 0) - 5) then
        panel.bar.waiting = false
        setBar(1, { 0.44, 0.82, 0.54 }, string.format("Done: %s auctions, %s items. Type /reload to send it to Desk.", num(sc.auctions), num(sc.items)))
    elseif sc.phase == "cancelled" and time() - (sc.finished or 0) < 120 then
        panel.bar.waiting = false
        setBar(1, { 0.91, 0.47, 0.42 }, "Scan stopped. Press Full scan to try again.")
    else
        panel.bar.waiting = false
        panel.bar:Hide()
        panel.step:SetText(nextStep())
        panel.step:Show()
    end
end

function ns.RefreshPanel()
    if not panel or not panel:IsShown() then return end
    local data = list()
    offset = math.max(0, math.min(offset, #data - ROWS))
    for i = 1, ROWS do updateRow(rows[i], data[i + offset]) end
    local hint = TAB_HINT[currentTab] or ""
    if currentTab == "mine" and ns.ProfitSince then
        local r = ns.ProfitSince(time() - 7 * 86400)
        if r.sales > 0 or r.expired > 0 then
            hint = string.format("Last 7 days: %d sales, flip profit %s%s|r, deposits lost %s. /myfa profit for more.",
                r.sales, r.flip >= 0 and GREEN .. "+" or RED, ns.Money(r.flip), ns.Money(r.lost))
        end
    elseif currentTab == "listed" then
        local busy, cur, left = ns.IsCheckingPrices()
        if busy then
            hint = string.format("Checking %s...  %d left. Searches only read prices.", cur and ns.ItemName(cur) or "", left)
        end
    elseif ns.AtNeutralAH() and (currentTab == "buys" or currentTab == "sells") then
        hint = currentTab == "buys" and "Neutral Auction House: cheap here, worth more on your faction's Auction House. Buy, then carry or mail them home."
            or "What sells for more here than at home, after the 15% neutral cut and its higher deposits."
    end
    panel.hint:SetText(hint)
    panel.addFlip:SetShown(currentTab == "mine")
    panel.check:SetShown(currentTab == "listed")
    panel.spec:SetShown(currentTab == "gear")
    if currentTab == "gear" then
        local name, which = ns.GearSpecName()
        panel.spec:SetText((which == "off" and "Off: " or "Main: ") .. (name or "?"))
    end
    local busy, cur, left = ns.IsCheckingPrices()
    panel.check:SetText(busy and "Stop" or "Check prices")
    panel.check:SetEnabled(busy or ahOpen() and true or false)
    panel.footer:SetWidth((currentTab == "mine" or currentTab == "listed") and (PANEL_W - 150)
        or currentTab == "gear" and (PANEL_W - 190) or (PANEL_W - 28))
    for key, tab in pairs(tabs) do
        local n
        if key == "mine" then n = #ns.Positions()
        elseif key == "listed" then n = #ns.MyAuctions()
        elseif key == "gear" then n = #ns.GearList()
        elseif ns.AtNeutralAH() and key ~= "crafts" then n = #(((targets() or {}).neutral or {})[key] or {})
        else n = #((targets() or {})[key] or {}) end
        tab:SetText(tab.label .. " " .. n)
        if key == currentTab then tab:LockHighlight() else tab:UnlockHighlight() end
    end
    if #data == 0 then
        local t = targets()
        if currentTab == "gear" then
            panel.empty:SetText("No gear upgrades yet.\n\nPress Full scan: MyFA reads the stats of every gear listing (chat says "
                .. "when it's done). Then /reload so MyFA Desk can score them for your specs, and /reload again once Desk has "
                .. "written the results.\n\nType /myfa gear to see which step is missing.")
        elseif currentTab == "listed" then
            panel.empty:SetText("No auctions recorded at this Auction House.\n\nOpen the Auction House's Auctions tab once so MyFA can see "
                .. "what you have listed. Then this tab shows which ones are undercut, and Check prices looks up live prices.")
        elseif currentTab == "mine" then
            panel.empty:SetText("No tracked flips yet.\n\nAnything you buy on the Auction House is tracked automatically, "
                .. "from any window or addon. You get an alert when it's worth selling.\n\n"
                .. "Bought something earlier? Press + Add flip below.")
        else
            panel.empty:SetText(t and "Nothing here in the latest targets." or
                "No targets yet.\n\n1. Full scan here\n2. /reload so MyFA Desk can read it\n3. /reload again once Desk says targets are ready")
        end
        panel.empty:Show()
    else
        panel.empty:Hide()
    end
    ns.RefreshHeader()
end

local function build()
    panel = CreateFrame("Frame", "MyFAPanel", UIParent, "BackdropTemplate")
    panel:SetSize(PANEL_W, PANEL_H)
    panel:SetPoint("CENTER")
    panel:SetFrameStrata("HIGH")
    panel:SetBackdrop({
        bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1,
    })
    panel:SetBackdropColor(0.055, 0.06, 0.07, 0.96)
    panel:SetBackdropBorderColor(GOLD[1], GOLD[2], GOLD[3], 0.35)
    panel:EnableMouse(true)
    panel:SetMovable(true)
    panel:RegisterForDrag("LeftButton")
    panel:SetClampedToScreen(true)
    panel:SetScript("OnDragStart", panel.StartMoving)
    panel:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        local point, _, relPoint, x, y = self:GetPoint(1)
        MyFA_DB.ui.pos = { point, relPoint, x, y }
        MyFA_DB.ui.manual = true
    end)
    panel:Hide()
    tinsert(UISpecialFrames, "MyFAPanel")

    panel.title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    panel.title:SetPoint("TOPLEFT", 14, -12)
    panel.title:SetText("MyFA")

    panel.status = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    panel.status:SetPoint("TOPLEFT", panel.title, "BOTTOMLEFT", 0, -4)

    -- progress bar while scanning; otherwise a "Next:" line telling you what to do
    local bar = CreateFrame("StatusBar", nil, panel)
    bar:SetSize(PANEL_W - 28, 18)
    bar:SetPoint("TOPLEFT", 14, -56)
    bar:SetStatusBarTexture("Interface\\Buttons\\WHITE8X8")
    bar:SetMinMaxValues(0, 1)
    bar.bg = bar:CreateTexture(nil, "BACKGROUND")
    bar.bg:SetAllPoints()
    bar.bg:SetColorTexture(1, 1, 1, 0.07)
    bar.text = bar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    bar.text:SetPoint("CENTER")
    bar.text:SetShadowOffset(1, -1)
    bar:SetScript("OnUpdate", function(self, elapsed)
        if self.waiting then  -- the server doesn't say how far along it is: show a moving fill
            self.phase = ((self.phase or 0) + (elapsed or 0) * 0.5) % 1
            self:SetValue(self.phase)
        end
    end)
    bar:Hide()
    panel.bar = bar
    panel.step = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    panel.step:SetPoint("TOPLEFT", 14, -59)
    panel.step:SetWidth(PANEL_W - 28)
    panel.step:SetJustifyH("LEFT")

    local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", 2, 2)

    panel.scan = makeButton(panel, "Full scan", 92)
    panel.scan:SetPoint("TOPRIGHT", -30, -14)
    panel.scan:SetScript("OnClick", function() ns.StartScan() end)

    local tabDefs = { { "buys", "Buy", 58 }, { "sells", "Sell", 58 }, { "crafts", "Craft", 62 }, { "mine", "My flips", 88 },
                      { "listed", "Listed", 74 }, { "gear", "Gear", 62 } }
    local prev
    for _, def in ipairs(tabDefs) do
        local b = makeButton(panel, def[2], def[3])
        b.label = def[2]
        if prev then b:SetPoint("LEFT", prev, "RIGHT", 5, 0) else b:SetPoint("TOPLEFT", 12, -84) end
        b:SetScript("OnClick", function()
            currentTab, offset = def[1], 0
            ns.RefreshPanel()
        end)
        b:SetScript("OnEnter", function(self)
            GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
            GameTooltip:SetText(def[2])
            GameTooltip:AddLine(TAB_HINT[def[1]], 1, 1, 1, true)
            GameTooltip:Show()
        end)
        b:SetScript("OnLeave", function() GameTooltip:Hide() end)
        tabs[def[1]] = b
        prev = b
    end

    panel.hint = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    panel.hint:SetPoint("TOPLEFT", 14, -112)
    panel.hint:SetWidth(PANEL_W - 28)
    panel.hint:SetJustifyH("LEFT")
    panel.hint:SetTextColor(0.75, 0.73, 0.68)

    panel.list = CreateFrame("Frame", nil, panel)
    panel.list:SetPoint("TOPLEFT", 14, -140)
    panel.list:SetSize(PANEL_W - 28, ROWS * ROW_H)
    panel.list:EnableMouseWheel(true)
    panel.list:SetScript("OnMouseWheel", function(_, delta)
        offset = offset - delta * 3
        ns.RefreshPanel()
    end)
    for i = 1, ROWS do rows[i] = buildRow(i) end

    panel.empty = panel.list:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    panel.empty:SetPoint("TOPLEFT", 8, -24)
    panel.empty:SetWidth(PANEL_W - 60)
    panel.empty:SetJustifyH("LEFT")
    panel.empty:SetSpacing(3)

    panel.footer = panel:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    panel.footer:SetPoint("BOTTOMLEFT", 14, 12)
    panel.footer:SetWidth(PANEL_W - 28)
    panel.footer:SetJustifyH("LEFT")
    panel.footer:SetText("Drag to move  ·  /myfa dock to snap back  ·  /myfa help for commands")
    panel.addFlip = makeButton(panel, "+ Add flip", 100)
    panel.addFlip:SetPoint("BOTTOMRIGHT", -12, 8)
    panel.addFlip:SetScript("OnClick", function() ns.ShowAddFlip() end)
    panel.addFlip:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:SetText("Add a flip")
        GameTooltip:AddLine("Track something you bought earlier at a known price. MyFA alerts you when it's worth selling.", 1, 1, 1, true)
        GameTooltip:Show()
    end)
    panel.addFlip:SetScript("OnLeave", function() GameTooltip:Hide() end)
    panel.spec = makeButton(panel, "Main spec", 150)
    panel.spec:SetPoint("BOTTOMRIGHT", -12, 8)
    panel.spec:SetScript("OnClick", function() ns.ToggleGearSpec() end)
    panel.check = makeButton(panel, "Check prices", 110)
    panel.check:SetPoint("BOTTOMRIGHT", -12, 8)
    panel.check:SetScript("OnClick", function() ns.CheckPrices() end)
    panel.check:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:SetText("Check prices")
        GameTooltip:AddLine("Looks up the live lowest price of each item you have listed, one search at a time. It only reads prices: it never cancels or posts.", 1, 1, 1, true)
        GameTooltip:Show()
    end)
    panel.check:SetScript("OnLeave", function() GameTooltip:Hide() end)

    panel:SetScript("OnShow", function()
        panel.ticker = C_Timer.NewTicker(1, ns.RefreshHeader)
        ns.RefreshPanel()
    end)
    panel:SetScript("OnHide", function()
        if panel.ticker then panel.ticker:Cancel(); panel.ticker = nil end
        if pending then cancelPending(true) end
    end)
end

function ns.TogglePanel()
    if not panel then build() end
    panel:SetShown(not panel:IsShown())
end

-- Add flip window: track something you bought earlier --------------------------------------

local dlg

local function findItemID(text)
    text = (text or ""):gsub("^%s+", ""):gsub("%s+$", "")
    if text == "" then return nil end
    local id = tonumber(text:match("item:(%d+)")) or tonumber(text)
    if id then return id end
    local lower = text:lower():gsub("^%[", ""):gsub("%]$", "")
    for itemID, meta in pairs(MyFA_DB.items) do
        if meta.n and meta.n:lower() == lower then return itemID end
    end
    if C_Item and C_Item.GetItemInfoInstant then
        local ok, found = pcall(C_Item.GetItemInfoInstant, text)
        if ok and found then return found end
    end
    return nil
end

local function label(parent, text, y, template)
    local fs = parent:CreateFontString(nil, "OVERLAY", template or "GameFontNormal")
    fs:SetPoint("TOPLEFT", 16, y)
    fs:SetWidth(300)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end

local function editBox(parent, w, y, x)
    local e = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
    e:SetSize(w, 22)
    e:SetPoint("TOPLEFT", x or 22, y)
    e:SetAutoFocus(false)
    e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return e
end

local function buildAddFlip()
    dlg = CreateFrame("Frame", "MyFAAddFlip", UIParent, "BackdropTemplate")
    dlg:SetSize(340, 268)
    dlg:SetPoint("CENTER")
    dlg:SetFrameStrata("DIALOG")
    dlg:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
    dlg:SetBackdropColor(0.055, 0.06, 0.07, 0.98)
    dlg:SetBackdropBorderColor(GOLD[1], GOLD[2], GOLD[3], 0.5)
    dlg:EnableMouse(true)
    dlg:SetMovable(true)
    dlg:RegisterForDrag("LeftButton")
    dlg:SetScript("OnDragStart", dlg.StartMoving)
    dlg:SetScript("OnDragStop", dlg.StopMovingOrSizing)
    tinsert(UISpecialFrames, "MyFAAddFlip")

    local title = dlg:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOPLEFT", 16, -14)
    title:SetText("Add a flip")
    local sub = label(dlg, "Bought something earlier? Add it and MyFA alerts you when it's worth selling.", -38, "GameFontHighlightSmall")
    sub:SetTextColor(0.75, 0.73, 0.68)

    label(dlg, "Item", -72)
    dlg.item = editBox(dlg, 296, -90)
    local hint = label(dlg, "Shift-click it, drag it here from your bags, or type its exact name.", -114, "GameFontDisableSmall")
    hint:SetWidth(310)

    label(dlg, "Quantity", -140)
    dlg.qty = editBox(dlg, 80, -158)
    dlg.qty:SetNumeric(true)
    local priceLabel = dlg:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    priceLabel:SetPoint("TOPLEFT", 130, -140)
    priceLabel:SetText("Price paid, each")
    dlg.price = editBox(dlg, 150, -158, 136)
    local ph = dlg:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    ph:SetPoint("TOPLEFT", 136, -182)
    ph:SetText("e.g. 14s50c, 1g20s or 1450")

    dlg.err = dlg:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    dlg.err:SetPoint("TOPLEFT", 16, -204)
    dlg.err:SetWidth(310)
    dlg.err:SetJustifyH("LEFT")
    dlg.err:SetTextColor(0.91, 0.47, 0.42)

    local add = makeButton(dlg, "Add flip", 110)
    add:SetPoint("BOTTOMRIGHT", -14, 12)
    local cancel = makeButton(dlg, "Cancel", 80)
    cancel:SetPoint("RIGHT", add, "LEFT", -6, 0)
    cancel:SetScript("OnClick", function() dlg:Hide() end)

    -- drop an item from the bags into the item box
    local function takeCursor(self)
        if not GetCursorInfo then return end
        local kind, id, link = GetCursorInfo()
        if kind == "item" then
            self:SetText(link or ("item:" .. id))
            if ClearCursor then ClearCursor() end
            dlg.qty:SetFocus()
        end
    end
    dlg.item:SetScript("OnReceiveDrag", takeCursor)
    dlg.item:HookScript("OnMouseDown", takeCursor)
    dlg.item:SetScript("OnTabPressed", function() dlg.qty:SetFocus() end)
    dlg.qty:SetScript("OnTabPressed", function() dlg.price:SetFocus() end)
    dlg.price:SetScript("OnTabPressed", function() dlg.item:SetFocus() end)

    local function submit()
        local id = findItemID(dlg.item:GetText())
        local qty = tonumber(dlg.qty:GetText())
        local price = ns.ParseMoney(dlg.price:GetText())
        if not id then
            dlg.err:SetText("Couldn't find that item. Shift-click it or drag it in from your bags.")
        elseif not qty or qty < 1 then
            dlg.err:SetText("Enter how many you bought.")
        elseif not price then
            dlg.err:SetText("Enter the price you paid for each, like 14s50c.")
        else
            ns.RecordBuy(id, qty, price, true)
            dlg:Hide()
            currentTab, offset = "mine", 0
            ns.RefreshPanel()
            return
        end
        dlg.err:Show()
    end
    add:SetScript("OnClick", submit)
    dlg.price:SetScript("OnEnterPressed", submit)
    dlg.qty:SetScript("OnEnterPressed", function() dlg.price:SetFocus() end)
    dlg.item:SetScript("OnEnterPressed", function() dlg.qty:SetFocus() end)
    dlg:Hide()
end

-- shift-clicking an item while the Item box has focus puts the item there
if hooksecurefunc and ChatEdit_InsertLink then
    hooksecurefunc("ChatEdit_InsertLink", function(link)
        if dlg and dlg:IsShown() and dlg.item:HasFocus() and type(link) == "string" and link:find("item:") then
            dlg.item:SetText(link)
            dlg.qty:SetFocus()
        end
    end)
end

function ns.ShowAddFlip(itemText)
    if not dlg then buildAddFlip() end
    dlg.item:SetText(itemText or "")
    dlg.qty:SetText("")
    dlg.price:SetText("")
    dlg.err:SetText("")
    dlg:Show()
    dlg.item:SetFocus()
end
ns._findItemID = findItemID

-- docking: sit beside whichever Auction House window is open (Blizzard's or an addon's) -----

local function rect(f)
    local ok, l, r, t, b = pcall(function() return f:GetLeft(), f:GetRight(), f:GetTop(), f:GetBottom() end)
    if not ok or not (l and r and t and b) then return nil end
    local k = (f:GetEffectiveScale() or 1) / (UIParent:GetEffectiveScale() or 1)
    return l * k, r * k, t * k, b * k
end

local AH_WORDS = { "auction", "aux", "market", "broker", "tsm", "ahframe" }

local function bigVisible(f, screenW)
    if f == panel or (f.IsForbidden and f:IsForbidden()) or not f:IsVisible() then return nil end
    if f.GetEffectiveAlpha and (f:GetEffectiveAlpha() or 1) < 0.05 then return nil end
    local l, r, t, b = rect(f)
    if not l then return nil end
    local w, h = r - l, t - b
    if w < 280 or h < 250 or w > screenW * 0.85 then return nil end
    return l, r, t, b
end

-- every frame that could be an auction window: UIParent's children, plus whatever lives inside
-- Blizzard's AuctionHouseFrame (some addons put their own window in there, bigger than Blizzard's)
local function candidates()
    local list, seen = {}, {}
    local function add(f) if f and not seen[f] then seen[f] = true; list[#list + 1] = f end end
    local function kids(f)
        local ok, t = pcall(function() return { f:GetChildren() } end)
        return ok and t or {}
    end
    for _, k in ipairs(kids(UIParent)) do add(k) end
    if AuctionHouseFrame then
        add(AuctionHouseFrame)
        for _, k in ipairs(kids(AuctionHouseFrame)) do
            add(k)
            for _, g in ipairs(kids(k)) do add(g) end
        end
    end
    return list
end

local function ahWindows()
    local screenW = UIParent:GetWidth() or 1920
    local base = AuctionHouseFrame
    local bl, br, bt, bb
    if base then
        local ok, l, r, t, b = pcall(bigVisible, base, screenW)
        if ok and l then bl, br, bt, bb = l, r, t, b end
    end
    local learned = MyFA_DB.ui.ahFrames or {}
    local found = {}
    for _, f in ipairs(candidates()) do
        pcall(function()
            local l, r, t, b = bigVisible(f, screenW)
            if not l then return end
            local name = (f.GetName and f:GetName() or "")
            local lname = name:lower()
            local looksLikeAH = false
            for _, w in ipairs(AH_WORDS) do if lname:find(w, 1, true) then looksLikeAH = true end end
            local insideAH = false
            local parent = f.GetParent and f:GetParent()
            while parent do
                if parent == base then insideAH = true; break end
                parent = parent.GetParent and parent:GetParent()
            end
            local overlaps = bl and not (l > br + 40 or r < bl - 40 or b > bt or t < bb)
            if f == base or insideAH or learned[name] or overlaps or (not bl and looksLikeAH) then
                found[#found + 1] = { l, r, t, b, f }
            end
        end)
    end
    return found
end

-- learn which windows belong to the Auction House: the big ones that close when it closes
local openSnapshot
local function snapshotOpen()
    local screenW = UIParent:GetWidth() or 1920
    openSnapshot = {}
    for _, f in ipairs(candidates()) do
        local ok, l = pcall(bigVisible, f, screenW)
        if ok and l then openSnapshot[#openSnapshot + 1] = f end
    end
end
local function learnOnClose()
    if not openSnapshot then return end
    MyFA_DB.ui.ahFrames = MyFA_DB.ui.ahFrames or {}
    for _, f in ipairs(openSnapshot) do
        local ok, visible = pcall(function() return f:IsVisible() end)
        local name = f.GetName and f:GetName()
        if ok and not visible and name and name ~= "" and f ~= panel then
            MyFA_DB.ui.ahFrames[name] = true
        end
    end
    openSnapshot = nil
end

local function dock()
    if not panel then return end
    if MyFA_DB.ui.manual and MyFA_DB.ui.pos then
        local p = MyFA_DB.ui.pos
        panel:ClearAllPoints()
        panel:SetPoint(p[1], UIParent, p[2], p[3], p[4])
        return
    end
    local wins = ahWindows()
    if #wins == 0 then return end
    local left, right, top = math.huge, -math.huge, -math.huge
    for _, w in ipairs(wins) do
        left, right, top = math.min(left, w[1]), math.max(right, w[2]), math.max(top, w[3])
    end
    local scale = (panel:GetEffectiveScale() or 1) / (UIParent:GetEffectiveScale() or 1)
    local width = PANEL_W * scale
    local x = right + 6
    if x + width > (UIParent:GetWidth() or 1920) then
        x = left - 6 - width                       -- no room on the right: dock on the left
        if x < 0 then x = (UIParent:GetWidth() or 1920) - width - 6 end
    end
    panel:ClearAllPoints()
    panel:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", x / scale, top / scale)
end

function ns.Redock()
    MyFA_DB.ui.manual, MyFA_DB.ui.pos = nil, nil
    if not panel then build() end
    dock()
    panel:Show()
    ns.Print("panel docked beside the Auction House. Drag it to move; it remembers where you put it.")
end

local function attachToAH()
    if not panel then build() end
    dock()
    panel:Show()
    -- other auction addons often open their window a moment later: dock again
    C_Timer.After(0.2, dock)
    C_Timer.After(0.8, function() dock(); snapshotOpen() end)
    C_Timer.After(2.0, dock)
end

-- events ---------------------------------------------------------------------

local ev = CreateFrame("Frame")
ev:RegisterEvent("AUCTION_HOUSE_SHOW")
ev:RegisterEvent("AUCTION_HOUSE_CLOSED")
for _, e in ipairs({ "COMMODITY_PRICE_UPDATED", "COMMODITY_PRICE_UNAVAILABLE",
                     "COMMODITY_PURCHASE_SUCCEEDED", "COMMODITY_PURCHASE_FAILED" }) do
    pcall(ev.RegisterEvent, ev, e)
end
ev:SetScript("OnEvent", function(_, event, a1, a2)
    if event == "AUCTION_HOUSE_SHOW" then
        attachToAH()
    elseif event == "AUCTION_HOUSE_CLOSED" then
        if pending then cancelPending(true) end
        if panel then panel:Hide() end
        C_Timer.After(0.3, learnOnClose)
    else
        onCommodityEvent(event, a1, a2)
    end
end)

-- tooltips -------------------------------------------------------------------

local function addTooltipLines(tt, id)
    if not id or not MyFA_DB then return end
    local realm = MyFA_DB.realms[ns.RealmKey()]
    local s = realm and realm.items and realm.items[id]
    local t = targets()
    local deskValue = t and t.prices and t.prices[id]
    local owned, parts = ns.Owned(id)
    local hasSales = ns.SellStats and ns.SellStats(id).listings > 0
    local nrealm = MyFA_DB.realms[ns.NeutralKey()]
    if not s and not deskValue and owned == 0 and not hasSales and not (nrealm and nrealm.items and nrealm.items[id]) then return end
    tt:AddLine(" ")
    if owned > 0 then
        tt:AddDoubleLine("|cffd9b45aMyFA|r you own", owned .. MUTED .. "  " .. ns.WhereText(parts, 3) .. "|r", 1, 1, 1, 1, 1, 1)
        for _, p in ipairs(ns.Positions()) do
            if p.id == id then
                tt:AddDoubleLine("|cffd9b45aMyFA|r you paid", ns.Money(p.cost) .. MUTED .. " each, sell at " .. "|r" .. ns.Money(p.target), 1, 1, 1, 1, 1, 1)
                break
            end
        end
    end
    if s then
        tt:AddDoubleLine("|cffd9b45aMyFA|r lowest", ns.Money(s.m) .. MUTED .. "  (" .. (s.q or 0) .. " listed)|r", 1, 1, 1, 1, 1, 1)
    end
    if deskValue then
        tt:AddDoubleLine("|cffd9b45aMyFA|r market", ns.Money(deskValue), 1, 1, 1, 1, 1, 1)
    end
    local nr = MyFA_DB.realms[ns.NeutralKey()]
    local ns_ = nr and nr.items and nr.items[id]
    if ns_ then
        tt:AddDoubleLine("|cffd9b45aMyFA|r neutral AH", ns.Money(ns_.m) .. MUTED .. "  (" .. (ns_.q or 0) .. " listed, 15% cut)|r", 1, 1, 1, 1, 1, 1)
    end
    if ns.SellStats then
        local st = ns.SellStats(id)
        if st.listings > 0 then
            tt:AddDoubleLine("|cffd9b45aMyFA|r your sales", string.format("%d%% of what you listed sold%s", math.floor(st.rate * 100 + 0.5),
                st.lost > 0 and (", " .. ns.Money(st.lost) .. " deposits lost") or ""), 1, 1, 1, 1, 1, 1)
        end
    end
    for _, e in ipairs(t and t.buys or {}) do
        if e.id == id then
            tt:AddDoubleLine(GREEN .. "Buy target|r", "up to " .. ns.Money(e.max), 1, 1, 1, 1, 1, 1)
            break
        end
    end
end

if TooltipDataProcessor and Enum and Enum.TooltipDataType then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tt, data)
        if tt ~= GameTooltip and tt ~= ItemRefTooltip then return end
        addTooltipLines(tt, data and data.id)
    end)
end

function ns.OnLogin()
    local t = targets()
    if t and t.generated then
        ns.Print(string.format("loaded targets from Desk (%s): %d buys, %d sells, %d crafts. /myfa to open.",
            age(t.generated), #(t.buys or {}), #(t.sells or {}), #(t.crafts or {})))
    end
end

-- exposed for the offline test harness
ns._buyClicked = buyClicked
ns._onCommodityEvent = onCommodityEvent
