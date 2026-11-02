/**
 * Bảng tra cứu `pricing_basis` (Task 7) — bản sao viết tay của
 * `billing.pricing_basis`, dùng cho form nhập giá ở Task 9. Phần đầu file CHỈ
 * canh hằng số/hàm thuần trong `pricingBasis.ts` — không render component nào.
 *
 * ⚠️ 12 dòng, KHÔNG PHẢI 11 — `0943` có 11, `0948_billing_text_units`
 * (2026-08-20) thêm vế `stt/text_units`. Nếu bài `đúng 12 dòng` đỏ, mở
 * `pricing-schema.sql` đếm lại, đừng sửa hằng theo cảm giác.
 *
 * Phần dưới (Task 8) canh màn `/pricing` (`BangGiaScreen`). Boot qua ROUTER
 * THẬT (`routeTree.gen.ts`, cùng khuôn `tests/billing-usage.test.tsx::boot()`)
 * dù màn không đọc search param nào — nhất quán với mọi bài test màn khác của
 * module, và để lỡ Task 9/10 thêm search param (panel) thì bài test này không
 * phải viết lại cách boot.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { LangProvider } from '@/i18n'
import { routeTree } from '@/routeTree.gen'
import { luuToken } from '@/features/billing/api'
import { PRICING_BASIS, STT_THOI_LUONG, basisCua, metricCua } from '@/features/billing/pricingBasis'
import { server } from '../vitest.setup'

describe('PRICING_BASIS', () => {
  it('đúng 13 dòng cơ sở', () => {
    expect(PRICING_BASIS).toHaveLength(13)
  })

  it('STT: audio_sec + text_units ĐƯỢC, audio_sec + wall_ms BỊ CHẶN', () => {
    // luật hẹp hơn từ migration 0948 — không phải "STT chỉ một metric"
    expect(STT_THOI_LUONG).toEqual(['audio_sec', 'wall_ms'])
    expect(metricCua('stt').map((b) => b.metric)).toContain('text_units')
  })

  it('tts và embed tính theo text_units, KHÔNG theo units', () => {
    expect(metricCua('tts').map((b) => b.metric)).toEqual(['text_units'])
    expect(metricCua('embed').map((b) => b.metric)).toEqual(['text_units'])
  })

  it('call tính theo audio_sec (giây), KHÔNG phải wall_ms — đối chiếu pricing-schema.sql', () => {
    expect(metricCua('call')).toEqual([
      { component: 'call', metric: 'audio_sec', per_units: 60, dvi: 'đ /phút' },
    ])
  })

  it('basisCua tìm đúng một dòng theo (component, metric)', () => {
    expect(basisCua('llm', 'input_tokens')?.per_units).toBe(1_000_000)
    expect(basisCua('khong-ton-tai', 'x')).toBeUndefined()
  })
})

function bootPricing() {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/pricing'] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
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
 * Theo dõi request tới một TIỀN TỐ đường dẫn qua sự kiện `request:start` của
 * MSW — không phải qua `server.use()` (ghi đè handler sẽ làm mất `thieuTokenAdmin()`
 * thật của fake, đúng thứ bài test cần giữ nguyên để canh nhánh 401).
 * `afterEach` bên dưới gỡ listener — `server.resetHandlers()` của
 * `vitest.setup.ts` KHÔNG dọn `server.events`, chỉ dọn `server.use()`.
 */
const NGHE_ADMIN: Array<(a: { request: Request }) => void> = []

function theoDoi(tienTo: string) {
  const goi = vi.fn()
  const nghe = ({ request }: { request: Request }) => {
    if (request.url.includes(tienTo)) goi(request.url)
  }
  server.events.on('request:start', nghe)
  NGHE_ADMIN.push(nghe)
  return goi
}

afterEach(() => {
  NGHE_ADMIN.forEach((nghe) => server.events.removeListener('request:start', nghe))
  NGHE_ADMIN.length = 0
  sessionStorage.clear()
})

