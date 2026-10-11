"""
Squid Game for 3DXChat - every game from all three seasons as playable arenas, linked by the show's own
pastel stair maze and dormitory.

  Arrival   the recruiter's subway platform (ddakji)          -> portal into the dormitory
  Hub       dormitory (bunks, piggy bank, O/X vote), stair maze with a door per game
  Season 1  Red Light Green Light, Dalgona, Tug of War, Marbles, Glass Stepping Stones, Squid Game
  Season 2  Six-Legged Pentathlon, Mingle   (Red Light Green Light is reused; Lights Out is the dormitory)
  Season 3  Hide-and-Seek, Jump Rope, Sky Squid Game
  Extras    VIP balcony over the glass bridge, coffin room for eliminated players

Nothing can kill or break in 3DXChat, so elimination is done the way 3DXChat game worlds do it: portals.
The wrong glass panels carry hidden portals; pits and floors under drops have elimination pads; everything
eliminated ends up in the coffin room, which has a portal back to the dormitory.

Usage: python squid_game.py [out.world] [--upto N] [--seed S]
"""
import json
import math
import os
import random
import sys

import numpy as np

from only_up import UP, World, basis_down, basis_upright, fwd, norm, right_of
import slutopoly
from slutopoly import plane_basis, rects, write

for _ch, _g in ((">", ["01000", "00100", "00010", "00001", "00010", "00100", "01000"]),
                (";", ["00000", "01100", "01100", "00000", "01100", "00100", "01000"]),
                ("=", ["00000", "00000", "11111", "00000", "11111", "00000", "00000"])):
    slutopoly.FONT[_ch] = _g
    slutopoly.GLYPH_RECTS[_ch] = rects(_g)

ILL = "unlit"           # flat colour, shown exactly as given (Illum washes pale colours out to white in-game)
GLOW = "Illum FLAT"     # only for things that give light: bulbs, lamps, buttons, clock digits
WHITE, BLACK = (1, 1, 1), (0.03, 0.03, 0.03)
PINK = (0.93, 0.25, 0.5)
GUARD_PINK = (0.93, 0.22, 0.45)
TRACK_GREEN = (0.05, 0.42, 0.36)
STEP, RUN = 0.25, 0.32

# ------------------------------------------------------------------ layout (arena centres, x z)
POS = {
    # the hub
    "subway": (-260, 0), "dorm": (0, 0), "coffin": (260, 0),
    # season 1, in the order they're played
    "rlgl": (-650, 320), "dalgona": (-390, 320), "tug": (-130, 320), "marbles": (130, 320), "glass": (390, 320),
    "squid": (650, 320),
    # season 2
    "pentathlon": (-130, -320), "mingle": (130, -320),
    # season 3
    "hide": (-260, -640), "jumprope": (0, -640), "sky": (260, -640),
}
SEASON_COL = {1: (0.95, 0.35, 0.55), 2: (0.3, 0.55, 0.95), 3: (0.98, 0.72, 0.15), 0: (0.55, 0.5, 0.6)}
# portal marker colours: red takes you out, gold means you made it, blue goes home, white goes up
PORTAL_COL = {"coffin": (1.0, 0.12, 0.15), "dorm": (0.25, 0.6, 1.0), "dorm_win": (1.0, 0.8, 0.2),
              "glass_win": (1.0, 0.8, 0.2), "sky_win": (1.0, 0.8, 0.2), "sky_top": (0.95, 0.95, 1.0),
              "vip": (0.75, 0.4, 1.0), "subway": (0.7, 0.7, 0.75)}
DEST_SEASON = {"rlgl": 1, "dalgona": 1, "tug": 1, "marbles": 1, "glass": 1, "squid": 1, "pentathlon": 2, "mingle": 2,
               "hide": 3, "jumprope": 3, "sky": 3}


class SG:
    """The world plus helpers in an arena's local frame."""

    def __init__(self, seed):
        self.w = World(seed)
        self.rng = random.Random(seed)
        self.o = np.zeros(3)
        self.pairs = []                 # (entry pos, entry yaw, exit pos, exit yaw, hidden)
        self.spots = {}                 # named arrival spots (world coords, yaw)

    # frame ------------------------------------------------------------
    def at(self, name):
        x, z = POS[name]
        self.o = np.array([x, 0.0, z])
        self.w.begin()

    def P(self, x, y, z):
        return self.o + np.array([x, y, z], float)

    # primitives in local coords ----------------------------------------
    def abox(self, x0, x1, y0, y1, z0, z1, mat, col=WHITE):
        x0, x1, y0, y1, z0, z1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1), min(z0, z1), max(z0, z1)
        c = self.P((x0 + x1) / 2, y0, (z0 + z1) / 2)
        self.w.ubox(c[0], c[1], c[2], x1 - x0, z1 - z0, y1 - y0, mat, col)

    def ybox(self, x, y, z, wdt, dep, h, mat, col=WHITE, yaw=0.0):
        c = self.P(x, y, z)
        self.w.ubox(c[0], c[1], c[2], wdt, dep, h, mat, col, yaw=yaw)

    def vcyl(self, x, y, z, d, h, mat, col=WHITE):
        c = self.P(x, y, z)
        self.w.vcyl(c[0], c[1], c[2], d, h, mat, col)

    def cyl(self, a, b, d, mat, col=WHITE, name="Cylinder"):
        self.w.cyl(self.P(*a), self.P(*b), d, mat, col, name)

    def ell(self, x, y, z, sx, sy, sz, mat, col=WHITE, yaw=0.0):
        self.w.ell(self.P(x, y, z), sx, sy, sz, mat, col, yaw=yaw)

    def shape(self, name, x, y, z, wd, dp, h, mat, col=WHITE, yaw=0.0):
        self.w.shape(name, self.P(x, y, z), wd, dp, h, mat, col, yaw=yaw)

    def hang(self, name, x, y, z, wd, dp, h, mat, col=WHITE, yaw=0.0):
        self.w.hang(name, self.P(x, y, z), wd, dp, h, mat, col, yaw=yaw)

    def prop(self, name, x, y, z, yaw=0.0, scale=1.0, mat=None, col=None):
        self.w.prop(name, self.P(x, y, z), yaw, scale, mat, col)

    def line(self, a, b, width, col, y=0.0, mat=ILL, thick=0.012):
        """Flat strip on the ground from a=(x,z) to b=(x,z)."""
        A, B = np.array([a[0], 0, a[1]], float), np.array([b[0], 0, b[1]], float)
        d = B - A
        L = float(np.linalg.norm(d))
        if L < 1e-6:
            return
        h = math.degrees(math.atan2(d[0], d[2]))
        m = (A + B) / 2
        self.ybox(m[0], y, m[2], width, L + width * 0.5, thick, mat, col, yaw=h)

    def ring(self, cx, cz, r, width, col, y=0.0, n=40, mat=ILL, a0=0.0, a1=360.0):
        pts = [(cx + r * math.sin(math.radians(a)), cz + r * math.cos(math.radians(a)))
               for a in np.linspace(a0, a1, n + 1)]
        for p, q in zip(pts, pts[1:]):
            self.line(p, q, width, col, y, mat)

    def poly(self, pts, width, col, y=0.0, closed=True, mat=ILL):
        seq = list(pts) + ([pts[0]] if closed else [])
        for p, q in zip(seq, seq[1:]):
            self.line(p, q, width, col, y, mat)

    # text --------------------------------------------------------------
    def sign(self, s, x, y, z, heading, px, col=WHITE, bg=(0.08, 0.08, 0.1), pad=None, mat=ILL, bgmat=ILL):
        """Upright sign read by someone looking along `heading` (the sign is in front of them)."""
        lines = s.upper().split("\n")
        W = max(len(l) for l in lines) * 6 * px
        H = (len(lines) * 8 - 1) * px
        pad = px * 4 if pad is None else pad
        c = self.P(x, y, z)
        R, F = right_of(heading), fwd(heading)
        if bg is not None:
            X, Y, Z = plane_basis(R, UP, F)
            self.w.box(c + F * 0.004, X, Y, Z, W + 2 * pad, H + 2 * pad, 0.06, bgmat, bg)
        write(self.w, s, c, R, UP, -F, px, col, mat, thick=0.012)
        return W + 2 * pad, H + 2 * pad

    def ftext(self, s, x, z, heading, px, col=WHITE, y=0.0, mat=ILL):
        """Text lying on the ground, read by someone facing `heading`."""
        write(self.w, s, self.P(x, y, z), right_of(heading), fwd(heading), UP.copy(), px, col, mat, thick=0.012, lift=0.0)

    def bitmap(self, bm, x, y, z, heading, px, col, mat=ILL, flat=False, on="1"):
        H, W = len(bm), max(len(r) for r in bm)
        R = right_of(heading)
        if flat:
            Uv, N = fwd(heading), UP.copy()
        else:
            Uv, N = UP.copy(), -fwd(heading)
        X, Y, Z = plane_basis(R, Uv, N)
        c = self.P(x, y, z)
        for (cx, cy, rw, rh) in rects(bm, on):
            o = c + R * ((cx + rw / 2 - W / 2) * px) + Uv * ((H / 2 - (cy + rh / 2)) * px)
            self.w.box(o, X, Y, Z, rw * px, rh * px, 0.012, mat, col)

    # portals -----------------------------------------------------------
    def portal(self, x, y, z, yaw, dest, label=None, hidden=False):
        """Entry pad here (local coords) leading to a named arrival spot. Unless hidden, it gets a marker: a
        glowing ring coloured by where it goes and, if labelled, a two-sided sign floating over it."""
        self.pairs.append((self.P(x, y, z), yaw, dest, hidden, label))

    def spot(self, name, x, y, z, yaw):
        self.spots[name] = (self.P(x, y, z), yaw)

    def emit_portals(self):
        self.w.begin()
        n = 0
        for entry, eyaw, dest, hidden, label in self.pairs:
            if dest not in self.spots:
                continue
            q, qyaw = self.spots[dest]
            self.w.prop("portal", entry + UP * 0.02, eyaw, (1, 1, 0.5), "discard")   # only the hexagon shows
            self.w.prop("portal", q + UP * 0.5, qyaw, (1, 1, 0.5), "discard")          # arrival: unseen
            if not hidden:
                self.marker(entry, eyaw, dest, label)
            n += 1
        return n

    def marker(self, at, yaw, dest, label):
        """A translucent coloured block exactly over the portal pad (same 1 x 1 m footprint, same turn), plus a
        floating sign if it has a destination name, so players can see it and where it goes."""
        col = PORTAL_COL.get(dest, SEASON_COL.get(DEST_SEASON.get(dest, 0)))
        w = self.w
        w.portal_glow(at, yaw, col)
        if label:                                                      # one board, the label on both faces
            lines = label.upper().split("\n")
            Wd = max(len(l) for l in lines) * 6 * 0.05 + 0.3
            Hd = (len(lines) * 8 - 1) * 0.05 + 0.3
            mid = at + UP * 2.55
            F0 = fwd(yaw)
            X, Y, Z = plane_basis(right_of(yaw), UP, F0)
            w.box(mid - F0 * 0.03, X, Y, Z, Wd, Hd, 0.06, ILL, (0.06, 0.06, 0.08))
            for h in (yaw, yaw + 180):
                F, R = fwd(h), right_of(h)
                write(w, label, mid - F * 0.035, R, UP, -F, 0.05, col, GLOW, thick=0.012)

    # common building ---------------------------------------------------
    def hall(self, x0, x1, z0, z1, h, wall_col, floor_mat, floor_col, wall_mat=ILL, ceiling=None, t=0.5, floor_y=0.0,
             north_gap=None):
        self.abox(x0 - t, x1 + t, floor_y - 0.4, floor_y, z0 - t, z1 + t, floor_mat, floor_col)
        self.abox(x0 - t, x0, floor_y, h, z0 - t, z1 + t, wall_mat, wall_col)
        self.abox(x1, x1 + t, floor_y, h, z0 - t, z1 + t, wall_mat, wall_col)
        self.abox(x0, x1, floor_y, h, z0 - t, z0, wall_mat, wall_col)
        if north_gap:
            ga, gb, gh = north_gap
            self.abox(x0, ga, floor_y, h, z1, z1 + t, wall_mat, wall_col)
            self.abox(gb, x1, floor_y, h, z1, z1 + t, wall_mat, wall_col)
            self.abox(ga, gb, gh, h, z1, z1 + t, wall_mat, wall_col)
        else:
            self.abox(x0, x1, floor_y, h, z1, z1 + t, wall_mat, wall_col)
        if ceiling is not None:
            self.abox(x0 - t, x1 + t, h, h + 0.4, z0 - t, z1 + t, ILL, ceiling)

    def stairs(self, x, y, z, heading, n, width, mat, col, run=RUN):
        """Straight flight from (x,y,z) going along heading, n steps up."""
        F = fwd(heading)
        for i in range(n):
            c = np.array([x, 0, z]) + F * (run * (i + 0.5))
            top = y + STEP * (i + 1)
            self.ybox(c[0], top - 0.37, c[2], width, run + 0.02, 0.37, mat, col, yaw=heading)
        end = np.array([x, 0, z]) + F * run * n
        return end[0], y + STEP * n, end[2]

    def bulbs(self, pts, col=(1, 0.9, 0.6), d=0.22):
        for p in pts:
            self.ell(p[0], p[1], p[2], d, d, d, GLOW, col)



CREDIT = "BY KINGCOLOSSUS"

