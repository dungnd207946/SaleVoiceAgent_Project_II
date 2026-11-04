# Task 7 — Báo cáo

**Status:** DONE
**Commit:** `8e3e2bb` (branch `feat/usage-billing-fe`)

## Test summary

- Trước: 771 passed · 6 skipped · 0 failed (baseline đề bài)
- Sau: **777 passed · 6 skipped · 0 failed** (60 test files) — đúng +6 test mới
  (5 ở `tests/billing-gia.test.tsx` + 1 ở `tests/billing-phien.test.tsx`)
- Chạy bằng: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`

## `npx tsc -b --force`

Output rỗng (thoát 0, không lỗi) — clean.

## `git status --porcelain` (sau commit)

```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Đúng hai file vùng cấm còn `M` (không đụng), không `git add` chúng. `node_modules` untracked, không liên quan.

## Số dòng `PRICING_BASIS` đếm từ nguồn

**12 dòng**, đếm trực tiếp từ `odyssey-portal-backend/docs/build_module_usage&billing/pricing-schema.sql` (mục 3b, `INSERT INTO billing.pricing_basis`) và đối chiếu với `migrations/versions/0943_billing_pricing.py` (11 dòng gốc) + `0948_billing_text_units.py` (thêm đúng 1 dòng `stt/conversation/text_units`) — khớp brief.

## Concerns / phát hiện thêm khi đối chiếu nguồn

Brief đưa code mẫu có một lỗi KHÔNG nằm trong hai con số được cảnh báo sẵn:
dòng `call` trong `PRICING_BASIS` ghi `metric: 'wall_ms', per_units: 60_000`.
Đối chiếu `pricing-schema.sql` dòng `('call', '', 'audio_sec', 'thời lượng
cuộc gọi — phí nền tảng/phút')` và cả hai migration `0943`/`0948` thì `call`
tính theo **`audio_sec`** (giây), không phải `wall_ms` (mili-giây). Đã sửa
thành `{ component: 'call', metric: 'audio_sec', per_units: 60, dvi: 'đ
/phút' }` (60 giây/phút, thay vì 60_000 chỉ đúng cho đơn vị mili-giây) và ghi
rõ trong docstring của file lý do khác bản nháp gốc. Thêm một bài test riêng
khoá đúng dòng này (`call tính theo audio_sec …`) trong `billing-gia.test.tsx`.

Không có concern nào khác. Việc ② (fix key `nhomTheoLuot`/`KhoiLuot`) đã kiểm
ngược: khôi phục tạm `key={n.turnIdx ?? 'null'}` ⇒ bài test mới đỏ đúng ở
assertion cảnh báo key trùng của React; khôi phục lại fix ⇒ xanh.

Thang chữ 9 bậc: mọi `text-[Npx]` trong `src/features/billing/` đều nằm trong
tập `{32,26,20,16,13.5,12.5,11,10.5}` — không có bậc lạ (task này không thêm
CSS nào ngoài comment).
