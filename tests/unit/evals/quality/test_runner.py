"""Runner tests. The agent is faked through `agent_factory`, so these run with
no Redis, no LLM key, and no RAG backend. The one thing they DO exercise for
real is the MAX_TOOL_ITERATIONS log watcher.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from evals.quality.cases import parse_case
from evals.quality.runner import EXHAUSTION_LOGGER, run_case


class FakeAgent:
    """Mimics the NobleAgent surface run_case uses."""

    def __init__(self, *, reply="ok", tools=(), customer=None, raises=None, exhaust=False):
        self._reply = reply
        self._tools = tools
        self._customer = customer or {}
        self._raises = raises
        self._exhaust = exhaust
        self.reset_called = False
        self.reset_count = 0
        self.seeded = None
        self.asked: list[str] = []

    async def reset(self):
        self.reset_count += 1
        self.reset_called = True

    async def set_customer_fields(self, fields):
        self.seeded = dict(fields)
        self._customer.update(fields)
        return self._customer

    async def get_customer(self):
        return dict(self._customer)

    async def stream_response(self, user_text, on_token=None, on_tool_start=None, on_tool_done=None, **_):
        self.asked.append(user_text)
        if self._raises:
            raise self._raises
        for name, args, result in self._tools:
            if on_tool_start:
                on_tool_start(name, args)
            if on_tool_done:
                on_tool_done(name, result)
        if on_token:
            on_token("x")
        if self._exhaust:
            logging.getLogger(EXHAUSTION_LOGGER).warning("runner: hit MAX_TOOL_ITERATIONS without natural termination")
        return self._reply


def _factory(agent):
    async def make(*, session_id, channel, tenant_id):
        return agent

    return make


def _case(turns=None, **over):
    data = {
        "id": "R-1",
        "tags": ["policy"],
        "origin": "handwritten",
        "tenant": "noble",
        "channel": "chat",
        "reviewed": True,
        "turns": turns or [{"user": "xin chào", "expect": {}}],
    }
    data.update(over)
    return parse_case(data)


async def test_run_case_captures_reply_tools_and_customer():
    agent = FakeAgent(
        reply="dạ em chuyển chuyên viên",
        tools=(("escalate", {"reason": "post_sale"}, "{}"),),
        customer={"name": "Anh Minh"},
    )
    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(agent))

    assert trace.error is None
    assert trace.case_id == "R-1"
    assert trace.tenant == "noble"
    assert trace.channel == "chat"
    assert len(trace.turns) == 1
    turn = trace.turns[0]
    assert turn.reply == "dạ em chuyển chuyên viên"
    assert turn.tool_calls[0].name == "escalate"
    assert turn.tool_calls[0].args == {"reason": "post_sale"}
    assert turn.tool_calls[0].raw_result == "{}"
    assert turn.customer_after == {"name": "Anh Minh"}
    assert turn.total_ms >= 0.0
    assert turn.ttft_ms is not None


async def test_run_case_resets_session_and_seeds_customer():
    agent = FakeAgent()
    await run_case(_case(customer={"name": "Chị Lan"}), run_id="testrun", agent_factory=_factory(agent))
    assert agent.reset_called is True
    assert agent.seeded == {"name": "Chị Lan"}


async def test_run_case_resets_session_again_on_cleanup():
    """REDIS_URL here is often a shared production Redis (see README) — a case
    must delete its own session keys when it finishes, not just at the start."""
    agent = FakeAgent()
    await run_case(_case(), run_id="testrun", agent_factory=_factory(agent))
    assert agent.reset_count == 2  # once at start, once for cleanup on exit


async def test_multi_turn_runs_every_turn_in_order():
    agent = FakeAgent()
    case = _case(turns=[{"user": "một", "expect": {}}, {"user": "hai", "expect": {}}])
    trace = await run_case(case, run_id="testrun", agent_factory=_factory(agent))
    assert agent.asked == ["một", "hai"]
    assert [t.user for t in trace.turns] == ["một", "hai"]


async def test_agent_crash_lands_in_error_not_an_exception():
    agent = FakeAgent(raises=RuntimeError("provider down"))
    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(agent))
    assert trace.error is not None
    assert "RuntimeError" in trace.error
    assert "provider down" in trace.error


async def test_cleanup_runs_after_a_crash_and_preserves_completed_turns():
    """Cleanup must run on the crash path too, without disturbing the error or
    the turns that completed before the crash."""

    class CrashesOnSecondTurn(FakeAgent):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def stream_response(self, user_text, on_token=None, on_tool_start=None, on_tool_done=None, **_):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("boom")
            return await super().stream_response(user_text, on_token, on_tool_start, on_tool_done)

    agent = CrashesOnSecondTurn()
    case = _case(turns=[{"user": "một", "expect": {}}, {"user": "hai", "expect": {}}])
    trace = await run_case(case, run_id="testrun", agent_factory=_factory(agent))

    assert trace.error is not None
    assert "boom" in trace.error
    assert [t.user for t in trace.turns] == ["một"]
    assert agent.reset_count == 2


async def test_cleanup_does_not_crash_when_the_factory_itself_raises():
    """Guards `agent: object | None = None` + `if agent is not None:` in the
    `finally:` block. Drop that guard and no `agent` was ever assigned, so
    evaluating the condition itself raises UnboundLocalError/AttributeError
    from inside `finally` — outside `contextlib.suppress`, so it escapes
    run_case and replaces its return value entirely. A normal return carrying
    the factory's error (not an exception raised out of run_case) is exactly
    what a lost guard would break."""

    async def _bad_factory(*, session_id, channel, tenant_id):
        raise RuntimeError("factory boom")

    trace = await run_case(_case(), run_id="testrun", agent_factory=_bad_factory)  # must not raise
    assert trace.error is not None
    assert "factory boom" in trace.error


async def test_cleanup_reset_failure_does_not_turn_a_success_into_an_error():
    class ResetFailsOnCleanup(FakeAgent):
        async def reset(self):
            self.reset_count += 1
            self.reset_called = True
            if self.reset_count == 2:
                raise RuntimeError("cleanup boom")

    agent = ResetFailsOnCleanup()
    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(agent))
    assert trace.error is None
    assert agent.reset_count == 2


async def test_cleanup_reset_failure_does_not_override_the_original_error():
    """Guards `contextlib.suppress(Exception)` around the cleanup `reset()`
    call. Without it, cleanup's RuntimeError would propagate from `finally`
    and replace the crash's TraceCase.error entirely. `reset_count == 2`
    pins that cleanup's `reset()` was actually attempted (and raised) —
    without it this test could pass vacuously if cleanup never ran at all."""

    class ResetFailsOnCleanup(FakeAgent):
        async def reset(self):
            self.reset_count += 1
            self.reset_called = True
            if self.reset_count == 2:
                raise RuntimeError("cleanup boom")

    agent = ResetFailsOnCleanup(raises=RuntimeError("original crash"))
    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(agent))
    assert trace.error is not None
    assert "original crash" in trace.error
    assert "cleanup boom" not in trace.error
    assert agent.reset_count == 2  # cleanup's reset() was attempted, not skipped


async def test_cancellation_still_runs_cleanup_but_propagates_uncaught():
    """`asyncio.CancelledError` is a BaseException (not an Exception), so it
    must escape both the crash handler's `except Exception` and cleanup's
    `contextlib.suppress(Exception)` — while cleanup still runs before it
    escapes. Locks the Python-version-sensitive detail that CancelledError
    does not inherit from Exception; a run_case that swallowed it into a
    TraceCase.error would silently break real task cancellation."""

    class CancelsMidTurn(FakeAgent):
        async def stream_response(self, user_text, on_token=None, on_tool_start=None, on_tool_done=None, **_):
            raise asyncio.CancelledError()

    agent = CancelsMidTurn()
    with pytest.raises(asyncio.CancelledError):
        await run_case(_case(), run_id="testrun", agent_factory=_factory(agent))
    assert agent.reset_count == 2  # cleanup ran even though the exception propagated


async def test_loop_exhaustion_detected_from_the_runner_warning():
    agent = FakeAgent(exhaust=True)
    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(agent))
    assert trace.turns[0].loop_exhausted is True


async def test_no_exhaustion_warning_means_flag_stays_false():
    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(FakeAgent()))
    assert trace.turns[0].loop_exhausted is False


async def test_watcher_is_detached_after_the_run():
    logger = logging.getLogger(EXHAUSTION_LOGGER)
    before = len(logger.handlers)
    await run_case(_case(), run_id="testrun", agent_factory=_factory(FakeAgent(exhaust=True)))
    assert len(logger.handlers) == before


async def test_trace_records_the_pinned_config_version_and_effective_temperature():
    """I5. Spec §4.2: a report must describe what it measured. The pinned config
    version determines the persona in `db` mode, and the effective temperature in
    `legacy` mode comes from the bundle's config.json — NOT from
    `settings.agent_temperature` — so it has to be read off the built agent.
    """

    class _AgentDef:
        temperature = 0.35

    class _Runner:
        _agent = _AgentDef()

    class Pinned(FakeAgent):
        pinned_version = 7
        _runner = _Runner()

    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(Pinned()))
    assert trace.pinned_version == 7
    assert trace.temperature == 0.35


async def test_missing_version_or_temperature_is_recorded_as_none_not_invented():
    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(FakeAgent()))
    assert trace.pinned_version is None
    assert trace.temperature is None


def test_config_header_records_the_temperature_setting():
    """`agent_temperature` is the real field name in src/noble_agent/config.py (the
    one facade.py::_agent_def_from_db passes into the AgentDef). Best-effort: the
    header is allowed to be partial, but if settings load at all this key is there.
    """
    from evals.quality.runner import build_config_header

    header = build_config_header()
    if "model" in header:  # settings loaded (an import failure yields git_sha only)
        assert "agent_temperature" in header
        assert isinstance(header["agent_temperature"], float)


async def test_tool_done_without_matching_start_is_not_dropped():
    """A provider can emit a done for a call whose start we never saw; record it
    rather than losing evidence the grounding scorer will need in P1."""

    class OddAgent(FakeAgent):
        async def stream_response(self, user_text, on_token=None, on_tool_start=None, on_tool_done=None, **_):
            if on_tool_done:
                on_tool_done("kb_search", "ctx blob")
            return "ok"

    trace = await run_case(_case(), run_id="testrun", agent_factory=_factory(OddAgent()))
    calls = trace.turns[0].tool_calls
    assert [c.name for c in calls] == ["kb_search"]
    assert calls[0].raw_result == "ctx blob"


async def test_session_id_carries_eval_prefix():
    seen: dict = {}

    async def factory(*, session_id, channel, tenant_id):
        seen["sid"] = session_id
        raise RuntimeError("stop early")  # không cần agent thật

    case = _case()
    await run_case(case, run_id="20260824-abc", agent_factory=factory)
    assert seen["sid"].startswith(f"eval:20260824-abc:{case.id}:")
