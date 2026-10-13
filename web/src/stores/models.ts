import { defineStore } from 'pinia';
import { computed, shallowRef } from 'vue';
import { api } from '@/api/client';
import type { ModelRegistry } from '@/api/types';

export const useModelsStore = defineStore('models', () => {
  const registry = shallowRef<ModelRegistry | null>(null);

  /** newest first */
  const versions = computed(() => (registry.value ? Object.keys(registry.value.versions || {}).sort().reverse() : []));

  async function refresh() {
    try {
      registry.value = await api.models();
    } catch {
      /* keep last */
    }
  }

  return { registry, versions, refresh };
});
