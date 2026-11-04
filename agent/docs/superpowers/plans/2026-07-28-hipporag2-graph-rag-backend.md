# Plan: HippoRAG 2 graph-RAG backend (option cạnh hybrid, bật qua .env)

**Branch:** `feat/refactor2` · **Ngày:** 2026-07-28

## Mục tiêu

Thêm một backend RAG mới `NOBLE_RAG_BACKEND=hipporag` chạy song song với
`flat_store` / `qdrant` / `grep_faq` / `empty`. Backend này dựng một đồ thị tri
thức (KG) kiểu HippoRAG 2 từ chunk text của collection Qdrant clone
(`qdrant_collection`, mặc định `noble_kb_hybrid`), rồi tại query-time chỉ chạy
Personalized PageRank (PPR) — **không gọi LLM ở query-time** (giữ TTFA cho voice).

## Quyết định đã chốt (với user)

1. **Kích hoạt:** backend value mới `hipporag` (không phải cờ overlay).
2. **Nguồn KG:** LLM OpenIE trên chunk của collection Qdrant clone.
3. **Cập nhật KG:** gắn vào `noble-rag-sync`.
   - Mặc định = **incremental** (chỉ OpenIE chunk mới theo `content_hash`; chunk
     cũ không tốn lại token LLM).
   - Cờ `--renew-graph` = rebuild toàn bộ KG từ đầu.
4. **PPR:** power-iteration thuần `numpy` (không thêm dependency; scipy/igraph
     không có sẵn).
5. **Startup reconcile in-process (http.py) KHÔNG build KG** — KG chỉ được
     dựng/cập nhật qua console `noble-rag-sync` (tránh tốn LLM mỗi lần boot).
     Runtime load artifact KG có sẵn trên đĩa.

## Kiến trúc

```
OFFLINE (noble-rag-sync):
  reconcile() clone (như hiện tại)
  → build_or_update_graph(renew): scroll clone → chunk mới → OpenIE (LLM)
    → phrase nodes + passage nodes + edges → persist data/hipporag/graph.json

RUNTIME (backend=hipporag, per turn, KHÔNG LLM):
  query_hipporag_for_noble_kb
    → qdrant.search_hybrid  (seed passages + score)  [tái dùng nguyên si]
    → expander.expand(seed_hits): map seed→passage node, PPR trên KG tĩnh (numpy)
    → rank passages theo PPR, fuse RRF với ranking hybrid gốc
    → _format_hits  [tái dùng flat_store_adapter]
```

## Module mới: `agent/rag/hipporag/`

| File | Vai trò | Test |
|---|---|---|
| `graph.py` | `HippoGraph`: node (phrase/passage) + edge store; `add_triples`; `personalized_pagerank` (numpy CSR power-iter); `to_json`/`from_json`; incremental merge theo `content_hash`; `remove_passage` | pure — TDD |
| `openie.py` | `parse_triples(text)` (bóc JSON chịu fence/prose → `[]` khi hỏng); `extract(chunk_text, complete_fn)` gọi LLM (inject được) | parse pure — TDD |
| `builder.py` | `build_or_update_graph(chunks, extract_fn, graph=None, renew=False)` thuần over inputs; `run_sync(renew)` orchestration (đọc Qdrant clone + build LLM providers + persist) | build pure — TDD |
| `expander.py` | `_load()` singleton từ artifact; `expand(graph, seed_hits, ...)` → `list[SearchHit]` | pure — TDD |
| `adapter.py` | `query_hipporag_for_noble_kb(query, project_filter, top_k)` — seed qdrant hybrid → expand → fuse → format; degrade về hybrid thuần khi KG thiếu/lỗi | integration — monkeypatch |
| `__init__.py` | re-export | — |

## Wiring

- `config.py`: `noble_rag_backend` nhận `"hipporag"`; thêm settings
  `hipporag_graph_path`, `hipporag_ppr_alpha` (0.5), `hipporag_ppr_iters` (30),
  `hipporag_seed_k` (8), `hipporag_min_edge` (1), `hipporag_openie_max_tokens`
  (1024). Model OpenIE dùng chain LLM sẵn có (pin theo `NOBLE_AGENT_MODEL`).
- `noble_kb.py`: nhánh `backend == "hipporag" → _query_via_hipporag`.
- `qdrant_store.py`: thêm `iter_clone_points()` (mirror `iter_root_points`, đọc
  clone, trả `(id, payload)` — cần `content_hash`/`text`/`project_id`).
- `sparse_reconcile.py`: `main()` parse `--renew-graph`; sau `reconcile()` gọi
  `hipporag.builder.run_sync(renew=...)` (log-and-continue, không wedge sync).

## Bất biến giữ nguyên

- Output shape: `_format_hits` (`[Nguon N | Du an: X | Diem: 0.YZ] text`).
- Degrade: KG thiếu/lỗi → fallback về `query_qdrant_for_noble_kb` (không vỡ turn).
- Không LLM ở query-time. Không dependency mới.
- `content_hash` = khoá incremental; qdrant `point.id` = khoá seed-map runtime.

## TDD thứ tự

1. `test_hippograph.py` — add_triples, PPR hội tụ + seed-locality, json round-trip,
   incremental merge (chunk mới thêm node, chunk cũ skip), remove_passage.
2. `test_hipporag_openie.py` — parse_triples (JSON thuần / fenced / prose / rác→[]).
3. `test_hipporag_builder.py` — build_or_update_graph incremental vs renew với
   extract_fn giả (đếm số lần gọi = số chunk MỚI).
4. `test_hipporag_expander.py` — expand: seed passage lan sang passage cùng entity.
5. `test_hipporag_adapter.py` + `test_noble_kb_dispatch` — dispatch + fuse + degrade.
6. `test_reconcile_renew_graph_flag.py` — arg parse + gọi builder đúng cờ.

## Gate

`make test-unit` — zero new failure so baseline đã biết (2 USD-normalize, 2
qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:',
1 local-.env media). Ruff clean trên mọi file mới. Smoke `/chat` với
`NOBLE_RAG_BACKEND=hipporag` sau khi có artifact KG.
