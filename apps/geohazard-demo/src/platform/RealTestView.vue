<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, errorMessage } from "./api";

const emit = defineEmits<{ back: [] }>();
const acceleration = ["ax", "ay", "az"] as const;
const angularRate = ["gx", "gy", "gz"] as const;
const soilChannels = [
  { key: "top_raw", label: "坡顶" },
  { key: "middle_raw", label: "坡中" },
  { key: "toe_raw", label: "坡脚" },
] as const;
type Imu = { id: "top" | "toe"; valid: boolean } & Record<
  (typeof acceleration)[number] | (typeof angularRate)[number], number | null
>;
type Sample = {
  telemetry_id: string;
  arrival_order: number;
  received_at: string;
  boot_id: number;
  seq: number;
  uptime_ms: number;
  time_synced: boolean;
  timestamp_ms: number | null;
  imu: Imu[];
  soil_raw: Record<(typeof soilChannels)[number]["key"], number | null>;
};
type BootObservation = {
  boot_id: number;
  source: string;
  scope: string;
  samples: number;
  store: "test_store" | "platform_db";
  first_received_at: string;
  last_received_at: string;
};
type StorageDescriptor = {
  engine: string;
  store_id: string;
  isolated: boolean;
  path_kind: string;
  store_name: string;
  platform_db_shared: boolean;
};
type PlatformDbProbe = {
  performed: boolean;
  mode: string;
  unexpected_rows_detected: boolean;
  warning: string | null;
  counts: Record<string, number>;
};
type Status = {
  latest: Sample | null;
  recent: Sample[];
  observed_at: string;
  arrival_age_seconds: number | null;
  stale: boolean;
  telemetry_count: number;
  soil_window: { status: "INSUFFICIENT_WINDOW" };
  formal_alarm_count: number;
  storage?: StorageDescriptor;
  observed_boot_ids?: BootObservation[];
  platform_db_probe?: PlatformDbProbe;
};

const data = ref<Status | null>(null);
const error = ref("");
const browserObservedAt = ref("");
const browserTimeFormat = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
  hourCycle: "h23", timeZoneName: "shortOffset",
});
const latest = computed(() => data.value?.latest);
const stale = computed(() => !!error.value || !!data.value?.stale);
const statusTone = computed(() => (error.value ? "offline" : !data.value || !latest.value ? "waiting" : stale.value ? "stale" : "fresh"));
const controller = new AbortController();
let nextPoll: ReturnType<typeof setTimeout> | undefined;

async function poll() {
  try {
    data.value = await api.get<Status>("/real-test/status", controller.signal);
    browserObservedAt.value = browserTimeFormat.format(new Date());
    error.value = "";
  } catch (cause) {
    if (!controller.signal.aborted) error.value = errorMessage(cause);
  } finally {
    if (!controller.signal.aborted) nextPoll = setTimeout(poll, 1000);
  }
}
onMounted(poll);
onUnmounted(() => {
  controller.abort();
  clearTimeout(nextPoll);
});
</script>

