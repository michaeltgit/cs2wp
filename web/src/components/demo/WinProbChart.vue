<script setup lang="ts">
import { computed, ref, shallowRef, watchEffect } from 'vue';
import { useCanvas, useElementWidth } from '@/composables/useCanvas';
import { CHART_HEIGHT, chartTickAt, drawChartFrame, renderChartLayer, type ChartSeries } from '@/lib/draw/chart';
import { pct } from '@/lib/format';
import { useViewerStore } from '@/stores/viewer';

const viewer = useViewerStore();
const wrap = ref<HTMLElement | null>(null);
const cv = ref<HTMLCanvasElement | null>(null);
const width = useElementWidth(wrap);
const canvas = useCanvas(cv, () => (width.value ? { w: width.value, h: CHART_HEIGHT } : null));

// The line, area and markers only change with the round / live series, so they are rendered
// to an offscreen layer; each frame just blits it and draws the playhead.
const layer = document.createElement('canvas');
const layerVersion = shallowRef(0);
let layerCount = 0;

const series = computed<ChartSeries>(() => {
  const L = viewer.liveNow();
  if (viewer.mode === 'live') {
    if (!L) return { ticks: [], ps: [] };
    const keys = [...L.series.keys()].sort((a, b) => a - b);
    return { ticks: keys, ps: keys.map((k) => L.series.get(k) ?? null) };
  }
  return viewer.R ? { ticks: viewer.R.ticks, ps: viewer.R.p_ct } : { ticks: [], ps: [] };
});

watchEffect(
  () => {
    const c = canvas.value;
    if (!c) return;
    renderChartLayer(layer, {
      w: c.w,
      h: c.h,
      dpr: c.dpr,
      domain: viewer.tickDomain,
      round: viewer.currentRound ?? viewer.R?.round ?? null,
      series: series.value,
      feed: viewer.R?.feed ?? [],
    });
    layerVersion.value = ++layerCount; // write-only: this effect must not track its own output
  },
  { flush: 'post' },
);

const hasCursor = computed(() => !!viewer.R || !!viewer.liveNow()?.hello);

watchEffect(
  () => {
    void layerVersion.value;
    const c = canvas.value;
    if (!c) return;
    drawChartFrame(
      c.ctx,
      layer,
      { w: c.w, h: c.h, dpr: c.dpr, domain: viewer.tickDomain },
      hasCursor.value ? { tick: viewer.curTick, p: viewer.curP } : null,
    );
  },
  { flush: 'post' },
);

const noModel = computed(() => viewer.mode === 'replay' && !!viewer.R && !viewer.R.hasP);
const readout = computed(() => {
  const p = viewer.curP;
  return p == null ? null : { ct: pct(p), t: pct(1 - p) };
});
const context = computed(() => {
  const rm = viewer.currentRound;
  if (!rm) return '';
  const L = viewer.liveNow();
  const model = viewer.mode === 'live' ? L?.frame?.model || L?.hello?.model : viewer.demo?.wpa?.model;
  return `Round ${rm.round} · tick ${viewer.curTick}${model ? ` · model ${model}` : ''}`;
});

// click / drag to seek
let dragging = false;
function seekFrom(e: PointerEvent) {
  const c = canvas.value;
  if (!c || !cv.value) return;
  const rect = cv.value.getBoundingClientRect();
  viewer.seekTick(chartTickAt({ w: c.w, h: c.h, domain: viewer.tickDomain }, e.clientX - rect.left));
}
function onDown(e: PointerEvent) {
  if (!hasCursor.value) return;
  dragging = true;
  cv.value?.setPointerCapture(e.pointerId);
  seekFrom(e);
}
function onMove(e: PointerEvent) {
  if (dragging) seekFrom(e);
}
function onUp() {
  dragging = false;
}
</script>

<template>
  <section id="chart-section" class="card">
    <div class="chart-head">
      <div id="readout">
        <template v-if="readout">
          <span class="c-ct">CT {{ readout.ct }}</span><span class="sep">·</span><span class="c-t">T {{ readout.t }}</span>
        </template>
        <template v-else>
          <span class="c-ct">CT <span class="na">–</span></span><span class="sep">·</span><span class="c-t">T <span class="na">–</span></span>
        </template>
      </div>
      <div id="chart-ctx" class="muted">{{ context }}</div>
      <div class="legend">
        <span><i class="dot ct"></i>CT kill</span>
        <span><i class="dot t"></i>T kill</span>
        <span><i class="tri"></i>plant</span>
        <span><i class="dia"></i>defuse</span>
        <span><i class="star">&#9733;</i>explode</span>
      </div>
    </div>
    <div id="chart-wrap" ref="wrap">
      <canvas id="chart" ref="cv" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp"></canvas>
      <div v-if="noModel" id="chart-msg">Train a model to see win probability</div>
    </div>
  </section>
</template>
