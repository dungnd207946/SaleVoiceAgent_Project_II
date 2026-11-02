# M6 — Tài liệu (KB) (thiết kế)

> **Ngày:** 2026-07-31 · **Trạng thái:** chờ duyệt · **Repo:** `odyssey-portal-backend` + `odyssey-portal-frontend`
> **Chặn bởi:** M3 (`core/storage.py` + khuôn job) · **Song song được với M5** · **Màn:** `kb` — "Tài liệu"
> **Nguồn nghiệp vụ:** **KB_01 v1.0 (2026-07-29, thebc)** — 12 business rule, 6 mã lỗi, bảng thành phần màn hình. Đã đọc và hợp nhất.
> **Nguồn kỹ thuật:** spec tổng §3 (M6) · `control-plane-design.ref.md` §5.6 quyết định #13 · work-packages Gói D

---

## 0. Spec này làm gì

Workspace tự nạp tài liệu (PDF/DOCX/XLSX) để agent trả lời khách bằng chính kiến thức của mình —
chính sách bán hàng, quy trình, phí dịch vụ, pháp lý dự án, FAQ.

KB_01 gọi đây là *"chức năng quyết định khách tự chủ được hay không: không có nó thì mỗi khách mới
lại cần dev nạp kiến thức hộ"* — tức là điều kiện cần để sản phẩm là **SaaS** chứ không phải dịch vụ
triển khai.

**Trong phạm vi:** upload nhiều file · parse → chunk → embed → index · một kho riêng mỗi workspace ·
danh sách + 3 trạng thái + xoá · tab *Agent đã trích dẫn* · tab *Không tìm được tài liệu* ·
cổng test cross-tenant.

**Ngoài phạm vi:** crawl web · duyệt tài liệu (workflow phê duyệt) · độ phủ theo chủ đề.

---

## 1. KB là **bậc 1**, không phải bậc 3

HT01 §II.2.1 chia ba bậc độ trễ hiệu lực. Tài liệu nằm ở **bậc 1 — tức thì**:

| | Config (M3·M5) | **Tài liệu (M6)** |
|---|---|---|
| Bậc | 3 — phải xuất bản | **1 — tức thì** |
| Agent thấy khi nào | Sau Áp dụng, ≤20s, chỉ phiên MỚI | **Ngay lượt hỏi kế tiếp**, kể cả giữa cuộc gọi |
| Vì sao | Persona phải đóng gói, đánh số, quay lui được | Agent truy xuất kho **mỗi lần** khách hỏi, không đệm |
| UI nói | Đang áp dụng → Sẵn sàng | **Đã lưu** |

**Hệ quả — và đây là chỗ dễ làm sai nhất:** màn Tài liệu **không có nút Xuất bản**, không version,
không nối vào `config_versions`. Index xong là xong.

Thêm nút Xuất bản ở đây "cho đồng bộ với màn Agent" là làm hệ chậm đi mà không đổi lấy gì — và dạy
người dùng một mô hình sai về sản phẩm của chính họ.

Cái vẫn phải nói rõ: **upload xong ≠ agent biết ngay**. Còn một khoảng parse+embed. Đó là lý do
trạng thái từng file (§4) là bắt buộc, không phải trang trí.

---

## 2. Cách ly: một kho mỗi workspace

```
kb_<tenant_id>     ← collection Qdrant riêng
```

Tầng RAG hiện **không có một chữ `tenant` nào**: tên collection là một biến môi trường toàn hệ
(`QDRANT_COLLECTION`), filter theo `project_id`. Một tenant thì vô hại; hai tenant thì `kb_search`
của B trả về chunk của A.

| | Luật |
|---|---|
| **BR01** | Tên kho sinh từ `tenant_id` theo quy tắc cố định **trong code**. **Không màn hình nào cho nhập hoặc chọn tên kho.** Không API nào nhận tên kho từ client |
| **BR01** | Tạo **lúc tạo workspace**, trước khi có tài liệu nào. Kho rỗng là hợp lệ |
| **BR02** | Agent đọc đúng kho của workspace nó phục vụ. Định danh từ cấu hình **lúc khởi động container** — không từ tham số câu hỏi, không từ client |
| **BR05** | Đóng workspace ⇒ xoá kho. Nghĩa vụ Nghị định 13/2023, không phải việc dọn dẹp để sau |
| **BR11** | Manifest của workspace khai trường trỏ tới kho |

