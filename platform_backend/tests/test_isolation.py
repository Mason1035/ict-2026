"""WP1 isolation regressions, also runnable with the standard unittest runner.

No broker, platform service, ACL runtime or third-party test dependency is needed
for these durable-intake and MQTT-callback checks. Pytest collects them normally.
"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from geohazard_platform.connectors import ConnectorError, _MQTTSession, get_connector, save_connector
from geohazard_platform.database import Database
from geohazard_platform.telemetry import IngestionError, ingest_telemetry


FIXTURE = Path(__file__).resolve().parents[2] / "edge_intake/tests/fixtures/a_mock/cases/M01_NORMAL.json"
NOW = "2026-11-02T06:00:00.000Z"
NOW_MS = int(datetime.fromisoformat(NOW.replace("Z", "+00:00")).timestamp() * 1000)


def sample(*, seq=1, boot=1, device="REAL-ISOLATION-01", level="EMERGENCY", score=90):
    payload = json.loads(FIXTURE.read_text())["messages"][0]["payload"]
    payload.update(device_id=device, seq=seq, boot_id=boot, uptime_ms=seq * 1000)
    payload["risk"].update(sensor_score=score, level=level)
    return payload


def ingest_real(db, payload, **metadata):
    return ingest_telemetry(db, payload, **{
        "source": "REAL", "scope": "OPERATIONAL", "transport": "mqtt", **metadata,
    })


def rows(db, table, where="1=1"):
    with db.connection() as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} WHERE {where}")]


def production_current(db):
    return rows(db, "telemetry", "source='REAL' AND scope='OPERATIONAL' AND is_current=1")


def mqtt_message(payload):
    return SimpleNamespace(topic=f"zhifang/v2/{payload['site_id']}/{payload['device_id']}/telemetry",
                           payload=json.dumps(payload).encode(), retain=False)


def connector_data(*, source="REAL", **config):
    return {"name": "WP1 isolated callback", "kind": "mqtt", "source": source, "enabled": False,
            "config": {"host": "127.0.0.1", "site_id": "MOCK-SITE-01", **config}}


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.initialize()
        self.addCleanup(self.db.close)

    def test_source_scope_behavior_matrix(self):
        for source, scope in (("MOCK", "TEST_ONLY"), ("MOCK", "OPERATIONAL"),
                              ("REAL", "TEST_ONLY"), ("REAL", "OPERATIONAL")):
            with self.subTest(source=source, scope=scope):
                db = Database(":memory:")
                self.addCleanup(db.close)
                baseline = ingest_real(db, sample(level="NORMAL", score=10))
                before = production_current(db)
                # MOCK provenance is globally separate from the REAL device.
                device = "MOCK-ISOLATION-01" if source == "MOCK" else "REAL-ISOLATION-01"
                receipt = ingest_telemetry(db, sample(seq=2, device=device), source=source,
                                           scope=scope, transport="mqtt")
                self.assertEqual(receipt["status"], "accepted")
                self.assertEqual(len(rows(db, "telemetry")), 2)
                stored = rows(db, "telemetry", "seq=2")[0]
                self.assertEqual((stored["source"], stored["scope"]), (source, scope))
                if (source, scope) == ("REAL", "OPERATIONAL"):
                    self.assertTrue(receipt["is_current"])
                    self.assertEqual(production_current(db)[0]["id"], receipt["telemetry_id"])
                    self.assertEqual(len(rows(db, "alarms")), 1)
                    self.assertEqual(rows(db, "alarms")[0]["scope"], "OPERATIONAL")
                    self.assertEqual(rows(db, "alarms")[0]["source_message_id"], receipt["telemetry_id"])
                else:
                    self.assertIsNone(receipt["alarm_id"])
                    self.assertEqual(rows(db, "alarms"), [])
                    self.assertEqual(rows(db, "events"), [])
                    self.assertEqual(production_current(db), before)
                    self.assertEqual(production_current(db)[0]["id"], baseline["telemetry_id"])
                # Non-production input is traceable without any alarm row.
                self.assertEqual(len(rows(db, "intake_receipts")), 2)

    def test_research_does_not_register_boot_or_suppress_later_escalation(self):
        ingest_real(self.db, sample(level="NORMAL", score=10))
        before = production_current(self.db)
        research = ingest_real(self.db, sample(seq=100, boot=42), scope="TEST_ONLY")
        self.assertFalse(research["is_current"])
        self.assertEqual(production_current(self.db), before)
        self.assertEqual(rows(self.db, "boot_sessions", "boot_id=42"), [])
        live = ingest_real(self.db, sample(seq=101, boot=42, level="WARNING", score=70))
        self.assertTrue(live["is_current"])
        self.assertEqual([r["level"] for r in rows(self.db, "alarms")], ["WARNING"])

    def test_first_real_test_input_never_becomes_current(self):
        research = ingest_real(self.db, sample(), scope="TEST_ONLY")
        self.assertFalse(research["is_current"])
        self.assertEqual(rows(self.db, "telemetry", "is_current=1"), [])
        self.assertEqual(rows(self.db, "boot_sessions"), [])
        live = ingest_real(self.db, sample(seq=2, level="WARNING", score=70))
        self.assertTrue(live["is_current"])
        self.assertIsNotNone(live["alarm_id"])

    def test_legacy_research_boot_registration_does_not_block_first_live_sample(self):
        ingest_real(self.db, sample(level="NORMAL", score=10))
        ingest_real(self.db, sample(boot=42), scope="TEST_ONLY")
        with self.db.connection() as connection:
            connection.execute("INSERT INTO boot_sessions(device_id,boot_id,first_seen) VALUES(?,42,?)",
                               ("REAL-ISOLATION-01", NOW))
        receipt = ingest_real(self.db, sample(boot=42, seq=2, level="WARNING", score=70))
        self.assertTrue(receipt["is_current"])
        self.assertIsNotNone(receipt["alarm_id"])

    def test_operational_business_gate_keeps_known_risk_across_unknown_readings(self):
        readings = ((10, "NORMAL"), (35, "WATCH"), (50, "WATCH"), (65, "WARNING"),
                    (85, "EMERGENCY"), (None, None), (92, "EMERGENCY"), (0, "NORMAL"))
        for seq, (score, level) in enumerate(readings, start=1):
            receipt = ingest_real(self.db, sample(seq=seq, score=score, level=level))
            self.assertTrue(receipt["is_current"])
        self.assertEqual([row["level"] for row in rows(self.db, "alarms")], ["WATCH", "WARNING", "EMERGENCY"])
        self.assertTrue(all(row["acknowledged"] == 0 for row in rows(self.db, "alarms")))

    def test_generated_or_unvalidated_identity_cannot_update_production(self):
        ingest_real(self.db, sample(level="NORMAL", score=10))
        before = production_current(self.db)
        for seq, context in enumerate((
                {"generated_replay_identity": True}, {"generated_replay_identity": "false"},
                {"identity_is_native_and_valid": False}, {"identity_is_native_and_valid": 1}), start=2):
            with self.subTest(context=context):
                receipt = ingest_real(self.db, sample(seq=seq), context=context)
                self.assertFalse(receipt["is_current"])
                self.assertIsNone(receipt["alarm_id"])
                self.assertEqual(production_current(self.db), before)
        self.assertEqual(rows(self.db, "alarms"), [])

    def test_replay_transport_or_sidecar_cannot_update_production(self):
        ingest_real(self.db, sample(level="NORMAL", score=10))
        before = production_current(self.db)
        cases = [
            {"transport": "sd_replay", "context": {"current_live_observation": True}},
            {"transport": "http_test"}, {"transport": "history_import"},
            {"context": {"current_live_observation": False}},
            {"context": {"is_replay": True}}, {"context": {"is_backfill": True}},
        ]
        for seq, metadata in enumerate(cases, start=2):
            with self.subTest(metadata=metadata):
                receipt = ingest_real(self.db, sample(seq=seq), **metadata)
                self.assertFalse(receipt["is_current"])
                self.assertIsNone(receipt["alarm_id"])
                self.assertEqual(production_current(self.db), before)
        self.assertEqual(rows(self.db, "alarms"), [])

    def test_stale_or_future_synchronized_input_is_not_live(self):
        with patch("geohazard_platform.telemetry.utc_now", return_value=NOW):
            for seq, offset in enumerate((-31000, 31000), start=1):
                with self.subTest(offset=offset):
                    payload = sample(seq=seq)
                    payload.update(time_synced=True, timestamp_ms=NOW_MS + offset)
                    receipt = ingest_real(self.db, payload)
                    self.assertFalse(receipt["is_current"])
                    self.assertIsNone(receipt["alarm_id"])
        self.assertEqual(production_current(self.db), [])
        self.assertEqual(rows(self.db, "boot_sessions"), [])
        self.assertEqual(len(rows(self.db, "telemetry")), 2)

    def test_fresh_synchronized_input_can_escalate_and_uses_configured_freshness(self):
        payload = sample()
        payload.update(time_synced=True, timestamp_ms=NOW_MS - 1000)
        with patch("geohazard_platform.telemetry.utc_now", return_value=NOW):
            receipt = ingest_real(self.db, payload)
            self.assertIsNotNone(receipt["alarm_id"])
            before = production_current(self.db)
            older = deepcopy(payload)
            older.update(seq=2, uptime_ms=2000, timestamp_ms=NOW_MS - 20000)
            self.assertFalse(ingest_real(self.db, older, freshness_seconds=10)["is_current"])
            self.assertEqual(production_current(self.db), before)

    def test_out_of_order_native_input_is_stored_without_live_effects(self):
        ingest_real(self.db, sample(seq=5, level="NORMAL", score=10))
        before = production_current(self.db)
        for payload in (sample(seq=1), {**sample(seq=6), "uptime_ms": 1000}):
            receipt = ingest_real(self.db, payload)
            self.assertFalse(receipt["is_current"])
            self.assertIsNone(receipt["alarm_id"])
            self.assertEqual(production_current(self.db), before)
        self.assertEqual(rows(self.db, "alarms"), [])

    def test_scope_switch_is_quarantined_in_both_directions_and_survives_restart(self):
        with TemporaryDirectory() as directory:
            for original_scope, new_scope in (("TEST_ONLY", "OPERATIONAL"), ("OPERATIONAL", "TEST_ONLY")):
                with self.subTest(original_scope=original_scope):
                    db = Database(Path(directory) / f"{original_scope}.sqlite3")
                    self.addCleanup(db.close)
                    payload = sample()
                    original = ingest_real(db, payload, scope=original_scope)
                    before = rows(db, "telemetry")
                    db.close()
                    db.initialize()
                    with self.assertRaises(IngestionError) as failure:
                        ingest_real(db, payload, scope=new_scope)
                    self.assertEqual(failure.exception.status_code, 409)
                    self.assertEqual(rows(db, "telemetry"), before)
                    self.assertEqual(rows(db, "telemetry")[0]["scope"], original_scope)
                    self.assertEqual(len(rows(db, "intake_receipts")), 1)
                    self.assertEqual(rows(db, "quarantine")[0]["scope"], new_scope)
                    duplicate = ingest_real(db, payload, scope=original_scope)
                    self.assertEqual(duplicate["status"], "duplicate")
                    self.assertEqual(duplicate["telemetry_id"], original["telemetry_id"])
                    self.assertEqual(len(rows(db, "alarms")), int(original_scope == "OPERATIONAL"))
                    db.close()

    def test_mock_cannot_claim_existing_operational_device(self):
        ingest_real(self.db, sample(level="NORMAL", score=10))
        before = production_current(self.db)
        with self.assertRaises(IngestionError) as failure:
            ingest_telemetry(self.db, sample(seq=2))
        self.assertEqual(failure.exception.status_code, 409)
        self.assertEqual(production_current(self.db), before)
        self.assertEqual(rows(self.db, "alarms"), [])

    def test_invalid_native_identity_is_quarantined(self):
        for field, value in (("seq", True), ("boot_id", -1), ("device_id", "")):
            with self.subTest(field=field):
                payload = sample()
                payload[field] = value
                with self.assertRaises(IngestionError) as failure:
                    ingest_real(self.db, payload)
                self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(rows(self.db, "telemetry"), [])
        self.assertEqual(rows(self.db, "alarms"), [])

    def test_unknown_scope_is_rejected_without_storage(self):
        for scope in ("DEVICE_INTAKE", "LEGACY_UNKNOWN", "operational", None, []):
            with self.subTest(scope=scope):
                with self.assertRaises(IngestionError) as failure:
                    ingest_real(self.db, sample(), scope=scope)
                self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(rows(self.db, "telemetry"), [])

    def test_old_schema_migration_keeps_alarm_history_unknown_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.executescript("""
                    CREATE TABLE alarms (
                        id TEXT PRIMARY KEY, site_id TEXT NOT NULL, device_id TEXT,
                        source TEXT NOT NULL, level TEXT NOT NULL, score REAL,
                        reason TEXT NOT NULL, source_message_id TEXT,
                        acknowledged INTEGER NOT NULL DEFAULT 0,
                        acknowledged_at TEXT, created_at TEXT NOT NULL
                    );
                    INSERT INTO alarms VALUES
                        ('legacy-real','MOCK-SITE-01','OLD-REAL','REAL','WARNING',70,'old',NULL,1,'then','then'),
                        ('legacy-mock','MOCK-SITE-01','OLD-MOCK','MOCK','WATCH',40,'old',NULL,0,NULL,'then');
                """)
            db = Database(path)
            self.addCleanup(db.close)
            for _ in range(2):
                db.initialize()
                legacy = rows(db, "alarms", "id LIKE 'legacy-%'")
                self.assertEqual([row["scope"] for row in legacy], ["LEGACY_UNKNOWN", "LEGACY_UNKNOWN"])
                self.assertEqual(legacy[0]["acknowledged"], 1)
                self.assertEqual(legacy[0]["acknowledged_at"], "then")
                db.close()
            ingest_real(db, sample())
            self.assertEqual(len(rows(db, "alarms", "scope='OPERATIONAL'")), 1)
            db.close()

    def test_restart_clears_legacy_real_research_current_but_preserves_mock(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "existing.sqlite3")
            self.addCleanup(db.close)
            ingest_real(db, sample(), scope="TEST_ONLY")
            mock = ingest_telemetry(db, sample(device="MOCK-OWN-STATE"))
            with db.connection() as connection:
                connection.execute("UPDATE telemetry SET is_current=1,is_backfill=0 WHERE source='REAL'")
            db.close()
            db.initialize()
            self.assertEqual(rows(db, "telemetry", "source='REAL' AND is_current=1"), [])
            self.assertEqual(rows(db, "telemetry", "source='MOCK' AND is_current=1")[0]["id"], mock["telemetry_id"])
            db.close()

    def test_mqtt_default_scope_is_test_only_for_both_sources(self):
        for source in ("REAL", "MOCK"):
            with self.subTest(source=source):
                item = save_connector(self.db, connector_data(source=source))
                self.assertEqual(item["config"]["scope"], "TEST_ONLY")
                session = _MQTTSession(self.db, item)
                payload = sample(device=source + "-MQTT-DEFAULT")
                session._on_message(None, None, mqtt_message(payload))
                self.assertEqual(session.snapshot()["messages_accepted"], 1)
                self.assertEqual(rows(self.db, "telemetry", f"device_id='{payload['device_id']}'")[0]["scope"], "TEST_ONLY")
        self.assertEqual(rows(self.db, "alarms"), [])
        self.assertEqual(production_current(self.db), [])

    def test_mqtt_explicit_real_operational_can_escalate(self):
        item = save_connector(self.db, connector_data(scope="OPERATIONAL"))
        session = _MQTTSession(self.db, item)
        session._on_message(None, None, mqtt_message(sample()))
        self.assertEqual(session.snapshot()["messages_accepted"], 1)
        self.assertEqual(len(rows(self.db, "alarms", "source='REAL' AND scope='OPERATIONAL'")), 1)
        self.assertEqual(len(production_current(self.db)), 1)

    def test_existing_real_connector_without_scope_defaults_to_test_only(self):
        item = save_connector(self.db, connector_data())
        del item["config"]["scope"]
        with self.db.connection() as connection:
            connection.execute("UPDATE connectors SET config_json=? WHERE id=?", (json.dumps(item["config"]), item["id"]))
        session = _MQTTSession(self.db, get_connector(self.db, item["id"]))
        session._on_message(None, None, mqtt_message(sample()))
        self.assertEqual(rows(self.db, "telemetry")[0]["scope"], "TEST_ONLY")
        self.assertEqual(production_current(self.db), [])
        self.assertEqual(rows(self.db, "alarms"), [])

    def test_mqtt_scope_change_rejects_same_identity_then_accepts_new_identity(self):
        item = save_connector(self.db, connector_data())
        first = _MQTTSession(self.db, item)
        first._on_message(None, None, mqtt_message(sample()))
        changed = save_connector(self.db, {"config": {"scope": "OPERATIONAL"}}, connector_id=item["id"])
        self.assertEqual(changed["version"], 2)
        session = _MQTTSession(self.db, changed)
        session._on_message(None, None, mqtt_message(sample()))
        self.assertEqual(session.snapshot()["messages_rejected"], 1)
        self.assertEqual(session.snapshot()["messages_accepted"], 0)
        self.assertEqual(rows(self.db, "telemetry")[0]["scope"], "TEST_ONLY")
        self.assertEqual(len(rows(self.db, "quarantine")), 1)
        self.assertEqual(rows(self.db, "alarms"), [])
        session._on_message(None, None, mqtt_message(sample(seq=2)))
        self.assertEqual(session.snapshot()["messages_accepted"], 1)
        self.assertEqual(len(rows(self.db, "alarms")), 1)

    def test_invalid_mqtt_scope_and_experimental_promotion_are_rejected(self):
        cases = [connector_data(scope=value) for value in (None, [], "OPERATION", "LEGACY_UNKNOWN")]
        cases.extend((connector_data(source="MOCK", scope="OPERATIONAL"),
                      connector_data(payload_format="tinyquake_v1", scope="OPERATIONAL")))
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(ConnectorError) as failure:
                    save_connector(self.db, data)
                self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(rows(self.db, "connectors"), [])


if __name__ == "__main__":
    unittest.main()
