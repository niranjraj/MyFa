"""Researched gold guide: asks Claude (with web search) to look up Wowhead and current WoW Forever guides for
your characters' level, class and professions, using your own scan prices. Needs your Anthropic API key.
Standard library only."""
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

GUIDE_PATH = Path(__file__).resolve().parent / "data" / "guide.json"
API_URL = "https://api.anthropic.com/v1/messages"


def api_key(cfg):
    return (cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def load_cached():
    try:
        return json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _fmt(c):
    c = int(c or 0)
    g, s, cc = c // 10000, (c % 10000) // 100, c % 100
    return f"{g}g {s:02d}s" if g else (f"{s}s {cc:02d}c" if s else f"{cc}c")


def build_prompt(result):
    chars = []
    for p in result["profiles"]:
        profs = ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in p["profs"].items()) or "no professions recorded"
        chars.append(f"- {p['name']}: level {p['level'] or '?'} {p.get('race') or ''} {p['class'] or '?'}, "
                     f"in {p['zone'] or 'unknown zone'}, {_fmt(p['money'])} gold, professions: {profs}")
    faction = result["realm"].rpartition("-")[2]
    market = [f"- {g['name']} ({g['type']}): {_fmt(g['market'])}, {g['listed']} listed" for g in result["gathering"][:20]]
    crafts = [f"- {r['name']} ({r['prof']}): mats {_fmt(r['cost'])}, sells {_fmt(r['value'])}"
              for r in result["crafts"] if r["profit"] is not None][:12]
    raids = ", ".join(f"{r['name']} on {r['date']}" for r in result["raids"]) or "none announced"
    return f"""You are a World of Warcraft: Forever gold and profession advisor. WoW Forever is Blizzard's 2026 vanilla-based \
game (launched 4 Nov 2026, level cap 60, realmless rulesets, modern commodity Auction House). It differs from Classic Era: \
check that what you recommend applies to Forever, and say so when you can't verify it.

The player ({faction}) has these characters:
{chr(10).join(chars) or '- (no character details recorded yet)'}

Current Auction House prices from their own scan:
{chr(10).join(market) or '- (none)'}

Recipes they know with current margins:
{chr(10).join(crafts) or '- (none recorded)'}

Upcoming raids: {raids}.

Use web search. Prefer wowhead.com/forever pages, Blizzard's Forever hotfix notes and recent Forever guides. Then write a \
practical guide for the highest-level character first, then briefly for the others. Use these sections, in markdown:

## Gold at your level
Quests in or near their level range that pay well in gold, or give rewards that sell well (quest name, zone, level, why). \
Also the best gold activity at this level: gathering route, dungeon or farm.

## Professions: what to do next
For each profession: what skill range they're in, the next recipes to make (and which ones sell, using the prices above), \
mats to buy now (only if cheaper than farming), and when to visit the trainer for the next rank.

## Items to watch
Items whose prices are about to move: new Forever content, hotfixes, raid demand on {raids}.

## What changed recently
Forever hotfixes or patch notes from the last few weeks that affect gold-making, with dates.

## This session's checklist
5 to 8 short, concrete steps in order.

Keep it under 900 words, be specific (names, zones, levels, prices), and don't invent quest or item names: leave out \
anything you couldn't find a source for."""


def _post(key, body, timeout=150):
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_guide(cfg, result, post=None):
    """Run the research and cache it. Returns the cached dict; on failure, a dict with 'error'."""
    post = post or _post
    key = api_key(cfg)
    if not key:
        return {"error": "Add your Claude API key in Settings first (console.anthropic.com, API keys)."}
    model = cfg.get("guide_model") or cfg.get("claude_model") or "claude-sonnet-5-5"
    messages = [{"role": "user", "content": build_prompt(result)}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": int(cfg.get("guide_searches", 8))}]
    blocks = []
    try:
        for _ in range(4):  # long searches can pause; continue them
            data = post(key, {"model": model, "max_tokens": 4000, "messages": messages, "tools": tools})
            content = data.get("content", [])
            blocks.extend(content)
            if data.get("stop_reason") == "pause_turn":
                messages = messages + [{"role": "assistant", "content": content}]
                continue
            break
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        msg = {401: "Your Claude API key was rejected. Check it in Settings.",
               429: "Claude API rate limit reached. Try again in a minute."}.get(e.code, f"Claude API error {e.code}: {detail}")
        if e.code == 400 and "web search" in detail.lower():
            msg = "Web search isn't enabled for your Claude API organization (Claude Console, Settings)."
        return {"error": msg}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"error": f"Couldn't reach the Claude API ({e})."}

    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    sources, seen = [], set()
    for b in blocks:
        for c in (b.get("citations") or []) if b.get("type") == "text" else []:
            url = c.get("url")
            if url and url not in seen:
                seen.add(url)
                sources.append({"url": url, "title": c.get("title") or url})
    for b in blocks:
        if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
            for r in b["content"]:
                url = r.get("url")
                if url and url not in seen and len(sources) < 15:
                    seen.add(url)
                    sources.append({"url": url, "title": r.get("title") or url})
    searches = sum(1 for b in blocks if b.get("type") == "server_tool_use")
    if not text:
        return {"error": "Claude didn't return a guide. Try again."}
    out = {"ts": int(time.time()), "model": model, "markdown": text, "sources": sources, "searches": searches,
           "for": [f"{p['name']} {p['level']}" for p in result["profiles"]]}
    GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUIDE_PATH.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def md_to_html(md):
    """Small, safe markdown renderer: headings, lists, bold, italics, links, paragraphs."""
    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>', t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        return t

    out, list_tag, para = [], None, []

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in md.splitlines():
        line = raw.rstrip()
        m_h = re.match(r"^(#{1,4})\s+(.*)$", line)
        m_ul = re.match(r"^\s*[-*•]\s+(.*)$", line)
        m_ol = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if not line.strip():
            flush_para(); close_list()
        elif m_h:
            flush_para(); close_list()
            level = min(4, len(m_h.group(1)) + 1)
            out.append(f"<h{level}>{inline(m_h.group(2))}</h{level}>")
        elif m_ul or m_ol:
            flush_para()
            tag = "ul" if m_ul else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append("<li>" + inline((m_ul or m_ol).group(1)) + "</li>")
        else:
            close_list()
            para.append(line.strip())
    flush_para(); close_list()
    return "\n".join(out)
