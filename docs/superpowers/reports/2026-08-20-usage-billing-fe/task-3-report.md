# Task 3 — báo cáo triển khai

## Phạm vi thực hiện

Đúng theo brief Task 3 + hợp đồng BE (`docs/contracts/usage-billing.md`), hợp
đồng thắng ở mọi chỗ lệch (xem mục "Lệch brief" dưới).

### Files tạo mới

- `src/features/billing/kieu.ts` — kiểu của 11 response, snake_case. Bốn
  ngoại lệ camelCase đánh dấu ⚠️ tại chỗ: `PreviewGia` (dict tay của BE),
  `DongGiaIn` (2 field), `GanBoGiaIn` (cả 2 field).
- `src/features/billing/api.ts` — 5 hook tenant (`useTongQuan`, `useTheoKey`,
  `useTheoOwner`, `usePhien`, `useChiTietPhien`) qua `goi()` trần, 6 hook admin
  (`useBoGia`, `useTaoBoGia`, `useThemDongGia`, `useKichHoat`, `usePreview`,
  `useGanChoWorkspace`) qua `goiAdmin()` (header `X-Platform-Admin-Token`,
  token đọc/lưu ở `sessionStorage`).

### Files sửa

- `src/features/billing/contracts.ts` — thêm `export type` 10 kiểu từ `kieu.ts`
  + `export { type Tien, tien }` từ `dinh-dang.ts`. **KHÔNG** đổi phần
  `BangGiaScreen` (vẫn stub của Task 1) — chưa có component nào ở task này,
  đúng bối cảnh được giao.
- `src/lib/msw/handlers.ts` — thêm fake cho 11 endpoint, snake_case đúng luật,
  hàng `agent_key_id: null` ở `by-key` (và hàng `user_id: null` ở `by-owner`,
  theo hợp đồng BE §2 — brief không nhắc riêng nhưng đây là cùng một lớp lỗi),
  `chi_phi_tong` = tổng CHÍNH XÁC các hàng kể cả hàng null (`125000.5...` =
  `60000 + 50000.5 + 15000`), event `tts` mẫu `units: 7, text_units: 1115`
  đúng ví dụ hợp đồng BE, và `thieuTokenAdmin()` chặn 401 cho cả 6 endpoint
  admin khi thiếu header.
- `src/features/billing/dinh-dang.ts` — sửa 1 dòng (`const [nguyen = '', ...]`
  thay vì `[nguyen, ...]`) để `tsc -b` sạch. Đây là bug tsc pre-existing của
  Task 2 (`nguyen` có thể `undefined` dưới `noUncheckedIndexedAccess`, dòng
  `nguyen.startsWith('-')` không có khiên) — không phải file trong danh sách
  Task 3, sửa vì nó chặn thẳng gate "tsc -b sạch" ở Step 5. Hành vi hàm không
  đổi (`'' || '0'` → `'0'`, giống hệt nhánh cũ khi `nguyen` rỗng).

## (a) Lấy `goi()` từ đâu

Đọc `src/features/platform/api.ts` và `src/features/ops/api.ts`. Chọn khuôn
của **`platform/api.ts`** (path đầy đủ truyền thẳng vào `fetch()`, không có
`GOC` prepend bên trong `goi()`) vì đó là khuôn brief trỏ tới, và vì `ops/api.ts`
dùng biến thể khác (`GOC` nội bộ + tham số `than` gộp method/body). **COPY**
nguyên `LoiApi`/`goi()` vào `features/billing/api.ts` — KHÔNG import — đúng
luật ranh giới module (`tests/module-boundaries.test.ts`), và đúng lý lẽ chính
`platform/api.ts` đã ghi khi nó tự copy thay vì import từ `auth/api.ts`.

## (b) Hợp đồng BE lệch brief chỗ nào

1. **Đường dẫn tenant thiếu prefix `/api/v1` trong code mẫu của brief**
   (`goi<TongQuan>(\`/billing/summary?...\`)`). Hợp đồng BE §"Xác thực" ghi rõ
   router không tự gắn `/api/v1` — `api/app.py` gắn — nên URL thật từ trình
   duyệt là `/api/v1/billing/...`. Vite proxy cũng chỉ khớp `'^/api/'`. Đã
   sửa thành `/api/v1/billing/...` trong `api.ts` (khớp cách mọi module khác
   trong repo gọi, vd `GOC = '/api/v1/agent/keys'` ở `platform/api.ts`).
2. **`DongOwner.user_id: null`** không chỉ là kiểu có sẵn — hợp đồng BE §2 xác
   nhận đây là hàng THẬT phải giữ (sửa 2026-08-20, trước đó INNER JOIN làm
   rớt nhóm này). Brief không nhắc yêu cầu fake phải có hàng null ở
   `by-owner` (chỉ nhắc `by-key`), nhưng tôi thêm vào fake vì cùng lớp lỗi —
   đã ghi rõ lý do trong comment tại `handlers.ts`.
