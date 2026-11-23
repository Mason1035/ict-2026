"""Real HTTP contracts. No desktop captures, production server, broker or board."""
from contextlib import contextmanager
import json

from fastapi.testclient import TestClient
import pytest

from geohazard_platform.main import create_app
from geohazard_platform.settings import Settings
from geohazard_platform.telemetry import ingest_telemetry
from geohazard_platform.demo import fixture_payload, SCENARIOS
from test_research_display import register_synthetic, EXPERIMENT


@contextmanager
def opened(root, token=""):
    registry, _ = register_synthetic(root)
    app = create_app(Settings(data_dir=root / "production", research_registry_path=registry,
                              demo_enabled=False, acl_mode="off", api_token=token))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client, app


def test_list_detail_rules_and_provenance(tmp_path):
    with opened(tmp_path) as (client, _):
        listing = client.get("/api/research/sessions")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["experiment_id"] == EXPERIMENT
        for suffix in ("", "/rules"):
            response = client.get(f"/api/research/sessions/{EXPERIMENT}{suffix}", params={"max_points": 16})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["scope"] == "RESEARCH" and body["uncalibrated"] is True
            assert body["production_alarm_eligible"] is False
            assert body["provenance"]["method_version"] == "PROVISIONAL-v1"
            assert len(body["provenance"]["config_sha256"]) == 64
            assert response.headers["cache-control"] == "no-store"
            if suffix:
                assert body["trigger_count"] > 0 and len(body["reason_decode"]) == 7
            else:
                assert all(len(curve["points"]) <= 16 for c in body["channels"].values() for curve in c["curves"])


@pytest.mark.parametrize("suffix", ["", "/rules"])
def test_unregistered_session_404(tmp_path, suffix):
    with opened(tmp_path) as (client, _):
        assert client.get("/api/research/sessions/unregistered" + suffix).status_code == 404


@pytest.mark.parametrize("limit", [0, 15, 2001, "invalid"])
def test_point_limit_validation(tmp_path, limit):
    with opened(tmp_path) as (client, _):
        assert client.get(f"/api/research/sessions/{EXPERIMENT}", params={"max_points": limit}).status_code == 422


def test_production_research_isolation_and_no_production_writes(tmp_path):
    with opened(tmp_path) as (client, app):
        payload = fixture_payload({"sensors": dict(SCENARIOS["D"]), "boot_id": 1, "seq": 1, "elapsed_seconds": 1})
        payload["device_id"] = "REAL-WP4-OPERATIONAL"
        ingest_telemetry(app.state.db, payload, source="REAL", scope="OPERATIONAL", transport="mqtt")
        def snapshot():
            with app.state.db.connection() as connection:
                tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                return {t: [tuple(r) for r in connection.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] for t in tables}
        before = snapshot()
        alarms = client.get("/api/v1/alarms").json()["items"]
        assert alarms and all(a["scope"] == "OPERATIONAL" for a in alarms)
        for suffix in ("", f"/{EXPERIMENT}", f"/{EXPERIMENT}/rules"):
            response = client.get("/api/research/sessions" + suffix, params={"scope": "OPERATIONAL"})
            assert response.status_code == 200
            assert "OPERATIONAL" not in json.dumps(response.json())
        assert client.get("/api/research/alarms").status_code == 404
        assert client.get("/api/research/sessions/REAL-WP4-OPERATIONAL").status_code == 404
        assert client.get("/api/v1/research/sessions").status_code == 404
        assert client.get("/api/v1/alarms", params={"scope": "RESEARCH"}).status_code == 422
        assert client.get("/api/v1/devices/NODE-01/telemetry").json()["items"] == []
        assert client.get("/api/v1/inference/results").json()["items"] == []
        assert client.get("/api/v1/alarms").json()["items"] == alarms
        assert snapshot() == before


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_research_endpoints_are_get_only(tmp_path, method):
    with opened(tmp_path) as (client, _):
        for suffix in ("", f"/{EXPERIMENT}", f"/{EXPERIMENT}/rules"):
            assert getattr(client, method)("/api/research/sessions" + suffix).status_code == 405


def test_research_auth_and_origin_boundary(tmp_path):
    with opened(tmp_path, token="test-secret") as (client, _):
        for suffix in ("", f"/{EXPERIMENT}", f"/{EXPERIMENT}/rules"):
            path = "/api/research/sessions" + suffix
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"Authorization": "Bearer test-secret"}).status_code == 200
        assert client.get("/api/research/sessions", headers={"Authorization": "Bearer test-secret", "Origin": "https://invalid.example"}).status_code == 403


def test_research_remote_without_token_is_denied(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "prod", demo_enabled=False, acl_mode="off"))
    with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.15", 50000)) as client:
        assert client.get("/api/research/sessions").status_code == 403


def test_missing_registry_no_file_creation(tmp_path):
    path = tmp_path / "absent.sqlite3"
    app = create_app(Settings(data_dir=tmp_path / "prod", research_registry_path=path, demo_enabled=False))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/research/sessions").status_code == 503
    assert not path.exists()


def test_changed_triplet_returns_sanitized_conflict(tmp_path):
    with opened(tmp_path) as (client, _):
        (tmp_path / "capture/N0000004.CSV").write_bytes(b"tampered")
        for suffix in ("", "/rules"):
            response = client.get(f"/api/research/sessions/{EXPERIMENT}{suffix}")
            assert response.status_code == 409
            assert str(tmp_path) not in response.text
