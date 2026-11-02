# Hợp đồng: payload point Qdrant

**Ngày:** 2026-08-14 · **Hướng:** `odyssey-portal-backend` (ghi) ↔ `odyssey-agent` (đọc)
**Trạng thái:** đang thi công trên nhánh `kb-tab` của cả hai repo
**Bản đối chiếu:** `odyssey-agent/docs/contracts/payload-qdrant.md` — hai bản phải giống nhau

> **Vì sao cần hợp đồng viết ra:** không có test nào ở hai repo bắt được một lần lệch tên khoá. Phía
> agent, test **có** ghim tên khoá dùng trong **filter** và tên collection/vector — nhưng **KHÔNG**
> ghim tên khoá được **render**: chúng tự dựng dict hit rồi đưa vào hàm format, nên đổi tên khoá phía
> ingest vẫn xanh cả hai đầu và chỉ hỏng ở production, im lặng. Đúng lỗi đó đang sống: xem §5.

## 1. Hai collection

| Collection | Ai ghi | Ai đọc | Vector |
|---|---|---|---|
`<tenant_id>_documents` | Portal (dự án · tài liệu · CSBH · pháp lý) | agent `kb_search` | `dense` 1024 Cosine + sparse `bm25` (IDF) |
`<tenant_id>_media` | Portal (ảnh · video · tour 360) | agent `send_media` | `text` 1024 + `visual` 768, Cosine |

Tên collection tính trong code ở **một chỗ mỗi repo**, không đọc từ cột nào. Cách ly tenant là **TÊN
COLLECTION**, không phải filter — nên một bug không thể lộ chunk của tenant khác. **Không có khoá
`tenant_id` trong payload.**

## 2. ⚠ Hai tên DÀNH RIÊNG

`id` và `score` — tầng tìm kiếm của agent **tự chèn** hai khoá này vào mỗi kết quả (`id` = id point,
`score` = điểm sau khi fuse). Payload dùng hai tên đó sẽ bị **ghi đè im lặng**.

## 3. `<tenant>_documents` — 11 khoá

| Khoá | Kiểu | Ví dụ | Nghĩa | Ai dùng |
|---|---|---|---|---|
`project_id` | text | `"VRI"` | Mã dự án neo. **Tên đặt sai** (nó mang mã neo, không phải id) nhưng agent lọc theo nó và test phía agent **ghim tên này**. Đổi tên là việc của một đợt riêng. | **agent lọc** (`MatchAny`, hợp với `"__ALL__"`) |
`project_name` | text | `"Vinhomes Royal Island"` | Tên dự án hiện tại. | **agent render** tiêu đề khối |
`record_id` | int | `1042` | Id hàng nguồn trong Postgres. | Portal (vị từ xoá) |
`doc_type` | text | `"csbh"` | `tong_quan` (dự án, gồm cả khối phân khu) · `csbh` · `phap_ly` · `huong_dan` · `khac`. Nằm trong id point. **Cũng là thứ suy ra bảng nguồn** — xem §6. | Portal |
`text` | text | `"Vinhomes Royal Island — Ưu đãi…\n\n### Ưu đãi…\n\| Đợt \| Tỷ lệ \|…"` | Nội dung chunk, **markdown nguyên vẹn** (kể cả `![alt](url)`). ⚠️ KHÔNG bằng chuỗi đã nhúng: chuỗi nhúng thay `![alt](url)` bằng `alt` vì URL không mang nghĩa cho phép tìm ngữ nghĩa. Agent đọc `text` để dựng `items`, nên ảnh phải còn nguyên ở đây. Đổi 2026-08-28. **Rỗng ⇒ agent loại hit.** | **agent render** |
`content_hash` | text | `"9f2a1c…"` | Băm nội dung **THUẦN**, **không** gồm nhãn — xem §4. | Portal (thoát sớm) |
`updated_at` | text ISO | `"2026-08-14T09:12:00Z"` | Mốc cập nhật hàng nguồn. | **agent render** dòng `(cập nhật: …)` |
`status` | text | `"published"` | Trạng thái **HIỆU LỰC** — xem §4. | **agent lọc** |
`file_public_url` | text | `"https://…/api/v1/public/files/tenants/anphu/docs/csbh-q3.pdf"` | URL **bền** của tệp nguồn (qua route Portal, **không** phải URL có hạn). Rỗng = chunk không có tệp. | **agent gửi kèm** |
`file_name` | text | `"CSBH quý 3 2026.pdf"` | Tên gốc để hiện cho khách. **Không suy được từ đâu khác** — khoá S3 đã qua bước chuẩn hoá nên mất tên tiếng Việt, và tiêu đề tài liệu có thể khác tên tệp thật. | agent |
`thumb_url` | text | `"https://…/public/files/…/csbh-q3-p1.webp"` | Ảnh preview: trang 1 của PDF, hoặc chính ảnh CSBH đã thu nhỏ. Không có nó thì tệp gửi kèm chỉ là link trần. | agent |

