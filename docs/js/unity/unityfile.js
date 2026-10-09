// Minimal reader for Unity 2021.3 player data (SerializedFile v22): the object
// table, a generic type-tree reader (layouts from UnityPy's database, see
// typetrees.json), and Mesh / Texture2D decoding. Reads straight from File
// objects the player picked; nothing is uploaded anywhere.

export class Bin {
  constructor(buf, le = true) { this.v = new DataView(buf); this.b = new Uint8Array(buf); this.p = 0; this.le = le; }
  get len() { return this.b.length; }
  u8() { return this.v.getUint8(this.p++); }
  i8() { return this.v.getInt8(this.p++); }
  u16() { const x = this.v.getUint16(this.p, this.le); this.p += 2; return x; }
  i16() { const x = this.v.getInt16(this.p, this.le); this.p += 2; return x; }
  u32() { const x = this.v.getUint32(this.p, this.le); this.p += 4; return x; }
  i32() { const x = this.v.getInt32(this.p, this.le); this.p += 4; return x; }
  i64() { const x = this.v.getBigInt64(this.p, this.le); this.p += 8; return Number(x); }
  u64() { const x = this.v.getBigUint64(this.p, this.le); this.p += 8; return Number(x); }
  f32() { const x = this.v.getFloat32(this.p, this.le); this.p += 4; return x; }
  f64() { const x = this.v.getFloat64(this.p, this.le); this.p += 8; return x; }
  bytes(n) { const x = this.b.subarray(this.p, this.p + n); this.p += n; return x; }
  align(n = 4) { this.p = (this.p + n - 1) & ~(n - 1); }
  cstr() { let e = this.p; while (this.b[e]) e++; const s = new TextDecoder().decode(this.b.subarray(this.p, e)); this.p = e + 1; return s; }
}

const readSlice = async (file, start, end) => new Uint8Array(await file.slice(start, end).arrayBuffer()).buffer;

// ------------------------------------------------------------------ object table
export async function openSerializedFile(file) {
  let h = new Bin(await readSlice(file, 0, 64), false);              // header is big-endian
  let metaSize = h.u32(); h.u32(); const version = h.u32(); let dataOffset = h.u32();
  if (version < 22) throw new Error(`Unsupported Unity file version ${version} (expected 22+)`);
  const bigEndian = h.u8() !== 0; h.p += 3;
  metaSize = h.u32(); h.i64(); dataOffset = h.i64(); h.i64();
  const metaStart = h.p;
  const r = new Bin(await readSlice(file, 0, metaStart + metaSize), !bigEndian);
  r.p = metaStart;
  const unityVersion = r.cstr();
  r.i32();                                   // target platform
  const typeTree = r.u8() !== 0;
  if (typeTree) throw new Error('This game build stores type trees; not supported by the web reader yet');
  const types = [];
  for (let i = 0, n = r.i32(); i < n; i++) {
    const classID = r.i32(); r.u8(); const scriptIndex = r.i16();
    if (classID === 114) r.p += 16;          // script id
    r.p += 16;                               // old type hash
    types.push({ classID, scriptIndex });
  }
  const objects = [];
  for (let i = 0, n = r.i32(); i < n; i++) {
    r.align(4);
    const pathID = r.i64(), start = r.i64() + dataOffset, size = r.u32(), typeIndex = r.i32();
    objects.push({ pathID, start, size, classID: types[typeIndex]?.classID });
  }
  return { file, version, unityVersion, objects, le: !bigEndian };
}

// m_Name is the first field of every NamedObject (Mesh, Texture2D, ...)
export async function readNames(sf, objs, onProgress) {
  const out = new Array(objs.length);
  const B = 48;
  for (let i = 0; i < objs.length; i += B) {
    await Promise.all(objs.slice(i, i + B).map(async (o, k) => {
      const buf = await readSlice(sf.file, o.start, o.start + Math.min(o.size, 260));
      const r = new Bin(buf, sf.le);
      const n = r.i32();
      out[i + k] = n > 0 && n <= r.len - 4 ? new TextDecoder().decode(r.bytes(n)) : '';
    }));
    onProgress?.(Math.min(1, (i + B) / objs.length));
  }
  return out;
}

