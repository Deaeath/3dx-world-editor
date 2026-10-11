"""World kit: the generators, checks and fix-it tools behind one small API.

The desktop server, the website (Pyodide in a Web Worker), the AI chat builder's tools and the Runix driver
all call these functions, so every surface builds and repairs worlds the same way.

    list_generators()                       -> [{id, name, description, options}]
    generate(gen_id, options)               -> {"world": {...}, "summary": {...}, "log": "..."}
    validate(world)                         -> {"stats": {...}, "portals": {...}, "problems": [...]}
    list_fixes()                            -> [{id, name, description, options}]
    apply_fix(world, fix_id, options)       -> {"world": {...}, "report": {...}}
    pose_zones(world)                       -> [{name, p, heading, front}]
"""
import contextlib
import copy
import io
import math
from collections import Counter

import numpy as np

UP = np.array([0.0, 1.0, 0.0])
PRIMITIVES = {"Box", "Cylinder", "Tube", "Sphere", "Cone", "Pyramid", "Hex", "Torus", "Arch", "Wedge", "Plane"}
LIGHTS = {"LightP", "LightS", "LightD", "Light"}
GLOW_DEFAULT = [0.3, 0.8, 1.0]


# ===================================================================== helpers
def flatten(groups):
    for g in groups:
        if g.get("n") == "group" or "objects" in g:
            yield from flatten(g.get("objects", []))
        else:
            yield g


def is_pose(name):
    """Pose zones: the *_ph markers and the furniture that carries its own poses."""
    return name.endswith("_ph") or name.endswith("_poses")


def yaw_of(o):
    """Heading of an upright object (r = [270, yaw, 0], as the generators write it); 0 when it is tilted."""
    r = o.get("r") or [0, 0, 0]
    if abs((r[0] % 360) - 270) < 1 and abs(r[2] % 360) < 1:
        return float(r[1]) % 360
    if abs(r[0] % 360) < 1 and abs(r[2] % 360) < 1:   # hand-placed: plain yaw about Y
        return float(r[1]) % 360
    return 0.0


def fwd(heading):
    h = math.radians(heading)
    return np.array([math.sin(h), 0.0, math.cos(h)])


def rf(v):
    return [round(float(x), 4) for x in v]


def _capture(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn(*a, **k)
    return res, buf.getvalue()


# ================================================================== generators
SLUT_FIXED = {"have_you_ever": 22, "poses": 6, "groups": 8}


def _font_chars():
    import slutopoly
    return set(slutopoly.FONT)


def _clean_text(s, chars, warnings, where):
    """Board text is a pixel font of capitals and some punctuation: upper-case it and swap what it can't draw."""
    swaps = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
             "*": "", "#": "", "@": "AT", "%": " PERCENT", "_": " ", "[": "(", "]": ")", "{": "(", "}": ")", "~": "-"}
    out = []
    for ch in str(s).upper():
        if ch == "\n" or ch in chars:
            out.append(ch)
        elif ch in swaps:
            out.append(swaps[ch])
        else:
            warnings.add(f"{where}: dropped '{ch}' (the board font can't draw it)")
    return "".join(out).strip()


def slutopoly_config(overrides=None):
    """Default Slutopoly config with `overrides` merged in and checked. Returns (cfg, warnings)."""
    import slutopoly
    cfg = copy.deepcopy(slutopoly.DEFAULT)
    warnings = set()
    chars = _font_chars()
    for k, v in (overrides or {}).items():
        if k not in cfg:
            warnings.add(f"unknown config key '{k}' ignored")
            continue
        cfg[k] = copy.deepcopy(v)
    for k, n in SLUT_FIXED.items():
        if len(cfg[k]) != n:
            raise ValueError(f"Slutopoly needs exactly {n} entries in '{k}' (got {len(cfg[k])})")
    for p in cfg["poses"]:
        if str(p).split()[0].upper() not in ("BED", "COUCH", "BENCH"):
            raise ValueError(f"each pose must start with BED, COUCH or BENCH (got '{p}')")
    for k, v in cfg.items():
        if isinstance(v, str):
            cfg[k] = _clean_text(v, chars, warnings, k)
        elif k == "rules":
            cfg[k] = [[ic, _clean_text(t, chars, warnings, k)] for ic, t in v]
        elif k == "groups":
            cfg[k] = [[_clean_text(name, chars, warnings, k), [float(c) for c in col][:3]] for name, col in v]
        elif isinstance(v, list):
            cfg[k] = [_clean_text(t, chars, warnings, k) for t in v]
    return cfg, sorted(warnings)


