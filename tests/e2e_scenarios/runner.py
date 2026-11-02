"""Drive a scenario through the real agent brain and evaluate assertions.

This is the thin live-integration layer: it needs Redis + an LLM key + a working
RAG backend, exactly like running the agent. It reuses the production entrypoint
`NobleAgent.stream_response` and captures tool calls via its callbacks — the same
seam voice/text transports use.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from noble_agent.agent.facade import NobleAgent
from tests.e2e_scenarios.assertions import AssertionResult, ToolCall, TurnResult, evaluate
from tests.e2e_scenarios.loader import Scenario, Turn


@dataclass
class TurnOutcome:
    turn: Turn
    result: TurnResult
    assertions: list[AssertionResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(a.ok for a in self.assertions)


@dataclass
class ScenarioResult:
    scenario: Scenario
    turns: list[TurnOutcome] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(t.ok for t in self.turns)


async def run_scenario(scenario: Scenario) -> ScenarioResult:
    """Run one scenario end-to-end. Never raises — a crash lands in `.error`."""
    out = ScenarioResult(scenario=scenario)
    session_id = f"e2e-{scenario.name}-{uuid.uuid4().hex[:8]}"
    try:
        agent = await NobleAgent.create(session_id=session_id, channel="chat")
        await agent.reset()
        if scenario.customer:
            await agent.set_customer_fields(scenario.customer)

        for turn in scenario.turns:
            pending: list[dict] = []

            def on_tool_start(name, args, _p=pending):
                _p.append({"name": name, "args": dict(args or {}), "result": None})

            def on_tool_done(name, result, _p=pending):
                for rec in reversed(_p):
                    if rec["name"] == name and rec["result"] is None:
                        rec["result"] = result
                        break

            reply = await agent.stream_response(
                user_text=turn.user,
                on_tool_start=on_tool_start,
                on_tool_done=on_tool_done,
            )
            customer = await agent.get_customer()
            tool_calls = tuple(ToolCall(r["name"], r["args"], r["result"]) for r in pending)
            result = TurnResult(user=turn.user, reply=reply or "", tool_calls=tool_calls, customer=customer)
            out.turns.append(TurnOutcome(turn=turn, result=result, assertions=evaluate(turn.expect, result)))
    except Exception as exc:  # noqa: BLE001 — a scenario crash is a scenario failure, not a harness crash
        out.error = f"{type(exc).__name__}: {exc}"
    return out
