import { SCENARIOS, SENSOR_META } from "./scenarios";
import type { DemoRisk, RiskLevel, SensorKey, SensorValues } from "./types";

/** DEMO_ONLY: positive weights and monotonic calibration, not a trained prediction model. */
const WEIGHTS: Record<SensorKey, number> = {
  moisture: 0.16,
  tilt: 0.28,
  vibration: 0.2,
  rain: 0.12,
  crack: 0.24,
};

export function normalizeSensor(key: SensorKey, value: number): number {
  const meta = SENSOR_META.find((sensor) => sensor.key === key)!;
  const finite = Number.isNaN(value) ? meta.min : value;
  return Math.max(0, Math.min(1, (finite - meta.min) / (meta.max - meta.min)));
}

function weightedInput(sensors: SensorValues): number {
  return SENSOR_META.reduce(
    (sum, meta) =>
      sum + normalizeSensor(meta.key, sensors[meta.key]) * WEIGHTS[meta.key],
    0,
  );
}

/** One shared monotonic piecewise mapping for presets AND every manual input. */
const CALIBRATION = [
  { input: 0, score: 0 },
  ...SCENARIOS.map((scenario) => ({
    input: weightedInput(scenario.sensors),
    score: scenario.targetScore,
  })),
  { input: 1, score: 100 },
];

export function riskLevel(score: number): RiskLevel {
  return score < 30
    ? "low"
    : score < 60
      ? "moderate"
      : score < 80
        ? "high"
        : "critical";
}

export function calculateDemoRisk(sensors: SensorValues): DemoRisk {
  const rawNormalized = weightedInput(sensors);
  const upperIndex = CALIBRATION.findIndex(
    (point) => point.input >= rawNormalized,
  );
  const upper = CALIBRATION[Math.max(1, upperIndex)];
  const lower = CALIBRATION[Math.max(0, upperIndex - 1)];
  const fraction = (rawNormalized - lower.input) / (upper.input - lower.input);
  // Classify the raw score. Rounding belongs to presentation and must not move
  // a value such as 29.95 over a risk threshold before it actually reaches 30.
  const score = Math.max(
    0,
    Math.min(100, lower.score + fraction * (upper.score - lower.score)),
  );
  let assigned = 0;
  const contributions = SENSOR_META.map((meta, index) => {
    const normalized = normalizeSensor(meta.key, sensors[meta.key]);
    // The final residual keeps the visible decomposition equal to the total.
    const points =
      index === SENSOR_META.length - 1
        ? score - assigned
        : Math.max(
            0,
            Math.min(
              score - assigned,
              rawNormalized > 0
                ? (score * normalized * WEIGHTS[meta.key]) / rawNormalized
                : 0,
            ),
          );
    assigned += points;
    return {
      sensor: meta.key,
      value: sensors[meta.key],
      normalized,
      weight: WEIGHTS[meta.key],
      points,
    };
  });
  return { score, level: riskLevel(score), rawNormalized, contributions };
}
