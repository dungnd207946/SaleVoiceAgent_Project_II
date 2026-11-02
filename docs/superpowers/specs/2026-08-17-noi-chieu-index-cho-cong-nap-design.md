# Nối chiều index Qdrant cho cổng nạp dữ liệu ngoài

Nhánh `feat/api-ingest`. Thiết kế gốc của cổng nạp:
[`2026-08-14-cong-nap-du-lieu-ngoai-design.md`](2026-08-14-cong-nap-du-lieu-ngoai-design.md).
Pipeline Qdrant: [`2026-08-10-ingest-qdrant-design.md`](2026-08-10-ingest-qdrant-design.md).

## 1. Vấn đề

Portal có hai đường ghi dữ liệu nghiệp vụ, và chỉ một đường nối đủ hai nửa.

**Đường giao diện** (`modules/realestate/router.py`): route Lưu ghi hàng vào Postgres
**và** đặt việc nạp trong cùng giao dịch (D01). Worker mang nội dung đi bóc chữ, chia
chunk, nhúng, rồi upsert point lên Qdrant.

**Đường cổng nạp** (`modules/ingest/chieu.py`): chiếu bản ghi vào 5 bảng KB, nhưng
**không đặt việc nạp**. Nó chỉ đặt `kb_delete` khi bản ghi rời `published`
(`_xep_purge`). Tức nó biết dọn point, không biết ghi point.

Không có DB trigger nào bù. Lưới an toàn lẽ ra bắt được (`kb/jobs.py::handle_reconcile`)
hiện là `raise NotImplementedError`.

### 1.1 Hậu quả

Agent đọc hai nguồn bằng hai loại tool khác nhau:

| Tool | Nguồn | Dữ liệu nạp qua cổng API |
|---|---|---|
| `discover_projects` · `search_units` · `recommend_units` · `get_project_overview` · `get_document` | Postgres `tenant_data` trực tiếp | thấy ngay |
| `kb_search` | Qdrant `<tenant>_documents` | **không thấy** |
| `send_media` | Qdrant `<tenant>_media` | **không thấy** |

Một tenant đấu nối bằng cổng API có agent trả lời đúng giá, diện tích, tình trạng bán,
nhưng trả lời như thể tài liệu và ảnh của dự án không tồn tại.

### 1.2 Đây là thiếu thi công, không phải quyết định còn mở

Spec cổng nạp §6.4 đã chốt hành vi:

> Projector ghi xong `projects`/`zones`/`documents`/`media` ⇒ đánh dấu `kb_index_state`
> bẩn ⇒ job có sẵn (`modules/kb/jobs.py`) đẩy lên S3 + Qdrant.

Câu "đánh dấu `kb_index_state` bẩn" là cách nói lỏng: `state` của bảng đó chỉ có
`queued|indexing|indexed|error|deleted` (migration `0501`), không có trạng thái "bẩn".
Cơ chế thật phải là đặt việc vào `control.jobs` — đúng thứ đường giao diện đang làm.

### 1.3 Điều làm nó nhẹ hơn: chỉ báo lệch CÓ hoạt động

`GET /projects/kb-status` (`realestate/repo.py::_PROJECT_STATUS_SQL`) so `updated_at`
của hàng với `indexed_at` trong sổ, và **hàng chưa có dòng sổ nào cũng tính là lệch**.
Nên dữ liệu nạp qua API **có** làm dự án hiện "chưa đồng bộ" trên màn danh sách, kèm
nút Đồng bộ.

Vấn đề thật vì thế là: cơ chế hiện tại **đòi một người mở portal rồi bấm**. Tenant
dùng cổng API là tenant có dữ liệu chảy tự động từ CRM của họ, không ai ngồi trong
portal. Không ai bấm.

## 2. Phạm vi

**Trong phạm vi**

1. Cổng nạp đặt việc nạp cho bản ghi vừa chiếu.
2. Sửa lỗi cùng họ: hàng `media` `tour_360` sinh từ `link_360` chưa từng được đặt việc
   (mục 5).
3. Mock bên thứ ba + script e2e xác minh trọn chuỗi tới Qdrant (mục 6).

**Ngoài phạm vi**

- **`handle_reconcile`.** Nó là lưới cho MỌI đường ghi (worker bị kill, sửa DB bằng SQL
  tay, PR quên enqueue, job hết retry), không riêng cổng API — xứng một spec riêng, và
  còn một quyết định chưa chốt: bù bằng cách đặt lại việc nạp (an toàn) hay gọi Qdrant
  thẳng (nhanh). Gộp vào đây làm nhánh khó review.
