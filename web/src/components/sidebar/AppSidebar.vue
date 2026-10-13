<script setup lang="ts">
import DemosPanel from './DemosPanel.vue';
import JobsPanel from './JobsPanel.vue';
import ModelsPanel from './ModelsPanel.vue';
</script>

<template>
  <aside id="sidebar">
    <div class="brand">CS2 <b>WinProb</b><span class="brand-sub">round win probability</span></div>
    <JobsPanel />
    <DemosPanel />
    <ModelsPanel />
  </aside>
</template>
