# Responsive cho điện thoại — thiết kế

Ngày: 2026-09-28 · Trạng thái: chờ duyệt spec

## 1. Mục tiêu

**Người dùng nói:** trên máy tính giữ nguyên hiện trạng (hoặc tốt hơn khi thu nhỏ
cửa sổ); trên điện thoại phải responsive để dùng dễ.

**Đã chốt:**

| Câu hỏi | Chốt |
| --- | --- |
| Mức độ | **A** — màn vận hành làm tốt hẳn cho mobile; màn cấu hình chỉ cần _dùng được, không vỡ_. Tối ưu thêm sau. |
| Điều hướng mobile | **Drawer ☰** chứa đúng Rail + NavPanel hiện có |
| Breakpoint | **3 tầng**: `<768` mobile · `768–1023` tablet · `≥1024` desktop y hệt hiện tại |
| Cách làm | **Kết hợp**: CSS (biến thể `max-*`) mặc định, JS chỉ ở chỗ đổi cấu trúc |

**Tiêu chí xong:**

1. Ở 360 · 375 · 430px: không màn nào có cuộn ngang cấp trang
   (`scrollWidth ≤ innerWidth` của document và của `<main>`). Bảng được cuộn ngang
   **bên trong khung của nó**.
2. Mọi màn tới được bằng drawer; đổi workspace / hồ sơ / đăng xuất tới được.
3. Ô nhập không làm iOS tự zoom (cỡ chữ ô ≥16px ở mobile). Nút icon ≥40px ở mobile.
4. Ở 1280 và 1440px: ảnh chụp mọi màn **trùng pixel** với trước khi sửa.
5. `make check` xanh; 95 test hiện có không phải sửa kỳ vọng.

**Ngoài phạm vi:** PWA/app native · thiết kế lại form cấu hình cho mobile ·
`/appts`, `/gaps` (đang là `ScreenStub`) · backend.

## 2. Luật nền — thứ bảo đảm desktop không đổi

1. **Chỉ THÊM biến thể `max-md:` / `max-lg:`, không sửa class gốc.** Class hiện có là
   class desktop; mobile là lớp phủ lên trên. Review diff: dòng nào xoá/sửa class
   không có tiền tố `max-*` là dòng phải giải thích.
   - Ngoại lệ duy nhất: thay đổi CÓ LỢI cho desktop hẹp mà không đổi ≥1024px thì dùng
     `max-lg:` — vẫn là thêm, không sửa.
2. **Breakpoint là của Tailwind mặc định** (`md` = 768, `lg` = 1024), không khai báo
   thang mới. Hook JS đọc đúng hai con số đó từ một hằng dùng chung.
3. **jsdom = desktop.** jsdom không có `matchMedia` ⇒ hook trả `desktop` ⇒ test cũ
   dựng đúng layout cũ. Test mobile/tablet mock `matchMedia` tường minh.

## 3. Hook `useKhoManHinh()`

- File: `src/lib/khoManHinh.ts`. Trả `'mobile' | 'tablet' | 'desktop'`.
- `matchMedia('(max-width: 767.98px)')` và `('(max-width: 1023.98px)')`, nghe
  `change`. Dùng `useSyncExternalStore` (không nháy layout lần render đầu).
- Hằng `BP = { md: 768, lg: 1024 }` xuất ra cùng file, kèm chú thích: phải khớp
  breakpoint Tailwind.
- Không có `window.matchMedia` ⇒ `desktop`.

## 4. Shell

### Desktop ≥1024
Không đổi class nào. `panelThuGon` vẫn là `useState(false)` như cũ.

### Tablet 768–1023
- Rail 68px giữ. Panel **mặc định thu gọn**; nút ở đáy rail (đã có) mở/đóng.
- Panel mở ra dạng **phủ**: `fixed left-[68px] inset-y-0`, nền mờ phía sau, không
  đẩy nội dung. Đóng khi: bấm mục màn trong panel · bấm nền · Esc · rời tầng tablet.
