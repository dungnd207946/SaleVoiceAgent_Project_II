/**
 * Màn «Thử agent» (`/thu-agent`) — chat qua gateway thật, nối THẲNG từ trình
 * duyệt (không qua backend). Viết lại lần bốn 2026-08-10 theo tài liệu
 * handoff chính thức của team gateway
 * (`odyssey-portal-backend/docs/build_test_agent/2026-08-10-frontend-chat-gateway-handoff.md`).
 *
 * Bốn ô Họ tên/Số điện thoại/Giới tính/API Key. Đổi ở lần này: không còn
 * relay/backend — `FakeWebSocket` mô phỏng thẳng giao thức `/v1/chat`
 * (handshake ngay lúc mở, chờ `session_id` mới coi là sẵn sàng, `suggestions`
 * là `{label,text}[]`).
 *
 * 2026-08-11: API Key đổi từ ô dán khoá thô sang `<select>` chọn theo tên
 * (backend từ migration `0918` lưu thêm `Khoa.api_key`) — `oApiKey()` giờ trỏ
 * vào `<select>`, chọn bằng `userEvent.selectOptions(oApiKey(), <api_key>)`,
 * KHÔNG còn `userEvent.type()`.
 *
 * 2026-08-11 (lần hai): **WS URL bỏ khỏi UI, fix cứng trong code**
 * (`WS_URL_CHAT_MAC_DINH`/`WS_URL_VOICE_MAC_DINH` ở `ThuAgentScreen.tsx`) — không
 * còn `oWsUrl()`/ô «WS URL» nào để test tương tác; các assertion `ws.url` bây
 * giờ so với domain cố định đó.
 */
import { act, StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { chuanHoaMedia } from '../src/features/platform/chatGateway'
import { routeTree } from '../src/routeTree.gen'
import { WS_URL_CHAT_MAC_DINH, WS_URL_VOICE_MAC_DINH } from '../src/features/platform/api'
import { server } from '../vitest.setup'

class FakeWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instances: FakeWebSocket[] = []

  readyState = FakeWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((e: { code: number; reason: string }) => void) | null = null
  readonly sent: string[] = []
  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.({ code: 1000, reason: '' })
  }

  /** Test-only: mở thành công — kéo theo FE gửi bắt tay ngay. */
  moThanhCong(): void {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }

  /** Test-only: mô phỏng gateway gửi một event JSON. */
  nhan(obj: unknown): void {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }

  /** Test-only: mô phỏng gateway đóng kết nối với (code, reason). */
  dong(code: number, reason = ''): void {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.({ code, reason })
  }
}

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const KHOA = [
  {
    id: 1,
    api_key: 'ody_ag_rawkey123',
    key_prefix: 'ody_ag_aaaa',
    label: 'Pod chat production',
    created_at: '2026-08-01T09:00:00Z',
    last_used_at: null,
    status: 'active' as const,
    revoked_at: null,
  },
]

function datApi(opts: { keys?: unknown[] } = {}) {
  server.use(
    http.get('/api/v1/agent/keys', () =>
      HttpResponse.json({
        endpoint_chat_url: 'wss://anphu.test/v1/chat',
        // `/v1/voice`, KHÔNG phải `/v1/stream` — path đó đã bỏ, không alias
        // (gateway-voice-ws-spec.md §1). FE không dùng field này làm mặc định
        // (xem `WS_URL_VOICE_MAC_DINH`), chỉ giữ đúng hình dạng response.
        endpoint_voice_url: 'wss://anphu.test/v1/voice',
        keys: opts.keys ?? KHOA,
      }),
    ),
    // Role của ô «Role» — đổ từ cấu hình chung (`/config`), không phải danh sách tĩnh.
    http.get('/api/v1/config', () =>
      HttpResponse.json({
        vaiTro: VAI_TRO_GIA.map((v) => ({ ...v, cauHinh: {}, laMacDinh: false })),
        version: 1,
        soRoleToiDa: 10,
      }),
    ),
  )
}

const VAI_TRO_GIA = [
  { key: 'customer', ten: 'Khách hàng', icon: null, macDinh: true },
  { key: 'sale', ten: 'Sale', icon: null, macDinh: false },
]

/** jsdom không có `AudioContext`/`getUserMedia` — giả tối thiểu để
 *  `moPhienGiongNoi()` chạy được tới lúc mở WS. KHÔNG mô phỏng âm thanh thật
 *  (không phải mục tiêu — xem docstring `giongNoi.ts`), chỉ đủ để phần EVENT
 *  (JSON qua WS) chạy được trong test. */
class FakeAudioContext {
  currentTime = 0
  sampleRate = 48000
  createMediaStreamSource() {
    return { connect() {}, disconnect() {} }
  }
  createScriptProcessor() {
    const bo = { connect() {}, disconnect() {}, onaudioprocess: null }
    FakeAudioContext.boXuLy.push(bo)
    return bo
  }
  createBuffer() {
    return { getChannelData: () => new Float32Array(0) }
  }
  createBufferSource() {
    return { connect() {}, start() {} }
  }
  createAnalyser() {
    return { fftSize: 0, connect() {}, disconnect() {}, getFloatTimeDomainData() {} }
  }
  state = 'running'
  destination = {}
  createOscillator() {
    const osc = {
      type: '',
      frequency: { value: 0 },
      connect() {},
      disconnect() {},
      start() {},
      stop() {},
      onended: null,
    }
    FakeAudioContext.chuong.push(osc)
    return osc
  }
  createGain() {
    const ham = () => {}
    return {
      gain: {
        value: 0,
        setValueAtTime: ham,
        linearRampToValueAtTime: ham,
        cancelScheduledValues: ham,
      },
      connect() {},
      disconnect() {},
    }
  }
  /** Mọi oscillator (chuông chờ) đã dựng — bài test chuông soi ở đây. */
  static chuong: Array<{ frequency: { value: number } }> = []
  /** Bộ xử lý mic — gọi `onaudioprocess` của cái cuối để giả một khối mic. */
  static boXuLy: Array<{ onaudioprocess: ((e: unknown) => void) | null }> = []
  close() {
    return Promise.resolve()
  }
}

/** jsdom không tải ảnh (`onload` không bao giờ bắn) — mà album sân khấu chỉ
 *  nhận ảnh ĐÃ tải xong (`taiTruocAnh`). Ảnh giả: tải xong NGAY khi gán `src`;
 *  URL chứa `hong` ⇒ lỗi; chứa `cham` ⇒ treo tới khi gọi `AnhGiaSanKhau.xong(url)`. */
class AnhGiaSanKhau {
  static cho = new Map<string, AnhGiaSanKhau>()
  static xong(url: string): void {
    const im = AnhGiaSanKhau.cho.get(url)
    AnhGiaSanKhau.cho.delete(url)
    im?.onload?.()
  }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  naturalWidth = 1200
  naturalHeight = 800
  private u = ''
  get src(): string {
    return this.u
  }
  set src(v: string) {
    this.u = v
    if (v.includes('hong')) this.onerror?.()
    else if (v.includes('cham')) AnhGiaSanKhau.cho.set(v, this)
    else this.onload?.()
  }
}

function datGiaMic() {
  vi.stubGlobal('Image', AnhGiaSanKhau)
  vi.stubGlobal('AudioContext', FakeAudioContext)
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
  })
}

function boot() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/thu-agent'] }),
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
}

const trongMan = () => within(screen.getByRole('main'))
const oHoTen = () => screen.getByLabelText('Họ tên')
const oDienThoai = () => screen.getByLabelText('Số điện thoại')
const oGioiTinh = () => screen.getByLabelText('Giới tính')
const oRole = () => screen.getByLabelText('Role')
const oApiKey = () => screen.getByLabelText('API Key')
const nutApDung = () => screen.getByRole('button', { name: /áp dụng/i })
const oNhap = () => screen.getByPlaceholderText(/thử/i)
const nutGui = () => screen.getByRole('button', { name: /^gửi$/i })
const tabChat = () => screen.getByRole('tab', { name: /^chat$/i })
const tabVoice = () => screen.getByRole('tab', { name: /voice/i })

/**
 * WS URL cố định trong code — không có ô nhập, chỉ có hằng để so trong assertion.
 *
 * IMPORT từ `api.ts` chứ KHÔNG chép chuỗi domain vào đây (đổi 2026-08-24). Bản cũ
 * gõ tay `wss://noble-saas.agents-dev.noble.vn/…`, và khi domain đổi sang
 * `agent-uat.noble.vn` thì ba bài đỏ mà **không có lỗi nào** — chúng canh một giá
 * trị cấu hình, trong khi thứ đáng canh là ĐƯỜNG ỐNG: WS mở tại đúng hằng của
 * code, có `?key=` ghép sau. Đổi domain là việc sửa một dòng ở `api.ts`, không
 * phải sửa một dòng ở đây nữa.
 */
const WS_URL_CHAT = WS_URL_CHAT_MAC_DINH
const WS_URL_VOICE = WS_URL_VOICE_MAC_DINH

/** Khai đủ năm trường. `apDung: false` để kiểm trạng thái trước khi bấm. */
async function thietLap({ apDung = true }: { apDung?: boolean } = {}) {
  await waitFor(() => expect(oHoTen()).toBeInTheDocument())
  await userEvent.clear(oHoTen())
  await userEvent.clear(oDienThoai())
  await userEvent.type(oHoTen(), 'Nguyễn Văn Duy')
  await userEvent.type(oDienThoai(), '0912010999')
  await userEvent.selectOptions(oGioiTinh(), 'nam')
  await waitFor(() => expect(oRole()).toBeEnabled())
  await userEvent.selectOptions(oRole(), 'sale')
  await userEvent.selectOptions(oApiKey(), 'ody_ag_rawkey123')
  if (apDung) await userEvent.click(nutApDung())
}

/** `thietLap()` + mô phỏng WS mở + nhận `session_id` (đúng điều kiện "sẵn
 *  sàng" của giao thức thật — KHÔNG phải chỉ "WS đã mở"). Trả WS giả. */
async function ketNoiThanhCong(): Promise<FakeWebSocket> {
  await thietLap()
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
  const ws = FakeWebSocket.instances[0] as FakeWebSocket
  act(() => ws.moThanhCong())
  act(() => ws.nhan({ type: 'session_id', session_id: 'abc123' }))
  // Mặc định trang gửi tin đổi engine (V2 + Qwen3.6, `engineThu.ts`) ⇒ agent trả `engine_ok` mới «Sẵn sàng».
  act(() =>
    ws.nhan({ type: 'engine_ok', engine: 'v2', provider: 'dashscope', model: 'qwen3.6-35b-a3b' }),
  )
  await screen.findByText(/^Sẵn sàng$/)
  return ws
}

describe('Thử agent — bắt buộc có API Key', () => {
  it('chưa có khoá nào thì bảo tạo trước và chỉ đường sang đó', async () => {
    datApi({ keys: [] })
    boot()
    await waitFor(() => expect(trongMan().getByText(/cần một api key/i)).toBeInTheDocument())
    expect(trongMan().getByRole('link', { name: /tạo api key/i })).toBeInTheDocument()
  })
})

describe('Thử agent — khoá tạo trước migration 0918 (api_key: null)', () => {
  it('có khoá active nhưng không cái nào có api_key ⇒ vẫn coi là chưa có khoá dùng được', async () => {
    datApi({
      keys: [{ ...KHOA[0], id: 2, api_key: null, label: 'Khoá cũ' }],
    })
    boot()
    await waitFor(() => expect(trongMan().getByText(/cần một api key/i)).toBeInTheDocument())
    expect(trongMan().getByRole('link', { name: /tạo api key/i })).toBeInTheDocument()
  })
})

