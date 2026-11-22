-- MyFA Core: saved data, character snapshot (bags, gold, recipes, vendor prices), slash commands.
local ADDON, ns = ...
ns.VERSION = "1.5.2"
ns.HISTORY_DAYS = 14

local DB_DEFAULTS = {
    version = 1,
    realms = {},    -- [realmKey] = { lastScan, auctions, items = {[itemID] = {m,p,q,n,l}}, h = {[itemID] = {[day] = min}} }
    items = {},     -- [itemID] = { n = name, v = vendorSell, c = quality, e = equipLoc, s = maxStack }
    chars = {},     -- [charKey] = { realmKey, faction, money, t, bags = {[itemID] = count}, recipes = {...} }
    vendorBuy = {}, -- [itemID] = copper per unit when bought from a merchant
    ledger = {},    -- { t, k = "buy", id, q, u, m = manual, x = forgotten }
    alerted = {},   -- [itemID] = { p = price alerted at, t = time }
    imported = {},  -- [mid] = true: flips added in MyFA Desk that are already in the ledger
    forgotten = {}, -- [itemID] = time: "stop tracking" requests from MyFA Desk already applied
    settings = { roi = 0.15, alerts = true },
    ui = {},        -- panel position
}

local function copyDefaults(dst, src)
    for k, v in pairs(src) do
        if dst[k] == nil then
            dst[k] = type(v) == "table" and {} or v
        end
    end
end

function ns.Print(msg)
    print("|cffd9b45aMyFA|r " .. tostring(msg))
end

function ns.Money(copper)
    copper = math.floor(tonumber(copper) or 0)
    local neg = copper < 0
    if neg then copper = -copper end
    local g = math.floor(copper / 10000)
    local s = math.floor((copper % 10000) / 100)
    local c = copper % 100
    local out
    if g > 0 then
        out = string.format("%d|cffd9b45ag|r %02d|cffb8b8b8s|r", g, s)
    elseif s > 0 then
        out = string.format("%d|cffb8b8b8s|r %02d|cffc58a4ac|r", s, c)
    else
        out = string.format("%d|cffc58a4ac|r", c)
    end
    return neg and ("-" .. out) or out
end

function ns.RealmKey()
    local realm = (GetNormalizedRealmName and GetNormalizedRealmName()) or GetRealmName() or "Unknown"
    local faction = UnitFactionGroup("player") or "Neutral"
    return realm .. "-" .. faction
end

function ns.CharKey()
    local name = UnitName("player") or "Unknown"
    local realm = (GetNormalizedRealmName and GetNormalizedRealmName()) or GetRealmName() or "Unknown"
    return name .. "-" .. realm
end

function ns.Today()
    return math.floor(time() / 86400)
end

function ns.Char()
    local key = ns.CharKey()
    local c = MyFA_DB.chars[key]
    if not c then
        c = { bags = {}, recipes = {} }
        MyFA_DB.chars[key] = c
    end
    c.realmKey = ns.RealmKey()
    c.faction = UnitFactionGroup("player")
    return c
end

-- Item metadata --------------------------------------------------------------

local pendingMeta = {}

function ns.FillItemMeta(itemID)
    if not itemID then return true end
    local meta = MyFA_DB.items[itemID]
    if meta and meta.n then return true end
    local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
    if not getInfo then return false end
    local name, _, quality, _, _, _, _, maxStack, equipLoc, _, sellPrice, classID, subclassID = getInfo(itemID)
    if name then
        MyFA_DB.items[itemID] = {
            n = name, c = quality, s = maxStack, v = sellPrice or 0, k = classID, u = subclassID,
            e = (equipLoc and equipLoc ~= "" and equipLoc ~= "INVTYPE_NON_EQUIP_IGNORE") and equipLoc or nil,
        }
        pendingMeta[itemID] = nil
        return true
    end
    pendingMeta[itemID] = true
    if C_Item and C_Item.RequestLoadItemDataByID then
        C_Item.RequestLoadItemDataByID(itemID)
    end
    return false
end

function ns.ItemName(itemID)
    local meta = MyFA_DB and MyFA_DB.items[itemID]
    return meta and meta.n or ("item:" .. tostring(itemID))
end

-- Bags -----------------------------------------------------------------------

