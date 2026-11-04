# M4-FE — Form nhập liệu KB Bất động sản

Ngày: 2026-08-03 · Trạng thái: đã chốt với chủ sản phẩm
Repo chính: `odyssey-portal-frontend` · Repo phụ: `odyssey-portal-backend` (2 endpoint kho tệp)

## 1. Vì sao có tài liệu này

Backend M4 xong 6/6 task (`odyssey-portal-backend/.superpowers/sdd/2026-08-03-kb-real-estate-viet-lai/progress.md`):
5 bảng KB, 25 route CRUD, cổng completeness, lớp đọc của agent, seed. Frontend
thì `src/features/realestate/` chỉ có `nav.ts`, và ba màn `projects`/`pform`/`uform`
đều render `<ScreenStub/>`. Nghĩa là **dữ liệu BĐS hôm nay chỉ nhập được bằng
curl/Postman**. Tài liệu này đặc tả phần FE để người biên tập nhập được bằng form,
cộng đúng hai endpoint kho tệp mà FE cần nhưng BE chưa có.

Nguồn sự thật về field và luật: `odyssey-portal-backend/docs/build_module_knowledgebase/`
(`02-knowledge-base.md`, `02a-real-estate-template.md`, `mau-form-cms.html`).
Hợp đồng HTTP: `odyssey-portal-backend/src/portal/modules/realestate/contracts.py`
và các DTO ghi trong `router.py`.

## 2. Hai ràng buộc cứng định hình thiết kế

**① Không được thêm file route.** `tests/nav-registry.test.ts` (mỗi màn có đúng
một route file) `readdirSync('src/routes/_app')`, lọc `.tsx`, rồi so **đúng bằng**
với 18 `path` của `src/lib/screens.ts`. Thêm `projects.$code.tsx` ⇒ thừa một path
⇒ đỏ. Chuyển `/projects` vào thư mục con ⇒ thiếu một path ⇒ đỏ. Vì vậy M4 chỉ có
đúng ba màn đã khai — `projects`, `pform`, `uform` — và **điều hướng giữa chúng đi
bằng search param**, không phải path param:

- `/projects` — danh sách dự án
- `/pform?code=VHOP2` — form dự án (tạo mới: `/pform` không có `code`)
- `/uform?code=VHOP2&unit=41` — form một căn (tạo mới: không có `unit`)

Không sửa `screens.ts`, không sửa `nav.ts`, không sửa `nav-registry.ts`. Ba cổng
`nav-registry.test.ts`, `module-boundaries.test.ts`, `actions-parity.test.ts` phải
xanh nguyên trạng.

**② Không có form library.** `package.json` chỉ có `react`, `@tanstack/react-query`,
`@tanstack/react-router`. Không thêm dependency: input controlled + validate ở
biên là việc React thuần làm được, và thêm `react-hook-form`+`zod` vào đây là thêm
hai thứ phải bảo trì cho một màn CMS nội bộ. Nếp code theo
`src/features/kb/components/TaiLieuList.tsx` (màn FE gần nhất, cùng khuôn `useQuery`
+ `useMutation` + `invalidateQueries`).

## 3. Bố cục — master–detail theo cây anchor

Chọn hình dạng này vì nó khớp 1:1 cây route của BE
(`/projects/{project_code}/zones|units|documents|media`) và khớp luật UX #1 của
`mau-form-cms.html` (`project_code` kế thừa từ dự án đang mở). Sáu tab phẳng của
mockup, nếu dựng đúng như vẽ, buộc người nhập chọn lại dự án ở từng tab — và một
lần chọn sai là một căn nằm trong dự án khác.

```
/projects
  ┌ tab Dự án          bảng + tìm kiếm + lọc khu vực/trạng thái + [+ Dự án]
  └ tab Tài liệu chung documents của project_code = __ALL__
        │ click một dự án
        ▼
/pform?code=VHOP2
  ┌ Thông tin   19 field của projects + 2 ô media (cover · mặt bằng tổng)
  ├ Phân khu    danh sách zones + form inline
  ├ Căn         danh sách units + lọc (phân khu · loại SP · trạng thái bán)
  ├ Tài liệu    documents của dự án
  └ Media       7 vùng theo category, mỗi vùng ≤ 6 ảnh
        │ click một căn
        ▼
/uform?code=VHOP2&unit=41
  15 field của units + ảnh căn (≤ 6)
```

