import re

from evals.common import REPORTS_DIR, new_run_id, percentiles_ms


def test_new_run_id_format():
    rid = new_run_id("quality")
    assert re.fullmatch(r"\d{8}-\d{6}-quality-[0-9a-f]{6}", rid)


def test_percentiles_ms_known_values():
    out = percentiles_ms([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0])
    assert out["p50"] == 50.0
    assert out["p95"] == 100.0
    assert out["max"] == 100.0


def test_percentiles_ms_empty():
    assert percentiles_ms([]) == {}


def test_reports_dir_inside_evals():
    assert REPORTS_DIR.name == "reports" and REPORTS_DIR.parent.name == "evals"