// ------------------------------------------------------------------ type trees
export function buildTree(rows) {
  const root = { level: rows[0][0], type: rows[0][1], name: rows[0][2], size: rows[0][3], flag: rows[0][4], children: [] };
  const stack = [root];
  for (let i = 1; i < rows.length; i++) {
    const [level, type, name, size, flag] = rows[i];
    const node = { level, type, name, size, flag, children: [] };
    while (stack[stack.length - 1].level >= level) stack.pop();
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  }
  return root;
}

const ALIGN = 0x4000;
const PRIM = {
  SInt8: r => r.i8(), UInt8: r => r.u8(), char: r => r.u8(), bool: r => r.u8() !== 0,
  short: r => r.i16(), SInt16: r => r.i16(), 'unsigned short': r => r.u16(), UInt16: r => r.u16(),
  int: r => r.i32(), SInt32: r => r.i32(), 'unsigned int': r => r.u32(), UInt32: r => r.u32(), 'Type*': r => r.u32(),
  'long long': r => r.i64(), SInt64: r => r.i64(), 'unsigned long long': r => r.u64(), UInt64: r => r.u64(), FileSize: r => r.u64(),
  float: r => r.f32(), double: r => r.f64(),
};

export function readTree(node, r) {
  let align = (node.flag & ALIGN) !== 0, v;
  const prim = PRIM[node.type];
  if (prim) v = prim(r);
  else if (node.type === 'string') { const n = r.i32(); v = new TextDecoder().decode(r.bytes(n)); align = true; }
  else if (node.type === 'TypelessData') v = r.bytes(r.i32());
  else if (node.type === 'pair') v = [readTree(node.children[0], r), readTree(node.children[1], r)];
  else if (node.children.length && node.children[0].type === 'Array') {
    if (node.children[0].flag & ALIGN) align = true;
    const n = r.i32();
    if (n < 0 || n > 1e8) throw new Error('Bad array length ' + n);
    const sub = node.children[0].children[1];
    if (sub.type === 'UInt8' || sub.type === 'char') v = r.bytes(n);
    else { v = new Array(n); for (let i = 0; i < n; i++) v[i] = readTree(sub, r); }
  } else {
    v = {};
    for (const c of node.children) v[c.name] = readTree(c, r);
  }
  if (align) r.align(4);
  return v;
}

export async function readObject(sf, obj, tree) {
  const r = new Bin(await readSlice(sf.file, obj.start, obj.start + obj.size), sf.le);
  return readTree(tree, r);
}

// ------------------------------------------------------------------ Mesh
const FMT_SIZE = [4, 2, 1, 1, 2, 2, 1, 1, 2, 2, 4, 4];   // VertexFormat (2019+)
function readComp(dv, off, fmt) {
  switch (fmt) {
    case 0: return dv.getFloat32(off, true);
    case 1: return half(dv.getUint16(off, true));
    case 2: return dv.getUint8(off) / 255;
    case 3: return Math.max(dv.getInt8(off) / 127, -1);
    case 4: return dv.getUint16(off, true) / 65535;
    case 5: return Math.max(dv.getInt16(off, true) / 32767, -1);
    case 6: return dv.getUint8(off);
    case 7: return dv.getInt8(off);
    case 8: return dv.getUint16(off, true);
    case 9: return dv.getInt16(off, true);
    case 10: return dv.getUint32(off, true);
    case 11: return dv.getInt32(off, true);
  }
  return 0;
}
function half(h) {
  const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 0x1f, f = h & 0x3ff;
  if (e === 0) return s * f * 2 ** -24;
  if (e === 31) return f ? NaN : s * Infinity;
  return s * (1 + f / 1024) * 2 ** (e - 15);
}

