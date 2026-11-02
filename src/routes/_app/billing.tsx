import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { UsageScreen, type UsageTim } from '@/features/billing/contracts'

const DS_KY = ['thang-nay', 'thang-truoc', '7-ngay', '30-ngay'] as const
const DS_GOP = ['khoa', 'nguoi', 'phien'] as const

/**
 * Màn `billing` — SỐ TIỀN & CHI PHÍ. Nội dung này CHUYỂN TỪ `/usage` sang
 * (người dùng chốt 2026-08-24): `billing` là chỗ đúng nghĩa để xem tiêu bao
 * nhiêu tiền, và `/usage` sẽ được xây lại từ đầu cho một mục đích khác.
 * Chuyển chỗ THUẦN vị trí — không một dòng logic, UI hay lời gọi API nào đổi:
 * `UsageScreen` là component thuần nhận `tim`/`datTim` qua prop nên route chỉ
 * là cầu nối, và cả feature vốn đã nằm ở `features/billing/`.
 *
 * HOÁ ĐƠN KHÔNG Ở ĐÂY. Portal chưa thiết kế phần hoá đơn; khi có endpoint
 * `GET /billing/invoices` thì nó là MỘT MÀN KHÁC (người dùng chốt 2026-08-24),
 * không phải một tab nhồi vào đây. Đừng "tiện tay" mở rộng `UsageTim` cho hoá
 * đơn — bốn khoá dưới đây thuộc bảng lượt dùng, trộn hai miền vào một chữ ký
 * search là đúng cái lỗi `screens.ts` đã tách ra làm hai màn từ 2026-08-09.
 *
 * ⚠️ BỐN KHOÁ ('ky'/'gop'/'trang'/'phien') LUÔN được `validateSearch` trả đủ:
 * router TRỘN kết quả validate lên search thô chứ không THAY nó, nên bỏ một
 * khoá ra khỏi object trả về (`{}` cho mặc định) để giá trị lạ trên URL lọt
 * thẳng xuống component nguyên văn, không chiều nào mở được. Bẫy này đã sập
 * thật ở `/projects` (CLAUDE.md, Change Log 2026-08-14).
 */
export const Route = createFileRoute('/_app/billing')({
  validateSearch: (s: Record<string, unknown>): UsageTim => ({
    ky: (DS_KY as readonly string[]).includes(String(s.ky))
      ? (String(s.ky) as UsageTim['ky'])
      : 'thang-nay',
    gop: (DS_GOP as readonly string[]).includes(String(s.gop))
      ? (String(s.gop) as UsageTim['gop'])
      : 'khoa',
    trang:
      Number.isFinite(Number(s.trang)) && Number(s.trang) > 0 ? Math.floor(Number(s.trang)) : 1,
    phien: typeof s.phien === 'string' && s.phien ? s.phien : undefined,
  }),
  component: ManBilling,
})

/** Cầu nối mỏng giữa router và `UsageScreen` — xem docstring đầu
 *  `features/billing/components/UsageScreen.tsx` vì sao logic không nằm ở
 *  chiều ngược lại (component tự đọc `Route` của chính route render nó). */
function ManBilling() {
  const tim = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  return (
    <UsageScreen
      tim={tim}
      datTim={(t) =>
        void navigate({
          search: (truoc) => ({ ...truoc, ...t }),
          // Đổi TRANG MỘT MÌNH (nút «Trang sau →» của chiều Phiên, Task 5) ⇒
          // PUSH, để Back của trình duyệt là "trang trước" — cùng lối
          // `quality.tsx` (`replace: l.beforeId === undefined`). Mọi thay đổi
          // khác (kỳ, chiều gộp — chiều gộp luôn kèm reset `trang: 1` nên rơi
          // vào nhánh này) ⇒ REPLACE, đừng chồng Back cho mỗi lượt bấm tab/kỳ.
          replace: !(Object.keys(t).length === 1 && 'trang' in t),
        })
      }
    />
  )
}