describe('Thử agent — WS URL cố định trong code, không có ô nhập', () => {
  it('không còn ô «WS URL» trên form', async () => {
    datApi()
    boot()
    await waitFor(() => expect(oHoTen()).toBeInTheDocument())
    expect(screen.queryByLabelText('WS URL')).not.toBeInTheDocument()
  })

  it('dù localStorage có cấu hình wsUrl cũ, WS vẫn mở đúng domain cố định trong code', async () => {
    localStorage.setItem(
      'thu-agent-gateway:cau-hinh',
      JSON.stringify({ wsUrl: 'wss://khac.example.com/v1/chat', apiKey: '' }),
    )
    datApi()
    boot()
    await thietLap()

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    expect((FakeWebSocket.instances[0] as FakeWebSocket).url).toBe(
      `${WS_URL_CHAT}?key=ody_ag_rawkey123`,
    )
  })

  /**
   * Cổng HÀNH VI, bổ sung cho cổng quét văn bản ở `don-khoa-tho-cu.test.ts`.
   * Cái kia canh hai tệp gateway; cái này canh KẾT QUẢ — dù khoá thô bị ghi
   * xuống từ tệp nào đi nữa.
   *
   * Bối cảnh: từ 2026-08-11 tới 27, mỗi lần bấm «Áp dụng» là portal ghi một
   * khoá `ody_ag_…` dạng rõ xuống máy người dùng và không bao giờ đọc lại. Khoá
   * đó mở được cả `/runtime-credentials` = mật khẩu Postgres của tenant.
   */
  it('bấm Áp dụng KHÔNG để khoá thô rơi vào localStorage', async () => {
    datApi()
    boot()
    await thietLap()

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))

    const tatCa = Object.keys(localStorage)
      .map((k) => `${k}=${localStorage.getItem(k) ?? ''}`)
      .join('|')
    expect(tatCa).not.toContain('ody_ag_')
  })
})

describe('Thử agent — năm trường bắt buộc', () => {
  it('vào màn là điền sẵn đủ năm ô — Áp dụng bấm được ngay', async () => {
    datApi()
    boot()
    await waitFor(() => expect(oApiKey()).toHaveValue('ody_ag_rawkey123'))
    expect(['Dũng', 'Dự', 'Thế']).toContain((oHoTen() as HTMLInputElement).value)
    expect((oDienThoai() as HTMLInputElement).value).toMatch(/^0\d{9}$/)
    expect(oGioiTinh()).toHaveValue('nam')
    expect(oRole()).toHaveValue('customer') // lựa chọn đầu tiên
    expect(nutApDung()).toBeEnabled()
  })

  it('xoá một ô thì Áp dụng khoá; điền lại mới mở', async () => {
    datApi()
    boot()
    await waitFor(() => expect(nutApDung()).toBeEnabled())

    await userEvent.clear(oHoTen())
    expect(nutApDung()).toBeDisabled()
    await userEvent.type(oHoTen(), 'Nguyễn Văn Duy')
    expect(nutApDung()).toBeEnabled()

    // Chủ động bỏ chọn role thì KHÔNG tự điền lại đè lên.
    await userEvent.selectOptions(oRole(), '')
    expect(nutApDung()).toBeDisabled()
    expect(oRole()).toHaveValue('')
  })

  it('ô Role liệt kê đúng các role trong cấu hình chung, value là key, nhãn là tên', async () => {
    datApi()
    boot()
    await waitFor(() => expect(oRole()).toBeEnabled())
    const tuyChon = within(oRole())
      .getAllByRole('option')
      .filter((o) => (o as HTMLOptionElement).value !== '')
      .map((o) => [(o as HTMLOptionElement).value, o.textContent])
    expect(tuyChon).toEqual([
      ['customer', 'Khách hàng'],
      ['sale', 'Sale'],
    ])
  })

  it('không tải được cấu hình ⇒ ô Role khoá, nói rõ không tải được', async () => {
    datApi()
    server.use(http.get('/api/v1/config', () => HttpResponse.json({}, { status: 500 })))
    boot()
    await waitFor(() =>
      expect(
        within(oRole()).getByRole('option', { name: /không tải được role/i }),
      ).toBeInTheDocument(),
    )
    expect(oRole()).toBeDisabled()
  })
})

describe('Thử agent — nối thẳng, không qua backend', () => {
  it('mở WS thẳng tới WS URL cố định trong code, gắn ?key= (KHÔNG có backend đứng giữa)', async () => {
    datApi()
    boot()
    await thietLap()

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    expect(ws.url).toBe(`${WS_URL_CHAT}?key=ody_ag_rawkey123`)
  })

  it('mở WS xong gửi NGAY bắt tay {identity, call_id} với khoá full_name (KHÔNG phải name)', async () => {
    datApi()
    boot()
    await thietLap()
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.moThanhCong())

    const batTay = JSON.parse(ws.sent[0] as string) as Record<string, unknown>
    expect(batTay['identity']).toEqual({
      full_name: 'Nguyễn Văn Duy',
      phone: '0912010999',
      gender: 'nam',
      role: 'sale',
    })
    expect(typeof batTay['call_id']).toBe('string')
  })

  it('WS mở xong nhưng CHƯA nhận session_id ⇒ agent CHƯA thức', async () => {
    datApi()
    boot()
    await thietLap()
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.moThanhCong())

    expect(screen.queryByText(/^Sẵn sàng$/)).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/thử/i)).not.toBeInTheDocument()
  })

  it('nhận session_id ⇒ agent THỨC, khung chat hiện ra', async () => {
    datApi()
    boot()
    await ketNoiThanhCong()
    expect(oNhap()).toBeInTheDocument()
  })
})

describe('Thử agent — agent ngủ / thức', () => {
  it('SỬA một ô sau khi áp dụng ⇒ agent ngủ lại, đóng WS, phải áp dụng lần nữa', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()

    // Sau Áp dụng thẻ thiết lập thu gọn (tab Chat) — mở lại rồi mới sửa được ô.
    await userEvent.click(screen.getByRole('button', { name: 'Sửa thiết lập' }))
    await userEvent.type(oHoTen(), ' Anh')

    await waitFor(() => expect(screen.queryByPlaceholderText(/thử/i)).not.toBeInTheDocument())
    expect(nutApDung()).toBeEnabled()
    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
  })
})

describe('Thử agent — danh tính + API Key dùng chung giữa hai tab', () => {
  it('gõ ở tab Chat, sang tab Voice thì bốn ô vẫn còn nguyên chữ', async () => {
    datApi()
    boot()
    await thietLap({ apDung: false })

    await userEvent.click(tabVoice())

    await waitFor(() => expect(oHoTen()).toHaveValue('Nguyễn Văn Duy'))
    expect(oDienThoai()).toHaveValue('0912010999')
    expect(oGioiTinh()).toHaveValue('nam')
    expect(oApiKey()).toHaveValue('ody_ag_rawkey123')
  })

  it('gõ ở tab Voice, quay lại tab Chat thì bốn ô vẫn còn nguyên chữ', async () => {
    datApi()
    boot()
    await waitFor(() => expect(tabVoice()).toBeInTheDocument())
    await userEvent.click(tabVoice())
    await thietLap({ apDung: false })

    await userEvent.click(tabChat())

    await waitFor(() => expect(oHoTen()).toHaveValue('Nguyễn Văn Duy'))
    expect(oDienThoai()).toHaveValue('0912010999')
    expect(oGioiTinh()).toHaveValue('nam')
    expect(oApiKey()).toHaveValue('ody_ag_rawkey123')
  })

  it('đang chạy phiên ở Chat, sang Voice rồi quay lại ⇒ CHỮ còn, nhưng phiên đã đóng (phải Áp dụng lại)', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()

    await userEvent.click(tabVoice())
    await userEvent.click(tabChat())

    await waitFor(() => expect(oHoTen()).toHaveValue('Nguyễn Văn Duy'))
    expect(oApiKey()).toHaveValue('ody_ag_rawkey123')
    expect(nutApDung()).toBeEnabled() // chưa Áp dụng lại — phiên cũ đã đóng
    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
  })
})

describe('Thử agent — đổi tab Chat/Voice giữ focus ở hàng tab', () => {
  /** Hai nhánh là hai component khác nhau: hàng tab từng nằm TRONG nhánh nên
   *  đổi tab gỡ luôn nút vừa bấm và focus rơi về `<body>` (audit a11y 05/10). */
  it('bấm hoặc dùng ←/→ đổi tab ⇒ focus nằm ở nút tab vừa chọn', async () => {
    datApi()
    boot()
    await waitFor(() => expect(tabVoice()).toBeInTheDocument())

    await userEvent.click(tabVoice())
    await screen.findByTestId('nguoi-dan') // nhánh Voice đã dựng
    expect(tabVoice()).toHaveAttribute('aria-selected', 'true')
    expect(tabVoice()).toHaveFocus()

    await userEvent.keyboard('{ArrowLeft}')
    await waitFor(() => expect(tabChat()).toHaveAttribute('aria-selected', 'true'))
    expect(screen.queryByTestId('nguoi-dan')).toBeNull()
    expect(tabChat()).toHaveFocus()
  })
})

describe('Thử agent — khung hội thoại Chat cho trình đọc màn hình', () => {
  it('khung là role=log có tên, bận lúc agent đang stream, mỗi lượt nói rõ ai nói', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    const log = screen.getByRole('log', { name: 'Hội thoại' })
    expect(log).toHaveAttribute('aria-busy', 'false')

    await userEvent.type(oNhap(), 'Còn căn 2PN không?')
    await userEvent.click(nutGui())
    act(() => ws.nhan({ type: 'token', text: 'Dạ ' }))
    // Đang stream ⇒ trình đọc màn hình chờ, không đọc từng token.
    expect(log).toHaveAttribute('aria-busy', 'true')

    act(() => {
      ws.nhan({ type: 'token', text: 'còn 2 căn.' })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })
    expect(log).toHaveAttribute('aria-busy', 'false')
    // Tiền tố sr-only ở đầu khối mỗi lượt; chữ của bong bóng vẫn khớp đúng một chỗ.
    expect(within(log).getByText('Còn căn 2PN không?').parentElement).toHaveTextContent(
      /^Bạn: Còn căn 2PN không\?$/,
    )
    expect(within(log).getByText('Dạ còn 2 căn.').parentElement).toHaveTextContent(
      /^Agent: Dạ còn 2 căn\./,
    )
  })
})

