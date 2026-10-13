import type { KalshiMarketPoint, MapWinSeries, RoundMeta } from '@/api/types';
import { COLOR, MAPC, TICKRATE } from '../constants';
import { clamp, fmtClock } from '../format';
import { lastAtOrBefore, lowerBound } from '../series';
import type { MapRoundView, MapZoom } from '@/stores/mapOdds';

export const MAP_PAD = { l: 40, r: 12, t: 10, b: 22 } as const;
export const MAP_HEIGHT = 200;

export interface MapChartInput {
  w: number;
  h: number;
  zoom: MapZoom;
  data: MapWinSeries;
  market: KalshiMarketPoint[] | null;
  rounds: RoundMeta[];
  roundNo: number | null;
  /** current round meta (round zoom domain) */
  current: RoundMeta | null;
  roundView: MapRoundView | null;
  /** playhead tick, or null */
  cursor: number | null;
}

/** What the readout above the chart shows. */
export type MapReadout =
  | { kind: 'none' }
  | { kind: 'loading' }
  | { kind: 'match'; team: string; ours: number | null; kalshi: { mid: number; bid: number | null; ask: number | null } | null }
  | {
      kind: 'round';
      team: string;
      ours: number | null;
      trade: { price: number; ago: number; count: number; gap: number | null } | null;
      note: 'nolink' | 'notrades' | null;
    };

export function mapDomain(zoom: MapZoom, current: RoundMeta | null, data: MapWinSeries | null): [number, number] {
  if (zoom === 'round' && current) return [current.freeze_end, current.end + 3 * TICKRATE];
  const t = data?.tick;
  return t?.length ? [t[0]!, t[t.length - 1]!] : [0, 1];
}

export const mapX = (w: number, dom: [number, number], tick: number): number =>
  MAP_PAD.l + ((tick - dom[0]) / Math.max(1, dom[1] - dom[0])) * (w - MAP_PAD.l - MAP_PAD.r);

export const mapY = (h: number, p: number): number => MAP_PAD.t + (1 - p) * (h - MAP_PAD.t - MAP_PAD.b);

export const mapTickAt = (w: number, dom: [number, number], px: number): number =>
  Math.round(dom[0] + clamp((px - MAP_PAD.l) / (w - MAP_PAD.l - MAP_PAD.r), 0, 1) * (dom[1] - dom[0]));

/** Market points with a mid inside the domain. */
export function visibleMarket(market: KalshiMarketPoint[] | null, dom: [number, number]) {
  return (market || []).filter(
    (m): m is KalshiMarketPoint & { mid_a: number } => m.mid_a != null && m.tick >= dom[0] && m.tick <= dom[1],
  );
}

export function drawMapChart(ctx: CanvasRenderingContext2D, inp: MapChartInput): MapReadout {
  const { w, h } = inp;
  const P = MAP_PAD;
  ctx.clearRect(0, 0, w, h);
  const dom = mapDomain(inp.zoom, inp.current, inp.data);
  const X = (t: number) => mapX(w, dom, t);
  const Y = (p: number) => mapY(h, p);
  ctx.font = '11px system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  for (const g of [0, 0.25, 0.5, 0.75, 1]) {
    ctx.strokeStyle = g === 0.5 ? '#3a4352' : COLOR.grid;
    ctx.setLineDash(g === 0.5 ? [4, 4] : []);
    ctx.beginPath();
    ctx.moveTo(P.l, Y(g));
    ctx.lineTo(w - P.r, Y(g));
    ctx.stroke();
    ctx.fillStyle = COLOR.faint;
    ctx.textAlign = 'right';
    ctx.fillText(`${g * 100}%`, P.l - 6, Y(g));
  }
  ctx.setLineDash([]);
  const teamA = inp.data.teams?.a?.name || 'Team A';
  if (inp.zoom === 'round') return drawRound(ctx, inp, dom, teamA);

  // round boundaries; highlight the open round
  ctx.textAlign = 'center';
  const rounds = inp.rounds;
  for (const r of rounds) {
    const x = X(r.freeze_end);
    if (r.round === inp.roundNo) {
      ctx.fillStyle = 'rgba(255,255,255,0.05)';
      ctx.fillRect(x, P.t, X(r.end) - x, h - P.t - P.b);
    }
    ctx.strokeStyle = r.round === 13 ? '#4a5466' : '#20262f';
    ctx.beginPath();
    ctx.moveTo(x, P.t);
    ctx.lineTo(x, h - P.b);
    ctx.stroke();
    if (rounds.length <= 30 || r.round % 3 === 1) {
      ctx.fillStyle = COLOR.faint;
      ctx.fillText(String(r.round), x + 6, h - P.b + 11);
    }
  }
  // Kalshi: bid-ask band + mid
  const mk = visibleMarket(inp.market, dom);
  if (mk.length) {
    ctx.fillStyle = 'rgba(177,151,252,0.16)';
    ctx.beginPath();
    mk.forEach((m, i) => (i ? ctx.lineTo(X(m.tick), Y(m.ask_a ?? m.mid_a)) : ctx.moveTo(X(m.tick), Y(m.ask_a ?? m.mid_a))));
    for (let i = mk.length - 1; i >= 0; i--) ctx.lineTo(X(mk[i]!.tick), Y(mk[i]!.bid_a ?? mk[i]!.mid_a));
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = MAPC.kal;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    mk.forEach((m, i) => (i ? ctx.lineTo(X(m.tick), Y(m.mid_a)) : ctx.moveTo(X(m.tick), Y(m.mid_a))));
    ctx.stroke();
  }
  // our model (a new sub-path per round)
  const { tick, p_map_a: pv, round: rr } = inp.data;
  ctx.strokeStyle = MAPC.ours;
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  let started = false;
  let prevR: number | null = null;
  for (let i = 0; i < tick.length; i++) {
    const p = pv[i];
    if (p == null) {
      started = false;
      continue;
    }
    const x = X(tick[i]!);
    const y = Y(p);
    if (!started || rr[i] !== prevR) {
      ctx.moveTo(x, y);
      started = true;
    } else ctx.lineTo(x, y);
    prevR = rr[i] ?? null;
  }
  ctx.stroke();
  ctx.lineWidth = 1;
  const cur = inp.cursor;
  if (cur == null) return { kind: 'none' };
  drawCursor(ctx, X(cur), h);
  const i = clamp(lowerBound(tick, cur), 0, tick.length - 1);
  let km: (typeof mk)[number] | null = null;
  for (const m of mk) {
    if (m.tick <= cur) km = m;
    else break;
  }
  return {
    kind: 'match',
    team: teamA,
    ours: pv[i] ?? null,
    kalshi: km ? { mid: km.mid_a, bid: km.bid_a, ask: km.ask_a } : null,
  };
}

