/**
 * Slide-over chi tiết phiên `/billing?phien=` — Task 6.
 *
 * ⚠️ ĐƯỜNG DẪN ĐỔI 2026-08-24: màn này TRƯỚC ở `/usage`, chuyển nguyên vẹn
 * sang `/billing` (người dùng chốt). `/usage` nay là màn khác nên boot
 * nhầm vào đó thì cả 8 bài treo 5s rồi đỏ ở `waitFor`, KHÔNG chỉ ra đường dẫn.
 *
 * Boot qua ROUTER THẬT (`routeTree.gen.ts`), cùng khuôn `tests/billing-usage.test.tsx`
 * — `phien` sống ở search param, và `validateSearch` của `routes/_app/billing.tsx`
 * là chỗ dễ vỡ nhất của thiết kế này.
 *
 * Fixture RIÊNG của test này (`server.use()`), không dựa vào fake mặc định ở
 * `features/billing/msw.ts` — cùng lý do `billing-usage.test.tsx` đã ghi: hai
 * nguồn cùng lúc là chỗ một bên đổi số mà không ai thấy bài test kia đỏ theo.
 *
 * `SESSION_ID` CỐ Ý ≤ 12 ký tự — cột Phiên (`HangPhien` ở `BangLuotDung.tsx`)
 * cắt `session_id` còn 12 ký tự để hiện, nên chuỗi ngắn hơn ngưỡng đó hiện
 * NGUYÊN VĂN và test bấm/đọc được bằng chính `session_id`, không phải bản cắt.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { LangProvider } from '@/i18n'
import { routeTree } from '@/routeTree.gen'
import type {
  ChiTietPhien,
  DanhSachPhien,
  EventUsage,
  PhienUsage,
  TongQuan,
} from '@/features/billing/kieu'
import { server } from '../vitest.setup'

function boot(duong: string) {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duong] }),
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

const SESSION_ID = 'sess-detail1'

const TONG_QUAN_GIA: TongQuan = {
  input_tokens: 50_000,
  output_tokens: 15_000,
  cache_read_tokens: 5_000,
  voice_sec: 176.85,
  so_phien: 5,
  so_key: 2,
  chi_phi: '5000.0000000000',
  currency: 'VND',
  canh_bao: { thieu_gia: 0, nhan_chua_phan_loai: 0, event_khong_so_do: 0, llm_khong_chinh_xac: 0 },
}

const PHIEN_GIA: PhienUsage = {
  session_id: SESSION_ID,
  agent_key_id: 9,
  key_label: 'Web widget test',
  customer_name: 'Khách demo',
  phone: '0900000000',
  channel: 'voice',
  bat_dau: '2026-08-18T08:00:00+07:00',
  so_turn: 2,
  input_tokens: 900,
  output_tokens: 300,
  voice_sec: 176.85,
  chi_phi: '1550.0000000000',
  // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (1000+300+150+20+60+15+5).
  chi_phi_llm: '1000.0000000000',
  chi_phi_tts: '300.0000000000',
  chi_phi_stt: '150.0000000000',
  chi_phi_embed: '20.0000000000',
  chi_phi_call: '60.0000000000',
  chi_phi_vad: '15.0000000000',
  chi_phi_speaker_verify: '5.0000000000',
  exact: true,
}

const DANH_SACH_PHIEN_GIA: DanhSachPhien = { items: [PHIEN_GIA], total: 1 }

// Đúng ví dụ hợp đồng BE (§0.4 task-6-brief): event `tts` có `units:7` (số
// clause đã synth) nhưng cơ sở TÍNH TIỀN là `text_units:1115` (ký tự) — bài
// test §2 dưới đây phải đọc ra "1.115 ký tự", không phải "7". `chi_phi:'0'`
// ở CHÍNH event này để cùng lúc canh luật "chi_phi==='0' ⇒ Không tính tiền"
// (§4) mà không cần thêm event riêng. `provider`/`model` rỗng ở cả tts lẫn
// call (DEFAULT '' của component audio, không NULL) — canh bài test §3.
const EVENTS_GIA: EventUsage[] = [
  {
    event_id: 1,
    seq: 1,
    turn_idx: 0,
    component: 'stt',
    purpose: 'transcribe',
    provider: 'soniox',
    model: 'stt-v2',
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    audio_sec: 5.2,
    units: 1,
    text_units: 120,
    exact: true,
    chi_phi: '40.0000000000',
    occurred_at: '2026-08-18T08:00:05+07:00',
  },
  {
    event_id: 2,
    seq: 2,
    turn_idx: 0,
    component: 'llm',
    purpose: 'respond',
    provider: 'anthropic',
    model: 'claude-sonnet',
    input_tokens: 900,
    output_tokens: 300,
    cache_read_tokens: 0,
    audio_sec: 0,
    units: 1,
    text_units: 0,
    exact: true,
    chi_phi: '900.0000000000',
    occurred_at: '2026-08-18T08:00:07+07:00',
  },
  {
    event_id: 3,
    seq: 3,
    turn_idx: 1,
    component: 'tts',
    purpose: 'speak',
    provider: '',
    model: '',
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    audio_sec: 8.2,
    units: 7,
    text_units: 1115,
    exact: true,
    chi_phi: '0',
    occurred_at: '2026-08-18T08:00:09+07:00',
  },
  {
    event_id: 4,
    seq: 4,
    turn_idx: 1,
    component: 'call',
    purpose: 'session',
    provider: '',
    model: '',
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    audio_sec: 176.85,
    units: 1,
    text_units: 0,
    exact: true,
    chi_phi: '610.0000000000',
    occurred_at: '2026-08-18T08:03:00+07:00',
  },
]

const CHI_TIET_GIA: ChiTietPhien = {
  phien: PHIEN_GIA,
  events: EVENTS_GIA,
  ghi_chu_turn:
    'turn_idx của dòng audio là xấp xỉ (TTS của lượt N nằm ở lô N+1). Tổng theo phiên luôn đúng; đừng dùng số theo từng lượt để đối chiếu tiền.',
}

function datApi(): void {
  server.use(
    http.get('/api/v1/billing/summary', () => HttpResponse.json(TONG_QUAN_GIA)),
    http.get('/api/v1/billing/sessions', () => HttpResponse.json(DANH_SACH_PHIEN_GIA)),
    http.get('/api/v1/billing/sessions/:sessionId', ({ params }) => {
      if (params['sessionId'] !== SESSION_ID) {
        return HttpResponse.json(
          { error: { code: 'PHIEN_KHONG_TON_TAI', message: 'Không tìm thấy' } },
          { status: 404 },
        )
      }
      return HttpResponse.json(CHI_TIET_GIA)
    }),
  )
}

describe('Slide-over chi tiết phiên (/billing?phien=)', () => {
  it('ghi_chu_turn hiện NGUYÊN VĂN, luôn hiện, không tooltip, không collapse', async () => {
    datApi()
    boot(`/billing?phien=${SESSION_ID}`)

    const ghi = await screen.findByText(/xấp xỉ/)
    expect(ghi).toBeVisible()
    // Nguyên văn — không bị cắt/diễn giải lại.
    expect(ghi.textContent).toBe(CHI_TIET_GIA.ghi_chu_turn)
    // KHÔNG nằm trong bất kỳ phần tử nào mang `title` (tức không phải tooltip).
    expect(ghi.closest('[title]')).toBeNull()
    // KHÔNG có `<details>` bọc quanh nó (tức không gập được).
    expect(ghi.closest('details')).toBeNull()
  })

  it('event TTS hiện text_units làm cơ sở tính tiền, không phải units', async () => {
    datApi()
    boot(`/billing?phien=${SESSION_ID}`)

    await screen.findByText(/xấp xỉ/)
    // Fixture: tts units=7 text_units=1115 — phải đọc ra 1.115 ký tự.
    expect(screen.getByText(/1\.115 ký tự/)).toBeInTheDocument()
    expect(screen.queryByText(/^7 ký tự$/)).not.toBeInTheDocument()
  })

  it('provider/model rỗng hiện «—» — chứ không phải ô trắng', async () => {
    datApi()
    boot(`/billing?phien=${SESSION_ID}`)

    await screen.findByText(/xấp xỉ/)
    // Event tts VÀ call đều có provider='' model='' — ít nhất 4 ô «—».
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4)
  })

  it('chi_phi === "0" hiện chữ mờ + pill «Không tính tiền»', async () => {
    datApi()
    boot(`/billing?phien=${SESSION_ID}`)

    await screen.findByText(/xấp xỉ/)
    // Chỉ event tts (chi_phi:'0') mang pill này — không phải lỗi, không gạch bỏ.
    const pill = screen.getByText('Không tính tiền')
    expect(pill).toBeInTheDocument()
    expect(pill.className).toContain('text-badge-neutral-fg')
  })

  it('mở bằng bấm hàng Phiên, đóng bằng Escape — cả hai đi qua search param', async () => {
    datApi()
    const r = boot('/billing?gop=phien')

    const nutHang = await screen.findByText(SESSION_ID)
    await userEvent.click(nutHang)

    expect(r.state.location.search).toMatchObject({ phien: SESSION_ID })
    await screen.findByText(/xấp xỉ/)

    await userEvent.keyboard('{Escape}')

    expect(r.state.location.search.phien).toBeUndefined()
    // Focus trả về ĐÚNG hàng vừa mở nó (khuôn `oKichHoatRef` của `LightboxAnh`).
    expect(nutHang).toHaveFocus()
  })

  it('đóng bằng nút × xoá search param', async () => {
    datApi()
    const r = boot(`/billing?phien=${SESSION_ID}`)

    await screen.findByText(/xấp xỉ/)
    const dialog = screen.getByRole('dialog')
    // Backdrop cũng mang `aria-label="Đóng"` nhưng đứng NGOÀI `role="dialog"`
    // — `within(dialog)` chỉ khớp đúng nút × bên trong.
    await userEvent.click(within(dialog).getByRole('button', { name: 'Đóng' }))

    expect(r.state.location.search.phien).toBeUndefined()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('đóng bằng click lớp phủ xoá search param', async () => {
    datApi()
    const r = boot(`/billing?phien=${SESSION_ID}`)

    await screen.findByText(/xấp xỉ/)
    const nutDong = screen.getAllByRole('button', { name: 'Đóng' })
    // Lớp phủ được render TRƯỚC dialog trong DOM ⇒ phần tử đầu tiên.
    await userEvent.click(nutDong[0]!)

    expect(r.state.location.search.phien).toBeUndefined()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

/**
 * `nhomTheoLuot()`/`KhoiLuot` (finding Minor của Task 6) — key theo
 * `turnIdx ?? 'null'` ĐỤNG NHAU khi có ≥2 nhóm `turn_idx: null` KHÔNG liền kề
 * (vd: turn 1 → null → turn 2 → null, một event `vad`/`call` không gắn lượt
 * chen giữa các lượt có số — dữ liệu thật đến được ca này). React cảnh báo
 * key trùng và có thể tái dùng nhầm DOM lúc refetch; ở màn đối soát tiền đó
 * là hiện SAI HÀNG event. Đã sửa: key theo `n.events[0].event_id`.
 */