describe('BangGiaScreen (Task 8)', () => {
  it('thiếu token → màn nói rõ, KHÔNG gọi API admin', async () => {
    sessionStorage.clear()
    const goi = theoDoi('/api/v1/admin/billing/')
    bootPricing()
    expect(await screen.findByLabelText(/token quản trị nền tảng/i)).toBeInTheDocument()
    expect(goi).not.toHaveBeenCalled()
  })

  it('có token → danh sách bộ giá, 5 cột, pill Mặc định', async () => {
    luuToken('test-admin-token')
    bootPricing()
    const bang = await screen.findByRole('table', { name: /danh sách bộ giá/i })
    expect(within(bang).getByText('Bảng giá VND mặc định')).toBeInTheDocument()
    expect(within(bang).getByText('Mặc định')).toBeInTheDocument()
  })

  it('ô «Tổ hợp chưa có giá» là SỐ ĐẾM, không hứa danh sách', async () => {
    luuToken('test-admin-token')
    bootPricing()
    await screen.findByRole('table', { name: /danh sách bộ giá/i })
    // không có nút mở panel lỗ giá — chưa có endpoint trả dòng chi tiết
    expect(screen.queryByRole('button', { name: /lỗ giá|chưa có giá/i })).toBeNull()
  })

  /**
   * KHOÁ LẠI review coordinator 2026-08-20: bản đầu render hai ô «Bộ giá mặc
   * định»/«Bộ đang áp» là `<button onClick={() => {}}>` — KHÔNG phải "chưa
   * nối panel", mà một ĐIỀU KHIỂN CHẾT (viền focus, con trỏ tay, tab tới
   * được, bấm không làm gì). Điều khiển chết TỆ HƠN không có nút: người dùng
   * bấm một lần, không thấy phản hồi, kết luận màn lỗi rồi lần sau không bấm
   * nữa.
   *
   * ⚠️ SỬA Task 9 (2026-08-20, đúng chủ đích — bài Task 8 tự nói trước điều
   * này): panel `PanelBoGia` đã nối thật. «Bộ giá mặc định» giờ LÀ `<button>`
   * — nó trỏ vào ĐÚNG MỘT bộ giá (`macDinh.id`), có đích thật để mở. Hai ô
   * còn lại VẪN `<div>` không tương tác: «Bộ đang áp» là một PHÉP ĐẾM (không
   * biết mở panel cho bộ nào trong số đó), «Tổ hợp chưa có giá» không có
   * nguồn tách dòng (đã ghi ở Task 8) — cả hai không có đích rõ ràng nên vẫn
   * là điều khiển chết nếu biến thành nút, kể cả bây giờ panel đã tồn tại.
   */
  it('ô «Bộ giá mặc định» LÀ button (Task 9 đã nối panel) — «Bộ đang áp»/«Tổ hợp chưa có giá» VẪN không phải', async () => {
    luuToken('test-admin-token')
    bootPricing()
    await screen.findByRole('table', { name: /danh sách bộ giá/i })
    expect(screen.getByRole('button', { name: /bộ giá mặc định/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /bộ đang áp/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /tổ hợp chưa có giá/i })).toBeNull()
  })

  it('thiếu token → KHÔNG hiện danh sách bộ giá lẫn nút «Bộ giá mới»', async () => {
    sessionStorage.clear()
    bootPricing()
    await screen.findByLabelText(/token quản trị nền tảng/i)
    expect(screen.queryByRole('table', { name: /danh sách bộ giá/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /bộ giá mới/i })).toBeNull()
  })

  it('có token → 401 từ admin API bắn xuống LoiTai, có nút Thử lại', async () => {
    server.use(
      http.get('/api/v1/admin/billing/price-versions', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHORIZED', message: 'Token sai' } },
          { status: 401 },
        ),
      ),
    )
    luuToken('token-sai')
    bootPricing()
    expect(await screen.findByRole('alert')).toHaveTextContent(/không tải được/i)
  })
})

/**
 * `PanelBoGia` (Task 9) — form thêm dòng giá + preview per-tenant + kích
 * hoạt. Hai bộ giá đặt tên riêng cho nhóm test này ('Chuẩn Q3/2026' id `1` ·
 * 'Nháp Q4/2026' id `2`) — KHÁC hai dòng của `BO_GIA_GIA` (fake dùng chung
 * `Task 8`, tên `Bảng giá VND mặc định`/`Bảng giá USD thí điểm`) để không
 * đụng bài test Task 8 phía trên. `id: 1` cố ý trùng route
 * `/admin/billing/price-versions/1/items` mà bài "unitPrice/perUnits" canh.
 *
 * ⚠️ Mã lỗi kích hoạt là `BANG_GIA_CON_LO` (đọc thẳng
 * `odyssey-portal-backend/src/portal/modules/billing/service.py::kich_hoat`)
 * — brief nháp đầu đoán `BO_GIA_CON_LO`, SAI, đã sửa theo mã thật.
 *
 * Workspace dùng ID THẬT của fake `GET /api/v1/me` (`lib/msw/handlers.ts`):
 * `ws_anphu`/`ws_sunrise`/`ws_haven` — brief nháp đầu viết `'bilw'` (không có
 * thật trong fake), đã đổi.
 */
