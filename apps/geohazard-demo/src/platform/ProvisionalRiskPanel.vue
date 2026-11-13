<script setup lang="ts">
import { computed } from "vue";
import PlatformTrend from "./PlatformTrend.vue";
import { dateTime, reading, type ProvisionalRisk, type HistoryPoint } from "./types";
const props = defineProps<{ latest: ProvisionalRisk | null; history: ProvisionalRisk[]; stale: boolean; replay: boolean }>();
const labels = { NORMAL: "NORMAL · 未触发演示阈值", ATTENTION: "ATTENTION · 关注", WARNING: "WARNING · 警示" };
const color = computed(() => props.latest?.level === "WARNING" ? "#bd514c" : props.latest?.level === "ATTENTION" ? "#b48b30" : "#39866a");
const points = computed<HistoryPoint[]>(() => props.history.map(r => ({ time: r.received_at, score: r.score, moisture: null, tilt: null, vibration: null, rain: null, crack: null })));
</script>
<template>
  <section class="panel platform-section provisional-panel" data-testid="provisional-risk">
    <div class="platform-panel-heading"><div><div><h2>临时风险（未标定，非正式告警）</h2><p>PROVISIONAL · 不参与正式风险融合 · NORMAL 不代表边坡安全</p></div></div><span class="source-badge">{{ replay ? '真实回放 / TEST_ONLY' : latest ? `${latest.source} / ${latest.scope}` : '等待数据' }}</span></div>
    <template v-if="latest">
      <strong :style="{ color }">{{ latest.level ? labels[latest.level] : '数据不足，暂不分级' }}</strong>
      <p>{{ stale ? '历史结果 / 数据已过期' : replay ? '回放采样结果' : '最新采样结果' }} · {{ dateTime(latest.received_at) }} · boot {{ latest.boot_id }}</p>
      <ul v-if="latest.reasons.length"><li v-for="reason in latest.reasons" :key="reason.feature">{{ reason.feature }} = {{ reading(reason.value, 4) }} → {{ reason.level }}</li></ul>
      <p v-else>当前有效特征未触发演示阈值；缺失通道和预热状态见下方质量标记。</p>
      <div class="feature-grid"><div>相对湿度指数（0–1，非含水率）<p>AIN0 / TOP {{ reading(latest.features.soil_index.top, 3) }} · AIN1 / MIDDLE {{ reading(latest.features.soil_index.middle, 3) }} · AIN2 排除</p></div>
        <div v-for="(metrics, sensor) in latest.features.imu" :key="sensor">IMU {{ sensor }}<p>倾角 {{ reading(metrics.tilt_deg, 2) }}° · 相对初始方向 {{ reading(metrics.direction_angle_deg, 2) }}°</p><p>振动 RMS {{ reading(metrics.vibration_rms_mps2, 4) }} m/s² · 陀螺 RMS {{ reading(metrics.gyro_rms_dps, 3) }} °/s</p></div></div>
      <details><summary>质量标记 / 预热状态</summary><p>{{ latest.quality_flags.join(' · ') }}</p></details>
    </template>
    <p v-else>所选最新遥测暂无临时风险结果；设备上报正式风险时保留其原值。</p>
    <div class="trend-header"><span>临时风险历史 · 序数分级 0 / 50 / 100，非概率</span><span>{{ history.length }} 条</span></div>
    <PlatformTrend :points="points" :color="color" empty-label="等待临时风险有效特征" chart-label="未标定临时分级历史；0/50/100 为序数，缺测处断线，非正式告警" />
    <p>1 Hz 采样不能还原高频振动；前 10 个有效 IMU 样本建立初始方向。候选 AIR/WATER 端点尚未冻结，未应用 IMU 标定修正。</p>
  </section>
</template>
<style scoped>
.provisional-panel { margin: 20px 0; }
.provisional-panel p, .provisional-panel li, .provisional-panel details { font-size: 12px; color: #68756e; overflow-wrap: anywhere; }
.feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin: 16px 0; font-size: 13px; }
</style>
