// The open demo, the loaded round, and playback (stored replay or live stream).
//
// Per-tick round data (~7k ticks x 10 players) lives in a shallowRef holding a markRaw object:
// it is never made deeply reactive. Canvases read it directly and re-draw when `idx` or the
// round reference changes.
import { defineStore } from 'pinia';
import { computed, markRaw, ref, shallowRef, triggerRef } from 'vue';
import { api } from '@/api/client';
import type { DemoDetail, RoundMeta } from '@/api/types';
import { CT, T } from '@/lib/constants';
import { clamp } from '@/lib/format';
import { deepLinkHash } from '@/lib/hash';
import { loadMapAsset, type MapAsset } from '@/lib/mapAsset';
import { prepRound, type PreparedRound } from '@/lib/round';
import { changeAt, lowerBound } from '@/lib/series';
import { advanceIndex, restartIndex, roundIndex } from '@/composables/usePlayback';
import { useLiveStream, type LiveSession, type LiveState } from '@/composables/useLiveStream';
import { useDemosStore } from './demos';
import { useMapOddsStore } from './mapOdds';
import { useSessionStore } from './session';

export type PlaybackMode = 'replay' | 'live';

/** A player at the current playback position (replay and live share this shape). */
export interface PlayerNow {
  steamid: string;
  name: string;
  team: number;
  alive: boolean;
  hp: number;
  x: number | null;
  y: number | null;
  yaw: number | null;
  armor: number | null;
  weapon: string | null;
  money: number | null;
  bomb: boolean;
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const useViewerStore = defineStore('viewer', () => {
  const openId = ref<string | null>(null);
  const demo = shallowRef<DemoDetail | null>(null);
  const roundNo = ref<number | null>(null);
  const R = shallowRef<PreparedRound | null>(null);
  const roundError = ref<string | null>(null);
  const mapAsset = shallowRef<MapAsset | null>(null);

  /** fractional index into R.ticks (replay mode) */
  const idx = ref(0);
  const playing = ref(false);
  const speed = ref(1);
  const mode = ref<PlaybackMode>('replay');
  /** triggerRef()'d on every live state change */
  const live = shallowRef<LiveSession | null>(null);

  let loadSeq = 0;

  // ------------------------------------------------------------------ derived
  const currentRound = computed<RoundMeta | null>(() => demo.value?.rounds?.find((r) => r.round === roundNo.value) ?? null);
  const demoRow = computed(() => useDemosStore().byId(openId.value));
  const curIndex = computed(() => (R.value ? roundIndex(idx.value, R.value.n) : 0));
  /**
   * The live session state while in live mode. A function rather than a computed: the state object
   * is mutated in place and `live` is triggerRef()'d, so callers must track `live` itself.
   */
  const liveNow = (): LiveState | null => (mode.value === 'live' ? (live.value?.state ?? null) : null);

  const curTick = computed<number>(() => {
    if (mode.value === 'live' && live.value) {
      const L = live.value.state;
      return L.frame?.tick ?? L.pendingTick ?? L.hello?.first_tick ?? R.value?.t0 ?? 0;
    }
    return R.value ? R.value.ticks[curIndex.value]! : 0;
  });

  const curP = computed<number | null>(() => {
    if (mode.value === 'live') return live.value?.state.frame?.p_ct ?? null;
    return R.value ? R.value.p_ct[curIndex.value] ?? null : null;
  });

  const tickDomain = computed<[number, number]>(() => {
    const L = liveNow();
    if (L?.hello) return [L.hello.first_tick, L.hello.last_tick];
    if (R.value) return [R.value.t0, R.value.t1];
    return [0, 1];
  });

  /** something to play: a stored round, or a live session that said hello */
  const playable = computed(() => (mode.value === 'live' ? !!live.value?.state.hello : !!R.value));

  const playersNow = computed<PlayerNow[]>(() => {
    if (mode.value === 'live') {
      const L = live.value?.state;
      if (!L?.frame) return [];
      return L.frame.players.map((p) => {
        const alive = !!p.alive && p.x != null;
        if (alive) L.lastPos.set(p.steamid, [p.x!, p.y!]);
        const lp = L.lastPos.get(p.steamid);
        return {
          steamid: p.steamid,
          name: p.name,
          team: p.team,
          alive,
          hp: alive ? p.hp : 0,
          x: alive ? p.x : (lp?.[0] ?? p.x),
          y: alive ? p.y : (lp?.[1] ?? p.y),
          yaw: p.yaw ?? null,
          armor: p.armor ?? null,
          weapon: p.weapon ?? null,
          money: p.money ?? null,
          bomb: alive && !!p.has_bomb,
        };
      });
    }
    const r = R.value;
    if (!r) return [];
    const i = curIndex.value;
    const tick = r.ticks[i]!;
    return r.players.map((p) => {
      const present = p.x[i] != null;
      const alive = present && p.alive[i] === 1;
      let x = p.x[i] ?? null;
      let y = p.y[i] ?? null;
      if (!alive) {
        const j = p.lastAlive[i]!;
        if (j >= 0) {
          x = p.x[j] ?? null;
          y = p.y[j] ?? null;
        }
      }
      return {
        steamid: p.steamid,
        name: p.name,
        team: p.team,
        alive,
        hp: alive ? p.hp[i]! : 0,
        x,
        y,
        yaw: p.yaw[i] ?? null,
        armor: changeAt(p.armor, tick),
        weapon: changeAt(p.weapon, tick),
        money: changeAt(p.money, tick),
        bomb: alive && !!changeAt(p.has_bomb, tick),
      };
    });
  });

  const aliveCounts = computed(() => {
    const ps = playersNow.value;
    return {
      ct: ps.filter((p) => p.alive && p.team === CT).length,
      t: ps.filter((p) => p.alive && p.team === T).length,
      any: ps.length > 0,
    };
  });

  // ------------------------------------------------------------------ live
  function stopLive() {
    const L = live.value;
    live.value = null;
    L?.dispose();
  }

  function startLive() {
    stopLive();
    if (!openId.value || roundNo.value == null) return;
    const session = useLiveStream(api.liveUrl(openId.value, roundNo.value), {
      isPlaying: () => playing.value,
      speed: () => speed.value,
      stopPlaying: () => {
        playing.value = false;
      },
      onUpdate: () => {
        if (live.value === session) triggerRef(live);
      },
    });
    live.value = session;
    setPlaying(false);
  }

  // ------------------------------------------------------------------ playback
  function setPlaying(on: boolean) {
    playing.value = on;
    if (mode.value === 'live') live.value?.play(on);
  }

  function togglePlay() {
    if (mode.value === 'live') {
      const L = live.value?.state;
      if (!L?.hello) return;
      if (!playing.value) {
        const t = curTick.value;
        if (speed.value > 0 && t >= L.hello.last_tick) seekTick(L.hello.first_tick);
        if (speed.value < 0 && t <= L.hello.first_tick) seekTick(L.hello.last_tick);
      }
      setPlaying(!playing.value);
      return;
    }
    if (!R.value) return;
    if (!playing.value) idx.value = restartIndex(idx.value, R.value.n, speed.value);
    setPlaying(!playing.value);
  }

  function seekTick(tick: number) {
    if (mode.value === 'live') {
      live.value?.seek(tick);
      return;
    }
    if (!R.value) return;
    idx.value = lowerBound(R.value.ticks, tick);
  }

  const seekBy = (dTicks: number) => seekTick(curTick.value + dTicks);

  /** Scrub bar input: an index in replay, a tick in live mode. */
  function scrubTo(v: number) {
    if (mode.value === 'live') live.value?.seek(v);
    else if (R.value) idx.value = clamp(v, 0, R.value.n - 1);
  }

  function setSpeed(v: number) {
    speed.value = v;
    if (mode.value === 'live') live.value?.setSpeed(v);
  }

  function stepRound(d: number) {
    const rounds = demo.value?.rounds || [];
    const i = rounds.findIndex((r) => r.round === roundNo.value);
    const nx = rounds[i + d];
    if (i >= 0 && nx) void loadRound(nx.round);
  }

  function setMode(m: PlaybackMode) {
    if (m === mode.value) return;
    if (playing.value) setPlaying(false);
    mode.value = m;
    if (m === 'live') startLive();
    else stopLive();
  }

  /** Called once per animation frame. */
  function onFrame(dt: number, now: number) {
    if (mode.value === 'replay' && playing.value && R.value) {
      const step = advanceIndex(idx.value, dt, speed.value, R.value.n);
      idx.value = step.idx;
      if (step.ended) setPlaying(false);
    }
    const L = live.value;
    if (L && L.checkStall(now, playing.value)) triggerRef(live);
  }

  // ------------------------------------------------------------------ loading
  async function loadMap(name: string | null) {
    mapAsset.value = null;
    if (!name) return;
    const asset = await loadMapAsset(name);
    if (demo.value?.map === name) mapAsset.value = asset;
  }

  async function loadRound(n: number, keepIdx: number | null = null) {
    const id = openId.value;
    if (!id) return;
    const seq = ++loadSeq;
    const wasLive = mode.value === 'live';
    stopLive();
    roundNo.value = n;
    let raw;
    try {
      raw = await api.round(id, n);
    } catch (e) {
      if (seq !== loadSeq) return;
      R.value = null;
      roundError.value = errMsg(e);
      return;
    }
    if (seq !== loadSeq) return;
    const r = markRaw(prepRound(raw));
    R.value = r;
    roundError.value = null;
    idx.value = keepIdx != null ? clamp(keepIdx, 0, r.n - 1) : 0;
    history.replaceState(null, '', deepLinkHash(id, n));
    useMapOddsStore().onRoundChanged();
    if (wasLive) startLive();
  }

  async function openDemo(id: string, wantRound: number | null = null) {
    const session = useSessionStore();
    const seq = ++loadSeq;
    stopLive();
    openId.value = id;
    R.value = null;
    roundNo.value = null;
    roundError.value = null;
    let d: DemoDetail;
    try {
      d = await api.demo(id);
    } catch (e) {
      if (seq !== loadSeq) return;
      openId.value = null;
      demo.value = null;
      session.showNotice({ title: 'Could not open demo', message: errMsg(e), isError: true });
      return;
    }
    if (seq !== loadSeq) return;
    demo.value = markRaw(d);
    session.notice = null;
    session.view = 'demo';
    void loadMap(d.map);
    void useMapOddsStore().load(id);
    const rounds = d.rounds || [];
    const want = wantRound != null && rounds.some((r) => r.round === wantRound) ? wantRound : rounds[0]?.round;
    if (want != null) await loadRound(want);
  }

  /** After a rescore/train finished: refresh p_ct + WPA but keep the position. */
  async function reloadOpenDemo() {
    const id = openId.value;
    if (!id) return;
    const keepIdx = idx.value;
    const rn = roundNo.value;
    let d: DemoDetail;
    try {
      d = await api.demo(id);
    } catch {
      return;
    }
    if (openId.value !== id) return;
    demo.value = markRaw(d);
    void useMapOddsStore().load(id);
    if (rn != null && mode.value === 'replay') await loadRound(rn, keepIdx);
  }

  function closeDemo() {
    ++loadSeq;
    stopLive();
    if (playing.value) setPlaying(false);
    openId.value = null;
    demo.value = null;
    R.value = null;
    roundNo.value = null;
    roundError.value = null;
    mapAsset.value = null;
    useMapOddsStore().reset();
    history.replaceState(null, '', location.pathname + location.search);
    const session = useSessionStore();
    if (session.view === 'demo') session.view = 'home';
  }

  return {
    // state
    openId,
    demo,
    roundNo,
    R,
    roundError,
    mapAsset,
    idx,
    playing,
    speed,
    mode,
    live,
    // derived
    currentRound,
    demoRow,
    curIndex,
    curTick,
    curP,
    tickDomain,
    playable,
    playersNow,
    aliveCounts,
    liveNow,
    // actions
    openDemo,
    closeDemo,
    reloadOpenDemo,
    loadRound,
    setMode,
    setPlaying,
    togglePlay,
    seekTick,
    seekBy,
    scrubTo,
    setSpeed,
    stepRound,
    onFrame,
    startLive,
    stopLive,
  };
});

