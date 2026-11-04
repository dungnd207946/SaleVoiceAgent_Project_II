/**
 * Màn `/users` — bảng thành viên của WORKSPACE đang mở (2026-08-09).
 *
 * Thay `tests/user-admin.test.tsx` (trục tổ chức) và `tests/members.test.tsx`
 * (bảng chỉ-đọc). Cả hai xoá ở Task 6.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { NHAN_LIFECYCLE } from '../src/features/auth/nhan'
import {
  FAKE_SESSION,
  RESET_LOI_MOI_GIA,
  RESET_USERS_GIA,
  RESET_VAI_TRO_GIA,
  RESET_WS_DANG_MO,
} from '../src/lib/msw/handlers'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'
import { boGiaLap, giaLapManHinh } from './man-hinh'

function boot(duong = '/users') {
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

/**
 * GIẢ hình học cho hai bài canh hướng mở của menu `⋯` (⑦c ⑦d).
 *
 * BẮT BUỘC phải giả: jsdom không có engine bố cục nên `getBoundingClientRect` trả
 * 0 ở MỌI phần tử — luật lật của `MenuHang` đo trên số thật, nên không giả thì cả
 * hai bài xanh TRIVIALLY và không bài nào chứng minh được điều gì.
 *
 * Phân biệt hai hộp bằng `data-testid="menu-hang"`: `MenuHang` đo đúng hai thứ, hộp mục (có
 * testid) và thẻ bọc nút `⋯` (không có). `overflowY` của mọi tổ tiên trong jsdom
 * là `visible` ⇒ `vungCat()` rơi về `{tren: 0, duoi: window.innerHeight}`, tức
 * ngưỡng dưới là `window.innerHeight`.
 */
function giaHinhHoc(hopMuc: Partial<DOMRect>, thebocNut: Partial<DOMRect>) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    const o = this.getAttribute('data-testid') === 'menu-hang' ? hopMuc : thebocNut
    return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, ...o } as DOMRect
  })
}

/** Hướng menu `⋯` đang mở — `MenuHang` phơi ra qua `data-huong`. */
function huongMenu(): string | null {
  return screen.getByTestId('menu-hang').getAttribute('data-huong')
}

/**
 * Hàng của một người — tìm TRONG `<main>`.
 *
 * Khoanh vùng là BẮT BUỘC: menu danh tính ở đáy panel luôn hiện tên người đang
 * đăng nhập, nên `screen.findByText(ten)` trần khớp hai chỗ — và chỗ ngoài bảng
 * không nằm trong `<tr>` nào, nên `.closest('tr')` trả `null` và bài đỏ ở một
 * dòng cách xa nguyên nhân.
 */
async function hangCua(ten: string): Promise<HTMLElement> {
  const main = within(await screen.findByRole('main'))
  const tr = (await main.findByText(ten)).closest('tr')
  expect(tr, `không thấy hàng của ${ten}`).not.toBeNull()
  return tr as HTMLElement
}

/**
 * Fixture bảng thành viên — ĐẶT TƯỜNG MINH, không dựa vào fake mặc định.
 *
 * `USERS_GIA` rải ba người qua HAI workspace và `GET /members` chỉ trả người của
 * `WS_DANG_MO`, nên "ai có mặt trong bảng" là một chi tiết của fake sẽ đổi. Buộc
 * bài test vào đó là buộc nó vào thứ không phải hợp đồng.
 */
// `kind: 'member'` TƯỜNG MINH ở cả ba (2026-08-22, chín trường từ `MemberOut`):
// bộ lọc trạng thái của `UserAdmin` giờ rẽ theo `kind` TRƯỚC `lifecycle` (một
// hàng thiếu `kind` sẽ rớt khỏi MỌI bộ lọc trạng thái, kể cả bộ lọc của chính
// nó) — thiếu trường này từng làm bài ④ đỏ ngay khi hàng lời mời được thêm vào
// describe dưới, không phải vì bài ④ sai mà vì fixture chưa theo hợp đồng mới.
const CHU = {
  kind: 'member' as const,
  // CHÍNH MÌNH luôn — hàng này gánh cả hai điều kiện ẩn mục gỡ (là owner, và là
  // người đang đăng nhập). Cần `FAKE_SESSION` để `laChinhMinh` đúng.
  userId: FAKE_SESSION.user.id,
  name: 'Trần Hải Đăng',
  email: 'dang@anphuland.vn',
  roleId: null,
  role: null,
  lifecycle: 'active' as const,
  invitedAt: null,
  expiresAt: null,
}
const LAN = {
  kind: 'member' as const,
  userId: 'u_fake_lan',
  name: 'Nguyễn Thị Lan',
  email: 'lan@anphuland.vn',
  roleId: 'role_gia_qt',
  role: 'Quản trị',
  lifecycle: 'active' as const,
  invitedAt: null,
  expiresAt: null,
}
const CHO = {
  kind: 'member' as const,
  userId: 'u_fake_cho',
  name: 'Người Chờ Mời',
  email: 'cho@anphuland.vn',
  roleId: 'role_gia_xem',
  role: 'Người xem',
  lifecycle: 'pending' as const,
  invitedAt: null,
  expiresAt: null,
}

function datBang(hang: readonly unknown[] = [CHU, LAN, CHO]) {
  server.use(http.get('/api/v1/members', () => HttpResponse.json(hang)))
}

beforeEach(() => {
  RESET_USERS_GIA()
  RESET_VAI_TRO_GIA()
  RESET_WS_DANG_MO()
  RESET_LOI_MOI_GIA()
  datBang()
})

// `giaHinhHoc()` vá `HTMLElement.prototype` — không tháo ra thì mọi bài chạy SAU
// nó vẫn thấy hình học giả, và bài đỏ sẽ rơi cách xa nguyên nhân.
afterEach(() => {
  vi.restoreAllMocks()
})

