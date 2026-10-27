"""Domain-level acceptance cases (prompt §5, cases 1, 2, 3, 4, 5, 6)."""

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from app.domain.anomaly_rules import (
    MetricPoint,
    detect_joint,
    detect_single_org,
    run_all_detectors,
    summarize_tasks,
)
from app.domain.prediction import (
    FEATURE_NAMES,
    build_feature_vector,
    feature_contract,
    naive_baseline,
    select_forecast_features,
)
from app.domain.train_mapping import Stop, SuspensionInput, map_suspension

T0 = datetime(2023, 7, 26, 0, 0, 0)


def _rules():
    path = Path(__file__).resolve().parents[1] / "config" / "rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pts(metric, province, values, start=T0, samples=20, step=1, avail_delay=None):
    out = []
    for i, v in enumerate(values):
        hour = start + timedelta(hours=i * step)
        out.append(
            MetricPoint(
                province,
                hour,
                metric,
                v,
                sample_size=samples,
                available_at=None if avail_delay is None else hour + avail_delay,
            )
        )
    return out


# Case 1 ---------------------------------------------------------------------


def test_case1_social_only_keeps_social_anomaly():
    social = _pts("negative_ratio", "FJ", [0.1] * 12 + [0.8] * 3) + _pts("personal_weibo_count", "FJ", [3] * 15)
    cands = run_all_detectors({"social": social, "organizational": [], "physical": []}, _rules())
    assert any(c.analysis_scope == "single" and c.dimensions == ["social"] for c in cands)
    assert not any("organizational" in c.dimensions for c in cands)


def test_case1_org_missing_emits_no_org_relation():
    social = _pts("personal_weibo_count", "JS", [2] * 10 + [15] * 5) + _pts("negative_ratio", "JS", [0.1] * 10 + [0.6] * 5)
    phys = _pts("affected_trains", "JS", [1] * 10 + [9] * 5)
    cands = run_all_detectors({"social": social, "organizational": [], "physical": phys}, _rules())
    assert not any("organizational" in c.dimensions for c in cands)
    tasks = summarize_tasks({"social": social, "organizational": [], "physical": phys}, cands)
    assert tasks["pair_social_org"]["JS"].startswith("insufficient")
    assert tasks["joint"]["JS"].startswith("insufficient")


# Case 2 ---------------------------------------------------------------------


def test_case2_two_active_dimensions_is_imbalance_not_triple():
    social = _pts("personal_weibo_count", "FJ", [10]) + _pts("negative_ratio", "FJ", [0.5])
    org = _pts("official_weibo_count", "FJ", [4])
    phys = _pts("affected_trains", "FJ", [0])
    cands = detect_joint(social, org, phys, _rules())
    types = {c.anomaly_type for c in cands}
    assert "triple_co_movement" not in types
    assert "triple_imbalance" in types
    imb = next(c for c in cands if c.anomaly_type == "triple_imbalance")
    assert imb.evidences[0]["payload"]["quiet"] == "physical"


def test_case2_joint_needs_all_three_dimensions():
    social = _pts("personal_weibo_count", "FJ", [10] * 15) + _pts("negative_ratio", "FJ", [0.5] * 15)
    org = _pts("official_weibo_count", "FJ", [4] * 15)
    cands = run_all_detectors({"social": social, "organizational": org, "physical": []}, _rules())
    assert not any(c.analysis_scope == "joint" for c in cands)


# Case 3 ---------------------------------------------------------------------


def test_case3_candidate_available_at_is_latest_input_and_unknown_propagates():
    delay = timedelta(minutes=70)
    social = _pts("negative_ratio", "FJ", [0.1] * 12 + [0.8] * 3, avail_delay=delay)
    social += _pts("personal_weibo_count", "FJ", [3] * 15, avail_delay=delay)
    cands = [c for c in run_all_detectors({"social": social}, _rules()) if c.anomaly_type == "negative_ratio_spike"]
    assert cands and all(c.available_at == c.hour_bj + delay for c in cands)

    unknown = _pts("negative_ratio", "FJ", [0.1] * 12 + [0.8] * 3)
    cands = [c for c in run_all_detectors({"social": unknown}, _rules()) if c.anomaly_type == "negative_ratio_spike"]
    assert cands and all(c.available_at is None for c in cands)


def test_case3_lagged_relation_waits_for_future_window():
    delay = timedelta(minutes=5)
    org = _pts("official_weibo_count", "ZJ", [0] * 12, avail_delay=delay)
    phys = _pts("affected_trains", "ZJ", [0] * 4 + [9] + [0] * 7, avail_delay=delay)
    cands = [
        c
        for c in run_all_detectors({"organizational": org, "physical": phys}, _rules())
        if c.anomaly_type == "org_physical_response_lag"
    ]
    assert cands
    lag = int(_rules()["pair"]["org_physical"]["official_vs_suspension_lag_hours"])
    for c in cands:
        assert c.requires_future_window
        assert c.available_at >= c.hour_bj + timedelta(hours=lag + 1)


# Case 4 ---------------------------------------------------------------------


