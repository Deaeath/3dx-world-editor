// 3DXChat World Editor - app wiring, selection, editing, UI.
import * as THREE from 'three';
import { World, Node, serializeNode, nodeFromJSON, matrixToUnity, unityToMatrix, tidy, stringifyWorld } from './world.js';
import { Assets } from './assets.js';
import { SceneView } from './scene.js';
import { api, setToken, hasServer } from './api.js';
import { Outliner } from './outliner.js';

const $ = s => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'html') e.innerHTML = v; else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k);
  return e;
};
const fmt = v => (Math.round(v * 10000) / 10000).toString();
const toast = (msg, kind = '') => {
  const t = el('div', { class: 'toast ' + kind }, msg);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), kind === 'error' ? 8000 : 3500);
};

setToken(document.querySelector('meta[name=editor-token]').content);
// 'local' = run by server.py on this PC (real files on disk, extracted game assets);
// 'web'   = static website (browser file pickers, generated shapes unless a game is linked)
const MODE = hasServer() ? 'local' : 'web';
document.body.dataset.mode = MODE;
const DEFAULT_WORLD = 'worlds/SNL-Monopoly-version.world';

// ======================================================================= state
const assets = new Assets();
const view = new SceneView($('#viewport canvas'), assets);
let world = null;
const sel = new Set();            // selected nodes (groups or leaves)
let selectMode = 'group';         // 'group' | 'object'
let clipboard = null;
const undoStack = [], redoStack = [];

// =================================================================== undo/redo
function snapshot(node) { return JSON.parse(JSON.stringify(node.obj)); }
function applyState(node, state) {
  const typeChanged = node.obj.n !== state.n || node.obj.m !== state.m;
  node.obj = JSON.parse(JSON.stringify(state));
  node.updateMatrix();
  if (typeChanged) view.rebuildLeaf(node); else view.updateLeaf(node);
}
function pushCmd(cmd) {
  undoStack.push(cmd); if (undoStack.length > 300) undoStack.shift();
  redoStack.length = 0;
  markDirty();
}
function undo() { const c = undoStack.pop(); if (!c) return; c.undo(); redoStack.push(c); afterEdit(); }
function redo() { const c = redoStack.pop(); if (!c) return; c.redo(); undoStack.push(c); afterEdit(); }

// change properties of leaves; mutate(node) edits node.obj in place
function editLeaves(leaves, mutate, label = 'edit') {
  const changes = [];
  for (const n of leaves) {
    const before = snapshot(n);
    mutate(n);
    const after = snapshot(n);
    if (JSON.stringify(before) !== JSON.stringify(after)) { changes.push({ n, before, after }); applyState(n, after); }
  }
  if (!changes.length) return;
  pushCmd({ label, undo: () => changes.forEach(c => applyState(c.n, c.before)), redo: () => changes.forEach(c => applyState(c.n, c.after)) });
  afterEdit();
}

// structural changes: insert / remove nodes
function insertNode(node, parent, index) {
  node.parent = parent;
  parent.children.splice(index, 0, node);
  view.addNode(node);
}
function detachNode(node) {
  const p = node.parent, i = p.children.indexOf(node);
  p.children.splice(i, 1);
  view.removeNode(node);
  return { p, i };
}

function markDirty() { if (world) { world.dirty = true; updateTitle(); } }
function afterEdit() { refreshSelection(); outliner.refresh(); }

// ================================================================== selection
function leavesOf(nodes) { const out = new Set(); for (const n of nodes) for (const l of n.leaves()) out.add(l); return [...out]; }
function selectedLeaves() { return leavesOf(sel); }

function setSelection(nodes, { add = false, toggle = false, reveal = false } = {}) {
  const prevLeaves = new Set(selectedLeaves());
  if (!add && !toggle) sel.clear();
  for (const n of nodes) {
    if (toggle && sel.has(n)) sel.delete(n); else sel.add(n);
  }
  // drop nodes whose ancestor is also selected
  for (const n of [...sel]) { let p = n.parent; while (p) { if (sel.has(p)) { sel.delete(n); break; } p = p.parent; } }
  const nowLeaves = new Set(selectedLeaves());
  for (const l of prevLeaves) if (!nowLeaves.has(l)) view.setSelected(l, false);
  for (const l of nowLeaves) if (!prevLeaves.has(l)) view.setSelected(l, true);
  if (reveal && sel.size === 1) outliner.reveal([...sel][0]);
  refreshSelection();
  outliner.refresh();
}

function refreshSelection() {
  const leaves = selectedLeaves();
  if (!leaves.length) { view.gizmo.detach(); view.showSelectionBox(null); inspector(); updateStatus(); return; }
  const box = view.boxOf(leaves);
  view.showSelectionBox(box);
  placePivot(leaves, box);
  inspector();
  updateStatus();
}

const pivot = new THREE.Object3D();
view.scene.add(pivot);
function placePivot(leaves, box) {
  if (gizmoDrag) return;
  if (leaves.length === 1 && view.gizmo.space === 'local') {
    leaves[0].matrix.decompose(pivot.position, pivot.quaternion, new THREE.Vector3());
  } else {
    box.getCenter(pivot.position);
    pivot.quaternion.identity();
  }
  pivot.scale.set(1, 1, 1);
  pivot.updateMatrixWorld();
  if (view.gizmo.object !== pivot) view.gizmo.attach(pivot);
}

