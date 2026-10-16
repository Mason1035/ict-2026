<script setup lang="ts">
import { computed, ref } from "vue";
const props = defineProps<{
  points: { time: number; score: number }[];
  color: string;
}>();
const hover = ref<number | null>(null);
const W = 320,
  H = 100,
  padding = 6;
const data = computed(() => props.points.slice(-60));
const xy = computed(() =>
  data.value.map((p, i) => ({
    x: padding + (i * (W - 2 * padding)) / Math.max(1, data.value.length - 1),
    y: H - padding - (p.score * (H - 2 * padding)) / 100,
    ...p,
  })),
);
const line = computed(() =>
  xy.value
    .map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(" "),
);
const area = computed(() =>
  xy.value.length
    ? `${line.value} L${xy.value.at(-1)!.x},${H} L${xy.value[0].x},${H} Z`
    : "",
);
const current = computed(() =>
  hover.value === null
    ? null
    : xy.value[Math.min(hover.value, xy.value.length - 1)],
);
function track(e: MouseEvent) {
  const r = (e.currentTarget as SVGElement).getBoundingClientRect();
  hover.value = Math.round(
    Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) *
      (xy.value.length - 1),
  );
}
const stamp = (t: number) =>
  `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
</script>
<template>
  <div class="risk-chart" aria-label="实时积累的风险历史曲线">
    <div class="chart-axis"><span>100</span><span>50</span><span>0</span></div>
    <svg
      :viewBox="`0 0 ${W} ${H}`"
      preserveAspectRatio="none"
      @mousemove="track"
      @mouseleave="hover = null"
      role="img"
      aria-label="风险趋势"
    >
      <defs>
        <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="color" stop-opacity=".15" />
          <stop offset="100%" :stop-color="color" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path
        d="M0 6H320 M0 50H320 M0 94H320"
        stroke="#e9ede8"
        stroke-width="1"
        stroke-dasharray="3 4"
        fill="none"
      />
      <path :d="area" fill="url(#riskFill)" />
      <path
        :d="line"
        :stroke="color"
        stroke-width="2"
        fill="none"
        vector-effect="non-scaling-stroke"
        stroke-linejoin="round"
      />
      <circle
        v-if="xy.length"
        :cx="xy.at(-1)!.x"
        :cy="xy.at(-1)!.y"
        r="3"
        :fill="color"
      />
      <template v-if="current">
        <path
          :d="`M${current.x} 0 V100`"
          stroke="#95a097"
          stroke-dasharray="3 3"
        />
        <circle
          :cx="current.x"
          :cy="current.y"
          r="4"
          :fill="color"
          stroke="white"
          stroke-width="2"
        />
      </template>
    </svg>
    <div v-if="current" class="chart-tooltip">
      T+{{ stamp(current.time) }}
      <strong>{{ current.score.toFixed(1) }}</strong>
    </div>
    <div v-if="!data.length" class="chart-empty">等待下一次采样</div>
    <div class="chart-time">
      <span>{{ data.length ? "T+" + stamp(data[0].time) : "00:00" }}</span
      ><span>仿真时间</span
      ><span>{{
        data.length ? "T+" + stamp(data.at(-1)!.time) : "00:00"
      }}</span>
    </div>
  </div>
</template>
