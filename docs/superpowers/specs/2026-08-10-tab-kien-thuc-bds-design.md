# Tab Kiến thức BĐS — chia lại màn dự án, và tách `doc_type` của tài liệu

Ngày: 2026-08-10 · Nhánh: `feat/kb-tab` · Trạng thái: đã chốt, chưa thi công

## 1. Vấn đề

Màn chi tiết một dự án (`/pform`, `/uform`) hiện có năm tab: `Thông tin` · `Phân khu` ·
`Căn` · `Tài liệu` · `Media`. Hai chỗ đau:

- **Tab `Thông tin` ôm 21 ô nhập** trong một trang cuộn dài, và tab `Media` dồn cả bảy
  vùng ảnh vào một màn.
- **Không khớp thói quen ngành.** Biên tập viên và sale BĐS quen cấu trúc của portal bán
  hàng: `Tổng quan` · `Vị trí` · `Ảnh 360` · `Phân khu` · `Mặt bằng quỹ căn` · `Quỹ căn` ·
  `CSBH` · `Video` · `Tiến độ` · `Tài liệu` · `Tin tức`. Bộ tab của Portal không đọc ra
  được cùng bản đồ đó, nên mỗi lần nhập là một lần phải dịch trong đầu.

Không có yêu cầu nào về phía agent. Đợt này **không** nhằm cải thiện chất lượng trả lời —
nhưng một phần của nó chạm vào luồng ingest, và chỗ đó có hệ quả thật (§4).

## 2. Ngoài phạm vi

- **Mọi thay đổi schema Postgres.** Không thêm cột, không thêm bảng, không migration. Đây
  là ràng buộc cứng do chủ sản phẩm đặt, và nó định hình §4.2 — phương án hiển nhiên
  (thêm `documents.doc_type`) đã bị loại vì lý do này, không phải vì kỹ thuật.
- **Tin tức.** Chưa có bảng nào, và không đủ nhu cầu để dựng. Bỏ khỏi bộ tab.
- **Màn `/kb` "Tài liệu tra cứu".** Kho tệp upload là chuyện khác, không đụng.
- **Cải thiện chất lượng retrieval.** `chunk` strategy giữ nguyên cho mọi loại.
- **Sửa bất kỳ tài liệu nào đã có** trong `docs/`. Xem §9.

## 3. Nguyên tắc: tab là lăng kính, không phải ngăn chứa

Quyết định nền, chi phối toàn bộ §5:

> Một row `media` hay `documents` nằm ở **đúng một chỗ** trong DB. Nhiều tab cùng nhìn vào
> nó bằng bộ lọc khác nhau. Overlap giữa các tab là bình thường và có chủ đích.

Hệ quả phải thiết kế theo, không được coi là lỗi:

- Tab `Media` hiện **đủ bảy vùng**, gồm cả `vi_tri` · `mat_bang` · `tien_do` vốn đã có tab
  chuyên đề riêng. Tab chuyên đề là lối tắt, tab `Media` là màn tổng.
- Tab `Tài liệu` hiện **toàn bộ** `documents`; tab `CSBH` là một lát cắt của chính danh sách đó.
- Sửa caption một ảnh ở tab `Vị trí` thì ở tab `Media` nó cũng đổi. Xoá ở một chỗ là mất ở
  mọi chỗ.

Điểm cuối là chỗ dễ hiểu nhầm nhất: người dùng thấy cùng một ảnh ở hai tab sẽ tưởng đó là
hai bản sao và bấm xoá "bản thừa". **UI phải nói ra** — mỗi tab chuyên đề mang một dòng
nhắc rằng nội dung của nó cũng nằm trong tab `Media`, và hộp thoại xác nhận xoá phải nói
là xoá khỏi dự án chứ không phải khỏi tab.

## 4. Tầng dữ liệu

### 4.1 Gộp `thong_tin` vào `tong_quan`

`REAL_ESTATE` hiện khai **hai** `EntitySpec` cho bảng `projects`:

| `doc_type` | `chunk` | `fields` |
|---|---|---|
| `thong_tin` | `facts` | `region` · `investor` · `total_land_area_m2` · `floor_area_m2` · `build_density_pct` · `product_scale` · `ownership_form` · `handover_standard` · `total_investment_vnd` |
| `tong_quan` | `markdown` | `overview` · `amenities` |

Gộp thành một, giữ `doc_type="tong_quan"`, bỏ `thong_tin`:

