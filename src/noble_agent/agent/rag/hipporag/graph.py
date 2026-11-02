"""HippoRAG knowledge graph — pure in-memory structure + Personalized PageRank.

Nodes are of two types:
  - ``passage``  — one per KB chunk (keyed by Qdrant point id); carries text +
                   project + content_hash.
  - ``phrase``   — one per distinct entity string extracted by OpenIE.

Edges (undirected, weighted by co-occurrence count):
  - passage ── phrase   ("contains": the passage mentions the entity)
  - phrase  ── phrase   (a relation triple links two entities)

Runtime retrieval seeds PPR at the passage nodes returned by the hybrid search;
probability mass flows through shared phrase nodes to co-entity passages —
multi-hop recall in a single, LLM-free step.

No third-party graph library: adjacency is a symmetric dict-of-dict and PPR is a
numpy power-iteration built from edge arrays. Fast at this corpus scale (~300
passages, a few hundred phrases).
"""

from __future__ import annotations

import json
import logging
import os

import numpy as np

logger = logging.getLogger("rag.hipporag.graph")


def _norm_phrase(name: str) -> str:
    """Fold an entity string to a stable node key (lowercase, collapse spaces)."""
    return " ".join((name or "").lower().split())


class HippoGraph:
    def __init__(self) -> None:
        # key -> {type, label, project, text, content_hash, point_id}
        self.nodes: dict[str, dict] = {}
        # symmetric adjacency: key -> {neighbour_key: weight}
        self.adj: dict[str, dict[str, float]] = {}
        # content_hashes already OpenIE'd (incremental skip set)
        self.processed_hashes: set[str] = set()
        # extracted triples (the SPARSE triple-seed source): one dict per triple
        # {"s": s_key, "o": o_key, "rel": str, "text": "subject relation object",
        #  "passage": point_id}. Relations are kept here (not on the weighted edge).
        self.triples: list[dict] = []
        # passage point id -> node key
        self._pid_to_key: dict[str, str] = {}
        # rebuilt lazily on each PPR call
        self._order: list[str] = []
        self._order_index: dict[str, int] = {}

    # ── keys ────────────────────────────────────────────────────────────────
    @staticmethod
    def _phrase_key(name: str) -> str:
        return "phrase::" + _norm_phrase(name)

    @staticmethod
    def _passage_key(point_id: str) -> str:
        return "passage::" + str(point_id)

    # ── mutation ──────────────────────────────────────────────────────────────
    def _ensure_node(self, key: str, **attrs) -> None:
        if key not in self.nodes:
            self.nodes[key] = attrs
            self.adj[key] = {}

    def _add_edge(self, a: str, b: str, w: float = 1.0) -> None:
        if a == b:
            return
        self.adj[a][b] = self.adj[a].get(b, 0.0) + w
        self.adj[b][a] = self.adj[b].get(a, 0.0) + w

    def add_passage(
        self,
        point_id: str,
        text: str,
        project: str,
        content_hash: str,
        triples: list[tuple[str, str, str]],
    ) -> None:
        """Add a passage node and the phrase nodes / edges from its triples.

        If a passage node with the same ``point_id`` already exists it is removed
        first (text changed → re-extracted), so no stale node lingers.
        """
        if point_id in self._pid_to_key:
            self.remove_passage(point_id)

        pkey = self._passage_key(point_id)
        self._ensure_node(
            pkey,
            type="passage",
            label=project or "",
            project=project or "",
            text=text or "",
            content_hash=content_hash or "",
            point_id=str(point_id),
        )
        self._pid_to_key[str(point_id)] = pkey

        for triple in triples:
            if not triple or len(triple) < 3:
                continue
            subj, rel, obj = triple[0], triple[1], triple[2]
            for ent in (subj, obj):
                ent = (ent or "").strip()
                if not ent:
                    continue
                ekey = self._phrase_key(ent)
                self._ensure_node(ekey, type="phrase", label=ent, project="", text="", content_hash="", point_id="")
                self._add_edge(pkey, ekey)  # "contains"
            s = (subj or "").strip()
            o = (obj or "").strip()
            rel = (rel or "").strip()
            if s and o:
                self._add_edge(self._phrase_key(s), self._phrase_key(o))  # relation
                # keep the full triple (relation text preserved) for the sparse seed
                self.triples.append(
                    {
                        "s": self._phrase_key(s),
                        "o": self._phrase_key(o),
                        "rel": rel,
                        "text": " ".join(x for x in (s, rel, o) if x),
                        "passage": str(point_id),
                    }
                )

        if content_hash:
            self.processed_hashes.add(content_hash)

    def remove_passage(self, point_id: str) -> None:
        """Remove a passage node (by point id) and prune phrase nodes it orphans."""
        pkey = self._pid_to_key.get(str(point_id))
        if not pkey or pkey not in self.nodes:
            return
        chash = self.nodes[pkey].get("content_hash", "")
        self._drop_node(pkey)
        self._pid_to_key.pop(str(point_id), None)
        if chash:
            self.processed_hashes.discard(chash)
        self.triples = [t for t in self.triples if t.get("passage") != str(point_id)]
        self._prune_orphan_phrases()

    def _prune_orphan_phrases(self) -> None:
        """Drop phrase nodes no longer supported by any passage (cascades:
        relation-only leftovers are removed too)."""
        changed = True
        while changed:
            changed = False
            for key in [k for k, a in self.nodes.items() if a.get("type") == "phrase"]:
                has_passage_nb = any(self.nodes.get(nb, {}).get("type") == "passage" for nb in self.adj.get(key, {}))
                if not has_passage_nb:
                    self._drop_node(key)
                    changed = True

    def _drop_node(self, key: str) -> None:
        for nb in list(self.adj.get(key, {}).keys()):
            self.adj.get(nb, {}).pop(key, None)
        self.adj.pop(key, None)
        self.nodes.pop(key, None)

    # ── introspection ─────────────────────────────────────────────────────────
    def has_passage(self, content_hash: str) -> bool:
        return bool(content_hash) and content_hash in self.processed_hashes

    def passage_key_for_id(self, point_id: str) -> str | None:
        return self._pid_to_key.get(str(point_id))

    def num_passages(self) -> int:
        return sum(1 for a in self.nodes.values() if a.get("type") == "passage")

    def num_phrases(self) -> int:
        return sum(1 for a in self.nodes.values() if a.get("type") == "phrase")

    # ── PPR ─────────────────────────────────────────────────────────────────
    def _rebuild_order(self) -> None:
        self._order = list(self.nodes.keys())
        self._order_index = {k: i for i, k in enumerate(self._order)}

    def personalized_pagerank(self, seeds: dict[str, float], *, alpha: float = 0.5, iters: int = 30) -> np.ndarray:
        """Power-iterate PPR. ``seeds`` maps node key → restart weight.

        r_{t+1} = (1-alpha)·p + alpha·(column-normalised adjacency)·r_t, with the
        mass of dangling nodes (no out-edges) redistributed to p each step so the
        total stays 1. Returns a score vector aligned to ``self._order`` (rebuilt
        here). Empty / zero seed → all-zeros.
        """
        self._rebuild_order()
        n = len(self._order)
        if n == 0:
            return np.zeros(0)

        p = np.zeros(n)
        for key, w in seeds.items():
            i = self._order_index.get(key)
            if i is not None and w > 0:
                p[i] += w
        total = p.sum()
        if total <= 0:
            return np.zeros(n)
        p /= total

        # edge arrays with source-normalised transition weights (both directions)
        deg = {k: sum(nbrs.values()) for k, nbrs in self.adj.items()}
        src: list[int] = []
        dst: list[int] = []
        wn: list[float] = []
        for a, nbrs in self.adj.items():
            da = deg.get(a, 0.0)
            if da <= 0:
                continue
            ia = self._order_index[a]
            for b, w in nbrs.items():
                src.append(ia)
                dst.append(self._order_index[b])
                wn.append(w / da)
        if not src:
            return p  # no edges: mass stays on the seeds

        src_a = np.asarray(src, dtype=np.intp)
        dst_a = np.asarray(dst, dtype=np.intp)
        wn_a = np.asarray(wn, dtype=np.float64)
        # dangling nodes (deg 0, e.g. a triple-less passage) would otherwise leak
        # their probability mass each step; collect it and redistribute via the
        # restart vector p so total mass stays 1 (a true distribution).
        dangling_idx = np.asarray([i for k, i in self._order_index.items() if deg.get(k, 0.0) <= 0], dtype=np.intp)

        r = p.copy()
        for _ in range(max(1, iters)):
            r_next = (1.0 - alpha) * p
            np.add.at(r_next, dst_a, alpha * r[src_a] * wn_a)
            if dangling_idx.size:
                r_next += alpha * float(r[dangling_idx].sum()) * p  # gom dangling-mass về p
            r = r_next
        return r

    def top_passages(
        self, scores: np.ndarray, top_k: int = 5, project_filter: str = ""
    ) -> list[tuple[str, float, str, str]]:
        """Return the top-K passage nodes as (point_id, score, project, text),
        aligned to the ``self._order`` used by the last PPR call.

        ``project_filter`` (when non-empty) keeps only passages of that project —
        applied BEFORE the top_k cut so a scoped query is never starved by
        cross-project passages that PPR happened to reach."""
        if scores.size == 0:
            return []
        out: list[tuple[str, float, str, str]] = []
        for key, i in self._order_index.items():
            node = self.nodes.get(key, {})
            if node.get("type") != "passage":
                continue
            if project_filter and node.get("project", "") != project_filter:
                continue
            sc = float(scores[i]) if i < scores.size else 0.0
            if sc <= 0:
                continue
            out.append((node.get("point_id", ""), sc, node.get("project", ""), node.get("text", "")))
        out.sort(key=lambda t: t[1], reverse=True)
        return out[:top_k]

    # ── persistence ───────────────────────────────────────────────────────────
    def to_json(self) -> dict:
        # edges stored once (a < b) to avoid duplication
        edges: list[list] = []
        seen: set[tuple[str, str]] = set()
        for a, nbrs in self.adj.items():
            for b, w in nbrs.items():
                pair = (a, b) if a < b else (b, a)
                if pair in seen:
                    continue
                seen.add(pair)
                edges.append([pair[0], pair[1], w])
        return {
            "version": 1,
            "nodes": {k: v for k, v in self.nodes.items()},
            "edges": edges,
            "processed_hashes": sorted(self.processed_hashes),
            "triples": self.triples,
        }

    @classmethod
    def from_json(cls, d: dict) -> HippoGraph:
        g = cls()
        for key, attrs in (d.get("nodes") or {}).items():
            g.nodes[key] = dict(attrs)
            g.adj[key] = {}
            if attrs.get("type") == "passage":
                pid = attrs.get("point_id") or ""
                if pid:
                    g._pid_to_key[str(pid)] = key
        for edge in d.get("edges") or []:
            if len(edge) < 3:
                continue
            a, b, w = edge[0], edge[1], float(edge[2])
            if a in g.adj and b in g.adj:
                g.adj[a][b] = w
                g.adj[b][a] = w
        g.processed_hashes = set(d.get("processed_hashes") or [])
        g.triples = list(d.get("triples") or [])
        return g


def save_graph(graph: HippoGraph, path: str) -> None:
    """Atomically persist the graph as JSON at ``path``."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(graph.to_json(), fh, ensure_ascii=False)
    os.replace(tmp, path)


def load_graph(path: str) -> HippoGraph | None:
    """Load a persisted graph, or ``None`` if the file is absent / unreadable."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return HippoGraph.from_json(json.load(fh))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("[hipporag.graph] load failed at %s: %s", path, exc)
        return None
