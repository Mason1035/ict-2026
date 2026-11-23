<script setup lang="ts">
import { computed } from "vue";
import {
  Cpu,
  Wifi,
  Radio,
  Router,
  Server,
  Cloud,
  HardDrive,
  ShieldCheck,
  ArrowRight,
  Info,
  Bell,
  Database,
} from "lucide-vue-next";
import type { SimulationState } from "../simulation";
const props = defineProps<{ state: SimulationState }>();
const emit = defineEmits<{
  link: [link: keyof SimulationState["communication"], value: boolean];
}>();
const comm = computed(() => props.state.communication);
const wifi = computed(() => props.state.activePath === "wifi");
const lora = computed(() => props.state.activePath === "lora");
const online = computed(() => props.state.activePath !== null);
const pending = computed(
  () => props.state.queue.filter((x) => x.status !== "Synced").length,
);
const status = computed(() =>
  props.state.network === "RECOVERING"
    ? "正在恢复补传"
    : wifi.value
      ? "Wi-Fi 主链路运行"
      : lora.value
        ? "LoRa 中继接管"
        : "离线保护运行",
);
const switches = [
  { key: "wifi", label: "NODE Wi-Fi" },
  { key: "lora", label: "NODE LoRa" },
  { key: "gateway", label: "GW-01 上行" },
  { key: "mqtt", label: "MQTT 服务" },
  { key: "atlas", label: "Atlas 服务" },
  { key: "cloud", label: "云端接收" },
] as const;
</script>
<template>
  <section class="panel network-panel" id="network">
    <div class="panel-heading">
      <div>
        <h2>通信链路与容灾</h2>
        <p>每一条数据，都有回家的路。</p>
      </div>
      <span :class="['tag', online ? 'tag-green' : 'tag-amber']"
        ><i />{{
          state.network === "RECOVERING"
            ? "补传中"
            : online
              ? "链路可用"
              : "离线"
        }}</span
      >
    </div>
    <div class="network-diagram">
      <div class="flow-device node">
        <Cpu :size="22" /><strong>NODE-01</strong><small>边缘监测节点</small>
      </div>
      <div class="network-branches">
        <div :class="['flow-branch', { active: wifi }]">
          <span class="flow-line" /><Wifi :size="15" /><span>Wi-Fi / MQTT</span
          ><span class="flow-line" /><ArrowRight :size="12" />
        </div>
        <div :class="['flow-branch', { active: lora }]">
          <span class="flow-line" /><Radio :size="15" /><span>LoRa</span
          ><span class="gateway-inline"><Router :size="15" />GW-01</span
          ><span class="flow-line" /><ArrowRight :size="12" />
        </div>
      </div>
      <div :class="['flow-device', { connected: online }]">
        <Server :size="21" /><strong>Atlas</strong><small>边缘计算</small>
      </div>
      <div :class="['flow-cloud-line', { active: online }]">
        <span class="flow-line" /><ArrowRight :size="12" />
      </div>
      <div :class="['flow-device cloud', { connected: online }]">
        <Cloud :size="22" /><strong>Huawei Cloud</strong
        ><small>云端接收模拟</small>
      </div>
    </div>
    <div
      :class="['local-flow', { engaged: !online }]"
      aria-label="本地自治流程"
    >
      <div>
        <Cpu :size="14" /><span>本地风险引擎</span><i class="local-live" />
      </div>
      <span class="local-connector" />
      <div :class="{ alarming: state.risk.score >= 60 }">
        <Bell :size="14" /><span>本地告警</span><i />
      </div>
      <span class="local-connector" />
      <div><HardDrive :size="14" /><span>MicroSD 模拟</span><i /></div>
      <span class="local-connector" />
      <div>
        <Database :size="14" /><span>离线队列</span
        ><strong>{{ pending }}</strong>
      </div>
    </div>
    <div :class="['network-summary', { offline: !online }]">
      <ShieldCheck v-if="online" :size="16" /><HardDrive
        v-else
        :size="16"
      /><span>{{ status }}</span
      ><span class="summary-meta">{{
        online
          ? state.network === "RECOVERING"
            ? pending + " 条待补传"
            : "当前采样实时传输"
          : "本地计算 · 本地告警 · 演示缓存"
      }}</span>
    </div>
    <div class="network-switches">
      <label v-for="item in switches" :key="item.key"
        ><span>{{ item.label }}</span
        ><button
          class="switch"
          role="switch"
          :aria-checked="comm[item.key]"
          :aria-label="item.label"
          :class="{ on: comm[item.key] }"
          @click="emit('link', item.key, !comm[item.key])"
        >
          <i /></button
      ></label>
    </div>
    <p class="network-note">
      <Info :size="12" /> LoRa 仅连接 NODE 与网关；上行及服务可用时才模拟送达。
    </p>
  </section>
</template>
