# 02c · Module ingest KB — hợp đồng đọc/ghi Postgres

> Nhóm **B**, tiếp `02` · `02a` · `02b`. Giả định **DB theo đúng `02a`/`01`** (tên cột của doc là
> chuẩn; migration hiện tại sẽ được sửa theo).
>
> Phạm vi: `src/portal/modules/kb/` — đưa dữ liệu **đã có trong Postgres** lên **S3 + Qdrant**.
> Nhập liệu (FE → Postgres) **không thuộc** doc này.

---

## 1. Bảng module này chạm — ba mức quyền

| Mức | Bảng · cột | Ghi chú |
|---|---|---|
| **Chỉ đọc** | `control.tenants(id, slug, status)` · `control.tenant_verticals(vertical, enabled)` | `slug` → tên collection · prefix S3 |
| **Chỉ đọc** | `projects` · `zones` · `documents` · `media` (bảng của M4) | không `ALTER`, không `DELETE` |
| **Ghi 3 cột của M4** | `documents.body` · `media.caption` · `media.thumb_url` · `media.content_hash` | cache kết quả service — **cần thoả thuận với M4** |
| **Sở hữu** | `tenant_data.kb_index_state` | migration `0500`, §5 |

`units` **không** ingest (`15.1`: chỉ Postgres, agent lọc bằng SQL).

---

## 2. Bốn nguồn TEXT → `<slug>_documents`

Theo `rag_config["real_estate"].embed_sources`. Mọi câu chạy trong `tenant_conn()` (RLS đã lọc
tenant) và **luôn kèm điều kiện anchor published**.

### 2.1 `projects` · doc_type `thong_tin` · chunk `facts`
```sql
SELECT id, project_code, name,
       region, investor, total_land_area_m2, floor_area_m2, build_density_pct,
       product_scale, ownership_form, handover_standard, total_investment_vnd
FROM   tenant_data.projects
WHERE  id = $1 AND status = 'published';
```
`section` = `name`. Gộp 9 field còn lại → **1 chunk**.

### 2.2 `projects` · doc_type `tong_quan` · chunk `markdown`
Cùng row, `fields = [overview, amenities]`. `section` = `name`.

### 2.3 `zones` · doc_type `phan_khu` · chunk `markdown`
```sql
SELECT z.id, z.project_code, z.name, z.overview, p.name AS project_name
FROM   tenant_data.zones z
JOIN   tenant_data.projects p
       ON (p.tenant_id, p.project_code) = (z.tenant_id, z.project_code)
WHERE  z.id = $1 AND z.status = 'published' AND p.status = 'published';
```
`section` = `"{project_name} > {z.name}"`.

### 2.4 `documents` · doc_type `tai_lieu` · chunk `structured_md`
```sql
SELECT d.id, d.project_code, d.title, d.body, d.file_url, p.name AS project_name
FROM   tenant_data.documents d
JOIN   tenant_data.projects p
       ON (p.tenant_id, p.project_code) = (d.tenant_id, d.project_code)
WHERE  d.id = $1 AND d.status = 'published' AND p.status = 'published';
```
`section` = `"{project_name} > {d.title}"` · `text` = `title + "\n" + body`.
`body` rỗng **và** có `file_url` → `extract_profile = pdf2text` (hoặc `ocr_markdown`), presign
`file_url` → `source_file_url`.
`documents` **không có `category`** (`02a` §4.4) → luôn một strategy duy nhất.

---

## 3. Nguồn MEDIA → `<slug>_media`

```sql
SELECT m.id, m.project_code, m.content_type, m.category, m.caption,
       m.media_url, m.thumb_url, m.content_hash, p.name AS project_name
FROM   tenant_data.media m
JOIN   tenant_data.projects p
       ON (p.tenant_id, p.project_code) = (m.tenant_id, m.project_code)
WHERE  m.id = $1 AND m.status = 'published' AND p.status = 'published'
  AND  m.category = ANY($2);      -- rag_config.media.visual, 7 giá trị
```
`category` ngoài 7 giá trị đó → **không index** (vẫn giữ trong Postgres để dashboard hiện).

---

## 4. Row → directive (§4.1 của doc kiến trúc)

