# Playbook thành template — Đợt 3: màn `/kich-ban` sửa được

Ngày: 2026-10-06 · Trạng thái: chờ duyệt · Phạm vi: **Đợt 3/3** (portal-frontend + một trường ở portal-backend)
Nền (repo `odyssey-agent`, `docs/superpowers/specs/`): `2026-10-06-playbook-template-dot-1-design.md` (mục tiêu chung,
khuôn nút §2, phác thảo Đợt 3) · `2026-10-06-playbook-template-dot-2-design.md` (bảng `kich_ban`, API, luật kiểm,
hash nút). Đợt 2 đã merge: agent !182, portal-backend !156 (`5fba438`).

## Mục tiêu

Trên `/kich-ban`, người có quyền `agent_config.write` sửa được kịch bản của workspace: sửa / thêm / xoá / bật-tắt từng
tình huống lớp sale, so với mẫu NobleX, áp lại mẫu, bật kịch bản theo role. Lớp hệ thống chỉ xem. Người chỉ có
`agent_config.read` thấy màn như hôm nay cộng trạng thái bản riêng.

**Đạt khi:** sửa một tình huống trên màn → lượt chat sau agent làm theo chữ mới (`meta.playbook.h` của lượt = `hash`
màn hiện) và số đo của riêng tình huống đó đếm lại từ đầu; role tắt thì agent không nhận chỉ dẫn kịch bản.

## Quyết định (người dùng chốt 2026-10-06)

1. **Lưu từng tình huống**, không bản nháp cả bộ: mỗi thao tác (lưu form, thêm, xoá, bật-tắt, dùng bản mẫu, thêm từ
   mẫu) là một `PUT /playbook` cả bộ với đúng một thay đổi. Không cần cơ chế bản nháp thứ hai như `/agent`
   (`useBanNhap`), và lần ghi nhỏ thì ít đụng người khác (409).
2. **Công tắc role đặt trên `/kich-ban`** (dải trạng thái), không trên tab role ở `/agent` — **lệch phác thảo Đợt 1**:
   `/agent` gom mọi thay đổi vào bản nháp + «Lưu và áp dụng»; công tắc ghi ngay bằng API khác phá luật đó, còn gộp vào
   bản nháp thì một lần Lưu thành hai request, hỏng một là lưng chừng. Danh sách role đọc qua `agent/contracts`
   (`docCauHinh`, `CAU_HINH_QUERY` — chung cache với `/agent`).
3. **`GET /playbook/template` trả thêm `gioiHan`** (MR backend nhỏ, merge trước FE) — **lệch câu "Đợt 3 chỉ làm FE"
   của spec Đợt 2**: FE cần danh sách nhóm / kênh / tool và các trần để dựng form, chép tay thì lệch agent không test
   nào bắt.
4. **So với mẫu theo từng tình huống** (nhãn giống / khác / riêng / chưa có, xem hai bản cạnh nhau, dùng bản mẫu cho
   một tình huống, thêm tình huống mẫu còn thiếu) + «Áp lại mẫu NobleX» cả bộ có xác nhận nói rõ mất gì. Không diff
   từng dòng.
5. **Form nằm trong khung chi tiết** (chế độ Xem / Sửa; desktop nới 376 → 560px khi sửa; điện thoại trong bottom sheet
   sẵn có). Không route mới, không modal.

## 1. Backend (portal-backend, MR riêng, merge trước)

`modules/playbook/contracts.py`: `TemplateOut` thêm `gioiHan: dict`. `router.xem_template` trả
`gioiHan=nut.gioi_han()`. Test: `GET /playbook/template` có `gioiHan` bằng đúng `nut.gioi_han()`. `CLAUDE.md` thêm
một dòng Change Log. Chỉ thêm trường — client cũ không vỡ.

## 2. Dữ liệu phía FE

**Nguồn:** `GET /playbook` (nodes đang chạy, khuôn `playbook.json` + trường tương thích + `hash`, `lop`, `khoaXoa`;
khối `kichBan`) và `GET /playbook/template` (`{templateVersion, nodes, gioiHan}`, static, cache lâu).

