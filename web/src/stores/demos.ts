import { defineStore } from 'pinia';
import { computed, shallowRef } from 'vue';
import { api } from '@/api/client';
import type { DemoSummary } from '@/api/types';
import { OPENABLE } from '@/lib/constants';

export const useDemosStore = defineStore('demos', () => {
  const list = shallowRef<DemoSummary[]>([]);
  const loaded = shallowRef(false);

  const openableCount = computed(() => list.value.filter((d) => OPENABLE.has(d.status)).length);

  async function refresh() {
    try {
      list.value = await api.demos();
      loaded.value = true;
    } catch {
      /* keep the last list; the jobs poll retries */
    }
  }

  const byId = (id: string | null) => (id ? list.value.find((d) => d.id === id) ?? null : null);

  return { list, loaded, openableCount, refresh, byId };
});