describe('nhomTheoLuot — nhóm turn_idx: null KHÔNG liền kề', () => {
  const SESSION_ID_NHOM = 'sess-nhom1'

  const PHIEN_NHOM: PhienUsage = {
    ...PHIEN_GIA,
    session_id: SESSION_ID_NHOM,
    so_turn: 2,
  }

  // Thứ tự turn_idx theo seq: 1 → null → 2 → null ⇒ BỐN nhóm, hai nhóm null
  // KHÔNG liền kề nhau.
  const EVENTS_NHOM: EventUsage[] = [
    {
      event_id: 101,
      seq: 1,
      turn_idx: 1,
      component: 'llm',
      purpose: 'respond',
      provider: 'anthropic',
      model: 'claude-sonnet',
      input_tokens: 100,
      output_tokens: 50,
      cache_read_tokens: 0,
      audio_sec: 0,
      units: 1,
      text_units: 0,
      exact: true,
      chi_phi: '10.0000000000',
      occurred_at: '2026-08-18T08:00:01+07:00',
    },
    {
      event_id: 102,
      seq: 2,
      turn_idx: null,
      component: 'vad',
      purpose: 'detect',
      provider: '',
      model: '',
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 3.1,
      units: 1,
      text_units: 0,
      exact: true,
      chi_phi: '0',
      occurred_at: '2026-08-18T08:00:02+07:00',
    },
    {
      event_id: 103,
      seq: 3,
      turn_idx: 2,
      component: 'llm',
      purpose: 'respond',
      provider: 'anthropic',
      model: 'claude-sonnet',
      input_tokens: 20,
      output_tokens: 10,
      cache_read_tokens: 0,
      audio_sec: 0,
      units: 1,
      text_units: 0,
      exact: true,
      chi_phi: '5.0000000000',
      occurred_at: '2026-08-18T08:00:03+07:00',
    },
    {
      event_id: 104,
      seq: 4,
      turn_idx: null,
      component: 'call',
      purpose: 'session',
      provider: '',
      model: '',
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 60,
      units: 1,
      text_units: 0,
      exact: true,
      chi_phi: '20.0000000000',
      occurred_at: '2026-08-18T08:03:00+07:00',
    },
  ]

  const CHI_TIET_NHOM: ChiTietPhien = {
    phien: PHIEN_NHOM,
    events: EVENTS_NHOM,
    ghi_chu_turn: CHI_TIET_GIA.ghi_chu_turn,
  }

  function datApiNhom(): void {
    server.use(
      http.get('/api/v1/billing/summary', () => HttpResponse.json(TONG_QUAN_GIA)),
      http.get('/api/v1/billing/sessions', () => HttpResponse.json(DANH_SACH_PHIEN_GIA)),
      http.get('/api/v1/billing/sessions/:sessionId', ({ params }) => {
        if (params['sessionId'] !== SESSION_ID_NHOM) {
          return HttpResponse.json(
            { error: { code: 'PHIEN_KHONG_TON_TAI', message: 'Không tìm thấy' } },
            { status: 404 },
          )
        }
        return HttpResponse.json(CHI_TIET_NHOM)
      }),
    )
  }

  it('bốn nhóm tách đúng, không cảnh báo key trùng, mỗi nhóm hiện đúng event của mình', async () => {
    const loi = vi.spyOn(console, 'error').mockImplementation(() => {})

    datApiNhom()
    boot(`/billing?phien=${SESSION_ID_NHOM}`)

    await screen.findByText(/xấp xỉ/)

    // Bốn nhóm: Lượt 1 · Chưa gán lượt · Lượt 2 · Chưa gán lượt.
    expect(screen.getByText('Lượt 1')).toBeInTheDocument()
    expect(screen.getByText('Lượt 2')).toBeInTheDocument()
    const nhomChuaGan = screen.getAllByText('Chưa gán lượt')
    expect(nhomChuaGan).toHaveLength(2)

    // Mỗi nhóm hiện ĐÚNG event của mình — nhóm null #1 mang seq 2 (vad), nhóm
    // null #2 mang seq 4 (call). Sai key (đụng nhau) là chỗ React có thể gộp
    // nhầm hai nhóm này lại hoặc tái dùng DOM sai lúc refetch.
    expect(within(nhomChuaGan[0]!.parentElement!).getByText('#2')).toBeInTheDocument()
    expect(within(nhomChuaGan[1]!.parentElement!).getByText('#4')).toBeInTheDocument()
    expect(within(screen.getByText('Lượt 1').parentElement!).getByText('#1')).toBeInTheDocument()
    expect(within(screen.getByText('Lượt 2').parentElement!).getByText('#3')).toBeInTheDocument()

    // Không cảnh báo key trùng của React (chuỗi thật: "Encountered two
    // children with the same key").
    const canhBaoKeyTrung = loi.mock.calls.some((call) =>
      call.some((arg) => typeof arg === 'string' && arg.includes('same key')),
    )
    expect(canhBaoKeyTrung).toBe(false)

    loi.mockRestore()
  })
})

