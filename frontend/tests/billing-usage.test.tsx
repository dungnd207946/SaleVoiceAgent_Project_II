/**
 * Màn `/billing` — khung: hàng chọn kỳ, dải cảnh báo, năm thẻ KPI (Task 4).
 *
 * ⚠️ ĐƯỜNG DẪN ĐỔI 2026-08-24: màn này TRƯỚC ở `/usage`, nội dung chuyển
 * nguyên vẹn sang `/billing` (người dùng chốt: «billing» = xem số tiền · chi
 * phí). Không một assertion nào về DỮ LIỆU hay UI phải đổi theo — chỉ đường
 * boot. `/usage` nay là màn khác, nên boot nhầm vào đó thì mọi bài đỏ với
 * lời than «không tìm thấy thẻ KPI», KHÔNG chỉ ra đường dẫn.
 *
 * Boot qua ROUTER THẬT (`routeTree.gen.ts`), không render `UsageScreen` trần:
 * `ky` sống ở search param và `validateSearch` là chỗ dễ vỡ nhất của thiết kế
 * này (bốn khoá phải LUÔN được trả đủ — xem `routes/_app/billing.tsx` và bẫy đã
 * sập thật ở `/projects`, `tests/realestate-nguon.test.tsx`). Cùng khuôn
 * `tests/re-fixture.tsx::boot()`.
 *
 * Fixture dùng RIÊNG của test này (`datApi()`), không dựa vào fake mặc định ở
 * `features/billing/msw.ts` — hai nguồn cùng lúc là chỗ một bên đổi số mà
 * không ai thấy bài test kia đỏ theo.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { LangProvider } from '@/i18n'
import { routeTree } from '@/routeTree.gen'
import { NHAN_CHUA_PHAN_LOAI } from '@/features/billing/components/BangLuotDung'
import { giay, tien, token } from '@/features/billing/dinh-dang'
import type {
  DanhSachKey,
  DanhSachPhien,
  DongOwner,
  PhanTich,
  TongQuan,
} from '@/features/billing/kieu'
import { BieuDoChiPhi } from '@/features/billing/components/BieuDoChiPhi'
import { bangMau } from '@/features/billing/component-hien'
import { server } from '../vitest.setup'

function boot(duong = '/billing') {
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

/** Fixture cơ sở — mọi field khớp kiểu `TongQuan` thật, số lấy tuỳ ý (KHÔNG
 *  trùng cố ý với `features/billing/msw.ts`, xem docstring đầu file). */
const CO_SO: TongQuan = {
  input_tokens: 125_000,
  output_tokens: 38_000,
  cache_read_tokens: 52_000,
  // 176.85s — thời lượng CUỘC GỌI (`component='call'`), không cộng chéo.
  voice_sec: 176.85,
  so_phien: 42,
  so_key: 3,
  chi_phi: '125000.5000000000',
  currency: 'VND',
  canh_bao: {
    thieu_gia: 2,
    nhan_chua_phan_loai: 5,
    event_khong_so_do: 1,
    llm_khong_chinh_xac: 3,
  },
}

function datApi(overrides: Partial<TongQuan> = {}) {
  const data: TongQuan = {
    ...CO_SO,
    ...overrides,
    canh_bao: { ...CO_SO.canh_bao, ...overrides.canh_bao },
  }
  server.use(http.get('/api/v1/billing/summary', () => HttpResponse.json(data)))
}

function datApi403() {
  server.use(
    http.get('/api/v1/billing/summary', () =>
      HttpResponse.json(
        { error: { code: 'FORBIDDEN', message: 'Bạn không có quyền xem chi phí workspace này' } },
        { status: 403 },
      ),
    ),
  )
}

function datApiLoi() {
  server.use(http.get('/api/v1/billing/summary', () => new HttpResponse(null, { status: 500 })))
}

/**
 * Fixture riêng của Task 5 (③ Explorer) — CÙNG lý do tách khỏi `features/
 * billing/msw.ts` ghi ở docstring đầu file: hai nguồn cùng lúc là chỗ một
 * bên đổi số mà không ai thấy bài test kia đỏ theo.
 *
 * Bốn hàng CỐ Ý: một hàng thường, một hàng ĐÃ THU HỒI, một hàng gần như không
 * phát sinh gì (`chi_phi` chỉ là một khoản phí nền nhỏ), và hàng
 * `agent_key_id: null` — GHIM CUỐI, không được thiếu (§9.1). `chi_phi_tong`
 * bằng ĐÚNG tổng bốn hàng (400491 + 9000 + 10 + 5000) — bài kiểm tra LỆCH tự
 * override riêng. Mỗi hàng còn mang bảy cột `chi_phi_<component>` CỘNG ĐÚNG
 * BẰNG `chi_phi` của chính hàng đó (2026-08-25, thay ba cột token in/out/
 * cache read cũ) — xem chú thích cạnh mỗi hàng.
 */
const CO_SO_KEY: DanhSachKey = {
  items: [
    {
      agent_key_id: 1,
      label: 'K-prod-web',
      key_prefix: 'ody_ag_ab12',
      nguoi_tao: 'u_quan',
      nguoi_tao_ten: 'Trần Minh Quân',
      da_thu_hoi: false,
      so_phien: 187,
      input_tokens: 2_810_000,
      output_tokens: 400_000,
      cache_read_tokens: 0,
      voice_sec: 0,
      so_event: 500,
      chi_phi: '400491.0000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (300000+60000+30000+8000+1800+611+80).
      chi_phi_llm: '300000.0000000000',
      chi_phi_tts: '60000.0000000000',
      chi_phi_stt: '30000.0000000000',
      chi_phi_embed: '80.0000000000',
      chi_phi_call: '8000.0000000000',
      chi_phi_vad: '1800.0000000000',
      chi_phi_speaker_verify: '611.0000000000',
    },
    {
      agent_key_id: 2,
      label: 'K-cu-thu-hoi',
      key_prefix: 'ody_ag_zz99',
      nguoi_tao: 'u_quan',
      nguoi_tao_ten: 'Trần Minh Quân',
      da_thu_hoi: true,
      so_phien: 10,
      input_tokens: 50_000,
      output_tokens: 12_000,
      cache_read_tokens: 8_000,
      voice_sec: 0,
      so_event: 60,
      chi_phi: '9000.0000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (7000+1200+500+200+70+20+10).
      chi_phi_llm: '7000.0000000000',
      chi_phi_tts: '1200.0000000000',
      chi_phi_stt: '500.0000000000',
      chi_phi_embed: '10.0000000000',
      chi_phi_call: '200.0000000000',
      chi_phi_vad: '70.0000000000',
      chi_phi_speaker_verify: '20.0000000000',
    },
    {
      // Khoá gần như không phát sinh gì — `chi_phi` là một khoản phí nền nhỏ,
      // dồn hết vào `llm` (đơn giản hoá của fixture).
      agent_key_id: 3,
      label: 'K-zero-token',
      key_prefix: 'ody_ag_0zer',
      nguoi_tao: 'u_quan',
      nguoi_tao_ten: 'Trần Minh Quân',
      da_thu_hoi: false,
      so_phien: 1,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      voice_sec: 0,
      so_event: 1,
      chi_phi: '10.0000000000',
      chi_phi_llm: '10.0000000000',
      chi_phi_tts: '0',
      chi_phi_stt: '0',
      chi_phi_embed: '0',
      chi_phi_call: '0',
      chi_phi_vad: '0',
      chi_phi_speaker_verify: '0',
    },
    {
      agent_key_id: null,
      label: '',
      key_prefix: '',
      nguoi_tao: '',
      nguoi_tao_ten: null,
      da_thu_hoi: false,
      so_phien: 7,
      input_tokens: 1_000,
      output_tokens: 500,
      cache_read_tokens: 0,
      voice_sec: 0,
      so_event: 10,
      chi_phi: '5000.0000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (3500+900+400+150+40+8+2).
      chi_phi_llm: '3500.0000000000',
      chi_phi_tts: '900.0000000000',
      chi_phi_stt: '400.0000000000',
      chi_phi_embed: '2.0000000000',
      chi_phi_call: '150.0000000000',
      chi_phi_vad: '40.0000000000',
      chi_phi_speaker_verify: '8.0000000000',
    },
  ],
  total: 4,
  chi_phi_tong: '414501.0000000000',
  currency: 'VND',
}

