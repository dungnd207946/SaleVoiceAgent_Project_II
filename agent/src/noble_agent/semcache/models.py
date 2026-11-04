"""Cache entry models — what we store in Redis and replay on hit.

Single-agent variant: no ``base_agent`` field (unified has one agent).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from noble_agent.storage.models import ThreadMessage


class CacheEntry(BaseModel):
    """One predicted query + its ghost-run chain.

    - mode="full": chain ends with an assistant message containing the final
      response text (no pending tool_calls). Replay = append everything + emit
      tokens via callbacks; LLM is NOT called.
    - mode="partial": chain ends with an assistant message whose ``tool_calls``
      include at least one write-tool. Replay strategy is up to the orchestrator
      (current unified port falls through to a live run on partial hits).
    """

    query: str
    embedding: list[float]
    mode: Literal["full", "partial"]
    chain: list[ThreadMessage] = Field(default_factory=list)
    # Customer fields the sandbox mutated (e.g. noble_search auto-sets
    # ``project_interest``). Applied to the real customer on cache hit so
    # the next turn's system prompt has the right FAQ context.
    customer_diff: dict = Field(default_factory=dict)


class CacheBundle(BaseModel):
    """All cache entries for one session, persisted as a single Redis key."""

    entries: list[CacheEntry] = Field(default_factory=list)
    created_at: datetime
    base_history_len: int  # for debugging: history length when this bundle was built