/**
 * KÝ HIỆU MŨ TỪ BE — `"0E-10"`, không phải `"0"`.
 *
 * `EVENTS_GIA` viết tiền 0 là chuỗi `'0'`, và đó là dạng API THẬT chỉ trả khi
 * event KHÔNG có dòng `rated_usage` nào (`COALESCE(sum(...), 0)` rơi về hằng
 * `0`). Khi event CÓ dòng tiền mà tổng bằng 0 — bảng giá mặc định
 * (`0949_seed_bang_gia_mac_dinh`) khai `unit_price = 0` cho `vad.audio_sec`,
 * còn `rate_usage()` chỉ lọc `qty > 0` — thì `sum(amount)` là
 * `Decimal('0E-10')` và Pydantic serialize thành `"0E-10"`.
 *
 * Panel này là màn ĐỐI SOÁT, nên hai thứ phải cùng đúng: dựng được (trước bản
 * vá `tienDay()` ném `SyntaxError` và slide-over trắng), VÀ vẫn nhận ra đây là
 * dòng không tính tiền.
 */
describe('event mang tiền dạng mũ "0E-10"', () => {
  const VAD: EventUsage = {
    event_id: 90,
    seq: 9,
    turn_idx: null,
    component: 'vad',
    purpose: 'conversation',
    provider: '',
    model: '',
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    audio_sec: 529.1,
    units: 0,
    text_units: 0,
    exact: true,
    chi_phi: '0E-10',
    occurred_at: '2026-08-18T08:03:10+07:00',
  }

  function datApiMu(): void {
    server.use(
      http.get('/api/v1/billing/summary', () => HttpResponse.json(TONG_QUAN_GIA)),
      http.get('/api/v1/billing/sessions', () => HttpResponse.json(DANH_SACH_PHIEN_GIA)),
      http.get('/api/v1/billing/sessions/:sessionId', () =>
        HttpResponse.json({ ...CHI_TIET_GIA, events: [VAD] }),
      ),
    )
  }

  it('dựng được và mang pill «Không tính tiền»', async () => {
    datApiMu()
    boot(`/billing?phien=${SESSION_ID}`)

    await screen.findByText(/xấp xỉ/)
    expect(screen.getByText('vad')).toBeInTheDocument()
    expect(screen.getAllByText('Không tính tiền')).toHaveLength(1)
  })
})
