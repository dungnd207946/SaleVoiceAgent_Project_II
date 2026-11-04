/**
 * Màn `/billing` — khung: hàng chọn kỳ, dải cảnh báo, năm thẻ KPI (Task 4) +
 * bảng Explorer ba chiều gộp (Task 5, mục ③).
 *
 * BA MỤC, ĐÁNH SỐ LIỀN 1·2·3 (2026-08-21). Mục ② («Tiền đi đâu») từng bị CẮT
 * khỏi v1 vì không endpoint nào trả tách theo ngày/theo component — chỗ trống
 * đó là lý do hai mục còn lại mang số ① và ③. Nay BE đã có
 * `GET /billing/breakdown` (repo `odyssey-portal-backend`, `repo.theo_ngay()` +
 * `repo.theo_component()`), mục ② vào đúng khe đã chừa sẵn và số mục liền lại.
 * Quyết định GIỮ số ③ hồi Task 5 (thay vì dồn xuống ②) chính là thứ làm lần
 * chèn này không phải đánh số lại gì cả.
 *
 * KHUÔN GIỐNG `FeedbackList` (`features/quality`): component nhận state search
 * đã được xác thực (`tim`) + setter (`datTim`) làm props, TỰ gọi
 * `useTongQuan()` bên trong — route (`routes/_app/billing.tsx`) chỉ là một cầu
 * nối mỏng giữa `Route.useSearch()`/`useNavigate()` và hai prop này. Component
 * KHÔNG tự đọc `Route` của chính route đang render nó: import ngược từ
 * `features/billing/…` vào `routes/_app/billing.tsx` (nơi ĐANG import chính
 * component này) là một vòng phụ thuộc hai chiều — deferred tới lúc chạy thì
 * vẫn hoạt động (ESM live-binding), nhưng test muốn dựng `UsageScreen` độc lập
 * (khuôn `quality-list.test.tsx`) sẽ phải dựng nguyên `routeTree` thật cho một
 * việc lẽ ra chỉ cần props tự tay.
 *
 * `datTim` giờ mang thêm nghĩa PUSH/REPLACE (xem `routes/_app/billing.tsx`):
 * đổi MỘT MÌNH `trang` (phân trang chiều Phiên) ⇒ push, Back = trang trước;
 * mọi thay đổi khác (kỳ, chiều gộp — luôn kèm reset `trang: 1`) ⇒ replace.
 * `UsageScreen`/`BangLuotDung` không tự quyết điều đó, chỉ gọi đúng shape.
 */
import { useRef } from 'react'
import { LoiApi } from '@/lib/http'
import { useTongQuan } from '../api'
import { giaiMaKy, type TenKy } from '../ky'
import { ChonMot } from '@/components/ui/Bang'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { BangLuotDung } from './BangLuotDung'
import { ChiTietPhien } from './ChiTietPhien'
import { PhanTichChiPhi } from './PhanTichChiPhi'
import { SparklineChiPhi } from './SparklineChiPhi'
import { TheKpi } from './TheKpi'
import { TieuDeMuc } from './TieuDeMuc'

/** Bốn khoá search của `/billing` — `gop`/`trang` Task 5 dùng, `phien` Task 6. */
export interface UsageTim {
  ky: TenKy
  gop: 'khoa' | 'nguoi' | 'phien'
  trang: number
  phien?: string | undefined
}

const NHAN_KY: Record<TenKy, string> = {
  'thang-nay': 'Tháng này',
  'thang-truoc': 'Tháng trước',
  '7-ngay': '7 ngày',
  '30-ngay': '30 ngày',
}
const DS_KY: readonly TenKy[] = ['thang-nay', 'thang-truoc', '7-ngay', '30-ngay']

const pad = (n: number) => String(n).padStart(2, '0')

/** `iso` dạng `YYYY-MM-DD`. `voiNam` thêm `/YYYY` — dùng cho mốc cuối. */
function hienNgay(iso: string, voiNam: boolean): string {
  const [y, m, d] = iso.split('-')
  return voiNam ? `${pad(Number(d))}/${pad(Number(m))}/${y}` : `${pad(Number(d))}/${pad(Number(m))}`
}

/** `to` của `giaiMaKy()` là mốc NỬA MỞ (BE lọc `occurred_at < to`) — ngày hiện
 *  cho người dùng phải là ngày CUỐI CÙNG còn nằm trong kỳ, tức hôm trước `to`. */
