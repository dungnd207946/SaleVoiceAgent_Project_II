"""Ghost-run an agent turn for a predicted query without touching real state.

Operates on cloned ``customer``/``state`` copies, accumulates a local chain
of messages, and stops at the first write-tool encountered. Read-only tools
(noble_search, discover_projects, …, plus ``booking`` with read-only ``action``)
execute normally because they have no externally observable side-effects.

Returns ``(mode, chain, customer_diff)``:

* ``mode == "full"`` — chain ends with an assistant final response.
* ``mode == "partial"`` — chain ends with an assistant message containing
  at least one write-tool call.
* ``(None, [], {})`` on error or iteration-limit exhaustion.

Unified-specific changes vs refactor:
- No ``briefing`` parameter (unified has a single thread, no handoff briefings).
- No ``switch_agent`` special case (unified has a single agent).
"""

from __future__ import annotations

import json
import logging
from typing import Literal

import noble_agent.agent.tools.builtins  # noqa: F401 — ensures built-ins are registered
from noble_agent.agent.base import AgentDef
from noble_agent.agent.prompts.builder import build_system_prompt
from noble_agent.agent.tools import analytics_vocab, registry
from noble_agent.agent.tools.dispatcher import ToolDispatcher
from noble_agent.data.providers.base import ESCALATE_SIGNAL
from noble_agent.storage.models import (
    Customer,
    State,
    ThreadMessage,
    ThreadSummary,
)

logger = logging.getLogger("noble_agent.semcache.sandbox")

MAX_TOOL_ITERATIONS = 5

# ``booking`` is special-cased below because action=check_availability/list is
# read-only while action=schedule/modify writes. Every other tool's
# read/write classification is sourced from the ToolSpec registry.
_READ_ONLY_BOOKING_ACTIONS: set[str] = {"check_availability", "list"}


def _is_write_tool(tool_call: dict, tenant: str = "noble") -> bool:
    name = tool_call["function"]["name"]
    if name == "booking":
        try:
            args = json.loads(tool_call["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            return True
        return args.get("action") not in _READ_ONLY_BOOKING_ACTIONS
    spec = registry.resolve(tenant, name)
    if spec is None:
        return True  # unknown → conservative write (unchanged)
    return not spec.read_only


class _SilentCallbacks:
    """No-op callback bag — sandbox events never reach the user."""

    interrupt_check = None  # surfaced as attribute so dispatcher/runner can read it

    async def on_token(self, _token: str) -> None: ...
    async def on_tool_start(self, _name: str, _args: dict) -> None: ...
    async def on_tool_done(self, _name: str, _result: str) -> None: ...
    async def on_agent_switch(self, **_kwargs) -> None: ...
    async def on_done(self) -> None: ...


def _diff_customer(before: dict, after: dict) -> dict:
    out: dict = {}
    for k, v in after.items():
        if before.get(k) != v:
            out[k] = v
    return out


async def run_sandbox_turn(
    *,
    agent: AgentDef,
    base_history: list[ThreadMessage],
    customer: Customer,
    state: State,
    prior_summary: ThreadSummary | None,
    llm,
    rag,
    sid: str,
    predicted_query: str,
    model: str | dict[str, str] | None = None,
    primary: str | None = None,
) -> tuple[Literal["full", "partial"] | None, list[ThreadMessage], dict]:
    """Run a single ghost turn. The base history is read but not mutated.

    Returns (mode, new_messages_after_user, customer_diff). ``new_messages``
    is what the orchestrator should append to the real history on cache hit
    (the seed user message is added separately by the orchestrator from the
    actual user input).
    """
    ghost_customer = customer.model_copy(deep=True)
    ghost_state = state.model_copy(deep=True)

    # Seed history = base + user(predicted_query). The user message is NOT
    # included in the returned chain (caller appends the real user_text).
    seed_msgs = list(base_history) + [ThreadMessage(role="user", content=predicted_query)]

    system = build_system_prompt(agent, ghost_customer, prior_summary)
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(m.to_openai() for m in seed_msgs)

    chain: list[ThreadMessage] = []
    cb = _SilentCallbacks()
    from noble_agent.tenant.loader import get_tenant_context

    tenant = get_tenant_context().tenant_id

    dispatcher = ToolDispatcher(
        state=ghost_state,
        customer=ghost_customer,
        rag=rag,
        callbacks=cb,
        session_id=sid,
        tenant=tenant,
        sandbox=True,
    )

    customer_before = ghost_customer.model_dump()
    # Use the caller-supplied model (per-provider mapping for the SemCache
    # path); fall back to the main-agent model only if nothing was passed
    # (preserves legacy direct callers).
    sandbox_model: str | dict[str, str] = model if model is not None else agent.model

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            content, tool_calls = await llm.stream_completion(
                messages=messages,
                tools=analytics_vocab.inject(agent.tool_schemas),
                model=sandbox_model,
                temperature=agent.temperature,
                max_tokens=agent.max_tokens,
                on_token=cb.on_token,
                primary=primary,
                purpose="semcache",
            )
        except Exception:
            logger.exception("sandbox: LLM call failed for %r", predicted_query)
            return None, [], {}

        assistant_msg = ThreadMessage(
            role="assistant",
            content=content or "",
            tool_calls=tool_calls,
        )
        chain.append(assistant_msg)
        messages.append(assistant_msg.to_openai())

        if not tool_calls:
            diff = _diff_customer(customer_before, ghost_customer.model_dump())
            return "full", chain, diff

        if any(_is_write_tool(tc, tenant) for tc in tool_calls):
            diff = _diff_customer(customer_before, ghost_customer.model_dump())
            return "partial", chain, diff

        for tc in tool_calls:
            try:
                result = await dispatcher.dispatch(tc)
            except Exception:
                logger.exception("sandbox: read-only tool dispatch failed")
                return None, [], {}
            # Tool bí dữ liệu ⇒ lượt thật sẽ chuyển sale. Chain này không mang
            # được escalate (đã tắt ở dispatcher), cache lại là trả lời hụt.
            if ESCALATE_SIGNAL in result:
                logger.debug("sandbox: bỏ lượt ghost vì %s bí dữ liệu", tc["function"]["name"])
                return None, [], {}
            tool_msg = ThreadMessage(
                role="tool",
                tool_call_id=tc["id"],
                name=tc["function"]["name"],
                content=result,
            )
            chain.append(tool_msg)
            messages.append(tool_msg.to_openai())

        if dispatcher.consume_customer_dirty():
            messages[0] = {
                "role": "system",
                "content": build_system_prompt(agent, ghost_customer, prior_summary),
            }

    logger.warning("sandbox: hit MAX_TOOL_ITERATIONS for %r", predicted_query)
    return None, [], {}
