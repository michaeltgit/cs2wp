<script setup lang="ts">
import { computed, reactive } from 'vue';
import { api } from '@/api/client';
import type { MetricSet, ModelVersion } from '@/api/types';
import { timeAgo } from '@/lib/format';
import { useJobsStore } from '@/stores/jobs';
import { useModelsStore } from '@/stores/models';

const models = useModelsStore();
const jobs = useJobsStore();
const openDetails = reactive(new Set<string>());
const brokenImg = reactive(new Set<string>());
const activating = reactive(new Set<string>());

const cards = computed(() => {
  const reg = models.registry;
  return reg ? models.versions.map((v) => ({ v, m: reg.versions[v]!, active: reg.active === v })) : [];
});

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

function metrics(m: ModelVersion): { base: MetricSet; cal: MetricSet } {
  const ov = m.overall || m.metrics?.overall || {};
  return { base: ov.baseline || {}, cal: ov.lightgbm_calibrated || ov.lightgbm || {} };
}

interface Row {
  label: string;
  base: string;
  cal: string;
  cls: string;
}

function rows(m: ModelVersion): Row[] {
  const { base, cal } = metrics(m);
  const f = (v: number | null | undefined) => (v == null ? '–' : v.toFixed(4));
  const out: Row[] = [];
  for (const [label, b, c] of [
    ['log loss', base.log_loss, cal.log_loss],
    ['Brier', base.brier, cal.brier],
  ] as const) {
    if (b == null && c == null) continue;
    out.push({ label, base: f(b), cal: f(c), cls: b != null && c != null ? (c < b ? 'better' : 'worse') : '' });
  }
  return out;
}

function importances(m: ModelVersion) {
  const fi = Object.entries(m.metrics?.feature_importance || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12);
  const max = Math.max(1e-9, ...fi.map((x) => x[1]));
  return fi.map(([name, gain]) => ({ name, gain, width: `${((gain / max) * 100).toFixed(1)}%` }));
}

function toggleDetails(v: string) {
  if (openDetails.has(v)) openDetails.delete(v);
  else openDetails.add(v);
}

async function activate(v: string) {
  activating.add(v);
  try {
    const r = await api.activateModel(v);
    jobs.watch(r.job_id);
  } catch (e) {
    alert(`Activate failed: ${errMsg(e)}`);
  }
  await models.refresh();
  activating.delete(v);
  void jobs.refresh();
}

</script>

<template>
  <section id="models-panel" class="panel">
    <h2>Models</h2>
    <div id="models-list">
      <div v-if="!models.versions.length" class="empty">No model trained yet (backend: <code>uv run cs2wp-ml train --activate</code>).</div>
      <div v-for="{ v, m, active } in cards" :key="v" class="model" :class="{ 'is-active': active }">
        <div class="top">
          <span class="ver">{{ v }}</span>
          <span v-if="active" class="badge active">active</span>
          <span class="muted" style="margin-left: auto">{{ m.created ? timeAgo(m.created) : '' }}</span>
        </div>
        <div class="meta">
          {{ m.n_demos ?? '?' }} demos · {{ m.n_rounds ?? '?' }} rounds · {{ m.held_out ? 'held-out eval' : 'in-sample eval' }}
        </div>
        <div v-if="!m.held_out" class="warn">In-sample, not trustworthy</div>
        <table>
          <tbody>
            <tr><th></th><th>baseline</th><th>LGBM cal.</th></tr>
            <tr v-for="r in rows(m)" :key="r.label">
              <td>{{ r.label }}</td><td>{{ r.base }}</td><td :class="r.cls">{{ r.cal }}</td>
            </tr>
          </tbody>
        </table>
        <div class="actions">
          <button class="btn small" :disabled="active || activating.has(v)" @click="activate(v)">Activate</button>
          <button class="btn small" @click="toggleDetails(v)">{{ openDetails.has(v) ? 'Hide details' : 'Details' }}</button>
        </div>
        <div v-if="openDetails.has(v)" class="details">
          <div v-if="brokenImg.has(v)" class="empty">No calibration plot</div>
          <img
            v-else
            :src="api.calibrationUrl(v, m.created ?? '')"
            :alt="`Calibration plot for ${v}`"
            loading="lazy"
            @error="brokenImg.add(v)"
          />
          <template v-if="importances(m).length">
            <div v-for="f in importances(m)" :key="f.name" class="fi">
              <span class="n" :title="f.name">{{ f.name }}</span>
              <span class="b"><i :style="{ width: f.width }"></i></span>
              <span class="v">{{ f.gain.toFixed(1) }}</span>
            </div>
          </template>
          <div v-else class="empty">No feature importances</div>
        </div>
      </div>
    </div>
  </section>
</template>
