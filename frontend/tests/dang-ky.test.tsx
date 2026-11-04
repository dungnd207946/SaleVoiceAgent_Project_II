/**
 * Màn `/dang-ky` — tự đăng ký (đổi 2026-08-17).
 *
 * Backend không còn nhận mật khẩu ở đây (`POST /auth/register` chỉ nhận
 * `email`+`name`) và KHÔNG còn đặt cookie phiên — mật khẩu đặt ở `/invite/<token>`
 * sau khi bấm link trong thư. Ba bài đầu khoá đúng ba màn kết quả (201 mới ·
 * 200 pending-resend · 409 EMAIL_TAKEN); bài cuối khoá việc KHÔNG CÒN Ô MẬT KHẨU.
 *
 * `boot()` cùng khuôn `tests/nhan-loi-moi.test.tsx` — `render(<DangKyForm />)`
 * trần không chạy được vì thiếu `QueryClientProvider`/`RouterProvider` (form
 * dùng `useMutation` + `<Link>`).
 */
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'

function boot(duong = '/dang-ky') {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duong] }),
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

async function dienVaGui(email: string, ten = 'Người Mới') {
  await userEvent.type(await screen.findByLabelText(/email/i), email)
  await userEvent.type(screen.getByLabelText(/tên người dùng/i), ten)
  await userEvent.click(screen.getByRole('button', { name: /đăng ký/i }))
}

describe('màn /dang-ky — tự đăng ký gửi link qua thư', () => {
  it('201 (tài khoản mới) -> "Kiểm tra hộp thư" nói ĐÚNG địa chỉ vừa nhập', async () => {
    boot()
    await dienVaGui('moi@x.vn')

    expect(await screen.findByText('Kiểm tra hộp thư')).toBeInTheDocument()
    expect(screen.getByText(/moi@x\.vn/)).toBeInTheDocument()
    expect(screen.getByText(/Đã gửi liên kết đặt mật khẩu tới/)).toBeInTheDocument()
    expect(screen.getByText(/hạn 7 ngày/)).toBeInTheDocument()
    // KHÔNG được nói "gửi lại" — đó là câu riêng của nhánh 200/pending.
    expect(screen.queryByText(/gửi lại/i)).not.toBeInTheDocument()
  })

  it('200 (tài khoản pending) -> nói RÕ đây là gửi LẠI, không phải lần đầu', async () => {
    boot()
    await dienVaGui('dang.cho@x.vn')

    expect(await screen.findByText(/chưa hoàn tất đăng ký/i)).toBeInTheDocument()
    expect(screen.getByText(/gửi lại/i)).toBeInTheDocument()
    expect(screen.getByText(/dang\.cho@x\.vn/)).toBeInTheDocument()
  })

  it('409 EMAIL_TAKEN -> "đã có tài khoản" KÈM nút/link Đăng nhập', async () => {
    boot()
    await dienVaGui('da.ton.tai@x.vn')

    const canhBao = await waitFor(() => {
      const c = screen.getByRole('alert')
      expect(c).toHaveTextContent(/đã có tài khoản/i)
      return c
    })
    expect(within(canhBao).getByRole('link', { name: /đăng nhập/i })).toBeInTheDocument()
    // Lỗi hiện TẠI CHỖ, KHÔNG rẽ sang màn "Kiểm tra hộp thư".
    expect(screen.queryByText('Kiểm tra hộp thư')).not.toBeInTheDocument()
  })

  it('không còn ô mật khẩu — mật khẩu đặt ở màn /invite', async () => {
    const { container } = boot()
    await screen.findByLabelText(/email/i)
    // Dò theo NHÃN — bắt được input mật khẩu CÓ nhãn diễn đạt đúng chữ đó.
    expect(screen.queryByLabelText(/mật khẩu/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    // Dò theo BẢN CHẤT (type="password") — cổng canh chính, không phụ thuộc
    // cách đặt nhãn: một input mật khẩu KHÔNG nhãn hoặc nhãn khác chữ ("Mã bí
    // mật", v.v.) vẫn phải bị bắt, vì quyết định trung tâm của đợt này là
    // KHÔNG CÓ input mật khẩu nào trên màn, bất kể nó được gọi là gì.
    expect(container.querySelector('input[type="password"]')).toBeNull()
  })
})