// ===================================================================== gizmo
let gizmoDrag = null;
view.gizmo.addEventListener('mouseDown', () => {
  const leaves = selectedLeaves();
  gizmoDrag = { leaves, start: leaves.map(l => l.matrix.clone()), before: leaves.map(snapshot), pivot0: pivot.matrixWorld.clone() };
});
view.gizmo.addEventListener('objectChange', () => {
  if (!gizmoDrag) return;
  if (view.gizmo.mode === 'scale' && gizmoDrag.leaves.length > 1) {   // multi-object scale: uniform
    const s = (pivot.scale.x + pivot.scale.y + pivot.scale.z) / 3;
    const axis = [pivot.scale.x, pivot.scale.y, pivot.scale.z].find(v => Math.abs(v - 1) > 1e-6) ?? s;
    pivot.scale.setScalar(axis);
  }
  pivot.updateMatrixWorld();
  const delta = pivot.matrixWorld.clone().multiply(gizmoDrag.pivot0.clone().invert());
  gizmoDrag.leaves.forEach((l, i) => { l.matrix.multiplyMatrices(delta, gizmoDrag.start[i]); view.updateLeafMatrixOnly(l); });
  view.showSelectionBox(view.boxOf(gizmoDrag.leaves));
});
view.gizmo.addEventListener('mouseUp', () => {
  if (!gizmoDrag) return;
  const { leaves, before, start } = gizmoDrag;
  const mode = view.gizmo.mode;
  gizmoDrag = null;
  if (leaves.every((l, i) => l.matrix.equals(start[i]))) return;   // click without a drag
  const changes = [];
  leaves.forEach((l, i) => {
    const u = matrixToUnity(l.matrix);
    const after = { ...before[i] };
    after.p = tidy(u.p);
    if (mode !== 'translate') { after.r = tidy(u.r); after.s = tidy(u.s); }
    changes.push({ n: l, before: before[i], after });
    applyState(l, after);
  });
  pushCmd({ label: 'transform', undo: () => changes.forEach(c => applyState(c.n, c.before)), redo: () => changes.forEach(c => applyState(c.n, c.after)) });
  afterEdit();
});
view.updateLeafMatrixOnly = function (leaf) {
  for (const e of this.entries.get(leaf.id) || []) e.bucket.write(e);
  this.requestRender();
};

function setGizmoMode(m) {
  view.gizmo.setMode(m);
  document.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
}
function setSpace(s) {
  view.gizmo.setSpace(s);
  $('#btn-space').textContent = s === 'local' ? 'Local' : 'World';
  refreshSelection();
}
function applySnap() {
  const on = $('#snap-on').checked;
  view.gizmo.setTranslationSnap(on ? +$('#snap-move').value : null);
  view.gizmo.setRotationSnap(on ? THREE.MathUtils.degToRad(+$('#snap-rot').value) : null);
  view.gizmo.setScaleSnap(on ? +$('#snap-scale').value : null);
}

// ============================================================ viewport input
const canvas = view.canvas;
let down = null;
const rectEl = $('#select-rect');
canvas.addEventListener('pointerdown', ev => {
  if (ev.button !== 0 || !world) return;
  if (view.gizmo.axis !== null && view.gizmo.object) return;   // gizmo handles it
  down = { x: ev.clientX, y: ev.clientY, shift: ev.shiftKey, ctrl: ev.ctrlKey || ev.metaKey, alt: ev.altKey, moved: false };
});
window.addEventListener('pointermove', ev => {
  if (!down) return;
  const dx = ev.clientX - down.x, dy = ev.clientY - down.y;
  if (!down.moved && dx * dx + dy * dy > 25) down.moved = true;
  if (down.moved) {
    const r = $('#viewport').getBoundingClientRect();
    Object.assign(rectEl.style, {
      display: 'block', left: Math.min(down.x, ev.clientX) - r.left + 'px', top: Math.min(down.y, ev.clientY) - r.top + 'px',
      width: Math.abs(dx) + 'px', height: Math.abs(dy) + 'px',
    });
  }
});
window.addEventListener('pointerup', ev => {
  if (!down) return;
  const d = down; down = null;
  rectEl.style.display = 'none';
  if (d.moved) {
    let leaves = view.pickRect(d.x, d.y, ev.clientX, ev.clientY);
    const nodes = selectMode === 'group' && !d.alt ? [...new Set(leaves.map(l => l.topAncestor(world.root)))] : leaves;
    setSelection(nodes, { add: d.shift || d.ctrl });
    return;
  }
  const hit = view.pick(ev);
  if (!hit) { if (!d.shift && !d.ctrl) setSelection([]); return; }
  let node = hit.node;
  if (selectMode === 'group' && !d.alt) node = node.topAncestor(world.root);
  setSelection([node], { add: d.shift, toggle: d.ctrl, reveal: true });
});
canvas.addEventListener('dblclick', ev => {
  const hit = view.pick(ev);
  if (!hit) return;
  // drill one level deeper than the current selection
  const chain = []; let n = hit.node; while (n && n !== world.root) { chain.unshift(n); n = n.parent; }
  const cur = [...sel][0];
  const i = chain.indexOf(cur);
  setSelection([chain[Math.min(i + 1, chain.length - 1)] || hit.node], { reveal: true });
});
canvas.addEventListener('contextmenu', e => e.preventDefault());

// fly navigation: hold right mouse + WASD/QE (Shift = fast)
const keys = new Set();
let rmb = false;
canvas.addEventListener('pointerdown', e => { if (e.button === 2) rmb = true; });
window.addEventListener('pointerup', e => { if (e.button === 2) rmb = false; });
let lastT = 0;
view.onFrame = t => {
  const dt = Math.min(0.05, (t - lastT) / 1000); lastT = t;
  if (!keys.size || document.activeElement?.matches('input,textarea,select')) return false;
  const flyKeys = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE'];
  const arrows = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown'];
  if (!(rmb && flyKeys.some(k => keys.has(k))) && !arrows.some(k => keys.has(k))) return false;
  const cam = view.camera, tgt = view.controls.target;
  const speed = (keys.has('ShiftLeft') || keys.has('ShiftRight') ? 4 : 1) * Math.max(4, cam.position.distanceTo(tgt) * 0.8) * dt;
  const fwd = new THREE.Vector3(); cam.getWorldDirection(fwd);
  const right = new THREE.Vector3().crossVectors(fwd, cam.up).normalize();
  const flat = fwd.clone().setY(0).normalize();
  const mv = new THREE.Vector3();
  if (rmb) {
    if (keys.has('KeyW')) mv.add(fwd); if (keys.has('KeyS')) mv.sub(fwd);
    if (keys.has('KeyD')) mv.add(right); if (keys.has('KeyA')) mv.sub(right);
    if (keys.has('KeyE')) mv.y += 1; if (keys.has('KeyQ')) mv.y -= 1;
  }
  if (keys.has('ArrowUp')) mv.add(flat); if (keys.has('ArrowDown')) mv.sub(flat);
  if (keys.has('ArrowRight')) mv.add(right); if (keys.has('ArrowLeft')) mv.sub(right);
  if (keys.has('PageUp')) mv.y += 1; if (keys.has('PageDown')) mv.y -= 1;
  if (!mv.lengthSq()) return false;
  mv.normalize().multiplyScalar(speed);
  cam.position.add(mv); tgt.add(mv);
  view.controls.update();
  return true;
};

