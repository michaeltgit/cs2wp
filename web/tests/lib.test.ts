import { describe, expect, it } from 'vitest';
import { clamp, fmtClock, money, pct, signedPts, swingPill, teamColor, teamKey, timeAgo } from '@/lib/format';
import { COLOR } from '@/lib/constants';
import { deepLinkHash, parseDeepLink } from '@/lib/hash';
import { parseJSON } from '@/lib/json';
import { changeAt, lastAtOrBefore, lowerBound, seriesP } from '@/lib/series';
import { prepRound } from '@/lib/round';
import type { RoundData } from '@/api/types';

describe('format', () => {
  it('fmtClock pads seconds and clamps at zero', () => {
    expect(fmtClock(115)).toBe('1:55');
    expect(fmtClock(5.9)).toBe('0:05');
    expect(fmtClock(-3)).toBe('0:00');
    expect(fmtClock(600)).toBe('10:00');
  });

  it('pct / money / clamp', () => {
    expect(pct(0.456)).toBe('46%');
    expect(money(12500)).toBe('$12,500');
    expect(money(null)).toBe('');
    expect(clamp(5, 0, 3)).toBe(3);
    expect(clamp(-1, 0, 3)).toBe(0);
  });

  it('team helpers', () => {
    expect(teamKey(3)).toBe('ct');
    expect(teamKey(2)).toBe('t');
    expect(teamKey(null)).toBe('');
    expect(teamColor(3)).toBe(COLOR.ct);
    expect(teamColor(2)).toBe(COLOR.t);
    expect(teamColor(0)).toBe(COLOR.muted);
  });

  it('timeAgo buckets', () => {
    const now = 1_000_000_000_000;
    const s = now / 1000;
    expect(timeAgo(s - 5, now)).toBe('5s ago');
    expect(timeAgo(s - 120, now)).toBe('2m ago');
    expect(timeAgo(s - 7200, now)).toBe('2h ago');
    expect(timeAgo(null, now)).toBe('');
    expect(timeAgo('1791841089.2', 1791841089200 + 30_000)).toBe('30s ago');
  });

  it('swingPill', () => {
    expect(swingPill(null)).toBeNull();
    expect(swingPill(Number.NaN)).toBeNull();
    expect(swingPill(0.0001)).toEqual({ cls: 'zero', text: '±0%' });
    expect(swingPill(0.034)).toEqual({ cls: 'ct', text: '+3.4% CT' });
    expect(swingPill(-0.25)).toEqual({ cls: 't', text: '+25% T' });
  });

  it('signedPts uses a real minus sign', () => {
    expect(signedPts(0.0123)).toBe('+1.2 pts');
    expect(signedPts(-0.213)).toBe('−21.3 pts');
  });
});

describe('series', () => {
  const list: [number, string][] = [
    [10, 'a'],
    [20, 'b'],
    [30, 'c'],
  ];

  it('changeAt returns the last change at or before t', () => {
    expect(changeAt(list, 5)).toBeNull();
    expect(changeAt(list, 10)).toBe('a');
    expect(changeAt(list, 19)).toBe('a');
    expect(changeAt(list, 20)).toBe('b');
    expect(changeAt(list, 1e9)).toBe('c');
    expect(changeAt([], 1)).toBeNull();
    expect(changeAt(null, 1)).toBeNull();
  });

  it('lowerBound is clamped to the array', () => {
    const a = [1, 3, 5, 7];
    expect(lowerBound(a, 0)).toBe(0);
    expect(lowerBound(a, 3)).toBe(1);
    expect(lowerBound(a, 4)).toBe(2);
    expect(lowerBound(a, 100)).toBe(3);
    expect(lowerBound([], 1)).toBe(0);
  });

  it('lastAtOrBefore', () => {
    const a = [1, 3, 5];
    expect(lastAtOrBefore(a, 0)).toBe(-1);
    expect(lastAtOrBefore(a, 3)).toBe(1);
    expect(lastAtOrBefore(a, 4)).toBe(1);
    expect(lastAtOrBefore(a, 9)).toBe(2);
  });

  it('seriesP is a step function', () => {
    const t = [10, 20, 30];
    const p = [0.1, null, 0.3];
    expect(seriesP(t, p, 5)).toBe(0.1);
    expect(seriesP(t, p, 15)).toBe(0.1);
    expect(seriesP(t, p, 20)).toBeNull();
    expect(seriesP(t, p, 99)).toBe(0.3);
    expect(seriesP([], [], 1)).toBeNull();
  });
});

