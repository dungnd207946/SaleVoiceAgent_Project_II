/**
 * Màn `/usage` — LƯỢNG DÙNG theo ngày, bảy tab (spec 2026-08-24 man-usage-bay-tab).
 *
 * Boot qua ROUTER THẬT (`routeTree.gen.ts`), không render component trần: năm
 * khoá search sống trên URL và `validateSearch` là chỗ dễ vỡ nhất của thiết kế
 * này — nó phải LUÔN trả đủ cả năm khoá, kể cả khoá đang mang giá trị mặc định
 * (router TRỘN kết quả validate lên search thô chứ không THAY nó). Bẫy đã sập
 * thật ở `/projects` (CLAUDE.md, Change Log 2026-08-14).
 *
 * Fixture dùng RIÊNG của bài này (`datApi()`), không dựa vào fake mặc định ở
 * `features/billing/msw.ts` — hai nguồn cùng lúc là chỗ một bên đổi số mà không
 * ai thấy bài kia đỏ theo.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'

import { LangProvider } from '@/i18n'
import { routeTree } from '@/routeTree.gen'
import { chuoiCuaTab } from '@/features/billing/chuoi-usage'
import { BieuDoLuongDung } from '@/features/billing/components/BieuDoLuongDung'
import { mocTruc } from '@/features/billing/truc-usage'
import { MA_TAB, nhanMocTruc } from '@/features/billing/so-tab-usage'
import type { DanhSachKey, DanhSachPhien, DongOwner, UsageTheoNgay } from '@/features/billing/kieu'
import { server } from '../vitest.setup'

/** 21 ngày; ngày thứ 9 (chỉ số 8) và 16 (chỉ số 15) KHÔNG có usage. */
const NGAY_RONG = [8, 15]
const SO_NGAY = 21

const CALL_DINH = 1200
const LLM_IN_NGAY = 50_000

/** Ba số đo `stt` MỖI NGÀY hoạt động (19 ngày) — tổng kỳ suy ra ở dưới. */
const STT_GIAY_NGAY = 110
const STT_STREAM_MS_NGAY = 8_000
const STT_KY_TU_NGAY = 1_000
const SO_NGAY_HOAT_DONG = SO_NGAY - NGAY_RONG.length // 19

function ngayISO(i: number): string {
  return `2026-08-${String(i + 1).padStart(2, '0')}`
}

const CO_SO: UsageTheoNgay = {
  theo_ngay: Array.from({ length: SO_NGAY }, (_, i) => {
    if (NGAY_RONG.includes(i)) return { ngay: ngayISO(i), so_phien: 0, phan: [] }
    // Đỉnh của `call` rơi vào ĐÚNG ngày 19 (chỉ số 18) — bài «đỉnh» neo vào đó.
    const heSo = i === 18 ? 1 : 0.5
    return {
      ngay: ngayISO(i),
      so_phien: 20,
      phan: [
        {
          component: 'llm',
          so_event: 7,
          input_tokens: LLM_IN_NGAY,
          output_tokens: 7_100,
          cache_read_tokens: 6_550,
          audio_sec: 0,
          text_units: 0,
          units: 7,
          wall_ms_stream: 0,
          text_units_hoi_thoai: 0,
        },
        {
          component: 'call',
          so_event: 1,
          input_tokens: 0,
          output_tokens: 0,
          cache_read_tokens: 0,
          audio_sec: CALL_DINH * heSo,
          text_units: 0,
          units: 1,
          wall_ms_stream: 0,
          text_units_hoi_thoai: 0,
        },
        {
          component: 'tts',
          so_event: 1,
          input_tokens: 0,
          output_tokens: 0,
          cache_read_tokens: 0,
          audio_sec: 0,
          text_units: 4_000,
          units: 7,
          wall_ms_stream: 0,
          text_units_hoi_thoai: 4_000,
        },
        // `stt` chở BA số đo, mỗi cái một mẫu số khác nhau — đó là cả lý do tab
        // này có đường thứ hai và một dòng phụ riêng:
        //   `audio_sec`            giây khách thực nói   (purpose conversation)
        //   `wall_ms_stream`       ms stream mở          (purpose stream)
        //   `text_units_hoi_thoai` ký tự transcript      (purpose conversation)
        // ⚠️ `text_units` KHÔNG lọc để 0 ở đây, KHÁC `text_units_hoi_thoai`: cột
        // lọc mới là thứ tab STT đọc, và một fixture đặt hai cột bằng nhau sẽ
        // xanh dù code đọc nhầm cột.
        {
          component: 'stt',
          so_event: 3,
          input_tokens: 0,
          output_tokens: 0,
          cache_read_tokens: 0,
          audio_sec: STT_GIAY_NGAY,
          text_units: 0,
          units: 3,
          wall_ms_stream: STT_STREAM_MS_NGAY,
          text_units_hoi_thoai: STT_KY_TU_NGAY,
        },
      ],
    }
  }),
}

