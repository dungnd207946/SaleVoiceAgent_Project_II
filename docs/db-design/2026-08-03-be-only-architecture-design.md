# Spec: CMS backend-only + rag_service & media_service

> **Ngày:** 2026-08-03 · **Trạng thái:** thiết kế — phần 1 đã duyệt, phần 2 đề xuất chưa duyệt
> **Mục tiêu:** Bỏ FE khỏi CMS, thu CMS về *control plane + ingest orchestration*; xây
> `rag_service` và `media_service` trong repo `santa-models`, mỗi service **own index của
> mình cả 2 chiều** (ghi lúc ingest, đọc lúc query). Giữ nguyên multi-tenant (Postgres RLS
> + Qdrant collection/workspace + MinIO prefix/workspace).

---

## 0. Cách dùng tài liệu này

Đây là **tài liệu handoff tự chứa** — viết để làm việc ở repo khác (`santa-models`
và/hoặc repo CMS mới), không cần mở lại repo `cms` hiện tại.

**Cần mang theo sang repo mới** (không nhắc lại nội dung ở đây, quá dài):

| File | Vì sao cần |
|---|---|
| `docs/db-design/00-overview.md` | Quyết định nền Postgres+RLS, taxonomy 4 nhóm, scale-ready |
| `docs/db-design/01-control-plane.md` | 8 bảng schema `control` (đủ field) |
| `docs/db-design/02-knowledge-base.md` | Nguyên tắc KB: anchor, visibility, freshness, cách ly |
| `docs/db-design/02a-real-estate-template.md` | Schema thật projects/zones/units/documents/media + enum + payload Qdrant |
| `docs/db-design/02b-rag-service.md` | Engine RAG: 5 module, `rag_config`, chunk strategy, pipeline |
| `backend/app/verticals/` | Code **đã chạy được** — khai báo lĩnh vực BĐS, giữ nguyên |
| `backend/app/kb/` | Interface CRUD generic (stub) — giữ, hoàn thiện |
| `experiments/santa-models/media/media_server.py` | Query path hybrid RRF đang chạy thật — nền của `media_service` |

**Trạng thái duyệt** — quan trọng khi đọc:
- §2, §3, §4 → **đã chốt cùng user** qua brainstorm 2026-08-03.
- §5–§13 → **đề xuất, chưa duyệt**. Cần review trước khi code.

---

## 1. Bối cảnh & hiện trạng

### 1.1 CMS repo (`~/Desktop/cms`)

Working tree đã **xoá 278 file** của CMS cũ (FE + backend Mongo + hotline/chat/projects
API + adapters). Còn lại **skeleton mới chưa commit**:

```
backend/app/
  verticals/          ← THẬT, chạy được: khai báo lĩnh vực bằng data
    base.py           VerticalTemplate · EntitySpec · FieldSpec
    registry.py       {key: template} + get()
    real_estate/      enums · fields · rag_config · media_categories · completeness · models/
  kb/                 ← interface + stub (NotImplementedError)
    common/           mixins · exceptions · base_repo · generic_repo · generic_service
                      · publish_service · rag_dispatch
    documents/        model · repo · service · schema · router
    media/            (cấu trúc giống documents/)
    router/entities.py  router generic /{vertical}/{entity} + /form-schema
  rag/                ← interface + stub
    engine.py · profiles.py · modules/{chunker,embedder,vision_extractor,
                                      video_extractor,vector_store,object_store}
    clients/          (trỏ embed_server:8013, media_server:8015)
docs/
  db-design/          ← thiết kế CHÍNH THỨC (00·01·02·02a·02b)
  cms-multitenant-plan.md  ← plan Mongo CŨ, chỉ tham khảo, đã bị 00-overview thay thế
  notion/             11 doc yêu cầu nghiệp vụ
experiments/santa-models/  ← git repo lồng, xem 1.2
```

Chiều phụ thuộc đã thiết lập: `verticals ──▶ kb ──▶ rag` (verticals không import ngược).

**Chưa có** (cần trước khi chạy): `core/` (config·security·logging), `db/engine`,
`tenancy/` (RLS), `main.py`/`worker.py`, `migrations/`, `pyproject.toml`, `tests/`.

### 1.2 santa-models repo (`experiments/santa-models`, git riêng)

Model microservice standalone, "dùng như cloud vendor: chỉ URL + protocol, không share code".
Auth = shared bearer `SANTA_MODELS_TOKEN`; `/health` mở.

| Service | Port | Runtime | Nội dung |
|---|---|---|---|
| `embed` | 8013 | **CPU**, Docker, `fastembed` ONNX INT8 | e5-large 1024d. `POST /embed {texts, is_query, normalize}`. **Đã có `is_query`** → hỗ trợ cả query & passage prefix |
| `media` | 8015 | **GPU**, native systemd | Hybrid search `media_v3`: E5-large (sentence-transformers, fp32) + SigLIP2 text tower → Qdrant RRF server-side. Cache 5'. **Query-only** |
| `stt` | 8012 | CPU, Docker | sherpa Zipformer streaming WS |
| `tts` | 8011 | **GPU**, native | VieNeu lmdeploy, WS streaming PCM |
| `speaker` | 8014 | CPU, Docker | sherpa CAM++ |

GPU box: Blackwell — GPU-in-Docker bị tránh, nên TTS + media chạy native systemd.

### 1.3 Hai vấn đề phát hiện khi đọc code (phải xử lý)

**(1) e5-large tồn tại 2 bản khác runtime → vector không khớp bit-level.**
`embed_server` dùng `fastembed` ONNX **INT8/CPU**; `media_server` dùng
`sentence-transformers` **fp32/GPU**. Nếu ingest embed bằng bản này mà query embed bằng
bản kia → retrieval degrade âm thầm, cực khó phát hiện. → §11.

