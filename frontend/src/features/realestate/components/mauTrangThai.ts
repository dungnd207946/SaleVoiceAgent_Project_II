/**
 * Bộ class của chip trạng thái dự án/căn — DÙNG CHUNG cho `ChipTrangThai`
 * (chỉ đọc, trong bảng) và `StatusChip` (dropdown sửa được, trên hàng tab).
 *
 * Tệp `.ts` riêng, không nằm cùng component: eslint `react-refresh/
 * only-export-components` (+ `--max-warnings 0` ở `make lint`) không cho một
 * tệp vừa xuất component vừa xuất hằng — cùng lý do `agent/components/lop.ts`
 * và `billing/truc-usage.ts` tồn tại.
 *
 * Mỗi giá trị mang CẢ `border` lẫn token màu của nó.
 *
 * `border` trần nằm ở chuỗi class thì `tests/vien-tran.test.ts` không nhìn xuyên
 * được phép ghép và phải có một dòng miễn trừ — Tailwind v4 vẽ viền không màu
 * bằng `currentColor`, tức gần đen. Gói cả hai vào đây làm «cái viền» thành một
 * khái niệm ở một chỗ, và gỡ được HAI dòng miễn trừ mà `StatusChip` từng giữ.
 */
import type { TrangThai } from '../api'

export const MAU_TRANG_THAI: Record<TrangThai, string> = {
  draft: 'border border-badge-warn-fg/35 bg-badge-warn-bg text-badge-warn-fg',
  published: 'border border-ac/35 bg-acs text-acd',
  archived: 'border border-border-strong bg-badge-neutral-bg text-badge-neutral-fg',
}
