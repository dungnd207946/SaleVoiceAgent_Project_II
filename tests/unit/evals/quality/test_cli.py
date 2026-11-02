"""CLI tests. `list` and `score` need no agent, so both are tested end-to-end
here; `run` is covered by Task 6's runner tests plus the live smoke in Task 9.
"""

from __future__ import annotations

import json
from pathlib import Path

import evals.__main__ as cli
import evals.quality.cases as cases_mod
import pytest
from evals.__main__ import main
from evals.quality.trace import TraceCase, TracedToolCall, TraceHeader, TraceTurn, write_traces


def _stub_cases() -> list[cases_mod.EvalCase]:
    """Schema-v2 stand-ins for the shipped case ids this file scores against.

    Task 13 deleted the real `evals/quality/data/cases/noble/*.jsonl` files
    (the directory now holds only `.gitkeep`), so these stubs exist purely to
    keep this file's CLI tests hermetic and independent of whatever cases a
    tenant happens to have on disk. They carry the same ids/shape the fixtures
    below expect, spanning both `--tag policy` and `--tag tool` so the gates
    below have something non-vacuous to read.
    """
    return [
        cases_mod.parse_case(
            {
                "id": "POL-001",
                "origin": "handwritten",
                "tenant": "noble",
                "channel": "chat",
                "reviewed": True,
                "tags": ["policy"],
                "turns": [{"user": "u", "expect": {"escalated": True}}],
            }
        ),
        cases_mod.parse_case(
            {
                "id": "TOOL-001",
                "origin": "handwritten",
                "tenant": "noble",
                "channel": "chat",
                "reviewed": True,
                "tags": ["tool"],
                "turns": [
                    {
                        "user": "u",
                        "golden": {
                            "tools": [
                                {"name": "recommend_units", "args": {"budget_max": {"equals": 5000000000}}}
                            ]
                        },
                    }
                ],
            }
        ),
        cases_mod.parse_case(
            {
                "id": "TOOL-004",
                "origin": "handwritten",
                "tenant": "noble",
                "channel": "chat",
                "reviewed": True,
                "tags": ["tool"],
                "turns": [
                    {
                        "user": "u",
                        "golden": {"tools": [{"name": "find_project"}], "banned_tools": ["get_document"]},
                    }
                ],
            }
        ),
    ]


@pytest.fixture(autouse=True)
def _stub_case_dir(monkeypatch):
    """Every test in this file selects from the fabricated cases above, not real
    shipped data — Task 13 deleted the shipped `noble` case files outright, so
    this stub is what keeps the file hermetic. A test that needs its own
    selection (e.g. the mixed-channel one) overrides this with its own
    `monkeypatch.setattr(cli, "load_case_dir", ...)`.
    """
    monkeypatch.setattr(cli, "load_case_dir", lambda _d: _stub_cases())


def test_list_prints_shipped_cases_and_exits_zero(capsys, monkeypatch):
    # `load_repo_dotenv` is monkeypatched so the developer's repo-root `.env` is
    # NOT injected into the pytest process — leaking it here would make the
    # whole suite non-hermetic and order-dependent.
    monkeypatch.setattr(cli, "load_repo_dotenv", lambda: None)
    code = main(["list"])
    out = capsys.readouterr().out
    assert code == 0
    assert "POL-001" in out
    assert "TOOL-001" in out


