# Task 9 — Panel bộ giá: báo cáo

## Status: DONE

Commit: `7dd3862` — `feat(billing): panel bộ giá — form sinh từ pricing_basis + preview per-tenant`

Files:

- Tạo: `src/features/billing/components/PanelBoGia.tsx`
- Sửa: `src/features/billing/components/BangGiaScreen.tsx` (wire panel: ô «Bộ giá
  mặc định» thành `<button>`, hàng bảng mở panel qua một `<button>` thật quanh
  tên bộ giá + `Hang mo={...}`, state `panelId`/`oMoRef`/`moPanel`/`dongPanel`)
- Sửa: `src/features/billing/pricingBasis.ts` (thêm `PURPOSE_TINH_KHACH` — bản
  sao viết tay `billing.purpose` billable=true, dùng cho `<select>` `purpose`)
- Sửa: `tests/billing-gia.test.tsx` (5 bài Task 9 + 1 bài Task 8 phải sửa)

## Sáu điều coordinator ghi đè brief — đã áp dụng đúng

1. Mã lỗi kích hoạt `BANG_GIA_CON_LO` (đọc thẳng
   `odyssey-portal-backend/src/portal/modules/billing/service.py::kich_hoat`,
   dòng 93-113) — brief nháp đầu đoán `BO_GIA_CON_LO`, sai, đã sửa test theo
   mã thật. Message BE hiện NGUYÊN VĂN qua `LoiApi.message`, không viết lại.
2. Không có endpoint đọc `price_item` — panel chỉ có form THÊM dòng, không
   bảng nào cả (không phải bảng rỗng không giải thích). Docstring đầu file +
   một dòng chữ mờ 11px trong khu "Thêm dòng giá" nói rõ lý do và cách khác để
   biết bộ giá đã đủ (Preview / Kích hoạt).
3. Preview cần `tenant` + trả MỘT tổng camelCase — bộ chọn Workspace từ
   `useSession().workspaces`, so sánh cũ→mới→Δ CHỈ hiện khi tenant chọn để
   preview TRÙNG `currentWorkspace` của phiên (vì `/billing/summary` xác thực
   qua cookie phiên, không nhận tham số `tenant` — đã đọc `router.py` xác
   nhận, không đoán). Khác tenant thì chỉ hiện số preview mới, có một câu giải
   thích tại sao không so được — không bịa số "cũ" sai tenant.
4. Luật STT hẹp lại (`0948`): `metricBiKhoa()` chỉ khoá option THỜI LƯỢNG còn
   lại (`audio_sec`/`wall_ms`) khi metric đang chọn cũng là thời lượng;
   `text_units` không bao giờ bị khoá. Có test canh cả ba nhánh.
5. Body `POST .../items`: chỉ `unitPrice`/`perUnits` camelCase, còn lại tên
   thường — khớp `DongGiaIn` (`kieu.ts`) và đã đọc `contracts.py` BE xác nhận
   `extra="forbid"`, không `populate_by_name`.
6. `unitPrice` là `<input type="text">` viết tay (không `OSo`, không
   `Number()`) — giữ nguyên chuỗi người gõ.

## Phát hiện thêm khi đọc `pricing-schema.sql` (không có trong brief)

`billing.purpose` (§3c) có cột `billable` — 4 purpose `billable=false`
(`memory`/`warm_cache`/`addressee_gate`/`semcache`) không bao giờ được
`rate_usage()` tính tiền, nên tạo dòng giá cho chúng là dòng chết. `<select>`
`purpose` của form vì thế chỉ liệt kê `PURPOSE_TINH_KHACH` (6 purpose
`billable=true`) + một lựa chọn rỗng "mọi purpose" — đây chính là điều
"purpose không tính khách không xuất hiện trong danh sách chọn" mà brief nhắc
tới nhưng không giải thích nguồn.

## Sửa bài test Task 8 — như thế nào

Bài `'ba ô số ở mục ① KHÔNG phải button — …'` đã đổi tên +
sửa thân: `expect(screen.queryByRole('button', {name: /bộ giá mặc định/i})).toBeNull()`
→ `expect(screen.getByRole('button', {...})).toBeInTheDocument()`. Hai
assertion còn lại («Bộ đang áp» / «Tổ hợp chưa có giá» vẫn KHÔNG phải button)
giữ nguyên — chỉ «Bộ giá mặc định» có đích thật (một `id` cụ thể) để mở panel;
hai ô kia không có đích rõ ràng (một phép đếm có thể nhiều bộ; ô còn lại không
có nguồn tách dòng) nên vẫn là `<div>`.

## Quyết định thiết kế đáng chú ý (không có sẵn trong brief)

- Hai bộ giá test dùng tên/ID riêng (`Chuẩn Q3/2026` id `1`, `Nháp Q4/2026` id
  `2`, override qua `server.use()` chỉ trong describe Task 9) — không đụng
  `BO_GIA_GIA` dùng chung của Task 8.
