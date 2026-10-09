// Asset catalog (extracted from the local game install) -> three.js geometries/materials.
import * as THREE from 'three';
import { hasShape, isRound, shapeGeometry, unitSphere } from './shapes.js';

export class Assets {
  constructor() {
    this.catalog = null;
    this.geoms = new Map();      // `${mesh}:${slot}` -> BufferGeometry (shares attributes)
    this.materials = new Map();  // key -> THREE.Material
    this.textures = new Map();
    this.loader = new THREE.TextureLoader();
    this.time = { value: 0 };
    this.unitBox = new THREE.BoxGeometry(1, 1, 1);
    this.ready = false;
  }

  // full mode: meshes + textures extracted from a local game install
  async load(base = 'assets/') {
    this.base = base;
    const [cat, bin] = await Promise.all([
      fetch(base + 'catalog.json').then(r => { if (!r.ok) throw new Error('catalog.json missing'); return r.json(); }),
      fetch(base + 'meshes.bin').then(r => { if (!r.ok) throw new Error('meshes.bin missing'); return r.arrayBuffer(); }),
    ]);
    this.useCatalog(cat, bin, 'full');
  }

  // lite mode: no game files. Basic shapes are generated, everything else is a sized box.
  async loadLite(url = 'lite/catalog-lite.json') {
    const text = await fetch(url).then(r => { if (!r.ok) throw new Error('lite catalog missing'); return r.text(); });
    this.liteRaw = JSON.parse(text);          // untouched copy: game linking needs its part lists
    const cat = JSON.parse(text);
    for (const [name, o] of Object.entries(cat.objects)) Object.assign(o, { parts: [], proxy: !hasShape(name), collider: o.b });
    this.useCatalog(cat, null, 'lite');
  }

  // linked mode: meshes/textures read in the browser from the player's own game folder (gamelink.js)
  useLinked({ catalog, textures }) {
    this.useCatalog(catalog, null, 'linked');
    this.textureOverrides = textures;
  }

  useCatalog(cat, bin, mode) {
    this.catalog = cat;
    this.bin = bin;
    this.mode = mode;
    this.textureOverrides = null;
    this.geoms.clear(); this.materials.clear();
    this.objectNames = Object.keys(cat.objects).sort((a, b) => a.localeCompare(b));
    this.materialNames = Object.keys(cat.materials).sort((a, b) => a.localeCompare(b));
    this.ready = true;
  }

  object(name) { return this.catalog?.objects[name] || null; }
  // a plain building shape (its prefab material is the neutral 'primitive')
  isPrimitive(name) {
    const d = this.object(name);
    if (!d) return false;
    if (!d.parts.length) return hasShape(name);
    return d.parts.every(p => (p.mats || []).every(m => !m || m === 'primitive'));
  }

  // ----------------------------------------------------------- geometry
  _meshGeometry(id) {
    const key = 'm' + id;
    if (this.geoms.has(key)) return this.geoms.get(key);
    const m = this.catalog.meshes[id];
    const g = new THREE.BufferGeometry();
    // mesh data lives either in meshes.bin (desktop) or in memory (linked game, m.data)
    const arr = (key, n, T) => (m.data ? m.data[key] : m[key] >= 0 ? new T(this.bin, m[key], n) : null);
    const pos = arr('pos', m.v * 3, Float32Array), nrm = arr('nrm', m.v * 3, Float32Array), uv = arr('uv', m.v * 2, Float32Array);
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    if (nrm) g.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
    if (uv) g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setIndex(new THREE.BufferAttribute(arr('idx', m.i, Uint32Array), 1));
    if (!nrm) g.computeVertexNormals();
    g.computeBoundingBox(); g.computeBoundingSphere();
    this.geoms.set(key, g);
    return g;
  }

  // geometry restricted to one submesh (draw range over the shared index)
  geometry(meshId, slot) {
    const key = meshId + ':' + slot;
    if (this.geoms.has(key)) return this.geoms.get(key);
    const base = this._meshGeometry(meshId);
    const grp = this.catalog.meshes[meshId].groups[slot];
    let g = base;
    if (this.catalog.meshes[meshId].groups.length > 1 && grp) {
      g = new THREE.BufferGeometry();
      for (const k in base.attributes) g.setAttribute(k, base.attributes[k]);
      g.setIndex(base.index);
      g.setDrawRange(grp[0], grp[1]);
      g.boundingBox = base.boundingBox; g.boundingSphere = base.boundingSphere;
    }
    this.geoms.set(key, g);
    return g;
  }