<template>
  <main class="real-test-view" data-testid="real-test-view">
    <header class="real-test-header">
      <div class="rt-title-group">
        <div class="rt-eyebrow">
          <span>智哨防灾 · 真实测试观测台</span>
          <span class="rt-site-code">NODE01-STAGE23-TEST</span>
          <span class="source-badge real">REAL</span>
          <span class="source-badge test-only">TEST_ONLY</span>
        </div>
        <h1>NODE-01-REAL-TEST</h1>
      </div>
      <button class="secondary-button" @click="emit('back')">返回平台</button>
    </header>

    <div :class="['rt-status-bar', statusTone]" role="status" data-testid="real-test-status">
      <div class="rt-status-main">
        <i :class="['status-dot', { paused: statusTone === 'stale', muted: statusTone === 'waiting', offline: statusTone === 'offline' }]" />
        <strong>{{ error ? '平台连接中断，保留最后一次观测' : !data ? '正在读取真实测试状态' :
          !latest ? '等待首条有效测试遥测' : stale ? '数据已过期' : '测试遥测新鲜' }}</strong>
      </div>
      <div class="rt-status-meta">
        <span>累计有效收包 {{ data?.telemetry_count == null ? '—' : data.telemetry_count }}</span>
        <span>{{ error ? '上次观测到达年龄' : '到达年龄' }} {{ data?.arrival_age_seconds == null ? '—' : `${Math.floor(data.arrival_age_seconds)} 秒` }}</span>
      </div>
    </div>

    <p v-if="error" class="inline-error">{{ error }}</p>
    <p v-if="data?.platform_db_probe?.unexpected_rows_detected" role="alert" class="inline-error">
      只读探测警告：主库 platform.sqlite3 中存在既有 NODE-01-REAL-TEST / NODE01-STAGE23-TEST 记录（未混入本页读数，未自动迁移、删除或改写）。
    </p>

    <section class="panel rt-section" aria-label="链路与存储元数据">
      <dl class="rt-spec-grid">
        <div>
          <dt>数据存储隔离</dt>
          <dd data-testid="real-test-storage">{{ data?.storage?.isolated ? `专用实测库（${data.storage.store_name} · ${data.storage.path_kind}）` : '未确认隔离' }}</dd>
        </div>
        <div>
          <dt>最新 seq / 收包顺序</dt>
          <dd>{{ latest ? `seq ${latest.seq} · 第 ${latest.arrival_order} 包 · boot ${latest.boot_id} · uptime ${latest.uptime_ms} ms` : '—' }}</dd>
        </div>
        <div>
          <dt>正式告警</dt>
          <dd data-testid="real-test-formal-alarm-count">{{ data?.formal_alarm_count == null ? '—' : data.formal_alarm_count }}</dd>
        </div>
        <div>
          <dt>最近有效收包（平台主机 UTC）</dt>
          <dd>{{ latest?.received_at ?? '—' }}</dd>
        </div>
        <div>
          <dt>服务端观察时间（平台主机 UTC）</dt>
          <dd>{{ data?.observed_at ?? '—' }}</dd>
        </div>
        <div>
          <dt>浏览器本机对照时间（收到状态时）</dt>
          <dd>{{ browserObservedAt || '—' }}</dd>
        </div>
        <div>
          <dt>设备时钟</dt>
          <dd>{{ latest ? (latest.time_synced ? latest.timestamp_ms : '未同步 · timestamp_ms=null') : '—' }}</dd>
        </div>
      </dl>
    </section>

    <section :class="['rt-readings', { 'stale-readings': stale }]" aria-label="最近一次测试读数">
      <div class="panel rt-section">
        <div class="rt-card-head">
          <div>
            <h2>土壤 ADC raw</h2>
            <p>窗口不足（1–3 包无法形成 120 s 窗口），仅展示 raw，不以 ΔVWC 为已验证结果，不换算绝对 %VWC。</p>
          </div>
          <span class="source-badge test-only">{{ data?.soil_window.status ?? 'INSUFFICIENT_WINDOW' }}</span>
        </div>
        <dl class="rt-soil-grid">
          <div v-for="channel in soilChannels" :key="channel.key" class="rt-soil-cell">
            <dt>{{ channel.label }} <code>{{ channel.key }}</code></dt>
            <dd class="rt-soil-val">{{ latest?.soil_raw[channel.key] ?? '—' }}</dd>
            <dd class="rt-soil-state">{{ !latest ? '等待收包' : latest.soil_raw[channel.key] != null ? '有值' : '缺样' }}</dd>
          </div>
        </dl>
      </div>

      <div class="panel rt-section">
        <div class="rt-card-head">
          <div>
            <h2>IMU 原始物理量 · 未校准 / 轴未映射</h2>
            <p>保留原始三轴加速度与角速度读数，缺测显示为「—」，不补零。</p>
          </div>
          <span class="source-badge">RAW · 未校准</span>
        </div>
        <div class="platform-table-scroll">
          <table class="platform-table">
            <thead><tr><th>位置</th><th>有效性</th><th v-for="axis in acceleration" :key="axis" class="num">{{ axis }} (m/s²)</th><th v-for="axis in angularRate" :key="axis" class="num">{{ axis }} (°/s)</th></tr></thead>
            <tbody>
              <tr v-for="imu in latest?.imu" :key="imu.id">
                <th scope="row">{{ imu.id }}</th><td>{{ imu.valid ? '有效' : '无效' }}</td>
                <td v-for="axis in acceleration" :key="axis" class="num">{{ imu[axis] ?? '—' }}</td>
                <td v-for="axis in angularRate" :key="axis" class="num">{{ imu[axis] ?? '—' }}</td>
              </tr>
              <tr v-if="!latest"><td colspan="8" class="rt-empty-cell">等待有效 IMU 读数</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="panel rt-section">
      <div class="rt-card-head">
        <div>
          <h2>最近接收记录</h2>
          <p>按平台首次入库顺序倒排，首行是最近有效收包。</p>
        </div>
        <span class="rt-count-tag">{{ data?.recent?.length ?? 0 }} 条</span>
      </div>
      <div class="platform-table-scroll">
        <table class="platform-table">
          <thead><tr><th class="num">收包顺序</th><th class="num">boot_id</th><th class="num">seq</th><th class="num">uptime_ms</th><th>平台接收时间（UTC）</th></tr></thead>
          <tbody>
            <tr v-for="row in data?.recent" :key="row.telemetry_id">
              <td class="num">{{ row.arrival_order }}</td><td class="num">{{ row.boot_id }}</td><td class="num">{{ row.seq }}</td>
              <td class="num">{{ row.uptime_ms }}</td><td>{{ row.received_at }}</td>
            </tr>
            <tr v-if="!data?.recent?.length"><td colspan="5" class="rt-empty-cell">尚无有效测试收包</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="data?.observed_boot_ids?.length" class="panel rt-section">
      <div class="rt-card-head">
        <div>
          <h2>已观察 boot_id（按来源库区分，仅只读核对，非分配）</h2>
          <p>用于核对实测专用库与主库历史隔离状态。</p>
        </div>
      </div>
      <div class="platform-table-scroll">
        <table class="platform-table">
          <thead><tr><th>来源库</th><th class="num">boot_id</th><th>source</th><th>scope</th><th class="num">样本数</th><th>最近接收（UTC）</th></tr></thead>
          <tbody>
            <tr v-for="item in data.observed_boot_ids" :key="`${item.store}-${item.boot_id}-${item.source}-${item.scope}`">
              <td>{{ item.store === 'test_store' ? '专用测试库 (test_store)' : '主库只读历史 (platform_db)' }}</td>
              <td class="num">{{ item.boot_id }}</td>
              <td><span :class="['source-badge', item.source.toLowerCase()]">{{ item.source }}</span></td>
              <td><span class="source-badge scope-badge">{{ item.scope }}</span></td>
              <td class="num">{{ item.samples }}</td>
              <td>{{ item.last_received_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<style scoped>
.real-test-view {
  width: min(100%, 1160px);
  margin: 0 auto;
  padding: 20px 24px 40px;
}
.real-test-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.rt-title-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.rt-eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
}
.rt-site-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-badge);
  padding: 2px 7px;
}
.rt-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-radius: var(--radius-card);
  border: 1px solid var(--border);
  background: var(--surface);
  margin-bottom: 14px;
  font-size: 13px;
}
.rt-status-bar.fresh {
  border-color: var(--status-normal-border);
  background: var(--status-normal-bg);
  color: var(--status-normal);
}
.rt-status-bar.stale {
  border-color: var(--status-warn-border);
  background: var(--status-warn-bg);
  color: var(--status-warn);
}
.rt-status-bar.offline {
  border-color: var(--status-danger-border);
  background: var(--status-danger-bg);
  color: var(--status-danger);
}
.rt-status-bar.waiting {
  color: var(--text-secondary);
}
.rt-status-main {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rt-status-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  flex-wrap: wrap;
}
.rt-section {
  margin-bottom: 16px;
}
.rt-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  flex-wrap: wrap;
}
.rt-card-head h2 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.rt-card-head p {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 3px;
  line-height: 1.45;
}
.rt-count-tag {
  font-size: 12px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.rt-spec-grid {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.rt-spec-grid > div {
  padding: 10px 14px;
  border-right: 1px solid var(--border-subtle);
  border-bottom: 1px solid var(--border-subtle);
  min-width: 0;
}
.rt-spec-grid > div:nth-child(3n) {
  border-right: 0;
}
.rt-spec-grid dt {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.rt-spec-grid dd {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.rt-soil-grid {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.rt-soil-cell {
  padding: 14px 16px;
  border-right: 1px solid var(--border-subtle);
}
.rt-soil-cell:last-child {
  border-right: 0;
}
.rt-soil-cell dt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.rt-soil-cell code {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
}
.rt-soil-val {
  margin: 6px 0 4px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.rt-soil-state {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
}
.rt-empty-cell {
  text-align: center;
  color: var(--text-muted);
  padding: 18px 12px;
}
.stale-readings,
.stale-readings :is(dt, dd, td, th, .rt-soil-val) {
  color: var(--text-muted);
}
@media (max-width: 900px) {
  .rt-spec-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .rt-spec-grid > div:nth-child(3n) {
    border-right: 1px solid var(--border-subtle);
  }
  .rt-spec-grid > div:nth-child(2n) {
    border-right: 0;
  }
}
@media (max-width: 640px) {
  .real-test-view {
    padding: 14px 12px 32px;
  }
  .rt-spec-grid,
  .rt-soil-grid {
    grid-template-columns: 1fr;
  }
  .rt-spec-grid > div,
  .rt-soil-cell {
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }
  .rt-soil-cell:last-child {
    border-bottom: 0;
  }
}
</style>
