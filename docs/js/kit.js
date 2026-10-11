// World kit client: the generators, checks and fix-it tools (generators/worldkit.py).
// Desktop app: the local server runs them. Website: a Pyodide worker runs the same Python in the browser.
import { api, hasServer } from './api.js';

let worker = null, seq = 0, kitUrl = null;
const pending = new Map();
const listeners = new Set();
let lastStatus = '';

function setStatus(text) { lastStatus = text; listeners.forEach(f => f(text)); }

async function webCall(op, args) {
  if (!worker) {
    const m = await fetch(new URL('../py/worldkit.json', import.meta.url)).then(r => r.json()).catch(() => ({}));
    kitUrl = new URL(`../py/worldkit.zip?v=${m.sha256 || Date.now()}`, import.meta.url).href;
    worker = new Worker(new URL('./kit-worker.js', import.meta.url), { type: 'module' });
    worker.onmessage = e => {
      const d = e.data;
      if (d.type === 'status') { setStatus(d.text); return; }
      const p = pending.get(d.id); if (!p) return;
      pending.delete(d.id);
      if (d.error) p.reject(new Error(d.error)); else p.resolve(JSON.parse(d.text));
    };
    worker.onerror = e => { setStatus(''); for (const p of pending.values()) p.reject(new Error(e.message || 'world kit crashed')); pending.clear(); };
  }
  worker.postMessage({ op: 'boot', kitUrl });   // no-op once loaded; retries a failed load
  const id = ++seq;
  return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); worker.postMessage({ id, op, args }); });
}

async function call(op, args = {}) {
  if (hasServer()) return api.post('/api/kit/' + op, JSON.stringify(args));
  return webCall(op, args);
}

export const kit = {
  onStatus(fn) { listeners.add(fn); fn(lastStatus); return () => listeners.delete(fn); },
  list: () => call('list'),
  config: generator => call('config', { generator }),
  // -> { world, summary, log }
  generate: (generator, options = {}) => call('generate', { generator, options }),
  // worldText: the .world file text (World.stringify())
  validate: worldText => call('validate', { world: worldText }),
  poses: worldText => call('poses', { world: worldText }),
  // pixel-font sign -> { objects, warnings }; at = bottom centre (game coords), read looking along heading
  text: ({ text, at, heading = 0, height = 0.4, color = [1, 1, 1], material = 'unlit', backing = null }) =>
    call('text', { text, at, heading, height, color, material, backing }),
  // -> { world, report }
  fix: (worldText, fix, options = {}) => call('fix', { world: worldText, fix, options }),
};
