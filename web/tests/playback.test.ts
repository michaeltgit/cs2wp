import { describe, expect, it } from 'vitest';
import { advanceIndex, frameDt, MAX_FRAME_DT, restartIndex, roundIndex } from '@/composables/usePlayback';
import { keyAction } from '@/composables/useKeyboard';

describe('advanceIndex (64 Hz stepping)', () => {
  const n = 7000;

  it('advances 64 ticks per second at 1x', () => {
    expect(advanceIndex(0, 1, 1, n)).toEqual({ idx: 64, ended: false });
    expect(advanceIndex(100, 0.5, 1, n)).toEqual({ idx: 132, ended: false });
  });

  it('scales with speed, including fractional speeds', () => {
    expect(advanceIndex(0, 1, 4, n).idx).toBe(256);
    expect(advanceIndex(10, 1 / 64, 0.25, n).idx).toBeCloseTo(10.25);
  });

  it('rewinds with negative speeds', () => {
    expect(advanceIndex(1000, 1, -2, n)).toEqual({ idx: 872, ended: false });
  });

  it('stops at the end going forward', () => {
    expect(advanceIndex(n - 10, 1, 1, n)).toEqual({ idx: n - 1, ended: true });
  });

  it('stops at the start going backward', () => {
    expect(advanceIndex(30, 1, -1, n)).toEqual({ idx: 0, ended: true });
  });

  it('does not stop at the start when moving forward from 0 with dt=0', () => {
    expect(advanceIndex(0, 0, 1, n)).toEqual({ idx: 0, ended: false });
  });

  it('handles empty rounds', () => {
    expect(advanceIndex(5, 1, 1, 0)).toEqual({ idx: 0, ended: true });
  });

  it('accumulates fractional indices across frames', () => {
    let idx = 0;
    for (let i = 0; i < 60; i++) idx = advanceIndex(idx, 1 / 60, 1, n).idx;
    expect(idx).toBeCloseTo(64, 6);
  });
});

describe('restartIndex', () => {
  it('restarts from the other end when pressing play at a boundary', () => {
    expect(restartIndex(99, 100, 1)).toBe(0);
    expect(restartIndex(0, 100, -1)).toBe(99);
    expect(restartIndex(50, 100, 1)).toBe(50);
    expect(restartIndex(0, 100, 1)).toBe(0);
  });
});

describe('frame helpers', () => {
  it('frameDt converts ms to s and clamps long gaps', () => {
    expect(frameDt(1016, 1000)).toBeCloseTo(0.016);
    expect(frameDt(5000, 0)).toBe(MAX_FRAME_DT);
    expect(frameDt(1000, 2000)).toBe(0);
  });

  it('roundIndex clamps to the round', () => {
    expect(roundIndex(3.6, 10)).toBe(4);
    expect(roundIndex(-2, 10)).toBe(0);
    expect(roundIndex(42, 10)).toBe(9);
    expect(roundIndex(1, 0)).toBe(0);
  });
});

describe('keyboard shortcuts', () => {
  it('maps keys to playback actions', () => {
    expect(keyAction(' ', false)).toEqual({ kind: 'toggle' });
    expect(keyAction('ArrowLeft', false)).toEqual({ kind: 'seek', ticks: -320 });
    expect(keyAction('ArrowRight', false)).toEqual({ kind: 'seek', ticks: 320 });
    expect(keyAction('ArrowLeft', true)).toEqual({ kind: 'round', delta: -1 });
    expect(keyAction('ArrowRight', true)).toEqual({ kind: 'round', delta: 1 });
    expect(keyAction(',', false)).toEqual({ kind: 'seek', ticks: -1 });
    expect(keyAction('<', true)).toEqual({ kind: 'seek', ticks: -1 });
    expect(keyAction('.', false)).toEqual({ kind: 'seek', ticks: 1 });
    expect(keyAction('>', true)).toEqual({ kind: 'seek', ticks: 1 });
    expect(keyAction('a', false)).toBeNull();
  });
});
