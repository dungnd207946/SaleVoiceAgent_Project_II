/**
 * Màn đăng nhập — route NGOÀI `_app`, render được khi CHƯA có phiên.
 *
 * Vì sao đó là điểm chính: `SessionProvider` chặn cả cây trên GET /api/v1/me. Khi
 * chưa đăng nhập, endpoint đó trả 401 — nên nếu provider còn bọc RouterProvider
 * như trước thì màn đăng nhập cũng không render được. Test này canh việc đã
 * chuyển provider vào `_app`.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

const CHUA_DANG_NHAP = http.get('/api/v1/me', () =>
  HttpResponse.json({ error: { code: 'NO_SESSION', message: 'x' } }, { status: 401 }),
)

function boot(path: string) {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

describe('màn đăng nhập', () => {
  it('render được khi /api/v1/me trả 401', async () => {
    server.use(CHUA_DANG_NHAP)
    boot('/login')

    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Mật khẩu')).toBeInTheDocument()
  })

  it('sai mật khẩu thì hiện lỗi TẠI CHỖ, không đẩy sang màn lỗi', async () => {
    server.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json(
          { error: { code: 'INVALID_CREDENTIALS', message: 'Email hoặc mật khẩu không đúng' } },
          { status: 401 },
        ),
      ),
    )
    boot('/login')

    await userEvent.type(await screen.findByLabelText('Email'), 'dang@anphuland.vn')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'sai')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    expect(await screen.findByText('Email hoặc mật khẩu không đúng')).toBeInTheDocument()
    // Form vẫn còn để thử lại — không bị thay bằng màn lỗi toàn trang.
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })

  // `409 NO_WORKSPACE nói khác hẳn` XOÁ 2026-08-15: đăng nhập không còn trả mã đó —
  // phiên không workspace là HỢP LỆ và FE đưa tới màn tạo workspace đầu tiên
  // (spec bo-organization §5.0). Mã `NO_WORKSPACE` giờ chỉ còn ở `POST /me/workspace`.

  it('vào màn trong app khi chưa đăng nhập thì bị đẩy về /login', async () => {
    server.use(CHUA_DANG_NHAP)
    boot('/dashboard')

    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
  })

  it('lỗi hạ tầng KHÔNG đẩy về /login — nó là màn lỗi có nút thử lại', async () => {
    /**
     * Hai thứ khác nhau phải xử lý khác nhau: 401 là "chưa đăng nhập" (đi đăng
     * nhập đi), 500 là "backend hỏng" (thử lại có nghĩa). Đẩy cả hai về /login
     * thì một sự cố hạ tầng trông như bị đăng xuất, và người dùng gõ mật khẩu
     * đúng nhiều lần rồi báo là "hệ thống không cho tôi vào".
     */
    server.use(http.get('/api/v1/me', () => new HttpResponse(null, { status: 500 })))
    boot('/dashboard')

    expect(await screen.findByText('Không tải được phiên đăng nhập')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
  })
})
