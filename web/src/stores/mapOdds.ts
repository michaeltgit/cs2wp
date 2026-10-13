// Map win probability (our model) vs the linked Kalshi market for the open demo.
import { defineStore } from 'pinia';
import { markRaw, ref, shallowRef } from 'vue';
import { api } from '@/api/client';
import type {
  KalshiAnalysis,
  KalshiComparison,
  KalshiRoundTrades,
  MapWinSeries,
} from '@/api/types';
import { useViewerStore } from './viewer';

export type MapZoom = 'match' | 'round';

/** 'This round · trade by trade' data: our odds at full tick rate + every Kalshi trade. */
export interface MapRoundView {
  id: string;
  n: number;
  data: MapWinSeries | null;
  trades: KalshiRoundTrades | null;
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));
const raw = <T extends object>(v: T | null): T | null => (v ? markRaw(v) : null);

export const useMapOddsStore = defineStore('mapOdds', () => {
  /** whole-map series, 1 point per second */
  const data = shallowRef<MapWinSeries | null>(null);
  const kal = shallowRef<KalshiComparison | null>(null);
  const zoom = ref<MapZoom>('match');
  const round = shallowRef<MapRoundView | null>(null);
  const loadedId = ref<string | null>(null);

  const analysis = shallowRef<KalshiAnalysis | null>(null);
  const analysisError = ref<string | null>(null);
  const analysisLoading = ref(false);

  const openId = () => useViewerStore().openId;

  function reset() {
    data.value = kal.value = null;
    round.value = null;
    loadedId.value = null;
    analysis.value = null;
    analysisError.value = null;
  }

  async function load(id: string) {
    data.value = kal.value = null;
    const [d, k] = await Promise.allSettled([api.mapwin(id), api.kalshi(id)]);
    if (openId() !== id) return;
    loadedId.value = id;
    data.value = d.status === 'fulfilled' ? raw(d.value) : null;
    kal.value = k.status === 'fulfilled' ? raw(k.value) : null;
    round.value = null;
    void loadAnalysis();
    void loadRound();
  }

  /** Fetch the trade-by-trade round view for the open round (only while zoomed in). */
  async function loadRound() {
    const viewer = useViewerStore();
    const id = viewer.openId;
    const n = viewer.roundNo;
    if (!id || n == null || zoom.value !== 'round') return;
    if (round.value?.n === n && round.value?.id === id) return;
    const [d, k] = await Promise.allSettled([
      api.mapwin(id, { every: 1, round: n }),
      kal.value ? api.kalshiRound(id, n) : Promise.reject(new Error('no market')),
    ]);
    if (viewer.openId !== id || viewer.roundNo !== n) return;
    round.value = markRaw({
      id,
      n,
      data: d.status === 'fulfilled' ? raw(d.value) : null,
      trades: k.status === 'fulfilled' ? raw(k.value) : null,
    });
  }

  function onRoundChanged() {
    round.value = null;
    void loadRound();
  }

  function setZoom(z: MapZoom) {
    zoom.value = z;
    round.value = null;
    if (z === 'round') void loadRound();
  }

  async function loadAnalysis() {
    const id = openId();
    analysis.value = null;
    analysisError.value = null;
    if (!id || !kal.value) return;
    analysisLoading.value = true;
    try {
      const a = await api.kalshiAnalysis(id);
      if (openId() === id) analysis.value = markRaw(a);
    } catch (e) {
      if (openId() === id) analysisError.value = errMsg(e);
    } finally {
      if (openId() === id) analysisLoading.value = false;
    }
  }

  return {
    data,
    kal,
    zoom,
    round,
    analysis,
    analysisError,
    analysisLoading,
    reset,
    load,
    loadRound,
    onRoundChanged,
    setZoom,
    loadAnalysis,
  };
});
