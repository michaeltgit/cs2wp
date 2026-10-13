<script setup lang="ts">
import type { DemoSummary } from '@/api/types';
import { OPENABLE } from '@/lib/constants';
import { useDemosStore } from '@/stores/demos';
import { useSessionStore } from '@/stores/session';
import { useViewerStore } from '@/stores/viewer';

const demos = useDemosStore();
const viewer = useViewerStore();
const session = useSessionStore();

function onClick(d: DemoSummary) {
  if (OPENABLE.has(d.status)) void viewer.openDemo(d.id);
  else if (d.status === 'failed') {
    viewer.closeDemo();
    session.showNotice({
      title: 'Demo failed to process',
      message: d.filename || d.id,
      detail: d.error || 'Unknown error',
      isError: true,
    });
  }
}

function showStatus() {
  viewer.closeDemo();
  session.showStatus();
}
</script>

<template>
  <section id="demos-panel" class="panel">
    <h2>
      Demos <span id="demos-count" class="count">{{ demos.list.length || '' }}</span>
      <button id="status-btn" class="btn small" @click="showStatus">Data status</button>
    </h2>
    <ul id="demos-list" class="list">
      <li v-if="!demos.list.length" class="empty">No demos yet (added on the backend).</li>
      <li
        v-for="d in demos.list"
        :key="d.id"
        class="demo"
        :class="{ openable: OPENABLE.has(d.status), active: d.id === viewer.openId }"
        :title="d.id"
        @click="onClick(d)"
      >
        <div class="top">
          <span class="map">{{ d.map || '…' }}</span>
          <span class="badge" :class="d.status">{{ String(d.status).replace('_', ' ') }}</span>
          <span class="score">
            <template v-if="d.score">
              <span class="c-ct">{{ d.score.ct_side_end }}</span><span class="muted"> : </span><span class="c-t">{{ d.score.t_side_end }}</span>
            </template>
          </span>
        </div>
        <div class="file">{{ d.filename || d.id }}{{ d.n_rounds ? ` · ${d.n_rounds} rounds` : '' }}</div>
        <div v-if="d.status === 'failed' && d.error" class="err">{{ d.error }}</div>
      </li>
    </ul>
  </section>
</template>
