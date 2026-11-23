import assert from "node:assert/strict";
import { access, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";
const base = process.env.PLATFORM_URL || "http://127.0.0.1:5173";
const output = resolve("test-results/platform");
await mkdir(output, { recursive: true });
let executablePath = process.env.BROWSER_EXECUTABLE;
if (!executablePath && process.platform === "darwin") {
  const installed = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  try { await access(installed); executablePath = installed; } catch { /* use installed Playwright Chromium */ }
}
const browser = await chromium.launch({ ...(executablePath ? { executablePath } : {}), headless: true, args: ["--enable-unsafe-swiftshader"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const checks = [];
const waitText = async (locator, value) => { await locator.waitFor(); await page.waitForFunction(([selector, text]) => document.querySelector(selector)?.textContent?.includes(text), [await locator.evaluate((el) => { el.setAttribute("data-smoke-target", "yes"); return '[data-smoke-target="yes"]'; }), value]); await locator.evaluate((el) => el.removeAttribute("data-smoke-target")); };
async function check(name, task) { await task(); checks.push(name); console.log(`PASS ${name}`); }
let connectorId;
try {
  await context.request.post(`${base}/api/v1/demo/reset`, { data: {} });
  await page.goto(base);
  await check("default platform reads real backend and preserves unknown vision", async () => {
    await waitText(page.getByTestId("backend-status"), "后端已连接");
    assert.ok((await page.getByTestId("platform-risk-score").innerText()).includes("18"));
    assert.ok((await page.locator(".risk-channels").innerText()).includes("未标定"));
    assert.equal(await page.locator(".local-demo-return").count(), 0);
  });
  await check("server scenario controls create persistent alarm and acknowledge it", async () => {
    await page.getByRole("button", { name: "暂停后端演示", exact: true }).click();
    await page.getByRole("button", { name: "极端灾害", exact: true }).click();
    await page.waitForFunction(() => Number(document.querySelector('[data-testid="platform-risk-score"]')?.textContent?.split('/')[0]) >= 80);
    await page.getByRole("button", { name: "告警与事件", exact: true }).click();
    await page.locator(".platform-alarm").first().waitFor();
    assert.ok((await page.locator(".platform-alarm").first().innerText()).includes("紧急预警"));
    await page.getByRole("button", { name: "确认告警", exact: true }).first().click();
    await page.locator(".acknowledged").first().waitFor();
  });
  await check("history uses backend records, raw JSON and cursor pagination", async () => {
    await page.getByRole("button", { name: "历史数据", exact: true }).click();
    await page.getByRole("button", { name: "查看 JSON", exact: true }).first().click();
    assert.ok((await page.locator(".payload-view").innerText()).includes("zhifang.telemetry.v2"));
    const more = page.getByRole("button", { name: "加载更早记录", exact: true });
    if (await more.count()) { const previous = await page.locator(".platform-table tbody tr").count(); await more.click(); await page.waitForFunction((n) => document.querySelectorAll(".platform-table tbody tr").length > n, previous); }
  });
  await check("MQTT connector CRUD starts an actual broker subscription", async () => {
    await page.getByRole("button", { name: "配置与接入", exact: true }).click();
    await page.getByRole("button", { name: "新增连接器", exact: true }).click();
    await page.getByLabel("名称", { exact: true }).fill("浏览器联调 MQTT");
    await page.getByLabel("数据来源", { exact: true }).selectOption("MOCK");
    await page.getByLabel("Broker 地址", { exact: true }).fill("127.0.0.1");
    await page.getByLabel("端口", { exact: true }).fill(process.env.MQTT_TEST_PORT || "18883");
    await page.getByLabel("站点 ID", { exact: true }).fill("MOCK-LAB");
    await page.getByLabel("启用持续订阅", { exact: true }).check();
    const response = page.waitForResponse((r) => r.url().endsWith("/connectors") && r.request().method() === "POST");
    await page.getByRole("button", { name: "保存连接器", exact: true }).click();
    const created = await response; const saved = await created.json(); assert.equal(created.status(), 201, JSON.stringify(saved)); connectorId = saved.id;
    await page.locator(".connector-row", { hasText: "浏览器联调 MQTT" }).waitFor();
    await page.getByRole("button", { name: "测试连接", exact: true }).click();
    await page.locator(".connector-row .inline-success").waitFor();
    await page.waitForFunction(() => Array.from(document.querySelectorAll("#platform-device option")).some((x) => x.textContent?.includes("MOCK-NODE-01")), null, { timeout: 20000 });
    await page.getByLabel("选择设备与数据来源", { exact: true }).selectOption("MOCK-LAB|MOCK-NODE-01|MOCK");
    await page.getByRole("button", { name: "监测总览", exact: true }).click();
    await waitText(page.getByTestId("platform-risk-score"), "72");
    assert.ok(!(await page.locator(".platform-demo-bar").count()), "server demo controls must not mutate an external MQTT stream");
  });
  await check("MOCK vision samples, authenticated images and ROI analysis work", async () => {
    await page.getByLabel("选择设备与数据来源", { exact: true }).selectOption("DEMO|DEMO-NODE-01|MOCK");
    await page.getByRole("button", { name: "视觉证据", exact: true }).click();
    await page.getByRole("button", { name: "一键生成示例", exact: true }).click();
    await page.locator(".vision-result").waitFor({ timeout: 20000 });
    await page.waitForFunction(() => document.querySelectorAll('.authenticated-media img[src^="blob:"]').length >= 3);
    assert.ok((await page.locator(".vision-result").innerText()).includes("不参与融合"));
    assert.ok((await page.locator(".vision-metrics").innerText()).includes("未标定"));
    await page.getByLabel("限定检测区域 ROI", { exact: true }).check();
    const response = page.waitForResponse((r) => r.url().endsWith("/vision/analyze") && r.request().method() === "POST");
    await page.getByRole("button", { name: "运行视觉基线", exact: true }).click();
    assert.equal((await response).status(), 200);
    await page.screenshot({ path: resolve(output, "vision.png"), fullPage: true });
  });
  await check("uncalibrated telemetry remains unknown instead of showing zero or normal", async () => {
    const snapshot = await (await context.request.get(`${base}/api/v1/dashboard`)).json();
    const payload = structuredClone(snapshot.latest.payload);
    payload.device_id = "MOCK-UNKNOWN-BROWSER"; payload.seq = Date.now() % 1000000;
    payload.risk.sensor_score = null; payload.risk.level = null;
    const response = await context.request.post(`${base}/api/v1/ingest/test`, { data: { payload, context: {} } });
    assert.equal(response.status(), 201, await response.text());
    await page.getByRole("button", { name: "刷新后端数据", exact: true }).click();
    await page.waitForFunction(() => Array.from(document.querySelectorAll("#platform-device option")).some((x) => x.textContent?.includes("MOCK-UNKNOWN-BROWSER")));
    await page.getByLabel("选择设备与数据来源", { exact: true }).selectOption("DEMO|MOCK-UNKNOWN-BROWSER|MOCK");
    await page.getByRole("button", { name: "监测总览", exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[data-testid="platform-risk-score"]')?.textContent?.trim().startsWith("—"));
    assert.ok((await page.locator(".platform-risk .risk-level").innerText()).includes("未标定"));
    assert.ok(!(await page.locator(".platform-demo-bar").count()), "only designated demo device receives server controls");
    await page.getByLabel("选择设备与数据来源", { exact: true }).selectOption("DEMO|DEMO-NODE-01|MOCK");
  });
  await check("backend failure clears current readings without a local fallback", async () => {
    await page.getByRole("button", { name: "监测总览", exact: true }).click();
    await page.route("**/api/v1/**", (route) => route.abort("failed"));
    await page.getByRole("button", { name: "刷新后端数据", exact: true }).click();
    await waitText(page.getByTestId("backend-status"), "后端失联");
    assert.ok((await page.getByTestId("platform-risk-score").innerText()).startsWith("—"));
    assert.ok((await page.getByTestId("reading-moisture").innerText()).startsWith("—"));
    assert.equal(await page.locator(".local-demo-return").count(), 0);
    await page.unroute("**/api/v1/**");
    await page.getByRole("button", { name: "刷新后端数据", exact: true }).click();
    await waitText(page.getByTestId("backend-status"), "后端已连接");
  });
  await check("responsive pages remain inside the viewport", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const name of ["监测总览", "视觉证据", "配置与接入", "告警与事件", "历史数据"]) {
      await page.getByRole("button", { name, exact: true }).click();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name} overflows viewport`);
    }
    await page.getByRole("button", { name: "监测总览", exact: true }).click();
    await page.screenshot({ path: resolve(output, "mobile.png"), fullPage: true });
  });
  await check("local simulation mounts only on explicit choice", async () => {
    await page.getByRole("button", { name: "进入独立本地演示", exact: true }).click();
    await page.locator(".local-demo-return").waitFor();
    await page.getByTestId("simulation-time").waitFor();
    await page.getByRole("button", { name: "返回后端平台", exact: true }).click();
    await waitText(page.getByTestId("backend-status"), "后端已连接");
    assert.equal(await page.getByTestId("simulation-time").count(), 0);
  });
  assert.deepEqual(errors, [], "No browser runtime errors");
  console.log(`Passed ${checks.length} platform checks`);
} catch (error) {
  await page.screenshot({ path: resolve(output, "failure.png"), fullPage: true });
  console.error(error); process.exitCode = 1;
} finally {
  if (connectorId) await context.request.delete(`${base}/api/v1/connectors/${connectorId}`);
  await context.request.post(`${base}/api/v1/demo/reset`, { data: {} });
  await browser.close();
}
