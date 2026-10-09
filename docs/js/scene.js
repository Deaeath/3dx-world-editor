// Instanced renderer for world nodes + camera, picking and selection highlight.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const HIDDEN = new THREE.Matrix4().makeScale(0, 0, 0);
const SEL_COLOR = new THREE.Color(0.35, 0.75, 1.0);
const _m = new THREE.Matrix4(), _c = new THREE.Color(), _box = new THREE.Box3(), _v = new THREE.Vector3();

class Bucket {
  constructor(view, geometry, material) {
    this.view = view;
    this.geometry = geometry;
    this.material = material;
    this.refs = [];          // instance index -> entry {node, part, bucket, index, color}
    this.capacity = 0;
    this.mesh = null;
    this.grow(16);
  }
  grow(min) {
    let cap = Math.max(16, this.capacity);
    while (cap < min) cap *= 2;
    const mesh = new THREE.InstancedMesh(this.geometry, this.material, cap);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    mesh.setColorAt(0, _c.setRGB(1, 1, 1));
    if (this.mesh) {
      mesh.instanceMatrix.array.set(this.mesh.instanceMatrix.array.subarray(0, this.refs.length * 16));
      mesh.instanceColor.array.set(this.mesh.instanceColor.array.subarray(0, this.refs.length * 3));
      this.view.scene.remove(this.mesh);
      this.mesh.dispose();
    }
    mesh.count = this.refs.length;
    mesh.userData.bucket = this;
    if (this.material.transparent) mesh.renderOrder = 2;
    this.mesh = mesh;
    this.capacity = cap;
    this.view.scene.add(mesh);
  }
  add(entry) {
    if (this.refs.length >= this.capacity) this.grow(this.refs.length + 1);
    entry.bucket = this; entry.index = this.refs.length;
    this.refs.push(entry);
    this.mesh.count = this.refs.length;
    this.write(entry);
  }
  remove(entry) {
    const last = this.refs.pop();
    if (last !== entry) {
      this.refs[entry.index] = last;
      last.index = entry.index;
      this.write(last);
    }
    this.mesh.count = this.refs.length;
    this.dirty();
  }
  write(e) {
    const node = e.node;
    if (node.hidden || this.view.isHiddenByAncestor(node)) this.mesh.setMatrixAt(e.index, HIDDEN);
    else this.mesh.setMatrixAt(e.index, e.part.matrix ? _m.multiplyMatrices(node.matrix, e.part.matrix) : node.matrix);
    _c.copy(e.color);
    if (e.selected) _c.lerp(SEL_COLOR, 0.55);
    this.mesh.setColorAt(e.index, _c);
    this.dirty();
  }
  dirty() {
    this.mesh.instanceMatrix.needsUpdate = true;
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
    this.mesh.boundingSphere = null;
    this.mesh.boundingBox = null;
  }
}

export class SceneView {
  constructor(canvas, assets) {
    this.assets = assets;
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1d2026);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3a3328, 0.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(-0.4, 1, 0.6);
    this.scene.add(sun);

    this.camera = new THREE.PerspectiveCamera(55, 1, 0.05, 30000);
    this.camera.position.set(0, 40, 80);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.screenSpacePanning = true;
    this.controls.zoomToCursor = true;
    // left = select (Alt+left orbits, set per click in main.js), right = mouse-look (main.js)
    this.controls.mouseButtons = { LEFT: -1, MIDDLE: THREE.MOUSE.PAN, RIGHT: -1 };
    this.controls.addEventListener('change', () => this.requestRender());

    this.gizmo = new TransformControls(this.camera, canvas);
    this.gizmo.setSize(0.9);
    this.scene.add(this.gizmo.getHelper());
    this.gizmo.addEventListener('dragging-changed', e => { this.controls.enabled = !e.value; });
    this.gizmo.addEventListener('change', () => this.requestRender());

