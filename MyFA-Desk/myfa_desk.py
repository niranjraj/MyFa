#!/usr/bin/env python3
"""MyFA Desk: reads the MyFA addon's scan data, finds profit, and writes targets back into the addon.

Run it and leave it open while you play. Each time you /reload in game it picks up the new scan,
writes Interface/AddOns/MyFA/Data/Targets.lua, and refreshes report.html.
Standard library only (Python 3.9+).
"""
import argparse
import json
import os
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from analysis import History, analyse, fmt, targets_table  # noqa: E402
from lua_io import LuaParseError, parse_saved_variables, to_lua  # noqa: E402
from report import build  # noqa: E402
import updater  # noqa: E402

CONFIG_PATH = HERE / "config.json"
DATA_DIR = HERE / "data"
REPORT_PATH = HERE / "report.html"
BRIEF_PATH = HERE / "claude_brief.md"
ADVICE_PATH = HERE / "claude_advice.md"

DEFAULTS = {
    "wow_path": "",              # the _forever_ folder, e.g. C:\\Program Files (x86)\\World of Warcraft\\_forever_
    "account": "",               # folder name under WTF\\Account
    "realm": "",                 # blank = whichever ruleset/faction you scanned most recently
    "ah_cut": 0.05,              # Blizzard hasn't published Forever's cut. Check a sale mail and fix this.
    "min_profit": 5000,          # copper per flip target (5000 = 50s)
    "min_roi": 0.15,             # at least 15% return after the cut
    "min_vendor_profit": 100,    # copper (1s)
    "flip_threshold": 0.7,       # no longer used for flips (they relist where you'd be the cheapest seller); kept for old configs
    "max_supply_share": 0.35,    # never buy more than 35% of everything listed for an item
    "max_spend_fraction": 0.3,   # never spend more than 30% of your gold on one item
    "max_targets": 40,
    "min_listed": 10,            # fewer units listed than this = thin market: shown as a risky snipe, not a Buy target
    "include_snipes": False,     # True puts thin-market snipes in the in-game Buy list too
    "min_item_value": 100,       # in-game Sell list skips stacks worth less than this (copper; 100 = 1s)
    "history_days": 14,          # days of prices that set "market value"
    "chart_days": 60,            # days of history shown in Trends charts
    "hold_rising_slope": 0.04,   # suggest holding an item rising >= 4% a day instead of selling now
    "band_days": 30,             # days used for buy-under / sell-at price bands
    "min_band_spread": 0.2,      # only show bands with at least 20% profit between the low and high after the cut
    "raids_file": "",            # blank = raids.json next to this app
    "neutral_cut": 0.15,         # neutral Auction Houses (Gadgetzan, Booty Bay, Everlook) take 15%
    "neutral_deposit_mult": 5,   # ...and charge five times the deposit until MyFA learns yours
    "deposit_rate": 0.20,        # deposit as a share of vendor price until MyFA sees you post (8-hour classic rule)
    "default_sell_rate": 0.6,    # share of listings assumed to sell until MyFA has your own sale mails
    "neutral_max_age_days": 7,   # ignore neutral prices older than this
    "include_gear": False,       # gear has random suffixes that share one item ID, so prices mix
    "vendor_costs": {},          # {"3371": 4} item ID -> copper, for vendor mats MyFA hasn't seen yet
    "open_report": True,
    "claude_model": "claude-sonnet-5-5",
    "anthropic_api_key": "",     # optional: enables the researched Guide (or set ANTHROPIC_API_KEY)
    "guide_searches": 8,         # web searches per guide with the API option (each costs about 1 cent)
    "guide_source": "auto",      # "auto", "claude_code" (your Claude plan), "chat" (copy/paste, your plan) or "api"
    "claude_code_path": "",      # only if Claude Code is installed somewhere MyFA can't find
    "desktop_notifications": True,  # Windows notification when a flip becomes worth selling
    "auto_update": "ask",        # "ask", "always" or "never": check GitHub for a new MyFA release at start
    "github_token": "",          # only needed if the MyFa repo is made private
    "addon_updates": "auto",     # "auto", "desk" or "curseforge": who updates the in-game addon (auto = CurseForge if installed from there)
}


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            sys.exit(f"config.json has a syntax error on line {e.lineno}: {e.msg}. Fix it or delete the file.")
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- locating WoW

