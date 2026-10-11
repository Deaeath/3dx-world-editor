"""
Slutopoly for 3DXChat - a party board game world: a 26 m Monopoly-style board you play on with your avatar,
three big rule/question panels, a Game Master hot tub and a Guests lounge.

Everything written on the panels (rules, "Have you ever" questions, story topics, role plays, the location
groups and the pose wheel) comes from slutopoly_config.json next to this script, so the game can be changed
without touching the code. Run with --write-config to (re)create that file from the defaults.

Usage:  python slutopoly.py [out.world] [--write-config]
"""
import json
import math
import os
import sys

import numpy as np

from only_up import FONT as BASE_FONT, UP, World, basis_down, basis_upright, fwd, right_of

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "slutopoly_config.json")

U = 2.0                    # board grid unit (m): 13 units a side, 2x2 corners, 9 squares of 1 x 2 units per side
HALF = 6.5 * U             # board half size (13 m)
INNER = 4.5 * U            # inner edge of the squares (9 m)
TOP = 0.25                 # board surface height
BLACK, WHITE = (0.02, 0.02, 0.02), (1, 1, 1)
RED = (0.88, 0.08, 0.08)
TEAL = (0.0, 0.47, 0.45)
MINT = (0.80, 0.94, 0.88)
INK = "paint_1"            # matte paint for black ink
GLOW = "unlit"             # flat colour as given (Illum washes pale colours out to white in-game)

DEFAULT = {
    "title": "SLUTOPOLY",
    "rules_title": "HOW TO PLAY",
    "rules_intro": ["/ROLL 6 ON YOUR TURN AND MOVE THAT MANY SQUARES. FIRST TO FINISH "
                    "3 LAPS WINS AND PICKS THE NEXT GAME MASTER.",
                    "EVERYTHING IS OPT-IN: SAY PASS AND TAKE 1 STEP BACK INSTEAD."],
    "rules": [
        ["q", "TRUTH OR DARE: DO THE ONE WITH YOUR SQUARE'S NUMBER ON THE BIG PANEL. DONE = 2 STEPS FORWARD."],
        ["story", "STORY TIME: /ROLL 6 FOR A TOPIC AND TELL IT. THE ROOM LIKES IT = 2 STEPS FORWARD."],
        ["role", "ROLE PLAY: PICK A PARTNER AND A SCENE FROM THE LIST, 3 MINUTES. THE ROOM VOTES: 2 STEPS "
                 "FORWARD OR 2 BACK FOR YOU BOTH."],
        ["pose", "POSE: PICK A PARTNER, /ROLL 6 ON THE POSE WHEEL AND GO TO THAT SPOT FOR 3 MINUTES."],
        ["dance", "DANCE: DANCE NAKED UNTIL YOUR NEXT TURN."],
        ["strip", "STRIP: LOSE ONE ITEM - THE PLAYER BEHIND YOU PICKS WHICH."],
        ["clinic", "CLINIC: SIT OUT ONE TURN AT THE BAR NEXT DOOR. GRAB A DRINK."],
    ],
    "have_you_ever_title": "TRUTH OR DARE",
    "have_you_ever": [
        "KISS THE PLAYER YOU THINK IS HOTTEST",
        "NEVER HAVE I EVER: SAY ONE - ALL WHO HAVE, STRIP",
        "TWO TRUTHS AND A LIE ABOUT YOUR LOVE LIFE",
        "30 SECOND LAP DANCE FOR THE PLAYER ON YOUR LEFT",
        "THE BOLDEST THING YOU'VE EVER DONE AT A PARTY?",
        "SWAP ONE PIECE OF CLOTHING WITH ANOTHER PLAYER",
        "SEXY CATWALK ALL THE WAY ROUND THE BOARD",
        "TAKE ANYONE TO THE BEDROOMS FOR ONE MINUTE",
        "WOULD YOU RATHER: A 3SOME WITH FRIENDS OR STRANGERS?",
        "DESCRIBE YOUR DREAM HOOKUP IN THREE WORDS",
        "BODY SHOT AT THE BAR - YOU PICK WHO AND WHERE",
        "WHAT'S THE WILDEST PLACE YOU'VE HOOKED UP?",
        "WHISPER (PM) SOMETHING DIRTY TO THE PLAYER ACROSS",
        "RATE EVERYONE'S OUTFIT 1-10. LOWEST SCORE STRIPS",
        "TOPLESS UNTIL YOUR NEXT TURN",
        "WHAT'S AT THE TOP OF YOUR SEX BUCKET LIST?",
        "MAKE OUT WITH ANYONE YOU LIKE FOR 10 SECONDS",
        "WHO HERE HAVE YOU THOUGHT ABOUT NAKED?",
        "THE GROUP PICKS YOUR NEXT POSE PARTNER",
        "YOUR MOST AWKWARD HOOKUP STORY - GO",
        "SPANK OR GET SPANKED - YOU CHOOSE BY WHOM",
        "PICK SOMEONE TO SIT ON YOUR LAP TILL YOUR NEXT TURN",
    ],
    "tell_title": "STORY TIME",
    "tell": [
        "YOUR WILDEST PARTY NIGHT",
        "THE HOTTEST KISS YOU'VE EVER HAD",
        "A HOOKUP THAT WENT HILARIOUSLY WRONG",
        "YOUR GUILTIEST TURN-ON",
        "THE CRAZIEST PLACE YOU'VE HOOKED UP",
        "A FANTASY YOU'VE NEVER TOLD ANYONE",
    ],
    "roll_play_title": "ROLE PLAY:",
    "roll_play": [
        "TRUCK DRIVER / STRANDED MOTORIST", "FILM DIRECTOR / STAR", "PARTY GIRL / NERD",
        "FLIGHT ATTENDANT / PASSENGER", "OFFICER / ROBBER", "HOOKER / CUSTOMER", "QUARTERBACK / CHEERLEADER",
        "PRISON GUARD / INMATE", "PHOTOGRAPHER / MODEL", "CELEBRITY / FAN", "LIMO DRIVER / PASSENGER",
        "BOSS / SECRETARY", "ALIEN / ABDUCTEE", "PROFESSOR / GRAD STUDENT", "DENTIST / PATIENT", "VIRGIN / SLUT",
        "POOL BOY / COUGAR", "MASSEUSE / CLIENT", "REPAIRMAN / HOUSEWIFE", "LANDLORD / TENANT",
        "MECHANIC / CAR OWNER", "SNEAKING AROUND AT THE IN-LAWS", "ROYALTY / SUBJECT", "TRAPPED IN ELEVATOR",
    ],
    # colour groups of the 22 question squares, in board order (2 + 3 + 3 + 3 + 3 + 3 + 3 + 2, like Monopoly)
    "groups": [
        ["BAR SEX", [0.80, 0.72, 0.16]], ["OFFICE SEX", [0.30, 0.86, 0.92]], ["SEX TAPE", [0.93, 0.40, 0.88]],
        ["PORN MOVIE", [1.00, 0.72, 0.10]], ["HOTEL SEX", [0.90, 0.12, 0.12]], ["POOL PARTY", [1.00, 0.95, 0.15]],
        ["HOME SEX", [0.30, 0.92, 0.20]], ["CAR SEX", [0.24, 0.40, 0.92]],
    ],
    "poses": ["BED ORAL", "BENCH FOREPLAY", "COUCH ORAL", "BENCH ORAL", "BED FOREPLAY", "COUCH FOREPLAY"],
}

