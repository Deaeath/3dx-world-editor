"""
3DXChat World Editor - asset extractor

Reads the world-editor prefabs (meshes), materials and textures from YOUR local
3DXChat install and writes them to a local cache the editor loads:

    %LOCALAPPDATA%\\3DXWorldEditor\\assets\\catalog.json   object + material catalog
                                            meshes.bin     packed vertex/index data
                                            tex\\*.png      textures

(LocalAppData rather than this folder: Windows Controlled Folder Access often
blocks python.exe from writing under Documents.)

Only the plain (unencrypted) game data is read. Objects whose meshes are only
shipped inside the game's encrypted bundles are exported as collider-sized
proxy boxes. The cache stays on your machine - do not redistribute it.

Usage:
    python extract_assets.py [--game "<...>\\3DXChat\\Game"] [--out <dir>]
"""
import argparse
import json
import os
import re
import struct
import sys
import time

import numpy as np

try:  # UnityPy imports its audio converter (FMOD) on the texture path; we never need audio
    import fmod_toolkit  # noqa: F401
except Exception:  # not installed / left out of the exe on purpose
    import types
    sys.modules["fmod_toolkit"] = types.ModuleType("fmod_toolkit")

import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gamepath import ASSET_CACHE as DEFAULT_OUT, find_game  # noqa: E402

DEFAULT_GAME = find_game()
LOD_RE = re.compile(r"_LOD([1-9]\d*)$")
MAX_TEX = 512
# Unity is left-handed; three.js is right-handed. We mirror X: F = diag(-1, 1, 1).
FLIP = np.diag([-1.0, 1.0, 1.0, 1.0])


_sink = None  # optional callback(str) used by the editor server


def log(*a):
    msg = " ".join(str(x) for x in a)
    if _sink:
        _sink(msg)
    else:
        print(msg, flush=True)


def game_data_dir(game):
    for cand in (os.path.join(game, "3DXChat_Data"), os.path.join(game, "Game", "3DXChat_Data"), game):
        if os.path.isfile(os.path.join(cand, "resources.assets")):
            return cand
    raise FileNotFoundError(f"Could not find 3DXChat_Data/resources.assets under: {game}")


def deref(ptr):
    try:
        if ptr is None or not ptr.path_id:
            return None
        return ptr.deref()
    except Exception:
        return None


def read(ptr):
    r = deref(ptr)
    if r is None:
        return None
    try:
        return r.read()
    except Exception:
        return None


def components(go):
    out = {}
    for c in go.m_Components:
        ptr = c.component if hasattr(c, "component") else c
        r = deref(ptr)
        if r is None:
            continue
        t = r.type.name
        if t in ("Transform", "RectTransform", "MeshFilter", "MeshRenderer",
                 "SkinnedMeshRenderer", "BoxCollider", "LODGroup", "Light"):
            try:
                out.setdefault(t, []).append(r.read())
            except Exception:
                pass
        else:
            out.setdefault(t, []).append(None)
    return out


def trs_matrix(tr):
    p, q, s = tr.m_LocalPosition, tr.m_LocalRotation, tr.m_LocalScale
    x, y, z, w = q.x, q.y, q.z, q.w
    r = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    m = np.eye(4)
    m[:3, :3] = r * np.array([s.x, s.y, s.z])
    m[:3, 3] = [p.x, p.y, p.z]
    return m


def walk(go, parent_m, root=True):
    """Yield (go, comps, matrix relative to prefab root, depth-name) for the hierarchy."""
    c = components(go)
    tr = (c.get("Transform") or c.get("RectTransform") or [None])[0]
    m = np.eye(4) if root else parent_m @ trs_matrix(tr) if tr else parent_m
    yield go, c, m
    if tr:
        for ch in tr.m_Children:
            t = read(ch)
            if t is None:
                continue
            g = read(t.m_GameObject)
            if g is not None:
                yield from walk(g, m, False)


