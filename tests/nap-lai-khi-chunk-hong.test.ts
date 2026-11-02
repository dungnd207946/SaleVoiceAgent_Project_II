/**
 * Nạp lại trang khi một chunk lazy-load 404 sau deploy.
 *
 * Sự cố thật 2026-08-25 (UAT, Safari): tab đang mở bundle CŨ, deploy thay
 * container ⇒ mọi chunk hash cũ biến mất ⇒ bấm sang `/convos` là
 * `import('/assets/convos-<hash cũ>.js')` 404 ⇒ «Importing a module script
 * failed» rơi vào ErrorComponent mặc định của TanStack. Vite phát sự kiện
 * `vite:preloadError` đúng lúc đó (cancelable; `preventDefault()` chặn ném
 * lại) — app chưa từng lắng nghe.
 *
 * Không dựng router thật ở đây: thứ cần canh là HÀNH VI của bộ nghe sự kiện,
 * còn việc Vite có phát sự kiện hay không là hợp đồng của Vite (đã grep thấy
 * `vite:preloadError` trong bundle build).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  datNapLaiKhiChunkHong,
  GIAN_CACH_NAP_LAI_MS,
  KHOA_LAN_NAP_LAI,
} from '../src/lib/napLaiKhiChunkHong'

function banSuKienChunkHong(): Event {
  // Vite dispatch với `cancelable: true` — thiếu cờ này thì `preventDefault()`
  // không ghi được vào `defaultPrevented` và bài test xanh nhầm.
  const e = new Event('vite:preloadError', { cancelable: true })
  window.dispatchEvent(e)
  return e
}

describe('nạp lại trang khi chunk hỏng sau deploy', () => {
  let go: (() => void) | undefined

  afterEach(() => {
    go?.()
    go = undefined
    sessionStorage.removeItem(KHOA_LAN_NAP_LAI)
  })

  it('lần đầu chunk hỏng: chặn lỗi ném ra và nạp lại trang đúng một lần', () => {
    const napLai = vi.fn()
    go = datNapLaiKhiChunkHong(napLai)

    const e = banSuKienChunkHong()

    expect(napLai).toHaveBeenCalledTimes(1)
    // Chặn Vite ném lại lỗi — nếu không, ErrorComponent chớp lên ngay trước
    // khi trang kịp nạp lại.
    expect(e.defaultPrevented).toBe(true)
    expect(sessionStorage.getItem(KHOA_LAN_NAP_LAI)).not.toBeNull()
  })

  it('vừa nạp lại xong mà chunk vẫn hỏng: KHÔNG nạp lại nữa, để lỗi hiện', () => {
    // Bản deploy mới tự nó thiếu chunk ⇒ nạp lại vô hạn là đổi màn lỗi lấy
    // một tab quay mãi. Sau một lần nạp lại trong giãn cách, lỗi phải đi tiếp
    // tới ErrorComponent như thường.
    sessionStorage.setItem(KHOA_LAN_NAP_LAI, String(Date.now() - 1_000))
    const napLai = vi.fn()
    go = datNapLaiKhiChunkHong(napLai)

    const e = banSuKienChunkHong()

    expect(napLai).not.toHaveBeenCalled()
    expect(e.defaultPrevented).toBe(false)
  })

  it('qua đủ giãn cách thì deploy lần sau lại được nạp lại', () => {
    sessionStorage.setItem(KHOA_LAN_NAP_LAI, String(Date.now() - GIAN_CACH_NAP_LAI_MS - 1))
    const napLai = vi.fn()
    go = datNapLaiKhiChunkHong(napLai)

    banSuKienChunkHong()

    expect(napLai).toHaveBeenCalledTimes(1)
  })

  it('gỡ bộ nghe xong thì sự kiện không còn nạp lại', () => {
    const napLai = vi.fn()
    datNapLaiKhiChunkHong(napLai)()

    banSuKienChunkHong()

    expect(napLai).not.toHaveBeenCalled()
  })

  /**
   * `main.tsx` có side effect (createRoot, MSW) nên không import được trong
   * jsdom — canh bằng quét văn bản, cùng lối `o-chon`/`vien-tran`. Một bộ nghe
   * đúng mà không ai cài thì sự cố 2026-08-25 lặp lại nguyên xi.
   */
  it('main.tsx cài bộ nạp lại', () => {
    const main = readFileSync(resolve(__dirname, '../src/main.tsx'), 'utf8')
    expect(main).toMatch(/datNapLaiKhiChunkHong\(\)/)
  })
})
