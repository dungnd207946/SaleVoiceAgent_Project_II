import { useEffect, type RefObject } from 'react'

/**
 * Khung bật lên đang mở (`mo`) thì đóng khi bấm chuột RA NGOÀI `ref` hoặc nhấn Escape.
 *
 * `mousedown` chứ không `click`: click vào một chỗ khác sẽ chạy hành động của nó TRƯỚC
 * rồi mới tới đây, khung đóng trễ một nhịp trông như bị kẹt. `dong` nhận chính sự kiện —
 * Escape thường trả focus về nút mở, còn bấm ra ngoài thì không kéo focus khỏi chỗ người
 * dùng vừa chỉ tay vào.
 */
export function useDongKhiRaNgoai(
  ref: RefObject<HTMLElement | null>,
  mo: boolean,
  dong: (e: MouseEvent | KeyboardEvent) => void,
): void {
  useEffect(() => {
    if (!mo) return
    const ngoai = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) dong(e)
    }
    const phim = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dong(e)
    }
    document.addEventListener('mousedown', ngoai)
    document.addEventListener('keydown', phim)
    return () => {
      document.removeEventListener('mousedown', ngoai)
      document.removeEventListener('keydown', phim)
    }
  }, [ref, mo, dong])
}
