"""Standard-library regressions; synthetic captures enter through WP2 registration."""

from copy import deepcopy
from dataclasses import replace
import contextlib
import io
import json
import math
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from geohazard_platform.research_features import TimeIntegral, compute_features
from geohazard_platform.research_rule_config import (
    DEFAULT_PARAMETERS, R4_EXPERIMENT_ID, canonical_json, config_digest, freeze_config, validate_config,
)
from geohazard_platform.research_rules import _coincidences, _periods, main, run_rules
from geohazard_platform.research_sessions import register_session
from test_sd_replay import observation, write_capture


def change_channel(session, sensor, transform):
    return replace(session, channels=tuple(
        replace(s, observations=tuple(transform(o) for o in s.observations)) if s.sensor_id == sensor else s
        for s in session.channels))


def rain_identity(session):
    return replace(session, metadata={**deepcopy(session.metadata), "experiment_id": "synthetic-rain",
                                      "session_type": "rain_50"})


class ResearchRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        rows = []
        for i in range(4001):
            for channel in (0, 1):
                row = observation("imu", channel, len(rows), 1000 + i * 10000 + channel * 100)
                row.update(ax_mps2=str(.0001 * math.sin(i / 13)), ay_mps2="0", az_mps2="9.81",
                           gx_dps="0.01", gy_dps="0.01", gz_dps="0.01")
                rows.append(row)
            if i % 50 == 0:
                for channel in (0, 1, 2):
                    rows.append(observation("soil", channel, len(rows), 1500 + i * 10000 + channel * 100,
                                            soil=10000 + (60 if channel == 2 else 1) * (1 if i % 100 else -1)))
        cls.capture = cls.root / "r4"
        path = write_capture(cls.capture, rows, experiment_id=R4_EXPERIMENT_ID)
        end = json.loads(path.with_suffix(".END").read_text())
        end["stop_us"] = 41_000_000
        path.with_suffix(".END").write_text(json.dumps(end))
        cls.registry = cls.root / "research.sqlite3"
        cls.session = register_session(cls.capture, "post_rain_static", cls.registry)
        cls.config = freeze_config(cls.session, generated_at="2026-11-02T00:00:00+00:00")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_synthetic_static_zero_trigger_and_candidate(self):
        result = run_rules(self.session, self.config)
        self.assertEqual((result["trigger_count"], result["candidate_count"]), (0, 0))
        self.assertTrue(all(c["state"] == "NO_TRIGGER" for c in result["channels"].values()))

    def test_freeze_rejects_rain_even_when_label_or_id_is_spoofed(self):
        for identity, kind in ((R4_EXPERIMENT_ID, "rain_50"), ("rain", "post_rain_static"), ("rain", "rain_70")):
            with self.subTest(identity=identity, kind=kind):
                session = replace(self.session, metadata={**self.session.metadata,
                                  "experiment_id": identity, "session_type": kind})
                with self.assertRaisesRegex(ValueError, "only designated R4"):
                    freeze_config(session)

    def test_deterministic_results_and_freeze_given_same_timestamp(self):
        self.assertEqual(canonical_json(run_rules(self.session, self.config)),
                         canonical_json(run_rules(self.session, self.config)))
        self.assertEqual(self.config, freeze_config(self.session, generated_at=self.config["generated_at"]))

    def test_rain_cannot_mutate_frozen_config_or_source(self):
        config_before = canonical_json(self.config)
        session_before = repr(self.session)
        rain = change_channel(rain_identity(self.session), "soil_top", lambda o: replace(
            o, raw=replace(o.raw, soil_raw=13000)) if o.relative_time_us > 20_000_000 else o)
        result = run_rules(rain, self.config)
        self.assertGreater(result["trigger_count"], 0)
        self.assertEqual(config_before, canonical_json(self.config))
        self.assertEqual(session_before, repr(self.session))

    def test_ain2_spike_filtered_on_copy_but_sustained_change_detected(self):
        original = rain_identity(self.session)
        def spike(o):
            return replace(o, raw=replace(o.raw, soil_raw=30000)) if 20_000_000 < o.relative_time_us < 20_100_000 else o
        spiked = change_channel(original, "soil_toe", spike)
        result = run_rules(spiked, self.config, include_features=True)
        self.assertEqual(result["trigger_count"], 0)
        self.assertGreater(result["channels"]["soil_toe"]["diagnostic_counts"]["AIN2_ADJACENT_JITTER_GUARD"], 0)
        self.assertIn(30000, [o.raw.soil_raw for o in spiked.channels[-1].observations])
        self.assertTrue(all(p["values"].get("filtered_adc_code", 10000) < 11000
                            for p in result["features"]["soil_toe"] if p["values"].get("filtered_adc_code") is not None))
        sustained = change_channel(original, "soil_toe", lambda o: replace(
            o, raw=replace(o.raw, soil_raw=13000)) if o.relative_time_us > 20_000_000 else o)
        sustained_result = run_rules(sustained, self.config)
        self.assertTrue(any(e["sensor_id"] == "soil_toe" for e in sustained_result["events"]))

    def test_prefix_causality_all_features_and_published_events(self):
        full = rain_identity(self.session)
        full = change_channel(full, "soil_top", lambda o: replace(o, raw=replace(o.raw, soil_raw=13000))
                              if o.relative_time_us > 16_000_000 else o)
        cut = 27_000_000
        prefix = replace(full, channels=tuple(replace(s, observations=tuple(
            o for o in s.observations if o.relative_time_us <= cut)) for s in full.channels))
        long = run_rules(full, self.config, include_features=True)
        short = run_rules(prefix, self.config, include_features=True)
        for sensor, points in short["features"].items():
            self.assertEqual(points, [p for p in long["features"][sensor] if p["time_us"] <= cut])
        for e in short["events"]:
            match = next(x for x in long["events"] if x["sensor_id"] == e["sensor_id"])
            self.assertEqual((e["start_us"], e["confirmed_at_us"]), (match["start_us"], match["confirmed_at_us"]))

    def test_future_samples_cannot_redefine_initial_reference(self):
        changed = change_channel(rain_identity(self.session), "imu_top", lambda o: replace(
            o, raw=replace(o.raw, acceleration_mps2=(2.0, 0.0, 9.81))) if o.relative_time_us > 25_000_000 else o)
        old = compute_features(self.session, self.config["parameters"])
        new = compute_features(changed, self.config["parameters"])
        self.assertEqual([p for p in old["imu_top"] if p["time_us"] < 25_000_000],
                         [p for p in new["imu_top"] if p["time_us"] < 25_000_000])
        self.assertEqual(old["imu_toe"], new["imu_toe"])
        self.assertTrue(any(e["sensor_id"] == "imu_top" for e in run_rules(changed, self.config)["events"]))

    def test_errors_interrupt_only_the_affected_channel(self):
        broken = change_channel(self.session, "imu_top", lambda o: replace(o, quality_flags=("SENSOR_INVALID",))
                                if 20_000_000 < o.relative_time_us < 20_020_000 else o)
        old = compute_features(self.session, self.config["parameters"])
        new = compute_features(broken, self.config["parameters"])
        self.assertEqual(old["imu_toe"], new["imu_toe"])
        self.assertTrue(any(p["state"] == "INVALID" for p in new["imu_top"]))
        self.assertFalse(any(p["state"] == "READY" for p in new["imu_top"] if 20_020_000 < p["time_us"] < 31_000_000))

    def test_long_gap_resets_imu_windows_and_soil_dwell(self):
        rain = change_channel(rain_identity(self.session), "soil_top", lambda o: replace(o, raw=replace(o.raw, soil_raw=13000))
                              if o.relative_time_us > 20_000_000 else o)
        rain = replace(rain, channels=tuple(replace(s, observations=tuple(o for o in s.observations
                         if not 22_000_000 < o.relative_time_us < 26_000_000)) for s in rain.channels))
        result = run_rules(rain, self.config, include_features=True)
        self.assertGreater(result["channels"]["imu_top"]["diagnostic_counts"]["LONG_GAP"], 0)
        event = next(e for e in result["events"] if e["sensor_id"] == "soil_top")
        self.assertGreaterEqual(event["start_us"], 26_000_000)
        self.assertGreaterEqual(event["confirmed_at_us"] - event["start_us"], 3_000_000)

    def test_zero_baseline_is_unavailable_but_zero_raw_is_preserved(self):
        zero = change_channel(self.session, "soil_top", lambda o: replace(o, raw=replace(o.raw, soil_raw=0)))
        result = run_rules(rain_identity(zero), self.config, include_features=True)
        self.assertEqual(result["channels"]["soil_top"]["state"], "INSUFFICIENT_BASELINE")
        self.assertTrue(all(p["values"]["raw_adc_code"] == 0 for p in result["features"]["soil_top"]))
        self.assertEqual(result["trigger_count"], 0)

    def test_failed_initial_reference_not_replaced_by_later_window(self):
        broken = change_channel(self.session, "soil_top", lambda o: replace(o, quality_flags=("SENSOR_INVALID",))
                                if o.relative_time_us < 1_000_000 else o)
        points = compute_features(broken, self.config["parameters"])["soil_top"]
        self.assertFalse(any(p["state"] == "READY" for p in points))
        with self.assertRaisesRegex(ValueError, "reference"):
            freeze_config(broken)

    def test_reference_same_id_different_fingerprint_is_refused(self):
        session = replace(self.session, metadata=deepcopy(self.session.metadata))
        session.metadata["integrity"]["file_sha256"]["csv"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            run_rules(session, self.config)

    def test_wrong_input_scope_or_channel_identity_is_refused(self):
        for key, value in (("scope", "OPERATIONAL"), ("risk_eligible", True), ("transport", "mqtt")):
            with self.subTest(key=key):
                session = replace(self.session, metadata={**self.session.metadata, key: value})
                with self.assertRaisesRegex(ValueError, "WP2"):
                    run_rules(session, self.config)
        with self.assertRaisesRegex(ValueError, "five"):
            run_rules(replace(self.session, channels=self.session.channels[:-1]), self.config)

    def test_config_digest_and_invalid_bits_parameters_rejected(self):
        config = deepcopy(self.config)
        config["parameters"]["orientation_dwell_us"] = 1
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_config(config)
        for mutation in (lambda c: c["reason_bits"].update(SOIL_TOP=3),
                         lambda c: c["parameters"].update(ain2_median_samples=4),
                         lambda c: c["parameters"].update(minimum_coverage=1.1),
                         lambda c: c["parameters"].update(soil_max_gap_us=-1)):
            c = deepcopy(self.config)
            mutation(c)
            c["config_sha256"] = config_digest(c)
            with self.assertRaises(ValueError):
                validate_config(c)

    def test_reason_mapping_replaced_without_executor_changes(self):
        c = deepcopy(self.config)
        c["reason_bits"] = {key: bit << 8 for key, bit in c["reason_bits"].items()}
        c["reason_definition_version"] = "replacement-mapping-fixture"
        c["config_sha256"] = config_digest(c)
        rain = change_channel(rain_identity(self.session), "soil_middle", lambda o: replace(o, raw=replace(o.raw, soil_raw=13000))
                              if o.relative_time_us > 20_000_000 else o)
        result = run_rules(rain, c)
        self.assertEqual(result["events"][0]["reason_mask"], c["reason_bits"]["SOIL_MIDDLE"])

    def test_time_integral_uses_actual_time_and_excludes_future_energy(self):
        integral = TimeIntegral()
        for time_us, value in ((0, 2), (10, 4), (30, 1000)):
            integral.append(time_us, value)
        self.assertAlmostEqual(integral.mean(0, 30, expected_interval_us=15, minimum_coverage=1), 100 / 30)
        self.assertEqual(integral.mean(10, 30, expected_interval_us=20, minimum_coverage=1), 4)
        self.assertIsNone(integral.mean(-1, 30, expected_interval_us=10, minimum_coverage=.9))
        self.assertIsNone(integral.mean(0, 30, expected_interval_us=10, minimum_coverage=.9))

    def test_vibration_is_candidate_only_even_when_sustained(self):
        points = [{"time_us": i * 500000, "state": "READY", "quality_flags": [],
                   "values": {"vibration_rms_mps2": 10, "sta_lta": 100}} for i in range(10)]
        features = compute_features(self.session, self.config["parameters"])
        # Isolate the classification boundary, with genuine covered points in other channels.
        features["imu_top"] = points
        with patch("geohazard_platform.research_rules.compute_features", return_value=features):
            result = run_rules(self.session, self.config)
        self.assertEqual(result["trigger_count"], 0)
        self.assertEqual(result["candidate_count"], 1)
        self.assertFalse(result["candidates"][0]["triggered"])
        self.assertEqual(result["channels"]["imu_top"]["state"], "NO_TRIGGER")

    def test_dwell_and_hysteresis_and_quality_interruption(self):
        def point(i, value, flags=()):
            return {"time_us": i * 1000000, "state": "READY", "quality_flags": list(flags), "values": {"x": value}}
        points = [point(0, 2), point(1, 0), point(2, 2), point(3, 2), point(4, 2),
                  point(5, .9), point(6, .7), point(7, .7), point(8, 2), point(9, 2), point(10, 2),
                  point(11, 2, ("ERROR",))]
        events = _periods(points, sensor="soil_top", event_class="test", metrics=("x",), thresholds=(1,),
                          dwell_us=2_000_000, parameters=DEFAULT_PARAMETERS, reason_key="SOIL_TOP", reason_mask=4)
        self.assertEqual([(e["start_us"], e["confirmed_at_us"], e["end_us"], e["closure"]) for e in events],
                         [(2_000_000, 4_000_000, 5_000_000, "RECOVERED"),
                          (8_000_000, 10_000_000, 10_000_000, "QUALITY_INTERRUPTION")])

    def test_overlap_never_uses_pre_confirmation_time(self):
        events = [{"sensor_id": "soil_top", "start_us": 0, "confirmed_at_us": 3, "end_us": 10, "reason_mask": 4},
                  {"sensor_id": "imu_top", "start_us": 2, "confirmed_at_us": 5, "end_us": 8, "reason_mask": 1}]
        overlap = _coincidences(events)
        self.assertEqual((overlap[0]["start_us"], overlap[0]["end_us"], overlap[0]["reason_mask"]), (5, 8, 5))

    def test_research_result_cannot_write_production_tables(self):
        before = self.registry.read_bytes()
        with patch("sqlite3.connect", side_effect=AssertionError("executor must be pure")):
            result = run_rules(self.session, self.config)
        self.assertEqual(before, self.registry.read_bytes())
        self.assertEqual(result["scope"], "RESEARCH")
        self.assertFalse(result["production_alarm_eligible"])
        self.assertFalse(result["risk_eligible"])
        with sqlite3.connect(self.registry) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {"research_sd_sessions", "research_sd_attempts"})

    def test_cli_freeze_exclusive_and_run_config_bytes_unchanged(self):
        with TemporaryDirectory() as temp:
            config_path = Path(temp) / "frozen.json"
            base = [str(self.capture), "--registry", str(self.registry)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["freeze", *base, "--output", str(config_path)]), 0)
            before = config_path.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["freeze", *base, "--output", str(config_path)]), 1)
            report = Path(temp) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["run", *base, "--type", "post_rain_static", "--config", str(config_path),
                                       "--output", str(report)]), 0)
            self.assertEqual(before, config_path.read_bytes())
            self.assertEqual(json.loads(report.read_text())["trigger_count"], 0)

    def test_cli_refuses_output_inside_capture_and_rain_freeze(self):
        base = [str(self.capture), "--registry", str(self.registry)]
        with contextlib.redirect_stderr(io.StringIO()):
            output = self.capture / "bad.json"
            self.assertEqual(main(["freeze", *base, "--output", str(output)]), 1)
        self.assertFalse(output.exists())
        with TemporaryDirectory() as temp, patch("geohazard_platform.research_rules.register_session",
                                               return_value=rain_identity(self.session)):
            output = Path(temp) / "rain-freeze.json"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["freeze", *base, "--output", str(output)]), 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
