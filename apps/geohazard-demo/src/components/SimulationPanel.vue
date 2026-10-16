<script setup lang="ts">
import {
  Leaf,
  CloudRain,
  Mountain,
  TriangleAlert,
  SlidersHorizontal,
  RotateCcw,
} from "lucide-vue-next";
import type { SimulationState, SensorValues } from "../simulation";
const props = defineProps<{ state: SimulationState }>();
const emit = defineEmits<{
  scenario: [scenario: "A" | "B" | "C" | "D"];
  sensor: [sensor: keyof SensorValues, value: number];
}>();
const scenes = [
  { id: "A", name: "正常监测", icon: Leaf, tone: "green", score: 18 },
  { id: "B", name: "持续暴雨", icon: CloudRain, tone: "yellow", score: 46 },
  { id: "C", name: "位移异常", icon: Mountain, tone: "orange", score: 72 },
  { id: "D", name: "极端灾害", icon: TriangleAlert, tone: "red", score: 91 },
] as const;
const fields = [
  { key: "moisture", label: "相对湿润度", max: 100, step: 1, unit: "%" },
  { key: "tilt", label: "地表倾角", max: 45, step: 0.1, unit: "°" },
  { key: "vibration", label: "微振动", max: 2, step: 0.01, unit: "g" },
  { key: "rain", label: "降雨强度", max: 100, step: 1, unit: "mm/h" },
  { key: "crack", label: "裂缝增量", max: 20, step: 0.1, unit: "mm" },
] as const;
function input(key: keyof SensorValues, e: Event) {
  const v = Number((e.target as HTMLInputElement).value);
  if (Number.isFinite(v)) emit("sensor", key, v);
}
</script>
<template>
  <section class="panel simulation-panel" id="simulator">
    <div class="panel-heading">
      <div>
        <h2>灾害演化模拟</h2>
        <p>从一次降雨，观察边坡的每一次变化。</p>
      </div>
      <SlidersHorizontal :size="17" class="muted" />
    </div>
    <div class="scenario-grid">
      <button
        v-for="scene in scenes"
        :key="scene.id"
        :class="[
          'scenario-button',
          scene.tone,
          { selected: state.scenario === scene.id },
        ]"
        :aria-pressed="state.scenario === scene.id"
        @click="emit('scenario', scene.id)"
      >
        <component :is="scene.icon" :size="19" /><span>{{ scene.name }}</span
        ><small>风险约 {{ scene.score }}</small>
      </button>
    </div>
    <div class="controls-heading">
      <span
        >传感器参数
        <small v-if="state.scenario === 'custom'">手动模式</small></span
      ><button
        class="text-button"
        @click="
          emit('scenario', state.scenario === 'custom' ? 'A' : state.scenario)
        "
      >
        <RotateCcw :size="12" />恢复场景值
      </button>
    </div>
    <div class="sensor-sliders">
      <label v-for="field in fields" :key="field.key"
        ><span>{{ field.label }}</span
        ><input
          type="range"
          :min="0"
          :max="field.max"
          :step="field.step"
          :value="state.sensors[field.key]"
          :aria-label="field.label + '滑块'"
          :style="{
            '--fill': (state.sensors[field.key] / field.max) * 100 + '%',
          }"
          @input="input(field.key, $event)"
        />
        <div class="number-input">
          <input
            type="number"
            :min="0"
            :max="field.max"
            :step="field.step"
            :value="state.sensors[field.key]"
            :aria-label="field.label + '数值'"
            @change="input(field.key, $event)"
          /><span>{{ field.unit }}</span>
        </div></label
      >
    </div>
  </section>
</template>
