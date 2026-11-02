# M4a — Dữ liệu BĐS (thiết kế)

> **Ngày:** 2026-08-02 · **Trạng thái:** chờ duyệt · **Repo:** `odyssey-portal-backend`
> **Chặn bởi:** M1 (`tenant_data.projects`/`units` · `field_policy_live` · `agent_api` · catalog test) ·
> M2a-BE (`require(action)` · `catalog.*`)
> **Chặn:** M9 bước 2 (*"nạp dữ liệu"*) · M10 cổng 1 (bootstrap đọc được gì) · demo có nội dung thật
> **Nguồn nghiệp vụ:** `DL_01` (Notion) · `work-packages-mvp.md` gói B · prototype `pform`/`uform`/`projects`/`domains`
> **Kiểm kê trường:** `specs/_m4a-kiem-ke-truong.md`

---

## 0. Spec này làm gì, không làm gì

Đưa hai bảng lõi `tenant_data.projects` và `tenant_data.units` từ *"vừa đủ để chứng minh cách ly"*
lên **đủ để agent tư vấn bằng dữ liệu thật của tenant**, cộng đường nạp dữ liệu hàng loạt và cơ chế
quyết định trường nào agent được đọc.

**Trong phạm vi:** migration `0400` (+4 cột `projects` · +22 cột `units` · +2 cột
`field_policy_live` · 4 bảng mới) · CRUD hai thực thể · ba cờ chính sách trường · gate 3 trường
thương mại · import CSV/XLSX hai bước · cảnh báo thiếu dữ liệu (BR07) · tắt dự án cho agent (BR11) ·
mở rộng view `agent_api` · **hợp đồng giao diện cho repo FE (§8)**.

Code FE nằm ở repo `odyssey-portal-frontend`, không thuộc repo này. §8 là **hợp đồng bàn giao** —
token, nếp đặt thành phần, và ba chỗ prototype lệch spec — không phải hướng dẫn thi công.

**Ngoài phạm vi — và vì sao:**

| Hoãn | Vì sao |
|---|---|
| **Media dự án** (ảnh · video · 8 danh mục · bản nhẹ · xem trước) | Hệ con riêng, `DL_02`, không dùng chung bảng hay API nào với M4a. Và `DL_02` còn **4 TODO chưa chốt** (ngưỡng dung lượng · wireframe chưa có · việc mới cho client phát video · chi phí băng thông) — gộp vào là để bốn cái đó chặn cả M4a. **Tách thành M4b.** 13 ô ảnh/video của prototype chuyển sang đó |
| **Ngưỡng độ tươi** (BR06 — *cấm khẳng định còn hàng khi dữ liệu quá hạn*) | Rào chắn này do **agent** cưỡng chế, không phải portal. M4a chỉ đóng dấu `updated_at` và lộ nó qua `agent_api`; luật hành vi thuộc M5 (rào chắn) và Gói G |
| **Lĩnh vực thứ hai** (Tài chính) | Quyết định #3 — ngoài MVP. Cơ chế `field_policy_live` đã theo `(entity, field)` nên thêm lĩnh vực là thêm dữ liệu, không sửa code |
| **Tự tạo thực thể mới** | BR14 chốt thẳng: *"không cho tự tạo thực thể mới ở MVP"*. Workspace chỉ khai thêm **trường** vào thực thể có sẵn, qua `extras` + `field_policy_live` |
| **Bảng lookup `unit_types`** | Xem §12 |

---

## 1. Vấn đề: bảng có nhưng gần rỗng

`0004_tenant_data_core.py` ghi thẳng trong header:

> *"M1 chỉ tạo cột LÕI — vừa đủ để 6 cổng test chứng minh cách ly hàng và gate cột.
> **M4 ALTER thêm cột cho `projects` và `units`. Đó là NGOẠI LỆ đã hẹn trước** của luật
> *module không sửa bảng của module khác* (spec tổng §4④)."*

Hôm nay:

| | Cột nghiệp vụ hiện có | Ô trên form prototype |
|---|---|---|
| `projects` | 14 | 35 |
| `units` | 19 | 49 |

Và **chưa code nào đọc `control.field_policy_live`** — `grep -rn field_policy src/` trả về rỗng.
Cơ chế gate cột của M1 đã xây xong nhưng chưa có ai đổ dữ liệu vào. M4a là người dùng đầu tiên,
nên nó cũng là người đặt seed.

Hệ quả nếu đấu nối agent trước M4a: pod bootstrap thành công, `SELECT` chạy sạch, và trả về một
căn hộ có 19 cột trong đó `field_policy_live` rỗng ⇒ `pol()` trả `false` cho mọi trường ⇒
**ba cột gated đều `NULL`**. Đúng cơ chế, vô dụng về nghiệp vụ.

---

## 2. Kiến trúc dữ liệu

### 2.1 "27 + 52" là số ô trên form, không phải số cột

Đây là chỗ dễ đánh giá sai nhất của gói B. Bóc từng nhóm của prototype:

| | Ô form | → M4b | → `overview` jsonb | → bảng con 1-N | bỏ | Ô còn lại | + không phải ô form | **Cột thật** |
|---|---|---|---|---|---|---|---|---|
| **Dự án** | 35 | 6 | 9 | 4 | 2 | 14 | 4 — `code` · `overview` · `extras` · `agent_enabled` | **18** |
| **Quỹ căn** | 49 | 7 | 0 | 0 | 2 | 40 | 1 — `extras` | **41** |

