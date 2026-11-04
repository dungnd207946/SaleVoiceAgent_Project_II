/**
 * Màn «Hồ sơ & tuỳ chọn» (`/settings`) — hồ sơ xem-trước-sửa-sau, đổi avatar
 * qua lưới gợi ý, ngôn ngữ, đổi mật khẩu.
 *
 * Màn dùng `useSession()` nên phải bọc `SessionProvider`; provider lại gọi
 * `useNavigate()` nên cả cụm sống trong một router tối giản — cùng lối
 * `dungTrongRouter` của `convos-list.test.tsx`.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { HoSoScreen } from '@/features/auth/components/HoSoScreen'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import { CO_EN, LangProvider } from '../src/i18n'
import { SessionProvider } from '../src/lib/session'
import { server } from '../vitest.setup'

function dung() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        <LangProvider>
          <SessionProvider>
            <HoSoScreen />
          </SessionProvider>
        </LangProvider>
      </QueryClientProvider>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/settings'] }),
  })
  return render(<RouterProvider router={router} />)
}

const AVATAR_MOI = "data:image/svg+xml;charset=utf-8,%3Csvg%20data-moi%3D'1'%2F%3E"

/** Fake PATCH ghi lại body và trả phiên đã trộn — bài nào cần thì `server.use`. */
function batPatch(danhSach: unknown[]) {
  server.use(
    http.patch('/api/v1/me/ho-so', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      danhSach.push(body)
      const u = FAKE_SESSION.user
      return HttpResponse.json({
        ...FAKE_SESSION,
        user: {
          ...u,
          name: typeof body.name === 'string' ? body.name : u.name,
          avatar: 'avatarSeed' in body ? AVATAR_MOI : u.avatar,
        },
      })
    }),
  )
}

describe('hồ sơ — xem trước, sửa sau', () => {
  it('mặc định là bản tóm tắt chỉ-đọc: có tên + email, KHÔNG có ô nhập nào', async () => {
    dung()
    expect(await screen.findByText('Trần Hải Đăng')).toBeInTheDocument()
    expect(screen.getByText('dang@anphuland.vn')).toBeInTheDocument()
    // SĐT lẫn chức danh đều chưa có ⇒ HAI dòng «Chưa đặt» — ô rỗng phải nói
    // thành chữ, không để <dd> trống.
    expect(screen.getAllByText('Chưa đặt')).toHaveLength(2)
    // Form hồ sơ UNMOUNT hẳn — không so `input` trần: khối Mật khẩu bên dưới
    // LUÔN có hai ô của nó, thứ phải vắng là ô của form hồ sơ.
    expect(screen.queryByLabelText('Họ tên')).not.toBeInTheDocument()
  })

  it('bấm «Sửa hồ sơ» mở form; Lưu gửi PATCH đúng payload rồi về chế độ xem', async () => {
    const goi: unknown[] = []
    batPatch(goi)
    dung()
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa hồ sơ' }))

    const oTen = screen.getByLabelText('Họ tên')
    await userEvent.clear(oTen)
    await userEvent.type(oTen, 'Lê Văn Mới')
    await userEvent.type(screen.getByLabelText('Số điện thoại'), '0900000009')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu' }))

    await waitFor(() => expect(goi).toHaveLength(1))
    expect(goi[0]).toEqual({ name: 'Lê Văn Mới', phone: '0900000009', jobTitle: null })
    // Về chế độ xem với dữ liệu MỚI từ response (cache phiên đã được ghi đè).
    expect(await screen.findByText('Lê Văn Mới')).toBeInTheDocument()
    expect(screen.queryByLabelText('Họ tên')).not.toBeInTheDocument()
  })

  it('«Huỷ» đóng form không gửi gì, và lần Sửa sau KHÔNG còn chữ đã gõ dở', async () => {
    const goi: unknown[] = []
    batPatch(goi)
    dung()
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa hồ sơ' }))
    await userEvent.type(screen.getByLabelText('Họ tên'), ' Dở Dang')
    await userEvent.click(screen.getByRole('button', { name: 'Huỷ' }))

    expect(goi).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Sửa hồ sơ' }))
    expect(screen.getByLabelText('Họ tên')).toHaveValue('Trần Hải Đăng')
  })
})

describe('đổi avatar', () => {
  function batGoiY() {
    server.use(
      http.get('/api/v1/me/avatar-goi-y', () =>
        HttpResponse.json(
          Array.from({ length: 12 }, (_, i) => ({
            seed: `seed-${i}`,
            avatar: `data:image/svg+xml;charset=utf-8,%3Csvg%20data-goiy%3D'${i}'%2F%3E`,
          })),
        ),
      ),
    )
  }

  it('«Đổi avatar» mở dialog 12 gợi ý; chọn một ô rồi Lưu gửi đúng seed', async () => {
    const goi: unknown[] = []
    batPatch(goi)
    batGoiY()
    dung()
    await userEvent.click(await screen.findByRole('button', { name: 'Đổi avatar' }))

    const dialog = await screen.findByRole('dialog')
    const oGoiY = await within(dialog).findAllByRole('button', { name: /Gợi ý \d+/ })
    expect(oGoiY).toHaveLength(12)

    await userEvent.click(within(dialog).getByRole('button', { name: 'Gợi ý 4' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Lưu avatar' }))

    await waitFor(() => expect(goi).toHaveLength(1))
    expect(goi[0]).toEqual({ avatarSeed: 'seed-3' }) // «Gợi ý 4» = phần tử thứ 4, seed-3
    // Avatar trên màn đổi ngay theo response — không chờ refetch /me.
    await waitFor(() =>
      expect(document.querySelector(`img[src="${AVATAR_MOI}"]`)).toBeInTheDocument(),
    )
  })

  it('«Dùng mặc định theo tên» gửi avatarSeed null tường minh', async () => {
    const goi: unknown[] = []
    batPatch(goi)
    batGoiY()
    dung()
    await userEvent.click(await screen.findByRole('button', { name: 'Đổi avatar' }))
    await userEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Dùng mặc định theo tên',
      }),
    )

    await waitFor(() => expect(goi).toHaveLength(1))
    expect(goi[0]).toEqual({ avatarSeed: null })
  })
})

