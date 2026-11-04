/**
 * ⌘K — canh bốn lời hứa của palette:
 *  1. mở/đóng bằng phím, đóng bằng Esc
 *  2. gõ KHÔNG DẤU vẫn tìm ra («hoi thoai» → Hội thoại, «du an» → Bất động sản)
 *  3. ↑↓ đi xuyên mảng, ↵ mở màn đang chọn
 *  4. cùng phép lọc quyền với rail — màn rail đã ẩn KHÔNG lọt vào palette
 *
 * Lời hứa ④ là lý do file này tồn tại. Ba cái trên hỏng thì người dùng thấy
 * ngay; ④ hỏng thì đó là một cửa sau lặng lẽ vào đúng những màn vừa được ẩn đi.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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
import { CommandPalette } from '../src/components/shell/CommandPalette'
import { boDau } from '../src/lib/boDau'
import { LangProvider } from '../src/i18n'
import { SessionProvider } from '../src/lib/session'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'
import type { Action } from '../src/lib/actions'

/** Path route cấp một của `_app`, đọc từ cây route thật. */
const DUONG_APP = Object.values(createRouter({ routeTree }).routesById)
  .filter((r) => r.parentRoute?.id === '/_app')
  .map((r) => r.fullPath)

function boot(initialPath = '/dashboard') {
  const rootRoute = createRootRoute({
    component: () => (
      <div>
        <CommandPalette />
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

function withActions(actions: readonly Action[]) {
  server.use(http.get('/api/v1/me', () => HttpResponse.json({ ...FAKE_SESSION, actions })))
}

/** Mở palette. Chờ phiên nạp xong trước — `useNavGroups` đọc `can()` từ nó. */
async function moPalette(): Promise<HTMLElement> {
  await screen.findByText(/data-screen=/)
  await userEvent.keyboard('{Meta>}k{/Meta}')
  return await screen.findByRole('dialog', { name: 'Tìm màn' })
}

describe('mở và đóng', () => {
  it('⌘K mở, Esc đóng', async () => {
    boot()
    const hop = await moPalette()
    expect(hop).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('⌘K lần hai thì đóng lại', async () => {
    boot()
    await moPalette()
    await userEvent.keyboard('{Meta>}k{/Meta}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('Ctrl+K cũng mở — bàn phím PC cắm vào máy Mac vẫn phải dùng được', async () => {
    boot()
    await screen.findByText(/data-screen=/)
    await userEvent.keyboard('{Control>}k{/Control}')
    expect(await screen.findByRole('dialog', { name: 'Tìm màn' })).toBeInTheDocument()
  })
})

describe('tìm không dấu', () => {
  it('«hoi thoai» ra Hội thoại', async () => {
    boot()
    const hop = await moPalette()
    await userEvent.type(within(hop).getByRole('combobox'), 'hoi thoai')

    expect(within(hop).getByText('Hội thoại')).toBeInTheDocument()
    expect(within(hop).queryByText('Tổng quan')).not.toBeInTheDocument()
  })

  /**
   * Bài này TRƯỚC ĐÂY đi qua giao diện: gõ «du lieu» phải ra «Nhật ký & Dữ
   * liệu». Nhãn đó đổi thành «Nhật ký» (2026-08-09), và sau lần đổi tên ấy
   * KHÔNG nhãn màn nào còn chứa `đ` — «Dự án» thì đã thành «Kiến thức» từ trước.
   *
   * Nên nhánh `đ` không còn đường nào chạm tới qua giao diện. Gọi thẳng `boDau`
   * là bước lùi về chất lượng bài test, và tôi ghi rõ ra thay vì lặng lẽ xoá
   * bài: một nhánh KHÔNG được canh còn tệ hơn một bài canh ở tầng thấp. Ngày nào
   * có một nhãn màn mang chữ `đ`, kéo bài này trở lại tầng giao diện.
   */
  it('`đ` không phải dấu tổ hợp — NFD không tách được, phải thay tay', async () => {
    // `normalize('NFD')` KHÔNG đụng tới `đ`: nó là một ký tự Unicode riêng, không
    // phải `d` + dấu. Thiếu hai dòng `.replace` trong `boDau` thì hai dòng dưới
    // trả về «đu lieu» / «Đon hang» và mọi truy vấn không dấu đều trượt.
    expect(boDau('Dữ liệu')).toBe('du lieu')
    expect(boDau('Đơn hàng')).toBe('don hang')
    // Và nhánh dấu tổ hợp bình thường vẫn phải chạy.
    expect(boDau('Hội thoại')).toBe('hoi thoai')
  })

  it('tiêu đề nhóm mang cả nhãn khối — palette soi đúng cấu trúc panel', async () => {
    boot()
    const hop = await moPalette()
    await userEvent.type(within(hop).getByRole('combobox'), 'ky nang')
    // «Kỹ năng» nằm trong khối «Bất động sản» của mảng «Agent»
    expect(within(hop).getByText('Agent · Bất động sản')).toBeInTheDocument()
  })

  it('không khớp gì thì nói thẳng, không hiện danh sách rỗng', async () => {
    boot()
    const hop = await moPalette()
    await userEvent.type(within(hop).getByRole('combobox'), 'xyzzy')
    expect(within(hop).getByText('Không có màn nào khớp')).toBeInTheDocument()
  })
})

describe('bàn phím', () => {
  it('↵ mở màn đang chọn', async () => {
    boot()
    const hop = await moPalette()
    // «Nhật ký» — trước 2026-08-13 bài này gõ «lich hen»; mục «Lịch hẹn» đã rời
    // nav nên nó không còn trong palette (đó chính là lời hứa ④ của file này).
    await userEvent.type(within(hop).getByRole('combobox'), 'nhat ky')
    await userEvent.keyboard('{Enter}')

    expect(await screen.findByText('data-screen="audit"')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('↓ đi XUYÊN biên mảng, không dừng ở cuối mảng đầu', async () => {
    boot()
    const hop = await moPalette()
    // Mảng Vận hành có 4 mục: 3 sau khi «Lịch hẹn» rời nav 2026-08-13, cộng
    // «Chuyển sale» thêm sau đó. Nhấn ↓ bốn lần từ mục 0 phải sang mục đầu của
    // mảng Agent, không quay lại đầu mảng Vận hành.
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}')
    const dangChon = within(hop)
      .getAllByRole('option')
      .find((b) => b.getAttribute('aria-selected') === 'true')
    expect(dangChon).toHaveAttribute('data-cmd', 'agent')
  })

  it('mục đang sáng được ô nhập trỏ tới (aria-activedescendant) — trình đọc biết ↑↓ chọn gì', async () => {
    boot()
    const hop = await moPalette()
    const o = within(hop).getByRole('combobox')
    await userEvent.keyboard('{ArrowDown}')
    const sang = within(hop)
      .getAllByRole('option')
      .find((b) => b.getAttribute('aria-selected') === 'true')!
    expect(o).toHaveAttribute('aria-activedescendant', sang.id)
    expect(o).toHaveFocus()
  })

  it('số màn khớp đọc qua role=status', async () => {
    boot()
    const hop = await moPalette()
    await userEvent.type(within(hop).getByRole('combobox'), 'xyzzy')
    expect(within(hop).getByRole('status')).toHaveTextContent('Không có màn nào khớp')
  })
})

describe('cùng phép lọc quyền với rail', () => {
  it('màn bị ẩn khỏi rail thì KHÔNG lọt vào palette', async () => {
    withActions([ACTIONS.OVERVIEW_READ, ACTIONS.CONVOS_READ])
    boot()
    const hop = await moPalette()

    expect(within(hop).getByText('Tổng quan')).toBeInTheDocument()
    // Cần WORKSPACE_ADMIN — không có thì rail đã ẩn, palette cũng phải ẩn
    expect(within(hop).queryByText('Thành viên')).not.toBeInTheDocument()
    expect(within(hop).queryByText('API Keys')).not.toBeInTheDocument()
    // Cần CATALOG_READ
    expect(within(hop).queryByText('Tài liệu chung')).not.toBeInTheDocument()
  })

  it('mảng rỗng thì không hiện tiêu đề mảng rỗng trong palette', async () => {
    withActions([ACTIONS.CONVOS_READ])
    boot('/convos')
    const hop = await moPalette()

    expect(within(hop).getByText('Hội thoại')).toBeInTheDocument()
    expect(within(hop).queryByText('Quản trị')).not.toBeInTheDocument()
  })
})
