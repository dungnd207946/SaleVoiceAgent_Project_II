/**
 * Ô ③ màn Tổng quan — điểm hài lòng cuối phiên + phân bố 5 sao.
 * Khuôn PORT từ `docs/design/demo-tong-quan.html` § "KHÁCH ĐÁNH GIÁ" (bản đã
 * duyệt), cùng họ với `FeedbackTongQuan.tsx` của `/quality`.
 *
 * `Sao` IMPORT thẳng từ `components/ui/Sao` — KHÔNG chép lại. Component đó
 * đã dùng ở `/quality` và `PhienKhach.tsx`; thêm bản thứ ba là ba chỗ phải
 * sửa mỗi lần đổi hình ngôi sao.
 *
 * KHÔNG làm tròn `trungBinh` khi vẽ sao: `Sao` tô một phần ngôi cuối theo
 * đúng số lẻ (`data-sao="phan"` + `data-phan="<%>"`) — làm tròn ở đây là vẽ
 * lệch tới nửa sao so với con số in ngay trên nó.
 *
 * `truoc === null` nghĩa là kỳ trước chưa có lượt đánh giá nào (backend cố ý
 * trả `null` chứ không phải `0`) ⇒ KHÔNG vẽ mũi tên delta — so với một kỳ
 * chưa từng có số là bịa.
 *
 * `tong === 0` (spec §4.4) — KHÔNG hiện `0,00 / 5`. Backend giữ phân biệt
 * `null` vs `0` ở `truoc` chính vì lớp lỗi này; ép nó về `0,00` ở tầng vẽ là
 * dựng lại đúng lời nói dối đó ở chỗ khác: tenant vừa bật agent sẽ đọc ra
 * «khách chấm agent 0 điểm», trong khi sự thật là chưa ai chấm. Trường
 * `trungBinh` vẫn về `0.0` từ backend (`or 0.0` ở `router.py`, để thang 0→5
 * luôn vẽ được) — nên `tong` là biến DUY NHẤT phân biệt được hai ca này.
 *
 * TOOLTIP mỗi hàng sao (round fix 2026-08-14) — bản đầu đánh rơi hẳn, trong
 * khi demo có (`gan(n, ...)` ở cuối khối ③). Nội dung PORT nguyên: tiêu đề
 * «N sao» + «Lượt» + «Tỉ lệ». Dùng khung `HopTip`/`useTip` chung (`./Tip.tsx`)
 * như ô ① và ô ⑤ — ô này là người dùng thứ BA.
 *
 * NĂM HÀNG THÀNH `<Link to="/quality" search={{rating:[n]}}>`, cùng lý lẽ đã
 * ghi ở `TheKienThuc.tsx`: ô cha (`ODanhGia`) mang stretched-link phủ trọn ô,
 * nên hàng phải `relative z-10` mới nhận được `mousemove` — mà nâng z-index
 * cho một hàng rồi không cho nó điều hướng thì bấm vào hàng KHÔNG có gì xảy
 * ra trong khi bấm chỗ khác của ô lại đi. Ở đây link còn CHỞ THÊM bộ lọc:
 * bấm hàng «1★» ra thẳng `/quality?rating=1`, tức đúng câu hỏi người ta vừa
 * nhìn thấy con số («bốn phiếu 1 sao là phiếu nào?»).
 *
 * Tooltip ở ô này CHỈ mở bằng chuột — KHÔNG thêm đường bàn phím như ô ①/⑤, và
 * đó là chủ ý: ở hai ô kia phần tử vốn ĐÃ là control thật (nút nhãn ngày,
 * link hàng kho) nên tiêu điểm là thứ có sẵn, còn giá trị tooltip mang («Tỉ
 * lệ») thì không hiện ở đâu khác. Ở đây «Lượt» đã in ngay trong hàng, chỉ còn
 * «Tỉ lệ» là mới — và nó đi vào đoạn `sr-only` cuối component. Dựng thêm một
 * bộ handler focus chỉ để lặp lại một con số đã có trong đoạn đó là thêm mã
 * không mua được gì.
 */
