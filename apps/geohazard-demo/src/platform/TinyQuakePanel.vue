<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Activity, Radio, TriangleAlert, RefreshCw } from "lucide-vue-next";
import { api, connectionSettings, errorMessage, isAborted } from "./api";
import { dateTime, reading, type Items } from "./types";
interface Result {
  id: string; site_id: string; device_id: string; sensor_id: string; source: string;
  received_at: string; stale: boolean; age_seconds: number; prediction: string | null;
  payload: { input_source: string; probabilities: number[] | null; inference_us: number;
    model_sha256: string; quality_valid: boolean; quality_reason: string; reference_index: number | null;
    frame_id: string | null; calibration_version: string | null; preprocessing_id: string; seq: number; boot_id: number };
}
const props = defineProps<{ connected: boolean; revision: string | null }>();
const streams = ref<Result[]>([]), rows = ref<Result[]>([]);
const selected = ref(""), error = ref(""), cursor = ref<string | null>(null), loading = ref(false);
const latest = computed(() => rows.value[0]);
const age = computed(() => { void props.revision; return latest.value ? Math.max(latest.value.age_seconds,(Date.now()-Date.parse(latest.value.received_at))/1000) : Infinity; });
const fresh = computed(() => props.connected && latest.value && !latest.value.stale && age.value <= 30);
const labels = ["P 波", "S 波", "噪声"];
const classes: Record<string,string> = { "P-wave": "P 波", "S-wave": "S 波", Noise: "噪声" };
const streamKey = (item: Result) => JSON.stringify([item.site_id,item.device_id,item.sensor_id,item.source]);
let expanded = false;
let generation = 0, controller: AbortController | undefined;
function cancel() { generation++; controller?.abort(); loading.value = false; }
function query() { const [site_id,device_id,sensor_id,source] = JSON.parse(selected.value); return new URLSearchParams({site_id,device_id,sensor_id,source}); }
async function load(more = false) {
  if (!props.connected || (more && (!cursor.value || loading.value))) return;
  cancel(); const request = generation; controller = new AbortController(); const signal = controller.signal;
  loading.value = true; error.value = "";
  try {
    if (!more) {
      const data = await api.get<Items<Result>>("/tinyquake/streams", signal);
      if (request !== generation) return;
      streams.value = data.items;
      if (!data.items.some(item => streamKey(item) === selected.value)) selected.value = data.items[0] ? streamKey(data.items[0]) : "";
    }
    if (!selected.value) { rows.value = []; cursor.value = null; return; }
    const params = query(); if (more && cursor.value) params.set("cursor",cursor.value);
    const data = await api.get<Items<Result>>(`/tinyquake/results?${params}`,signal);
    if (request !== generation) return;
    const ids = new Set(rows.value.map(row => row.id));
    if (more) {
      rows.value = [...rows.value,...data.items.filter(row => !ids.has(row.id))];
      cursor.value = data.next_cursor || null; expanded = true;
    } else if (expanded) {
      const freshIds = new Set(data.items.map(row => row.id));
      rows.value = [...data.items,...rows.value.filter(row => !freshIds.has(row.id))];
    } else { rows.value = data.items; cursor.value = data.next_cursor || null; }
  } catch (cause) {
    if (request !== generation || isAborted(cause)) return;
    error.value = errorMessage(cause); if (!more) { rows.value=[]; cursor.value=null; }
  } finally { if (request === generation) loading.value = false; }
}
function choose() { cancel(); expanded=false; rows.value=[]; cursor.value=null; void load(); }
// Each successful parent poll supplies a new revision. Never show stale scores
// while disconnected; backend settings and request generations remain isolated.
watch(() => [props.connected,props.revision,connectionSettings.base,connectionSettings.token], () => {
  if (!props.connected) { cancel(); expanded=false; cursor.value=null; rows.value=[]; return; }
  void load();
}, {immediate:true});
onBeforeUnmount(cancel);
</script>
<template>
  <section class="panel platform-section tinyquake-panel">
    <div class="platform-panel-heading"><div><Activity :size="20" /><div><h2>TinyQuake · 波形分类实验</h2><p>独立 CNN17 通道，按站点、板卡、传感器和来源保存。</p></div></div><button class="secondary-button" :disabled="!connected || loading" @click="load()"><RefreshCw :size="14" />刷新结果</button></div>
    <div class="tq-body">
    <div class="backend-alert neutral"><TriangleAlert :size="20" /><div><strong>实验结果不参与正式风险评分</strong><p>分类为 P 波 / S 波 / 噪声，不表示地震预测。参考波形用于验证板端推理，不能当作现场采集。</p></div></div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <label class="tq-selector">模型数据流<select v-model="selected" aria-label="选择 TinyQuake 数据流" :disabled="!connected || !streams.length" @change="choose"><option v-if="!streams.length" value="">等待 ESP32 上报</option><option v-for="stream in streams" :key="streamKey(stream)" :value="streamKey(stream)">{{ stream.site_id }} / {{ stream.device_id }} / {{ stream.sensor_id }} / {{ stream.source }}</option></select></label>
    <div v-if="!connected" class="platform-empty"><Radio :size="28" /><h3>后端数据不可用</h3><p>恢复连接后重新读取已保存的实验结果。</p></div>
    <div v-else-if="!latest" class="platform-empty"><Radio :size="28" /><h3>{{ loading ? '正在读取模型结果' : '尚未收到 TinyQuake 结果' }}</h3><p>在配置与接入中新增 MQTT 连接器，消息格式选择 TinyQuake。参考固件使用 MOCK 来源。</p><code>zhifang/experimental/tinyquake/v1/{站点}/{设备}/{传感器}/result</code></div>
    <template v-else>
      <div class="platform-context"><div><span :class="['source-badge', latest.source.toLowerCase()]">{{ latest.source }}</span><span class="source-badge test-only">TEST_ONLY</span><strong>{{ latest.payload.input_source === 'REFERENCE' ? '参考波形 · 非实采' : '传感器波形 · 尚未现场验证' }}</strong><span :class="{ 'stale-tag': !fresh }">{{ !fresh ? `接收已过期 · ${Math.max(0,Math.floor(age))} 秒` : '最近接收 '+dateTime(latest.received_at) }}</span></div></div>
      <div class="tq-summary"><div><span>窗口分类</span><strong>{{ !fresh ? '数据已过期' : latest.payload.quality_valid ? classes[latest.prediction || ''] || '—' : '窗口不可用' }}</strong><small>{{ latest.payload.input_source === 'REFERENCE' ? `官方 NPZ 参考行号 ${latest.payload.reference_index}` : `坐标 ${latest.payload.frame_id || '待确认'} · 校准 ${latest.payload.calibration_version || '未提供'}` }}</small></div><div><span>设备上报推理耗时</span><strong>{{ fresh ? reading(latest.payload.inference_us/1000,3) : '—' }} <small>ms</small></strong><small>不含采样等待与前处理</small></div></div>
      <div class="tq-probabilities"><article v-for="(label,index) in labels" :key="label"><span>{{ label }}</span><strong>{{ fresh && latest.payload.probabilities ? reading(latest.payload.probabilities[index]! * 100,2)+'%' : '—' }}</strong><progress max="1" :value="fresh ? latest.payload.probabilities?.[index] || 0 : 0" :aria-label="label+'分类分数'" /></article></div>
      <p class="connection-note">40 Hz · 每轴 80 点 · 三分量 · float32。分数为 softmax 输出，未做现场概率校准。新鲜度仅按后端接收时间判断。</p>
      <details><summary>模型与输入信息</summary><p class="tq-hash">模型 SHA-256：<code>{{ latest.payload.model_sha256 }}</code></p><p>预处理：{{ latest.payload.preprocessing_id }} · 质量：{{ latest.payload.quality_reason }} · boot {{ latest.payload.boot_id }} / seq {{ latest.payload.seq }}</p></details>
      <h3 class="tq-history-title">接收历史</h3><div class="platform-table-scroll"><table class="platform-table"><thead><tr><th>接收时间</th><th>输入</th><th>分类</th><th class="num">推理耗时</th><th class="num">序号</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ dateTime(row.received_at) }}</td><td>{{ row.payload.input_source === 'REFERENCE' ? '参考波形' : '传感器波形' }}</td><td>{{ row.payload.quality_valid ? classes[row.prediction || ''] || '—' : '窗口无效' }}</td><td class="num">{{ reading(row.payload.inference_us/1000,3) }} ms</td><td class="num">{{ row.payload.boot_id }} / {{ row.payload.seq }}</td></tr></tbody></table></div><div v-if="cursor" class="history-more"><button class="secondary-button" :disabled="loading" @click="load(true)">加载更早模型结果</button></div>
    </template>
    </div>
  </section>
