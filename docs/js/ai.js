// AI builder: chat with Claude, which builds and repairs the open world through the editor's own tools.
// Bring-your-own Anthropic API key (kept in this browser only); the desktop app can also take it from the
// ANTHROPIC_API_KEY environment variable.
import Anthropic from '../vendor/anthropic/sdk.js';
import { TOOLS, makeExecutor } from './ai-tools.js';

export const MODEL = 'claude-opus-5-5';
const MAX_TURNS = 60;          // model calls per message, a guard against runaway loops

const SYSTEM = `You are the AI builder inside 3DX World Editor, an editor for 3DXChat .world files (an adult social game where players walk avatars around user-built worlds). You build, change and repair the world the user has open by calling tools. Every change is one undo step for the user (Ctrl+Z); the user saves the file themselves.

Coordinates are the game's own (Unity, left-handed), in metres: x east, y up, z north. A heading h points along fwd(h) = (sin h, 0, cos h): 0 = +z, 90 = +x, 180 = -z, 270 = -x; right_of(h) = (cos h, 0, -sin h).

Objects are {n, p, r, s, c, m}. Nearly everything stands upright with r = [270, (h + 180) % 360, 0]; pass yaw: h to add_objects instead of r. For upright primitives (Box, Cylinder, Cone, Pyramid, Sphere, Hex, Tube...) p is the bottom centre and s = [width along right_of(h), depth along fwd(h), height]; a Box spans p.y to p.y + height. Floors are boxes about 0.1-0.3 m thick. Game models (furniture, props, lights, portal...) use s as a scale factor, usually [1, 1, 1].

Materials: "unlit" = flat colour, the default for coloured primitives. "Illum FLAT" glows; use it only for lights and neon, it washes pastel colours out to white. "discard" = invisible but solid (invisible walkways, hidden portal models). "glass_1"/"glass_2" translucent, "water", "Hologram2" translucent glow, plus textured ones from list_catalog. Colours c = [r, g, b] from 0 to 1.

Rules of the game world:
- Avatars cannot jump. Every walkable rise must be 0.25 m or less (stairs: 0.25 m risers), ramps under about 28 degrees, gaps bridged (an invisible "discard" box works), and keep 2.2 m of head room.
- Portals are objects named "portal". Consecutive portals in file order form one two-way pair, so add exactly two per link in the same add_objects call, each standing on a floor with room for a body. Players like portal models hidden with a glowing hexagon on the floor: run apply_fix portal_glow after adding portals.
- Pose zones are models ending in _ph or _poses (bed_ph, sofa_ph, chair_ph, table_ph, pool_ph, bar_stool_2_poses, cross_stool_poses...). Their poses face fwd(h - 90): to make poses face direction d, use yaw = d + 90. Lay a pose zone over its furniture at the same place.
- Text on signs uses add_text (capital pixel letters).

How to work: look first (world_summary, find_objects, pose_zones), then make each change in as few calls as possible (one add_objects call can hold hundreds of objects). Build near what the user is looking at (camera_looks_at in world_summary) unless they say otherwise. After building, run check_world and fix real problems. For whole themed worlds, list_generators first: Only Up!, Squid Game and Slutopoly are ready-made. When done, reply briefly: what you built and where. If a request is unclear, ask one short question instead of guessing.`;

export class AIBuilder {
  constructor(ed, ui) {
    this.ui = ui;
    this.execute = makeExecutor(ed);
    this.messages = [];
    this.effort = 'high';
    this.busy = false;
    this.abort = null;
    this.client = null;
  }

  setKey(key) {
    this.client = key ? new Anthropic({ apiKey: key, dangerouslyAllowBrowser: true, maxRetries: 3 }) : null;
  }

  reset() { if (!this.busy) this.messages = []; }

  stop() { this.abort?.abort(); }

