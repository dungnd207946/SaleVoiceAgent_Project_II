/**
 * Nav của `/quality` — un-defer 2026-08-12 (Task 9).
 *
 * Trước ở `features/deferred/nav.ts` cùng `finance`/`usage`/`billing`, vì màn
 * đợi một tiền đề chưa có: agent không thu feedback, không có cơ chế đánh giá
 * sau hội thoại (`docs/product/2026-07-28-phan-bien-prototype-va-dinh-huong-san-pham.md`
 * §3). Tiền đề đó giờ có (`POST/GET /agent/feedback`) nên nửa CSAT của màn ra
 * khỏi hoãn — nửa eval (bộ kiểm thử hồi quy) vẫn hoãn, xem `note` ở
 * `lib/screens.ts`.
 *
 * `requiredActions` đổi từ `ACTIONS.OVERVIEW_READ` (placeholder lúc màn chưa
 * có backend thật) sang `ACTIONS.CONVOS_READ` — đúng cổng quyền thật mà
 * backend chấm trên `GET /agent/feedback` (PQ_01 nhóm 2). Nav permissions chỉ
 * là cosmetic (BR-Q03: ẩn nút KHÔNG phải bảo vệ, cổng thật ở API), nhưng vẫn
 * phải nói đúng ai dùng được màn.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const qualityNav: NavLeaf = {
  kind: 'leaf',
  key: 'quality',
  path: '/quality',
  label: { vi: 'Chất lượng', en: 'Quality' },
  icon: 'quality',
  requiredActions: [ACTIONS.CONVOS_READ],
}
