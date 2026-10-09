// Generated stand-ins for 3DXChat's basic building shapes, used when no game is
// linked. Built in Unity space (left-handed, Z = the shape's "height" axis,
// world-editor pivots), then mirrored on X into three.js space like the real meshes.
import * as THREE from 'three';

const MIRROR = new THREE.Matrix4().makeScale(-1, 1, 1);

// profile drawn in Unity XZ (u = x, v = z), extruded along Unity Y over [y0, y0 + depth]
function extrudeXZ(shape, y0 = -0.5, depth = 1, curveSegments = 16) {
  const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments });
  // (u, v, w) -> (x = u, y = w + y0, z = v): an axis swap, so the winding flips too
  g.applyMatrix4(new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, y0, 0, 1, 0, 0, 0, 0, 0, 1));
  return flipWinding(g);
}
function quarterRing(cx, rIn, rOut, y0 = -0.5) {
  const s = new THREE.Shape();
  s.moveTo(cx + rOut, 0);
  s.absarc(cx, 0, rOut, 0, Math.PI / 2, false);
  s.lineTo(cx, rIn);
  if (rIn > 0) s.absarc(cx, 0, rIn, Math.PI / 2, 0, true);
  else s.lineTo(cx, 0);
  s.closePath();
  return extrudeXZ(s, y0, 1, 24);
}
// three primitives are Y-up; rotate so their axis is Unity Z and sit them on z = 0
const yToZ = (g, z0) => g.rotateX(Math.PI / 2).translate(0, 0, z0);

const GEN = {
  box: () => new THREE.BoxGeometry(1, 1, 1).translate(0, 0, 0.5),
  cylinder: () => yToZ(new THREE.CylinderGeometry(0.5, 0.5, 1, 32), 0.5),
  tube: () => {
    const s = new THREE.Shape().absarc(0, 0, 0.5, 0, Math.PI * 2);
    s.holes.push(new THREE.Path().absarc(0, 0, 0.4, 0, Math.PI * 2, true));
    return new THREE.ExtrudeGeometry(s, { depth: 1, bevelEnabled: false, curveSegments: 32 });
  },
  sphere: () => new THREE.SphereGeometry(0.5, 32, 16).translate(0, 0, 0.5),
  cone: () => yToZ(new THREE.ConeGeometry(0.5, 1, 32), 0.5),
  cone1: () => yToZ(new THREE.ConeGeometry(0.5, 0.5, 32), 0.25),
  pyramid: () => yToZ(new THREE.ConeGeometry(Math.SQRT1_2, 1, 4).rotateY(Math.PI / 4), 0.5),
  prism: () => extrudeXZ(new THREE.Shape([new THREE.Vector2(-0.5, 0), new THREE.Vector2(0.5, 0), new THREE.Vector2(0, 1)])),
  prism1: () => extrudeXZ(new THREE.Shape([new THREE.Vector2(0, 0), new THREE.Vector2(1, 0), new THREE.Vector2(0, 1)])),
  quarter: () => quarterRing(-0.5, 0, 1),
  ring2: () => quarterRing(-1.5, 1, 2),
  ring3: () => quarterRing(-2.5, 2, 3),
  ring4: () => quarterRing(-3.5, 3, 4, -1),
  arc: () => {
    const s = new THREE.Shape();
    s.moveTo(-0.5, 0); s.lineTo(-0.45, 0);
    s.absarc(0, 0, 0.45, Math.PI, 0, true);
    s.lineTo(0.5, 0); s.lineTo(0.5, 0.5); s.lineTo(-0.5, 0.5); s.closePath();
    return extrudeXZ(s, -0.5, 1, 24);
  },
  // quarter torus: centre-line radius 2 around (x = -2, z = 0), tube radius 0.5
  torusq2: () => flipWinding(new THREE.TorusGeometry(2, 0.5, 16, 32, Math.PI / 2)
    .applyMatrix4(new THREE.Matrix4().set(1, 0, 0, -2, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1))),
};

const BY_NAME = {
  Box: 'box', BoxCh: 'box', BoxCh1: 'box', BoxSoft1: 'box',
  Cylinder: 'cylinder', Cylinder2: 'cylinder', Tube: 'tube', Sphere: 'sphere',
  Cone: 'cone', Cone1: 'cone1', Pyramid: 'pyramid', Prism: 'prism', Prism1: 'prism1',
  SemiArch1: 'quarter', SemiArch11: 'quarter', SemiArch2: 'ring2', SemiArch3: 'ring3', SemiArch4: 'ring4',
  Arc: 'arc', TorusQ2: 'torusq2',
};
// rounded objects without a generator: an ellipsoid filling their bounds looks closer than a box
const ROUND = /^(Egg\d*|EggHalf|Hemisphere|Heart|Dish\d*)$/;

// after any mirroring transform: reverse triangle winding so faces stay outward
function flipWinding(g) {
  const idx = g.index;
  if (idx) { const a = idx.array; for (let i = 0; i < a.length; i += 3) { const t = a[i + 1]; a[i + 1] = a[i + 2]; a[i + 2] = t; } }
  else for (const k in g.attributes) {
    const at = g.attributes[k], n = at.itemSize, a = at.array;
    for (let i = 0; i < at.count; i += 3) for (let j = 0; j < n; j++) { const t = a[(i + 1) * n + j]; a[(i + 1) * n + j] = a[(i + 2) * n + j]; a[(i + 2) * n + j] = t; }
  }
  return g;
}

const cache = new Map();
function finish(g) {
  flipWinding(g.applyMatrix4(MIRROR));
  g.computeBoundingBox(); g.computeBoundingSphere();
  return g;
}

export function hasShape(name) { return name in BY_NAME; }
export function isRound(name) { return ROUND.test(name); }

export function shapeGeometry(name) {
  const key = BY_NAME[name];
  if (!key) return null;
  if (!cache.has(key)) cache.set(key, finish(GEN[key]()));
  return cache.get(key);
}

let sphere = null;
export function unitSphere() { return sphere || (sphere = new THREE.SphereGeometry(0.5, 20, 12)); }