```python
EntitySpec(
    table="projects",
    doc_type="tong_quan",
    chunk="facts",
    is_anchor=True,
    anchor_col=ANCHOR_CODE_COL,
    fields=(
        "region", "investor", "total_land_area_m2", "floor_area_m2",
        "build_density_pct", "product_scale", "ownership_form",
        "handover_standard", "total_investment_vnd",
        "overview", "amenities",
    ),
),
```

**`chunk` phải là `facts`, không phải `markdown`.** `build_text()` rẽ nhánh ngay trên giá
trị đó (`resolve.py`): `facts` sinh `"{tên cột}: {giá trị}"` mỗi dòng, mọi giá trị khác sinh
giá trị trần. Chọn `markdown` thì chín quick-fact mất nhãn cột và embed thành chuỗi
`"Hà Nội\nVingroup\n50000\n42.5\n…"` — không còn gì cho biết `42.5` là mật độ xây dựng.
Đổi lại, `overview`/`amenities` mang tiền tố `overview: …`; vô hại với embedding.

**`overview`/`amenities` đặt CUỐI `fields`.** Thứ tự `fields` quyết định `content_hash`
(`build_text` ghép theo đúng thứ tự khai). Đặt cuối giữ nguyên thứ tự tương đối của chín
quick-fact nên diff đọc được. Hash vẫn đổi và toàn bộ `projects` sẽ reindex — đó là ý đồ.

**`source_for()` sẽ im lặng chấp nhận caller cũ.** Sau khi gộp, `projects` chỉ còn một
candidate nên nhánh `len(candidates) == 1` nhận và tham số `doc_type` bị bỏ qua — một
caller còn truyền `"thong_tin"` vẫn chạy đúng, không lỗi, không cảnh báo. Nên phải sửa
caller tường minh; đừng dựa vào việc test sẽ đỏ.

### 4.2 Phân loại tài liệu — tiền tố `title`, không cột mới

`tenant_data.documents` có `title` · `body` · `file_url` · `status`, không gì phân biệt
CSBH với tài liệu khác. Migration `0400` ghi rõ đây là chủ ý — và cũng đã chỉ sẵn lối đi:

> `documents` KHÔNG CÓ CỘT `category` — nó gộp faq/hoàn thiện/vật liệu/pháp lý/CSBH/hướng
> dẫn thành MỘT loại nội dung, **phân biệt bằng `title`**.

§2 cấm mọi thay đổi schema, nên phân loại phải sống trong một cột đã có. Ba cột kia đều đã
mang nghĩa khác, còn lại `title`.

**Vì sao không đơn giản là "khai thêm `EntitySpec`".** `EntitySpec.doc_type` là **hằng khai
báo** — thuộc tính của *spec*, không của *row*. Khai bốn spec cho `documents` sẽ sinh bốn
câu SQL giống hệt nhau, vì `list_published_sql` chỉ lọc theo `status` và không biết gì về
loại; kết quả là mỗi tài liệu được index bốn lần dưới bốn `doc_type`. Phân loại thay đổi
theo từng row, nên nó phải đến từ row.

**Vì sao không phải `file_url`.** Đây là ứng viên trực giác nhất khi UI chia vùng upload,
và nó sai. Khoá kho là content-addressed:

```python
khoa = f"tenants/{tenant}/kb-bds/{sha256}/{ten_an_toan}"
```

Docstring của `tai_tep_len()` nói vì sao: *"tải cùng một ảnh hai lần cho cùng một khoá, nên
không sinh bản sao và FE gửi lại được sau khi mất mạng mà không rác"*. Chèn loại vào khoá
phá đúng tính chất đó, và tệ hơn: **đổi loại một tài liệu sẽ phải chuyển byte sang khoá
mới**, vì loại nằm trong một đường dẫn bất biến. Phân loại là thứ hay đổi; khoá lưu trữ là
thứ không được đổi. Ngoài ra `file_url` nullable — `0400` chốt là nhập tay `title` + `body`,
nên tài liệu gõ tay sẽ không có gì để phân loại.

**Cơ chế.** Tiền tố cố định ở đầu `title`, do UI ghép chứ không do người dùng gõ:

