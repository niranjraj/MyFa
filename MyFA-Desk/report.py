"""Self-contained HTML dashboard for MyFA Desk results."""
import html
import time

QUALITY = {0: "q0", 1: "q1", 2: "q2", 3: "q3", 4: "q4", 5: "q5"}


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def money(copper, signed=False):
    if copper is None:
        return '<span class="na">n/a</span>'
    copper = int(round(copper))
    neg = copper < 0
    a = abs(copper)
    g, s, c = a // 10000, (a % 10000) // 100, a % 100
    if g:
        body = f'{g:,}<i class="g">g</i>&#8202;{s:02d}<i class="s">s</i>'
    elif s:
        body = f'{s}<i class="s">s</i>&#8202;{c:02d}<i class="c">c</i>'
    else:
        body = f'{c}<i class="c">c</i>'
    sign = "&minus;" if neg else ("+" if signed and a else "")
    return f'<span class="m">{sign}{body}</span>'


def ago(ts, now):
    if not ts:
        return "never"
    m = int((now - ts) // 60)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    if m < 2880:
        return f"{m // 60} h ago"
    return f"{m // 1440} days ago"


def item(r, chart_ids=()):
    cls = QUALITY.get(r.get("q", 1), "q1")
    if r.get("id") in chart_ids:
        return (f'<button type="button" class="item itemlink {cls}" data-item="{r["id"]}" '
                f'title="Show price history">{esc(r["name"])}</button>')
    return f'<span class="item {cls}">{esc(r["name"])}</span>'


def td(content, value=None, cls=""):
    v = f' data-v="{esc(value)}"' if value is not None else ""
    c = f' class="{cls}"' if cls else ""
    return f"<td{c}{v}>{content}</td>"


def pct(x, per_day=False):
    if x is None:
        return '<span class="na">n/a</span>'
    cls = "pos" if x > 0.005 else ("neg" if x < -0.005 else "")
    return f'<span class="{cls}">{x * 100:+.{1 if per_day else 0}f}%{"/day" if per_day else ""}</span>'


def table(tab_id, columns, rows, empty):
    if not rows:
        return f'<div class="empty"><p>{empty}</p></div>'
    head = "".join(
        f'<th scope="col" class="{c[2]}"><button type="button" data-col="{n}">{esc(c[0])}</button></th>'
        for n, c in enumerate(columns))
    body = "\n".join("<tr>" + "".join(cells) + "</tr>" for cells in rows)
    return (f'<div class="tablewrap"><table data-table="{tab_id}"><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


RISK = {"none": "risk-none", "low": "risk-low", "medium": "risk-med", "high": "risk-high"}
ACTION = {"ah": ("Auction House", "act-ah"), "vendor": ("Vendor", "act-v"), "craft": ("Craft", "act-c"),
          "hold": ("Hold", "act-h")}



PHASES = [("stock", "Stock up", "more than 14 days out"), ("build", "Build stock", "7 to 14 days"),
          ("launch", "Launch week", "0 to 7 days"), ("raiding", "Raiding", "first 2 weeks"),
          ("settled", "Settled", "after that")]
PHASE_TIP = {
    "stock": "Buy consumables and their mats only when they dip under their usual low, and craft what you can. Don't sell raid items now.",
    "build": "Keep buying dips and crafting. Start pricing what you hold, but keep it until launch week.",
    "launch": "Demand peaks now. Sell held stock and fresh crafts; don't buy except for your own raid.",
    "raiding": "Raid nights keep demand high. Keep selling, and list before your server's raid evenings.",
    "settled": "Launch demand is over. Clear spare stock and go back to normal flipping.",
}
ACTION_CLS = {"Buy": "act-c", "Sell": "act-ah", "Craft & sell": "act-ah", "Craft & hold": "act-c", "Hold": "act-h",
              "Wait for dip": "act-v", "Don't buy": "risk-high", "Normal": "act-v", "Watch": "act-v"}
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def analysis_panel(result, it, sort_or):
    cfg = result["cfg"]
    cut_pct = f'{cfg["ah_cut"] * 100:g}%'
    parts = []

    ready = [r for r in result["positions"] if r["status"] == "Sell now"]
    if ready:
        total = sum(r["pl"] or 0 for r in ready)
        items = "".join(
            f'<li>{it(r)} <span class="sub">x{r["qty"]} · {esc(r["where"])}</span>'
            f'<span class="num pos">{money(r["pl"], True)}</span></li>' for r in ready[:6])
        parts.append(f"""
<section class="block ready" aria-labelledby="h-ready">
  <div class="blockhead">
    <h2 id="h-ready">Ready to sell</h2>
    <p class="lede">{len(ready)} of your flips cleared your profit target. Selling them all at today's lowest price
      makes <strong>{money(total, True)}</strong> after the cut. Fetch them from the bank or mailbox where noted.</p>
  </div>
  <ul class="readylist">{items}</ul>
</section>""")

    # raid prep
    raids = result["raids"]
    if raids:
        first = raids[0]
        same = [r["name"] for r in raids if r["day"] == first["day"]]
        cur = next((r["phase"] for r in result["raid_plan"] if r["phase"]), "stock")
        steps = "".join(
            f'<li class="{"on" if key == cur else ""}"><b>{label}</b><span>{hint}</span></li>' for key, label, hint in PHASES)
        rows, watch = [], []
        for r in result["raid_plan"]:
            if r["action"] == "Watch":
                watch.append(esc(r["name"]))
                continue
            rows.append([
                td(it(r) if r["id"] else esc(r["name"]), r["name"]),
                td(esc(r["role"]), r["role"]),
                td(f'<span class="{ACTION_CLS.get(r["action"], "")}">{esc(r["action"])}</span>'
                   + (f' <span class="sub">x{r["qty"]}</span>' if r["qty"] else ""), r["action"], "nowrap"),
                td(money(r["now"]) if r["now"] else '<span class="na">none</span>', sort_or(r["now"]), "num"),
                td(money(r["buy"]) if r["buy"] else '<span class="na">n/a</span>', sort_or(r["buy"]), "num"),
                td(money(r["sell"]) if r["sell"] else '<span class="na">n/a</span>', sort_or(r["sell"]), "num"),
                td(pct(r["change7"]), sort_or(r["change7"]), "num"),
                td(f'{r["owned"]:,}' if r["owned"] else "", r["owned"], "num"),
                td(money(r["craft"], True) if r["craft"] else "", sort_or(r["craft"]), "num pos" if r["craft"] else "num"),
                td(esc(r["why"]), None, "why"),
            ])
        table_html = table("raidplan", [
            ("Item", "s", ""), ("Used for", "s", ""), ("Action", "s", ""), ("Lowest now", "n", "num"),
            ("Usual low", "n", "num"), ("Usual high", "n", "num"), ("7-day", "n", "num"), ("You own", "n", "num"),
            ("Craft profit", "n", "num"), ("Why", "s", "why")], rows,
            "None of the raid consumables in raids.json are on the Auction House yet.")
        watch_html = (f'<details class="watch"><summary>{len(watch)} raid items aren\'t listed yet, so there\'s no price to judge</summary>'
                      f'<p>{", ".join(watch)}.</p></details>' if watch else "")
        parts.append(f"""
<section class="block" aria-labelledby="h-raid">
  <div class="blockhead">
    <h2 id="h-raid">Raid prep</h2>
    <p class="lede"><strong>{esc(", ".join(same))}</strong> open {esc(first["date"])},
      <strong>{first["days_left"]} days</strong> away.{" " + PHASE_TIP.get(cur, "")}</p>
  </div>
  <ol class="phases" aria-label="Where we are in the raid cycle">{steps}</ol>
  {table_html}
  {watch_html}
  <p class="fine">Timing follows how WoW markets usually move around a new raid, not a guarantee. Dates and items live in
  <code>raids.json</code>: add new raids there when Blizzard announces them.</p>
</section>""")

    # market movement
    if result["index"] and result["index"]["series"]:
        movers = sorted([r for r in result["trends"] if r["days"] >= 3], key=lambda r: r["change7"])
        down = movers[:5]
        up = list(reversed(movers[-5:]))
        def mv(rows):
            return "".join(f'<li>{it(r)}<span class="num">{pct(r["change7"])}</span></li>' for r in rows)
        parts.append(f"""
<section class="block" aria-labelledby="h-index">
  <div class="blockhead">
    <h2 id="h-index">Market movement</h2>
    <p class="lede">Each line is the median item's price compared with its first scan (100 = unchanged). Above 100 the group got pricier.</p>
  </div>
  <div class="chartcard">
    <ul class="legend" id="index-legend" aria-label="Series"></ul>
    <div class="plot" id="plot-index" aria-label="Market price index by category"></div>
    <div class="tip" id="index-tip" hidden></div>
  </div>
  <div class="movers">
    <div><h3>Up most in 7 days</h3><ul>{mv(up)}</ul></div>
    <div><h3>Down most in 7 days</h3><ul>{mv(down)}</ul></div>
  </div>
</section>""")
    else:
        parts.append('<section class="block"><div class="blockhead"><h2>Market movement</h2></div>'
                     '<div class="empty"><p>Needs scans on at least 2 days. Scan once a day.</p></div></section>')

    # flip bands
    zone = {"buy": ('In buy zone', "act-c"), "sell": ("In sell zone", "act-ah"), "mid": ("In between", "act-v")}
    band_rows = [[
        td(it(r), r["name"]),
        td(f'<span class="{zone[r["zone"]][1]}">{zone[r["zone"]][0]}</span>', {"buy": 0, "mid": 1, "sell": 2}[r["zone"]]),
        td(money(r["now"]), r["now"], "num"),
        td(money(r["buy"]), r["buy"], "num"),
        td(money(r["sell"]), r["sell"], "num"),
        td(money(r["per_unit"], True), r["per_unit"], "num pos"),
        td(f'{r["spread"] * 100:.0f}%', r["spread"], "num"),
        td(f'{r["vol"] * 100:.0f}%', r["vol"], "num"),
        td(f'{r["listed"]:,}', r["listed"], "num"),
        td(f'{r["owned"]:,}' if r["owned"] else "", r["owned"], "num"),
    ] for r in result["bands"]]
    parts.append(f"""
<section class="block" aria-labelledby="h-bands">
  <div class="blockhead">
    <h2 id="h-bands">Flip bands</h2>
    <p class="lede">Items that keep swinging between a cheap and an expensive price without trending steadily up or down. <em>Buy under</em> is their usual low
    (20th percentile of daily lowest prices over {cfg["band_days"]} days), <em>sell at</em> their usual high (80th). Profit is after the {cut_pct} cut.
    Items in the buy zone are listed first.</p>
  </div>
  {table("bands", [("Item", "s", ""), ("Zone", "n", ""), ("Lowest now", "n", "num"), ("Buy under", "n", "num"),
                   ("Sell at", "n", "num"), ("Profit/unit", "n", "num"), ("Spread", "n", "num"), ("Swing", "n", "num"),
                   ("Listed", "n", "num"), ("You own", "n", "num")], band_rows,
          "Bands need 5 or more days of scans for an item. Scan daily and they fill in.")}
</section>""")

    # weekday
    wd = result["weekday"]
    if wd:
        lo_i, hi_i = wd.index(min(wd)), wd.index(max(wd))
        span = max(abs(v) for v in wd) or 1
        bars = "".join(
            f'<li><span class="d">{DOW[k]}</span><span class="bar"><i style="--w:{abs(v) / span * 50:.1f}%" '
            f'class="{"up" if v >= 0 else "down"}"></i></span><span class="num">{v * 100:+.1f}%</span></li>'
            for k, v in enumerate(wd))
        wd_html = (f'<p class="lede">Prices run cheapest on <strong>{DOW[lo_i]}</strong> and highest on '
                   f'<strong>{DOW[hi_i]}</strong>, compared with each item\'s own average. Buy on the low day, list before the high day.</p>'
                   f'<ul class="weekday">{bars}</ul>')
    else:
        wd_html = ('<div class="empty"><p>Needs 14 days of scans to find which weekday is cheapest. Until then, a common pattern is '
                   'cheaper prices after the weekly reset and higher ones before raid nights.</p></div>')
    parts.append(f'<section class="block" aria-labelledby="h-wd"><div class="blockhead"><h2 id="h-wd">Best day to buy and sell</h2></div>{wd_html}</section>')

    # playbook
    best_band = next((r for r in result["bands"] if r["zone"] == "buy"), None)
    tip_band = (f' Right now {it(best_band)} is in its buy zone at {money(best_band["now"])}; it usually sells near {money(best_band["sell"])}.'
                if best_band else "")
    parts.append(f"""
<section class="block" aria-labelledby="h-play">
  <div class="blockhead"><h2 id="h-play">How to flip on Forever</h2></div>
  <ol class="playbook">
    <li><b>Scan at the same times each day.</b> One full scan a day builds the history behind bands, trends and the raid plan. Two (morning and evening) is better.</li>
    <li><b>Buy only in the buy zone.</b> Use the Flip bands above or the Flips tab. Never pay above <em>buy under</em> just because it's the lowest listing.{tip_band}</li>
    <li><b>Stick to items that sell.</b> Prefer items with a lot listed. Thin markets look profitable but can take days to sell.</li>
    <li><b>Match, don't undercut.</b> On Forever the newest listing at a price sells first, so matching the lowest price is enough and keeps the price from sliding.</li>
    <li><b>Cap your exposure.</b> MyFA never buys more than {int(cfg["max_supply_share"] * 100)}% of an item's supply or {int(cfg["max_spend_fraction"] * 100)}% of your gold on one item. Spread across several items.</li>
    <li><b>Count the cut.</b> Every profit figure already takes off the {cut_pct} Auction House cut. Confirm the real cut from a sale mail and set <code>ah_cut</code>.</li>
    <li><b>Time raids.</b> Stock consumables and mats while a raid is more than a week away, then sell in launch week.</li>
    <li><b>Cut losers.</b> If an item drops below what you paid and the trend is falling, sell at market and move on rather than waiting.</li>
  </ol>
</section>""")
    return "".join(parts)


def build(result, advice=None, config_path=""):
    now = result["now"]
    cfg = result["cfg"]
    realm, _, faction = result["realm"].rpartition("-")
    cut_pct = f'{cfg["ah_cut"] * 100:g}%'
    chart_ids = set(result["chart"])
    it = lambda r: item(r, chart_ids)  # noqa: E731
    sort_or = lambda x, d=-999: x if x is not None else d  # noqa: E731

    flips_rows = [[
        td(it(r), r["name"]),
        td(money(r["avg"]), r["avg"], "num"),
        td(money(r["max"]), r["max"], "num"),
        td(f'{r["qty"]:,}', r["qty"], "num"),
        td(money(r["sell"]), r["sell"], "num"),
        td(money(r["profit"], True), r["profit"], "num pos"),
        td(f'{r["roi"] * 100:.0f}%', r["roi"], "num"),
        td(f'{r["listed"]:,}', r["listed"], "num"),
        td(f'<span class="{RISK[r["risk"]]}">{r["risk"]}</span>', ["none", "low", "medium", "high"].index(r["risk"])),
        td(esc(r["why"]), None, "why"),
    ] for r in result["flips"]]

    vendor_rows = [[
        td(it(r), r["name"]),
        td(money(r["avg"]), r["avg"], "num"),
        td(f'{r["qty"]:,}', r["qty"], "num"),
        td(money(r["sell"]), r["sell"], "num"),
        td(money(r["profit"], True), r["profit"], "num pos"),
        td(f'{r["roi"] * 100:.0f}%', r["roi"], "num"),
    ] for r in result["vendor"]]

    inv_rows = []
    for r in result["inventory"]:
        label, cls = ACTION[r["action"]]
        if r["into"]:
            label += f' <span class="sub">into {esc(r["into"])}</span>'
        inv_rows.append([
            td(it(r), r["name"]),
            td(f'{r["qty"]:,}', r["qty"], "num"),
            td(esc(r["loc"]), r["loc"]),
            td(f'<span class="{cls}">{label}</span>', r["action"]),
            td(money(r["price"]) if r["price"] else '<span class="na">none listed</span>', r["price"], "num"),
            td(money(r["ah"]), r["ah"], "num"),
            td(money(r["vendor"]), r["vendor"], "num"),
            td(money(r["craft"]) if r["craft"] else '<span class="na">n/a</span>', r["craft"], "num"),
            td(money(r["value"]), r["value"], "num strong"),
            td(money(r["gain"], True), r["gain"], "num pos" if r["gain"] else "num"),
            td(pct(r["trend"], True), sort_or(r["trend"]), "num"),
            td(esc(r["note"]), None, "why"),
        ])

    craft_rows = []
    for r in result["crafts"]:
        p = r["profit"]
        pcls = "num pos" if p and p > 0 else ("num neg" if p is not None else "num")
        mats = esc(r["mats"]) + (f'<br><span class="warn">No price for: {esc(", ".join(r["missing"]))}</span>' if r["missing"] else "")
        craft_rows.append([
            td(it(r), r["name"]),
            td(esc(r["prof"]), r["prof"]),
            td(money(r["cost"]), r["cost"], "num"),
            td(money(r["value"]), r["value"], "num"),
            td(money(p, True) if p is not None else '<span class="na">n/a</span>', sort_or(p, -10**12), pcls),
            td(f'{r["margin"] * 100:.0f}%' if r["margin"] is not None else "", sort_or(r["margin"]), "num"),
            td(f'{r["stock"]:,}' if r["stock"] else '<span class="na">0</span>', r["stock"], "num"),
            td(money(r["stock_gain"], True) if r["stock"] else "", r["stock_gain"],
               "num pos" if r["stock_gain"] > 0 else ("num neg" if r["stock_gain"] < 0 else "num")),
            td(pct(r["trend"], True), sort_or(r["trend"]), "num"),
            td(f'{r["listed"]:,}', r["listed"], "num"),
            td(mats, None, "why"),
        ])

    gather_rows = [[
        td(it(r), r["name"]),
        td(esc(r["type"]), r["type"]),
        td(money(r["market"]), r["market"], "num strong"),
        td(money(r["now"]), r["now"], "num"),
        td(money(r["stack"]), r["stack"], "num"),
        td(f'{r["listed"]:,}', r["listed"], "num"),
        td(pct(r["change7"]), sort_or(r["change7"]), "num"),
        td(pct(r["slope"], True), sort_or(r["slope"]), "num"),
        td(f'{r["owned"]:,}' if r["owned"] else "", r["owned"], "num"),
    ] for r in result["gathering"]]

    trend_rows = [[
        td(it(r), r["name"]),
        td(money(r["now"]), r["now"], "num"),
        td(money(r["market"]), r["market"], "num"),
        td(pct(r["change7"]), r["change7"], "num"),
        td(pct(r["slope"], True), sort_or(r["slope"]), "num"),
        td(str(r["days"]), r["days"], "num"),
        td(f'{r["listed"]:,}', r["listed"], "num"),
        td(f'{r["owned"]:,}' if r["owned"] else "", r["owned"], "num"),
    ] for r in result["trends"]]

    STATUS = {"Sell now": "act-c", "Hold": "act-h", "Under water": "risk-high", "Not listed": "act-v"}
    pos_rows = [[
        td(it(r), r["name"]),
        td(f'<span class="{STATUS[r["status"]]}">{esc(r["status"])}</span>', ["Sell now", "Hold", "Under water", "Not listed"].index(r["status"]), "nowrap"),
        td(f'{r["qty"]:,}', r["qty"], "num"),
        td(esc(r["where"]), r["where"]),
        td(money(r["cost"]), r["cost"], "num"),
        td(money(r["now"]) if r["now"] else '<span class="na">none</span>', sort_or(r["now"]), "num"),
        td(money(r["target"]), r["target"], "num"),
        td(money(r["suggest"]), r["suggest"], "num strong"),
        td(money(r["pl"], True) if r["pl"] is not None else '<span class="na">n/a</span>', sort_or(r["pl"], -10**12),
           "num " + ("pos" if (r["pl"] or 0) > 0 else "neg" if (r["pl"] or 0) < 0 else "")),
        td(pct(r["trend"], True), sort_or(r["trend"]), "num"),
        td(time.strftime("%d %b", time.localtime(r["since"])), r["since"]),
        td(esc(r["note"]), None, "why"),
    ] for r in result["positions"]]

    names = {}
    for group in ("flips", "vendor", "inventory", "trends"):
        for r in result[group]:
            names[r["id"]] = r["name"]
    ledger_rows = [[
        td(time.strftime("%d %b %H:%M", time.localtime(e.get("t", 0))), e.get("t", 0)),
        td(esc(names.get(e.get("id"), f'Item {e.get("id")}')), names.get(e.get("id"), "")),
        td(f'{e.get("q", 0):,}', e.get("q", 0), "num"),
        td(money(e.get("u", 0)), e.get("u", 0), "num"),
        td(money(e.get("u", 0) * e.get("q", 0)), e.get("u", 0) * e.get("q", 0), "num"),
    ] for e in reversed(result["ledger"])]

    total_flip = sum(r["profit"] for r in result["flips"]) + sum(r["profit"] for r in result["vendor"])
    inv_value = sum(r["value"] for r in result["inventory"])
    inv_gain = sum(r["gain"] for r in result["inventory"] if r["action"] in ("craft",))
    profs = ", ".join(result["professions"]) or "none yet"

    chart_html = CHART_HTML if result["chart"] else (
        '<div class="empty"><p>Charts need scans on at least 2 different days. Scan once a day and they fill in; '
        'history is kept in data\\history.sqlite.</p></div>')

    panels = []
    if advice:
        panels.append(("claude", "Claude", None, f'<div class="advice">{advice}</div>',
                       "Claude's read on this scan, from your API key."))
    raid_note = ""
    if result["raids"]:
        r0 = result["raids"][0]
        raid_note = f" Next raids open {esc(r0['date'])} ({r0['days_left']} days)."
    panels.append(("analysis", "Analysis", None, analysis_panel(result, it, sort_or),
                   "Your overview: raid timing, how the market is moving, the price bands to flip in, and how to flip." + raid_note))
    ready = [r for r in result["positions"] if r["status"] == "Sell now"]
    roi_pct = int(round(result["roi"] * 100))
    panels.append(("mine", "My flips", len(result["positions"]), table("mine", [
        ("Item", "s", ""), ("Status", "n", ""), ("Qty", "n", "num"), ("Where", "s", ""), ("You paid", "n", "num"),
        ("Lowest now", "n", "num"), ("Alert at", "n", "num"), ("Aim to sell at", "n", "num"), ("Profit now", "n", "num"),
        ("Trend", "n", "num"), ("Bought", "n", ""), ("Note", "s", "why")], pos_rows,
        "Nothing tracked yet. Every Auction House purchase is tracked automatically, from any window or addon. "
        "For something you bought earlier, type <code>/myfa bought [item] qty price</code> in game, for example "
        "<code>/myfa bought [Golden Sansam] 20 14s50c</code>."),
        f"Items you bought and still hold on any character, bags, bank or mailbox. <em>Alert at</em> is the lowest listing "
        f"that clears {roi_pct}% profit after the {cut_pct} cut. MyFA alerts you in game and here when it's reached. "
        f"<em>Aim to sell at</em> is the higher of that, the market value and the item's usual high. "
        f"Change the {roi_pct}% in game with <code>/myfa roi 20</code>."))
    panels += [
        ("flips", "Flips", len(result["flips"]), table("flips", [
            ("Item", "s", ""), ("Avg buy", "n", "num"), ("Buy up to", "n", "num"), ("Qty", "n", "num"),
            ("Relist at", "n", "num"), ("Profit", "n", "num"), ("ROI", "n", "num"), ("Listed", "n", "num"),
            ("Risk", "n", ""), ("Why", "s", "why")], flips_rows,
            "No flips pass your filters right now. With fewer than 3 days of scans, flips come only from price gaps "
            "inside one scan, so scan once a day. Lowering <code>min_profit</code> or raising <code>flip_threshold</code> "
            "in config.json shows more."),
         f"Units listed under {int(cfg['flip_threshold'] * 100)}% of market. Profit is after the {cut_pct} AH cut, "
         f"capped at {int(cfg['max_supply_share'] * 100)}% of supply and {int(cfg['max_spend_fraction'] * 100)}% of your gold per item. "
         "Falling items are marked high risk."),
        ("vendor", "Vendor flips", len(result["vendor"]), table("vendor", [
            ("Item", "s", ""), ("Avg buy", "n", "num"), ("Qty", "n", "num"), ("Vendor pays", "n", "num"),
            ("Profit", "n", "num"), ("ROI", "n", "num")], vendor_rows,
            "Nothing is listed below its vendor price. These show up most when people dump cloth and herbs late at night."),
         "Listed below what a vendor pays. Buy them all and sell them to any merchant. No risk."),
        ("inventory", "All characters", len(result["inventory"]), table("inventory", [
            ("Item", "s", ""), ("Qty", "n", "num"), ("Where", "s", ""), ("Best use", "s", ""), ("Post at", "n", "num"),
            ("AH net", "n", "num"), ("Vendor", "n", "num"), ("Crafted", "n", "num"), ("Best value", "n", "num"),
            ("Gain vs next", "n", "num"), ("Trend", "n", "num"), ("Note", "s", "why")], inv_rows,
            "Nothing recorded yet. Log in with MyFA enabled, visit a banker once, then /reload."),
         f"Everything you own on this Auction House across {result['n_chars']} character{'s' if result['n_chars'] != 1 else ''} "
         f"(bags, bank and mailbox), worth {money(inv_value)} at its best use. "
         f"<em>Crafted</em> is what each unit is worth turned into your best recipe that uses it, buying any other mats it needs"
         f"{', adding ' + money(inv_gain) + ' over selling as is' if inv_gain else ''}. "
         + ("" if result["bank_seen"] else "<strong>Bank not seen yet: open your bank once on each character.</strong>")),
        ("crafts", "Crafts", len(result["crafts"]), table("crafts", [
            ("Recipe", "s", ""), ("Profession", "s", ""), ("Mat cost", "n", "num"), ("Sells for", "n", "num"),
            ("Profit", "n", "num"), ("Margin", "n", "num"), ("Make from stock", "n", "num"),
            ("Gain vs selling mats", "n", "num"), ("Trend", "n", "num"), ("Listed", "n", "num"), ("Mats", "s", "why")],
            craft_rows,
            "No recipes recorded yet. Open each profession window once in game so MyFA can read what you know, then /reload."),
         f"Every recipe your characters know. Professions recorded: {esc(profs)}. Open any other profession window once to add it. "
         f"<em>Make from stock</em> uses only what's in your bags and bank."),
        ("gathering", "Gathering", len(result["gathering"]), table("gathering", [
            ("Item", "s", ""), ("Type", "s", ""), ("Market", "n", "num"), ("Lowest now", "n", "num"),
            ("Per stack", "n", "num"), ("Listed", "n", "num"), ("7-day", "n", "num"), ("Trend", "n", "num"),
            ("You own", "n", "num")], gather_rows,
            "No herbs, ore, leather or cloth in this scan yet."),
         "Raw materials from Herbalism, Mining, Skinning, cloth drops and cooking, ranked by market value. "
         "Pair it with your own gathering rate to pick a farm."),
        ("trends", "Trends", len(result["trends"]), chart_html + table("trends", [
            ("Item", "s", ""), ("Lowest now", "n", "num"), ("Market", "n", "num"), ("7-day", "n", "num"),
            ("Trend", "n", "num"), ("Days", "n", "num"), ("Listed", "n", "num"), ("You own", "n", "num")],
            trend_rows, "Trends need scans on at least 2 days."),
         "Price history from every scan you've made. Click any item name, here or in another tab, to chart it. "
         "Trend is the average daily change across the whole history."),
        ("activity", "Activity", len(result["ledger"]), table("activity", [
            ("When", "n", ""), ("Item", "s", ""), ("Qty", "n", "num"), ("Each", "n", "num"), ("Total", "n", "num")],
            ledger_rows, "No purchases made through the MyFA panel yet."),
         f"Purchases made with the Buy button. Spent in the last 7 days: {money(result['spent_7d'])}."),
    ]

    tabs_html = "".join(
        f'<button type="button" role="tab" id="tab-{pid}" aria-controls="panel-{pid}" '
        f'aria-selected="{"true" if n == 0 else "false"}" tabindex="{0 if n == 0 else -1}">'
        f'{esc(label)}{f" <span class=count>{count}</span>" if count is not None else ""}</button>'
        for n, (pid, label, count, _, _) in enumerate(panels))
    panels_html = "".join(
        f'<section role="tabpanel" id="panel-{pid}" aria-labelledby="tab-{pid}" {"" if n == 0 else "hidden"}>'
        f'<div class="panelhead"><p class="desc">{desc}</p>'
        f'{"" if pid in ("claude", "analysis") else f"<label class=filter><span class=sr>Filter {esc(label)}</span><input type=search placeholder=Filter… data-filter=panel-{pid}></label>"}'
        f'</div>{body}</section>'
        for n, (pid, label, count, body, desc) in enumerate(panels))

    facts = [
        ("Scan", ago(result["scan_ts"], now)),
        ("Auctions", f'{result["auctions"]:,}'),
        ("Items", f'{result["item_count"]:,}'),
        ("History", f'{result["history_days"]} days'),
        ("Owned value", money(inv_value) if inv_value else "n/a"),
        ("Gold" if result["n_chars"] <= 1 else f"Gold, {result['n_chars']} chars", money(result["money"]) if result["money"] else "n/a"),
    ]
    facts_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)

    summary = []
    if total_flip:
        summary.append(f"{money(total_flip)} available from {len(result['flips']) + len(result['vendor'])} buy targets")
    best_craft = next((r for r in result["crafts"] if r["profit"] and r["profit"] > 0), None)
    if best_craft:
        summary.append(f"best craft {esc(best_craft['name'])} at {money(best_craft['profit'], True)} each")
    rising = [r for r in result["trends"] if r["slope"] and r["slope"] > 0.02 and r["owned"]]
    if rising:
        summary.append(f"{len(rising)} item{'s' if len(rising) > 1 else ''} you own {'are' if len(rising) > 1 else 'is'} rising")
    summary_html = " · ".join(summary) if summary else "No opportunities in this scan yet."

    import json
    chart_json = json.dumps({"items": result["chart"], "focus": result["chart_focus"]}, separators=(",", ":"))
    chart_json = chart_json.replace("</", "<\\/")
    index_json = json.dumps(result["index"] or {}, separators=(",", ":")).replace("</", "<\\/")

    return TEMPLATE.format(
        realm=esc(realm or result["realm"]), faction=esc(faction), facts=facts_html, summary=summary_html,
        tabs=tabs_html, panels=panels_html, generated=time.strftime("%d %b %Y, %H:%M", time.localtime(now)),
        config=esc(config_path), cut=cut_pct, chart_json=chart_json, chart_js=CHART_JS, index_json=index_json, index_js=INDEX_JS,
    )


CHART_HTML = """
<div class="chartcard" id="chart">
  <div class="chartbar">
    <div class="charttitle">
      <h2 id="chart-name">Price history</h2>
      <ul class="legend" aria-label="Series">
        <li><span class="sw sw-mkt"></span>Market</li>
        <li><span class="sw sw-low"></span>Lowest listing</li>
      </ul>
    </div>
    <div class="chartctl">
      <label><span class="sr">Item to chart</span>
        <input id="chart-pick" list="chart-items" placeholder="Chart an item…" autocomplete="off"></label>
      <datalist id="chart-items"></datalist>
      <div class="seg" role="group" aria-label="Range">
        <button type="button" data-range="14">14d</button>
        <button type="button" data-range="30" aria-pressed="true">30d</button>
        <button type="button" data-range="60">60d</button>
      </div>
    </div>
  </div>
  <div class="plot" id="plot-price" aria-label="Price over time"></div>
  <p class="subhead">Listed quantity</p>
  <div class="plot short" id="plot-qty" aria-label="Quantity listed over time"></div>
  <div class="tip" id="chart-tip" hidden></div>
</div>
"""


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MyFA Desk · {realm} {faction}</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #0b0d0f; --panel: #12151a; --raise: #171b21; --line: #242a31; --line-soft: #1b2026;
  --text: #ebe6da; --muted: #a29d91; --faint: #8f8a7e;
  --gold: #e3bd62; --silver: #c3c6cc; --copper: #d08a55;
  --pos: #72d38e; --neg: #f08c79; --warn: #e9c46a;
  --q0: #9d9d9d; --q1: #ebe6da; --q2: #52e06c; --q3: #4ea8ff; --q4: #c387ff; --q5: #ff9d42;
  --mono: ui-monospace, "Cascadia Mono", "SF Mono", Consolas, "Liberation Mono", monospace;
  --sans: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
}}
* {{ box-sizing: border-box; }}
html {{ background: var(--bg); }}
body {{ margin: 0; color: var(--text); font: 14px/1.45 var(--sans); -webkit-font-smoothing: antialiased; }}
::selection {{ background: rgba(227, 189, 98, .32); color: #fff; }}
* {{ scrollbar-color: #2c333b var(--bg); scrollbar-width: thin; }}
:focus-visible {{ outline: 2px solid var(--gold); outline-offset: 2px; border-radius: 3px; }}
.wrap {{ max-width: 1480px; margin: 0 auto; padding: 28px 28px 48px; }}

header {{ display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 20px 40px;
  padding-bottom: 20px; border-bottom: 1px solid var(--line); }}
h1 {{ margin: 0; font-size: 22px; font-weight: 650; letter-spacing: -0.01em; }}
h1 span {{ color: var(--gold); }}
.where {{ margin: 4px 0 0; color: var(--muted); }}
dl {{ display: flex; flex-wrap: wrap; gap: 6px 28px; margin: 0; }}
dl div {{ display: flex; flex-direction: column; }}
dt {{ color: var(--faint); font-size: 12px; }}
dd {{ margin: 0; font: 600 15px/1.3 var(--sans); font-variant-numeric: tabular-nums; }}

.summary {{ display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px 24px; margin: 18px 0 22px;
  color: var(--muted); }}
.summary strong {{ color: var(--text); font-weight: 500; }}
.next {{ color: var(--faint); }}
.next kbd {{ font: 12px var(--mono); color: var(--text); background: var(--raise); border: 1px solid var(--line);
  border-radius: 4px; padding: 1px 6px; }}

[role=tablist] {{ display: flex; flex-wrap: wrap; gap: 2px; border-bottom: 1px solid var(--line); }}
[role=tab] {{ appearance: none; background: none; border: 0; color: var(--muted); font: 500 14px var(--sans);
  padding: 10px 14px 11px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
  transition: color .15s ease-out, border-color .15s ease-out; }}
[role=tab]:hover {{ color: var(--text); }}
[role=tab][aria-selected=true] {{ color: var(--text); border-bottom-color: var(--gold); }}
.count {{ font: 12px var(--mono); color: var(--faint); margin-left: 4px; }}
[role=tab][aria-selected=true] .count {{ color: var(--gold); }}

.panelhead {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px 24px;
  margin: 18px 0 12px; }}
.desc {{ margin: 0; color: var(--muted); max-width: 80ch; }}
.filter input {{ width: 220px; background: var(--panel); border: 1px solid var(--line); color: var(--text);
  border-radius: 6px; padding: 7px 10px; font: 13px var(--sans); }}
.filter input::placeholder {{ color: var(--faint); }}
.filter input:focus {{ border-color: var(--gold); outline: none; }}
.sr {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }}

.tablewrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }}
table {{ width: 100%; border-collapse: collapse; }}
thead th {{ position: sticky; top: 0; background: var(--raise); text-align: left; padding: 0;
  border-bottom: 1px solid var(--line); white-space: nowrap; }}
