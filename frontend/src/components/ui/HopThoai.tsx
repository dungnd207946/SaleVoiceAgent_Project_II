/**
 * Khung hộp thoại DÙNG CHUNG — `<dialog>` + `showModal()`.
 *
 * Trước 2026-10-05 portal có 25 khung `role="dialog"` tự dựng (`fixed inset-0 z-70` +
 * nút backdrop + `<div role="dialog">`). 0/25 giữ được Tab bên trong — Tab ba lần là
 * focus đã ra tới rail — và phần lớn đóng xong thả focus về `<body>`. Audit impeccable
 * 05/10, P1 #1.
 *
 * Trình duyệt lo phần khó, miễn phí:
 * - nền INERT: Tab không thoát ra ngoài, trình đọc màn hình không đọc trang phía sau;
 * - top layer: khỏi đua `z-index`, khỏi `createPortal` chỉ để thoát stacking context.
 *
 * Component lo ba việc trình duyệt KHÔNG làm cho React:
 * - **Trả focus.** Bước trả focus của trình duyệt chỉ chạy khi `close()`; React gỡ
 *   `<dialog>` khỏi DOM thì không có bước nào chạy. Nên nhớ `activeElement` lúc mở,
 *   rồi `close()` + `focus()` trong cleanup của layout effect — lúc đó `<dialog>` vẫn
 *   còn trong DOM.
 * - **Esc qua listener ở `document`, có `preventDefault`.** Không dựa vào sự kiện
 *   `cancel`: nó để `<dialog>` tự đóng mà React không biết, và Chrome bỏ qua
 *   `preventDefault()` của `cancel` ở lần Esc thứ hai không có cú bấm xen giữa — đúng
 *   lúc `khoaDong` cần giữ hộp thoại lại. Chặn ở `keydown` thì không có close request
 *   nào sinh ra. Hộp thoại lồng nhau: chỉ cái mở SAU CÙNG nhận Esc (`NGAN`).
 * - **Bấm nền thì đóng.** Cú bấm vào `::backdrop` tới `<dialog>` với toạ độ nằm ngoài
 *   khung. Phải nhấn XUỐNG ngoài khung nữa: bôi đen chữ trong ô rồi thả chuột ra nền
 *   không được tính là bấm nền.
 *
 * Focus ban đầu: `showModal()` tự đưa focus vào phần tử focus được đầu tiên. Màn nào
 * muốn focus chỗ khác (ô nhập, nút Copy) cứ giữ `useEffect(() => ref.current?.focus())`
 * như cũ — `showModal()` chạy ở layout effect, TRƯỚC mọi `useEffect` của con.
 *
 * `className` THAY toàn bộ lớp của `<dialog>`, không cộng thêm: hai lớp cùng thuộc tính
 * (`max-h-*`, `bg-*`) trong một chuỗi thì Tailwind không hứa cái nào thắng. Hộp thoại
 * giữa màn ghép `KHUNG_HOP_THOAI` + bề rộng của mình; slide-over và lightbox tự khai
 * trọn bộ. `<dialog>` CHÍNH LÀ khung — không có `<div>` bọc thứ hai.
 */
import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'

/**
 * Khung của mọi hộp thoại giữa màn — chép từ 13 bản cũ, giờ ở một chỗ. Ghép thêm
 * `max-w-[…]`.
 * - `m-auto`: preflight của Tailwind đặt `margin: 0` cho mọi phần tử, tức xoá đúng cái
 *   `margin: auto` mà trình duyệt dùng để căn giữa `<dialog>`.
 * - `w-[calc(100%-2rem)]`: lề 16px hai bên ở điện thoại (bản cũ nhờ `px-4` của lớp bọc).
 * - `max-h-[calc(100dvh-2rem)]` + `overflow-y-auto`: dialog cao hơn màn thì cuộn bên trong
 *   — landscape mobile 667×375 từng cắt mất hàng nút.
 * - `text-fg`: UA đặt `color: CanvasText` cho `<dialog>`, chữ không thừa hưởng màu trang.
 */
export const KHUNG_HOP_THOAI =
  'm-auto w-[calc(100%-2rem)] max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-lg border border-border-field bg-surface p-5 text-fg shadow-hop-thoai backdrop:bg-panel/45'

/** Hộp thoại đang mở, theo thứ tự mở. Chỉ cái cuối nhận Esc. */
const NGAN: HTMLDialogElement[] = []

/**
 * Hộp thoại nằm trên cùng: cái mở sau cùng, trừ khi nó là TỔ TIÊN của một cái khác
 * trong ngăn — hai hộp lồng nhau mount cùng một lượt thì con chạy effect trước cha.
 */
function tren(): HTMLDialogElement | undefined {
  return NGAN.filter((d) => !NGAN.some((k) => k !== d && d.contains(k))).at(-1)
}

function ngoaiKhung(el: HTMLElement, x: number, y: number): boolean {
  const r = el.getBoundingClientRect()
  return x < r.left || x > r.right || y < r.top || y > r.bottom
}

export function HopThoai({
  onDong,
  khoaDong = false,
  dongBangNen = true,
  className = KHUNG_HOP_THOAI,
  children,
  ...aria
}: {
  readonly onDong: () => void
  /** Đang gửi (hoặc bí mật chưa lưu): Esc và bấm nền KHÔNG đóng. */
  readonly khoaDong?: boolean
  /** `false`: bấm nền không đóng, Esc vẫn đóng. */
  readonly dongBangNen?: boolean
  readonly className?: string
  readonly children: ReactNode
  readonly 'aria-labelledby'?: string
  readonly 'aria-label'?: string
  readonly 'aria-describedby'?: string
  readonly role?: 'dialog' | 'alertdialog'
  readonly 'data-testid'?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const nhanNgoai = useRef(false)
  // Ref cho hai giá trị listener đọc — để listener Esc gắn MỘT lần, không gỡ/gắn lại
  // mỗi lần `onDong` là một arrow function mới.
  const dong = useRef({ onDong, khoaDong })
  dong.current = { onDong, khoaDong }

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const truoc = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!el.open) el.showModal()
    NGAN.push(el)
    return () => {
      NGAN.splice(NGAN.indexOf(el), 1)
      if (el.open) el.close()
      if (truoc?.isConnected) truoc.focus()
    }
  }, [])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape' || tren() !== ref.current) return
      e.preventDefault()
      if (!dong.current.khoaDong) dong.current.onDong()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  return (
    <dialog
      ref={ref}
      aria-modal="true"
      {...aria}
      className={className}
      onCancel={(e) => {
        // `<input type="file">` bắn `cancel` khi người dùng ĐÓNG hộp chọn tệp mà không
        // chọn gì, và sự kiện đó NỔI BỌT tới đây — không lọc thì huỷ chọn tệp là đóng
        // luôn cả hộp thoại. Chỉ `cancel` của chính `<dialog>` mới là close request.
        if (e.target !== e.currentTarget) return
        // Close request không đến từ Esc (cử chỉ back trên Android): cùng luật.
        e.preventDefault()
        if (!khoaDong) onDong()
      }}
      onPointerDown={(e) => {
        nhanNgoai.current =
          e.target === e.currentTarget && ngoaiKhung(e.currentTarget, e.clientX, e.clientY)
      }}
      onClick={(e) => {
        if (!dongBangNen || khoaDong || !nhanNgoai.current) return
        if (e.target === e.currentTarget && ngoaiKhung(e.currentTarget, e.clientX, e.clientY))
          onDong()
      }}
    >
      {children}
    </dialog>
  )
}
