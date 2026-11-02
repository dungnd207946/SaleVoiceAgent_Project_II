# Màn dự án — vòng 2: chín tab, media dạng folder, trạng thái suy ra

> Tiếp sau [2026-08-10-tab-kien-thuc-bds-design.md](2026-08-10-tab-kien-thuc-bds-design.md) (vòng 1, đã thi công xong: 10 tab + `documents.loai`). Vòng này **đổi hai quyết định của vòng 1** — nói rõ ở §3 và §5.
>
> ⚠️ **Cập nhật 2026-08-11 sau khi merge `develop`:** migration `0917_bo_agent_api` đã **xoá hẳn** schema `agent_api`. Mọi câu trong spec này viết "`agent_api.projects` lọc `WHERE status='published'`" nay phải đọc là: **agent đọc thẳng `tenant_data.projects` và tự lọc `status='published'`**, cách ly tenant dựa vào **RLS FORCE** (`0913`). **Bản chất thiết kế không đổi** — `status` vẫn là công tắc quyết định agent có đọc bản ghi hay không, nên §4.4 (`status` suy ra) vẫn đúng nguyên vẹn; chỉ *cơ chế lọc* dời từ view sang câu SQL của agent.
>
> Spec này bao trùm **cả hai repo** (`odyssey-portal-backend`, `odyssey-portal-frontend`) và **một hợp đồng gửi sang repo thứ ba** (`odyssey-agent`, §7).

## 1. Vấn đề

Vòng 1 chia màn `/pform` thành mười tab và cho tài liệu một phân loại thật. Dùng thử phát sinh chín yêu cầu, chia làm ba nhóm:

**Bố cục sai thứ tự thao tác.** Mặt bằng đứng *sau* Phân khu, nhưng người mở mặt bằng là để chọn phân khu — đọc mặt bằng trước, rồi mới vào phân khu. Media đứng *trước* Tiến độ dù nó là kho tổng, thứ mở sau cùng. Tab CSBH đứng riêng trong khi nó chỉ là một loại tài liệu.

**Trần 6 ảnh chặn đúng việc người dùng cần làm.** Một dự án thật có hàng chục ảnh ngoại thất. Trần 6 là con số của bản mockup CMS, không phải của nghiệp vụ, và nó biến "nạp ảnh dự án" thành "chọn 6 ảnh đại diện" — một việc khác hẳn.

**Ba thứ trên màn nói điều người dùng không cần biết.** Ô "Trạng thái hiển thị" (`draft`/`published`/`archived`) là một khái niệm của hệ thống, không phải của biên tập viên: họ nạp dữ liệu để agent trả lời, nên "đã phát hành" là *kết quả* của việc nạp đủ, không phải một lựa chọn. Bảy vùng media mở sẵn xếp dọc thành một trang dài không cuộn hết. Bảng tài liệu không phân biệt được loại nào là loại nào ở tầm nhìn một giây.

## 2. Ngoài phạm vi

- **Mọi thay đổi lược đồ Postgres.** Không cột mới, không bảng mới, không `DROP COLUMN`. Cột `status` **vẫn còn** trong cả năm bảng và vẫn còn trong năm view `agent_api.*`; chỉ có UI thôi khai nó (§4.4).
- **Kéo-thả sắp xếp ảnh.** Thứ tự ảnh trong một danh mục vẫn là thứ tự `created_at` như hiện nay.
- **Sửa repo `odyssey-agent`.** Repo đó không nằm trong phạm vi phiên này; §7 chỉ ghi hợp đồng để copy tay.
- **Tìm kiếm/lọc mới** ngoài thanh lọc loại tài liệu đã có.
- **Gộp năm bản `<div role="alertdialog">` inline** thành component dùng chung — đã chốt là task độc lập từ vòng 1.

## 3. Đổi một nguyên tắc của vòng 1: media thành *một danh mục một chỗ*

Vòng 1 §3 chốt **«tab là lăng kính, không phải ngăn chứa»**: một row nằm ở đúng một chỗ trong DB, nhiều tab cùng *nhìn* vào nó; nên tab Media hiện **đủ bảy** danh mục kể cả ba danh mục đã có tab chuyên đề (`vi_tri`, `mat_bang`, `tien_do`).

