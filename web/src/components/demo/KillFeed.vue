<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { RoundEvent } from '@/api/types';
import { TICKRATE } from '@/lib/constants';
import { fmtClock, swingPill, teamKey } from '@/lib/format';
import { lastAtOrBefore } from '@/lib/series';
import { useViewerStore } from '@/stores/viewer';

const viewer = useViewerStore();
const list = ref<HTMLOListElement | null>(null);

const feed = computed<RoundEvent[]>(() => viewer.R?.feed ?? []);
const feedTicks = computed(() => feed.value.map((e) => e.tick));
const freezeEnd = computed(() => viewer.R?.round.freeze_end ?? 0);

/** index of the latest event at or before the playhead */
const lastPast = computed(() => (feed.value.length ? lastAtOrBefore(feedTicks.value, viewer.curTick) : -1));

const rows = computed(() =>
  feed.value.map((e, i) => ({
    e,
    i,
    time: fmtClock((e.tick - freezeEnd.value) / TICKRATE),
    actorCls: teamKey(Number(e.actor_team)),
    victimCls: teamKey(Number(e.victim_team)),
    pill: swingPill(e.swing_ct),
  })),
);

function seek(e: RoundEvent) {
  viewer.seekTick(e.tick - 2 * TICKRATE);
}

// keep the latest passed row visible inside the list (without scrolling the page)
watch(lastPast, async (i) => {
  if (i < 0 || !viewer.playing) return;
  await nextTick();
  const ol = list.value;
  const li = ol?.children[i] as HTMLElement | undefined;
  if (!ol || !li) return;
  const lr = li.getBoundingClientRect();
  const or = ol.getBoundingClientRect();
  if (lr.bottom > or.bottom) ol.scrollTop += lr.bottom - or.bottom;
  else if (lr.top < or.top) ol.scrollTop -= or.top - lr.top;
});
</script>

<template>
  <div id="events-panel" class="card">
    <h3>Kill feed &amp; bomb</h3>
    <ol id="events" ref="list">
      <li v-if="viewer.roundError" class="empty" style="padding: 8px 10px">Failed to load round: {{ viewer.roundError }}</li>
      <li v-else-if="viewer.R && !feed.length" class="empty" style="padding: 8px 10px">No kills or bomb events this round</li>
      <template v-else>
      <li
        v-for="r in rows"
        :key="r.i"
        class="ev"
        :class="{ past: r.i <= lastPast, current: r.i === lastPast }"
        @click="seek(r.e)"
      >
        <span class="tm">{{ r.time }}</span>
        <span class="txt">
          <template v-if="r.e.type === 'kill'">
            <span v-if="r.e.actor_name" :class="r.actorCls">{{ r.e.actor_name }}</span><span v-else class="muted">world</span>
            → <span :class="r.victimCls">{{ r.e.victim_name ?? '?' }}</span>
            <span class="wpn-n"> ({{ r.e.weapon || '?' }})</span><span v-if="r.e.headshot" class="hs">HS</span>
          </template>
          <template v-else-if="r.e.type === 'plant'">
            <span :class="r.actorCls">{{ r.e.actor_name ?? '?' }}</span> <span class="tag">planted the bomb</span>
          </template>
          <template v-else-if="r.e.type === 'defuse_start'">
            <span :class="r.actorCls">{{ r.e.actor_name ?? '?' }}</span> started defusing
          </template>
          <template v-else-if="r.e.type === 'defuse'">
            <span :class="r.actorCls">{{ r.e.actor_name ?? '?' }}</span> <span class="tag">defused the bomb</span>
          </template>
          <span v-else-if="r.e.type === 'explode'" class="tag" style="color: var(--bomb)">Bomb exploded</span>
          <template v-else>{{ r.e.type }}</template>
        </span>
        <span v-if="r.pill" class="pill" :class="r.pill.cls">{{ r.pill.text }}</span>
      </li>
      </template>
    </ol>
  </div>
</template>
