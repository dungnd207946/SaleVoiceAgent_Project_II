import json

import pytest
from evals.labeller import server


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    cases = tmp_path / "cases" / "du_test"
    golden = tmp_path / "golden" / "du_test"
    cases.mkdir(parents=True)
    golden.mkdir(parents=True)
    monkeypatch.setattr(server, "ROOTS", {"cases": tmp_path / "cases", "golden": tmp_path / "golden"})
    return cases, golden


_CASE = {"id": "QA-001", "tenant": "du_test", "origin": "handwritten", "reviewed": False,
         "tags": ["qa"], "channel": "chat", "turns": [{"user": "u", "golden": {"answer": "a"}}]}
_GOLD = {"id": "g1", "tenant": "du_test", "query": "q", "status": "draft",
         "golden_chunks": [{"chunk_id": "c1", "evidence": "e"}], "answer": "a"}


def test_roundtrip_cases(roots):
    cases_dir, _ = roots
    (cases_dir / "a.jsonl").write_text(json.dumps(_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    tree = server.list_tree()
    assert tree["cases"][0]["file"] == "a.jsonl"
    out = server.read_file("cases", "du_test/a.jsonl")
    assert out["lines"][0]["data"]["id"] == "QA-001" and out["lines"][0]["error"] == ""
    server.write_file("cases", "du_test/a.jsonl", [dict(_CASE, reviewed=True)])
    out2 = server.read_file("cases", "du_test/a.jsonl")
    assert out2["lines"][0]["data"]["reviewed"] is True


def test_golden_draft_editable(roots):
    server.write_file("golden", "du_test/d.jsonl", [_GOLD])  # draft PHẢI ghi được (labeller sửa draft)
    assert server.read_file("golden", "du_test/d.jsonl")["lines"][0]["data"]["status"] == "draft"


def test_invalid_line_blocks_whole_write(roots):
    cases_dir, _ = roots
    (cases_dir / "a.jsonl").write_text(json.dumps(_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    before = (cases_dir / "a.jsonl").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        server.write_file("cases", "du_test/a.jsonl", [_CASE, {"id": "X", "thiếu": "hết"}])
    assert (cases_dir / "a.jsonl").read_text(encoding="utf-8") == before  # không ghi gì


def test_read_reports_bad_line_without_crashing(roots):
    cases_dir, _ = roots
    (cases_dir / "a.jsonl").write_text(
        json.dumps(_CASE, ensure_ascii=False) + "\n" + '{"id": "B", "hỏng": 1}\n', encoding="utf-8")
    out = server.read_file("cases", "du_test/a.jsonl")
    assert out["lines"][0]["error"] == "" and out["lines"][1]["error"] != ""


def test_path_traversal_blocked(roots):
    for bad in ("../../etc/passwd", "du_test/../../x.jsonl", "du_test/a.txt", "/etc/x.jsonl"):
        with pytest.raises(ValueError):
            server.resolve_path("cases", bad)
    with pytest.raises(ValueError):
        server.resolve_path("nope", "du_test/a.jsonl")


def test_tree_recursive_and_lists_empty_dirs(roots):
    cases_dir, _ = roots
    nested = cases_dir / "deep"
    nested.mkdir()
    (nested / "n.jsonl").write_text(json.dumps(_CASE, ensure_ascii=False) + "\n", encoding="utf-8")
    (cases_dir.parent / "empty_tenant").mkdir()  # folder rỗng vẫn phải hiện ra
    tree = server.list_tree()
    paths = [r["path"] for r in tree["cases"]]
    assert "du_test/deep/n.jsonl" in paths
    assert "empty_tenant" in tree["dirs"]["cases"]
    row = next(r for r in tree["cases"] if r["path"] == "du_test/deep/n.jsonl")
    assert row["tenant"] == "du_test/deep"


def test_make_dir_creates_and_rejects(roots):
    cases_dir, _ = roots
    server.make_dir("cases", "tenant_moi")
    assert (cases_dir.parent / "tenant_moi").is_dir()
    with pytest.raises(ValueError, match="exists"):
        server.make_dir("cases", "tenant_moi")
    for bad in ("../ngoai", "", "/tmp/x", "du_test/../.."):
        with pytest.raises(ValueError):
            server.resolve_dir("cases", bad)
    with pytest.raises(ValueError):
        server.resolve_dir("nope", "x")