window.addEventListener('keyup', e => keys.delete(e.code));
window.addEventListener('blur', () => keys.clear());
window.addEventListener('keydown', e => {
  if (e.target.matches('input,textarea,select')) { if (e.key === 'Escape') e.target.blur(); return; }
  if ($('.modal.open')) { if (e.key === 'Escape') closeModals(); return; }
  keys.add(e.code);
  const ctrl = e.ctrlKey || e.metaKey;
  const k = e.key.toLowerCase();
  if (ctrl && k === 's') { e.preventDefault(); e.shiftKey ? saveAs() : save(); return; }
  if (ctrl && k === 'o') { e.preventDefault(); openDialog(); return; }
  if (!world) return;
  if (ctrl && k === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if (ctrl && k === 'y') { e.preventDefault(); redo(); return; }
  if (ctrl && k === 'd') { e.preventDefault(); duplicate(); return; }
  if (ctrl && k === 'c') { copy(); return; }
  if (ctrl && k === 'v') { paste(); return; }
  if (ctrl && k === 'a') { e.preventDefault(); setSelection(world.root.children); return; }
  if (ctrl && k === 'g') { e.preventDefault(); e.shiftKey ? ungroup() : group(); return; }
  if (rmb) return;   // WASD are flying
  if (k === 'delete' || k === 'backspace') { del(); return; }
  if (k === 'escape') { setSelection([]); return; }
  if (k === 'w') setGizmoMode('translate');
  else if (k === 'e') setGizmoMode('rotate');
  else if (k === 'r') setGizmoMode('scale');
  else if (k === 'l') setSpace(view.gizmo.space === 'local' ? 'world' : 'local');
  else if (k === 'f') focusSelection();
  else if (k === 'h') e.altKey ? unhideAll() : hideSelected();
  else if (k === 'tab') { e.preventDefault(); toggleSelectMode(); }
  else if (k === 'x') { $('#snap-on').checked = !$('#snap-on').checked; applySnap(); }
  else if (e.code === 'Numpad7' || k === '7') view.view('top');
  else if (e.code === 'Numpad1' || k === '1') view.view('front');
  else if (e.code === 'Numpad3' || k === '3') view.view('left');
});

function focusSelection() {
  const leaves = selectedLeaves();
  view.frame(leaves.length ? view.boxOf(leaves) : denseBox([...world.leaves()]));
}
// box around where most of the build is: the densest 8 m cell and everything within
// 30 m of it (5th-95th percentile), so far-off skyboxes and outliers don't zoom us out
function denseBox(leaves) {
  if (leaves.length < 20) return view.boxOf(leaves);
  const v = new THREE.Vector3(), cells = new Map(), pos = [];
  for (const l of leaves) {
    v.setFromMatrixPosition(l.matrix); pos.push(v.clone());
    const k = `${Math.floor(v.x / 8)},${Math.floor(v.y / 8)},${Math.floor(v.z / 8)}`;
    cells.set(k, (cells.get(k) || 0) + 1);
  }
  const best = [...cells].reduce((a, b) => (b[1] > a[1] ? b : a))[0].split(',').map(n => (+n + 0.5) * 8);
  const c = new THREE.Vector3(...best);
  const near = pos.filter(p => p.distanceTo(c) < 30);
  const xs = [], ys = [], zs = [];
  for (const p of near.length >= 20 ? near : pos) { xs.push(p.x); ys.push(p.y); zs.push(p.z); }
  const q = (a, f) => { a.sort((x, y) => x - y); return a[Math.floor(f * (a.length - 1))]; };
  return new THREE.Box3(new THREE.Vector3(q(xs, 0.05), q(ys, 0.05), q(zs, 0.05)), new THREE.Vector3(q(xs, 0.95), q(ys, 0.95), q(zs, 0.95)));
}
function toggleSelectMode() {
  selectMode = selectMode === 'group' ? 'object' : 'group';
  $('#btn-selmode').textContent = selectMode === 'group' ? 'Pick: Groups' : 'Pick: Objects';
}

// ================================================================= operations
function selectionRoots() {
  // selected nodes in document order
  const order = new Map(); let i = 0;
  for (const n of world.root.walk()) order.set(n, i++);
  return [...sel].sort((a, b) => order.get(a) - order.get(b));
}

function del() {
  const nodes = selectionRoots();
  if (!nodes.length) return;
  setSelection([]);
  const recs = nodes.slice().reverse().map(n => ({ n, ...detachNode(n) }));
  pushCmd({
    label: 'delete',
    undo: () => recs.slice().reverse().forEach(r => insertNode(r.n, r.p, r.i)),
    redo: () => recs.forEach(r => detachNode(r.n)),
  });
  afterEdit();
}

function cloneNode(n, parent) { return nodeFromJSON(JSON.parse(JSON.stringify(serializeNode(n))), parent); }

function duplicate() {
  const nodes = selectionRoots();
  if (!nodes.length) return;
  const recs = nodes.map(n => { const c = cloneNode(n, n.parent); const i = n.parent.children.indexOf(n) + 1; insertNode(c, n.parent, i); return { n: c, p: n.parent }; });
  pushCmd({
    label: 'duplicate',
    undo: () => recs.forEach(r => detachNode(r.n)),
    redo: () => recs.forEach(r => insertNode(r.n, r.p, r.p.children.length)),
  });
  setSelection(recs.map(r => r.n));
  toast(`Duplicated ${recs.length} item(s) in place — move them with the gizmo`);
}

function copy() {
  const nodes = selectionRoots();
  if (!nodes.length) return;
  clipboard = nodes.map(serializeNode);
  const text = stringifyWorld({ objects: clipboard });
  navigator.clipboard?.writeText(text).catch(() => {});
  toast(`Copied ${nodes.length} item(s)`);
}
async function paste() {
  let objs = clipboard;
  try {
    const t = await navigator.clipboard.readText();
    const j = JSON.parse(t);
    if (Array.isArray(j?.objects)) objs = j.objects; else if (j?.n) objs = [j];
  } catch { /* use internal clipboard */ }
  if (!objs?.length) return;
  addObjects(objs, 'paste');
}
function addObjects(objs, label) {
  const parent = world.root;
  const nodes = objs.map(o => nodeFromJSON(JSON.parse(JSON.stringify(o)), parent));
  nodes.forEach(n => insertNode(n, parent, parent.children.length));
  pushCmd({ label, undo: () => nodes.forEach(detachNode), redo: () => nodes.forEach(n => insertNode(n, parent, parent.children.length)) });
  setSelection(nodes);
  afterEdit();
  return nodes;
}

function group() {
  const nodes = selectionRoots();
  if (nodes.length < 1) return;
  const parent = nodes[0].parent;
  if (nodes.some(n => n.parent !== parent)) { toast('Select items that share the same parent to group them', 'error'); return; }
  const g = new Node({ n: 'group', objects: true }, parent);
  const idx = parent.children.indexOf(nodes[0]);
  const recs = nodes.map(n => ({ n, i: parent.children.indexOf(n) }));
  const doIt = () => {
    for (const r of recs.slice().reverse()) parent.children.splice(parent.children.indexOf(r.n), 1);
    g.children = recs.map(r => r.n); g.children.forEach(c => c.parent = g);
    parent.children.splice(Math.min(idx, parent.children.length), 0, g);
  };
  const undoIt = () => {
    parent.children.splice(parent.children.indexOf(g), 1);
    for (const r of recs) { r.n.parent = parent; parent.children.splice(r.i, 0, r.n); }
    g.children = [];
  };
  doIt();
  pushCmd({ label: 'group', undo: () => { undoIt(); setSelection(recs.map(r => r.n)); }, redo: () => { doIt(); setSelection([g]); } });
  setSelection([g]);
  toast(`Grouped ${nodes.length} item(s)`);
}
function ungroup() {
  const groups = selectionRoots().filter(n => n.isGroup);
  if (!groups.length) return;
  const recs = groups.map(g => ({ g, p: g.parent, i: g.parent.children.indexOf(g), kids: g.children.slice() }));
  const doIt = () => recs.forEach(r => {
    r.p.children.splice(r.p.children.indexOf(r.g), 1, ...r.kids);
    r.kids.forEach(k => k.parent = r.p);
  });
  const undoIt = () => recs.slice().reverse().forEach(r => {
    r.p.children.splice(r.p.children.indexOf(r.kids[0]), r.kids.length, r.g);
    r.g.children = r.kids.slice(); r.kids.forEach(k => k.parent = r.g);
  });
  doIt();
  pushCmd({ label: 'ungroup', undo: () => { undoIt(); setSelection(recs.map(r => r.g)); }, redo: () => { doIt(); setSelection(recs.flatMap(r => r.kids)); } });
  setSelection(recs.flatMap(r => r.kids));
}

function hideSelected() {
  for (const n of sel) { n.hidden = true; view.refreshNode(n); }
  setSelection([]);
}
function unhideAll() {
  for (const n of world.root.walk()) if (n.hidden) { n.hidden = false; view.refreshNode(n); }
  outliner.refresh();
}

function addFromLibrary(name) {
  if (!world) newWorld();
  const t = view.controls.target;
  const snap = $('#snap-on').checked ? +$('#snap-move').value || 0 : 0;
  const s = v => snap ? Math.round(v / snap) * snap : +v.toFixed(3);
  const obj = { n: name, p: [s(-t.x), s(t.y), s(t.z)], r: [0, 0, 0], s: [1, 1, 1], c: [1, 1, 1] };
  if (assets.isPrimitive(name)) obj.m = 'plaster_1';
  addObjects([obj], 'add ' + name);
}

function applyMaterial(name) {
  const leaves = selectedLeaves();
  if (!leaves.length) { toast('Select objects first, then click a material'); return; }
  editLeaves(leaves, n => { n.obj.m = name; }, 'material');
}

// ================================================================ inspector
function numInput(value, onCommit, step = 0.1) {
  const i = el('input', { type: 'number', step, value: fmt(value) });
  i.addEventListener('change', () => { const v = parseFloat(i.value); if (Number.isFinite(v)) onCommit(v); });
  scrubbable(i, step, onCommit);
  return i;
}
function scrubbable(input, step, onCommit) {
  // drag on the field's label to scrub
  input.addEventListener('wheel', e => {
    if (document.activeElement !== input) return;
    e.preventDefault();
    const v = (parseFloat(input.value) || 0) + (e.deltaY < 0 ? step : -step) * (e.shiftKey ? 10 : 1);
    input.value = fmt(v); onCommit(v);
  }, { passive: false });
}
function vecRow(label, vec, onCommit, step) {
  const row = el('div', { class: 'row vec' }, el('label', {}, label));
  ['X', 'Y', 'Z'].forEach((ax, i) => row.append(el('span', { class: 'ax ax' + ax }, ax), numInput(vec[i] ?? 0, v => onCommit(i, v), step)));
  return row;
}
const toHex = c => '#' + c.slice(0, 3).map(v => Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, '0')).join('');
const fromHex = h => [1, 3, 5].map(i => parseInt(h.substr(i, 2), 16) / 255);