## 4. Hai khoá có bẫy — đọc trước khi dùng

### `status` — giá trị HIỆU LỰC, không phải bản copy của cột

Lấy từ Postgres, nhưng từ **HAI** cột, không phải một:

```
media.status      (trạng thái của chính bản ghi)
projects.status   (trạng thái dự án cha)     →  status = "published" CHỈ KHI cả hai published
                                                          ngược lại "draft" / "archived"
```

Câu SQL đọc **đã JOIN dự án cha sẵn** (đó là cách nó lấy tên dự án) nên không thêm truy vấn nào.

**Gộp lúc GHI, không ghi cả hai rồi để agent tự `AND`:** một point của phân khu hay tài liệu **không
biết gì** về hàng dự án. Ghi cả hai là **2 khoá**; gộp lúc ghi giữ được **1**, và luật nghiệp vụ ở
lại Portal.

**Hệ quả: giá trị trong payload có thể LỆCH với cột nguồn.**

| `media.status` | `projects.status` (cha) | `status` payload |
|---|---|---|
`published` | `published` | `published` |
`published` | `draft` | **`draft`** ← lệch, **cố ý** |
`draft` | `published` | `draft` |
bất kỳ | `archived` | `archived` |

Hàng thứ hai là chỗ người debug vấp: Postgres nói ảnh `published`, payload nói `draft`, tưởng ingest
sai. Nó **đúng** — dự án cha đang nháp.

**Mệnh đề lọc phải là `status == 'published'`.** Không được viết `status != 'draft'`: ba giá trị, dùng
`!=` thì `archived` **lọt ra khách**. Và `==` là thứ giữ tính **fail-closed** — point thiếu khoá
`status` không khớp ⇒ bị ẩn, đúng ý muốn.

### `content_hash` — băm nội dung THUẦN, không gồm nhãn

Trước 2026-08-14 tiền tố `"<tên dự án> — <mục>"` được prepend **trước** khi băm, nên đổi tên dự án
làm dấu tay của **mọi** phân khu và **mọi** tài liệu con đổi theo ⇒ nhúng lại cả cây (một dự án có
thể 116 record) trong khi nội dung không đổi một chữ.

Nay băm **chỉ** nội dung thuần. Đổi tên dự án ⇒ dấu tay không đổi ⇒ chỉ cập nhật payload
(`project_name` + phần tiền tố trong `text`), **không nhúng lại**.

**Đánh đổi:** vector không được cập nhật theo tên mới cho tới lần nội dung thật đổi, nên tra cứu
**BM25** theo tên dự án mới không khớp ngay. Gần như không quan trọng: đường tìm theo tên dự án đi
qua `find_project` (tên → mã) rồi **lọc theo mã**, không qua BM25.

## 5. `<tenant>_media` — 10 khoá

| Khoá | Kiểu | Ví dụ | Nghĩa | Ai dùng |
|---|---|---|---|---|
`project_id` | text | `"VRI"` | mã dự án neo | **agent lọc** |
`project_name` | text | `"Vinhomes Royal Island"` | | agent |
`record_id` | int | `964` | Id hàng `media`. Ở đây chỉ **một** bảng nguồn nên `record_id` đủ định danh. | Portal (vị từ xoá) |
`content_type` | text | `"image"` · `"video"` · `"tour_360"` | `tour_360` **là giá trị mới** (2026-08-14). | **agent lọc** (`MatchValue`) |
`category` | text | `"tong_quan"` | **7** danh mục: `tong_quan` `ngoai_that` `noi_that` `tien_ich` `mat_bang` `vi_tri` `tien_do`. **`csbh` đã bị bỏ** — nó là loại **tài liệu**, không phải danh mục ảnh. | **agent lọc** (`MatchValue`) |
`caption` | text | `"Toàn cảnh phân khu ven sông lúc hoàng hôn"` | Mô tả. **Rỗng** với `vi_tri` và `mat_bang` (không gọi VLM cho bản đồ và bản vẽ). Tour 360: `"Tour tham quan thực tế ảo 360 độ — <tên dự án>"`. | agent render nhãn |
`media_url` | text | xem §5.1 | URL trình duyệt mở được — **không bao giờ là khoá S3**. **Rỗng ⇒ agent loại hit.** | **agent render** |
`thumb_url` | text | `"https://…/thumb.webp"` | Ảnh thu nhỏ | agent |
`content_hash` | text | `"3b7e…"` | | Portal (thoát sớm) |
`status` | text | `"published"` | hiệu lực, như §4 | **agent lọc** |

