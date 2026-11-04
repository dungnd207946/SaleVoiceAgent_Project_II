/**
 * Màn `/usage` — LƯỢNG DÙNG theo ngày. Hai thẻ, không mục đánh số.
 *
 *   ① bảng điều khiển: RAIL bảy chỉ số (dọc, trái) × BIỂU ĐỒ (phải)
 *   ② bảng «Lượt dùng chi tiết», ba chiều gộp
 *
 * ⚠️ MÀN NÀY KHÔNG HIỆN MỘT ĐỒNG NÀO. Không `₫`, không phần trăm chi phí, không
 * dải cảnh báo `thieu_gia` (đó là cảnh báo ĐỊNH GIÁ, thuộc `/billing`). Đây
 * không phải để cho gọn — nó là điều kiện để màn này được phép bày các số đo mà
 * `/billing` không được phép cộng lại.
 *
 * ⚠️ ĐỪNG lấy khuôn từ `UsageScreen.tsx` (nay thuộc `/billing`). Sáu thứ đã bị
 * bỏ có chủ ý qua sáu vòng thiết kế, người dùng chốt: khuôn «bốn mục đánh số»
 * (`TieuDeMuc` + ô số ①②③④) · dải KPI ngang (`TheKpi`) · small multiples / biểu
 * đồ gộp nhiều đường · bảng «Cường độ theo service» · mọi dòng chữ giải thích
 * dưới tiêu đề · dải cảnh báo giá.
 *
 * Component THUẦN: nhận `tim`/`datTim` qua prop, không tự đọc `Route`. Route là
 * cầu nối mỏng — xem `routes/_app/usage.tsx`.
 */
import { ChonMot } from '@/components/ui/Bang'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { usePhien, useTheoKey, useTheoOwner, useUsageTheoNgay } from '../api'
import { chuoiCuaTab, duLieuNgoai, sttHaiVe, tokenTachLoai } from '../chuoi-usage'
import { MA_TAB, NHAN_DON_VI, TAB_USAGE, timTab } from '../so-tab-usage'
import { giaiMaKy, type TenKy } from '../ky'
import { giay, token } from '../dinh-dang'
import { bienMau, bienMauPhu } from '../truc-usage'
import type { ChuoiTab } from '../chuoi-usage'
import { BangLuotDungUsage, type ChieuGop } from './BangLuotDungUsage'
import { BieuDoLuongDung } from './BieuDoLuongDung'
import { ChiTietPhien } from './ChiTietPhien'
import { RailUsage } from './RailUsage'

/** Bốn khoá search của `/usage`. Xem `routes/_app/usage.tsx` về việc
 *  `validateSearch` phải LUÔN trả đủ cả bốn. */
export interface UsageLuongTim {
  readonly ky: TenKy
  readonly tab: string
  readonly trang: number
  readonly gop: ChieuGop
  readonly phien: string | undefined
}

const SO_MOI_TRANG = 50

const DS_KY: readonly { readonly ma: TenKy; readonly nhan: string }[] = [
  { ma: 'thang-nay', nhan: 'Tháng này' },
  { ma: 'thang-truoc', nhan: 'Tháng trước' },
  { ma: '7-ngay', nhan: '7 ngày' },
  { ma: '30-ngay', nhan: '30 ngày' },
]

/**
 * ⚠️ KHÔNG có prop `co`/`coBieuDo` để ghi đè phép đo khung biểu đồ, và đó là chủ
 * ý: màn này luôn được dựng qua ROUTER (`routes/_app/usage.tsx`), nên một seam ở
 * đây không có đường nào truyền tới — nó sẽ là prop chết. Hình học của biểu đồ
 * kiểm ở tầng COMPONENT (`BieuDoLuongDung` có prop `co`, cùng khuôn
 * `BieuDoChiPhi`/`BieuDoNgay`); tầng màn kiểm HÀNH VI, thứ không cần
 * `ResizeObserver` bắn.
 */
