/**
 * Tạo workspace từ switcher: request THẬT, và chuyển sang workspace vừa tạo.
 *
 * BA ĐIỀU NEO LẠI Ở ĐÂY:
 *   ① `POST /api/v1/workspaces` được gọi với đúng `name` — không phải chỉ đổi
 *      state client rồi để danh sách switcher tự trôi.
 *   ② Lỗi 409 hiện TRONG dialog và dialog KHÔNG đóng. Đóng nó là ném người dùng
 *      về switcher mà không nói vì sao, và tên họ vừa gõ thì mất.
 *   ③ Mục Tạo workspace mới hiện cho MỌI người (2026-08-15). Trước đó chỉ owner
 *      là mời họ bấm vào một 403 của backend.
 *
 * Handler khai bằng `server.use(...)` tại chỗ, KHÔNG thêm vào `lib/msw/handlers.ts`:
 * file đó đang được sửa bởi effort vai-trò-động, và một handler chỉ một test này
 * cần thì không thuộc bộ handler dùng chung. Cùng khuôn `doi-workspace.test.tsx`.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

const WS_MOI = {
  id: 'ws_san_dong_nam',
  name: 'Sàn Đông Nam',
  lifecycle: 'active',
  status: 'provisioning',
  createdAt: '2026-08-04T10:00:00Z',
}

function boot(duongDan = '/dashboard') {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duongDan] }),
  })
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

/** Mở menu switcher. Lọc theo TÊN workspace đang hiện — cùng lý do doi-workspace.test.tsx. */
async function moMenu() {
  await userEvent.click(await screen.findByRole('button', { name: /An Phú Land/ }))
}

async function moDialog() {
  await moMenu()
  await userEvent.click(await screen.findByRole('button', { name: /Tạo workspace mới/ }))
  return screen.findByRole('dialog')
}

describe('tạo workspace', () => {
  it('gọi POST /api/v1/workspaces với đúng tên đã gõ', async () => {
    const daGoi = vi.fn()
    server.use(
      http.post('/api/v1/workspaces', async ({ request }) => {
        daGoi((await request.json()) as { name: string })
        return HttpResponse.json(WS_MOI, { status: 201 })
      }),
      http.post('/api/v1/me/workspace', () =>
        HttpResponse.json({ ...FAKE_SESSION, currentWorkspaceId: WS_MOI.id }),
      ),
    )
    boot()

    await moDialog()
    await userEvent.type(screen.getByLabelText(/Tên workspace/), 'Sàn Đông Nam')
    await userEvent.click(screen.getByRole('button', { name: /^Tạo workspace$/ }))

    await vi.waitFor(() => {
      expect(daGoi).toHaveBeenCalledWith({ name: 'Sàn Đông Nam' })
    })
  })

  it('sau khi tạo thì CHUYỂN sang workspace mới (POST /me/workspace)', async () => {
    const daDoi = vi.fn()
    server.use(
      http.post('/api/v1/workspaces', () => HttpResponse.json(WS_MOI, { status: 201 })),
      http.post('/api/v1/me/workspace', async ({ request }) => {
        const body = (await request.json()) as { workspaceId: string }
        daDoi(body.workspaceId)
        return HttpResponse.json({ ...FAKE_SESSION, currentWorkspaceId: body.workspaceId })
      }),
    )
    boot()

    await moDialog()
    await userEvent.type(screen.getByLabelText(/Tên workspace/), 'Sàn Đông Nam')
    await userEvent.click(screen.getByRole('button', { name: /^Tạo workspace$/ }))

    await vi.waitFor(() => {
      expect(daDoi).toHaveBeenCalledWith(WS_MOI.id)
    })
  })

  it('tạo XONG thì dialog đóng, không kẹt ở Đang tạo…', async () => {
    // Phiên trả về SAU khi đổi phải CHỨA workspace mới, nếu không `SessionReady`
    // ném Phiên không có workspace nào và test đo nhầm màn lỗi.
    const PHIEN_MOI = {
      ...FAKE_SESSION,
      workspaces: [
        ...FAKE_SESSION.workspaces,
        { id: WS_MOI.id, slug: 'san_dong_nam', name: WS_MOI.name, plan: null },
      ],
      currentWorkspaceId: WS_MOI.id,
    }
    server.use(
      http.post('/api/v1/workspaces', () => HttpResponse.json(WS_MOI, { status: 201 })),
      http.post('/api/v1/me/workspace', () => HttpResponse.json(PHIEN_MOI)),
    )
    boot()

    await moDialog()
    await userEvent.type(screen.getByLabelText(/Tên workspace/), 'Sàn Đông Nam')
    await userEvent.click(screen.getByRole('button', { name: /^Tạo workspace$/ }))

    // Switcher nằm trong <Sidebar>, NGOÀI `key` của routes/_app.tsx — đổi
    // workspace remount <Outlet> chứ không remount sidebar. Nên dialog KHÔNG tự
    // biến mất; ai đó phải đóng nó.
    await vi.waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Đang tạo/ })).not.toBeInTheDocument()
  })

  it('409 trùng tên: hiện lỗi TRONG dialog, dialog KHÔNG đóng', async () => {
    server.use(
      http.post('/api/v1/workspaces', () =>
        HttpResponse.json(
          {
            error: {
              code: 'WORKSPACE_TRUNG_TEN',
              message: 'Tổ chức của bạn đã có một workspace tên đó',
            },
          },
          { status: 409 },
        ),
      ),
    )
    boot()

    await moDialog()
    await userEvent.type(screen.getByLabelText(/Tên workspace/), 'Trùng')
    await userEvent.click(screen.getByRole('button', { name: /^Tạo workspace$/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/đã có một workspace/)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // Tên vừa gõ phải còn đó — mất nó là bắt gõ lại một cái tên vừa bị từ chối.
    expect(screen.getByLabelText(/Tên workspace/)).toHaveValue('Trùng')
  })

  it('hiện MÃ DỰ KIẾN đã fold dấu ngay khi gõ', async () => {
    boot()
    await moDialog()
    await userEvent.type(screen.getByLabelText(/Tên workspace/), 'Sàn Đông Nam')
    // `s_n_ng_nam` cũng khớp regex của DB — nên test phải neo giá trị ĐÚNG, không
    // chỉ neo "có hiện gì đó".
    expect(await screen.findByText('san_dong_nam')).toBeInTheDocument()
  })

  it('nút Tạo bị chặn khi ô tên rỗng', async () => {
    boot()
    await moDialog()
    expect(screen.getByRole('button', { name: /^Tạo workspace$/ })).toBeDisabled()
  })

  // `member KHÔNG thấy mục Tạo workspace mới` XOÁ 2026-08-15: cổng `org_role='owner'`
  // ở `service.tao()` đã bỏ — ai đăng nhập được cũng tạo được workspace, và người
  // tạo thành "Quản trị" của nó.

  it('Esc đóng dialog', async () => {
    boot()
    await moDialog()
    await userEvent.keyboard('{Escape}')
    await vi.waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})
