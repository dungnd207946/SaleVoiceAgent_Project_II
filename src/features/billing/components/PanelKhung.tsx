/**
 * Vỏ dialog dùng CHUNG cho ba slide-over của module `billing` — `PanelBoGia`
 * (Task 9), `PanelGanWorkspace` (Task 10), `ChiTietPhien` (Task 6). Trước
 * review 2026-08-20, ba nơi giữ BA bản COPY NGUYÊN VĂN của đúng phần này (53
 * dòng byte-identical giữa `PanelGanWorkspace`/`PanelBoGia`, và `ChiTietPhien`
 * inline cùng JSX + cùng hai `useEffect`) — nhánh này đã có HAI bug focus/
 * Escape từ đúng thói quen "sửa một chỗ quên hai chỗ kia". Rút vào một chỗ.
 *
 * Từ 2026-10-05 vỏ là `HopThoai` (`<dialog>` + `showModal()`): Esc, bấm nền,
 * Tab bị giữ trong khung, trả focus đều do nó lo — chỗ gọi KHÔNG còn tự dựng
 * lớp phủ `fixed inset-0 z-70` + nút backdrop. Component này còn lo: khung
 * slide-over neo phải (`<dialog>` tự khai trọn className — xem docstring
 * `HopThoai`: preflight đặt margin 0 và UA đặt `color: CanvasText`, nên margin,
 * màu chữ và `backdrop:` phải tự có) và focus vào nút × lúc mount.
 */
import { useEffect, useRef, type ReactNode } from 'react'
import { HopThoai } from '@/components/ui/HopThoai'

export function PanelKhung({
  idTieuDe,
  onDong,
  children,
}: {
  readonly idTieuDe: string
  readonly onDong: () => void
  readonly children: ReactNode
}) {
  const oDongRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    oDongRef.current?.focus()
  }, [])

  return (
    <HopThoai
      onDong={onDong}
      aria-labelledby={idTieuDe}
      className="m-0 ml-auto flex h-dvh max-h-none w-full max-w-[min(760px,94vw)] flex-col bg-surface text-fg shadow-noi backdrop:bg-panel/45"
    >
      <button
        ref={oDongRef}
        type="button"
        onClick={onDong}
        aria-label="Đóng"
        className="absolute top-4 right-4 flex size-8 flex-none items-center justify-center rounded-md text-muted hover:bg-fill hover:text-fg"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.92"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="size-4"
        >
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
      {children}
    </HopThoai>
  )
}
