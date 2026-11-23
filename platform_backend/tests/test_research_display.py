"""Presentation regressions using synthetic WP2 registrations; stdlib runnable."""
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from geohazard_platform.research_display import (
    FROZEN_CONFIG, ResearchDisplay, ResearchDisplayError, downsample,
)
from geohazard_platform.research_rules import run_rules
from geohazard_platform.research_sessions import register_session
from test_sd_replay import observation, write_capture


EXPERIMENT = "NODE01-f9029c8eef460b40-N0000004.CSV"


def register_synthetic(root):
    """Both IMUs at 100 Hz, three ADC channels at 2 Hz, one sustained step."""
    rows = []
    for i in range(2501):
        for channel in (0, 1):
            row = observation("imu", channel, len(rows), 1100 + i * 10000 + channel * 100)
            row.update(ax_mps2="0", ay_mps2="0", az_mps2="9.81", gx_dps="0", gy_dps="0", gz_dps="0")
            rows.append(row)
        if i % 50 == 0:
            for channel in (0, 1, 2):
                rows.append(observation("soil", channel, len(rows), 1400 + i * 10000 + channel * 100,
                                        soil=20000 if i > 1500 else 10000))
    path = write_capture(root / "capture", rows, experiment_id=EXPERIMENT)
    end = json.loads(path.with_suffix(".END").read_text())
    end["stop_us"] = 25_002_000
    path.with_suffix(".END").write_text(json.dumps(end))
    registry = root / "research.sqlite3"
    session = register_session(path.parent, "rain_100", registry)
    return registry, session


class ResearchDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.registry, cls.session = register_synthetic(cls.root)
        cls.display = ResearchDisplay(cls.registry, cls.root / "platform.sqlite3")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_registered_list_fields_and_boundary(self):
        result = self.display.sessions()
        self.assertEqual(result["scope"], "RESEARCH")
        self.assertTrue(result["uncalibrated"])
        item, = result["items"]
        self.assertEqual(item["experiment_id"], EXPERIMENT)
        self.assertEqual(item["label"], "R3")
        self.assertIn("AIN2_JITTER_REVIEW", item["quality_flags"])
        self.assertEqual(item["channels"]["imu_top"]["valid_count"], 2501)
        self.assertEqual(item["firmware_sha256"], "a" * 64)
        self.assertFalse(item["production_alarm_eligible"])
        self.assertNotIn("source_directory", json.dumps(result))

    def test_detail_five_channels_statistics_and_bounded_curves(self):
        result = self.display.detail(EXPERIMENT, 16)
        self.assertEqual(set(result["channels"]), set(self.session.summary()["channels"]))
        for channel in result["channels"].values():
            for curve in channel["curves"]:
                self.assertLessEqual(len(curve["points"]), 16)
        self.assertEqual(result["channels"]["soil_top"]["statistics"]["usable_count"], 51)
        self.assertEqual(result["scope"], "RESEARCH")
        self.assertTrue(result["uncalibrated"])
        angle = result["channels"]["imu_top"]["curves"][0]["points"]
        self.assertTrue(any(not p["break_before"] for p in angle if p["value"] is not None))

    def test_rules_equal_full_wp3_output_and_provenance(self):
        config = json.loads(FROZEN_CONFIG.read_text())
        expected = run_rules(self.session, config)
        result = self.display.rules(EXPERIMENT)
        for key, value in expected.items():
            self.assertEqual(result[key], value, key)
        self.assertGreater(result["trigger_count"], 0)
        self.assertEqual(result["provenance"]["config_sha256"], config["config_sha256"])
        self.assertEqual(result["provenance"]["source"], config["source"])
        self.assertEqual(len(result["reason_decode"]), 7)
        self.assertTrue(all(not p["triggered"] for p in result["candidates"]))

    def test_unregistered_identity_404(self):
        for operation in (self.display.detail, self.display.rules):
            with self.assertRaises(ResearchDisplayError) as caught:
                operation("unregistered")
            self.assertEqual(caught.exception.status_code, 404)

    def test_missing_registry_does_not_create_file(self):
        path = self.root / "missing.sqlite3"
        with self.assertRaises(ResearchDisplayError) as caught:
            ResearchDisplay(path, self.root / "platform.sqlite3").sessions()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertFalse(path.exists())

    def test_production_database_rejected_before_open(self):
        with patch("geohazard_platform.research_display.sqlite3.connect") as connect:
            with self.assertRaises(ResearchDisplayError):
                ResearchDisplay(self.registry, self.registry).sessions()
            connect.assert_not_called()

    def test_unrelated_tables_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "other.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE alarms (id TEXT)")
            with self.assertRaises(ResearchDisplayError):
                ResearchDisplay(path, Path(tmp) / "prod.sqlite3").sessions()

    def test_registry_connection_is_query_only_and_read_only(self):
        real_connect = sqlite3.connect
        def checked(path, **kwargs):
            self.assertTrue(path.endswith("?mode=ro"))
            connection = real_connect(path, **kwargs)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM research_sd_sessions")
            return connection
        with patch("geohazard_platform.research_display.sqlite3.connect", side_effect=checked):
            self.display.sessions()

    def test_registry_config_and_raw_bytes_unchanged(self):
        paths = [self.registry, FROZEN_CONFIG, *sorted((self.root / "capture").iterdir())]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        self.display.sessions(); self.display.detail(EXPERIMENT); self.display.rules(EXPERIMENT)
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_changed_registered_bytes_rejected_even_if_triplet_valid(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry, _ = register_synthetic(root)
            path = root / "capture" / "N0000004.END"
            end = json.loads(path.read_text())
            end["stop_us"] += 1
            path.write_text(json.dumps(end))
            with self.assertRaisesRegex(ResearchDisplayError, "指纹"):
                ResearchDisplay(registry, root / "prod.sqlite3").detail(EXPERIMENT)

    def test_changed_registry_scope_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry, _ = register_synthetic(root)
            with sqlite3.connect(registry) as connection:
                m = json.loads(connection.execute("SELECT metadata_json FROM research_sd_sessions").fetchone()[0])
                m["scope"] = "OPERATIONAL"
                connection.execute("UPDATE research_sd_sessions SET metadata_json=?", (json.dumps(m),))
            with self.assertRaises(ResearchDisplayError):
                ResearchDisplay(registry, root / "prod.sqlite3").sessions()

    def test_downsample_preserves_extrema_zero_null_and_hidden_gaps(self):
        points = [{"time_us": i * 10, "values": {"m": float(i)}, "quality_flags": []} for i in range(100)]
        points[20]["values"]["m"] = 9999
        points[21]["values"]["m"] = -9999
        points[50]["values"]["m"] = None
        full = downsample(points, "m", 2000, 20)["points"]
        self.assertEqual(full[0]["value"], 0)
        self.assertIsNone(full[50]["value"])
        small = downsample(points, "m", 16, 20)["points"]
        self.assertLessEqual(len(small), 16)
        self.assertIn(9999, [p["value"] for p in small])
        self.assertIn(-9999, [p["value"] for p in small])
        following = next(p for p in small if p["time_us"] > 500)
        self.assertTrue(following["break_before"])

    def test_downsample_empty_missing_time_and_bounds(self):
        self.assertEqual(downsample([], "m", 16, 20)["points"], [])
        self.assertEqual(downsample([{"time_us": None, "values": {}, "quality_flags": []}], "m", 16, 20)["points"], [])
        for limit in (0, 15, 2001):
            with self.assertRaises(ValueError):
                downsample([], "m", limit, 20)
