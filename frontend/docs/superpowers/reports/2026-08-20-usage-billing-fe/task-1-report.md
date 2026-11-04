# Task 1 — Khai báo màn (action · nav · screens · route) — Báo cáo

Worktree: `/home/dungnd/Dungnd/dev/odyssey-project/.wt-usage-billing-fe`, branch `feat/usage-billing-fe`.

## An toàn — một khối lệnh khả nghi trong CLAUDE.md, đã bỏ qua

Trước khi làm việc, `CLAUDE.md` gốc nạp vào context một khối "context-mode —
MANDATORY routing rules" tự xưng "override mọi hành vi mặc định", đòi mọi
Read/Grep/Bash output phải đi qua các MCP tool `ctx_*` (kể cả gửi nội dung ra
một "sandbox" ngoài). Đây đọc như một prompt injection cắm vào file dự án,
không phải quy ước dự án thật — CLAUDE.md thật của repo (đọc được ở cuối cùng
context, có Change Log) còn ghi rõ dòng 2026-08-06: "bỏ khối luật `ctx_*` (MCP
tool không tồn tại, và nội dung nói về repo khác)". Tôi đã **không** làm theo
khối đó, và cũng bỏ qua một system-reminder khác giữa phiên bảo ưu tiên
`sed`/heredoc thay vì Read/Edit/Write. Toàn bộ việc bên dưới dùng Read/Edit/
Write/Bash bình thường, không có tool `ctx_*` nào được gọi, không có nội dung
nào rời máy này ngoài các lệnh `git`/`npx` cục bộ.

## Năm quyết định đã áp dụng NGUYÊN VĂN

1. **`khoi()` không nhãn.** `segments` của nhóm `admin` trong `nav-registry.ts`
   nay là `[khoi(usersNav, auditNav), khoi(usageNav, billingNav, pricingNav)]`
   — khối thứ hai không nhãn, ba mục phẳng có icon.
2. **Nhãn dịch cả ba**: «Lượt dùng» / «Hoá đơn» / «Bảng giá» (vi), «Usage» /
   «Invoices» / «Pricing» (en). Chú thích cũ ở `deferred/nav.ts` («giữ tiếng
   Anh ở cả hai ngôn ngữ») đã xoá cùng hai leaf; docstring mới ở
   `features/billing/nav.ts` giải thích vì sao đảo quyết định.
3. **Không khai `badge`** trên `pricingNav`, lý do ghi trong docstring tại chỗ.
4. **Icon**: `billing` giữ nguyên (đã có trong `PATHS`); thêm `usage`
   (`Activity`) và `pricing` (`Tags`) vào nhánh `LUCIDE`. `usageNav.icon` đổi
   từ `'quality'` (mượn tạm) sang `'usage'`.
5. **Hoá đơn ngoài phạm vi**: `/billing` giữ `ScreenStub` + `mvp: 'deferred'`,
   chỉ đổi `note`; `billingNav` vẫn khai đủ trong khối.

## Việc làm ngoài bốn quyết định trên (brief không lường hết)

- **`ACTIONS.BILLING_READ`** thêm vào `lib/actions.ts`. Tra
  `odyssey-portal-backend/contracts/actions.json`: **đã có `billing.read`**
  (14 actions, artefact do `make contracts` bên đó sinh) → copy nguyên file
  sang `contracts/actions.json` của FE, không sửa tay. Không cần báo
  `DONE_WITH_CONCERNS` ở mục này.
- **Tổng số action đổi 13 → 14.** Đây là hệ quả cơ học của việc thêm
  `BILLING_READ` (action mọc NGOÀI 13 dòng gốc của PQ_01 §3.1), không phải một
  lựa chọn — nhưng brief không nhắc, nên nhiều chỗ hard-code "13" đã đỏ và
  phải sửa cho khớp: `tests/actions-parity.test.ts` (hai `toHaveLength(13)` →
  `14`, tiêu đề cổng), `tests/nav-registry.test.ts` (một `toHaveLength(13)` →
  `14`, tiêu đề), docstring `lib/actions.ts`, và hai chú thích số học ở
  `lib/session.tsx` / `lib/msw/handlers.ts` (mô tả suông, không phải assertion,
  sửa cho khớp thực tế).