# what each game was in the show, and how to play it here (a host - the Front Man - runs it and /roll settles
# anything the world can't do on its own)
GUIDE = {
    "dorm": ("THE DORMITORY", "THE HUB  -  LIGHTS OUT  -  THE VOTE",
             "PLAYERS SLEEP IN STACKED BUNKS UNDER THE PIGGY BANK, WHICH GAINS 100 MILLION WON PER ELIMINATION. "
             "AFTER EACH GAME THEY VOTE O TO GO ON OR X TO STOP.",
             "THE NORTH DOOR LEADS TO THE STAIRS: ONE DOOR PER GAME. VOTE BY STANDING IN THE O OR X CIRCLE. THE "
             "HOST (FRONT MAN) RUNS EVERY GAME; /ROLL SETTLES THE REST."),
    "rlgl": ("RED LIGHT, GREEN LIGHT", "SEASON 1 GAME 1  -  SEASON 2 GAME 1",
             "CROSS THE FIELD IN 5 MINUTES. THE DOLL SINGS WITH HER BACK TURNED, THEN SPINS ROUND - ANYONE SHE "
             "CATCHES MOVING IS OUT.",
             "THE HOST CALLS GREEN / RED IN CHAT. MOVE ONLY ON GREEN. CAUGHT ON RED: USE A RED PAD BY THE WALLS. "
             "CROSS THE RED LINE IN TIME AND STEP ON SURVIVED."),
    "dalgona": ("DALGONA", "SEASON 1 GAME 2",
                "PICK A SHAPE - CIRCLE, TRIANGLE, STAR, UMBRELLA - THEN CARVE IT OUT OF A HONEYCOMB CANDY WITH A "
                "NEEDLE IN 10 MINUTES WITHOUT BREAKING IT.",
                "STAND AT THE STALL OF THE SHAPE YOU WANT. THE HOST DOES /ROLL 4: 1 CIRCLE, 2 TRIANGLE, 3 STAR, "
                "4 UMBRELLA. THAT SHAPE'S CANDY CRACKS - EVERYONE AT THAT STALL TAKES THE ELIMINATED PAD."),
    "tug": ("TUG OF WAR", "SEASON 1 GAME 3",
            "TWO TEAMS OF 10 PULL ONE ROPE BETWEEN TWO HIGH PLATFORMS. THE AXE CUTS THE ROPE AND THE LOSING TEAM "
            "FALLS.",
            "TAKE THE YELLOW STAIRS TO YOUR PLATFORM. ON THE SIGNAL EVERYONE /ROLLS 100 - HIGHER TEAM TOTAL WINS. "
            "LOSERS STEP OFF THE END - THE PADS BELOW CATCH THEM."),
    "marbles": ("MARBLES", "SEASON 1 GAME 4",
                "PARTNERS (GGANBU) GET 10 MARBLES EACH AND MUST WIN ALL OF THE OTHER'S IN 30 MINUTES, BY ANY GAME "
                "THEY LIKE.",
                "PAIR UP IN AN ALLEY. PLAY ODD-OR-EVEN WITH /ROLL OR ANY GAME YOU AGREE ON. RUN OUT OF MARBLES AND "
                "TAKE THE ELIMINATED PAD BY THE GATE."),
    "glass": ("GLASS STEPPING STONES", "SEASON 1 GAME 5",
              "18 STEPS, EACH A PAIR OF GLASS PANELS: ONE TEMPERED, ONE THAT SHATTERS. 16 PLAYERS, 16 MINUTES.",
              "STAND ON YOUR NUMBER AND CROSS IN ORDER, STEPPING ONTO THE LEFT OR RIGHT PANEL OF EACH ROW. THE "
              "WRONG PANEL TELEPORTS YOU TO THE COFFIN ROOM. STEP ON SURVIVED AT THE FAR END."),
    "squid": ("SQUID GAME", "SEASON 1 FINAL",
              "ATTACKERS HOP ON ONE FOOT UNTIL THEY CROSS THE SQUID'S WAIST, THEN RACE FOR ITS HEAD. DEFENDERS PUSH "
              "THEM OUT OF THE LINES.",
              "IT'S TAG: ATTACKERS START IN THE CIRCLE, GO IN BY THE BOTTOM GATE AND WALK (NO RUNNING) UNTIL PAST "
              "THE WAIST, THEN RUN FOR 2 AND STEP ON WINNER. A DEFENDER TOUCHES YOU: YOU'RE OUT."),
    "pentathlon": ("SIX-LEGGED PENTATHLON", "SEASON 2 GAME 2",
                   "TEAMS OF 5, LEGS TIED, RUN A RAINBOW TRACK. AT 5 STATIONS ONE PLAYER EACH CLEARS A CHILDHOOD "
                   "GAME. 5 MINUTES FOR THE WHOLE TEAM.",
                   "STAY TOGETHER. AT EACH STATION ITS PLAYER /ROLLS 100 TO BEAT THE HOST'S TARGET. MISS THE 5:00 "
                   "CLOCK AND THE TEAM TAKES THE ELIMINATED PAD."),
    "mingle": ("MINGLE", "SEASON 2 GAME 3",
               "WHEN THE CAROUSEL STOPS A NUMBER IS CALLED: GET INTO A ROOM IN A GROUP OF EXACTLY THAT MANY WITHIN "
               "30 SECONDS.",
               "DANCE ON THE ORANGE PLATFORM. THE HOST CALLS A NUMBER AND COUNTS 30. WRONG GROUP SIZE OR LEFT "
               "OUTSIDE: TAKE THE ELIMINATED PAD."),
    "hide": ("HIDE-AND-SEEK", "SEASON 3 GAME 4",
             "BLUE HIDERS HIDE IN A MAZE OF ALLEYS. RED SEEKERS EACH HAVE TO FIND AND CATCH ONE BEFORE THE "
             "30 MINUTES ARE UP.",
             "/ROLL 2: 1 HIDES, 2 SEEKS. HIDERS GET A 2 MINUTE HEAD START - THE CRATES IN THE DEAD ENDS ARE GOOD "
             "SPOTS. A SEEKER TOUCHES YOU: YOU'RE OUT. STILL HIDDEN AT 30:00? STEP ON SURVIVED."),
    "jumprope": ("JUMP ROPE", "SEASON 3 GAME 5",
                 "CROSS A NARROW BRIDGE OVER A PIT WHILE TWO GIANT DOLLS SWING A ROPE, AND JUMP EVERY TIME IT COMES "
                 "ROUND. 20 MINUTES.",
                 "NO JUMPING HERE: WHEN THE HOST CALLS ROPE AND COUNTS 3, BE STANDING ON A PINK STRIPE. ANYONE "
                 "BETWEEN STRIPES IS HIT AND STEPS OFF. WATCH THE NARROW MIDDLE. REACH THE FAR PLATFORM IN TIME."),
    "sky": ("SKY SQUID GAME", "SEASON 3 FINAL",
            "A TOWER OF THREE PLATFORMS - SQUARE, TRIANGLE, CIRCLE. EACH 15-MINUTE ROUND, SOMEONE MUST BE PUSHED "
            "OFF BEFORE THE REST MOVE UP.",
            "TAKE THE ELEVATOR PAD. THE RED BUTTON STARTS THE CLOCK. PUSH, OR LOWEST /ROLL STEPS OFF. THEN CLIMB TO "
            "THE NEXT PLATFORM. LAST ONE STANDING WINS."),
}


def wrap_text(t, n):
    out, line = [], ""
    for word in t.split():
        if line and len(line) + 1 + len(word) > n:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        out.append(line)
    return out


def guide_board(sg, key, x, y, z, heading, floor_y=0.0, width=10.4):
    """A big rules board on two posts: title, season, 'in the show' and 'how to play here', and the credit.
    (x, y, z) is the middle of its bottom edge; it is read by someone looking along `heading`."""
    title, sub, show, here = GUIDE[key]
    PX = 0.032
    n = int((width - 0.6) / (6 * PX))
    rows = [(title, 0.085, (1, 0.35, 0.6), 0.25), (sub, 0.035, (1, 0.85, 0.45), 0.35),
            ("IN THE SHOW", 0.04, (0.55, 0.85, 1.0), 0.12)]
    rows += [(l, PX, WHITE, 0.0) for l in wrap_text(show, n)]
    rows[-1] = (rows[-1][0], PX, WHITE, 0.3)
    rows += [("HOW TO PLAY HERE", 0.04, (0.55, 1.0, 0.65), 0.12)]
    rows += [(l, PX, WHITE, 0.0) for l in wrap_text(here, n)]
    rows[-1] = (rows[-1][0], PX, WHITE, 0.35)
    rows += [("SQUID GAME 3DX  -  " + CREDIT, 0.03, (1, 0.35, 0.6), 0.0)]
    H = sum(px * 9 + gap for _, px, _, gap in rows) + 0.5
    R, F = right_of(heading), fwd(heading)
    c = sg.P(x, y, z)
    X, Y, Z = plane_basis(R, UP, F)
    sg.w.box(c + UP * (H / 2) + F * 0.03, X, Y, Z, width + 0.24, H + 0.24, 0.05, ILL, (0.93, 0.25, 0.5))   # pink frame
    sg.w.box(c + UP * (H / 2) + F * 0.004, X, Y, Z, width, H, 0.05, ILL, (0.07, 0.07, 0.09))
    for sx in (-1, 1):
        post = c + R * sx * (width / 2 - 0.3) + F * 0.12
        sg.w.vcyl(post[0], sg.o[1] + floor_y, post[2], 0.14, y - floor_y + 0.2, "metal_4", (0.25, 0.25, 0.28))
    ytop = H - 0.3
    left = c - R * (width / 2 - 0.3)
    for t, px, col, gap in rows:
        h = px * 9
        cy = ytop - h / 2
        if px >= 0.035:
            write(sg.w, t, c + UP * cy, R, UP, -F, px, col, ILL, thick=0.012)
        else:
            write(sg.w, t, left + UP * cy, R, UP, -F, px, col, ILL, thick=0.012, align="left")
        ytop -= h + gap


# ------------------------------------------------------------------ figures
SKIN = (1.0, 0.86, 0.74)


def young_hee(sg, x, z, heading, H=6.5, y=0.0, outfit="s1", rope_hand=None):
    """The doll. outfit s1: yellow shirt, orange pinafore. s3 (jump rope): white blouse, red pinafore."""
    u = H / 12.0
    F, R = fwd(heading), right_of(heading)
    b = sg.P(x, y, z)

    def put(v, fx=0.0, ux=0.0, rx=0.0):
        return b + F * fx + UP * ux + R * rx

    shirt = (1, 0.85, 0.15) if outfit == "s1" else (0.97, 0.95, 0.93)
    dress = (0.97, 0.45, 0.1) if outfit == "s1" else (0.85, 0.12, 0.18)
    w = sg.w
    for s in (-1, 1):
        w.ell(put(0, fx=0.3 * u, ux=0.3 * u, rx=s * 0.9 * u), 1.0 * u, 0.6 * u, 1.5 * u, ILL, (0.1, 0.08, 0.08), yaw=heading)
        w.vcyl(*put(0, ux=0.5 * u, rx=s * 0.9 * u), 0.9 * u, 1.6 * u, ILL, WHITE)                    # socks
        w.vcyl(*put(0, ux=2.0 * u, rx=s * 0.9 * u), 0.82 * u, 2.4 * u, ILL, SKIN)                    # legs
    w.shape("Cone", put(0, ux=3.6 * u), 5.0 * u, 4.2 * u, 6.0 * u, ILL, dress, yaw=heading)          # pinafore
    w.ell(put(0, ux=7.2 * u), 2.7 * u, 2.6 * u, 2.1 * u, ILL, shirt, yaw=heading)                     # torso
    w.ell(put(0, fx=0.55 * u, ux=6.7 * u), 2.2 * u, 1.9 * u, 1.2 * u, ILL, dress, yaw=heading)       # bib
    for s in (-1, 1):
        w.ell(put(0, ux=7.7 * u, rx=s * 1.55 * u), 1.4 * u, 1.3 * u, 1.4 * u, ILL, shirt, yaw=heading)  # puff sleeves
        if rope_hand is not None:
            hand = put(0, fx=1.6 * u, ux=6.0 * u, rx=s * 0.5 * u)
        else:
            hand = put(0, fx=0.2 * u, ux=4.9 * u, rx=s * 1.9 * u)
        w.cyl(put(0, ux=7.4 * u, rx=s * 1.75 * u), hand, 0.6 * u, ILL, SKIN)
        w.ell(hand, 0.75 * u, 0.75 * u, 0.75 * u, ILL, SKIN)
    if outfit != "s1":                                                                                # white collar
        w.ell(put(0, fx=0.5 * u, ux=8.15 * u), 1.9 * u, 0.4 * u, 1.0 * u, ILL, WHITE, yaw=heading)
    head = put(0, ux=9.9 * u)
    w.ell(head, 3.6 * u, 3.6 * u, 3.4 * u, ILL, SKIN, yaw=heading)
    w.ell(head + UP * 0.45 * u - F * 0.35 * u, 3.85 * u, 3.0 * u, 3.6 * u, ILL, (0.12, 0.08, 0.06), yaw=heading)  # hair
    w.ell(head + UP * 1.0 * u + F * 1.0 * u, 3.0 * u, 1.0 * u, 1.4 * u, ILL, (0.12, 0.08, 0.06), yaw=heading)   # fringe
    for s in (-1, 1):
        w.ell(head + R * s * 1.75 * u - UP * 0.6 * u - F * 0.2 * u, 0.8 * u, 1.3 * u, 0.9 * u, ILL, (0.12, 0.08, 0.06))
        w.ell(head + R * s * 1.95 * u - UP * 0.2 * u - F * 0.4 * u, 0.4 * u, 0.4 * u, 0.4 * u, ILL, (0.95, 0.4, 0.6))  # bobbles
        w.ell(head + F * 1.62 * u + R * s * 0.62 * u + UP * 0.1 * u, 0.42 * u, 0.6 * u, 0.25 * u, ILL, BLACK, yaw=heading)
        w.ell(head + F * 1.5 * u + R * s * 1.05 * u - UP * 0.5 * u, 0.5 * u, 0.3 * u, 0.15 * u, ILL, (1, 0.6, 0.6), yaw=heading)
    w.ell(head + F * 1.66 * u - UP * 0.75 * u, 0.5 * u, 0.25 * u, 0.15 * u, ILL, (0.85, 0.3, 0.35), yaw=heading)
    if rope_hand is not None:
        return put(0, fx=1.6 * u, ux=6.0 * u)
    return None


def cheol_su(sg, x, z, heading, H=6.5, y=0.0, rope_hand=False):
    u = H / 12.0
    F, R = fwd(heading), right_of(heading)
    b = sg.P(x, y, z)
    w = sg.w

    def put(fx=0.0, ux=0.0, rx=0.0):
        return b + F * fx + UP * ux + R * rx

    green = (0.15, 0.55, 0.3)
    for s in (-1, 1):
        w.ell(put(0.3 * u, 0.3 * u, s * 0.9 * u), 1.0 * u, 0.6 * u, 1.5 * u, ILL, (0.95, 0.95, 0.95), yaw=heading)
        w.vcyl(*put(0, 0.5 * u, s * 0.9 * u), 0.9 * u, 1.4 * u, ILL, WHITE)
        w.vcyl(*put(0, 1.8 * u, s * 0.9 * u), 0.85 * u, 2.0 * u, ILL, SKIN)
    w.vcyl(*put(0, 3.6 * u), 3.0 * u, 1.6 * u, ILL, (0.12, 0.15, 0.3))                               # shorts
    for i in range(8):                                                                                # striped shirt
        w.vcyl(*put(0, 5.0 * u + i * 0.42 * u), (2.8 - 0.05 * i) * u, 0.43 * u, ILL, green if i % 2 else WHITE)
    for s in (-1, 1):
        sh = put(0, 8.0 * u, s * 1.5 * u)
        hand = put(1.6 * u, 6.0 * u, s * 0.5 * u) if rope_hand else put(0.2 * u, 4.9 * u, s * 1.9 * u)
        w.cyl(sh, hand, 0.75 * u, ILL, green)
        w.ell(hand, 0.75 * u, 0.75 * u, 0.75 * u, ILL, SKIN)
    head = put(0, 9.9 * u)
    w.ell(head, 3.6 * u, 3.6 * u, 3.4 * u, ILL, SKIN, yaw=heading)
    w.ell(head + UP * 0.9 * u - F * 0.2 * u, 3.75 * u, 2.2 * u, 3.6 * u, ILL, green, yaw=heading)      # cap
    w.ell(head + UP * 0.75 * u + F * 1.9 * u, 2.4 * u, 0.3 * u, 1.6 * u, ILL, green, yaw=heading)      # brim
    for s in (-1, 1):
        w.ell(head + R * s * 1.7 * u - UP * 0.3 * u, 0.6 * u, 1.2 * u, 0.9 * u, ILL, (0.12, 0.08, 0.06))
        w.ell(head + F * 1.62 * u + R * s * 0.62 * u + UP * 0.05 * u, 0.42 * u, 0.6 * u, 0.25 * u, ILL, BLACK, yaw=heading)
    w.ell(head + F * 1.66 * u - UP * 0.75 * u, 0.6 * u, 0.22 * u, 0.15 * u, ILL, (0.8, 0.3, 0.3), yaw=heading)
    return put(1.6 * u, 6.0 * u) if rope_hand else None


MASKS = {
    "circle": [".11111.", "1.....1", "1.....1", "1.....1", "1.....1", "1.....1", ".11111."],
    "triangle": ["...1...", "..1.1..", "..1.1..", ".1...1.", ".1...1.", "1.....1", "1111111"],
    "square": ["1111111", "1.....1", "1.....1", "1.....1", "1.....1", "1.....1", "1111111"],
}


def guard(sg, x, z, heading, symbol="circle", y=0.0):
    """A pink-suited guard standing at attention (a statue)."""
    F, R = fwd(heading), right_of(heading)
    b = sg.P(x, y, z)
    w = sg.w
    for s in (-1, 1):
        w.ell(b + R * s * 0.13 + F * 0.05 + UP * 0.06, 0.16, 0.12, 0.3, ILL, BLACK, yaw=heading)
        w.vcyl(*(b + R * s * 0.13), 0.2, 0.95, "Fabric1", GUARD_PINK)
    w.vcyl(*(b + UP * 0.9), 0.48, 0.65, "Fabric1", GUARD_PINK)
    w.vcyl(*(b + UP * 0.92), 0.5, 0.07, ILL, BLACK)                                              # belt
    for s in (-1, 1):
        w.cyl(b + UP * 1.5 + R * s * 0.3, b + UP * 0.95 + R * s * 0.32 + F * 0.05, 0.13, "Fabric1", GUARD_PINK)
    w.ell(b + UP * 1.72, 0.42, 0.45, 0.42, "Fabric1", GUARD_PINK)                                  # hood
    face = b + UP * 1.72 + F * 0.17
    w.ell(face, 0.3, 0.36, 0.12, ILL, BLACK, yaw=heading)                                          # mask
    sym = face + F * 0.065
    bm = MASKS[symbol]
    X, Y, Z = plane_basis(R, UP, -F)
    for (cx, cy, rw, rh) in rects(bm):
        o = sym + R * ((cx + rw / 2 - 3.5) * 0.026) + UP * ((3.5 - (cy + rh / 2)) * 0.026)
        w.box(o, X, Y, Z, rw * 0.026, rh * 0.026, 0.01, ILL, WHITE)