Cột *"không phải ô form"* là những thứ không có ô trên `pform`/`uform`: khoá `code`, hai cột chứa
(`overview`, `extras`), và `agent_enabled` — công tắc *Agent dùng* nằm ở **màn danh sách**, không
nằm trên form.

Ba đường thoát, mỗi đường một lý do:

- **`overview jsonb`** — cột này **đã tồn tại** ở `0004`, và prototype **tự ghi trên form**:
  *"Tổng quan · ghi vào `overview` jsonb — 11 khoá"*. Chín ô của nhóm đó (`scale` · `units_text` ·
  `density` · `area_summary` · `product` · `ownership` · `ownership_type` · `apartment_standard` ·
  `description`) là văn bản mô tả — không ô nào được lọc hay sắp xếp.
- **Bảng con 1-N** — `location_highlights[]` (*"5 điểm"*), `project_progress` (*"9 mốc"*),
  `project_documents` (*"6 tài liệu"*). Prototype gọi ba cái sau là *"ba editor dạng list"*.
  Nhóm lặp lại thì tách bảng; đó là lực đẩy duy nhất được phép tách ở đây.
- **Bỏ** — `seo_title` · `seo_description` (Odyssey không xuất bản web công khai; di sản CMS
  website cũ) và `lat_p` · `lng_p` trên `units` (trùng `projects.lat`/`lng`, suy được bằng join).

### 2.2 Vì sao KHÔNG tách `units` thành `unit_prices` / `unit_policies`

Một căn hộ thật sự có ~39 thuộc tính **vô hướng**. Tách chúng ra là tách 1-1, và trong hệ này nó
đắt hơn ở nơi khác vì ba lý do cụ thể:

1. **Đường đọc của agent phải là một lượt.** `DL_01` mục Hiệu suất: *"Truy vấn căn nằm trên đường
   trả lời khách, kể cả cuộc gọi — một lượt đọc, không nhiều chặng."*
2. **Mỗi bảng mới trong `tenant_data` là một bề mặt cách ly mới** — phải gọi
   `enforce_tenant_isolation()`, phải khai vào catalog, cổng 6 của M1 quét mọi PR. Tách 1-1 nhân
   số bề mặt lên mà không thêm nghĩa nào.
3. **View `agent_api` là definer và tự lọc tenant trong `WHERE`.** Join hai bảng trong definer view
   nghĩa là **hai** mệnh đề `WHERE tenant` — quên một cái là rò, và không có lỗi nào báo.

Bảng rộng chỉ sai khi cột là **nhóm lặp lại** (⇒ tách 1-N, §2.1 đã làm) hoặc **thưa theo loại**
(⇒ jsonb, `overview`/`extras` đã làm).

### 2.3 Tham chiếu theo mã tự nhiên, không theo id nội bộ

Prototype tham chiếu bằng `project_id` · `unit_type_id` · `parent_id` · `sale_id`. `0004` đã chọn
khoá tự nhiên `(tenant_id, code)` và `units.project_code text`. **M4a theo `0004`:**

| Prototype | M4a | Vì sao |
|---|---|---|
| `project_id` | `project_code text` *(đã có)* | Đổi lại là đổi luôn index `units_tenant_project_idx` và cột `project_code` của `agent_api.units` |
| `parent_id` | `parent_code text` self-FK | File CSV tham chiếu dự án mẹ bằng mã người đọc được, không bằng số nội bộ |
| `unit_type_id` | `unit_type text` *(đã có)* | Xem §12 — bảng lookup hoãn có điều kiện |
| `sale_id` | `sale_email text` | `tenant_data` trỏ FK sang `control.users` là hướng phụ thuộc mới mà RLS của `units` không phủ. Lưu email là đủ cho MVP |

Lợi ích dồn về một chỗ: **file import mở bằng Excel là đọc được và sửa được.**

```csv
code,project_code,unit_type,status,direction,price_ty,area_m2,bedrooms
NT2-1408,VOP2,Sky Villa 4PN,available,Đông Nam,5.62,78.4,4
```

### 2.4 Migration `0400_bds_full_fields.py`

| Bảng | Thay đổi |
|---|---|
| `tenant_data.projects` | **+4**: `parent_code` · `sort_order` · `is_featured` · `agent_enabled` |
| `tenant_data.units` | **+22**: `investor` · `zone` · `building` · `bathrooms` · `price_label` · `price_tttd_vnd` · `price_loan_vnd` · `loan_info` · `is_hot` · `hot_sort` · `delivery_standard` · `floor_min` · `floor_max` · `axis` · `front` · `check_time` · `description` · `is_active` · `sort_order` · `sale_email` · **`lat` · `lng`** |
| `control.field_policy_live` | **+2**: `form_visible` · `required_for_agent` — **ngoại lệ §4④, xem §3.2** |
| `tenant_data.project_highlights` | mới · 1-N · `(tenant_id, project_code, sort_order, text)` |
| `tenant_data.project_progress` | mới · 1-N · mốc tiến độ, ảnh + link |
| `tenant_data.project_documents` | mới · 1-N · chỉ link, không lưu tệp |
| `tenant_data.import_jobs` | mới · `state` · `report jsonb` · `file_sha256` · `expires_at` — xem §5 |

