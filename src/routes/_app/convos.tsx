import { createFileRoute, Outlet } from '@tanstack/react-router'

/**
 * Layout route — CHỈ render route con qua `<Outlet/>`. `/convos` (danh sách,
 * Task 5, dọn sang `convos.index.tsx`) và `/convos/$phone` (chi tiết, Task 6,
 * `convos.$phone.tsx`) là hai route CON của route này.
 *
 * FINDING 1 (review cuối nhánh M7, 2026-08-06): bản trước trả THẲNG
 * `<KhachList/>` ở đây, không có `<Outlet/>`. `Outlet` là nơi DUY NHẤT
 * TanStack Router render match con — đọc `Match.js` của thư viện xác nhận
 * không có fallback ngầm. Hệ quả thật: bấm một hàng khách đổi URL sang
 * `/convos/$phone` nhưng màn vẫn là danh sách, `PhienKhach` (Task 6) không
 * bao giờ mount — toàn bộ Task 6 không tới được người dùng.
 *
 * Sửa bằng khuôn chuẩn flat-route của TanStack: route cha là layout thuần,
 * danh sách chuyển xuống `convos.index.tsx` (route index của `/convos`) —
 * KHÔNG rẽ nhánh `{s.phone ? <Outlet/> : <KhachList/>}` ở đây, vì cách đó trộn
 * hai trách nhiệm (layout + danh sách) vào một tệp.
 *
 * `tests/nav-registry.test.ts` chỉ đối chiếu route CẤP MỘT của `_app` với nav —
 * `convos.index.tsx` là route con giống `convos.$phone.tsx`, không cần khai thêm.
 */
export const Route = createFileRoute('/_app/convos')({
  component: () => <Outlet />,
})
