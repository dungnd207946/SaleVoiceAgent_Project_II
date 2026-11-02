# Gộp phân khu vào `tong_quan` + dọn payload Qdrant

**Ngày:** 2026-08-19 · **Repo:** `odyssey-portal-backend` (ghi) → `odyssey-agent` (đọc)
**Chạm:** `modules/kb` · `modules/realestate` · `modules/ingest` · `docs/contracts/payload-qdrant.md`

## 1. Vấn đề — đo trên dữ liệu sản xuất

`zones` là một `EntitySpec` riêng với `doc_type="phan_khu"`, nên mỗi phân khu thành một doc,
một `record_id`, ít nhất một point.

Đo trên `aina_2` / `CE9F4363_74CE_491D_8032_E0210D2C50B5` (Vinhomes Global Gate Hạ Long),
6 phân khu, `category`/`product_scale`/`overview` **rỗng hết**:

```
tong_quan#426  len=84
phan_khu#284   len=28   "## Phân khu\nVịnh Bình Minh 2"
phan_khu#285   len=28   "## Phân khu\nVịnh Bình Minh 1"
phan_khu#286   len=28   "## Phân khu\nVịnh Bình Minh 2"    ← trùng #284
phan_khu#288   len=35   "## Phân khu\nThiên Đường Nhiệt Đới 1"
phan_khu#290   len=28   "## Phân khu\nVịnh Bình Minh 1"    ← trùng #285
phan_khu#300   len=35   "## Phân khu\nThiên Đường Nhiệt Đới 1"  ← trùng #288
```

Sáu vector 28–35 ký tự, ba cặp giống hệt nhau. `ChunkSpec.min_chars = 300` tồn tại đúng để
chống mảnh vụn cỡ này, nhưng nó chỉ gộp được **trong một doc** — sáu phân khu là sáu doc nên
nó bất lực. Toàn collection `aina_2_documents`: 35 point cho 12 dự án, trong đó 21 point là
`phan_khu`.

## 2. Quyết định

| | Quyết định |
|---|---|
D1 | Bỏ `doc_type = "phan_khu"`. Phân khu trở thành một khối trong doc `tong_quan` của dự án cha |
D2 | Khối phân khu là **một point RIÊNG**, không trộn chung point với quick-fact của dự án |
D3 | Payload `<tenant>_documents` bỏ `section`, `section_path`, `page` — còn 11 khoá |
D4 | Ghép **mọi** phân khu bất kể `status` |
D5 | Gộp phân khu có khối render **giống hệt nhau** |
D6 | `category` đi vào text bằng **nhãn tiếng Việt**, không phải mã enum thô |

### D2 — vì sao ranh giới point phải đến từ ĐỘ SÂU đường dẫn

Đã thử ba bố cục, chỉ một cái tách được **chắc chắn**:

| Bố cục | Dữ liệu thật (6 zone rỗng) | Seed (2 zone đủ field) |
|---|---|---|
`### <tên>` mỗi phân khu dưới `## Phân khu` | **1 point** (dán lại) | 2 point |
`## Thông tin chung` bọc quick-fact + `## Phân khu` phẳng | **1 point** (dán lại) | **1 point** (dán lại) |
`## Cơ cấu sản phẩm` › `### Phân khu` + bullet | 2 point | 2 point |

Hai bố cục đầu bị `_gop_manh_vun()` dán lại: khối phân khu ngắn hơn `min_chars` **và**
`_cung_cha()` coi đường dẫn rỗng `()` là cùng cha với mọi đường dẫn cấp 1. Bố cục thứ ba
thoát vì đường dẫn **sâu 2 cấp** — không khớp mệnh đề nào trong bốn mệnh đề của `_cung_cha()`.

Tính bền đã đo: 0 / 1 / 6 / 40 phân khu × `min_chars` ∈ {0, 300, 600} — **12/12 ca tách sạch**,
không ca nào lẫn quick-fact vào point phân khu. Ranh giới không phụ thuộc cỡ chunk, nên chỉnh
`min_chars` sau này không âm thầm dán hai point lại.