**Payload dựng từ `GET /playbook`, không từ bản FE tự giữ.** BE đã lọc tool agent gỡ ra khỏi `nodes` (`tuong_thich`),
nên dựng `PUT` từ đó thì không bao giờ gặp 422 trên tình huống người dùng không sửa (ghi chú "cho đợt 3" của MR !156).

**Khuôn `NutVao`** (gửi lên; BE `extra="forbid"`): `id, ten, nhom, bat, kenh[], dau_hieu[], lam[], tool[], cam[],
khi_thieu, cau_ket, lan_2, chi_lan_2, nguon, buoc[{id, lam}]`. `veKhuon` lấy đúng các khoá này, `buoc` bỏ `tool`;
trường tương thích (`trang_thai`, `loai`, `dieu_kien`, `tiep`, `can_du_lieu`) và `hash`, `lop`, `khoaXoa` không gửi.
`nguon` giữ nguyên (ẩn khỏi form); tình huống mới `nguon: ""`.

**Lớp sale** = `nodes.filter(lop === 'sale')`, giữ thứ tự BE trả; tình huống mới nối cuối.

**Kiểu thêm vào `api.ts`** (chép tay từ `contracts.py`, như sẵn có): `KichBan` (= `KichBanOut`), `GioiHan`,
`NutVao`, `TemplateOut`; `NutKichBan` thêm `hash`, `lop`, `khoaXoa`, `bat`, `lan_2`, `chi_lan_2`, `cau_ket`;
`DuLieuKichBan` thêm `kichBan`. Màn tiếp tục đọc trường tương thích ở phần xem (sơ đồ, chi tiết) — chuyển hẳn sang
trường khuôn mới là việc riêng, trước khi BE bỏ trường tương thích.

## 3. Luồng ghi

Một hàm `ghi(bienDoi: (bo: NutVao[]) => NutVao[])` cho mọi thao tác trên tình huống:

1. Lấy `data` của lần tải `GET /playbook` mới nhất (query của màn) → `bo = sale(data.nodes).map(veKhuon)`.
2. `moi = bienDoi(bo)`; kiểm phía client (mục 6) — có lỗi thì dừng, hiện lỗi.
3. `PUT /playbook {version: data.kichBan.version, nut: moi}`.
4. Thành công → làm mới mọi query `['kich-ban', …]` và **đợi tải xong** mới mở lại nút ghi (mutation `onSuccess` trả
   promise `invalidateQueries`) — lần ghi sau không cầm `version` cũ. `useTenKichBan` (thẻ nút ở `/convos`) dùng chung
   cache nên tự nhận tên mới.

`POST /playbook/ap-dung {version}` cho «Áp lại mẫu NobleX»; `PUT /playbook/role-dung {version, roles}` cho công tắc
role. Cả hai cũng làm mới `['kich-ban']` sau khi xong.

**Quyền:** `useSession().can([ACTIONS.AGENT_CONFIG_WRITE])`. Không có → không render nút ghi (Sửa, Xoá, Thêm, Áp lại,
Dùng bản mẫu, Thêm vào, công tắc bật-tắt); công tắc role hiện dạng khoá.

**Không làm:** nút «Áp dụng» riêng ở trạng thái mẫu — lần lưu đầu tiên tự tạo bản riêng (BE: `PUT` khi chưa áp dụng
= áp dụng), form báo trước. Đổi thứ tự bước. Lịch sử phiên bản / hoàn tác.

## 4. Màn hình

### 4a. Dải trạng thái (`DaiTrangThai`, đầu màn, trên hàng bộ lọc)

| `kichBan` | Dòng 1 | Hành động (có quyền ghi) |
|---|---|---|
| `trangThai: "mau"` | «Đang dùng kịch bản mẫu NobleX — agent tự nhận bản mẫu mới.» | dặn: «Sửa một tình huống bất kỳ sẽ tạo bản riêng cho workspace.» |
| `"rieng"` | «Bản riêng của workspace · sửa lần cuối dd/mm hh:mm» (`capNhatLuc`) | [So với mẫu (n khác · m chưa có)] · [Áp lại mẫu NobleX] |
| `"rieng"` + `coTemplateMoi` | tông cảnh báo: «NobleX có bản mẫu mới.» | hai nút như trên, nút So với mẫu nổi |