`/pform` không có `code` ⇒ chỉ hiện tab Thông tin (bốn tab con đều cần
`project_code` đã tồn tại để POST). Sau khi POST thành công thì
`navigate({search:{code}})` và bốn tab kia mở ra.

## 4. Cây file — mỗi file một việc

Tất cả nằm trong `src/features/realestate/`. Chỉ `nav.ts` được module khác import
(luật `module-boundaries.test.ts`). Ba file route chỉ `createFileRoute` +
`validateSearch` + render component, không logic.

| File | Trách nhiệm | Phụ thuộc |
|---|---|---|
| `api.ts` | Client HTTP: 25 route CRUD + 2 route kho tệp. Type `DuAn`/`PhanKhu`/`Can`/`TaiLieu`/`Media`/`Trang<T>`, lớp `LoiApi` mang `code` + `truong` (map field→lỗi) | — |
| `enums.ts` | 8 enum ↔ nhãn tiếng Việt + thứ tự hiện trong dropdown | — |
| `completeness.ts` | `BAT_BUOC` bản FE (`project`: name·region·overview · `unit`: priceVnd·areaBuiltM2·saleStatus) + `thieuTruong()` | — |
| `components/DuAnList.tsx` | Màn `/projects`: 2 tab, bảng, tìm/lọc, badge thiếu dữ liệu, xoá có xác nhận | api · enums · completeness · TrangCuon |
| `components/DuAnForm.tsx` | Màn `/pform`: khung 5 tab, sở hữu `code`, breadcrumb | 5 tab con |
| `components/tabs/ThongTinTab.tsx` | 3 nhóm field của projects + 2 ô media | OTruong · OMedia |
| `components/tabs/PhanKhuTab.tsx` | zones: danh sách + form inline | OTruong · OMedia |
| `components/tabs/CanTab.tsx` | units: danh sách + 3 bộ lọc + link `/uform` | TrangCuon |
| `components/tabs/TaiLieuTab.tsx` | documents của một `project_code` (dùng lại cho `__ALL__`) | OTruong · OTep |
| `components/tabs/MediaTab.tsx` | 7 vùng category, mỗi vùng ≤ 6 ảnh | OMedia |
| `components/CanForm.tsx` | Màn `/uform`: 15 field + ảnh căn | OTruong · OMedia |
| `components/OTruong.tsx` | label + input/select/textarea + lỗi field + dấu `*` | — |
| `components/OMedia.tsx` | Ô media: tab Tải lên/Dán URL · xem trước · caption · xoá | api |
| `components/OTep.tsx` | Ô tệp tài liệu (không phải ảnh): tải lên → `fileUrl` | api |
| `components/TrangCuon.tsx` | Hook `useTrangCuon()` — bọc `useInfiniteQuery` theo giao thức cursor | api |

`enums.ts` tách riêng vì 8 enum được dùng ở ba nơi (dropdown form · nhãn trong
bảng · dropdown bộ lọc); để trong component là ba bản sao sẽ lệch nhau.
`OTruong` tách riêng vì nó là markup lặp cho **toàn bộ** ô nhập của năm thực thể
(§5 liệt kê 54 ô: 21 · 8 · 15 · 4 · 6); `OMedia` lặp ở 5 chỗ (cover · mặt bằng của
project và zone, ảnh căn) cộng 7 vùng của tab Media.

## 5. Field — phủ trọn danh sách trắng `COT_*` của BE

Danh sách dưới đây là **đầy đủ**: nó phủ hết `COT_DU_AN`/`COT_PHAN_KHU`/`COT_CAN`/
`COT_TAI_LIEU`/`COT_MEDIA` của `contracts.py`, trừ bốn cột hệ thống
(`id`/`tenant_id`/`created_at`/`updated_at`) và hai cột do router tự gán
(`cover_media_id`/`map_media_id`). Tổng 54 ô: projects 21 · zones 8 · units 15 ·
documents 4 · media 6. (`mau-form-cms.html` chỉ vẽ 46 ô vì mockup gộp vài vùng —
theo `COT_*`, không theo mockup.)

