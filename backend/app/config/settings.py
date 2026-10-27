from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


_ENV_CANDIDATES = [
    BACKEND_ROOT / ".env",
    BACKEND_ROOT.parent / ".env",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(str(p) for p in _ENV_CANDIDATES if p.exists()) or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_mode: str = "demo"
    database_url: str = "sqlite:///./typhoon_platform.db"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    api_key: str = ""
    precheck_secret: str = ""
    precheck_ttl_minutes: int = 60
    seed_random_seed: int = 42
    default_dataset_id: str = "demo"
    rules_config_path: str = str(BACKEND_ROOT / "config" / "rules.yaml")
    prediction_targets_path: str = str(BACKEND_ROOT / "config" / "prediction_targets.yaml")
    demo_open: bool = True
    max_upload_mb: int = 20
    max_page_size: int = 200
    artifact_dir: str = str(BACKEND_ROOT / "artifacts")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
