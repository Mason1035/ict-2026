from dataclasses import dataclass, field
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[3]


def local_origins() -> tuple[str, ...]:
    raw_port = os.environ.get("GEOHAZARD_PORT", "8000")
    if not raw_port.isascii() or not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise ValueError("GEOHAZARD_PORT must be an integer between 1 and 65535")
    ports = dict.fromkeys((5173, 5174, 8000, int(raw_port)))
    return tuple(f"http://{host}:{port}" for port in ports for host in ("127.0.0.1", "localhost"))


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("GEOHAZARD_DATA_DIR", str(REPO_ROOT / "platform_backend" / "data"))))
    api_token: str = field(default_factory=lambda: os.environ.get("GEOHAZARD_API_TOKEN", ""))
    demo_enabled: bool = field(default_factory=lambda: os.environ.get("GEOHAZARD_DEMO", "1") == "1")
    demo_interval: float = 2.0
    freshness_seconds: int = 30
    allowed_origins: tuple[str, ...] = field(default_factory=local_origins)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "platform.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"
