# Changelog

## 1.1.0

- **Link game** on the website: pick your 3DXChat folder and the browser reads the real models and textures from it, locally. Nothing is uploaded.
- New camera controls, like a game: **W A S D** move and **Q / E** go down/up without holding anything, **right-drag** looks around from where you stand (wheel while right-dragging sets fly speed), **Alt + left-drag** orbits, middle-drag pans. Move / rotate / scale moved to **1 / 2 / 3**.
- Fixed: any click switched the move gizmo into a broken state.
- Camera controls hint in the 3D view; clicking the view gives it keyboard focus (needed inside the SBS window).
- Objects whose model can't be read now show as their basic shape (cylinder, arch...) where there is one, instead of a box.
- Desktop app: one-file `3DXWorldEditor.exe` that finds your game folder by itself; texture reading fixed in the exe.

## 1.0.0

- 3D editor for 3DXChat `.world` files: instanced rendering, selection (click, box, groups), move/rotate/scale gizmo with snapping, undo/redo, duplicate, copy/paste between worlds, group/ungroup, hide, inspector, object and material library, world settings, merge and export.
- Website version (GitHub Pages) with generated basic shapes, starting with the SNL Monopoly board.
- Desktop version: local server that reads and writes `.world` files (with `.bak` backups) and shows the real game models extracted from your own install.
