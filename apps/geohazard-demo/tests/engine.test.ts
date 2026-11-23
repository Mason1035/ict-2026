import test from "node:test";
import assert from "node:assert/strict";
import {
  calculateDemoRisk,
  chooseActivePath,
  createInitialState,
  getQueueStats,
  reduceSimulation,
  riskLevel,
  SCENARIOS,
  SENSOR_META,
  type Communication,
  type SimulationAction,
  type SimulationState,
} from "../src/simulation/index.ts";

function run(
  state: SimulationState,
  ...actions: SimulationAction[]
): SimulationState {
  return actions.reduce(reduceSimulation, state);
}

function ticks(state: SimulationState, count: number): SimulationState {
  for (let i = 0; i < count; i += 1)
    state = reduceSimulation(state, { type: "tick" });
  return state;
}

function offline(state = createInitialState()): SimulationState {
  return run(
    state,
    { type: "set-link", link: "wifi", value: false },
    { type: "set-link", link: "lora", value: false },
  );
}

test("the four presets share one risk function and immediate channel/history state", () => {
  let state = createInitialState();
  assert.equal(state.risk.score, 18);
  assert.equal(state.network, "ONLINE_WIFI");
  assert.equal(state.running, true);
  assert.equal(getQueueStats(state).pending, 0);
  for (const [index, scenario] of SCENARIOS.entries()) {
    const risk = calculateDemoRisk(scenario.sensors);
    assert.ok(Math.abs(risk.score - scenario.targetScore) < 1e-10);
    assert.equal(risk.level, ["low", "moderate", "high", "critical"][index]);
    state = reduceSimulation(state, {
      type: "set-scenario",
      scenario: scenario.id,
    });
    assert.deepEqual(state.sensors, scenario.sensors);
    assert.deepEqual(state.sensorHistory.at(-1), {
      time: state.elapsedSeconds,
      ...state.sensors,
    });
    assert.equal(
      state.channels.find((channel) => channel.id === "IMU-1")?.readings.tilt,
      scenario.sensors.tilt,
    );
    assert.equal(
      state.channels.find((channel) => channel.id === "SCENE-RAIN")?.source,
      "scenario",
    );
  }
});

test("each input is monotonic across its entire range for every preset", () => {
  for (const scenario of SCENARIOS) {
    for (const meta of SENSOR_META) {
      let previousScore = -1;
      for (let sample = 0; sample <= 100; sample += 1) {
        const risk = calculateDemoRisk({
          ...scenario.sensors,
          [meta.key]: (meta.max * sample) / 100,
        });
        assert.ok(
          risk.score >= previousScore - 1e-10,
          `${scenario.id}/${meta.key}/${sample} moved backwards`,
        );
        assert.ok(risk.score >= 0 && risk.score <= 100);
        assert.ok(risk.contributions.every((part) => part.points >= 0));
        assert.ok(
          Math.abs(
            risk.contributions.reduce((sum, part) => sum + part.points, 0) -
              risk.score,
          ) < 1e-10,
        );
        previousScore = risk.score;
      }
    }
  }
  assert.equal(
    calculateDemoRisk({ moisture: 0, tilt: 0, vibration: 0, rain: 0, crack: 0 })
      .score,
    0,
  );
  assert.equal(
    calculateDemoRisk({
      moisture: 100,
      tilt: 45,
      vibration: 2,
      rain: 100,
      crack: 20,
    }).score,
    100,
  );
});

test("risk levels use raw thresholds instead of presentation rounding", () => {
  assert.equal(riskLevel(29.999), "low");
  assert.equal(riskLevel(30), "moderate");
  assert.equal(riskLevel(59.999), "moderate");
  assert.equal(riskLevel(60), "high");
  assert.equal(riskLevel(79.999), "high");
  assert.equal(riskLevel(80), "critical");
  // Search an actual manual input just below the first threshold.
  let left = 8;
  let right = 100;
  for (let i = 0; i < 70; i += 1) {
    const rain = (left + right) / 2;
    if (calculateDemoRisk({ ...SCENARIOS[0].sensors, rain }).score < 29.95)
      left = rain;
    else right = rain;
  }
  const result = calculateDemoRisk({ ...SCENARIOS[0].sensors, rain: left });
  assert.ok(result.score > 29.94 && result.score < 30);
  assert.equal(result.level, "low");
});

