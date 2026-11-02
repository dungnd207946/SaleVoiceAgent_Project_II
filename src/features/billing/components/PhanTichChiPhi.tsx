/**
 * Mục ② «Tiền đi đâu» — băng hai thẻ: TRÁI theo ngày (`BieuDoChiPhi`), PHẢI
 * theo component (`TheComponent`). Cùng kỳ, cùng tổng với mục ①, khác chiều gộp.
 *
 * MỘT REQUEST cho cả hai thẻ (`GET /billing/breakdown`) — chúng luôn hiện cùng
 * nhau, luôn cùng khoảng ngày, và hai request rời nhau cho ra hai skeleton lệch
 * pha trên cùng một hàng.
 *
 * LƯỚI `1fr 336px` từ `lg` trở lên, xếp dọc ở màn hẹp: thẻ component có bề
 * rộng CỐ ĐỊNH vì nội dung nó là một danh sách nhãn + số, không co giãn theo
 * dữ liệu; chart thì ngược lại, càng rộng càng đọc được nhiều ngày. Số 336
 * chép từ bản demo.
 *
 * LỖI Ở ĐÂY KHÔNG LÀM SẬP CẢ MÀN. Mục ① và ③ gọi endpoint khác, chúng vẫn
 * dùng được khi riêng `/breakdown` hỏng — nên nhánh lỗi là một thẻ nhỏ tại
 * chỗ, không phải `LoiTai` toàn màn. Cùng lý lẽ `BangLuotDung` đã áp cho mục ③.
 */
import { LoiApi } from '@/lib/http'
import { usePhanTich } from '../api'
import { bangMau } from '../component-hien'
import { BieuDoChiPhi } from './BieuDoChiPhi'
import { TheComponent } from './TheComponent'

const LUOI = 'grid gap-3.5 lg:grid-cols-[minmax(0,1fr)_336px]'

export function PhanTichChiPhi({ from, to }: { readonly from: string; readonly to: string }) {
  const q = usePhanTich(from, to)

  if (q.isPending) {
    return (
      <div className={LUOI}>
        <div className="h-[300px] animate-pulse rounded-lg border border-border bg-fill" />
        <div className="h-[300px] animate-pulse rounded-lg border border-border bg-fill" />
      </div>
    )
  }

  if (q.error) {
    // 403 đã được mục ① chặn trước (cùng action `billing.read`) nên tới đây
    // gần như chỉ còn lỗi mạng/5xx — vẫn hiện message thật thay vì câu chung.
    const message = q.error instanceof LoiApi ? q.error.message : 'Không tải được dữ liệu'
    return (
      <div className="rounded-lg border border-border bg-surface p-4 text-than text-muted">
        <p>{message}</p>
        <button
          type="button"
          onClick={() => void q.refetch()}
          className="mt-2 text-[13px] font-medium text-ac hover:text-acd"
        >
          Thử lại
        </button>
      </div>
    )
  }

  const d = q.data
  // Bảng màu tính MỘT LẦN ở đây rồi truyền xuống cả hai thẻ — hai thẻ tự tính
  // riêng là hai bảng có thể lệch nhau, mà người dùng đối chiếu chúng bằng
  // đúng màu ô vuông (xem `component-hien.ts`).
  const mau = bangMau(d.theo_component)
  return (
    <div className={LUOI}>
      <BieuDoChiPhi chuoi={d.theo_ngay} chiPhiTong={d.chi_phi_tong} mau={mau} />
      <TheComponent items={d.theo_component} chiPhiTong={d.chi_phi_tong} mau={mau} />
    </div>
  )
}
