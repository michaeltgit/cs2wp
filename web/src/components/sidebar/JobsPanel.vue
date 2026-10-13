<script setup lang="ts">
import { computed, reactive } from 'vue';
import type { Job } from '@/api/types';
import { timeAgo } from '@/lib/format';
import { useJobsStore } from '@/stores/jobs';

const jobs = useJobsStore();
const expanded = reactive(new Set<string>());

const count = computed(() => {
  const n = jobs.list.length;
  if (!n) return '';
  return jobs.activeCount ? `${jobs.activeCount} active` : String(n);
});

const what = (j: Job) => (j.kind === 'process' ? `process ${j.demo_id ?? ''}` : j.kind);
const stage = (j: Job) => (j.status === 'running' ? j.stage || 'running' : j.status);
const lastLine = (j: Job) => (j.message ? j.message.trim().split('\n').pop() || '' : '');
const title = (j: Job) =>
  j.status === 'failed' ? j.message || 'failed' : `${j.kind} · ${j.status} · ${timeAgo(j.updated_at || j.created_at)}`;

function toggle(j: Job, e: MouseEvent) {
  if (j.status !== 'failed') return;
  if ((e.target as Element).closest('pre')) return;
  if (expanded.has(j.id)) expanded.delete(j.id);
  else expanded.add(j.id);
}
</script>

<template>
  <section id="jobs-panel" class="panel">
    <h2>Jobs <span id="jobs-count" class="count">{{ count }}</span></h2>
    <ul id="jobs-list" class="list scroll">
      <li v-if="!jobs.list.length" class="empty">No jobs yet</li>
      <li v-for="j in jobs.list" :key="j.id" class="job" :class="j.status" :title="title(j)" @click="toggle(j, $event)">
        <i class="sdot"></i><span class="what">{{ what(j) }}</span><span class="stage">{{ stage(j) }}</span>
        <pre v-if="j.status === 'failed' && expanded.has(j.id)">{{ j.message || 'no message' }}</pre>
        <div v-else-if="j.status === 'running' && j.kind === 'train' && lastLine(j)" class="hint">{{ lastLine(j) }}</div>
      </li>
    </ul>
  </section>
</template>