function homTruoc(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

/** Hàng chọn kỳ + khoảng ngày THẬT (không phải nhãn kỳ suông) — luôn hiện,
 *  kể cả lúc đang tải/lỗi: người dùng có thể muốn đổi kỳ ngay lúc đó, không
 *  phải chờ dữ liệu cũ tải xong rồi mới thấy được nút. */
function HangKy({
  ky,
  datKy,
  from,
  to,
}: {
  readonly ky: TenKy
  readonly datKy: (k: TenKy) => void
  readonly from: string
  readonly to: string
}) {
  return (
    <div className="flex flex-none flex-wrap items-center justify-between gap-3">
      <ChonMot
        nhan="Chọn kỳ"
        muc={DS_KY.map((k) => ({ ma: k, nhan: NHAN_KY[k] }))}
        chon={ky}
        doi={datKy}
        className="max-md:w-full"
      />
      <p className="font-mono text-phu text-muted">
        {hienNgay(from, false)} – {hienNgay(homTruoc(to), true)}
      </p>
    </div>
  )
}

/** `q.isPending` — đúng hình 5 thẻ, KHÔNG spinner giữa màn (nút kỳ vẫn bấm
 *  được ngay trong lúc tải, xem `HangKy`). */
function KhungDangTai() {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="h-[92px] animate-pulse rounded-lg border border-border bg-fill" />
      ))}
    </div>
  )
}

export function UsageScreen({
  tim,
  datTim,
}: {
  readonly tim: UsageTim
  readonly datTim: (t: Partial<UsageTim>) => void
}) {
  const { from, to } = giaiMaKy(tim.ky)
  const q = useTongQuan(from, to)
  const datKy = (ky: TenKy) => datTim({ ky })

  // Phần tử đã MỞ slide-over (nút định danh của hàng Phiên, tận trong
  // `BangLuotDung.tsx`) — sống Ở ĐÂY vì UsageScreen là nơi cả hàng bảng lẫn
  // `ChiTietPhien` đều với tới được; khuôn `oKichHoatRef` của `LightboxAnh`
  // (xem docstring `ChiTietPhien.tsx`). Không phải state: đổi nó không cần
  // vẽ lại gì, chỉ cần còn sống tới lúc `dongPhien` chạy.
  const oKichHoatRef = useRef<HTMLElement | null>(null)

  function moPhien(sessionId: string, el: HTMLElement | null): void {
    oKichHoatRef.current = el
    datTim({ phien: sessionId })
  }

  /** Đóng qua CẢ BA đường (nút ×, click lớp phủ, Escape của `ChiTietPhien`) —
   *  cả ba gọi ĐÚNG hàm này, không có đường tắt nào chỉ ẩn component mà quên
   *  xoá search param. */
  function dongPhien(): void {
    datTim({ phien: undefined })
    oKichHoatRef.current?.focus()
  }

  if (q.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <HangKy ky={tim.ky} datKy={datKy} from={from} to={to} />
        <KhungDangTai />
      </div>
    )
  }

  if (q.error) {
    // 403 KHÔNG phải lỗi mạng — một nút «Thử lại» ở đó là nút vô nghĩa, xin
    // lại chính request vừa bị từ chối không đổi được gì.
    const khongCoQuyen = q.error instanceof LoiApi && q.error.code === 'FORBIDDEN'
    return (
      <div className="flex flex-col gap-4 p-6">
        <HangKy ky={tim.ky} datKy={datKy} from={from} to={to} />
        {khongCoQuyen ? (
          <div className="rounded-lg border border-border bg-surface p-6 text-center text-than text-muted">
            <p className="font-medium text-fg">Bạn không có quyền xem chi phí</p>
            <p className="mt-1">Liên hệ quản trị workspace này để được cấp quyền xem chi phí.</p>
          </div>
        ) : (
          <LoiTai viec="dữ liệu lượng dùng" thuLai={() => void q.refetch()} />
        )}
      </div>
    )
  }

  const data = q.data

  if (data.so_phien === 0) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <HangKy ky={tim.ky} datKy={datKy} from={from} to={to} />
        <KhoRong tieuDe="Chưa có lượt dùng nào" huongDan="Workspace này chưa ghi nhận usage nào" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <HangKy ky={tim.ky} datKy={datKy} from={from} to={to} />
      <TieuDeMuc so={1} tieuDe="Tổng quan" phu="Tổng các chỉ số chính của kỳ đang chọn" />
      <TheKpi data={data} hinhChiPhi={<SparklineChiPhi from={from} to={to} />} />
      <TieuDeMuc
        so={2}
        tieuDe="Chi phí"
        phu="Chi phí tương ứng với lượng usage đã sử dụng, quy đổi theo bảng giá"
      />
      <PhanTichChiPhi from={from} to={to} />
      <TieuDeMuc
        so={3}
        tieuDe="Lượt dùng chi tiết"
        phu="Gộp theo khoá, người tạo, hoặc từng phiên"
      />
      <BangLuotDung tim={tim} datTim={datTim} from={from} to={to} moPhien={moPhien} />
      {tim.phien && <ChiTietPhien sessionId={tim.phien} onDong={dongPhien} />}
    </div>
  )
}
