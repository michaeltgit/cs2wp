<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue';
import { api } from '@/api/client';
import type { StatusMap, StatusResponse } from '@/api/types';
import { useViewerStore } from '@/stores/viewer';

const viewer = useViewerStore();
const status = shallowRef<StatusResponse | null>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try {
    status.value = await api.status();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
});

const matchLabel = (m: string) => m.replace(/^[0-9a-f]{8}-/, '').slice(0, 58);
const scoreCls = (k: string | null) => (k === 'out-of-sample' ? 'oos' : k === 'in-sample' ? 'ins' : '');

function open(x: StatusMap, e: MouseEvent) {
  if ((e.target as Element).closest('a')) return;
  void viewer.openDemo(x.id);
}
</script>

<template>
  <div id="status-view">
    <div v-if="error" class="card st-wrap err">{{ error }}</div>
    <div v-else-if="!status" class="card st-wrap muted">loading status…</div>
    <div v-else class="card st-wrap">
      <h2>Data status</h2>
      <div class="st-cards">
        <div class="st-card"><span>Matches</span><b>{{ status.summary.matches }}</b><i></i></div>
        <div class="st-card">
          <span>Maps</span><b>{{ status.summary.maps }}</b><i>{{ status.summary.ready }} ready · {{ status.summary.failed }} failed</i>
        </div>
        <div class="st-card">
          <span>Kalshi</span><b>{{ status.summary.kalshi_linked }} linked</b><i>{{ status.summary.kalshi_no_market }} no market</i>
        </div>
        <div class="st-card">
          <span>Alignment</span><b>{{ status.summary.alignment.good }} good</b>
          <i>{{ status.summary.alignment.weak }} weak · {{ status.summary.alignment.bad }} bad</i>
        </div>
        <div class="st-card">
          <span>Scores</span><b>{{ status.summary.out_of_sample }} out-of-sample</b><i>{{ status.summary.in_sample }} in-sample</i>
        </div>
      </div>
      <table class="st-table">
        <thead>
          <tr>
            <th>Match</th><th>Map</th><th>Status</th><th>Rounds</th><th>Kalshi / alignment</th><th>Scores</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="m in status.matches" :key="m.match">
            <tr v-for="(x, i) in m.maps" :key="x.id" :class="{ first: i === 0 }" :data-id="x.id" @click="open(x, $event)">
              <td>{{ i === 0 ? matchLabel(m.match) : '' }}</td>
              <td>{{ (x.map || '?').replace('de_', '') }}</td>
              <td><span class="badge" :class="x.status">{{ x.status }}</span></td>
              <td>{{ x.rounds ?? '' }}</td>
              <td>
                <span v-if="x.kalshi === 'linked'" class="badge" :class="`al-${x.alignment || 'none'}`" :title="x.ticker || ''">
                  {{ x.alignment || 'linked' }}
                </span>
                <span v-else class="muted">{{ x.kalshi || '–' }}</span>
              </td>
              <td><span class="badge" :class="scoreCls(x.score_kind)">{{ x.score_kind || '–' }}</span></td>
            </tr>
          </template>
        </tbody>
      </table>
      <p class="muted">
        Click a row to open that map. Alignment "good" = the market is flat before round ends and moves the round's way right after.
      </p>
    </div>
  </div>
</template>
