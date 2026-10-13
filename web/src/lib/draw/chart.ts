import type { RoundEvent, RoundMeta } from '@/api/types';
import { COLOR, TICKRATE } from '../constants';
import { clamp, fmtClock, teamColor } from '../format';
import { seriesP } from '../series';

export const CHART_PAD = { l: 40, r: 12, t: 10, b: 20 } as const;
export const CHART_HEIGHT = 220;

export interface ChartSeries {
  ticks: ArrayLike<number>;
  ps: ArrayLike<number | null>;
}

export interface ChartGeom {
  w: number;
  h: number;
  domain: [number, number];
}

export const chartX = (g: ChartGeom, tick: number): number => {
  const [a, b] = g.domain;
  return CHART_PAD.l + ((tick - a) / Math.max(1, b - a)) * (g.w - CHART_PAD.l - CHART_PAD.r);
};

export const chartY = (g: ChartGeom, p: number): number => CHART_PAD.t + (1 - p) * (g.h - CHART_PAD.t - CHART_PAD.b);

/** Pixel x (CSS px from the canvas' left edge) -> tick, clamped to the domain. */
export const chartTickAt = (g: ChartGeom, px: number): number => {
  const [a, b] = g.domain;
  return Math.round(a + clamp((px - CHART_PAD.l) / (g.w - CHART_PAD.l - CHART_PAD.r), 0, 1) * (b - a));
};

export interface ChartLayerInput extends ChartGeom {
  dpr: number;
  round: RoundMeta | null;
  series: ChartSeries;
  feed: RoundEvent[];
}

