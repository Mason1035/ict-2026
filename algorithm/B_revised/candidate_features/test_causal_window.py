import unittest

from candidate_features.causal_window import CausalObservationBuffer


KEY = ("run_test", "boot_1", "imu_top", "cal_test", "odr_test", "coord_test")


class CausalWindowTests(unittest.TestCase):
    def buffer(self):
        # 以下毫秒数全是 TEST_ONLY 控制输入，不是正式窗口参数。
        return CausalObservationBuffer(lookback_ms=1000, max_gap_ms=600, max_age_ms=200)

    def test_zero_is_observation_and_invalid_is_not_zero(self):
        buffer = self.buffer()
        buffer.add(segment_key=KEY, uptime_ms=1000, value=0.0, valid=True)
        buffer.add(segment_key=KEY, uptime_ms=1200, value=999, valid=False)
        result = buffer.window(end_uptime_ms=1200, min_valid_samples=1)
        self.assertEqual(result.status, "STRUCTURE_VALID_ONLY")
        self.assertEqual(result.samples, ((1000, 0.0),))

    def test_stale_and_invalid_gap_are_explicit(self):
        buffer = self.buffer()
        buffer.add(segment_key=KEY, uptime_ms=0, value=1, valid=True)
        buffer.add(segment_key=KEY, uptime_ms=500, value=None, valid=False)
        self.assertEqual(buffer.window(end_uptime_ms=500, min_valid_samples=1).status, "STALE")
        buffer.add(segment_key=KEY, uptime_ms=700, value=2, valid=True)
        self.assertEqual(buffer.window(end_uptime_ms=700, min_valid_samples=2).status, "VALID_DATA_GAP")

    def test_segment_change_resets_history(self):
        buffer = self.buffer()
        buffer.add(segment_key=KEY, uptime_ms=100, value=1, valid=True)
        reason = buffer.add(segment_key=("run_test", "boot_2", *KEY[2:]),
                            uptime_ms=50, value=2, valid=True)
        self.assertEqual(reason, "SEGMENT_CHANGED")
        self.assertEqual(buffer.window(end_uptime_ms=50, min_valid_samples=2).status,
                         "INSUFFICIENT_VALID_DATA")

    def test_odr_change_and_long_gap_reset(self):
        buffer = self.buffer()
        buffer.add(segment_key=KEY, uptime_ms=0, value=1, valid=True)
        changed = (*KEY[:4], "odr_changed", KEY[5])
        self.assertEqual(buffer.add(segment_key=changed, uptime_ms=100, value=2, valid=True),
                         "SEGMENT_CHANGED")
        self.assertEqual(buffer.add(segment_key=changed, uptime_ms=800, value=3, valid=True),
                         "OBSERVATION_GAP")

    def test_reversal_resets_and_future_peek_rejected(self):
        buffer = self.buffer()
        buffer.add(segment_key=KEY, uptime_ms=100, value=1, valid=True)
        self.assertEqual(buffer.add(segment_key=KEY, uptime_ms=100, value=2, valid=True),
                         "NON_MONOTONIC_TIME")
        with self.assertRaises(ValueError):
            buffer.window(end_uptime_ms=99, min_valid_samples=1)

    def test_required_parameters_reject_defaults_and_nan(self):
        with self.assertRaises(ValueError):
            CausalObservationBuffer(lookback_ms=0, max_gap_ms=1, max_age_ms=1)
        buffer = self.buffer()
        with self.assertRaises(ValueError):
            buffer.add(segment_key=KEY, uptime_ms=0, value=float("nan"), valid=True)


if __name__ == "__main__":
    unittest.main()
