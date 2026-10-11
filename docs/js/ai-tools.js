// Tools the AI builder can use on the open world. Every change goes through the editor's undo stack.
// Coordinates and rotations are the game's own (as stored in the .world file).
const r4 = v => Math.round(v * 1e4) / 1e4;
const vec = { type: 'array', items: { type: 'number' }, minItems: 3, maxItems: 3 };
const color = { type: 'array', items: { type: 'number' }, minItems: 3, maxItems: 4, description: '[r, g, b] from 0 to 1' };

const OBJECT = {
  type: 'object',
  properties: {
    n: { type: 'string', description: 'Object type: a primitive (Box, Cylinder, Cone, Pyramid, Sphere, Hex, ...) or a game model name from list_catalog.' },
    p: { ...vec, description: 'Position [x, y, z]; for upright primitives this is the bottom centre.' },
    yaw: { type: 'number', description: 'Heading h in degrees for an upright object (its depth axis runs along fwd(h)). Used instead of r.' },
    r: { ...vec, description: 'Raw Unity Euler rotation (degrees). Upright objects are [270, (h + 180) % 360, 0].' },
    s: { ...vec, description: 'Scale. Upright primitives: [width, depth, height] in metres.' },
    c: color,
    m: { type: 'string', description: 'Material, e.g. unlit, Illum FLAT, discard, glass_1, water, Hologram2.' },
  },
  required: ['n', 'p'],
};

export const TOOLS = [
  {
    name: 'world_summary',
    description: 'Overview of the open world: object counts, respawn, weather, bounds, the top-level groups (with ids, sizes and centres), the current selection and the point the camera looks at. Call this first.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'find_objects',
    description: 'Find objects by type name, material, group, the user selection, or distance from a point. Returns ids you can modify, delete or focus.',
    input_schema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Substring of the object type (case-insensitive).' },
        material: { type: 'string', description: 'Substring of the material.' },
        near: { ...vec, description: 'Only objects within `radius` of this point.' },
        radius: { type: 'number', description: 'Metres (default 10).' },
        group_id: { type: 'integer', description: 'Only objects inside this group.' },
        selected: { type: 'boolean', description: 'Only the objects the user has selected.' },
        limit: { type: 'integer', description: 'Default 100, max 500.' },
      },
    },
  },
  {
    name: 'add_objects',
    description: 'Add objects to the world as one new group (one undo step). Returns the group id and object ids.',
    input_schema: {
      type: 'object',
      properties: { objects: { type: 'array', items: OBJECT, minItems: 1 }, label: { type: 'string', description: 'What this is, for the undo list.' } },
      required: ['objects'],
    },
  },
  {
    name: 'modify_objects',
    description: 'Change objects (or every object inside groups) by id: set fields, move by an offset, rotate about the vertical axis around their shared centre, or scale. One undo step.',
    input_schema: {
      type: 'object',
      properties: {
        ids: { type: 'array', items: { type: 'integer' }, minItems: 1 },
        set: { type: 'object', description: 'Fields to set on every object: n, m, c, p, r, s, or yaw.', properties: { n: { type: 'string' }, m: { type: 'string' }, c: color, p: vec, r: vec, s: vec, yaw: { type: 'number' } } },
        move: { ...vec, description: 'Offset [dx, dy, dz] in metres.' },
        turn: { type: 'number', description: 'Degrees to turn the whole set about the vertical axis through its centre (positive = clockwise seen from above, like headings).' },
        scale: { type: 'number', description: 'Multiply sizes (and spacing from the shared centre) by this.' },
      },
      required: ['ids'],
    },
  },
  {
    name: 'delete_objects',
    description: 'Delete objects or groups by id (one undo step).',
    input_schema: { type: 'object', properties: { ids: { type: 'array', items: { type: 'integer' }, minItems: 1 } }, required: ['ids'] },
  },
  {
    name: 'show_objects',
    description: 'Select objects or groups by id in the editor and move the camera to them, so the user can see what you mean.',
    input_schema: { type: 'object', properties: { ids: { type: 'array', items: { type: 'integer' }, minItems: 1 } }, required: ['ids'] },
  },
  {
    name: 'world_settings',
    description: 'Change the respawn point and facing, weather (Clear, Rain, Snow, Cloudy, Fog, Night, Sunrise...) or ocean level.',
    input_schema: { type: 'object', properties: { respawn: vec, facing: { type: 'number' }, weather: { type: 'string' }, oceanlevel: { type: 'number' } } },
  },
  {
    name: 'list_catalog',
    description: 'Search the game objects and materials available in this editor (names only).',
    input_schema: { type: 'object', properties: { kind: { type: 'string', enum: ['objects', 'materials'] }, query: { type: 'string' }, limit: { type: 'integer' } }, required: ['kind'] },
  },
  {
    name: 'add_text',
    description: 'Add a standing sign in the board pixel font (capitals A-Z, 0-9, simple punctuation; \\n for new lines) as one group. `at` is the bottom centre; it reads correctly for someone looking along `heading`.',
    input_schema: {
      type: 'object',
      properties: {
        text: { type: 'string' }, at: vec, heading: { type: 'number' },
        height: { type: 'number', description: 'Letter height in metres (default 0.4).' },
        color, material: { type: 'string', description: 'unlit (default) or Illum FLAT for neon.' },
        backing: { ...color, description: 'Colour of a board behind the letters (optional).' },
      },
      required: ['text', 'at'],
    },
  },
  {
    name: 'list_generators',
    description: 'The ready-made world generators and their options.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'run_generator',
    description: 'Build a whole world with a generator. mode "replace" opens it instead of the current world (the user can undo); "merge" adds it to the current world as one group.',
    input_schema: {
      type: 'object',
      properties: { generator: { type: 'string' }, options: { type: 'object' }, mode: { type: 'string', enum: ['replace', 'merge'] } },
      required: ['generator', 'mode'],
    },
  },
  {
    name: 'check_world',
    description: 'Check the open world: portals with no floor or blocked exits, washed-out colours, visible portal models, missing respawn. Returns problems and notes.',
    input_schema: { type: 'object', properties: {} },
  },
  {
    name: 'apply_fix',
    description: 'Run a fix-it tool on the whole world (one undo step): portal_glow, hide_portal_models, flat_colours, respawn. See check_world for when to use them.',
    input_schema: { type: 'object', properties: { fix: { type: 'string', enum: ['portal_glow', 'hide_portal_models', 'flat_colours', 'respawn'] }, options: { type: 'object' } }, required: ['fix'] },
  },
  {
    name: 'pose_zones',
    description: 'Every pose zone (*_ph, *_poses) with its heading and the direction its poses face, and turns on the pose arrows in the 3D view.',
    input_schema: { type: 'object', properties: {} },
  },
];

