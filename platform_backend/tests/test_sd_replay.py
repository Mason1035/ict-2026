"""Synthetic SD captures only; real captures stay outside the repository."""

import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
import zlib

from geohazard_platform.research_sessions import (
    ReplayIdentityConflict, main, register_session, to_analysis_session,
)
from geohazard_platform.sd_replay import COLUMNS, ReplayValidationError, parse_sd_session


FIRMWARE = "a" * 64
EXPERIMENT = "NODE01-synthetic-N0000001.CSV"


def observation(kind, channel, index, acquired, *, validity="Valid", error=0, soil=42):
    row = dict.fromkeys(COLUMNS, "")
    row.update(kind=kind, channel=str(channel), acquisition_index=str(index),
               attempted_uptime_us=str(acquired - 10 if acquired is not None else 1500),
               acquired_uptime_us=str(acquired) if acquired is not None else "",
               time_synced="false", validity=validity, error=str(error))
    if kind == "imu":
        row.update(dict.fromkeys(COLUMNS[9:15], "1"))
        row.update(dict.fromkeys(COLUMNS[15:21], "1.25"))
    elif soil is not None:
        row["soil_raw"] = str(soil)
    return row


def sample_rows():
    return [
        observation("imu", 0, 0, 1100), observation("imu", 1, 1, 1200),
        observation("soil", 0, 2, 1300), observation("soil", 1, 3, 1400),
        observation("soil", 2, 4, 1500), observation("imu", 0, 5, 11100),
        observation("imu", 1, 6, 11200),
    ]