⚠️ Từ có nghĩa phải ở **cấp cuối** (`### Phân khu`, không phải `### Danh sách`): `_tien_to()`
lấy `section_path[-1]` làm tiền tố nhúng, và agent lấy nó làm tiêu đề khối.

### D1 — tên phân khu phải là NỘI DUNG, không phải tiêu đề

`chunker._tach_khoi()` chỉ phát ra một khối khi section có **thân**; một `###` trần bị đẩy
khỏi ngăn xếp `cho` khi `###` kế tiếp tới và **mất hẳn**. Phân khu thật chỉ có tên, mọi field
khác rỗng — bố cục "mỗi phân khu một `###`" xoá sạch phân khu khỏi index trên chính dữ liệu
sản xuất. Nên tên đi vào bullet.

## 3. Hình dạng text và point

Một doc `tong_quan` cho mỗi dự án, cấu trúc:

```
## <nhãn field 1>
<giá trị>
…                              ← 11 quick-fact như hôm nay, KHÔNG đổi

## Cơ cấu sản phẩm
### Phân khu
- **<tên phân khu>** — Loại hình: <nhãn> · Quy mô: <product_scale>
  <overview>
- **<tên phân khu 2>** …
```

Bỏ khối `## Cơ cấu sản phẩm` khi dự án không có phân khu nào — không sinh section rỗng.

### Output thật — `aina_2` / Vinhomes Global Gate Hạ Long: 7 point → 2

```
▸ point[0]  uuid5("tong_quan:426:0")  section_path=[]  len=84
  ## Khu vực
  Tỉnh Quảng Ninh

  ## Chủ đầu tư
  Vinhomes

  ## Quy mô sản phẩm
  2000 sản phẩm

▸ point[1]  uuid5("tong_quan:426:1")  section_path=["Cơ cấu sản phẩm","Phân khu"]  len≈120
  ## Cơ cấu sản phẩm
  ### Phân khu
  - **Vịnh Bình Minh 1**
  - **Vịnh Bình Minh 2**
  - **Thiên Đường Nhiệt Đới 1**
```

Ba dòng chứ không sáu — D5 gộp ba cặp trùng.

Chuỗi thật đem nhúng cho point[1] (tiền tố do `_tien_to()` gắn):

```
Vinhomes Global Gate Hạ Long — Phân khu

## Cơ cấu sản phẩm
### Phân khu
- **Vịnh Bình Minh 1**
…
```

### Output — seed `Noble Palace Long Biên`: 3 point → 2

```
▸ point[1]  section_path=["Cơ cấu sản phẩm","Phân khu"]
  ## Cơ cấu sản phẩm
  ### Phân khu
  - **Phân khu River Villas** — Loại hình: Biệt thự · Quy mô: 120 căn đơn lập
    Phân khu biệt thự ven sông, view trực diện mặt nước.
  - **Phân khu Park Row** — Loại hình: Liền kề · Quy mô: 260 căn liền kề
    Phân khu liền kề mặt công viên trung tâm dự án.
```

Dự án nhiều phân khu tách tự nhiên: 40 phân khu đủ field → 1 point tổng quan + 5 point phân
khu, cả 5 cùng `section_path`.

Quy mô: `aina_2_documents` **35 point → ~14**.

## 4. Thay đổi theo file

### 4.1 `kb/contracts.py` — `ChildBlockSpec`

```python
@dataclass(frozen=True, slots=True)
class ChildBlockSpec:
    table: str
    name_col: str
    section: str          # "Cơ cấu sản phẩm"
    subsection: str       # "Phân khu"
    fields: tuple[str, ...]
    field_labels: Mapping[str, str]
    value_labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    anchor_col: str = "project_code"
```

