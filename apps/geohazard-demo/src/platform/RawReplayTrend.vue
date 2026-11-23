<script setup lang="ts">
import { computed } from "vue";
import type { TelemetryRow } from "./types";
const props = defineProps<{ rows: TelemetryRow[] }>();
import { replayGroups, rawPath, type RawReplayPayload } from "./rawReplay";
const groups = computed(() => replayGroups(props.rows, true));
const colors = ["#2f7a5f", "#b95322", "#3a6696"];
const charts = computed(() => groups.value.flatMap(group => [
  { name: "土壤原码", unit: "ADC 码", fields: ["top_raw", "middle_raw"], labels: ["AIN0 / TOP", "AIN1 / MIDDLE"], read: (r: RawReplayPayload, f: string) => r.soil[f] },
  ...[0, 1].map(i => ({ name: i === 0 ? "TOP 加速度" : "TOE 加速度", unit: "m/s²", fields: ["ax", "ay", "az"], labels: ["ax", "ay", "az"], read: (r: RawReplayPayload, f: string) => r.imu[i]?.[f as "ax" | "ay" | "az"] ?? null })),
].map(chart => {
  const values = group.samples.flatMap(r => chart.fields.map(f => chart.read(r, f))).filter((v): v is number => v != null && Number.isFinite(v));
  const min = values.length ? Math.min(...values) : 0, max = values.length ? Math.max(...values) : 1;
  const paths = chart.fields.map((field, fi) => ({ key: field, d: rawPath(group.samples, r => chart.read(r, field), min, max), color: colors[fi] }));
  return { ...chart, min, max, paths, boot: group.boot, first: (group.samples[0]?.uptime_ms || 0)/1000, last: (group.samples.at(-1)?.uptime_ms || 0)/1000, hasValues: values.length > 0 };
})));
</script>
<template>
  <section class="panel platform-section raw-replay-panel" data-testid="raw-replay-trend">
    <div class="platform-panel-heading"><div><div><h2>原始通道</h2><p>未标定 · 无插值、平滑或补点 · 设备 uptime（秒）；不同 boot 分开绘制，不跨场连接。AIN2 仅诊断，不参与临时风险。</p></div></div><span class="source-badge real">REAL · 原始序列</span></div>
    <div class="raw-replay-body">
      <p v-if="!charts.length" class="raw-empty">尚无原始通道回放样本</p>
      <div v-else class="raw-replay-grid"><figure v-for="chart in charts" :key="`${chart.boot}-${chart.name}`" class="raw-chart-card">
        <figcaption><strong>{{ chart.name }}（{{ chart.unit }}）</strong><span class="raw-legend"><span v-for="(label, i) in chart.labels" :key="label" :style="{ color: colors[i] }">{{ label }}</span></span></figcaption>
        <p class="raw-meta">boot {{ chart.boot }} · {{ chart.first.toFixed(3) }}–{{ chart.last.toFixed(3) }} 秒</p>
        <div class="raw-bound">{{ chart.max.toPrecision(5) }}</div>
        <svg viewBox="0 0 320 100" role="img" :aria-label="`${chart.name}；null 处断线`"><path d="M0 10H320 M0 50H320 M0 90H320" stroke="#e4e8e4" stroke-dasharray="3 4" fill="none" /><path v-for="path in chart.paths" :key="path.key" :d="path.d" :stroke="path.color" fill="none" stroke-width="1.6" vector-effect="non-scaling-stroke" /></svg>
        <div class="raw-bound">{{ chart.min.toPrecision(5) }}</div>
        <p v-if="!chart.hasValues" class="raw-empty">暂无有效原始样本</p>
      </figure></div>
    </div>
  </section>
</template>
<style scoped>
.raw-replay-body { padding: 14px 16px; }
.raw-replay-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.raw-chart-card { margin: 0; padding: 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-control); background: var(--surface-subtle); }
figcaption { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; font-size: 13px; color: var(--text-primary); }
.raw-legend { display: inline-flex; gap: 8px; font-size: 11px; font-weight: 600; }
.raw-meta { color: var(--text-muted); font-size: 11px; margin: 4px 0 8px; font-variant-numeric: tabular-nums; }
.raw-bound { font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
svg { width: 100%; height: 132px; background: var(--surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-badge); display: block; margin: 2px 0; }
.raw-empty { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
</style>