Dòng 2: «Agent dùng kịch bản khi nói chuyện với:» + một `CongTac` cho mỗi role của workspace (nhãn = tên role), bật ⇔
role ∈ `roleDung`. Bấm → `PUT /role-dung` với tập mới (chỉ role đang có; role trong `roleDung` mà workspace đã xoá thì
bỏ khi gửi). Tắt hết → dòng phụ «Agent không dùng kịch bản với role nào.» Đang gửi → công tắc khoá.

### 4b. Khung chi tiết — chế độ Xem (`BangChiTiet`)

- Chip mới: `lop === 'he_thong'` → «Hệ thống NobleX — chỉ xem»; trạng thái riêng + lớp sale → «Giống mẫu» / «Khác
  mẫu» / «Riêng của workspace» (mục 5). Chip «Bản nháp — chưa áp dụng» → «Đang tắt — agent không chọn»; chú giải
  «bản nháp» → «đang tắt».
- Hàng nút (lớp sale, có quyền): [Sửa] · `CongTac` «Đang dùng» (ghi ngay, đảo `bat`) · [Xoá] — **không có Xoá** khi
  `khoaXoa` (agent chỉ bắt buộc có mặt; tắt được).
- Tình huống «Khác mẫu»: [Xem bản mẫu] — chỉ các mục khác nhau, «Bản của bạn» trên, «Bản mẫu» dưới (nền `fill`);
  [Dùng bản mẫu] — xác nhận trong trang «Thay «X» bằng bản mẫu? Chữ hiện tại sẽ mất.» → `ghi(thayNut(mau))`.

### 4c. Khung chi tiết — chế độ Sửa (`FormNut`)

Desktop: khung 560px khi sửa/thêm (376px khi xem). Thứ tự ô (nhãn cho trưởng phòng kinh doanh, không mã):

| # | Ô | Trường | Điều khiển · luật (`gioiHan`) |
|---|---|---|---|
| 1 | Tên tình huống * | `ten` | `OChu`, đếm /`maxTen` |
| 2 | Nhóm * | `nhom` | `OChon`, `gioiHan.nhom` xếp theo `THU_TU_NHOM`, nhãn `TEN_NHOM` |
| 3 | Kênh | `kenh` | ba lựa chọn: Cả chat và cuộc gọi `[]` / Chỉ chat `["chat"]` / Chỉ cuộc gọi `["voice"]` |
| 4 | Khi nào dùng * | `dau_hieu` | `ODanhSachDong` ≤ `maxDong.dau_hieu` ý, mỗi ý ≤ `maxKyTu`, `" \| ".join` ≤ `maxDauHieuTong`. Gợi ý: «Tả lời khách nói để agent nhận ra tình huống. Nhắc tình huống khác bằng tên, không bằng mã.» |
| 5 | Agent làm gì * | `lam` | ≤ `maxDong.lam` ý × `maxKyTu` |
| 6 | Các bước | `buoc` | ≤ `maxBuoc` bước × `maxKyTu`; «Để trống nếu xử lý trong một lượt». Bước cũ giữ `id`; bước mới `id` = `b<n>` nhỏ nhất chưa dùng |
| 7 | Không được làm | `cam` | ≤ `maxDong.cam` ý, tổng ≤ `maxCamTong` |
| 8 | Kỹ năng nên dùng | `tool` | `OChonNhieu` từ `gioiHan.tool`, nhãn `nhanKyNang` (`no_lookup_needed` → «Không cần tra cứu»), ≤ `maxTool` |
| 9 | Khi thiếu tài liệu | `khi_thieu` | ≤ `maxCau` |
| 10 | Câu kết hỏi khách | `cau_ket` | ≤ `maxCau`; «Agent tự bỏ khi đang hỏi trước» |
| 11 | Khi khách lặp lại lần 2, chuyển sang | `lan_2` | `OChon`: «Không chuyển» `""` / tên mọi tình huống khác (sale ∪ hệ thống), trừ chính nó |
| 12 | Chỉ dùng khi được chuyển tới | `chi_lan_2` | ô chọn; khoá kèm lý do khi không tình huống nào (sale ∪ hệ thống) có `lan_2` trỏ tới nó |

