import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'
import { routeTree } from '../src/routeTree.gen'
import { LangProvider } from '../src/i18n'
import { FAKE_KICH_BAN } from '../src/features/kich-ban/msw'

function boot(path = '/kich-ban') {
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
  return router
}

describe('bảng chi tiết nút', () => {
  it('hiện dấu hiệu / làm / cấm / nút kế tiếp / số đo — bằng chữ viết cho người đọc', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    const h = FAKE_KICH_BAN.nodes.find((x) => x.id === 'che_dat')!.hien!
    expect(within(b).getByText('Khách chê đắt')).toBeInTheDocument()
    expect(within(b).getByText(h.dau_hieu![1]!)).toBeInTheDocument()
    expect(within(b).getByText(h.lam![1]!)).toBeInTheDocument()
    expect(within(b).getByText(h.cam![1]!)).toBeInTheDocument()
    expect(within(b).getByText(h.khi_thieu!)).toBeInTheDocument()
    // chữ gốc viết cho LLM (IN HOA nhấn mạnh, mã tool) không lọt ra
    expect(b.textContent).not.toMatch(/LẦN ĐẦU|NGAY|escalate|→/)
    expect(
      within(b).getByRole('button', { name: /Chê đắt lần hai.*gặp lần 2/ }),
    ).toBeInTheDocument()
    expect(within(b).getByText('71%')).toBeInTheDocument()
  })

  it('số đo «hay phạm» nói bằng đúng chữ của mục «Không được làm»', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    const h = FAKE_KICH_BAN.nodes.find((x) => x.id === 'che_dat')!.hien!
    expect(
      within(b).getByText(new RegExp(`Hay phạm điều cấm: ${h.cam![2]!} \\(3 lần\\)`)),
    ).toBeInTheDocument()
  })

  it('nút chưa có bản cho người đọc: dịch chữ gốc — tên kỹ năng thay mã tool, không snake_case', async () => {
    boot('/kich-ban?nut=chot')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(
      within(b).getByText('chốt khách đủ 4 bước, thông tin cọc chỉ từ tài liệu'),
    ).toBeInTheDocument()
    expect(within(b).getByText('Tra tài liệu của workspace')).toBeInTheDocument()
    expect(within(b).getByText('Chốt')).toBeInTheDocument()
    expect(b.textContent).not.toMatch(/kb_search|search_units|luong\b|san_sang_coc/)
  })

  it('đến từ: nút đích liệt kê nút dẫn tới nó', async () => {
    boot('/kich-ban?nut=chuyen_that')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByRole('button', { name: /Chốt căn.*gặp lần 2/ })).toBeInTheDocument()
  })

  it('bước của nút luồng', async () => {
    boot('/kich-ban?nut=chot')
    const b = await screen.findByTestId('bang-chi-tiet')
    const n = FAKE_KICH_BAN.nodes.find((x) => x.id === 'chot')!
    expect(within(b).getByText(new RegExp(n.buoc[0]!.lam))).toBeInTheDocument()
  })

  it('danh sách lượt + lọc không đạt + link sang phiên', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(await within(b).findAllByTestId('luot-nut')).toHaveLength(2)
    fireEvent.click(within(b).getByRole('checkbox', { name: 'Chỉ lượt không đạt' }))
    await waitFor(() => expect(within(b).getAllByTestId('luot-nut')).toHaveLength(1))
    const link = within(b).getByRole('link', { name: /Mở phiên/ })
    expect(link.getAttribute('href')).toContain('/convos/0912448111')
    expect(link.getAttribute('href')).toContain('session=s-anh')
    expect(link.getAttribute('href')).toContain('seq=')
  })

  it('bấm nút kế tiếp chuyển ?nut=', async () => {
    const router = boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    fireEvent.click(within(b).getByRole('button', { name: /Chê đắt lần hai/ }))
    await waitFor(() =>
      expect(router.state.location.search).toMatchObject({ nut: 'che_dat_downsell' }),
    )
  })

  it('đổi nút thì ô "Chỉ lượt không đạt" trở về tắt', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    const o = within(b).getByRole('checkbox', { name: 'Chỉ lượt không đạt' })
    fireEvent.click(o)
    expect(o).toBeChecked()
    fireEvent.click(within(b).getByRole('button', { name: /Chê đắt lần hai/ }))
    await waitFor(() =>
      expect(within(b).getByRole('checkbox', { name: 'Chỉ lượt không đạt' })).not.toBeChecked(),
    )
  })

  it('nút không còn trong kịch bản → bảng tối giản + danh sách lượt', async () => {
    boot('/kich-ban?nut=nut_cu')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('nut_cu')).toBeInTheDocument()
    expect(await within(b).findByText(/Chưa có lượt nào/)).toBeInTheDocument()
  })
})
