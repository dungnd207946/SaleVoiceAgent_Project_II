# Cổng nạp dữ liệu ngoài — thiết kế

> Chốt 2026-08-14. Frontend đã thi công xong (`odyssey-portal-frontend`, màn con
> `/projects?nap=1`).
>
> **Backend: §3–§7 ĐÃ THI CÔNG** — migration `0927`·`0928`·`0929`·`0930`·`0931`,
> `modules/ingest`, 146 bài test. Chi tiết những gì lệch so với bản thiết kế đầu
> tiên nằm ngay trong từng mục, đánh dấu «đo được».
>
> **2026-08-15: tái cấu trúc lõi**, theo review
> `odyssey-qa/reviews/2026-08-15-review-ingest.md` (đóng finding #1–#14; #15 đã
> đóng ở đợt `0930`) — hàng đợi `projected_at` bị BỎ, chiếu chuyển sang đồng bộ
> per-record trong savepoint; §3.1/§4.1/§6.1/§6.2/§9 dưới đây phản ánh quyết
> định MỚI, không phải bản 08-14 gốc.

---

## 1. Bài toán

Tenant đã có hệ thống riêng — CRM, ERP, web bán hàng — chứa sẵn dự án · phân khu ·
quỹ căn. Câu hỏi: đưa dữ liệu đó vào `tenant_data` để agent trả lời được.

**Hướng đầu tiên đã thử và bỏ:** Odyssey viết adapter cho từng API của từng
khách. Không tổng quát hoá được, và chỗ vỡ không phải tên trường — mà là **giao
thức**: mỗi nơi một kiểu xác thực, một kiểu phân trang, một kiểu báo lỗi, một
cách biết cái gì vừa đổi. Phần đó không có mẫu số chung.

**Hướng thứ hai đã thử và bỏ:** vỏ cố định + ruột tự do (`attributes` JSONB) +
bảng ánh xạ trường theo tenant, cấu hình bằng giao diện. Nó giải được vấn đề tên
trường, nhưng đẩy việc map sang cho quản trị workspace ngồi bấm tay và đẻ ra một
tập phép biến đổi phải bảo trì. **Đừng dựng lại nó.**

## 2. Quyết định nền

| # | Quyết định | Hệ quả |
|---|---|---|
| 1 | **Khách ĐẨY sang mình**, không phải mình kéo về | Mọi phức tạp giao thức nằm ở phía họ |
| 2 | **Schema CỐ ĐỊNH** | Adapter dịch từ mô hình của họ là việc **bên họ viết, chạy ở phía họ**. Mình chỉ cung cấp đầu vào |
| 3 | **Trường lạ ⇒ bỏ qua im lặng**, không từ chối bản ghi | Hệ thống bên khách mọc thêm cột thì adapter của họ vẫn chạy |
| 4 | **Phiên bản trên đường dẫn** (`/v1/`), luật đổi: **chỉ thêm, không đổi tên, không bỏ** | N adapter ngoài kia đang code vào hợp đồng này |
| 5 | **Đẩy khi có thay đổi** | Kèm đối soát định kỳ — xem §7 |
| 6 | `external_id` của khách ≠ `project_code` của mình | Khách trỏ bản ghi con về cha bằng mã của **chính họ**; mình sinh `project_code` |
| 7 | **Tài liệu API = Swagger**, portal không chép lại | Bản chép tay không có cổng parity sẽ lệch, và dev bên khách viết adapter theo bản sai |

## 3. Hợp đồng HTTP

Nền đường dẫn: `/api/v1/ingest/{vertical}/{version}` — hiện `realestate/v1`.

Lĩnh vực nằm **trên đường dẫn**, không trong thân request: đó là thứ giữ lời hứa
«token của BĐS không với sang lĩnh vực khác» — nó không có đường gọi tới đường
dẫn của lĩnh vực đó.

### 3.1 `POST …/events` — nạp dữ liệu

Xác thực: `Authorization: Bearer <token>`. Xem §5.

```json
{
  "syncId": "erp-push-2026-08-14T09:12:33Z",
  "records": [
    {
      "entity": "unit",
      "externalId": "ERP-UNIT-88213",
      "op": "upsert",
      "occurredAt": "2026-08-14T09:12:33Z",
      "data": { "…": "trường của thực thể, xem §4" }
    }
  ]
}
```

**Vỏ bản ghi** — bốn trường, giống nhau ở cả năm thực thể:

| Trường | Kiểu | Bắt buộc | Ghi chú |
|---|---|---|---|
| `entity` | enum | ✓ | `project` · `zone` · `unit` · `document` · `media` |
| `externalId` | chuỗi | ✓ | Mã bản ghi **bên khách** — khoá duy nhất, không đổi theo thời gian |
| `op` | enum | ✓ | `upsert` · `delete` |
| `occurredAt` | ngày ISO | ✓ | Lúc thay đổi xảy ra **bên khách** |

⚠️ **`occurredAt` PHẢI mang múi giờ** (offset hoặc `Z`) — đổi 2026-08-15, review
finding #11. Giá trị **naive** bị từ chối `422` ngay ở tầng Pydantic
(`AwareDatetime`), không đi xa hơn. Lý do: asyncpg encode một `datetime` naive
theo **giờ HOST** của tiến trình đang chạy, không phải UTC và không phải giờ
khách gửi — và `occurredAt` chính là trọng tài của mọi thứ tự (idempotency lẫn
tie-break, §6.2 mục 2–3). Một trọng tài đổi nghĩa theo múi giờ của máy triển
khai (dev ở giờ VN, production ở UTC) là một nguồn lệch không grep ra được bằng
mắt — nó chỉ hiện khi hai môi trường xử lý cùng một payload ra hai thứ tự khác
nhau. Cùng luật áp cho `updatedAt` của bản kê (§3.2).

`syncId` tuỳ chọn, chỉ để lần vết một lô trong nhật ký.

**Trả về `202` kèm kết quả TỪNG bản ghi**, không phải một mã cho cả lô — một bản
ghi hỏng không được làm rớt 499 bản còn lại:

```json
{
  "accepted": 499,
  "rejected": 1,
  "results": [
    { "externalId": "ERP-UNIT-88213", "status": "accepted" },
    { "externalId": "ERP-UNIT-88214", "status": "rejected",
      "field": "priceVnd", "reason": "Phải là số, nhận được chuỗi \"4,85 tỷ\"" }
  ]
}
```

`field` rỗng ⇒ lỗi ở **cấp bản ghi** (thiếu trường vỏ, `op` sai), không cấp
trường. Giao diện phân biệt hai ca này.

**Lý do lỗi phải đủ để bên khách tự sửa** — đây là đường phản hồi duy nhất cho họ
dưới schema cố định. Nêu cả giá trị gây lỗi, và với enum thì liệt kê giá trị hợp
lệ ngay trong câu (`Giá trị "giu_cho" không hợp lệ — chỉ nhận available · booked
· sold`). Một câu «422 Unprocessable Entity» ở đây là vô dụng.

**Idempotent** theo `(tenant_id, entity, external_id)`. `occurredAt` **cũ hơn
hoặc bằng** bản đang có ⇒ bỏ qua, trả `status: "stale"`. Chống đẩy trùng và chống
sự kiện về lệch thứ tự — cả hai chắc chắn xảy ra khi khách đẩy theo thay đổi.

#### `?dryRun=true` — thử payload, không ghi gì

Chốt 2026-08-14. Cùng thân request, cùng toàn bộ đường validate, trả **cùng hình
dạng `results`** — chỉ bỏ bước ghi và không đụng `ingest_records`.

