/**
 * Mặt tiền công khai của `features/billing` — module KHÁC chỉ được import từ
 * đây, không import ruột `api.ts`/`components/*` (luật ranh giới module,
 * `tests/module-boundaries.test.ts`).
 *
 * ⚠️ CHỈ xuất thứ có người dùng THẬT từ ngoài module — hai component màn dưới
 * đây (`routes/_app/billing.tsx`, `routes/_app/pricing.tsx`). Review 2026-08-20
 * dọn 15 export mồ côi (11 type + `Tien`/`tien` + `TenKy`/`giaiMaKy`): không
 * chỗ nào ngoài module import chúng qua mặt tiền này — test đọc thẳng
 * `kieu.ts`/`dinh-dang.ts`/`ky.ts` vì chúng ở CÙNG module (`tests/` không bị
 * luật ranh giới ràng buộc). Một export mồ côi là lời hứa không ai gọi; ngày
 * một module khác cần một type/hàm cụ thể thì thêm đúng một dòng ở đây.
 */

/**
 * Màn `/billing` (Task 4) — khung: hàng chọn kỳ, dải cảnh báo, năm thẻ KPI.
 * `route`/`routes/_app/billing.tsx` là chỗ DUY NHẤT gọi tới đây; nó cầu nối
 * `Route.useSearch()`/`useNavigate()` sang hai prop `tim`/`datTim` của
 * `UsageScreen` — xem docstring đầu file component để rõ vì sao KHÔNG làm
 * ngược lại (component tự đọc `Route` của route đang render nó).
 */
export { UsageScreen, type UsageTim } from './components/UsageScreen'
export { UsageLuongDungScreen, type UsageLuongTim } from './components/UsageLuongDungScreen'

/**
 * Ô «Chi phí» ở `/dashboard` (module `ops`; trước 06/10 là ô ⑥ «Usage & Billing»
 * hai tile) — đọc thẳng `GET /billing/summary`. `useTongQuan`/`TongQuan` là số
 * liệu; `tien`/`tienGon` là hàm định dạng tiền của module này (đừng tự viết lại —
 * xem bẫy `"0E-10"` ở `dinh-dang.ts`); `SparklineChiPhi` là hình chi phí theo
 * ngày dùng lại NGUYÊN VẸN từ thẻ «Tổng chi phí» của mục ① `/billing`; `TopDichVu`
 * là bản gọn của thẻ «Theo từng dịch vụ» (cùng nhãn, cùng màu theo thứ hạng).
 */
export { useTongQuan } from './api'
export type { TongQuan } from './kieu'
export { tien, tienGon } from './dinh-dang'
export { SparklineChiPhi } from './components/SparklineChiPhi'
export { TopDichVu } from './components/TopDichVu'
/** Ô Chi phí khoá kỳ vào "Tháng này" — cùng công thức `/billing` dùng làm mặc định
 *  (2026-08-28, người dùng chốt sau khi so ảnh chụp: kỳ 7 ngày của Tổng quan
 *  làm biểu đồ trông "khác hẳn" bản thật trên `/billing` mỗi khi tuần gần
 *  nhất ít hoạt động — không phải bug, chỉ là hai kỳ khác nhau). */
export { giaiMaKy } from './ky'

/**
 * Màn `/pricing` (Task 8) — dải token quản trị nền tảng + ba ô số + bảng danh
 * sách bộ giá. `routes/_app/pricing.tsx` là chỗ DUY NHẤT gọi tới đây; khác
 * `UsageScreen`, màn này không đọc search param nào nên route chỉ cần gán
 * thẳng làm `component`, không cần cầu nối `useSearch()`/`useNavigate()`.
 */
export { BangGiaScreen } from './components/BangGiaScreen'