Cả 4 bảng mới gọi `control.enforce_tenant_isolation()` và **phải khai vào catalog** theo
`isolation.md §6.0`; thiếu một khai báo là **cổng 6 của M1 đỏ**, và đó là hành vi mong muốn.

**Tiền vẫn là `bigint` VND.** Ba cột giá mới (`price_tttd_vnd` · `price_loan_vnd`) mang hậu tố
`_vnd` như hai cột đã có. Không cột nào tên `*_ty`. Prototype ghi trên form *"đơn vị giá: tỷ đồng"* —
đó là đơn vị **nhập**, đổi ở biên (§4.3).

### 2.5 Ba chỗ phải nói rõ, nếu không người sau đọc `0004` sẽ tưởng M4a vi phạm

**(a) `building` và `floor` — có cột, KHÔNG mở bộ lọc.**

`0004` cấm tạo `tower` và cấm seed `floor` là filterable, vì bộ lọc theo tầng/toà **trả sai âm
thầm**: `schemas.py` khai hai filter đó cho LLM, `nbx_mongo.search_units` không đọc chúng, nên khách
hỏi *"căn tầng 14"* thì nhận căn tầng bất kỳ và agent đọc như thể đúng.

Prototype lại có ô **Toà** (`building`) và **Phân khu** (`zone`) trên form. Hai việc này không mâu
thuẫn, vì `BR04` tách đúng chỗ: *"một trường chỉ được bật cờ **agent lọc được** khi dữ liệu thật có
giá trị cho trường đó"*. Nên:

> **Tạo cột để tenant nhập. Seed `filterable = false`. Cổng test 8 canh.**
> Đổi `filterable` sang `true` là **quyết định có dữ liệu**, không phải quyết định có cột.

**(b) `floor` · `building` · `zone` LÊN view `agent_api`, khác `0004`.**

`0004` để `floor` ngoài view kèm ghi chú *"M4 quyết định lại khi có dữ liệu thật"*. M4a quyết định:
đưa cả ba lên view ở dạng **đọc được, không lọc được**. Lý do: cái sai âm thầm nằm ở **lọc**, không
ở **đọc** — agent đọc *"Toà S2.03"* rồi nói lại cho khách là đúng.

⚠️ **Điều kiện của quyết định này là `BR03`** (bỏ khoá rỗng). Chưa có `BR03` thì một `floor` chưa
điền tới LLM dưới dạng `floor: null`, và model có thể diễn giải bừa. Xem §6.2 — `BR03` là mục hợp
đồng cho Gói G, không phải việc portal làm được một mình.

**(c) `agent_enabled` không phải `status`.**

`BR11`: dự án tắt *Agent dùng* thì **không xuất hiện trong bất kỳ kết quả nào** trả cho agent —
*"kể cả khi khách gọi đích danh tên dự án đó"*. `status` (`draft`/`published`) là trạng thái biên
tập, khác việc. Hệ quả kỹ thuật ở §6.1.

---

## 3. Ba cờ chính sách trường

### 3.1 Hai cờ đã có, thiếu một

`control.field_policy_live` (`0002_control_core.py:72`) đã có:

```
tenant_id · entity · field · is_core · agent_readable · filterable · match_op
          · label_vi · type · enum_values
```

`BR01` đòi **ba cờ độc lập**: *hiện trên form* · *agent đọc được* · *agent lọc được*. Cờ 2 và 3 có
sẵn (`agent_readable`, `filterable`). Cờ 1 chưa có. `BR07` còn cần cờ thứ tư: trường nào tính vào
định nghĩa *"đủ dữ liệu cho agent"*.

### 3.2 Thêm hai cột vào bảng của M1 — ngoại lệ, khai tường minh

```sql
ALTER TABLE control.field_policy_live
  ADD COLUMN form_visible       boolean NOT NULL DEFAULT true,
  ADD COLUMN required_for_agent boolean NOT NULL DEFAULT false;
```

Đây là **sửa bảng của module khác**, luật §4④ cấm. Khai ngoại lệ theo đúng nếp `0004` đã khai cho
`projects`/`units`, và ba điều làm nó an toàn:

1. **Chưa code nào đọc bảng này** ngoài `portal.pol()` và `portal.gated_extras()`.
2. **Cả hai hàm đó chỉ đọc `agent_readable` và `is_core`** — thêm cột không đổi một dòng nào của
   `0005_agent_api.py`.
3. Cả hai cột có `DEFAULT`, nên hàng đang có không cần backfill.

Phương án thay thế — bảng `vertical_field_template` riêng — bị loại vì nó tạo **hai chủ cho một
khái niệm** và bắt phải định nghĩa luật trộn (*tenant tắt cờ mà template bật thì ai thắng?*), trong
khi MVP mới có đúng một lĩnh vực. Đúng cái spec tổng §5.5 cảnh báo.

### 3.3 Bốn cờ, và ai đặt chúng

| Cờ | Ai đặt | Đọc ở đâu |
|---|---|---|
| `form_visible` | platform seed → tenant đè | FE dựng form |
| `agent_readable` | platform seed → tenant đè | `portal.pol()` · `portal.gated_extras()` — **Postgres cưỡng chế** |
| `filterable` + `match_op` | platform, có điều kiện dữ liệu (BR04) | tool schema của agent (M5 · Gói G) |
| `required_for_agent` | **BA** | `/data-gaps` (BR07) |

