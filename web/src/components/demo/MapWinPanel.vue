<script setup lang="ts">
import { computed, ref, shallowRef, watchEffect } from 'vue';
import { useCanvas, useElementWidth } from '@/composables/useCanvas';
import { MAPC } from '@/lib/constants';
import { clamp, pct } from '@/lib/format';
import { drawMapChart, MAP_HEIGHT, mapDomain, mapTickAt, type MapReadout } from '@/lib/draw/mapChart';
import { useMapOddsStore, type MapZoom } from '@/stores/mapOdds';
import { useViewerStore } from '@/stores/viewer';
import KalshiPanel from './KalshiPanel.vue';

const viewer = useViewerStore();
const odds = useMapOddsStore();
const wrap = ref<HTMLElement | null>(null);
const cv = ref<HTMLCanvasElement | null>(null);
const width = useElementWidth(wrap);
const canvas = useCanvas(cv, () => (width.value ? { w: width.value, h: MAP_HEIGHT } : null));
const readout = shallowRef<MapReadout>({ kind: 'none' });

const hasData = computed(() => !!odds.data?.tick?.length);
const cursor = computed(() => (viewer.R || viewer.liveNow() ? viewer.curTick : null));

watchEffect(
  () => {
    const c = canvas.value;
    if (!c) return;
    const data = odds.data;
    if (!data?.tick?.length) {
      c.ctx.clearRect(0, 0, c.w, c.h);
      readout.value = { kind: 'none' };
      return;
    }
    readout.value = drawMapChart(c.ctx, {
      w: c.w,
      h: c.h,
      zoom: odds.zoom,
      data,
      market: odds.kal?.market ?? null,
      rounds: viewer.demo?.rounds ?? [],
      roundNo: viewer.roundNo,
      current: viewer.currentRound,
      roundView: odds.round,
      cursor: cursor.value,
    });
  },
  { flush: 'post' },
);

const teamsLabel = computed(() => {
  const t = odds.data?.teams;
  return t ? `· ${t.a.name} vs ${t.b.name} (shown for ${t.a.name})` : '';
});

const zooms: { z: MapZoom; label: string }[] = [
  { z: 'match', label: 'Whole map' },
  { z: 'round', label: 'This round · trade by trade' },
];

const fmtCount = (n: number) => (n < 10 ? n.toFixed(1) : String(Math.round(n)));
const fmtGap = (g: number) => `${g >= 0 ? '+' : '−'}${Math.abs(g).toFixed(1)} pts`;
const cents = (v: number | null) => (v == null ? '–' : String(Math.round(v * 100)));

async function onClick(e: MouseEvent) {
  const c = canvas.value;
  if (!c || !odds.data?.tick?.length || !cv.value) return;
  const rect = cv.value.getBoundingClientRect();
  const dom = mapDomain(odds.zoom, viewer.currentRound, odds.data);
  const tick = mapTickAt(c.w, dom, e.clientX - rect.left);
  if (odds.zoom === 'round') {
    viewer.seekTick(tick);
    return;
  }
  const rounds = viewer.demo?.rounds || [];
  let target = rounds[0];
  for (const rr of rounds) if (rr.freeze_end <= tick) target = rr;
  if (!target) return;
  if (target.round !== viewer.roundNo) await viewer.loadRound(target.round);
  viewer.seekTick(clamp(tick, target.freeze_end, target.end));
}
</script>

<template>
  <section id="map-section" class="card">
    <div class="chart-head">
      <h3>Map win probability <span id="map-teams" class="muted">{{ teamsLabel }}</span></h3>
      <div id="map-zoom" class="seg">
        <button v-for="z in zooms" :key="z.z" class="btn small" :class="{ on: odds.zoom === z.z }" :data-z="z.z" @click="odds.setZoom(z.z)">
          {{ z.label }}
        </button>
      </div>
      <div id="map-readout">
        <span v-if="readout.kind === 'loading'" class="muted">loading round…</span>
        <template v-else-if="readout.kind === 'match'">
          {{ readout.team }}: <b :style="{ color: MAPC.ours }">{{ readout.ours != null ? pct(readout.ours) : '–' }}</b> model
          <template v-if="readout.kalshi">
            · <b :style="{ color: MAPC.kal }">{{ cents(readout.kalshi.mid) }}¢</b> Kalshi ({{ cents(readout.kalshi.bid) }}/{{ cents(readout.kalshi.ask) }})
          </template>
        </template>
        <template v-else-if="readout.kind === 'round'">
          {{ readout.team }}: <b :style="{ color: MAPC.ours }">{{ readout.ours != null ? pct(readout.ours) : '–' }}</b> model
          <template v-if="readout.trade">
            · <b :style="{ color: MAPC.kal }">{{ cents(readout.trade.price) }}¢</b> last Kalshi trade ({{ readout.trade.ago.toFixed(1) }}s ago,
            {{ fmtCount(readout.trade.count) }} contracts)
            <template v-if="readout.trade.gap != null"> · gap <b>{{ fmtGap(readout.trade.gap) }}</b></template>
          </template>
          <template v-else-if="readout.note === 'nolink'"> · <span class="muted">no Kalshi market for this map</span></template>
          <template v-else-if="readout.note === 'notrades'"> · <span class="muted">no Kalshi trades yet this round</span></template>
        </template>
      </div>
      <div class="legend">
        <span><i class="ln ours"></i>our model</span>
        <span><i class="ln kal"></i>Kalshi mid · bid–ask band</span>
      </div>
    </div>
    <div id="map-wrap" ref="wrap">
      <canvas id="mapchart" ref="cv" @click="onClick"></canvas>
      <div v-if="!hasData" id="map-msg">Train a model to see map win probability</div>
    </div>
    <KalshiPanel />
  </section>
</template>