// -> { v, i, pos: Float32Array, nrm|null, uv|null, idx: Uint32Array, groups: [[start, count, slot]], box }
// in three.js space (X mirrored, winding reversed), matching extract_assets.py.
// PackedBitVector -> ints / floats (Unity's compressed mesh storage)
function unpackInts(pv, start = 0, count = pv.m_NumItems) {
  const bitSize = pv.m_BitSize, data = pv.m_Data, out = new Uint32Array(count);
  let bitPos = bitSize * start, idx = bitPos >> 3;
  bitPos &= 7;
  for (let i = 0; i < count; i++) {
    let bits = 0, value = 0;
    while (bits < bitSize) {
      value |= (data[idx] >> bitPos) << bits;
      const num = Math.min(bitSize - bits, 8 - bitPos);
      bitPos += num; bits += num;
      if (bitPos === 8) { idx++; bitPos = 0; }
    }
    out[i] = (bitSize >= 32 ? value : value & ((1 << bitSize) - 1)) >>> 0;
  }
  return out;
}
function unpackFloats(pv, start = 0, count = pv.m_NumItems) {
  const out = new Float32Array(count);
  if (!pv.m_BitSize) { out.fill(pv.m_Start); return out; }
  const q = unpackInts(pv, start, count), scale = pv.m_Range / (2 ** pv.m_BitSize - 1);
  for (let i = 0; i < count; i++) out[i] = q[i] * scale + pv.m_Start;
  return out;
}

function decodeCompressed(m) {
  const cm = m.m_CompressedMesh, n = Math.floor(cm.m_Vertices.m_NumItems / 3);
  if (!n) return null;
  const pos = unpackFloats(cm.m_Vertices, 0, n * 3);
  let uv = null;
  if (cm.m_UV.m_NumItems > 0) {
    const info = cm.m_UVInfo;
    if (info) {
      let off = 0;
      for (let ch = 0; ch < 8 && !uv; ch++) {
        const bits = (info >> (ch * 4)) & 15;
        if (!(bits & 4)) continue;
        const dim = 1 + (bits & 3);
        const all = unpackFloats(cm.m_UV, off, n * dim);
        if (ch === 0 && dim >= 2) { uv = new Float32Array(n * 2); for (let i = 0; i < n; i++) { uv[i * 2] = all[i * dim]; uv[i * 2 + 1] = all[i * dim + 1]; } }
        off = dim * n;
      }
    } else uv = unpackFloats(cm.m_UV, 0, n * 2);
  }
  let nrm = null;
  if (cm.m_Normals.m_NumItems > 0) {
    const nd = unpackFloats(cm.m_Normals), signs = unpackInts(cm.m_NormalSigns);
    nrm = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const x = nd[i * 2], y = nd[i * 2 + 1], zsq = 1 - x * x - y * y;
      let z = zsq >= 0 ? Math.sqrt(zsq) : 0, nx = x, ny = y;
      if (zsq < 0) { const l = Math.hypot(x, y) || 1; nx = x / l; ny = y / l; }
      if (signs[i] === 0) z = -z;
      nrm[i * 3] = nx; nrm[i * 3 + 1] = ny; nrm[i * 3 + 2] = z;
    }
  }
  const tri = cm.m_Triangles.m_NumItems > 0 ? unpackInts(cm.m_Triangles) : new Uint32Array(0);
  return { n, pos, nrm, uv, index: i => tri[i], indexUnit: m.m_IndexFormat === 0 ? 2 : 4 };
}

