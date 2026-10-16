<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { api, errorMessage, isAborted, connectionSettings } from "./api";
const props = defineProps<{ url: string | null | undefined; alt: string }>();
const image = ref("");
const error = ref("");
let controller: AbortController | undefined;
let generation = 0;
function release() { if (image.value) URL.revokeObjectURL(image.value); image.value = ""; }
watch(() => [props.url, connectionSettings.base, connectionSettings.token], async () => {
  controller?.abort(); release(); error.value = "";
  const current = ++generation;
  if (!props.url) return;
  controller = new AbortController();
  try {
    const blob = await api.media(props.url, controller.signal);
    if (current === generation) image.value = URL.createObjectURL(blob);
  } catch (cause) { if (!isAborted(cause) && current === generation) error.value = errorMessage(cause); }
}, { immediate: true });
onBeforeUnmount(() => { generation++; controller?.abort(); release(); });
</script>
<template>
  <div class="authenticated-media">
    <img v-if="image" :src="image" :alt="alt" />
    <span v-else-if="error" class="inline-error">{{ error }}</span>
    <span v-else>{{ url ? "读取图像…" : "选择图像后预览" }}</span>
  </div>
</template>
