"""End-of-call summary generator for unified agent.

Produces the structured call-summary document persisted at session-stop time.
Uses the same provider chain as the live turn (built via
`facade.build_llm_providers`) but with a one-shot non-streaming prompt + low
temperature + hard token cap.

Output contract for `generate_call_summary` matches the legacy implementation
(`noble_agent.agent.summary.generator`) so downstream consumers (dashboard,
cross-session memory load) don't need changes.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

logger = logging.getLogger("noble_agent.summary.generator")

# Per-provider timeout (seconds) for the summary LLM call. Bounds EACH provider
# attempt inside the shared fallback chain so a slow/failing model fails fast and
# `complete_once` falls through to the next provider — real fallback, not a single
# overall cap that would cut the chain short.
_SUMMARY_PROVIDER_TIMEOUT_SEC = 12.0


async def _call_llm(prompt: str, *, max_tokens: int, temperature: float = 0.2) -> str:
    """Run prompt through the summary provider chain, non-streaming.

    Uses the SAME per-provider model map (`provider_model_map`) + primary pin
    (`NOBLE_SUMMARY_MODEL` via `primary_for`) as the async in-turn summary, via
    `StreamingClient.complete_once`. This is the shared contract in CLAUDE.md —
    each provider is asked with ITS OWN configured model and the primary runs
    first. The previous hand-rolled loop omitted `dashscope`/`vllm` from its
    model map (so DashScope got the OpenAI model → 404) and ignored the primary
    pin (so it burned the close-timeout budget on anthropic/openai/dashscope
    before ever reaching the configured summary model). Returns "" on total
    failure.
    """
    try:
        from noble_agent.agent.facade import build_llm_providers
        from noble_agent.agent.llm.client import StreamingClient
        from noble_agent.config import get_settings, primary_for, provider_model_map
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SUMMARY] imports failed: %s", exc)
        return ""

    providers = build_llm_providers()
    if not providers:
        logger.warning("[SUMMARY] no LLM providers configured")
        return ""

    settings = get_settings()
    client = StreamingClient(
        providers=providers,
        enable_thinking=settings.llm_enable_thinking,
        openai_reasoning_effort=settings.openai_reasoning_effort,
    )
    # Summary runs on the SAME model as the live conversation (NOBLE_AGENT_MODEL)
    # and the SAME provider fallback chain — `agent_model` is the primary pin,
    # `summary_model` only a legacy fallback. `request_timeout` bounds each
    # provider so a genuinely-failing API falls through to the next model.
    primary = primary_for(settings, settings.agent_model or settings.summary_model)
    try:
        text = await client.complete_once(
            messages=[{"role": "user", "content": prompt}],
            model=provider_model_map(settings),
            temperature=temperature,
            max_tokens=max_tokens,
            primary=primary,
            request_timeout=_SUMMARY_PROVIDER_TIMEOUT_SEC,
            purpose="summary",
        )
        return (text or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SUMMARY] all providers failed: %s", exc)
        return ""


def _format_history(history: list[dict], max_turns: int = 20, *, agent_name: str = "Luna") -> str:
    """Flatten history into KH/<agent_name> lines, capped at max_turns × 300 chars each."""
    recent = history[-max_turns:] if len(history) > max_turns else history
    lines: list[str] = []
    for m in recent:
        role = m.get("role", "")
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        prefix = "KH" if role == "user" else agent_name if role == "assistant" else role
        snippet = content[:300]
        lines.append(f"{prefix}: {snippet}")
    return "\n".join(lines)


_CALL_SUMMARY_PROMPT = """Tóm tắt cuộc gọi sau cho context lần sau.

Viết CHÍNH XÁC theo 2 section sau (plain text, KHÔNG JSON, KHÔNG markdown, KHÔNG code fence):

SUMMARY:
<2-3 câu tiếng Việt — KH muốn gì, {agent} đã làm gì, kết quả chính>

ACTIONS:
- <việc {agent} hứa làm tiếp, hoặc khách cần follow up — 1 việc 1 dòng>
- <tối đa 5 dòng, bỏ qua section này nếu không có>

Thông tin khách (tham khảo, KHÔNG lặp lại vào SUMMARY):
{customer}

