import assert from "node:assert/strict";
import { access, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

// Use an installed Playwright module; this check never downloads a browser.
const { chromium } = process.env.PLAYWRIGHT_MODULE
  ? await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href)
  : await import("playwright");
let executable = process.env.BROWSER_EXECUTABLE;
if (executable) await access(executable);
else if (process.platform === "darwin") {
  const installedChrome =
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  try {
    await access(installedChrome);
    executable = installedChrome;
  } catch {
    /* use Playwright Chromium */
  }
}
const localDemoUrl = new URL(process.env.DEMO_URL || "http://127.0.0.1:5173");
localDemoUrl.searchParams.set("mode", "local");
const output = resolve("test-results");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  ...(executable ? { executablePath: executable } : {}),
  headless: true,
  args: ["--enable-unsafe-swiftshader"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
});
const page = await context.newPage();
const errors = [],
  warnings = [],
  results = [];
page.on("pageerror", (error) =>
  errors.push({ type: "runtime", message: error.message }),
);
page.on("console", (message) => {
  if (message.type() === "error")
    errors.push({ type: "console", message: message.text() });
  if (message.type() === "warning") warnings.push(message.text());
});

async function check(name, fn) {
  try {
    await fn();
    results.push({ name, passed: true });
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({ name, passed: false, message: error.message });
    console.log(`FAIL ${name}: ${error.message}`);
    await page.screenshot({
      path: resolve(output, `failure-${results.length}.png`),
      fullPage: true,
    });
  }
}

async function settle() {
  await page.waitForTimeout(650);
}
async function expectText(locator, text) {
  await locator.waitFor({ state: "visible" });
  assert.ok(
    (await locator.innerText()).includes(text),
    `expected ${text}, got ${await locator.innerText()}`,
  );
}
async function pause() {
  const button = page.getByRole("button", { name: "暂停仿真", exact: true });
  if (await button.count()) await button.click();
}
async function reset() {
  await page.getByRole("button", { name: "重置演示", exact: true }).click();
  await pause();
  await settle();
}
async function scene(name, score) {
  await page
    .getByRole("button", { name: new RegExp(`^${name}\\s*风险约`) })
    .click();
  await settle();
  assert.equal(
    parseFloat(await page.locator(".risk-number").innerText()),
    score,
  );
}
async function link(name, enabled) {
  const button = page.getByRole("switch", { name, exact: true });
  if ((await button.getAttribute("aria-checked")) !== String(enabled))
    await button.click();
}
async function step(count = 1) {
  for (let index = 0; index < count; index += 1)
    await page.getByRole("button", { name: "推进一步", exact: true }).click();
}
async function queueTab() {
  await page.getByRole("tab", { name: /^离线队列/ }).click();
}
async function pendingCount() {
  return parseInt(
    await page
      .locator(".queue-summary > div")
      .first()
      .locator("strong")
      .innerText(),
  );
}
async function queueRows() {
  return page.locator(".queue-row").evaluateAll((rows) =>
    rows.map((row) => ({
      id: row.querySelector("code").textContent,
      status: row.querySelector(".queue-status").textContent.trim(),
      score: parseFloat(row.children[2].textContent.split("·")[1]),
      kind: row.children[1].textContent,
      attempts: Number(
        row.querySelector("small").textContent.replace(/\D/g, ""),
      ),
    })),
  );
}