```python
# kb/contracts.py — KHÔNG ở verticals/real_estate.py: modules/realestate phải ghép và
# tách tiền tố ở biên HTTP, mà luật 3 chỉ cho nó import contracts.
TITLE_SEPARATOR = " — "
TITLE_PREFIXES = {"CSBH": "csbh", "Pháp lý": "phap_ly", "Hướng dẫn": "huong_dan"}
DEFAULT_DOC_TYPE = "khac"

def split_title(title: str) -> tuple[str, str]:
    """Tiền tố lạ thì trả NGUYÊN VĂN cả câu — xem "cái phải trả" ở cuối mục."""
    dau, sep, duoi = title.partition(TITLE_SEPARATOR)
    if sep and dau in TITLE_PREFIXES:
        return TITLE_PREFIXES[dau], duoi
    return DEFAULT_DOC_TYPE, title

def doc_type_of(row: dict) -> str:   # chữ ký khớp EntitySpec.doc_type_from
    return split_title(str(row["title"]))[0]
```

```python
# contracts.py — EntitySpec thêm một trường
doc_type_from: Callable[[dict], str] | None = None   # None = dùng doc_type hằng

# resolve.py — resolve_text()
doc_type=spec.doc_type_from(row) if spec.doc_type_from else spec.doc_type
```

**Không phải thêm gì vào `extra_cols`:** `title` đã nằm trong `fields` của spec `documents`
nên `read_record_sql` vốn đã SELECT nó.

Ba thứ được, y như phương án cột: point-id mang loại thật thay vì `tai_lieu` chung chung;
`kb_index_state` tách dòng theo loại nên trả lời được "CSBH của dự án này đã index chưa";
và breadcrumb `section` tự mang loại — `section_col="title"` nên nó thành
`Vinhomes Global Gate > CSBH — Bảng giá đợt 3` mà không cần chèn cấp nào. Tiền tố cũng nằm
sẵn trong text embed vì `title` là field đầu.

**Tập giá trị: `csbh` · `phap_ly` · `huong_dan` · `khac`.** Ba loại còn lại trong danh sách
của `0400` (`hoan_thien` · `vat_lieu` · `faq`) để lại: giá trị không có vùng nào dùng thì
không ai nhập, và một enum chết đắt hơn việc thêm một dòng vào `TITLE_PREFIXES` sau.

**Cái phải trả: `title` mang hai nghĩa** — vừa là tiêu đề người đọc, vừa là khoá phân loại
máy đọc. UI chặn được đường thường (ô tiêu đề chỉ chứa phần đuôi, tiền tố hiển thị như nhãn
dính liền), nhưng API và SQL tay vẫn sửa thẳng `title` được. Một tiêu đề bị sửa hỏng tiền
tố sẽ lặng lẽ rơi về `khac`: biến khỏi tab CSBH, **và** đổi point-id nên để lại point mồ
côi (§4.4).

### 4.3 Bất biến point-id — chỗ nguy hiểm nhất của đợt này

Đặc tả rag-service (`docs/db-design/02b-rag-service.md` §5 bước 6):

```
Point: id uuid5(doc_type:record_id:idx)
```

**Không có tên bảng trong công thức.** `doc_type` là thứ duy nhất phân biệt nguồn. Hôm nay
điều đó an toàn vì mỗi bảng có đúng một `doc_type` hằng do lập trình viên khai. Cho
`documents` lấy `doc_type` từ row là **chuyển bất biến ấy sang tay người nhập liệu**.

Nếu tập giá trị bao giờ đó chứa `tong_quan` hoặc `phan_khu`, thì `projects` id 12 và
`documents` id 12 sinh **cùng một uuid5** và ghi đè lẫn nhau — không lỗi, không log, chỉ là
một trong hai biến mất khỏi kho vector. `tong_quan` là cái tên tự nhiên nhất người ta sẽ
nghĩ đến cho một tài liệu giới thiệu dự án, nên đây không phải rủi ro lý thuyết.

(Tenant không bị ảnh hưởng: collection tách theo `workspace_slug`, nên hai tenant không thể
đụng nhau qua point-id.)

Không gian `doc_type` sau đợt này:

| Nguồn | `doc_type` | Đến từ |
|---|---|---|
| `projects` | `tong_quan` | hằng, khai trong spec |
| `zones` | `phan_khu` | hằng, khai trong spec |
| `documents` | `csbh` · `phap_ly` · `huong_dan` · `khac` | **suy từ tiền tố `title`** |
| `media` | `""` | đường riêng (`service.py` truyền rỗng) |

**Phương án tiền tố lại an toàn hơn phương án cột ở đúng chỗ này.** `doc_type_of()` là
hàm toàn phần với miền giá trị **đóng**: mọi title không khớp `TITLE_PREFIXES` đều rơi về `khac`.
Người dùng không nhập `doc_type`, họ chọn vùng — nên không có đường nào để `tong_quan` lọt
vào. Bất biến được cưỡng chế bởi cấu trúc của hàm, không bởi một CHECK constraint mà ai đó
có thể mở rộng ở migration sau.

