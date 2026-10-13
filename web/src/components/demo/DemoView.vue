<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useElementWidth } from '@/composables/useCanvas';
import { clamp } from '@/lib/format';
import DemoHeader from './DemoHeader.vue';
import KillFeed from './KillFeed.vue';
import MapWinPanel from './MapWinPanel.vue';
import PlaybackBar from './PlaybackBar.vue';
import RadarCanvas from './RadarCanvas.vue';
import RoundStrip from './RoundStrip.vue';
import TeamsPanel from './TeamsPanel.vue';
import WinProbChart from './WinProbChart.vue';
import WpaTable from './WpaTable.vue';

const RIGHT_MIN = 320;
const GAP = 12;

const stage = ref<HTMLElement | null>(null);
const radarCol = ref<HTMLElement | null>(null);
const stageW = useElementWidth(stage);
const innerH = ref(window.innerHeight);
const radarColH = ref(0);

const onResize = () => {
  innerH.value = window.innerHeight;
};
let ro: ResizeObserver | null = null;
onMounted(() => {
  window.addEventListener('resize', onResize);
  ro = new ResizeObserver(() => {
    radarColH.value = radarCol.value?.offsetHeight ?? 0;
  });
  if (radarCol.value) ro.observe(radarCol.value);
});
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  ro?.disconnect();
});

/** radar side: as big as the width (leaving room for the right column) and height allow */
const radarSize = computed(() => {
  const sw = stageW.value;
  if (!sw) return 560;
  return Math.floor(clamp(Math.min(sw - RIGHT_MIN - GAP, innerH.value - 320), 300, 1000));
});
const wideTeams = computed(() => stageW.value - radarSize.value - GAP >= 470);
</script>

<template>
  <div id="demo-view">
    <DemoHeader />
    <RoundStrip />

    <div id="stage" ref="stage" :style="{ gridTemplateColumns: `${radarSize}px minmax(${RIGHT_MIN}px, 1fr)` }">
      <div id="radar-col" ref="radarCol">
        <RadarCanvas :size="radarSize" />
        <PlaybackBar />
      </div>
      <div id="right-col" :style="radarColH ? { height: `${radarColH}px` } : undefined">
        <TeamsPanel :wide="wideTeams" />
        <KillFeed />
      </div>
    </div>

    <WinProbChart />
    <MapWinPanel />
    <WpaTable />
  </div>
</template>