**(2) Contract payload đã từng lệch giữa ingest và query.** Comment trong
`media_server.py` đầy dấu vết `media_v2 → media_v3`: `project_code`→`project_id`,
`category` từ `list[str]`→`str`, bỏ `rel_path`. Đây là bằng chứng thực nghiệm cho việc
**ai ghi index thì người đó phải own index** → là lý do chốt §2.2.

---

## 2. Quyết định đã chốt

### 2.1 rag_service & media_service nằm trong repo `santa-models`

santa-models trở thành **service layer** trên GPU box. `media_service` kế thừa
`media_server:8015` hiện có; `rag_service` là service mới.

### 2.2 Service own index cả 2 chiều

Mỗi service **vừa ghi vừa đọc** Qdrant collection của nó. CMS worker gửi *record đã
resolve* qua `POST /index`; service tự chunk / caption / embed / upsert.

**Lý do:** point-id scheme + payload schema + named vector + model version phải khớp
tuyệt đối giữa write và read. Một codebase quyết định cả hai → không thể lệch. Nếu tách
2 repo thì mỗi lần đổi model/schema là một lần lặp lại nỗi đau `media_v2→v3` (§1.3.2).

**Hệ quả:** CMS **không** có Qdrant client, **không** biết tên model, **không** cài
torch/transformers → image nhẹ, test không cần GPU.

### 2.3 Model layer dùng chung + tách process

Nâng `embed_server` thành **model layer duy nhất** (e5 dense · BM25 sparse · SigLIP2
image tower + text tower). `query_api` và `ingest_worker` là **2 process riêng**, cả hai
gọi vào model layer. Model layer có **priority queue: query sync ưu tiên, ingest batch nhường**.

**Lý do:** 1 copy model (tiết kiệm VRAM — đang chia GPU với TTS lmdeploy), vector parity
đảm bảo *bằng cấu trúc* chứ không bằng kỷ luật, latency cô lập bằng queue priority.
**Đánh đổi đã chấp nhận:** query thêm 1 hop loopback (~1–2ms, inference vẫn chiếm chủ
đạo) và model layer thành SPOF của cả 2 path.

### 2.4 Phạm vi ingest phase này: CHỈ nhập tay qua dashboard

**Một dev khác đang build dashboard** để nhập liệu → API của CMS là **contract với team
khác**, không phải chuyện nội bộ.

CMS surface = **API (cho dashboard) + worker + scheduler + CLI**.

**Không làm phase này** (YAGNI): adapter framework đa nguồn, raw landing
(`raw_documents`), normalize per-source, `sources` table, api_pull + cursor incremental,
webhook receiver, bulk import từ cây file.

> Khớp đúng `02-knowledge-base.md` §6: *"Phase này nhập tay (manual-only): bỏ `source` ·
> `external_id` · `synced_at` · `verified_at`"* và `01-control-plane.md` Δ: *"❌ Bỏ
> `sources` khỏi MVP"*. Toàn bộ tầng adapter trong `cms-multitenant-plan.md` là **doc chết**.

**Quan trọng — làm rõ thuật ngữ:** "pipeline ingest" mà user muốn là **pipeline làm giàu
+ index** (chunk → caption/OCR → embed → Qdrant/MinIO), *không phải* adapter đa nguồn.

---

## 3. Kiến trúc mục tiêu

```
┌── CMS repo — control plane + ingest orchestration ──────────────────────┐
│  api          /api/v1  ← dashboard team gọi (OpenAPI, versioned)       │
│  worker       consume Redis rag:jobs → POST /index                     │
│  scheduler    reconcile cron (KHÔNG pull nguồn ngoài)                  │
│  cli          provision-tenant · teardown · backfill · reconcile        │
│                                                                         │
│  Postgres (schema control + tenant_data, RLS FORCE)                     │
│  MinIO (ghi file gốc + presign)   ·   Redis (queue)                     │
│  KHÔNG: GPU · torch · Qdrant client · tên model · thuật toán chunk      │
└──────────────┬─────────────────────────────────────────────────────────┘
               │ HTTP  POST /index · DELETE /index · POST /admin/collections
               │       (bearer SANTA_MODELS_TOKEN)
┌──────────────▼──── santa-models repo — GPU box ────────────────────────┐
│  model_layer  :8013   e5 dense · BM25 sparse · SigLIP2 image+text      │
│                       priority queue: query sync ⟩ ingest batch        │
│         ▲ query (ưu tiên)                    ▲ passage / image (batch) │
│  rag_service   :8016  index + query  <slug>_documents                  │
│  media_service :8015  index + query  <slug>_media                      │
│         └────────────► Qdrant                                          │
│  common/              qdrant client · point-id · content_hash · payload │
│  stt :8012 · tts :8011 · speaker :8014  (giữ nguyên)                   │
└────────────────────────────────────────────────────────────────────────┘
               ▲
               │ POST /search  (kb_search · send_media)
        agent (hotline / chat)
```

**Nguyên tắc cắt:** CMS quyết định **"cái gì, của tenant nào, theo chiến lược nào"**;
service quyết định **"biểu diễn nó trong index ra sao"**.

Ba hệ quả, đều là điểm mạnh:
- Đổi model embed / thuật toán chunk / payload schema → **chỉ sửa santa-models**. Re-index
  bằng CLI `backfill` của CMS gọi lại `/index`.
- Thêm vertical mới → **chỉ sửa CMS** (`verticals/<x>/`). santa-models không biết vertical.
- CMS test được không cần GPU/model; santa-models test được không cần Postgres.

---

## 4. Contract CMS ↔ services

Biên giới thật của hệ thống. Cần freeze và version.

### 4.1 `POST /index`

CMS gửi **directive đã resolve từ `rag_config`**, không gửi config thô.