# ------------------------------------------------------------------ bitmaps for dalgona shapes
def raster(segments, n=23, t=0.075):
    """Bitmap from line segments in unit coords (0..1, y down)."""
    rows = []
    for j in range(n):
        row = ""
        for i in range(n):
            px, py = (i + 0.5) / n, (j + 0.5) / n
            on = False
            for (ax, ay), (bx, by) in segments:
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                t_ = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
                if math.hypot(px - (ax + dx * t_), py - (ay + dy * t_)) < t:
                    on = True
                    break
            row += "1" if on else "."
        rows.append(row)
    return rows


def arc(cx, cy, r, a0, a1, n=24):
    pts = [(cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a))) for a in np.linspace(a0, a1, n + 1)]
    return list(zip(pts, pts[1:]))


def closed(pts):
    return list(zip(pts, pts[1:] + pts[:1]))


SHAPES = {
    "circle": raster(arc(0.5, 0.5, 0.38, 0, 360)),
    "triangle": raster(closed([(0.5, 0.1), (0.9, 0.85), (0.1, 0.85)])),
    "star": raster(closed([(0.5 + (0.42 if k % 2 == 0 else 0.18) * math.sin(math.radians(36 * k)),
                            0.53 - (0.42 if k % 2 == 0 else 0.18) * math.cos(math.radians(36 * k))) for k in range(10)])),
    "umbrella": raster(arc(0.5, 0.5, 0.4, 0, 180) + [((0.1, 0.5), (0.9, 0.5)), ((0.5, 0.5), (0.5, 0.82))]
                       + arc(0.42, 0.82, 0.08, 180, 360, 8)),
}


def _fig(x, y, s=0.12, arms="down"):
    """Stick figure in unit coords: head, body, legs, arms."""
    segs = arc(x, y - 0.8 * s, 0.22 * s, 0, 360, 8)
    segs += [((x, y - 0.58 * s), (x, y))]
    segs += [((x, y), (x - 0.3 * s, y + 0.55 * s)), ((x, y), (x + 0.3 * s, y + 0.55 * s))]
    if arms == "pull":
        segs += [((x, y - 0.4 * s), (x + 0.45 * s, y - 0.35 * s))]
    elif arms == "up":
        segs += [((x, y - 0.4 * s), (x - 0.35 * s, y - 0.8 * s)), ((x, y - 0.4 * s), (x + 0.35 * s, y - 0.8 * s))]
    else:
        segs += [((x, y - 0.4 * s), (x - 0.3 * s, y - 0.1 * s)), ((x, y - 0.4 * s), (x + 0.3 * s, y - 0.1 * s))]
    return segs


def _wide(segs, w=46, h=23, t=0.035):
    rows = []
    for j in range(h):
        row = ""
        for i in range(w):
            px, py = (i + 0.5) / w * 2.0, (j + 0.5) / h
            on = False
            for (ax, ay), (bx, by) in segs:
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                t_ = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
                if math.hypot(px - (ax + dx * t_), py - (ay + dy * t_)) < t:
                    on = True
                    break
            row += "1" if on else "."
        rows.append(row)
    return rows


PICTO = {
    "tug": _wide([((0.15, 0.62), (1.85, 0.62))] + sum((_fig(0.3 + i * 0.2, 0.75, 0.3, "pull") for i in range(3)), [])
                 + sum((_fig(1.3 + i * 0.2, 0.75, 0.3, "pull") for i in range(3)), [])
                 + [((0.1, 0.95), (0.85, 0.95)), ((1.15, 0.95), (1.9, 0.95))]),
    "bridge": _wide(sum(([((x, 0.85), (x + 0.12, 0.85))] for x in np.arange(0.15, 1.85, 0.2)), [])
                    + _fig(0.75, 0.68, 0.3) + _fig(1.15, 0.68, 0.3, "up")),
    "squid": _wide(arc(1.0, 0.18, 0.12, 0, 360, 16) + [((0.75, 0.55), (1.25, 0.55)), ((0.75, 0.55), (1.0, 0.32)),
                                                         ((1.25, 0.55), (1.0, 0.32)), ((0.75, 0.55), (0.75, 0.92)),
                                                         ((1.25, 0.55), (1.25, 0.92)), ((0.75, 0.92), (1.25, 0.92))]
                   + _fig(0.4, 0.75, 0.3, "up") + _fig(1.6, 0.75, 0.3)),
    "rlgl": _wide(_fig(1.7, 0.7, 0.5) + _fig(0.3, 0.75, 0.3) + _fig(0.6, 0.78, 0.3, "up") + _fig(0.95, 0.75, 0.3)
                  + [((1.45, 0.98), (1.45, 0.2))]),
    "marbles": _wide(_fig(0.6, 0.72, 0.35) + _fig(1.4, 0.72, 0.35)
                     + sum((arc(0.85 + i * 0.1, 0.93, 0.025, 0, 360, 6) for i in range(4)), [])),
    "dalgona": _wide(arc(0.5, 0.5, 0.3, 0, 360, 20) + arc(0.5, 0.5, 0.12, 0, 360, 12)
                     + [((1.2, 0.8), (1.5, 0.2)), ((1.5, 0.2), (1.8, 0.8)), ((1.8, 0.8), (1.2, 0.8))]),
}


# ================================================================== arenas
def subway(sg):
    """Arrival: the recruiter's subway platform with the ddakji tiles and the business card."""
    sg.at("subway")
    s = sg
    s.abox(-22, 22, -0.6, 1.0, -4, 6, "tiles_2", (0.85, 0.85, 0.85))                 # platform
    s.abox(-22, 22, -0.6, 0.0, -10, -4, "concrete_4", (0.5, 0.5, 0.5))               # track bed
    for x in (-1.6, 1.6):
        for rz in (-8.2, -5.8):
            s.abox(-22, 22, 0.0, 0.15, rz - 0.04, rz + 0.04, "metal_4", (0.6, 0.6, 0.6))
    s.abox(-22, 22, 1.0, 1.012, -3.85, -3.45, ILL, (1, 0.85, 0.1))                    # yellow line
    s.abox(-22, 22, 1.0, 6.0, 6, 6.5, "tiles_1", (0.95, 0.95, 0.95))                  # back wall
    s.abox(-22, 22, 2.6, 2.9, 5.95, 6.0, ILL, (0.2, 0.5, 0.9))                         # line colour band
    s.abox(-22, 22, 6.0, 6.3, -10, 6.5, ILL, (0.85, 0.87, 0.88))                       # ceiling
    s.abox(-22, 22, 0.0, 6.0, -10.5, -10, "tiles_1", (0.9, 0.9, 0.9))
    for x in range(-18, 19, 9):
        s.abox(x - 0.3, x + 0.3, 1.0, 6.0, -0.3, 0.3, ILL, (0.8, 0.82, 0.85))
        s.abox(x - 0.31, x + 0.31, 3.5, 3.8, -0.31, 0.31, ILL, (0.2, 0.5, 0.9))
    for x in range(-20, 21, 5):
        s.abox(x - 1.2, x + 1.2, 5.85, 6.0, 1.2, 1.5, GLOW, (1, 1, 0.95))               # light strips
    s.sign("SQUID GAME LINE", 0, 4.6, 5.95, 0, 0.09, WHITE, (0.2, 0.5, 0.9))
    # bench, briefcase, ddakji
    s.abox(4, 6.5, 1.0, 1.45, 4.6, 5.4, "WoodTeakX", (0.8, 0.6, 0.4))
    s.abox(4.3, 4.4, 1.0, 1.45, 4.65, 5.35, "metal_4")
    s.abox(6.1, 6.2, 1.0, 1.45, 4.65, 5.35, "metal_4")
    s.ybox(7.2, 1.0, 4.8, 0.55, 0.15, 0.4, "Leather_Italian", (0.35, 0.2, 0.1), yaw=10)
    for (dx, dz, col, yaw) in ((1.0, 2.0, (0.2, 0.45, 0.95), 15), (2.0, 1.4, (0.9, 0.15, 0.15), -20)):
        s.ybox(dx, 1.0, dz, 0.45, 0.45, 0.05, "paint_1", col, yaw=yaw)
        s.ybox(dx, 1.05, dz, 0.62, 0.05, 0.01, "paint_1", tuple(c * 0.7 for c in col), yaw=yaw + 45)
    # the business card on the wall
    s.abox(-8, -2, 2.0, 4.9, 5.85, 5.95, ILL, (0.85, 0.75, 0.55))
    for k, name in enumerate(("circle", "triangle", "square")):
        s.bitmap(MASKS[name], -6.6 + k * 1.6, 3.45, 5.84, 0, 0.13, BLACK)
    s.sign("WOULD YOU LIKE TO PLAY A GAME?", -5, 1.55, 5.9, 0, 0.035, BLACK, None)
    # welcome board: the map of the world
    lines = ("SQUID GAME - ALL 3 SEASONS\n" + CREDIT + "\n\n"
             "THE PORTAL AT THE END OF THE PLATFORM TAKES\nYOU TO THE DORMITORY. THE STAIRS BEHIND IT\n"
             "HAVE A DOOR FOR EVERY GAME:\n\n"
             "S1  RED LIGHT GREEN LIGHT    DALGONA\n    TUG OF WAR    MARBLES    GLASS BRIDGE\n    SQUID GAME\n"
             "S2  SIX-LEGGED PENTATHLON    MINGLE\n    (RED LIGHT RETURNS - LIGHTS OUT IN THE DORM)\n"
             "S3  HIDE AND SEEK    JUMP ROPE    SKY SQUID GAME\n\n"
             "EVERY GAME HAS A RULES BOARD WHERE YOU ARRIVE.\n"
             "ELIMINATED? PORTALS TAKE YOU TO THE COFFIN ROOM.\nA HOST (FRONT MAN) RUNS THE RULES. USE /ROLL.")
    s.sign(lines, 12, 3.6, 5.85, 0, 0.032, WHITE, (0.1, 0.12, 0.15))
    s.spot("subway", 0, 1.0, 1.5, 0)
    s.portal(20, 1.0, 1.0, 90, "dorm", "STEP IN TO PLAY")
    s.sign("THE GAME", 20, 3.0, 5.9, 0, 0.08, (1, 0.3, 0.5), (0.05, 0.05, 0.06))
    s.sign("SQUID GAME", 0, 5.35, 5.94, 0, 0.07, (1, 0.35, 0.6), None)
    s.sign(CREDIT, 0, 4.95, 5.94, 0, 0.035, WHITE, None)


def dorm(sg):
    """The dormitory: stacked bunks, the piggy bank, the O/X vote. Its north opening leads into the stairs."""
    sg.at("dorm")
    s = sg
    X0, X1, Z0, Z1, H = -32, 32, -22, 22, 16
    s.hall(X0, X1, Z0, Z1, H, (0.6, 0.68, 0.72), "paint_1", (0.5, 0.52, 0.55), ceiling=(0.42, 0.45, 0.48),
           north_gap=(-3, 3, 8))
    # bunk walls on east and west: an outer stack of 7 and an inner one of 4, beds lengthwise
    for side in (-1, 1):
        for depth, levels in ((0, 7), (1, 4)):
            xin = side * (31.5 - depth * 1.2)
            xa, xb = xin - side * 1.1, xin
            for lv in range(levels):
                y = 0.3 + lv * 1.15
                s.abox(xa, xb, y, y + 0.08, -20, 20, ILL, (0.92, 0.93, 0.95))            # shelf
                for k in range(19):
                    z = -19 + k * 2.1 + 1.05
                    if (k + lv + depth) % 7 == 3:
                        continue                                                          # an empty bunk here and there
                    s.abox(xa + side * 0.05, xb - side * 0.05, y + 0.08, y + 0.28, z - 0.95, z + 0.95, "Fabric2", (0.97, 0.97, 0.97))
                    s.abox(xa + side * 0.08, xb - side * 0.08, y + 0.28, y + 0.36, z - 0.5, z + 0.85, "Fabric1", (0.55, 0.6, 0.68))
            for k in range(20):
                z = -20 + k * 2.1
                for xx in (xa, xb):
                    s.abox(xx - 0.04, xx + 0.04, 0, 0.3 + levels * 1.15, z - 0.04, z + 0.04, ILL, (0.9, 0.9, 0.92))
            if depth == 1:                                                                # ladders
                for k in range(0, 19, 3):
                    z = -19 + k * 2.1 + 1.05
                    for r in range(int(levels * 1.15 / 0.3)):
                        s.abox(xb - 0.02, xb + side * 0.15, 0.3 + r * 0.3, 0.34 + r * 0.3, z - 0.3, z + 0.3, ILL, (0.88, 0.88, 0.9))
    # the drawings of the games hidden on the walls behind the bunks (revealed as the beds empty)
    for k, (bm, zc) in enumerate(((PICTO["tug"], -14), (PICTO["bridge"], -2), (PICTO["squid"], 10),
                                  (PICTO["rlgl"], 14), (PICTO["marbles"], -10), (PICTO["dalgona"], 2))):
        side = -1 if k < 3 else 1
        x = side * 31.95
        s.bitmap(bm, x, 4.5, zc, 270 if side < 0 else 90, 0.22, (0.15, 0.15, 0.17))
    # the piggy bank over the room, gold balls inside
    py = 10.5
    s.cyl((0, H, 0), (0, py + 2.8, 0), 0.08, "metal_4")
    s.ell(0, py, 0, 5.2, 5.0, 7.2, "GlassClear", (0.85, 0.95, 1.0))
    s.cyl((0, py, 3.4), (0, py, 4.4), 1.9, "GlassClear", (0.85, 0.95, 1.0))
    for sx in (-1, 1):
        s.shape("Cone", sx * 1.6, py + 2.1, 2.2, 1.0, 0.6, 1.2, "GlassClear", (0.85, 0.95, 1.0))
        for sz in (-1, 1):
            s.cyl((sx * 1.6, py - 1.8, sz * 2.2), (sx * 1.6, py - 3.0, sz * 2.2), 0.9, "GlassClear", (0.85, 0.95, 1.0))
    rng = s.rng
    for _ in range(70):
        a, r = rng.random() * 6.283, rng.random() ** 0.5 * 1.9
        s.ell(math.sin(a) * r, py - 1.9 + rng.random() * 1.4, math.cos(a) * r * 1.35, 0.55, 0.55, 0.55, "gold", (1, 0.82, 0.3))
    s.abox(-0.9, 0.9, py + 2.35, py + 2.5, -0.15, 0.15, ILL, BLACK)                     # coin slot
    s.sign("45,600,000,000 WON", 0, 13.5, Z0 + 0.6, 180, 0.16, (1, 0.85, 0.3), (0.05, 0.05, 0.06))
    # O/X vote stage (season 2)
    s.abox(-8, 8, 0, 0.25, -21.5, -15, ILL, (0.25, 0.27, 0.3))                  # one step up
    for xb, label, col in ((-4, "O", (0.15, 0.45, 1.0)), (4, "X", (1.0, 0.15, 0.2))):
        s.vcyl(xb, 0.25, -18, 2.4, 0.03, GLOW, col)                                   # stand in it to vote
        s.vcyl(xb, 0.25, -18, 1.9, 0.035, ILL, (0.12, 0.12, 0.14))
        s.ftext(label, xb, -18, 180, 0.12, col, y=0.29)
        s.sign(label, xb, 9.0, Z0 + 0.6, 180, 0.6, col, None)
        s.sign("0", xb, 6.0, Z0 + 0.6, 180, 0.35, WHITE, None)
    s.sign("VOTE: STAND IN O TO CONTINUE, IN X TO STOP", 0, 3.2, Z0 + 0.6, 180, 0.07, WHITE, (0.05, 0.05, 0.06))
    s.sign("LIGHTS OUT: THE FRONT MAN SAYS WHEN", 0, 2.0, Z0 + 0.6, 180, 0.05, (1, 0.5, 0.5), None)
    s.sign("THE GAMES ->", 0, 9.5, Z1 - 0.25, 0, 0.12, WHITE, (0.05, 0.05, 0.06))
    s.sign("SQUID GAME  -  " + CREDIT, 0, 15.0, Z0 + 0.6, 180, 0.06, (1, 0.35, 0.6), None)
    for k, sym in enumerate(("circle", "triangle", "square")):
        guard(s, -6 + k * 6, 20.5, 180, sym)
    guide_board(s, "dorm", 0, 3.0, -4, 0)
    s.spot("dorm", 0, 0, -9, 0)
    s.spot("dorm_win", 3, 0, -9, 0)


