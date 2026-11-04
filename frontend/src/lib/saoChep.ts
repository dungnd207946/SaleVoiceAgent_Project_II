import { useEffect, useRef, useState } from 'react'

/** Bao lâu dấu ✓ «đã copy» đứng trước khi trở về icon copy — một nhịp cho cả portal. */
const GIU_DA_COPY = 1600

/**
 * Copy vào clipboard + biên nhận tạm. `copy` trả `true` khi copy được.
 *
 * `loiCopy`: `navigator.clipboard` không có ở ngữ cảnh không bảo mật (http:// khác
 * localhost) và trong jsdom — nơi nào chữ KHÔNG hiện sẵn trên màn thì phải báo, đừng
 * nuốt im lặng. Bấm liên tiếp thì hẹn lại từ cú bấm CUỐI, đồng hồ cũ không tắt ✓ sớm;
 * unmount thì dọn đồng hồ.
 */
export function useSaoChep() {
  const [daCopy, setDaCopy] = useState(false)
  const [loiCopy, setLoiCopy] = useState(false)
  const dongHo = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => void (dongHo.current && clearTimeout(dongHo.current)), [])

  async function copy(chu: string): Promise<boolean> {
    setLoiCopy(false)
    try {
      await navigator.clipboard.writeText(chu)
    } catch {
      setLoiCopy(true)
      return false
    }
    setDaCopy(true)
    if (dongHo.current) clearTimeout(dongHo.current)
    dongHo.current = setTimeout(() => setDaCopy(false), GIU_DA_COPY)
    return true
  }

  return { daCopy, loiCopy, copy }
}
