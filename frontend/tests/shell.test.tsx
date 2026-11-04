/**
 * Canh shell render được và canh việc lọc nav theo quyền.
 *
 * Từ 2026-08-07 shell là RAIL (mảng) + PANEL (màn của mảng đang mở), không còn
 * một sidebar phẳng. Bốn thứ đáng test ở đây, không hơn:
 *  1. mọi route đều render được — không màn nào crash lúc người ta mở
 *  2. panel CHỈ hiện màn của mảng đang mở, và bấm rail thì đổi mảng
 *  3. thiếu quyền thì mục nav không hiện (và mảng rỗng thì mất luôn icon rail)
 *  4. đổi ngôn ngữ đổi nhãn mảng và nhãn màn
 */
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { ACTIONS } from '../src/lib/actions'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import { NavPanel } from '../src/components/shell/NavPanel'
import { Rail } from '../src/components/shell/Rail'
import { Topbar } from '../src/components/shell/Topbar'
import { CO_EN, LangProvider } from '../src/i18n'
import { SessionProvider } from '../src/lib/session'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'
import type { Action } from '../src/lib/actions'

/** Path route cấp một của `_app`, đọc từ cây route thật. */
const DUONG_APP = Object.values(createRouter({ routeTree }).routesById)
  .filter((r) => r.parentRoute?.id === '/_app')
  .map((r) => r.fullPath)

/**
 * Dựng router trong bộ nhớ với ĐÚNG các path của cây route thật, nhưng mỗi màn
 * là một dấu `data-screen="…"` — test canh shell, không canh nội dung màn.
 */
function renderShell(initialPath: string) {
  const rootRoute = createRootRoute({
    component: () => (
      <div>
        <Rail />
        <NavPanel />
        <Topbar />
        <Outlet />
      </div>
    ),
  })

  const routes = DUONG_APP.map((p) =>
    createRoute({
      getParentRoute: () => rootRoute,
      path: p,
      component: () => <p>{`data-screen="${p.slice(1)}"`}</p>,
    }),
  )

  const router = createRouter({
    routeTree: rootRoute.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  })

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <SessionProvider>
          <RouterProvider router={router} />
        </SessionProvider>
      </LangProvider>
    </QueryClientProvider>,
  )
}

/** Rail — cột icon của bốn mảng. */
async function rail(): Promise<HTMLElement> {
  return await screen.findByRole('navigation', { name: 'Mảng' })
}

/**
 * Panel — danh sách màn của mảng đang mở. `aria-label` của nó LÀ tên mảng, nên
 * hàm này nhận tên vào: gọi `panel('Vận hành')` vừa lấy được panel vừa khẳng
 * định đúng mảng đang mở.
 *
 * Nhãn mảng và nhãn màn có thể trùng chữ («Agent» là cả hai), và tiêu đề topbar
 * dùng lại nhãn màn — nên mọi truy vấn phải khoanh vùng, không thì
 * `getByText('Agent')` khớp ba chỗ và test đỏ vì lý do sai.
 */
async function panel(tenMang: string): Promise<HTMLElement> {
  return await screen.findByRole('navigation', { name: tenMang })
}

/** Tiêu đề màn ở topbar. */
function pageTitle(): HTMLElement {
  return screen.getByRole('heading', { level: 1 })
}

/** Ghi đè phiên để thử giao diện của một vai trò hẹp. */
function withActions(actions: readonly Action[]) {
  server.use(http.get('/api/v1/me', () => HttpResponse.json({ ...FAKE_SESSION, actions })))
}

describe('mọi route đều render được', () => {
  for (const p of DUONG_APP) {
    it(p, async () => {
      renderShell(p)
      expect(await screen.findByText(`data-screen="${p.slice(1)}"`)).toBeInTheDocument()
    })
  }
})

