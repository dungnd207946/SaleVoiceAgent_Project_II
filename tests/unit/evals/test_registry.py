
import pytest
from evals.registry import append_entry, make_entry, read_entries


def test_roundtrip(tmp_path):
    p = tmp_path / "registry.jsonl"
    e = make_entry(run_id="r1", kind="quality", config={"model": "m"},
                   metrics={"x": 1.0}, gates={"g": "pass"}, verdict="pass", report_dir="evals/reports/r1/")
    append_entry(e, path=p)
    append_entry(e, path=p)
    rows = read_entries(p)
    assert len(rows) == 2
    assert rows[0]["run_id"] == "r1" and rows[0]["kind"] == "quality"
    assert rows[0]["ts"] and "git_sha" in rows[0]


def test_bad_verdict_rejected():
    with pytest.raises(ValueError):
        make_entry(run_id="r", kind="quality", config={}, metrics={}, gates={}, verdict="ok", report_dir="")


def test_bad_kind_rejected():
    with pytest.raises(ValueError):
        make_entry(run_id="r", kind="latency", config={}, metrics={}, gates={}, verdict="pass", report_dir="")


def test_read_broken_line_names_lineno(tmp_path):
    p = tmp_path / "registry.jsonl"
    p.write_text('{"run_id": "a"}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        read_entries(p)


def test_read_missing_file_is_empty(tmp_path):
    assert read_entries(tmp_path / "nope.jsonl") == []
