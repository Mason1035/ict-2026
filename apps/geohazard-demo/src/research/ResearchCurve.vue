<script setup lang="ts">
import { computed } from "vue";
import type { Curve, Period } from "./api";
const props = defineProps<{ curve: Curve; title: string; duration: number; periods: Period[] }>();
const width = 800, left = 70, right = 780, top = 16, bottom = 150;
const finite = computed(() => props.curve.points.flatMap((p) => p.value == null ? [] : [p.value]));
const bounds = computed(() => {
  const min = Math.min(...finite.value), max = Math.max(...finite.value);
  const pad = Math.max((max - min) * .08, Math.abs(max) * .01, 1e-8);
  return { min: min - pad, max: max + pad };
});
const x = (t: number) => left + Math.max(0, Math.min(1, t / Math.max(props.duration * 1e6, 1))) * (right - left);
const y = (v: number) => bottom - (v - bounds.value.min) / (bounds.value.max - bounds.value.min) * (bottom - top);
const path = computed(() => {
  let connected = false;
  return props.curve.points.map((p) => {
    if (p.value == null) { connected = false; return ""; }
    const command = connected && !p.break_before ? "L" : "M";
    connected = true;
    return `${command}${x(p.time_us).toFixed(2)},${y(p.value).toFixed(2)}`;
  }).join(" ");
});
const format = (v: number) => Number.isFinite(v) ? v.toPrecision(4) : "—";
</script>
<template>
  <figure class="research-curve">
    <figcaption><strong>{{ title }}</strong><span>{{ curve.unit }} · {{ curve.points.length }} / {{ curve.input_points }} 评估点</span></figcaption>
    <svg v-if="finite.length" :viewBox="`0 0 ${width} 180`" role="img" :aria-label="`${title}，横轴为场内秒，纵轴 ${curve.unit}`">
      <g v-for="(period, index) in periods" :key="index" :class="period.candidate_only ? 'candidate' : 'trigger'">
        <rect :x="x(period.start_us)" :y="top" :width="Math.max(0, x(period.confirmed_at_us) - x(period.start_us))" :height="bottom - top" opacity=".1"><title>持续越限，尚未确认</title></rect>
        <rect :x="x(period.confirmed_at_us)" :y="top" :width="Math.max(0, x(period.end_us) - x(period.confirmed_at_us))" :height="bottom - top" opacity=".22"><title>{{ period.candidate_only ? '振动候选' : '研究触发' }} · {{ (period.confirmed_at_us / 1e6).toFixed(3) }}–{{ (period.end_us / 1e6).toFixed(3) }} s</title></rect>
      </g>
      <path :d="`M${left},${top}V${bottom}H${right}`" fill="none" stroke="#c7d1ce" />
      <path :d="path" fill="none" stroke="#277d76" stroke-width="1.7" vector-effect="non-scaling-stroke" />
      <text x="4" :y="top + 7">{{ format(bounds.max) }}</text><text x="4" :y="bottom">{{ format(bounds.min) }}</text>
      <text v-for="tick in [0, .5, 1]" :key="tick" :x="x(tick * duration * 1e6)" y="173" text-anchor="middle">{{ (tick * duration).toFixed(1) }} s</text>
    </svg>
    <p v-else>无可用指标：预热、缺测或基线不足；未以 0 补值。</p>
  </figure>
</template>
<style scoped>
.research-curve { margin: 16px 0 0; } figcaption { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; } figcaption span, text { color: #667b78; fill: #667b78; font-size: 11px; } svg { display: block; width: 100%; margin-top: 6px; } .trigger { fill: #b65348; } .candidate { fill: #c18b24; } p { color: #667b78; padding: 20px; }
</style>
