import json
import random
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from examples import make_history, scenarios
from risk_algorithm import DEFAULT_CONFIG, RiskEvaluator, evaluate


class AlgorithmTests(unittest.TestCase):
    def test_three_scenarios(self):
        expected = {"normal": "normal", "abnormal": "warning", "missing": "unknown"}
        for name, history in scenarios().items():
            with self.subTest(name=name):
                result = evaluate(history)
                self.assertEqual(result["risk_level"], expected[name])
                self.assertEqual(set(result), {"risk_level", "reasons", "missing_fields"})
        self.assertEqual(evaluate(scenarios()["normal"])["reasons"], [])

    def test_shuffle_and_duplicates_invariant(self):
        records = scenarios()["abnormal"]
        mixed = records + deepcopy(records[1:5])
        random.Random(42).shuffle(mixed)
        self.assertEqual(evaluate(mixed), evaluate(records))

    def test_conflicting_duplicate(self):
        records = make_history()
        duplicate = deepcopy(records[0])
        duplicate["tilt_deg"] = 4
        self.assertEqual(evaluate(records + [duplicate])["risk_level"], "unknown")

    def test_canonical_timestamp_duplicate(self):
        records = make_history()
        duplicate = deepcopy(records[0])
        duplicate["timestamp"] = duplicate["timestamp"].replace("Z", "+00:00")
        self.assertEqual(evaluate(records + [duplicate]), evaluate(records))

    def test_battery_does_not_change_risk(self):
        for history in (make_history(), scenarios()["abnormal"]):
            expected = evaluate(history)["risk_level"]
            for battery in (0, 20, None):
                records = deepcopy(history)
                records[-1]["battery_pct"] = battery
                result = evaluate(records)
                self.assertEqual(result["risk_level"], expected)
                self.assertTrue(any("设备状态" in reason for reason in result["reasons"]))
                self.assertEqual(result["missing_fields"], ["battery_pct"] if battery is None else [])

    def test_missing_required_measurements(self):
        for index in (0, 5):
            for field in ("soil_moisture_pct", "tilt_deg"):
                records = make_history()
                records[index][field] = None
                result = evaluate(records)
                self.assertEqual(result["risk_level"], "unknown")
                self.assertIn(field, result["missing_fields"])

    def test_insufficient_and_missing_baseline(self):
        for records in ([], make_history()[:5], make_history()[1:]):
            self.assertEqual(evaluate(records)["risk_level"], "unknown")

    def test_no_mutation(self):
        records = scenarios()["abnormal"]
        before = deepcopy(records)
        evaluate(records)
        self.assertEqual(records, before)

    def test_invalid_records(self):
        for field, value in (
            ("source", "drone"), ("sequence", True), ("sequence", 2**53),
            ("battery_pct", "85"), ("soil_moisture_pct", float("nan")),
            ("tilt_deg", float("inf")), ("soil_moisture_pct", 101),
            ("timestamp", "2026-09-23T12:00:00+08:00"),
            ("timestamp", "2026-09-23T12:00:00"),
        ):
            with self.subTest(field=field, value=value):
                records = make_history()
                records[0][field] = value
                self.assertEqual(evaluate(records)["risk_level"], "unknown")
        for change in ("extra", "missing"):
            records = make_history()
            if change == "extra":
                records[0]["risk"] = "normal"
            else:
                del records[0]["tilt_deg"]
            self.assertEqual(evaluate(records)["risk_level"], "unknown")

    def test_mixed_node_and_source(self):
        for field, value in (("node_id", "OTHER"), ("source", "real")):
            records = make_history()
            records[-1][field] = value
            self.assertEqual(evaluate(records)["risk_level"], "unknown")

    def test_time_reversal_and_equal(self):
        for timestamp in ("2026-09-23T11:59:00Z", "2026-09-23T12:00:40Z"):
            records = make_history()
            records[-1]["timestamp"] = timestamp
            self.assertEqual(evaluate(records)["risk_level"], "unknown")

    def test_long_gap_and_short_duration(self):
        records = make_history()
        records[-1]["timestamp"] = "2026-09-23T12:02:00Z"
        self.assertEqual(evaluate(records)["risk_level"], "unknown")
        records = make_history()
        for index in range(3, 6):
            records[index]["timestamp"] = f"2026-09-23T12:00:{30 + index - 3:02d}Z"
        self.assertEqual(evaluate(records)["risk_level"], "unknown")

    def test_sequence_gap(self):
        records = make_history(tilts=[0.2] * 7, moisture=[32] * 7)
        del records[4]
        self.assertEqual(evaluate(records)["risk_level"], "unknown")

    def test_unstable_baseline(self):
        records = make_history(tilts=[0.2, 1.2, 0.2, 0.2, 0.2, 0.2])
        self.assertEqual(evaluate(records)["risk_level"], "unknown")

    def test_humidity_alone_never_warning(self):
        records = make_history(moisture=[32, 32, 32, 34, 37, 40])
        self.assertEqual(evaluate(records)["risk_level"], "attention")

    def test_tilt_alone_and_negative_direction(self):
        for tilt in (4.0, -4.0):
            records = make_history(tilts=[0.2, 0.2, 0.2, tilt, tilt, tilt])
            self.assertEqual(evaluate(records)["risk_level"], "warning")

    def test_single_spike_and_alternating_direction(self):
        for tail in ([0.2, 0.2, 4.0], [4.0, -4.0, 4.0]):
            records = make_history(tilts=[0.2, 0.2, 0.2] + tail)
            result = evaluate(records)
            self.assertEqual(result["risk_level"], "normal")
            self.assertTrue(any("复核" in reason for reason in result["reasons"]))

    def test_moisture_nonmonotonic_and_exact_threshold(self):
        records = make_history(moisture=[32, 32, 32, 34, 33, 40])
        self.assertEqual(evaluate(records)["risk_level"], "normal")
        records = make_history(moisture=[32, 32, 32, 32, 33, 34])
        self.assertEqual(evaluate(records)["risk_level"], "attention")

    def test_historic_null_outside_assessed_segments(self):
        records = make_history(tilts=[0.2] * 9, moisture=[32] * 9)
        records[4]["soil_moisture_pct"] = None
        result = evaluate(records)
        self.assertEqual(result["risk_level"], "normal")
        self.assertEqual(result["missing_fields"], [])

    def test_exact_tilt_thresholds(self):
        for tilt, expected in ((1.0, "attention"), (3.0, "warning"), (0.999, "normal")):
            records = make_history(tilts=[0, 0, 0, tilt, tilt, tilt])
            self.assertEqual(evaluate(records)["risk_level"], expected)

    def test_late_data_repairs_current_window(self):
        records = scenarios()["abnormal"]
        partial = [record for record in records if record["sequence"] != 5]
        self.assertEqual(evaluate(partial)["risk_level"], "unknown")
        self.assertEqual(evaluate(partial + [records[4]])["risk_level"], "warning")

    def test_old_data_does_not_become_latest(self):
        records = make_history(tilts=[0.2] * 9, moisture=[32] * 9)
        expected = evaluate(records)
        self.assertEqual(evaluate(records[6:] + records[:6]), expected)

    def test_baseline_does_not_follow_abnormal_tail(self):
        records = make_history(tilts=[0.2] * 3 + [4] * 9, moisture=[32] * 12)
        self.assertEqual(evaluate(records)["risk_level"], "warning")

    def test_configurable_baseline_and_bad_config(self):
        config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            config["baseline_start_sequence"] = 101
            path.write_text(json.dumps(config), encoding="utf-8")
            evaluator = RiskEvaluator(path)
            records = make_history()
            for record in records:
                record["sequence"] += 100
            self.assertEqual(evaluator.evaluate(records)["risk_level"], "normal")
            config["demo_only"] = False
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ValueError):
                RiskEvaluator(path)


if __name__ == "__main__":
    unittest.main()
