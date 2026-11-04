import { StrictMode } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { boGiaLap, giaLapManHinh } from './man-hinh'
import { server } from '../vitest.setup'
import { routeTree } from '../src/routeTree.gen'
import { LangProvider } from '../src/i18n'
import { FAKE_KICH_BAN } from '../src/features/kich-ban/msw'

function boot(path = '/kich-ban') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        <LangProvider>
          <RouterProvider router={router} />
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
  return router
}

describe('màn Kịch bản', () => {
  it('đủ nút, màu theo ngưỡng, nháp nét đứt', async () => {
    boot()
    for (const n of FAKE_KICH_BAN.nodes)
      expect(await screen.findByTestId(`nut-${n.id}`)).toBeInTheDocument()
    expect(screen.getByTestId('nut-che_dat')).toHaveAttribute('data-mau', 'vang')
    expect(screen.getByTestId('nut-chot')).toHaveAttribute('data-mau', 'do')
    expect(screen.getByTestId('nut-chuyen_that')).toHaveAttribute('data-mau', 'xam')
    // %đạt bằng CHỮ cạnh tên, không chỉ màu chấm (audit 05/10): che_dat đạt 71%; nút xám
    // (chưa đủ 5 lượt chấm) không in số.
    expect(screen.getByTestId('nut-che_dat')).toHaveTextContent('Khách chê đắt · 71%')
    expect(screen.getByTestId('nut-chuyen_that')).not.toHaveTextContent('%')
    expect(screen.getByTestId('nut-goi_dien_ra')).toHaveAttribute('data-nhap', 'true')
  })

  it('bấm nút → ?nut= và mở bảng chi tiết', async () => {
    const router = boot()
    await userEvent.click(await screen.findByTestId('nut-che_dat'))
    expect(router.state.location.search).toMatchObject({ nut: 'che_dat' })
    expect(await screen.findByTestId('bang-chi-tiet')).toBeInTheDocument()
  })

  it('lúc đầu mind map chiếm cả bề ngang, bấm nút thì khung chi tiết trượt vào, Đóng thì trượt ra', async () => {
    boot()
    const khung = await screen.findByTestId('khung-chi-tiet')
    expect(khung).toHaveAttribute('data-mo', 'false')
    expect(screen.queryByText(/Bấm một tình huống/)).toBeNull()
    expect(screen.queryByTestId('bang-chi-tiet')).toBeNull()

    await userEvent.click(screen.getByTestId('nut-che_dat'))
    expect(await screen.findByTestId('bang-chi-tiet')).toBeInTheDocument()
    expect(screen.getByTestId('khung-chi-tiet')).toHaveAttribute('data-mo', 'true')

    await userEvent.click(screen.getByRole('button', { name: 'Đóng' }))
    expect(screen.getByTestId('khung-chi-tiet')).toHaveAttribute('data-mo', 'false')
    expect(screen.queryByTestId('bang-chi-tiet')).toBeNull()
  })

  it('SVG bản đồ vẽ trên lớp riêng (Safari để lại vệt chữ khi bản đồ co giãn)', async () => {
    boot()
    const svg = await screen.findByRole('group', { name: /Sơ đồ cây/ })
    expect(svg).toHaveClass('will-change-transform')
  })

  it('phóng to / thu nhỏ đổi viewBox, Vừa khung trả về toàn cây', async () => {
    boot()
    const svg = await screen.findByRole('group', { name: /Sơ đồ cây/ })
    const dau = svg.getAttribute('viewBox')
    const rong = () => Number(svg.getAttribute('viewBox')!.split(' ')[2])
    const w0 = rong()
    expect(screen.getByRole('button', { name: 'Vừa khung' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Phóng to' }))
    expect(rong()).toBeLessThan(w0)
    await userEvent.click(screen.getByRole('button', { name: 'Thu nhỏ' }))
    await userEvent.click(screen.getByRole('button', { name: 'Thu nhỏ' }))
    expect(rong()).toBeGreaterThan(w0)

    await userEvent.click(screen.getByRole('button', { name: 'Vừa khung' }))
    expect(svg.getAttribute('viewBox')).toBe(dau)
  })

  it('kéo để dời sơ đồ — thả tay trên một tình huống không tính là bấm', async () => {
    const router = boot()
    const nut = await screen.findByTestId('nut-che_dat')
    const svg = screen.getByRole('group', { name: /Sơ đồ cây/ })
    const dau = svg.getAttribute('viewBox')
    // jsdom chưa có PointerEvent — MouseEvent mang đủ clientX/button, React nghe theo TÊN sự kiện.
    const ban = (el: Element, ten: string, x: number) =>
      fireEvent(el, new MouseEvent(ten, { bubbles: true, button: 0, clientX: x, clientY: x }))
    ban(nut, 'pointerdown', 100)
    ban(svg, 'pointermove', 160)
    ban(svg, 'pointerup', 160)
    fireEvent.click(nut)
    expect(svg.getAttribute('viewBox')).not.toBe(dau)
    expect(router.state.location.search).not.toHaveProperty('nut')
  })

  it('Toàn màn hình mở cả sơ đồ lẫn bảng chi tiết, nút đổi thành Thoát', async () => {
    const xin = vi.fn(() => Promise.resolve())
    Element.prototype.requestFullscreen = xin
    try {
      boot('/kich-ban?nut=che_dat')
      await userEvent.click(await screen.findByRole('button', { name: 'Toàn màn hình' }))
      expect(xin).toHaveBeenCalledOnce()
      const khung = xin.mock.contexts[0] as HTMLElement
      expect(khung).toContainElement(screen.getByRole('group', { name: /Sơ đồ cây/ }))
      expect(khung).toContainElement(await screen.findByTestId('bang-chi-tiet'))

      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: khung })
      fireEvent(document, new Event('fullscreenchange'))
      expect(await screen.findByRole('button', { name: 'Thoát toàn màn hình' })).toBeInTheDocument()
    } finally {
      // @ts-expect-error — jsdom không có sẵn, xoá bản giả
      delete Element.prototype.requestFullscreen
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null })
    }
  })

  it('bàn phím: Enter trên một tình huống cũng mở chi tiết', async () => {
    const router = boot()
    const n = await screen.findByTestId('nut-chot')
    n.focus()
    await userEvent.keyboard('{Enter}')
    expect(router.state.location.search).toMatchObject({ nut: 'chot' })
  })

  it('hiện tên tiếng Việt, không hiện mã snake_case', async () => {
    boot()
    const n = await screen.findByTestId('nut-che_dat')
    expect(within(n).getByText('Khách chê đắt')).toBeInTheDocument()
    expect(n.textContent).not.toContain('che_dat')
    // tên nhóm + số đếm (số nằm trong <tspan> riêng) — so cả phần tử <text>
    expect(
      screen.getByText((_, el) => el?.tagName === 'text' && el.textContent === 'Phản đối · 2'),
    ).toBeInTheDocument()
  })

  it('chỉ để xem: không kéo thả, không nút xếp lại, không lưu vị trí', async () => {
    const ghi = vi.spyOn(Storage.prototype, 'setItem')
    try {
      const router = boot()
      fireEvent.click(await screen.findByTestId('nut-che_dat'))
      await screen.findByTestId('bang-chi-tiet')
      expect(router.state.location.search).toMatchObject({ nut: 'che_dat' })
      expect(screen.queryByRole('button', { name: 'Xếp lại' })).toBeNull()
      expect(document.querySelector('[draggable="true"], .react-flow')).toBeNull()
      expect(ghi.mock.calls.filter(([k]) => String(k).startsWith('kich-ban'))).toEqual([])
    } finally {
      ghi.mockRestore()
    }
  })

  it('đổi khoảng ngày gọi lại API với ngay=30', async () => {
    let ngay = ''
    server.use(
      http.get('/api/v1/playbook', ({ request }) => {
        ngay = new URL(request.url).searchParams.get('ngay') ?? ''
        return HttpResponse.json(FAKE_KICH_BAN)
      }),
    )
    boot()
    await screen.findByTestId('nut-che_dat')
    await userEvent.click(screen.getByRole('button', { name: '30 ngày' }))
    await screen.findByTestId('nut-che_dat')
    expect(ngay).toBe('30')
  })

  it('chưa có dữ liệu → dòng báo', async () => {
    server.use(
      http.get('/api/v1/playbook', () =>
        HttpResponse.json({ ...FAKE_KICH_BAN, soDo: {}, coDuLieu: false }),
      ),
    )
    boot()
    expect(await screen.findByText(/Chưa có dữ liệu chấm/)).toBeInTheDocument()
    expect(await screen.findByTestId('nut-che_dat')).toHaveAttribute('data-mau', 'xam')
  })
})

