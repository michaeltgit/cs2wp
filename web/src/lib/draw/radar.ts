import { BOMB_TIME, COLOR, NADES, TICKRATE } from '../constants';
import { clamp, teamColor } from '../format';
import type { MapAsset } from '../mapAsset';
import type { PreparedRound } from '../round';

export interface RadarPlayer {
  team: number;
  alive: boolean;
  hp: number;
  x: number | null;
  y: number | null;
  yaw: number | null;
  name: string;
  bomb: boolean;
}

export interface RadarInput {
  w: number;
  h: number;
  map: MapAsset | null;
  /** stored round (nades/bomb are drawn from it in replay mode; also used for fallback bounds) */
  R: PreparedRound | null;
  players: RadarPlayer[];
  tick: number;
  replay: boolean;
  /** anything to draw at all (a round, or a live frame) */
  active: boolean;
}

interface Transform {
  s: number;
  rect: [number, number, number, number];
  x: (x: number) => number;
  y: (y: number) => number;
}

/** Map outline bounds, or fit to positions seen this round (cached on the round). */
export function radarBounds(map: MapAsset | null, R: PreparedRound | null, players: RadarPlayer[]): [number, number, number, number] {
  if (map?.bounds) return map.bounds;
  if (R?.bounds) return R.bounds;
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  const add = (x: number, y: number) => {
    x0 = Math.min(x0, x);
    x1 = Math.max(x1, x);
    y0 = Math.min(y0, y);
    y1 = Math.max(y1, y);
  };
  if (R) {
    for (const p of R.players)
      for (let i = 0; i < R.n; i += 16) {
        const x = p.x[i];
        const y = p.y[i];
        if (x != null && y != null) add(x, y);
      }
  } else {
    for (const p of players) if (p.x != null && p.y != null) add(p.x, p.y);
  }
  if (!Number.isFinite(x0)) return [-3000, 3000, -3000, 3000];
  const b: [number, number, number, number] = [x0 - 400, x1 + 400, y0 - 400, y1 + 400];
  if (R) R.bounds = b;
  return b;
}

function transform(w: number, h: number, [x0, x1, y0, y1]: [number, number, number, number]): Transform {
  const pad = 6;
  const s = Math.min((w - 2 * pad) / (x1 - x0), (h - 2 * pad) / (y1 - y0));
  const ox = (w - (x1 - x0) * s) / 2;
  const oy = (h - (y1 - y0) * s) / 2;
  return {
    s,
    rect: [ox, oy, (x1 - x0) * s, (y1 - y0) * s],
    x: (x) => ox + (x - x0) * s,
    y: (y) => oy + (y1 - y) * s,
  };
}

