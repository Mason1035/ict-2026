import { connectionSettings, readResponseWithTimeout } from "../platform/api";

export interface Boundary { scope: "RESEARCH"; uncalibrated: true; production_alarm_eligible: false }
export interface Session extends Boundary {
  experiment_id: string; replay_id: string; session_type: string; label: string; type_label: string;
  duration_s: number; firmware_sha256: string; firmware_identity_status: string; quality_flags: string[];
  channels: Record<string, { valid_count: number; invalid_count: number }>;
}
export interface Curve {
  metric: string; unit: string; input_points: number;
  points: { time_us: number; value: number | null; break_before: boolean }[];
}
export interface Period {
  scope: "RESEARCH"; event_class: string; candidate_only: boolean; triggered: boolean; sensor_id: string;
  start_us: number; confirmed_at_us: number; end_us: number; reason_codes: string[]; reason_mask: number;
  closure: string; contributions: { sensor_id: string; peak_values: Record<string, number>; thresholds: Record<string, number> }[];
}
export interface Provenance extends Boundary {
  method_version: string; generated_at: string; config_sha256: string; rule_version: string; reference_version: string;
  source: { experiment_id: string; session_type: string; replay_id: string; file_sha256: Record<string, string>; quality_flags: string[] };
  reason_definition_version: string;
}
export interface Detail extends Boundary {
  session: Session; max_points: number; provenance: Provenance;
  channels: Record<string, { statistics: { count: number; usable_count: number; missing_value_count: number; duration_s: number | null; median_interval_us: number | null; quality_flags: string[] };
    rule_summary: { state: string; diagnostic_counts: Record<string, number> }; curves: Curve[] }>;
}
export interface Rules extends Boundary {
  experiment_id: string; config_sha256: string; trigger_count: number; candidate_count: number; provenance: Provenance;
  events: Period[]; candidates: Period[];
  coincidences: { start_us: number; end_us: number; channels: string[]; reason_mask: number }[];
  reason_decode: { code: string; mask: number; label: string }[];
}

export function researchUrl(path: string): URL {
  const url = new URL(connectionSettings.base, window.location.origin);
  if (!/\/api\/v1\/?$/.test(url.pathname)) throw new Error("后端地址须以 /api/v1 结尾，以定位独立研究 API");
  url.pathname = url.pathname.replace(/\/api\/v1\/?$/, "/api/research") + path;
  return url;
}
export async function researchGet<T extends Boundary>(path: string, signal?: AbortSignal): Promise<T> {
  const headers = new Headers();
  if (connectionSettings.token) headers.set("Authorization", `Bearer ${connectionSettings.token}`);
  const value = await readResponseWithTimeout<T>(researchUrl(path), { headers, signal, cache: "no-store" }, (r) => r.json() as Promise<T>, 90000);
  if (value.scope !== "RESEARCH" || value.uncalibrated !== true || value.production_alarm_eligible !== false) {
    throw new Error("研究结果边界标识不符，已拒绝展示");
  }
  return value;
}