**Vòng này bỏ nguyên tắc đó cho media.** Ba danh mục có tab riêng rời khỏi tab Media hẳn:

| Danh mục | Vòng 1 | Vòng 2 |
|---|---|---|
`tong_quan` · `ngoai_that` · `noi_that` · `tien_ich` | tab Media | tab Media (**giữ**) |
`vi_tri` | tab Media **và** tab Vị trí | chỉ tab **Vị trí** |
`mat_bang` | tab Media **và** tab Mặt bằng | chỉ tab **Mặt bằng** |
`tien_do` | tab Media **và** tab Tiến độ | chỉ tab **Tiến độ** |

**Vì sao đổi:** nguyên tắc lăng kính trả giá bằng một câu giải thích mà người dùng phải đọc và tin — "cùng một ảnh, không phải bản sao, nên xoá ở đây là xoá khỏi dự án". Vòng 1 phải viết câu đó vào tab Media (Task 7) chính vì không có cách nào *cho thấy* điều đó. Một danh mục một chỗ thì không cần câu nào: chỗ duy nhất thấy ảnh tiến độ là tab Tiến độ, xoá ở đó là xoá, hết.

**Nguyên tắc lăng kính vẫn giữ cho tài liệu**, và ở đó nó đúng: tab Tài liệu hiện **toàn bộ** `documents` với thanh lọc theo loại — lọc là lăng kính thật, không phải ngăn chứa, vì cùng một bảng và người dùng thấy rõ mình đang lọc.

**Hệ quả phải nói ra trên UI:** tab Media không còn là "kho tổng của mọi ảnh". Câu chữ của nó (vòng 1 Task 7 viết) phải sửa lại, nếu không nó *khẳng định một điều sai* — đúng hạng lỗi đã nổ bốn lần trên nhánh vòng 1.

## 4. Chín thay đổi

### 4.1 Bộ tab: mười → chín

```
tong-quan · vi-tri · anh-360 · mat-bang · phan-khu · quy-can · tien-do · media · tai-lieu
```

Ba phép đổi so với vòng 1:
- `mat-bang` chuyển lên **trước** `phan-khu` (đọc mặt bằng rồi mới vào phân khu)
- `media` chuyển xuống **sau** `tien-do` (kho tổng mở sau cùng, trước Tài liệu)
- `csbh` **bỏ** — nó là một loại trong tab Tài liệu (§4.6)

`tabHopLe()` phải ánh xạ `?tab=csbh` → `tai-lieu`, nối vào bảng `TAB_CU` đã có (`thong-tin`→`tong-quan`, `can`→`quy-can`). Link cũ đồng nghiệp đã gửi không được chết.

Điều kiện khoá tab lúc tạo mới (`KhungDuAn.tsx`, `!code && t.id !== 'tong-quan'`) suy theo `id` nên tự đúng với chín tab — nhưng cổng canh của nó suy danh sách từ `TAB_DU_AN`, nên nó cũng tự theo.

### 4.2 Tab Media: folder hai mức, bốn danh mục

**Mức 1 — bộ folder.** Lưới thẻ, mỗi thẻ một danh mục: ảnh bìa (ảnh đầu của danh mục, hoặc ô trống có nhãn), tên danh mục, số lượng (`N ảnh · M video`, video đếm riêng). Bấm vào thẻ → mức 2.

**Mức 2 — trong một folder.** Đường dẫn `‹ Mọi danh mục / Tổng quan`, nút Thêm, lưới ảnh của **riêng** danh mục đó. Nút quay lại về mức 1.

Mức đang xem sống ở **state của component**, không ở URL: thêm một search param thứ hai (`?tab=media&folder=noi_that`) là thêm một nguồn sự thật cho một trạng thái không ai deep-link tới. Đổi tab rồi quay lại Media thì về mức 1 — đúng, vì `DuAnForm` render mỗi tab từ một khe riêng nên component remount.