**BR03 — cách ly do cấu trúc, không do lọc.** Dùng chung một kho rồi filter theo `tenant_id` rẻ hơn
ở quy mô lớn, nhưng nó đặt cách ly vào tay *người viết query nhớ thêm điều kiện* — đúng mô hình đã
bị bác cho Postgres khi chọn RLS. Một chỗ quên là rò dữ liệu giữa hai khách hàng, và lỗi đó **im
lặng**: query vẫn trả kết quả, chỉ là kết quả của người khác.

> **Kho thứ ba, không có RLS.** Postgres có RLS cưỡng chế; Qdrant thì không — cách ly ở đây là
> **cấu trúc** (kho riêng), không phải cơ chế của kho. Nên nó chỉ đúng khi tên kho suy ra từ
> `TenantContext` và **không có đường nào** để tham số bên ngoài đổi nó. Một hàm
> `ten_collection(tenant_id)` duy nhất, **không nhận tham số nào khác** — cổng test 2.

**Chỗ nối duy nhất với M3 (BR11):** `manifest.toml` trong bundle mang trường `kb.collection`, được
**render từ `tenant_id`**, không đi qua `payload`. Nếu workspace sửa được tên kho của chính mình thì
mọi thứ ở §2 vô nghĩa. M6 dùng lại đúng hàm `ten_collection()` mà M3 gọi lúc render.

**Hai việc kéo theo:**
- Tenant đã tồn tại (seed dev) chưa có kho → bước backfill **idempotent** trong `make dev-seed`.
  Không phải migration: Qdrant không nằm trong Alembic.
- KB_01 §I.2 yêu cầu *"tạo kho không được làm chậm bước tạo workspace"*, còn §5.6 nói *"cùng
  transaction tạo tenant"*. Không mâu thuẫn về ý nhưng **không thể cùng transaction thật** — Qdrant
  ở ngoài Postgres. Cách làm: tạo kho **đồng bộ trong cùng request** (tạo collection rỗng là thao
  tác mili-giây), và nếu nó chưa xong khi người dùng vào màn Tài liệu thì **ER_06**. Không đẩy vào
  job nền: một workspace có bản ghi mà không có kho là workspace hỏng khó chẩn đoán.

---

## 3. Luồng nạp tài liệu

Dùng lại đúng khuôn job của M3 — cùng bảng `jobs`, `kind='rag_build'` (`kind` là `text` tự do,
không cần migration).

```
POST /kb/files    (nhiều file một lần, kéo thả)
     FE validate:  định dạng ngoài PDF/DOCX/XLSX → ER_01 · vượt dung lượng → ER_02
     BE: lưu S3 tenants/<id>/kb/<sha>/<tên gốc>      (core/storage.py của M3)
         INSERT kb_files(state='dang_xu_ly')
         INSERT jobs(kind='rag_build', payload={file_id})
   worker:
     1. tải file từ S3
     2. bóc chữ    PDF/DOCX/XLSX → text     ← MỚI.  không có lớp chữ → ER_03
     3. cắt đoạn                             ← MỚI
     4. sinh vector                          ← NHẤC từ santa-agent-cms
     5. ghi vào kho CỦA WORKSPACE ĐÓ         ← NHẤC từ santa-agent-cms
     6. UPDATE kb_files(state='san_sang', chunk_count=N) + ghi nhật ký   (BR09)
        lỗi khác → state='loi', ER_04
   FE: cập nhật trạng thái không cần reload (poll)
```

**Nhấc, đừng viết lại.** Đường build index Qdrant đã có ở `santa-agent-cms`
(`services/rag/nbx_rag_build.py`, `qdrant_core.py`). Phần **thật sự mới** là parser + chunker cho
file người dùng upload — cái đó `santa-agent-cms` không có, vì nguồn của nó là dữ liệu có cấu trúc.

**BR07 — xoá là xoá ngay.** Gỡ khỏi kho **trong cùng thao tác**, xoá S3, xoá hàng, ghi nhật ký.
Không thùng rác, không hoàn tác. Tài liệu sai đang được agent dùng để trả lời khách là sự cố đang
diễn ra; thêm bước "khôi phục" vào giữa là kéo dài nó. Popup xác nhận nói rõ *agent thôi dùng tài
liệu này từ lần trả lời kế tiếp*.

