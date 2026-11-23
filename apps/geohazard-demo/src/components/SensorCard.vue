<script setup lang="ts">
import { computed } from "vue";
import {
  Droplets,
  MoveUpRight,
  Activity,
  CloudRain,
  ScanLine,
  ArrowUpRight,
  Minus,
} from "lucide-vue-next";
import AnimatedNumber from "./AnimatedNumber.vue";
const props = defineProps<{
  name: string;
  label: string;
  value: number;
  unit: string;
  source: string;
  simulated?: boolean;
  values: number[];
  max: number;
  decimals: number;
}>();
const icons: Record<string, typeof Droplets> = {
  moisture: Droplets,
  tilt: MoveUpRight,
  vibration: Activity,
  rain: CloudRain,
  crack: ScanLine,
};
const delta = computed(() =>
  props.values.length > 1 ? props.value - props.values.at(-2)! : 0,
);
const alert = computed(
  () =>
    props.value >=
    ({ moisture: 65, tilt: 12, vibration: 0.4, rain: 30, crack: 4 }[
      props.name as "moisture"
    ] ?? props.max * 0.5),
);
const path = computed(() => {
  const v = props.values.slice(-40);
  if (!v.length) return "";
  return v
    .map(
      (y, i) =>
        `${i ? "L" : "M"}${(i * 170) / Math.max(1, v.length - 1)},${26 - (y / props.max) * 24}`,
    )
    .join(" ");
});
</script>
<template>
  <article class="sensor-card" :data-sensor="name">
    <div class="sensor-heading">
      <span><component :is="icons[name]" :size="15" />{{ label }}</span
      ><span :class="['sensor-state', { watch: alert }]"
        ><i />{{ alert ? "关注" : "稳定" }}</span
      >
    </div>
    <div class="sensor-reading">
      <strong><AnimatedNumber :value="value" :decimals="decimals" /></strong
      ><span>{{ unit }}</span
      ><span class="sensor-change"
        ><ArrowUpRight v-if="delta > 0" :size="13" /><Minus
          v-else
          :size="12"
        />{{ Math.abs(delta).toFixed(decimals) }}</span
      >
    </div>
    <svg
      viewBox="0 0 170 28"
      preserveAspectRatio="none"
      class="sparkline"
      aria-hidden="true"
    >
      <path
        :d="path"
        fill="none"
        :stroke="alert ? '#be9856' : '#74a189'"
        stroke-width="1.5"
        vector-effect="non-scaling-stroke"
      />
    </svg>
    <div class="sensor-source">
      <span>{{ source }}</span
      ><span v-if="simulated" class="sim-tag">场景模拟</span>
    </div>
  </article>
</template>
