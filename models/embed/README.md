# embed :8013 — nhà máy vector

Service độc lập load embedding model. Không biết Qdrant, không biết tenant.
Vào: text hoặc ảnh → ra: vector.

Một endpoint `/embed`; chiều khai bằng field **`side`** (`index` | `query`) — **bắt buộc, không
có default**. Prefix e5 bất đối xứng (`passage:` vs `query:`) nên gửi sai chiều làm vector lệch
mà không có lỗi nào báo; để `side` bắt buộc thì "quên" thành `422` chứ không thành lệch âm thầm.

| Endpoint | Việc |
|---|---|
| [`POST /embed`](#post-embed) | Sinh vector — chiều khai bằng `side` |
| [`GET /health`](#get-health) | Liveness + cấu hình hiệu lực |

Schema tương tác: `http://localhost:8013/docs` (FastAPI tự sinh từ code — luôn khớp).

---

## `POST /embed`

**Header:** `Authorization: Bearer <ODYSSEY_MODELS_TOKEN>` · `Content-Type: application/json`

**Request**

| Field | Kiểu | Bắt buộc | Mặc định | Ý nghĩa |
|---|---|:--:|---|---|
| `side` | string | ✅ | **không có** | `"index"` → e5 prefix `passage:` · `"query"` → `query:` |
| `kind` | string | ❌ | `"dense"` | `dense` · `sparse` · `visual_image` (chỉ `side=index`) · `visual_text` (chỉ `side=query`) |
| `texts` | string[] | ✅ khi `kind ≠ visual_image` | `[]` | Text cần embed |
| `images` | string[] | ✅ khi `kind = visual_image` | `[]` | Ảnh **base64** (không phải URL) |

`side` **không có default** là cố ý: prefix e5 bất đối xứng, nên "quên khai chiều" phải là
`422` chứ không được im lặng thành `passage`.

`is_query` và `normalize` đã bỏ — gửi vào (hay bất kỳ field lạ nào) nhận `422`. Vector **luôn** được L2-norm.

**Response — `kind = dense | visual_image | visual_text`**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `embeddings` | float[][] | Một vector mỗi input, đã L2-norm |
| `dim` | int | `1024` (dense) · `768` (visual_*) |
| `model` | string | Model thật đã dùng cho `kind` đó |
| `count` | int | Số input |

**Response — `kind = sparse`** (shape khác, không có `embeddings`/`dim`)

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `sparse` | object[] | `{indices: int[], values: float[]}` mỗi input |
| `model` | string | Model sparse đang dùng |
| `count` | int | Số input |

**Lỗi**

| Mã | Khi nào |
|---|---|
| `400` | `side` không phải `index`/`query` · `kind` lạ (kèm danh sách hợp lệ) · `kind` sai chiều · `texts` rỗng · `visual_image` thiếu `images` · `images` không phải base64 |
| `401` | Token sai/thiếu |
| `422` | **Thiếu `side`**, field lạ (kể cả `is_query`/`normalize` cũ) hoặc body không phải JSON hợp lệ |

```bash
# dense, chiều index (bên ghi gọi)
curl -s localhost:8013/embed -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"side":"index","texts":["bể bơi vô cực"]}'
# → {"embeddings":[[…1024 số…]],"dim":1024,"model":"intfloat/multilingual-e5-large","count":1}

# dense, chiều query (bên đọc gọi)
curl -s localhost:8013/embed … -d '{"side":"query","texts":["hồ bơi ở đâu"]}'

# sparse — dùng được cả hai chiều, shape response khác
curl -s localhost:8013/embed … -d '{"side":"index","kind":"sparse","texts":["bể bơi"]}'
# → {"sparse":[{"indices":[…],"values":[…]}],"model":"Qdrant/bm25","count":1}

# ảnh — chỉ side=index
curl -s localhost:8013/embed … \
  -d '{"side":"index","kind":"visual_image","images":["'"$(base64 -w0 pool.png)"'"]}'

# text tower của visual — chỉ side=query
curl -s localhost:8013/embed … -d '{"side":"query","kind":"visual_text","texts":["hồ bơi"]}'

# quên side → 422
curl -s localhost:8013/embed … -d '{"texts":["x"]}'
```

---

## `GET /health`

Liveness + cấu hình đang hiệu lực. **Mở, không cần token.**

**Request:** không có body.

**Response**

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `status` | string | `ok` khi đã nạp ít nhất một model, `warming` khi chưa |
| `device` | string | `cpu` \| `cuda` |
| `models` | object | Map `kind` → model đang dùng — để so cấu hình giữa các container |
| `kinds` | string[] | Mọi kind có trong `LOADERS` |
| `loaded` | string[] | Kind đã nạp vào RAM |

```bash
curl -s localhost:8013/health
# → {"status":"ok","device":"cpu",
#    "models":{"dense":"intfloat/multilingual-e5-large","sparse":"Qdrant/bm25",
#              "visual_text":"google/siglip2-base-patch16-256",
#              "visual_image":"google/siglip2-base-patch16-256"},
#    "kinds":["dense","sparse","visual_text","visual_image"],"loaded":["dense"]}
```

---

## Bốn kind → model nào

| `kind` | Model (env đổi được) | Chiều | Vector | Dùng cho |
|---|---|:--:|---|---|
| `dense` | `EMBED_DENSE_MODEL` — hiện `intfloat/multilingual-e5-large`, qua `sentence-transformers` | cả hai | 1024d, cosine | Dense text embedding (tìm kiếm ngữ nghĩa) |
| `sparse` | `EMBED_SPARSE_MODEL` — hiện `Qdrant/bm25`, qua `fastembed.SparseTextEmbedding` | cả hai | sparse | Sparse text embedding (tìm kiếm theo từ khoá) |
| `visual_image` | `EMBED_VISUAL_MODEL` — hiện `google/siglip2-base-patch16-256`, image tower | **chỉ index** | 768d, cosine | Image embedding cho visual search |
| `visual_text` | cùng model trên, text tower | **chỉ query** | 768d, cosine | Text embedding cho truy vấn visual search |

Hai kind visual dùng **chung một instance model**. BM25 chỉ có bản CPU.

Vector **luôn** được L2-norm (Qdrant cosine cần vậy) — đó là lý do bỏ `normalize`: model vốn
normalize sẵn nên param đó chưa bao giờ có tác dụng như tên gọi.

## Env

Tên biến theo **vai trò**, không theo model: đổi sang model khác chỉ đổi giá trị.

| Biến | Mặc định |
|---|---|
| `EMBED_DENSE_MODEL` | `intfloat/multilingual-e5-large` |
| `EMBED_SPARSE_MODEL` | `Qdrant/bm25` |
| `EMBED_VISUAL_MODEL` | `google/siglip2-base-patch16-256` |
| `EMBED_VISUAL_MAXLEN` | `64` — padding text tower, phải khớp giữa index và query |
| `EMBED_DEVICE` | `cpu` — đổi sang `cuda` không cần re-index (fp32 cpu vs cuda chênh ~1e-6) |
| `EMBED_BATCH_SIZE` | `32` |
| `EMBED_WARMUP` | `dense` — kind nạp sẵn lúc boot (fail sớm). Nhiều kind: `dense,sparse` |
| `ODYSSEY_MODELS_TOKEN` | rỗng = mở. `/health` luôn mở |

## Thêm một kind

Thêm file trong [models/](models/) + một entry `"tên": Class` vào `LOADERS` ở
[models/__init__.py](models/__init__.py), và thêm entry vào `MODEL_BY_KIND` ở
[settings.py](settings.py). Router không đổi.

Class cần method tương ứng — vector trả về phải L2-norm sẵn, server không chuẩn hoá lại:
`encode(texts, is_query=…)` cho text, `encode_sparse(texts)` cho sparse, `encode_images(list[bytes])` cho ảnh. Nếu kind mới chỉ có
nghĩa một chiều, thêm nó vào `SIDE_BY_KIND` trong [server.py](server.py).

## Chạy · test

```bash
docker compose up -d embed          # build context là repo root (cần pyproject.toml)
pytest tests/test_embed_api.py -q   # không cần torch: LOADERS được inject bản giả
```
