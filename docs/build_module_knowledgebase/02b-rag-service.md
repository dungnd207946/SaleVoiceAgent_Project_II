# 02b · RAG Service — engine generic (embed · vision · caption · chunk · store)

> Service **event-driven multi-tenant** để embed + lưu + truy hồi tri thức KB. Thiết kế **generic, vertical-agnostic**: mọi *cơ chế* nằm ở engine + 5 module; mọi phần *lĩnh vực* là **data khai báo** (`rag_config` + `PROFILES`). Giá trị cụ thể cho BĐS ở `02a` §7.1.
>
> Chú thích Δ: `🆕` mới · `✏️` đổi · `📎` khớp hệ thật.

---

## 1. Kiến trúc tổng

```
                                     ┌─ caption_worker    : VisionExtractor · VideoExtractor → (caption/OCR text)
CMS API ─emit event─▶ Redis queue ─▶ ├─ text_embed_worker  : Chunker → Embedder(dense+sparse) → VectorStore
  publish/edit/upload                ├─ media_embed_worker : Embedder(text+visual) → VectorStore
                                     └─ reconcile_worker   : VectorStore (scroll↔drift, cron)
Orchestrator ─đọc rag_config[vertical]─ráp module (mỗi worker = 1 pipeline)─▶ Qdrant (<slug>_documents, <slug>_media)
Adapter ObjectStore/VectorStore ở ranh giới kho                             └▶ MinIO (file gốc + webp thumb)
```
> Mỗi worker là **1 pipeline module**; mỗi loại data đi 1 đường riêng xuyên qua các worker (ảnh/video → caption_worker → media_embed_worker → `_media`; văn bản → text_embed_worker → `_documents`; PDF → caption_worker(OCR) → text_embed_worker → `_documents`). Khối chung (Embedder, VectorStore, MinIO) dùng lại; đường riêng theo loại.

- Object storage = **MinIO** (S3-compatible, self-hosted; storage layer dùng S3-API, endpoint trỏ MinIO).
- Job mang `tenant_id`; worker set RLS/scope đúng workspace. Cách ly: collection + MinIO prefix theo **workspace lá**.
- Tenant → vertical (`tenant_verticals`, `01`) → `rag_config[vertical]`. Engine **không hardcode** lĩnh vực.
- External API (VLM/Gemini) → rate-limit + retry backoff.

---

## 2. Năm module generic (zero domain knowledge)

**1. `Embedder`** — vectorizer thuần
| Method | Trả | Model |
|---|---|---|
| `dense(texts, is_query)` | vec 1024 | e5-large (prefix `passage:`/`query:`, L2-norm, cosine) |
| `sparse(texts)` | SparseVector | BM25 (fastembed `Qdrant/bm25`, IDF) |
| `visual_image(images)` | vec 768 | SigLIP2 image tower |
| `visual_text(texts)` | vec 768 | SigLIP2 text tower |

**Backend (chọn qua config):** **A** — santa-models HTTP (`embed_server :8013` e5, `media_server :8015` SigLIP2 GPU) *(khuyến nghị: không nhân đôi model)*; **B** — local (`fastembed` + `transformers/torch`). Đổi backend không đụng worker.

**2. `VisionExtractor`** — **ảnh → text** (gộp caption + OCR): `extract(image, profile) → text`. `profile` ∈ `PROFILES` (data). Backend Qwen-VL `qwen-vl-max`.

**3. `VideoExtractor`** — **video → text**: `describe(video_ref, prompt) → text`. Backend Gemini `gemini-2.5-flash` (YouTube `FileData(uri)` / mp4 Files API).

**4. `Chunker`** — **text → chunks**: toolbox chiến lược (§4). Hàm text thuần.

**5. `VectorStore` / `ObjectStore`** — adapter Qdrant / MinIO thuần (upsert/scroll/delete; put/presign).

> `VisionExtractor`/`VideoExtractor`/`Embedder` là **primitive**: nhận input + tham số, trả output — không biết "BĐS"/"CSBH". Phần lĩnh vực chỉ là profile/config truyền vào.

---

## 3. `rag_config` — schema (data khai báo per-vertical)

### A. `rag_config` (top-level)
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `anchor` | object | entity neo: bảng gốc + field code + field tên | `{table:"projects", code_field:"project_code", name_field:"name"}` |
| `embed_sources` | list\<object\> | nguồn text → `_documents` (bảng B) | `[…]` |
| `media.visual` | list\<text\> | category media = **ảnh/video để GỬI** → `_media` | `["mat_bang","tien_ich",…]` |
| `document_extract` | map\<engine\> | `documents.file_url` (PDF) → trích text vào `body` bằng engine nào | `{pdf_text:"pdf2text", pdf_scan:"ocr_markdown"}` |
| `caption_profiles` | map\<category → profile\> | category ảnh dùng profile nào (`default` cho cái không khai) | `{default:"caption_full", vi_tri:"caption_subject"}` |
| `chunk_defaults` | object? | tham số chunk mặc định | `{max_chars:800, overlap:150}` |