- Workspace test dùng ID thật của fake `GET /api/v1/me`
  (`ws_anphu`/`ws_sunrise`/`ws_haven`, `lib/msw/handlers.ts`) — brief nháp viết
  `'bilw'`, không tồn tại trong fake, đã đổi.
- «Kích hoạt» gate theo `usePreview().isSuccess` của MỘT query mà `enabled`
  chỉ bật sau khi bấm nút «Preview» (chọn workspace không tự bắn request) —
  panel `key={panelId}` ở `BangGiaScreen` nên đổi bộ giá là remount, tự reset
  gate về đúng nghĩa "preview cho ĐÚNG bộ này".
- Sửa một bug tự gây ra giữa chừng: bản nháp đầu của `PanelKhung` dùng
  ref-callback trên `<div>` không `tabIndex` để focus lúc mở — không hoạt động
  (div trần không nhận `.focus()`) và còn gọi lại mỗi lần re-render (mất
  Escape-handling luôn trong lần viết lại đó). Đã sửa về đúng khuôn
  `ChiTietPhien.tsx`: `useRef` + `useEffect` focus nút đóng, listener Escape ở
  `document`, gỡ khi unmount.
- Hàng bảng ② thêm một `<button>` thật quanh tên bộ giá (`Hang` cố ý không
  nhận Tab, cần một phần tử tương tác thật trong hàng theo đúng docstring của
  chính component đó) — vừa sửa một lỗ hổng bàn phím/trình đọc màn hình có sẵn
  từ Task 8 (trước đó `Hang mo={() => {}}` không làm gì và không có phần tử
  tương tác nào khác trong hàng), vừa là điểm neo `oMoRef` để trả focus đúng
  chỗ lúc đóng panel.

## Test summary

- Trước (baseline theo brief + CLAUDE.md): **783 passed · 6 skipped · 0 failed**.
- File `tests/billing-gia.test.tsx` riêng: **11 → 16 bài** (5 bài Task 9 mới),
  tất cả xanh.
- Sau (full suite): **788 passed | 6 skipped (794)** — đúng 783 + 5, không hồi
  quy, không bài nào khác đổi trạng thái.

```
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run
 Test Files  60 passed (60)
      Tests  788 passed | 6 skipped (794)
```

## `npx tsc -b --force`

Output rỗng, exit 0 (chạy lại sau `prettier --write`, vẫn sạch).

## `git status --porcelain` (sau commit)

```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Đúng hai file vùng cấm (không đụng tới) — không file nào khác ngoài staged
commit của task này.

## Hai grep thang chữ

```
$ grep -rhoE 'text-\[[0-9.]+px\]' src/features/billing/ | sort | uniq -c | sort -rn
     29 text-[12.5px]
     10 text-[13.5px]
      9 text-[11px]
      6 text-[10.5px]
      4 text-[26px]
      4 text-[16px]
      3 text-[20px]
      1 text-[32px]

