"""Embedding seam — data/embed_client.

Pins the switch (EMBED_BACKEND) and each backend's wire shape. Sparse follows the
switch too — `service` loads no model, anything else runs in-process (fastembed).
Visual has no API equivalent, so it is service-only regardless.
"""
from __future__ import annotations

import httpx
import pytest

from noble_agent.data import embed_client as ec


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _FakeClient:
    def __init__(self, resp, cap):
        self._resp = resp
        self._cap = cap

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._cap["url"] = url
        self._cap["json"] = json
        self._cap["headers"] = headers
        return self._resp


def _http(monkeypatch, resp, cap):
    monkeypatch.setattr(ec.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp, cap))


@pytest.fixture
def cfg(monkeypatch):
    """Settings the module reads; each test overrides what it cares about."""
    s = ec.get_settings()
    monkeypatch.setattr(s, "embed_backend", "gemini", raising=False)
    monkeypatch.setattr(s, "embed_model", "", raising=False)
    monkeypatch.setattr(s, "embed_dim", 1024, raising=False)
    monkeypatch.setattr(s, "embed_timeout", 30.0, raising=False)
    monkeypatch.setattr(s, "embed_service_url", "http://embed:8013/embed", raising=False)
    monkeypatch.setattr(s, "embed_sparse_model", "Qdrant/bm25", raising=False)
    monkeypatch.setattr(s, "gemini_api_key", "gkey", raising=False)
    return s


class _SparseVec:
    def __init__(self, indices, values):
        self.indices = indices
        self.values = values


@pytest.fixture
def sparse_model(monkeypatch):
    """Stub the fastembed model; records loads so caching is observable."""
    seen: dict = {"loads": []}

    class _Stub:
        def embed(self, texts):
            seen["texts"] = texts
            return iter([_SparseVec([7, 3], [0.5, 0.25]) for _ in texts])

    def _fake_load(name):
        seen["loads"].append(name)
        return _Stub()

    monkeypatch.setattr(ec, "_load_sparse", _fake_load)
    return seen


# ── gemini (default dense backend) ───────────────────────────────────────────


async def test_gemini_request_shape(cfg, monkeypatch):
    cap: dict = {}
    _http(monkeypatch, _FakeResp({"embeddings": [{"values": [0.1, 0.2]}]}), cap)
    out = await ec.embed_dense(["hồ bơi"], side="query")
    assert out == [[0.1, 0.2]]
    assert "gemini-embedding-001:batchEmbedContents" in cap["url"]
    assert "key=gkey" in cap["url"]
    req = cap["json"]["requests"][0]
    assert req["content"]["parts"][0]["text"] == "hồ bơi"
    assert req["outputDimensionality"] == 1024
    assert req["taskType"] == "RETRIEVAL_QUERY"