export function UsageLuongDungScreen({
  tim,
  datTim,
}: {
  readonly tim: UsageLuongTim
  readonly datTim: (t: Partial<UsageLuongTim>) => void
}) {
  const { from, to } = giaiMaKy(tim.ky)
  const q = useUsageTheoNgay(from, to)

  return (
    <div className="flex flex-col gap-4 px-7 pt-[22px] pb-15 max-md:px-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ChonMot
          nhan="Chọn kỳ"
          muc={DS_KY}
          chon={tim.ky}
          doi={(ky) => datTim({ ky, trang: 0 })}
          className="max-md:w-full"
        />
        <span className="font-mono text-phu text-muted-2">{khoangDoc(from, to)}</span>
      </div>

      {q.isError ? (
        <LoiTai viec="lượng dùng theo ngày" thuLai={() => void q.refetch()} />
      ) : (
        <BangDieuKhien
          theoNgay={q.data?.theo_ngay ?? []}
          dangTai={q.isPending}
          tab={tim.tab}
          datTab={(tab) => datTim({ tab })}
        />
      )}

      <BangChiTiet tim={tim} datTim={datTim} from={from} to={to} />

      {tim.phien ? (
        <ChiTietPhien sessionId={tim.phien} onDong={() => datTim({ phien: undefined })} />
      ) : null}
    </div>
  )
}

/**
 * Thẻ ①. Chuỗi của CẢ BẢY tab dẫn xuất một lần từ cùng một response — đổi tab
 * KHÔNG gọi lại API và cũng không tính lại sáu tab kia khỏi màn.
 */
function BangDieuKhien({
  theoNgay,
  dangTai,
  tab,
  datTab,
}: {
  readonly theoNgay: Parameters<typeof chuoiCuaTab>[0]
  readonly dangTai: boolean
  readonly tab: string
  readonly datTab: (ma: string) => void
}) {
  const chuoi: Record<string, ChuoiTab> = {}
  for (const t of TAB_USAGE) chuoi[t.ma] = chuoiCuaTab(theoNgay, t.ma)
  const dangXem = chuoi[tab] ?? chuoi[MA_TAB[0]!]!
  const tk = tokenTachLoai(theoNgay)
  const stt = sttHaiVe(theoNgay)
  const dln = duLieuNgoai(theoNgay)
  const dinhDangTab = timTab(dangXem.ma)
  const d2 = dinhDangTab.duong2

  return (
    <section className="grid grid-cols-1 overflow-hidden rounded-lg border border-border bg-surface lg:grid-cols-[274px_minmax(0,1fr)]">
      <RailUsage
        chuoi={chuoi}
        dangChon={dangXem.ma}
        datTab={datTab}
        phuThem={{
          llm: [`in ${token(tk.input)}`, `out ${token(tk.output)}`, `cache ${token(tk.cache)}`],
          /* Hai vế của STT, NHÃN LÀ CHÍNH GIÁ TRỊ `purpose` trong
             `billing.usage_events` (người dùng chốt 2026-08-25) — không dịch
             sang tiếng Việt: người đọc dòng này đang đối chiếu với bảng giá,
             và ở đó hai nhãn viết đúng như vậy. Đây là tab DUY NHẤT không chở
             `TB …/ngày`: hai đồng hồ vendor thu song song thì một con số trung
             bình gộp cả hai là con số không tồn tại. */
          stt: [`stream ${giay(stt.streamGiay)}`, `conversation ${token(stt.hoiThoaiKyTu)}`],
        }}
        themPhu={{
          ...(dln.token > 0 ? { llm: [`gồm ${token(dln.token)} dữ liệu ngoài`] } : {}),
          ...(dln.kyTu > 0 ? { embed: [`gồm ${token(dln.kyTu)} dữ liệu ngoài`] } : {}),
        }}
      />
      <div className="flex min-w-0 flex-col px-[18px] pt-[14px] pb-[10px]">
        <div className="flex min-h-[26px] flex-wrap items-baseline gap-3">
          <h2 className="m-0 text-the font-semibold tracking-[-0.01em]">
            {dinhDangTab.nhan} theo ngày
          </h2>
          {/* Tab một đường: một chip đơn vị trần, như cũ. Tab HAI đường: chú
              giải có ô mẫu.
              Hai thứ trả lời hai câu KHÁC nhau, đừng bỏ cái nào: nhãn dọc trên
              mỗi trục nói trục ĐO CÁI GÌ, chú giải nói ĐƯỜNG NÀO thuộc trục
              nào. Buộc đường vào trục bằng cách tô màu nhãn trục thì không được
              — `--a`/`--d2` chỉ đạt 3.25–3.85, dưới ngưỡng 4.5 của WCAG cho
              CHỮ ở cỡ 10px. */}
          {d2 ? (
            <span
              className="flex flex-wrap items-center gap-x-[13px] gap-y-1"
              style={{ ...bienMau(dangXem.ma), ...bienMauPhu(dangXem.ma) }}
              data-chu-giai
            >
              <MucChuGiai nhan={`${d2.nhanChinh} · ${NHAN_DON_VI[dinhDangTab.donVi]}`} />
              <MucChuGiai nhan={`${d2.nhan} · ${NHAN_DON_VI[d2.donVi]}`} phu />
            </span>
          ) : (
            <span className="font-mono text-nhan text-muted-2">
              đơn vị {NHAN_DON_VI[dinhDangTab.donVi]}
            </span>
          )}
        </div>
        {dangTai ? (
          <div className="mt-2 min-h-[260px] flex-1 animate-pulse rounded-md bg-fill" />
        ) : theoNgay.length === 0 ? (
          <KhoRong
            tieuDe="Chưa có lượt dùng nào trong kỳ này"
            huongDan="Agent chạy rồi thì số đo hiện ở đây, tách theo từng service."
          />
        ) : (
          <BieuDoLuongDung chuoi={dangXem} />
        )}
      </div>
    </section>
  )
}

