/**
 * `useTuCuonCuoi` — khung hội thoại `/thu-agent` tự chạy theo chữ mới, trừ khi
 * người dùng đang cuộn lên đọc lại.
 *
 * jsdom không có bố cục: `scrollHeight`/`clientHeight` luôn 0. Nên hình học
 * được GIẢ trên chính phần tử (chiều cao nội dung = số dòng × 100px, khung
 * 300px), còn `scrollTop` là thuộc tính ghi được thật của jsdom.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { useTuCuonCuoi } from '@/features/platform/useTuCuonCuoi'

const CAO_DONG = 100
const CAO_KHUNG = 300

let themDong: () => void = () => {}

function Khung() {
  const hop = useTuCuonCuoi<HTMLDivElement>()
  const [dong, setDong] = useState(5)
  themDong = () => setDong((n) => n + 1)
  return (
    <div
      data-testid="hop"
      ref={(el) => {
        hop.current = el
        if (!el) return
        Object.defineProperty(el, 'clientHeight', { configurable: true, value: CAO_KHUNG })
        Object.defineProperty(el, 'scrollHeight', {
          configurable: true,
          get: () => el.children.length * CAO_DONG,
        })
      }}
    >
      {Array.from({ length: dong }, (_, i) => (
        <p key={i}>dòng {i}</p>
      ))}
    </div>
  )
}

const day = (el: HTMLElement) => el.scrollHeight - el.clientHeight

describe('useTuCuonCuoi', () => {
  it('đang ở đáy ⇒ chữ mới ra thì khung cuộn theo', async () => {
    render(<Khung />)
    const hop = screen.getByTestId('hop')
    expect(hop.scrollTop).toBe(hop.scrollHeight)

    await act(async () => themDong())
    // Hook gán scrollTop = scrollHeight; trình duyệt thật tự kẹp về đáy.
    expect(hop.scrollTop).toBe(6 * CAO_DONG)
    expect(hop.scrollTop).toBeGreaterThanOrEqual(day(hop))
  })

  it('người dùng lăn chuột lên ⇒ chữ mới KHÔNG kéo khung về đáy', async () => {
    render(<Khung />)
    const hop = screen.getByTestId('hop')

    fireEvent.wheel(hop, { deltaY: -100 })
    hop.scrollTop = 50
    fireEvent.scroll(hop)

    await act(async () => themDong())
    await act(async () => themDong())
    expect(hop.scrollTop).toBe(50)
  })

  it('kéo thanh cuộn lên (không lăn chuột) cũng tắt tự cuộn', async () => {
    render(<Khung />)
    const hop = screen.getByTestId('hop')

    hop.scrollTop = 0
    fireEvent.scroll(hop)

    await act(async () => themDong())
    expect(hop.scrollTop).toBe(0)
  })

  it('cuộn về lại đáy ⇒ tự cuộn bật lại', async () => {
    render(<Khung />)
    const hop = screen.getByTestId('hop')

    fireEvent.wheel(hop, { deltaY: -100 })
    hop.scrollTop = 0
    fireEvent.scroll(hop)
    await act(async () => themDong())
    expect(hop.scrollTop).toBe(0)

    hop.scrollTop = day(hop)
    fireEvent.scroll(hop)
    await act(async () => themDong())
    expect(hop.scrollTop).toBeGreaterThanOrEqual(day(hop))
  })
})
