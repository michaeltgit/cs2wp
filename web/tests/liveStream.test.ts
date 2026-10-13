import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  liveBadge,
  LiveSession,
  NUDGE_DELAY_MS,
  NUDGE_PLAY_MS,
  START_FAILED,
  STALL_MS,
  type LiveDeps,
  type LiveHost,
  type SocketLike,
} from '@/composables/useLiveStream';

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: unknown[] = [];
  closed = false;
  onopen: SocketLike['onopen'] = null;
  onmessage: SocketLike['onmessage'] = null;
  onerror: SocketLike['onerror'] = null;
  onclose: SocketLike['onclose'] = null;
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closed = true;
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
  }
  receive(obj: unknown | string) {
    this.onmessage?.({ data: typeof obj === 'string' ? obj : JSON.stringify(obj) } as MessageEvent);
  }
  serverClose() {
    this.readyState = 3;
    this.onclose?.({} as CloseEvent);
  }
  fail() {
    this.onerror?.({} as Event);
  }
}

const hello = { type: 'hello', session: 's1', first_tick: 1000, last_tick: 1500, model: 'v008' };
const frame = (tick: number, extra: Record<string, unknown> = {}) => ({
  type: 'frame',
  tick,
  p_ct: 0.5,
  series: [[tick, 0.5]],
  players: [],
  model: 'v008',
  ...extra,
});

let sock: FakeSocket;
let now: number;
let playing: boolean;
let speed: number;
let updates: number;
let host: LiveHost;
let deps: LiveDeps;

beforeEach(() => {
  vi.useFakeTimers();
  sock = new FakeSocket();
  now = 0;
  playing = false;
  speed = 1;
  updates = 0;
  host = {
    isPlaying: () => playing,
    speed: () => speed,
    stopPlaying: () => {
      playing = false;
    },
    onUpdate: () => {
      updates++;
    },
  };
  deps = {
    createSocket: () => sock,
    now: () => now,
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
  };
});

function connected() {
  const s = new LiveSession('ws://x/ws/live/d/1', host, deps);
  sock.open();
  return s;
}

