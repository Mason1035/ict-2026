<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { Camera, Upload, ScanLine, Image as ImageIcon } from "lucide-vue-next";
import { api, errorMessage, isAborted } from "./api";
import { dateTime, reading, type Device, type Evidence, type Items, type VisionResult } from "./types";
import AuthMedia from "./AuthMedia.vue";
const props = defineProps<{ device: Device | undefined; connected: boolean; revision: string | null }>();
const emit = defineEmits<{ refresh: [] }>();
const evidence = ref<Evidence[]>([]);
const results = ref<VisionResult[]>([]);
const currentId = ref("");
const referenceId = ref("");
const resultId = ref("");
const file = ref<File | null>(null);
const fileInput = ref<HTMLInputElement>();
const camera = ref("CAM-01");
const captureTime = ref("");
const error = ref("");
const notice = ref("");
const busy = ref(false);
const roiEnabled = ref(false);
const roi = reactive({ x: 0, y: 0, width: 320, height: 240 });
let controller: AbortController | undefined;
let loading = false;
let disposed = false;
let loadGeneration = 0;
const current = computed(() => evidence.value.find((x) => x.id === currentId.value));
const reference = computed(() => evidence.value.find((x) => x.id === referenceId.value));
const result = computed(() => resultId.value ? results.value.find((x) => x.id === resultId.value) : results.value.find((x) => x.evidence_id === currentId.value));
const comparableEvidence = computed(() => evidence.value.filter((x) => x.id !== currentId.value && (!current.value || x.camera_id === current.value.camera_id)));
async function load() {
  if (!props.device || !props.connected || document.hidden || loading || disposed) return;
  loading = true;
  const generation = loadGeneration;
  const device = props.device;
  controller = new AbortController();
  try {
    const query = new URLSearchParams({ site_id: device.site_id, device_id: device.device_id, source: device.source });
    const [images, analyses] = await Promise.all([api.get<Items<Evidence>>(`/evidence?${query}`, controller.signal), api.get<Items<VisionResult>>(`/vision/results?${query}`, controller.signal)]);
    if (disposed || generation !== loadGeneration) return;
    evidence.value = images.items.filter((x) => x.device_id === device.device_id && x.source === device.source);
    const ids = new Set(evidence.value.map((x) => x.id));
    results.value = analyses.items.filter((x) => ids.has(x.evidence_id));
    if (!ids.has(currentId.value)) currentId.value = evidence.value[0]?.id || "";
    if (referenceId.value && !ids.has(referenceId.value)) referenceId.value = "";
  } catch (cause) { if (!isAborted(cause)) error.value = errorMessage(cause); }
  finally { loading = false; }
}
function chooseFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null; error.value = ""; }
async function upload() {
  if (!file.value || !props.device) return;
  const device = props.device;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const body = new FormData();
    body.set("file", file.value); body.set("site_id", device.site_id); body.set("device_id", device.device_id); body.set("source", device.source); body.set("scope", device.source === "MOCK" ? "TEST_ONLY" : "OPERATIONAL"); body.set("camera_id", camera.value);
    if (captureTime.value) body.set("capture_time", new Date(captureTime.value).toISOString());
    const saved = await api.send<Evidence>("/evidence", body);
    currentId.value = saved.id; resultId.value = "";
    file.value = null; if (fileInput.value) fileInput.value.value = "";
    await load(); notice.value = "图像已保存到后端。选择参考图后可运行变化检测。"; emit("refresh");
  } catch (cause) { error.value = errorMessage(cause); }
  finally { busy.value = false; }
}
async function samples() {
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const saved = await api.send<{ reference: Evidence; current: Evidence; result: VisionResult }>("/demo/vision-samples");
    evidence.value = [saved.current, saved.reference, ...evidence.value.filter((item) => item.id !== saved.current.id && item.id !== saved.reference.id)];
    results.value = [saved.result, ...results.value.filter((item) => item.id !== saved.result.id)];
    currentId.value = saved.current.id;
    await nextTick();
    referenceId.value = saved.reference.id; resultId.value = saved.result.id;
    notice.value = "已生成两张明确标记为 MOCK 的示例图像，并保存变化检测结果。"; emit("refresh");
  } catch (cause) { error.value = errorMessage(cause); }
  finally { busy.value = false; }
}
async function analyze() {
  if (!current.value) return;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    const body = { evidence_id: currentId.value, ...(referenceId.value ? { reference_id: referenceId.value } : {}), ...(roiEnabled.value ? { roi: { ...roi } } : {}) };
    const saved = await api.send<VisionResult>("/vision/analyze", body);
    results.value = [saved, ...results.value.filter((x) => x.id !== saved.id)]; resultId.value = saved.id;
    notice.value = "视觉基线已完成，结果已持久化。变化指标尚未标定为灾害概率。"; emit("refresh");
  } catch (cause) { error.value = errorMessage(cause); }
  finally { busy.value = false; }
}
function reset() { loadGeneration++; controller?.abort(); loading = false; evidence.value = []; results.value = []; currentId.value = ""; referenceId.value = ""; resultId.value = ""; error.value = ""; notice.value = ""; void load(); }
watch(() => `${props.device?.site_id}|${props.device?.device_id}|${props.device?.source}`, reset);
watch(() => props.revision, () => { void load(); });
watch(currentId, () => { resultId.value = ""; if (currentId.value === referenceId.value || (current.value && reference.value && current.value.camera_id !== reference.value.camera_id)) referenceId.value = ""; });
onMounted(() => { void load(); });
onBeforeUnmount(() => { disposed = true; controller?.abort(); });
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
    <div class="platform-panel-heading"><div><Camera :size="19" /><div><h2>视觉证据与变化检测</h2><p>上传现场图像，运行 OpenCV 基线，保留原图和分析结果。</p></div></div><button v-if="device?.site_id === 'DEMO' && device?.source === 'MOCK'" class="secondary-button" :disabled="busy || !connected" @click="samples"><ImageIcon :size="14" />一键生成示例</button><span v-else class="mini-badge">视觉分数未标定</span></div>
    <p class="connection-note">当前站点 {{ device?.site_id || '—' }} / {{ device?.device_id || '—' }} · {{ device?.source || '—' }}。参考图需与当前图来自同一相机；ROI 使用原图像素坐标。基线结果不参与风险融合。</p>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p><p v-if="notice" class="inline-success" role="status">{{ notice }}</p>
    <form class="upload-form" @submit.prevent="upload">
      <label class="file-picker"><Upload :size="20" /><span>{{ file?.name || '选择 PNG / JPEG 图像' }}</span><input ref="fileInput" type="file" accept="image/png,image/jpeg" required @change="chooseFile" aria-label="选择图像" /></label>
      <label>相机 ID<input v-model="camera" required maxlength="100" /></label><label>采集时间（可选）<input v-model="captureTime" type="datetime-local" /></label>
      <button class="primary-button compact" :disabled="busy || !file || !device || !connected"><Upload :size="14" />{{ busy ? '处理中…' : '上传图像' }}</button>
    </form>
    <div v-if="!evidence.length" class="platform-empty"><ImageIcon :size="30" /><h3>还没有视觉证据</h3><p>先上传一张图像检查画面质量，再上传同一相机的第二张图像进行对比。</p></div>
    <template v-else>
      <div class="evidence-grid">
        <div class="evidence-card"><label>参考图像<select v-model="referenceId" aria-label="参考图像"><option value="">不选择 · 仅检查当前画面质量</option><option v-for="item in comparableEvidence" :key="item.id" :value="item.id">{{ item.camera_id }} / {{ item.original_name || item.filename || item.id.slice(0, 8) }} / {{ dateTime(item.capture_time || item.captured_at || item.arrival_time || item.created_at) }}</option></select></label><AuthMedia :url="reference?.file_url" alt="用于视觉基线对比的参考图像" /><p v-if="reference">{{ reference.width }} × {{ reference.height }} · {{ reference.source }} · {{ reference.camera_id }}<small>采集 {{ dateTime(reference.capture_time || reference.captured_at) }}</small></p></div>
        <div class="evidence-card"><label>当前图像<select v-model="currentId" aria-label="当前图像"><option v-for="item in evidence" :key="item.id" :value="item.id">{{ item.camera_id }} / {{ item.original_name || item.filename || item.id.slice(0, 8) }} / {{ dateTime(item.capture_time || item.captured_at || item.arrival_time || item.created_at) }}</option></select></label><AuthMedia :url="current?.file_url" alt="当前上传的现场图像" /><p v-if="current">{{ current.width }} × {{ current.height }} · {{ current.source }} · {{ current.camera_id }}<small>采集 {{ dateTime(current.capture_time || current.captured_at) }} · 入库 {{ dateTime(current.arrival_time || current.created_at || current.received_at) }}</small></p></div>
      </div>
      <div class="analysis-controls"><label class="checkbox-label"><input v-model="roiEnabled" type="checkbox" />限定检测区域 ROI</label><template v-if="roiEnabled"><label v-for="key in (['x', 'y', 'width', 'height'] as const)" :key="key">{{ key }}<input v-model.number="roi[key]" type="number" :min="key === 'x' || key === 'y' ? 0 : 1" :max="key === 'x' || key === 'width' ? current?.width : current?.height" required /></label></template><button class="primary-button compact" :disabled="busy || !current || !connected" @click="analyze"><ScanLine :size="15" />运行视觉基线</button></div>
      <div v-if="result" class="vision-result">
        <div class="vision-result-heading"><h3>分析结果</h3><span :class="['connection-pill', { online: result.baseline_valid }]">{{ result.baseline_valid ? '基线有效' : '仅质量检查 / 基线无效' }}</span><span>风险分数 {{ reading(result.vision_score) }} · {{ result.fusion_eligible ? '可参与融合' : '不参与融合' }}</span></div>
        <div class="vision-metrics"><div><span>变化区域比例</span><strong>{{ result.metrics?.changed_area_ratio == null ? '—' : (Number(result.metrics.changed_area_ratio) * 100).toFixed(2) + '%' }}</strong></div><div><span>结构相似度 SSIM</span><strong>{{ metric('ssim') }}</strong></div><div><span>光流中位数 / P95</span><strong class="flow-reading">{{ metric('optical_flow_median_px_per_frame') }} / {{ metric('optical_flow_p95_px_per_frame') }} <small>px/帧对</small></strong></div><div><span>视觉风险</span><strong>{{ result.vision_score == null ? '未标定' : reading(result.vision_score) }}</strong></div></div>
        <div class="result-details"><div><h4>画面质量</h4><dl><template v-for="row in qualityRows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl><p v-for="reason in result.reasons || []" :key="reason" class="result-reason">{{ reason === 'uncalibrated_vision_score' ? '视觉风险分数尚未标定，当前结果不参与融合。' : reason }}</p><p class="muted">结果保存于 {{ dateTime(result.created_at) }}。SSIM、帧差与光流仅表示图像变化，受光照和相机运动影响。</p></div><div v-if="result.overlay_url"><h4>变化叠加图</h4><AuthMedia :url="result.overlay_url" alt="OpenCV 变化检测叠加图" /></div></div>
      </div>
    </template>
  </section>
</template>
