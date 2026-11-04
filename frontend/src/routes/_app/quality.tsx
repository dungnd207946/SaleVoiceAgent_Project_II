import { createFileRoute, useNavigate } from '@tanstack/react-router'
import type { LocFeedback } from '@/features/quality/api'
import { FeedbackList } from '@/features/quality/components/FeedbackList'

/**
 * Màn `/quality` (phần CSAT) — bộ lọc nằm ở SEARCH PARAM, cùng lý do
 * `convos.index.tsx`: F5 hoặc gửi link cho đồng nghiệp vẫn ra đúng bộ lọc
 * đang xem.
 */
export interface TimKiem {
  rating?: readonly number[] | undefined
  beforeId?: number | undefined
}

export const Route = createFileRoute('/_app/quality')({
  validateSearch: (s: Record<string, unknown>): TimKiem => ({
    rating: Array.isArray(s.rating) ? s.rating.map(Number) : undefined,
    beforeId: typeof s.beforeId === 'number' ? s.beforeId : undefined,
  }),
  component: ManChatLuong,
})

function ManChatLuong() {
  const s = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  // `LocFeedback` (Task 4, `api.ts`) khai `ratings?`/`beforeId?` KHÔNG kèm
  // `| undefined` — `exactOptionalPropertyTypes` cấm gán tường minh
  // `undefined` vào đó, nên trải object có điều kiện thay vì gán thẳng.
  const loc: LocFeedback = {
    ...(s.rating !== undefined ? { ratings: s.rating } : {}),
    ...(s.beforeId !== undefined ? { beforeId: s.beforeId } : {}),
  }

  return (
    <FeedbackList
      loc={loc}
      datLoc={(l) =>
        void navigate({
          search: { rating: l.ratings, beforeId: l.beforeId },
          // `datLoc` gánh cả hai việc: đổi bộ lọc VÀ đổi trang (Finding 3/5).
          // Tín hiệu rẻ nhất để phân biệt hai ca đó là chính `l.beforeId` —
          // `FeedbackList` CHỈ đặt field này lúc bấm "Trang sau →"
          // (`boLoc()`, Finding 1, luôn bỏ nó khi đổi lọc). Đổi lọc ⇒
          // `replace` (đừng chồng 5 lần Back cho 5 lượt bấm chip, cùng lý do
          // `convos.index.tsx`); đổi trang ⇒ push, để Back = "trang trước".
          replace: l.beforeId === undefined,
        })
      }
    />
  )
}