function inspector() {
  const box = $('#inspector-body');
  box.innerHTML = '';
  if (!world) { box.append(el('p', { class: 'muted' }, 'Open a .world file to start.')); return; }
  const leaves = selectedLeaves();
  if (!sel.size) {
    box.append(el('p', { class: 'muted' }, `${world.count().toLocaleString()} objects. Click to select (groups by default), drag a box to multi-select, Alt+click for a single object.`));
    box.append(el('button', { onclick: worldSettings }, 'World settings…'));
    return;
  }
  const single = sel.size === 1 && !([...sel][0].isGroup) ? [...sel][0] : null;
  if (single) {
    const o = single.obj, def = assets.object(o.n);
    box.append(el('div', { class: 'row' }, el('label', {}, 'Object'), datalistInput(o.n, 'dl-objects', v => {
      if (!v) return; editLeaves([single], n => { n.obj.n = v; }, 'type');
    })));
    if (def?.proxy) box.append(el('p', { class: 'note' }, def.kind === 'light' ? 'Light (shown as a wire box).' : def.kind === 'effect' ? 'Effect (shown as a wire box).' : 'Shown as a sized stand-in box: this model is only stored in the game\'s encrypted bundles.'));
    if (!def && assets.ready) box.append(el('p', { class: 'note' }, 'Unknown object type (game-mode marker or newer than your extracted assets).'));
    box.append(el('div', { class: 'row' }, el('label', {}, 'Material'), datalistInput(o.m || '', 'dl-materials', v => {
      editLeaves([single], n => { if (v) n.obj.m = v; else delete n.obj.m; }, 'material');
    }, '(prefab default)')));
    box.append(colorRow(o.c, (c) => editLeaves([single], n => { n.obj.c = c; }, 'color')));
    const setv = (key, def) => (i, v) => editLeaves([single], n => { const a = (n.obj[key] || def).slice(); a[i] = v; n.obj[key] = a; }, key);
    box.append(vecRow('Position', o.p || [0, 0, 0], setv('p', [0, 0, 0]), 0.1));
    box.append(vecRow('Rotation', o.r || [0, 0, 0], setv('r', [0, 0, 0]), 5));
    box.append(vecRow('Scale', o.s || [1, 1, 1], setv('s', [1, 1, 1]), 0.1));
    const extra = Object.keys(o).filter(k => !['n', 'p', 'r', 's', 'c', 'm'].includes(k));
    if (extra.length) box.append(el('p', { class: 'muted small' }, 'Other fields: ' + extra.join(', ')));
  } else {
    const groups = [...sel].filter(n => n.isGroup).length;
    box.append(el('p', {}, el('b', {}, `${sel.size} selected`), ` — ${leaves.length.toLocaleString()} object(s)${groups ? `, ${groups} group(s)` : ''}`));
    const center = view.boxOf(leaves).getCenter(new THREE.Vector3());
    const cu = [-center.x, center.y, center.z];
    box.append(vecRow('Center', cu, (i, v) => {
      const d = v - cu[i];
      editLeaves(leaves, n => { const p = (n.obj.p || [0, 0, 0]).slice(); p[i] = +(p[i] + d).toFixed(6); n.obj.p = p; }, 'move');
    }, 0.1));
    const colors = new Set(leaves.map(l => JSON.stringify(l.obj.c || null)));
    box.append(colorRow(colors.size === 1 ? leaves[0].obj.c : null, c => editLeaves(leaves, n => { n.obj.c = c; }, 'color'), colors.size > 1 ? 'mixed' : ''));
    const mats = new Set(leaves.map(l => l.obj.m || ''));
    box.append(el('div', { class: 'row' }, el('label', {}, 'Material'), datalistInput(mats.size === 1 ? [...mats][0] : '', 'dl-materials', v => {
      editLeaves(leaves, n => { if (v) n.obj.m = v; else delete n.obj.m; }, 'material');
    }, mats.size > 1 ? 'mixed' : '(prefab default)')));
    const btns = el('div', { class: 'btns' });
    if (groups) btns.append(el('button', { onclick: ungroup, title: 'Ctrl+Shift+G' }, 'Ungroup'));
    btns.append(el('button', { onclick: group, title: 'Ctrl+G' }, 'Group'));
    if (groups) btns.append(el('button', { onclick: () => setSelection([...sel].flatMap(n => n.isGroup ? n.children : [n])) }, 'Select children'));
    box.append(btns);
  }
  const btns = el('div', { class: 'btns' },
    el('button', { onclick: duplicate, title: 'Ctrl+D' }, 'Duplicate'),
    el('button', { onclick: del, title: 'Delete' }, 'Delete'),
    el('button', { onclick: focusSelection, title: 'F' }, 'Focus'),
    el('button', { onclick: hideSelected, title: 'H' }, 'Hide'),
    el('button', { onclick: exportSelection }, 'Export…'));
  box.append(btns);
}

