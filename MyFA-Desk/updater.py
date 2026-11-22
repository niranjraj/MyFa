"""Self-update for MyFA: checks GitHub Releases and installs the new addon + Desk in place."""
import hashlib
import json
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "niranjraj/MyFa"
HERE = Path(__file__).resolve().parent
VERSION_FILE = HERE / "VERSION"
DATA_DIR = HERE / "data"
SHIPPED_RAIDS_HASH = DATA_DIR / "raids.shipped.sha256"

# files in the Desk folder that belong to you, never overwritten by an update
KEEP_DESK = {"config.json", "report.html", "claude_brief.md", "claude_advice.md", "Targets.lua"}


def local_version():
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _parse(v):
    parts = []
    for p in v.lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts + [0] * (3 - len(parts)))


def _get(url, token=None, accept="application/vnd.github+json", timeout=15):
    headers = {"User-Agent": "MyFA-Desk", "Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
        return resp.read()


def latest_release(token=None, repo=REPO):
    """(version, asset) for the newest release with a MyFA-Kit zip, or (None, None)."""
    data = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest", token))
    asset = next((a for a in data.get("assets", [])
                  if a["name"].startswith("MyFA-Kit") and a["name"].endswith(".zip")), None)
    return data.get("tag_name"), asset, data.get("body") or ""


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def apply_update(zip_path: Path, addon_dir: Path = None, desk_dir: Path = HERE):
    """Install a MyFA-Kit zip. Returns a list of notes for the user."""
    notes = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                target = (tmp / member).resolve()
                if not str(target).startswith(str(tmp.resolve())):
                    raise ValueError(f"unsafe path in update zip: {member}")
            z.extractall(tmp)
        new_addon, new_desk = tmp / "MyFA", tmp / "MyFA-Desk"
        if not new_desk.exists():
            raise ValueError("update zip has no MyFA-Desk folder")

        # addon: replace everything except the targets Desk writes
        if addon_dir and new_addon.exists():
            addon_dir.mkdir(parents=True, exist_ok=True)
            for src in new_addon.rglob("*"):
                rel = src.relative_to(new_addon)
                dst = addon_dir / rel
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                elif rel.as_posix() == "Data/Targets.lua" and dst.exists():
                    continue
                else:
                    shutil.copy2(src, dst)
            notes.append(f"Addon updated in {addon_dir}. Type /reload in game.")
        elif new_addon.exists():
            notes.append("Addon not updated: WoW folder unknown. Copy MyFA from the release zip by hand.")

        # desk: replace program files, keep your settings, data and edited raid calendar
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shipped = SHIPPED_RAIDS_HASH.read_text().strip() if SHIPPED_RAIDS_HASH.exists() else None
        mine = desk_dir / "raids.json"
        for src in new_desk.rglob("*"):
            rel = src.relative_to(new_desk)
            dst = desk_dir / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            if rel.parts[0] == "data" or rel.name in KEEP_DESK:
                continue
            if rel.as_posix() == "raids.json" and mine.exists() and shipped and _sha(mine) != shipped:
                shutil.copy2(src, desk_dir / "raids.new.json")
                notes.append("You've edited raids.json, so it was kept. The new calendar is in raids.new.json; merge what you need.")
                continue
            shutil.copy2(src, dst)
        new_raids = new_desk / "raids.json"
        if new_raids.exists():
            SHIPPED_RAIDS_HASH.write_text(_sha(new_raids))
    return notes


def remember_shipped_raids():
    """On first run, record the shipped raids.json so later updates can tell if you edited it."""
    mine = HERE / "raids.json"
    if mine.exists() and not SHIPPED_RAIDS_HASH.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SHIPPED_RAIDS_HASH.write_text(_sha(mine))


def check_and_update(addon_dir, mode="ask", token=None, force=False):
    """Returns True if an update was installed (caller should restart)."""
    remember_shipped_raids()
    if mode == "never" and not force:
        return False
    try:
        tag, asset, body = latest_release(token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            if force:
                print("No MyFA release published yet.")
            return False
        print(f"Update check failed (GitHub {e.code}). Carrying on.")
        return False
    except (urllib.error.URLError, OSError, ValueError) as e:
        if force:
            print(f"Couldn't reach GitHub to check for updates ({e}).")
        return False
    if not tag or not asset:
        return False
    current = local_version()
    if _parse(tag) <= _parse(current):
        if force:
            print(f"MyFA is up to date ({current}).")
        return False

    print(f"\nMyFA {tag} is available (you have {current}).")
    if body.strip():
        print("  " + "\n  ".join(body.strip().splitlines()[:8]))
    if mode == "ask" and not force:
        answer = input("Update now? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("Skipped. Run with --update any time.")
            return False

    print(f"Downloading {asset['name']}...")
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / asset["name"]
        if token:
            data = _get(asset["url"], token, accept="application/octet-stream", timeout=120)
        else:
            data = _get(asset["browser_download_url"], accept="application/octet-stream", timeout=120)
        zpath.write_bytes(data)
        notes = apply_update(zpath, addon_dir)
    VERSION_FILE.write_text(tag.lstrip("vV") + "\n", encoding="utf-8")
    print(f"Updated to {tag}.")
    for n in notes:
        print("  " + n)
    return True