Cổng canh còn lại chỉ một lớp, và nó canh **hằng `TITLE_PREFIXES`**, không canh dữ liệu:

```python
# tests/unit/test_doc_type_khong_dung.py
def test_loai_tai_lieu_khong_dung_doc_type_cua_nguon_khac():
    values = set(TITLE_PREFIXES.values()) | {"khac"}
    khac = {s.doc_type for s in REAL_ESTATE.embed_sources if s.doc_type_from is None}
    assert values & khac == set()
```

Test này đỏ khi ai đó thêm một tiền tố mới vào `TITLE_PREFIXES` và vô tình chọn một tên đã thuộc
nguồn khác. Nó phải mang comment nói rõ vì sao — nếu không, người gặp nó sẽ nghĩ đây là
test khó tính và sửa `values` cho xanh.

### 4.4 Đổi loại tài liệu làm mồ côi point

`csbh → phap_ly` đổi point-id. `reconcile.diff()` so drift theo `record_id`, **không** theo
`doc_type`, nên record đó vẫn published và point cũ không bị tính là orphan. Khác với §8
ở chỗ nó lặp lại mỗi lần biên tập viên đổi vùng của một tài liệu, không phải một lần khi
migrate.

Với phương án tiền tố, bề mặt rộng hơn một chút: **mọi** thay đổi `title` đều phải kiểm,
không chỉ thao tác "đổi vùng" — vì loại được suy ra từ chính `title`. Bù lại, phép kiểm rẻ
và thuần: gọi `doc_type_of()` trên row cũ và row mới rồi so.

Xử ở chỗ ghi: `PATCH /documents/{id}` đọc `title` cũ trong **cùng transaction** với update;
nếu `split_title(cũ)[0] != split_title(mới)[0]` thì enqueue một job `kb_delete` mang
`doc_type` **cũ**. Sửa phần đuôi tiêu đề (đổi tên tài liệu, giữ tiền tố) không đổi loại nên
đi đường thường: `content_hash` đổi, reindex tại chỗ, point-id giữ nguyên.

Bản spec đầu viết *"trước khi enqueue index loại mới"* — sai về hiện trạng: router
`realestate` **không enqueue job index nào cả**, việc index đi qua `POST /kb/{entity}/
{record_id}/reindex` hoặc `backfill`. Nên việc cần làm ở đây chỉ là enqueue job xoá.

Xem §7 cho phần lỗ hở còn lại.

## 5. Bộ tab

Mười tab, thứ tự bám bộ tab ngành:

| # | id | Nhãn | Nhìn vào |
|---|---|---|---|
| 1 | `tong-quan` | Tổng quan | 16 trường của `projects` + ảnh cover · chia section bên trong |
| 2 | `vi-tri` | Vị trí | `region` · `address` + media `vi_tri` |
| 3 | `anh-360` | Ảnh 360 | `link_360` |
| 4 | `phan-khu` | Phân khu | `zones` — giữ nguyên `PhanKhuTab` |
| 5 | `mat-bang` | Mặt bằng | media `mat_bang` + `map_media_id` |
| 6 | `quy-can` | Quỹ căn | `units` — giữ nguyên `CanTab` |
| 7 | `csbh` | CSBH | `documents` — chỉ vùng `CSBH` |
| 8 | `media` | Media | **cả bảy vùng** media |
| 9 | `tien-do` | Tiến độ | media `tien_do` |
| 10 | `tai-lieu` | Tài liệu | **toàn bộ** `documents`, chia **bốn vùng** theo loại |

### 5.1 Các quyết định lệch khỏi bộ tab ngành

**Không có tab `Video`.** `media` phân biệt bằng **hai** trục — `category` (bảy giá trị) và
`content_type`. Một tab Video cắt ngang trục `category`, nên video tiến độ sẽ xuất hiện ở
cả tab Video lẫn tab Tiến độ; xoá ở một chỗ thì chỗ kia biến mất mà người dùng không hiểu
vì sao. Video ở lại đúng tab chủ đề của nó. (Đây là overlap **không** có chủ đích, khác với
§3: hai tab đó không có quan hệ tổng–bộ phận nào để người dùng đoán ra.)

**Không có tab `Tin tức`.** Xem §2.

