import { RISK_ORDER } from "./scenarios";
import type {
  ActivePath,
  Communication,
  DemoRecord,
  QueueStats,
  SimulationState,
} from "./types";

export function isPathUsable(
  communication: Communication,
  path: ActivePath,
): boolean {
  if (!communication.mqtt || !communication.atlas || !communication.cloud)
    return false;
  if (path === "wifi") return communication.wifi;
  if (path === "lora") return communication.lora && communication.gateway;
  return false;
}

export function chooseActivePath(communication: Communication): ActivePath {
  if (isPathUsable(communication, "wifi")) return "wifi";
  if (isPathUsable(communication, "lora")) return "lora";
  return null;
}

export function isOutstanding(record: DemoRecord): boolean {
  return record.status !== "Synced";
}

/** High-risk history first, then severity, alerts, chronological FIFO; IDs are stable. */
export function compareBackfillPriority(a: DemoRecord, b: DemoRecord): number {
  const aHigh = RISK_ORDER[a.level] >= 2 ? 1 : 0;
  const bHigh = RISK_ORDER[b.level] >= 2 ? 1 : 0;
  return (
    bHigh - aHigh ||
    RISK_ORDER[b.level] - RISK_ORDER[a.level] ||
    Number(b.kind === "alert") - Number(a.kind === "alert") ||
    a.time - b.time ||
    a.id.localeCompare(b.id)
  );
}

export function getQueueStats(state: SimulationState): QueueStats {
  const outstanding = state.queue.filter(isOutstanding);
  const synced = state.queue.length - outstanding.length;
  return {
    pending: outstanding.length,
    highRisk: outstanding.filter((record) => RISK_ORDER[record.level] >= 2)
      .length,
    samples: outstanding.filter((record) => record.kind === "sample").length,
    sending: outstanding.filter((record) => record.status === "Sending").length,
    failed: outstanding.filter((record) => record.status === "Failed").length,
    synced,
    total: state.queue.length,
    progress: state.queue.length
      ? Math.round((synced / state.queue.length) * 100)
      : 100,
    latestResult: state.queue
      .filter(
        (record) => record.status === "Synced" || record.status === "Failed",
      )
      .sort((a, b) => (b.updatedAt ?? b.time) - (a.updatedAt ?? a.time))[0],
  };
}
