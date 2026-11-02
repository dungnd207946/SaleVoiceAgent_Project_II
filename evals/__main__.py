"""Eval harness CLI.

    python -m evals list
    python -m evals run   [--tenant noble] [--case ID,ID] [--tag policy] [--model M]
    python -m evals score --run-dir evals/reports/<RUN_ID> [--tenant noble] [--case ID,ID] [--tag policy]

`run` needs Redis + an LLM key + a working RAG backend (same prerequisites as
running the agent). `list` and `score` need nothing — scoring reads a trace.

Exit code is non-zero when a gate fails, so it drops into CI unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from evals.common import REPORTS_DIR, load_repo_dotenv, new_run_id
from evals.quality.cases import EvalCase, load_case_dir
from evals.quality.latency import score_latency
from evals.quality.scorecard import build_scorecard, load_thresholds, render_markdown
from evals.quality.scorers.policy import score_policy
from evals.quality.scorers.run_integrity import score_run_integrity
from evals.quality.scorers.style import score_style
from evals.quality.scorers.tool_selection import score_tool_selection
from evals.quality.scorers.trajectory import score_trajectory
from evals.quality.trace import TraceHeader, read_traces, write_traces
from evals.registry import append_entry, make_entry

_HERE = Path(__file__).resolve().parent
_CASES_ROOT = _HERE / "quality" / "data" / "cases"
_THRESHOLDS = _HERE / "quality" / "data" / "thresholds.toml"
_RUNS = REPORTS_DIR

_GREEN, _RED, _DIM, _RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m evals")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("list", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--tenant", default="noble", help="Tenant case directory to load (default: noble)")
        sp.add_argument("--case", default="", help="Comma-separated case ids (default: all)")
        sp.add_argument("--tag", default="", help="Only cases carrying this tag")
        if name == "run":
            sp.add_argument("--model", help="Pin NOBLE_AGENT_MODEL for the run")
            sp.add_argument(
                "--as-tenant", default="",
                help="Chạy bộ case của --tenant dưới tenant khác (vd. case aina_prod trên bản sao aina_test)",
            )
            sp.add_argument("--run-id", default="", help="Override the generated run id")
            sp.add_argument("--no-score", action="store_true", help="Write traces only, skip scoring")
        sp.add_argument(
            "--judge", action="store_true",
            help="Also run the 3 LLM-judge rubrics (correctness/groundedness/multiturn)",
        )
        sp.add_argument("--judge-budget-usd", type=float, default=None, help="Cap $ spent by the judge")

    sp = sub.add_parser("score")
    sp.add_argument("--run-dir", required=True, help="Directory holding traces.jsonl")
    sp.add_argument("--tenant", default="noble")
    sp.add_argument("--case", default="")
    sp.add_argument("--tag", default="", help="Only cases carrying this tag")
    sp.add_argument(
        "--judge", action="store_true",
        help="Also run the 3 LLM-judge rubrics (correctness/groundedness/multiturn)",
    )
    sp.add_argument("--judge-budget-usd", type=float, default=None, help="Cap $ spent by the judge")

    sp = sub.add_parser("rag")
    sp.add_argument("--golden", required=True, help="Đường dẫn file golden JSONL (toàn status approved)")
    sp.add_argument("--tenant", default="noble")
    sp.add_argument("--top-k", type=int, default=5)
    sp.add_argument("--mode", choices=("structured", "agent-string"), default="structured")
    sp.add_argument("--judge", action="store_true", help="Thêm stage generation: faithfulness + answer correctness")
    sp.add_argument("--judge-budget-usd", type=float, default=None)

    sp = sub.add_parser("gen-golden")
    sp.add_argument("--tenant", default="noble")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--per-chunk", type=int, default=2)
    sp.add_argument("--model", default=None, help="Default: evals.rag.golden_gen.default_model()")

    sp = sub.add_parser("bench")
    sp.add_argument("--components", default="stt,tts,speaker,vad,llm")
    sp.add_argument("--runs", type=int, default=10)

    sp = sub.add_parser("load")
    sp.add_argument("--target", choices=("chat", "voice", "service"), default="chat")
    sp.add_argument("--max", type=int, default=64)
    sp.add_argument("--hold", type=float, default=60.0)
    sp.add_argument("--host", default="ws://localhost:8766")
    sp.add_argument("--admission-cap", type=int, default=None)
    sp.add_argument("--component", choices=("stt", "tts", "speaker"), default=None,
                    help="Required when --target service")

    sub.add_parser("report")

    sp = sub.add_parser("labeller")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = share được trong LAN; 127.0.0.1 = chỉ máy này")
    return p.parse_args(argv)


def _select(cases: list[EvalCase], *, ids: str, tag: str) -> list[EvalCase]:
    if ids:
        wanted = {x.strip() for x in ids.split(",") if x.strip()}
        cases = [c for c in cases if c.id in wanted]
    if tag:
        cases = [c for c in cases if tag in c.tags]
    return cases


def _load(tenant: str, ids: str, tag: str) -> list[EvalCase]:
    directory = _CASES_ROOT / tenant
    if not directory.is_dir():
        raise FileNotFoundError(f"case directory not found: {directory}")
    return _select(load_case_dir(directory), ids=ids, tag=tag)


def _cmd_list(args: argparse.Namespace) -> int:
    cases = _load(args.tenant, args.case, args.tag)
    for case in cases:
        flag = "" if case.reviewed else f" {_DIM}(unreviewed — excluded from scorecard){_RESET}"
        tags = ",".join(case.tags) or "-"
        print(f"{case.id:<12} {tags:<13} {case.channel:<6} {len(case.turns)} turn(s){flag}")
    print(f"\n{len(cases)} case(s) in {_CASES_ROOT / args.tenant}")
    return 0


def _reject_empty_selection(cases: list[EvalCase]) -> bool:
    """True when the selection is empty (caller must then return 1).

    Scoring zero cases used to print every gate ✓ and PASS — a typo in
    `--tag`/`--case`, or a `--tenant` whose directory holds no matching case,
    silently certified a trace that proves the opposite. Selecting nothing is
    never evidence of anything.
    """
    if cases:
        return False
    print(f"{_RED}no cases selected — refusing to report a verdict (check --tenant/--case/--tag){_RESET}")
    return True


def _reject_mixed_channels(cases: list[EvalCase]) -> bool:
    """True when the selection spans more than one channel (caller returns 1).

    Spec §4.1: "Scorecard tách số theo channel, **không gộp**." The scorecard has
    no channel dimension yet (real per-channel scoring is P1), so a mixed
    selection would blend chat and voice into one gated number where a
    voice-only regression could hide behind chat's passes. Refuse loudly instead.
    """
    channels = sorted({c.channel for c in cases})
    if len(channels) <= 1:
        return False
    print(
        f"{_RED}mixed-channel selection {channels} — the scorecard does not split by channel yet, "
        f"so scoring them together could mask a single-channel regression. "
        f"Score one channel at a time.{_RESET}"
    )
    return True


def _append_registry(card, run_dir: Path) -> None:
    """Registry là bản ghi bền — best-effort nhưng lỗi phải HIỆN, không nuốt im."""
    errored = card.metrics.get("cases_errored")
    scored = card.config.get("cases_scored")
    if errored is not None and scored and float(errored) >= float(scored):
        verdict = "error"
    else:
        verdict = "pass" if card.ok else "fail"
    entry = make_entry(
        run_id=card.run_id, kind="quality", config=card.config,
        metrics={k: v for k, v in card.metrics.items()},
        gates={g.metric: ("skipped" if g.skipped else "pass" if g.ok else "fail") for g in card.gates},
        verdict=verdict, report_dir=str(run_dir) + "/",
    )
    append_entry(entry)
    print(f"registry: appended {card.run_id} ({verdict})")


def _score_and_report(
    run_dir: Path,
    cases: list[EvalCase],
    *,
    case_filter: str = "",
    judge: bool = False,
    judge_budget: float | None = None,
) -> int:
    traces_path = run_dir / "traces.jsonl"
    if not traces_path.is_file():
        print(f"{_RED}traces not found: {traces_path}{_RESET}")
        return 1
    # Both `score` and `run --no-score=false` funnel through here, so the guards live
    # here — `_cmd_run` repeats them only to fail BEFORE spending an LLM budget.
    if _reject_empty_selection(cases) or _reject_mixed_channels(cases):
        return 1
    header, traces = read_traces(traces_path)
    axes = [
        score_policy(cases, traces),
        score_tool_selection(cases, traces),
        score_trajectory(cases, traces),
        # Sees every selected case regardless of tag — the per-axis scorers cannot
        # notice a crashed case that is not on their own axis.
        score_run_integrity(cases, traces),
        score_latency(cases, traces),
        # Linter văn phong (mục Style của persona) — xác định, không judge, chấm mọi reply.
        score_style(cases, traces),
    ]
    if judge:
        from evals.judge_client import set_budget, set_cache_path
        from evals.quality.judge import score_judge

        set_cache_path(_RUNS / ".judge_cache.db")
        set_budget(judge_budget)

        # Pha judge chạy TUẦN TỰ, mỗi call tới 30s + 2 retry — với ~100 case là hàng chục
        # phút không in gì. Không có tiến độ thì nó không phân biệt được với treo, và người
        # chạy Ctrl-C giữa chừng (đã xảy ra 2026-08-25). In một dòng ghi đè mỗi call.
        def _judge_progress(done: int, planned: int, rubric: str, case_id: str, cached: bool) -> None:
            tail = f"{_DIM}(cache){_RESET}" if cached else ""
            print(f"\r{_DIM}judge{_RESET} [{done}/{planned}] {rubric:<13} {case_id:<14}{tail}", end="", flush=True)
            if done == planned:
                print()

        axes.extend(asyncio.run(score_judge(cases, traces, progress=_judge_progress)))
    # Coverage belongs in the run's self-description: a PASS over one case must not read
    # like a PASS over the whole suite. A COUNT, never the id list — at P1's ~300 cases an
    # id list would swamp the config table, and ids already appear per finding.
    # `cases_scored` is the SELECTION size; the reviewed-only (= actually gated) count is
    # the `cases_gated` metric, since an unreviewed case can never move a gated number.
    config = {**header.config, "cases_scored": len(cases)}
    if case_filter:
        config["case_filter"] = case_filter
    card = build_scorecard(header.run_id or run_dir.name, config, axes, load_thresholds(_THRESHOLDS), judge_ran=judge)

    md = render_markdown(card)
    (run_dir / "scorecard.md").write_text(md, encoding="utf-8")
    (run_dir / "scores.json").write_text(
        json.dumps(
            {
                "run_id": card.run_id,
                "ok": card.ok,
                "config": card.config,
                "metrics": card.metrics,
                "gates": [asdict(g) for g in card.gates],
                "axes": [
                    {"axis": a.axis, "checks": a.checks, "failures": a.failures, "pass_rate": a.pass_rate}
                    for a in card.axes
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for axis in card.axes:
        mark = _GREEN + "✓" + _RESET if axis.failures == 0 else _RED + "✗" + _RESET
        print(f"{mark} {axis.axis:<13} {axis.checks - axis.failures}/{axis.checks} checks passed")
    for gate in card.gates:
        mark = _DIM + "⏭" + _RESET if gate.skipped else _GREEN + "✓" + _RESET if gate.ok else _RED + "✗" + _RESET
        actual = "skipped" if gate.skipped else "missing" if gate.actual is None else f"{gate.actual:.4g}"
        print(f"{mark} gate {gate.metric} = {actual} (need {gate.op} {gate.limit:.4g}) — {gate.name}")
    verdict = f"{_GREEN}PASS{_RESET}" if card.ok else f"{_RED}FAIL{_RESET}"
    print(f"\n{'=' * 60}\n{verdict} — scorecard: {run_dir / 'scorecard.md'}")
    _append_registry(card, run_dir)
    return 0 if card.ok else 1


def _filter_desc(*, case: str, tag: str) -> str:
    parts = [p for p in (f"--case {case}" if case else "", f"--tag {tag}" if tag else "") if p]
    return " ".join(parts)


def _cmd_score(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"{_RED}run dir not found: {run_dir}{_RESET}")
        return 1
    cases = _load(args.tenant, args.case, args.tag)
    return _score_and_report(
        run_dir,
        cases,
        case_filter=_filter_desc(case=args.case, tag=args.tag),
        judge=args.judge,
        judge_budget=args.judge_budget_usd,
    )


def _cmd_run(args: argparse.Namespace) -> int:
    # Must execute before any `noble_agent.*` import (spec §5.3): metering must
    # never turn on as a side effect of running the eval harness.
    os.environ["BILLING_METERING_ENABLED"] = "false"
    from evals.quality.runner import build_config_header, run_case

    cases = _load(args.tenant, args.case, args.tag)
    if args.as_tenant:
        cases = [replace(c, tenant=args.as_tenant) for c in cases]
    # Fail before driving a single turn: an unusable selection must not cost an LLM
    # budget and half an hour to discover at score time.
    if _reject_empty_selection(cases) or _reject_mixed_channels(cases):
        return 1

    # Computed before preflight so a preflight failure still has a run_id to log under —
    # a cron run with Redis down must leave a trace, not exit 1 silently (spec §10).
    run_id = args.run_id or new_run_id("quality")

    from evals.preflight import check_redis

    err = asyncio.run(check_redis())
    # Credential per-tenant: kiểm TRƯỚC khi drive, không thì cả N case cùng chết bằng
    # "no published config" và người chạy phải đọc N dòng ERROR để suy ra một nguyên nhân.
    if not err:
        from evals import tenant_creds

        if tenant_creds.configured():
            try:
                asyncio.run(tenant_creds.ensure(args.as_tenant or args.tenant))
            except tenant_creds.CredentialError as exc:
                err = str(exc)
    if err:
        print(f"{_RED}preflight: {err}{_RESET}")
        entry = make_entry(
            run_id=run_id, kind="quality", verdict="error",
            config={
                "preflight_error": err, "tenant": args.tenant,
                "case_filter": _filter_desc(case=args.case, tag=args.tag),
                "cases_scored": len(cases),
            },
            metrics={}, gates={}, report_dir="",
        )
        append_entry(entry)
        print(f"registry: appended {run_id} (error)")
        return 1

    run_dir = _RUNS / run_id
    started_at = datetime.now(UTC).isoformat()

    from evals import tenant_creds

    async def _drive():
        out = []
        for i, case in enumerate(cases, start=1):
            # Credential per-tenant sống ~1 giờ, lượt 100 case tuần tự có thể lâu hơn —
            # gọi mỗi case, hàm tự no-op khi còn hạn (auth API có rate-limit).
            if await tenant_creds.ensure(case.tenant):
                print(f"{_DIM}credential: đã nạp PG role per-tenant cho {case.tenant}{_RESET}")
            trace = await run_case(case, run_id=run_id)
            state = f"{_RED}ERROR{_RESET}" if trace.error else f"{_GREEN}ok{_RESET}"
            print(f"[{i}/{len(cases)}] {case.id:<12} {state}" + (f" {trace.error}" if trace.error else ""))
            # Nguyên nhân #1 của lỗi này là thiếu credential per-tenant, và nó lặp lại y
            # nhau ở mọi case — nói ra một lần thay vì để người chạy tự suy.
            out.append(trace)
            if "no published config" in (trace.error or "") and not tenant_creds.configured():
                print(
                    f"{_RED}→ tenant {case.tenant!r} cần PG role per-tenant: đặt "
                    f"{tenant_creds.ENV_KEY}=<API key gateway của tenant> rồi chạy lại. "
                    f"Dừng sớm — {len(cases) - i} case còn lại sẽ chết y hệt.{_RESET}"
                )
                break
        return out

    traces = asyncio.run(_drive())
    write_traces(run_dir / "traces.jsonl", TraceHeader(run_id, started_at, build_config_header()), traces)
    print(f"\ntraces: {run_dir / 'traces.jsonl'}")
    if args.no_score:
        return 0
    return _score_and_report(
        run_dir,
        cases,
        case_filter=_filter_desc(case=args.case, tag=args.tag),
        judge=args.judge,
        judge_budget=args.judge_budget_usd,
    )


def _cmd_rag(args: argparse.Namespace) -> int:
    os.environ["BILLING_METERING_ENABLED"] = "false"
    from evals.rag.golden import load_golden
    from evals.rag.runner import run_rag, search_agent_string, search_structured

    golden = load_golden(Path(args.golden))
    if not golden:
        print(f"{_RED}golden set rỗng — {args.golden} không có case 'approved' nào, từ chối chạy{_RESET}")
        return 1
    run_id = new_run_id("rag")
    run_dir = _RUNS / run_id

    async def _drive():
        from noble_agent.tenant.current import reset_current_tenant, set_current_tenant

        token = set_current_tenant(args.tenant)
        try:
            search = search_structured if args.mode == "structured" else search_agent_string
            return await run_rag(golden, search=lambda q, p: search(q, p, top_k=args.top_k), top_k=args.top_k)
        finally:
            reset_current_tenant(token)

    out = asyncio.run(_drive())
    run_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "tenant": args.tenant, "mode": args.mode, "top_k": args.top_k,
        "golden_file": args.golden, "cases": len(golden),
        "rag_backend": os.getenv("NOBLE_RAG_BACKEND", "flat_store"),
    }

    if args.judge:
        from evals.judge_client import set_budget, set_cache_path
        from evals.rag.generate import gen_model, run_generation

        set_cache_path(_RUNS / ".judge_cache.db")
        set_budget(args.judge_budget_usd)
        gen = asyncio.run(run_generation(golden, out["rows"], model=gen_model()))
        out["metrics"].update(gen["metrics"])
        out["gen_rows"] = gen["rows"]
        config["gen_model"] = gen_model()

    (run_dir / "rag.json").write_text(
        json.dumps({"run_id": run_id, "config": config, **out}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    verdict = "error" if out["metrics"].get("empty_rate") == 1.0 else "pass"
    append_entry(
        make_entry(
            run_id=run_id, kind="rag", config=config, metrics=out["metrics"],
            gates={}, verdict=verdict, report_dir=str(run_dir) + "/",
        )
    )
    for key in (
        "recall_at_1", "recall_at_5", "context_recall_at_5", "mrr", "empty_rate", "retrieval_p95_ms",
        "faithfulness_rate", "rag_answer_correctness_mean",
    ):
        print(f"{key:<20} {out['metrics'].get(key)}")
    print(f"\nrag.json: {run_dir / 'rag.json'}")
    return 0 if verdict == "pass" else 1


def _cmd_gen_golden(args: argparse.Namespace) -> int:
    os.environ["BILLING_METERING_ENABLED"] = "false"
    from evals.rag.golden_gen import default_model, draft_path, fetch_chunks, gen_questions, write_draft

    model = args.model or default_model()

    async def _drive():
        chunks = await fetch_chunks(tenant=args.tenant, limit=args.limit)
        cases = []
        for chunk in chunks:
            for i, pair in enumerate(await gen_questions(chunk, model=model, n=args.per_chunk)):
                cases.append({
                    "id": f"gg-{chunk['id'][:8]}-{i}", "tenant": args.tenant,
                    "query": pair["query"], "answer": pair["answer"],
                    "golden_chunks": [{"chunk_id": chunk["id"], "evidence": pair["evidence"]}],
                    "project_code": chunk["project_code"],
                })
        return cases

    cases = asyncio.run(_drive())
    out = draft_path(args.tenant)
    write_draft(cases, out)
    print(f"{len(cases)} draft case → {out}")
    print('Duyệt tay: sửa/xoá câu kém, đổi status → "approved", rồi: python -m evals rag --golden', out)
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    os.environ["BILLING_METERING_ENABLED"] = "false"
    from evals.bench.results import flatten

    wanted = {x.strip() for x in args.components.split(",") if x.strip()}
    pcm = (Path(__file__).resolve().parent / "bench" / "fixtures" / "fixture_16k.pcm").read_bytes()
    token = os.getenv("VOICE_SERVICE_AUTH_TOKEN", "").strip()
    results = []

    async def _drive():
        if "stt" in wanted:
            from evals.bench.stt import measure_stt

            results.append(
                await measure_stt(
                    url=os.getenv("STT_SERVICE_URL", "ws://127.0.0.1:8770/stt"), token=token, pcm=pcm,
                    runs=args.runs,
                )
            )
        if "tts" in wanted:
            from evals.bench.tts import measure_tts

            results.append(
                await measure_tts(
                    url=os.getenv("TTS_SERVICE_URL", "ws://127.0.0.1:8771/tts"), token=token,
                    text="Dạ em xin phép giới thiệu về dự án của Noble, đây là một dự án căn hộ cao cấp ạ.",
                    voice=os.getenv("VIENEU_VOICE_ID", "").strip() or None, runs=args.runs,
                )
            )
        if "speaker" in wanted:
            url = os.getenv("SPEAKER_REMOTE_URL", "").strip()
            if url:
                from evals.bench.speaker import measure_speaker

                results.append(await measure_speaker(url=url, pcm=pcm, runs=args.runs))
            else:
                print("speaker: SPEAKER_REMOTE_URL rỗng — bỏ qua")
        if "llm" in wanted:
            from evals.bench.llm import measure_llm

            results.append(await measure_llm(runs=min(args.runs, 5)))

    if "vad" in wanted:
        from evals.bench.vad import measure_vad

        results.append(measure_vad(pcm))
    asyncio.run(_drive())

    run_id = new_run_id("bench")
    run_dir = _RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics = flatten(results)
    payload = {
        "run_id": run_id,
        "components": [{"component": r.component, "runs": r.runs, "errors": r.errors, "stats": r.stats}
                       for r in results],
    }
    (run_dir / "bench.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    all_dead = bool(results) and all(r.runs == 0 for r in results)
    verdict = "error" if (all_dead or not results) else "pass"
    append_entry(
        make_entry(
            run_id=run_id, kind="bench",
            config={"components": sorted(wanted), "runs": args.runs},
            metrics=metrics, gates={}, verdict=verdict, report_dir=str(run_dir) + "/",
        )
    )
    for r in results:
        print(
            f"{r.component:<8} runs={r.runs} errors={r.errors} "
            + " ".join(f"{m}.p50={p['p50']:.0f}" for m, p in r.stats.items() if "p50" in p)
        )
    print(f"\nbench.json: {run_dir / 'bench.json'}")
    return 0 if verdict == "pass" else 1


def _cmd_load_chat(args: argparse.Namespace) -> int:
    from evals.load.chat_ccu import assert_admission, run_chat_ccu, summarize_admission
    from evals.load.ramp import write_results_md

    base_ws = args.host
    base_http = base_ws.replace("ws://", "http://", 1).replace("wss://", "https://", 1)
    run_id = new_run_id("load")
    run_dir = _RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(run_chat_ccu(base_ws=base_ws, max_concurrency=args.max, hold_s=args.hold))
    write_results_md(result, run_dir / "chat_ccu.md")
    knee_step = next((s for s in result.steps if s.concurrency == result.knee), result.steps[-1])
    metrics = {
        "knee_ccu": float(result.knee or 0),
        "p95_at_knee_ms": (knee_step.latency.get("p95", 0.0)) * 1000.0,
        "err_rate_at_knee": knee_step.err_rate,
    }
    gates: dict[str, str] = {}
    admission_ok = True
    if args.admission_cap:
        res = asyncio.run(assert_admission(base_ws=base_ws, base_http=base_http, cap=args.admission_cap))
        gates, admission_ok = summarize_admission(res, args.admission_cap)
        (run_dir / "admission.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    all_dead = all(s.err_rate >= 1.0 for s in result.steps)
    verdict = "error" if all_dead else ("pass" if admission_ok else "fail")
    append_entry(
        make_entry(
            run_id=run_id, kind="load",
            config={
                "target": "chat", "host": base_ws, "max": args.max, "hold_s": args.hold,
                "admission_cap": args.admission_cap,
            },
            metrics=metrics, gates=gates, verdict=verdict, report_dir=str(run_dir) + "/",
        )
    )
    print(f"knee={result.knee} → {run_dir / 'chat_ccu.md'}")
    return 0 if verdict == "pass" else 1


def _cmd_load_voice(args: argparse.Namespace) -> int:
    from evals.load.voice_ccu import run_voice_ccu

    run_id = new_run_id("load")
    run_dir = _RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # run_voice_ccu already writes voice_ccu.md into out_dir itself.
    result = asyncio.run(run_voice_ccu(max_concurrency=args.max, hold_s=args.hold, out_dir=run_dir))
    all_dead = bool(result.steps) and all(s.err_rate >= 1.0 for s in result.steps)
    verdict = "error" if all_dead else "pass"
    append_entry(
        make_entry(
            run_id=run_id, kind="load",
            config={"target": "voice", "max": args.max, "hold_s": args.hold},
            metrics={
                "knee_ccu": float(result.knee or 0),
                "ttfr_p95_at_knee_ms": (
                    next((s for s in result.steps if s.concurrency == result.knee), result.steps[-1]).latency.get(
                        "p95", 0.0
                    )
                    * 1000.0
                    if result.steps
                    else 0.0
                ),
            },
            gates={}, verdict=verdict, report_dir=str(run_dir) + "/",
        )
    )
    print(f"knee={result.knee} → {run_dir / 'voice_ccu.md'}")
    return 0 if verdict == "pass" else 1


def _cmd_load_service(args: argparse.Namespace) -> int:
    if not args.component:
        print(f"{_RED}--target service requires --component stt|tts|speaker{_RESET}")
        return 1
    from evals.load.ramp import write_results_md
    from evals.load.service_ccu import run_service_ccu

    run_id = new_run_id("load")
    run_dir = _RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(run_service_ccu(args.component, max_concurrency=args.max, hold_s=args.hold))
    write_results_md(result, run_dir / f"{args.component}_ccu.md")
    all_dead = bool(result.steps) and all(s.err_rate >= 1.0 for s in result.steps)
    verdict = "error" if all_dead else "pass"
    append_entry(
        make_entry(
            run_id=run_id, kind="load",
            config={"target": "service", "component": args.component, "max": args.max, "hold_s": args.hold},
            metrics={f"{args.component}_knee_ccu": float(result.knee or 0)},
            gates={}, verdict=verdict, report_dir=str(run_dir) + "/",
        )
    )
    print(f"knee={result.knee} → {run_dir / f'{args.component}_ccu.md'}")
    return 0 if verdict == "pass" else 1


def _cmd_load(args: argparse.Namespace) -> int:
    os.environ["BILLING_METERING_ENABLED"] = "false"
    if args.target == "chat":
        return _cmd_load_chat(args)
    if args.target == "voice":
        return _cmd_load_voice(args)
    return _cmd_load_service(args)


def _cmd_report(args: argparse.Namespace) -> int:  # noqa: ARG001
    from evals.registry import read_entries
    from evals.report import render_trend

    md = render_trend(read_entries())
    out = _RUNS / "TREND.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"→ {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_repo_dotenv()
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "run" and getattr(args, "model", None):
        # Set BEFORE noble_agent.config is imported so pydantic-settings reads it.
        # Scoped to `run` — `gen-golden` also has a `--model` attribute, but it names
        # the golden-gen LLM (OpenAI), not the agent's NOBLE_AGENT_MODEL.
        os.environ["NOBLE_AGENT_MODEL"] = args.model
    try:
        if args.cmd == "list":
            return _cmd_list(args)
        if args.cmd == "score":
            return _cmd_score(args)
        if args.cmd == "rag":
            return _cmd_rag(args)
        if args.cmd == "gen-golden":
            return _cmd_gen_golden(args)
        if args.cmd == "bench":
            return _cmd_bench(args)
        if args.cmd == "load":
            return _cmd_load(args)
        if args.cmd == "report":
            return _cmd_report(args)
        if args.cmd == "labeller":
            from evals.labeller.server import main as labeller_main

            labeller_main(port=args.port, host=args.host)
            return 0
        return _cmd_run(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"{_RED}{type(exc).__name__}: {exc}{_RESET}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
