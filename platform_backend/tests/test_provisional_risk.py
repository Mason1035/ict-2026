"""Synthetic vectors/counts only. Provisional processing cannot confer alarm eligibility."""
import copy
import json
import math

from fastapi.testclient import TestClient
import pytest

from geohazard_platform import provisional_config as cfg, provisional_risk as pr
from geohazard_platform.main import create_app
from geohazard_platform.settings import Settings
from geohazard_platform.telemetry import ingest_telemetry
from test_ingestion import db, payload, rows


def sample(payload, seq=1, boot=1):
    p = copy.deepcopy(payload)
    p.update(seq=seq, boot_id=boot, uptime_ms=seq * 1000, timestamp_ms=None, time_synced=False)
    p["risk"] = dict.fromkeys(("level", "sensor_score", "reason_mask"))
    p["soil"].update(top_raw=20670, middle_raw=20879, toe_raw=-32768)
    for imu in p["imu"]:
        imu.update(valid=True, ax=0, ay=0, az=cfg.GRAVITY_MPS2, gx=0, gy=0, gz=0)
    return p


@pytest.mark.parametrize("channel", ["top", "middle"])
def test_endpoints_clipping_and_missing(channel):
    dry, wet = cfg.SOIL_ENDPOINTS[channel]
    assert pr.moisture_index(dry, channel) == (0, [])
    assert pr.moisture_index(wet, channel) == (1, [])
    index, flags = pr.moisture_index((dry + wet)/2, channel)
    assert index == pytest.approx(.5) and flags == []
    assert pr.moisture_index(dry + 10, channel) == (0, ["SOIL_INDEX_CLIPPED"])
    assert pr.moisture_index(wet - 10, channel) == (1, ["SOIL_INDEX_CLIPPED"])
    assert pr.moisture_index(None, channel)[0] is None
    assert pr.moisture_index(-32768, "toe") == (None, ["AIN2_EXCLUDED_DIAGNOSTIC_ONLY"])


def test_known_gravity_baseline_rms_and_causal_state(payload):
    state = None
    for seq in range(1, cfg.BASELINE_SAMPLES + 1):
        result, state = pr.compute(sample(payload, seq), state)
    m = result["features"]["imu"]["top"]
    assert m == dict(tilt_deg=0, direction_angle_deg=0, vibration_rms_mps2=0, gyro_rms_dps=0)
    frozen = copy.deepcopy(state)
    rotated = sample(payload, 11)
    rotated["imu"][0].update(ax=cfg.GRAVITY_MPS2, az=0, gx=3, gy=4)
    result, state = pr.compute(rotated, state)
    assert frozen["imus"]["top"]["baseline"] == state["imus"]["top"]["baseline"]
    assert result["features"]["imu"]["top"]["direction_angle_deg"] == pytest.approx(90)
    assert result["features"]["imu"]["top"]["tilt_deg"] == pytest.approx(90)
    assert result["features"]["imu"]["top"]["gyro_rms_dps"] == pytest.approx(5/math.sqrt(2))
    p1 = sample(payload)
    p1["imu"][0]["az"] += 1
    _, state = pr.compute(p1)
    p2 = sample(payload, 2)
    p2["imu"][0]["az"] -= 1
    result, _ = pr.compute(p2, state)
    assert result["features"]["imu"]["top"]["vibration_rms_mps2"] == pytest.approx(1)
    assert pr.rms([3, 4]) == pytest.approx(math.sqrt(12.5))


def test_levels_and_threshold_provenance(payload):
    p = sample(payload)
    result, _ = pr.compute(p)
    assert result["level"] == "NORMAL"  # AIN2 cannot trigger.
    p["soil"]["top_raw"] = 15000
    assert pr.compute(p)[0]["level"] == "ATTENTION"
    p["soil"]["top_raw"] = 12510
    result, _ = pr.compute(p)
    assert (result["level"], result["score"]) == ("WARNING", 100)
    assert result["reasons"][0]["threshold_source"] == cfg.VERSION
    features = {"soil_index": {}, "imu": {"top": dict(direction_angle_deg=None, vibration_rms_mps2=None, gyro_rms_dps=None)}}
    assert pr.map_level(features) == (None, None, [])
    for metric in features["imu"]["top"]:
        f = copy.deepcopy(features)
        threshold = cfg.reference_config()["channels"]["imu_top"]["metrics"][metric]["frozen_value"]
        f["imu"]["top"][metric] = threshold * 1.5
        assert pr.map_level(f)[0] == "ATTENTION"
        f["imu"]["top"][metric] = threshold * 3
        level, _, reasons = pr.map_level(f)
        assert level == "WARNING" and cfg.REFERENCE_PATH in reasons[0]["threshold_source"]


