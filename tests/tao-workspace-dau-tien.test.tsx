/**
 * Màn `/tao-workspace-dau-tien` — tạo xong PHẢI sang `/dashboard`, không quay lại.
 *
 * BUG 2026-08-17, hai nguyên nhân nối tiếp nhau. Backend đã sửa (phiên Redis nay
 * trỏ vào workspace vừa tạo); đây là nguyên nhân THỨ HAI, thuần client:
 *
 *   ① `LoginForm` ghi `setQueryData(['session'], phien)` với `currentWorkspaceId:
 *      null`, rồi `SessionReady` đá sang màn này.
 *   ② Màn này nằm NGOÀI `_app`, nên `SessionProvider` unmount ⇒ query `['session']`
 *      thành INACTIVE. Cache vẫn còn (gcTime mặc định 5 phút).
 *   ③ `invalidateQueries` KHÔNG refetch query inactive — nó chỉ đánh dấu stale, và
 *      `await` của nó trả về ngay.
 *   ④ Điều hướng `/dashboard` ⇒ `SessionProvider` mount lại ⇒ React Query trả
 *      CACHE CŨ ngay lập tức (`currentWorkspaceId: null`) trong lúc refetch chạy
 *      nền ⇒ `useEffect` của `SessionReady` bắn ⇒ đá về lại màn này.
 *
 * Đúng lớp lỗi mà `switchWorkspace` (`lib/session.tsx`) đã ghi cảnh báo và tránh
 * bằng `removeQueries` + `setQueryData` thay vì `invalidateQueries`.
 *
 * Bài test dựng lại ĐÚNG trạng thái đó: cache phiên gieo sẵn với
 * `currentWorkspaceId: null` — không gieo thì không có gì cũ để trả về, và bài sẽ
 * xanh cả khi bug còn nguyên.
 */
import { describe, expect, it } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

const WS_MOI = {
  id: 'ws_dau_tien',
  name: 'Sàn Đầu Tiên',
  lifecycle: 'active',
  status: 'provisioning',
  createdAt: '2026-08-17T10:00:00Z',
}

/** Phiên NGAY SAU đăng ký: có tài khoản, chưa thuộc workspace nào. */
const PHIEN_CHUA_CO_WS = {
  ...FAKE_SESSION,
  workspaces: [],
  currentWorkspaceId: null,
  actions: [],
}

/** Phiên SAU khi backend đã trỏ phiên vào workspace mới. */
const PHIEN_DA_CO_WS = {
  ...FAKE_SESSION,
  workspaces: [WS_MOI],
  currentWorkspaceId: WS_MOI.id,
}

function boot() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // GIEO CACHE CŨ — đây là mấu chốt của bài test, xem docstring đầu file.
  qc.setQueryData(['session'], PHIEN_CHUA_CO_WS)

  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/tao-workspace-dau-tien'] }),
  })
  render(
    <QueryClientProvider client={qc}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
  return router
}

describe('/tao-workspace-dau-tien', () => {
  it('tạo xong thì sang /dashboard và KHÔNG quay lại màn tạo', async () => {
    let daTao = false
    server.use(
      http.post('/api/v1/workspaces', async () => {
        daTao = true
        return HttpResponse.json(WS_MOI, { status: 201 })
      }),
      // `/me` trả phiên MỚI ngay từ lần gọi đầu — backend đã sửa. Nên nếu FE vẫn
      // đá về màn tạo thì lỗi CHẮC CHẮN nằm ở client, không phải hợp đồng.
      http.get('/api/v1/me', () => HttpResponse.json(daTao ? PHIEN_DA_CO_WS : PHIEN_CHUA_CO_WS)),
    )

    const router = boot()

    await userEvent.type(await screen.findByLabelText(/tên workspace/i), 'Sàn Đầu Tiên')
    await userEvent.click(screen.getByRole('button', { name: /tạo workspace/i }))

    // Chờ MÀN cũ biến mất, không chỉ chờ pathname đổi. `router.state` cập nhật
    // trước khi React commit, nên khẳng định pathname một mình sẽ xanh trong lúc
    // người dùng vẫn đang nhìn màn tạo workspace. Và nếu bị đá về thì `waitFor`
    // này hết hạn — đó chính là cách bài test bắt được bug.
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: /tạo workspace đầu tiên/i })).toBeNull()
    })
    expect(router.state.location.pathname).toBe('/dashboard')

    // Và ĐỨNG YÊN ở đó. Cú đá về là một `navigate` trong `useEffect` của
    // `SessionReady`, nó bắn SAU khi pathname đã kịp bằng /dashboard một nhịp —
    // nên phải để React chạy hết các effect còn treo rồi kiểm lại. `act` bọc lấy
    // nhịp chờ, nếu không render đang treo sẽ không được flush và bài test đọc
    // một DOM cũ.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    expect(router.state.location.pathname).toBe('/dashboard')
    expect(screen.queryByRole('heading', { name: /tạo workspace đầu tiên/i })).toBeNull()
  })

  it('lỗi khi tạo thì ở lại màn tạo và hiện thông báo', async () => {
    server.use(
      http.post('/api/v1/workspaces', () =>
        HttpResponse.json(
          { error: { code: 'WORKSPACE_TRUNG_TEN', message: 'Trùng tên' } },
          { status: 409 },
        ),
      ),
      http.get('/api/v1/me', () => HttpResponse.json(PHIEN_CHUA_CO_WS)),
    )

    const router = boot()

    await userEvent.type(await screen.findByLabelText(/tên workspace/i), 'Trùng')
    await userEvent.click(screen.getByRole('button', { name: /tạo workspace/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/đã có một workspace tên này/i)
    expect(router.state.location.pathname).toBe('/tao-workspace-dau-tien')
  })
})
