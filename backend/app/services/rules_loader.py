from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


@lru_cache
def load_rules() -> dict[str, Any]:
    path = Path(get_settings().rules_config_path)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_prediction_targets() -> dict[str, Any]:
    path = Path(get_settings().prediction_targets_path)
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def clear_config_cache() -> None:
    load_rules.cache_clear()
    load_prediction_targets.cache_clear()