async def test_gemini_index_side_uses_document_task(cfg, monkeypatch):
    """Query and document sides are different task types — mixing them shifts vectors."""
    cap: dict = {}
    _http(monkeypatch, _FakeResp({"embeddings": [{"values": [1.0]}]}), cap)
    await ec.embed_dense(["x"], side="index")
    assert cap["json"]["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"


async def test_gemini_honours_dim_and_model_override(cfg, monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(cfg, "embed_dim", 768, raising=False)
    monkeypatch.setattr(cfg, "embed_model", "custom-embed", raising=False)
    _http(monkeypatch, _FakeResp({"embeddings": [{"values": [1.0]}]}), cap)
    await ec.embed_dense(["x"], side="query")
    assert cap["json"]["requests"][0]["outputDimensionality"] == 768
    assert "custom-embed:batchEmbedContents" in cap["url"]


async def test_gemini_batches_all_texts(cfg, monkeypatch):
    cap: dict = {}
    _http(monkeypatch, _FakeResp({"embeddings": [{"values": [1.0]}, {"values": [2.0]}]}), cap)
    out = await ec.embed_dense(["a", "b"], side="query")
    assert len(cap["json"]["requests"]) == 2
    assert out == [[1.0], [2.0]]


async def test_gemini_without_key_raises(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "gemini_api_key", "", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        await ec.embed_dense(["x"], side="query")


# ── backend switch ───────────────────────────────────────────────────────────


async def test_backend_service_routes_dense_to_service(cfg, monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(cfg, "embed_backend", "service", raising=False)
    _http(monkeypatch, _FakeResp({"embeddings": [[0.5]]}), cap)
    out = await ec.embed_dense(["x"], side="query")
    assert cap["url"] == "http://embed:8013/embed"
    assert cap["json"] == {"side": "query", "kind": "dense", "texts": ["x"]}
    assert out == [[0.5]]


async def test_backend_hf_loads_local_model(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "embed_backend", "hf", raising=False)
    seen: dict = {}

    class _Stub:
        def encode(self, texts, normalize_embeddings=False):
            seen["texts"] = texts
            seen["norm"] = normalize_embeddings
            return [[0.1, 0.2]]

    def _fake_load(name):
        seen["model"] = name
        return _Stub()

    monkeypatch.setattr(ec, "_load_hf", _fake_load)
    out = await ec.embed_dense(["hồ bơi"], side="query")
    assert seen["model"] == "intfloat/multilingual-e5-large"  # backend default
    assert seen["texts"] == ["query: hồ bơi"]  # E5 prefix
    assert seen["norm"] is True
    assert out == [[0.1, 0.2]]


async def test_unknown_backend_raises(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "embed_backend", "bogus", raising=False)
    with pytest.raises(ValueError, match="unknown EMBED_BACKEND"):
        await ec.embed_dense(["x"], side="query")


# ── sparse: in-process ───────────────────────────────────────────────────────


async def test_sparse_runs_in_process_no_http(cfg, sparse_model, monkeypatch):
    """No embed service involved — a dead service must not break kb_search."""
    cap: dict = {}
    _http(monkeypatch, _FakeResp({}), cap)
    out = await ec.embed_sparse(["hồ bơi"], side="query")
    assert out == [{"indices": [7, 3], "values": [0.5, 0.25]}]
    assert sparse_model["texts"] == ["hồ bơi"]
    assert cap == {}  # no HTTP call at all


async def test_sparse_works_without_service_url(cfg, sparse_model, monkeypatch):
    monkeypatch.setattr(cfg, "embed_service_url", "", raising=False)
    assert await ec.embed_sparse(["x"], side="query") == [{"indices": [7, 3], "values": [0.5, 0.25]}]


async def test_sparse_uses_configured_model(cfg, sparse_model, monkeypatch):
    """Must match ingest's model or the term ids are a different vocabulary."""
    monkeypatch.setattr(cfg, "embed_sparse_model", "Qdrant/bm42-all-minilm-l6-v2-attentions", raising=False)
    await ec.embed_sparse(["x"], side="query")
    assert sparse_model["loads"] == ["Qdrant/bm42-all-minilm-l6-v2-attentions"]


async def test_sparse_rejects_bad_side(cfg, sparse_model):
    with pytest.raises(ValueError):
        await ec.embed_sparse(["x"], side="passage")


# ── sparse: service (EMBED_BACKEND=service must load NO model) ────────────────


async def test_sparse_via_service_when_backend_is_service(cfg, sparse_model, monkeypatch):
    """The whole point of EMBED_BACKEND=service: nothing is loaded in-process.

    Wire shape is the service's own (`kind=sparse`, response key `sparse`) — verified
    live to return bit-identical indices/values to fastembed, so ingest's term ids
    still match.
    """
    cap: dict = {}
    _http(monkeypatch, _FakeResp({"sparse": [{"indices": [9], "values": [1.66]}]}), cap)
    monkeypatch.setattr(cfg, "embed_backend", "service", raising=False)

    out = await ec.embed_sparse(["hồ bơi"], side="query")

    assert out == [{"indices": [9], "values": [1.66]}]
    assert cap["json"] == {"side": "query", "kind": "sparse", "texts": ["hồ bơi"]}
    assert sparse_model["loads"] == []  # no fastembed model touched


async def test_sparse_service_error_does_not_fall_back_to_local(cfg, sparse_model, monkeypatch):
    """Falling back would load the very model the flag says not to."""
    cap: dict = {}
    _http(monkeypatch, _FakeResp({}, status=500), cap)
    monkeypatch.setattr(cfg, "embed_backend", "service", raising=False)

    with pytest.raises(httpx.HTTPStatusError):
        await ec.embed_sparse(["x"], side="query")
    assert sparse_model["loads"] == []


def test_sparse_model_cached_per_name(monkeypatch):
    """Loading the ONNX model per call would cost real latency on the voice path."""
    ec._sparse_cache.clear()
    built: list[str] = []

    class _FakeSparse:
        def __init__(self, model_name):
            built.append(model_name)

    import sys
    import types

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(SparseTextEmbedding=_FakeSparse)
    )
    a = ec._load_sparse("m1")
    b = ec._load_sparse("m1")
    ec._load_sparse("m2")
    assert a is b
    assert built == ["m1", "m2"]
    ec._sparse_cache.clear()


# ── service-only kinds ───────────────────────────────────────────────────────


async def test_visual_text_always_uses_service_query_side(cfg, monkeypatch):
    cap: dict = {}
    _http(monkeypatch, _FakeResp({"embeddings": [[0.3]]}), cap)
    out = await ec.embed_visual_text(["x"])
    assert cap["json"] == {"side": "query", "kind": "visual_text", "texts": ["x"]}
    assert out == [[0.3]]


async def test_service_bearer_from_env(cfg, monkeypatch):
    cap: dict = {}
    monkeypatch.setenv("SANTA_MODELS_TOKEN", "tok")
    _http(monkeypatch, _FakeResp({"embeddings": []}), cap)
    await ec.embed_visual_text(["x"])
    assert cap["headers"] == {"Authorization": "Bearer tok"}


async def test_service_no_token_omits_header(cfg, monkeypatch):
    cap: dict = {}
    monkeypatch.delenv("SANTA_MODELS_TOKEN", raising=False)
    _http(monkeypatch, _FakeResp({"embeddings": []}), cap)
    await ec.embed_visual_text(["x"])
    assert cap["headers"] == {}


async def test_service_url_unset_raises_naming_the_kind(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "embed_service_url", "", raising=False)
    with pytest.raises(ValueError, match="visual_text"):
        await ec.embed_visual_text(["x"])


# ── shared behaviour ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "call",
    [
        lambda: ec.embed_dense([], side="query"),
        lambda: ec.embed_sparse([], side="query"),
        lambda: ec.embed_visual_text([]),
    ],
)
async def test_empty_input_short_circuits(cfg, monkeypatch, call):
    """No text → no request at all."""
    cap: dict = {}
    _http(monkeypatch, _FakeResp({}), cap)
    assert await call() == []
    assert cap == {}


async def test_bad_side_rejected_before_request(cfg, monkeypatch):
    cap: dict = {}
    _http(monkeypatch, _FakeResp({}), cap)
    with pytest.raises(ValueError):
        await ec.embed_dense(["x"], side="passage")
    assert cap == {}


async def test_missing_response_key_returns_empty(cfg, monkeypatch):
    _http(monkeypatch, _FakeResp({}), {})
    assert await ec.embed_dense(["x"], side="query") == []
    _http(monkeypatch, _FakeResp({}), {})
    assert await ec.embed_visual_text(["x"]) == []


async def test_http_error_propagates(cfg, monkeypatch):
    _http(monkeypatch, _FakeResp({}, status=500), {})
    with pytest.raises(httpx.HTTPError):
        await ec.embed_dense(["x"], side="query")
