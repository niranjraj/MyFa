"""Price history and profit analysis for MyFA Desk."""
import datetime
import json
import math
import sqlite3
import statistics
import time
from pathlib import Path

DAY = 86400

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
        self.db.commit()
        return new

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
    realm_key = cfg.get("realm") or max(realms, key=lambda k: realms[k].get("lastScan") or 0)
    realm = realms[realm_key]
    for k, r in realms.items():
        history.ingest(k, r)

    meta = {int(k): v for k, v in (db.get("items") or {}).items()}
    scan = {int(k): v for k, v in (realm.get("items") or {}).items()}
    vendor_buy = {int(k): v for k, v in (db.get("vendorBuy") or {}).items()}
    for k, v in (cfg.get("vendor_costs") or {}).items():
        vendor_buy[int(k)] = int(v)

    cut = float(cfg["ah_cut"])
    today = now // DAY
    series = history.series(realm_key, today - int(cfg["chart_days"]))
    trends = {i: trend(p) for i, p in series.items()}

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
    for i, s in scan.items():
        m = meta.get(i) or {}
        if m.get("e") and not cfg["include_gear"]:
            continue
        ladder = s.get("l") or []
        total = s.get("q") or 0
        if len(ladder) < 2 or total < 2:
            continue
        wall = _wall(ladder, total)
        h, days = hist(i)
        ref = min(h, wall) if days >= 3 else wall
        if not ref:
            continue
        units, cost, top = _units_below(ladder, ref * float(cfg["flip_threshold"]))
        if units <= 0:
            continue
        avg = cost / units
        cap = max(1, int(total * float(cfg["max_supply_share"])))
        if avg > 0 and budget != float("inf"):
            cap = min(cap, int(budget // avg))
        units = min(units, cap)
        if units <= 0:
            continue
        net = ref * (1 - cut) - avg
        profit = int(net * units)
        roi = net / avg if avg else 0
        if profit < cfg["min_profit"] or roi < cfg["min_roi"]:
            continue
        basis = f"{days}-day history" if days >= 3 else "price gap in this scan"
        risk = "low" if days >= 7 and total >= 40 else ("medium" if days >= 3 else "high")
        thin = total < int(cfg["min_listed"])
        t = trends.get(i)
        if t and t["slope"] is not None and t["slope"] < -0.05:
            risk = "high"
            basis += f", but falling {t['slope'] * 100:.0f}%/day"
        flips.append({
            "id": i, "name": name(i), "q": quality(i), "kind": "snipe" if thin else "flip",
            "max": int(min(top, avg * 1.02)), "qty": units, "avg": int(avg), "sell": int(ref),
            "profit": profit, "roi": round(roi, 3), "listed": total, "days": days, "risk": risk,
            "why": (f"Thin market: only {total} listed, so it may take a long time to sell at {fmt(ref)}. "
                    f"Only for patience or your own use." if thin else
                    f"{units} listed under {int(cfg['flip_threshold'] * 100)}% of market ({basis}). "
                    f"Relist at {fmt(ref)}; {int(cut * 100)}% AH cut included."),
        })
        if thin:
            flips[-1]["risk"] = "high"
    flips.sort(key=lambda r: (r["kind"] == "snipe", -r["profit"]))
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
        ah = price * (1 - cut) if price else 0
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
        out_net = sell * n_out * (1 - cut) if sell else 0
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
        ah = price * (1 - cut) if price else 0
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
        per_unit = b["sell"] * (1 - cut) - b["buy"]
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
            sell_ref = r["sell"] or int((r["market"] or r["now"]) * 1.15)
            profit = int((sell_ref * (1 - cut) - r["now"]) * r["qty"])
            if profit > 0 and not any(f["id"] == r["id"] for f in flips):
                flips.append({
                    "id": r["id"], "name": r["name"], "q": r["q"], "kind": "raid", "max": r["buy"] or r["now"],
                    "qty": r["qty"], "avg": r["now"], "sell": sell_ref, "profit": profit, "roi": 0, "listed": r["listed"],
                    "days": 0, "risk": "medium",
                    "why": f"Raid stock-up for {', '.join(r['raids'])} ({r['days_left']} days). Sell launch week near {fmt(sell_ref)}.",
                })

    ledger = [e for e in (db.get("ledger") or []) if isinstance(e, dict)]

    # ---- my flips: what you bought and still hold, on every character ------------------
    roi = float((db.get("settings") or {}).get("roi") or cfg.get("flip_roi", 0.15))
    buys_by = {}
    for e in ledger:
        if e.get("k") == "buy" and not e.get("x") and e.get("t", 0) >= now - 90 * DAY and e.get("id") and e.get("q") and e.get("u"):
            buys_by.setdefault(int(e["id"]), []).append(e)
    positions = []
    for i, buys in buys_by.items():
        hold = min(owned.get(i, 0), sum(e["q"] for e in buys))
        if hold <= 0:
            continue
        buys.sort(key=lambda e: e["t"], reverse=True)  # oldest sold first, so you hold the newest
        need, spent = hold, 0
        for e in buys:
            take = min(need, e["q"])
            spent += take * e["u"]
            need -= take
            if need <= 0:
                break
        cost = spent / hold
        s_ = scan.get(i)
        now_p = s_["m"] if s_ else None
        target = math.ceil(cost * (1 + roi) / (1 - cut))
        mk = market(i)
        b = band(i)
        suggest = max(target, b["sell"] if b else 0, mk or 0)
        pl = int((now_p * (1 - cut) - cost) * hold) if now_p else None
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
            "ready_value": int((target * (1 - cut) - cost) * hold), "note": note,
        })
    order = {"Sell now": 0, "Hold": 1, "Under water": 2, "Not listed": 3}
    positions.sort(key=lambda r: (order[r["status"]], -(r["pl"] or -10**12)))

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
        "mail_seen": any(c.get("mailT") for c in chars),
    }


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
    keys = ("id", "name", "kind", "max", "qty", "profit", "why")
    cfg = result["cfg"]
    flips = [r for r in result["flips"] if r["kind"] != "snipe" or cfg.get("include_snipes")]
    buys = [{k: r[k] for k in keys} for r in result["vendor"] + flips]
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
    }