describe('rail — ba mảng', () => {
  it('hiện đủ ba mảng, và mảng chứa màn đang mở được đánh dấu', async () => {
    renderShell('/dashboard')
    const r = within(await rail())
    for (const ten of ['Vận hành', 'Agent', 'Quản trị']) {
      expect(r.getByText(ten)).toBeInTheDocument()
    }
    expect(r.getByText('Vận hành').closest('a')).toHaveAttribute('data-current', 'true')
    expect(r.getByText('Agent').closest('a')).not.toHaveAttribute('data-current')
  })

  it('đang ở màn KHÁC trong cùng mảng thì mảng vẫn sáng', async () => {
    // /convos không phải màn đầu của Vận hành (/dashboard là). Đây là ca mà một
    // `aria-current` viết tay từng cho ra giá trị khác với ca ở trên.
    renderShell('/convos')
    const r = within(await rail())
    expect(r.getByText('Vận hành').closest('a')).toHaveAttribute('data-current', 'true')
  })

  it('bấm một mảng thì ĐIỀU HƯỚNG tới màn đầu của mảng đó', async () => {
    renderShell('/dashboard')
    const r = within(await rail())

    await userEvent.click(r.getByText('Quản trị'))

    // `usersNav` («Thành viên») là mục đầu của mảng Quản trị — trở lại 2026-08-17
    // sau hai ngày bị ẩn. Nó đứng TRƯỚC «Nhật ký» có chủ ý: quản lý người trong
    // workspace là việc làm hằng ngày, nhật ký là việc tra khi cần.
    expect(await screen.findByText('data-screen="users"')).toBeInTheDocument()
    expect(pageTitle()).toHaveTextContent('Thành viên')
  })

  it('màn không có mục nav vẫn tô sáng đúng mảng — /pform thuộc Agent', async () => {
    renderShell('/pform')
    const r = within(await rail())
    expect(r.getByText('Agent').closest('a')).toHaveAttribute('data-current', 'true')
    // và topbar vẫn có tiêu đề dù màn này không có mục nav.
    // «Kiến thức» — ĐÚNG nhãn của mục nav dẫn tới đây (`/projects`), không phải
    // nhãn khối «Bất động sản» bọc nó. Hai cái đó từng lệch nhau, xem `OFF_NAV`.
    expect(pageTitle()).toHaveTextContent('Kiến thức')
  })
})

