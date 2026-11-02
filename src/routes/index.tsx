import { createFileRoute } from '@tanstack/react-router'
import { TrangGioiThieu } from '@/components/landing/TrangGioiThieu'

/**
 * `/` — trang giới thiệu CÔNG KHAI.
 *
 * NGOÀI `_app`, cùng lý do với `/login`: `_app` bọc `<SessionProvider>` và
 * provider đó chặn cả cây trên `GET /api/v1/me`. Trang này phải render được khi
 * chưa có phiên — đó là toàn bộ lý do nó tồn tại.
 *
 * Thay cho `_app/index.tsx` cũ (redirect `/` → `/dashboard`). Hai tệp không
 * sống chung được: `_app` là layout pathless nên `_app/index.tsx` cũng ra path
 * `/`, và tsr sẽ có hai route cùng đường dẫn.
 *
 * Người ĐÃ đăng nhập vào `/` vẫn thấy trang này chứ không bị đẩy sang
 * `/dashboard`. Cố ý: biết có phiên hay không là việc của `SessionProvider`,
 * mà provider chỉ sống trong `_app`. Muốn đẩy thì phải gọi `/api/v1/me` ngay ở
 * đây — tức thêm một chỗ thứ hai biết hình dạng seam phiên, đúng thứ
 * `lib/session.tsx` được viết để tránh. Nút «Đăng nhập portal» đi `/login`, và
 * `/login` mới là chỗ biết đẩy tiếp đi đâu.
 */
export const Route = createFileRoute('/')({
  component: TrangGioiThieu,
})