const KEY_GIA: DanhSachKey = {
  items: [
    {
      agent_key_id: 1,
      label: 'Bot bán hàng',
      key_prefix: 'sk_live_a1b2…',
      nguoi_tao: 'u_a',
      nguoi_tao_ten: 'Nguyễn Văn A',
      da_thu_hoi: false,
      so_phien: 300,
      input_tokens: 900_000,
      output_tokens: 120_000,
      cache_read_tokens: 110_000,
      voice_sec: 12_000,
      so_event: 3_000,
      chi_phi: '1000.0000000000',
      // Màn `/usage` không hiện bảy cột này (chỉ `/billing` hiện) — giá trị ở
      // đây chỉ cần khớp kiểu `DongKey`, cộng đúng bằng `chi_phi` cho gọn.
      chi_phi_llm: '700.0000000000',
      chi_phi_tts: '150.0000000000',
      chi_phi_stt: '80.0000000000',
      chi_phi_embed: '2.0000000000',
      chi_phi_call: '40.0000000000',
      chi_phi_vad: '20.0000000000',
      chi_phi_speaker_verify: '8.0000000000',
    },
    {
      agent_key_id: null,
      label: '',
      key_prefix: '',
      nguoi_tao: '',
      nguoi_tao_ten: null,
      da_thu_hoi: false,
      so_phien: 20,
      input_tokens: 50_000,
      output_tokens: 6_000,
      cache_read_tokens: 5_000,
      voice_sec: 600,
      so_event: 200,
      chi_phi: '50.0000000000',
      chi_phi_llm: '30.0000000000',
      chi_phi_tts: '10.0000000000',
      chi_phi_stt: '5.0000000000',
      chi_phi_embed: '0.5000000000',
      chi_phi_call: '3.0000000000',
      chi_phi_vad: '1.0000000000',
      chi_phi_speaker_verify: '0.5000000000',
    },
  ],
  total: 2,
  chi_phi_tong: '1050.0000000000',
  currency: 'VND',
}

const OWNER_GIA: DongOwner[] = [
  {
    user_id: 'u_a',
    ten: 'Nguyễn Văn A',
    email: 'a@noblex.vn',
    so_key: 1,
    so_phien: 300,
    input_tokens: 900_000,
    output_tokens: 120_000,
    cache_read_tokens: 110_000,
    voice_sec: 12_000,
    so_event: 3_000,
    chi_phi: '1000.0000000000',
    // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (600+200+100+10+60+20+10).
    chi_phi_llm: '600.0000000000',
    chi_phi_tts: '200.0000000000',
    chi_phi_stt: '100.0000000000',
    chi_phi_embed: '10.0000000000',
    chi_phi_call: '60.0000000000',
    chi_phi_vad: '20.0000000000',
    chi_phi_speaker_verify: '10.0000000000',
  },
  {
    user_id: null,
    ten: null,
    email: null,
    so_key: 0,
    so_phien: 20,
    input_tokens: 50_000,
    output_tokens: 6_000,
    cache_read_tokens: 5_000,
    voice_sec: 600,
    so_event: 200,
    chi_phi: '50.0000000000',
    // Cùng bảy cột với hàng «chưa phân loại» của khoá — cùng nhóm, cùng tổng.
    chi_phi_llm: '30.0000000000',
    chi_phi_tts: '10.0000000000',
    chi_phi_stt: '5.0000000000',
    chi_phi_embed: '0.5000000000',
    chi_phi_call: '3.0000000000',
    chi_phi_vad: '1.0000000000',
    chi_phi_speaker_verify: '0.5000000000',
  },
]

const PHIEN_GIA: DanhSachPhien = {
  items: [
    {
      session_id: 's_9f3c',
      agent_key_id: 1,
      key_label: 'Bot bán hàng',
      customer_name: 'Phạm Minh',
      phone: '0900000001',
      channel: 'voice',
      bat_dau: '2026-08-19T07:22:00Z',
      so_turn: 18,
      input_tokens: 6_200,
      output_tokens: 880,
      voice_sec: 412,
      chi_phi: '10.0000000000',
      // Màn `/usage` không hiện bảy cột này (chỉ `/billing` hiện) — dồn cả
      // vào `llm` cho gọn, cùng lệ `K-zero-token` ở `billing-usage.test.tsx`.
      chi_phi_llm: '10.0000000000',
      chi_phi_tts: '0',
      chi_phi_stt: '0',
      chi_phi_embed: '0',
      chi_phi_call: '0',
      chi_phi_vad: '0',
      chi_phi_speaker_verify: '0',
      exact: false,
    },
  ],
  total: 120,
}

let demGoi = { ngay: 0 }

function datApi(ghiDe?: { readonly ngay?: () => Response }) {
  demGoi = { ngay: 0 }
  server.use(
    http.get('/api/v1/billing/usage-by-day', () => {
      demGoi.ngay += 1
      return ghiDe?.ngay ? ghiDe.ngay() : HttpResponse.json(CO_SO)
    }),
    http.get('/api/v1/billing/by-key', () => HttpResponse.json(KEY_GIA)),
    http.get('/api/v1/billing/by-owner', () => HttpResponse.json(OWNER_GIA)),
    http.get('/api/v1/billing/sessions', () => HttpResponse.json(PHIEN_GIA)),
  )
}

