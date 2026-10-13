import { onBeforeUnmount, onMounted } from 'vue';
import { TICKRATE } from '@/lib/constants';

/** Longest frame step we integrate (s): a backgrounded tab must not jump the replay ahead. */
export const MAX_FRAME_DT = 0.1;

export const frameDt = (now: number, last: number): number => Math.max(0, Math.min(MAX_FRAME_DT, (now - last) / 1000));

export interface StepResult {
  idx: number;
  /** playback hit the end in its direction of travel and should stop */
  ended: boolean;
}

/**
 * Advance a fractional tick index by `dt` seconds at `speed`x on a 64 Hz round of `n` ticks.
 * Negative speeds rewind. The index is clamped to [0, n-1]; reaching the boundary in the
 * direction of travel ends playback.
 */
export function advanceIndex(idx: number, dt: number, speed: number, n: number, tickrate = TICKRATE): StepResult {
  if (n <= 0) return { idx: 0, ended: true };
  const last = n - 1;
  const next = idx + dt * tickrate * speed;
  if (next >= last) return { idx: last, ended: speed > 0 };
  if (next <= 0) return { idx: 0, ended: speed < 0 };
  return { idx: next, ended: false };
}

/** Pressing play at the boundary restarts from the other end. */
export function restartIndex(idx: number, n: number, speed: number): number {
  if (speed > 0 && idx >= n - 1) return 0;
  if (speed < 0 && idx <= 0) return Math.max(0, n - 1);
  return idx;
}

/** Fractional index -> integer index into the tick arrays. */
export const roundIndex = (idx: number, n: number): number => (n > 0 ? Math.max(0, Math.min(n - 1, Math.round(idx))) : 0);

/**
 * Run `onFrame(dt, now)` on every animation frame while the calling component is mounted.
 * dt is in seconds, clamped to MAX_FRAME_DT.
 */
export function usePlaybackLoop(onFrame: (dt: number, now: number) => void): void {
  let raf = 0;
  let last = 0;
  const loop = (now: number) => {
    const dt = last ? frameDt(now, last) : 0;
    last = now;
    onFrame(dt, now);
    raf = requestAnimationFrame(loop);
  };
  onMounted(() => {
    raf = requestAnimationFrame(loop);
  });
  onBeforeUnmount(() => cancelAnimationFrame(raf));
}
