export type Source = "MOCK" | "REAL";
export type Level = "low" | "moderate" | "high" | "critical" | "unknown";
export type SensorKey = "moisture" | "tilt" | "vibration" | "rain" | "crack";
export type Sensors = Record<SensorKey, number | null>;
export interface Device { site_id: string; device_id: string; source: Source; scope: string; last_received_at: string | null; }
export interface MqttStatus { id?: string; connector_id?: string; name?: string; status?: string; state?: string; connected?: boolean; last_error?: string | null; message?: string; received_count?: number; messages_received?: number; messages_accepted?: number; messages_rejected?: number; intake_healthy?: boolean; last_durable_at?: string | null; }
export interface Health { status: string; version: string; storage: { durable: boolean }; demo: { running?: boolean; scenario?: string } | boolean; auth_mode: string; mqtt: MqttStatus[]; }
export interface Risk { sensor_score: number | null; vision_score: number | null; final_score: number | null; level: Level; mode: string; reason: string; }
export interface Latest { id: string; received_at: string; source_time: number | null; age_seconds: number; stale: boolean; sensors: Sensors; risk: Risk; system: Record<string, boolean | null>; }
export interface HistoryPoint extends Sensors { time: string; score: number | null; }
export interface Alarm { id: string; level: Level | string; score: number | null; reason: string; acknowledged: boolean; created_at: string; source?: Source; }
export interface Event { id: string; kind: string; message: string; created_at: string; }
export interface ConnectorConfig { payload_format?: "telemetry_v2" | "tinyquake_v1"; host: string; port: number; topic: string; site_id: string; username?: string; password?: string; password_configured?: boolean; tls: boolean; client_id?: string; }
export interface Connector { id: string; name: string; kind: "mqtt"; source: Source; enabled: boolean; config: ConnectorConfig; status?: MqttStatus | string; password_configured?: boolean; has_password?: boolean; }
export interface ConnectorWrite { name: string; kind: "mqtt"; source: Source; enabled: boolean; config: ConnectorConfig; }
export interface Evidence { id: string; file_url: string; original_name?: string; filename?: string; width: number; height: number; camera_id: string; site_id: string; device_id: string | null; source: Source; scope: string; capture_time?: string | null; captured_at?: string | null; created_at?: string; received_at?: string; arrival_time?: string; }
export interface Region { x: number; y: number; width: number; height: number; }
export interface VisionResult { site_id?: string; device_id?: string | null; source?: Source; camera_id?: string; scope?: string; roi?: Region; id: string; evidence_id: string; reference_id: string | null; vision_score: number | null; quality: Record<string, unknown>; metrics: Record<string, number | string | boolean | null>; baseline_valid: boolean; fusion_eligible: boolean; reasons: string[]; overlay_url: string | null; created_at?: string; }
export interface Dashboard { site_id: string; device_id: string; source: Source; scope: string; latest: Latest | null; history: HistoryPoint[]; alarms: Alarm[]; events: Event[]; stats: { telemetry_count: number; alarm_count: number; evidence_count: number }; demo: { running: boolean; scenario: string; elapsed_seconds: number }; connectors: Connector[]; vision: { evidence: Evidence[]; results: VisionResult[]; latest_result: VisionResult | null }; }
export interface TelemetryRow { id: string; received_at: string; source_time?: string; source?: Source; payload?: Record<string, unknown>; sensors?: Sensors; risk?: Risk; [key: string]: unknown; }
export interface Items<T> { items: T[]; next_cursor?: string | null; total?: number; }
export const sensorFields: { key: SensorKey; label: string; unit: string; decimals: number }[] = [
  { key: "moisture", label: "土壤湿度", unit: "%", decimals: 1 },
  { key: "tilt", label: "地表倾斜", unit: "°", decimals: 2 },
  { key: "vibration", label: "微振动", unit: "g", decimals: 3 },
  { key: "rain", label: "降雨强度", unit: "mm/h", decimals: 1 },
  { key: "crack", label: "裂缝变化", unit: "mm", decimals: 2 },
];
export const levelNames: Record<Level, string> = { low: "低风险", moderate: "中风险", high: "高风险", critical: "紧急预警", unknown: "未标定" };
export const levelColors: Record<Level, string> = { low: "#39866a", moderate: "#b48b30", high: "#ce7548", critical: "#bd514c", unknown: "#87938c" };
export function reading(value: number | null | undefined, decimals = 1) { return value == null || !Number.isFinite(value) ? "—" : value.toFixed(decimals); }
export function dateTime(value?: string | number | null) { if (!value) return "—"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false }); }
export function deviceKey(device: Device) { return [device.site_id, device.device_id, device.source].join("|"); }

export function normalizeLevel(value: string): Level { return ({ NORMAL: "low", WATCH: "moderate", WARNING: "high", EMERGENCY: "critical" } as Record<string, Level>)[value] || (value in levelNames ? value as Level : "unknown"); }
