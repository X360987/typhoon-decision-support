"""场景：灾中。用现有单指标预测合成多维走向。没有校准集时不给出区间。"""

from __future__ import annotations

from typing import Any

WEIGHTS = {
    "affected_trains": 0.25,
    "personal_weibo_count": 0.25,
    "negative_ratio": 0.25,
    "official_weibo_count": 0.25,
}


def _scale(target_id: str, value: float | None) -> float | None:
    if value is None:
        return None
    if target_id == "negative_ratio":
        return max(0.0, min(1.0, value))
    return value / (value + 1.0)


def synthesize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in items:
        if item.get("point_pred") is None:
            continue
        grouped.setdefault((item["province_code"], item["lead_hours"]), []).append(item)
    out = []
    for (province, lead), rows in sorted(grouped.items()):
        weights = []
        scaled = {}
        for row in rows:
            target = row["target_id"]
            value = _scale(target, row["point_pred"])
            if value is None:
                continue
            scaled[target] = value
            weights.append((WEIGHTS.get(target, 0.0), value))
        total = sum(weight for weight, _ in weights)
        if total <= 0:
            continue
        out.append(
            {
                "province_code": province,
                "lead_hours": lead,
                "valid_time": rows[0]["valid_time"],
                "value": sum(weight * value for weight, value in weights) / total,
                "contributions": scaled,
                "interval_low": None,
                "interval_high": None,
                "interval_reason": "区间不可用：当前模型与基线均不输出经过校准的预测区间",
                "sample_size": len(scaled),
            }
        )
    return out