Cả bốn danh mục vẫn dùng **cùng** query key `['re', code, 'media']` với một lần nạp — folder chỉ là phép lọc client-side trên danh sách đã có, không phải bốn query. (Sau §4.8, `limit` của query này đổi theo phân trang; xem §6 *Rủi ro*.)

### 4.3 Bỏ trần 6 ảnh

| Chỗ | Hiện tại | Sau |
|---|---|---|
`router.py:789` | `TRAN_ANH_MOI_DANH_MUC = 6` | bỏ hằng |
`router.py:834` | `if dang_co >= TRAN_ANH_MOI_DANH_MUC: raise` | bỏ nhánh |
`router.py:112` | câu lỗi `Tối đa {n} ảnh cho mỗi danh mục…` | bỏ hàm dựng lỗi nếu không còn ai gọi |
`enums.ts:127` | `TRAN_ANH = 6` | bỏ hằng |
`VungMedia.tsx:30,58,96` | `day = soAnh >= TRAN_ANH`; `{soAnh}/{TRAN_ANH} ảnh`; câu "Đã đủ 6 ảnh" | bộ đếm thành `{soAnh} ảnh`; bỏ `day`, bỏ câu |
`CanForm.tsx:530,537,586,592` | cùng khuôn, cho ảnh **căn** | bỏ hết — trần bỏ ở **mọi** cấp |
`MediaTab.tsx:49` | câu "Mỗi danh mục nhận tối đa 6 ảnh" | bỏ (câu này viết lại ở §4.2 rồi) |
`thongDiep.ts:39-40` | hai câu dịch lỗi trần | bỏ nhánh |

Backend là nguồn sự thật của trần, nên **phải bỏ ở backend trước hoặc cùng lúc**: bỏ ở FE trước thì nút Thêm mở khoá và mọi lần upload thứ bảy trả 409 mà UI không còn câu nào giải thích.

### 4.4 Bỏ ô Trạng thái — `status` thành giá trị **suy ra**

Đây là thay đổi có hệ quả sâu nhất của vòng này, vì `status` là **công tắc quyết định agent có đọc bản ghi hay không**: `agent_api.projects` lọc `WHERE status = 'published'` ([0401_agent_doc_kb.py:137](../../../migrations/versions/0401_agent_doc_kb.py)), và bốn view con (`zones`/`units`/`documents`/`media`) cascade qua nó. Mặc định của DB là `'draft'` ([0400:97](../../../migrations/versions/0400_kb_real_estate.py)).

**Bỏ ô mà không gửi gì** ⇒ mọi bản ghi mới nằm ở `draft` ⇒ agent trả lời "không có dự án nào". Sai, và im lặng.
**Luôn gửi `published`** ⇒ không tạo được dự án nữa: cổng `_chan_tao_moi_thieu` (`router.py:200-213`) từ chối 422 khi thiếu `name`/`region`/`overview`, nên lần Lưu đầu của một dự án mới luôn bị chặn.

**Cách chọn: FE tính `status` từ completeness.**

```
đủ trường bắt buộc  → status = 'published'
còn thiếu           → status = 'draft'
```

Việc này chạy được **không sửa backend một dòng nào**, vì cả hai cổng completeness chỉ áp khi bản ghi *sắp thành* `published`:
- `_chan_tao_moi_thieu` (`router.py:211`): `if ban_ghi_moi.get("status") != "published": return`
- `_chan_publish_thieu` (`router.py:194`): `if trang_thai_moi != "published": return`

Nên `draft` thiếu trường vẫn lưu được, `published` đủ trường vẫn qua cổng. Luật completeness đã có sẵn ở FE (`completeness.ts`, `BAT_BUOC.project = name·region·overview`, `BAT_BUOC.unit = priceVnd·areaBuiltM2·saleStatus`) và nó **chép nguyên văn** luật Python — đây đúng là chỗ dùng nó.

**Ba entity không có luật completeness** (`zones`, `documents`, `media`) → luôn gửi `'published'`. `VungMedia.tsx:40` và `CanForm.tsx:511` đã hardcode như vậy từ trước, nên đây là mở rộng một nếp đã có, không phải nếp mới.