### B. `embed_sources[]` (mỗi nguồn embed)
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `table` | text | bảng KB nguồn | `"faqs"` |
| `doc_type` | text | nhãn loại tài liệu (breadcrumb + phân loại) | `"hoi_dap"` |
| `fields` | list\<text\> | các cột ghép thành text để embed | `["question","answer"]` |
| `chunk` | enum | chiến lược chunk (bảng C) | `"atomic"` |
| `filter` | text? | điều kiện lọc thêm (optional) | `"status='published'"` |

### C. `chunk` strategy (toolbox generic — engine cài sẵn)
| Strategy | Đơn vị chunk | Dùng cho (BĐS) |
|---|---|---|
| `facts` | gộp `fields` → 1 chunk | projects quick-facts |
| `markdown` | markdown-aware `max_chars/overlap` | overview, documents |
| `atomic` | 1 record → 1 chunk | faqs |
| `per_row` | 1 row → 1 chunk | finishings |
| `merged_list` | gộp nhiều record → 1 doc | materials |
| `structured_md` | tách theo `##`, **giữ bảng nguyên** | sales_policies, legal_docs |

Chung mọi strategy: breadcrumb `section` = `{anchor_name} > {doc_type/mục}`; overlap giữ ngữ cảnh biên; **không cắt giữa bảng markdown** (bảng lớn → cắt theo dòng, lặp header + breadcrumb).

### D. `PROFILES[]` (thư viện profile của `VisionExtractor` — generic, dùng chung mọi vertical)
| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `name` | text (key) | tên profile | `"ocr_markdown"` |
| `prompt` | text | prompt gửi VLM (tiếng Việt, temp 0, cấm brand/marketing) | `"Đọc toàn bộ ảnh → markdown ## + bảng, giữ số liệu, không bịa"` |
| `output` | enum `text`\|`markdown` | định dạng đầu ra | `"markdown"` |
| `max_tokens` | int | giới hạn output | `4096` |
| `resize` | int (px) | cạnh resize trước khi gửi VLM | `1600` |

### E. Ví dụ đầy đủ — `rag_config["real_estate"]`
```python
RAG_CONFIG["real_estate"] = {
  "anchor": {"table": "projects", "code_field": "project_code", "name_field": "name"},

  # nguồn embed → <slug>_documents: (bảng, doc_type, fields→text, chiến lược chunk)
  "embed_sources": [
    {"table":"projects",  "doc_type":"thong_tin", "chunk":"facts",
     "fields":["region","investor","total_land_area_m2","floor_area_m2","build_density_pct",
               "product_scale","ownership_form","handover_standard","total_investment_vnd"]},
    {"table":"projects",  "doc_type":"tong_quan", "chunk":"markdown",      "fields":["overview","amenities"]},
    {"table":"zones",     "doc_type":"phan_khu",  "chunk":"markdown",      "fields":["overview"]},
    {"table":"documents", "doc_type":"tai_lieu",  "chunk":"structured_md", "fields":["title","body"]},
  ],

  # media: chỉ ảnh/video để GỬI (→ _media). CSBH/pháp lý KHÔNG ở media (→ documents)
  "media": {"visual": ["tong_quan","ngoai_that","noi_that","tien_ich","mat_bang","vi_tri","tien_do"]},

  # documents có file_url (PDF) → trích text vào body trước khi embed
  "document_extract": {"pdf_text": "pdf2text", "pdf_scan": "ocr_markdown"},

  # category ảnh → profile của VisionExtractor (PROFILES ở §3.D)
  "caption_profiles": {"default":"caption_full",
                       "vi_tri":"caption_subject","tien_do":"caption_subject","mat_bang":"caption_subject"},

  "chunk_defaults": {"max_chars": 800, "overlap": 150},
}
```

> `rag_config` + `PROFILES` là **data**; thêm lĩnh vực mới = thêm 1 `rag_config` (+ profile nếu cần), **engine + 5 module không đổi**.

---

## 4. Pipeline TEXT → `<slug>_documents` (hybrid dense+sparse)

