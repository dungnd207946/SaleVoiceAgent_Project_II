import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Sao } from '@/components/ui/Sao'

describe('Sao', () => {
  it('tô đủ 5 sao, đúng số lượng tô theo gia', () => {
    const { container } = render(<Sao gia={3} />)
    const sao = container.querySelectorAll('[data-sao]')
    expect(sao).toHaveLength(5)
    expect(container.querySelectorAll('[data-sao="on"]')).toHaveLength(3)
    expect(container.querySelectorAll('[data-sao="off"]')).toHaveLength(2)
  })

  it('gia=5 tô hết, gia=0 không tô cái nào', () => {
    const { container: c5 } = render(<Sao gia={5} />)
    expect(c5.querySelectorAll('[data-sao="on"]')).toHaveLength(5)

    const { container: c0 } = render(<Sao gia={0} />)
    expect(c0.querySelectorAll('[data-sao="on"]')).toHaveLength(0)
  })

  it('gia lẻ tô một phần ngôi kế tiếp — 3.58 ⇒ 3 đầy + 1 ở 58%', () => {
    const { container } = render(<Sao gia={3.58} />)
    expect(container.querySelectorAll('[data-sao]')).toHaveLength(5)
    expect(container.querySelectorAll('[data-sao="on"]')).toHaveLength(3)
    expect(container.querySelectorAll('[data-sao="off"]')).toHaveLength(1)

    const le = container.querySelectorAll('[data-sao="phan"]')
    expect(le).toHaveLength(1)
    const leDau = le[0]!
    expect(leDau.getAttribute('data-phan')).toBe('58')
    // Lớp phủ cắt đúng 58% bề rộng — chỗ hiệu ứng thật sự nằm.
    expect(leDau.querySelector<HTMLElement>('.overflow-hidden')!.style.width).toBe('58%')
  })

  it('phần lẻ sát mép về đầy/rỗng, không vẽ lớp phủ 100% hay 0%', () => {
    const { container: cGanDay } = render(<Sao gia={3.998} />)
    expect(cGanDay.querySelectorAll('[data-sao="on"]')).toHaveLength(4)
    expect(cGanDay.querySelectorAll('[data-sao="phan"]')).toHaveLength(0)

    const { container: cGanRong } = render(<Sao gia={3.002} />)
    expect(cGanRong.querySelectorAll('[data-sao="on"]')).toHaveLength(3)
    expect(cGanRong.querySelectorAll('[data-sao="phan"]')).toHaveLength(0)
  })

  it('có tên bằng chữ cho trình đọc màn hình — số lẻ theo vi-VN', () => {
    render(<Sao gia={4.33} />)
    expect(screen.getByRole('img', { name: '4,33 trên 5 sao' })).toBeInTheDocument()
  })

  it('sao rỗng dùng viền ô nhập (n6, 3,23:1), không dùng border-strong (n5, 1,39:1)', () => {
    const { container } = render(<Sao gia={1} />)
    const rong = container.querySelector('[data-sao="off"] svg')!
    expect(rong.getAttribute('class')).toContain('text-border-field')
  })
})