**Trạng thái vô hình phải thành trạng thái nhìn thấy được.** Nhãn "Còn thiếu để phát hành: Khu vực, Tổng quan" đã tồn tại ở hai chỗ (badge trên bảng danh sách, nhãn cạnh nút Lưu). Nay nó là **thứ duy nhất** cho người dùng biết agent chưa đọc bản ghi này, nên câu chữ phải nói đúng điều đó — không phải "chưa phát hành được" (một hành động họ không còn làm được) mà "**agent chưa đọc dữ liệu này — còn thiếu Khu vực, Tổng quan**".

**Chỗ phải bỏ khai `status`:**

| File | Việc |
|---|---|
`TongQuanTab.tsx:184` | bỏ `OChon` Trạng thái |
`TomTatDuAn.tsx:48` | bỏ dòng xem Trạng thái |
`TaiLieuTab.tsx:453` | bỏ `OChon` Trạng thái (và `goiY` "Chỉ Đã phát hành thì agent mới đọc") |
`TaiLieuTab.tsx:173,355` | bỏ dòng xem + cột bảng |
`CanTab.tsx:222` · `PhanKhuTab.tsx:384` | bỏ cột/badge |
`TomTatCan.tsx:67` | bỏ dòng xem |
`DuAnList.tsx:146,220,286-291` | bỏ ô lọc theo trạng thái, bỏ badge, bỏ hàm màu badge |
`CanForm.tsx:168,421,429-437` | `chanPublish` và ba câu quanh nó viết lại theo nghĩa mới |
`enums.ts` | `TRANG_THAI` chỉ còn dùng nội bộ để tính, **không** export cho UI |

⚠️ **`archived` mất đường vào từ UI.** Bản ghi đang `archived` vẫn `archived` trong DB, agent vẫn không đọc, và nay **không còn cách nào đưa nó về `published` từ Portal**. Ba lựa chọn — (a) chấp nhận, xử bằng SQL khi cần; (b) FE coi `archived` như `draft` và ghi đè thành `published` khi đủ trường; (c) giữ một ô ẩn ở đâu đó. Spec chọn **(a)**: `archived` chưa có đường tạo nào từ UI hiện tại nên trên dữ liệu thật gần như không tồn tại; thêm cơ chế cho một trạng thái không ai tạo là YAGNI. Ghi lại ở §6 để người sau không kết luận là bỏ sót.

⚠️ **Row sentinel `__ALL__`** luôn `published` và được miễn completeness (`_bo_qua_completeness_du_an`), đồng thời bị ẩn khỏi `liet_ke_du_an` — nên FE không bao giờ thấy nó và phép suy `status` không với tới nó. Không cần nhánh riêng.

### 4.5 Tab Mặt bằng: một vùng ảnh duy nhất

Tab hiện có **hai** khối: `NhomTruong "Mặt bằng tổng thể"` bọc một `OMedia` ghi vào cột `projects.map_media_id`, cộng một `VungMedia` cho danh mục `mat_bang`. Hai khối cho **một** khái niệm.

Sau vòng này: **một** `VungMedia` cho `mat_bang`, hết. `mapMediaId` **luôn null** — không còn khái niệm "ảnh mặt bằng chính", agent trả cả bộ ảnh `mat_bang`.

Kéo theo: bỏ `OMedia`, bỏ mutation `suaDuAn({mapMedia})`, bỏ nút "Lưu mặt bằng tổng", bỏ state `mapMedia` — nên tab này thôi giữ dữ liệu chưa lưu và thôi cần cờ `dirty` cùng `key={duAn.projectCode}`. Cả hai cổng canh của chúng phải bỏ theo, **không** để lại test canh một cơ chế đã biến mất.

⚠️ **Cần repo `odyssey-agent` đổi theo** — xem §7. Cho đến khi đó, agent đọc `map_media_id` sẽ nhận `null` và trả lời "chưa có mặt bằng" cho dự án **có** ảnh mặt bằng. Đây là một khoảng hồi quy có chủ ý, người yêu cầu đã được cảnh báo và chọn phương án này.