describe('Thử agent — chat', () => {
  it('gửi câu hỏi ⇒ WS nhận đúng {"type":"user_text"}', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()

    await userEvent.type(oNhap(), 'Còn căn 2PN không?')
    await userEvent.click(nutGui())

    expect(ws.sent.at(-1)).toEqual(
      JSON.stringify({ type: 'user_text', text: 'Còn căn 2PN không?' }),
    )
    expect(await screen.findByText('Còn căn 2PN không?')).toBeInTheDocument()
  })

  it('ghép các event token liên tiếp thành một bong bóng, hiện tool call', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Còn căn 2PN không?')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'kb_search', args: {} })
      ws.nhan({ type: 'token', text: 'Dạ ' })
      ws.nhan({ type: 'token', text: 'còn 2 căn.' })
      ws.nhan({ type: 'tool_done', tool: 'kb_search', result: '{}' })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    expect(await screen.findByText('Dạ còn 2 căn.')).toBeInTheDocument()
    expect(screen.getByText('kb_search')).toBeInTheDocument()
    expect(screen.getByText('tool_done')).toBeInTheDocument()
  })

  it('tool_done.result mang items[] (send_media) ⇒ hiện card ảnh, đúng doc §4.3', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Cho mình xem hình dự án')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'send_media', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        // `result` là CHUỖI JSON (doc §4.3), không phải object.
        result: JSON.stringify({
          ok: true,
          project_name: 'Noble Crystal',
          caption: 'Hình ảnh dự án Noble Crystal',
          count: 2,
          message: 'Dạ em gửi hình ảnh dự án qua app cho anh/chị rồi ạ.',
          items: [
            {
              kind: 'image',
              url: 'https://x.test/full1.jpg',
              label: 'Phối cảnh',
              thumb: 'https://x.test/t1.jpg',
            },
            { kind: 'image', url: 'https://x.test/full2.jpg' },
          ],
        }),
      })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    const the = await screen.findByText('Hình ảnh dự án Noble Crystal')
    await waitFor(() => expect(the.closest('div')?.querySelectorAll('img')).toHaveLength(2))
  })

  it('kb_search trả items kind=file ⇒ hiện thẻ tệp kèm, không rơi im lặng', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'chính sách bán hàng thế nào')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'kb_search', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'kb_search',
        result: JSON.stringify({
          context: '[SOLA › CHÍNH SÁCH BÁN HÀNG] ...',
          items: [
            {
              kind: 'file',
              url: 'https://nbx.test/qc-sola__csbh.png',
              label: 'CSBH SOLA quý 3.png',
              thumb: 'https://portal.test/thumb.webp',
            },
          ],
        }),
      })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    const lien = await screen.findByRole('link', { name: /CSBH SOLA quý 3\.png/ })
    expect(lien).toHaveAttribute('href', 'https://nbx.test/qc-sola__csbh.png')
  })

  it('send_media trả items kind=tour ⇒ hiện thẻ tour 360', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'có tour 360 không em')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'send_media', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({
          ok: true,
          caption: 'Tour 360 dự án',
          items: [
            {
              kind: 'tour',
              url: 'https://kuula.co/share/collection/7MgHS?logo=1&fs=1',
              label: 'Tour tham quan thực tế ảo 360 độ — SOLA',
            },
          ],
        }),
      })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    const lien = await screen.findByRole('link', { name: /Tour tham quan thực tế ảo 360 độ/ })
    expect(lien).toHaveAttribute('href', 'https://kuula.co/share/collection/7MgHS?logo=1&fs=1')
  })

  // Biến thể `video{url,embed_url?,thumb?}` (2026-08-25): agent phát cho video KHÔNG
  // phải YouTube (Google Drive `file/d/<id>` → url gốc + embed_url `/preview` +
  // thumb; folder/host khác → chỉ url). Portal không có lightbox video nên chỉ
  // mở `url` tab mới — `embed_url` dành cho client có lightbox (AINA).
  it('send_media trả video Drive (url + thumb) ⇒ thẻ link mở url gốc, ảnh là thumb', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'video tiến độ tháng 5')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'send_media', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({
          ok: true,
          caption: 'Video dự án',
          items: [
            {
              kind: 'video',
              url: 'https://drive.google.com/file/d/1SqV/view',
              embed_url: 'https://drive.google.com/file/d/1SqV/preview',
              thumb: 'https://drive.google.com/thumbnail?id=1SqV&sz=w480',
              title: 'Tiến độ tháng 5.2026',
            },
          ],
        }),
      })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    const lien = await screen.findByRole('link', { name: /Tiến độ tháng 5\.2026/ })
    expect(lien).toHaveAttribute('href', 'https://drive.google.com/file/d/1SqV/view')
    expect(lien).toHaveAttribute('target', '_blank')
    expect(within(lien).getByRole('img')).toHaveAttribute(
      'src',
      'https://drive.google.com/thumbnail?id=1SqV&sz=w480',
    )
  })

  it('video url KHÔNG có thumb ⇒ ô ▶ + title, không có img rỗng', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'video')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({
          ok: true,
          items: [{ kind: 'video', url: 'https://vimeo.com/123', title: 'Clip flycam' }],
        }),
      })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    const lien = await screen.findByRole('link', { name: /Clip flycam/ })
    expect(lien).toHaveAttribute('href', 'https://vimeo.com/123')
    expect(within(lien).queryByRole('img')).not.toBeInTheDocument()
  })

  it('video thiếu CẢ video_id lẫn url ⇒ bỏ phần tử, không đoán', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'ảnh')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({
          ok: true,
          items: [
            { kind: 'video', title: 'hỏng' },
            { kind: 'image', url: 'https://s3/a.jpg', label: 'Phối cảnh' },
          ],
        }),
      })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    expect(await screen.findByRole('img', { name: 'Phối cảnh' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /hỏng/ })).not.toBeInTheDocument()
  })

  it('tool_done.result KHÔNG mang items[] (vd kb_search) ⇒ KHÔNG hiện card', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Còn căn 2PN không?')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'kb_search', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'kb_search',
        result: JSON.stringify({ ok: false, items: [], count: 0, note: 'no_media' }),
      })
      ws.nhan({ type: 'token', text: 'Dạ hiện chưa có ảnh ạ.' })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    expect(await screen.findByText('Dạ hiện chưa có ảnh ạ.')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('event error hiện banner nhưng KHÔNG đóng phiên (vẫn có done theo sau)', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()

    act(() => {
      ws.nhan({ type: 'error', message: 'Xin lỗi, hệ thống đang bận.' })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    expect(await screen.findByText('Xin lỗi, hệ thống đang bận.')).toBeInTheDocument()
    expect(oNhap()).toBeInTheDocument()
  })

  it('suggestions là {label,text}[] — hiện LABEL, bấm điền TEXT vào ô nhập, KHÔNG tự gửi', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()

    act(() =>
      ws.nhan({
        type: 'suggestions',
        items: [{ label: 'Xem hình ảnh', text: 'Cho mình xem hình dự án' }],
      }),
    )
    const chip = await screen.findByRole('button', { name: 'Xem hình ảnh' })
    await userEvent.click(chip)

    expect(oNhap()).toHaveValue('Cho mình xem hình dự án')
    expect(
      ws.sent.filter((s) => (JSON.parse(s) as { type: string }).type === 'user_text'),
    ).toHaveLength(0)
  })

  it('Reset hội thoại gửi {"type":"reset"} và xoá lịch sử hiển thị', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Còn căn 2PN không?')
    await userEvent.click(nutGui())
    expect(await screen.findByText('Còn căn 2PN không?')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /reset hội thoại/i }))

    expect(ws.sent.at(-1)).toEqual(JSON.stringify({ type: 'reset' }))
    expect(screen.queryByText('Còn căn 2PN không?')).not.toBeInTheDocument()
    expect(screen.getByText(/chưa có tin nhắn/i)).toBeInTheDocument()
  })
})

/** `window.Image` giả — jsdom không tải ảnh thật nên `onload` không tự bắn.
 *  Ghi lại từng instance để test tự gọi `onload()` đúng lúc, mô phỏng
 *  "ảnh gốc tải xong". */
class FakeImage {
  static instances: FakeImage[] = []
  onload: (() => void) | null = null
  private _src = ''
  constructor() {
    FakeImage.instances.push(this)
  }
  set src(v: string) {
    this._src = v
  }
  get src() {
    return this._src
  }
}

describe('Thử agent — lightbox ảnh trong card media', () => {
  /** Mở phiên, gửi câu hỏi, mô phỏng `send_media` trả 2 ảnh (một có `thumb`,
   *  một không) — dựng sẵn card để mỗi test chỉ còn việc tương tác lightbox. */
  async function moCardMedia(): Promise<void> {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Cho mình xem hình dự án')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'send_media', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({
          ok: true,
          caption: 'Hình ảnh dự án Noble Crystal',
          items: [
            {
              kind: 'image',
              url: 'https://x.test/full1.jpg',
              label: 'Phối cảnh',
              thumb: 'https://x.test/t1.jpg',
            },
            { kind: 'image', url: 'https://x.test/full2.jpg' },
          ],
        }),
      })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })
    await screen.findByText('Hình ảnh dự án Noble Crystal')
  }

  beforeEach(() => {
    FakeImage.instances = []
  })

  it('bấm ảnh mở lightbox, hiện thumb trước rồi nâng cấp sang ảnh gốc khi tải xong', async () => {
    vi.stubGlobal('Image', FakeImage)
    await moCardMedia()

    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))
    const dialog = screen.getByRole('dialog')
    const anhLon = within(dialog).getByRole('img')
    expect(anhLon).toHaveAttribute('src', 'https://x.test/t1.jpg')

    const anhNen = FakeImage.instances.at(-1)
    expect(anhNen?.src).toBe('https://x.test/full1.jpg')
    act(() => anhNen?.onload?.())

    await waitFor(() => expect(anhLon).toHaveAttribute('src', 'https://x.test/full1.jpg'))
  })

  it('ảnh không có thumb thì hiện thẳng url gốc, không có bước nâng cấp', async () => {
    vi.stubGlobal('Image', FakeImage)
    await moCardMedia()

    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh' }))
    const dialog = screen.getByRole('dialog')
    // `alt=""` (không có `label`) làm ảnh thành "presentation" trong cây
    // accessibility — cùng lý do test media Voice dùng querySelector thay vì
    // getByRole('img'), xem comment ở đó.
    expect(dialog.querySelector('img')).toHaveAttribute('src', 'https://x.test/full2.jpg')
    expect(FakeImage.instances).toHaveLength(0)
  })

  it('bấm nút × đóng lightbox, focus trả về đúng nút ảnh vừa mở', async () => {
    await moCardMedia()
    const nutAnh = screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' })
    await userEvent.click(nutAnh)

    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /đóng/i }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(nutAnh).toHaveFocus()
  })

  it('phím Esc đóng lightbox', async () => {
    await moCardMedia()
    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('bấm ra ngoài (backdrop) đóng lightbox', async () => {
    await moCardMedia()
    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))

    // Nền là `::backdrop` của `<dialog>` (`HopThoai`), không còn là nút: cú bấm
    // tới chính `<dialog>` với toạ độ NGOÀI khung — khuôn `hop-thoai.test.tsx`.
    // jsdom trả 0 cho mọi `getBoundingClientRect` và không có `PointerEvent`.
    const dialog = screen.getByRole('dialog')
    dialog.getBoundingClientRect = () =>
      ({ left: 100, right: 300, top: 100, bottom: 300, width: 200, height: 200 }) as DOMRect
    fireEvent(dialog, new MouseEvent('pointerdown', { clientX: 10, clientY: 10, bubbles: true }))
    fireEvent.click(dialog, { clientX: 10, clientY: 10 })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('thumb lưới hỏng thì rơi về ảnh gốc, không để ô trắng', async () => {
    // 2026-08-13: payload Qdrant của một tenant mang KHOÁ S3 thay vì URL, trình duyệt
    // nối tương đối rồi 404 — và vì lưới chỉ đọc `thumb` nên ảnh gốc vẫn 200 cũng mất.
    await moCardMedia()
    const anh = within(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' })).getByRole('img')
    expect(anh).toHaveAttribute('src', 'https://x.test/t1.jpg')

    fireEvent.error(anh)

    await waitFor(() => expect(anh).toHaveAttribute('src', 'https://x.test/full1.jpg'))
  })

  it('thumb hỏng trong lightbox cũng rơi về ảnh gốc', async () => {
    vi.stubGlobal('Image', FakeImage)
    await moCardMedia()
    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))
    const anhLon = within(screen.getByRole('dialog')).getByRole('img')

    fireEvent.error(anhLon)

    await waitFor(() => expect(anhLon).toHaveAttribute('src', 'https://x.test/full1.jpg'))
  })

  it('lưới card media giờ 2 cột (không phải 3)', async () => {
    await moCardMedia()
    // Nút ảnh nay nằm trong `<figure>` (chú thích số ảnh) — lưới là ông của
    // nút, không còn là cha trực tiếp.
    const grid = screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }).parentElement
      ?.parentElement
    expect(grid).toHaveClass('grid-cols-2')
  })

  /**
   * Lightbox PORTAL ra `document.body` (2026-08-24, người dùng báo ảnh mở ra
   * lệch hẳn sang một bên trên màn thật): `position: fixed` mà mount sâu trong
   * cây bong bóng thì một tổ tiên có transform/filter bất kỳ bắt nó làm
   * containing block — `inset-0` lúc đó là toạ độ so với TỔ TIÊN đó, không phải
   * viewport, và ảnh trôi theo. jsdom không dựng containing block nên không bài
   * render nào bắt được vị trí — cổng này đo thứ jsdom ĐO ĐƯỢC và cũng chính là
   * nguyên nhân: quan hệ CHA-CON. Cùng khuôn cổng portal của HopTip
   * (`overview-man.test.tsx`, 2026-08-14).
   */
  it('lightbox portal ra body — KHÔNG nằm trong card media', async () => {
    await moCardMedia()
    const card = screen.getByText('Hình ảnh dự án Noble Crystal').parentElement as HTMLElement
    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))

    const dialog = screen.getByRole('dialog')
    expect(card.contains(dialog)).toBe(false)
    expect(document.body.contains(dialog)).toBe(true)
  })

  /**
   * ĐIỀU HƯỚNG GIỮA CÁC ẢNH (2026-08-24) — người dùng ĐẢO chốt 2026-08-11
   * («không làm mũi tên trái/phải»): dùng thật mới thấy card nhiều ảnh mà mỗi
   * lần xem một ảnh phải đóng-mở lại là quá đắt. Mũi tên trên màn + phím
   * ArrowLeft/ArrowRight, KẸP ở hai đầu (không vòng lại).
   */
  it('nút mũi tên chuyển giữa các ảnh trong cùng card, kèm bộ đếm', async () => {
    vi.stubGlobal('Image', FakeImage)
    await moCardMedia()
    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('1/2')).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Ảnh sau' }))
    // Ảnh 2 không có `label` ⇒ `alt=""` ⇒ ra khỏi cây accessibility, đọc bằng
    // querySelector — cùng lý do bài «không có thumb» phía trên.
    expect(dialog.querySelector('img')).toHaveAttribute('src', 'https://x.test/full2.jpg')
    expect(within(dialog).getByText('2/2')).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Ảnh trước' }))
    expect(dialog.querySelector('img')).toHaveAttribute('src', 'https://x.test/t1.jpg')
  })

  it('phím mũi tên trái/phải cũng chuyển ảnh', async () => {
    vi.stubGlobal('Image', FakeImage)
    await moCardMedia()
    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))
    const dialog = screen.getByRole('dialog')

    await userEvent.keyboard('{ArrowRight}')
    expect(dialog.querySelector('img')).toHaveAttribute('src', 'https://x.test/full2.jpg')

    await userEvent.keyboard('{ArrowLeft}')
    expect(dialog.querySelector('img')).toHaveAttribute('src', 'https://x.test/t1.jpg')
  })

  it('mũi tên KHOÁ ở hai đầu — không vòng từ ảnh cuối về ảnh đầu', async () => {
    vi.stubGlobal('Image', FakeImage)
    await moCardMedia()
    await userEvent.click(screen.getByRole('button', { name: 'Xem ảnh: Phối cảnh' }))
    const dialog = screen.getByRole('dialog')

    expect(within(dialog).getByRole('button', { name: 'Ảnh trước' })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Ảnh sau' }))
    expect(within(dialog).getByRole('button', { name: 'Ảnh sau' })).toBeDisabled()
    // Phím mũi tên cũng kẹp: bấm tiếp ở đầu cuối thì đứng yên, không ném lỗi.
    await userEvent.keyboard('{ArrowRight}')
    expect(dialog.querySelector('img')).toHaveAttribute('src', 'https://x.test/full2.jpg')
  })
})