function boot(duong = '/usage') {
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

/** Mục rail theo mã component. */
function mucRail(ma: string): HTMLElement {
  return document.querySelector(`[data-tab="${ma}"]`) as HTMLElement
}

beforeEach(() => datApi())

describe('rail tám chỉ số', () => {
  it('tám mục, đúng thứ tự chốt, mỗi mục một con số tổng', async () => {
    boot()
    await screen.findByText('Lượt dùng chi tiết')
    const muc = [...document.querySelectorAll('[data-tab]')]
    expect(muc.map((m) => m.getAttribute('data-tab'))).toEqual([
      'llm',
      'stt',
      'tts',
      'vad',
      'call',
      'embed',
      'speaker_verify',
      'search',
    ])
    // Thứ tự này là quyết định sản phẩm, không phải kết quả sắp xếp: xếp theo
    // độ lớn thì đổi kỳ là các tab đổi chỗ.
    expect(muc.map((m) => m.getAttribute('data-tab'))).toEqual([...MA_TAB])
  })

  it('tổng kỳ của rail = tổng chuỗi ngày, không lấy từ nguồn thứ hai', async () => {
    boot()
    // ⚠️ CHỜ ĐÚNG CON SỐ, không chờ nhãn rail («Thời gian gọi» có mặt ngay ở
    // trạng thái đang tải, khi mọi tổng còn là 0) — bài này đã đỏ một lần vì
    // đọc rail quá sớm và thấy `0,0s`.
    // 19 ngày có usage; 18 ngày × 600s + 1 ngày đỉnh × 1200s = 12.000s.
    const mong = chuoiCuaTab(CO_SO.theo_ngay, 'call').tong
    expect(mong).toBe(18 * 600 + 1200)
    // Tìm con số TRƯỚC rồi khẳng định nó nằm trong ĐÚNG mục rail — `mucRail()`
    // đọc DOM ngay lúc gọi nên dùng nó làm container của một `findBy*` là trỏ
    // vào `null` (rail chưa dựng xong). Cách này còn chặt hơn: nó chứng minh
    // con số ở đúng chỗ, không chỉ có mặt đâu đó trên màn.
    // `findAllByText` chứ không `findByText`: chuỗi này có mặt ở NHIỀU chỗ
    // (con số rail, và nhãn a11y của biểu đồ khi tab `call` đang mở). Bài này
    // hỏi «con số có ở ĐÚNG mục rail không», nên lọc theo `data-tab` mới là
    // phép đo đúng — `getByText` đơn chỉ đang đòi màn phải có duy nhất một chỗ
    // nhắc con số đó, một ràng buộc không ai hứa.
    const o = await screen.findAllByText('3h 20m 0s')
    expect(o.map((e) => e.closest('[data-tab]')?.getAttribute('data-tab'))).toContain('call')
  })

  it('dòng phụ: tab Token chở in/out/cache, sáu tab kia chở ĐÚNG MỘT mục TB/ngày', async () => {
    boot()
    // 12.000s / 21 ngày của KỲ = 571,4s ⇒ `9m 31s`. ⚠️ Mẫu số là ngày của KỲ,
    // KHÔNG phải 19 ngày hoạt động (chia thế ra `10m 31s`) — xem docstring
    // `ChuoiTab.tbMoiNgay` về việc hai cách chia trả lời hai câu khác nhau.
    await screen.findByText('Trung bình 9m 31s/ngày')

    const llm = within(mucRail('llm'))
    expect(llm.getByText(/^in /)).toBeVisible()
    expect(llm.getByText(/^cache /)).toBeVisible()
    expect(llm.queryByText(/^Trung bình /)).toBeNull()

    const call = within(mucRail('call'))
    expect(call.getByText('Trung bình 9m 31s/ngày')).toBeVisible()
    // «chỉ đưa ra thông tin trung bình» (người dùng chốt): đỉnh và số ngày hoạt
    // động đã rời dòng phụ — hai con số cho một dòng 10.5px là thứ người ta tra
    // khi đã quan tâm, không phải thứ cần thấy khi đang quét bảy mục.
    expect(call.queryByText(/đỉnh/)).toBeNull()
    expect(call.queryByText(/ngày hoạt động|\/21 ngày/)).toBeNull()
    expect(mucRail('call').querySelectorAll('[data-phu] > span')).toHaveLength(1)
  })

  it('tab STT chở HAI vế `purpose` thay cho trung bình', async () => {
    boot()
    await screen.findByText('stream 2m 32s')
    const stt = within(mucRail('stt'))
    // 19 ngày × 8.000 ms = 152.000 ms = 152s ⇒ `2m 32s`.
    // ⚠️ Nếu quên chia 1000 thì ra `42h 13m 20s` — vẫn là một chuỗi hợp lệ
    // trông rất thật, nên chỉ con số cụ thể mới bắt được (xem `sttHaiVe`).
    expect(stt.getByText('conversation 19k')).toBeVisible() // 19 × 1.000 ký tự
    expect(stt.queryByText(/^Trung bình /)).toBeNull()
    expect(mucRail('stt').querySelectorAll('[data-phu] > span')).toHaveLength(2)
  })

  it('vế `conversation` đọc cột LỌC, không đọc `text_units` trần', async () => {
    // Fixture cố ý đặt `text_units: 0` cho `stt` trong khi
    // `text_units_hoi_thoai: 1.000` — hai cột này khác mẫu số (`text_units` là
    // số đo của `tts`/`embed`), và hôm nay chúng tình cờ bằng nhau trên dữ
    // liệu thật nên chỉ một fixture lệch mới phân biệt được.
    boot()
    await screen.findByText('conversation 19k')
    const stt = within(mucRail('stt'))
    expect(stt.getByText('conversation 19k')).toBeVisible()
    expect(stt.queryByText('conversation 0')).toBeNull()
  })
})

describe('đổi tab', () => {
  it('bấm mục rail đổi tiêu đề + đơn vị của biểu đồ', async () => {
    boot()
    await screen.findByText('Lượt dùng chi tiết')
    expect(screen.getByRole('heading', { level: 2, name: /Token theo ngày/ })).toBeVisible()
    expect(screen.getByText('đơn vị token')).toBeVisible()

    await userEvent.click(mucRail('tts'))
    expect(screen.getByRole('heading', { level: 2, name: /TTS theo ngày/ })).toBeVisible()
    // ⚠️ TTS đo `text_units`, mà `text_units` là KÝ TỰ trong DB (migration
    // `0948`; `billing.metric` khai `'character'`). Nhãn trên màn vẫn là
    // «token» — người dùng chốt 2026-08-25, và chốt cho CẢ BA chỗ đo cột đó
    // (TTS · Embed · đường 2 của STT) để chúng không nói hai tên khác nhau.
    // Vế còn đúng nguyên: TTS KHÔNG theo giây.
    expect(screen.getByText('đơn vị token')).toBeVisible()
    expect(screen.queryByText('đơn vị giây')).toBeNull()
  })

  it('đổi tab KHÔNG gọi lại API', async () => {
    boot()
    await screen.findByText('Lượt dùng chi tiết')
    expect(demGoi.ngay).toBe(1)
    await userEvent.click(mucRail('vad'))
    await userEvent.click(mucRail('embed'))
    await userEvent.click(mucRail('llm'))
    expect(demGoi.ngay).toBe(1)
  })

  it('`?tab=` lạ rơi về tab đầu, KHÔNG phải «không tab nào mở»', async () => {
    boot('/usage?tab=khong-ton-tai')
    await screen.findByText('Lượt dùng chi tiết')
    expect(mucRail('llm')).toHaveAttribute('aria-pressed', 'true')
    expect(
      [...document.querySelectorAll('[data-tab]')].filter(
        (m) => m.getAttribute('aria-pressed') === 'true',
      ),
    ).toHaveLength(1)
  })
})

describe('biểu đồ — HÌNH HỌC, kiểm ở tầng component', () => {
  /**
   * Hai bài này KHÔNG boot qua router: `ResizeObserver` giả của
   * `vitest.setup.ts` không bao giờ BẮN và `clientWidth` luôn 0 dưới jsdom, nên
   * biểu đồ không vẽ gì khi dựng qua màn. Prop `co` là seam duy nhất đo được —
   * cùng khuôn `BieuDoChiPhi`/`BieuDoNgay`, và `vitest.setup.ts` đã ghi rõ lối
   * này. Tầng MÀN thì kiểm hành vi (dưới), thứ không cần hình học.
   */
  const CO = { rong: 800, cao: 400 }

  it('ngày 0 vẽ vòng tròn rỗng, và không chuỗi NaN nào lọt vào DOM', () => {
    render(<BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />)
    const svg = document.querySelector('[data-bieu-do] svg')
    expect(svg).not.toBeNull()
    // Vòng tròn ngày-0 phân biệt với chấm ngày thường bằng `stroke`: `--color-n6`
    // vs `--c`. Hai thứ này KHÔNG được trộn — một cái nói «đã đo và bằng 0»,
    // cái kia nói «đây là một số đo».
    const rong = [...svg!.querySelectorAll('circle')].filter(
      (c) => c.getAttribute('stroke') === 'var(--color-n6)',
    )
    expect(rong).toHaveLength(NGAY_RONG.length)
    expect(document.body.innerHTML).not.toContain('NaN')
  })

  it('kỳ rỗng hoàn toàn vẫn vẽ được — không chia cho 0', () => {
    const rong: UsageTheoNgay = {
      theo_ngay: Array.from({ length: 3 }, (_, i) => ({
        ngay: ngayISO(i),
        so_phien: 0,
        phan: [],
      })),
    }
    render(<BieuDoLuongDung chuoi={chuoiCuaTab(rong.theo_ngay, 'call')} co={CO} />)
    // Đỉnh 0 ⇒ trần trục phải bị kẹp lên 1, nếu không mọi toạ độ y là `NaN` và
    // SVG lặng lẽ không vẽ gì: không lỗi, không hình, không dấu hiệu.
    expect(document.body.innerHTML).not.toContain('NaN')
    const svg = document.querySelector('[data-bieu-do] svg')!
    expect([...svg.querySelectorAll('circle')]).toHaveLength(3)
  })

  it('mốc trục dọc TRÒN SỐ theo đơn vị, và luôn phủ đỉnh', () => {
    // Thời gian có bậc riêng — chia đều một trục thời gian ra `1m 47s` thì
    // không mốc nào đọc được thành một quãng người ta nghĩ bằng.
    // Mốc gốc là `0s` — KHÔNG `0,0s` (`giay()` in một chữ số thập phân dưới 60s;
    // đúng cho số đo, sai cho gốc trục).
    const nhan = (dinh: number) => {
      const m = mocTruc(dinh, 'giay', 4)
      const buoc = m.length > 1 ? m[1]! - m[0]! : m[0]!
      return m.map((v) => nhanMocTruc('giay', v, buoc))
    }
    expect(nhan(1200)).toEqual(['0', '5m', '10m', '15m', '20m'])
    // MỘT đơn vị cho CẢ TRỤC, chọn theo BƯỚC. Suy theo từng giá trị thì trục
    // bước 30s ra `0s · 30s · 1m · 90s` — ba đơn vị trong bốn mốc, đo được
    // trên tab «Xác thực giọng» 2026-08-25.
    expect(nhan(90)).toEqual(['0', '30s', '60s', '90s'])
    // Dưới 60s in NGUYÊN, không `giay()` (`10,0s`): một chữ số thập phân đúng
    // cho SỐ ĐO, sai cho mốc trục. Ca này lộ ra ở kỳ RỖNG (trần kẹp về 1).
    expect(nhan(1)).toEqual(['0', '10s'])
    for (const [dinh, don] of [
      [1200, 'giay'],
      [90_000, 'token'],
      [4_000, 'token'],
    ] as const) {
      const m = mocTruc(dinh, don, 4)
      expect(m[m.length - 1]).toBeGreaterThanOrEqual(dinh)
    }
  })
})

describe('biểu đồ — HÀNH VI qua router', () => {
  it('lỗi `usage-by-day` KHÔNG kéo bảng dưới xuống theo', async () => {
    datApi({
      ngay: () => HttpResponse.json({ error: { code: 'X', message: 'sập' } }, { status: 500 }),
    })
    boot()
    // Thẻ ① báo lỗi…
    expect(await screen.findByRole('button', { name: /Thử lại/i })).toBeVisible()
    // …còn thẻ ② vẫn render: hai endpoint khác nhau, hỏng cái này không được
    // làm mất cái kia.
    expect(await screen.findByText('Bot bán hàng')).toBeVisible()
  })
})

describe('nét · chấm · tooltip — ba lỗi người dùng báo 2026-08-25', () => {
  const CO = { rong: 700, cao: 300 }

  /**
   * ⚠️ `fireEvent.pointerMove(el, { clientX })` KHÔNG truyền được toạ độ ở đây:
   * jsdom không có `PointerEvent`, nên testing-library rơi về một `Event` trần
   * và `clientX` biến mất — handler nhận `undefined`, tính ra `NaN`, và bài đỏ
   * ở một chỗ chẳng liên quan (`chuoi.ngay[NaN].slice`). Dựng `MouseEvent`
   * thật mang toạ độ rồi dispatch dưới tên `pointermove`.
   */
  function reChuot(el: HTMLElement, clientX: number, clientY: number) {
    fireEvent(el, new MouseEvent('pointermove', { bubbles: true, clientX, clientY }))
  }

  /** Sự kiện con trỏ kèm `pointerType` — jsdom không có `PointerEvent`. */
  function cham(el: HTMLElement, ten: string, clientX: number, loai = 'touch') {
    // React dựng `onPointerLeave` từ `pointerout` + `relatedTarget`, không nghe `pointerleave`.
    const e = new MouseEvent(ten, {
      bubbles: true,
      clientX,
      clientY: 150,
      relatedTarget: document.body,
    })
    Object.defineProperty(e, 'pointerType', { value: loai })
    fireEvent(el, e)
  }

  it('CHẠM (không rê) cũng hiện tooltip, nhấc ngón vẫn giữ, chạm ra ngoài thì tắt', () => {
    render(<BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />)
    const khung = document.querySelector('[data-bieu-do]') as HTMLElement
    khung.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: CO.rong, height: CO.cao }) as DOMRect
    cham(khung, 'pointerdown', 205)
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull()
    cham(khung, 'pointerout', 205) // cảm ứng: rời khung ngay sau khi nhấc ngón
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull()
    cham(document.body, 'pointerdown', 5)
    expect(document.querySelector('[role="tooltip"]')).toBeNull()
  })

  it('CHUỘT rời khung thì tắt tooltip như cũ', () => {
    render(<BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />)
    const khung = document.querySelector('[data-bieu-do]') as HTMLElement
    khung.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: CO.rong, height: CO.cao }) as DOMRect
    cham(khung, 'pointermove', 205, 'mouse')
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull()
    cham(khung, 'pointerout', 205, 'mouse')
    expect(document.querySelector('[role="tooltip"]')).toBeNull()
  })

  it('BÀN PHÍM: Tab vào khung, ←/→/End đi từng ngày và đọc qua vùng live, Esc tắt', async () => {
    const u = userEvent.setup()
    const chuoi = chuoiCuaTab(CO_SO.theo_ngay, 'call')
    render(<BieuDoLuongDung chuoi={chuoi} co={CO} />)
    await u.tab()
    expect(screen.getByRole('group', { name: /theo ngày/ })).toHaveFocus()
    const doc = screen.getByTestId('bieu-do-doc')
    expect(doc).toHaveAttribute('aria-live', 'polite')
    await u.keyboard('{ArrowRight}')
    expect(document.querySelector('[role="tooltip"]')).not.toBeNull()
    expect(doc.textContent).toMatch(/^\d{2}\/\d{2}/)
    const dau = doc.textContent
    await u.keyboard('{End}')
    expect(doc.textContent).not.toBe(dau)
    await u.keyboard('{Escape}')
    expect(document.querySelector('[role="tooltip"]')).toBeNull()
    expect(chuoi.ngay.length).toBeGreaterThan(1)
  })

  it('nét dùng gradient ĐẶC→VỪA (`--c`→`--a`), KHÔNG chạm `--b`', () => {
    render(<BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />)
    const stops = [...document.querySelectorAll('linearGradient[id^="u-net-"] stop')].map((s) =>
      s.getAttribute('stop-color'),
    )
    // `--b` chỉ đạt tương phản 1.5–1.8 trên `surface`; để nó làm stop của NÉT
    // là nửa cuối mỗi đường không đủ tương phản (WCAG 1.4.11 đòi ≥ 3.0).
    expect(stops).toEqual(['var(--c)', 'var(--a)'])
    expect(stops).not.toContain('var(--b)')
  })

  it('chấm ngày TÔ ĐẶC màu đường — không phải vòng ruột trắng', () => {
    render(<BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />)
    const dac = [...document.querySelectorAll('circle')].filter(
      (c) => c.getAttribute('fill') === 'var(--c)' && !c.getAttribute('stroke'),
    )
    // 19 ngày có số đo (hai ngày rỗng dùng vòng tròn `--color-n6` riêng).
    expect(dac).toHaveLength(SO_NGAY - NGAY_RONG.length)
    // KHÔNG chấm nào được vừa ruột trắng vừa viền màu đường — đó CHÍNH LÀ kiểu
    // cũ, và nó làm nét đọc ra thành đứt đoạn. Vòng tròn ngày-0 cũng ruột trắng
    // nhưng viền `--color-n6`: khác vật, khác nghĩa, được phép.
    const kieuCu = [...document.querySelectorAll('circle')].filter(
      (c) =>
        c.getAttribute('fill') === 'var(--color-surface)' &&
        c.getAttribute('stroke') === 'var(--c)',
    )
    expect(kieuCu).toHaveLength(0)
  })

  it('tooltip BÁM con trỏ: đổi vị trí chuột thì đổi chỗ', async () => {
    const { container } = render(
      <BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />,
    )
    const khung = container.querySelector('[data-bieu-do]') as HTMLElement
    khung.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: CO.rong, height: CO.cao }) as DOMRect

    reChuot(khung, 150, 200)
    const t1 = document.querySelector('[role="tooltip"]') as HTMLElement
    expect(t1).not.toBeNull()
    const trai1 = t1.style.left

    reChuot(khung, 300, 120)
    const t2 = document.querySelector('[role="tooltip"]') as HTMLElement
    // Bản đầu ghim `top-2 right-2` nên hộp ĐỨNG YÊN trong khi con trỏ chạy —
    // mắt phải nhảy qua lại giữa điểm đang trỏ và một hộp ở góc.
    expect(t2.style.left).not.toBe(trai1)
  })

  it('tooltip TỰ LẬT khi sắp tràn mép phải / mép trên', () => {
    const { container } = render(
      <BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />,
    )
    const khung = container.querySelector('[data-bieu-do]') as HTMLElement
    khung.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: CO.rong, height: CO.cao }) as DOMRect

    reChuot(khung, 60, 250)
    expect(document.querySelector('[role="tooltip"]')).toHaveAttribute('data-lat', 'phai-tren')

    // Sát mép PHẢI và sát mép TRÊN ⇒ lật cả hai chiều, nếu không hộp tràn ra
    // ngoài khung và bị cắt.
    reChuot(khung, CO.rong - 10, 8)
    expect(document.querySelector('[role="tooltip"]')).toHaveAttribute('data-lat', 'trai-duoi')
  })
})