Ba trường thương mại `commission` · `bank_support` · `csbh_full` seed `agent_readable = false`.
`BR09` gọi việc lộ chúng là *"sự cố thương mại thật, không phải tính năng phụ"* — và nó được cưỡng
chế ở **tầng đọc**, không phải bằng câu dặn trong prompt.

---

## 4. Import CSV/XLSX

### 4.1 Hai bước, không thoả hiệp

`BR08`: *"**không bao giờ ghi mà chưa qua bước xem trước.** Báo cáo phải hiện số dòng sẽ XOÁ. Chế độ
Thay thế toàn bộ cần xác nhận riêng. Ghi là một giao dịch cả-hoặc-không."*

```
① POST /imports            (multipart: file, entity, mode)
     ├─ đọc file → list[dict]                     ← HÀM THUẦN
     ├─ đổi đơn vị giá                            ← HÀM THUẦN
     ├─ kiểm từng dòng → BaoCaoChayThu            ← HÀM THUẦN
     ├─ lưu file: tenants/<id>/imports/<job_id>   ← core/storage.py (M3)
     └─ INSERT import_jobs (state='cho_xac_nhan', report, file_sha256, expires_at)
   ⇒ trả job_id + {them: N, sua: M, xoa: K, loi: [{dong, ly_do}...]}
   ⇒ CHƯA GHI GÌ vào projects/units

② POST /imports/{job_id}/apply  {file_sha256, xac_nhan_xoa?, so_dong_se_xoa?}
     ├─ sha lệch ⇒ 409, không ghi gì
     ├─ mode='thay_the_toan_bo' ⇒ đòi xac_nhan_xoa=true VÀ so_dong_se_xoa khớp report
     ├─ MỘT transaction: UPSERT + DELETE
     └─ state='da_ap_dung' · audit_log
```

### 4.2 Vì sao lưu file thay vì để FE gửi lại

Không lưu thì file gửi ở bước ② **có thể khác** file đã chạy thử ở bước ①. Người dùng xác nhận
*"xoá 3 dòng"* và hệ thống ghi một file xoá 300 dòng — không có gì bắt được. Đúng thứ `BR08` sinh ra
để chặn.

Lưu file cho thêm ba thứ: nhật ký `BR13` có chỗ neo bằng chứng thật · file 5.000 dòng không phải
upload hai lần · job quá hạn dọn bằng worker `jobs` của M1, không cần cơ chế mới.

### 4.3 Đổi đơn vị giá — một hàm thuần, ba đường gọi

```python
# modules/realestate/gia.py — HÀM THUẦN, không I/O
def doi_don_vi_gia(nhap: str | float | None) -> int | None:
    """Nhận giá người dùng nhập bằng TỶ, trả bigint VND. '5,62' -> 5_620_000_000"""
```

Form · import · seed đều gọi **hàm này**, không chỗ nào tự nhân `1e9`. `BR05` nói lý do:
*"tuyệt đối không đổi đơn vị ở tầng đọc — đó là cách sinh ra lỗi giá sai hệ số một tỷ"*, và agent đã
phải sửa đúng bug đó một lần.

---

## 5. Kiến trúc code

```
src/portal/modules/realestate/
  gia.py          doi_don_vi_gia()                      ← HÀM THUẦN
  nhap_lieu.py    bytes -> list[dict] -> BaoCaoChayThu  ← HÀM THUẦN
  chinh_sach.py   ba cờ · suy trường thiếu (BR07)       ← HÀM THUẦN
  contracts.py    pydantic v2
  repo.py         SQL asyncpg thô
  service.py      CRUD · chay_thu() · ap_dung()
  router.py       endpoint, mỗi cái khai action
migrations/versions/0400_bds_full_fields.py
tests/fixtures/import/*.csv, *.xlsx     ← file thật, không mock
```

Ba hàm thuần theo đúng nếp `bundle.render()` (M3) và `parse.py`/`chunk.py` (M6): phần **nhiều biến
thể và dễ sai nhất** phải test được mà không cần Postgres, MinIO hay worker.

**`nhap_lieu.py` không chạm DB.** Nó nhận `bytes` + tập cột hợp lệ, trả `BaoCaoChayThu`. Việc so với
dữ liệu đang có (để biết dòng nào *sửa*, dòng nào *xoá*) do `service.py` làm. Ranh giới này là lý do
test được 20 biến thể file hỏng trong vài trăm mili-giây.

**Vì sao module mới chứ không nhét vào `config`:** `config` sở hữu payload cấu hình agent (M3/M5).
Dữ liệu BĐS là thực thể nghiệp vụ, vòng đời khác, người gọi khác. Hai chủ cho một module là đúng cái
lỗi M5 §9 đã tránh.

---

## 6. Đường đọc của agent

### 6.1 View `agent_api` phải mang hai mệnh đề tenant

`BR11` bắt dự án tắt biến mất khỏi **mọi** kết quả — kể cả kết quả tra căn:

```sql
CREATE OR REPLACE VIEW agent_api.units AS
SELECT u.code, u.project_code, u.unit_type, u.status, u.direction,
       u.zone, u.building, u.floor, u.bedrooms, u.bathrooms,     -- §2.5(b)
       u.price_vnd, u.price_tts_vnd, u.price_tttd_vnd, u.price_loan_vnd,
       u.area_m2, u.area_build_m2, u.fund_type, u.is_hot,
       u.csbh_brief, u.gift, u.legal, u.delivery_standard, u.loan_info,
       u.description, u.check_time,
       CASE WHEN portal.pol('unit','commission')   THEN u.commission   END AS commission,
       CASE WHEN portal.pol('unit','bank_support') THEN u.bank_support END AS bank_support,
       CASE WHEN portal.pol('unit','csbh_full')    THEN u.csbh_full    END AS csbh_full,
       portal.gated_extras('unit', u.extras) AS extras,
       u.updated_at
  FROM tenant_data.units u
 WHERE u.tenant_id = portal.current_tenant()          -- ① cách ly hàng
   AND u.is_active
   AND EXISTS (SELECT 1 FROM tenant_data.projects p
                WHERE p.tenant_id = portal.current_tenant()   -- ② BR11, KHÔNG được quên
                  AND p.code = u.project_code
                  AND p.agent_enabled);
```

Mệnh đề ② là chỗ dễ quên nhất trong toàn bộ M4a, vì view là **definer** nên RLS của owner không áp
— thiếu nó thì không có lỗi nào, chỉ có dự án đã tắt vẫn được agent nhắc tới. Cổng test 3 canh.

### 6.2 `BR03` (bỏ khoá rỗng) không làm được ở phía portal — đây là mục hợp đồng

`BR03`: *"trường không có giá trị thì bỏ hẳn khoá khỏi kết quả"*. Hiện **7 trên 18 khoá luôn rỗng**,
gần 40% payload.

Nhưng agent **đọc thẳng `agent_api` qua DSN**, không đi qua API của portal (kiến trúc M10 ④). Một
SQL view trả về tập cột cố định — nó không "bỏ khoá" được. Nên `BR03` phải cưỡng chế ở chỗ nó thực
sự hỏng: **`_serialize.py` của `santa-hotline-agent`**.

> **G-11 (bổ sung cho hợp đồng Gói G):** serializer bỏ mọi khoá có giá trị `NULL`/rỗng trước khi
> đưa vào ngữ cảnh của LLM. Đây là **điều kiện** để `floor`/`building`/`zone` được lên view (§2.5b).
>
> **G-12:** gỡ hai filter `floor` và `tower` khỏi `schemas.py` của kỹ năng tra căn (quyết định #17 ·
> BR04 · BR15). Portal seed `filterable = false`, nhưng tool schema là artefact của repo agent.

### 6.3 `BR07` — cảnh báo thiếu dữ liệu, đọc từ dữ liệu chứ không từ code

`GET /data-gaps` đọc `field_policy_live WHERE required_for_agent` rồi dựng mệnh đề `WHERE` đếm số
căn thiếu. **Tên trường phải lọc qua danh sách cột thật của bảng trước khi ghép vào SQL** — dữ liệu
trong bảng chính sách là đầu vào không tin được, và ghép thẳng là lỗ SQL injection.

Đổi định nghĩa *"đủ dữ liệu"* là `PATCH /field-policy`, **không deploy lại**. Cổng test 9 canh.

---

## 7. API

Không cần action mới — `catalog.read` · `catalog.write` · `catalog.delete` đã có ở
`core/auth/actions.py` (dòng 7·8·9 của PQ_01) và phủ đúng *"Dự án · Quỹ căn"*.

| Method | Đường | Action |
|---|---|---|
| `GET` `POST` | `/projects` | `catalog.read` · `catalog.write` |
| `GET` `PATCH` | `/projects/{code}` | `catalog.read` · `catalog.write` |
| `DELETE` | `/projects/{code}` | `catalog.delete` |
| `GET` `POST` | `/units` | `catalog.read` · `catalog.write` |
| `GET` `PATCH` | `/units/{code}` | `catalog.read` · `catalog.write` |
| `DELETE` | `/units/{code}` | `catalog.delete` |
| `GET` | `/data-gaps` | `catalog.read` |
| `GET` `PATCH` | `/field-policy/{entity}[/{field}]` | `catalog.read` · `catalog.write` |
| `POST` | `/imports` | `catalog.write` |
| `POST` | `/imports/{job_id}/apply` | `catalog.write` |
| `GET` | `/imports/template` | `catalog.read` |

Đường trong router viết tương đối; tiền tố do `api/app.py` gắn — một chỗ duy nhất, theo `auth.md`.
Phân trang cursor. Module raise `LoiPortal`, không tự trả JSON.

### Hình dạng lỗi (DL_01 §II.4)

| Mã | HTTP | Khi nào |
|---|---|---|
| `ER_01` | 422 | Thiếu trường bắt buộc — nói rõ trường nào |
| `ER_02` | 422 | Giá không phải số — kèm ví dụ định dạng |
| `ER_03` | 422 | File thiếu cột bắt buộc — liệt kê cột thiếu, **không ghi gì** |
| `ER_04` | 422 | Có dòng lỗi trong file — **không dòng nào được ghi** |
| `ER_05` | 500 | Lỗi chung |
| `ER_06` | 422 | Trùng mã căn trong cùng dự án — **không tự chọn dòng nào thắng** (BR10) |

Thêm một mã ngoài `DL_01`, cho luồng hai bước:

| Mã | HTTP | Khi nào |
|---|---|---|
| `IMPORT_JOB_STALE` | 409 | `file_sha256` không khớp job · job hết hạn · job đã áp dụng rồi — **một mã cho cả ba**, và cả ba đều không ghi gì |