    this.grid = new THREE.GridHelper(400, 400, 0x4b5160, 0x30343c);
    this.grid.material.transparent = true; this.grid.material.opacity = 0.55;
    this.scene.add(this.grid);
    this.selBox = new THREE.Box3Helper(new THREE.Box3(), 0x5ac8ff);
    this.selBox.visible = false;
    this.scene.add(this.selBox);
    this.respawn = makeRespawnMarker();
    this.scene.add(this.respawn);
    this.ocean = new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: 0x1b5d84, transparent: true, opacity: 0.45, roughness: 0.15, depthWrite: false }));
    this.ocean.visible = false;
    this.scene.add(this.ocean);

    this.buckets = new Map();
    this.entries = new Map();     // node.id -> [entry]
    this.raycaster = new THREE.Raycaster();
    this._needsRender = true;
    this.animate = false;
    this.onFrame = null;
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    const loop = t => {
      requestAnimationFrame(loop);
      this.assets.time.value = t / 1000;
      const moving = this.onFrame?.(t);
      if (this._needsRender || this.animate || moving) { this._needsRender = false; this.renderer.render(this.scene, this.camera); }
    };
    requestAnimationFrame(loop);
    this.assets.onTextureLoad = () => this.requestRender();
  }

  requestRender() { this._needsRender = true; }

  resize() {
    const el = this.canvas.parentElement;
    const w = el.clientWidth, h = el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  // ------------------------------------------------------------ world
  clear() {
    for (const b of this.buckets.values()) { this.scene.remove(b.mesh); b.mesh.dispose(); }
    this.buckets.clear();
    this.entries.clear();
    this.requestRender();
  }

  load(world) {
    this.clear();
    this.world = world;
    for (const leaf of world.leaves()) this.addLeaf(leaf);
    const h = world.header;
    if (h.respawn?.p) {
      this.respawn.position.set(-h.respawn.p[0], h.respawn.p[1], h.respawn.p[2]);
      this.respawn.rotation.set(0, -(h.respawn.r || 0) * Math.PI / 180, 0);
      this.respawn.visible = true;
    } else this.respawn.visible = false;
    this.ocean.position.y = +h.oceanlevel || 0;
    this.animate = [...this.buckets.values()].some(b => b.material.userData.animated);
    this.requestRender();
  }

  bucketFor(geometry, matName) {
    const key = geometry.uuid + '|' + (matName || '');
    let b = this.buckets.get(key);
    if (!b) {
      b = new Bucket(this, geometry, this.assets.material(matName));
      this.buckets.set(key, b);
      if (b.material.userData.animated) this.animate = true;
    }
    return b;
  }

  addLeaf(node) {
    const list = [];
    for (const part of this.assets.parts(node.obj.n)) {
      const matName = part.proxy ? part.matName : (node.obj.m || part.matName);
      const e = { node, part, color: new THREE.Color(), selected: false };
      this.assets.tint(node.obj, matName, e.color);
      this.bucketFor(part.geometry, matName).add(e);
      list.push(e);
    }
    this.entries.set(node.id, list);
  }

  removeLeaf(node) {
    for (const e of this.entries.get(node.id) || []) e.bucket.remove(e);
    this.entries.delete(node.id);
    this.requestRender();
  }

  // transform/color changed (same type & material)
  updateLeaf(node) {
    for (const e of this.entries.get(node.id) || []) {
      const matName = e.part.proxy ? e.part.matName : (node.obj.m || e.part.matName);
      this.assets.tint(node.obj, matName, e.color);
      e.bucket.write(e);
    }
    this.requestRender();
  }

  // type or material changed
  rebuildLeaf(node) {
    const sel = this.entries.get(node.id)?.[0]?.selected;
    this.removeLeaf(node);
    node.updateMatrix();
    this.addLeaf(node);
    if (sel) this.setSelected(node, true);
    this.requestRender();
  }

  addNode(node) { for (const l of node.leaves()) { l.updateMatrix(); this.addLeaf(l); } }
  removeNode(node) { for (const l of node.leaves()) this.removeLeaf(l); }
  refreshNode(node) { for (const l of node.leaves()) this.updateLeaf(l); }

  isHiddenByAncestor(node) { let p = node.parent; while (p) { if (p.hidden) return true; p = p.parent; } return false; }

  setSelected(leaf, on) {
    for (const e of this.entries.get(leaf.id) || []) { e.selected = on; e.bucket.write(e); }
  }

  // ------------------------------------------------------------ bounds
  leafBox(leaf, target) {
    for (const e of this.entries.get(leaf.id) || []) {
      const g = e.part.geometry;
      if (!g.boundingBox) g.computeBoundingBox();
      _box.copy(g.boundingBox).applyMatrix4(e.part.matrix ? _m.multiplyMatrices(leaf.matrix, e.part.matrix) : leaf.matrix);
      target.union(_box);
    }
    return target;
  }
  boxOf(leaves) { const b = new THREE.Box3(); for (const l of leaves) this.leafBox(l, b); return b; }

  showSelectionBox(box) {
    this.selBox.visible = !!box && !box.isEmpty();
    if (this.selBox.visible) this.selBox.box.copy(box);
    this.requestRender();
  }

  frame(box, instant = false) {
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    const r = Math.max(0.5, box.getSize(_v).length() / 2);
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    if (dir.lengthSq() < 1e-6) dir.set(0, 0.5, 1).normalize();
    const dist = r / Math.sin((this.camera.fov * Math.PI / 180) / 2) * 0.9;
    this.controls.target.copy(c);
    this.camera.position.copy(c).addScaledVector(dir, dist);
    this.camera.near = Math.max(0.01, dist / 2000);
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.requestRender();
  }

  view(kind) {
    const t = this.controls.target, d = this.camera.position.distanceTo(t) || 50;
    // top: north (Unity +Z) up, Unity +X right
    const dirs = { top: [0, 1, -0.0001], bottom: [0, -1, -0.0001], front: [0, 0, -1], back: [0, 0, 1], left: [1, 0, 0], right: [-1, 0, 0] };
    // 'front' looks along Unity +Z (three +Z): camera sits at -Z
    const v = new THREE.Vector3(...dirs[kind]).normalize();
    this.camera.position.copy(t).addScaledVector(v, d);
    this.controls.update();
    this.requestRender();
  }

  // ------------------------------------------------------------ picking
  ndc(ev) {
    const r = this.canvas.getBoundingClientRect();
    return new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  }
  pick(ev) {
    this.raycaster.setFromCamera(this.ndc(ev), this.camera);
    const meshes = [];
    for (const b of this.buckets.values()) if (b.refs.length && b.material.name !== '__light' && b.material.name !== '__effect') meshes.push(b.mesh);
    const lights = [...this.buckets.values()].filter(b => b.refs.length && (b.material.name === '__light' || b.material.name === '__effect')).map(b => b.mesh);
    const hit = this.raycaster.intersectObjects(meshes, false)[0] || this.raycaster.intersectObjects(lights, false)[0];
    if (!hit) return null;
    const e = hit.object.userData.bucket.refs[hit.instanceId];
    return e ? { node: e.node, point: hit.point } : null;
  }
  // leaves whose center projects inside a screen rectangle (client coords)
  pickRect(x0, y0, x1, y1) {
    const r = this.canvas.getBoundingClientRect();
    const ax = Math.min(x0, x1), bx = Math.max(x0, x1), ay = Math.min(y0, y1), by = Math.max(y0, y1);
    const out = [];
    this.camera.updateMatrixWorld();
    for (const leaf of this.world.leaves()) {
      if (leaf.hidden || this.isHiddenByAncestor(leaf)) continue;
      _v.setFromMatrixPosition(leaf.matrix).project(this.camera);
      if (_v.z > 1 || _v.z < -1) continue;
      const sx = r.left + (_v.x + 1) / 2 * r.width, sy = r.top + (1 - _v.y) / 2 * r.height;
      if (sx >= ax && sx <= bx && sy >= ay && sy <= by) out.push(leaf);
    }
    return out;
  }
  // point on a horizontal plane under the cursor (for placing objects)
  groundPoint(ev, y = 0) {
    this.raycaster.setFromCamera(this.ndc(ev), this.camera);
    const p = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -y), p) ? p : null;
  }
}

function makeRespawnMarker() {
  const g = new THREE.Group();
  const mat = new THREE.MeshBasicMaterial({ color: 0x36d399, transparent: true, opacity: 0.85, depthTest: false });
  const body = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 1.8, 16).translate(0, 0.9, 0), mat);
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.25, 0.6, 12).rotateX(Math.PI / 2).translate(0, 1.2, 0.6), mat);
  g.add(body, arrow);
  g.renderOrder = 10;
  g.visible = false;
  return g;
}