def write_capture(directory, rows=None, *, experiment_id=EXPERIMENT):
    directory.mkdir(parents=True, exist_ok=True)
    rows = sample_rows() if rows is None else rows
    name = experiment_id.rsplit("-", 1)[-1]
    path = directory / name
    stream = io.StringIO(newline="")
    stream.write(f"# app_elf_sha256={FIRMWARE}; device=NODE-01; experiment_id={experiment_id}\n")
    writer = csv.DictWriter(stream, COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data = stream.getvalue().encode()
    path.write_bytes(data)
    begin = {"record_type": "START_INTENT", "experiment_id": experiment_id,
             "elf_sha256": FIRMWARE, "csv": "/sdcard/" + name}
    end = {**begin, "record_type": "END", "start_us": 1000, "stop_us": 20000,
           "csv_bytes": len(data), "csv_crc32": f"{zlib.crc32(data):08x}",
           "verified_rows": len(rows), "accepted": len(rows)}
    counts = {(kind, channel): sum(row["kind"] == kind and row["channel"] == str(channel)
                                  and row["validity"] == "Valid" for row in rows)
              for kind, channel in (("imu", 0), ("imu", 1), ("soil", 0), ("soil", 1), ("soil", 2))}
    end.update(top_valid=counts[("imu", 0)], toe_valid=counts[("imu", 1)],
               soil_valid=[counts[("soil", i)] for i in range(3)])
    path.with_suffix(".BEG").write_text(json.dumps(begin))
    path.with_suffix(".END").write_text(json.dumps(end))
    return path


class SDReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.path = write_capture(self.capture)
        self.registry = self.root / "research.sqlite3"

    def edit_sidecar(self, extension, **changes):
        path = self.path.with_suffix(extension)
        record = json.loads(path.read_text())
        record.update(changes)
        path.write_text(json.dumps(record))

    def analysis(self, rows=None):
        if rows is not None:
            write_capture(self.capture, rows)
        return to_analysis_session(parse_sd_session(self.capture), "rain_50", replay_id="test-replay")

    def channels(self, session):
        return {series.sensor_id: series for series in session.channels}

    def test_exact_fingerprints_counts_and_source_lines(self):
        parsed = parse_sd_session(self.capture)
        self.assertTrue(parsed.integrity.passed)
        self.assertEqual(parsed.integrity.data_rows, 7)
        self.assertEqual(parsed.integrity.valid_counts,
                         {"imu_top": 2, "imu_toe": 2, "soil_top": 1, "soil_middle": 1, "soil_toe": 1})
        self.assertEqual(parsed.integrity.file_sha256["csv"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(parsed.rows[0].source_line, 3)
        self.assertEqual(parsed.rows[0].imu_raw, (1,) * 6)
        self.assertEqual(parsed.rows[0].acceleration_mps2, (1.25,) * 3)
        self.assertIsNone(parsed.rows[0].timestamp_ms)
        self.assertFalse(parsed.rows[0].time_synced)

    def test_top_toe_and_soils_have_independent_series(self):
        session = self.analysis()
        channels = self.channels(session)
        self.assertEqual(len(channels), 5)
        self.assertEqual([s.raw.acquisition_index for s in channels["imu_top"].observations], [0, 5])
        self.assertEqual([s.raw.acquisition_index for s in channels["imu_toe"].observations], [1, 6])
        self.assertEqual([s.relative_time_us for s in channels["imu_top"].observations], [100, 10100])
        self.assertEqual(channels["imu_top"].statistics()["median_interval_us"], 10000)
        self.assertEqual(channels["imu_toe"].statistics()["duration_s"], .01)
        self.assertEqual(channels["soil_toe"].units, ("ADC raw code",))
        self.assertIsNone(channels["soil_toe"].statistics()["median_interval_us"])
        self.assertEqual((session.metadata["source"], session.metadata["scope"],
                          session.metadata["transport"]), ("REAL", "TEST_ONLY", "sd_replay"))
        self.assertFalse(session.metadata["fusion_eligible"])
        self.assertFalse(session.metadata["risk_eligible"])
        self.assertTrue(session.metadata["generated_replay_identity"])
        self.assertIsNone(session.metadata["boot_id"])

    def test_failed_rows_are_retained_and_never_bridge_intervals(self):
        rows = [observation("imu", 0, 0, 1100),
                observation("imu", 0, 1, None, validity="Error", error=263),
                observation("imu", 0, 2, 11100)]
        # Payloads may be absent on errors, including every IMU measurement.
        for key in COLUMNS[9:21]:
            rows[1][key] = ""
        session = self.analysis(rows)
        channel = session.channels[0]
        failed = channel.observations[1]
        self.assertEqual((failed.raw.validity, failed.raw.error), ("Error", 263))
        self.assertIsNone(failed.relative_time_us)
        self.assertEqual(failed.raw.acceleration_mps2, (None,) * 3)
        self.assertFalse(failed.usable)
        self.assertIn("SENSOR_ERRORS_PRESENT", session.metadata["quality_flags"])
        self.assertEqual(session.metadata["invalid_counts"]["imu_top"], 1)
        self.assertEqual(channel.statistics()["usable_count"], 2)
        self.assertIsNone(channel.statistics()["median_interval_us"])

    def test_missing_soil_stays_missing_and_legal_zero_is_preserved(self):
        rows = [observation("soil", 0, 0, 1100, soil=0),
                observation("soil", 1, 1, None, validity="Error", error=1, soil=None),
                observation("soil", 2, 2, 1300, soil=None)]
        channels = self.channels(self.analysis(rows))
        self.assertEqual(channels["soil_top"].observations[0].raw.soil_raw, 0)
        self.assertTrue(channels["soil_top"].observations[0].usable)
        for sensor in ("soil_middle", "soil_toe"):
            channel = channels[sensor]
            self.assertIsNone(channel.observations[0].raw.soil_raw)
            self.assertEqual(channel.statistics()["usable_count"], 0)
            self.assertIsNone(channel.statistics()["duration_s"])
        self.assertIsNone(channels["imu_top"].statistics()["duration_s"])

    def test_validity_alone_does_not_hide_missing_time_or_error_codes(self):
        rows = [observation("imu", 0, 0, None), observation("imu", 1, 1, 1100, error=1)]
        session = self.analysis(rows)
        self.assertTrue(session.metadata["sensor_errors_present"])
        for channel in session.channels[:2]:
            self.assertEqual(channel.statistics()["valid_count"], 1)
            self.assertEqual(channel.statistics()["usable_count"], 0)

    def test_time_reversal_duplicate_and_attempt_order_are_flagged_per_sensor(self):
        rows = [observation("imu", 0, 0, 2100), observation("imu", 1, 1, 1100),
                observation("imu", 0, 2, 2000), observation("imu", 0, 3, 2100),
                observation("imu", 0, 4, 3100)]
        rows[-1]["attempted_uptime_us"] = "3200"
        channels = self.channels(self.analysis(rows))
        self.assertTrue(channels["imu_toe"].observations[0].usable)
        top = channels["imu_top"]
        self.assertIn("TIME_BACKWARDS", top.observations[1].quality_flags)
        self.assertIn("DUPLICATE_SAMPLE_TIME", top.observations[2].quality_flags)
        self.assertIn("ACQUIRED_BEFORE_ATTEMPT", top.observations[3].quality_flags)
        self.assertIsNone(top.statistics()["median_interval_us"])

    def test_relative_time_uses_acquired_not_attempted_or_wall_clock(self):
        rows = sample_rows()
        rows[0].update(attempted_uptime_us="1001", timestamp_ms="123456789", time_synced="true")
        sample = self.analysis(rows).channels[0].observations[0]
        self.assertEqual(sample.relative_time_us, 100)
        self.assertEqual(sample.raw.timestamp_ms, 123456789)

    def test_independent_end_integrity_assertions(self):
        for field, value in (("csv_bytes", 1), ("csv_crc32", "ffffffff"),
                             ("verified_rows", 1), ("accepted", 1), ("top_valid", 3)):
            with self.subTest(field=field):
                write_capture(self.capture)
                self.edit_sidecar(".END", **{field: value})
                with self.assertRaises(ReplayValidationError) as error:
                    parse_sd_session(self.capture)
                self.assertFalse(error.exception.integrity.passed)

    def test_same_length_byte_corruption_fails_crc(self):
        self.path.write_bytes(self.path.read_bytes().replace(b"1.25", b"1.26", 1))
        with self.assertRaises(ReplayValidationError) as error:
            parse_sd_session(self.capture)
        self.assertIn("csv_crc32", str(error.exception))

    def test_indices_must_start_at_zero_and_be_contiguous_including_errors(self):
        for offset, index in ((0, "1"), (1, "0"), (1, "2"), (5, "4")):
            with self.subTest(offset=offset, index=index):
                rows = sample_rows()
                rows[offset].update(acquisition_index=index, validity="Error")
                write_capture(self.capture, rows)
                with self.assertRaises(ReplayValidationError) as error:
                    parse_sd_session(self.capture)
                self.assertFalse(error.exception.integrity.acquisition_index_contiguous)

    def test_mixed_sidecars_and_csv_identities_are_rejected(self):
        for extension, changes in ((".END", {"experiment_id": "another"}),
                                   (".END", {"elf_sha256": "b" * 64}),
                                   (".BEG", {"csv": "/sdcard/another.CSV"})):
            with self.subTest(extension=extension, changes=changes):
                write_capture(self.capture)
                self.edit_sidecar(extension, **changes)
                with self.assertRaises(ReplayValidationError):
                    parse_sd_session(self.capture)
        write_capture(self.capture)
        self.path.write_bytes(self.path.read_bytes().replace(FIRMWARE.encode(), b"b" * 64, 1))
        with self.assertRaisesRegex(ReplayValidationError, "CSV/BEG firmware"):
            parse_sd_session(self.capture)

    def test_invalid_schema_or_measurement_is_never_silently_skipped(self):
        for changes in ({"kind": "other"}, {"channel": "3"}, {"acquisition_index": "1.5"},
                        {"time_synced": "unknown"}, {"validity": ""}, {"gx_dps": "nan"},
                        {"ay_mps2": "inf"}, {"time_synced": "true"}):
            with self.subTest(changes=changes):
                rows = sample_rows()
                rows[0].update(changes)
                write_capture(self.capture, rows)
                with self.assertRaisesRegex(ReplayValidationError, "CSV line 3"):
                    parse_sd_session(self.capture)
        write_capture(self.capture)
        self.path.write_bytes(self.path.read_bytes().replace(b"kind,channel", b"type,channel"))
        with self.assertRaisesRegex(ReplayValidationError, "22-column"):
            parse_sd_session(self.capture)

    def test_missing_sidecar_and_ambiguous_selection_are_rejected(self):
        self.path.with_suffix(".END").unlink()
        with self.assertRaises(ReplayValidationError):
            parse_sd_session(self.capture)
        write_capture(self.capture)
        write_capture(self.capture, experiment_id="NODE01-other-N0000002.CSV")
        with self.assertRaisesRegex(ReplayValidationError, "one CSV"):
            parse_sd_session(self.capture)
        self.assertEqual(parse_sd_session(self.capture, "N0000001.CSV").experiment_id, EXPERIMENT)
        with self.assertRaisesRegex(ReplayValidationError, "basename"):
            parse_sd_session(self.capture, "../capture/N0000001.CSV")

    def test_capture_quality_flags_use_full_identity(self):
        for identity, kind in (("NODE01-f9029c8eef460b40-N0000004.CSV", "rain_100"),
                               ("NODE01-2e379f02688fd631-N0000005.CSV", "post_rain_static")):
            with self.subTest(identity=identity):
                directory = self.root / kind
                write_capture(directory, experiment_id=identity)
                session = to_analysis_session(parse_sd_session(directory), kind, replay_id="test-id")
                self.assertIn("AIN2_JITTER_REVIEW", session.metadata["quality_flags"])
                self.assertEqual(session.channels[-1].quality_flags, ("AIN2_JITTER_REVIEW",))
                self.assertEqual(session.channels[0].quality_flags, ())
                if kind == "post_rain_static":
                    self.assertIn("POST_RAIN_NOT_DRY_BASELINE", session.metadata["quality_flags"])
        self.assertNotIn("AIN2_JITTER_REVIEW", self.analysis().metadata["quality_flags"])

    def test_registration_is_durable_idempotent_and_read_only_for_raw_files(self):
        before = {p.name: p.read_bytes() for p in self.capture.iterdir()}
        first = register_session(self.capture, "rain_50", self.registry)
        second = register_session(self.capture, "rain_50", self.registry)
        self.assertEqual(first.metadata, second.metadata)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.capture.iterdir()})
        with sqlite3.connect(self.registry) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM research_sd_sessions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT status FROM research_sd_attempts").fetchall(),
                             [("REGISTERED",), ("DUPLICATE",)])

    def test_known_r4_cannot_be_registered_as_a_rain_session(self):
        other = self.root / "r4"
        write_capture(other, experiment_id="NODE01-2e379f02688fd631-N0000005.CSV")
        with self.assertRaisesRegex(ValueError, "requires session type post_rain_static"):
            register_session(other, "rain_50", self.registry)
        with sqlite3.connect(self.registry) as db:
            self.assertEqual(db.execute("SELECT status FROM research_sd_attempts").fetchall(),
                             [("REJECTED_METADATA",)])
            self.assertEqual(db.execute("SELECT count(*) FROM research_sd_sessions").fetchone()[0], 0)

    def test_same_basename_different_experiments_do_not_collide_or_share_series(self):
        other = self.root / "other"
        rows = [observation("soil", 0, 0, 1300, soil=0)]
        write_capture(other, rows, experiment_id="NODE01-different-N0000001.CSV")
        first = register_session(self.capture, "rain_50", self.registry)
        second = register_session(other, "rain_70", self.registry)
        self.assertNotEqual(first.metadata["replay_id"], second.metadata["replay_id"])
        self.assertEqual(len(first.channels[0].observations), 2)
        self.assertEqual(second.channels[0].observations, ())
        self.assertEqual(second.channels[2].observations[0].relative_time_us, 300)

    def test_same_identity_changed_bytes_or_label_are_audited_without_overwriting(self):
        original = register_session(self.capture, "rain_50", self.registry)
        with self.assertRaises(ReplayIdentityConflict):
            register_session(self.capture, "rain_70", self.registry)
        rows = sample_rows()
        rows[2]["soil_raw"] = "100"
        write_capture(self.capture, rows)
        with self.assertRaises(ReplayIdentityConflict):
            register_session(self.capture, "rain_50", self.registry)
        with sqlite3.connect(self.registry) as db:
            stored = json.loads(db.execute("SELECT metadata_json FROM research_sd_sessions").fetchone()[0])
            self.assertEqual(stored, json.loads(json.dumps(original.metadata)))
            self.assertEqual(db.execute("SELECT count(*) FROM research_sd_attempts WHERE status='REJECTED_IDENTITY'")
                             .fetchone()[0], 2)

    def test_integrity_failure_is_persisted_and_exposes_no_registered_session(self):
        self.edit_sidecar(".END", csv_crc32="00000000")
        with self.assertRaises(ReplayValidationError):
            register_session(self.capture, "rain_50", self.registry)
        with sqlite3.connect(self.registry) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM research_sd_sessions").fetchone()[0], 0)
            status, details = db.execute("SELECT status,details_json FROM research_sd_attempts").fetchone()
            self.assertEqual(status, "REJECTED_INTEGRITY")
            self.assertFalse(json.loads(details)["integrity"]["passed"])
            self.assertIn("csv_crc32", json.loads(details)["issues"][0])

    def test_registry_cannot_write_into_capture_or_operational_database(self):
        raw_registry = self.capture / "registry.sqlite3"
        with self.assertRaisesRegex(ValueError, "read-only capture"):
            register_session(self.capture, "rain_50", raw_registry)
        self.assertFalse(raw_registry.exists())
        operational = self.root / "operational.sqlite3"
        with sqlite3.connect(operational) as db:
            db.executescript("CREATE TABLE telemetry (current_value TEXT); INSERT INTO telemetry VALUES('keep');")
        before = operational.read_bytes()
        with self.assertRaisesRegex(ValueError, "dedicated research registry"):
            register_session(self.capture, "rain_50", operational)
        self.assertEqual(operational.read_bytes(), before)

    def test_cli_prints_statistics_and_reports_validation_failure(self):
        args = [str(self.capture), "--type", "rain_50", "--registry", str(self.registry)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args), 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["metadata"]["experiment_id"], EXPERIMENT)
        self.assertEqual(summary["channels"]["imu_top"]["count"], 2)
        self.edit_sidecar(".END", csv_bytes=1)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(args), 1)
        self.assertEqual(json.loads(errors.getvalue())["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
