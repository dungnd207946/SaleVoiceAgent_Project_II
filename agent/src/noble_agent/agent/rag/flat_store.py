"""In-process flat vector store for ~4k chunks.

Design (see docs/analysis/livekit_pipeline_comparison.md §35-§40):
- Load all chunks from santa-chat-agent LightRAG JSON export.
- Encode once with e5-large (via fastembed ONNX INT8 if available, else sentence-transformers).
- Cache embeddings to .npy on disk — subsequent boots skip encoding.
- Cosine similarity via single `embeddings @ q_vec` numpy matmul.
- Exact L1 query-hash cache in-process (dict, LRU cap).

Scale premise: 3,741 chunks × 1024d × 4B ≈ 15 MB — fits CPU L3 cache,
matmul <2 ms on AVX2 CPUs. No vector DB needed until >50k chunks.

Ported from voiceagentrag/src/agent/rag/flat_store.py (rev 3 step 5).
Only behavioural change: default data_dir + cache_dir resolve to sh repo
root (parents[4] vs vag's parents[3] — sh has extra `noble_agent/` package).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# Load project .env so these C-extension env vars (read via os.getenv, NOT
# pydantic settings) take effect without needing `export` in the shell. Must
# happen BEFORE `from fastembed import ...`. Restricted to exactly these keys:
# loading the whole .env into os.environ would clobber unrelated settings
# globally and override code defaults in tests that build
# UnifiedSettings(_env_file=None).
_DOTENV_KEYS = {
    "FASTEMBED_CACHE_PATH",
    "FLAT_STORE_MODEL",
    "FLAT_STORE_CACHE_DIR",
    "HF_TOKEN",
    "SANTA_CHAT_DATA_DIR",
}


def _load_project_dotenv() -> None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        env_path = parent / ".env"
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, raw = line.partition("=")
                    key = key.strip()
                    raw = raw.strip()
                    if raw[:1] in ("'", '"'):
                        # Quoted value: take content verbatim (no inline-comment handling).
                        val = raw.strip('"').strip("'")
                    else:
                        # Unquoted: strip a whitespace-preceded inline comment (dotenv
                        # convention) — a bare `#` inside a value (e.g. a URL fragment) is data.
                        val = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
                    if key in _DOTENV_KEYS and key not in os.environ:
                        os.environ[key] = os.path.expanduser(val)
            except Exception:
                pass
            break


_load_project_dotenv()


def _expand_home_paths_in_env() -> None:
    # onnxruntime and many C-extension libs don't expand `~` themselves —
    # normalize any home-relative env var (set by .env, python-dotenv, or
    # the shell) so consumers always see an absolute path.
    for k, v in list(os.environ.items()):
        if v.startswith("~/") or v == "~":
            os.environ[k] = os.path.expanduser(v)


_expand_home_paths_in_env()

logger = logging.getLogger("rag.flat_store")

# Optional hybrid deps
try:
    import bm25s  # type: ignore

    _HAS_BM25S = True
except ImportError:
    _HAS_BM25S = False

try:
    from pyvi.ViTokenizer import tokenize as _vi_tokenize  # type: ignore

    _HAS_PYVI = True
except ImportError:
    _HAS_PYVI = False


def _tokenize_vi(text: str) -> list[str]:
    """Vietnamese tokenize: pyvi if available, else whitespace."""
    text = text.lower()
    if _HAS_PYVI:
        return _vi_tokenize(text).split()
    return text.split()


# ─── Defaults ───────────────────────────────────────────────────────────────
# parents[4] = repo root (src/noble_agent/agent/rag/flat_store.py → up 4 levels).
# Default points to sh's local data/rag/ (symlinks to NobleX/santa-chat-agent
# checkout). Override via SANTA_CHAT_DATA_DIR for prod / different layout.
DEFAULT_SANTA_DATA = Path(
    os.environ.get(
        "SANTA_CHAT_DATA_DIR",
        str(Path(__file__).resolve().parents[4] / "data" / "rag"),
    )
)
PROJECT_MAP = {
    "crystal_tay_ho": "NCTH",
    "noble_crystal_long_bien": "NCLB",
    "noble_palace_long_bien": "NPLB",
    "noble_palace_tay_thang_long": "NPTTL",
    "noble_sunshine_legend_city": "SLC",
    "noble_crystal_riverside": "NCR",
    "noble_palace_tay_ho": "NPTH",
    "sunshine_sky_city": "SSC",
    "sunshine_golden_river": "SGR",
    "sunshine_green_iconic": "SGI",
    "sunshine_river_park": "SRP",
    "sunshine_city_ha_noi": "SCHN",
    "sunshine_bay_retreat": "SBR",
    "alluvia_sunshine_marina": "ASM",
    "alumi": "ALM",
}
DEFAULT_CACHE_DIR = Path(
    os.environ.get(
        "FLAT_STORE_CACHE_DIR",
        str(Path(__file__).resolve().parents[4] / "data" / "flat_store"),
    )
)


@dataclass
class Chunk:
    id: str
    project: str
    text: str
    tokens: int | None = None
    chunk_order: int | None = None
    full_doc_id: str | None = None
    is_faq: bool = False


def _detect_faq(content: str) -> bool:
    if not content:
        return False
    head = content[:400]
    return '_faq"' in head or "_FAQ" in head or "_faq |" in head


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


# ─── Embedder abstraction ───────────────────────────────────────────────────
DEFAULT_MODEL = os.environ.get("FLAT_STORE_MODEL", "intfloat/multilingual-e5-large")


class _Embedder:
    """Wraps fastembed (preferred) or sentence-transformers fallback.

    Default model: `intfloat/multilingual-e5-large` (1024d, ~100 langs incl. Vietnamese).
    Supported natively by fastembed ONNX INT8.

    Note: BGE-M3 is NOT supported by fastembed — use sentence-transformers
    if you want BGE-M3 specifically (slower, ~40-80ms/query CPU).
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, threads: int = 4):
        self.model_name = model_name
        self.threads = threads
        self._backend = None
        self._impl = None
        self._remote_url = ""
        self._remote_timeout = 10.0
        self._remote_token = ""

    def load(self):
        if self._impl is not None or self._backend == "remote":
            return

        # Remote-first: if a sidecar URL is configured, skip local load entirely.
        # See infra/runpod/embed_server.py for the sidecar implementation.
        import os

        remote_url = os.environ.get("EMBED_REMOTE_URL", "").strip()
        if not remote_url:
            try:
                from noble_agent.config import settings as _s

                remote_url = getattr(_s, "embed_remote_url", "") or ""
                self._remote_timeout = float(getattr(_s, "embed_remote_timeout", 10.0))
            except Exception:
                pass
        if remote_url:
            import httpx

            self._remote_url = remote_url.rstrip("/")
            # Bearer token for the embed service (empty → no Authorization header).
            token = os.environ.get("EMBED_REMOTE_TOKEN", "").strip()
            if not token:
                try:
                    from noble_agent.config import settings as _s

                    token = (getattr(_s, "embed_remote_token", "") or "").strip()
                except Exception:
                    pass
            self._remote_token = token
            headers = {"Authorization": f"Bearer {token}"} if token else None
            self._impl = httpx.Client(timeout=self._remote_timeout, headers=headers)
            self._backend = "remote"
            logger.info(
                "remote embedder → %s (model=%s, auth=%s)",
                self._remote_url,
                self.model_name,
                "yes" if token else "no",
            )
            return

        try:
            from fastembed import TextEmbedding

            t0 = time.monotonic()
            self._impl = TextEmbedding(model_name=self.model_name, threads=self.threads)
            self._backend = "fastembed"
            logger.info("fastembed loaded %s (%.2fs)", self.model_name, time.monotonic() - t0)
            return
        except ImportError:
            pass
        try:
            from sentence_transformers import SentenceTransformer

            t0 = time.monotonic()
            self._impl = SentenceTransformer(self.model_name)
            self._backend = "sentence_transformers"
            logger.info(
                "sentence-transformers loaded %s (%.2fs)",
                self.model_name,
                time.monotonic() - t0,
            )
            return
        except ImportError as e:
            raise RuntimeError(
                "Need either `fastembed` or `sentence-transformers`, "
                "or set EMBED_REMOTE_URL to a sidecar. "
                "pip install fastembed  (recommended)"
            ) from e

    def _encode_remote(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        """POST texts to the embed service and return a float32 matrix.

        Body ``{"texts":[...],"is_query":bool}``; the service applies the e5
        query/passage handling and returns L2-normalized vectors as
        ``{"embeddings": [[...], ...]}``.
        """
        resp = self._impl.post(
            f"{self._remote_url}/embed",
            json={"texts": texts, "is_query": is_query},
        )
        resp.raise_for_status()
        data = resp.json()
        vecs = np.asarray(data["embeddings"], dtype=np.float32)
        return vecs

    def encode_batch(self, texts: list[str], batch_size: int = 32, show_progress: bool = True) -> np.ndarray:
        self.load()
        total = len(texts)

        if self._backend == "remote":
            # Remote service already returns L2-normalized vectors; batch in
            # chunks of 64 so a huge corpus encode doesn't exceed the HTTP
            # request size limit of the sidecar.
            out: list[np.ndarray] = []
            for i in range(0, total, 64):
                out.append(self._encode_remote(texts[i : i + 64], is_query=False))
            return np.concatenate(out, axis=0) if out else np.zeros((0, 1024), dtype=np.float32)

        if self._backend == "fastembed":
            # Encode batch-by-batch to expose progress. fastembed returns a generator.
            out: list[np.ndarray] = []
            t0 = time.monotonic()
            last_print = 0.0
            gen = self._impl.embed(texts, batch_size=batch_size)
            for i, vec in enumerate(gen):
                out.append(np.asarray(vec, dtype=np.float32))
                done = i + 1
                now = time.monotonic()
                if show_progress and (now - last_print >= 1.0 or done == total):
                    elapsed = now - t0
                    rate = done / max(elapsed, 1e-3)
                    eta = (total - done) / max(rate, 1e-3)
                    bar_len = 30
                    filled = int(bar_len * done / total)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    print(
                        f"\r  encoding [{bar}] {done:>5}/{total}  "
                        f"{rate:6.1f} it/s  ETA {eta:6.1f}s  elapsed {elapsed:6.1f}s",
                        end="",
                        flush=True,
                    )
                    last_print = now
            if show_progress:
                print()
            vecs = np.stack(out, axis=0)
        else:
            vecs = self._impl.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=show_progress,
            ).astype(np.float32)
        # Safety renormalize
        norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
        return vecs / norms

    def encode_query(self, text: str) -> np.ndarray:
        self.load()
        if self._backend == "remote":
            vecs = self._encode_remote([text], is_query=True)
            return vecs[0].astype(np.float32)
        if self._backend == "fastembed":
            if hasattr(self._impl, "query_embed"):
                vec = next(iter(self._impl.query_embed([text])))
            else:
                vec = next(iter(self._impl.embed([text])))
        else:
            vec = self._impl.encode(text, normalize_embeddings=True, show_progress_bar=False)
        vec = np.asarray(vec, dtype=np.float32)
        vec /= np.linalg.norm(vec) + 1e-12
        return vec

    @property
    def backend(self) -> str:
        return self._backend or "unloaded"


