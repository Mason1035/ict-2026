"""数值、因果性、状态隔离与失效门禁；仅使用 TEST_ONLY 合成夹具。"""
import copy
import unittest
from types import MappingProxyType

from candidate_features import risk_math
from telemetry_v2_intake import evaluate_telemetry_v2
from telemetry_v2_intake.config import REASONS, config_hash, contribution
from telemetry_v2_intake.demo_runtime import fixture, test_only_config
from telemetry_v2_intake.runtime import FeatureRiskRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FeatureRiskRuntime(test_only_config())

    def run_fixture(self, **kwargs):
        p, c = fixture(**kwargs)
        return self.runtime.evaluate(p, context=c)

    def test_stationary_numerical_features_and_shared_score(self):
        p, c = fixture()
        original = copy.deepcopy((p, c))
        result = evaluate_telemetry_v2(p, context=c, runtime=self.runtime)
        self.assertEqual(result["risk_execution"], "TEST_ONLY_RISK_COMPUTED")
        self.assertEqual(result["features"]["imu"]["top"],
                         {"tilt_deg": 0, "tilt_rate_dps": 0, "vibration_rms": 0})
        self.assertEqual(result["features"]["soil"]["avg_pct"], 20)
        self.assertEqual(result["features"]["soil"]["growth_pct_min"], 0)
        self.assertEqual(result["risk"], {"sensor_score": 5.0, "level": "NORMAL", "reason_mask": None})
        self.assertEqual((p, c), original)

    def test_abnormal_expected_features_and_bonus(self):
        result = self.run_fixture(scenario="abnormal")
        self.assertAlmostEqual(result["features"]["soil"]["growth_pct_min"], 600)
        self.assertAlmostEqual(result["features"]["imu"]["top"]["vibration_rms"], .392474875970, places=9)
        self.assertAlmostEqual(result["risk"]["sensor_score"], 75.47803014177, places=8)
        self.assertEqual(result["consensus_bonus"], 5)
        self.assertEqual(result["risk"]["level"], "WARNING")

    def test_batch_and_streaming_equivalence(self):
        whole = self.run_fixture(scenario="abnormal")
        streaming = FeatureRiskRuntime(test_only_config())
        for start, end, seq in ((0, 1000, 1), (1010, 2000, 2), (2010, 3000, 3)):
            p, c = fixture(start=start, end=end, seq=seq, scenario="abnormal")
            partial = streaming.evaluate(p, context=c)
        self.assertEqual(whole["features"], partial["features"])
        self.assertEqual(whole["risk"], partial["risk"])

    def test_missing_is_null_and_not_reweighted(self):
        result = self.run_fixture(scenario="missing")
        self.assertIsNone(result["features"]["soil"]["middle_pct"])
        self.assertTrue(all(v is None for v in result["risk"].values()))
        self.assertTrue(all(v is None for v in result["contributions"].values()))

    def test_zero_adc_preserved_and_reversed_calibration(self):
        c = test_only_config()
        for probe in c["soil"]["calibration"].values():
            probe.update(dry_raw=10000, wet_raw=0)
        c["config_hash"] = config_hash(c)
        self.runtime = FeatureRiskRuntime(c)
        p, b = fixture()
        for pos in ("top", "middle", "toe"):
            p["soil"][f"{pos}_raw"] = 0
            for row in b["runtime_input"]["soil"][pos]:
                row["raw"] = 0
        result = self.runtime.evaluate(p, context=b)
        self.assertEqual(result["features"]["soil"]["avg_pct"], 100)

    def test_unclipped_out_of_range_diagnostic_blocks(self):
        p, c = fixture()
        p["soil"]["top_raw"] = 12000
        for row in c["runtime_input"]["soil"]["top"]:
            row["raw"] = 12000
        result = self.runtime.evaluate(p, context=c)
        self.assertEqual(result["feature_details"]["soil"]["probes"]["top"]["unclipped_pct"], 120)
        self.assertIsNone(result["features"]["soil"]["top_pct"])
        self.assertIsNone(result["risk"]["level"])

    def test_duplicate_and_conflict_do_not_add_samples(self):
        p, c = fixture()
        first = self.runtime.evaluate(p, context=c)
        second = self.runtime.evaluate(p, context=c)
        self.assertEqual(second["processing"], "DUPLICATE_NO_RECOMPUTE")
        self.assertEqual(first["features"], second["features"])
        corrupt = copy.deepcopy(c)
        corrupt["runtime_input"]["soil"]["top"][-1]["raw"] += 1
        rejected = self.runtime.evaluate(p, context=corrupt)
        self.assertEqual(rejected["processing"], "INPUT_REJECTED_NO_STATE_CHANGE")
        self.assertEqual(self.runtime.evaluate(p, context=c)["risk"], first["risk"])

    def test_held_soil_values_do_not_count_as_new(self):
        first = self.run_fixture()
        p, c = fixture(start=3000, end=3010, seq=2)
        # 3000 ms 是保持值，仅新 IMU 的 3010 ms 应被加入。
        result = self.runtime.evaluate(p, context=c)
        self.assertEqual(result["feature_details"]["soil"]["growth_window"]["valid_count"],
                         first["feature_details"]["soil"]["growth_window"]["valid_count"] - 1)
        self.assertEqual(result["features"]["soil"]["growth_pct_min"], 0)

    def test_stale_latest_observation_blocks(self):
        self.run_fixture()
        p, c = fixture(end=3000, seq=2)
        p["uptime_ms"] = 4000
        c["runtime_input"]["imu"] = {p: [] for p in ("top", "toe")}
        c["runtime_input"]["soil"] = {p: [] for p in ("top", "middle", "toe")}
        result = self.runtime.evaluate(p, context=c)
        self.assertIsNone(result["risk"]["level"])
        self.assertEqual(result["feature_details"]["imu"]["top"]["tilt_window"]["status"],
                         "INSUFFICIENT_VALID_DATA")

    def test_future_wrong_metadata_or_snapshot_rejected_transactionally(self):
        for kind in ("future", "calibration", "source", "snapshot", "validity"):
            with self.subTest(kind=kind):
                p, c = fixture()
                if kind == "future":
                    c["runtime_input"]["imu"]["top"][-1]["uptime_ms"] += 1
                elif kind == "calibration":
                    c["runtime_input"]["calibration_version"] = "OTHER"
                elif kind == "source":
                    c["runtime_input"]["source"] = "REAL"
                elif kind == "snapshot":
                    p["imu"][0]["ax"] = 1
                else:
                    c["runtime_input"]["soil"]["top"][-1]["valid"] = "Valid"
                runtime = FeatureRiskRuntime(test_only_config())
                result = runtime.evaluate(p, context=c)
                self.assertEqual(result["processing"], "INPUT_REJECTED_NO_STATE_CHANGE")
                self.assertEqual(runtime._states, {})

    def test_boot_change_and_imu_gap_warmup(self):
        self.run_fixture()
        for kwargs in ({"start": 0, "end": 100, "boot": 2, "seq": 1},
                       {"start": 5000, "end": 5100, "boot": 1, "seq": 2}):
            runtime = FeatureRiskRuntime(test_only_config())
            p, c = fixture()
            runtime.evaluate(p, context=c)
            p, c = fixture(**kwargs)
            # 当前最新 Soil 是保持值；填入缺少的采样行以对应快照。
            if not c["runtime_input"]["soil"]["top"]:
                for pos in ("top", "middle", "toe"):
                    c["runtime_input"]["soil"][pos] = [{"uptime_ms": kwargs["start"], "valid": True, "raw": 2000}]
            result = runtime.evaluate(p, context=c)
            self.assertIsNone(result["risk"]["level"])
            self.assertIsNone(result["features"]["imu"]["top"]["tilt_deg"])

    def test_imu_invalid_and_misalignment_remove_bonus(self):
        for fault in ("invalid", "misaligned"):
            p, c = fixture(scenario="abnormal")
            if fault == "invalid":
                p["imu"][1]["valid"] = False
                c["runtime_input"]["imu"]["toe"][-1]["valid"] = False
            else:
                c["runtime_input"]["imu"]["toe"].pop()
                for key, value in zip(("ax", "ay", "az"), c["runtime_input"]["imu"]["toe"][-1]["acceleration_mps2"]):
                    p["imu"][1][key] = value
            result = self.runtime.evaluate(p, context=c)
            self.assertIsNone(result["risk"]["sensor_score"])
            self.assertNotIn("consensus_bonus", result)
            self.runtime = FeatureRiskRuntime(test_only_config())

    def test_config_failure_keeps_last_valid_config_and_history(self):
        self.run_fixture()
        c = test_only_config()
        c["soil"]["calibration"]["top"]["wet_raw"] = 0
        c["config_hash"] = config_hash(c)
        with self.assertRaises(ValueError):
            self.runtime.reload_config(c)
        self.assertEqual(self.run_fixture()["processing"], "DUPLICATE_NO_RECOMPUTE")
        c = test_only_config()
        c["calibration_version"] = "NEW-CAL"
        c["config_hash"] = config_hash(c)
        self.runtime.reload_config(c)
        self.assertEqual(self.runtime._states, {})

    def test_draft_hash_curves_and_review_gate(self):
        for change in ("draft", "hash", "curve", "review"):
            c = test_only_config()
            if change == "draft":
                c["mode"] = "DRAFT"
            elif change == "hash":
                c["config_hash"] = "incorrect"
            elif change == "curve":
                c["curves"]["tilt"] = [[10, 0], [0, 100]]
            else:
                c["mode"] = "CALIBRATED"
                c["validated_for_runtime"] = True
                c["review_refs"] = {}
            if change != "hash":
                c["config_hash"] = config_hash(c)
            with self.assertRaises(ValueError):
                FeatureRiskRuntime(c)

    def test_piecewise_mapping_and_float_level_boundaries(self):
        points = [[0, 0], [10, 40], [20, 100]]
        self.assertEqual([contribution(v, points) for v in (None, -1, 5, 15, 30)],
                         [None, 0, 20, 70, 100])
        self.assertEqual([risk_math.risk_level(v) for v in (29.999, 30, 59.999, 60, 79.999, 80, 100)],
                         ["NORMAL", "WATCH", "WATCH", "WARNING", "WARNING", "EMERGENCY", "EMERGENCY"])

    def test_readonly_upstream_input(self):
        def freeze(value):
            if isinstance(value, dict):
                return MappingProxyType({k: freeze(v) for k, v in value.items()})
            if isinstance(value, list):
                return tuple(freeze(v) for v in value)
            return value
        p, c = fixture()
        result = self.runtime.evaluate(freeze(p), context=freeze(c))
        self.assertEqual(result["risk_execution"], "TEST_ONLY_RISK_COMPUTED")

    def test_retired_boot_and_same_boot_reordered_run_rejected(self):
        self.run_fixture()
        p, c = fixture(end=100, boot=2)
        self.runtime.evaluate(p, context=c)
        result = self.run_fixture()
        self.assertEqual(result["processing"], "INPUT_REJECTED_NO_STATE_CHANGE")
        p, c = fixture(end=50, boot=2, seq=0)
        p["experiment"]["run_id"] = c["runtime_input"]["run_id"] = "OTHER-RUN"
        result = self.runtime.evaluate(p, context=c)
        self.assertEqual(result["processing"], "INPUT_REJECTED_NO_STATE_CHANGE")

    def test_snapshot_alone_cannot_supply_waveform(self):
        p, c = fixture()
        result = self.runtime.evaluate(p, context={"sampling_snapshot": c["runtime_input"]})
        self.assertEqual(result["risk_execution"], "RISK_EXECUTION_BLOCKED")
        self.assertEqual(self.runtime._states, {})

    def test_calibrated_branch_requires_review_and_source(self):
        # 只验证门禁代码路径。下面的虚拟 refs/bit 绝不是团队会签或实测配置。
        cfg = test_only_config()
        cfg.update(mode="CALIBRATED", validated_for_runtime=True,
                   review_refs={p: "UNIT_TEST_FAKE_REF_" + p for p in ("A", "B", "C")},
                   reason_mask_version="UNIT_TEST_FAKE_BITS",
                   reason_bits={r: i for i, r in enumerate(REASONS)})
        cfg["config_hash"] = config_hash(cfg)
        runtime = FeatureRiskRuntime(cfg)
        p, c = fixture()
        self.assertEqual(runtime.evaluate(p, context=c)["processing"], "INPUT_REJECTED_NO_STATE_CHANGE")
        c["runtime_input"]["source"] = "REAL"  # 此标签只模拟门禁输入，不改变夹具的合成事实。
        result = runtime.evaluate(p, context=c)
        self.assertEqual(result["risk"]["reason_mask"], 1 << cfg["reason_bits"]["MOISTURE_CONTRIBUTION"])

    def test_soil_fault_recovery_requires_new_window(self):
        self.run_fixture()
        p, c = fixture(start=3010, end=3500, seq=2, scenario="missing")
        self.runtime.evaluate(p, context=c)
        p, c = fixture(start=3510, end=4000, seq=3)
        result = self.runtime.evaluate(p, context=c)
        self.assertIsNone(result["risk"]["level"])
        self.assertEqual(result["feature_details"]["soil"]["growth_window"]["valid_count"], 1)

    def test_sequential_soil_scans_keep_causal_growth_history(self):
        p, c = fixture(end=3020)
        for pos, offset in (("top", 0), ("middle", 10), ("toe", 20)):
            for row in c["runtime_input"]["soil"][pos]:
                row["uptime_ms"] += offset
        result = self.runtime.evaluate(p, context=c)
        self.assertEqual(result["risk_execution"], "TEST_ONLY_RISK_COMPUTED")
        self.assertEqual(result["feature_details"]["soil"]["growth_window"]["valid_count"], 7)
        self.assertEqual(result["features"]["soil"]["growth_pct_min"], 0)


if __name__ == "__main__":
    unittest.main()
