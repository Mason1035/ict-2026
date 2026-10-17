import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import test from "node:test";

const storage = new Map<string, string>();
Object.defineProperty(globalThis, "sessionStorage", { value: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) }, configurable: true });
const { readResponseWithTimeout } = await import("../src/platform/api");

test("request deadline includes stalled JSON, error JSON and image bodies after headers", async () => {
  const server = createServer((request, response) => {
    response.writeHead(request.url === "/error" ? 422 : 200, { "Content-Type": request.url === "/image" ? "image/png" : "application/json" });
    response.flushHeaders();
    response.write(request.url === "/image" ? Buffer.from([137, 80, 78, 71]) : '{"partial":');
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  try {
    for (const path of ["/json", "/error", "/image"]) {
      const started = performance.now();
      await assert.rejects(readResponseWithTimeout(`http://127.0.0.1:${address.port}${path}`, {}, (response) => path === "/image" ? response.blob() : response.json(), 100), (error: unknown) => error instanceof DOMException && error.name === "TimeoutError");
      assert.ok(performance.now() - started < 1500, "stalled body must not outlive the request deadline");
    }
  } finally { server.closeAllConnections(); server.close(); }
});

test("external cancellation still reaches a body already being read", async () => {
  let arrived: (() => void) | undefined;
  const headersSent = new Promise<void>((resolve) => { arrived = resolve; });
  const server = createServer((_request, response) => { response.writeHead(200, { "Content-Type": "application/json" }); response.flushHeaders(); response.write('{"partial":'); arrived?.(); });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const address = server.address(); assert.ok(address && typeof address !== "string");
  const controller = new AbortController();
  const pending = readResponseWithTimeout(`http://127.0.0.1:${address.port}/`, { signal: controller.signal }, (response) => response.json(), 2000);
  try {
    await headersSent;
    await new Promise((resolve) => setTimeout(resolve, 30));
    controller.abort();
    await assert.rejects(pending, (error: unknown) => error instanceof DOMException && error.name === "AbortError");
  } finally { server.closeAllConnections(); server.close(); }
});