Tên ô = alias camelCase trong `router.py`. `*` = bắt buộc ở biên HTTP.
`⚠` = bắt buộc để publish (`completeness.py`).

**projects — tab Thông tin**

*Nhóm Định danh & vị trí*: `projectCode`* Mã dự án (chỉ nhập lúc tạo, PATCH
không có ô này) · `name`*⚠ Tên thương mại · `category` Loại hình (**chọn nhiều**,
`text[]`) · `region`⚠ Khu vực · `address` Vị trí chính xác · `investor` Chủ đầu tư ·
`developer` Đơn vị phát triển · `salePhase` Trạng thái kinh doanh · `status`
Trạng thái hiển thị.

*Nhóm Quy mô*: `totalLandAreaM2` Tổng DT đất (m²) · `floorAreaM2` Tổng DT sàn
(m²) · `buildDensityPct` Mật độ XD (%) · `productScale` Quy mô sản phẩm ·
`ownershipForm` Hình thức sở hữu · `handoverStandard` Tiêu chuẩn bàn giao ·
`totalInvestmentVnd` Tổng mức đầu tư (VND) · `amenities` Tiện ích (mô tả, textarea).

*Nhóm Mô tả & liên kết*: `overview`⚠ Tổng quan (textarea — nguồn RAG) ·
`link360` Link tham quan 360 · `coverMedia` Ảnh cover · `mapMedia` Ảnh mặt bằng tổng.

**zones — tab Phân khu**: `zoneCode`* Mã phân khu · `name` Tên phân khu ·
`category` Loại hình (**chọn một**, nullable) · `productScale` Quy mô phân khu ·
`overview` Tổng quan · `status` · `coverMedia` · `mapMedia`.

**units — màn `/uform`**: `zoneCode`* Phân khu (dropdown lấy từ zones của dự án) ·
`unitCode`* Mã căn · `productType`* Loại sản phẩm · `bedrooms` Số phòng ngủ (0–50) ·
`saleStatus`⚠ Trạng thái bán · `direction` Hướng · `block` Tòa/block · `floor` Căn
ở tầng (−50…300) · `numFloors` Số tầng của căn (0–300) · `areaBuiltM2`⚠ DT thông
thuỷ · `areaWallM2` DT tim tường · `areaLandM2` DT đất · `priceVnd`⚠ Giá bán (VND) ·
`pricePerM2Vnd` Đơn giá/m² · `status` · ảnh căn (≤6) · `imageUrl` (**không có ô
riêng** — FE gán bằng key của ảnh đầu, xem §7).

**documents — tab Tài liệu và tab Tài liệu chung**: `title`* Tiêu đề (mặc định
= tên tệp vừa tải lên) · `fileUrl` Tệp tài liệu · `body` Nội dung markdown
(textarea) · `status`.

**media — tab Media**: `contentType`* (image·video) · `category`* (7 giá trị) ·
`mediaUrl`* · `caption` · `zoneCode`/`unitCode` (tuỳ vùng) · `status`.
`thumbUrl` để rỗng (xem §9).

Enum (`enums.ts`) — giá trị đúng như `Literal` ở `router.py`, nhãn tiếng Việt:
`status` draft·published·archived · `salePhase` sap_mo_ban·dang_ban·ban_giao·dong_gio_hang ·
`category` chung_cu·biet_thu·lien_ke·shophouse·dat_nen·van_phong ·
`productType` 12 giá trị · `direction` 8 hướng · `saleStatus` available·booked·sold ·
`contentType` image·video · `mediaCategory` tong_quan·ngoai_that·noi_that·tien_ich·mat_bang·vi_tri·tien_do.

## 6. Hai endpoint thêm ở backend