```jsonc
// → rag_service :8016  (text → <slug>_documents)
{
  "workspace_slug": "acme",
  "record_id": 4501,
  "doc_type": "tai_lieu",        // CHỈ để dựng point-id; KHÔNG vào payload
  "anchor_code": "NPLB",         // → payload.project_id
  "anchor_name": "Noble Palace Long Biên",
  "section": "Noble Palace > Chính sách bán hàng Q3 2026",   // breadcrumb
  "text": "…",                   // CMS đã ghép fields theo rag_config.embed_sources
  "chunk": { "strategy": "structured_md", "max_chars": 800, "overlap": 150 },
  "source_file_url": "https://minio/…?X-Amz-Signature=…",   // presigned GET, TTL ngắn
  "extract_profile": "pdf2text"  // null nếu không cần trích text từ file
}

// → media_service :8015  (ảnh/video → <slug>_media)
{
  "workspace_slug": "acme",
  "record_id": 8802,
  "anchor_code": "NPLB",
  "content_type": "image",       // image | video
  "category": "mat_bang",
  "media_url": "https://…/mb.webp",        // URL bền, vào payload + dựng point-id
  "file_url": "https://minio/…?X-Amz-Signature=…",   // presigned GET để service fetch bytes;
                                           // null khi media_url là URL ngoài (§4.2d)
  "caption": null,               // null → service sinh + TRẢ VỀ; có → dùng luôn, BỎ QUA VLM
  "caption_profile": "caption_subject"     // tên profile; nội dung prompt do service own
}
```

**Response** (cả 2 service):
```jsonc
{ "points_upserted": 7, "points_deleted": 2,
  "content_hash": "a1b2c3…",
  "caption": "Mặt bằng tầng điển hình…",   // media: khi service tự sinh
  "extracted_text": "## Tiến độ…" }        // rag: khi trích từ PDF
```

### 4.2 Ba quyết định nằm trong contract

**(a) File truyền bằng presigned GET URL — không truyền bytes, không cấp MinIO creds cho
santa-models.** Service fetch qua URL rồi bỏ. → santa-models không cần biết prefix/tenant
layout, không giữ credential ghi. CMS là nơi **duy nhất** có quyền MinIO.

**(b) `caption` là trường 2 chiều.** `null` → service sinh caption, trả về, CMS ghi vào
`media.caption` cho user sửa trên dashboard (`02b` §5). Có giá trị → service dùng luôn,
**bỏ qua VLM**. → user sửa caption chỉ tốn 1 lần embed, không gọi lại Qwen-VL. Tiết kiệm
chi phí đáng kể vì caption sẽ bị sửa nhiều.

Tương tự `extracted_text`: trích 1 lần, CMS lưu vào `documents.body`, lần sau gửi text đi
thay vì gửi lại PDF.

**(d) `media_url` có thể là URL NGOÀI, không phải MinIO.** `02a` §4.5 cho phép
`media_url` trỏ YouTube / kuula / Drive. Khi đó **không có `file_url` để presign** →
service phải xử lý 2 nhánh:
- MinIO: `file_url` presigned → fetch bytes → SigLIP2 image tower.
- Ngoài: `file_url = null` → dùng `media_url` trực tiếp. Video YouTube đưa thẳng vào
  Gemini `FileData(uri)` (`02b` §2); ảnh URL công khai thì fetch thường.

Đây là nhánh dễ bị bỏ sót nhất khi code `/index` của media_service — không có nó thì mọi
media ngoài MinIO sẽ fail index.

**(c) `chunk.strategy` / `caption_profile` / `extract_profile` là *tên*; `rag_config` ở
lại CMS.** CMS resolve `rag_config` → gửi tên + tham số. Service cài 6 chunk strategy và
thư viện `PROFILES`. → service vertical-agnostic thật, khai báo lĩnh vực vẫn tập trung
một chỗ trong CMS.

### 4.3 Các endpoint còn lại

| Endpoint | Service | Việc |
|---|---|---|
| `DELETE /index` | cả 2 | `{workspace_slug, doc_type?, record_id}` → xoá mọi point của record (unpublish/archive) |
| `POST /admin/collections` | cả 2 | `{workspace_slug}` → tạo collection + payload index. Idempotent |
| `DELETE /admin/collections` | cả 2 | drop collection (teardown tenant) |
| `POST /admin/scroll` | cả 2 | `{workspace_slug, anchor_code}` → `[{point_id, record_id, content_hash}]` cho reconcile của CMS |
| `POST /search` | rag_service | `kb_search`: dense+sparse → RRF, filter `project_id ∈ {active, "__ALL__"}` |
| `POST /search` | media_service | `send_media`: text+visual → RRF, filter `project_id`, `category`. **Đã có, giữ contract** |
| `GET /health` | cả 2 | liveness (mở, không auth) |

> `POST /admin/scroll` là mảnh ghép cho reconcile: CMS không có Qdrant client (§2.2) nên
> phải hỏi service "collection đang có những gì" để so với `published` ở Postgres.

### 4.4 Tương thích ngược của `media_service`

`media_server:8015` đang phục vụ agent thật trên `media_v3` với body
`{query, project_code, category, top_k?, threshold?}`. **Giữ nguyên `POST /search`**;
chỉ thêm `workspace_slug` (optional, default → `media_v3` cho tới khi migrate xong §11).
Đừng breaking-change agent đang chạy.

---

## 5. Cấu trúc thư mục — repo CMS *(đề xuất, chưa duyệt)*

### 5.1 Layout mục tiêu

Bỏ FE rồi thì tên `backend/` mất nghĩa (không còn "backend của" cái gì) → **phẳng lên root**.

