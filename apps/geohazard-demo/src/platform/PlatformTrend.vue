<script setup lang="ts">
import { computed, ref } from "vue";
import type { HistoryPoint } from "./types";
import { dateTime, reading } from "./types";
const props = defineProps<{ points: HistoryPoint[]; color: string }>();
const hover = ref<number | null>(null);
const data = computed(() => props.points.slice(-100));
const points = computed(() => data.value.map((p, index) => ({ ...p, x: 6 + index * 308 / Math.max(1, data.value.length - 1), y: p.score == null ? null : 94 - p.score * .88 })));
const line = computed(() => { let active = false; return points.value.map((p) => { if (p.y == null) { active = false; return ""; } const command = `${active ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`; active = true; return command; }).join(" "); });
const current = computed(() => hover.value == null ? null : points.value[Math.min(hover.value, points.value.length - 1)]);
const hasScores = computed(() => data.value.some((p) => p.score != null));
function track(event: MouseEvent) { const box = (event.currentTarget as SVGElement).getBoundingClientRect(); hover.value = Math.round(Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) * Math.max(0, points.value.length - 1)); }
const stamp = (value: string | undefined) => value ? new Date(value).toLocaleTimeString("zh-CN", { hour12: false }) : "—";
</script>
<template>
  <div class="risk-chart platform-chart">
    <div class="chart-axis"><span>100</span><span>50</span><span>0</span></div>
    <svg viewBox="0 0 320 100" preserveAspectRatio="none" role="img" aria-label="后端保存的风险历史趋势；缺测和未标定处不连线" @mousemove="track" @mouseleave="hover = null"><path d="M0 6H320 M0 50H320 M0 94H320" stroke="#e9ede8" stroke-dasharray="3 4" fill="none" /><path :d="line" :stroke="color" stroke-width="2" fill="none" vector-effect="non-scaling-stroke" stroke-linejoin="round" /><template v-if="current && current.y != null"><path :d="`M${current.x} 0V100`" stroke="#95a097" stroke-dasharray="3 3" /><circle :cx="current.x" :cy="current.y" r="3" :fill="color" /></template></svg>
    <div v-if="!hasScores" class="chart-empty">{{ data.length ? '尚无已标定的风险分数' : '等待后端采样' }}</div><div v-if="current" class="chart-tooltip">{{ dateTime(current.time) }}<strong>{{ reading(current.score) }}</strong></div>
    <div class="chart-time"><span>{{ stamp(data[0]?.time) }}</span><span>入库时间</span><span>{{ stamp(data.at(-1)?.time) }}</span></div>
  </div>
</template>
