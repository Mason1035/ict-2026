import assert from "node:assert/strict";
import test from "node:test";

const storage = new Map<string, string>();
Object.defineProperty(globalThis, "sessionStorage", { value: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) }, configurable: true });
Object.defineProperty(globalThis, "window", { value: { location: { origin: "http://127.0.0.1:5173" } }, configurable: true });
const { connectionSettings } = await import("../src/platform/api");
const { researchGet, researchUrl } = await import("../src/research/api");
const boundary = { scope: "RESEARCH", uncalibrated: true, production_alarm_eligible: false };

test("research prefix follows backend origin and reverse-proxy path", () => {
  connectionSettings.base = "/api/v1";
  assert.equal(researchUrl("/sessions").href, "http://127.0.0.1:5173/api/research/sessions");
  connectionSettings.base = "https://backend.example/prefix/api/v1/";
  assert.equal(researchUrl("/sessions/A/rules").href, "https://backend.example/prefix/api/research/sessions/A/rules");
  connectionSettings.base = "/unexpected";
  assert.throws(() => researchUrl("/sessions"), /api\/v1/);
});

test("research GET carries auth, no-store and accepts only research boundary", async () => {
  connectionSettings.base = "/api/v1"; connectionSettings.token = "synthetic-token";
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (input, init) => {
      assert.equal(String(input), "http://127.0.0.1:5173/api/research/sessions");
      assert.equal(new Headers(init?.headers).get("Authorization"), "Bearer synthetic-token");
      assert.equal(init?.cache, "no-store");
      assert.ok(!init?.method || init.method === "GET");
      return Response.json({ ...boundary, items: [] });
    };
    assert.deepEqual(await researchGet("/sessions"), { ...boundary, items: [] });
    for (const bad of [{ ...boundary, scope: "OPERATIONAL" }, { ...boundary, uncalibrated: false }, { ...boundary, production_alarm_eligible: true }]) {
      globalThis.fetch = async () => Response.json(bad);
      await assert.rejects(researchGet("/sessions"), /边界标识不符/);
    }
  } finally { globalThis.fetch = original; connectionSettings.token = ""; }
});

test("research errors keep the backend message", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ detail: "研究会话未登记" }, { status: 404 });
    await assert.rejects(researchGet("/sessions/missing"), /研究会话未登记/);
  } finally { globalThis.fetch = original; }
});

test("research session cancellation reaches fetch", async () => {
  const original = globalThis.fetch;
  const controller = new AbortController();
  try {
    globalThis.fetch = async (_input, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason), { once: true });
    });
    const pending = researchGet("/sessions/A", controller.signal);
    controller.abort();
    await assert.rejects(pending, (error: unknown) => error instanceof DOMException && error.name === "AbortError");
  } finally { globalThis.fetch = original; }
});

test("research detail query stays in search, not encoded into the experiment path", () => {
  connectionSettings.base = "/api/v1";
  const experiment = "NODE01-f9029c8eef460b40-N0000004.CSV";
  const detail = researchUrl(`/sessions/${encodeURIComponent(experiment)}?max_points=600`);
  assert.equal(detail.pathname, `/api/research/sessions/${experiment}`);
  assert.equal(detail.search, "?max_points=600");
  assert.equal(detail.searchParams.get("max_points"), "600");
  assert.equal(detail.href, `http://127.0.0.1:5173/api/research/sessions/${experiment}?max_points=600`);
  assert.ok(!detail.href.includes("%3F"), "query ? must not be percent-encoded into the path");
  const rules = researchUrl(`/sessions/${encodeURIComponent(experiment)}/rules`);
  assert.equal(rules.pathname, `/api/research/sessions/${experiment}/rules`);
  assert.equal(rules.search, "");
  assert.equal(rules.href, `http://127.0.0.1:5173/api/research/sessions/${experiment}/rules`);
});

test("research detail preserves a reverse-proxy prefix and an encoded session ID", () => {
  connectionSettings.base = "https://backend.example/prefix/api/v1/";
  const experiment = encodeURIComponent("NODE 01?#.CSV");
  const detail = researchUrl(`/sessions/${experiment}?max_points=600`);
  assert.equal(detail.origin, "https://backend.example");
  assert.equal(detail.pathname, `/prefix/api/research/sessions/${experiment}`);
  assert.equal(detail.searchParams.get("max_points"), "600");
  assert.equal(detail.hash, "");
});

test("research GET for detail uses query string, not a %3F path", async () => {
  connectionSettings.base = "/api/v1";
  const experiment = "NODE01-f9029c8eef460b40-N0000004.CSV";
  const original = globalThis.fetch;
  const seen: string[] = [];
  try {
    globalThis.fetch = async (input, init) => {
      seen.push(String(input));
      assert.ok(!init?.method || init.method === "GET");
      return Response.json({ ...boundary, experiment_id: experiment, session: { experiment_id: experiment } });
    };
    await researchGet(`/sessions/${encodeURIComponent(experiment)}?max_points=600`);
    await researchGet(`/sessions/${encodeURIComponent(experiment)}/rules`);
    assert.deepEqual(seen, [
      `http://127.0.0.1:5173/api/research/sessions/${experiment}?max_points=600`,
      `http://127.0.0.1:5173/api/research/sessions/${experiment}/rules`,
    ]);
  } finally { globalThis.fetch = original; }
});