- `ODanhSachDong` (component mới trong module): mỗi ý một ô tự giãn cao, ✕ bỏ ý, «+ Thêm ý» khoá khi đủ trần; đếm
  ký tự mỗi ý và tổng (khi có trần tổng). Ý rỗng bỏ khi gửi (BE coi «có dòng rỗng» là lỗi).
- Lỗi hiện ngay dưới ô (`Truong.tsx`: `aria-invalid` + `aria-describedby`). Bấm Lưu khi còn lỗi → không gửi, focus ô
  lỗi đầu tiên.
- Cạnh nút Lưu: «Lưu xong, số đo tình huống này đếm lại từ đầu.» Trạng thái mẫu thêm: «Lần lưu này tạo bản riêng cho
  workspace: từ đó agent dùng bản của bạn; mẫu NobleX mới chỉ được báo ở đầu màn, không tự cập nhật.»
- Đang sửa dở (form khác giá trị lúc mở) mà Huỷ / đóng khung / chọn tình huống khác → hỏi trong trang «Bỏ phần đang
  sửa?» (không `confirm()`).

### 4d. Thêm tình huống

Nút [Thêm tình huống] ở hàng bộ lọc (có quyền; khoá kèm `title` «Đã đủ N tình huống» khi lớp sale = `maxNut`). Mở
`FormNut` trống trong khung chi tiết (`?them=1`, `bat: true`). Lưu → `id = idRieng(ten, idDaCo)` → `ghi(themNut)` → chọn tình
huống mới (`?nut=<id>`).

`idRieng`: bỏ dấu (`lib/boDau.ts`), chữ thường, ký tự ngoài `[a-z0-9]` → `_`, gộp `_` liên tiếp, cắt hai đầu, cắt còn
33 ký tự → `rieng_<slug>`; slug rỗng → `rieng_tinh_huong`; trùng (sale ∪ hệ thống) → hậu tố `_2`, `_3`… (cắt slug để
vẫn ≤ 33). Luôn khớp `gioiHan.khuonIdRieng`.

### 4e. Xoá

Xác nhận trong trang: «Xoá «X»? Lượt cũ của nó chuyển vào mục 'tình huống đã bỏ'.» → `ghi(xoaNut(id))`.
**Chặn** (`chanXoa`), hiện tên tình huống bấm được để mở:
- tình huống khác (sale ∪ hệ thống) có `lan_2 === id` → ««Y» chuyển sang tình huống này khi khách lặp lại — đổi ở «Y»
  trước»;
- `X.lan_2 = Z`, `Z.chi_lan_2` và không còn tình huống nào khác trỏ `lan_2` tới Z → ««Z» chỉ tới được từ tình huống
  này — xoá «Z» hoặc bỏ 'Chỉ dùng khi được chuyển tới' ở «Z» trước».

### 4f. So với mẫu (`SoVoiMau`)

Chỉ ở trạng thái riêng. Mở từ dải trạng thái, hiện trong khung chi tiết (thay chi tiết; `?so=mau`, mục 4h):
- **Khác mẫu (n)** — bấm mở tình huống;
- **Có trong mẫu, chưa có trong bản của bạn (m)** — mỗi dòng [Thêm vào] → `ghi(themNut(veKhuon(mau)))` (giữ id mẫu).
  Kiểm client trước: `lan_2` của nó trỏ tới tình huống chưa có, hoặc nó `chi_lan_2` mà chưa ai trỏ tới → báo «Cần thêm
  «T» trước»;
- **Riêng của workspace (k)** — bấm mở tình huống.

### 4g. Áp lại mẫu NobleX

