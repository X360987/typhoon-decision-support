from datetime import datetime, timedelta

import yaml
from pathlib import Path

from app.domain.anomaly_rules import MetricPoint, run_all_detectors
from app.domain.geo import attribute_provinces, extract_provinces_from_text
from app.domain.prediction import build_lag_features, clip_prediction, future_window_sum
from app.domain.sentiment import DemoRuleSentiment
from app.domain.stats import robust_z, safe_ratio
from app.domain.train_mapping import Stop, SuspensionInput, map_suspension_to_region_hours


def test_safe_ratio_missing_not_zero():
    assert safe_ratio(None, 10) is None
    assert safe_ratio(1, 0) is None
    assert safe_ratio(2, 4) == 0.5


def test_sentiment_unknown_not_neutral():
    s = DemoRuleSentiment()
    r = s.classify("今天天气一般")
    assert r.label == "unknown"
    r2 = s.classify("福建担心停运求助")
    assert r2.label == "negative"
    assert r2.is_help_request


def test_multi_province_attribution():
    attrs = attribute_provinces("福建和广东都在讨论", None, None)
    codes = [a[0] for a in attrs]
    assert "FJ" in codes and "GD" in codes


def test_unknown_region_not_forced():
    assert attribute_provinces("没有地名", None, "9.9.9.9") == []


def test_cross_midnight_mapping():
    stops = [
        Stop("SIM-K5201", 1, "南京", "JS", "22:10", "22:10"),
        Stop("SIM-K5201", 2, "上海", "SH", "01:20", "01:20"),
        Stop("SIM-K5201", 3, "杭州", "ZJ", "03:40", "03:40"),
    ]
    base = datetime(2023, 7, 26, 0, 0, 0)
    hits = map_suspension_to_region_hours(
        SuspensionInput(1, "SIM-K5201", base, "南京", "杭州"),
        stops,
    )
    provinces = {h.province_code for h in hits}
    assert "JS" in provinces and "SH" in provinces and "ZJ" in provinces
    # Shanghai/Hangzhou should be next calendar day hours
    sh = [h for h in hits if h.province_code == "SH"][0]
    assert sh.hour_bj.day == 27


def test_mad_zero_no_crash():
    z, status = robust_z(5.0, [1.0, 1.0, 1.0, 1.0])
    assert status == "mad_zero"


def test_baseline_no_future():
    origin = datetime(2023, 7, 26, 12, 0, 0)
    series = {
        origin - timedelta(hours=1): 1.0,
        origin: 2.0,
        origin + timedelta(hours=1): 99.0,  # future must not enter features
    }
    feats = build_lag_features(series, origin)
    assert feats["lag_1"] == 1.0
    # origin itself may be included depending on contract; future hour must not
    assert 99.0 not in feats.values()


def test_clip_prediction():
    assert clip_prediction(-1, 0, None) == 0
    assert clip_prediction(1.5, 0, 1) == 1


def test_future_window_sum():
    origin = datetime(2023, 7, 26, 10, 0, 0)
    series = {
        origin + timedelta(hours=1): 2.0,
        origin + timedelta(hours=2): 3.0,
    }
    assert future_window_sum(series, origin, 2) == 5.0


def _rules():
    path = Path(__file__).resolve().parents[1] / "config" / "rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pts(metric, province, start, values, samples=None):
    out = []
    for i, v in enumerate(values):
        out.append(
            MetricPoint(
                province,
                start + timedelta(hours=i),
                metric,
                v,
                sample_size=(samples[i] if samples else 20),
            )
        )
    return out


def test_social_only_anomaly():
    start = datetime(2023, 7, 26, 0, 0, 0)
    # long baseline then spike
    neg = [0.1] * 12 + [0.7] * 3
    disc = [3] * 15
    social = _pts("negative_ratio", "FJ", start, neg) + _pts("personal_weibo_count", "FJ", start, disc)
    org = _pts("official_weibo_count", "FJ", start, [2] * 15)
    phys = _pts("affected_trains", "FJ", start, [1] * 15)
    cands = run_all_detectors({"social": social, "organizational": org, "physical": phys}, _rules())
    social_hits = [c for c in cands if c.analysis_scope == "single" and "social" in c.dimensions]
    assert social_hits
    assert any(c.anomaly_type == "negative_ratio_spike" for c in social_hits)


def test_org_only_and_physical_only():
    start = datetime(2023, 7, 26, 0, 0, 0)
    social = _pts("negative_ratio", "GD", start, [0.1] * 15) + _pts(
        "personal_weibo_count", "GD", start, [2] * 15
    )
    org = _pts("official_weibo_count", "GD", start, [3] * 10 + [0] * 5)
    phys = _pts("affected_trains", "ZJ", start, [1] * 10 + [12] * 5)
    cands = run_all_detectors(
        {
            "social": social,
            "organizational": org + _pts("official_weibo_count", "ZJ", start, [1] * 15),
            "physical": phys + _pts("affected_trains", "GD", start, [1] * 15),
        },
        _rules(),
    )
    assert any(c.anomaly_type in ("official_publish_gap", "official_publish_spike") for c in cands)
    assert any(c.anomaly_type == "suspension_concentration" for c in cands)


def test_missing_dimension_does_not_block():
    start = datetime(2023, 7, 26, 0, 0, 0)
    social = _pts("negative_ratio", "FJ", start, [0.1] * 12 + [0.8] * 3, [20] * 15)
    social += _pts("personal_weibo_count", "FJ", start, [3] * 15)
    cands = run_all_detectors({"social": social, "organizational": [], "physical": []}, _rules())
    assert any(c.analysis_scope == "single" for c in cands)


def test_low_sample_not_anomaly():
    start = datetime(2023, 7, 26, 0, 0, 0)
    social = _pts("negative_ratio", "GD", start, [0.9] * 15, [1] * 15)
    social += _pts("personal_weibo_count", "GD", start, [1] * 15)
    cands = run_all_detectors({"social": social, "organizational": [], "physical": []}, _rules())
    assert not any(c.anomaly_type == "negative_ratio_spike" for c in cands)


def test_pair_and_joint_can_fire():
    start = datetime(2023, 7, 26, 0, 0, 0)
    social = _pts("personal_weibo_count", "JS", start, [2] * 10 + [15] * 5)
    social += _pts("negative_ratio", "JS", start, [0.1] * 10 + [0.5] * 5)
    org = _pts("official_weibo_count", "JS", start, [0] * 15)
    phys = _pts("affected_trains", "JS", start, [1] * 10 + [8] * 5)
    cands = run_all_detectors({"social": social, "organizational": org, "physical": phys}, _rules())
    assert any(c.analysis_scope == "pair" for c in cands)

    social2 = _pts("personal_weibo_count", "FJ", start, [10] * 15)
    social2 += _pts("negative_ratio", "FJ", start, [0.45] * 15)
    org2 = _pts("official_weibo_count", "FJ", start, [4] * 15)
    phys2 = _pts("affected_trains", "FJ", start, [8] * 15)
    cands2 = run_all_detectors({"social": social2, "organizational": org2, "physical": phys2}, _rules())
    assert any(c.analysis_scope == "joint" for c in cands2)
