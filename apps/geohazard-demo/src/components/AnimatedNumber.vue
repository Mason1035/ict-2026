<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
const props = withDefaults(
  defineProps<{ value: number; decimals?: number }>(),
  { decimals: 0 },
);
const shown = ref(props.value);
let frame = 0;
watch(
  () => props.value,
  (next) => {
    cancelAnimationFrame(frame);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      shown.value = next;
      return;
    }
    const from = shown.value,
      start = performance.now();
    function update(t: number) {
      const p = Math.min(1, (t - start) / 420);
      shown.value = from + (next - from) * (1 - Math.pow(1 - p, 3));
      if (p < 1) frame = requestAnimationFrame(update);
    }
    frame = requestAnimationFrame(update);
  },
);
onBeforeUnmount(() => cancelAnimationFrame(frame));
</script>
<template>
  <span :aria-label="value.toFixed(decimals)">{{
    shown.toFixed(decimals)
  }}</span>
</template>