def _gen_only_up(opts):
    import only_up
    seed = int(opts.get("seed", 7))
    (world, w, route, top, stuck), log = _capture(only_up.build, seed)
    summary = {"objects": w.count, "summit_m": round(float(top)), "stuck_zones": stuck}
    route_info, log2 = _capture(only_up.check, route)
    summary["route"] = route_info
    return world, summary, log + log2


def _gen_squid_game(opts):
    import squid_game
    seed = int(opts.get("seed", 7))
    upto = opts.get("upto")
    (world, sg, info, pairs), log = _capture(squid_game.build, seed, int(upto) if upto else None)
    info = dict(info)
    safe = info.pop("glass_safe", None)
    summary = {"objects": sg.w.count, "portal_pairs": pairs, "objects_per_stage": info}
    if safe is not None:
        summary["glass_bridge_safe_side"] = "".join("L" if v < 0 else "R" for v in safe)
    return world, summary, log


def _gen_slutopoly(opts):
    import slutopoly
    cfg, warnings = slutopoly_config(opts.get("config"))
    (world, w), log = _capture(slutopoly.build, cfg)
    return world, {"objects": w.count, "warnings": warnings}, log


GENERATORS = {
    "only_up": {
        "name": "Only Up!",
        "description": "A 1500 m tower climb, walkable all the way up without jumping, with a teleporter plaza "
                       "and checkpoints. Takes a while to build (route search).",
        "options": {"seed": {"type": "integer", "default": 7, "description": "Changes the route and scenery."}},
        "build": _gen_only_up,
    },
    "squid_game": {
        "name": "Squid Game",
        "description": "Every game from all three seasons plus the subway, dorm, stair maze and coffin room, "
                       "with rules boards and hexagon portals between them.",
        "options": {
            "seed": {"type": "integer", "default": 7, "description": "Changes the random details (glass bridge, marbles...)."},
            "upto": {"type": "integer", "description": "Only build the first N stages (1-15), for quick previews."},
        },
        "build": _gen_squid_game,
    },
    "slutopoly": {
        "name": "Slutopoly",
        "description": "Adult party board game (truth or dare, role play, poses) with an elevated lobby bar, "
                       "bedrooms and a Game Master martini glass. Every board text can be changed.",
        "options": {
            "config": {"type": "object", "description":
                       "Overrides for the board text. Keys: title, rules_title, rules_intro (list), rules "
                       "(list of [icon, text]), have_you_ever_title, have_you_ever (exactly 22), tell_title, tell "
                       "(list), roll_play_title, roll_play (list), groups (exactly 8 [name, [r,g,b]]), poses "
                       "(exactly 6, each starting BED, COUCH or BENCH). Text is drawn in capitals."},
        },
        "build": _gen_slutopoly,
    },
}


def list_generators():
    return [{"id": k, **{f: v[f] for f in ("name", "description", "options")}} for k, v in GENERATORS.items()]


def generate(gen_id, options=None):
    if gen_id not in GENERATORS:
        raise ValueError(f"unknown generator '{gen_id}' (have: {', '.join(GENERATORS)})")
    world, summary, log = GENERATORS[gen_id]["build"](options or {})
    summary["credit"] = "By KingColossus"
    return {"world": world, "summary": summary, "log": log}


def default_config(gen_id):
    if gen_id != "slutopoly":
        return {}
    import slutopoly
    return copy.deepcopy(slutopoly.DEFAULT)


# ===================================================================== checks
def stats(world):
    objs = list(flatten(world.get("objects", [])))
    names = Counter(o.get("n", "?") for o in objs)
    mats = Counter(o.get("m", "") for o in objs if o.get("m"))
    ps = np.array([o.get("p", [0, 0, 0]) for o in objs], float) if objs else np.zeros((1, 3))
    return {
        "objects": len(objs),
        "groups": len(world.get("objects", [])),
        "portals": names.get("portal", 0),
        "pose_zones": sum(v for k, v in names.items() if is_pose(k)),
        "lights": sum(v for k, v in names.items() if k in LIGHTS),
        "bounds": {"min": rf(ps.min(0)), "max": rf(ps.max(0))},
        "top_objects": names.most_common(15),
        "top_materials": mats.most_common(10),
        "respawn": world.get("respawn"),
    }


