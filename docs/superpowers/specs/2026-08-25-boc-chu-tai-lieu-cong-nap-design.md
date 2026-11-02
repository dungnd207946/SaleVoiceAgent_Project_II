# Bóc chữ tài liệu của cổng nạp + PDF đi qua OCR markdown

**Ngày:** 2026-08-25 · **Trạng thái:** đã thi công, đang kiểm chứng trên bản sao local của `aina_prod`
**Phát hiện lúc:** chạy thử trọn pipeline ở local, không phải từ báo lỗi hay từ test

## 1. Vấn đề, đo được

Agent biết về chính sách bán hàng của `aina_prod` đúng **43 ký tự**:

```
body = 'Phạm vi: toàn dự án\nHiệu lực: từ 2026-06-25'     ← siêu dữ liệu adapter ghi
file = 'https://…s3…/CSBH.pdf'                            ← nội dung thật, chưa từng được đọc
```

| Đo trên `aina_prod` | |
|---|---|
Tài liệu | 40 |
`body` trung bình | **51 ký tự** |
`body` < 300 ký tự | 39 |
Trong đó **có tệp PDF** | **27** |
`body_auto` (chữ đã bóc) | **0** |

Không lỗi nào phát ra: job xanh, `kb_index_state` = `indexed`, badge trên portal xanh.
Đúng lớp hỏng-im-lặng.

## 2. Nguyên nhân: bốn cổng cùng khoá trên một giả định

| # | Chỗ | Điều kiện cũ |
|---|---|---|
1 | `ingest/chieu.py::_qua_viec_thumb` | `not co_body and co_tep` |
2 | `kb/directive/profiles.py::extract_profile` | `if body.strip(): return None` |
3 | `kb/jobs.py::handle_enrich` | `if not force and (body or body_auto)` |
4 | `kb/state/repo.py::cache_extracted_text` | `UPDATE … AND body = ''` |

Cộng một luật **đọc** thứ năm: `source/query.py` lấy `coalesce(nullif(body,''), body_auto)`
— tức `body` thắng, nên kể cả bóc được chữ thì nó vẫn bị bỏ qua.

Giả định chung, viết thẳng trong docstring: *"khách gửi kèm nội dung thì chữ của họ thắng"*.
Giả định ĐÚNG; chỉ là adapter của AINA đặt siêu dữ liệu vào `body`, nên hệ thống đọc 43 ký
tự đó thành "khách đã gửi nội dung".

## 3. Quyết định

| Câu hỏi | Chốt |
|---|---|
Nới cho loại tài liệu nào | **Chỉ bản ghi của cổng nạp** (`external_id IS NOT NULL`). Tài liệu nhập tay giữ luật cũ — `body` là ô người dùng sửa, bóc đè lên là xoá việc của họ |
Text đưa vào vector | **Nối** `body` rồi `body_auto`. Giữ được «Hiệu lực từ ngày…» mà khách hay hỏi, thêm nội dung thật |
27 tài liệu đang thiếu | **Lệnh CLI** `boc_lai_tai_lieu` — cổng nạp chỉ đặt việc khi bản ghi ĐỔI nên chúng không tự khỏi |
Siêu dữ liệu nằm ở chunk nào | Chỉ chunk đầu. Tiêu đề tài liệu đã ở `chunk_root` nên mọi chunk vẫn mang «CSBH — T6/2026» |
PDF có lớp chữ | **Đi qua `ocr_markdown`**, `pypdf` thành đường lùi — xem §5 |

## 4. Thay đổi

- `chieu.py::_qua_viec_thumb`: tài liệu **có tệp** thì luôn qua chặng bóc.
- `handle_enrich`: bản ghi ngoài chỉ xét `body_auto`; **mọi nhánh rời hàm đều nối sang việc
  nạp** qua `_noi_sang_nap()`.
- `cache_extracted_text`: nhánh bản ghi ngoài bỏ `AND body = ''`.
- `source/query.py`: `concat_ws(E'\n\n', nullif(body,''), nullif(body_auto,''))`.
- `contracts.py`: `LANE_ENRICH = 4`.
- `cli/boc_lai_tai_lieu.py`: quét tài liệu có tệp mà `body_auto` rỗng, xếp việc bóc.
  Thử khô mặc định.

