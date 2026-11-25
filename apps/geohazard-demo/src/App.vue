<script setup lang="ts">
import { ref, defineAsyncComponent } from "vue";
import PlatformDashboard from "./PlatformDashboard.vue";
const DemoDashboard = defineAsyncComponent(() => import("./DemoDashboard.vue"));
const ResearchReplay = defineAsyncComponent(() => import("./research/ResearchReplay.vue"));
const RealTestView = defineAsyncComponent(() => import("./platform/RealTestView.vue"));
const localDemo = ref(new URLSearchParams(window.location.search).get("mode") === "local");
const research = ref(new URLSearchParams(window.location.search).get("mode") === "research");
const realTest = ref(new URLSearchParams(window.location.search).get("mode") === "real-test");
function changeMode(local: boolean) {
  research.value = false;
  realTest.value = false;
  localDemo.value = local;
  const url = new URL(window.location.href);
  if (local) url.searchParams.set("mode", "local");
  else url.searchParams.delete("mode");
  window.history.replaceState({}, "", url);
}
function openResearch() {
  localDemo.value = false;
  realTest.value = false;
  research.value = true;
  const url = new URL(window.location.href);
  url.searchParams.set("mode", "research");
  window.history.replaceState({}, "", url);
}
function openRealTest() {
  localDemo.value = false;
  research.value = false;
  realTest.value = true;
  const url = new URL(window.location.href);
  url.searchParams.set("mode", "real-test");
  window.history.replaceState({}, "", url);
  window.scrollTo(0, 0);
}
</script>
<template>
  <div v-if="localDemo" class="local-demo-return">
    <span class="source-badge demo">DEMO</span>
    <span>独立本地仿真演示 · 未连接真实设备或后端，数据仅存在于浏览器内存</span>
    <button class="secondary-button" @click="changeMode(false)">返回后端平台</button>
  </div>
  <RealTestView v-if="realTest" @back="changeMode(false)" />
  <ResearchReplay v-else-if="research" @back="changeMode(false)" />
  <DemoDashboard v-else-if="localDemo" />
  <PlatformDashboard v-else @local-demo="changeMode(true)" @research="openResearch" @real-test="openRealTest" />
</template>
<style>
.local-demo-return {
  position: relative;
  z-index: 60;
  margin-left: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  min-height: 40px;
  padding: 6px 16px;
  background: var(--source-demo-bg, #eef2f6);
  border-bottom: 1px dashed var(--source-demo-border, #5c6a7a);
  color: var(--source-demo-ink, #364150);
  font-size: 12px;
  font-weight: 500;
}
.local-demo-return .secondary-button {
  min-height: 26px;
  padding: 3px 10px;
  font-size: 12px;
}
@media (max-width: 760px) {
  .local-demo-return {
    margin-left: 52px;
    justify-content: flex-start;
    padding: 6px 12px;
  }
}
</style>