import { Link } from '@tanstack/react-router'
import { Icon } from '@/components/icons'
import { Sao } from '@/components/ui/Sao'
import type { Overview, SaoKey } from '../api'
import { so, soLe1, soLe2 } from '@/lib/dinhDang'
import { DongTip, HopTip } from './Tip'
import { useTip } from './useTip'

// Vẽ từ 5★ xuống 1★ — mắt đọc "nhiều sao nhất trước".
const THU_TU_SAO = [5, 4, 3, 2, 1] as const

export function TheDanhGia({ danhGia }: { readonly danhGia: Overview['danhGia'] }) {
  const { trungBinh, truoc, tong, theoSao } = danhGia
  const delta = truoc !== null ? trungBinh - truoc : null
  const tang = delta !== null && delta >= 0

  // Chưa ai chấm ⇒ KHÔNG khối số, KHÔNG sao, KHÔNG phân bố — cả ba đều là
  // cách nói «đã đo được rồi». Tiêu đề ô nằm ở `TongQuanScreen` nên vẫn còn.
  if (tong === 0) {
    return (
      <div
        data-testid="dg-chua-co"
        className="flex h-full flex-col items-center justify-center gap-1.5 text-center"
      >
        <p className="text-[13px] font-medium text-muted">Chưa có đánh giá</p>
        <p className="max-w-[230px] text-phu leading-relaxed text-muted-2">
          Khách chưa chấm điểm phiên nào trong kỳ này.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-none border-b border-border-soft pb-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[30px] font-medium leading-none tracking-tight">
            {soLe2(trungBinh)}
          </span>
          <span className="text-[14px] text-muted-2">/ 5</span>
          {delta !== null && (
            /* Đuôi «điểm» KHÔNG phải trang trí: badge của ô ① ngay bên trái
               trông y hệt badge này nhưng mang PHẦN TRĂM (`▲13,5%`), còn cái
               này mang chênh lệch TUYỆT ĐỐI trên thang 5 (`▼0,08`). Hai badge
               cùng hình, cùng cỡ, cùng cụm mũi tên, cách nhau một ô — không
               có đơn vị thì `0,08` đọc thành «giảm 0,08%», tức nhỏ đi 100
               lần so với sự thật. */
            <span
              data-testid="dg-delta"
              className={`inline-flex items-center gap-[3px] rounded-full px-2 py-0.5 font-mono text-nhan ${
                tang ? 'bg-acs text-acd' : 'bg-badge-alert-bg text-badge-alert-fg'
              }`}
            >
              {tang ? '▲' : '▼'} {soLe2(Math.abs(delta))}
              <span className="font-sans">điểm</span>
            </span>
          )}
        </div>
        <div className="mt-2">
          {/* KHÔNG làm tròn: xem chú thích đầu file. */}
          <Sao gia={trungBinh} kichThuoc={17} />
        </div>
        <p className="mt-[7px] text-[12px] text-muted">
          <b className="font-mono font-medium text-fg">{so(tong)}</b> lượt đánh giá
        </p>
      </div>

      <div className="mt-2.5 grid flex-1 auto-rows-fr gap-1.5">
        {THU_TU_SAO.map((n) => (
          <HangSao key={n} n={n} dem={theoSao[String(n) as SaoKey] ?? 0} tong={tong} />
        ))}
      </div>

      {/* Bảng số cho trình đọc màn hình — cùng lối với ô ① và ô ⑤. «Tỉ lệ» chỉ
          sống trong tooltip (chuột), nên không có đoạn này thì nó không tới
          được người dùng trình đọc màn hình bằng bất kỳ đường nào. */}
      <p className="sr-only">
        Phân bố sao:{' '}
        {THU_TU_SAO.map((n) => {
          const dem = theoSao[String(n) as SaoKey] ?? 0
          return `${n} sao — ${so(dem)} lượt, ${soLe1(tiLe(dem, tong))}%`
        }).join('; ')}
      </p>
    </div>
  )
}

/** Tỉ lệ phần trăm của một mức sao. `tong = 0` ⇒ 0/0 ra `NaN`, và `width:NaN%`
 *  là CSS không hợp lệ (trình duyệt bỏ qua LẶNG LẼ) — chốt 0 tường minh thay
 *  vì dựa vào hành vi ngầm đó. Nhánh rỗng ở đầu `TheDanhGia` đã chặn
 *  `tong === 0` không tới được đây; giữ phép kiểm này làm lớp thứ hai, vì nó
 *  rẻ và vì ngày ai đó gỡ nhánh kia thì `NaN%` quay lại mà không lỗi nào nổ. */
function tiLe(dem: number, tong: number): number {
  return tong > 0 ? (dem / tong) * 100 : 0
}

/** Một mức sao — thanh tỉ lệ + tooltip, và là đường đi tới `/quality` đã lọc
 *  sẵn đúng mức sao đó. Xem docstring đầu file cho cả hai quyết định. */
function HangSao({
  n,
  dem,
  tong,
}: {
  readonly n: number
  readonly dem: number
  readonly tong: number
}) {
  const ti = tiLe(dem, tong)
  // Một state độc lập mỗi hàng — mỗi hàng chỉ cần biết vị trí tooltip của
  // chính nó, không có "hàng đang xem" chung nào cần đồng bộ (cùng lý lẽ
  // `TheKienThuc.tsx`; `i` truyền vào luôn là `0`).
  const { tip, taiChuot, an } = useTip()

  return (
    <Link
      to="/quality"
      search={{ rating: [n] }}
      data-testid={`dg-sao-${n}`}
      onMouseMove={(e) => taiChuot(0, e)}
      onMouseLeave={an}
      // `text-fg` + `no-underline` CỐ Ý, cùng lý do đã ghi ở `TheKienThuc.tsx`:
      // luật toàn cục `a { color: var(--color-ac) }` (theme.css) ăn vào hàng
      // này ngay khi nó thành `<Link>`. Ba ô con đã tự khai sắc riêng nên
      // không đổi màu, nhưng để `<a>` trần thì mọi chữ thêm vào sau này lên
      // xanh accent mà không ai chủ ý.
      // `-mx-2 px-2` để nền hover nở rộng ra hai bên mà KHÔNG đẩy lưới: ba cột
      // vẫn thẳng hàng với khối số phía trên.
      // Nền hover là `fill-strong`, KHÔNG phải `fill`: rãnh của thanh tỉ lệ
      // chính là `bg-fill`, nên tô nền hover cùng sắc đó làm phần CHƯA đạt của
      // thanh tan vào nền — đúng lúc người dùng đang nhìn nó.
      className="relative z-10 -mx-2 grid grid-cols-[26px_1fr_34px] items-center gap-2.5 rounded-sm px-2 text-phu text-fg no-underline transition-colors hover:bg-fill-strong"
    >
      <span className="inline-flex items-center justify-end gap-0.5 font-mono text-muted-2">
        {n}
        <Icon name="star" className="size-3 fill-current" />
        <span className="sr-only"> sao</span>
      </span>
      <span className="h-[11px] overflow-hidden rounded-full bg-fill">
        <span
          data-vai="thanh"
          className="block h-full rounded-full bg-ac"
          style={{ width: `${ti}%` }}
        />
      </span>
      <span className="text-right font-mono text-muted">{so(dem)}</span>

      {tip && (
        <HopTip x={tip.x} y={tip.y} testId="dg-tip">
          <div className="mb-[5px] text-[11.5px] font-semibold">{n} sao</div>
          <DongTip ten="Lượt" gia={so(dem)} />
          <DongTip ten="Tỉ lệ" gia={`${soLe1(ti)}%`} />
        </HopTip>
      )}
    </Link>
  )
}