---

## 8. Giao diện — hợp đồng cho repo `odyssey-portal-frontend`

FE nằm ở repo khác, nên mục này là **hợp đồng bàn giao**, không phải hướng dẫn thi công. Nguồn
style: prototype `design/Tenant Portal.dc.html`, hai màn `projects` và `pform`.

> **Style là ràng buộc, nội dung thì không.** Bố cục, token, và nếp đặt thành phần theo prototype;
> danh sách trường theo §2 của spec này. Chỗ nào hai thứ lệch nhau — §8.4 ghi rõ — thì **spec thắng**.

### 8.1 Bốn màn, hai màn có prototype

| Màn | `data-screen` | Prototype | Ghi chú |
|---|---|---|---|
| Danh sách Dự án / Quỹ căn | `projects` | ✅ | hai tab trong cùng một màn |
| Form dự án | `pform` | ✅ | |
| Form quỹ căn | `uform` | ✅ | 7 nhóm, theo **đúng nếp `pform`** — không thiết kế lại |
| Quản lý lĩnh vực | `domains` | ✅ | M4a chỉ dùng phần *Bất động sản*, thu gọn |
| **Import** | — | ❌ | Prototype **không vẽ**. `DL_01` mục 3 mới có bảng thành phần, wireframe nằm trong TODO của nó. Xem §8.5 |

### 8.2 Token nền — lấy từ prototype, không đặt mới

| | Giá trị |
|---|---|
| Font | `'Be Vietnam Pro', system-ui, sans-serif` |
| Chữ chính | `#14161a` |
| Viền | `#e7e5e0` |
| Mặt phẳng | `#fff` trên nền giấy ấm (canvas hơi ngả vàng, **không** phải `#f5f5f5` xám) |
| Nhấn | `--ac` xanh lá đậm · `--acs` bản nhạt dùng cho nền mục nav đang chọn |
| Bo góc | ô nhập ~8px · thẻ ~12px |
| Sidebar | rộng 250px, nền trắng, `border-right`, `position: sticky` |

Tiêu đề nhóm trong sidebar (`VẬN HÀNH` · `KIẾN THỨC` · `CẤU HÌNH`) là chữ hoa nhỏ, giãn ký tự, màu
xám nhạt. Mục đang chọn: nền `--acs`, chữ `--ac`, `font-weight: 600`. Badge số bên phải, màu câm.

Dùng primitives `components/ui/` (shadcn) đã có; **không thêm thư viện UI thứ hai**.

### 8.3 Nếp lặp lại — bốn thứ đáng chép nguyên

**(a) Mã trường hiện cạnh nhãn, kiểu chữ mono xám.**

```
Tên dự án *  name              Slug  slug
Miền *  area_region            Chủ đầu tư  investor
```

Nhìn thì lạ với một sản phẩm cho người dùng cuối, nhưng nó phục vụ đúng một việc rất thật: **đó là
tên cột trong file CSV import**. Người nhập liệu nhìn form là biết cột nào trong file mẫu ứng với ô
nào — không phải tra tài liệu. Giữ.

**(b) Nhóm trường là thẻ có số thứ tự + ghi chú kỹ thuật.**

```
01  Thông tin chung
02  Tổng quan     ghi vào overview jsonb — 11 khoá
```

Số là mono xám nhạt, ghi chú bên phải tiêu đề cũng vậy. Cho người dùng cảm giác form có cấu trúc
thay vì đổ một mạch — đúng yêu cầu `DL_01` mục Giao diện/UX.

**(c) Chip trạng thái nhiều màu, mỗi màu một nghĩa.**

`indexed` xanh nhạt · `draft` xám · `48 thiếu dữ liệu` hổ phách. Hổ phách **luôn** là *cần người
làm gì đó*, không phải lỗi. Pill cảnh báo trên đầu màn (`● 48 căn chưa đủ dữ liệu cho agent`) dùng
cùng màu hổ phách đó — cùng một nghĩa thì cùng một màu.

**(d) Công tắc là ô có viền, có nhãn chữ.**

Không phải toggle trần. Prototype vẽ một hộp có viền, nhãn trường phía trên, bên trong là chữ
`Đang bật` / `Đang tắt` cộng switch. Chữ quan trọng hơn switch — người dùng đọc trạng thái, không
phải đoán màu.

### 8.4 Ba chỗ prototype lệch spec — spec thắng

| # | Prototype | Spec M4a | Vì sao |
|---|---|---|---|
| 1 | Cột **AGENT DÙNG** hiện chip `indexed`/`draft`/`48 thiếu dữ liệu` | Phải là **công tắc bật/tắt** (`agent_enabled`) | `DL_01` mục 3 khai rõ *"Toggle · Agent dùng · bật tắt từng dự án cho agent"*, và `BR11` bắt dự án tắt biến mất khỏi mọi kết quả. Prototype đang trộn **trạng thái** với **công tắc** — hai thứ khác nhau (§2.5c). Đề nghị: tách hai cột, hoặc một cột công tắc + một chip trạng thái nhỏ bên cạnh |
| 2 | Nhãn trường chỉ có mã kỹ thuật | Cần thêm **hai nhãn** `DL_01` yêu cầu: *Agent dùng trường này* và *Không chia sẻ với khách* | `DL_01` mục 3: *"không đánh dấu thì người nhập điền đều tay, tốn công vào trường agent không đọc"*. Hai nhãn này đọc từ `field_policy_live` (`agent_readable`, và `false` trên ba trường thương mại) — **không hardcode** |
| 3 | `pform` có nhóm **SEO** (`seo_title` · `seo_description`) và các ô ảnh | Bỏ SEO; ảnh sang M4b | §2.1 |

