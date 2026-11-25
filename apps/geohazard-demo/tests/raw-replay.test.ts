import assert from "node:assert/strict";
import test from "node:test";
import { rawPath, replayGroups, type RawReplayPayload } from "../src/platform/rawReplay.ts";
import type { TelemetryRow } from "../src/platform/types.ts";
function sample(seq: number, uptime_ms: number, value: number | null): RawReplayPayload {
  return { boot_id: 1, seq, uptime_ms, experiment: { run_id: "REAL_REPLAY|UNCALIBRATED|test" }, soil: { top_raw: value }, imu: [] };
}
test("raw channels break at null, retain zero and use device time spacing", () => {
  const d = rawPath([sample(1, 1000, 0), sample(2, 1500, 10), sample(3, 2000, null), sample(4, 3000, 5)], p => p.soil.top_raw, 0, 10);
  assert.equal(d, "M8.00,90.00 L84.00,10.00  M312.00,50.00");
});
test("separate boots, preserve seq order, exclude MOCK and unmarked REAL", () => {
  const row = (p: RawReplayPayload, source = "REAL"): TelemetryRow => ({ id: String(p.seq), received_at: "2026-11-01T00:00:00Z", source: source as "REAL" | "MOCK", payload: p as unknown as Record<string, unknown> });
  const groups = replayGroups([row(sample(2, 1500, 2)), row({ ...sample(1, 30, 3), boot_id: 2 }), row(sample(1, 1000, 1)), row(sample(4, 2000, 9), "MOCK"), row({ ...sample(5, 2500, 9), experiment: { run_id: "live" } })]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].samples.map(p => p.seq), [1, 2]);
  assert.deepEqual(groups[1].samples.map(p => p.uptime_ms), [30]);
});
