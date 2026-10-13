// Live stream mode: a stored round replayed by the server through gamestate -> inference ->
// winprob over a WebSocket (/ws/live/{demo}/{round}).
//
// Protocol: server sends {type:'hello', first_tick, last_tick, model} once, then
// {type:'frame', tick, p_ct, series:[[tick,p]], players, model} while playing, or
// {type:'error', message}. Client sends {cmd:'play'|'pause'} / {cmd:'seek', tick} /
// {cmd:'speed', value}. The server only publishes frames while playing, so a seek while paused
// is followed by a short play/pause "nudge" to get one frame at the new position.
import { parseJSON } from '@/lib/json';
import type { LiveCommand, LiveFrame, LiveHello, LiveMessage } from '@/api/types';

const WS_CONNECTING = 0;
const WS_OPEN = 1;

export type LiveStatus = 'connecting' | 'live' | 'stalled' | 'closed' | 'error';

export interface LiveState {
  hello: LiveHello | null;
  frame: LiveFrame | null;
  /** every tick -> P(CT) seen so far */
  series: Map<number, number | null>;
  /** last alive position per steamid, so dead players stay where they fell */
  lastPos: Map<string, [number, number]>;
  status: LiveStatus;
  error: string | null;
  pendingTick: number | null;
  /** performance.now() when play was last pressed */
  playAt: number | null;
  lastFrameAt: number | null;
}

/** Minimal WebSocket surface (lets tests inject a fake). */
export interface SocketLike {
  readyState: number;
  send(data: string): void;
  close(): void;
  onopen: ((ev: Event) => unknown) | null;
  onmessage: ((ev: MessageEvent) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
  onclose: ((ev: CloseEvent) => unknown) | null;
}

export interface LiveHost {
  isPlaying(): boolean;
  speed(): number;
  /** stop the play state without sending a command (server already stopped / socket closed) */
  stopPlaying(): void;
  /** called after every state change */
  onUpdate(): void;
}

export interface LiveDeps {
  createSocket(url: string): SocketLike;
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(id: unknown): void;
}

export const defaultLiveDeps = (): LiveDeps => ({
  createSocket: (url) => new WebSocket(url) as unknown as SocketLike,
  now: () => performance.now(),
  setTimeout: (fn, ms) => window.setTimeout(fn, ms),
  clearTimeout: (id) => window.clearTimeout(id as number),
});

/** No frames for this long after pressing play = the inference stage is stuck. */
export const STALL_MS = 3000;
export const NUDGE_DELAY_MS = 90;
export const NUDGE_PLAY_MS = 75;
export const START_FAILED = 'Live stream failed to start (is a model trained and active?)';

export function createLiveState(): LiveState {
  return {
    hello: null,
    frame: null,
    series: new Map(),
    lastPos: new Map(),
    status: 'connecting',
    error: null,
    pendingTick: null,
    playAt: null,
    lastFrameAt: null,
  };
}

export class LiveSession {
  readonly state: LiveState = createLiveState();
  private readonly ws: SocketLike;
  private nudgeTimer: unknown = null;
  private disposed = false;

  constructor(
    readonly url: string,
    private readonly host: LiveHost,
    private readonly deps: LiveDeps = defaultLiveDeps(),
  ) {
    this.ws = deps.createSocket(url);
    this.ws.onmessage = (ev) => this.handleMessage(String(ev.data));
    this.ws.onerror = () => this.handleError();
    this.ws.onclose = () => this.handleClose();
  }

  get closed(): boolean {
    return this.disposed;
  }

  send(cmd: LiveCommand): void {
    if (!this.disposed && this.ws.readyState === WS_OPEN) this.ws.send(JSON.stringify(cmd));
  }

  /** Tell the server to play/pause; remembers when play started for stall detection. */
  play(on: boolean): void {
    this.send({ cmd: on ? 'play' : 'pause' });
    if (on) this.state.playAt = this.deps.now();
  }

  setSpeed(value: number): void {
    this.send({ cmd: 'speed', value });
  }

