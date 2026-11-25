"""PyCharm 可直接运行：全链路 TEST_ONLY 回放；不是真实危险阈值。"""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telemetry_v2_intake import evaluate_telemetry_v2
from telemetry_v2_intake.config import config_hash
from telemetry_v2_intake.runtime import FeatureRiskRuntime


def test_only_config():
    """所有数值只是确定性软件测试夹具，不能复制到真实节点。"""
    c = {
        "schema": "B.feature_risk.config.v1", "mode": "TEST_ONLY",
        "config_version": "TEST_ONLY-1", "feature_version": "CANDIDATE-LP-1",
        "calibration_version": "TEST_ONLY-CAL-1", "frame_id": "TEST_ONLY-FRAME",
        "device_identity": {"site_id": "TEST_ONLY-SITE", "device_id": "NODE-01"},
        "sensor_ids": {"imu": {p: "TEST-IMU-" + p for p in ("top", "toe")},
                       "soil": {p: "TEST-SOIL-" + p for p in ("top", "middle", "toe")}},
        "validated_for_runtime": False, "review_refs": None,
        "reason_mask_version": None, "reason_bits": None,
        "weights": {"tilt": .30, "vibration": .25, "moisture": .25, "growth": .20},
        "odr_hz": {"imu": 100, "soil": 2},
        "missing_policy": "REQUIRE_BOTH_IMU_AND_ALL_THREE_SOIL_V1",
        "imu": {"filter": "CAUSAL_GRAVITY_LOWPASS_V1", "gravity_tau_ms": 80,
                "warmup_ms": 200, "alignment_ms": 5,
                "baseline_gravity_mps2": {"top": [0, 0, 9.8], "toe": [0, 0, 9.8]}},
        "soil": {"alignment_ms": 30,
                 "calibration": {p: {"dry_raw": 0, "wet_raw": 10000, "min_span_raw": 100}
                                 for p in ("top", "middle", "toe")}},
        "windows": {
            "tilt": {"lookback_ms": 500, "max_gap_ms": 20, "max_age_ms": 20,
                     "min_samples": 20, "min_span_ms": 300},
            "vibration": {"lookback_ms": 500, "max_gap_ms": 20, "max_age_ms": 20,
                          "min_samples": 20, "min_span_ms": 300},
            "soil_growth": {"lookback_ms": 3000, "max_gap_ms": 600, "max_age_ms": 550,
                            "min_samples": 3, "min_span_ms": 1000}},
        "curves": {"tilt": [[0, 0], [10, 100]], "vibration": [[0, 0], [1, 100]],
                   "moisture": [[0, 0], [100, 100]], "growth": [[0, 0], [60, 100]]},
        "consensus": {"tilt_threshold_deg": 5, "max_tilt_difference_deg": 2, "bonus": 5}}
    c["config_hash"] = config_hash(c)
    return c


def fixture(end=3000, *, scenario="normal", start=0, seq=1, boot=1):
    """可复现原始观测；IMU 100 Hz，Soil 2 Hz。"""
    def acceleration(t):
        if scenario == "abnormal":
            angle = math.radians(8)
            return [9.8 * math.sin(angle) + .6 * math.sin(2 * math.pi * 20 * t / 1000),
                    0, 9.8 * math.cos(angle)]
        return [0, 0, 9.8]

    def soil_raw(t):
        return int(4000 + t) if scenario == "abnormal" else 2000

    payload = {
        "schema": "zhifang.telemetry.v2", "site_id": "TEST_ONLY-SITE", "device_id": "NODE-01",
        "boot_id": boot, "seq": seq, "timestamp_ms": None, "time_synced": False, "uptime_ms": end,
        "imu": [{"id": p, **dict(zip(("ax", "ay", "az"), acceleration(end))),
                 "gx": 0, "gy": 0, "gz": 0, "valid": True,
                 "tilt_deg": None, "tilt_rate_dps": None, "vibration_rms": None}
                for p in ("top", "toe")],
        "soil": {"top_raw": soil_raw(end // 500 * 500),
                 "middle_raw": soil_raw(end // 500 * 500), "toe_raw": soil_raw(end // 500 * 500),
                 "top_pct": None, "middle_pct": None, "toe_pct": None,
                 "avg_pct": None, "growth_pct_min": None},
        "experiment": {"run_id": "TEST_ONLY-RUN", "rain_level": None},
        "risk": {"sensor_score": None, "level": None, "reason_mask": None},
        "system": {"wifi_up": False, "mqtt_up": False, "lora_ready": False,
                   "sd_ok": False, "edge_online": False, "sensor_degraded": False}}
    b = {"schema": "B.observation_batch.v1", "source": "TEST_ONLY",
         "identity": {k: payload[k] for k in ("site_id", "device_id", "boot_id")},
         "run_id": "TEST_ONLY-RUN", "frame_id": "TEST_ONLY-FRAME",
         "calibration_version": "TEST_ONLY-CAL-1", "odr_hz": {"imu": 100, "soil": 2},
         "sensor_ids": copy.deepcopy(test_only_config()["sensor_ids"]),
         "imu": {p: [{"uptime_ms": t, "valid": True, "acceleration_mps2": acceleration(t)}
                     for t in range(start, end + 1, 10)] for p in ("top", "toe")},
         "soil": {p: [{"uptime_ms": t, "valid": True, "raw": soil_raw(t)}
                      for t in range((start + 499) // 500 * 500, end + 1, 500)]
                  for p in ("top", "middle", "toe")}}
    if scenario == "missing":
        payload["soil"]["middle_raw"] = None
        for row in b["soil"]["middle"]:
            row.update(valid=False, raw=None)
    return payload, {"runtime_input": b}


def main():
    report = {"notice": "TEST_ONLY：演示参数和合成观测，非实测标定或灾害预测。", "cases": {}}
    for scenario in ("normal", "abnormal", "missing"):
        runtime = FeatureRiskRuntime(test_only_config())
        payload, context = fixture(scenario=scenario)
        original = copy.deepcopy(payload)
        result = evaluate_telemetry_v2(payload, context=context, runtime=runtime)
        assert payload == original
        report["cases"][scenario] = result
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
