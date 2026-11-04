/**
 * Tổng quan — «Cần bạn» (shape 06/10) + tự làm mới (harden cùng lượt).
 *
 * Critique 05/10 (22/40): việc tồn chuyển sale hiện thành một tỉ lệ ở ô cuối
 * («1,3% phiên cần người thật» đọc như tin tốt trong lúc còn ca chưa ai gọi),
 * màn không nói số lấy lúc nào và không tự làm mới. Ô Chuyển sale nay mở bằng
 * số ca chưa liên hệ (`/escalations`, cùng khoá query với `/chuyen-sale`), tỉ
 * lệ lùi xuống dòng phụ; đầu màn có «Cập nhật hh:mm».
 *
 * Số đối chiếu đọc từ `features/ops/msw.ts`: `CA_GIA` có 2 ca `new` (12, 13)
 * và 4 ca tất cả; overview có 302 phiên ⇒ «4/302 phiên (1,3%)».
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { O_BAM_DUOC, TongQuanScreen } from '@/features/ops/components/TongQuanScreen'
import { KHOA_OVERVIEW, type Overview } from '@/features/ops/api'
import { daCho } from '@/features/ops/thoiGian'
import { server } from '../vitest.setup'

function veRoi() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        <TongQuanScreen />
      </QueryClientProvider>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(<RouterProvider router={router} />)
  return qc
}

const loi = (status: number, code: string) => () =>
  HttpResponse.json({ error: { code, message: 'x' } }, { status })

function datCaCho(phanHoi: Parameters<typeof http.get>[1]) {
  server.use(http.get('/api/v1/escalations', phanHoi))
}

/** Số lần gọi theo đường dẫn — đếm ở `request:start`, cùng khuôn `chuyen-sale-*.test`. */
const NGHE: Array<(a: { request: Request }) => void> = []
function demGoi(duong: string) {
  const dem = { n: 0 }
  const nghe = ({ request }: { request: Request }) => {
    if (new URL(request.url).pathname === duong) dem.n += 1
  }
  server.events.on('request:start', nghe)
  NGHE.push(nghe)
  return dem
}
afterEach(() => {
  NGHE.forEach((nghe) => server.events.removeListener('request:start', nghe))
  NGHE.length = 0
  focusManager.setFocused(undefined)
})

describe('ô Chuyển sale mở bằng việc tồn', () => {
  it('còn ca: số ca chưa liên hệ (màu cảnh báo) + danh sách chờ lâu nhất + tỉ lệ ở dòng phụ', async () => {
    veRoi()
    const o = await screen.findByTestId('o-chuyen-sale')
    const so = await within(o).findByTestId('cs-cho')
    expect(so).toHaveTextContent('2')
    expect(so).toHaveClass('text-badge-alert-fg')
    expect(o).toHaveTextContent('ca chưa liên hệ')
    // Danh sách ca chờ lâu nhất (06/10): mỗi hàng mở thẳng ca đó ở hàng đợi.
    const ds = within(o).getByTestId('cs-ds-cho')
    const hang = within(ds).getAllByRole('link')
    expect(hang).toHaveLength(2)
    expect(hang[0]).toHaveAccessibleName(/^Nguyễn Minh Anh, chờ \d+ ngày$/)
    expect(hang[0]!.getAttribute('href')).toMatch(/^\/chuyen-sale\?tab=new&cu=true&ca=1[23]$/)
    expect(within(o).getByTestId('cs-ti-le')).toHaveTextContent(
      'Kỳ này agent chuyển 4/302 phiên (1,3%)',
    )
    // Gauge nửa cung đã gỡ.
    expect(within(o).queryByRole('img')).not.toBeInTheDocument()
  })

  it('hết ca: nói «không còn ca nào», KHÔNG tô đỏ', async () => {
    datCaCho(() => HttpResponse.json({ items: [], tongCa: 0, duAnCo: [] }))
    veRoi()
    const o = await screen.findByTestId('o-chuyen-sale')
    expect(await within(o).findByText('Không còn ca nào chờ gọi.')).toBeInTheDocument()
    expect(within(o).queryByTestId('cs-cho')).not.toBeInTheDocument()
    expect(o.innerHTML).not.toContain('badge-alert')
  })

  it('vai trò không có quyền xem ca (403): chỉ còn tỉ lệ, không link, không nhấc', async () => {
    datCaCho(loi(403, 'FORBIDDEN'))
    veRoi()
    const o = await screen.findByTestId('o-chuyen-sale')
    await waitFor(() => expect(within(o).queryByRole('link')).not.toBeInTheDocument())
    expect(within(o).getByTestId('cs-ti-le')).toBeInTheDocument()
    expect(o.className).not.toContain(O_BAM_DUOC)
    expect(o).not.toHaveTextContent('Không tải được')
  })

  it('/escalations hỏng (500): nói rõ, link vẫn dẫn sang hàng đợi', async () => {
    datCaCho(loi(500, 'INTERNAL'))
    veRoi()
    const o = await screen.findByTestId('o-chuyen-sale')
    expect(await within(o).findByText('Không tải được số ca chờ.')).toBeInTheDocument()
    expect(within(o).getByRole('link', { name: /Xem ca/ })).toHaveAttribute(
      'href',
      '/chuyen-sale?tab=new&cu=true',
    )
  })

  it('ô Chuyển sale đứng ĐẦU trong DOM (điện thoại + Tab); desktop vẫn vẽ Hội thoại ở cột trái', async () => {
    veRoi()
    const o = await screen.findByTestId('o-chuyen-sale')
    expect(o.parentElement!.firstElementChild).toBe(o)
    expect(screen.getByTestId('o-hoi-thoai').className).toContain('md:-order-1')
  })

  it('màn rỗng (0 phiên, 0 đánh giá) vẫn báo ca chưa liên hệ — việc tồn không theo kỳ', async () => {
    const rong: Overview = {
      moc: { tuNgay: '2026-08-07', tinhDen: '2026-08-13' },
      hoiThoai: { tong: 0, truoc: 0, theoNgay: [], theoKenh: [] },
      chuyenSale: { chuyen: 0, tuXuLy: 0 },
      danhGia: {
        trungBinh: 0,
        truoc: null,
        tong: 0,
        theoSao: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
      },
      kienThuc: { muc: [] },
    }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(rong)))
    veRoi()
    const bao = await screen.findByTestId('tq-rong-ca-cho')
    expect(bao).toHaveTextContent('Vẫn còn 2 ca chưa liên hệ từ trước.')
    expect(within(bao).getByRole('link', { name: 'Xem ca' })).toHaveAttribute(
      'href',
      '/chuyen-sale?tab=new&cu=true',
    )
  })
})