test("manual changes are clamped, instantaneous, logged, and do not mutate previous state", () => {
  const original = createInitialState();
  const previousJson = JSON.stringify(original);
  const changed = reduceSimulation(original, {
    type: "set-sensor",
    sensor: "tilt",
    value: 90,
  });
  assert.equal(JSON.stringify(original), previousJson);
  assert.equal(changed.sensors.tilt, 45);
  assert.equal(changed.scenario, "custom");
  assert.ok(changed.risk.score > original.risk.score);
  assert.equal(changed.sensorHistory.at(-1)?.tilt, 45);
  assert.ok(changed.logs.some((event) => event.message.includes("手动调节")));
  assert.equal(
    reduceSimulation(changed, {
      type: "set-sensor",
      sensor: "rain",
      value: NaN,
    }),
    changed,
  );
  assert.equal(
    reduceSimulation(changed, {
      type: "set-sensor",
      sensor: "rain",
      value: Infinity,
    }),
    changed,
  );
  assert.equal(
    reduceSimulation(changed, {
      type: "set-sensor",
      sensor: "moisture",
      value: -30,
    }).sensors.moisture,
    0,
  );
});

test("pause prevents ticking; a single step samples once while preserving pause", () => {
  const paused = reduceSimulation(createInitialState(), {
    type: "set-running",
    running: false,
  });
  assert.equal(reduceSimulation(paused, { type: "tick" }), paused);
  const stepped = reduceSimulation(paused, { type: "step" });
  assert.equal(stepped.elapsedSeconds, 1);
  assert.equal(stepped.running, false);
  assert.equal(stepped.riskHistory.length, 2);
  assert.equal(stepped.transmissions.length, 1);
  const fast = reduceSimulation(stepped, { type: "set-speed", speed: 4 });
  assert.equal(fast.speed, 4);
  assert.equal(reduceSimulation(fast, { type: "step" }).elapsedSeconds, 2);
});

test("all 64 link/service combinations gate cloud delivery correctly", () => {
  const keys = ["wifi", "lora", "gateway", "mqtt", "atlas", "cloud"] as const;
  for (let bits = 0; bits < 64; bits += 1) {
    const communication = Object.fromEntries(
      keys.map((key, index) => [key, Boolean(bits & (1 << index))]),
    ) as Communication;
    const services =
      communication.mqtt && communication.atlas && communication.cloud;
    const expected =
      services && communication.wifi
        ? "wifi"
        : services && communication.lora && communication.gateway
          ? "lora"
          : null;
    assert.equal(
      chooseActivePath(communication),
      expected,
      `incorrect delivery for bitset ${bits}`,
    );
  }
  let state = reduceSimulation(createInitialState(), {
    type: "set-link",
    link: "wifi",
    value: false,
  });
  assert.equal(state.network, "ONLINE_LORA");
  state = reduceSimulation(state, {
    type: "set-link",
    link: "gateway",
    value: false,
  });
  assert.equal(state.network, "OFFLINE");
  state = reduceSimulation(createInitialState(), {
    type: "set-link",
    link: "mqtt",
    value: false,
  });
  assert.equal(state.network, "OFFLINE");
  assert.equal(state.communication.wifi, true);
  assert.equal(state.communication.lora, true);
  assert.equal(ticks(state, 1).transmissions.length, 0);
});

test("offline sampling keeps risk local and queue IDs intact beyond UI history caps", () => {
  const state = ticks(offline(), 410);
  assert.equal(state.network, "OFFLINE");
  assert.equal(state.risk.score, 18);
  assert.equal(state.elapsedSeconds, 410);
  assert.equal(state.queue.length, 410);
  assert.equal(getQueueStats(state).pending, 410);
  assert.equal(new Set(state.queue.map((record) => record.id)).size, 410);
  assert.equal(state.riskHistory.length, 120);
  assert.equal(state.sensorHistory.length, 120);
  assert.equal(state.logs.length, 160);
  assert.equal(state.transmissions.length, 0);
  assert.ok(state.queue.every((record) => record.status === "Pending"));
});

