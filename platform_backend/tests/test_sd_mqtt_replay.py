"""Synthetic triplets; real captures opt in and remain read-only."""
import io
import json
import math
import os
from pathlib import Path
from unittest.mock import patch

import unittest
from tempfile import TemporaryDirectory
from contextlib import redirect_stdout, redirect_stderr
import importlib.util

from geohazard_platform.sd_mqtt_replay import ReplayOptions, deterministic_boot, frames, main, replay
from geohazard_platform.sd_replay import parse_sd_session, ReplayValidationError
from geohazard_platform.telemetry import IMU_NUMBERS, SOIL_NUMBERS, TOP, validate_telemetry
from test_sd_replay import observation, write_capture


def capture(tmp_path):
    rows = []
    # Realistic acquired-time ordering, including invalid observations and gaps.
    for t in range(10_000, 2_510_000, 10_000):
        for ch in (0, 1):
            if ch == 1 and 500_000 < t < 1_600_000:
                continue
            row = observation("imu", ch, len(rows), t, validity="Valid" if t != 700_000 else "I2CError")
            row.update(ax_mps2=str(t/1e6), ay_mps2="0", az_mps2="9.8")
            rows.append(row)
        if t == 10_000:
            for ch in range(3):
                rows.append(observation("soil", ch, len(rows), t, soil=100+ch))
    path = write_capture(tmp_path/"capture", rows, experiment_id="NODE01-02d2774d245ce042-N0000001.CSV")
    end = json.loads(path.with_suffix(".END").read_text())
    end.update(stop_us=2_510_000, storage_clean=True, i2c_errors=1)
    path.with_suffix(".END").write_text(json.dumps(end))
    return parse_sd_session(path.parent)


def check_projection_contract_nulls_age_identity_and_fingerprints(capture):
    before = capture.integrity.file_sha256
    options = ReplayOptions()
    data = list(frames(capture, 123, options))
    assert len(data) == 5
    assert [p["seq"] for p in data] == list(range(1, 6))
    assert data[0]["uptime_ms"] == 10
    for p in data:
        assert validate_telemetry(p, topic=options.topic) == []
        assert set(p) == TOP
        assert p["soil"]["toe_raw"] is None
        assert all(p["soil"][f] is None for f in SOIL_NUMBERS)
        assert all(v is None for v in p["risk"].values())
        assert p["timestamp_ms"] is None and p["time_synced"] is False
        assert p["system"]["sd_ok"] and p["system"]["sensor_degraded"]
        for imu in p["imu"]:
            assert imu["tilt_deg"] is imu["tilt_rate_dps"] is imu["vibration_rms"] is None
            if not imu["valid"]:
                assert all(imu[f] is None for f in IMU_NUMBERS)
    assert not data[2]["imu"][1]["valid"]
    assert data[0]["soil"]["top_raw"] == 100
    assert data[3]["soil"]["top_raw"] is None
    assert list(frames(capture, 123, ReplayOptions(include_ain2=True)))[0]["soil"]["toe_raw"] == 102
    assert validate_telemetry(data[0], topic="zhifang/v2/OTHER/OTHER/telemetry")
    out = io.StringIO()
    summary = replay(capture, 123, options, dry_run=True, output=out)
    assert summary["frames"] == 5 and summary["rejected"] == summary["published"] == 0
    assert len(out.getvalue().splitlines()) == 5
    assert parse_sd_session(capture.directory).integrity.file_sha256 == before


def check_schedule_accumulates_monotonic_and_retain_false(capture, speed):
    clock = [0.]
    calls = []
    def sleep(delay):
        clock[0] += delay
    def publish(topic, data, **kwargs):
        calls.append((clock[0], kwargs, json.loads(data)))
        clock[0] += .0001  # Publisher work must not accumulate as clock drift.
    report = replay(capture, 42, ReplayOptions(speed=speed), publish=publish,
                    monotonic=lambda: clock[0], sleep=sleep)
    assert report["published"] == 5
    for stamp, kwargs, payload in calls:
        assert math.isclose(stamp, (payload["uptime_ms"]-10)/1000/speed, abs_tol=1e-9)
        assert kwargs == {"qos": 0, "retain": False}


def check_invalid_options(field, value):
    with unittest.TestCase().assertRaises(ValueError):
        ReplayOptions(**{field: value})


def check_display_is_causal_and_matches_window_rms(capture):
    data = list(frames(capture, 1, ReplayOptions(derive_display=True)))
    assert all(validate_telemetry(p) == [] for p in data)
    assert abs(data[0]["imu"][0]["tilt_deg"]) <= 1e-6
    samples = [math.sqrt(r.acceleration_mps2[0]**2+9.8**2) for r in capture.rows
               if r.kind == "imu" and r.channel == 0 and 10_000 < r.acquired_uptime_us <= 510_000]
    mean = sum(samples)/len(samples)
    assert math.isclose(data[1]["imu"][0]["vibration_rms"], math.sqrt(sum((v-mean)**2 for v in samples)/len(samples)), abs_tol=1e-9)
    # Modify future observations; earlier outputs cannot change.
    from dataclasses import replace
    future = replace(capture, rows=tuple(replace(r, acceleration_mps2=(900., 0., 0.)) if r.acquired_uptime_us > 510_000 else r for r in capture.rows))
    assert list(frames(future, 1, ReplayOptions(derive_display=True)))[:2] == data[:2]