Dưới schema cố định, sai một tên trường là bản ghi bị từ chối — không còn ca
«trường lạ nằm chờ map» nữa. Không có `dryRun` thì dev bên khách chỉ có một cách
kiểm adapter: **ghi vào dữ liệu thật của chính họ rồi đọc bảng lỗi**. Đó là bắt
người ta lấy production làm môi trường thử.

Rẻ vì dùng lại nguyên đường validate. Ba ràng buộc:

- **Không** ghi `ingest_records` lẫn `ingest_errors` — một lần thử không được làm
  bẩn số liệu vận hành.
- **Có** kiểm tra token như thường: `dryRun` không phải cửa sau cho request không
  xác thực.
- Kiểm cả **quan hệ cha–con** ở mức có thể (`projectExternalId` đã tồn tại chưa),
  nhưng báo là *cảnh báo* chứ không phải lỗi — cha có thể tới sau (§6.2 mục 2).

### 3.2 `POST …/manifest` — bản kê đối soát

Cùng xác thực Bearer như `…/events`. Thân: `{ entity, records: [{ externalId, updatedAt }] }`.
Nó là nửa còn lại của «đẩy khi có thay đổi», không phải một tính năng phụ — §7.

```json
{ "soLech": 2, "soNghiMatTich": 1,
  "externalIdLech": ["ERP-U-88213", "ERP-U-88240"],
  "externalIdNghiMatTich": ["ERP-U-70001"] }
```

**Response CHÍNH LÀ yêu cầu đẩy lại.** `externalIdLech` là danh sách bên khách
gửi lại. Không có webhook gọi ngược: bản kê do họ gửi lên, nên họ đang đứng chờ
response này — dựng một callback sẽ cần một URL đăng ký, một cơ chế retry và một
cổng xác thực thứ hai, cho đúng một danh sách chuỗi.

**`422` nếu bản kê có `externalId` trùng, hoặc quá `TRAN_BAN_KE` (20.000 mục) —
trần của MỘT TRANG.** Cả hai kiểm TRƯỚC khi chạm dữ liệu — xem §7.

**Phân trang** (thêm 2026-08-15, mặc định = hành vi một trang): sắp theo
`externalId` **thứ tự byte**, mỗi trang kèm `afterExternalId` = mã lớn nhất **đã
gửi** ở trang trước, trang cuối kèm `isLastPage: true`. Chi tiết và bốn cái bẫy:
§8 mục 1.

### 3.3 Bốn endpoint quản trị (xác thực bằng **phiên portal**, không phải token)

| Đường dẫn | Trả về |
|---|---|
| `GET …/tong-quan` | `{ diemNap, docsUrl, thongKe: { nhanCuoiLuc, soNhan24h, soGhiDuoc24h, soHong24h }, tokens: [{ id, label, token }] }` |
| `POST …/keys` `{ label }` | `{ id, label, token }` — 201 |
| `DELETE …/keys/{id}` | 204 |
| `GET …/loi` | `{ loi: [{ id, entity, externalId, truong, lyDo, nhanLuc }] }` |

Cả bốn khai `require(ACTIONS.WORKSPACE_ADMIN)`.

⚠️ **`diemNap` và `docsUrl` do BACKEND trả về**, không ghép chuỗi ở FE — đường dẫn
docs là thứ backend biết về chính nó. `docsUrl` neo thẳng vào **operation** của
`POST …/events` trong Swagger, không phải trang docs chung.

## 4. Trường của `data`, theo thực thể

Tên trường **camelCase** (hợp đồng HTTP), map thẳng sang cột snake_case trong
`tenant_data` — xem `migrations/versions/0400_kb_real_estate.py` là nguồn sự thật.

- **`project`** — `name`✓ · `region` · `address` · `investor` · `developer` ·
  `category[]` · `salePhase` · `productScale` · `overview` · `amenities` ·
  `ownershipForm` · `handoverStandard` · `totalLandAreaM2` · `floorAreaM2` ·
  `buildDensityPct` · `totalInvestmentVnd` · `link360` · `status`
- **`zone`** — `projectExternalId`✓ · `name`✓ · `category` · `productScale` ·
  `overview` · `status`
- **`unit`** — `projectExternalId`✓ · `zoneExternalId` · `unitCode`✓ ·
  `saleStatus`✓ · **`productType`✓** · `priceVnd` · `pricePerM2Vnd` ·
  `direction` · `bedrooms` · `block` · `floor` · `numFloors` · `areaBuiltM2` ·
  `areaWallM2` · `areaLandM2` · `imageUrl` · `status`
- **`document`** — `projectExternalId`✓ · `title`✓ · `loai` · `body` · `fileUrl` ·
  `status`
- **`media`** — `projectExternalId`✓ · `mediaUrl`✓ · **`contentType`✓** ·
  **`category`✓** · `zoneExternalId` · `unitExternalId` · `caption` ·
  `fileName` · `status`

### 4.2 Bốn chỗ hợp đồng lệch khỏi trực giác (đo được lúc thi công)

Cả bốn tìm ra bằng cách đọc `0400_kb_real_estate.py`, và ba trong số đó bản nháp
FE đã ghi SAI:

| Chỗ | Sự thật |
|---|---|
| `link360` | Cột là **`link_360`** — có gạch dưới trước số |
| `media.contentType` | Chỉ nhận **`image` · `video` · `tour_360`** (`tour_360` từ `0929_media_tour_360`, đồng bộ 2026-08-15), KHÔNG phải MIME type. Bản nháp FE ghi «VD image/webp» |
| `media.category` | **Bắt buộc**, enum 7 giá trị (`tong_quan`…`tien_do`) — cột `NOT NULL` không DEFAULT. `csbh` RỜI danh mục ảnh từ `0927_tu_dong_nap_kien_thuc` (đồng bộ 2026-08-15): CSBH là một loại TÀI LIỆU — adapter gửi `entity: "document"` với `loai: "csbh"`, không phải một media |
| `unit.productType` | **Bắt buộc** — `NOT NULL` không DEFAULT. Không có giá trị nào mặc định được tử tế: `chung_cu` cho một lô biệt thự là bịa dữ liệu, và agent sẽ trả lời theo nó |
| `document.loai` | **KHÔNG phải cột.** Nó nhập vào `title` thành tiền tố (`kb.contracts.join_title`) — `"csbh"` + `"Bảng giá"` → `"CSBH — Bảng giá"` |

⚠️ Bốn chỗ này là lý do có cổng `tests/modules/ingest/test_hop_dong_khop_schema.py`:
nó đọc `information_schema` + `pg_constraint` của DB thật rồi so từng cột, từng
giá trị enum, và kiểm mọi cột `NOT NULL`-không-DEFAULT đều được khai bắt buộc.
Bản chép tay không có cổng canh sẽ lệch — repo này đã trả giá cho đúng lớp lỗi đó
hai lần (`lib/tools.ts`, fake MSW).

`status` tuỳ chọn, **mặc định `published`**: dữ liệu đã nằm trong ERP của khách là
dữ liệu thật. Muốn nạp mà chưa cho agent thấy thì gửi `draft`.

Enum lấy đúng `enums.ts`/`0400`: `saleStatus` ∈ `available|booked|sold` ·
`direction` ∈ 8 hướng · `productType` ∈ 12 giá trị · `status` ∈
`draft|published|archived`.

### 4.1 `zoneExternalId` của `unit` là TUỲ CHỌN (đảo quyết định, 2026-08-15)

Bản 2026-08-14 chốt **bắt buộc**, trích đúng schema đọc được lúc đó:

```sql
zone_code text NOT NULL,
CONSTRAINT units_tenant_zone_fk FOREIGN KEY (tenant_id, project_code, zone_code)
    REFERENCES tenant_data.zones (…) ON DELETE CASCADE
```

**Tiền đề đó đã CHẾT từ trước khi dòng trên được viết** —
`migrations/versions/0902_noi_zone_code_nullable.py` nới `zone_code` thành
nullable vì DB dùng chung với team agent có **3015/3015 hàng `units` với
`zone_code IS NULL`, và `zones` RỖNG**: phân khu là một tầng phân loại mà nguồn
dữ liệu của tenant đó không có, không phải một trường họ quên điền. Trích
docstring `0902`: *«Một cột NULL nói đúng sự thật "chưa biết"; một hàng bịa thì
nói sai»* — đúng lý lẽ đó, giờ áp cho `zoneExternalId`. `0902` cũng chỉ ra hình
dạng này đã có tiền lệ ngay trong schema: `media.zone_code` nullable với ĐÚNG
cùng FK tổ hợp, từ `0400`.

**FK không yếu đi.** Postgres mặc định MATCH SIMPLE cho khoá ngoại tổ hợp: chỉ
kiểm khi MỌI cột của nó non-NULL. `(tenant_id, project_code, NULL)` đi qua;
`(tenant_id, project_code, 'ZONE_BIA')` vẫn bị từ chối như trước — cổng
`test_fk_zone_van_chan_zone_code_bia` (viết cùng `0902`) canh đúng nửa đó.

**Vì sao cổng parity của chính module này
(`tests/modules/ingest/test_hop_dong_khop_schema.py`) không đỏ trước khi lệch
này bị phát hiện:** phép kiểm «mọi cột `NOT NULL` không `DEFAULT` phải được hợp
đồng khai bắt buộc» loại trừ một `tu_dien` các cột Portal tự điền lúc chiếu —
và `zone_code` đã nằm trong `tu_dien` đó **từ đầu**, nhưng vì một lý do hoàn
toàn khác: `zones.zone_code` (cột cùng tên, **bảng khác**) vẫn `NOT NULL` không
`DEFAULT`, tự sinh bởi `_ma_con_moi`, không phải trường khách gửi. Cổng parity
đọc TÊN CỘT, không phân biệt được `units.zone_code` với `zones.zone_code` đứng
sau cùng một chuỗi loại trừ — nên nó im lặng đúng ở chỗ lẽ ra phải kêu. Review
2026-08-15 finding #13.

Hai đường vòng bản 08-14 từng cân nhắc và loại — **cả hai hết cần thiết vì tiền
đề chính đã sai, không phải vì chúng dở**: sinh phân khu mặc định
(`__MAIN__`, vẫn đẻ ra một hàng `zones` ma nếu ai đó chọn hướng đó) và nới
`zone_code` thành nullable. Vế thứ hai **đã xảy ra thật** — chỉ là ở `0902`,
cho một lý do khác (dữ liệu thật của agent), không phải vì cổng nạp; cổng nạp
thừa hưởng nó miễn phí mà bản spec 08-14 không biết tới lúc viết.

⚠️ Bản ghi `unit` **không khai** `zoneExternalId`, hoặc khai một
`zoneExternalId` mà `zone` cha chưa tới, đều KHÔNG phải lỗi — vế sau vẫn đi qua
nhánh chờ cha bình thường (§6.2 mục 1), y hệt trước khi quyết định này đảo.
Chỉ khi bản kê đối soát cho thấy zone đó không bao giờ tới thì mới thành lỗi
(§7).

## 5. Token đẩy dữ liệu

Bảng mới `control.ingest_tokens`:

| Cột | Ghi chú |
|---|---|
| `id` | bigserial |
| `tenant_id` | FK `control.tenants` |
| `vertical` | `'realestate'` |
| `label` | ≤ 60 ký tự, **bắt buộc** — thứ duy nhất phân biệt hai token |
| `token` | chuỗi **THÔ**, không mã hoá — xem dưới |
| `token_sha256` | dùng để tra lúc xác thực |
| `created_by` · `created_at` | `last_used_at` đã **bỏ** ở `0930` — xem §8 |

**Quyền CỨNG, không cấu hình được:** đúng một `catalog.write`, đúng một cặp
(workspace, lĩnh vực). Token này **không** đọc được hội thoại, bản ghi thoại hay
cấu hình agent.

Nửa *workspace* của cặp đó do `tenant_id` trên chính hàng token bảo đảm. Nửa
*lĩnh vực* thì **phải được so tường minh**: `service.xac_thuc(..., vertical=…)`
đối chiếu `ingest_tokens.vertical` với lĩnh vực của endpoint đang gọi.

⚠️ Bản thi công đầu (2026-08-14) **thiếu đúng phép so đó**: `repo.tra_token` vẫn
`SELECT vertical` nhưng không handler nào đọc, nên `/ingest/<bất kỳ>/v1/events`
nhận mọi token còn sống. Nó vô hại chỉ vì `CHECK (vertical IN ('realestate'))`
khiến giá trị thứ hai chưa tồn tại — không phải vì code đúng. Bài học ghi lại vì
nó là một lớp lỗi lặp được: **đặt tên một ràng buộc lên đường dẫn không thi hành
nó.** Đường dẫn `/ingest/realestate/` khiến cả docstring lẫn spec đọc như thể
lĩnh vực đã bị chặn ở tầng định tuyến, trong khi tầng định tuyến chỉ so chuỗi
đường dẫn với chính nó.

Vá cùng ngày. `vertical` là tham số **bắt buộc, không mặc định** — một mặc định
nghĩa là router của lĩnh vực thứ hai copy-paste được nguyên dòng gọi và âm thầm
nhận phép kiểm của lĩnh vực thứ nhất. Hai bài canh: một so ở tầng hàm
(`vertical="finance"` ⇒ từ chối, viết được trước khi `finance` tồn tại), một quét
AST `router.py` đòi mọi lời gọi khai `vertical=LINH_VUC` chứ không phải chuỗi
viết tay lệch khỏi prefix.

⚠️ **KHÔNG dùng lại `control.agent_keys`.** Luật viết trong
`modules/enrollment/service.py` là *«api_key nói tôi là ai; credential nói tôi
được làm gì. Không gộp hai vai. api_key mở được ĐÚNG MỘT thứ»* — và cái một-thứ
đó là bộ credential của tenant, tức mật khẩu Postgres. Thêm vai nạp dữ liệu vào
chính khoá ấy là phá đúng luật đó, và tệ hơn: token đẩy **nằm trong hệ thống của
bên thứ ba**, còn khoá agent thì không.

**Xem lại được bất cứ lúc nào.** Khác `KhoaMoiDialog` của agent (chỉ hiện một
lần): giao diện hiện token tại chỗ trong bảng, che sẵn, bấm con mắt là mở. Vì thế
`token` lưu bản THÔ.

⚠️ **Mã hoá at-rest ĐÃ CÂN NHẮC VÀ BỎ ở increment này** — bản thiết kế đầu tiên
yêu cầu nó, và yêu cầu đó sai về thứ tự ưu tiên: `control.agent_keys.api_key` đã
lưu plaintext từ `0918`, và khoá đó **nguy hiểm hơn** — nó đổi được lấy
`/runtime-credentials`, tức mật khẩu Postgres của tenant. Mã hoá bảng mới rồi để
nguyên bảng nguy hiểm hơn là dời rủi ro chứ không giảm.