def test_case4_baseline_window_is_time_based():
    # Sparse points 20h apart: a 12h real-time window holds no history, so no baseline and no anomaly.
    org = _pts("official_weibo_count", "FJ", [3] * 12 + [20], step=20)
    assert not detect_single_org(org, _rules())


def test_case4_missing_hours_are_not_zero_publication():
    base = [3.0] * 12
    gaps = _pts("official_weibo_count", "FJ", base) + [
        MetricPoint("FJ", T0 + timedelta(hours=h), "official_weibo_count", 0.0, 20) for h in (12, 14, 16, 18, 20)
    ]
    assert not any(c.anomaly_type == "official_publish_gap" for c in detect_single_org(gaps, _rules()))

    consecutive = _pts("official_weibo_count", "FJ", base + [0.0] * 6)
    assert any(c.anomaly_type == "official_publish_gap" for c in detect_single_org(consecutive, _rules()))


# Case 5 ---------------------------------------------------------------------


def test_case5_feature_vector_follows_contract():
    origin = T0 + timedelta(hours=12)
    series = {origin - timedelta(hours=i): float(i) for i in range(1, 13)}
    vec = build_feature_vector(series, origin, [], "FJ", 3)
    assert len(vec) == len(FEATURE_NAMES) == len(feature_contract()["names"])
    future = dict(series)
    future[origin + timedelta(hours=1)] = 999.0
    assert build_feature_vector(future, origin, [], "FJ", 3) == vec


def test_case5_forecast_selection_respects_arrival_and_region():
    origin = T0 + timedelta(hours=12)
    late = {"issued_at": origin - timedelta(hours=1), "arrived_at": origin + timedelta(minutes=5), "valid_time": origin + timedelta(hours=3), "metric": "max_wind", "value": 40.0}
    other = {"issued_at": origin - timedelta(hours=2), "arrived_at": origin - timedelta(hours=1), "valid_time": origin + timedelta(hours=3), "metric": "max_wind", "value": 30.0, "province_code": "GD"}
    ok = {"issued_at": origin - timedelta(hours=3), "arrived_at": origin - timedelta(hours=2), "valid_time": origin + timedelta(hours=3), "metric": "max_wind", "value": 25.0}
    feats = select_forecast_features([late, other, ok], origin, "FJ", 3)
    assert feats["forecast_wind"] == 25.0
    assert select_forecast_features([other], origin, "GD", 3)["forecast_wind"] == 30.0


def test_case5_naive_baseline_uses_newest_hours():
    assert naive_baseline(list(range(1, 13))) == 3.5


# Case 6 ---------------------------------------------------------------------

STOPS = [
    Stop("T1", 1, "南京", "JS", "22:10", "22:10"),
    Stop("T1", 2, "上海", "SH", "01:20", "01:20"),
    Stop("T1", 3, "杭州", "ZJ", "03:40", "03:40"),
]


def test_case6_partial_segment_after_midnight_lands_next_day():
    r = map_suspension(SuspensionInput(1, "T1", T0, "上海", "杭州"), STOPS)
    assert r.status == "mapped"
    assert {(h.province_code, h.hour_bj) for h in r.hits} == {
        ("SH", datetime(2023, 7, 27, 1)),
        ("ZJ", datetime(2023, 7, 27, 3)),
    }
    assert all(h.run_key == "T1|2023-07-26" for h in r.hits)
    assert sorted(s for h in r.hits for s in h.stations) == ["上海", "杭州"]


def test_case6_unknown_endpoint_goes_to_review():
    r = map_suspension(SuspensionInput(1, "T1", T0, "苏州", "杭州"), STOPS)
    assert r.status == "pending_review" and r.reason == "segment_start_unmatched" and not r.hits


def test_case6_timetable_versions_are_not_mixed():
    summer = [
        Stop("T2", 1, "福州", "FJ", "08:00", "08:00", "summer", datetime(2023, 7, 1), datetime(2023, 7, 31)),
        Stop("T2", 2, "厦门", "FJ", "10:00", "10:00", "summer", datetime(2023, 7, 1), datetime(2023, 7, 31)),
    ]
    autumn = [
        Stop("T2", 1, "福州", "FJ", "09:00", "09:00", "autumn", datetime(2023, 8, 1), datetime(2023, 9, 30)),
        Stop("T2", 2, "厦门", "FJ", "12:30", "12:30", "autumn", datetime(2023, 8, 1), datetime(2023, 9, 30)),
    ]
    r = map_suspension(SuspensionInput(1, "T2", datetime(2023, 8, 5), None, None), summer + autumn)
    assert r.timetable_version == "autumn"
    assert {h.hour_bj.hour for h in r.hits} == {9, 12}

    undated = [Stop(s.train_code, s.stop_order, s.station_name, s.province_code, s.arrive_time, s.depart_time, v) for s, v in ((summer[0], "a"), (summer[1], "a"), (autumn[0], "b"), (autumn[1], "b"))]
    r = map_suspension(SuspensionInput(1, "T2", datetime(2023, 8, 5), None, None), undated)
    assert r.status == "pending_review" and r.reason == "timetable_version_ambiguous"