function datApiKey(overrides: Partial<DanhSachKey> = {}) {
  const data: DanhSachKey = { ...CO_SO_KEY, ...overrides }
  server.use(http.get('/api/v1/billing/by-key', () => HttpResponse.json(data)))
}

/** Hàng «Trần Minh Quân» khớp CÙNG người của `CO_SO_KEY` (cùng ý nghĩa nghiệp
 *  vụ, khác chiều gộp) + hàng «chưa phân loại» ghim cuối — KHÔNG có
 *  `chi_phi_tong` riêng cho chiều này (`DongOwner[]` trần, xem `kieu.ts`). */
const CO_SO_OWNER: DongOwner[] = [
  {
    user_id: 'u_quan',
    ten: 'Trần Minh Quân',
    email: 'quan.tm@greenpark.vn',
    so_key: 2,
    so_phien: 197,
    // Sáu cột LƯỢNG mọc ở BE 2026-08-24 cho bảng của `/usage` — bảng của
    // `/billing` (bài này) KHÔNG hiện chúng, nhưng kiểu đòi có mặt.
    input_tokens: 6_816_200,
    output_tokens: 807_700,
    cache_read_tokens: 748_600,
    voice_sec: 27_619.4,
    so_event: 7_486,
    chi_phi: '409491.0000000000',
    // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (300000+80000+20000+491+8000+900+100).
    chi_phi_llm: '300000.0000000000',
    chi_phi_tts: '80000.0000000000',
    chi_phi_stt: '20000.0000000000',
    chi_phi_embed: '491.0000000000',
    chi_phi_call: '8000.0000000000',
    chi_phi_vad: '900.0000000000',
    chi_phi_speaker_verify: '100.0000000000',
  },
  {
    user_id: null,
    ten: null,
    email: null,
    so_key: 0,
    so_phien: 7,
    input_tokens: 242_200,
    output_tokens: 28_700,
    cache_read_tokens: 26_600,
    voice_sec: 981.4,
    so_event: 266,
    chi_phi: '5000.0000000000',
    // Cùng bảy cột với hàng «chưa phân loại» của `CO_SO_KEY` — cùng nhóm, cùng tổng.
    chi_phi_llm: '3500.0000000000',
    chi_phi_tts: '900.0000000000',
    chi_phi_stt: '400.0000000000',
    chi_phi_embed: '2.0000000000',
    chi_phi_call: '150.0000000000',
    chi_phi_vad: '40.0000000000',
    chi_phi_speaker_verify: '8.0000000000',
  },
]

function datApiOwner(items: DongOwner[] = CO_SO_OWNER) {
  server.use(http.get('/api/v1/billing/by-owner', () => HttpResponse.json(items)))
}

/** `sess-aaa111`/`sess-bbb222`/`sess-ccc333` — cả ba ≤ 12 ký tự, tức luật
 *  "cắt còn 12 ký tự" của cột Phiên không cắt gì cả ở đây (chuỗi ngắn hơn
 *  ngưỡng) — hiện nguyên văn, dễ assert bằng `findByText` chuỗi đầy đủ. Hai
 *  hàng `exact: false` (theo đúng khuôn task-5-brief: "fixture có 2 phiên
 *  exact=false"), một hàng `exact: true` để đối chứng KHÔNG có badge. */
const CO_SO_PHIEN: DanhSachPhien = {
  items: [
    {
      session_id: 'sess-aaa111',
      agent_key_id: 1,
      key_label: 'K-prod-web',
      customer_name: 'Nguyễn Minh Anh',
      phone: '0912448111',
      channel: 'chat',
      bat_dau: '2026-08-14T09:12:00+07:00',
      so_turn: 8,
      input_tokens: 4_200,
      output_tokens: 1_300,
      voice_sec: 0,
      chi_phi: '3200.0000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (2000+700+300+50+100+40+10).
      chi_phi_llm: '2000.0000000000',
      chi_phi_tts: '700.0000000000',
      chi_phi_stt: '300.0000000000',
      chi_phi_embed: '50.0000000000',
      chi_phi_call: '100.0000000000',
      chi_phi_vad: '40.0000000000',
      chi_phi_speaker_verify: '10.0000000000',
      exact: true,
    },
    {
      session_id: 'sess-bbb222',
      agent_key_id: null,
      key_label: null,
      customer_name: null,
      phone: '0987654321',
      channel: 'voice',
      bat_dau: '2026-08-15T10:00:00+07:00',
      so_turn: 3,
      input_tokens: 900,
      output_tokens: 300,
      voice_sec: 176.85,
      chi_phi: '1800.0000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (1000+400+200+30+120+40+10).
      chi_phi_llm: '1000.0000000000',
      chi_phi_tts: '400.0000000000',
      chi_phi_stt: '200.0000000000',
      chi_phi_embed: '30.0000000000',
      chi_phi_call: '120.0000000000',
      chi_phi_vad: '40.0000000000',
      chi_phi_speaker_verify: '10.0000000000',
      exact: false,
    },
    {
      session_id: 'sess-ccc333',
      agent_key_id: 1,
      key_label: 'K-prod-web',
      customer_name: null,
      phone: null,
      channel: 'chat',
      bat_dau: '2026-08-16T08:00:00+07:00',
      so_turn: 5,
      input_tokens: 1_200,
      output_tokens: 400,
      voice_sec: 0,
      chi_phi: '900.0000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (500+200+100+20+60+15+5).
      chi_phi_llm: '500.0000000000',
      chi_phi_tts: '200.0000000000',
      chi_phi_stt: '100.0000000000',
      chi_phi_embed: '20.0000000000',
      chi_phi_call: '60.0000000000',
      chi_phi_vad: '15.0000000000',
      chi_phi_speaker_verify: '5.0000000000',
      exact: false,
    },
  ],
  total: 3,
}