```
app/
  main.py                 FastAPI cho dashboard
  worker.py               consume rag:jobs → clients/*.index()
  scheduler.py            reconcile cron (APScheduler trong lifespan)
  cli/                    typer: provision-tenant · teardown · backfill · reconcile
  core/                   config (pydantic-settings) · security (JWT) · logging · errors
  db/                     engine · session · RLS session setup (SET app.tenant_id)
  tenancy/                TenantContext · resolve từ JWT · provisioning · teardown
  control/                nhóm A: organizations · tenants · tenant_verticals ·
                          memberships · users · field_definitions · config_versions · audit_log
  kb/                     nhóm B: CRUD generic          ← GIỮ NGUYÊN, hoàn thiện stub
    common/ documents/ media/ router/
  verticals/              khai báo lĩnh vực              ← GIỮ NGUYÊN, đã chạy được
    base.py registry.py real_estate/
  indexing/               ← ĐỔI TÊN từ rag/
    dispatch.py           enqueue Redis (từ kb/common/rag_dispatch.py)
    directives.py         rag_config → IndexDirective (resolve fields/strategy/profile)
    clients/              httpx client → rag_service · media_service (retry, timeout)
    reconcile.py           so published@Postgres vs /admin/scroll
  storage/
    object_store.py       MinIO: upload · presign GET/PUT · delete prefix
migrations/               alembic
tests/
pyproject.toml
```

### 5.2 Việc di chuyển / xoá — hệ quả trực tiếp của §2.2

| File hiện tại | Đích | Ghi chú |
|---|---|---|
| `rag/modules/chunker.py` | → santa-models `rag_service/chunking/` | CMS không chunk nữa |
| `rag/modules/embedder.py` | → santa-models `model_layer/` | CMS không embed nữa |
| `rag/modules/vision_extractor.py` | → santa-models `common/vision/` | |
| `rag/modules/video_extractor.py` | → santa-models `media_service/` | |
| `rag/modules/vector_store.py` | → santa-models `common/qdrant/` | CMS không có Qdrant client |
| `rag/profiles.py` | → santa-models `common/vision/profiles.py` | CMS chỉ giữ *tên* profile trong `rag_config` |
| `rag/clients/` | → `app/indexing/clients/` | Đổi mục đích: gọi `/index` chứ không gọi `/embed` |
| `rag/engine.py` | **xoá** | Logic chuyển sang service; CMS chỉ còn `directives.py` |
| `rag/modules/object_store.py` | → `app/storage/object_store.py` | **Ở LẠI CMS** — CMS là nơi duy nhất ghi MinIO (§4.2a) |
| `kb/common/rag_dispatch.py` | → `app/indexing/dispatch.py` | |
| `docs/cms-multitenant-plan.md` | → `docs/archive/` | Doc chết, đánh dấu superseded |

**Không đụng:** `verticals/` (đã thật), `kb/documents|media|router|common` (trừ rag_dispatch).

---

## 6. Cấu trúc thư mục — repo santa-models *(đề xuất, chưa duyệt)*

```
santa-models/
  model_layer/            ← nâng cấp từ embed/ (:8013)
    server.py             POST /embed {texts, kind, priority}
                          kind: dense|sparse|visual_image|visual_text
                          priority: query|ingest     ← queue ưu tiên §2.3
    models/               e5.py · bm25.py · siglip2.py  (lazy load, 1 copy)
    queue.py              priority queue + batching
    Dockerfile / .service
  common/                 ← DÙNG CHUNG bởi index & query — chống lệch v2/v3
    qdrant/               client · collection provisioning · payload index
    point_id.py           uuid5 scheme (text + media)
    content_hash.py       sha1 → incremental/drift
    payload.py            dataclass payload 2 collection = SINGLE SOURCE OF TRUTH
    vision/               Qwen-VL client · profiles.py (PROFILES)
    auth.py               bearer SANTA_MODELS_TOKEN
  rag_service/            :8016  <slug>_documents
    query_api.py          POST /search  (dense+sparse → RRF)
    index_api.py          POST/DELETE /index
    chunking/             6 strategy: facts · markdown · atomic · per_row ·
                          merged_list · structured_md
    extract/              pdf2text · ocr_markdown (qua common/vision)
  media_service/          :8015  <slug>_media
    query_api.py          POST /search  ← từ media_server.py hiện tại, GIỮ contract
    index_api.py          POST/DELETE /index
    caption.py            ảnh: Qwen-VL theo profile
    video.py              video: Gemini describe
    thumbnail.py          WebP thumb → trả URL cho CMS
  stt/ tts/ speaker/      giữ nguyên
  docker-compose.yml      CPU services
```

**`common/payload.py` là mảnh quan trọng nhất của cả thiết kế này.** Một dataclass duy
nhất định nghĩa payload; `index_api` ghi theo nó, `query_api` đọc theo nó. Đây chính là
thứ làm `media_v2→v3` không thể tái diễn.

**`priority` trong model_layer:** query request vào head queue, ingest batch vào tail,
batch ingest bị chia nhỏ để không block query quá 1 batch. Đây là toàn bộ cơ chế bảo vệ
latency của §2.3 — làm sai chỗ này thì mất hết lợi ích của việc tách process.

---

## 7. Hai pipeline chi tiết *(đề xuất, chưa duyệt)*

### 7.1 Pipeline TEXT → `<slug>_documents`

```
dashboard POST /api/v1/kb/real_estate/documents
    → validate theo FieldSpec (kb/common/generic_service)
    → INSERT status=draft                                    [Postgres]
dashboard POST …/{id}/publish
    → completeness gate (verticals/real_estate/completeness)  ← chặn nếu thiếu field
    → UPDATE status=published
    → indexing/dispatch.enqueue{tenant_id, vertical, table, id, op=upsert}   [Redis]
worker
    → đọc row + anchor name                                  [Postgres, RLS]
    → directives.resolve(rag_config, table) → ghép fields, lấy chunk strategy, doc_type
    → nếu có file_url và body rỗng → presign GET + extract_profile
    → POST rag_service/index
        → (nếu cần) trích text từ PDF
        → chunk theo strategy, prepend breadcrumb section
        → model_layer: dense(passage:) + sparse, priority=ingest
        → point-id uuid5(doc_type:record_id:idx)
        → scroll point cũ của record → so content_hash → upsert cái đổi, XOÁ point thừa
    → ghi lại extracted_text + trạng thái index                [Postgres]
```

