"""Real localhost MQTT broker → Paho → validator → SQLite integration."""
import asyncio
import copy
import json
from pathlib import Path
import socket
from threading import Thread
import time

import paho.mqtt.client as mqtt
import pytest
from amqtt.broker import Broker

from geohazard_platform.connectors import MQTTManager, save_connector, test_connector
from geohazard_platform.database import Database


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise AssertionError("timed out waiting for MQTT integration condition")


class LocalBroker:
    def __init__(self):
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            self.port = reserve.getsockname()[1]
        self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.broker = None
        asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(timeout=5)

    async def _start(self):
        self.broker = Broker({
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"}},
            "sys_interval": 0,
            "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
        })
        await self.broker.start()

    def stop(self):
        if self.broker is not None:
            asyncio.run_coroutine_threadsafe(self.broker.shutdown(), self.loop).result(timeout=5)
            self.broker = None
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)
        self.loop.close()


@pytest.fixture
def broker():
    broker = LocalBroker()
    try:
        yield broker
    finally:
        if broker.thread.is_alive():
            broker.stop()


def count(db, table):
    with db.connection() as connection:
        return connection.execute("SELECT count(*) FROM " + table).fetchone()[0]


def test_real_mqtt_publish_dedup_quarantine_reload_and_disconnect(tmp_path, broker):
    db = Database(tmp_path / "mqtt.sqlite3")
    db.initialize()
    fixture = Path(__file__).resolve().parents[2] / "edge_intake/tests/fixtures/a_mock/cases/M01_NORMAL.json"
    payload = json.loads(fixture.read_text())["messages"][0]["payload"]
    topic = f"zhifang/v2/{payload['site_id']}/{payload['device_id']}/telemetry"
    item = save_connector(db, {"name": "Real localhost test broker", "kind": "mqtt", "source": "MOCK", "enabled": True, "config": {"host": "127.0.0.1", "port": broker.port, "site_id": payload["site_id"]}})
    manager = MQTTManager(db)
    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pytest-fixture-publisher")
    try:
        manager.start()
        wait_for(lambda: manager.statuses()[0]["connected"])
        assert test_connector(db, item["id"], timeout=2)["success"]
        publisher.connect("127.0.0.1", broker.port)
        publisher.loop_start()
        publisher.publish(topic, json.dumps(payload), qos=0).wait_for_publish(timeout=2)
        wait_for(lambda: count(db, "telemetry") == 1)
        publisher.publish(topic, json.dumps(payload), qos=0).wait_for_publish(timeout=2)
        wait_for(lambda: manager.statuses()[0]["duplicates"] == 1)
        assert count(db, "telemetry") == 1 and count(db, "alarms") == 0
        with db.connection() as connection:
            stored = connection.execute("SELECT payload_json,source,transport FROM telemetry").fetchone()
            assert json.loads(stored["payload_json"])["risk"] == {"sensor_score": None, "level": None, "reason_mask": None}
            assert stored["source"] == "MOCK" and stored["transport"] == "mqtt"
        invalid = copy.deepcopy(payload)
        invalid["seq"] = True
        publisher.publish(topic, json.dumps(invalid), qos=0).wait_for_publish(timeout=2)
        wait_for(lambda: count(db, "quarantine") == 1)
        publisher.publish(topic, '{"seq":1,"seq":2}', qos=0).wait_for_publish(timeout=2)
        wait_for(lambda: count(db, "quarantine") == 2)
        assert manager.statuses()[0]["messages_rejected"] == 2
        save_connector(db, {"enabled": False}, connector_id=item["id"])
        manager.reload()
        assert manager.statuses()[0]["state"] == "disabled"
        payload["seq"] = 2
        payload["uptime_ms"] = 2000
        publisher.publish(topic, json.dumps(payload), qos=0).wait_for_publish(timeout=2)
        time.sleep(0.1)
        assert count(db, "telemetry") == 1
        save_connector(db, {"enabled": True}, connector_id=item["id"])
        manager.reload()
        wait_for(lambda: manager.statuses()[0]["connected"])
        publisher.publish(topic, json.dumps(payload), qos=0).wait_for_publish(timeout=2)
        wait_for(lambda: count(db, "telemetry") == 2)
        broker.stop()
        wait_for(lambda: not manager.statuses()[0]["connected"])
        assert manager.statuses()[0]["state"] == "reconnecting"
        assert not test_connector(db, item["id"], timeout=0.2)["success"]
    finally:
        publisher.disconnect()
        publisher.loop_stop()
        manager.stop()
        db.close()


def test_retained_broker_replay_is_quarantined_on_subscription(tmp_path, broker):
    db = Database(tmp_path / "retained.sqlite3")
    db.initialize()
    fixture = Path(__file__).resolve().parents[2] / "edge_intake/tests/fixtures/a_mock/cases/M01_NORMAL.json"
    payload = json.loads(fixture.read_text())["messages"][0]["payload"]
    payload["risk"].update(sensor_score=90, level="EMERGENCY")
    topic = f"zhifang/v2/{payload['site_id']}/{payload['device_id']}/telemetry"
    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pytest-retained-publisher")
    manager = MQTTManager(db)
    try:
        publisher.connect("127.0.0.1", broker.port)
        publisher.loop_start()
        # Reproduce an old retained broker snapshot delivered on a fresh
        # subscription, which must never become current arrival-only state.
        publisher.publish(topic, json.dumps(payload), qos=1, retain=True).wait_for_publish(timeout=2)
        save_connector(db, {"name": "Retained replay test", "kind": "mqtt", "source": "MOCK", "enabled": True,
                            "config": {"host": "127.0.0.1", "port": broker.port, "site_id": payload["site_id"]}})
        manager.start()
        wait_for(lambda: manager.statuses()[0]["connected"])
        wait_for(lambda: count(db, "quarantine") == 1)
        assert count(db, "telemetry") == count(db, "alarms") == 0
        assert manager.statuses()[0]["messages_rejected"] == 1
        publisher.publish(topic, json.dumps(payload), qos=0, retain=False).wait_for_publish(timeout=2)
        wait_for(lambda: count(db, "telemetry") == 1)
        assert count(db, "alarms") == 1
    finally:
        publisher.publish(topic, b"", qos=0, retain=True).wait_for_publish(timeout=2)
        publisher.disconnect()
        publisher.loop_stop()
        manager.stop()
        db.close()