**`Tổng quan` vẫn là tab nặng nhất — 16 trường cộng ảnh cover,** chia bằng section có tiêu
đề bên trong chứ không bằng tab: `Định danh & phân loại` (5) · `Chủ đầu tư` (2) ·
`Quy mô & mật độ` (5) · `Sở hữu & bàn giao` (2) · `Mô tả` (2). Một phương án tách `Thông số`
thành tab thứ mười một đã được cân nhắc và bỏ. Nó giải quyết triệt để hơn một trong hai
vấn đề ở §1, nhưng §1 có hai vấn đề: bốn ô rời khỏi tab này sang `Vị trí`/`Ảnh 360`/`Mặt
bằng` đã lấy đi phần lớn độ dài, và chia section giữ được sự liền mạch khi nhập một dự án
mới — biên tập viên điền một mạch từ tên đến mô tả, không phải nhớ mình đang ở tab nào.

**`investor`/`developer` ở `Tổng quan`, không ở nhóm số liệu** — dù trong spec cũ `investor`
thuộc nhóm `thong_tin`. Ràng buộc đó mất khi gộp §4.1, và chủ đầu tư là thứ sale nói ở câu
thứ hai, không phải con số tra cứu.

**Ảnh cover ở lại `Tổng quan`** dù các vùng media khác đã dời đi. `cover_media_id` là một
trường FK của `projects`, hành xử như `name`/`project_code`, không như một vùng thư viện.

### 5.2 Tab `Tài liệu` chia vùng — và vì sao vùng phải có hai lối vào

Bốn vùng, mỗi vùng ứng với một tiền tố ở §4.2. Hình dạng lấy nguyên từ `MediaTab` (bảy
vùng theo `category`), nên biên tập viên gặp cùng một cách nhập ở cả hai chỗ: kéo tệp vào
đúng vùng, không phải chọn thêm một dropdown sau khi kéo.

```
tab Tài liệu
┌─ CSBH ─────────────┐  ┌─ Pháp lý ──────────┐
│ [kéo tệp][Soạn tay]│  │ [kéo tệp][Soạn tay]│
│ • Bảng giá đợt 3   │  │ • Hợp đồng mẫu     │
└────────────────────┘  └────────────────────┘
┌─ Hướng dẫn ────────┐  ┌─ Khác ─────────────┐
│ [kéo tệp][Soạn tay]│  │ [kéo tệp][Soạn tay]│
└────────────────────┘  └────────────────────┘
```

Danh sách trong vùng hiện **phần đuôi** tiêu đề (`Bảng giá đợt 3`), không hiện tiền tố —
tiền tố đã là tên vùng, lặp lại nó làm mỗi dòng dài thêm mà không thêm thông tin.

**Mỗi vùng phải có cả "Soạn tay", không chỉ dropzone.** `0400` chốt cách nhập chính của
`documents` là gõ tay `title` + `body`, và `file_url` nullable. Một vùng chỉ nhận kéo-thả
sẽ không có cửa nào cho kiểu nhập đó — tài liệu không kèm tệp trở thành thứ không tạo được
qua UI.

**Tab `CSBH` là lăng kính của vùng đầu** (§3): cùng một row, hiện ở hai tab. Nó cần dòng
nhắc rằng đây cũng là vùng CSBH trong tab `Tài liệu`, nếu không người dùng thấy tài liệu ở
hai nơi sẽ tưởng có bản sao. Vì sao vẫn giữ tab riêng dù đã có vùng: CSBH là thứ sale mở
nhiều lần trong ngày, còn ba loại kia mở theo tuần — đưa nó lên hàng tab là đúng tần suất,
và đúng chỗ nó đứng trong bộ tab ngành.

### 5.3 Ghi chú thi công

**Năm tab dùng chung một vùng upload,** nên `VungMedia` (hiện nằm trong `MediaTab.tsx`)
tách ra file riêng.

**Cả năm giữ CÙNG query key `['re', code, 'media']` với `limit: 200`.** React-query dùng
lại một cache nên tách tab không sinh thêm request, và quan trọng hơn: số đếm "còn mấy ảnh
so với trần 6" vẫn đúng. Trần của backend đếm theo `(project, zone, unit, category)`; một
tab fetch riêng chỉ category của mình vẫn đếm đúng, nhưng năm query rời nhau sẽ lệch nhau
sau mỗi lần upload cho tới khi cả năm invalidate.

**Link cũ.** `tabHopLe()` hiện đưa mọi giá trị lạ về tab đầu, nên `?tab=thong-tin` và
`?tab=media` sẽ im lặng rơi về `tong-quan`. Thêm bảng ánh xạ `thong-tin→tong-quan` ·
`can→quy-can`; `media` giữ nguyên id nên không cần ánh xạ.