describe('LiveSession', () => {
  it('starts connecting and ignores sends before the socket opens', () => {
    const s = new LiveSession('ws://x', host, deps);
    expect(s.state.status).toBe('connecting');
    s.play(true);
    expect(sock.sent).toEqual([]);
    expect(liveBadge(s.state)).toMatchObject({ cls: 'off', text: 'connecting…' });
  });

  it('on hello: goes live, syncs speed and seeks to the first tick', () => {
    speed = 2;
    const s = connected();
    sock.receive(hello);
    expect(s.state.status).toBe('live');
    expect(s.state.hello?.last_tick).toBe(1500);
    expect(s.state.pendingTick).toBe(1000);
    expect(sock.sent.slice(0, 2)).toEqual([
      { cmd: 'speed', value: 2 },
      { cmd: 'seek', tick: 1000 },
    ]);
    expect(updates).toBeGreaterThan(0);
    expect(liveBadge(s.state)).toMatchObject({ cls: '', live: true });
    expect(liveBadge(s.state).text).toContain('model v008');
  });

  it('nudges the server for one frame after a seek while paused', () => {
    const s = connected();
    sock.receive(hello);
    sock.sent = [];
    s.seek(1200.4);
    expect(sock.sent).toEqual([{ cmd: 'seek', tick: 1200 }]);
    vi.advanceTimersByTime(NUDGE_DELAY_MS);
    expect(sock.sent.slice(1)).toEqual([{ cmd: 'seek', tick: 1200 }, { cmd: 'speed', value: 1 }, { cmd: 'play' }]);
    vi.advanceTimersByTime(NUDGE_PLAY_MS);
    expect(sock.sent.slice(4)).toEqual([{ cmd: 'pause' }, { cmd: 'speed', value: 1 }]);
  });

  it('debounces nudges and clamps seeks to the round', () => {
    const s = connected();
    sock.receive(hello);
    sock.sent = [];
    s.seek(5);
    s.seek(99999);
    expect(sock.sent).toEqual([
      { cmd: 'seek', tick: 1000 },
      { cmd: 'seek', tick: 1500 },
    ]);
    vi.advanceTimersByTime(NUDGE_DELAY_MS + NUDGE_PLAY_MS);
    const seeks = sock.sent.filter((c) => (c as { cmd: string }).cmd === 'seek');
    expect(seeks).toHaveLength(3); // one nudge only, for the last position
  });

  it('does not nudge while playing', () => {
    const s = connected();
    sock.receive(hello);
    playing = true;
    sock.sent = [];
    s.seek(1100);
    vi.advanceTimersByTime(1000);
    expect(sock.sent).toEqual([{ cmd: 'seek', tick: 1100 }]);
  });

  it('frames update the state and merge the series', () => {
    const s = connected();
    sock.receive(hello);
    now = 50;
    sock.receive(frame(1010, { series: [[1005, 0.4], [1010, 0.45]], p_ct: 0.45 }));
    sock.receive(frame(1020, { series: [[1015, 0.5], [1020, NaN]] }));
    expect(s.state.frame?.tick).toBe(1020);
    expect(s.state.pendingTick).toBeNull();
    expect(s.state.lastFrameAt).toBe(50);
    expect([...s.state.series.entries()]).toEqual([
      [1005, 0.4],
      [1010, 0.45],
      [1015, 0.5],
      [1020, null],
    ]);
  });

  it('accepts bare NaN in frames', () => {
    const s = connected();
    sock.receive(hello);
    sock.receive('{"type":"frame","tick":1001,"p_ct":NaN,"series":[[1001,NaN]],"players":[]}');
    expect(s.state.frame?.p_ct).toBeNull();
  });

  it('a seek with a frame updates the shown tick and p from the known series', () => {
    const s = connected();
    sock.receive(hello);
    sock.receive(frame(1010, { series: [[1005, 0.4], [1010, 0.45]] }));
    s.seek(1005);
    expect(s.state.frame?.tick).toBe(1005);
    expect(s.state.frame?.p_ct).toBe(0.4);
  });

  it('stops playing when the stream reaches the end in the play direction', () => {
    connected();
    sock.receive(hello);
    playing = true;
    sock.receive(frame(1499));
    expect(playing).toBe(true);
    sock.receive(frame(1500));
    expect(playing).toBe(false);

    playing = true;
    speed = -1;
    sock.receive(frame(1200));
    expect(playing).toBe(true);
    sock.receive(frame(1000));
    expect(playing).toBe(false);
  });

  it('records play time and flags a stalled inference stage', () => {
    const s = connected();
    sock.receive(hello);
    now = 1000;
    s.play(true);
    playing = true;
    expect(sock.sent.at(-1)).toEqual({ cmd: 'play' });
    expect(s.checkStall(1000 + STALL_MS - 1, true)).toBe(false);
    expect(s.checkStall(1000 + STALL_MS + 1, true)).toBe(true);
    expect(s.state.status).toBe('stalled');
    expect(liveBadge(s.state).cls).toBe('err');
    // a frame recovers it
    now = 5000;
    sock.receive(frame(1100));
    expect(s.state.status).toBe('live');
    expect(s.checkStall(9999, true)).toBe(false);
  });

  it('server error messages are shown and survive the close', () => {
    const s = connected();
    sock.receive({ type: 'error', message: 'no trained model' });
    expect(s.state.status).toBe('error');
    sock.serverClose();
    expect(s.state.error).toBe('no trained model');
    expect(liveBadge(s.state)).toMatchObject({ cls: 'err', text: 'no trained model' });
  });

  it('a close before hello reports a start failure', () => {
    playing = true;
    const s = connected();
    sock.fail();
    sock.serverClose();
    expect(s.state.status).toBe('error');
    expect(s.state.error).toBe(START_FAILED);
    expect(playing).toBe(false);
  });

  it('a close after hello is just "closed"', () => {
    const s = connected();
    sock.receive(hello);
    sock.serverClose();
    expect(s.state.status).toBe('closed');
    expect(liveBadge(s.state).text).toBe('stream closed');
  });

  it('dispose closes the socket and ignores late messages and timers', () => {
    const s = connected();
    sock.receive(hello);
    s.seek(1300);
    s.dispose();
    expect(sock.closed).toBe(true);
    const before = sock.sent.length;
    const ups = updates;
    sock.receive(frame(1400));
    vi.advanceTimersByTime(1000);
    expect(s.state.frame).toBeNull();
    expect(sock.sent.length).toBe(before);
    expect(updates).toBe(ups);
    expect(s.closed).toBe(true);
  });

  it('ignores unparseable messages', () => {
    const s = connected();
    sock.receive('not json');
    expect(s.state.status).toBe('connecting');
  });
});