### 5.1 `media_url`: khách tải ảnh lên, hay dán link

Hai tầng lưu **hai giá trị khác nhau** — chỗ này dễ hiểu nhầm nhất:

| Khách làm gì | `media.media_url` (Postgres) | `media_url` (payload) |
|---|---|---|
**Tải ảnh lên** (kéo-thả) | **KHOÁ S3** `"tenants/anphu/media/toan-canh.webp"` | `"https://…/api/v1/public/files/tenants/anphu/media/toan-canh.webp"` |
Dán link YouTube | `"https://www.youtube.com/embed/fSVkxmsjAEw?si=…"` | **nguyên văn** |
Dán link tour 360 | `"https://kuula.co/share/collection/7l8Rt?…"` | **nguyên văn** |
Dán link ảnh ngoài | `"https://…cloudfront.net/x.jpg"` | **nguyên văn** |

Hàm sinh URL công khai **cho đi nguyên văn** mọi giá trị đã bắt đầu bằng `http://`/`https://`, và chỉ
nối tiền tố cho phần còn lại (tức khoá). Nên payload **luôn** giữ URL mở được.

⚠ Hàm đó **trả rỗng** khi chưa cấu hình miền công khai — cố ý: *thà agent coi là "không có ảnh" còn
hơn nhận một link không mở được*. Nên thiếu cấu hình miền ở một môi trường thì **mọi ảnh tải lên im
lặng biến mất** khỏi kết quả.

## 6. Khoá đã BỎ (2026-08-14) — và vì sao bỏ được

| Bỏ | Có ở | Lý do |
|---|---|---|
`entity` | cả hai | Nó tồn tại để vị từ xoá phân biệt `projects#5` với `zones#5`. Nhưng **`doc_type` đã làm được**: ba tập giá trị **rời nhau**. Điều kiện: đường xoá suy bảng nguồn từ `doc_type`, **và** một test khẳng định tính rời nhau — mất nó là **xoá nhầm point của record khác**, im lặng. |
`anchor_code` | cả hai | Trùng **đúng giá trị** `project_id`. |
`content_type` | **chỉ documents** | Ở đó nó luôn là `"text"` — hằng số, không ai đọc. **GIỮ ở media**: khoá lọc thật, có test ghim. |
`section` | documents | Trùng **phần tử cuối** của `section_path`. **ĐÃ BỎ HẲN 2026-08-19** (pha 3 hoàn tất). |
`section_path` | documents | Trùng nội dung `text`: `_tien_to()` gắn `"<project_name> — <mục>"` vào đầu **mọi** chunk trước khi nhúng. Đo trên 136 point thật ở 4 collection: **136/136** khớp. Agent thoái hoá êm — `_section()` trả `""`, tiêu đề khối rút từ `[Dự án › Mục]` xuống `[Dự án]`, nhãn mục vẫn nằm trong `text` ngay bên dưới. |
`page` | documents | Hardcode `0` từ ngày đầu, chưa từng có giá trị khác. Agent bỏ qua khi `<= 0`. |
`chunk_index` | documents | Không ai đọc; đã nằm trong id point `uuid5(doc_type:record_id:idx)`. |
`status` thô + `anchor_status` | cả hai | Chỉ để soi — **Postgres là nguồn sự thật để soi**. Giữ duy nhất `status` hiệu lực (§4). |
`file_url` (khoá S3) | documents | Agent **không bao giờ** cần khoá, nó cần URL mở được. Khoá chỉ Portal dùng, và Portal đọc từ Postgres. |

**Bỏ khoá S3 KHÔNG ảnh hưởng việc trả ảnh/tệp:**

