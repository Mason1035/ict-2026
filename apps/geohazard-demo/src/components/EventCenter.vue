<script setup lang="ts">
import { computed, ref, watch, nextTick } from "vue";
import {
  List,
  Bell,
  Database,
  Check,
  ArrowUpRight,
  X,
  CheckCircle2,
  ShieldCheck,
  Inbox,
  Trash2,
} from "lucide-vue-next";
import type { SimulationState } from "../simulation";
import { getQueueStats } from "../simulation";
const props = defineProps<{ state: SimulationState }>();
const emit = defineEmits<{ clear: [] }>();
const tab = ref("logs"),
  important = ref(false),
  clearPrompt = ref(false);
const selected = ref<SimulationState["alerts"][number] | null>(null);
const alertDialog = ref<HTMLDialogElement>(),
  clearDialog = ref<HTMLDialogElement>();
watch(selected, async (value) => {
  await nextTick();
  if (value && !alertDialog.value?.open) alertDialog.value?.showModal();
  else if (!value) alertDialog.value?.close();
});
watch(clearPrompt, async (value) => {
  await nextTick();
  if (value && !clearDialog.value?.open) clearDialog.value?.showModal();
  else if (!value) clearDialog.value?.close();
});
watch(
  () => props.state.bootId,
  () => {
    selected.value = null;
    clearPrompt.value = false;
    important.value = false;
    tab.value = "logs";
  },
);
function tabKey(e: KeyboardEvent) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const tabs = ["logs", "alerts", "queue"],
    i = tabs.indexOf(tab.value);
  tab.value =
    e.key === "Home"
      ? "logs"
      : e.key === "End"
        ? "queue"
        : tabs[(i + (e.key === "ArrowRight" ? 1 : 2)) % 3];
  nextTick(() => document.getElementById("event-tab-" + tab.value)?.focus());
}
const pending = computed(() =>
  props.state.queue.filter((r) => r.status !== "Synced"),
);
const high = computed(() => pending.value.filter((r) => r.score >= 60).length);
const synced = computed(
  () => props.state.queue.filter((r) => r.status === "Synced").length,
);
const sending = computed(() =>
  props.state.queue.find((r) => r.status === "Sending"),
);
const logs = computed(() =>
  props.state.logs
    .filter((r) => !important.value || !r.message.includes("采样完成"))
    .slice(0, 60),
);
const rows = computed(() =>
  [...props.state.queue]
    .sort(
      (a, b) =>
        (a.status === "Synced" ? 1 : 0) - (b.status === "Synced" ? 1 : 0) ||
        b.score - a.score,
    )
    .slice(0, 30),
);
const stamp = (t: number) =>
  `T+${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
const levels: Record<string, string> = {
  low: "低风险",
  moderate: "中风险",
  high: "高风险",
  critical: "紧急预警",
};
const progress = computed(() =>
  props.state.queue.length
    ? (synced.value / props.state.queue.length) * 100
    : 0,
);
const lastSynced = computed(() => getQueueStats(props.state).latestResult);
</script>
<template>
  <section class="panel event-center" id="events">
    <div class="event-toolbar">
      <div
        class="event-tabs"
        @keydown="tabKey"
        role="tablist"
        aria-label="事件中心"
      >
        <button
          :class="{ selected: tab === 'logs' }"
          id="event-tab-logs"
          role="tab"
          aria-controls="event-tabpanel"
          :tabindex="tab === 'logs' ? 0 : -1"
          :aria-selected="tab === 'logs'"
          @click="tab = 'logs'"
        >
          <List :size="16" />事件日志<span>{{
            state.logs.length
          }}</span></button
        ><button
          :class="{ selected: tab === 'alerts' }"
          id="event-tab-alerts"
          role="tab"
          aria-controls="event-tabpanel"
          :tabindex="tab === 'alerts' ? 0 : -1"
          :aria-selected="tab === 'alerts'"
          @click="tab = 'alerts'"
        >
          <Bell :size="16" />告警中心<span
            :class="{ 'alert-count': state.risk.score >= 60 }"
            >{{ state.alerts.length }}</span
          ></button
        ><button
          :class="{ selected: tab === 'queue' }"
          id="event-tab-queue"
          role="tab"
          aria-controls="event-tabpanel"
          :tabindex="tab === 'queue' ? 0 : -1"
          :aria-selected="tab === 'queue'"
          @click="tab = 'queue'"
        >
          <Database :size="16" />离线队列<span>{{ pending.length }}</span>
        </button>
      </div>
      <label v-if="tab === 'logs'" class="event-filter"
        ><input type="checkbox" v-model="important" />仅重要事件</label
      ><button
        v-else-if="tab === 'queue'"
        class="text-button"
        @click="clearPrompt = true"
      >
        <Trash2 :size="13" />清空演示数据
      </button>
    </div>
    <div
      class="event-content"
      id="event-tabpanel"
      role="tabpanel"
      :aria-labelledby="'event-tab-' + tab"
    >
      <template v-if="tab === 'logs'"
        ><div class="log-header">
          <span>仿真时间</span><span>事件类型</span><span>事件详情</span
          ><span>来源</span>
        </div>
        <div class="log-list">
          <div v-for="log in logs" :key="log.id" class="log-row">
            <time>{{ stamp(log.time) }}</time
            ><span :class="['log-type', log.type.toLowerCase()]">{{
              log.type
            }}</span
            ><span>{{ log.message }}</span
            ><small>DEMO ENGINE</small>
          </div>
          <div v-if="!logs.length" class="empty-state">
            <Inbox :size="24" /><strong>等待下一次事件</strong>
            <p>推进仿真即可生成采样记录。</p>
          </div>
        </div></template
      >
      <template v-if="tab === 'alerts'"
        ><div v-if="!state.alerts.length" class="empty-state">
          <ShieldCheck :size="28" /><strong>当前没有风险告警</strong>
          <p>切换暴雨或位移异常场景，观察风险升级。</p>
        </div>
        <div v-else class="alerts-list">
          <button
            v-for="alert in state.alerts"
            :key="alert.id"
            class="alert-row"
            @click="selected = alert"
          >
            <span :class="['alert-icon', alert.level]"
              ><Bell :size="17"
            /></span>
            <div>
              <strong>{{ levels[alert.level] }}</strong>
              <p>{{ alert.reason }}</p>
            </div>
            <time>{{ stamp(alert.time) }}</time
            ><span
              :class="[
                'tag',
                alert.status === 'active' ? 'tag-amber' : 'tag-neutral',
              ]"
              >{{ alert.status === "active" ? "待关注" : "已解除" }}</span
            ><ArrowUpRight :size="16" />
          </button></div
      ></template>
      <template v-if="tab === 'queue'"
        ><div class="queue-summary">
          <div>
            <small>待补传</small
            ><strong>{{ pending.length }}<span>条</span></strong>
          </div>
          <div>
            <small>高危历史事件</small
            ><strong>{{ high }}<span>条</span></strong>
          </div>
          <div>
            <small>历史采样</small
            ><strong
              >{{ pending.filter((r) => r.kind === "sample").length
              }}<span>条</span></strong
            >
          </div>
          <div class="queue-progress">
            <small>{{
              sending
                ? "正在发送 " + sending.id
                : state.network === "OFFLINE"
                  ? "等待链路恢复"
                  : "补传进度"
            }}</small>
            <div class="progress-track">
              <i :style="{ width: progress + '%' }" />
            </div>
            <span
              >{{ synced }} / {{ state.queue.length }} 已同步{{
                lastSynced ? " · 最近送达 " + lastSynced.id : ""
              }}</span
            >
          </div>
        </div>
        <div v-if="!state.queue.length" class="queue-empty">
          <CheckCircle2 :size="20" />没有积压记录。关闭 Wi-Fi 和
          LoRa，体验本地缓存。
        </div>
        <div v-else class="queue-list">
          <div v-for="row in rows" :key="row.id" class="queue-row">
            <code>{{ row.id }}</code
            ><span>{{ row.kind === "alert" ? "风险告警" : "遥测采样" }}</span
            ><span :class="row.level"
              >{{ levels[row.level] }} · {{ row.score.toFixed(1) }}</span
            ><time>{{ stamp(row.time) }}</time
            ><span :class="['queue-status', row.status.toLowerCase()]"
              ><Check v-if="row.status === 'Synced'" :size="12" />{{
                row.status
              }}</span
            ><small>尝试 {{ row.attempts }}</small>
          </div>
        </div></template
      >
    </div>
    <div class="event-footer">
      <span><i class="status-dot" />本地风险引擎持续运行</span
      ><span>稳定事件 ID · 高危优先 · 按记录确认补传</span>
    </div>
    <Teleport to="body"
      ><dialog
        ref="alertDialog"
        class="modal native-modal"
        aria-labelledby="alert-title"
        @close="selected = null"
      >
        <section v-if="selected" class="dialog-content">
          <button
            class="modal-close icon-button"
            aria-label="关闭详情"
            @click="selected = null"
          >
            <X :size="18" /></button
          ><Bell :size="24" class="accent" />
          <h2 id="alert-title">{{ levels[selected.level] }}详情</h2>
          <p>{{ selected.reason }}</p>
          <dl class="detail-list">
            <div>
              <dt>触发时间</dt>
              <dd>{{ stamp(selected.time) }}</dd>
            </div>
            <div>
              <dt>事件 ID</dt>
              <dd>{{ selected.id }}</dd>
            </div>
            <div>
              <dt>演示风险评分</dt>
              <dd>{{ selected.score.toFixed(1) }} / 100</dd>
            </div>
            <div>
              <dt>湿度 / 倾角 / 振动</dt>
              <dd>
                {{ selected.sensors.moisture }}% / {{ selected.sensors.tilt }}°
                / {{ selected.sensors.vibration }}g
              </dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{{ selected.status === "active" ? "待关注" : "已解除" }}</dd>
            </div>
          </dl>
          <button class="primary-button" @click="selected = null">了解</button>
        </section>
      </dialog>
      <dialog
        ref="clearDialog"
        class="modal native-modal"
        aria-labelledby="clear-title"
        @close="clearPrompt = false"
      >
        <section class="dialog-content">
          <Database :size="24" />
          <h2 id="clear-title">清空演示记录</h2>
          <p>
            清空事件、告警和补传记录，并恢复正常场景与通信初始状态。此操作仅影响
            Demo 内存状态，不会操作真实硬件或云端数据。
          </p>
          <div class="modal-actions">
            <button class="secondary-button" @click="clearPrompt = false">
              取消</button
            ><button
              class="primary-button"
              @click="
                emit('clear');
                clearPrompt = false;
              "
            >
              清空演示数据
            </button>
          </div>
        </section>
      </dialog></Teleport
    >
  </section>
</template>