/**
 * Chú thích số ảnh («Ảnh N») trên từng ô lưới — bài canh RIÊNG cho
 * `figcaption`, khác cổng thuần `chuanHoaMedia — giữ số ảnh` phía dưới (đó
 * chỉ canh `index` sống sót qua chuẩn hoá, không canh nó có LÊN MÀN HÌNH hay
 * không). Một reviewer xoá nguyên khối JSX `figcaption` và 74/74 test cũ vẫn
 * xanh — không bài nào từng render và đọc con số đó trên màn.
 */
describe('Thử agent — chú thích số ảnh trên card media', () => {
  async function moCardVoiChiSo(
    items: Array<{ kind: 'image'; url: string; label?: string; index?: number }>,
  ): Promise<void> {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Cho mình xem hình dự án')
    await userEvent.click(nutGui())

    // Trích dẫn đủ mọi `index` đang có — bài canh này canh `figcaption`, không
    // canh bộ lọc trích dẫn, nên câu trả lời phải nhắc hết để ảnh không bị lọc.
    const soCanNhac = items.map((it) => it.index).filter((so): so is number => so !== undefined)
    const loiDap =
      soCanNhac.length > 0
        ? `Dạ, mời xem ${soCanNhac.map((so) => `ảnh ${so}`).join(' và ')} nhé.`
        : 'Dạ, mời xem ảnh nhé.'

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'send_media', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({ ok: true, items }),
      })
      ws.nhan({ type: 'token', text: loiDap })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })
  }

  it('ảnh có `index` hiện "Ảnh N" gắn đúng vào ô của nó', async () => {
    await moCardVoiChiSo([
      { kind: 'image', url: 'https://x.test/a.jpg', label: 'Sảnh chính', index: 3 },
    ])

    const nutAnh = await screen.findByRole('button', { name: 'Xem ảnh: Sảnh chính' })
    const figure = nutAnh.parentElement as HTMLElement
    expect(figure.tagName.toLowerCase()).toBe('figure')
    const chuThich = figure.querySelector('figcaption')
    expect(chuThich).not.toBeNull()
    expect(chuThich?.textContent).toContain('Ảnh 3')
    expect(chuThich?.textContent).toContain('Sảnh chính')
  })

  it('ảnh KHÔNG có `index` không hiện chú thích nào (ca agent cũ, không được hồi quy)', async () => {
    await moCardVoiChiSo([{ kind: 'image', url: 'https://x.test/b.jpg', label: 'Hồ bơi' }])

    const nutAnh = await screen.findByRole('button', { name: 'Xem ảnh: Hồ bơi' })
    const figure = nutAnh.parentElement as HTMLElement
    expect(figure.querySelector('figcaption')).toBeNull()
  })

  it('nhiều ảnh trong cùng card — thiếu `index` ở một ô không làm lệch số của ô khác', async () => {
    await moCardVoiChiSo([
      { kind: 'image', url: 'https://x.test/a.jpg', label: 'Sảnh chính', index: 3 },
      { kind: 'image', url: 'https://x.test/b.jpg', label: 'Hồ bơi' },
      { kind: 'image', url: 'https://x.test/c.jpg', label: 'Phòng gym', index: 1 },
    ])

    const figureCua = async (label: string) => {
      const nut = await screen.findByRole('button', { name: `Xem ảnh: ${label}` })
      return nut.parentElement as HTMLElement
    }

    const figSanh = await figureCua('Sảnh chính')
    expect(figSanh.querySelector('figcaption')?.textContent).toContain('Ảnh 3')

    const figHoBoi = await figureCua('Hồ bơi')
    expect(figHoBoi.querySelector('figcaption')).toBeNull()

    const figGym = await figureCua('Phòng gym')
    expect(figGym.querySelector('figcaption')?.textContent).toContain('Ảnh 1')
  })
})

/**
 * `kb_search` trả ảnh của cả năm chunk lân cận trong tài liệu, không phải chỉ
 * ảnh liên quan câu hỏi — câu trả lời chỉ nói tới đúng vài tấm bằng số thứ tự
 * («xem ảnh 2»). Card phải chỉ hiện đúng những ảnh được nhắc, không phải mọi
 * ảnh `kb_search` tìm thấy.
 */