</template>
<style scoped>
.tq-body { padding: 16px; }
.tq-body .connection-note { padding: 10px 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-control); }
.tq-body .backend-alert { margin: 0 0 14px; }
.tq-body .platform-table-scroll { max-width: 100%; }
.tq-selector { display: grid; gap: 6px; max-width: 560px; margin: 14px 0; font-size: 13px; }
.tq-summary { display: flex; flex-wrap: wrap; gap: 16px 28px; justify-content: space-between; margin: 16px 0; padding: 12px 14px; border: 1px solid var(--border-subtle); border-radius: var(--radius-control); background: var(--surface-subtle); }
.tq-summary > div { display: grid; gap: 4px; }
.tq-summary span, .tq-summary small { font-size: 12px; color: var(--text-secondary); }
.tq-summary strong { font-size: 22px; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.tq-probabilities { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 14px 0; }
.tq-probabilities article { display: grid; gap: 6px; padding: 10px 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-control); background: var(--surface); }
.tq-probabilities span { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.tq-probabilities strong { font-size: 22px; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.tq-probabilities progress { width: 100%; height: 6px; accent-color: var(--accent); }
.tq-hash { overflow-wrap: anywhere; max-width: 100%; }
.tq-history-title { font-size: 15px; font-weight: 600; margin: 18px 0 8px; }
details { font-size: 12px; margin: 14px 0; color: var(--text-secondary); }
summary { cursor: pointer; font-weight: 500; color: var(--text-primary); }
.platform-empty code { overflow-wrap: anywhere; max-width: 100%; font-size: 12px; }
@media (max-width: 600px) {
  .tq-body { padding: 12px; }
  .tq-probabilities { gap: 8px; }
  .tq-probabilities strong { font-size: 18px; }
}
</style>
