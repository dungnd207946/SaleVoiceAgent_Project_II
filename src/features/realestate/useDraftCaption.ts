/**
 * Sinh mô tả cho ảnh vừa tải lên, TRƯỚC khi hàng `media` tồn tại.
 *
 * Poll có điều kiện dừng: `success`/`failed` hoặc hết `TRAN_LAN`. Không dừng thì một
 * job kẹt `queued` (worker chết) thành một vòng lặp gọi API vô hạn.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { docCaptionNhap, taoCaptionNhap } from './api'

const NHIP_MS = 2000
const TRAN_LAN = 45

export function useDraftCaption(onCaption: (s: string) => void) {
  const [running, setRunning] = useState(false)
  const huy = useRef(false)
  const nhan = useRef(onCaption)
  nhan.current = onCaption

  useEffect(() => {
    huy.current = false
    return () => {
      huy.current = true
    }
  }, [])

  const sinh = useCallback(async (mediaUrl: string, contentType = 'image', category = '') => {
    if (!mediaUrl) return
    setRunning(true)
    try {
      const { jobId } = await taoCaptionNhap(mediaUrl, contentType, category)
      for (let i = 0; i < TRAN_LAN; i++) {
        await new Promise((r) => setTimeout(r, NHIP_MS))
        if (huy.current) return
        const ra = await docCaptionNhap(jobId)
        if (ra.state === 'success') {
          if (ra.caption) nhan.current(ra.caption)
          return
        }
        if (ra.state === 'failed') return
      }
    } catch {
      // Chú thích nháp là tiện thêm, không phải dữ liệu — hỏng thì im lặng bỏ,
      // người dùng vẫn tự gõ được.
    } finally {
      if (!huy.current) setRunning(false)
    }
  }, [])

  return { sinh, running }
}
