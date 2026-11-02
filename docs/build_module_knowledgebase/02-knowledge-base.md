# 02 · Knowledge Base — nguyên tắc chung (PostgreSQL, `tenant_data`)

> Nhóm **B**. **Khung chung, không phụ thuộc lĩnh vực** cho mọi Knowledge Base: KB là gì, anchor, visibility, freshness, cách ly, bộ cột chung, cách agent đọc, pattern RAG, và **cơ chế template lĩnh vực**.
>
> Instantiation cụ thể cho **bất động sản** ở `02a-real-estate-template.md`; RAG service (engine embed/caption/store) ở `02b-rag-service.md`. Lĩnh vực mới sau này chỉ cần thêm 1 file template, **không đụng** doc này.
>
> Chú thích Δ: `🆕` mới · `✏️` đổi · `📎` khớp Notion/hệ thật · `⚠️` cố ý khác.

---

## 1. KB là gì — phạm vi

**KB** = dữ liệu tenant **curate** để **agent đọc phục vụ khách**. Ba loại nội dung:
- **Dữ liệu cấu trúc** (entity nghiệp vụ của lĩnh vực) — lọc/tra chính xác.
- **Văn bản** (`documents`) → chunk + embed → hỏi–đáp ngữ nghĩa + trích dẫn. Một bảng `documents` gánh mọi tri thức văn bản (FAQ/pháp lý/chính sách/hướng dẫn…), phân biệt bằng `title` — không tách nhiều bảng.
- **Media** (ảnh/video/tour/file) → metadata (Postgres) + file (MinIO), gửi cho khách.

**KHÔNG thuộc KB** `⚠️`(khác DL_01 BR09 — bỏ gate đọc):
- Trường **nội bộ nhạy cảm** (hoa hồng, giá net, chiết khấu tối đa…) → **bỏ hẳn, không lưu** ở bảng KB. Agent đọc được **tất cả** những gì có trong KB → **không cần cột gate**.
- Dữ liệu agent tự sinh (contacts/conversations/appointments) → nhóm **C** (`04`).

> **Vì sao bỏ gate:** không đưa dữ liệu nhạy cảm vào KB ngay từ đầu, thay vì lưu chung rồi che bằng `VIEW agent_*`. Đơn giản, không rủi ro lộ do cấu hình view sai.

---

## 2. Anchor pattern — 1 entity neo

Mỗi KB có **một entity neo**; mọi entity khác trỏ về nó bằng **business code** (không phải id nội bộ), FK tổ hợp mang cả `tenant_id`:

```
<anchor>  (vd real-estate = projects)
   ├─N <child>   → FK (tenant_id, <anchor_code>)
   ├─N documents → FK (tenant_id, <anchor_code>)   (<anchor_code> = "__ALL__" = tài liệu chung tenant)
   └─N media     → FK (tenant_id, <anchor_code>)
```

- **FK tổ hợp `(tenant_id, <anchor_code>)`** `📎` — Postgres **chặn tham chiếu chéo tenant** ở tầng DB (lưới an toàn thứ 2 sau RLS).
- **Cascade theo anchor:** anchor `status≠published` → ẩn toàn bộ cây con khỏi mọi kết quả agent `📎`(DL_01 BR11).
- **Tài liệu cấp tenant (project-less):** chỉ **nội dung lá** (`documents`/`media`) có bản cấp-tenant, đặt **`<anchor_code> = "__ALL__"`**; entity anchor/con (projects/zones/units) không dùng. `"__ALL__"` là **1 row anchor hệ thống** seed sẵn mỗi tenant (status=published) → giữ FK, không cần nullable/`scope`. Truy hồi luôn gộp `IN {active, "__ALL__"}`.

---

## 3. Visibility — `status` (không gate, không cờ thừa)

Mỗi bảng KB có **`status`**: `draft` (đang soạn, agent không thấy) · `published` (công khai) · `archived` (ẩn).

- **Cascade:** anchor phải `published` thì con mới hiện (JOIN lọc anchor.status + record.status = `published`).
- **Completeness ("thiếu dữ liệu")** = tính **lúc publish/đọc** theo luật của template (không lưu cột) — chặn publish + badge UI.
- Trạng thái **nghiệp vụ** (vd BĐS: giai đoạn bán) là field RIÊNG, độc lập với `status` hiển thị.
- Qdrant chỉ sync bản `published` (unpublish = xoá point) → payload không cần `status`.

`✏️` Bỏ `agent_enabled`/`is_agent_ready` (cột) — gộp về `status` + completeness computed.

---

## 4. Freshness — 3 bậc hiệu lực `📎`(HT_01)

| Bậc | Loại thay đổi | Hiệu lực | Cơ chế |
|---|---|---|---|
| **Bậc 1 — tức thì** | dữ liệu cấu trúc, tài liệu | agent thấy **ngay** truy vấn kế | đọc trực tiếp bảng KB; Qdrant re-embed khi text đổi (`content_hash`) |
| **Bậc 2 — đầu cuộc** | đổi anchor đang tư vấn | áp ở **đầu conversation** | agent resolve scope 1 lần khi mở phiên |
| **Bậc 3 — phải publish** | persona · kỹ năng · rào chắn | chỉ khi **publish** `config_versions` | nhóm D (`05`) |

Agent surface "**cập nhật lúc {updated_at}**" `📎`(DL_01 BR06).

---

## 5. Cách ly + kiểm chứng `📎`(0.2/0.3/KB_01 BR10)