FE không upload được vào bảng `media` hôm nay: `mediaUrl`/`fileUrl` là **chuỗi**, và
`grep UploadFile` toàn `src/portal` chỉ trúng `modules/kb/router.py`. Thêm đúng hai
route vào `modules/realestate/router.py` (không file mới, không migration, không
action mới — vẫn `catalog.read`/`catalog.write` nên cổng parity giữ nguyên):

| Route | Hành vi |
|---|---|
| `POST /api/v1/realestate/uploads` | multipart một tệp. Chặn loại + dung lượng ở biên (ảnh `.jpg .jpeg .png .webp` ≤ 10 MB; tài liệu `.pdf .docx .xlsx` ≤ 25 MB), `sha256` nội dung, `KhoTep.ghi()` vào `tenants/{tenant_id}/kb-bds/{sha}/{tên}`, trả `{"key","contentHash","contentType"}`. `require(CATALOG_WRITE)` |
| `GET /api/v1/realestate/files?key=…` | Trả nội dung tệp (`StreamingResponse`). **Cưỡng chế `key.startswith(f"tenants/{p.tenant_id}/")` — không khớp thì 404**, và đây là dòng quan trọng nhất của cả hai route: thiếu nó thì một `key` đoán được sẽ đọc tệp của tenant khác, và toàn bộ cách ly M1 vô nghĩa ở đúng chỗ này. `require(CATALOG_READ)` |

**Lưu key, không lưu URL.** `media_url`/`file_url` nhận **khoá S3** (đúng ví dụ
`"acme/docs/csbh-q3.pdf"` của `02a §4`), không phải presigned URL — presigned hết
hạn, mà hai cột này lưu vĩnh viễn và agent còn đọc lại. Quy ước đọc, dùng ở cả FE
lẫn (sau này) agent: **giá trị bắt đầu bằng `http` thì dùng nguyên văn** (YouTube ·
kuula · Drive — `02a §4` cho phép đúng các nguồn này), **ngược lại là khoá MinIO**
và render qua `/api/v1/realestate/files?key=…`. Auth là cookie
(`request.cookies.get(TEN_COOKIE)` trong `core/auth/require.py`) và dev server proxy
`^/api/` cùng origin, nên `<img src="/api/v1/realestate/files?key=…">` gửi cookie
tự động — không cần token trong URL.

**Cấu hình MinIO.** Dev **giữ MinIO local cổng 9002** của `docker-compose.dev.yml`:
test phải chạy offline và `make reset` phải xoá sạch được kho, mà `KhoTep.xoa_sach()`
trỏ vào một bucket dùng chung là một lệnh xoá dữ liệu của người khác. Endpoint dùng
thật (`http://10.50.13.220:9000`) và cặp khoá của nó vào `.env` cục bộ (đã có trong
`.gitignore`) cộng `deploy/odyssey-portal-backend.env.example` **dạng placeholder** —
`S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET`. Không commit
secret thật. `core/config.py` và `core/storage.py` không cần sửa: chúng đã đọc đúng
bốn biến đó.

## 7. Luồng dữ liệu

**Query key.** `['re','projects',{search,region}]` · `['re',code]` (chi tiết dự án) ·
`['re',code,'zones']` · `['re',code,'units',{zone,productType,saleStatus}]` ·
`['re',code,'documents']` · `['re',code,'media']`. Tài liệu chung dùng
`['re','__ALL__','documents']` — cùng component, khác `code`.
Ghi xong thì `invalidateQueries({queryKey:['re',code]})`; tạo/xoá dự án thì
`['re','projects']`.

**Phân trang cursor.** `useInfiniteQuery`, `getNextPageParam: (p) => p.nextCursor`.
**Dừng khi `nextCursor === null`, không phải khi `items` rỗng** — trang cuối vừa
khớp `limit` hàng vẫn cho `items` đầy (`contracts.py`, `TrangDuAn.nextCursor`).
Cursor là chuỗi đục, gửi lại nguyên văn, FE không tự sinh.