function datalistInput(value, list, onCommit, placeholder = '') {
  const i = el('input', { list, value, placeholder, spellcheck: 'false' });
  i.addEventListener('change', () => onCommit(i.value.trim()));
  return i;
}
function colorRow(c, onCommit, note = '') {
  c = c || [1, 1, 1];
  const row = el('div', { class: 'row vec' }, el('label', {}, 'Color'));
  const pick = el('input', { type: 'color', value: toHex(c) });
  pick.addEventListener('change', () => onCommit(fromHex(pick.value).map(v => +v.toFixed(4))));
  row.append(pick);
  ['R', 'G', 'B'].forEach((ax, i) => row.append(numInput(c[i] ?? 1, v => { const a = c.slice(0, 3); a[i] = v; onCommit(a); }, 0.05)));
  if (note) row.append(el('span', { class: 'muted small' }, note));
  return row;
}

// ================================================================== library
function buildLibrary() {
  const dlo = $('#dl-objects'), dlm = $('#dl-materials');
  dlo.innerHTML = ''; dlm.innerHTML = '';
  for (const n of assets.objectNames || []) dlo.append(el('option', { value: n }));
  for (const n of assets.materialNames || []) dlm.append(el('option', { value: n }));
  renderLibrary();
}
let libTab = 'objects';
function renderLibrary() {
  const list = $('#library-list');
  const q = $('#library-search').value.trim().toLowerCase();
  list.innerHTML = '';
  if (!assets.ready) { list.append(el('p', { class: 'muted' }, 'Assets not extracted yet.')); return; }
  const names = (libTab === 'objects' ? assets.objectNames : assets.materialNames).filter(n => !q || n.toLowerCase().includes(q));
  const frag = document.createDocumentFragment();
  for (const n of names.slice(0, 600)) {
    if (libTab === 'objects') {
      const d = assets.object(n);
      frag.append(el('div', { class: 'lib-item', title: 'Click to add at the view center', onclick: () => addFromLibrary(n) },
        el('span', { class: 'tag ' + (d.proxy ? 'proxy' : d.kind) }, d.kind === 'mesh' ? (d.proxy ? 'box' : 'mesh') : d.kind), n));
    } else {
      const m = assets.catalog.materials[n];
      const sw = el('span', { class: 'swatch' });
      const tex = assets.mode === 'full' && (m.tex?._MainTex || m.tex?._BaseMap);
      sw.style.background = tex ? `url("${assets.base}tex/${encodeURIComponent(tex)}") center/cover, ${toHex(m.color)}` : toHex(m.avg || m.color);
      frag.append(el('div', { class: 'lib-item', title: `${m.kind} — click to apply to the selection`, onclick: () => applyMaterial(n) }, sw, n,
        el('span', { class: 'muted small' }, ' ' + m.kind)));
    }
  }
  list.append(frag);
  if (names.length > 600) list.append(el('p', { class: 'muted small' }, `${names.length - 600} more — refine the search`));
}
$('#library-search').addEventListener('input', renderLibrary);
document.querySelectorAll('[data-libtab]').forEach(b => b.addEventListener('click', () => {
  libTab = b.dataset.libtab;
  document.querySelectorAll('[data-libtab]').forEach(x => x.classList.toggle('on', x === b));
  renderLibrary();
}));