/** jsdom chưa có `PointerEvent`: MouseEvent + gắn tay `pointerId`/`pointerType`. */
function tro(el: Element, ten: string, id: number, x: number, y: number, loai = 'touch') {
  const e = new MouseEvent(ten, { bubbles: true, button: 0, clientX: x, clientY: y })
  Object.defineProperty(e, 'pointerId', { value: id })
  Object.defineProperty(e, 'pointerType', { value: loai })
  fireEvent(el, e)
}

describe('sơ đồ — cảm ứng (tablet)', () => {
  afterEach(() => vi.unstubAllGlobals())

  /** jsdom không có ma trận màn hình — giả một ma trận đơn vị để phép quy đổi chạy. */
  function giaMaTran(svg: Element) {
    ;(svg as SVGSVGElement).getScreenCTM = () =>
      ({ a: 1, inverse: () => ({}) }) as unknown as DOMMatrix
    vi.stubGlobal(
      'DOMPoint',
      class {
        x: number
        y: number
        constructor(x = 0, y = 0) {
          this.x = x
          this.y = y
        }
        matrixTransform() {
          return { x: this.x, y: this.y }
        }
      },
    )
  }

  it('hai ngón chụm ra thì phóng to, ngón thứ hai không làm sơ đồ nhảy', async () => {
    boot()
    const svg = await screen.findByRole('group', { name: /Sơ đồ cây/ })
    giaMaTran(svg)
    const rong = () => Number(svg.getAttribute('viewBox')!.split(' ')[2])
    const w0 = rong()
    tro(svg, 'pointerdown', 1, 100, 100)
    tro(svg, 'pointerdown', 2, 200, 100)
    tro(svg, 'pointermove', 2, 300, 100) // khoảng cách 100 → 200
    expect(rong()).toBeCloseTo(w0 / 2, 0)
    tro(svg, 'pointerup', 2, 300, 100)
    tro(svg, 'pointerup', 1, 100, 100)
  })

  it('nhả chuột ngoài sơ đồ rồi nhấn lại KHÔNG bị đọc thành chụm', async () => {
    boot()
    const svg = await screen.findByRole('group', { name: /Sơ đồ cây/ })
    giaMaTran(svg)
    const vb = svg.getAttribute('viewBox')
    tro(svg, 'pointerdown', 1, 100, 100, 'mouse') // không có pointerup: nhả ngoài khung
    tro(svg, 'pointerdown', 1, 100, 100, 'mouse')
    tro(svg, 'pointermove', 1, 102, 100, 'mouse') // dưới ngưỡng kéo 4px
    expect(svg.getAttribute('viewBox')).toBe(vb)
  })
})

