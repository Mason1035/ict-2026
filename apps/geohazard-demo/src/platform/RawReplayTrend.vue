<script setup lang="ts">
import { computed } from "vue";
import type { TelemetryRow } from "./types";
const props = defineProps<{ rows: TelemetryRow[] }>();
import { replayGroups, rawPath, type RawReplayPayload } from "./rawReplay";
const groups = computed(() => replayGroups(props.rows));
const colors = ["#39866a", "#ce7548", "#537db5"];
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
    <h2>原始通道</h2><p>未标定 · 无插值、平滑或补点 · 设备 uptime（秒）；不同 boot 分开绘制，不跨场连接。AIN2 默认不发布。</p>
    <div class="raw-replay-grid"><figure v-for="chart in charts" :key="`${chart.boot}-${chart.name}`">
      <figcaption>{{ chart.name }}（{{ chart.unit }}） <span v-for="(label, i) in chart.labels" :key="label" :style="{ color: colors[i] }">{{ label }} </span></figcaption>
      <p>boot {{ chart.boot }} · {{ chart.first.toFixed(3) }}–{{ chart.last.toFixed(3) }} 秒</p><div>{{ chart.max.toPrecision(5) }}</div>
      <svg viewBox="0 0 320 100" role="img" :aria-label="`${chart.name}；null 处断线`"><path v-for="path in chart.paths" :key="path.key" :d="path.d" :stroke="path.color" fill="none" stroke-width="1.5" vector-effect="non-scaling-stroke" /></svg>
      <div>{{ chart.min.toPrecision(5) }}</div><p v-if="!chart.hasValues">暂无有效原始样本</p>
    </figure></div>

  </section>
</template>
<style scoped>
.raw-replay-panel { margin: 20px 0; }
.raw-replay-panel p { color: #68756e; font-size: 12px; }
.raw-replay-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
figure { margin: 12px 0; } figcaption { font-size: 13px; } svg { width: 100%; height: 150px; background: #f6f8f5; } figure > div { font-size: 11px; color: #68756e; }
</style>
