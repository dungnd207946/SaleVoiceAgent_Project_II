import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { LocStage } from '@/features/ops/components/LocStage'

function nut() {
  return screen.getByRole('button', { name: /stage/i })
}

describe('LocStage — một ô, bấm mới mở menu', () => {
  it('đóng sẵn: chỉ một nút ghi «Tất cả», không có menu', () => {
    render(<LocStage gia={undefined} doi={() => {}} />)
    expect(nut()).toHaveTextContent('Tất cả')
    expect(nut()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('bấm mở menu đủ sáu mục theo thứ tự phễu', async () => {
    render(<LocStage gia={undefined} doi={() => {}} />)
    await userEvent.click(nut())
    const muc = screen.getAllByRole('menuitemradio').map((m) => m.textContent)
    // Mỗi bậc kèm NGHĨA ngay trong mục (audit 05/10 — MQL/SQL không tự giải thích).
    expect(muc).toEqual([
      'Tất cả',
      'Leadkhách tiềm năng',
      'MQLđã quan tâm',
      'SQLđủ điều kiện mua',
      'Hẹn gặpđã có lịch hẹn',
      'Chưa phân loại',
    ])
    expect(nut()).toHaveAttribute('aria-expanded', 'true')
  })

  it('chọn một mục ⇒ gọi `doi` đúng giá trị và đóng menu', async () => {
    const doi = vi.fn()
    render(<LocStage gia={undefined} doi={doi} />)
    await userEvent.click(nut())
    await userEvent.click(screen.getByRole('menuitemradio', { name: /^SQL/ }))
    expect(doi).toHaveBeenCalledWith('sql')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('«Tất cả» ⇒ `doi(undefined)`; «Chưa phân loại» ⇒ `doi("none")`', async () => {
    const doi = vi.fn()
    render(<LocStage gia="sql" doi={doi} />)
    await userEvent.click(nut())
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'Tất cả' }))
    await userEvent.click(nut())
    await userEvent.click(screen.getByRole('menuitemradio', { name: 'Chưa phân loại' }))
    expect(doi.mock.calls).toEqual([[undefined], ['none']])
  })

  it('đang lọc ⇒ ô hiện CHÍNH chip của stage và mục đó được đánh dấu', async () => {
    render(<LocStage gia="hen_gap" doi={() => {}} />)
    expect(nut().querySelector('[data-stage="hen_gap"]')).not.toBeNull()
    await userEvent.click(nut())
    expect(screen.getByRole('menuitemradio', { name: /^Hẹn gặp/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })

  it('Esc và bấm ra ngoài đều đóng menu', async () => {
    render(
      <>
        <LocStage gia={undefined} doi={() => {}} />
        <p>ngoài</p>
      </>,
    )
    await userEvent.click(nut())
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    await userEvent.click(nut())
    await userEvent.click(screen.getByText('ngoài'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('↓/↑ đi giữa các mục, Enter chọn', async () => {
    const doi = vi.fn()
    render(<LocStage gia={undefined} doi={doi} />)
    await userEvent.click(nut())
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(doi).toHaveBeenCalledWith('mql')
  })

  it('menu PORTAL ra body — không nằm trong khối cha (tấm nền `overflow-hidden` sẽ cắt nó)', async () => {
    const { container } = render(<LocStage gia={undefined} doi={() => {}} />)
    await userEvent.click(nut())
    expect(container.contains(screen.getByRole('menu'))).toBe(false)
  })
})