Chi tiết 1 và 2 là chỗ prototype **thiếu**, không phải chỗ nó sai — nó vẽ trước khi `DL_01` chốt.

### 8.5 Màn Import — chưa có prototype, dựng theo `DL_01` mục 3

Ba bước trên **cùng một màn**, không phải wizard nhiều trang:

```
① Dropzone Tải file CSV hoặc XLSX  + link tải file mẫu
   Radio Chế độ:  ◉ Thêm và cập nhật    ○ Thay thế toàn bộ     ← mặc định trái

② Bảng Kết quả chạy thử
   Thêm  128     Cập nhật  40     XOÁ  3      Lỗi  2 dòng
                                  ↑ in đậm, màu cảnh báo, cỡ chữ lớn hơn ba số kia
   Danh sách dòng lỗi kèm lý do từng dòng

③ [Huỷ]  [Áp dụng]      ← chế độ Thay thế: popup riêng, nói rõ số bản ghi sẽ bị xoá
```

`DL_01 BR08` nói thẳng vì sao số **XOÁ** phải nổi bật hơn ba số còn lại: prototype của màn danh sách
có dòng *"sửa hàng loạt tại đây ghi đè toàn bộ danh sách"* — người dùng đã được hứa một thao tác
phá huỷ, nên số dòng sẽ mất phải là thứ mắt nhìn thấy trước tiên. **Không được apply mà không hiện
nó.**

Trạng thái rỗng của mỗi danh mục/danh sách viết theo nếp `DL_02`: nói **hệ quả**, không báo lỗi —
*"Chưa có căn nào — agent sẽ không tư vấn được dự án này"*, không phải *"Không có dữ liệu"*.

### 8.6 Cấu trúc thư mục FE

```
odyssey-portal-frontend/src/
  features/realestate/
    nav.ts            ← đã có từ M2a-FE, khai requiredActions: ['catalog.read']
    api.ts            ← client gọi §7
    contracts.ts      ← mặt tiền công khai, module khác import cái này
    components/
      BangDuAn.tsx · BangQuyCan.tsx
      NhomTruong.tsx      ← thẻ 01 Thông tin chung, dùng lại cho pform+uform
      OTruong.tsx         ← nhãn + mã mono + hai nhãn chính sách (§8.4-2)
      ChipTrangThai.tsx
      HopThoaiImport.tsx
  routes/_app/{projects,pform,uform,domains}.tsx   ← 4 route rỗng đã có từ M2a-FE
```

`NhomTruong` và `OTruong` dùng chung cho cả `pform` lẫn `uform` — đó là lý do §8.1 nói *không thiết
kế lại `uform`*. Hai form khác nhau ở **dữ liệu mô tả trường** (đọc từ `field-policy`), không ở
component.

`features/realestate/` chỉ import `lib/`, `components/`, `i18n/`. Cần thứ của module khác thì import
`features/<khác>/contracts` — canh bằng eslint boundary rule và `tests/module-boundaries.test.ts`.

---

## 9. Mười một cổng test

| # | Cổng | Đỏ khi nào | File |
|---|---|---|---|
| 1 | RLS trên 4 bảng mới — A không `SELECT` được hàng của B | Quên `enforce_tenant_isolation()` | `test_cach_ly_bang_moi.py` |
| 2 | `field_policy` tắt ⇒ `agent_api.units.commission` **IS NULL**; bật ⇒ có giá trị | Gate cột thương mại thủng — BR09 | `test_gate_truong.py` |
| 3 | `agent_enabled=false` ⇒ `agent_api.units` của dự án đó trả **0 hàng** *(không chỉ `agent_api.projects`)* | Thiếu mệnh đề ② §6.1 — BR11 | `test_tat_du_an.py` |
| 4 | Nhập `"5,62"` qua **form**, qua **import**, qua **seed** ⇒ cả ba ra `5_620_000_000`. Và quét động: không cột nào tên `*_ty` | Lỗi hệ số một tỷ quay lại — BR05 | `test_doi_don_vi_gia.py` |
| 5 | `apply` với file **khác** file đã chạy thử ⇒ `409`, DB **không đổi một hàng** | Xác nhận một đằng ghi một nẻo — BR08 | `test_import_hai_buoc.py` |
| 6 | Một dòng lỗi trong 500 dòng ⇒ **0 hàng** được ghi | Cả-hoặc-không thành một phần — BR08 | `test_import_hai_buoc.py` |
| 7 | Trùng mã căn trong cùng file ⇒ `ER_06`, không tự chọn dòng thắng | BR10 | `test_import_trung_ma.py` |
| 8 | **Quét động** mọi hàng `filterable=true`: phải là cột thật của bảng **và** có `match_op`. `floor`·`building`·`zone` phải `filterable=false` | Mở bộ lọc cho trường không có dữ liệu — BR04, quyết định #17 | `test_bo_loc_co_du_lieu.py` |
| 9 | Đổi `required_for_agent` bằng API ⇒ `/data-gaps` đổi theo, **không deploy lại** | BR07 bị hardcode | `test_canh_bao_thieu_du_lieu.py` |
| 10 | Catalog test của M1 xanh sau `0400` — 4 bảng mới đều khai | Bảng mới quên bật cách ly | *(cổng 6 của M1, chạy sẵn)* |
| 11 | **Quét động** router: mọi `POST`/`PATCH`/`DELETE`/`apply` đều ghi `audit_log` | BR13 im lặng biến mất khi ai đó thêm endpoint | `test_nhat_ky_day_du.py` |