**Media của project/zone — một request.** `coverMedia`/`mapMedia` là DTO lồng
(`MediaUploadIn`) trong `ProjectIn`/`ZoneIn`: FE `POST /uploads` lấy `key`, rồi gửi
`{"coverMedia":{"mediaUrl":key,"caption":…}}` **kèm form cha**. Router tự tạo hàng
`media` với `category` đúng (`tong_quan` cho cover, `mat_bang` cho map) rồi gán
`cover_media_id`/`map_media_id` nguyên tử. FE **không** tự gọi `POST /media` cho hai
ô này, và **không** tự chọn `category` — router quyết theo ô.

**Ảnh căn — ba bước, không nguyên tử.** `UnitIn` không có DTO media lồng (đây là
minor đã ghi deferred ở task 4). FE làm: ① `POST /uploads` từng tệp → key ②
`POST /projects/{code}/media` từng ảnh với `unitCode` + `category` (**mặc định
`noi_that`**, có dropdown đổi — trần ≤6 đếm theo `(project, zone, unit, category)`
nên đổi category là đổi cả nhóm bị đếm, phải nói rõ trên màn) ③
`PATCH /projects/{code}/units/{id}` đặt `imageUrl` = key của ảnh đầu. Bước ② hỏng
giữa chừng thì có ảnh đã lên mà `imageUrl` chưa đổi — FE hiện lỗi nêu rõ *ảnh nào*
đã lên và *ảnh nào* chưa, không hiện lưu thất bại chung, vì người dùng bấm lại là
nhân đôi số ảnh đã lên và chạm trần 6.

**Ô media, 3 trạng thái**: chưa có · đang tải (disable nút Lưu) · đã có (xem trước +
caption + xoá). Tab Dán URL luôn có mặt: video YouTube/tour kuula không upload được.

## 8. Lỗi — dịch từng mã thành một câu người dùng sửa được

`api.ts` đọc khuôn `{"error":{"code","message"}}`. Không hiện `message` thô của BE
lên form (bản `VALIDATION_ERROR` của BE có nhúng `repr` Python — minor đã ghi
deferred ở task 4, và đó chính là lý do FE phải tự viết câu).

| Mã / tình huống | Màn hiện gì |
|---|---|
| `VALIDATION_ERROR` 422 | Gắn lỗi vào **đúng field** theo `loc` trong body lỗi, cuộn tới field đầu tiên bị lỗi. Không có `loc` đọc được ⇒ một dòng lỗi ở đầu form |
| 409 trùng mã | Mã dự án `VHOP2` đã tồn tại ngay dưới ô mã (tương tự mã phân khu) |
| `MEDIA_LIMIT` 422 | Danh mục *Tiện ích* đã đủ 6 ảnh — xoá một ảnh trước khi thêm. ngay tại vùng đó |
| 404 khi PATCH/DELETE | Bản ghi này vừa bị xoá ở nơi khác + refetch danh sách |
| Thiếu completeness | **Chặn ở FE trước khi gửi**: đổi `status` sang `published` mà `thieuTruong()` không rỗng ⇒ hiện đúng tên field thiếu và không gửi request. BE vẫn là lưới thứ hai (nó chặn cả POST lẫn PATCH) |
| `__ALL__` | Row hệ thống: **ẩn** nút Xoá và ô Trạng thái hiển thị, hiện nhãn Tài liệu chung toàn workspace. BE trả `SENTINEL_PROTECTED`; FE không được để người dùng bấm tới đó |
| Kho rỗng | Hướng dẫn, **không** phải lỗi: không `role="alert"`, không màu đỏ (nếp `TaiLieuList.tsx`, BR04 của M6) |
| Mất mạng / 5xx | Không tải được danh sách dự án. + nút Thử lại. Không hiện như chưa có dự án nào — người dùng sẽ đi nhập lại thứ đã nhập |

Badge thiếu dữ liệu hiện ở cả bảng danh sách (dự án nào chưa đủ trường) và cạnh
nút Lưu, tính bằng `completeness.ts` — người biên tập thấy trước khi bấm publish,
không phải sau khi nhận 422.

## 9. Bốn chỗ lệch `mau-form-cms.html` — chốt theo tài liệu + BE