- **Thống nhất hành vi `kb_delete` giữa hai đường.** Đường giao diện dùng
  `dat_viec_doi_co` khi CHỈ đổi `status` (cập nhật payload point, không nhúng lại) và
  chỉ dùng `kb_delete` khi hàng bị xoá thật; cổng nạp dùng `kb_delete` cho cả trường hợp
  rời `published`. Lệch này có thật nhưng không chặn việc đang làm — không đổi ở đợt này.
- **Sửa bất kỳ dòng nào trong `modules/kb`.** Nếu phải sửa nó thì tức là chỗ móc đã chọn
  sai.

## 3. Bốn quyết định đã chốt

| # | Quyết định | Đánh đổi đã nêu và chấp nhận |
|---|---|---|
| 1 | **Tự động hoàn toàn** — lô nạp xong là hệ thống tự đặt việc, không cần ai bấm | Mỗi lô có thể tiêu tiền embed. Lưới chặn là dấu tay nội dung: worker thoát trước khi nhúng nếu nội dung không đổi |
| 2 | **Đặt việc theo TỪNG bản ghi**, không gộp theo dự án | Lô 500 bản ghi có thể sinh tới 500 hàng `control.jobs`, và worker chạy tuần tự nên tenant khác dùng chung worker phải đợi. Chọn vậy vì `kb_sync_project` chỉ liệt kê con **đang published**, nên hàng nháp nạp qua API sẽ không bao giờ được nhúng — lệch hành vi so với đường giao diện, nơi hàng nháp CŨNG có point (D07) |
| 3 | **Tài liệu cần OCR thì tự duyệt** ở đường API (bật cờ `tu_duyet`) | OCR đọc sai thì agent trả lời theo chữ sai mà không ai kiểm. Chọn vậy vì tenant dùng API không có người ngồi duyệt, và van duyệt khi đó biến thành "tài liệu đứng mãi" |
| 4 | **Không làm `reconcile`** ở nhánh này | Việc bị rơi vì lý do khác cổng API vẫn không có gì bù. Chỉ báo lệch trên giao diện là lưới tạm |

## 4. Thiết kế

### 4.1 Nguyên tắc

Cổng nạp **không biết cách nhúng gì cả**. Nó chỉ đặt việc, đúng như đường giao diện.
Toàn bộ pipeline Qdrant — bóc chữ, chia chunk, nhúng, upsert, sổ trạng thái — giữ
nguyên.

### 4.2 Chỗ móc: `chieu.chieu_mot()`, sau `_upsert`, TRONG savepoint của bản ghi

Ba lý do, mỗi lý do loại một phương án khác:

1. **Đối xứng với `_xep_purge`** đã nằm sẵn trong chính hàm đó. Hai chiều của cùng một
   việc thì ở cùng một chỗ.
2. **Nó phủ CẢ HAI đường vào mà không viết hai lần.** Đường nóng (`service._nap_mot`) và
   đường nhặt-con-đang-chờ (`service._chieu_con_dang_cho`) đều gọi `chieu_mot`. Móc ở
   `_nap_mot` sẽ bỏ sót đường thứ hai — mà đó là đường **mọi** bản ghi tới trước cha đi
   qua, tức là ca thường xuyên nhất của đẩy bất đồng bộ, không phải ca hiếm.
3. **Nằm trong savepoint** nên bản ghi rollback thì việc biến mất theo. Không bao giờ có
   hàng `control.jobs` trỏ vào một bản ghi chưa được ghi. Đặt việc sau khi cả lô xong
   (trong `nap_lo`) mất tính chất này.

**Import phải đi qua mặt tiền.** Luật 3 (`tests/test_module_boundaries.py`, đọc AST) chỉ
cho module import `portal.core.*` và `portal.modules.<khác>.contracts`. Hai hàm đặt việc
sống ở `kb/ops/enqueue.py` và được `kb/contracts.py` phơi ra qua `__getattr__` lười
(`_ENQUEUE_FACADE`) — dựng sẵn cho `modules/realestate`. Cổng nạp dùng đúng cửa đó, như
nó đã làm với `KIND_DELETE_INDEX`.

### 4.3 Loại việc theo entity

Bám đúng luật đường giao diện đang dùng (`realestate/router.py`):