// ================================================================= outliner
const outliner = new Outliner($('#outliner-list'), {
  getRoot: () => world?.root,
  isSelected: n => { if (sel.has(n)) return 'sel'; let p = n.parent; while (p) { if (sel.has(p)) return 'in'; p = p.parent; } return ''; },
  onSelect: (n, e) => setSelection([n], { add: e.shiftKey, toggle: e.ctrlKey || e.metaKey }),
  onFocus: n => { setSelection([n]); focusSelection(); },
  onToggleHide: n => { n.hidden = !n.hidden; view.refreshNode(n); outliner.refresh(); },
  label: n => {
    if (n.isGroup) return { text: `group`, sub: `${[...n.leaves()].length}`, color: null };
    return { text: n.obj.n, sub: n.obj.m || '', color: n.obj.c ? toHex(n.obj.c) : null, proxy: assets.ready && (!assets.object(n.obj.n) || assets.object(n.obj.n).proxy) };
  },
});
$('#outliner-search').addEventListener('input', e => outliner.setFilter(e.target.value));
$('#outliner-select-matches').addEventListener('click', () => { const m = outliner.matches(); if (m.length) setSelection(m); });

// ================================================================ files
async function loadWorldText(text, path, name) {
  let w;
  try { w = World.parse(text, path); } catch (e) { toast('Not a valid world file: ' + e.message, 'error'); return; }
  world = w;
  world.displayName = name || (path ? path.split(/[\\/]/).pop() : 'untitled.world');
  sel.clear(); undoStack.length = 0; redoStack.length = 0;
  const t0 = performance.now();
  view.load(world);
  outliner.refresh(true);
  // open looking north (from Unity -Z), the way builds are usually laid out to be read
  view.camera.position.copy(view.controls.target).add(new THREE.Vector3(0, 0.9, -1));
  focusSelection();
  inspector(); updateTitle(); updateStatus();
  const proxies = [...world.leaves()].filter(l => !assets.object(l.obj.n) || assets.object(l.obj.n).proxy).length;
  toast(`Loaded ${world.count().toLocaleString()} objects in ${Math.round(performance.now() - t0)} ms` + (proxies ? ` — ${proxies} shown as stand-in boxes` : ''));
}

async function openPath(path) {
  try {
    const text = await api.text('/api/world?path=' + encodeURIComponent(path));
    await loadWorldText(text, path);
    localStorage.setItem('we.lastDir', path.replace(/[\\/][^\\/]*$/, ''));
  } catch (e) { toast('Open failed: ' + e.message, 'error'); }
}

function newWorld() {
  loadWorldText(JSON.stringify({ respawn: { p: [0, 1, 0], r: 0 }, oceanlevel: 0.0, weather: 'Clear', valuetype: 'float', objects: [] }), null, 'untitled.world');
}

async function save() {
  if (!world) return;
  if (MODE === 'web') return world.handle ? webWrite(world.handle) : saveAs();
  if (!world.path) return saveAs();
  await writeWorld(world.path);
}
async function writeWorld(path) {
  try {
    const r = await api.post('/api/world?path=' + encodeURIComponent(path), world.stringify());
    world.path = path; world.displayName = path.split(/[\\/]/).pop(); world.dirty = false;
    updateTitle();
    toast(`Saved ${world.displayName}` + (r.backup ? ' (previous version kept as .bak)' : ''));
  } catch (e) { toast('Save failed: ' + e.message, 'error'); }
}
function saveAs() {
  if (!world) return;
  if (MODE === 'web') return webWrite(null);
  fileDialog('save', path => writeWorld(path), world.displayName);
}
function openDialog() {
  if (world?.dirty && !confirm('Discard unsaved changes?')) return;
  if (MODE === 'web') {
    webPickText().then(async f => { if (f) { await loadWorldText(f.text, null, f.name); if (world) world.handle = f.handle; } })
      .catch(e => toast('Open failed: ' + e.message, 'error'));
    return;
  }
  fileDialog('open', openPath);
}
function exportSelection() {
  const nodes = selectionRoots();
  if (!nodes.length) return;
  const text = stringifyWorld({ ...world.header, objects: nodes.map(serializeNode) });
  if (MODE === 'web') { webSaveText(text, 'selection.world', null).then(r => r && toast('Exported ' + r.name)).catch(e => toast('Export failed: ' + e.message, 'error')); return; }
  fileDialog('save', async path => {
    try { await api.post('/api/world?path=' + encodeURIComponent(path), text); toast('Exported ' + path.split(/[\\/]/).pop()); }
    catch (e) { toast('Export failed: ' + e.message, 'error'); }
  }, 'selection.world');
}
async function mergeWorld() {
  if (!world) return;
  const merge = text => {
    const j = JSON.parse(text.replace(/^﻿/, ''));
    const nodes = addObjects([{ n: 'group', objects: j.objects || [] }], 'merge');
    toast(`Merged ${[...nodes[0].leaves()].length.toLocaleString()} objects as one group`);
  };
  try {
    if (MODE === 'web') { const f = await webPickText(); if (f) merge(f.text); return; }
    fileDialog('open', async path => {
      try { merge(await api.text('/api/world?path=' + encodeURIComponent(path))); }
      catch (e) { toast('Merge failed: ' + e.message, 'error'); }
    });
  } catch (e) { toast('Merge failed: ' + e.message, 'error'); }
}

