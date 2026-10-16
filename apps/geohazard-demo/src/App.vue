<script setup lang="ts">
import { ref, defineAsyncComponent } from "vue";
import PlatformDashboard from "./PlatformDashboard.vue";
const DemoDashboard = defineAsyncComponent(() => import("./DemoDashboard.vue"));
const localDemo = ref(new URLSearchParams(window.location.search).get("mode") === "local");
function changeMode(local: boolean) {
  localDemo.value = local;
  const url = new URL(window.location.href);
  if (local) url.searchParams.set("mode", "local");
  else url.searchParams.delete("mode");
  window.history.replaceState({}, "", url);
}
</script>
<template>
  <div v-if="localDemo" class="local-demo-return">
    <span>独立本地演示 · 数据仅存在于浏览器内存</span>
    <button @click="changeMode(false)">返回后端平台</button>
  </div>
  <DemoDashboard v-if="localDemo" />
  <PlatformDashboard v-else @local-demo="changeMode(true)" />
</template>
<style>
.local-demo-return { position: relative; z-index: 60; display: flex; align-items: center; justify-content: center; gap: 20px; min-height: 36px; background: #f3e7cf; color: #6c542d; font-size: 12px; }
.local-demo-return button { text-decoration: underline; padding: 8px; }
</style>