def _clean_traces() -> list[TraceCase]:
    """One clean trace per case in `_CLEAN_SELECTION`.

    The selection deliberately spans BOTH tags: since C2, a gated metric whose
    sample is empty reports `missing` and FAILs, so a policy-only selection can
    no longer PASS. POL-001 feeds `policy_violations`, TOOL-001 feeds
    `arg_accuracy`, TOOL-004 feeds `banned_call_rate`, and any traced turn
    feeds `loop_exhaustion_rate`.
    """
    return [
        TraceCase(
            case_id="POL-001",
            tags=("policy",),
            tenant="noble",
            channel="chat",
            reviewed=True,
            turns=(
                TraceTurn(
                    total_ms=1200.0,  # run thật luôn có timing; gate loại 2 turn_total_p95_ms đọc nó
                    user="u",
                    reply="em chuyển chuyên viên ngay nhé",
                    tool_calls=(TracedToolCall("escalate", {}, "{}"),),
                    customer_after={},
                ),
            ),
        ),
        TraceCase(
            case_id="TOOL-001",
            tags=("tool",),
            tenant="noble",
            channel="chat",
            reviewed=True,
            turns=(
                TraceTurn(
                    total_ms=1200.0,  # run thật luôn có timing; gate loại 2 turn_total_p95_ms đọc nó
                    user="u",
                    reply="em gợi ý vài căn nhé",
                    tool_calls=(TracedToolCall("recommend_units", {"budget_max": 5000000000}, "[]"),),
                    customer_after={},
                ),
            ),
        ),
        TraceCase(
            case_id="TOOL-004",
            tags=("tool",),
            tenant="noble",
            channel="chat",
            reviewed=True,
            turns=(
                TraceTurn(
                    total_ms=1200.0,  # run thật luôn có timing; gate loại 2 turn_total_p95_ms đọc nó
                    user="u",
                    reply="tiện ích gồm bể bơi và gym",
                    tool_calls=(TracedToolCall("find_project", {"name": "Alluvia"}, "{}"),),
                    customer_after={},
                ),
            ),
        ),
    ]


_CLEAN_SELECTION = "POL-001,TOOL-001,TOOL-004"


def test_score_passes_on_a_clean_trace(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "append_entry", lambda entry: None)
    run_dir = tmp_path / "20260817-000000"
    traces = run_dir / "traces.jsonl"
    write_traces(
        traces, TraceHeader("20260817-000000", "2026-08-17T00:00:00+00:00", {"git_sha": "abc"}), _clean_traces()
    )

    code = main(["score", "--run-dir", str(run_dir), "--case", _CLEAN_SELECTION])
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out
    assert (run_dir / "scorecard.md").exists()
    md = (run_dir / "scorecard.md").read_text(encoding="utf-8")
    # A clean run produces no findings, so no case id appears anywhere — case ids only
    # ever render inside the Findings table. What MUST appear is the coverage the
    # verdict rests on, so that "PASS" over one case cannot read like a full-suite PASS.
    assert "cases_scored" in md
    assert "case_filter" in md
    assert "Không có finding nào" in md
    assert "policy" in md


