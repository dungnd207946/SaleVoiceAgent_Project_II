/**
 * Đăng xuất phải là REQUEST THẬT, và chỉ được coi là xong khi server nói xong.
 *
 * Điểm dễ làm sai nhất nằm ở nhánh lỗi: xoá state client rồi đẩy về /login khi
 * request hỏng là NÓI DỐI — phiên vẫn sống trong Redis, và người dùng vừa rời
 * một máy dùng chung với niềm tin là mình đã thoát. Test số 5 canh đúng chỗ đó.
 *
 * Khối danh tính trong menu (tên · email · tổ chức · vai trò) test ở cuối: nó là
 * thứ duy nhất trên màn phân biệt được hai tài khoản của hai tổ chức khác nhau.
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

function boot(queryClient: QueryClient) {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/dashboard'] }),
  })
  render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
  return router
}

/**
 * Mở menu danh tính ở ĐÁY panel.
 *
 * Trước 2026-08-07 nó nằm chung menu với workspace switcher, nên helper này bấm
 * vào nút mang tên workspace («An Phú Land»). Rail + panel tách hai thứ ra hai
 * đầu của panel: workspace mở đầu, danh tính khép lại — nên nút cần bấm giờ
 * mang TÊN NGƯỜI ĐANG ĐĂNG NHẬP.
 */
async function moMenu() {
  await userEvent.click(await screen.findByRole('button', { name: FAKE_SESSION.user.name }))
}

/** QueryClient mới cho MỖI test — dùng chung là để cache của test trước rò sang test sau. */
const moiClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

describe('đăng xuất', () => {
  it('menu ở đáy panel có mục Đăng xuất', async () => {
    boot(moiClient())

    await moMenu()

    expect(await screen.findByRole('button', { name: /Đăng xuất/ })).toBeInTheDocument()
  })

  it('gọi POST /api/v1/auth/logout, không chỉ xoá state client', async () => {
    const daGoi = vi.fn()
    server.use(
      http.post('/api/v1/auth/logout', () => {
        daGoi()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot(moiClient())

    await moMenu()
    await userEvent.click(await screen.findByRole('button', { name: /Đăng xuất/ }))

    await vi.waitFor(() => {
      expect(daGoi).toHaveBeenCalled()
    })
  })

  it('204 rồi thì điều hướng tới /login', async () => {
    const router = boot(moiClient())

    await moMenu()
    await userEvent.click(await screen.findByRole('button', { name: /Đăng xuất/ }))

    await vi.waitFor(() => {
      expect(router.state.location.pathname).toBe('/login')
    })
  })

  it('XOÁ cache, không để dữ liệu workspace cũ sống qua lượt đăng nhập sau', async () => {
    /**
     * Người sau đăng nhập trên cùng tab là một người KHÁC. Còn cache của người
     * trước thì màn đầu tiên họ mở hiện dữ liệu của workspace mà họ không thuộc
     * — rò đúng thứ hợp đồng cách ly tồn tại để chặn, chỉ là ở tầng client.
     */
    const queryClient = moiClient()
    queryClient.setQueryData(['du-an'], ['Dự án của người dùng CŨ'])
    boot(queryClient)

    await moMenu()
    await userEvent.click(await screen.findByRole('button', { name: /Đăng xuất/ }))

    await vi.waitFor(() => {
      expect(queryClient.getQueryData(['du-an'])).toBeUndefined()
    })
  })

  it('nút «Tiếp tục với Google» hiện ngay ở /login, không phải đợi reload', async () => {
    /**
     * Hồi quy 2026-08-19. `clear()` chạy SAU `navigate('/login')`, tức là sau khi
     * NutGoogle đã mount và đã bắn `GET /api/v1/auth/providers`. Nó huỷ luôn query
     * đang bay; response về sau đó rơi vào hư không, observer nằm lại với
     * `data === undefined`. Vì `staleTime: Infinity` và component KHÔNG remount
     * (người dùng đứng yên ở /login), không gì kích hoạt fetch lại — nút biến mất
     * cho tới khi người dùng tự F5.
     *
     * Chờ DOM chứ không chờ request: NutGoogle im lặng ở CẢ hai trạng thái
     * đang-hỏi và đã-tắt, nên chỉ có cái <a> hiện ra mới phân biệt được.
     */
    boot(moiClient())

    await moMenu()
    await userEvent.click(await screen.findByRole('button', { name: /Đăng xuất/ }))

    expect(await screen.findByRole('link', { name: /Google/i })).toBeInTheDocument()
  })

  it('request hỏng thì KHÔNG điều hướng — phiên vẫn sống, nói đã thoát là nói dối', async () => {
    server.use(
      http.post('/api/v1/auth/logout', () =>
        HttpResponse.json(
          { error: { code: 'REDIS_DOWN', message: 'Không thu hồi được phiên' } },
          { status: 500 },
        ),
      ),
    )
    const router = boot(moiClient())

    await moMenu()
    await userEvent.click(await screen.findByRole('button', { name: /Đăng xuất/ }))

    expect(await screen.findByText(/Không thu hồi được phiên/)).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/dashboard')
  })

  it('menu hiện tên và email của người đang đăng nhập', async () => {
    boot(moiClient())

    await moMenu()

    const menu = await screen.findByRole('group', { name: 'Tài khoản' })
    expect(menu).toHaveTextContent(FAKE_SESSION.user.email)
  })

  // `huy hiệu vai trò đọc từ orgRole` XOÁ 2026-08-15: `session.orgRole` và huy hiệu
  // của nó không còn — chỉ còn vai trò TRONG workspace, đã nằm trong `actions`.
})
