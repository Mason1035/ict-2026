import type { TelemetryRow } from "./types";
export interface RawReplayPayload {
  boot_id: number; seq: number; uptime_ms: number;
  experiment?: { run_id?: string };
  soil: Record<string, number | null>;
  imu: { ax: number | null; ay: number | null; az: number | null }[];
}
export function replayGroups(rows: TelemetryRow[]) {
  const groups = new Map<number, RawReplayPayload[]>();
  for (const row of rows) {
    const p = row.payload as unknown as RawReplayPayload | undefined;
    if (row.source !== "REAL" || !p?.experiment?.run_id?.startsWith("REAL_REPLAY|")) continue;
    const samples = groups.get(p.boot_id) || [];
    samples.push(p); groups.set(p.boot_id, samples);
  }
  return [...groups].map(([boot, samples]) => ({ boot, samples: samples.sort((a, b) => a.seq - b.seq) }));
}
export function rawPath(samples: RawReplayPayload[], read: (p: RawReplayPayload) => number | null, min: number, max: number) {
  const first = samples[0]?.uptime_ms || 0;
  const duration = (samples.at(-1)?.uptime_ms || first) - first || 1;
  let active = false;
  return samples.map(p => {
    const value = read(p);
    if (value == null || !Number.isFinite(value)) { active = false; return ""; }
    const command = `${active ? "L" : "M"}${(8+(p.uptime_ms-first)/duration*304).toFixed(2)},${(90-(value-min)/(max-min || 1)*80).toFixed(2)}`;
    active = true; return command;
  }).join(" ");
}
