/**
 * Nhãn tiếng Việt cho các giá trị enum của backend — MỘT chỗ cho cả module auth.
 *
 * Còn ở đây: `NHAN_LIFECYCLE` + `MAU_LIFECYCLE` (trạng thái tài khoản). Gom một
 * chỗ vì nhiều màn của M2b cùng cần chúng, và mỗi bản sao là một chỗ lệch khi
 * PQ_01 §2.4 đổi từ ngữ.
 *
 * `NHAN_VAI_TRO` (nhãn cho vai trò theo workspace) ĐÃ XOÁ 2026-08-06 cùng enum
 * `VaiTro`: vai trò giờ là chữ tự do owner tự đặt, không bảng nhãn cố định nào
 * dịch được — chỗ nào hiện vai trò thì in thẳng chuỗi backend trả.
 *
 * `NHAN_ORG_ROLE` · `NHAN_NHOM_ACTION` · `THU_TU_NHOM_ACTION` · `nhanHetHan` ·
 * `isoSangNgayInput` · `ngayInputSangIso` ĐÃ XOÁ 2026-08-09 cùng cây tự-tạo-vai-
 * trò và ô `expiresAt`: `UserAdmin` hiện «Chủ tổ chức» bằng chữ tại chỗ (một
 * nhãn không cần một bảng tra), và không màn nào còn đặt hạn membership.
 *
 * TÊN KỸ THUẬT Ở DB, NHÃN TIẾNG VIỆT Ở GIAO DIỆN — và phép dịch chỉ đi một chiều:
 * không hàm nào ở đây dịch ngược từ nhãn về giá trị. Gửi lên API luôn là giá trị
 * gốc (`'owner'`), không bao giờ là chuỗi người đọc.
 */
import type { Lifecycle } from './api'

export const NHAN_LIFECYCLE: Record<Lifecycle, string> = {
  /**
   * ĐỔI TỪ «Chờ nhận lời mời» 2026-08-22. Nhãn cũ nay thuộc về hàng LỜI MỜI
   * (`NHAN_CHO_XAC_NHAN` bên dưới). Một hàng THÀNH VIÊN mang `pending` từ nay chỉ
   * còn nghĩa một thứ: tài khoản di sản chưa đặt mật khẩu — sau thay đổi này không
   * sinh thêm ca đó nữa. Hai nhãn gần giống nhau cho hai thứ khác nhau là chỗ đọc sai.
   */
  pending: 'Chưa đặt mật khẩu',
  active: 'Đang hoạt động',
  suspended: 'Đã đình chỉ',
}

/** Trạng thái của hàng `kind='invite'` — suy từ `kind`, KHÔNG từ `lifecycle`. */
export const NHAN_CHO_XAC_NHAN = 'Chờ xác nhận lời mời'
export const MAU_CHO_XAC_NHAN = 'bg-badge-warn-bg text-badge-warn-fg'

/**
 * Lớp Tailwind cho chip trạng thái tài khoản.
 *
 * ⚠ Docstring cũ ở đây biện minh màu `warn` của `pending` bằng «hệ thống này không
 * gửi email, nên `pending` là việc đang chờ ĐÍCH THÂN admin làm». Câu đó lỗi thời
 * từ khi có `core/mailer.py`, và lỗi thời hai lần từ 2026-08-22: việc-đang-chờ giờ
 * là hàng LỜI MỜI, và nó mang màu warn ở `MAU_CHO_XAC_NHAN`. `pending` ở đây là
 * một tài khoản di sản — vẫn `warn`, nhưng vì nó là một tài khoản không đăng nhập
 * được, không vì ai đang chờ.
 */
export const MAU_LIFECYCLE: Record<Lifecycle, string> = {
  pending: 'bg-badge-warn-bg text-badge-warn-fg',
  active: 'bg-badge-neutral-bg text-badge-neutral-fg',
  suspended: 'bg-badge-alert-bg text-badge-alert-fg',
}