| Entity hợp đồng | Việc đặt | Vì sao |
|---|---|---|
| `project`, `zone` | `dat_viec_nap` | nội dung đã là chữ sẵn trong cột DB |
| `unit` | **không đặt gì** | `units` không nhúng (`verticals/real_estate.py`); agent lọc căn bằng SQL trên cột thật |
| `media` `content_type` ∈ {`image`, `video`} | `dat_viec_thumb` | việc thumb TỰ nối sang việc nạp khi xong. Đặt nạp thẳng thì point mang `thumb_url` rỗng vĩnh viễn và không gì kích hoạt nạp lại — đúng lý lẽ docstring `dat_viec_thumb` |
| `media` `content_type` = `tour_360` | `dat_viec_nap` | là một link, không có ảnh để thu nhỏ. Khớp `router.py::_sync_tour_360` |
| `document` có `body` khác rỗng | `dat_viec_nap` | đã có chữ, không cần bóc |
| `document` `body` rỗng hoặc vắng, có `file_url` | `dat_viec_thumb(tu_duyet=True)` | nối thumb → bóc chữ → nạp. `tu_duyet` đã là tham số có sẵn của `dat_viec_thumb`, không phải thêm mới |
| `document` không có cả hai | `dat_viec_nap` | `documents` chỉ nhúng cột `body`, nên không có gì để nhúng: `rag.index` xoá point cũ rồi trả 0 point. Đó là kết cục ĐÚNG (tài liệu chỉ có tiêu đề không tra cứu được), và phải đi qua việc nạp mới xảy ra — bỏ qua thì point cũ sống sót sau khi khách xoá trắng nội dung |

Hai chi tiết dễ sai:

- **`entity` truyền vào là TÊN BẢNG**, không phải tên entity của hợp đồng: `dat_viec_nap`
  và toàn bộ `modules/kb` dùng `projects`/`zones`/`documents`/`media`, còn hợp đồng dùng
  số ít. Map `chieu._BANG` đã có, và `_xep_purge` đã dùng đúng nó.
- **`project_code` phải có trong payload việc.** Chỉ báo tiến độ đếm theo khoá đó; việc
  thiếu nó không đếm vào dự án nào. Trong `chieu_mot` giá trị này đã có trong `cot` cho
  mọi entity (bản ghi con lấy từ `_giai_cha`, `project` tự sinh ở nhánh riêng).

### 4.4 Bốn ca KHÔNG đặt việc

| Ca | Cơ chế |
|---|---|
| Bản ghi `stale` | `chieu_mot` không được gọi — `repo.ghi_ban_ghi` trả `False` trước đó |
| Bản ghi chờ cha | `_giai_cha` ném `ChuaGiaiDuocCha` trước khi tới `_upsert` |
| `op: delete` | `_xoa_mem` chạy rồi `return` sớm, không đi tới nhánh upsert |
| Lượt này đã đặt `kb_delete` (hàng rời `published` qua upsert) | **Điều kiện thêm mới** — xem dưới |

Ca cuối là ca duy nhất cần code mới, và nó cần vì hai việc sẽ chống nhau: `chieu_mot`
đặt việc nạp ở cuối, còn nhánh `hien_trang["status"] == "published" and
cot.get("status") != "published"` đặt `kb_delete` ngay sau đó. Thứ tự chạy của hai việc
không xác định, và cả hai kết cục đều "không sai" nhưng đều lãng phí: nạp-rồi-xoá tiêu
một lượt embed cho point bị xoá ngay, xoá-rồi-nạp để lại point mang `status` không
`published` (agent lọc bỏ — vô hại nhưng đã tốn embed).

Cách xử lý: hàm biết nó vừa đặt `kb_delete` thì bỏ bước đặt việc nạp của chính lượt đó.
Một biến cục bộ, không thêm truy vấn.

### 4.5 Chống trùng đã có sẵn

`dat_viec_nap` và `dat_viec_thumb` đều tra `_CAU_DA_CHO` trước: record đang có việc cùng
loại ở trạng thái `queued` thì trả `None` và không đặt thêm. Nên adapter đẩy lặp, hoặc
hai lô đụng cùng bản ghi, không sinh việc nhân đôi. Chỉ gộp việc `queued` — việc đã
`running` đọc bản CŨ nên lượt này phải có việc riêng.

## 5. Lỗi cùng họ: `tour_360` chưa từng được đặt việc