def lod0_renderers(c):
    """Path ids of renderers in LOD0 of a LODGroup (or None if not available)."""
    for lg in c.get("LODGroup") or []:
        if lg is None or not getattr(lg, "m_LODs", None):
            continue
        try:
            return {r.renderer.path_id for r in lg.m_LODs[0].renderers}
        except Exception:
            return None
    return None


class MeshStore:
    def __init__(self):
        self.chunks = []
        self.offset = 0
        self.meshes = []
        self.by_key = {}

    def _put(self, arr):
        b = arr.tobytes()
        pad = (-len(b)) % 4
        off = self.offset
        self.chunks.append(b + b"\0" * pad)
        self.offset += len(b) + pad
        return off

    def add(self, mesh_reader):
        key = (mesh_reader.assets_file.name, mesh_reader.path_id)
        if key in self.by_key:
            return self.by_key[key]
        mesh = mesh_reader.read()
        h = MeshHandler(mesh)
        h.process()
        if not h.m_Vertices or not h.m_VertexCount:
            self.by_key[key] = None
            return None
        n = h.m_VertexCount

        def channel(data, comps):
            """Vertex channel as float32 (n, comps); channels may be stored with extra components."""
            if not data:
                return None
            a = np.asarray(data, dtype=np.float32).reshape(-1)
            if a.size % n or a.size // n < comps:
                return None
            return np.ascontiguousarray(a.reshape(n, -1)[:, :comps])

        pos = channel(h.m_Vertices, 3)
        if pos is None:
            self.by_key[key] = None
            return None
        pos[:, 0] *= -1
        nrm = channel(h.m_Normals, 3)
        if nrm is not None:
            nrm[:, 0] *= -1
        uv = channel(h.m_UV0, 2)
        groups, idx = [], []
        for slot, tris in enumerate(h.get_triangles()):
            t = np.asarray(tris, dtype=np.uint32).reshape(-1, 3)[:, ::-1]  # mirrored -> reverse winding
            groups.append([sum(len(i) for i in idx), t.size, slot])
            idx.append(t.reshape(-1))
        idx = np.concatenate(idx) if idx else np.zeros(0, np.uint32)
        lo, hi = pos.min(0), pos.max(0)
        rec = {
            "name": mesh.m_Name,
            "v": int(len(pos)),
            "i": int(idx.size),
            "pos": self._put(pos),
            "nrm": self._put(nrm) if nrm is not None else -1,
            "uv": self._put(uv) if uv is not None else -1,
            "idx": self._put(idx.astype(np.uint32)),
            "groups": groups,
            "box": [lo.tolist(), hi.tolist()],
        }
        self.meshes.append(rec)
        mid = len(self.meshes) - 1
        self.by_key[key] = mid
        return mid

    def write(self, path):
        with open(path, "wb") as f:
            for c in self.chunks:
                f.write(c)


def material_kind(shader, keywords):
    s = (shader or "").lower()
    if "triplanar" in s:
        return "triplanar"
    if "glass" in s:
        return "glass"
    if "illum" in s:
        return "illum"
    if "hologram" in s:
        return "hologram"
    if "unlit" in s:
        return "unlit"
    if "water" in s:
        return "water"
    if "transp" in s or "fade" in s:
        return "transparent"
    return "standard"


def export_texture(tex_reader, out_dir, cache):
    key = (tex_reader.assets_file.name, tex_reader.path_id)
    if key in cache:
        return cache[key]
    fn = None
    try:
        t = tex_reader.read()
        img = t.image
        if img is not None and img.width > 0:
            if max(img.size) > MAX_TEX:
                img.thumbnail((MAX_TEX, MAX_TEX))
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", t.m_Name)[:60]
            base = f"{safe}_{tex_reader.path_id & 0xffffffff:x}"
            if img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 250:
                fn = base + ".png"
                img.save(os.path.join(out_dir, fn))
            else:
                fn = base + ".jpg"
                img.convert("RGB").save(os.path.join(out_dir, fn), quality=88)
    except Exception as e:
        log("   texture failed:", key, e)
    cache[key] = fn
    return fn