⚠️ **Bẫy do chính thay đổi này tạo ra, đã đóng:** `handle_enrich` trước đây trả sớm khi
"đã có nội dung" mà **không** xếp việc index. Hôm nay vô hại vì nhánh đó gần như không
chạy tới; sau khi định tuyến mọi tài liệu có tệp qua chặng bóc, nó thành đường thường —
và tài liệu sẽ không bao giờ được index.

⚠️ **`kb_enrich` thiếu trần làn** là bug đo được: mỗi việc 165–362 giây (OCR từng trang),
trần mặc định 1 ⇒ 18 tài liệu mất gần một giờ. Nó chờ mạng y như caption.

## 5. PDF đi qua OCR markdown

`pypdf.extract_text()` trả **văn bản phẳng**: mất heading, bảng thành chữ so le, nên
`chunker._cat_bang` (cắt theo hàng, lặp hàng tiêu đề) **không bao giờ kích hoạt**. Với
chính sách bán hàng thì bảng chính là nội dung — 83/284 chunk CSBH chứa bảng.

Đối chiếu hai đường trên CÙNG một tài liệu **có lớp chữ** (`#164`, PDF 272 KB):

| | `pypdf` | OCR markdown |
|---|---|---|
Ký tự | 16.591 | **16.778** |
Con số đặc trưng (%, số tiền) | 26 | **26** |
Có ở `pypdf` mà mất ở OCR | — | **không có gì** |
Heading / bảng | 0 / 0 | có |

OCR **không làm mất điều khoản nào**. `pypdf` giữ lại làm đường lùi cho hai ca: không có
VLM (đường `kb_files`), và OCR trả rỗng.

Kèm `_bo_fence()`: qwen-vl-max bọc mỗi trang trong ```` ```markdown ```` — 4 dòng rác mỗi
tài liệu hai trang. Chunker không đọc fence nên đây là dọn rác, không phải vá cấu trúc.

## 6. Nạp qua API là nạp THẲNG

Không màn duyệt nào chen giữa, kể cả khi chữ do OCR đọc. Cờ đi qua ba chặng:
`chieu.py` đặt `tu_duyet=True` cho tài liệu → `handle_thumb` chuyển tiếp → `handle_enrich`
chỉ bật `body_cho_duyet` khi `not tu_duyet`. CLI bóc lại cũng truyền `tu_duyet=True`.
Đo trên bản sao local: **0/40 tài liệu bị treo chờ duyệt**.

⚠️ **CÒN NGỎ:** PDF người dùng tải tay trong portal có `tu_duyet=False`, mà từ nay mọi PDF
đều qua OCR ⇒ chúng **sẽ phải duyệt**, trong khi trước đây PDF có lớp chữ nạp thẳng. Ba
lựa chọn: giữ nguyên (đúng nguyên tắc «model sinh ⇒ người xem») · bỏ hẳn van duyệt · chỉ
duyệt khi PDF **không** có lớp chữ. Chưa chốt.

## 7. Kết quả đo trên bản sao local

| | |
|---|---|
Tài liệu đã bóc | 11/28 (đang chạy) |
Dài trung bình | ~15.100 ký tự (trước: 43) |
Có bảng markdown | **11/11** |
Chunk `doc_type=csbh` trong Qdrant | 284, trong đó **83 chứa bảng** |
Tài liệu treo chờ duyệt | 0 |
Job hỏng | 0 |

Mẫu một chunk có bảng, kèm tiền tố ngữ cảnh do `chunk_root` + `section_path` gắn:

```
SUNSHINE SKY CITY — 3. TIẾN ĐỘ THANH TOÁN BẰNG VỐN VAY NGÂN HÀNG