### 7.2 Pipeline MEDIA → `<slug>_media`

```
dashboard POST /api/v1/kb/media/presign  → {put_url, media_url}
dashboard PUT trực tiếp lên MinIO (không qua CMS → không ăn bandwidth CMS)
dashboard POST /api/v1/kb/media/confirm  → INSERT status=draft            [Postgres]
publish → completeness + category ∈ rag_config.media.visual → enqueue    [Redis]
worker
    → presign GET file_url
    → POST media_service/index {caption: null}
        → fetch bytes
        → thumbnail WebP → MinIO?  ⚠️ xem quyết định mở §14.3
        → ảnh: caption Qwen-VL theo profile | video: Gemini describe
        → model_layer: text=dense(passage: "{project} › {category}\n{caption}")
                       visual=visual_image(ảnh | thumbnail video), priority=ingest
        → point-id uuid5(media:{project_id}:sha1(media_url))
        → upsert incremental theo content_hash
    → ghi caption + thumb_url trả về vào bảng media           [Postgres]
user sửa caption trên dashboard
    → UPDATE caption → re-enqueue
    → POST /index {caption: "<đã sửa>"} → BỎ QUA VLM, chỉ re-embed  ← §4.2b
```

### 7.3 Unpublish / archive / delete

`status → draft|archived` hoặc DELETE row → `enqueue op=delete` → `DELETE /index`.
Qdrant chỉ chứa bản `published` (`02` §3) nên payload không cần cột `status`.

**Cascade anchor:** `projects.status ≠ published` → phải xoá point của **toàn bộ cây con**
(zones/units/documents/media của project đó). Đây là chỗ dễ sai nhất — `publish_service`
phải fan-out enqueue cho cả cây, không chỉ row anchor.

---

## 8. Multi-tenant & cách ly *(giữ nguyên thiết kế đã chốt)*

| Kho | Cách ly | Cưỡng chế |
|---|---|---|
| Postgres | `tenant_id` mọi bảng `tenant_data` + **RLS FORCE** | app dùng role **không** BYPASSRLS + `SET app.tenant_id` mỗi request; FK tổ hợp `(tenant_id, …)` chặn ref chéo tenant |
| Qdrant | 2 collection/workspace: `<slug>_documents` · `<slug>_media` | `workspace_slug` trong mọi call `/index`, `/search` |
| MinIO | 1 prefix/workspace `<slug>/` | mọi key qua helper prefix; presign cũng qua helper |

**Phân quyền (RLS)** — `01-control-plane.md` §5b:

| Scope | GUC | Thấy |
|---|---|---|
| Platform-admin | `role=platform` | control plane; **KHÔNG** data nghiệp vụ |
| Org admin | `app.org_id` | gộp workspace con: `tenant_id IN (SELECT id FROM tenants WHERE org_id = current)` |
| Workspace role | `app.tenant_id` | đúng 1 workspace (4 vai trò) |
| Agent | `app.tenant_id` cố định lúc boot | đọc KB tất (không gate) + ghi đúng 3 bảng (`WITH CHECK`) |

**Provision tenant — cả-hoặc-không** (`01` §Provisioning, `02` §9):
1. INSERT `tenants` (slug, org_id, `qdrant_documents_coll`, `qdrant_media_coll`, `s3_prefix`)
2. INSERT `tenant_verticals` (vertical=real_estate)
3. `POST rag_service/admin/collections` + `POST media_service/admin/collections`
4. Tạo MinIO prefix `<slug>/`
5. **Seed row anchor hệ thống** `projects(project_code="__ALL__", status=published)` — cho
   documents/media cấp tenant (`02a` §4b). Thiếu bước này thì FK tổ hợp vỡ khi user tạo
   tài liệu chung.

**Teardown (NĐ13):** `DELETE FROM tenants WHERE id=…` (FK ON DELETE CASCADE) + drop 2
Qdrant collection + xoá MinIO prefix.

---

## 9. API contract cho dashboard team *(đề xuất, chưa duyệt)*

Đây là contract với **dev khác** → đổi field là breaking change. Cần OpenAPI + version.

| Nhóm | Endpoint | Ghi chú |
|---|---|---|
| Auth | `POST /api/v1/auth/login` → JWT | claim: `user_id`, memberships → scope + role |
| | `GET /api/v1/auth/me` | + danh sách workspace cho **tenant switcher** |
| Meta | `GET /api/v1/kb/{vertical}/{entity}/form-schema` | **Trung tâm của thiết kế** — dashboard render form động từ `FieldSpec` |
| | `GET /api/v1/kb/{vertical}/enums` | options enum + nhãn tiếng Việt |
| | `GET /api/v1/kb/{vertical}/media-categories` | 7 category + label + thứ tự hiển thị |
| CRUD | `GET/POST/PATCH/DELETE /api/v1/kb/{vertical}/{entity}` | router generic đã có ở `kb/router/entities.py` |
| Publish | `POST …/{id}/publish` · `POST …/{id}/unpublish` | trả **lý do thiếu dữ liệu** khi completeness fail |
| File | `POST /api/v1/kb/media/presign` → `{put_url, media_url}` | upload trực tiếp MinIO |
| | `POST /api/v1/kb/media/confirm` | tạo row sau khi upload xong |
| Trạng thái | `GET …/{id}/index-status` | để dashboard hiện "đang index / đã index / lỗi" |

**`/form-schema` là điểm mạnh nhất của kiến trúc `verticals/` hiện có — phải giữ.** Thêm
field BĐS mới → dashboard **không cần sửa code**. Nói rõ điều này với dev kia ngay từ đầu,
nếu không họ sẽ hardcode form và mất toàn bộ lợi ích.