local function readContainers(ids)
    local out = {}
    for _, bag in ipairs(ids) do
        local ok, slots = pcall(C_Container.GetContainerNumSlots, bag)
        for slot = 1, (ok and slots or 0) do
            local info = C_Container.GetContainerItemInfo(bag, slot)
            if info and info.itemID and not info.isBound then
                out[info.itemID] = (out[info.itemID] or 0) + (info.stackCount or 1)
                ns.FillItemMeta(info.itemID)
            end
        end
    end
    return out
end

function ns.SnapshotBags()
    if not C_Container then return end
    local c = ns.Char()
    local ids = {}
    for bag = 0, (NUM_BAG_SLOTS or 4) + (NUM_REAGENTBAG_SLOTS or 0) do ids[#ids + 1] = bag end
    c.bags = readContainers(ids)
    c.money = GetMoney()
    c.t = time()
end

-- Bank: classic-style bank + bank bags, or modern character bank tabs; warband tabs kept separately.
local function bankContainerIDs()
    local char, account, seen = {}, {}, {}
    local function add(list, id)
        if id and not seen[id] then seen[id] = true; list[#list + 1] = id end
    end
    local BI = Enum and Enum.BagIndex
    add(char, BI and BI.Bank or -1)
    local first = (NUM_TOTAL_EQUIPPED_BAG_SLOTS or ((NUM_BAG_SLOTS or 4) + (NUM_REAGENTBAG_SLOTS or 0))) + 1
    for id = first, first + (NUM_BANKBAGSLOTS or 7) - 1 do add(char, id) end
    if BI then
        for key, id in pairs(BI) do
            if type(key) == "string" and key:find("BankTab") then
                add(key:find("Account") and account or char, id)
            end
        end
    end
    return char, account
end

local bankOpen = false

function ns.SnapshotBank()
    if not (C_Container and bankOpen) then return end
    local charIDs, accountIDs = bankContainerIDs()
    local c = ns.Char()
    c.bank = readContainers(charIDs)
    c.bankT = time()
    if #accountIDs > 0 then
        local warband = readContainers(accountIDs)
        if next(warband) then
            MyFA_DB.warband = { items = warband, t = time(), realmKey = ns.RealmKey() }
        end
    end
    if not ns.bankNoticeShown then
        local n = 0
        for _ in pairs(c.bank) do n = n + 1 end
        ns.Print(string.format("recorded your bank (%d item types).", n))
        ns.bankNoticeShown = true
    end
end

-- Character profile: level, class, zone, professions (for MyFA Desk's Guide) --------------

function ns.SnapshotProfile()
    local ok, err = pcall(function()
        local c = ns.Char()
        c.level = UnitLevel and UnitLevel("player") or c.level
        if UnitClass then
            local className, classFile = UnitClass("player")
            c.class, c.classFile = className, classFile
        end
        if UnitRace then c.race = UnitRace("player") end
        if GetZoneText then c.zone = GetZoneText() end
        c.profs = c.profs or {}
        if GetProfessions and GetProfessionInfo then
            local list = { GetProfessions() }
            for i = 1, select("#", GetProfessions()) do
                local idx = list[i]
                if idx then
                    local name, _, skill, maxSkill = GetProfessionInfo(idx)
                    if name then c.profs[name] = { skill, maxSkill } end
                end
            end
        end
        c.profileT = time()
    end)
    if not ok and not ns.profileWarned then
        ns.profileWarned = true
        ns.Print("couldn't read your character profile: " .. tostring(err))
    end
end

-- Mailbox: Auction House purchases land here first -----------------------------

function ns.SnapshotMail()
    if not GetInboxNumItems or not GetInboxItem then return end
    local c = ns.Char()
    local mail = {}
    for i = 1, GetInboxNumItems() or 0 do
        for j = 1, (ATTACHMENTS_MAX_RECEIVE or 16) do
            local _, itemID, _, count = GetInboxItem(i, j)
            if itemID then
                mail[itemID] = (mail[itemID] or 0) + (count or 1)
                ns.FillItemMeta(itemID)
            end
        end
    end
    c.mail = mail
    c.mailT = time()
    if ns.ReadPurchaseMail then ns.ReadPurchaseMail() end
end

-- Everything you own, across every character on this Auction House --------------

local function shortName(charKey)
    return (charKey:match("^([^-]+)")) or charKey
end

-- returns total, { {who, where, n}, ... } for one item across all characters on this realm/faction
function ns.Owned(itemID)
    local realmKey = ns.RealmKey()
    local total, parts = 0, {}
    for key, c in pairs(MyFA_DB.chars) do
        if c.realmKey == realmKey then
            for _, where in ipairs({ "bags", "bank", "mail" }) do
                local n = c[where] and c[where][itemID]
                if n and n > 0 then
                    total = total + n
                    parts[#parts + 1] = { shortName(key), where, n }
                end
            end
        end
    end
    local wb = MyFA_DB.warband
    if wb and wb.realmKey == realmKey and wb.items and wb.items[itemID] then
        total = total + wb.items[itemID]
        parts[#parts + 1] = { "Warband", "bank", wb.items[itemID] }
    end
    return total, parts
end

function ns.WhereText(parts, limit)
    local out = {}
    for i, p in ipairs(parts) do
        if limit and i > limit then out[#out + 1] = "+" .. (#parts - limit) .. " more"; break end
        out[#out + 1] = string.format("%s %s %d", p[1], p[2], p[3])
    end
    return table.concat(out, ", ")
end

function ns.AllGold()
    local realmKey, sum = ns.RealmKey(), 0
    for _, c in pairs(MyFA_DB.chars) do
        if c.realmKey == realmKey then sum = sum + (c.money or 0) end
    end
    return sum
end

-- "1g20s50c", "20s", "1450" -> copper
function ns.ParseMoney(text)
    if not text or text == "" then return nil end
    text = text:lower():gsub("%s+", "")
    if text:match("^%d+$") then return tonumber(text) end
    local g = tonumber(text:match("(%d+)g")) or 0
    local s = tonumber(text:match("(%d+)s")) or 0
    local c = tonumber(text:match("(%d+)c")) or 0
    local total = g * 10000 + s * 100 + c
    return total > 0 and total or nil
end

-- Recipes (modern profession API; silently skipped if the client lacks it) ---

function ns.SnapshotRecipes()
    local TS = C_TradeSkillUI
    if not (TS and TS.GetAllRecipeIDs and TS.GetRecipeInfo and TS.GetRecipeSchematic) then return end
    local ok, err = pcall(function()
        local profName
        local c = ns.Char()
        if TS.GetBaseProfessionInfo then
            local p = TS.GetBaseProfessionInfo()
            profName = p and p.professionName
            if profName and p.skillLevel then
                c.profs = c.profs or {}
                c.profs[profName] = { p.skillLevel, p.maxSkillLevel }
            end
        end
        local count = 0
        for _, recipeID in ipairs(TS.GetAllRecipeIDs() or {}) do
            local info = TS.GetRecipeInfo(recipeID)
            if info and info.learned then
                local sch = TS.GetRecipeSchematic(recipeID, false)
                if sch and sch.outputItemID then
                    local reagents = {}
                    for _, slot in ipairs(sch.reagentSlotSchematics or {}) do
                        local isBasic = slot.required
                        if Enum and Enum.CraftingReagentType and slot.reagentType ~= nil then
                            isBasic = isBasic or slot.reagentType == Enum.CraftingReagentType.Basic
                        end
                        local first = slot.reagents and slot.reagents[1]
                        if isBasic and first and first.itemID then
                            reagents[#reagents + 1] = { first.itemID, slot.quantityRequired or 1 }
                            ns.FillItemMeta(first.itemID)
                        end
                    end
                    ns.FillItemMeta(sch.outputItemID)
                    c.recipes[recipeID] = {
                        n = info.name, p = profName, o = sch.outputItemID,
                        qa = sch.quantityMin or 1, qb = sch.quantityMax or sch.quantityMin or 1,
                        r = reagents,
                    }
                    count = count + 1
                end
            end
        end
        if count > 0 then
            ns.recipeNoticeShown = ns.recipeNoticeShown or {}
            local key = profName or "?"
            if not ns.recipeNoticeShown[key] then
                ns.Print(string.format("recorded %d %s recipes.", count, profName or "profession"))
                ns.recipeNoticeShown[key] = true
            end
        end
    end)
    if not ok then ns.Print("could not read recipes: " .. tostring(err)) end
end

-- Merchant buy prices (vials, thread, flux...) --------------------------------

function ns.SnapshotMerchant()
    local n = GetMerchantNumItems and GetMerchantNumItems() or 0
    for i = 1, n do
        local itemID = GetMerchantItemID and GetMerchantItemID(i)
        local price, qty, extended
        if C_MerchantFrame and C_MerchantFrame.GetItemInfo then
            local info = C_MerchantFrame.GetItemInfo(i)
            if info then price, qty, extended = info.price, info.stackCount, info.hasExtendedCost end
        elseif GetMerchantItemInfo then
            local _
            _, _, price, qty, _, _, _, extended = GetMerchantItemInfo(i)
        end
        if itemID and price and price > 0 and not extended then
            MyFA_DB.vendorBuy[itemID] = math.floor(price / math.max(qty or 1, 1))
        end
    end
end

-- Events ---------------------------------------------------------------------

local f = CreateFrame("Frame")
ns.eventFrame = f
f:RegisterEvent("ADDON_LOADED")
f:RegisterEvent("PLAYER_LOGIN")
f:RegisterEvent("PLAYER_LOGOUT")
f:RegisterEvent("BAG_UPDATE_DELAYED")
f:RegisterEvent("PLAYER_MONEY")
f:RegisterEvent("TRADE_SKILL_LIST_UPDATE")
f:RegisterEvent("MERCHANT_SHOW")
f:RegisterEvent("ITEM_DATA_LOAD_RESULT")
f:RegisterEvent("BANKFRAME_OPENED")
f:RegisterEvent("BANKFRAME_CLOSED")
pcall(f.RegisterEvent, f, "PLAYERBANKSLOTS_CHANGED")
f:RegisterEvent("MAIL_SHOW")
for _, e in ipairs({ "PLAYER_LEVEL_UP", "SKILL_LINES_CHANGED", "ZONE_CHANGED_NEW_AREA" }) do pcall(f.RegisterEvent, f, e) end
f:RegisterEvent("MAIL_INBOX_UPDATE")
f:RegisterEvent("MAIL_CLOSED")

f:SetScript("OnEvent", function(_, event, arg1, arg2)
    if event == "ADDON_LOADED" and arg1 == ADDON then
        MyFA_DB = MyFA_DB or {}
        copyDefaults(MyFA_DB, DB_DEFAULTS)
        MyFA_DB.addonVersion = ns.VERSION
        MyFA_DB.settings.roi = MyFA_DB.settings.roi or 0.15
        if MyFA_DB.settings.alerts == nil then MyFA_DB.settings.alerts = true end
    elseif event == "PLAYER_LOGIN" then
        ns.SnapshotBags()
        ns.SnapshotProfile()
        if ns.OnLogin then ns.OnLogin() end
    elseif event == "PLAYER_LOGOUT" then
        ns.SnapshotBags()
    elseif event == "BAG_UPDATE_DELAYED" or event == "PLAYER_MONEY" then
        ns.SnapshotBags()
        if bankOpen then ns.SnapshotBank() end
    elseif event == "BANKFRAME_OPENED" then
        bankOpen = true
        ns.SnapshotBank()
    elseif event == "PLAYERBANKSLOTS_CHANGED" then
        ns.SnapshotBank()
    elseif event == "BANKFRAME_CLOSED" then
        ns.SnapshotBank()
        bankOpen = false
    elseif event == "PLAYER_LEVEL_UP" or event == "SKILL_LINES_CHANGED" or event == "ZONE_CHANGED_NEW_AREA" then
        if C_Timer then C_Timer.After(0.5, ns.SnapshotProfile) else ns.SnapshotProfile() end
    elseif event == "MAIL_SHOW" or event == "MAIL_INBOX_UPDATE" or event == "MAIL_CLOSED" then
        ns.SnapshotMail()
    elseif event == "TRADE_SKILL_LIST_UPDATE" then
        ns.SnapshotRecipes()
    elseif event == "MERCHANT_SHOW" then
        ns.SnapshotMerchant()
    elseif event == "ITEM_DATA_LOAD_RESULT" then
        if arg2 and pendingMeta[arg1] then ns.FillItemMeta(arg1) end
    end
end)

-- Slash ----------------------------------------------------------------------

SLASH_MYFA1 = "/myfa"
SLASH_MYFA2 = "/mfa"
local HELP = {
    "/myfa - show or hide the panel",
    "/myfa scan - full Auction House scan (once every 15 min)",
    "/myfa status - data and targets age",
    "/myfa add - open the Add flip window (or use + Add flip on the My flips tab)",
    "/myfa bought [item] qty price - track something you bought earlier, e.g. /myfa bought [Golden Sansam] 20 14s50c",
    "/myfa forget [item] - stop tracking an item's flip",
    "/myfa roi 20 - alert when a flip is worth 20%% profit after the cut (now %d%%)",
    "/myfa alerts on|off - sell alerts",
    "/myfa dock - snap the panel back beside the Auction House",
}

SlashCmdList.MYFA = function(msg)
    msg = (msg or ""):gsub("^%s+", ""):gsub("%s+$", "")
    local cmd, rest = msg:match("^(%S*)%s*(.-)$")
    cmd = (cmd or ""):lower()
    if cmd == "scan" then
        ns.StartScan()
    elseif cmd == "status" then
        local r = MyFA_DB.realms[ns.RealmKey()]
        if r and r.lastScan then
            ns.Print(string.format("%s: last full scan %d min ago, %d auctions, %d items.",
                ns.RealmKey(), math.floor((time() - r.lastScan) / 60), r.auctions or 0, r.itemCount or 0))
        else
            ns.Print("no scan yet for " .. ns.RealmKey() .. ". Open the Auction House and press Full scan.")
        end
        local t = MyFA_Targets
        if t and t.generated then
            ns.Print(string.format("targets from Desk: %d min old, %d buys, %d sells, %d crafts.",
                math.floor((time() - t.generated) / 60), #(t.buys or {}), #(t.sells or {}), #(t.crafts or {})))
        else
            ns.Print("no targets loaded yet. Run MyFA Desk, then /reload.")
        end
        local n = ns.Positions and #ns.Positions() or 0
        ns.Print(string.format("tracking %d flips; alerts %s at %d%% profit. MyFA %s.", n,
            MyFA_DB.settings.alerts and "on" or "off", math.floor(MyFA_DB.settings.roi * 100 + 0.5), ns.VERSION))
        ns.Print(MyFA_DB.lastBuyT and string.format("last purchase recorded %d min ago.", math.floor((time() - MyFA_DB.lastBuyT) / 60))
            or "no purchases recorded yet. Buy something, or open your mailbox so MyFA can read your Auction won mails.")
    elseif cmd == "bought" or cmd == "forget" then
        local itemID = tonumber(rest:match("item:(%d+)")) or tonumber(rest:match("^(%d+)"))
        local after = rest:gsub("|c%x+|H.-|h.-|h|r", ""):gsub("^%d+", "")
        if not itemID then
            ns.Print("shift-click the item into the command, e.g. /myfa " .. cmd .. " [Golden Sansam]" .. (cmd == "bought" and " 20 14s50c" or ""))
            return
        end
        ns.FillItemMeta(itemID)
        if cmd == "forget" then
            ns.ForgetFlip(itemID)
            return
        end
        local qty, price = after:match("^%s*(%d+)%s+(%S+)")
        price = ns.ParseMoney(price)
        if not qty or not price then
            ns.Print("usage: /myfa bought [item] qty price-each, e.g. /myfa bought [Golden Sansam] 20 14s50c")
            return
        end
        ns.RecordBuy(itemID, tonumber(qty), price, true)
    elseif cmd == "roi" then
        local v = tonumber(rest)
        if v and v > 0 then
            MyFA_DB.settings.roi = v / 100
            ns.Print(string.format("sell alerts now fire at %d%% profit after the cut.", v))
            if ns.CheckFlips then ns.CheckFlips() end
        else
            ns.Print("usage: /myfa roi 20")
        end
    elseif cmd == "alerts" then
        MyFA_DB.settings.alerts = rest:lower() ~= "off"
        ns.Print("sell alerts " .. (MyFA_DB.settings.alerts and "on." or "off."))
    elseif cmd == "add" then
        if ns.ShowAddFlip then ns.ShowAddFlip() end
    elseif cmd == "dock" then
        if ns.Redock then ns.Redock() end
    elseif cmd == "help" or cmd == "?" then
        for i, line in ipairs(HELP) do
            ns.Print(i == 7 and string.format(line, math.floor(MyFA_DB.settings.roi * 100 + 0.5)) or line)
        end
    else
        if ns.TogglePanel then ns.TogglePanel() end
    end
end
