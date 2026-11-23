"""External R4/rain regressions via WP2; raw triplets are never vendored."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from geohazard_platform.research_rule_config import canonical_json, freeze_config
from geohazard_platform.research_rules import run_rules
from geohazard_platform.research_sessions import register_session
from test_sd_replay_data import DATA_ROOT, GOLDEN
import os


CONFIG = Path(__file__).resolve().parents[1] / "config/research_rules/provisional-v1-r4.json"


class ExternalResearchRulesTests(unittest.TestCase):
    def assert_session(self, kind):
        relative, filename, identity, *_ = GOLDEN[kind]
        source = DATA_ROOT / relative
        if not source.is_dir():
            self.skipTest(f"external golden capture unavailable: {source}")
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob("N*.*")
                  if p.suffix in (".BEG", ".CSV", ".END")}
        config_bytes = CONFIG.read_bytes()
        config = json.loads(config_bytes)
        with TemporaryDirectory() as temp:
            session = register_session(source, kind, Path(temp) / "research.sqlite3", csv_name=filename)
            first = run_rules(session, config)
            second = run_rules(session, config)
            self.assertEqual(canonical_json(first), canonical_json(second))
            if kind == "post_rain_static":
                self.assertEqual((first["trigger_count"], first["candidate_count"]), (0, 0))
                self.assertTrue(all(c["state_counts"]["READY"] > 0 for c in first["channels"].values()))
                recreated = freeze_config(session, generated_at=config["generated_at"])
                # A fresh registry creates its own UUID; statistics/parameters must still match exactly.
                self.assertEqual(recreated["parameters"], config["parameters"])
                self.assertEqual(recreated["channels"], config["channels"])
            else:
                with self.assertRaisesRegex(ValueError, "only designated R4"):
                    freeze_config(session)
                # Regression expectations recorded after freezing, never used by
                # the freeze tool to choose thresholds or window parameters.
                self.assertEqual((first["trigger_count"], first["candidate_count"]), (5, 0))
                expected = ({"imu_toe": 1, "soil_top": 1, "soil_middle": 1, "soil_toe": 2}
                            if kind == "rain_100" else
                            {"imu_top": 1, "imu_toe": 1, "soil_top": 1, "soil_middle": 1, "soil_toe": 1})
                self.assertEqual({sensor: len(channel["events"]) for sensor, channel in first["channels"].items()
                                  if channel["events"]}, expected)
            self.assertEqual(first["experiment_id"], identity)
            self.assertEqual(first["scope"], "RESEARCH")
            self.assertFalse(first["production_alarm_eligible"])
        self.assertEqual(config_bytes, CONFIG.read_bytes())
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob("N*.*")
                 if p.suffix in (".BEG", ".CSV", ".END")}
        self.assertEqual(before, after)

    def test_r4_zero_trigger_and_reproducible_freeze(self):
        self.assert_session("post_rain_static")

    def test_r1_rain_50_read_only_frozen_validation(self):
        self.assert_session("rain_50")

    def test_r2_rain_70_read_only_frozen_validation(self):
        self.assert_session("rain_70")

    def test_r3_rain_100_read_only_frozen_validation(self):
        self.assert_session("rain_100")


if __name__ == "__main__":
    unittest.main()
