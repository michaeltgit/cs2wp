<script setup lang="ts">
import { computed } from 'vue';
import { CT, REASONS, T } from '@/lib/constants';
import { pct } from '@/lib/format';
import { useViewerStore } from '@/stores/viewer';

const viewer = useViewerStore();

const chips = computed(() => {
  const rounds = viewer.demo?.rounds || [];
  let prevCt: Set<string> | null = null;
  return rounds.map((r) => {
    const p = r.p_ct_start ?? null;
    const ctSet = new Set(r.ct_players || []);
    // a side swap: almost nobody from last round's CT side is CT now
    const swapped = !!prevCt && ctSet.size > 0 && [...ctSet].filter((x) => prevCt!.has(x)).length <= 1;
    prevCt = ctSet;
    const tip =
      `Round ${r.round}: ${r.winner === CT ? 'CT' : r.winner === T ? 'T' : '?'} win (${(r.reason != null && REASONS[r.reason]) || r.reason})` +
      `${p != null ? ` · P(CT) at start ${pct(p)}` : ''}${r.valid ? '' : ' · invalid (not used for training)'}`;
    return { round: r.round, winner: r.winner, valid: r.valid, p, swapped, tip };
  });
});
</script>

<template>
  <nav id="round-strip" aria-label="Rounds">
    <div
      v-for="c in chips"
      :key="c.round"
      class="chip"
      :class="[`w${c.winner}`, { invalid: !c.valid, on: c.round === viewer.roundNo, half: c.swapped }]"
      :title="c.tip"
      role="button"
      tabindex="0"
      @click="viewer.loadRound(c.round)"
      @keydown.enter="viewer.loadRound(c.round)"
    >
      <div class="rn">{{ c.round }}</div>
      <div class="pb">
        <template v-if="c.p != null"><i :style="{ width: `${(c.p * 100).toFixed(1)}%` }"></i><b></b></template>
      </div>
    </div>
  </nav>
</template>
