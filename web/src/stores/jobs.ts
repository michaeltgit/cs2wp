import { defineStore } from 'pinia';
import { computed, shallowRef } from 'vue';
import { api } from '@/api/client';
import type { Job } from '@/api/types';
import { ACTIVE_JOB } from '@/lib/constants';
import { useDemosStore } from './demos';
import { useModelsStore } from './models';
import { useViewerStore } from './viewer';

export const FAST_POLL_MS = 2000;
export const SLOW_POLL_MS = 10000;
export const RETRY_POLL_MS = 5000;

/** Jobs that just left queued/running (or that we started and are no longer active). */
export function finishedJobs(prev: Job[], next: Job[], watched: Set<string>): Job[] {
  const before = new Map(prev.map((j) => [j.id, j.status]));
  return next.filter(
    (j) => !ACTIVE_JOB.has(j.status) && ((before.has(j.id) && ACTIVE_JOB.has(before.get(j.id)!)) || watched.has(j.id)),
  );
}

export const useJobsStore = defineStore('jobs', () => {
  const list = shallowRef<Job[]>([]);
  /** job ids this UI started; refresh when they finish */
  const watched = new Set<string>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let firstLoad = true;
  let running = false;

  const activeCount = computed(() => list.value.filter((j) => ACTIVE_JOB.has(j.status)).length);

  function watch(id: string | null | undefined) {
    if (id) watched.add(id);
  }

  function schedule(ms: number) {
    if (timer) clearTimeout(timer);
    timer = running ? setTimeout(refresh, ms) : null;
  }

  /** Poll /api/jobs: 2 s while work is in flight, 10 s otherwise (catches CLI-started jobs). */
  async function refresh(): Promise<void> {
    if (timer) clearTimeout(timer);
    let jobs: Job[];
    try {
      jobs = await api.jobs();
    } catch {
      schedule(RETRY_POLL_MS);
      return;
    }
    const finished = finishedJobs(list.value, jobs, watched);
    finished.forEach((j) => watched.delete(j.id));
    list.value = jobs;

    const anyActive = jobs.some((j) => ACTIVE_JOB.has(j.status));
    if (finished.length || anyActive || firstLoad) {
      await Promise.all([useDemosStore().refresh(), useModelsStore().refresh()]);
    }
    const viewer = useViewerStore();
    if (!firstLoad && finished.length && viewer.openId) {
      const affects = finished.some((j) => j.kind !== 'process' || j.demo_id === viewer.openId);
      if (affects) void viewer.reloadOpenDemo();
    }
    firstLoad = false;
    schedule(anyActive || watched.size ? FAST_POLL_MS : SLOW_POLL_MS);
  }

  function start() {
    if (running) return;
    running = true;
    void refresh();
  }

  function stop() {
    running = false;
    if (timer) clearTimeout(timer);
    timer = null;
  }

  return { list, activeCount, watch, refresh, start, stop };
});
