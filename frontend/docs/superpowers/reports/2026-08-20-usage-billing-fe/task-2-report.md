# Task 2 — báo cáo triển khai

## Phạm vi thực hiện

Đúng theo brief Task 2 (`dinh-dang.ts`), **cộng thêm** `ky.ts` theo ruling của
người giao việc (Task 4 Step 3 tạo `ky.ts` và ghi test vào cùng
`tests/billing-dinh-dang.test.ts` — làm ở đây để tránh hai task cùng đụng một
diff test).

### Files tạo mới

- `src/features/billing/dinh-dang.ts` — `Tien = string`, `tien()`/`tienDay()`
  (BigInt, không parse qua `number`), `token()`, `giay()`, `phanTram()`,
  `rong()`.
- `src/features/billing/ky.ts` — `TenKy`, `giaiMaKy()` (khoảng `from`/`to`
  nửa mở theo đúng ruling, `dangChay` cho biết kỳ có đang chạy dở không).
- `tests/billing-dinh-dang.test.ts` — 23 test (gộp cả hai file trên).

## Kiểm code `tien()` brief đưa — ba ca biên người giao việc yêu cầu tự kiểm

Đã trace tay + viết test cho cả ba ca, **code brief đưa ĐÚNG, không cần sửa**:

| Input | Kỳ vọng | Kết quả | Ghi chú |
|---|---|---|---|
| `'0.5'` | `'1'` | `'1'` | digit đầu phần thập phân `5 >= 5` ⇒ làm tròn lên |
| `'-1204500.6'` | giữ dấu, tròn đúng | `'-1.204.501'` | `nguyên = '-1204500'`, cộng thêm `-1n` vì digit đầu `6>=5` và có dấu `-` — đúng "round half away from zero" |
| `'1204500'` (không thập phân) | `'1.204.500'` | `'1.204.500'` | `le = ''`, `le[0] ?? '0'` → `'0'` → không làm tròn thêm, `BigInt` nhóm nghìn đúng |

Ba ca này đã thêm thành test riêng (`tien` describe block) — không phải chỉ
verify tay rồi bỏ qua.

## Test

Chạy đúng cờ Node bắt buộc: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`.

- File mới: **23/23 pass** (`tests/billing-dinh-dang.test.ts`).
- Toàn bộ suite: **713 passed · 6 skipped · 0 failed** (baseline, trước) →
  **736 passed · 6 skipped · 0 failed** (sau). Không hồi quy — chênh lệch
  đúng bằng 23 test mới thêm.

## Định dạng

`npx prettier --write` trên cả 3 file đã tạo (đúng luật "chấm theo file").

## Concerns

Không có. Code brief đưa cho `tien()` đúng ở mọi ca biên đã kiểm; `ky.ts`
theo đúng nội dung "đã chốt" của ruling, thêm test bắc qua mốc năm
(`thang-truoc` tháng 1 → tháng 12 năm trước) và mốc tháng (`30-ngay`).