Một **workspace lá** = 1 không gian KB trên 3 kho (org cha gộp con, **không có kho riêng**):

| Kho | Cách ly | Cưỡng chế |
|---|---|---|
| Postgres | cột `tenant_id` + **RLS FORCE** | sai tenant = 0 hàng; FK tổ hợp chặn tham chiếu chéo |
| Qdrant | **2 collection/workspace**: `<slug>_documents` (dense) + `<slug>_media` (hybrid text+visual) | collection riêng theo workspace = vật lý cách ly; xoá workspace = drop cả 2 |
| MinIO (S3-API) | **1 prefix/workspace** `<slug>/` | key luôn dưới prefix; IAM/policy theo prefix |

`📎` **Test cross-tenant BẮT BUỘC**: tenant A **không** đọc được dữ liệu B trên cả Postgres/Qdrant/S3 — điều kiện chặn merge.

---

## 6. Bộ cột CHUNG mọi bảng KB `🆕`

Mọi bảng KB đều mang các cột nền sau; template lĩnh vực khai thêm field đặc thù (và **không dùng `custom_fields`** — template khai đủ schema).

| Field | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `id` | PK | Khóa chính (surrogate) | `4501` |
| `tenant_id` | FK → tenants (RLS) | Khoá cách ly | `12` |
| `status` | text `draft`\|`published`\|`archived` | Hiển thị với agent (§3) | `"published"` |
| `created_at`/`updated_at` | timestamptz | Mốc tạo/sửa (Bậc-1 freshness) | `2026-07-29T08:00:00Z` |

Bảng con mang thêm `<anchor_code>` (+ FK tổ hợp).

> **Phase này nhập tay (manual-only):** bỏ `source` · `external_id` · `synced_at` · `verified_at` (đồ multi-source/sync + xác minh). Khi thêm import/sync (NobleX…) sẽ đưa lại `source` + `external_id` (khoá nguồn ngoài) + `UNIQUE(tenant_id, source, external_id)` để upsert idempotent.

---

## 7. Agent đọc KB thế nào

- **Đọc tất, không gate** (§1) — KB đã sạch dữ liệu nhạy cảm.
- **Lọc trên bộ field CORE cố định** (định nghĩa trong code theo template, không per-field).
- **Chỉ thấy bản `published` + đủ dữ liệu**, anchor cha `published` (§3).
- **Kèm mốc freshness** khi trả lời (§4).

---

## 8. Pattern RAG (áp mọi lĩnh vực)

**2 collection Qdrant / workspace** (engine + pipeline chi tiết ở `02b`):

| Collection | Vector | Dùng cho | Tool |
|---|---|---|---|
| `<slug>_documents` | **HYBRID** `dense`(e5 1024) + `sparse`(BM25), RRF | hỏi–đáp nội dung văn bản | `kb_search` |
| `<slug>_media` | **HYBRID** `text`(e5 1024) + `visual`(SigLIP2 768), RRF | gửi ảnh/video | `send_media` |

- **Tài liệu dài** (PDF): **text → `_documents`** (hỏi được), **file → `documents.file_url`** (trả về được). `media` chỉ chứa ảnh/video. Chi tiết ở `02a`/`02b`.
- Giữ cơ chế: chunk markdown-aware + breadcrumb, point-id `uuid5`, `content_hash` incremental/drift; chỉ sync bản `published`.

---

## 9. Cơ chế Template lĩnh vực `🆕`

Mỗi lĩnh vực = **một template code-defined, versioned** (registry trong code, không phải bảng). Khi tenant bật vertical (`tenant_verticals`, `01`) → **provisioning** dùng template để:

1. Khai **schema cố định** các bảng của lĩnh vực (không `custom_fields`).
2. Khai **enum mặc định** + đánh dấu single/multi (tenant mở rộng giá trị được).
3. Khai **bộ quick-fact field** để UI render form từng ô.
4. Khai **danh mục media**.
5. Khai **RAG config** (bảng/field embed, doc_type, tham số chunk) + tạo `<slug>_documents` & `<slug>_media`.
6. Khai **bộ field CORE agent lọc**.
7. Khai **luật completeness** ("đủ dữ liệu").
8. Tạo **MinIO prefix** `<slug>/`.
9. **Seed row anchor hệ thống** `<anchor_code>="__ALL__"` (status=published) cho tài liệu/media cấp tenant (§2).

→ Lĩnh vực đầu tiên: **`real_estate`** (`02a-real-estate-template.md`). Engine RAG chạy config này: `02b-rag-service.md`.

---

## 10. Δ tổng hợp (khung chung)

- `⚠️` Bỏ gate đọc (không lưu trường nhạy cảm) thay `VIEW agent_*`.
- `✏️` Visibility gộp về `status` (bỏ `agent_enabled`/`is_agent_ready`).
- `✏️` Bỏ `custom_fields` — template khai đủ schema.
- `📎` RAG: `_documents` **hybrid** (dense e5 + sparse BM25, RRF); `_media` **hybrid** (text e5 + visual SigLIP2, RRF). Engine ở `02b`.
- `📎` Giữ: anchor + cascade, 3 bậc freshness, cách ly 3 kho + test cross-tenant.

---

## 11. Quyết định còn mở

1. Ngưỡng freshness cụ thể (bao lâu coi là "cũ").
2. Khi thêm sync: đưa lại `source`/`external_id`/`synced_at` (+ `verified_at` nếu cần badge "đã xác minh").
3. Pipeline trích text PDF → `content` — chốt khi code.