- Cách làm: `_app.tsx` suy trạng thái từ `kho`; ở tablet bọc `<NavPanel/>` trong
  `LopPhu` (component mới, `components/shell/LopPhu.tsx`).

### Mobile <768
- Rail và NavPanel **không render** trong luồng layout.
- Topbar thêm nút ☰ bên trái `<h1>` — **chỉ render ở mobile** (ở desktop nút thu gọn
  vẫn ở đáy rail, đúng quyết định 2026-08-24).
- Bấm ☰ ⇒ `LopPhu` trượt từ trái chứa `<Rail/>` + `<NavPanel/>` cạnh nhau
  (68 + 240 = 308px, vừa màn 320px; nền mờ lấp phần còn lại).
- **Đóng ⇒ unmount**, không `hidden` (luật của `_app.tsx`/CLAUDE.md).
- Đóng khi: bấm **mục màn trong panel** · nền mờ · Esc · rời tầng mobile.
  **Bấm mục rail KHÔNG đóng**: rail vẫn điều hướng tới màn đầu của mảng như cũ, drawer
  ở lại để người dùng thấy các màn khác trong mảng.
  - Cơ chế: context `DongNav` (trong `LopPhu`), `NavItem` gọi `dongNav?.()` khi bấm.
    Rail không gọi. Ngoài lớp phủ context rỗng ⇒ `NavItem` desktop không đổi hành vi.
- Mở: khoá cuộn `<main>`, focus vào lớp phủ; đóng: focus trả về nút đã mở (☰ hoặc
  nút đáy rail).
- `Rail`/`NavPanel` dùng `h-screen` ⇒ trong lớp phủ thêm `max-lg:h-dvh`.

### Topbar ở mobile
- `max-md:h-14 max-md:px-4 max-md:gap-2`; `<h1>` `max-md:text-[18px]`.
- Ô «Tìm màn» 248px ⇒ ở mobile thành **nút icon 40px** (`aria-label` = «Tìm màn»),
  vẫn phát cùng sự kiện ⌘K — một đường vào palette. `kbd` ẩn.
- Hệ quả: mọi `calc(100dvh-72px)` có thêm `max-md:` bản `-56px` (xem §5.1).

### `<main>`
`max-md:h-dvh` — `100vh` của iOS cao hơn vùng nhìn thấy.

### CommandPalette
`pt-[12vh]` ⇒ `max-md:pt-4`; `max-h-[64vh]` ⇒ `max-md:max-h-[calc(100dvh-2rem)]`;
ô nhập `max-md:text-base`.

### CLAUDE.md
Thêm mục **«Shell responsive (2026-09-28)»**: ba tầng, drawer = Rail + NavPanel,
vì sao rail không đóng drawer, vì sao ☰ chỉ ở mobile. Luật «không sửa shell để thêm
màn» giữ nguyên — lần sửa này là sửa _hành vi khung_, không đặc-biệt-hoá màn nào
(`module-boundaries.test.ts` vẫn phải xanh).

## 5. Primitive dùng chung

Sửa ở hằng/component chung để các màn tự hưởng, không tự chế.

### 5.1 Khung trang
- `KHUNG_MAN` (`Bang.tsx`): thêm `max-md:h-[calc(100dvh-56px)] max-md:px-4 max-md:pb-4`.
- 18 file dùng `px-7` làm lề trang: thêm `max-md:px-4`. Những file tự viết
  `h-[calc(100vh|dvh-Npx)]` (`DuAnList`, `PhienKhach`, `HopThuSale`, `TongQuanScreen`)
  thêm bản `max-md:` tính theo topbar 56px và dùng `dvh`.

### 5.2 Bảng
- `Bang` giữ `min-w-[720px]` (desktop không đổi); bảo đảm luôn nằm trong vùng
  `overflow-x-auto` (`VungCuon`/`TheBang` — kiểm từng chỗ dùng; chỗ nào chưa có
  wrapper thì bọc). Cuộn ngang trong thẻ là chấp nhận được cho màn cấu hình.
