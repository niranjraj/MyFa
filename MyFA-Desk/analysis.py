"""Price history and profit analysis for MyFA Desk."""
import datetime
import json
import math
import sqlite3
import statistics
import time
from pathlib import Path

import bbb
import pnl
import upgrades as upg

DAY = 86400
NEUTRAL_SUFFIX = "-NeutralAH"   # the addon stores neutral (goblin) Auction House scans under "<realm>-NeutralAH"

# Skill needed to gather (classic values; Forever may differ for some nodes and its new herbs aren't known yet)
GATHER_SKILL = {
    "Peacebloom": 1, "Silverleaf": 1, "Earthroot": 15, "Mageroyal": 50, "Briarthorn": 70, "Stranglekelp": 85,
    "Bruiseweed": 100, "Wild Steelbloom": 115, "Grave Moss": 120, "Kingsblood": 125, "Liferoot": 150, "Fadeleaf": 160,
    "Goldthorn": 170, "Khadgar's Whisker": 185, "Wintersbite": 195, "Firebloom": 205, "Purple Lotus": 210,
    "Arthas' Tears": 220, "Sungrass": 230, "Blindweed": 235, "Ghost Mushroom": 245, "Gromsblood": 250,
    "Golden Sansam": 260, "Dreamfoil": 270, "Mountain Silversage": 280, "Plaguebloom": 285, "Icecap": 290,
    "Black Lotus": 300, "Copper Ore": 1, "Tin Ore": 65, "Silver Ore": 75, "Iron Ore": 125, "Gold Ore": 155,
    "Mithril Ore": 175, "Truesilver Ore": 230, "Dark Iron Ore": 230, "Thorium Ore": 245, "Rough Stone": 1,
    "Coarse Stone": 65, "Heavy Stone": 125, "Solid Stone": 175, "Dense Stone": 245, "Light Leather": 1,
    "Medium Leather": 100, "Heavy Leather": 150, "Thick Leather": 200, "Rugged Leather": 250,
}

# Trade Goods (class 7) subclasses that gathering professions produce
GATHER_TYPES = {5: "Cloth", 6: "Leather", 7: "Metal & Stone", 8: "Cooking", 9: "Herb", 10: "Elemental", 12: "Enchanting"}


