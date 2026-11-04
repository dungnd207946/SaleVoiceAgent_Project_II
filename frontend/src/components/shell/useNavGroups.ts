/**
 * `NAV` đã lọc theo quyền — MỘT phép lọc cho cả ba chỗ đọc nav: rail, panel,
 * command palette.
 *
 * Trước đây phép lọc này nằm trong `Sidebar.tsx` vì chỉ có một chỗ đọc. Rail +
 * panel + palette là ba, và ba bản sao của cùng một luật quyền là ba chỗ để
 * lệch — palette lọt một màn mà rail đã ẩn thì đúng thứ việc ẩn kia định tránh
 * lại quay lại qua cửa sau.
 *
 * ⚠ ẨN NÚT KHÔNG PHẢI BẢO VỆ (PQ_01 §BR-Q03). Đây chỉ để người dùng không thấy
 * mục bấm vào là báo lỗi. Quyền thật kiểm ở tầng API bằng `require(action)`.
 *
 * Mảng mất hết mục thì mất luôn icon trên rail — một mảng mở ra rỗng trông như
 * lỗi.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { docLinhVuc } from '@/features/agent/contracts'
import { NAV } from '@/lib/nav-registry'
import { useSession } from '@/lib/session'
import type { NavGroup } from '@/lib/nav-types'

/**
 * Lọc theo HAI luật khác hẳn nhau, đừng gộp làm một khi đọc:
 *
 *   ① QUYỀN (`can`) — người này được THẤY mục nào. Ẩn nút không phải bảo vệ.
 *   ② LĨNH VỰC BẬT/TẮT — workspace này CÓ DÙNG lĩnh vực đó không. Không liên
 *      quan gì tới người đang đăng nhập; tắt là tắt với cả workspace, và nó
 *      còn cắt luôn kỹ năng của lĩnh vực khỏi payload gửi agent (xem
 *      `features/agent/linhVuc.ts`).
 *
 * Rồi tầng nào rỗng thì biến mất luôn: mục → khối → mảng. Khối rỗng phải rời đi
 * cùng NHÃN của nó — một nhãn «BẤT ĐỘNG SẢN» đứng trên khoảng trống nói với
 * người dùng rằng có thứ gì đó ở đó mà họ không thấy.
 *
 * Danh sách lĩnh vực CHƯA VỀ ⇒ coi như bật hết. Ngược lại thì mọi khối lĩnh vực
 * nháy mất rồi hiện lại ở mỗi lần tải trang — và một panel tự đổi hình sau khi
 * đã vẽ xong trông như lỗi, kể cả khi nó đang đúng.
 */
export function useNavGroups(): readonly NavGroup[] {
  const { can } = useSession()
  const linhVuc = useQuery({ queryKey: ['linh-vuc'], queryFn: docLinhVuc })
  const data = linhVuc.data

  return useMemo(() => {
    const tat = new Set((data ?? []).filter((l) => !l.bat).map((l) => l.ma))
    return NAV.map((g): NavGroup => ({
      ...g,
      segments: g.segments
        .filter((s) => s.linhVuc === undefined || !tat.has(s.linhVuc))
        .map((s) => ({ ...s, entries: s.entries.filter((e) => can(e.requiredActions)) }))
        .filter((s) => s.entries.length > 0),
    })).filter((g) => g.segments.length > 0)
  }, [can, data])
}