`EntitySpec` mọc thêm `child_block: ChildBlockSpec | None = None`. Máy móc ở `query`/`reader`/
`resolve` đọc spec, không biết chữ "Phân khu" — giữ tính vertical-agnostic.

### 4.2 `kb/directive/verticals/real_estate.py`

Bỏ `EntitySpec(table="zones", doc_type="phan_khu", …)`. `embed_sources` còn `projects` +
`documents`. Spec `projects` khai:

```python
child_block=ChildBlockSpec(
    table="zones",
    name_col="name",
    section="Cơ cấu sản phẩm",
    subsection="Phân khu",
    fields=("category", "product_scale", "overview"),
    field_labels={"category": "Loại hình", "product_scale": "Quy mô"},
    value_labels={"category": PROJECT_TYPE_LABELS},
),
```

`overview` không có nhãn — nó xuống dòng thụt, không đi vào dòng fact inline.

### 4.3 `realestate/contracts.py` — `PROJECT_TYPE_LABELS` (D6)

Từ điển `mã → nhãn` cho `_LoaiHinhDuAn` (6 giá trị). Đặt ở mặt tiền `realestate` vì enum là
của module đó; `kb` import qua `portal.modules.realestate.contracts` — hợp Luật 3, và không
tạo vòng import (`realestate/__init__.py` rỗng, `contracts.py` không import `kb`).

Hôm nay nhãn tiếng Việt chỉ tồn tại ở `odyssey-portal-frontend/src/features/realestate/enums.ts`
(bản chép tay). Bản backend là bản thứ hai; cổng chống lệch ở §8.

`category` `NULL` (dữ liệu thật có) ⇒ bỏ vế đó khỏi dòng fact.

### 4.4 `kb/source/query.py` + `reader.py`

Thêm `read_child_rows_sql(vertical, spec)`:

```sql
SELECT <name_col>, <fields…>
  FROM tenant_data.<table>
 WHERE tenant_id = portal.current_tenant() AND <anchor_col> = $1
 ORDER BY id
```

Bắt buộc mang `_CACH_LY`. Không lọc `status` (D4). `reader.read_child_rows()` trả `list[dict]`.

`read_record()` cho spec anchor gọi thêm câu này và gắn vào `row["children"]`.

### 4.5 `kb/directive/resolve.py::build_text`

Sau vòng ghép field, nếu spec có `child_block` và có hàng con thì nối khối. Dựng dòng:

```
- **<name>** — <nhãn>: <giá trị đã dịch> · <nhãn>: <giá trị>
  <overview>
```

Bỏ vế rỗng. **Gộp trùng (D5): loại dòng có khối render byte-identical**, giữ thứ tự lần đầu
xuất hiện. Hai phân khu cùng tên nhưng khác field thì **giữ cả hai** — đó là hai hàng khác
nhau thật.

### 4.6 `kb/ops/enqueue.py::dat_viec_nap` — một chỗ duy nhất

`entity == "zones"` ⇒ tra `projects.id` theo `project_code` (đã là tham số sẵn có) rồi xếp
job `entity="projects"` với id đó. UI (`realestate/router.py::_enqueue_index`) và API
(`ingest/chieu.py::_xep_nap`) đều đi qua hàm này, nên hai đường giống nhau **theo cấu trúc**
chứ không nhờ chép đúng hai lần.

Không tìm thấy dự án cha ⇒ không xếp gì và ghi `log.warning`; hàng mồ côi không được làm
gãy lô nạp.

### 4.7 Đường purge

`realestate/router.py::_enqueue_purge_zone` và `ingest/chieu.py::_xep_purge(entity="zone")`:
thay purge point của zone bằng **nạp lại dự án cha**. **Giữ nguyên** vế cascade purge media
neo vào zone — nó không liên quan tới thay đổi này.

### 4.8 `kb/clients/rag.py` + `kb/index/store.py` (D3)