`chieu._sync_tour_360` (thêm 2026-08-17) gọi `realestate.contracts.sync_tour_360` và
**bỏ qua giá trị trả về**. Hàm đó trả `(id vừa ghi, id vừa xoá)`, và đường giao diện
(`router.py::_sync_tour_360`) dùng cả hai: ghi thì `_enqueue_index`, xoá thì
`_enqueue_purge_record`.

Hậu quả hai chiều:

- Khách đẩy dự án kèm `link360` ⇒ hàng `media` tour được tạo trong Postgres nhưng không
  có point ⇒ `send_media` không bao giờ gửi được tour đó.
- Khách **rút** `link360` ⇒ `repo.sync_tour_360` chạy `DELETE` (xoá THẬT, không xoá mềm)
  ⇒ point cũ ở lại vĩnh viễn ⇒ agent tiếp tục gửi cho khách một link tour đã chết. Chiều
  này tệ hơn: không phải thiếu thông tin mà là thông tin sai.

**Sửa:** nhận `(moi, da_xoa)` rồi đặt việc tương ứng — `dat_viec_nap` cho `moi`,
`kb_delete` theo `(entity="media", record_id)` cho `da_xoa`. Giống hệt đường giao diện.

Hai test hiện có (`test_link360_qua_cong_nap_sinh_hang_media_tour`,
`test_bo_link360_qua_cong_nap_thi_xoa_hang_tour`) chỉ kiểm **hàng trong Postgres** nên
vẫn xanh trong khi lỗi này tồn tại. Test mới phải kiểm ở tầng `control.jobs`.

## 6. Mock bên thứ ba và e2e

### 6.1 Ràng buộc đã chốt: chỉ embed THẬT

E2E gọi embed service thật (`KB_EMBED_URL` + `KB_SANTA_MODELS_TOKEN`). Hệ quả phải nói
rõ ngay:

- **Không chạy được trong CI** và không chạy được trên máy không có đường vào VPC.
- **Tốn tiền embed mỗi lượt chạy.**

Nên script này là công cụ xác minh chạy tay trên máy dev, cùng hạng
`scripts/demo_cong_nap_e2e.py`. Phần bao phủ **tự động** nằm ở mục 7, dùng
`kb/fake.py::FakeIndexClient` như các test hiện có.

Qdrant thì dùng bản trong `docker-compose.dev.yml` (cổng 6343), không cần gì thêm.

### 6.2 Giữ nguyên `demo_cong_nap_e2e.py`

Không gộp phần Qdrant vào script đó. Nó đang kiểm nửa Postgres + bài rate-limit và
**chạy được không cần embed**; gộp vào là làm nó phụ thuộc tunnel và mất khả năng đó.
Script mới đứng riêng.

### 6.3 Ba thành phần mới

**(a) Server CRM giả** — `scripts/crm_gia/`, app FastAPI nhỏ chạy cổng **8123** (mọi cổng
khác trên máy dev đã có chủ: 5442 · 6382 · 6343 · 9002 · 8100 · 5273 · 8016).

Điểm quan trọng nhất: **tên trường và đơn vị CỐ Ý khác hợp đồng của mình.** Giá trả theo
triệu đồng, diện tích trả dạng chuỗi `"85 m²"`, tên trường tiếng Việt, mã bản ghi dạng
`PRJ-0001`. Nếu server giả trả đúng schema của mình thì adapter chỉ là copy, và ta không
kiểm được điều đáng kiểm nhất: hợp đồng này có viết adapter được hay không.

Bốn thứ nó có, mỗi thứ ép adapter xử lý một tình huống thật:

| Thứ | Ép adapter phải |
|---|---|
| Phân trang (`?page=`) | ghép nhiều trang trước khi đẩy |
| `?since=` | biết cái gì vừa đổi, để vòng chạy delta chỉ đẩy phần thay đổi |
| Bản ghi **biến mất** khỏi danh sách | phát hiện xoá bằng bản kê, không bằng event |
| Endpoint phục vụ tệp (`GET /tep/<ten>`) | nhánh bóc chữ có thứ thật để tải về |

Bản ghi biến mất cần một cách kích hoạt tường minh, không phải ngẫu nhiên: server giả có
thêm `POST /gia-lap/an/<loai>/<ma>` để script e2e chủ động ẩn một bản ghi khỏi danh sách.
Ngẫu nhiên hoá sẽ làm một lượt e2e đỏ không tái lập được.