class History:
    """Keeps every scan the addon hands over, so market values and charts survive beyond the addon's 14 days."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS scans (realm TEXT, ts INTEGER, auctions INTEGER, items INTEGER,
                PRIMARY KEY (realm, ts));
            CREATE TABLE IF NOT EXISTS prices (realm TEXT, item INTEGER, ts INTEGER, min INTEGER,
                mkt INTEGER, qty INTEGER, PRIMARY KEY (realm, item, ts));
            CREATE TABLE IF NOT EXISTS daymins (realm TEXT, item INTEGER, day INTEGER, min INTEGER,
                PRIMARY KEY (realm, item, day));
            CREATE TABLE IF NOT EXISTS sold (realm TEXT, item INTEGER, day INTEGER, early INTEGER, maybe INTEGER,
                value INTEGER, PRIMARY KEY (realm, item, day));
            CREATE TABLE IF NOT EXISTS observed (realm TEXT, day INTEGER, hours REAL, PRIMARY KEY (realm, day));
            """
        )

    def ingest(self, realm_key, realm):
        ts = int(realm.get("lastScan") or 0)
        if not ts:
            return False
        new = self.db.execute("SELECT 1 FROM scans WHERE realm=? AND ts=?", (realm_key, ts)).fetchone() is None
        if new:
            self.db.execute("INSERT INTO scans VALUES (?,?,?,?)",
                            (realm_key, ts, realm.get("auctions", 0), realm.get("itemCount", 0)))
            self.db.executemany(
                "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?)",
                [(realm_key, int(i), ts, s.get("m"), robust_market(s), s.get("q")) for i, s in (realm.get("items") or {}).items()],
            )
        rows = []
        for item, days in (realm.get("h") or {}).items():
            for day, mn in (days.items() if isinstance(days, dict) else enumerate(days, 1)):
                rows.append((realm_key, int(item), int(day), int(mn)))
        self.db.executemany(
            "INSERT INTO daymins VALUES (?,?,?,?) ON CONFLICT(realm,item,day) DO UPDATE SET min=MIN(min, excluded.min)",
            rows,
        )
        # sales the addon worked out by comparing scans (it keeps 14 days; Desk keeps them longer)
        sold = []
        for item, days in (realm.get("sd") or {}).items():
            for day, r in (days.items() if isinstance(days, dict) else enumerate(days, 1)):
                if isinstance(r, list) and len(r) >= 3:
                    sold.append((realm_key, int(item), int(day), int(r[0]), int(r[1]), int(r[2])))
        self.db.executemany("INSERT OR REPLACE INTO sold VALUES (?,?,?,?,?,?)", sold)
        obs = realm.get("obs") or {}
        self.db.executemany("INSERT OR REPLACE INTO observed VALUES (?,?,?)",
                            [(realm_key, int(d), float(h)) for d, h in (obs.items() if isinstance(obs, dict) else enumerate(obs, 1))])
        self.db.commit()
        return new

    def sales(self, realm_key, since_day):
        """(hours watched, {item: {"early", "maybe", "value", "days": {day: (early, value)}}}) since since_day."""
        hours = self.db.execute("SELECT COALESCE(SUM(hours), 0) FROM observed WHERE realm=? AND day>=?",
                                (realm_key, since_day)).fetchone()[0]
        out = {}
        for item, day, e, m, v in self.db.execute(
                "SELECT item, day, early, maybe, value FROM sold WHERE realm=? AND day>=?", (realm_key, since_day)):
            r = out.setdefault(item, {"early": 0, "maybe": 0, "value": 0, "days": {}})
            r["early"] += e
            r["maybe"] += m
            r["value"] += v
            r["days"][day] = (e, v)
        days_watched = self.db.execute("SELECT COUNT(*) FROM observed WHERE realm=? AND day>=? AND hours>0",
                                       (realm_key, since_day)).fetchone()[0]
        return float(hours or 0), int(days_watched or 0), out

    def series(self, realm_key, since_day):
        """{item: [[day, lowest, market, listed], ...]} one point per day, oldest first.
        market is the median of that day's scans (None on days only the addon's daily minimum covers)."""
        days = {}
        for item, day, mn in self.db.execute(
                "SELECT item, day, min FROM daymins WHERE realm=? AND day>=?", (realm_key, since_day)):
            days.setdefault(item, {}).setdefault(day, {"min": mn, "mkt": [], "qty": None, "ts": 0})
        for item, ts, mn, mkt, qty in self.db.execute(
                "SELECT item, ts, min, mkt, qty FROM prices WHERE realm=? AND ts>=? ORDER BY ts",
                (realm_key, since_day * DAY)):
            d = days.setdefault(item, {}).setdefault(ts // DAY, {"min": mn, "mkt": [], "qty": None, "ts": 0})
            if mn is not None:
                d["min"] = min(d["min"], mn) if d["min"] is not None else mn
            if mkt:
                d["mkt"].append(mkt)
            if qty is not None and ts >= d["ts"]:
                d["qty"], d["ts"] = qty, ts
        out = {}
        for item, per_day in days.items():
            out[item] = [[day, v["min"], int(statistics.median(v["mkt"])) if v["mkt"] else None, v["qty"]]
                         for day, v in sorted(per_day.items())]
        return out

    def scan_count(self, realm_key):
        return self.db.execute("SELECT COUNT(*) FROM scans WHERE realm=?", (realm_key,)).fetchone()[0]


def robust_market(s):
    """Market price that a single cheap dump can't drag down: where real supply sits, never below the addon's estimate."""
    ladder, total = s.get("l") or [], s.get("q") or 0
    wall = _wall(ladder, total) if ladder else None
    p = s.get("p") or s.get("m")
    return max(p, wall) if wall and p else (wall or p)


def _units_below(ladder, limit_price):
    """Units and cost purchasable at or below limit_price from a ladder of [price, cumulative qty]."""
    units = cost = 0
    prev = 0
    top = None
    for price, cum in ladder:
        if price > limit_price:
            break
        q = cum - prev
        units += q
        cost += q * price
        prev = cum
        top = price
    return units, cost, top


def _wall(ladder, total, share=0.2):
    """Price where real supply sits: the cheapest level holding >= share of all listed units."""
    need = max(5, total * share)
    for price, cum in ladder:
        if cum >= need:
            return price
    return ladder[-1][0] if ladder else None


def sales_model(history, realm_key, today, window=7):
    """How fast each item really sells on one Auction House, from listings that vanished between your scans.

    Per item: lo / mid / hi units sold a day (mid counts one in ten of the listings that may just have expired,
    hi counts them all), the usual sale price (median of each day's average sale price), a confidence and a label.
    """
    hours, days_watched, raw = history.sales(realm_key, today - window + 1)
    model = {"hours": hours, "days": days_watched, "items": {}}
    if hours < 1:
        return model
    for i, r in raw.items():
        e, m = r["early"], r["maybe"]
        lo = max(0.0, e - math.sqrt(e)) / hours * 24
        mid = (e + 0.1 * m) / hours * 24
        hi = (e + m + math.sqrt(e + m)) / hours * 24
        daily = {d: v / n for d, (n, v) in r["days"].items() if n > 0}
        prices = sorted(daily.values())
        usual = statistics.median(prices) if prices else None
        slope = None
        if len(daily) >= 4:   # how real sale prices moved over the week (log-linear, per day)
            xs = sorted(daily)
            ys = [math.log(daily[d]) for d in xs]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            den = sum((x - mx) ** 2 for x in xs)
            if den:
                slope = math.exp(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den) - 1
        conf = ("high" if hours >= 24 and e >= 20 else "medium" if hours >= 6 and e >= 5 else "low")
        model["items"][int(i)] = {"lo": lo, "mid": mid, "hi": hi, "usual": usual, "usual_days": len(prices),
                                  "conf": conf, "sold": e, "slope": slope}
    return model


def rate_txt(x):
    return f"{x:.0f}" if x >= 10 else f"{x:.1f}"


def sells_label(mid):
    if mid is None:
        return "Not measured"
    return "Sells steadily" if mid >= 5 else ("Sells slowly" if mid >= 1 else "Rarely sells")


def plan_flip(ladder, cut, risk_u, min_roi, typical=None, cap=None):
    """The flip you can really sell: buy the cheapest listings up to some price level, then relist at the next
    listing that's left (you're now the cheapest seller), never above where the item usually bottoms out.

    ladder: [[price, cumulative qty], ...] cheapest first. typical: the usual daily lowest price (history).
    Returns the most profitable plan, or None. Every level bought must clear min_roi at that resale price,
    and you must be able to buy all of it (cap): otherwise cheaper listings would still sit under yours.
    """
    best = None
    prev = units = cost = 0
    for k in range(len(ladder) - 1):
        price, cum = ladder[k]
        q = cum - prev
        prev = cum
        ahead = 0
        if cap is not None and units + q > cap:
            # can't take the whole level (gold or what the market takes): buy part of it; the rest at this
            # price stays ahead of yours and sells first
            take = cap - units
            if take <= 0:
                break
            ahead, q = q - take, take
        units += q
        cost += q * price
        nxt = ladder[k + 1][0]
        resale = min(nxt, typical) if typical else nxt
        net = resale * (1 - cut) - risk_u
        if price > net / (1 + min_roi):
            continue   # a higher next listing might still make it work
        profit = net * units - cost
        if not best or profit > best["profit"]:
            best = {"units": units, "cost": cost, "top": price, "resale": int(resale), "next": nxt, "ahead": ahead,
                    "profit": profit, "net": net, "capped_by_history": bool(typical and typical < nxt)}
        if ahead:
            break
    return best


def trend(points):
    """Trend stats from daily points [day, lowest, market, listed]."""
    vals = [(p[0], p[2] or p[1]) for p in points if (p[2] or p[1])]
    if len(vals) < 2:
        return None
    last_day, last = vals[-1]
    base = next((v for d, v in vals if d >= last_day - 7), vals[0][1])
    change7 = (last - base) / base if base else 0
    slope = None
    if len(vals) >= 4:
        xs = [d for d, _ in vals]
        ys = [math.log(v) for _, v in vals]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den:
            b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
            slope = math.exp(b) - 1
    return {"change7": change7, "slope": slope, "days": len(vals), "last": last}


def analyse(sv, history: History, cfg, now=None):
    now = now or int(time.time())
    db = sv.get("MyFA_DB") or {}
    realms = db.get("realms") or {}
    if not realms:
        return None
    home_keys = [k for k in realms if not str(k).endswith(NEUTRAL_SUFFIX)]
    if not home_keys:
        return None   # only a neutral scan so far: your own faction's Auction House comes first
    realm_key = cfg.get("realm") if cfg.get("realm") in home_keys else max(home_keys, key=lambda k: realms[k].get("lastScan") or 0)
    realm = realms[realm_key]
    neutral_key = realm_key.rpartition("-")[0] + NEUTRAL_SUFFIX
    neutral_realm = realms.get(neutral_key)
    for k, r in realms.items():
        history.ingest(k, r)

    meta = {int(k): v for k, v in (db.get("items") or {}).items()}
    scan = {int(k): v for k, v in (realm.get("items") or {}).items()}
    vendor_buy = {int(k): v for k, v in (db.get("vendorBuy") or {}).items()}
    for k, v in (cfg.get("vendor_costs") or {}).items():
        vendor_buy[int(k)] = int(v)

    cut = float(cfg["ah_cut"])
    ids_by_name = {str(m.get("n")).lower(): i for i, m in meta.items() if m.get("n")}
    riskm = pnl.RiskModel(db, meta, cfg, ids_by_name)
    today = now // DAY
    series = history.series(realm_key, today - int(cfg["chart_days"]))
    trends = {i: trend(p) for i, p in series.items()}
    smodel = sales_model(history, realm_key, today)

    def sales_of(i, model=None):
        """This item's sales on a market, or a 'measured zero' when the market was watched and it never sold."""
        model = model or smodel
        st = model["items"].get(int(i))
        if st:
            return st
        if model["hours"] >= 6:
            return {"lo": 0.0, "mid": 0.0, "hi": 0.0, "usual": None, "usual_days": 0, "conf": "medium" if model["hours"] >= 24 else "low",
                    "sold": 0, "slope": None}
        return None

    def band(i):
        """Typical price range from daily lowest prices: buy under the 20th percentile, sell at the 80th."""
        lows = [p[1] for p in series.get(i, []) if p[0] >= today - int(cfg["band_days"]) and p[1]]
        if len(lows) < 5:
            return None
        q = statistics.quantiles(lows, n=10, method="inclusive")
        lo, hi = q[1], q[7]
        mean = statistics.fmean(lows)
        return {"buy": int(lo), "sell": int(hi), "days": len(lows),
                "spread": (hi * (1 - cut) - lo) / lo if lo else 0,
                "vol": statistics.pstdev(lows) / mean if mean else 0}

    def name(i):
        return (meta.get(i) or {}).get("n") or f"Item {i}"

    def quality(i):
        return (meta.get(i) or {}).get("c", 1)

    def hist(i):
        """(median daily value over history_days, number of days)"""
        cutoff = today - int(cfg["history_days"])
        vals = [p[2] or p[1] for p in series.get(i, []) if p[0] >= cutoff and (p[2] or p[1])]
        return (statistics.median(vals), len(vals)) if vals else (None, 0)

    def typical_low(i):
        """(median of the daily lowest price over history_days, days): where the item usually bottoms out,
        which is the price buyers actually pay."""
        cutoff = today - int(cfg["history_days"])
        lows = [p[1] for p in series.get(i, []) if p[0] >= cutoff and p[1]]
        return (statistics.median(lows), len(lows)) if lows else (None, 0)

    def market(i):
        """Best estimate of what an item sells for: history when we have it, current scan otherwise."""
        h, days = hist(i)
        s = scan.get(i)
        if days >= 3:
            return int(h)
        if s:
            return int(robust_market(s))
        return int(h) if h else None

    def sell_price(i):
        """What you'd list it at today: match the lowest, unless the lowest looks dumped."""
        s = scan.get(i)
        if not s:
            return None, ""
        h, days = hist(i)
        if days >= 3 and s["m"] < 0.8 * h:
            return int(h), "Lowest listing looks dumped; post at market and wait."
        return int(s["m"]), ""

    def buy_cost(i):
        options = []
        s = scan.get(i)
        if s and s.get("m"):
            options.append(s["m"])
        if i in vendor_buy:
            options.append(vendor_buy[i])
        return min(options) if options else None

    char_items = [(k, c) for k, c in (db.get("chars") or {}).items() if c.get("realmKey") == realm_key]
    chars = [c for _, c in char_items]
    money = sum((c.get("money") or 0) for c in chars)
    budget = money * float(cfg["max_spend_fraction"]) if money else float("inf")

    # ---- flips ---------------------------------------------------------------
    flips = []
    # Flips, the way market trackers judge them: only items that demonstrably sell, priced at their usual
    # sale price, bought in a quantity the market takes within a few days, ranked by expected gold a day.
    skips = {"rarely": [], "surge": [], "falling": [], "unmeasured": [], "slow": []}
    min_sold = float(cfg.get("min_sold_per_day", 1.0))
    max_days = float(cfg.get("max_days_to_sell", 3))
    for i, s in scan.items():
        m = meta.get(i) or {}
        if m.get("e") and not cfg["include_gear"]:
            continue
        ladder = s.get("l") or []
        total = s.get("q") or 0
        if len(ladder) < 2 or total < 2:
            continue
        st = sales_of(i)
        low, low_days = typical_low(i)
        # the usual sale price: real sales when we have two days of them, else the usual daily low, else the newest scan less 15%
        if st and st["usual"] and st["usual_days"] >= 2:
            usual, basis = min(st["usual"], low * 1.5) if low_days >= 3 else st["usual"], "sales"
        elif low_days >= 3:
            usual, basis = low, "daily lows"
        else:
            usual, basis = ladder[1][0] * 0.85, "this scan, less 15%"
        if usual <= (m.get("v") or 0):
            continue   # a vendor pays as much: not a flip (cheap ones show as vendor flips)
        cheap = ladder[0][0] < usual * 0.8   # only worth explaining a skip if something looks cheap
        # supply surge: far more listed than usual, so the price is about to slide (a poison glut, say)
        qtys = [p_[3] for p_ in series.get(i, []) if p_[3] and p_[0] >= today - 7]
        usual_qty = statistics.median(qtys[:-1]) if len(qtys) >= 3 else None
        if usual_qty and usual_qty >= 5 and total > 2 * usual_qty:
            if cheap:
                skips["surge"].append(name(i))
            continue
        # falling: real sale prices when MyFA has four days of them, else the listing trend
        slope = st.get("slope") if st else None
        if slope is None:
            t = trends.get(i)
            slope = t["slope"] if t else None
        if slope is not None and slope < -0.03:
            if cheap:
                skips["falling"].append(name(i))
            continue
        if st is None:
            # not measured yet: only deep, steady markets, and small
            if total < 200 or low_days < 5:
                if cheap:
                    skips["unmeasured"].append(name(i))
                continue
            per_day = None
            cap_sales = max(1, int(total * 0.05))
        else:
            if st["mid"] < min_sold:
                if cheap:
                    skips["rarely"].append(name(i))
                continue
            per_day = st["lo"] if st["lo"] > 0 else st["mid"] / 2
            cap_sales = max(1, int(per_day * max_days))
        # how much to buy: what the market takes in max_days_to_sell once sales are measured;
        # before that, a small share of what's listed
        cap = cap_sales if st is not None else min(max(1, int(total * float(cfg["max_supply_share"]))), cap_sales)
        if budget != float("inf") and ladder[0][0] > 0:
            cap = min(cap, int(budget // ladder[0][0]))
        p_sell = riskm.rate(i)
        # lost deposits: your usual rate, but never less than the 1 silver minimum per auction
        risk_u = riskm.per_unit(i, "home")
        plan = plan_flip(ladder, cut, risk_u, float(cfg["min_roi"]), usual, cap)
        if not plan:
            continue
        units, cost, avg = plan["units"], plan["cost"], plan["cost"] / plan["units"]
        min_dep = 100 * (1 - p_sell) / p_sell      # one auction's 1s minimum deposit, lost as often as listings fail
        profit = int(plan["profit"] - min_dep)
        roi = (plan["net"] - avg) / avg if avg else 0
        if profit < cfg["min_profit"] or roi < cfg["min_roi"]:
            continue
        days_to_sell = (units + plan.get("ahead", 0)) / per_day if per_day else None
        if days_to_sell and days_to_sell > max_days * 1.01:
            skips["slow"].append(name(i))
            continue
        per_unit = profit / units
        profit_day = per_unit * min(units, per_day) if per_day else None
        thin = total < int(cfg["min_listed"])
        conf = st["conf"] if st else "not measured"
        risk = {"high": "low", "medium": "medium"}.get(conf, "high")
        if thin:
            risk = "high"
        label = sells_label(st["mid"] if st else None)
        if st:
            speed = (f"{label}: about {rate_txt(st['mid'])} a day ({rate_txt(st['lo'])} to {rate_txt(st['hi'])}, {conf} confidence). ")
        else:
            speed = "Sales not measured yet (scan twice, an hour apart, to measure them), so only a small amount. "
        price_note = {"sales": "its usual sale price over the last 7 days",
                      "daily lows": "where it usually bottoms out",
                      "this scan, less 15%": "the next listing less 15% (no history yet)"}[basis]
        flips.append({
            "id": i, "name": name(i), "q": quality(i), "kind": "snipe" if thin else "flip",
            "max": int(plan["top"]), "qty": units, "avg": int(avg), "sell": plan["resale"],
            "profit": profit, "roi": round(roi, 3), "listed": total, "days": low_days, "risk": risk,
            "usual": int(usual), "usual_basis": basis, "sold_day": round(st["mid"], 1) if st else None,
            "sold_lo": round(st["lo"], 1) if st else None, "sold_hi": round(st["hi"], 1) if st else None,
            "sells": label, "conf": conf, "days_to_sell": round(days_to_sell, 1) if days_to_sell else None,
            "profit_day": int(profit_day) if profit_day is not None else None,
            "why": speed + (f"Buy {units} at up to {fmt(plan['top'])} ({plan['ahead']} more at that price sell first)"
                            if plan.get("ahead") else f"Buy all {units} listed at up to {fmt(plan['top'])}")
                   + f" and relist at {fmt(plan['resale'])}, "
                   f"{price_note}; you'll be the cheapest seller."
                   + ((" Sells within a day." if days_to_sell < 1 else f" About {days_to_sell:.1f} days to sell.") if days_to_sell else "")
                   + f" {int(cut * 100)}% cut and likely lost deposits included.",
            "risk_unit": int(risk_u), "sell_rate": round(p_sell, 2),
        })
    # ---- deals you pasted from Booty Bay Broker: their sales figures, your flip checks ------------------
    bbb_info = None
    pasted = bbb.load() if cfg.get("use_bbb", True) else None
    if pasted and pasted.get("rows"):
        my_faction = realm_key.rpartition("-")[2]
        age_min = int((now - pasted["t"]) / 60)
        info = {"market": pasted.get("market"), "faction": pasted.get("faction"), "age_min": age_min,
                "rows": len(pasted["rows"]), "passed": [], "surge": [], "nogap": [], "rare": [], "unknown": [],
                "gone": [], "wrong_faction": pasted.get("faction") not in (None, my_faction)}
        have = {r["id"] for r in flips}
        for d in ([] if info["wrong_faction"] else pasted["rows"]):
            i = ids_by_name.get(d["name"].lower())
            if i is None:
                info["unknown"].append(d["name"])
                continue
            if i in have:
                continue
            if d.get("surge"):
                info["surge"].append(d["name"])
                continue
            mid, lo = d.get("sold") or 0, d.get("lo") or 0
            if d.get("label") == "Rarely sells" or mid < min_sold:
                info["rare"].append(d["name"])
                continue
            s_ = scan.get(i)
            mine_newer = int(realm.get("lastScan") or 0) > d.get("seen", d.get("t", 0))
            if mine_newer:
                # your own scan is newer: trust what it shows now
                if not s_ or (s_.get("m") or 0) > d["lowest"] * 1.05:
                    info["gone"].append(d["name"])   # the cheap listing is gone: someone bought or relisted it
                    continue
                ladder = s_.get("l") or []
            else:
                ladder = [[d["lowest"], d["available"]], [d["next"] or d["usual"], d["available"] + 1]]
            if len(ladder) < 2:
                ladder = ladder + [[d["usual"], (ladder[-1][1] if ladder else 0) + 1]]
            per_day = lo if lo > 0 else mid / 2
            cap = max(1, int(per_day * max_days))
            if budget != float("inf") and ladder[0][0] > 0:
                cap = min(cap, int(budget // ladder[0][0]))
            risk_u = riskm.per_unit(i, "home")
            p_sell = riskm.rate(i)
            plan = plan_flip(ladder, cut, risk_u, float(cfg["min_roi"]), d["usual"], cap)
            profit = int(plan["profit"] - 100 * (1 - p_sell) / p_sell) if plan else 0
            avg = plan["cost"] / plan["units"] if plan else 0
            roi = (plan["net"] - avg) / avg if plan and avg else 0
            if not plan or profit < cfg["min_profit"] or roi < cfg["min_roi"]:
                info["nogap"].append(d["name"])
                continue
            units = plan["units"]
            days_to_sell = (units + plan.get("ahead", 0)) / per_day if per_day else None
            flips.append({
                "id": i, "name": name(i), "q": quality(i), "kind": "flip", "source": "bbb",
                "max": int(plan["top"]), "qty": units, "avg": int(avg), "sell": plan["resale"],
                "profit": profit, "roi": round(roi, 3), "listed": (s_ or {}).get("q", d["available"]), "days": 7,
                "risk": "medium", "usual": int(d["usual"]), "usual_basis": "Booty Bay Broker",
                "sold_day": round(mid, 1), "sold_lo": round(lo, 1), "sold_hi": round(d.get("hi") or mid, 1),
                "sells": d.get("label") or sells_label(mid), "conf": "Booty Bay Broker",
                "days_to_sell": round(days_to_sell, 1) if days_to_sell else None,
                "profit_day": int(profit / units * min(units, per_day)),
                "why": (f"From Booty Bay Broker ({info['market']}, pasted {age_min} min ago): {d.get('label') or 'sells'}, "
                        f"about {rate_txt(mid)} a day ({rate_txt(lo)} to {rate_txt(d.get('hi') or mid)}), usual sale price {fmt(d['usual'])}. "
                        + (f"Buy {units} at up to {fmt(plan['top'])} ({plan['ahead']} more at that price will sell before yours)"
                           if plan.get("ahead") else f"Buy all {units} at up to {fmt(plan['top'])}")
                        + f" and relist at {fmt(plan['resale'])}"
                        + (f" (next listing {fmt(plan['next'])})" if plan["next"] < d["usual"] else "")
                        + "; you'll be the cheapest seller."
                        + ((" Sells within a day." if days_to_sell < 1 else f" About {days_to_sell:.1f} days to sell.") if days_to_sell else "")
                        + (" Prices checked against your newer scan." if mine_newer else " Their scan is newer than yours: check the price in game first.")
                        + f" {int(cut * 100)}% cut and likely lost deposits included."),
                "risk_unit": int(risk_u), "sell_rate": round(p_sell, 2),
            })
            info["passed"].append(d["name"])
        bbb_info = info

    # best gold a day first; unmeasured ones after the measured ones
    flips.sort(key=lambda r: (r["kind"] == "snipe", r["profit_day"] is None, -(r["profit_day"] or 0), -r["profit"]))
    flips = flips[: cfg["max_targets"]]

    # ---- vendor flips --------------------------------------------------------
    vendor = []
    for i, s in scan.items():
        v = (meta.get(i) or {}).get("v") or 0
        if v <= 0:
            continue
        units, cost, top = _units_below(s.get("l") or [], v - 1)
        if units <= 0:
            continue
        profit = units * v - cost
        if profit < cfg["min_vendor_profit"]:
            continue
        vendor.append({
            "id": i, "name": name(i), "q": quality(i), "kind": "vendor",
            "max": int(top), "qty": units, "avg": int(cost / units), "sell": v, "profit": int(profit),
            "roi": round((v - cost / units) / (cost / units), 3), "listed": s.get("q"), "days": 0, "risk": "none",
            "why": f"Listed below the vendor price of {fmt(v)}. Buy, then sell to any vendor.",
        })
    vendor.sort(key=lambda r: r["profit"], reverse=True)

    # ---- what you own (bags + bank + warband bank) -------------------------------
    stock, places = {}, {}

    def add_stock(i, n, where, who):
        i = int(i)
        e = stock.setdefault(i, {"bags": 0, "bank": 0, "mail": 0, "warband": 0})
        e[where] += int(n)
        places.setdefault(i, []).append((who, "bank" if where == "warband" else where, int(n)))

    for key, c in char_items:
        who = key.split("-")[0]
        for where in ("bags", "bank", "mail"):
            for i, n in (c.get(where) or {}).items():
                add_stock(i, n, where, who)
    wb = db.get("warband") or {}
    if wb.get("items") and wb.get("realmKey", realm_key) == realm_key:
        for i, n in wb["items"].items():
            add_stock(i, n, "warband", "Warband")
    owned = {i: sum(e.values()) for i, e in stock.items()}

    def where_text(i, limit=4):
        parts = places.get(i, [])
        txt = ", ".join(f"{who} {where} {n}" for who, where, n in parts[:limit])
        return txt + (f", +{len(parts) - limit} more" if len(parts) > limit else "")

    def raw_value(i):
        """Per-unit value of selling an item as it is: max of AH (after cut) and vendor."""
        price, _ = sell_price(i)
        ah = price * (1 - cut) - riskm.per_unit(i, "home") if price else 0
        v = (meta.get(i) or {}).get("v") or 0
        return max(ah, v)

    # ---- crafts, every profession on every character on this realm --------------
    recipes, seen = [], set()
    for c in chars:
        for rid, r in (c.get("recipes") or {}).items():
            if rid in seen:
                continue
            seen.add(rid)
            recipes.append(r)

    crafts = []
    for r in recipes:
        out_id = int(r.get("o"))
        reagents = [(int(p[0]), int(p[1])) for p in (r.get("r") or [])]
        parts, missing, cost = [], [], 0
        for rg_id, qty in reagents:
            unit = buy_cost(rg_id)
            if unit is None:
                missing.append(name(rg_id))
                continue
            cost += unit * qty
            parts.append(f"{qty}x {name(rg_id)} @ {fmt(unit)}")
        sell, _ = sell_price(out_id)
        if sell is None:
            sell = market(out_id)
        n_out = (float(r.get("qa", 1)) + float(r.get("qb", r.get("qa", 1)))) / 2
        out_net = max(0, (sell * (1 - cut) - riskm.per_unit(out_id, "home")) * n_out) if sell else 0
        out_vendor = ((meta.get(out_id) or {}).get("v") or 0) * n_out
        value = int(max(out_net, out_vendor))
        can_make = min((owned.get(rg, 0) // q for rg, q in reagents), default=0) if reagents else 0
        mats_value = sum(raw_value(rg) * q for rg, q in reagents)
        t = trends.get(out_id)
        row = {
            "id": out_id, "name": r.get("n") or name(out_id), "q": quality(out_id),
            "prof": r.get("p") or "", "cost": int(cost), "missing": missing, "value": value,
            "listed": (scan.get(out_id) or {}).get("q", 0), "mats": "; ".join(parts),
            "stock": can_make, "reagents": reagents, "n_out": n_out, "out_net": out_net,
            "stock_gain": int(can_make * (value - mats_value)) if can_make and value else 0,
            "trend": t["slope"] if t else None,
        }
        row["profit"] = value - row["cost"] if value and not missing else None
        row["margin"] = round(row["profit"] / row["cost"], 3) if row["profit"] is not None and row["cost"] else None
        crafts.append(row)
    crafts.sort(key=lambda r: (r["profit"] is None, -(r["profit"] or 0)))

    def best_craft_use(i):
        """Best per-unit value of item i when crafted into something (other mats bought at today's price)."""
        best = None
        for row in crafts:
            if not row["value"]:
                continue
            need = next((q for rg, q in row["reagents"] if rg == i), 0)
            if not need:
                continue
            others = 0
            for rg, q in row["reagents"]:
                if rg == i:
                    continue
                unit = buy_cost(rg)
                if unit is None:
                    others = None
                    break
                others += unit * q
            if others is None:
                continue
            per_unit = (row["value"] - others) / need
            if not best or per_unit > best[0]:
                best = (per_unit, row["name"])
        return best

    # ---- raid calendar ----------------------------------------------------------
    raid_cfg = load_raids(cfg)
    by_name = {}
    for i, m in meta.items():
        if m.get("n"):
            by_name.setdefault(m["n"].lower(), i)
    raid_days = {}
    for r in raid_cfg.get("raids", []):
        try:
            raid_days[r["name"]] = datetime.date.fromisoformat(r["date"]).toordinal() - datetime.date(1970, 1, 1).toordinal()
        except (KeyError, ValueError):
            continue
    live = {n: d for n, d in raid_days.items() if d >= today - 21}
    raid_items = {}
    for entry in raid_cfg.get("items", []):
        names = list(live) if "all" in entry.get("raids", []) else [n for n in entry.get("raids", []) if n in live]
        if not names:
            continue
        day = min(live[n] for n in names)
        raid_items[entry["name"].lower()] = {"name": entry["name"], "role": entry.get("role", ""),
                                             "raids": names, "day": day, "id": by_name.get(entry["name"].lower())}

    def phase(days_left):
        if days_left > 14:
            return "stock", "Stock up"
        if days_left > 7:
            return "build", "Build stock"
        if days_left >= 0:
            return "launch", "Launch week"
        if days_left >= -14:
            return "raiding", "Raiding"
        return "settled", "Settled"

    raid_by_id = {v["id"]: v for v in raid_items.values() if v["id"]}

    # ---- best use of everything you own ----------------------------------------
    inventory = []
    for i, e in stock.items():
        n = owned[i]
        price, note = sell_price(i)
        ah = max(0, price * (1 - cut) - riskm.per_unit(i, "home")) if price else 0
        v = (meta.get(i) or {}).get("v") or 0
        craft = best_craft_use(i)
        options = {"ah": ah, "vendor": v}
        if craft and craft[0] > 0:
            options["craft"] = craft[0]
        if not any(options.values()):
            continue
        ranked = sorted(options.items(), key=lambda kv: kv[1], reverse=True)
        action, best = ranked[0]
        gain = (best - ranked[1][1]) * n if len(ranked) > 1 else 0
        t = trends.get(i)
        notes = [note] if note else []
        raid = raid_by_id.get(i)
        hold = None
        if raid and action in ("ah", "vendor") and phase(raid["day"] - today)[0] in ("stock", "build"):
            action, hold = "hold", "raid"
            when = _date(raid["day"])
            notes.append(f"Raid consumable ({raid['role']}). Hold for {', '.join(raid['raids'])} on {when}; "
                         f"demand usually peaks launch week, so sell then.")
        elif raid and phase(raid["day"] - today)[0] in ("launch", "raiding") and action in ("ah", "hold"):
            notes.append(f"Raid demand is live for {', '.join(raid['raids'])}: sell now while prices are up.")
        elif action == "ah" and t and t["slope"] is not None and t["slope"] >= float(cfg["hold_rising_slope"]):
            action, hold = "hold", "rising"
            notes.append(f"Price rising about {t['slope'] * 100:.0f}% a day over {t['days']} days; holding may pay more.")
        elif t and t["slope"] is not None and abs(t["slope"]) >= 0.03:
            notes.append(f"Price {'rising' if t['slope'] > 0 else 'falling'} about {abs(t['slope']) * 100:.0f}% a day.")
        if action == "craft":
            notes.append(f"Worth {fmt(best)} each crafted into {craft[1]} vs {fmt(max(ah, v))} sold as is.")
        loc = where_text(i)
        inventory.append({
            "id": i, "name": name(i), "q": quality(i), "qty": n, "bags": e["bags"], "bank": e["bank"],
            "warband": e["warband"], "loc": loc, "action": action, "price": price or 0,
            "into": craft[1] if action == "craft" else None,
            "ah": int(ah * n), "vendor": int(v * n), "craft": int(craft[0] * n) if craft and craft[0] > 0 else 0,
            "value": int(best * n), "gain": int(gain), "note": " ".join(notes),
            "trend": t["slope"] if t else None, "hold": hold,
        })
    inventory.sort(key=lambda r: r["value"], reverse=True)

    # ---- gathering: what raw materials are worth farming -------------------------
    gathering = []
    for i, s in scan.items():
        m = meta.get(i) or {}
        if m.get("k") != 7 or m.get("u") not in GATHER_TYPES:
            continue
        mk = market(i)
        if not mk:
            continue
        t = trends.get(i)
        gathering.append({
            "id": i, "name": name(i), "q": quality(i), "type": GATHER_TYPES[m["u"]], "market": mk,
            "now": s["m"], "listed": s.get("q", 0), "change7": t["change7"] if t else None,
            "slope": t["slope"] if t else None, "days": t["days"] if t else 0,
            "stack": mk * (m.get("s") or 20), "owned": owned.get(i, 0),
        })
    gathering.sort(key=lambda r: r["market"], reverse=True)

    # ---- trends (table + chart data) -----------------------------------------------
    trend_rows = []
    chart = {}
    for i, s in scan.items():
        t = trends.get(i)
        pts = series.get(i) or []
        if len(pts) >= 2:
            chart[i] = {"n": name(i), "q": quality(i), "p": pts}
        if not t:
            continue
        trend_rows.append({
            "id": i, "name": name(i), "q": quality(i), "now": s["m"], "market": market(i) or s["m"],
            "change7": t["change7"], "slope": t["slope"], "days": t["days"], "listed": s.get("q", 0),
            "owned": owned.get(i, 0),
        })
    trend_rows.sort(key=lambda r: (r["slope"] is None, -(r["slope"] or 0), -r["change7"]))
    focus = [r["id"] for r in trend_rows[:1]] or list(chart)[:1]
    if any(r["owned"] for r in trend_rows):
        focus = [max((r for r in trend_rows if r["owned"]), key=lambda r: r["market"] * r["owned"])["id"]]

    # ---- flip bands: items that swing between a cheap and an expensive range ------
    bands = []
    for i, s in scan.items():
        m = meta.get(i) or {}
        if m.get("e") and not cfg["include_gear"]:
            continue
        b = band(i)
        if not b or b["spread"] < float(cfg["min_band_spread"]):
            continue
        t = trends.get(i)
        if t and t["slope"] is not None and abs(t["slope"]) >= 0.03:
            continue  # trending steadily up or down: not a range to flip in
        listed = s.get("q", 0)
        zone = "buy" if s["m"] <= b["buy"] else ("sell" if s["m"] >= b["sell"] else "mid")
        per_unit = b["sell"] * (1 - cut) - b["buy"] - riskm.per_unit(i, "home")
        bands.append({
            "id": i, "name": name(i), "q": quality(i), "now": s["m"], "buy": b["buy"], "sell": b["sell"],
            "spread": round(b["spread"], 3), "vol": round(b["vol"], 3), "days": b["days"], "listed": listed,
            "zone": zone, "per_unit": int(per_unit), "owned": owned.get(i, 0),
            "score": b["spread"] * min(1.0, listed / 60) * min(1.0, per_unit / 2000 + 0.25),
        })
    bands.sort(key=lambda r: (r["zone"] != "buy", -r["score"]))
    bands = bands[:50]

    # ---- market index by category ---------------------------------------------------
    def category(i):
        m = meta.get(i) or {}
        if m.get("k") == 7 and m.get("u") == 9:
            return "Herbs"
        if m.get("k") == 0:
            return "Consumables"
        if m.get("k") == 7 and m.get("u") in (5, 6):
            return "Cloth & leather"
        return None

    all_days = sorted({p[0] for pts in series.values() for p in pts})
    index = None
    if len(all_days) >= 2:
        names_ = ["All items", "Herbs", "Consumables", "Cloth & leather"]
        ratios = {n: {d: [] for d in all_days} for n in names_}
        for i, pts in series.items():
            vals = [(p[0], p[2] or p[1]) for p in pts if (p[2] or p[1])]
            if len(vals) < 2:
                continue
            base = vals[0][1]
            cat = category(i)
            for d, v in vals:
                ratios["All items"][d].append(v / base)
                if cat:
                    ratios[cat][d].append(v / base)
        out_series = []
        for n in names_:
            vals = [round(statistics.median(ratios[n][d]) * 100, 1) if len(ratios[n][d]) >= 2 else None for d in all_days]
            if sum(v is not None for v in vals) >= 2:
                out_series.append({"name": n, "values": vals})
        index = {"days": all_days, "series": out_series}

    # ---- weekday pattern (needs two weeks) --------------------------------------------
    weekday = None
    if len(all_days) >= 14:
        rel = {k: [] for k in range(7)}
        for pts in series.values():
            vals = [(p[0], p[2] or p[1]) for p in pts if (p[2] or p[1])]
            if len(vals) < 14:
                continue
            mean = statistics.fmean(v for _, v in vals)
            for d, v in vals:
                rel[(d + 3) % 7].append(v / mean - 1)
        if all(rel[k] for k in range(7)):
            weekday = [round(statistics.median(rel[k]), 4) for k in range(7)]

    # ---- raid plan ---------------------------------------------------------------------
    craft_by_out = {r["id"]: r for r in crafts}
    raid_plan = []
    for info in raid_items.values():
        i = info["id"]
        days_left = info["day"] - today
        ph, ph_label = phase(days_left)
        s = scan.get(i) if i else None
        b = band(i) if i else None
        t = trends.get(i) if i else None
        mk = market(i) if i else None
        have = owned.get(i, 0) if i else 0
        craft = craft_by_out.get(i)
        can_craft = bool(craft and craft["profit"] is not None and craft["profit"] > 0)
        now_p = s["m"] if s else None
        cheap = now_p is not None and ((b and now_p <= b["buy"]) or (not b and mk and now_p <= 0.9 * mk))
        qty = 0
        if not s:
            action, why = "Watch", "Not on the Auction House yet. MyFA will price it once someone lists one."
        elif ph in ("stock", "build"):
            if cheap:
                limit = b["buy"] if b else int(0.9 * mk)
                units, cost, _ = _units_below(s.get("l") or [], limit)
                qty = min(units, max(1, int((s.get("q") or 0) * float(cfg["max_supply_share"]))))
                if budget != float("inf") and s["m"]:
                    qty = min(qty, int(budget // s["m"]))  # never more than your per-item gold limit
                action = "Buy"
                why = (f"At or under its usual low ({fmt(limit)}) with {days_left} days to go. "
                       f"Raid demand usually lifts consumables into launch week.")
            elif can_craft:
                action = "Craft & hold"
                why = f"You can craft it for {fmt(craft['profit'])} profit each now; hold them for launch week."
            elif have:
                action = "Hold"
                why = f"You have {have}. Sell in launch week, not now."
            else:
                target = b["buy"] if b else int(0.9 * mk) if mk else None
                action = "Wait for dip"
                why = f"Buy only under {fmt(target)}." if target else "Not enough price history yet."
        elif ph in ("launch", "raiding"):
            if have:
                action, why = "Sell", f"Raid demand is live. Post your {have} at today's lowest or market, whichever is higher."
            elif can_craft:
                action, why = "Craft & sell", f"Crafting makes {fmt(craft['profit'])} each while demand is high."
            else:
                action, why = "Don't buy", "Prices are near their peak; buy only for your own raid use."
        else:
            action = "Sell" if have else "Normal"
            why = "Launch demand has settled." + (" Sell spare stock." if have else "")
        raid_plan.append({
            "id": i, "name": info["name"] if not i else name(i), "q": quality(i) if i else 1, "role": info["role"],
            "raids": info["raids"], "days_left": days_left, "phase": ph, "phase_label": ph_label,
            "now": now_p, "market": mk, "buy": b["buy"] if b else None, "sell": b["sell"] if b else None,
            "trend": t["slope"] if t else None, "change7": t["change7"] if t else None, "owned": have,
            "listed": (s or {}).get("q", 0), "craft": craft["profit"] if can_craft else None,
            "action": action, "why": why, "qty": qty,
        })
    order = {"Buy": 0, "Sell": 1, "Craft & sell": 2, "Craft & hold": 3, "Hold": 4, "Wait for dip": 5,
             "Don't buy": 6, "Normal": 7, "Watch": 8}
    raid_plan.sort(key=lambda r: (order.get(r["action"], 9), -(r["market"] or 0)))
    raids_out = sorted(({"name": n, "day": d, "days_left": d - today, "date": _date(d)} for n, d in live.items()),
                       key=lambda r: r["day"])

    # raid buys become in-game targets too
    for r in raid_plan:
        if r["action"] == "Buy" and r["qty"] > 0 and r["id"]:
            # the band's high is where it bottoms out on good days: a realistic raid-week price, not a wish
            sell_ref = r["sell"] or int(r["market"] or r["now"])
            profit = int((sell_ref * (1 - cut) - r["now"] - riskm.per_unit(r["id"], "home")) * r["qty"])
            rst = sales_of(r["id"])
            if rst is not None and rst["mid"] < float(cfg.get("min_sold_per_day", 1.0)):
                continue   # it doesn't sell here even now: raid week won't rescue that
            if profit > 0 and not any(f["id"] == r["id"] for f in flips):
                flips.append({
                    "id": r["id"], "name": r["name"], "q": r["q"], "kind": "raid", "max": r["buy"] or r["now"],
                    "qty": r["qty"], "avg": r["now"], "sell": sell_ref, "profit": profit, "roi": 0, "listed": r["listed"],
                    "days": 0, "risk": "medium", "risk_unit": int(riskm.per_unit(r["id"], "home")),
                    "sell_rate": round(riskm.rate(r["id"]), 2),
                    "why": f"Raid stock-up for {', '.join(r['raids'])} ({r['days_left']} days). Sell launch week near {fmt(sell_ref)}.",
                })

    ledger = [e for e in (db.get("ledger") or []) if isinstance(e, dict)]

    # flips added or removed in MyFA Desk that the addon hasn't picked up yet
    manual = load_manual()
    have_mids = {e.get("mid") for e in ledger if e.get("mid")}
    for m in manual.get("adds", []):
        if m.get("mid") not in have_mids and m.get("realm", realm_key) == realm_key:
            ledger.append({"t": m["t"], "k": "buy", "id": m["id"], "q": m["q"], "u": m["u"], "m": True, "mid": m["mid"]})
    forgets = {int(k): v for k, v in (manual.get("forgets") or {}).items()}
    if forgets:
        ledger = [e for e in ledger if not (e.get("id") in forgets and e.get("t", 0) <= forgets[e.get("id")])]

    # ---- my flips: what you bought and still hold, on every character ------------------
    roi = float((db.get("settings") or {}).get("roi") or cfg.get("flip_roi", 0.15))
    def lot_left(e):
        return int(e.get("q") or 0) - int(e.get("s") or 0)

    buys_by = {}
    for e in ledger:
        if (e.get("k") == "buy" and not e.get("x") and e.get("t", 0) >= now - 90 * DAY and e.get("id") and e.get("q")
                and e.get("u") and lot_left(e) > 0):
            buys_by.setdefault(int(e["id"]), []).append(e)

    # what's listed on an Auction House right now (still yours until it sells)
    listed, listed_places = {}, {}
    for key, c in char_items:
        who = key.split("-")[0]
        for kind, l in (c.get("listed") or {}).items():
            for li, n in ((l or {}).get("items") or {}).items():
                listed[int(li)] = listed.get(int(li), 0) + int(n)
                listed_places.setdefault(int(li), []).append((who, "on neutral AH" if kind == "neutral" else "on AH", int(n)))
    positions = []
    all_chars = db.get("chars") or {}
    for i, buys in buys_by.items():
        # bought since that character last opened the mailbox: on its way, not yet seen in mail
        transit = 0
        for e in buys:
            if e.get("src") != "mail" and not e.get("m"):
                c = all_chars.get(e.get("c")) if e.get("c") else (chars[0] if chars else None)
                if not c or e.get("t", 0) > (c.get("mailT") or 0):
                    transit += lot_left(e)
        if transit:
            places.setdefault(i, []).append(("on its way", "mail", transit))
        for place in listed_places.get(i, []):
            places.setdefault(i, []).append(place)
        hold = min(owned.get(i, 0) + listed.get(i, 0) + transit, sum(lot_left(e) for e in buys))
        if hold <= 0:
            continue
        buys.sort(key=lambda e: e["t"], reverse=True)  # oldest sold first, so you hold the newest
        need, spent = hold, 0
        for e in buys:
            take = min(need, lot_left(e))
            spent += take * e["u"]
            need -= take
            if need <= 0:
                break
        cost = spent / hold
        s_ = scan.get(i)
        now_p = s_["m"] if s_ else None
        risk_u = riskm.per_unit(i, "home")
        target = math.ceil((cost * (1 + roi) + risk_u) / (1 - cut))
        mk = market(i)
        b = band(i)
        low, low_days = typical_low(i)
        # match the cheapest listing (that's what sells), but never under your alert price
        suggest = max(target, now_p if now_p else (int(low) if low_days >= 3 else (mk or 0)))
        pl = int((now_p * (1 - cut) - cost - risk_u) * hold) if now_p else None
        if now_p is None:
            status = "Not listed"
        elif now_p >= target:
            status = "Sell now"
        elif now_p * (1 - cut) >= cost:
            status = "Hold"
        else:
            status = "Under water"
        t = trends.get(i)
        note = ""
        raid = raid_by_id.get(i)
        if raid and phase(raid["day"] - today)[0] in ("stock", "build"):
            note = (f"Raid consumable: launch week ({_date(raid['day'])}) usually pays more. "
                    f"Sell now to lock in the profit, or hold for the raids.")
        elif t and t["slope"] is not None and t["slope"] <= -0.03 and status in ("Hold", "Under water"):
            note = "Falling about %d%% a day. Consider selling at market before it drops further." % round(-t["slope"] * 100)
        elif t and t["slope"] is not None and t["slope"] >= 0.04 and status == "Sell now":
            note = "Still rising about %d%% a day; selling part now and part later spreads the risk." % round(t["slope"] * 100)
        positions.append({
            "id": i, "name": name(i), "q": quality(i), "qty": hold, "cost": int(cost), "now": now_p, "market": mk,
            "target": target, "suggest": int(suggest), "pl": pl, "status": status, "where": where_text(i),
            "since": buys[-1]["t"], "trend": t["slope"] if t else None, "invested": int(cost * hold),
            "ready_value": int((target * (1 - cut) - cost - risk_u) * hold), "note": note,
            "listed": listed.get(i, 0), "risk_unit": int(risk_u),
        })
    order = {"Sell now": 0, "Hold": 1, "Under water": 2, "Not listed": 3}
    positions.sort(key=lambda r: (order[r["status"]], -(r["pl"] or -10**12)))

    # ---- your auctions: how long they've been up, and whether they're undercut ---------------------------
    pos_cost = {r["id"]: r["cost"] for r in positions}
    my_auctions = []
    posts = [p_ for p_ in (db.get("posts") or []) if isinstance(p_, dict)]
    for key, c in char_items:
        who = key.split("-")[0]
        for kind, l in (c.get("listed") or {}).items():
            l = l or {}
            snap_t = int(l.get("t") or now)
            first = {int(k): int(v) for k, v in (l.get("first") or {}).items()}
            groups = {}
            for a in l.get("auctions") or []:
                i = int(a["id"])
                g = groups.setdefault(i, {"id": i, "qty": 0, "u": 0, "left": None, "seen": None})
                g["qty"] += int(a.get("q") or 1)
                g["u"] = max(g["u"], int(a.get("u") or 0))
                if a.get("tl") is not None:
                    left = max(0, int(a["tl"]) - (now - snap_t))
                    g["left"] = left if g["left"] is None else min(g["left"], left)
                seen = first.get(int(a.get("aid") or -1))
                if seen and (g["seen"] is None or seen < g["seen"]):
                    g["seen"] = seen
            mscan = scan if kind != "neutral" else {int(k): v for k, v in ((neutral_realm or {}).get("items") or {}).items()}
            kcut = cut if kind != "neutral" else float(cfg.get("neutral_cut", 0.15))
            for i, g in groups.items():
                chain = sorted((p_ for p_ in posts if p_.get("id") == i and p_.get("c") == key and (p_.get("a") or "home") == kind),
                               key=lambda p_: -(p_.get("t") or 0))
                since, relists = None, 0
                for p_ in chain:
                    if p_.get("r") == "sold":
                        break
                    since = p_.get("t")
                    if p_.get("r") in ("expired", "cancelled"):
                        relists += 1
                if g["seen"] and (since is None or g["seen"] < since):
                    since = g["seen"]
                s_ = mscan.get(i) or {}
                other = s_.get("o") or (s_.get("m") if s_.get("m") and s_.get("m") < g["u"] else None)
                if s_.get("x"):
                    other = None
                wall = _wall(s_.get("l") or [], s_.get("q") or 0) if s_.get("l") else None
                v = (meta.get(i) or {}).get("v") or 0
                floor = math.ceil(v / (1 - kcut))
                if i in pos_cost:
                    floor = max(floor, math.ceil(pos_cost[i] / (1 - kcut)))
                repost = None
                if other and other < g["u"]:
                    if other >= floor:
                        status, repost = "Undercut", other
                    elif wall and wall >= floor:
                        status = "Cheap dump"
                        repost = wall if g["u"] > wall * 1.15 else None
                    else:
                        status = "Price fell"
                elif s_:
                    status = "Lowest"
                else:
                    status = "No price"
                mk = market(i) if kind != "neutral" else wall
                my_auctions.append({
                    "id": i, "name": name(i), "q": quality(i), "who": who, "ah": kind, "qty": g["qty"], "u": g["u"],
                    "other": other, "wall": wall, "status": status, "repost": repost, "since": since, "relists": relists,
                    "left": g["left"], "snap": snap_t, "floor": floor,
                    "high": bool(mk and g["u"] > mk * 1.5 and status != "Lowest"),
                })
    order_a = {"Price fell": 0, "Undercut": 1, "Cheap dump": 2, "No price": 3, "Lowest": 4}
    my_auctions.sort(key=lambda r: (order_a[r["status"]], -(r["u"] * r["qty"])))

    # ---- gear upgrades for each character ---------------------------------------------------------------
    gear_listings, gear_where = upg.merge_listings(realm, neutral_realm)
    gear_ups, gear_wts = upg.all_upgrades(db, {"gear": gear_listings}, char_items, realm_key, gear_where)
    gear_status = upg.status(db, gear_listings, char_items)
    for ck, u in gear_ups.items():
        u["name"] = ck.split("-")[0]

    # ---- neutral Auction House: a separate market both factions share ---------------------------------
    nmodel = sales_model(history, neutral_key, today)
    neutral = neutral_trades(cfg, now, today, history, neutral_key, neutral_realm, scan, typical_low, meta, name, quality,
                             riskm, cut, budget, inventory, flips, sales_of, lambda i: sales_of(i, nmodel), smodel, nmodel)

    # ---- realized profit from your sales -------------------------------------------------------------
    craft_unit_cost = {r["id"]: r["cost"] / max(r["n_out"], 1) for r in crafts if r["cost"] and not r["missing"]}
    profit = pnl.profit_report(db, meta, now, set(raid_by_id), craft_unit_cost, ids_by_name, riskm)

    # ---- characters: level, class, professions (for the Guide) -------------------------------
    profiles = []
    for key, c in char_items:
        profiles.append({
            "name": key.split("-")[0], "level": c.get("level"), "class": c.get("class"), "race": c.get("race"),
            "zone": c.get("zone"), "money": c.get("money") or 0,
            "profs": {k: v for k, v in (c.get("profs") or {}).items() if isinstance(v, (list, tuple)) and len(v) >= 2},
            "recipes": len(c.get("recipes") or {}), "bank": bool(c.get("bankT")),
        })
    profiles.sort(key=lambda p: -(p["level"] or 0))

    # ---- next moves: the best things to do right now, ranked by gold ---------------------------
    next_moves = []
    def move(kind, text, gold=None, detail=""):
        next_moves.append({"kind": kind, "text": text, "gold": int(gold) if gold else None, "detail": detail})

    ready_pos = [r for r in positions if r["status"] == "Sell now"]
    for r in ready_pos[:3]:
        move("sell", f"Sell {r['qty']} {r['name']}: it cleared your profit target", r["pl"], f"From {r['where']}.")
    posts = [r for r in inventory if r["action"] == "ah"]
    if posts:
        total = sum(r["value"] for r in posts)
        names_ = ", ".join(r["name"] for r in posts[:3])
        move("sell", f"Post {len(posts)} item types on the Auction House, starting with {names_}", total,
             "Sell tab in game; match the lowest price.")
    stock_crafts = sorted([r for r in crafts if r["stock"] and r["stock_gain"] > 0], key=lambda r: -r["stock_gain"])
    for r in stock_crafts[:2]:
        move("craft", f"Craft {r['stock']} {r['name']} from mats you already own", r["stock_gain"],
             f"{r['prof']}: worth more than selling the mats raw.")
    buy_crafts = [r for r in crafts if r["profit"] and r["profit"] > 0 and not r["stock"]]
    for r in buy_crafts[:2]:
        move("craft", f"Buy mats and craft {r['name']}", r["profit"], f"{r['prof']}: profit per craft, {r['listed']} listed.")
    real_flips = [r for r in flips if r["kind"] in ("flip", "raid")]
    for r in real_flips[:3]:
        move("flip", f"Buy {r['qty']} {r['name']} at up to {fmt(r['max'])} each and resell", r["profit"], r["why"])
    for key, verb in (("tohome", "on the neutral AH and sell them at home"), ("toneutral", "here and sell them on the neutral AH")):
        rows = neutral[key]
        if rows:
            move("flip", f"Buy {rows[0]['qty']} {rows[0]['name']} {verb}" + (f" (+{len(rows) - 1} more)" if len(rows) > 1 else ""),
                 sum(r["profit"] for r in rows), rows[0]["why"])
    if neutral["sell"]:
        move("sell", f"Sell {len(neutral['sell'])} item type{'s' if len(neutral['sell']) != 1 else ''} on the neutral AH, starting with {neutral['sell'][0]['name']}",
             sum(r["extra"] for r in neutral["sell"]), "Extra over their best use at home, after the 15% cut.")
    for e in profit["relist"][:2]:
        move("fix", f"Stop relisting {e['name']} at that price: only {e['rate'] * 100:.0f}% of what you listed sold", None,
             f"{e['listings']} listings so far, {fmt(e['lost'])} lost in deposits. Price it lower or sell it another way.")
    if vendor:
        move("flip", f"Buy {len(vendor)} underpriced item type{'s' if len(vendor) != 1 else ''} and sell to a vendor", sum(r["profit"] for r in vendor),
             "Vendor flips: no risk.")
    gather_map = {"Herbalism": "Herb", "Mining": "Metal & Stone", "Skinning": "Leather"}
    for p_ in profiles:
        for prof, (skill, mx) in p_["profs"].items():
            gtype = gather_map.get(prof)
            if gtype:
                can = [g for g in gathering if g["type"] == gtype and GATHER_SKILL.get(g["name"], 999) <= (skill or 0)]
                can.sort(key=lambda g: -g["market"])
                best = can[:3]
                nxt = sorted([g for g in gathering if g["type"] == gtype and (skill or 0) < GATHER_SKILL.get(g["name"], 999) <= (skill or 0) + 50],
                             key=lambda g: GATHER_SKILL[g["name"]])
                if best:
                    tail = (f" At {GATHER_SKILL[nxt[0]['name']]} skill you can gather {nxt[0]['name']} ({fmt(nxt[0]['market'])})."
                            if nxt else "")
                    move("gather", f"{p_['name']}'s {prof} ({skill}/{mx}): {', '.join(g['name'] for g in best)} are the best you can gather now",
                         None, "Market: " + ", ".join(f"{g['name']} {fmt(g['market'])}" for g in best) + "." + tail
                         + " Skill needs are classic values; Forever may differ.")
            if mx and skill is not None and skill >= mx - 5 and mx < 300:
                move("skill", f"{p_['name']}'s {prof} is at {skill}/{mx}: visit a trainer for the next rank", None,
                     "You stop gaining skill at the cap.")
    order_k = {"sell": 0, "craft": 1, "flip": 2, "fix": 3, "gather": 4, "skill": 5}
    with_gold = sorted([m for m in next_moves if m["gold"]], key=lambda m: -m["gold"])
    advice = sorted([m for m in next_moves if not m["gold"]], key=lambda m: order_k[m["kind"]])
    # skill and gathering advice has no gold figure, so keep room for it
    next_moves = with_gold[:max(4, 10 - len(advice[:4]))] + advice[:4]

    spent_7d = sum((e.get("q", 0) * e.get("u", 0)) for e in ledger if e.get("t", 0) >= now - 7 * DAY)

    prices = {i: market(i) for i in scan if market(i)}

    return {
        "now": now, "realm": realm_key, "scan_ts": realm.get("lastScan"), "auctions": realm.get("auctions", 0),
        "item_count": realm.get("itemCount", len(scan)), "money": money, "scans_stored": history.scan_count(realm_key),
        "history_days": max((hist(i)[1] for i in scan), default=0),
        "bank_seen": any(c.get("bankT") for c in chars), "chars": [c for c in (db.get("chars") or {})],
        "professions": sorted({r["prof"] for r in crafts if r["prof"]}),
        "flips": flips, "vendor": vendor, "crafts": crafts, "inventory": inventory, "gathering": gathering[:60],
        "trends": trend_rows, "chart": chart, "chart_focus": focus[0] if focus else None,
        "ledger": ledger[-40:], "spent_7d": spent_7d, "prices": prices, "cfg": cfg,
        "bands": bands, "index": index, "weekday": weekday, "raid_plan": raid_plan, "raids": raids_out,
        "positions": positions, "roi": roi, "n_chars": len(chars),
        "manual": manual, "names": {(m.get("n") or "").lower(): i for i, m in meta.items() if m.get("n")},
        "profiles": profiles, "next_moves": next_moves,
        "mail_seen": any(c.get("mailT") for c in chars),
        "neutral": neutral, "profit": profit, "my_auctions": my_auctions,
        "upgrades": gear_ups, "gear_status": gear_status, "spec_options": {c: list(w) for c, w in gear_wts.items()},
        "bbb": bbb_info, "flip_skips": skips, "sales_watch": {"hours": round(smodel["hours"], 1), "days": smodel["days"],
                                             "items": len(smodel["items"])},
        "risk": {"p0": riskm.p0, "p0_basis": riskm.p0_basis, "dep_rate": riskm.dep_rate, "dep_learned": riskm.dep_learned,
                 "units": {i: int(riskm.per_unit(i, "home")) for i in {r["id"] for r in positions} | {r["id"] for r in flips}
                           if riskm.per_unit(i, "home") >= 1},
                 "rates": {r["id"]: round(riskm.rate(r["id"]), 2) for r in inventory if riskm.has_history(r["id"])}},
    }


def neutral_trades(cfg, now, today, history, neutral_key, neutral_realm, scan, typical_low, meta, name, quality, risk, cut,
                   budget, inventory, flips, sales_home, sales_neutral, hmodel, nmodel):
    """Trades between your faction's Auction House and the neutral one (Gadgetzan, Booty Bay, Everlook).

    tohome:    cheap on the neutral AH, worth more at home (buy there, carry or mail it home, sell at home)
    toneutral: cheap at home, worth more on the neutral AH after its 15% cut and bigger deposits
    sell:      things you own that fetch more on the neutral AH than their best use at home
    """
    ncut = float(cfg.get("neutral_cut", 0.15))
    out = {"key": neutral_key, "cut": ncut, "scan_ts": None, "age_days": None, "items": 0, "stale": False,
           "tohome": [], "toneutral": [], "sell": []}
    if not neutral_realm or not neutral_realm.get("items"):
        return out
    nscan = {int(k): v for k, v in neutral_realm["items"].items()}
    n_ts = int(neutral_realm.get("lastScan") or 0)
    age = (now - n_ts) / DAY
    out.update(scan_ts=n_ts, age_days=round(age, 1), items=len(nscan))
    if age > float(cfg.get("neutral_max_age_days", 7)):
        out["stale"] = True
        return out
    nseries = history.series(neutral_key, today - int(cfg["history_days"]))
    min_roi, min_profit = float(cfg["min_roi"]), int(cfg["min_profit"])
    share = float(cfg["max_supply_share"])
    thin = max(3, int(cfg["min_listed"]) // 2)
    age_note = f" Neutral prices are {age:.0f} days old; rescan there before you go." if age >= 2 else ""

    # where you'd sell: matching the cheapest listing there now, never above where it usually bottoms out
    def ref(s_, series_pts):
        if not s_:
            return None
        now_low = s_.get("o") or s_.get("m")
        lows = [p_[1] for p_ in series_pts if p_[1]]
        if len(lows) >= 3 and now_low:
            return min(statistics.median(lows), now_low)
        return now_low

    def home_ref(i):
        s_ = scan.get(i)
        if not s_:
            return None
        now_low = s_.get("o") or s_.get("m")
        low, days = typical_low(i)
        return min(low, now_low) if days >= 3 and now_low else now_low

    def skip_gear(i):
        return (meta.get(i) or {}).get("e") and not cfg["include_gear"]

    min_sold = float(cfg.get("min_sold_per_day", 1.0))
    max_days = float(cfg.get("max_days_to_sell", 3))

    def demand(st, model, ref_price):
        """(resale price, units that house takes in max_days, note) or None when it doesn't sell there."""
        if not st or st["mid"] < min_sold:
            return None
        price = st["usual"] if st["usual"] and st["usual_days"] >= 2 else ref_price
        if not price:
            return None
        price = min(price, ref_price) if ref_price else price
        haircut = model["days"] < 3
        if haircut:
            price *= 0.85   # under three days of history on the house you sell to: trust its prices less
        per_day = st["lo"] if st["lo"] > 0 else st["mid"] / 2
        note = (f" Sells about {rate_txt(st['mid'])} a day there ({st['conf']} confidence)."
                + (" Resale cut 15%: under three days of history there." if haircut else ""))
        return price, max(1, int(per_day * max_days)), per_day, note

    # buy on the neutral AH, sell at home
    for i, ns_ in nscan.items():
        hs = scan.get(i)
        if skip_gear(i) or not hs or (hs.get("q") or 0) < thin:
            continue
        d = demand(sales_home(i), hmodel, home_ref(i))
        if not d:
            continue
        sell, takes, per_day, dnote = d
        per_unit = sell * (1 - cut) - risk.per_unit(i, "home") - 100 / max(1, takes)
        units, cost, top = _units_below(ns_.get("l") or [], per_unit / (1 + min_roi))
        if units <= 0:
            continue
        cap = min(max(1, int((hs.get("q") or 0) * share)), takes)
        avg = cost / units
        if budget != float("inf") and avg > 0:
            cap = min(cap, int(budget // avg))
        units = min(units, cap)
        if units <= 0:
            continue
        profit = int((per_unit - avg) * units)
        roi = (per_unit - avg) / avg if avg else 0
        if profit < min_profit or roi < min_roi:
            continue
        out["tohome"].append({
            "id": i, "name": name(i), "q": quality(i), "kind": "tohome", "max": int(min(top, avg * 1.02)), "qty": units,
            "avg": int(avg), "sell": int(sell), "profit": profit, "roi": round(roi, 3), "listed": hs.get("q", 0),
            "nlisted": ns_.get("q", 0),
            "why": (f"{units} on the neutral AH under {fmt(per_unit / (1 + min_roi))}; at home the cheapest is about "
                    f"{fmt(sell)}. Buy at the neutral AH, carry or mail it home and post at that price. "
                    f"Your {int(cut * 100)}% cut included." + dnote + risk.note(i, "home", units) + age_note),
            "sold_day": round(sales_home(i)["mid"], 1), "profit_day": int((per_unit - avg) * min(units, per_day)),
        })

    # buy at home, sell on the neutral AH
    flip_profit = {r["id"]: r["profit"] for r in flips}
    for i, hs in scan.items():
        ns_ = nscan.get(i)
        if skip_gear(i) or not ns_ or (ns_.get("q") or 0) < thin:
            continue
        d = demand(sales_neutral(i), nmodel, ref(ns_, nseries.get(i, [])))
        if not d:
            continue
        sell, takes, per_day, dnote = d
        per_unit = sell * (1 - ncut) - risk.per_unit(i, "neutral") - 100 / max(1, takes)
        units, cost, top = _units_below(hs.get("l") or [], per_unit / (1 + min_roi))
        if units <= 0:
            continue
        cap = min(max(1, int((ns_.get("q") or 0) * share)), takes)   # neutral markets are small: don't flood them
        avg = cost / units
        if budget != float("inf") and avg > 0:
            cap = min(cap, int(budget // avg))
        units = min(units, cap)
        if units <= 0:
            continue
        profit = int((per_unit - avg) * units)
        roi = (per_unit - avg) / avg if avg else 0
        if profit < min_profit or roi < min_roi or profit <= flip_profit.get(i, 0):
            continue
        out["toneutral"].append({
            "id": i, "name": name(i), "q": quality(i), "kind": "toneutral", "max": int(min(top, avg * 1.02)), "qty": units,
            "avg": int(avg), "sell": int(sell), "profit": profit, "roi": round(roi, 3), "listed": hs.get("q", 0),
            "nlisted": ns_.get("q", 0),
            "why": (f"{units} here under {fmt(per_unit / (1 + min_roi))}; on the neutral AH the cheapest is about {fmt(sell)} "
                    f"({ns_.get('q', 0)} listed). Post at that price; after its {int(ncut * 100)}% cut that still pays. "
                    f"Take them to Gadgetzan, Booty Bay or Everlook, or mail them to a character parked there."
                    + dnote + risk.note(i, "neutral", units) + age_note),
            "sold_day": round(sales_neutral(i)["mid"], 1), "profit_day": int((per_unit - avg) * min(units, per_day)),
        })

    # things you own that pay more on the neutral AH
    for r in inventory:
        i = r["id"]
        ns_ = nscan.get(i)
        if not ns_ or (ns_.get("q") or 0) < thin or not r["qty"]:
            continue
        d = demand(sales_neutral(i), nmodel, ref(ns_, nseries.get(i, [])))
        if not d:
            continue
        sell, takes, _, dnote = d
        post_at = int(sell)
        per_unit = post_at * (1 - ncut) - risk.per_unit(i, "neutral")
        best = r["value"] / r["qty"]
        extra = (per_unit - best) * r["qty"]
        if per_unit <= best * 1.1 or extra < min_profit / 2:
            continue
        out["sell"].append({
            "id": i, "name": r["name"], "q": r["q"], "qty": r["qty"], "price": post_at, "value": int(per_unit * r["qty"]),
            "extra": int(extra), "home": int(best * r["qty"]), "loc": r["loc"], "nlisted": ns_.get("q", 0),
            "why": (f"Post at about {fmt(post_at)} on the neutral AH: {fmt(extra)} more than its best use at home, "
                    f"after the {int(ncut * 100)}% cut." + dnote + risk.note(i, "neutral", r["qty"]) + age_note),
        })
    for key in ("tohome", "toneutral"):
        out[key].sort(key=lambda r: -(r.get("profit_day") or 0))
        out[key] = out[key][: int(cfg["max_targets"])]
    out["sell"].sort(key=lambda r: -r["extra"])
    return out


MANUAL_PATH = Path(__file__).resolve().parent / "data" / "manual.json"


def load_manual():
    try:
        return json.loads(MANUAL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"adds": [], "forgets": {}}


def save_manual(data):
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")


def parse_money(text):
    """'1g20s50c', '20s', '1450' -> copper"""
    import re
    t = (text or "").lower().replace(" ", "")
    if not t:
        return None
    if t.isdigit():
        return int(t)
    total = sum(int(n) * mult for n, mult in
                ((m.group(1), {"g": 10000, "s": 100, "c": 1}[m.group(2)]) for m in re.finditer(r"(\d+)([gsc])", t)))
    return total or None


def _date(day):
    return (datetime.date(1970, 1, 1) + datetime.timedelta(days=day)).strftime("%d %b")


def load_raids(cfg):
    path = Path(cfg.get("raids_file") or Path(__file__).resolve().parent / "raids.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fmt(copper):
    copper = int(round(copper or 0))
    neg = copper < 0
    copper = abs(copper)
    g, s, c = copper // 10000, (copper % 10000) // 100, copper % 100
    if g:
        out = f"{g}g {s:02d}s"
    elif s:
        out = f"{s}s {c:02d}c"
    else:
        out = f"{c}c"
    return ("-" if neg else "") + out


def targets_table(result):
    """The data written to Data/Targets.lua for the addon."""
    keys = ("id", "name", "kind", "max", "qty", "profit", "sell", "why", "sold_day", "profit_day")
    cfg = result["cfg"]
    flips = [r for r in result["flips"] if r["kind"] != "snipe" or cfg.get("include_snipes")]
    toneutral = (result.get("neutral") or {}).get("toneutral") or []
    buys = [{k: r[k] for k in keys if r.get(k) is not None} for r in result["vendor"] + flips + toneutral]
    buys.sort(key=lambda r: r["profit"], reverse=True)
    sells = [{"id": r["id"], "name": r["name"], "price": r["price"], "qty": r["qty"], "action": r["action"],
              "value": r["value"], "loc": r["loc"], "into": r["into"], "hold": r["hold"], "why": r["note"] or None}
             for r in result["inventory"] if r["value"] >= int(cfg.get("min_item_value", 100))]
    crafts = [{"id": r["id"], "name": r["name"], "cost": r["cost"], "value": r["value"], "profit": r["profit"],
               "why": (f"Can make {r['stock']} from your own stock. " if r["stock"] else "") + r["mats"]}
              for r in result["crafts"] if r["profit"] is not None]
    return {
        "generated": result["now"], "realm": result["realm"], "scan": result["scan_ts"],
        "cut": result["cfg"]["ah_cut"], "buys": buys, "sells": sells, "crafts": crafts, "prices": result["prices"],
        "flips": {r["id"]: {"note": r["note"]} for r in result["positions"] if r["note"]},
        "imports": [{k: m[k] for k in ("mid", "id", "q", "u", "t")} for m in result["manual"].get("adds", [])
                    if m.get("realm", result["realm"]) == result["realm"]],
        "forgets": [{"id": int(k), "t": v} for k, v in (result["manual"].get("forgets") or {}).items()],
        "upgrades": {ck: {"main": u["main"], "off": u["off"], "lists": {
                        sp["spec"]: [{"id": r["id"], "key": r["key"], "name": r["name"], "slot": r["slot"], "price": r["price"],
                                      "pct": r["pct"], "gain": r["gain"], "replaces": r["replaces"], "stats": r["stats"],
                                      "where": r.get("where", "")}
                                     for r in sp["items"][:25]] for sp in u["specs"]}}
                     for ck, u in (result.get("upgrades") or {}).items()},
        "risk": result["risk"]["units"],
        "rates": result["risk"].get("rates") or {},
        "neutral": neutral_targets(result),
    }


def neutral_targets(result):
    n = result.get("neutral") or {}
    if not n.get("scan_ts") or n.get("stale"):
        return None
    keys = ("id", "name", "kind", "max", "qty", "profit", "sell", "why", "sold_day", "profit_day")
    return {
        "scan": n["scan_ts"], "cut": n["cut"],
        "buys": [{k: r[k] for k in keys if r.get(k) is not None} for r in n["tohome"]],
        "sells": [{"id": r["id"], "name": r["name"], "price": r["price"], "qty": r["qty"], "action": "ah",
                   "value": r["value"], "loc": r["loc"], "why": r["why"]} for r in n["sell"]],
    }
