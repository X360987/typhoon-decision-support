"""场景：灾前。由台风名称、编号和省份生成带版本的检索词。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.config import get_settings
PROVINCE_CN = {"FJ": "福建", "GD": "广东", "ZJ": "浙江", "JS": "江苏", "SH": "上海", "TW": "台湾"}


@lru_cache
def load_lexicon() -> dict[str, list[str]]:
    path = Path(get_settings().keyword_lexicon_path)
    if not path.exists():
        return {"scene_words": ["台风"], "negative_words": []}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return {
        "scene_words": [str(w) for w in data.get("scene_words") or []],
        "negative_words": [str(w) for w in data.get("negative_words") or []],
    }


def _dedupe(words: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for word in words:
        text = str(word).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def build_keyword_set(
    *,
    name: str | None,
    english_name: str | None = None,
    typhoon_id: str | None = None,
    aliases: list[str] | None = None,
    provinces: list[str] | None = None,
) -> dict[str, Any]:
    """正向词：中文名、英文名、编号、别名，以及「台风+省份」。再并入场景词。"""
    lexicon = load_lexicon()
    positive: list[str] = []
    for word in (name, english_name, typhoon_id, *(aliases or [])):
        if word:
            positive.append(str(word))
    for code in provinces or []:
        cn = PROVINCE_CN.get(code, code)
        positive.append(f"台风{cn}")
    positive.extend(lexicon["scene_words"])
    return {
        "keywords": _dedupe(positive),
        "negative_keywords": _dedupe(lexicon["negative_words"]),
    }


def estimate_coverage(keywords: list[str], negative: list[str], samples: list[str]) -> float | None:
    if not samples:
        return None
    hit = 0
    for text in samples:
        body = text or ""
        if any(word in body for word in negative) and not any(word in body for word in keywords):
            continue
        if any(word in body for word in keywords):
            hit += 1
    return hit / len(samples)
