"""Guard the shipped case files: they must parse, be unique, and cover the smoke set."""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.quality.cases import load_case_dir

_CASES_ROOT = Path(__file__).resolve().parents[4] / "evals" / "quality" / "data" / "cases"

pytestmark = pytest.mark.skipif(not _CASES_ROOT.is_dir(), reason="case data ported in a later task")


def _tenant_dirs_with_data() -> list[Path]:
    # `noble/` currently ships no `*.jsonl` (it's kept as an empty directory only
    # so `evals.__main__`'s tenant `is_dir()` check has somewhere to point — the
    # CLI's own tests stub the case loader itself). Only dirs that actually ship
    # data are in scope for the "parses + unique ids" guarantee below.
    dirs = sorted(p for p in _CASES_ROOT.iterdir() if p.is_dir() and any(p.glob("*.jsonl")))
    assert dirs, f"no tenant ships any case data under {_CASES_ROOT}"
    return dirs


def test_every_shipped_jsonl_parses_and_ids_are_unique():
    # load_case_dir already raises on a parse error or a duplicate id within a
    # single tenant directory (schema v2, evals/quality/cases.py) — walking every
    # data-shipping tenant dir here means a broken file anywhere fails this test
    # loudly instead of silently dropping cases from the scorecard.
    for case_dir in _tenant_dirs_with_data():
        cases = load_case_dir(case_dir)
        assert cases, f"{case_dir} ships no cases"


def test_du_test_smoke_set_has_pol_tool_qa():
    # Makefile's `eval-quality-smoke` target pins this exact id set — if any of
    # them goes missing the smoke target silently runs on fewer cases than it
    # claims to.
    du_test_dir = _CASES_ROOT / "du_test"
    ids = {c.id for c in load_case_dir(du_test_dir)}
    for expected in ("POL-001", "TOOL-001", "QA-001"):
        assert expected in ids, f"{expected} missing from {du_test_dir}"
