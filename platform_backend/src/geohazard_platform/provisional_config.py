"""PROVISIONAL_DEMO: display-only adaptation of offline references to 1 Hz.

These are NOT calibration, B's frozen rule executor, or alarm thresholds.
All additional demo constants live here. Never fit them to rain/live data.
"""
from functools import lru_cache
import json

from .settings import REPO_ROOT
from .research_rule_config import validate_config

VERSION = "PROVISIONAL_DEMO-live-v1"
DISCLAIMER = "uncalibrated, not a formal alarm"
CANDIDATE_SOURCE = "algorithm/B_revised/docs/CALIBRATION_REVIEW_2026-11-12.md"
# AIR/WATER candidates, explicitly requested for a relative index only; not VWC.
SOIL_ENDPOINTS = {"top": (20669.506, 12510.328), "middle": (20878.817, 12508.750)}
REFERENCE_PATH = "platform_backend/config/research_rules/provisional-v1-r4.json"
GRAVITY_MPS2 = 9.80665
BASELINE_SAMPLES = 10  # First 10 valid samples per IMU, frozen until boot changes.
MIN_RMS_SAMPLES = 2
MAX_WINDOW_SAMPLES = 64  # Bound memory even for unexpectedly fast publishers.
MAX_GAP_MS = 2500  # 1 Hz demo, unlike the offline executor's 30 ms coverage gate.
SOIL_ATTENTION_INDEX = 0.60  # PROVISIONAL_DEMO; no moisture threshold exists in B's config.
SOIL_WARNING_INDEX = 0.85
WARNING_REFERENCE_MULTIPLIER = 2.0  # PROVISIONAL_DEMO; B has no severity levels.
LEVEL_SCORES = {"NORMAL": 0, "ATTENTION": 50, "WARNING": 100}  # Ordinal display only.


@lru_cache(maxsize=1)
def reference_config():
    config = json.loads((REPO_ROOT / REFERENCE_PATH).read_text())
    validate_config(config)
    return config


def provenance():
    reference = reference_config()
    return {"version": VERSION, "soil_endpoints": CANDIDATE_SOURCE,
            "candidate_status": "pending review; relative display index only, not loaded as calibration",
            "soil_endpoint_values": SOIL_ENDPOINTS,
            "reference_path": REFERENCE_PATH, "config_sha256": reference["config_sha256"],
            "reference_metrics": ["direction_angle_deg", "vibration_rms_mps2", "gyro_rms_dps"],
            "reference_thresholds": {sensor: {metric: data["metrics"][metric]["frozen_value"]
                for metric in ("direction_angle_deg", "vibration_rms_mps2", "gyro_rms_dps")}
                for sensor, data in reference["channels"].items() if sensor.startswith("imu_")},
            "demo_parameters": {"baseline_samples": BASELINE_SAMPLES, "gravity_mps2": GRAVITY_MPS2,
                "min_rms_samples": MIN_RMS_SAMPLES, "max_window_samples": MAX_WINDOW_SAMPLES,
                "max_gap_ms": MAX_GAP_MS, "soil_attention_index": SOIL_ATTENTION_INDEX,
                "soil_warning_index": SOIL_WARNING_INDEX,
                "warning_reference_multiplier": WARNING_REFERENCE_MULTIPLIER,
                "level_scores": LEVEL_SCORES},
            "rms_window_ms": reference["parameters"]["rms_window_us"] / 1000,
            "interpretation": "1 Hz sample RMS and instantaneous gravity direction; no offline coverage, "
                "dwell or STA/LTA equivalence. R4 post-rain reference is not a dry baseline. "
                "Vibration uses |accel|-g, unlike offline vector residual. Gyro reference is diagnostic "
                "in B's executor; severity mapping here is PROVISIONAL_DEMO. No IMU correction applied."}