  // Render parts for an object type: [{geometry, matName, matrix(local)|null, proxy}]
  parts(name) {
    const o = this.object(name);
    if (!o) return [{ geometry: this.unitBox, matName: '__unknown', matrix: null, proxy: true }];
    if (o._parts) return o._parts;
    const out = [];
    if (!o.parts.length) {    // no game mesh for it (website, or unreadable): generated shape if there is one
      const g = shapeGeometry(name);
      if (g) out.push({ geometry: g, matName: null, matrix: null, proxy: false });
      else if (isRound(name)) {
        const b = o.b || o.collider;
        out.push({ geometry: unitSphere(), matName: null, proxy: false,
          matrix: new THREE.Matrix4().compose(new THREE.Vector3(...b.c), new THREE.Quaternion(), new THREE.Vector3(...b.s)) });
      }
    }
    for (const p of o.parts) {
      const mat = new THREE.Matrix4().fromArray(p.m);
      const groups = this.catalog.meshes[p.mesh].groups;
      groups.forEach((g, slot) => out.push({
        geometry: this.geometry(p.mesh, slot),
        matName: p.mats[slot] ?? p.mats[p.mats.length - 1] ?? null,
        matrix: mat, proxy: false,
      }));
    }
    if (!out.length) {
      const c = o.collider || { c: [0, 0, 0], s: [1, 1, 1] };
      const mat = new THREE.Matrix4().compose(new THREE.Vector3(...c.c), new THREE.Quaternion(), new THREE.Vector3(...c.s.map(v => v || 0.05)));
      out.push({ geometry: this.unitBox, matName: o.kind === 'light' ? '__light' : o.kind === 'effect' ? '__effect' : '__proxy', matrix: mat, proxy: true });
    }
    o._parts = out;
    return out;
  }

  // ----------------------------------------------------------- textures
  texture(file, srgb = true) {
    if (!file) return null;
    if (this.textureOverrides?.has(file)) return this.textureOverrides.get(file);
    const key = file + (srgb ? '' : ':lin');
    if (this.textures.has(key)) return this.textures.get(key);
    const t = this.loader.load(this.base + 'tex/' + encodeURIComponent(file), () => this.onTextureLoad?.());
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    t.anisotropy = 4;
    this.textures.set(key, t);
    return t;
  }

  // ----------------------------------------------------------- materials
  // matName: material name from the world ('m') or prefab default. Returns a shared material.
  material(matName, { selectedTint = false } = {}) {
    const key = matName || '__default';
    if (this.materials.has(key)) return this.materials.get(key);
    const def = matName ? this.catalog?.materials[matName] : null;
    const m = this._makeMaterial(matName, def);
    // lite mode has no textures: use the texture's average colour as the base colour
    if (def?.avg && !m.map && !m.userData.triplanar && m.color && def.kind !== 'illum' && def.kind !== 'hologram') m.color.setRGB(...def.avg, THREE.SRGBColorSpace);
    m.name = key;
    this.materials.set(key, m);
    return m;
  }

