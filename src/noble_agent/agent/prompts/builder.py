"""Compose the unified agent's system prompt from AgentDef + runtime state."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import jinja2

from noble_agent.agent.base import AgentDef
from noble_agent.storage.models import Customer, ThreadSummary

_customer_env = jinja2.Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
_VN_WEEKDAYS = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật")


def _today_vn() -> str:
    now = datetime.now(tz=_VN_TZ)
    return f"{now.strftime('%d/%m/%Y')} ({_VN_WEEKDAYS[now.weekday()]})"


def _render_customer(template_src: str, customer: Customer) -> str:
    return _customer_env.from_string(template_src).render(customer=customer)


def render_customer_block(agent: AgentDef, customer: Customer) -> str:
    """Render the customer profile block once (used to freeze it per session)."""
    return _render_customer(agent.sections["customer_format"], customer)


def build_system_prompt(
    agent: AgentDef,
    customer: Customer,
    prior_summary: ThreadSummary | None,
    *,
    customer_block: str | None = None,
) -> str:
    block = (
        customer_block if customer_block is not None else _render_customer(agent.sections["customer_format"], customer)
    )
    # Pass the summary text directly (not model_dump()) so the template can't
    # accidentally render `updated_at: datetime(...)` into the system prompt.
    summary_text = (prior_summary.text or "").strip() if prior_summary else None
    return agent.prompt_template.render(
        soul=agent.sections["soul"],
        rules=agent.sections["rules"],
        customer_block=block,
        prior_summary=summary_text or None,
        today=_today_vn(),
    )
