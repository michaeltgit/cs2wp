<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue';
import AppSidebar from './components/sidebar/AppSidebar.vue';
import DemoView from './components/demo/DemoView.vue';
import EmptyState from './components/EmptyState.vue';
import StatusView from './components/StatusView.vue';
import { useKeyboard } from './composables/useKeyboard';
import { usePlaybackLoop } from './composables/usePlayback';
import { parseDeepLink } from './lib/hash';
import { useJobsStore } from './stores/jobs';
import { useSessionStore } from './stores/session';
import { useViewerStore } from './stores/viewer';

const session = useSessionStore();
const viewer = useViewerStore();
const jobs = useJobsStore();

usePlaybackLoop((dt, now) => viewer.onFrame(dt, now));

useKeyboard({
  enabled: () => viewer.playable || !!viewer.R,
  run: (a) => {
    if (a.kind === 'toggle') viewer.togglePlay();
    else if (a.kind === 'seek') viewer.seekBy(a.ticks);
    else viewer.stepRound(a.delta);
  },
});

// deep link: #demo=ID&round=N (our own history.replaceState calls do not fire hashchange)
function followHash() {
  const link = parseDeepLink(location.hash);
  if (!link) return;
  if (link.demo !== viewer.openId) void viewer.openDemo(link.demo, link.round);
  else if (link.round != null && link.round !== viewer.roundNo) void viewer.loadRound(link.round);
}

onMounted(() => {
  jobs.start();
  followHash();
  window.addEventListener('hashchange', followHash);
});
onBeforeUnmount(() => {
  jobs.stop();
  window.removeEventListener('hashchange', followHash);
});
</script>

<template>
  <AppSidebar />
  <main id="main">
    <EmptyState v-if="session.view === 'home'" />
    <StatusView v-else-if="session.view === 'status'" :key="session.statusNonce" />
    <DemoView v-else-if="viewer.demo" />
  </main>
</template>
