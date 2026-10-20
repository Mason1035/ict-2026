import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from geohazard_platform.database import Database
from geohazard_platform.main import create_app
from geohazard_platform.settings import Settings
from geohazard_platform.connectors import save_connector, _MQTTSession, ConnectorError
from geohazard_platform.telemetry import IngestionError
from geohazard_platform import tinyquake


def payload(**changes):
    value={"schema":tinyquake.SCHEMA,"site_id":"TQ-LAB","device_id":"MOCK-TQ-01","sensor_id":"reference",
           "boot_id":1,"seq":1,"model_sha256":tinyquake.MODEL_SHA256,"input_source":"REFERENCE",
           "sample_rate_hz":40,"sample_count":80,"probabilities":[.99934906,.000650934,.000000006],
           "inference_us":12000,"quality_valid":True,"quality_reason":"reference_vector","reference_index":3,
           "window_start_uptime_ms":None,"window_end_uptime_ms":None,"frame_id":None,
           "calibration_version":None,"preprocessing_id":"tinyquake.reference.preprocessed.v1"}
    return {**value,**changes}


@pytest.fixture
def db():
    db=Database(":memory:"); db.initialize()
    yield db
    db.close()


def config(**changes):
    return {"name":"TQ MQTT","kind":"mqtt","enabled":False,"source":"MOCK",
            "config":{"host":"127.0.0.1","port":1883,"site_id":"TQ-LAB","payload_format":"tinyquake_v1",**changes}}


def test_mqtt_routes_reference_to_sidecar_without_risk_changes(db):
    item=save_connector(db,config())
    assert item["config"]["topic"]=="zhifang/experimental/tinyquake/v1/TQ-LAB/+/+/result"
    session=_MQTTSession(db,item)
    msg=SimpleNamespace(topic="zhifang/experimental/tinyquake/v1/TQ-LAB/MOCK-TQ-01/reference/result",payload=json.dumps(payload()).encode(),retain=False)
    session._on_message(None,None,msg)
    session._on_message(None,None,msg)
    assert session.snapshot()["messages_accepted"]==2
    assert session.snapshot()["duplicates"]==1
    rows=tinyquake.listing(db)["items"]
    assert len(rows)==1 and rows[0]["prediction"]=="P-wave"
    assert rows[0]["scope"]=="TEST_ONLY" and rows[0]["risk_eligible"] is False
    with db.connection() as c:
        for table in ("telemetry","alarms"):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]==0


@pytest.mark.parametrize("changes",[
    {"probabilities":[True,0,0]}, {"probabilities":[float("nan"),0,0]},
    {"probabilities":[.1,.1,.1]}, {"model_sha256":"a"*64}, {"sample_rate_hz":100},
    {"sample_count":160}, {"input_source":[]}, {"quality_valid":False}, {"reference_index":99},
    {"window_start_uptime_ms":1000}, {"device_id":"bad/device"}, {"seq":True},
])
def test_bad_results_rejected(db,changes):
    with pytest.raises(IngestionError): tinyquake.ingest(db,payload(**changes),source="MOCK")
    assert tinyquake.listing(db)["items"]==[]


def test_reference_cannot_be_labeled_real_and_mismatch_is_quarantined(db):
    item=save_connector(db,{**config(),"source":"REAL"})
    session=_MQTTSession(db,item)
    msg=SimpleNamespace(topic="zhifang/experimental/tinyquake/v1/TQ-LAB/MOCK-TQ-01/reference/result",payload=json.dumps(payload()).encode(),retain=False)
    session._on_message(None,None,msg)
    assert session.snapshot()["messages_rejected"]==1
    assert not tinyquake.listing(db)["items"]
    with db.connection() as c: assert c.execute("SELECT count(*) FROM quarantine").fetchone()[0]==1


def test_sensor_quality_failure_stays_unknown(db):
    p=payload(input_source="SENSOR",sensor_id="top",reference_index=None,window_start_uptime_ms=1000,
              window_end_uptime_ms=2975,quality_valid=False,quality_reason="missing_samples",probabilities=None)
    tinyquake.ingest(db,p,source="REAL")
    row=tinyquake.listing(db)["items"][0]
    assert row["prediction"] is None and row["risk_eligible"] is False
    assert row["payload"]["calibration_version"] is None


def test_conflict_and_sensor_topic_identity(db):
    tinyquake.ingest(db,payload(),source="MOCK")
    with pytest.raises(IngestionError) as conflict:
        tinyquake.ingest(db,payload(probabilities=[.2,.7,.1]),source="MOCK")
    assert conflict.value.status_code==409
    with pytest.raises(IngestionError):
        tinyquake.ingest(db,payload(seq=2),source="MOCK",topic="zhifang/experimental/tinyquake/v1/TQ-LAB/OTHER/reference/result")


def test_pagination_filters_and_staleness(db):
    for seq in range(7): tinyquake.ingest(db,payload(seq=seq),source="MOCK")
    tinyquake.ingest(db,payload(device_id="MOCK-OTHER"),source="MOCK")
    first=tinyquake.listing(db,device_id="MOCK-TQ-01",limit=3)
    second=tinyquake.listing(db,device_id="MOCK-TQ-01",limit=3,cursor=first["next_cursor"])
    third=tinyquake.listing(db,device_id="MOCK-TQ-01",limit=3,cursor=second["next_cursor"])
    assert len({r["id"] for page in (first,second,third) for r in page["items"]})==7
    assert third["next_cursor"] is None
    with pytest.raises(IngestionError): tinyquake.listing(db,device_id="MOCK-OTHER",cursor=first["next_cursor"])
    with db.connection() as c: c.execute("UPDATE tinyquake_results SET received_at='2020-01-01T00:00:00.000Z'")
    assert all(row["stale"] for row in tinyquake.streams(db)["items"])