**`VI_SAO_KHOA_TAB` phải sửa lời** — giờ chín tab bị khoá khi chưa tạo dự án, không phải bốn.

## 6. Bề mặt thay đổi

**Không có migration.** Head alembic (`0916_conversations_source`) không bị đụng.

**Backend**

| File | Việc |
|---|---|
| `modules/kb/contracts.py` | `EntitySpec` thêm `doc_type_from: Callable[[dict], str] \| None = None`; thêm `TITLE_SEPARATOR` · `TITLE_PREFIXES` · `DEFAULT_DOC_TYPE` · `split_title()` · `join_title()` · `doc_type_of()` · `KIND_DELETE_INDEX` |
| `modules/kb/directive/resolve.py` | `resolve_text` gọi `spec.doc_type_from(row)` khi có |
| `modules/kb/directive/verticals/real_estate.py` | Gộp hai spec `projects`; spec `documents` khai `doc_type_from=doc_type_of` |
| `modules/kb/service.py` | `index_text` ghi `kb_index_state` bằng `directive.doc_type`, không phải `spec.doc_type`; `delete_index` tra `read_state()` khi caller không truyền `doc_type` |
| `modules/kb/jobs.py` | `KIND_DELETE` lấy từ `contracts.KIND_DELETE_INDEX` để không có hai nguồn |
| `modules/kb/state/repo.py` | Docstring `"""projects có hai dòng (thong_tin + tong_quan)"""` sai ngay sau §4.1 |
| `modules/realestate/contracts.py` | `TaiLieuOut` thêm `loai: str`; `title` trở thành phần đuôi |
| `modules/realestate/router.py` | DTO documents: **`loai` + `title` rời nhau ở API**, ghép/tách ở router (xem dưới); `PATCH` đổi loại thì enqueue `kb_delete` cho loại cũ (§4.4) |

**Hai hàng `service.py` không nằm trong bản spec đầu — chúng lộ ra lúc đọc code.** Sổ
`kb_index_state` đang ghi bằng hằng `spec.doc_type`, nên không sửa thì point mang `csbh`
còn sổ ghi `tai_lieu`, và §4.4 không có gì đúng để tra. Còn `delete_index` thì khi row đã
mất, không suy được loại từ `title` nữa — nguồn duy nhất còn lại là sổ. Điều này cũng vá
một bug sẵn có: `delete_cascade` gọi `delete_index` **không** truyền `doc_type` nên đang
xoá bằng `""`, không khớp point-id của bất kỳ nguồn nào.

**Không có `?loai=` trên API.** Tab lọc client-side trên danh sách dùng chung, đúng như
năm tab media ở §5.3 — không phải sửa `repo.py`, không phải nghĩ về phân trang khi lọc.

**Tiền tố ghép ở backend, không ở frontend.** DTO ghi nhận `loai: Literal["csbh","phap_ly",
"huong_dan","khac"]` và `title` là **phần đuôi**; router ghép `title = f"{tiền tố}{TITLE_SEPARATOR}{title}"`
trước khi ghi. DTO đọc làm ngược lại: nếu đoạn đầu khớp `TITLE_PREFIXES` thì trả `loai` tương ứng
và `title` là phần đuôi, ngược lại trả `loai="khac"` và `title` **nguyên văn**. Điều kiện
"nguyên văn" là chỗ dễ sai: một tiêu đề tự do như `Quy trình — bước 2` có dấu ngăn cách
nhưng không có tiền tố hợp lệ, và cắt nó đi sẽ âm thầm đổi tên tài liệu của người dùng.

Làm vậy để bảng tiền tố chỉ tồn tại ở **một** nơi. Nếu để frontend tự ghép, `TITLE_PREFIXES` phải
có bản sao bên repo kia, không có cổng nào so hai bên, và một chữ lệch sẽ khiến tài liệu
mới rơi hết về `khac` — im lặng, và chỉ phát hiện được khi ai đó thắc mắc sao tab CSBH rỗng.

**Frontend**

`tabDuAn.ts` lên mười tab + bảng ánh xạ id cũ · `VungMedia` tách khỏi `MediaTab.tsx` ·
năm component mới (`ViTriTab` `Anh360Tab` `MatBangTab` `TienDoTab` `CsbhTab`) ·
`ThongTinTab` → `TongQuanTab` chia section · `TaiLieuTab` chia bốn vùng, mỗi vùng có
dropzone và "Soạn tay" · `enums.ts` thêm `LOAI_TAI_LIEU` (chỉ **nhãn hiển thị**, không phải
tiền tố) · `api.ts` thêm `loai`.

