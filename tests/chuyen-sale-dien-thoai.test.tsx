/**
 * «Chuyển sale» — nút Gọi và bố cục điện thoại (adapt sau critique 05/10).
 *
 * Gọi lại khách là toàn bộ việc của CSKH, mà trước đây số chỉ là chữ thường.
 * Trên điện thoại, nút ca đứng cạnh tên thì đè lên tên, nằm ở nửa trên màn và
 * trôi mất khi đọc; cụm lọc còn chiếm 27% màn chi tiết.
 *
 * Bài nào đổi trạng thái thì tự «Hoàn tác»: `CA_GIA` là trạng thái module.
 *
 * Back (adapt 06/10): mở ca từ danh sách trên điện thoại từng là REPLACE ⇒ vuốt
 * back của iOS / nút Android rời cả màn «Chuyển sale» thay vì về danh sách.
 */
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
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
  return router
}

const hang = (id: number) => document.querySelector<HTMLElement>(`[data-ca="${id}"]`)
async function choHang(id: number) {
  await waitFor(() => expect(hang(id)).not.toBeNull())
  return hang(id)!
}

const NGHE: Array<(a: { request: Request }) => void> = []
function demPatch() {
  const goi = vi.fn()
  const nghe = ({ request }: { request: Request }) => {
    if (request.method === 'PATCH' && request.url.includes('/escalations/')) goi()
  }
  server.events.on('request:start', nghe)
  NGHE.push(nghe)
  return goi
}

// jsdom không điều hướng `tel:` (chỉ in «Not implemented: navigation») — chặn mặc
// định ở pha capture để log sạch; `onClick` của React vẫn chạy.
const chanTel = (e: MouseEvent) => {
  if ((e.target as Element).closest('a[href^="tel:"]')) e.preventDefault()
}
beforeEach(() => document.addEventListener('click', chanTel, true))
afterEach(() => {
  document.removeEventListener('click', chanTel, true)
  NGHE.forEach((nghe) => server.events.removeListener('request:start', nghe))
  NGHE.length = 0
  boGiaLap()
})

describe('Chuyển sale — nút Gọi', () => {
  it('ca có số: «Gọi» là link tel: đúng số, đứng CUỐI hàng nút', async () => {
    boot('/chuyen-sale?ca=12')
    const goi = await screen.findByRole('link', { name: 'Gọi 0912448111' })
    expect(goi).toHaveAttribute('href', 'tel:0912448111')
    const hang = goi.parentElement!
    expect(hang.lastElementChild).toBe(goi)
    expect(within(hang).getByRole('button', { name: 'Nhận ca này' })).toBeInTheDocument()
  })

  it('ca không có số: không mời gọi', async () => {
    boot('/chuyen-sale?ca=14')
    await screen.findByRole('button', { name: 'Đánh dấu xong' })
    expect(screen.queryByRole('link', { name: /^Gọi/ })).not.toBeInTheDocument()
  })

  it('ca đã xong: không mời gọi — mở lại ca trước', async () => {
    boot('/chuyen-sale?ca=15')
    await screen.findByRole('button', { name: 'Mở lại ca' })
    expect(screen.queryByRole('link', { name: /^Gọi/ })).not.toBeInTheDocument()
  })

  it('gọi một ca CHƯA LIÊN HỆ thì tự nhận ca; ca đang xử lý thì chỉ gọi', async () => {
    const patch = demPatch()
    boot('/chuyen-sale?tab=new&ca=12')
    await userEvent.click(await screen.findByRole('link', { name: 'Gọi 0912448111' }))

    expect(await screen.findByText('Đã nhận ca Nguyễn Minh Anh.')).toBeInTheDocument()
    expect(patch).toHaveBeenCalledTimes(1)

    // Đã nhận rồi: gọi lại lần nữa không đổi trạng thái gì.
    await userEvent.click(screen.getByRole('link', { name: 'Gọi 0912448111' }))
    await new Promise((r) => setTimeout(r, 50))
    expect(patch).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByRole('button', { name: 'Hoàn tác' }))
    expect(await screen.findByRole('button', { name: 'Nhận ca này' })).toBeInTheDocument()
  })
})