function datApiPhien(overrides: Partial<DanhSachPhien> = {}) {
  const data: DanhSachPhien = { ...CO_SO_PHIEN, ...overrides }
  server.use(http.get('/api/v1/billing/sessions', () => HttpResponse.json(data)))
}

beforeEach(() => {
  datApi()
  datApiKey()
  datApiOwner()
  datApiPhien()
})

/**
 * Fixture mục ② — HAI bất biến được cố tình mã hoá vào đây:
 *  · `theo_ngay` có ngày `chi_phi: '0'` (03/08) — ngày thật không phát sinh,
 *    KHÔNG được rơi khỏi chuỗi vẽ.
 *  · `vad` có số đo nhưng `chi_phi: '0'` — component đo được mà chưa có giá.
 * Tổng cả hai chiều = `chi_phi_tong`, đúng như BE đảm bảo.
 */
const CO_SO_PHAN_TICH: PhanTich = {
  theo_ngay: [
    {
      ngay: '2026-08-01',
      chi_phi: '30000.0000000000',
      phan: [
        { component: 'llm', chi_phi: '24000.0000000000' },
        { component: 'call', chi_phi: '6000.0000000000' },
      ],
    },
    {
      ngay: '2026-08-02',
      chi_phi: '20000.0000000000',
      phan: [{ component: 'llm', chi_phi: '20000.0000000000' }],
    },
    // Ngày rỗng: `phan` RỖNG, không phải thiếu khoá.
    { ngay: '2026-08-03', chi_phi: '0', phan: [] },
    {
      ngay: '2026-08-04',
      chi_phi: '75000.5000000000',
      phan: [
        { component: 'llm', chi_phi: '56000.5000000000' },
        { component: 'call', chi_phi: '19000.0000000000' },
        // Dòng 0 đồng CÓ ở API (component chưa có giá) — tooltip phải lọc bỏ.
        { component: 'vad', chi_phi: '0' },
      ],
    },
  ],
  theo_component: [
    {
      component: 'llm',
      so_event: 120,
      input_tokens: 100_000,
      output_tokens: 20_000,
      cache_read_tokens: 5_000,
      audio_sec: 0,
      text_units: 0,
      units: 120,
      chi_phi: '100000.5000000000',
    },
    {
      component: 'call',
      so_event: 2,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 176.85,
      text_units: 0,
      units: 2,
      chi_phi: '25000.0000000000',
    },
    {
      component: 'vad',
      so_event: 40,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 529.1,
      text_units: 0,
      units: 0,
      chi_phi: '0',
    },
  ],
  chi_phi_tong: '125000.5000000000',
  currency: 'VND',
}

function datApiPhanTich(overrides: Partial<PhanTich> = {}) {
  const data: PhanTich = { ...CO_SO_PHAN_TICH, ...overrides }
  server.use(http.get('/api/v1/billing/breakdown', () => HttpResponse.json(data)))
}