| Trường gửi service | Lấy từ |
|---|---|
| `workspace_slug` | `tenants.slug` |
| `record_id` | `id` của row |
| `doc_type` | `embed_sources[].doc_type` — **chỉ để dựng point-id** |
| `anchor_code` | `project_code` → `payload.project_id` |
| `anchor_name` | `projects.name` → `payload.project_name` |
| `section` | breadcrumb §2 |
| `text` | ghép `fields` theo `embed_sources[].fields` |
| `chunk` | `{strategy, max_chars: 800, overlap: 150}` |
| `source_file_url` | presign GET `documents.file_url`, TTL ngắn |
| `extract_profile` | `document_extract` — `null` nếu `body` đã có |
| `caption` / `caption_profile` | `media.caption` (rỗng → `null`) · `caption_profiles[category]` |
| `media_url` / `file_url` | `media.media_url` · presign nếu là key S3, **`null` nếu URL ngoài** |

---

## 5. `tenant_data.kb_index_state` — bảng duy nhất module này tạo

```sql
CREATE TABLE tenant_data.kb_index_state (
    id           bigserial PRIMARY KEY,
    tenant_id    <FK tenants>,
    entity       text NOT NULL,               -- projects|zones|documents|media
    record_id    bigint NOT NULL,
    doc_type     text NOT NULL DEFAULT '',    -- projects embed 2 lần → phải có
    target       text NOT NULL CHECK (target IN ('documents','media')),
    state        text NOT NULL DEFAULT 'queued'
                 CHECK (state IN ('queued','indexing','indexed','error','deleted')),
    content_hash text NOT NULL DEFAULT '',
    points       integer NOT NULL DEFAULT 0,
    error        text NOT NULL DEFAULT '',
    attempts     smallint NOT NULL DEFAULT 0,
    indexed_at   timestamptz,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, entity, record_id, doc_type)
);
SELECT control.enforce_tenant_isolation('tenant_data.kb_index_state');
```

`UNIQUE` phải có `doc_type`: `projects` sinh **hai** dòng (`thong_tin`, `tong_quan`).

---

## 6. Cascade & reconcile

**Fan-out khi anchor rời `published`** (`02` §2, `§7.3`) — `units` không có mặt vì không embed:
```sql
SELECT 'zones'     AS entity, id FROM tenant_data.zones     WHERE project_code = $1
UNION ALL SELECT 'documents', id FROM tenant_data.documents WHERE project_code = $1
UNION ALL SELECT 'media',     id FROM tenant_data.media     WHERE project_code = $1;
```
`project_code = '__ALL__'` là row hệ thống, **luôn published** → không bao giờ vào fan-out.

**Reconcile:** tập mong đợi (`status='published'` + anchor published) so với `POST /admin/scroll`
→ thiếu thì enqueue `upsert`, thừa thì `DELETE /index`.

---

## 7. Bốn quyết định phát sinh từ schema

**D1 — Tên collection sinh trong code, không đọc `tenants.qdrant_documents_coll`.** `01` §2 khai hai
cột đó, nhưng cột **sửa được** là một đường rò: đặt tên collection của tenant B vào hàng của tenant A
thì RLS không chặn gì cả (nó là text, không phải FK). Sinh `f"{slug}_documents"` trong code — khớp
yêu cầu ở spec kiến trúc §9 (*"tên sinh trong code"*). Hai cột kia giữ để audit, hoặc bỏ.

**D2 — `content_hash`: service là nguồn sự thật.** Nó hash đúng thứ nó index (chunk text / caption +
bytes ảnh); portal không thể tái tạo mà không biết chunk strategy. `media.content_hash` và
`kb_index_state.content_hash` **ghi từ response**, chỉ dùng để bỏ qua job trùng.

**D3 — `tenants.id` bigint theo `01` là thay đổi của M1, không phải của module này.** Migration hiện
tại dùng `id text` có `CHECK` vì nó đi thẳng vào `CREATE ROLE agent_<id>`; đổi sang bigint đụng
`current_tenant()`, FK mọi bảng `tenant_data`, và cách sinh tên role. Module `kb/` chỉ cần **`slug`**
— nếu M1 chưa đổi thì `slug := tenants.id` là đủ, không chặn.

**D4 — Ghi vào bảng của M4 là seam cần chốt.** `documents.body` (extracted_text), `media.caption`,
`media.thumb_url`, `media.content_hash`. Bốn cột này M4 cũng ghi (user sửa trên dashboard) → cần luật
"ai thắng": đề xuất **user thắng** (portal chỉ ghi khi cột đang rỗng), trừ `content_hash`/`thumb_url`
luôn do ingest ghi.
