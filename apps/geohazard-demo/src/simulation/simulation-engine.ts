import {
  chooseActivePath,
  compareBackfillPriority,
  isOutstanding,
  isPathUsable,
} from "./communication";
import { calculateDemoRisk } from "./risk-engine";
import { RISK_LABELS, RISK_ORDER, SCENARIOS, SENSOR_META } from "./scenarios";
import type {
  Alert,
  DemoRecord,
  LinkKey,
  LogType,
  SensorChannel,
  SensorValues,
  SimulationAction,
  SimulationState,
} from "./types";

const HISTORY_LIMIT = 120;
const LOG_LIMIT = 160;
const TRANSMISSION_DISPLAY_LIMIT = 120;
const LINK_LABELS: Record<LinkKey, string> = {
  wifi: "NODE Wi-Fi",
  lora: "NODE LoRa",
  gateway: "GW-01 上行链路",
  mqtt: "MQTT 服务",
  atlas: "Atlas 服务",
  cloud: "Huawei Cloud 服务",
};

function channels(sensors: SensorValues, time: number): SensorChannel[] {
  return [
    {
      id: "SOIL-1",
      label: "SEN0193 · ADS1115",
      source: "demo-hardware",
      fields: ["moisture"],
      readings: { moisture: sensors.moisture },
      updatedAt: time,
    },
    {
      id: "IMU-1",
      label: "ICM-42688-P",
      source: "demo-hardware",
      fields: ["tilt", "vibration"],
      readings: { tilt: sensors.tilt, vibration: sensors.vibration },
      updatedAt: time,
    },
    {
      id: "SCENE-RAIN",
      label: "场景降雨",
      source: "scenario",
      fields: ["rain"],
      readings: { rain: sensors.rain },
      updatedAt: time,
    },
    {
      id: "SCENE-CRACK",
      label: "场景裂缝",
      source: "scenario",
      fields: ["crack"],
      readings: { crack: sensors.crack },
      updatedAt: time,
    },
  ];
}

function nextId(state: SimulationState): string {
  state.sequence += 1;
  return `NODE-01-${state.bootId}-${String(state.sequence).padStart(6, "0")}`;
}

function log(state: SimulationState, type: LogType, message: string): void {
  state.logs.unshift({
    id: nextId(state),
    time: state.elapsedSeconds,
    type,
    message,
  });
  state.logs = state.logs.slice(0, LOG_LIMIT);
}

export function createInitialState(
  bootId = "demo-1",
  bootOrdinal = 1,
): SimulationState {
  const sensors = { ...SCENARIOS[0].sensors };
  const risk = calculateDemoRisk(sensors);
  const state: SimulationState = {
    bootId,
    bootOrdinal,
    sequence: 0,
    scenario: "A",
    sensors,
    channels: channels(sensors, 0),
    risk,
    communication: {
      wifi: true,
      lora: true,
      gateway: true,
      mqtt: true,
      atlas: true,
      cloud: true,
    },
    network: "ONLINE_WIFI",
    activePath: "wifi",
    running: true,
    speed: 1,
    elapsedSeconds: 0,
    riskHistory: [{ time: 0, score: risk.score, level: risk.level }],
    sensorHistory: [{ time: 0, ...sensors }],
    logs: [],
    alerts: [],
    queue: [],
    transmissions: [],
  };
  log(state, "system", "演示已启动 · NODE-01 正常监测 · DEMO ONLY");
  return state;
}

function clone(state: SimulationState): SimulationState {
  return {
    ...state,
    sensors: { ...state.sensors },
    communication: { ...state.communication },
    riskHistory: [...state.riskHistory],
    sensorHistory: [...state.sensorHistory],
    logs: [...state.logs],
    alerts: [...state.alerts],
    queue: [...state.queue],
    transmissions: [...state.transmissions],
  };
}

function appendSnapshot(state: SimulationState): void {
  state.channels = channels(state.sensors, state.elapsedSeconds);
  state.riskHistory.push({
    time: state.elapsedSeconds,
    score: state.risk.score,
    level: state.risk.level,
  });
  state.sensorHistory.push({ time: state.elapsedSeconds, ...state.sensors });
  state.riskHistory = state.riskHistory.slice(-HISTORY_LIMIT);
  state.sensorHistory = state.sensorHistory.slice(-HISTORY_LIMIT);
}

function record(state: SimulationState, kind: DemoRecord["kind"]): DemoRecord {
  const id = nextId(state);
  return {
    id,
    deviceId: "NODE-01",
    bootId: state.bootId,
    sequence: state.sequence,
    time: state.elapsedSeconds,
    kind,
    score: state.risk.score,
    level: state.risk.level,
    sensors: { ...state.sensors },
    status: "Pending",
    attempts: 0,
  };
}