Hội thoại:
{history}
"""


_SUMMARY_SECTION_RE = re.compile(
    r"SUMMARY\s*:\s*(.+?)(?=\n\s*ACTIONS\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIONS_SECTION_RE = re.compile(
    r"ACTIONS\s*:\s*(.+?)\Z",
    re.IGNORECASE | re.DOTALL,
)
_ACTION_LINE_RE = re.compile(r"^\s*[-*•]\s+(.+?)\s*$", re.MULTILINE)


def _parse_summary_sections(raw: str) -> tuple[str, list[str]]:
    """Extract SUMMARY narrative + ACTIONS list from LLM plain-text output."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:\w+)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)

    summary = ""
    actions: list[str] = []

    m = _SUMMARY_SECTION_RE.search(text)
    if m:
        summary = m.group(1).strip()
    else:
        actions_at = re.search(r"\n\s*ACTIONS\s*:", text, re.IGNORECASE)
        summary = (text[: actions_at.start()] if actions_at else text).strip()

    m = _ACTIONS_SECTION_RE.search(text)
    if m:
        block = m.group(1)
        actions = [line.strip()[:200] for line in _ACTION_LINE_RE.findall(block) if line.strip()][:5]

    summary = summary.strip().strip('"').strip("'").strip()
    return summary[:500], actions


async def generate_call_summary(
    session_id: str,
    customer: dict,
    history: list[dict],
    *,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> dict:
    """Full structured summary for the Postgres `tenant_data.conversations` row.

    Narrative + open_actions come from LLM text sections. key_facts come from
    the canonical customer state (already validated by `update_customer` tool
    during the call). If LLM fails, returns a minimal doc so the record still
    exists for dashboard listing.
    """
    now = datetime.now(UTC)
    started_at = started_at or now
    ended_at = ended_at or now

    def _base_doc() -> dict:
        # Schema mirrors the Portal call-record contract exactly:
        # customer_name + project_code are TOP-LEVEL (not nested in key_facts);
        # key_facts = {budget, bedrooms, purpose, loan_needed}. The handoff /
        # follow-up fields (priority/transferred_to_sales/sales_followed_up/
        # reason/followed_up_*) are defaulted here but persisted via $setOnInsert
        # in save_call_summary so an escalate-during-call is never clobbered.
        return {
            "session_id": session_id,
            "customer_name": customer.get("full_name") or customer.get("name", ""),
            "summary": "",
            "priority": "normal",
            "project_code": customer.get("project_interest", ""),
            "transferred_to_sales": False,
            "sales_followed_up": False,
            "duration_seconds": max(int((ended_at - started_at).total_seconds()), 0),
            "started_at": started_at,
            "ended_at": ended_at,
            "created_at": now,
            "key_facts": {
                "budget": customer.get("budget", ""),
                "bedrooms": customer.get("bedroom_count", ""),
                "purpose": customer.get("purpose", ""),
                "loan_needed": bool(customer.get("loan_needed", False)),
            },
            "open_actions": [],
            "agent_path": [],
            "reason": None,
            "followed_up_by": None,
            "followed_up_at": None,
            "follow_up_notes": None,
        }

    from noble_agent.config import get_settings

    agent_name = get_settings().agent_name
    history_text = _format_history(history, max_turns=20, agent_name=agent_name)
    if not history_text:
        return _base_doc()

    try:
        customer_json = json.dumps(customer, ensure_ascii=False, default=str)
    except TypeError:
        customer_json = str(customer)

    prompt = _CALL_SUMMARY_PROMPT.format(customer=customer_json, history=history_text, agent=agent_name)
    raw = await _call_llm(prompt, max_tokens=600, temperature=0.2)

    doc = _base_doc()
    if not raw:
        logger.info("[SUMMARY] LLM returned empty — keeping minimal doc")
        return doc

    summary_text, actions = _parse_summary_sections(raw)
    if not summary_text:
        logger.warning("[SUMMARY] parse extracted empty narrative; raw=%r", raw[:200])
    doc["summary"] = summary_text
    # CMS SummaryDetail schema types open_actions as list[dict[str, Any]] — each
    # item MUST be an object, not a bare string, or the detail view fails
    # Pydantic validation (500). Wrap each parsed action line as {"action": ...}.
    doc["open_actions"] = [{"action": a} for a in actions]
    return doc
