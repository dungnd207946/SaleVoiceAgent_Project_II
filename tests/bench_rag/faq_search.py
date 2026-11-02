"""FAQ search — load per-project JSON from data/faq/source/, encode with e5-large (share FlatStore session),
top-K retrieval with threshold. Disk cache at data/faq_cache/."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "faq" / "source"
CACHE_DIR = ROOT / "data" / "faq_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class FAQItem:
    id: str
    project: str
    category: str
    question: str
    answer: str


def _file_to_project(p: Path) -> str:
    # nclb_faq.json -> NCLB
    stem = p.stem.upper()
    return stem.replace("_FAQ", "")


def _load_project_items(project: str) -> list[FAQItem]:
    path = SOURCE_DIR / f"{project.lower()}_faq.json"
    if not path.exists():
        logger.warning("[faq_search] missing source: %s", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items: list[FAQItem] = []
        for r in raw:
            if not r.get("question") or not r.get("answer"):
                continue
            items.append(
                FAQItem(
                    id=r.get("id", ""),
                    project=r.get("project", project).upper(),
                    category=r.get("category", ""),
                    question=r["question"].strip(),
                    answer=r["answer"].strip(),
                )
            )
        return items
    except Exception as e:
        logger.warning("[faq_search] parse failed %s: %s", path, e)
        return []


def _items_hash(items: list[FAQItem]) -> str:
    h = hashlib.sha256()
    for it in items:
        h.update(it.id.encode("utf-8"))
        h.update(b"|")
        h.update(it.question.encode("utf-8"))
    return h.hexdigest()[:10]


class FaqSearcher:
    """e5-large based retriever over FAQ items. Shares FlatStore's embedder."""

    DEFAULT_PROJECTS = ["NCLB", "NCTH", "NPLB", "NTTL", "SSLC"]

    def __init__(self):
        self._items_by_proj: dict[str, list[FAQItem]] = {}
        self._emb_by_proj: dict[str, np.ndarray] = {}
        self._indexed = False
        self._encoder = None

    async def _get_encoder(self):
        if self._encoder is not None:
            return self._encoder
        # Share FlatStore's embedder (e5-large fastembed)
        from bench_rag.flat_store_runner import get_flat_store

        store = await get_flat_store()
        self._encoder = store.embedder
        return self._encoder

    async def ensure_indexed(self, projects: list[str] | None = None) -> int:
        if self._indexed:
            return sum(len(v) for v in self._items_by_proj.values())
        projects = projects or self.DEFAULT_PROJECTS
        encoder = await self._get_encoder()
        total = 0
        for proj in projects:
            items = _load_project_items(proj)
            if not items:
                continue
            self._items_by_proj[proj] = items
            total += len(items)
            # Cache
            ih = _items_hash(items)
            cache_path = CACHE_DIR / f"{proj}_e5large_{ih}.npz"
            if cache_path.exists():
                try:
                    data = np.load(cache_path)
                    self._emb_by_proj[proj] = data["emb"]
                    logger.info("[faq_search] %s: cache hit (%d items)", proj, len(items))
                    continue
                except Exception as e:
                    logger.warning("[faq_search] cache read failed %s: %s", cache_path, e)

            # Encode (question only — cleaner semantic match than Q+A blend)
            texts = [f"query: {it.question}" for it in items]  # e5 query-style for search matching
            logger.info("[faq_search] %s: encoding %d items", proj, len(items))
            t0 = time.monotonic()
            loop = asyncio.get_event_loop()
            emb = await loop.run_in_executor(None, encoder.encode_batch, texts)
            # Normalize
            norms = np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12
            emb = (emb / norms).astype(np.float32)
            self._emb_by_proj[proj] = emb
            try:
                np.savez_compressed(cache_path, emb=emb)
            except Exception as e:
                logger.warning("[faq_search] cache save failed: %s", e)
            logger.info("[faq_search] %s: encoded in %.1fs", proj, time.monotonic() - t0)

        self._indexed = True
        return total

    async def search(
        self,
        query: str,
        project_filter: str | list[str],
        top_k: int = 5,
        threshold: float = 0.35,
    ) -> list[tuple[FAQItem, float]]:
        if not self._indexed:
            await self.ensure_indexed()
        from noble_agent.agent import project_catalog as _catalog

        if isinstance(project_filter, str):
            raw_list = [p.strip() for p in project_filter.split(",") if p.strip()]
        else:
            raw_list = [p.strip() for p in project_filter if p]
        projects = [code for code in (_catalog.normalize(p) for p in raw_list) if code]
        projects = [p for p in projects if p in self._items_by_proj]
        if not projects:
            return []

        encoder = await self._get_encoder()
        loop = asyncio.get_event_loop()
        q_vec = await loop.run_in_executor(None, lambda: encoder.encode_query(f"query: {query}"))
        q_vec = q_vec / (np.linalg.norm(q_vec) + 1e-12)

        all_hits: list[tuple[FAQItem, float]] = []
        for proj in projects:
            emb = self._emb_by_proj[proj]
            items = self._items_by_proj[proj]
            scores = emb @ q_vec
            for i, s in enumerate(scores):
                if float(s) >= threshold:
                    all_hits.append((items[i], float(s)))
        all_hits.sort(key=lambda x: x[1], reverse=True)
        return all_hits[:top_k]

    def format_block(self, hits: list[tuple[FAQItem, float]], project_filter: str | list[str]) -> str:
        if not hits:
            return ""
        from noble_agent.agent import project_catalog as _catalog

        raw = project_filter if isinstance(project_filter, list) else [project_filter]
        names: list[str] = []
        for raw_p in raw:
            code = _catalog.normalize(raw_p)
            meta = _catalog.by_code(code)
            if meta:
                names.append(meta.name_vi)
        proj_display = ", ".join(names) if names else "ALL"
        lines = [
            f"═══ FAQ KHỚP NHẤT ({proj_display}) ═══",
            "Nếu câu khách trùng Q dưới đây → trả lời ngay từ A, KHÔNG gọi tool.",
            "Nếu KHÔNG trùng → dùng tool theo SKILL guidance.",
            "",
        ]
        for it, _score in hits:
            lines.append(f"**Q:** {it.question}")
            lines.append(f"**A:** {it.answer}")
            lines.append("")
        lines.append("═══ END FAQ ═══")
        return "\n".join(lines)


# Singleton accessor
_SEARCHER: FaqSearcher | None = None


async def get_searcher() -> FaqSearcher:
    global _SEARCHER
    if _SEARCHER is None:
        _SEARCHER = FaqSearcher()
    return _SEARCHER


async def inject_faq_searched(
    query: str,
    project_filter: str | list[str],
    top_k: int = 5,
    threshold: float = 0.35,
) -> str:
    """Convenience: search FAQ for query+project, return formatted block or ''."""
    s = await get_searcher()
    hits = await s.search(query, project_filter, top_k=top_k, threshold=threshold)
    return s.format_block(hits, project_filter)
