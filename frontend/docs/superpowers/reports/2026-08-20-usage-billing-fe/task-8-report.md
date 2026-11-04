# Task 8 — Báo cáo

**Status:** DONE
**Commit:** `c54113e` (branch `feat/usage-billing-fe`)

## Test summary

- Trước: 777 passed · 6 skipped · 0 failed (baseline đề bài, đã đo lại tại chỗ)
- Sau: **782 passed · 6 skipped · 0 failed** (60 test files) — đúng +5 test mới,
  toàn bộ ở `tests/billing-gia.test.tsx` (3 bài tối thiểu theo brief + 2 bài
  thêm: chặn cả bảng lẫn nút «Bộ giá mới» khi thiếu token, và nhánh lỗi 401
  admin → `LoiTai` có nút Thử lại)
- `tests/boot.test.tsx` sửa (không thêm/bớt số bài): route `/pricing` giờ
  render `BangGiaScreen` thật thay vì `ScreenStub`, nên bảng dấu hiệu
  `DAU_HIEU_MAN_THAT` cần một dòng mới (`pricing: 'Token quản trị nền tảng'`)
  — thiếu dòng này bài "18 màn đều mở được qua cây route thật" đỏ vì hồi quy
  thật (route đổi hành vi), không phải baseline hỏng sẵn.
- Chạy bằng: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`

## `npx tsc -b --force`

Output rỗng (thoát 0, không lỗi) — clean.

## `git status --porcelain` (sau commit)

```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Đúng hai file vùng cấm còn `M` (không đụng, không `git add`). `node_modules`
untracked, không liên quan.

## Hai grep bắt buộc

```
$ grep -rhoE 'text-\[[0-9.]+px\]' src/features/billing/ | sort | uniq -c | sort -rn
     21 text-[12.5px]
      8 text-[13.5px]
      7 text-[11px]
      4 text-[26px]
      3 text-[16px]
      3 text-[10.5px]
      2 text-[20px]
      1 text-[32px]

$ grep -rn 'style={{[^}]*fontSize' src/features/billing/ || echo OK
OK
```

Mọi bậc nằm trong tập `{32,26,20,16,13.5,12.5,11,10.5}` (15 không dùng ở
module này, không bắt buộc dùng hết 9 bậc). Bị bắt một lần khi mới viết:
`TaoBoGiaDialog.tsx` copy nguyên `TaoKhoaDialog.tsx` (module `platform`,
KHÔNG bị grep này canh) và mang theo ba bậc lạ — `16.5px` (tiêu đề dialog),
`14px` (ô nhập), `13px` (banner lỗi). Sửa về `16px`/`13.5px`/`12.5px`.

## Việc đã làm

1. `contracts.ts`: `BangGiaScreen` đổi từ `ScreenStub` sang re-export
   `./components/BangGiaScreen` thật.
2. `components/BangGiaScreen.tsx` (mới): dải token (`sessionStorage`,
   `docToken`/`luuToken` Task 3, một dòng `text-[12.5px] text-muted`, KHÔNG
   phải dải cảnh báo) → mục ① ba ô (Bộ giá mặc định + Bộ đang áp từ
   `useBoGia()`, Tổ hợp chưa có giá từ `useTongQuan('thang-nay')` →
   `canh_bao.thieu_gia`) → mục ② bảng 5 cột (`Bộ giá`/`Trạng thái`/`Tiền
   tệ`/`Tạo lúc`/mũi tên) + nút «Bộ giá mới».
   - Ô «Tổ hợp chưa có giá» là `<div>`, KHÔNG PHẢI `<button>` — hai ô kia và
     hàng bảng LÀ `<button>`/hàng bấm được nhưng `onClick`/`mo` là hàm rỗng
     (Task 9/10 nối panel thật, chưa tồn tại ở Task 8).
   - Bảng + hai ô phụ thuộc token gói TRONG nhánh `!coToken` — thiếu token thì
     `useBoGia()` không fetch (`enabled` sửa ở `api.ts`) VÀ không nút/bảng nào
     dẫn tới một request admin chắc chắn 401.
   - Ô thứ ba (`useTongQuan`) gọi vô điều kiện vì `/billing/summary` xác thực
     bằng cookie phiên tenant, không phải token nền tảng — hai luồng xác thực
     độc lập, ghi rõ trong docstring đầu file.
3. `components/TaoBoGiaDialog.tsx` (mới): hộp thoại 3 ô `code`/`name`/
   `currency` (`<select>` mang `o-chon`), khuôn `z-70` + backdrop `<button>`
   chép từ `TaoKhoaDialog.tsx`, hàng nút theo `HANG_NUT`.
4. `api.ts`: `useBoGia()` thêm `enabled: Boolean(docToken())`.
5. `dinh-dang.ts`: thêm `dinhDangLuc()` (`dd/MM/yyyy HH:mm`, bản sao cùng
   khuôn `features/platform/api.ts::dinhDangLuc`, không import được qua ranh
   giới module).