export async function decodeMesh(sf, resS, m) {
  if (m.m_MeshCompression) {
    const c = decodeCompressed(m);
    return c ? finishMesh(m, c.n, c.pos, c.nrm, c.uv, c.index, c.indexUnit) : null;
  }
  const vd = m.m_VertexData, n = vd.m_VertexCount;
  if (!n) return null;
  let data = vd.m_DataSize;
  if ((!data || !data.length) && m.m_StreamData?.size) {
    if (!resS) return null;
    data = new Uint8Array(await resS.slice(m.m_StreamData.offset, m.m_StreamData.offset + m.m_StreamData.size).arrayBuffer());
  }
  if (!data?.length) return null;
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const ch = vd.m_Channels;
  const streamCount = ch.reduce((a, c) => ((c.dimension & 0xf) ? Math.max(a, c.stream + 1) : a), 0);
  const streams = [];
  let off = 0;
  for (let s = 0; s < streamCount; s++) {
    let stride = 0;
    for (const c of ch) if (c.stream === s && (c.dimension & 0xf)) stride += (c.dimension & 0xf) * FMT_SIZE[c.format];
    streams.push({ off, stride });
    off += n * stride; off = (off + 15) & ~15;
  }
  const channel = (idx, comps) => {
    const c = ch[idx];
    const dim = c ? c.dimension & 0xf : 0;
    if (!dim || dim < comps) return null;
    const st = streams[c.stream], size = FMT_SIZE[c.format], out = new Float32Array(n * comps);
    for (let i = 0; i < n; i++) {
      const base = st.off + i * st.stride + c.offset;
      for (let k = 0; k < comps; k++) out[i * comps + k] = readComp(dv, base + k * size, c.format);
    }
    return out;
  };
  const pos = channel(0, 3);
  if (!pos) return null;
  const ib = m.m_IndexBuffer, idv = new DataView(ib.buffer, ib.byteOffset, ib.byteLength);
  const use16 = m.m_IndexFormat === 0;
  const index = use16 ? i => idv.getUint16(i * 2, true) : i => idv.getUint32(i * 4, true);
  return finishMesh(m, n, pos, channel(1, 3), channel(4, 2), index, use16 ? 2 : 4);
}

// mirror X, reverse winding, split submeshes into groups (same output as extract_assets.py)
function finishMesh(m, n, pos, nrm, uv, index, indexUnit) {
  for (let i = 0; i < n; i++) { pos[i * 3] = -pos[i * 3]; if (nrm) nrm[i * 3] = -nrm[i * 3]; }
  const parts = [], groups = [];
  let total = 0;
  m.m_SubMeshes.forEach((sm, slot) => {
    if (sm.topology !== 0) return;                          // triangles only (all world-editor meshes)
    const first = sm.firstByte / indexUnit, cnt = sm.indexCount - (sm.indexCount % 3);
    const a = new Uint32Array(cnt);
    for (let i = 0; i < cnt; i += 3) {                      // reversed winding for the mirror
      a[i] = index(first + i + 2); a[i + 1] = index(first + i + 1); a[i + 2] = index(first + i);
    }
    groups.push([total, cnt, slot]); parts.push(a); total += cnt;
  });
  const idx = new Uint32Array(total);
  let o = 0; for (const p of parts) { idx.set(p, o); o += p.length; }
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) { const x = pos[i * 3 + k]; if (x < lo[k]) lo[k] = x; if (x > hi[k]) hi[k] = x; }
  return { name: m.m_Name, v: n, i: total, pos, nrm, uv, idx, groups, box: [lo, hi] };
}

// ------------------------------------------------------------------ Texture2D
// Unity TextureFormat -> how to upload it. Crunched formats (28/29) can't be decoded here.
export const TEX_FORMATS = {
  3: { kind: 'rgb24' }, 4: { kind: 'rgba32' },
  10: { kind: 'block', ext: 's3tc', gl: 'RGB_S3TC_DXT1_Format', block: 8 },
  12: { kind: 'block', ext: 's3tc', gl: 'RGBA_S3TC_DXT5_Format', block: 16 },
  25: { kind: 'block', ext: 'bptc', gl: 'RGBA_BPTC_Format', block: 16 },
  26: { kind: 'block', ext: 'rgtc', gl: 'RED_RGTC1_Format', block: 8 },
};

export async function textureData(resS, t) {
  let data = t['image data'];
  if ((!data || !data.length) && t.m_StreamData?.size) {
    if (!resS) return null;
    data = new Uint8Array(await resS.slice(t.m_StreamData.offset, t.m_StreamData.offset + t.m_StreamData.size).arrayBuffer());
  }
  return data?.length ? data : null;
}
