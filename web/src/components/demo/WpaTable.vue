<script setup lang="ts">
import { computed } from 'vue';
import { useViewerStore } from '@/stores/viewer';

const viewer = useViewerStore();
const wpa = computed(() => viewer.demo?.wpa ?? null);

const rows = computed(() => {
  const w = wpa.value;
  if (!w?.players?.length) return [];
  const players = [...w.players].sort((a, b) => b.wpa - a.wpa);
  const max = Math.max(1e-9, ...players.map((p) => Math.abs(p.wpa)));
  return players.map((p) => {
    const v = p.wpa * 100;
    return {
      ...p,
      cls: v > 0.05 ? 'pos' : v < -0.05 ? 'neg' : '',
      text: `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}`,
      width: `${((Math.abs(p.wpa) / max) * 50).toFixed(1)}%`,
      bar: p.wpa >= 0 ? 'pos' : 'neg',
    };
  });
});
</script>

<template>
  <section id="wpa-section" class="card">
    <h3>
      Win Probability Added &middot; whole match
      <span id="wpa-model" class="muted">{{ wpa?.model ? `(model ${wpa.model})` : '' }}</span>
    </h3>
    <table id="wpa">
      <tbody>
        <tr v-if="!rows.length"><td class="empty" style="text-align: left">No WPA yet — train a model to score this demo.</td></tr>
        <template v-else>
          <tr><th>#</th><th>Player</th><th>WPA</th><th>K</th><th>D</th><th>Plants</th><th>Defuses</th><th></th></tr>
          <tr v-for="(p, i) in rows" :key="p.steamid">
            <td class="rank">{{ i + 1 }}</td>
            <td class="name">{{ p.name }}</td>
            <td :class="p.cls">{{ p.text }}</td>
            <td>{{ p.kills }}</td><td>{{ p.deaths }}</td><td>{{ p.plants }}</td><td>{{ p.defuses }}</td>
            <td class="barcell"><div class="dbar"><i :class="p.bar" :style="{ width: p.width }"></i></div></td>
          </tr>
        </template>
      </tbody>
    </table>
  </section>
</template>