describe('parseJSON', () => {
  it('parses valid JSON untouched', () => {
    expect(parseJSON('{"a":[1,2],"b":"NaN"}')).toEqual({ a: [1, 2], b: 'NaN' });
  });

  it('maps bare NaN / Infinity / -Infinity to null', () => {
    expect(parseJSON('{"a": NaN, "b": [1, NaN, -Infinity], "c": Infinity}')).toEqual({ a: null, b: [1, null, null], c: null });
    expect(parseJSON('[NaN]')).toEqual([null]);
  });

  it('still throws on genuinely broken JSON', () => {
    expect(() => parseJSON('{oops')).toThrow();
  });
});

describe('deep links', () => {
  it('round-trips demo + round', () => {
    const h = deepLinkHash('abc def/1', 7);
    expect(h).toBe('#demo=abc%20def%2F1&round=7');
    expect(parseDeepLink(h)).toEqual({ demo: 'abc def/1', round: 7 });
  });

  it('round is optional; no demo means no link', () => {
    expect(parseDeepLink('#demo=x')).toEqual({ demo: 'x', round: null });
    expect(parseDeepLink('#round=3')).toBeNull();
    expect(parseDeepLink('')).toBeNull();
  });
});

describe('prepRound', () => {
  const raw: RoundData = {
    round: { round: 1, freeze_end: 100, end: 200, winner: 3, reason: 8, valid: true, ct_score: 0, t_score: 0 },
    tickrate: 64,
    ticks: [100, 101, 102, 103],
    p_ct: [null, 0.5, 0.6, null],
    players: [
      {
        steamid: '1', name: 'zed', team: 2, x: [0, 1, 2, 3], y: [0, 0, 0, 0], yaw: [0, 0, 0, 0],
        hp: [100, 100, 0, 0], alive: [1, 1, 0, 0], armor: [], weapon: [], has_bomb: [], money: [],
      },
      {
        steamid: '2', name: 'amy', team: 3, x: [null, 5, 6, 7], y: [0, 0, 0, 0], yaw: [0, 0, 0, 0],
        hp: [100, 100, 100, 100], alive: [1, 1, 1, 1], armor: [], weapon: [], has_bomb: [], money: [],
      },
    ],
    events: [
      { tick: 103, type: 'explode' },
      { tick: 101, type: 'smoke', x: 1, y: 2 },
      { tick: 102, type: 'kill', actor_team: 3, victim_team: 2 },
      { tick: 101, type: 'plant', x: 0, y: 0 },
      { tick: 101, type: 'flash', x: null, y: null },
    ],
  };
  const R = prepRound(raw);

  it('derives domain, feed, and bomb events', () => {
    expect(R.n).toBe(4);
    expect([R.t0, R.t1]).toEqual([100, 103]);
    expect(R.feed.map((e) => e.type)).toEqual(['plant', 'kill', 'explode']);
    expect(R.plant?.tick).toBe(101);
    expect(R.explode?.tick).toBe(103);
    expect(R.defuse).toBeNull();
    expect(R.nades.map((e) => e.type)).toEqual(['smoke']); // flash has no position
    expect(R.hasP).toBe(true);
  });

  it('sorts CT first then by name, and tracks the last alive index', () => {
    expect(R.players.map((p) => p.name)).toEqual(['amy', 'zed']);
    const zed = R.players[1]!;
    expect([...zed.lastAlive]).toEqual([0, 1, 1, 1]);
    const amy = R.players[0]!;
    expect([...amy.lastAlive]).toEqual([-1, 1, 2, 3]);
  });
});
