/**
 * «Chuyển sale» — tự làm mới (harden 06/10, sau critique 05/10 23/40).
 *
 * Hộp thư lấy lại danh sách khi quay lại tab và mỗi 30 giây. Cái giá phải chặn:
 * dữ liệu mới về KHÔNG được đổi ca đang hiện dưới tay người dùng — đúng lớp lỗi
 * «nhận nhầm ca» đã sửa 05/10 (desktop rơi về `items[0]`, ca mới chen lên đầu).
 *
 * Làm mới trong test = `qc.refetchQueries` (cùng đường `refetchInterval` đi), hoặc
 * `focusManager` cho «quay lại tab». Không bài nào ghi vào `CA_GIA`.
 */
import { StrictMode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import type { Ca, TrangCa } from '../src/features/ops/api'
import { server } from '../vitest.setup'
import { boGiaLap, giaLapManHinh } from './man-hinh'

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
  return qc
}

const lamMoi = (qc: QueryClient) => qc.refetchQueries({ queryKey: ['escalations'] })
const hang = (id: number) => document.querySelector(`[data-ca="${id}"]`)

/** Danh sách «Tất cả» của fake, lấy qua chính MSW — để dựng bản «server vừa đổi». */
async function dsGoc(): Promise<TrangCa> {
  const r = await fetch('/api/v1/escalations?trang_thai=all&limit=10&offset=0')
  return (await r.json()) as TrangCa
}
function datDs(ds: TrangCa) {
  server.use(http.get('/api/v1/escalations', () => HttpResponse.json(ds)))
}

const NGHE: Array<(a: { request: Request }) => void> = []
afterEach(() => {
  NGHE.forEach((nghe) => server.events.removeListener('request:start', nghe))
  NGHE.length = 0
  focusManager.setFocused(undefined)
  boGiaLap()
})

describe('Chuyển sale — tự làm mới', () => {
  it('quay lại tab thì lấy lại danh sách', async () => {
    const dem = { n: 0 }
    const nghe = ({ request }: { request: Request }) => {
      if (new URL(request.url).pathname === '/api/v1/escalations') dem.n += 1
    }
    server.events.on('request:start', nghe)
    NGHE.push(nghe)
    boot('/chuyen-sale')
    await waitFor(() => expect(hang(12)).not.toBeNull())
    const truoc = dem.n

    focusManager.setFocused(false)
    focusManager.setFocused(true)
    await waitFor(() => expect(dem.n).toBe(truoc + 1))
  })

  it('desktop, chưa chọn ca: ca mới chen lên đầu KHÔNG đổi ca đang hiện', async () => {
    const goc = await dsGoc()
    const qc = boot('/chuyen-sale')
    await screen.findByRole('heading', { level: 2, name: 'Nguyễn Minh Anh' })
    expect(hang(12)).toHaveAttribute('aria-current', 'true')

    const moi: Ca = { ...goc.items[0]!, id: 99, ten: 'Khách vừa chuyển', phone: '0900000099' }
    datDs({ ...goc, items: [moi, ...goc.items], tongCa: goc.tongCa + 1 })
    await lamMoi(qc)

    await waitFor(() => expect(hang(99)).not.toBeNull())
    expect(screen.getByRole('heading', { level: 2, name: 'Nguyễn Minh Anh' })).toBeInTheDocument()
    expect(hang(12)).toHaveAttribute('aria-current', 'true')
    expect(hang(99)).not.toHaveAttribute('aria-current')
  })

  it('ca đang xem bị đổi ở nơi khác (rời danh sách): giữ ca, NÓI RA, cất nút đổi trạng thái', async () => {
    const goc = await dsGoc()
    const qc = boot('/chuyen-sale?ca=15')
    expect(await screen.findByRole('button', { name: 'Mở lại ca' })).toBeInTheDocument()

    datDs({ ...goc, items: goc.items.filter((c) => c.id !== 15), tongCa: goc.tongCa - 1 })
    await lamMoi(qc)

    expect(await screen.findByText(/Ca này vừa thay đổi/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Trần Bảo Long' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mở lại ca' })).not.toBeInTheDocument()
    // Không nhảy sang ca khác.
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1)
  })

  it('điện thoại: ca đang xem rời danh sách — KHÔNG đá về danh sách, hàng nút đáy biến mất', async () => {
    giaLapManHinh(375)
    const goc = await dsGoc()
    const qc = boot('/chuyen-sale?ca=15')
    expect(await screen.findByRole('button', { name: 'Mở lại ca' })).toBeInTheDocument()

    datDs({ ...goc, items: goc.items.filter((c) => c.id !== 15), tongCa: goc.tongCa - 1 })
    await lamMoi(qc)

    expect(await screen.findByText(/Ca này vừa thay đổi/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Trần Bảo Long' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Tìm ca theo tên hoặc số điện thoại')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mở lại ca' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '‹ Danh sách' })).toBeInTheDocument()
  })

  it('làm mới hỏng: GIỮ danh sách đang hiện, báo «chưa làm mới được» — không thay bằng khung lỗi', async () => {
    const qc = boot('/chuyen-sale')
    await waitFor(() => expect(hang(12)).not.toBeNull())
    server.use(
      http.get('/api/v1/escalations', () =>
        HttpResponse.json({ error: { code: 'INTERNAL', message: 'x' } }, { status: 500 }),
      ),
    )
    await lamMoi(qc)

    expect(await screen.findByText(/chưa làm mới được/)).toBeInTheDocument()
    expect(hang(12)).not.toBeNull()
    expect(screen.queryByText('Không tải được danh sách ca.')).not.toBeInTheDocument()
  })
})
