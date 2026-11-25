"""B 入口单元测试；上游 Validator 的真实门禁另由 verify_a_mock.py 检查。"""

import copy
import unittest
from unittest.mock import patch

from candidate_features import reference
from telemetry_v2_intake import evaluate_telemetry_v2


def valid_mock_payload():
    def imu(position, ax):
        return {"id": position, "ax": ax, "ay": 0, "az": 9.8,
                "gx": 0, "gy": 0, "gz": 0, "tilt_deg": None,
                "tilt_rate_dps": None, "vibration_rms": None, "valid": True}

    return {
        "schema": "zhifang.telemetry.v2", "site_id": "MOCK-SITE-01",
        "device_id": "NODE-01", "boot_id": 1, "seq": 1,
        "timestamp_ms": None, "uptime_ms": 1000, "time_synced": False,
        "imu": [imu("top", 0.02), imu("toe", 0)],
        "soil": {"top_raw": 12000, "middle_raw": 13000, "toe_raw": 14000,
                 "top_pct": None, "middle_pct": None, "toe_pct": None,
                 "avg_pct": None, "growth_pct_min": None},
        "experiment": {"run_id": None, "rain_level": None},
        "risk": {"sensor_score": None, "level": None, "reason_mask": None},
        "system": {"wifi_up": False, "mqtt_up": False, "lora_ready": False,
                   "sd_ok": False, "edge_online": False, "sensor_degraded": True},
    }


class TelemetryV2IntakeTests(unittest.TestCase):
    def test_m01_real_functions_called_without_inventing_risk(self):
        payload = valid_mock_payload()
        original = copy.deepcopy(payload)
        with patch.object(reference, "relative_wetness_index",
                          wraps=reference.relative_wetness_index) as wetness, \
             patch.object(reference, "dual_imu_tilt_difference_deg",
                          wraps=reference.dual_imu_tilt_difference_deg) as tilt:
            result = evaluate_telemetry_v2(payload)
        self.assertEqual(wetness.call_count, 3)
        tilt.assert_called_once_with(None, None)
        self.assertEqual(result["status"], "REAL_CODE_REACHED")
        self.assertEqual(result["risk_execution"], "RISK_EXECUTION_BLOCKED")
        self.assertEqual(result["feature_status"], "BLOCKED")
        self.assertEqual(result["risk"], payload["risk"])
        self.assertEqual(result["identity"]["seq"], 1)
        self.assertEqual(result["observations"]["time"]["timestamp_ms"], None)
        self.assertEqual(payload, original)

    def test_m02_null_is_not_zero_or_proof_of_error(self):
        payload = valid_mock_payload()
        payload["soil"]["top_raw"] = 0
        payload["soil"]["middle_raw"] = None
        context = {"sampling_snapshot": {"soil": [{}, {"validity": "Unavailable"}, {}]}}
        result = evaluate_telemetry_v2(payload, context=context)
        self.assertEqual(result["observations"]["soil"]["top_raw"], 0)
        self.assertIsNone(result["observations"]["soil"]["middle_raw"])
        self.assertIsNone(result["function_calls"][1]["returned"])
        self.assertEqual(result["feature_details"]["soil_relative_index"]["middle"],
                         "MISSING_OBSERVATION_CAUSE_UNKNOWN")
        self.assertFalse(result["context_used_for_computation"])
        self.assertEqual(result["risk"], payload["risk"])

    def test_m07_all_raw_present_does_not_enable_risk(self):
        payload = valid_mock_payload()
        result = evaluate_telemetry_v2(payload)
        self.assertEqual(len(result["function_calls"]), 4)
        self.assertTrue(all(value is None for value in result["risk"].values()))
        self.assertEqual(result["risk_execution"], "RISK_EXECUTION_BLOCKED")
        self.assertTrue(payload["system"]["sensor_degraded"])

    def test_precondition_rejects_wrong_version_before_feature_call(self):
        payload = valid_mock_payload()
        payload["schema"] = "zhifang.telemetry.v999"
        with patch.object(reference, "relative_wetness_index") as wetness:
            with self.assertRaises(ValueError):
                evaluate_telemetry_v2(payload)
            wetness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
