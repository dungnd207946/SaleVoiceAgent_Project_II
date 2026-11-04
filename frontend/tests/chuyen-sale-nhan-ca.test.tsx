/**
 * «Chuyển sale» — đổi trạng thái ca (harden sau critique 05/10).
 *
 * Lỗi gốc: ở tab «Chưa liên hệ», nhận một ca thì ca đó rời trang, khung chi tiết
 * desktop rơi về `items[0]`. Dữ liệu giả có hai ca CÙNG một khách (12 và 13), nên
 * tiêu đề không đổi, nút «Nhận ca này» không đổi chỗ và vẫn giữ focus — Enter lần
 * hai nhận luôn ca kia mà không có gì báo.
 *
 * Mỗi bài tự trả dữ liệu giả về như cũ (Hoàn tác) hoặc không ghi gì (PATCH lỗi):
 * `CA_GIA` là trạng thái module, dùng chung giữa các bài trong file.
 */
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

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

/** Thân các PATCH gửi tới `/escalations/:id`, theo thứ tự. */
const NGHE: Array<(a: { request: Request }) => void> = []
function theoDoiPatch() {
  const goi = vi.fn<(id: string, than: unknown) => void>()
  const nghe = ({ request }: { request: Request }) => {
    if (request.method !== 'PATCH' || !request.url.includes('/escalations/')) return
    const id = request.url.split('/').pop() ?? ''
    void request
      .clone()
      .json()
      .then((than) => goi(id, than))
  }
  server.events.on('request:start', nghe)
  NGHE.push(nghe)
  return goi
}

afterEach(() => {
  NGHE.forEach((nghe) => server.events.removeListener('request:start', nghe))
  NGHE.length = 0
})

const tieuDeCa = () => screen.getByRole('heading', { level: 2, name: 'Nguyễn Minh Anh' })

describe('Chuyển sale — nhận ca', () => {
  it('nhận xong vẫn đứng ở CA VỪA NHẬN; Enter lần hai không nhận thêm ca nào', async () => {
    const patch = theoDoiPatch()
    boot('/chuyen-sale?tab=new')

    const nut = await screen.findByRole('button', { name: 'Nhận ca này' })
    nut.focus()
    await userEvent.keyboard('{Enter}')

    expect(await screen.findByText('Đã nhận ca Nguyễn Minh Anh.')).toHaveAttribute('role', 'status')
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    const [idNhan] = patch.mock.calls[0]!

    // Khung chi tiết là ca vừa nhận, ở trạng thái mới — không phải ca kế tiếp
    // mang cùng nút «Nhận ca này».
    expect(screen.queryByRole('button', { name: 'Nhận ca này' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Đánh dấu xong' })).toBeInTheDocument()
    // Focus về tiêu đề ca — Enter ở đó không bấm gì.
    await waitFor(() => expect(document.activeElement).toBe(tieuDeCa()))
    await userEvent.keyboard('{Enter}')
    expect(patch).toHaveBeenCalledTimes(1)

    // Ca còn lại vẫn nằm trong «Chưa liên hệ».
    await waitFor(() => expect(screen.getByText('1–1 / 1')).toBeInTheDocument())

    // Hoàn tác: đúng ca đó quay về `new`, nút «Nhận ca này» trở lại.
    await userEvent.click(screen.getByRole('button', { name: 'Hoàn tác' }))
    expect(
      await screen.findByText('Đã trả ca Nguyễn Minh Anh về «Chưa liên hệ».'),
    ).toBeInTheDocument()
    expect(patch).toHaveBeenCalledTimes(2)
    expect(patch.mock.calls[1]).toEqual([idNhan, { trangThai: 'new' }])
    expect(await screen.findByRole('button', { name: 'Nhận ca này' })).toBeInTheDocument()
  })

  it('chọn hàng khác thì thôi ghim ca vừa đổi và thôi báo', async () => {
    boot('/chuyen-sale?ca=15')
    await userEvent.click(await screen.findByRole('button', { name: 'Mở lại ca' }))
    expect(await screen.findByText('Đã mở lại ca Trần Bảo Long.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Hoàn tác' }))
    expect(await screen.findByText('Đã đánh dấu xong ca Trần Bảo Long.')).toBeInTheDocument()

    await userEvent.click(screen.getAllByText('Khách chưa cho tên')[0]!)
    await waitFor(() =>
      expect(screen.queryByText('Đã đánh dấu xong ca Trần Bảo Long.')).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('status').textContent).toBe('')
  })
})

describe('Chuyển sale — lỗi', () => {
  it('lưu «Đánh dấu xong» hỏng: báo NGAY TRONG hộp, ghi chú còn nguyên', async () => {
    server.use(
      http.patch('/api/v1/escalations/:id', () =>
        HttpResponse.json({ error: { code: 'INTERNAL', message: 'Mất kết nối' } }, { status: 500 }),
      ),
    )
    boot('/chuyen-sale?ca=14')
    await userEvent.click(await screen.findByRole('button', { name: 'Đánh dấu xong' }))
    const hop = within(screen.getByRole('dialog'))
    await userEvent.type(hop.getByLabelText('Ghi chú kết quả'), 'Đã gọi, khách hẹn thứ Bảy.')
    await userEvent.click(hop.getByRole('button', { name: 'Lưu và đánh dấu xong' }))

    expect(await hop.findByRole('alert')).toHaveTextContent(/Không lưu được/)
    expect(hop.getByLabelText('Ghi chú kết quả')).toHaveValue('Đã gọi, khách hẹn thứ Bảy.')
  })

  it('tải danh sách hỏng: nói rõ và có «Thử lại»', async () => {
    let lan = 0
    server.use(
      http.get('/api/v1/escalations', () => {
        lan += 1
        return lan === 1
          ? HttpResponse.json({ error: { code: 'INTERNAL', message: 'x' } }, { status: 500 })
          : undefined
      }),
    )
    boot('/chuyen-sale')
    expect(await screen.findByRole('alert')).toHaveTextContent('Không tải được danh sách ca.')
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByLabelText('Trang sau')).toBeInTheDocument()
  })
})