@pytest.mark.parametrize("scope", ["OPERATIONAL", "TEST_ONLY"])
def test_real_ingestion_preserves_formal_fields_and_duplicates(db, payload, scope):
    p = sample(payload)
    if scope == "TEST_ONLY":
        p["experiment"]["run_id"] = "REAL_REPLAY|synthetic|v1"
    original = copy.deepcopy(p)
    receipt = ingest_telemetry(db, p, source="REAL", scope=scope, transport="mqtt")
    assert receipt["status"] == "accepted" and receipt["risk"] == original["risk"]
    assert receipt["is_current"] is (scope == "OPERATIONAL")
    assert p == original and json.loads(rows(db, "telemetry")[0]["payload_json"]) == original
    r = pr.latest(db, site_id=p["site_id"], device_id=p["device_id"])
    assert r["telemetry_id"] == receipt["telemetry_id"]
    assert r["status"] == "PROVISIONAL" and r["calibration_version"] is None
    assert r["fusion_eligible"] is False and r["disclaimer"] == cfg.DISCLAIMER
    assert rows(db, "alarms") == []
    ingest_telemetry(db, p, source="REAL", scope=scope, transport="mqtt")
    assert len(rows(db, "provisional_risk")) == 1


def test_restart_boot_scope_partition_and_late_observation(db, payload):
    p = sample(payload)
    for seq in range(1, 11):
        p = sample(payload, seq)
        ingest_telemetry(db, p, source="REAL", scope="OPERATIONAL", transport="mqtt")
    db.close()
    db.initialize()
    for seq, boot, scope in ((12, 1, "OPERATIONAL"), (11, 1, "OPERATIONAL"), (13, 1, "TEST_ONLY"), (1, 2, "OPERATIONAL")):
        p = sample(payload, seq, boot)
        p["imu"][0].update(ax=cfg.GRAVITY_MPS2, az=0)
        ingest_telemetry(db, p, source="REAL", scope=scope, transport="mqtt")
        r = pr.latest(db, site_id=p["site_id"], device_id=p["device_id"])
        if seq == 12:
            assert r["features"]["imu"]["top"]["direction_angle_deg"] == pytest.approx(90)
        elif seq == 11:
            assert r["level"] is None and "OUT_OF_ORDER_NOT_EVALUATED" in r["quality_flags"]
        else:
            assert r["features"]["imu"]["top"]["direction_angle_deg"] is None


def test_missing_and_gaps_do_not_fabricate_ready_features(payload):
    p = sample(payload)
    p["soil"] = dict.fromkeys(p["soil"])
    for imu in p["imu"]:
        imu.update(valid=False, **dict.fromkeys(set(imu) - {"id", "valid"}))
    result, _ = pr.compute(p)
    assert result["level"] is None
    _, state = pr.compute(sample(payload))
    result, _ = pr.compute(sample(payload, 10), state)
    assert result["features"]["imu"]["top"]["vibration_rms_mps2"] is None
    assert "imu.top:RMS_GAP_RESET" in result["quality_flags"]


def test_provisional_failure_rolls_back_only_savepoint(db, payload, monkeypatch, caplog):
    def failure(*args, **kwargs):
        with db.connection() as c:
            c.execute("INSERT INTO provisional_risk(telemetry_id,result_json) VALUES(?,?)", (args[1], "{}"))
            raise RuntimeError("synthetic failure")
    monkeypatch.setattr(pr, "compute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("feature failure")))
    receipt = ingest_telemetry(db, sample(payload))
    assert receipt["status"] == "accepted" and len(rows(db, "telemetry")) == 1
    assert rows(db, "provisional_risk") == [] and "Provisional risk failed" in caplog.text
    monkeypatch.setattr(pr, "record", failure)
    assert ingest_telemetry(db, sample(payload, 2))["status"] == "accepted"
    assert len(rows(db, "telemetry")) == 2 and rows(db, "provisional_risk") == []
    assert rows(db, "alarms") == []


def test_lan_api_auth_origin_and_provisional_dashboard(tmp_path, payload):
    settings = Settings(data_dir=tmp_path, demo_enabled=False, host="0.0.0.0", api_token="lan-token", acl_mode="off")
    with TestClient(create_app(settings), base_url="http://192.0.2.1:8000", client=("192.0.2.2", 1234)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/v1/health").status_code == 401
        client.headers.update({"Authorization": "Bearer lan-token", "Origin": "http://192.0.2.1:8000"})
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health", headers={"Origin": "http://evil.example"}).status_code == 403
        p = sample(payload)
        ingest_telemetry(client.app.state.db, p, source="REAL", scope="OPERATIONAL", transport="mqtt")
        query = {"site_id": p["site_id"], "device_id": p["device_id"], "source": "REAL"}
        latest = client.get("/api/v1/provisional-risk/latest", params=query).json()
        assert latest["status"] == "PROVISIONAL"
        h = client.get("/api/v1/provisional-risk/history", params=query).json()["items"]
        assert h == [latest]
        assert client.get("/api/v1/provisional-risk/history", params={**query, "before": "bad"}).status_code == 422
        dash = client.get("/api/v1/dashboard", params=query).json()
        assert dash["provisional_risk"] == latest and dash["provisional_history"] == h
        assert dash["latest"]["risk"]["level"] == "unknown" and dash["alarms"] == []
        # Replay is visible while remaining backfill with formal latest unavailable.
        p.update(device_id="REPLAY-SYNTHETIC")
        p["experiment"]["run_id"] = "REAL_REPLAY|synthetic|v1"
        ingest_telemetry(client.app.state.db, p, source="REAL", scope="TEST_ONLY", transport="mqtt")
        dash = client.get("/api/v1/dashboard", params={**query, "device_id": p["device_id"]}).json()
        assert dash["latest"] is None and dash["provisional_risk"]["scope"] == "TEST_ONLY"