3. Không phát hiện lệch nào khác giữa brief và hợp đồng ở phần dữ liệu/field
   — brief đã đồng bộ khá sát với hợp đồng cho phần Task 3 (snake_case,
   `voice_sec` chỉ tính `call`, `units`/`text_units`, `Tien = string`).

## Typecheck + Test

- `npx tsc -b --force` — **sạch**, không lỗi.
- `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`:
  **736 passed · 6 skipped · 0 failed** (trước) → **736 passed · 6 skipped ·
  0 failed** (sau). Không hồi quy, không test mới thêm ở Task 3 (chưa có
  component để test — đúng phạm vi).
- `tests/module-boundaries.test.ts`: 4/4 pass riêng (đảm bảo import
  `@/features/billing/kieu` trong `handlers.ts` không phá luật ranh giới —
  file này đã có trong `ALLOWLIST`).
- `npx prettier --check` trên cả 5 file đã đụng: sạch.

## Concerns

- `lib/msw/handlers.ts` sửa **trực tiếp trong file** theo đúng danh sách file
  của brief, thay vì tạo `features/billing/msw.ts` rồi cắm vào `HANDLERS`
  (khuôn mà chính header của `handlers.ts` mô tả và `ops`/`quality`/
  `realestate` đều theo). Không sai luật (file đã trong `ALLOWLIST`, chấp
  nhận import nhiều feature), nhưng lệch quy ước hiện có của repo — nếu người
  review muốn đồng bộ, có thể tách `FAKE_*`/`thieuTokenAdmin`/11 handler
  billing sang `features/billing/msw.ts` ở một commit sau mà không đổi hành
  vi.
- Chưa có cổng nào canh hai điều "một lớp lỗi" đã tự thêm (hàng null ở
  `by-owner`, và tổng `chi_phi_tong` khớp tay) — tự kiểm bằng mắt lúc viết
  fake, Task 5 sẽ là cổng thật.

## Fix theo review — tách fake sang `features/billing/msw.ts`

Coordinator ruling: concern đã nêu ở trên là Important, phải sửa. Ba tiền lệ
`features/ops/msw.ts` · `features/quality/msw.ts` · `features/realestate/msw.ts`
đều export một mảng `xxxHandlers` rồi `lib/msw/handlers.ts` spread vào
`HANDLERS` — đọc `features/quality/msw.ts` trước khi làm để copy đúng khuôn
(mảng đặt tên `qualityHandlers`, khai types từ `./api` bằng import cục bộ,
không import chéo module khác).

**Đã làm:**
- Tạo `src/features/billing/msw.ts` — chuyển nguyên `KEY_CHUA_PHAN_LOAI`,
  `BILLING_BY_KEY_GIA`, `BILLING_SUMMARY_GIA`, `BILLING_BY_OWNER_GIA`,
  `PHIEN_BILLING_1`/`2`, `BILLING_SESSIONS_GIA`, `EVENTS_BILLING_2`,
  `CHI_TIET_PHIEN_BILLING_GIA`, `BO_GIA_GIA`, `PREVIEW_GIA_FAKE`,
  `thieuTokenAdmin()`, và 11 handler `http.*` sang đây, export dưới tên
  `billingHandlers` (đúng khuôn `qualityHandlers`). Types import từ `./kieu`
  (nội bộ module, không phải `@/features/billing/kieu` — cùng cách
  `quality/msw.ts` import `./api`).
- `src/lib/msw/handlers.ts` — bỏ toàn bộ `FAKE_*`/`thieuTokenAdmin`/11 handler
  billing và import type billing (không còn cần). Thay bằng
  `import { billingHandlers } from '@/features/billing/msw'` (cạnh
  `opsHandlers`/`qualityHandlers`/`nguonHandlers`) và một dòng
  `...billingHandlers,` trong mảng `HANDLERS`, đặt cạnh ba spread kia — file
  giờ chỉ còn seam `/api/v1/me` + `/api/v1/linh-vuc` (bản sao tại chỗ có sẵn
  từ trước) + bốn dòng spread, đúng lời hứa của docstring đầu file ("thêm một
  dòng, không sửa gì khác").
- Hành vi giữ nguyên 100% — không đổi field, giá trị, hay logic
  `thieuTokenAdmin`, chỉ đổi vị trí file.

**Đã chạy và kết quả:**
- `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/module-boundaries.test.ts tests/billing-dinh-dang.test.ts`
  → `Test Files 2 passed (2)`, `Tests 27 passed (27)`.
- `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run` (cả suite)
  → `Test Files 57 passed (57)`, `Tests 736 passed | 6 skipped (742)` — đúng
  con số yêu cầu, không hồi quy.
- `npx tsc -b --force` → sạch, không output, không lỗi.
- `npx prettier --check src/features/billing/msw.ts src/lib/msw/handlers.ts`
  → `All matched files use Prettier code style!`.

Commit fix: `<xem hash trong phần trả lời>`.
