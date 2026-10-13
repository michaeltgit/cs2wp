<script setup lang="ts">
import { computed } from 'vue';
import { CT, REASONS, T } from '@/lib/constants';
import { useViewerStore } from '@/stores/viewer';

const viewer = useViewerStore();
const d = computed(() => viewer.demo!);
const row = computed(() => viewer.demoRow);
const r = computed(() => viewer.currentRound);
const kind = computed(() => d.value.wpa?.kind);
</script>

<template>
  <header id="demo-header">
    <span class="map">{{ d.map || '?' }}</span>
    <span v-if="row?.score" class="final">
      <span class="c-ct">{{ row.score.ct_side_end }}</span><span class="muted"> : </span><span class="c-t">{{ row.score.t_side_end }}</span>
    </span>
    <span class="kv">demo <b>{{ viewer.openId }}</b></span>
    <span class="kv">model <b>{{ d.wpa?.model || 'none' }}</b></span>
    <span
      v-if="kind === 'out-of-sample'"
      class="badge oos"
      title="These probabilities come from a model that was NOT trained on this match"
    >out-of-sample</span>
    <span
      v-else-if="kind === 'in-sample'"
      class="badge ins"
      title="The model that scored this demo was trained on this match: numbers look better than reality. Retrain on the backend (it rescores out-of-sample)."
    >in-sample</span>
    <span v-if="row?.status === 'needs_model'" class="badge needs_model">needs model</span>
    <span class="round-info">
      <template v-if="r">
        Round <b>{{ r.round }}</b> ·
        <span v-if="r.winner === CT" class="c-ct">CT win</span><span v-else-if="r.winner === T" class="c-t">T win</span><template v-else>?</template>
        · {{ (r.reason != null && REASONS[r.reason]) || `reason ${r.reason}` }}<template v-if="!r.valid"> · <span class="muted">invalid</span></template>
        · <span class="c-ct">{{ r.ct_score }}</span>–<span class="c-t">{{ r.t_score }}</span> before
      </template>
    </span>
  </header>
</template>
