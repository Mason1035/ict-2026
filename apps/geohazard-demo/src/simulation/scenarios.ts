import type { RiskLevel, Scenario, SensorMeta } from "./types";

export const SENSOR_META: SensorMeta[] = [
  // SEN0193 produces an analogue relative index; the percentage is DEMO_ONLY,
  // and does not claim calibrated volumetric soil water content.
  {
    key: "moisture",
    label: "土壤湿度",
    shortLabel: "湿度",
    unit: "%",
    min: 0,
    max: 100,
    step: 1,
    hardware: "SEN0193 · ADS1115 相对指标演示",
    source: "demo-hardware",
  },
  {
    key: "tilt",
    label: "地表倾斜",
    shortLabel: "倾角",
    unit: "°",
    min: 0,
    max: 45,
    step: 0.1,
    hardware: "ICM-42688-P 聚合演示",
    source: "demo-hardware",
  },
  // g is a presentation unit only; this is not a formal accelerometer contract.
  {
    key: "vibration",
    label: "微振动",
    shortLabel: "振动",
    unit: "g",
    min: 0,
    max: 2,
    step: 0.01,
    hardware: "ICM-42688-P 聚合演示 · g 为展示单位",
    source: "demo-hardware",
  },
  {
    key: "rain",
    label: "降雨强度",
    shortLabel: "降雨",
    unit: "mm/h",
    min: 0,
    max: 100,
    step: 1,
    hardware: "场景模拟数据",
    source: "scenario",
  },
  {
    key: "crack",
    label: "裂缝增量",
    shortLabel: "裂缝",
    unit: "mm",
    min: 0,
    max: 20,
    step: 0.1,
    hardware: "场景模拟数据",
    source: "scenario",
  },
];

export const SCENARIOS: Scenario[] = [
  {
    id: "A",
    label: "正常监测",
    shortLabel: "正常",
    english: "STABLE",
    description: "边坡状态稳定，连续采集多模态遥测。",
    sensors: { moisture: 42, tilt: 6.5, vibration: 0.18, rain: 8, crack: 1.2 },
    targetScore: 18,
  },
  {
    id: "B",
    label: "持续暴雨",
    shortLabel: "暴雨",
    english: "HEAVY RAIN",
    description: "降雨和湿度升高，观察局部风险累积。",
    sensors: {
      moisture: 71,
      tilt: 10.8,
      vibration: 0.27,
      rain: 43,
      crack: 2.4,
    },
    targetScore: 46,
  },
  {
    id: "C",
    label: "山体位移异常",
    shortLabel: "位移异常",
    english: "DISPLACEMENT",
    description: "倾角和裂缝扩大，触发高风险演示预警。",
    sensors: {
      moisture: 78,
      tilt: 18.6,
      vibration: 0.52,
      rain: 36,
      crack: 5.8,
    },
    targetScore: 72,
  },
  {
    id: "D",
    label: "极端灾害",
    shortLabel: "极端灾害",
    english: "CRITICAL",
    description: "多模态异常叠加，进入紧急预警演示。",
    sensors: {
      moisture: 91,
      tilt: 26.4,
      vibration: 0.94,
      rain: 67,
      crack: 11.2,
    },
    targetScore: 91,
  },
];

export const RISK_LABELS: Record<RiskLevel, string> = {
  low: "低风险",
  moderate: "中风险",
  high: "高风险",
  critical: "紧急预警",
};

export const RISK_ORDER: Record<RiskLevel, number> = {
  low: 0,
  moderate: 1,
  high: 2,
  critical: 3,
};
