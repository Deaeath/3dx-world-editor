"""
ONLY UP! for 3DXChat - generates an enormous vertical climbing world.

    python generators/only_up.py [out.world] [--seed N]

One continuous walkable route, ~1.5 km straight up, through twelve zones in the
spirit of Only Up!: junkyard, favela, factory, beanstalk + dragon, cloud bridge,
floating Japanese city, desert (pyramid + dinosaur skeleton), plane graveyard,
pirate ship + killer whale, giant flower garden, heaven, space, and the Moon.

The route never needs a jump: it is beams, ramps (<= 28 deg) and stairs with
0.25 m steps - the same rise as the game's own Stair prefabs - getting narrower
the higher you go. Fall off and you land on whatever is below. Like the
original there are no checkpoints; a portal on the summit takes you back down.

Coordinates are the game's (Unity, left-handed, Y up). Every walkable surface is
a Box. Scenery is checked against a head-room volume over the route, and big
scenery reserves its space so the route steers around it.
"""
import json
import math
import os
import random
import sys

import numpy as np

UP = np.array([0.0, 1.0, 0.0])
HEADROOM = 2.7          # clear space kept above every walkable surface
PLAZA_C = np.array([0.0, 0.0, -20.0])   # teleporter plaza behind the spawn
PLAZA_R = 11.0
DENSITY = 1.8                 # scenery multiplier (objects around the route)
STEP = 0.25             # stair rise (same as the game's Stair1/Stair2)
MAX_SLOPE = 28.0        # ramps never steeper than this (degrees)


# ============================================================ maths
def unity_euler(X, Y, Z):
    """Rotation whose columns are the local X/Y/Z axes -> Unity Euler (deg), R = Ry*Rx*Rz."""
    R = np.column_stack([X, Y, Z])
    assert np.linalg.det(R) > 0, "improper rotation"
    sx = max(-1.0, min(1.0, -R[1, 2]))
    x = math.asin(sx)
    if abs(math.cos(x)) > 1e-6:
        y = math.atan2(R[0, 2], R[2, 2])
        z = math.atan2(R[1, 0], R[1, 1])
    else:
        y = math.atan2(-R[2, 0], R[0, 0])
        z = 0.0
    return [round(math.degrees(a) % 360.0, 3) for a in (x, y, z)]


