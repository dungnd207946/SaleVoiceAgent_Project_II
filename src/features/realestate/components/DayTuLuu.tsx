/**
 * Đáy dán của form dự án — tình trạng lưu, tiến độ nạp, và MỘT nút Sửa / Lưu.
 *
 * MỘT NÚT CHO CẢ FORM, không phải mỗi tab một nút (người dùng chốt 2026-08-21):
 * bấm Sửa ở Tổng quan rồi sang Vị trí thì vẫn đang sửa. Cờ vì thế sống ở
 * `DuAnForm`, không sống trong tab.
 *
 * «LƯU» MÀ KHÔNG GỬI GÌ: mỗi ô đã tự lưu lúc rời ô, nên nút chỉ đóng chế độ sửa.
 * Nó ghi «Lưu» vì đó là chữ người dùng đi tìm, và MỜ khi chưa sửa gì để thôi mời
 * bấm một cú không làm gì.
 *
 * Cờ, bản ghi dự án và `coDoi` đi qua context — xem `../khungSua.ts`.
 */
import type { ReactNode } from 'react'
import { HANG_NUT_DAN, NUT_CHINH } from '@/components/ui/Bang'
import { KbBadge } from './KbBadge'
import { useKhungSua } from '../khungSua'
import { useKbStatus } from '../useKbStatus'

export function DayTuLuu({
  dangLuu,
  vuaLuu,
  children,
}: {
  dangLuu: boolean
  vuaLuu: boolean
  children?: ReactNode
}) {
  const { duAn, dangSua, doiSua } = useKhungSua()
  const kb = useKbStatus()

  return (
    <div data-testid="pform-day" className={HANG_NUT_DAN}>
      <span className="shrink-0 text-[13px] text-muted-2" role="status">
        {dangLuu ? 'Đang lưu…' : vuaLuu ? 'Đã lưu.' : ''}
      </span>
      {duAn && <KbBadge tt={kb.byCode[duAn.projectCode]} />}
      <span className="flex-1" />
      {children}
      {duAn && (
        <button
          type="button"
          // Mờ = XÁM, không phải xanh nhạt: `disabled:opacity-50` của
          // `NUT_CHINH` vẫn đọc ra một nút chính đang chờ, còn xám thì nói
          // «chưa có gì để lưu».
          className={`${NUT_CHINH} shrink-0 disabled:cursor-not-allowed disabled:bg-fill-strong disabled:text-muted-3 disabled:opacity-100`}
          onClick={() => doiSua(!dangSua)}
        >
          {dangSua ? 'Lưu' : 'Sửa'}
        </button>
      )}
    </div>
  )
}