# ─── Flat store ─────────────────────────────────────────────────────────────
class FlatStore:
    def __init__(
        self,
        data_dir: Path = DEFAULT_SANTA_DATA,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        model_name: str = DEFAULT_MODEL,
        threads: int = 4,
        query_cache_size: int = 1000,
        skip_faq: bool = False,
    ):
        self.skip_faq = skip_faq
        self.data_dir = Path(data_dir)
        self.cache_dir = Path(cache_dir)
        self.model_name = model_name
        self.embedder = _Embedder(model_name, threads=threads)
        self.chunks: list[Chunk] = []
        self.embeddings: np.ndarray | None = None
        self.project_idx: dict[str, np.ndarray] = {}
        self._query_cache: OrderedDict[str, list[SearchHit]] = OrderedDict()
        self._query_cache_size = query_cache_size
        self.stats = {"cache_hit": 0, "cache_miss": 0, "embed_ms_total": 0.0}
        self.bm25_retriever = None  # lazy loaded via .load_bm25()

    # — Data loading —
    def _load_chunks_from_disk(self) -> list[Chunk]:
        rows: list[Chunk] = []
        for key, code in PROJECT_MAP.items():
            path = self.data_dir / f"lightrag_s02_{key}" / key / "kv_store_text_chunks.json"
            if not path.exists():
                logger.warning("Missing chunk file: %s", path)
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            for chunk_id, payload in data.items():
                content = payload.get("content", "")
                is_faq = _detect_faq(content)
                if self.skip_faq and is_faq:
                    continue
                rows.append(
                    Chunk(
                        id=chunk_id,
                        project=code,
                        text=content,
                        tokens=payload.get("tokens"),
                        chunk_order=payload.get("chunk_order_index"),
                        full_doc_id=payload.get("full_doc_id"),
                        is_faq=is_faq,
                    )
                )
        return rows

    def load(self, force_reencode: bool = False) -> None:
        self.chunks = self._load_chunks_from_disk()
        if not self.chunks:
            raise RuntimeError(f"No chunks loaded from {self.data_dir}")

        safe_model = self.model_name.replace("/", "__")
        tag = "_nofaq" if self.skip_faq else ""
        emb_cache = self.cache_dir / f"embeddings_{safe_model}{tag}.npy"
        meta_cache = self.cache_dir / f"meta_{safe_model}{tag}.json"

        meta_now = {
            "count": len(self.chunks),
            "model": self.model_name,
            "chunk_ids_sample": [c.id for c in self.chunks[:5]],
        }

        if emb_cache.exists() and meta_cache.exists() and not force_reencode:
            try:
                meta_old = json.loads(meta_cache.read_text())
                if meta_old == meta_now:
                    self.embeddings = np.load(emb_cache).astype(np.float32)
                    logger.info("Loaded %d embeddings from cache %s", len(self.chunks), emb_cache)
            except Exception as exc:
                logger.warning("Cache load failed: %s — will re-encode", exc)
                self.embeddings = None

        if self.embeddings is None:
            logger.info("Encoding %d chunks with %s (one-time)…", len(self.chunks), self.model_name)
            t0 = time.monotonic()
            self.embeddings = self.embedder.encode_batch([c.text for c in self.chunks], batch_size=32)
            logger.info("Encoded in %.1fs", time.monotonic() - t0)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            np.save(emb_cache, self.embeddings)
            meta_cache.write_text(json.dumps(meta_now, indent=2))

        assert self.embeddings.shape == (len(self.chunks), self.embeddings.shape[1])

        arr = np.array([c.project for c in self.chunks])
        for p in set(PROJECT_MAP.values()):
            self.project_idx[p] = np.where(arr == p)[0]

    def load_chunks_only(self) -> None:
        """Load chunks + project_idx WITHOUT dense embeddings.

        For the qdrant backend, where Qdrant owns the dense signal and only
        BM25 + chunk metadata (text, project, chunk_id) stay local for RRF
        fusion. Leaves ``self.embeddings`` as None.
        """
        self.chunks = self._load_chunks_from_disk()
        if not self.chunks:
            raise RuntimeError(f"No chunks loaded from {self.data_dir}")
        arr = np.array([c.project for c in self.chunks])
        for p in set(PROJECT_MAP.values()):
            self.project_idx[p] = np.where(arr == p)[0]

    # — Public search —
    def search(self, query: str, project_filter: str = "", top_k: int = 5) -> list[SearchHit]:
        assert self.embeddings is not None, "Call .load() first"
        cache_key = hashlib.sha256(f"{query}|{project_filter}|{top_k}".encode()).hexdigest()

        cached = self._query_cache.get(cache_key)
        if cached is not None:
            self._query_cache.move_to_end(cache_key)
            self.stats["cache_hit"] += 1
            return cached

        self.stats["cache_miss"] += 1

        t0 = time.perf_counter()
        q_vec = self.embedder.encode_query(query)
        self.stats["embed_ms_total"] += (time.perf_counter() - t0) * 1000

        if project_filter and project_filter in self.project_idx:
            idx = self.project_idx[project_filter]
            sub_emb = self.embeddings[idx]
            scores = sub_emb @ q_vec
            k = min(top_k, len(scores))
            top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(k)
            top = top[np.argsort(-scores[top])]
            hits = [SearchHit(chunk=self.chunks[int(idx[i])], score=float(scores[i])) for i in top]
        else:
            scores = self.embeddings @ q_vec
            k = min(top_k, len(scores))
            top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(k)
            top = top[np.argsort(-scores[top])]
            hits = [SearchHit(chunk=self.chunks[int(i)], score=float(scores[i])) for i in top]

        self._query_cache[cache_key] = hits
        if len(self._query_cache) > self._query_cache_size:
            self._query_cache.popitem(last=False)
        return hits

    def clear_cache(self) -> None:
        self._query_cache.clear()
        self.stats = {"cache_hit": 0, "cache_miss": 0, "embed_ms_total": 0.0}

    # ─── Hybrid BM25 ────────────────────────────────────────────────────────
    def _bm25_cache_dir(self) -> Path:
        tag = "_nofaq" if self.skip_faq else ""
        return self.cache_dir / f"bm25_index{tag}"

    def build_bm25(self) -> None:
        """Offline: build BM25 index over current chunks. Save to disk."""
        if not _HAS_BM25S:
            raise RuntimeError("pip install bm25s pyvi")
        assert self.chunks, "Call .load() first"
        logger.info(
            "Building BM25 index over %d chunks (pyvi=%s)…",
            len(self.chunks),
            _HAS_PYVI,
        )
        t0 = time.monotonic()
        tokenized = [_tokenize_vi(c.text) for c in self.chunks]
        retriever = bm25s.BM25(method="lucene")
        retriever.index(tokenized)
        out = self._bm25_cache_dir()
        out.mkdir(parents=True, exist_ok=True)
        retriever.save(str(out))
        logger.info("BM25 built in %.1fs → %s", time.monotonic() - t0, out)
        self.bm25_retriever = retriever

    def load_bm25(self, build_if_missing: bool = True) -> None:
        if not _HAS_BM25S:
            raise RuntimeError("pip install bm25s pyvi")
        path = self._bm25_cache_dir()
        if not path.exists():
            if build_if_missing:
                self.build_bm25()
                return
            raise FileNotFoundError(f"BM25 index not found at {path}. Call build_bm25() first.")
        t0 = time.monotonic()
        self.bm25_retriever = bm25s.BM25.load(str(path))
        logger.info("BM25 loaded from %s (%.2fs)", path, time.monotonic() - t0)

    def _dense_topk(self, q_vec: np.ndarray, project_filter: str, k: int) -> list[tuple[int, float]]:
        if project_filter and project_filter in self.project_idx:
            idx = self.project_idx[project_filter]
            scores = self.embeddings[idx] @ q_vec
            kk = min(k, len(scores))
            top = np.argpartition(-scores, kk - 1)[:kk] if kk < len(scores) else np.arange(kk)
            top = top[np.argsort(-scores[top])]
            return [(int(idx[i]), float(scores[i])) for i in top]
        scores = self.embeddings @ q_vec
        kk = min(k, len(scores))
        top = np.argpartition(-scores, kk - 1)[:kk] if kk < len(scores) else np.arange(kk)
        top = top[np.argsort(-scores[top])]
        return [(int(i), float(scores[i])) for i in top]

    def _bm25_topk(self, query: str, project_filter: str, k: int) -> list[tuple[int, float]]:
        assert self.bm25_retriever is not None, "Call load_bm25() first"
        q_tokens = _tokenize_vi(query)
        # Over-fetch if filter so we have enough after filtering
        over_k = k * 5 if project_filter else k
        ids_arr, scores_arr = self.bm25_retriever.retrieve([q_tokens], k=min(over_k, len(self.chunks)))
        ids = ids_arr[0].tolist()
        scores = scores_arr[0].tolist()
        if project_filter and project_filter in self.project_idx:
            allowed = set(self.project_idx[project_filter].tolist())
            filtered = [(i, s) for i, s in zip(ids, scores) if i in allowed]
            return filtered[:k]
        return list(zip(ids, scores))[:k]

    def search_hybrid(
        self,
        query: str,
        project_filter: str = "",
        top_k: int = 5,
        candidates: int = 20,
        rrf_k: int = 60,
    ) -> list[SearchHit]:
        """Dense + BM25 with Reciprocal Rank Fusion."""
        if self.bm25_retriever is None:
            self.load_bm25()
        # Dense
        q_vec = self.embedder.encode_query(query)
        dense_hits = self._dense_topk(q_vec, project_filter, candidates)
        # Sparse
        sparse_hits = self._bm25_topk(query, project_filter, candidates)
        # RRF
        rrf: dict[int, float] = {}
        dense_score: dict[int, float] = {}
        for rank, (cid, s) in enumerate(dense_hits):
            rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (rrf_k + rank)
            dense_score[cid] = s
        for rank, (cid, _) in enumerate(sparse_hits):
            rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (rrf_k + rank)
        fused = sorted(rrf.items(), key=lambda x: -x[1])[:top_k]
        return [SearchHit(chunk=self.chunks[cid], score=dense_score.get(cid, float(s))) for cid, s in fused]


# ─── Singleton ──────────────────────────────────────────────────────────────
_store: FlatStore | None = None


def get_flat_store() -> FlatStore:
    global _store
    if _store is None:
        _store = FlatStore()
        _store.load()
    return _store


def format_hits(hits: list[SearchHit], max_chars: int = 1200) -> str:
    if not hits:
        return "Không tìm thấy thông tin liên quan."
    lines = []
    for i, h in enumerate(hits, 1):
        snippet = h.chunk.text
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars] + "…"
        lines.append(f"[Nguồn {i} | Dự án: {h.chunk.project} | Điểm: {h.score:.3f}]\n{snippet}")
    return "\n\n".join(lines)