def shader_name(m):
    sh = read(m.m_Shader)
    if sh is None:
        return None
    try:
        return sh.m_ParsedForm.m_Name
    except Exception:
        return getattr(sh, "m_Name", None)


def export_material(m, tex_dir, tex_cache):
    shader = shader_name(m)
    kw = list(getattr(m, "m_ValidKeywords", None) or [])
    if not kw:
        kw = (getattr(m, "m_ShaderKeywords", "") or "").split()
    sp = m.m_SavedProperties
    floats = {k: float(v) for k, v in sp.m_Floats}
    colors = {k: [v.r, v.g, v.b, v.a] for k, v in sp.m_Colors}
    tex, tiling = {}, {}
    for k, v in sp.m_TexEnvs:
        if k in ("_MainTex", "_BaseMap", "_MainTex1", "_MainTex2") and v.m_Texture.path_id:
            r = deref(v.m_Texture)
            if r is not None and r.type.name == "Texture2D":
                fn = export_texture(r, tex_dir, tex_cache)
                if fn:
                    tex[k] = fn
                    tiling[k] = [v.m_Scale.x, v.m_Scale.y, v.m_Offset.x, v.m_Offset.y]
    mode = next((k[6:].lower() for k in kw if k.startswith("_MODE_")), None)
    return {
        "shader": shader,
        "kind": material_kind(shader, kw),
        "mode": mode,
        "keywords": kw,
        "color": colors.get("_Color") or colors.get("_BaseColor") or [1, 1, 1, 1],
        "emission": colors.get("_EmissionColor", [0, 0, 0, 1]),
        "gloss": floats.get("_Glossiness", floats.get("_Smoothness", 0.5)),
        "metal": floats.get("_Metallic", 0.0),
        "mode_f": floats.get("_Mode", 0.0),
        "tex": tex,
        "tiling": tiling,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=DEFAULT_GAME)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    try:
        run(args.game, args.out)
    except FileNotFoundError as e:
        sys.exit(str(e))