thead th button {{ all: unset; display: block; width: 100%; box-sizing: border-box; padding: 9px 12px;
  color: var(--faint); font: 600 12px var(--sans); cursor: pointer; }}
thead th button:hover {{ color: var(--text); }}
thead th button:focus-visible {{ outline: 2px solid var(--gold); outline-offset: -2px; }}
thead th[aria-sort] button {{ color: var(--gold); }}
thead th[aria-sort=ascending] button::after {{ content: " \\2191"; }}
thead th[aria-sort=descending] button::after {{ content: " \\2193"; }}
th.num, td.num {{ text-align: right; }}
th.num button {{ text-align: right; }}
td {{ padding: 8px 12px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }}
tbody tr:last-child td {{ border-bottom: 0; }}
tbody tr:hover td {{ background: rgba(255, 255, 255, .025); }}
td.num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; white-space: nowrap; }}
td.why {{ color: var(--muted); min-width: 280px; max-width: 56ch; font-size: 13px; }}
td.pos {{ color: var(--pos); }} td.neg {{ color: var(--neg); }} td.strong {{ color: var(--text); font-weight: 600; }}
.m i {{ font-style: normal; font-size: .8em; margin-left: 1px; }}
.m i.g {{ color: var(--gold); }} .m i.s {{ color: var(--silver); }} .m i.c {{ color: var(--copper); }}
td.pos .m i, td.neg .m i {{ color: inherit; opacity: .75; }}
.na {{ color: var(--faint); }}
.warn {{ color: var(--warn); }}
.item {{ font-weight: 500; white-space: nowrap; }}
.q0 {{ color: var(--q0); }} .q1 {{ color: var(--q1); }} .q2 {{ color: var(--q2); }} .q3 {{ color: var(--q3); }}
.q4 {{ color: var(--q4); }} .q5 {{ color: var(--q5); }}
.risk-none {{ color: var(--muted); }} .risk-low {{ color: var(--pos); }} .risk-med {{ color: var(--warn); }} .risk-high {{ color: var(--neg); }}
.act-ah {{ color: var(--gold); }} .act-v {{ color: var(--muted); }}
code {{ font: 12.5px var(--mono); color: var(--text); }}
.empty {{ border: 1px dashed var(--line); border-radius: 8px; padding: 28px; color: var(--muted); }}
.empty p {{ margin: 0; max-width: 70ch; }}
.advice {{ border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 20px 24px;
  max-width: 82ch; line-height: 1.6; white-space: pre-wrap; }}
