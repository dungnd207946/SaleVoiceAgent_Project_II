/**
 * Dải thống kê đầu màn `/quality` — điểm trung bình (cột trái, rộng cố định)
 * + phân bố 5 sao (cột phải, mỗi dòng một thanh ngang).
 *
 * Component TRÌNH BÀY thuần — không tự gọi API, chỉ đọc 3 field của
 * `DanhSachFeedback` (Task 4). Dữ liệu thật do Task 8 truyền vào.
 */
import { Icon } from '@/components/icons'
import { Sao } from '@/components/ui/Sao'
import { so, soLe2 } from '@/lib/dinhDang'
import type { DanhSachFeedback } from '../api'

// Vẽ từ 5★ xuống 1★ — mắt đọc "nhiều sao nhất trước", giống mọi UI rating
// (App Store, Google Play…), không phải thứ tự lưu trong `theoSao`.
const THU_TU_SAO = [5, 4, 3, 2, 1] as const

export function FeedbackTongQuan({
  total,
  theoSao,
  diemTrungBinh,
}: {
  total: number
  theoSao: DanhSachFeedback['theoSao']
  diemTrungBinh: number
}) {
  return (
    <div className="flex border-b border-border-soft max-md:flex-col">
      <div className="flex w-[220px] shrink-0 flex-col justify-center border-r border-border-soft px-6 py-5 max-md:w-full max-md:border-r-0 max-md:border-b max-md:px-4">
        <p className="text-nhan uppercase tracking-wide text-muted-2">Người dùng đánh giá </p>
        {/* Cùng formatter với ô «Đánh giá» ở Tổng quan (`soLe2`): trước in số thô
            «4.33» — trong vi-VN dấu chấm là phân cách NGHÌN. */}
        <p className="font-mono text-[28px] font-medium leading-none tracking-tight tabular-nums">
          {soLe2(diemTrungBinh)}
        </p>
        <div className="mt-1.5">
          {/* KHÔNG làm tròn: `Sao` tô một phần ngôi cuối theo đúng số lẻ —
              làm tròn ở đây là vẽ lệch tới nửa sao so với con số ngay trên. */}
          <Sao gia={diemTrungBinh} kichThuoc={16} />
        </div>
        <p className="mt-2 text-[13px] text-muted">{so(total)} lượt đánh giá</p>
      </div>
      <div className="flex flex-1 flex-col justify-center gap-1.5 px-6 py-4 max-md:px-4">
        {THU_TU_SAO.map((n) => {
          const dem = theoSao[String(n) as keyof DanhSachFeedback['theoSao']]
          // total = 0 (chưa có feedback nào) → chia 0/0 ra NaN, width: NaN%
          // là CSS không hợp lệ (bị trình duyệt bỏ qua, thanh coi như 0%) —
          // chốt tường minh 0 ở đây để không phụ thuộc hành vi ngầm đó.
          const ty_le = total > 0 ? (dem / total) * 100 : 0
          return (
            <div
              key={n}
              data-testid={`phan-bo-${n}`}
              data-sao-hang={n}
              className="flex items-center gap-2 text-[13px]"
            >
              <span className="inline-flex w-[30px] items-center justify-end gap-0.5 font-mono text-muted-2">
                {n}
                <Icon name="star" className="size-3 fill-current" />
                <span className="sr-only"> sao</span>
              </span>
              <div className="h-[7px] max-w-[280px] flex-1 rounded-full bg-fill">
                <div className="h-full rounded-full bg-ac" style={{ width: `${ty_le}%` }} />
              </div>
              <span className="w-8 font-mono text-muted-2 tabular-nums">{so(dem)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