try {
  await page.goto(localDemoUrl.href, {
    waitUntil: "networkidle",
  });
  await pause();
  await settle();

  await check(
    "initial A=18, Wi-Fi online, five telemetry cards, no queue",
    async () => {
      assert.equal(
        parseFloat(await page.locator(".risk-number").innerText()),
        18,
      );
      assert.equal(await page.locator(".sensor-card").count(), 5);
      await expectText(page.locator(".network-summary"), "Wi-Fi 主链路运行");
      await queueTab();
      assert.equal(await pendingCount(), 0);
      await expectText(page.locator(".queue-empty"), "没有积压记录");
      assert.ok(
        await page.locator(".terrain-canvas canvas").count(),
        "expected functioning WebGL canvas",
      );
    },
  );

  await check(
    "scenario B=46 / C=72 / D=91 and alert deduplication",
    async () => {
      await scene("持续暴雨", 46);
      await scene("位移异常", 72);
      await scene("极端灾害", 91);
      await page.getByRole("tab", { name: /^告警中心/ }).click();
      assert.equal(await page.locator(".alert-row").count(), 3);
      await expectText(page.locator(".alert-row").first(), "紧急预警");
      await step(3);
      assert.equal(await page.locator(".alert-row").count(), 3);
    },
  );

  await check(
    "number input and keyboard slider update telemetry, risk and node detail",
    async () => {
      await reset();
      await scene("持续暴雨", 46);
      const number = page.getByRole("spinbutton", { name: "地表倾角数值" });
      await number.fill("20");
      await number.press("Tab");
      await settle();
      assert.ok(
        parseFloat(await page.locator(".risk-number").innerText()) > 46,
      );
      await expectText(
        page.locator('[data-sensor="tilt"] .sensor-reading strong'),
        "20.0",
      );
      await page
        .getByRole("button", { name: "查看 IMU-1 地表倾斜", exact: true })
        .click();
      await expectText(
        page.getByRole("region", { name: "IMU-1 节点详情" }),
        "20.0°",
      );
      const range = page.getByRole("slider", { name: "地表倾角滑块" });
      await range.focus();
      await range.press("End");
      await settle();
      assert.equal(await number.inputValue(), "45");
      await expectText(
        page.getByRole("region", { name: "IMU-1 节点详情" }),
        "45.0°",
      );
      await page
        .getByRole("button", { name: "关闭节点详情", exact: true })
        .click();
    },
  );

  await check(
    "primary, LoRa gateway and downstream service gating",
    async () => {
      await reset();
      await link("NODE Wi-Fi", false);
      await expectText(page.locator(".network-summary"), "LoRa 中继接管");
      await link("GW-01 上行", false);
      await expectText(page.locator(".network-summary"), "离线保护运行");
      await link("GW-01 上行", true);
      await expectText(page.locator(".network-summary"), "LoRa 中继接管");
      await link("MQTT 服务", false);
      await expectText(page.locator(".network-summary"), "离线保护运行");
      await link("MQTT 服务", true);
      await expectText(page.locator(".network-summary"), "LoRa 中继接管");
      await link("云端接收", false);
      await expectText(page.locator(".network-summary"), "离线保护运行");
      await link("云端接收", true);
      await expectText(page.locator(".network-summary"), "LoRa 中继接管");
      await link("Atlas 服务", false);
      await expectText(page.locator(".network-summary"), "离线保护运行");
      await link("Atlas 服务", true);
      await expectText(page.locator(".network-summary"), "LoRa 中继接管");
    },
  );

  await check(
    "offline queue grows while paused stepping, priority recovery is gradual and IDs survive retry",
    async () => {
      await reset();
      await link("NODE Wi-Fi", false);
      await link("NODE LoRa", false);
      await step(3);
      await scene("位移异常", 72);
      await step();
      await scene("极端灾害", 91);
      await step();
      await queueTab();
      const initial = await pendingCount();
      assert.equal(initial, 9);
      const originalIds = (await queueRows()).map((row) => row.id).sort();
      await link("NODE Wi-Fi", true);
      await expectText(page.locator(".network-summary"), "正在恢复补传");
      assert.equal(await pendingCount(), initial);
      await step();
      const sending = (await queueRows()).find(
        (row) => row.status === "Sending",
      );
      assert.equal(sending.score, 91);
      assert.equal(sending.kind, "风险告警");
      assert.equal(await pendingCount(), initial);
      await page.screenshot({
        path: resolve(output, "recovery-sending.png"),
        fullPage: true,
      });
      await step();
      assert.equal(await pendingCount(), initial - 1);
      assert.equal(
        (await queueRows()).find((row) => row.id === sending.id).status,
        "Synced",
      );
      const interrupted = (await queueRows()).find(
        (row) => row.status === "Sending",
      );
      await link("NODE Wi-Fi", false);
      assert.equal(
        (await queueRows()).find((row) => row.id === interrupted.id).status,
        "Failed",
      );
      await link("NODE Wi-Fi", true);
      await step();
      assert.equal(
        (await queueRows()).find((row) => row.id === interrupted.id).status,
        "Sending",
      );
      assert.equal(
        (await queueRows()).find((row) => row.id === interrupted.id).attempts,
        2,
      );
      await step();
      assert.equal(
        (await queueRows()).find((row) => row.id === interrupted.id).status,
        "Synced",
      );
      for (let guard = 0; (await pendingCount()) && guard < 20; guard += 1) {
        const rows = await queueRows();
        const next = rows.find((row) => row.status === "Sending");
        if (rows.some((row) => row.status !== "Synced" && row.score >= 60))
          assert.ok(
            next.score >= 60,
            "low history sent before high-risk backlog",
          );
        const before = await pendingCount();
        await step();
        assert.ok((await pendingCount()) < before);
      }
      assert.equal(await pendingCount(), 0);
      assert.deepEqual(
        (await queueRows()).map((row) => row.id).sort(),
        originalIds,
      );
      assert.ok((await queueRows()).every((row) => row.status === "Synced"));
      await expectText(page.locator(".network-summary"), "Wi-Fi 主链路运行");
    },
  );

  await check(
    "history clears while paused, next step samples, reset clears alerts/queue/network",
    async () => {
      await page.getByRole("button", { name: "清空历史", exact: true }).click();
      await expectText(page.locator(".chart-empty"), "等待下一次采样");
      const time = await page.getByTestId("simulation-time").innerText();
      await page.waitForTimeout(1100);
      assert.equal(await page.getByTestId("simulation-time").innerText(), time);
      assert.equal(await page.locator(".chart-empty").count(), 1);
      await step();
      assert.equal(await page.locator(".chart-empty").count(), 0);
      await reset();
      assert.equal(
        parseFloat(await page.locator(".risk-number").innerText()),
        18,
      );
      assert.equal(
        await page.getByTestId("simulation-time").innerText(),
        "00:00:00",
      );
      await expectText(page.locator(".network-summary"), "Wi-Fi 主链路运行");
      for (const name of [
        "NODE Wi-Fi",
        "NODE LoRa",
        "GW-01 上行",
        "MQTT 服务",
        "Atlas 服务",
        "云端接收",
      ])
        assert.equal(
          await page
            .getByRole("switch", { name, exact: true })
            .getAttribute("aria-checked"),
          "true",
        );
      await queueTab();
      assert.equal(await pendingCount(), 0);
      assert.equal(await page.locator(".queue-row").count(), 0);
      await page.getByRole("tab", { name: /^告警中心/ }).click();
      assert.equal(await page.locator(".alert-row").count(), 0);
      const points = await page
        .locator(".risk-chart svg path")
        .nth(2)
        .getAttribute("d");
      assert.equal((points.match(/M/g) || []).length, 1);
    },
  );

  await check("visible contribution values sum to visible total", async () => {
    await page
      .getByRole("button", { name: "查看风险评分分解", exact: true })
      .click();
    try {
      const values = await page
        .locator(".contribution-list strong")
        .allTextContents();
      const total = parseFloat(
        await page.locator(".contribution-total strong").innerText(),
      );
      assert.equal(
        Math.round(values.reduce((sum, value) => sum + Number(value), 0) * 100),
        Math.round(total * 100),
      );
    } finally {
      await page
        .getByRole("button", { name: "关闭评分分解", exact: true })
        .click();
    }
  });

  await check(
    "native guide traps keyboard focus and Escape closes it",
    async () => {
      await page
        .getByRole("button", { name: "了解本演示", exact: true })
        .focus();
      await page.keyboard.press("Enter");
      await page.locator("dialog[open]").waitFor();
      try {
        assert.ok(
          await page
            .locator("dialog[open]")
            .evaluate((dialog) => dialog.matches(":modal")),
        );
        // Native Chromium may place focus on browser chrome (activeElement=body)
        // at a Tab boundary; underlying application controls must remain inert.
        for (let index = 0; index < 7; index += 1) {
          assert.ok(
            await page
              .locator("dialog[open]")
              .evaluate(
                (dialog) =>
                  dialog.contains(document.activeElement) ||
                  document.activeElement === document.body,
              ),
          );
          await page.keyboard.press("Tab");
        }
        await page
          .getByRole("button", { name: "关闭说明", exact: true })
          .focus();
        await page.keyboard.press("Escape");
        assert.equal(await page.locator("dialog[open]").count(), 0);
      } finally {
        const close = page.getByRole("button", {
          name: "关闭说明",
          exact: true,
        });
        if (await close.isVisible()) await close.click();
      }
    },
  );

  await check(
    "alert detail moves/traps keyboard focus and Escape closes it",
    async () => {
      await scene("位移异常", 72);
      await page.getByRole("tab", { name: /^告警中心/ }).click();
      const alert = page.locator(".alert-row").first();
      await alert.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "高风险详情" });
      await dialog.waitFor();
      try {
        assert.ok(
          await dialog.evaluate((element) =>
            element.contains(document.activeElement),
          ),
          "opening did not move focus into alert dialog",
        );
        assert.ok(
          await dialog.evaluate((element) => element.matches(":modal")),
        );
        for (let index = 0; index < 8; index += 1) {
          assert.ok(
            await dialog.evaluate(
              (element) =>
                element.contains(document.activeElement) ||
                document.activeElement === document.body,
            ),
            "focus escaped alert dialog",
          );
          await page.keyboard.press("Tab");
        }
        await dialog.locator("button").first().focus();
        await page.keyboard.press("Escape");
        assert.equal(await dialog.count(), 0);
      } finally {
        const close = page.getByRole("button", {
          name: "关闭详情",
          exact: true,
        });
        if (await close.count()) await close.click();
      }
    },
  );

  await check(
    "clear-demo dialog moves/traps keyboard focus and Escape cancels it",
    async () => {
      await queueTab();
      const clear = page.getByRole("button", {
        name: "清空演示数据",
        exact: true,
      });
      await clear.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "清空演示记录" });
      await dialog.waitFor();
      try {
        assert.ok(
          await dialog.evaluate((element) =>
            element.contains(document.activeElement),
          ),
          "opening did not move focus into clear-demo dialog",
        );
        assert.ok(
          await dialog.evaluate((element) => element.matches(":modal")),
        );
        for (let index = 0; index < 8; index += 1) {
          assert.ok(
            await dialog.evaluate(
              (element) =>
                element.contains(document.activeElement) ||
                document.activeElement === document.body,
            ),
            "focus escaped clear-demo dialog",
          );
          await page.keyboard.press("Tab");
        }
        await dialog.locator("button").first().focus();
        await page.keyboard.press("Escape");
        assert.equal(await dialog.count(), 0);
      } finally {
        const cancel = page.getByRole("button", { name: "取消", exact: true });
        if (await cancel.count()) await cancel.click();
      }
    },
  );

  await check(
    "event tabs support roving Arrow/Home/End keyboard selection",
    async () => {
      await page.getByRole("tab", { name: /^事件日志/ }).click();
      await page.keyboard.press("ArrowRight");
      assert.equal(
        await page
          .getByRole("tab", { name: /^告警中心/ })
          .getAttribute("aria-selected"),
        "true",
      );
      await page.keyboard.press("End");
      assert.equal(
        await page
          .getByRole("tab", { name: /^离线队列/ })
          .getAttribute("aria-selected"),
        "true",
      );
      await page.keyboard.press("Home");
      assert.equal(
        await page
          .getByRole("tab", { name: /^事件日志/ })
          .getAttribute("aria-selected"),
        "true",
      );
    },
  );

  await check(
    "reset returns terrain mode, camera preset and selected node to initial state",
    async () => {
      await reset();
      await page.getByRole("button", { name: "风险热力", exact: true }).click();
      await page
        .getByRole("button", { name: "切换俯视视角", exact: true })
        .click();
      await page.getByRole("button", { name: "放大地形", exact: true }).click();
      await page
        .getByRole("button", { name: "查看 IMU-1 地表倾斜", exact: true })
        .click();
      assert.equal(
        await page
          .getByRole("button", { name: "风险热力", exact: true })
          .getAttribute("aria-pressed"),
        "true",
      );
      assert.equal(
        await page
          .getByRole("button", { name: "切换俯视视角", exact: true })
          .getAttribute("aria-pressed"),
        "true",
      );
      await reset();
      assert.equal(
        await page
          .getByRole("button", { name: "标准地形", exact: true })
          .getAttribute("aria-pressed"),
        "true",
      );
      assert.equal(
        await page
          .getByRole("button", { name: "切换俯视视角", exact: true })
          .getAttribute("aria-pressed"),
        "false",
      );
      assert.equal(
        await page.getByRole("region", { name: "IMU-1 节点详情" }).count(),
        0,
      );
    },
  );

  await reset();
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const [width, height] of [
    [1440, 900],
    [1280, 800],
    [960, 800],
    [390, 844],
  ]) {
    await check(
      `responsive ${width}×${height} has no page overflow`,
      async () => {
        await page.setViewportSize({ width, height });
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.waitForTimeout(250);
        const dimensions = await page.evaluate(() => ({
          width: innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          bodyWidth: document.body.scrollWidth,
        }));
        assert.ok(
          dimensions.scrollWidth <= width + 1 &&
            dimensions.bodyWidth <= width + 1,
          JSON.stringify(dimensions),
        );
        await page.screenshot({
          path: resolve(output, `viewport-${width}.png`),
          fullPage: true,
        });
      },
    );
  }

  await check(
    "reduced motion preserves sampling and 4× playback controls",
    async () => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await reset();
      assert.equal(
        await page
          .locator(".scenario-button")
          .first()
          .evaluate((element) => getComputedStyle(element).transitionDuration),
        "0s",
      );
      await page.getByRole("button", { name: "4×", exact: true }).click();
      await page.getByRole("button", { name: "继续仿真", exact: true }).click();
      await page.waitForTimeout(850);
      await pause();
      const seconds = Number(
        (await page.getByTestId("simulation-time").innerText())
          .split(":")
          .at(-1),
      );
      assert.ok(seconds >= 3, `4× playback only advanced ${seconds}s`);
      assert.equal(
        parseFloat(await page.locator(".risk-number").innerText()),
        18,
      );
    },
  );

  await check(
    "unsupported WebGL shows interactive SVG fallback without runtime errors",
    async () => {
      const fallbackContext = await browser.newContext({
        viewport: { width: 1280, height: 800 },
        reducedMotion: "reduce",
      });
      const fallbackPage = await fallbackContext.newPage();
      const fallbackErrors = [],
        expectedRendererMessages = [];
      fallbackPage.on("pageerror", (error) =>
        fallbackErrors.push(error.message),
      );
      fallbackPage.on("console", (message) => {
        if (message.type() !== "error") return;
        if (
          /THREE\.WebGLRenderer.*Error creating WebGL context/.test(
            message.text(),
          )
        )
          expectedRendererMessages.push(message.text());
        else fallbackErrors.push(message.text());
      });
      await fallbackPage.addInitScript(() => {
        const original = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
          if (
            kind === "webgl" ||
            kind === "webgl2" ||
            kind === "experimental-webgl"
          )
            return null;
          return original.call(this, kind, ...args);
        };
      });
      try {
        await fallbackPage.goto(
          localDemoUrl.href,
          { waitUntil: "networkidle" },
        );
        await fallbackPage
          .getByRole("button", { name: "暂停仿真", exact: true })
          .click();
        await fallbackPage.locator(".terrain-fallback").waitFor();
        assert.equal(
          await fallbackPage.locator(".terrain-canvas canvas").count(),
          0,
        );
        assert.ok(
          await fallbackPage
            .getByRole("button", { name: "放大地形", exact: true })
            .isDisabled(),
        );
        await fallbackPage
          .getByRole("button", { name: /^持续暴雨\s*风险约/ })
          .click();
        await fallbackPage.waitForTimeout(200);
        assert.equal(
          parseFloat(await fallbackPage.locator(".risk-number").innerText()),
          46,
        );
        await fallbackPage
          .getByRole("button", { name: "查看 SOIL-1 土壤湿度", exact: true })
          .click();
        assert.ok(
          (
            await fallbackPage
              .getByRole("region", { name: "SOIL-1 节点详情" })
              .innerText()
          ).includes("71.0 %"),
        );
        assert.deepEqual(fallbackErrors, []);
        assert.ok(
          expectedRendererMessages.length > 0,
          "forced WebGL failure did not exercise renderer fallback",
        );
        await fallbackPage.screenshot({
          path: resolve(output, "webgl-fallback.png"),
        });
      } finally {
        await fallbackContext.close();
      }
    },
  );
  await check("browser has no runtime or console errors", async () =>
    assert.deepEqual(errors, []),
  );
  if (process.env.CAPTURE_FINAL === "1") {
    await page.setViewportSize({ width: 1440, height: 900 });
    await reset();
    await step(2);
    const screenshots = resolve("docs/screenshots");
    await mkdir(screenshots, { recursive: true });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(350);
    await page.screenshot({ path: resolve(screenshots, "overview.png") });
    await scene("极端灾害", 91);
    await page.getByRole("button", { name: "风险热力", exact: true }).click();
    await page
      .getByRole("button", { name: "查看 IMU-1 地表倾斜", exact: true })
      .click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(350);
    await page.screenshot({ path: resolve(screenshots, "critical.png") });
  }
} finally {
  await writeFile(
    resolve(output, "browser-smoke.json"),
    JSON.stringify({ results, errors, warnings }, null, 2),
  );
  await browser.close();
}
if (results.some((result) => !result.passed)) process.exitCode = 1;
