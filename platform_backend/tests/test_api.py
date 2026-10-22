"""End-to-end local HTTP contracts, using a fresh durable store per test."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import sys

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from geohazard_platform.demo import DEVICE, SITE, SCENARIOS, fixture_payload
from geohazard_platform.main import create_app
from geohazard_platform.settings import Settings
from geohazard_platform.telemetry import ingest_telemetry


API = "/api/v1"


@contextmanager
def opened(data_dir, *, demo=True, token="", remote=False):
    settings = Settings(data_dir=data_dir, demo_enabled=demo, demo_interval=100,
                        api_token=token)
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1",
                    client=("192.0.2.15" if remote else "127.0.0.1", 50000)) as client:
        yield client, app


def payload(device="MOCK-API-01", *, seq=1, score=None, level=None):
    result = fixture_payload({"sensors": dict(SCENARIOS["A"]), "boot_id": 1,
                              "seq": seq, "elapsed_seconds": seq})
    result["device_id"] = device
    result["risk"].update(sensor_score=score, level=level)
    return result


def inject(client, data, **context):
    return client.post(API + "/ingest/test", json={"payload": data, "context": context})


def png(changed=False):
    rng = np.random.default_rng(23)
    pixels = rng.integers(30, 220, size=(96, 128, 3), dtype=np.uint8)
    if changed:
        pixels[25:60, 40:90] = (240, 80, 60)
    output = io.BytesIO()
    Image.fromarray(pixels).save(output, format="PNG")
    return output.getvalue()


def upload_image(client, changed=False, **metadata):
    data = {"site_id": SITE, "camera_id": "API-CAMERA", "source": "MOCK", "scope": "TEST_ONLY", **metadata}
    response = client.post(API + "/evidence", data=data,
                           files={"file": ("../../frame.png", png(changed), "image/png")})
    assert response.status_code == 201, response.text
    return response.json()


def test_backend_demo_scores_history_and_durable_restart(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "acl", None)
    with opened(tmp_path) as (client, _):
        health = client.get(API + "/health").json()
        assert health["storage"]["durable"]
        assert not health["storage"]["node_cleanup_authorized"]
        assert health["auth_mode"] == "local_loopback"
        assert health["capabilities"]["atlas_acl"] == "not_connected"
        inference_status = client.get(API + "/inference/status").json()
        assert inference_status["state"] == "not_connected" and inference_status["reason"]
        for scenario, expected in zip("ABCD", (18, 46, 72, 91)):
            response = client.post(API + "/demo/scenario", json={"scenario": scenario})
            assert response.status_code == 200
            dashboard = client.get(API + "/dashboard").json()
            assert dashboard["latest"]["risk"]["final_score"] == pytest.approx(expected)
            assert dashboard["latest"]["risk"]["vision_score"] is None
            assert dashboard["scope"] == "TEST_ONLY" and dashboard["source"] == "MOCK"
        assert client.post(API + "/demo/control", json={"running": False}).json()["running"] is False
        stepped = client.post(API + "/demo/step").json()
        assert stepped["elapsed_seconds"] == 1
        rows = client.get(API + f"/devices/{DEVICE}/telemetry").json()["items"]
        last_id, count = rows[0]["id"], len(rows)
        assert count >= 6
        assert rows[0]["payload"]["timestamp_ms"] is None
        assert rows[0]["freshness_basis"] == "arrival_only"
    with opened(tmp_path) as (client, _):
        dashboard = client.get(API + "/dashboard").json()
        assert dashboard["latest"]["id"] == last_id
        assert dashboard["stats"]["telemetry_count"] == count
        assert dashboard["demo"]["scenario"] == "D"
        assert dashboard["demo"]["running"] is False


def test_reset_only_clears_designated_mock_device_preserves_operational_data(tmp_path):
    with opened(tmp_path) as (client, app):
        ingest_telemetry(app.state.db, payload("REAL-NODE-01", score=85, level="EMERGENCY"),
                         source="REAL", scope="DEVICE_INTAKE", transport="mqtt")
        assert inject(client, payload("MOCK-OTHER", score=40, level="WATCH")).status_code == 201
        client.post(API + "/demo/scenario", json={"scenario": "D"})
        reset = client.post(API + "/demo/reset")
        assert reset.status_code == 200 and reset.json()["scenario"] == "A"
        assert len(client.get(API + f"/devices/{DEVICE}/telemetry").json()["items"]) == 1
        real = client.get(API + "/devices/REAL-NODE-01/telemetry", params={"source": "REAL"}).json()["items"]
        assert len(real) == 1 and real[0]["risk"]["final_score"] == 85
        assert len(client.get(API + "/alarms", params={"source": "REAL"}).json()["items"]) == 1
        assert len(client.get(API + "/devices/MOCK-OTHER/telemetry").json()["items"]) == 1


def test_test_ingress_durable_deduplication_identity_restriction_and_conflict(tmp_path):
    with opened(tmp_path) as (client, _):
        original = payload()
        first = inject(client, original).json()
        repeated = inject(client, deepcopy(original)).json()
        assert first["status"] == "accepted" and repeated["status"] == "duplicate"
        assert first["telemetry_id"] == repeated["telemetry_id"]
        assert first["receipt_id"] != repeated["receipt_id"]
        assert first["durable"] and not first["node_cleanup_authorized"]
        changed = deepcopy(original)
        changed["soil"]["avg_pct"] = 43.0
        assert inject(client, changed).status_code == 409
        assert inject(client, payload("NODE-OPERATIONS")).status_code == 422
        assert len(client.get(API + "/devices/MOCK-API-01/telemetry").json()["items"]) == 1


def test_null_fields_remain_unknown_and_provenance_cannot_be_smuggled_in(tmp_path):
    with opened(tmp_path) as (client, _):
        original = payload()
        original["soil"] = {key: None for key in original["soil"]}
        for imu in original["imu"]:
            imu.update({key: None for key in imu if key not in {"id", "valid"}})
            imu["valid"] = False
        response = inject(client, original, source="REAL", scope="OPERATIONAL")
        assert response.status_code == 201
        assert response.json()["source"] == "MOCK" and response.json()["scope"] == "TEST_ONLY"
        dashboard = client.get(API + "/dashboard", params={"device_id": "MOCK-API-01"}).json()
        current = dashboard["latest"]
        assert current["payload"] == original
        assert all(value is None for value in current["sensors"].values())
        assert current["risk"]["final_score"] is None and current["risk"]["level"] == "unknown"
        forged = payload("MOCK-FORGED")
        forged["source"] = "REAL"
        assert inject(client, forged).status_code == 422
        assert client.get(API + "/quarantine").json()["items"]
        assert all("raw_payload" not in item for item in client.get(API + "/quarantine").json()["items"])


def test_ack_is_idempotent_and_dropout_does_not_erase_emergency_alarm(tmp_path):
    with opened(tmp_path) as (client, _):
        accepted = inject(client, payload(score=91, level="EMERGENCY")).json()
        alarm_id = accepted["alarm_id"]
        assert alarm_id
        first = client.post(API + f"/alarms/{alarm_id}/ack", json={"note": "人工已读"})
        second = client.post(API + f"/alarms/{alarm_id}/ack", json={"note": "重复确认"})
        assert first.status_code == second.status_code == 200
        assert first.json()["acknowledged_at"] == second.json()["acknowledged_at"]
        assert first.json()["level"] == "EMERGENCY" and first.json()["score"] == 91
        assert inject(client, payload(seq=2)).status_code == 201
        assert inject(client, payload(seq=3, score=92, level="EMERGENCY")).status_code == 201
        alarms = client.get(API + "/alarms", params={"device_id": "MOCK-API-01"}).json()["items"]
        assert len(alarms) == 1 and alarms[0]["level"] == "EMERGENCY" and alarms[0]["acknowledged"] == 1
        events = client.get(API + "/events", params={"device_id": "MOCK-API-01"}).json()["items"]
        assert sum(item["kind"] == "alarm_acknowledged" for item in events) == 1
        assert client.post(API + "/alarms/missing/ack", json={}).status_code == 404


def test_rest_source_isolation_and_unknown_device_has_no_manufactured_zero(tmp_path):
    with opened(tmp_path) as (client, app):
        assert inject(client, payload(score=72, level="WARNING")).status_code == 201
        ingest_telemetry(app.state.db, payload("REAL-API-01", score=91, level="EMERGENCY"),
                         source="REAL", scope="DEVICE_INTAKE", transport="mqtt")
        real = client.get(API + "/dashboard", params={"device_id": "REAL-API-01", "source": "REAL"}).json()
        assert real["latest"]["source"] == "REAL"
        assert all(item["source"] == "REAL" for item in real["alarms"] + real["events"])
        mismatch = client.get(API + "/dashboard", params={"device_id": "REAL-API-01", "source": "MOCK"}).json()
        assert mismatch["latest"] is None and mismatch["history"] == [] and mismatch["alarms"] == []
        unknown = client.get(API + "/dashboard", params={"device_id": "MISSING"}).json()
        assert unknown["latest"] is None and unknown["history"] == []
        assert unknown["scope"] is None and unknown["stats"]["telemetry_count"] == 0
        assert client.get(API + "/risk-results", params={"device_id": "MISSING"}).json()["items"] == []
        assert all(item["source"] == "REAL" for item in client.get(API + "/devices", params={"source": "REAL"}).json()["items"])
        assert all(item["source"] == "MOCK" for item in client.get(API + f"/sites/{SITE}/devices", params={"source": "MOCK"}).json()["items"])


def test_connector_crud_hides_password_preserves_it_on_edit_and_records_disabled_state(tmp_path):
    with opened(tmp_path) as (client, _):
        connector = {"name": "本地 MQTT", "kind": "mqtt", "source": "MOCK", "enabled": False,
                     "config": {"host": "127.0.0.1", "port": 1883, "site_id": SITE,
                                "username": "operator", "password": "private-test-password", "tls": False}}
        response = client.post(API + "/connectors", json=connector)
        assert response.status_code == 201
        saved = response.json()
        assert saved["has_password"] is True and "password" not in saved["config"]
        listing = client.get(API + "/connectors")
        assert "private-test-password" not in listing.text
        assert listing.json()["items"][0]["status"]["state"] == "disabled"
        edited = deepcopy(connector)
        edited["name"] = "已修改 MQTT"
        del edited["config"]["password"]
        updated = client.put(API + f"/connectors/{saved['id']}", json=edited).json()
        assert updated["version"] == 2 and updated["has_password"] is True
        assert "private-test-password" not in client.get(API + "/events").text
        assert client.delete(API + f"/connectors/{saved['id']}").json() == {"deleted": True}
        assert client.get(API + "/connectors").json()["items"] == []
        assert client.delete(API + f"/connectors/{saved['id']}").status_code == 404
        connector["config"]["topic"] = "#"
        assert client.post(API + "/connectors", json=connector).status_code == 422
        assert client.post(API + "/connectors", json={"name": "reserved", "kind": "http_json", "enabled": True,
                                                      "source": "MOCK", "config": {"url": "https://example.com/data"}}).status_code == 422


def test_mqtt_probe_reports_failed_without_leaking_network_errors(tmp_path, monkeypatch):
    # Broker integration is covered separately. Inject an OS failure at the
    # network boundary so this HTTP test remains runnable in socket sandboxes.
    from geohazard_platform.connectors import _MQTTSession

    def refused(_session):
        raise OSError("private-credential-must-not-appear")

    monkeypatch.setattr(_MQTTSession, "start", refused)
    with opened(tmp_path) as (client, _):
        saved = client.post(API + "/connectors", json={"name": "unavailable", "kind": "mqtt", "enabled": False,
                                                       "source": "MOCK", "config": {"host": "127.0.0.1", "port": 1883, "site_id": SITE}}).json()
        result = client.post(API + f"/connectors/{saved['id']}/test")
        assert result.status_code == 200
        assert result.json()["success"] is False and result.json()["state"] == "failed"
        assert "private-credential-must-not-appear" not in result.text


def test_image_upload_analyze_overlay_and_durable_result_api(tmp_path):
    with opened(tmp_path) as (client, _):
        rejected = client.post(API + "/evidence", data={"site_id": SITE},
                               files={"file": ("bad.png", b"not an image", "image/png")})
        assert rejected.status_code == 415
        reference, current = upload_image(client), upload_image(client, changed=True)
        assert current["filename"] == "frame.png" and current["capture_time"] is None
        quality_only = client.post(API + "/vision/analyze", json={"evidence_id": current["id"]}).json()
        assert quality_only["metrics"] is None and quality_only["vision_score"] is None
        response = client.post(API + "/vision/analyze", json={"evidence_id": current["id"], "reference_id": reference["id"],
                                                               "roi": {"x": 10, "y": 10, "width": 100, "height": 70}})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["metrics"]["changed_area_ratio"] > 0
        assert result["vision_score"] is None and result["model_version"] is None and not result["fusion_eligible"]
        assert client.get(current["file_url"]).headers["content-type"] == "image/png"
        overlay = client.get(result["overlay_url"])
        assert overlay.status_code == 200 and overlay.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert overlay.headers["x-content-type-options"] == "nosniff"
        assert client.get(API + f"/evidence/{current['id']}").json() == current
        assert client.get(API + f"/vision/results/{result['id']}").json() == result
        assert len(client.get(API + "/evidence", params={"site_id": SITE}).json()["items"]) == 2
        assert len(client.get(API + "/vision/results").json()["items"]) == 2
        assert client.get(API + "/evidence/../../etc/passwd/file").status_code == 404
    with opened(tmp_path) as (client, _):
        assert client.get(API + f"/vision/results/{result['id']}").json() == result
        assert client.get(result["overlay_url"]).status_code == 200


def test_image_roi_requires_strict_integers_and_compatible_reference(tmp_path):
    with opened(tmp_path) as (client, _):
        reference = upload_image(client, camera_id="OTHER")
        current = upload_image(client)
        assert client.post(API + "/vision/analyze", json={"evidence_id": current["id"], "reference_id": reference["id"]}).status_code == 422
        for value in (True, 1.5, "1"):
            result = client.post(API + "/vision/analyze", json={"evidence_id": current["id"], "roi": {"x": value, "y": 0, "width": 10, "height": 10}})
            assert result.status_code == 422


def test_api_token_covers_files_and_overlay_and_rejects_cross_origin_and_host(tmp_path):
    with opened(tmp_path, token="secret-local-token") as (client, _):
        assert client.get(API + "/health").status_code == 401
        client.headers["Authorization"] = "Bearer secret-local-token"
        assert client.get(API + "/health").json()["auth_mode"] == "bearer"
        reference, current = upload_image(client), upload_image(client, changed=True)
        result = client.post(API + "/vision/analyze", json={"evidence_id": current["id"], "reference_id": reference["id"]}).json()
        for url in (current["file_url"], result["overlay_url"]):
            assert client.get(url).status_code == 200
            assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get(API + "/health", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get(API + "/health", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200
        assert client.get(API + "/health", headers={"Host": "evil.example"}).status_code == 400


def test_remote_without_token_and_disabled_test_producers_are_rejected(tmp_path):
    with opened(tmp_path / "remote", remote=True) as (client, _):
        assert client.get(API + "/health").status_code == 403
    with opened(tmp_path / "disabled", demo=False) as (client, _):
        assert client.get(API + "/health").json()["counts"]["telemetry"] == 0
        assert inject(client, payload()).status_code == 403
        assert client.post(API + "/demo/step").status_code == 403
        assert client.post(API + "/demo/reset").status_code == 403
        assert client.post(API + "/demo/vision-samples").status_code == 403
        assert client.get(API + "/dashboard").json()["latest"] is None


def test_request_and_upload_limits_return_413(tmp_path):
    with opened(tmp_path, demo=False) as (client, _):
        result = client.post(API + "/evidence", content=b"small", headers={"Content-Length": str(14 * 1024 * 1024)})
        assert result.status_code == 413
        result = client.post(API + "/evidence", data={"site_id": SITE},
                             files={"file": ("oversized.png", b"x" * (12 * 1024 * 1024 + 1), "image/png")})
        assert result.status_code == 413
        assert client.get(API + "/evidence").json()["items"] == []


def test_existing_b_algorithm_entry_is_inspectable_but_execution_blocked(tmp_path):
    with opened(tmp_path, demo=False) as (client, _):
        capabilities = client.get(API + "/algorithms/capabilities").json()
        assert capabilities["sensor"]["formal_configuration"] == "NOT_CONFIGURED"
        assert capabilities["fusion"]["vision_score"] is None
        response = client.post(API + "/algorithms/sensor/inspect", json={"payload": payload()})
        assert response.status_code == 200
        assert "RISK_EXECUTION_BLOCKED" in json.dumps(response.json())


def test_history_pagination_does_not_skip_equal_timestamp_rows(tmp_path):
    with opened(tmp_path) as (client, app):
        for seq in range(1, 6):
            assert inject(client, payload(seq=seq)).status_code == 201
        with app.state.db.connection() as connection:
            connection.execute("UPDATE telemetry SET received_at=? WHERE device_id=?", ("2026-10-16T10:00:00.000Z", "MOCK-API-01"))
        collected = []
        cursor = None
        for _ in range(4):
            params = {"limit": 2, "source": "MOCK"}
            if cursor:
                params["cursor"] = cursor
            page = client.get(API + "/devices/MOCK-API-01/telemetry", params=params)
            assert page.status_code == 200, page.text
            collected.extend(item["id"] for item in page.json()["items"])
            cursor = page.json()["next_cursor"]
            if not cursor:
                break
        assert len(collected) == 5 and len(set(collected)) == 5
        assert client.get(API + "/devices/MOCK-API-01/telemetry", params={"cursor": "not-a-cursor"}).status_code == 422


def test_synchronized_source_age_and_future_clock_are_not_reported_fresh(tmp_path):
    with opened(tmp_path) as (client, _):
        now = datetime.now(timezone.utc)
        old = payload("MOCK-OLD")
        old.update(time_synced=True, timestamp_ms=int((now - timedelta(hours=1)).timestamp() * 1000))
        assert inject(client, old).status_code == 201
        projected = client.get(API + "/dashboard", params={"device_id": "MOCK-OLD"}).json()["latest"]
        assert projected["stale"] and projected["source_age_seconds"] > 3500
        assert projected["freshness_basis"] == "source_and_arrival"
        future = payload("MOCK-FUTURE")
        future.update(time_synced=True, timestamp_ms=int((now + timedelta(hours=1)).timestamp() * 1000))
        assert inject(client, future).status_code == 201
        projected = client.get(API + "/dashboard", params={"device_id": "MOCK-FUTURE"}).json()["latest"]
        assert projected["stale"] and projected["clock_error"]


def test_connector_url_and_escaped_unicode_errors_return_422(tmp_path):
    with opened(tmp_path) as (client, _):
        for url in (123, None, [], "http://[broken"):
            response = client.post(API + "/connectors", json={"name": "URL boundary", "kind": "http_json", "config": {"url": url}})
            assert response.status_code == 422, response.text
        for in_context in (False, True):
            body = {"payload": payload(), "context": {"note": "\ud800"} if in_context else {}}
            if not in_context:
                body["payload"]["experiment"]["run_id"] = "\ud800"
            # ASCII escaping is valid JSON transport; the decoded surrogate is
            # still not a valid UTF-8 string and must be a client error.
            response = client.post(API + "/ingest/test", content=json.dumps(body), headers={"Content-Type": "application/json"})
            assert response.status_code == 422, response.text
        assert len(client.get(API + "/quarantine").json()["items"]) == 2


def test_time_filters_use_equivalent_utc_offsets_and_reject_naive_dates(tmp_path):
    with opened(tmp_path) as (client, app):
        assert inject(client, payload(score=90, level="EMERGENCY")).status_code == 201
        stamp = "2026-10-18T00:00:00.000Z"
        with app.state.db.connection() as connection:
            connection.execute("UPDATE telemetry SET received_at=? WHERE device_id=?", (stamp, "MOCK-API-01"))
            connection.execute("UPDATE alarms SET created_at=? WHERE device_id=?", (stamp, "MOCK-API-01"))
            connection.execute("UPDATE events SET created_at=? WHERE device_id=?", (stamp, "MOCK-API-01"))
        for path in ("/devices/MOCK-API-01/telemetry", "/alarms", "/events"):
            params = {"device_id": "MOCK-API-01"}
            # An equal timestamp in another zone must produce the same set.
            utc = client.get(API + path, params={**params, "after": stamp}).json()["items"]
            offset = client.get(API + path, params={**params, "after": "2026-10-18T08:00:00+08:00"}).json()["items"]
            assert len(utc) == len(offset) == 1
            assert client.get(API + path, params={**params, "before": "2026-10-18T08:00:00+08:00"}).json()["items"] == []
            assert len(client.get(API + path, params={**params, "before": "2026-10-18T00:00:00.000001Z"}).json()["items"]) == 1
            assert client.get(API + path, params={**params, "after": "2026-10-18T00:00:00.000001Z"}).json()["items"] == []
            for invalid in ("not-a-date", "2026-10-18", "2026-10-18T00:00:00", ""):
                for field in ("before", "after"):
                    response = client.get(API + path, params={field: invalid})
                    assert response.status_code == 422, (path, field, invalid, response.text)


def test_vision_api_scopes_before_pagination_and_dashboard_uses_total_counts(tmp_path):
    with opened(tmp_path, demo=False) as (client, app):
        # Interleave the same station/camera across devices and sources. Every
        # accepted image must stay in its device/source slice before LIMIT.
        desired = []
        for index in range(3):
            desired.append(upload_image(client, device_id="TARGET", camera_id="CAM-SHARED"))
            upload_image(client, device_id="OTHER", camera_id="CAM-SHARED")
            upload_image(client, device_id="TARGET", source="REAL", scope="OPERATIONAL", camera_id="CAM-SHARED")
        desired_ids = {item["id"] for item in desired}
        results = [client.post(API + "/vision/analyze", json={"evidence_id": item["id"]}).json() for item in desired]
        with app.state.db.connection() as connection:
            connection.execute("UPDATE vision_evidence SET arrival_time=?", ("2026-10-18T00:00:00.000Z",))
            connection.execute("UPDATE vision_results SET created_at=?", ("2026-10-18T00:00:00.000Z",))
        for path, ids in (("/evidence", desired_ids), ("/vision/results", {item["id"] for item in results})):
            seen, cursor = [], None
            for _ in range(4):
                params = {"site_id": SITE, "device_id": "TARGET", "source": "MOCK", "camera_id": "CAM-SHARED", "limit": 1}
                if cursor:
                    params["cursor"] = cursor
                response = client.get(API + path, params=params)
                assert response.status_code == 200, response.text
                page = response.json()
                assert page["total"] == 3
                assert all(item["device_id"] == "TARGET" and item["source"] == "MOCK" for item in page["items"])
                seen.extend(item["id"] for item in page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert len(seen) == len(set(seen)) == 3 and set(seen) == ids
            assert client.get(API + path, params={"cursor": "broken"}).status_code == 422
        dashboard = client.get(API + "/dashboard", params={"device_id": "TARGET"}).json()
        assert {item["id"] for item in dashboard["vision"]["evidence"]} == desired_ids
        assert dashboard["stats"]["evidence_count"] == 3
        assert dashboard["stats"]["vision_result_count"] == 3
        with app.state.db.connection() as connection:
            template = dict(connection.execute("SELECT * FROM vision_evidence WHERE id=?", (desired[0]["id"],)).fetchone())
            for index in range(201):
                item = json.loads(template["data_json"])
                item["id"] = f"extra-evidence-{index}"
                connection.execute("INSERT INTO vision_evidence(id,site_id,camera_id,source,scope,arrival_time,path,data_json) VALUES(?,?,?,?,?,?,?,?)", (item["id"],template["site_id"],template["camera_id"],template["source"],template["scope"],template["arrival_time"],template["path"],json.dumps(item)))
        dashboard = client.get(API + "/dashboard", params={"device_id": "TARGET"}).json()
        assert dashboard["stats"]["evidence_count"] == 204
        assert len(dashboard["vision"]["evidence"]) == 200
        assert dashboard["vision"]["evidence_next_cursor"]
        # Count all alarms while returning only the recent display slice.
        with app.state.db.connection() as connection:
            connection.executemany("INSERT INTO alarms(id,site_id,device_id,source,level,score,reason,source_message_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)", [(f"alarm-{i}", SITE, "TARGET", "MOCK", "WATCH", 40, "count test", None, "2026-10-18T00:00:00.000Z") for i in range(105)])
        dashboard = client.get(API + "/dashboard", params={"device_id": "TARGET"}).json()
        assert dashboard["stats"]["alarm_count"] == 105
        assert len(dashboard["alarms"]) == 100


def test_inference_unavailable_does_not_break_ingestion_or_risk(tmp_path, monkeypatch):
    import time
    monkeypatch.setitem(sys.modules, "acl", None)
    with opened(tmp_path) as (client, app):
        for seq in range(1, 6):
            response = inject(client, payload(seq=seq, score=90, level="EMERGENCY"))
            assert response.status_code == 201 and response.json()["durable"]
        deadline = time.monotonic() + 3
        while app.state.inference.status()["failure_count"] == 0:
            assert time.monotonic() < deadline
            time.sleep(.005)
        assert client.get(API + "/health").json()["capabilities"]["atlas_acl"] == "not_connected"
        assert "acl_import_failed" in client.get(API + "/inference/status").json()["reason"]
        assert client.post(API + "/inference/self-check").json()["available"] is False
        dashboard = client.get(API + "/dashboard", params={"device_id": "MOCK-API-01"}).json()
        assert dashboard["latest"]["risk"]["final_score"] == 90


def test_inference_results_shape_filtering_pagination_and_auth(tmp_path):
    with opened(tmp_path, demo=False, token="inference-token") as (client, app):
        assert client.get(API + "/inference/status").status_code == 401
        assert client.get(API + "/inference/results").status_code == 401
        assert client.post(API + "/inference/self-check").status_code == 401
        client.headers["Authorization"] = "Bearer inference-token"
        assert client.get(API + "/inference/results").json() == {"items": [], "next_cursor": None, "total": 0}
        with app.state.db.connection() as c:
            for index in range(4):
                c.execute("""INSERT INTO inference_results
                    (id,site_id,device_id,source,scope,model,window_start_at,window_end_at,
                     predicted_delta,latency_ms,created_at,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(index), "S", "D" if index < 3 else "OTHER", "MOCK", "TEST_ONLY", "soil",
                     "2026-10-22T00:00:00.000Z", "2026-10-22T00:00:03.000Z", "[0.01]", .5,
                     "2026-10-22T00:00:04.000Z", "Uncalibrated research; excluded from risk fusion"))
        params = {"site_id": "S", "device_id": "D", "limit": 2}
        page = client.get(API + "/inference/results", params=params).json()
        assert page["total"] == 3 and len(page["items"]) == 2 and page["next_cursor"]
        item = page["items"][0]
        assert item["predicted_delta"] == [.01] and item["fusion_eligible"] is False
        assert item["source"] == "MOCK" and item["scope"] == "TEST_ONLY"
        assert item["calibration"] == "uncalibrated_research" and item["reason"]
        second = client.get(API + "/inference/results", params={**params, "cursor": page["next_cursor"]}).json()
        assert len(second["items"]) == 1 and second["next_cursor"] is None
        assert len({item["id"] for item in page["items"] + second["items"]}) == 3
        assert client.get(API + "/inference/results", params={"cursor": "broken"}).status_code == 422
        assert client.get(API + "/inference/results", params={"limit": 0}).status_code == 422


def test_common_ingestion_hook_observes_accepted_current_only_and_is_isolated(tmp_path, monkeypatch):
    with opened(tmp_path) as (client, app):
        observations = []
        monkeypatch.setattr(app.state.inference, "observe", observations.append)
        original = payload(seq=2)
        assert inject(client, original).status_code == 201
        assert len(observations) == 1
        assert observations[0]["source"] == "MOCK" and observations[0]["scope"] == "TEST_ONLY"
        assert inject(client, original).json()["status"] == "duplicate"
        assert inject(client, payload(seq=1)).json()["is_backfill"]
        assert len(observations) == 1
        assert client.post(API + "/demo/step").status_code == 200
        assert observations[-1]["device_id"] == DEVICE

        def broken_observer(payload):
            raise RuntimeError("inference adapter failure")

        monkeypatch.setattr(app.state.inference, "observe", broken_observer)
        response = inject(client, payload(seq=3))
        assert response.status_code == 201 and response.json()["durable"]
