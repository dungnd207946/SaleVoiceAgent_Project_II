import { createContext, type ReactNode, useContext, useEffect, useRef } from 'react'
import { HopThoai } from '@/components/ui/HopThoai'

/**
 * Lớp phủ nav cho tablet/mobile (spec 2026-09-28-responsive-mobile §4).
 *
 * Chứa ĐÚNG `<Rail/>`/`<NavPanel/>` của desktop — không dựng nav thứ hai (hai nav
 * trông giống nhau sẽ lệch ở lần sửa sau, như bộ tab của Thử agent từng lệch).
 *
 * Đóng theo CÚ BẤM mục màn (context `DongNav`), KHÔNG theo đổi pathname: bấm rail
 * cũng đổi pathname (tới màn đầu của mảng) mà lớp phủ phải ở lại để người dùng
 * thấy các màn khác trong mảng; và bấm mục đang sáng không đổi pathname mà vẫn
 * phải đóng.
 *
 * Unmount khi đóng là việc của nơi gọi (`_app.tsx` render có điều kiện).
 *
 * HAI kiểu theo tầng (audit 05/10 — bản trước khai `aria-modal` cho cả hai mà
 * không giữ focus: Tab lọt ra trang phía sau 27/40 lần):
 *  · mobile (`trai`) — lớp phủ chứa TRỌN nav nên là hộp thoại THẬT (`HopThoai`,
 *    `<dialog>` + `showModal()`): nền inert, Tab quanh trong lớp phủ, Esc/back
 *    đóng, trả focus về ☰. Esc khi palette mở bên trên: chỉ palette đóng.
 *  · tablet (`sauRail`) — rail nằm NGOÀI lớp phủ và phải bấm được khi panel đang
 *    mở (nút thu/mở panel ở đáy rail, đổi mảng), nên KHÔNG modal: không khai
 *    `aria-modal`, Tab đi tiếp ra rail/trang là đúng.
 */
const DongNav = createContext<(() => void) | null>(null)

/** `null` ngoài lớp phủ ⇒ `NavItem` trên desktop không đổi hành vi. */
export function useDongNav() {
  return useContext(DongNav)
}

export function LopPhu({
  dong,
  nhan,
  lech = 'trai',
  children,
}: {
  dong: () => void
  nhan: string
  /** `sauRail`: tablet — rail đã nằm trong luồng, lớp phủ mở ngay bên phải nó. */
  lech?: 'trai' | 'sauRail'
  children: ReactNode
}) {
  const noiDung = <DongNav.Provider value={dong}>{children}</DongNav.Provider>
  if (lech === 'sauRail') {
    return (
      <CanhRail dong={dong} nhan={nhan}>
        {noiDung}
      </CanhRail>
    )
  }
  // Hộp thoại choán trọn màn (nền trong suốt, mờ do `backdrop:`): nav bên trái, phần
  // còn lại là nút «Đóng menu» — chạm ra ngoài nav là đóng, như bản trước.
  return (
    <HopThoai
      onDong={dong}
      aria-label={nhan}
      dongBangNen={false}
      className="m-0 flex h-dvh max-h-none w-full max-w-none bg-transparent p-0 text-fg backdrop:bg-fg/25"
    >
      <div className="relative flex h-dvh overscroll-contain shadow-noi">{noiDung}</div>
      <button
        type="button"
        aria-label="Đóng menu"
        onClick={dong}
        className="min-w-0 flex-1 cursor-default"
      />
    </HopThoai>
  )
}

/** Tablet: panel mở cạnh rail, KHÔNG modal (xem đầu tệp). */
function CanhRail({
  dong,
  nhan,
  children,
}: {
  dong: () => void
  nhan: string
  children: ReactNode
}) {
  const khung = useRef<HTMLDivElement>(null)
  // `dong` đổi danh tính mỗi lần layout render; neo vào ref để effect chỉ chạy
  // lúc mount/unmount — nếu không mỗi lần render lại là focus bị giật về khung.
  const dongRef = useRef(dong)
  dongRef.current = dong

  useEffect(() => {
    const truoc = document.activeElement instanceof HTMLElement ? document.activeElement : null
    khung.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dongRef.current()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (truoc && document.body.contains(truoc)) truoc.focus()
    }
  }, [])

  return (
    <div className="fixed inset-y-0 right-0 left-[68px] z-60 flex">
      <button
        type="button"
        aria-label="Đóng menu"
        onClick={dong}
        className="absolute inset-0 cursor-default bg-fg/25"
      />
      <div
        ref={khung}
        role="dialog"
        aria-label={nhan}
        tabIndex={-1}
        className="relative flex h-dvh overscroll-contain shadow-noi outline-none"
      >
        {children}
      </div>
    </div>
  )
}