def test_score_fails_and_exits_one_when_a_gate_breaks(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "append_entry", lambda entry: None)
    run_dir = tmp_path / "r"
    bad = [
        TraceCase(
            case_id="POL-001",
            tags=("policy",),
            tenant="noble",
            channel="chat",
            reviewed=True,
            turns=(TraceTurn(user="u", reply="dạ em không rõ ạ", tool_calls=(), customer_after={}),),
        )
    ]
    write_traces(run_dir / "traces.jsonl", TraceHeader("r", "t", {}), bad)

    code = main(["score", "--run-dir", str(run_dir), "--case", "POL-001"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out


def test_score_writes_machine_readable_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "append_entry", lambda entry: None)
    run_dir = tmp_path / "r"
    write_traces(run_dir / "traces.jsonl", TraceHeader("r", "t", {}), _clean_traces())
    main(["score", "--run-dir", str(run_dir), "--case", _CLEAN_SELECTION])
    data = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert "policy_violations" in data["metrics"]
    assert data["gates"]
    # Coverage must be machine-readable too, not just in the Markdown report — a
    # consumer scripting against scores.json needs the same "how much did this
    # actually cover" guarantee that the --case/--tag narrowing implies.
    assert data["config"]["cases_scored"] == 3
    assert "POL-001" in data["config"]["case_filter"]
    # `cases_scored` is the selection size; `cases_gated` is the reviewed-only count
    # that can actually move a gate. Both must be machine-readable (I4).
    assert data["metrics"]["cases_gated"] == 3
    assert data["metrics"]["cases_errored"] == 0
    assert data["metrics"]["cases_missing_trace"] == 0


def test_score_appends_registry(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr("evals.__main__.append_entry", lambda e: captured.append(e))
    run_dir = tmp_path / "r"
    write_traces(run_dir / "traces.jsonl", TraceHeader("r", "t", {}), _clean_traces())

    code = main(["score", "--run-dir", str(run_dir), "--case", _CLEAN_SELECTION])

    assert code == 0
    assert len(captured) == 1
    assert captured[0].kind == "quality"
    assert captured[0].verdict in {"pass", "fail", "error"}


def test_score_on_missing_run_dir_exits_one(tmp_path, capsys):
    code = main(["score", "--run-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "not found" in capsys.readouterr().out.lower()


def _write_violating_trace(run_dir: Path) -> None:
    """A trace that PROVES a policy violation: POL-001 expects `escalated`, this
    reply escalates nothing. Any scoring of it must FAIL."""
    write_traces(
        run_dir / "traces.jsonl",
        TraceHeader("r", "t", {}),
        [
            TraceCase(
                case_id="POL-001",
                tags=("policy",),
                tenant="noble",
                channel="chat",
                reviewed=True,
                turns=(TraceTurn(user="u", reply="dạ em không rõ ạ", tool_calls=(), customer_after={}),),
            )
        ],
    )


def test_score_with_an_empty_case_selection_fails_instead_of_certifying(tmp_path, capsys):
    """C1 regression. A typo in `--tag` (or a `--tenant` whose directory holds no
    matching case) used to select ZERO cases; every scorer then produced its
    vacuous value, every gate rendered ✓ and the CLI printed PASS / exit 0 —
    certifying a trace that contains a proven violation. Selecting nothing is
    never evidence of anything, so it must be a loud non-zero exit.
    """
    run_dir = tmp_path / "r"
    _write_violating_trace(run_dir)

    code = main(["score", "--run-dir", str(run_dir), "--tag", "bogus_tag"])
    out = capsys.readouterr().out

    assert code == 1
    assert "no cases selected" in out.lower()
    assert "PASS" not in out


def test_score_with_an_unmatched_case_id_fails(tmp_path, capsys):
    run_dir = tmp_path / "r"
    _write_violating_trace(run_dir)
    code = main(["score", "--run-dir", str(run_dir), "--case", "NO-SUCH-CASE"])
    assert code == 1
    assert "no cases selected" in capsys.readouterr().out.lower()


def test_run_with_an_empty_case_selection_exits_one_before_touching_the_agent(capsys):
    """`run`'s own guard — it must refuse before spending an LLM budget or probing
    Redis. Hermetic: the guard fires before preflight and before any agent is
    built, so no Redis/LLM key is needed.
    """
    code = main(["run", "--case", "NO-SUCH-CASE"])
    assert code == 1
    assert "no cases selected" in capsys.readouterr().out.lower()


def test_score_of_a_policy_only_selection_fails_the_tool_arg_gate_as_missing(tmp_path, capsys, monkeypatch):
    """C2 regression, end to end. `--tag policy` produces no `tool_arg`
    assertions, so `arg_accuracy` measured NOTHING. It used to render `1` (its
    vacuous pass value) and the gate that exists to catch a 1e9 price-unit error
    read green. It must now render `missing` and FAIL.
    """
    monkeypatch.setattr(cli, "append_entry", lambda entry: None)
    run_dir = tmp_path / "r"
    # A clean policy trace: POL-001 escalates as expected → zero policy violations.
    write_traces(
        run_dir / "traces.jsonl",
        TraceHeader("r", "t", {}),
        [
            TraceCase(
                case_id="POL-001",
                tags=("policy",),
                tenant="noble",
                channel="chat",
                reviewed=True,
                turns=(
                    TraceTurn(
                        user="u",
                        reply="em chuyển chuyên viên ngay nhé",
                        tool_calls=(TracedToolCall("escalate", {}, "{}"),),
                        customer_after={},
                    ),
                ),
            )
        ],
    )

    code = main(["score", "--run-dir", str(run_dir), "--case", "POL-001"])
    out = capsys.readouterr().out

    assert code == 1
    assert "gate arg_accuracy = missing" in out
    data = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    assert data["metrics"]["arg_accuracy"] is None
    assert data["ok"] is False


def test_score_refuses_a_mixed_channel_selection(tmp_path, capsys, monkeypatch):
    """I6. Spec §4.1: "Scorecard tách số theo channel, KHÔNG gộp." Real
    per-channel scoring is P1; until then a mixed selection must be refused
    rather than blended into one gated number that could mask a voice-only
    regression.
    """
    run_dir = tmp_path / "r"
    _write_violating_trace(run_dir)

    chat = cases_mod.parse_case(
        {
            "id": "POL-001",
            "tags": ["policy"],
            "origin": "handwritten",
            "tenant": "noble",
            "channel": "chat",
            "reviewed": True,
            "turns": [{"user": "u", "expect": {"escalated": True}}],
        }
    )
    voice = cases_mod.parse_case(
        {
            "id": "POL-002",
            "tags": ["policy"],
            "origin": "handwritten",
            "tenant": "noble",
            "channel": "voice",
            "reviewed": True,
            "turns": [{"user": "u", "expect": {"escalated": True}}],
        }
    )
    monkeypatch.setattr(cli, "load_case_dir", lambda _d: [chat, voice])

    code = main(["score", "--run-dir", str(run_dir)])
    out = capsys.readouterr().out

    assert code == 1
    assert "chat" in out and "voice" in out
    assert "PASS" not in out


def test_main_loads_dotenv_before_dispatching_any_subcommand(monkeypatch):
    """`RUN` needs `os.environ["REDIS_URL"]` set (storage/redis_client.py reads
    it directly), so `.env` must be loaded before any subcommand — including
    `list`/`score`, which are cheap to call here — ever runs. This is the
    narrow, hermetic slice of the contract: order, not file contents (the file
    contents themselves are `evals.common.load_repo_dotenv`'s own tests).
    """
    order: list[str] = []
    monkeypatch.setattr(cli, "load_repo_dotenv", lambda: order.append("dotenv"))
    monkeypatch.setattr(cli, "_cmd_list", lambda args: order.append("dispatch") or 0)

    code = cli.main(["list"])

    assert order == ["dotenv", "dispatch"]
    assert code == 0


def test_run_as_tenant_drives_cases_under_the_override_tenant(tmp_path, monkeypatch):
    """`--as-tenant X` chạy bộ case của thư mục `--tenant` dưới tenant X: mỗi case tới
    `run_case` mang `tenant == X`, và preflight credential xin key cho X (không phải
    tenant ghi trong file). Dùng khi key/dữ liệu ở tenant sao chép (`aina_test`) mà
    case được viết cho tenant gốc (`aina_prod`).
    """
    import evals.preflight as preflight
    import evals.quality.runner as runner
    import evals.tenant_creds as tenant_creds

    monkeypatch.setattr(cli, "load_repo_dotenv", lambda: None)
    monkeypatch.setattr(cli, "_RUNS", tmp_path)

    async def _no_redis_error():
        return None

    monkeypatch.setattr(preflight, "check_redis", _no_redis_error)
    monkeypatch.setattr(tenant_creds, "configured", lambda: True)
    ensured: list[str] = []

    async def _ensure(tenant_id: str) -> bool:
        ensured.append(tenant_id)
        return False

    monkeypatch.setattr(tenant_creds, "ensure", _ensure)
    driven: list[str] = []

    async def _run_case(case, *, run_id):
        driven.append(case.tenant)
        return TraceCase(
            case_id=case.id,
            tags=case.tags,
            tenant=case.tenant,
            channel=case.channel,
            reviewed=case.reviewed,
            error=None,
            pinned_version=None,
            temperature=0.7,
            turns=[],
        )

    monkeypatch.setattr(runner, "run_case", _run_case)
    monkeypatch.setattr(runner, "build_config_header", lambda: {})

    code = main(["run", "--tenant", "noble", "--case", "TOOL-001", "--as-tenant", "aina_test", "--no-score"])

    assert code == 0
    assert driven == ["aina_test"]
    assert ensured == ["aina_test", "aina_test"]  # preflight + trước mỗi case