def stair_maze(sg):
    """The pastel M.C.-Escher stairs north of the dormitory: a door on each landing, one per game."""
    sg.at("dorm")
    s = sg
    X0, X1, Z0, Z1, H = -9, 9, 22.5, 40.5, 50
    PINKW = (0.97, 0.66, 0.72)
    s.abox(X0 - 0.5, X1 + 0.5, -0.4, 0, Z0, Z1 + 0.5, ILL, (0.95, 0.85, 0.88))
    s.abox(X0 - 0.5, X0, 0, H, Z0, Z1 + 0.5, ILL, PINKW)
    s.abox(X1, X1 + 0.5, 0, H, Z0, Z1 + 0.5, ILL, PINKW)
    s.abox(X0, X1, 0, H, Z1, Z1 + 0.5, ILL, PINKW)
    s.abox(X0, -3, 0, H, Z0 - 0.5, Z0, ILL, PINKW)                                        # south wall with
    s.abox(3, X1, 0, H, Z0 - 0.5, Z0, ILL, PINKW)                                          # the opening from
    s.abox(-3, 3, 8, H, Z0 - 0.5, Z0, ILL, PINKW)                                          # the dormitory
    s.abox(X0 - 0.5, X1 + 0.5, H, H + 0.4, Z0 - 0.5, Z1 + 0.5, ILL, (0.98, 0.9, 0.92))
    # window frames painted on the walls (blue rectangles, like the set)
    rng = s.rng
    for k in range(40):
        wall = rng.choice("nsew")
        u, yy = rng.uniform(-7, 7), rng.uniform(3, H - 3)
        col = rng.choice([(0.45, 0.65, 0.85), (0.98, 0.82, 0.45), (0.95, 0.5, 0.6)])
        wd, ht = rng.uniform(0.9, 1.6), rng.uniform(1.4, 2.4)
        if wall == "n":
            pts = [(u - wd / 2, Z1 - 0.02), (u + wd / 2, Z1 - 0.02)]
            for (a, b) in ((0, 0), ):
                pass
            s.abox(u - wd / 2, u + wd / 2, yy, yy + ht, Z1 - 0.06, Z1, ILL, col)
            s.abox(u - wd / 2 + 0.18, u + wd / 2 - 0.18, yy + 0.18, yy + ht - 0.18, Z1 - 0.08, Z1 - 0.05, ILL, PINKW)
        elif wall in "ew":
            x = X1 if wall == "e" else X0
            sg_ = 1 if wall == "e" else -1
            zz = 31.5 + u
            s.abox(x - sg_ * 0.06, x, yy, yy + ht, zz - wd / 2, zz + wd / 2, ILL, col)
            s.abox(x - sg_ * 0.08, x - sg_ * 0.05, yy + 0.18, yy + ht - 0.18, zz - wd / 2 + 0.18, zz + wd / 2 - 0.18, ILL, PINKW)
    # the route: landings and flights round the walls, two laps
    BAND = 3.0
    cols = [(1.0, 0.84, 0.4), (0.5, 0.72, 0.95), (0.98, 0.62, 0.7), (0.62, 0.86, 0.66)]
    corner = {"SE": (7.5, 24.0), "NE": (7.5, 39.0), "NW": (-7.5, 39.0), "SW": (-7.5, 24.0)}
    mid = {"S": (0.0, 24.0, 4.32, 3.0), "E": (7.5, 31.5, 3.0, 4.32), "N": (0.0, 39.0, 4.32, 3.0), "W": (-7.5, 31.5, 3.0, 4.32)}
    order = [("mid", "S"), ("corner", "SE"), ("mid", "E"), ("corner", "NE"), ("mid", "N"), ("corner", "NW"),
             ("mid", "W"), ("corner", "SW")]
    # heading of the flight leaving each stop (towards the next stop)
    leave = {"S": 90, "SE": 0, "E": 0, "NE": 270, "N": 270, "NW": 180, "W": 180, "SW": 90}
    stops = []
    y = 0.0
    k = 0
    while y <= 42.0 + 1e-6:
        kind, name = order[k % 8]
        stops.append((kind, name, y))
        k += 1
        y += 3.0
    doors = [
        ("RED LIGHT\nGREEN LIGHT", "SEASON 1  GAME 1", "rlgl", 1),
        ("DALGONA", "SEASON 1  GAME 2", "dalgona", 1),
        ("TUG OF WAR", "SEASON 1  GAME 3", "tug", 1),
        ("MARBLES", "SEASON 1  GAME 4", "marbles", 1),
        ("GLASS BRIDGE", "SEASON 1  GAME 5", "glass", 1),
        ("SQUID GAME", "SEASON 1  FINAL", "squid", 1),
        ("RED LIGHT\nGREEN LIGHT", "SEASON 2  GAME 1", "rlgl", 2),
        ("SIX-LEGGED\nPENTATHLON", "SEASON 2  GAME 2", "pentathlon", 2),
        ("MINGLE", "SEASON 2  GAME 3", "mingle", 2),
        ("HIDE AND SEEK", "SEASON 3  GAME 4", "hide", 3),
        ("JUMP ROPE", "SEASON 3  GAME 5", "jumprope", 3),
        ("SKY SQUID GAME", "SEASON 3  FINAL", "sky", 3),
        ("VIP LOUNGE", "WATCH THE BRIDGE", "vip", 0),
        ("LEAVE THE GAME", "BACK TO THE SUBWAY", "subway", 0),
    ]
    land = {1: (0.98, 0.8, 0.86), 2: (0.74, 0.84, 1.0), 3: (1.0, 0.9, 0.62), 0: (0.86, 0.83, 0.92)}
    di = 0
    prev_season = None
    for idx, (kind, name, y) in enumerate(stops):
        col = cols[idx % 4]
        season = doors[idx - 1][3] if 1 <= idx <= len(doors) else 0
        lc = land[season] if idx else (0.86, 0.83, 0.92)
        if kind == "corner":
            cx, cz = corner[name]
            s.abox(cx - 1.5, cx + 1.5, y - 0.4, y, cz - 1.5, cz + 1.5, ILL, lc)
        else:
            cx, cz, wx, wz = mid[name]
            s.abox(cx - wx / 2, cx + wx / 2, y - 0.4, y, cz - wz / 2, cz + wz / 2, ILL, lc)
        # inner railing (the open middle of the hall)
        inner = {"S": ((-2.16, 2.16), 25.5, "z"), "N": ((-2.16, 2.16), 37.5, "z"), "E": ((29.34, 33.66), 6.0, "x"),
                 "W": ((29.34, 33.66), -6.0, "x"), "SE": None, "NE": None, "NW": None, "SW": None}[name]
        if inner:
            (a, b), c, ax = inner
            if ax == "z":
                s.abox(a, b, y, y + 1.0, c - 0.1, c + 0.1, ILL, col)
            else:
                s.abox(c - 0.1, c + 0.1, y, y + 1.0, a, b, ILL, col)
        # door on the outer wall (not at the dormitory entrance)
        if not (kind == "mid" and name == "S" and y == 0.0) and di < len(doors):
            title, sub, dest, season = doors[di]
            di += 1
            if kind == "mid":
                nrm = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}[name]
                wx_, wz_ = cx + nrm[0] * 1.5, cz + nrm[1] * 1.5
                pxp, pzp = cx + nrm[0] * 0.75, cz + nrm[1] * 0.75
            else:
                nrm = {"SE": (1, 0), "NE": (0, 1), "NW": (-1, 0), "SW": (0, -1)}[name]
                side = {"SE": (0, -1), "NE": (1, 0), "NW": (0, 1), "SW": (-1, 0)}[name]
                wx_, wz_ = cx + nrm[0] * 1.5 + side[0] * 0.75, cz + nrm[1] * 1.5 + side[1] * 0.75
                pxp, pzp = cx + nrm[0] * 0.8 + side[0] * 0.8, cz + nrm[1] * 0.8 + side[1] * 0.8
            view = math.degrees(math.atan2(nrm[0], nrm[1])) % 360      # looking at the wall
            R = right_of(view)
            # door: green steel, white frame, game name above
            s.ybox(wx_ - nrm[0] * 0.05, y, wz_ - nrm[1] * 0.05, 2.1, 0.1, 3.0, ILL, SEASON_COL[season], yaw=view)
            if season and season != prev_season:                          # where each season starts
                s.sign(f"SEASON {season}", wx_ - nrm[0] * 0.12, y + 5.2, wz_ - nrm[1] * 0.12, view, 0.11,
                       (0.08, 0.06, 0.1), SEASON_COL[season])
            prev_season = season
            s.ybox(wx_ - nrm[0] * 0.1, y, wz_ - nrm[1] * 0.1, 1.6, 0.08, 2.75, "MetalPaintGreen", (0.3, 0.6, 0.45), yaw=view)
            hp = np.array([wx_, 0, wz_]) - np.array([nrm[0], 0, nrm[1]]) * 0.16 + R * 0.55
            s.ybox(hp[0], y + 1.2, hp[2], 0.08, 0.08, 0.25, "metal_4", yaw=view)
            s.sign(title, wx_ - nrm[0] * 0.12, y + 3.7 + (0.18 if "\n" in title else 0), wz_ - nrm[1] * 0.12, view, 0.055,
                   WHITE, (0.1, 0.1, 0.12))
            s.sign(sub, wx_ - nrm[0] * 0.12, y + 3.05, wz_ - nrm[1] * 0.12, view, 0.03, (1, 0.85, 0.4), None)
            s.portal(pxp, y, pzp, view, dest)
        # flight to the next stop
        if idx + 1 < len(stops):
            h = leave[name]
            F = fwd(h)
            if kind == "mid":
                cx, cz, wx, wz = mid[name]
                start = np.array([cx, 0, cz]) + F * (wx / 2 if h in (90, 270) else wz / 2)
            else:
                cx, cz = corner[name]
                start = np.array([cx, 0, cz]) + F * 1.5
            s.stairs(start[0], y, start[2], h, 12, BAND, ILL, cols[(idx + 1) % 4])
            # railing on the inner side, following the slope
            Rr = right_of(h)
            inward = -Rr if np.dot(-Rr, np.array([-start[0], 0, 31.5 - start[2]])) > 0 else Rr
            a = start + inward * (BAND / 2 - 0.1)
            b = a + F * RUN * 12
            A3, B3 = s.P(a[0], y + 1.0, a[2]), s.P(b[0], y + 4.0, b[2])
            s.w.beam(A3, B3, 0.2, 1.3, ILL, cols[(idx + 1) % 4])


def rlgl(sg):
    """Red Light, Green Light: a sand field inside walls painted as sky, the doll under her tree."""
    sg.at("rlgl")
    s = sg
    X0, X1, Z0, Z1, H = -25, 25, -40, 40, 18
    SKY = (0.6, 0.8, 0.96)
    s.hall(X0, X1, Z0, Z1, H, SKY, "sand_1", (0.92, 0.8, 0.62))
    rng = s.rng
    # clouds on all four walls
    for k in range(60):
        wall = k % 4
        u, yy = rng.uniform(-0.9, 0.9), rng.uniform(8, 16)
        sx, sy = rng.uniform(3, 7), rng.uniform(1.2, 2.2)
        if wall < 2:
            z = Z1 - 0.1 if wall == 0 else Z0 + 0.1
            x = u * 23
            for j in range(3):
                s.ell(x + (j - 1) * sx * 0.35, yy + (0.3 if j == 1 else 0), z, sx * 0.55, sy, 0.3, ILL, WHITE)
        else:
            x = X1 - 0.1 if wall == 2 else X0 + 0.1
            z = u * 38
            for j in range(3):
                s.ell(x, yy + (0.3 if j == 1 else 0), z + (j - 1) * sx * 0.35, 0.3, sy, sx * 0.55, ILL, WHITE)
    # painted village along the bottom of the walls: terracotta roofs, cream walls
    def house(x, z, along_x, wdt, ht, inward):
        if along_x:
            s.abox(x - wdt / 2, x + wdt / 2, 0, ht, z, z + inward * 0.12, ILL, (0.96, 0.9, 0.78))
            for j in range(6):
                f = j / 6
                s.abox(x - wdt / 2 * (1 - f) - 0.3, x + wdt / 2 * (1 - f) + 0.3, ht + j * 0.35, ht + (j + 1) * 0.35,
                       z + inward * 0.12, z + inward * 0.2, ILL, (0.78, 0.35, 0.22))
            s.abox(x - 0.6, x + 0.6, ht * 0.25, ht * 0.65, z + inward * 0.12, z + inward * 0.16, ILL, (0.45, 0.65, 0.85))
        else:
            s.abox(z, z + inward * 0.12, 0, ht, x - wdt / 2, x + wdt / 2, ILL, (0.96, 0.9, 0.78))
            for j in range(6):
                f = j / 6
                s.abox(z + inward * 0.12, z + inward * 0.2, ht + j * 0.35, ht + (j + 1) * 0.35,
                       x - wdt / 2 * (1 - f) - 0.3, x + wdt / 2 * (1 - f) + 0.3, ILL, (0.78, 0.35, 0.22))
            s.abox(z + inward * 0.12, z + inward * 0.16, ht * 0.25, ht * 0.65, x - 0.6, x + 0.6, ILL, (0.45, 0.65, 0.85))
    for x in range(-21, 22, 7):
        house(x, Z1, True, 5.6, rng.uniform(3.2, 4.4), -1)
    for z in range(-34, 35, 7):
        house(z, X0, False, 5.6, rng.uniform(3.2, 4.4), 1)
        house(z, X1, False, 5.6, rng.uniform(3.2, 4.4), -1)
    # start and finish lines, the gate
    s.line((-24.5, -32), (24.5, -32), 0.25, WHITE, y=0.0)
    s.line((-24.5, 28), (24.5, 28), 0.3, (0.9, 0.1, 0.1), y=0.0)
    s.abox(-4, 4, 0, 7, Z0 + 0.05, Z0 + 0.3, "MetalPlate", (0.55, 0.58, 0.6))
    s.abox(-0.05, 0.05, 0, 7, Z0 + 0.3, Z0 + 0.35, ILL, (0.2, 0.2, 0.2))
    # the tree and the doll
    s.prop("CupuacuTree01", 7, 0, 36, 20, 2.2)
    s.prop("CupuacuTree01", -8, 0, 37.5, 160, 1.6)
    s.vcyl(0, 0, 33, 3.0, 0.4, ILL, (0.85, 0.8, 0.7))
    young_hee(s, 0, 33, 180, H=7.0, y=0.4)
    s.sign("05:00", 0, 12.5, Z1 - 0.15, 0, 0.3, (1, 0.15, 0.15), (0.03, 0.03, 0.04), mat=GLOW)
    for k, z in enumerate(range(-28, 29, 14)):
        for side in (-1, 1):
            guard(s, side * 23.5, z, 90 if side < 0 else 270, ("circle", "triangle", "square")[k % 3])
    for z in (-20, 0, 20):
        for side in (-1, 1):
            s.portal(side * 22.0, 0.0, z, 90 if side > 0 else 270, "coffin", "ELIMINATED")
    guide_board(s, "rlgl", 0, 2.8, -33.5, 0)
    s.spot("rlgl", 0, 0, -36.5, 0)
    s.portal(-20, 0.0, -38, 0, "dorm", "BACK TO DORM")
    s.portal(0, 0.0, 30.5, 0, "dorm_win", "SURVIVED")


