// Calls to the local editor server (server.py). Every call carries the session token.
let token = '';
export function setToken(t) { token = t; }
// server.py replaces the placeholder in index.html; on the static website it stays
export function hasServer() { return !!token && !token.startsWith('__'); }

async function req(url, opts = {}) {
  const r = await fetch(url, { ...opts, headers: { 'X-Editor-Token': token, ...(opts.headers || {}) } });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).error || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r;
}

export const api = {
  json: async url => (await req(url)).json(),
  text: async url => (await req(url)).text(),
  post: async (url, body) => (await req(url, { method: 'POST', body, headers: { 'Content-Type': 'application/json' } })).json(),
};
