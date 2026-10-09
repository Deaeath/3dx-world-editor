"""Locate the 3DXChat game folder and the editor's asset cache (stdlib only)."""
import glob
import os

ASSET_CACHE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "3DXWorldEditor", "assets")


def _candidates():
    home = os.path.expanduser("~")
    pats = [
        os.path.join(home, "Downloads", "3DXChatLauncher*", "3DXChat", "Game"),
        os.path.join(home, "Downloads", "3DXChatLauncher*", "*", "3DXChat", "Game"),
        os.path.join(home, "Desktop", "3DXChat*", "3DXChat", "Game"),
        r"C:\3DXChat\Game", r"C:\3DXChat\3DXChat\Game", r"D:\3DXChat\Game",
        r"C:\Program Files\3DXChat\Game", r"C:\Program Files (x86)\3DXChat\Game",
        os.path.join(home, "AppData", "Local", "3DXChat", "Game"),
    ]
    for p in pats:
        yield from sorted(glob.glob(p), key=os.path.getmtime, reverse=True)


def find_game():
    """Best guess at '...\\3DXChat\\Game' (the folder holding 3DXChat_Data), or ''."""
    for c in _candidates():
        if os.path.isfile(os.path.join(c, "3DXChat_Data", "resources.assets")):
            return c
    return ""
