/**
 * Chip trạng thái CHỈ-ĐỌC — dùng trong bảng danh sách, nơi mỗi hàng là một bản ghi.
 *
 * Khác `StatusChip.tsx`: cái kia là một dropdown SỬA ĐƯỢC, treo trên hàng tab và
 * PATCH `projects.status`. Một dropdown trong mỗi hàng của bảng 5.609 căn là 5.609
 * cửa sửa mà không ai xin, nên bảng chỉ HIỆN.
 *
 * MÀU LÀ HẰNG DÙNG CHUNG (`MAU_TRANG_THAI`, ở `mauTrangThai.ts`) chứ không phải
 * bản chép: hai bản là hai chỗ phải sửa mỗi lần đổi một sắc độ, và cái thứ hai
 * luôn là cái bị quên — thấy ngay bằng mắt vì cùng một portal mà chip chỗ này
 * khác chỗ kia. Hằng KHÔNG nằm trong tệp này: eslint `react-refresh/
 * only-export-components` (+ `--max-warnings 0`) không cho một tệp vừa xuất
 * component vừa xuất hằng — cùng lý do `agent/components/lop.ts` tồn tại.
 */
import type { TrangThai } from '../api'
import { TRANG_THAI, nhanCua } from '../enums'
import { MAU_TRANG_THAI } from './mauTrangThai'

export function ChipTrangThai({ status }: { status: TrangThai }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-nhan font-semibold ${MAU_TRANG_THAI[status]}`}
    >
      <span aria-hidden className="size-[5px] rounded-full bg-current" />
      {nhanCua(TRANG_THAI, status)}
    </span>
  )
}
