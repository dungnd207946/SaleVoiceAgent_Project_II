/**
 * Màn `/invite/$token` — nhận lời mời.
 *
 * TÁCH RA từ `tests/user-admin.test.tsx` (2026-08-09, review round 1 của Task 2
 * «gọn thành viên và phân quyền»): file đó bị xoá vì phần bảng `/users` trong nó
 * kiểm trục TỔ CHỨC đã thay thế bằng `tests/thanh-vien.test.tsx`, nhưng describe
 * này KHÔNG chạm gì tới trục đó — nó tự chứa (`boot('/invite/…')` + MSW riêng),
 * và `/invite/$token` đứng NGOÀI `_app` nên `tests/boot.test.tsx` (vòng lặp chỉ
 * soi route con của `_app`) không bao giờ tới được nó. Xoá cả
 * file gốc theo premise "chỉ kiểm `/users`" là sai — bốn bài dưới đây bị mất
 * theo trong khi đáng lẽ không liên quan gì tới việc đổi trục.
 *
 * Nội dung describe GIỮ NGUYÊN VĂN so với bản gốc (không sửa assertion nào),
 * chỉ mang theo đúng phần import + helper `boot()` mà nó thật sự dùng.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

function boot(duong: string) {
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

describe('màn /invite/$token — nhận lời mời', () => {
  it('token còn hiệu lực (kind: invite_new) -> nói tên workspace, có email chỉ-đọc', async () => {
    // ĐỔI từ `kind: 'invite'` (giá trị đã bỏ) sang `invite_new` — Task 9 tách
    // `invite` cũ thành `invite_new`/`invite_existing` (xem docstring `LoiMoi.kind`
    // ở `api.ts`), và Task 10 ĐẢO LẠI quyết định 2026-08-15 «không hiện tên
    // workspace» (xem docstring `LoiMoi.workspaceName`). `name: null` đúng hợp
    // đồng: `invite_new` chưa có hàng `users` nào để có tên.
    server.use(
      http.get('/api/v1/invites/:token', () =>
        HttpResponse.json({
          email: 'moi@anphuland.vn',
          name: null,
          kind: 'invite_new',
          workspaceName: 'NobleX',
        }),
      ),
    )
    boot('/invite/tok_hop_le')

    expect(await screen.findByText(/NobleX/)).toBeInTheDocument()
    expect(screen.getByLabelText('Email đăng nhập')).toHaveValue('moi@anphuland.vn')
    expect(screen.getByLabelText('Email đăng nhập')).toHaveAttribute('readonly')

    // Ô chỉ-đọc KHÔNG được mang `bg-panel`. Hai token trong theme.css đều được gọi
    // là "panel" và chúng NGƯỢC NHAU: `chrome-2` (#f8f6f1) là panel nav sáng,
    // `panel` (#1a1c20) là mặt TỐI của khối «Thử ngay» + lớp phủ modal. Ô này từng
    // dùng `bg-panel` và ra một ô gần như đen — `text-muted` trên nền đó đo được
    // 2.90, dưới sàn AA 4.5. Canh theo TÊN CLASS vì đó là chỗ lỗi thật sự xảy ra;
    // jsdom không tính được màu đã resolve nên không có cách đo tương phản ở đây.
    const o = screen.getByLabelText('Email đăng nhập')
    expect(o.className).not.toContain('bg-panel')
    expect(o.className).toContain('bg-chrome-2')

    expect(screen.getByRole('button', { name: /Tham gia workspace/ })).toBeInTheDocument()
  })

  it('token còn hiệu lực (kind: signup) -> tiêu đề "Hoàn tất đăng ký", nút "Đặt mật khẩu"', async () => {
    server.use(
      http.get('/api/v1/invites/:token', () =>
        HttpResponse.json({
          email: 'tu.dang.ky@anphuland.vn',
          name: 'Người Tự Đăng Ký',
          kind: 'signup',
        }),
      ),
    )
    boot('/invite/tok_gia_dk_1')

    expect(await screen.findByText('Hoàn tất đăng ký')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Đặt mật khẩu' })).toBeInTheDocument()
    // KHÔNG hiện tên workspace ở ca signup — quyết định đã chốt.
    expect(screen.queryByText(/NobleX/)).not.toBeInTheDocument()
  })

  it('④ token chết -> nói phải xin link mới, KHÔNG hiện form', async () => {
    server.use(
      http.get('/api/v1/invites/:token', () =>
        HttpResponse.json(
          {
            error: { code: 'INVITE_INVALID', message: 'Lời mời không hợp lệ hoặc đã hết hiệu lực' },
          },
          { status: 404 },
        ),
      ),
    )
    boot('/invite/tok_chet')

    expect(await screen.findByText('Lời mời không còn hiệu lực')).toBeInTheDocument()
    // MỘT câu cho cả ba nguyên nhân — backend cố ý không phân biệt, UI không đoán thay.
    expect(screen.getByRole('alert')).toHaveTextContent(/đã được dùng, đã hết hạn.*hoặc không đúng/)
    expect(screen.queryByLabelText('Mật khẩu mới')).not.toBeInTheDocument()
  })

  it('hai lần nhập mật khẩu khác nhau -> chặn ở client, không gửi request', async () => {
    // Backend chỉ nhận MỘT mật khẩu nên nó không có cách nào biết người dùng gõ
    // nhầm lần thứ hai. Đây là phép kiểm duy nhất chỉ client làm được.
    //
    // `kind: 'signup'` thêm vào (fixture gốc thiếu trường này, hợp lệ dưới hợp
    // đồng hai-giá-trị cũ nhưng `kind` nay BẮT BUỘC — Task 9). Nhãn ô thứ hai sửa
    // từ «Nhập lại mật khẩu» (chưa từng khớp DOM thật, xem docstring cuối file)
    // sang đúng «Xác nhận mật khẩu» mà cả bản cũ lẫn bản mới đều render.
    let daGoi = false
    server.use(
      http.get('/api/v1/invites/:token', () =>
        HttpResponse.json({ email: 'a@b.vn', name: 'A', kind: 'signup', workspaceName: null }),
      ),
      http.post('/api/v1/invites/accept', () => {
        daGoi = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot('/invite/tok_hop_le')

    await userEvent.type(await screen.findByLabelText('Mật khẩu mới'), 'mat-khau-dai-du')
    await userEvent.type(screen.getByLabelText('Xác nhận mật khẩu'), 'mat-khau-khac-han')
    await userEvent.click(screen.getByRole('button', { name: /Đặt mật khẩu/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('không giống nhau')
    expect(daGoi).toBe(false)
  })
})

describe('ba nhánh lời mời (2026-08-22)', () => {
  it('invite_new: nói tên workspace, có ô mật khẩu, không chào theo tên', async () => {
    server.use(
      http.get('/api/v1/invites/:t', () =>
        HttpResponse.json({
          email: 'moi@x.vn',
          name: null,
          kind: 'invite_new',
          workspaceName: 'An Phú Land',
        }),
      ),
    )
    boot('/invite/tk')
    expect(await screen.findByText(/An Phú Land/)).toBeInTheDocument()
    expect(screen.getByLabelText('Mật khẩu mới')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Tham gia workspace/ })).toBeInTheDocument()
  })

  it('invite_existing: KHÔNG có ô mật khẩu, một nút xác nhận', async () => {
    server.use(
      http.get('/api/v1/invites/:t', () =>
        HttpResponse.json({
          email: 'daco@x.vn',
          name: 'Đã Có',
          kind: 'invite_existing',
          workspaceName: 'Sunrise',
        }),
      ),
    )
    boot('/invite/tk')
    expect(await screen.findByText(/Sunrise/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Mật khẩu mới')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Tham gia workspace/ })).toBeInTheDocument()
  })

  it('invite_existing gửi thân KHÔNG có password', async () => {
    let than: unknown = null
    server.use(
      http.get('/api/v1/invites/:t', () =>
        HttpResponse.json({
          email: 'a@x.vn',
          name: 'A',
          kind: 'invite_existing',
          workspaceName: 'WS',
        }),
      ),
      http.post('/api/v1/invites/accept', async ({ request }) => {
        than = await request.json()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot('/invite/tk')
    await userEvent.click(await screen.findByRole('button', { name: /Tham gia workspace/ }))
    await waitFor(() => expect(than).toEqual({ token: 'tk' }))
  })

  it('signup: giữ nguyên tiêu đề cũ, không nói workspace', async () => {
    server.use(
      http.get('/api/v1/invites/:t', () =>
        HttpResponse.json({ email: 'a@x.vn', name: 'A', kind: 'signup', workspaceName: null }),
      ),
    )
    boot('/invite/tk')
    expect(await screen.findByText('Hoàn tất đăng ký')).toBeInTheDocument()
    expect(screen.getByLabelText('Mật khẩu mới')).toBeInTheDocument()
  })
})
