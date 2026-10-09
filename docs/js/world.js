// World model: .world JSON <-> editable node tree, Unity <-> three.js transforms.
import * as THREE from 'three';

const D2R = Math.PI / 180, R2D = 180 / Math.PI;
const _e = new THREE.Euler(), _q = new THREE.Quaternion(), _m = new THREE.Matrix4();
const _p = new THREE.Vector3(), _s = new THREE.Vector3();

// Unity is left-handed; we mirror X to get three.js (right-handed) space.
export function unityToMatrix(p, r, s, out = new THREE.Matrix4()) {
  p = p || [0, 0, 0]; r = r || [0, 0, 0]; s = s || [1, 1, 1];
  _e.set(r[0] * D2R, r[1] * D2R, r[2] * D2R, 'YXZ');      // Unity Euler = Ry * Rx * Rz
  _q.setFromEuler(_e);
  _q.set(_q.x, -_q.y, -_q.z, _q.w);                          // mirror X
  _p.set(-p[0], p[1], p[2]);
  _s.set(s[0], s[1], s[2]);
  return out.compose(_p, _q, _s);
}

export function matrixToUnity(m) {
  m.decompose(_p, _q, _s);
  _q.set(_q.x, -_q.y, -_q.z, _q.w);
  _e.setFromQuaternion(_q, 'YXZ');
  const norm = a => { a = a * R2D % 360; if (a < 0) a += 360; return Math.abs(a - 360) < 1e-4 || Math.abs(a) < 1e-4 ? 0 : a; };
  return {
    p: [-_p.x, _p.y, _p.z],
    r: [norm(_e.x), norm(_e.y), norm(_e.z)],
    s: [_s.x, _s.y, _s.z],
  };
}

export function unityPosToThree(p) { return new THREE.Vector3(-p[0], p[1], p[2]); }
export function threePosToUnity(v) { return [-v.x, v.y, v.z]; }

// ---------------------------------------------------------------- nodes
let nextId = 1;

export class Node {
  constructor(obj, parent = null) {
    this.id = nextId++;
    this.obj = obj;            // the JSON object (kept for unknown keys), without 'objects'
    this.parent = parent;
    this.children = obj.objects ? [] : null;
    this.hidden = false;
    this.expanded = false;
    this.matrix = null;        // leaves: cached three.js world matrix
  }
  get isGroup() { return this.children !== null; }
  get name() { return this.obj.n; }
  updateMatrix() { if (!this.isGroup) this.matrix = unityToMatrix(this.obj.p, this.obj.r, this.obj.s, this.matrix || new THREE.Matrix4()); }
  *leaves() {
    if (!this.isGroup) { yield this; return; }
    for (const c of this.children) yield* c.leaves();
  }
  *walk() { yield this; if (this.isGroup) for (const c of this.children) yield* c.walk(); }
  depth() { let d = 0, n = this.parent; while (n && n.parent) { d++; n = n.parent; } return d; }
  topAncestor(root) { let n = this; while (n.parent && n.parent !== root) n = n.parent; return n; }
}

function build(obj, parent) {
  const { objects, ...rest } = obj;
  const node = new Node(objects ? { ...rest, objects: true } : rest, parent);
  if (objects) for (const o of objects) node.children.push(build(o, node));
  else node.updateMatrix();
  return node;
}

export class World {
  constructor(json, path = null) {
    const { objects = [], ...header } = json;
    this.header = header;
    this.path = path;
    this.root = new Node({ n: '(world)', objects: true }, null);
    for (const o of objects) this.root.children.push(build(o, this.root));
    this.dirty = false;
  }
  static parse(text, path) {
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    return new World(JSON.parse(text), path);
  }
  *leaves() { yield* this.root.leaves(); }
  count() { let n = 0; for (const _ of this.leaves()) n++; return n; }

  toJSON() {
    const out = { ...this.header };
    out.objects = this.root.children.map(serializeNode);
    // keep the game's key order: header fields first, then objects
    return out;
  }
  stringify() { return stringifyWorld(this.toJSON()); }
}

export function serializeNode(node) {
  if (node.isGroup) {
    const { objects, ...rest } = node.obj;
    return { ...rest, objects: node.children.map(serializeNode) };
  }
  return { ...node.obj };
}

export function nodeFromJSON(json, parent) { return build(json, parent); }

// ----------------------------------------------------------- serializer
// Matches the game's compact style: no whitespace, floats always carry a decimal
// point (1.0, not 1), and values we computed are rounded to float precision.
function num(v) {
  if (!Number.isFinite(v)) v = 0;
  if (Number.isInteger(v)) return v.toFixed(1);
  let s = String(v);
  if (s.length > 12) s = String(parseFloat(v.toPrecision(9)));
  if (/e/i.test(s)) s = s.replace(/e/, 'E');
  if (!/[.E]/.test(s)) s += '.0';
  return s;
}
export function stringifyWorld(value) {
  const parts = [];
  const write = v => {
    if (v === null || v === undefined) parts.push('null');
    else if (typeof v === 'number') parts.push(num(v));
    else if (typeof v === 'string' || typeof v === 'boolean') parts.push(JSON.stringify(v));
    else if (Array.isArray(v)) { parts.push('['); v.forEach((x, i) => { if (i) parts.push(','); write(x); }); parts.push(']'); }
    else {
      parts.push('{'); let first = true;
      for (const k in v) { if (v[k] === undefined) continue; if (!first) parts.push(','); first = false; parts.push(JSON.stringify(k), ':'); write(v[k]); }
      parts.push('}');
    }
  };
  write(value);
  return parts.join('');
}

// round computed transform values to ~float32 precision for tidy output
export const tidy = a => a.map(v => parseFloat((+v).toPrecision(8)));
