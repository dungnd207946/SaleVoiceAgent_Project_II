/**
 * Hộp xác nhận dùng chung — khuôn portal: `HopThoai` + `HANG_NUT` (nút chính CUỐI), không `confirm()`.
 * Không có `onDongY` ⇒ hộp chỉ để báo (một nút đóng). `phaHuy` ⇒ nút chính đỏ và focus vào Huỷ
 * lúc mở (APG: nút ít phá huỷ nhất). `loi` hiện ngay trên hàng nút — hộp ở lại để thử lại.
 */
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { CAO_O, HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'

const NUT_XOA = `${CAO_O} inline-flex items-center justify-center rounded-md bg-badge-alert-fg px-[15px] text-than font-semibold text-white disabled:opacity-50`

export function XacNhan({
  tieuDe,
  children,
  nutChinh,
  nutPhu = 'Huỷ',
  phaHuy,
  dangGui,
  loi,
  role = 'dialog',
  onDongY,
  onHuy,
}: {
  tieuDe: string
  children?: ReactNode
  nutChinh?: string | undefined
  nutPhu?: string | undefined
  phaHuy?: boolean | undefined
  dangGui?: boolean | undefined
  loi?: string | null | undefined
  role?: 'dialog' | 'alertdialog'
  onDongY?: (() => void) | undefined
  onHuy: () => void
}) {
  const id = useId()
  const huy = useRef<HTMLButtonElement>(null)
  // Sau `showModal()` của `HopThoai` (layout effect) — nó đã ghi nhận chỗ trả focus.
  useEffect(() => {
    if (phaHuy) huy.current?.focus()
  }, [phaHuy])
  return (
    <HopThoai
      onDong={onHuy}
      khoaDong={dangGui ?? false}
      aria-labelledby={id}
      role={role}
      className={`${KHUNG_HOP_THOAI} max-w-[440px]`}
    >
      <h2 id={id} className="text-muc leading-tight font-semibold text-fg">
        {tieuDe}
      </h2>
      {children ? (
        <div className="mt-3 space-y-2 text-than leading-[1.55] text-muted">{children}</div>
      ) : null}
      {loi ? (
        <p
          role="alert"
          className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] text-badge-alert-fg"
        >
          {loi}
        </p>
      ) : null}
      <div className={`${HANG_NUT} mt-5`}>
        <button
          ref={huy}
          type="button"
          onClick={onHuy}
          disabled={dangGui}
          className={`${NUT_PHU} cursor-pointer`}
        >
          {nutPhu}
        </button>
        {onDongY && nutChinh ? (
          <button
            type="button"
            onClick={onDongY}
            disabled={dangGui}
            className={`${phaHuy ? NUT_XOA : NUT_CHINH} cursor-pointer`}
          >
            {nutChinh}
          </button>
        ) : null}
      </div>
    </HopThoai>
  )
}
