"""MyFA Desk app mode: runs quietly in the background and shows a live control center in your browser.

Start it by double-clicking "MyFA Desk.pyw" (no terminal window). It watches for /reload exactly like
the terminal version, serves the dashboard at http://127.0.0.1:47800, and refreshes it after every scan.
Only this computer can reach it. Standard library only.
"""
import collections
import contextlib
import html
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import myfa_desk as desk  # noqa: E402
import updater  # noqa: E402
import guide as guide_mod  # noqa: E402
import analysis  # noqa: E402
from analysis import History  # noqa: E402

DEFAULT_PORT = 47800
LOG = collections.deque(maxlen=200)
LOG_LOCK = threading.Lock()


class _LogWriter(io.TextIOBase):
    """Collects everything the Desk prints, so the control center can show it (pythonw has no console)."""

    def __init__(self):
        self._buf = ""

    def write(self, s):
        with LOG_LOCK:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = re.sub(r"^\[\d\d:\d\d:\d\d\]\s*", "", line.rstrip())
                if line.strip():
                    LOG.append(f"{time.strftime('%H:%M:%S')}  {line}")
        return len(s)

    def flush(self):
        pass


def log(msg):
    print(msg)


class Desk:
    def __init__(self, port):
        self.port = port
        self.cfg = desk.load_config()
        self.state = "starting"
        self.message = ""
        self.paused = False
        self.result = None
        self.report_ts = desk.REPORT_PATH.stat().st_mtime if desk.REPORT_PATH.exists() else 0
        self.update = {"checked": False, "available": False, "tag": None, "notes": "", "busy": False}
        self.guide = {"busy": False, "error": None, "started": None}
        self.reprocess = threading.Event()
        self.stop = threading.Event()
        self.restart_after_stop = False
        self.server = None

    # ---- paths -------------------------------------------------------------------
    def paths(self):
        cfg = self.cfg
        flavor = Path(cfg["wow_path"]) if cfg.get("wow_path") else None
        if not flavor or not flavor.exists():
            found = desk.find_wow()
            if found:
                cfg["wow_path"] = str(found)
                desk.save_config(cfg)
                log(f"Found WoW Forever at {found}")
                flavor = found
            else:
                self.state, self.message = "setup", "Tell MyFA where your WoW Forever (_forever_) folder is."
                return None
        accs = desk.accounts(flavor)
        if cfg.get("account") not in accs:
            if len(accs) == 1:
                cfg["account"] = accs[0]
                desk.save_config(cfg)
            elif not accs:
                self.state, self.message = "setup", ("No account folder yet. Log into WoW Forever once with the MyFA "
                                                     "addon enabled, then come back.")
                return None
            else:
                self.state, self.message = "setup", "Pick which WoW account to use."
                return None
        sv = flavor / "WTF" / "Account" / cfg["account"] / "SavedVariables" / "MyFA.lua"
        targets = flavor / "Interface" / "AddOns" / "MyFA" / "Data" / "Targets.lua"
        return sv, targets

    # ---- watcher -----------------------------------------------------------------
    def watch(self):
        history = History(desk.DATA_DIR / "history.sqlite")
        args = types.SimpleNamespace(ask_claude=False, no_open=True)
        last = None
        written = None
        while not self.stop.is_set():
            try:
                if self.paused:
                    self.state = "paused"
                    self.stop.wait(1)
                    continue
                p = self.paths()
                if not p:
                    self.stop.wait(2)
                    continue
                sv, targets = p
                if not (targets.parent.parent.exists()):
                    self.state = "setup"
                    self.message = f"The MyFA addon isn't installed in {targets.parent.parent.parent}."
                    self.stop.wait(3)
                    continue
                try:
                    st = sv.stat()
                    sig = (st.st_mtime, st.st_size)
                except OSError:
                    sig = None
                    self.state = "waiting"
                    self.message = "Waiting for your first scan: open the Auction House, press Full scan, then /reload."
                if self.reprocess.is_set():
                    self.reprocess.clear()
                    last = None
                if written is not None and desk.targets_signature(targets) != written:
                    last = None   # an addon update replaced the targets: write them again
                    log("Targets were replaced (addon update?). Writing them again.")
                if sig and sig != last:
                    time.sleep(1.0)  # let WoW finish writing
                    st2 = sv.stat()
                    if (st2.st_mtime, st2.st_size) == sig:
                        self.state, self.message = "working", "Reading your latest scan..."
                        self.cfg = desk.load_config()
                        result = desk.process(sv, targets, self.cfg, history, args)
                        if result:
                            self.result = result
                            self.report_ts = desk.REPORT_PATH.stat().st_mtime
                            written = desk.targets_signature(targets)
                        last = sig
                if sig:
                    self.state = "watching"
                    self.message = "Watching for /reload."
            except Exception as e:  # keep the app alive; show the problem in the control center
                self.state, self.message = "error", f"{type(e).__name__}: {e}"
                log(f"Error: {e}")
                self.stop.wait(5)
            self.stop.wait(2)

    # ---- updates -----------------------------------------------------------------
    def check_update(self, quiet=True):
        try:
            tag, asset, body = updater.latest_release(self.cfg.get("github_token") or None)
        except Exception as e:
            if not quiet:
                log(f"Couldn't check for updates ({e}).")
            self.update.update(checked=True, available=False)
            return
        newer = bool(tag and asset and updater._parse(tag) > updater._parse(updater.local_version()))
        self.update.update(checked=True, available=newer, tag=tag, notes=body or "")
        if not quiet:
            log(f"MyFA {tag} is available." if newer else f"MyFA is up to date ({updater.local_version()}).")
        if newer and self.cfg.get("auto_update") == "always":
            self.apply_update()

    def apply_update(self):
        if self.update["busy"]:
            return
        self.update["busy"] = True
        try:
            addon_dir = Path(self.cfg["wow_path"]) / "Interface" / "AddOns" / "MyFA" if self.cfg.get("wow_path") else None
            via_cf = updater.addon_source(addon_dir, self.cfg.get("addon_updates", "auto")) == "curseforge"
            if updater.check_and_update(addon_dir, "always", self.cfg.get("github_token") or None, force=True, addon_via_cf=via_cf):
                log("Restarting MyFA Desk with the new version...")
                self.restart_after_stop = True
                threading.Thread(target=self.shutdown, daemon=True).start()
        finally:
            self.update["busy"] = False

    def update_loop(self):
        if self.cfg.get("auto_update") == "never":
            return
        while not self.stop.is_set():
            self.check_update()
            self.stop.wait(6 * 3600)

    # ---- lifecycle -----------------------------------------------------------------
    def shutdown(self):
        time.sleep(0.4)  # let the HTTP response go out
        self.stop.set()
        if self.server:
            self.server.shutdown()

    # ---- api -------------------------------------------------------------------------
    def status(self):
        r = self.result
        summary = None
        ready = []
        if r:
            ready = [{"name": p["name"], "qty": p["qty"], "pl": p["pl"], "where": p["where"]}
                     for p in r["positions"] if p["status"] == "Sell now"]
            summary = {
                "realm": r["realm"], "scan_ts": r["scan_ts"], "flips": len(r["flips"]) + len(r["vendor"]),
                "ready": len(ready), "owned": len(r["inventory"]), "chars": r["n_chars"],
                "crafts": sum(1 for c in r["crafts"] if c["profit"] and c["profit"] > 0),
            }
        flavor = Path(self.cfg["wow_path"]) if self.cfg.get("wow_path") else None
        with LOG_LOCK:
            lines = list(LOG)[-80:]
        return {
            "version": updater.local_version(), "state": self.state, "message": self.message, "paused": self.paused,
            "report_ts": self.report_ts, "summary": summary, "ready": ready, "log": lines, "update": self.update,
            "settings": {
                "wow_path": self.cfg.get("wow_path", ""), "account": self.cfg.get("account", ""),
                "accounts": desk.accounts(flavor) if flavor and flavor.exists() else [],
                "ah_cut": self.cfg.get("ah_cut", 0.05),
                "desktop_notifications": bool(self.cfg.get("desktop_notifications", True)),
                "auto_update": self.cfg.get("auto_update", "ask"),
                "addon_updates": self.cfg.get("addon_updates", "auto"),
            },
            "windows": os.name == "nt",
            "guide": dict(self.guide, has_key=bool(guide_mod.api_key(self.cfg)), provider=guide_mod.provider(self.cfg),
                          claude_code=bool(guide_mod.find_claude_cli(self.cfg)), source=self.cfg.get("guide_source", "auto")),
        }

    def save_settings(self, data):
        cfg = desk.load_config()
        errors = []
        if "wow_path" in data:
            raw = (data.get("wow_path") or "").strip().strip('"')
            if raw:
                flavor = desk.resolve_flavor(Path(raw))
                if not flavor:
                    errors.append("That folder doesn't look like WoW Forever. Pick the _forever_ folder (it contains Interface and WTF).")
                else:
                    cfg["wow_path"] = str(flavor)
        if data.get("account"):
            cfg["account"] = data["account"]
        if "ah_cut" in data:
            try:
                cut = float(data["ah_cut"]) / 100
                if not 0 <= cut < 0.5:
                    raise ValueError
                cfg["ah_cut"] = round(cut, 4)
            except (TypeError, ValueError):
                errors.append("Auction House cut must be a percentage between 0 and 50.")
        if "desktop_notifications" in data:
            cfg["desktop_notifications"] = bool(data["desktop_notifications"])
        if data.get("auto_update") in ("ask", "always", "never"):
            cfg["auto_update"] = data["auto_update"]
        if data.get("addon_updates") in ("auto", "desk", "curseforge"):
            cfg["addon_updates"] = data["addon_updates"]
        if data.get("guide_source") in ("auto", "claude_code", "chat", "api"):
            cfg["guide_source"] = data["guide_source"]
        if "anthropic_api_key" in data and data["anthropic_api_key"] != "__keep__":
            key = (data.get("anthropic_api_key") or "").strip()
            if key and not key.startswith("sk-"):
                errors.append("That doesn't look like a Claude API key (they start with sk-).")
            else:
                cfg["anthropic_api_key"] = key
        if not errors:
            desk.save_config(cfg)
            self.cfg = cfg
            self.reprocess.set()
            log("Settings saved.")
        return errors

    # ---- flips added or removed from the dashboard --------------------------------------
    def add_flip(self, data):
        r = self.result
        if not r:
            return {"error": "No scan loaded yet. Do a scan first so MyFA knows item names."}
        text = (data.get("item") or "").strip()
        item_id = int(text) if text.isdigit() else r["names"].get(text.lower())
        if not item_id:
            return {"error": f"Couldn't find \"{text}\". Pick a name from the suggestions; the item must have been seen in a scan or your bags."}
        try:
            qty = int(data.get("qty") or 0)
        except ValueError:
            qty = 0
        if qty < 1:
            return {"error": "Enter how many you bought."}
        price = analysis.parse_money(str(data.get("price") or ""))
        if not price:
            return {"error": "Enter the price you paid for each, like 14s50c or 1g20s."}
        ts = int(time.time())
        if data.get("date"):
            try:
                ts = int(time.mktime(time.strptime(data["date"] + " 12:00", "%Y-%m-%d %H:%M")))
            except ValueError:
                pass
        manual = analysis.load_manual()
        manual.setdefault("adds", []).append({
            "mid": os.urandom(6).hex(), "id": item_id, "q": qty, "u": price, "t": ts, "realm": r["realm"], "name": text})
        manual.setdefault("forgets", {}).pop(str(item_id), None)
        analysis.save_manual(manual)
        log(f"Added flip: {qty} {text} at {analysis.fmt(price)} each. /reload in game to sync it to the addon.")
        self.reprocess.set()
        return {"ok": True, "message": f"Added {qty} {text}. It shows here in a moment; /reload in game to sync it."}

    def forget_flip(self, data):
        try:
            item_id = int(data.get("id"))
        except (TypeError, ValueError):
            return {"error": "Unknown item."}
        manual = analysis.load_manual()
        manual["adds"] = [m for m in manual.get("adds", []) if m.get("id") != item_id]
        manual.setdefault("forgets", {})[str(item_id)] = int(time.time())
        analysis.save_manual(manual)
        log("Stopped tracking a flip. /reload in game to sync it to the addon.")
        self.reprocess.set()
        return {"ok": True}

    def item_names(self):
        r = self.result
        if not r:
            return []
        owned = {x["name"] for x in r["inventory"]}
        names = sorted(r["names"], key=lambda n: n)
        # items you own first, then everything else; original capitalisation from the scan
        proper = {}
        for g in ("inventory", "trends", "gathering", "flips", "crafts"):
            for x in r.get(g, []):
                proper[x["name"].lower()] = x["name"]
        out = sorted(owned) + [proper.get(n, n.title()) for n in names if proper.get(n, n.title()) not in owned]
        return out[:6000]

    # ---- researched guide ----------------------------------------------------------------
    def start_guide(self):
        if self.guide["busy"]:
            return {"ok": True}
        if not self.result:
            return {"error": "No scan loaded yet. Do a scan first."}
        how = guide_mod.provider(self.cfg)
        if how == "chat":
            return {"error": "Use the Claude chat steps: copy the request, ask Claude, paste the answer back."}
        self.guide.update(busy=True, error=None, started=time.time())

        def run():
            log("Researching your guide with " + ("Claude Code (your Claude plan)" if how == "claude_code" else "the Claude API")
                + " and web search... this takes a few minutes.")
            out = guide_mod.fetch(self.cfg, self.result)
            if out.get("error"):
                self.guide.update(busy=False, error=out["error"])
                log(f"Guide: {out['error']}")
            else:
                self.guide.update(busy=False, error=None)
                log(f"Guide ready (via {out.get('via', 'Claude')}).")
                self.reprocess.set()
        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def guide_prompt(self):
        if not self.result:
            return {"error": "No scan loaded yet. Do a scan first."}
        return {"prompt": guide_mod.chat_prompt(self.result)}

    def guide_paste(self, data):
        if not self.result:
            return {"error": "No scan loaded yet. Do a scan first."}
        out = guide_mod.save_pasted(data.get("text", ""), self.result)
        if out.get("error"):
            return out
        log("Saved Claude's guide from chat.")
        self.reprocess.set()
        return {"ok": True}

    def detect(self):
        found = desk.find_wow()
        if found:
            return {"wow_path": str(found)}
        return {"error": "Couldn't find it automatically. In Battle.net: World of Warcraft, choose WoW Forever, "
                         "gear icon next to Play, Show in Explorer, open _forever_, then copy the address bar."}

    def desktop_shortcut(self):
        candidates = []
        if os.environ.get("OneDrive"):
            candidates.append(Path(os.environ["OneDrive"]) / "Desktop")
        candidates.append(Path.home() / "Desktop")
        target = next((c for c in candidates if c.exists()), None)
        if not target:
            return {"error": "Couldn't find your Desktop folder."}
        stub = target / "MyFA Desk.pyw"
        stub.write_text(
            "# Starts MyFA Desk (no terminal). Created by MyFA.\n"
            f"import sys\nsys.path.insert(0, r\"{HERE}\")\nimport app\napp.main()\n",
            encoding="utf-8",
        )
        log(f"Added MyFA Desk to your desktop: {stub}")
        return {"ok": True, "path": str(stub)}