  /** Seek to a tick (clamped to the round). While paused, nudge the server for one frame. */
  seek(tick: number): void {
    const L = this.state;
    if (!L.hello || this.disposed) return;
    const t = Math.max(L.hello.first_tick, Math.min(L.hello.last_tick, Math.round(tick)));
    L.pendingTick = t;
    if (L.frame) L.frame = { ...L.frame, tick: t, p_ct: L.series.get(t) ?? L.frame.p_ct };
    this.send({ cmd: 'seek', tick: t });
    if (!this.host.isPlaying()) {
      this.deps.clearTimeout(this.nudgeTimer);
      this.nudgeTimer = this.deps.setTimeout(() => {
        if (this.disposed || this.host.isPlaying()) return;
        // run at 1x for ~2 streamer frames (33 ms each) so at least one frame is published
        this.send({ cmd: 'seek', tick: t });
        this.send({ cmd: 'speed', value: 1 });
        this.send({ cmd: 'play' });
        this.deps.setTimeout(() => {
          if (this.disposed) return;
          if (!this.host.isPlaying()) this.send({ cmd: 'pause' });
          this.send({ cmd: 'speed', value: this.host.speed() });
        }, NUDGE_PLAY_MS);
      }, NUDGE_DELAY_MS);
    }
    this.host.onUpdate();
  }

  handleMessage(raw: string): void {
    if (this.disposed) return;
    let msg: LiveMessage;
    try {
      msg = parseJSON<LiveMessage>(raw);
    } catch {
      return;
    }
    const L = this.state;
    if (msg.type === 'hello') {
      L.hello = msg;
      L.status = 'live';
      this.send({ cmd: 'speed', value: this.host.speed() });
      this.seek(msg.first_tick);
    } else if (msg.type === 'frame') {
      L.frame = msg;
      L.lastFrameAt = this.deps.now();
      if (L.status === 'stalled') L.status = 'live';
      L.pendingTick = null;
      for (const [t, p] of msg.series || []) L.series.set(t, p);
      const sp = this.host.speed();
      const hello = L.hello;
      if (hello && this.host.isPlaying() && ((sp > 0 && msg.tick >= hello.last_tick) || (sp < 0 && msg.tick <= hello.first_tick))) {
        this.host.stopPlaying();
      }
    } else if (msg.type === 'error') {
      L.error = msg.message || 'live stream failed';
      L.status = 'error';
    }
    this.host.onUpdate();
  }

  private handleError(): void {
    if (this.disposed) return;
    const L = this.state;
    L.status = 'error';
    if (!L.error) L.error = 'connection error';
    this.host.onUpdate();
  }

  private handleClose(): void {
    if (this.disposed) return;
    const L = this.state;
    if (!L.hello) {
      L.status = 'error';
      L.error = L.error && L.error !== 'connection error' ? L.error : START_FAILED;
    } else if (L.status !== 'error') L.status = 'closed';
    this.host.stopPlaying();
    this.host.onUpdate();
  }

  /** Flag a stalled inference stage: playing, socket live, but no frames since play. Returns true on change. */
  checkStall(now: number, playing: boolean): boolean {
    const L = this.state;
    if (L.status === 'live' && playing && L.playAt != null && now - L.playAt > STALL_MS && !(L.lastFrameAt != null && L.lastFrameAt > L.playAt)) {
      L.status = 'stalled';
      return true;
    }
    return false;
  }

  /** Close the socket and ignore anything it still delivers. */
  dispose(): void {
    if (this.disposed) return;
    this.deps.clearTimeout(this.nudgeTimer);
    this.disposed = true;
    if (this.ws.readyState === WS_CONNECTING || this.ws.readyState === WS_OPEN) this.ws.close();
  }
}

export interface LiveBadge {
  cls: '' | 'off' | 'err';
  text: string;
  live: boolean;
}

/** Text + style for the badge over the radar. */
export function liveBadge(L: LiveState): LiveBadge {
  const model = L.frame?.model || L.hello?.model || '?';
  switch (L.status) {
    case 'error':
      return { cls: 'err', text: L.error || 'live stream failed', live: false };
    case 'connecting':
      return { cls: 'off', text: 'connecting…', live: false };
    case 'closed':
      return { cls: 'off', text: 'stream closed', live: false };
    case 'stalled':
      return { cls: 'err', text: 'no frames from inference (check the server log)', live: false };
    default:
      return { cls: '', text: ` · gamestate → inference → winprob (model ${model})`, live: true };
  }
}

/** Composable entry point: open a live session against `url`. Dispose it with `session.dispose()`. */
export function useLiveStream(url: string, host: LiveHost, deps?: LiveDeps): LiveSession {
  return new LiveSession(url, host, deps);
}
