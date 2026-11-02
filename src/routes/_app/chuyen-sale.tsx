import { createFileRoute, useLocation, useNavigate, useRouter } from '@tanstack/react-router'
import type { LocCa } from '@/features/ops/api'
import { HopThuSale } from '@/features/ops/components/HopThuSale'

/**
 * Màn «Chuyển sale». Bộ lọc · trang · ca đang mở đều ở search param — gửi link
 * cho đồng nghiệp thì họ mở đúng ca bạn đang xem.
 */
const TAB = ['new', 'contacted', 'done'] as const

declare module '@tanstack/history' {
  interface HistoryState {
    /** Mục lịch sử này sinh ra vì điện thoại mở một ca TỪ DANH SÁCH (push) — mục
     *  ngay trước nó là danh sách đó. */
    tuDs?: boolean
  }
}

export interface TimCa {
  q?: string | undefined
  tab?: (typeof TAB)[number] | undefined
  duAn?: string | undefined
  cu?: true | undefined
  trang?: number | undefined
  ca?: number | undefined
}

export const Route = createFileRoute('/_app/chuyen-sale')({
  validateSearch: (s: Record<string, unknown>): TimCa => ({
    q: typeof s.q === 'string' && s.q !== '' ? s.q : undefined,
    tab: TAB.includes(s.tab as (typeof TAB)[number]) ? (s.tab as (typeof TAB)[number]) : undefined,
    duAn: typeof s.duAn === 'string' && s.duAn !== '' ? s.duAn : undefined,
    cu: s.cu === true || s.cu === 'true' ? true : undefined,
    trang: Number(s.trang) > 1 ? Number(s.trang) : undefined,
    ca: Number(s.ca) > 0 ? Number(s.ca) : undefined,
  }),
  component: ManChuyenSale,
})

function ManChuyenSale() {
  const s = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const router = useRouter()
  const tuDs = useLocation({ select: (l) => l.state.tuDs === true })

  // `LocCa` khai các trường KHÔNG kèm `| undefined`, mà `exactOptionalPropertyTypes`
  // cấm gán tường minh `undefined` — nên trải có điều kiện, đừng gán thẳng.
  const loc: LocCa = {
    trangThai: s.tab ?? 'all',
    ...(s.q !== undefined ? { q: s.q } : {}),
    ...(s.duAn !== undefined ? { duAn: s.duAn } : {}),
    ...(s.cu ? { sapXep: 'cu' as const } : {}),
    ...(s.trang !== undefined ? { trang: s.trang } : {}),
  }

  return (
    <HopThuSale
      loc={loc}
      datLoc={(l) =>
        void navigate({
          search: {
            q: l.q || undefined,
            tab: l.trangThai === 'all' ? undefined : l.trangThai,
            duAn: l.duAn || undefined,
            cu: l.sapXep === 'cu' ? true : undefined,
            trang: (l.trang ?? 1) > 1 ? l.trang : undefined,
            // Đổi bộ lọc hay đổi trang thì bỏ ca đang mở: nó có thể không còn
            // trong tập vừa lọc, và trỏ vào một ca ngoài màn hình là nói dối.
            ca: undefined,
          },
          replace: true,
        })
      }
      caDangMo={s.ca}
      // Điện thoại: mở ca từ danh sách là PUSH — Back của trình duyệt/điện thoại (vuốt
      // iOS, nút Android) về lại danh sách thay vì rời cả màn; «‹ Danh sách» lùi đúng
      // mục đó chứ không ghi mục mới (ghi mới thì phải Back hai lần mới ra). Mở bằng
      // link `?ca=` thì không có mục danh sách nào phía sau ⇒ thay tại chỗ. Desktop
      // (hai cột) đổi hàng vẫn REPLACE: lịch sử không phình theo từng cú bấm hàng.
      moCa={(id, day) => {
        if (id === undefined && tuDs) {
          router.history.back()
          return
        }
        void navigate({
          search: { ...s, ca: id },
          replace: !day,
          ...(day ? { state: { tuDs: true } } : {}),
        })
      }}
    />
  )
}
