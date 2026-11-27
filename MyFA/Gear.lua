-- MyFA Gear: what each character wears, and the stats of every gear listing on the Auction House.
-- MyFA Desk scores them with stat weights for the class and specs you pick and shows the upgrades.
local ADDON, ns = ...

local SKIP_LOC = { INVTYPE_BAG = true, INVTYPE_QUIVER = true, INVTYPE_AMMO = true, INVTYPE_BODY = true,
                   INVTYPE_TABARD = true, INVTYPE_NON_EQUIP = true, INVTYPE_NON_EQUIP_IGNORE = true, [""] = true }
local SLOTS = { 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 }   -- no shirt (4) or tabard (19)
local PER_FRAME = 40
local KEEP_DAYS = 30

local function instant(id)
    if C_Item and C_Item.GetItemInfoInstant then return C_Item.GetItemInfoInstant(id) end
    if GetItemInfoInstant then return GetItemInfoInstant(id) end
end

-- armor or a weapon you can wear
function ns.IsGearItem(id)
    local _, _, _, equipLoc, _, classID = instant(id)
    return (classID == 2 or classID == 4) and equipLoc ~= nil and not SKIP_LOC[equipLoc] or false
end

-- "12345" or "12345:-17" (random suffix) from an item link
function ns.GearKey(link)
    local id, rest = tostring(link or ""):match("item:(%d+):([^|]*)")
    if not id then return nil end
    local f = {}
    for v in (rest .. ":"):gmatch("([^:]*):") do f[#f + 1] = v end
    -- fields after the item ID: enchant, gem1-4, suffix
    local suffix = tonumber(f[6] or "") or 0
    return suffix ~= 0 and (id .. ":" .. suffix) or id
end

local function keyLink(key)
    local id, suffix = key:match("^(%d+):?(%-?%d*)$")
    return "item:" .. id .. ":0:0:0:0:0:" .. (suffix ~= "" and suffix or "0")
end

-- stats ------------------------------------------------------------------------------------------------

-- equip lines the stat API may not report (English client)
local PATTERNS = {
    { "Increases healing done by spells and effects by up to (%d+)", "HEAL" },
    { "Increases damage and healing done by magical spells and effects by up to (%d+)", "SP" },
    { "Increases damage done by (%a+) spells and effects by up to (%d+)", "SCHOOL" },
    { "Improves your chance to get a critical strike with spells by (%d+)%%", "SCRIT" },
    { "Improves your chance to hit with spells by (%d+)%%", "SHIT" },
    { "Improves your chance to get a critical strike by (%d+)%%", "CRIT" },
    { "Improves your chance to hit by (%d+)%%", "HIT" },
    { "Restores (%d+) mana per 5 sec", "MP5" },
    { "Restores (%d+) health per 5 sec", "HP5" },
    { "Increases attack power by (%d+) in Cat, Bear, Dire Bear", "FAP" },
    { "Increases ranged attack power by (%d+)", "RAP" },
    { "%+(%d+) ranged Attack Power", "RAP" },
    { "%+(%d+) Attack Power", "AP" },
    { "Increases attack power by (%d+)", "AP" },
    { "Increased Defense %+(%d+)", "DEF" },
    { "Increases your chance to dodge an attack by (%d+)%%", "DODGE" },
    { "Increases your chance to parry an attack by (%d+)%%", "PARRY" },
    { "Increases your chance to block attacks with a shield by (%d+)%%", "BLOCK" },
    { "Increases the block value of your shield by (%d+)", "BLOCKVAL" },
    { "^(%d+) Block$", "BLOCKVAL" },
    { "%((%d+%.?%d*) damage per second%)", "DPS" },
    { "^(%d+) Armor$", "ARMOR" },
    { "^%+(%d+) Strength", "STR" }, { "^%+(%d+) Agility", "AGI" }, { "^%+(%d+) Stamina", "STA" },
    { "^%+(%d+) Intellect", "INT" }, { "^%+(%d+) Spirit", "SPI" },
}

-- the text of an item's tooltip: the tooltip data API where the client has it, otherwise a hidden tooltip
local scanTip
ns.TooltipMethod = "none"
function ns.TooltipLines(link)
    local out = {}
    if C_TooltipInfo and C_TooltipInfo.GetHyperlink then
        local ok, data = pcall(C_TooltipInfo.GetHyperlink, link)
        if ok and data and data.lines and #data.lines > 0 then
            for _, line in ipairs(data.lines) do out[#out + 1] = line.leftText or "" end
            ns.TooltipMethod = "tooltip data"
            return out
        end
    end
    if not scanTip then
        local ok, tip = pcall(CreateFrame, "GameTooltip", "MyFAScanTip", nil, "GameTooltipTemplate")
        scanTip = ok and tip or false
    end
    if scanTip and scanTip.SetHyperlink then
        pcall(scanTip.SetOwner, scanTip, WorldFrame, "ANCHOR_NONE")
        scanTip:ClearLines()
        local ok = pcall(scanTip.SetHyperlink, scanTip, link)
        local n = ok and scanTip.NumLines and scanTip:NumLines() or 0
        for i = 1, n do
            local fs = _G["MyFAScanTipTextLeft" .. i]
            out[#out + 1] = fs and fs.GetText and fs:GetText() or ""
        end
        scanTip:Hide()
        if n > 0 then ns.TooltipMethod = "hidden tooltip" end
    end
    return out
end

-- returns "STA=10;INT=7;HEAL=22", the class restriction (or nil), and whether the item was fully readable
function ns.ReadGearStats(link)
    local stats, apiOk = {}, false
    local getStats = (C_Item and C_Item.GetItemStats) or GetItemStats
    if getStats then
        local ok, t = pcall(getStats, link)
        if ok and type(t) == "table" then
            apiOk = true
            for k, v in pairs(t) do
                if type(v) == "number" and v ~= 0 then
                    local short = k:gsub("^ITEM_MOD_", ""):gsub("_SHORT$", ""):gsub("_NAME$", "")
                    stats[short] = v
                end
            end
        end
    end
    local classes, lines = nil, 0
    for _, text in ipairs(ns.TooltipLines(link)) do
        if text ~= "" then
            lines = lines + 1
            classes = classes or text:match("^Classes: (.+)$")
            for _, p in ipairs(PATTERNS) do
                local a, b = text:match(p[1])
                if a then
                    if p[2] == "SCHOOL" then
                        stats[a:upper()] = math.max(stats[a:upper()] or 0, tonumber(b))
                    else
                        stats[p[2]] = math.max(stats[p[2]] or 0, tonumber(a))
                    end
                    break
                end
            end
        end
    end
    local parts = {}
    for k, v in pairs(stats) do parts[#parts + 1] = k .. "=" .. (math.floor(v * 10 + 0.5) / 10) end
    table.sort(parts)
    -- readable: the tooltip had text, or (no tooltip at all) the stat API answered
    return table.concat(parts, ";"), classes, lines > 1 or (apiOk and lines == 0)
end

-- what Desk needs about one gear item, kept in MyFA_DB.gear (shared by all characters)
local function describe(key, link)
    local id = tonumber(key:match("^(%d+)"))
    local name, _, quality, _, minLevel, _, _, _, equipLoc, _, _, classID, subclassID = GetItemInfo(link or id)
    if not name then return false end
    local st, classes, full = ns.ReadGearStats(link or keyLink(key))
    if not full then return false end
    MyFA_DB.gear[key] = { n = name, q = quality, lvl = minLevel or 0, loc = equipLoc, k = classID, u = subclassID,
                          st = st, cl = classes, seen = time() }
    ns.FillItemMeta(id)
    return true
end

-- background reading, a few items per frame, retried once the client has loaded them
local queue, queued, waiting, total, done = {}, {}, {}, 0, 0
local worker = CreateFrame("Frame")

local function progress()
    return total, done
end
ns.GearProgress = progress

local function work()
    local n = 0
    while n < PER_FRAME and #queue > 0 do
        local e = table.remove(queue)
        queued[e.key] = nil
        if describe(e.key, e.link) then
            done = done + 1
        else
            e.tries = (e.tries or 0) + 1
            if e.tries <= 3 then
                waiting[#waiting + 1] = e
                local id = tonumber(e.key:match("^(%d+)"))
                if C_Item and C_Item.RequestLoadItemDataByID then pcall(C_Item.RequestLoadItemDataByID, id) end
            else
                done = done + 1
            end
        end
        n = n + 1
    end
    if #queue == 0 then
        if #waiting > 0 then
            -- give the client a moment to load the rest, then try again
            queue, waiting = waiting, {}
            for _, e in ipairs(queue) do queued[e.key] = true end
            worker:SetScript("OnUpdate", nil)
            C_Timer.After(2, function() worker:SetScript("OnUpdate", work) end)
        else
            worker:SetScript("OnUpdate", nil)
            if total > 0 then ns.Print(string.format("gear stats read for %d items. /reload so MyFA Desk can find upgrades.", total)) end
            total, done = 0, 0
        end
    end
end

-- after a scan: read stats for gear MyFA hasn't seen yet
function ns.QueueGearStats(listings)
    local now = time()
    for key, e in pairs(listings) do
        local known = MyFA_DB.gear[key]
        if known then
            known.seen = now
        elseif not queued[key] then
            queued[key] = true
            queue[#queue + 1] = { key = key, link = e[2] }
            total = total + 1
        end
    end
    if #queue > 0 then worker:SetScript("OnUpdate", work) end
    -- forget gear not listed for a month
    for key, g in pairs(MyFA_DB.gear) do
        if now - (g.seen or 0) > KEEP_DAYS * 86400 and not g.worn then MyFA_DB.gear[key] = nil end
    end
end

-- what this character wears -------------------------------------------------------------------------

function ns.SnapshotGear()
    if not GetInventoryItemLink then return end
    local c = ns.Char()
    c.gear = {}
    local pending = {}
    for _, slot in ipairs(SLOTS) do
        local link = GetInventoryItemLink("player", slot)
        local key = link and ns.GearKey(link)
        if key then
            c.gear[slot] = key
            local g = MyFA_DB.gear[key]
            if g then g.worn = true else pending[key] = { 0, link } end
        end
    end
    if next(pending) then
        ns.QueueGearStats(pending)
        for key in pairs(pending) do
            C_Timer.After(5, function() if MyFA_DB.gear[key] then MyFA_DB.gear[key].worn = true end end)
        end
    end
    c.gearT = time()
end

local ev = CreateFrame("Frame")
for _, e in ipairs({ "PLAYER_LOGIN", "PLAYER_EQUIPMENT_CHANGED", "PLAYER_LEVEL_UP" }) do pcall(ev.RegisterEvent, ev, e) end
ev:SetScript("OnEvent", function(_, event)
    MyFA_DB.gear = MyFA_DB.gear or {}
    if event == "PLAYER_LOGIN" then
        C_Timer.After(3, ns.SnapshotGear)
    else
        C_Timer.After(0.5, ns.SnapshotGear)
    end
end)

-- the upgrade lists MyFA Desk wrote for this character ---------------------------------------------------

local which = "main"
local function mine()
    local t = MyFA_Targets and MyFA_Targets.upgrades
    return t and t[ns.CharKey()]
end

function ns.GearSpecName()
    local u = mine()
    if not u then return nil, which end
    if which == "off" and (u.off or "") == "" then which = "main" end
    return which == "off" and u.off or u.main, which
end

function ns.ToggleGearSpec()
    local u = mine()
    if u and (u.off or "") ~= "" then which = (which == "main") and "off" or "main" end
    if ns.RefreshPanel then ns.RefreshPanel() end
end

function ns.GearList()
    local u = mine()
    local spec = ns.GearSpecName()
    return (u and spec and u.lists and u.lists[spec]) or {}
end

ns._gearKeyLink = keyLink

-- /myfa gear: which step is missing
function ns.GearStatus()
    local c = ns.Char()
    local worn, wornRead = 0, 0
    for _, key in pairs(c.gear or {}) do
        worn = worn + 1
        if MyFA_DB.gear[key] then wornRead = wornRead + 1 end
    end
    ns.Print(string.format("gear: wearing %d items, stats read for %d.", worn, wornRead))
    local any = false
    for _, rk in ipairs({ ns.RealmKey(), ns.NeutralKey and ns.NeutralKey() or nil }) do
        local realm = rk and MyFA_DB.realms[rk]
        if realm and realm.gear then
            local n, read = 0, 0
            for key in pairs(realm.gear) do
                n = n + 1
                if MyFA_DB.gear[key] then read = read + 1 end
            end
            any = any or n > 0
            ns.Print(string.format("  %s: %d gear listings in the last scan, stats read for %d.", rk, n, read))
        end
    end
    if not any then ns.Print("  no gear listings yet: press Full scan at the Auction House (MyFA 1.9.0 or newer).") end
    if total > 0 then ns.Print(string.format("  still reading stats: %d of %d done. Wait for the chat message, then /reload.", done, total)) end
    ns.Print("  stats read with: " .. ns.TooltipMethod .. ".")
    local u = mine()
    if u then
        local n = 0
        for _, list in pairs(u.lists or {}) do n = n + #list end
        ns.Print(string.format("  MyFA Desk lists: %s / %s, %d upgrades.", u.main or "?", (u.off ~= "" and u.off) or "none", n))
    else
        ns.Print("  no lists from MyFA Desk for this character yet: /reload, let Desk say \"Targets ready\", then /reload again.")
    end
end