  async send(text) {
    if (this.busy || !text.trim()) return;
    if (!this.client) { this.ui.error('Add your Anthropic API key first (AI settings).'); return; }
    this.busy = true;
    this.ui.busy(true);
    this.abort = new AbortController();
    const start = this.messages.length;
    this.messages.push({ role: 'user', content: text });
    let jsonRetries = 0;
    const usage = { input: 0, output: 0, cached: 0 };
    try {
      for (let turn = 0; turn < MAX_TURNS; turn++) {
        const out = this.ui.assistant();
        const stream = this.client.beta.messages.stream({
          model: MODEL,
          max_tokens: 64000,
          betas: ['server-side-fallback-2026-07-01'],
          fallbacks: 'default',
          thinking: { type: 'adaptive', display: 'summarized' },
          output_config: { effort: this.effort },
          system: [{ type: 'text', text: SYSTEM, cache_control: { type: 'ephemeral' } }],
          tools: TOOLS.map(t => ({ ...t, eager_input_streaming: true })),
          messages: this.messages,
        }, { signal: this.abort.signal });
        stream.on('text', d => out.text(d));
        stream.on('thinking', d => out.thinking(d));
        stream.on('inputJson', (_d, snapshot) => out.writing(JSON.stringify(snapshot ?? '').length));

        let msg;
        try {
          msg = await stream.finalMessage();
          jsonRetries = 0;
        } catch (err) {
          // a tool input that is not even partial JSON: re-ask (a couple of times); real API errors go up
          if (err instanceof Anthropic.APIError || err instanceof Anthropic.APIUserAbortError || this.abort.signal.aborted || jsonRetries++ >= 2) throw err;
          out.note('The tool input came back garbled; asking again…');
          continue;
        }
        usage.input += (msg.usage.input_tokens || 0) + (msg.usage.cache_creation_input_tokens || 0) + (msg.usage.cache_read_input_tokens || 0);
        usage.cached += msg.usage.cache_read_input_tokens || 0;
        usage.output += msg.usage.output_tokens || 0;
        if (msg.content.some(b => b.type === 'fallback')) out.note(`Answered by ${msg.model} (fallback model).`);

        if (msg.stop_reason === 'refusal') {
          out.note('Claude declined this request.' + (msg.stop_details?.explanation ? ' ' + msg.stop_details.explanation : ''));
          break;   // never run tools from a refused turn
        }
        if (msg.stop_reason === 'pause_turn') { this.messages.push({ role: 'assistant', content: msg.content }); continue; }

        const calls = msg.content.filter(b => b.type === 'tool_use');
        if (msg.stop_reason === 'max_tokens') {
          // a tool call cut off here usually still parses, as a truncated object: never run it
          if (!calls.length) this.messages.push({ role: 'assistant', content: msg.content });
          out.note(calls.length ? 'The reply ran out of room while writing a tool call; nothing was changed. Ask for a smaller step.' : 'The reply hit its length limit.');
          break;
        }
        this.messages.push({ role: 'assistant', content: msg.content });
        if (!calls.length) break;

        const results = [];
        for (const call of calls) {
          const row = out.tool(call.name, call.input);
          try {
            const res = await this.execute(call.name, call.input);
            const text = JSON.stringify(res ?? { ok: true });
            row.done(res);
            results.push({ type: 'tool_result', tool_use_id: call.id, content: text.length > 60000 ? text.slice(0, 60000) + '…(cut)' : text });
          } catch (err) {
            row.fail(err.message);
            const content = err.invalidInput ? JSON.stringify({ INVALID_INPUT: err.message, received: JSON.stringify(call.input).slice(0, 2000) }) : 'Error: ' + err.message;
            results.push({ type: 'tool_result', tool_use_id: call.id, is_error: true, content });
          }
        }
        this.messages.push({ role: 'user', content: results });   // every result for the turn in one message
        if (turn === MAX_TURNS - 1) out.note('Stopped after many steps; say "continue" to go on.');
      }
    } catch (err) {
      if (err instanceof Anthropic.APIUserAbortError || this.abort.signal.aborted) this.ui.error('Stopped.');
      else if (err instanceof Anthropic.AuthenticationError) this.ui.error('The API key was refused. Check it in AI settings.');
      else if (err instanceof Anthropic.RateLimitError) this.ui.error('Rate limited by the API; wait a moment and try again.');
      else if (err instanceof Anthropic.APIError) this.ui.error(`API error ${err.status ?? ''}: ${err.message}`);
      else this.ui.error(err.message || String(err));
      // keep the history valid: drop a dangling assistant turn whose tool calls never got results
      const last = this.messages[this.messages.length - 1];
      if (last?.role === 'assistant' && Array.isArray(last.content) && last.content.some(b => b.type === 'tool_use')) this.messages.pop();
      if (this.messages.length === start + 1) this.messages.length = start;   // nothing came back: forget the question
    } finally {
      this.busy = false;
      this.ui.busy(false);
      this.ui.usage(usage);
    }
  }
}
