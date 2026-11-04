import { createFileRoute } from '@tanstack/react-router'
import { NhanLoiMoi } from '@/features/auth/components/NhanLoiMoi'

// NGOÀI `_app` — cùng lý lẽ `login.tsx`, và ở đây nó còn gắt hơn: `_app` bọc
// <SessionProvider>, provider đó đẩy về /login khi `GET /me` trả 401, và người
// được mời thì CHƯA CÓ mật khẩu để đăng nhập. Đặt màn này bên trong tạo một vòng
// kín: bấm link -> /login -> không vào được -> không đặt được mật khẩu.
//
// Token nằm trong đường dẫn vì nó phải là một link bấm được từ tin nhắn. Đánh đổi
// (token vào access log của proxy) được bù bằng hạn 7 ngày + dùng một lần — xem
// docstring `xem_loi_moi` ở backend.
export const Route = createFileRoute('/invite/$token')({
  component: ManNhanLoiMoi,
})

function ManNhanLoiMoi() {
  const { token } = Route.useParams()
  return <NhanLoiMoi token={token} />
}
