# HippoRAG triple embedding trên Qdrant (flag-gated)

**Ngày:** 2026-07-29
**Branch:** `feat/refactor2`
**Phạm vi:** `src/noble_agent/agent/rag/hipporag/` + `agent/rag/qdrant_store.py` + `config.py`

## Vấn đề

Triple embedding của HippoRAG (dùng cho sparse triple-seed, `HIPPORAG_SPARSE_SEED_ENABLED`)
hiện được lưu trong một numpy sidecar local `<graph>.triple_emb.npz` cạnh `graph.json`:

- **Build** (`noble-rag-sync`): `builder.build_and_save_triple_index` embed mỗi triple
  ("subject relation object") → `triple_index.save_triple_index` ghi npz, căn theo
  `(s_key, o_key)` của mỗi triple.
- **Query** (`adapter._sparse_seed`): `expander.load_triple_index()` nạp npz vào RAM →
  `TripleIndex.search(query_vec, top_m)` cosine bằng numpy matmul, trả top-M
  `(s_key, o_key, score)`; mỗi triple seed PPR tại CẢ HAI phrase node.

Sidecar `.npz` là artifact local: phải build/ship/mount trên mỗi máy query. Toàn bộ
stack RAG còn lại (dense + BM25 sparse) đã nằm trên Qdrant clone (single source of
truth). Ta muốn chuyển triple embedding lên Qdrant để runtime query không phụ thuộc
file local.

**Ngoài phạm vi:** `graph.json` (cấu trúc đồ thị phrase↔passage + adjacency) VẪN là
artifact local — chỉ triple *embedding* chuyển lên Qdrant. Nếu về sau muốn bỏ hẳn
local, graph là một effort riêng.

## Quyết định thiết kế

| Quyết định | Chọn | Lý do |
|---|---|---|
| Migration | Flag-gated, giữ local làm backup | Rollback bằng 1 env var; đúng phong cách degrade-gracefully của codebase |
| Vòng đời collection | Recreate + fill mỗi sync | Triple đổi theo graph; drop-fill tránh triple cũ tồn đọng (mirror `recreate_clone`) |
| Build store nào | Build CẢ HAI (npz + Qdrant) mỗi sync | Backup local có dữ liệu thật; toggle `HIPPORAG_TRIPLE_STORE` không cần rebuild |
| Chuỗi fallback query | `qdrant → local → hybrid` | Qdrant lỗi vẫn dùng npz; cả hai rỗng thì sparse-seed no-op (pipeline chạy tiếp) |
| Payload point | `{s, o, text}` | Tối thiểu `s`/`o` để seed PPR; `text` thêm để soi/debug trên Qdrant |

## Kiến trúc

### 1. Config (`config.py`) — thêm 2 setting

```python
hipporag_triple_store: str = "local"          # env HIPPORAG_TRIPLE_STORE: "local" | "qdrant"
qdrant_triple_collection: str = "noble_kb_hipporag_triples"   # env QDRANT_TRIPLE_COLLECTION
```

`hipporag_triple_store` chọn nguồn ĐỌC lúc query. Default `local` → hành vi hiện tại,
zero behaviour change khi chưa set env.

### 2. Qdrant store (`qdrant_store.py`) — thêm 3 hàm, KHÔNG đụng hàm cũ

Collection triple là collection RIÊNG (tách khỏi clone `qdrant_collection`), dense-only,
vector **unnamed** (mặc định), `distance=Cosine` (tương đương dot-product trên emb đã
chuẩn hóa mà `TripleIndex` đang làm).

```python
async def recreate_triple_collection(dim: int) -> None:
    """Drop + create collection triple: 1 dense vector unnamed, distance=Cosine, size=dim.
    Mirror recreate_clone nhưng không sparse, không payload index."""

async def upsert_triples(points: list) -> None:
    """Upsert batch PointStruct vào qdrant_triple_collection."""

async def search_triples(query_vec: list[float], top_m: int) -> list[tuple[str, str, float]]:
    """1 lần query_points limit=top_m trên collection triple, đọc payload → [(s, o, score)].
    Ném exception nếu collection thiếu / Qdrant lỗi (caller bắt để fallback local)."""
```

- Point: `id = <index tuần tự 0..N-1>`, `vector = <emb triple>`, `payload = {"s": s_key, "o": o_key, "text": triple_text}`.
- `search_triples` trả raw `(s, o, score)`; KHÔNG lọc `score<=0` ở đây — lọc giữ chung
  trong `_sparse_seed` (đúng như đường local).

### 3. Build (`builder.py`) — build cả hai store mỗi sync

Giữ nguyên `_build_triple_index_from_embedder` (npz). Thêm:

```python
async def _build_triple_qdrant(graph: HippoGraph) -> None:
    """Embed triple bằng _Embedder (remote-aware), recreate_triple_collection(dim),
    upsert_triples. Best-effort try/except như bản npz — lỗi chỉ để lại Qdrant-triple
    rỗng (runtime tự fallback về local)."""
```

