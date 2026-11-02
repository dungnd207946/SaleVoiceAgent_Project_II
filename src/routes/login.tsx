import { createFileRoute } from '@tanstack/react-router'
import { LoginForm } from '@/features/auth/components/LoginForm'

/**
 * NGOÀI `_app` — cố ý. `_app` là layout của mọi màn SAU đăng nhập và nó bọc
 * <SessionProvider>; màn này phải render được khi chưa có phiên.
 *
 * `?loi=` là đường lỗi CỦA CỬA GOOGLE: callback là điều hướng trình duyệt nên
 * nó không trả JSON được, và envelope `{error:{code,message}}` không có chỗ để
 * đi. Xem `modules/auth/router.py::_ve_login`.
 */
const NHAN_LOI: Record<string, string> = {
  STATE_HET_HAN: 'Phiên đăng nhập Google đã quá hạn. Bấm lại nút để thử lần nữa.',
  GOOGLE_TU_CHOI:
    'Google không hoàn tất được lần đăng nhập này. Thử lại, hoặc dùng email và mật khẩu.',
  EMAIL_CHUA_XAC_THUC: 'Tài khoản Google này chưa xác thực email. Xác thực ở Google rồi quay lại.',
  TAI_KHOAN_DINH_CHI:
    'Tài khoản của bạn đã bị đình chỉ. Liên hệ quản trị viên của tổ chức để được mở lại.',
  DANG_KY_DANG_TAT: 'Portal đang tạm ngừng nhận tài khoản mới.',
}

export const Route = createFileRoute('/login')({
  // Trả `loi` như một khoá TUỲ CHỌN (`{}` khi vắng), KHÔNG phải khoá luôn có
  // mặt với giá trị `string | undefined` — TanStack Router suy "route này BẮT
  // BUỘC `search`" từ chính hình dạng khoá, không phải từ giá trị. Bản đầu
  // (`{ loi: ... ?? undefined }`) làm MỌI `<Link to="/login">` sẵn có trong
  // app (trang giới thiệu, nút "Đăng nhập" ở `/dang-ky`, `/invite/<token>`,
  // `SessionProvider`) đỏ ở `tsc -b` vì chúng không truyền `search` — chúng
  // không nên phải biết gì về `?loi=` của riêng cửa Google.
  validateSearch: (s: Record<string, unknown>): { loi?: string } =>
    typeof s.loi === 'string' ? { loi: s.loi } : {},
  component: ManDangNhap,
})

function ManDangNhap() {
  const { loi } = Route.useSearch()
  // Mã lạ -> không hiện gì. Một mã ta không biết nghĩa là backend đã đi trước FE
  // một bản deploy; hiện mã thô ra màn đăng nhập không giúp ai cả.
  return <LoginForm loiBanDau={loi ? NHAN_LOI[loi] : undefined} />
}
