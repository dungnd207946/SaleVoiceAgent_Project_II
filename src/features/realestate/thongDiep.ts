/**
 * Mã lỗi backend → câu người dùng SỬA ĐƯỢC.
 *
 * VÌ SAO KHÔNG HIỆN THẲNG `error.message`: với `VALIDATION_ERROR` thì message của
 * backend là *"Dữ liệu gửi lên không hợp lệ (2 lỗi): body.mediaUrl, body.status"*
 * — đúng cho log, vô dụng cho người đang nhập liệu (họ không biết "body." là gì).
 * Một bảng dịch ở đây là chỗ DUY NHẤT biết cách nói tiếng Việt của người dùng.
 *
 * Mã LẠ (module backend thêm mã mới mà FE chưa biết) rơi về `message` của
 * backend, không rơi về "Có lỗi xảy ra": message của backend luôn là một câu
 * tiếng Việt đọc được, nên nó là bản dự phòng tốt hơn một câu chung.
 */
import { LoiApi } from '@/lib/http'

export function cauLoi(e: unknown, viec: string): string {
  if (!(e instanceof LoiApi)) return `Không ${viec} được. Kiểm tra kết nối mạng rồi thử lại.`

  switch (e.code) {
    case 'VALIDATION_ERROR':
      return e.truong.length === 1
        ? 'Một ô chưa hợp lệ — xem ô được tô đỏ bên dưới.'
        : `${e.truong.length} ô chưa hợp lệ — xem các ô được tô đỏ bên dưới.`

    case 'DUPLICATE_CODE':
      return 'Mã này đã tồn tại. Chọn một mã khác.'

    case 'SENTINEL_PROTECTED':
      return 'Đây là bản ghi hệ thống (tài liệu chung toàn workspace) — không sửa trạng thái hay xoá được.'

    case 'INCOMPLETE_DATA':
      return `Chưa phát hành được — ${e.message.replace(/^Thiếu dữ liệu bắt buộc để publish: /, 'còn thiếu: ')}`

    case 'PROJECT_NOT_FOUND':
    case 'ZONE_NOT_FOUND':
    case 'UNIT_NOT_FOUND':
    case 'DOCUMENT_NOT_FOUND':
    case 'MEDIA_NOT_FOUND':
      return 'Bản ghi này không còn tồn tại — có thể vừa bị xoá ở nơi khác. Danh sách đã được nạp lại.'

    case 'INVALID_CURSOR':
      return 'Trang đã cũ. Nạp lại danh sách từ đầu.'

    case 'UNSUPPORTED_TYPE':
    case 'FILE_TOO_LARGE':
    case 'NO_FILE':
      return e.message

    default:
      return e.message
  }
}

export function laBienMat(e: unknown): boolean {
  return (
    e instanceof LoiApi &&
    [
      'PROJECT_NOT_FOUND',
      'ZONE_NOT_FOUND',
      'UNIT_NOT_FOUND',
      'DOCUMENT_NOT_FOUND',
      'MEDIA_NOT_FOUND',
    ].includes(e.code)
  )
}

export function loiO(e: unknown, ten: string): string | undefined {
  return e instanceof LoiApi ? e.loiCua(ten) : undefined
}
