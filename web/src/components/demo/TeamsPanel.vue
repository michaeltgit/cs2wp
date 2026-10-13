<script setup lang="ts">
import { computed } from 'vue';
import { CT, T } from '@/lib/constants';
import { clamp, money } from '@/lib/format';
import { useViewerStore } from '@/stores/viewer';

defineProps<{ wide: boolean }>();
const viewer = useViewerStore();

const teams = computed(() =>
  [CT, T].map((team) => {
    const players = viewer.playersNow
      .filter((p) => p.team === team)
      .sort((a, b) => String(a.name).localeCompare(String(b.name)))
      .map((p) => ({ ...p, hpPct: clamp(p.hp || 0, 0, 100) }));
    const alive = players.filter((p) => p.alive).length;
    const cash = players.reduce((s, p) => s + (p.money ?? 0), 0);
    return {
      team,
      key: team === CT ? 'ct' : 't',
      label: team === CT ? 'Counter-Terrorists' : 'Terrorists',
      players,
      summary: `${alive}/${players.length} alive${cash ? ` · ${money(cash)}` : ''}`,
    };
  }),
);
</script>

<template>
  <div id="teams" :class="{ wide }">
    <div v-for="t in teams" :key="t.team" class="team" :class="t.key">
      <div class="team-head"><span>{{ t.label }}</span><span class="alive">{{ t.summary }}</span></div>
      <div v-for="p in t.players" :key="p.steamid" class="pl" :class="{ dead: !p.alive }">
        <div class="pl-top">
          <span v-if="p.bomb" class="c4" title="Carrying the bomb">C4</span>
          <span class="pl-name" :title="p.name">{{ p.name }}</span><span class="pl-money">{{ money(p.money) }}</span>
        </div>
        <div class="pl-bot">
          <div class="hp"><i :class="{ low: p.hpPct <= 25 }" :style="{ width: `${p.hpPct}%` }"></i><span>{{ p.alive ? p.hpPct : 'dead' }}</span></div>
          <span class="armor" title="Armor">{{ p.armor != null ? `◈ ${p.armor}` : '' }}</span>
          <span class="wpn" :title="p.weapon || ''">{{ p.alive ? p.weapon || '' : '' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
