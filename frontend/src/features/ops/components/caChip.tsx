/**
 * Chip dùng chung giữa hàng danh sách và khối chi tiết.
 *
 * `NhanKyNang` đi qua `nhanCua()` — AG_01 §II.3: không bao giờ hiện tên hàm cho
 * người dùng. Sale đọc «Tìm căn theo tiêu chí», không đọc `search_units`.
 */
import { nhanCua } from '@/lib/tools'
import type { Ca } from '../api'

export function NhanKyNang({ ten }: { ten: string | null }) {
  if (!ten) return null
  return (
    // Chip chỉ in tên kỹ năng — nghĩa «agent bí dữ liệu ở đây» đi qua `title` (rê
    // chuột) và chữ sr-only, để hàng danh sách không dài thêm một cụm chữ.
    <span
      title="Agent thiếu dữ liệu ở kỹ năng này"
      className="rounded-full bg-badge-warn-bg px-2 py-[3px] text-[11.5px] font-medium text-badge-warn-fg"
    >
      <span className="sr-only">Thiếu dữ liệu: </span>
      {nhanCua(ten)}
    </span>
  )
}

/** `null` ở tab «Chưa liên hệ» — chip «Chưa liên hệ» trên mọi hàng là nhiễu. */
export function TrangThaiCa({ ca }: { ca: Ca }) {
  if (ca.trangThai === 'new') return null
  // Không biết ai thì hiện mỗi trạng thái. «Ai đó»/«—» là bịa một người không có.
  const chu =
    ca.trangThai === 'contacted'
      ? ca.nguoiXuLy
        ? `${ca.nguoiXuLy} đang xử lý`
        : 'Đang xử lý'
      : ca.nguoiXuLy
        ? `Xong · ${ca.nguoiXuLy}`
        : 'Xong'
  return (
    <span className="rounded-full bg-acs px-2 py-[3px] text-[11.5px] font-medium text-acd">
      {chu}
    </span>
  )
}

/** Bản tóm tắt còn tạm — `summaryLuc === null` là tín hiệu DUY NHẤT phân biệt. */
export function ChipDangTomTat() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-badge-neutral-bg px-2 py-[3px] text-[11.5px] font-medium text-badge-neutral-fg">
      <span className="size-1.5 rounded-full bg-badge-neutral-fg" />
      Đang tóm tắt
    </span>
  )
}
