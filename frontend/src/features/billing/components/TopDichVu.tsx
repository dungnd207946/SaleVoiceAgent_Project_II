/**
 * «Tiền đi đâu» bản gọn cho ô Chi phí của `/dashboard` (06/10 — người dùng chỉ ra
 * ô chỉ có một con số + sparkline, phần dưới trống). Mấy dịch vụ tốn nhất của kỳ,
 * mỗi dòng: ô màu · tên · số tiền + thanh tỉ lệ — CÙNG nhãn, CÙNG màu theo thứ
 * hạng với thẻ «Theo từng dịch vụ» của `/billing` (`component-hien.ts`), nên bấm
 * sang là đối chiếu được ngay.
 *
 * Đọc `usePhanTich` — CÙNG khoá query với `SparklineChiPhi` ngay trên, React Query
 * gộp hai observer: không thêm request nào. Chưa có dữ liệu / lỗi ⇒ `null` (cùng thế
 * đứng `SparklineChiPhi`: `/billing` mới là chỗ báo lỗi chi tiết).
 *
 * Bao nhiêu dòng VỪA chỗ là do chỗ gọi quyết qua `className` (lưới `auto-fill`
 * theo chiều cao ô — dòng không vừa cao 0, không bị cắt nửa); `toiDa` chỉ là trần.
 * Cắt bằng CSS được vì dòng không bấm được, không có gì lọt thứ tự Tab.
 *
 * Bỏ dịch vụ không tính tiền (`chi_phi` 0 — VAD, hoặc thiếu dòng giá): ô tóm tắt
 * trả lời «tiền đi đâu», một dòng «0 ₫» ở đây là nhiễu; `/billing` vẫn liệt kê đủ.
 */
import { usePhanTich } from '../api'
import { bangMau, nhanComponent } from '../component-hien'
import { tien } from '../dinh-dang'

export function TopDichVu({
  from,
  to,
  toiDa = 4,
  className = '',
}: {
  readonly from: string
  readonly to: string
  readonly toiDa?: number
  readonly className?: string
}) {
  const q = usePhanTich(from, to)
  if (!q.data) return null
  const { theo_component, chi_phi_tong, currency } = q.data
  const mau = bangMau(theo_component)
  const tong = Number(chi_phi_tong)
  const dong = theo_component.filter((d) => Number(d.chi_phi) > 0).slice(0, toiDa)
  if (dong.length === 0 || tong <= 0) return null

  return (
    <ul aria-label="Chi phí theo dịch vụ" className={`border-t border-border-soft ${className}`}>
      {dong.map((d) => {
        const pt = (Number(d.chi_phi) / tong) * 100
        return (
          <li key={d.component} className="min-h-0 overflow-hidden pt-2">
            <div className="flex items-center gap-2 text-phu">
              <i
                aria-hidden
                className="size-[9px] flex-none rounded-[2px]"
                style={{ background: mau[d.component] }}
              />
              <span className="min-w-0 flex-1 truncate text-fg">{nhanComponent(d.component)}</span>
              <span className="flex-none font-mono text-fg tabular-nums">
                {tien(d.chi_phi)}
                <span className="ml-1 text-nhan text-muted-2">{currency}</span>
              </span>
            </div>
            <div className="mt-1 h-[3px] overflow-hidden rounded-[2px] bg-fill-strong">
              <span
                className="block h-full rounded-[2px]"
                style={{ width: `${pt.toFixed(2)}%`, background: mau[d.component] }}
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}