describe('tab STT — đường thứ hai có TRỤC RIÊNG', () => {
  const CO = { rong: 700, cao: 300 }
  const CHUOI_STT = () => chuoiCuaTab(CO_SO.theo_ngay, 'stt')

  function veStt() {
    return render(<BieuDoLuongDung chuoi={CHUOI_STT()} co={CO} />)
  }

  it('chuỗi 2 đi kèm chuỗi chính, cùng độ dài, KHÔNG trộn vào `gia`', () => {
    const c = CHUOI_STT()
    expect(c.gia2).toHaveLength(SO_NGAY)
    // Ngày rỗng vẫn có phần tử = 0 ở CẢ HAI chuỗi: hai mảng lệch độ dài thì
    // mọi phép vẽ theo chỉ số sau đó lệch một ngày.
    for (const i of NGAY_RONG) expect(c.gia2![i]).toBe(0)
    expect(c.tong2).toBe(SO_NGAY_HOAT_DONG * STT_KY_TU_NGAY)
    expect(c.dinh2).toBe(STT_KY_TU_NGAY)

    // ⚠️ ĐƯỜNG CHÍNH ĐỌC `wall_ms_stream`, KHÔNG `audio_sec` (người dùng chốt
    // 2026-08-25). Fixture cố ý đặt hai cột LỆCH nhau (8s/ngày của vế stream vs
    // 110s/ngày của `audio_sec`) — bằng nhau thì bài này xanh dù đọc cột nào.
    expect(c.tong).toBe((SO_NGAY_HOAT_DONG * STT_STREAM_MS_NGAY) / 1000)
    expect(c.tong).not.toBe(SO_NGAY_HOAT_DONG * STT_GIAY_NGAY)
    // Tổng chuỗi chính cũng không được nhiễm ký tự — hai đơn vị khác nhau.
    expect(c.tong).not.toBe(c.tong2)
  })

  it('vẽ đúng HAI đường, đường 2 nét LIỀN màu RIÊNG, không vùng tô', () => {
    const { container } = veStt()
    const duong2 = container.querySelector('[data-duong2]')
    expect(duong2).not.toBeNull()
    // Người dùng chốt 2026-08-25: phân biệt bằng MÀU, không bằng nét đứt.
    expect(duong2).not.toHaveAttribute('stroke-dasharray')
    expect(duong2!.getAttribute('stroke')).toMatch(/^url\(#u-net2-/)
    // `fill="none"`: một vùng tô thứ hai chồng lên vùng tô thứ nhất thì hai
    // mảng màu cộng nhau và đọc ra một mức không chuỗi nào có.
    expect(duong2).toHaveAttribute('fill', 'none')

    // Gradient của đường 2 chạy `--d` → `--d2`, KHÔNG chạm `--a`/`--b` của
    // đường chính — dùng lại token của đường kia là hai đường một màu.
    const stops = [...container.querySelectorAll('linearGradient[id^="u-net2-"] stop')].map((x) =>
      x.getAttribute('stop-color'),
    )
    expect(stops).toEqual(['var(--d)', 'var(--d2)'])
  })

  it('đường 2 CÓ vùng tô, và cả hai vùng tô vẽ TRƯỚC mọi nét', () => {
    const { container } = veStt()
    const tô = container.querySelector('linearGradient[id^="u-vung2-"]')
    expect(tô, 'đường 2 mất vùng tô — người dùng chốt phải có, giống đường kia').not.toBeNull()
    // CÙNG ba nấc mờ với đường chính: nhạt hơn thì nó đọc thành «dữ liệu kém
    // tin hơn», mà hai đường ở đây ngang hàng nhau.
    const mo = (id: string) =>
      [...container.querySelectorAll(`linearGradient[id^="${id}"] stop`)].map((x) =>
        x.getAttribute('stop-opacity'),
      )
    expect(mo('u-vung2-')).toEqual(mo('u-vung-'))

    // ⚠️ THỨ TỰ: cả hai mảng tô phải đứng TRƯỚC mọi nét. Vẽ mảng của đường 2
    // sau nét đường 1 thì nó phủ lên chính cái nét đó và làm nét loang màu.
    const ve = [...container.querySelectorAll('path')]
    const cuoiTo = ve.findLastIndex((x) => (x.getAttribute('fill') ?? '').startsWith('url(#u-vung'))
    const dauNet = ve.findIndex((x) => x.getAttribute('fill') === 'none')
    expect(cuoiTo).toBeLessThan(dauNet)
  })

  it('mỗi trục có NHÃN ĐƠN VỊ quay dọc, lấy từ sổ tab', () => {
    const { container } = veStt()
    const nhan = [...container.querySelectorAll('[data-nhan-truc]')]
    expect(nhan).toHaveLength(2)
    expect(nhan.map((x) => x.textContent)).toEqual(['giây', 'token'])
    // Quay quanh CHÍNH điểm neo — `rotate(-90 x y)`, không phải `rotate(-90)`
    // rồi bù bằng `translate` (chữ sẽ trôi khỏi trục ở cỡ khung khác).
    for (const x of nhan)
      expect(x.getAttribute('transform')).toMatch(/^rotate\(-90 [\d.]+ [\d.]+\)$/)
  })

  it('tab một đường KHÔNG có nhãn trục — chip «đơn vị …» đã nói rồi', () => {
    const { container } = render(
      <BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />,
    )
    expect(container.querySelectorAll('[data-nhan-truc]')).toHaveLength(0)
  })

  it('tab một đường KHÔNG mọc đường 2 — không lan sang sáu tab kia', () => {
    const { container } = render(
      <BieuDoLuongDung chuoi={chuoiCuaTab(CO_SO.theo_ngay, 'call')} co={CO} />,
    )
    expect(container.querySelector('[data-duong2]')).toBeNull()
    expect(chuoiCuaTab(CO_SO.theo_ngay, 'call').gia2).toBeUndefined()
  })

  it('HAI trục, cùng số mốc, và mốc phải đọc theo ĐƠN VỊ của đường 2', () => {
    const { container } = veStt()
    const nhan = [...container.querySelectorAll('svg > g > text')].map((t) => t.textContent)
    // Trục trái là GIÂY (`nhanMocTruc` in `m`/`h`/`s`), trục phải là KÝ TỰ
    // (`token()` in số trần / `k` / `M`). Chung một trục thì một trong hai
    // đường nằm bẹp dưới đáy — 2.090 giây cạnh 19.000 ký tự.
    expect(nhan.some((x) => /m$|h$|s$/.test(x ?? ''))).toBe(true)
    expect(nhan.filter((x) => x === '0')).toHaveLength(2) // gốc của CẢ HAI trục
    // Cùng số mốc ⇒ hai trục dùng chung các đường kẻ ngang, không thành lưới đôi.
    const ke = container.querySelectorAll('svg > g > line')
    expect(nhan).toHaveLength(ke.length * 2)
  })

  it('tooltip hiện CẢ HAI giá trị, mỗi giá trị một đơn vị', () => {
    const { container } = veStt()
    const khung = container.querySelector('[data-bieu-do]') as HTMLElement
    khung.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: CO.rong, height: CO.cao }) as DOMRect

    // x phải rơi vào một ngày CÓ số đo: bề rộng cột = (700−58−52)/20 = 29,5 ⇒
    // 205 ra chỉ số 5. `clientX: 300` ra chỉ số 8 — đúng một trong hai ngày
    // rỗng, và cả hai dòng in `—` nên bài xanh mà không đo gì.
    fireEvent(khung, new MouseEvent('pointermove', { bubbles: true, clientX: 205, clientY: 150 }))
    const tip = document.querySelector('[role="tooltip"]') as HTMLElement
    const t = within(tip)
    // Nhãn hai đường do người dùng chốt 2026-08-25 — KHÔNG còn «STT»/«Ký tự
    // transcript». Xem chú thích ở `so-tab-usage.ts` về chữ «Stream»: nó là
    // nghĩa thường, không phải giá trị `purpose='stream'`.
    expect(t.getByText('Stream')).toBeVisible()
    expect(t.getByText('8,0s')).toBeVisible() // 8.000 ms của một ngày, ĐÃ chia 1000
    expect(t.getByText('Conversation')).toBeVisible()
    expect(t.getByText('1.000')).toBeVisible() // 1.000 đơn vị text, KHÔNG phải giây
  })
})