Xác nhận trong trang, số tính từ `soMau`: «Áp lại mẫu NobleX? n tình huống khác mẫu trở về bản mẫu · k tình huống
riêng bị xoá · m tình huống trong mẫu được thêm. Số đo các tình huống đổi chữ đếm lại từ đầu.» → `POST /ap-dung`.

### 4h. Sơ đồ, danh sách, điện thoại

- Sơ đồ (`DoThi`) và danh sách (`DanhSachNut`): trạng thái riêng thì sau tên thêm chữ nhỏ «· khác mẫu» / «· riêng»
  (CHỮ, không ký hiệu ✎/＋: font tự host không có hai glyph đó — luật 9 `CLAUDE.md` — và `<text>` SVG không nhúng được
  `Icon`); chú giải thêm hai mục đó. Không đổi bố cục cây.
- Khung chi tiết (desktop) / bottom sheet (điện thoại) mở khi có một trong ba search param: `?nut=<id>` (xem / sửa),
  `?so=mau` (so với mẫu), `?them=1` (thêm). Một chỗ quyết định mở-đóng; Back của trình duyệt đóng như hôm nay.
- Điện thoại: `FormNut`, `SoVoiMau` chạy trong bottom sheet sẵn có; ô nhập ≥16px đã do rule chung cuối `theme.css`
  lo; dải trạng thái xếp dọc.

### 4i. Luật portal áp vào màn này (`CLAUDE.md` FE)

- **Xem trước, sửa sau:** chế độ Xem và `FormNut` khai **cùng mục, cùng thứ tự, cùng nhãn** (mục 4c là nguồn) —
  `BangChiTiet` xếp lại các mục xem theo thứ tự form, đổi nhãn cho khớp («Kỹ năng dùng» → «Kỹ năng nên dùng», «Đi tiếp»
  hiện thành «Khi khách lặp lại lần 2, chuyển sang»), thêm mục «Câu kết hỏi khách»; mục rỗng ở chế độ xem bỏ hẳn (như
  hôm nay). Form **unmount** ở chế độ xem; Huỷ đặt lại state form rồi về bản xem; Lưu xong về bản xem của chính tình
  huống đó — được phép vì bản xem render lại từ query đã tải lại (mục 3 bước 4), không giữ ảnh chụp cũ.
- **Ngoại lệ có ý thức của điều 6 («danh sách phải ẩn khi form mở»):** sơ đồ vẫn hiện cạnh form — người sửa cần nó để
  chọn «chuyển sang» và đối chiếu tình huống lân cận. Mối nguy điều 6 canh (bấm chỗ khác thay nội dung form không
  báo) chặn bằng hỏi «Bỏ phần đang sửa?» (mục 4c).
- Hộp xác nhận (Xoá, Dùng bản mẫu, Áp lại, Bỏ phần đang sửa) dùng `HopThoai`, hàng nút `HANG_NUT` (nút chính cuối);
  không `confirm()`.
- Ô nhập dùng primitive `components/ui/Truong.tsx` (`OChu`, `OChon` — mang `o-chon`, `OChonNhieu`, `NhomTruong`);
  công tắc dùng `CongTac`; màu/viền/cỡ chữ chỉ qua token (`border-field`, thang `text-*`); nút tự dựng mang
  `cursor-pointer`.

## 5. So sánh với mẫu (`soMau`)

Theo `id` + `hash` giữa lớp sale đang chạy và `template.nodes`:

| Loại | Điều kiện |
|---|---|
| giống | id có ở mẫu, `hash` bằng nhau |
| khác | id có ở mẫu, `hash` khác |
| riêng | id không có ở mẫu (thường `rieng_…`) |
| chưa có | id ở mẫu, không có ở bản riêng |

Giới hạn ghi rõ trên màn bằng chữ «khác **bản mẫu hiện tại**»: BE không giữ mẫu lúc áp dụng (chỉ `tuTemplate` là hash),
nên không phân biệt được workspace tự sửa hay NobleX đổi mẫu. Hash hai phía cùng định nghĩa (parity Đợt 2 §3).
Trạng thái mẫu: mọi tình huống sale là mẫu → không nhãn, không «So với mẫu».

## 6. Kiểm phía client (báo sớm; BE là chốt chặn)