describe('PanelBoGia (Task 9)', () => {
  // ⚠️ CẢ HAI 'inactive' — nút Kích hoạt chỉ hiện chữ "Kích hoạt" khi
  // `status !== 'active'` (`KhuPreviewVaKichHoat.dangKichHoat`); một dòng
  // 'active' sẽ đổi tên nút thành "Đã kích hoạt" và mọi
  // `getByRole('button', {name:'Kích hoạt'})` của cả hai bộ đều trượt tên,
  // không phải trượt logic khoá/mở (đã bắt lỗi này khi viết bài remount).
  const BO_GIA_TASK9 = [
    {
      id: 1,
      code: 'q3-2026-chuan',
      name: 'Chuẩn Q3/2026',
      currency: 'VND',
      status: 'inactive',
      is_default: true,
      created_at: '2026-07-01T00:00:00+07:00',
    },
    {
      id: 2,
      code: 'q4-2026-nhap',
      name: 'Nháp Q4/2026',
      currency: 'VND',
      status: 'inactive',
      is_default: false,
      created_at: '2026-08-01T00:00:00+07:00',
    },
  ]

  /** `bootPricing()` của Task 8, ghi đè danh sách bộ giá về hai dòng riêng ở
   *  trên — token đã kiểm nên không cần lặp lại `thieuTokenAdmin()` ở đây. */
  function bootPanel() {
    server.use(
      http.get('/api/v1/admin/billing/price-versions', () => HttpResponse.json(BO_GIA_TASK9)),
    )
    return bootPricing()
  }

  /** Mở panel qua nút tên bộ giá TRONG bảng (không phải ô «Bộ giá mặc định»
   *  ở mục ① — tên có thể trùng, và table row hoạt động cho CẢ hai ca mặc
   *  định/không mặc định). */
  async function moPanelBoGia(ten: string) {
    const bang = await screen.findByRole('table', { name: /danh sách bộ giá/i })
    await userEvent.click(within(bang).getByRole('button', { name: ten }))
    await screen.findByRole('dialog')
  }

  /**
   * Bắt body JSON của lần gọi ĐẦU TIÊN khớp method + tiền tố URL. Trả về một
   * hàm `() => Promise<unknown>` — gọi hàm đó rồi `await` khi cần đọc body,
   * đúng khuôn `theoDoi()` ở trên nhưng đọc BODY thay vì chỉ đếm URL.
   */
  function batBody(method: string, tienTo: string): () => Promise<unknown> {
    const p = new Promise<unknown>((resolve) => {
      const nghe = ({ request }: { request: Request }) => {
        if (request.method !== method || !request.url.includes(tienTo)) return
        server.events.removeListener('request:start', nghe)
        void request.clone().json().then(resolve)
      }
      // Đăng ký vào `NGHE_ADMIN` (mảng dọn chung ở `afterEach` phía trên) —
      // test fail trước khi request khớp thì listener vẫn được gỡ, không rò
      // sang bài kế tiếp (`resetHandlers()` KHÔNG dọn `server.events`).
      server.events.on('request:start', nghe)
      NGHE_ADMIN.push(nghe)
    })
    return () => p
  }

  /** Ghi đè `/activate` trả `409` với đúng mã + message cho lượt kích hoạt kế tiếp. */
  function dat409(code: string, message: string) {
    server.use(
      http.post('/api/v1/admin/billing/price-versions/:pb/activate', () =>
        HttpResponse.json({ error: { code, message } }, { status: 409 }),
      ),
    )
  }

  /**
   * Mở panel qua PHẦN TRẦN của hàng — KHÁC `moPanelBoGia()` (luôn bấm nút
   * tên). Đúng đường review chỉ ra `oMoRef` từng KHÔNG được đặt: `Hang` bỏ
   * qua click phát từ phần tử tương tác (`closest(TU_BAM_DUOC)`, `Bang.tsx`),
   * nên bấm chỗ trống của hàng đi đường `Hang.mo`, không đi qua `onClick` của
   * nút tên. Click vào Ô TRẠNG THÁI (`<td>` chỉ chứa `<span>` pill, không
   * nằm trong `TU_BAM_DUOC`) — không phải nút tên, không phải phần tử tương
   * tác nào khác. Trả về nút tên: đó là đích focus PHẢI quay về khi đóng.
   */
  async function moPanelBoGiaQuaHangTran(ten: string) {
    const bang = await screen.findByRole('table', { name: /danh sách bộ giá/i })
    const nutTen = within(bang).getByRole('button', { name: ten })
    const hang = nutTen.closest('tr')
    if (!hang) throw new Error('không tìm thấy <tr> chứa nút tên')
    const oTrangThai = within(hang).getAllByRole('cell')[1]
    if (!oTrangThai) throw new Error('không tìm thấy ô Trạng thái của hàng')
    await userEvent.click(oTrangThai)
    await screen.findByRole('dialog')
    return nutTen
  }

  it('body POST items gửi unitPrice/perUnits camelCase, phần còn lại tên thường', async () => {
    luuToken('t')
    const body = batBody('POST', '/admin/billing/price-versions/1/items')
    bootPanel()
    await moPanelBoGia('Chuẩn Q3/2026')
    await userEvent.selectOptions(screen.getByLabelText('Component'), 'tts')
    await userEvent.type(screen.getByLabelText('Đơn giá'), '0.126')
    await userEvent.click(screen.getByRole('button', { name: 'Thêm dòng' }))
    // Không có `populate_by_name` ở BE ⇒ gửi `unit_price` thay vì `unitPrice` ăn 422.
    expect(await body()).toEqual({
      component: 'tts',
      purpose: '',
      provider: '',
      model: '',
      metric: 'text_units',
      unitPrice: '0.126',
      perUnits: 1,
      note: '',
    })
  })

  it('STT: chọn audio_sec vẫn cho chọn text_units, nhưng KHOÁ wall_ms', async () => {
    luuToken('t')
    bootPanel()
    await moPanelBoGia('Nháp Q4/2026')
    await userEvent.selectOptions(screen.getByLabelText('Component'), 'stt')
    const metric = screen.getByLabelText('Metric') as HTMLSelectElement
    const opt = (v: string) => [...metric.options].find((o) => o.value === v)!
    expect(opt('audio_sec').disabled).toBe(false)
    expect(opt('text_units').disabled).toBe(false) // ĐỘC LẬP từ 0948
    expect(opt('wall_ms').disabled).toBe(true) // loại trừ với audio_sec
  })

  it('đơn vị hiện thành CHỮ trong ô nhập, đổi theo metric', async () => {
    luuToken('t')
    bootPanel()
    await moPanelBoGia('Nháp Q4/2026')
    await userEvent.selectOptions(screen.getByLabelText('Component'), 'llm')
    expect(screen.getByText('đ /1M token')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Component'), 'tts')
    expect(screen.getByText('đ /ký tự')).toBeInTheDocument()
  })

  it('Kích hoạt KHOÁ tới khi preview đã chạy cho ĐÚNG bộ đó', async () => {
    luuToken('t')
    server.use(
      http.get('/api/v1/admin/billing/price-versions/:pb/preview', () =>
        HttpResponse.json({ chiPhi: '1204516.0000000000', currency: 'VND' }),
      ),
    )
    bootPanel()
    await moPanelBoGia('Nháp Q4/2026')
    expect(screen.getByRole('button', { name: 'Kích hoạt' })).toBeDisabled()
    await userEvent.selectOptions(screen.getByLabelText('Workspace'), 'ws_sunrise')
    await userEvent.click(screen.getByRole('button', { name: /Preview/ }))
    await screen.findByText(/1\.204\.516/)
    expect(screen.getByRole('button', { name: 'Kích hoạt' })).toBeEnabled()
  })

  it('409 khi kích hoạt bộ còn lỗ giá — hiện nguyên văn message của BE', async () => {
    luuToken('t')
    dat409(
      'BANG_GIA_CON_LO',
      'chưa có dòng giá cho: llm/input_tokens, tts/text_units. Muốn miễn phí thì tạo dòng giá 0 — để trống nghĩa là âm thầm miễn phí và không cảnh báo nào kêu.',
    )
    bootPanel()
    await moPanelBoGia('Nháp Q4/2026')
    await userEvent.selectOptions(screen.getByLabelText('Workspace'), 'ws_sunrise')
    await userEvent.click(screen.getByRole('button', { name: /Preview/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Kích hoạt' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Kích hoạt' }))
    expect(await screen.findByText(/chưa có dòng giá cho: llm\/input_tokens/)).toBeInTheDocument()
  })

  /**
   * BA bài dưới đây canh cả ba đường đóng — KHOÁ LẠI sau review 2026-08-20:
   * `oMoRef` (BangGiaScreen.tsx) từng KHÔNG được đặt trên đường click phần
   * TRẦN của hàng (`Hang.mo`, khác đường click nút tên), nên `dongPanel()`
   * trả focus về `null`/hàng mở TRƯỚC thay vì hàng vừa đóng. Cả ba bài MỞ
   * bằng `moPanelBoGiaQuaHangTran()` (đường từng hỏng), không phải
   * `moPanelBoGia()` (đường nút, luôn đúng ngay từ đầu nên không bắt được
   * bug này).
   */
  it('Đóng qua nút × trả focus về đúng nút đã mở nó (mở bằng phần TRẦN của hàng)', async () => {
    luuToken('t')
    bootPanel()
    const nutTen = await moPanelBoGiaQuaHangTran('Nháp Q4/2026')
    const dialog = screen.getByRole('dialog')
    // Backdrop cũng mang `aria-label="Đóng"` nhưng đứng NGOÀI `role="dialog"`
    // — `within(dialog)` chỉ khớp đúng nút × bên trong.
    await userEvent.click(within(dialog).getByRole('button', { name: 'Đóng' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nutTen).toHaveFocus()
  })

  it('Đóng qua click lớp phủ trả focus về đúng nút đã mở nó (mở bằng phần TRẦN của hàng)', async () => {
    luuToken('t')
    bootPanel()
    const nutTen = await moPanelBoGiaQuaHangTran('Nháp Q4/2026')
    const nutDong = screen.getAllByRole('button', { name: 'Đóng' })
    // Lớp phủ render TRƯỚC dialog trong DOM ⇒ phần tử đầu tiên.
    await userEvent.click(nutDong[0]!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nutTen).toHaveFocus()
  })

  it('Đóng qua Escape trả focus về đúng nút đã mở nó (mở bằng phần TRẦN của hàng)', async () => {
    luuToken('t')
    bootPanel()
    const nutTen = await moPanelBoGiaQuaHangTran('Chuẩn Q3/2026')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nutTen).toHaveFocus()
  })

  it('preview bộ A rồi mở bộ B ⇒ nút Kích hoạt của B vẫn khoá (remount theo pbId reset gate)', async () => {
    luuToken('t')
    server.use(
      http.get('/api/v1/admin/billing/price-versions/:pb/preview', () =>
        HttpResponse.json({ chiPhi: '999999.0000000000', currency: 'VND' }),
      ),
    )
    bootPanel()
    await moPanelBoGia('Chuẩn Q3/2026')
    await userEvent.selectOptions(screen.getByLabelText('Workspace'), 'ws_sunrise')
    await userEvent.click(screen.getByRole('button', { name: /Preview/ }))
    await screen.findByText(/999\.999/)
    expect(screen.getByRole('button', { name: 'Kích hoạt' })).toBeEnabled()

    // Đóng bộ A, mở bộ B — `PanelBoGia key={pbId}` ở `BangGiaScreen` remount
    // toàn bộ component, xoá sạch state cục bộ (kể cả gate preview).
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Đóng' }))
    await moPanelBoGia('Nháp Q4/2026')
    expect(screen.getByRole('button', { name: 'Kích hoạt' })).toBeDisabled()
  })
})

/**
 * `PanelGanWorkspace` (Task 10) — bảng gán bộ giá cho workspace, mở từ nút
 * «Gán workspace» cạnh «Bộ giá mới» ở dải công cụ mục ②. Dùng NGUYÊN fake mặc
 * định `BO_GIA_GIA` của `features/billing/msw.ts` (KHÔNG override như nhóm
 * Task 9 ở trên) — nó đã sẵn đúng ca cần: `id:1` `status:'active'`
 * ('Bảng giá VND mặc định') và `id:2` `status:'inactive'`
 * ('Bảng giá USD thí điểm'), đúng cặp active/inactive để canh bộ lọc select.
 *
 * Workspace dùng ID/tên THẬT của fake `GET /api/v1/me` (`lib/msw/handlers.ts`):
 * `ws_anphu`/An Phú Land, `ws_sunrise`/Sunrise Land, `ws_haven`/Havenly Property.
 */
describe('PanelGanWorkspace (Task 10)', () => {
  async function moPanelGan() {
    const nutMo = await screen.findByRole('button', { name: 'Gán workspace' })
    await userEvent.click(nutMo)
    await screen.findByRole('dialog')
    return nutMo
  }

  /** Bắt body JSON của lần gọi ĐẦU TIÊN khớp `POST .../tenants/:id/price-version`. */
  function batBodyGan(): () => Promise<{ priceVersionId: number; effectiveFrom: string }> {
    const p = new Promise<{ priceVersionId: number; effectiveFrom: string }>((resolve) => {
      const nghe = ({ request }: { request: Request }) => {
        if (request.method !== 'POST' || !request.url.includes('/tenants/')) return
        server.events.removeListener('request:start', nghe)
        void request
          .clone()
          .json()
          .then((b) => resolve(b as { priceVersionId: number; effectiveFrom: string }))
      }
      server.events.on('request:start', nghe)
      NGHE_ADMIN.push(nghe)
    })
    return () => p
  }

  /** Ghi đè `POST .../tenants/:id/price-version` trả `409` cho lượt kế tiếp. */
  function dat409Gan(code: string, message: string) {
    server.use(
      http.post('/api/v1/admin/billing/tenants/:tenantId/price-version', () =>
        HttpResponse.json({ error: { code, message } }, { status: 409 }),
      ),
    )
  }

  it('liệt kê đủ ba workspace của phiên, kèm slug', async () => {
    luuToken('t')
    bootPricing()
    await moPanelGan()
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('An Phú Land')).toBeInTheDocument()
    expect(within(dialog).getByText('anphu')).toBeInTheDocument()
    expect(within(dialog).getByText('Sunrise Land')).toBeInTheDocument()
    expect(within(dialog).getByText('Havenly Property')).toBeInTheDocument()
  })

  it('select «Bộ giá» CHỈ liệt kê bộ giá status active, KHÔNG có bộ inactive', async () => {
    luuToken('t')
    bootPricing()
    await moPanelGan()
    const chon = screen.getByLabelText('Bộ giá cho An Phú Land') as HTMLSelectElement
    const nhan = [...chon.options].map((o) => o.textContent)
    expect(nhan).toContain('Bảng giá VND mặc định') // status active
    expect(nhan).not.toContain('Bảng giá USD thí điểm') // status inactive — phải bị lọc
  })

  it('mọi <select> mang class o-chon (luật 6 design token)', async () => {
    luuToken('t')
    bootPricing()
    await moPanelGan()
    const chon = screen.getByLabelText('Bộ giá cho Sunrise Land')
    expect(chon.className).toContain('o-chon')
  })

  it('cột «Đang áp» hiện — kèm title giải thích — không phải nghĩa "chưa gán"', async () => {
    luuToken('t')
    bootPricing()
    await moPanelGan()
    // Ba hàng, mỗi hàng một `—` kèm title (không phải MỘT ô chung cho cả bảng).
    const dau = screen.getAllByTitle(/chưa có endpoint đọc.*tenant_price_version/i)
    expect(dau).toHaveLength(3)
    dau.forEach((el) => expect(el).toHaveTextContent('—'))
  })

  it('gửi Gán: body priceVersionId/effectiveFrom camelCase, effectiveFrom TZ-AWARE (có hậu tố Z)', async () => {
    luuToken('t')
    const body = batBodyGan()
    bootPricing()
    await moPanelGan()
    await userEvent.selectOptions(screen.getByLabelText('Bộ giá cho Sunrise Land'), '1')
    // `datetime-local` trả chuỗi NAIVE — `fireEvent.change` mô phỏng đúng giá
    // trị trình duyệt trả về cho input này (`userEvent.type` không gõ được
    // đúng vào loại input này trong jsdom).
    fireEvent.change(screen.getByLabelText('Hiệu lực từ cho Sunrise Land'), {
      target: { value: '2026-09-01T00:00' },
    })
    const hang = screen.getByLabelText('Bộ giá cho Sunrise Land').closest('tr')
    if (!hang) throw new Error('không tìm thấy hàng Sunrise Land')
    await userEvent.click(within(hang).getByRole('button', { name: 'Gán' }))

    const b = await body()
    expect(b.priceVersionId).toBe(1)
    // ⚠️ KIỂM NGƯỢC (ghi trong báo cáo, không phải một bài test riêng): tạm bỏ
    // `.toISOString()` ở `HangGan.guiGan()` (gửi thẳng chuỗi `datetime-local`
    // naive) làm ĐÚNG hai assertion dưới đây đỏ — `effectiveFrom` khi đó bằng
    // `'2026-09-01T00:00'`, không khớp `/Z$/` và không tzinfo. Xác nhận xong,
    // hoàn nguyên lại `.toISOString()`.
    expect(b.effectiveFrom).toMatch(/Z$/)
    expect(b.effectiveFrom).not.toBe('2026-09-01T00:00')
    expect(new Date(b.effectiveFrom).getTime()).toBe(new Date('2026-09-01T00:00').getTime())
  })

  it('409 MOC_QUA_KHU_DA_DINH_GIA — hiện NGUYÊN VĂN message của BE', async () => {
    luuToken('t')
    dat409Gan(
      'MOC_QUA_KHU_DA_DINH_GIA',
      'đã có usage được định giá từ 01/08/2026 trở đi. Chọn một mốc sau kỳ đã chốt, hoặc xoá rated_usage của kỳ đó trước nếu thật sự muốn tính lại.',
    )
    bootPricing()
    await moPanelGan()
    await userEvent.selectOptions(screen.getByLabelText('Bộ giá cho An Phú Land'), '1')
    fireEvent.change(screen.getByLabelText('Hiệu lực từ cho An Phú Land'), {
      target: { value: '2026-07-01T00:00' },
    })
    const hang = screen.getByLabelText('Bộ giá cho An Phú Land').closest('tr')
    if (!hang) throw new Error('không tìm thấy hàng An Phú Land')
    await userEvent.click(within(hang).getByRole('button', { name: 'Gán' }))
    expect(await screen.findByText(/đã có usage được định giá từ 01\/08\/2026/)).toBeInTheDocument()
  })

  it('409 MOC_TRUOC_KHOANG_DANG_MO — hiện NGUYÊN VĂN message của BE', async () => {
    luuToken('t')
    dat409Gan(
      'MOC_TRUOC_KHOANG_DANG_MO',
      'khoảng đang chạy hiện tại mở từ 15/08/2026 09:00, sau mốc gán mới (01/08/2026 00:00). Chọn một mốc SAU 15/08/2026 09:00.',
    )
    bootPricing()
    await moPanelGan()
    await userEvent.selectOptions(screen.getByLabelText('Bộ giá cho Havenly Property'), '1')
    fireEvent.change(screen.getByLabelText('Hiệu lực từ cho Havenly Property'), {
      target: { value: '2026-08-01T00:00' },
    })
    const hang = screen.getByLabelText('Bộ giá cho Havenly Property').closest('tr')
    if (!hang) throw new Error('không tìm thấy hàng Havenly Property')
    await userEvent.click(within(hang).getByRole('button', { name: 'Gán' }))
    expect(
      await screen.findByText(/khoảng đang chạy hiện tại mở từ 15\/08\/2026 09:00/),
    ).toBeInTheDocument()
  })

  it('Đóng qua nút × trả focus về nút «Gán workspace»', async () => {
    luuToken('t')
    bootPricing()
    const nutMo = await moPanelGan()
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Đóng' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nutMo).toHaveFocus()
  })

  it('Đóng qua click lớp phủ trả focus về nút «Gán workspace»', async () => {
    luuToken('t')
    bootPricing()
    const nutMo = await moPanelGan()
    const nutDong = screen.getAllByRole('button', { name: 'Đóng' })
    // Lớp phủ render TRƯỚC dialog trong DOM ⇒ phần tử đầu tiên.
    await userEvent.click(nutDong[0]!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nutMo).toHaveFocus()
  })

  it('Đóng qua Escape trả focus về nút «Gán workspace»', async () => {
    luuToken('t')
    bootPricing()
    const nutMo = await moPanelGan()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nutMo).toHaveFocus()
  })
})

