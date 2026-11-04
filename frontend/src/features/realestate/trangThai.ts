/**
 * `status` của CĂN suy ra từ completeness. Của DỰ ÁN thì KHÔNG — nó là ô người
 * dùng chọn ở tab Tổng quan từ 2026-08-11 (`trangThaiDuAn` đã xoá cùng ngày).
 *
 * VÌ SAO SUY CHỨ KHÔNG CỨNG `'published'`: cổng `_chan_tao_moi_thieu` của backend
 * từ chối 422 khi một bản ghi THÀNH `published` mà thiếu trường bắt buộc, nên gửi
 * cứng `published` làm lần Lưu đầu của một căn mới luôn bị chặn.
 *
 * VÌ SAO KHÔNG BỎ TRỐNG: gửi thiếu `status` thì DB dùng `DEFAULT 'draft'` — cùng
 * kết quả cho bản ghi thiếu, nhưng do tình cờ, và bản ghi ĐỦ trường cũng thành
 * `draft`, tức agent không đọc căn nào.
 *
 * `archived` không có đường tạo từ form căn. Bản ghi đang `archived` giữ nguyên —
 * `hienTai` là cách hàm này biết điều đó mà không tự sinh ra `archived` bao giờ.
 */
import { thieuTruongCan } from './completeness'
import type { TrangThai } from './api'

export function trangThaiCan(
  c: Parameters<typeof thieuTruongCan>[0],
  hienTai: TrangThai | undefined,
): TrangThai {
  if (hienTai === 'archived') return 'archived'
  return thieuTruongCan(c).length === 0 ? 'published' : 'draft'
}