- **Từng ô** (`kiemNut(nut, gioiHan)`): mọi luật cột «luật» mục 4c + bắt buộc `ten`, `nhom`, ≥ 1 ý `dau_hieu` và `lam`.
  Con số lấy từ `gioiHan`, không chép tay.
- **Cả bộ** (`kiemBo(bo, heThong, gioiHan)`, chạy trong `ghi` sau `bienDoi`): ≤ `maxNut`; không trùng id (kể cả hệ
  thống); `lan_2` không trỏ chính nó và trỏ tới id có trong bộ ∪ hệ thống; mọi `chi_lan_2` là đích `lan_2` của ít nhất
  một tình huống (bộ ∪ hệ thống); đủ các id `khoaXoa`. Mỗi lỗi kèm tên tình huống, không mã.

## 7. Lỗi

| Lỗi | Màn làm gì |
|---|---|
| 409 `PLAYBOOK_DA_DOI` | Hiện câu BE; làm mới `['kich-ban']`; **giữ chữ đang gõ**; Lưu lần nữa dựng bộ từ bản mới. `hash` của tình huống đang sửa (lúc mở form) khác `hash` mới → thêm «Tình huống này cũng vừa được sửa ở nơi khác — xem lại trước khi lưu.» |
| 422 `VALIDATION_ERROR` | `error.fields[].field` dạng `body.nut[i].<trường>[...]` → tình huống `moi[i]`. Là tình huống đang sửa → lỗi dưới đúng ô (`buoc[j].lam` → bước j). Tình huống khác → ««Y» chưa hợp lệ: <reason>» + link mở «Y». `body.nut` (cả bộ) → trên đầu form / hộp xác nhận. |
| 422 `PLAYBOOK_ROLE_KHONG_CO` | Câu BE; làm mới `CAU_HINH_QUERY`. |
| 403 | Câu BE (lẽ ra không tới vì nút đã ẩn). |
| Mạng / 5xx | «Chưa lưu được — thử lại.» Giữ form. |
| `/playbook/template` lỗi hoặc thiếu `gioiHan` | Phần xem chạy bình thường; nút ghi khoá, `title` «Không tải được giới hạn kịch bản — tải lại trang». FE lên trước MR backend rơi vào ca này, không vỡ màn. |

`api.ts` thêm hàm `gui<T>(method, duong, body)` (PUT/POST JSON) cạnh `goi` sẵn có; `LoiApi` thêm `fields?:
{field, reason}[]` đọc từ thân lỗi.

## 8. MSW (dev không backend + test)

`features/kich-ban/msw.ts` giữ trạng thái trong bộ nhớ `{nut: NutVao[] | null, roleDung, version, tuTemplate}`:
- `GET /playbook`: `nodes` = hệ thống ∪ (sale từ trạng thái, dựng trường tương thích + `hash` giả ổn định theo nội dung)
  hoặc mẫu; `kichBan` theo trạng thái.
- `GET /playbook/template`: sale mẫu + `gioiHan` (bản sao khối thật của `playbook.json`).
- `PUT /playbook`, `POST /ap-dung`, `PUT /role-dung`: `version` lệch → 409 `PLAYBOOK_DA_DOI`; thành công tăng `version`.
- Hàm xuất cho test: đặt lại trạng thái, ép lỗi 422 với `fields` cho lần gửi kế tiếp.

## 9. Nhật ký

Chép `contracts/audit-actions.json` từ backend (`develop` sau !156). `features/platform/so-hanh-dong.ts`:
`playbook.ap_dung` «Áp dụng mẫu kịch bản», `playbook.luu` «Lưu kịch bản», `playbook.role_dung` «Đổi role dùng kịch
bản»; nhóm lọc `cau-hinh` thêm tiền tố `playbook`. Cổng `tests/audit-actions-parity.test.ts` phải xanh.

## 10. Kiểm thử

