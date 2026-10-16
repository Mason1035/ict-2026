"""Persisted connector configuration and a real MQTT subscriber lifecycle.

Connectivity succeeds only after CONNACK and SUBACK. No device-control messages
or invented durable acknowledgements are published by this local intake.
"""
from __future__ import annotations

import json
from pathlib import Path
import ssl
from threading import Event, RLock
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .database import Database, utc_now
from .telemetry import IngestionError, ingest_telemetry, quarantine_message


class ConnectorError(ValueError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = {"message": detail}
        super().__init__(detail)


def _validate(data: dict[str, Any], old: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool, str | None]:
    if not isinstance(data, dict):
        raise ConnectorError(422, "connector must be an object")
    allowed = {"id", "name", "kind", "config", "enabled", "source", "version", "created_at", "updated_at", "has_password"}
    if set(data) - allowed:
        raise ConnectorError(422, "unknown connector fields")
    merged = {**(old or {}), **data}
    name = merged.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ConnectorError(422, "name must contain 1..120 characters")
    kind = merged.get("kind", "mqtt")
    if kind not in {"mqtt", "http_json"}:
        raise ConnectorError(422, "supported connector kinds are mqtt and reserved http_json")
    enabled = merged.get("enabled", False)
    if type(enabled) is not bool:
        raise ConnectorError(422, "enabled must be a boolean")
    source = merged.get("source", "MOCK")
    if source not in {"MOCK", "REAL"}:
        raise ConnectorError(422, "source must be MOCK or REAL")
    supplied = data.get("config", {})
    if not isinstance(supplied, dict):
        raise ConnectorError(422, "config must be an object")
    config = {**((old or {}).get("config", {}) if (old or {}).get("kind", kind) == kind else {}), **supplied}
    password_changed = "password" in supplied
    password = config.pop("password", None)
    if password is not None and (not isinstance(password, str) or len(password) > 4096):
        raise ConnectorError(422, "password must be a string up to 4096 characters or null")
    if kind == "http_json":
        if set(config) - {"url", "timeout_seconds"}:
            raise ConnectorError(422, "reserved http_json config supports url and timeout_seconds only")
        parsed = urlsplit(config.get("url", ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ConnectorError(422, "HTTP connector requires an http(s) URL without embedded credentials")
        if enabled:
            raise ConnectorError(422, "HTTP polling adapter is reserved and cannot be enabled; use the documented test injection API")
        if password_changed:
            raise ConnectorError(422, "reserved HTTP adapter does not accept credentials")
        config = {"url": config["url"], "timeout_seconds": 5}
    else:
        keys = {"host", "port", "site_id", "topic", "client_id", "username", "tls", "ca_cert_path", "qos", "keepalive", "password_configured"}
        if set(config) - keys:
            raise ConnectorError(422, "unsupported MQTT setting; TLS certificate verification cannot be disabled")
        config.pop("password_configured", None)
        host = config.get("host", "")
        if not isinstance(host, str) or not host.strip() or len(host) > 253 or any(c.isspace() for c in host) or any(c in host for c in "/@\x00"):
            raise ConnectorError(422, "MQTT host must be a hostname or IP address without a scheme")
        port = config.get("port", 1883)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ConnectorError(422, "MQTT port must be an integer 1..65535")
        site = config.get("site_id", "")
        if not isinstance(site, str) or not site.strip() or len(site) > 128 or any(c in site for c in "/+#\x00"):
            raise ConnectorError(422, "site_id must be one nonempty MQTT segment")
        topic = config.get("topic", f"zhifang/v2/{site}/+/telemetry")
        parts = topic.split("/") if isinstance(topic, str) else []
        if len(parts) != 5 or parts[:3] != ["zhifang", "v2", site] or parts[4] != "telemetry" or not parts[3] or "#" in topic or ("+" in parts[3] and parts[3] != "+") or "\x00" in topic:
            raise ConnectorError(422, "MQTT whitelist must be zhifang/v2/{site_id}/+/telemetry or one explicit device topic")
        tls = config.get("tls", False)
        if type(tls) is not bool:
            raise ConnectorError(422, "tls must be a boolean; certificate verification is always required")
        ca_path = config.get("ca_cert_path")
        if ca_path is not None:
            if not tls or not isinstance(ca_path, str) or not Path(ca_path).is_absolute() or not Path(ca_path).is_file():
                raise ConnectorError(422, "ca_cert_path requires TLS and an existing absolute local CA certificate path")
            if Path(ca_path).suffix.lower() not in {".pem", ".crt"} or Path(ca_path).stat().st_size > 1048576:
                raise ConnectorError(422, "CA certificate must be a PEM/CRT file up to 1 MiB")
        username = config.get("username")
        if username is not None and (not isinstance(username, str) or len(username) > 256 or "\x00" in username):
            raise ConnectorError(422, "username must be a string up to 256 characters or null")
        client_id = config.get("client_id", "")
        if not isinstance(client_id, str) or len(client_id) > 128 or "\x00" in client_id:
            raise ConnectorError(422, "client_id must be a string up to 128 characters")
        qos = config.get("qos", 0)
        if type(qos) is not int or qos not in {0, 1, 2}:
            raise ConnectorError(422, "qos must be 0, 1, or 2")
        keepalive = config.get("keepalive", 30)
        if type(keepalive) is not int or not 5 <= keepalive <= 300:
            raise ConnectorError(422, "keepalive must be an integer 5..300 seconds")
        config = {"host": host, "port": port, "site_id": site, "topic": topic, "client_id": client_id, "username": username, "tls": tls, "ca_cert_path": ca_path, "qos": qos, "keepalive": keepalive}
    return {"name": name.strip(), "kind": kind, "enabled": enabled, "source": source, "config": config}, password_changed, password


def _public(row: Any, has_password: bool = False) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "config": json.loads(row["config_json"]), "enabled": bool(row["enabled"]), "source": row["source"], "version": row["version"], "created_at": row["created_at"], "updated_at": row["updated_at"], "has_password": has_password}


def list_connectors(db: Database) -> list[dict[str, Any]]:
    with db.connection() as connection:
        rows = connection.execute("SELECT c.*, (s.password IS NOT NULL AND s.password<>'') AS has_password FROM connectors c LEFT JOIN connector_secrets s ON s.connector_id=c.id ORDER BY c.created_at,c.id").fetchall()
        return [_public(row, bool(row["has_password"])) for row in rows]


def get_connector(db: Database, connector_id: str) -> dict[str, Any]:
    found = next((row for row in list_connectors(db) if row["id"] == connector_id), None)
    if found is None:
        raise ConnectorError(404, "connector not found")
    return found


def save_connector(db: Database, data: dict[str, Any], connector_id: str | None = None) -> dict[str, Any]:
    old = get_connector(db, connector_id) if connector_id else None
    item, password_changed, password = _validate(data, old)
    identifier = connector_id or str(uuid4())
    now = utc_now()
    with db.connection() as connection:
        connection.execute("INSERT INTO connectors(id,name,kind,config_json,enabled,source,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,config_json=excluded.config_json,enabled=excluded.enabled,source=excluded.source,version=excluded.version,updated_at=excluded.updated_at", (identifier, item["name"], item["kind"], json.dumps(item["config"]), int(item["enabled"]), item["source"], (old["version"] + 1) if old else 1, old["created_at"] if old else now, now))
        if password_changed:
            connection.execute("INSERT INTO connector_secrets(connector_id,password) VALUES(?,?) ON CONFLICT(connector_id) DO UPDATE SET password=excluded.password", (identifier, password or None))
        if item["kind"] != "mqtt":
            connection.execute("DELETE FROM connector_secrets WHERE connector_id=?", (identifier,))
    return get_connector(db, identifier)


def delete_connector(db: Database, connector_id: str) -> None:
    with db.connection() as connection:
        cursor = connection.execute("DELETE FROM connectors WHERE id=?", (connector_id,))
        if cursor.rowcount == 0:
            raise ConnectorError(404, "connector not found")


def _password(db: Database, connector_id: str) -> str | None:
    with db.connection() as connection:
        row = connection.execute("SELECT password FROM connector_secrets WHERE connector_id=?", (connector_id,)).fetchone()
        return row["password"] if row else None


def _code(value: Any) -> int:
    return int(getattr(value, "value", value))


class _MQTTSession:
    def __init__(self, db: Database, item: dict[str, Any], *, probe: bool = False):
        self.db, self.item, self.probe = db, item, probe
        self.ready = Event()
        self.stopped = False
        self.state: dict[str, Any] = {"connector_id": item["id"], "state": "connecting", "connected": False, "messages_received": 0, "messages_accepted": 0, "messages_rejected": 0, "duplicates": 0, "last_message_at": None, "last_error": None, "updated_at": utc_now()}
        self._lock = RLock()
        self.client: Any = None

    def _update(self, **values: Any) -> None:
        with self._lock:
            self.state.update(values, updated_at=utc_now())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.state)

    def start(self) -> None:
        import paho.mqtt.client as mqtt
        config = self.item["config"]
        # A probe must never evict the persistent subscriber's configured ID.
        client_id = ("probe-" + uuid4().hex[:16]) if self.probe else (config["client_id"] or "zhifang-" + self.item["id"][:16])
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
        self.client.max_queued_messages_set(1000)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        if config.get("username") is not None:
            self.client.username_pw_set(config["username"], _password(self.db, self.item["id"]))
        if config["tls"]:
            self.client.tls_set(ca_certs=config.get("ca_cert_path"), cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_disconnect = self._on_disconnect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_message = self._on_message
        self.client.connect_async(config["host"], config["port"], config["keepalive"])
        self.client.loop_start()

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if _code(reason_code) != 0:
            self._update(state="error", connected=False, last_error="MQTT CONNACK rejected (code %s)" % _code(reason_code))
            self.ready.set()
            return
        self._update(state="subscribing", connected=False, last_error=None)
        result, _ = client.subscribe(self.item["config"]["topic"], qos=self.item["config"]["qos"])
        if result != 0:
            self._update(state="error", connected=False, last_error="MQTT subscription request failed")
            self.ready.set()

    def _on_subscribe(self, client: Any, userdata: Any, mid: int, reason_codes: Any, properties: Any) -> None:
        if not reason_codes or any(_code(code) >= 128 for code in reason_codes):
            self._update(state="error", connected=False, last_error="MQTT SUBACK rejected the telemetry whitelist")
        else:
            self._update(state="connected", connected=True, last_error=None)
        self.ready.set()

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if self.stopped:
            self._update(state="stopped", connected=False)
        else:
            self._update(state="reconnecting", connected=False, last_error="MQTT connection lost; retrying with backoff")
        self.ready.set()

    def _on_connect_fail(self, client: Any, userdata: Any) -> None:
        self._update(state="reconnecting", connected=False, last_error="MQTT TCP/TLS connection failed; retrying with backoff")
        self.ready.set()

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        if self.probe or self.stopped:
            return
        with self._lock:
            self.state["messages_received"] += 1
        self._update(last_message_at=utc_now())
        source = self.item["source"]
        scope = "TEST_ONLY" if source == "MOCK" else "OPERATIONAL"
        metadata = {"source": source, "scope": scope, "transport": "mqtt", "connector_id": self.item["id"], "topic": message.topic}
        try:
            if len(message.payload) > 262144:
                raise ValueError("MQTT message exceeds 256 KiB limit")
            text = message.payload.decode("utf-8", errors="strict")
            def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("JSON object contains duplicate keys")
                    result[key] = value
                return result
            payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
            whitelist = self.item["config"]["topic"].split("/")
            received_parts = message.topic.split("/")
            if len(received_parts) != len(whitelist) or any(expected != "+" and actual != expected for expected, actual in zip(whitelist, received_parts)):
                raise ValueError("message is outside configured telemetry whitelist")
            receipt = ingest_telemetry(self.db, payload, **metadata)
            with self._lock:
                self.state["messages_accepted"] += 1
                self.state["duplicates"] += int(receipt["status"] == "duplicate")
            self._update(last_error=None)
        except IngestionError as exc:
            with self._lock:
                self.state["messages_rejected"] += 1
            self._update(last_error=exc.detail["message"])
        except (ValueError, UnicodeError, IndexError) as exc:
            quarantine_message(self.db, message.payload, **metadata, reason=str(exc))
            with self._lock:
                self.state["messages_rejected"] += 1
            self._update(last_error="MQTT payload rejected; see quarantine")
        except Exception:
            # Do not propagate into Paho's network thread, nor include payloads,
            # connection strings or credentials in public errors.
            with self._lock:
                self.state["messages_rejected"] += 1
            self._update(last_error="MQTT intake storage/runtime failure; no durable receipt issued")

    def stop(self) -> None:
        self.stopped = True
        if self.client is not None:
            self.client.disconnect()
            self.client.loop_stop()
        self._update(state="stopped", connected=False)


def test_connector(db: Database, connector_id: str, timeout: float = 5.0) -> dict[str, Any]:
    item = get_connector(db, connector_id)
    if item["kind"] != "mqtt":
        return {"success": False, "state": "not_implemented", "message": "HTTP polling adapter is reserved; no connection claimed"}
    probe = _MQTTSession(db, item, probe=True)
    try:
        probe.start()
        probe.ready.wait(min(max(float(timeout), 0.1), 10))
        status = probe.snapshot()
        return {"success": status["connected"], "state": status["state"] if status["connected"] else "failed", "message": "MQTT CONNACK and SUBACK received" if status["connected"] else status["last_error"] or "MQTT handshake/subscription timed out", "checked_at": utc_now()}
    except Exception:
        return {"success": False, "state": "failed", "message": "MQTT connection test failed; verify address, authentication, and TLS settings", "checked_at": utc_now()}
    finally:
        probe.stop()

# Prevent pytest from collecting this application helper imported by tests.
test_connector.__test__ = False


class MQTTManager:
    def __init__(self, db: Database):
        self.db = db
        self._sessions: dict[str, _MQTTSession] = {}
        self._lock = RLock()
        self._running = False

    def start(self) -> None:
        self._running = True
        self.reload()

    def reload(self) -> None:
        with self._lock:
            items = {item["id"]: item for item in list_connectors(self.db)}
            for identifier, session in list(self._sessions.items()):
                item = items.get(identifier)
                if item is None or not item["enabled"] or item["kind"] != "mqtt" or item["version"] != session.item["version"]:
                    session.stop()
                    del self._sessions[identifier]
            if not self._running:
                return
            for identifier, item in items.items():
                if item["enabled"] and item["kind"] == "mqtt" and identifier not in self._sessions:
                    session = _MQTTSession(self.db, item)
                    self._sessions[identifier] = session
                    try:
                        session.start()
                    except Exception:
                        session._update(state="error", connected=False, last_error="MQTT startup failed; verify authentication/TLS/runtime configuration")

    def statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            statuses = []
            for item in list_connectors(self.db):
                session = self._sessions.get(item["id"])
                if session:
                    statuses.append(session.snapshot())
                else:
                    statuses.append({"connector_id": item["id"], "state": "disabled" if not item["enabled"] else "not_implemented" if item["kind"] != "mqtt" else "stopped", "connected": False, "last_error": None})
            return statuses

    def stop(self) -> None:
        with self._lock:
            self._running = False
            for session in self._sessions.values():
                session.stop()
            self._sessions.clear()