Tệp sinh tại chỗ bằng thư viện **đã có** trong `pyproject.toml`, không thêm dependency:
PDF có lớp chữ (viết thẳng cấu trúc PDF tối giản, `pypdf` bóc được) · PDF không lớp chữ
(Pillow xuất ảnh thành PDF ⇒ đi nhánh OCR) · PNG (Pillow) · docx (`python-docx`) · xlsx
(`openpyxl`).

**(b) Adapter** — `scripts/adapter_crm_gia.py`. Đóng đúng vai hệ thống bên khách, và phải
làm bốn việc mà khách thật cũng phải làm:

1. Đẩy `/events` theo lô ≤ 500 bản ghi.
2. Đọc `results` và in bản ghi `rejected` kèm lý do — không chỉ xem mã HTTP.
3. Gửi `/manifest` cho từng entity: sắp `externalId` theo **thứ tự byte**, phân trang với
   `afterExternalId` = mã lớn nhất **đã gửi** ở trang trước, `isLastPage` đúng ở trang
   cuối.
4. Nhận `externalIdLech` rồi đẩy lại đúng những mã đó.

Có một vòng chạy cố ý **đảo thứ tự** (đẩy `unit` trước `project`) để xác minh cơ chế chờ
cha và lan truyền hoạt động qua đường thật, không chỉ trong test.

Tách khỏi script e2e để nó đọc được như tài liệu sống: đây là thứ đưa cho đội kỹ thuật
bên khách xem.

**(c) Script e2e** — `scripts/e2e_nap_toi_qdrant.py`. Chuỗi bước:

1. Vai quản trị (cookie phiên + `WORKSPACE_ADMIN`): tạo token nạp.
2. Gọi adapter **vòng 1** — đẩy toàn bộ dữ liệu theo thứ tự ĐẢO (`unit` trước `project`)
   để bản ghi con phải nằm chờ cha rồi được lan truyền.
3. Chờ hàng đợi cạn: poll `control.jobs` của tenant tới khi không còn `queued|running`,
   **có timeout** và in ra việc `failed` nếu có.
4. Xác minh Qdrant: đếm point trên `<tenant>_documents` và `<tenant>_media`; đọc một
   point mỗi loại và kiểm payload — `project_id` đúng, có `status`, `text` chứa tên dự
   án, ảnh có `thumb_url` không rỗng.
5. Kiểm chiều xoá: rút `link360` + `op: delete` một tài liệu ⇒ point tương ứng biến mất.
6. Kiểm dấu tay: gọi adapter **vòng 2** — đường delta qua `?since=`, không đổi nội dung
   gì ⇒ số point không đổi và việc nạp báo bỏ qua theo dấu tay.
7. Dọn: xoá mềm bản ghi đã tạo, xoá token.

Mọi `externalId` mang tiền tố duy nhất theo lượt chạy, như script demo đã làm, nên chạy
lại không giẫm lên nhau.

⚠️ Bản kê của adapter phải **khoanh vùng** (`afterExternalId` = tiền tố lượt chạy,
`isLastPage: false` ở trang cuối của vùng) — cùng bẫy mà `demo_cong_nap_e2e.py` đã ghi:
một bản kê `isLastPage: true` từ script sẽ gắn cờ nghi mất tích cho mọi bản ghi có sẵn
của tenant dev nằm sau khoảng đó.

### 6.4 Dữ liệu — hoàn toàn mới

Không dùng lại dữ liệu seed hay dữ liệu dev. Khối lượng chọn để mỗi luật trong hợp đồng
có ít nhất một bản ghi chạm tới:

| Loại | Số lượng | Cố ý gồm |
|---|---|---|
| Dự án | 3 | ba `region`, ba `salePhase` khác nhau, một dự án có `link360` |
| Phân khu | 7 | **một dự án không có phân khu nào** — chạm luật `zoneExternalId` tuỳ chọn (`units.zone_code` nullable từ `0902`) |
| Căn | ~120 | trộn `productType`, đủ ba `saleStatus`, vài căn **chưa có giá** |
| Tài liệu | 12 | một số gửi kèm `body`; một số chỉ có `fileUrl` — cả PDF có lớp chữ lẫn PDF scan (nhánh OCR); có `loai: csbh` |
| Ảnh/video | 20 | đủ 7 `category` ảnh, vài `video`, một `tour_360` |

