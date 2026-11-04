"""Semantic response cache for the unified single agent.

Predicts next user queries, ghost-runs them in sandbox, caches the resulting
assistant chain in Redis. On the next user turn the orchestrator does a cosine
lookup; on hit it replays the cached chain instead of calling the LLM again.

Public surface used by the orchestrator: ``SemCacheManager.try_hit`` (lookup),
``SemCacheManager.schedule_refresh`` (fire-and-forget), ``cancel_refresh``,
and ``invalidate``.
"""

from noble_agent.semcache.manager import CacheHit, SemCacheManager

__all__ = ["CacheHit", "SemCacheManager"]
