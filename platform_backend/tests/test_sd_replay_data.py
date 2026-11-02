"""External read-only capture regressions; never vendor raw captures into git."""

import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from geohazard_platform.research_sessions import register_session
from geohazard_platform.sd_replay import parse_sd_session


PROJECT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path(os.environ.get("ICT_REPLAY_DATA_ROOT", str(
    PROJECT / "数据/2026-11-02重测与无雨300秒"))).expanduser()
LEGACY_N2 = Path(os.environ.get("ICT_REPLAY_LEGACY_N2", str(
    PROJECT / "数据/相同降雨量/70 pwm挡位/1（I2C错误）/N0000002.CSV"))).expanduser()
FIRMWARE = "288e76253c36efcc1939959443c2ae58c245eb2ea0f7ba667e950d9d2372119d"

# Frozen acceptance values, not inferred from the parser or current sidecars.
GOLDEN = {
    "rain_50": ("相同降雨量/50档pwm", "N0000001.CSV", "NODE01-5f604a129b915316-N0000001.CSV",
                36979, 5199071, "8d69498e", (17998, 17901, 360, 360, 360)),
    "rain_70": ("相同降雨量/70档pwm", "N0000002.CSV", "NODE01-d5a1317c1f27fded-N0000002.CSV",
                36978, 5157310, "730feccd", (17997, 17901, 360, 360, 360)),
    "rain_100": ("相同降雨量/100档pwm", "N0000004.CSV", "NODE01-f9029c8eef460b40-N0000004.CSV",
                 36973, 5174628, "711a03ea", (17995, 17898, 360, 360, 360)),
    "post_rain_static": ("300s不降雨测试", "N0000005.CSV", "NODE01-2e379f02688fd631-N0000005.CSV",
                         61629, 8582426, "1a5fd03b", (29994, 29835, 600, 600, 600)),
}


class GoldenSDReplayTests(unittest.TestCase):
    def assert_capture(self, kind):
        directory, filename, experiment, rows, size, crc, counts = GOLDEN[kind]
        source = DATA_ROOT / directory
        if not source.is_dir() and "ICT_REPLAY_DATA_ROOT" not in os.environ:
            self.skipTest(f"external golden captures unavailable: {source}")
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source.glob("N*.*") if p.suffix in (".CSV", ".BEG", ".END")}
        with TemporaryDirectory() as temp:
            session = register_session(source, kind, Path(temp) / "research.sqlite3", csv_name=filename)
        metadata = session.metadata
        integrity = metadata["integrity"]
        self.assertEqual(metadata["experiment_id"], experiment)
        self.assertEqual(metadata["firmware_sha256"], FIRMWARE)
        self.assertEqual((integrity["data_rows"], integrity["csv_bytes"], integrity["csv_crc32"]), (rows, size, crc))
        self.assertTrue(integrity["passed"])
        self.assertTrue(integrity["acquisition_index_contiguous"])
        self.assertEqual(integrity["valid_counts"], dict(zip(
            ("imu_top", "imu_toe", "soil_top", "soil_middle", "soil_toe"), counts)))
        self.assertEqual(tuple(series.statistics()["count"] for series in session.channels), counts)
        self.assertEqual(sum(integrity["invalid_counts"].values()), 0)
        for channel in session.channels:
            self.assertTrue(all(sample.raw.timestamp_ms is None and not sample.raw.time_synced
                                and sample.usable for sample in channel.observations))
            self.assertGreater(channel.statistics()["median_interval_us"], 0)
        self.assertGreater(session.channels[0].statistics()["duration_s"], 299.9 if kind == "post_rain_static" else 179.9)
        if kind in ("rain_100", "post_rain_static"):
            self.assertIn("AIN2_JITTER_REVIEW", metadata["quality_flags"])
            self.assertIn("AIN2_JITTER_REVIEW", session.channels[-1].quality_flags)
        if kind == "post_rain_static":
            self.assertIn("POST_RAIN_NOT_DRY_BASELINE", metadata["quality_flags"])
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in source.glob("N*.*") if p.suffix in (".CSV", ".BEG", ".END")}
        self.assertEqual(before, after)

    def test_r1_rain_50_golden_capture(self):
        self.assert_capture("rain_50")

    def test_r2_rain_70_golden_capture(self):
        self.assert_capture("rain_70")

    def test_r3_rain_100_golden_capture(self):
        self.assert_capture("rain_100")

    def test_r4_post_rain_static_golden_capture(self):
        self.assert_capture("post_rain_static")


class LegacyFaultSDReplayTests(unittest.TestCase):
    def test_old_n2_preserves_771_sensor_errors(self):
        if not LEGACY_N2.is_file() and "ICT_REPLAY_LEGACY_N2" not in os.environ:
            self.skipTest(f"historical fault sample absent (not the new rain_70): {LEGACY_N2}")
        # Historical assessment appendix A pins the old sample independently.
        self.assertEqual(hashlib.sha256(LEGACY_N2.read_bytes()).hexdigest(),
                         "d54c00fda2788361d87f2c5975a5017b8ce5597e58288a4200b9ca4c4fe005fb")
        parsed = parse_sd_session(LEGACY_N2.parent, LEGACY_N2.name)
        self.assertEqual(parsed.integrity.csv_crc32, "311660b9")
        self.assertEqual(parsed.integrity.data_rows, 36020)
        self.assertEqual(parsed.integrity.valid_counts, dict(zip(
            ("imu_top", "imu_toe", "soil_top", "soil_middle", "soil_toe"), (17465, 17330, 166, 145, 143))))
        errors = [row for row in parsed.rows if row.validity != "Valid"]
        self.assertEqual(len(errors), 771)
        self.assertEqual(sum(row.kind == "imu" for row in errors), 145)
        self.assertEqual(sum(row.kind == "soil" for row in errors), 626)
        self.assertTrue(all(row.soil_raw is None for row in errors if row.kind == "soil"))


if __name__ == "__main__":
    unittest.main()