**Cần chốt với dev dashboard:**
- Presign vs multipart (khuyến nghị presign — video lớn, CMS không nên gánh bandwidth)
- CORS origin của dashboard
- Định dạng lỗi validate (đề xuất RFC 7807 + `field` → message, để render inline dưới ô input)
- Ai lo tenant switcher UI, header nào truyền tenant (đề xuất `X-Tenant-Id`, chỉ platform/org-admin dùng)

---

## 10. Latency, GPU, vận hành *(đề xuất, chưa duyệt)*

**Trả lời câu hỏi gốc "gộp ingest vào service có tăng latency query không":** không phải
do gộp *codebase*, mà do gộp *tài nguyên*. Cụ thể:

- **Caption/OCR/video = API cloud** (Qwen-VL `qwen-vl-max`, Gemini `2.5-flash` — `02b` §2)
  → phần **nặng nhất** của ingest không ăn GPU local, chỉ là I/O chờ. Không cạnh tranh gì.
- Ingest ăn GPU local chỉ còn **e5 passage + SigLIP2 image tower** — bursty nhưng ngắn.
- Rủi ro latency nằm ở **đúng một chỗ**: tranh chấp GPU giữa embed-batch (ingest) và
  embed-query. Đó là thứ được xử lý bằng priority queue §2.3, không phải bằng việc tách repo.

Vận hành:
- **2 systemd unit riêng** cho `query_api` và `ingest_worker` mỗi service → restart /
  scale / xem log độc lập.
- **Backpressure:** worker CMS giới hạn concurrency (`asyncio.Semaphore`) + `/index` trả
  429 khi queue model layer quá sâu → worker retry backoff.
- **Rate limit external API** (Qwen-VL/Gemini) + retry backoff — `02b` §1.
- Giữ **cache 5'** của query path (đã có trong `media_server.py`).
- **Reconcile cron** (`02b` §7): so `published`@Postgres vs `/admin/scroll` → bù point
  thiếu, xoá point thừa. Lưới an toàn cho event bị miss — bắt buộc có, vì Redis queue
  không đảm bảo delivery.

---

## 11. Vector parity + re-index *(đề xuất, chưa duyệt)*

Xử lý vấn đề §1.3.1:

1. **Model layer là nơi DUY NHẤT load e5 và SigLIP2.** Xoá `SentenceTransformer` khỏi
   `media_server`; xoá `fastembed` khỏi path ingest. Một implementation, một dtype, một device.
2. **Chốt runtime cho e5** trước khi index bất cứ thứ gì. Query hiện tại chạy fp32/GPU
   (`media_server`), ingest cũ chạy INT8/CPU (`embed_server`) → phải chọn 1. Khuyến nghị
   **fp32/GPU** vì query path đang dùng nó và chất lượng cao hơn INT8.
3. **`media_v3` hiện tại đã index bằng pipeline cũ** → không đảm bảo parity với model layer
   mới. Collection mới `<slug>_media` phải **re-index toàn bộ từ Postgres**, không copy point
   từ `media_v3`. Dùng CLI `backfill`.
4. **Golden vector test:** cố định 20 câu tiếng Việt → snapshot vector. Test fail khi ai đó
   đổi model/dtype/prefix. Đây là cách duy nhất bắt được lỗi loại này trước khi nó phá index.

---

## 12. Test bắt buộc *(đề xuất, chưa duyệt)*

| Test | Vì sao |
|---|---|
| **Cross-tenant isolation** — tenant A không đọc được data B trên **cả 3 kho** | `00` §5 ghi rõ: **điều kiện chặn merge** |
| **Round-trip index→search** — index 1 record rồi search lại chính nó, assert `record_id` khớp | Bắt lệch payload/point-id giữa write và read — chính là bug `media_v2→v3` |
| **Golden vector** — 20 câu cố định, snapshot vector | Bắt đổi model/dtype/prefix (§11.4) |
| **Incremental** — index 2 lần cùng record → `points_upserted=0` lần 2; sửa 1 chunk → chỉ chunk đó upsert; bớt chunk → point thừa bị xoá | Logic `content_hash` là chỗ dễ để lại rác |
| **Cascade unpublish** — unpublish project → point của **toàn bộ** zones/units/documents/media biến mất | §7.3, chỗ dễ sai nhất |
| **Completeness gate** — publish thiếu field → 422 + liệt kê field thiếu | Contract với dashboard |
| **`__ALL__` sentinel** — tài liệu cấp tenant vẫn ra trong search khi không có project active | `02a` §4b |
| **Contract test** — CMS client vs service schema (đề xuất schemathesis từ OpenAPI) | 2 repo tách nhau, không có type checking xuyên biên |

---

## 13. Thứ tự công việc *(đề xuất, chưa duyệt)*

Xếp theo **dependency thật**, không theo độ khó. Mỗi phase là một PR review được.

### Phase 0 — Nền CMS *(chặn mọi thứ khác)*
- [ ] `pyproject.toml`, layout phẳng (§5.1), ruff/pytest
- [ ] `core/config.py` (pydantic-settings), `core/logging.py`, `core/errors.py`
- [ ] `db/engine.py` + session; **`SET app.tenant_id` per-request** (không dùng BYPASSRLS)
- [ ] alembic + migration schema `control` (8 bảng, `01`)
- [ ] migration `tenant_data` real_estate (projects·zones·units·documents·media, `02a`) —
      RLS FORCE + FK tổ hợp + index dẫn đầu `tenant_id`
- [ ] **Test cross-tenant isolation Postgres** ← không pass thì không đi tiếp

### Phase 1 — Model layer *(chặn cả 2 service)*
- [ ] Nâng `embed_server` → `model_layer`: 4 kind (dense/sparse/visual_image/visual_text)
- [ ] Priority queue query ⟩ ingest + batching
- [ ] Chốt runtime e5 (§11.2), xoá bản trùng
- [ ] Golden vector test
- [ ] `common/`: payload dataclass · point_id · content_hash · qdrant client · auth

