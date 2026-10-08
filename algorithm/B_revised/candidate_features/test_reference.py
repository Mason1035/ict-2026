import math
import unittest

from candidate_features.reference import (
    causal_slope_per_second,
    dual_imu_tilt_difference_deg,
    dynamic_accel_rms_mps2,
    gravity_tilt_change_deg,
    relative_wetness_index,
    spatial_probe_spread,
    valid_probe_mean,
)
from candidate_features.risk_math import risk_level, sensor_score


class CandidateMathTests(unittest.TestCase):
    def test_tilt_is_relative_and_missing_propagates(self):
        self.assertAlmostEqual(gravity_tilt_change_deg((0, 0, 9.81), (0, 9.81, 0)), 90)
        self.assertIsNone(gravity_tilt_change_deg(None, (0, 0, 9.81)))

    def test_slope_uses_elapsed_time_and_rejects_reversal(self):
        self.assertAlmostEqual(causal_slope_per_second([(1000, 0.0), (2000, 2.0), (3000, 4.0)]), 2)
        self.assertIsNone(causal_slope_per_second([(2000, 2.0), (1000, 0.0)]))

    def test_rms_requires_dynamic_acceleration_input(self):
        self.assertAlmostEqual(dynamic_accel_rms_mps2([(3, 4, 0), None]), 5)
        self.assertIsNone(dynamic_accel_rms_mps2([None]))

    def test_per_probe_index_does_not_clamp_or_claim_vwc(self):
        self.assertAlmostEqual(relative_wetness_index(750, 1000, 500), 0.5)
        self.assertAlmostEqual(relative_wetness_index(250, 1000, 500), 1.5)
        self.assertIsNone(relative_wetness_index(0, 1, 1))

    def test_partial_soil_and_dual_imu(self):
        self.assertEqual(valid_probe_mean([0.0, None, 0.6]), (0.3, 2))
        self.assertAlmostEqual(spatial_probe_spread([0.0, None, 0.6]), 0.6)
        self.assertIsNone(spatial_probe_spread([None, 0.6]))
        self.assertAlmostEqual(dual_imu_tilt_difference_deg(1.0, 1.5), 0.5)
        self.assertIsNone(dual_imu_tilt_difference_deg(1.0, math.nan))

    def test_frozen_score_shell_and_level_boundaries(self):
        self.assertEqual(sensor_score({"tilt": 100, "vibration": 100, "moisture": 100, "growth": 100}, 5), 100)
        self.assertIsNone(sensor_score({"tilt": None, "vibration": 0, "moisture": 0, "growth": 0}, 0))
        self.assertEqual([risk_level(x) for x in (0, 29.999, 30, 60, 80, 100)],
                         ["NORMAL", "NORMAL", "WATCH", "WARNING", "EMERGENCY", "EMERGENCY"])
        self.assertIsNone(risk_level(None))

    def test_malformed_numeric_types_fail_closed(self):
        base = {"tilt": 0, "vibration": 0, "moisture": 0, "growth": 0}
        self.assertIsNone(sensor_score({**base, "tilt": "0"}, 0))
        self.assertIsNone(sensor_score(base, "5"))
        self.assertIsNone(sensor_score({**base, "tilt": True}, 0))
        self.assertIsNone(risk_level("30"))
        self.assertIsNone(relative_wetness_index("150", 100, 200))


if __name__ == "__main__":
    unittest.main()
