import { StrictMode } from 'react'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { docNhanKichBan } from '@/features/ops/nhanKichBan'

function boot(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        <LangProvider>
          <RouterProvider router={router} />
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
}

// seq của lượt assistant gắn nhãn trong msw.ts (phiên s-anh-1)
const SEQ = 3

describe('docNhanKichBan', () => {
  it('meta hỏng / không nhãn → null', () => {
    for (const m of [
      null,
      'x',
      [],
      {},
      { playbook: 'x' },
      { playbook: { dat: true } },
      { playbook: { nut: 3 } },
    ])
      expect(docNhanKichBan(m)).toBeNull()
  })
  it('đọc đủ trường, bỏ phần tử không phải chuỗi', () => {
    const n = docNhanKichBan({
      playbook: {
        nut: 'che_dat',
        dat: false,
        thieu: ['a', 1],
        vi_pham_cam: ['b'],
        da_lam: ['c'],
        thieu_du_lieu: true,
        jev_nut: 'che_xa',
        do_tin: 0.8,
        buoc: 'b1',
      },
    })
    expect(n).toEqual({
      nut: 'che_dat',
      buoc: 'b1',
      dat: false,
      loi: null,
      daLam: ['c'],
      thieu: ['a'],
      viPhamCam: ['b'],
      thieuDuLieu: true,
      jevNut: 'che_xa',
      doTin: 0.8,
    })
  })
})

describe('màn hội thoại — nút kịch bản', () => {
  it('thẻ nút dưới tin agent, bấm mở chi tiết, link sang /kich-ban', async () => {
    boot('/convos/0912448111?session=s-anh-1')
    const the = await screen.findByTestId('the-nut')
    // Tên tình huống như `/kich-ban` in (từ `/playbook`), KHÔNG mã thô `che_dat` — và kết
    // quả bằng chữ, không ✓/✗ (audit 05/10). Mã bước `b1` không có trong nút ⇒ không in.
    const link = await within(the).findByRole('link', { name: 'Khách chê đắt' })
    expect(link.getAttribute('href')).toContain('/kich-ban?nut=che_dat')
    expect(the).toHaveTextContent('Chưa đạt')
    expect(the).not.toHaveTextContent('che_dat')
    expect(the).not.toHaveTextContent('b1')
    fireEvent.click(within(the).getByRole('button', { name: /chi tiết/i }))
    expect(within(the).getByText(/kết nối lợi ích/)).toBeInTheDocument()
  })

  it('?seq= tô sáng đúng tin', async () => {
    boot(`/convos/0912448111?session=s-anh-1&seq=${SEQ}`)
    const tin = await screen.findByTestId(`tin-${SEQ}`)
    await waitFor(() => expect(tin).toHaveAttribute('data-to-sang', 'true'))
  })
})
