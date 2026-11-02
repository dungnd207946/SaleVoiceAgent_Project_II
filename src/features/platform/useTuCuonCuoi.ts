import { useEffect, useRef } from 'react'

/**
 * Khoảng cách tới đáy (px) vẫn coi là «đang đứng ở cuối». Nhỏ có chủ ý: một
 * nấc lăn chuột lên là ~100px, ra khỏi ngưỡng ngay — nên người dùng cuộn lên
 * dù chỉ một nấc cũng không bị kéo về. Không đặt 0 vì `scrollTop` lẻ pixel
 * trên màn HiDPI khiến đáy thật có thể cách vài phần pixel.
 */
export const NGUONG_DAY_PX = 16

/**
 * Tự cuộn một hộp xuống đáy mỗi khi nội dung bên trong đổi — NHƯNG chỉ khi
 * người dùng đang đứng ở đáy (2026-09-25, người dùng báo: tab Voice nói tới đâu
 * chữ ra tới đó mà khung không chạy theo).
 *
 * Luật: người dùng cuộn lên đọc lại ⇒ ngừng tự cuộn, không giằng co với tay họ;
 * tự cuộn về lại đáy ⇒ bật lại. Trạng thái nằm trong ref, không phải state: nó
 * đổi theo từng sự kiện cuộn, re-render cho nó là vô ích.
 *
 * Nghe DOM (`MutationObserver`) chứ không nhận dependency từ component: chữ
 * đến theo nhiều đường (partial transcript ghi đè, từng câu agent, card media,
 * dòng tool…) — một mảng dependency sẽ sót đường nào đó. Ảnh trong card đổi
 * chiều cao lúc TẢI XONG mà không đổi DOM, nên nghe thêm `load` (capture — sự
 * kiện `load` không nổi bọt).
 */
export function useTuCuonCuoi<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const oDay = useRef(true)

  useEffect(() => {
    const hop = ref.current
    if (!hop) return

    const cuonXuong = () => {
      if (oDay.current) hop.scrollTop = hop.scrollHeight
    }
    const khiCuon = () => {
      oDay.current = hop.scrollHeight - hop.scrollTop - hop.clientHeight <= NGUONG_DAY_PX
    }
    // Lăn chuột lên thì tắt NGAY, không chờ sự kiện `scroll`: nếu một câu mới
    // chen vào giữa cú lăn và sự kiện cuộn, hộp sẽ bị giật về đáy đúng lúc
    // người dùng đang kéo lên.
    const khiLan = (e: WheelEvent) => {
      if (e.deltaY < 0) oDay.current = false
    }

    const quanSat = new MutationObserver(cuonXuong)
    quanSat.observe(hop, { childList: true, subtree: true, characterData: true })
    hop.addEventListener('scroll', khiCuon, { passive: true })
    hop.addEventListener('wheel', khiLan, { passive: true })
    hop.addEventListener('load', cuonXuong, true)
    cuonXuong()

    return () => {
      quanSat.disconnect()
      hop.removeEventListener('scroll', khiCuon)
      hop.removeEventListener('wheel', khiLan)
      hop.removeEventListener('load', cuonXuong, true)
    }
  }, [])

  return ref
}