def _candidates():
    roots = []
    if os.name == "nt":
        for d in string.ascii_uppercase[2:12]:
            for sub in (r"Program Files (x86)\World of Warcraft", r"Program Files\World of Warcraft",
                        r"World of Warcraft", r"Games\World of Warcraft", r"Battle.net\World of Warcraft"):
                roots.append(Path(f"{d}:\\") / sub)
    else:
        roots += [Path("/Applications/World of Warcraft"), Path.home() / "Games/World of Warcraft"]
    return roots


def resolve_flavor(path: Path):
    """Accept the WoW root or the _forever_ folder itself."""
    if (path / "WTF").exists() or (path / "Interface").exists():
        return path
    for name in ("_forever_", "_classic_beta_"):
        if (path / name).exists():
            return path / name
    return None


def find_wow():
    for root in _candidates():
        if root.exists():
            flavor = resolve_flavor(root)
            if flavor:
                return flavor
    return None


def accounts(flavor: Path):
    base = flavor / "WTF" / "Account"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "SavedVariables").exists())


def setup(cfg, args):
    if args.wow:
        flavor = resolve_flavor(Path(args.wow))
        if not flavor:
            sys.exit(f"No WoW Forever folder found at {args.wow}. Point --wow at the _forever_ folder.")
        cfg["wow_path"] = str(flavor)
    if not cfg["wow_path"] or not Path(cfg["wow_path"]).exists():
        found = find_wow()
        if found:
            print(f"Found WoW Forever at {found}")
            cfg["wow_path"] = str(found)
        else:
            entered = input("Where is your WoW Forever folder? (the one named _forever_)\n> ").strip().strip('"')
            flavor = resolve_flavor(Path(entered)) if entered else None
            if not flavor:
                sys.exit("That folder doesn't contain WTF or Interface. In Battle.net: gear next to Play > Show in Explorer.")
            cfg["wow_path"] = str(flavor)
    flavor = Path(cfg["wow_path"])
    if args.account:
        cfg["account"] = args.account
    accs = accounts(flavor)
    if not cfg["account"] or cfg["account"] not in accs:
        if not accs:
            sys.exit("No WTF\\Account folder yet. Log into WoW Forever once with the addon installed, then rerun.")
        if len(accs) == 1:
            cfg["account"] = accs[0]
        else:
            print("Which account?")
            for n, a in enumerate(accs, 1):
                print(f"  {n}. {a}")
            pick = input("> ").strip()
            cfg["account"] = accs[int(pick) - 1] if pick.isdigit() and 0 < int(pick) <= len(accs) else accs[0]
    save_config(cfg)
    sv = flavor / "WTF" / "Account" / cfg["account"] / "SavedVariables" / "MyFA.lua"
    addon = flavor / "Interface" / "AddOns" / "MyFA"
    if not addon.exists():
        print(f"Warning: the MyFA addon isn't installed at {addon}. Copy the MyFA folder there.")
    return sv, addon / "Data" / "Targets.lua"


# ---------------------------------------------------------------- outputs

def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def companion_dir(path: Path):
    """Interface/AddOns/MyFA_Desk: a tiny data-only addon next to MyFA. Addon updates (including the CurseForge
    app, which replaces the whole MyFA folder) never touch it, so your targets survive them."""
    if path.parent.name == "Data" and path.parent.parent.name == "MyFA":
        return path.parent.parent.parent / "MyFA_Desk"
    return None


def write_targets(result, path: Path):
    body = ("-- Written by MyFA Desk " + time.strftime("%Y-%m-%d %H:%M") + ". Overwritten on every run.\n"
            "MyFA_Targets = " + to_lua(targets_table(result)) + "\n")
    _atomic_write(path, body)
    comp = companion_dir(path)
    if comp:
        iface = "16001"
        try:
            for line in (path.parent.parent / "MyFA.toc").read_text(encoding="utf-8").splitlines():
                if line.startswith("## Interface:"):
                    iface = line.split(":", 1)[1].strip()
        except OSError:
            pass
        toc = (f"## Interface: {iface}\n## Title: MyFA Desk data\n"
               "## Notes: Buy, sell and craft targets written by the MyFA Desk app. Keep it enabled together with MyFA.\n"
               f"## Author: MyFA\n## Version: {updater.local_version()}\n\nTargets.lua\n")
        toc_path = comp / "MyFA_Desk.toc"
        if not toc_path.exists() or toc_path.read_text(encoding="utf-8") != toc:
            _atomic_write(toc_path, toc)
        _atomic_write(comp / "Targets.lua", body)


