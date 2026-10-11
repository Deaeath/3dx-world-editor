"""Pack the world kit (generators/*.py + glyphs.json) into docs/py/worldkit.zip for the website, which runs it
in Pyodide. Run after changing anything in generators/; `python make_web_kit.py --check` fails if it is stale.
"""
import hashlib
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "generators")
OUT = os.path.join(ROOT, "docs", "py")
FILES = ["worldkit.py", "only_up.py", "squid_game.py", "slutopoly.py", "validate_route.py", "validate_portals.py",
         "glyphs.json"]


def build():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            with open(os.path.join(SRC, name), "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))   # fixed time: same input, same zip
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    data = buf.getvalue()
    return data, {"sha256": hashlib.sha256(data).hexdigest()[:16], "files": FILES}


def main():
    data, manifest = build()
    zpath, mpath = os.path.join(OUT, "worldkit.zip"), os.path.join(OUT, "worldkit.json")
    if "--check" in sys.argv:
        try:
            current = json.load(open(mpath, encoding="utf-8"))["sha256"]
        except (OSError, KeyError, ValueError):
            current = None
        if current != manifest["sha256"]:
            sys.exit("docs/py/worldkit.zip is out of date: run python make_web_kit.py")
        print("web kit up to date", manifest["sha256"])
        return
    os.makedirs(OUT, exist_ok=True)
    with open(zpath, "wb") as f:
        f.write(data)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    print(f"wrote {zpath} ({len(data) // 1024} KB, {manifest['sha256']})")


if __name__ == "__main__":
    main()