| ĐỢT | TỶ LỆ THANH TOÁN | GHI CHÚ | TIẾN ĐỘ THANH TOÁN |
|-----|------------------|--------|----------------------|
| Đợt 6 | 5% Giá trị HĐMB chưa gồm VAT | KH thanh toán bằng vốn tự có | Khi có Thông báo Bàn giao GCN… |
```

## 8. Ranh giới và nợ

- **`OCR_MAX_PAGES = 20`** cắt âm thầm tài liệu dài hơn: `da_cat=True` chỉ nằm trong thông
  điệp job, không lên giao diện.
- **Tài liệu nhập tay** không đổi luật bóc; van duyệt của chúng còn ngỏ (§6).
- **Chi phí OCR**: mỗi trang một lượt VLM. 28 tài liệu tối đa 560 lượt.
- **Docstring `profiles.py` nói sai code**: nó ghi "Docling bóc chữ cục bộ cho nhánh PDF có
  lớp chữ", thực tế là `pypdf`. Đã lỗi thời từ trước đợt này.

## 9. Cần thêm vào CLAUDE.md (người dùng tự dán)

| Ngày | Thay đổi |
|---|---|
| 2026-08-25 | **Tài liệu của cổng nạp: đọc TỆP kể cả khi `body` đã có chữ — và PDF đi qua OCR markdown thay vì `pypdf`.** Đo trên `aina_prod` khi chạy thử pipeline ở local: **27/40 tài liệu mang một PDF chưa từng được đọc**; `body` của chúng là 43 ký tự siêu dữ liệu adapter ghi («Phạm vi… Hiệu lực…»), và **BỐN cổng** cùng đọc `body` khác rỗng thành «khách đã gửi nội dung» (`chieu.py::_qua_viec_thumb` · `profiles.extract_profile` · `handle_enrich` · `cache_extracted_text`), cộng luật ĐỌC thứ năm `coalesce(nullif(body,''), body_auto)` làm siêu dữ liệu thắng cả khi có chữ bóc. Không lỗi nào phát ra: job xanh, `kb_index_state = indexed`, badge xanh. Nay với **bản ghi ngoài** (`external_id IS NOT NULL`) chỉ `body_auto` mới nói «đã bóc rồi», `cache_extracted_text` bỏ `AND body = ''`, và `source/query.py` **NỐI** hai cột (`concat_ws(E'\n\n', …)`) — giữ được «Hiệu lực từ ngày…» mà khách hay hỏi. Tài liệu **nhập tay giữ luật cũ**: `body` là ô người dùng sửa, bóc đè lên là xoá việc của họ. ⚠️ **Bẫy do chính thay đổi tạo ra, đã đóng**: `handle_enrich` trả sớm khi «đã có nội dung» mà KHÔNG xếp việc index — vô hại khi nhánh đó hiếm, nhưng sau khi mọi tài liệu có tệp đi qua chặng bóc thì nó thành đường thường và tài liệu sẽ không bao giờ lên Qdrant; nay mọi nhánh rời hàm đều qua `_noi_sang_nap()`. ⚠️ **`LANE_ENRICH = 4`**: bóc chữ là việc CHỜ MẠNG (OCR từng trang), mỗi việc 165–362 giây, trần mặc định 1 làm 18 tài liệu mất gần một giờ. **PDF nay đi qua `ocr_markdown`**, `pypdf` chỉ còn là đường lùi (không có VLM, hoặc OCR trả rỗng): `pypdf.extract_text()` cho văn bản PHẲNG nên mất heading và bảng thành chữ so le, và `chunker._cat_bang` (cắt theo hàng, lặp hàng tiêu đề) không bao giờ kích hoạt — với chính sách bán hàng thì **bảng chính là nội dung** (83/284 chunk CSBH chứa bảng). Đối chiếu hai đường trên cùng một PDF có lớp chữ: `pypdf` 16.591 ký tự / 26 con số vs OCR 16.778 ký tự / 26 con số, **không mất con số nào** — nên đây không phải đánh đổi. Kèm `_bo_fence()` bỏ ```` ```markdown ```` mà qwen-vl-max tự bọc quanh mỗi trang (4 dòng rác mỗi tài liệu 2 trang; chunker không đọc fence nên chỉ là dọn rác). **Nạp qua API vẫn là nạp THẲNG**: cờ `tu_duyet=True` đi qua ba chặng, đo được 0/40 tài liệu bị treo chờ duyệt. ⚠️ **CÒN NGỎ**: PDF tải tay trong portal có `tu_duyet=False` nên từ nay **phải duyệt** (trước đây PDF có lớp chữ nạp thẳng) — chưa chốt giữ nguyên / bỏ hẳn / chỉ duyệt khi không có lớp chữ. Nợ khác: `OCR_MAX_PAGES = 20` cắt âm thầm tài liệu dài hơn (`da_cat` chỉ nằm trong thông điệp job); docstring `profiles.py` vẫn ghi «Docling» trong khi code dùng `pypdf`. Mới: `python -m portal.cli.boc_lai_tai_lieu --tenant <id> [--that]` (thử khô mặc định) để bóc lại dữ liệu đã nạp trước mốc này — cổng nạp chỉ đặt việc khi bản ghi ĐỔI nên chúng không tự khỏi. Spec: `docs/superpowers/specs/2026-08-25-boc-chu-tai-lieu-cong-nap-design.md`. |