/**
 * Khoảng hở mã lỗi của Task 9 (Task 10 vá) — form thêm dòng giá
 * (`FormThemDongGia` trong `PanelBoGia.tsx`) chỉ có bài test cho
 * `BANG_GIA_CON_LO` (đường KÍCH HOẠT, describe Task 9 ở trên). Đường THÊM DÒNG
 * GIÁ còn hai mã thật khác của `service.py::them_dong_gia`:
 * `DONG_GIA_TRUNG` (trùng UNIQUE constraint) và `STT_HAI_CO_SO` (vi phạm
 * `price_item_stt_single_basis`).
 *
 * ⚠️ `NHIEU_DON_VI_TIEN` KHÔNG có bài test ở đây — đã đọc thẳng
 * `odyssey-portal-backend/src/portal/modules/billing/router.py::tao_dong_gia`:
 * endpoint `POST .../price-versions/{pb}/items` chỉ gọi
 * `service.them_dong_gia()`, và mã đó được ném DUY NHẤT ở `repo.py` cho
 * `summary`/`by-key` (trộn đơn vị tiền trong MỘT KHOẢNG THỜI GIAN truy vấn) —
 * không đường nào từ form thêm dòng giá gọi tới đó. Viết một bài test giả lập
 * mã này ở đây sẽ khoá một hành vi KHÔNG THỂ xảy ra thật, tức một cổng test
 * giả tạo lòng tin sai. Xử lý lỗi vẫn hiện đúng NGUYÊN VĂN nếu BE có ngày nào
 * đó thay đổi và trả mã này (xem lý do generic dưới đây), chỉ là không có gì
 * để canh THẬT ở đây.
 *
 * Đường xử lý lỗi hiện tại (`thongDiep()` trong `PanelBoGia.tsx`) ĐÃ GENERIC —
 * nó chỉ đọc `err.message` của MỌI `LoiApi`, không rẽ nhánh theo `code`. Hai
 * bài dưới đây là CỔNG cho khẳng định đó, không chỉ là lời khẳng định suông.
 */
