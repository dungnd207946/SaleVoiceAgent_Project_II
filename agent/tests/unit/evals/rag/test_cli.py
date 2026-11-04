"""CLI tests for `python -m evals rag` (`_cmd_rag`)."""

from __future__ import annotations

import evals.__main__ as cli
from evals.__main__ import main


def test_rag_with_an_empty_golden_file_exits_one_before_running_or_recording(tmp_path, capsys, monkeypatch):
    """A whitespace-only golden file loads as `[]` (blank lines are skipped by
    `load_golden`). Mirroring the quality suite's C1 guard ("selecting nothing
    is never evidence"), this must refuse loudly instead of running zero cases,
    computing `empty_rate` over an empty set, and recording a `pass` verdict.
    """
    captured = []
    monkeypatch.setattr(cli, "append_entry", lambda e: captured.append(e))
    golden = tmp_path / "empty.jsonl"
    golden.write_text("   \n\n", encoding="utf-8")

    code = main(["rag", "--golden", str(golden)])
    out = capsys.readouterr().out

    assert code == 1
    assert str(golden) in out
    assert captured == []
