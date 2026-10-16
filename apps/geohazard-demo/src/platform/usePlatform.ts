import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, errorMessage, isAborted } from "./api";
import { deviceKey, type Dashboard, type Device, type Health, type Items, type TelemetryRow } from "./types";
export function usePlatform() {
  const dashboard = ref<Dashboard | null>(null);
  const health = ref<Health | null>(null);
  const devices = ref<Device[]>([]);
  const selectedKey = ref("");
  const history = ref<TelemetryRow[]>([]);
  const historyCursor = ref<string | null>(null);
  const historyLoading = ref(false);
  let loadedMore = false;
  const connection = ref<"loading" | "online" | "offline">("loading");
  const error = ref("");
  const updatedAt = ref<string | null>(null);
  const busy = ref(false);
  const actionError = ref("");
  const selected = computed(() => devices.value.find((d) => deviceKey(d) === selectedKey.value));
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  let refreshing = false;
  let generation = 0;
  function stop() { clearTimeout(timer); controller?.abort(); generation++; refreshing = false; }
  async function refresh() {
    if (disposed || document.hidden || refreshing) return;
    clearTimeout(timer);
    refreshing = true;
    const currentGeneration = generation;
    controller = new AbortController();
    const signal = controller.signal;
    try {
      const [nextHealth, list] = await Promise.all([api.get<Health>("/health", signal), api.get<Items<Device>>("/devices", signal)]);
      if (currentGeneration !== generation) return;
      devices.value = list.items;
      let device = list.items.find((d) => deviceKey(d) === selectedKey.value);
      if (!device) {
        device = list.items.find((d) => d.site_id === "DEMO" && d.source === "MOCK") || list.items[0];
        selectedKey.value = device ? deviceKey(device) : "";
      }
      const query = new URLSearchParams(device ? { site_id: device.site_id, device_id: device.device_id, source: device.source } : { site_id: "DEMO", device_id: "DEMO-NODE-01", source: "MOCK" });
      const [next, rows] = await Promise.all([
        api.get<Dashboard>(`/dashboard?${query}`, signal),
        device ? api.get<Items<TelemetryRow>>(`/devices/${encodeURIComponent(device.device_id)}/telemetry?${query}&limit=100`, signal) : Promise.resolve({ items: [], next_cursor: null }),
      ]);
      if (currentGeneration !== generation) return;
      health.value = nextHealth;
      dashboard.value = next;
      if (loadedMore) {
        const ids = new Set(rows.items.map((row) => row.id));
        history.value = [...rows.items, ...history.value.filter((row) => !ids.has(row.id))];
      } else {
        history.value = rows.items;
        historyCursor.value = rows.next_cursor || null;
      }
      connection.value = "online";
      error.value = "";
      updatedAt.value = new Date().toISOString();
    } catch (cause) {
      if (isAborted(cause) || currentGeneration !== generation) return;
      connection.value = "offline";
      error.value = errorMessage(cause);
      dashboard.value = null;
      history.value = [];
      health.value = null;
    } finally {
      if (currentGeneration === generation) {
        refreshing = false;
        if (!disposed && !document.hidden) timer = setTimeout(refresh, 2000);
      }
    }
  }
  function reconnect() { stop(); loadedMore = false; historyCursor.value = null; dashboard.value = null; history.value = []; connection.value = "loading"; void refresh(); }
  function visibility() { if (document.hidden) stop(); else void refresh(); }
  function select(key: string) { stop(); loadedMore = false; historyCursor.value = null; selectedKey.value = key; dashboard.value = null; history.value = []; void refresh(); }
  async function moreHistory() {
    if (!historyCursor.value || !selected.value || historyLoading.value) return;
    const device = selected.value;
    const key = selectedKey.value;
    const query = new URLSearchParams({ site_id: device.site_id, source: device.source, limit: "100", cursor: historyCursor.value });
    historyLoading.value = true; actionError.value = "";
    try {
      const rows = await api.get<Items<TelemetryRow>>(`/devices/${encodeURIComponent(device.device_id)}/telemetry?${query}`);
      if (selectedKey.value !== key || disposed) return;
      const ids = new Set(history.value.map((row) => row.id));
      history.value = [...history.value, ...rows.items.filter((row) => !ids.has(row.id))];
      historyCursor.value = rows.next_cursor || null; loadedMore = true;
    } catch (cause) { actionError.value = errorMessage(cause); }
    finally { historyLoading.value = false; }
  }
  async function action(path: string, body: unknown = {}) {
    if (busy.value) return;
    busy.value = true;
    actionError.value = "";
    try { await api.send(path, body); stop(); await refresh(); }
    catch (cause) { actionError.value = errorMessage(cause); }
    finally { busy.value = false; }
  }
  onMounted(() => { void refresh(); document.addEventListener("visibilitychange", visibility); });
  onBeforeUnmount(() => { disposed = true; stop(); document.removeEventListener("visibilitychange", visibility); });
  return { dashboard, health, devices, selectedKey, selected, history, historyCursor, historyLoading, moreHistory, connection, error, actionError, updatedAt, busy, refresh, reconnect, select, action };
}
