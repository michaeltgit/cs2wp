<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue';
import { useCanvas } from '@/composables/useCanvas';
import { liveBadge } from '@/composables/useLiveStream';
import { drawRadar } from '@/lib/draw/radar';
import { useViewerStore } from '@/stores/viewer';

const props = defineProps<{ size: number }>();
const viewer = useViewerStore();
const cv = ref<HTMLCanvasElement | null>(null);
const canvas = useCanvas(cv, () => ({ w: props.size, h: props.size }));

watchEffect(
  () => {
    const c = canvas.value;
    if (!c) return;
    const live = viewer.liveNow();
    drawRadar(c.ctx, {
      w: c.w,
      h: c.h,
      map: viewer.mapAsset,
      R: viewer.R,
      players: viewer.playersNow,
      tick: viewer.curTick,
      replay: viewer.mode === 'replay',
      active: !!viewer.R || !!live?.frame,
    });
  },
  { flush: 'post' },
);

const badge = computed(() => {
  const L = viewer.liveNow();
  return L ? liveBadge(L) : null;
});
</script>

<template>
  <div id="radar-wrap" :style="{ width: `${size}px`, height: `${size}px` }">
    <canvas id="radar" ref="cv"></canvas>
    <div id="radar-hud">
      <template v-if="viewer.aliveCounts.any">
        <span class="c-ct">{{ viewer.aliveCounts.ct }}</span><span class="vs">v</span><span class="c-t">{{ viewer.aliveCounts.t }}</span>
      </template>
    </div>
    <div v-if="badge" id="live-badge" :class="badge.cls">
      <i class="ldot"></i><template v-if="badge.live"><b>LIVE</b></template>{{ badge.text }}
    </div>
  </div>
</template>