- **Không** làm biến thể thẻ cho `Bang`: không màn vận hành nào dùng `Bang`
  (KhachList/HopThuSale/Feedback là hàng tự dựng) — YAGNI.
- Bảng tay trong `UserAdmin`, `TaiLieuList`, `NormalizationDialog`: cùng xử lý.

### 5.3 Hộp thoại (~20 cái, `fixed inset-0`)
- Giữ kiểu hộp giữa màn, **không** làm bottom-sheet: các hộp đã là
  `w-full max-w-[420–620px]`, chỉ thiếu lề và giới hạn chiều cao.
- Mỗi lớp phủ: bảo đảm có `px-4`; mỗi hộp: `max-md:max-h-[calc(100dvh-2rem)]
  max-md:overflow-y-auto`. Hàng nút dùng `HANG_NUT` đã `flex-wrap`.
- Bề rộng cố định bên trong hộp (`w-[150–240px]`) ⇒ `max-md:w-full`.

### 5.4 Ô nhập & vùng chạm
- `O_CHUNG` (`Truong.tsx`), `O_LOC`, ô palette, ô tìm của `HopThuSale`:
  `max-md:text-base` (16px) — dưới 16px iOS Safari tự zoom khi focus.
- `CAO_O` giữ `h-9`; thêm `max-md:h-10`. `NutIcon` ≥40px ở mobile.
- Ô lọc có bề rộng cố định (`w-[130px]`, `w-[240px]`, `min-w-[190px]`…) ⇒
  `max-md:w-full` / `max-md:min-w-0`.

### 5.5 Thứ chỉ hiện khi hover
**Rà lại khi viết plan: KHÔNG có hành động nào bị giấu sau hover.** 4 chỗ
`opacity-0 group-hover:*` là trang trí: vạch 3px bên trái hàng (`KhachRow`,
`CaRow` — hàng đang chọn đã hiện sẵn vạch) · mũi tên «→» trên thẻ dashboard
(`TongQuanScreen`) · `VungMedia` đã chuyển nút sang thường trực từ trước. Mốc giờ
(`.moc-gio`) đã có `@media (hover: none)`. ⇒ không thêm variant `cham:` (YAGNI);
§8.3 vẫn soi ảnh chụp mobile để chắc không có thứ gì chỉ lộ ra khi rê chuột.

### 5.6 `NhomTab`
Ở mobile: `max-md:overflow-x-auto max-md:max-w-full` + mục không xuống dòng — hàng
tab dài (`/pform`, `/users`) cuộn ngang thay vì tràn trang.

## 6. Màn vận hành — làm tốt hẳn

### 6.1 `/dashboard` (`TongQuanScreen`)
- Lưới 24 cột đã có tầng `max-[1240px]` (12 cột). Thêm tầng `max-md:`: một cột,
  `grid-rows-none auto-rows-auto`, mọi thẻ `col-span-full`.
- Khung `overflow-hidden` + chiều cao cố định ⇒ `max-md:h-auto max-md:overflow-visible`:
  mobile cuộn dọc cả trang thay vì ép 5 thẻ vào một viewport.
- Biểu đồ/gauge: kiểm nhãn trục không chồng ở 360px; nếu chồng, giảm số mốc ở mobile
  bằng `kho === 'mobile'` (chỉ khi thấy thật trên ảnh chụp).

### 6.2 `/convos` (`KhachList`, `KhachRow`)
- Hàng lọc đã `flex-wrap`; ô lọc cố định bề rộng theo §5.4.
- `KhachRow` ở mobile: xếp hai dòng (tên + SĐT / kênh + thời gian + trạng thái),
  nút hành động hiện sẵn (§5.5). `ThanhTrang` (phân trang): kiểm vừa 360px.

