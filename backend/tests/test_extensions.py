"""锁定后续增量不能改掉的口径：未知主体、缺站名、分析未接入。"""

from app.attitude import NOT_INTEGRATED, results_payload
from app.geo import count_endpoints, endpoints
from app.subjects import metric_counts, overview_counts


class _Row:
    def __init__(self, origin, destination):
        self.origin = origin
        self.destination = destination


class _Post:
    def __init__(self, flag):
        self.is_government = flag


def test_endpoints_pass_through_names():
    assert endpoints(_Row("甲", "乙")) == ("甲", "乙")
    assert endpoints(_Row(None, None)) == (None, None)
    assert count_endpoints([_Row(None, None), _Row("甲", None)]) == ({"甲": 1}, {})


def test_unknown_government_is_not_zero_in_metrics():
    unknown = [(None, _Post(None)), (None, _Post(None))]
    mixed = [(None, _Post(True)), (None, _Post(False)), (None, _Post(None))]
    assert metric_counts([])["weibo_count"] is None
    assert metric_counts(unknown)["government_weibo_count"] is None
    assert metric_counts(unknown)["unclassified_weibo_count"] == 2
    mixed_counts = metric_counts(mixed)
    assert mixed_counts["government_weibo_count"] == 1
    assert mixed_counts["non_government_weibo_count"] == 1
    assert mixed_counts["unclassified_weibo_count"] == 1
    assert overview_counts([]) == {
        "government": 0,
        "non_government": 0,
        "unknown_government": 0,
    }


def test_attitude_stays_unintegrated():
    payload = results_payload({"event_id": 1})
    assert payload["status"] == NOT_INTEGRATED
    assert payload["items"] == []
    assert payload["context"]["event_id"] == 1