Cổng 4, 8 và 11 là **cổng quét động**, cùng hạng với cổng 5/6 của M1: chúng bắt được người thêm cột
`price_ty` hoặc thêm endpoint không ghi nhật ký sáu tháng nữa. Ba cổng còn lại chỉ chứng minh code
hôm nay đúng.

---

## 10. Việc kéo theo

- `scripts/seed_bds.py` — seed `field_policy_live` cho lĩnh vực Bất động sản (59 hàng = 18 + 41) + vài dự án
  và quỹ căn mẫu. **Đây là chỗ đặt bộ trường mẫu của platform** (BR01).
- `make dev-seed` gọi thêm `seed_bds.py`.
- `docs/contracts/isolation.md §6.0` — khai 4 bảng mới vào catalog.
- `docs/contracts/dau-noi-agent.md` — thêm **G-11** và **G-12** (§6.2). Nếu M10 chưa ship, ghi tạm
  vào spec M10 §7.
- File mẫu CSV/XLSX tải về (`GET /imports/template`) — sinh từ cùng danh sách cột mà
  `nhap_lieu.py` chấp nhận, không phải một file tĩnh commit vào repo.
- Repo `odyssey-portal-frontend`: `features/realestate/` hiện mới có `nav.ts`; bốn route
  `projects` · `pform` · `uform` · `domains` đã có từ M2a-FE nhưng rỗng. **Hợp đồng giao diện ở §8**
  — kèm ba chỗ prototype lệch spec (§8.4) và màn Import chưa có wireframe (§8.5).
- Một test ở repo FE canh §8.4-2: hai nhãn *Agent dùng trường này* / *Không chia sẻ với khách*
  phải suy từ dữ liệu `field-policy` trả về, **không** từ danh sách cứng trong component. Cùng tinh
  thần `nav-registry.test.ts` của M2a-FE: vỡ luật là CI đỏ, không phải review bắt.

---

## 11. Ranh giới với module khác

| Module | Quan hệ |
|---|---|
| **M4b** (media) | Nhận 13 ô ảnh/video của prototype. Khoá nối là `project_code`, không phải id. Spec riêng |
| **M10** (đấu nối agent) | M4a **không** chặn M10, và M10 **không** chặn M4a. Nhưng bootstrap trước M4a thì pod đọc được một bảng gần rỗng, rồi phải sửa view + seed và chạy lại cổng 1 của M10 ⇒ **thứ tự đề nghị: M4a trước** |
| **M5** (Agent Studio) | 12 tool toggle của M5 gồm `search_units` · `check_inventory` · `list_projects`. Cờ `filterable` của M4a quyết định tool schema có filter nào. Nối bằng `contracts/tools.json` (commit `f7d54e8`) |
| **M9** (Onboarding) | Bước 2 *"nạp dữ liệu — import file hoặc nhập 1 dự án mẫu"* chính là `POST /imports` + `POST /projects` của M4a |
| **M7** (Vận hành) | Màn *Cần bổ sung* (`gaps`) thuộc M7, khác `/data-gaps` của M4a: M7 là *khách hỏi mà agent không trả lời được*, M4a là *trường bắt buộc chưa điền* |

---

## 12. Còn treo

- **N2 — định nghĩa *"đủ dữ liệu cho agent"*.** Trường nào bắt buộc trên Dự án và trên Căn. Việc của
  BA cùng sales, không phải của dev. **Chặn con số của BR07, không chặn màn hình** — M4a ship cơ chế
  (`required_for_agent`) và một seed đề xuất; đổi bằng `PATCH /field-policy`.
- **Ba cờ cho từng trường** của bộ trường mẫu BĐS — y hệt: seed đề xuất, BA đè lên bằng dữ liệu.
- **Bảng lookup `unit_types`.** Hoãn để giữ import CSV đơn giản. Điều kiện mở lại: nếu dữ liệu thật
  cho thấy cùng một loại căn bị gõ nhiều biến thể (*"Sky Villa 4PN"* / *"SkyVilla 4PN"* / *"SV 4PN"*)
  thì `search_units` lọc theo `unit_type` sẽ trả thiếu — lúc đó bảng lookup rẻ hơn việc dọn dữ liệu.
- **`sale_email` chưa nối `control.users`.** Lưu chuỗi, chưa kiểm người đó còn là thành viên
  workspace không. Nối được sau M2b mà không đổi cột.
- **`fake.py` — nợ chung, không phải của M4a.** Spec tổng §4② yêu cầu mỗi module ship `fake.py`,
  nhưng `modules/kb/` và `modules/config/` hiện **không có**. M4a theo hiện trạng; khôi phục cơ chế ②
  là một việc riêng cho cả ba module, không nên để M4a gánh một mình.
- **Ngưỡng độ tươi BR06** (giờ / ngày / tháng cho ba nhóm) — chưa chốt, và thuộc phía agent. M4a chỉ
  đóng dấu `updated_at` và `check_time`.
