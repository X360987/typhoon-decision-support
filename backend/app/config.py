"""集中管理配置，不在源码中保存数据库密码。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量或项目 .env 读取本机运行参数。"""

    database_url: str = "postgresql+psycopg://typhoon:CHANGE_ME@127.0.0.1:55432/typhoon"
    storage_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 50 * 1024 * 1024
    write_api_key: str = ""
    max_import_rows: int = 100_000
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore"
    )


settings = Settings()