$ grep -rn 'style={{[^}]*fontSize' src/features/billing/ || echo OK
OK
```

Toàn bộ nằm trong 9 bậc cho phép (32·26·20·16·15·13.5·12.5·11·10.5). Số nổi
bật của panel là 20px (đúng một chỗ, dòng "Nếu dùng bộ này" ở khu Preview) —
`32`/`26` là của `TheKpi.tsx` (Task 4), không đụng.

`npx prettier --check` bốn file đã sửa: xanh sau một lượt `--write`.

## Concerns

- «Tổng hiện tại» để so cũ→mới→Δ chỉ đọc được khi workspace chọn để preview
  TRÙNG workspace hiện tại của phiên đăng nhập admin — hạn chế thật của kiến
  trúc (`/billing/summary` không nhận `tenant`), không phải một khoảng hở tôi
  bỏ sót; đã tài liệu hoá trong docstring `PanelBoGia.tsx` và có nhánh UI nói
  rõ lý do khi không so được, thay vì bịa số.
- Chưa viết test riêng cho nhánh so sánh cũ→mới→Δ (chỉ triển khai theo brief
  Step 3) — 5 bài bắt buộc của Step 1 đều đã xanh và phủ đúng phần "quan trọng
  nhất" (alias, khoá STT, đơn vị, gate kích hoạt, message 409 nguyên văn).
  Muốn phủ thêm nhánh hiển thị Δ thì cần chọn `tenant = currentWorkspace.id`
  (`ws_anphu`) trong test thay vì `ws_sunrise`.

---

## Bản vá theo review (2026-08-20, lượt hai)

### [Important] `oMoRef` không được đặt khi mở panel bằng click HÀNG — ĐÃ SỬA

Xác nhận đúng phát hiện: `src/features/billing/components/BangGiaScreen.tsx`
dòng cũ `<Hang mo={() => setPanelId(b.id)}>` gọi thẳng `setPanelId`, bỏ qua
`moPanel()` — nên đường click phần TRẦN của hàng không bao giờ cập nhật
`oMoRef`, trong khi đường click nút tên (`onClick={(e) => moPanel(b.id,
e.currentTarget)}`) thì có. Hai đường loại trừ nhau thật (`Hang` bỏ qua click
trên `closest(TU_BAM_DUOC)`), nên `dongPanel()` gọi qua đường hàng-trần sẽ
`.focus()` vào `null` (lần mở đầu) hoặc vào phần tử của LẦN MỞ TRƯỚC.

**Cách chọn: đặt `oMoRef` ở CẢ HAI đường, không bỏ đường nào — không thêm
đường thứ ba.** Thêm `nutTenRef = useRef<Map<number, HTMLButtonElement>>()`
ghi nhớ đúng `<button>` tên của MỖI hàng (`ref={(el) => dangKyNutTen(b.id,
el)}`). Đường `Hang.mo` giờ tra map này: `mo={() => moPanel(b.id,
nutTenRef.current.get(b.id) ?? null)}`. Lý do KHÔNG gán `oMoRef` vào chính
`<tr>`: `<tr>` không có `tabIndex` nên không nhận `.focus()` — đúng lớp bug
ref-callback vừa sửa ở `PanelBoGia.tsx` trong lượt đầu, gán lại vào `<tr>` sẽ
tái tạo đúng lỗi đó ở một chỗ khác. `moPanel()` đổi kiểu tham số `el` từ
`HTMLElement` sang `HTMLElement | null` để chấp nhận map-miss (không xảy ra
thật trong runtime — hàng nào cũng render đúng một nút tên — nhưng an toàn
kiểu hơn `!`).

Cả hai đường mở giờ hội tụ về CÙNG một `oMoRef`/CÙNG một target (nút tên của
đúng hàng), bất kể người dùng bấm nút hay bấm chỗ trống của hàng.

### [Minor] Hai cổng còn thiếu — ĐÃ THÊM

① Ba bài test mới canh CẢ BA đường đóng (nút ×, click lớp phủ, Escape) —
`tests/billing-gia.test.tsx`, dùng helper mới `moPanelBoGiaQuaHangTran()` mở
panel qua PHẦN TRẦN của hàng (click vào ô Trạng thái, không phải nút tên) —
đúng đường đang hỏng, khác `moPanelBoGia()` cũ (luôn bấm nút, nên không bao
giờ bắt được bug này dù đóng đúng ba cách). Cả ba bài kiểm `toHaveFocus()`
trên nút tên đã dùng để mở.

② Một bài mới: preview bộ A (đủ điều kiện Kích hoạt) rồi đóng, mở bộ B —
nút Kích hoạt của B phải khoá lại. Xác nhận `key={pbId}` remount `PanelBoGia`
xoá sạch state cục bộ (kể cả gate preview) khi đổi bộ giá.

⚠️ Fixture phát sinh giữa chừng: `BO_GIA_TASK9` ban đầu có 'Chuẩn Q3/2026'
`status: 'active'` — nút Kích hoạt của bộ ĐÃ active hiện chữ «Đã kích hoạt»,
không phải «Kích hoạt», nên bài remount trượt TÊN nút chứ không phải trượt
logic. Đổi cả hai fixture về `status: 'inactive'` (docstring tại chỗ giải
thích) — không đụng gì tới ý nghĩa bài test 5 cũ (không bài nào trong 5 bài
đó kiểm `status`).

### Kiểm ngược bài test focus

Trả `<Hang mo={() => moPanel(...)}>` về `<Hang mo={() => setPanelId(b.id)}>`
(bản hỏng), chạy `tests/billing-gia.test.tsx`:

```
Tests  3 failed | 17 passed (20)
```

Đúng và CHỈ đúng ba bài mới (nút ×, lớp phủ, Escape — cả ba mở bằng
`moPanelBoGiaQuaHangTran()`) đỏ; 17 bài còn lại (gồm cả bài remount, mở bằng
`moPanelBoGia()` — đường nút, không đi qua chỗ hỏng) vẫn xanh. Đã hoàn nguyên
lại bản sửa ngay sau đó.

### Test summary (sau bản vá)

- File `tests/billing-gia.test.tsx`: 16 → **20 bài** (thêm 4: ba đường đóng +
  một bài remount), tất cả xanh.
- Full suite: `Test Files 60 passed (60)` / `Tests 792 passed | 6 skipped
  (798)` — 788 (lượt đầu) + 4, 0 failed.

### `npx tsc -b --force`

Output rỗng, exit 0.

### `git status --porcelain`

```
 M src/features/billing/components/BangGiaScreen.tsx
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/billing-gia.test.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Hai file vùng cấm không đụng tới; hai file `M` còn lại là staged cho commit
bản vá này.

`npx prettier --check` hai file sửa: xanh, không cần `--write` thêm lần nào.

### Ba điều reviewer nói KHÔNG phải finding — giữ nguyên, không đụng

So sánh cũ→mới→Δ theo tenant hiện tại · `PURPOSE_TINH_KHACH` · bài test Task 8
đã sửa — cả ba giữ nguyên như lượt đầu, không thay đổi gì thêm.