describe('panel — chỉ màn của mảng đang mở', () => {
  it('ở /dashboard thì thấy 3 màn Vận hành, KHÔNG thấy màn của mảng khác', async () => {
    renderShell('/dashboard')
    const p = within(await panel('Vận hành'))

    expect(p.getByText('Tổng quan')).toBeInTheDocument()
    expect(p.getByText('Hội thoại')).toBeInTheDocument()
    expect(p.getByText('Chất lượng')).toBeInTheDocument()
    // «Lịch hẹn» rời nav 2026-08-13 — route còn, mục nav thì không.
    expect(p.queryByText('Lịch hẹn')).not.toBeInTheDocument()

    // «Tài liệu chung» thuộc mảng Agent, «Bất động sản» thuộc Dữ liệu
    expect(p.queryByText('Tài liệu chung')).not.toBeInTheDocument()
    expect(p.queryByText('Bất động sản')).not.toBeInTheDocument()
  })

  it('mảng Agent chia khối: phần chung trước, rồi mỗi lĩnh vực một khối', async () => {
    renderShell('/agent')
    const p = within(await panel('Agent'))

    expect(p.getAllByRole('link').map((a) => a.getAttribute('data-nav'))).toEqual([
      // khối CHUNG — áp cho mọi lĩnh vực
      'agent',
      'kb',
      'thu-agent',
      // khối «Bất động sản» — Kiến thức + Dữ liệu ngoài + Kỹ năng + Kịch bản
      'projects',
      'du-lieu-ngoai',
      'ky-nang-bds',
      'kich-ban',
      // khối HỆ THỐNG — xuống cuối, dựng một lần rồi thôi
      'api',
      'domains',
    ])
    expect(p.getByText('Bất động sản')).toBeInTheDocument()
  })

  it('dữ liệu nghiệp vụ nằm TRONG Agent, không phải một mảng riêng', async () => {
    // «agent nói sai giá căn hộ, sửa ở đâu?» — không được bắt người dùng đoán
    // xem giá căn hộ là "dữ liệu" hay là "agent".
    renderShell('/projects')
    const p = within(await panel('Agent'))
    // Chọn theo `data-nav`: nhãn «Kiến thức» CỐ Ý trùng nhau giữa các lĩnh vực
    // (mỗi cái nằm dưới nhãn khối của lĩnh vực mình).
    expect(p.getByRole('link', { name: /Kiến thức/, current: 'page' })).toHaveAttribute(
      'data-nav',
      'projects',
    )
    expect(within(await rail()).queryByText('Dữ liệu')).not.toBeInTheDocument()
  })

  it('khối lĩnh vực là DROPDOWN mở sẵn — gập lại thì con biến mất', async () => {
    renderShell('/agent')
    const p = within(await panel('Agent'))

    const dau = p.getByRole('button', { name: /Bất động sản/ })
    expect(dau).toHaveAttribute('aria-expanded', 'true')
    expect(p.getByRole('link', { name: /Kỹ năng/ })).toBeInTheDocument()

    await userEvent.click(dau)
    expect(dau).toHaveAttribute('aria-expanded', 'false')
    expect(p.queryByRole('link', { name: /Kỹ năng/ })).not.toBeInTheDocument()
    // Đầu khối vẫn còn — gập là gập con, không phải xoá lĩnh vực.
    expect(p.getByRole('button', { name: /Bất động sản/ })).toBeInTheDocument()
  })

  it('đang Ở TRONG một lĩnh vực thì khối không gập được — không giấu mục đang sáng', async () => {
    renderShell('/ky-nang-bds')
    const p = within(await panel('Agent'))

    const dau = p.getByRole('button', { name: /Bất động sản/ })
    await userEvent.click(dau)

    expect(dau).toHaveAttribute('aria-expanded', 'true')
    expect(p.getByRole('link', { name: /Kỹ năng/ })).toBeInTheDocument()
  })

  it('nhãn khối biến mất cùng khối khi hết quyền, không treo trên khoảng trống', async () => {
    // Chỉ WORKSPACE_ADMIN ⇒ mảng Agent còn «API Keys», còn cả bốn mục của khối
    // «Bất động sản» (catalog.read · kb_web.read · agent_config.read) bị ẩn —
    // khối rỗng hẳn và phải mất luôn nhãn.
    withActions([ACTIONS.WORKSPACE_ADMIN, ACTIONS.OVERVIEW_READ])
    renderShell('/api-keys')

    const p = within(await panel('Agent'))
    expect(p.getByText('API Keys')).toBeInTheDocument()
    expect(p.queryByText('Bất động sản')).not.toBeInTheDocument()
  })
})

describe('lọc nav theo quyền — ẩn nút KHÔNG phải bảo vệ (PQ_01 §BR-Q03)', () => {
  it('thiếu WORKSPACE_ADMIN thì mất Thành viên · API Keys · Gói cước', async () => {
    withActions([ACTIONS.OVERVIEW_READ, ACTIONS.CONVOS_READ, ACTIONS.AUDIT_READ])
    renderShell('/dashboard')

    const p = within(await panel('Vận hành'))
    expect(p.getByText('Tổng quan')).toBeInTheDocument()

    // Ba màn đó thuộc mảng Agent/Quản trị — kiểm qua rail: mảng Agent mất hết
    // mục nên mất luôn icon, còn Quản trị chỉ còn Nhật ký (nhờ AUDIT_READ — từ
    // 2026-08-25 mục này khoá theo audit.read, không còn overview.read).
    const r = within(await rail())
    expect(r.queryByText('Agent')).not.toBeInTheDocument()
    await userEvent.click(r.getByText('Quản trị'))
    const q = within(await panel('Quản trị'))
    expect(q.getByText('Nhật ký')).toBeInTheDocument()
    expect(q.queryByText('Thành viên')).not.toBeInTheDocument()
    expect(q.queryByText('Gói cước')).not.toBeInTheDocument()
  })

  it('mảng không còn mục nào thì mất luôn icon trên rail', async () => {
    // Chỉ CONVOS_READ ⇒ hai mảng Agent · Quản trị rỗng hoàn toàn.
    withActions([ACTIONS.CONVOS_READ])
    renderShell('/convos')

    const r = within(await rail())
    expect(r.getByText('Vận hành')).toBeInTheDocument()
    expect(r.queryByText('Agent')).not.toBeInTheDocument()
    expect(r.queryByText('Quản trị')).not.toBeInTheDocument()
  })

  it('mảng đầu tiên còn quyền là nơi dấu thương hiệu dẫn tới, không phải /dashboard cứng', async () => {
    // Không có OVERVIEW_READ ⇒ Tổng quan bị ẩn; logo phải trỏ tới màn được phép
    // đầu tiên chứ không phải một cái 403.
    withActions([ACTIONS.CONVOS_READ])
    renderShell('/convos')

    const logo = await screen.findByRole('link', { name: 'NobleX Agent' })
    expect(logo).toHaveAttribute('href', '/convos')
  })
})