describe('màn /users — bảng thành viên workspace', () => {
  it('① một bảng, KHÔNG có hàng tab', async () => {
    boot()
    await screen.findByRole('main')
    await waitFor(() => expect(screen.getAllByRole('table')).toHaveLength(1))
    // Tab «Vai trò» đã rời màn 2026-08-09 — 13 action ở lại backend.
    expect(screen.queryByRole('tab', { name: 'Vai trò' })).toBeNull()
    expect(screen.queryByRole('tablist')).toBeNull()
  })

  it('② hàng hiện tên · email · vai trò · trạng thái', async () => {
    boot()
    const hang = await hangCua('Nguyễn Thị Lan')
    expect(within(hang).getByText('lan@anphuland.vn')).toBeTruthy()
    expect(within(hang).getByText('Quản trị')).toBeTruthy()
    expect(within(hang).getByText('Đang hoạt động')).toBeTruthy()
  })

  it('②c điện thoại: bảng GỌN hai cột — vai trò + trạng thái xuống dòng phụ dưới email', async () => {
    giaLapManHinh(390)
    try {
      boot()
      const hang = await hangCua('Nguyễn Thị Lan')
      expect(hang.querySelectorAll('td')).toHaveLength(2)
      const o = hang.querySelector('td')!
      expect(within(o).getByText('lan@anphuland.vn')).toBeTruthy()
      expect(within(o).getByText('Quản trị')).toBeTruthy()
      expect(within(o).getByText('Đang hoạt động')).toBeTruthy()
      // Bảng gọn không mang móc «cột dính» — nó không cuộn ngang.
      expect(hang.closest('table')).not.toHaveAttribute('data-bang')
    } finally {
      boGiaLap()
    }
  })

  // ②b XOÁ 2026-08-17 — bài «Chủ tổ chức nằm ở ô VAI TRÒ».
  //
  // Nó neo một pill phái sinh từ `MemberOut.isOrgOwner`, mà trường đó phái sinh
  // từ `users.org_role` — cột bị XOÁ ở migration `0106_bo_organizations`. Backend
  // chưa bao giờ trả `isOrgOwner`, nên nhánh pill đó THỰC TẾ chưa từng render trên
  // app thật: `undefined` luôn rơi xuống nhánh `m.role === null`.
  //
  // Bài này xanh suốt thời gian đó vì nó đọc FAKE MSW — và fake CÓ `isOrgOwner:
  // true`. Tức nó là một bài test bảo vệ chính cái sai: nó chứng minh fake khớp
  // component, không chứng minh gì về sản phẩm. Đúng lớp lỗi mà mục Gotchas của
  // CLAUDE.md đã cảnh báo ("một bài test khoá hành vi của fake là bài test bảo vệ
  // chính cái sai").
  //
  // Không thay bằng bài khác: khái niệm «chủ tổ chức» chết cùng tầng organization,
  // không có gì để neo. Nhánh «—» của ô Vai trò vẫn còn và vẫn có bài ②a phủ.

  // ②c ②d — avatar trên hàng thành viên (2026-08-25). Backend `GET /members` nay
  // trả `avatar` (data URI DiceBear, CÙNG công thức `/me`) — bảng phải hiện đúng
  // ảnh người đó đã set ở «Hồ sơ & tuỳ chọn», trước đó nó tự vẽ chữ cái nên LỆCH
  // với avatar chân sidebar của chính người đó (người dùng bắt được trên màn thật).

  const AVATAR_THU =
    "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D'http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg'%2F%3E"

  it('②c hàng thành viên CÓ avatar hiện đúng ẢNH đã set, không còn chữ cái', async () => {
    datBang([{ ...LAN, avatar: AVATAR_THU }])
    boot()
    const hang = await hangCua('Nguyễn Thị Lan')
    expect(hang.querySelector(`img[src="${AVATAR_THU}"]`)).not.toBeNull()
    expect(within(hang).queryByText('NL')).toBeNull()
  })

  it('②d avatar VẮNG (backend cũ chưa trả) ⇒ rơi về chữ cái như trước, không <img>', async () => {
    datBang([LAN])
    boot()
    const hang = await hangCua('Nguyễn Thị Lan')
    expect(hang.querySelector('img')).toBeNull()
    expect(within(hang).getByText('NL')).toBeTruthy()
  })

  it('③ KHÔNG có <select> nào ở chế độ nghỉ — quyền không sửa được bằng một cú lỡ tay', async () => {
    // Luật «xem trước, sửa sau» (CLAUDE.md): một ô chọn QUYỀN luôn sống trong
    // bảng mời gõ nhầm vào dữ liệu đang phát hành. Đổi vai trò đi qua menu ⋯.
    boot()
    const main = within(await screen.findByRole('main'))
    await waitFor(() => expect(main.getAllByRole('row').length).toBeGreaterThan(1))
    // Ô lọc trạng thái là `<select>` HỢP LỆ — nó không ghi gì.
    for (const s of main.queryAllByRole('combobox'))
      expect(s.getAttribute('aria-label')).toMatch(/Lọc/)
  })

  it('④ lọc «Chờ nhận lời mời» chỉ còn hàng pending', async () => {
    boot()
    const main = within(await screen.findByRole('main'))
    await main.findByText('Nguyễn Thị Lan')
    await userEvent.selectOptions(main.getByLabelText(/Lọc theo trạng thái/), 'pending')
    await waitFor(() => expect(main.queryByText('Nguyễn Thị Lan')).toBeNull())
    expect(main.getByText('Người Chờ Mời')).toBeTruthy()
  })

  it('⑤a không tải được — FORBIDDEN nói RÕ «không có quyền»', async () => {
    server.use(
      http.get('/api/v1/members', () =>
        HttpResponse.json({ error: { code: 'FORBIDDEN', message: 'x' } }, { status: 403 }),
      ),
    )
    boot()
    expect(await screen.findByRole('alert')).toHaveTextContent(/không có quyền/i)
  })

  it('⑤b không tải được — lỗi KHÁC (backend chết) nói câu KHÁC hẳn, không đổ lỗi cho quyền', async () => {
    // «Hai nguyên nhân, hai câu» (CLAUDE.md): backend chết mà UI báo "không có
    // quyền" thì người dùng đi xin quyền và không ai báo sự cố. Đây là nhánh
    // ⑤a KHÔNG kiểm — thiếu bài này thì cả hai nhánh của `if (khongCoQuyen)`
    // có thể sụp về cùng một câu mà không test nào bắt được.
    server.use(http.get('/api/v1/members', () => new HttpResponse(null, { status: 500 })))
    boot()
    const canhBao = await screen.findByRole('alert')
    expect(canhBao).toHaveTextContent(/Không tải được danh sách thành viên/)
    expect(canhBao).not.toHaveTextContent(/không có quyền/i)
  })

  it('⑥ đổi vai trò qua ⋯ gửi PATCH mang roleId, KHÔNG mang tên', async () => {
    // `role_gia_xem` -> `role_gia_qt`. Tên «Người xem»/«Quản trị» là của
    // `VAI_TRO_GIA` — fake KHÔNG có vai trò nào tên «CSKH» hay «Biên tập».
    let than: unknown = null
    let duong = ''
    server.use(
      http.patch('/api/v1/members/:id', async ({ request, params }) => {
        than = await request.json()
        duong = String(params.id)
        return HttpResponse.json({ ...CHO, roleId: 'role_gia_qt', role: 'Quản trị' })
      }),
    )
    boot()
    const hang = await hangCua('Người Chờ Mời')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Đổi vai trò…' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.click(within(hop).getByRole('radio', { name: 'Quản trị' }))
    await userEvent.click(within(hop).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(than).toEqual({ roleId: 'role_gia_qt' }))
    expect(duong).toBe('u_fake_cho')
  })

  it('⑥b mở ⋯ → «Đổi vai trò…» → Esc đóng hộp thoại ⇒ focus về nút ⋯ của ĐÚNG hàng đó', async () => {
    // Menu unmount ngay khi chọn mục; nếu focus còn ở mục đó thì nó rơi về <body> và
    // `HopThoai` ghi nhận <body> làm chỗ trả. `MenuHang` phải trả focus về trigger
    // TRƯỚC khi unmount. Có hai hàng mở được menu để chứng minh nó là nút của hàng này.
    boot()
    const hang = await hangCua('Người Chờ Mời')
    const nut = within(hang).getByRole('button', { name: /Thao tác/ })
    await userEvent.click(nut)
    await userEvent.click(await screen.findByRole('button', { name: 'Đổi vai trò…' }))
    await screen.findByRole('dialog')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(nut).toHaveFocus()
    expect(
      within(await hangCua('Nguyễn Thị Lan')).getByRole('button', { name: /Thao tác/ }),
    ).not.toHaveFocus()
  })

  it('⑦ hàng chủ tổ chức (chính mình) hết mục nào để làm ⇒ KHÔNG có nút «Thao tác»', async () => {
    // Gỡ chủ tổ chức là tự khoá cửa tổ chức; hàng này còn là CHÍNH MÌNH, tức tự
    // đá mình ra khỏi màn đang đứng. Backend chặn cả hai bằng 409 — đây là phòng
    // tuyến một, cho ĐỠ RỐI MẮT (PQ_01 §BR-Q03).
    //
    // CHU (chính mình, `roleId: null`, `lifecycle: 'active'`) rớt CẢ BA điều kiện
    // của `muc`: không đổi vai trò (không mang `roleId`), không mời lại (không
    // `pending`), không gỡ (là chính mình). Từ 2026-08-09 tới 2026-08-17 «Sửa hồ
    // sơ…» là mục KHÔNG điều kiện nên CHU vẫn còn đúng một mục và nút «Thao tác»
    // vẫn hiện; mục đó đã gỡ (nó chỉ dẫn tới 403 `FEATURE_DISABLED` của khối
    // `/users*` đang tắt), nên `muc` rỗng và `MenuHang` trả `null` — về đúng
    // trạng thái trước Task 5.
    //
    // Hai hàng còn lại PHẢI có nút — không có phép kiểm đó thì bài này xanh
    // TRIVIALLY khi cả bảng gãy (không hàng nào render, `MenuHang` ném, …), tức
    // canh đúng thứ mà `getAllByRole('button').length > 0` trong menu từng canh. Đừng bỏ.
    boot()
    const hangChu = await hangCua('Trần Hải Đăng')
    expect(within(hangChu).queryByRole('button', { name: /Thao tác/ })).toBeNull()

    for (const ten of ['Nguyễn Thị Lan', 'Người Chờ Mời']) {
      const hang = await hangCua(ten)
      expect(within(hang).getByRole('button', { name: /Thao tác/ })).toBeTruthy()
    }
  })

  it('⑦b menu `⋯` KHÔNG còn mục «Sửa hồ sơ…» ở hàng nào', async () => {
    // Cổng chống dựng lại mục đó mà không đọc lý do. Nó là thứ DUY NHẤT của portal
    // còn chạm `/users*` — khối quản trị user toàn hệ thống mà backend đóng bằng
    // `USERS_ADMIN_ENABLED=false` từ `0106`: cửa quyền cũ (`users.org_role`) biến
    // mất cùng tầng tổ chức, và mở lại cờ là cho Quản trị của MỘT workspace sửa
    // user của MỌI workspace khác.
    //
    // Kiểm ở hàng CHO (`pending` + có `roleId`) vì đó là hàng có NHIỀU mục nhất —
    // hàng ít mục nhất thì phép kiểm "absent" nói được ít nhất.
    boot()
    const hang = await hangCua('Người Chờ Mời')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    const menu = within(await screen.findByTestId('menu-hang')).getAllByRole('button')
    expect(menu.length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /Sửa hồ sơ/ })).toBeNull()
  })

  it('⑦c menu `⋯` chạm đáy vùng cuộn ⇒ LẬT LÊN TRÊN (hàng cuối list không còn bị che)', async () => {
    // Bug người dùng báo 2026-08-17: mở menu ở hàng CUỐI list thì thẻ bị che, phải
    // cuộn list xuống mới thấy. Nguyên nhân là HAI tầng cắt lồng nhau ở
    // `components/ui/Bang.tsx` — `TheBang` (`overflow-hidden` + `max-h-[560px]`) và
    // vùng cuộn trong nó (`overflow-auto`) — mà menu là `absolute` nên nằm trong cả
    // hai. Không phải lỗi z-index: nâng `z-50` lên bao nhiêu cũng vô nghĩa với
    // `overflow`.
    //
    // Giả: hộp mục cao 150 và tràn xuống 900 (> `innerHeight` = 768 của jsdom) ⇒
    // chạm đáy; nút ở `top: 400` ⇒ phía trên còn 400 > 150 ⇒ đủ chỗ lật.
    giaHinhHoc({ top: 750, bottom: 900, height: 150 }, { top: 400, bottom: 436, height: 36 })
    boot()
    const hang = await hangCua('Người Chờ Mời')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await screen.findByTestId('menu-hang')
    expect(huongMenu()).toBe('tren')
    // Lật bằng `bottom-full`, KHÔNG phải `top`/`translate`: neo mép DƯỚI của menu
    // vào mép TRÊN của thẻ bọc nút, nên không phụ thuộc chiều cao menu.
    expect(screen.getByTestId('menu-hang').className).toContain('bottom-full')
  })

  it('⑦d còn chỗ phía dưới ⇒ menu `⋯` giữ nguyên hướng xuống', async () => {
    // Vế còn lại của ⑦c, và là chỗ chống «lật vô điều kiện»: lật mọi lúc thì hàng
    // ĐẦU list bị cắt ở mép trên y như hàng cuối từng bị cắt ở mép dưới — đổi một
    // bug lấy một bug. Ở đây hộp mục kết thúc tại 500, dưới ngưỡng 768.
    giaHinhHoc({ top: 350, bottom: 500, height: 150 }, { top: 300, bottom: 336, height: 36 })
    boot()
    const hang = await hangCua('Người Chờ Mời')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await screen.findByTestId('menu-hang')
    expect(huongMenu()).toBe('duoi')
    expect(screen.getByTestId('menu-hang').className).not.toContain('bottom-full')
  })

  it('⑦e chạm đáy NHƯNG phía trên không đủ chỗ ⇒ KHÔNG lật', async () => {
    // Menu cao 150 mà nút chỉ cách mép trên vùng cắt 40px: lật lên là bị cắt ở mép
    // TRÊN, chỗ không cuộn tới được. Giữ `duoi` — ở đó ít nhất còn cuộn tới.
    giaHinhHoc({ top: 750, bottom: 900, height: 150 }, { top: 40, bottom: 76, height: 36 })
    boot()
    const hang = await hangCua('Người Chờ Mời')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await screen.findByTestId('menu-hang')
    expect(huongMenu()).toBe('duoi')
  })

  it('⑧ gỡ một thành viên thường gọi DELETE /members/{id}', async () => {
    let daGoi = ''
    server.use(
      http.delete('/api/v1/members/:id', ({ params }) => {
        daGoi = String(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot()
    const hang = await hangCua('Người Chờ Mời')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Gỡ khỏi workspace' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.click(within(hop).getByRole('button', { name: 'Gỡ' }))
    await waitFor(() => expect(daGoi).toBe('u_fake_cho'))
  })

  it('⑨ mục mời lại CHỈ có trên hàng pending', async () => {
    boot()
    const hangChay = await hangCua('Nguyễn Thị Lan') // active
    await userEvent.click(within(hangChay).getByRole('button', { name: /Thao tác/ }))
    expect(screen.queryByRole('button', { name: 'Gửi lại lời mời' })).toBeNull()
    await userEvent.keyboard('{Escape}')

    const hangCho = await hangCua('Người Chờ Mời') // pending
    await userEvent.click(within(hangCho).getByRole('button', { name: /Thao tác/ }))
    expect(await screen.findByRole('button', { name: 'Gửi lại lời mời' })).toBeTruthy()
  })

  it('⑩ bấm «Gửi lại lời mời» gọi POST /members/{id}/invite và hiện link trả về', async () => {
    // ⑨ chỉ kiểm mục CÓ MẶT, không bấm nó — nên `moiLaiThanhVien`, `urlMoi`, và
    // dòng hiện `linkMoi` đều KHÔNG có phép kiểm nào bắt được nếu bị gỡ. Đây là
    // hành động mang tác dụng phụ thật (huỷ token mời cũ), nên cần một bài bấm
    // thật, kiểm cả ĐƯỜNG GỌI lẫn KẾT QUẢ hiện ra — cùng khuôn ⑥⑧.
    let daGoi = ''
    server.use(
      http.post('/api/v1/members/:id/invite', ({ params }) => {
        daGoi = String(params.id)
        return HttpResponse.json({ invitePath: '/invite/tok_gia_lai_xyz' })
      }),
    )
    boot()
    const hang = await hangCua('Người Chờ Mời')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Gửi lại lời mời' }))
    await waitFor(() => expect(daGoi).toBe('u_fake_cho'))
    expect(
      await within(hang).findByText(`${window.location.origin}/invite/tok_gia_lai_xyz`),
    ).toBeTruthy()
  })

  it('⑪ mời 2 email cùng lúc gửi ĐÚNG một request {emails, roleId}', async () => {
    const than: unknown[] = []
    server.use(
      http.post('/api/v1/members', async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(
          {
            invites: [
              {
                email: 'lan@anphuland.vn',
                userId: 'u_lan',
                invitePath: '/invite/tok_a',
                daCo: false,
              },
              { email: 'minh@anphuland.vn', userId: 'u_minh', invitePath: null, daCo: true },
            ],
          },
          { status: 201 },
        )
      }),
    )
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    const o = within(hop).getByLabelText(/Email/)
    await userEvent.type(o, 'lan@anphuland.vn{enter}minh@anphuland.vn{enter}')
    await userEvent.click(within(hop).getByRole('radio', { name: 'Người xem' }))
    await userEvent.click(within(hop).getByRole('button', { name: 'Gửi lời mời' }))

    await waitFor(() => expect(than).toHaveLength(1))
    // MỘT request cho cả lô, không phải một request mỗi email — đó là điểm của
    // «mời một bước». `toHaveLength(1)` là phần canh việc đó.
    expect(than[0]).toEqual({
      emails: ['lan@anphuland.vn', 'minh@anphuland.vn'],
      roleId: 'role_gia_xem',
    })
  })

  it('⑫ panel kết quả hiện link cho người MỚI, và nói rõ người đã có', async () => {
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          {
            invites: [
              {
                email: 'lan@anphuland.vn',
                userId: 'u_lan',
                invitePath: '/invite/tok_a',
                daCo: false,
              },
              { email: 'minh@anphuland.vn', userId: 'u_minh', invitePath: null, daCo: true },
            ],
          },
          { status: 201 },
        ),
      ),
    )
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.type(
      within(hop).getByLabelText(/Email/),
      'lan@anphuland.vn{enter}minh@anphuland.vn{enter}',
    )
    await userEvent.click(within(hop).getByRole('radio', { name: 'Người xem' }))
    await userEvent.click(within(hop).getByRole('button', { name: 'Gửi lời mời' }))

    // Người MỚI: có link để copy — backend chưa có mailer.
    expect(await within(hop).findByDisplayValue(/\/invite\/tok_a$/)).toBeTruthy()
    // Người ĐÃ CÓ tài khoản: không sinh lời mời, và phải nói ra.
    expect(within(hop).getByText(/minh@anphuland\.vn/)).toBeTruthy()
    expect(within(hop).getByText(/đã có tài khoản/i)).toBeTruthy()
  })

  it('⑫b lỗi TỪNG DÒNG (2026-08-17): lô hỗn hợp invites+loi hiện ĐỦ cả hai — người mời được vẫn hiện, người hỏng hiện đúng câu', async () => {
    // «Mời 40 người mà một người hỏng thì 39 người kia vẫn phải vào được» —
    // đây là phép kiểm trực tiếp của luật đó: MỘT response mang cả invites lẫn
    // loi, panel phải hiện ĐỦ hai phía, không phía nào nuốt mất phía kia.
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          {
            invites: [
              {
                email: 'lan@anphuland.vn',
                userId: 'u_lan',
                invitePath: '/invite/tok_a',
                daCo: false,
              },
            ],
            loi: [{ email: 'cho.dang.ky@anphuland.vn', ma: 'USER_PENDING_SIGNUP' }],
          },
          { status: 201 },
        ),
      ),
    )
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.type(
      within(hop).getByLabelText(/Email/),
      'lan@anphuland.vn{enter}cho.dang.ky@anphuland.vn{enter}',
    )
    await userEvent.click(within(hop).getByRole('radio', { name: 'Người xem' }))
    await userEvent.click(within(hop).getByRole('button', { name: 'Gửi lời mời' }))

    // Người mời được VẪN hiện — lỗi của người khác không kéo họ rớt theo.
    // (Email "lan@anphuland.vn" xuất hiện ở CẢ nhãn `sr-only` lẫn span hiện —
    // `findByDisplayValue` trên chính ô link là phép khẳng định không mập mờ.)
    expect(await within(hop).findByDisplayValue(/\/invite\/tok_a$/)).toBeTruthy()
    // Người hỏng hiện ĐÚNG câu cho USER_PENDING_SIGNUP, kèm email của họ.
    const canhBaoLoi = within(hop).getByText(/đang chờ hoàn tất đăng ký/i)
    expect(canhBaoLoi).toHaveTextContent(/cho\.dang\.ky@anphuland\.vn/)
  })

  it('⑫c loi rỗng — KHÔNG render khối lỗi nào (không phải một khung trống lúc nào cũng hiện)', async () => {
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          {
            invites: [
              {
                email: 'lan@anphuland.vn',
                userId: 'u_lan',
                invitePath: '/invite/tok_a',
                daCo: false,
              },
            ],
            loi: [],
          },
          { status: 201 },
        ),
      ),
    )
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.type(within(hop).getByLabelText(/Email/), 'lan@anphuland.vn{enter}')
    await userEvent.click(within(hop).getByRole('radio', { name: 'Người xem' }))
    await userEvent.click(within(hop).getByRole('button', { name: 'Gửi lời mời' }))

    await within(hop).findByDisplayValue(/\/invite\/tok_a$/)
    // Khối lỗi chỉ có MỘT vai `alert` trong hộp thoại này (form đóng nên
    // `gui.error` không còn) — `loi: []` không được để lại một `role="alert"`
    // rỗng nào cả.
    expect(within(hop).queryByRole('alert')).toBeNull()
    expect(within(hop).queryByText(/USER_PENDING_SIGNUP/)).toBeNull()
    expect(within(hop).queryByText(/không mời được/i)).toBeNull()
  })

  it('⑬ email trùng bị bỏ, và không gửi được khi chưa có email nào', async () => {
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    expect(within(hop).getByRole('button', { name: 'Gửi lời mời' })).toBeDisabled()
    await userEvent.type(within(hop).getByLabelText(/Email/), 'a@x.vn{enter}a@x.vn{enter}')
    expect(within(hop).getAllByRole('button', { name: /Bỏ a@x\.vn/ })).toHaveLength(1)
  })

  it('⑭ email đang gõ dở (chưa Enter) khi bấm Gửi vẫn được gộp — không rơi mất theo nhịp blur/click', async () => {
    // `userEvent.click()` KHÔNG bắt được race này: nó tự chèn một nhịp chờ
    // giữa các sự kiện DOM cấp thấp, nên `blur` luôn kịp flush state TRƯỚC
    // khi `click` chạy — dù `onClick` gọi thẳng `gui.mutate()` không qua
    // `dangGo`. Race THẬT xảy ra khi trình duyệt phát `blur` rồi `click` như
    // MỘT cú bấm — cùng một nhịp xử lý sự kiện, chưa kịp render lại giữa
    // chừng. `act()` bọc CẢ HAI `fireEvent` trong MỘT lần mới ép đúng nhịp
    // đó: state của `blur` bị hoãn tới cuối, và `onClick` phải tự đọc `dangGo`
    // (không được cậy `emails` đã có sẵn) mới không rơi mất email đang gõ dở.
    const than: unknown[] = []
    server.use(
      http.post('/api/v1/members', async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json({ invites: [] }, { status: 201 })
      }),
    )
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.click(within(hop).getByRole('radio', { name: 'Người xem' }))
    const o = within(hop).getByLabelText(/Email/)
    await userEvent.type(o, 'lan@anphuland.vn{enter}minh@anphuland.vn')
    const nutGui = within(hop).getByRole('button', { name: 'Gửi lời mời' })
    await act(async () => {
      fireEvent.blur(o)
      fireEvent.click(nutGui)
    })

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({
      emails: ['lan@anphuland.vn', 'minh@anphuland.vn'],
      roleId: 'role_gia_xem',
    })
  })

  it('⑮ dán một khối nhiều email tách theo phẩy/chấm phẩy/khoảng trắng — dán từ Excel vẫn chạy', async () => {
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.click(within(hop).getByLabelText(/Email/))
    await userEvent.paste('a@x.vn, b@x.vn; c@x.vn')

    expect(within(hop).getByText('a@x.vn')).toBeTruthy()
    expect(within(hop).getByText('b@x.vn')).toBeTruthy()
    expect(within(hop).getByText('c@x.vn')).toBeTruthy()
  })
})