def dalgona(sg):
    """Dalgona: a giant pastel playground; four shape stalls (circle, triangle, star, umbrella)."""
    sg.at("dalgona")
    s = sg
    X0, X1, Z0, Z1, H = -28, 28, -22, 22, 14
    s.hall(X0, X1, Z0, Z1, H, (0.97, 0.8, 0.85), "sand_1", (0.97, 0.88, 0.7))
    stripes = [(0.98, 0.75, 0.82), (0.75, 0.92, 0.85), (1, 0.93, 0.6), (0.82, 0.78, 0.97)]
    for k, x in enumerate(range(-28, 28, 7)):
        s.abox(x, x + 7, 0, H, Z1 - 0.06, Z1, ILL, stripes[k % 4])
        s.abox(x, x + 7, 0, H, Z0, Z0 + 0.06, ILL, stripes[(k + 2) % 4])
    for k, z in enumerate(range(-22, 22, 11)):
        s.abox(X0, X0 + 0.06, 0, H, z, z + 11, ILL, stripes[(k + 1) % 4])
        s.abox(X1 - 0.06, X1, 0, H, z, z + 11, ILL, stripes[(k + 3) % 4])
    s.ell(-20, 11, Z1 - 0.1, 4, 4, 0.3, ILL, (1, 0.85, 0.3))                               # painted sun
    # giant slide: tower, stairs, slide
    s.abox(-3, 3, 0, 6, 8, 14, ILL, (0.98, 0.6, 0.72))
    s.abox(-3.3, 3.3, 6, 6.3, 7.7, 14.3, ILL, (1, 0.85, 0.35))
    for x in (-3.2, 3.2):
        s.abox(x - 0.1, x + 0.1, 6.3, 7.3, 8, 14, ILL, (0.5, 0.72, 0.95))
    s.stairs(4.5, 0, 14, 180, 24, 2.2, ILL, (0.5, 0.72, 0.95))                               # from the back, up to 6 m
    s.abox(3, 5.6, 5.6, 6, 6.0, 8.0, ILL, (0.5, 0.72, 0.95))                                  # top step to tower
    A, B = s.P(0, 6.0, 8.0), s.P(0, 0.05, 8.0 - 6.0 / math.tan(math.radians(28)))
    s.w.beam(A, B, 3.0, 0.4, ILL, (1, 0.85, 0.35), over=0.1)
    for sx in (-1.6, 1.6):
        s.w.beam(A + np.array([sx, 0.7, 0]), B + np.array([sx, 0.7, 0]), 0.15, 0.8, ILL, (0.98, 0.5, 0.65))
    # swings
    for k in range(3):
        x = -16 + k * 2.2
        s.abox(x - 0.05, x + 0.05, 0.6, 3.6, 4.95, 5.05, "metal_4")
        s.abox(x - 0.05, x + 0.05, 0.6, 3.6, 6.95, 7.05, "metal_4")
        s.abox(x - 0.3, x + 0.3, 0.55, 0.62, 5.6, 6.4, ILL, (0.95, 0.3, 0.3))
    s.abox(-17.5, -10.5, 3.6, 3.8, 5.4, 6.6, ILL, (0.95, 0.35, 0.35))
    for x in (-17.4, -10.6):
        for z in (4.8, 7.2):
            s.cyl((x, 0, z), (x, 3.7, 6.0 + (z - 6) * 0.1), 0.2, ILL, (0.95, 0.35, 0.35))
    # jungle gym
    for i in range(4):
        for j in range(4):
            c = stripes[(i + j) % 4]
            s.cyl((13 + i * 1.5, 0, 6 + j * 1.5), (13 + i * 1.5, 4.5, 6 + j * 1.5), 0.12, ILL, c)
    for lv in (1.5, 3.0, 4.5):
        for i in range(4):
            s.cyl((13, lv, 6 + i * 1.5), (17.5, lv, 6 + i * 1.5), 0.1, ILL, (0.5, 0.72, 0.95))
            s.cyl((13 + i * 1.5, lv, 6), (13 + i * 1.5, lv, 10.5), 0.1, ILL, (0.98, 0.6, 0.72))
    # sandbox and seesaw
    for (a, b) in (((-24, -6), (-17, -6)), ((-17, -6), (-17, 1)), ((-17, 1), (-24, 1)), ((-24, 1), (-24, -6))):
        s.line(a, b, 0.35, (0.85, 0.6, 0.35), y=0, mat="WoodTeakX")
    s.abox(20, 21, 0, 0.6, -6, -5, ILL, (1, 0.85, 0.35))
    s.w.beam(s.P(20.5, 0.35, -9.5), s.P(20.5, 1.05, -1.5), 0.5, 0.12, ILL, (0.5, 0.72, 0.95))
    # the four shape stalls along the south wall
    shapes = ["circle", "triangle", "star", "umbrella"]
    for k, name in enumerate(shapes):
        x = -16.5 + k * 11
        s.abox(x - 3.5, x + 3.5, 0, 0.9, -19.5, -17.5, ILL, (0.95, 0.95, 0.95))                    # counter
        s.abox(x - 3.7, x + 3.7, 4.4, 4.7, -20.5, -16.8, ILL, stripes[k])                         # awning
        for xx in (x - 3.6, x + 3.6):
            s.abox(xx - 0.08, xx + 0.08, 0, 4.4, -17, -16.84, ILL, WHITE)
        s.abox(x - 2.2, x + 2.2, 5.2, 9.6, Z0 + 0.06, Z0 + 0.12, ILL, WHITE)
        s.bitmap(SHAPES[name], x, 7.4, Z0 + 0.13, 180, 0.17, (0.75, 0.45, 0.15))
        for t in range(4):                                                                         # tins and candies
            tx = x - 2.4 + t * 1.6
            s.vcyl(tx, 0.9, -18.5, 0.5, 0.12, "metal_4", (0.8, 0.8, 0.85))
            s.vcyl(tx, 1.02, -18.5, 0.4, 0.02, ILL, (0.85, 0.55, 0.2))
        s.line((x - 3, -16), (x + 3, -16), 0.15, stripes[k], y=0.0)
        s.ftext(name.upper(), x, -15.2, 180, 0.07, (0.4, 0.3, 0.3), y=0.0)
    s.sign("DALGONA\nCARVE THE SHAPE OUT WITHOUT BREAKING IT.\n10 MINUTES.", 0, 11.5, Z0 + 0.15, 180, 0.07,
           (0.6, 0.35, 0.15), (1, 0.95, 0.85))
    guard(s, -26, -10, 90, "triangle")
    guard(s, 26, -10, 270, "circle")
    guide_board(s, "dalgona", -12, 3.0, 14, 180)
    s.spot("dalgona", 0, 0, 18, 180)
    s.portal(-5, 0, 19, 180, "dorm", "BACK TO DORM")
    s.portal(5, 0, 19, 180, "coffin", "ELIMINATED")


def tug(sg):
    """Tug of War: two yellow platforms 12 m up under a circus big-top, the axe above the rope."""
    sg.at("tug")
    s = sg
    X0, X1, Z0, Z1, H = -16, 16, -30, 30, 22
    s.hall(X0, X1, Z0, Z1, H, (0.12, 0.1, 0.12), "concrete_6", (0.25, 0.25, 0.27), ceiling=None)
    # big-top ceiling: dark red and green stripes rising to the centre, bulbs round the rim
    for k in range(20):
        a = k / 20 * 2 * math.pi
        rim = np.array([math.sin(a) * 18, H, math.cos(a) * 32])
        A, B = s.P(*rim), s.P(0, H + 10, 0)
        s.w.beam(A, B, 8.5, 0.2, ILL, (0.45, 0.06, 0.08) if k % 2 else (0.06, 0.28, 0.16))
    s.abox(X0 - 0.5, X1 + 0.5, H, H + 0.3, Z0 - 0.5, Z0, ILL, (0.1, 0.1, 0.1))
    PY = 12.0
    for sgn in (-1, 1):
        z0, z1 = sgn * 6, sgn * 22
        s.abox(-3, 3, 0, PY, z0, z1, "concrete_6", (0.55, 0.55, 0.55))
        s.abox(-3.1, 3.1, PY - 0.3, PY, z0, z1, ILL, (1, 0.82, 0.1))                          # yellow deck
        for x in (-2.9, 2.9):                                                                     # yellow railings
            zr = z1 - sgn * 2.6 if x > 0 else z1                                                  # gap for the stairs
            s.abox(x - 0.05, x + 0.05, PY + 0.95, PY + 1.05, z0, zr, ILL, (1, 0.82, 0.1))
            for z in np.linspace(z0, zr, 7):
                s.abox(x - 0.05, x + 0.05, PY, PY + 1.0, z - 0.05, z + 0.05, ILL, (1, 0.82, 0.1))
        for x in (-2.6, 2.6):                                                                     # hazard posts at the edge
            for j in range(8):
                s.abox(x - 0.15, x + 0.15, PY + j * 0.25, PY + (j + 1) * 0.25, z0 - sgn * 0.0, z0 + sgn * 0.3,
                       ILL, BLACK if j % 2 else (1, 0.82, 0.1))
        s.bulbs([(x, PY - 0.15, z) for x in (-3.15, 3.15) for z in np.linspace(z0, z1, 14)], (1, 0.85, 0.5), 0.18)
        for j in range(10):                                                                       # ten places per team
            z = sgn * (8 + j * 1.35)
            s.ftext(str(j + 1), -1.3, z, 0 if sgn < 0 else 180, 0.05, BLACK, y=PY)
        # switchback stairs up the outside
        s.stairs(4.2, 0, sgn * 21.5, 180 if sgn > 0 else 0, 24, 2.0, ILL, (0.85, 0.85, 0.2))
        s.abox(3.2, 7.4, 5.6, 6.0, sgn * 13.8, sgn * 11.8, ILL, (0.85, 0.85, 0.2))
        s.stairs(6.4, 6.0, sgn * 11.8, 0 if sgn > 0 else 180, 24, 2.0, ILL, (0.85, 0.85, 0.2))
        s.abox(3.0, 7.4, PY - 0.4, PY, sgn * 19.5, sgn * 21.5, ILL, (0.85, 0.85, 0.2))
        s.sign("TEAM " + ("1" if sgn < 0 else "2"), 0, PY + 3.5, sgn * 22.6, 0 if sgn > 0 else 180, 0.12, WHITE, (0.05, 0.05, 0.06))
    s.cyl((0, PY + 1.0, -21), (0, PY + 1.0, 21), 0.14, "Fabric1", (0.85, 0.75, 0.55))           # the rope
    s.cyl((0, PY + 1.0, -0.3), (0, PY + 1.0, 0.3), 0.2, ILL, (0.9, 0.1, 0.1))                     # centre mark
    # the axe hanging over the middle
    for x in (-1.2, 1.2):
        s.cyl((x, H + 3, 0), (x, PY + 4.5, 0), 0.12, "metal_4")
    s.abox(-1.4, 1.4, PY + 4.3, PY + 4.6, -0.15, 0.15, "metal_4")
    s.abox(-0.35, 0.35, PY + 3.6, PY + 4.3, -0.35, 0.35, "metal_4", (0.3, 0.3, 0.32))                # axe head
    for j in range(6):                                                                                # blade, widening
        wdt = 0.8 + j * 0.28
        s.abox(-0.04, 0.04, PY + 3.6 - (j + 1) * 0.22, PY + 3.6 - j * 0.22, -wdt / 2, wdt / 2, "chrome", (0.9, 0.9, 0.95))
    s.abox(-0.05, 0.05, PY + 2.2, PY + 2.3, -1.15, 1.15, ILL, (1, 1, 1))                               # the edge
    # the drop: elimination pads under the gap
    for x in (-2, 2):
        for z in (-3, 0, 3):
            s.portal(x, 0, z, 0, "coffin")
    s.ftext("ELIMINATED", 0, -4.6, 0, 0.12, (1, 0.2, 0.2), y=0.0)
    s.sign("TUG OF WAR\nTEAMS OF 10. PULL THE OTHER TEAM\nOFF THEIR PLATFORM.", 12, 4.0, Z1 - 0.3, 0, 0.06,
           WHITE, (0.08, 0.08, 0.1))
    guide_board(s, "tug", -6, 2.8, -24, 0)
    s.spot("tug", 5.3, 0, -25.5, 0)
    s.portal(-4, 0, -27, 0, "dorm", "BACK TO DORM")


def marbles(sg):
    """Marbles: an old neighbourhood of alleys under a painted sunset."""
    sg.at("marbles")
    s = sg
    X0, X1, Z0, Z1, H = -30, 30, -25, 25, 16
    s.hall(X0, X1, Z0, Z1, H, (0.5, 0.35, 0.6), "concrete_4", (0.62, 0.58, 0.55))
    bands = [(1, 0.62, 0.32), (1, 0.55, 0.4), (0.98, 0.5, 0.5), (0.85, 0.45, 0.6), (0.62, 0.4, 0.65), (0.4, 0.33, 0.6)]
    for k, col in enumerate(bands):
        y0 = 3 + k * 2.2
        for (a, b, c, d) in ((X0, X1, Z1 - 0.06, Z1), (X0, X1, Z0, Z0 + 0.06)):
            s.abox(a, b, y0, y0 + 2.2, c, d, ILL, col)
        for (a, b) in ((X0, X0 + 0.06), (X1 - 0.06, X1)):
            s.abox(a, b, y0, y0 + 2.2, Z0, Z1, ILL, col)
    rng = s.rng

    def house(x, z, wdt, dep, yaw, wall=(0.9, 0.85, 0.75)):
        X, Y, Z = basis_upright(yaw)
        c = s.P(x, 0, z)
        hh = rng.uniform(3.0, 3.8)
        s.w.box(c, X, Y, Z, wdt, dep, hh, "PlasterStucco", wall)
        # roof: two sloped beams meeting along the ridge
        for sgn in (-1, 1):
            eave = c + Y * sgn * (dep / 2 + 0.6) + UP * (hh - 0.3)
            ridge = c + UP * (hh + 1.5)
            n = norm(ridge - eave)
            Ls = float(np.linalg.norm(ridge - eave))
            Xr = X
            Zr = norm(np.cross(Xr, n)) * (1 if np.dot(np.cross(Xr, n), UP) > 0 else -1)
            Yr = np.cross(Zr, Xr)
            s.w.box((eave + ridge) / 2 - Zr * 0.15, Xr, Yr, Zr, wdt + 1.0, Ls + 0.1, 0.18, "roof_3", (0.35, 0.38, 0.45))
        door = c - Y * (dep / 2 + 0.02) + X * rng.uniform(-wdt / 4, wdt / 4)
        s.w.box(door, X, Y, Z, 1.1, 0.06, 2.1, "WoodPlaknsOldX", (0.45, 0.3, 0.2))
        for wx in (-wdt / 3, wdt / 3):
            win = c - Y * (dep / 2 + 0.02) + X * wx + UP * 1.3
            s.w.box(win, X, Y, Z, 0.9, 0.06, 0.8, ILL, (1, 0.8, 0.45))
    for row, z in enumerate((-14, -2, 10)):
        for col, x in enumerate((-20, -8, 4, 16)):
            if (row, col) == (1, 1):
                continue                                                                 # the little square
            house(x + rng.uniform(-1, 1), z, rng.uniform(6.5, 8.5), 5.5, 180 if row % 2 == 0 else 0)
    # low walls with gates and street lamps along the alleys
    for z in (-7.5, 4.5, 16.5):
        for x in range(-26, 27, 6):
            if abs(x) < 2:
                continue
            s.abox(x - 2.4, x + 2.4, 0, 1.4, z - 0.15, z + 0.15, "brick_3", (0.75, 0.55, 0.45))
    for (x, z) in ((-26, -8), (-14, 4), (-2, -8), (10, 4), (22, -8), (-26, 16), (22, 16), (-2, 16)):
        s.vcyl(x, 0, z + 1.0, 0.15, 4.2, "metal_4", (0.3, 0.3, 0.32))
        s.ell(x, 4.2, z + 1.0, 0.5, 0.5, 0.5, GLOW, (1, 0.85, 0.5))
    s.abox(-30, 30, 7.5, 7.55, 22.9, 23.0, ILL, BLACK)                                           # power lines
    s.abox(-30, 30, 7.2, 7.25, -19.5, -19.4, ILL, BLACK)
    s.sign("SUPER", 4, 4.3, 7.15, 0, 0.12, (1, 1, 1), (0.85, 0.15, 0.15))
    # marbles and holes
    cols = [(0.9, 0.2, 0.2), (0.2, 0.5, 0.95), (0.2, 0.8, 0.4), (1, 0.85, 0.2), (0.7, 0.3, 0.9), (1, 1, 1)]
    for _ in range(80):
        x, z = rng.uniform(-28, 28), rng.uniform(-23, 23)
        s.ell(x, 0.06, z, 0.12, 0.12, 0.12, "glass_1", rng.choice(cols))
    for (x, z) in ((-8, -2), (-5, 1), (-26, -4), (8, -10), (20, 22), (-14, 20), (26, 2)):
        s.vcyl(x, 0.0, z, 0.35, 0.013, ILL, (0.15, 0.12, 0.1))
        s.ell(x + 0.6, 0.12, z + 0.3, 0.3, 0.25, 0.3, "Fabric1", (0.85, 0.65, 0.5))           # marble pouch
    s.sign("MARBLES\nPAIR UP. WIN ALL 10 OF YOUR PARTNER'S\nMARBLES IN 30 MINUTES - ANY GAME YOU LIKE.",
           0, 2.6, -24.6, 180, 0.05, WHITE, (0.1, 0.08, 0.12))
    s.sign("GGANBU", 0, 5.0, -24.6, 180, 0.15, (1, 0.85, 0.4), None)
    guard(s, -3, -21, 0, "square")
    guard(s, 3, -21, 0, "circle")
    guide_board(s, "marbles", 0, 2.8, -18.5, 0)
    s.spot("marbles", 0, 0, -21, 0)
    s.portal(-6, 0, -23, 0, "dorm", "BACK TO DORM")
    s.portal(6, 0, -23, 0, "coffin", "ELIMINATED")


