<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { BOMB_TIME, ROUND_TIME, SPEEDS, TICKRATE } from '@/lib/constants';
import { fmtClock } from '@/lib/format';
import { useViewerStore, type PlaybackMode } from '@/stores/viewer';

const viewer = useViewerStore();
const scrub = ref<HTMLInputElement | null>(null);
const dragging = ref(false);

const modes: { mode: PlaybackMode; label: string; title: string }[] = [
  { mode: 'replay', label: 'Stored replay', title: 'Replay the stored, batch-scored round' },
  { mode: 'live', label: 'Live stream', title: 'Stream the round through gamestate → inference → winprob' },
];

/** replay: tick index; live: tick */
const range = computed(() => {
  const hello = viewer.liveNow()?.hello;
  if (viewer.mode === 'live') return hello ? { min: hello.first_tick, max: hello.last_tick } : null;
  return viewer.R ? { min: 0, max: viewer.R.n - 1 } : null;
});
const scrubValue = computed(() => (viewer.mode === 'live' ? viewer.curTick : viewer.curIndex));

// Drive the range input imperatively so playback never fights a drag in progress.
watch(
  [scrubValue, range, scrub],
  () => {
    const el = scrub.value;
    if (!el || dragging.value) return;
    const r = range.value;
    el.min = String(r?.min ?? 0);
    el.max = String(r?.max ?? 0);
    el.value = String(scrubValue.value);
  },
  { flush: 'post', immediate: true },
);

function onScrub() {
  if (scrub.value) viewer.scrubTo(Number(scrub.value.value));
}

function onSpeed(e: Event) {
  const el = e.target as HTMLSelectElement;
  viewer.setSpeed(Number(el.value));
  el.blur();
}

const roundClock = computed(() => {
  const rm = viewer.currentRound;
  if (!rm) return '–:––';
  return fmtClock(Math.ceil(ROUND_TIME - (viewer.curTick - rm.freeze_end) / TICKRATE));
});

const bombClock = computed(() => {
  const R = viewer.R;
  const pl = R?.plant;
  const tick = viewer.curTick;
  if (!viewer.currentRound || !R || !pl || tick < pl.tick) return null;
  const defused = !!R.defuse && tick >= R.defuse.tick;
  const rem = Math.max(0, BOMB_TIME - ((defused ? R.defuse!.tick : tick) - pl.tick) / TICKRATE);
  return { done: defused, text: defused ? `C4 defused ${rem.toFixed(1)}` : `C4 ${rem.toFixed(1)}` };
});
</script>

<template>
  <div id="playback">
    <div class="pb-row">
      <div id="mode-toggle" class="seg">
        <button
          v-for="m in modes"
          :key="m.mode"
          :class="{ on: viewer.mode === m.mode }"
          :title="m.title"
          :data-mode="m.mode"
          @click="viewer.setMode(m.mode)"
        >{{ m.label }}</button>
      </div>
      <div class="transport">
        <button id="btn-back5" class="btn icon" title="Back 5 s (←)" @click="viewer.seekBy(-5 * TICKRATE)">−5s</button>
        <button id="btn-back1" class="btn icon" title="Back 1 tick (,)" @click="viewer.seekBy(-1)">−1t</button>
        <button id="btn-play" class="btn icon play" title="Play / pause (Space)" :aria-label="viewer.playing ? 'Pause' : 'Play'" @click="viewer.togglePlay()">
          <svg v-if="viewer.playing" viewBox="0 0 16 16"><path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" /></svg>
          <svg v-else viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" /></svg>
        </button>
        <button id="btn-fwd1" class="btn icon" title="Forward 1 tick (.)" @click="viewer.seekBy(1)">+1t</button>
        <button id="btn-fwd5" class="btn icon" title="Forward 5 s (→)" @click="viewer.seekBy(5 * TICKRATE)">+5s</button>
        <select id="speed" title="Playback speed (negative = rewind)" :value="viewer.speed" @change="onSpeed">
          <option v-for="s in SPEEDS" :key="s" :value="s">{{ s }}×</option>
        </select>
      </div>
      <div class="clocks">
        <span id="round-clock" title="Round clock">{{ roundClock }}</span>
        <span v-if="bombClock" id="bomb-clock" :class="{ done: bombClock.done }" title="Bomb timer">{{ bombClock.text }}</span>
      </div>
    </div>
    <input
      id="scrub"
      ref="scrub"
      type="range"
      min="0"
      max="0"
      step="1"
      aria-label="Round position"
      @input="onScrub"
      @pointerdown="dragging = true"
      @pointerup="dragging = false"
      @pointercancel="dragging = false"
      @change="dragging = false"
    />
  </div>
</template>