describe('Thử agent — lọc ảnh theo trích dẫn trong câu trả lời', () => {
  /** Ba ảnh có `index` 1/2/3, rồi câu trả lời lần lượt từng `tokens` — media
   *  đến TRƯỚC (qua `tool_done`), chữ trả lời STREAM SAU, đúng thứ tự event
   *  thật của `moPhienChatGateway`. */
  async function moCardVoiTrichDan(tokens: string[]): Promise<void> {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Cho mình xem hình dự án')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'send_media', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({
          ok: true,
          items: [
            { kind: 'image', url: 'https://x.test/a.jpg', label: 'Sảnh chính', index: 1 },
            { kind: 'image', url: 'https://x.test/b.jpg', label: 'Hồ bơi', index: 2 },
            { kind: 'image', url: 'https://x.test/c.jpg', label: 'Phòng gym', index: 3 },
          ],
        }),
      })
      for (const text of tokens) ws.nhan({ type: 'token', text })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })
  }

  const nutAnh = (label: string) => screen.queryByRole('button', { name: `Xem ảnh: ${label}` })

  it('trích dẫn đúng một số ⇒ chỉ ảnh đó hiện, hai ảnh còn lại bị ẩn', async () => {
    await moCardVoiTrichDan(['Dạ, bạn xem ảnh 2 nhé.'])

    expect(await screen.findByRole('button', { name: 'Xem ảnh: Hồ bơi' })).toBeInTheDocument()
    expect(nutAnh('Sảnh chính')).not.toBeInTheDocument()
    expect(nutAnh('Phòng gym')).not.toBeInTheDocument()
  })

  it('trích dẫn hai số ⇒ cả hai ảnh hiện, ảnh không được nhắc bị ẩn', async () => {
    await moCardVoiTrichDan(['Dạ, xem ảnh 1 và tham khảo thêm ảnh 3 nhé.'])

    expect(await screen.findByRole('button', { name: 'Xem ảnh: Sảnh chính' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Xem ảnh: Phòng gym' })).toBeInTheDocument()
    expect(nutAnh('Hồ bơi')).not.toBeInTheDocument()
  })

  it('ảnh có `index` nhưng câu trả lời không trích dẫn số nào ⇒ ẩn hết, không phải hiện đủ', async () => {
    await moCardVoiTrichDan(['Dạ, dự án có nhiều tiện ích nội khu.'])

    expect(nutAnh('Sảnh chính')).not.toBeInTheDocument()
    expect(nutAnh('Hồ bơi')).not.toBeInTheDocument()
    expect(nutAnh('Phòng gym')).not.toBeInTheDocument()
  })

  it('không trích dẫn số nào và không có mục `file` ⇒ card không hiện gì, không để lại khung/lề', async () => {
    await moCardVoiTrichDan(['Dạ, em chưa tìm thấy thông tin trong tài liệu.'])

    const bongBong = await waitFor(() => {
      const el = screen.getByText('Dạ, em chưa tìm thấy thông tin trong tài liệu.')
      return el.parentElement as HTMLElement
    })
    // Không card ảnh nào ở lại quanh bong bóng chữ — không `<img>`, không
    // khung `bg-surface` của `TheMedia` trôi ra dù rỗng.
    expect(bongBong.querySelector('img')).toBeNull()
    expect(bongBong.querySelector('.bg-surface')).toBeNull()
    expect(nutAnh('Sảnh chính')).not.toBeInTheDocument()
  })

  it('mục `file` (tài liệu nguồn) không có số ⇒ luôn hiện, không bị lọc theo trích dẫn', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Cho mình xem hình dự án')
    await userEvent.click(nutGui())

    act(() => {
      ws.nhan({ type: 'tool_start', tool: 'send_media', args: {} })
      ws.nhan({
        type: 'tool_done',
        tool: 'send_media',
        result: JSON.stringify({
          ok: true,
          items: [
            { kind: 'image', url: 'https://x.test/a.jpg', label: 'Sảnh chính', index: 1 },
            { kind: 'image', url: 'https://x.test/b.jpg', label: 'Hồ bơi', index: 2 },
            { kind: 'file', url: 'https://x.test/brochure.pdf', label: 'Brochure dự án' },
          ],
        }),
      })
      ws.nhan({ type: 'token', text: 'Dạ, bạn xem ảnh 1 nhé.' })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })

    expect(await screen.findByRole('button', { name: 'Xem ảnh: Sảnh chính' })).toBeInTheDocument()
    expect(nutAnh('Hồ bơi')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Brochure dự án' })).toBeInTheDocument()
  })
})

describe('Thử agent — tab Voice, nối thẳng qua /v1/voice', () => {
  const nutDung = () => screen.getByRole('button', { name: /^kết thúc$/i })

  /** Chuyển tab Voice, khai đủ bốn ô, bấm Áp dụng. CHƯA mở WS/mic — đó là
   *  việc của nút «Bắt đầu trò chuyện» bên trong (tách hai bước, xem
   *  docstring `CheGiongNoi`). */
  async function thietLapVoice(): Promise<void> {
    // Màn mở mặc định ở tab Chat — chờ nó render xong (khoá đã tải) rồi mới
    // bấm sang Voice, nếu không `tabVoice()` tìm trên một cây rỗng.
    await waitFor(() => expect(tabVoice()).toBeInTheDocument())
    await userEvent.click(tabVoice())
    await waitFor(() => expect(oHoTen()).toBeInTheDocument())
    await userEvent.clear(oHoTen())
    await userEvent.clear(oDienThoai())
    await userEvent.type(oHoTen(), 'Nguyễn Văn Duy')
    await userEvent.type(oDienThoai(), '0912010999')
    await userEvent.selectOptions(oGioiTinh(), 'nam')
    await waitFor(() => expect(oRole()).toBeEnabled())
    await userEvent.selectOptions(oRole(), 'sale')
    await userEvent.selectOptions(oApiKey(), 'ody_ag_rawkey123')
    await userEvent.click(nutApDung())
  }

  /** `thietLapVoice()` + bấm «Bắt đầu trò chuyện» + mô phỏng WS mở. Trả WS giả. */
  async function batDauNoi(): Promise<FakeWebSocket> {
    datGiaMic()
    await thietLapVoice()
    await userEvent.click(await screen.findByRole('button', { name: /bắt đầu trò chuyện/i }))
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.moThanhCong())
    return ws
  }

  it('sân khấu người dẫn CHỈ có ở tab Voice — cả trước lẫn sau Áp dụng, tab Chat không có', async () => {
    datApi()
    boot()
    await waitFor(() => expect(tabVoice()).toBeInTheDocument())
    expect(screen.queryByTestId('nguoi-dan')).toBeNull()

    await userEvent.click(tabVoice())
    expect(await screen.findByTestId('nguoi-dan')).toBeInTheDocument()

    await userEvent.clear(oHoTen())

    await userEvent.clear(oDienThoai())

    await userEvent.type(oHoTen(), 'Nguyễn Văn Duy')
    await userEvent.type(oDienThoai(), '0912010999')
    await userEvent.selectOptions(oGioiTinh(), 'nam')
    await waitFor(() => expect(oRole()).toBeEnabled())
    await userEvent.selectOptions(oRole(), 'sale')
    await userEvent.selectOptions(oApiKey(), 'ody_ag_rawkey123')
    await userEvent.click(nutApDung())
    await screen.findByRole('button', { name: /bắt đầu trò chuyện/i })
    // jsdom không có WebGL ⇒ người dẫn rơi về ảnh tĩnh khung nghỉ, đứng im.
    const nguoi = screen.getByTestId('nguoi-dan')
    expect(nguoi).toHaveAttribute('data-dang-noi', '0')
    expect(nguoi.querySelector('img')?.getAttribute('src')).toBe('/nguoi-dan-nghi.webp')
  })

  it('video người dẫn CHỈ tải sau Áp dụng — mở tab Voice để xem là ảnh tĩnh', async () => {
    // jsdom không có WebGL ⇒ người dẫn luôn ảnh tĩnh. Giả CÓ WebGL để nhánh video
    // dựng được; `getContext` trả null nên vòng vẽ thoát sớm, `<video>` vẫn ở DOM.
    const coWebGl = 'WebGLRenderingContext' in window
    Object.assign(window, { WebGLRenderingContext: function () {} })
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    try {
      datApi()
      boot()
      await waitFor(() => expect(tabVoice()).toBeInTheDocument())
      await userEvent.click(tabVoice())
      const truoc = await screen.findByTestId('nguoi-dan')
      expect(truoc.querySelector('video')).toBeNull()
      expect(truoc.querySelector('img')?.getAttribute('src')).toBe('/nguoi-dan-nghi.webp')

      await userEvent.clear(oHoTen())
      await userEvent.clear(oDienThoai())
      await userEvent.type(oHoTen(), 'Nguyễn Văn Duy')
      await userEvent.type(oDienThoai(), '0912010999')
      await userEvent.selectOptions(oGioiTinh(), 'nam')
      await waitFor(() => expect(oRole()).toBeEnabled())
      await userEvent.selectOptions(oRole(), 'sale')
      await userEvent.selectOptions(oApiKey(), 'ody_ag_rawkey123')
      await userEvent.click(nutApDung())
      await screen.findByRole('button', { name: /bắt đầu trò chuyện/i })
      const sau = screen.getByTestId('nguoi-dan')
      expect(sau.querySelectorAll('video')).toHaveLength(2)
      expect(sau.querySelector('video')?.getAttribute('src')).toBe('/nguoi-dan.mp4')
    } finally {
      getContext.mockRestore()
      if (!coWebGl) delete (window as { WebGLRenderingContext?: unknown }).WebGLRenderingContext
    }
  })

  it('vòng mức micro chạy theo từng khối mic; Kết thúc ⇒ về 0', async () => {
    datApi()
    boot()
    await batDauNoi()
    const meter = screen.getByRole('meter', { name: /mức micro/i })
    expect(meter).toHaveAttribute('aria-valuenow', '0')
    const khoi = new Float32Array(4096).fill(0.1) // RMS 0,1 × 4 ⇒ 40%
    act(() =>
      FakeAudioContext.boXuLy
        .at(-1)
        ?.onaudioprocess?.({ inputBuffer: { getChannelData: () => khoi } }),
    )
    expect(meter).toHaveAttribute('aria-valuenow', '40')
    await userEvent.click(screen.getByRole('button', { name: /kết thúc/i }))
    expect(screen.getByRole('meter', { name: /mức micro/i })).toHaveAttribute('aria-valuenow', '0')
  })

  it('Áp dụng CHƯA mở WS — chỉ mở khoá cho nút «Bắt đầu trò chuyện»', async () => {
    datApi()
    boot()
    await thietLapVoice()

    expect(await screen.findByRole('button', { name: /bắt đầu trò chuyện/i })).toBeInTheDocument()
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it('bấm Bắt đầu trò chuyện ⇒ mở WS thẳng tới .../v1/voice cố định trong code, gắn ?key=', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    expect(ws.url).toBe(`${WS_URL_VOICE}?key=ody_ag_rawkey123`)
    // Chưa có tiếng agent ⇒ còn đang «đổ chuông».
    expect(await screen.findByText(/^Đang gọi…$/)).toBeInTheDocument()
    expect(nutDung()).toBeInTheDocument()
  })

  it('chuông chờ 425 Hz kêu từ lúc bấm, tắt khi tiếng agent ĐẦU TIÊN tới', async () => {
    FakeAudioContext.chuong = []
    datApi()
    boot()
    const ws = await batDauNoi()

    expect(FakeAudioContext.chuong.map((o) => o.frequency.value)).toEqual([425])
    expect(screen.getByText(/^Đang gọi…$/)).toBeInTheDocument()
    const guiAudio = (pcm: Int16Array) =>
      act(() =>
        (ws.onmessage as unknown as (e: { data: ArrayBuffer }) => void)({
          data: pcm.buffer as ArrayBuffer,
        }),
      )
    // Khung IM LẶNG (track LiveKit gửi ngay khi worker vào phòng) ⇒ VẪN đổ chuông.
    guiAudio(new Int16Array(480))
    expect(screen.getByText(/^Đang gọi…$/)).toBeInTheDocument()
    // Khung có tiếng ⇒ bắt máy.
    guiAudio(new Int16Array(480).fill(8000))
    expect(await screen.findByText(/^Đang nghe$/)).toBeInTheDocument()
  })

  it('khách nói trước khi agent lên tiếng ⇒ chuông tắt', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => ws.nhan({ type: 'partial_transcript', text: 'alo' }))
    expect(await screen.findByText(/^Đang nghe$/)).toBeInTheDocument()
  })

  it('mở xong gửi bắt tay {identity, call_id} — cùng khoá full_name như chat', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    const batTay = JSON.parse(ws.sent[0] as string) as Record<string, unknown>
    expect(batTay['identity']).toEqual({
      full_name: 'Nguyễn Văn Duy',
      phone: '0912010999',
      gender: 'nam',
      role: 'sale',
    })
    expect(typeof batTay['call_id']).toBe('string')
  })

  it('agent_speaking (câu chào) hiện thành bong bóng agent', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => ws.nhan({ type: 'agent_speaking', text: 'Dạ chào Quý Khách.', turn_id: 'greeting' }))

    expect(await screen.findByText('Dạ chào Quý Khách.')).toBeInTheDocument()
  })

  it('transcript (khách) + agent_speaking (agent, cùng turn_id) ra HAI bong bóng, tool chip gắn đúng lượt', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => {
      ws.nhan({ type: 'transcript', text: 'Dự án nào đang mở bán?', turn_id: 't1' })
      ws.nhan({ type: 'tool_start', tool: 'kb_search', args: {} })
      ws.nhan({ type: 'tool_done', tool: 'kb_search' })
      ws.nhan({ type: 'agent_speaking', text: 'Dạ,', turn_id: 't1', sentence_id: 0 })
      ws.nhan({
        type: 'agent_speaking',
        text: 'Noble Crystal đang mở bán.',
        turn_id: 't1',
        sentence_id: 1,
      })
      ws.nhan({ type: 'agent_done', turn_id: 't1' })
    })

    expect(await screen.findByText('Dự án nào đang mở bán?')).toBeInTheDocument()
    expect(await screen.findByText('Dạ, Noble Crystal đang mở bán.')).toBeInTheDocument()
    expect(screen.getByText('kb_search')).toBeInTheDocument()
    expect(screen.getByText('tool_done')).toBeInTheDocument()
  })

  it('trình đọc màn hình: trạng thái gọi là MỘT vùng status, khung hội thoại bận trong lượt agent', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    const trangThai = await screen.findByText(/^Đang gọi…$/)
    expect(trangThai).toHaveAttribute('role', 'status')
    act(() => ws.nhan({ type: 'partial_transcript', text: 'alo' }))
    // CÙNG phần tử, chỉ chữ đổi — vùng live mới mount thì trình đọc không đọc.
    await waitFor(() => expect(trangThai).toHaveTextContent(/^Đang nghe$/))

    const log = screen.getByRole('log', { name: 'Hội thoại' })
    // Bản nháp ghi đè liên tục ⇒ không đọc; lượt chốt mới đọc.
    expect(within(log).getByText('alo')).toHaveAttribute('aria-hidden', 'true')
    act(() => {
      ws.nhan({ type: 'transcript', text: 'Dự án nào đang mở bán?', turn_id: 't1' })
      ws.nhan({ type: 'agent_speaking', text: 'Dạ,', turn_id: 't1', sentence_id: 0 })
    })
    expect(log).toHaveAttribute('aria-busy', 'true')
    act(() => ws.nhan({ type: 'agent_done', turn_id: 't1' }))
    expect(log).toHaveAttribute('aria-busy', 'false')
    expect(within(log).getByText('Dự án nào đang mở bán?').parentElement).toHaveTextContent(
      /^Bạn: Dự án nào đang mở bán\?$/,
    )
    expect(within(log).getByText('Dạ,').parentElement).toHaveTextContent(/^Agent: Dạ,$/)
  })

  it('partial_transcript hiện bong bóng TẠM (viền đứt), transcript chốt thì thay bằng bong bóng thật', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => ws.nhan({ type: 'partial_transcript', text: 'tôi muốn hỏi về dự' }))
    expect(await screen.findByText('tôi muốn hỏi về dự')).toBeInTheDocument()

    act(() =>
      ws.nhan({ type: 'transcript', text: 'tôi muốn hỏi về dự án noble crystal', turn_id: 't1' }),
    )
    expect(screen.queryByText('tôi muốn hỏi về dự')).not.toBeInTheDocument()
    expect(await screen.findByText('tôi muốn hỏi về dự án noble crystal')).toBeInTheDocument()
  })

  it('sân khấu: nền mặc định (phông studio CSS, không ảnh); agent gửi ẢNH ⇒ ảnh đó thành nền + người dẫn đưa tay', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    const sanKhau = () => screen.getByTestId('san-khau')
    expect(sanKhau()).not.toHaveAttribute('data-anh-nen')
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '0')

    // Card chỉ có video ⇒ không đổi nền, không đưa tay.
    act(() => {
      ws.nhan({ type: 'transcript', text: 'Cho xem video', turn_id: 't1' })
      ws.nhan({ type: 'media', items: [{ kind: 'video', video_id: 'abcdefghijk' }] })
    })
    expect(sanKhau()).not.toHaveAttribute('data-anh-nen')
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '0')

    act(() => {
      ws.nhan({
        type: 'media',
        items: [
          { kind: 'image', url: 'https://x.test/phoi-canh.jpg', thumb: 'https://x.test/t.jpg' },
          { kind: 'image', url: 'https://x.test/khac.jpg' },
        ],
      })
    })
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/phoi-canh.jpg')
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '1')

    // Ảnh thứ hai ⇒ đổi nền tiếp + đưa tay lần nữa.
    act(() => {
      ws.nhan({ type: 'media', items: [{ kind: 'image', url: 'https://x.test/tien-ich.jpg' }] })
    })
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/tien-ich.jpg')
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '2')
  })

  it('sân khấu: card NHIỀU ảnh ⇒ luân phiên sau 2 lượt trả lời, không đưa tay thêm khi tự đổi', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    const sanKhau = () => screen.getByTestId('san-khau')
    act(() => {
      ws.nhan({ type: 'transcript', text: 'Cho xem hình', turn_id: 't1' })
      ws.nhan({
        type: 'media',
        items: [
          { kind: 'image', url: 'https://x.test/1.jpg' },
          { kind: 'image', url: 'https://x.test/2.jpg' },
          { kind: 'image', url: 'https://x.test/3.jpg' },
        ],
      })
    })
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/1.jpg')
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '1')

    act(() => ws.nhan({ type: 'agent_done', turn_id: 't1' }))
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/1.jpg') // mới 1 lượt
    act(() => {
      ws.nhan({ type: 'transcript', text: 'Còn gì nữa', turn_id: 't2' })
      ws.nhan({ type: 'agent_done', turn_id: 't2' })
    })
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/2.jpg')
    // Ảnh tự đổi ⇒ KHÔNG giơ tay thêm (chỉ card mới mới giơ tay).
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '1')
  })

  it('album: tự lướt sau 6,5s, vòng lại; chỉ ĐÓNG (về nền cũ) khi đã xem hết VÀ qua 3 lượt', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    // Chỉ giả đồng hồ cho phần album — phần dựng màn ở trên chạy thật.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
    try {
      act(() => {
        ws.nhan({
          type: 'media',
          items: [
            { kind: 'image', url: 'https://x.test/1.jpg' },
            { kind: 'image', url: 'https://x.test/2.jpg' },
          ],
        })
      })
      const sanKhau = () => screen.getByTestId('san-khau')
      expect(sanKhau()).toHaveAttribute('data-album', '2')
      act(() => vi.advanceTimersByTime(6_000))
      expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/1.jpg')
      act(() => vi.advanceTimersByTime(1_500))
      expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/2.jpg')
      // Đã xem hết, quá giờ nhưng chưa có lượt nào ⇒ KHÔNG đóng, vòng lại ảnh 1.
      act(() => vi.advanceTimersByTime(8_000))
      expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/1.jpg')
      act(() => vi.advanceTimersByTime(40_000))
      expect(sanKhau()).not.toHaveAttribute('data-album', '0')
      // Ba lượt trả lời xong ⇒ lần tới hết giờ thì đóng.
      for (const turn of ['t1', 't2', 't3'])
        act(() => ws.nhan({ type: 'agent_done', turn_id: turn }))
      act(() => vi.advanceTimersByTime(8_500))
      expect(sanKhau()).not.toHaveAttribute('data-anh-nen')
      expect(sanKhau()).toHaveAttribute('data-album', '0')
    } finally {
      vi.useRealTimers()
    }
  })

  it('album: giảm chuyển động ⇒ KHÔNG tự lướt theo giờ (WCAG 2.2.2); vuốt tay vẫn đổi ảnh', async () => {
    // jsdom không có `matchMedia` — giả đúng một truy vấn khớp.
    window.matchMedia = (q: string) =>
      ({
        matches: q === '(prefers-reduced-motion: reduce)',
        media: q,
        addEventListener() {},
        removeEventListener() {},
      }) as unknown as MediaQueryList
    try {
      datApi()
      boot()
      const ws = await batDauNoi()
      const anh = () => screen.getByTestId('san-khau').getAttribute('data-anh-nen')
      vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
      try {
        act(() => {
          ws.nhan({
            type: 'media',
            items: [
              { kind: 'image', url: 'https://x.test/1.jpg' },
              { kind: 'image', url: 'https://x.test/2.jpg' },
            ],
          })
        })
        act(() => vi.advanceTimersByTime(60_000))
        expect(anh()).toBe('https://x.test/1.jpg')
        expect(screen.getByTestId('san-khau')).toHaveAttribute('data-album', '2')
      } finally {
        vi.useRealTimers()
      }
      const el = screen.getByTestId('album')
      for (const [loai, x] of [
        ['pointerdown', 300],
        ['pointermove', 150],
        ['pointerup', 150],
      ] as const)
        act(() => {
          el.dispatchEvent(new MouseEvent(loai, { bubbles: true, clientX: x, button: 0 }))
        })
      expect(anh()).toBe('https://x.test/2.jpg')
    } finally {
      delete (window as { matchMedia?: unknown }).matchMedia
    }
  })

  it('album: vuốt NGANG sang trái ⇒ ảnh kế, sang phải ⇒ ảnh trước (vòng)', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    act(() => {
      ws.nhan({
        type: 'media',
        items: [
          { kind: 'image', url: 'https://x.test/1.jpg' },
          { kind: 'image', url: 'https://x.test/2.jpg' },
          { kind: 'image', url: 'https://x.test/3.jpg' },
        ],
      })
    })
    const vuot = (tu: number, toi: number) => {
      const el = screen.getByTestId('album')
      const ban = (loai: string, x: number) =>
        act(() => {
          el.dispatchEvent(new MouseEvent(loai, { bubbles: true, clientX: x, button: 0 }))
        })
      ban('pointerdown', tu)
      ban('pointermove', (tu + toi) / 2)
      ban('pointermove', toi)
      ban('pointerup', toi)
    }
    const anh = () => screen.getByTestId('san-khau').getAttribute('data-anh-nen')
    vuot(300, 150)
    expect(anh()).toBe('https://x.test/2.jpg')
    vuot(150, 300)
    vuot(150, 300)
    expect(anh()).toBe('https://x.test/3.jpg') // lùi qua ảnh 1 ⇒ vòng về cuối
    // Chạm nhẹ (không kéo) ⇒ giữ nguyên.
    vuot(200, 204)
    expect(anh()).toBe('https://x.test/3.jpg')
  })

  it('album: ảnh CHƯA tải xong thì chưa lên album (không thẻ trắng); tải xong mới mở', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    const sanKhau = () => screen.getByTestId('san-khau')
    act(() => {
      ws.nhan({ type: 'media', items: [{ kind: 'image', url: 'https://x.test/cham-1.jpg' }] })
    })
    expect(sanKhau()).toHaveAttribute('data-album', '0')
    expect(sanKhau()).not.toHaveAttribute('data-anh-nen')
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '0')
    act(() => AnhGiaSanKhau.xong('https://x.test/cham-1.jpg'))
    expect(sanKhau()).toHaveAttribute('data-album', '1')
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/cham-1.jpg')
    expect(sanKhau()).toHaveAttribute('data-lenh-gio-tay', '1')
  })

  it('album: ảnh LỖI bị bỏ qua; ảnh tải xong muộn chen vào đúng thứ tự gốc', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    const sanKhau = () => screen.getByTestId('san-khau')
    act(() => {
      ws.nhan({
        type: 'media',
        items: [
          { kind: 'image', url: 'https://x.test/cham-a.jpg' },
          { kind: 'image', url: 'https://x.test/hong-b.jpg' },
          { kind: 'image', url: 'https://x.test/c.jpg' },
        ],
      })
    })
    // c tải xong trước ⇒ album mở với c; b lỗi ⇒ không bao giờ vào.
    expect(sanKhau()).toHaveAttribute('data-album', '1')
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/c.jpg')
    act(() => AnhGiaSanKhau.xong('https://x.test/cham-a.jpg'))
    // a chen lên ĐẦU (thứ tự gốc), ảnh đang hiện vẫn là c.
    expect(sanKhau()).toHaveAttribute('data-album', '2')
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/c.jpg')
    expect(screen.getByTestId('album')).toHaveAttribute('data-album-anh', '1')
  })

  it('album: card MỚI tới thì ảnh của card cũ tải xong muộn KHÔNG chen vào', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    const sanKhau = () => screen.getByTestId('san-khau')
    act(() => {
      ws.nhan({ type: 'media', items: [{ kind: 'image', url: 'https://x.test/cham-cu.jpg' }] })
    })
    act(() => {
      ws.nhan({ type: 'media', items: [{ kind: 'image', url: 'https://x.test/moi.jpg' }] })
    })
    act(() => AnhGiaSanKhau.xong('https://x.test/cham-cu.jpg'))
    expect(sanKhau()).toHaveAttribute('data-album', '1')
    expect(sanKhau()).toHaveAttribute('data-anh-nen', 'https://x.test/moi.jpg')
  })

  it('sân khấu: cuộc gọi MỚI ⇒ nền về mặc định', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()
    act(() => {
      ws.nhan({ type: 'media', items: [{ kind: 'image', url: 'https://x.test/a.jpg' }] })
    })
    expect(screen.getByTestId('san-khau')).toHaveAttribute('data-anh-nen', 'https://x.test/a.jpg')
    await userEvent.click(nutDung())
    await userEvent.click(await screen.findByRole('button', { name: /bắt đầu trò chuyện/i }))
    expect(screen.getByTestId('san-khau')).not.toHaveAttribute('data-anh-nen')
  })

  it('event media hiện card ảnh — items[] duyệt hết, không chỉ phần tử đầu', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => {
      ws.nhan({ type: 'transcript', text: 'Cho xem hình dự án', turn_id: 't1' })
      ws.nhan({
        type: 'media',
        caption: 'Hình ảnh dự án Noble Crystal',
        message: 'Dạ em gửi hình ảnh dự án ạ.',
        items: [
          {
            kind: 'image',
            url: 'https://x.test/full1.jpg',
            label: 'Phối cảnh',
            thumb: 'https://x.test/t1.jpg',
          },
          // Phần tử THỨ HAI cố ý không có `label`/`thumb` — kiểm cả nhánh
          // thiếu optional field. `alt=""` (rơi từ `label` vắng) làm ảnh
          // thành "presentation" trong cây accessibility, nên đếm bằng
          // `querySelectorAll` thay vì `getAllByRole('img')`.
          { kind: 'image', url: 'https://x.test/full2.jpg' },
        ],
      })
    })

    const the = await screen.findByText('Hình ảnh dự án Noble Crystal')
    await waitFor(() => expect(the.closest('div')?.querySelectorAll('img')).toHaveLength(2))
  })

  /**
   * Voice không gửi `index` cho ảnh (event `media` không có khái niệm số thứ
   * tự) — dù câu nói của agent tình cờ có chữ số giống trích dẫn, card KHÔNG
   * được lọc theo nó: không có `index` thì không có gì để so, phải hiện
   * NGUYÊN như trước khi có bộ lọc.
   */
  it('card media của Voice không có `index` ⇒ không bị lọc dù lời agent có số', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => {
      ws.nhan({ type: 'transcript', text: 'Cho xem hình dự án', turn_id: 't1' })
      ws.nhan({
        type: 'agent_speaking',
        text: 'Ảnh 1 rất đẹp, còn ảnh 2 cũng đẹp không kém ạ.',
        turn_id: 't1',
      })
      ws.nhan({
        type: 'media',
        caption: 'Hình ảnh dự án Noble Crystal',
        items: [
          { kind: 'image', url: 'https://x.test/full1.jpg', label: 'Sảnh chính' },
          { kind: 'image', url: 'https://x.test/full2.jpg', label: 'Hồ bơi' },
        ],
      })
    })

    expect(await screen.findByRole('button', { name: 'Xem ảnh: Sảnh chính' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Xem ảnh: Hồ bơi' })).toBeInTheDocument()
  })

  it('agent_interrupted đánh dấu bong bóng agent đang mở là đã ngắt lời', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => {
      ws.nhan({ type: 'transcript', text: 'Câu hỏi', turn_id: 't1' })
      ws.nhan({ type: 'agent_speaking', text: 'Dạ để em tra', turn_id: 't1' })
      ws.nhan({ type: 'agent_interrupted', turn_id: 't1', last_completed_sentence_id: 0 })
    })

    expect(await screen.findByText(/đã ngắt lời/i)).toBeInTheDocument()
  })

  it('bấm Dừng ⇒ đóng WS, KHÔNG hiện banner lỗi (tự đóng)', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    await userEvent.click(nutDung())

    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /bắt đầu trò chuyện/i })).toBeInTheDocument()
  })

  it('4001/bad_credential (server đóng ngoài ý muốn) → báo lỗi đúng câu, KHÁC lúc tự đóng', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    act(() => ws.dong(4001, 'bad_credential'))

    expect(await screen.findByText(/api key không hợp lệ/i)).toBeInTheDocument()
  })

  it('Áp dụng xong form năm ô VẪN ở đó, nút thành «Đã áp dụng» (bố cục không nhảy)', async () => {
    datApi()
    boot()
    await batDauNoi()
    expect(oHoTen()).toHaveValue('Nguyễn Văn Duy')
    expect(screen.getByRole('button', { name: /^đã áp dụng$/i })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /^sửa$/i })).not.toBeInTheDocument()
  })

  it('sửa một ô khi đang gọi ⇒ đóng phiên, nút gọi khoá, phải Áp dụng lại', async () => {
    datApi()
    boot()
    const ws = await batDauNoi()

    await userEvent.type(oHoTen(), ' Anh')

    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
    // Chưa Áp dụng lại ⇒ nút gọi KHOÁ (vẫn đứng đúng chỗ, bố cục không nhảy).
    expect(screen.getByRole('button', { name: /bắt đầu trò chuyện/i })).toBeDisabled()
    expect(nutApDung()).toBeEnabled()
  })
})

