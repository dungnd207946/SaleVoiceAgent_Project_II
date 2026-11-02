"""HippoRAG 2 graph-RAG backend for noble_kb.

A knowledge graph (phrase nodes + passage nodes) is built OFFLINE from the
Qdrant clone collection via LLM OpenIE (see ``builder``), persisted to disk, and
queried at runtime with Personalized PageRank (see ``expander`` / ``adapter``) —
no LLM call on the query path, so voice TTFA is unaffected.

Activated via ``NOBLE_RAG_BACKEND=hipporag``. Built/updated via ``noble-rag-sync``
(``--renew-graph`` rebuilds from scratch; default is incremental by content_hash).
"""

from __future__ import annotations

from noble_agent.agent.rag.hipporag.graph import HippoGraph

__all__ = ["HippoGraph"]