describe('② Tiền đi đâu', () => {
  /** Thẻ «Theo từng dịch vụ» — TỪ 2026-08-25, bảng ③ (chiều «Khoá») cũng có
   *  cột LLM/TTS/STT/Embed/Cuộc gọi/VAD/Xác thực giọng cùng NHÃN NGẮN này, nên
   *  mọi phép tìm nhãn component phải `within` đúng thẻ này, không tìm cả màn. */
  function theoDichVu(): HTMLElement {
    return screen.getByRole('heading', { name: 'Theo từng dịch vụ' }).closest('div')!
      .parentElement as HTMLElement
  }

  it('hai thẻ, và tiền của mỗi component đọc từ API', async () => {
    datApiPhanTich()
    boot()

    expect(await screen.findByText('Chi phí theo ngày')).toBeInTheDocument()
    const the = theoDichVu()
    expect(within(the).getByText('LLM')).toBeInTheDocument()
    expect(within(the).getByText('Cuộc gọi')).toBeInTheDocument()
    expect(within(the).getByText(`${tien('100000.5000000000')} ₫`)).toBeInTheDocument()
  })

  it('component ĐO ĐƯỢC mà KHÔNG tính tiền vẫn có hàng, và nói ra là không tính tiền', async () => {
    datApiPhanTich()
    boot()

    await screen.findByText('Chi phí theo ngày')
    const the = theoDichVu()
    // Ẩn hàng này là giấu đúng thứ dải `thieu_gia` phía trên đang cảnh báo.
    expect(within(the).getByText('VAD')).toBeInTheDocument()
    expect(within(the).getByText('không tính tiền')).toBeInTheDocument()
    // …và KHÔNG được hiện một phần trăm như thể nó có phần trong tổng.
    expect(within(the).queryByText('0,0%')).not.toBeInTheDocument()
  })

  it('TB/ngày chia cho SỐ NGÀY của kỳ, kể cả ngày 0 đồng', async () => {
    datApiPhanTich()
    boot()

    // 125000,5 / 4 ngày = 31250,125 → hiện 31.250. Mẫu số là 4, KHÔNG phải 3:
    // bỏ ngày 0 đồng ra khỏi mẫu số là nói "trung bình mỗi ngày CÓ CHẠY", một
    // đại lượng khác hẳn thứ nhãn đang hứa.
    expect(await screen.findByText(new RegExp(`TB\\s*${tien('31250.1250')}`))).toBeInTheDocument()
  })

  it('lỗi riêng của mục ② KHÔNG làm sập mục ① và ③', async () => {
    server.use(http.get('/api/v1/billing/breakdown', () => new HttpResponse(null, { status: 500 })))
    boot()

    expect(await screen.findByRole('heading', { name: 'Tổng chi phí' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
    // Mục ③ vẫn đứng — nó đọc endpoint khác.
    expect(screen.getByText('Lượt dùng chi tiết')).toBeInTheDocument()
  })
})

/**
 * Hình học SVG — render THẲNG `BieuDoChiPhi` với prop `co`, không qua router.
 * jsdom không có engine bố cục (`clientWidth` luôn 0) và stub `ResizeObserver`
 * ở `vitest.setup.ts` cố ý không bao giờ bắn callback, nên đường vẽ KHÔNG tồn
 * tại trong các bài đi qua `boot()` phía trên. `co` là seam duy nhất để kiểm
 * nó — cùng khuôn `BieuDoNgay` của `features/ops`.
 */
describe('② biểu đồ — hình học', () => {
  const CO = { rong: 600, cao: 260 }
  const MAU = bangMau(CO_SO_PHAN_TICH.theo_component)

  it('vẽ ĐỦ số điểm bằng số ngày, kể cả ngày 0 đồng', () => {
    const { container } = render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={CO}
      />,
    )
    // CHIỀU CAO ĐI THEO KHUNG ĐO ĐƯỢC, không phải một hằng trong component.
    // Bản đầu khoá `height` vào 260px trong khi thẻ bị lưới `items-stretch`
    // kéo cao theo thẻ «Theo component» ⇒ chart nằm gọn ở nửa trên, để lại
    // một mảng trắng bên dưới. Cổng này khoá đúng chiều đó.
    const svg = container.querySelector('svg')
    expect(svg?.getAttribute('height')).toBe(String(CO.cao))
    expect(svg?.getAttribute('width')).toBe(String(CO.rong))

    const duong = container.querySelector('path[stroke="var(--color-ac)"]')
    expect(duong).not.toBeNull()
    const d = duong?.getAttribute('d') ?? ''
    // 4 ngày ⇒ 4 toạ độ. Ngày 03/08 (0 đồng) là một điểm THẬT nằm ở đáy, không
    // phải một chỗ khuyết để đường nối tắt qua.
    expect(d.split('L')).toHaveLength(CO_SO_PHAN_TICH.theo_ngay.length)
  })

  it('mỗi ngày có một vùng bắt chuột đọc được số tiền của đúng ngày đó', () => {
    render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={CO}
      />,
    )
    // Nhãn đọc được là đường DUY NHẤT một người dùng bàn phím/trình đọc màn
    // hình lấy được số của từng ngày — tooltip chỉ hiện khi hover/focus.
    expect(screen.getByLabelText('03/08/2026: 0 ₫')).toBeInTheDocument()
    expect(screen.getByLabelText(`04/08/2026: ${tien('75000.5000000000')} ₫`)).toBeInTheDocument()
  })

  it('thẻ cao hơn thì SVG cao theo — không có trần cứng', () => {
    const { container } = render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={{ rong: 600, cao: 430 }}
      />,
    )
    expect(container.querySelector('svg')?.getAttribute('height')).toBe('430')
  })

  it('nhãn trục ngang MANG THÁNG (dd/MM), có ngày đầu và ngày cuối', () => {
    const { container } = render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={CO}
      />,
    )
    const nhan = [...container.querySelectorAll('svg text')].map((t) => t.textContent)
    // Không có tháng thì kỳ «30 ngày» bắc qua hai tháng đọc thành vô nghĩa.
    expect(nhan).toContain('01/08')
    expect(nhan).toContain('04/08')
    expect(nhan.some((x) => x === '01' || x === '04')).toBe(false)
  })

  it('đường TB mang LUÔN con số, không chỉ hai chữ «TB»', () => {
    const { container } = render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={CO}
      />,
    )
    const nhan = [...container.querySelectorAll('svg text')].map((t) => t.textContent)
    expect(nhan).toContain(`TB ${tien('31250.1250')} ₫`)
  })

  it('tooltip: tổng + TÁCH THEO COMPONENT của đúng ngày đó, bỏ dòng 0 đồng', async () => {
    const { container } = render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={CO}
      />,
    )
    const vung = container.querySelectorAll('g[aria-label]')
    fireEvent.mouseEnter(vung[3] as Element) // 04/08 — ngày có 3 dòng `phan`

    const tip = await screen.findByRole('status')
    expect(within(tip).getByText('04/08/2026')).toBeInTheDocument()
    expect(within(tip).getByText('Tổng')).toBeInTheDocument()
    expect(within(tip).getByText(`${tien('75000.5000000000')} ₫`)).toBeInTheDocument()
    // Tách component — thứ thẻ bên phải chỉ trả lời được cho CẢ KỲ.
    expect(within(tip).getByText('LLM')).toBeInTheDocument()
    expect(within(tip).getByText(tien('56000.5000000000'))).toBeInTheDocument()
    expect(within(tip).getByText('Cuộc gọi')).toBeInTheDocument()
    // `vad` 0 đồng KHÔNG được chen vào giữa các dòng có tiền.
    expect(within(tip).queryByText('VAD')).not.toBeInTheDocument()
  })

  it('tooltip của ngày 0 đồng nói «Không phát sinh», không hiện danh sách rỗng', async () => {
    const { container } = render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={CO}
      />,
    )
    fireEvent.mouseEnter(container.querySelectorAll('g[aria-label]')[2] as Element)
    const tip = await screen.findByRole('status')
    expect(within(tip).getByText('Không phát sinh')).toBeInTheDocument()
  })

  it('khung quá hẹp thì KHÔNG vẽ, nhưng hàng «TB/ngày» vẫn còn', () => {
    // Lần render đầu (trước khi `ResizeObserver` kịp đo) rơi vào đúng ca này.
    const { container } = render(
      <BieuDoChiPhi
        chuoi={CO_SO_PHAN_TICH.theo_ngay}
        chiPhiTong={CO_SO_PHAN_TICH.chi_phi_tong}
        mau={MAU}
        co={{ rong: 0, cao: 260 }}
      />,
    )
    expect(container.querySelector('svg')).toBeNull()
    expect(screen.getByText(new RegExp(`TB\\s*${tien('31250.1250')}`))).toBeInTheDocument()
  })
})

