import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { NhomTab, type MucTab } from '@/components/ui/Bang'
import { panelTab } from '@/components/ui/panelTab'

type Id = 'a' | 'b' | 'c'
const MUC: readonly MucTab<Id>[] = [
  { id: 'a', nhan: 'Một' },
  { id: 'b', nhan: 'Hai' },
  { id: 'c', nhan: 'Ba' },
]

function Nhom() {
  const [mo, setMo] = useState<Id>('a')
  return <NhomTab muc={MUC} dangMo={mo} doi={setMo} nhan="Thử" />
}

describe('NhomTab — phím theo WAI-ARIA Tabs', () => {
  it('roving tabIndex: Tab vào nhóm chỉ dừng ở tab đang mở', async () => {
    render(<Nhom />)
    await userEvent.tab()
    expect(screen.getByRole('tab', { name: 'Một' })).toHaveFocus()
    await userEvent.tab()
    expect(document.body).toHaveFocus()
  })

  it('→ sang tab kề, vòng về đầu; ← ngược lại', async () => {
    render(<Nhom />)
    screen.getByRole('tab', { name: 'Một' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Hai' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Hai' })).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Ba' })).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Một' })).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Ba' })).toHaveAttribute('aria-selected', 'true')
  })

  it('Home/End về đầu/cuối', async () => {
    render(<Nhom />)
    screen.getByRole('tab', { name: 'Một' }).focus()
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'Ba' })).toHaveFocus()
    await userEvent.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: 'Một' })).toHaveFocus()
  })
})

describe('NhomTab — nối với vùng nội dung (`idPanel` + `panelTab`)', () => {
  function CoPanel() {
    const [mo, setMo] = useState<Id>('a')
    return (
      <>
        <NhomTab muc={MUC} dangMo={mo} doi={setMo} nhan="Thử" idPanel="p" />
        <div {...panelTab('p', mo)}>nội dung {mo}</div>
      </>
    )
  }

  it('tab trỏ tới panel, panel mang tên của tab đang mở và đổi theo', async () => {
    render(<CoPanel />)
    expect(screen.getByRole('tab', { name: 'Một' })).toHaveAttribute('aria-controls', 'p')
    expect(screen.getByRole('tabpanel', { name: 'Một' })).toHaveTextContent('nội dung a')
    await userEvent.click(screen.getByRole('tab', { name: 'Hai' }))
    expect(screen.getByRole('tabpanel', { name: 'Hai' })).toHaveTextContent('nội dung b')
  })
})