// --- browser file access (website). The File System Access pickers are not
// allowed everywhere (e.g. inside another site's iframe), so fall back to a
// plain file input for opening and a download for saving.
const PICKER_TYPES = [{ description: '3DXChat world', accept: { 'application/json': ['.world', '.json'] } }];
async function webPickText() {
  if ('showOpenFilePicker' in window) {
    try {
      const [h] = await window.showOpenFilePicker({ types: PICKER_TYPES });
      const f = await h.getFile();
      return { text: await f.text(), name: f.name, handle: h };
    } catch (e) { if (e.name === 'AbortError') return null; /* not allowed here: fall back */ }
  }
  return new Promise(resolve => {
    const i = el('input', { type: 'file', accept: '.world,.json' });
    i.onchange = async () => { const f = i.files[0]; resolve(f ? { text: await f.text(), name: f.name, handle: null } : null); };
    i.click();
  });
}
async function webSaveText(text, name, handle) {
  if (handle?.createWritable) {
    const w = await handle.createWritable(); await w.write(text); await w.close();
    return { handle, name: handle.name };
  }
  if ('showSaveFilePicker' in window) {
    try {
      const h = await window.showSaveFilePicker({ suggestedName: name, types: PICKER_TYPES });
      const w = await h.createWritable(); await w.write(text); await w.close();
      return { handle: h, name: h.name };
    } catch (e) { if (e.name === 'AbortError') return null; /* not allowed here: fall back */ }
  }
  const a = el('a', { href: URL.createObjectURL(new Blob([text], { type: 'application/json' })), download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  return { handle: null, name, downloaded: true };
}
async function webWrite(handle) {
  try {
    const r = await webSaveText(world.stringify(), world.displayName, handle);
    if (!r) return;
    world.handle = r.handle; world.displayName = r.name; world.dirty = false;
    updateTitle();
    toast(r.downloaded ? `Downloaded ${r.name} — check your Downloads folder` : `Saved ${r.name}`);
  } catch (e) { toast('Save failed: ' + e.message, 'error'); }
}

// --- simple file browser modal (files live on this PC; the local server reads/writes them)
async function fileDialog(mode, onPick, defaultName = '') {
  const m = $('#modal-file');
  m.classList.add('open');
  $('#file-title').textContent = mode === 'open' ? 'Open world' : 'Save world as';
  const nameIn = $('#file-name');
  nameIn.value = defaultName;
  $('#file-name-row').style.display = mode === 'save' ? '' : 'none';
  let dir = localStorage.getItem('we.lastDir') || '';
  const list = $('#file-list');
  const go = async d => {
    try {
      const r = await api.json('/api/browse?dir=' + encodeURIComponent(d || ''));
      dir = r.dir; $('#file-dir').value = r.dir;
      list.innerHTML = '';
      list.append(el('div', { class: 'f dir', onclick: () => go(r.parent) }, '⬑ ..'));
      for (const d2 of r.dirs) list.append(el('div', { class: 'f dir', onclick: () => go(r.dir + '\\' + d2) }, '📁 ' + d2));
      for (const f of r.files) {
        const item = el('div', { class: 'f', onclick: () => { if (mode === 'open') pick(r.dir + '\\' + f.name); else nameIn.value = f.name; } },
          '🌐 ' + f.name, el('span', { class: 'muted small' }, ` ${(f.size / 1048576).toFixed(1)} MB · ${new Date(f.mtime * 1000).toLocaleString()}`));
        list.append(item);
      }
    } catch (e) { toast(e.message, 'error'); }
  };
  const pick = p => { closeModals(); localStorage.setItem('we.lastDir', dir); onPick(p); };
  $('#file-dir').onchange = e => go(e.target.value);
  $('#file-ok').onclick = () => {
    if (mode === 'save') {
      let n = nameIn.value.trim(); if (!n) return;
      if (!/\.(world|json)$/i.test(n)) n += '.world';
      pick(dir + '\\' + n);
    }
  };
  $('#file-ok').style.display = mode === 'save' ? '' : 'none';
  go(dir);
}
function closeModals() { document.querySelectorAll('.modal.open').forEach(m => m.classList.remove('open')); }
document.querySelectorAll('.modal .close').forEach(b => b.addEventListener('click', closeModals));

// drag & drop a .world file onto the window
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', async e => {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (!f) return;
  if (world?.dirty && !confirm('Discard unsaved changes?')) return;
  await loadWorldText(await f.text(), null, f.name);
  toast('Opened from drag & drop — use Save As to choose where to save it');
});

// ============================================================ world settings
function worldSettings() {
  if (!world) return;
  const h = world.header;
  const m = $('#modal-world'); m.classList.add('open');
  const body = $('#world-body'); body.innerHTML = '';
  const rp = h.respawn || { p: [0, 0, 0], r: 0 };
  const p = rp.p.slice(); let r = rp.r || 0;
  body.append(vecRow('Respawn', p, (i, v) => { p[i] = v; }, 0.5));
  body.append(el('div', { class: 'row' }, el('label', {}, 'Facing (°)'), numInput(r, v => { r = v; }, 5)));
  body.append(el('div', { class: 'btns' }, el('button', {
    onclick: () => { const t = view.controls.target; p[0] = +(-t.x).toFixed(3); p[1] = +t.y.toFixed(3); p[2] = +t.z.toFixed(3); worldSettingsApply(p, r); worldSettings(); },
  }, 'Use view center as respawn')));
  const weather = el('input', { list: 'dl-weather', value: h.weather ?? '' });
  body.append(el('div', { class: 'row' }, el('label', {}, 'Weather'), weather));
  let ocean = +h.oceanlevel || 0;
  body.append(el('div', { class: 'row' }, el('label', {}, 'Ocean level'), numInput(ocean, v => { ocean = v; }, 1)));
  const amb = el('input', { value: (h.ambient || []).join(', ') });
  body.append(el('div', { class: 'row' }, el('label', {}, 'Ambient'), amb));
  $('#world-ok').onclick = () => {
    const before = JSON.parse(JSON.stringify(world.header));
    worldSettingsApply(p, r);
    if (weather.value.trim()) h.weather = weather.value.trim();
    if ('oceanlevel' in h || ocean) h.oceanlevel = ocean;
    const a = amb.value.split(',').map(s => parseFloat(s)).filter(Number.isFinite);
    if (a.length) h.ambient = a;
    const after = JSON.parse(JSON.stringify(world.header));
    pushCmd({ label: 'world settings', undo: () => { world.header = JSON.parse(JSON.stringify(before)); view.load(world); }, redo: () => { world.header = JSON.parse(JSON.stringify(after)); view.load(world); } });
    view.load(world); setSelection([...sel]);
    closeModals();
  };
}
function worldSettingsApply(p, r) { world.header.respawn = { p: tidy(p), r: +r }; }

