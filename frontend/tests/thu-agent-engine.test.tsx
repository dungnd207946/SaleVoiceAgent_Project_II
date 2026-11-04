/**
 * Màn «Thử agent» tab Chat — chọn engine (legacy / v2) + provider/model của v2 cho RIÊNG phiên thử, và khối
 * «Luồng xử lý» (trace) dưới mỗi câu trả lời. Agent nhận tin `{"type":"engine",…}` sau `session_id` và trả
 * `engine_ok`; trace tới sau `done` (chỉ khi worker bật CHAT_SEND_TRACE — môi trường thử).
 */
import { act, StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'
import { boGiaLap, giaLapManHinh } from './man-hinh'

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
  moThanhCong(): void {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }
  nhan(obj: unknown): void {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
  tin(type: string): unknown[] {
    return this.sent.map((s) => JSON.parse(s) as { type?: string }).filter((m) => m.type === type)
  }
}

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  localStorage.clear()
  server.use(
    http.get('/api/v1/agent/keys', () =>
      HttpResponse.json({
        endpoint_chat_url: 'wss://anphu.test/v1/chat',
        endpoint_voice_url: 'wss://anphu.test/v1/voice',
        keys: [
          {
            id: 1,
            api_key: 'ody_ag_rawkey123',
            key_prefix: 'ody_ag_aaaa',
            label: 'Pod chat',
            created_at: '2026-08-01T09:00:00Z',
            last_used_at: null,
            status: 'active',
            revoked_at: null,
          },
        ],
      }),
    ),
    http.get('/api/v1/config', () =>
      HttpResponse.json({
        vaiTro: [
          {
            key: 'customer',
            ten: 'Khách hàng',
            icon: null,
            macDinh: true,
            cauHinh: {},
            laMacDinh: false,
          },
        ],
        version: 1,
        soRoleToiDa: 10,
      }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

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

const oEngine = () => screen.getByLabelText('Engine')
const oModel = () => screen.queryByLabelText('Model')

async function dienForm(): Promise<void> {
  await waitFor(() => expect(screen.getByLabelText('Họ tên')).toBeInTheDocument())
  await userEvent.clear(screen.getByLabelText('Họ tên'))
  await userEvent.clear(screen.getByLabelText('Số điện thoại'))
  await userEvent.type(screen.getByLabelText('Họ tên'), 'Nguyễn Văn Duy')
  await userEvent.type(screen.getByLabelText('Số điện thoại'), '0912010999')
  await userEvent.selectOptions(screen.getByLabelText('Giới tính'), 'nam')
  await waitFor(() => expect(screen.getByLabelText('Role')).toBeEnabled())
  await userEvent.selectOptions(screen.getByLabelText('Role'), 'customer')
  await userEvent.selectOptions(screen.getByLabelText('API Key'), 'ody_ag_rawkey123')
}

/** Áp dụng + mở WS + `session_id`. `engineOk` (mặc định bật): agent nhận tin engine thì trả `engine_ok` như thật. */
async function apDungVaMo({
  engineOk = true,
}: { engineOk?: boolean } = {}): Promise<FakeWebSocket> {
  await userEvent.click(screen.getByRole('button', { name: /^áp dụng$/i }))
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
  const ws = FakeWebSocket.instances[0] as FakeWebSocket
  act(() => ws.moThanhCong())
  act(() => ws.nhan({ type: 'session_id', session_id: 'abc123' }))
  const tin = ws.tin('engine')[0] as
    { engine: string; provider?: string; model?: string } | undefined
  if (engineOk && tin)
    act(() =>
      ws.nhan({
        type: 'engine_ok',
        engine: tin.engine,
        provider: tin.provider ?? '',
        model: tin.model ?? '',
      }),
    )
  return ws
}

describe('Thử agent — chọn engine / model', () => {
  it('mặc định V2 + Qwen3.6 35B-A3B DashScope ⇒ gửi tin engine đó sau session_id', async () => {
    boot()
    await dienForm()
    expect(oEngine()).toHaveValue('v2')
    expect(oModel()).toHaveValue('dashscope/qwen3.6-35b-a3b')
    const ws = await apDungVaMo()
    expect(ws.tin('engine')).toEqual([
      { type: 'engine', engine: 'v2', provider: 'dashscope', model: 'qwen3.6-35b-a3b' },
    ])
    await screen.findByText(/^Sẵn sàng$/)
    expect(screen.getByText('v2 · dashscope/qwen3.6-35b-a3b')).toBeInTheDocument()
  })

  it('chọn «theo server»: không gửi tin engine, sẵn sàng ngay; ô Model ẩn', async () => {
    boot()
    await dienForm()
    await userEvent.selectOptions(oEngine(), '')
    expect(oModel()).toBeNull()
    const ws = await apDungVaMo()
    await screen.findByText(/^Sẵn sàng$/)
    expect(ws.tin('engine')).toHaveLength(0)
  })

  it('chọn Gemini ⇒ tin engine mang provider/model đó; chưa sẵn sàng tới khi engine_ok', async () => {
    boot()
    await dienForm()
    await userEvent.selectOptions(oModel() as HTMLElement, 'gemini/gemini-2.5-flash')
    const ws = await apDungVaMo({ engineOk: false })
    expect(ws.tin('engine')).toEqual([
      { type: 'engine', engine: 'v2', provider: 'gemini', model: 'gemini-2.5-flash' },
    ])
    expect(screen.queryByText(/^Sẵn sàng$/)).toBeNull()
    expect(screen.getByText(/đang đổi engine/i)).toBeInTheDocument()
    act(() =>
      ws.nhan({ type: 'engine_ok', engine: 'v2', provider: 'gemini', model: 'gemini-2.5-flash' }),
    )
    await screen.findByText(/^Sẵn sàng$/)
    expect(screen.getByText('v2 · gemini/gemini-2.5-flash')).toBeInTheDocument()
  })

  it('V2 với model «theo server» ⇒ tin engine KHÔNG mang provider/model', async () => {
    boot()
    await dienForm()
    await userEvent.selectOptions(oModel() as HTMLElement, '')
    const ws = await apDungVaMo()
    expect(ws.tin('engine')).toEqual([{ type: 'engine', engine: 'v2' }])
  })

  it('chọn Legacy ⇒ gửi {"type":"engine","engine":"legacy"}', async () => {
    boot()
    await dienForm()
    await userEvent.selectOptions(oEngine(), 'legacy')
    expect(oModel()).toBeNull()
    const ws = await apDungVaMo()
    expect(ws.tin('engine')).toEqual([{ type: 'engine', engine: 'legacy' }])
  })

  it('agent từ chối đổi engine (error) ⇒ báo lỗi, không kẹt ở «đang đổi engine»', async () => {
    boot()
    await dienForm()
    const ws = await apDungVaMo({ engineOk: false })
    act(() =>
      ws.nhan({ type: 'error', message: 'Đổi engine chỉ bật ở môi trường thử (CHAT_SEND_TRACE).' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(/CHAT_SEND_TRACE/)
    await screen.findByText(/^Sẵn sàng$/)
  })
})

describe('Thử agent — thẻ thiết lập thu gọn sau Áp dụng', () => {
  it('sẵn sàng ⇒ form thu thành một dòng (danh tính + engine), «Sửa thiết lập» mở lại, «Thu gọn» đóng', async () => {
    boot()
    await dienForm()
    await apDungVaMo()
    await screen.findByText(/^Sẵn sàng$/)
    expect(screen.queryByLabelText('Họ tên')).toBeNull()
    expect(
      screen.getByText(/Nguyễn Văn Duy · 0912010999 · Nam · Khách hàng · Pod chat/),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Sửa thiết lập' }))
    expect(screen.getByLabelText('Họ tên')).toHaveValue('Nguyễn Văn Duy')
    expect(screen.getByText(/^Sẵn sàng$/)).toBeInTheDocument() // phiên vẫn chạy
    await userEvent.click(screen.getByRole('button', { name: 'Thu gọn thiết lập' }))
    expect(screen.queryByLabelText('Họ tên')).toBeNull()
  })

  it('mở lại rồi đổi engine ⇒ phiên đóng, phải Áp dụng lại (như sửa một ô)', async () => {
    boot()
    await dienForm()
    const ws = await apDungVaMo()
    await screen.findByText(/^Sẵn sàng$/)
    await userEvent.click(screen.getByRole('button', { name: 'Sửa thiết lập' }))
    await userEvent.selectOptions(oEngine(), 'legacy')
    expect(ws.readyState).toBe(FakeWebSocket.CLOSED)
    expect(screen.getByRole('button', { name: /^áp dụng$/i })).toBeEnabled()
  })
})

describe('Thử agent — khối Luồng xử lý', () => {
  const TRACE = {
    user: 'Còn căn 2PN không?',
    nlu: { source: 'llm', acts: [{ i: 'tim_can' }], fixes: [], dropped: [], need: {}, buc: false },
    project: { status: 'resolved', code: 'VHOP2', ms: 3000 },
    parts: [{ topic: 'tìm căn', facts: ['3 căn 2PN'], actions: [], media: 0 }],
    factsheet: 'FACTS\n- 3 căn 2PN',
    composer: 'skipped',
    guard: [],
    g6_added: [],
    code_out: ['1) Căn A'],
    actions: [],
    timing: { l0_ms: 2, nlu_ms: 637, skills_ms: 2370, ttft_ms: 3010, total_ms: 3010 },
    reply: 'Dạ còn 3 căn.',
  }

  afterEach(() => boGiaLap())

  /** Gửi một câu, agent trả lời + trace của lượt đó. */
  async function motLuot(ws: FakeWebSocket, hoi: string, dap: string, acts: string): Promise<void> {
    await userEvent.type(screen.getByPlaceholderText(/thử/i), hoi)
    await userEvent.click(screen.getByRole('button', { name: /^gửi$/i }))
    act(() => {
      ws.nhan({ type: 'token', text: dap })
      ws.nhan({ type: 'done', turn_id: hoi })
      ws.nhan({
        type: 'trace',
        turn_id: hoi,
        engine: 'v2',
        trace: { ...TRACE, nlu: { ...TRACE.nlu, acts: [{ i: acts }] } },
      })
    })
    await screen.findByText(dap)
  }

  async function sanSang(): Promise<FakeWebSocket> {
    boot()
    await dienForm()
    const ws = await apDungVaMo()
    await screen.findByText(/^Sẵn sàng$/)
    return ws
  }

  it('màn rộng: panel ĐÓNG mặc định; bấm dòng tóm tắt mới mở, bấm lại / nút × thì đóng, focus về dòng đó', async () => {
    const ws = await sanSang()
    await motLuot(ws, 'Còn căn 2PN không?', 'Dạ còn 3 căn.', 'tim_can')

    const tom1 = await screen.findByRole('button', { name: /luồng xử lý · lượt 1/i })
    expect(tom1).toHaveAttribute('aria-expanded', 'false')
    expect(within(tom1).getByText('tim_can')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Luồng xử lý' })).toBeNull()

    await userEvent.click(tom1)
    const panel = screen.getByRole('region', { name: 'Luồng xử lý' })
    expect(tom1).toHaveAttribute('aria-expanded', 'true')
    for (const buoc of [
      /L0 · Tiền xử lý/,
      /L2 · NLU/,
      /Chọn dự án/,
      /Fact sheet/,
      /L6 · Composer/,
      /L7 · Guard/,
      /Phát ra/,
    ])
      expect(within(panel).getByRole('button', { name: buoc })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: /copy json/i })).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: /Fact sheet/ }))
    expect(within(panel).getByText(/- 3 căn 2PN/)).toBeInTheDocument()

    // lượt mới KHÔNG tự đổi panel; bấm lượt 2 thì panel sang lượt 2
    await motLuot(ws, 'Giá bao nhiêu?', 'Dạ từ 2 tỷ.', 'hoi_gia')
    expect(within(panel).queryByText('hoi_gia')).toBeNull()
    const tom2 = screen.getByRole('button', { name: /luồng xử lý · lượt 2/i })
    await userEvent.click(tom2)
    expect(
      within(screen.getByRole('region', { name: 'Luồng xử lý' })).getByText('hoi_gia'),
    ).toBeInTheDocument()
    expect(tom1).toHaveAttribute('aria-expanded', 'false')

    // bấm lại dòng đang mở ⇒ đóng
    await userEvent.click(tom2)
    expect(screen.queryByRole('region', { name: 'Luồng xử lý' })).toBeNull()

    // nút × đóng và trả focus về dòng tóm tắt
    await userEvent.click(tom1)
    await userEvent.click(screen.getByRole('button', { name: 'Đóng luồng xử lý' }))
    expect(screen.queryByRole('region', { name: 'Luồng xử lý' })).toBeNull()
    expect(tom1).toHaveFocus()
  })

  it('màn hẹp: không có panel, chi tiết mở TẠI CHỖ dưới câu trả lời', async () => {
    giaLapManHinh(900)
    const ws = await sanSang()
    await motLuot(ws, 'Còn căn 2PN không?', 'Dạ còn 3 căn.', 'tim_can')

    const nut = await screen.findByRole('button', { name: /luồng xử lý · lượt 1/i })
    expect(nut).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: /L2 · NLU/ })).toBeNull()
    await userEvent.click(nut)
    expect(nut).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /L2 · NLU/ })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Luồng xử lý' })).toBeNull()
  })

  it('không có trace (engine legacy) ⇒ không có dòng luồng xử lý, không có panel', async () => {
    const ws = await sanSang()
    await userEvent.type(screen.getByPlaceholderText(/thử/i), 'chào')
    await userEvent.click(screen.getByRole('button', { name: /^gửi$/i }))
    act(() => {
      ws.nhan({ type: 'token', text: 'Dạ chào anh.' })
      ws.nhan({ type: 'done', turn_id: 't1' })
    })
    await screen.findByText('Dạ chào anh.')
    expect(screen.queryByRole('button', { name: /luồng xử lý/i })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Luồng xử lý' })).toBeNull()
  })
})