export function drawRadar(ctx: CanvasRenderingContext2D, inp: RadarInput): void {
  const { w, h } = inp;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#0b0d11';
  ctx.fillRect(0, 0, w, h);
  if (!inp.active) return;
  const tf = transform(w, h, radarBounds(inp.map, inp.R, inp.players));
  const map = inp.map;
  if (map?.img) {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(map.img, ...tf.rect);
  }
  if (map?.sites) {
    ctx.save();
    ctx.font = `800 ${Math.round(w / 11)}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(255,255,255,0.13)';
    for (const [k, [x, y]] of Object.entries(map.sites)) ctx.fillText(k, tf.x(x), tf.y(y));
    ctx.restore();
  }
  if (inp.R && inp.replay) {
    drawNades(ctx, tf, inp.tick, inp.R);
    drawBomb(ctx, tf, inp.tick, inp.R);
  }
  const r = clamp(w / 95, 4.5, 8);
  // dead first, so the living draw on top
  for (const p of inp.players) if (!p.alive && p.x != null) drawDead(ctx, tf, p, r);
  for (const p of inp.players) if (p.alive && p.x != null) drawPlayer(ctx, tf, p, r);
}

function drawNades(ctx: CanvasRenderingContext2D, tf: Transform, tick: number, R: PreparedRound) {
  for (const e of R.nades) {
    const spec = NADES[e.type];
    const dt = (tick - e.tick) / TICKRATE;
    if (dt < 0 || dt > spec.dur) continue;
    const x = tf.x(e.x);
    const y = tf.y(e.y);
    ctx.save();
    if (e.type === 'smoke') {
      const fade = Math.min(1, dt / 0.6, (spec.dur - dt) / 1.0);
      ctx.fillStyle = `rgba(185,192,204,${0.32 * fade})`;
      ctx.strokeStyle = `rgba(210,215,225,${0.45 * fade})`;
      ctx.beginPath();
      ctx.arc(x, y, spec.r * tf.s, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    } else if (e.type === 'molotov') {
      const fade = Math.min(1, dt / 0.3, (spec.dur - dt) / 0.7);
      ctx.fillStyle = `rgba(240,120,40,${0.28 * fade})`;
      ctx.strokeStyle = `rgba(255,150,60,${0.6 * fade})`;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.arc(x, y, spec.r * tf.s, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    } else if (e.type === 'flash') {
      const k = dt / spec.dur;
      ctx.strokeStyle = `rgba(255,255,255,${0.9 * (1 - k)})`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, Math.max(4, (40 + 260 * k) * tf.s), 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = `rgba(255,255,255,${0.5 * (1 - k)})`;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    } else if (e.type === 'he') {
      const k = dt / spec.dur;
      const rr = Math.max(4, (40 + 180 * k) * tf.s);
      ctx.fillStyle = `rgba(255,220,70,${0.55 * (1 - k)})`;
      ctx.beginPath();
      for (let i = 0; i < 16; i++) {
        const a = (i / 16) * Math.PI * 2;
        const rad = i % 2 ? rr * 0.45 : rr;
        ctx.lineTo(x + Math.cos(a) * rad, y + Math.sin(a) * rad);
      }
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  }
}

function drawBomb(ctx: CanvasRenderingContext2D, tf: Transform, tick: number, R: PreparedRound) {
  const pl = R.plant;
  if (!pl || pl.x == null || pl.y == null || tick < pl.tick || tick > R.round.end) return;
  const x = tf.x(pl.x);
  const y = tf.y(pl.y);
  const defused = !!R.defuse && tick >= R.defuse.tick;
  // blink faster as the timer runs down (tick-based, so it follows playback)
  const rem = BOMB_TIME - (tick - pl.tick) / TICKRATE;
  const period = rem > 10 ? 64 : rem > 5 ? 32 : 16;
  const on = defused || Math.floor((tick - pl.tick) / (period / 2)) % 2 === 0;
  ctx.save();
  ctx.fillStyle = defused ? 'rgba(91,155,213,0.9)' : on ? COLOR.bomb : 'rgba(255,75,62,0.35)';
  ctx.shadowColor = defused ? COLOR.ct : COLOR.bomb;
  ctx.shadowBlur = on ? 12 : 0;
  ctx.beginPath();
  ctx.arc(x, y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = 'rgba(255,75,62,0.5)';
  ctx.beginPath();
  ctx.arc(x, y, 9, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
  if (R.explode && tick >= R.explode.tick) {
    const k = clamp((tick - R.explode.tick) / (TICKRATE * 1.5), 0, 1);
    ctx.save();
    ctx.fillStyle = `rgba(255,120,40,${0.5 * (1 - k)})`;
    ctx.beginPath();
    ctx.arc(x, y, 10 + 60 * k, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

function drawPlayer(ctx: CanvasRenderingContext2D, tf: Transform, p: RadarPlayer, r: number) {
  const x = tf.x(p.x!);
  const y = tf.y(p.y!);
  const col = teamColor(p.team);
  ctx.save();
  if (p.yaw != null) {
    const a = (p.yaw * Math.PI) / 180;
    ctx.strokeStyle = col;
    ctx.globalAlpha = 0.85;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(x + Math.cos(a) * r, y - Math.sin(a) * r);
    ctx.lineTo(x + Math.cos(a) * (r + 9), y - Math.sin(a) * (r + 9));
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  ctx.fillStyle = col;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  // low hp shows a dark wedge
  if (p.hp < 100 && p.hp > 0) {
    ctx.fillStyle = 'rgba(0,0,0,0.45)';
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - p.hp / 100));
    ctx.closePath();
    ctx.fill();
  }
  if (p.bomb) {
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, r + 1.5, 0, Math.PI * 2);
    ctx.stroke();
  } else {
    ctx.strokeStyle = 'rgba(0,0,0,0.6)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.font = '600 10px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const label = String(p.name ?? '').slice(0, 14);
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(8,10,14,0.85)';
  ctx.strokeText(label, x, y + r + 2);
  ctx.fillStyle = 'rgba(232,236,244,0.92)';
  ctx.fillText(label, x, y + r + 2);
  ctx.restore();
}

function drawDead(ctx: CanvasRenderingContext2D, tf: Transform, p: RadarPlayer, r: number) {
  const x = tf.x(p.x!);
  const y = tf.y(p.y!);
  const k = r * 0.7;
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = teamColor(p.team);
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x - k, y - k);
  ctx.lineTo(x + k, y + k);
  ctx.moveTo(x + k, y - k);
  ctx.lineTo(x - k, y + k);
  ctx.stroke();
  ctx.restore();
}
