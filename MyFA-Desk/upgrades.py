"""Gear upgrades on the Auction House for each character, scored for the class and specs you pick.

The addon records what each character wears and the stats of every gear listing it scans (MyFA_DB.gear).
Here each item gets a score = sum(stat x weight) for a spec, and an upgrade is an item you can use that
scores higher than what you wear in that slot. Weights are classic-style approximations, normalised so the
spec's main stat is about 1. Edit data/stat_weights.json to change them (Desk writes it on first run).
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
WEIGHTS_FILE = DATA / "stat_weights.json"
SETTINGS_FILE = DATA / "upgrade_specs.json"

# canonical stat names: what the addon reports -> what weights use
ALIASES = {
    "STRENGTH": "STR", "AGILITY": "AGI", "STAMINA": "STA", "INTELLECT": "INT", "SPIRIT": "SPI",
    "RESISTANCE0": "ARMOR", "ATTACK_POWER": "AP", "RANGED_ATTACK_POWER": "RAP", "FERAL_ATTACK_POWER": "FAP",
    "POWER_REGEN0": "MP5", "MANA_REGENERATION": "MP5", "SPELL_HEALING_DONE": "HEAL", "SPELL_DAMAGE_DONE": "SP",
    "SPELL_POWER": "SP", "CRIT_RATING": "CRIT", "CRIT_MELEE_RATING": "CRIT", "CRIT_SPELL_RATING": "SCRIT",
    "HIT_RATING": "HIT", "HIT_MELEE_RATING": "HIT", "HIT_SPELL_RATING": "SHIT", "DEFENSE_SKILL_RATING": "DEF",
    "DODGE_RATING": "DODGE", "PARRY_RATING": "PARRY", "BLOCK_RATING": "BLOCK", "BLOCK_VALUE": "BLOCKVAL",
    "DAMAGE_PER_SECOND": "DPS", "HEALTH_REGEN": "HP5",
}
STAT_LABEL = {
    "STR": "Strength", "AGI": "Agility", "STA": "Stamina", "INT": "Intellect", "SPI": "Spirit", "ARMOR": "Armor",
    "AP": "attack power", "RAP": "ranged attack power", "FAP": "feral attack power", "MP5": "mana per 5s",
    "HEAL": "healing", "SP": "spell damage and healing", "CRIT": "% crit", "SCRIT": "% spell crit", "HIT": "% hit",
    "SHIT": "% spell hit", "DEF": "defense", "DODGE": "% dodge", "PARRY": "% parry", "BLOCK": "% block",
    "BLOCKVAL": "block value", "DPS": "weapon DPS", "FIRE": "fire damage", "FROST": "frost damage",
    "SHADOW": "shadow damage", "ARCANE": "arcane damage", "NATURE": "nature damage", "HOLY": "holy damage",
    "HP5": "health per 5s",
}
PERCENT = {"CRIT", "SCRIT", "HIT", "SHIT", "DODGE", "PARRY", "BLOCK"}

# ---- stat weights per class and spec (value of one point; % stats per 1%) -----------------------------
_MELEE = {"STR": 1.0, "AGI": 0.7, "AP": 0.5, "CRIT": 14, "HIT": 15, "STA": 0.1, "DPS": 5}
DEFAULT_WEIGHTS = {
    "WARRIOR": {
        "Arms": {**_MELEE},
        "Fury": {**_MELEE, "DPS": 4},
        "Protection": {"STA": 1.0, "DEF": 1.2, "ARMOR": 0.08, "DODGE": 12, "PARRY": 10, "BLOCK": 6, "BLOCKVAL": 0.3,
                       "STR": 0.4, "AGI": 0.6, "HIT": 4, "DPS": 1},
    },
    "PALADIN": {
        "Holy": {"HEAL": 1.0, "SP": 1.0, "INT": 1.0, "SCRIT": 15, "MP5": 2.5, "SPI": 0.15, "STA": 0.3},
        "Protection": {"STA": 1.0, "DEF": 1.2, "ARMOR": 0.08, "DODGE": 12, "PARRY": 10, "BLOCK": 6, "BLOCKVAL": 0.3,
                       "SP": 0.6, "HOLY": 0.6, "INT": 0.4, "STR": 0.3},
        "Retribution": {**_MELEE, "INT": 0.2, "SP": 0.2},
    },
    "HUNTER": {
        "Beast Mastery": {"AGI": 1.0, "RAP": 0.5, "AP": 0.45, "CRIT": 14, "HIT": 16, "INT": 0.2, "STA": 0.1, "DPS": 5},
        "Marksmanship": {"AGI": 1.0, "RAP": 0.5, "AP": 0.45, "CRIT": 15, "HIT": 16, "INT": 0.2, "STA": 0.1, "DPS": 6},
        "Survival": {"AGI": 1.1, "RAP": 0.5, "AP": 0.45, "CRIT": 14, "HIT": 16, "INT": 0.2, "STA": 0.15, "DPS": 5},
    },
    "ROGUE": {
        "Assassination": {"AGI": 1.0, "STR": 0.5, "AP": 0.5, "CRIT": 15, "HIT": 16, "STA": 0.1, "DPS": 4},
        "Combat": {"AGI": 1.0, "STR": 0.5, "AP": 0.5, "CRIT": 14, "HIT": 18, "STA": 0.1, "DPS": 5},
        "Subtlety": {"AGI": 1.0, "STR": 0.5, "AP": 0.5, "CRIT": 14, "HIT": 15, "STA": 0.15, "DPS": 4},
    },
    "PRIEST": {
        "Holy": {"HEAL": 1.0, "SP": 1.0, "INT": 0.7, "SPI": 0.9, "MP5": 3.0, "SCRIT": 8, "STA": 0.2},
        "Discipline": {"HEAL": 1.0, "SP": 1.0, "INT": 0.8, "SPI": 0.7, "MP5": 3.0, "SCRIT": 8, "STA": 0.25},
        "Shadow": {"SP": 1.0, "SHADOW": 1.0, "SHIT": 13, "SCRIT": 8, "INT": 0.3, "SPI": 0.2, "STA": 0.2},
    },
    "SHAMAN": {
        "Elemental": {"SP": 1.0, "NATURE": 1.0, "FIRE": 0.5, "SCRIT": 12, "SHIT": 13, "INT": 0.4, "MP5": 1.0, "STA": 0.2},
        "Enhancement": {**_MELEE, "INT": 0.2},
        "Restoration": {"HEAL": 1.0, "SP": 1.0, "INT": 0.8, "MP5": 3.0, "SCRIT": 9, "SPI": 0.2, "STA": 0.2},
    },
    "MAGE": {
        "Arcane": {"SP": 1.0, "ARCANE": 1.0, "SCRIT": 11, "SHIT": 13, "INT": 0.5, "SPI": 0.2, "STA": 0.2},
        "Fire": {"SP": 1.0, "FIRE": 1.0, "SCRIT": 12, "SHIT": 13, "INT": 0.4, "SPI": 0.1, "STA": 0.2},
        "Frost": {"SP": 1.0, "FROST": 1.0, "SCRIT": 10, "SHIT": 13, "INT": 0.4, "SPI": 0.1, "STA": 0.2},
    },
    "WARLOCK": {
        "Affliction": {"SP": 1.0, "SHADOW": 1.0, "SHIT": 13, "SCRIT": 6, "INT": 0.3, "STA": 0.4, "SPI": 0.05},
        "Demonology": {"SP": 1.0, "SHADOW": 1.0, "FIRE": 0.4, "SHIT": 13, "SCRIT": 8, "INT": 0.3, "STA": 0.5},
        "Destruction": {"SP": 1.0, "SHADOW": 1.0, "FIRE": 0.6, "SHIT": 13, "SCRIT": 12, "INT": 0.3, "STA": 0.3},
    },
    "DRUID": {
        "Balance": {"SP": 1.0, "NATURE": 1.0, "ARCANE": 1.0, "SCRIT": 11, "SHIT": 13, "INT": 0.4, "SPI": 0.2, "STA": 0.2},
        "Feral (cat)": {"STR": 1.2, "AGI": 1.0, "FAP": 0.5, "AP": 0.5, "CRIT": 14, "HIT": 15, "STA": 0.1},
        "Feral (bear)": {"STA": 1.0, "ARMOR": 0.1, "AGI": 0.6, "DEF": 1.0, "DODGE": 12, "STR": 0.4, "FAP": 0.15,
                         "AP": 0.15, "HIT": 4},
        "Restoration": {"HEAL": 1.0, "SP": 1.0, "INT": 0.8, "SPI": 0.8, "MP5": 3.0, "SCRIT": 7, "STA": 0.2},
    },
}
CLASS_NAMES = {"WARRIOR": "Warrior", "PALADIN": "Paladin", "HUNTER": "Hunter", "ROGUE": "Rogue", "PRIEST": "Priest",
               "SHAMAN": "Shaman", "MAGE": "Mage", "WARLOCK": "Warlock", "DRUID": "Druid"}
DEFAULT_SPECS = {"WARRIOR": ("Fury", "Protection"), "PALADIN": ("Holy", "Retribution"), "HUNTER": ("Marksmanship", "Survival"),
                 "ROGUE": ("Combat", "Assassination"), "PRIEST": ("Holy", "Shadow"), "SHAMAN": ("Restoration", "Elemental"),
                 "MAGE": ("Frost", "Fire"), "WARLOCK": ("Affliction", "Destruction"), "DRUID": ("Restoration", "Feral (cat)")}

# ---- what each class can wear -----------------------------------------------------------------------
# armor subclasses: 0 misc (rings, necks, trinkets, held in off-hand), 1 cloth, 2 leather, 3 mail, 4 plate,
# 6 shield, 7 libram, 8 idol, 9 totem
ARMOR = {
    "WARRIOR": {0: 1, 1: 1, 2: 1, 3: 1, 4: 40, 6: 1}, "PALADIN": {0: 1, 1: 1, 2: 1, 3: 1, 4: 40, 6: 1, 7: 1},
    "HUNTER": {0: 1, 1: 1, 2: 1, 3: 40}, "ROGUE": {0: 1, 1: 1, 2: 1}, "PRIEST": {0: 1, 1: 1},
    "SHAMAN": {0: 1, 1: 1, 2: 1, 3: 40, 6: 1, 9: 1}, "MAGE": {0: 1, 1: 1}, "WARLOCK": {0: 1, 1: 1},
    "DRUID": {0: 1, 1: 1, 2: 1, 8: 1},
}
# weapon subclasses: 0 axe 1H, 1 axe 2H, 2 bow, 3 gun, 4 mace 1H, 5 mace 2H, 6 polearm, 7 sword 1H, 8 sword 2H,
# 10 staff, 13 fist, 15 dagger, 16 thrown, 18 crossbow, 19 wand
WEAPONS = {
    "WARRIOR": {0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 13, 15, 16, 18}, "PALADIN": {0, 1, 4, 5, 6, 7, 8},
    "HUNTER": {0, 1, 2, 3, 6, 7, 8, 10, 13, 15, 16, 18}, "ROGUE": {2, 3, 4, 7, 13, 15, 16, 18},
    "PRIEST": {4, 10, 15, 19}, "SHAMAN": {0, 1, 4, 5, 10, 13, 15}, "MAGE": {7, 10, 15, 19},
    "WARLOCK": {7, 10, 15, 19}, "DRUID": {4, 5, 10, 13, 15},
}
DUAL_WIELD = {"WARRIOR", "ROGUE", "HUNTER"}       # who can hold a weapon in the off hand
CASTER_OFFHAND = {"PRIEST", "MAGE", "WARLOCK", "DRUID", "SHAMAN", "PALADIN"}
RANGED_SPECS = {"Beast Mastery", "Marksmanship", "Survival"}

SLOT_NAME = {1: "Head", 2: "Neck", 3: "Shoulders", 5: "Chest", 6: "Waist", 7: "Legs", 8: "Feet", 9: "Wrists",
             10: "Hands", 11: "Ring", 13: "Trinket", 15: "Back", 16: "Main hand", 17: "Off hand", 18: "Ranged"}
LOC_SLOT = {
    "INVTYPE_HEAD": 1, "INVTYPE_NECK": 2, "INVTYPE_SHOULDER": 3, "INVTYPE_CHEST": 5, "INVTYPE_ROBE": 5,
    "INVTYPE_WAIST": 6, "INVTYPE_LEGS": 7, "INVTYPE_FEET": 8, "INVTYPE_WRIST": 9, "INVTYPE_HAND": 10,
    "INVTYPE_FINGER": 11, "INVTYPE_TRINKET": 13, "INVTYPE_CLOAK": 15, "INVTYPE_WEAPON": 16,
    "INVTYPE_WEAPONMAINHAND": 16, "INVTYPE_2HWEAPON": 16, "INVTYPE_WEAPONOFFHAND": 17, "INVTYPE_SHIELD": 17,
    "INVTYPE_HOLDABLE": 17, "INVTYPE_RANGED": 18, "INVTYPE_RANGEDRIGHT": 18, "INVTYPE_THROWN": 18,
    "INVTYPE_RELIC": 18,
}


WEIGHTS_VERSION = 2
# healer weights before version 2 (too little value on mana); an unedited copy of these is upgraded
_V1_HEALERS = {'PALADIN|Holy': {'HEAL': 1.0, 'SP': 1.0, 'INT': 1.0, 'SCRIT': 15, 'MP5': 2.0, 'SPI': 0.1, 'STA': 0.3}, 'PRIEST|Holy': {'HEAL': 1.0, 'SP': 1.0, 'INT': 0.6, 'SPI': 0.5, 'MP5': 2.0, 'SCRIT': 8, 'STA': 0.2}, 'PRIEST|Discipline': {'HEAL': 1.0, 'SP': 1.0, 'INT': 0.7, 'SPI': 0.4, 'MP5': 2.0, 'SCRIT': 8, 'STA': 0.25}, 'SHAMAN|Restoration': {'HEAL': 1.0, 'SP': 1.0, 'INT': 0.6, 'MP5': 2.2, 'SCRIT': 9, 'SPI': 0.1, 'STA': 0.2}, 'DRUID|Restoration': {'HEAL': 1.0, 'SP': 1.0, 'INT': 0.6, 'SPI': 0.5, 'MP5': 2.0, 'SCRIT': 7, 'STA': 0.2}}

# how much a character cares about mana against raw healing or damage: multiplies Intellect, Spirit and mana per 5s
MANA_STYLES = {
    "healing": ("Healing first (short fights)", 0.6),
    "balanced": ("Balanced", 1.0),
    "mana": ("Mana first (long fights, leveling, PvP)", 1.6),
}
MANA_STATS = ("MP5", "SPI", "INT")


def weights():
    """The weights in use: data/stat_weights.json if you've edited it, else the defaults (written there once)."""
    w = None
    try:
        w = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not isinstance(w, dict) or not w:
        w = json.loads(json.dumps(DEFAULT_WEIGHTS))
        w["_version"] = WEIGHTS_VERSION
        _write_weights(w)
    elif int(w.get("_version") or 1) < WEIGHTS_VERSION:
        for key, old in _V1_HEALERS.items():
            cls, spec = key.split("|")
            if (w.get(cls) or {}).get(spec) == old:
                w[cls][spec] = dict(DEFAULT_WEIGHTS[cls][spec])
        w["_version"] = WEIGHTS_VERSION
        _write_weights(w)
    return {c: v for c, v in w.items() if not c.startswith("_") and isinstance(v, dict)}


