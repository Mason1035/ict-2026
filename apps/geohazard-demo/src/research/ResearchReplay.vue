<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { connectionSettings, errorMessage, saveConnection } from "../platform/api";
import { researchGet } from "./api";
import type { Boundary, Detail, Period, Rules, Session } from "./api";
import ResearchCurve from "./ResearchCurve.vue";
defineEmits<{ back: [] }>();
const sessions = ref<Session[]>([]), selected = ref("");
const detail = ref<Detail | null>(null), rules = ref<Rules | null>(null);
const loading = ref(false), listing = ref(false), error = ref("");
const showConnection = ref(false), base = ref(connectionSettings.base), token = ref(connectionSettings.token);
let listRequest: AbortController | undefined, detailRequest: AbortController | undefined;
const sensorNames: Record<string, string> = { imu_top: "TOP IMU", imu_toe: "TOE IMU", soil_top: "AIN0 · TOP", soil_middle: "AIN1 · MIDDLE", soil_toe: "AIN2 · TOE" };
const metricNames: Record<string, string> = { direction_angle_deg: "相对方向角（倾角变化）", vibration_rms_mps2: "动态振动 RMS", sta_lta: "振动 STA/LTA", raw_adc_code: "原始 ADC 码", relative_change_fraction: "原始 ADC 码相对变化" };
const qualityNames: Record<string, string> = { UNCALIBRATED: "未标定", AIN2_JITTER_REVIEW: "AIN2 抖动待复查", POST_RAIN_NOT_DRY_BASELINE: "雨后静置，非干土基线", FIRMWARE_IDENTITY_DECLARED_ONLY: "固件哈希仅为声明，未独立验收", SENSOR_ERRORS_PRESENT: "存在传感器错误" };
const stateNames: Record<string, string> = { TRIGGERED: "出现研究触发", NO_TRIGGER: "无研究触发（不代表安全）", WARMUP: "窗口预热", INVALID: "质量无效", INSUFFICIENT_BASELINE: "基线不足" };
const periods = computed(() => [...(rules.value?.events || []), ...(rules.value?.candidates || [])].sort((a, b) => a.confirmed_at_us - b.confirmed_at_us));
function channelPeriods(sensor: string, metric: string): Period[] {
  return periods.value.filter((p) => p.sensor_id === sensor && (metric.startsWith("vibration") || metric === "sta_lta" ? p.candidate_only : !p.candidate_only));
}
const seconds = (us: number) => (us / 1e6).toFixed(3);
function decode(codes: string[]) { return codes.map((code) => rules.value?.reason_decode.find((r) => r.code === code)?.label || code).join("、"); }
async function loadSessions() {
  listRequest?.abort(); detailRequest?.abort();
  const request = listRequest = new AbortController();
  sessions.value = []; selected.value = ""; detail.value = null; rules.value = null; error.value = ""; listing.value = true;
  try {
    const data = await researchGet<Boundary & { items: Session[] }>("/sessions", request.signal);
    if (request.signal.aborted) return;
    sessions.value = data.items;
    selected.value = data.items[0]?.experiment_id || "";
  } catch (cause) { if (!request.signal.aborted) error.value = errorMessage(cause); }
  finally { if (listRequest === request) listing.value = false; }
}
async function loadDetail(id: string) {
  detailRequest?.abort(); detail.value = null; rules.value = null; loading.value = false;
  if (!id) return;
  const request = detailRequest = new AbortController();
  error.value = ""; loading.value = true;
  try {
    const path = `/sessions/${encodeURIComponent(id)}`;
    const [data, result] = await Promise.all([researchGet<Detail>(`${path}?max_points=600`, request.signal), researchGet<Rules>(`${path}/rules`, request.signal)]);
    if (request.signal.aborted || selected.value !== id) return;
    if (data.session.experiment_id !== id || result.experiment_id !== id || data.provenance.config_sha256 !== result.config_sha256) throw new Error("会话或冻结配置来源不一致，已拒绝展示");
    detail.value = data; rules.value = result;
  } catch (cause) { if (!request.signal.aborted) { error.value = errorMessage(cause); request.abort(); } }
  finally { if (detailRequest === request) loading.value = false; }
}
function applyConnection() {
  try { saveConnection(base.value, token.value); showConnection.value = false; }
  catch (cause) { error.value = errorMessage(cause); }
}
watch(selected, (id) => { void loadDetail(id); });
watch(() => connectionSettings.revision, () => { void loadSessions(); });
onMounted(() => { void loadSessions(); });
onBeforeUnmount(() => { listRequest?.abort(); detailRequest?.abort(); });
</script>
<template>
  <div class="research-page">
    <header class="research-header"><div><span class="eyebrow">智哨防灾 / 阶段 I</span><h1>研究回放</h1></div><nav aria-label="研究导航"><button @click="$emit('back')">返回生产监控</button><button @click="showConnection = !showConnection">后端连接</button><button :disabled="listing" @click="loadSessions">重新读取</button></nav></header>
    <div class="research-banner" role="note"><strong>研究结果 · 未标定 · 非生产预警</strong><p>只读消费已登记的 SD 研究会话。结果不进入生产告警、当前态或风险融合；无触发不代表边坡安全。</p></div>
    <form v-if="showConnection" class="research-card connection" @submit.prevent="applyConnection"><label>后端 API 地址<input v-model="base" placeholder="/api/v1" /></label><label>API Token<input v-model="token" type="password" autocomplete="off" /></label><button type="submit">应用连接</button></form>
    <p v-if="error" class="research-error" role="alert">{{ error }}</p>
    <p v-if="listing" role="status">正在读取研究登记库…</p><p v-else-if="!sessions.length && !error" class="research-card">尚无已登记研究会话。请先离线通过 WP2 CLI 登记原件。</p>
    <div v-if="sessions.length" class="research-layout">
      <aside class="research-card session-list"><h2>研究会话</h2><button v-for="session in sessions" :key="session.experiment_id" :class="{ selected: selected === session.experiment_id }" :aria-pressed="selected === session.experiment_id" @click="selected = session.experiment_id"><strong>{{ session.label }} · {{ session.type_label }}</strong><span>{{ session.duration_s.toFixed(2) }} s · RESEARCH</span><small>{{ session.experiment_id }}</small><span v-for="flag in session.quality_flags" :key="flag" class="quality">{{ qualityNames[flag] || flag }}</span><span v-for="(count, sensor) in session.channels" :key="sensor">{{ sensorNames[sensor] || sensor }}：{{ count.valid_count }} 有效 / {{ count.invalid_count }} 无效</span></button></aside>
      <main>
        <p v-if="loading" role="status">正在校验原件并计算冻结配置结果…</p>
        <template v-if="detail && rules">
          <section class="research-card"><h2>{{ detail.session.label }} · {{ detail.session.type_label }}</h2><p class="mono">{{ detail.session.experiment_id }}</p><p>场内时间相对 END.start_us，单位秒；时长为采集跨度，不代表连续覆盖率。</p><details><summary>固件与回放身份</summary><p class="mono">固件 SHA-256：{{ detail.session.firmware_sha256 }}</p><p>{{ detail.session.firmware_identity_status }}</p><p class="mono">回放：{{ detail.session.replay_id }}</p></details></section>
          <section class="research-card provenance"><h2>冻结配置来源</h2><dl><dt>方法版本</dt><dd>{{ rules.provenance.method_version }}（PROVISIONAL v1）</dd><dt>来源会话</dt><dd class="mono">{{ rules.provenance.source.experiment_id }}</dd><dt>来源性质</dt><dd>R4 · 雨后静置，非干土基线；同源零触发自检不作为独立误报率验证</dd><dt>generated_at</dt><dd>{{ rules.provenance.generated_at }}</dd><dt>config_sha256</dt><dd class="mono">{{ rules.provenance.config_sha256 }}</dd><dt>规则 / 参考版本</dt><dd>{{ rules.provenance.rule_version }} / {{ rules.provenance.reference_version }}</dd></dl><details><summary>来源三件套 SHA-256</summary><p v-for="(hash, file) in rules.provenance.source.file_sha256" :key="file" class="mono">{{ file }}：{{ hash }}</p></details></section>
          <section class="research-card"><h2>研究触发 {{ rules.trigger_count }} 段 · 振动候选 {{ rules.candidate_count }} 段</h2><p><span class="legend trigger-key" />红色：研究触发；<span class="legend candidate-key" />琥珀色：振动候选，永不计作触发。浅色为确认前持续越限，深色从确认时刻开始。</p><p class="quality">AIN2 质量提示：存在抖动复查要求；执行器仅在处理副本做后向 5 点中位滤波和相邻差防护，原始 ADC 码保留。</p><p>土壤仅显示原始 ADC 码/相对变化（fraction）；变化正负不解释为变湿或变干。曲线在完整规则计算后做极值降采样，缺测处断线。</p></section>
          <section v-for="(channel, sensor) in detail.channels" :key="sensor" class="research-card"><h2>{{ sensorNames[sensor] || sensor }}</h2><p>{{ stateNames[channel.rule_summary.state] || channel.rule_summary.state }} · {{ channel.statistics.usable_count }} / {{ channel.statistics.count }} 可用 · 缺值 {{ channel.statistics.missing_value_count }} · 观测跨度 {{ channel.statistics.duration_s?.toFixed(3) ?? '—' }} s · 相邻间隔中位数 {{ channel.statistics.median_interval_us ?? '—' }} µs</p><p v-for="flag in channel.statistics.quality_flags" :key="flag" class="quality">{{ qualityNames[flag] || flag }}</p><details v-if="Object.keys(channel.rule_summary.diagnostic_counts).length"><summary>质量诊断计数</summary><p v-for="(count, flag) in channel.rule_summary.diagnostic_counts" :key="flag">{{ flag }}：{{ count }}</p></details><ResearchCurve v-for="curve in channel.curves" :key="curve.metric" :curve="curve" :title="metricNames[curve.metric] || curve.metric" :duration="detail.session.duration_s" :periods="channelPeriods(String(sensor), curve.metric)" /></section>
          <section class="research-card"><h2>时段与通道贡献</h2><p v-if="!periods.length">本场无研究触发或振动候选；不据此判定安全。</p><div v-for="(period, index) in periods" :key="index" class="period"><strong>{{ period.candidate_only ? '振动候选' : '研究触发' }} · {{ sensorNames[period.sensor_id] }}</strong><p>起始 {{ seconds(period.start_us) }} s → 确认 {{ seconds(period.confirmed_at_us) }} s → 最后支持 {{ seconds(period.end_us) }} s · 关闭 {{ period.closure }}</p><p>{{ decode(period.reason_codes) }} · 临时 mask {{ period.reason_mask }} · {{ period.reason_codes.join(', ') }}</p><p v-for="(contribution, ci) in period.contributions" :key="ci" class="mono">{{ sensorNames[contribution.sensor_id] }} · 峰值 {{ JSON.stringify(contribution.peak_values) }} · 冻结值 {{ JSON.stringify(contribution.thresholds) }}</p></div><p v-for="(overlap, index) in rules.coincidences" :key="index">同时变化：{{ seconds(overlap.start_us) }}–{{ seconds(overlap.end_us) }} s · {{ overlap.channels.map((sensor) => sensorNames[sensor] || sensor).join(' / ') }}。只描述重合，不推断因果。</p><details><summary>临时原因码解码 · {{ rules.provenance.reason_definition_version }}</summary><p v-for="reason in rules.reason_decode" :key="reason.code">{{ reason.mask }} · {{ reason.code }} · {{ reason.label }}</p></details></section>
        </template>
      </main>
    </div>
  </div>