describe('điện thoại — danh sách thay sơ đồ, chi tiết là bottom sheet', () => {
  afterEach(() => boGiaLap())

  it('không vẽ sơ đồ; mỗi tình huống một dòng có tỷ lệ bằng chữ', async () => {
    giaLapManHinh(390)
    boot()
    const ds = await screen.findByRole('navigation', { name: 'Các tình huống kịch bản theo nhóm' })
    expect(screen.queryByRole('group', { name: /Sơ đồ cây/ })).toBeNull()
    const dong = within(ds).getByTestId('dong-che_dat')
    expect(dong).toHaveTextContent('Khách chê đắt')
    expect(dong).toHaveTextContent(/đạt \d+%|chưa đủ lượt chấm|Đang tắt/)
  })

  it('chạm một dòng mở bottom sheet; Đóng thì sheet đi và bỏ ?nut', async () => {
    giaLapManHinh(390)
    const router = boot()
    await userEvent.click(await screen.findByTestId('dong-che_dat'))
    const sheet = await screen.findByRole('dialog', { name: /Chi tiết tình huống Khách chê đắt/ })
    expect(within(sheet).getByTestId('bang-chi-tiet')).toBeInTheDocument()
    expect(router.state.location.search).toMatchObject({ nut: 'che_dat' })
    await userEvent.click(within(sheet).getByRole('button', { name: 'Đóng' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(router.state.location.search).not.toHaveProperty('nut')
  })
})
