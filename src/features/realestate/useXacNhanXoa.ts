/**
 * Focus cho hộp xác nhận xoá INLINE (`role="alertdialog"` dựng ngay trong trang, không
 * phải overlay — nên không dùng `HopThoai`). Theo APG, ba chặng:
 * - hộp hiện ra → focus vào nút ÍT phá huỷ nhất (Huỷ), không để người dùng Enter nhầm;
 * - Huỷ → trả focus về nút xoá đã mở hộp (nếu hàng đó còn trong DOM);
 * - xoá xong (`daXoa`, hàng biến mất, nút xoá đi theo) → focus về `dich` (nút «Thêm …» của
 *   bảng) thay vì để rơi về `<body>`.
 *
 * Nút xoá lấy từ `document.activeElement` lúc bấm: `NutIcon` không đưa sự kiện ra ngoài.
 * Safari không focus `<button>` khi bấm chuột — ca đó nút không được nhớ, Huỷ chỉ đóng hộp.
 */
import { useEffect, useId, useRef, useState } from 'react'

export function useXacNhanXoa<T>() {
  const [sap, setSap] = useState<T | null>(null)
  const nutXoa = useRef<HTMLElement | null>(null)
  const huyRef = useRef<HTMLButtonElement>(null)
  const dichEl = useRef<HTMLElement | null>(null)
  const idTieuDe = useId()
  const idMoTa = useId()

  useEffect(() => {
    if (sap !== null) huyRef.current?.focus()
  }, [sap])

  return {
    sap,
    huyRef,
    /** Callback ref (không phải `useRef`): nút «Thêm …» là `<button>` hay `<Link>` tuỳ tab. */
    dich(el: HTMLElement | null) {
      dichEl.current = el
    },
    idTieuDe,
    idMoTa,
    hoi(x: T) {
      const dang = document.activeElement
      nutXoa.current = dang instanceof HTMLElement && dang !== document.body ? dang : null
      setSap(x)
    },
    boQua() {
      setSap(null)
      if (nutXoa.current?.isConnected) nutXoa.current.focus()
    },
    daXoa() {
      setSap(null)
      dichEl.current?.focus()
    },
  }
}