describe('Chuyển sale — điện thoại', () => {
  it('đang xem một ca: cụm lọc rời màn, nút ca vào hàng dán đáy (không ở cạnh tên)', async () => {
    giaLapManHinh(375)
    boot('/chuyen-sale?ca=12')
    const ten = await screen.findByRole('heading', { level: 2, name: 'Nguyễn Minh Anh' })

    expect(screen.queryByLabelText('Tìm ca theo tên hoặc số điện thoại')).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Trạng thái ca' })).not.toBeInTheDocument()

    const nhan = screen.getByRole('button', { name: 'Nhận ca này' })
    // Nút KHÔNG nằm cùng khối đầu ca với tên — đó là chỗ nó từng đè lên tên.
    expect(ten.closest('.flex.items-start')!.contains(nhan)).toBe(false)
    expect(nhan.parentElement).toHaveClass('sticky', 'bottom-0')
    expect(screen.getByRole('link', { name: 'Gọi 0912448111' }).parentElement).toBe(
      nhan.parentElement,
    )
  })

  it('về danh sách thì cụm lọc trở lại, hàng dán đáy biến mất', async () => {
    giaLapManHinh(375)
    boot('/chuyen-sale?ca=12')
    await userEvent.click(await screen.findByRole('button', { name: '‹ Danh sách' }))
    expect(await screen.findByLabelText('Tìm ca theo tên hoặc số điện thoại')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nhận ca này' })).not.toBeInTheDocument()
  })

  it('desktop giữ nút ở đầu ca, cạnh tên — và vẫn có cụm lọc', async () => {
    boot('/chuyen-sale?ca=12')
    const ten = await screen.findByRole('heading', { level: 2, name: 'Nguyễn Minh Anh' })
    const nhan = screen.getByRole('button', { name: 'Nhận ca này' })
    expect(ten.closest('.flex.items-start')!.contains(nhan)).toBe(true)
    expect(screen.getByLabelText('Tìm ca theo tên hoặc số điện thoại')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Nhận ca này' })).toHaveLength(1),
    )
  })
})

describe('Chuyển sale — Back trên điện thoại', () => {
  it('mở ca từ danh sách rồi Back của máy: về danh sách, focus đúng hàng vừa xem', async () => {
    giaLapManHinh(375)
    const router = boot('/chuyen-sale')
    await userEvent.click(await choHang(12))
    await screen.findByRole('heading', { level: 2, name: 'Nguyễn Minh Anh' })
    expect(router.history.canGoBack()).toBe(true)

    act(() => router.history.back())

    expect(await screen.findByLabelText('Tìm ca theo tên hoặc số điện thoại')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument()
    await waitFor(() => expect(document.activeElement).toBe(hang(12)))
  })

  it('«‹ Danh sách» LÙI đúng mục đó — không ghi thêm mục (không phải Back hai lần mới ra)', async () => {
    giaLapManHinh(375)
    const router = boot('/chuyen-sale')
    await userEvent.click(await choHang(12))
    await userEvent.click(await screen.findByRole('button', { name: '‹ Danh sách' }))

    expect(await screen.findByLabelText('Tìm ca theo tên hoặc số điện thoại')).toBeInTheDocument()
    expect(router.history.canGoBack()).toBe(false)
  })

  it('đổi trạng thái rồi Back: ca không bị ghim hiện lại, dải báo trống', async () => {
    giaLapManHinh(375)
    const router = boot('/chuyen-sale?tab=new')
    await userEvent.click(await choHang(12))
    await userEvent.click(await screen.findByRole('button', { name: 'Nhận ca này' }))
    expect(await screen.findByText('Đã nhận ca Nguyễn Minh Anh.')).toBeInTheDocument()
    // Trả dữ liệu giả về như cũ ngay — ca vẫn ghim (đã rớt khỏi tab «Chưa liên hệ»
    // rồi quay lại), đúng trạng thái cần thử.
    await userEvent.click(screen.getByRole('button', { name: 'Hoàn tác' }))
    expect(
      await screen.findByText('Đã trả ca Nguyễn Minh Anh về «Chưa liên hệ».'),
    ).toBeInTheDocument()

    act(() => router.history.back())

    expect(await screen.findByLabelText('Tìm ca theo tên hoặc số điện thoại')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument()
    expect(screen.getByRole('status').textContent).toBe('')
  })

  it('mở bằng link `?ca=`: «‹ Danh sách» thay tại chỗ (không có danh sách nào phía sau để lùi)', async () => {
    giaLapManHinh(375)
    const router = boot('/chuyen-sale?ca=12')
    await userEvent.click(await screen.findByRole('button', { name: '‹ Danh sách' }))
    expect(await screen.findByLabelText('Tìm ca theo tên hoặc số điện thoại')).toBeInTheDocument()
    expect(router.history.canGoBack()).toBe(false)
  })

  it('desktop đổi hàng KHÔNG thêm mục lịch sử', async () => {
    const router = boot('/chuyen-sale')
    await userEvent.click(await choHang(12))
    await userEvent.click(await choHang(14))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ ca: 14 }))
    expect(router.history.canGoBack()).toBe(false)
  })
})
