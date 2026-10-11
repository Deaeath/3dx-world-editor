// The AI builder's chat panel (right side of the 3D view).
import { AIBuilder, MODEL } from './ai.js';
import { api, hasServer } from './api.js';

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
const store = {
  get: k => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch { /* storage blocked */ } },
};

// one line per tool call, e.g. "add_objects - 120 objects"
function describeCall(name, input) {
  if (name === 'add_objects') return `${input.objects?.length ?? 0} objects${input.label ? ' - ' + input.label : ''}`;
  if (name === 'modify_objects' || name === 'delete_objects' || name === 'show_objects') return `${input.ids?.length ?? 0} item(s)`;
  if (name === 'run_generator') return `${input.generator} (${input.mode})`;
  if (name === 'apply_fix') return input.fix;
  if (name === 'add_text') return JSON.stringify(input.text);
  if (name === 'find_objects') return Object.entries(input).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ');
  return '';
}
function describeResult(res) {
  if (!res || typeof res !== 'object') return '';
  if (Array.isArray(res)) return `${res.length} item(s)`;
  const parts = [];
  for (const k of ['objects', 'matches', 'changed', 'deleted', 'shown', 'glows_added', 'models_hidden']) if (typeof res[k] === 'number') parts.push(`${k.replace(/_/g, ' ')} ${res[k].toLocaleString()}`);
  if (res.problems) parts.push(`${res.problems.length} problem(s)`);
  if (res.summary?.objects) parts.push(`${res.summary.objects.toLocaleString()} objects`);
  if (res.poses) parts.push(`${res.poses.length} pose zones`);
  return parts.join(', ');
}

export function mountAIPanel(ed) {
  const panel = $('#ai-panel'), log = $('#ai-log'), input = $('#ai-input');
  const sendBtn = $('#ai-send'), stopBtn = $('#ai-stop'), keyIn = $('#ai-key'), effortSel = $('#ai-effort');
  let envKey = false;

  const scroll = () => { log.scrollTop = log.scrollHeight; };
  const ui = {
    assistant() {
      const box = el('div', { class: 'ai-msg bot' });
      let textEl = null, thinkEl = null, writingEl = null;
      log.append(box); scroll();
      return {
        text(d) { if (!textEl) { textEl = el('div', { class: 'ai-text' }); box.append(textEl); } textEl.textContent += d; scroll(); },
        thinking(d) {
          if (!thinkEl) { thinkEl = el('details', { class: 'ai-think' }, el('summary', {}, 'Thinking'), el('div')); box.append(thinkEl); }
          thinkEl.lastChild.textContent += d; scroll();
        },
        writing(n) {
          if (!writingEl) { writingEl = el('div', { class: 'ai-writing muted small' }); box.append(writingEl); }
          writingEl.textContent = `Writing a tool call… ${(n / 1024).toFixed(1)} KB`;
        },
        note(msg) { box.append(el('div', { class: 'ai-note' }, msg)); scroll(); },
        tool(name, inp) {
          writingEl?.remove(); writingEl = null;
          const row = el('div', { class: 'ai-tool' }, el('span', { class: 'ai-tool-name' }, name), ' ', el('span', { class: 'muted' }, describeCall(name, inp)));
          box.append(row); scroll();
          return {
            done(res) { row.classList.add('ok'); const d = describeResult(res); if (d) row.append(el('span', { class: 'muted' }, ' → ' + d)); },
            fail(msg) { row.classList.add('bad'); row.append(el('div', { class: 'small' }, msg)); scroll(); },
          };
        },
      };
    },
    error(msg) { log.append(el('div', { class: 'ai-msg err' }, msg)); scroll(); },
    busy(b) { sendBtn.hidden = b; stopBtn.hidden = !b; input.disabled = false; panel.classList.toggle('busy', b); },
    usage(u) {
      if (!u.input && !u.output) return;
      $('#ai-usage').textContent = `Last message: ${u.input.toLocaleString()} input tokens (${u.cached.toLocaleString()} cached), ${u.output.toLocaleString()} output`;
    },
  };

  const ai = new AIBuilder(ed, ui);
  const applyKey = () => {
    const k = keyIn.value.trim() || (envKey ? envKey : '');
    ai.setKey(k);
    $('#ai-key-state').textContent = keyIn.value.trim() ? 'Key saved in this browser only.' : envKey ? 'Using ANTHROPIC_API_KEY from this PC.' : 'No key yet.';
    $('#ai-settings').open = !k;
  };
  keyIn.value = store.get('we.aiKey') || '';
  effortSel.value = store.get('we.aiEffort') || 'high';
  ai.effort = effortSel.value;
  keyIn.addEventListener('change', () => { store.set('we.aiKey', keyIn.value.trim()); applyKey(); });
  effortSel.addEventListener('change', () => { ai.effort = effortSel.value; store.set('we.aiEffort', effortSel.value); });
  $('#ai-model').textContent = MODEL;

  const send = () => {
    const text = input.value.trim();
    if (!text || ai.busy) return;
    log.append(el('div', { class: 'ai-msg me' }, text)); scroll();
    input.value = '';
    ai.send(text);
  };
  sendBtn.addEventListener('click', send);
  stopBtn.addEventListener('click', () => ai.stop());
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  $('#ai-new').addEventListener('click', () => { if (ai.busy) return; ai.reset(); log.replaceChildren(); $('#ai-usage').textContent = ''; });
  for (const b of document.querySelectorAll('[data-ai-example]')) b.addEventListener('click', () => { input.value = b.dataset.aiExample; input.focus(); });

  const toggle = on => {
    panel.hidden = !(on ?? panel.hidden);
    $('#btn-ai').classList.toggle('on', !panel.hidden);
    if (!panel.hidden) input.focus();
  };
  $('#btn-ai').addEventListener('click', () => toggle());
  $('#ai-close').addEventListener('click', () => toggle(false));

  (async () => {
    if (hasServer()) { try { envKey = (await api.json('/api/ai/key')).key || false; } catch { /* older server */ } }
    applyKey();
  })();
  return ai;
}
