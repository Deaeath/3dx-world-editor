"""
Build docs/lite/catalog-lite.json from an extracted asset cache.

The lite catalog is what the web version uses when no game is linked. It holds
no game meshes or textures: only each object's name, kind and bounding box, and
each material's kind, colour, gloss and a single average colour. The editor
draws basic shapes (Box, arches, cylinders, ...) with its own generated geometry
and everything else as sized boxes.

Usage:  python make_lite_catalog.py [--assets <extracted cache>]
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

from gamepath import ASSET_CACHE

HERE = os.path.dirname(os.path.abspath(__file__))


def bounds(cat, o):
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for p in o["parts"]:
        m = cat["meshes"][p["mesh"]]
        M = np.array(p["m"]).reshape(4, 4).T
        a, b = np.array(m["box"][0]), np.array(m["box"][1])
        for c in [(x, y, z) for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])]:
            w = M @ np.array([*c, 1.0])
            lo, hi = np.minimum(lo, w[:3]), np.maximum(hi, w[:3])
    if not np.isfinite(lo).all():
        c = o.get("collider") or {"c": [0, 0, 0], "s": [1, 1, 1]}
        return {"c": c["c"], "s": [max(v, 0.02) for v in c["s"]]}
    return {"c": ((lo + hi) / 2).round(4).tolist(), "s": np.maximum(hi - lo, 0.02).round(4).tolist()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=ASSET_CACHE)
    args = ap.parse_args()
    cat = json.load(open(os.path.join(args.assets, "catalog.json"), encoding="utf-8"))

    objects = {}
    for name, o in cat["objects"].items():
        objects[name] = {"kind": o["kind"], "b": bounds(cat, o)}

    materials = {}
    for name, m in cat["materials"].items():
        rec = {k: m[k] for k in ("kind", "mode", "color", "gloss", "metal") if k in m}
        tex = (m.get("tex") or {})
        f = tex.get("_MainTex") or tex.get("_BaseMap") or tex.get("_MainTex1")
        if f:
            try:
                im = Image.open(os.path.join(args.assets, "tex", f)).convert("RGB").resize((8, 8))
                rec["avg"] = [round(float(v) / 255, 3) for v in np.asarray(im).reshape(-1, 3).mean(0)]
            except OSError:
                pass
        materials[name] = rec

    out = os.path.join(HERE, "docs", "lite", "catalog-lite.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "lite": True, "objects": objects, "materials": materials}, f, separators=(",", ":"))
    print(f"{len(objects)} objects, {len(materials)} materials -> {out} ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
