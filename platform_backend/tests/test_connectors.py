import json
import socket

import pytest

from geohazard_platform.connectors import ConnectorError, MQTTManager, delete_connector, get_connector, list_connectors, save_connector, test_connector
from geohazard_platform.database import Database


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    yield db
    db.close()


def config(**values):
    return {"name": "Local MQTT", "kind": "mqtt", "enabled": False, "source": "MOCK", "config": {"host": "127.0.0.1", "port": 1883, "site_id": "SITE-TEST", **values}}


def test_secret_redaction_preservation_clear_and_delete(db):
    public = save_connector(db, config(password="never-return-this", username="test"))
    identifier = public["id"]
    assert public["has_password"]
    assert "never-return-this" not in json.dumps(public)
    assert "password" not in public["config"]
    updated = save_connector(db, {"name": "Updated", "config": {"port": 1884}}, connector_id=identifier)
    assert updated["has_password"] and updated["version"] == 2
    assert updated["config"]["username"] == "test"
    with db.connection() as connection:
        assert connection.execute("SELECT password FROM connector_secrets WHERE connector_id=?", (identifier,)).fetchone()[0] == "never-return-this"
    assert not save_connector(db, {"config": {"password": None}}, connector_id=identifier)["has_password"]
    assert len(list_connectors(db)) == 1
    delete_connector(db, identifier)
    assert list_connectors(db) == []
    with db.connection() as connection:
        assert connection.execute("SELECT count(*) FROM connector_secrets").fetchone()[0] == 0


@pytest.mark.parametrize("changes", [
    {"port": True}, {"port": 0}, {"host": "mqtt://localhost"},
    {"site_id": "+"}, {"topic": "#"}, {"topic": "zhifang/v2/other/+/telemetry"},
    {"topic": "zhifang/v2/SITE-TEST/+/command"}, {"tls": "false"},
    {"tls_insecure": True}, {"qos": 3}, {"password": ["secret"]},
])
def test_reject_unsafe_or_wrong_configuration(db, changes):
    with pytest.raises(ConnectorError) as failure:
        save_connector(db, config(**changes))
    assert failure.value.status_code == 422
    assert list_connectors(db) == []


def test_disabled_manager_and_reserved_adapter_report_honestly(db):
    mqtt = save_connector(db, config())
    manager = MQTTManager(db)
    manager.start()
    status = manager.statuses()[0]
    assert status["state"] == "disabled" and not status["connected"]
    http = save_connector(db, {"name": "Future HTTP", "kind": "http_json", "config": {"url": "https://example.invalid/data"}})
    assert test_connector(db, http["id"])["state"] == "not_implemented"
    with pytest.raises(ConnectorError):
        save_connector(db, {"enabled": True}, connector_id=http["id"])
    manager.stop()


def test_tcp_listener_without_mqtt_handshake_is_not_success(db):
    # A TCP accept alone must never be displayed as a successful MQTT test.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        item = save_connector(db, config(port=listener.getsockname()[1], password="must-stay-private"))
        result = test_connector(db, item["id"], timeout=0.15)
    assert result["success"] is False
    assert "must-stay-private" not in json.dumps(result)
    assert get_connector(db, item["id"])["has_password"]


def test_missing_connector(db):
    with pytest.raises(ConnectorError) as failure:
        get_connector(db, "unknown")
    assert failure.value.status_code == 404


@pytest.mark.parametrize("url", [123, True, [], {}, None, "http://[broken", "http://host:99999"])
def test_reserved_http_url_rejects_bad_types_and_parsing_errors(db, url):
    with pytest.raises(ConnectorError) as failure:
        save_connector(db, {"name": "Invalid URL", "kind": "http_json", "config": {"url": url}})
    assert failure.value.status_code == 422
    assert list_connectors(db) == []


def test_connector_invalid_unicode_is_rejected_before_sqlite(db):
    with pytest.raises(ConnectorError) as failure:
        save_connector(db, config(password="\ud800"))
    assert failure.value.status_code == 422
    assert list_connectors(db) == []


def mqtt_callback_session(db):
    from geohazard_platform.connectors import _MQTTSession
    return _MQTTSession(db, {"id": "callback-test", "source": "MOCK", "config": {"topic": "zhifang/v2/MOCK-SITE-01/+/telemetry"}})


def mqtt_fixture_message(*, retain=False):
    from pathlib import Path
    from types import SimpleNamespace
    fixture = Path(__file__).resolve().parents[2] / "edge_intake/tests/fixtures/a_mock/cases/M01_NORMAL.json"
    payload = json.loads(fixture.read_text())["messages"][0]["payload"]
    payload["risk"].update(sensor_score=90, level="EMERGENCY")
    return SimpleNamespace(topic=f"zhifang/v2/{payload['site_id']}/{payload['device_id']}/telemetry", payload=json.dumps(payload).encode(), retain=retain)


def test_retained_telemetry_is_quarantined_without_current_state_or_alarm(db):
    session = mqtt_callback_session(db)
    session._on_message(None, None, mqtt_fixture_message(retain=True))
    with db.connection() as connection:
        assert connection.execute("SELECT count(*) FROM telemetry").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM alarms").fetchone()[0] == 0
        reason = connection.execute("SELECT reason FROM quarantine").fetchone()[0]
        assert "Retained telemetry" in reason
    assert session.snapshot()["messages_rejected"] == 1
    assert session.snapshot()["messages_accepted"] == 0


def test_failed_quarantine_does_not_escape_callback_and_valid_intake_recovers(db, monkeypatch):
    from types import SimpleNamespace
    import geohazard_platform.connectors as connectors
    session = mqtt_callback_session(db)
    # Broker connectivity and durable intake health are separate facts.
    session._update(state="connected", connected=True)
    original = connectors.quarantine_message

    def fail(*args, **kwargs):
        raise OSError("private-disk-error")

    monkeypatch.setattr(connectors, "quarantine_message", fail)
    session._on_message(None, None, SimpleNamespace(topic="zhifang/v2/MOCK-SITE-01/NODE-01/telemetry", payload=b"not json", retain=False))
    failed = session.snapshot()
    assert failed["connected"] and failed["state"] == "storage_error"
    assert not failed["intake_healthy"]
    assert failed["messages_accepted"] == 0 and failed["messages_rejected"] == 1
    assert failed["last_durable_at"] is None and "private-disk-error" not in failed["last_error"]
    monkeypatch.setattr(connectors, "quarantine_message", original)
    session._on_message(None, None, mqtt_fixture_message())
    healthy = session.snapshot()
    assert healthy["state"] == "connected" and healthy["intake_healthy"]
    assert healthy["last_durable_at"] and healthy["messages_accepted"] == 1
