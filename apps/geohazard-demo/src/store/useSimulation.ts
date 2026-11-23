import { onMounted, onUnmounted, shallowRef, watch } from "vue";
import { createInitialState, reduceSimulation } from "../simulation";
import type { SimulationAction } from "../simulation";

export function useSimulation() {
  const state = shallowRef(createInitialState());
  let interval: ReturnType<typeof setInterval> | undefined;
  function dispatch(action: SimulationAction) {
    state.value = reduceSimulation(state.value, action);
  }
  function schedule() {
    clearInterval(interval);
    if (state.value.running && !document.hidden)
      interval = setInterval(
        () => dispatch({ type: "tick" }),
        1000 / state.value.speed,
      );
  }
  watch(() => [state.value.running, state.value.speed], schedule);
  onMounted(() => {
    schedule();
    document.addEventListener("visibilitychange", schedule);
  });
  onUnmounted(() => {
    clearInterval(interval);
    document.removeEventListener("visibilitychange", schedule);
  });
  return { state, dispatch };
}
