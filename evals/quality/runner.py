"""RUN phase — drive one eval case through the production agent entrypoint.

Deliberately the ONLY module in the harness that imports `noble_agent`: keeping
the agent dependency here is what lets every scorer be unit-tested with no
Redis, no LLM key, and no RAG backend.

Modelled on `tests/e2e_scenarios/runner.py` (same `NobleAgent.stream_response`
seam the voice/text transports use), plus three things a scorecard needs:
timing, a loop-exhaustion signal, and a persisted trace.

Loop exhaustion cannot be derived from the tool callbacks: the dispatcher runs a
batch's calls sequentially, so N tools in one batch and N batches of one tool
emit an identical callback sequence — there is no observable batch boundary. The
real signal is `noble_agent.runner`'s warning at MAX_TOOL_ITERATIONS, which we
listen for with a temporary logging handler (no production change).
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable

from evals.quality.cases import EvalCase
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn

EXHAUSTION_LOGGER = "noble_agent.runner"
EXHAUSTION_NEEDLE = "hit MAX_TOOL_ITERATIONS"

AgentFactory = Callable[..., Awaitable[object]]

logger = logging.getLogger(__name__)


class _ExhaustionWatch(logging.Handler):
    """Flag whether `noble_agent.runner` reported MAX_TOOL_ITERATIONS while attached."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.hit = False

    def emit(self, record: logging.LogRecord) -> None:
        # A broken log record must never fail an eval run.
        with contextlib.suppress(Exception):
            if EXHAUSTION_NEEDLE in record.getMessage():
                self.hit = True

    def __enter__(self) -> _ExhaustionWatch:
        self.hit = False
        logging.getLogger(EXHAUSTION_LOGGER).addHandler(self)
        return self

    def __exit__(self, *_exc) -> None:
        logging.getLogger(EXHAUSTION_LOGGER).removeHandler(self)


async def _default_factory(*, session_id: str, channel: str, tenant_id: str):
    from noble_agent.agent.facade import NobleAgent

    return await NobleAgent.create(session_id=session_id, channel=channel, tenant_id=tenant_id)


def build_config_header() -> dict:
    """Config that makes a run self-describing. Best-effort — never raises."""
    config: dict = {}
    try:
        config["git_sha"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — a missing git is not a reason to abort an eval run
        config["git_sha"] = ""
    # Record what we can; a partial header beats none.
    with contextlib.suppress(Exception):
        from noble_agent.config import get_settings

        s = get_settings()
        config.update(
            {
                "model": s.agent_model,
                "rag_backend": s.noble_rag_backend,
                "embed_backend": s.embed_backend,
                "embed_sparse_model": s.embed_sparse_model,
                "agent_config_source": s.agent_config_source,
                "tenant_id": s.tenant_id,
                # Spec §4.2 mandates temperature: two runs at different temperatures
                # are not comparable. `agent_temperature` is the field the turn loop
                # uses in `db` mode (facade.py::_agent_def_from_db). In `legacy` mode
                # the effective value comes from the bundle's persona config.json
                # instead, which is why the EFFECTIVE per-case value is recorded
                # separately in each trace's `temperature` (see `_describe_agent`).
                "agent_temperature": s.agent_temperature,
            }
        )
    return config


def _describe_agent(agent: object) -> dict:
    """What the built agent is pinned to — spec §4.2's "config version đã pin" +
    the temperature actually in force. Best-effort; never raises.

    `pinned_version` is public on `NobleAgent` (0 = legacy/package mode). The
    effective temperature lives on the runner's `AgentDef`, reached the same way
    production's own `NobleAgent.get_identity` reaches it (`_runner._agent`), and
    matters because in `legacy` mode it comes from the bundle's config.json, NOT
    from `settings.agent_temperature`.
    """
    out: dict = {}
    with contextlib.suppress(Exception):
        version = getattr(agent, "pinned_version", None)
        if version is not None:
            out["pinned_version"] = int(version)
    with contextlib.suppress(Exception):
        agent_def = getattr(getattr(agent, "_runner", None), "_agent", None)
        temperature = getattr(agent_def, "temperature", None)
        if temperature is not None:
            out["temperature"] = float(temperature)
    return out


async def run_case(case: EvalCase, *, run_id: str, agent_factory: AgentFactory | None = None) -> TraceCase:
    """Run every turn of `case` and return its trace. Never raises.

    `REDIS_URL` here is often a SHARED Redis also used by production (see
    README), so the session this case creates is deleted again via
    `agent.reset()` on every exit path — success, crash, or cancellation —
    not just seeded at the start. Cleanup is best-effort and must never
    change the outcome this function would otherwise have returned.
    """
    factory = agent_factory or _default_factory
    session_id = f"eval:{run_id}:{case.id}:{uuid.uuid4().hex[:6]}"
    turns: list[TraceTurn] = []
    described: dict = {}
    agent: object | None = None
    try:
        agent = await factory(session_id=session_id, channel=case.channel, tenant_id=case.tenant)
        described = _describe_agent(agent)
        await agent.reset()
        if case.customer:
            await agent.set_customer_fields(case.customer)

        for case_turn in case.turns:
            pending: list[dict] = []
            first_token_at: list[float] = []

            def on_tool_start(name, args, _p=pending):
                _p.append({"name": name, "args": dict(args or {}), "result": None, "done": False})

            def on_tool_done(name, result, _p=pending):
                for rec in reversed(_p):
                    if rec["name"] == name and not rec["done"]:
                        rec["result"] = result
                        rec["done"] = True
                        return
                # No matching start (provider quirk) — keep the evidence anyway.
                _p.append({"name": name, "args": {}, "result": result, "done": True})

            def on_token(_text, _at=first_token_at):
                if not _at:
                    _at.append(time.perf_counter())

            started = time.perf_counter()
            with _ExhaustionWatch() as watch:
                reply = await agent.stream_response(
                    user_text=case_turn.user,
                    on_token=on_token,
                    on_tool_start=on_tool_start,
                    on_tool_done=on_tool_done,
                )
                exhausted = watch.hit
            total_ms = (time.perf_counter() - started) * 1000.0
            ttft_ms = (first_token_at[0] - started) * 1000.0 if first_token_at else None

            turns.append(
                TraceTurn(
                    user=case_turn.user,
                    reply=reply or "",
                    tool_calls=tuple(
                        TracedToolCall(name=r["name"], args=r["args"], raw_result=r["result"]) for r in pending
                    ),
                    customer_after=await agent.get_customer(),
                    ttft_ms=ttft_ms,
                    total_ms=total_ms,
                    loop_exhausted=exhausted,
                )
            )
    except Exception as exc:  # noqa: BLE001 — a case crash is a case failure, not a harness crash
        return TraceCase(
            case_id=case.id,
            tags=case.tags,
            tenant=case.tenant,
            channel=case.channel,
            reviewed=case.reviewed,
            turns=tuple(turns),
            error=f"{type(exc).__name__}: {exc}",
            **described,
        )
    finally:
        if agent is not None:
            try:
                await agent.reset()
            except Exception:  # cleanup must never change run_case's outcome
                logger.warning("cleanup reset() failed for session %s", session_id, exc_info=True)

    return TraceCase(
        case_id=case.id,
        tags=case.tags,
        tenant=case.tenant,
        channel=case.channel,
        reviewed=case.reviewed,
        turns=tuple(turns),
        **described,
    )