| Công cụ | Collection | Trả gì | Đọc khoá nào |
|---|---|---|---|
`send_media` | media | ảnh · video · tour 360 | `media_url` + `thumb_url` — **đã là URL công khai từ trước tới giờ** |
`kb_search` | documents | chữ + **tệp gửi kèm** (mới) | `file_public_url` · `file_name` · `thumb_url` · `page` |

## 7. Id point

`uuid5(NAMESPACE_URL, f"{doc_type}:{record_id}:{idx}")` — tất định, nên upsert **idempotent**: chạy
lại ghi đè đúng point cũ, không nhân bản. Media dùng `doc_type=""` và `idx=0`.

**Hệ quả:** đổi `doc_type` của một tài liệu (đổi tiền tố tiêu đề) sinh point **MỚI** và bỏ lại point
cũ mồ côi ⇒ route sửa tài liệu phải xoá point loại cũ.

## 8. Thứ tự deploy khi payload đổi

Ba pha, không đảo được — xem §7 của
[`specs/2026-08-14-tu-dong-nap-kien-thuc-design.md`](../superpowers/specs/2026-08-14-tu-dong-nap-kien-thuc-design.md).
Tóm: **Portal ghi khoá mới + nạp lại toàn bộ → agent thêm mệnh đề lọc → Portal mở nạp hàng nháp.**
Đảo hai bước đầu ⇒ RAG câm. Đảo hai bước sau ⇒ nội dung nháp tới khách.

**Cổng chặn:** đếm point **thiếu khoá `status`** trên mọi collection phải bằng **0** trước khi deploy
pha 2. Mệnh đề lọc fail-closed nên point thiếu khoá đó bị ẩn.

## 9. Phân khu nằm trong doc `tong_quan` (2026-08-19)

`doc_type = "phan_khu"` **đã bỏ**. Phân khu của một dự án gộp thành MỘT khối trong doc
`tong_quan` của dự án đó, và khối ấy luôn là **point riêng**:

```
Vinhomes Global Gate Hạ Long — Phân khu

## Cơ cấu sản phẩm
### Phân khu
- **Vịnh Bình Minh 1**
- **Vịnh Bình Minh 2**
```

Point khối phân khu mang `doc_type = "tong_quan"` và **cùng `record_id`** với point quick-fact
của dự án (id hàng `projects`) — chúng khác nhau ở `idx` trong id point.

Ranh giới point đến từ **độ sâu đường dẫn tiêu đề** (2 cấp), không từ cỡ chunk — nên nó
không đổi theo `min_chars`. Đo: 0/1/6/40 phân khu × `min_chars` ∈ {0, 300, 600}, 12/12 tách sạch.

⚠ **`status` của point là của DỰ ÁN.** Phân khu `draft` vẫn vào text; không mệnh đề lọc nào
tách được nó ra. Đánh đổi có chủ ý — xem
[`specs/2026-08-19-gop-phan-khu-vao-tong-quan-design.md`](../superpowers/specs/2026-08-19-gop-phan-khu-vao-tong-quan-design.md) §7.

## 10. doc_type `kb_file` — kho «Tài liệu tra cứu» (màn /kb, spec 2026-08-20)

Point nằm trong `<tenant>_documents`, nguồn là bảng `tenant_data.kb_files`
(KHÔNG phải `documents` — kho thứ tư ghi vào collection này, sổ của nó là chính
`kb_files.state`, không có dòng `kb_index_state` nào).

- `project_id` = `"__ALL__"` — nội dung cấp workspace; kb_search hợp lệ nhờ
  sentinel union sẵn có phía agent (`data/qdrant_search.py::build_scope_filter`).
- `project_name` = **tên tệp** (wart có chủ ý: không có dự án nào để gọi tên;
  chỗ render của agent dùng khoá này làm nhãn ngữ cảnh, tên tệp là nhãn đúng
  nhất hiện có).
- `record_id` = `kb_files.id` · `status` luôn `"published"` (kho này không có
  khái niệm nháp — BR06 gắn vào `kb_files.state`, chỉ hàng `san_sang` có point).
- `file_public_url`/`file_name` mang link + tên tệp để agent gửi được tệp gốc.
- Vị từ xoá: `(doc_type='kb_file', record_id)` — tính rời nhau của doc_type do
  `tests/modules/kb/test_doc_type_roi_nhau.py` canh.
