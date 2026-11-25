<script setup lang="ts">
import { computed } from "vue";
import PlatformTrend from "./PlatformTrend.vue";
import { dateTime, levelColors, reading, type ProvisionalRisk, type HistoryPoint } from "./types";
const props = defineProps<{ latest: ProvisionalRisk | null; history: ProvisionalRisk[]; stale: boolean; replay: boolean }>();
const labels = { NORMAL: "NORMAL · 未触发演示阈值", ATTENTION: "ATTENTION · 关注", WARNING: "WARNING · 警示" };
const color = computed(() => props.latest?.level === "WARNING" ? levelColors.critical : props.latest?.level === "ATTENTION" ? levelColors.moderate : levelColors.low);
const points = computed<HistoryPoint[]>(() => props.history.map(r => ({ time: r.received_at, score: r.score, moisture: null, tilt: null, vibration: null, rain: null, crack: null })));
const soilChannels = [{ key: "top", label: "AIN0", color: "#2b7882" }, { key: "middle", label: "AIN1", color: "#91813c" }, { key: "toe", label: "AIN2", color: "#775c91" }];
function soilPoints(key: string): HistoryPoint[] {
  return props.history.map((r, i) => ({ time: r.received_at,
    score: i > 0 && (r.boot_id !== props.history[i-1]?.boot_id || r.soil_calibration?.version !== props.history[i-1]?.soil_calibration?.version) ? null : r.features.soil_w_rel_pct?.[key] ?? null,
    moisture: null, tilt: null, vibration: null, rain: null, crack: null }));
}
</script>
<template>
  <section class="panel platform-section provisional-panel" data-testid="provisional-risk">
    <div class="platform-panel-heading"><div><div><h2>临时风险（未标定，非正式告警）</h2><p>PROVISIONAL · 不参与正式风险融合 · NORMAL 不代表边坡安全</p></div></div><span :class="['source-badge', replay ? 'test-only' : latest?.source?.toLowerCase()]">{{ replay ? '真实回放 / TEST_ONLY' : latest ? `${latest.source} / ${latest.scope}` : '等待数据' }}</span></div>
    <div class="provisional-body">
      <template v-if="latest">
        <div class="provisional-status-row">
          <strong :style="{ color }">{{ latest.level ? labels[latest.level] : '数据不足，暂不分级' }}</strong>
          <span>{{ stale ? '历史结果 / 数据已过期' : replay ? '回放采样结果' : '最新采样结果' }} · {{ dateTime(latest.received_at) }} · boot {{ latest.boot_id }}</span>
        </div>
        <ul v-if="latest.reasons.length" class="provisional-reasons"><li v-for="reason in latest.reasons" :key="reason.feature">{{ reason.feature }} = {{ reading(reason.value, 4) }} → {{ reason.level }}</li></ul>
        <p v-else>未触发 IMU 演示阈值或数据不足；土壤相对指标仅展示，不参与本次分级。</p>
        <div class="feature-grid">
          <div class="feature-item"><strong>Air–Water 相对湿度（0–100%，非体积含水率）</strong><p data-testid="air-water-values">AIN0 {{ reading(latest.features.soil_w_rel_pct?.top ?? null, 2) }}% · AIN1 {{ reading(latest.features.soil_w_rel_pct?.middle ?? null, 2) }}% · AIN2 {{ reading(latest.features.soil_w_rel_pct?.toe ?? null, 2) }}%</p></div>
          <div v-for="(metrics, sensor) in latest.features.imu" :key="sensor" class="feature-item"><strong>IMU {{ sensor }}</strong><p>倾角 {{ reading(metrics.tilt_deg, 2) }}° · 相对初始方向 {{ reading(metrics.direction_angle_deg, 2) }}°</p><p>振动 RMS {{ reading(metrics.vibration_rms_mps2, 4) }} m/s² · 陀螺 RMS {{ reading(metrics.gyro_rms_dps, 3) }} °/s</p></div>
        </div>
        <p v-if="latest.soil_calibration">相对标定版本 {{ latest.soil_calibration.version }} · {{ latest.soil_calibration.applicable ? "参数匹配（操作者声明，非设备认证），实板及会话尚未验收" : "固件声明缺失、不适用或会话冲突，保持空值" }}</p>
        <p v-else>历史旧版本结果，未按新端点重算。</p>
        <details><summary>质量标记 / 预热状态</summary><p>{{ latest.quality_flags.join(' · ') }}</p></details>
      </template>
      <p v-else>所选最新遥测暂无临时风险结果；设备上报正式风险时保留其原值。</p>
      <div class="feature-grid" data-testid="air-water-trends"><div v-for="channel in soilChannels" :key="channel.key" class="feature-item"><p>{{ channel.label }} 相对湿度历史（%）</p><PlatformTrend :points="soilPoints(channel.key)" :color="channel.color" empty-label="缺少可适用的相对标定数据" :chart-label="`${channel.label} Air–Water 相对湿度百分比，非体积含水率；缺测、会话和标定版本变化处断线`" /></div></div>
      <div class="trend-header"><span>临时风险历史 · 序数分级 0 / 50 / 100，非概率</span><span>{{ history.length }} 条</span></div>
      <PlatformTrend :points="points" :color="color" empty-label="等待临时风险有效特征" chart-label="未标定临时分级历史；0/50/100 为序数，缺测处断线，非正式告警" />
      <p class="provisional-footnote">1 Hz 采样不能还原高频振动；前 10 个有效 IMU 样本建立初始方向。三路 Air–Water 相对百分比与旧 120 s ΔVWC 分属不同指标。湿度风险阈值未启用，IMU 标定修正未应用。</p>
    </div>
  </section>
</template>
<style scoped>
.provisional-body { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.provisional-status-row { display: flex; align-items: baseline; justify-content: space-between; gap: 8px 16px; flex-wrap: wrap; }
.provisional-status-row strong { font-size: 15px; font-weight: 600; }
.provisional-body :is(p, li, details, .provisional-status-row span) { font-size: 12px; color: var(--text-secondary); line-height: 1.5; overflow-wrap: anywhere; }
.provisional-reasons { margin: 0; padding-left: 18px; }
.feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 10px; }
.feature-item { min-width: 0; padding: 10px 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-control); background: var(--surface-subtle); font-variant-numeric: tabular-nums; }
.feature-item > strong { display: block; font-size: 12px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.provisional-body summary { cursor: pointer; font-weight: 500; color: var(--text-primary); }
.provisional-body .provisional-footnote { padding-top: 8px; border-top: 1px solid var(--border-subtle); }
</style>
