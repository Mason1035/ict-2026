import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "playwright";
const origin = "http://127.0.0.1:5188";
const vite = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5188", "--strictPort"], { stdio: ["ignore", "pipe", "pipe"] });
let output = ""; vite.stdout.on("data", (chunk) => { output += chunk; }); vite.stderr.on("data", (chunk) => { output += chunk; });
let browser;
try {
  for (let attempt = 0; attempt < 50; attempt++) { if (vite.exitCode != null) throw new Error(output); try { if ((await fetch(origin)).ok) break; } catch {} await delay(100); }
  let executablePath = process.env.BROWSER_EXECUTABLE;
  if (!executablePath && process.platform === "darwin") { const installed = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; try { await access(installed); executablePath = installed; } catch {} }
  browser = await chromium.launch({ ...(executablePath ? { executablePath } : {}), headless: true, args: ["--enable-unsafe-swiftshader"] });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const runtimeErrors = []; page.on("pageerror", (error) => runtimeErrors.push(error.message));
  const device = (id) => ({ site_id: "DEMO", device_id: id, source: "MOCK", scope: "TEST_ONLY", last_received_at: null });
  const devices = [device("A"), device("B"), device("DEMO-NODE-01")];
  const image = (id, owner = "A") => ({ id, site_id: "DEMO", device_id: owner, source: "MOCK", scope: "TEST_ONLY", camera_id: "CAM-01", file_url: `/api/v1/evidence/${id}/file`, width: 640, height: 400, filename: `${id}.png`, capture_time: null, arrival_time: "2026-10-18T01:00:00Z" });
  const result = (id = "RESULT-A", evidenceId = "A-current") => ({ id, site_id: "DEMO", device_id: "A", source: "MOCK", scope: "TEST_ONLY", camera_id: "CAM-01", evidence_id: evidenceId, reference_id: "A-reference", roi: { x: 0, y: 0, width: 640, height: 400 }, vision_score: null, quality: {}, metrics: { changed_area_ratio: .1, ssim: .9 }, baseline_valid: true, fusion_eligible: false, reasons: [], overlay_url: null, created_at: "2026-10-18T01:00:00Z" });
  const rows = (owner) => [{ id: `${owner}-fresh`, source: "MOCK", received_at: "2026-10-18T01:00:00Z", payload: { schema: "zhifang.telemetry.v2", device_id: owner } }];
  const dashboard = (id) => ({ ...device(id), latest: null, history: [], alarms: [], events: [], stats: { telemetry_count: 2, alarm_count: 0, evidence_count: id === "A" ? 3 : 0 }, demo: { running: true, scenario: "A", elapsed_seconds: 0 }, connectors: [{ id: "BROKEN", name: "写入故障链路", kind: "mqtt", source: "REAL", enabled: true, config: { host: "127.0.0.1", port: 1883, site_id: "SITE", topic: "zhifang/v2/SITE/+/telemetry", tls: false }, status: { connector_id: "BROKEN", connected: true, intake_healthy: false, state: "storage_error", last_error: "disk full" } }], vision: { evidence: [], results: [], latest_result: null } });
  let analysisQueue = [], historyQueue = [], deferAnalysis = false, deferHistory = false, resetCalls = 0;
  const pendingWait = async (queue, length) => { for (let i = 0; i < 100; i++) { if (queue.length >= length) return; await delay(25); } throw new Error("expected deferred request was not received"); };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url()), path = url.pathname, owner = url.searchParams.get("device_id") || "A";
    const json = async (body) => { try { await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }); } catch {} };
    if (path.endsWith("/demo/reset")) { resetCalls++; return json({}); }
    if (path.endsWith("/health")) return json({ status: "ok", version: "test", storage: { durable: true }, demo: true, auth_mode: "test", mqtt: [] });
    if (path.endsWith("/devices")) return json({ items: devices });
    if (path.endsWith("/dashboard")) return json(dashboard(owner));
    if (path.endsWith("/telemetry")) {
      const id = decodeURIComponent(path.split("/").at(-2));
      if (url.searchParams.has("cursor")) { if (deferHistory) { const position = historyQueue.length; historyQueue.push({ resolve: () => json({ items: [{ ...rows(id)[0], id: `${id}-stale-${position}` }], next_cursor: null }) }); return; } return json({ items: [{ ...rows(id)[0], id: `${id}-older` }], next_cursor: null }); }
      return json({ items: rows(id), next_cursor: "next-history" });
    }
    if (path.endsWith("/evidence")) { assert.ok(url.searchParams.has("device_id")); assert.equal(url.searchParams.get("source"), "MOCK"); return json({ items: owner === "A" ? url.searchParams.has("cursor") ? [image("A-older")] : [image("A-current"), image("A-reference")] : [], next_cursor: owner === "A" && !url.searchParams.has("cursor") ? "next-evidence" : null, total: owner === "A" ? 3 : 0 }); }
    if (path.endsWith("/vision/results")) return json({ items: owner === "A" ? url.searchParams.has("cursor") ? [result("OLDER", "A-older")] : [result()] : [], next_cursor: owner === "A" && !url.searchParams.has("cursor") ? "next-results" : null, total: owner === "A" ? 2 : 0 });
    if (path.endsWith("/vision/analyze")) { if (deferAnalysis) { const position = analysisQueue.length; analysisQueue.push({ resolve: () => json(result(`ANALYSIS-${position}`)) }); return; } return json({ ...result("NEW-ANALYSIS"), ...route.request().postDataJSON() }); }
    if (path.endsWith("/file")) { try { await route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==", "base64") }); } catch {} return; }
    return json({});
  });
  const choose = async (id) => { await page.getByLabel("选择设备与数据来源", { exact: true }).selectOption(`DEMO|${id}|MOCK`); await page.waitForFunction((value) => document.querySelector('.platform-context')?.textContent?.includes(value), id === "DEMO-NODE-01" ? "后端演示" : "模拟接入"); };
  const nav = (name) => page.getByRole("button", { name, exact: true }).click();
  const check = async (name, task) => { await task(); console.log(`PASS ${name}`); };
  await page.goto(origin); await page.getByTestId("backend-status").filter({ hasText: "后端已连接" }).waitFor(); await nav("视觉证据");
  await check("visual pagination stays scoped and old evidence/results remain selectable", async () => {
    await page.getByLabel("当前图像", { exact: true }).waitFor();
    await page.getByRole("button", { name: "加载更多证据", exact: true }).click();
    await page.getByRole("button", { name: "加载更多分析记录", exact: true }).click();
    await page.getByLabel("当前图像", { exact: true }).locator('option[value="A-older"]').waitFor({ state: "attached" });
    await page.getByLabel("已保存的分析", { exact: true }).locator('option[value="OLDER"]').waitFor({ state: "attached" });
  });
  await check("reference and ROI edits mark saved results as belonging to earlier inputs", async () => {
    await page.getByLabel("参考图像", { exact: true }).selectOption("A-reference");
    assert.equal(await page.getByTestId("vision-inputs-changed").count(), 0);
    await page.getByLabel("参考图像", { exact: true }).selectOption("");
    await page.getByTestId("vision-inputs-changed").waitFor();
    await page.getByLabel("参考图像", { exact: true }).selectOption("A-reference");
    await page.getByLabel("限定检测区域 ROI", { exact: true }).check();
    await page.getByTestId("vision-inputs-changed").waitFor();
    assert.ok((await page.getByTestId("vision-saved-inputs").innerText()).includes("640×400"));
    await page.getByLabel("限定检测区域 ROI", { exact: true }).uncheck();
  });
  await check("A to B to A discards an old analysis without clearing a newer operation's busy state", async () => {
    deferAnalysis = true;
    await page.getByRole("button", { name: "运行视觉基线", exact: true }).click(); await pendingWait(analysisQueue, 1);
    await choose("B"); await choose("A"); await page.getByLabel("当前图像", { exact: true }).waitFor();
    await page.getByRole("button", { name: "运行视觉基线", exact: true }).click(); await pendingWait(analysisQueue, 2);
    await analysisQueue[0].resolve(); await delay(100);
    assert.equal(await page.getByRole("button", { name: "运行视觉基线", exact: true }).isDisabled(), true);
    assert.equal(await page.getByLabel("已保存的分析", { exact: true }).locator('option[value="ANALYSIS-0"]').count(), 0);
    await analysisQueue[1].resolve(); await page.getByRole("button", { name: "运行视觉基线", exact: true }).waitFor();
    await page.waitForFunction(() => !document.querySelector('button[aria-busy="true"]'));
    deferAnalysis = false;
  });
  await check("sample generation is limited to the designated backend demo device", async () => {
    assert.equal(await page.getByRole("button", { name: "一键生成示例", exact: true }).count(), 0);
    await choose("DEMO-NODE-01"); await page.getByRole("button", { name: "一键生成示例", exact: true }).waitFor(); await choose("A");
  });
  await check("history pagination drops A to B to A and changed-backend responses", async () => {
    await nav("历史数据"); deferHistory = true;
    await page.getByRole("button", { name: "加载更早记录", exact: true }).click(); await pendingWait(historyQueue, 1);
    await choose("B"); await choose("A");
    await page.getByRole("button", { name: "加载更早记录", exact: true }).click(); await pendingWait(historyQueue, 2);
    await historyQueue[0].resolve(); await delay(100);
    assert.equal(await page.getByRole("button", { name: "读取中…", exact: true }).isDisabled(), true);
    assert.ok(!(await page.locator(".platform-table").innerText()).includes("stale-0"));
    await page.getByRole("button", { name: "连接设置", exact: true }).click();
    await page.getByLabel("API 地址", { exact: true }).fill(`${origin}/api/v1`);
    await page.getByRole("button", { name: "保存并连接", exact: true }).click();
    await page.getByRole("button", { name: "加载更早记录", exact: true }).waitFor();
    await historyQueue[1].resolve(); await delay(100);
    assert.ok(!(await page.locator(".platform-table").innerText()).includes("stale-1")); deferHistory = false;
  });
  await check("a connected broker with a durable-storage failure is visibly unhealthy", async () => { await nav("配置与接入"); await page.getByText("接入存储异常", { exact: true }).waitFor(); assert.ok((await page.locator(".connector-row").innerText()).includes("disk full")); });
  await check("backend demo reset requires confirmation and cancel never sends a request", async () => {
    await choose("DEMO-NODE-01"); await nav("监测总览");
    await page.getByRole("button", { name: "重置后端演示", exact: true }).click();
    await page.getByRole("dialog", { name: "重置后端演示？", exact: true }).waitFor();
    await page.getByRole("button", { name: "取消", exact: true }).click(); assert.equal(resetCalls, 0);
    await page.getByRole("button", { name: "重置后端演示", exact: true }).click();
    await page.getByRole("button", { name: "重置演示", exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('dialog[open]'));
    assert.equal(resetCalls, 1);
  });
  assert.deepEqual(runtimeErrors, []);
  console.log("Passed 7 targeted platform regressions");
} finally {
  await browser?.close();
  vite.kill("SIGTERM");
  await new Promise((resolve) => { if (vite.exitCode != null) resolve(); else { vite.once("exit", resolve); setTimeout(() => { vite.kill("SIGKILL"); resolve(); }, 2000).unref(); } });
}