// ------------------------------------------------------------ input checks
// The model's tool input streams in eagerly, so check it against the schema before running anything.
export function checkInput(schema, v, path = 'input') {
  const t = schema.type;
  if (t === 'object') {
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return `${path} must be an object`;
    for (const k of schema.required || []) if (!(k in v)) return `${path}.${k} is required`;
    for (const [k, s] of Object.entries(schema.properties || {})) if (k in v) { const e = checkInput(s, v[k], `${path}.${k}`); if (e) return e; }
  } else if (t === 'array') {
    if (!Array.isArray(v)) return `${path} must be an array`;
    if (schema.minItems && v.length < schema.minItems) return `${path} needs at least ${schema.minItems} items`;
    if (schema.maxItems && v.length > schema.maxItems) return `${path} allows at most ${schema.maxItems} items`;
    if (schema.items) for (let i = 0; i < v.length; i++) { const e = checkInput(schema.items, v[i], `${path}[${i}]`); if (e) return e; }
  } else if (t === 'number' || t === 'integer') {
    if (typeof v !== 'number' || !Number.isFinite(v) || (t === 'integer' && !Number.isInteger(v))) return `${path} must be a${t === 'integer' ? 'n integer' : ' number'}`;
  } else if (t === 'string') {
    if (typeof v !== 'string') return `${path} must be a string`;
    if (schema.enum && !schema.enum.includes(v)) return `${path} must be one of ${schema.enum.join(', ')}`;
  } else if (t === 'boolean' && typeof v !== 'boolean') return `${path} must be true or false`;
  return null;
}

// ------------------------------------------------------------ executors
const upright = yaw => [270, ((yaw + 180) % 360 + 360) % 360, 0];

function toWorldObject(o) {
  const out = { n: o.n, p: o.p.map(r4) };
  out.r = o.yaw !== undefined ? upright(o.yaw) : (o.r || [270, 180, 0]).map(r4);
  out.s = (o.s || [1, 1, 1]).map(r4);
  if (o.c) out.c = o.c.map(r4);
  if (o.m) out.m = o.m;
  return out;
}

