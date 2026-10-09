"""
3DXChat World Editor - local server

Serves the editor UI and the extracted asset cache, and lets the editor open/save
.world files on this PC. Listens on 127.0.0.1 only; every /api call must carry the
per-session token embedded in the page, so other websites cannot use it.

Usage:  python server.py [--port 8790] [--no-browser] [--game "<...>\\3DXChat\\Game"]
"""
import argparse
import json
import mimetypes
import os
import secrets
import shutil
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

# bundled files live in sys._MEIPASS when frozen by PyInstaller
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(HERE, "docs")
sys.path.insert(0, HERE)
from gamepath import ASSET_CACHE as DEFAULT_OUT, find_game  # noqa: E402

TOKEN = secrets.token_urlsafe(24)
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
WORLD_EXT = (".world", ".json")
extract_state = {"running": False, "log": [], "ok": None}

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/json", ".json")


def world_file_ok(path):
    return os.path.isabs(path) and path.lower().endswith(WORLD_EXT)


def run_extract(game, out):
    extract_state.update(running=True, log=[], ok=None)

    failed = [0]

    def sink(line):
        if "texture failed" in line:   # show the first few, then just count
            failed[0] += 1
            if failed[0] > 3:
                return
        extract_state["log"].append(line)
    try:
        import extract_assets  # heavy (UnityPy, numpy): only imported when needed
        extract_assets.run(game, out, sink)
        if failed[0]:
            extract_state["log"].append(f"({failed[0]} textures could not be read; those materials use their plain colour)")
        extract_state["ok"] = True
    except Exception as e:
        extract_state["log"].append(f"ERROR: {e}")
        extract_state["ok"] = False
    extract_state["running"] = False


class Handler(SimpleHTTPRequestHandler):
    server_version = "3DXWorldEditor/1.0"
    assets_dir = DEFAULT_OUT
    game_dir = ""

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))

    def translate_path(self, path):
        path = unquote(urlparse(path).path)
        if path.startswith("/assets/"):
            rel = path[len("/assets/"):]
            full = os.path.normpath(os.path.join(self.assets_dir, rel))
            if not full.startswith(os.path.normpath(self.assets_dir)):
                return os.path.join(WEB, "__nope__")
            return full
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB):
            return os.path.join(WEB, "__nope__")
        return full

    def end_headers(self):
        p = urlparse(self.path).path
        if p.startswith("/assets/") and not p.endswith("catalog.json"):
            self.send_header("Cache-Control", "max-age=86400")
        else:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ---- helpers -------------------------------------------------------
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get("X-Editor-Token") != TOKEN:
            self.send_json({"error": "forbidden"}, 403)
            return False
        return True

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n)

    # ---- routes --------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
                html = f.read().replace("__EDITOR_TOKEN__", TOKEN)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not u.path.startswith("/api/"):
            return super().do_GET()
        if not self.authorized():
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/api/status":
            cat = os.path.join(self.assets_dir, "catalog.json")
            return self.send_json({
                "assets": os.path.isfile(cat),
                "assets_dir": self.assets_dir,
                "game_dir": self.game_dir,
                "downloads": DOWNLOADS,
                "extract": extract_state,
            })
        if u.path == "/api/browse":
            d = q.get("dir") or DOWNLOADS
            if not os.path.isdir(d):
                return self.send_json({"error": f"Not a folder: {d}"}, 400)
            dirs, files = [], []
            try:
                for e in os.scandir(d):
                    if e.is_dir() and not e.name.startswith("."):
                        dirs.append(e.name)
                    elif e.is_file() and e.name.lower().endswith(WORLD_EXT):
                        st = e.stat()
                        files.append({"name": e.name, "size": st.st_size, "mtime": st.st_mtime})
            except PermissionError:
                pass
            return self.send_json({"dir": os.path.abspath(d), "parent": os.path.dirname(os.path.abspath(d)),
                                   "dirs": sorted(dirs, key=str.lower),
                                   "files": sorted(files, key=lambda f: -f["mtime"])})
        if u.path == "/api/world":
            path = q.get("path", "")
            if not world_file_ok(path) or not os.path.isfile(path):
                return self.send_json({"error": "bad path"}, 400)
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if not u.path.startswith("/api/") or not self.authorized():
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/api/world":
            path = q.get("path", "")
            if not world_file_ok(path):
                return self.send_json({"error": "Path must be absolute and end in .world"}, 400)
            data = self.body()
            try:
                json.loads(data.decode("utf-8-sig"))
            except Exception as e:
                return self.send_json({"error": f"Refusing to save invalid JSON: {e}"}, 400)
            try:
                if os.path.isfile(path):
                    shutil.copy2(path, path + ".bak")
                tmp = path + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            except OSError as e:
                hint = ""
                if getattr(e, "winerror", None) in (2, 5):
                    hint = (" Windows may be blocking python.exe here (Controlled Folder Access)."
                            " Save into Downloads, or allow python.exe in Windows Security.")
                return self.send_json({"error": f"{e}.{hint}"}, 500)
            return self.send_json({"ok": True, "path": path, "backup": path + ".bak"})
        if u.path == "/api/extract":
            if extract_state["running"]:
                return self.send_json({"error": "already running"}, 409)
            game = q.get("game") or self.game_dir
            Handler.game_dir = game
            threading.Thread(target=run_extract, args=(game, self.assets_dir), daemon=True).start()
            return self.send_json({"ok": True})
        self.send_json({"error": "not found"}, 404)


def selftest(report_path):
    """Used by the build: check bundled files, the extractor's imports and a live request."""
    import urllib.request
    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            fn()
            lines.append(f"ok   {name}")
        except Exception as e:  # noqa: BLE001 - report everything
            ok = False
            lines.append(f"FAIL {name}: {e}")

    check("web files", lambda: [open(os.path.join(WEB, p), "rb").close() for p in
                                ("index.html", "js/main.js", "vendor/three/three.module.js",
                                 "lite/catalog-lite.json", "worlds/SNL-Monopoly-version.world")])
    check("lite catalog", lambda: json.load(open(os.path.join(WEB, "lite", "catalog-lite.json"), encoding="utf-8"))["objects"]["Box"])
    check("extractor imports", lambda: __import__("extract_assets"))
    check("texture decoders", lambda: (__import__("UnityPy.export.Texture2DConverter"),
                                       __import__("texture2ddecoder").decode_bc1(bytes(8), 4, 4)))

    def serve():
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        html = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8")
        assert TOKEN in html, "token not injected"
        req = urllib.request.Request(base + "/api/status", headers={"X-Editor-Token": TOKEN})
        json.loads(urllib.request.urlopen(req, timeout=10).read())
        srv.shutdown()
    check("server", serve)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sys.exit(0 if ok else 1)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--game", default=None)
    ap.add_argument("--assets", default=DEFAULT_OUT)
    args = ap.parse_args()
    Handler.assets_dir = os.path.abspath(args.assets)
    Handler.game_dir = args.game or find_game()

    srv = None
    for port in range(args.port, args.port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit("No free port found")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"3DXChat World Editor running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