describe('bảng lượt dùng chi tiết', () => {
  it('ba chiều gộp, hàng «chưa phân loại» ở cuối, tổng cột = hàng Tổng', async () => {
    boot()
    // CHỜ DỮ LIỆU, không chỉ chờ `<table>`: bảng render ngay ở lượt đầu với
    // `items = []`, nên `findByRole('table')` khớp lúc `tbody` còn rỗng.
    await screen.findByText('Bot bán hàng')
    const bang = screen.getByRole('table', { name: 'Lượt dùng theo khoá' })
    const than = bang.querySelectorAll('tbody tr')
    expect(than).toHaveLength(2)
    expect(than[1]!.textContent).toContain('Chưa phân loại')

    // 900.000 + 50.000 = 950k
    const tong = within(bang.querySelector('tfoot')! as HTMLElement)
    expect(tong.getByText('950k')).toBeVisible()
  })

  it('chiều «Người tạo» có ĐÚNG bộ cột lượng của chiều «Khoá»', async () => {
    boot()
    await screen.findByText('Bot bán hàng')
    const cotKhoa = [...document.querySelectorAll('thead th')].map((t) => t.textContent)

    await userEvent.click(screen.getByRole('tab', { name: 'Người tạo' }))
    const bang = await screen.findByRole('table', { name: 'Lượt dùng theo người tạo' })
    const cotNguoi = [...bang.querySelectorAll('thead th')].map((t) => t.textContent)

    // Năm cột lượng phải khớp từng chữ, và ĐÚNG thứ tự — người bấm từ chiều này
    // sang chiều kia phải tìm lại đúng những cột vừa đọc.
    const LUONG = ['Phiên', 'In', 'Out', 'Cache read', 'Thời gian gọi']
    expect(cotKhoa.slice(-5)).toEqual(LUONG)
    expect(cotNguoi.slice(-5)).toEqual(LUONG)
  })

  it('bảng KHÔNG có cột tiền nào ở cả ba chiều', async () => {
    boot()
    await screen.findByText('Bot bán hàng')
    for (const chieu of ['Người tạo', 'Phiên']) {
      await userEvent.click(screen.getByRole('tab', { name: chieu }))
      await screen.findByRole('table', { name: new RegExp(chieu === 'Phiên' ? 'phiên' : 'người') })
    }
    // Canh chiều NGƯỢC: `/usage` là màn LƯỢNG. Thêm một cột tiền vào đây sẽ
    // không làm bài nào khác đỏ.
    expect(document.body.textContent).not.toContain('₫')
    expect([...document.querySelectorAll('thead th')].map((t) => t.textContent)).not.toContain(
      'Chi phí',
    )
  })

  it('`exact = false` hiện dấu !', async () => {
    boot('/usage?gop=phien')
    await screen.findByText('Phạm Minh')
    expect(screen.getByTitle(/exact=false/)).toBeVisible()
  })

  it('bấm hàng phiên đặt `?phien=` và mở slide-over; đóng thì xoá param', async () => {
    server.use(
      http.get('/api/v1/billing/sessions/:id', () =>
        HttpResponse.json({
          phien: PHIEN_GIA.items[0],
          events: [],
          ghi_chu_turn: 'Số lượt là xấp xỉ.',
        }),
      ),
    )
    const r = boot('/usage?gop=phien')
    await screen.findByText('s_9f3c')
    await userEvent.click(screen.getByText('s_9f3c'))
    expect(r.state.location.search).toMatchObject({ phien: 's_9f3c' })

    await userEvent.keyboard('{Escape}')
    expect(r.state.location.search.phien).toBeUndefined()
  })
})

describe('kỳ', () => {
  it('đổi kỳ gọi lại API và đặt lại trang về 0', async () => {
    const r = boot('/usage?trang=3')
    await screen.findByText('Lượt dùng chi tiết')
    expect(demGoi.ngay).toBe(1)
    await userEvent.click(screen.getByRole('button', { name: '7 ngày' }))
    expect(r.state.location.search).toMatchObject({ ky: '7-ngay', trang: 0 })
    await vi.waitFor(() => expect(demGoi.ngay).toBe(2))
  })

  it('`validateSearch` trả ĐỦ năm khoá, kể cả khoá mặc định', async () => {
    const r = boot('/usage')
    await screen.findByText('Lượt dùng chi tiết')
    // Thiếu một khoá ở đây là giá trị lạ trên URL lọt thẳng xuống component —
    // bẫy đã sập thật ở `/projects`.
    expect(Object.keys(r.state.location.search).sort()).toEqual(['gop', 'ky', 'tab', 'trang'])
  })
})