Bỏ 3 khoá khỏi `payload`. `store.doi_ten_trong_text()` không còn `section_path` để dựng lại
tiền tố cũ ⇒ đọc thẳng dòng đầu của `text`:

```python
head, sep, body = str(pl.get("text") or "").partition("\n\n")
if not sep or not (head == old_name or head.startswith(f"{old_name} — ")):
    missed += 1
    continue
await set_payload(text=f"{new_name}{head[len(old_name):]}\n\n{body}")
```

Chặt hơn bản cũ: không còn giả định `section_path` đồng bộ với `text`, mà so thẳng vào chuỗi
sắp ghi đè, và giữ nguyên văn phần đuôi ` — <mục>`.

`chunker` **không đổi** — `Chunk.section_path` vẫn cần cho việc gom nhóm; chỉ payload bỏ nó.

## 5. Hợp đồng payload — 11 khoá

Bằng chứng cho D3: quét **136 point thật** trên `aina_2` · `an_phu_land` · `nobles_homes` ·
`hanoi` — **136/136** có `text` mở đầu **đúng bằng** `"<project_name> — <section_path[-1]>"`.
`_tien_to()` gắn nhãn đó vào mọi chunk trước khi nhúng, kể cả mảnh thứ 2, 3 của một đoạn văn
dài (chỗ duy nhất dòng `##` không được lặp). Ba khoá `section`, `section_path`, `text` nói cùng
một chuyện; `page` thì hardcode `0` từ ngày đầu.

```json
{
  "project_id": "CE9F4363_74CE_491D_8032_E0210D2C50B5",
  "project_name": "Vinhomes Global Gate Hạ Long",
  "record_id": 426,
  "doc_type": "tong_quan",
  "text": "Vinhomes Global Gate Hạ Long — Phân khu\n\n## Cơ cấu sản phẩm\n### Phân khu\n- **Vịnh Bình Minh 1**\n…",
  "content_hash": "6f1f91a5…",
  "updated_at": "2026-08-18T03:17:11.929822+00:00",
  "status": "published",
  "file_public_url": "",
  "file_name": "",
  "thumb_url": ""
}
```

`doc_type` còn `tong_quan` · `csbh` · `phap_ly` · `huong_dan` · `khac` — vẫn **rời nhau** theo
bảng nguồn, nên vị từ xoá của `delete_by_record` giữ nguyên tính đúng và
`tests/modules/kb/test_doc_type_roi_nhau.py` chỉ bớt một giá trị.

### Thứ tự deploy: không cần chia pha

Khác vụ khoá `status` (mệnh đề lọc fail-closed, đảo pha ⇒ RAG câm). Ở đây agent
`kb_service_adapter._section()` mất `section_path` thì trả `""`, tiêu đề khối rút từ
`[Dự án › Mục]` xuống `[Dự án]` — **thoái hoá êm**, và nhãn mục vẫn nằm trong `text` mà agent
render ngay bên dưới. Portal bỏ trước, agent dọn `_section()` lúc nào cũng được.

Hệ quả phụ duy nhất: `_dinh_kem` lấy nhãn tệp theo `file_name or _section(h) or "Tài liệu"` —
mất vế giữa. Không đổi gì trên thực tế: `file_name` luôn có (suy từ `title` khi cột rỗng).

## 6. Dọn dữ liệu cũ

`handle_sync_project` **chỉ xếp job nạp, không dọn point mồ côi** — đã kiểm. Thiếu bước này
thì 21 point `phan_khu` của `aina_2` sống vĩnh viễn và agent vẫn tra thấy chúng.

CLI một lần `python -m portal.cli.drop_zone_points` (mặc định **thử khô**, theo nếp
`ma_hoa_bi_mat_cu`), mỗi tenant:

1. xoá mọi point `doc_type == "phan_khu"` trong `<slug>_documents`
2. `DELETE FROM tenant_data.kb_index_state WHERE entity = 'zones'`
3. xếp `kb_index` cho **toàn bộ** `projects` của tenant