/**
 * Thẻ ②. Ba hook chạy CẢ BA, không gate theo chiều đang mở — cùng lối
 * `BangLuotDung` của `/billing` (nó cũng gọi cả ba). Đổi chiều gộp là một cú
 * bấm tab, và ba chiều là ba câu hỏi về CÙNG một kỳ: tải sẵn thì đổi tab hiện
 * ngay, gate lại thì mỗi lần bấm là một lần skeleton cho dữ liệu vốn nhỏ (hai
 * chiều đầu gộp về vài hàng).
 *
 * `q` là hook của chiều đang mở — chỉ dùng để chọn ĐÚNG lỗi cần báo. Báo lỗi
 * của một chiều người dùng không xem là báo một sự cố họ không thấy.
 */
function BangChiTiet({
  tim,
  datTim,
  from,
  to,
}: {
  readonly tim: UsageLuongTim
  readonly datTim: (t: Partial<UsageLuongTim>) => void
  readonly from: string
  readonly to: string
}) {
  const khoa = useTheoKey(from, to)
  const nguoi = useTheoOwner(from, to)
  const phien = usePhien(from, to, SO_MOI_TRANG, tim.trang * SO_MOI_TRANG)
  const q = tim.gop === 'khoa' ? khoa : tim.gop === 'nguoi' ? nguoi : phien

  if (q.isError) {
    return <LoiTai viec="bảng lượt dùng chi tiết" thuLai={() => void q.refetch()} />
  }
  return (
    <BangLuotDungUsage
      chieu={tim.gop}
      datChieu={(gop) => datTim({ gop, trang: 0 })}
      khoa={khoa.data}
      nguoi={nguoi.data}
      phien={phien.data}
      trang={tim.trang}
      datTrang={(trang) => datTim({ trang })}
      moPhien={(phienId) => datTim({ phien: phienId })}
      soMoiTrang={SO_MOI_TRANG}
    />
  )
}

/** `2026-08-01`/`2026-09-01` → `01/08 – 31/08/2026`. `to` là cận trên MỞ nên
 *  ngày hiện ra phải trừ một — hiện `01/09` là nói kỳ dài hơn một ngày. */
function khoangDoc(from: string, to: string): string {
  const t = new Date(`${to}T00:00:00Z`)
  t.setUTCDate(t.getUTCDate() - 1)
  const cuoi = t.toISOString().slice(0, 10)
  return `${from.slice(8)}/${from.slice(5, 7)} – ${cuoi.slice(8)}/${cuoi.slice(5, 7)}/${cuoi.slice(0, 4)}`
}

/**
 * Một mục chú giải của biểu đồ hai đường. `phu` vẽ ô mẫu bằng màu của ĐƯỜNG 2.
 *
 * Cùng khuôn ô mẫu với tooltip (`DongTip`) — hai chỗ vẽ cùng một vật thì phải
 * cùng một hình, lệch nhau là chú giải trỏ nhầm đường.
 *
 * ⚠️ Chú giải này KHÔNG thừa dù mỗi trục đã có nhãn đơn vị: nhãn trục nói trục
 * ĐO CÁI GÌ, chú giải nói ĐƯỜNG NÀO thuộc trục nào. Bỏ nó thì hai đường màu
 * khác nhau không còn tên, và người đọc phải đoán đường nào ứng với trục nào.
 */
function MucChuGiai({ nhan, phu }: { readonly nhan: string; readonly phu?: boolean }) {
  return (
    <span className="flex items-center gap-[6px] font-mono text-nhan text-muted-2">
      <i
        aria-hidden
        className="h-[3px] w-[14px] flex-none rounded-sm"
        style={{
          background: phu
            ? 'linear-gradient(90deg,var(--d),var(--d2))'
            : 'linear-gradient(90deg,var(--c),var(--a))',
        }}
      />
      {nhan}
    </span>
  )
}