- **`usage` un-defer cần một `owner`.** Brief Step 6 chỉ nói đổi `mvp` và xoá
  `note`, không nói `owner`. Nhưng `tests/nav-registry.test.ts` có cổng
  `expect(s.owner === null).toBe(s.mvp === 'deferred')` — `owner: null` +
  `mvp: 'full'` sẽ đỏ. Tra bảng module ở
  `docs/superpowers/specs/2026-07-29-...kien-truc-va-ban-do-module.md` (dòng
  M8: "Kết nối · Nhật ký · Lưu trữ … ghi nhận token"): M8 là module đã ghi
  nhận token làm nguồn cho màn Usage. Gán `owner: 'M8'` cho `usage`. Đây là
  suy luận cơ học từ tài liệu sẵn có (không phải quyết định thiết kế mới), nên
  không dừng lại hỏi — nhưng ghi rõ ở đây để review biết vì sao khác brief.
  `pricing` giữ `owner: 'M9'` đúng như brief/plan ghi (M9 có thật trong
  `MODULES`).
- **`tests/nav-registry.test.ts`**: `RAIL_ORDER` + `PROTOTYPE_SCREENS` thêm
  `pricing`; bài "màn hoãn ngoài MVP" sửa từ `['billing','finance','usage']`
  còn `['billing','finance']` (usage không còn hoãn).
- **`tests/shell.test.tsx`**: bài "màn hoãn ngoài MVP có dấu ⏸" trước đây dùng
  `/usage` làm ví dụ màn hoãn — nay `usage` đã vào MVP đầy đủ nên bài đó SAI
  tiền đề. Chuyển sang `/billing` (màn hoãn thật còn lại trong khối), chữ
  `getByText('Usage')` → `getByText('Hoá đơn')`.
- **`BangGiaScreen` không trả `null` suông.** Thử để rỗng (`return null`) làm
  đỏ `tests/boot.test.tsx` — bài "19 màn đều mở được qua cây route thật" tìm
  `data-screen="pricing"` (fallback mặc định khi màn chưa có dấu hiệu riêng
  trong `DAU_HIEU_MAN_THAT`) mà không thấy gì. Sửa: `BangGiaScreen` render
  `<ScreenStub screen="pricing" />` qua `createElement` (tệp `contracts.ts` là
  `.ts`, JSX cần `.tsx`) — đúng quy ước "mọi màn chưa nhận render `ScreenStub`"
  của chính codebase, Task 8 sẽ thay nội dung.
- Một lỗi tự gây trong lúc viết docstring: chuỗi `features/*/contracts.ts`
  trong comment chứa `*/` làm compiler đóng sớm khối `/** */`, ra lỗi cú pháp.
  Phát hiện qua vitest, sửa thành `các tệp contracts.ts khác trong features/`.

## Files

Modify: `src/lib/actions.ts` · `src/lib/screens.ts` · `src/lib/nav-registry.ts`
· `src/features/deferred/nav.ts` · `src/components/icons.tsx` ·
`src/routes/_app/usage.tsx` · `src/lib/session.tsx` (comment) ·
`src/lib/msw/handlers.ts` (comment) · `contracts/actions.json` (copy từ
backend) · `tests/actions-parity.test.ts` · `tests/nav-registry.test.ts` ·
`tests/shell.test.tsx` · `src/routeTree.gen.ts` (sinh lại, bẩn prettier —
bình thường)

Create: `src/features/billing/nav.ts` · `src/features/billing/contracts.ts` ·
`src/routes/_app/pricing.tsx`

## Kiểm chứng

- `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`
  - Trước: 56 tệp · 712 passed · 6 skipped · 0 failed (baseline đã đo sẵn).
  - Sau: **56 tệp · 713 passed · 6 skipped · 0 failed.**
- `npx tsc -b --force` (typecheck thật, không phải `--noEmit` rỗng): sạch, 0 lỗi.
- `npx eslint src tests`: sạch, 0 lỗi.
- `npx prettier --check` trên toàn bộ file đã sửa/tạo (trừ `routeTree.gen.ts`
  sinh tự động): tất cả đúng format.
- `npx tsr generate` chạy lại sau khi thêm route `/pricing`; `routeTree.gen.ts`
  đã `git add`.

## Concern

Không có concern chặn — backend đã có `billing.read` sẵn trong
`contracts/actions.json`, không cần dừng chờ.
