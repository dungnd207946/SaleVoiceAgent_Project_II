import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { NutGoogle } from '@/features/auth/components/NutGoogle'
import { server } from '../vitest.setup'

function renderVoiProvider(ui: React.ReactElement) {
  // QueryClient MỚI mỗi test: dùng chung một client là để kết quả của test trước
  // rò sang test sau qua cache, và lỗi ấy hiện ra dưới dạng một test đỏ ngẫu nhiên
  // tuỳ thứ tự chạy. `retry: false` để nhánh lỗi không chờ hai lượt.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('NutGoogle', () => {
  it('vẽ một thẻ <a> thật, không phải <button>', async () => {
    renderVoiProvider(<NutGoogle />)
    const a = await screen.findByRole('link', { name: /Google/i })
    // Phải là <a href> — OAuth cần trình duyệt RỜI KHỎI trang. Một <button> +
    // fetch sẽ đâm vào CORS của Google và không bao giờ chạy.
    expect(a).toHaveAttribute('href', '/api/v1/auth/google/start')
  })

  it('không vẽ gì khi backend báo tính năng tắt', async () => {
    let daHoi = false
    server.use(
      http.get('/api/v1/auth/providers', () => {
        daHoi = true
        return HttpResponse.json({ google: false })
      }),
    )
    const { container } = renderVoiProvider(<NutGoogle />)
    // Chờ REQUEST, không chờ DOM: component không vẽ gì ở cả hai trạng thái, nên
    // `waitFor` trên DOM khớp ngay ở lần render đang-tải và test thành vô nghĩa.
    await waitFor(() => expect(daHoi).toBe(true))
    expect(container).toBeEmptyDOMElement()
  })

  it('không vẽ gì trong lúc đang hỏi backend', () => {
    // Vẽ chỗ trống rồi nhét nút vào sau là để một nút nhảy ra dưới ngón tay
    // người đang bấm «Đăng nhập».
    const { container } = renderVoiProvider(<NutGoogle />)
    expect(container).toBeEmptyDOMElement()
  })
})