def run(game, out, sink=None):
    global _sink
    _sink = sink
    data = game_data_dir(game)
    out = os.path.abspath(out)
    tex_dir = os.path.join(out, "tex")
    os.makedirs(tex_dir, exist_ok=True)

    t0 = time.time()
    log(f"Loading game data from {data} (this takes a minute)...")
    env = UnityPy.load(data)
    log(f"  loaded in {time.time() - t0:.0f}s")

    roots, meshes_by_name, materials = {}, {}, {}
    for o in env.objects:
        t = o.type.name
        if t not in ("GameObject", "Mesh", "Material"):
            continue
        try:
            name = o.peek_name()
        except Exception:
            continue
        if t == "Mesh":
            meshes_by_name.setdefault(name, o)
        elif t == "Material":
            if o.assets_file.name == "resources.assets":
                materials.setdefault(name, []).append(o)
        elif o.assets_file.name == "resources.assets" and not LOD_RE.search(name):
            roots.setdefault(name, []).append(o)

    store = MeshStore()
    tex_cache = {}
    catalog_objects, used_mats = {}, set()
    n_real = n_proxy = 0
    log(f"Scanning {len(roots)} candidate prefabs...")
    for name in sorted(roots):
        best = None
        for o in roots[name]:
            try:
                go = o.read()
            except Exception:
                continue
            c = components(go)
            tr = (c.get("Transform") or [None])[0]
            if tr is None or (tr.m_Father is not None and tr.m_Father.path_id):
                continue  # not a prefab root
            if not (c.get("BoxCollider") or c.get("LODGroup") or c.get("MeshFilter")):
                continue
            parts, collider, kind = [], None, "mesh"
            lod0 = lod0_renderers(c)
            nodes = list(walk(go, np.eye(4)))
            # collider (proxy bounds): root BoxCollider, else the LODGroup's object size
            bcs = c.get("BoxCollider") or []
            if bcs and bcs[0] is not None:
                ce, sz = bcs[0].m_Center, bcs[0].m_Size
                collider = {"c": [-ce.x, ce.y, ce.z], "s": [abs(sz.x), abs(sz.y), abs(sz.z)]}
            else:
                for lg in c.get("LODGroup") or []:
                    if lg is not None and getattr(lg, "m_Size", 0):
                        rp = lg.m_LocalReferencePoint
                        collider = {"c": [-rp.x, rp.y, rp.z], "s": [lg.m_Size] * 3, "approx": True}
            for g, gc, m in nodes:
                if gc.get("Light"):
                    kind = "light"
                elif "ParticleSystem" in gc and kind == "mesh":
                    kind = "effect"

            def renderer_id(g):
                for cc in g.m_Components:
                    ptr = cc.component if hasattr(cc, "component") else cc
                    r = deref(ptr)
                    if r is not None and r.type.name == "MeshRenderer":
                        return r.path_id

            candidates = []
            for g, gc, m in nodes:
                if LOD_RE.search(g.m_Name) or not getattr(g, "m_IsActive", True):
                    continue
                mfs = gc.get("MeshFilter") or []
                mrs = gc.get("MeshRenderer") or []
                if not mfs or not mrs or mfs[0] is None or mrs[0] is None:
                    continue
                if not getattr(mrs[0], "m_Enabled", 1):
                    continue
                candidates.append((g, mfs[0], mrs[0], m, renderer_id(g)))
            if lod0:
                in_lod0 = [cd for cd in candidates if cd[4] in lod0]
                candidates = in_lod0 or candidates  # e.g. lights: LOD0 holds only particles
            for g, mf, mr, m, _ in candidates:
                mesh_r = deref(mf.m_Mesh)
                if mesh_r is None:
                    # mesh only exists inside the encrypted bundles; try a same-named plain mesh
                    mesh_r = meshes_by_name.get(name + "_LOD0") or meshes_by_name.get(name)
                    if mesh_r is None:
                        continue
                mid = store.add(mesh_r)
                if mid is None:
                    continue
                mats = []
                for mp in mr.m_Materials:
                    mm = deref(mp)
                    mn = None
                    if mm is not None:
                        try:
                            mn = mm.peek_name()
                        except Exception:
                            pass
                    mats.append(mn)
                    if mn:
                        used_mats.add(mn)
                mm3 = FLIP @ m @ FLIP
                parts.append({"mesh": mid, "mats": mats, "m": [round(float(v), 6) for v in mm3.T.reshape(-1)]})
            entry = {"parts": parts, "collider": collider, "kind": kind}
            # prefer the variant with geometry; among equals prefer the 'primitive' material
            score = (len(parts) > 0, any("primitive" in (p["mats"] or [None]) for p in parts))
            if best is None or score > best[0]:
                best = (score, entry)
        if best is None:
            continue
        entry = best[1]
        if not entry["parts"] and not entry["collider"]:
            entry["collider"] = {"c": [0, 0, 0], "s": [1, 1, 1], "approx": True}
        entry["proxy"] = not entry["parts"]
        n_real += not entry["proxy"]
        n_proxy += entry["proxy"]
        catalog_objects[name] = entry

    log(f"  objects: {n_real} with real meshes, {n_proxy} proxies; {len(store.meshes)} meshes")

    log("Exporting materials + textures...")
    catalog_mats = {}
    for name, objs in sorted(materials.items()):
        try:
            m = objs[0].read()
            if not ("HOME_EDITOR" in (shader_name(m) or "") or name in used_mats or name == "unlit"):
                continue  # not a world-editor material
            catalog_mats[name] = export_material(m, tex_dir, tex_cache)
        except Exception as e:
            log("   material failed:", name, e)
    log(f"  materials: {len(catalog_mats)}, textures: {sum(1 for v in tex_cache.values() if v)}")

    store.write(os.path.join(out, "meshes.bin"))
    with open(os.path.join(out, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({
            "version": 1,
            "source": data,
            "extracted": time.strftime("%Y-%m-%d %H:%M:%S"),
            "objects": catalog_objects,
            "meshes": store.meshes,
            "materials": catalog_mats,
        }, f, separators=(",", ":"))
    log(f"Done in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
