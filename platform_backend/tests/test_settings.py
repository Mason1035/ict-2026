import pytest

from geohazard_platform.settings import Settings


def test_custom_platform_port_allows_only_matching_local_origins(monkeypatch):
    monkeypatch.setenv("GEOHAZARD_PORT", "8001")
    origins = Settings().allowed_origins
    assert "http://127.0.0.1:8001" in origins
    assert "http://localhost:8001" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "http://127.0.0.1:8000" in origins
    assert "http://192.168.1.2:8001" not in origins
    assert "http://127.0.0.1:8002" not in origins


@pytest.mark.parametrize("port", ["", "0", "65536", "-1", "8000.0", "8000/path", "８０００"])
def test_invalid_platform_port_fails_before_startup(monkeypatch, port):
    monkeypatch.setenv("GEOHAZARD_PORT", port)
    with pytest.raises(ValueError, match="GEOHAZARD_PORT"):
        Settings()