function transmit(state: SimulationState, value: DemoRecord): void {
  // This list is a display history. Cached queue rows are retained independently.
  state.transmissions.unshift(value);
  state.transmissions = state.transmissions.slice(
    0,
    TRANSMISSION_DISPLAY_LIMIT,
  );
}

function routeRecord(state: SimulationState, value: DemoRecord): void {
  const path = chooseActivePath(state.communication);
  if (path) {
    transmit(state, {
      ...value,
      status: "Synced",
      path,
      attempts: 1,
      delivery: "realtime",
      syncedAt: state.elapsedSeconds,
      updatedAt: state.elapsedSeconds,
    });
    if (RISK_ORDER[value.level] >= 2 && state.network === "RECOVERING") {
      log(
        state,
        "sync",
        `当前高危${value.kind === "alert" ? "告警" : "遥测"}优先发送 · ${value.id}`,
      );
    }
  } else {
    // Never apply a display cap here: the pending queue is the source of truth.
    state.queue.push(value);
    log(
      state,
      "cache",
      `已写入 MicroSD 演示缓存 · ${value.id} · 待补传 ${state.queue.filter(isOutstanding).length} 条`,
    );
  }
}

function emitSample(
  state: SimulationState,
  message = "NODE-01 多模态采样完成",
): void {
  routeRecord(state, record(state, "sample"));
  log(state, "info", message);
}

function updateSensors(state: SimulationState, values: SensorValues): void {
  const previousLevel = state.risk.level;
  state.sensors = values;
  state.risk = calculateDemoRisk(values);
  if (previousLevel !== state.risk.level) {
    state.alerts = state.alerts.map((alert) =>
      alert.status === "active"
        ? { ...alert, status: "resolved" as const }
        : alert,
    );
    const up = RISK_ORDER[state.risk.level] > RISK_ORDER[previousLevel];
    log(
      state,
      "risk",
      `风险等级${up ? "升至" : "降至"}${RISK_LABELS[state.risk.level]} · ${state.risk.score.toFixed(1)} / 100`,
    );
    if (up) {
      const alertRecord = record(state, "alert");
      const strongest = [...state.risk.contributions]
        .sort((a, b) => b.points - a.points)
        .slice(0, 3);
      const reason = strongest
        .map((contribution) => {
          const meta = SENSOR_META.find(
            (sensor) => sensor.key === contribution.sensor,
          )!;
          return `${meta.shortLabel} ${contribution.value}${meta.unit}`;
        })
        .join(" · ");
      const alert: Alert = {
        id: alertRecord.id,
        time: state.elapsedSeconds,
        level: state.risk.level,
        score: state.risk.score,
        reason: `${reason} · 演示阈值升级`,
        status: "active",
        sensors: { ...values },
      };
      state.alerts.unshift(alert);
      routeRecord(state, alertRecord);
      log(
        state,
        "alert",
        `触发${RISK_LABELS[state.risk.level]}演示告警 · ${alert.id}`,
      );
    }
  }
  appendSnapshot(state);
}

function reconcileNetwork(state: SimulationState): void {
  const oldPath = state.activePath;
  const oldNetwork = state.network;
  const path = chooseActivePath(state.communication);
  state.activePath = path;
  // An interrupted in-flight row is marked Failed; next recovery retries its ID.
  state.queue = state.queue.map((row) => {
    if (
      row.status !== "Sending" ||
      isPathUsable(state.communication, row.path ?? null)
    )
      return row;
    log(state, "network", `补传中断，保留事件等待重试 · ${row.id}`);
    return {
      ...row,
      status: "Failed" as const,
      updatedAt: state.elapsedSeconds,
    };
  });
  const outstanding = state.queue.some(isOutstanding);
  state.network = path
    ? outstanding
      ? "RECOVERING"
      : path === "wifi"
        ? "ONLINE_WIFI"
        : "ONLINE_LORA"
    : "OFFLINE";
  if (!path && oldNetwork !== "OFFLINE") {
    log(
      state,
      "network",
      "上行链路不可用 · 本地采集、计算、告警继续 · MicroSD 缓存启用",
    );
  } else if (path && oldNetwork === "OFFLINE") {
    log(
      state,
      "network",
      `网络恢复 · ${path === "wifi" ? "Wi-Fi" : "LoRa 中继"}可用${outstanding ? " · 开始逐条补传" : ""}`,
    );
  } else if (path && oldPath !== path) {
    log(
      state,
      "network",
      path === "lora"
        ? "主链路不可用，已切换 LoRa 中继 · GW-01 上行正常"
        : "Wi-Fi 主链路恢复，已切回主链路",
    );
  }
  if (oldNetwork === "RECOVERING" && state.network !== "RECOVERING" && path) {
    log(state, "sync", "历史记录补传完成 · 所有缓存事件已同步");
  }
}