function brief(n) {
  if (n.isGroup) return { id: n.id, group: true, objects: [...n.leaves()].length };
  const o = n.obj, b = { id: n.id, n: o.n, p: o.p, r: o.r, s: o.s };
  if (o.c) b.c = o.c.slice(0, 3).map(v => Math.round(v * 100) / 100);
  if (o.m) b.m = o.m;
  return b;
}

// ed: the editor's hooks (main.js) - see makeEditorHooks there
export function makeExecutor(ed) {
  const byId = () => { const m = new Map(); for (const n of ed.world().root.walk()) m.set(n.id, n); return m; };
  const nodesFor = ids => {
    const map = byId(), nodes = [], missing = [];
    for (const id of ids) { const n = map.get(id); if (n && n !== ed.world().root) nodes.push(n); else missing.push(id); }
    if (missing.length) throw new Error(`no object or group with id ${missing.join(', ')} (ids change when the world is reopened: use find_objects)`);
    return nodes;
  };
  const centreOf = leaves => {
    const c = [0, 0, 0];
    for (const l of leaves) for (let i = 0; i < 3; i++) c[i] += (l.obj.p || [0, 0, 0])[i] / leaves.length;
    return c;
  };

  const run = {
    world_summary() {
      const w = ed.world(), leaves = [...w.leaves()];
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      const names = new Map();
      for (const l of leaves) {
        const p = l.obj.p || [0, 0, 0];
        for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i], p[i]); hi[i] = Math.max(hi[i], p[i]); }
        names.set(l.obj.n, (names.get(l.obj.n) || 0) + 1);
      }
      const groups = w.root.children.slice(0, 80).map(g => {
        const ls = [...g.leaves()];
        const top = new Map(); for (const l of ls) top.set(l.obj.n, (top.get(l.obj.n) || 0) + 1);
        return { id: g.id, group: g.isGroup, objects: ls.length, centre: ls.length ? centreOf(ls).map(v => Math.round(v * 10) / 10) : null,
          mostly: [...top].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => `${k} x${v}`).join(', ') };
      });
      return {
        file: w.displayName, objects: leaves.length, top_level_items: w.root.children.length,
        groups_shown: groups.length, groups, header: w.header,
        bounds: leaves.length ? { min: lo.map(r4), max: hi.map(r4) } : null,
        object_types: [...names].sort((a, b) => b[1] - a[1]).slice(0, 25),
        selection: ed.selection().slice(0, 50).map(brief),
        camera_looks_at: ed.viewCentre().map(v => Math.round(v * 100) / 100),
      };
    },

    find_objects(a) {
      const limit = Math.min(500, a.limit || 100);
      let pool;
      if (a.selected) pool = ed.selection().flatMap(n => [...n.leaves()]);
      else if (a.group_id !== undefined) pool = [...nodesFor([a.group_id])[0].leaves()];
      else pool = [...ed.world().leaves()];
      const nm = a.name?.toLowerCase(), mt = a.material?.toLowerCase(), rad = a.radius ?? 10;
      const hits = [];
      let total = 0;
      for (const l of pool) {
        if (nm && !l.obj.n.toLowerCase().includes(nm)) continue;
        if (mt && !(l.obj.m || '').toLowerCase().includes(mt)) continue;
        if (a.near) { const p = l.obj.p || [0, 0, 0]; if (Math.hypot(p[0] - a.near[0], p[1] - a.near[1], p[2] - a.near[2]) > rad) continue; }
        total++;
        if (hits.length < limit) hits.push({ ...brief(l), group_id: l.topAncestor(ed.world().root).id });
      }
      return { matches: total, shown: hits.length, objects: hits };
    },

    add_objects(a) {
      const objs = a.objects.map(toWorldObject);
      const [g] = ed.addObjects([{ n: 'group', objects: objs }], a.label || 'AI: add');
      return { group_id: g.id, ids: g.children.map(c => c.id) };
    },

    modify_objects(a) {
      const leaves = [...new Set(nodesFor(a.ids).flatMap(n => [...n.leaves()]))];
      const c = centreOf(leaves);
      const th = (a.turn || 0) * Math.PI / 180, cs = Math.cos(th), sn = Math.sin(th);
      ed.editLeaves(leaves, n => {
        const o = n.obj;
        if (a.set) {
          for (const k of ['n', 'm']) if (a.set[k] !== undefined) o[k] = a.set[k];
          if (a.set.c) o.c = a.set.c.map(r4);
          for (const k of ['p', 'r', 's']) if (a.set[k]) o[k] = a.set[k].map(r4);
          if (a.set.yaw !== undefined) o.r = upright(a.set.yaw);
        }
        let p = (o.p || [0, 0, 0]).slice();
        if (a.scale) { p = p.map((v, i) => c[i] + (v - c[i]) * a.scale); o.s = (o.s || [1, 1, 1]).map(v => r4(v * a.scale)); }
        if (th) {
          // headings turn clockwise seen from above: fwd(h) = (sin h, 0, cos h)
          const dx = p[0] - c[0], dz = p[2] - c[2];
          p[0] = c[0] + dx * cs + dz * sn; p[2] = c[2] - dx * sn + dz * cs;
          const r = o.r || [0, 0, 0];
          o.r = [r[0], ((r[1] + a.turn) % 360 + 360) % 360, r[2]].map(r4);
        }
        if (a.move) p = p.map((v, i) => v + a.move[i]);
        if (a.scale || th || a.move) o.p = p.map(r4);
      }, 'AI: modify');
      return { changed: leaves.length };
    },

    delete_objects(a) { const nodes = nodesFor(a.ids); ed.deleteNodes(nodes); return { deleted: nodes.length }; },

    show_objects(a) { const nodes = nodesFor(a.ids); ed.show(nodes); return { shown: nodes.length }; },

    world_settings(a) {
      const patch = {};
      if (a.respawn || a.facing !== undefined) {
        const cur = ed.world().header.respawn || { p: [0, 0, 0], r: 0 };
        patch.respawn = { p: (a.respawn || cur.p).map(r4), r: a.facing ?? cur.r ?? 0 };
      }
      if (a.weather) patch.weather = a.weather;
      if (a.oceanlevel !== undefined) patch.oceanlevel = a.oceanlevel;
      ed.setHeader(patch);
      return { header: ed.world().header };
    },

    list_catalog(a) {
      const names = ed.catalog(a.kind);
      const q = (a.query || '').toLowerCase();
      const hits = names.filter(n => !q || n.toLowerCase().includes(q));
      return { matches: hits.length, names: hits.slice(0, Math.min(400, a.limit || 150)) };
    },

    async add_text(a) {
      const res = await ed.kit.text(a);
      const [g] = ed.addObjects([{ n: 'group', objects: res.objects }], 'AI: sign');
      return { group_id: g.id, objects: res.objects.length, warnings: res.warnings };
    },

    async list_generators() { return (await ed.kit.list()).generators; },

    async run_generator(a) {
      const res = await ed.kit.generate(a.generator, a.options || {});
      if (a.mode === 'merge') {
        const [g] = ed.addObjects([{ n: 'group', objects: res.world.objects }], 'AI: ' + a.generator);
        return { merged_group_id: g.id, summary: res.summary };
      }
      ed.replaceWorld(res.world, 'AI: ' + a.generator, `${a.generator}.world`);
      return { opened: true, summary: res.summary };
    },

    async check_world() {
      const v = await ed.kit.validate(ed.world().stringify());
      return { problems: v.problems, notes: v.notes, portal_pairs: v.portals.pairs, stats: { ...v.stats, top_objects: v.stats.top_objects.slice(0, 10) } };
    },

    async apply_fix(a) {
      const v = ed.version();
      const res = await ed.kit.fix(ed.world().stringify(), a.fix, a.options || {});
      if (ed.version() !== v) throw new Error('the user changed the world while the fix ran, so nothing was applied; run it again');
      ed.replaceWorld(res.world, 'AI: ' + a.fix);
      return res.report;
    },

    pose_zones() { ed.showPoses(true); return { poses: ed.poseZones().slice(0, 200) }; },
  };

  return async function execute(name, input) {
    const tool = TOOLS.find(t => t.name === name);
    if (!tool) throw new Error(`unknown tool ${name}`);
    const bad = checkInput(tool.input_schema, input);
    if (bad) { const e = new Error(bad); e.invalidInput = true; throw e; }
    if (!ed.world() && name !== 'run_generator' && name !== 'list_generators' && name !== 'list_catalog') ed.newWorld();
    return run[name](input);
  };
}