def targets_signature(path: Path):
    """Changes if something other than Desk rewrote or removed the targets (an addon update, for example)."""
    out = []
    for f in (path, (companion_dir(path) or path.parent) / "Targets.lua"):
        try:
            st = f.stat()
            out.append((st.st_mtime, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def brief(result):
    """A compact markdown summary to hand to Claude (upload it in chat, or --ask-claude)."""
    c = result["cfg"]
    lines = [
        f"# MyFA scan: {result['realm']}",
        f"Scan {time.strftime('%Y-%m-%d %H:%M', time.localtime(result['scan_ts'] or 0))}, "
        f"{result['auctions']:,} auctions, {result['item_count']:,} items, {result['history_days']} days of history, "
        f"gold on hand {fmt(result['money'])} across {result['n_chars']} character(s). AH cut assumed {c['ah_cut'] * 100:g}%.",
    ]
    if result["positions"]:
        lines += ["", "## My flips (bought and still held)", "| Item | Qty | Paid | Lowest now | Status | P/L now | Where |",
                  "|---|---|---|---|---|---|---|"]
        lines += [f"| {r['name']} | {r['qty']} | {fmt(r['cost'])} | {fmt(r['now']) if r['now'] else 'not listed'} | "
                  f"{r['status']} | {fmt(r['pl']) if r['pl'] is not None else 'n/a'} | {r['where']} |" for r in result["positions"]]
    lines += ["", "## Flip targets", "| Item | Avg buy | Qty | Relist | Profit | Risk | Days |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['name']} | {fmt(r['avg'])} | {r['qty']} | {fmt(r['sell'])} | {fmt(r['profit'])} | {r['risk']} | {r['days']} |"
              for r in result["flips"][:20]] or ["| none | | | | | | |"]
    lines += ["", "## Vendor flips"] + [f"- {r['name']}: {r['qty']} @ {fmt(r['avg'])}, profit {fmt(r['profit'])}"
                                        for r in result["vendor"][:10]]
    lines += ["", "## Crafts", "| Recipe | Cost | Sells | Profit | Listed |", "|---|---|---|---|---|"]
    lines += [f"| {r['name']} | {fmt(r['cost'])} | {fmt(r['value'])} | "
              f"{fmt(r['profit']) if r['profit'] is not None else 'missing: ' + ', '.join(r['missing'])} | {r['listed']} |"
              for r in result["crafts"][:20]]
    lines += ["", "## What to do with items in bags and bank",
              "| Item | Qty | Where | Best use | Value | Gain vs next best | Note |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['qty']} | {r['loc']} | {r['action']}{' into ' + r['into'] if r['into'] else ''} | "
              f"{fmt(r['value'])} | {fmt(r['gain'])} | {r['note']} |" for r in result["inventory"][:30]]
    lines += ["", "## Craft from own stock"] + [
        f"- {r['name']} ({r['prof']}): can make {r['stock']}, gain vs selling the mats {fmt(r['stock_gain'])}"
        for r in result["crafts"] if r["stock"]][:15]
    lines += ["", "## Gathering values"] + [
        f"- {r['name']} ({r['type']}): market {fmt(r['market'])}, {r['listed']} listed"
        + (f", 7-day change {r['change7'] * 100:+.0f}%" if r["change7"] is not None else "")
        for r in result["gathering"][:15]]
    if result["raids"]:
        lines += ["", "## Raid prep"] + [f"- {r['name']}: {r['date']} ({r['days_left']} days)" for r in result["raids"]]
        lines += ["| Item | Role | Action | Now | Usual low / high | Own | Why |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {r['name']} | {r['role']} | {r['action']} | {fmt(r['now']) if r['now'] else 'not listed'} | "
                  f"{fmt(r['buy']) + ' / ' + fmt(r['sell']) if r['buy'] else 'n/a'} | {r['owned']} | {r['why']} |"
                  for r in result["raid_plan"] if r["action"] != "Watch"][:30]
    lines += ["", "## Flip bands (buy under / sell at)"] + [
        f"- {r['name']}: now {fmt(r['now'])}, buy under {fmt(r['buy'])}, sell at {fmt(r['sell'])}, "
        f"{r['spread'] * 100:.0f}% after cut, zone {r['zone']}, {r['listed']} listed" for r in result["bands"][:20]]
    lines += ["", "## Trends (biggest daily rise first)"] + [
        f"- {r['name']}: now {fmt(r['now'])}, market {fmt(r['market'])}, 7-day {r['change7'] * 100:+.0f}%"
        + (f", {r['slope'] * 100:+.1f}%/day over {r['days']} days" if r["slope"] is not None else "")
        for r in result["trends"][:15]]
    return "\n".join(lines) + "\n"


NOTIFIED_PATH = DATA_DIR / "notified.json"


def notify(title, message):
    """Windows tray notification; silently does nothing elsewhere or if PowerShell is unavailable."""
    if os.name != "nt":
        return
    def q(x):
        return x.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
        f"$n.BalloonTipTitle = '{q(title)}'; $n.BalloonTipText = '{q(message)}'; $n.Visible = $true; "
        "$n.ShowBalloonTip(10000); Start-Sleep -Seconds 11; $n.Dispose()"
    )
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass


def notify_ready(result, cfg):
    """Tell you once per price level when a flip becomes worth selling."""
    try:
        seen = json.loads(NOTIFIED_PATH.read_text(encoding="utf-8")) if NOTIFIED_PATH.exists() else {}
    except ValueError:
        seen = {}
    fresh, current = [], {}
    for r in result["positions"]:
        if r["status"] != "Sell now":
            continue
        key = f"{result['realm']}:{r['id']}"
        prev = seen.get(key)
        if prev is None or r["now"] >= prev * 1.1:
            fresh.append(r)
            current[key] = r["now"]
        else:
            current[key] = prev
    NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFIED_PATH.write_text(json.dumps(current), encoding="utf-8")
    for r in fresh:
        print(f"  SELL {r['name']} x{r['qty']}: lowest {fmt(r['now'])}, you paid {fmt(r['cost'])}. "
              f"+{fmt(r['pl'])} after the cut ({r['where']}).")
    if fresh and cfg.get("desktop_notifications", True):
        if len(fresh) == 1:
            r = fresh[0]
            notify("MyFA: time to sell", f"{r['name']} x{r['qty']} is up to {fmt(r['now'])}. "
                                         f"Sell for +{fmt(r['pl'])} ({r['where']}).")
        else:
            total = sum(r["pl"] or 0 for r in fresh)
            notify("MyFA: time to sell", f"{len(fresh)} flips are ready, +{fmt(total)} in total: "
                                         + ", ".join(r["name"] for r in fresh[:4]))


def ask_claude(text, cfg):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("Set ANTHROPIC_API_KEY to use --ask-claude (console.anthropic.com > API keys).")
        return None
    prompt = (
        "You are a World of Warcraft: Forever gold-making analyst. Forever uses the modern commodity auction house; "
        "the newest listing at a price sells first, so advise matching rather than undercutting. Based on this scan, "
        "give the player a short, concrete plan for this session: what to buy and the max price, what to craft, what "
        "to post or vendor, and what to avoid. Flag thin data or risky calls. Plain text, under 300 words.\n\n" + text)
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": cfg["claude_model"], "max_tokens": 1200,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    except urllib.error.HTTPError as e:
        print(f"Claude API error {e.code}: {e.read()[:300].decode(errors='replace')}")
    except urllib.error.URLError as e:
        print(f"Couldn't reach the Claude API: {e.reason}")
    return None


# ---------------------------------------------------------------- run loop

def process(sv_path: Path, targets_path: Path, cfg, history, args, first=False):
    try:
        text = sv_path.read_text(encoding="utf-8", errors="replace")
        sv = parse_saved_variables(text)
    except (OSError, LuaParseError) as e:
        print(f"Couldn't read {sv_path.name} yet ({e}). Waiting for the next /reload.")
        return False
    result = analyse(sv, history, cfg)
    if not result:
        print("No scan in the data yet. Open the Auction House, press Full scan, then /reload.")
        return False
    write_targets(result, targets_path)
    BRIEF_PATH.write_text(brief(result), encoding="utf-8")
    notify_ready(result, cfg)

    advice = None
    if args.ask_claude:
        print("Asking Claude for a session plan...")
        advice = ask_claude(BRIEF_PATH.read_text(encoding="utf-8"), cfg)
        if advice:
            ADVICE_PATH.write_text(advice, encoding="utf-8")
    if getattr(args, "guide", False):
        import guide as guide_mod
        how = guide_mod.provider(cfg)
        if how == "chat":
            prompt_path = HERE / "claude_guide_request.md"
            prompt_path.write_text(guide_mod.chat_prompt(result), encoding="utf-8")
            print(f"No Claude Code or API key found. Paste {prompt_path.name} into Claude chat; the app can save the answer.")
            out = {"error": "Used the Claude chat route instead."}
        else:
            print("Researching your guide with " + ("Claude Code (your Claude plan)" if how == "claude_code" else "the Claude API")
                  + " and web search... this takes a few minutes.")
            out = guide_mod.fetch(cfg, result)
        print(out["error"] if out.get("error") else f"Guide ready ({out.get('searches', 0)} web searches). See the Guide tab.")
    import html as _html
    REPORT_PATH.write_text(build(result, _html.escape(advice) if advice else None, str(CONFIG_PATH)), encoding="utf-8")

    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] {result['realm']}: {len(result['flips'])} flips, {len(result['vendor'])} vendor flips, "
          f"{sum(1 for r in result['crafts'] if r['profit'] and r['profit'] > 0)} profitable crafts, "
          f"{len(result['inventory'])} owned items on {result['n_chars']} character(s)"
          f"{'' if result['bank_seen'] else ' (bank not seen yet: visit a banker)'}, "
          f"{sum(1 for r in result['positions'] if r['status'] == 'Sell now')} flips ready to sell. "
          f"Targets ready. Type /reload in game.")
    if first and cfg.get("open_report") and not args.no_open:
        webbrowser.open(REPORT_PATH.as_uri())
    return result


