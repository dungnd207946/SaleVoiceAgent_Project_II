/**
 * Lớp CSS dùng chung của module `billing` — cùng khuôn
 * `features/agent/components/lop.ts`.
 *
 * `SO_LON` là công thức CON SỐ NỔI BẬT của portal, chép từ chỗ đã có sẵn chứ
 * không phát minh lại: `/dashboard` dùng đúng bộ này ở bốn nơi, tất cả cùng
 * **30px** từ 2026-09-08 (`TongQuanScreen.tsx` · `TheDanhGia.tsx` — người
 * dùng chốt đồng bộ một cỡ cho các ô số của dashboard; `GaugeNuaCung.tsx` đã
 * xoá 06/10). Font, độ đậm, `leading`, `tracking` vẫn khoá lại ở đây như cũ.
 *
 * ⚠️ ĐỘ ĐẬM LÀ 500, KHÔNG PHẢI 600. Trước 2026-08-21 thẻ «Tổng chi phí»
 * của `/billing` dùng `font-semibold` (600) còn bốn thẻ cạnh nó dùng
 * `font-medium` (500) — chủ ý «thẻ nhấn đậm hơn», nhưng nó đứng CẠNH bốn thẻ
 * cùng hàng nên hai độ đậm đọc ra thành hai kiểu chữ khác nhau, không ra một
 * thứ bậc. Cỡ chữ 32 vs 26 đã nói đủ điều mà `font-semibold` định nói. Cả
 * `/dashboard` lẫn `/pricing` đều dùng 500 cho MỌI con số lớn — 600 ở đây là
 * ngoại lệ duy nhất của cả portal.
 *
 * `tabular-nums`: xem `TD_SO` ở `components/ui/Bang.tsx`.
 */
export const SO_LON = 'font-mono font-medium leading-none tracking-tight tabular-nums'