def norm(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def heading_of(v):
    return math.degrees(math.atan2(v[0], v[2])) % 360


def fwd(heading):
    h = math.radians(heading)
    return np.array([math.sin(h), 0.0, math.cos(h)])


def right_of(heading):     # viewer's right in the game's left-handed space
    h = math.radians(heading)
    return np.array([math.cos(h), 0.0, -math.sin(h)])


def rf(v):
    return [round(float(x), 4) for x in v]


def basis_upright(heading):
    F = fwd(heading)
    return np.cross(F, UP), F, UP.copy()          # X = Y x Z keeps det = +1


def basis_down(heading):
    """Upside-down basis (local Z pointing down) for cones/pyramids hanging below islands."""
    X, Y, _ = basis_upright(heading)
    return -X, Y, -UP


class AABB:
    """Axis-aligned box; may also carry the exact oriented box it was made from (centre, axes rows, half sizes),
    in which case overlap tests are exact (separating axes) after the quick axis-aligned check."""
    __slots__ = ("lo", "hi", "obb")

    def __init__(self, lo, hi, obb=None):
        self.lo, self.hi, self.obb = np.asarray(lo, float), np.asarray(hi, float), obb

    def box(self):
        return self.obb if self.obb is not None else ((self.lo + self.hi) / 2, np.eye(3), (self.hi - self.lo) / 2)

    def hits(self, o, pad=0.0):
        if not (np.all(self.lo - pad < o.hi) and np.all(o.lo - pad < self.hi)):
            return False
        if self.obb is None and o.obb is None:
            return True
        return obb_overlap(*self.box(), *o.box(), pad)


def obb_overlap(c1, A1, e1, c2, A2, e2, pad=0.0):
    """Separating-axis test for two oriented boxes (axes as rows); `pad` grows the second box."""
    e2 = np.asarray(e2) + pad
    crosses = np.cross(A1[:, None, :], A2[None, :, :]).reshape(-1, 3)
    axes = np.vstack([A1, A2, crosses])
    n = np.linalg.norm(axes, axis=1)
    axes = axes[n > 1e-6] / n[n > 1e-6, None]
    r1 = np.abs(axes @ A1.T) @ e1
    r2 = np.abs(axes @ A2.T) @ e2
    d = np.abs(axes @ (np.asarray(c2) - np.asarray(c1)))
    return not bool(np.any(d >= r1 + r2 - 1e-9))


def corners_aabb(origin, X, Y, Z, sx, sy, sz, zmin=0.0, zmax=1.0):
    pts = []
    for a in (-0.5, 0.5):
        for b in (-0.5, 0.5):
            for c in (zmin, zmax):
                pts.append(origin + X * a * sx + Y * b * sy + Z * c * sz)
    pts = np.array(pts)
    axes = np.array([norm(np.asarray(X, float)), norm(np.asarray(Y, float)), norm(np.asarray(Z, float))])
    obb = (origin + np.asarray(Z, float) * sz * (zmin + zmax) / 2, axes, np.abs([sx / 2, sy / 2, sz * (zmax - zmin) / 2]))
    return AABB(pts.min(0), pts.max(0), obb)


def bbox(center, half):
    c, h = np.asarray(center, float), np.asarray(half, float)
    return AABB(c - h, c + h)


class Grid:
    """Spatial hash of tagged AABBs."""

    def __init__(self, cell=8.0):
        self.cell, self.cells, self.items = cell, {}, []

    def _keys(self, bb):
        c = self.cell
        lo, hi = np.floor(bb.lo / c).astype(int), np.floor(bb.hi / c).astype(int)
        for i in range(lo[0], hi[0] + 1):
            for j in range(lo[1], hi[1] + 1):
                for k in range(lo[2], hi[2] + 1):
                    yield (i, j, k)

    def add(self, bb, tag):
        idx = len(self.items)
        self.items.append((bb, tag))
        for k in self._keys(bb):
            self.cells.setdefault(k, []).append(idx)

    def retract(self, n):
        """Forget every item added after the first n (they stay hashed but never hit)."""
        for idx in range(n, len(self.items)):
            self.items[idx] = (self.items[idx][0], None)

    def hit(self, bb, ignore=(), pad=0.0, only=None):
        seen = set()
        for k in self._keys(bb):
            for idx in self.cells.get(k, ()):
                if idx in seen:
                    continue
                seen.add(idx)
                b, tag = self.items[idx]
                if tag is None or tag in ignore or (only is not None and tag not in only):
                    continue
                if b.hits(bb, pad):
                    return True
        return False


# ============================================================ world builder
class World:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.groups = []
        self.g = None
        self.count = 0
        self.route = Grid()           # head-room above walkable surfaces
        self.solid = Grid()           # walkable surfaces + reserved scenery
        self.piece = 0                # route piece counter (tags)
        self.guard = None             # (AABB, y): scenery may not rise above y inside this box (the next zone's airspace)
        self.keepout = []             # boxes scenery stays out of entirely (e.g. the view from the spawn to the big sign)

    def begin(self):
        self.g = {"n": "group", "objects": []}
        self.groups.append(self.g)
        return self.g

    def add(self, obj):
        self.g["objects"].append(obj)
        self.count += 1
        return obj

    def snapshot(self, r, *extra):
        return (r.p.copy(), r.h, r.width, r.in_dir.copy(), r._pad_at, len(r.log), self.piece, len(self.route.items),
                len(self.solid.items), len(self.g["objects"]), self.count, extra)

    def restore(self, r, snap):
        """Undo everything the route and its landings built since `snap`; returns the snapshot's extras."""
        p, r.h, r.width, in_dir, r._pad_at, nlog, self.piece, nroute, nsolid, nobj, self.count, extra = snap
        r.p, r.in_dir = p.copy(), in_dir.copy()
        del r.log[nlog:]
        self.route.retract(nroute)
        self.solid.retract(nsolid)
        del self.g["objects"][nobj:]
        return extra

    def free_all(self, bbs, pad=0.25, recent=0):
        """free() for several boxes at once: reserves them only if every one is clear."""
        if any(self.route.hit(bb, pad=pad) for bb in bbs):
            return False
        if self.guard is not None and any(bb.hi[1] > self.guard[1] and bb.hits(self.guard[0]) for bb in bbs):
            return False
        if any(bb.hits(k) for bb in bbs for k in self.keepout):
            return False
        for bb in bbs:
            self.solid.add(bb, -1)
        return True

    def recent(self, n):
        return set(range(max(0, self.piece - n), self.piece + 1))

    def free(self, bb, pad=0.25, recent=0):
        """True if bb stays out of the route's head-room; then reserves bb so later route avoids it."""
        if self.route.hit(bb, pad=pad):            # exact against the route's oriented head-room, recent pieces included
            return False
        if self.guard is not None:
            g, gy = self.guard
            if bb.hi[1] > gy and bb.hits(g):
                return False
        if any(bb.hits(k) for k in self.keepout):
            return False
        self.solid.add(bb, -1)
        return True

    # ---- primitives
    def obj(self, name, origin, X, Y, Z, s, mat=None, color=None):
        o = {"n": name, "p": rf(origin), "r": unity_euler(X, Y, Z), "s": rf(s)}
        if color is not None:
            o["c"] = rf(color)
        if mat:
            o["m"] = mat
        return self.add(o)

    def box(self, origin, X, Y, Z, sx, sy, sz, mat, color=(1, 1, 1)):
        """Box spanning local x,y in [-.5,.5]*size and z in [0,1]*sz from origin."""
        self.obj("Box", origin, X, Y, Z, (sx, sy, sz), mat, color)

    def ubox(self, cx, ybot, cz, w, d, h, mat, color=(1, 1, 1), yaw=0.0):
        X, Y, Z = basis_upright(yaw)
        self.box(np.array([cx, ybot, cz]), X, Y, Z, w, d, h, mat, color)

    def beam(self, A, B, width, thick, mat, color=(1, 1, 1), over=0.0):
        """Box whose TOP surface runs along A->B."""
        A, B = np.asarray(A, float), np.asarray(B, float)
        F = norm(B - A)
        U = norm(UP - F * F[1]) if abs(F[1]) < 0.999 else np.array([1.0, 0, 0])
        X = np.cross(F, U)
        L = np.linalg.norm(B - A) + over
        self.box((A + B) / 2 - U * thick, X, F, U, width, L, thick, mat, color)

    def cyl(self, A, B, d, mat, color=(1, 1, 1), name="Cylinder"):
        A, B = np.asarray(A, float), np.asarray(B, float)
        Z = norm(B - A)
        ref = np.array([1.0, 0, 0]) if abs(Z[0]) < 0.9 else np.array([0, 0, 1.0])
        X = norm(np.cross(ref, Z))
        Y = np.cross(Z, X)
        self.obj(name, A, X, Y, Z, (d, d, np.linalg.norm(B - A)), mat, color)

    def vcyl(self, x, y, z, d, h, mat, color=(1, 1, 1), name="Cylinder"):
        self.cyl((x, y, z), (x, y + h, z), d, mat, color, name)

    def ell(self, c, sx, sy, sz, mat, color=(1, 1, 1), name="Sphere", yaw=0.0):
        """Sphere-like shape centred at c with extents sx (side), sy (height), sz (length along yaw)."""
        X, Y, Z = basis_upright(yaw)
        self.obj(name, np.asarray(c, float) - UP * sy / 2, X, Y, Z, (sx, sz, sy), mat, color)

    def shape(self, name, base, w, d, h, mat, color=(1, 1, 1), yaw=0.0):
        """Upright primitive (Cone, Pyramid...) standing on base."""
        X, Y, Z = basis_upright(yaw)
        self.obj(name, np.asarray(base, float), X, Y, Z, (w, d, h), mat, color)

    def hang(self, name, top, w, d, depth, mat, color=(1, 1, 1), yaw=0.0):
        """Cone/Pyramid pointing down from `top` (island undersides)."""
        X, Y, Z = basis_down(yaw)
        self.obj(name, np.asarray(top, float), X, Y, Z, (w, d, depth), mat, color)

    def prop(self, name, base, yaw=0.0, scale=1.0, mat=None, color=None):
        X, Y, Z = basis_upright(yaw)
        sc = scale if isinstance(scale, (list, tuple)) else (scale, scale, scale)
        self.obj(name, base, X, Y, Z, sc, mat, color)

    def portal_glow(self, at, yaw, color):
        """A translucent glowing hexagon on the floor exactly over a portal pad (flat, so it never gets between
        you and the portal), and a coloured light above it."""
        X, Y, Z = basis_upright(yaw)
        at = np.asarray(at, float)
        self.obj("Hex", at, X, Y, Z, (1.4, 1.4, 0.05), "Hologram2", color)
        self.obj("LightP", at + UP * 0.8, X, Y, Z, (1.0, 1.0, 1.0), None, color)


# ============================================================ pixel font (5x7)
FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    ".": ["00000", "00000", "00000", "00000", "00000", "00000", "00100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "'": ["00100", "00100", "01000", "00000", "00000", "00000", "00000"],
    " ": ["00000"] * 7,
}


def text(w, center, heading, s, px=0.35, mat="Illum FLAT", color=(1, 0.85, 0.2), board=None):
    """Pixel text centred at `center`, readable by someone looking along `heading`."""
    R, F = right_of(heading), fwd(heading)
    X, Y, Z = -R, UP.copy(), -F          # faces the viewer; X = Y x Z
    lines = s.split("\n")
    cols = max(len(line) for line in lines) * 6 - 1
    rows = len(lines) * 8 - 1
    W, H = cols * px, rows * px
    center = np.asarray(center, float)
    top_left = center - R * W / 2 + UP * H / 2
    if board:
        bm, bc = board
        # board: a slab standing behind the letters (Z up, Y across the viewing direction)
        Xb, Yb, Zb = np.cross(-F, UP), -F, UP.copy()
        w.box(center - UP * (H / 2 + px) + F * 0.1, Xb, Yb, Zb, W + 2 * px, 0.1, H + 2 * px, bm, bc)
    for li, line in enumerate(lines):
        for ci, ch in enumerate(line.upper()):
            glyph = FONT.get(ch, FONT[" "])
            for ri, row in enumerate(glyph):
                c = 0
                while c < 5:
                    if row[c] == "1":
                        e = c
                        while e < 5 and row[e] == "1":
                            e += 1
                        n = e - c
                        x0 = (ci * 6 + c) * px
                        y0 = (li * 8 + ri) * px
                        o = top_left + R * (x0 + n * px / 2) - UP * (y0 + px / 2)
                        w.box(o, X, Y, Z, n * px, px, 0.12, mat, color)
                        c = e
                    else:
                        c += 1


def sign_bbox(center, heading, chars, lines, px):
    """Space a sign takes: wide along the viewer's right, thin along the view direction."""
    W = (chars * 6) * px + 2 * px
    H = (lines * 8) * px + 2 * px
    half = np.abs(right_of(heading)) * (W / 2 + 0.3) + np.abs(fwd(heading)) * 0.4
    return bbox(center, (half[0], H / 2 + 0.3, half[2]))


# ============================================================ the route
class Route:
    """A turtle that lays a continuous walkable path."""

    def __init__(self, w, pos, heading):
        self.w = w
        self.p = np.array(pos, float)
        self.h = heading
        self.log = []                      # (kind, start, end, width)
        self.style = None
        self.width = 2.0
        self.in_dir = fwd(heading)         # horizontal direction of the last piece laid (the way you arrive)
        self.spirals = {}
        self._pad_at = None

    def _clear_boxes(self, A, B, width, extra=0.0):
        """Head-room over A->B as vertical-sided boxes, one per short stretch, so a standing body is covered all
        the way along slopes too; `extra` widens them sideways/upwards but never below the surface, so scenery
        hanging under a landing doesn't count as blocking the way off it."""
        d = B - A
        Fh = np.array([d[0], 0.0, d[2]])
        Lh = float(np.linalg.norm(Fh))
        Fh = Fh / Lh if Lh > 1e-6 else fwd(self.h)
        X = np.cross(Fh, UP)
        n = max(1, int(math.ceil(Lh / 1.5)))
        out = []
        for i in range(n):
            a, b = A + d * (i / n), A + d * ((i + 1) / n)
            lo_y, rise = min(a[1], b[1]), abs(b[1] - a[1])
            mid = (a + b) / 2
            out.append(corners_aabb(np.array([mid[0], lo_y, mid[2]]), X, Fh, UP, width + 0.3 + 2 * extra,
                                    max(Lh / n, 0.05), HEADROOM + extra + rise))
        return out

    def _register(self, A, B, width, thick=0.4, same_piece=False):
        w = self.w
        if not same_piece:
            w.piece += 1
        for bb in self._clear_boxes(A, B, width):
            w.route.add(bb, w.piece)
        F = norm(B - A)
        U = norm(UP - F * F[1])
        X = np.cross(F, U)
        w.solid.add(corners_aabb((A + B) / 2 - U * thick, X, F, U, width, np.linalg.norm(B - A), thick), w.piece)

    def would_hit(self, A, B, width):
        """Would a new piece A->B collide with older route pieces or reserved scenery?"""
        w = self.w
        return self._blocked([(A, B)], width)

    def _blocked(self, segs, width, skip=1.0):
        """Segments (A, B) of a new piece vs everything built: with a margin against older pieces; against the
        last two (the one you stand on and the one before) exactly, once more than `skip` m from the joint, so
        a piece doubling back over them is still caught."""
        w = self.w
        recent = w.recent(2)
        gone = 0.0
        for A, B in segs:
            if any(w.route.hit(c, ignore=recent) or w.solid.hit(c, ignore=recent)
                   for c in self._clear_boxes(A, B, width, extra=0.5)):
                return True
            d = B - A
            Lh = math.hypot(d[0], d[2])
            if gone + Lh > skip:
                A2 = A + d * (max(0.0, skip - gone) / Lh) if gone < skip else A
                if any(w.route.hit(c, only=recent) for c in self._clear_boxes(A2, B, max(0.3, width - 0.2))):
                    return True
            gone += Lh
        return False

    # moves ------------------------------------------------------------------
    def surface(self, A, B, width, kind):
        self.style.surface(self.w, A, B, width, kind)
        self._register(A, B, width)
        self.log.append((kind, A.copy(), B.copy(), width))
        self.in_dir = fwd(self.h)

    def walk(self, L, width=None):
        width = width or self.width
        A = self.p.copy()
        B = A + fwd(self.h) * L
        self.surface(A, B, width, "walk")
        self.p = B

    def ramp(self, L, rise, width=None):
        width = width or self.width
        if math.degrees(math.atan2(abs(rise), L)) > MAX_SLOPE:
            L = abs(rise) / math.tan(math.radians(MAX_SLOPE))
        A = self.p.copy()
        B = A + fwd(self.h) * L + UP * rise
        self.surface(A, B, width, "ramp")
        self.p = B

    def stairs(self, n, run=0.32, width=None):
        width = width or self.width
        F = fwd(self.h)
        A = self.p.copy()
        for i in range(n):
            a = A + F * run * i + UP * STEP * (i + 1)
            self.style.step(self.w, a, a + F * run, width)
        B = A + F * run * n + UP * STEP * n
        self._register(A, B, width)
        self.log.append(("stairs", A, B, width))
        self.in_dir = F
        self.p = B

    def landing(self, size, turn=0.0, kind="landing"):
        """Square landing laid straight on from the way you arrived (so it never reaches back over a slope
        below), left in the current heading plus `turn`."""
        F = self.in_dir
        A = self.p.copy()
        C = A + F * size / 2
        self.style.landing(self.w, C, size, heading_of(F), kind)
        self._register(A, A + F * size, size)
        self.h = (self.h + turn) % 360
        self.p = C + fwd(self.h) * size / 2
        self.in_dir = fwd(self.h)
        self.log.append((kind, A, self.p.copy(), size))      # logged to where the route actually leaves it
        return C

    def pivot(self, turn):
        """Turn. At the top of a slope, turning on the spot would put the next piece's back corner over the
        steps below (a wall), so turn on a small flat head laid straight on; on the flat, turn on the spot over
        a pad reaching forward, which fills the corner notch. Returns False if there's no room for the head."""
        if self.log and self.log[-1][0] in ("stairs", "ramp", "spiral"):
            size = self.width + 0.3
            if self.would_hit(self.p, self.p + self.in_dir * size, size):
                return False
            self.landing(size, turn=turn)
            return True
        if self._pad_at is None or np.linalg.norm(self._pad_at - self.p) > 0.05:      # one pad per spot
            self.style.notch_pad(self.w, self.p, self.width, heading_of(self.in_dir))
            self._pad_at = self.p.copy()
        self.h = (self.h + turn) % 360
        return True

    def _spiral_steps(self, radius, steps, direction):
        centre = self.p + right_of(self.h) * direction * radius
        off = self.p - centre
        start_ang = math.atan2(off[0], off[2])
        dth = 0.42 / radius * direction            # increasing angle walks forward when the centre is on the right
        prev, out = self.p.copy(), []
        for i in range(steps):
            ang = start_ang + dth * (i + 1)
            b = centre + np.array([math.sin(ang), 0, math.cos(ang)]) * radius
            b[1] = self.p[1] + STEP * (i + 1)
            out.append((np.array([prev[0], b[1], prev[2]]), b))
            prev = b
        return centre, out

    def spiral(self, radius, steps, direction=1, width=None):
        """Spiral staircase around a pole; ends heading along the last step."""
        width = width or self.width
        centre, segs = self._spiral_steps(radius, steps, direction)
        p0 = self.p.copy()
        for i, (a2, b) in enumerate(segs):
            self.style.step(self.w, a2, b, width, wedge=True)
            self._register(a2, b, width, same_piece=i > 0)      # the whole spiral is one piece
        last = segs[-1][1] - segs[-1][0]
        prev = segs[-1][1]
        pr = max(0.4, (radius - width / 2 - 0.2) * 0.6) / 2
        self.style.pole(self.w, centre, p0[1], prev[1], radius - width / 2 - 0.2)
        self.w.solid.add(AABB((centre[0] - pr, p0[1] - 0.5, centre[2] - pr), (centre[0] + pr, prev[1] - 0.3, centre[2] + pr)), -1)
        self.h = math.degrees(math.atan2(last[0], last[2])) % 360
        self.in_dir = fwd(self.h)
        self.p = prev
        self.log.append(("spiral", p0, prev, width))
        self.spirals[len(self.log) - 1] = segs           # step geometry, for the walkability check

    def spiral_fits(self, radius, steps, direction, width=None):
        width = width or self.width
        centre, segs = self._spiral_steps(radius, steps, direction)
        pr = max(0.4, (radius - width / 2 - 0.2) * 0.6) / 2 + 0.2
        pole = AABB((centre[0] - pr, self.p[1] - 0.5, centre[2] - pr), (centre[0] + pr, segs[-1][1][1], centre[2] + pr))
        if self.w.route.hit(pole) or self.w.solid.hit(pole):
            return False
        return not self._blocked(segs, width, skip=1.2)


# ============================================================ zone styles
class Style:
    """How a zone's route looks."""

    def __init__(self, w, mat, color=(1, 1, 1), edge=None, thick=0.35, step_mat=None, step_color=None):
        self.w, self.rng = w, w.rng
        self.mat, self.color, self.edge, self.thick = mat, color, edge, thick
        self.step_mat, self.step_color = step_mat or mat, step_color or color

    def surface(self, w, A, B, width, kind):
        w.beam(A, B, width, self.thick, self.mat, self.color, over=0.15)
        if self.edge:
            em, ec = self.edge
            F = norm(B - A)
            X = norm(np.cross(F, UP))
            for sgn in (-1, 1):
                off = X * sgn * (width / 2 + 0.05)
                w.beam(A + off - UP * 0.02, B + off - UP * 0.02, 0.1, self.thick + 0.06, em, ec)

    def step(self, w, a, b, width, wedge=False):
        w.beam(a, b, width + (0.25 if wedge else 0), STEP + 0.12, self.step_mat, self.step_color, over=0.12 if wedge else 0.06)

    def landing(self, w, C, size, heading, kind):
        self.pad(w, C, size, heading)

    def slab(self, w, C, size, heading, extra, thick, mat, color):
        """Landing top `extra` m bigger than the walkway, overhanging forward and sideways only (never back over
        the way up), and reserved so later route can't run underneath it."""
        X, Y, Z = basis_upright(heading)
        o = C + Y * extra / 2 - UP * thick
        if extra and w.route.hit(corners_aabb(o, X, Y, Z, size + extra, size + extra, thick + 0.05)):
            extra, o = 0.0, C - UP * thick                  # the overhang would hang over route: no overhang
        w.box(o, X, Y, Z, size + extra, size + extra, thick, mat, color)
        w.solid.add(corners_aabb(o, X, Y, Z, size + extra, size + extra, thick), -1)

    def notch_pad(self, w, P, width, heading):
        """Pad for a turn on the spot: the corner notch is always ahead of the turning point, never behind it."""
        X, Y, Z = basis_upright(heading)
        o = P + Y * (width * 0.3) - UP * self.thick
        w.box(o, X, Y, Z, width, width * 0.6, self.thick, self.mat, self.color)
        w.solid.add(corners_aabb(o, X, Y, Z, width, width * 0.6, self.thick), -1)

    def pad(self, w, P, s, heading):
        X, Y, Z = basis_upright(heading)
        w.box(P - UP * self.thick, X, Y, Z, s, s, self.thick, self.mat, self.color)

    def pole(self, w, centre, y0, y1, r):
        w.vcyl(centre[0], y0 - 0.5, centre[2], max(0.4, r * 0.6), y1 - y0 + 0.2, self.mat, self.color)   # top under the last step


COLOURS = [(0.95, 0.55, 0.45), (0.5, 0.75, 0.95), (0.95, 0.85, 0.45), (0.6, 0.9, 0.6), (0.95, 0.65, 0.85), (1, 1, 1)]
FLOWERS = [(1, 0.3, 0.45), (1, 0.85, 0.2), (0.6, 0.45, 1), (1, 0.55, 0.15), (0.35, 0.75, 1)]
BONE = (0.95, 0.92, 0.85)
RED = (0.9, 0.2, 0.12)
GOLD = (1, 0.85, 0.3)


class Favela(Style):
    def landing(self, w, C, size, heading, kind):
        # every landing is a shack roof with the house hanging below it
        X, Y, Z = basis_upright(heading)
        self.slab(w, C, size, heading, 0.4, 0.35, "roof_2", (0.75, 0.72, 0.7))
        hh = self.rng.uniform(2.6, 4.2)
        if w.free(AABB(C - np.array([size / 2, hh + 0.35, size / 2]), C + np.array([size / 2, -0.4, size / 2])), recent=3):
            w.box(C - UP * (hh + 0.35), X, Y, Z, size, size, hh, self.rng.choice(["PlasterStucco", "brick_1", "concrete_8"]),
                  self.rng.choice(COLOURS))


class Industrial(Style):
    def surface(self, w, A, B, width, kind):
        super().surface(w, A, B, width, kind)            # I-beam: top plate, web, bottom flange
        w.beam(A - UP * self.thick, B - UP * self.thick, 0.12, 0.9, "metal_10", (0.35, 0.35, 0.38))
        w.beam(A - UP * (self.thick + 0.9), B - UP * (self.thick + 0.9), width * 0.7, 0.15, "metal_10", (0.35, 0.35, 0.38))

    def landing(self, w, C, size, heading, kind):
        # a shipping container to stand on
        X, Y, Z = basis_upright(heading + self.rng.choice([0, 90]))
        W, L = max(size, 2.5), max(size, 6.0)
        col = self.rng.choice([(0.85, 0.25, 0.2), (0.2, 0.45, 0.8), (0.95, 0.65, 0.15), (0.25, 0.6, 0.35), (0.7, 0.7, 0.72)])
        if not w.free(corners_aabb(C - UP * 2.6, X, Y, Z, W + 0.2, L, 2.55), recent=3):
            self.pad(w, C, size, heading)
            return
        w.box(C - UP * 2.6, X, Y, Z, W, L, 2.6, "MetalPlate", col)
        for t in np.linspace(-0.45, 0.45, 7):
            for sgn in (-1, 1):
                w.box(C - UP * 2.55 + Y * L * t + X * sgn * (W / 2 + 0.03), X, Y, Z, 0.06, 0.12, 2.45, "MetalPlate",
                      tuple(c * 0.8 for c in col))


class Leafy(Style):
    def landing(self, w, C, size, heading, kind):
        X, Y, Z = basis_upright(heading)
        self.slab(w, C, size, heading, 0.6, 0.3, "leaf_2", (0.5, 0.9, 0.35))
        tip = C - UP * 0.6 - fwd(heading + 135) * (size * 0.9)
        if w.free(bbox(tip, (2, 0.5, 2)), recent=3):
            w.ell(tip, size * 0.6, 0.25, size * 1.1, "leaf_2", (0.45, 0.85, 0.3), yaw=heading + 135)


class Cloudy(Style):
    def surface(self, w, A, B, width, kind):
        w.beam(A, B, width, 0.18, "GlassClear", (0.85, 0.95, 1), over=0.15)
        for t in np.linspace(0.1, 0.9, max(2, int(np.linalg.norm(B - A) // 3))):
            q = A + (B - A) * t - UP * 1.4
            if w.free(bbox(q, (1.3, 0.8, 1.3)), recent=2):
                w.ell(q, 2.6, 1.6, 2.6, "Fabric2", (1, 1, 1))

    def landing(self, w, C, size, heading, kind):
        X, Y, Z = basis_upright(heading)
        w.box(C - UP * 0.2, X, Y, Z, size, size, 0.2, "Fabric2", (1, 1, 1))
        for k in range(6):
            a = k / 6 * 2 * math.pi
            q = C - UP * 1.3 + np.array([math.sin(a), 0, math.cos(a)]) * size * 0.45
            if w.free(bbox(q, (size * 0.35, 1, size * 0.35)), recent=3):
                w.ell(q, size * 0.7, 2.0, size * 0.7, "Fabric2", (1, 1, 1))


class Japan(Style):
    def landing(self, w, C, size, heading, kind):
        X, Y, Z = basis_upright(heading)
        s = size + 3
        self.slab(w, C, size, heading, 3.0, 0.3, "grass_1", (0.7, 0.9, 0.6))
        depth = self.rng.uniform(6, 12)
        if w.free(AABB(C - np.array([s / 2, depth + 0.3, s / 2]), C + np.array([s / 2, -0.35, s / 2])), recent=3):
            w.hang("Pyramid", C - UP * 0.3, s, s, depth, "rock_11", (0.75, 0.65, 0.6), yaw=heading)
        # a torii gate over the way in (the route never goes back that way): posts outside the walkway, beams overhead
        R = right_of(heading)
        gate = C - fwd(heading) * (size / 2 - 0.3)
        posts = [gate + R * sgn * (size / 2 + 0.5) for sgn in (-1, 1)]
        parts = [bbox(q + UP * 2.1, (0.5, 2.2, 0.5)) for q in posts]
        parts.append(AABB(np.minimum(gate + R * (size / 2 + 1.4), gate - R * (size / 2 + 1.4)) + UP * 3.35 - np.array([0.4, 0, 0.4]),
                          np.maximum(gate + R * (size / 2 + 1.4), gate - R * (size / 2 + 1.4)) + UP * 4.7 + 0.4))
        if self.rng.random() < 0.5 and w.free_all(parts, recent=3):
            for sgn in (-1, 1):
                q = gate + R * sgn * (size / 2 + 0.5)
                w.vcyl(q[0], C[1], q[2], 0.45, 4.2, "MetalPaintRed", RED)
            w.beam(gate + R * (size / 2 + 1.4) + UP * 4.6, gate - R * (size / 2 + 1.4) + UP * 4.6, 0.6, 0.45, "WoodWalnutX", (0.25, 0.15, 0.12))
            w.beam(gate + R * (size / 2 + 0.9) + UP * 3.7, gate - R * (size / 2 + 0.9) + UP * 3.7, 0.35, 0.3, "MetalPaintRed", RED)
        for sgn in (-1, 1):                                   # paper lanterns hanging under the front corners
            q = C + R * sgn * (s / 2 - 0.5) + fwd(heading) * (s / 2 - 0.5)
            if w.free(bbox(q - UP * 1.6, (0.5, 1.2, 0.5)), recent=3, pad=0.0):
                w.cyl(q - UP * 0.3, q - UP * 1.0, 0.04, "WoodWalnutX")
                w.ell(q - UP * 1.6, 0.8, 1.0, 0.8, "Illum FLAT", (1, 0.25, 0.1))


class Desert(Style):
    def landing(self, w, C, size, heading, kind):
        X, Y, Z = basis_upright(heading)
        self.slab(w, C, size, heading, 2.0, 0.5, "sand_1", (1, 0.9, 0.7))
        depth = self.rng.uniform(4, 9)
        if w.free(AABB(C - np.array([size / 2 + 1, depth + 0.5, size / 2 + 1]), C + np.array([size / 2 + 1, -0.55, size / 2 + 1])), recent=3):
            w.hang("Cone", C - UP * 0.5, size + 2, size + 2, depth, "Rock_CliffDesert4", yaw=heading)


class Plane(Style):
    def surface(self, w, A, B, width, kind):
        # aircraft wings: white with a red stripe
        w.beam(A, B, width, 0.3, "MetalPaintWhite", (0.95, 0.95, 0.97), over=0.15)
        X = norm(np.cross(norm(B - A), UP))
        w.beam(A + X * (width / 2 - 0.08) + UP * 0.005, B + X * (width / 2 - 0.08) + UP * 0.005, 0.16, 0.02, "MetalPaintRed", (0.9, 0.2, 0.2))

    def landing(self, w, C, size, heading, kind):
        # stand on the back of an airliner
        self.pad(w, C, size, heading)
        X, Y, Z = basis_upright(heading + 90)
        L = self.rng.uniform(18, 28)
        body = C - UP * 2.15
        A, B = body - Y * L * 0.5, body + Y * L * 0.5
        bb = AABB(np.minimum(A, B) - np.array([2.4, 2.2, 2.4]) - np.abs(Y) * 6, np.maximum(A, B) + np.array([2.4, 2.0, 2.4]) + np.abs(Y) * 4)
        if not w.free(bb, recent=3):
            return
        w.cyl(A, B, 4.2, "MetalPaintWhite", (0.92, 0.92, 0.95))
        w.obj("Cone", B, X, -Z, Y, (4.2, 4.2, 3.5), "MetalPaintWhite", (0.92, 0.92, 0.95))     # nose
        w.obj("Cone", A, X, Z, -Y, (4.2, 4.2, 5.5), "MetalPaintWhite", (0.92, 0.92, 0.95))     # tail cone
        fin = A + Y * 1.5 + UP * 1.6
        w.beam(fin, fin + UP * 4.5 + Y * 2.5, 0.35, 2.4, "MetalPaintRed", (0.85, 0.15, 0.15))
        for k in range(int(L // 2)):
            w.ell(A + Y * (2 + k * 2) + X * 2.05 + UP * 0.6, 0.08, 0.7, 0.7, "glass_1", (0.1, 0.12, 0.15), yaw=heading + 90)
        for s in (-1, 1):                                  # wings low on the body, away from the walkway
            w0 = body + Y * 1.0 - UP * 0.9
            w.beam(w0 + X * s * 2.0, w0 + X * s * 14 - Y * 3, 3.2, 0.3, "MetalPaintWhite", (0.92, 0.92, 0.95))


class Ship(Style):
    def landing(self, w, C, size, heading, kind):
        self.pad(w, C, size, heading)
        if self.rng.random() < 0.5:                         # a barrel hanging under the boards
            q = C - UP * 1.6 + right_of(heading) * size * 0.25
            if w.free(bbox(q, (0.7, 0.9, 0.7))):
                w.vcyl(q[0], q[1] - 0.8, q[2], 1.2, 1.6, "WoodWalnutX", (0.55, 0.35, 0.25))


def galleon(w, rng, stern, heading, L=22.0, B=7.0, walkway=0.0, build=True):
    """A flying pirate ship whose deck starts at `stern` and runs along `heading`. Returns the boxes it fills
    (hull, masts, sails, figurehead) - the deck's walkway is left clear. Draws it only if `build`."""
    X, Y, Z = basis_upright(heading)
    F = fwd(heading)
    R = right_of(heading)
    mid = stern + F * L / 2
    parts = [corners_aabb(mid - UP * 5.9, X, Y, Z, B + 0.6, L, 5.5)]                       # hull
    side = rng.choice([-1, 1])
    masts = [(stern + F * (L * f) + R * side * s_ * (walkway / 2 + 0.9 if walkway else 0)) for f, s_ in ((0.3, 1), (0.68, -1))]
    for m in masts:
        parts.append(bbox(m + UP * 8.5, (0.5, 8.5, 0.5)))
        parts.append(corners_aabb(m + UP * 6.0, X, Y, Z, B + 1.5, 0.8, 7.5))                 # sail
    figure = stern + F * (L + 1.6) - UP * 1.6
    parts.append(bbox(figure, (1.3, 1.3, 2.0)))
    if not build:
        return parts
    deck = mid - UP * 0.4
    w.box(deck, X, Y, Z, B, L, 0.4, "WoodTeakX")
    for k in range(5):
        w.box(deck - UP * (k + 1) * 1.1, X, Y, Z, B - k * 1.2, L - 1.0 - k * 2.4, 1.1, "WoodWalnutX", (0.55, 0.35, 0.25))
    for sgn in (-1, 1):                                    # rails along the sides, cannons poking out
        w.box(deck + R * sgn * (B / 2 - 0.15), X, Y, Z, 0.3, L, 0.9, "WoodWalnutX", (0.5, 0.3, 0.2))
        for t in (0.25, 0.45, 0.65):
            q = stern + F * (L * t) + R * sgn * (B / 2 + 0.2) - UP * 0.9
            w.cyl(q, q + R * sgn * 1.6, 0.45, "metal_10", (0.15, 0.15, 0.17))
    for m in masts:
        w.vcyl(m[0], m[1] - 0.4, m[2], 0.6, 16.5, "WoodWalnutX", (0.45, 0.28, 0.18))
        w.box(m + UP * 6.0, X, Y, Z, B + 1.5, 0.15, 7.0, "Fabric2", (0.95, 0.93, 0.85))
        w.box(m + UP * 15.2, X, Y, Z, 0.05, 2.2, 1.4, "Fabric1", (0.08, 0.08, 0.08))          # black flag
    w.ell(figure, 2.2, 2.2, 3.5, "gold", GOLD, yaw=heading)
    return parts


class Garden(Style):
    def landing(self, w, C, size, heading, kind):
        # stand on a giant flower: yellow centre, petals around, stem below
        col = self.rng.choice(FLOWERS)
        self.pad(w, C, size, heading)
        for k in range(8):
            a = k / 8 * 360
            q = C - UP * 0.5 + fwd(a) * (size * 0.5 + 1.6)
            if w.free(bbox(q, (2.1, 0.3, 2.1)), recent=3):
                w.ell(q, 2.4, 0.35, 4.0, "Fabric1", col, yaw=a)
        if w.free(AABB(C - np.array([0.8, 30.5, 0.8]), C + np.array([0.8, -0.5, 0.8])), recent=3):
            w.vcyl(C[0], C[1] - 30, C[2], 1.2, 29.6, "leaf_1", (0.4, 0.75, 0.3))


class Heaven(Style):
    def landing(self, w, C, size, heading, kind):
        X, Y, Z = basis_upright(heading)
        self.slab(w, C, size, heading, 1.0, 0.5, "Marble", (1, 1, 1))
        for sx in (-1, 1):
            for sz in (-1, 1):
                if size < 4:                                   # small landings: the corners are on the way out
                    continue
                q = C + X * sx * (size / 2 + 0.2) + Y * sz * (size / 2 + 0.2)
                if w.free(AABB(q - np.array([0.6, 0.5, 0.6]), q + np.array([0.6, 4.6, 0.6])), recent=3, pad=0.0):
                    w.vcyl(q[0], q[1] - 0.5, q[2], 0.6, 4.6, "Marble", (1, 1, 1))
                    w.ubox(q[0], q[1] + 4.1, q[2], 1, 1, 0.4, "gold", GOLD)
        if w.free(AABB(C - np.array([size / 2 + 3, 4, size / 2 + 3]), C + np.array([size / 2 + 3, -1.0, size / 2 + 3])), recent=3):
            w.ell(C - UP * 2.5, size + 6, 3, size + 6, "Fabric2", (1, 1, 1))


class Space(Style):
    def surface(self, w, A, B, width, kind):
        w.beam(A, B, width, 0.25, "TileSciFi2_met", (0.8, 0.85, 0.95), over=0.15)
        X = norm(np.cross(norm(B - A), UP))
        for sgn in (-1, 1):
            off = X * sgn * (width / 2 + 0.06)
            w.beam(A + off - UP * 0.05, B + off - UP * 0.05, 0.08, 0.12, "Illum FLAT", (0.2, 0.9, 1))

    def landing(self, w, C, size, heading, kind):
        X, Y, Z = basis_upright(heading)
        w.box(C - UP * 0.3, X, Y, Z, size, size, 0.3, "TileSciFi1_met", (0.85, 0.85, 0.9))
        if w.free(AABB(C - np.array([size * 0.4, 2.6, size * 0.4]), C + np.array([size * 0.4, -0.35, size * 0.4])), recent=3):
            w.vcyl(C[0], C[1] - 2.6, C[2], size * 0.8, 2.3, "metal_9", (0.85, 0.85, 0.9))
        for s in (-1, 1):                                    # solar panels to the sides, below head-room
            q = C - UP * 1.4 + right_of(heading) * s * (size / 2 + 4)
            if w.free(bbox(q, (3.2, 0.3, 3.2)), recent=3):
                w.beam(q - fwd(heading) * 2, q + fwd(heading) * 2, 6, 0.1, "glass_4", (0.2, 0.35, 0.9))


# ============================================================ zones
ZONES = [
    ("THE JUNKYARD", 0),
    ("THE FAVELA", 120),
    ("THE FACTORY", 245),
    ("THE BEANSTALK", 410),
    ("CLOUD BRIDGE", 470),
    ("FLOATING CITY", 630),
    ("THE DESERT", 785),
    ("PLANE GRAVEYARD", 930),
    ("PIRATE SKIES", 1075),
    ("GIANT GARDEN", 1215),
    ("HEAVEN", 1350),
    ("ORBIT", 1500),
]


def ring(rng, centre, rmin, rmax):
    a = rng.random() * 2 * math.pi
    rr = rng.uniform(rmin, rmax)
    return centre[0] + math.sin(a) * rr, centre[1] + math.cos(a) * rr


# ---------------------------------------------------------------- scenery per zone
def deco_favela(w, rng, centre, y0, top):
    for _ in range(int(160 * DENSITY)):                                   # stacked shacks
        x, z = ring(rng, centre, 8, 50)
        y = rng.uniform(y0 - 6, top)
        hh, ww, dd = rng.uniform(3, 6), rng.uniform(3, 6), rng.uniform(3, 6)
        if not w.free(AABB((x - ww, y, z - dd), (x + ww, y + hh + 1.5, z + dd))):
            continue
        yaw = rng.choice([0, 15, 30, 45, 60, 75])
        w.ubox(x, y, z, ww, dd, hh, rng.choice(["PlasterStucco", "brick_1", "concrete_8"]), rng.choice(COLOURS), yaw=yaw)
        w.ubox(x, y + hh, z, ww + 0.6, dd + 0.6, 0.25, "roof_2", (0.7, 0.68, 0.65), yaw=yaw)
        X, Y, Z = basis_upright(yaw)
        for _k in range(rng.randint(1, 3)):                 # windows on the front wall
            o = np.array([x, y + rng.uniform(1, hh - 1.2), z]) + X * rng.uniform(-ww / 3, ww / 3) - Y * (dd / 2 + 0.03)
            w.box(o, X, Y, Z, 0.9, 0.06, 0.9, "glass_1", (0.1, 0.12, 0.15))
        if rng.random() < 0.4:                              # water tank
            w.vcyl(x + ww / 4, y + hh + 0.25, z, 1.0, 1.2, "MetalPaintBlue", (0.6, 0.8, 1))
        if rng.random() < 0.3:                              # washing line to a neighbour
            p0 = np.array([x, y + hh - 0.3, z])
            p1 = p0 + np.array([rng.uniform(-8, 8), rng.uniform(-1, 1), rng.uniform(-8, 8)])
            if w.free(AABB(np.minimum(p0, p1) - np.array([0.4, 1.0, 0.4]), np.maximum(p0, p1) + 0.4)):
                w.cyl(p0, p1, 0.04, "metal_4")
                for t in np.linspace(0.15, 0.85, 5):
                    q = p0 + (p1 - p0) * t
                    w.ubox(q[0], q[1] - 0.7, q[2], 0.5, 0.06, 0.65, "Fabric1",
                           rng.choice([(1, .3, .3), (.3, .6, 1), (1, 1, .4), (1, 1, 1), (.4, 1, .5)]))
    for _ in range(10):                                    # power poles
        x, z = ring(rng, centre, 55, 56)
        if w.free(AABB((x - 0.5, 0, z - 0.5), (x + 0.5, top * 0.8, z + 0.5))):
            w.vcyl(x, 0, z, 0.4, top * 0.8, "WoodPlaknsOldX")
            w.cyl((x - 1.2, top * 0.8 - 0.6, z), (x + 1.2, top * 0.8 - 0.6, z), 0.18, "WoodPlaknsOldX")


def deco_factory(w, rng, centre, y0, top):
    for _ in range(9):                                     # smoke stacks
        x, z = ring(rng, centre, 32, 60)
        h = rng.uniform(top - y0 + 20, top - y0 + 60)
        base = y0 - 40
        if not w.free(AABB((x - 3.5, base, z - 3.5), (x + 3.5, base + h, z + 3.5))):
            continue
        for k in range(int(h // 8)):
            w.vcyl(x, base + k * 8, z, 6 - k * 0.08, 8, "brick_6" if k % 2 == 0 else "MetalPaintWhite",
                   (0.75, 0.35, 0.3) if k % 2 == 0 else (1, 1, 1))
        w.prop("Smoke", (x, base + int(h // 8) * 8, z), 0, 6.0)
    for _ in range(6):                                     # tower cranes
        x, z = ring(rng, centre, 33, 52)
        h = top - y0 + 30
        base = y0 - 30
        if not w.free(AABB((x - 1.5, base, z - 1.5), (x + 1.5, base + h, z + 1.5))):
            continue
        for dx, dz in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            w.vcyl(x + dx * 0.9, base, z + dz * 0.9, 0.18, h, "MetalPaintYellow")
        for k in range(int(h // 3)):
            yy = base + k * 3
            w.cyl((x - 0.9, yy, z - 0.9), (x + 0.9, yy + 3, z - 0.9), 0.1, "MetalPaintYellow")
            w.cyl((x - 0.9, yy, z + 0.9), (x + 0.9, yy + 3, z + 0.9), 0.1, "MetalPaintYellow")
        Fa = fwd(rng.random() * 360)
        p0 = np.array([x, base + h, z]) - Fa * 12
        p1 = np.array([x, base + h, z]) + Fa * 40
        if w.free(AABB(np.minimum(p0, p1) - 1.5, np.maximum(p0, p1) + 1.5)):
            w.cyl(p0, p1, 1.2, "MetalPaintYellow")
            cw = p0 + Fa * 2
            w.ubox(cw[0], base + h - 2, cw[2], 3, 3, 3, "concrete_5")
            hook = p1 - Fa * 6
            if w.free(AABB(hook - np.array([0.3, 15, 0.3]), hook + np.array([0.3, 0, 0.3]))):
                w.cyl(hook, hook - UP * 15, 0.05, "metal_4")
    for _ in range(int(80 * DENSITY)):                                    # floating containers and pipes
        x, z = ring(rng, centre, 10, 50)
        y = rng.uniform(y0, top)
        yaw = rng.random() * 180
        if rng.random() < 0.6:
            if w.free(AABB((x - 3.5, y, z - 3.5), (x + 3.5, y + 2.7, z + 3.5))):
                w.ubox(x, y, z, 2.5, 6.0, 2.6, "MetalPlate", rng.choice([(0.85, 0.25, 0.2), (0.2, 0.45, 0.8), (0.95, 0.65, 0.15), (0.25, 0.6, 0.35)]), yaw=yaw)
        else:
            p0 = np.array([x, y, z])
            p1 = p0 + fwd(yaw) * rng.uniform(8, 20)
            if w.free(AABB(np.minimum(p0, p1) - 1, np.maximum(p0, p1) + 1)):
                w.cyl(p0, p1, rng.uniform(0.5, 1.2), "metal_7", (0.8, 0.6, 0.5))


def deco_beanstalk(w, rng, centre, y0, top):
    ys = np.arange(y0 - 30, top + 25, 4)                   # the giant stalk, twisting up the zone's axis
    for i, y in enumerate(ys):
        tw = i * 0.22
        x, z = centre[0] + math.sin(tw) * 3, centre[1] + math.cos(tw) * 3
        d = 7.5 - 2.5 * (y - y0) / (top - y0 + 30)
        if w.free(AABB((x - d / 2, y, z - d / 2), (x + d / 2, y + 4.5, z + d / 2)), pad=0.1):
            w.vcyl(x, y, z, d, 4.6, "leaf_1", (0.45, 0.8, 0.3))
        if i % 3 == 0:                                      # big leaves sticking out
            ang = i * 77
            p0 = np.array([x, y + 2, z])
            p1 = p0 + fwd(ang) * rng.uniform(8, 14) + UP * 2
            if w.free(AABB(np.minimum(p0, p1) - 2.5, np.maximum(p0, p1) + 2.5)):
                w.ell((p0 + p1) / 2, 4, 0.4, 10, "leaf_2", (0.5, 0.9, 0.35), yaw=ang)
    segs = 70                                              # the dragon coiling around it
    for i in range(segs):
        t = i / segs
        ang = t * 4.2 * math.pi
        rad = 32 + 6 * math.sin(t * 9)
        y = y0 + 20 + t * (top - y0 - 30)
        c = np.array([centre[0] + math.sin(ang) * rad, y, centre[1] + math.cos(ang) * rad])
        d = 4.2 - 2.6 * t if i > 2 else 4.2
        if w.free(bbox(c, (d / 2, d / 2, d / 2)), pad=0.2):
            w.ell(c, d, d * 0.9, d, "MetalPaintRed", (0.85, 0.15, 0.1))
            if i % 2 == 0:
                w.shape("Cone", c + UP * d * 0.35, d * 0.35, d * 0.35, d * 0.7, "gold", GOLD)
        hdg = math.degrees(ang) + 90
        if i == 0:
            head = c + UP * 1.5
            if w.free(bbox(head + fwd(hdg) * 3, (4, 3, 4))):
                w.ell(head + fwd(hdg) * 3, 5, 3.4, 7, "MetalPaintRed", (0.9, 0.15, 0.1), yaw=hdg)
                for s in (-1, 1):
                    w.shape("Cone", head + right_of(hdg) * s * 1.5 + UP * 1.4, 0.8, 0.8, 3.5, "gold", GOLD)
                    w.ell(head + right_of(hdg) * s * 1.6 + fwd(hdg) * 4.5 + UP * 0.8, 0.9, 0.9, 0.9, "Illum FLAT", (1, 0.9, 0.2))
        if i in (10, 11):
            for s in (-1, 1):
                wing0 = c + UP * 1
                wing1 = wing0 + right_of(math.degrees(ang)) * s * 16 + UP * 8
                if w.free(AABB(np.minimum(wing0, wing1) - 4, np.maximum(wing0, wing1) + 4)):
                    w.beam(wing0, wing1, 8, 0.25, "MetalPaintRed", (0.6, 0.08, 0.06))


def deco_clouds(w, rng, centre, y0, top):
    for _ in range(int(80 * DENSITY)):
        x, z = ring(rng, centre, 15, 70)
        c = np.array([x, rng.uniform(y0 - 20, top + 10), z])
        for _k in range(rng.randint(3, 7)):
            q = c + np.array([rng.uniform(-6, 6), rng.uniform(-1.5, 1.5), rng.uniform(-6, 6)])
            s = rng.uniform(3, 8)
            if w.free(bbox(q, (s / 2, s * 0.3, s / 2))):
                w.ell(q, s, s * 0.6, s, "Fabric2", (1, 1, 1))


def deco_japan(w, rng, centre, y0, top):
    for _ in range(int(24 * DENSITY)):                                    # pagodas on floating rocks
        x, z = ring(rng, centre, 22, 60)
        y = rng.uniform(y0, top - 10)
        tiers = rng.randint(3, 6)
        if not w.free(AABB((x - 8, y - 14, z - 8), (x + 8, y + tiers * 3.4 + 4, z + 8))):
            continue
        yaw = rng.random() * 90
        w.ubox(x, y - 0.6, z, 14, 14, 0.6, "grass_1", (0.7, 0.9, 0.6), yaw=yaw)
        w.hang("Pyramid", (x, y - 0.6, z), 14, 14, 12, "rock_11", (0.75, 0.65, 0.6), yaw=yaw)
        for t in range(tiers):
            s = 7 - t * 0.9
            yy = y + t * 3.4
            w.ubox(x, yy, z, s * 0.7, s * 0.7, 2.6, "WoodSequoia", (0.9, 0.35, 0.25), yaw=yaw)
            w.shape("Pyramid", (x, yy + 2.6, z), s * 1.25, s * 1.25, 1.2, "roof_2", (0.25, 0.25, 0.3), yaw=yaw)
        w.shape("Cone", (x, y + tiers * 3.4 + 1, z), 0.4, 0.4, 3.5, "gold", GOLD)
    for _ in range(int(45 * DENSITY)):                                    # cherry trees on little rocks
        x, z = ring(rng, centre, 12, 55)
        y = rng.uniform(y0, top)
        if not w.free(AABB((x - 3, y - 4, z - 3), (x + 3, y + 6.5, z + 3))):
            continue
        w.ell((x, y - 2, z), 5, 3, 5, "rock_11", (0.75, 0.65, 0.6))
        w.vcyl(x, y - 0.5, z, 0.45, 3.5, "bark_1", (0.5, 0.35, 0.3))
        w.ell((x, y + 4.2, z), 5, 3.4, 5, "Fabric1", (1, 0.7, 0.85))
        w.ell((x + 1.2, y + 3.4, z - 0.8), 3.5, 2.4, 3.5, "Fabric1", (1, 0.6, 0.8))


def deco_desert(w, rng, centre, y0, top):
    for _ in range(int(60 * DENSITY)):
        x, z = ring(rng, centre, 15, 60)
        y = rng.uniform(y0 - 5, top)
        kind = rng.random()
        if kind < 0.45:                                     # floating dune islands with palms
            s = rng.uniform(8, 16)
            if not w.free(AABB((x - s / 2, y - 8, z - s / 2), (x + s / 2, y + 9, z + s / 2))):
                continue
            yaw = rng.random() * 90
            w.ubox(x, y - 0.6, z, s, s, 0.6, "sand_1", (1, 0.9, 0.7), yaw=yaw)
            w.hang("Cone", (x, y - 0.6, z), s, s, rng.uniform(5, 9), "Rock_CliffDesert4", yaw=yaw)
            for _k in range(rng.randint(1, 3)):
                w.prop("CoconutPalmTree01", (x + rng.uniform(-s / 3, s / 3), y, z + rng.uniform(-s / 3, s / 3)),
                       rng.random() * 360, rng.uniform(0.8, 1.3))
        elif kind < 0.7:                                    # obelisks
            h = rng.uniform(10, 22)
            if not w.free(AABB((x - 1.2, y, z - 1.2), (x + 1.2, y + h + 2, z + 1.2))):
                continue
            w.ubox(x, y, z, 1.8, 1.8, h, "stones_5", (1, 0.88, 0.62))
            w.shape("Pyramid", (x, y + h, z), 1.8, 1.8, 1.6, "gold", GOLD)
        else:                                               # far pyramids
            s = rng.uniform(14, 30)
            if not w.free(AABB((x - s / 2, y, z - s / 2), (x + s / 2, y + s * 0.7, z + s / 2))):
                continue
            w.shape("Pyramid", (x, y, z), s, s, s * 0.65, "stones_5", (1, 0.88, 0.62), yaw=rng.random() * 90)


def deco_planes(w, rng, centre, y0, top):
    for i in range(30):                                    # wrecked planes and rockets
        x, z = ring(rng, centre, 18, 60)
        y = rng.uniform(y0, top)
        yaw = rng.random() * 360
        if i % 3 == 2:
            h = rng.uniform(14, 26)
            if not w.free(AABB((x - 2.6, y, z - 2.6), (x + 2.6, y + h + 4, z + 2.6))):
                continue
            w.vcyl(x, y, z, 2.4, h, "MetalPaintWhite")
            w.shape("Cone", (x, y + h, z), 2.4, 2.4, 4, "MetalPaintRed", (0.9, 0.2, 0.2))
            for k in range(4):
                w.beam((x, y + 2, z), np.array([x, y, z]) + fwd(k * 90) * 2.4, 0.2, 1.4, "MetalPaintRed", (0.9, 0.2, 0.2))
            continue
        Fp = fwd(yaw)
        L = rng.uniform(16, 26)
        A = np.array([x, y, z]) - Fp * L / 2
        B = A + Fp * L + UP * rng.uniform(-3, 3)
        if not w.free(AABB(np.minimum(A, B) - 9, np.maximum(A, B) + 9)):
            continue
        col = rng.choice([(0.92, 0.92, 0.95), (0.55, 0.6, 0.45), (0.7, 0.72, 0.75)])
        w.cyl(A, B, 3.6, "MetalPaintWhite", col)
        w.cyl(B, B + norm(B - A) * 3, 3.6, "MetalPaintWhite", col, name="Cone")
        mid = (A + B) / 2
        R = right_of(yaw)
        w.beam(mid - R * 11, mid + R * 11, 3.2, 0.3, "MetalPaintWhite", col)
        w.beam(A + R * 4 + UP * 0.5, A - R * 4 + UP * 0.5, 1.6, 0.2, "MetalPaintWhite", col)


def deco_pirates(w, rng, centre, y0, top):
    for _ in range(int(14 * DENSITY)):                     # the fleet
        x, z = ring(rng, centre, 28, 70)
        hd = rng.random() * 360
        stern = np.array([x, rng.uniform(y0 - 10, top), z]) - fwd(hd) * 11
        if w.free_all(galleon(w, rng, stern, hd, build=False) + [corners_aabb(stern - UP * 6, *basis_upright(hd), 8, 26, 24)]):
            galleon(w, rng, stern, hd)
    for i in range(36):
        x, z = ring(rng, centre, 20, 60)
        y = rng.uniform(y0, top)
        c = np.array([x, y, z])
        if i % 2:                                           # treasure chests on cloud puffs
            if w.free(bbox(c, (3, 2.5, 3))):
                w.ell(c - UP * 1, 5, 2, 5, "Fabric2", (1, 1, 1))
                w.ubox(x, y, z, 1.6, 1.0, 1.0, "WoodTeakX")
                w.ell(c + UP * 1.0, 1.6, 0.6, 1.0, "gold", GOLD)
        else:                                               # floating barrels
            if w.free(bbox(c, (1, 1.2, 1))):
                w.vcyl(x, y, z, 1.2, 1.6, "WoodWalnutX", (0.55, 0.35, 0.25))
                w.vcyl(x, y + 0.3, z, 1.25, 0.12, "metal_10")
                w.vcyl(x, y + 1.2, z, 1.25, 0.12, "metal_10")


def deco_garden(w, rng, centre, y0, top):
    for i in range(70):
        x, z = ring(rng, centre, 15, 60)
        y = rng.uniform(y0, top)
        c = np.array([x, y, z])
        if i % 3 == 0:                                      # giant toadstools
            if w.free(AABB(c - np.array([5, 12, 5]), c + np.array([5, 3, 5]))):
                w.vcyl(x, y - 12, z, 1.6, 12, "PlasterStucco", (1, 0.97, 0.9))
                w.ell(c + UP * 0.8, 9, 3.5, 9, "Fabric1", (0.9, 0.15, 0.12))
                for _k in range(6):
                    w.ell(c + UP * 1.9 + fwd(rng.random() * 360) * rng.uniform(1, 3.5), 1.2, 0.5, 1.2, "PlasterStucco", (1, 1, 1))
        else:                                               # flowers on tall stems
            col = rng.choice(FLOWERS)
            if w.free(AABB(c - np.array([5, 20, 5]), c + np.array([5, 1.5, 5]))):
                w.vcyl(x, y - 20, z, 0.7, 20, "leaf_1", (0.4, 0.75, 0.3))
                w.ell(c, 2.4, 1.2, 2.4, "Fabric1", (1, 0.85, 0.2))
                for k in range(6):
                    w.ell(c + fwd(k * 60) * 2.6, 2.4, 0.4, 3.6, "Fabric1", col, yaw=k * 60)
                a = rng.random() * 360
                w.ell(c - UP * 9 + fwd(a) * 2.5, 1.6, 0.3, 5, "leaf_2", (0.5, 0.9, 0.35), yaw=a)


def deco_heaven(w, rng, centre, y0, top):
    for _ in range(int(90 * DENSITY)):                                    # cloud banks
        x, z = ring(rng, centre, 15, 65)
        c = np.array([x, rng.uniform(y0 - 15, top), z])
        s = rng.uniform(4, 10)
        if w.free(bbox(c, (s / 2, s * 0.25, s / 2))):
            w.ell(c, s, s * 0.5, s, "Fabric2", (1, 1, 1))
    for i in range(4):                                     # temples with golden domes
        a = i / 4 * 2 * math.pi + 0.4
        c = np.array([centre[0] + math.sin(a) * 48, y0 + (top - y0) * (0.25 + 0.2 * i), centre[1] + math.cos(a) * 48])
        if not w.free(AABB(c - np.array([9.5, 1.5, 9.5]), c + np.array([9.5, 14, 9.5]))):
            continue
        w.ubox(c[0], c[1] - 1, c[2], 18, 18, 1, "Marble", (1, 1, 1))
        for k in range(12):
            aa = k / 12 * 2 * math.pi
            w.vcyl(c[0] + math.sin(aa) * 7, c[1], c[2] + math.cos(aa) * 7, 0.9, 8, "Marble", (1, 1, 1))
        w.vcyl(c[0], c[1] + 8, c[2], 16, 0.8, "Marble", (1, 1, 1))
        w.ell(c + UP * 8.8, 12, 9, 12, "gold", GOLD)


def deco_space(w, rng, centre, y0, top):
    for _ in range(int(80 * DENSITY)):                                    # asteroids
        x, z = ring(rng, centre, 15, 80)
        c = np.array([x, rng.uniform(y0, top + 40), z])
        s = rng.uniform(2, 9)
        if w.free(bbox(c, (s * 0.6, s * 0.5, s * 0.6))):
            w.ell(c, s, s * rng.uniform(0.6, 1), s * rng.uniform(0.7, 1.2), "rock_3", (0.35, 0.33, 0.32), yaw=rng.random() * 360)
    for _ in range(9):                                     # satellites
        x, z = ring(rng, centre, 25, 50)
        c = np.array([x, rng.uniform(y0, top), z])
        if not w.free(bbox(c, (9, 3, 9))):
            continue
        w.ubox(c[0], c[1] - 1.5, c[2], 3, 3, 3, "gold", GOLD)
        yaw = rng.random() * 360
        for s in (-1, 1):
            w.beam(c + right_of(yaw) * s * 1.5, c + right_of(yaw) * s * 8, 3, 0.1, "glass_4", (0.2, 0.35, 0.9))
        w.ell(c + UP * 2.5, 2.4, 0.6, 2.4, "MetalPaintWhite", (1, 1, 1))
    pc = np.array([centre[0] + 130, y0 + 60, centre[1] - 100])  # a ringed planet out in the void
    w.ell(pc, 60, 60, 60, "MetalPaintBlue", (0.55, 0.45, 0.85))
    w.cyl(pc - UP * 0.4, pc + UP * 0.4, 110, "Illum FLAT", (0.85, 0.7, 1.0), name="Tube")


# ---------------------------------------------------------------- special moves
def make_specials(w, rng):
    def pyramid_climb(r):
        """Climb the face of a giant pyramid by its stairs."""
        F = fwd(r.h)
        n, run = 60, 0.32
        A = r.p.copy()
        B = A + F * run * n + UP * STEP * n
        height = STEP * n
        half = height / math.tan(math.radians(36))
        base_c = A + F * half - UP * 0.6
        bb = AABB(base_c - np.array([half + 1, 0, half + 1]), base_c + np.array([half + 1, height + 2, half + 1]))
        recent = w.recent(3)
        if r.would_hit(A, B, r.width) or w.route.hit(bb, ignore=recent) or w.solid.hit(bb, ignore=recent):
            return False
        X, Y, Z = basis_upright(r.h)
        w.obj("Pyramid", base_c, X, Y, Z, (2 * half + 1.2, 2 * half + 1.2, height + 0.4), "stones_5", (1, 0.88, 0.62))
        r.stairs(n, run)
        for k in range(8):                                    # reserve it as stepped layers, all below the summit
            y_lo, y_hi = base_c[1] + height * k / 8, base_c[1] + height * (k + 1) / 8
            hk = half * (1 - k / 8) + 0.6
            w.solid.add(AABB((base_c[0] - hk, y_lo, base_c[2] - hk), (base_c[0] + hk, min(y_hi, B[1] - 0.6), base_c[2] + hk)), -1)
        r.landing(3.0, turn=90)
        return True

    def dino_spine(r):
        """Walk a dinosaur skeleton's spine: narrow bone path, ribs hanging below, skull ahead."""
        F = fwd(r.h)
        L, rise = 26, 4.5
        A = r.p.copy()
        B = A + F * L + UP * rise
        if r.would_hit(A, B, 3.5):
            return False
        old = r.style
        r.style = Style(w, "PlasterStucco", BONE, thick=0.45)
        r.ramp(L, rise, width=0.9)
        R = right_of(r.h)
        for t in np.linspace(0.08, 0.92, 12):
            q = A + (B - A) * t - UP * 0.5
            w.ell(q, 1.1, 0.9, 1.1, "PlasterStucco", BONE)
            for s in (-1, 1):
                w.cyl(q, q + R * s * 2.4 - UP * 2.0, 0.28, "PlasterStucco", BONE)
                w.cyl(q + R * s * 2.4 - UP * 2.0, q + R * s * 1.2 - UP * 4.2, 0.25, "PlasterStucco", BONE)
        r.style = old
        hb = r.h
        C = r.landing(3.0, turn=rng.choice([-90, 90]))
        skull = C + fwd(hb) * 4.2 - UP * 0.2
        if w.free(bbox(skull, (2.4, 1.4, 2.4)), recent=2):
            w.ell(skull, 3.0, 2.4, 4.2, "PlasterStucco", BONE, yaw=hb)
            for s in (-1, 1):
                w.ell(skull + fwd(hb) * 0.9 + right_of(hb) * s * 0.8 + UP * 0.6, 0.7, 0.7, 0.7, "rock_3", (0.05, 0.05, 0.05))
        for k in range(10):                                  # the tail hanging behind
            q = A - F * (k * 1.6) - UP * (k * 0.9 + 0.8)
            if w.free(bbox(q, (0.6, 0.5, 0.6)), recent=3):
                w.ell(q, 1.0 - k * 0.07, 0.8 - k * 0.05, 1.0 - k * 0.07, "PlasterStucco", BONE)
        return True

    def ship_deck(r):
        """Board a flying pirate galleon at the stern and walk its deck to the bow."""
        F = fwd(r.h)
        A = r.p.copy()
        L = 22.0
        if r.would_hit(A, A + F * (L + 2.5), 3.2):
            return False
        parts = galleon(w, rng, A, r.h, L, walkway=3.0, build=False)
        if any(w.route.hit(b) or w.solid.hit(b) for b in parts):
            return False
        galleon(w, rng, A, r.h, L, walkway=3.0)
        B = A + F * L
        r._register(A, B, 3.0)
        r.log.append(("walk", A.copy(), B.copy(), 3.0))
        r.in_dir = F
        r.p = B
        for b in parts:
            w.solid.add(b, -1)
        r.landing(2.4)                                       # step off the bowsprit
        return True

    def sword_bridge(r):
        """Cross a killer whale on the swords stuck in its back."""
        F = fwd(r.h)
        A = r.p.copy()
        mid = A + F * 15 - UP * 9
        if not w.free(bbox(mid, (16, 6.5, 16)), recent=2):
            return False
        old = r.style
        r.style = Style(w, "chrome", (0.85, 0.87, 0.9), thick=0.15)
        made = 0
        for _k in range(3):
            L, rise = rng.uniform(7, 10), rng.uniform(1.0, 2.5)
            if r.would_hit(r.p, r.p + F * L + UP * rise, 0.8):
                break
            hilt = r.p.copy()
            r.ramp(L, rise, width=0.8)
            w.beam(hilt - fwd(r.h + 90) * 0.7, hilt + fwd(r.h + 90) * 0.7, 0.3, 0.3, "gold", GOLD)
            r.landing(1.6)
            made += 1
        r.style = old
        yaw = r.h
        w.ell(mid, 9, 8, 26, "rock_3", (0.04, 0.04, 0.05), yaw=yaw)                         # body
        w.ell(mid - UP * 2 + F * 2, 7.6, 5, 22, "PlasterStucco", (0.98, 0.98, 0.98), yaw=yaw)   # white belly
        for s in (-1, 1):
            w.ell(mid + F * 9 + right_of(yaw) * s * 3.2 + UP * 1.5, 1.4, 1.0, 2.6, "PlasterStucco", (1, 1, 1), yaw=yaw)
        w.beam(mid + UP * 3.5 - right_of(yaw) * 2.5, mid + UP * 8 - F * 3 - right_of(yaw) * 2.5, 0.6, 3.5, "rock_3", (0.04, 0.04, 0.05))
        tail = mid - F * 14
        w.beam(tail - right_of(yaw) * 6, tail + right_of(yaw) * 6, 3, 0.6, "rock_3", (0.04, 0.04, 0.05))
        return made > 0

    return pyramid_climb, dino_spine, sword_bridge, ship_deck


# ============================================================ build
def build(seed=7):
    w = World(seed)
    rng = w.rng

    # ------------------------------------------------------------ hub (ground)
    w.begin()
    w.ubox(0, -2, 0, 700, 700, 2, "asphalt_1", (0.55, 0.52, 0.5))             # the ground everything falls onto
    w.ubox(0, -0.02, 0, 46, 46, 0.04, "PavementCobblestone2")
    for i in range(14):                                                         # junk piles, cars, tyres, barrels
        a = i / 14 * 2 * math.pi
        rr = 30 + rng.random() * 25
        x, z = math.sin(a) * rr, math.cos(a) * rr
        if abs(x) < 17 and z < 0:                          # keep clear of the teleporter plaza behind the spawn
            x, z = math.sin(a) * (rr + 14), math.cos(a) * (rr + 14)
        if i % 3 == 0:
            w.prop("Car_03", (x, 0, z), rng.random() * 360)
        for _k in range(5):
            w.ubox(x + rng.uniform(-3, 3), rng.random() * 1.5, z + rng.uniform(-3, 3), rng.uniform(1, 2.5), rng.uniform(1, 2.5),
                   rng.uniform(0.6, 1.6), rng.choice(["metal_7", "metal_8", "WoodPlaknsOldX", "rock_9"]),
                   (rng.uniform(.6, 1), rng.uniform(.5, .9), rng.uniform(.4, .8)), yaw=rng.random() * 90)
        w.cyl((x + 2, 0.4, z - 2), (x + 2, 0.4, z - 1.4), 1.0, "rock_3", (0.15, 0.15, 0.15), name="Tube")
        w.vcyl(x - 2, 0, z + 2, 0.7, 1.0, "MetalPaintBlue" if i % 2 else "MetalPaintRed")
    # the big sign north of the start, raised on posts so the route can pass beneath; spawn faces it
    text(w, (0, 12.5, 16), 0, "ONLY UP!", px=0.6, color=(1, 0.75, 0.1), board=("metal_10", (0.15, 0.15, 0.18)))
    text(w, (0, 7.6, 16), 0, "THE ONLY WAY IS UP\nDON'T LOOK DOWN", px=0.22, color=(1, 1, 1), board=("metal_10", (0.15, 0.15, 0.18)))
    text(w, (0, 4.6, 16), 0, "BY KINGCOLOSSUS", px=0.14, color=(1, 0.75, 0.1), board=("metal_10", (0.15, 0.15, 0.18)))
    w.solid.add(AABB((-3.5, 3.8, 15.5), (3.5, 5.5, 17)), -1)
    for sx in (-6, 6):
        w.vcyl(sx, 0, 16.4, 0.4, 15.5, "metal_4")
        w.solid.add(AABB((sx - 0.4, 0, 15.9), (sx + 0.4, 16, 16.9)), -1)
    w.solid.add(AABB((-16, 5.8, 15.5), (16, 16.5, 17)), -1)
    w.keepout.append(AABB((-18, -1, -14), (18, 18, 18)))                      # spawn -> sign: nothing in the way
    w.keepout.append(AABB((-PLAZA_R - 4, -1, PLAZA_C[2] - PLAZA_R - 6), (PLAZA_R + 4, 12, PLAZA_C[2] + PLAZA_R + 3)))
    w.solid.add(AABB((-PLAZA_R - 4, -1, PLAZA_C[2] - PLAZA_R - 6), (PLAZA_R + 4, 12, PLAZA_C[2] + PLAZA_R + 3)), -1)
    arrivals = {}                                                               # zone -> (portal pos, yaw, start height)

    r = Route(w, (0, 0.0, 4), 90.0)
    respawn = {"p": [0.0, 0.15, -6.0], "r": 0.0}
    pyramid_climb, dino_spine, sword_bridge, ship_deck = make_specials(w, rng)

    STD = [("stairs", 4), ("ramp", 3), ("walk", 2), ("turn", 2), ("spiral", 1)]
    zones = [
        (Favela(w, "WoodPlaknsOldX", (0.9, 0.8, 0.7), step_mat="concrete_8"), (25, 35), 26, (2.2, 1.6), STD, deco_favela, (1, 0.75, 0.2)),
        (Industrial(w, "MetalPlate", (0.7, 0.7, 0.72), edge=("MetalPaintYellow", (1, 0.8, 0.1))), (40, 75), 26, (1.6, 1.2), STD, deco_factory, (1, 0.8, 0.1)),
        (Leafy(w, "leaf_2", (0.55, 0.95, 0.35), step_mat="leaf_1", step_color=(0.45, 0.8, 0.3)), (60, 110), 22, (1.4, 1.1),
         [("stairs", 3), ("ramp", 4), ("turn", 3), ("spiral", 2)], deco_beanstalk, (0.5, 1, 0.4)),
        (Cloudy(w, "Fabric2"), (80, 145), 24, (1.2, 0.9), [("stairs", 3), ("ramp", 3), ("walk", 3), ("turn", 2)], deco_clouds, (0.7, 0.9, 1)),
        (Japan(w, "WoodSequoia", (0.95, 0.5, 0.35), edge=("MetalPaintRed", RED)), (100, 185), 24, (1.3, 0.9), STD, deco_japan, (1, 0.35, 0.25)),
        (Desert(w, "stones_5", (1, 0.88, 0.62)), (125, 235), 26, (1.2, 0.85),
         [("stairs", 3), ("ramp", 3), ("walk", 2), ("turn", 2), (pyramid_climb, 0.6), (dino_spine, 0.7)], deco_desert, (1, 0.8, 0.4)),
        (Plane(w, "MetalPaintWhite"), (155, 265), 26, (1.6, 1.0), STD, deco_planes, (0.85, 0.9, 1)),
        (Ship(w, "WoodTeakX", (1, 0.9, 0.8)), (185, 295), 26, (1.1, 0.8),
         [("stairs", 3), ("ramp", 3), ("walk", 2), ("turn", 2), (sword_bridge, 0.7), (ship_deck, 1.2)], deco_pirates, (1, 0.85, 0.3)),
        (Garden(w, "leaf_2", (0.5, 0.9, 0.35), step_mat="Fabric1", step_color=(1, 0.6, 0.75)), (215, 325), 24, (1.0, 0.75), STD, deco_garden, (1, 0.5, 0.8)),
        (Heaven(w, "Marble", (1, 1, 1), edge=("gold", GOLD), step_mat="Marble"), (245, 355), 22, (1.0, 0.7), STD, deco_heaven, (1, 0.9, 0.5)),
        (Space(w, "TileSciFi2_met"), (275, 385), 24, (1.0, 0.75), STD, deco_space, (0.3, 0.9, 1)),
    ]
    stuck_total = 0
    for zi, (style, centre, rmax, widths, menu, decorate, sign_col) in enumerate(zones, start=1):
        name, top = ZONES[zi]
        w.begin()
        r.style = style
        y0 = r.p[1]
        # zone title on a turning landing, sign straight ahead (the route turns away)
        r.width = max(widths[0], 2.5)
        pre_title = w.snapshot(r)
        title_tries = 0

        def lay_title(C=None):
            F_in = r.in_dir.copy()
            C = r.landing(5.0, turn=rng.choice([-90, 0, 90]) if title_tries else rng.choice([-90, 90]), kind="title")
        # zone sign just off the landing's outer edge and below it: the route only climbs, so nothing below
        # the surface can ever be in its way; read looking out and down
            out_dir = norm(np.array([C[0] - centre[0], 0, C[2] - centre[1]]))
            sh = math.degrees(math.atan2(out_dir[0], out_dir[2])) % 360
            spot = C + out_dir * (5.0 * 0.75 + 0.6) - UP * 1.5
            if w.free(sign_bbox(spot - UP * 0.8, sh, len(name), 2, 0.17), recent=2):
                text(w, spot, sh, name, px=0.17, color=sign_col, board=("metal_10", (0.08, 0.08, 0.1)))
                text(w, spot - UP * 1.45, sh, f"{int(round(y0))} M", px=0.1, color=(1, 1, 1), board=("metal_10", (0.08, 0.08, 0.1)))
            # teleporter arrival: a dead-end pad beside the landing, off the way through it
            out_h = r.h
            opts = [C - fwd(out_h) * 4.0]                     # opposite the way out
            if abs(((out_h - heading_of(F_in) + 540) % 360) - 180) > 10:
                opts.append(C + F_in * 4.0)                   # straight on, when the way out turns off
            for q in opts:
                head = AABB(q - np.array([1.3, 0, 1.3]), q + np.array([1.3, HEADROOM, 1.3]))
                slab = bbox(q - UP * 0.2, (1.5, 0.2, 1.5))
                if not (w.route.hit(head) or w.solid.hit(head) or w.route.hit(slab)):
                    r.style.pad(w, q, 3.0, heading_of(C - q))
                    w.solid.add(slab, -1)
                    w.route.add(head, -2)                     # kept clear like the route
                    arrivals[zi] = (q + UP * 0.5, heading_of(C - q), y0)
                    break
            else:                                             # no room: the landing's quiet back corner
                side = -fwd(out_h) if len(opts) > 1 else right_of(heading_of(F_in))
                q = C - F_in * 1.7 + side * 1.7
                arrivals[zi] = (q + UP * 0.5, heading_of(C - q), y0)

        lay_title()
        next_marker = (int(y0 // 100) + 1) * 100
        fails = 0
        rtarget = rmax * 0.65                       # the route orbits the zone's axis at about this radius
        history = [w.snapshot(r, next_marker)]      # state before each successful move, for backtracking
        backtracks, depth = 0, 0
        while r.p[1] < top - 0.5:
            if fails > 40:                          # boxed in: undo ever more of the climb and try again
                if backtracks >= 400:
                    print(f"    stuck: backtracks {backtracks} title_tries {title_tries} history {len(history)} at {r.p.round(1)}", flush=True)
                    stuck_total += 1
                    break
                backtracks += 1
                depth = min(depth + 2, 24)
                k = min(depth, len(history) - 1)
                if backtracks % 12 == 0 and r.p[1] - y0 < 4:   # not getting off the start: re-lay the title landing differently
                    title_tries += 1
                    w.restore(r, pre_title)
                    r.h = (r.h + rng.choice([-45, 0, 45])) % 360
                    if title_tries % 2 == 0:         # or step off the previous zone's end first
                        r.pivot(rng.choice([-90, 90]))
                    lay_title()
                    history = [w.snapshot(r, (int(y0 // 100) + 1) * 100)]
                    depth, fails = 0, 0
                    continue
                snap = history[-k - 1] if k else history[0]
                del history[len(history) - k:]
                next_marker, = w.restore(r, snap)
                r.h = (r.h + rng.choice([-90, -45, 45, 90, 180])) % 360
                fails = 0
                continue
            frac = min(1.0, (r.p[1] - y0) / max(1, top - y0))
            r.width = widths[0] + (widths[1] - widths[0]) * frac
            F = fwd(r.h)
            off = np.array([r.p[0] - centre[0], 0, r.p[2] - centre[1]])
            dist = np.linalg.norm(off)
            ang = math.degrees(math.atan2(off[0], off[2]))
            # counter-clockwise tangent, bent inwards when too far out and outwards when too close
            corr = max(-90.0, min(90.0, (dist - rtarget) / rtarget * 80.0))
            desired = (ang + 90.0 + corr) % 360
            diff = ((desired - r.h + 540) % 360) - 180
            move = rng.choices([m[0] for m in menu], weights=[m[1] for m in menu])[0]
            if abs(diff) > 35 or move == "turn":
                if fails % 3 == 2:                  # boxed in: try anything, including turning back
                    turn = rng.choice([-135, -90, -45, 45, 90, 135, 180])
                else:
                    turn = max(-90, min(90, round(diff / 45) * 45)) or rng.choice([-45, 45])
                size = max(2.2, r.width + 0.8)
                if r.would_hit(r.p, r.p + r.in_dir * size, size):
                    r.pivot(turn)
                    fails += 1
                    continue
                hb = r.h
                history.append(w.snapshot(r, next_marker))
                C = r.landing(size, turn=turn)
                if C[1] >= next_marker and next_marker < top - 5:
                    od = norm(np.array([C[0] - centre[0], 0, C[2] - centre[1]]))
                    sh = math.degrees(math.atan2(od[0], od[2])) % 360
                    spot = C + od * (size * 0.75 + 0.6) - UP * 1.6      # below the landing, out of the climb's way
                    label = f"{next_marker} M"
                    if w.free(sign_bbox(spot, sh, len(label), 1, 0.18), recent=2):
                        text(w, spot, sh, label, px=0.18, color=(1, 1, 1), board=("metal_10", (0.1, 0.1, 0.12)))
                    next_marker += 100
                continue
            nudge = rng.choice([-45, 45]) if abs(diff) < 10 else (45 if diff > 0 else -45)
            if move == "stairs":
                n = min(rng.randint(6, 18), max(1, int((top - r.p[1]) / STEP) + 1))
                run = rng.choice([0.3, 0.32, 0.36, 0.4])
                if r.would_hit(r.p, r.p + F * run * n + UP * STEP * n, r.width):
                    r.pivot(nudge)
                    fails += 1
                    continue
                history.append(w.snapshot(r, next_marker))
                r.stairs(n, run)
            elif move == "ramp":
                L = rng.uniform(5, 12)
                rise = min(L * math.tan(math.radians(rng.uniform(12, MAX_SLOPE))), top - r.p[1] + 0.3)
                if r.would_hit(r.p, r.p + F * L + UP * rise, r.width):
                    r.pivot(nudge)
                    fails += 1
                    continue
                history.append(w.snapshot(r, next_marker))
                r.ramp(L, rise)
            elif move == "walk":
                L = rng.uniform(4, 10)
                if r.would_hit(r.p, r.p + F * L, r.width):
                    r.pivot(nudge)
                    fails += 1
                    continue
                history.append(w.snapshot(r, next_marker))
                r.walk(L)
            elif move == "spiral":
                steps = min(rng.randint(20, 44), int((top - r.p[1]) / STEP) + 1)
                rad = rng.uniform(2.6, 4.0)
                d = rng.choice([-1, 1])
                if not r.spiral_fits(rad, steps, d, max(r.width, 1.2)):
                    r.pivot(nudge)
                    fails += 1
                    continue
                history.append(w.snapshot(r, next_marker))
                r.width = max(r.width, 1.2)
                r.spiral(rad, steps, d)
                r.landing(max(2.2, r.width + 0.6))
            elif callable(move):
                history.append(w.snapshot(r, next_marker))
                if not move(r):
                    w.restore(r, history.pop())
                    r.pivot(nudge)
                    fails += 1
                    continue
            fails = 0
            depth = max(0, depth - 1)
        # keep this zone's scenery out of the air the next zone has to climb through
        if zi < len(zones):
            nc, nr = zones[zi][1], zones[zi][2]
            lo = np.minimum([r.p[0] - 30, 0, r.p[2] - 30], [nc[0] - nr - 8, 0, nc[1] - nr - 8])
            hi = np.maximum([r.p[0] + 30, 1e5, r.p[2] + 30], [nc[0] + nr + 8, 1e5, nc[1] + nr + 8])
            w.guard = (AABB(lo, hi), r.p[1] - 1.0)
        decorate(w, rng, centre, y0, top)
        w.guard = None
        print(f"  {name:<16} {y0:7.1f} -> {r.p[1]:7.1f} m   objects {w.count:6d}", flush=True)

    # ------------------------------------------------------------ the Moon + summit
    w.begin()
    r.style = Space(w, "TileSciFi2_met")
    r.width = 1.2
    r.walk(10)
    hb = r.h
    C = r.landing(8.0, kind="summit")
    moon_c = None
    for dist in (75, 95, 120, 150):
        for k in range(18):
            q = C + fwd(hb + 180 + k * 20) * dist - UP * 15
            if w.free(bbox(q, (46, 46, 46))):
                moon_c = q
                break
        if moon_c is not None:
            break
    if moon_c is None:
        moon_c = C + fwd(hb) * 200
    w.ell(moon_c, 90, 90, 90, "rock_2", (0.85, 0.85, 0.88))
    for _k in range(40):                                    # craters
        a, b = rng.random() * 2 * math.pi, rng.uniform(0.25, 1.3)
        n = np.array([math.sin(a) * math.sin(b), math.cos(b), math.cos(a) * math.sin(b)])
        q = moon_c + n * 44.6
        if w.free(bbox(q, (4, 4, 4))):
            s = rng.uniform(3, 9)
            w.ell(q, s, s * 0.3, s, "rock_1", (0.55, 0.55, 0.58))
    flag = C + right_of(hb) * 3.0
    w.vcyl(flag[0], C[1], flag[2], 0.12, 5.0, "metal_9")
    w.beam(flag + UP * 4.9, flag + UP * 4.9 + fwd(hb + 90) * 2.6, 1.6, 0.05, "Illum FLAT", (1, 0.75, 0.1))
    text(w, C + fwd(hb) * 5 + UP * 5.0, hb, "YOU MADE IT!", px=0.32, color=(1, 0.8, 0.1), board=("metal_10", (0.05, 0.05, 0.08)))
    text(w, C + fwd(hb) * 5 + UP * 7.1, hb, "ONLY UP!  BY KINGCOLOSSUS", px=0.12, color=(1, 1, 1), board=("metal_10", (0.05, 0.05, 0.08)))
    text(w, C + fwd(hb) * 5 + UP * 2.6, hb, f"{int(round(C[1]))} M - STEP ON THE PORTAL\nTO GO BACK DOWN", px=0.13,
         color=(1, 1, 1), board=("metal_10", (0.05, 0.05, 0.08)))
    summit = C + fwd(hb) * 2.2

    # ------------------------------------------------------------ portals: pairs in file order (entry, then exit)
    w.begin()
    w.prop("portal", summit, 180, (1, 1, 0.5), "discard")                                  # only the hexagon shows
    w.portal_glow(summit, 180, (1, 0.8, 0.2))
    w.prop("portal", (16, 0.05, 2), 180, (1, 1, 0.5), "discard")                          # arrival: unseen
    text(w, (16, 2.4, 3.2), 0, "WELCOME BACK", px=0.12, color=(1, 1, 1))

    # level select: a ring of teleporters behind the spawn, open towards it; each pairs with its level's start
    pc = PLAZA_C
    w.vcyl(pc[0], -0.03, pc[2], 2 * PLAZA_R + 5, 0.07, "metal_10", (0.22, 0.24, 0.3))
    w.vcyl(pc[0], -0.03, pc[2], 2 * PLAZA_R + 5.6, 0.05, "Illum FLAT", (0.3, 0.9, 1))
    hdr = pc + fwd(180) * (PLAZA_R + 4.2) + UP * 7.0
    text(w, hdr, 180, "TELEPORTERS", px=0.24, color=(1, 0.75, 0.1), board=("metal_10", (0.1, 0.1, 0.13)))
    text(w, hdr - UP * 2.6, 180, "PICK A LEVEL", px=0.14, color=(1, 1, 1), board=("metal_10", (0.1, 0.1, 0.13)))
    for sx in (-7.5, 7.5):
        w.vcyl(hdr[0] + sx, 0, hdr[2] + 0.3, 0.35, 8.6, "metal_4")
    for i, (zstyle, _c, _r, _w, _m, _d, col) in enumerate(zones):
        zi = i + 1
        if zi not in arrivals:
            continue
        a = 30.0 + 30.0 * i
        P = pc + fwd(a) * PLAZA_R
        w.portal_glow(P, a + 180, col)
        sign = pc + fwd(a) * (PLAZA_R + 1.5)
        text(w, sign + UP * 3.1, a, str(zi), px=0.14, color=col, board=("metal_10", (0.1, 0.1, 0.13)))
        name = ZONES[zi][0]
        text(w, sign + UP * 1.75, a, name + "\n" + f"{int(round(arrivals[zi][2]))} M", px=0.055, color=(1, 1, 1),
             board=("metal_10", (0.1, 0.1, 0.13)))
        w.vcyl(sign[0], 0, sign[2] + 0.0, 0.18, 1.2, "metal_4")
        pos, yaw, _y = arrivals[zi]
        w.prop("portal", P + UP * 0.05, a + 180, (1, 1, 0.5), "discard")   # entry: only the hexagon shows
        w.prop("portal", pos, yaw, (1, 1, 0.5), "discard")            # exit (unseen), by the level's first landing

    world = {
        "respawn": respawn,
        "ambient": [1.0] * 11,
        "oceanlevel": -10.0,
        "weather": "Sunrise",
        "valuetype": "float",
        "objects": w.groups,
    }
    return world, w, r, float(C[1]), stuck_total


def check(route):
    """Walkability report: slopes, widths and continuity of the route."""
    worst = 0.0
    narrowest = 99.0
    gaps = 0
    length = 0.0
    prev = None
    for kind, A, B, width in route.log:
        d = B - A
        horiz = math.hypot(d[0], d[2])
        length += horiz
        if kind in ("walk", "ramp") and horiz > 0.01:
            worst = max(worst, math.degrees(math.atan2(abs(d[1]), horiz)))
        if kind in ("walk", "ramp", "stairs", "spiral"):
            narrowest = min(narrowest, width)
        if prev is not None and np.linalg.norm(A - prev) > 0.6 and kind != "spiral":
            gaps += 1
            if gaps <= 8:
                print(f"    gap {np.linalg.norm(A - prev):.2f} m before {kind} at {np.round(A, 1)}")
        prev = B
    return dict(pieces=len(route.log), length_m=round(length), worst_ramp_deg=round(worst, 1), narrowest_m=round(float(narrowest), 2), gaps=gaps)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "Downloads", "Only-Up-3DX.world")
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
    print("Building ONLY UP! ...")
    world, w, route, top, stuck = build(seed)
    data = json.dumps(world, separators=(",", ":"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(data)
    print(f"Wrote {out}: {w.count:,} objects, summit {top:.0f} m, {len(data) / 1048576:.1f} MB, stuck zones: {stuck}")
    print("Route:", check(route))


if __name__ == "__main__":
    main()
