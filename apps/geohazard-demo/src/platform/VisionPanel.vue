<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { Camera, Upload, ScanLine, Image as ImageIcon } from "lucide-vue-next";
import { api, connectionSettings, errorMessage, isAborted } from "./api";
import { dateTime, deviceKey, reading, type Device, type Evidence, type Items, type Region, type VisionResult } from "./types";
import AuthMedia from "./AuthMedia.vue";
const props = defineProps<{ device: Device | undefined; connected: boolean; revision: string | null }>();
const emit = defineEmits<{ refresh: [] }>();
const evidence = ref<Evidence[]>([]), results = ref<VisionResult[]>([]);
const currentId = ref(""), referenceId = ref(""), resultId = ref("");
const evidenceCursor = ref<string | null>(null), resultCursor = ref<string | null>(null);
const evidenceTotal = ref(0), resultTotal = ref(0);
const evidenceLoading = ref(false), resultLoading = ref(false), listLoading = ref(false);
const file = ref<File | null>(null), fileInput = ref<HTMLInputElement>();
const camera = ref("CAM-01"), captureTime = ref("");
const error = ref(""), loadError = ref(""), notice = ref("");
const busy = ref(false), roiEnabled = ref(false);
const roi = reactive<Region>({ x: 0, y: 0, width: 320, height: 240 });
let disposed = false, generation = 0, mutationId = 0, loadId = 0;
let listController: AbortController | undefined, mutationController: AbortController | undefined;
let evidenceController: AbortController | undefined, resultController: AbortController | undefined;
let evidenceRequest = 0, resultRequest = 0, evidencePaged = false, resultsPaged = false;
const contextKey = computed(() => `${props.device ? deviceKey(props.device) : ""}|${connectionSettings.revision}`);
const isDemo = computed(() => props.device?.site_id === "DEMO" && props.device.device_id === "DEMO-NODE-01" && props.device.source === "MOCK");
const current = computed(() => evidence.value.find((x) => x.id === currentId.value));
const reference = computed(() => evidence.value.find((x) => x.id === referenceId.value));
const result = computed(() => resultId.value ? results.value.find((x) => x.id === resultId.value) : results.value.find((x) => x.evidence_id === currentId.value));
const comparableEvidence = computed(() => evidence.value.filter((x) => x.id !== currentId.value && (!current.value || (x.camera_id === current.value.camera_id && x.device_id === current.value.device_id && x.site_id === current.value.site_id && x.source === current.value.source && x.scope === current.value.scope && x.width === current.value.width && x.height === current.value.height))));
const effectiveRoi = computed<Region | null>(() => roiEnabled.value ? { ...roi } : current.value ? { x: 0, y: 0, width: current.value.width, height: current.value.height } : null);
const regionKey = (region: Region | null | undefined) => region ? [region.x, region.y, region.width, region.height].join(",") : "";
const resultChanged = computed(() => !!result.value && (result.value.evidence_id !== currentId.value || (result.value.reference_id || "") !== referenceId.value || regionKey(result.value.roi) !== regionKey(effectiveRoi.value)));
const invalidRoi = computed(() => roiEnabled.value && (!current.value || !Object.values(roi).every(Number.isInteger) || roi.x < 0 || roi.y < 0 || roi.width < 1 || roi.height < 1 || roi.x + roi.width > current.value.width || roi.y + roi.height > current.value.height));
function merge<T extends { id: string }>(head: T[], tail: T[]) { const ids = new Set(head.map((item) => item.id)); return [...head, ...tail.filter((item) => !ids.has(item.id))]; }
function matches(item: { site_id?: string; device_id?: string | null; source?: string }, device: Device) { return item.site_id === device.site_id && item.device_id === device.device_id && item.source === device.source; }
function queryFor(device: Device, cursor?: string | null) { return new URLSearchParams({ site_id: device.site_id, device_id: device.device_id, source: device.source, limit: "50", ...(cursor ? { cursor } : {}) }); }
async function load() {
  if (!props.device || !props.connected || document.hidden || listLoading.value || disposed) return;
  listLoading.value = true;
  const epoch = generation, request = ++loadId, device = props.device;
  const valid = () => !disposed && epoch === generation && request === loadId;
  listController = new AbortController();
  try {
    const query = queryFor(device);
    const [images, analyses] = await Promise.all([api.get<Items<Evidence>>(`/evidence?${query}`, listController.signal), api.get<Items<VisionResult>>(`/vision/results?${query}`, listController.signal)]);
    if (!valid()) return;
    evidence.value = merge(images.items.filter((item) => matches(item, device)), evidence.value);
    results.value = merge(analyses.items.filter((item) => matches(item, device)), results.value);
    evidenceTotal.value = images.total ?? evidence.value.length; resultTotal.value = analyses.total ?? results.value.length;
    if (!evidencePaged) evidenceCursor.value = images.next_cursor || null;
    if (!resultsPaged) resultCursor.value = analyses.next_cursor || null;
    if (!currentId.value) currentId.value = evidence.value[0]?.id || "";
    loadError.value = "";
  } catch (cause) { if (valid() && !isAborted(cause)) loadError.value = errorMessage(cause); }
  finally { if (valid()) listLoading.value = false; }
}
async function more(kind: "evidence" | "results") {
  const isEvidence = kind === "evidence", cursor = isEvidence ? evidenceCursor.value : resultCursor.value;
  if (!props.device || !props.connected || !cursor || (isEvidence ? evidenceLoading.value : resultLoading.value)) return;
  const device = props.device, epoch = generation, controller = new AbortController();
  const request = isEvidence ? ++evidenceRequest : ++resultRequest;
  if (isEvidence) { evidenceController = controller; evidenceLoading.value = true; } else { resultController = controller; resultLoading.value = true; }
  const valid = () => !disposed && epoch === generation && request === (isEvidence ? evidenceRequest : resultRequest);
  try {
    const page = await api.get<Items<Evidence | VisionResult>>(`/${isEvidence ? "evidence" : "vision/results"}?${queryFor(device, cursor)}`, controller.signal);
    if (!valid()) return;
    if (isEvidence) { evidence.value = merge(evidence.value, page.items.filter((item) => matches(item, device)) as Evidence[]); evidenceCursor.value = page.next_cursor || null; evidencePaged = true; evidenceTotal.value = page.total ?? evidence.value.length; }
    else { results.value = merge(results.value, page.items.filter((item) => matches(item, device)) as VisionResult[]); resultCursor.value = page.next_cursor || null; resultsPaged = true; resultTotal.value = page.total ?? results.value.length; }
    loadError.value = "";
  } catch (cause) { if (valid() && !isAborted(cause)) loadError.value = errorMessage(cause); }
  finally { if (valid()) { if (isEvidence) evidenceLoading.value = false; else resultLoading.value = false; } }
}
function chooseFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null; error.value = ""; }
function operation() {
  if (busy.value || !props.device || !props.connected) return null;
  const epoch = generation, request = ++mutationId, device = props.device;
  mutationController = new AbortController(); busy.value = true; error.value = ""; notice.value = "";
  return { device, signal: mutationController.signal, valid: () => !disposed && epoch === generation && request === mutationId, finish: () => { if (!disposed && epoch === generation && request === mutationId) busy.value = false; } };
}
async function upload() {
  if (!file.value) return;
  const selectedFile = file.value, op = operation(); if (!op) return;
  try {
    if (selectedFile.size > 12 * 1024 * 1024) throw new Error("图片最大 12 MiB，请选择较小的 PNG 或 JPEG 图像");
    const body = new FormData();
    body.set("file", selectedFile); body.set("site_id", op.device.site_id); body.set("device_id", op.device.device_id); body.set("source", op.device.source); body.set("scope", op.device.source === "MOCK" ? "TEST_ONLY" : "OPERATIONAL"); body.set("camera_id", camera.value);
    if (captureTime.value) body.set("capture_time", new Date(captureTime.value).toISOString());
    const saved = await api.send<Evidence>("/evidence", body, "POST", op.signal);
    if (!op.valid()) return;
    evidence.value = merge([saved], evidence.value); currentId.value = saved.id; resultId.value = "";
    file.value = null; if (fileInput.value) fileInput.value.value = "";
    notice.value = "图像已保存到后端。选择参考图后可运行变化检测。"; emit("refresh");
  } catch (cause) { if (op.valid() && !isAborted(cause)) error.value = errorMessage(cause); }
  finally { op.finish(); }
}
async function samples() {
  if (!isDemo.value) return;
  const op = operation(); if (!op) return;
  try {
    const saved = await api.send<{ reference: Evidence; current: Evidence; result: VisionResult }>("/demo/vision-samples", {}, "POST", op.signal);
    if (!op.valid()) return;
    evidence.value = merge([saved.current, saved.reference], evidence.value); results.value = merge([saved.result], results.value); currentId.value = saved.current.id;
    await nextTick(); if (!op.valid()) return;
    referenceId.value = saved.reference.id; resultId.value = saved.result.id; roiEnabled.value = false;
    notice.value = "已生成两张明确标记为 MOCK 的示例图像，并保存变化检测结果。"; emit("refresh");
  } catch (cause) { if (op.valid() && !isAborted(cause)) error.value = errorMessage(cause); }
  finally { op.finish(); }
}
async function analyze() {
  if (!current.value || invalidRoi.value) return;
  const op = operation(); if (!op) return;
  try {
    const body = { evidence_id: currentId.value, ...(referenceId.value ? { reference_id: referenceId.value } : {}), ...(roiEnabled.value ? { roi: { ...roi } } : {}) };
    const saved = await api.send<VisionResult>("/vision/analyze", body, "POST", op.signal);
    if (!op.valid()) return;
    results.value = merge([saved], results.value); resultId.value = saved.id;
    notice.value = "视觉基线已完成，结果已持久化。变化指标尚未标定为灾害概率。"; emit("refresh");
  } catch (cause) { if (op.valid() && !isAborted(cause)) error.value = errorMessage(cause); }
  finally { op.finish(); }
}
function cancel() {
  generation++; mutationId++; loadId++; evidenceRequest++; resultRequest++;
  listController?.abort(); mutationController?.abort(); evidenceController?.abort(); resultController?.abort();
  busy.value = false; listLoading.value = false; evidenceLoading.value = false; resultLoading.value = false;
}
function reset() {
  cancel(); evidence.value = []; results.value = []; evidenceCursor.value = null; resultCursor.value = null; evidenceTotal.value = 0; resultTotal.value = 0; evidencePaged = false; resultsPaged = false;
  currentId.value = ""; referenceId.value = ""; resultId.value = ""; error.value = ""; loadError.value = ""; notice.value = ""; file.value = null; if (fileInput.value) fileInput.value.value = "";
  roiEnabled.value = false; camera.value = "CAM-01"; captureTime.value = ""; void load();
}
watch(contextKey, reset, { flush: "sync" });
watch(() => props.revision, () => { void load(); });
watch(() => props.connected, (connected) => { if (connected) void load(); });
watch(currentId, () => { resultId.value = ""; if (referenceId.value && !comparableEvidence.value.some((item) => item.id === referenceId.value)) referenceId.value = ""; });
onMounted(() => { void load(); });
onBeforeUnmount(() => { disposed = true; cancel(); });
function savedInputLabel(value: VisionResult) {
  const region = value.roi;
  return `参考图：${value.reference_id ? evidence.value.find((item) => item.id === value.reference_id)?.filename || value.reference_id : "未选择（仅质量检查）"}；区域：${region ? `x=${region.x}, y=${region.y}, ${region.width}×${region.height} px` : "未记录"}`;
}
function metric(key: string, decimals = 3) { const value = result.value?.metrics?.[key]; return typeof value === "number" ? reading(value, decimals) : "—"; }
const qualityRows = computed(() => {
  const quality = result.value?.quality || {};
  const currentQuality = quality.current && typeof quality.current === "object" ? quality.current as Record<string, unknown> : quality;
  const referenceQuality = quality.reference && typeof quality.reference === "object" ? quality.reference as Record<string, unknown> : null;
  const readable = (item: Record<string, unknown>, label: string) => [
    { label: `${label}可用性`, value: item.acceptable == null ? "—" : item.acceptable ? "通过质量检查" : "未通过质量检查" },
    { label: `${label}亮度`, value: typeof item.mean_gray === "number" ? item.mean_gray.toFixed(2) : "—" },
    { label: `${label}清晰度方差`, value: typeof item.laplacian_variance === "number" ? item.laplacian_variance.toFixed(2) : "—" },
    { label: `${label}质量标记`, value: Array.isArray(item.flags) && item.flags.length ? item.flags.join("、") : "无" },
  ];
  return [...readable(currentQuality, "当前图"), ...(referenceQuality ? readable(referenceQuality, "参考图") : [])];
});
</script>
<template>
  <section class="panel platform-section vision-panel">
    <div class="platform-panel-heading"><div><Camera :size="19" /><div><h2>视觉证据与变化检测</h2><p>上传现场图像，运行 OpenCV 基线，保留原图和分析结果。</p></div></div><button v-if="isDemo" class="secondary-button" :disabled="busy || !connected" @click="samples"><ImageIcon :size="14" />一键生成示例</button><span v-else class="mini-badge">视觉分数未标定</span></div>
    <p class="connection-note">当前站点 {{ device?.site_id || '—' }} / {{ device?.device_id || '—' }} · {{ device?.source || '—' }}。参考图需与当前图来自同一相机；ROI 使用原图像素坐标。基线结果不参与风险融合。</p>
    <p v-if="loadError" class="inline-error" role="alert">读取证据失败：{{ loadError }} <button class="text-button" @click="load">重试读取</button></p><p v-if="error" class="inline-error" role="alert">{{ error }}</p><p v-if="notice" class="inline-success" role="status">{{ notice }}</p>
    <form class="upload-form" @submit.prevent="upload">
      <label class="file-picker"><Upload :size="20" /><span>{{ file?.name || '选择 PNG / JPEG 图像' }}</span><input ref="fileInput" type="file" accept="image/png,image/jpeg" required @change="chooseFile" aria-label="选择图像" /></label>
      <label>相机 ID<input v-model="camera" required maxlength="100" /></label><label>采集时间（可选）<input v-model="captureTime" type="datetime-local" /></label>
      <button class="primary-button compact" :disabled="busy || !file || !device || !connected"><Upload :size="14" />{{ busy ? '处理中…' : '上传图像' }}</button>
    </form>
    <div v-if="!evidence.length" class="platform-empty" role="status" :aria-busy="listLoading"><ImageIcon :size="30" /><h3>{{ listLoading ? '正在读取视觉证据…' : !connected ? '后端未连接，证据暂不可用' : loadError ? '视觉证据读取失败' : '还没有视觉证据' }}</h3><p>{{ connected && !loadError ? '先上传一张图像检查画面质量，再上传同一设备、同相机的第二张图像进行对比。' : '恢复连接或重试后读取已保存的图像，失败不代表没有证据。' }}</p></div>
    <template v-else>
      <div class="analysis-controls" aria-live="polite"><span class="muted list-count">已加载 {{ evidence.length }} / {{ evidenceTotal }} 份证据</span><button v-if="evidenceCursor" class="secondary-button" :disabled="evidenceLoading || !connected" :aria-busy="evidenceLoading" @click="more('evidence')">{{ evidenceLoading ? '读取中…' : '加载更多证据' }}</button></div>
      <div class="evidence-grid">
        <div class="evidence-card"><label>参考图像<select v-model="referenceId" aria-label="参考图像"><option value="">不选择 · 仅检查当前画面质量</option><option v-for="item in comparableEvidence" :key="item.id" :value="item.id">{{ item.camera_id }} / {{ item.original_name || item.filename || item.id.slice(0, 8) }} / {{ dateTime(item.capture_time || item.captured_at || item.arrival_time || item.created_at) }}</option></select></label><AuthMedia :url="reference?.file_url" alt="用于视觉基线对比的参考图像" /><p v-if="reference">{{ reference.width }} × {{ reference.height }} · {{ reference.source }} · {{ reference.camera_id }}<small>采集 {{ dateTime(reference.capture_time || reference.captured_at) }}</small></p></div>
        <div class="evidence-card"><label>当前图像<select v-model="currentId" aria-label="当前图像"><option v-for="item in evidence" :key="item.id" :value="item.id">{{ item.camera_id }} / {{ item.original_name || item.filename || item.id.slice(0, 8) }} / {{ dateTime(item.capture_time || item.captured_at || item.arrival_time || item.created_at) }}</option></select></label><AuthMedia :url="current?.file_url" alt="当前上传的现场图像" /><p v-if="current">{{ current.width }} × {{ current.height }} · {{ current.source }} · {{ current.camera_id }}<small>采集 {{ dateTime(current.capture_time || current.captured_at) }} · 入库 {{ dateTime(current.arrival_time || current.created_at || current.received_at) }}</small></p></div>
      </div>
      <div class="analysis-controls"><label class="checkbox-label"><input v-model="roiEnabled" type="checkbox" />限定检测区域 ROI</label><template v-if="roiEnabled"><label v-for="key in (['x', 'y', 'width', 'height'] as const)" :key="key">{{ key }}<input v-model.number="roi[key]" type="number" :min="key === 'x' || key === 'y' ? 0 : 1" :max="key === 'x' || key === 'width' ? current?.width : current?.height" required /></label></template><button class="primary-button compact" :disabled="busy || !current || !connected || invalidRoi" :aria-busy="busy" @click="analyze"><ScanLine :size="15" />运行视觉基线</button></div>
      <p v-if="invalidRoi" class="inline-error region-error" role="alert">检测区域需为原图范围内的整数坐标，宽高至少 1 px。</p>
      <div v-if="results.length || resultCursor" class="analysis-controls"><label class="saved-result-select">已保存的分析<select v-model="resultId" aria-label="已保存的分析"><option value="">当前图的最近结果</option><option v-for="item in results" :key="item.id" :value="item.id">{{ dateTime(item.created_at) }} · {{ evidence.find((image) => image.id === item.evidence_id)?.filename || item.evidence_id }}</option></select></label><span class="muted list-count">已加载 {{ results.length }} / {{ resultTotal }} 条</span><button v-if="resultCursor" class="secondary-button" :disabled="resultLoading || !connected" :aria-busy="resultLoading" @click="more('results')">{{ resultLoading ? '读取中…' : '加载更多分析记录' }}</button></div>
      <div v-if="result" class="vision-result">
        <p v-if="resultChanged" class="inline-error" role="status" data-testid="vision-inputs-changed">参数已更改，需重新分析。以下为已保存结果，与当前预览或检测区域不一致。</p>
        <p class="connection-note" data-testid="vision-saved-inputs">{{ savedInputLabel(result) }} · 当前图 ID：{{ result.evidence_id }}</p>
        <div class="vision-result-heading"><h3>{{ resultChanged ? '已保存的分析结果' : '分析结果' }}</h3><span :class="['connection-pill', { online: result.baseline_valid }]">{{ result.baseline_valid ? '基线有效' : '仅质量检查 / 基线无效' }}</span><span>风险分数 {{ reading(result.vision_score) }} · {{ result.fusion_eligible ? '可参与融合' : '不参与融合' }}</span></div>
        <div class="vision-metrics"><div><span>变化区域比例</span><strong>{{ result.metrics?.changed_area_ratio == null ? '—' : (Number(result.metrics.changed_area_ratio) * 100).toFixed(2) + '%' }}</strong></div><div><span>结构相似度 SSIM</span><strong>{{ metric('ssim') }}</strong></div><div><span>光流中位数 / P95</span><strong class="flow-reading">{{ metric('optical_flow_median_px_per_frame') }} / {{ metric('optical_flow_p95_px_per_frame') }} <small>px/帧对</small></strong></div><div><span>视觉风险</span><strong>{{ result.vision_score == null ? '未标定' : reading(result.vision_score) }}</strong></div></div>
        <div class="result-details"><div><h4>画面质量</h4><dl><template v-for="row in qualityRows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl><p v-for="reason in result.reasons || []" :key="reason" class="result-reason">{{ reason === 'uncalibrated_vision_score' ? '视觉风险分数尚未标定，当前结果不参与融合。' : reason }}</p><p class="muted">结果保存于 {{ dateTime(result.created_at) }}。SSIM、帧差与光流仅表示图像变化，受光照和相机运动影响。</p></div><div v-if="result.overlay_url"><h4>变化叠加图</h4><AuthMedia :url="result.overlay_url" alt="OpenCV 变化检测叠加图" /></div></div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.analysis-controls { padding-top: 16px; }
.analysis-controls > .saved-result-select { max-width: min(100%, 540px); width: min(100%, 540px); }
.list-count { font-size: 11px; }
.region-error { margin-inline: 23px; }
.vision-result > .connection-note { padding: 10px 0 15px; overflow-wrap: anywhere; }
@media (max-width: 760px) { .analysis-controls > .saved-result-select { width: 100%; max-width: 100%; } }
</style>
