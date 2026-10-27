"""Single / pair / joint anomaly detectors. Do not read scenario labels.

Each detector only runs where the dimensions it needs have observations for the
province and window. A missing dimension yields an ``insufficient`` task status,
never a deterministic relation anomaly, and missing hours are never read as zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.domain.stats import quantile, rolling_mean, robust_z, safe_ratio

DIMENSIONS = ("social", "organizational", "physical")
PAIR_TASKS = {
    "pair_social_org": ("social", "organizational"),
    "pair_social_physical": ("social", "physical"),
    "pair_org_physical": ("organizational", "physical"),
}


@dataclass
class MetricPoint:
    province_code: str
    hour_bj: datetime
    metric_id: str
    value: float | None
    sample_size: int | None = None
    available_at: datetime | None = None


@dataclass
class AnomalyCandidate:
    analysis_scope: str
    dimensions: list[str]
    anomaly_type: str
    province_code: str
    hour_bj: datetime
    nature: str = "observation"
    score: float | None = None
    baseline: float | None = None
    threshold: float | None = None
    quality_status: str = "ok"
    explanation: str = ""
    evidences: list[dict[str, Any]] = field(default_factory=list)
    group_key: str = ""
    available_at: datetime | None = None
    requires_future_window: bool = False
    task: str = ""


def _avail(points: Iterable[MetricPoint | None], floor: datetime | None = None) -> datetime | None:
    """Latest availability among inputs; unknown availability of any input makes the result unknown."""
    latest = floor
    for p in points:
        if p is None:
            continue
        if p.available_at is None:
            return None
        if latest is None or p.available_at > latest:
            latest = p.available_at
    return latest


def _window(series: list[MetricPoint], hour: datetime, window: int) -> list[MetricPoint]:
    """Observed points in the real-time window [hour - window h, hour)."""
    lo = hour - timedelta(hours=window)
    return [p for p in series if lo <= p.hour_bj < hour and p.value is not None]


def _history_before(series: list[MetricPoint], hour: datetime, window: int) -> list[float]:
    return [p.value for p in _window(series, hour, window)]  # type: ignore[misc]


def _by_province(points: list[MetricPoint]) -> dict[str, list[MetricPoint]]:
    grouped: dict[str, list[MetricPoint]] = {}
    for p in points:
        grouped.setdefault(p.province_code, []).append(p)
    for code in grouped:
        grouped[code] = sorted(grouped[code], key=lambda x: x.hour_bj)
    return grouped


def _index(points: list[MetricPoint], metric: str) -> dict[tuple[str, datetime], MetricPoint]:
    return {(p.province_code, p.hour_bj): p for p in points if p.metric_id == metric}


def detect_single_social(
    points: list[MetricPoint],
    rules: dict[str, Any],
    rule_version: str = "rules-v1",
) -> list[AnomalyCandidate]:
    cfg = rules.get("single", {})
    social = cfg.get("social", {})
    window = int(cfg.get("window_hours", 12))
    min_samples = int(cfg.get("min_samples", 6))
    out: list[AnomalyCandidate] = []

    neg_by_prov = _by_province([p for p in points if p.metric_id == "negative_ratio"])
    disc_by_prov = _by_province([p for p in points if p.metric_id == "personal_weibo_count"])

    for neg_series in neg_by_prov.values():
        for p in neg_series:
            if p.value is None or (p.sample_size or 0) < min_samples:
                continue
            win = _window(neg_series, p.hour_bj, window)
            hist = [x.value for x in win]
            z, status = robust_z(p.value, hist)  # type: ignore[arg-type]
            floor = float(social.get("negative_ratio_abs_floor", 0.35))
            thr = quantile(hist, float(cfg.get("quantile_threshold", 0.95))) if hist else None  # type: ignore[arg-type]
            triggered = False
            score = z
            if status == "ok" and z is not None and z >= float(cfg.get("mad_z_threshold", 3.0)):
                triggered = True
            elif thr is not None and p.value >= thr and p.value >= floor and len(hist) >= 3:
                triggered = p.value > thr or p.value >= floor + 0.15
                score = p.value - thr
            elif len(hist) < 3 and p.value >= floor + 0.15:
                triggered = True
                score = p.value - floor
            if triggered:
                out.append(
                    AnomalyCandidate(
                        "single",
                        ["social"],
                        "negative_ratio_spike",
                        p.province_code,
                        p.hour_bj,
                        score=score,
                        baseline=rolling_mean(hist),  # type: ignore[arg-type]
                        threshold=thr if thr is not None else floor,
                        explanation="社会维：负面情绪比例相对适用基线显著升高。",
                        evidences=[
                            {
                                "evidence_type": "metric",
                                "summary": f"negative_ratio={p.value}, samples={p.sample_size}, window_points={len(hist)}",
                                "payload": {
                                    "metric_id": "negative_ratio",
                                    "value": p.value,
                                    "sample_size": p.sample_size,
                                    "window_hours": window,
                                    "window_points": len(hist),
                                },
                            }
                        ],
                        group_key=f"social:neg:{p.province_code}:{p.hour_bj.isoformat()}",
                        available_at=_avail([p, *win]),
                        task="single_social",
                    )
                )

    factor = float(social.get("discussion_spike_factor", 2.5))
    for disc_series in disc_by_prov.values():
        for p in disc_series:
            if p.value is None:
                continue
            win = _window(disc_series, p.hour_bj, window)
            hist = [x.value for x in win]
            base = rolling_mean(hist)  # type: ignore[arg-type]
            if base is None or base <= 0 or len(hist) < min_samples:
                continue
            if p.value >= base * factor:
                out.append(
                    AnomalyCandidate(
                        "single",
                        ["social"],
                        "discussion_spike",
                        p.province_code,
                        p.hour_bj,
                        score=p.value / base,
                        baseline=base,
                        threshold=base * factor,
                        explanation="社会维：讨论量相对滚动基线突增。",
                        evidences=[
                            {
                                "evidence_type": "metric",
                                "summary": f"personal_weibo_count={p.value}, baseline={base:.2f}",
                                "payload": {"metric_id": "personal_weibo_count", "value": p.value, "baseline": base},
                            }
                        ],
                        group_key=f"social:disc:{p.province_code}:{p.hour_bj.isoformat()}",
                        available_at=_avail([p, *win]),
                        task="single_social",
                    )
                )
    return out


def detect_single_org(points: list[MetricPoint], rules: dict[str, Any]) -> list[AnomalyCandidate]:
    cfg = rules.get("single", {})
    org = cfg.get("org", {})
    window = int(cfg.get("window_hours", 12))
    min_samples = int(cfg.get("min_samples", 6))
    out: list[AnomalyCandidate] = []
    spike = float(org.get("publish_spike_factor", 2.5))
    drop = float(org.get("publish_drop_factor", 0.35))
    gap_h = int(org.get("gap_hours", 6))
    need = max(3, min(gap_h, 5))
    for series in _by_province([p for p in points if p.metric_id == "official_weibo_count"]).values():
        observed = {x.hour_bj: x for x in series if x.value is not None}
        for p in series:
            if p.value is None:
                continue
            win = _window(series, p.hour_bj, window)
            hist = [x.value for x in win]
            base = rolling_mean(hist)  # type: ignore[arg-type]
            if base is None or len(hist) < min_samples:
                continue
            if p.value >= max(1.0, base * spike):
                out.append(
                    AnomalyCandidate(
                        "single",
                        ["organizational"],
                        "official_publish_spike",
                        p.province_code,
                        p.hour_bj,
                        score=p.value / max(base, 1e-6),
                        baseline=base,
                        threshold=base * spike,
                        explanation="组织维：可观测信息发布序列相对基线突变升高。",
                        evidences=[
                            {
                                "evidence_type": "metric",
                                "summary": f"official_weibo_count={p.value}, baseline={base:.2f}",
                                "payload": {"metric_id": "official_weibo_count", "value": p.value, "baseline": base},
                            }
                        ],
                        group_key=f"org:spike:{p.province_code}:{p.hour_bj.isoformat()}",
                        available_at=_avail([p, *win]),
                        task="single_org",
                    )
                )
            if base >= 1 and p.value <= base * drop:
                streak: list[MetricPoint] = []
                cursor = p.hour_bj
                while True:
                    x = observed.get(cursor)
                    if x is None or x.value is None or x.value > base * drop:
                        break
                    streak.append(x)
                    cursor -= timedelta(hours=1)
                if len(streak) >= need:
                    out.append(
                        AnomalyCandidate(
                            "single",
                            ["organizational"],
                            "official_publish_gap",
                            p.province_code,
                            p.hour_bj,
                            score=safe_ratio(p.value, base),
                            baseline=base,
                            threshold=base * drop,
                            explanation="组织维：信息发布相对基线连续偏低（按连续观测小时计，不据此断言失职）。",
                            evidences=[
                                {
                                    "evidence_type": "metric",
                                    "summary": f"consecutive_low_hours={len(streak)}, need={need}",
                                    "payload": {"value": p.value, "baseline": base, "consecutive_hours": len(streak)},
                                }
                            ],
                            group_key=f"org:gap:{p.province_code}:{p.hour_bj.isoformat()}",
                            available_at=_avail([p, *win, *streak]),
                            task="single_org",
                        )
                    )
    return out


def detect_single_physical(points: list[MetricPoint], rules: dict[str, Any]) -> list[AnomalyCandidate]:
    cfg = rules.get("single", {})
    phys = cfg.get("physical", {})
    window = int(cfg.get("window_hours", 12))
    min_samples = int(cfg.get("min_samples", 6))
    out: list[AnomalyCandidate] = []
    factor = float(phys.get("suspension_spike_factor", 2.0))
    floor = float(phys.get("affected_trains_abs_floor", 8))
    for series in _by_province([p for p in points if p.metric_id == "affected_trains"]).values():
        for p in series:
            if p.value is None:
                continue
            win = _window(series, p.hour_bj, window)
            hist = [x.value for x in win]
            base = rolling_mean(hist)  # type: ignore[arg-type]
            triggered = False
            thr = None
            score = None
            if base is not None and len(hist) >= min_samples and base > 0 and p.value >= base * factor:
                triggered = True
                thr = base * factor
                score = p.value / base
            elif p.value >= floor and (base is None or p.value >= max(floor, base + 3)):
                triggered = True
                thr = floor
                score = p.value - floor
            if triggered:
                out.append(
                    AnomalyCandidate(
                        "single",
                        ["physical"],
                        "suspension_concentration",
                        p.province_code,
                        p.hour_bj,
                        score=score,
                        baseline=base,
                        threshold=thr,
                        explanation="物理维：停运/受影响车次集中增加（可能含预防性停运，不等于设施损坏）。",
                        evidences=[
                            {
                                "evidence_type": "metric",
                                "summary": f"affected_trains={p.value}",
                                "payload": {"metric_id": "affected_trains", "value": p.value, "baseline": base},
                            }
                        ],
                        group_key=f"phys:susp:{p.province_code}:{p.hour_bj.isoformat()}",
                        available_at=_avail([p, *win]),
                        task="single_physical",
                    )
                )
    return out


def detect_social_org(social: list[MetricPoint], org: list[MetricPoint], rules: dict[str, Any]) -> list[AnomalyCandidate]:
    pair_cfg = rules.get("pair", {})
    lag = int(pair_cfg.get("lag_hours", 3))
    min_cov = float(pair_cfg.get("min_coverage", 0.5))
    imb = float(pair_cfg.get("social_org", {}).get("discussion_vs_official_imbalance", 2.0))
    disc = _index(social, "personal_weibo_count")
    off = _by_province([p for p in org if p.metric_id == "official_weibo_count"])
    out: list[AnomalyCandidate] = []
    for (prov, hour), d in disc.items():
        if d.value is None or d.value < 5 or prov not in off:
            continue
        lo = hour - timedelta(hours=lag)
        win = [p for p in off[prov] if lo <= p.hour_bj <= hour and p.value is not None]
        if len(win) / (lag + 1) < min_cov:
            continue
        off_sum = float(sum(p.value for p in win))  # type: ignore[misc]
        ratio = d.value / max(off_sum, 0.5)
        if ratio >= imb:
            out.append(
                AnomalyCandidate(
                    "pair",
                    ["organizational", "social"],
                    "social_org_mismatch",
                    prov,
                    hour,
                    score=ratio,
                    baseline=off_sum,
                    threshold=imb,
                    explanation="社会—组织：公众讨论升高而同期官方发布匹配偏弱（相关性非因果）。",
                    evidences=[
                        {
                            "evidence_type": "relation",
                            "summary": f"discussion={d.value}, official_sum={off_sum}, org_hours_observed={len(win)}/{lag + 1}",
                            "payload": {"discussion": d.value, "official_sum": off_sum, "window_hours": lag + 1},
                        }
                    ],
                    group_key=f"pair:so:{prov}:{hour.isoformat()}",
                    available_at=_avail([d, *win]),
                    task="pair_social_org",
                )
            )
    return out


def detect_social_physical(
    social: list[MetricPoint], physical: list[MetricPoint], rules: dict[str, Any]
) -> list[AnomalyCandidate]:
    pair_cfg = rules.get("pair", {})
    imb = float(pair_cfg.get("social_physical", {}).get("emotion_vs_suspension_imbalance", 2.0))
    neg = _index(social, "negative_ratio")
    trains = _index(physical, "affected_trains")
    out: list[AnomalyCandidate] = []
    for key in set(neg) & set(trains):
        n, t = neg[key], trains[key]
        if n.value is None or t.value is None:
            continue
        prov, hour = key
        if n.value >= 0.4 and t.value <= 1:
            out.append(
                AnomalyCandidate(
                    "pair",
                    ["physical", "social"],
                    "emotion_without_suspension",
                    prov,
                    hour,
                    score=n.value,
                    baseline=t.value,
                    threshold=0.4,
                    explanation="社会—物理：负面情绪升高但停运影响仍低，需结合预报性讨论解释。",
                    evidences=[{"evidence_type": "relation", "summary": f"neg={n.value}, trains={t.value}"}],
                    group_key=f"pair:sp:{prov}:{hour.isoformat()}",
                    available_at=_avail([n, t]),
                    task="pair_social_physical",
                )
            )
        if t.value >= 5 and n.value >= 0.45:
            score = n.value * (t.value / 5.0)
            if score >= imb:
                out.append(
                    AnomalyCandidate(
                        "pair",
                        ["physical", "social"],
                        "emotion_suspension_co_move",
                        prov,
                        hour,
                        score=score,
                        threshold=imb,
                        explanation="社会—物理：停运影响与公众负面情绪同步偏高。",
                        evidences=[{"evidence_type": "relation", "summary": f"neg={n.value}, trains={t.value}"}],
                        group_key=f"pair:sp2:{prov}:{hour.isoformat()}",
                        available_at=_avail([n, t]),
                        task="pair_social_physical",
                    )
                )
    return out


def detect_org_physical(org: list[MetricPoint], physical: list[MetricPoint], rules: dict[str, Any]) -> list[AnomalyCandidate]:
    """Lagged relation: needs the window after the impact hour, so the result matures only after that window."""
    pair_cfg = rules.get("pair", {})
    min_cov = float(pair_cfg.get("min_coverage", 0.5))
    lag_op = int(pair_cfg.get("org_physical", {}).get("official_vs_suspension_lag_hours", 4))
    trains = _index(physical, "affected_trains")
    off = _by_province([p for p in org if p.metric_id == "official_weibo_count"])
    out: list[AnomalyCandidate] = []
    for (prov, hour), t in trains.items():
        if t.value is None or t.value < 6 or prov not in off:
            continue
        hi = hour + timedelta(hours=lag_op)
        win = [p for p in off[prov] if hour <= p.hour_bj <= hi and p.value is not None]
        if len(win) / (lag_op + 1) < min_cov:
            continue
        official_after = float(sum(p.value for p in win))  # type: ignore[misc]
        if official_after <= 0:
            out.append(
                AnomalyCandidate(
                    "pair",
                    ["organizational", "physical"],
                    "org_physical_response_lag",
                    prov,
                    hour,
                    score=float(t.value),
                    baseline=0.0,
                    threshold=float(lag_op),
                    explanation="组织—物理：停运影响出现后窗口内官方公告偏少（滞后耦合，非失职断言；窗口成熟后才确认）。",
                    evidences=[
                        {
                            "evidence_type": "relation",
                            "summary": f"trains={t.value}, official_after={official_after}, window_end={hi.isoformat()}",
                            "payload": {"window_end": hi.isoformat(), "org_hours_observed": len(win)},
                        }
                    ],
                    group_key=f"pair:op:{prov}:{hour.isoformat()}",
                    available_at=_avail([t, *win], floor=hi + timedelta(hours=1)),
                    requires_future_window=True,
                    task="pair_org_physical",
                )
            )
    return out


def detect_pairs(
    social: list[MetricPoint],
    org: list[MetricPoint],
    physical: list[MetricPoint],
    rules: dict[str, Any],
) -> list[AnomalyCandidate]:
    """Run only the pair relations whose two dimensions both have observations."""
    out: list[AnomalyCandidate] = []
    if social and org:
        out.extend(detect_social_org(social, org, rules))
    if social and physical:
        out.extend(detect_social_physical(social, physical, rules))
    if org and physical:
        out.extend(detect_org_physical(org, physical, rules))
    return out


def detect_joint(
    social: list[MetricPoint],
    org: list[MetricPoint],
    physical: list[MetricPoint],
    rules: dict[str, Any],
) -> list[AnomalyCandidate]:
    """Three-dimension relation. Requires observations in all three dimensions; counts dimensions, not metrics."""
    joint_cfg = rules.get("joint", {})
    thr = float(joint_cfg.get("score_threshold", 3.0))
    imbalance = bool(joint_cfg.get("imbalance_enabled", True))
    disc = _index(social, "personal_weibo_count")
    neg = _index(social, "negative_ratio")
    off = _index(org, "official_weibo_count")
    trains = _index(physical, "affected_trains")
    out: list[AnomalyCandidate] = []

    def val(idx: dict, key) -> float | None:
        p = idx.get(key)
        return None if p is None else p.value

    for key in (set(disc) | set(neg)) & set(off) & set(trains):
        d, n, o, t = val(disc, key), val(neg, key), val(off, key), val(trains, key)
        if (d is None and n is None) or o is None or t is None:
            continue
        signal = {
            "social": (d is not None and d >= 8) or (n is not None and n >= 0.4),
            "organizational": o >= 3,
            "physical": t >= 6,
        }
        active = [k for k in DIMENSIONS if signal[k]]
        prov, hour = key
        inputs = [disc.get(key), neg.get(key), off.get(key), trains.get(key)]
        summary = f"discussion={d}, neg={n}, official={o}, trains={t}, active_dimensions={len(active)}/3"
        if len(active) == 3 and float(len(active)) >= thr:
            out.append(
                AnomalyCandidate(
                    "joint",
                    list(DIMENSIONS),
                    "triple_co_movement",
                    prov,
                    hour,
                    score=float(len(active)),
                    threshold=thr,
                    explanation="三维联合：社会反应、组织发布与交通影响三个维度同时偏高。",
                    evidences=[{"evidence_type": "joint", "summary": summary, "payload": {"active": active}}],
                    group_key=f"joint:{prov}:{hour.isoformat()}",
                    available_at=_avail(inputs),
                    task="joint",
                )
            )
        elif imbalance and len(active) == 2:
            quiet = next(k for k in DIMENSIONS if not signal[k])
            label = {"social": "社会", "organizational": "组织", "physical": "物理"}
            out.append(
                AnomalyCandidate(
                    "joint",
                    list(DIMENSIONS),
                    "triple_imbalance",
                    prov,
                    hour,
                    score=2.0,
                    threshold=thr,
                    explanation=(
                        f"三维关系失衡：{'、'.join(label[a] for a in active)}偏高而{label[quiet]}未同步，"
                        "三维均有观测；不是三维同步。"
                    ),
                    evidences=[
                        {"evidence_type": "joint", "summary": summary, "payload": {"active": active, "quiet": quiet}}
                    ],
                    group_key=f"joint:imb:{prov}:{hour.isoformat()}",
                    available_at=_avail(inputs),
                    task="joint",
                )
            )
    return out


def run_all_detectors(points_by_dim: dict[str, list[MetricPoint]], rules: dict[str, Any]) -> list[AnomalyCandidate]:
    social = points_by_dim.get("social", [])
    org = points_by_dim.get("organizational", [])
    physical = points_by_dim.get("physical", [])
    results: list[AnomalyCandidate] = []
    results.extend(detect_single_social(social, rules, rules.get("version", "rules-v1")))
    results.extend(detect_single_org(org, rules))
    results.extend(detect_single_physical(physical, rules))
    results.extend(detect_pairs(social, org, physical, rules))
    if social and org and physical:
        results.extend(detect_joint(social, org, physical, rules))
    return results


def summarize_tasks(
    points_by_dim: dict[str, list[MetricPoint]],
    candidates: list[AnomalyCandidate],
    min_samples: int = 6,
) -> dict[str, dict[str, str]]:
    """Per task and province: anomaly | normal | insufficient (with the missing dimension named)."""
    covered: dict[str, set[str]] = {}
    for dim in DIMENSIONS:
        provs = {p.province_code for p in points_by_dim.get(dim, []) if p.value is not None}
        if dim == "social":
            provs = {
                p.province_code
                for p in points_by_dim.get(dim, [])
                if p.value is not None and (p.metric_id != "negative_ratio" or (p.sample_size or 0) >= min_samples)
            }
        covered[dim] = provs
    provinces = sorted(set().union(*covered.values()) | {c.province_code for c in candidates})
    hit = {(c.task, c.province_code) for c in candidates}
    tasks: dict[str, tuple[str, ...]] = {
        "single_social": ("social",),
        "single_org": ("organizational",),
        "single_physical": ("physical",),
        **PAIR_TASKS,
        "joint": DIMENSIONS,
    }
    label = {"social": "社会", "organizational": "组织", "physical": "物理"}
    report: dict[str, dict[str, str]] = {}
    for task, dims in tasks.items():
        row: dict[str, str] = {}
        for prov in provinces:
            missing = [d for d in dims if prov not in covered[d]]
            if (task, prov) in hit:
                row[prov] = "anomaly"
            elif missing:
                row[prov] = "insufficient:" + "、".join(label[m] for m in missing) + "缺测"
            else:
                row[prov] = "normal"
        report[task] = row
    return report