### Phase 2 — Auth + API skeleton *(mở khoá dev dashboard — ưu tiên cao)*
- [ ] JWT login + `memberships` → scope/role → `TenantContext`
- [ ] `/auth/me` + tenant switcher data
- [ ] `/form-schema` + `/enums` + `/media-categories` từ `verticals/`
- [ ] OpenAPI publish cho dev kia + CORS
> Làm sớm phase này: dev dashboard đang bị chặn ở đây.

### Phase 3 — CRUD KB + publish gate
- [ ] Hoàn thiện `kb/common/generic_repo|generic_service` (validate theo `FieldSpec`)
- [ ] `kb/router/entities.py` chạy thật cho projects/zones/units
- [ ] `documents` + `media` CRUD; presign/confirm MinIO
- [ ] `publish_service`: completeness gate + **cascade anchor fan-out** + enqueue
- [ ] Seed `__ALL__` anchor lúc provision

### Phase 4 — rag_service
- [ ] 6 chunk strategy + breadcrumb + "không cắt giữa bảng markdown"
- [ ] `POST/DELETE /index` + incremental theo `content_hash`
- [ ] `POST /search` dense+sparse RRF, filter `project_id ∈ {active, "__ALL__"}`
- [ ] `extract/`: pdf2text + ocr_markdown
- [ ] `admin/collections` + `admin/scroll`
- [ ] Round-trip + incremental test

### Phase 5 — media_service
- [ ] Refactor `media_server.py` → `media_service/query_api.py`, **giữ contract** (§4.4)
- [ ] `POST/DELETE /index`: fetch → thumbnail → caption/video → embed → upsert
- [ ] `caption` 2 chiều (§4.2b)
- [ ] `admin/*` + test

### Phase 6 — Worker + orchestration CMS
- [ ] `indexing/directives.py`: `rag_config` → IndexDirective
- [ ] `indexing/clients/`: httpx + retry + backpressure 429
- [ ] `worker.py` consume Redis, concurrency cap
- [ ] Ghi lại `caption`/`extracted_text`/index-status vào Postgres
- [ ] `GET …/{id}/index-status` cho dashboard

### Phase 7 — Vận hành
- [ ] `cli`: provision-tenant · teardown · backfill · reconcile
- [ ] `scheduler.py`: reconcile cron
- [ ] Backfill `media_v3` → `<slug>_media` (§11.3)
- [ ] Test cascade + `__ALL__` + contract test
- [ ] systemd unit tách query/ingest; CI cho cả 2 repo

---

## 14. Quyết định còn mở

**Cần chốt trước khi code:**

1. **Repo CMS mới hay tiếp tục repo này?** Working tree đang có 278 file deleted chưa
   commit. Nếu làm repo mới → cần quyết định mang gì sang (khuyến nghị: `verticals/` +
   `kb/` + `docs/db-design/`). Nếu ở lại → cần 1 commit "remove FE + Mongo backend" trước.
2. **Job queue lib** — Redis list thô (đơn giản, đã có `QUEUE_KEY = "rag:jobs"`) vs arq
   (retry/scheduling sẵn). `02b` §9 để mở. Khuyến nghị **arq** vì cần retry + backoff cho
   external API.
3. **Thumbnail WebP do ai làm?** Hiện `02a` để `thumb_url` trong bảng `media`. Nếu
   media_service làm thì nó cần **quyền ghi MinIO** → phá nguyên tắc §4.2a. Ba lựa chọn:
   (a) CMS làm thumbnail lúc confirm (pillow, CPU, rẻ) ← khuyến nghị;
   (b) media_service trả bytes, CMS ghi;
   (c) cấp write-scoped presigned PUT cho service.
4. **PK `bigint identity` vs `uuid`** (`01` §Quyết định mở) — bigint mặc định; uuid nếu cần
   id public không đoán được.
5. **Tên 4 vai trò workspace** (`01` §Quyết định mở, Notion N4 chưa chốt).
6. **`pdf2text` engine** — pymupdf vs pdfminer + ngưỡng "PDF scan → OCR" (`02b` §9).

**Mâu thuẫn phát hiện trong doc hiện tại — cần sửa khi mang sang:**

7. `02a` §7 ghi *"Danh mục media | 9 category"* nhưng `enums.py::MediaCategory`,
   `media_categories.py`, và `rag_config.media.visual` đều có **7**. Con số 7 là đúng
   (`csbh`/`phap_ly` đã chuyển sang `documents` theo `02a` §6). Sửa `02a` §7 → 7.
8. `01` §Δ ghi *"`tenants` … −`qdrant_media_coll`"* nhưng bảng `tenants` ở chính file đó
   **có** cột `qdrant_media_coll`. Bảng đúng, dòng Δ sai. Sửa dòng Δ.
9. `media/README.md` của santa-models liệt kê `category` gồm `csbh` — đó là di sản
   `media_v3`. Collection mới `<slug>_media` chỉ có 7 category, không có `csbh`.
10. `media_v3` có `content_type ∈ {image, video, tour_360, document}`; thiết kế mới chỉ
    còn **`image` | `video`** (`02a` §4.5 — *"media giờ thuần ảnh/video"*; document đã
    chuyển sang bảng `documents`). Khi backfill (§11.3) phải quyết định số phận point
    `tour_360`/`document` đang có: bỏ hẳn, hay `tour_360` → một category/kind mới. Cần
    kiểm tra agent hiện tại có phụ thuộc `tour_360` không trước khi bỏ.

---

## 15. Phụ lục — bảng tham chiếu

### 15.1 `rag_config["real_estate"]` (nguyên văn từ `verticals/real_estate/rag_config.py`)

