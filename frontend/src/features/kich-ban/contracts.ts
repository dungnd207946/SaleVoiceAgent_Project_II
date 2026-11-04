/**
 * Mặt tiền công khai của module `kich-ban` — module khác chỉ được import tệp này
 * (`tests/module-boundaries.test.ts`).
 *
 * Người dùng đầu tiên: thẻ nút kịch bản dưới tin agent ở `/convos/$phone`
 * (`ops/TheNutKichBan`). Trước 2026-10-05 thẻ in mã thô `che_dat · b1` trong khi
 * `/kich-ban` in «Khách chê đắt» — cùng một tình huống, hai cách gọi.
 */
import { useMemo } from 'react'
import { useKichBan } from './api'
import { docDe, tenNut } from './logic'

export { docDe }

export interface TenKichBan {
  /** id nút → tên cho người đọc (`ten` agent xuất; vắng ⇒ id) — tham số `ten` của `docDe`. */
  readonly ten: Record<string, string>
  /** «bước N» theo thứ tự `buoc` của nút; không tìm thấy ⇒ `null` (mã bước trần không nói gì với người đọc). */
  readonly buoc: (nut: string, buocId: string) => string | null
}

/**
 * Đọc CHUNG cache `/playbook` 7 ngày của màn `/kich-ban` (cùng `queryKey`) — một
 * request cho mọi thẻ của phiên. Chưa tải xong hoặc không có quyền `agent_config.read`
 * (403) ⇒ bảng rỗng, người gọi rơi về mã như trước, không báo lỗi gì thêm.
 */
export function useTenKichBan(): TenKichBan {
  const { data } = useKichBan(7)
  return useMemo(() => {
    const nodes = data?.nodes ?? []
    return {
      ten: Object.fromEntries(nodes.map((n) => [n.id, tenNut(n)])),
      buoc: (nut, buocId) => {
        const i = nodes.find((n) => n.id === nut)?.buoc.findIndex((b) => b.id === buocId) ?? -1
        return i >= 0 ? `bước ${i + 1}` : null
      },
    }
  }, [data])
}