describe('đổi mật khẩu', () => {
  it('gửi đúng body; thành công báo «Đã đổi mật khẩu.» và dọn cả ba ô', async () => {
    const goi: unknown[] = []
    server.use(
      http.post('/api/v1/me/mat-khau', async ({ request }) => {
        goi.push(await request.json())
        return new HttpResponse(null, { status: 204 })
      }),
    )
    dung()
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'mat-khau-cu-dai')
    await userEvent.type(screen.getByLabelText('Mật khẩu mới'), 'mat-khau-moi-du-dai')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'mat-khau-moi-du-dai')
    await userEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))

    expect(await screen.findByText('Đã đổi mật khẩu.')).toBeInTheDocument()
    expect(goi[0]).toEqual({ matKhauHienTai: 'mat-khau-cu-dai', matKhauMoi: 'mat-khau-moi-du-dai' })
    expect(screen.getByLabelText('Mật khẩu hiện tại')).toHaveValue('')
    expect(screen.getByLabelText('Nhập lại mật khẩu mới')).toHaveValue('')
  })

  it('nhập lại KHÔNG khớp → nút khoá + thông điệp tại chỗ, không gửi request nào', async () => {
    const goi: unknown[] = []
    server.use(
      http.post('/api/v1/me/mat-khau', async ({ request }) => {
        goi.push(await request.json())
        return new HttpResponse(null, { status: 204 })
      }),
    )
    dung()
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'mat-khau-cu-dai')
    await userEvent.type(screen.getByLabelText('Mật khẩu mới'), 'mat-khau-moi-du-dai')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'go-nham-mot-chu')

    expect(screen.getByText('Mật khẩu nhập lại không khớp.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Đổi mật khẩu' })).toBeDisabled()
    expect(goi).toHaveLength(0)
  })

  it('sai mật khẩu hiện tại → hiện thông điệp lỗi của server, không phải câu chung', async () => {
    server.use(
      http.post('/api/v1/me/mat-khau', () =>
        HttpResponse.json(
          { error: { code: 'MAT_KHAU_HIEN_TAI_SAI', message: 'Mật khẩu hiện tại không đúng' } },
          { status: 400 },
        ),
      ),
    )
    dung()
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'doan-bua-x')
    await userEvent.type(screen.getByLabelText('Mật khẩu mới'), 'mat-khau-moi-du-dai')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'mat-khau-moi-du-dai')
    await userEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))

    expect(await screen.findByText('Mật khẩu hiện tại không đúng')).toBeInTheDocument()
  })

  it('tài khoản Google (coMatKhau false) → hộp hướng sang Google, KHÔNG có ô mật khẩu nào', async () => {
    server.use(
      http.get('/api/v1/me', () =>
        HttpResponse.json({ ...FAKE_SESSION, user: { ...FAKE_SESSION.user, coMatKhau: false } }),
      ),
    )
    dung()
    // Khuôn theo ảnh người dùng chốt 2026-08-22: hộp đóng khung nói rõ ĐỔI Ở ĐÂU
    // (vào tài khoản Google), không chỉ nói «không có mật khẩu».
    expect(await screen.findByText(/Hãy đăng nhập vào tài khoản Google/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Mật khẩu hiện tại')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Đổi mật khẩu' })).not.toBeInTheDocument()
  })
})

describe('ngôn ngữ', () => {
  it.skipIf(CO_EN)('EN đang tắt ⇒ không có thẻ «Ngôn ngữ hiển thị»', async () => {
    dung()
    await screen.findByText('Trần Hải Đăng')
    expect(screen.queryByRole('heading', { name: 'Ngôn ngữ hiển thị' })).toBeNull()
    expect(screen.queryByRole('radio', { name: 'English' })).toBeNull()
  })

  // EN đang tắt (`CO_EN`, i18n) — thẻ «Ngôn ngữ hiển thị» không hiện; bài này tự chạy lại khi bật.
  it.skipIf(!CO_EN)('chọn English đổi nhãn màn ngay tại chỗ', async () => {
    dung()
    await screen.findByText('Trần Hải Đăng')
    await userEvent.click(screen.getByRole('radio', { name: 'English' }))

    expect(await screen.findByRole('button', { name: 'Edit profile' })).toBeInTheDocument()
  })
})