**Test**

- Sửa `"thong_tin"`: `tests/modules/kb/test_source_query.py` (1 chỗ), `tests/modules/kb/test_directive.py` (3 chỗ).
- Thêm `tests/unit/test_doc_type_khong_dung.py` (§4.3).
- Thêm test cho `doc_type_from`: spec có hàm thì directive lấy giá trị từ row, spec không có thì lấy từ hằng.
- Thêm test cho `doc_type_of()`: bốn tiền tố hợp lệ · không có dấu ngăn cách · **có dấu
  ngăn cách nhưng tiền tố lạ** (phải ra `khac` và giữ nguyên `title`) · tiền tố sai hoa thường.
- Thêm test cho §4.4: PATCH làm đổi loại phải gọi `delete` với loại cũ; PATCH chỉ đổi phần
  đuôi tiêu đề thì **không** được gọi `delete`.

## 7. Hạn chế đã biết

**`reconcile` không bắt được point mồ côi do đổi loại bằng SQL tay.** §4.4 bịt đường qua
API, nhưng `reconcile` là lưới cho đúng những gì đi vòng qua API. Bịt hẳn phải thêm
`doc_type` vào `IndexPoint` và cho `diff()` so theo `(record_id, doc_type)` — tức đổi hợp
đồng `/admin/scroll` với repo `odyssey-agent`. Không làm ở đợt này; nhận phần hở.

**Overlap giữa các tab chưa có test.** Việc "xoá ảnh ở tab Vị trí thì tab Media cũng mất"
là hành vi đúng theo §3 nhưng chỉ được đảm bảo bởi việc năm tab dùng chung query key —
một người refactor sau có thể tách key mà mọi test vẫn xanh.

**`title` mang hai nghĩa, và DB không cưỡng chế được nghĩa thứ hai.** Không có cột thì
không có CHECK constraint; một `UPDATE documents SET title = …` bằng SQL tay đổi được cả
tiêu đề lẫn loại lẫn point-id trong một câu, không qua chỗ nào kiểm. Đây là cái giá của
ràng buộc "không đụng schema" ở §2, không phải một thiếu sót có thể vá trong phạm vi đó.
Nếu ràng buộc ấy được gỡ sau này, đường nâng cấp là thêm cột `doc_type` và đổi
`doc_type_from` thành đọc thẳng cột — `EntitySpec` không phải sửa, vì nó đã nhận một hàm
trên row chứ không nhận tên cột.

**`payload["doc_type"]` mang hai nghĩa tuỳ `kind` của job.** Từ `ops/backfill.py` (kind
`kb_index`) nó là *định danh spec* — `"tai_lieu"` — dùng để tra `EntitySpec`. Từ PATCH đổi
loại (kind `kb_delete`) nó là *doc_type thật của point* — `"csbh"`. Cùng một khoá, hai khái
niệm; chuyển tiếp nhầm giữa hai đường là point ở lại vĩnh viễn (`handle_index` từng làm vậy).

**Đường đọc của agent trả `title` CÓ tiền tố.** `agent_api.documents` và
`repo.liet_ke_tai_lieu_cho_agent` trả nguyên cột, trong khi mọi đường đọc của Portal trả
phần đuôi. Nhất quán với text đem đi embed, nhưng là thay đổi thấy được ở repo
`odyssey-agent` — nó nhận `"CSBH — Bảng giá"` chứ không phải `"Bảng giá"`.

**Audit không truy được "ai đã đổi phân loại tài liệu này".** `_nhat_ky` ghi
`truong: ["title"]` cho một PATCH chỉ gửi `loai`, vì loại nhập vào `title` trước khi xuống
DB. Nhật ký nói đúng cột đã đổi nhưng không nói được ý định của người dùng.

**Tiêu đề tự do bắt chước tiền tố sẽ bị đọc lại thành loại đó.** POST
`{loai: "khac", title: "CSBH — Bảng giá"}` lưu nguyên văn rồi `split_title` đọc lại thành
`loai="csbh"`. Response trả về đã tự sửa nên người dùng thấy ngay và không mất dữ liệu.

