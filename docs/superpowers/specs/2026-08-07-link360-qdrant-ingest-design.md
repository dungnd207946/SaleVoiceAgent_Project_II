# Ingest link 360 vào Qdrant `<tenant>_documents`

**Ngày:** 2026-08-07
**Trạng thái:** design, chờ implement
**Tính chất:** hotfix — thiết kế để xoá được gọn, không để lại dấu vết trong `src/`

## Vấn đề

`link_360` của mỗi dự án đã nằm ở `tenant_data.projects.link_360` (Postgres) và ra
được qua tool `get_project_overview` (`data/providers/postgres_kb.py:170` →
`_serialize.py:55`). Nhưng `kb_search` — đường trả lời chính của Luna — chỉ đọc
Qdrant `<tenant>_documents`, do phía ingest ghi. Trong đó **không có** thông tin
tour 360. Khách hỏi "có tham quan ảo không / cho em xem tour 360" thì `kb_search`
trả context rỗng về khoản này.

Mục tiêu: chunk tour 360 có mặt trong `<tenant>_documents` để `kb_search` bắt được.

## Phạm vi

**Trong phạm vi:** một script ingest đọc Postgres → upsert 1 point/dự án vào
`<tenant>_documents`.

**Ngoài phạm vi (đã cân nhắc và loại):**

- **Đường `<tenant>_media`.** Không đạt mục tiêu: `kb_search` không đọc collection
  đó, chỉ `send_media` đọc. Ngoài ra đặt link 360 vào `media_url` sinh ảnh vỡ —
  `_hit_to_item` (`data/media_data.py`) chỉ sinh 2 kind: `_parse_youtube_id` trả
  `None` (anchor theo host YouTube), `_is_image_url` trả `False` (path không đuôi
  ảnh), nên chunk chỉ lọt khi ingest ghi `content_type="image"` → client chạy
  `<img src="https://kuula.co/…">` → icon ảnh vỡ ở cả lưới lẫn lightbox, và `<img>`
  không bấm ra link được. Đây đúng là lỗi vừa gỡ ngày 2026-08-06 (`thumb_url` trỏ
  MinIO private → phải tắt `MEDIA_SEND_THUMB`). `thumb` hiện cũng không được gửi
  (cờ mặc định `false`) nên set vào đó vô ích.
  Muốn đi đường media cho đúng thì phải có **ảnh preview thật** làm `media_url`,
  cộng thêm field `link` optional trên image item, sửa `_hit_to_item` + 2 web client
  + contract app mobile → app phải ra bản mới. Để dành cho slice sau.
- **Sửa `_format_kb_hits`.** Không cần: URL nằm thẳng trong `text` nên adapter
  render sẵn, không phải đụng code đọc.
- **Backfill `link_360` vào Postgres.** Dữ liệu đã có sẵn.

## Thiết kế

### Vị trí

Một file duy nhất: **`scripts/ingest_link360.py`**.

Không tạo package mới, không sửa gì trong `src/`. `scripts/` đã là nơi ở của đúng
loại việc này (`build_qdrant.py`, `mongo_migrate_noble_profile.py`,
`test_search_tools.py` — đều import `noble_agent` và chạy tay).

Gỡ hotfix = `python scripts/ingest_link360.py --delete` (dọn point trong Qdrant)
rồi `rm scripts/ingest_link360.py`. Không còn dấu vết.

### Luồng

```
tenant_data.projects
  SELECT project_code, name, link_360
  WHERE tenant_id = :tenant AND status = 'published'
    AND link_360 IS NOT NULL AND link_360 <> ''
        │  1 dự án = 1 chunk
        ▼
text = "{NAME}

        Tour tham quan thực tế ảo 360 độ

        Dự án {NAME} có tour tham quan thực tế ảo 360 độ trực
        tuyến. Khách hàng có thể xem trước toàn cảnh dự án, nhà
        mẫu và tiện ích mà không cần tới tận nơi, qua đường
        link: {link_360}"
        │  embed_client.embed_dense(side="index")
        │  embed_client.embed_sparse(side="index")     ← chạy song song
        ▼
upsert vào <tenant>_documents
  id      = uuid5(NAMESPACE_URL, f"{tenant}:{project_code}:link_360")
  vectors = {"dense": [...1024], "bm25": {indices, values}}
  payload = {
    project_id:      <project_code>,
    project_name:    <name>,
    section:         "Tour 360",
    chunk_index:     0,
    text:            <text ở trên>,
    content_hash:    sha1(text),
    doc_type:        "tour_360",
    updated_at:      None,
    source_file_url: None,
  }
```

Payload khớp shape point thật của ingest chính, trừ `record_id` (id hàng nguồn bên
Portal) — cố ý bỏ, không bịa ra id để khỏi đụng id thật.

`doc_type="tour_360"` là giá trị riêng, không trùng doc_type nào của ingest chính
(`thong_tin` / `tong_quan`), nên `--delete` không thể chạm dữ liệu của họ. Không có
đường đọc nào lọc theo `doc_type` (`build_scope_filter` chỉ lọc `project_id`) nên
thêm giá trị mới là an toàn.

Mở đầu text bằng tên dự án theo đúng quy ước chunk của ingest chính — giúp BM25
khớp khi khách gọi tên dự án.

### Các quyết định và lý do

**URL nằm trong `text`, không phải payload field riêng.**
`_format_kb_hits` (`agent/rag/kb_service_adapter.py:33-56`) chỉ render `text`,
`project_name`, `section`, `updated_at` — payload field khác bị bỏ qua. URL ở
payload thì LLM không nhìn thấy. Để trong `text` là cách duy nhất không phải sửa
code đọc.