function drawCursor(ctx: CanvasRenderingContext2D, x: number, h: number) {
  ctx.strokeStyle = '#ffffff';
  ctx.globalAlpha = 0.7;
  ctx.beginPath();
  ctx.moveTo(x, MAP_PAD.t);
  ctx.lineTo(x, h - MAP_PAD.b);
  ctx.stroke();
  ctx.globalAlpha = 1;
}

function drawRound(ctx: CanvasRenderingContext2D, inp: MapChartInput, dom: [number, number], teamA: string): MapReadout {
  const { w, h } = inp;
  const P = MAP_PAD;
  const [a, b] = dom;
  const X = (t: number) => mapX(w, dom, t);
  const Y = (p: number) => mapY(h, p);
  ctx.textAlign = 'center';
  for (let sec = 0; sec <= (b - a) / TICKRATE; sec += 15) {
    ctx.fillStyle = COLOR.faint;
    ctx.fillText(fmtClock(sec), X(a + sec * TICKRATE), h - P.b + 11);
  }
  const R = inp.roundView;
  if (!R) return { kind: 'loading' };
  const tr = R.trades;
  // Kalshi: last-trade step line + one dot per trade (area ~ size)
  if (tr?.tick?.length) {
    ctx.strokeStyle = MAPC.kal;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let px: number | null = null;
    tr.tick.forEach((t, i) => {
      const x = X(clamp(t, a, b));
      const y = Y(tr.price_a[i]!);
      if (px == null) ctx.moveTo(x, y);
      else {
        ctx.lineTo(x, Y(tr.price_a[i - 1]!));
        ctx.lineTo(x, y);
      }
      px = x;
    });
    ctx.lineTo(X(b), Y(tr.price_a[tr.price_a.length - 1]!));
    ctx.stroke();
    ctx.fillStyle = 'rgba(177,151,252,0.55)';
    tr.tick.forEach((t, i) => {
      if (t < a) return;
      ctx.beginPath();
      ctx.arc(X(t), Y(tr.price_a[i]!), clamp(Math.sqrt(tr.count[i] ?? 0) / 2, 1.5, 7), 0, Math.PI * 2);
      ctx.fill();
    });
  }
  // our map odds for this round at full tick rate
  const d = R.data;
  if (d?.tick?.length) {
    ctx.strokeStyle = MAPC.ours;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    let pen = false;
    d.tick.forEach((t, i) => {
      const p = d.p_map_a[i];
      if (p == null) {
        pen = false;
        return;
      }
      if (pen) ctx.lineTo(X(t), Y(p));
      else ctx.moveTo(X(t), Y(p));
      pen = true;
    });
    ctx.stroke();
  }
  ctx.lineWidth = 1;
  const cur = inp.cursor;
  if (cur == null) return { kind: 'none' };
  drawCursor(ctx, X(cur), h);
  const ours = d?.tick?.length ? d.p_map_a[clamp(lowerBound(d.tick, cur), 0, d.tick.length - 1)] ?? null : null;
  const j = tr?.tick?.length ? lastAtOrBefore(tr.tick, cur) : -1;
  if (tr && j >= 0) {
    const price = tr.price_a[j]!;
    return {
      kind: 'round',
      team: teamA,
      ours,
      trade: { price, ago: (cur - tr.tick[j]!) / TICKRATE, count: tr.count[j]!, gap: ours != null ? (ours - price) * 100 : null },
      note: null,
    };
  }
  return { kind: 'round', team: teamA, ours, trade: null, note: tr ? 'notrades' : 'nolink' };
}