def _write_weights(w):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        WEIGHTS_FILE.write_text(json.dumps(w, indent=1), encoding="utf-8")
    except OSError:
        pass


def styled(w, style):
    """The spec's weights with the character's healing-or-mana choice applied."""
    f = MANA_STYLES.get(style or "balanced", MANA_STYLES["balanced"])[1]
    return {k: (v * f if k in MANA_STATS else v) for k, v in w.items()}


def uses_mana(cls, wts):
    return any(any(k in MANA_STATS and v >= 0.3 for k, v in sw.items()) for sw in (wts.get(cls) or {}).values())


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(char_key, cls, main, off, pvp, mana="balanced"):
    s = load_settings()
    s[char_key] = {"class": cls, "main": main, "off": off, "pvp": bool(pvp),
                   "mana": mana if mana in MANA_STYLES else "balanced"}
    DATA.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def parse_stats(st):
    """'STA=10;STAMINA=10;INT=7' -> {'STA': 10, 'INT': 7} (same stat from two sources counts once)."""
    out = {}
    for part in (st or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = ALIASES.get(k, k)
        try:
            out[k] = max(out.get(k, 0), float(v))
        except ValueError:
            pass
    return out


def score(stats, w, slot, cls, spec, pvp=False):
    total = 0.0
    for k, v in stats.items():
        wt = w.get(k, 0)
        if k == "STA" and pvp:
            wt = max(wt, 0.8)    # PvP: staying alive is worth a lot more
        if k == "DPS":
            # weapon speed matters only for the hand that uses it
            if spec in RANGED_SPECS:
                wt = wt if slot == 18 else wt * 0.1
            elif slot == 18:
                wt = 0
            elif slot == 17:
                wt = wt * 0.5 if cls in DUAL_WIELD else 0
        total += v * wt
    return total


def usable(g, cls, level):
    """(can wear now, reason if not)"""
    if g.get("lvl", 0) > level:
        return False
    if g.get("cl") and CLASS_NAMES.get(cls, cls) not in [c.strip() for c in g["cl"].split(",")]:
        return False
    k, u, loc = g.get("k"), g.get("u"), g.get("loc")
    if k == 4:
        need = ARMOR.get(cls, {}).get(u)
        if need is None or level < need:
            return False
        if loc == "INVTYPE_HOLDABLE" and cls not in CASTER_OFFHAND:
            return False
    elif k == 2:
        if u not in WEAPONS.get(cls, set()):
            return False
        if loc == "INVTYPE_WEAPONOFFHAND" and cls not in DUAL_WIELD:
            return False
    else:
        return False
    return True


def change_stats(new, old, w, n=5):
    """What changes if you swap, the stats that matter most first: '+11 healing, −6 Spirit, −4 mana per 5s'."""
    keys = {k for k in set(new) | set(old) if w.get(k, 0) > 0}
    ranked = sorted(((abs((new.get(k, 0) - old.get(k, 0)) * w[k]), k, new.get(k, 0) - old.get(k, 0)) for k in keys), reverse=True)
    parts = []
    for _, k, d in ranked[:n]:
        if abs(d) < 0.05:
            continue
        label = STAT_LABEL.get(k, k.lower())
        sign = "+" if d > 0 else "\u2212"
        parts.append(f"{sign}{abs(d):g}{label}" if k in PERCENT else f"{sign}{abs(d):g} {label}")
    return ", ".join(parts)


def weights_text(w):
    """'healing 1 · mana per 5s 3 · Spirit 0.8 …' for the weights that count, biggest first."""
    ranked = sorted(((v, k) for k, v in w.items() if v > 0 and k not in PERCENT and k != "DPS"), reverse=True)
    return " \u00b7 ".join(f"{STAT_LABEL.get(k, k.lower())} {round(v, 2):g}" for v, k in ranked[:7])


def key_stats(stats, w):
    """The stats that matter for this spec, biggest first: '+12 Intellect, +22 healing'."""
    ranked = sorted(((v * w.get(k, 0), k, v) for k, v in stats.items() if w.get(k, 0) > 0), reverse=True)
    parts = []
    for _, k, v in ranked[:4]:
        label = STAT_LABEL.get(k, k.lower())
        parts.append(f"+{v:g}{label}" if k in PERCENT else f"+{v:g} {label}")
    return ", ".join(parts)


def merge_listings(realm, neutral_realm):
    """Cheapest price per gear item across your faction's and the neutral Auction House; where = keys cheaper at neutral."""
    merged, where = {}, {}
    for label, rr in (("", realm), ("Neutral AH", neutral_realm)):
        for k, v in ((rr or {}).get("gear") or {}).items():
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            k = str(k)
            if k not in merged or v < merged[k]:
                merged[k] = v
                if label:
                    where[k] = label
                else:
                    where.pop(k, None)
    return merged, where


def _worn(char):
    g = char.get("gear")
    if isinstance(g, dict):
        return {int(s): str(k) for s, k in g.items()}
    if isinstance(g, list):
        return {i + 1: str(k) for i, k in enumerate(g) if k}
    return {}


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except ValueError:
        return (0,)


def status(db, listings, chars):
    """What the Gear upgrades tab needs and what it has, so an empty tab can say which step is missing."""
    info = db.get("gear") or {}
    st = {"version": db.get("addonVersion"), "old_addon": False, "listings": len(listings),
          "read": sum(1 for k in listings if k in info), "chars": {}, "unseen": []}
    st["old_addon"] = bool(st["version"]) and _ver(st["version"]) < (1, 9, 0)
    for key, c in chars:
        if not isinstance(c, dict):
            continue
        worn = _worn(c)
        if not worn:
            st["unseen"].append(key.split("-")[0])
            continue
        st["chars"][key] = {"worn": len(worn), "read": sum(1 for k in worn.values() if k in info)}
    return st


def find_upgrades(db, realm, char_key, char, settings, wts, limit=40, where=None):
    """Upgrades for one character: {'class', 'level', 'specs': [{'spec', 'items': [...]}, ...]}."""
    gear_info = db.get("gear") or {}
    cls = (settings.get("class") or char.get("classFile") or "").upper()
    if cls not in wts:
        return None
    level = int(char.get("level") or 1)
    worn = _worn(char)
    main = settings.get("main") or DEFAULT_SPECS.get(cls, ("", ""))[0]
    off = settings.get("off") if "off" in settings else DEFAULT_SPECS.get(cls, ("", ""))[1]
    pvp = bool(settings.get("pvp"))
    mana = settings.get("mana") if settings.get("mana") in MANA_STYLES else "balanced"
    listings = {str(k): int(v) for k, v in ((realm or {}).get("gear") or {}).items()}
    out = {"class": cls, "level": level, "main": main, "off": off, "pvp": pvp, "mana": mana,
           "uses_mana": uses_mana(cls, wts), "specs": [], "worn": len(worn)}

    def stats_of(key):
        g = gear_info.get(key)
        return parse_stats(g.get("st")) if g else {}

    for spec in [s for s in (main, off) if s]:
        w = wts[cls].get(spec)
        if not w:
            continue
        w = styled(w, mana)

        def sc(key, slot):
            return score(stats_of(key), w, slot, cls, spec, pvp)

        # what you have now, per slot (rings and trinkets: the weaker one is what you'd replace)
        cur = {}
        for slot in (1, 2, 3, 5, 6, 7, 8, 9, 10, 15, 18):
            cur[slot] = (sc(worn[slot], slot), worn[slot]) if slot in worn else (0.0, None)
        for a, b in ((11, 12), (13, 14)):
            pair = sorted([(sc(worn[x], x), worn[x]) if x in worn else (0.0, None) for x in (a, b)], key=lambda t: t[0])
            cur[a] = pair[0]
        mh = (sc(worn[16], 16), worn[16]) if 16 in worn else (0.0, None)
        oh = (sc(worn[17], 17), worn[17]) if 17 in worn else (0.0, None)
        two_hander = 16 in worn and (gear_info.get(worn[16]) or {}).get("loc") == "INVTYPE_2HWEAPON"

        items = []
        for key, price in listings.items():
            g = gear_info.get(key)
            if not g or not usable(g, cls, level):
                continue
            slot = LOC_SLOT.get(g.get("loc"))
            if not slot:
                continue
            if g.get("k") == 4 and g.get("u") in (7, 8, 9):
                slot = 18   # relics share the ranged slot
            new = sc(key, slot)
            old_stats = None
            if g.get("loc") == "INVTYPE_2HWEAPON":
                old, old_key = mh[0] + oh[0], mh[1]
                old_stats = {}
                for k_ in (mh[1], oh[1]):
                    for a_, b_ in (stats_of(k_) if k_ else {}).items():
                        old_stats[a_] = old_stats.get(a_, 0) + b_
            elif slot == 16:
                old, old_key = mh   # a one-hander against your main hand (or your two-hander, with an empty off hand)
            elif slot == 17:
                if two_hander:
                    continue       # an off-hand needs a one-handed weapon first
                old, old_key = oh
            else:
                old, old_key = cur.get(slot, (0.0, None))
            gain = new - old
            if gain <= 0.5:
                continue
            items.append({
                "key": key, "id": int(key.split(":")[0]), "name": g.get("n") or key, "q": g.get("q") or 1,
                "slot": SLOT_NAME.get(slot, "?"), "price": price, "gain": round(gain, 1),
                "pct": round(gain / old * 100) if old > 0 else None, "per_gold": round(gain / max(price / 10000, 0.01), 2),
                "replaces": (gear_info.get(old_key) or {}).get("n") if old_key else None, "empty": old_key is None,
                "stats": change_stats(stats_of(key), old_stats if old_stats is not None else (stats_of(old_key) if old_key else {}), w),
                "lvl": g.get("lvl", 0), "where": (where or {}).get(key, ""),
            })
        # most upgrade for the gold first
        items.sort(key=lambda r: -r["per_gold"])
        out["specs"].append({"spec": spec, "items": items[:limit], "count": len(items), "weights": weights_text(w)})
    return out


def all_upgrades(db, realm, chars, realm_key, where=None):
    """Upgrades for every character on this realm and faction, with their spec settings."""
    wts = weights()
    settings = load_settings()
    out = {}
    for key, c in chars:
        if not isinstance(c, dict) or not c.get("gear"):
            continue
        res = find_upgrades(db, realm, key, c, settings.get(key, {}), wts, where=where)
        if res:
            out[key] = res
    return out, wts
