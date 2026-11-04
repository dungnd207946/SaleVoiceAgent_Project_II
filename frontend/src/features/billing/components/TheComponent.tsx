/**
 * Thẻ PHẢI của mục ② `/billing` — tiền tách theo component, kèm SỐ ĐO của mỗi
 * component và một thanh tỷ lệ. PORT từ `docs/design/demo-usage-billing.html`
 * § `#ds-comp`.
 *
 * BA QUYẾT ĐỊNH CỦA BẢN DEMO, GIỮ NGUYÊN:
 *
 * ① **Không có hàng TỔNG cho cột số đo.** `audio_sec` của `vad`/`stt`/`call`
 *    đo những quãng CHỒNG LẤN nhau trong cùng một cuộc gọi (agent nghe trong
 *    lúc TTS đang phát) — cộng lại là đếm một giây nhiều lần, đo được ~2,64×
 *    ở BE. Chỉ cột TIỀN cộng được, và tổng đó đã nằm ở thẻ KPI mục ①. Dòng
 *    chú thích cuối thẻ nói đúng điều này ra cho người đọc; đừng bỏ nó đi.
 *
 * ② **Component ĐO ĐƯỢC mà KHÔNG tính tiền vẫn nằm trong danh sách** — xám,
 *    ngoài thang accent, và nói thẳng «không tính tiền» thay vì hiện `0 ₫`
 *    trơn. Ẩn nó đi thì ai thấy 52.910 giây VAD trong log agent mà không thấy
 *    ở đây sẽ đi hỏi; hiện `0 ₫` trơn thì đọc thành «dùng mà không tốn», che
 *    mất khả năng đây là một tổ hợp CHƯA CÓ GIÁ (đang mất doanh thu — chính
 *    thứ dải `thieu_gia` phía trên cảnh báo).
 *
 * ③ **Sắc theo THỨ HẠNG, không theo danh tính component.** Các component là
 *    những lát của MỘT tổng đã xếp theo độ lớn, không phải những hạng ngang
 *    nhau cần phân biệt bằng sắc. Nhãn và bảng màu nằm ở `../component-hien.ts`
 *    — DÙNG CHUNG với tooltip của biểu đồ ngày, vì người dùng đối chiếu hai
 *    thẻ đó bằng đúng màu ô vuông.
 *
 * SỐ ĐO NÀO ĐƯỢC HIỆN là suy từ `PRICING_BASIS` (`../pricingBasis`), không
 * phải một bảng `component → nhãn` viết tay thứ hai: cơ sở tính tiền của một
 * component CHÍNH LÀ số đo đáng hiện cạnh số tiền của nó. Component lạ (BE
 * thêm mới, FE chưa biết) rơi về `so_event` — không bao giờ hiện rỗng.
 */
import { MAU_KHONG_TINH_TIEN, nhanComponent } from '../component-hien'
import { SO, giay, phanTram, soSanhTien, tien, token, type Tien } from '../dinh-dang'
import type { DongComponent } from '../kieu'
import { metricCua } from '../pricingBasis'

/**
 * Chuỗi số đo của một dòng — CHỌN theo cơ sở tính tiền của chính component đó.
 * Nhiều cơ sở (LLM có 4 metric token) ⇒ gộp thành một con số token; `stt` có cả
 * giây lẫn ký tự ⇒ hiện giây (vế người đọc hiểu ngay) rồi tới ký tự.
 */
function soDo(d: DongComponent): string {
  const metric = new Set(metricCua(d.component).map((b) => b.metric))
  const phan: string[] = []
  const tongToken = d.input_tokens + d.output_tokens + d.cache_read_tokens
  if (metric.has('input_tokens') && tongToken > 0) phan.push(`${token(tongToken)} token`)
  if (metric.has('audio_sec') && d.audio_sec > 0) phan.push(giay(d.audio_sec))
  if (metric.has('text_units') && d.text_units > 0) phan.push(`${token(d.text_units)} ký tự`)
  if (metric.has('units') && d.units > 0) phan.push(`${SO(d.units)} lượt`)
  if (phan.length === 0) phan.push(`${SO(d.so_event)} lượt`)
  return phan.join(' · ')
}