Trigger: record `status→published`, edit khi đang published, hoặc unpublish/archive (→ xoá).
1. Emit job `{tenant, table, record_id, op}`.
2. Orchestrator: tenant→vertical→`rag_config`; tìm `embed_sources` khớp `table`.
3. Đọc record (+ `anchor.name_field`); ghép `fields` → source-doc; gắn `doc_type`, breadcrumb `section`.
4. `Chunker[chunk]` → chunks (theo strategy bảng C).
5. `Embedder.dense(passage)` + `Embedder.sparse` → named vectors `{dense, sparse}`.
6. Point: id `uuid5(doc_type:record_id:idx)`; payload `{project_id(=anchor code), project_name, section, chunk_index, text, content_hash, source_file_url?}`.
7. Incremental: scroll points hiện có của `(project_id, source)` → `{id: content_hash}`; upsert chunk đổi; **xoá point thừa**; op=delete/unpublish → xoá hết point của source.
8. `VectorStore.upsert`.

**Query (`kb_search`):** `Embedder.dense+sparse(query)` → 2 `Prefetch`(`dense`,`sparse`) + `FusionQuery(RRF)`, filter `project_id ∈ {dự_án_active, "__ALL__"}` (luôn gộp tài liệu chung tenant, §6b).

---

## 5. Pipeline MEDIA → `<slug>_media` (hybrid text+visual)

Trigger: media upload/publish, `category ∈ rag_config.media.visual`.
1. File → MinIO (gốc) → WebP thumbnail → MinIO (`thumb_url`).
2. Caption: `VisionExtractor.extract(img, PROFILES[caption_profiles[category] or default])` (ảnh) hoặc `VideoExtractor.describe` (video) → `media.caption` (auto) → UI cho user sửa.
3. Embed: `text` = `dense(passage: "{project} › {category}\n{caption}")`; `visual` = `visual_image(ảnh)` hoặc `visual_image(thumbnail video)`.
4. Point: id `uuid5(media:{project_id}:sha1(media_url))`; named vectors `{text, visual}`; payload `{project_id, content_type, category, caption, media_url, thumb_url, content_hash}`.
5. Incremental + upsert.

**Query (`send_media`):** `dense(query)` + `visual_text(query)` → 2 `Prefetch`(`text`,`visual`) + RRF, filter `project_id ∈ {active, "__ALL__"}`(+`category`).

---

## 6. Tài liệu có file (CSBH/pháp lý/PDF) → `documents` → `_documents`

`documents` có `file_url` (PDF) đi luồng tài liệu — **không** đụng `media`/`_media`:
1. Upload file PDF → MinIO; tạo/cập nhật row `documents` với `file_url`.
2. Trích text (markdown) theo `document_extract`: PDF-text → `pdf2text`; PDF-scan/ảnh → `VisionExtractor.extract(img, PROFILES["ocr_markdown"])` → ghi `documents.body`.
3. Record publish → **luồng TEXT** (§4), `payload.source_file_url = documents.file_url`.
4. Trả **file** cho khách: tool `get_document(project_code, …)` (query `documents`) hoặc `source_file_url` sau `kb_search`.

## 6b. Tài liệu cấp tenant (sentinel `"__ALL__"`)

Record `documents`/`media` **chung cả tenant** (giới thiệu công ty, quy trình mua, brochure…) đặt `project_code = "__ALL__"` (row `projects` hệ thống seed sẵn; chỉ documents/media dùng).
- Embed như thường → `payload.project_id = "__ALL__"`.
- Truy hồi (`kb_search`/`send_media`) filter `project_id ∈ {dự_án_active, "__ALL__"}` → **luôn kèm** tri thức chung. Không có dự án active → chỉ `"__ALL__"`.
- Không cần cột `scope`/nullable; visibility theo `status` riêng của record (không cascade dự án).

---

## 7. Incremental & Reconcile

- `content_hash` (sha1) mỗi point → chỉ re-embed cái đổi, xoá cái thừa.
- **Event job:** cập nhật ngay khi publish/edit/unpublish (freshness Bậc-1).
- **Reconcile job (cron/workspace):** so tập `published` ở Postgres vs point Qdrant → thêm thiếu, xoá thừa → bắt event bị miss (lưới an toàn).

---

## 8. Điểm nổi bật

- Service **event-driven + reconcile** (không phải script chạy tay).
- **5 module generic** + `rag_config`/`PROFILES` data → **đa lĩnh vực** không đụng engine.
- `_documents` **hybrid** (dense e5 + sparse BM25, RRF); `_media` **hybrid** (text e5 + visual SigLIP2, RRF).
- Caption **on-upload auto + user sửa**; **OCR-cấu-trúc** (markdown `##` + bảng) cho tài liệu.
- Object storage **MinIO**.

---

## 9. Quyết định còn mở

1. Backend `Embedder`: santa-models HTTP vs local — chốt khi code (mặc định santa-models).
2. Job queue lib (arq/celery/rq) — chốt khi code.
3. Tham số chunk cụ thể mỗi strategy (max_chars/overlap) — tinh chỉnh sau đo chất lượng.
4. `pdf2text` engine (pymupdf vs pdfminer) + ngưỡng "PDF scan → OCR".