### 4.6 Bỏ tab CSBH

CSBH đã là một giá trị `loai` trong tab Tài liệu từ vòng 1, và tab CSBH là **cùng** component `TaiLieuTab` với `loaiKhoa="csbh"`. Bỏ tab ⇒ bỏ nhánh render đó khỏi `DuAnForm`, bỏ mục khỏi `TAB_DU_AN`, thêm ánh xạ `TAB_CU`.

Prop `loaiKhoa` của `TaiLieuTab` thành **không consumer nào dùng**. Bỏ nó — cùng với `locHieuLuc`, nhánh câu rỗng theo `loaiKhoa`, điều kiện `!loaiKhoa` quanh thanh lọc, và ba cổng canh của chúng. Giữ một prop không ai truyền là YAGNI, và ba test canh nó thành ba test canh code chết.

### 4.7 Tab Tài liệu: badge màu theo loại

Cột **Loại** hiện badge có màu; pill tương ứng trên thanh lọc dùng **cùng** màu, để mắt nối được pill vừa bấm với hàng vừa lọc.

Theo khuôn `MAU_TRANG_THAI` ở `features/kb/components/TaiLieuList.tsx:69` (đã có tiền lệ map giá trị → class màu). **Không viết màu thô vào component** — thêm **token** vào `src/styles/theme.css` rồi dùng qua class, đúng nếp của ba cặp badge đang có.

Ba cặp badge hiện có mang **nghĩa trạng thái**, không dùng lại được cho phân loại: `badge-alert` (đỏ) đọc thành "lỗi", `badge-warn` (hổ phách) đọc thành "đang chờ", và `--color-ac` (xanh `#0d7a5f`) theo docstring `TaiLieuList.tsx:63-67` **dành riêng cho hành động chính** — tô một phân loại bằng nó thì mắt bị kéo về một hàng không cần ai làm gì. Nên thêm ba cặp mới, và dùng lại `badge-neutral` cho `khac` (thùng chưa phân loại đúng là màu trung tính):

| Loại | Token | bg | fg | Tương phản |
|---|---|---|---|---|
`csbh` | `--color-badge-doc-csbh-*` | `#e8f0fb` | `#1f5aa8` | **5.93** |
`phap_ly` | `--color-badge-doc-phaply-*` | `#f0ecfa` | `#5b45a8` | **6.32** |
`huong_dan` | `--color-badge-doc-huongdan-*` | `#e6f2f4` | `#1f6b7a` | **5.34** |
`khac` | `badge-neutral` (**đã có**) | `#f0efec` | `var(--color-n8)` | 7.17 |

Ba tỉ lệ trên đo bằng WCAG relative luminance, đều vượt 4.5 và nằm cùng khoảng với hai cặp đang có (`alert` 4.98, `warn` 5.27) — `theme.css` có nếp ghi số đo ngay cạnh giá trị, giữ nếp đó. `theme.css` hiện **không có block dark**, nên không cần cặp thứ hai.

Ba hue chọn (lam-dương · tím · lam-lục) tách được khỏi đỏ/hổ phách/xanh-accent, nên không loại nào bị đọc lẫn thành trạng thái.

Ngoài màu: bỏ cột Trạng thái (§4.4) và thêm phân trang (§4.8) — hai việc đó làm bảng gọn hơn nhiều so với việc chỉ thêm màu.

`nhanCua()` trả **chính `value`** khi không tìm thấy nhãn, nên một `loai` lạ (dữ liệu cũ, hoặc backend thêm loại thứ năm) sẽ hiện mã máy `csbh_moi` **và không có màu**. Bảng màu phải có nhánh mặc định, nếu không class là `undefined` và badge mất nền.

### 4.8 Phân trang có số trang

Backend hiện phân trang bằng **cursor** (`Trang*.nextCursor`), không có tổng số hàng, nên "Trang 3/12" là không dựng được. Đổi cả hai đầu:

**Backend** — năm endpoint danh sách (`/projects`, `…/zones`, `…/units`, `…/documents`, `…/media`):
- nhận thêm `offset: int = 0`
- trả thêm `total: int` (một `COUNT(*)` cùng mệnh đề `WHERE` của truy vấn chính, trong **cùng** giao dịch `tenant_conn` — hai giao dịch rời nhau cho `total` lệch khỏi `items`)
- `nextCursor` **giữ lại**, không bỏ: nó là hợp đồng đang dùng, và bỏ một field khỏi response là phá vỡ với mọi client khác

Kẹp `offset` cùng lối `_gioi_han` đã kẹp `limit` (`repo.py:181`, trần `GIOI_HAN_TRANG = 200`). `offset` âm → 0.

**Frontend** — thay `useTrangCuon` (cuộn-nối) bằng một hook phân trang mới cho các **bảng**: `useTrangSo` giữ `trang` + `soHang`, gọi `nap({limit, offset})`, trả `{items, total, soTrang}`. Thanh phân trang: `‹ 1 2 [3] 4 5 … 12 ›`, câu "Hiện 41–60 / 237", và ô chọn số hàng (20/50/100).

`useTrangCuon` **không xoá** — nó vẫn đúng cho media (§4.2 nạp một lần rồi lọc client-side) và cho bất cứ chỗ nào không phải bảng. Hai hook cho hai kiểu nạp, mỗi cái một việc rõ.

### 4.9 Tab Quỹ căn: thêm cột Hướng

`direction` đã có trên cả kiểu đọc (`api.ts:136`) và kiểu ghi (`api.ts:251`), enum `HUONG` đã có (`enums.ts:67`), và form căn đã cho nhập. Chỉ thiếu cột trên bảng.

Chèn cột **Hướng** vào `COT` của `CanTab` — đặt sau `DT thông thuỷ`, trước `Giá`: hướng là thuộc tính vật lý của căn, thuộc nhóm với diện tích, không thuộc nhóm thương mại (giá/tình trạng bán). Render `nhanCua(HUONG, c.direction)`.

⚠️ Thêm một cột vào `COT` mà quên thêm `<td>` (hoặc ngược lại) làm **mọi cột sau nó lệch nhãn** mà không test nào đỏ — vòng 1 đã đo được đúng chuyện này với cột Loại của tài liệu. Cần cổng canh `role="columnheader"` cho cột mới.

### 4.10 Tab Tổng quan: năm nhóm → ba

Vòng 1 chia tab Tổng quan thành năm nhóm. Vòng này gộp còn ba:

| Nhóm | Ô |
|---|---|
**Tổng quan** | `projectCode` · `name` · `salePhase` · `category` · `investor` · `developer` · `amenities` · `overview` · Ảnh cover |
**Quy mô & mật độ** | `totalLandAreaM2` · `floorAreaM2` · `buildDensityPct` · `productScale` · `totalInvestmentVnd` |
**Sở hữu & bàn giao** | `ownershipForm` · `handoverStandard` |

Ba nhóm cũ — "Định danh & phân loại", "Chủ đầu tư", "Mô tả" — biến mất; nội dung của chúng vào nhóm **Tổng quan**. Ô `status` bỏ hẳn (§4.4), nên tab còn **15 ô `projects` + 1 ô media**.

Thứ tự trong nhóm Tổng quan đi từ *nhận diện* (mã, tên) → *phân loại* (giai đoạn bán, loại hình) → *ai làm* (chủ đầu tư, đơn vị phát triển) → *kể về nó* (tiện ích, tổng quan, ảnh) — đúng thứ tự một người giới thiệu dự án bằng lời.

⚠️ **Chế độ XEM (`TomTatDuAn.tsx`) phải đổi cùng lúc.** Vòng 1 sập đúng hố này bốn lần: `GiaTri` render giá trị rỗng thành chữ **«Chưa đặt»**, nên một ô còn ở chế độ xem mà `tuDuAn()` thôi copy sẽ *khẳng định một điều sai*. Cổng canh so tập nhãn ô hai chế độ (đã dựng ở vòng 1) sẽ bắt được — **nếu** nó được cập nhật cùng, không bị allowlist nới rộng cho qua.

## 5. Bề mặt thay đổi

