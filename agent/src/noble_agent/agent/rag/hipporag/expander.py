"""HippoRAG query-time expansion — Personalized PageRank over the loaded graph.

Light-weight (numpy only): loads the persisted graph once (singleton) and, given
the passages the hybrid search seeded, spreads probability through shared phrase
nodes to co-entity passages. NO LLM call. Returns PPR-ranked passages; the
adapter fuses them with the hybrid ranking.
"""

from __future__ import annotations

import logging

from noble_agent.agent.rag.hipporag import triple_index as _triple_index
from noble_agent.agent.rag.hipporag.graph import HippoGraph, load_graph
from noble_agent.agent.rag.hipporag.triple_index import TripleIndex
from noble_agent.config import settings

logger = logging.getLogger("rag.hipporag.expander")

_graph: HippoGraph | None = None
_loaded = False
_triple_idx: TripleIndex | None = None
_triple_loaded = False


def reset_cache() -> None:
    """Drop the cached graph + triple index (tests / after a re-sync in-process)."""
    global _graph, _loaded, _triple_idx, _triple_loaded
    _graph = None
    _loaded = False
    _triple_idx = None
    _triple_loaded = False


def load_triple_index() -> TripleIndex | None:
    """Return the cached triple-embedding index (sparse-seed source), loading it
    on first use. ``None`` when the sidecar is absent → sparse-seed no-ops."""
    global _triple_idx, _triple_loaded
    if _triple_loaded:
        return _triple_idx
    _triple_idx = _triple_index.load_triple_index(settings.hipporag_graph_path)
    _triple_loaded = True
    if _triple_idx is not None:
        logger.info("[hipporag.expander] triple index loaded (%d triples)", len(_triple_idx.s_keys))
    return _triple_idx


def load() -> HippoGraph | None:
    """Return the cached graph, loading it from disk on first use. ``None`` when
    the artifact is missing (caller degrades to plain hybrid)."""
    global _graph, _loaded
    if _loaded:
        return _graph
    _graph = load_graph(settings.hipporag_graph_path)
    _loaded = True
    if _graph is None:
        logger.warning("[hipporag.expander] no graph at %s — degrade to hybrid", settings.hipporag_graph_path)
    else:
        logger.info(
            "[hipporag.expander] graph loaded (%d passages, %d phrases)",
            _graph.num_passages(),
            _graph.num_phrases(),
        )
    return _graph


def _normalize(d: dict[str, float]) -> dict[str, float]:
    total = sum(d.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in d.items()}


def expand(
    graph: HippoGraph,
    seed_hits,
    *,
    alpha: float = 0.5,
    iters: int = 30,
    seed_k: int = 8,
    top_k: int = 5,
    project_filter: str = "",
    extra_seeds: dict[str, float] | None = None,
    sparse_weight: float = 0.0,
    passage_threshold: float = 0.0,
    phrase_threshold: float = 0.0,
) -> list[tuple[str, float, str, str]]:
    """Seed PPR at the hybrid hits' passage nodes, return top-K passages.

    ``seed_hits`` — ``[(point_id, project, text, score), ...]`` from the hybrid
    search (the DENSE seeds). Returns ``[(point_id, ppr_score, project, text), ...]``
    or ``[]`` when no seed maps into the graph (→ caller keeps the hybrid result).

    ``extra_seeds`` — optional phrase-node keys → weight (the SPARSE triple-seed).
    When given with ``sparse_weight`` in (0,1], the restart distribution becomes
    ``(1-sparse_weight)·dense + sparse_weight·sparse`` (each group normalised
    first so the RRF-scale dense scores and the cosine-scale sparse scores mix on
    equal footing). ``sparse_weight=0`` (default) → passage-only seeding, exactly
    as before.

    ``project_filter`` (non-empty) restricts the returned passages to that
    project — the PPR still spreads through cross-project shared entities (that's
    where the recall comes from), but the OUTPUT is scoped so a query already
    pinned to one project never surfaces another project's passage.

    ``passage_threshold`` / ``phrase_threshold`` — minimum score a top-K seed must
    clear to be USED (applied AFTER top-K, BEFORE the mix), so low-similarity seeds
    don't inject noise into PPR. ``0.0`` (default) keeps every top-K seed.
    """
    if graph is None or graph.num_passages() == 0:
        return []

    passage_seeds: dict[str, float] = {}
    for hit in seed_hits[:seed_k]:
        pid, _proj, _text, score = hit[0], hit[1], hit[2], hit[3]
        key = graph.passage_key_for_id(pid)
        if key is None:
            continue
        w = float(score)
        if w < passage_threshold:  # drop low-similarity dense seeds
            continue
        passage_seeds[key] = max(passage_seeds.get(key, 0.0), w if w > 0 else 1.0)

    phrase_seeds: dict[str, float] = {}
    if extra_seeds and sparse_weight > 0:
        # keep phrase keys that exist in the graph AND clear the phrase threshold
        phrase_seeds = {
            k: float(v) for k, v in extra_seeds.items() if v > 0 and v >= phrase_threshold and k in graph.nodes
        }

    if phrase_seeds:
        seeds = {k: (1.0 - sparse_weight) * v for k, v in _normalize(passage_seeds).items()}
        for k, v in _normalize(phrase_seeds).items():
            seeds[k] = seeds.get(k, 0.0) + sparse_weight * v
    else:
        seeds = passage_seeds

    if not seeds:
        return []
    scores = graph.personalized_pagerank(seeds, alpha=alpha, iters=iters)
    return graph.top_passages(scores, top_k=top_k, project_filter=project_filter)