tr.hidden {{ display: none; }}
.itemlink {{ all: unset; cursor: pointer; font-weight: 500; white-space: nowrap; border-radius: 3px;
  text-decoration: underline; text-decoration-color: rgba(235, 230, 218, .18); text-underline-offset: 3px; }}
.itemlink:hover {{ text-decoration-color: currentColor; }}
.itemlink:focus-visible {{ outline: 2px solid var(--gold); outline-offset: 2px; }}
.sub {{ color: var(--muted); font-size: 12.5px; }}
.act-c {{ color: var(--pos); }} .act-h {{ color: #8fb8f0; }}
em {{ font-style: normal; color: var(--text); }}
.desc strong {{ color: var(--warn); font-weight: 500; }}
span.pos {{ color: var(--pos); }} span.neg {{ color: var(--neg); }}

.block {{ margin: 8px 0 36px; }}
.block.ready {{ border: 1px solid rgba(114, 211, 142, .35); background: rgba(114, 211, 142, .05); border-radius: 8px;
  padding: 16px 18px 10px; }}
.readylist {{ list-style: none; margin: 0; padding: 0; max-width: 760px; }}
.readylist li {{ display: flex; align-items: baseline; gap: 10px; padding: 6px 0; border-top: 1px solid var(--line-soft); }}
.readylist li .num {{ margin-left: auto; font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.blockhead {{ margin-bottom: 14px; }}
.block h2 {{ margin: 0 0 6px; font-size: 17px; font-weight: 600; letter-spacing: -0.005em; }}
.block h3 {{ margin: 0 0 8px; font-size: 13px; font-weight: 600; color: var(--muted); }}
.lede {{ margin: 0; color: var(--muted); max-width: 82ch; }}
.lede strong {{ color: var(--text); font-weight: 600; }}
.fine {{ margin: 10px 0 0; color: var(--faint); font-size: 12.5px; max-width: 90ch; }}
.watch {{ margin: 10px 0 0; color: var(--muted); font-size: 13px; max-width: 110ch; }}
.watch summary {{ cursor: pointer; color: var(--faint); width: fit-content; border-radius: 3px; }}
.watch summary:hover {{ color: var(--text); }}
.watch p {{ margin: 6px 0 0; }}
td.nowrap {{ white-space: nowrap; }}
.phases {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0; list-style: none; padding: 0;
  margin: 0 0 16px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
.phases li {{ padding: 10px 14px; border-left: 1px solid var(--line); display: flex; flex-direction: column; gap: 2px; }}
.phases li:first-child {{ border-left: 0; }}
.phases b {{ font-weight: 600; color: var(--muted); font-size: 13px; }}
.phases span {{ color: var(--faint); font-size: 12px; }}
.phases li.on {{ background: rgba(227, 189, 98, .08); box-shadow: inset 0 -2px 0 var(--gold); }}
.phases li.on b {{ color: var(--text); }}
.movers {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px 32px; margin-top: 16px; }}
.movers ul {{ list-style: none; margin: 0; padding: 0; }}
.movers li {{ display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--line-soft); }}
.movers .num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.weekday {{ list-style: none; margin: 14px 0 0; padding: 0; max-width: 560px; }}
.weekday li {{ display: grid; grid-template-columns: 44px 1fr 70px; align-items: center; gap: 12px; padding: 4px 0; }}
.weekday .d {{ color: var(--muted); }}
.weekday .num {{ text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.weekday .bar {{ position: relative; height: 12px; }}
.weekday .bar::before {{ content: ""; position: absolute; left: 50%; top: -2px; bottom: -2px; width: 1px; background: var(--line); }}
.weekday i {{ position: absolute; top: 0; height: 12px; width: var(--w); border-radius: 4px; background: #5b6570; }}
.weekday i.up {{ left: 50%; border-top-left-radius: 0; border-bottom-left-radius: 0; }}
.weekday i.down {{ right: 50%; border-top-right-radius: 0; border-bottom-right-radius: 0; }}
.playbook {{ margin: 0; padding-left: 22px; max-width: 86ch; display: grid; gap: 10px; color: var(--muted); }}
.playbook b {{ color: var(--text); font-weight: 600; }}
.playbook li::marker {{ color: var(--gold); font-variant-numeric: tabular-nums; }}
@media (max-width: 720px) {{ .phases {{ grid-template-columns: 1fr; }} .phases li {{ border-left: 0; border-top: 1px solid var(--line); }}
  .phases li:first-child {{ border-top: 0; }} }}
.chartcard {{ position: relative; border: 1px solid var(--line); border-radius: 8px; background: var(--panel);
  padding: 16px 18px 12px; margin-bottom: 16px; }}
.chartbar {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 12px 24px;
  margin-bottom: 8px; }}
.charttitle h2 {{ margin: 0 0 6px; font-size: 16px; font-weight: 600; }}
.legend {{ display: flex; gap: 16px; list-style: none; margin: 0; padding: 0; color: var(--muted); font-size: 12.5px; }}
.legend li {{ display: flex; align-items: center; gap: 6px; }}
.sw {{ width: 14px; height: 2px; border-radius: 1px; display: inline-block; }}
.sw-mkt {{ background: #b08a2c; }} .sw-low {{ background: #4d8ad0; }}
.chartctl {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
.chartctl input {{ width: 240px; background: var(--bg); border: 1px solid var(--line); color: var(--text);
  border-radius: 6px; padding: 7px 10px; font: 13px var(--sans); }}
.chartctl input:focus {{ border-color: var(--gold); outline: none; }}
.seg {{ display: inline-flex; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }}
.seg button {{ appearance: none; background: none; border: 0; color: var(--muted); padding: 6px 10px;
  font: 500 12.5px var(--sans); cursor: pointer; }}
.seg button + button {{ border-left: 1px solid var(--line); }}
.seg button[aria-pressed=true] {{ background: var(--raise); color: var(--text); }}
.plot {{ width: 100%; height: 260px; outline: none; }}
.plot.short {{ height: 96px; }}
.plot:focus-visible {{ box-shadow: 0 0 0 2px var(--gold); border-radius: 4px; }}
.plot svg {{ display: block; overflow: visible; }}
.plot text {{ fill: var(--muted); font: 11.5px var(--sans); font-variant-numeric: tabular-nums; }}
.plot text.end {{ fill: var(--text); font-weight: 500; }}
.subhead {{ margin: 6px 0 0; color: var(--faint); font-size: 12px; }}
.tip {{ position: absolute; pointer-events: none; background: var(--raise); border: 1px solid var(--line);
  border-radius: 6px; padding: 8px 10px; font-size: 12.5px; min-width: 150px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, .45); z-index: 2; }}
.tip b {{ display: block; font-weight: 600; margin-bottom: 4px; }}
.tip div {{ display: flex; justify-content: space-between; gap: 16px; color: var(--muted); }}
.tip span {{ color: var(--text); font-variant-numeric: tabular-nums; }}
.tip i {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
footer {{ margin-top: 28px; color: var(--faint); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 6px 24px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
@media (max-width: 720px) {{ .wrap {{ padding: 18px 14px 36px; }} .filter input {{ width: 100%; }} }}
</style>
</head>
<body>
<!--MYFA-CONTROL-->
<div class="wrap">
<header>
  <div>
    <h1>MyFA <span>Desk</span></h1>
    <p class="where">{realm} · {faction} auction house</p>
  </div>
  <dl>{facts}</dl>
</header>
<div class="summary">
  <p><strong>{summary}</strong></p>
  <p class="next">Targets written. Type <kbd>/reload</kbd> in game to load them.</p>
</div>
<div role="tablist" aria-label="Results">{tabs}</div>
{panels}
<footer>
  <span>Generated {generated}</span>
  <span>AH cut assumed {cut}: confirm it from a sale mail and set <code>ah_cut</code></span>
  <span>Settings: {config}</span>
</footer>
</div>
<script>
(() => {{
  const tabs = [...document.querySelectorAll('[role=tab]')];
  const select = (tab) => {{
    tabs.forEach(t => {{
      const on = t === tab;
      t.setAttribute('aria-selected', on);
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    }});
    try {{ localStorage.setItem('myfa-tab', tab.id); }} catch (e) {{}}
  }};
  tabs.forEach((t, i) => {{
    t.addEventListener('click', () => select(t));
    t.addEventListener('keydown', (e) => {{
      const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!d) return;
      const next = tabs[(i + d + tabs.length) % tabs.length];
      select(next); next.focus(); e.preventDefault();
    }});
  }});
  try {{ const saved = document.getElementById(localStorage.getItem('myfa-tab')); if (saved) select(saved); }} catch (e) {{}}

  document.querySelectorAll('table').forEach(table => {{
    const ths = [...table.querySelectorAll('th')];
    ths.forEach((th, col) => th.querySelector('button').addEventListener('click', () => {{
      const asc = th.getAttribute('aria-sort') === 'descending';
      ths.forEach(h => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
      const body = table.tBodies[0];
      const rows = [...body.rows];
      const key = r => {{
        const c = r.cells[col]; const v = c.dataset.v ?? c.textContent;
        const n = parseFloat(v); return isNaN(n) ? v.toLowerCase() : n;
      }};
      rows.sort((a, b) => {{
        const x = key(a), y = key(b);
        const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
        return asc ? r : -r;
      }});
      rows.forEach(r => body.appendChild(r));
    }}));
  }});

  document.querySelectorAll('[data-filter]').forEach(input => input.addEventListener('input', () => {{
    const q = input.value.trim().toLowerCase();
    document.querySelectorAll('#' + input.dataset.filter + ' tbody tr').forEach(tr => {{
      tr.classList.toggle('hidden', q && !tr.textContent.toLowerCase().includes(q));
    }});
  }}));
}})();
</script>
<script type="application/json" id="chart-data">{chart_json}</script>
<script type="application/json" id="index-data">{index_json}</script>
<script>{index_js}</script>
<script>{chart_js}</script>
</body>
</html>
"""


CHART_JS = r"""
(() => {
  const el = document.getElementById('chart-data');
  const DATA = el ? JSON.parse(el.textContent) : { items: {} };
  const ids = Object.keys(DATA.items);
  const plotP = document.getElementById('plot-price');
  if (!plotP || !ids.length) { bindLinks(false); return; }
  const plotQ = document.getElementById('plot-qty');
  const tip = document.getElementById('chart-tip');
  const card = document.getElementById('chart');
  const C = { mkt: '#b08a2c', low: '#4d8ad0', qty: '#5b6570', grid: '#242a31', axis: '#2e353d', bg: '#12151a' };
  const NS = 'http://www.w3.org/2000/svg';
  let current = String(DATA.focus ?? ids[0]);
  let range = 30;
  let hoverIdx = null;

  const money = (c) => {
    if (c == null) return 'n/a';
    c = Math.round(c);
    const g = Math.floor(c / 10000), s = Math.floor((c % 10000) / 100), cc = c % 100;
    if (g) return g.toLocaleString() + 'g ' + String(s).padStart(2, '0') + 's';
    if (s) return s + 's ' + String(cc).padStart(2, '0') + 'c';
    return cc + 'c';
  };
  const date = (d) => new Date(d * 86400000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const mk = (tag, attrs, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  };
  const niceTicks = (lo, hi, count) => {
    const span = hi - lo || hi || 1;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(st => st >= raw) || raw;
    const start = Math.floor(lo / step) * step;
    const ticks = [];
    for (let v = start; v <= hi + step * 0.5; v += step) ticks.push(v);
    return ticks;
  };

  // picker
  const list = document.getElementById('chart-items');
  const byName = {};
  ids.map(i => [i, DATA.items[i].n]).sort((a, b) => a[1].localeCompare(b[1])).forEach(([i, n]) => {
    byName[n.toLowerCase()] = i;
    const o = document.createElement('option'); o.value = n; list.appendChild(o);
  });
  const pick = document.getElementById('chart-pick');
  pick.addEventListener('change', () => {
    const i = byName[pick.value.trim().toLowerCase()];
    if (i) { current = i; hoverIdx = null; render(); }
  });
  document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', x === b));
    range = +b.dataset.range; hoverIdx = null; render();
  }));

  let geom = null;

  function render() {
    const item = DATA.items[current];
    if (!item) return;
    document.getElementById('chart-name').textContent = item.n;
    pick.value = '';
    const all = item.p;
    const lastDay = all[all.length - 1][0];
    const pts = all.filter(p => p[0] > lastDay - range);
    const W = Math.max(320, plotP.clientWidth);
    const M = { l: 64, r: W < 560 ? 16 : 112, t: 12, b: 26 };
    const H = plotP.clientHeight || 260, HQ = plotQ.clientHeight || 96;
    const d0 = pts[0][0], d1 = pts[pts.length - 1][0];
    const x = (d) => d1 === d0 ? (M.l + (W - M.r)) / 2 : M.l + (d - d0) / (d1 - d0) * (W - M.l - M.r);
    const vals = pts.flatMap(p => [p[1], p[2]]).filter(v => v != null);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.12 || hi * 0.1 || 1;
    lo = Math.max(0, lo - pad); hi = hi + pad;
    const ticks = niceTicks(lo, hi, 4);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const y = (v) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);

    plotP.innerHTML = '';
    const svg = mk('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img',
      'aria-label': `${item.n} market and lowest price, ${pts.length} days` }, plotP);
    ticks.forEach(t => {
      mk('line', { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t), stroke: C.grid, 'stroke-width': 1 }, svg);
      const tx = mk('text', { x: M.l - 10, y: y(t) + 4, 'text-anchor': 'end' }, svg); tx.textContent = money(t);
    });
    const nLab = Math.min(pts.length, W < 560 ? 3 : 6);
    const stepL = Math.max(1, Math.ceil((pts.length - 1) / Math.max(1, nLab - 1)));
    const labIdx = [];
    for (let k = 0; k < pts.length; k += stepL) labIdx.push(k);
    const lastI = pts.length - 1;
    if (labIdx[labIdx.length - 1] !== lastI) {
      if (lastI - labIdx[labIdx.length - 1] <= stepL / 2 && labIdx.length > 1) labIdx.pop();
      labIdx.push(lastI);
    }
    labIdx.forEach(k => {
      const p = pts[k];
      const tx = mk('text', { x: x(p[0]), y: H - 6, 'text-anchor': 'middle' }, svg); tx.textContent = date(p[0]);
    });
    const line = (idx, color) => {
      let d = '', pen = false;
      pts.forEach(p => {
        if (p[idx] == null) { pen = false; return; }
        d += (pen ? 'L' : 'M') + x(p[0]).toFixed(1) + ',' + y(p[idx]).toFixed(1); pen = true;
      });
      mk('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
    };
    line(1, C.low); line(2, C.mkt);
    // end markers + direct labels
    const ends = [];
    [[2, C.mkt, 'Market'], [1, C.low, 'Lowest']].forEach(([idx, color, label]) => {
      const last = [...pts].reverse().find(p => p[idx] != null);
      if (!last) return;
      mk('circle', { cx: x(last[0]), cy: y(last[idx]), r: 4, fill: color, stroke: C.bg, 'stroke-width': 2 }, svg);
      ends.push({ y: y(last[idx]), text: `${label} ${money(last[idx])}`, x: x(last[0]) });
    });
    if (M.r > 40) {
      ends.sort((a, b) => a.y - b.y);
      if (ends.length === 2 && ends[1].y - ends[0].y < 16) { const mid = (ends[0].y + ends[1].y) / 2; ends[0].y = mid - 8; ends[1].y = mid + 8; }
      ends.forEach(e => { const t = mk('text', { x: e.x + 10, y: e.y + 4, class: 'end' }, svg); t.textContent = e.text; });
    }
    const cross = mk('g', { visibility: 'hidden' }, svg);
    const cl = mk('line', { y1: M.t, y2: H - M.b, stroke: '#5b6570', 'stroke-width': 1 }, cross);
    const dm = mk('circle', { r: 4, fill: C.mkt, stroke: C.bg, 'stroke-width': 2 }, cross);
    const dl = mk('circle', { r: 4, fill: C.low, stroke: C.bg, 'stroke-width': 2 }, cross);

    // quantity bars (own chart, own axis)
    plotQ.innerHTML = '';
    const sq = mk('svg', { width: W, height: HQ, viewBox: `0 0 ${W} ${HQ}`, role: 'img', 'aria-label': `${item.n} quantity listed` }, plotQ);
    const qs = pts.map(p => p[3] || 0);
    const qmax = Math.max(1, ...qs);
    const qy = (v) => 4 + (1 - v / qmax) * (HQ - 22);
    const step = pts.length > 1 ? (x(d1) - x(d0)) / (pts.length - 1) : 40;
    const bw = Math.max(3, Math.min(18, step * 0.6));
    mk('line', { x1: M.l, x2: W - M.r, y1: qy(0), y2: qy(0), stroke: C.axis, 'stroke-width': 1 }, sq);
    const tq = mk('text', { x: M.l - 10, y: qy(qmax) + 8, 'text-anchor': 'end' }, sq); tq.textContent = qmax.toLocaleString();
    const tz = mk('text', { x: M.l - 10, y: qy(0) + 4, 'text-anchor': 'end' }, sq); tz.textContent = '0';
    const bars = pts.map((p, k) => {
      const v = qs[k]; if (!v) return null;
      const bx = x(p[0]) - bw / 2, top = qy(v), base = qy(0), r = Math.min(4, bw / 2, base - top);
      const d = `M${bx},${base}V${top + r}Q${bx},${top} ${bx + r},${top}H${bx + bw - r}Q${bx + bw},${top} ${bx + bw},${top + r}V${base}Z`;
      return mk('path', { d, fill: C.qty }, sq);
    });

    geom = { pts, x, y, W, H, M, cross, cl, dm, dl, bars, svg, sq };
    if (hoverIdx != null) showHover(Math.min(hoverIdx, pts.length - 1));
  }

  function showHover(k) {
    if (!geom) return;
    const { pts, x, y, cross, cl, dm, dl, bars } = geom;
    hoverIdx = k;
    const p = pts[k];
    const cx = x(p[0]);
    cross.setAttribute('visibility', 'visible');
    cl.setAttribute('x1', cx); cl.setAttribute('x2', cx);
    if (p[2] != null) { dm.setAttribute('cx', cx); dm.setAttribute('cy', y(p[2])); dm.style.display = ''; } else dm.style.display = 'none';
    if (p[1] != null) { dl.setAttribute('cx', cx); dl.setAttribute('cy', y(p[1])); dl.style.display = ''; } else dl.style.display = 'none';
    bars.forEach((b, i) => b && b.setAttribute('fill', i === k ? '#7d8893' : C.qty));
    tip.innerHTML = `<b>${date(p[0])}</b>` +
      `<div><span><i style="background:${C.mkt}"></i>Market</span><span>${money(p[2])}</span></div>` +
      `<div><span><i style="background:${C.low}"></i>Lowest</span><span>${money(p[1])}</span></div>` +
      `<div>Listed<span>${p[3] != null ? p[3].toLocaleString() : 'n/a'}</span></div>`;
    tip.hidden = false;
    const cardBox = card.getBoundingClientRect(), plotBox = plotP.getBoundingClientRect();
    let left = plotBox.left - cardBox.left + cx + 14;
    if (left + tip.offsetWidth > card.clientWidth - 8) left = plotBox.left - cardBox.left + cx - tip.offsetWidth - 14;
    tip.style.left = left + 'px';
    tip.style.top = (plotBox.top - cardBox.top + 8) + 'px';
  }
  function hideHover() {
    hoverIdx = null; tip.hidden = true;
    if (geom) { geom.cross.setAttribute('visibility', 'hidden'); geom.bars.forEach(b => b && b.setAttribute('fill', C.qty)); }
  }
  function nearest(clientX, host) {
    const box = host.getBoundingClientRect();
    const mx = clientX - box.left;
    let best = 0, bd = Infinity;
    geom.pts.forEach((p, k) => { const d = Math.abs(geom.x(p[0]) - mx); if (d < bd) { bd = d; best = k; } });
    return best;
  }
  [plotP, plotQ].forEach(host => {
    host.tabIndex = 0;
    host.addEventListener('pointermove', e => geom && showHover(nearest(e.clientX, host)));
    host.addEventListener('pointerleave', hideHover);
    host.addEventListener('blur', hideHover);
    host.addEventListener('keydown', e => {
      if (!geom) return;
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const k = hoverIdx == null ? geom.pts.length - 1 : hoverIdx + (e.key === 'ArrowRight' ? 1 : -1);
        showHover(Math.max(0, Math.min(geom.pts.length - 1, k))); e.preventDefault();
      } else if (e.key === 'Escape') hideHover();
    });
  });
  new ResizeObserver(() => render()).observe(plotP);

  bindLinks(true);
  function bindLinks(enabled) {
    document.querySelectorAll('.itemlink').forEach(b => b.addEventListener('click', () => {
      if (!enabled || !DATA.items[b.dataset.item]) return;
      current = b.dataset.item; hoverIdx = null;
      const tab = document.getElementById('tab-trends');
      if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
      render();
      card.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    }));
  }
  document.getElementById('tab-trends')?.addEventListener('click', () => requestAnimationFrame(render));
  render();
})();
"""


INDEX_JS = r"""
(() => {
  const el = document.getElementById('index-data');
  const host = document.getElementById('plot-index');
  if (!el || !host) return;
  const D = JSON.parse(el.textContent);
  if (!D.series || !D.series.length) return;
  const COLORS = ['#b08a2c', '#4d8ad0', '#4a9c6a', '#a866c9'];   // fixed order, validated for dark mode
  const tip = document.getElementById('index-tip');
  const card = host.closest('.chartcard');
  const NS = 'http://www.w3.org/2000/svg';
  const mk = (t, a, p) => { const n = document.createElementNS(NS, t); for (const k in a) n.setAttribute(k, a[k]); if (p) p.appendChild(n); return n; };
  const date = (d) => new Date(d * 86400000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const legend = document.getElementById('index-legend');
  legend.innerHTML = D.series.map((s, i) => `<li><span class="sw" style="background:${COLORS[i]}"></span>${s.name}</li>`).join('');
  let geom = null;

  function render() {
    const W = Math.max(320, host.clientWidth), H = host.clientHeight || 260;
    const M = { l: 48, r: W < 560 ? 16 : 130, t: 12, b: 26 };
    const days = D.days;
    const x = (k) => days.length === 1 ? (M.l + W - M.r) / 2 : M.l + k / (days.length - 1) * (W - M.l - M.r);
    const all = D.series.flatMap(s => s.values).filter(v => v != null);
    let lo = Math.min(100, ...all), hi = Math.max(100, ...all);
    const pad = (hi - lo) * 0.12 || 5; lo -= pad; hi += pad;
    const y = (v) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);
    host.innerHTML = '';
    const svg = mk('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Price index by category' }, host);
    const step = Math.max(1, Math.round((hi - lo) / 4 / 5) * 5) || 5;
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      mk('line', { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t), stroke: t === 100 ? '#3a424b' : '#242a31', 'stroke-width': 1 }, svg);
      const tx = mk('text', { x: M.l - 8, y: y(t) + 4, 'text-anchor': 'end' }, svg); tx.textContent = t;
    }
    const n = Math.min(days.length, W < 560 ? 3 : 6);
    const st = Math.max(1, Math.ceil((days.length - 1) / Math.max(1, n - 1)));
    const idx = []; for (let k = 0; k < days.length; k += st) idx.push(k);
    if (idx[idx.length - 1] !== days.length - 1) { if (days.length - 1 - idx[idx.length - 1] <= st / 2 && idx.length > 1) idx.pop(); idx.push(days.length - 1); }
    idx.forEach(k => { const tx = mk('text', { x: x(k), y: H - 6, 'text-anchor': 'middle' }, svg); tx.textContent = date(days[k]); });
    const ends = [];
    D.series.forEach((s, i) => {
      let d = '', pen = false, last = null;
      s.values.forEach((v, k) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + x(k).toFixed(1) + ',' + y(v).toFixed(1); pen = true; last = k; });
      mk('path', { d, fill: 'none', stroke: COLORS[i], 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
      if (last != null) {
        mk('circle', { cx: x(last), cy: y(s.values[last]), r: 4, fill: COLORS[i], stroke: '#12151a', 'stroke-width': 2 }, svg);
        ends.push({ y: y(s.values[last]), x: x(last), text: `${s.name} ${s.values[last]}` });
      }
    });
    if (M.r > 40) {
      ends.sort((a, b) => a.y - b.y);
      for (let k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 15) ends[k].y = ends[k - 1].y + 15;
      ends.forEach(e => { const t = mk('text', { x: e.x + 10, y: e.y + 4, class: 'end' }, svg); t.textContent = e.text; });
    }
    const cross = mk('line', { y1: M.t, y2: H - M.b, stroke: '#5b6570', 'stroke-width': 1, visibility: 'hidden' }, svg);
    geom = { x, y, cross, days };
  }
  function show(k) {
    const { x, cross, days } = geom;
    cross.setAttribute('x1', x(k)); cross.setAttribute('x2', x(k)); cross.setAttribute('visibility', 'visible');
    tip.innerHTML = `<b>${date(days[k])}</b>` + D.series.map((s, i) =>
      `<div><span><i style="background:${COLORS[i]}"></i>${s.name}</span><span>${s.values[k] ?? 'n/a'}</span></div>`).join('');
    tip.hidden = false;
    const cb = card.getBoundingClientRect(), hb = host.getBoundingClientRect();
    let left = hb.left - cb.left + x(k) + 14;
    if (left + tip.offsetWidth > card.clientWidth - 8) left = hb.left - cb.left + x(k) - tip.offsetWidth - 14;
    tip.style.left = left + 'px'; tip.style.top = (hb.top - cb.top + 8) + 'px';
    geom.k = k;
  }
  function hide() { tip.hidden = true; if (geom) geom.cross.setAttribute('visibility', 'hidden'); }
  host.tabIndex = 0;
  host.addEventListener('pointermove', e => {
    if (!geom) return;
    const mx = e.clientX - host.getBoundingClientRect().left;
    let best = 0, bd = Infinity; geom.days.forEach((_, k) => { const d = Math.abs(geom.x(k) - mx); if (d < bd) { bd = d; best = k; } });
    show(best);
  });
  host.addEventListener('pointerleave', hide); host.addEventListener('blur', hide);
  host.addEventListener('keydown', e => {
    if (!geom) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      const k = geom.k == null ? geom.days.length - 1 : geom.k + (e.key === 'ArrowRight' ? 1 : -1);
      show(Math.max(0, Math.min(geom.days.length - 1, k))); e.preventDefault();
    } else if (e.key === 'Escape') hide();
  });
  new ResizeObserver(() => render()).observe(host);
  render();
})();
"""