def glass_bridge(sg, rows=18):
    """Glass Stepping Stones: 18 rows of two panels, one tempered, one that breaks (a hidden portal)."""
    sg.at("glass")
    s = sg
    X0, X1, Z0, Z1, H = -15, 15, -42, 42, 46
    s.hall(X0, X1, Z0, Z1, H, (0.05, 0.05, 0.1), "concrete_6", (0.08, 0.08, 0.1), ceiling=(0.04, 0.04, 0.07))
    rng = s.rng
    for _ in range(160):                                                                   # stars in the dark
        wall = rng.randrange(4)
        yy = rng.uniform(4, H - 2)
        if wall < 2:
            s.ell(rng.uniform(-14.5, 14.5), yy, Z1 - 0.1 if wall == 0 else Z0 + 0.1, 0.12, 0.12, 0.05, GLOW, (1, 1, 0.9))
        else:
            s.ell(X1 - 0.1 if wall == 2 else X0 + 0.1, yy, rng.uniform(-41, 41), 0.05, 0.12, 0.12, GLOW, (1, 1, 0.9))
    BY = 30.0
    # start stage: mirror floor, bulb-lined arch, pink curtains
    s.abox(-6, 6, BY - 1.0, BY, -38, -24.0, "mirror_1", (0.9, 0.85, 0.9))
    s.abox(-6, 6, BY - 3.0, BY - 1.0, -38, -24.0, ILL, (0.95, 0.35, 0.55))
    for k in range(16):                                                                    # numbered spots
        x, z = -3 + (k % 4) * 2, -35 + (k // 4) * 2.4
        s.ftext(f"{k + 1:02d}", x, z, 0, 0.05, (1, 0.4, 0.6), y=BY)
    s.abox(-5, 5, BY, BY + 7, -38.3, -38, ILL, (0.95, 0.45, 0.62))
    for k in range(12):                                                                    # curtain folds
        x = -5 + k * 0.85
        s.abox(x, x + 0.4, BY, BY + 7, -38.0, -37.8, ILL, (0.85, 0.3, 0.5))
    pts = [(-5.6, BY + y, -37.7) for y in np.linspace(0.3, 6.5, 12)] + [(5.6, BY + y, -37.7) for y in np.linspace(0.3, 6.5, 12)]
    pts += [(5.6 * math.cos(a), BY + 6.5 + 2.4 * math.sin(a), -37.7) for a in np.linspace(0, math.pi, 16)]
    s.bulbs(pts, (1, 0.92, 0.7), 0.25)
    s.bulbs([(x, BY - 0.1, -24.0) for x in np.linspace(-5.8, 5.8, 20)], (1, 0.92, 0.7), 0.2)
    # the rows: 2.25 m pitch, 1.2 x 1.1 m panels. Avatars can't jump, so - as in HotKitty's bridge - invisible
    # ("discard") walkways bridge the 1.15 m between rows. Each row still has its open middle and open sides:
    # to go on you must step onto the left or the right panel.
    z_first = -22.3
    safe = [rng.choice((-1, 1)) for _ in range(rows)]
    for i in range(rows):
        z = z_first + i * 2.25
        for side in (-1, 1):
            x = side * 0.95
            s.abox(x - 0.6, x + 0.6, BY - 0.05, BY, z - 0.55, z + 0.55, "glass_1", (0.72, 0.95, 0.88))
            for (a, b, c, d) in ((x - 0.66, x + 0.66, z - 0.6, z - 0.55), (x - 0.66, x + 0.66, z + 0.55, z + 0.6),
                                 (x - 0.66, x - 0.6, z - 0.6, z + 0.6), (x + 0.6, x + 0.66, z - 0.6, z + 0.6)):
                s.abox(a, b, BY - 0.12, BY - 0.01, c, d, "metal_4", (0.55, 0.57, 0.6))
            if side != safe[i]:
                s.portal(x, BY - 0.02, z, 0, "coffin", hidden=True)
        s.abox(-1.75, 1.75, BY - 0.25, BY - 0.12, z - 0.08, z + 0.08, "metal_4", (0.45, 0.47, 0.5))
    z_end = z_first + (rows - 1) * 2.25 + 0.55 + 1.15
    edges = [-24.0] + [z_first + i * 2.25 + sgn * 0.55 for i in range(rows) for sgn in (-1, 1)] + [z_end]
    for za, zb in zip(edges[0::2], edges[1::2]):                                      # the gaps between rows
        s.abox(-1.55, 1.55, BY - 0.05, BY, za - 0.02, zb + 0.02, "discard", WHITE)
    for x in (-1.75, 1.75):                                                                   # side girders
        s.abox(x - 0.1, x + 0.1, BY - 0.6, BY - 0.25, -24.0, z_end, "metal_4", (0.4, 0.42, 0.45))
    s.abox(-6, 6, BY - 1.0, BY, z_end, z_end + 10, "mirror_1", (0.9, 0.85, 0.9))
    s.abox(-6, 6, BY - 3.0, BY - 1.0, z_end, z_end + 10, ILL, (0.95, 0.35, 0.55))
    s.sign("16:00", 0, BY + 9, Z1 - 0.2, 0, 0.35, (1, 0.15, 0.15), (0.03, 0.03, 0.04), mat=GLOW)
    s.sign("GLASS STEPPING STONES\n18 STEPS. ONE PANEL OF EACH PAIR IS TEMPERED.\nTHE OTHER BREAKS. 16 MINUTES.",
           0, BY + 3.0, -37.6, 180, 0.04, WHITE, (0.1, 0.05, 0.08))
    # fall guard: floor pads for anyone who jumps off the side
    for x in (-6, 0, 6):
        for z in (-20, 0, 20):
            s.portal(x, 0, z, 0, "coffin")
    s.ftext("ELIMINATED", 0, -26, 0, 0.3, (1, 0.2, 0.2), y=0.0)
    # VIP balcony on the east wall
    s.abox(9, 15, BY + 3.6, BY + 4.0, -10, 10, "MarbleRed", (0.55, 0.1, 0.12))
    s.abox(8.9, 9.1, BY + 4.0, BY + 5.0, -10, 10, "gold", (1, 0.82, 0.3))
    for z in (-6, 0, 6):
        s.prop("sofa_7", 13.2, BY + 4.0, z, 270)
        s.prop("sofa_ph", 13.2, BY + 4.0, z, 270)
    s.vcyl(11.5, BY + 4.0, -3, 0.9, 0.7, "gold", (1, 0.82, 0.3))
    s.vcyl(11.5, BY + 4.0, 3, 0.9, 0.7, "gold", (1, 0.82, 0.3))
    s.sign("VIP", 14.9, BY + 7.5, 0, 90, 0.2, (1, 0.82, 0.3), (0.1, 0.02, 0.02))
    s.spot("vip", 12, BY + 4.0, 8.5, 270)
    s.portal(12, BY + 4.0, -8.5, 270, "dorm", "BACK TO DORM")
    guide_board(s, "glass", 0, BY + 2.6, -30.5, 0, floor_y=BY)
    s.spot("glass", 0, BY, -36.5, 0)
    s.portal(-4.5, BY, -37, 0, "dorm", "BACK TO DORM")
    s.spot("glass_win", 0, BY, z_end + 6, 0)
    s.portal(0, BY, z_end + 8, 0, "dorm_win", "SURVIVED")
    return safe


def squid_court(sg):
    """The final game, outdoors: the squid drawn in the dirt (circle on top, triangle and square below)."""
    sg.at("squid")
    s = sg
    s.abox(-30, 30, -0.4, 0, -30, 30, "sand_1", (0.78, 0.66, 0.5))
    for x in (-30, 30):                                                                          # low concrete walls
        s.abox(x - 0.4 * (1 if x > 0 else -1), x, 0, 3.0, -30, 30, "concrete_4", (0.6, 0.6, 0.6))
    for z in (-30, 30):
        s.abox(-30, 30, 0, 3.0, z - 0.4 * (1 if z > 0 else -1), z, "concrete_4", (0.6, 0.6, 0.6))
    W = 0.22
    C = (1, 1, 1)
    # rectangle (defensive house) with its gate at the bottom
    s.poly([(-6, -14), (6, -14), (6, -2), (-6, -2)], W, C)
    s.line((-1.2, -14), (1.2, -14), W + 0.05, (0.78, 0.66, 0.5), y=0.003, mat="sand_1")      # the gate gap
    # triangle on top of the rectangle, its tip reaching into the circle
    s.poly([(-6, -2), (6, -2), (0, 9)], W, C, closed=False)
    s.poly([(0, 9), (-6, -2)], W, C, closed=False)
    s.ring(0, 11.5, 4.0, W, C, n=48)                                                              # offence's house
    # promotion zones either side of the waist
    s.poly([(-6, -8), (-10, -8), (-10, -5), (-6, -5)], W, C, closed=False)
    s.poly([(6, -8), (10, -8), (10, -5), (6, -5)], W, C, closed=False)
    s.ftext("1", 0, 11.5, 180, 0.12, C, y=0.0)
    s.ftext("2", 0, 7.8, 180, 0.12, C, y=0.0)
    s.ftext("3", 0, -8, 180, 0.12, C, y=0.0)
    s.sign("SQUID GAME\nATTACKERS START IN THE CIRCLE AND HOP ON ONE FOOT\nUNTIL THEY CROSS THE WAIST. "
           "REACH THE SQUID'S\nHEAD (2) TO WIN. PUSHED OUT IS ELIMINATED.", 0, 1.8, -29.5, 180, 0.045, WHITE,
           (0.1, 0.1, 0.12))
    for k, (x, z) in enumerate(((-16, 0), (16, 0), (-16, 18), (16, 18), (0, 24))):
        guard(s, x, z, 180 if z > 0 else 0, ("circle", "triangle", "square")[k % 3])
    guide_board(s, "squid", -13, 2.8, -22, 0)
    s.spot("squid", 0, 0, -24, 0)
    s.portal(-10, 0, -27, 0, "dorm", "BACK TO DORM")
    s.portal(10, 0, -27, 0, "coffin", "ELIMINATED")
    s.portal(0, 0, 18.5, 0, "dorm_win", "WINNER")


def pentathlon(sg):
    """Six-Legged Pentathlon: a school courtyard, cloud-painted walls, bunting and a rainbow track, 5 stations."""
    sg.at("pentathlon")
    s = sg
    X0, X1, Z0, Z1, H = -32, 32, -24, 24, 16
    s.hall(X0, X1, Z0, Z1, H, (0.7, 0.86, 0.98), "sand_1", (0.95, 0.88, 0.72))
    rng = s.rng
    # school building on the north wall: white with blue bands, classroom windows with teal curtains
    s.abox(X0, X1, 0, 11, Z1 - 1.0, Z1, ILL, (0.97, 0.97, 0.98))
    for y in (0.0, 5.4):
        s.abox(X0, X1, y, y + 0.5, Z1 - 1.05, Z1 - 1.0, ILL, (0.6, 0.72, 0.95))
    for fl in range(2):
        for k in range(10):
            x = -28 + k * 6.2
            y = 1.5 + fl * 5.0
            s.abox(x, x + 4.6, y, y + 2.8, Z1 - 1.08, Z1 - 1.04, ILL, (0.3, 0.3, 0.32))
            s.abox(x + 0.2, x + 4.4, y + 0.2, y + 2.6, Z1 - 1.1, Z1 - 1.07, ILL, (0.2, 0.45, 0.4))
            for xx in (x + 0.2, x + 3.7):
                s.abox(xx, xx + 0.7, y + 0.2, y + 2.6, Z1 - 1.13, Z1 - 1.1, ILL, (0.45, 0.85, 0.8))
    # clouds on the other walls
    for _ in range(45):
        wall = rng.randrange(3)
        yy, sx = rng.uniform(5, 15), rng.uniform(2.5, 5)
        if wall == 0:
            x = rng.uniform(-28, 28)
            for j in range(3):
                s.ell(x + (j - 1) * sx * 0.3, yy, Z0 + 0.1, sx * 0.5, sx * 0.3, 0.2, ILL, WHITE)
        else:
            x = X0 + 0.1 if wall == 1 else X1 - 0.1
            z = rng.uniform(-22, 20)
            for j in range(3):
                s.ell(x, yy, z + (j - 1) * sx * 0.3, 0.2, sx * 0.3, sx * 0.5, ILL, WHITE)
    # bunting strung across the yard
    flag_cols = [(0.95, 0.3, 0.3), (1, 0.8, 0.2), (0.3, 0.75, 0.4), (0.3, 0.5, 0.95), (0.9, 0.5, 0.85)]
    for (a, b) in (((-30, 10.5, 22.5), (30, 10.5, -22)), ((30, 10.5, 22.5), (-30, 10.5, -22))):
        A, B = np.array(a), np.array(b)
        for t in np.linspace(0.03, 0.97, 34):
            p = A + (B - A) * t - np.array([0, 2.0 * math.sin(math.pi * t), 0])
            s.hang("Pyramid", p[0], p[1], p[2], 0.5, 0.05, 0.6, ILL, flag_cols[int(t * 34) % 5])
    # rainbow track: a stadium oval, seven bands
    rainbow = [(0.9, 0.2, 0.2), (1, 0.55, 0.15), (1, 0.85, 0.2), (0.3, 0.75, 0.35), (0.25, 0.5, 0.95),
               (0.35, 0.3, 0.75), (0.65, 0.35, 0.8)]
    for k, col in enumerate(rainbow):
        r = 7.5 + k * 0.45
        for side in (-1, 1):
            s.line((-12, side * r), (12, side * r), 0.46, col, y=0.002)
            s.ring(side * 12, 0, r, 0.46, col, y=0.002, n=18, a0=0 if side > 0 else 180, a1=180 if side > 0 else 360)
    # the five stations along the track, every ~10 m
    stations = [("1 DDAKJI", (-10, -8.8)), ("2 FLYING STONE", (2, -8.8)), ("3 GONGGI", (14.5, -4)),
                ("4 SPINNING TOP", (8, 8.8)), ("5 JEGI", (-6, 8.8))]
    for label, (x, z) in stations:
        side = -1 if z < 0 else 1
        sx, sz = x, z + side * 3.2
        s.vcyl(sx, 0, sz, 0.08, 2.0, "metal_4")
        s.sign(label.split()[0], sx, 2.35, sz, 180 if side < 0 else 0, 0.12, WHITE, (0.1, 0.1, 0.1))
        s.sign(" ".join(label.split()[1:]), sx, 1.6, sz, 180 if side < 0 else 0, 0.04, (0.1, 0.1, 0.1), (1, 1, 1))
        s.abox(x - 1.2, x + 1.2, 0, 0.03, z - side * 0.6 - 0.9, z - side * 0.6 + 0.9, "Fabric1", (0.95, 0.9, 0.8))
    x, z = -10, -8.8                                                                                  # ddakji tiles
    s.ybox(x - 0.3, 0.03, z - 0.6, 0.4, 0.4, 0.06, "paint_1", (0.2, 0.45, 0.95), yaw=20)
    s.ybox(x + 0.3, 0.03, z - 0.6, 0.4, 0.4, 0.06, "paint_1", (0.9, 0.15, 0.15), yaw=-10)
    s.ybox(2, 0, -14.5, 0.35, 0.1, 0.5, "rock_3", (0.7, 0.68, 0.65))                                  # flying stone target
    s.line((-0.5, -10.5), (4.5, -10.5), 0.08, WHITE, y=0.035)
    for k in range(5):                                                                               # gonggi stones
        s.ell(14.2 + k * 0.15, 0.05, -4.6 + (k % 2) * 0.15, 0.08, 0.08, 0.08, ILL, flag_cols[k])
    s.ring(8, 9.4, 0.6, 0.05, WHITE, y=0.035, n=16)                                                   # spinning top circle
    s.shape("Cone", 8, 0.03, 9.4, 0.12, 0.12, 0.12, "WoodTeakX")
    s.ring(-6, 9.4, 0.9, 0.05, WHITE, y=0.035, n=16)                                                  # jegi
    s.ell(-6, 0.1, 9.4, 0.12, 0.08, 0.12, ILL, (0.95, 0.3, 0.4))
    s.abox(-16.5, -15.5, 0, 4, -10, -9.6, ILL, (1, 0.85, 0.2))                                          # start / finish gate
    s.abox(-16.5, -15.5, 0, 4, -6.4, -6.0, ILL, (1, 0.85, 0.2))
    s.abox(-16.6, -15.4, 4, 4.8, -10, -6.0, ILL, (0.95, 0.3, 0.45))
    s.sign("START", -16.0, 4.4, -8.0, 90, 0.07, WHITE, None)
    s.sign("5:00", 0, 13, Z0 + 0.15, 180, 0.35, (1, 0.2, 0.2), (0.03, 0.03, 0.04), mat=GLOW)
    s.sign("SIX-LEGGED PENTATHLON\nTEAMS OF 5, LEGS TIED. EACH PLAYER CLEARS ONE OF\n"
           "5 GAMES ON THE WAY ROUND. 5 MINUTES.", 0, 3.0, Z0 + 0.15, 180, 0.045, WHITE, (0.1, 0.12, 0.2))
    guard(s, -30, 0, 90, "circle")
    guard(s, 30, 0, 270, "square")
    guide_board(s, "pentathlon", -22, 2.8, -12, 0)
    s.spot("pentathlon", -22, 0, -18, 0)
    s.portal(-26, 0, -21, 0, "dorm", "BACK TO DORM")
    s.portal(-18, 0, -21, 0, "coffin", "ELIMINATED")


def mingle(sg, n_doors=40):
    """Mingle: the carousel under a striped circus tent, rooms all round behind coloured doors."""
    sg.at("mingle")
    s = sg
    R0, RR, H = 26.0, 29.0, 9.0
    s.abox(-31, 31, -0.4, 0, -31, 31, "Marble", (0.95, 0.8, 0.86))
    door_cols = [(0.95, 0.3, 0.3), (1, 0.6, 0.2), (1, 0.85, 0.25), (0.6, 0.85, 0.3), (0.25, 0.7, 0.45),
                 (0.3, 0.75, 0.85), (0.3, 0.5, 0.95), (0.55, 0.4, 0.9), (0.9, 0.45, 0.8), (0.97, 0.65, 0.75)]
    step = 360.0 / n_doors
    for k in range(n_doors):
        a0 = math.radians(k * step)
        a1 = math.radians((k + 1) * step)
        am = (a0 + a1) / 2
        col = door_cols[k % 10]
        # wall pieces either side of the doorway (white panelling)
        for (ta, tb) in ((a0, am - 0.024), (am + 0.024, a1)):
            pa = np.array([math.sin(ta), 0, math.cos(ta)]) * R0
            pb = np.array([math.sin(tb), 0, math.cos(tb)]) * R0
            mid = (pa + pb) / 2
            yaw = math.degrees(math.atan2((pb - pa)[0], (pb - pa)[2]))
            s.ybox(mid[0], 0, mid[2], 0.3, float(np.linalg.norm(pb - pa)) + 0.05, H, ILL, (0.97, 0.88, 0.78), yaw=yaw)
        pd = np.array([math.sin(am), 0, math.cos(am)])
        tang = math.degrees(am) + 90
        c = pd * R0
        s.ybox(c[0], 2.4, c[2], 0.32, 1.45, H - 2.4, ILL, (0.97, 0.88, 0.78), yaw=tang)             # over the door
        tg = np.array([math.cos(am), 0, -math.sin(am)])                                               # along the wall
        arch = pd * (R0 - 0.17)
        for f in (-1, 1):                                                                             # coloured frame
            j = arch + tg * f * 0.7
            s.ybox(j[0], 0, j[2], 0.06, 0.2, 2.6, ILL, col, yaw=tang)
        s.ybox(arch[0], 2.4, arch[2], 0.06, 1.6, 0.25, ILL, col, yaw=tang)
        leaf = pd * (R0 + 0.5) + tg * 0.6                                                             # leaf swung open
        s.ybox(leaf[0], 0, leaf[2], 0.05, 0.9, 2.3, ILL, col, yaw=math.degrees(am))
        num = pd * (R0 - 0.2)
        s.sign(f"{k + 1:02d}", num[0], 3.0, num[2], (math.degrees(am)) % 360, 0.05, (0.2, 0.2, 0.25), WHITE)
        bow = pd * (R0 - 0.2)
        s.ell(bow[0] - math.cos(am) * 0.25, 4.0, bow[2] + math.sin(am) * 0.25, 0.4, 0.3, 0.1, ILL, (0.95, 0.4, 0.62), yaw=tang)
        s.ell(bow[0] + math.cos(am) * 0.25, 4.0, bow[2] - math.sin(am) * 0.25, 0.4, 0.3, 0.1, ILL, (0.95, 0.4, 0.62), yaw=tang)
        # the room behind: partitions and a back wall in the door's colour
        pa = np.array([math.sin(a0), 0, math.cos(a0)])
        p1, p2 = pa * R0, pa * RR
        mid = (p1 + p2) / 2
        s.ybox(mid[0], 0, mid[2], 0.2, RR - R0, 3.4, ILL, (0.8, 0.7, 0.66), yaw=math.degrees(a0))
        back = pd * RR
        s.ybox(back[0], 0, back[2], 0.25, 2 * RR * math.sin(math.radians(step / 2)) + 0.3, 3.4, ILL,
               tuple(0.6 + 0.4 * v for v in col), yaw=tang)
    for k in range(n_doors):                                                                   # room ceilings
        am = math.radians((k + 0.5) * step)
        c = np.array([math.sin(am), 0, math.cos(am)]) * (R0 + RR) / 2
        s.ybox(c[0], 3.4, c[2], 2 * RR * math.sin(math.radians(step / 2)) + 0.4, RR - R0 + 0.3, 0.2, ILL,
               (0.75, 0.66, 0.62), yaw=math.degrees(am))
    # bulbs round the wall and the striped tent
    s.bulbs([(math.sin(a) * (R0 - 0.3), H - 0.6, math.cos(a) * (R0 - 0.3)) for a in np.linspace(0, 2 * math.pi, 90, endpoint=False)],
            (1, 0.85, 0.55), 0.2)
    for k in range(32):
        a = k / 32 * 2 * math.pi
        rim = s.P(math.sin(a) * (R0 + 0.5), H, math.cos(a) * (R0 + 0.5))
        s.w.beam(rim, s.P(0, H + 14, 0), 5.4, 0.15, ILL, (0.97, 0.55, 0.4) if k % 2 else (0.99, 0.95, 0.94))
    for k in range(24):                                                                        # pink valance swags
        a = k / 24 * 2 * math.pi
        s.ell(math.sin(a) * (R0 - 0.4), H - 1.3, math.cos(a) * (R0 - 0.4), 6.0, 1.1, 0.25, ILL, (0.95, 0.5, 0.65),
              yaw=math.degrees(a) + 90)
    # the orange platform and the cake-like carousel
    s.vcyl(0, 0, 0, 28, 0.22, ILL, (0.98, 0.55, 0.2))                    # one step up (avatars can't jump)
    s.vcyl(0, 0.22, 0, 27.4, 0.03, ILL, (1, 0.65, 0.3))
    s.ring(0, 0, 13.8, 0.25, (1, 0.85, 0.5), y=0.26, n=60)
    s.vcyl(0, 0.25, 0, 7.0, 3.3, ILL, (0.98, 0.9, 0.92))
    for k in range(10):                                                                         # arched panels
        a = k / 10 * 2 * math.pi
        p = np.array([math.sin(a), 0, math.cos(a)]) * 3.45
        s.ybox(p[0], 0.8, p[2], 1.0, 0.05, 2.0, ILL, (0.95, 0.55, 0.65), yaw=math.degrees(a))
        s.ybox(p[0], 0.95, p[2], 0.8, 0.07, 1.7, ILL, (0.98, 0.9, 0.92), yaw=math.degrees(a))
    s.vcyl(0, 3.55, 0, 7.4, 0.25, ILL, (0.95, 0.55, 0.65))
    s.vcyl(0, 3.8, 0, 6.4, 0.6, ILL, (0.98, 0.92, 0.94))
    for k in range(3):                                                                          # three pink horses
        a = k / 3 * 2 * math.pi
        p = np.array([math.sin(a) * 1.8, 0, math.cos(a) * 1.8])
        hy = math.degrees(a) + 90
        s.vcyl(p[0], 4.4, p[2], 0.12, 4.5, "gold", (1, 0.8, 0.5))
        F = fwd(hy)
        b = p + UP * 5.6
        s.ell(b[0], b[1], b[2], 0.7, 0.75, 1.6, ILL, (0.98, 0.85, 0.9), yaw=hy)
        hd = b + F * 0.85 + UP * 0.55
        s.ell(hd[0], hd[1], hd[2], 0.4, 0.75, 0.45, ILL, (0.98, 0.85, 0.9), yaw=hy)
        s.ell(hd[0] - F[0] * 0.1, hd[1] + 0.2, hd[2] - F[2] * 0.1, 0.25, 0.6, 0.3, ILL, (0.95, 0.35, 0.6), yaw=hy)  # mane
        for fx in (-0.5, 0.5):
            for rx in (-0.2, 0.2):
                q = b + F * fx + right_of(hy) * rx
                s.cyl((q[0], q[1] - 0.2, q[2]), (q[0] + F[0] * fx * 0.3, q[1] - 1.0, q[2] + F[2] * fx * 0.3), 0.14, ILL, (0.98, 0.85, 0.9))
        s.ell(p[0], 9.1, p[2], 0.7, 0.5, 0.2, ILL, (0.95, 0.3, 0.6), yaw=hy)                     # bow on the pole
    s.sign("MINGLE\nWHEN THE MUSIC STOPS, GET INTO A ROOM WITH\nEXACTLY THE NUMBER CALLED. 30 SECONDS.",
           0, 6.2, -25.4, 180, 0.05, WHITE, (0.55, 0.15, 0.3))
    for k, a in enumerate((45, 135, 225, 315)):
        p = fwd(a) * 22
        guard(s, p[0], p[2], (a + 180) % 360, ("circle", "triangle", "square", "circle")[k])
    guide_board(s, "mingle", -8, 3.0, -6, 0, floor_y=0.25)
    s.spot("mingle", 0, 0.25, -11, 0)
    s.portal(-3, 0, -19, 0, "dorm", "BACK TO DORM")
    s.portal(3, 0, -19, 0, "coffin", "ELIMINATED")


def hide_and_seek(sg, n=11, cell=4.0):
    """Hide-and-Seek: a brick-alley maze with street lamps, manholes, green steel doorways and crates to hide
    behind. (The show added keys and locked doors - here it's plain hide and seek.)"""
    sg.at("hide")
    s = sg
    rng = random.Random(4)
    half = n * cell / 2
    s.abox(-half - 8, half + 8, -0.4, 0, -half - 14, half + 8, "asphalt_2", (0.45, 0.45, 0.47))
    # perfect maze (depth-first) with a few extra openings
    walls_h = [[True] * n for _ in range(n + 1)]       # horizontal walls between rows (z), walls_h[j][i]
    walls_v = [[True] * (n + 1) for _ in range(n)]     # vertical walls between columns (x), walls_v[j][i]
    seen = [[False] * n for _ in range(n)]
    stack = [(0, 0)]
    seen[0][0] = True
    while stack:
        i, j = stack[-1]
        nbrs = [(i + di, j + dj, di, dj) for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= i + di < n and 0 <= j + dj < n and not seen[j + dj][i + di]]
        if not nbrs:
            stack.pop()
            continue
        ni, nj, di, dj = rng.choice(nbrs)
        if di == 1:
            walls_v[j][i + 1] = False
        elif di == -1:
            walls_v[j][i] = False
        elif dj == 1:
            walls_h[j + 1][i] = False
        else:
            walls_h[j][i] = False
        seen[nj][ni] = True
        stack.append((ni, nj))
    for _ in range(n * 2):
        i, j = rng.randrange(1, n), rng.randrange(n)
        walls_v[j][i] = False
    walls_h[0][n // 2] = False                                       # entrance (south)
    WH = 4.2
    brick = [(0.62, 0.42, 0.36), (0.7, 0.5, 0.42), (0.55, 0.4, 0.38), (0.75, 0.62, 0.5)]
    green_doors = []
    for j in range(n + 1):
        for i in range(n):
            x0, z0 = -half + i * cell, -half + j * cell
            if walls_h[j][i]:
                s.abox(x0 - 0.15, x0 + cell + 0.15, 0, WH, z0 - 0.15, z0 + 0.15, "brick_2", rng.choice(brick))
            elif 0 < j < n and rng.random() < 0.28:
                green_doors.append(("h", x0 + cell / 2, z0))
    for j in range(n):
        for i in range(n + 1):
            x0, z0 = -half + i * cell, -half + j * cell
            if walls_v[j][i]:
                s.abox(x0 - 0.15, x0 + 0.15, 0, WH, z0 - 0.15, z0 + cell + 0.15, "brick_2", rng.choice(brick))
            elif 0 < i < n and rng.random() < 0.28:
                green_doors.append(("v", x0, z0 + cell / 2))
    # green steel doorways in some passages (the show's set; nothing locks here)
    for k, (o, x, z) in enumerate(green_doors):
        if o == "h":
            s.abox(x - 2.0, x - 0.7, 0, WH, z - 0.18, z + 0.18, "MetalPaintGreen", (0.25, 0.55, 0.4))
            s.abox(x + 0.7, x + 2.0, 0, WH, z - 0.18, z + 0.18, "MetalPaintGreen", (0.25, 0.55, 0.4))
            s.abox(x - 0.7, x + 0.7, 2.6, WH, z - 0.18, z + 0.18, "MetalPaintGreen", (0.25, 0.55, 0.4))
        else:
            s.abox(x - 0.18, x + 0.18, 0, WH, z - 2.0, z - 0.7, "MetalPaintGreen", (0.25, 0.55, 0.4))
            s.abox(x - 0.18, x + 0.18, 0, WH, z + 0.7, z + 2.0, "MetalPaintGreen", (0.25, 0.55, 0.4))
            s.abox(x - 0.18, x + 0.18, 2.6, WH, z - 0.7, z + 0.7, "MetalPaintGreen", (0.25, 0.55, 0.4))
    # hiding spots: crate stacks and bins in the dead ends (cells walled on three sides)
    for j in range(n):
        for i in range(n):
            closed = int(walls_h[j][i]) + int(walls_h[j + 1][i]) + int(walls_v[j][i]) + int(walls_v[j][i + 1])
            if closed < 3 or (i, j) == (n // 2, 0):
                continue
            cx, cz = -half + (i + 0.5) * cell, -half + (j + 0.5) * cell
            # tuck the stack into the back of the dead end, away from its open side
            ox = (0.9 if not walls_v[j][i] else -0.9 if not walls_v[j][i + 1] else 0.0)
            oz = (0.9 if not walls_h[j][i] else -0.9 if not walls_h[j + 1][i] else 0.0)
            bx, bz = cx + ox, cz + oz
            for kk in range(rng.randint(2, 4)):
                sz = rng.uniform(0.9, 1.3)
                s.ybox(bx + rng.uniform(-0.3, 0.3), kk * 0.9 if kk < 2 else 1.8, bz + rng.uniform(-0.3, 0.3), sz, sz,
                       0.9, "WoodPlaknsOldX", (0.85, 0.7, 0.5), yaw=rng.random() * 30)
    # street dressing: lamps, bins, manholes, graffiti-ish posters
    for _ in range(26):
        i, j = rng.randrange(n), rng.randrange(n)
        cx, cz = -half + (i + 0.5) * cell, -half + (j + 0.5) * cell
        kind = rng.random()
        if kind < 0.35:
            s.vcyl(cx + 1.4, 0, cz + 1.4, 0.12, 3.6, "metal_4", (0.3, 0.3, 0.32))
            s.ell(cx + 1.4, 3.6, cz + 1.4, 0.4, 0.4, 0.4, GLOW, (1, 0.85, 0.55))
        elif kind < 0.65:
            s.vcyl(cx - 1.3, 0, cz + 1.3, 0.6, 0.9, "MetalPaintBlue", (0.3, 0.45, 0.7))
        else:
            s.vcyl(cx, 0, cz, 0.9, 0.02, "metal_7", (0.35, 0.35, 0.35))
    # start yard (south): the gumball machine, the vests, the rules
    gz = -half - 8
    s.vcyl(0, 0, gz, 1.4, 1.2, ILL, (0.9, 0.15, 0.2))
    s.ell(0, 2.2, gz, 1.8, 1.8, 1.8, "GlassClear", (0.9, 0.95, 1))
    for k in range(40):
        a, r = rng.random() * 6.28, rng.random() * 0.7
        s.ell(math.sin(a) * r, 1.6 + rng.random() * 0.8, gz + math.cos(a) * r, 0.22, 0.22, 0.22, ILL,
              (0.9, 0.15, 0.15) if k % 2 else (0.2, 0.45, 0.95))
    s.ell(0, 3.15, gz, 0.6, 0.3, 0.6, ILL, (0.9, 0.15, 0.2))
    s.vcyl(-6, 0, gz + 2, 1.0, 0.9, ILL, (0.2, 0.45, 0.95))
    s.vcyl(6, 0, gz + 2, 1.0, 0.9, ILL, (0.9, 0.15, 0.15))
    s.ftext("BLUE - HIDERS", -6, gz + 3.6, 0, 0.05, (0.2, 0.45, 0.95), y=0.0)
    s.ftext("RED - SEEKERS", 6, gz + 3.6, 0, 0.05, (0.9, 0.15, 0.15), y=0.0)
    guard(s, -3, -half - 2, 0, "triangle")
    guard(s, 3, -half - 2, 0, "circle")
    guide_board(s, "hide", 0, 3.0, -half - 2.2, 0)
    s.spot("hide", 0, 0, gz + 4.5, 0)
    s.portal(-12, 0, gz, 0, "dorm", "BACK TO DORM")
    s.portal(12, 0, gz, 0, "coffin", "ELIMINATED")
    s.portal(0, 0, gz - 3.5, 0, "dorm_win", "SURVIVED")


def jump_rope(sg):
    """Jump Rope: a narrow walkway over a flower-filled pit, a gap in the middle; Young-hee and
    Cheol-su turning a giant rope."""
    sg.at("jumprope")
    s = sg
    X0, X1, Z0, Z1, H = -18, 18, -48, 48, 30
    s.hall(X0, X1, Z0, Z1, H, (0.97, 0.75, 0.82), "grass_1", (0.45, 0.65, 0.35))
    rng = s.rng
    for _ in range(140):                                                                  # the flower pit
        s.prop("FlowerPatch01", rng.uniform(-16, 16), 0, rng.uniform(-28, 28), rng.random() * 360, 3.0)
    BY = 9.0
    # start and finish platforms, white house-roof shapes behind them (like the set)
    for sgn in (-1, 1):
        z0 = sgn * 30
        s.abox(-6, 6, 0, BY, z0, z0 + sgn * 17, ILL, (0.62, 0.32, 0.45))
        s.abox(-6.1, 6.1, BY - 0.2, BY, z0, z0 + sgn * 17, ILL, (0.95, 0.5, 0.66))
        hz = sgn * 46.5
        s.abox(-8, 8, BY, BY + 5, hz - 0.3, hz + 0.3, ILL, (0.99, 0.97, 0.97))
        for j in range(8):
            f = j / 8
            s.abox(-9 * (1 - f) - 0.5, 9 * (1 - f) + 0.5, BY + 5 + j * 0.6, BY + 5 + (j + 1) * 0.6, hz - 0.35, hz + 0.35, ILL,
                   (0.95, 0.95, 0.96))
    # the walkway: 0.9 m wide and continuous (avatars can't jump), ramping down and up; in the middle the
    # "broken" stretch narrows to 0.6 m. Pink stripes are the safe spots when the rope comes round.
    LOW = BY - 1.5
    prof = [(-30, BY, 0.9), (-20, LOW, 0.9), (-1.5, LOW, 0.9), (1.5, LOW, 0.6), (20, LOW, 0.9), (30, BY, 0.9)]
    for (za, ya, wa), (zb, yb, wb) in zip(prof, prof[1:]):
        wd = wb if wb < wa else wa
        A, B = s.P(0, ya, za), s.P(0, yb, zb)
        s.w.beam(A, B, wd, 0.25, ILL, (0.98, 0.98, 0.98), over=0.05)
        for sx in (-1, 1):
            off = np.array([sx * (wd / 2 + 0.04), -0.25, 0])
            s.w.beam(A + off, B + off, 0.08, 0.3, ILL, (0.95, 0.4, 0.55))
    for z in (-16, -10, -4, 4, 10, 16):                                                    # safe stripes
        s.abox(-0.45, 0.45, LOW, LOW + 0.012, z - 0.6, z + 0.6, ILL, (0.95, 0.3, 0.55))
    s.ftext("SAFE", 0, -16, 0, 0.05, WHITE, y=LOW + 0.013)
    for z in (-20, -10, 10, 20):                                                           # slender supports
        s.cyl((0, 0, z), (0, BY - 1.8, z), 0.25, ILL, (0.95, 0.4, 0.55))
    # the dolls on either side, holding the rope up at its top swing
    hy = young_hee(s, -12, 0, 90, H=17, outfit="s3", rope_hand=True)
    hc = cheol_su(s, 12, 0, 270, H=17, rope_hand=True)
    A, B = hy, hc
    top = (A + B) / 2 + UP * 9.0
    pts = [A + (B - A) * t + (top - (A + B) / 2) * (4 * t * (1 - t)) for t in np.linspace(0, 1, 26)]
    for p, q in zip(pts, pts[1:]):
        s.w.cyl(p, q, 0.28, ILL, (0.75, 0.6, 0.45))
    s.sign("20:00", 0, 24, Z1 - 0.2, 0, 0.4, (1, 0.15, 0.15), (0.03, 0.03, 0.04), mat=GLOW)
    s.sign("JUMP ROPE\nCROSS THE BRIDGE IN 20 MINUTES. WHEN THE ROPE\nCOMES ROUND, BE ON A PINK STRIPE.", 0, BY + 3.0, -46.0, 180, 0.05, WHITE, (0.2, 0.08, 0.12))
    for x in (-9, -3.5, 3.5, 9):
        for z in (-20, -6, 6, 20):
            s.portal(x, 0, z, 0, "coffin")
    guide_board(s, "jumprope", 0, BY + 2.8, -34, 0, floor_y=BY)
    s.spot("jumprope", 0, BY, -40, 0)
    s.portal(-4, BY, -44, 0, "dorm", "BACK TO DORM")
    s.portal(0, BY, 40, 0, "dorm_win", "SURVIVED")


def sky_squid(sg):
    """Sky Squid Game: one tower of three platforms - square, then triangle, then circle - in a pink hall.
    A button on each starts the 15-minute round; push someone off to move up."""
    sg.at("sky")
    s = sg
    X0, X1, Z0, Z1, H = -32, 32, -32, 32, 72
    s.hall(X0, X1, Z0, Z1, H, (0.95, 0.6, 0.7), "concrete_6", (0.85, 0.55, 0.62), ceiling=(0.98, 0.8, 0.85))
    for k in range(0, 72, 6):                                                               # light bands
        for (a, b, c, d) in ((X0, X1, Z1 - 0.06, Z1), (X0, X1, Z0, Z0 + 0.06)):
            s.abox(a, b, k + 2.5, k + 2.7, c, d, ILL, (1, 0.88, 0.92))
    SQ, TR, CI = 38.0, 44.0, 50.0
    s.abox(-3.2, 3.2, 0, SQ - 0.8, -3.2, 3.2, "concrete_6", (0.5, 0.52, 0.5))              # the column
    s.abox(-3.6, 3.6, SQ - 0.8, SQ, -3.6, 3.6, "stones_5", (0.95, 0.82, 0.35))               # square platform
    # the diamond holding up the triangle: two pyramids point to point, then the triangle slab
    s.shape("Pyramid", 0, SQ, 0, 2.2, 2.2, 2.4, "rock_3", (0.25, 0.42, 0.42), yaw=45)
    s.hang("Pyramid", 0, TR - 0.6, 0, 5.2, 5.2, 3.2, "rock_3", (0.25, 0.42, 0.42), yaw=45)
    tri = [(0, 3.4), (2.95, -1.7), (-2.95, -1.7)]
    for j in range(14):                                                                     # filled triangle in strips
        f0, f1 = j / 14, (j + 1) / 14
        zb = -1.7 + (3.4 + 1.7) * f0
        wdt = 5.9 * (1 - (f0 + f1) / 2)
        s.abox(-wdt / 2, wdt / 2, TR - 0.6, TR, zb, -1.7 + 5.1 * f1, "rock_3", (0.28, 0.48, 0.48))
    s.vcyl(0, TR, 0, 1.0, CI - TR - 0.6, "rock_3", (0.22, 0.22, 0.25))
    s.vcyl(0, CI - 0.6, 0, 4.0, 0.6, "rock_3", (0.18, 0.18, 0.2))                            # the circle
    # buttons
    for (y, (x, z)) in ((SQ, (2.4, -2.4)), (TR, (0, -0.8)), (CI, (0.9, 0))):
        s.vcyl(x, y, z, 0.6, 0.08, ILL, (0.85, 0.85, 0.88))
        s.vcyl(x, y + 0.08, z, 0.42, 0.1, GLOW, (0.95, 0.1, 0.1))
    # narrow steps up between the levels (use them only when the round is won)
    s.stairs(-3.0, SQ, -3.0, 90, 24, 0.7, "stones_5", (0.9, 0.78, 0.35), run=0.25)
    s.abox(2.4, 3.4, TR - 0.3, TR, -3.35, -1.4, "stones_5", (0.9, 0.78, 0.35))
    for k in range(24):                                                                     # spiral to the circle
        a = math.radians(k * 13)                         # k=0 sits over the triangle's tip
        r = 2.35
        x, z = math.sin(a) * r, math.cos(a) * r
        s.ybox(x, TR + 0.25 * (k + 1) - 0.3, z, 0.7, 0.5, 0.3, "rock_3", (0.3, 0.3, 0.32), yaw=math.degrees(a) + 90)
    s.sign("SKY SQUID GAME\nSTART ON THE SQUARE. PRESS THE BUTTON: 15 MINUTES.\n"
           "SOMEONE MUST BE PUSHED OFF BEFORE THE REST MOVE UP\nTO THE TRIANGLE, THEN THE CIRCLE.",
           0, 3.0, Z0 + 0.15, 180, 0.06, WHITE, (0.25, 0.08, 0.15))
    s.sign("15:00", 0, 60, Z1 - 0.15, 0, 0.6, (1, 0.15, 0.15), (0.03, 0.03, 0.04), mat=GLOW)
    # the lift (a portal at the foot) and the fall pads all round
    s.spot("sky_top", -2.4, SQ, 2.4, 135)
    guide_board(s, "sky", 0, 3.0, -11, 0)
    s.spot("sky", 0, 0, -20, 0)
    s.portal(0, 0, -16, 0, "sky_top", "ELEVATOR")
    for r in (7, 13):
        for k in range(10 if r == 7 else 16):
            a = 2 * math.pi * k / (10 if r == 7 else 16)
            s.portal(math.sin(a) * r, 0, math.cos(a) * r, 0, "coffin")
    s.portal(-6, 0, -26, 0, "dorm", "BACK TO DORM")
    s.spot("sky_win", 0, CI, 0, 0)


def coffin_room(sg):
    """Where the eliminated go: black coffins with pink bows. A portal leads back to the dormitory."""
    sg.at("coffin")
    s = sg
    s.hall(-14, 14, -10, 10, 6, (0.12, 0.12, 0.14), "concrete_6", (0.2, 0.2, 0.22), ceiling=(0.08, 0.08, 0.1))
    for i in range(5):
        for j in range(2):
            x, z = -10 + i * 4.5, -4 + j * 6
            s.abox(x - 1.1, x + 1.1, 0, 0.6, z - 0.4, z + 0.4, ILL, (0.05, 0.05, 0.06))
            s.abox(x - 1.15, x + 1.15, 0.6, 0.72, z - 0.45, z + 0.45, ILL, (0.08, 0.08, 0.09))
            s.abox(x - 0.08, x + 0.08, 0.6, 0.74, z - 0.46, z + 0.46, ILL, (0.95, 0.35, 0.6))
            s.abox(x - 1.16, x + 1.16, 0.6, 0.74, z - 0.06, z + 0.06, ILL, (0.95, 0.35, 0.6))
            s.ell(x - 0.15, 0.82, z, 0.25, 0.18, 0.12, ILL, (0.95, 0.35, 0.6))
            s.ell(x + 0.15, 0.82, z, 0.25, 0.18, 0.12, ILL, (0.95, 0.35, 0.6))
    s.abox(-3, 3, 0, 4, 9.6, 10, "MetalPlate", (0.4, 0.4, 0.42))                            # incinerator door
    s.sign("ELIMINATED", 0, 4.8, 9.55, 0, 0.12, (1, 0.25, 0.4), None)
    s.sign("YOU HAVE BEEN ELIMINATED.\nSTEP ON THE PORTAL TO WATCH FROM THE DORMITORY.", 0, 3.0, -9.55, 180, 0.05,
           WHITE, (0.1, 0.1, 0.12))
    s.spot("coffin", 0, 0, -7.5, 180)
    s.portal(0, 0, -5.5, 180, "dorm", "BACK TO DORM")


STAGES = [("subway", subway), ("dorm", dorm), ("stairs", stair_maze), ("rlgl", rlgl), ("dalgona", dalgona),
          ("tug", tug), ("marbles", marbles), ("glass", glass_bridge), ("squid", squid_court),
          ("pentathlon", pentathlon), ("mingle", mingle), ("hide", hide_and_seek), ("jumprope", jump_rope),
          ("sky", sky_squid), ("coffin", coffin_room)]


def build(seed=7, upto=None):
    sg = SG(seed)
    info = {}
    for k, (name, fn) in enumerate(STAGES):
        if upto is not None and k >= upto:
            break
        before = sg.w.count
        r = fn(sg)
        info[name] = sg.w.count - before
        if name == "glass":
            info["glass_safe"] = r
    pairs = sg.emit_portals()
    sx, sz = POS["subway"]
    world = {
        "respawn": {"p": [sx + 0.0, 1.05, 1.5], "r": 0.0},
        "ambient": [1.0] * 11,
        "oceanlevel": -50.0,
        "weather": "Sunrise",
        "valuetype": "float",
        "objects": sg.w.groups,
    }
    return world, sg, info, pairs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "Downloads", "Squid-Game-3DX.world")
    upto = int(sys.argv[sys.argv.index("--upto") + 1]) if "--upto" in sys.argv else None
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
    world, sg, info, pairs = build(seed, upto)
    data = json.dumps(world, separators=(",", ":"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(data)
    print(f"Wrote {out}: {sg.w.count:,} objects, {pairs} portal pairs, {len(data) / 1048576:.1f} MB")
    for k, v in info.items():
        if k != "glass_safe":
            print(f"  {k:<11} {v:6d}")
    if "glass_safe" in info:
        print("  glass bridge safe side per row (L/R):", "".join("L" if v < 0 else "R" for v in info["glass_safe"]))


if __name__ == "__main__":
    main()
