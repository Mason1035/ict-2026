<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Mountain,
  LayoutDashboard,
  Box,
  Network,
  Bell,
  CircleHelp,
  ChevronRight,
  ChevronDown,
  Radio,
  Pause,
  Play,
  SkipForward,
  RotateCcw,
  Info,
  ShieldCheck,
  ArrowUpRight,
  X,
  TriangleAlert,
  Command,
  Clock3,
} from "lucide-vue-next";
import { useSimulation } from "./store/useSimulation";
import type { SensorValues } from "./simulation";
import TerrainScene from "./components/TerrainScene.vue";
import RiskTrend from "./components/RiskTrend.vue";
import AnimatedNumber from "./components/AnimatedNumber.vue";
import SensorCard from "./components/SensorCard.vue";
import NetworkPanel from "./components/NetworkPanel.vue";
import SimulationPanel from "./components/SimulationPanel.vue";
import EventCenter from "./components/EventCenter.vue";
const { state, dispatch } = useSimulation();
const guide = ref<HTMLDialogElement>(),
  breakdown = ref<HTMLDialogElement>();
const activeNav = ref("overview");
const levelMeta = {
  low: {
    name: "低风险",
    en: "Low risk",
    color: "#39866a",
    message: "边坡状态稳定",
    description: "多模态指标处于稳定区间，持续监测中。",
  },
  moderate: {
    name: "中风险",
    en: "Moderate risk",
    color: "#c09a3e",
    message: "降雨影响持续增强",
    description: "关注湿度与倾角变化，建议加强巡检。",
  },
  high: {
    name: "高风险",
    en: "High risk",
    color: "#d08043",
    message: "边坡位移异常",
    description: "本地预警已触发，请关注坡面位移与裂缝。",
  },
  critical: {
    name: "紧急预警",
    en: "Critical risk",
    color: "#bd514c",
    message: "滑坡风险显著升高",
    description: "演示紧急预警已触发，请查看告警详情。",
  },
};
const riskMeta = computed(() => levelMeta[state.value.risk.level]);
const connection = computed(() =>
  state.value.network === "OFFLINE"
    ? "离线保护"
    : state.value.network === "RECOVERING"
      ? "恢复补传"
      : state.value.activePath === "lora"
        ? "LoRa 备用链路"
        : "Wi-Fi 主链路",
);
const pending = computed(
  () => state.value.queue.filter((x) => x.status !== "Synced").length,
);
const time = computed(
  () =>
    `${String(Math.floor(state.value.elapsedSeconds / 3600)).padStart(2, "0")}:${String(Math.floor(state.value.elapsedSeconds / 60) % 60).padStart(2, "0")}:${String(state.value.elapsedSeconds % 60).padStart(2, "0")}`,
);
const fields = [
  {
    name: "moisture",
    label: "土壤湿度",
    unit: "%",
    source: "SEN0193 · ADS1115",
    max: 100,
    decimals: 0,
  },
  {
    name: "tilt",
    label: "地表倾斜",
    unit: "°",
    source: "ICM-42688-P · 双 IMU",
    max: 45,
    decimals: 1,
  },
  {
    name: "vibration",
    label: "微振动",
    unit: "g",
    source: "ICM-42688-P · 聚合",
    max: 2,
    decimals: 2,
  },
  {
    name: "rain",
    label: "降雨强度",
    unit: "mm/h",
    source: "气象场景",
    max: 100,
    decimals: 0,
    simulated: true,
  },
  {
    name: "crack",
    label: "裂缝变化",
    unit: "mm",
    source: "位移场景",
    max: 20,
    decimals: 1,
    simulated: true,
  },
] as const;
const sensorLabels: Record<keyof SensorValues, string> = {
  moisture: "相对湿润度",
  tilt: "地表倾角",
  vibration: "微振动",
  rain: "场景降雨",
  crack: "场景裂缝",
};
const displayContributions = computed(() => {
  const total = Math.round(state.value.risk.score * 100);
  const rows = state.value.risk.contributions.map((item) => ({
    ...item,
    cents: Math.floor(item.points * 100),
    fraction: item.points * 100 - Math.floor(item.points * 100),
  }));
  const remaining = total - rows.reduce((sum, item) => sum + item.cents, 0);
  const ranked = [...rows].sort((a, b) => b.fraction - a.fraction);
  for (let i = 0; i < remaining; i++) ranked[i % ranked.length].cents++;
  return rows.map((item) => ({ ...item, points: item.cents / 100 }));
});
const navItems = [
  { id: "overview", name: "监测总览", icon: LayoutDashboard },
  { id: "twin", name: "数字孪生", icon: Box },
  { id: "network", name: "通信容灾", icon: Network },
  { id: "events", name: "告警与事件", icon: Bell },
] as const;
function navigate(id: string) {
  activeNav.value = id;
  document
    .getElementById(id)
    ?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "start",
    });
}
</script>
<template>
  <div class="app-shell" :style="{ '--risk-color': riskMeta.color }">
    <aside class="sidebar">
      <a
        class="brand-mark"
        href="#overview"
        aria-label="智哨防灾首页"
        @click.prevent="navigate('overview')"
        ><Mountain :size="27" :stroke-width="1.6"
      /></a>
      <div class="sidebar-rule" />
      <nav aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.id"
          :class="['nav-button', { active: activeNav === item.id }]"
          :aria-label="item.name"
          :title="item.name"
          @click="navigate(item.id)"
        >
          <component :is="item.icon" :size="21" /><span class="nav-tooltip">{{
            item.name
          }}</span
          ><i
            v-if="item.id === 'events' && state.risk.score >= 60"
            class="nav-alert"
          />
        </button>
      </nav>
      <div class="sidebar-bottom">
        <button
          class="nav-button"
          aria-label="演示说明"
          title="演示说明"
          @click="guide?.showModal()"
        >
          <CircleHelp :size="20" /></button
        ><span class="avatar" title="演示工作空间">ZM</span>
      </div>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <div class="workspace-brand">
          智哨防灾 <span>/</span><span class="breadcrumb">指挥中心</span
          ><ChevronDown :size="13" />
        </div>
        <div class="topbar-right">
          <span class="demo-badge">DEMO</span
          ><span class="topbar-divider" /><span class="live-status"
            ><i :class="['status-dot', { paused: !state.running }]" />{{
              state.running ? "实时仿真" : "仿真已暂停"
            }}</span
          ><button
            class="icon-button guide-button"
            aria-label="了解本演示"
            @click="guide?.showModal()"
          >
            <Info :size="17" />
          </button>
        </div>
      </header>
      <main id="overview">
        <div class="page-heading">
          <div>
            <div class="product-name">GEO HAZARD INTELLIGENCE</div>
            <h1>数字孪生指挥中心<span>监测总览</span></h1>
            <p>感知细微变化，让预警先于灾害。</p>
          </div>
          <div class="site-selector">
            <span class="site-icon"><Mountain :size="19" /></span>
            <div>
              <strong>青岚山 · 示范边坡</strong
              ><small>程序化模拟地形 / NODE-01</small>
            </div>
            <ChevronDown :size="14" />
          </div>
        </div>
        <div class="simulation-bar">
          <div class="simulation-status">
            <Radio :size="15" /><span>模拟引擎</span
            ><span class="status-pip" /><strong>{{
              state.running ? "运行中" : "已暂停"
            }}</strong
            ><span class="bar-divider" /><Clock3 :size="13" /><time
              data-testid="simulation-time"
              >{{ time }}</time
            >
          </div>
          <div class="playback-controls">
            <div class="speed-control" aria-label="仿真倍速">
              <button
                v-for="speed in [1, 2, 4] as const"
                :key="speed"
                :class="{ selected: state.speed === speed }"
                :aria-pressed="state.speed === speed"
                @click="dispatch({ type: 'set-speed', speed })"
              >
                {{ speed }}×
              </button>
            </div>
            <span class="bar-divider" /><button
              class="playback-button"
              :aria-label="state.running ? '暂停仿真' : '继续仿真'"
              @click="
                dispatch({ type: 'set-running', running: !state.running })
              "
            >
              <Pause v-if="state.running" :size="14" /><Play
                v-else
                :size="14"
              />{{ state.running ? "暂停" : "继续" }}</button
            ><button
              class="icon-button"
              aria-label="推进一步"
              title="推进一步（1 秒）"
              @click="dispatch({ type: 'step' })"
            >
              <SkipForward :size="16" /></button
            ><button
              class="icon-button reset-button"
              aria-label="重置演示"
              title="重置所有模拟状态"
              @click="dispatch({ type: 'reset' })"
            >
              <RotateCcw :size="15" />
            </button>
          </div>
        </div>
        <div v-if="state.risk.score >= 60" class="risk-notice" role="status">
          <TriangleAlert :size="17" /><strong>{{ riskMeta.name }}</strong
          ><span
            >{{ riskMeta.message }}。{{
              state.network === "OFFLINE"
                ? "网络离线，本地预警继续有效。"
                : "查看告警中心，了解触发指标。"
            }}</span
          ><button @click="navigate('events')">
            查看事件<ArrowUpRight :size="14" />
          </button>
        </div>
        <div class="hero-grid">
          <section class="panel terrain-panel" id="twin">
            <div class="terrain-heading">
              <div>
                <Box :size="17" />
                <h2>边坡数字孪生</h2>
                <span class="mini-badge">3D</span>
              </div>
              <span class="terrain-online"
                ><i class="status-dot" />5 路模拟遥测</span
              >
            </div>
            <div class="terrain-viewport">
              <TerrainScene
                :score="state.risk.score"
                :sensors="state.sensors"
                :running="state.running"
                :elapsed="state.elapsedSeconds"
                :reset-key="state.bootId"
                :gateway-online="state.communication.gateway"
              />
            </div>
          </section>
          <section class="panel risk-panel">
            <div class="risk-heading">
              <h2>综合风险评估</h2>
              <button
                class="icon-button"
                aria-label="查看风险评分分解"
                title="查看演示评分分解"
                @click="breakdown?.showModal()"
              >
                <Info :size="15" />
              </button>
            </div>
            <div class="risk-overview">
              <div class="risk-number">
                <AnimatedNumber :value="Math.floor(state.risk.score)" /><span
                  >/ 100</span
                >
              </div>
              <svg class="risk-orbit" viewBox="0 0 120 120" aria-hidden="true">
                <circle
                  cx="60"
                  cy="60"
                  r="46"
                  fill="none"
                  stroke="#edf1eb"
                  stroke-width="5"
                />
                <circle
                  cx="60"
                  cy="60"
                  r="46"
                  fill="none"
                  :stroke="riskMeta.color"
                  stroke-width="5"
                  stroke-linecap="round"
                  :stroke-dasharray="`${(state.risk.score / 100) * 289} 289`"
                  transform="rotate(-90 60 60)"
                />
                <circle cx="60" cy="60" r="34" fill="#f6f8f4" />
                <path
                  v-if="state.risk.level === 'low'"
                  d="m48 60 8 8 17-18"
                  fill="none"
                  :stroke="riskMeta.color"
                  stroke-width="3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path
                  v-else
                  d="M60 44v19m0 10v1"
                  :stroke="riskMeta.color"
                  stroke-width="3"
                  stroke-linecap="round"
                />
              </svg>
            </div>
            <div class="risk-level">
              <span
                :style="{
                  color: riskMeta.color,
                  background: riskMeta.color + '12',
                }"
                ><i />{{ riskMeta.name }}</span
              ><small>{{ riskMeta.en }}</small>
            </div>
            <h3>{{ riskMeta.message }}</h3>
            <p class="risk-description">{{ riskMeta.description }}</p>
            <div class="trend-header">
              <span>风险历史趋势</span
              ><button
                class="text-button"
                @click="dispatch({ type: 'clear-history' })"
              >
                清空历史
              </button>
            </div>
            <RiskTrend :points="state.riskHistory" :color="riskMeta.color" />
            <div class="risk-footnote">
              <ShieldCheck :size="12" />确定性演示评分 · 非实测预测模型
            </div>
          </section>
        </div>
        <div class="section-label">
          <h2>多模态传感器遥测</h2>
          <span
            ><i class="status-dot" />同源状态，联动更新
            <span class="label-note">全部为模拟值</span></span
          >
        </div>
        <section class="sensor-grid" aria-label="传感器实时读数">
          <SensorCard
            v-for="field in fields"
            :key="field.name"
            v-bind="field"
            :value="state.sensors[field.name]"
            :values="state.sensorHistory.map((p) => p[field.name])"
          />
        </section>
        <div class="operations-grid">
          <NetworkPanel
            :state="state"
            @link="(link, value) => dispatch({ type: 'set-link', link, value })"
          /><SimulationPanel
            :state="state"
            @scenario="
              (scenario) => dispatch({ type: 'set-scenario', scenario })
            "
            @sensor="
              (sensor, value) => dispatch({ type: 'set-sensor', sensor, value })
            "
          />
        </div>
        <EventCenter
          :state="state"
          @clear="dispatch({ type: 'clear-demo-data' })"
        />
        <footer class="page-footer">
          <div>
            <Mountain :size="15" /><span>智哨防灾</span
            ><span>感知 · 分析 · 预警</span>
          </div>
          <span>DEMO ONLY · 模拟地形与遥测 · 未连接真实设备或云端</span>
        </footer>
      </main>
      <div class="bottom-status">
        <span><i class="status-dot" />NODE-01 本地引擎</span
        ><span
          >{{ connection
          }}<span v-if="pending"> · {{ pending }} 条待补传</span></span
        ><span><Command :size="11" />交互演示环境</span>
      </div>
    </div>
    <dialog ref="guide" class="modal native-modal">
      <button
        class="modal-close icon-button"
        aria-label="关闭说明"
        @click="guide?.close()"
      >
        <X :size="18" /></button
      ><span class="modal-brand"><Mountain :size="25" /></span>
      <h2>从感知，到预警。</h2>
      <p>
        这里是智哨防灾的交互演示。尝试四种灾害场景，拖动传感器参数，再切断通信，观察本地计算与恢复补传。
      </p>
      <div class="guide-steps">
        <div>
          <span>01</span>
          <p>
            <strong>探索边坡</strong>拖动旋转地形，点击监测点，切换风险热力。
          </p>
        </div>
        <div>
          <span>02</span>
          <p><strong>模拟风险</strong>选择持续暴雨、位移异常或极端灾害。</p>
        </div>
        <div>
          <span>03</span>
          <p>
            <strong>验证容灾</strong>关闭 Wi-Fi 和 LoRa，推进采样，再恢复
            Wi-Fi。
          </p>
        </div>
      </div>
      <p class="disclosure">
        地形、传感器值、评分、缓存和云端送达均为浏览器模拟。湿度为相对湿润度；降雨和裂缝为场景信号。振动展示单位
        g（1g = 9.80665 m/s²）。本 Demo 不代表正式算法已经训练、验证或完成部署。
      </p>
      <button class="primary-button" @click="guide?.close()">开始体验</button>
    </dialog>
    <dialog ref="breakdown" class="modal native-modal">
      <button
        class="modal-close icon-button"
        aria-label="关闭评分分解"
        @click="breakdown?.close()"
      >
        <X :size="18" />
      </button>
      <h2>演示风险评分分解</h2>
      <p>
        五个输入分别归一化、加权，之后使用同一条单调校准曲线。所有场景与手动参数使用相同计算规则。
      </p>
      <div class="contribution-list">
        <div v-for="item in displayContributions" :key="item.sensor">
          <span>{{ sensorLabels[item.sensor] }}</span
          ><span class="contribution-bar"
            ><i :style="{ width: item.points + '%' }" /></span
          ><strong>{{ item.points.toFixed(2) }}</strong>
        </div>
      </div>
      <div class="contribution-total">
        <span>总分</span
        ><strong>{{ state.risk.score.toFixed(2) }} / 100</strong>
      </div>
      <p class="disclosure">
        分解项按最终得分同比例分配，合计与总分一致。这是一套为产品演示校准的模型，正式风险阈值和归一化仍需现场标定。
      </p>
    </dialog>
  </div>
</template>