### Backend (`odyssey-portal-backend`)

| File | Thay đổi |
|---|---|
`modules/realestate/router.py` | bỏ trần ảnh (§4.3); `offset` + `total` cho 5 endpoint danh sách (§4.8) |
`modules/realestate/contracts.py` | `Trang*` thêm `total: int` |
`modules/realestate/repo.py` | `offset` + hàm đếm cho 5 truy vấn danh sách |
`docs/contracts/mat-bang-agent.md` | **file mới** — hợp đồng §7 |

Không migration. Không đụng `completeness.py` (§4.4 dùng đúng luật đang có).

### Frontend (`odyssey-portal-frontend`)

| File | Thay đổi |
|---|---|
`tabDuAn.ts` | 9 tab, thứ tự mới, `TAB_CU` thêm `csbh` |
`components/MediaTab.tsx` | folder hai mức, 4 danh mục, câu chữ mới |
`components/VungMedia.tsx` | bỏ trần |
`components/MatBangTab.tsx` | một vùng ảnh, bỏ `mapMedia`/`dirty`/`key` |
`components/TongQuanTab.tsx` | ba nhóm, bỏ ô Trạng thái, `status` suy ra |
`components/TomTatDuAn.tsx` | ba nhóm khớp chế độ sửa, bỏ dòng Trạng thái |
`components/TaiLieuTab.tsx` | badge màu, bỏ `loaiKhoa`, bỏ Trạng thái, phân trang |
`components/CanTab.tsx` | cột Hướng, bỏ Trạng thái, phân trang |
`components/PhanKhuTab.tsx` | bỏ Trạng thái, phân trang |
`components/CanForm.tsx` | bỏ trần ảnh căn, `status` suy ra, ba câu quanh `chanPublish` |
`components/DuAnList.tsx` | bỏ lọc + badge trạng thái, phân trang |
`components/DuAnForm.tsx` | 9 nhánh render, bỏ `csbh`, câu tạo mới suy từ `TAB_DU_AN` |
`components/useTrangSo.ts` | **file mới** — hook phân trang có số |
`enums.ts` | bỏ `TRAN_ANH`, thêm bảng màu loại tài liệu |
`api.ts` | `Trang<T>` thêm `total`; các hàm danh sách nhận `offset` |
`completeness.ts` | **không sửa** — chỉ được đọc thêm bởi chỗ tính `status` |

## 6. Rủi ro và giới hạn đã biết

**Khoảng hồi quy của mặt bằng.** `mapMediaId` thành null trước khi repo `odyssey-agent` đổi sang đọc cả bộ (§7). Trong khoảng đó agent trả lời "chưa có mặt bằng" cho dự án có ảnh. Nếu cần tránh: để FE tự đặt `mapMediaId` = ảnh đầu như lưới an toàn, gỡ sau khi repo kia xong — một dòng, và spec này không chọn nó vì người yêu cầu đã quyết.

**`archived` không còn đường vào từ UI** (§4.4). Chấp nhận có chủ ý.

**Media nạp một lần, không phân trang.** §4.2 giữ nguyên lối "nạp hết rồi lọc client-side" của vòng 1 để bốn folder không lệch số đếm nhau. Với `limit` hiện tại (200) và trần ảnh vừa bỏ, một dự án >200 media sẽ **thiếu ảnh ở folder mà không có dấu hiệu nào**. Vòng 1 đã gặp đúng hạng lỗi này với thanh lọc tài liệu và vá bằng câu chữ ("Số đếm chỉ tính phần đã tải"). Tab Media cần cùng cách vá — hoặc nâng `limit`, và nói ra khi còn trang sau.

**Thanh phân trang và bộ lọc loại tài liệu đá nhau.** Lọc là client-side trên **trang hiện tại**, nên "CSBH 4" nghĩa là 4 trong 20 hàng của trang này, không phải 4 trong 237 hàng của dự án. Câu chữ phải nói ra, cùng lối vòng 1 đã vá.

