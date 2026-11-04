import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ChipStage, TomTatLead } from '@/features/ops/components/ChipStage'
import { laLocStage, nhanDoiTuong } from '@/features/ops/lead'

describe('ChipStage', () => {
  it('bốn bậc hiện đúng nhãn và lớp màu của bậc', () => {
    render(
      <>
        <ChipStage stage="lead" />
        <ChipStage stage="mql" />
        <ChipStage stage="sql" />
        <ChipStage stage="hen_gap" />
      </>,
    )
    expect(screen.getByText('Lead')).toHaveClass('bg-lead-1-bg')
    expect(screen.getByText('MQL')).toHaveClass('bg-lead-2-bg')
    expect(screen.getByText('SQL')).toHaveClass('bg-lead-3-bg')
    expect(screen.getByText('Hẹn gặp')).toHaveClass('bg-lead-4-bg')
  })

  it('stage LẠ hiện nguyên văn bằng chip trung tính, không crash', () => {
    render(<ChipStage stage="chot" />)
    expect(screen.getByText('chot')).toHaveClass('bg-badge-neutral-bg')
  })
})

describe('TomTatLead', () => {
  it('không có stage ⇒ chữ «Chưa phân loại», không chip', () => {
    render(<TomTatLead stage={null} diem={null} doiTuong={null} />)
    expect(screen.getByText('Chưa phân loại')).toBeInTheDocument()
  })

  it('đủ ba trường ⇒ chip + «90 điểm» + «· Khách mua»', () => {
    const { container } = render(<TomTatLead stage="hen_gap" diem={90} doiTuong="end_user" />)
    expect(screen.getByText('Hẹn gặp')).toBeInTheDocument()
    expect(container.textContent).toContain('90điểm')
    expect(container.textContent).toContain('· Khách mua')
  })

  it('có stage nhưng thiếu điểm và đối tượng ⇒ chỉ chip, không «null»/«·» thừa', () => {
    const { container } = render(<TomTatLead stage="sql" diem={null} doiTuong={undefined} />)
    expect(container.textContent).toBe('SQL')
  })

  it('có đối tượng mà thiếu điểm ⇒ không mở đầu bằng «·»', () => {
    const { container } = render(<TomTatLead stage="sql" diem={null} doiTuong="broker" />)
    expect(container.textContent).toBe('SQLMôi giới')
  })
})

describe('lead.ts', () => {
  it('nhanDoiTuong dịch hai mã đã biết, giữ nguyên mã lạ', () => {
    expect(nhanDoiTuong('end_user')).toBe('Khách mua')
    expect(nhanDoiTuong('broker')).toBe('Môi giới')
    expect(nhanDoiTuong('investor')).toBe('investor')
  })

  it('laLocStage chỉ nhận bốn bậc + none', () => {
    expect(['lead', 'mql', 'sql', 'hen_gap', 'none'].every(laLocStage)).toBe(true)
    expect(laLocStage('xyz')).toBe(false)
    expect(laLocStage(undefined)).toBe(false)
  })
})
