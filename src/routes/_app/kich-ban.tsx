import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'

// Màn lazy-load — bản đồ kịch bản không vào bundle các màn khác.
const KichBanScreen = lazy(() =>
  import('@/features/kich-ban/components/KichBanScreen').then((m) => ({
    default: m.KichBanScreen,
  })),
)

export interface TimKiemKichBan {
  nut?: string | undefined
  ngay?: 7 | 30 | 90 | undefined
  nguon?: string | undefined
  q?: string | undefined
  /** `mau` = khung chi tiết hiện «So với mẫu» (đợt 3). */
  so?: 'mau' | undefined
  /** Khung chi tiết hiện form thêm tình huống. */
  them?: true | undefined
}

const str = (v: unknown) => (typeof v === 'string' && v ? v : undefined)

export const Route = createFileRoute('/_app/kich-ban')({
  validateSearch: (s: Record<string, unknown>): TimKiemKichBan => ({
    nut: str(s.nut),
    ngay: s.ngay === 30 || s.ngay === 90 || s.ngay === 7 ? s.ngay : undefined,
    nguon: str(s.nguon),
    q: str(s.q),
    so: s.so === 'mau' ? 'mau' : undefined,
    // Gõ tay `?them=1` về thành SỐ, `<Link search={{them:true}}>` về thành boolean — nhận cả bốn dạng
    // (bẫy `?nap=1` của `/projects`, CLAUDE.md).
    them: s.them === 1 || s.them === '1' || s.them === true || s.them === 'true' ? true : undefined,
  }),
  component: () => (
    <Suspense fallback={<p className="p-6 text-muted-3">Đang tải…</p>}>
      <KichBanScreen />
    </Suspense>
  ),
})
