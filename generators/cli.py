"""Command line for the world kit (used by the Runix driver and scripts). Every command prints one JSON object.

  python cli.py list
  python cli.py generate <only_up|squid_game|slutopoly> --out PATH [--seed N] [--upto N] [--config FILE.json]
  python cli.py validate PATH
  python cli.py fix PATH <fix id> [--out PATH] [--options JSON]
  python cli.py info PATH
  python cli.py poses PATH
  python cli.py config slutopoly           (the default board text, to edit and pass back with --config)
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worldkit  # noqa: E402


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(world, path):
    data = json.dumps(world, separators=(",", ":"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)
    return len(data)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="worldkit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    g = sub.add_parser("generate")
    g.add_argument("generator")
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int)
    g.add_argument("--upto", type=int)
    g.add_argument("--config", help="JSON file of Slutopoly config overrides")
    for name in ("validate", "info", "poses"):
        sub.add_parser(name).add_argument("path")
    f = sub.add_parser("fix")
    f.add_argument("path")
    f.add_argument("fix")
    f.add_argument("--out")
    f.add_argument("--options", default="{}")
    c = sub.add_parser("config")
    c.add_argument("generator")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        out = {"generators": worldkit.list_generators(), "fixes": worldkit.list_fixes()}
    elif a.cmd == "generate":
        opts = {k: v for k, v in (("seed", a.seed), ("upto", a.upto)) if v is not None}
        if a.config:
            opts["config"] = load(a.config)
        res = worldkit.generate(a.generator, opts)
        size = save(res["world"], a.out)
        out = {"ok": True, "path": os.path.abspath(a.out), "bytes": size, "summary": res["summary"]}
    elif a.cmd == "validate":
        res = worldkit.validate(load(a.path))
        out = {"ok": not res["problems"], **res}
    elif a.cmd == "info":
        out = worldkit.stats(load(a.path))
    elif a.cmd == "poses":
        out = {"poses": worldkit.pose_zones(load(a.path))}
    elif a.cmd == "fix":
        res = worldkit.apply_fix(load(a.path), a.fix, json.loads(a.options))
        dest = a.out or a.path
        if dest == a.path:
            shutil.copy2(a.path, a.path + ".bak")          # same as the editor's Save: keep the previous file
        save(res["world"], dest)
        out = {"ok": True, "path": os.path.abspath(dest), "report": res["report"]}
    else:
        out = {"config": worldkit.default_config(a.generator)}
    print(json.dumps(out))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)
