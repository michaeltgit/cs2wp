import { COLOR, CT, T } from './constants';

export const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, v));

export const teamKey = (t: number | null | undefined): '' | 'ct' | 't' => (t === CT ? 'ct' : t === T ? 't' : '');

export const teamColor = (t: number | null | undefined): string =>
  t === CT ? COLOR.ct : t === T ? COLOR.t : COLOR.muted;

export const pct = (p: number): string => `${Math.round(p * 100)}%`;

export const money = (v: number | null | undefined): string =>
  v == null ? '' : `$${Number(v).toLocaleString('en-US')}`;

/** m:ss, clamped at 0. */
export function fmtClock(sec: number): string {
  sec = Math.max(0, sec);
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Relative time for a unix-seconds timestamp. */
export function timeAgo(ts: number | string | null | undefined, now: number = Date.now()): string {
  const t = Number(ts);
  if (!ts || !Number.isFinite(t)) return '';
  const d = now / 1000 - t;
  if (d < 60) return `${Math.max(0, Math.round(d))}s ago`;
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${Math.round(d / 3600)}h ago`;
  return new Date(t * 1000).toLocaleDateString();
}

/** Signed percentage points with a real minus sign, e.g. "+3.2 pts" / "−1.0 pts". */
export const signedPts = (x: number): string => `${x >= 0 ? '+' : '−'}${Math.abs(x * 100).toFixed(1)} pts`;

export interface SwingPill {
  cls: 'zero' | 'ct' | 't';
  text: string;
}

/** Kill-feed swing badge: how much the event moved P(CT). */
export function swingPill(sw: number | null | undefined): SwingPill | null {
  if (sw == null || Number.isNaN(sw)) return null;
  const v = sw * 100;
  const fmt = (x: number) => (Math.abs(x) >= 10 ? String(Math.round(Math.abs(x))) : Math.abs(x).toFixed(1));
  if (Math.abs(v) < 0.05) return { cls: 'zero', text: '±0%' };
  return v > 0 ? { cls: 'ct', text: `+${fmt(v)}% CT` } : { cls: 't', text: `+${fmt(v)}% T` };
}

/** "mid≈" helper used by tooltips: a fraction to "x.x pts" or an en dash. */
export const ptsOrDash = (v: number | null | undefined): string => (v != null ? `${(v * 100).toFixed(1)} pts` : '–');
