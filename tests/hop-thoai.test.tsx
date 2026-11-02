/**
 * `HopThoai` — khung hộp thoại dùng chung trên `<dialog>` + `showModal()`.
 *
 * jsdom không có `showModal()` (shim ở `vitest.setup.ts` chỉ bật thuộc tính `open`),
 * nên nền inert và focus ban đầu KHÔNG kiểm được ở đây — đó là việc của trình duyệt.
 * Thứ kiểm được là phần component tự làm: trả focus, Esc, bấm nền, khoá đóng, lồng nhau.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { HopThoai } from '@/components/ui/HopThoai'

function MoDong({ khoaDong = false, dongBangNen = true }) {
  const [mo, setMo] = useState(false)
  return (
    <>
      <button onClick={() => setMo(true)}>Mở</button>
      {mo && (
        <HopThoai
          onDong={() => setMo(false)}
          khoaDong={khoaDong}
          dongBangNen={dongBangNen}
          aria-label="Thử"
        >
          <button>Bên trong</button>
        </HopThoai>
      )}
    </>
  )
}

/** jsdom không có `PointerEvent`: `fireEvent.pointerDown` rơi mất toạ độ. */
function nhanXuong(el: HTMLElement, clientX: number, clientY: number) {
  fireEvent(el, new MouseEvent('pointerdown', { clientX, clientY, bubbles: true }))
}

/** Giả hình học khung: jsdom trả 0 cho mọi `getBoundingClientRect`. */
function giaKhung(el: HTMLElement) {
  el.getBoundingClientRect = () =>
    ({ left: 100, right: 300, top: 100, bottom: 300, width: 200, height: 200 }) as DOMRect
}

describe('HopThoai', () => {
  it('① là <dialog> modal, có tên', async () => {
    render(<MoDong />)
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    const hop = screen.getByRole('dialog', { name: 'Thử' })
    expect(hop.tagName).toBe('DIALOG')
    expect(hop).toHaveAttribute('open')
    expect(hop).toHaveAttribute('aria-modal', 'true')
  })

  it('② đóng xong trả focus về nút đã mở nó', async () => {
    render(<MoDong />)
    const nut = screen.getByRole('button', { name: 'Mở' })
    await userEvent.click(nut)
    screen.getByRole('button', { name: 'Bên trong' }).focus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nut).toHaveFocus()
  })

  it('③ khoaDong: Esc không đóng, và Esc bị preventDefault (không sinh close request)', async () => {
    render(<MoDong khoaDong />)
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    const ev = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('④ bấm nền (ngoài khung) thì đóng; bấm trong khung thì không', async () => {
    render(<MoDong />)
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    const hop = screen.getByRole('dialog')
    giaKhung(hop)
    nhanXuong(hop, 200, 200)
    fireEvent.click(hop, { clientX: 200, clientY: 200 })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    nhanXuong(hop, 10, 10)
    fireEvent.click(hop, { clientX: 10, clientY: 10 })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('⑤ nhấn xuống TRONG khung rồi thả ra nền (bôi đen chữ) không tính là bấm nền', async () => {
    render(<MoDong />)
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    const hop = screen.getByRole('dialog')
    giaKhung(hop)
    nhanXuong(hop, 200, 200)
    fireEvent.click(hop, { clientX: 10, clientY: 10 })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('⑥ dongBangNen=false: bấm nền không đóng, Esc vẫn đóng', async () => {
    render(<MoDong dongBangNen={false} />)
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    const hop = screen.getByRole('dialog')
    giaKhung(hop)
    nhanXuong(hop, 10, 10)
    fireEvent.click(hop, { clientX: 10, clientY: 10 })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('⑦ lồng nhau: Esc chỉ đóng hộp thoại mở SAU CÙNG', async () => {
    const dongNgoai = vi.fn()
    const dongTrong = vi.fn()
    render(
      <HopThoai onDong={dongNgoai} aria-label="Ngoài">
        <HopThoai onDong={dongTrong} aria-label="Trong">
          x
        </HopThoai>
      </HopThoai>,
    )
    await userEvent.keyboard('{Escape}')
    expect(dongTrong).toHaveBeenCalledTimes(1)
    expect(dongNgoai).not.toHaveBeenCalled()
  })

  it('⑧ sự kiện cancel (close request không đến từ Esc) đi qua cùng luật', async () => {
    render(<MoDong />)
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    const ev = new Event('cancel', { cancelable: true })
    fireEvent(screen.getByRole('dialog'), ev)
    expect(ev.defaultPrevented).toBe(true)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('⑨ huỷ hộp chọn tệp (cancel nổi bọt từ <input type="file">) KHÔNG đóng hộp thoại', () => {
    const dong = vi.fn()
    render(
      <HopThoai onDong={dong} aria-label="Thử tệp">
        <input type="file" aria-label="Tệp 2" />
      </HopThoai>,
    )
    // Sự kiện `cancel` của input file trong Chrome: bubbles, không cancelable.
    fireEvent(screen.getByLabelText('Tệp 2'), new Event('cancel', { bubbles: true }))
    expect(dong).not.toHaveBeenCalled()
  })
})