**Không hỗ trợ ở MVP:** ảnh scan không có lớp chữ (→ ER_03) · file đặt mật khẩu.

---

## 4. Ba trạng thái (không phải bốn)

| `state` | Chip | Agent dùng? |
|---|---|---|
| `dang_xu_ly` | Đang xử lý | ❌ |
| `san_sang` | Sẵn sàng | ✅ |
| `loi` | Lỗi + **lý do và cách sửa** | ❌ |

**BR06 — chưa xử lý xong thì chưa dùng.** Tài liệu `dang_xu_ly` hoặc `loi` **không xuất hiện trong
kết quả truy xuất**. Chỉ `san_sang` mới được agent dùng. Đây là bất biến của tầng truy vấn, không
phải quy ước UI — cổng test 5.

**Lỗi phải nói lý do và cách sửa**, không chỉ chữ "Lỗi". ER_03 là ví dụ mẫu: *"File này không có
lớp chữ — có thể là ảnh scan. Hãy nạp bản có chữ hoặc chuyển ảnh thành văn bản trước."* Đây là chỗ
workspace tự sửa được hoặc phải gọi hỗ trợ — chênh nhau ở đúng một câu chữ.

**BR04 — kho rỗng là hợp lệ.** Empty state hiện **hướng dẫn nạp tài liệu đầu tiên**, không hiện như
lỗi. Và agent với kho rỗng trả lời *"chưa có tài liệu về việc này"* rồi chuyển người thật — **không
báo lỗi, không suy đoán**.

**BR08 — lỗi tìm kiếm không thành câu trả lời bịa.** Hệ thống tìm kiếm lỗi ⇒ agent rơi về phương án
dự phòng; hết phương án thì chuyển người thật kèm lời giải thích. *Hành vi này ở phía agent —
**Gói G**; ghi vào hợp đồng bàn giao.*

---

## 5. Bảng `tenant_data.kb_files`

Nằm ở `tenant_data` (**RLS + FORCE**), không phải `control` — đây là dữ liệu của khách.

| Cột | Ghi chú |
|---|---|
| `id` · `tenant_id` | RLS theo `tenant_id` |
| `ten_file` · `s3_key` · `kich_thuoc` · `loai` | `loai ∈ pdf·docx·xlsx` — `CHECK`, không phải quy ước |
| `state` | `dang_xu_ly · san_sang · loi` — `CHECK` |
| `chunk_count` · `loi_message` | `loi_message` hiện nguyên văn lên UI |
| `uploaded_at` · `uploaded_by` | Danh sách hiện: tên · định dạng · dung lượng · **người nạp** · thời điểm · trạng thái |

**Fail loud** (quy ước §6.2): lỗi parse nổi lên UI thành lỗi, không thành danh sách rỗng.

---

## 6. Hai tab đo hiệu quả

| Tab | Nội dung | Ai ghi dữ liệu |
|---|---|---|
| **Agent đã trích dẫn** | Tài liệu nào đang thực sự trả lời khách, kèm **số lượt** — cho biết tài liệu nào vô dụng | **Gói G** |
| **Không tìm được tài liệu** | Câu hỏi agent không trả lời được vì thiếu tài liệu — liên kết sang màn *Cần bổ sung* (M7) | **Gói G** |

