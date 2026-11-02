/**
 * Thanh tiến độ nạp kiến thức trên danh sách dự án.
 *
 * Thay dòng chữ tĩnh «Đang nạp kiến thức cho agent…»: nó không phân biệt được một
 * đợt còn 30 giây với một đợt kẹt hai tiếng. Con số nằm sau cú rê chuột, thanh là
 * thứ đọc được từ xa.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { KbBadge } from '../src/features/realestate/components/KbBadge'
import type { KbStatus } from '../src/features/realestate/api'

const GOC: KbStatus = { projectCode: 'VGP', indexing: false, hasError: false, total: 0, done: 0 }

function ve(tt: KbStatus) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <KbBadge tt={tt} />
    </QueryClientProvider>,
  )
}

describe('KbBadge — thanh tiến độ', () => {
  it('đang nạp thì hiện phần trăm', () => {
    ve({ ...GOC, indexing: true, total: 659, done: 412 })
    expect(screen.getByText('63%')).toBeInTheDocument()
  })

  it('nạp đủ thì hiện 100%', () => {
    ve({ ...GOC, total: 1470, done: 1470 })
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('dự án chưa có gì để nạp thì không vẽ thanh', () => {
    const { container } = ve({ ...GOC, total: 0, done: 0 })
    expect(container.querySelector('[role="progressbar"]')).toBeNull()
  })

  it('lỗi thì hiện nút Thử lại chứ không hiện thanh', () => {
    const { container } = ve({ ...GOC, hasError: true, total: 10, done: 3 })
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
    expect(container.querySelector('[role="progressbar"]')).toBeNull()
  })

  it('con số đầy đủ nằm ở title để rê chuột mới thấy', () => {
    ve({ ...GOC, indexing: true, total: 659, done: 412 })
    expect(screen.getByRole('progressbar')).toHaveAttribute('title', '412/659 mục đã tới agent')
  })
})