describe('① bốn thẻ KPI', () => {
  it('hiện bốn nhãn, và «Thời lượng gọi» đọc voice_sec (KHÔNG phải «Thời lượng voice»)', async () => {
    boot()

    expect(await screen.findByRole('heading', { name: 'Tổng chi phí' })).toBeInTheDocument()
    expect(screen.getByText('Token')).toBeInTheDocument()
    // `getByRole('heading', …)` chứ không `getByText`: từ Task 5, bảng ③ (mặc
    // định chiều «Khoá») cũng có một cột tên «Phiên» — `<h3>` của thẻ KPI vẫn
    // là nhãn DUY NHẤT mang role heading, cột bảng là `columnheader`.
    expect(screen.getByRole('heading', { name: 'Phiên hội thoại' })).toBeInTheDocument()
    expect(screen.getByText('Thời lượng gọi')).toBeInTheDocument()
    expect(screen.queryByText(/thời lượng voice/i)).not.toBeInTheDocument()
    // Thẻ «API key đang hoạt động» đã BỎ (2026-09-29) — chỗ nhường cho thẻ
    // Tổng chi phí. Canh chiều ngược để nó không quay lại.
    expect(screen.queryByText('API key đang hoạt động')).not.toBeInTheDocument()

    // Đọc từ hằng `CO_SO` qua chính `giay()`/`tien()`/`token()` — không gõ tay
    // lại con số, cùng lý lẽ `TONG_DANH_GIA_GIA` ở `quality-list.test.tsx`.
    expect(screen.getByText(giay(CO_SO.voice_sec))).toBeInTheDocument()
    expect(screen.getByText(tien(CO_SO.chi_phi))).toBeInTheDocument()
    expect(screen.getByText(String(CO_SO.so_phien))).toBeInTheDocument()
    // Thẻ Tổng chi phí chiếm hai cột — chỗ của thẻ khoá đã bỏ.
    expect(
      screen.getByRole('heading', { name: 'Tổng chi phí' }).closest('div')?.className,
    ).toContain('col-span-2')
  })

  it('bốn con số CHỈ khác nhau ở CỠ — font, độ đậm, tracking phải trùng khít', async () => {
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    // Bug 2026-08-21: thẻ nhấn dùng `font-semibold` còn bốn thẻ cạnh nó dùng
    // `font-medium` — hai độ đậm trên cùng một hàng đọc ra thành hai KIỂU CHỮ,
    // không ra một thứ bậc. Cỡ chữ (32 vs 26) mới là thứ được phép khác.
    const NHAN = ['Tổng chi phí', 'Token', 'Phiên hội thoại', 'Thời lượng gọi']
    const kieu = NHAN.map((nhan) => {
      // `getByRole('heading', …)`, không `getByText`: từ 2026-08-25 bảng ③
      // cũng có một cột «Tổng chi phí» — `<h3>` của thẻ KPI vẫn là nhãn DUY
      // NHẤT mang role heading (cột bảng là `columnheader`/`button`).
      const so = screen.getByRole('heading', { name: nhan }).closest('div')?.querySelector('p')
      expect(so, `không thấy con số của thẻ «${nhan}»`).not.toBeNull()
      return (
        [...(so as HTMLElement).classList]
          // bỏ token CỠ — cái duy nhất được khác: cỡ viết tay `text-[Npx]` hoặc bậc thang
          // `--text-*` (theme.css, 2026-10-05)
          .filter((c) => !/^text-(\[\d|(nhan|phu|than|noi|the|muc|trang|so|so-lon)$)/.test(c))
          .sort()
          .join(' ')
      )
    })
    expect(new Set(kieu).size, `bốn thẻ đang có ${new Set(kieu).size} kiểu chữ`).toBe(1)
    expect(kieu[0]).toContain('font-mono')
    expect(kieu[0]).toContain('tabular-nums')
  })

  it('thẻ Token hiện tổng ở số lớn, in/out/cache ở dòng chân', async () => {
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    const tong = CO_SO.input_tokens + CO_SO.output_tokens + CO_SO.cache_read_tokens
    expect(screen.getByText(token(tong))).toBeInTheDocument()

    // Kiểm TỪNG mục, không kiểm cả câu. Trước 2026-08-21 dòng chân là MỘT
    // chuỗi bị `truncate` cắt cụt trong thẻ rộng 1/5 hàng — mục cuối (`cache
    // read`) không bao giờ đọc được, mà một bài neo vào cả chuỗi thì vẫn XANH
    // vì `textContent` không biết CSS đã cắt tới đâu. Ba phép tìm rời nhau
    // cũng chính là bất biến cần giữ: mỗi con số là một dữ kiện độc lập.
    const theToken = screen.getByText('Token').closest('div') as HTMLElement
    for (const [nhan, gia] of [
      ['in', token(CO_SO.input_tokens)],
      ['out', token(CO_SO.output_tokens)],
      ['cache read', token(CO_SO.cache_read_tokens)],
    ]) {
      expect(within(theToken).getByText(nhan as string)).toBeInTheDocument()
      expect(within(theToken).getByText(gia as string)).toBeInTheDocument()
    }
  })
})

describe('kỳ và khoảng ngày', () => {
  it('kỳ mặc định là Tháng này, và hiện khoảng ngày THẬT', async () => {
    boot()

    expect(
      await screen.findByRole('button', { name: 'Tháng này', pressed: true }),
    ).toBeInTheDocument()
    expect(screen.getByText(/\d{2}\/\d{2} – \d{2}\/\d{2}\/\d{4}/)).toBeInTheDocument()
  })

  it('bấm «Tháng trước» đổi nút đang nhấn VÀ đổi URL', async () => {
    const router = boot()
    await screen.findByRole('button', { name: 'Tháng này', pressed: true })

    await userEvent.click(screen.getByRole('button', { name: 'Tháng trước' }))

    expect(
      await screen.findByRole('button', { name: 'Tháng trước', pressed: true }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tháng này' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(router.state.location.search.ky).toBe('thang-truoc')
  })
})

describe('bốn nhánh trạng thái', () => {
  it('đang tải lần đầu → skeleton đúng hình 5 thẻ, không spinner giữa màn', async () => {
    server.use(
      http.get('/api/v1/billing/summary', async () => {
        await delay(30)
        return HttpResponse.json(CO_SO)
      }),
    )
    boot()

    // Kỳ vẫn bấm được ngay trong lúc tải — không có nhánh "khoá cả màn".
    expect(await screen.findByRole('button', { name: 'Tháng này' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Tổng chi phí' })).not.toBeInTheDocument()

    expect(await screen.findByRole('heading', { name: 'Tổng chi phí' })).toBeInTheDocument()
  })

  it('403 KHÔNG hiện LoiTai — không có nút Thử lại cho một lỗi quyền', async () => {
    datApi403()
    boot()

    expect(await screen.findByText(/không có quyền xem chi phí/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /thử lại/i })).toBeNull()
    expect(screen.queryByText(/không tải được/i)).not.toBeInTheDocument()
  })

  it('lỗi khác (500) → LoiTai với nút Thử lại, thử lại thành công thì hiện dữ liệu', async () => {
    datApiLoi()
    boot()

    expect(await screen.findByText(/Không tải được dữ liệu lượng dùng/i)).toBeInTheDocument()
    expect(screen.queryByText(/không có quyền/i)).not.toBeInTheDocument()

    datApi()
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))

    expect(await screen.findByRole('heading', { name: 'Tổng chi phí' })).toBeInTheDocument()
  })

  it('so_phien = 0 ⇒ KhoRong, không phải bảng/thẻ toàn số 0', async () => {
    datApi({ so_phien: 0 })
    boot()

    expect(await screen.findByText('Chưa có lượt dùng nào')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Tổng chi phí' })).not.toBeInTheDocument()
  })
})

describe('③ Explorer — một bảng, ba chiều gộp (Task 5)', () => {
  it('hàng «Chưa phân loại» GHIM CUỐI và không có cách nào ẩn nó', async () => {
    boot('/billing')
    await screen.findByText('K-prod-web')

    const hang = screen.getAllByRole('row')
    const nhan = hang.map((r) => r.textContent ?? '')
    const i = nhan.findIndex((t) => t.includes(NHAN_CHUA_PHAN_LOAI))
    expect(i).toBeGreaterThan(-1)
    // Ghim CUỐI: sau nó chỉ còn hàng Tổng, không hàng dữ liệu nào khác.
    expect(nhan.slice(i + 1).filter((t) => !t.includes('Tổng kỳ'))).toHaveLength(0)
    // Không nút/checkbox nào lọc bỏ nó.
    expect(screen.queryByRole('checkbox', { name: /chưa phân loại|ẩn/i })).toBeNull()
  })

  it('ghim cuối GIỮ NGUYÊN dù đổi cột đang sắp xếp — không riêng mặc định chi_phi', async () => {
    boot('/billing')
    await screen.findByText('K-prod-web')

    await userEvent.click(screen.getByRole('button', { name: 'Phiên' }))

    const nhan = screen.getAllByRole('row').map((r) => r.textContent ?? '')
    const i = nhan.findIndex((t) => t.includes(NHAN_CHUA_PHAN_LOAI))
    expect(i).toBeGreaterThan(-1)
    expect(nhan.slice(i + 1).filter((t) => !t.includes('Tổng kỳ'))).toHaveLength(0)
  })

  /**
   * GATE TRƯỚC ĐÂY RỖNG (review 2026-08-20): hai bài trên canh ĐÚNG luật §9.1
   * («Chưa phân loại» ghim cuối + không control nào lọc bỏ) nhưng CHỈ ở chiều
   * «Khoá». `BangLuotDung.tsx::BangTheoNguoiTao` thi hành ĐÚNG cùng luật đó
   * cho `user_id === null` (dòng `ghimCuoiVaSap(items, (d) => d.user_id ===
   * null, …)`) — nhưng không bài nào canh nó: lọc bỏ hẳn hàng đó ở chiều
   * «Người tạo» vẫn để suite XANH. Bài này lặp lại đúng hai assertion của hai
   * bài trên (ghim cuối, không control lọc bỏ) nhưng sau khi bấm sang tab
   * «Người tạo» — dùng CO_SO_OWNER (đã có sẵn hàng `user_id: null`, xem dòng
   * khai báo hằng đó phía trên).
   */
  it('chiều «Người tạo»: hàng «Chưa phân loại» GHIM CUỐI và không có cách nào ẩn nó', async () => {
    boot('/billing')
    await screen.findByText('K-prod-web')

    await userEvent.click(screen.getByRole('tab', { name: 'Người tạo' }))
    await screen.findByText('quan.tm@greenpark.vn')

    const hang = screen.getAllByRole('row')
    const nhan = hang.map((r) => r.textContent ?? '')
    const i = nhan.findIndex((t) => t.includes(NHAN_CHUA_PHAN_LOAI))
    expect(i).toBeGreaterThan(-1)
    // Ghim CUỐI: sau nó chỉ còn hàng Tổng, không hàng dữ liệu nào khác.
    expect(nhan.slice(i + 1).filter((t) => !t.includes('Tổng kỳ'))).toHaveLength(0)
    // Không nút/checkbox nào lọc bỏ nó.
    expect(screen.queryByRole('checkbox', { name: /chưa phân loại|ẩn/i })).toBeNull()
  })

  it('hàng Tổng dùng chi_phi_tong của API, KHÔNG tự cộng — dù lệch với tổng các hàng', async () => {
    // Cố tình LỆCH so với tổng bốn hàng thật (414501) — đây là tín hiệu lỗi.
    datApiKey({ chi_phi_tong: '999999.0000000000' })
    boot('/billing')
    await screen.findByText('K-prod-web')

    // Hàng Tổng hiện số API trả (999.999 theo nhóm nghìn vi-VN), KHÔNG phải
    // tổng tự cộng (414.501).
    expect(screen.getByText(tien('999999.0000000000'))).toBeInTheDocument()
    expect(screen.queryByText(tien('414501.0000000000'))).not.toBeInTheDocument()

    // Lệch ⇒ dải cảnh báo riêng (có thể có thêm dải cảnh báo khác của mục ①
    // cùng `role="status"` — tìm đúng dải nói về Tổng chi phí API trả về, câu
    // chữ hiện hành của banner này — không neo vào tên trường thô `chi_phi_tong`
    // vì banner không hiện tên trường đó cho người dùng nữa).
    const dai = await screen.findAllByRole('status')
    expect(dai.some((el) => /Tổng chi phí API trả về/.test(el.textContent ?? ''))).toBe(true)
  })

  it('đổi chiều gộp KHÔNG đổi kỳ, và ghi vào URL (replace)', async () => {
    const r = boot('/billing')
    await screen.findByText('K-prod-web')

    await userEvent.click(screen.getByRole('tab', { name: 'Người tạo' }))

    expect(await screen.findByText('quan.tm@greenpark.vn')).toBeInTheDocument()
    expect(r.state.location.search).toMatchObject({ gop: 'nguoi', ky: 'thang-nay', trang: 1 })
  })

  it('cột voice_sec KHÔNG có ở bảng chính (không cộng chéo component)', async () => {
    boot('/billing')
    await screen.findByText('K-prod-web')

    expect(screen.queryByRole('columnheader', { name: /voice|thời lượng/i })).toBeNull()
  })

  it('«Đã thu hồi» hiện pill trên hàng khoá đã thu hồi', async () => {
    boot('/billing')
    await screen.findByText('K-prod-web')

    expect(screen.getByText('Đã thu hồi')).toBeInTheDocument()
    expect(
      within(screen.getByText('K-cu-thu-hoi').closest('tr')!).getByText('Đã thu hồi'),
    ).toBeInTheDocument()
  })

  it('bảy cột dịch vụ (LLM/TTS/STT/Embed/Cuộc gọi/VAD/Xác thực giọng) thay ba cột token in/out/cache read', async () => {
    boot('/billing')
    await screen.findByText('K-prod-web')

    for (const nhan of ['LLM', 'TTS', 'STT', 'Embed', 'Cuộc gọi', 'VAD', 'Xác thực giọng']) {
      expect(screen.getByRole('columnheader', { name: nhan })).toBeInTheDocument()
    }
    expect(
      screen.queryByRole('columnheader', { name: /token in|token out|cache read/i }),
    ).toBeNull()

    // Cột «Tổng chi phí» của bảng và tiêu đề «Tổng chi phí» của thẻ KPI CÙNG
    // chữ nhưng KHÔNG đụng nhau: cột bảng luôn kèm mũi tên sắp xếp
    // (`↓`/`↑`/`↕`) ngay sau chữ nên `textContent` của nó không BAO GIỜ khớp
    // đúng chuỗi `'Tổng chi phí'` trần — `getByRole('heading', …)` vẫn chỉ
    // trúng MỘT phần tử (thẻ KPI), `getByRole('columnheader', …)` trúng cột.
    expect(screen.getByRole('heading', { name: 'Tổng chi phí' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Tổng chi phí' })).toBeInTheDocument()

    const hangProdWeb = screen.getByText('K-prod-web').closest('tr')!
    for (const gia of [
      tien('300000.0000000000'),
      tien('60000.0000000000'),
      tien('30000.0000000000'),
      tien('80.0000000000'),
      tien('8000.0000000000'),
      tien('1800.0000000000'),
      tien('611.0000000000'),
    ]) {
      expect(within(hangProdWeb).getByText(gia)).toBeInTheDocument()
    }
    // «Tổng chi phí» của hàng vẫn hiện đúng `chi_phi` — không phải tổng bảy cột
    // trên tự cộng lại ở FE (dù ở fixture này hai số bằng nhau).
    expect(within(hangProdWeb).getByText(tien('400491.0000000000'))).toBeInTheDocument()
  })

  it('chiều «Phiên»: exact=true KHÔNG có badge; hai hàng exact=false có pill «Đo thiếu»', async () => {
    boot('/billing?gop=phien')
    await screen.findByText('sess-aaa111')

    expect(screen.getAllByText('Đo thiếu')).toHaveLength(2)
    const hangExact = screen.getByText('sess-aaa111').closest('tr')!
    expect(within(hangExact).queryByText('Đo thiếu')).toBeNull()
  })

  it('chiều «Phiên»: phân trang PUSH khi bấm nút «›» (Back = trang trước), giữ nguyên gop', async () => {
    datApiPhien({ total: 120 })
    const r = boot('/billing?gop=phien')
    await screen.findByText('sess-aaa111')

    const thanh = screen.getByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: 'Trang sau' }))

    expect(await within(thanh).findByRole('button', { name: '2' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(r.state.location.search).toMatchObject({ gop: 'phien', trang: 2 })
  })

  it('chiều «Phiên»: bấm thẳng số trang trong thanh phân trang cũng PUSH', async () => {
    // total=120, GIOI_HAN_PHIEN=10 ⇒ 12 trang. Ở trang 1, dãy hiện `1 2 … 12`
    // (§`daySoTrang`) — bấm trang CUỐI để canh cả cú nhảy xa, không chỉ liền kề.
    datApiPhien({ total: 120 })
    const r = boot('/billing?gop=phien')
    await screen.findByText('sess-aaa111')

    const thanh = screen.getByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '12' }))

    expect(r.state.location.search).toMatchObject({ gop: 'phien', trang: 12 })
  })

  it('chiều «Phiên»: hết trang ⇒ nút «›» disabled, chỉ 1 trang thì không hiện số trang nào khác', async () => {
    boot('/billing?gop=phien') // total = 3, ≤ limit 10 mặc định
    await screen.findByText('sess-aaa111')

    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    expect(within(thanh).getByRole('button', { name: 'Trang sau' })).toBeDisabled()
    expect(within(thanh).getByRole('button', { name: 'Trang trước' })).toBeDisabled()
    expect(within(thanh).queryByRole('button', { name: '2' })).not.toBeInTheDocument()
  })
})

/**
 * HÌNH TRONG THẺ KPI — sparkline (thẻ «Chi phí») + thanh xếp lớp (thẻ «Token»).
 * Phương án D của `docs/design/demo-usage-tong-quan.html`, người dùng chốt
 * 2026-08-21 kèm một điều kiện: KHÔNG hiệu ứng hover.
 *
 * ĐIỀU QUAN TRỌNG NHẤT Ở ĐÂY LÀ BÀI `/breakdown` HỎNG. Sparkline đọc
 * `theo_ngay` của `/breakdown`, còn năm con số đọc `/summary` — hai endpoint
 * KHÁC NHAU. Nếu ai đó nối chúng lại (cho `TheKpi` tự gọi hook rồi chờ
 * `isPending`, hoặc để `UsageScreen` bỏ cuộc khi `qNgay.error`) thì một lỗi ở
 * `/breakdown` sẽ giết luôn mục ① — đúng thứ `PhanTichChiPhi` đã cấm bằng chữ.
 *
 * Truy vấn hình bằng DOM trực tiếp (`querySelector`) chứ không bằng role/text:
 * cả hai đều `aria-hidden` CÓ CHỦ Ý (số liệu đã là chữ ngay cạnh), nên chúng
 * không có role nào để tìm. Cùng lối các bài «② biểu đồ — hình học» ở trên.
 * Luôn `within` một THẺ cụ thể: mục ② cũng có `polyline`/`span` trên màn.
 */
describe('① hình trong thẻ', () => {
  /** Thẻ KPI mang nhãn `nhan` — hình luôn phải tìm bên trong nó, không tìm cả màn.
   *  `getByRole('heading', …)`, không `getByText`: từ 2026-08-25 bảng ③ cũng có
   *  một cột «Tổng chi phí» — `<h3>` của thẻ KPI vẫn là nhãn DUY NHẤT mang role
   *  heading (cột bảng là `columnheader`/`button`). */
  function the(nhan: string): HTMLElement {
    const el = screen.getByRole('heading', { name: nhan }).closest('div')
    expect(el, `không thấy thẻ «${nhan}»`).not.toBeNull()
    return el as HTMLElement
  }

  function datApiPhanTichLoi() {
    server.use(http.get('/api/v1/billing/breakdown', () => new HttpResponse(null, { status: 500 })))
  }

  it('sparkline vẽ ĐÚNG một điểm cho mỗi ngày của `theo_ngay`', async () => {
    datApi()
    datApiPhanTich()
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    const sp = await vi.waitFor(() => {
      const el = the('Tổng chi phí').querySelector('polyline')
      expect(el, 'thẻ Chi phí chưa có sparkline').not.toBeNull()
      return el as SVGPolylineElement
    })
    // 4 ngày trong fixture ⇒ 4 điểm. Ngày 0 đồng (`2026-08-03`) VẪN là một
    // điểm: bỏ nó là nối thẳng qua chỗ trũng, tức vẽ một mức tiền dương cho
    // ngày agent không chạy (luật ở `DongNgay.chi_phi`).
    expect(sp.getAttribute('points')!.trim().split(/\s+/)).toHaveLength(
      CO_SO_PHAN_TICH.theo_ngay.length,
    )
    // Thiếu cái này thì nét dày mỏng khác nhau theo bề rộng thẻ (thẻ co theo lưới).
    expect(sp.getAttribute('vector-effect')).toBe('non-scaling-stroke')
  })

  it('`/breakdown` HỎNG ⇒ mục ① vẫn đủ năm con số, chỉ mất cái hình', async () => {
    datApi()
    datApiPhanTichLoi()
    boot()

    // Năm con số — thứ mục ① thật sự sống bằng (`/summary`).
    expect(await screen.findByText(tien(CO_SO.chi_phi))).toBeInTheDocument()
    expect(screen.getByText(giay(CO_SO.voice_sec))).toBeInTheDocument()
    expect(screen.getByText(String(CO_SO.so_phien))).toBeInTheDocument()
    // …và KHÔNG có sparkline. Chờ mục ② báo lỗi xong mới khẳng định, nếu không
    // bài này xanh chỉ vì `/breakdown` còn đang bay.
    await screen.findByRole('button', { name: 'Thử lại' })
    expect(the('Tổng chi phí').querySelector('polyline')).toBeNull()
  })

  it('kỳ chỉ có MỘT ngày ⇒ không vẽ (một điểm không thành đường)', async () => {
    datApi()
    datApiPhanTich({
      theo_ngay: [{ ngay: '2026-08-01', chi_phi: '30000.0000000000', phan: [] }],
    })
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    await screen.findByText('Chi phí theo ngày')
    expect(the('Tổng chi phí').querySelector('polyline')).toBeNull()
  })

  it('mọi ngày 0 đồng (thiếu bảng giá) ⇒ không vẽ, không NaN', async () => {
    datApi({ chi_phi: '0' })
    datApiPhanTich({
      theo_ngay: [
        { ngay: '2026-08-01', chi_phi: '0', phan: [] },
        { ngay: '2026-08-02', chi_phi: '0', phan: [] },
      ],
      chi_phi_tong: '0',
    })
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    await screen.findByText('Chi phí theo ngày')
    const theChiPhi = the('Tổng chi phí')
    expect(theChiPhi.querySelector('polyline')).toBeNull()
    // Chia cho 0 ra `NaN` và SVG lặng lẽ không vẽ — cổng này phân biệt «không
    // vẽ vì đã quyết định» với «không vẽ vì toạ độ hỏng».
    expect(theChiPhi.innerHTML).not.toContain('NaN')
  })

  it('thanh xếp lớp: ba đoạn, bề rộng ĐÚNG tỉ lệ in/out/cache', async () => {
    datApi()
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    const doan = [...the('Token').querySelectorAll<HTMLElement>('span[style*="width"]')]
    expect(doan).toHaveLength(3)

    const tong = CO_SO.input_tokens + CO_SO.output_tokens + CO_SO.cache_read_tokens
    const pc = (v: number) => `${((v / tong) * 100).toFixed(2)}%`
    expect(doan.map((d) => d.style.width)).toEqual([
      pc(CO_SO.input_tokens),
      pc(CO_SO.output_tokens),
      pc(CO_SO.cache_read_tokens),
    ])
    // Màu KHOÁ THEO LOẠI, không theo thứ hạng: đậm nhất luôn là input, bất kể
    // kỳ nào. Ngược với thang `--comp-*` của mục ② (nhạt dần theo thứ hạng).
    expect(doan.map((d) => d.className)).toEqual([
      expect.stringContaining('bg-ac'),
      expect.stringContaining('bg-ac/60'),
      expect.stringContaining('bg-ac/30'),
    ])
  })

  it('kỳ không có token nào ⇒ không có thanh (chia cho 0)', async () => {
    datApi({ input_tokens: 0, output_tokens: 0, cache_read_tokens: 0 })
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    expect(the('Token').querySelectorAll('span[style*="width"]')).toHaveLength(0)
    // Thẻ vẫn còn và vẫn nói 0 — mất thanh, không mất thẻ. Nhắm vào CON SỐ LỚN
    // (`<p>` đầu thẻ) chứ không `getByText('0')`: dòng chân lúc này cũng là
    // `in 0 · out 0 · cache read 0`, nên một phép tìm theo chữ khớp bốn chỗ.
    expect(the('Token').querySelector('p')?.textContent).toBe('0')
  })

  it('KHÔNG thẻ nào có hover hay transition (người dùng chốt khi xem demo)', async () => {
    datApi()
    boot()
    await screen.findByRole('heading', { name: 'Tổng chi phí' })

    // Thẻ KPI không bấm được; nhấc lên hay đổ bóng khi rê chuột là hứa một cú
    // bấm không tồn tại. jsdom không rê chuột được nên cổng này đọc CLASS.
    for (const nhan of ['Tổng chi phí', 'Token', 'Phiên hội thoại', 'Thời lượng gọi']) {
      const cls = the(nhan).className
      expect(cls, `thẻ «${nhan}» có hover:`).not.toMatch(/hover:/)
      expect(cls, `thẻ «${nhan}» có transition`).not.toMatch(/transition|duration-/)
    }
  })
})

/**
 * KÝ HIỆU MŨ TỪ BE — `"0E-10"`, không phải `"0"`.
 *
 * Mọi fixture phía trên viết tiền 0 là chuỗi `'0'`, và đó chính là dạng mà API
 * THẬT gần như không bao giờ trả: `sum(amount)` trên cột `numeric(20,10)` ra
 * `Decimal('0E-10')`, và Pydantic serialize nó bằng `str()` thành `"0E-10"`.
 * Chỉ khi KHÔNG có dòng `rated_usage` nào thì `COALESCE(..., 0)` mới ra `"0"`.
 *
 * Bảng giá MẶC ĐỊNH (`0949_seed_bang_gia_mac_dinh`) khai `unit_price = 0` cho
 * `vad.audio_sec`, và `billing.rate_usage()` chỉ lọc `qty > 0` — nên mọi phiên
 * voice đều sinh dòng tiền 0 cho `vad`. Hai bài dưới đây là đường đi thật của
 * cấu hình mặc định, không phải ca biên dựng tay.
 */
describe('tiền dạng mũ "0E-10" từ API thật', () => {
  it('hàng component tiền 0 dựng được — không làm sập cả màn', async () => {
    datApi()
    datApiPhanTich({
      theo_component: CO_SO_PHAN_TICH.theo_component.map((d) =>
        d.component === 'vad' ? { ...d, chi_phi: '0E-10' } : d,
      ),
    })
    boot()

    await screen.findByText('Chi phí theo ngày')
    // `within` thẻ «Theo từng dịch vụ»: từ 2026-08-25 bảng ③ cũng có cột «VAD».
    const the = screen.getByRole('heading', { name: 'Theo từng dịch vụ' }).closest('div')!
      .parentElement as HTMLElement
    expect(within(the).getByText('VAD')).toBeInTheDocument()
    expect(within(the).getByText('không tính tiền')).toBeInTheDocument()
    // Hai thẻ kia vẫn đọc được — màn không rơi vào nhánh lỗi.
    expect(screen.getByText('Chi phí theo ngày')).toBeInTheDocument()
  })
})
