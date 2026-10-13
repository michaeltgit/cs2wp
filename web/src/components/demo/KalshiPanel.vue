<script setup lang="ts">
import { computed } from 'vue';
import type { KalshiDisagreement } from '@/api/types';
import { MAPC } from '@/lib/constants';
import { fmtClock, pct, ptsOrDash, signedPts } from '@/lib/format';
import { useMapOddsStore } from '@/stores/mapOdds';
import { useViewerStore } from '@/stores/viewer';

const viewer = useViewerStore();
const odds = useMapOddsStore();

const teams = computed(() => odds.data?.teams ?? null);
const k = computed(() => odds.kal);
const yesName = computed(() => {
  const kk = k.value;
  if (!kk) return '';
  return (kk.yes_team === 'a' ? teams.value?.a?.name : teams.value?.b?.name) || kk.yes_team;
});
const startText = computed(() => (k.value ? new Date(k.value.start_ts * 1000).toLocaleString() : ''));

// ---- analysis card
const a = computed(() => odds.analysis);
const al = computed(() => a.value?.alignment ?? {});
const teamA = computed(() => a.value?.teams?.a?.name || 'Team A');
const alTitle = computed(
  () =>
    `Market moves after round ends: ${ptsOrDash(al.value.post_move)}; before: ${ptsOrDash(al.value.pre_move)}; ` +
    `best fit within ±5 min at ${al.value.best_offset_s ?? '–'} s`,
);
const weak = computed(() => (al.value.confidence ? al.value.confidence !== 'good' : !((a.value?.lag_corr ?? -Infinity) >= 0.2)));
const better = computed(() => ((a.value?.brier_ours ?? Infinity) < (a.value?.brier_market ?? Infinity) ? 'our model' : 'the market'));
const postMove = computed(() => {
  const v = al.value.post_move;
  return v != null ? `${v * 100 >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)} pts` : '–';
});

async function jump(d: KalshiDisagreement) {
  if (d.round !== viewer.roundNo) await viewer.loadRound(d.round);
  viewer.seekTick(d.tick);
  if (odds.zoom !== 'round') odds.setZoom('round');
  document.getElementById('radar-wrap')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
</script>

<template>
  <div v-if="odds.data" id="kalshi-panel">
    <!-- linked market -->
    <template v-if="k">
      <div class="row">
        <b>Kalshi</b> <span>{{ k.title || k.ticker }}</span>
        <span class="muted">{{ k.ticker }} · YES = {{ yesName }}{{ k.result ? ` · settled ${k.result}` : '' }}</span>
      </div>
      <div class="row stat">
        Round 1 aligned to <b>{{ startText }}</b> · mean |model − market|
        <b>{{ k.mean_abs_gap != null ? `${(k.mean_abs_gap * 100).toFixed(1)} pts` : '–' }}</b> over <b>{{ k.n_compared }}</b> minutes
      </div>
      <div id="k-analysis" class="k-analysis" :class="{ muted: !a || !a.n_seconds }">
        <span v-if="odds.analysisError" class="err">{{ odds.analysisError }}</span>
        <template v-else-if="!a">analysing…</template>
        <template v-else-if="!a.n_seconds">No overlap between the market and this map.</template>
        <template v-else>
          <div class="row">
            <span class="badge" :class="`al-${al.confidence || 'none'}`" :title="alTitle">alignment: {{ al.confidence || 'unknown' }}</span>
          </div>
          <div v-if="weak" class="k-warn">
            ⚠ Alignment is {{ al.confidence || 'uncertain' }}: the market's moves after round ends are weak or a different offset fits
            better. Check a few round ends in the trade-by-trade view: the purple jumps should follow the round results.
          </div>
          <div class="k-stats">
            <div>
              <span>Avg gap</span><b>{{ ((a.mean_abs_gap ?? 0) * 100).toFixed(1) }} pts</b>
              <i>we rate {{ teamA }} {{ signedPts(a.mean_gap ?? 0) }} vs market on average</i>
            </div>
            <div>
              <span>Who was closer to the result?</span><b>{{ better }}</b>
              <i>
                Brier (lower = better): model {{ a.brier_ours?.toFixed(3) ?? '–' }} · market {{ a.brier_market?.toFixed(3) ?? '–' }} · final
                {{ a.final }}
              </i>
            </div>
            <div>
              <span>Market reaction to round results</span><b>{{ postMove }}</b>
              <i>
                avg move in the round's direction within ~60 s of a round end · before it:
                {{ ptsOrDash(al.pre_move) }} (should be ≈0)
              </i>
            </div>
            <div>
              <span>Data</span><b>{{ (a.n_trades ?? 0).toLocaleString() }} trades</b>
              <i>{{ a.n_seconds.toLocaleString() }} s compared · aligned by {{ a.aligned_by || '?' }} · level corr {{ a.level_corr ?? '–' }}</i>
            </div>
          </div>
          <div class="k-dis-h">Biggest disagreements <span class="muted">(click to jump there)</span></div>
          <table class="k-dis">
            <tbody>
              <tr v-for="d in a.disagreements || []" :key="`${d.round}-${d.tick}`" :data-r="d.round" :data-t="d.tick" @click="jump(d)">
                <td>R{{ d.round }}</td>
                <td>{{ fmtClock(d.round_secs) }}</td>
                <td>{{ d.score }}</td>
                <td :style="{ color: MAPC.ours }">model {{ pct(d.ours) }}</td>
                <td :style="{ color: MAPC.kal }">market {{ pct(d.market) }}</td>
                <td :class="d.gap >= 0 ? 'pos' : 'neg'">{{ signedPts(d.gap) }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </template>

    <!-- not linked -->
    <div v-else class="row muted">
      <b>Kalshi</b> No market linked for this map. Kalshi lists mostly tier-1/2 matches; linking runs
      automatically after a demo is processed.
    </div>
  </div>
</template>
