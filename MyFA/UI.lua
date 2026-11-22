-- MyFA UI: targets panel beside the Auction House, Search/Buy actions, price tooltips.
local ADDON, ns = ...

local ROWS, ROW_H = 9, 40
local PANEL_W, PANEL_H = 430, 540
local GOLD = { 0.85, 0.71, 0.35 }
local GREEN = "|cff6fd08a"
local RED = "|cffe8796b"
local MUTED = "|cffa9a59a"

local panel, rows, tabs = nil, {}, {}

-- what each tab is for, shown under the tab buttons
local TAB_HINT = {
    buys = "Cheap listings worth buying to resell. Right: your profit after reselling. Press Buy, then Confirm.",
    sells = "What to do with what you own, on every character. Right: what the whole stack is worth.",
    crafts = "Recipes you know that make a profit. Right: profit per craft. Open a profession window to add recipes.",
    mine = "Things you bought, tracked until you sell them. Right: profit if you sold now. You get an alert when it's time.",
}
local currentTab, offset = "buys", 0
local pending -- { id, qty, max, state = "starting"|"confirm"|"buying", unit, total }

-- helpers --------------------------------------------------------------------

local function targets()
    return MyFA_Targets
end

local function list()
    if currentTab == "mine" then return ns.Positions() end
    local t = targets()
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
    r.buy:SetScript("OnClick", function() if r.entry then buyClicked(r.entry) end end)
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
        r.detail:SetText(string.format("buy x%d, max %s each%s%s|r", left, ns.Money(e.max), MUTED, kind))
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
        if e.action == "vendor" then what = "sell to a vendor"
        elseif e.action == "craft" then what = "craft it into " .. (e.into or "?")
        elseif e.action == "hold" then what = (e.hold == "raid") and "keep for raid week" or "keep, price rising"
        else what = "post at " .. ns.Money(e.price) .. " each" end
        r.detail:SetText(string.format("%s  %s%s|r", what, MUTED, e.loc or ("x" .. (e.qty or 0))))
        r.profit:SetText(ns.Money(e.value or 0))
        if e.action ~= "ah" then r.search:Hide() end
    elseif currentTab == "mine" then
        local state
        if e.ready then
            state = GREEN .. "SELL|r  " .. MUTED .. "now " .. "|r" .. ns.Money(e.now)
        elseif e.now then
            state = MUTED .. "hold, sell at " .. "|r" .. ns.Money(e.target)
        else
            state = MUTED .. "not listed in last scan|r"
        end
        r.detail:SetText(string.format("x%d  %spaid %s|r  %s", e.qty, MUTED, ns.Money(e.cost), state))
        if e.pl then
            r.profit:SetText((e.pl >= 0 and GREEN .. "+" or RED) .. ns.Money(e.pl) .. "|r")
        else
            r.profit:SetText("")
        end
    else -- crafts
        r.detail:SetText(string.format("mats %s  %ssells for %s|r", ns.Money(e.cost), MUTED, ns.Money(e.value)))
        local p = e.profit or 0
        r.profit:SetText((p >= 0 and GREEN .. "+" or RED) .. ns.Money(p) .. "|r")
    end
    if pending and pending.id == e.id and pending.state == "confirm" then
        r.detail:SetText(string.format("%sConfirm x%d at %s each = %s|r", GREEN, pending.qty, ns.Money(pending.unit), ns.Money(pending.total)))
    end
end

function ns.RefreshHeader()
    if not panel then return end
    local t = targets()
    local realm = MyFA_DB.realms[ns.RealmKey()]
    local scanText = ns.scanStatus or ("Scan " .. age(realm and realm.lastScan))
    local deskText = t and t.generated and ("targets " .. age(t.generated)) or "no targets yet"
    panel.status:SetText(MUTED .. scanText .. "  ·  " .. deskText .. "|r")

    local left = ns.ScanCooldownLeft and ns.ScanCooldownLeft() or 0
    if ns.IsScanning and ns.IsScanning() then
        panel.scan:SetText("Scanning"); panel.scan:Disable()
    elseif left > 0 then
        panel.scan:SetText(string.format("%d:%02d", math.floor(left / 60), left % 60)); panel.scan:Disable()
    else
        panel.scan:SetText("Full scan"); panel.scan:SetEnabled(ahOpen() and true or false)
    end
end

function ns.RefreshPanel()
    if not panel or not panel:IsShown() then return end
    local data = list()
    offset = math.max(0, math.min(offset, #data - ROWS))
    for i = 1, ROWS do updateRow(rows[i], data[i + offset]) end
    panel.hint:SetText(TAB_HINT[currentTab] or "")
    for key, tab in pairs(tabs) do
        local n = key == "mine" and #ns.Positions() or #((targets() or {})[key] or {})
        tab:SetText(tab.label .. " " .. n)
        if key == currentTab then tab:LockHighlight() else tab:UnlockHighlight() end
    end
    if #data == 0 then
        local t = targets()
        if currentTab == "mine" then
            panel.empty:SetText("No tracked flips yet.\n\nAnything you buy on the Auction House is tracked automatically, "
                .. "from any window or addon. You get an alert when it's worth selling.\n\n"
                .. "For something you bought earlier:\n/myfa bought [item] qty price\ne.g. /myfa bought [Golden Sansam] 20 14s50c")
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

    local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", 2, 2)

    panel.scan = makeButton(panel, "Full scan", 92)
    panel.scan:SetPoint("TOPRIGHT", -30, -14)
    panel.scan:SetScript("OnClick", function() ns.StartScan() end)

    local tabDefs = { { "buys", "Buy" }, { "sells", "Sell" }, { "crafts", "Craft" }, { "mine", "My flips" } }
    local prev
    for _, def in ipairs(tabDefs) do
        local b = makeButton(panel, def[2], 92)
        b.label = def[2]
        if prev then b:SetPoint("LEFT", prev, "RIGHT", 6, 0) else b:SetPoint("TOPLEFT", 12, -58) end
        b:SetScript("OnClick", function()
            currentTab, offset = def[1], 0
            ns.RefreshPanel()
        end)
        tabs[def[1]] = b
        prev = b
    end

    panel.hint = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    panel.hint:SetPoint("TOPLEFT", 14, -86)
    panel.hint:SetWidth(PANEL_W - 28)
    panel.hint:SetJustifyH("LEFT")
    panel.hint:SetTextColor(0.75, 0.73, 0.68)

    panel.list = CreateFrame("Frame", nil, panel)
    panel.list:SetPoint("TOPLEFT", 14, -114)
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
    if not s and not deskValue and owned == 0 then return end
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