**Đổi loại `A → B → A` với NHIỀU worker có thể xoá mất point đang sống.** Mỗi PATCH đổi
loại xếp một cặp job `kb_delete{loại cũ}` + `kb_index`. Hai PATCH liên tiếp `csbh → phap_ly
→ csbh` cho `D1{csbh}` · `I1` · `D2{phap_ly}` · `I2`. `run_once` claim job theo `ORDER BY id`
nhưng **chạy handler ngoài giao dịch claim**, nên với từ hai worker trở lên, `D1` có thể
hoàn tất sau `I2` — nó xoá đúng point `csbh` mà `I2` vừa tạo, rồi `mark_deleted(["csbh"])`.
Tài liệu biến khỏi kho vector, không lỗi, không log. Job xoá không có hàng rào so version.

Một worker (`make worker`, mặc định) thì tuần tự nên an toàn. Bịt hẳn cần cùng thứ đã nêu ở
đầu §7: `doc_type` trong `IndexPoint` để `reconcile` so `(record_id, doc_type)` và bù lại
point thiếu.

## 8. Runbook — dọn point mồ côi

Chưa môi trường nào index dữ liệu thật, nên đợt này **không viết script**. Đoạn dưới dành
cho người triển khai lên một môi trường đã có index.

Hai loại point sẽ mồ côi sau khi lên bản này:

- `doc_type = 'thong_tin'` (bỏ ở §4.1)
- `doc_type = 'tai_lieu'` (thay bằng bốn loại ở §4.2)

**`reconcile` không dọn hộ.** Nó so theo `record_id`; record vẫn published nên point cũ
không bị coi là orphan. Bỏ qua bước này thì mỗi dự án tồn tại hai bản thông tin trong kho
vector, bản cũ đóng băng vĩnh viễn và agent vẫn tra ra — trả lời theo dữ liệu cũ mà không
có dấu hiệu gì.

Với mỗi tenant:

1. Với mọi `projects` published: `delete(workspace_slug, record_id=<project.id>, doc_type="thong_tin")`.
2. Với mọi `documents` published: `delete(workspace_slug, record_id=<document.id>, doc_type="tai_lieu")`.
3. `DELETE FROM tenant_data.kb_index_state WHERE doc_type IN ('thong_tin', 'tai_lieu')` —
   trong `tenant_conn()`, một transaction. Bảng nằm ở **`tenant_data`**, không phải `control`.
4. Backfill lại `projects` và `documents` để sinh point mới.

**Tài liệu cũ sẽ rơi hết về vùng `Khác`,** vì không tiêu đề nào có tiền tố. Đó là hành vi
đúng và không cần backfill dữ liệu — nhưng phải nói trước với biên tập viên, nếu không họ
mở tab `CSBH` lần đầu và thấy rỗng. Kéo một tài liệu sang vùng đúng là một lần đổi `title`,
tức một lần đi qua §4.4.

Phương án thay thế nếu số tenant nhỏ: `drop_collection` + `backfill` trọn vẹn. Chắc chắn
sạch nhưng embed lại cả `zones`/`media` vốn không đổi.

## 9. Lệch tài liệu — có chủ ý, ghi lại ở đây

Yêu cầu của chủ sản phẩm: **không sửa file tài liệu nào đã có.** Nên các chỗ sau sẽ mâu
thuẫn với code sau đợt này, và không có dấu hiệu nào tại chỗ báo cho người đọc:

| File | Chỗ lệch |
|---|---|
| `docs/db-design/02c-kb-ingest-module.md` §2.1 | mô tả `projects · doc_type thong_tin · chunk facts` — `thong_tin` không còn |
| `docs/db-design/02c-kb-ingest-module.md` §124 | "`projects` sinh **hai** dòng (`thong_tin`, `tong_quan`)" — nay một dòng |
| `docs/db-design/02a-real-estate-template.md` §225 | khai `rag_config` với hai spec `projects` |
| `docs/db-design/02b-rag-service.md` §101 | như trên |
| `docs/build_module_knowledgebase/02a`, `02b` | bản sao của hai file trên |
| `CLAUDE.md` | mục cảnh báo "RLS ĐÃ BỊ DỠ TOÀN BỘ" đã lỗi thời từ `0913_bat_lai_rls_tenant_data`, không liên quan đợt này |

`migrations/versions/0400_kb_real_estate.py` **không** nằm trong bảng trên: câu *"`documents`
KHÔNG CÓ CỘT `category` … phân biệt bằng `title`"* vẫn đúng nguyên vẹn sau đợt này — §4.2
làm đúng những gì nó nói.

File này là chỗ duy nhất truy ra được các lệch trên.