// =========================================================== status / title
function updateTitle() {
  const n = world ? (world.dirty ? '● ' : '') + world.displayName : 'no world';
  document.title = `${n} — 3DX World Editor`;
  $('#file-label').textContent = world ? (world.path || world.displayName) + (world.dirty ? ' (unsaved)' : '') : '';
}
function updateStatus() {
  if (!world) { $('#status').textContent = ''; return; }
  const leaves = selectedLeaves().length;
  $('#status').textContent = `${world.count().toLocaleString()} objects · ${view.buckets.size} draw batches · ${leaves ? leaves.toLocaleString() + ' selected' : 'nothing selected'} · undo ${undoStack.length}`;
}
window.addEventListener('beforeunload', e => { if (world?.dirty) { e.preventDefault(); e.returnValue = ''; } });

// ================================================================ toolbar
const on = (id, f) => $(id).addEventListener('click', f);
on('#btn-new', () => { if (world?.dirty && !confirm('Discard unsaved changes?')) return; newWorld(); });
on('#btn-open', openDialog);
on('#btn-save', save);
on('#btn-saveas', saveAs);
on('#btn-merge', mergeWorld);
on('#btn-undo', undo);
on('#btn-redo', redo);
on('#btn-space', () => setSpace(view.gizmo.space === 'local' ? 'world' : 'local'));
on('#btn-selmode', toggleSelectMode);
on('#btn-world', worldSettings);
on('#btn-help', () => $('#modal-help').classList.add('open'));
on('#btn-focus', focusSelection);
document.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => setGizmoMode(b.dataset.mode)));
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => view.view(b.dataset.view)));
['#snap-on', '#snap-move', '#snap-rot', '#snap-scale'].forEach(id => $(id).addEventListener('change', applySnap));
$('#tog-grid').addEventListener('change', e => { view.grid.visible = e.target.checked; view.requestRender(); });
$('#tog-ocean').addEventListener('change', e => { view.ocean.visible = e.target.checked; view.requestRender(); });
$('#tog-respawn').addEventListener('change', e => { view.respawn.visible = e.target.checked && !!world?.header.respawn; view.requestRender(); });
setGizmoMode('translate'); applySnap();
// navigation hint: shown until dismissed (remembered per browser)
try { if (localStorage.getItem('we.navHint') === 'off') $('#nav-hint').classList.add('hidden'); } catch { /* storage blocked */ }
on('#nav-hint-close', () => { $('#nav-hint').classList.add('hidden'); try { localStorage.setItem('we.navHint', 'off'); } catch { /* storage blocked */ } });
// clicking into the 3D view gives it keyboard focus (WASD, F, W/E/R...) - matters inside the SBS window iframe
canvas.tabIndex = 0;
canvas.addEventListener('pointerdown', () => canvas.focus({ preventScroll: true }));

// ================================================================ startup
async function extractFlow(status) {
  const m = $('#modal-extract'); m.classList.add('open');
  $('#extract-game').value = status.game_dir;
  $('#extract-dir').textContent = status.assets_dir;
  const log = $('#extract-log');
  return new Promise(resolve => {
    $('#extract-skip').onclick = () => { closeModals(); resolve(false); };
    $('#extract-go').onclick = async () => {
      $('#extract-go').disabled = true;
      try { await api.post('/api/extract?game=' + encodeURIComponent($('#extract-game').value.trim()), ''); }
      catch (e) { toast(e.message, 'error'); $('#extract-go').disabled = false; return; }
      const poll = setInterval(async () => {
        const s = await api.json('/api/status');
        log.textContent = s.extract.log.join('\n'); log.scrollTop = log.scrollHeight;
        if (!s.extract.running && s.extract.ok !== null) {
          clearInterval(poll);
          $('#extract-go').disabled = false;
          if (s.extract.ok) { closeModals(); resolve(true); } else toast('Extraction failed — see the log', 'error');
        }
      }, 800);
    };
  });
}

// console / automation handle
window.editor = {
  THREE, view, assets, openPath, save, undo, redo, setSelection, editLeaves, addObjects, group, ungroup, duplicate, del,
  get world() { return world; }, get selection() { return [...sel]; }, selectedLeaves,
};

async function loadDefaultWorld() {
  const q = new URLSearchParams(location.search).get('world');
  const url = q || DEFAULT_WORLD;
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
    const name = decodeURIComponent(url.split('?')[0].split(/[\\/]/).pop()) || 'world.world';
    await loadWorldText(await r.text(), null, name);
    return true;
  } catch (e) { toast(`Could not load ${url}: ${e.message}`, 'error'); return false; }
}

function updateModeChip() {
  const c = $('#mode-chip');
  if (!c) return;
  const full = assets.mode === 'full';
  c.textContent = full ? 'Real game models' : 'Basic shapes';
  c.className = 'chip ' + (full ? 'ok' : 'warn');
  c.title = full ? 'Models and materials read from your own 3DXChat install.'
    : 'Basic shapes are generated; other objects show as sized boxes. Use the desktop app (or link your game) for the real models.';
}

(async function start() {
  inspector(); updateTitle();
  if (MODE === 'web') {
    try { await assets.loadLite(); } catch (e) { toast(e.message, 'error'); }
    buildLibrary();
    updateModeChip();
    if (!(await loadDefaultWorld())) $('#welcome').classList.add('open');
  } else {
    let status;
    try { status = await api.json('/api/status'); }
    catch (e) { toast('Cannot reach the editor server. Start it with Start-WorldEditor.bat', 'error'); return; }
    if (!status.assets) await extractFlow(status);
    try {
      await assets.load('assets/');
      toast(`Game assets: ${assets.objectNames.length} objects, ${assets.materialNames.length} materials`);
    } catch (e) {
      await assets.loadLite().catch(() => {});
      toast('No extracted game assets — using basic shapes', 'error');
    }
    buildLibrary();
    updateModeChip();
    $('#welcome').classList.add('open');
  }
  $('#welcome-open').onclick = () => { closeModals(); openDialog(); };
  $('#welcome-new').onclick = () => { closeModals(); newWorld(); };
})();