**Ranh giới rõ:** M6 dựng **bảng + API đọc + UI**; **Gói G ghi dữ liệu vào**, vì `kb_search` chạy
trong tiến trình agent (quyết định #6 — in-process, một chặng, để bảo vệ TTFA của voice). Portal
không nằm trên đường truy vấn nên không tự biết agent đã trích dẫn gì.

Hai tab này **rỗng cho tới khi Gói G xong** — đó là trạng thái đúng, không phải bug. Ghi vào hợp
đồng bàn giao để người nhận Gói G biết mình đang lấp chỗ nào.

---

## 7. API

| Method | Đường dẫn | Action |
|---|---|---|
| GET | `/api/v1/kb/files` | `catalog.read` |
| POST | `/api/v1/kb/files` | `catalog.write` |
| GET | `/api/v1/kb/files/{id}` | `catalog.read` |
| DELETE | `/api/v1/kb/files/{id}` | `catalog.delete` |
| GET | `/api/v1/kb/citations` | `catalog.read` |
| GET | `/api/v1/kb/gaps` | `catalog.read` |

Sáu endpoint dùng **4 action đã có** trong `contracts/actions.json` từ M2a. Không thêm action mới,
cổng parity giữ nguyên xanh.

---

## 8. Sáu mã lỗi (KB_01 §II.4)

| Mã | Khi nào | Kiểu |
|---|---|---|
| ER_01 | Định dạng ngoài PDF/DOCX/XLSX | Toast — chặn ở FE |
| ER_02 | Vượt dung lượng (ngưỡng: **chưa chốt**, BR12) | Toast |
| ER_03 | Không bóc được chữ — ảnh scan | Popup + `state='loi'` kèm lý do này |
| ER_04 | Lỗi xử lý khác | Trạng thái trên dòng + [Nạp lại] |
| ER_05 | Lỗi chung | Toast |
| ER_06 | Kho chưa sẵn sàng — workspace còn đang cấp | Popup |

---

## 9. Cấu trúc code

```
BE  src/portal/modules/kb/
      router.py · service.py · repo.py · contracts.py · fake.py
      jobs.py        register("rag_build", handle_rag_build)
      parse.py       PDF/DOCX/XLSX -> text        ← HÀM THUẦN (bytes vào, text ra)
      chunk.py       text -> list[Chunk]          ← HÀM THUẦN
      qdrant.py      client + ten_collection(tenant_id)
    migrations/versions/0300_kb_files.py

FE  src/features/kb/{nav.ts, api.ts, components/}
    src/routes/_app/kb.tsx      ← route rỗng đã có từ M2a-FE
```

`parse.py` và `chunk.py` là **hàm thuần** — cùng lý do như `bundle.render()` của M3: đây là phần
nhiều biến thể và dễ sai nhất, và test nó không nên cần Qdrant, S3 hay worker. Một thư mục fixture
vài file thật là đủ.

---

## 10. Cổng test

| # | Cổng | Đỏ khi nào |
|---|---|---|
| 1 | **Cross-tenant RAG (BR10)** — truy vấn từ workspace A **không bao giờ** trả về đoạn của B | Cách ly Qdrant thủng |
| 2 | `ten_collection()` chỉ nhận `tenant_id`, không nguồn nào khác; không API nào nhận tên kho | Ai đó mở đường cấu hình |
| 3 | Xoá file ⇒ chunk biến khỏi kho **ngay trong cùng request** | Xoá lười, agent còn trích dẫn file đã xoá |
| 4 | RLS trên `kb_files` — A không `SELECT` được hàng của B | Quên `FORCE ROW LEVEL SECURITY` |
| 5 | **BR06** — file `dang_xu_ly`/`loi` không xuất hiện trong kết quả truy xuất | Agent dùng tài liệu chưa index xong |
| 6 | Parse hỏng ⇒ `state='loi'` + `loi_message` đọc được, **không** stacktrace lên UI | Fail loud sai cách |
| 7 | Tenant mới ⇒ kho tồn tại và rỗng, trước khi có file nào | Bước tạo kho bị bỏ quên |

**BR10 nói rõ cổng 1 không được bỏ qua** — ngang hàng với test cách ly dữ liệu quan hệ. Bốn cổng
cách ly của M1 chỉ phủ Postgres; Qdrant là kho thứ ba và nó có lỗ riêng.

---

## 11. Còn treo

- **Ngưỡng dung lượng mỗi file và tổng mỗi workspace (BR12)** — đầu vào bảng giá, không phải quyết
  định kỹ thuật. **Chặn ER_02.**
- **Chi phí một kho ở trạng thái rỗng** — đầu vào cho giá gói nhỏ nhất. Đo trước khi chốt giá.
- **Hành vi khi workspace bị tạm ngưng:** giữ kho hay xoá.
- **Mô hình embedding** — **phải trùng `santa-agent-cms`**. Đổi mô hình là reindex toàn bộ và chunk
  cũ không so sánh được với chunk mới.
- **Wireframe màn Tài liệu** — KB_01 §3 mới có bảng thành phần, chưa có hình.