# ---- HTTP ---------------------------------------------------------------------------------

def make_handler(app: Desk):
    allowed_hosts = {f"127.0.0.1:{app.port}", f"localhost:{app.port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _ok_host(self):
            return self.headers.get("Host", "") in allowed_hosts

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._ok_host():
                return self._send(403, '{"error":"forbidden"}')
            if self.path in ("/", "/index.html"):
                return self._send(200, page(app), "text/html")
            if self.path == "/favicon.ico":
                return self._send(200, FAVICON, "image/svg+xml")
            if self.path == "/api/status":
                return self._send(200, json.dumps(app.status()))
            if self.path == "/api/guide-prompt":
                return self._send(200, json.dumps(app.guide_prompt()))
            if self.path == "/api/items":
                return self._send(200, json.dumps(app.item_names()))
            return self._send(404, '{"error":"not found"}')

        def do_POST(self):
            # only our own page can call these: custom header + matching Host block other sites and DNS rebinding
            if not self._ok_host() or self.headers.get("X-MyFA") != "1":
                return self._send(403, '{"error":"forbidden"}')
            length = min(int(self.headers.get("Content-Length") or 0), 65536)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                data = {}
            route = self.path
            if route == "/api/pause":
                app.paused = True
                log("Paused. MyFA won't read new scans until you resume.")
                return self._send(200, '{"ok":true}')
            if route == "/api/resume":
                app.paused = False
                app.reprocess.set()
                log("Resumed watching.")
                return self._send(200, '{"ok":true}')
            if route == "/api/refresh":
                app.reprocess.set()
                return self._send(200, '{"ok":true}')
            if route == "/api/settings":
                errors = app.save_settings(data)
                return self._send(200, json.dumps({"ok": not errors, "errors": errors}))
            if route == "/api/addflip":
                return self._send(200, json.dumps(app.add_flip(data)))
            if route == "/api/forget":
                return self._send(200, json.dumps(app.forget_flip(data)))
            if route == "/api/guide-paste":
                return self._send(200, json.dumps(app.guide_paste(data)))
            if route == "/api/guide":
                return self._send(200, json.dumps(app.start_guide()))
            if route == "/api/detect":
                return self._send(200, json.dumps(app.detect()))
            if route == "/api/shortcut":
                return self._send(200, json.dumps(app.desktop_shortcut()))
            if route == "/api/check-update":
                app.check_update(quiet=False)
                return self._send(200, json.dumps(app.update))
            if route == "/api/update":
                threading.Thread(target=app.apply_update, daemon=True).start()
                return self._send(200, '{"ok":true}')
            if route == "/api/quit":
                log("Stopping MyFA Desk.")
                threading.Thread(target=app.shutdown, daemon=True).start()
                return self._send(200, '{"ok":true}')
            return self._send(404, '{"error":"not found"}')

    return Handler


def page(app: Desk):
    if desk.REPORT_PATH.exists():
        body = desk.REPORT_PATH.read_text(encoding="utf-8")
        control = CONTROL_HTML.replace("__TS__", json.dumps(app.report_ts)).replace("__PORT__", str(app.port))
        if "<!--MYFA-CONTROL-->" in body:
            return body.replace("<!--MYFA-CONTROL-->", control, 1)
        return body.replace("<body>", "<body>" + control, 1)
    return SETUP_HTML.replace("__CONTROL__", CONTROL_HTML.replace("__TS__", "0").replace("__PORT__", str(app.port)))


PID_PATH = desk.DATA_DIR / "app.pid"
ERROR_PAGE = desk.DATA_DIR / "startup-error.html"


def running_status(port):
    """The running copy's status, or None if nothing answers."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def ask_to_quit(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/quit", data=b"{}", method="POST",
                                     headers={"X-MyFA": "1", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception:
        return False


def kill_old(pid):
    """Stop a frozen copy of MyFA Desk (only the process recorded in data/app.pid)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


class DeskServer(ThreadingHTTPServer):
    """Owns its port exclusively, so a second MyFA Desk can never share it.
    On Windows SO_REUSEADDR would let two programs bind the same port, so use SO_EXCLUSIVEADDRUSE there;
    elsewhere SO_REUSEADDR only skips the TIME_WAIT delay after a restart."""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            elif os.name != "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_port_free(port, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if port_free(port):
            return True
        time.sleep(0.4)
    return port_free(port)


def show_startup_error(port, detail):
    """No terminal in app mode, so explain the problem in the browser."""
    desk.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ERROR_PAGE.write_text(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>MyFA Desk couldn't start</title>
<style>body{{background:#0b0d0f;color:#ebe6da;font:15px/1.6 "Segoe UI",system-ui,sans-serif;max-width:640px;margin:12vh auto;padding:0 24px}}
h1{{font-size:22px}} code{{color:#e3bd62}} p{{color:#a29d91}} b{{color:#ebe6da}}</style></head><body>
<h1>MyFA Desk couldn't start</h1>
<p>Something else on this PC is using port <code>{port}</code>, and it isn't a MyFA Desk that answers.</p>
<p><b>Try this:</b> restart your PC, then double-click MyFA Desk again. If it keeps happening, open
<code>config.json</code> in the MyFA-Desk folder and set <code>"port": {port + 1}</code>.</p>
<p>Details: {html.escape(detail)}</p></body></html>""", encoding="utf-8")
    webbrowser.open(ERROR_PAGE.as_uri())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.stdout is None or "--quiet" in argv or sys.executable.lower().endswith("pythonw.exe"):
        sys.stdout = sys.stderr = _LogWriter()
    else:
        tee = _LogWriter()
        real = sys.stdout

        class _Tee(io.TextIOBase):
            def write(self, s):
                real.write(s)
                return tee.write(s)

            def flush(self):
                real.flush()
        sys.stdout = _Tee()

    cfg = desk.load_config()
    port = int(cfg.get("port") or DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}/"
    no_browser = "--no-browser" in argv

    app = Desk(port)
    server = None
    deadline = time.time() + (20 if "--restart" in argv else 0)
    mine = updater.local_version()
    while server is None:
        try:
            server = DeskServer(("127.0.0.1", port), make_handler(app))
            break
        except OSError:
            if time.time() < deadline:
                time.sleep(0.5)
                continue
        # the port is taken: is it MyFA Desk, and is it this version?
        status = running_status(port)
        if status and status.get("version") == mine:
            if not no_browser:
                webbrowser.open(url)          # already running and up to date: just show it
            return
        if status:
            log(f"Replacing MyFA Desk {status.get('version')} with {mine}.")
            ask_to_quit(port)
        else:
            try:
                pid = int(PID_PATH.read_text().strip())
            except (OSError, ValueError):
                pid = None
            if pid and pid != os.getpid():
                log("The running MyFA Desk isn't answering. Restarting it.")
                kill_old(pid)
        if not wait_port_free(port, 12):
            show_startup_error(port, "the port is still in use after trying to stop the old copy")
            return
        try:
            server = DeskServer(("127.0.0.1", port), make_handler(app))
        except OSError as e:
            show_startup_error(port, str(e))
            return
    app.server = server
    try:
        desk.DATA_DIR.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(str(os.getpid()))
    except OSError:
        pass
    updater.remember_shipped_raids()
    log(f"MyFA Desk {updater.local_version()} running at {url}")
    threading.Thread(target=app.watch, daemon=True).start()
    threading.Thread(target=app.update_loop, daemon=True).start()
    if not no_browser and "--restart" not in argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        app.stop.set()
        try:
            if PID_PATH.exists() and PID_PATH.read_text().strip() == str(os.getpid()):
                PID_PATH.unlink()
        except OSError:
            pass
        if app.restart_after_stop:
            pyw = Path(sys.executable)
            exe = pyw.with_name("pythonw.exe") if os.name == "nt" and pyw.with_name("pythonw.exe").exists() else pyw
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([str(exe), str(HERE / "app.py"), "--restart"], cwd=str(HERE),
                             creationflags=flags if os.name == "nt" else 0, close_fds=True)


# ---- UI: control bar injected above the dashboard, and the first-run page ----------------------------

FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#e3bd62"/>'
           '<circle cx="16" cy="16" r="10" fill="none" stroke="#8a6a1f" stroke-width="2"/>'
           '<text x="16" y="21" font-size="13" font-family="Segoe UI,Arial" font-weight="700" text-anchor="middle" '
           'fill="#3a2a08">FA</text></svg>')

CONTROL_HTML = r"""
<style>
.cbar { position: sticky; top: 0; z-index: 20; background: rgba(11, 13, 15, .92); backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line, #242a31); font: 13.5px/1.4 var(--sans, system-ui); color: var(--text, #ebe6da); }
.cbar-in { max-width: 1480px; margin: 0 auto; padding: 10px 28px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 20px; }
.cstate { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 320px; }
.cstate b { font-weight: 600; white-space: nowrap; }
.cstate .muted { color: var(--muted, #a29d91); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: none; background: #5b6570; }
.dot.watching { background: #72d38e; box-shadow: 0 0 0 0 rgba(114, 211, 142, .5); animation: pulse 2.4s ease-out infinite; }
.dot.working { background: #e3bd62; }
.dot.paused { background: #8f8a7e; }
.dot.setup, .dot.waiting { background: #e9c46a; }
.dot.error { background: #f08c79; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(114, 211, 142, .45); } 70% { box-shadow: 0 0 0 8px rgba(114, 211, 142, 0); } 100% { box-shadow: 0 0 0 0 rgba(114, 211, 142, 0); } }
@media (prefers-reduced-motion: reduce) { .dot.watching { animation: none; } }
.cact { display: flex; flex-wrap: wrap; gap: 8px; }
.cbtn { appearance: none; border: 1px solid var(--line, #242a31); background: var(--panel, #12151a); color: var(--text, #ebe6da);
  font: 500 13px var(--sans, system-ui); padding: 7px 12px; border-radius: 6px; cursor: pointer;
  transition: background-color .15s ease-out, border-color .15s ease-out; }
.cbtn:hover { background: var(--raise, #171b21); border-color: #343b43; }
.cbtn:active { transform: translateY(1px); }
.cbtn:disabled { opacity: .55; cursor: default; }
.cbtn.primary { background: #e3bd62; border-color: #e3bd62; color: #17130a; font-weight: 600; }
.cbtn.primary:hover { background: #ecc978; }
.cbtn.ghost { background: transparent; }
.cbtn:focus-visible { outline: 2px solid #e3bd62; outline-offset: 2px; }
.pill { appearance: none; border: 1px solid rgba(114, 211, 142, .45); background: rgba(114, 211, 142, .1); color: #a6e6b8;
  border-radius: 999px; padding: 5px 12px; font: 500 12.5px var(--sans, system-ui); cursor: pointer; }
.pill:hover { background: rgba(114, 211, 142, .18); }
.cpanel { border-top: 1px solid var(--line, #242a31); background: var(--panel, #12151a); }
.cpanel-in { max-width: 1480px; margin: 0 auto; padding: 18px 28px 22px; display: grid; gap: 22px 40px;
  grid-template-columns: minmax(300px, 560px) minmax(260px, 1fr); }
.cpanel h3 { margin: 0 0 12px; font-size: 14px; font-weight: 600; }
.field { display: grid; gap: 6px; margin-bottom: 14px; }
.field label { font-weight: 500; }
.field .hint { color: var(--muted, #a29d91); font-size: 12.5px; }
.row { display: flex; gap: 8px; }
.row input { flex: 1; }
.cpanel input[type=text], .cpanel input[type=number], .cpanel select { background: var(--bg, #0b0d0f); color: var(--text, #ebe6da);
  border: 1px solid var(--line, #242a31); border-radius: 6px; padding: 7px 10px; font: 13px var(--sans, system-ui); min-width: 0; }
.cpanel input:focus, .cpanel select:focus { border-color: #e3bd62; outline: none; }
.check { display: flex; align-items: center; gap: 8px; }
.check input { accent-color: #e3bd62; width: 16px; height: 16px; }
.errors { color: #f08c79; margin: 0 0 12px; }
.saved { color: #72d38e; margin-left: 10px; }
.logbox { margin: 0; height: 260px; overflow: auto; background: var(--bg, #0b0d0f); border: 1px solid var(--line, #242a31);
  border-radius: 6px; padding: 10px 12px; font: 12px/1.55 var(--mono, ui-monospace, monospace); color: var(--muted, #a29d91);
  white-space: pre-wrap; }
.stopped { max-width: 560px; margin: 18vh auto; padding: 0 24px; font: 15px/1.6 var(--sans, system-ui); color: var(--muted, #a29d91); }
.stopped h1 { color: var(--text, #ebe6da); font-size: 22px; margin: 0 0 8px; }
@media (max-width: 860px) { .cpanel-in { grid-template-columns: 1fr; } .cbar-in, .cpanel-in { padding-left: 14px; padding-right: 14px; } }
</style>
<div class="cbar" id="cbar">
  <div class="cbar-in">
    <div class="cstate" role="status" aria-live="polite">
      <span class="dot" id="c-dot"></span><b id="c-state">Starting</b><span class="muted" id="c-msg"></span>
    </div>
    <button type="button" class="pill" id="c-new" hidden>New scan ready, refresh</button>
    <div class="cact">
      <button type="button" class="cbtn" id="c-pause">Pause</button>
      <button type="button" class="cbtn" id="c-update">Check for updates</button>
      <button type="button" class="cbtn" id="c-settings" aria-expanded="false" aria-controls="c-panel">Settings</button>
      <button type="button" class="cbtn ghost" id="c-quit">Quit</button>
    </div>
  </div>
  <div class="cpanel" id="c-panel" hidden>
    <div class="cpanel-in">
      <form id="c-form" novalidate>
        <h3>Settings</h3>
        <p class="errors" id="c-errors" hidden></p>
        <div class="field">
          <label for="c-wow">WoW Forever folder</label>
          <div class="row"><input type="text" id="c-wow" spellcheck="false" autocomplete="off"
            placeholder="C:\Program Files (x86)\World of Warcraft\_forever_"><button type="button" class="cbtn" id="c-detect">Find it</button></div>
          <span class="hint">The <code>_forever_</code> folder. In Battle.net: gear next to Play, Show in Explorer.</span>
        </div>
        <div class="field">
          <label for="c-account">WoW account</label>
          <select id="c-account"></select>
        </div>
        <div class="field">
          <label for="c-cut">Auction House cut (%)</label>
          <input type="number" id="c-cut" min="0" max="50" step="0.5" style="max-width:120px">
          <span class="hint">Check a "sold" mail in game and enter the real cut.</span>
        </div>
        <div class="field">
          <label class="check"><input type="checkbox" id="c-notify"> Windows notification when a flip is worth selling</label>
        </div>
        <div class="field">
          <label for="c-guide">Guide uses</label>
          <select id="c-guide" style="max-width:360px">
            <option value="auto">Automatic (Claude Code if installed, otherwise Claude chat)</option>
            <option value="claude_code">Claude Code on this PC (your Claude plan)</option>
            <option value="chat">Claude chat, copy and paste (your Claude plan)</option>
            <option value="api">Claude API key (API credit)</option>
          </select>
          <span class="hint" id="c-guide-hint"></span>
        </div>
        <div class="field" id="c-key-field">
          <label for="c-key">Claude API key (only for the API option)</label>
          <input type="password" id="c-key" autocomplete="off" spellcheck="false" placeholder="sk-ant-...">
        </div>
        <div class="field">
          <label for="c-auto">Updates</label>
          <select id="c-auto" style="max-width:260px">
            <option value="ask">Ask me (button turns gold)</option>
            <option value="always">Install automatically</option>
            <option value="never">Never check</option>
          </select>
        </div>
        <div class="field">
          <label for="c-addonsrc">In-game addon updated by</label>
          <select id="c-addonsrc" style="max-width:260px">
            <option value="auto">Automatic (CurseForge app if it came from there)</option>
            <option value="desk">MyFA Desk</option>
            <option value="curseforge">CurseForge app</option>
          </select>
        </div>
        <div class="row" style="align-items:center">
          <button type="submit" class="cbtn primary">Save settings</button>
          <button type="button" class="cbtn" id="c-shortcut">Add MyFA to desktop</button>
          <span class="saved" id="c-saved" hidden>Saved</span>
        </div>
      </form>
      <div>
        <h3>Activity</h3>
        <pre class="logbox" id="c-log" aria-label="Activity log"></pre>
      </div>
    </div>
  </div>
</div>
<script>
(() => {
  const LOADED_TS = __TS__;
  const $ = (id) => document.getElementById(id);
  const LABEL = { watching: 'Watching', working: 'Reading scan', paused: 'Paused', setup: 'Setup needed',
                  waiting: 'Waiting for first scan', error: 'Problem', starting: 'Starting' };
  let last = null, formDirty = false, stopped = false;
  const post = (path, body) => fetch(path, { method: 'POST', headers: { 'X-MyFA': '1', 'Content-Type': 'application/json' },
                                             body: JSON.stringify(body || {}) }).then(r => r.json().catch(() => ({})));
  const ago = (ts) => { const m = Math.floor((Date.now() / 1000 - ts) / 60); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : Math.floor(m / 60) + ' h ago'; };

  function fill(s) {
    const st = s.settings;
    if (formDirty) return;
    $('c-wow').value = st.wow_path || '';
    const sel = $('c-account');
    sel.innerHTML = (st.accounts.length ? st.accounts : [st.account || '']).map(a =>
      `<option ${a === st.account ? 'selected' : ''}>${a.replace(/</g, '&lt;')}</option>`).join('');
    sel.disabled = st.accounts.length < 2;
    $('c-cut').value = Math.round(st.ah_cut * 1000) / 10;
    $('c-notify').checked = st.desktop_notifications;
    $('c-notify').closest('.field').hidden = !s.windows;
    $('c-auto').value = st.auto_update;
    if ($('c-addonsrc')) $('c-addonsrc').value = st.addon_updates || 'auto';
    if (s.guide) {
      $('c-guide').value = s.guide.source || 'auto';
      $('c-key').placeholder = s.guide.has_key ? 'Saved (type to replace)' : 'sk-ant-...';
      $('c-guide-hint').textContent = s.guide.claude_code ? 'Claude Code is installed on this PC.'
        : 'Claude Code not found. Install it and run `claude` once to log in for one-click guides.';
      $('c-key-field').hidden = $('c-guide').value !== 'api';
    }
  }

  let render = function (s) {
    last = s;
    $('c-dot').className = 'dot ' + s.state;
    $('c-state').textContent = LABEL[s.state] || s.state;
    let msg = s.message || '';
    if (s.summary && (s.state === 'watching' || s.state === 'paused')) {
      const x = s.summary;
      msg = `${x.realm} · scan ${ago(x.scan_ts)} · ${x.flips} buy targets · ${x.ready} ready to sell · ${x.chars} character${x.chars === 1 ? '' : 's'}`;
    }
    $('c-msg').textContent = msg;
    $('c-pause').textContent = s.paused ? 'Resume' : 'Pause';
    const u = s.update, ub = $('c-update');
    if (u.busy) { ub.textContent = 'Updating…'; ub.disabled = true; ub.className = 'cbtn'; }
    else if (u.available) { ub.textContent = `Update to ${u.tag}`; ub.disabled = false; ub.className = 'cbtn primary'; ub.title = u.notes || ''; }
    else { ub.textContent = 'Check for updates'; ub.disabled = false; ub.className = 'cbtn'; ub.title = `You have ${s.version}`; }
    if (s.report_ts && s.report_ts > LOADED_TS + 0.5) {
      if (document.hidden || !LOADED_TS) location.reload(); else $('c-new').hidden = false;
    }
    const lg = $('c-log'), atBottom = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 8;
    lg.textContent = s.log.join('\n');
    if (atBottom) lg.scrollTop = lg.scrollHeight;
    fill(s);
    if ((s.state === 'setup') && $('c-panel').hidden) openPanel(true);
  };

  async function poll() {
    if (stopped) return;
    try { render(await (await fetch('/api/status', { cache: 'no-store' })).json()); }
    catch (e) { $('c-dot').className = 'dot error'; $('c-state').textContent = 'Not running';
      $('c-msg').textContent = 'MyFA Desk stopped or is restarting. Double-click MyFA Desk to start it.'; }
  }

  function openPanel(open) {
    $('c-panel').hidden = !open;
    $('c-settings').setAttribute('aria-expanded', open);
  }

  $('c-settings').onclick = () => openPanel($('c-panel').hidden);
  $('c-new').onclick = () => location.reload();
  $('c-pause').onclick = async () => { await post(last && last.paused ? '/api/resume' : '/api/pause'); poll(); };
  $('c-update').onclick = async () => {
    if (last && last.update.available) {
      $('c-update').textContent = 'Updating…'; $('c-update').disabled = true;
      await post('/api/update');
      const waitBack = setInterval(async () => {
        try { const s = await (await fetch('/api/status', { cache: 'no-store' })).json();
              if (s.version !== last.version) { clearInterval(waitBack); location.reload(); } } catch (e) {}
      }, 1500);
    } else {
      $('c-update').textContent = 'Checking…';
      await post('/api/check-update'); poll();
    }
  };
  $('c-quit').onclick = async () => {
    await post('/api/quit');
    stopped = true;
    document.body.innerHTML = '<div class="stopped"><h1>MyFA Desk has stopped</h1><p>It no longer reads scans or updates targets. ' +
      'Double-click <b>MyFA Desk</b> to start it again. You can close this tab.</p></div>';
  };
  $('c-detect').onclick = async () => {
    const r = await post('/api/detect');
    if (r.wow_path) { $('c-wow').value = r.wow_path; formDirty = true; $('c-errors').hidden = true; }
    else { $('c-errors').textContent = r.error; $('c-errors').hidden = false; }
  };
  $('c-shortcut').onclick = async () => {
    const r = await post('/api/shortcut');
    $('c-saved').textContent = r.ok ? 'Added to desktop' : (r.error || 'Couldn\'t add it');
    $('c-saved').hidden = false; setTimeout(() => $('c-saved').hidden = true, 4000);
  };
  $('c-form').addEventListener('input', () => { formDirty = true; $('c-key-field').hidden = $('c-guide').value !== 'api'; });
  $('c-form').onsubmit = async (e) => {
    e.preventDefault();
    const r = await post('/api/settings', {
      wow_path: $('c-wow').value, account: $('c-account').value, ah_cut: $('c-cut').value,
      desktop_notifications: $('c-notify').checked, auto_update: $('c-auto').value, addon_updates: $('c-addonsrc').value,
      guide_source: $('c-guide').value, anthropic_api_key: $('c-key').value || '__keep__' });
    if (r.ok) { formDirty = false; $('c-errors').hidden = true; $('c-saved').textContent = 'Saved'; $('c-saved').hidden = false;
                setTimeout(() => $('c-saved').hidden = true, 2500); poll(); }
    else { $('c-errors').textContent = (r.errors || ['Couldn\'t save.']).join(' '); $('c-errors').hidden = false; }
  };
  // ---- dashboard forms that need the running app (the dashboard loads below this script) ----
  document.body.classList.add('live');
  let gFetch = null, gStatus = null, guideWasBusy = false;
  const guideTick = (s) => {
    if (!gFetch || !s.guide) return;
    if (s.guide.busy) {
      guideWasBusy = true;
      gFetch.disabled = true; gFetch.textContent = 'Researching…'; gStatus.style.color = '';
      gStatus.textContent = `Searching Wowhead and Forever guides… ${Math.round(Date.now() / 1000 - s.guide.started)}s`;
    } else if (s.guide.error) {
      gFetch.disabled = !s.guide.has_key; gStatus.textContent = s.guide.error; gStatus.style.color = '#f08c79';
      if (gFetch.textContent === 'Researching…') gFetch.textContent = 'Try again';
    } else if (guideWasBusy) {
      gStatus.textContent = 'Guide ready. Loading…'; gStatus.style.color = '#72d38e'; guideWasBusy = false;
      setTimeout(() => location.reload(), 2500);
    }
  };
  const _render = render;
  render = (s) => { _render(s); guideTick(s); };
  const wire = () => {
  const fAdd = document.getElementById('f-add');
  if (fAdd) {
    fetch('/api/items', { cache: 'no-store' }).then(r => r.json()).then(names => {
      document.getElementById('f-items').innerHTML = names.map(n => `<option value="${n.replace(/"/g, '&quot;').replace(/</g, '&lt;')}">`).join('');
    }).catch(() => {});
    fAdd.onsubmit = async (e) => {
      e.preventDefault();
      const msg = document.getElementById('f-msg');
      msg.textContent = 'Adding…';
      const r = await post('/api/addflip', { item: document.getElementById('f-item').value, qty: document.getElementById('f-qty').value,
        price: document.getElementById('f-price').value, date: document.getElementById('f-date').value });
      msg.textContent = r.ok ? r.message : (r.error || 'Couldn\'t add it.');
      msg.style.color = r.ok ? '#72d38e' : '#f08c79';
      if (r.ok) { fAdd.reset(); setTimeout(() => location.reload(), 3500); }
    };
  }
  document.querySelectorAll('[data-forget]').forEach(b => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'Removing…';
    await post('/api/forget', { id: b.dataset.forget });
    setTimeout(() => location.reload(), 3500);
  }));
  gFetch = document.getElementById('g-fetch'); gStatus = document.getElementById('g-status');
  const gCopy = document.getElementById('g-copy');
  if (gCopy) gCopy.onclick = async () => {
    const r = await (await fetch('/api/guide-prompt', { cache: 'no-store' })).json();
    const out = document.getElementById('g-copied');
    if (r.error) { out.textContent = r.error; return; }
    try { await navigator.clipboard.writeText(r.prompt); out.textContent = 'Copied. Now open Claude and paste it.'; }
    catch (e) {
      const ta = document.getElementById('g-paste'); ta.value = r.prompt; ta.select();
      out.textContent = 'Copy blocked by the browser: the request is in the box below, press Ctrl+C, then clear the box.';
    }
  };
  const gSave = document.getElementById('g-save');
  if (gSave) gSave.onclick = async () => {
    const out = document.getElementById('g-saved');
    const r = await post('/api/guide-paste', { text: document.getElementById('g-paste').value });
    out.textContent = r.ok ? 'Saved. Loading your guide…' : (r.error || 'Couldn\'t save it.');
    out.style.color = r.ok ? '#72d38e' : '#f08c79';
    if (r.ok) setTimeout(() => location.reload(), 3000);
  };
  if (gFetch) gFetch.onclick = async () => {
    const r = await post('/api/guide');
    if (r.error) { gStatus.textContent = r.error; return; }
    gFetch.disabled = true; gFetch.textContent = 'Researching…'; guideWasBusy = true;
    gStatus.textContent = 'Starting…';
  };
  const gKey = document.getElementById('g-keyform');
  if (gKey) gKey.onsubmit = async (e) => {
    e.preventDefault();
    const r = await post('/api/settings', { anthropic_api_key: document.getElementById('g-key').value });
    if (r.ok) { location.reload(); } else { gStatus.textContent = (r.errors || []).join(' '); }
  };
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  poll();
  setInterval(poll, 3000);
})();
</script>
"""

SETUP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MyFA Desk</title>
<style>
:root { color-scheme: dark; --bg: #0b0d0f; --panel: #12151a; --raise: #171b21; --line: #242a31; --text: #ebe6da;
  --muted: #a29d91; --faint: #8f8a7e; --gold: #e3bd62;
  --mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
  --sans: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, Arial, sans-serif; }
html { background: var(--bg); } body { margin: 0; color: var(--text); font: 15px/1.6 var(--sans); }
::selection { background: rgba(227, 189, 98, .32); }
.wrap { max-width: 720px; margin: 0 auto; padding: 56px 28px 64px; }
h1 { margin: 0 0 6px; font-size: 26px; font-weight: 650; letter-spacing: -0.01em; } h1 span { color: var(--gold); }
.lede { margin: 0 0 28px; color: var(--muted); }
ol { margin: 0; padding-left: 22px; display: grid; gap: 14px; color: var(--muted); }
ol b { color: var(--text); font-weight: 600; }
li::marker { color: var(--gold); }
code, kbd { font: 13px var(--mono); color: var(--text); }
kbd { background: var(--raise); border: 1px solid var(--line); border-radius: 4px; padding: 1px 6px; }
.note { margin-top: 28px; color: var(--faint); font-size: 13.5px; }
</style>
</head>
<body>
__CONTROL__
<div class="wrap">
  <h1>MyFA <span>Desk</span></h1>
  <p class="lede">Runs in the background and turns your Auction House scans into targets, alerts and charts.
  This page updates by itself.</p>
  <ol>
    <li><b>Point MyFA at WoW Forever.</b> If the bar above says <em>Setup needed</em>, open Settings, press
      <em>Find it</em> or paste your <code>_forever_</code> folder, then Save.</li>
    <li><b>Log in with the MyFA addon enabled.</b> Open your bank and mailbox once on each character.</li>
    <li><b>Scan.</b> At the Auction House press <em>Full scan</em> in the MyFA panel, then type <kbd>/reload</kbd>.</li>
    <li><b>Load the targets.</b> When the bar shows your scan, type <kbd>/reload</kbd> again in game.</li>
  </ol>
  <p class="note">Leave MyFA Desk running while you play. Close it any time with Quit in the bar above.</p>
</div>
</body>
</html>
"""

if __name__ == "__main__":
    main()
