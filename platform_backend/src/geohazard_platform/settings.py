from dataclasses import dataclass, field
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("GEOHAZARD_DATA_DIR", str(REPO_ROOT / "platform_backend" / "data"))))
    api_token: str = field(default_factory=lambda: os.environ.get("GEOHAZARD_API_TOKEN", ""))
    demo_enabled: bool = field(default_factory=lambda: os.environ.get("GEOHAZARD_DEMO", "1") == "1")
    demo_interval: float = 2.0
    freshness_seconds: int = 30
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:5174", "http://localhost:5174",
        "http://127.0.0.1:8000", "http://localhost:8000",
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "platform.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"
