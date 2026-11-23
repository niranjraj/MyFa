"""Deals you copy from Booty Bay Broker's WoW Forever deals page and paste into MyFA Desk.

Booty Bay Broker's terms forbid automated scraping, so MyFA never fetches their site: you open a deals page,
select all, copy, and paste it into Desk. This module only parses that text. Each deal keeps the figures the
page shows (lowest buyout, usual price, units available, next listing, est. sold a day and its range, the
selling-speed label, supply surge) so Desk can run its own flip checks on them.
"""
import json
import re
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "bbb_deals.json"
MAX_AGE_HOURS = 6        # their prices refresh hourly; older pastes are ignored

_MONEY = re.compile(r"^\s*(?:(\d[\d,]*)g)?\s*(?:(\d+)s)?\s*(?:(\d+)c)?\s*$")
_MONEY_ANY = re.compile(r"(?:(\d[\d,]*)g\s*)?(?:(\d+)s\s*)?(?:(\d+)c)?")
_LABELS = ("Sells fast", "Sells steadily", "Sells slowly", "Rarely sells")
_STOP = ("Sorted by", "Vendor flips", "Previous page", "Next page", "Page ")


def money(text):
    """'329g 0s 0c' / '59s 10c' / '420g' -> copper, or None."""
    m = _MONEY.match(text or "")
    if not m or not any(m.groups()):
        return None
    g, s, c = (int((x or "0").replace(",", "")) for x in m.groups())
    return g * 10000 + s * 100 + c


def _num(text):
    try:
        return float(text.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _is_scanned(line):
    return line.startswith("scanned ") and line.endswith(" ago")


def _split(text):
    """Lines, with cells split on tabs, and 'price scanned N min ago' split in two."""
    out = []
    for raw in re.split(r"[\r\n\t]+", text or ""):
        raw = raw.strip()
        if not raw:
            continue
        m = re.match(r"^(.*?)\s*(scanned .+? ago)\s*(.*)$", raw)
        if m and m.group(1):
            out.append(m.group(1).strip())
            out.append(m.group(2))
            if m.group(3).strip():
                out.append(m.group(3).strip())
        else:
            out.append(raw)
    return out


_MONEY_TXT = r"((?:\d[\d,]*g\s*)?(?:\d+s\s*)?(?:\d+c)?)"


def parse(text):
    """Pasted page text -> {"market", "faction", "rows": [...]}. Tolerates tabs, blank lines and merged cells."""
    lines = _split(text)
    market = faction = None
    for i, l in enumerate(lines[:80]):
        m = re.match(r"^Deals on (.+?), (Alliance|Horde|Neutral|Blackwater)\b", l)
        if m:
            market, faction = m.group(1), m.group(2)
            break
        if l in ("Alliance", "Horde") and i > 0 and not faction:
            faction, market = l, lines[i - 1]
    # a deal: a name line, an optional "Supply surge" note, then a price line followed by "scanned ... ago"
    starts = []
    for i, l in enumerate(lines):
        if _is_scanned(l) and i >= 2 and money(lines[i - 1]) is not None:
            j = i - 2
            surge = False
            while j > 0 and (lines[j].startswith("More than twice") or lines[j] == "Supply surge"):
                surge = surge or lines[j] == "Supply surge"
                j -= 1
            starts.append((j, i - 1, surge))
    rows = []
    for n, (name_i, price_i, surge) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        block = lines[price_i:end]
        stop = next((k for k, b in enumerate(block) if any(b.startswith(s) for s in _STOP)), len(block))
        block = block[:stop]
        lowest = money(block[0])
        rest = block[2:]
        usual = money(rest[0]) if rest else None
        if usual is None or lowest is None:
            continue   # vendor-flip rows have no usual price
        joined = " ".join(rest)
        m = re.search(r"([\d.]+)%\s+(\d+)\b", joined)
        pct, avail = (_num(m.group(1)), int(m.group(2))) if m else (None, 1)
        m = re.search(r"next listing\s+" + _MONEY_TXT, joined)
        nxt = money(m.group(1)) if m and m.group(1).strip() else None
        m = re.search(r"estimated\s*([\d.,]+)\s*,?\s*\(([\d.,]+)\s*[–-]\s*([\d.,]+)\)", joined)
        sold, lo, hi = (_num(m.group(1)), _num(m.group(2)), _num(m.group(3))) if m else (None, None, None)
        label = next((lb for lb in _LABELS if lb in joined), None)
        m = re.match(r"scanned (\d+) (min|hour|hours|day|days) ago", block[1]) if len(block) > 1 else None
        scanned_min = None
        if m:
            scanned_min = int(m.group(1)) * {"min": 1, "hour": 60, "hours": 60, "day": 1440, "days": 1440}[m.group(2)]
        rows.append({
            "name": lines[name_i], "lowest": lowest, "usual": usual, "under": pct, "available": avail, "scanned_min": scanned_min,
            "next": nxt, "sold": sold, "lo": lo if lo is not None else sold, "hi": hi if hi is not None else sold,
            "label": label, "surge": surge,
        })
    return {"market": market, "faction": faction, "rows": rows}


def save(parsed, path=DATA):
    """Merge a pasted page into what's stored (several pages can be pasted one after another)."""
    old = load(path, max_age_hours=None) or {}
    now = int(time.time())
    same_market = old.get("market") == parsed["market"] and old.get("faction") == parsed["faction"]
    rows = {r["name"]: r for r in (old.get("rows") or [])} if same_market and now - old.get("t", 0) < MAX_AGE_HOURS * 3600 else {}
    for r in parsed["rows"]:
        r["t"] = now
        r["seen"] = now - 60 * (r.get("scanned_min") or 0)   # when their scan saw these prices
        rows[r["name"]] = r
    data = {"market": parsed["market"], "faction": parsed["faction"], "t": now, "rows": list(rows.values())}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def load(path=DATA, max_age_hours=MAX_AGE_HOURS):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if max_age_hours is not None:
        cutoff = time.time() - max_age_hours * 3600
        data["rows"] = [r for r in data.get("rows") or [] if r.get("t", 0) >= cutoff]
    return data


def clear(path=DATA):
    try:
        path.unlink()
    except OSError:
        pass