describe('workspace switcher — đỉnh panel', () => {
  it('hiện 3 workspace và đổi được', async () => {
    renderShell('/dashboard')
    const trigger = await screen.findByRole('button', { name: /An Phú Land/ })
    await userEvent.click(trigger)

    const menu = screen.getByRole('group', { name: 'Workspace của bạn' })
    expect(within(menu).getByText('Sunrise Land')).toBeInTheDocument()
    expect(within(menu).getByText('Havenly Property')).toBeInTheDocument()
    // Workspace đang mở nói bằng `aria-current`, không chỉ bằng dấu ✓.
    expect(within(menu).getByRole('button', { name: /An Phú Land/ })).toHaveAttribute(
      'aria-current',
      'true',
    )

    await userEvent.click(within(menu).getByRole('button', { name: /Sunrise Land/ }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Sunrise Land/ })).toBeInTheDocument()
    })
  })

  it('disclosure, không phải role=menu: Esc đóng và trả focus về nút mở', async () => {
    renderShell('/dashboard')
    const trigger = await screen.findByRole('button', { name: /An Phú Land/ })
    await userEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    await userEvent.tab()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('group', { name: 'Workspace của bạn' })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})

describe('user menu — đáy panel', () => {
  it('mở ra có danh tính, Hồ sơ và Đăng xuất', async () => {
    renderShell('/dashboard')
    await userEvent.click(await screen.findByRole('button', { name: /Trần Hải Đăng/ }))

    const menu = screen.getByRole('group', { name: 'Tài khoản' })
    expect(within(menu).getByText(FAKE_SESSION.user.email)).toBeInTheDocument()
    expect(within(menu).getByRole('link', { name: /Hồ sơ/ })).toBeInTheDocument()
    expect(within(menu).getByRole('button', { name: /Đăng xuất/ })).toBeInTheDocument()
  })

  it('Esc đóng và trả focus về nút mở', async () => {
    renderShell('/dashboard')
    const trigger = await screen.findByRole('button', { name: /Trần Hải Đăng/ })
    await userEvent.click(trigger)
    await userEvent.tab()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('group', { name: 'Tài khoản' })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})

describe('i18n', () => {
  // EN đang tắt (`CO_EN`, i18n) — bài này tự chạy lại khi bật.
  it.skipIf(!CO_EN)('đổi sang EN thì nhãn mảng, nhãn màn và tiêu đề đổi theo', async () => {
    renderShell('/dashboard')
    expect(within(await rail()).getByText('Vận hành')).toBeInTheDocument()
    expect(within(await panel('Vận hành')).getByText('Tổng quan')).toBeInTheDocument()
    expect(pageTitle()).toHaveTextContent('Tổng quan')

    // Nút ngôn ngữ ĐÃ RỜI thanh trên, vào menu «Hồ sơ & tuỳ chọn» (2026-08-09)
    // — nên phải mở menu đó ra trước. Hai nút `aria-pressed` trong nhóm «Ngôn ngữ»
    // (`menuitemradio` bỏ 2026-10-05 khi menu thôi là `role="menu"`).
    await userEvent.click(await screen.findByRole('button', { name: /Trần Hải Đăng/ }))
    await userEvent.click(
      within(screen.getByRole('group', { name: 'Ngôn ngữ' })).getByRole('button', { name: 'en' }),
    )

    const r = within(await rail())
    expect(r.getByText('Operate')).toBeInTheDocument()
    expect(r.queryByText('Vận hành')).not.toBeInTheDocument()
    expect(within(await panel('Operate')).getByText('Overview')).toBeInTheDocument()
    expect(pageTitle()).toHaveTextContent('Overview')
  })
})

describe('EN đang tắt (CO_EN = false)', () => {
  it.skipIf(CO_EN)(
    'menu không còn hàng «Ngôn ngữ», và `en` đã lưu từ trước thì vẫn hiện tiếng Việt',
    async () => {
      localStorage.setItem('odyssey.lang', 'en')
      try {
        renderShell('/dashboard')
        expect(within(await rail()).getByText('Vận hành')).toBeInTheDocument()
        expect(document.documentElement.lang).toBe('vi')
        await userEvent.click(await screen.findByRole('button', { name: /Trần Hải Đăng/ }))
        expect(screen.queryByRole('group', { name: 'Ngôn ngữ' })).toBeNull()
        expect(screen.queryByText('Ngôn ngữ')).toBeNull()
      } finally {
        localStorage.removeItem('odyssey.lang')
      }
    },
  )
})

describe('avatar user ở chân panel', () => {
  const AVATAR_THU =
    "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D'http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg'%2F%3E"

  it('phiên có avatar ⇒ ẢNH ở cả nút lẫn khối danh tính trong menu mở ra', async () => {
    server.use(
      http.get('/api/v1/me', () =>
        HttpResponse.json({ ...FAKE_SESSION, user: { ...FAKE_SESSION.user, avatar: AVATAR_THU } }),
      ),
    )
    renderShell('/dashboard')
    // Ảnh mang alt rỗng (trang trí — cùng lý lẽ aria-hidden của ô initials) nên
    // vắng mặt trong cây a11y; truy bằng querySelector theo đúng src.
    const nut = await screen.findByRole('button', { name: /Trần Hải Đăng/ })
    await userEvent.click(nut)
    await waitFor(() =>
      expect(document.querySelectorAll(`img[src="${AVATAR_THU}"]`)).toHaveLength(2),
    )
  })

  it('phiên KHÔNG có avatar (backend cũ) ⇒ giữ ô chữ initials, không <img> nào', async () => {
    // Fake /me mặc định NAY mang avatar (khớp backend mới) — ca «backend cũ»
    // phải tự bóc trường đó ra, không dựa vào fake dùng chung.
    const userCu = { ...FAKE_SESSION.user }
    delete userCu.avatar
    server.use(http.get('/api/v1/me', () => HttpResponse.json({ ...FAKE_SESSION, user: userCu })))
    renderShell('/dashboard')
    await screen.findByRole('button', { name: /Trần Hải Đăng/ })
    expect(screen.getAllByText('TĐ').length).toBeGreaterThan(0)
    // KHÔNG so `img` trần — shell có sẵn logo `/logo-nx-agent.svg`; thứ cần vắng
    // là ảnh avatar (data URI), không phải mọi <img>.
    expect(document.querySelector('img[src^="data:"]')).not.toBeInTheDocument()
  })
})

describe('phiên hỏng thì nổi lên thành lỗi, không thành shell rỗng', () => {
  it('GET /api/v1/me trả 500 ⇒ hiện lỗi + nút thử lại', async () => {
    server.use(http.get('/api/v1/me', () => new HttpResponse(null, { status: 500 })))
    renderShell('/dashboard')

    expect(await screen.findByText('Không tải được phiên đăng nhập')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
    // shell không được render nửa vời
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})
