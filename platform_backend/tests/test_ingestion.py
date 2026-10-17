import copy
import json
from pathlib import Path

import pytest

from geohazard_platform.database import Database
from geohazard_platform.telemetry import IngestionError, ingest_telemetry, validate_telemetry


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "platform.sqlite3")
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def payload():
    path = Path(__file__).resolve().parents[2] / "edge_intake/tests/fixtures/a_mock/cases/M01_NORMAL.json"
    return json.loads(path.read_text())["messages"][0]["payload"]


def rows(db, table):
    with db.connection() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM " + table)]


def risk_payload(payload, *, seq, score=None, level=None, boot=1, uptime=None):
    p = copy.deepcopy(payload)
    p.update(seq=seq, uptime_ms=seq * 1000 if uptime is None else uptime, boot_id=boot)
    p["risk"].update(sensor_score=score, level=level)
    return p


def test_durable_duplicate_conflict_and_restart(db, payload):
    result = ingest_telemetry(db, payload)
    assert result["status"] == "accepted" and result["durable"]
    assert result["node_cleanup_authorized"] is False
    assert ingest_telemetry(db, copy.deepcopy(payload))["status"] == "duplicate"
    changed = copy.deepcopy(payload)
    changed["soil"]["top_raw"] += 1
    with pytest.raises(IngestionError) as failure:
        ingest_telemetry(db, changed)
    assert failure.value.status_code == 409
    assert len(rows(db, "telemetry")) == 1
    assert len(rows(db, "intake_receipts")) == 2
    assert len(rows(db, "quarantine")) == 1
    db.close()
    db.initialize()
    assert ingest_telemetry(db, payload)["status"] == "duplicate"


def test_unknowns_and_sidecar_preserved_without_mutation(db, payload):
    original = copy.deepcopy(payload)
    context = {"demo_sensors": {"rainfall": 17}, "source": "REAL"}
    result = ingest_telemetry(db, payload, context=context)
    payload["soil"]["top_raw"] = -1
    stored = rows(db, "telemetry")[0]
    assert json.loads(stored["payload_json"]) == original
    assert result["risk"] == {"sensor_score": None, "level": None, "reason_mask": None}
    assert json.loads(stored["context_json"])["source"] == "MOCK"
    assert json.loads(stored["context_json"])["demo_sensors"] == {"rainfall": 17}
    assert rows(db, "alarms") == []
    assert context["source"] == "REAL"


def test_backfill_known_boot_and_null_risk_do_not_reset_alarm_baseline(db, payload):
    ingest_telemetry(db, risk_payload(payload, seq=5, score=82, level="EMERGENCY"))
    old = ingest_telemetry(db, risk_payload(payload, seq=1, score=90, level="EMERGENCY"))
    assert old["is_backfill"]
    ingest_telemetry(db, risk_payload(payload, seq=6))
    ingest_telemetry(db, risk_payload(payload, seq=7, score=84, level="EMERGENCY"))
    assert len(rows(db, "alarms")) == 1
    # Boot IDs are unique, not numerically monotonic.
    newer = ingest_telemetry(db, risk_payload(payload, seq=1, boot=0, score=70, level="WARNING"))
    assert newer["is_current"]
    backfill = ingest_telemetry(db, risk_payload(payload, seq=8, boot=1, score=95, level="EMERGENCY"))
    assert not backfill["is_current"] and backfill["alarm_id"] is None
    assert len([r for r in rows(db, "telemetry") if r["is_current"]]) == 1
    assert next(r for r in rows(db, "telemetry") if r["is_current"])["boot_id"] == 0


def test_alarm_only_upward_transitions_and_emergency_is_not_cleared(db, payload):
    for seq, score, level in [(1, 10, "NORMAL"), (2, 35, "WATCH"), (3, 50, "WATCH"), (4, 65, "WARNING"), (5, 85, "EMERGENCY"), (6, None, None), (7, 0, "NORMAL")]:
        ingest_telemetry(db, risk_payload(payload, seq=seq, score=score, level=level))
    alarms = rows(db, "alarms")
    assert [row["level"] for row in alarms] == ["WATCH", "WARNING", "EMERGENCY"]
    assert all(row["acknowledged"] == 0 for row in alarms)


@pytest.mark.parametrize("path,value", [
    (("seq",), True), (("boot_id",), -1), (("imu", 0, "ax"), float("nan")),
    (("imu", 0, "gx"), float("inf")), (("risk", "sensor_score"), 10**1000), (("soil", "top_pct"), 101),
    (("soil", "top_raw"), 40000), (("system", "wifi_up"), None),
    (("risk", "sensor_score"), False), (("experiment", "rain_level"), 4),
    (("timestamp_ms",), 123), (("imu", 0, "valid"), False),
])
def test_invalid_inputs_quarantined(db, payload, path, value):
    current = payload
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value
    with pytest.raises(IngestionError) as failure:
        ingest_telemetry(db, payload)
    assert failure.value.status_code == 422
    assert len(rows(db, "quarantine")) == 1
    assert rows(db, "telemetry") == []


def test_topic_identity_and_global_device_registration(db, payload):
    with pytest.raises(IngestionError):
        ingest_telemetry(db, payload, topic="zhifang/v2/wrong/NODE-01/telemetry")
    ingest_telemetry(db, payload, topic=f"zhifang/v2/{payload['site_id']}/{payload['device_id']}/telemetry")
    moved = copy.deepcopy(payload)
    moved.update(seq=2, site_id="OTHER")
    with pytest.raises(IngestionError) as failure:
        ingest_telemetry(db, moved)
    assert failure.value.status_code == 409


def test_exact_shape_and_risk_classification(payload):
    p = copy.deepcopy(payload)
    p["transport"] = "mqtt"
    assert validate_telemetry(p)
    p = copy.deepcopy(payload)
    p["risk"] = {"sensor_score": 29.9, "level": "WATCH", "reason_mask": None}
    assert validate_telemetry(p)
    p["risk"]["level"] = "NORMAL"
    assert validate_telemetry(p) == []


def test_transaction_rolls_back(db):
    with pytest.raises(RuntimeError):
        with db.connection() as connection:
            connection.execute("INSERT INTO events VALUES('one','test','message',NULL,NULL,'MOCK','{}','now')")
            raise RuntimeError("interrupted")
    assert rows(db, "events") == []


def test_invalid_utf8_payload_is_quarantined_as_escaped_json(db, payload):
    payload["experiment"]["run_id"] = "bad-\ud800"
    with pytest.raises(IngestionError) as failure:
        ingest_telemetry(db, payload)
    assert failure.value.status_code == 422
    assert rows(db, "telemetry") == []
    quarantined = rows(db, "quarantine")[0]
    assert "\\ud800" in quarantined["raw_payload"]
    assert json.loads(quarantined["raw_payload"])["experiment"]["run_id"] == "bad-\ud800"


def test_invalid_utf8_sidecar_maps_edge_intake_error_to_422(db, payload):
    with pytest.raises(IngestionError) as failure:
        ingest_telemetry(db, payload, context={"note": "\ud800"})
    assert failure.value.status_code == 422
    assert rows(db, "telemetry") == []
    assert len(rows(db, "quarantine")) == 1