  _makeMaterial(name, def) {
    if (name === '__proxy' || name === '__unknown')
      return new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.45, roughness: 0.8, depthWrite: false });
    if (name === '__light')
      return new THREE.MeshBasicMaterial({ color: 0xffe08a, wireframe: true });
    if (name === '__effect')
      return new THREE.MeshBasicMaterial({ color: 0xff8a3d, wireframe: true });
    if (name === 'discard')
      return new THREE.MeshBasicMaterial({ color: 0x88ccff, wireframe: true, transparent: true, opacity: 0.35 });
    if (!def) return new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.6 });

    const tex = def.tex || {}, til = def.tiling || {};
    const mainKey = tex._MainTex ? '_MainTex' : tex._BaseMap ? '_BaseMap' : null;
    const map = mainKey ? this.texture(tex[mainKey]) : null;
    const tiling = mainKey && til[mainKey] ? til[mainKey] : [1, 1, 0, 0];
    const gloss = def.gloss ?? 0.5, metal = def.metal ?? 0;

    switch (def.kind) {
      case 'illum': {
        const m = new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false });
        if (def.mode === 'rainbow') rainbow(m, this.time);
        return m;
      }
      case 'hologram': {
        const m = new THREE.MeshBasicMaterial({
          color: 0xffffff, map: this.texture(tex._MainTex1 || tex._MainTex2), transparent: true,
          blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false,
        });
        return m;
      }
      case 'unlit':
        return new THREE.MeshBasicMaterial({ color: 0xffffff });
      case 'water':
        return new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.6, roughness: 0.05, metalness: 0.1 });
      case 'glass':
        return new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: Math.max(0.02, 1 - gloss), metalness: Math.min(1, metal + 0.15), envMapIntensity: 1.2 });
      case 'transparent':
        return new THREE.MeshStandardMaterial({ color: 0xffffff, map, transparent: true, opacity: 0.5, depthWrite: false, roughness: 1 - gloss });
      case 'triplanar': {
        const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: Math.min(1, Math.max(0.04, 1 - gloss * 0.85)), metalness: metal });
        if (map) triplanar(m, map, tiling);
        return m;
      }
      default: {
        const m = new THREE.MeshStandardMaterial({ color: 0xffffff, map, roughness: Math.min(1, Math.max(0.05, 1 - gloss)), metalness: metal });
        if (map) { map.repeat.set(tiling[0] || 1, tiling[1] || 1); map.offset.set(tiling[2] || 0, tiling[3] || 0); }
        if (map && /png$/i.test(tex[mainKey])) { m.alphaTest = 0.5; m.side = THREE.DoubleSide; }
        return m;
      }
    }
  }

  // tint for an object: world 'c' color if present, else the material's own color
  tint(obj, matName, out) {
    const c = obj.c;
    if (c) return out.setRGB(c[0], c[1], c[2], THREE.SRGBColorSpace);
    const def = matName && this.catalog?.materials[matName];
    if (def && def.kind !== 'standard') return out.setRGB(def.color[0], def.color[1], def.color[2], THREE.SRGBColorSpace);
    return out.setRGB(1, 1, 1);
  }
}

// World-space triplanar mapping (matches 3DX "Triplanar" shaders), instancing-aware.
function triplanar(mat, map, tiling) {
  mat.userData.triplanar = true;
  mat.onBeforeCompile = sh => {
    sh.uniforms.tpMap = { value: map };
    sh.uniforms.tpScale = { value: new THREE.Vector2(tiling[0] || 1, tiling[1] || 1) };
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vTpPos;\nvarying vec3 vTpNrm;')
      .replace('#include <worldpos_vertex>', `#include <worldpos_vertex>
        vec4 tpW = vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
          tpW = instanceMatrix * tpW;
        #endif
        tpW = modelMatrix * tpW;
        vTpPos = tpW.xyz;
        vec3 tpN = objectNormal;
        #ifdef USE_INSTANCING
          tpN = mat3(instanceMatrix) * tpN;
        #endif
        vTpNrm = normalize(mat3(modelMatrix) * tpN);`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform sampler2D tpMap;\nuniform vec2 tpScale;\nvarying vec3 vTpPos;\nvarying vec3 vTpNrm;')
      .replace('#include <map_fragment>', `
        vec3 tpB = pow(abs(normalize(vTpNrm)), vec3(4.0));
        tpB /= (tpB.x + tpB.y + tpB.z + 1e-5);
        vec4 tx = texture2D(tpMap, vTpPos.zy * tpScale);
        vec4 ty = texture2D(tpMap, vTpPos.xz * tpScale);
        vec4 tz = texture2D(tpMap, vTpPos.xy * tpScale);
        diffuseColor *= tx * tpB.x + ty * tpB.y + tz * tpB.z;`);
  };
  mat.customProgramCacheKey = () => 'triplanar';
}

function rainbow(mat, time) {
  mat.onBeforeCompile = sh => {
    sh.uniforms.uTime = time;
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vRbPos;')
      .replace('#include <worldpos_vertex>', `#include <worldpos_vertex>
        vec4 rbW = vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
          rbW = instanceMatrix * rbW;
        #endif
        vRbPos = (modelMatrix * rbW).xyz;`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uTime;\nvarying vec3 vRbPos;')
      .replace('#include <color_fragment>', `#include <color_fragment>
        float h = fract(uTime * 0.15 + (vRbPos.x + vRbPos.y + vRbPos.z) * 0.05);
        diffuseColor.rgb *= clamp(abs(mod(h * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);`);
  };
  mat.customProgramCacheKey = () => 'rainbow';
  mat.userData.animated = true;
}
