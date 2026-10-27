"""API-oriented tests that do not require MySQL (pure helpers / import precheck)."""

from pathlib import Path

from app.services.export_service import _csv_safe
from app.services.import_service import precheck_file


def test_csv_formula_injection_guard():
    assert _csv_safe("=1+1").startswith("'")
    assert _csv_safe("normal") == "normal"


def test_precheck_template():
    path = Path(__file__).resolve().parents[1] / "data" / "templates" / "weibo_template.csv"
    report = precheck_file(path, "weibo")
    assert report["ok"] is True
    assert report["rows"] >= 2