# colour of each kind of square (the rules panel's legend uses the same chips)
KIND_COL = {"q": (0.2, 0.42, 0.95), "story": (0.88, 0.08, 0.08), "role": (0.05, 0.6, 0.6), "pose": (0.96, 0.38, 0.66),
            "dance": (0.55, 0.3, 0.88), "strip": (0.86, 0.12, 0.3), "clinic": (0.2, 0.7, 0.25), "go": (0.98, 0.72, 0.1)}
KIND_TAG = {"q": "T/D", "story": "STORY", "role": "ROLE", "pose": "POSE", "dance": "DANCE", "strip": "STRIP",
            "clinic": "BAR", "go": "GO"}

# the 40 squares, GO first, in the order players move
LAYOUT = ["go",
          "q", "story", "q", "dance", "roll", "q", "strip", "q", "q",
          "clinic",
          "q", "strip", "q", "q", "roll", "q", "story", "q", "q",
          "safe",
          "q", "poses", "q", "q", "roll", "q", "q", "strip", "q",
          "gotoclinic",
          "q", "q", "dance", "q", "roll", "poses", "q", "strip", "q"]
GROUP_SIZES = [2, 3, 3, 3, 3, 3, 3, 2]

# ------------------------------------------------------------------ pixel font and icons
FONT = dict(BASE_FONT)
FONT.update({
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    ",": ["00000", "00000", "00000", "00000", "00110", "00100", "01000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    '"': ["01010", "01010", "01010", "00000", "00000", "00000", "00000"],
    "&": ["01100", "10010", "10100", "01000", "10101", "10010", "01101"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "=": ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
    ">": ["01000", "00100", "00010", "00001", "00010", "00100", "01000"],
    ";": ["00000", "01100", "01100", "00000", "01100", "00100", "01000"],
})

ICONS = {
    "check": ["1111111", "1....11", "1...1.1", "11.1..1", "1.1...1", "1.....1", "1111111"],
    "cross": ["1111111", "11...11", "1.1.1.1", "1..1..1", "1.1.1.1", "11...11", "1111111"],
    "dancer": [
        ".....11.....",
        ".....11.....",
        "....1111..1.",
        "...1.11..1..",
        "..1..11.1...",
        ".1...1111...",
        "1....111....",
        ".....11.....",
        ".....111....",
        "....11.11...",
        "...11...11..",
        "..11.....1..",
        ".11......1..",
        "11.......11.",
    ],
    "strip": [
        "11..........",
        "11.....11...",
        "11.....11...",
        "11....1111..",
        "11...1.11.1.",
        "11..1..11..1",
        "11.1...111..",
        "111....1111.",
        "11....11..1.",
        "11...11...1.",
        "11..11....1.",
        "11........1.",
        "11.......11.",
        "11..........",
        "1111........",
        "111111......",
    ],
    "masks": [
        "1111111.......",
        "1.....1.......",
        "1.1.1.1111111.",
        "1.....11.....1",
        "1.111.11.1.1.1",
        "1.....11.....1",
        ".1...1.1.111.1",
        "..111..1.1.1.1",
        ".......1.....1",
        "........1...1.",
        ".........111..",
    ],
    "poses": [
        "......11.11.....",
        ".....11111111...",
        "......111111....",
        ".......1111.....",
        "........11......",
        "1...............",
        "1..1111.........",
        "1.1111111111111.",
        "1111111111111111",
        "1..............1",
        "1..............1",
    ],
    "hat": [
        "....11111111....",
        "....11111111....",
        "....11111111....",
        "....11111111....",
        "....11111111....",
        "....22222222....",
        "....11111111....",
        "1111111111111111",
        ".11111111111111.",
    ],
    "arrow": [
        "...1..........",
        "..11..........",
        ".111..........",
        "11111111111111",
        "11111111111111",
        ".111..........",
        "..11..........",
        "...1..........",
    ],
}


def rects(bitmap, on="1"):
    """Cover a bitmap's 'on' cells with few rectangles (greedy: widest run, then as tall as it stays full)."""
    rows = [list(r) for r in bitmap]
    H = len(rows)
    W = max(len(r) for r in rows)
    for r in rows:
        r += ["."] * (W - len(r))
    done = [[False] * W for _ in range(H)]
    out = []
    for y in range(H):
        for x in range(W):
            if rows[y][x] != on or done[y][x]:
                continue
            w = 1
            while x + w < W and rows[y][x + w] == on and not done[y][x + w]:
                w += 1
            h = 1
            while y + h < H and all(rows[y + h][x + k] == on and not done[y + h][x + k] for k in range(w)):
                h += 1
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    done[yy][xx] = True
            out.append((x, y, w, h))
    return out


GLYPH_RECTS = {ch: rects(g) for ch, g in FONT.items()}


def plane_basis(Rv, Uv, Nv):
    """Box axes for a plane with text-right Rv, text-up Uv and normal Nv (boxes are symmetric across X and Y,
    so X may be flipped to keep the rotation proper)."""
    X, Y, Z = np.array(Rv, float), np.array(Uv, float), np.array(Nv, float)
    if np.linalg.det(np.column_stack([X, Y, Z])) < 0:
        X = -X
    return X, Y, Z


def draw_rects(w, rs, centre, Rv, Uv, Nv, px, W, H, mat, color, thick, lift=0.0):
    """Draw cell rectangles of a W x H pixel grid centred at `centre` on the plane (Rv right, Uv up)."""
    X, Y, Z = plane_basis(Rv, Uv, Nv)
    Rv, Uv, Nv = np.array(Rv, float), np.array(Uv, float), np.array(Nv, float)
    for (x, y, rw, rh) in rs:
        cx = (x + rw / 2 - W / 2) * px
        cy = (H / 2 - (y + rh / 2)) * px
        o = centre + Rv * cx + Uv * cy + Nv * lift
        w.box(o, X, Y, Z, rw * px, rh * px, thick, mat, color)


def icon(w, name, centre, Rv, Uv, Nv, px, color=BLACK, mat=INK, thick=0.012, lift=0.0, second=None):
    bm = ICONS[name]
    H, W = len(bm), max(len(r) for r in bm)
    draw_rects(w, rects(bm), centre, Rv, Uv, Nv, px, W, H, mat, color, thick, lift)
    if second:                                           # cells marked "2" in another colour (the hat band)
        draw_rects(w, rects(bm, "2"), centre, Rv, Uv, Nv, px, W, H, second[0], second[1], thick, lift)


def write(w, s, centre, Rv, Uv, Nv, px, color=BLACK, mat=INK, thick=0.012, align="center", lift=0.0, leading=8):
    """Pixel text on a plane: lines centred (or left-aligned with `centre` as the left middle); `leading` is the
    line pitch in pixels (glyphs are 7 tall)."""
    Rv, Uv, Nv = np.array(Rv, float), np.array(Uv, float), np.array(Nv, float)
    X, Y, Z = plane_basis(Rv, Uv, Nv)
    lines = s.upper().split("\n")
    total_h = len(lines) * leading - (leading - 7)
    for li, line in enumerate(lines):
        width = len(line) * 6 - 1
        x0 = -width / 2 if align == "center" else 0.0
        ytop = total_h / 2 - li * leading
        for ci, ch in enumerate(line):
            for (x, y, rw, rh) in GLYPH_RECTS.get(ch, GLYPH_RECTS[" "]):
                cx = x0 + ci * 6 + x + rw / 2
                cy = ytop - (y + rh / 2)
                o = centre + Rv * (cx * px) + Uv * (cy * px) + Nv * lift
                w.box(o, X, Y, Z, rw * px, rh * px, thick, mat, color)


def text_width(s, px):
    return max(len(l) for l in s.split("\n")) * 6 * px


def wrap(s, n):
    out, line = [], ""
    for word in s.split():
        if line and len(line) + 1 + len(word) > n:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        out.append(line)
    return out


SYMBOLS = {"dancer": "\U0001F483", "masks": "\U0001F3AD", "lingerie": "\U0001F459", "kiss": "\U0001F48F",
           "tophat": "\U0001F3A9", "lips": "\U0001F48B", "cocktail": "\U0001F378", "heart": "\u2764"}
_GLYPHS = {}


def glyph_bitmap(name, res=56):
    """A silhouette (Segoe UI Symbol) as a bitmap of '1' and '.' rows, cropped to its ink. Read from the
    pre-baked glyphs.json when it has them (the website's Python has no Windows fonts)."""
    if not _GLYPHS:
        try:
            with open(os.path.join(HERE, "glyphs.json"), encoding="utf-8") as f:
                baked = json.load(f)
            _GLYPHS.update({(k, baked["res"]): v for k, v in baked["glyphs"].items()})
        except OSError:
            pass
    if (name, res) not in _GLYPHS:
        from PIL import Image, ImageDraw, ImageFont
        f = ImageFont.truetype(r"C:\Windows\Fonts\seguisym.ttf", res)
        im = Image.new("L", (res * 2, res * 2), 255)
        ImageDraw.Draw(im).text((res // 4, 0), SYMBOLS[name], font=f, fill=0)
        im = im.crop(Image.eval(im, lambda v: 255 - v).getbbox())
        _GLYPHS[(name, res)] = ["".join("1" if im.getpixel((x, y)) < 128 else "." for x in range(im.width))
                                for y in range(im.height)]
    return _GLYPHS[(name, res)]


def glyph(w, name, centre, Rv, Uv, Nv, size, color, mat=GLOW, thick=0.012, lift=0.012):
    """Draw a silhouette `size` m tall (or wide, whichever is larger) centred on the plane."""
    bm = glyph_bitmap(name)
    H, W = len(bm), len(bm[0])
    draw_rects(w, rects(bm), centre, Rv, Uv, Nv, size / max(H, W), W, H, mat, color, thick, lift)


# ------------------------------------------------------------------ flat helpers on the board
def flat(heading):
    """Text basis lying on the board for a reader facing `heading`: right, away-from-reader, up."""
    return right_of(heading), fwd(heading), UP.copy()


def at(x, z, y=TOP):
    return np.array([x, y, z], float)


def slab(w, centre, heading, along_r, along_f, mat, color, thick=0.01, y=TOP):
    """Flat rectangle on the board: `along_r` across the reader, `along_f` away from them."""
    X, Y, Z = basis_upright(heading)
    w.box(np.array([centre[0], y, centre[2]]), X, Y, Z, along_r, along_f, thick, mat, color)


def seg(w, A, B, width=0.07, color=BLACK, y=TOP + 0.002):
    A, B = np.array(A, float), np.array(B, float)
    d = B - A
    h = math.degrees(math.atan2(d[0], d[2]))
    slab(w, (A + B) / 2, h, width, float(np.linalg.norm(d)) + width, INK, color, 0.012, y)


def outline(w, centre, heading, size, width=0.07, color=BLACK):
    R, F = right_of(heading), fwd(heading)
    c = np.array(centre, float)
    pts = [c + (R * sx + F * sz) * size / 2 for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    for i in range(4):
        seg(w, pts[i], pts[(i + 1) % 4], width, color)


def disc(w, centre, d, color, mat=GLOW, y=TOP, h=0.01):
    w.vcyl(centre[0], y, centre[2], d, h, mat, color)


# ------------------------------------------------------------------ the board
def square_frame(k):
    """Side k (0 bottom/GO side .. 3): reader heading, inward F, reader-right R, centre of the side's row."""
    h = [0.0, 90.0, 180.0, 270.0][k]
    F, R = fwd(h), right_of(h)
    return h, F, R


def square_centre(pos):
    k, i = divmod(pos, 10)
    h, F, R = square_frame(k)
    if i == 0:                                            # corner: GO, clinic, safe space, go to clinic
        c = -F * (HALF - U) + R * (HALF - U)
        return c, h
    s = (i - 1) * U - 4 * U                               # -8 .. 8 along the side, moving from the corner
    c = -F * (HALF - U) - R * s
    return c, h


def step_badge(w, centre, heading, n):
    """The square's step number (count your /roll by these): white on a black badge at the outer edge."""
    R, F, N = flat(heading)
    slab(w, centre, heading, 0.95, 0.5, INK, BLACK, 0.012, TOP + 0.002)
    write(w, str(n), centre, R, F, N, 0.05, WHITE, GLOW, lift=0.016)


def colour_tile(w, c, h, col, big, small, sym=None, big_px=0.05, small_px=0.022):
    """A square-filling colour tile: a word, a white silhouette and a short line."""
    R, F, N = flat(h)
    slab(w, c + F * 0.15, h, U - 0.18, 2 * U - 0.9, GLOW, col)
    write(w, big, c + F * (1.2 if "\n" not in big else 1.12), R, F, N, big_px, WHITE, GLOW, lift=0.012, leading=9)
    if sym:
        glyph(w, sym, c + F * 0.05, R, F, N, 1.35, WHITE)
    if small:
        write(w, "\n".join(wrap(small, 12)), c - F * 1.05, R, F, N, small_px, WHITE, GLOW, lift=0.012, leading=10)


def tile(w, pos, kind, q, cfg, group):
    c, h = square_centre(pos)
    R, F, N = flat(h)
    c = np.array([c[0], TOP, c[2]])
    lift = 0.01
    if kind == "q":
        name, col = group
        bar = c + F * (U - 0.38)
        slab(w, bar, h, U, 0.76, GLOW, tuple(col))
        write(w, name, bar, R, F, N, 0.027, lift=lift)
        write(w, f"Q{q}", c + F * 0.15, R, F, N, 0.09, KIND_COL["q"], GLOW, lift=lift)
        write(w, "TRUTH\nOR DARE", c - F * 0.85, R, F, N, 0.035, (0.25, 0.25, 0.3), GLOW, lift=lift, leading=10)
    elif kind == "story":
        disc(w, c + F * 0.45, 1.55, RED)
        tail = c - F * 0.25 - R * 0.45
        slab(w, tail, h + 35, 0.32, 0.55, GLOW, RED)
        write(w, "STORY\nTIME", c + F * 0.45, R, F, N, 0.042, WHITE, GLOW, lift=lift + 0.002)
    elif kind == "strip":
        colour_tile(w, c, h, KIND_COL["strip"], "STRIP", "LOSE ONE ITEM", "lingerie")
    elif kind == "dance":
        colour_tile(w, c, h, KIND_COL["dance"], "DANCE", "NAKED TILL YOUR NEXT TURN", "dancer")
    elif kind == "roll":
        colour_tile(w, c, h, KIND_COL["role"], "ROLE\nPLAY", "PICK A PARTNER", "masks", big_px=0.045)
    elif kind == "poses":
        colour_tile(w, c, h, KIND_COL["pose"], "POSE", "SPIN THE WHEEL", "kiss")


def corner(w, pos, kind, cfg):
    c, h = square_centre(pos)
    c = np.array([c[0], TOP, c[2]])
    d = (h - 45.0) % 360                                 # diagonal reader: outside the corner, facing the middle
    R, F, N = flat(d)
    lift = 0.01
    if kind == "go":
        write(w, "GO", c + F * 0.3, R, F, N, 0.18, lift=lift)
        # the red arrow lies under GO, parallel to it, pointing to the reader's left - the way players move
        tip = c - F * 1.0 - R * 0.85
        slab(w, tip + R * 0.75, (d + 90) % 360, 0.18, 1.3, GLOW, RED, 0.012, TOP + 0.01)             # shaft
        for sg_ in (-1, 1):                                                                          # head
            slab(w, tip + R * 0.21 + F * sg_ * 0.18, (d + 90 - sg_ * 40) % 360, 0.18, 0.62, GLOW, RED, 0.012,
                 TOP + 0.011)
    elif kind == "clinic":
        hs, Fs, Rs = square_frame(pos // 10)
        # "PASSING THRU" along the two outer strips, the clinic box in the inner corner
        box_c = c + (Fs - Rs) * 0.55
        slab(w, box_c, h, 2.6, 2.6, GLOW, (0.97, 0.98, 0.97))
        outline(w, box_c, h, 2.6)
        Rb, Fb, Nb = flat(h)
        cross = box_c + Fb * 0.25
        for (a, b) in ((1.3, 0.45), (0.45, 1.3)):
            slab(w, cross, h, a, b, GLOW, (0.2, 0.75, 0.2), 0.012, TOP + 0.004)
        write(w, "CLINIC", cross, Rb, Fb, Nb, 0.03, WHITE, GLOW, lift=lift + 0.006)
        write(w, "SIT OUT A TURN\nAT THE BAR", box_c - Fb * 0.85, Rb, Fb, Nb, 0.025, lift=lift, leading=10)
        write(w, "PASSING", c - Fs * 1.55 + Rs * 0.3, *flat(h), 0.07, lift=lift)    # outer strip of this side
        h0 = (h - 90) % 360                              # ...and of the GO side
        write(w, "THRU", c - fwd(h0) * 1.55 - right_of(h0) * 0.3, *flat(h0), 0.07, lift=lift)
    elif kind == "safe":
        write(w, "SAFE\nSPACE", c + F * 0.85, R, F, N, 0.08, lift=lift)
    elif kind == "gotoclinic":
        write(w, "GO TO\nCLINIC", c + F * 0.6, R, F, N, 0.08, lift=lift)
        for (a, b) in ((1.0, 0.34), (0.34, 1.0)):
            slab(w, c - F * 0.8, d, a, b, GLOW, (0.2, 0.75, 0.2), 0.012, TOP + 0.004)


def board(w, cfg):
    # slab, then the grid of black lines
    w.ubox(0, 0, 0, 2 * HALF + 0.4, 2 * HALF + 0.4, TOP - 0.01, "metal_10", (0.1, 0.1, 0.1))
    w.ubox(0, TOP - 0.01, 0, 2 * HALF, 2 * HALF, 0.01, GLOW, MINT)
    for k in range(4):
        h, F, R = square_frame(k)
        a = -F * HALF
        seg(w, a + R * HALF, a - R * HALF, 0.1)                       # outer edge
        b = -F * INNER
        seg(w, b + R * INNER, b - R * INNER, 0.08)                    # inner edge
        for i in range(10):                                           # separators between squares
            s = -INNER + i * U
            seg(w, -F * HALF - R * s, -F * INNER - R * s, 0.06)
    # squares
    groups = []
    for (name, col), n in zip(cfg["groups"], GROUP_SIZES):
        groups += [(name, col)] * n
    q = 0
    for pos, kind in enumerate(LAYOUT):
        if kind in ("go", "clinic", "safe", "gotoclinic"):
            corner(w, pos, kind, cfg)
        else:
            gr = None
            if kind == "q":
                gr = groups[q]
                q += 1
            tile(w, pos, kind, q, cfg, gr)


# what stands on each kind of square: the visible piece, plus the game's pose zone laid over it (always at scale 1,
# same place and turn, the way the game's own worlds do it). The cross bench has its poses built in.
FURNITURE = {
    "BED": [("bed_3", 0.0), ("bed_ph", 0.0)],
    "COUCH": [("sofa_6", 0.0), ("sofa_ph", 0.0)],
    "BENCH": [("cross_stool_poses", 0.0), ("chair_ph", -90.0)],
}


def furniture(w, kind, pos, yaw):
    for name, dyaw in FURNITURE[kind]:
        w.prop(name, np.array([pos[0], TOP + 0.013, pos[2]]), yaw + dyaw)


def centre_art(w, cfg):
    h = 315.0                                           # read from the GO corner, like the original
    R, F, N = flat(h)
    T, S = fwd(h), right_of(h)                          # towards the far corner / reader's right
    o = np.array([0.0, TOP, 0.0])
    # SLUTOPOLY banner
    b = o + T * 1.9
    tw = text_width(cfg["title"], 0.16)
    slab(w, b, h, tw + 1.0, 2.2, GLOW, WHITE, 0.012)
    slab(w, b, h, tw + 0.6, 1.8, GLOW, RED, 0.012, TOP + 0.004)
    write(w, cfg["title"], b, R, F, N, 0.16, WHITE, GLOW, lift=0.018)
    # the top hat over the banner, two big dice either side
    glyph(w, "tophat", o + T * 4.3, R, F, N, 1.9, BLACK, INK)
    w.prop("Dice1", o + T * 4.3 - S * 2.4 + UP * 0.55, 20, 0.7)
    w.prop("Dice2", o + T * 4.5 + S * 2.4 + UP * 0.55, 65, 0.7)
    # BED / COUCH / BENCH squares, each with its furniture and poses
    places = [("BED", o + T * 7.6, h, 3.6), ("COUCH", o + T * 4.5 - S * 5.2, h + 90, 2.8),
              ("BENCH", o + T * 4.5 + S * 5.2, h + 180, 2.8)]
    for label, c, yaw, size in places:
        slab(w, c, h, size, size, GLOW, (0.97, 0.98, 0.97))
        outline(w, c, h, size, 0.06)
        write(w, label, c - T * (size / 2 - 0.25), R, F, N, 0.05, lift=0.012)
        furniture(w, label, c + T * 0.15, yaw)
        w.prop("LightP", c + UP * 3.2, 0, 1.2, color=(1, 0.85, 0.65))
    # the pose wheel: six red circles round a POSES square holding the six pieces, each next to its circle
    wc = o - T * 5.0
    half = 3.6                                          # a round pad, so all six circles stay clear of it
    disc(w, wc, 2 * half + 0.14, BLACK, INK, h=0.011)
    disc(w, wc, 2 * half, (0.97, 0.98, 0.97), GLOW, y=TOP + 0.001, h=0.011)
    write(w, "POSES", wc, R, F, N, 0.06, lift=0.013)
    w.prop("LightP", wc + UP * 3.4, 0, 1.4, color=(1, 0.85, 0.65))
    for k, label in enumerate(cfg["poses"]):
        th = math.radians((k - 1) * 60)                  # circle 2 at the top, then clockwise
        dirv = T * math.cos(th) + S * math.sin(th)
        cc = wc + dirv * (half + 1.0)
        disc(w, cc, 1.9, RED)
        write(w, str(k + 1), cc + T * 0.5, R, F, N, 0.055, lift=0.012)
        write(w, label.replace(" ", "\n"), cc - T * 0.2, R, F, N, 0.027, lift=0.012)
        place = label.split()[0]
        if place in FURNITURE:
            radial = math.degrees(math.atan2(dirv[0], dirv[2]))
            furniture(w, place, wc + dirv * 2.3, radial)                # lengthwise towards its circle


# ------------------------------------------------------------------ panels
def panel(w, centre_bottom, heading, width, height):
    """A teal panel standing at centre_bottom, read by someone looking along `heading`. Returns its writing frame."""
    F, R = fwd(heading), right_of(heading)
    X, Y, Z = plane_basis(R, UP, F)
    face = np.array(centre_bottom, float)
    # wooden back frame, then the teal face (box spans from the face plane away from the reader)
    w.box(face + UP * (height / 2) + F * 0.12, X, Y, Z, width + 0.5, height + 0.5, 0.3, "WoodWalnutX", (0.35, 0.22, 0.14))
    w.box(face + UP * (height / 2), X, Y, Z, width, height, 0.12, GLOW, TEAL)
    for sx in (-1, 1):                                  # legs
        leg = face + R * sx * (width / 2 - 0.6) + F * 0.3
        w.vcyl(leg[0], -0.6, leg[2], 0.3, face[1] + 0.6, "WoodWalnutX", (0.3, 0.2, 0.12))
    return face, R, UP.copy(), -F


def title_line(w, s, c, R, Uv, N, px):
    write(w, s, c, R, Uv, N, px, WHITE, GLOW, thick=0.01)
    wd = text_width(s, px)
    X, Y, Z = plane_basis(R, Uv, N)
    w.box(c - Uv * (px * 6.5), X, Y, Z, wd + 0.4, px * 0.8, 0.01, GLOW, (0.92, 0.85, 0.6))


def rules_layout(cfg, width, px):
    """Line layout of the rules for a text size; returns (intro lines, blocks, total height)."""
    chars = int((width - 0.5 - 1.55 - 0.3) / (6 * px))
    intro = [l for s in cfg["rules_intro"] for l in wrap(s, int((width - 0.8) / (6 * px)))]
    blocks = [(ic, wrap(s, chars)) for ic, s in cfg["rules"]]
    hgt = 2.1 + len(intro) * px * 9 + 0.35 + sum(max(len(ls) * px * 9, 0.9) + 0.4 for _, ls in blocks)
    return intro, blocks, hgt


def rules_panel(w, cfg, face, R, Uv, N, width, height):
    px = 0.05
    while px > 0.03:                                    # the biggest text that fits the panel
        intro, blocks, hgt = rules_layout(cfg, width, px)
        if hgt < height - 0.4:
            break
        px -= 0.002
    top = face + Uv * (height - 0.9)
    title_line(w, cfg["rules_title"], top, R, Uv, N, 0.1)
    y = height - 2.1
    for line in intro:
        write(w, line, face + Uv * y, R, Uv, N, px, WHITE, GLOW, thick=0.01)
        y -= px * 9
    y -= 0.35
    left = -width / 2 + 0.5
    for ic, lines in blocks:
        block = max(len(lines) * px * 9, 0.9)
        mid = y - block / 2 + px * 4
        ic_c = face + R * (left + 0.6) + Uv * mid
        X, Y, Z = plane_basis(R, Uv, N)
        w.box(ic_c, X, Y, Z, 1.1, 0.55, 0.012, GLOW, KIND_COL[ic])
        write(w, KIND_TAG[ic], ic_c, R, Uv, N, 0.033, WHITE, GLOW, thick=0.01, lift=0.014)
        yy = y - (block - len(lines) * px * 9) / 2
        for line in lines:
            write(w, line, face + R * (left + 1.55) + Uv * yy, R, Uv, N, px, WHITE, GLOW, thick=0.01, align="left")
            yy -= px * 9
        y -= block + 0.4


def list_panel(w, face, R, Uv, N, width, height, sections, px):
    y = height - 0.9
    for title, items, numbered in sections:
        title_line(w, title, face + Uv * y, R, Uv, N, 0.09)
        y -= 1.05
        left = -width / 2 + 0.45
        for i, s in enumerate(items, start=1):
            line = f"{i:>2} {s}" if numbered else s
            write(w, line, face + R * left + Uv * y, R, Uv, N, px, WHITE, GLOW, thick=0.01, align="left")
            y -= px * 9.5
        y -= 0.6


# ------------------------------------------------------------------ the room and props
def tent_sign(w, c, heading, label, color=(0.6, 0.08, 0.08)):
    """A folded card sign like the original's GAME MASTER / GUESTS cards, read looking along `heading`."""
    F, R = fwd(heading), right_of(heading)
    c = np.asarray(c, float)
    apex = c + UP * 1.15
    for front in (True, False):
        foot = c - F * 0.42 if front else c + F * 0.42
        up = norm_vec(apex - foot)
        n = norm_vec(np.cross(up, R)) if front else norm_vec(np.cross(R, up))   # outward normal of this face
        X, Y, Z = plane_basis(R, up, n)
        mid = (foot + apex) / 2
        w.box(mid - n * 0.03, X, Y, Z, 2.6, float(np.linalg.norm(apex - foot)), 0.03, "paint_1", (0.97, 0.95, 0.9))
        if front:
            write(w, label, mid, R, up, n, 0.05, color, "paint_1", thick=0.01)


def norm_vec(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


WIN = 11.0                 # half-width of the opening between the game room and the lobby
LY = 4.0                   # lobby floor height: it overlooks the board


def room(w):
    S = 34.0
    w.ubox(0, -0.3, 0, 2 * S, 2 * S, 0.3, "concrete_6", (0.06, 0.05, 0.04))
    # the striped olive carpet around the board
    for i in range(-44, 45):
        x = i * 0.55
        w.ubox(x, 0.0, 0, 0.14, 48, 0.006, "FabricBrocades2", (0.45, 0.42, 0.12))
    for sx, sz, ww, dd in ((0, S, 2 * S, 0.5), (0, -S, 2 * S, 0.5), (-S, 0, 0.5, 2 * S)):
        w.ubox(sx, 0, sz, ww, dd, 22, "concrete_6", (0.03, 0.03, 0.035))
    # east wall: the lobby looks down onto the board through a wide opening
    for z0, z1 in ((-S, -WIN), (WIN, S)):
        w.ubox(S, 0, (z0 + z1) / 2, 0.5, z1 - z0, 22, "concrete_6", (0.03, 0.03, 0.035))
    w.ubox(S, 0, 0, 0.5, 2 * WIN, LY, "concrete_6", (0.03, 0.03, 0.035))
    w.ubox(S, LY + 5.0, 0, 0.5, 2 * WIN, 22 - LY - 5.0, "concrete_6", (0.03, 0.03, 0.035))
    w.ubox(0, 22, 0, 2 * S, 2 * S, 0.4, "concrete_6", (0.02, 0.02, 0.025))
    w.prop("Light90", (0, 8.0, 0), 0, 2.0, color=(1, 0.95, 0.85))
    for p in ((-19, 4.5, -15.5), (19.5, 4.0, 4.0)):
        w.prop("LightP", p, 0, 1.2, color=(1, 0.85, 0.65))


def game_master(w):
    c = np.array([-19.0, 0.0, -15.5])
    w.ubox(c[0], 0, c[2], 4.4, 4.4, 0.35, GLOW, (0.92, 0.92, 0.9))
    w.ubox(c[0], 0.35, c[2], 3.2, 3.2, 0.02, GLOW, (0.12, 0.5, 0.2))
    glyph(w, "cocktail", c + UP * 0.38, *flat(45), 2.4, (0.2, 0.75, 0.35))                     # emblem on the base
    w.vcyl(c[0], 0.37, c[2], 2.0, 0.15, "glass_1", (0.8, 1, 0.85))                              # foot
    w.vcyl(c[0], 0.5, c[2], 0.35, 1.2, "glass_1", (0.8, 1, 0.85))                               # stem
    rim, depth, dia = 3.4, 1.75, 4.4
    top = c + UP * rim
    for k in range(20):                                                   # the bowl: a hollow shell of glass panels
        th = math.radians(k * 18)
        out = np.array([math.sin(th), 0.0, math.cos(th)])
        w.beam(top + out * (dia / 2), top - UP * depth + out * 0.12, 2 * math.pi * (dia / 2) / 20 * 1.08, 0.05,
               "glass_1", (0.85, 1, 0.9))
    lv = 0.25                                                                                    # liquid just under the rim
    ld = dia * (1 - lv / depth) - 0.08
    w.hang("Cone", top - UP * lv, ld, ld, depth - lv - 0.04, "glass_2", (0.2, 0.85, 0.45))       # the liquid
    w.vcyl(c[0], rim - lv - 0.02, c[2], ld, 0.03, "water", (0.25, 0.95, 0.55))                   # its surface
    w.prop("LightP", top - UP * 0.9, 0, 1.2, color=(0.3, 1, 0.5))                              # lit from inside
    pick = top + fwd(60) * 1.5
    w.cyl(pick + UP * 0.6, pick - UP * 0.5 - fwd(60) * 0.4, 0.04, "WoodTeakX", (0.8, 0.6, 0.4))
    w.ell(pick - UP * 0.2 - fwd(60) * 0.12, 0.42, 0.42, 0.42, GLOW, (0.45, 0.75, 0.2))          # olive on a pick
    a = math.degrees(math.atan2(-c[0], -c[2])) % 360      # the Game Master's spot: on the rim facing the board,
    w.prop("pool_ph", top - UP * (lv + 0.35) + fwd(a) * (dia / 2 - 0.45), (a - 90) % 360)   # arms over the rim
    two_way(w, c + fwd(0) * 3.3, 180, "SIT IN\nTHE GLASS", top - UP * lv + fwd(a + 180) * 0.9, (a + 180) % 360, "BACK\nDOWN",
            (0.3, 1.0, 0.5))                                                          # into the glass and out
    tent_sign(w, c + fwd(45) * 3.6, 225, "GAME\nMASTER")
    w.prop("Dice1", c + fwd(100) * 3.2 + UP * 0.5, 20, 0.6)
    w.prop("Dice2", c + fwd(130) * 3.4 + UP * 0.5, 65, 0.6)


def guests(w):
    c = np.array([19.5, 0.0, 4.0])
    w.vcyl(c[0], 0, c[2], 7.0, 0.45, "Marble", (0.95, 0.93, 0.9))              # ashtray base
    w.cyl(c + UP * 0.45, c + UP * 1.45, 7.0, "Marble", (0.95, 0.93, 0.9), name="Tube")   # rim
    w.vcyl(c[0], 0.45, c[2], 6.2, 0.06, "concrete_6", (0.35, 0.33, 0.3))      # ash
    out = fwd(150)                                                           # the cigar rests in a notch on the rim
    butt = c + out * 5.0 + UP * 1.62
    lit = c + out * 1.4 + UP * 1.5
    d = (lit - butt) / np.linalg.norm(lit - butt)
    w.cyl(butt, lit, 0.5, "Leather_Italian", (0.36, 0.2, 0.1))                 # the cigar
    w.cyl(butt + d * 0.35, butt + d * 0.75, 0.53, "gold", (1, 0.8, 0.3))       # its band
    w.cyl(lit, lit + d * 0.45, 0.48, "concrete_6", (0.6, 0.58, 0.55))         # ash
    w.cyl(lit + d * 0.45, lit + d * 0.5, 0.42, "Illum FLAT", (1, 0.35, 0.05))  # ember
    w.prop("Smoke", lit + d * 0.5 + UP * 0.3, 0, 2.0)
    for k in range(6):                                                       # seats on the rim
        a_ = 200 + k * 32
        w.prop("Sofa1", c + fwd(a_) * 3.25 + UP * 1.5, a_)
    tent_sign(w, c + np.array([-4.5, 0, -6.0]), 90, "GUESTS")


def safe_space(w):
    c, h = square_centre(20)
    tc = np.array([c[0], TOP, c[2]]) - fwd(h - 45) * 0.55
    perp = right_of(h - 45)
    for k, col in zip((-1, 0, 1), ((0.55, 0.12, 0.6), (0.95, 0.95, 0.95), (0.55, 0.12, 0.6))):
        p = tc + perp * k * 1.25 + UP * 0.35
        w.ell(p, 1.2, 0.7, 1.2, "Fabric1", col)
        w.prop("Sofa1", p + UP * 0.2, h - 45 + 180)                         # a seat on each beanbag


def portal_label(w, at, yaw, label, col):
    """A two-sided sign floating over a portal."""
    lines = label.upper().split("\n")
    Wd = max(len(l) for l in lines) * 6 * 0.05 + 0.3
    Hd = (len(lines) * 8 - 1) * 0.05 + 0.3
    mid = np.asarray(at, float) + UP * 2.55
    F0 = fwd(yaw)
    X, Y, Z = plane_basis(right_of(yaw), UP, F0)
    w.box(mid - F0 * 0.03, X, Y, Z, Wd, Hd, 0.06, "unlit", (0.06, 0.06, 0.08))
    for h in (yaw, yaw + 180):
        F, R = fwd(h), right_of(h)
        write(w, label, mid - F * 0.035, R, UP, -F, 0.05, col, "Illum FLAT", thick=0.012)


def two_way(w, a, ay, alabel, b, by, blabel, col):
    """One portal pair = one two-way link: a pad at each end (in file order), each with a glow and a sign
    saying where it goes."""
    for p, yaw, label in ((a, ay, alabel), (b, by, blabel)):
        w.prop("portal", np.asarray(p, float) + UP * 0.02, yaw, (1, 1, 0.5), "discard")   # only the hexagon shows
        w.portal_glow(p, yaw, col)
        portal_label(w, p, yaw, label, col)


def teleporters(w):
    """The game room and the lobby, joined by one two-way portal."""
    two_way(w, np.array([27.0, 0.0, -25.0]), 315, "LOBBY & BAR", np.array([50.0, LY, -11.0]), 270, "BACK TO\nTHE GAME",
            (1.0, 0.35, 0.7))


def leather_sofa(w, c, facing, length=2.3):
    """A brown leather three-seater facing `facing`, with the game's sofa poses laid over it."""
    F, R = fwd(facing), right_of(facing)
    c = np.asarray(c, float)
    brown, dark = (0.36, 0.2, 0.12), (0.26, 0.14, 0.08)
    w.ubox(c[0], c[1], c[2], length, 0.95, 0.42, "Leather_Italian", dark, yaw=facing)                 # base
    for k in (-1, 0, 1):                                                                             # seat cushions
        p = c + R * k * (length - 0.5) / 3 + F * 0.05
        w.ubox(p[0], c[1] + 0.42, p[2], (length - 0.5) / 3 - 0.03, 0.8, 0.14, "Leather_Italian", brown, yaw=facing)
    b = c - F * 0.38
    w.ubox(b[0], c[1] + 0.42, b[2], length - 0.1, 0.24, 0.55, "Leather_Italian", brown, yaw=facing)    # back
    for sg in (-1, 1):                                                                               # arms
        a = c + R * sg * (length / 2 - 0.12)
        w.ubox(a[0], c[1] + 0.42, a[2], 0.26, 0.95, 0.22, "Leather_Italian", brown, yaw=facing)
    w.prop("sofa_ph", c, (facing + 90) % 360)                                                        # its poses (they face the pose model's left)


def lobby(w):
    """Upstairs, overlooking the board: plank walls, a warm lit feature wall with the welcome and the neon sign,
    leather sofas round a coffee table, high tables with stools, and the bar."""
    X0, X1, Z0, Z1, H = 34.25, 52.0, -13.0, 13.0, 5.5
    wood, dark = (0.32, 0.22, 0.16), (0.18, 0.12, 0.09)
    w.ubox((X0 + X1) / 2, LY - 0.3, 0, X1 - X0 + 0.5, Z1 - Z0 + 0.5, 0.3, "WoodMosaic2", (0.45, 0.3, 0.2))   # parquet
    w.ubox((X0 + X1) / 2, LY + H, 0, X1 - X0 + 0.5, Z1 - Z0 + 0.5, 0.3, "WoodPlaknsOldX", dark)              # ceiling
    for z in (Z0 - 0.25, Z1 + 0.25):                                                                         # side walls
        w.ubox((X0 + X1) / 2, LY, z, X1 - X0 + 0.5, 0.5, H, "WoodPlaknsOldX", wood)
    w.ubox(X1 + 0.25, LY, 0, 0.5, Z1 - Z0 + 1.0, H, "PlasterTerracotta", (0.85, 0.5, 0.28))                  # feature wall
    w.ubox(X0 + 0.45, LY, 0, 0.4, 2 * WIN, 1.0, "WoodPlaknsOldX", wood)                                       # parapet
    w.ubox(X0 + 0.45, LY + 1.0, 0, 0.55, 2 * WIN, 0.08, "WoodWalnutX", dark)                                  # its rail
    for z in (-10.0, -4.0, 2.0, 8.0):                                                                        # wall washers
        w.prop("LightP", (X1 - 0.8, LY + 4.6, z), 0, 1.6, color=(1.0, 0.55, 0.2))
    # the welcome, as on the original lobby wall
    R, Uv, N = right_of(90), UP, -fwd(90)
    face = np.array([X1 - 0.02, 0, 0])
    write(w, "WELCOME", face + UP * (LY + 4.45) + R * 3.0, R, Uv, N, 0.13, WHITE, GLOW, thick=0.012)
    rules = ("PLEASE DON'T INTERRUPT AN ACTIVE GAME\nFOLLOW THE GAME MASTER'S INSTRUCTIONS\nPLEASE READ THE RULES\n"
             "(6) PLAYERS MAX - BE WILLING TO FINISH")
    write(w, rules, face + UP * (LY + 2.75) + R * 3.0, R, Uv, N, 0.045, WHITE, GLOW, thick=0.012, leading=11)
    write(w, "SLUTOPOLY  -  BY KINGCOLOSSUS", face + UP * (LY + 1.45) + R * 3.0, R, Uv, N, 0.03, (1, 0.75, 0.5),
          GLOW, thick=0.012)
    # the neon sign: SLUTOPOLY on red, LOBBY in cyan, the top hat and lips over it
    sc = face + UP * (LY + 2.9) - R * 6.5
    X, Y, Z = plane_basis(R, Uv, N)
    w.box(sc - N * 0.06, X, Y, Z, 4.8, 1.2, 0.04, GLOW, (0.05, 0.05, 0.06))                 # backing
    w.box(sc - N * 0.02, X, Y, Z, 4.6, 1.0, 0.02, GLOW, (0.85, 0.1, 0.12))                  # red panel
    write(w, "SLUTOPOLY", sc, R, Uv, N, 0.085, WHITE, "Illum FLAT", thick=0.015)
    write(w, "LOBBY", sc - UP * 0.95 + R * 1.2, R, Uv, N, 0.07, (0.3, 0.95, 1.0), "Illum FLAT", thick=0.015)
    glyph(w, "tophat", sc + UP * 1.35 - R * 0.8, R, Uv, N, 1.1, (0.3, 0.95, 1.0), "Illum FLAT")
    glyph(w, "lips", sc + UP * 1.3 + R * 0.9, R, Uv, N, 1.0, (1.0, 0.3, 0.55), "Illum FLAT")
    # lounge: leather sofas facing each other over a coffee table with wine and snacks
    t = np.array([43.0, LY, 1.5])
    leather_sofa(w, t + np.array([0, 0, -1.9]), 0)
    leather_sofa(w, t + np.array([0, 0, 1.9]), 180)
    leather_sofa(w, t + np.array([3.0, 0, 0]), 270)
    w.prop("coffee_table_1", t, 0)
    w.prop("drinkWine1", t + np.array([0.3, 0.46, 0.1]), 0, 1.3)
    for dx in (-0.25, 0.1):
        w.prop("drinkGlassWineRed", t + np.array([dx, 0.46, -0.2]), 0, 1.3)
    w.prop("Dish1", t + np.array([-0.35, 0.46, 0.15]), 0, (0.35, 0.35, 0.3))
    for k in range(5):
        w.prop("foodFrenchfries", t + np.array([-0.35 + 0.05 * (k - 2), 0.49, 0.15]), k * 40, 1.0)
    # high tables with stools along the parapet, a candle on each
    for z in (-8.0, 8.0):
        p = np.array([36.4, LY, z])
        w.prop("bar_table", p, 0)
        for dz in (-0.5, 0.5):                       # face the board, turned a little to the table
            front = 270 + (20 if dz < 0 else -20)
            w.prop("bar_stool_2_poses", p + np.array([0.6, 0, dz]), (front + 90) % 360)
        w.prop("LightP", p + UP * 1.35, 0, 0.4, color=(1, 0.7, 0.4))
    # the bar along the north wall
    bz = 9.6
    w.ubox(47.0, LY, bz, 8.0, 1.0, 1.05, "WoodWalnutX", (0.4, 0.22, 0.13))
    w.ubox(47.0, LY + 1.05, bz, 8.4, 1.25, 0.08, "Marble", (0.2, 0.18, 0.18))
    w.ubox(47.0, LY + 0.05, bz - 0.52, 7.8, 0.06, 0.12, GLOW, (1.0, 0.55, 0.2))
    w.ubox(47.0, LY, Z1 - 0.3, 8.0, 0.6, 1.0, "WoodWalnutX", (0.3, 0.18, 0.1))
    w.ubox(47.0, LY + 1.0, Z1 - 0.05, 7.6, 0.1, 2.6, "mirror_1", (0.8, 0.75, 0.7))
    drinks = ["drinkWine1", "drinkWine2", "drinkWine3", "drinkWine4", "drinkBeer1", "drinkBeer2", "drinkBeer3", "drinkBeer4"]
    for lv, y in enumerate((1.0, 1.75, 2.5)):
        w.ubox(47.0, LY + y - 0.04, Z1 - 0.35, 7.6, 0.6, 0.04, "glass_1", (0.95, 0.9, 0.8))
        for k, x in enumerate(np.arange(43.4, 50.7, 0.55)):
            w.prop(drinks[(k + lv * 3) % len(drinks)], (x, LY + y, Z1 - 0.35), 0, 1.6)
    for x in (44.5, 47.0, 49.5):
        w.vcyl(x, LY + 1.13, bz + 0.3, 0.08, 0.45, "chrome", (0.9, 0.9, 0.95))
    for x in np.arange(43.6, 50.5, 1.15):
        w.prop("bar_stool_2_poses", (x, LY, bz - 1.1), 90)                    # facing the bar
    write(w, "BAR", np.array([47.0, LY + 4.3, Z1 - 0.02]), right_of(0), UP, -fwd(0), 0.12, (1.0, 0.55, 0.2),
          "Illum FLAT", thick=0.02)


def bedrooms(w):
    """Four curtained bedroom alcoves along the south wall, each with a bed and its poses."""
    wall_z = -33.75
    cols = [(0.6, 0.1, 0.3), (0.3, 0.1, 0.55), (0.6, 0.1, 0.3), (0.3, 0.1, 0.55)]
    centres = [-8.0, 0.0, 8.0, 16.0]
    for x in (-12.0, -4.0, 4.0, 12.0, 20.0):                                        # partitions
        w.ubox(x, 0, wall_z + 3.0, 0.25, 6.0, 3.4, "unlit", (0.15, 0.07, 0.12))
    for k, x in enumerate(centres):
        w.ubox(x, 3.4, wall_z + 3.0, 8.0, 6.0, 0.15, "unlit", (0.12, 0.05, 0.1))     # canopy
        w.ubox(x, 0.0, wall_z + 2.6, 5.0, 4.0, 0.012, "Fabric_Carpet", cols[k])     # rug
        for sx in (-1, 1):                                                         # curtains, drawn half open
            w.ubox(x + sx * 3.1, 0, wall_z + 6.0, 1.6, 0.06, 3.3, "Fabric1", cols[k])
            w.prop("light_1", (x + sx * 1.9, 0, wall_z + 1.0), 0)
        w.prop("bed_3", (x, 0, wall_z + 1.6), 0)
        w.prop("bed_ph", (x, 0, wall_z + 1.6), 0)
        w.prop("LightP", (x, 2.9, wall_z + 2.5), 0, 1.0, color=(1, 0.45, 0.7))
        write(w, str(k + 1), np.array([x, 3.62, wall_z + 6.08]), right_of(180), UP, -fwd(180), 0.07, (1, 0.5, 0.8),
              "Illum FLAT", thick=0.012)
    write(w, "BEDROOMS", np.array([4.0, 5.2, wall_z + 0.02]), right_of(180), UP, -fwd(180), 0.16, (1, 0.45, 0.75),
          "Illum FLAT", thick=0.02)


def quick_start(w):
    """A mat at the spawn: the whole game in four lines."""
    c = np.array([15.0, 0.0, -15.0])
    h = 315.0
    R, F, N = flat(h)
    slab(w, c, h, 4.6, 3.0, "unlit", (0.07, 0.06, 0.09), 0.012, 0.0)
    slab(w, c, h, 4.75, 3.15, "unlit", (0.95, 0.35, 0.6), 0.01, 0.0)
    write(w, "QUICK START", c + F * 1.05, R, F, N, 0.06, (1, 0.45, 0.7), "unlit", lift=0.014)
    lines = "1  /ROLL 6 AND MOVE" + chr(10) + "2  DO YOUR SQUARE" + chr(10) + "3  PASS = 1 STEP BACK" + chr(10) + "4  FIRST TO 3 LAPS WINS"
    write(w, lines, c - F * 0.25, R, F, N, 0.03, WHITE, "unlit", lift=0.014, leading=11)


def build(cfg):
    w = World(3)
    w.begin()
    room(w)
    w.begin()
    board(w, cfg)
    w.begin()
    centre_art(w, cfg)
    safe_space(w)
    # three panels behind the far (SAFE SPACE) corner, in a shallow arc facing the GO corner
    w.begin()
    PH = 15.0
    specs = [(-41.0, "rules", 12.0), (0.0, "questions", 13.0), (41.0, "roleplay", 11.5)]
    for off, kind, PW in specs:
        dirv = fwd(315 + off)
        heading = (315 + off) % 360
        base = dirv * 22.0 + UP * 1.2
        face, R, Uv, N = panel(w, base, heading, PW, PH)
        if kind == "rules":
            rules_panel(w, cfg, face, R, Uv, N, PW, PH)
        elif kind == "questions":
            list_panel(w, face, R, Uv, N, PW, PH, [(cfg["have_you_ever_title"], cfg["have_you_ever"], True),
                                                   (cfg["tell_title"], cfg["tell"], True)], 0.036)
        else:
            list_panel(w, face, R, Uv, N, PW, PH, [(cfg["roll_play_title"], cfg["roll_play"], False)], 0.05)
    w.begin()
    game_master(w)
    guests(w)
    w.begin()
    bedrooms(w)
    quick_start(w)
    w.begin()
    lobby(w)
    w.begin()
    teleporters(w)
    world = {
        "respawn": {"p": [17.5, 0.1, -17.5], "r": 315.0},
        "ambient": [1.0] * 11,
        "oceanlevel": -50.0,
        "weather": "Night",
        "valuetype": "float",
        "objects": w.groups,
    }
    return world, w


def main():
    if "--write-config" in sys.argv or not os.path.exists(CONFIG):
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(DEFAULT, f, indent=2)
        print("wrote", CONFIG)
    cfg = dict(DEFAULT)
    with open(CONFIG, encoding="utf-8") as f:
        cfg.update(json.load(f))
    assert len(cfg["have_you_ever"]) == 22, "the board has 22 'have you ever' squares"
    assert len(cfg["poses"]) == 6
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = args[0] if args else os.path.join(os.path.expanduser("~"), "Downloads", "Slutopoly-3DX.world")
    world, w = build(cfg)
    data = json.dumps(world, separators=(",", ":"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(data)
    print(f"Wrote {out}: {w.count:,} objects, {len(data) / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
