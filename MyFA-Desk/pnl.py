"""Realized profit from your sales, how often each item sells, and the deposits that costs you.

The addon records every sale, expiry and cancellation from your Auction House mail (MyFA_DB.sales), with the
cost of the purchases each sale closed. This module turns that into:
  * RiskModel: per-item sell rate and the expected deposit you lose per unit sold (used in every profit figure)
  * profit_report(): totals by approach (flips, crafts, raid holds, farmed/looted), per-item stats, daily profit
"""
from collections import defaultdict

DAY = 86400
CATEGORIES = [
    ("flip", "Flips", "Bought on the Auction House and resold"),
    ("raid", "Raid holds", "Raid consumables you bought and held for raid demand"),
    ("craft", "Crafts", "Things you crafted (mat cost at today's prices)"),
    ("farm", "Farmed and looted", "Things you gathered or looted: no purchase cost"),
]


def _units_sold(o):
    return int(o.get("q") or 0)


class RiskModel:
    """Expected deposit lost per unit sold = deposit per unit x (1 - sell rate) / sell rate.

    The sell rate is the share of listed units that sold, from your own sale/expiry mails, blended with a
    prior (your overall rate, or default_sell_rate) so one bad listing doesn't swing it. Deposit per unit is
    vendor price x your learned deposit rate for that Auction House (or the classic 8-hour rule).
    """

    def __init__(self, db, meta, cfg, ids_by_name=None):
        self.meta = meta
        self.cfg = cfg
        self.stats = defaultdict(lambda: {"sold": 0, "units": 0, "n": 0, "lost": 0})
        for o in db.get("sales") or []:
            if not isinstance(o, dict):
                continue
            i = o.get("id")
            if i is None and ids_by_name and o.get("n"):
                i = ids_by_name.get(str(o["n"]).lower())
            if i is None:
                continue
            s = self.stats[int(i)]
            q = _units_sold(o)
            s["units"] += q
            s["n"] += 1
            if o.get("k") == "sold":
                s["sold"] += q
            else:
                s["lost"] += int(o.get("lost") or 0)
        mails = sum(s["n"] for s in self.stats.values())
        units = sum(s["units"] for s in self.stats.values())
        sold = sum(s["sold"] for s in self.stats.values())
        default = float(cfg.get("default_sell_rate", 0.6))
        self.p0 = min(0.95, max(0.2, sold / units)) if mails >= 10 and units else default
        self.p0_basis = "your overall sell rate" if mails >= 10 and units else "a starting guess until MyFA sees more of your sales"
        rates = db.get("depRate") or {}
        home = rates.get("home")
        self.dep_rate = {
            "home": float(home) if home else float(cfg.get("deposit_rate", 0.20)),
            "neutral": float(rates["neutral"]) if rates.get("neutral") else
            (float(home) if home else float(cfg.get("deposit_rate", 0.20))) * float(cfg.get("neutral_deposit_mult", 5)),
        }
        self.dep_learned = {"home": bool(home), "neutral": bool(rates.get("neutral"))}

    def rate(self, i):
        s = self.stats.get(int(i)) if i is not None else None
        if not s or not s["units"]:
            return self.p0
        raw = s["sold"] / s["units"]
        w = s["n"]
        return max(0.15, (raw * w + self.p0 * 2) / (w + 2))

    def has_history(self, i):
        s = self.stats.get(int(i)) if i is not None else None
        return bool(s and s["n"])

    def dep_unit(self, i, kind="home"):
        v = (self.meta.get(int(i)) or {}).get("v") or 0
        return v * self.dep_rate.get(kind, self.dep_rate["home"])

    def per_unit(self, i, kind="home"):
        """Expected lost deposit for each unit you end up selling."""
        p = self.rate(i)
        return self.dep_unit(i, kind) * (1 - p) / p

    def note(self, i, kind="home", units=1):
        """A short sentence for 'why' columns, or '' when the cost is negligible."""
        cost = self.per_unit(i, kind) * units
        if cost < 50:   # under 50 copper in total: not worth mentioning
            return ""
        p = self.rate(i)
        basis = f"yours sell {p * 100:.0f}%" if self.has_history(i) else f"assumes {p * 100:.0f}% sell"
        return f" Lost relist deposits included: about {_fmt(cost)} ({basis})."


def _fmt(copper):
    copper = int(round(copper or 0))
    g, s, c = abs(copper) // 10000, (abs(copper) % 10000) // 100, abs(copper) % 100
    out = f"{g}g {s:02d}s" if g else (f"{s}s {c:02d}c" if s else f"{c}c")
    return ("-" if copper < 0 else "") + out