def check_cli_multiple_sessions_fresh_boot_seq_logs(capture, capsys):
    assert main([str(capture.directory), str(capture.directory), "--dry-run", "--deterministic-boot"]) == 0
    output = capsys.readouterr()
    data = [json.loads(line) for line in output.out.splitlines()]
    assert data[0]["boot_id"] == deterministic_boot(capture) <= 2**53-1
    assert data[5]["boot_id"] != data[0]["boot_id"]
    assert data[5]["seq"] == 1
    path = Path(output.err.split("Replay log: ")[-1].strip())
    log = json.loads(path.read_text())
    assert [s["boot_id"] for s in log["sessions"]] == [data[0]["boot_id"], data[5]["boot_id"]]
    assert all(s["experiment_id"] == capture.experiment_id for s in log["sessions"])
    assert main([str(capture.directory), "--dry-run", "--loop", "--max-frames", "7"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 7


def check_rejection_limit_and_fingerprint_detection(capture):
    from dataclasses import replace
    summary = {}
    with patch("geohazard_platform.sd_mqtt_replay.validate_telemetry", return_value=[{"message": "bad"}]):
        with unittest.TestCase().assertRaisesRegex(ValueError, "10 consecutive"):
            replay(capture, 1, ReplayOptions(frame_hz=10), dry_run=True, summary=summary)
    assert summary["rejected"] == 10 and summary["published"] == 0
    path = capture.directory/capture.csv_name
    path.write_bytes(path.read_bytes()+b"\n")
    with unittest.TestCase().assertRaises(ReplayValidationError):
        parse_sd_session(capture.directory)
    with unittest.TestCase().assertRaisesRegex(ValueError, "fingerprint"):
        replay(capture, 1, ReplayOptions(), dry_run=True, output=io.StringIO())


def check_real_air_dry_run(capsys):
    root = os.environ.get("ICT_REPLAY_DATA_ROOT")
    if not root:
        raise unittest.SkipTest("ICT_REPLAY_DATA_ROOT not set")
    directory = Path(root)/"标定土壤传感器/AIR-1"
    assert main([str(directory), "--csv", "N0000010.CSV", "--dry-run", "--frame-hz", "2"]) == 0
    out = capsys.readouterr()
    data = [json.loads(line) for line in out.out.splitlines()]
    assert 59 <= len(data) <= 61
    assert all(validate_telemetry(p, topic=ReplayOptions().topic) == [] for p in data)


def check_local_real_mqtt_test_only_dashboard(capture, tmp_path, demo):
    from test_mqtt_integration import LocalBroker, wait_for, count
    from test_api import opened
    import paho.mqtt.client as mqtt
    options = ReplayOptions(speed=50)
    broker = LocalBroker()
    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        with opened(tmp_path/"api", demo=demo) as (client, app):
            db = app.state.db
            alarms_before = count(db, "alarms")
            response = client.post("/api/v1/connectors", json={"name": "Real SD replay", "kind": "mqtt", "source": "REAL", "enabled": True,
                "config": {"host": "127.0.0.1", "port": broker.port, "site_id": options.site_id,
                           "topic": "zhifang/v2/REPLAY-LAB/+/telemetry", "scope": "TEST_ONLY", "tls": False,
                           "qos": 0, "keepalive": 30, "payload_format": "telemetry_v2"}})
            assert response.status_code == 201, response.text
            wait_for(lambda: any(s["connected"] for s in client.get("/api/v1/health").json()["mqtt"]))
            publisher.connect("127.0.0.1", broker.port)
            publisher.loop_start()
            report = replay(capture, 123, options, publish=publisher.publish)
            def real_count():
                with db.connection() as c:
                    return c.execute("SELECT count(*) FROM telemetry WHERE source='REAL'").fetchone()[0]
            wait_for(lambda: real_count() == report["published"])
            assert real_count() == 5 and count(db, "alarms") == alarms_before
            devices = client.get("/api/v1/devices").json()["items"]
            assert any(d["device_id"] == options.device_id and d["source"] == "REAL" for d in devices)
            dash = client.get("/api/v1/dashboard", params={"site_id": options.site_id, "device_id": options.device_id, "source": "REAL"}).json()
            assert dash["latest"] is None  # Replay must never advance operational current state.
            assert dash["replay_latest"]["source"] == "REAL"
            assert dash["replay_latest"]["payload"]["seq"] == 5
            assert dash["stats"]["telemetry_count"] == 5
            assert dash["alarms"] == []
            assert count(db, "provisional_risk") == 5
            assert dash["provisional_risk"]["status"] == "PROVISIONAL"
            assert dash["provisional_risk"]["scope"] == "TEST_ONLY"
            assert dash["provisional_risk"]["fusion_eligible"] is False
    finally:
        publisher.disconnect()
        publisher.loop_stop()
        broker.stop()


class Captured:
    def __init__(self):
        self.out, self.err = io.StringIO(), io.StringIO()
    def __enter__(self):
        self.stdout = redirect_stdout(self.out)
        self.stderr = redirect_stderr(self.err)
        self.stdout.__enter__()
        self.stderr.__enter__()
        return self
    def __exit__(self, *args):
        self.stderr.__exit__(*args)
        self.stdout.__exit__(*args)
    def readouterr(self):
        from types import SimpleNamespace
        value = SimpleNamespace(out=self.out.getvalue(), err=self.err.getvalue())
        self.out.seek(0); self.out.truncate()
        self.err.seek(0); self.err.truncate()
        return value


def test_remote_broker_credentials_and_redacted_log(tmp_path, capsys, monkeypatch):
    session = capture(tmp_path)
    monkeypatch.setenv("GEOHAZARD_MQTT_PASSWORD", "synthetic-private-password")
    with patch("paho.mqtt.client.Client") as client:
        assert main([str(session.directory), "--host", "192.0.2.20", "--port", "1883",
                     "--username", "node01", "--max-frames", "1"]) == 0
        client.return_value.username_pw_set.assert_called_once_with("node01", "synthetic-private-password")
        client.return_value.connect.assert_called_once_with("192.0.2.20", 1883, keepalive=30)
        assert client.return_value.publish.call_count == 1
    output = capsys.readouterr()
    path = Path(output.err.split("Replay log: ")[-1].strip())
    assert "synthetic-private-password" not in path.read_text() + output.out + output.err
    assert json.loads(path.read_text())["options"]["password"] == "<redacted>"


class SDMQTTReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = capture(self.root)

    def test_projection_contract_nulls_age_identity_and_fingerprints(self):
        check_projection_contract_nulls_age_identity_and_fingerprints(self.capture)

    def test_schedule_accumulates_monotonic_and_retain_false(self):
        for speed in (.1, 1, 50):
            with self.subTest(speed=speed):
                check_schedule_accumulates_monotonic_and_retain_false(self.capture, speed)

    def test_invalid_options(self):
        for field, value in [("site_id", "a/b"), ("site_id", "+"), ("device_id", "x#"),
    ("device_id", "MOCK-X"), ("site_id", "DEMO-X"), ("device_id", ""), ("site_id", "\0"),
    ("speed", 0), ("speed", 51), ("frame_hz", 11), ("baseline_s", 0), ("imu_max_age_ms", -1)]:
            with self.subTest(field=field, value=value):
                check_invalid_options(field, value)

    def test_display_is_causal_and_matches_window_rms(self):
        check_display_is_causal_and_matches_window_rms(self.capture)

    def test_cli_multiple_sessions_fresh_boot_seq_logs(self):
        with Captured() as cap:
            check_cli_multiple_sessions_fresh_boot_seq_logs(self.capture, cap)

    def test_rejection_limit_and_fingerprint_detection(self):
        check_rejection_limit_and_fingerprint_detection(self.capture)

    def test_real_air_dry_run(self):
        with Captured() as cap:
            check_real_air_dry_run(cap)

    def test_test_only_history_visible_without_advancing_current(self):
        from geohazard_platform.database import Database
        from geohazard_platform.dashboard import device_listing, history, latest
        from geohazard_platform.telemetry import ingest_telemetry
        db = Database(":memory:")
        db.initialize()
        self.addCleanup(db.close)
        for p in frames(self.capture, 123):
            ingest_telemetry(db, p, source="REAL", scope="TEST_ONLY", transport="mqtt", topic=ReplayOptions().topic)
        devices = device_listing(db)["items"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "REPLAY-NODE01")
        self.assertEqual(devices[0]["scope"], "TEST_ONLY")
        self.assertEqual(device_listing(db, source="MOCK")["items"], [])
        self.assertIsNone(latest(db, device_id="REPLAY-NODE01", source="REAL"))
        rows = history(db, device_id="REPLAY-NODE01", source="REAL")["items"]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["is_backfill"] and r["source"] == "REAL" for r in rows))
        p = next(frames(self.capture, 456))
        p["device_id"] = "OTHER-NODE"
        p["experiment"]["run_id"] = "ordinary-test"
        ingest_telemetry(db, p, source="REAL", scope="TEST_ONLY", transport="mqtt")
        self.assertEqual(len(device_listing(db)["items"]), 1)
        with db.connection() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM alarms").fetchone()[0], 0)

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("paho", "amqtt", "fastapi", "pytest")), "MQTT/API test dependencies not installed")
    def test_local_real_mqtt_test_only_dashboard_demo_on(self):
        check_local_real_mqtt_test_only_dashboard(self.capture, self.root, True)

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("paho", "amqtt", "fastapi", "pytest")), "MQTT/API test dependencies not installed")
    def test_local_real_mqtt_test_only_dashboard_demo_off(self):
        check_local_real_mqtt_test_only_dashboard(self.capture, self.root, False)


if __name__ == "__main__":
    unittest.main()