describe('Thử agent — đánh giá phiên (POST /agent/feedback như một app ngoài)', () => {
  const sao = (n: number) => screen.getByRole('radio', { name: `${n} sao` })
  const oNhanXet = () => screen.getByLabelText(/nhận xét/i)
  const nutGuiDanhGia = () => screen.getByRole('button', { name: /gửi đánh giá/i })

  /** Bắt mọi lần gọi `POST /api/v1/agent/feedback` để assert body + header. */
  function batFeedback(status = 204): Array<{ body: unknown; auth: string | null }> {
    const goi: Array<{ body: unknown; auth: string | null }> = []
    server.use(
      http.post('/api/v1/agent/feedback', async ({ request }) => {
        goi.push({ body: await request.json(), auth: request.headers.get('Authorization') })
        if (status === 204) return new HttpResponse(null, { status: 204 })
        return HttpResponse.json(
          { error: { code: 'INVALID_AGENT_KEY', message: 'Khoá đấu nối không hợp lệ' } },
          { status },
        )
      }),
    )
    return goi
  }

  /** Nút nhỏ dưới bong bóng agent cuối — mở khung đánh giá (kiểu Claude). */
  const nutMoDanhGia = () => screen.getByRole('button', { name: /đánh giá cuộc trò chuyện/i })

  /** Một lượt hỏi-đáp trọn vẹn (có `done`). `mo: false` để kiểm trạng thái
   *  TRƯỚC khi bấm nút — khung đánh giá không tự mở. */
  async function motLuotXong({ mo = true }: { mo?: boolean } = {}): Promise<FakeWebSocket> {
    const ws = await ketNoiThanhCong()
    await userEvent.type(oNhap(), 'Còn căn 2PN không?')
    await userEvent.click(nutGui())
    act(() => {
      ws.nhan({ type: 'token', text: 'Dạ còn 2 căn.' })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })
    await screen.findByText('Dạ còn 2 căn.')
    if (mo) await userEvent.click(nutMoDanhGia())
    return ws
  }

  it('chưa có lượt trả lời nào ⇒ chưa có cả nút lẫn khung đánh giá', async () => {
    datApi()
    boot()
    await ketNoiThanhCong()

    expect(
      screen.queryByRole('button', { name: /đánh giá cuộc trò chuyện/i }),
    ).not.toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: '5 sao' })).not.toBeInTheDocument()
  })

  it('agent trả lời xong ⇒ hiện NÚT dưới bong bóng, khung đánh giá KHÔNG tự mở', async () => {
    datApi()
    boot()
    await motLuotXong({ mo: false })

    expect(nutMoDanhGia()).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: '5 sao' })).not.toBeInTheDocument()
    expect(nutMoDanhGia()).toHaveAttribute('aria-expanded', 'false')
  })

  it('bấm nút ⇒ khung đánh giá mở ra ngay dưới bong bóng cuối', async () => {
    datApi()
    boot()
    const ws = await motLuotXong({ mo: false })

    await userEvent.click(nutMoDanhGia())

    expect(screen.getByRole('radio', { name: '5 sao' })).toBeInTheDocument()
    expect(nutMoDanhGia()).toHaveAttribute('aria-expanded', 'true')
    // Khung nằm TRONG khung hội thoại, sau bong bóng cuối — không phải một dải
    // treo trên ô nhập như bản trước.
    const bongBongCuoi = screen.getByText('Dạ còn 2 căn.')
    expect(bongBongCuoi.closest('div')?.parentElement).toContainElement(
      screen.getByRole('radiogroup'),
    )
    expect(
      ws.sent.filter((s) => (JSON.parse(s) as { type: string }).type === 'user_text'),
    ).toHaveLength(1)
  })

  it('nút copy đứng cạnh nút đánh giá, copy ĐÚNG nội dung bong bóng đó', async () => {
    // `userEvent.setup()` tự cài `navigator.clipboard` giả (jsdom không có) —
    // phải setup TRƯỚC rồi mới spy, xem ghi chú dài ở `khoa-dau-noi.test.tsx`.
    const u = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    datApi()
    boot()
    await motLuotXong({ mo: false })

    await u.click(screen.getByRole('button', { name: /^copy câu trả lời$/i }))

    expect(writeText).toHaveBeenCalledExactlyOnceWith('Dạ còn 2 căn.')
    // Biên nhận cho cú bấm — không có nó thì bấm xong không biết đã copy chưa.
    expect(await screen.findByRole('button', { name: /đã copy/i })).toBeInTheDocument()
  })

  it('hai nút có hiệu ứng hover: nổi nền + đậm nét icon', async () => {
    // jsdom không vẽ nên không "rê chuột" kiểm được — chỉ khoá được ĐÚNG bộ
    // lớp hover, cùng lối `tests/o-chon.test.ts` và bài `grid-cols-2` ở trên.
    // Đây là hiệu ứng người dùng yêu cầu tường minh (2026-08-13), không phải
    // trang trí ai đó thêm vào, nên mất nó phải làm đỏ một bài.
    datApi()
    boot()
    await motLuotXong({ mo: false })

    for (const nut of [
      screen.getByRole('button', { name: /^copy câu trả lời$/i }),
      nutMoDanhGia(),
    ]) {
      expect(nut).toHaveClass('hover:bg-fill-strong')
      expect(nut).toHaveClass('hover:text-fg')
      expect(nut).toHaveClass('transition-colors')
    }
  })

  it('copy lấy bong bóng CUỐI, không phải bong bóng đầu tiên của phiên', async () => {
    const u = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    datApi()
    boot()
    const ws = await motLuotXong({ mo: false })

    await userEvent.type(oNhap(), 'Còn căn 3PN thì sao?')
    await userEvent.click(nutGui())
    act(() => {
      ws.nhan({ type: 'token', text: 'Dạ 3PN còn 1 căn.' })
      ws.nhan({ type: 'done', turn_id: 't2' })
    })
    await screen.findByText('Dạ 3PN còn 1 căn.')

    await u.click(screen.getByRole('button', { name: /^copy câu trả lời$/i }))

    expect(writeText).toHaveBeenCalledExactlyOnceWith('Dạ 3PN còn 1 căn.')
  })

  it('nhiều lượt ⇒ nút CHỈ nằm dưới bong bóng agent cuối cùng, không phải mọi bong bóng', async () => {
    datApi()
    boot()
    const ws = await motLuotXong({ mo: false })

    await userEvent.type(oNhap(), 'Còn căn 3PN thì sao?')
    await userEvent.click(nutGui())
    act(() => {
      ws.nhan({ type: 'token', text: 'Dạ 3PN còn 1 căn.' })
      ws.nhan({ type: 'done', turn_id: 't2' })
    })
    await screen.findByText('Dạ 3PN còn 1 căn.')

    expect(screen.getAllByRole('button', { name: /đánh giá cuộc trò chuyện/i })).toHaveLength(1)
  })

  it('chấm sao + nhận xét ⇒ POST đúng session_id của phiên, kèm Bearer khoá đang dùng', async () => {
    const goi = batFeedback()
    datApi()
    boot()
    await motLuotXong()

    await userEvent.click(sao(4))
    await userEvent.type(oNhanXet(), 'Trả lời nhanh')
    await userEvent.click(nutGuiDanhGia())

    await waitFor(() => expect(goi).toHaveLength(1))
    expect(goi[0]?.body).toEqual({ session_id: 'abc123', rating: 4, comment: 'Trả lời nhanh' })
    expect(goi[0]?.auth).toBe('Bearer ody_ag_rawkey123')
    expect(await screen.findByText(/đã gửi đánh giá/i)).toBeInTheDocument()
  })

  it('gửi xong ⇒ khung đóng lại và KHÔNG mời chấm lần nữa', async () => {
    batFeedback()
    datApi()
    boot()
    await motLuotXong()

    await userEvent.click(sao(5))
    await userEvent.click(nutGuiDanhGia())

    expect(await screen.findByText(/đã gửi đánh giá/i)).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: '5 sao' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /đánh giá cuộc trò chuyện/i }),
    ).not.toBeInTheDocument()
  })

  it('nhận xét là TUỲ CHỌN — chỉ chấm sao vẫn gửi được, comment rỗng', async () => {
    const goi = batFeedback()
    datApi()
    boot()
    await motLuotXong()

    await userEvent.click(sao(5))
    await userEvent.click(nutGuiDanhGia())

    await waitFor(() => expect(goi).toHaveLength(1))
    expect(goi[0]?.body).toEqual({ session_id: 'abc123', rating: 5, comment: '' })
  })

  it('chưa chấm sao thì nút Gửi còn khoá — rating là bắt buộc (API 1-5)', async () => {
    datApi()
    boot()
    await motLuotXong()

    expect(nutGuiDanhGia()).toBeDisabled()
  })

  it('gửi hỏng (401) ⇒ hiện lỗi và vẫn cho gửi lại, KHÔNG nuốt im lặng', async () => {
    batFeedback(401)
    datApi()
    boot()
    await motLuotXong()

    await userEvent.click(sao(2))
    await userEvent.click(nutGuiDanhGia())

    expect(await screen.findByText(/khoá đấu nối không hợp lệ/i)).toBeInTheDocument()
    expect(nutGuiDanhGia()).toBeEnabled()
  })

  it('Bỏ qua ⇒ khung đóng lại nhưng NÚT còn đó để mở lại, KHÔNG gọi API', async () => {
    const goi = batFeedback()
    datApi()
    boot()
    await motLuotXong()

    await userEvent.click(screen.getByRole('button', { name: /bỏ qua/i }))

    expect(screen.queryByRole('radio', { name: '5 sao' })).not.toBeInTheDocument()
    expect(nutMoDanhGia()).toBeInTheDocument()
    expect(goi).toHaveLength(0)

    await userEvent.click(nutMoDanhGia())
    expect(screen.getByRole('radio', { name: '5 sao' })).toBeInTheDocument()
  })
})