1. **`documents.body` nhập tay** (textarea markdown). Mockup ghi auto pdf2text /
   OCR (VisionExtractor); pipeline RAG (`02b-rag-service.md`) nằm ngoài phạm vi đợt
   này theo đúng plan `2026-08-03-kb-real-estate-viet-lai.md` §Ngoài phạm vi.
2. **`caption` nhập tay, `thumbUrl` để rỗng.** Mockup ghi caption + thumb auto —
   cùng lý do: VisionExtractor chưa có.
3. **Trần ảnh là 6, không phải 5.** Mockup viết Ảnh căn upload · tối đa 5;
   `02a §4.5` và `TRAN_ANH_MOI_DANH_MUC` ở BE là 6. Mockup mâu thuẫn tài liệu ⇒ theo
   tài liệu + BE, nếu không thì FE chặn ở 5 mà BE cho tới 6, và trần thật thành thứ
   không ai biết ở đâu.
4. **Phân khu là bắt buộc với một căn.** Mockup có mục — (không phân khu) trong
   dropdown; `units.zone_code` là `text NOT NULL` + FK tới `zones`, và `UnitIn.zone_code`
   khai `min_length=1`. Không có căn nào không thuộc phân khu nào. FE: dự án chưa có
   phân khu nào thì tab Căn hiện Tạo phân khu trước khi thêm căn + link sang tab
   Phân khu, không hiện một form gửi lên chắc chắn 422.

## 10. Kiểm thử

Vitest + MSW + Testing Library (đã có hạ tầng, `vitest.setup.ts` + `src/lib/msw/`).

Frontend — `tests/`:
- `realestate-list.test.tsx` — bảng · tìm kiếm · lọc khu vực/trạng thái · kho rỗng
  là hướng dẫn không phải lỗi · cursor: `nextCursor` null thì hết, `items` đầy mà
  còn cursor thì tải tiếp · badge thiếu dữ liệu · xoá có xác nhận
- `realestate-pform.test.tsx` — 19 field gửi đúng alias camelCase · `category` gửi
  mảng · số rỗng gửi `null` không gửi `""` · 422 gắn đúng field · 409 trùng mã ·
  chặn publish khi thiếu `overview` · `/pform` không có `code` chỉ mở một tab
- `realestate-uform.test.tsx` — 17 field · biên `bedrooms`/`floor`/`numFloors` ·
  dropdown phân khu lấy từ zones của đúng dự án · dự án không có phân khu thì chặn
- `realestate-media.test.tsx` — upload → `key` → nằm trong payload cha ·
  `MEDIA_LIMIT` hiện tại đúng vùng · dán URL YouTube đi nguyên văn · key MinIO render
  qua `/files?key=` · ảnh căn: bước ② hỏng thì báo rõ ảnh nào đã lên
- `realestate-tailieu.test.tsx` — tài liệu dự án · tài liệu `__ALL__` ẩn nút Xoá và ô Trạng thái

Ba cổng cũ phải xanh nguyên trạng: `nav-registry.test.ts` (18 route file),
`module-boundaries.test.ts` (không import chéo module), `actions-parity.test.ts`.

Backend — `tests/modules/realestate/`:
- `test_uploads.py` — loại tệp lạ 422 · quá dung lượng 422 · cùng nội dung ra cùng
  `key` (content-addressed) · key nằm đúng tiền tố `tenants/{id}/`
- `test_files.py` — đọc lại được tệp vừa ghi · **`key` của tenant khác trả 404** ·
  `key` dạng `../` hoặc tiền tố tenant khác trả 404 · thiếu `catalog.read` thì 403

## 11. Ngoài phạm vi

Pipeline RAG (embed/chunk/caption, `02b`) · VisionExtractor auto-caption ·
pdf2text/OCR cho `documents.body` · màn `domains` (M4 sở hữu nhưng là màn khác) ·
màn `finance` (hoãn) · sửa `mau-form-cms.html` cho khớp bốn điểm ở §9 (mockup là
tài liệu tham chiếu, không phải nguồn sự thật) · thay đổi `screens.ts`/`nav.ts`.