Bước 3 bắt buộc: cấu trúc text đổi ⇒ `content_hash` đổi ⇒ point cũ của `tong_quan` cũng phải
được ghi lại.

Là CLI chứ không phải job định kỳ: đây là di trú một lần, không có nhịp nào để lặp.

## 7. Đánh đổi đã chấp nhận

**Nội dung nháp lộ ra khách.** D4 ghép mọi phân khu bất kể `status`, và point `tong_quan` chỉ
mang **một** `status` — của dự án. Dự án `published` + phân khu `draft` ⇒ nội dung nháp tới
khách, không mệnh đề lọc nào chặn được. Trước đây phân khu có point riêng mang status riêng
nên agent lọc được. Đây là bước lùi **có chủ ý**, người yêu cầu đã chọn sau khi được nêu.

Nếu sau này muốn đóng: lọc `status = 'published'` ở §4.4 — đổi lại thì publish/unpublish một
phân khu sẽ đổi text của dự án ⇒ đổi `content_hash` ⇒ nhúng lại doc dự án, trong khi hôm nay
publish chỉ cập nhật payload.

**Point phân khu có thể rất ngắn** (≈120 ký tự trên dữ liệu thật) — dưới `min_chars = 300`,
đúng thứ ngưỡng đó tồn tại để tránh. Chấp nhận vì D2 là yêu cầu tường minh, và đổi lại một
truy vấn "dự án có những phân khu nào" nhận được vector tập trung thay vì một vector bị 11
quick-fact pha loãng.

## 8. Test

| Bài | Khẳng định |
|---|---|
`test_child_block_tach_point_rieng` | 0/1/6/40 phân khu × `min_chars` ∈ {0,300,600} — khối phân khu luôn ở point riêng, không point tổng quan nào chứa chữ phân khu |
`test_phan_khu_khong_field_van_vao_index` | Zone chỉ có tên (ca sản xuất) vẫn xuất hiện trong text — cổng chống lỗi heading-trần-bị-bỏ |
`test_gop_phan_khu_trung` | Ba cặp trùng của `aina_2` ra ba dòng; cùng tên khác field thì giữ cả hai |
`test_nhan_loai_hinh_khop_enum` | `set(PROJECT_TYPE_LABELS) == set(get_args(router._LoaiHinhDuAn))` — cổng chống lệch từ điển |
`test_dat_viec_nap_zones_thanh_projects` | Xếp job cho `entity="zones"` ra job `entity="projects"` của cha; gọi từ cả hai đường cho ra job giống nhau |
`test_doi_ten_khong_co_section_path` | `doi_ten_trong_text` đổi đúng tiền tố khi `section_path` rỗng **và** khi có đuôi ` — Phân khu`; dòng đầu không khớp thì đếm vào `missed`, không ghi |
`test_payload_11_khoa` | Payload đúng 11 khoá, không còn `section`/`section_path`/`page` |
`test_doc_type_roi_nhau` | Cập nhật: bỏ `phan_khu` |
`test_hop_dong_khop_schema` (ingest) | Không đổi — `zones` vẫn là bảng nạp được, chỉ thôi là nguồn embed riêng |

Cổng cách ly: câu SQL mới ở §4.4 phải mang `_CACH_LY`, và `make test-isolation` không được thêm dòng đỏ nào so với baseline trước đợt này.

## 9. Ngoài phạm vi

- `enums.ts` phía FE vẫn là bản chép tay thứ ba. Cổng parity BE↔FE là việc riêng.
- `aina_3`/`aina_slug_test` có `external_id` là uuid nhưng `project_code` là slug —
  `ung_vien_ma()` không thể sinh ra chuỗi đó từ uuid, nên `external_id` đã bị đổi bằng đường
  ngoài `ON CONFLICT` sau khi hàng được tạo. Không chặn việc gì hôm nay; ghi lại để không ai
  kết luận `project_id` Qdrant lệch với FE là bug.
