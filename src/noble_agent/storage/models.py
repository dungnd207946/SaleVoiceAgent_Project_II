"""Unified single-agent state models.

3 Redis keys per session: meta / customer / state. State holds a single flat
history thread and an optional async-generated summary covering older turns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Meta(BaseModel):
    session_id: str
    started_at: datetime
    last_active: datetime
    phone: str | None = None


class Customer(BaseModel):
    name: str | None = None
    noble_user_id: str | None = None
    full_name: str | None = None
    gender: Literal["M", "F"] | None = None
    phone: str | None = None
    project_interest: str | None = None
    purpose: str | None = None
    budget: str | None = None
    preferred_area: str | None = None
    bedroom_count: str | None = None
    is_buyer: bool | None = None
    is_noble_customer: bool | None = None
    noble_info: str | None = None
    notes: str | None = None  # bối cảnh để tư vấn sát: nơi làm, gia đình, thời điểm, băn khoăn (cộng dồn)


class ThreadMessage(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str = ""
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    # Stamped at construction (= append time on the live turn path). Storage-only:
    # never rendered into to_openai(), so it can't perturb the LLM request or
    # bust the provider prompt-cache prefix. Legacy Redis blobs without the field
    # get stamped at first load (one-time deploy artifact, then stable on re-save).
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_openai(self) -> dict:
        """Render as an OpenAI Chat Completions message dict."""
        if self.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": self.tool_call_id or "",
                "name": self.name or "",
                "content": self.content,
            }
        if self.role == "assistant" and self.tool_calls:
            return {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls}
        return {"role": self.role, "content": self.content}


class ThreadSummary(BaseModel):
    text: str
    covers_turns: int
    updated_at: datetime


class State(BaseModel):
    history: list[ThreadMessage] = Field(default_factory=list)
    summary: ThreadSummary | None = None
    scratchpad: dict = Field(default_factory=dict)
