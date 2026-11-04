"""In-process project-name resolver: fuse similarity channels + gate confidence.

Built once from the DB roster rows (code/name/region). resolve() returns a
resolved code, an ambiguous candidate list, or not_found. Weights + thresholds
are module constants calibrated against tests/.../test_resolution_eval.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from noble_agent.data.project_matching import channels, fold

# Channel weights (sum need not be 1; combined is renormalized by weight total).
_W_TRIGRAM = 0.20
_W_TOKEN = 0.35
_W_PHONETIC = 0.35
_W_EMBED = 0.10
# Additive context boosts.
_BOOST_REGION = 0.15
_BOOST_BRAND = 0.08
# Confidence gate.
_FLOOR = 0.55  # top-1 must clear this to be resolved
_MARGIN = 0.09  # top-1 must beat top-2 by this to be resolved
_STRONG_FLOOR = 0.85  # very-high absolute top-1 confidence
_STRONG_MARGIN = 0.05  # lighter separation required at the strong tier
_AMBIG_FLOOR = 0.45  # below this for top-1 => not_found
_AMBIG_DELTA = 0.10  # candidates within this of top-1 are returned
_MAX_CANDIDATES = 4
# Best-guess gate on not_found: a heavily STT-mangled name still leaves top-1
# clearly separated from top-2, while non-name speech scores a near-tie.
_GUESS_FLOOR = 0.35
_GUESS_MARGIN = 0.10


@dataclass(frozen=True)
class Candidate:
    code: str
    name: str
    region: str
    score: float


@dataclass(frozen=True)
class ResolveResult:
    status: str  # "resolved" | "ambiguous" | "not_found"
    code: str = ""
    name: str = ""
    region: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    message: str = ""


@dataclass
class _Entry:
    code: str
    name: str
    region: str
    norm_name: str
    folded_name: str
    trigrams: frozenset[str]
    name_tokens: frozenset[str]
    embed: list[float] | None = None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return max(0.0, min(1.0, dot))  # e5 vectors are L2-normalized => dot == cosine


class ProjectNameIndex:
    def __init__(
        self,
        rows: list[dict],
        *,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ) -> None:
        self._entries: list[_Entry] = []
        for r in rows:
            code = (r.get("code") or "").strip()
            name = (r.get("name") or "").strip()
            if not code or not name:
                continue
            norm = fold.normalize_text(name)
            self._entries.append(
                _Entry(
                    code=code,
                    name=name,
                    region=(r.get("region") or "").strip(),
                    norm_name=norm,
                    folded_name=fold.fold_text(name),
                    trigrams=frozenset(channels.trigram_set(norm)),
                    name_tokens=frozenset(norm.split(" ")),
                )
            )
        if embed_fn is not None and self._entries:
            try:
                vecs = embed_fn([e.name for e in self._entries])
                for e, v in zip(self._entries, vecs, strict=False):
                    e.embed = list(v)
            except Exception:  # noqa: BLE001 — embedding is a supporting vote; degrade
                pass

    def _combined(
        self,
        e: _Entry,
        q_norm: str,
        q_folded: str,
        q_trigrams: set[str],
        region_hint: str,
        brand_tokens: frozenset[str],
        q_vec: list[float] | None,
    ) -> float:
        tri = channels.trigram_score_sets(q_trigrams, e.trigrams)
        tok = channels.token_set_score_normalized(q_norm, e.norm_name)
        pho = channels.phonetic_score_folded(q_folded, e.folded_name)
        w = _W_TRIGRAM + _W_TOKEN + _W_PHONETIC
        s = _W_TRIGRAM * tri + _W_TOKEN * tok + _W_PHONETIC * pho
        if q_vec is not None and e.embed is not None:
            s += _W_EMBED * _cosine(q_vec, e.embed)
            w += _W_EMBED
        s /= w
        if region_hint and e.region and fold.normalize_text(region_hint) in fold.normalize_text(e.region):
            s += _BOOST_REGION
        if brand_tokens and (brand_tokens & e.name_tokens):
            s += _BOOST_BRAND
        return s

    def lookup(self, code: str) -> Candidate | None:
        """Roster entry for a canonical code (score is meaningless here)."""
        for e in self._entries:
            if e.code == code:
                return Candidate(e.code, e.name, e.region, 0.0)
        return None

    def resolve(
        self,
        query: str,
        *,
        region_hint: str = "",
        investor_hint: str = "",
        query_embed_fn: Callable[[str], list[float]] | None = None,
    ) -> ResolveResult:
        if not (query or "").strip() or not self._entries:
            return ResolveResult(status="not_found", message="Chưa nhận được tên dự án.")
        brand_tokens = frozenset(fold.normalize_text(investor_hint).split(" ")) if investor_hint else frozenset()
        q_vec = query_embed_fn(query) if query_embed_fn is not None else None
        q_norm = fold.normalize_text(query)
        q_folded = fold.fold_text(query)
        q_trigrams = channels.trigram_set(q_norm)
        scored = [
            Candidate(
                e.code,
                e.name,
                e.region,
                self._combined(e, q_norm, q_folded, q_trigrams, region_hint, brand_tokens, q_vec),
            )
            for e in self._entries
        ]
        scored.sort(key=lambda c: c.score, reverse=True)
        top1 = scored[0]
        top2 = scored[1] if len(scored) > 1 else Candidate("", "", "", 0.0)
        exact = [e for e in self._entries if e.norm_name == q_norm]
        if len(exact) == 1:
            e = exact[0]
            return ResolveResult(status="resolved", code=e.code, name=e.name, region=e.region)
        if top1.score >= _FLOOR and (top1.score - top2.score) >= _MARGIN:
            return ResolveResult(status="resolved", code=top1.code, name=top1.name, region=top1.region)
        if top1.score >= _STRONG_FLOOR and (top1.score - top2.score) >= _STRONG_MARGIN:
            return ResolveResult(status="resolved", code=top1.code, name=top1.name, region=top1.region)
        if top1.score >= _AMBIG_FLOOR:
            cands = [c for c in scored if (top1.score - c.score) <= _AMBIG_DELTA][:_MAX_CANDIDATES]
            return ResolveResult(status="ambiguous", candidates=cands)
        if top1.score >= _GUESS_FLOOR and (top1.score - top2.score) >= _GUESS_MARGIN:
            return ResolveResult(status="not_found", message="Không tìm thấy dự án khớp.", candidates=[top1])
        return ResolveResult(status="not_found", message="Không tìm thấy dự án khớp.")
