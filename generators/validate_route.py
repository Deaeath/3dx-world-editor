"""Independent walkability check for only_up.py: rebuilds the world, turns every primitive back into its real
shape from the written transform (p, Unity Euler r, s) and walks the route's centre line every 0.5 m:

  * support   - something solid within 0.2 m under your feet
  * head-room - nothing inside a 0.5 m wide, 1.9 m tall body standing there

Usage: python validate_route.py [--seed N]
"""
import math
import sys
from collections import defaultdict

import numpy as np

import only_up as ou

CELL = 4.0


def euler_matrix(r):
    x, y, z = (math.radians(a) for a in r)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


def inside(name, u):
    x, y, z = u
    if name == "Box":
        return abs(x) <= 0.5 and abs(y) <= 0.5 and 0 <= z <= 1
    if name in ("Cylinder", "Tube"):
        return x * x + y * y <= 0.25 and 0 <= z <= 1
    if name == "Sphere":
        return x * x + y * y + (z - 0.5) ** 2 <= 0.25
    if name == "Cone":
        return 0 <= z <= 1 and math.hypot(x, y) <= 0.5 * (1 - z)
    if name == "Pyramid":
        return 0 <= z <= 1 and max(abs(x), abs(y)) <= 0.5 * (1 - z)
    return False


class Solids:
    def __init__(self, objects):
        self.items, self.cells = [], defaultdict(list)
        for o in objects:
            if o["n"] not in ("Box", "Cylinder", "Tube", "Sphere", "Cone", "Pyramid"):
                continue
            R = euler_matrix(o.get("r") or (0, 0, 0))
            p, s = np.array(o.get("p") or (0, 0, 0), float), np.array(o.get("s") or (1, 1, 1), float)
            if not np.all(np.abs(s) > 1e-9):
                continue
            corners = np.array([p + R @ (np.array([a, b, c]) * s) for a in (-.5, .5) for b in (-.5, .5) for c in (0, 1)])
            lo, hi = corners.min(0), corners.max(0)
            idx = len(self.items)
            self.items.append((o["n"], p, R, s))
            for i in range(int(lo[0] // CELL), int(hi[0] // CELL) + 1):
                for j in range(int(lo[1] // CELL), int(hi[1] // CELL) + 1):
                    for k in range(int(lo[2] // CELL), int(hi[2] // CELL) + 1):
                        self.cells[(i, j, k)].append(idx)

    def at(self, P):
        key = tuple(int(v // CELL) for v in P)
        for idx in self.cells.get(key, ()):
            name, p, R, s = self.items[idx]
            u = (R.T @ (P - p)) / s
            if inside(name, u):
                return idx
        return None


def flatten(groups):
    """Every object in a world's object list, however deeply grouped (hand-made worlds mix groups and objects)."""
    for o in groups:
        if "objects" in o:
            yield from flatten(o["objects"])
        else:
            yield o


def check_route(world, route):
    """Walk the route's centre line: returns samples, no_floor, blocked and the problem list."""
    solids = Solids(list(flatten(world["objects"])))
    samples = no_floor = blocked = 0
    bad = []
    for n, (kind, A, B, width) in enumerate(route.log):
        if kind == "spiral":                     # wedge steps around a pole: check each step's middle
            for a2, b2 in route.spirals[n]:
                P = (a2 + b2) / 2
                samples += 1
                if not any(solids.at(P - ou.UP * dy) is not None for dy in (0.05, 0.12, 0.2)):
                    no_floor += 1
                    bad.append(("no floor", kind, n, np.round(P, 1)))
                    continue
                hit = next((solids.at(P + ou.UP * h) for h in (0.45, 1.1, 1.9) if solids.at(P + ou.UP * h) is not None), None)
                if hit is not None:
                    blocked += 1
                    name, p, _, s = solids.items[hit]
                    bad.append((f"blocked by {name} {np.round(s, 1)}", kind, n, np.round(P, 1)))
            continue
        d = B - A
        L = float(np.linalg.norm(d))
        F = ou.norm(np.array([d[0], 0, d[2]])) if math.hypot(d[0], d[2]) > 1e-6 else np.array([0, 0, 1.0])
        R = np.cross(F, ou.UP)
        for t in np.linspace(0, 1, max(2, int(L / 0.5) + 1))[1:-1]:
            P = A + d * t
            samples += 1
            if not any(solids.at(P - ou.UP * dy) is not None for dy in (0.05, 0.12, 0.2)):
                no_floor += 1
                bad.append(("no floor", kind, n, np.round(P, 1)))
                continue
            for h in (0.45, 1.1, 1.9):
                hit = next((solids.at(P + ou.UP * h + R * l) for l in (-0.25, 0, 0.25)
                            if solids.at(P + ou.UP * h + R * l) is not None), None)
                if hit is not None:
                    blocked += 1
                    name, p, _, s = solids.items[hit]
                    bad.append((f"blocked by {name} {np.round(s, 1)}", kind, n, np.round(P, 1)))
                    break
    return dict(samples=samples, no_floor=no_floor, blocked=blocked, problems=bad)


def main():
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
    world, w, route, top, stuck = ou.build(seed)
    res = check_route(world, route)
    samples, no_floor, blocked, bad = res["samples"], res["no_floor"], res["blocked"], res["problems"]
    spirals = sum(1 for k in route.log if k[0] == "spiral")
    print(f"route pieces {len(route.log)} ({spirals} spiral staircases), samples {samples}")
    print(f"no floor: {no_floor}   head-room blocked: {blocked}")
    by = defaultdict(int)
    for b in bad:
        by[(b[0], b[1])] += 1
    for k, v in sorted(by.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {v:5d}  {k[0]}  (on {k[1]})")
    if "-v" in sys.argv:
        for b in bad[:40]:
            print("  ", *b)
    sys.exit(1 if (no_floor or blocked) else 0)


if __name__ == "__main__":
    main()