def validate(world):
    """Stats plus every check that applies to any world. Problems (broken things) and notes (style
    suggestions) are plain sentences."""
    import validate_portals
    st = stats(world)
    problems = []
    pairs, portal_problems = validate_portals.check(world) if st["portals"] else (0, [])
    problems += portal_problems
    objs = list(flatten(world.get("objects", [])))
    washed = [o for o in objs if o.get("m") == "Illum FLAT" and o.get("n") in PRIMITIVES and not _whiteish(o)]
    notes = []
    if washed:
        notes.append(f"{len(washed)} coloured primitives use 'Illum FLAT'. It glows, which suits neon signs, but "
                     f"it washes pastel colours out to white in game; if they aren't meant to glow, the "
                     f"'flat_colours' fix swaps them to 'unlit'.")
    visible = [o for o in objs if o.get("n") == "portal" and o.get("m") != "discard"]
    if visible:
        notes.append(f"{len(visible)} portal models are visible; the 'portal_glow' fix hides them and marks "
                     f"each with a glowing hexagon instead.")
    if not world.get("respawn"):
        problems.append("no respawn point")
    for o in objs:
        s = o.get("s") or [1, 1, 1]
        if any(abs(v) < 1e-6 for v in s):
            problems.append(f"zero scale on {o.get('n')} at {o.get('p')}")
            break
    return {"stats": st, "portals": {"pairs": pairs, "problems": portal_problems}, "problems": problems, "notes": notes}


def _whiteish(o):
    c = o.get("c") or [1, 1, 1]
    return min(c[:3]) >= 0.95


def pose_zones(world):
    """Each pose zone and the way its poses face: the model's local +X axis (the generators place one with
    heading h so that its poses face fwd(h - 90)). `heading` is that h."""
    from validate_route import euler_matrix
    out = []
    for o in flatten(world.get("objects", [])):
        n = o.get("n", "")
        if is_pose(n):
            front = euler_matrix(o.get("r") or (0, 0, 0)) @ np.array([1.0, 0.0, 0.0])
            heading = (math.degrees(math.atan2(front[0], front[2])) + 90) % 360
            out.append({"name": n, "p": o.get("p"), "heading": round(heading, 1), "front": rf(front)})
    return out


def text_objects(text, at, heading=0.0, height=0.4, color=(1, 1, 1), material="unlit", backing=None):
    """A standing pixel-font sign: `at` is the bottom centre, read by someone looking along `heading`
    (fwd(heading) = (sin, 0, cos)); `height` is the capital height in metres. Returns (objects, warnings)."""
    import slutopoly
    from only_up import World, right_of
    warnings = set()
    text = _clean_text(text, _font_chars(), warnings, "text")
    if not text:
        raise ValueError("nothing to write (the board font draws A-Z, 0-9 and simple punctuation)")
    px = float(height) / 7
    lines = text.split("\n")
    total_h = (len(lines) * 8 - 1) * px
    F, R = fwd(heading), right_of(heading)
    mid = np.asarray(at, float) + UP * (total_h / 2 + (0.15 if backing else 0.0))
    w = World(0)
    w.begin()
    if backing:                                   # a board just behind the letters, standing on `at`
        Wd = max(len(l) for l in lines) * 6 * px + 0.3
        w.obj("Box", mid + F * 0.03 - UP * (total_h / 2 + 0.15), *_upright(F), (Wd, 0.06, total_h + 0.3),
              "unlit", tuple(backing))
    slutopoly.write(w, text, mid, R, UP, -F, px, tuple(color), material, thick=max(0.01, px * 0.3))
    return w.groups[0]["objects"], sorted(warnings)


def _upright(F):
    """Axes for an upright box whose depth (local Y) runs along F."""
    return np.cross(F, UP), F, UP.copy()


# ======================================================================= fixes
def _fix_hide_portal_models(world, opts):
    n = 0
    for o in flatten(world["objects"]):
        if o.get("n") == "portal" and o.get("m") != "discard":
            o["m"] = "discard"
            n += 1
    return {"hidden": n}