/** Static layer: grid, axis labels, the P(CT) line/area split at 50%, and event markers. */
export function renderChartLayer(layer: HTMLCanvasElement, inp: ChartLayerInput): void {
  const { w, h, dpr } = inp;
  layer.width = Math.max(1, Math.round(w * dpr));
  layer.height = Math.max(1, Math.round(h * dpr));
  const ctx = layer.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const X = (t: number) => chartX(inp, t);
  const Y = (p: number) => chartY(inp, p);
  const plotL = CHART_PAD.l;
  const plotR = w - CHART_PAD.r;
  const plotT = CHART_PAD.t;
  const plotB = h - CHART_PAD.b;
  const y50 = Y(0.5);

  // grid + y labels
  ctx.font = '10.5px system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'right';
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    const y = Math.round(Y(v)) + 0.5;
    ctx.strokeStyle = v === 0.5 ? '#4a5466' : COLOR.grid;
    ctx.setLineDash(v === 0.5 ? [5, 4] : []);
    ctx.beginPath();
    ctx.moveTo(plotL, y);
    ctx.lineTo(plotR, y);
    ctx.stroke();
    ctx.fillStyle = COLOR.faint;
    ctx.fillText(`${v * 100}%`, plotL - 6, y);
  }
  ctx.setLineDash([]);
  ctx.fillStyle = 'rgba(91,155,213,0.55)';
  ctx.textAlign = 'left';
  ctx.fillText('CT', plotL + 4, plotT + 7);
  ctx.fillStyle = 'rgba(232,163,61,0.55)';
  ctx.fillText('T', plotL + 4, plotB - 7);

  const rm = inp.round;
  const [a, b] = inp.domain;
  // x labels every 15 s of round time
  if (rm && b > a) {
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = COLOR.faint;
    const step = 15 * TICKRATE;
    for (let t = rm.freeze_end; t <= b; t += step) {
      if (t < a) continue;
      const x = X(t);
      ctx.fillStyle = COLOR.faint;
      ctx.fillText(fmtClock((t - rm.freeze_end) / TICKRATE), x, plotB + 5);
      ctx.strokeStyle = 'rgba(38,45,56,0.6)';
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, plotT);
      ctx.lineTo(Math.round(x) + 0.5, plotB);
      ctx.stroke();
    }
    if (rm.end >= a && rm.end <= b) {
      const x = Math.round(X(rm.end)) + 0.5;
      ctx.strokeStyle = '#4a5466';
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(x, plotT);
      ctx.lineTo(x, plotB);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = COLOR.faint;
      ctx.textAlign = 'right';
      ctx.fillText('end', x - 3, plotT);
    }
  }

  // line + area, split into segments at nulls
  const { ticks, ps } = inp.series;
  const segs: [number, number][][] = [];
  let cur: [number, number][] | null = null;
  for (let i = 0; i < ticks.length; i++) {
    const p = ps[i];
    if (p == null) {
      cur = null;
      continue;
    }
    if (!cur) {
      cur = [];
      segs.push(cur);
    }
    cur.push([X(ticks[i]!), Y(p)]);
  }
  for (const top of [true, false]) {
    ctx.save();
    ctx.beginPath();
    if (top) ctx.rect(plotL, plotT - 2, plotR - plotL, y50 - plotT + 2);
    else ctx.rect(plotL, y50, plotR - plotL, plotB - y50 + 2);
    ctx.clip();
    const col = top ? COLOR.ct : COLOR.t;
    for (const seg of segs) {
      ctx.beginPath();
      ctx.moveTo(seg[0]![0], y50);
      for (const [x, y] of seg) ctx.lineTo(x, y);
      ctx.lineTo(seg[seg.length - 1]![0], y50);
      ctx.closePath();
      ctx.fillStyle = top ? 'rgba(91,155,213,0.16)' : 'rgba(232,163,61,0.16)';
      ctx.fill();
      ctx.beginPath();
      seg.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      if (seg.length === 1) ctx.lineTo(seg[0]![0] + 1, seg[0]![1]);
      ctx.strokeStyle = col;
      ctx.lineWidth = 1.8;
      ctx.lineJoin = 'round';
      ctx.stroke();
    }
    ctx.restore();
  }

  // event markers (from the stored round, same round in both modes)
  for (const e of inp.feed) {
    if (e.type === 'defuse_start' || e.tick < a || e.tick > b) continue;
    const p = seriesP(ticks, ps, e.tick);
    const x = X(e.tick);
    const y = Y(p ?? 0.5);
    ctx.save();
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = 'rgba(10,12,16,0.9)';
    if (e.type === 'kill') {
      ctx.fillStyle = teamColor(Number(e.actor_team));
      ctx.beginPath();
      ctx.arc(x, y, 3.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    } else if (e.type === 'plant') {
      ctx.fillStyle = COLOR.bomb;
      ctx.beginPath();
      ctx.moveTo(x, y - 6);
      ctx.lineTo(x + 5.5, y + 4);
      ctx.lineTo(x - 5.5, y + 4);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    } else if (e.type === 'defuse') {
      ctx.fillStyle = COLOR.ct;
      ctx.beginPath();
      ctx.moveTo(x, y - 6);
      ctx.lineTo(x + 5, y);
      ctx.lineTo(x, y + 6);
      ctx.lineTo(x - 5, y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    } else if (e.type === 'explode') {
      ctx.fillStyle = COLOR.bomb;
      ctx.beginPath();
      for (let i = 0; i < 10; i++) {
        const ang = -Math.PI / 2 + (i * Math.PI) / 5;
        const rad = i % 2 ? 3 : 7;
        ctx.lineTo(x + Math.cos(ang) * rad, y + Math.sin(ang) * rad);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }
}

/** Blit the cached layer, then draw the playhead + current-probability dot. */
export function drawChartFrame(
  ctx: CanvasRenderingContext2D,
  layer: HTMLCanvasElement,
  g: ChartGeom & { dpr: number },
  cursor: { tick: number; p: number | null } | null,
): void {
  const cv = ctx.canvas;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (layer.width > 0 && layer.height > 0) ctx.drawImage(layer, 0, 0);
  ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
  if (!cursor) return;
  const x = Math.round(chartX(g, cursor.tick)) + 0.5;
  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, CHART_PAD.t - 4);
  ctx.lineTo(x, g.h - CHART_PAD.b);
  ctx.stroke();
  const p = cursor.p;
  if (p != null) {
    ctx.fillStyle = p >= 0.5 ? COLOR.ct : COLOR.t;
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(x, chartY(g, p), 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}
