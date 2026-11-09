// frontend/src/lib/studio/osc.ts
// OSC output: turn each engine OutputFrame into OSC messages and stream them
// to the backend (/api/studio/osc), which sends them on over UDP.
// Design + address list: docs/superpowers/plans/2026-11-08-studio-osc-output.md

import { artLab, labToRgb, type ArtSettings } from './art';
import type { OutputFrame } from './engine';

export type OscGroup = 'aus' | 'ausRelative' | 'emotions' | 'mood' | 'eyes' | 'head' | 'colour' | 'events' | 'sync';

export interface OscSettings {
  enabled: boolean;
  host: string;
  port: number;
  /** Address prefix, e.g. '/pyfeat'. */
  prefix: string;
  /** Allow a destination other than this computer. */
  allowLan: boolean;
  groups: Record<OscGroup, boolean>;
}

export const OSC_GROUP_LABELS: Record<OscGroup, { label: string; hint: string }> = {
  emotions: { label: 'Emotions', hint: '…/emotion/happiness 0–1' },
  mood: { label: 'Mood & energy', hint: '…/valence, …/arousal, …/energy, /group/…' },
  aus: { label: 'Facial movements', hint: '…/au/AU12 0–1' },
  ausRelative: { label: 'Facial movements, relative to each person', hint: '…/auz/AU12 (≈0 at rest)' },
  eyes: { label: 'Eyes', hint: '…/gaze/x, y, away, movement' },
  head: { label: 'Head', hint: '…/head/turn, nod, tilt (radians), movement' },
  colour: { label: 'Art colour', hint: '…/color r g b (0–1)' },
  events: { label: 'Bursts, rises, glances, head moves', hint: '…/onset/AU12, …/onset/happiness, …/glance, …/headmove' },
  sync: { label: 'Synchrony & mimicry', hint: '/sync, /sync/1/2, /mimicry' },
};

export const DEFAULT_OSC: OscSettings = {
  enabled: false,
  host: '127.0.0.1',
  port: 9000,
  prefix: '/pyfeat',
  allowLan: false,
  groups: { emotions: true, mood: true, aus: true, ausRelative: false, eyes: true, head: true, colour: true, events: true, sync: true },
};

export function normalizePrefix(p: string): string {
  const clean = p.trim().replace(/[^A-Za-z0-9/_-]/g, '').replace(/\/+/g, '/').replace(/\/$/, '');
  return clean ? (clean.startsWith('/') ? clean : `/${clean}`) : DEFAULT_OSC.prefix;
}

export function normalizeOsc(v: Partial<OscSettings> | null | undefined): OscSettings {
  const d = DEFAULT_OSC;
  if (!v || typeof v !== 'object') return structuredClone(d);
  const groups = { ...d.groups };
  for (const k of Object.keys(groups) as OscGroup[]) {
    if (typeof v.groups?.[k] === 'boolean') groups[k] = v.groups[k];
  }
  return {
    enabled: v.enabled === true,
    host: typeof v.host === 'string' && v.host.trim() ? v.host.trim().slice(0, 253) : d.host,
    port: Number.isInteger(v.port) && v.port! >= 1 && v.port! <= 65535 ? v.port! : d.port,
    prefix: typeof v.prefix === 'string' ? normalizePrefix(v.prefix) : d.prefix,
    allowLan: v.allowLan === true,
    groups,
  };
}

/** One OSC message as sent to the backend: [address, type tags, args]. */
export type OscMsg = [string, string, (number | string)[]];

const f = (addr: string, v: number | undefined): OscMsg | null =>
  v === undefined || !Number.isFinite(v) ? null : [addr, 'f', [v]];

/** Address (under the person) for an engine onset feature. Emotion and mood
 *  names don't collide with AU names, so they share `onset/`. */
export function onsetAddress(feature: string): string {
  if (feature === 'gaze:shift') return 'glance';
  if (feature === 'pose:movement') return 'headmove';
  if (feature.startsWith('emotion:')) return `onset/${feature.slice(8)}`;
  return `onset/${feature}`;
}

/**
 * Builds the messages for each frame. Stateful only to announce departures:
 * a person who leaves gets one `present 0`.
 */
export class OscFrameBuilder {
  private present = new Set<number>();

