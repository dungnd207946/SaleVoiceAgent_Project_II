/**
 * Màn «Nhật ký» (`/audit`, M8) — render component TRỰC TIẾP, không boot router
 * (cùng lý lẽ `khoa-dau-noi.test.tsx`). Fake MSW mặc định là `nhatKyHandlers`;
 * các bài cần đếm request thì `server.use` một handler GHI LẠI url rồi uỷ quyền
 * cho `locNhatKyGia` — hành vi giữ nguyên, chỉ thêm tai nghe.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LangProvider } from '../src/i18n'
import { NhatKyScreen } from '../src/features/platform/components/NhatKyScreen'
import { NHAT_KY_GIA, locNhatKyGia } from '../src/features/platform/mswNhatKy'
import { server } from '../vitest.setup'

function boot() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <NhatKyScreen />
      </LangProvider>
    </QueryClientProvider>,
  )
}

/** Ghi lại mọi URL gọi `/api/v1/audit`; `epLimit` ép trang nhỏ để test «Tải thêm». */
function ngheRequest(epLimit?: number): URLSearchParams[] {
  const goi: URLSearchParams[] = []
  server.use(
    http.get('/api/v1/audit', ({ request }) => {
      const p = new URL(request.url).searchParams
      goi.push(new URLSearchParams(p))
      if (epLimit !== undefined) p.set('limit', String(epLimit))
      return HttpResponse.json(locNhatKyGia(NHAT_KY_GIA, p))
    }),
  )
  return goi
}

async function bang() {
  return within(await screen.findByRole('table', { name: 'Nhật ký hoạt động' }))
}

function soHang(b: ReturnType<typeof within>): number {
  return b.getAllByRole('row').length - 1 // trừ hàng tiêu đề
}

describe('màn Nhật ký', () => {
  beforeEach(() => server.resetHandlers())

  it('hiện nhãn tiếng Việt, tên người, ba loại actor đặc biệt', async () => {
    boot()
    const b = await bang()
    expect(b.getAllByText('Sửa dự án').length).toBeGreaterThan(0)
    expect(b.queryByText('realestate.project.update')).not.toBeInTheDocument()
    expect(b.getAllByText('Hải Đỗ').length).toBeGreaterThan(0)
    expect(b.getAllByText('Hệ thống').length).toBeGreaterThan(0)
    expect(b.getAllByText('Cổng nạp').length).toBeGreaterThan(0)
    expect(b.getAllByText('u_da_xoa').length).toBeGreaterThan(0)
    // Mặc định KHÔNG có hàng máy
    expect(b.queryByText('Agent')).not.toBeInTheDocument()
    expect(b.queryByText('Agent lấy credential')).not.toBeInTheDocument()
    // Chi tiết dạng khoá: giá trị
    expect(b.getAllByText('project_code: NT2 · truong: name, price').length).toBeGreaterThan(0)
  })

  it('mặc định request KHÔNG có may; bật công tắc ⇒ may=true và hàng agent hiện', async () => {
    const goi = ngheRequest()
    boot()
    await bang()
    expect(goi[0]?.has('may')).toBe(false)
    await userEvent.click(screen.getByRole('checkbox', { name: 'Hiện hoạt động của agent' }))
    await waitFor(() => expect(goi.at(-1)?.get('may')).toBe('true'))
    const b = await bang()
    await waitFor(() => expect(b.getAllByText('Agent lấy credential').length).toBeGreaterThan(0))
  })

  it('đổi nhóm ⇒ request mang đúng danh sách tiền tố', async () => {
    const goi = ngheRequest()
    boot()
    await bang()
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Nhóm hành động' }),
      'thanh-vien',
    )
    await waitFor(() => expect(goi.at(-1)?.get('nhom')).toBe('thanh_vien,user,role,owner'))
    const b = await bang()
    await waitFor(() => expect(b.queryByText('Sửa dự án')).not.toBeInTheDocument())
    expect(b.getAllByText('Mời thành viên').length).toBeGreaterThan(0)
  })

  it('«đến hết ngày» D ⇒ to = D + 1; «từ ngày» gửi nguyên', async () => {
    const goi = ngheRequest()
    boot()
    await bang()
    await userEvent.type(screen.getByLabelText('Từ ngày'), '2026-08-18')
    await userEvent.type(screen.getByLabelText('Đến hết ngày'), '2026-08-20')
    await waitFor(() => {
      const p = goi.at(-1)
      expect(p?.get('from')).toBe('2026-08-18')
      expect(p?.get('to')).toBe('2026-08-21')
    })
  })

  it('«Tải thêm» nối trang và biến mất khi hết', async () => {
    const goi = ngheRequest(3)
    boot()
    let b = await bang()
    expect(soHang(b)).toBe(3)
    await userEvent.click(screen.getByRole('button', { name: 'Tải thêm' }))
    await waitFor(() => expect(soHang(bangDongBo())).toBe(6))
    expect(goi.at(-1)?.get('cursor')).toBeTruthy()
    // Bấm tới khi hết: 45 hàng − 3 hàng agent (i = 2, 17, 32) = 42 hàng ⇒ 14 trang.
    for (let i = 0; i < 20 && screen.queryByRole('button', { name: 'Tải thêm' }); i++) {
      await userEvent.click(screen.getByRole('button', { name: 'Tải thêm' }))
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: /Đang tải/ })).not.toBeInTheDocument(),
      )
    }
    b = await bang()
    expect(soHang(b)).toBe(42)
    expect(screen.queryByRole('button', { name: 'Tải thêm' })).not.toBeInTheDocument()
  })

  it('rỗng', async () => {
    server.use(http.get('/api/v1/audit', () => HttpResponse.json({ items: [], nextCursor: null })))
    boot()
    expect(await screen.findByText('Chưa có hoạt động nào')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('403 hiện message của API nguyên văn', async () => {
    server.use(
      http.get('/api/v1/audit', () =>
        HttpResponse.json(
          {
            error: {
              code: 'FORBIDDEN',
              message: 'Vai trò Người xem không có quyền Xem Nhật ký hoạt động',
            },
          },
          { status: 403 },
        ),
      ),
    )
    boot()
    const canh = await screen.findByRole('alert')
    expect(canh).toHaveTextContent('Vai trò Người xem không có quyền Xem Nhật ký hoạt động')
  })

  it('lỗi mạng (không phải LoiApi) hiện câu chung, không hiện «Failed to fetch»', async () => {
    server.use(http.get('/api/v1/audit', () => HttpResponse.error()))
    boot()
    const canh = await screen.findByRole('alert')
    expect(canh).toHaveTextContent('Không tải được nhật ký.')
    expect(canh).not.toHaveTextContent('Failed to fetch')
  })

  it('«Từ ngày» khoá ô «Đến hết ngày» qua thuộc tính `min`', async () => {
    boot()
    await bang()
    fireEvent.change(screen.getByLabelText('Từ ngày'), { target: { value: '2026-08-10' } })
    await waitFor(() =>
      expect(screen.getByLabelText('Đến hết ngày')).toHaveAttribute('min', '2026-08-10'),
    )
  })
})

function bangDongBo() {
  return within(screen.getByRole('table', { name: 'Nhật ký hoạt động' }))
}
