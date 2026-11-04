/**
 * Chỉ báo «nội dung dự án này đang trên đường tới agent». HAI hình thái và một
 * trạng thái im lặng — lúc bình thường không hiện gì, vì một nhãn khẳng định điều
 * mặc định chỉ dạy người ta rằng có thứ cần theo dõi.
 *
 * KHÔNG tự gọi API: hiện ở mọi hàng bảng nên tự tra là N request cho một trang.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { syncKb, type KbStatus } from '../api'
import { KB_KEY } from '../useKbStatus'

const NUT_THU_LAI =
  'rounded border border-badge-alert-fg/40 px-1.5 py-0.5 text-nhan hover:bg-badge-alert-fg hover:text-white disabled:opacity-50'

export function KbBadge({ tt }: { tt: KbStatus | undefined }) {
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: () => syncKb(tt!.projectCode, 'delta'),
    onSuccess: () => void qc.invalidateQueries({ queryKey: KB_KEY }),
  })

  if (!tt) return null

  if (tt.hasError) {
    return (
      <span
        className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] text-badge-alert-fg"
        onClick={(e) => e.stopPropagation()}
      >
        ✕ Lỗi nạp kiến thức cho agent
        <button type="button" className={NUT_THU_LAI} disabled={m.isPending} onClick={() => m.mutate()}>
          Thử lại
        </button>
        {m.error && <span>Không gửi được yêu cầu. Thử lại.</span>}
      </span>
    )
  }

  if (tt.total <= 0) return null

  const pct = Math.round((tt.done / tt.total) * 100)

  return (
    <span
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      title={`${tt.done}/${tt.total} mục đã tới agent`}
      className="inline-flex items-center gap-2 whitespace-nowrap"
    >
      <span className="block h-[5px] w-[118px] overflow-hidden rounded-full bg-fill-strong">
        {/* `block` bắt buộc: span mặc định là inline và inline thì bỏ qua width/height. */}
        <span
          className={`block h-full rounded-full bg-ac transition-[width] duration-500 ${pct >= 100 ? 'opacity-75' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="text-[12px] tabular-nums text-muted">{pct}%</span>
    </span>
  )
}
