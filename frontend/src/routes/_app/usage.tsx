import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { UsageLuongDungScreen, type UsageLuongTim } from '@/features/billing/contracts'

const DS_KY = ['thang-nay', 'thang-truoc', '7-ngay', '30-ngay'] as const
const DS_GOP = ['khoa', 'nguoi', 'phien'] as const
const DS_TAB = ['llm', 'stt', 'tts', 'vad', 'call', 'embed', 'speaker_verify'] as const

/**
 * Màn `/usage` — LƯỢNG DÙNG theo ngày, bảy tab một thứ đo.
 *
 * Không phải màn tiền: `/billing` là chỗ đó. Nội dung số liệu CHI PHÍ đã chuyển
 * sang `/billing` ngày 2026-08-24, và màn này được xây mới từ bản vẽ
 * `docs/design/demo-usage.html` + spec `2026-08-24-man-usage-bay-tab-design.md`.
 *
 * ⚠️ NĂM KHOÁ ('ky'/'tab'/'trang'/'gop'/'phien') LUÔN được `validateSearch` trả
 * đủ, kể cả khoá đang mang giá trị mặc định. Router TRỘN kết quả validate lên
 * search thô chứ không THAY nó, nên bỏ một khoá ra khỏi object trả về (`{}` cho
 * mặc định) để giá trị lạ trên URL lọt thẳng xuống component nguyên văn —
 * `?tab=xyz` sẽ làm KHÔNG TAB NÀO mở. Bẫy này đã sập thật ở `/projects`
 * (CLAUDE.md, Change Log 2026-08-14) và ở `/billing`.
 *
 * ⚠️ `DS_TAB` là bản SAO của `MA_TAB` (`features/billing/so-tab-usage.ts`), cố ý
 * viết tay: route không được import ruột feature (Luật 3 — `contracts.ts` là mặt
 * tiền, và bảy mã này không đáng mở một cửa mới ở đó). Thêm một component thì
 * thêm mã ở CẢ HAI chỗ — bài test `?tab=` lạ ở `tests/usage-luong-dung.test.tsx`
 * đỏ nếu hai danh sách lệch nhau.
 */
export const Route = createFileRoute('/_app/usage')({
  validateSearch: (s: Record<string, unknown>): UsageLuongTim => ({
    ky: (DS_KY as readonly string[]).includes(String(s.ky))
      ? (String(s.ky) as UsageLuongTim['ky'])
      : 'thang-nay',
    tab: (DS_TAB as readonly string[]).includes(String(s.tab)) ? String(s.tab) : 'llm',
    trang:
      Number.isFinite(Number(s.trang)) && Number(s.trang) >= 0 ? Math.floor(Number(s.trang)) : 0,
    gop: (DS_GOP as readonly string[]).includes(String(s.gop))
      ? (String(s.gop) as UsageLuongTim['gop'])
      : 'khoa',
    phien: typeof s.phien === 'string' && s.phien ? s.phien : undefined,
  }),
  component: ManUsage,
})

/** Cầu nối mỏng giữa router và `UsageLuongDungScreen` — component đó là THUẦN,
 *  nhận `tim`/`datTim` qua prop và không tự đọc `Route`. */
function ManUsage() {
  const tim = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  return (
    <UsageLuongDungScreen
      tim={tim}
      datTim={(t) =>
        void navigate({
          search: (truoc) => ({ ...truoc, ...t }),
          // Đổi TRANG một mình ⇒ PUSH, để Back của trình duyệt là "trang
          // trước" — cùng lối `quality.tsx`/`billing.tsx`. Mọi thay đổi khác
          // (kỳ, tab, chiều gộp, mở/đóng slide-over) ⇒ REPLACE: đừng chồng một
          // nhịp Back cho mỗi lượt bấm tab.
          replace: !(Object.keys(t).length === 1 && 'trang' in t),
        })
      }
    />
  )
}