  build(frame: OutputFrame, s: OscSettings, art: ArtSettings): OscMsg[] {
    const P = normalizePrefix(s.prefix);
    const g = s.groups;
    const out: (OscMsg | null)[] = [[`${P}/count`, 'i', [frame.people.length]]];
    const now = new Set<number>();
    const byslot = new Map(frame.people.map(p => [p.slot, p.n]));
    let gv = 0, ge = 0, gn = 0;

    for (const p of frame.people) {
      const base = `${P}/person/${p.n}`;
      now.add(p.n);
      out.push([`${base}/present`, 'i', [1]], f(`${base}/x`, p.x));
      if (g.aus || g.ausRelative) {
        for (const [k, v] of Object.entries(p.values)) {
          if (!/^AU\d+$/.test(k)) continue;
          if (g.aus) out.push(f(`${base}/au/${k}`, v));
          if (g.ausRelative) out.push(f(`${base}/auz/${k}`, p.z[k]));
        }
      }
      if (g.emotions && p.emotions) {
        for (const [k, v] of Object.entries(p.emotions)) out.push(f(`${base}/emotion/${k}`, v));
      }
      if (g.mood) {
        out.push(f(`${base}/valence`, p.valence), f(`${base}/arousal`, p.arousal), f(`${base}/energy`, p.energy));
        if (p.valence !== undefined) { gv += p.valence; gn++; }
        ge += p.energy;
      }
      if (g.eyes) {
        out.push(
          f(`${base}/gaze/x`, p.values['gaze:horizontal']),
          f(`${base}/gaze/y`, p.values['gaze:vertical']),
          f(`${base}/gaze/away`, p.values['gaze:away']),
          f(`${base}/gaze/movement`, p.z['gaze:shift']),
        );
      }
      if (g.head) {
        out.push(
          f(`${base}/head/turn`, p.values['pose:turn']),
          f(`${base}/head/nod`, p.values['pose:nod']),
          f(`${base}/head/tilt`, p.values['pose:tilt']),
          f(`${base}/head/movement`, p.z['pose:movement']),
        );
      }
      if (g.colour) {
        const [L, A, B] = artLab(p, art);
        const [r, gg, b] = labToRgb(L, A, B);
        out.push([`${base}/color`, 'fff', [r / 255, gg / 255, b / 255]]);
      }
    }
    for (const n of this.present) if (!now.has(n)) out.push([`${P}/person/${n}/present`, 'i', [0]]);
    this.present = now;

    if (g.mood && frame.people.length) {
      if (gn) out.push(f(`${P}/group/valence`, gv / gn));
      out.push(f(`${P}/group/energy`, ge / frame.people.length));
    }
    if (g.events) {
      for (const o of frame.onsets) {
        const n = byslot.get(o.slot);
        if (n === undefined) continue;
        out.push(f(`${P}/person/${n}/${onsetAddress(o.feature)}`, o.strength));
      }
    }
    if (g.sync) {
      let best = 0;
      for (const pr of frame.pairs) {
        const a = byslot.get(pr.a), b = byslot.get(pr.b);
        if (a === undefined || b === undefined) continue;
        best = Math.max(best, pr.strength);
        out.push(f(`${P}/sync/${Math.min(a, b)}/${Math.max(a, b)}`, pr.strength));
      }
      out.push(f(`${P}/sync`, best));
      for (const m of frame.mimicry) {
        const a = byslot.get(m.leader), b = byslot.get(m.follower);
        if (a !== undefined && b !== undefined) out.push([`${P}/mimicry`, 'iisf', [a, b, m.feature, m.latency]]);
      }
    }
    return out.filter((m): m is OscMsg => m !== null);
  }

  reset(): void {
    this.present.clear();
  }
}

export type OscStatus = 'off' | 'connecting' | 'sending' | 'error';

export interface OscStats {
  /** Messages and packets per second (last report), and errors. */
  messages: number;
  packets: number;
  errors: number;
  lastError?: string;
}

/**
 * The page's end of /api/studio/osc. Reconnects with backoff while running;
 * drops a frame rather than queue when the socket is backed up (stale
 * expression data is worse than missing data).
 */
export class OscLink {
  status: OscStatus = 'off';
  error: string | null = null;
  stats: OscStats = { messages: 0, packets: 0, errors: 0 };
  private ws: WebSocket | null = null;
  private settings: OscSettings | null = null;
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;

  constructor(private onChange: () => void, private url = defaultUrl()) {}

  /** Start, retarget or stop according to the settings. */
  apply(s: OscSettings): void {
    this.settings = s;
    if (!s.enabled) { this.stop(); return; }
    this.running = true;
    if (this.ws?.readyState === WebSocket.OPEN) this.sendConfig();
    else if (!this.ws) this.connect();
  }

  send(msgs: OscMsg[]): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN || this.status !== 'sending' || !msgs.length) return;
    if (ws.bufferedAmount > 256 * 1024) return;
    ws.send(JSON.stringify({ type: 'frame', msgs }));
  }

  test(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'test', address: `${normalizePrefix(this.settings?.prefix ?? '')}/test` }));
    }
  }

  stop(): void {
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const ws = this.ws;
    this.ws = null;
    ws?.close();
    this.set('off', null);
  }

  private connect(): void {
    this.set('connecting', null);
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      this.fail(`Couldn’t reach the backend: ${(e as Error).message}`);
      return;
    }
    this.ws = ws;
    ws.onopen = () => { this.retry = 0; this.sendConfig(); };
    ws.onmessage = (ev) => {
      let m: { type?: string; ok?: boolean; error?: string } & Partial<OscStats>;
      try { m = JSON.parse(String(ev.data)); } catch { return; }
      if (m.type === 'status') {
        if (m.ok) this.set('sending', null);
        else this.set('error', m.error ?? 'Destination rejected.');
      } else if (m.type === 'stats') {
        this.stats = { messages: m.messages ?? 0, packets: m.packets ?? 0, errors: m.errors ?? 0, lastError: m.lastError };
        this.onChange();
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // replaced or stopped
      this.ws = null;
      if (this.running) this.fail('Lost connection to the backend; retrying…');
    };
  }

  private sendConfig(): void {
    const s = this.settings;
    if (!s || this.ws?.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({ type: 'config', host: s.host, port: s.port, allowLan: s.allowLan }));
  }

  private fail(msg: string): void {
    this.set('error', msg);
    if (!this.running) return;
    const delay = Math.min(10000, 500 * 2 ** this.retry++);
    this.timer = setTimeout(() => { this.timer = null; if (this.running && !this.ws) this.connect(); }, delay);
  }

  private set(status: OscStatus, error: string | null): void {
    this.status = status;
    this.error = error;
    this.onChange();
  }
}

function defaultUrl(): string {
  if (typeof location === 'undefined') return 'ws://127.0.0.1/api/studio/osc';
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/studio/osc`;
}