test("recovery sends live high-risk data then visibly backfills high-risk histories first", () => {
  let state = ticks(offline(), 3);
  state = reduceSimulation(state, { type: "set-scenario", scenario: "C" });
  state = ticks(state, 1);
  state = reduceSimulation(state, { type: "set-scenario", scenario: "D" });
  state = ticks(state, 1);
  const ids = state.queue.map((row) => row.id);
  const initialCount = state.queue.length;
  state = reduceSimulation(state, {
    type: "set-link",
    link: "wifi",
    value: true,
  });
  assert.equal(state.network, "RECOVERING");
  assert.equal(getQueueStats(state).pending, initialCount);
  assert.ok(state.queue.every((row) => row.status === "Pending"));
  state = ticks(state, 1);
  assert.equal(getQueueStats(state).pending, initialCount);
  const sending = state.queue.find((row) => row.status === "Sending");
  assert.equal(sending?.kind, "alert");
  assert.equal(sending?.level, "critical");
  assert.equal(state.transmissions[0].delivery, "realtime");
  assert.equal(state.transmissions[0].level, "critical");
  state = ticks(state, 1);
  assert.equal(getQueueStats(state).pending, initialCount - 1);
  assert.equal(
    state.queue.find((row) => row.id === sending?.id)?.status,
    "Synced",
  );
  assert.equal(
    state.queue.find((row) => row.status === "Sending")?.level,
    "critical",
  );
  state = ticks(state, initialCount + 1);
  assert.equal(state.network, "ONLINE_WIFI");
  assert.equal(getQueueStats(state).pending, 0);
  assert.equal(state.queue.length, initialCount);
  assert.deepEqual(
    state.queue.map((row) => row.id),
    ids,
  );
  for (const id of ids)
    assert.equal(state.transmissions.filter((row) => row.id === id).length, 1);
  const historyDeliveries = state.transmissions
    .filter((row) => row.delivery === "backfill")
    .reverse();
  const firstLow = historyDeliveries.findIndex((row) => row.level === "low");
  assert.ok(
    historyDeliveries
      .slice(0, firstLow)
      .every((row) => row.level === "critical" || row.level === "high"),
  );
  assert.ok(state.logs.some((event) => event.message.includes("补传完成")));
});

test("an interrupted Sending row becomes Failed and retries its original ID exactly once", () => {
  let state = ticks(offline(), 3);
  state = reduceSimulation(state, {
    type: "set-link",
    link: "wifi",
    value: true,
  });
  state = ticks(state, 1);
  const inFlight = state.queue.find((row) => row.status === "Sending")!;
  assert.equal(inFlight.attempts, 1);
  state = reduceSimulation(state, {
    type: "set-link",
    link: "wifi",
    value: false,
  });
  assert.equal(state.network, "OFFLINE");
  assert.equal(
    state.queue.find((row) => row.id === inFlight.id)?.status,
    "Failed",
  );
  assert.equal(getQueueStats(state).failed, 1);
  state = ticks(state, 1);
  state = reduceSimulation(state, {
    type: "set-link",
    link: "lora",
    value: true,
  });
  assert.equal(state.network, "RECOVERING");
  state = ticks(state, 1);
  assert.equal(
    state.queue.find((row) => row.id === inFlight.id)?.status,
    "Sending",
  );
  assert.equal(state.queue.find((row) => row.id === inFlight.id)?.attempts, 2);
  state = ticks(state, 1);
  assert.equal(
    state.queue.find((row) => row.id === inFlight.id)?.status,
    "Synced",
  );
  assert.equal(
    state.transmissions.filter((row) => row.id === inFlight.id).length,
    1,
  );
  state = ticks(state, state.queue.length + 1);
  assert.equal(state.network, "ONLINE_LORA");
  assert.equal(getQueueStats(state).pending, 0);
  assert.equal(
    new Set(state.queue.map((row) => row.id)).size,
    state.queue.length,
  );
});