### 6.3 `/convos/$phone` (`PhienKhach`) — master/detail
- Desktop: giữ 2 cột (danh sách phiên 300px | transcript).
- Mobile (`kho === 'mobile'`): **một cột một lúc**. Mặc định hiện danh sách phiên
  full-width; chọn phiên ⇒ hiện transcript full-width với đường về
  «‹ Các phiên» (hằng `DUONG_VE`, là `<button>` — không đổi URL). Phiên đang chọn
  (`chon`) là `useState` và được chọn sẵn một phiên mặc định, nên «đang xem chi
  tiết» phải là state RIÊNG `dangXemPhien` (mặc định `false` ở mobile; mở link có
  `phienMoDau` ⇒ `true`) — không suy từ `chon`, nếu không mobile luôn nhảy thẳng vào
  transcript.
- Khung cao `h-[calc(100vh-120px)]` ⇒ bản `max-md:` theo §5.1.

### 6.4 `/chuyen-sale` (`HopThuSale`)
- Master/detail như §6.3, nhưng **ca đang mở đã nằm ở search param** (để F5/gửi link
  ra đúng ca) — nên ở mobile rẽ nhánh THEO URL, không thêm state: có ca trên URL ⇒
  chỉ `CaChiTiet` full-width + «‹ Danh sách» (`moCa(undefined)` — bỏ param ca, giữ
  bộ lọc + trang); không có ⇒ chỉ danh sách. ⚠ Rẽ theo `caDangMo` (param thô), KHÔNG
  theo `dangMo`: `dangMo` rơi về `items[0]` khi không có param, nên suy từ nó thì
  mobile luôn nhảy thẳng vào ca đầu. Lưới `minmax(300px,380px)_1fr` giữ ở desktop.
  `moCa` hiện dùng `replace: true` — nút Back của trình duyệt KHÔNG quay về danh
  sách; giữ nguyên hành vi đó (đổi là đổi lịch sử điều hướng của cả desktop).
- Ô tìm `w-[240px]` ⇒ `max-md:w-full`. Hộp nội tuyến `max-w-[460px]` theo §5.3.
- Mẫu master/detail dùng chung một helper nhỏ nếu hai chỗ giống nhau thật
  (`components/ui/HaiKhung.tsx`) — chỉ tách khi viết xong chỗ thứ hai và thấy trùng.

### 6.5 `/quality` (`FeedbackList`, `FeedbackTongQuan`, `FeedbackReviewCard`)
- `FeedbackTongQuan`: cột trái `w-[220px]` + viền phải ⇒ `max-md:` xếp dọc
  (`flex-col`, cột trái `w-full` + viền dưới).
- Lề `px-6` ⇒ `max-md:px-4`. Thẻ review: kiểm `ml-[44px]` không đẩy chữ quá hẹp.

## 7. Màn cấu hình — «dùng được, không vỡ»

`/agent` · `/kb` · `/projects` `/pform` `/uform` · `/finance` · `/ky-nang-bds` ·
`/domains` · `/thu-agent` · `/api-keys` · `/users` `/roles` · `/audit` · `/billing`
`/usage` `/pricing` · `/settings` `/workspace` `/onboarding` · `login` `dang-ky`
`invite` `tao-workspace-dau-tien` · landing `/`.

Cách làm: chụp từng màn ở 375px, sửa **chỉ** chỗ gây cuộn ngang cấp trang hoặc
che/không bấm được, bằng §5. Không đổi thứ tự ô, không đổi luồng xem/sửa. Kỳ vọng:
- Form: `NhomTruong` đã `md:grid-cols-2` ⇒ một cột sẵn; chủ yếu là lề + ô cố định.
- `/thu-agent`: khung hội thoại theo §5.1; thanh nhập đáy không bị bàn phím che
  (dùng `dvh`).
- Bảng giá/usage: bảng cuộn ngang trong thẻ; lưới KPI `grid-cols-N` không tiền tố
  ⇒ `max-md:grid-cols-2`/`1`.
- `/appts`, `/gaps` (`ScreenStub`): không thiết kế, nhưng vẫn phải qua tiêu chí
  «không cuộn ngang» (cột nhãn `w-[104px]` + `p-7` ⇒ lề §5.1).

### 7.1 Lớp UI không phải route — cũng phải qua tiêu chí §1