- **`tests/kich-ban-khuon.test.ts`:** `veKhuon` một nút mẫu → đúng tập khoá `NutVao`, `buoc` không `tool`;
  `idRieng` (bỏ dấu, trùng → hậu tố, tên toàn ký hiệu, cắt 33 vẫn khớp khuôn); `soMau` bốn loại; `kiemNut` mỗi luật
  một ca; `kiemBo` mỗi luật một ca; `chanXoa` hai ca chặn + một ca được xoá.
- **`tests/kich-ban-sua.test.tsx`** (RTL + MSW):
  1. người chỉ xem: không Sửa / Xoá / Thêm / Áp lại, công tắc role khoá;
  2. Sửa → đổi «Agent làm gì» → Lưu → `PUT` có `version` hiện tại, đủ bộ sale, chỉ tình huống đó khác, không trường
     tương thích;
  3. 409 → câu báo, chữ còn nguyên; Lưu lần hai gửi `version` mới;
  4. 422 `body.nut[i].lam` → lỗi dưới ô «Agent làm gì»;
  5. tình huống `khoaXoa` không có Xoá; Xoá bị chặn vì `lan_2`; Xoá được → `PUT` thiếu đúng id đó;
  6. Thêm → id `rieng_…`, màn chọn tình huống mới;
  7. công tắc role → `PUT /role-dung` đúng tập;
  8. trạng thái mẫu: form có câu báo tạo bản riêng;
  9. Áp lại: hộp xác nhận đúng n/k/m → `POST /ap-dung`;
  10. So với mẫu: đủ ba nhóm; Thêm vào gửi nút mẫu giữ id;
  11. sửa dở → chọn tình huống khác → hỏi «Bỏ phần đang sửa?»;
  12. thiếu `gioiHan` → nút ghi khoá, phần xem vẫn hiện.
- `tests/audit-actions-parity.test.ts` xanh; test `/kich-ban` sẵn có vẫn xanh; `make check`.
- Backend: test `gioiHan` (mục 1).
- **Trình duyệt:** dev server 5273 với MSW và với backend local thật (`VITE_MSW=0`, PG 5444 đã ở `0976`): áp dụng qua
  sửa, thêm, xoá, role, so với mẫu, áp lại; khung 400px.

## 11. Đưa lên

1. MR backend (`gioiHan`) → `develop`.
2. MR FE → `develop` (CI deploy dev, xem ở agent-portal-dev).
3. Kiểm thật trên dev với workspace thử: sửa một tình huống → «Thử agent» chat đúng tình huống → `meta.playbook.h` của
   lượt = `hash` trên màn, chỉ dẫn mang chữ mới; tắt role → không nhận chỉ dẫn.
4. `develop → uat` khi người dùng yêu cầu.

## 12. Tài liệu

- FE `CLAUDE.md`: mục ngắn «Kịch bản sửa được» — luồng `ghi(bienDoi)`, vì sao payload dựng từ `GET /playbook`, công
  tắc role ở `/kich-ban` chứ không ở `/agent`, ngoại lệ điều 6 của «xem trước, sửa sau»; một dòng Change Log.
- Backend `CLAUDE.md`: Change Log `gioiHan` ở `/playbook/template`.

## Ngoài phạm vi

- FE chuyển hẳn sang trường khuôn mới (bỏ đọc `trang_thai`, `loai`, `dieu_kien`, `tiep`) — trước khi BE bỏ trường
  tương thích.
- Đổi thứ tự bước / tình huống; nhân bản tình huống; lịch sử phiên bản; diff từng dòng.
- Gợi ý viết «Khi nào dùng» bằng AI.

## Rủi ro

- Workspace viết «Khi nào dùng» kém → agent chọn sai tình huống. Đỡ bằng gợi ý dưới ô; số đo theo tình huống lộ ra.
- Luật cả bộ có bản thứ ba ở FE (`kiemBo`) — chỉ để báo sớm; lệch thì BE 422 chặn và mục 7 hiện đúng chỗ. Con số
  giới hạn đọc từ `gioiHan`, không lệch được.
- Mỗi lần lưu `tang_version` → agent dựng runner mới; nhịp người bấm thì không đáng kể.
- Hai người sửa cùng tình huống: sau 409 người lưu sau đè người trước — màn báo trước khi lưu lại.