describe('Thử agent — đánh giá sau cuộc gọi Voice', () => {
  async function goiXong(opts: { session?: string; cupMay?: boolean } = {}): Promise<void> {
    datGiaMic()
    await waitFor(() => expect(tabVoice()).toBeInTheDocument())
    await userEvent.click(tabVoice())
    await waitFor(() => expect(oHoTen()).toBeInTheDocument())
    await userEvent.clear(oHoTen())
    await userEvent.clear(oDienThoai())
    await userEvent.type(oHoTen(), 'Nguyễn Văn Duy')
    await userEvent.type(oDienThoai(), '0912010999')
    await userEvent.selectOptions(oGioiTinh(), 'nam')
    await waitFor(() => expect(oRole()).toBeEnabled())
    await userEvent.selectOptions(oRole(), 'sale')
    await userEvent.selectOptions(oApiKey(), 'ody_ag_rawkey123')
    await userEvent.click(nutApDung())
    await userEvent.click(await screen.findByRole('button', { name: /bắt đầu trò chuyện/i }))
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.moThanhCong())
    if (opts.session) act(() => ws.nhan({ type: 'session_id', session_id: opts.session }))
    if (opts.cupMay !== false)
      await userEvent.click(screen.getByRole('button', { name: /^kết thúc$/i }))
  }

  it('cúp máy ⇒ hiện thanh đánh giá, gửi đúng session_id gateway đã trả (= tên room)', async () => {
    const goi: Array<{ body: unknown; auth: string | null }> = []
    server.use(
      http.post('/api/v1/agent/feedback', async ({ request }) => {
        goi.push({ body: await request.json(), auth: request.headers.get('Authorization') })
        return new HttpResponse(null, { status: 204 })
      }),
    )
    datApi()
    boot()
    await goiXong({ session: 'anphu-portal-1-9-ab' })

    await userEvent.click(await screen.findByRole('radio', { name: '3 sao' }))
    await userEvent.type(screen.getByLabelText(/nhận xét/i), 'Nghe rõ, trả lời nhanh')
    await userEvent.click(screen.getByRole('button', { name: /gửi đánh giá/i }))

    await waitFor(() => expect(goi).toHaveLength(1))
    expect(goi[0]?.body).toEqual({
      session_id: 'anphu-portal-1-9-ab',
      rating: 3,
      comment: 'Nghe rõ, trả lời nhanh',
    })
    expect(goi[0]?.auth).toBe('Bearer ody_ag_rawkey123')
    expect(await screen.findByText(/cảm ơn bạn/i)).toBeInTheDocument()
  })

  it('đang trong cuộc gọi thì CHƯA hỏi — người dùng đang nói, không đọc màn hình', async () => {
    datApi()
    boot()
    await goiXong({ session: 's-1', cupMay: false })

    expect(screen.queryByRole('radio', { name: '5 sao' })).not.toBeInTheDocument()
  })

  it('gateway cũ chưa trả session_id ⇒ vẫn hiện thanh nhưng khoá nút và nói rõ vì sao', async () => {
    datApi()
    boot()
    await goiXong({ cupMay: false })
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.nhan({ type: 'agent_speaking', text: 'Dạ em chào anh.', turn_id: 'greeting' }))
    await userEvent.click(screen.getByRole('button', { name: /^kết thúc$/i }))

    expect(await screen.findByRole('radio', { name: '5 sao' })).toBeInTheDocument()
    expect(screen.getByText(/chưa nhận được session_id/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /gửi đánh giá/i })).toBeDisabled()
  })

  it('cuộc gọi CHƯA từng thông (gateway đóng ngay, không event nào) ⇒ báo lỗi, KHÔNG hỏi đánh giá', async () => {
    datApi()
    boot()
    await goiXong({ cupMay: false })
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.dong(4001, 'bad_credential'))

    expect(await screen.findByText(/api key không hợp lệ/i)).toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: '5 sao' })).not.toBeInTheDocument()
  })

  it('gọi lần hai ⇒ thanh đánh giá về trạng thái mới, mang session_id của cuộc gọi MỚI', async () => {
    const goi: unknown[] = []
    server.use(
      http.post('/api/v1/agent/feedback', async ({ request }) => {
        goi.push(await request.json())
        return new HttpResponse(null, { status: 204 })
      }),
    )
    datApi()
    boot()
    await goiXong({ session: 'phien-1' })
    await userEvent.click(await screen.findByRole('radio', { name: '5 sao' }))
    await userEvent.click(screen.getByRole('button', { name: /gửi đánh giá/i }))
    await waitFor(() => expect(goi).toHaveLength(1))

    // Cuộc gọi thứ hai trong cùng lần mở màn — WS mới, session_id mới.
    await userEvent.click(screen.getByRole('button', { name: /bắt đầu trò chuyện/i }))
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2))
    const ws2 = FakeWebSocket.instances[1] as FakeWebSocket
    act(() => ws2.moThanhCong())
    act(() => ws2.nhan({ type: 'session_id', session_id: 'phien-2' }))
    await userEvent.click(screen.getByRole('button', { name: /^kết thúc$/i }))

    await userEvent.click(await screen.findByRole('radio', { name: '2 sao' }))
    await userEvent.click(screen.getByRole('button', { name: /gửi đánh giá/i }))

    await waitFor(() => expect(goi).toHaveLength(2))
    expect(goi[1]).toEqual({ session_id: 'phien-2', rating: 2, comment: '' })
  })
})