```python
RAG_CONFIG = {
    "anchor": "projects",
    "embed_sources": [
        {"table": "projects", "doc_type": "thong_tin", "chunk": "facts",
         "fields": ["region", "investor", "total_land_area_m2", "floor_area_m2",
                    "build_density_pct", "product_scale", "ownership_form",
                    "handover_standard", "total_investment_vnd"]},
        {"table": "projects", "doc_type": "tong_quan", "chunk": "markdown",
         "fields": ["overview", "amenities"]},
        {"table": "zones", "doc_type": "phan_khu", "chunk": "markdown",
         "fields": ["overview"]},
        {"table": "documents", "doc_type": "tai_lieu", "chunk": "structured_md",
         "fields": ["title", "body"]},
    ],
    "media": {"visual": ["tong_quan", "ngoai_that", "noi_that", "tien_ich",
                         "mat_bang", "vi_tri", "tien_do"]},
    "document_extract": {"pdf_text": "pdf2text", "pdf_scan": "ocr_markdown"},
    "caption_profiles": {"default": "caption_full", "vi_tri": "caption_subject",
                         "tien_do": "caption_subject", "mat_bang": "caption_subject"},
}
```

> `units` **KHÔNG** embed — chỉ ở Postgres (search/filter/inventory bằng SQL).
> `doc_type` chỉ để phân biệt point-id khi 1 bảng embed nhiều lần (`projects` xuất hiện 2
> lần) — **không** vào payload, **không** filter theo nó.

### 15.2 6 chunk strategy (`02b` §3.C)

| Strategy | Đơn vị chunk | Dùng cho |
|---|---|---|
| `facts` | gộp `fields` → 1 chunk | projects quick-facts |
| `markdown` | markdown-aware `max_chars`/`overlap` | overview, amenities |
| `atomic` | 1 record → 1 chunk | FAQ |
| `per_row` | 1 row → 1 chunk | (dự phòng) |
| `merged_list` | gộp nhiều record → 1 doc | (dự phòng) |
| `structured_md` | tách theo `##`, **giữ bảng nguyên** | documents (CSBH/pháp lý) |

Chung mọi strategy: breadcrumb `section` prepend vào chunk; overlap giữ ngữ cảnh biên;
**không cắt giữa bảng markdown** (bảng lớn → cắt theo dòng, lặp header + breadcrumb).
Mặc định `max_chars=800`, `overlap=150`.

### 15.3 `PROFILES` (nguyên văn từ `rag/profiles.py`)

```python
PROFILES = {
    "caption_full":    {"kind": "caption", "focus": "full",   "ocr": False},
    "caption_subject": {"kind": "caption", "focus": "subject", "ocr": False},
    "ocr_markdown":    {"kind": "ocr",     "format": "markdown"},
    "pdf2text":        {"kind": "extract", "format": "text"},
}
```
Prompt VLM: tiếng Việt, temp 0, **cấm brand/marketing**, không bịa số liệu. `resize` 1600px,
`max_tokens` 4096 (`02b` §3.D).

### 15.4 Payload Qdrant — freeze, đây là contract

**`<slug>_documents`** — named vectors `dense`(e5 1024, cosine) + `sparse`(BM25), RRF.
Payload index: `project_id`.

| Field | Kiểu | Ghi chú |
|---|---|---|
| `project_id` | keyword (index) | = `project_code`; **giữ tên key** cho agent |
| `project_name` | text | tên thương mại |
| `section` | text | breadcrumb, đã prepend vào `text` |
| `chunk_index` | int | thứ tự chunk trong 1 nguồn |
| `text` | text | nội dung chunk |
| `content_hash` | keyword | sha1 → incremental/drift |
| `source_file_url` | keyword? | link PDF gốc nếu chunk trích từ file |

Point-id: `uuid5(f"{doc_type}:{record_id}:{idx}")`

**`<slug>_media`** — named vectors `text`(e5 1024) + `visual`(SigLIP2
`google/siglip2-base-patch16-256`, 768), RRF. Payload index: `project_id`, `category`,
`content_type`.

| Field | Kiểu |
|---|---|
| `project_id` | keyword (index) |
| `content_type` | keyword (index) — `image`\|`video` |
| `category` | keyword (index) — 7 giá trị |
| `caption` | text — nguồn embed vector `text` |
| `media_url` | text |
| `thumb_url` | text |
| `content_hash` | keyword |

Point-id: `uuid5(f"media:{project_id}:{sha1(media_url)}")`
Vector `text` = `dense("passage: {project} › {category}\n{caption}")`

### 15.5 Enum real_estate (`verticals/real_estate/enums.py`)

```
Category:      can_ho · biet_thu · shophouse · lien_ke · dat_nen · penthouse · duplex
SaleStatus:    con_hang · giu_cho · da_ban · khong_ban
Direction:     dong · tay · nam · bac · dong_nam · dong_bac · tay_nam · tay_bac
DocType:       faq · phap_ly · chinh_sach_ban_hang · huong_dan · khac
MediaCategory: tong_quan · ngoai_that · noi_that · tien_ich · mat_bang · vi_tri · tien_do
```

### 15.6 Cột chung mọi bảng KB (`02` §6)

`id` (PK) · `tenant_id` (FK, RLS) · `status` (`draft`|`published`|`archived`) ·
`created_at`/`updated_at` (timestamptz). Bảng con thêm `project_code` + FK tổ hợp
`(tenant_id, project_code)`.

**Phase này manual-only:** không có `source` · `external_id` · `synced_at` · `verified_at`.
Khi thêm sync sau này → đưa lại `source` + `external_id` + `UNIQUE(tenant_id, source,
external_id)` để upsert idempotent.

### 15.7 Luật completeness (`02a` §7)

- `projects`: cần `name` + `region` + `overview`
- `units`: cần `price_vnd` + `area_built_m2` + `sale_status`

Tính **lúc publish/đọc**, không lưu cột. Fail → chặn publish + trả danh sách field thiếu.

### 15.8 Field CORE agent lọc (`02a` §7)

`product_type` · `price` · `area` · `direction` · `unit_code` · `sale_status` ·
`bedrooms` · `region` · `investor` · `category`

Cột thật, có index. Agent lọc trên bộ này, **không** cấu hình per-field.
