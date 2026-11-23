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