Khoảng 160 bản ghi, nhưng chi phí embed chỉ đến từ 3 + 7 + 12 + 20 = 42 bản ghi — `units`
không nhúng.

## 7. Test tự động

Bám khuôn `tests/modules/ingest/test_nap.py`, nơi đã có sẵn các test đọc thẳng
`control.jobs` để kiểm payload `kb_delete`. File mới:
`tests/modules/ingest/test_xep_viec_nap.py`.

| Test | Kiểm |
|---|---|
| mỗi entity đặt đúng loại việc | `project`/`zone` ⇒ `kb_index`; ảnh ⇒ `kb_thumb`; tài liệu có `body` ⇒ `kb_index`; tài liệu chỉ có `fileUrl` ⇒ `kb_thumb` với `tu_duyet=True`; `tour_360` ⇒ `kb_index` |
| `unit` không sinh việc | lô toàn `unit` ⇒ không hàng `control.jobs` nào thêm |
| payload việc mang `project_code` | mọi việc đặt ra đều có khoá đó, khác rỗng |
| `entity` trong payload là tên bảng | `documents`/`media`/`projects`/`zones`, không phải số ít |
| đẩy lại y hệt không nhân đôi việc | hai lô giống nhau ⇒ đúng một việc `queued` mỗi record |
| `stale` không sinh việc | mốc cũ hơn ⇒ không chiếu, không việc |
| chờ cha: việc xuất hiện đúng lúc cha tới | trước: không việc cho con. Sau khi cha chiếu: có việc cho cả con |
| rời `published` chỉ có `kb_delete` | không việc nạp nào đi kèm trong cùng lượt |
| `op: delete` không sinh việc nạp | chỉ `kb_delete` |
| `tour_360` hai chiều | thêm `link360` ⇒ có `kb_index` cho hàng media mới; rút `link360` ⇒ có `kb_delete` đúng `record_id` vừa mất |
| cách ly tenant | việc đặt ra thuộc đúng `tenant_id` của token |

## 8. Bề mặt thay đổi

| File | Thay đổi |
|---|---|
| `src/portal/modules/ingest/chieu.py` | đặt việc nạp sau `_upsert`; bảng luật theo entity; điều kiện bỏ qua khi vừa đặt `kb_delete`; `_sync_tour_360` dùng giá trị trả về |
| `tests/modules/ingest/test_xep_viec_nap.py` | mới |
| `scripts/crm_gia/` | mới — server CRM giả + bộ dữ liệu + sinh tệp |
| `scripts/adapter_crm_gia.py` | mới — vai hệ thống bên khách |
| `scripts/e2e_nap_toi_qdrant.py` | mới — chạy adapter rồi xác minh tới Qdrant |
| `Makefile` | hai target: `crm-gia` (chạy server giả) và `e2e-qdrant` (chạy adapter + xác minh). Ở Makefile chứ không chỉ trong README, để cách chạy nằm cùng chỗ với mọi lệnh khác của repo |

Không sửa `modules/kb`. Không sửa `demo_cong_nap_e2e.py`. Không thêm dependency.

## 9. Hạn chế đã biết

1. **Lô lớn làm nghẽn hàng đợi.** Quyết định #2 chọn từng-bản-ghi, nên một lô 500 bản ghi
   sinh tới 500 việc và worker chạy tuần tự — tenant khác dùng chung worker phải đợi.
   Giảm nhẹ bằng gộp việc-đang-chờ (§4.5) và bằng việc `units` không sinh việc nào (phần
   lớn khối lượng của một lô thật là căn). Nếu đo thấy nghẽn thật thì hướng xử lý là
   nhiều worker, không phải gộp việc theo dự án — gộp sẽ mang lại đúng lỗ hổng hàng nháp
   đã nêu ở #2.
2. **OCR sai đi thẳng tới agent** (quyết định #3). Nội dung vẫn hiện ở tab Kiến thức nên
   sửa được sau, nhưng không có ai chặn trước.
3. **E2E không chạy trong CI** (§6.1). Regression thật sự do test ở mục 7 canh; script
   e2e chỉ chứng minh chuỗi hoạt động khi có người chạy.
4. **Lệch `kb_delete` vs `dat_viec_doi_co` giữa hai đường** vẫn còn (§2). Cổng nạp tiêu
   một lượt xoá point ở chỗ đường giao diện chỉ cập nhật cờ trong payload.