def profit_report(db, meta, now, raid_ids, craft_unit_cost, ids_by_name, risk):
    """Everything the Profit tab shows."""
    def name(i, fallback=None):
        return (meta.get(i) or {}).get("n") or fallback or f"Item {i}"

    def quality(i):
        return (meta.get(i) or {}).get("c", 1)

    bought = {int(e["id"]) for e in (db.get("ledger") or []) if isinstance(e, dict) and e.get("k") == "buy" and e.get("id")}

    trades = []     # one row per sale part or lost deposit
    for o in db.get("sales") or []:
        if not isinstance(o, dict):
            continue
        i = o.get("id")
        if i is None and o.get("n"):
            i = ids_by_name.get(str(o["n"]).lower())
        i = int(i) if i is not None else None
        t = int(o.get("t") or 0)
        ah = o.get("a") or "home"
        base = {"t": t, "id": i, "name": name(i, o.get("n")) if i else (o.get("n") or "?"), "q_": quality(i) if i else 1,
                "ah": ah, "char": str(o.get("c") or "").split("-")[0]}
        if o.get("k") == "sold":
            q = max(1, _units_sold(o))
            net = int(o.get("g") or 0) - int(o.get("cut") or 0)
            mq = min(q, int(o.get("mq") or 0))
            if mq:
                share = net * mq / q
                cost = int(o.get("cost") or 0)
                cat = "raid" if i in raid_ids else "flip"
                trades.append({**base, "kind": "sold", "cat": cat, "qty": mq, "net": share, "cost": cost,
                               "lost": 0, "profit": share - cost, "est": False})
            if q - mq > 0:
                share = net * (q - mq) / q
                unit = craft_unit_cost.get(i) if i is not None else None
                if unit is not None:
                    cost, cat, est = unit * (q - mq), "craft", True
                else:
                    cost, cat, est = 0, "farm", False
                trades.append({**base, "kind": "sold", "cat": cat, "qty": q - mq, "net": share, "cost": cost,
                               "lost": 0, "profit": share - cost, "est": est})
        else:
            lost = int(o.get("lost") or 0)
            if i in bought:
                cat = "raid" if i in raid_ids else "flip"
            elif i in craft_unit_cost:
                cat = "craft"
            else:
                cat = "farm"
            trades.append({**base, "kind": o.get("k"), "cat": cat, "qty": _units_sold(o), "net": 0, "cost": 0,
                           "lost": lost, "profit": -lost, "est": bool(o.get("est"))})
    trades.sort(key=lambda r: -r["t"])

    def totals(since):
        out = {c: {"net": 0, "cost": 0, "lost": 0, "profit": 0, "sales": 0} for c, _, _ in CATEGORIES}
        neutral = 0
        for r in trades:
            if r["t"] < since:
                continue
            c = out[r["cat"]]
            c["net"] += r["net"]
            c["cost"] += r["cost"]
            c["lost"] += r["lost"]
            c["profit"] += r["profit"]
            if r["kind"] == "sold":
                c["sales"] += 1
            if r["ah"] == "neutral":
                neutral += r["profit"]
        s = {k: sum(c[k] for c in out.values()) for k in ("net", "cost", "lost", "profit", "sales")}
        return {"cats": out, "sum": s, "neutral": neutral}

    windows = {"7": totals(now - 7 * DAY), "30": totals(now - 30 * DAY), "all": totals(0)}

    # per item: how well it sells and what it made
    items = {}
    for o in db.get("sales") or []:
        if not isinstance(o, dict):
            continue
        i = o.get("id")
        if i is None and o.get("n"):
            i = ids_by_name.get(str(o["n"]).lower())
        if i is None:
            continue
        i = int(i)
        e = items.setdefault(i, {"id": i, "name": name(i), "q": quality(i), "listings": 0, "sold": 0, "expired": 0,
                                 "cancelled": 0, "lost": 0, "profit": 0, "last": 0})
        e["listings"] += 1
        k = o.get("k")
        if k == "sold":
            e["sold"] += _units_sold(o)
            e["last"] = max(e["last"], int(o.get("t") or 0))
        elif k in ("expired", "cancelled"):
            e[k] += _units_sold(o)
            e["lost"] += int(o.get("lost") or 0)
    for r in trades:
        if r["id"] in items:
            items[r["id"]]["profit"] += r["profit"]
    item_rows = []
    for e in items.values():
        units = e["sold"] + e["expired"] + e["cancelled"]
        e["rate"] = e["sold"] / units if units else 0
        e["relist"] = e["listings"] >= 3 and e["rate"] < 0.4
        e["risk_unit"] = int(risk.per_unit(e["id"]))
        item_rows.append(e)
    item_rows.sort(key=lambda e: (not e["relist"], -e["profit"]))

    # daily profit for the last 30 days
    today = now // DAY
    daily = defaultdict(float)
    for r in trades:
        d = r["t"] // DAY
        if d > today - 30:
            daily[d] += r["profit"]
    days = [{"day": d, "profit": int(daily.get(d, 0))} for d in range(today - 29, today + 1)]

    return {
        "trades": trades[:300], "windows": windows, "items": item_rows, "daily": days,
        "has_data": bool(trades), "categories": CATEGORIES,
        "relist": [e for e in item_rows if e["relist"]],
    }