</template>
<style scoped>
.research-page { min-height: 100vh; background: #f4f7f5; color: #203e3b; padding: 30px max(20px, calc((100vw - 1480px) / 2)); font-size: 14px; line-height: 1.6; } .research-header, nav { display: flex; align-items: center; justify-content: space-between; gap: 12px; } h1 { font-size: 30px; margin: 3px 0 18px; } h2 { font-size: 18px; margin: 0 0 10px; } p { margin: 8px 0; } .eyebrow { color: #617b75; font-size: 12px; letter-spacing: .08em; } button { cursor: pointer; border: 1px solid #c4d3ce; border-radius: 8px; background: #fff; padding: 8px 14px; text-align: left; } button:hover, button.selected { border-color: #277d76; background: #e6f2ed; } button:focus-visible, input:focus-visible { outline: 3px solid #277d76; outline-offset: 2px; } button:disabled { opacity: .5; } .research-banner { background: #fff2d7; border: 1px solid #d9b36b; border-left: 5px solid #aa7623; border-radius: 10px; padding: 18px 22px; margin-bottom: 24px; } .research-banner strong { font-size: 20px; color: #785018; } .research-banner p { color: #795f38; } .research-layout { display: grid; grid-template-columns: 310px minmax(0, 1fr); align-items: start; gap: 24px; } .research-card { background: #fff; border: 1px solid #dce6e0; border-radius: 12px; padding: 22px; margin-bottom: 20px; min-width: 0; } .session-list { position: sticky; top: 20px; max-height: calc(100vh - 40px); overflow: auto; } .session-list button { width: 100%; margin-top: 12px; padding: 14px; display: grid; gap: 5px; } .session-list span { font-size: 12px; } small, .mono { overflow-wrap: anywhere; font-family: ui-monospace, monospace; font-size: 12px; } .quality { color: #8c6323; font-size: 12px; } .research-error { border: 1px solid #be675a; background: #fff0ed; padding: 16px; border-radius: 8px; } dl { display: grid; grid-template-columns: 135px minmax(0, 1fr); gap: 10px; } dt { color: #678078; } dd { margin: 0; } details { margin-top: 12px; } summary { cursor: pointer; color: #277d76; } .legend { display: inline-block; width: 12px; height: 9px; margin-right: 4px; } .trigger-key { background: #b65348; } .candidate-key { background: #c18b24; } .period { border-top: 1px solid #e2e9e5; padding: 14px 0; } .connection { display: flex; flex-wrap: wrap; gap: 14px; align-items: end; } label { display: grid; gap: 4px; flex: 1; } input { border: 1px solid #c4d3ce; border-radius: 6px; padding: 8px; width: 100%; } @media (max-width: 950px) { .research-layout { grid-template-columns: 1fr; } .session-list { position: static; max-height: none; } .research-header { align-items: start; flex-wrap: wrap; } nav { flex-wrap: wrap; margin-bottom: 18px; } dl { grid-template-columns: 1fr; gap: 4px; } dd { margin-bottom: 8px; } }
</style>
