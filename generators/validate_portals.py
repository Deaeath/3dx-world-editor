"""Check every portal in a generated world: an entry needs floor under it and room for a body; an exit (raised
0.5 m as the game's own worlds do) needs floor within 1 m below it and nothing in the space a player lands in.

Usage: python validate_portals.py path/to/world.world"""
import json
import sys

import numpy as np

from validate_route import Solids, flatten

UP = np.array([0.0, 1.0, 0.0])


def body_clear(S, base):
    for h in (0.4, 1.0, 1.7):
        for dx, dz in ((0, 0), (0.25, 0), (-0.25, 0), (0, 0.25), (0, -0.25)):
            i = S.at(base + np.array([dx, h, dz]))
            if i is not None:
                name, p, _, s = S.items[i]
                return f"{name} at {np.round(p, 1)} size {np.round(s, 2)}"
    return None


def floor_below(S, base, depth):
    for dy in np.arange(0.03, depth, 0.05):
        if S.at(base - UP * dy) is not None:
            return round(float(dy), 2)
    return None


def check(world):
    """Every portal pair (consecutive in file order): returns (pairs, [problem strings])."""
    objs = list(flatten(world["objects"]))
    S = Solids(objs)
    ports = [o for o in objs if o["n"] == "portal"]
    out = []
    for k in range(0, len(ports) - 1, 2):
        e, x = ports[k], ports[k + 1]
        ep, xp = np.array(e["p"], float), np.array(x["p"], float)
        problems = []
        if floor_below(S, ep + UP * 0.02, 0.3) is None:
            problems.append("entry has no floor")
        b = body_clear(S, ep)
        if b:
            problems.append("entry blocked by " + b)
        fb = floor_below(S, xp, 1.2)
        if fb is None:
            problems.append("exit has no floor within 1.2 m")
        else:
            b = body_clear(S, xp - UP * fb)
            if b:
                problems.append("exit blocked by " + b)
        if problems:
            out.append(f"pair {k // 2}: entry {np.round(ep, 1).tolist()} -> exit {np.round(xp, 1).tolist()}: " + "; ".join(problems))
    if len(ports) % 2:
        out.append(f"odd number of portals ({len(ports)}): the last one has no partner")
    return len(ports) // 2, out


def main():
    world = json.load(open(sys.argv[1], encoding="utf-8-sig"))
    pairs, problems = check(world)
    for p in problems:
        print(p)
    print(f"{pairs} portal pairs, {len(problems)} with problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