def main():
    ap = argparse.ArgumentParser(description="MyFA Desk: auction house profit finder for WoW Forever.")
    ap.add_argument("--wow", help="path to your _forever_ folder (auto-detected if omitted)")
    ap.add_argument("--account", help="account folder name under WTF\\Account")
    ap.add_argument("--sv", help="read this SavedVariables file directly (skips WoW detection)")
    ap.add_argument("--targets", help="write Targets.lua here (with --sv)")
    ap.add_argument("--once", action="store_true", help="process once and exit instead of watching")
    ap.add_argument("--no-open", action="store_true", help="don't open the report in a browser")
    ap.add_argument("--ask-claude", action="store_true", help="ask Claude for a session plan (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--guide", action="store_true", help="research a gold/profession guide with Claude (needs an API key)")
    ap.add_argument("--update", action="store_true", help="check GitHub for a new MyFA version and install it")
    ap.add_argument("--no-update", action="store_true", help="skip the update check this time")
    ap.add_argument("--version", action="store_true", help="print the installed version")
    args = ap.parse_args()
    if args.version:
        print(f"MyFA {updater.local_version()}")
        return

    cfg = load_config()
    if args.sv:
        sv_path = Path(args.sv)
        targets_path = Path(args.targets) if args.targets else HERE / "Targets.lua"
        if not CONFIG_PATH.exists():
            save_config(cfg)
    else:
        sv_path, targets_path = setup(cfg, args)
    if not args.no_update:
        addon_dir = targets_path.parent.parent if not args.sv else (
            Path(cfg["wow_path"]) / "Interface" / "AddOns" / "MyFA" if cfg.get("wow_path") else None)
        mode = "always" if args.update else cfg.get("auto_update", "ask")
        via_cf = updater.addon_source(addon_dir, cfg.get("addon_updates", "auto")) == "curseforge"
        if updater.check_and_update(addon_dir, mode, cfg.get("github_token") or None, force=args.update, addon_via_cf=via_cf):
            print("Restarting MyFA Desk...\n")
            rest = [a for a in sys.argv[1:] if a != "--update"]
            sys.exit(subprocess.call([sys.executable, str(Path(__file__).resolve()), *rest]))

    history = History(DATA_DIR / "history.sqlite")
    print(f"MyFA Desk {updater.local_version()}")
    print(f"Reading  {sv_path}\nWriting  {targets_path}\nReport   {REPORT_PATH}")
    if not sv_path.exists():
        print("No MyFA data yet. In game: open the Auction House, press Full scan, then /reload.")

    last = None
    written = None
    first = True
    if args.once:
        process(sv_path, targets_path, cfg, history, args, first=True)
        return
    print("Watching for /reload. Leave this window open. Ctrl+C to stop.")
    try:
        while True:
            try:
                st = sv_path.stat()
                sig = (st.st_mtime, st.st_size)
            except OSError:
                sig = None
            if written is not None and targets_signature(targets_path) != written:
                last = None   # targets were replaced or removed (an addon update): write them again
            if sig and sig != last:
                time.sleep(1.0)  # let WoW finish writing
                try:
                    st2 = sv_path.stat()
                except OSError:
                    continue
                if (st2.st_mtime, st2.st_size) != sig:
                    continue
                cfg = load_config()
                if process(sv_path, targets_path, cfg, history, args, first=first):
                    first = False
                    written = targets_signature(targets_path)
                last = sig
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