6. `routes/_app/pricing.tsx`: sửa comment lỗi thời (còn nhắc `ScreenStub`).
7. `tests/billing-gia.test.tsx`: thêm 5 bài (khối `describe('BangGiaScreen
   (Task 8)')`), boot qua router thật (`routeTree.gen.ts`) cùng khuôn
   `billing-usage.test.tsx`. Helper `theoDoi()` theo dõi request qua sự kiện
   MSW `request:start` (không `server.use()` ghi đè handler — giữ nguyên
   `thieuTokenAdmin()` thật của fake để canh đúng nhánh 401).
8. `tests/boot.test.tsx`: thêm dòng `pricing` vào `DAU_HIEU_MAN_THAT`.

## Concerns

- Test 2 & 3 dùng fixture có sẵn của `features/billing/msw.ts`
  (`BO_GIA_GIA[0].name = 'Bảng giá VND mặc định'`) thay vì chuỗi mẫu
  `'Chuẩn Q3/2026'` trong brief — brief viết trước khi biết tên fixture thật
  của Task 6/7. Không sửa fixture (dùng chung, Task 9/10 có thể đã giả định
  theo tên hiện tại); tên bộ giá mặc định TRÙNG cả trong ô ① lẫn trong hàng
  bảng ②, nên bài test 2 phải `within(getByRole('table', {name: /danh sách
  bộ giá/i}))` để tránh khớp hai phần tử — `findByText` trần sẽ ném lỗi "found
  multiple elements".
- Hai ô «Bộ giá mặc định»/«Bộ đang áp» là `<button onClick={() => {}}>` theo
  đúng chữ brief ("mỗi ô là nút mở panel") dù chưa có panel để mở ở Task 8 —
  cố ý chừa chỗ cho Task 9 chỉ cần đổi một dòng `onClick`, không đổi cấu trúc.
  Đáng để reviewer xác nhận đây đúng là ý muốn (thay vì để chúng là `<div>`
  cho tới khi panel tồn tại).
- Không đổi `public/demo-usage-billing.html` hay bất kỳ file ngoài
  `src/features/billing/`, `src/routes/_app/pricing.tsx`,
  `tests/{billing-gia,boot}.test.tsx`.

---

## Sửa theo review coordinator (2026-08-20, sau báo cáo đầu)

**Commit:** `cc6a8af`

**Ruling:** concern #2 đúng — hai ô «Bộ giá mặc định»/«Bộ đang áp» ở `BaOSo` từng là `<button onClick={() => {}}>`: điều khiển chết (viền focus, con trỏ tay, tab tới được, bấm không làm gì), tệ hơn không phải nút. Concern #1 (dùng tên fixture thật thay vì mẫu brief, `within(getByRole('table'))` tránh multi-match) giữ nguyên, không phải finding.

**Việc đã làm:**
1. `BangGiaScreen.tsx`: cả ba ô ở `BaOSo` đổi thành `<div>` không tương tác (không `type="button"`, không `onClick`, không lớp hover/focus). Xoá hằng `O_THE_BAM` (không còn ai dùng — grep xác nhận rỗng).
2. `tests/billing-gia.test.tsx`: thêm bài `'ba ô số ở mục ① KHÔNG phải button — chưa có panel để mở, và nút bấm-không-làm-gì là điều khiển chết'` — khoá cả ba ô không mang `role="button"`. Đặt tên nói rõ LÝ DO (điều khiển chết), không phải "chưa nối". Bài này sẽ đỏ có chủ đích khi Task 9 nối panel thật và đổi hai ô đầu thành `<button>` — buộc người nối đọc docstring trước khi sửa/xoá bài test.
3. Docstring đầu `BangGiaScreen.tsx` ghi lại quyết định 2026-08-20 và lý do (kèm phân biệt với hàng bảng `Hang mo={...}` — hàng bảng GIỮ NGUYÊN bấm được vì đó là khuôn chuẩn `components/ui/Bang.tsx::Hang` cho mọi bảng, không phải điều khiển ngụ ý hành động như một ô KPI).

### Test summary

- Trước sửa: 782 passed · 6 skipped · 0 failed
- Sau sửa: **783 passed · 6 skipped · 0 failed** (60 test files, +1 bài mới)
- `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx tests/boot.test.tsx` → 2 file, 17 tests, tất cả xanh
- `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run` (cả suite) → 60 file, 783 passed · 6 skipped · 0 failed

### `npx tsc -b --force`

Output rỗng (thoát 0, không lỗi) — clean.

### `npx prettier --check` (file sửa)

`All matched files use Prettier code style!` — cả `BangGiaScreen.tsx` lẫn `billing-gia.test.tsx`.

### `git status --porcelain` (sau commit)

```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Đúng hai file vùng cấm còn `M` (không đụng). `node_modules` untracked, không liên quan.