describe('làm mới', () => {
  it('đầu màn nói số lấy lúc nào («Cập nhật hh:mm»)', async () => {
    veRoi()
    expect(await screen.findByTestId('tq-cap-nhat')).toHaveTextContent(/^Cập nhật \d{2}:\d{2}$/)
  })

  it('quay lại tab thì lấy lại cả tổng quan lẫn số ca chờ', async () => {
    const tq = demGoi('/api/v1/overview')
    const ca = demGoi('/api/v1/escalations')
    veRoi()
    await screen.findByTestId('cs-cho')
    const [tq0, ca0] = [tq.n, ca.n]

    focusManager.setFocused(false)
    focusManager.setFocused(true)
    await waitFor(() => expect(tq.n).toBe(tq0 + 1))
    await waitFor(() => expect(ca.n).toBe(ca0 + 1))
  })

  it('làm mới hỏng: GIỮ số đang hiện, báo «chưa làm mới được» — không thay cả màn bằng khung lỗi', async () => {
    const qc = veRoi()
    await screen.findByTestId('o-hoi-thoai')
    server.use(http.get('/api/v1/overview', loi(500, 'INTERNAL')))

    await qc.refetchQueries({ queryKey: KHOA_OVERVIEW })

    expect(await screen.findByText(/chưa làm mới được/)).toBeInTheDocument()
    expect(screen.getByTestId('o-hoi-thoai')).toBeInTheDocument()
    expect(screen.getByTestId('ht-tong')).toHaveTextContent('302')
    expect(screen.queryByTestId('tong-quan-loi')).not.toBeInTheDocument()
  })
})

describe('daCho', () => {
  const luc = '2026-10-06T08:00:00+07:00'
  const sau = (phut: number) => new Date(new Date(luc).getTime() + phut * 60_000)

  it('phút · giờ (tới 47) · ngày', () => {
    expect(daCho(luc, sau(0))).toBe('1 phút')
    expect(daCho(luc, sau(5))).toBe('5 phút')
    expect(daCho(luc, sau(59))).toBe('59 phút')
    expect(daCho(luc, sau(60))).toBe('1 giờ')
    expect(daCho(luc, sau(47 * 60 + 59))).toBe('47 giờ')
    expect(daCho(luc, sau(48 * 60))).toBe('2 ngày')
  })

  it('chuỗi hỏng ⇒ null, không «NaN giờ»', () => {
    expect(daCho('khong-phai-ngay', sau(5))).toBeNull()
  })
})

describe('ô Chi phí — tiền đi đâu', () => {
  it('dịch vụ tốn nhất của kỳ, tối đa 6 (bỏ dịch vụ không tính tiền), cùng nhãn với /billing', async () => {
    // jsdom không có bố cục nên mọi dòng đều render; số dòng VỪA ô do lưới `auto-fill` quyết.
    veRoi()
    const o = await screen.findByTestId('o-chi-phi')
    const ds = await within(o).findByRole('list', { name: 'Chi phí theo dịch vụ' })
    const dong = within(ds).getAllByRole('listitem')
    // Fake `features/billing/msw.ts`: llm 62.000 · tts 28.000 · stt 21.010,5 · call 9.000 · …
    expect(dong.map((d) => d.textContent)).toEqual([
      'LLM62.000VND',
      'TTS28.000VND',
      'STT21.011VND',
      'Cuộc gọi9.000VND',
      'Embed3.500VND',
      'Xác thực giọng1.500VND',
    ])
    expect(ds).not.toHaveTextContent('VAD')
  })
})