def test_config_separates_frozen_telemetry_topic(db):
    with pytest.raises(ConnectorError): save_connector(db,config(payload_format=[]))
    with pytest.raises(ConnectorError): save_connector(db,config(topic="zhifang/v2/TQ-LAB/+/telemetry"))
    with pytest.raises(ConnectorError): save_connector(db,config(topic="zhifang/experimental/tinyquake/v1/OTHER/+/+/result"))
    item=save_connector(db,{"name":"normal","kind":"mqtt","config":{"host":"localhost","site_id":"SITE"}})
    assert item["config"]["payload_format"]=="telemetry_v2"


def test_api_auth_persistence_and_test_ingress_restriction(tmp_path):
    settings=Settings(data_dir=tmp_path,api_token="test-secret",demo_enabled=True)
    with TestClient(create_app(settings),base_url="http://127.0.0.1",client=("127.0.0.1",1234)) as client:
        assert client.get("/api/v1/tinyquake/results").status_code==401
        client.headers["Authorization"]="Bearer test-secret"
        assert client.post("/api/v1/tinyquake/test",json={"payload":payload()}).status_code==201
        assert client.get("/api/v1/tinyquake/streams").json()["items"][0]["device_id"]=="MOCK-TQ-01"
        assert client.post("/api/v1/tinyquake/test",json={"payload":payload(device_id="ESP32-TQ-01")}).status_code==422
    with TestClient(create_app(Settings(data_dir=tmp_path,api_token="test-secret",demo_enabled=False)),base_url="http://127.0.0.1") as client:
        client.headers["Authorization"]="Bearer test-secret"
        assert len(client.get("/api/v1/tinyquake/results").json()["items"])==1
        assert client.post("/api/v1/tinyquake/test",json={"payload":payload()}).status_code==403


def test_actual_broker_reference_round_trip(tmp_path):
    from test_mqtt_integration import LocalBroker, wait_for, count
    from geohazard_platform.connectors import MQTTManager
    import paho.mqtt.client as mqtt
    broker=LocalBroker()
    db=Database(tmp_path/"tinyquake.sqlite3"); db.initialize()
    manager=MQTTManager(db)
    publisher=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        item=config(port=broker.port); item["enabled"]=True
        save_connector(db,item); manager.start()
        wait_for(lambda: manager.statuses()[0]["connected"])
        publisher.connect("127.0.0.1",broker.port); publisher.loop_start()
        topic="zhifang/experimental/tinyquake/v1/TQ-LAB/MOCK-TQ-01/reference/result"
        publisher.publish(topic,json.dumps(payload()),qos=0,retain=False).wait_for_publish(timeout=2)
        wait_for(lambda: count(db,"tinyquake_results")==1)
        assert tinyquake.listing(db)["items"][0]["payload"]["probabilities"][0]>.99
        publisher.publish(topic,json.dumps(payload(seq=2)),qos=0,retain=False).wait_for_publish(timeout=2)
        wait_for(lambda: count(db,"tinyquake_results")==2)
        assert count(db,"telemetry")==0 and count(db,"alarms")==0
    finally:
        publisher.disconnect(); publisher.loop_stop(); manager.stop(); db.close(); broker.stop()


def test_usb_bridge_preserves_result_and_never_calls_reference_real():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[2]/"scripts/tinyquake_usb_bridge.py"
    spec=importlib.util.spec_from_file_location("tinyquake_usb_bridge",path)
    bridge=importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge)
    value=payload()
    raw=json.dumps(value).encode()
    parsed,topic,forwarded=bridge.result_from_line(b"TINYQUAKE_RESULT "+raw+b"\n","MOCK")
    assert parsed==value and forwarded==raw
    assert topic.endswith("/TQ-LAB/MOCK-TQ-01/reference/result")
    assert bridge.result_from_line(b"I (100) normal boot log\n","MOCK") is None
    with pytest.raises(ValueError): bridge.result_from_line(b"TINYQUAKE_RESULT "+raw,"REAL")
    with pytest.raises(ValueError): bridge.result_from_line(b"TINYQUAKE_RESULT []","MOCK")


def test_usb_bridge_waits_for_real_subscription_before_forwarding(monkeypatch):
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[2]/"scripts/tinyquake_usb_bridge.py"
    spec=importlib.util.spec_from_file_location("tq_bridge",path)
    bridge=importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge)
    calls=[]
    def request(base,path,body=None,method="GET"):
        calls.append((path,method))
        if method=="POST": return {"id":"created"}
        if len(calls)==1: return {"items":[]}
        return {"items":[{"id":"created","status":{"connected":True}}]}
    monkeypatch.setattr(bridge,"platform_request",request)
    bridge.configure("http://127.0.0.1:8000/api/v1","TQ-LAB","MOCK",18884)
    assert calls==[("/connectors","GET"),("/connectors","POST"),("/connectors","GET")]