function Hang({
  d,
  mau,
  tong,
}: {
  readonly d: DongComponent
  readonly mau: string
  /** `chi_phi_tong` của BE quy về số — CHỈ để tính bề rộng thanh và phần trăm. */
  readonly tong: number
}) {
  const khongTinhTien = Number(d.chi_phi) === 0
  const pt = tong > 0 ? (Number(d.chi_phi) / tong) * 100 : 0
  return (
    <div
      className={`grid grid-cols-[1fr_auto] items-center gap-x-2.5 border-t border-rule py-2 first:border-t-0 ${khongTinhTien ? 'opacity-75' : ''}`}
    >
      <div className="flex min-w-0 items-center gap-2">
        <i
          aria-hidden
          className="size-[9px] flex-none rounded-[2px]"
          style={{ background: khongTinhTien ? 'var(--color-comp-0)' : mau }}
        />
        <span className="truncate text-than text-fg">{nhanComponent(d.component)}</span>
        <span className="flex-none font-mono text-nhan whitespace-nowrap text-muted-2">
          · {soDo(d)}
        </span>
      </div>
      <div className="flex flex-col items-end gap-px">
        <span
          className={`font-mono text-than tabular-nums ${khongTinhTien ? 'text-muted-2' : 'text-fg'}`}
        >
          {tien(d.chi_phi)} ₫
        </span>
        <span className={`text-nhan text-muted-2 ${khongTinhTien ? '' : 'font-mono'}`}>
          {khongTinhTien ? 'không tính tiền' : phanTram(Number(d.chi_phi), tong)}
        </span>
      </div>
      {Number(d.chi_phi_du_lieu_ngoai ?? 0) > 0 && (
        <p className="col-span-2 text-[11.5px] text-muted">
          {soSanhTien(d.chi_phi_du_lieu_ngoai!, d.chi_phi) === 0
            ? 'toàn bộ là dữ liệu ngoài'
            : `gồm ${tien(d.chi_phi_du_lieu_ngoai!)} ₫ dữ liệu ngoài`}
        </p>
      )}
      <div className="col-span-2 mt-px h-[3px] overflow-hidden rounded-[2px] bg-fill-strong">
        <span
          className="block h-full rounded-[2px]"
          style={{
            width: `${pt.toFixed(2)}%`,
            background: khongTinhTien ? 'var(--color-comp-0)' : mau,
          }}
        />
      </div>
    </div>
  )
}

export function TheComponent({
  items,
  chiPhiTong,
  mau,
}: {
  readonly items: readonly DongComponent[]
  readonly chiPhiTong: Tien
  /** DÙNG CHUNG với tooltip biểu đồ — xem `component-hien.ts`. */
  readonly mau: Readonly<Record<string, string>>
}) {
  // Mẫu số là `chi_phi_tong` CỦA BE, không phải tổng tự cộng lại từ `items`:
  // hai con số đó phải bằng nhau, và khi chúng không bằng thì thứ đúng để hiện
  // là con số BE chịu trách nhiệm — xem docstring `congTien()` ở `dinh-dang.ts`.
  const tong = Number(chiPhiTong)
  return (
    <div className="flex min-w-0 flex-col rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-rule px-4 py-2.5">
        <h3 className="text-than font-medium text-fg">Theo từng dịch vụ</h3>
        <p className="ml-auto text-phu text-muted">Cả kỳ</p>
      </div>
      <div className="flex flex-1 flex-col px-4 pt-1.5 pb-3.5">
        {items.map((d) => (
          <Hang key={d.component} d={d} mau={mau[d.component] ?? MAU_KHONG_TINH_TIEN} tong={tong} />
        ))}
        {/* <p className="mt-auto border-t border-dashed border-border-strong pt-2.5 text-phu leading-[1.55] text-muted">
          <b className="font-medium text-fg">Cột số đo không có hàng tổng.</b> Giây audio của{' '}
          <code className="font-mono text-[12px]">vad</code>·
          <code className="font-mono text-[12px]">stt</code>·
          <code className="font-mono text-[12px]">call</code> chồng lấn nhau; cộng lại là đếm một
          giây nhiều lần. Chỉ cột tiền cộng được.
        </p> */}
      </div>
    </div>
  )
}
