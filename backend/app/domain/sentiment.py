"""Pluggable sentiment interface. Default is an explicitly labeled demo rule classifier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


NEGATIVE_KEYWORDS = ("担心", "害怕", "求助", "停运", "危险", "受灾", "恐慌", "催促", "抱怨", "愤怒")
POSITIVE_KEYWORDS = ("安全", "谢谢", "安心", "恢复", "顺利", "加油")
HELP_KEYWORDS = ("求助", "求救", "需要帮助", "谁能帮")


@dataclass
class SentimentResult:
    label: str  # negative|neutral|positive|unknown
    score: float | None
    model_version: str
    is_help_request: bool


class SentimentModel(Protocol):
    def classify(self, text: str) -> SentimentResult: ...


class DemoRuleSentiment:
    """Demo-only rule classifier. Replace via SentimentModel adapter without changing API contracts."""

    version = "demo-rule-v1"

    def classify(self, text: str) -> SentimentResult:
        if not text or not text.strip():
            return SentimentResult("unknown", None, self.version, False)
        t = text.strip()
        neg = sum(1 for k in NEGATIVE_KEYWORDS if k in t)
        pos = sum(1 for k in POSITIVE_KEYWORDS if k in t)
        help_req = any(k in t for k in HELP_KEYWORDS)
        if neg == 0 and pos == 0:
            return SentimentResult("unknown", None, self.version, help_req)
        if neg > pos:
            score = min(1.0, 0.55 + 0.1 * neg)
            return SentimentResult("negative", score, self.version, help_req)
        if pos > neg:
            score = min(1.0, 0.55 + 0.1 * pos)
            return SentimentResult("positive", score, self.version, help_req)
        return SentimentResult("neutral", 0.5, self.version, help_req)


_default = DemoRuleSentiment()


def get_sentiment_model() -> SentimentModel:
    return _default