function advanceBackfill(state: SimulationState): void {
  if (!state.activePath) return;
  const sendingIndex = state.queue.findIndex((row) => row.status === "Sending");
  if (sendingIndex >= 0) {
    const row = state.queue[sendingIndex];
    if (isPathUsable(state.communication, row.path ?? null)) {
      const synced: DemoRecord = {
        ...row,
        status: "Synced",
        syncedAt: state.elapsedSeconds,
        updatedAt: state.elapsedSeconds,
        delivery: "backfill",
      };
      state.queue[sendingIndex] = synced;
      transmit(state, synced);
      log(
        state,
        "sync",
        `补传成功 · ${row.id} · 剩余 ${state.queue.filter(isOutstanding).length} 条`,
      );
    } else {
      state.queue[sendingIndex] = {
        ...row,
        status: "Failed",
        updatedAt: state.elapsedSeconds,
      };
      log(state, "network", `补传失败，保留事件等待重试 · ${row.id}`);
    }
  }
  const next = state.queue
    .filter((row) => row.status === "Pending" || row.status === "Failed")
    .sort(compareBackfillPriority)[0];
  if (next) {
    const index = state.queue.findIndex((row) => row.id === next.id);
    state.queue[index] = {
      ...next,
      status: "Sending",
      path: state.activePath,
      attempts: next.attempts + 1,
      updatedAt: state.elapsedSeconds,
    };
    log(
      state,
      "sync",
      `${next.attempts ? "重试" : "正在"}补传 · ${next.id} · ${RISK_LABELS[next.level]}`,
    );
  }
  reconcileNetwork(state);
}

/** Pure reducer; time, sampling, IDs, delivery, alerts all derive from this state. */
export function reduceSimulation(
  current: SimulationState,
  action: SimulationAction,
): SimulationState {
  if (action.type === "reset" || action.type === "clear-demo-data") {
    return createInitialState(
      `demo-${current.bootOrdinal + 1}`,
      current.bootOrdinal + 1,
    );
  }
  if (action.type === "tick" && !current.running) return current;
  if (action.type === "set-sensor" && !Number.isFinite(action.value))
    return current;
  const state = clone(current);
  switch (action.type) {
    case "tick":
    case "step":
      state.elapsedSeconds += 1;
      // Deterministic constant sampling after a preset/manual change. No random
      // noise, unstable alert threshold crossings, or freshly fabricated curves.
      appendSnapshot(state);
      // Current live telemetry is always handled BEFORE historical backfill.
      emitSample(state);
      advanceBackfill(state);
      break;
    case "set-scenario": {
      const scenario = SCENARIOS.find((item) => item.id === action.scenario);
      if (!scenario) return current;
      if (
        state.scenario === scenario.id &&
        SENSOR_META.every(
          (meta) => state.sensors[meta.key] === scenario.sensors[meta.key],
        )
      )
        return current;
      state.scenario = scenario.id;
      log(state, "system", `切换场景 · ${scenario.label} · 预设为模拟数据`);
      updateSensors(state, { ...scenario.sensors });
      emitSample(state, `NODE-01 场景采样完成 · ${scenario.label}`);
      break;
    }
    case "set-sensor": {
      const meta = SENSOR_META.find((sensor) => sensor.key === action.sensor);
      if (!meta) return current;
      const value =
        Math.round(
          Math.max(meta.min, Math.min(meta.max, action.value)) * 1000,
        ) / 1000;
      if (state.sensors[action.sensor] === value) return current;
      state.scenario = "custom";
      log(
        state,
        "system",
        `手动调节 · ${meta.label} ${value}${meta.unit} · 演示输入`,
      );
      updateSensors(state, { ...state.sensors, [action.sensor]: value });
      emitSample(state, "NODE-01 手动参数采样完成");
      break;
    }
    case "set-link":
      if (state.communication[action.link] === action.value) return current;
      state.communication[action.link] = action.value;
      log(
        state,
        "network",
        `${LINK_LABELS[action.link]}${action.value ? "恢复" : "中断"}`,
      );
      reconcileNetwork(state);
      break;
    case "set-running":
      if (state.running === action.running) return current;
      state.running = action.running;
      log(state, "system", action.running ? "仿真继续运行" : "仿真已暂停");
      break;
    case "set-speed":
      if (![1, 2, 4].includes(action.speed) || state.speed === action.speed)
        return current;
      state.speed = action.speed;
      log(state, "system", `仿真速度 · ${action.speed}×`);
      break;
    case "clear-history":
      state.riskHistory = [];
      state.sensorHistory = [];
      log(state, "system", "已清空演示趋势历史 · 后续采样继续积累");
      break;
  }
  return state;
}
