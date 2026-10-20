<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { Plus, Pencil, Trash2, Radio, PlugZap, Save, X } from "lucide-vue-next";
import { api, errorMessage } from "./api";
import type { Connector, ConnectorWrite, Items, MqttStatus } from "./types";
const props = defineProps<{ connectors: Connector[]; statuses: MqttStatus[]; connected: boolean }>();
const emit = defineEmits<{ refresh: [] }>();
const items = ref<Connector[]>([]);
watch(() => props.connectors, (value) => { items.value = value; }, { immediate: true });
const defaults = () => ({ name: "", source: "REAL" as "REAL" | "MOCK", enabled: false, payload_format: "telemetry_v2" as "telemetry_v2" | "tinyquake_v1", host: "127.0.0.1", port: 1883, topic: "zhifang/v2/{SITE}/+/telemetry", site_id: "SITE01", username: "", password: "", tls: false, client_id: "" });
const form = reactive(defaults());
const editing = ref<string | null>(null);
const showForm = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const testResult = ref<{ id: string; text: string; success: boolean } | null>(null);
const existingPassword = computed(() => { const item = items.value.find((x) => x.id === editing.value); return item?.has_password || item?.password_configured || item?.config.password_configured; });
function open(item?: Connector) {
  Object.assign(form, defaults());
  editing.value = item?.id || null;
  if (item) Object.assign(form, { name: item.name, source: item.source, enabled: item.enabled, ...item.config, password: "" });
  error.value = ""; notice.value = ""; showForm.value = true;
}
function formatChanged() { form.topic = form.payload_format === "tinyquake_v1" ? "zhifang/experimental/tinyquake/v1/{SITE}/+/+/result" : "zhifang/v2/{SITE}/+/telemetry"; if (form.payload_format === "tinyquake_v1") form.source = "MOCK"; }
async function reload() { items.value = (await api.get<Items<Connector>>("/connectors")).items; emit("refresh"); }
async function save() {
  busy.value = true; error.value = ""; notice.value = "";
  const config: ConnectorWrite["config"] = { payload_format: form.payload_format, host: form.host.trim(), port: Number(form.port), topic: form.topic.trim().replaceAll("{SITE}", form.site_id.trim()), site_id: form.site_id.trim(), username: form.username, tls: form.tls };
  if (form.password || !editing.value) config.password = form.password;
  if (form.client_id) config.client_id = form.client_id;
  const body: ConnectorWrite = { name: form.name.trim(), kind: "mqtt", source: form.source, enabled: form.enabled, config };
  try {
    await api.send(editing.value ? `/connectors/${encodeURIComponent(editing.value)}` : "/connectors", body, editing.value ? "PUT" : "POST");
    showForm.value = false; notice.value = "连接器已保存。启用后由后端持续接收并写入数据库。"; await reload();
  } catch (cause) { error.value = errorMessage(cause); }
  finally { busy.value = false; }
}
async function remove(item: Connector) {
  if (!window.confirm(`删除连接器“${item.name}”？已接收的历史数据会保留。`)) return;
  busy.value = true; error.value = "";
  try { await api.send(`/connectors/${encodeURIComponent(item.id)}`, {}, "DELETE"); notice.value = "连接器已删除"; await reload(); }
  catch (cause) { error.value = errorMessage(cause); }
  finally { busy.value = false; }
}
async function test(item: Connector) {
  busy.value = true; error.value = ""; testResult.value = null;
  try {
    const result = await api.send<Record<string, unknown>>(`/connectors/${encodeURIComponent(item.id)}/test`);
    const success = result.ok === true || result.connected === true || result.success === true;
    testResult.value = { id: item.id, success, text: String(result.message || result.error || result.detail || result.status || JSON.stringify(result)) };
    await reload();
  } catch (cause) { testResult.value = { id: item.id, success: false, text: errorMessage(cause) }; }
  finally { busy.value = false; }
}
function status(item: Connector) {
  const state = props.statuses.find((x) => x.id === item.id || x.connector_id === item.id);
  if (!props.connected) return { label: "后端失联", detail: "连接状态不可用", online: false };
  if (!item.enabled) return { label: "未启用", detail: "保存配置后，勾选启用以持续订阅", online: false };
  const own = typeof item.status === "object" ? item.status : undefined;
  const current = state || own;
  if (current?.state === "storage_error" || current?.intake_healthy === false) return { label: "接入存储异常", detail: current.last_error || "Broker 连接存在，但遥测尚未可靠写入存储", online: false };
  return { label: current?.connected ? "已连接" : current?.state || current?.status || (typeof item.status === "string" ? item.status : "等待连接"), detail: current?.last_error || current?.message || `已接收 ${current?.messages_received ?? current?.received_count ?? "—"} 条消息`, online: !!current?.connected };
}
</script>
<template>
  <section class="panel platform-section connector-panel">
    <div class="platform-panel-heading"><div><Radio :size="19" /><div><h2>MQTT 数据接入</h2><p>连接真实网关或独立测试流，按来源分别保存。</p></div></div><button class="primary-button compact" @click="open()" :disabled="!connected || busy"><Plus :size="15" />新增连接器</button></div>
    <div class="connection-note">Topic 中的 <code>{SITE}</code> 使用站点 ID 替换；设备段支持 <code>+</code> 或指定设备 ID，订阅限定在所选站点内。认证信息仅保存在后端，界面读取脱敏配置。</div>
    <p v-if="error" class="inline-error" role="alert">{{ error }}</p><p v-if="notice" class="inline-success" role="status">{{ notice }}</p>
    <form v-if="showForm" class="connector-form" @submit.prevent="save">
      <div class="form-title"><h3>{{ editing ? '编辑连接器' : '新增 MQTT 连接器' }}</h3><button type="button" class="icon-button" aria-label="关闭连接器表单" @click="showForm = false"><X :size="17" /></button></div>
      <div class="form-grid">
        <label>名称<input v-model="form.name" required maxlength="120" placeholder="现场 Atlas 网关" /></label>
        <label>数据来源<select v-model="form.source" aria-label="数据来源"><option value="REAL">REAL · 真实设备</option><option value="MOCK">MOCK · 测试数据</option></select></label>
        <label>消息格式<select v-model="form.payload_format" aria-label="消息格式" @change="formatChanged"><option value="telemetry_v2">标准 v2 遥测</option><option value="tinyquake_v1">TinyQuake 实验结果</option></select></label>
        <label>Broker 地址<input v-model="form.host" required placeholder="127.0.0.1" /></label>
        <label>端口<input v-model.number="form.port" type="number" required min="1" max="65535" /></label>
        <label>站点 ID<input v-model="form.site_id" required pattern="[A-Za-z0-9_-]+" /></label>
        <label>订阅 Topic<input v-model="form.topic" required /></label>
        <label>用户名<input v-model="form.username" autocomplete="off" /></label>
        <label>密码<input v-model="form.password" type="password" autocomplete="new-password" :placeholder="existingPassword ? '已配置；留空保留原密码' : '可选'" /></label>
        <label>客户端 ID<input v-model="form.client_id" placeholder="留空由后端生成" /></label>
        <div class="form-checkboxes"><label><input v-model="form.tls" type="checkbox" />启用 TLS</label><label><input v-model="form.enabled" type="checkbox" />启用持续订阅</label></div>
      </div>
      <div class="form-actions"><span>启用配置将启动后端订阅任务。</span><button class="primary-button compact" :disabled="busy"><Save :size="14" />{{ busy ? '保存中…' : '保存连接器' }}</button></div>
    </form>
    <div v-if="!items.length && !showForm" class="platform-empty"><PlugZap :size="30" /><h3>接入第一路设备数据</h3><p>配置 Broker、站点和 Topic。未接入硬件时，可使用后端演示数据验证平台流程。</p></div>
    <div v-for="item in items" :key="item.id" class="connector-row">
      <div class="connector-icon"><Radio :size="20" /></div><div class="connector-main"><div><strong>{{ item.name }}</strong><span v-if="item.config.payload_format === 'tinyquake_v1'" class="source-badge">TinyQuake · TEST_ONLY</span><span :class="['source-badge', item.source.toLowerCase()]">{{ item.source }}</span><span :class="['connection-pill', { online: status(item).online }]">{{ status(item).label }}</span></div><p>{{ item.config.host }}:{{ item.config.port }} <span>· {{ item.config.tls ? 'TLS' : 'TCP' }} · {{ item.config.site_id }}</span></p><code>{{ item.config.topic }}</code><small>{{ status(item).detail }}</small><p v-if="testResult?.id === item.id" :class="testResult.success ? 'inline-success' : 'inline-error'" role="status">连通性测试：{{ testResult.text }}</p></div>
      <div class="connector-actions"><button class="secondary-button" :disabled="busy || !connected" @click="test(item)"><PlugZap :size="14" />测试连接</button><button class="icon-button" :disabled="busy || !connected" aria-label="编辑连接器" @click="open(item)"><Pencil :size="16" /></button><button class="icon-button danger-button" :disabled="busy || !connected" aria-label="删除连接器" @click="remove(item)"><Trash2 :size="16" /></button></div>
    </div>
  </section>
</template>
