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


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.1", "::", "atlas-board"])
def test_lan_requires_nonempty_token(host):
    with pytest.raises(ValueError, match="GEOHAZARD_API_TOKEN"):
        Settings(host=host, api_token=" ")
    assert Settings(host=host, api_token="secret").host == host


def test_real_test_database_defaults_to_separate_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOHAZARD_REAL_TEST_DATABASE", raising=False)
    settings = Settings(data_dir=tmp_path)
    assert settings.real_test_database_path == tmp_path / "real_test.sqlite3"
    assert settings.real_test_database_path != settings.database_path
    assert settings.real_test_database_path != settings.research_registry_path
    assert settings.real_test_database_path_kind == "default_data_dir"


def test_real_test_database_env_configuration(tmp_path, monkeypatch):
    custom = tmp_path / "dedicated" / "node01_real_test.sqlite3"
    monkeypatch.setenv("GEOHAZARD_REAL_TEST_DATABASE", str(custom))
    settings = Settings(data_dir=tmp_path)
    assert settings.real_test_database_path == custom
    assert settings.real_test_database_path_kind == "configured_env"


def test_real_test_database_rejects_platform_and_research_collisions(tmp_path, monkeypatch):
    platform_db = tmp_path / "platform.sqlite3"
    research_db = tmp_path / "research.sqlite3"
    platform_db.write_text("", encoding="utf-8")
    research_db.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="platform.sqlite3"):
        Settings(data_dir=tmp_path, real_test_database_path=platform_db)
    with pytest.raises(ValueError, match="research"):
        Settings(data_dir=tmp_path, research_registry_path=research_db, real_test_database_path=research_db)
    with pytest.raises(ValueError, match="directory"):
        Settings(data_dir=tmp_path, real_test_database_path=tmp_path)
    with pytest.raises(ValueError, match="regular local SQLite"):
        Settings(data_dir=tmp_path, real_test_database_path=":memory:")
    monkeypatch.setenv("GEOHAZARD_REAL_TEST_DATABASE", "   ")
    with pytest.raises(ValueError, match="GEOHAZARD_REAL_TEST_DATABASE"):
        Settings(data_dir=tmp_path)


def test_real_test_database_rejects_symlink_to_platform(tmp_path):
    platform_db = tmp_path / "platform.sqlite3"
    platform_db.write_text("", encoding="utf-8")
    alias = tmp_path / "alias.sqlite3"
    try:
        alias.symlink_to(platform_db)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable; exercised by Linux CI")
        raise
    with pytest.raises(ValueError, match="platform.sqlite3"):
        Settings(data_dir=tmp_path, real_test_database_path=alias)
