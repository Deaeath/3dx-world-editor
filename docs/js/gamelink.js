// "Link your game": read the real meshes and textures from the player's own
// 3DXChat folder, in the browser. Files are read locally with the File API and
// never uploaded. The lite catalog says which mesh/texture (by name and size)
// each object and material uses.
import * as THREE from 'three';
import { openSerializedFile, readNames, buildTree, readObject, decodeMesh, TEX_FORMATS, textureData } from './unity/unityfile.js';

// ------------------------------------------------------------ picking the folder
const DB = 'we-gamelink';
function idb(mode, fn) {
  return new Promise((res, rej) => {
    const open = indexedDB.open(DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore('kv');
    open.onerror = () => rej(open.error);
    open.onsuccess = () => {
      const tx = open.result.transaction('kv', mode), st = tx.objectStore('kv');
      const r = fn(st);
      tx.oncomplete = () => res(r?.result);
      tx.onerror = () => rej(tx.error);
    };
  });
}
export async function rememberedFolder() {
  try { return (await idb('readonly', st => st.get('dir'))) || null; } catch { return null; }
}
async function remember(dir) { try { await idb('readwrite', st => st.put(dir, 'dir')); } catch { /* storage blocked */ } }

async function findInHandle(dir) {
  const routes = [[], ['3DXChat_Data'], ['Game', '3DXChat_Data'], ['3DXChat', 'Game', '3DXChat_Data']];
  for (const route of routes) {
    try {
      let d = dir;
      for (const part of route) d = await d.getDirectoryHandle(part);
      const assets = await (await d.getFileHandle('resources.assets')).getFile();
      let resS = null;
      try { resS = await (await d.getFileHandle('resources.assets.resS')).getFile(); } catch { /* optional */ }
      return { assets, resS };
    } catch { /* try the next layout */ }
  }
  return null;
}

// returns { assets: File, resS: File|null } or null if cancelled; throws if the folder is wrong
export async function pickGameFiles({ useRemembered = false } = {}) {
  if ('showDirectoryPicker' in window) {
    let dir = useRemembered ? await rememberedFolder() : null;
    try {
      if (dir && (await dir.requestPermission({ mode: 'read' })) !== 'granted') dir = null;
      if (!dir) dir = await window.showDirectoryPicker({ id: '3dxchat-game', mode: 'read' });
    } catch (e) {
      if (e.name === 'AbortError') return null;
      dir = null;                     // not allowed here (e.g. inside another site's frame): use the file input
    }
    if (dir) {
      const found = await findInHandle(dir);
      if (!found) throw new Error(`"${dir.name}" doesn't contain 3DXChat_Data\\resources.assets. Pick your 3DXChat "Game" folder.`);
      remember(dir);
      return found;
    }
  }
  // fallback: folder upload input. Browsers word this as "upload", but the files stay on this PC.
  const files = await new Promise(resolve => {
    const i = document.createElement('input');
    i.type = 'file'; i.webkitdirectory = true;
    i.onchange = () => resolve([...i.files]);
    i.oncancel = () => resolve(null);
    i.click();
  });
  if (!files) return null;
  const by = suffix => files.find(f => (f.webkitRelativePath || f.name).replace(/\\/g, '/').endsWith(suffix));
  const assets = by('3DXChat_Data/resources.assets') || by('/resources.assets') || files.find(f => f.name === 'resources.assets');
  if (!assets) throw new Error('That folder has no 3DXChat_Data\\resources.assets. Pick the 3DXChat_Data folder inside your 3DXChat "Game" folder.');
  return { assets, resS: by('3DXChat_Data/resources.assets.resS') || files.find(f => f.name === 'resources.assets.resS') || null };
}

// ------------------------------------------------------------ reading the game
export async function linkGame(files, lite, renderer, log = () => {}) {
  const t0 = performance.now();
  const trees = await fetch('js/unity/typetrees.json').then(r => r.json());
  const meshTree = buildTree(trees.Mesh), texTree = buildTree(trees.Texture2D);
  log(`Reading ${files.assets.name} (${(files.assets.size / 1048576).toFixed(0)} MB)...`);
  const sf = await openSerializedFile(files.assets);
  log(`Unity ${sf.unityVersion}, ${sf.objects.length.toLocaleString()} objects`);

  // meshes: match by name, confirm by vertex count
  const meshObjs = sf.objects.filter(o => o.classID === 43);
  const meshNames = await readNames(sf, meshObjs, p => log(`Indexing meshes ${Math.round(p * 100)}%`, true));
  const byName = new Map();
  meshObjs.forEach((o, i) => { const n = meshNames[i]; if (!byName.has(n)) byName.set(n, []); byName.get(n).push(o); });
  const meshes = new Array(lite.meshes.length).fill(null);
  let done = 0, skipped = 0;
  for (let i = 0; i < lite.meshes.length; i++) {
    const [name, v] = lite.meshes[i];
    for (const o of byName.get(name) || []) {
      try {
        const m = await readObject(sf, o, meshTree);
        const count = m.m_MeshCompression ? Math.floor(m.m_CompressedMesh.m_Vertices.m_NumItems / 3) : m.m_VertexData?.m_VertexCount;
        if (count !== v) continue;
        meshes[i] = await decodeMesh(sf, files.resS, m);
        if (meshes[i]) break;
      } catch (e) { console.warn('mesh', name, e); }
    }
    if (meshes[i]) done++; else skipped++;
    if (i % 20 === 0) log(`Meshes ${i + 1}/${lite.meshes.length}`, true);
  }
  log(`Meshes: ${done} read${skipped ? `, ${skipped} not readable (kept as basic shapes)` : ''}`);

  // textures: match by name + size + format; only formats the GPU can take directly
  const ext = name => renderer.extensions.has(name);
  const canUse = { s3tc: ext('WEBGL_compressed_texture_s3tc'), bptc: ext('EXT_texture_compression_bptc'), rgtc: ext('EXT_texture_compression_rgtc') };
  const wanted = new Map();   // name -> [{mat, key, meta}]
  for (const [mat, def] of Object.entries(lite.materials)) {
    for (const [key, meta] of Object.entries(def.tm || {})) {
      const f = TEX_FORMATS[meta.fmt];
      if (!f || (f.ext && !canUse[f.ext])) continue;
      if (!wanted.has(meta.name)) wanted.set(meta.name, []);
      wanted.get(meta.name).push({ mat, key, meta });
    }
  }
  const textures = new Map(), texFiles = {};
  if (wanted.size) {
    const texObjs = sf.objects.filter(o => o.classID === 28);
    const texNames = await readNames(sf, texObjs, p => log(`Indexing textures ${Math.round(p * 100)}%`, true));
    const made = new Map();
    let k = 0;
    for (let i = 0; i < texObjs.length; i++) {
      const uses = wanted.get(texNames[i]);
      if (!uses) continue;
      try {
        const t = await readObject(sf, texObjs[i], texTree);
        for (const u of uses) {
          if (t.m_Width !== u.meta.w || t.m_Height !== u.meta.h || t.m_TextureFormat !== u.meta.fmt) continue;
          const id = `${texNames[i]}#${t.m_Width}x${t.m_Height}`;
          if (!made.has(id)) {
            const data = await textureData(files.resS, t);
            made.set(id, data ? makeTexture(TEX_FORMATS[t.m_TextureFormat], t.m_Width, t.m_Height, t.m_MipCount || 1, data, u.key) : null);
            if (++k % 10 === 0) log(`Textures ${k}`, true);
          }
          const tex = made.get(id);
          if (tex) { const file = `link:${id}`; textures.set(file, tex); (texFiles[u.mat] ||= {})[u.key] = file; }
        }
      } catch (e) { console.warn('texture', texNames[i], e); }
    }
    log(`Textures: ${[...made.values()].filter(Boolean).length} read (game textures with "crunched" compression keep their average colour)`);
  }

  // a full catalog the renderer already understands
  const catMeshes = [], remap = new Map();
  const objects = {};
  for (const [name, o] of Object.entries(lite.objects)) {
    let parts = [];
    if (o.parts?.length && o.parts.every(p => meshes[p.mesh])) {
      parts = o.parts.map(p => {
        if (!remap.has(p.mesh)) {
          const m = meshes[p.mesh];
          remap.set(p.mesh, catMeshes.length);
          catMeshes.push({ name: m.name, v: m.v, i: m.i, groups: m.groups, box: m.box, data: m });
        }
        return { mesh: remap.get(p.mesh), m: p.m, mats: p.mats };
      });
    }
    objects[name] = { kind: o.kind, parts, collider: o.b, b: o.b, proxy: !parts.length };
  }
  const materials = {};
  for (const [name, def] of Object.entries(lite.materials)) {
    const tex = texFiles[name] || {};
    const tiling = Object.fromEntries(Object.keys(tex).map(k => [k, def.tm[k].til]));
    materials[name] = { ...def, tex, tiling };
  }
  log(`Linked in ${((performance.now() - t0) / 1000).toFixed(1)} s`);
  return { catalog: { version: 2, linked: true, objects, materials, meshes: catMeshes }, textures };
}

function makeTexture(f, w, h, mips, data, key) {
  let tex;
  if (f.kind === 'block') {
    const levels = [];
    let off = 0, mw = w, mh = h;
    for (let i = 0; i < mips; i++) {
      const size = Math.max(1, Math.ceil(mw / 4)) * Math.max(1, Math.ceil(mh / 4)) * f.block;
      if (off + size > data.length) break;
      levels.push({ data: data.subarray(off, off + size), width: mw, height: mh });
      off += size; mw = Math.max(1, mw >> 1); mh = Math.max(1, mh >> 1);
    }
    if (!levels.length) return null;
    const full = levels.length === Math.floor(Math.log2(Math.max(w, h))) + 1;
    tex = new THREE.CompressedTexture(full ? levels : [levels[0]], w, h, THREE[f.gl]);
    tex.minFilter = full ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
  } else {
    let px = data.subarray(0, w * h * (f.kind === 'rgb24' ? 3 : 4));
    if (f.kind === 'rgb24') {
      const out = new Uint8Array(w * h * 4);
      for (let i = 0, j = 0; i < w * h; i++) { out[j++] = px[i * 3]; out[j++] = px[i * 3 + 1]; out[j++] = px[i * 3 + 2]; out[j++] = 255; }
      px = out;
    }
    tex = new THREE.DataTexture(px, w, h, THREE.RGBAFormat);
    tex.generateMipmaps = true;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
  }
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.magFilter = THREE.LinearFilter;
  tex.anisotropy = 4;
  tex.colorSpace = f.gl === 'RED_RGTC1_Format' || key === '_BumpMap' ? THREE.NoColorSpace : THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}
