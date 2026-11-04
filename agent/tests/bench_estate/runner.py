"""Drive StreamingLLM v9 production pipeline per case, capture turns/tools/timings.

This module is the bench_estate runtime — `run_one()` (added in M2.3) takes a
typed Case from loader.py + uses delivery.py to produce user_inputs, drives the
real `StreamingLLM` pipeline (one Redis-backed session per case), and captures
TTFT, total ms, tool calls, agent switches into a CaseResult.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger("bench_estate.runner")

Verdict = Literal["pass", "fail", "uncertain", "refused", "error", "judge_error"]


@dataclass
class CaseResult:
    """Per-case outcome from runner + judge.

    Populated incrementally:
    - runner.run_one() fills user_inputs, agent_outputs, tool_calls, ttft_ms,
      total_ms, stage_ms, agent_switches, plus error/verdict='error' on failure.
    - judge.grade() (later) fills judge_model, judge_rationale, score_raw,
      score_max, rubric_breakdown, verdict (final).
    """

    case_id: str
    section: str
    topic: str
    delivery_mode: str
    user_inputs: list[str] = field(default_factory=list)
    agent_outputs: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)  # [{turn_idx, name, args, result_summary, ms}]
    ttft_ms: list[float] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)
    stage_ms: list[dict] = field(default_factory=list)
    agent_switches: list[str] = field(default_factory=list)
    judge_model: str = ""
    judge_rationale: str = ""
    score_raw: float = 0.0
    score_max: float = 0.0
    rubric_breakdown: dict[str, float] | None = None
    verdict: Verdict = "fail"
    error: str | None = None


import time  # noqa: E402

from tests.bench_estate.delivery import to_user_inputs  # noqa: E402
from tests.bench_estate.judge import judge_essay, judge_mcq, judge_sales  # noqa: E402
from tests.bench_estate.loader import Case, EssayCase, MCQCase, ScenarioCase  # noqa: E402


async def _create_llm(session_id: str):
    """Real impl creates production StreamingLLM. Tests patch this seam.

    Lazy-imports noble_agent.agent.llm.streaming so importing runner.py in unit
    tests does not require the heavy production dependencies (redis, qdrant,
    etc.) to be available at import time.
    """
    from noble_agent.agent.llm.streaming import StreamingLLM  # noqa: PLC0415

    return await StreamingLLM.create(session_id)


async def _flush_redis(session_id: str) -> None:
    """Wipe Redis keys for this session. Tests patch this seam.

    Best-effort: if Redis is offline or the connection manager isn't initialized,
    log a warning and continue — eval still produces a valid CaseResult.
    """
    try:
        from noble_agent.storage.connection import get_connection_manager  # noqa: PLC0415

        cm = get_connection_manager()
        if cm.redis is None:
            return
        async for key in cm.redis.scan_iter(match=f"*{session_id}*"):
            await cm.redis.delete(key)
    except Exception as e:  # noqa: BLE001 — best-effort cleanup
        logger.warning("redis flush failed for %s: %s", session_id, e)


async def _stream_with_timings(llm, user_input: str, result: CaseResult) -> None:
    """Drive one turn through StreamingLLM with full callback instrumentation.

    Captures TTFT (first token), total, per-tool ms, agent switches.
    """
    t0 = time.monotonic()
    ttft_holder: dict[str, float | None] = {"v": None}
    tokens: list[str] = []

    def _on_token(tok: str) -> None:
        if ttft_holder["v"] is None:
            ttft_holder["v"] = (time.monotonic() - t0) * 1000
        tokens.append(tok)

    tools_log: list[dict] = []
    tool_t0: dict[str, float] = {"v": 0.0}

    def _on_tool_start(name: str, args: str) -> None:
        tool_t0["v"] = time.monotonic()
        tools_log.append({"name": name, "args": args, "result": "", "ms": 0.0})

    def _on_tool_done(name: str, result_text: str) -> None:
        if tools_log:
            tools_log[-1]["result"] = (result_text or "")[:200]
            tools_log[-1]["ms"] = (time.monotonic() - tool_t0["v"]) * 1000

    switches: list[str] = []

    def _on_agent_switch() -> None:
        cur = getattr(llm, "_current_agent", "?")
        switches.append(cur)

    full_text = await llm.stream_response(
        user_input,
        on_token=_on_token,
        on_tool_start=_on_tool_start,
        on_tool_done=_on_tool_done,
        on_agent_switch=_on_agent_switch,
    )
    total_ms = (time.monotonic() - t0) * 1000
    result.agent_outputs.append(full_text or "".join(tokens))
    ttft_v = ttft_holder["v"] if ttft_holder["v"] is not None else total_ms
    result.ttft_ms.append(ttft_v)
    result.total_ms.append(total_ms)
    tools_total = sum(t["ms"] for t in tools_log)
    result.stage_ms.append(
        {
            "llm_ttft": ttft_v,
            "llm_total": total_ms,
            "tools_total": tools_total,
            "tools_n": len(tools_log),
        }
    )
    turn_idx = len(result.user_inputs) - 1
    for t in tools_log:
        result.tool_calls.append({"turn_idx": turn_idx, **t})
    result.agent_switches.extend(switches)


async def run_one(
    case: Case,
    *,
    run_id: str,
    deferred_phone: str = "0942866939",
) -> CaseResult:
    """Drive one full case through the v9 production pipeline.

    Captures: user_inputs, agent_outputs, per-turn ttft_ms / total_ms / stage_ms,
    tool_calls, agent_switches via on_token / on_tool_* / on_agent_switch callbacks
    exposed by StreamingLLM.stream_response (M2.4).
    On any pipeline exception: result.verdict = 'error', result.error = repr(e),
    Redis is still flushed.
    """
    section = case.section if isinstance(case, MCQCase) else "C" if isinstance(case, EssayCase) else "S"
    topic = case.topic if isinstance(case, MCQCase) else case.title
    result = CaseResult(
        case_id=case.case_id,
        section=section,
        topic=topic,
        delivery_mode=case.delivery_mode,
    )
    session_id = f"bench-est-{run_id}-{case.case_id}"
    try:
        llm = await _create_llm(session_id)
        result.user_inputs = to_user_inputs(case)
        for user_input in result.user_inputs:
            await _stream_with_timings(llm, user_input, result)
    except Exception as e:  # noqa: BLE001 — capture all errors into result
        result.error = repr(e)
        result.verdict = "error"
        logger.exception("run_one failed for %s", case.case_id)
    finally:
        await _flush_redis(session_id)
    return result


async def grade(result: CaseResult, case: Case, *, judge_model: str) -> CaseResult:
    """Dispatch to the right rubric judge based on case type. Mutates+returns result."""
    if isinstance(case, MCQCase):
        agent_text = result.agent_outputs[0] if result.agent_outputs else ""
        jr = await judge_mcq(case=case, agent_output=agent_text, model=judge_model)
    elif isinstance(case, EssayCase):
        transcript = "\n\n".join(
            f"USER: {u}\nAGENT: {o}" for u, o in zip(result.user_inputs, result.agent_outputs, strict=False)
        )
        jr = await judge_essay(case=case, transcript_text=transcript, model=judge_model)
    elif isinstance(case, ScenarioCase):
        transcript = "\n\n".join(
            f"USER: {u}\nAGENT: {o}" for u, o in zip(result.user_inputs, result.agent_outputs, strict=False)
        )
        jr = await judge_sales(case=case, transcript_text=transcript, model=judge_model)
    else:
        return result
    result.judge_model = judge_model
    result.score_raw = jr.score
    result.score_max = jr.score_max
    result.verdict = jr.verdict
    result.judge_rationale = jr.rationale
    result.rubric_breakdown = jr.rubric_breakdown if jr.rubric_breakdown else None
    return result
