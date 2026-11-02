/** Hộp thoại của màn Dữ liệu ngoài — cùng khung/số đo với `VaiTroDialog` của module agent. */
import { useEffect, type ReactNode } from 'react'

const KHUNG =
  'relative w-full max-w-[560px] rounded-2xl border border-border-field bg-surface p-5 shadow-hop-thoai max-md:max-h-[calc(100dvh-2rem)] max-md:overflow-y-auto'

export function HopThoai({ tieuDe, dong, children }: { tieuDe: string; dong: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dong()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [dong])
  return (
    <div className="fixed inset-0 z-70 grid place-items-center px-4">
      <button type="button" aria-label="Đóng" onClick={dong} className="absolute inset-0 cursor-default bg-panel/45" />
      <div role="dialog" aria-modal="true" aria-label={tieuDe} className={KHUNG}>
        <h2 className="text-[16.5px] leading-tight font-semibold text-fg">{tieuDe}</h2>
        {children}
      </div>
    </div>
  )
}