**Bỏ trần ảnh mở đường cho upload hàng loạt vô ý.** Không còn phanh nào ở tầng dữ liệu. Chấp nhận: trần 6 là con số của mockup, không phải của nghiệp vụ, và MinIO không tính phí theo số object ở môi trường này.

**`total` là một `COUNT(*)` mỗi request.** Trên bảng `units` của một dự án lớn, đây là một lần quét thêm. Chấp nhận ở quy mô hiện tại; nếu chậm thì đây là chỗ đầu tiên nhìn.

## 7. Hợp đồng gửi repo `odyssey-agent`

Ghi vào `docs/contracts/mat-bang-agent.md` (**file mới**, không sửa hợp đồng nào đang có) và **copy tay** sang repo kia — không có job CI nào so hai bên.

**Đang có:** agent đọc `agent_api.projects.map_media_id` (cột nằm trong `_COT_DU_AN`, [0401_agent_doc_kb.py:100-105](../../../migrations/versions/0401_agent_doc_kb.py)) để trả lời "cho xem mặt bằng dự án".

**Sau vòng này:** `map_media_id` **luôn `NULL`** với mọi dự án Portal tạo/sửa. Agent phải đổi sang:

```sql
SELECT id, media_url, thumb_url, caption
  FROM agent_api.media
 WHERE project_code = $1
   AND zone_code IS NULL AND unit_code IS NULL
   AND category = 'mat_bang'
 ORDER BY created_at
```

`agent_api.media` đã có đủ cột cần (`category` nằm trong `_COT_MEDIA`, [0401:116-119](../../../migrations/versions/0401_agent_doc_kb.py)) và đã `GRANT SELECT` cho `agent_all`. **Không cần migration.**

Cột `map_media_id` **không bị xoá** — giữ để dữ liệu cũ không mất và để repo agent đổi được theo nhịp riêng. Nhưng đừng đọc nó nữa: một dự án cũ còn `map_media_id` khác null và một dự án mới có null sẽ cho hai hành vi khác nhau cho cùng một câu hỏi.

## 8. Thứ tự thi công

Backend trước, vì FE phụ thuộc cả hai thay đổi của nó:

1. **Backend §4.3** bỏ trần ảnh — độc lập, không ai chờ.
2. **Backend §4.8** `offset` + `total` — FE không dựng được phân trang trước khi có `total`.
3. **Backend §7** viết `docs/contracts/mat-bang-agent.md`.
4. **FE §4.1** bộ tab 9 + ánh xạ link cũ — mọi thay đổi tab sau đó dựa lên đây.
5. **FE §4.4** `status` suy ra — đụng nhiều file nhất, và mọi form đều liên quan; làm sớm để các task sau không phải sửa lại chỗ khai `status`.
6. **FE §4.5** Mặt bằng một vùng · **§4.6** bỏ tab CSBH — hai việc bỏ, làm sau §4.1.
7. **FE §4.2** Media folder — phụ thuộc §4.3 (trần) và §4.1 (thứ tự tab).
8. **FE §4.8** phân trang các bảng — phụ thuộc backend bước 2.
9. **FE §4.9** cột Hướng · **§4.7** badge màu · **§4.10** ba nhóm Tổng quan — ba việc độc lập, làm cuối.

## 9. Trôi tài liệu

Vòng 1 để lại hai chỗ nói sai mà spec này **không** sửa (chúng có trước, ngoài phạm vi): `DuAnForm.tsx:5` và `KhungDuAn.tsx:5` nói `routes/_app` khoá ở "18 file .tsx" trong khi thực tế là 25.

Vòng này **tự sinh ra** trôi mới nếu không cẩn thận, vì mọi comment nói "mười tab", "bảy vùng media", "trần 6 ảnh", "năm nhóm", "16 ô" đều thành sai. Vòng 1 đã phải dọn ~18 dòng như vậy ở cuối. Cách không lặp lại: mỗi task sửa comment **trong cùng commit với code**, không dồn về cuối.

`CLAUDE.md` của backend có mục "Tự bảo trì file này" — bỏ trần ảnh và thêm `total`/`offset` là **đổi hợp đồng với repo khác**, nên phải kèm một dòng Change Log trong cùng commit.