- Reuse cùng `_Embedder` với bản npz để dim/không gian embedding khớp hệt.
- `dim` lấy từ `emb.shape[1]`.
- `triples = graph.triples`; rỗng → no-op (không tạo collection).
- Gọi trong `run_sync` NGAY SAU `_build_triple_index_from_embedder(graph, path)`.
  Vì `run_sync` luôn có Qdrant (đã đọc clone), việc build luôn cả hai là an toàn.
- Embed 1 lần, dùng cho cả hai bản (tránh embed 2 lần): refactor nhẹ để
  `_build_triple_index_from_embedder` và `_build_triple_qdrant` nhận chung ma trận
  `emb` đã tính, HOẶC mỗi hàm tự embed (đơn giản hơn, chi phí build-time chấp nhận
  được). **Chọn: mỗi hàm tự embed** để giữ hai hàm độc lập, dễ test riêng; tối ưu embed-
  một-lần để lại nếu thành nút cổ chai (corpus nhỏ → không đáng).

### 4. Query (`adapter._sparse_seed`) — branch theo flag + chuỗi fallback

```python
async def _sparse_seed(query: str, top_m: int) -> dict[str, float]:
    from noble_agent.agent.rag.qdrant_adapter import _embed_query
    loop = asyncio.get_running_loop()
    dense = await loop.run_in_executor(None, _embed_query, query)   # embed 1 lần, dùng chung

    triples: list[tuple[str, str, float]]
    if settings.hipporag_triple_store == "qdrant":
        from noble_agent.agent.rag import qdrant_store
        try:
            triples = await qdrant_store.search_triples(dense, top_m)      # 1) Qdrant
        except Exception as exc:
            logger.warning("[hipporag.adapter] qdrant triple search failed (%s) — local fallback", exc)
            idx = expander.load_triple_index()                            # 2) local npz backup
            triples = await loop.run_in_executor(None, idx.search, dense, top_m) if idx else []
    else:
        idx = expander.load_triple_index()                                # local path (như cũ)
        triples = await loop.run_in_executor(None, idx.search, dense, top_m) if idx else []

    # seed-building CHUNG cho mọi nguồn (giữ nguyên logic hiện tại)
    seeds: dict[str, float] = {}
    for s_key, o_key, score in triples:
        if score <= 0:
            continue
        for key in (s_key, o_key):
            if key:
                seeds[key] = max(seeds.get(key, 0.0), score)
    return seeds
```

Chuỗi `qdrant → local → hybrid`:
1. **Qdrant** — nguồn chính khi `HIPPORAG_TRIPLE_STORE=qdrant`.
2. **local** — Qdrant ném → nạp `.triple_emb.npz` (build sẵn mỗi sync) → cosine numpy.
3. **hybrid** — cả hai rỗng → `triples=[]` → `seeds={}` → sparse-seed no-op →
   adapter chạy tiếp bằng dense/passage-PPR (hoặc pure hybrid nếu không có graph).
   Đây là lưới an toàn hiện có, không thêm mới.

Lưu ý: `_sparse_seed` chạy trong `asyncio.gather` song song với `_hybrid_rows` (cũng là
call Qdrant) → wall-clock ≈ max hai call, gần như không đổi.

## Không đổi (bất biến giữ nguyên)

- `graph.json`, `expander.load()`, `HippoGraph`, PPR, `_rrf_fuse`, output scoping theo
  `project_filter`.
- `expander.load_triple_index`, `TripleIndex`, `triple_index.py` (npz) — nguyên vẹn,
  phục vụ đường local + fallback.
- Ngữ nghĩa `top_m`, cosine, mỗi triple seed ≤2 phrase node — **giống hệt** (Cosine
  distance + emb chuẩn hóa ≡ dot-product hiện tại).
- Đường `store=local` (default) — zero behaviour change.

## Test

- `qdrant_store`: `recreate_triple_collection` / `upsert_triples` / `search_triples`
  (mock `AsyncQdrantClient`, theo `test_qdrant_store` sẵn có — assert collection name,
  vector config Cosine, payload đọc `s`/`o`/`text`, limit=top_m).
- `builder._build_triple_qdrant`: inject embedder giả + capture upsert/recreate (theo
  style `build_and_save_triple_index` đang inject `encode_batch_fn`); case triple rỗng →
  no-op; case embedder ném → best-effort không raise.
- `adapter._sparse_seed`:
  - `store=qdrant`, `search_triples` trả triple → seeds đúng.
  - `store=qdrant`, `search_triples` ném → nạp local npz (stub `load_triple_index`) →
    seeds từ local.
  - `store=qdrant`, cả hai rỗng → `{}`.
  - `store=local` → đường cũ, không gọi Qdrant.
- Gate hồi quy: `tests/unit/unified` không có failure mới ngoài baseline đã biết.

## Vận hành

- Bật: `HIPPORAG_TRIPLE_STORE=qdrant` (+ `QDRANT_TRIPLE_COLLECTION` nếu đổi tên) trong `.env`.
- Trước khi bật, chạy `noble-rag-sync` một lần để build collection triple trên Qdrant
  (đồng thời cũng refresh npz local làm backup). Graph cũ chưa có triple → chạy
  `noble-rag-sync --renew-graph` như ghi chú HippoRAG hiện tại.
- Rollback: đặt lại `HIPPORAG_TRIPLE_STORE=local`, không cần rebuild (npz vẫn còn).
