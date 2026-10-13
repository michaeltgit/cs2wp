import type { RoundData, RoundEvent, RoundMeta, RoundPlayer } from '@/api/types';
import { FEED_TYPES, NADES, type NadeType } from './constants';

export interface PreparedPlayer extends RoundPlayer {
  /** index of the last tick <= i where the player was alive with a position, or -1 */
  lastAlive: Int32Array;
}

export interface NadeEvent extends RoundEvent {
  type: NadeType;
  x: number;
  y: number;
}

/** A round from GET /rounds/{n}, plus derived lookups. Treated as immutable and never made reactive. */
export interface PreparedRound {
  round: RoundMeta;
  tickrate: number;
  ticks: number[];
  p_ct: (number | null)[];
  players: PreparedPlayer[];
  events: RoundEvent[];
  n: number;
  t0: number;
  t1: number;
  feed: RoundEvent[];
  plant: RoundEvent | null;
  defuse: RoundEvent | null;
  explode: RoundEvent | null;
  nades: NadeEvent[];
  hasP: boolean;
  /** cached fallback radar bounds when no map outline is available */
  bounds?: [number, number, number, number];
}

const isNade = (e: RoundEvent): e is NadeEvent => e.type in NADES && e.x != null && e.y != null;

export function prepRound(R: RoundData): PreparedRound {
  const n = R.ticks.length;
  const players: PreparedPlayer[] = R.players.map((p) => {
    const la = new Int32Array(n);
    let last = -1;
    for (let i = 0; i < n; i++) {
      if (p.alive[i] === 1 && p.x[i] != null) last = i;
      la[i] = last;
    }
    return { ...p, lastAlive: la };
  });
  players.sort((a, b) => b.team - a.team || String(a.name).localeCompare(String(b.name)));
  const events = (R.events || []).filter((e) => e && e.tick != null).sort((a, b) => a.tick - b.tick);
  return {
    round: R.round,
    tickrate: R.tickrate,
    ticks: R.ticks,
    p_ct: R.p_ct,
    players,
    events,
    n,
    t0: R.ticks[0] ?? 0,
    t1: R.ticks[n - 1] ?? 0,
    feed: events.filter((e) => FEED_TYPES.has(e.type)),
    plant: events.find((e) => e.type === 'plant') ?? null,
    defuse: events.find((e) => e.type === 'defuse') ?? null,
    explode: events.find((e) => e.type === 'explode') ?? null,
    nades: events.filter(isNade),
    hasP: R.p_ct.some((v) => v != null),
  };
}