**Embed qua `noble_agent.data.embed_client`, không tự viết.**
Đó chính là seam `kb_search` gọi lúc query (`kb_service_adapter.py:74-77`). Dùng
chung ⇒ chắc chắn cùng không gian vector và cùng từ vựng BM25. Rủi ro nếu tự viết:
model ingest lệch model query thì Qdrant trả rác **mà không báo lỗi** — đã đo được
E5-query trên collection E5 ~0.82 còn Gemini-query trên cùng collection ~0.03.
`side="index"` (không phải `"query"`) vì E5 prefix passage/query khác nhau.

**Point id tất định qua `uuid5`.**
Chạy lại = ghi đè đúng point cũ, không nhân bản. Không cần bảng theo dõi trạng
thái, không cần xoá trước khi ghi.

**Payload đúng khoá mà adapter đọc.**
`project_id` là khoá `build_scope_filter` lọc (`data/qdrant_search.py:136`) — phải
là canonical `project_code`, để `kb_search` với `project_filter` scope đúng dự án.
`section` = "Tour 360" hiện ra trong context dạng `[Tên dự án › Tour 360]`.

**Fail-loud khi collection không tồn tại.**
Dừng và báo lỗi, **không tự tạo**. Schema collection do phía ingest định nghĩa
(tên vector, dim, distance, payload index); tự tạo sai là hỏng cả collection cho
mọi document khác.

### CLI

```
python scripts/ingest_link360.py [options]

--tenant <id>      tenant cần ingest (vd noble-homes_k3n7_retail)
--all-tenants      mọi tenant có dự án mang link_360
--project <code>   chỉ làm 1 dự án
--pg-dsn <dsn>     nguồn Postgres (mặc định POSTGRES_DSN trong .env)
--dry-run          in ra text + số điểm sẽ ghi, không gọi embed, không ghi Qdrant
--delete           xoá point doc_type="tour_360" của tenant
```

Có `--all-tenants` vì thực tế đang là 4 tenant chứ không phải một; chạy tay từng
cái là chỗ dễ sót.

Config còn lại đọc từ `.env`: `QDRANT_URL`, `QDRANT_API_KEY`, `EMBED_*`,
`SANTA_MODELS_TOKEN`.

**Lưu ý DSN:** `POSTGRES_DSN` trong `.env` trỏ `10.50.13.220:5433` — không kết nối
được từ máy dev (connection refused). Nguồn dùng thật là mockdb
`postgresql://sp_admin:sp_admin_pw@127.0.0.1:5432/odyssey` (xem
`docs/handoff/postgres_access.md`), truyền qua `--pg-dsn`.

### Xử lý lỗi

| Tình huống | Hành vi |
|---|---|
| `QDRANT_URL` rỗng | dừng, báo lỗi |
| Collection `<tenant>_documents` không tồn tại | dừng, báo lỗi, **không tạo** |
| Postgres không kết nối được | dừng, báo lỗi |
| Không dự án nào có `link_360` | in cảnh báo, exit 0 (không phải lỗi) |
| Embed service lỗi | dừng, báo lỗi — không fallback sang model khác (fallback = sai không gian vector) |
| Một dự án lỗi giữa chừng | log dự án đó, tiếp tục các dự án còn lại, in tổng kết cuối |

## Kiểm chứng — đã chạy, kết quả thật

Không viết unit test — script ops một lần, giá trị nằm ở kiểm chứng live.

| # | Việc | Kết quả |
|---|---|---|
| 1 | Đọc schema collection thật qua tunnel | `dense` 1024 Cosine + sparse `bm25` (idf); payload index `project_id`/`doc_type`/`record_id` — **khớp** giả định trong `kb_service_adapter` |
| 2 | Đối chiếu mã dự án mockdb ↔ Qdrant (`noble-homes_k3n7_retail`) | 7/7 khớp (`VGC,VGG,VGGHL,VOP2,VOP3,VRI,VWC`) → đúng nguồn |
| 3 | `--dry-run` một dự án | text đọc tự nhiên, id tất định |
| 4 | Ghi thật `--project VRI` | 1/1 |
| 5 | `kb_search` qua `scripts/test_search_tools.py` | chunk `[VINHOMES ROYAL ISLAND › Tour 360]` về **hạng 1** |
| 6 | Chạy lại VRI, đếm point | 23 → 23, **idempotent** |
| 7 | `--all-tenants` | **30/30 point trên 4 tenant** |
| 8 | Spot-check tenant khác (`an-phu-land_z5r1_retail`) | `[AMBIENCE › Tour 360]` hạng 1 |
| 9 | `--delete --dry-run` | báo đúng, không đụng dữ liệu |
| 10 | `ruff check` + `ruff format --check` | sạch |

Số dự án có `link_360`: `an-phu-land_q8w2_retail` 7/14 · `an-phu-land_z5r1_retail`
10/14 · `noble-homes_k3n7_retail` 7/7 · `noble-homes_k3n7_wholesale` 6/6.

Còn lại: smoke `/chat` một lượt thật (hỏi tour 360 → Luna đọc được link).

## Việc còn lại sau này (không làm ở đây)

- Slice media: `kind:"image"` + field `link` optional + ảnh preview → card 360 bấm
  được trong app. Cần ảnh preview và một lần deploy app.
- Ingest tự động: hiện chạy tay. Khi phía ingest (Portal/RAG) nhận việc thì bỏ
  script này đi, đó là lý do nó nằm gọn trong 1 file.