Thứ nổi lên trên trang (định vị `absolute`/`fixed`) là thứ hay tràn mép phải nhất
trên màn hẹp, và không route nào «sở hữu» nó nên dễ lọt khi rà theo màn:

| Nhóm | Chỗ | Xử lý |
| --- | --- | --- |
| Menu thả | `WorkspaceSwitcher`, `UserMenu`, `LangToggle` (trong drawer) · `MenuHang` (hàng `/users`) · `StatusChip` · dropdown của `OChonNhieu` (`Truong.tsx`) | Mở trong drawer 308px / hàng sát mép phải: `max-md:max-w-[calc(100vw-2rem)]`, neo phía còn chỗ; không bị lớp phủ drawer cắt |
| Tooltip | `Tip` / `useTip` (dashboard) | Không có hover ⇒ bấm để mở/đóng; kẹp trong viewport |
| Lightbox | `AnhLon` (media dự án) | Ảnh `max-w-full max-h-[100dvh]`, nút đóng ≥40px |
| Màn trạng thái | `notFoundComponent` (`__root.tsx`) · màn lỗi router (`main.tsx`) · màn chờ/lỗi của `SessionProvider` (`session.tsx`) · màn chờ của `DangKyForm`/`NhanLoiMoi` | Đã `grid place-items-center px-6` — chỉ kiểm chữ dài xuống dòng |
| Màn công khai | `login` · `dang-ky` · `invite/$token` · `tao-workspace-dau-tien` · landing `/` (`TrangGioiThieu`, lưới `max-w-[1240px]`) | Form đã `w-full max-w-[352px]`; kiểm lề, ô 16px (§5.4), nút Google; landing kiểm các lưới `md:`/`lg:` đã có |

§8.3 chụp thêm mỗi nhóm trên ở trạng thái **mở** (menu mở, tooltip mở, lightbox,
một URL 404), không chỉ trạng thái mặc định của màn.

## 8. Kiểm chứng

1. **Unit (vitest):**
   - `useKhoManHinh`: 3 tầng + đổi tầng khi `change`; không có `matchMedia` ⇒ desktop.
   - Shell mobile: ☰ mở lớp phủ; đóng ⇒ nav **không còn trong DOM**; bấm mục rail
     vẫn mở; bấm mục panel đóng; Esc đóng + trả focus về ☰.
   - Shell tablet: panel mặc định thu gọn; mở ra là lớp phủ; bấm mục đóng.
   - `PhienKhach`/`HopThuSale` mobile: chỉ danh sách ⇒ chọn ⇒ chỉ chi tiết ⇒ «‹» về.
2. **Cổng văn bản** (kiểu `o-chon.test.ts`): `O_CHUNG` và `O_LOC` chứa
   `max-md:text-base` — lớp lỗi zoom iOS jsdom không bắt được.
3. **Trình duyệt thật** (Playwright chạy tạm qua `npx`, không thêm dependency),
   MSW bật, mọi route sau đăng nhập + màn công khai:
   - 360 / 375 / 430 / 768px: đo `scrollWidth` document và `<main>`; chụp ảnh để xem.
   - 1280 / 1440px: chụp **trước** khi sửa (baseline) và **sau**, so pixel — phải
     trùng. Khác ⇒ tìm class gốc đã bị đụng.
4. `make check` + `make build` (repo dùng `tsc -b`, không dùng `tsc --noEmit`).

## 9. Rủi ro

- **Ảnh baseline lệch do dữ liệu theo thời gian** (dashboard, «x phút trước»): cố
  định đồng hồ trong Playwright (`page.clock`) cho cả hai lượt chụp.
- **Master/detail dùng JS** ⇒ nếu người dùng xoay ngang giữa chừng (đổi tầng) phải
  giữ phiên/ca đang chọn: state chọn nằm ngoài nhánh rẽ mobile/desktop.
- **Khối lượng**: ~20 hộp thoại + 18 file lề là việc cơ học; rủi ro là bỏ sót ⇒ đo
  bằng §8.3, không bằng mắt.