def _fix_portal_glow(world, opts):
    """A translucent glowing hexagon on the floor under every portal, plus a light above it; hides the models."""
    from validate_route import Solids
    color = rf(opts.get("color") or GLOW_DEFAULT)
    objs = list(flatten(world["objects"]))
    S = Solids(objs)
    hexes = [np.array(o["p"], float) for o in objs if o.get("n") == "Hex" and o.get("m") == "Hologram2"]
    group = {"n": "group", "objects": []}
    added = skipped = 0
    for o in objs:
        if o.get("n") != "portal":
            continue
        p = np.array(o.get("p", [0, 0, 0]), float)
        floor = p.copy()
        for dy in np.arange(0.0, 1.2, 0.05):           # sit on whatever is under it (arrival pads float 0.5 m)
            if S.at(p - UP * (dy + 0.03)) is not None:
                floor = p - UP * dy
                break
        if any(abs(h[1] - floor[1]) < 0.3 and math.hypot(*(h - floor)[[0, 2]]) < 0.4 for h in hexes):
            skipped += 1
            continue
        yaw = yaw_of(o)
        group["objects"].append({"n": "Hex", "p": rf(floor + UP * 0.005), "r": [270.0, yaw, 0.0],
                                 "s": [1.4, 1.4, 0.05], "c": color, "m": "Hologram2"})
        group["objects"].append({"n": "LightP", "p": rf(floor + UP * 0.8), "r": [270.0, yaw, 0.0],
                                 "s": [1.0, 1.0, 1.0], "c": color})
        hexes.append(floor)
        added += 1
    if group["objects"]:
        world["objects"].append(group)
    hidden = _fix_hide_portal_models(world, opts)["hidden"] if opts.get("hide_models", True) else 0
    return {"glows_added": added, "already_marked": skipped, "models_hidden": hidden}


def _fix_flat_colours(world, opts):
    keep_white = opts.get("keep_white", True)
    n = 0
    for o in flatten(world["objects"]):
        if o.get("m") == "Illum FLAT" and o.get("n") in PRIMITIVES and not (keep_white and _whiteish(o)):
            o["m"] = "unlit"
            n += 1
    return {"changed": n}


def _fix_respawn(world, opts):
    """Put the respawn at the given point, or over the middle of the build if it has none."""
    if opts.get("p"):
        world["respawn"] = {"p": rf(opts["p"]), "r": float(opts.get("r", 0))}
        return {"respawn": world["respawn"]}
    if world.get("respawn"):
        return {"respawn": world["respawn"], "changed": False}
    objs = list(flatten(world["objects"]))
    ps = np.array([o.get("p", [0, 0, 0]) for o in objs], float) if objs else np.zeros((1, 3))
    c = np.median(ps, 0)
    world["respawn"] = {"p": rf([c[0], ps[:, 1].min() + 1.0, c[2]]), "r": 0.0}
    return {"respawn": world["respawn"], "changed": True}


FIXES = {
    "portal_glow": {
        "name": "Hexagon portals",
        "description": "Hides every portal model and marks each portal with a translucent glowing hexagon on the "
                       "floor and a light above it (skips portals that already have one).",
        "options": {"color": {"type": "array", "description": "Glow colour [r, g, b] 0-1.", "default": GLOW_DEFAULT},
                    "hide_models": {"type": "boolean", "default": True}},
        "run": _fix_portal_glow,
    },
    "hide_portal_models": {
        "name": "Hide portal models",
        "description": "Makes portal models invisible (material 'discard'); they still teleport.",
        "options": {},
        "run": _fix_hide_portal_models,
    },
    "flat_colours": {
        "name": "Flat colours",
        "description": "Swaps 'Illum FLAT' on coloured primitives for 'unlit', which keeps pastel colours "
                       "instead of washing them out to white in game.",
        "options": {"keep_white": {"type": "boolean", "default": True,
                                   "description": "Leave white ones alone (usually lamps)."}},
        "run": _fix_flat_colours,
    },
    "respawn": {
        "name": "Respawn point",
        "description": "Sets the respawn to a given point, or adds one over the build if it has none.",
        "options": {"p": {"type": "array", "description": "[x, y, z] in game coordinates."},
                    "r": {"type": "number", "description": "Facing in degrees."}},
        "run": _fix_respawn,
    },
}


def list_fixes():
    return [{"id": k, **{f: v[f] for f in ("name", "description", "options")}} for k, v in FIXES.items()]


def apply_fix(world, fix_id, options=None):
    if fix_id not in FIXES:
        raise ValueError(f"unknown fix '{fix_id}' (have: {', '.join(FIXES)})")
    world = copy.deepcopy(world)
    world.setdefault("objects", [])
    report = FIXES[fix_id]["run"](world, options or {})
    return {"world": world, "report": report}