Mã hoá at-rest là một việc riêng và phải phủ **cả hai** bảng cùng lúc (§8).

⚠️ Kèm một khoảng hở đã biết: cổng `test_khong_cot_text_nao_chua_bi_mat` chỉ quét
`agent_keys`/`agent_credentials`, nên nó **không phủ** `ingest_tokens`. Ghi lại ở
`tests/isolation/test_isolation_catalog.py` cạnh mục khai bảng.

**Chỉ có XOÁ, không có thu hồi.** Không tồn tại trạng thái vô hiệu: một hàng «đã
thu hồi» hoặc còn giữ chuỗi thô (bí mật vô dụng nằm chờ rò) hoặc không giữ (hàng
rỗng không trả lời câu hỏi nào). `DELETE` xoá hàng. Ai xoá token nào là việc của
Nhật ký, không phải của bảng.

## 6. Đường dữ liệu

### 6.1 `tenant_data.ingest_records` — bản thô

Mọi bản ghi nhận được lưu nguyên payload (`jsonb`) kèm `entity` · `external_id` ·
`occurred_at` · `sync_id` · `received_at` · **`cho_cha_entity`/`cho_cha_ma`**
(thay `projected_at` — đổi 2026-08-15, xem dưới).

**Chiếu là ĐỒNG BỘ, ngay trong request đó, không phải một hàng đợi quét lại**
(đổi 2026-08-15, thay bản chạy trên cột `projected_at`). `projected_at` là
state machine của một hàng đợi chiếu trễ, và hàng đợi đó tự nó là nguồn của bốn
lớp bug đo được lúc review (finding #1 #3 #7 #8): hàng kẹt vĩnh viễn khi cha
không bao giờ tới, đánh-dấu-đã-chiếu dù chiếu vừa hỏng, starvation ở một `LIMIT`
quét, và lô này đè `projected_at` reset của lô khác. Lý do DUY NHẤT thật sự cần
một trạng thái chờ là «con tới trước cha» — nên trạng thái thay thế nó
(`cho_cha_entity`/`cho_cha_ma`, migration `0931_cho_cha`) nói ĐÚNG một điều đó
và không nói gì khác: bản ghi này đang chờ đúng bản ghi cha nào; `NULL` cả cặp
nghĩa là đã chiếu xong. CHECK `(cho_cha_entity IS NULL) = (cho_cha_ma IS NULL)`
chặn trạng thái nửa vời (chờ nhưng không rõ chờ ai); index MỘT PHẦN
`WHERE cho_cha_ma IS NOT NULL` giữ tập chờ nhỏ đúng thiết kế — tra thẳng những
con đang chờ MỘT cha cụ thể, không quét toàn bảng.

**Chiếu hỏng ⇒ savepoint rollback CẢ bản thô — không có trạng thái "nhận rồi
nhưng không bao giờ vào kho, không ai biết".** Lưu bản thô và chiếu chạy trong
MỘT savepoint cho từng bản ghi (§6.2 mục 1): một `except` bọc ngoài mà không có
savepoint chỉ đổi chỗ nổ, vì Postgres huỷ cả giao dịch ngay khi một câu lệnh bên
trong lỗi. Rollback nghĩa là bản đang lưu (nếu có) giữ nguyên `occurred_at` cũ —
khách sửa lỗi rồi đẩy lại NGUYÊN VĂN (cùng `occurredAt`) được nhận lại bình
thường, không có một cờ "đã từng nhận" nào đứng chặn đường.

Migration `0931` **XOÁ** mọi hàng còn `projected_at IS NULL` từ cơ chế cũ
(chưa chiếu xong) thay vì mang chúng sang cơ chế mới — một hàng "đã nhận,
chưa rõ số phận" không dịch được sang state machine mới mà không bịa dữ liệu.
Hàng bị xoá quay về đúng trạng thái «không tồn tại»: đối soát §7 sẽ báo
`nghi_mat_tich_tu` ở lượt bản kê kế tiếp, và khách đẩy lại được — mất một vòng
đối soát, không mất dữ liệu.

**`UNIQUE (tenant_id, entity, external_id)` — latest-wins, KHÔNG phải sổ
append-only.** Một sổ trả lời được «họ gửi gì lúc 9h sáng thứ Ba», nhưng giá là
một bảng lớn vô hạn cần chính sách lưu trữ riêng; câu người ta thật sự hỏi là
«HIỆN GIỜ họ đang gửi cái gì». Hệ quả phải biết: mất khả năng truy vết một giá
trị đã bị đè — lịch sử thay đổi là việc của Nhật ký.

**HAI lớp cách ly, cả hai bắt buộc** (không phải «RLS theo tenant» như bản thiết
kế đầu viết):
  1. RLS ở tầng DB — `0927` gọi `control.enforce_tenant_isolation` cho cả hai bảng.
  2. Vị từ `portal.current_tenant()` trong CHÍNH câu SQL, canh bởi cổng quét tĩnh
     `tests/isolation/test_loc_tenant_o_tang_app.py`.

Một lớp là một điểm chết — đó đúng là bài học của `0913`: agent uỷ thác lọc cho
RLS, `0909` rút sàn, và không có gì để grep ra.

**Vì sao giữ bản thô** dù schema đã cố định: hỗ trợ và chiếu lại. Khi khách hỏi
«tôi đã gửi cái gì», câu trả lời phải là dữ liệu chứ không phải suy đoán; và khi
mình sửa một lỗi projector, chiếu lại từ bản thô rẻ hơn gọi điện xin khách đẩy
lại 681 căn.

### 6.2 Projector

`ingest_records` → `projects`/`zones`/`units`/`documents`/`media`. Sáu quyết
định đổi hoặc thêm 2026-08-15, giữ nguyên số 4/8 (xoá mềm) và 8/8 (trường lạ)
từ bản gốc:

1. **Chiếu ĐỒNG BỘ, per-record, trong cùng savepoint với việc lưu bản thô**
   (thay hàng đợi `projected_at` — xem §6.1). Giải `externalId` → khoá nội bộ
   qua bảng tra `(tenant_id, entity, external_id) → (project_code | zone_code |
   unit id)`; lần đầu thấy một `project.externalId` thì **sinh `project_code`**
   (mình kiểm soát định dạng — nó đi vào SQL của agent và tên chunk trên
   Qdrant). Bản ghi con tới **trước** cha (thứ tự sự kiện không đảm bảo) ⇒ ghi
   địa chỉ cha còn thiếu vào `cho_cha_entity`/`cho_cha_ma` rồi nằm chờ — không
   từ chối, đó là chuyện bình thường của đẩy bất đồng bộ. **Đúng lúc cha đó
   chiếu xong**, service nhặt lại mọi con đang chờ ĐÚNG cha đó (qua index một
   phần) và chiếu **lan truyền**: zone mở khoá unit đang chờ nó, unit/zone mở
   khoá media đang chờ nó. Mọi câu SQL của MỘT lượt lan truyền chạy trong
   savepoint RIÊNG của lượt đó — một câu hỏng ở tầng lan truyền không được phép
   abort giao dịch NGOÀI của cả lô (§3.1: một bản ghi hỏng không được kéo lô).
   Ngân sách một lượt là `TRAN_LAN_TRUYEN = 2000` bản ghi con: vượt trần thì
   các con còn lại GIỮ NGUYÊN cờ chờ (vẫn an toàn — vẫn ở trạng thái "chờ cha")
   và service ghi MỘT dòng `ingest_errors` cho bản ghi CHA nói rõ cách tiếp
   tục — đẩy lại chính cha đó với `occurredAt` mới hơn để chạy tiếp lượt lan
   truyền. **Không có auto-resume nào được hứa** — một cascade vượt trần cần
   một cú đẩy lại tường minh từ khách, không phải một job nền âm thầm chạy nốt.

2. **Latest-wins nghĩa là THAY THẾ TRỌN BẢN GHI, không phải merge-từng-cột**
   (sửa finding #6). Ngữ nghĩa một câu: **bản ghi sau upsert phải Y HỆT bản ghi
   được INSERT MỚI từ cùng payload đó.** Cột hợp đồng không có mặt trong
   payload lần này KHÔNG giữ nguyên giá trị cũ — nó quay về **DEFAULT của
   chính cột đó trong DB** (`SET cột = DEFAULT` trong mệnh đề
   `ON CONFLICT DO UPDATE`; Postgres tự tra default hiện hành trong catalog,
   code không chép giá trị default nào vào tay nên không có một nguồn thứ hai
   có thể lệch khỏi migration khi ai đó đổi default sau này). Với cột nullable,
   DEFAULT là `NULL`; với cột có default nghiệp vụ, DEFAULT là giá trị đó —
   **không phải `NULL` trần cho mọi trường vắng mặt.** ⚠️ Cảnh báo cho adapter:
   `project.salePhase` vắng mặt trong payload ⇒ cột `sale_phase` quay về
   `'sap_mo_ban'` (default nghiệp vụ của `0400`), KHÔNG giữ phase đã ghi ở lần
   upsert trước — muốn giữ một phase đã đặt thì lần upsert SAU phải gửi lại nó.
   Bản merge-từng-cột cũ để `priceVnd: null` (giá rút khỏi thị trường) không
   bao giờ xoá được giá cũ — đúng bug đã đo.

3. **Tie-break khi hai bản ghi cùng `occurredAt`: `delete` THẮNG `upsert`**
   (tombstone thắng). Lý lẽ: một ERP điển hình export mỗi dòng theo
   `updated_at`, nên một `delete` và một `upsert` trùng đúng mốc là chuyện TỰ
   NHIÊN khi khách xoá một bản ghi rồi export lại đúng giây đó. Chiều ngược —
   một `upsert` cùng mốc với một `delete` đã lưu — KHÔNG hồi sinh bản ghi: hồi
   sinh cần một sự kiện MỚI HƠN, không phải cùng giờ. Đẩy lại y hệt (cùng
   `occurredAt`, cùng `op`) vẫn `stale` như luật idempotent gốc — tie-break chỉ
   can thiệp khi `op` khác nhau ở đúng cùng một mốc.

4. `op: delete` ⇒ **xoá mềm** bằng `status = 'archived'` (dùng lại đúng enum
   `status` mà `draft`/`published` đã dùng, không phải một cột `deleted_at`
   riêng), vì bản ghi có thể đã lên Qdrant và cần đường gỡ — xem mục 6.

5. **Media derive `public_url` LÚC CHIẾU**, không lúc khách gửi:
   `public_url = public_url_of(media_url)`, cùng hàm mà đường nhập tay
   (`realestate/router.py`) dùng. Thiếu bước này thì ảnh đẩy qua cổng nạp vô
   hình với agent — nó đọc `public_url`, không đọc `media_url` thô (finding
   #9).

6. **Mọi transition RỜI `published` qua ingest — `op:delete` HOẶC một `upsert`
   đổi `status` sang giá trị khác — enqueue `KIND_DELETE_INDEX`, đúng khuôn
   payload với đường xoá thủ công** (finding #5, khớp `_enqueue_purge_*` ở
   `realestate/router.py`): `project` purge theo `anchor_code` (cascade cả cây
   con trên Qdrant); `zone`/`document`/`media` purge theo `(entity,
   record_id)`. **`zone` cascade thêm mọi `media` neo vào nó** — worker KB chỉ
   tự cascade theo `anchor_code` (cấp `project`), KHÔNG theo `zone`; thiếu
   bước này thì media bị archived (ẩn khỏi agent) nhưng point Qdrant của nó
   sống sót, đúng lớp lỗi `NT2-1408`. **`unit` không purge gì** — `units` chưa
   từng lên RAG (§6.4), không có point nào để xoá.

7. **`unitExternalId` của `media` giải TRỌN địa chỉ ba cột từ CHÍNH bản ghi
   `unit`** (`project_code`/`zone_code`/`unit_code`), không lấy `project_code`
   từ payload của `media` rồi ghép riêng `unit_code` từ `unit` (finding #14) —
   hai nguồn khác nhau cho một khoá ngoại ba cột là đường cho một `media` trỏ
   `unit` của một dự án, trong khi `projectExternalId` khai trong `data` lại
   trỏ dự án khác; khoá ngoại tổ hợp khi đó nổ ở một chỗ khó đọc thay vì bị
   chặn ngay từ khâu giải cha.

8. Trường lạ trong `data` ⇒ bỏ qua, **không** ghi lỗi (quyết định #3).

### 6.3 `tenant_data.ingest_errors`

`entity` · `external_id` · `field` · `reason` · `received_at`. Là nguồn của
`GET …/loi` và là đường phản hồi cho bên khách.

### 6.4 Nối vào RAG

Projector ghi xong `projects`/`zones`/`documents`/`media` ⇒ đánh dấu
`kb_index_state` bẩn ⇒ job có sẵn (`modules/kb/jobs.py`) đẩy lên S3 + Qdrant.

`units` **không** ingest — agent lọc bằng SQL, đúng `docs/db-design/02c §1`. Nên
quỹ căn đẩy về là **dùng được ngay**, không chờ embed. Đây cũng là lý do
`saleStatus` là trường tươi nhất của cả hợp đồng.

## 7. Đối soát

«Đẩy khi có thay đổi» **sẽ** trôi dạt: mạng đứt, job bên khách chết, họ deploy,
một exception bị nuốt. Khi một sự kiện rơi, không ai biết — và nó rơi theo hướng
nguy hiểm nhất: căn đã bán vẫn nằm «còn hàng» ở phía mình, agent nói với khách là
còn. Đúng bug `NT2-1408`.

**Cơ chế:** khách đẩy bản kê nhẹ `{externalId, updatedAt}` cho một thực thể
(`POST …/manifest`). So hai chiều, mỗi chiều một cách xử lý hoàn toàn khác:

| Lệch | Nghĩa | Làm gì |
|---|---|---|
| Khách có, mình **thiếu hoặc cũ hơn** | Mình hụt một lần cập nhật | Trả mã về ⇒ họ đẩy lại. Không cần người |
| Mình có, **bản kê không có** | Nghi mất tích | Gắn cờ `nghi_mat_tich_tu`, ghi Nhật ký, **KHÔNG tự xoá** |

**Vì sao không tự xoá:** một `delete` bị rơi và một bản ghi khách thật sự xoá
trông **giống hệt nhau** ở phía mình. Đoán sai theo chiều xoá là mất dữ liệu
không lấy lại được; đoán sai theo chiều giữ lại là một hàng thừa mà ai đó nhìn
thấy và xử lý. Hai sai lầm không cùng hạng.

### 7.1 Ba cái bẫy, cả ba đã chặn

**Bản kê cắt dở.** Đây là bẫy lớn nhất của cả cơ chế: một bản kê thiếu làm **mọi
bản ghi không nằm trong đó** bị gắn cờ nghi mất tích. Nên bản kê phải ĐẦY ĐỦ cho
thực thể đó, và lô quá `TRAN_BAN_KE` bị **từ chối thẳng** thay vì nhận một nửa —
thà gãy to còn hơn âm thầm gắn cờ sai cho hàng nghìn hàng. Thông điệp lỗi nói
đúng lý do đó, không phải «payload quá lớn».

**`externalId` trùng trong bản kê.** Làm phép so ra kết quả tuỳ mục nào thắng —
không tái lập được. Từ chối, và từ chối TRƯỚC khi chạm dữ liệu.

**Bản ghi đã `delete`.** Không tính là mất tích: bản kê của khách đương nhiên
không liệt kê thứ họ vừa xoá. Tính nó sẽ tạo một cảnh báo cho đúng thứ đang chạy
đúng.

### 7.2 Cờ tự gỡ, và mốc giữ lần đầu

Bản ghi xuất hiện lại ở bản kê sau ⇒ cờ về `NULL`, không cần ai dọn tay. Nếu
không, một lần bản kê thiếu sót để lại cảnh báo vĩnh viễn và người trực học cách
bỏ qua chúng.

`nghi_mat_tich_tu` giữ mốc **lần đầu** bị nghi (`coalesce(…, now())`), không đè
mỗi đêm — nó trả lời «đã nghi bao lâu rồi», thứ quyết định có đi điều tra hay
không.

### 7.3 Cảnh báo đi đâu

**`control.audit_log`** (`hanh_dong = "ingest.nghi_mat_tich"`) — bảng mà màn
Nhật ký của portal đọc. Chỉ ghi khi có cờ **MỚI**: một bản ghi nghi mất tích ba
tuần liền mà đêm nào cũng sinh một dòng là cách dạy người trực bỏ qua chính dòng
đó. Khớp nhau hoàn toàn thì **im lặng**.

⚠️ **Giao diện quản trị workspace KHÔNG hiện kết quả đối soát** (chốt
2026-08-14). Bản dựng có một dòng báo và đã bỏ: phần lớn nội dung nó báo không
cần ai động tay, nên nó khoe cả lúc không có việc — đúng thứ luật của `/agent`
cấm (*«hiện nó thường trực là dạy người dùng bỏ qua chỗ đó, để rồi lúc nó thành
Mất kết nối thì không ai còn nhìn»*). Ngày bày lại thì bày **đúng phần cần
người**: bản ghi nghi mất tích, đọc từ `dang_nghi_mat_tich()`.

### 7.4 Ai bấm nút

**Bên khách.** Job đêm của họ POST bản kê; mình không có cron nào gọi sang họ.

Hệ quả phải biết: **khách không chạy job thì không có đối soát nào cả**. §7.5 là
nửa còn lại — thứ làm mình biết được điều đó.

### 7.5 Cảnh báo «tenant im lặng» — nhịp tim của adapter

Đối soát bảo vệ dữ liệu; mục này bảo vệ **đối soát**.

Vì bản kê do bên khách gửi lên, job của họ chết là §7 tắt — và tắt **im lặng**:
không lỗi, không request thất bại, không dòng nhật ký. Đó là chế độ hỏng tệ hơn
«chưa có đối soát»: không có thì ai cũng biết là không có; có mà chết âm thầm thì
người vận hành **tin** là đang được bảo vệ. Cơ chế dựng ra để chống hỏng-im-lặng,
mà bản thân nó hỏng đúng theo kiểu đó.

**Bản kê là một nhịp tim sẵn có, chỉ chưa ai ghi lại.** Hai loại im lặng khác hẳn
nhau, và đó là lý do mốc đo là bản kê chứ không phải `/events`:

| | Im lặng nghĩa là gì |
|---|---|
| Không có `/events` | **Mơ hồ** — có thể tuần này khách không sửa gì |
| Không có bản kê | **Không mơ hồ** — bản kê gửi bất kể có thay đổi hay không |

`tenant_data.ingest_manifest_runs` (`0929`) ghi mốc nhận theo `(tenant, entity)`.
Đóng dấu **TRƯỚC** phép so: dấu này trả lời «adapter còn sống không», và nó sống
bất kể kết quả so ra sao — đóng dấu sau thì một lỗi ở giữa làm một tenant *đang*
đối soát bị báo là im lặng.

Job đêm (`modules/ingest/jobs.py`) kêu khi **cả ba** đúng: tenant có dùng cổng nạp
(`ingest_records` không rỗng — workspace chưa đấu nối mà bị nhắc mỗi đêm là cách
nhanh nhất để người trực tắt kênh này) · quá `INGEST_IM_LANG_NGAY` (mặc định **3**
= chịu được hai lần lỡ) hoặc **chưa từng** gửi · và chưa có cảnh báo cho **đợt
này**.

**Một cảnh báo mỗi ĐỢT, không phải mỗi đêm** — cùng lý lẽ đã dùng cho cờ nghi mất
tích. Mốc so là chính bản kê gần nhất, nên khách chạy lại rồi lại chết thì đợt mới
được báo lại. Trạng thái «đang im lặng bao lâu» đọc từ bảng; nhật ký kể **sự
kiện**, không giữ trạng thái liên tục.

Kích hoạt: cron gọi `python -m portal.cli.kiem_tenant_im_lang`, lệnh này chỉ **xếp
hàng** một job mỗi tenant. Tự làm hết việc rồi thoát thì lần nó không chạy sẽ
không để lại gì — khá mỉa mai nếu cái bắt-im-lặng lại chết im lặng.

⚠️ Cảnh báo đọc mốc **mới nhất của mọi thực thể**, không theo từng thực thể — «đối
soát `project` mà quên `unit`» chưa bắt được. Dữ liệu đã lưu theo thực thể nên
siết sau được; chưa làm vì nó sẽ kêu ngay ngày đầu với mọi tenant chỉ đối soát một
phần, và một cảnh báo kêu sai là một cảnh báo bị tắt.

## 8. Nợ đã trả (giữ lại lý lẽ)

**1. ~~Trần bản kê 20.000 mục~~ — ĐÃ LÀM.** Phân trang bằng **KHOẢNG**, không
bằng phiên. Mỗi trang tự khai đoạn nó phủ và phép so chỉ chạm đúng đoạn đó:

    (afterExternalId, max(externalId trong trang)]   — trang giữa
    (afterExternalId, +∞)                            — isLastPage

Không phiên vì phiên cần trạng thái giữa các request, cần hạn cho phiên bỏ dở, và
cần một câu trả lời cho «phiên chết giữa chừng thì cờ đã đặt đi đâu». Khoảng thì
mỗi request TỰ ĐỦ — gửi lại được, và một trang không bao giờ tới chỉ khiến đoạn đó
không được kiểm (hỏng về phía an toàn), chứ không gắn cờ sai.

Mặc định `afterExternalId=null` + `isLastPage=true` ⇒ **nguyên hành vi một trang**,
adapter đang chạy không phải sửa gì.

⚠️ Bốn chỗ phải đúng cùng lúc, và cả bốn hỏng ÂM THẦM:
  · **Cận trên suy từ `max(records)`**, không phải giá trị khách khai — để họ khai
    thì một trang khai rộng hơn thứ nó chứa sẽ gắn cờ cho phần chênh.
  · **Câu gỡ cờ phải mang cùng vị từ khoảng** với câu tìm mất tích, nếu không trang
    sau xoá cờ trang trước vừa đặt. Khoảng vì thế tính MỘT lần ở `service` rồi
    truyền vào cả hai — để mỗi hàm tự tính là đúng lỗi đã sập một lần: hàm gỡ cờ
    nhận danh sách MẤT TÍCH chứ không phải bản kê, nên trang không có gì mất tích
    ra khoảng `(-∞, +∞)` và gỡ sạch mọi cờ.
  · **«Phủ không gì» phải có biểu diễn RIÊNG** (`khoang()` trả `None`). Bản đầu trả
    `(tu_ma, tu_ma)`, đúng khi có `tu_ma` nhưng ở trang đầu thành `(None, None)` =
    `(-∞, +∞)` — hai nghĩa trái ngược trong cùng một giá trị.
  · **So bằng `COLLATE "C"`** (thứ tự byte). Không có nó, ranh giới phụ thuộc
    collation của DB còn khách sắp theo thứ tự của họ; lệch nhau là bản ghi rơi vào
    trang không chứa nó và bị gắn cờ SAI.

⚠️ `afterExternalId` = mã lớn nhất **ĐÃ GỬI** ở trang trước, KHÔNG phải «đã quét».
Chọn nghĩa sau tạo một khe im lặng ở đúng ranh giới: bản ghi bị xoá rơi ra ngoài cả
hai trang. Đã đo cả hai chiều.

Nhịp tim (§7.5) **chỉ đóng dấu ở trang cuối** — một cuộc phân trang chết giữa chừng
là một cuộc đối soát chưa xong, và đóng dấu ở trang đầu sẽ làm im cảnh báo «tenant
im lặng» cho đúng ca adapter hỏng sau trang một.

**2. ~~Giới hạn tốc độ theo token~~ — ĐÃ LÀM.** `modules/ingest/nhip.py`, cửa sổ
cố định trên Redis, đếm theo **băm** token và kiểm **trước khi tra DB** (không thì
một máy dò token bắt portal chạy một truy vấn cho mỗi lần đoán). Hai cửa hai nhịp:
`/events` 120 req/phút · `/manifest` 30 req/giờ — không gộp, vì một lượt đối soát
là phép so trên TOÀN BỘ dữ liệu còn nhịp hợp lệ của nó chỉ là hằng đêm. **Đếm
REQUEST, không đếm bản ghi**: `TRAN_LO` đã chặn khối lượng mỗi lượt, còn đếm bản
ghi thì một vòng lặp hỏng gửi lô 1 bản ghi vẫn chạy được 30.000 lượt/phút «dưới
hạn mức». Vượt ⇒ **`429`**, tách bạch với `401`: `401` nghĩa là đổi token, `429`
nghĩa là token đúng rồi, chậm lại. ⚠️ KHÔNG phủ request không kèm token — không có
gì để quy trách nhiệm, đó là việc của tầng vào.

**3. ~~Mã hoá at-rest cho token~~ — ĐÃ LÀM.** AES-256-GCM, `core/bi_mat_luu.py`,
phủ **cả hai cột cùng lượt** (`agent_keys.api_key` + `ingest_tokens.token`) đúng như
`0927` đã đặt điều kiện: mã hoá bảng này rồi để nguyên bảng kia là dời rủi ro chứ
không giảm. Mã hoá/giải mã ở **tầng repo** — chỗ duy nhất chạm SQL — nên không tầng
nào phía trên phải nhớ gọi. **Đường xác thực KHÔNG đổi một dòng**: nó vẫn tra
`key_sha256`/`token_sha256`, và đó là thứ làm bản vá này rẻ. Khoá **RIÊNG**
(`TOKEN_ENC_KEY`), không dẫn xuất từ `AGENT_MASTER_KEY` — quyết định về vòng đời:
xoay khoá gốc là mọi tenant suy lại mật khẩu Postgres/S3, và nếu nó còn giải mã
token thì một lần xoay mà quên mã hoá lại là mất vĩnh viễn mọi khoá thô. Ciphertext
mang tiền tố phiên bản `enc.v1.` từ ngày đầu, để xoay khoá sau này là thêm một
nhánh chứ không phải migrate định dạng. `giai_ma()` trả nguyên văn chuỗi không có
tiền tố ⇒ **deploy code trước, backfill sau** (`python -m portal.cli.ma_hoa_bi_mat_cu`,
mặc định thử khô). ⚠️ Bằng chứng nợ đã trả: `_NGOAI_LE_CO_CHU_Y` của cổng
`test_khong_cot_text_nao_chua_bi_mat` nay **RỖNG** — ngoại lệ cho `agent_keys.api_key`
tự hết chứ không được tha, và có thêm một cổng quét động cho `ingest_tokens`.

**4. ~~Dọn `ingest_errors`~~ — ĐÃ LÀM.** Job đêm `ingest_don_loi`
(`python -m portal.cli.don_loi_nap`), cắt **hai vế**: quá `INGEST_LOI_GIU_NGAY`
(30) và quá `INGEST_LOI_TRAN_HANG` (2.000) dòng mỗi tenant. Cần cả hai — cắt theo
tuổi một mình không chặn được một ĐỢT BÙNG (adapter hỏng sinh hàng chục nghìn dòng
trong một đêm, tất cả đều mới tinh), còn cắt theo số dòng một mình thì một tenant
lỗi lai rai giữ mãi vài dòng từ năm ngoái. ⚠️ Vế thứ hai cắt theo **`id`**, không
theo `received_at`: cột đó mặc định `now()` — GIỜ GIAO DỊCH — nên cả 500 dòng của
một lô mang ĐÚNG một mốc, và `min(received_at)` khi đó bằng chính nó, tức phép cắt
xoá được không gì. Lệnh RIÊNG chứ không gộp vào `kiem_tenant_im_lang`: hai việc có
nhịp hợp lý khác nhau, và một lệnh làm hai việc thì ops không tắt được việc này mà
giữ việc kia.

**5. ~~`last_used_at` là một cột nói dối~~ — ĐÃ XỬ LÝ.** `repo.cham_da_dung` là
code chết từ `0927` nên cột luôn `NULL`, và `NULL` ở đó đọc thành «token này chưa
ai dùng» — sai, và sai theo hướng **mời người ta xoá một token đang chạy**.

Chọn **BỎ** chứ không «ghi nó», và lý do quyết định KHÔNG phải giá: ghi rẻ được
(chỉ ở request đầu mỗi cửa sổ nhịp, tận dụng bộ đếm Redis đã có). Lý do là **không
ai đọc** — `TokenOut` có đúng ba trường sau năm vòng cắt, và «Dùng cuối» bị cắt kèm
lý do rõ: câu hỏi đó đã được «Nhận cuối» ở khối Endpoint trả lời cho cả workspace.
Một cột được ghi trung thực mà không giao diện nào bày ra vẫn là cùng một lời nói
dối, chỉ đổi chiều.

⚠️ **Lời hứa thứ hai cũng rỗng, và đã trả cùng lượt.** `TokenOut` khai «siêu dữ
liệu kiểm toán là việc của Nhật ký» và `router_tenant.xoa_token` khai «ai xoá token
nào là việc của Nhật ký» — nhưng module chưa từng ghi một dòng nào cho vòng đời
token. `service.tao_token`/`xoa_token` nay ghi `ingest.token_tao`/`ingest.token_xoa`
vào `control.audit_log`, kèm **nhãn** (sau khi xoá thì hàng không còn để tra id) và
**không kèm chuỗi thô** (Nhật ký có nhiều người đọc hơn bảng token). Xoá hụt thì
KHÔNG ghi: với id của tenant khác, một dòng nhật ký còn là rò rỉ — nó khẳng định id
ấy tồn tại.

> Hai mục từng ở đây đã chốt 2026-08-14 và nằm trong thân tài liệu:
> `zoneExternalId` **bắt buộc** (§4.1) · `?dryRun=true` **có** (§3.1).
> ⚠️ Quyết định đầu đã bị **đảo lại** 2026-08-15 — `zoneExternalId` giờ TUỲ
> CHỌN, xem §4.1 hiện hành. Giữ dòng cũ ở đây để thấy tiến trình, không phải vì
> nó còn đúng.

## 9. Kiểm thử

- **Hợp đồng** — thiếu trường vỏ · sai kiểu · giá trị ngoài enum · `occurredAt`
  lệch thứ tự · đẩy trùng · trường lạ (phải **đi qua**, không phải bị từ chối).

  ⚠️ Bổ sung sau review MR !55 — hai ca «CÓ MẶT nhưng rỗng» mà bản đầu bỏ sót, cả
  hai đều được nhận rồi chết ở tầng dưới: trường bắt buộc gửi tường minh `null`
  (`t.ten in data` là True nên không bị coi là thiếu), và **khoá tham chiếu cha
  thiếu hẳn** (nằm trong `QUAN_HE` nên bị loại khỏi vòng kiểm chính, chưa từng
  được kiểm ở đâu). Bài học chung: *«đã kiểm sự hiện diện» không bằng «đã kiểm giá
  trị dùng được»*.

  ⚠️ Bổ sung sau review 2026-08-15
  (`odyssey-qa/reviews/2026-08-15-review-ingest.md`) — cùng bài học, đi xa hơn:
  `kiem()` giờ khớp ĐÚNG miền giá trị mà cột DB chấp nhận, không chỉ đúng kiểu.
  Chuỗi RỖNG cho trường bắt buộc (0400 đặt CHECK `<> ''`) · ký tự NUL trong chuỗi (Postgres từ chối bằng `22P05`) · phần tử `null` trong một mảng enum
  (`category <@ ARRAY[...]` ra FALSE khi mảng chứa NULL) · `loai` sai kiểu hoặc
  sai giá trị · khoá tham chiếu cha falsy (`''`/`0`/`false`) dù trường đó TUỲ
  CHỌN — tất cả thành lỗi field-level ngay LÚC NHẬN, không còn một
  `CheckViolation` mờ mịt lúc chiếu sau khi bản ghi đã báo `accepted`. Riêng
  một bài canh cho `occurredAt`/`updatedAt` naive (không múi giờ) ⇒ `422` —
  viết trước khi có adapter thật nào từng gửi giờ naive, đúng cách một bài canh
  hợp đồng nên tồn tại.

- **Chiếu không được làm hỏng lô** — một bản ghi không ghi được vào kho phải thành
  một dòng `ingest_errors` chứ không phải một `500` mất cả lô. Bài canh dựng một
  hàng thô hỏng SẴN trong bảng rồi khẳng định lô mới vẫn vào. Không có savepoint
  cho từng bản ghi thì `except` chỉ đổi chỗ nổ: Postgres huỷ cả giao dịch ngay khi
  một câu lệnh lỗi.

- **Tầng HTTP** (`test_router.py`) — bốn endpoint quản trị **có lên** (phân biệt
  `401` với `404`: chúng sống nhờ đúng một dòng `include_router`, xoá đi thì 404
  im lặng) · mọi dạng xác thực sai ra cùng một mã · `?dryRun` parse đúng và không
  ghi gì · token nạp **không** mở được endpoint quản trị · hai handler nạp không
  nhận `Principal` (kiểm ở chữ ký — một request không cookie trả 401 không chứng
  minh được gì).
- **Cách ly** — token tenant A không chạm được dữ liệu tenant B; token lĩnh vực A
  không chạm lĩnh vực B; token đã xoá trả 401.

  ⚠️ Vế giữa nằm ở đây từ bản spec đầu nhưng **bài canh tương ứng không được
  viết**, và lỗ hổng §5 sống sót đúng nhờ khoảng hở đó: một dòng spec mô tả hành
  vi mong muốn đọc y hệt một dòng mô tả hành vi đã có. Viết xong 2026-08-14.
- **Projector** — con tới trước cha, kể cả lan truyền HAI TẦNG (zone chờ
  project, rồi unit/media chờ zone) · lan truyền vượt `TRAN_LAN_TRUYEN` để lại
  đúng MỘT dòng lỗi cho bản ghi cha gốc và các con còn lại giữ nguyên cờ chờ
  (không mất gì) · `delete` xoá mềm bằng `status = 'archived'` · chiếu lại từ
  bản thô ra cùng kết quả.

  ⚠️ Năm bài canh mới của đợt tái cấu trúc 2026-08-15: **thay-thế-trọn-bản-ghi**
  — upsert thứ hai bỏ một trường tuỳ chọn khỏi payload thì cột đó quay về
  DEFAULT của DB (không giữ giá trị của lần upsert trước) · **tie-break
  tombstone** — `delete` cùng `occurredAt` thắng một `upsert` đang lưu, chiều
  ngược lại không hồi sinh, đẩy lại y hệt vẫn `stale` · **purge Qdrant** — mọi
  transition rời `published` (cả `op:delete` lẫn upsert đổi status) enqueue
  đúng `KIND_DELETE_INDEX` khớp khuôn đường manual, và `zone` cascade đúng mọi
  `media` neo vào nó · **`public_url`** của media được derive lúc chiếu, không
  lúc nhận · **địa chỉ nhất quán** — `media` giải `unitExternalId` thì
  `project_code`/`zone_code` đi theo ĐÚNG unit đó, không theo
  `projectExternalId` khai riêng trong payload của chính `media`.
- **Đối soát** — dựng lệch có chủ ý rồi kiểm phát hiện đúng cả hai chiều · **không**
  tự xoá gì · cờ tự gỡ khi bản ghi xuất hiện lại · mốc nghi giữ lần đầu · bản ghi
  đã `delete` không bị tính là mất tích · bản kê của thực thể này không gắn cờ cho
  thực thể khác · bản kê của tenant A không chạm dữ liệu tenant B (đối soát GHI,
  nên nó nguy hiểm hơn một đường đọc) · mã trùng và bản kê quá trần bị chặn TRƯỚC
  khi chạm dữ liệu · Nhật ký ghi khi có cờ MỚI và **không** ghi lại lần sau.
- **`dryRun`** — cùng payload cho ra cùng `results` như bản ghi thật; và sau một
  lượt `dryRun`, `ingest_records` · `ingest_errors` · bảng thực thể đích (ví dụ
  `projects`) đều **không đổi**. Vế sau mới là bài quan trọng: một `dryRun` ghi
  lén trông y hệt một `dryRun` đúng cho tới lúc ai đó đọc số liệu. (Bài trước
  đây còn canh cả `last_used_at` — cột đó đã **bỏ** ở `0930`, xem §5.)

## 10. Frontend — đã xong, không phải làm lại

`odyssey-portal-frontend`, màn con `/projects?nap=1` (nút «Nạp qua API» cạnh
«Thêm dự án» ở `/projects`). Ba khối: endpoint + ba con số 24 giờ + link Tài liệu
API · bảng token · bảng bản ghi bị từ chối. Hợp đồng ở
`src/features/realestate/nguon.ts`, fake ở `src/features/realestate/msw.ts`,
16 bài ở `tests/realestate-nguon.test.tsx`.

⚠️ Fake MSW là **bản sao viết tay không có cổng parity**. Khi backend thật lên,
đối chiếu lại từng tên trường — đã sập một lần trong lúc thi công FE: đổi một tên
trường trong kiểu mà quên đổi ở fake làm cả tab trắng lúc chạy trong khi `tsc -b`
vẫn xanh.
