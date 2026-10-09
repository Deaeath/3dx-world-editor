"""Generate build/icon.ico (an isometric cube). Requires Pillow."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1] if len(sys.argv) > 1 else "build")
out.mkdir(parents=True, exist_ok=True)

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=(22, 24, 29, 255))
cx, cy, r = S // 2, S // 2 + 10, 300
top = [(cx, cy - r), (cx + r * 0.87, cy - r / 2), (cx, cy), (cx - r * 0.87, cy - r / 2)]
left = [(cx - r * 0.87, cy - r / 2), (cx, cy), (cx, cy + r), (cx - r * 0.87, cy + r / 2)]
right = [(cx, cy), (cx + r * 0.87, cy - r / 2), (cx + r * 0.87, cy + r / 2), (cx, cy + r)]
d.polygon(top, fill=(120, 205, 255, 255))
d.polygon(left, fill=(74, 179, 255, 255))
d.polygon(right, fill=(29, 78, 216, 255))

img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(f"icon written to {out}")
