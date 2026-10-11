// The world kit on the website: the same Python generators, checks and fix-it tools as the desktop app,
// run by Pyodide (Python compiled to WebAssembly) in this worker so the editor stays responsive.
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const status = text => postMessage({ type: 'status', text });
let ready = null;

async function boot(kitUrl) {
  status('Loading Python (first time only, about 15 MB)…');
  const py = await loadPyodide({ indexURL: 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/' });
  status('Loading numpy…');
  await py.loadPackage('numpy');
  status('Loading the world kit…');
  const r = await fetch(kitUrl);
  if (!r.ok) throw new Error(`world kit: ${r.status} ${r.statusText}`);
  py.unpackArchive(await r.arrayBuffer(), 'zip', { extractDir: '/kit' });
  py.runPython(`
import sys, json
sys.path.insert(0, '/kit')
import worldkit

def _kit_call(op, a):
    if op == 'list':
        return {'generators': worldkit.list_generators(), 'fixes': worldkit.list_fixes()}
    if op == 'generate':
        return worldkit.generate(a['generator'], a.get('options'))
    if op == 'config':
        return {'config': worldkit.default_config(a['generator'])}
    if op == 'validate':
        return worldkit.validate(json.loads(a['world']))
    if op == 'poses':
        return {'poses': worldkit.pose_zones(json.loads(a['world']))}
    if op == 'text':
        objs, warnings = worldkit.text_objects(**a)
        return {'objects': objs, 'warnings': warnings}
    if op == 'fix':
        return worldkit.apply_fix(json.loads(a['world']), a['fix'], a.get('options'))
    raise ValueError('unknown operation ' + op)
`);
  status('');
  return py;
}

onmessage = async e => {
  const { id, op, args, kitUrl } = e.data;
  if (op === 'boot') {
    // a failed load (offline, blocked CDN) may be retried by the next boot
    ready = ready || boot(kitUrl).catch(err => { ready = null; status(''); throw err; });
    return;
  }
  try {
    if (!ready) throw new Error('The world kit is not loaded (are you offline?). Try again.');
    const py = await ready;
    // worlds travel as JSON text both ways: far faster than converting nested objects
    py.globals.set('_op', op);
    py.globals.set('_args', JSON.stringify(args || {}));
    const text = py.runPython('json.dumps(_kit_call(_op, json.loads(_args)), separators=(",", ":"))');
    postMessage({ id, text });
  } catch (err) {
    // keep only the last line of a Python traceback: that's the readable part
    const msg = String(err?.message || err).trim().split('\n').filter(Boolean).pop();
    postMessage({ id, error: msg });
  }
};