test("downstream outage during backfill cannot declare a cloud-success path", () => {
  let state = ticks(offline(), 2);
  state = reduceSimulation(state, {
    type: "set-link",
    link: "wifi",
    value: true,
  });
  state = ticks(state, 1);
  const record = state.queue.find((row) => row.status === "Sending")!;
  state = reduceSimulation(state, {
    type: "set-link",
    link: "cloud",
    value: false,
  });
  const priorTransmissions = state.transmissions.length;
  state = ticks(state, 2);
  assert.equal(state.network, "OFFLINE");
  assert.equal(state.activePath, null);
  assert.equal(
    state.queue.find((row) => row.id === record.id)?.status,
    "Failed",
  );
  assert.equal(state.transmissions.length, priorTransmissions);
  state = reduceSimulation(state, {
    type: "set-link",
    link: "cloud",
    value: true,
  });
  assert.equal(state.network, "RECOVERING");
  state = ticks(state, state.queue.length + 2);
  assert.equal(getQueueStats(state).pending, 0);
});

test("alerts occur only on a new upward level transition, never on sampling or rerendering", () => {
  let state = createInitialState();
  for (const scenario of ["B", "C", "D"] as const) {
    state = reduceSimulation(state, { type: "set-scenario", scenario });
    state = ticks(state, 12);
  }
  assert.equal(state.alerts.length, 3);
  assert.equal(
    state.alerts.filter((alert) => alert.status === "active").length,
    1,
  );
  state = reduceSimulation(state, {
    type: "set-sensor",
    sensor: "rain",
    value: 68,
  });
  assert.equal(state.alerts.length, 3);
  state = reduceSimulation(state, { type: "set-scenario", scenario: "A" });
  assert.equal(state.alerts.length, 3);
  assert.ok(state.alerts.every((alert) => alert.status === "resolved"));
  state = reduceSimulation(state, { type: "set-scenario", scenario: "B" });
  assert.equal(state.alerts.length, 4);
  assert.equal(new Set(state.alerts.map((alert) => alert.id)).size, 4);
});

test("clearing trends preserves the queue; resetting replaces every demo state and event namespace", () => {
  let state = reduceSimulation(offline(), {
    type: "set-scenario",
    scenario: "D",
  });
  state = ticks(state, 3);
  const cachedIds = state.queue.map((row) => row.id);
  state = reduceSimulation(state, { type: "clear-history" });
  assert.equal(state.riskHistory.length, 0);
  assert.equal(state.sensorHistory.length, 0);
  assert.deepEqual(
    state.queue.map((row) => row.id),
    cachedIds,
  );
  state = ticks(state, 1);
  assert.equal(state.riskHistory.length, 1);
  state = run(
    state,
    { type: "set-speed", speed: 4 },
    { type: "set-running", running: false },
  );
  const reset = reduceSimulation(state, { type: "reset" });
  assert.equal(reset.bootId, "demo-2");
  assert.deepEqual(reset.sensors, SCENARIOS[0].sensors);
  assert.equal(reset.scenario, "A");
  assert.equal(reset.risk.score, 18);
  assert.equal(reset.network, "ONLINE_WIFI");
  assert.equal(reset.activePath, "wifi");
  assert.ok(Object.values(reset.communication).every(Boolean));
  assert.equal(reset.running, true);
  assert.equal(reset.speed, 1);
  assert.equal(reset.elapsedSeconds, 0);
  assert.equal(reset.queue.length, 0);
  assert.equal(reset.alerts.length, 0);
  assert.equal(reset.transmissions.length, 0);
  assert.equal(reset.riskHistory.length, 1);
  assert.equal(reset.logs.length, 1);
  assert.equal(
    reduceSimulation(reset, { type: "clear-demo-data" }).bootId,
    "demo-3",
  );
});
