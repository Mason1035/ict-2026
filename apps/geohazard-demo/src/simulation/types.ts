/** DEMO_ONLY: display and simulation contracts, never a formal hardware/model schema. */
export type SensorKey = "moisture" | "tilt" | "vibration" | "rain" | "crack";
export type SensorValues = Record<SensorKey, number>;
export type ScenarioId = "A" | "B" | "C" | "D";
export type RiskLevel = "low" | "moderate" | "high" | "critical";
export type LinkKey = "wifi" | "lora" | "gateway" | "mqtt" | "atlas" | "cloud";
export type Communication = Record<LinkKey, boolean>;
export type NetworkState =
  "ONLINE_WIFI" | "ONLINE_LORA" | "OFFLINE" | "RECOVERING";
export type ActivePath = "wifi" | "lora" | null;
export type QueueStatus = "Pending" | "Sending" | "Synced" | "Failed";
export type LogType =
  "info" | "risk" | "network" | "system" | "cache" | "sync" | "alert";

export interface SensorMeta {
  key: SensorKey;
  label: string;
  shortLabel: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  hardware: string;
  source: "demo-hardware" | "scenario";
}

export interface RiskContribution {
  sensor: SensorKey;
  value: number;
  normalized: number;
  weight: number;
  points: number;
}

export interface DemoRisk {
  score: number;
  level: RiskLevel;
  rawNormalized: number;
  contributions: RiskContribution[];
}

export interface Scenario {
  id: ScenarioId;
  label: string;
  shortLabel: string;
  english: string;
  description: string;
  sensors: SensorValues;
  targetScore: number;
}

/** Channels preserve an expansion point for multiple physical sensors. */
export interface SensorChannel {
  id: string;
  label: string;
  source: SensorMeta["source"];
  fields: SensorKey[];
  readings: Partial<SensorValues>;
  updatedAt: number;
}

export interface RiskHistoryPoint {
  time: number;
  score: number;
  level: RiskLevel;
}
export type SensorHistoryPoint = SensorValues & { time: number };
export interface EventLog {
  id: string;
  time: number;
  type: LogType;
  message: string;
}
export interface Alert {
  id: string;
  time: number;
  level: RiskLevel;
  score: number;
  reason: string;
  status: "active" | "resolved";
  sensors: SensorValues;
}

/** A cached row and its eventual transmission deliberately retain the same ID. */
export interface DemoRecord {
  id: string;
  deviceId: "NODE-01";
  bootId: string;
  sequence: number;
  time: number;
  kind: "sample" | "alert";
  score: number;
  level: RiskLevel;
  sensors: SensorValues;
  status: QueueStatus;
  attempts: number;
  path?: Exclude<ActivePath, null>;
  syncedAt?: number;
  updatedAt?: number;
  delivery?: "realtime" | "backfill";
}

export interface SimulationState {
  bootId: string;
  bootOrdinal: number;
  sequence: number;
  scenario: ScenarioId | "custom";
  sensors: SensorValues;
  channels: SensorChannel[];
  risk: DemoRisk;
  communication: Communication;
  network: NetworkState;
  activePath: ActivePath;
  running: boolean;
  speed: 1 | 2 | 4;
  elapsedSeconds: number;
  riskHistory: RiskHistoryPoint[];
  sensorHistory: SensorHistoryPoint[];
  logs: EventLog[];
  alerts: Alert[];
  queue: DemoRecord[];
  transmissions: DemoRecord[];
}

export type SimulationAction =
  | { type: "tick" }
  | { type: "step" }
  | { type: "set-scenario"; scenario: ScenarioId }
  | { type: "set-sensor"; sensor: SensorKey; value: number }
  | { type: "set-link"; link: LinkKey; value: boolean }
  | { type: "set-running"; running: boolean }
  | { type: "set-speed"; speed: 1 | 2 | 4 }
  | { type: "clear-history" }
  | { type: "reset" }
  | { type: "clear-demo-data" };

export interface QueueStats {
  pending: number;
  highRisk: number;
  samples: number;
  sending: number;
  failed: number;
  synced: number;
  total: number;
  progress: number;
  latestResult: DemoRecord | undefined;
}
