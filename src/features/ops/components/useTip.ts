/**
 * Hook quản lý vị trí tooltip — tách khỏi `Tip.tsx` (2026-08-14) vì
 * `react-refresh/only-export-components` (`--max-warnings 0` ở `make lint`)
 * không cho một file export vừa component vừa một hook: fast refresh chỉ
 * theo dõi đúng được file thuần component. Cùng lý do `features/agent/
 * useBanNhap.ts` đứng riêng khỏi `KhungSuaAgent.tsx`.
 */
import { useState } from 'react'

/** Vị trí + đối tượng mà tooltip đang nói về. `null` = không hiện. `i` là chỉ
 *  số phần tử (ngày, hàng, …) trong danh sách của người gọi — hook này không
 *  biết ý nghĩa của nó, chỉ giữ hộ. */
export interface ViTriTip {
  readonly i: number
  /** Toạ độ VIEWPORT (`clientX`/`clientY`), vì tooltip là `position: fixed`. */
  readonly x: number
  readonly y: number
}

/**
 * Quản lý state vị trí tooltip cho MỘT vùng tương tác (khung biểu đồ, một
 * hàng, …). Hai cách mở khớp hai cách với tới: chuột (toạ độ từ sự kiện) và
 * bàn phím (`tiêu điểm` — neo vào tâm mép trên của phần tử đang focus, vì
 * lúc đó không có toạ độ con trỏ nào để dùng).
 */
export function useTip() {
  const [tip, setTip] = useState<ViTriTip | null>(null)
  return {
    tip,
    /** Mở tại toạ độ con trỏ chuột hiện tại. */
    taiChuot: (i: number, e: { readonly clientX: number; readonly clientY: number }) =>
      setTip({ i, x: e.clientX, y: e.clientY }),
    /** Mở khi một phần tử NHẬN tiêu điểm bàn phím — neo vào tâm mép trên. */
    taiTieuDiem: (i: number, el: Element) => {
      const b = el.getBoundingClientRect()
      setTip({ i, x: b.left + b.width / 2, y: b.top })
    },
    an: () => setTip(null),
  }
}
