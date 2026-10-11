// "Generate…" and "Check & fix…" dialogs for the world kit.
const $ = s => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k);
  return e;
};
const hex = c => '#' + c.slice(0, 3).map(v => Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, '0')).join('');
const unhex = h => [1, 3, 5].map(i => +(parseInt(h.substr(i, 2), 16) / 255).toFixed(3));

let catalog = null;
async function getCatalog(kit) { return catalog || (catalog = await kit.list()); }

// a status line that follows the kit (Python loading on the website, etc.)
function statusLine(kit) {
  const line = el('p', { class: 'kit-status muted small' });
  const off = kit.onStatus(t => {
    if (line.dataset.live && !line.isConnected) { off(); return; }   // its dialog was redrawn: stop listening
    if (t) line.textContent = t;
  });
  requestAnimationFrame(() => { line.dataset.live = '1'; });
  return line;
}

export function mountKitUI(ed) {
  const { kit, toast } = ed;

  // ------------------------------------------------------------------ generate
  async function openGenerate() {
    $('#modal-gen').classList.add('open');
    const body = $('#gen-body');
    body.replaceChildren(el('p', { class: 'muted' }, ed.MODE === 'web' ? 'Starting the world kit… (the website runs it in your browser)' : 'Loading…'), statusLine(kit));
    let cat;
    try { cat = await getCatalog(kit); } catch (e) { body.replaceChildren(el('p', { class: 'note' }, 'The world kit could not start: ' + e.message)); return; }
    let chosen = cat.generators[0].id;
    const configs = {};
    const opts = el('div');
    const cards = el('div', { class: 'gen-cards' });
    const mode = el('select', {}, el('option', { value: 'replace' }, 'Open it as a new world'), el('option', { value: 'merge' }, 'Add it to this world as a group'));
    const status = statusLine(kit);
    const go = el('button', { class: 'primary' }, 'Generate');

    const renderOpts = async () => {
      opts.replaceChildren();
      const g = cat.generators.find(x => x.id === chosen);
      for (const [k, o] of Object.entries(g.options)) {
        if (o.type === 'integer') {
          opts.append(el('div', { class: 'row' }, el('label', { title: o.description }, k), el('input', { type: 'number', 'data-opt': k, value: o.default ?? '', placeholder: o.default === undefined ? 'all' : '', step: 1 }),
            el('span', { class: 'muted small' }, o.description)));
        } else if (k === 'config') {
          const ta = el('textarea', { 'data-opt': 'config', spellcheck: 'false', rows: 12 });
          opts.append(el('p', { class: 'muted small' }, 'Board text (JSON). Change any line; the lists marked "exactly" must keep their length. Text is drawn in capitals.'), ta,
            el('div', { class: 'btns' }, el('button', { onclick: async () => { delete configs[chosen]; ta.value = JSON.stringify((await kit.config(chosen)).config, null, 2); } }, 'Reset to default')));
          ta.value = configs[chosen] || JSON.stringify((await kit.config(chosen)).config, null, 2);
          ta.oninput = () => { configs[chosen] = ta.value; };
        }
      }
    };
    for (const g of cat.generators) {
      const card = el('label', { class: 'gen-card' + (g.id === chosen ? ' on' : '') },
        el('input', { type: 'radio', name: 'gen', value: g.id, checked: g.id === chosen }), el('b', {}, g.name), el('span', { class: 'muted small' }, g.description));
      card.querySelector('input').onchange = () => { chosen = g.id; cards.querySelectorAll('.gen-card').forEach(c => c.classList.toggle('on', c === card)); renderOpts(); };
      cards.append(card);
    }
    if (!ed.world()) mode.value = 'replace';
    go.onclick = async () => {
      const options = {};
      for (const i of opts.querySelectorAll('[data-opt]')) {
        if (i.dataset.opt === 'config') {
          try { options.config = JSON.parse(i.value); } catch (e) { toast('The board text is not valid JSON: ' + e.message, 'error'); return; }
        } else if (i.value !== '') options[i.dataset.opt] = parseInt(i.value, 10);
      }
      go.disabled = true; status.textContent = 'Building… (Only Up! takes a while' + (ed.MODE === 'web' ? ', longer in the browser' : '') + ')';
      try {
        const res = await kit.generate(chosen, options);
        const name = cat.generators.find(x => x.id === chosen).name;
        if (mode.value === 'merge' && ed.world()) ed.addObjects([{ n: 'group', objects: res.world.objects }], 'generate ' + chosen);
        else ed.replaceWorld(res.world, 'generate ' + chosen, `${name.replace(/[^\w]+/g, '-').replace(/-+$/, '')}-3DX.world`);
        const warn = res.summary.warnings?.length ? ` — ${res.summary.warnings.length} text warning(s), see the console` : '';
        if (warn) console.warn(res.summary.warnings);
        toast(`${name}: ${res.summary.objects.toLocaleString()} objects${warn}`);
        ed.closeModals();
      } catch (e) {
        status.textContent = '';
        toast('Generate failed: ' + e.message, 'error');
      } finally { go.disabled = false; }
    };
    body.replaceChildren(cards, opts, el('div', { class: 'row' }, el('label', {}, 'Result'), mode), status, el('div', { class: 'btns' }, go));
    renderOpts();
  }

  // ------------------------------------------------------------- check & fix
  async function openCheck() {
    if (!ed.world()) { toast('Open or generate a world first'); return; }
    $('#modal-check').classList.add('open');
    const body = $('#check-body');
    body.replaceChildren(el('p', { class: 'muted' }, 'Checking…'), statusLine(kit));
    let cat, v;
    try { [cat, v] = await Promise.all([getCatalog(kit), kit.validate(ed.world().stringify())]); }
    catch (e) { body.replaceChildren(el('p', { class: 'note' }, 'Check failed: ' + e.message)); return; }
    const st = v.stats;
    const list = (items, cls) => el('ul', { class: cls }, ...items.map(t => el('li', {}, t)));
    body.replaceChildren(
      el('p', {}, `${st.objects.toLocaleString()} objects · ${st.portals} portals (${v.portals.pairs} pairs) · ${st.pose_zones} pose zones · ${st.lights} lights`),
      v.problems.length ? el('div', {}, el('b', {}, 'Problems'), list(v.problems, 'problems')) : el('p', { class: 'ok' }, 'No problems found.'),
      v.notes.length ? el('div', {}, el('b', {}, 'Suggestions'), list(v.notes, 'notes')) : null,
      el('h4', {}, 'Fix-it tools'),
      ...cat.fixes.map(f => fixRow(f)),
      el('div', { class: 'row' }, el('label', {}, 'Poses'), el('button', { onclick: () => { ed.showPoses(true); ed.closeModals(); toast('Pink arrows show which way each pose zone faces'); } }, 'Show pose directions')),
    );
  }

  function fixRow(f) {
    const extra = [];
    let colorIn = null;
    if (f.id === 'portal_glow') { colorIn = el('input', { type: 'color', value: hex(f.options.color.default), title: 'Glow colour' }); extra.push(colorIn); }
    if (f.id === 'respawn') extra.push(el('span', { class: 'muted small' }, 'adds one if missing; use World settings to place it exactly'));
    const btn = el('button', {}, 'Apply');
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const v = ed.version();
        const res = await kit.fix(ed.world().stringify(), f.id, colorIn ? { color: unhex(colorIn.value) } : {});
        if (ed.version() !== v) throw new Error('the world changed while it ran, so nothing was applied. Run it again');
        ed.replaceWorld(res.world, f.name);
        toast(`${f.name}: ${Object.entries(res.report).map(([k, v]) => `${k.replace(/_/g, ' ')} ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(', ')}`);
        openCheck();
      } catch (e) { toast(`${f.name} failed: ${e.message}`, 'error'); btn.disabled = false; }
    };
    return el('div', { class: 'fix-row' }, el('div', {}, el('b', {}, f.name), el('div', { class: 'muted small' }, f.description)), el('div', { class: 'fix-act' }, ...extra, btn));
  }

  $('#btn-generate').addEventListener('click', openGenerate);
  $('#btn-check').addEventListener('click', openCheck);
}
