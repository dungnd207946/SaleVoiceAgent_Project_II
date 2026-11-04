/**
 * Avatar khách — DÙNG CHUNG giữa `KhachRow.tsx` (danh sách) và `PhienKhach.tsx`
 * (chi tiết một khách). Trước đây mỗi nơi tự tính lấy nên cùng một khách có
 * thể hiện hai avatar khác nhau giữa hai màn — tách ra một chỗ để không lệch.
 */
import type { ReactNode } from 'react'
import { chuCai } from '@/lib/chuCai'

/**
 * Màu avatar chọn TẤT ĐỊNH từ phone: cùng số ⇒ cùng màu qua mọi lần tải.
 * Bốn token `av1`..`av4` khai ở `src/styles/theme.css` — KHÔNG viết mã hex ở
 * đây, mọi mã màu của portal sống trong một tệp.
 */
const MAU = [
  'bg-av1-bg text-av1-fg',
  'bg-av2-bg text-av2-fg',
  'bg-av3-bg text-av3-fg',
  'bg-av4-bg text-av4-fg',
] as const

export function mauCua(phone: string): string {
  let n = 0
  for (const c of phone) n = (n + c.charCodeAt(0)) % MAU.length
  return MAU[n] ?? MAU[0]
}

/**
 * Chữ cái của tên; CHƯA CÓ TÊN (kể cả nhóm «Chưa có số») thì trả icon người
 * trung tính THAY vì đoán một chữ cái không có căn cứ. `currentColor` ăn theo
 * màu chữ (`text-*`) mà `mauCua`/màu xám trung tính đã đặt trên `<span>` cha,
 * nên không cần khai thêm class màu riêng cho icon. Vẽ THẲNG ở đây (không tách
 * component riêng) để file này chỉ export hàm, không export component — tránh
 * cảnh báo `react-refresh/only-export-components`.
 *
 * ⚠ THAM SỐ `avatar` ĐÃ BỎ (2026-08-25, đảo chốt 2026-08-21): khách không «set»
 * avatar nên ảnh DiceBear backend trả kèm là thừa — lịch sử hội thoại vẽ chữ
 * cái mặc định như bảng Thành viên. Backend VẪN trả trường `avatar` trên
 * `Khach`/`Phien`/`Ca` (hợp đồng không đổi), FE chỉ thôi đọc — đừng nối lại
 * `<img>` ở đây khi thấy trường đó «thừa»; đó là quyết định, không phải sót.
 */
export function noiDungAvatar(ten: string | null): ReactNode {
  if (ten) return chuCai(ten)
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-[52%]"
      aria-hidden="true"
    >
      <circle cx="12" cy="8" r="3.6" />
      <path d="M4.5 20c0-4.2 3.8-6.4 7.5-6.4s7.5 2.2 7.5 6.4" />
    </svg>
  )
}
