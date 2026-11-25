from dataclasses import dataclass, field
from pathlib import Path
import os
import ipaddress

REPO_ROOT = Path(__file__).resolve().parents[3]


def loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def local_origins() -> tuple[str, ...]:
    raw_port = os.environ.get("GEOHAZARD_PORT", "8000")
    if not raw_port.isascii() or not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise ValueError("GEOHAZARD_PORT must be an integer between 1 and 65535")
    ports = dict.fromkeys((5173, 5174, 8000, int(raw_port)))
    return tuple(f"http://{host}:{port}" for port in ports for host in ("127.0.0.1", "localhost"))


def _env_real_test_database() -> Path | None:
    raw = os.environ.get("GEOHAZARD_REAL_TEST_DATABASE")
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must be a nonempty file path when set")
    return Path(value)


def _same_path(first: Path, second: Path) -> bool:
    resolved_first = first.expanduser().resolve(strict=False)
    resolved_second = second.expanduser().resolve(strict=False)
    if resolved_first == resolved_second:
        return True
    if resolved_first.exists() and resolved_second.exists():
        return resolved_first.samefile(resolved_second)
    return False


def validate_real_test_database_path(real_test_path: Path, platform_path: Path, research_path: Path) -> Path:
    raw = str(real_test_path).strip()
    if not raw or raw == ":memory:" or raw.startswith("file:"):
        raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must be a regular local SQLite file path")
    candidate = Path(raw)
    resolved = candidate.expanduser().resolve(strict=False)
    if resolved.exists() and resolved.is_dir():
        raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must point to a file, not a directory")
    if _same_path(candidate, platform_path):
        raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must not share the platform.sqlite3 path")
    if _same_path(candidate, research_path):
        raise ValueError("GEOHAZARD_REAL_TEST_DATABASE must not share the research registry path")
    return candidate


@dataclass
class Settings:
    host: str = field(default_factory=lambda: os.environ.get("GEOHAZARD_HOST", "127.0.0.1"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("GEOHAZARD_DATA_DIR", str(REPO_ROOT / "platform_backend" / "data"))))
    api_token: str = field(default_factory=lambda: os.environ.get("GEOHAZARD_API_TOKEN", ""))
    demo_enabled: bool = field(default_factory=lambda: os.environ.get("GEOHAZARD_DEMO", "1") == "1")
    acl_mode: str = field(default_factory=lambda: os.environ.get("GEOHAZARD_ACL", "auto"))
    acl_model_dir: Path = field(default_factory=lambda: Path(os.environ.get("GEOHAZARD_ACL_MODEL_DIR", str(REPO_ROOT / "experiments/atlas_public_sensor_v1"))))
    demo_interval: float = 2.0
    freshness_seconds: int = 30
    allowed_origins: tuple[str, ...] = field(default_factory=local_origins)
    research_registry_path: Path = field(default_factory=lambda: Path(os.environ.get(
        "GEOHAZARD_RESEARCH_REGISTRY", str(REPO_ROOT / "work/replay/research.sqlite3"))))
    real_test_database_path: Path | None = None
    real_test_database_path_kind: str = field(init=False, default="default_data_dir")

    def __post_init__(self):
        if not self.host or any(c.isspace() for c in self.host) or any(c in self.host for c in "/@?#"):
            raise ValueError("GEOHAZARD_HOST must be a bind IP or hostname")
        if not loopback_host(self.host) and not self.api_token.strip():
            raise ValueError("Non-loopback GEOHAZARD_HOST requires GEOHAZARD_API_TOKEN")
        if self.real_test_database_path is not None:
            self.real_test_database_path = Path(self.real_test_database_path)
            self.real_test_database_path_kind = "explicit_setting"
        else:
            env_path = _env_real_test_database()
            if env_path is not None:
                self.real_test_database_path = env_path
                self.real_test_database_path_kind = "configured_env"
            else:
                self.real_test_database_path = self.data_dir / "real_test.sqlite3"
                self.real_test_database_path_kind = "default_data_dir"
        self.real_test_database_path = validate_real_test_database_path(
            self.real_test_database_path, self.database_path, self.research_registry_path
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "platform.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"