describe('hàng lời mời trong bảng (2026-08-22)', () => {
  // Hình dạng `MemberOut` với `kind: 'invite'` — email CHƯA có tài khoản, nên
  // `userId`/`name`/`lifecycle` đều `null` CÙNG LÚC (đúng docstring `MemberOut`
  // ở `thanhVien.ts`). Email THẬT trùng seed của `LOI_MOI_GIA` (`handlers.ts`),
  // không phải bịa — cùng chuỗi mà `tests/thanh-vien-seam.test.ts` dùng cho
  // nhánh THÀNH CÔNG của `guiLaiLoiMoi`/`thuHoiLoiMoi`.
  const MOI = {
    kind: 'invite' as const,
    userId: null,
    name: null,
    email: 'chuaco@anphuland.vn',
    roleId: 'role_gia_xem',
    role: 'Người xem',
    lifecycle: null,
    invitedAt: '2026-08-22T03:00:00Z',
    expiresAt: '2026-08-29T03:00:00Z',
  }

  // HÀNG THỨ HAI, cùng hình dạng null (review round 1): `MOI` một mình không canh
  // được lớp lỗi «React key rỗng» — hai hàng invite khác email đều mang
  // `userId: null`, nên `key={m.userId}` (bug đã sửa) cho CẢ HAI cùng một chuỗi
  // khoá `"null"`. Một danh sách với hai phần tử-anh-em trùng key là chỗ React
  // không còn giữ được từng hàng đúng danh tính của nó qua một lần render lại —
  // và điều đó chỉ lộ ra khi CÓ một lần render lại (đổi bộ lọc/tìm kiếm), không
  // lộ ở lần mount đầu (lúc đó DOM dựng thẳng từ props, key chưa cần dùng tới).
  const MOI2 = {
    kind: 'invite' as const,
    userId: null,
    name: null,
    email: 'chuabiet@anphuland.vn',
    roleId: 'role_gia_qt',
    role: 'Quản trị',
    lifecycle: null,
    invitedAt: '2026-08-22T03:00:00Z',
    expiresAt: '2026-08-29T03:00:00Z',
  }

  // HÀNG THỨ BA — `invite_existing` (`userId`/`name`/`lifecycle` KHÔNG null, xem
  // finding A): backend `LEFT JOIN`s `users` nên một lời mời cho một email ĐÃ có
  // tài khoản mang theo cái tên đó. Trước đợt sửa này, `UserAdmin.tsx` render
  // `m.name ?? m.email` làm dòng chính — với hàng này `m.name` LUÔN có mặt, nên
  // email (định danh THẬT của hàng, đúng thứ `guiLaiLoiMoi`/`thuHoiLoiMoi` gửi
  // đi) không hiện ở đâu trên hàng cả. `LOI_MOI_GIA` (`lib/msw/handlers.ts`) đã
  // được vá cùng lỗi này ở tầng seam/msw; fixture riêng ở đây canh CHÍNH component.
  const MOI3 = {
    kind: 'invite' as const,
    userId: 'u_fake_minh',
    name: 'Phạm Văn Minh',
    email: 'minh@anphuland.vn',
    roleId: 'role_gia_qt',
    role: 'Quản trị',
    lifecycle: 'active' as const,
    invitedAt: '2026-08-22T03:00:00Z',
    expiresAt: '2026-08-29T03:00:00Z',
  }

  // Đè LẠI fixture của `beforeEach` ngoài cùng (chạy SAU nó) — ba hàng cũ + BA
  // hàng lời mời (hai `invite_new` + một `invite_existing`), để bảng có ĐỦ BA
  // hình dạng hàng cùng lúc như dữ liệu thật.
  beforeEach(() => {
    datBang([CHU, LAN, CHO, MOI, MOI2, MOI3])
  })

  it('email chưa có tài khoản hiện email làm định danh + «chưa có tài khoản» + «Chờ xác nhận lời mời»', async () => {
    boot()
    const hang = await hangCua('chuaco@anphuland.vn')
    expect(within(hang).getByText('chưa có tài khoản')).toBeTruthy()
    expect(within(hang).getByText('Chờ xác nhận lời mời')).toBeTruthy()
  })

  it('email ĐÃ có tài khoản (invite_existing): email vẫn là dòng chính, tên đi kèm ở dòng phụ (finding A)', async () => {
    boot()
    // `hangCua` tìm hàng bằng CHÍNH email — nếu `UserAdmin.tsx` hồi quy về
    // `m.name ?? m.email` làm dòng chính, email không còn ở đâu trong hàng và
    // `hangCua` ném ngay tại đây (không thấy `getByText('minh@anphuland.vn')`).
    const hang = await hangCua('minh@anphuland.vn')
    // Tên vẫn có mặt — CẠNH trạng thái tài khoản, không thay nó.
    expect(within(hang).getByText(/Phạm Văn Minh/)).toBeTruthy()
    expect(within(hang).getByText(/đã có tài khoản/)).toBeTruthy()
    expect(within(hang).getByText('Chờ xác nhận lời mời')).toBeTruthy()
  })

  it('menu ⋯ của hàng lời mời chỉ có Gửi lại và Thu hồi — KHÔNG Đổi vai trò, KHÔNG Gỡ khỏi workspace', async () => {
    boot()
    const hang = await hangCua('chuaco@anphuland.vn')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    expect(await screen.findByRole('button', { name: 'Gửi lại lời mời' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Thu hồi lời mời' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Đổi vai trò…' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Gỡ khỏi workspace' })).toBeNull()
  })

  it('bấm «Gửi lại lời mời» gọi POST theo EMAIL, không phải /members/null', async () => {
    // Đây là phép kiểm trực tiếp cho lớp lỗi mà cả fixture này tồn tại để canh:
    // một `m.userId` (`null`) chạy lọt vào đường ghi thay vì `m.email` sẽ dựng
    // `/members/null/invite` — 404 không ai hiểu vì sao.
    let duong = ''
    server.use(
      http.post('/api/v1/members/invites/:email/resend', ({ params }) => {
        duong = String(params.email)
        return HttpResponse.json({ invitePath: null })
      }),
    )
    boot()
    const hang = await hangCua('chuaco@anphuland.vn')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Gửi lại lời mời' }))
    await waitFor(() => expect(duong).toBe('chuaco@anphuland.vn'))
    expect(duong).not.toBe('null')
  })

  it('bấm «Thu hồi lời mời» gọi DELETE theo EMAIL, không phải /members/null', async () => {
    let duong = ''
    server.use(
      http.delete('/api/v1/members/invites/:email', ({ params }) => {
        duong = String(params.email)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot()
    const hang = await hangCua('chuaco@anphuland.vn')
    await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Thu hồi lời mời' }))
    await waitFor(() => expect(duong).toBe('chuaco@anphuland.vn'))
    expect(duong).not.toBe('null')
  })

  it('hai hàng lời mời khác email, CÙNG userId null: KHÔNG phát cảnh báo "key trùng" của React (review round 1 — key rỗng)', async () => {
    // Lớp lỗi cụ thể: nếu key của hàng quay lại `m.userId` trần, HAI hàng
    // invite ở đây cùng đứng vào key `null` — và React đọc `key={null}` (khác
    // `undefined`) thành CHUỖI `"null"`, tức hai anh em TRÙNG key THẬT, không
    // phải "thiếu key" (thiếu key mới fallback về index và không cảnh báo gì).
    //
    // ĐÃ THỬ một bài "canh hệ quả" (bấm menu hàng thứ hai / mở link rồi gõ lại
    // ô tìm để buộc reconcile) TRƯỚC KHI chọn cách này — cả hai lần đều XANH dù
    // key sai, vì: (a) `mutationFn` luôn đóng đúng `m` của phần tử JSX hiện tại
    // bất kể fiber nào bị tái dùng, và (b) đo bằng tay không thấy `linkMoi` bị
    // rớt qua reconcile như suy đoán ban đầu — cơ chế khoá trùng của React
    // không lộ ra ở đúng hai hệ quả đó trong bản React đang chạy ở repo này.
    // Cảnh báo `console.error` là DẤU HIỆU DUY NHẤT đo được chắc chắn: React
    // phát nó NGAY LÚC RENDER mảng có hai key trùng, đồng bộ, không phụ thuộc
    // reconciliation timing hay việc có tương tác gì sau đó — đây cũng là lựa
    // chọn thứ hai review round 1 chấp nhận.
    const loi = vi.spyOn(console, 'error').mockImplementation(() => {})
    boot()
    await hangCua('chuaco@anphuland.vn')
    await hangCua('chuabiet@anphuland.vn')

    const canhBaoKeyTrung = loi.mock.calls.some((doi) =>
      doi.some((a) => typeof a === 'string' && a.includes('same key')),
    )
    expect(canhBaoKeyTrung).toBe(false)
  })

  it('tìm theo email vẫn khớp hàng lời mời — `m.name` null không ném và không rơi mất hàng', async () => {
    boot()
    const main = within(await screen.findByRole('main'))
    await main.findByText('Nguyễn Thị Lan')
    await userEvent.type(main.getByLabelText(/Tìm theo/), 'chuaco@')
    expect(await main.findByText('chuaco@anphuland.vn')).toBeTruthy()
    expect(main.queryByText('Nguyễn Thị Lan')).toBeNull()
    // Không lẫn hàng invite thứ hai — "chuaco@" không phải tiền tố của nó.
    expect(main.queryByText('chuabiet@anphuland.vn')).toBeNull()
  })

  it('lọc trạng thái «Chờ xác nhận lời mời» chỉ còn hàng invite — `cho-xac-nhan` không phải một Lifecycle', async () => {
    boot()
    const main = within(await screen.findByRole('main'))
    await main.findByText('Nguyễn Thị Lan')
    await userEvent.selectOptions(main.getByLabelText(/Lọc theo trạng thái/), 'cho-xac-nhan')
    await waitFor(() => expect(main.queryByText('Nguyễn Thị Lan')).toBeNull())
    // CẢ HAI hàng invite hiện — bộ lọc là theo `kind`, không phải một fixture
    // đơn lẻ tình cờ khớp.
    expect(main.getByText('chuaco@anphuland.vn')).toBeTruthy()
    expect(main.getByText('chuabiet@anphuland.vn')).toBeTruthy()
    // Hàng THÀNH VIÊN `pending` (di sản, «Chưa đặt mật khẩu») không được lọt vào
    // bộ lọc này — hai trục `kind` và `lifecycle` không được gộp nhầm.
    expect(main.queryByText('Người Chờ Mời')).toBeNull()
  })

  it('nhãn `pending` của hàng THÀNH VIÊN nay là «Chưa đặt mật khẩu» — «Chờ nhận lời mời» đã chuyển nghĩa sang hàng lời mời', () => {
    expect(NHAN_LIFECYCLE.pending).toBe('Chưa đặt mật khẩu')
  })
})

describe('panel kết quả mời (2026-08-22)', () => {
  /**
   * Một lượt mời hoàn chỉnh qua UI: mở dialog → gõ email → Enter → chọn vai
   * trò đầu → Gửi. Viết một lần ở đây thay vì lặp trong mỗi `it`: ba bài dưới
   * chỉ khác THÂN RESPONSE, và các thao tác này là nghi thức để tới được panel
   * kết quả — cùng khuôn bài ⑫/⑫b/⑫c ở trên (mở qua nút «Mời thành viên» của
   * màn `/users`, KHÔNG render `MoiThanhVienDialog` trần: file này không có
   * `Wrapper` nào cho nó, và `boot()` đã dựng đủ router + provider).
   */
  async function moiXong(email: string) {
    await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.type(within(hop).getByLabelText(/Email/), `${email}{enter}`)
    await userEvent.click(within(hop).getAllByRole('radio')[0]!)
    await userEvent.click(within(hop).getByRole('button', { name: 'Gửi lời mời' }))
    return hop
  }

  it('email đã có tài khoản: nói ĐÃ GỬI THƯ, không nói «đã thêm thẳng»', async () => {
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          {
            invites: [{ email: 'daco@x.vn', userId: 'u_daco', invitePath: null, daCo: true }],
            loi: [],
          },
          { status: 201 },
        ),
      ),
    )
    boot()
    const hop = await moiXong('daco@x.vn')
    expect(await within(hop).findByText(/đã gửi thư xác nhận tham gia/)).toBeInTheDocument()
    expect(within(hop).queryByText(/đã thêm thẳng vào workspace/)).not.toBeInTheDocument()
  })

  it('USER_ALREADY_MEMBER có câu riêng', async () => {
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          { invites: [], loi: [{ email: 'trong@x.vn', ma: 'USER_ALREADY_MEMBER' }] },
          { status: 201 },
        ),
      ),
    )
    boot()
    const hop = await moiXong('trong@x.vn')
    expect(await within(hop).findByText(/đã là thành viên của workspace này/)).toBeInTheDocument()
  })

  it('email chưa có tài khoản vẫn có ô link khi mailer tắt', async () => {
    // Trước 2026-08-22 khối link chỉ render cho `daCo === false`. Nay CẢ HAI
    // nhánh phát token, nên gate cũ sẽ giấu mất link của người đã có tài khoản
    // — và ngược lại, một người CHƯA có tài khoản vẫn phải thấy link của
    // chính họ (đây là bài đó, phía ngược).
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          {
            invites: [{ email: 'x@x.vn', userId: null, invitePath: '/invite/tk', daCo: false }],
            loi: [],
          },
          { status: 201 },
        ),
      ),
    )
    boot()
    const hop = await moiXong('x@x.vn')
    expect(await within(hop).findByDisplayValue(/\/invite\/tk$/)).toBeInTheDocument()
  })

  it('daCo=true VÀ mailer tắt (invitePath khác null): KHÔNG nói "đã gửi thư" trong khi vẫn đưa link để tự gửi tay', async () => {
    // Ca đúng thứ round 1 review bắt: `daCo:true` không còn đủ để suy ra thư
    // đã đi — phải xét CẢ `invitePath`. Trước khi sửa, câu tổng hợp lọc CHỈ
    // theo `daCo` nên panel nói "đã gửi thư xác nhận tham gia" ĐỒNG THỜI đưa
    // một ô link ngay dưới banner "Chưa gửi được email tự động" cho ĐÚNG một
    // người này — hai câu ngược nhau, và admin tin nhầm câu "đã gửi" thì
    // không ai forward link, lời mời không tới ai.
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          {
            invites: [
              { email: 'daco2@x.vn', userId: 'u_daco2', invitePath: '/invite/xyz', daCo: true },
            ],
            loi: [],
          },
          { status: 201 },
        ),
      ),
    )
    boot()
    const hop = await moiXong('daco2@x.vn')
    // Vẫn đưa link để admin tự gửi tay — mailer tắt cho người này.
    expect(await within(hop).findByDisplayValue(/\/invite\/xyz$/)).toBeInTheDocument()
    // KHÔNG có câu nào nói thư đã gửi cho họ — chỉ một người trong response
    // này, nên nếu câu đó xuất hiện Ở ĐÂU CŨNG được là panel đang nói dối.
    expect(within(hop).queryByText(/đã gửi thư xác nhận tham gia/)).not.toBeInTheDocument()
    // Sự thật "đã có tài khoản" không mất — vẫn phải đọc được ở đâu đó, để
    // admin hiểu vì sao hàng này khác (không cần đặt mật khẩu mới).
    expect(within(hop).getByText(/đã có tài khoản/)).toBeInTheDocument()
  })
})