describe('FormThemDongGia — mã lỗi khác BANG_GIA_CON_LO ở đường thêm dòng giá (Task 10)', () => {
  async function moPanelMacDinh() {
    await screen.findByRole('table', { name: /danh sách bộ giá/i })
    await userEvent.click(screen.getByRole('button', { name: /bộ giá mặc định/i }))
    await screen.findByRole('dialog')
  }

  function dat409Items(code: string, message: string) {
    server.use(
      http.post('/api/v1/admin/billing/price-versions/:pb/items', () =>
        HttpResponse.json({ error: { code, message } }, { status: 409 }),
      ),
    )
  }

  it('409 DONG_GIA_TRUNG — hiện NGUYÊN VĂN message của BE', async () => {
    luuToken('t')
    dat409Items(
      'DONG_GIA_TRUNG',
      'đã có dòng giá cho cùng bộ (component, purpose, provider, model, metric)',
    )
    bootPricing()
    await moPanelMacDinh()
    await userEvent.type(screen.getByLabelText('Đơn giá'), '0.5')
    await userEvent.click(screen.getByRole('button', { name: 'Thêm dòng' }))
    expect(
      await screen.findByText(/đã có dòng giá cho cùng bộ \(component, purpose/),
    ).toBeInTheDocument()
  })

  it('409 STT_HAI_CO_SO — hiện NGUYÊN VĂN message của BE', async () => {
    luuToken('t')
    dat409Items(
      'STT_HAI_CO_SO',
      "STT chỉ được tính tiền theo MỘT cơ sở. `(stt,'conversation')/audio_sec` và `(stt,'stream')/wall_ms` là hai cách đo cùng một dịch vụ — đặt giá cả hai là tính tiền STT hai lần. Đặt cơ sở không dùng về 0.",
    )
    bootPricing()
    await moPanelMacDinh()
    await userEvent.type(screen.getByLabelText('Đơn giá'), '0.5')
    await userEvent.click(screen.getByRole('button', { name: 'Thêm dòng' }))
    expect(await screen.findByText(/STT chỉ được tính tiền theo MỘT cơ sở/)).toBeInTheDocument()
  })
})