describe('Thử agent — mã đóng WS theo đúng bảng của gateway', () => {
  it('4001/bad_credential → API key không hợp lệ', async () => {
    datApi()
    boot()
    await thietLap()
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.dong(4001, 'bad_credential'))

    expect(await screen.findByText(/api key không hợp lệ/i)).toBeInTheDocument()
  })

  it('4001/auth_api_unavailable → câu báo KHÁC bad_credential (đừng gộp)', async () => {
    datApi()
    boot()
    await thietLap()
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.dong(4001, 'auth_api_unavailable'))

    expect(await screen.findByText(/hệ thống xác thực đang bận/i)).toBeInTheDocument()
    expect(screen.queryByText(/api key không hợp lệ/i)).not.toBeInTheDocument()
  })

  it('4004 unknown_route → sai WS URL', async () => {
    datApi()
    boot()
    await thietLap()
    const ws = FakeWebSocket.instances[0] as FakeWebSocket
    act(() => ws.dong(4004, 'unknown_route'))

    expect(await screen.findByText(/sai ws url/i)).toBeInTheDocument()
  })

  it('4029 chat_at_capacity → báo quá tải', async () => {
    datApi()
    boot()
    const ws = await ketNoiThanhCong()
    act(() => ws.dong(4029, 'chat_at_capacity'))

    expect(await screen.findByText(/quá tải/i)).toBeInTheDocument()
  })
})

describe('chuanHoaMedia — video hai biến thể (YouTube video_id | url)', () => {
  it('giữ embed_url/thumb/title của biến thể url; bỏ video thiếu cả video_id lẫn url', () => {
    const ra = chuanHoaMedia({
      items: [
        { kind: 'video', video_id: 'dQw4w9WgXcQ', title: 'YT' },
        {
          kind: 'video',
          url: 'https://drive.google.com/file/d/1SqV/view',
          embed_url: 'https://drive.google.com/file/d/1SqV/preview',
          thumb: 'https://drive.google.com/thumbnail?id=1SqV&sz=w480',
          title: 'Drive',
          la: 1,
        },
        { kind: 'video', title: 'hỏng' },
        { kind: 'video', url: 'https://vimeo.com/1', embed_url: 7 },
      ],
    })
    expect(ra.items).toEqual([
      { kind: 'video', video_id: 'dQw4w9WgXcQ', title: 'YT' },
      {
        kind: 'video',
        url: 'https://drive.google.com/file/d/1SqV/view',
        embed_url: 'https://drive.google.com/file/d/1SqV/preview',
        thumb: 'https://drive.google.com/thumbnail?id=1SqV&sz=w480',
        title: 'Drive',
      },
      { kind: 'video', url: 'https://vimeo.com/1' },
    ])
  })
})

describe('chuanHoaMedia — giữ số ảnh (`index`)', () => {
  it('giữ `index` của item ảnh', () => {
    // chuanHoaMedia dựng lại từng item bằng danh sách trường CỨNG và bỏ mọi
    // trường lạ; không khai `index` ở đó thì số bị nuốt im lặng — không lỗi,
    // không cảnh báo. Bài này phải ĐỎ nếu `index` chưa được khai.
    const ra = chuanHoaMedia({
      items: [{ kind: 'image', url: 'https://x/a.png', label: 'Màn đăng nhập', index: 3 }],
    })
    expect(ra.items[0]).toMatchObject({ kind: 'image', index: 3 })
  })

  it('ảnh không có `index` vẫn nhận được, không có số nào bị suy đoán', () => {
    const ra = chuanHoaMedia({ items: [{ kind: 'image', url: 'https://x/a.png' }] })
    expect(ra.items).toHaveLength(1)
    expect((ra.items[0] as { index?: number }).index).toBeUndefined()
  })

  it('bỏ `index` không phải số hoặc ≤ 0, không đoán', () => {
    const ra = chuanHoaMedia({
      items: [
        { kind: 'image', url: 'https://x/a.png', index: '3' },
        { kind: 'image', url: 'https://x/b.png', index: 0 },
        { kind: 'image', url: 'https://x/c.png', index: -1 },
      ],
    })
    for (const it of ra.items) {
      expect((it as { index?: number }).index).toBeUndefined()
    }
  })
})
