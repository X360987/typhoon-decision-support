"""Apply migrations and (demo mode only) seed the simulated dataset."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services.demo_setup import seed_and_prepare_demo  # noqa: E402


def upgrade_schema(database_url: str | None = None) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["database_url"] = database_url or get_settings().database_url
    cfg.attributes["skip_logging_config"] = True
    command.upgrade(cfg, "head")


def main() -> None:
    settings = get_settings()
    print("Applying migrations (alembic upgrade head)...")
    upgrade_schema()
    if settings.data_mode != "demo":
        print("DATA_MODE=real: schema ready, no demo data seeded.")
        return
    db = SessionLocal()
    try:
        print("Seeding demo dataset and running the simulated model experiment...")
        out = seed_and_prepare_demo(db)
        print(out["seed"])
        print(out["train"])
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
