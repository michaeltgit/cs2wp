<script setup lang="ts">
import { useDemosStore } from '@/stores/demos';
import { useSessionStore } from '@/stores/session';

const session = useSessionStore();
const demos = useDemosStore();
</script>

<template>
  <div id="empty-state" class="empty-state">
    <!-- explicit notice: failed demo / could not open -->
    <div v-if="session.notice" class="empty-card" :class="{ error: session.notice.isError }">
      <h1>{{ session.notice.title }}</h1>
      <p>
        {{ session.notice.message }}
        <template v-if="session.notice.detail"><br /><br /><code>{{ session.notice.detail }}</code></template>
      </p>
    </div>

    <!-- before the first demos list arrives -->
    <div v-else-if="!demos.loaded" class="empty-card">
      <h1>No demo open</h1>
      <p>Loading the demos list…</p>
    </div>

    <div v-else-if="!demos.list.length" class="empty-card">
      <h1>No demos yet</h1>
      <p>
        Demos are added on the backend: drop HLTV <code>.rar</code> / <code>.dem</code> files into <code>data/inbox</code>
        (or run <code>uv run cs2wp-pipeline ingest &lt;files&gt;</code>). Each one is parsed, featurized and scored, then shows
        up here as <b>ready</b>.
      </p>
    </div>

    <div v-else class="empty-card">
      <h1>Pick a demo</h1>
      <p v-if="demos.openableCount">
        Click a <b>ready</b> demo in the sidebar to open it. {{ demos.openableCount }} of {{ demos.list.length }} demos can be
        opened.
      </p>
      <p v-else>
        Your demos are still processing — watch the Jobs list. They open once they reach <b>ready</b> or <b>needs model</b>.
      </p>
    </div>
  </div>
</template>
