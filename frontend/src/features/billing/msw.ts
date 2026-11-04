/**
 * Fake của module `billing` (M11) — spec §4②: mỗi module ship kèm fake để
 * module khác dev được mà không cần backend chạy. Cùng khuôn `features/ops/msw.ts` ·
 * `features/quality/msw.ts` · `features/realestate/msw.ts` — export một mảng
 * `xxxHandlers`, cắm vào `HANDLERS` ở `lib/msw/handlers.ts` bằng một dòng spread.
 *
 * ⚠️ Bản sao viết tay, KHÔNG có cổng parity nào canh (cùng hạng `contracts/*.json`
 * — xem mục «Fake MSW KHÔNG phải nguồn sự thật» ở CLAUDE.md, và gotcha `userCount`
 * sửa ở `f03da45`: một fake mã hoá luật NGƯỢC với backend rồi cả lý lẽ dựng trên
 * đó). MỌI field ở đây snake_case — module `billing` KHÔNG khai alias_generator,
 * khác `ops`/`quality`. Ngoại lệ ĐÚNG NGƯỢC: `PREVIEW_GIA_FAKE` (camelCase, dict
 * tay của BE) và hai body admin gửi LÊN mà client tự soạn (không phải ở đây).
 */
import { http, HttpResponse } from 'msw'
import type {
  BoGia,
  ChiTietPhien,
  DanhSachKey,
  DanhSachPhien,
  DongOwner,
  EventUsage,
  PhanTich,
  PhanUsageNgay,
  PhienUsage,
  PreviewGia,
  TongQuan,
  UsageTheoNgay,
} from './kieu'

/** Hàng `agent_key_id: null` — nhóm "chưa phân loại", KHÔNG được thiếu (bài
 *  test §9.1 Task 5 canh đúng hàng này). `chi_phi_tong` dưới PHẢI bằng tổng
 *  CHÍNH XÁC bốn hàng, kể cả hàng này. */
const KEY_CHUA_PHAN_LOAI = {
  agent_key_id: null,
  label: '',
  key_prefix: '',
  nguoi_tao: '',
  nguoi_tao_ten: null,
  da_thu_hoi: false,
  so_phien: 7,
  input_tokens: 15_000,
  output_tokens: 5_000,
  cache_read_tokens: 7_000,
  voice_sec: 26.35,
  so_event: 45,
  chi_phi: '15000.0000000000',
  // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` ở trên (10000+3000+1200+500+200+80+20).
  chi_phi_llm: '10000.0000000000',
  chi_phi_tts: '3000.0000000000',
  chi_phi_stt: '1200.0000000000',
  chi_phi_embed: '20.0000000000',
  chi_phi_call: '500.0000000000',
  chi_phi_vad: '200.0000000000',
  chi_phi_speaker_verify: '80.0000000000',
} as const

const BILLING_BY_KEY_GIA: DanhSachKey = {
  items: [
    {
      agent_key_id: 1,
      label: 'Zalo OA chính',
      key_prefix: 'ody_ag_1a2b',
      nguoi_tao: 'u_fake_dang',
      nguoi_tao_ten: 'Trần Hải Đăng',
      da_thu_hoi: false,
      so_phien: 20,
      input_tokens: 60_000,
      output_tokens: 18_000,
      cache_read_tokens: 25_000,
      voice_sec: 90.5,
      so_event: 340,
      chi_phi: '60000.0000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (40000+12000+5000+2000+800+150+50).
      chi_phi_llm: '40000.0000000000',
      chi_phi_tts: '12000.0000000000',
      chi_phi_stt: '5000.0000000000',
      chi_phi_embed: '50.0000000000',
      chi_phi_call: '2000.0000000000',
      chi_phi_vad: '800.0000000000',
      chi_phi_speaker_verify: '150.0000000000',
    },
    {
      agent_key_id: 2,
      label: 'Web widget',
      key_prefix: 'ody_ag_9f8e',
      nguoi_tao: 'u_fake_dang',
      nguoi_tao_ten: 'Trần Hải Đăng',
      da_thu_hoi: true,
      so_phien: 15,
      input_tokens: 50_000,
      output_tokens: 15_000,
      cache_read_tokens: 20_000,
      voice_sec: 60,
      so_event: 210,
      chi_phi: '50000.5000000000',
      // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (33000+10000.5+4500+1800+500+150+50).
      chi_phi_llm: '33000.0000000000',
      chi_phi_tts: '10000.5000000000',
      chi_phi_stt: '4500.0000000000',
      chi_phi_embed: '50.0000000000',
      chi_phi_call: '1800.0000000000',
      chi_phi_vad: '500.0000000000',
      chi_phi_speaker_verify: '150.0000000000',
    },
    {
      // Token in/out = 0 THẬT (lỗi gọi giữa chừng / phiên chỉ đọc cache) —
      // KHÔNG được che thành «—» như Cache read cùng hàng (review Task 5:
      // FE từng áp nhầm luật gạch-khi-0 của Cache read sang cả Token in/out).
      agent_key_id: 3,
      label: 'Zero-token key',
      key_prefix: 'ody_ag_0zer',
      nguoi_tao: 'u_fake_dang',
      nguoi_tao_ten: 'Trần Hải Đăng',
      da_thu_hoi: false,
      so_phien: 1,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      voice_sec: 0,
      so_event: 1,
      chi_phi: '10.0000000000',
      // Phí nền không gắn với dịch vụ nào cụ thể — dồn cả vào `llm` (đơn giản
      // hoá của fixture: một hàng usage rất nhỏ, không phải một quy luật).
      chi_phi_llm: '10.0000000000',
      chi_phi_tts: '0',
      chi_phi_stt: '0',
      chi_phi_embed: '0',
      chi_phi_call: '0',
      chi_phi_vad: '0',
      chi_phi_speaker_verify: '0',
    },
    KEY_CHUA_PHAN_LOAI,
  ],
  total: 4,
  // 60000 + 50000.5 + 10 + 15000 — tổng CHÍNH XÁC 4 hàng trên, kể cả hàng null.
  chi_phi_tong: '125010.5000000000',
  currency: 'VND',
}

const BILLING_SUMMARY_GIA: TongQuan = {
  input_tokens: 125_000,
  output_tokens: 38_000,
  cache_read_tokens: 52_000,
  // Thời lượng CUỘC GỌI (`component='call'`), KHÔNG cộng chéo — khớp hàng
  // `s-billing-2` bên dưới (event `call` audio_sec 176.85 lấy đúng số từ
  // hợp đồng BE §1 — không phải trùng hợp).
  voice_sec: 176.85,
  so_phien: 43,
  so_key: 4,
  chi_phi: BILLING_BY_KEY_GIA.chi_phi_tong,
  currency: 'VND',
  canh_bao: {
    thieu_gia: 2,
    nhan_chua_phan_loai: 5,
    event_khong_so_do: 1,
    llm_khong_chinh_xac: 3,
  },
}

const BILLING_BY_OWNER_GIA: DongOwner[] = [
  {
    user_id: 'u_fake_dang',
    ten: 'Trần Hải Đăng',
    email: 'dang@anphuland.vn',
    so_key: 2,
    so_phien: 35,
    input_tokens: 1211000,
    output_tokens: 143500,
    cache_read_tokens: 133000,
    voice_sec: 4907.0,
    so_event: 1330,
    chi_phi: '110000.5000000000',
    // Bảy cột dịch vụ CỘNG ĐÚNG BẰNG `chi_phi` (73000+22000+10000+100.5+4000+900+0).
    chi_phi_llm: '73000.0000000000',
    chi_phi_tts: '22000.0000000000',
    chi_phi_stt: '10000.0000000000',
    chi_phi_embed: '100.5000000000',
    chi_phi_call: '4000.0000000000',
    chi_phi_vad: '900.0000000000',
    chi_phi_speaker_verify: '0',
  },
  // Nhóm "chưa phân loại" ở theo-owner (sửa 2026-08-20 — trước đó INNER JOIN
  // làm rớt nhóm này). KHÔNG được thiếu, cùng lý do hàng null ở by-key.
  {
    user_id: null,
    ten: null,
    email: null,
    so_key: 0,
    so_phien: 7,
    input_tokens: 242200,
    output_tokens: 28700,
    cache_read_tokens: 26600,
    voice_sec: 981.4,
    so_event: 266,
    chi_phi: '15000.0000000000',
    // Cùng bảy cột với `KEY_CHUA_PHAN_LOAI` — cùng nhóm, cùng tổng.
    chi_phi_llm: '10000.0000000000',
    chi_phi_tts: '3000.0000000000',
    chi_phi_stt: '1200.0000000000',
    chi_phi_embed: '20.0000000000',
    chi_phi_call: '500.0000000000',
    chi_phi_vad: '200.0000000000',
    chi_phi_speaker_verify: '80.0000000000',
  },
]

const PHIEN_BILLING_1: PhienUsage = {
  session_id: 's-billing-1',
  agent_key_id: 1,
  key_label: 'Zalo OA chính',
  customer_name: 'Nguyễn Minh Anh',
  phone: '0912448111',
  channel: 'zalo',
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
}

const PHIEN_BILLING_2: PhienUsage = {
  session_id: 's-billing-2',
  agent_key_id: null,
  key_label: null,
  customer_name: null,
  phone: null,
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
}

/**
 * `usage-by-day` — 21 ngày × 6 component. KHÔNG có trường tiền nào (hợp đồng).
 *
 * Sinh bằng một đường cong TIỀN ĐỊNH (không `Math.random`): fake phải ra cùng
 * con số mỗi lần mở, nếu không thì hai người xem hai bản khác nhau và không ai
 * đối chiếu được. Hai số 0 (chỉ số 8 và 15) là chủ nhật agent không chạy — đó
 * là ca mà biểu đồ phải vẽ vòng tròn rỗng chạm đáy, và là ca bài test canh.
 *
 * ⚠️ ĐƠN VỊ theo `billing.pricing_basis`: `tts`/`embed` là KÝ TỰ (`text_units`),
 * `call`/`vad`/`speaker_verify` là GIÂY (`audio_sec`), `llm` là TOKEN. Đặt số
 * vào ô sai là fake dạy sai đơn vị — và `features/billing/msw.ts` KHÔNG có cổng
 * parity nào canh (cùng hạng `contracts/*.json`).
 */
const HOAT = [
  0.42, 0.13, 0.58, 0.68, 0.65, 0.71, 0.63, 0.24, 0, 0.55, 0.74, 0.79, 0.76, 0.65, 0.27, 0, 0.7,
  0.83, 0.9, 0.85, 0.78,
]

const HE_SO: readonly {
  readonly component: string
  readonly he: number
  readonly o: keyof PhanUsageNgay
}[] = [
  { component: 'llm', he: 90_000, o: 'input_tokens' },
  { component: 'call', he: 1_510, o: 'audio_sec' },
  { component: 'vad', he: 1_820, o: 'audio_sec' },
  { component: 'stt', he: 193, o: 'audio_sec' },
  { component: 'tts', he: 46_000, o: 'text_units' },
  { component: 'embed', he: 31_000, o: 'text_units' },
  { component: 'speaker_verify', he: 75, o: 'audio_sec' },
]

const BILLING_USAGE_BY_DAY_GIA: UsageTheoNgay = {
  theo_ngay: HOAT.map((h, i) => ({
    ngay: `2026-08-${String(i + 1).padStart(2, '0')}`,
    so_phien: h === 0 ? 0 : Math.round(29 * h),
    phan:
      h === 0
        ? []
        : HE_SO.map(({ component, he, o }) => {
            const v = Math.round(he * h)
            const p: PhanUsageNgay = {
              component,
              so_event: Math.max(1, Math.round(120 * h)),
              input_tokens: 0,
              output_tokens: 0,
              cache_read_tokens: 0,
              audio_sec: 0,
              text_units: 0,
              units: Math.max(1, Math.round(8 * h)),
              wall_ms_stream: 0,
              text_units_hoi_thoai: 0,
            }
            // Hai vế LỌC THEO `purpose` (hợp đồng §`usage-by-day` điều 5).
            // `wall_ms_stream` chỉ `stt` mới có, và nó là MILI GIÂY — đặt cùng
            // thang với `audio_sec` ở đây là fake dạy sai đơn vị, rail sẽ in ra
            // một quãng gấp nghìn lần sự thật.
            if (component === 'stt') {
              return { ...p, audio_sec: v, wall_ms_stream: v * 2400, text_units_hoi_thoai: v * 5 }
            }
            // `tts`/`embed`: mọi dòng đều `purpose='conversation'` nên hai cột
            // ký tự BẰNG NHAU — fake lệch ở đây là dạy sai chính bất biến đó.
            if (o === 'text_units') return { ...p, text_units: v, text_units_hoi_thoai: v }
            // `llm` có ba loại token; component khác chỉ có một ô số đo.
            if (component === 'llm') {
              return {
                ...p,
                input_tokens: v,
                output_tokens: Math.round(v * 0.142),
                cache_read_tokens: Math.round(v * 0.131),
              }
            }
            return { ...p, [o]: v }
          }),
  })),
}

const BILLING_SESSIONS_GIA: DanhSachPhien = {
  items: [PHIEN_BILLING_1, PHIEN_BILLING_2],
  total: 2,
}

// Event `tts` mang `units` NHỎ (số clause) và `text_units` LỚN (ký tự đưa vào
// TTS) — đúng ca `units: 7, text_units: 1115` hợp đồng BE nêu làm ví dụ. Task 6
// có bài test đọc đúng cặp này; đừng "làm tròn cho đẹp" mà lệch khỏi ví dụ đó.
const EVENTS_BILLING_2: EventUsage[] = [
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
    audio_sec: 12.4,
    units: 1,
    text_units: 340,
    exact: true,
    chi_phi: '50.0000000000',
    occurred_at: '2026-08-15T10:00:05+07:00',
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
    exact: false,
    chi_phi: '1200.0000000000',
    occurred_at: '2026-08-15T10:00:07+07:00',
  },
  {
    event_id: 3,
    seq: 3,
    turn_idx: 1,
    component: 'tts',
    purpose: 'speak',
    // '' — DEFAULT '' của component audio, không phải null (xem `kieu.ts`).
    provider: '',
    model: '',
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    audio_sec: 8.2,
    units: 7,
    text_units: 1115,
    exact: true,
    chi_phi: '350.0000000000',
    occurred_at: '2026-08-15T10:00:09+07:00',
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
    chi_phi: '200.0000000000',
    occurred_at: '2026-08-15T10:03:00+07:00',
  },
]

const CHI_TIET_PHIEN_BILLING_GIA: Record<string, ChiTietPhien> = {
  's-billing-1': {
    phien: PHIEN_BILLING_1,
    events: [],
    ghi_chu_turn:
      'turn_idx của dòng audio là xấp xỉ (TTS của lượt N nằm ở lô N+1). Tổng theo phiên luôn đúng; đừng dùng số theo từng lượt để đối chiếu tiền.',
  },
  's-billing-2': {
    phien: PHIEN_BILLING_2,
    events: EVENTS_BILLING_2,
    ghi_chu_turn:
      'turn_idx của dòng audio là xấp xỉ (TTS của lượt N nằm ở lô N+1). Tổng theo phiên luôn đúng; đừng dùng số theo từng lượt để đối chiếu tiền.',
  },
}

const BO_GIA_GIA: BoGia[] = [
  {
    id: 1,
    code: 'vn-default',
    name: 'Bảng giá VND mặc định',
    currency: 'VND',
    status: 'active',
    is_default: true,
    created_at: '2026-01-01T00:00:00+07:00',
  },
  {
    id: 2,
    code: 'us-pilot',
    name: 'Bảng giá USD thí điểm',
    currency: 'USD',
    status: 'inactive',
    is_default: false,
    created_at: '2026-07-01T00:00:00+07:00',
  },
]

/**
 * Mục ② «Tiền đi đâu». HAI bất biến của fake này, cả hai đã được BE đảm bảo
 * nên fake sai là fake dạy sai:
 *  ① `theo_ngay` có ĐỦ MỌI NGÀY của kỳ, kể cả ngày 0 đồng (15/08 và 17/08 ở
 *    đây) — nếu bỏ ngày rỗng thì chart nối thẳng qua chỗ trũng.
 *  ② Tổng của CẢ HAI chiều = `chi_phi_tong` = `chi_phi` của `/summary`. Một
 *    fake lệch tổng dạy màn hình rằng lệch tổng là bình thường, đúng lớp lỗi
 *    `userCount` (gotcha `f03da45`) đã gây một vòng thiết kế sai.
 *  ③ `phan` của mỗi ngày cộng lại ĐÚNG BẰNG `chi_phi` của ngày đó — tooltip
 *    hiện tổng và từng dòng cạnh nhau, lệch một đồng là thấy ngay.
 *
 * `vad` cố ý `chi_phi: '0'` NHƯNG có số đo: đó là component đo được mà chưa có
 * dòng giá nào khớp — nhánh hiển thị riêng của `TheComponent`, không có hàng
 * này thì nhánh đó không bao giờ được chạy dưới MSW.
 */
const BILLING_BREAKDOWN_GIA: PhanTich = {
  theo_ngay: [
    {
      ngay: '2026-08-01',
      chi_phi: '6207.7132000000',
      phan: [
        { component: 'llm', chi_phi: '3078.7671000000' },
        { component: 'tts', chi_phi: '1390.4109000000' },
        { component: 'stt', chi_phi: '1043.3296000000' },
        { component: 'call', chi_phi: '446.9178000000' },
        { component: 'embed', chi_phi: '173.8013000000' },
        { component: 'speaker_verify', chi_phi: '74.4865000000' },
      ],
    },
    {
      ngay: '2026-08-02',
      chi_phi: '6849.8904000000',
      phan: [
        { component: 'llm', chi_phi: '3397.2602000000' },
        { component: 'tts', chi_phi: '1534.2465000000' },
        { component: 'stt', chi_phi: '1151.2602000000' },
        { component: 'call', chi_phi: '493.1506000000' },
        { component: 'embed', chi_phi: '191.7808000000' },
        { component: 'speaker_verify', chi_phi: '82.1921000000' },
      ],
    },
    {
      ngay: '2026-08-03',
      chi_phi: '2354.6498000000',
      phan: [
        { component: 'llm', chi_phi: '1167.8082000000' },
        { component: 'tts', chi_phi: '527.3972000000' },
        { component: 'stt', chi_phi: '395.7457000000' },
        { component: 'call', chi_phi: '169.5205000000' },
        { component: 'embed', chi_phi: '65.9246000000' },
        { component: 'speaker_verify', chi_phi: '28.2536000000' },
      ],
    },
    {
      ngay: '2026-08-04',
      chi_phi: '1926.5317000000',
      phan: [
        { component: 'llm', chi_phi: '955.4794000000' },
        { component: 'tts', chi_phi: '431.5068000000' },
        { component: 'stt', chi_phi: '323.7919000000' },
        { component: 'call', chi_phi: '138.6986000000' },
        { component: 'embed', chi_phi: '53.9383000000' },
        { component: 'speaker_verify', chi_phi: '23.1167000000' },
      ],
    },
    {
      ngay: '2026-08-05',
      chi_phi: '7599.0972000000',
      phan: [
        { component: 'llm', chi_phi: '3768.8356000000' },
        { component: 'tts', chi_phi: '1702.0548000000' },
        { component: 'stt', chi_phi: '1277.1793000000' },
        { component: 'call', chi_phi: '547.0890000000' },
        { component: 'embed', chi_phi: '212.7568000000' },
        { component: 'speaker_verify', chi_phi: '91.1817000000' },
      ],
    },
    {
      ngay: '2026-08-06',
      chi_phi: '8134.2449000000',
      phan: [
        { component: 'llm', chi_phi: '4034.2465000000' },
        { component: 'tts', chi_phi: '1821.9178000000' },
        { component: 'stt', chi_phi: '1367.1215000000' },
        { component: 'call', chi_phi: '585.6164000000' },
        { component: 'embed', chi_phi: '227.7397000000' },
        { component: 'speaker_verify', chi_phi: '97.6030000000' },
      ],
    },
    {
      ngay: '2026-08-07',
      chi_phi: '7385.0381000000',
      phan: [
        { component: 'llm', chi_phi: '3662.6712000000' },
        { component: 'tts', chi_phi: '1654.1095000000' },
        { component: 'stt', chi_phi: '1241.2024000000' },
        { component: 'call', chi_phi: '531.6780000000' },
        { component: 'embed', chi_phi: '206.7636000000' },
        { component: 'speaker_verify', chi_phi: '88.6134000000' },
      ],
    },
    {
      ngay: '2026-08-08',
      chi_phi: '8562.3630000000',
      phan: [
        { component: 'llm', chi_phi: '4246.5753000000' },
        { component: 'tts', chi_phi: '1917.8082000000' },
        { component: 'stt', chi_phi: '1439.0753000000' },
        { component: 'call', chi_phi: '616.4383000000' },
        { component: 'embed', chi_phi: '239.7260000000' },
        { component: 'speaker_verify', chi_phi: '102.7399000000' },
      ],
    },
    {
      ngay: '2026-08-09',
      chi_phi: '9204.5402000000',
      phan: [
        { component: 'llm', chi_phi: '4565.0684000000' },
        { component: 'tts', chi_phi: '2061.6438000000' },
        { component: 'stt', chi_phi: '1547.0059000000' },
        { component: 'call', chi_phi: '662.6712000000' },
        { component: 'embed', chi_phi: '257.7054000000' },
        { component: 'speaker_verify', chi_phi: '110.4455000000' },
      ],
    },
    {
      ngay: '2026-08-10',
      chi_phi: '3317.9157000000',
      phan: [
        { component: 'llm', chi_phi: '1645.5479000000' },
        { component: 'tts', chi_phi: '743.1506000000' },
        { component: 'stt', chi_phi: '557.6417000000' },
        { component: 'call', chi_phi: '238.8698000000' },
        { component: 'embed', chi_phi: '92.8938000000' },
        { component: 'speaker_verify', chi_phi: '39.8119000000' },
      ],
    },
    {
      ngay: '2026-08-11',
      chi_phi: '2782.7680000000',
      phan: [
        { component: 'llm', chi_phi: '1380.1369000000' },
        { component: 'tts', chi_phi: '623.2876000000' },
        { component: 'stt', chi_phi: '467.6994000000' },
        { component: 'call', chi_phi: '200.3424000000' },
        { component: 'embed', chi_phi: '77.9109000000' },
        { component: 'speaker_verify', chi_phi: '33.3908000000' },
      ],
    },
    {
      ngay: '2026-08-12',
      chi_phi: '9632.6584000000',
      phan: [
        { component: 'llm', chi_phi: '4777.3972000000' },
        { component: 'tts', chi_phi: '2157.5342000000' },
        { component: 'stt', chi_phi: '1618.9597000000' },
        { component: 'call', chi_phi: '693.4931000000' },
        { component: 'embed', chi_phi: '269.6917000000' },
        { component: 'speaker_verify', chi_phi: '115.5825000000' },
      ],
    },
    {
      ngay: '2026-08-13',
      chi_phi: '10167.8061000000',
      phan: [
        { component: 'llm', chi_phi: '5042.8082000000' },
        { component: 'tts', chi_phi: '2277.3972000000' },
        { component: 'stt', chi_phi: '1708.9019000000' },
        { component: 'call', chi_phi: '732.0205000000' },
        { component: 'embed', chi_phi: '284.6746000000' },
        { component: 'speaker_verify', chi_phi: '122.0037000000' },
      ],
    },
    {
      ngay: '2026-08-14',
      chi_phi: '9418.5993000000',
      phan: [
        { component: 'llm', chi_phi: '4671.2328000000' },
        { component: 'tts', chi_phi: '2109.5890000000' },
        { component: 'stt', chi_phi: '1582.9828000000' },
        { component: 'call', chi_phi: '678.0821000000' },
        { component: 'embed', chi_phi: '263.6986000000' },
        { component: 'speaker_verify', chi_phi: '113.0140000000' },
      ],
    },
    { ngay: '2026-08-15', chi_phi: '0.0000000000', phan: [] },
    {
      ngay: '2026-08-16',
      chi_phi: '10917.0128000000',
      phan: [
        { component: 'llm', chi_phi: '5414.3835000000' },
        { component: 'tts', chi_phi: '2445.2054000000' },
        { component: 'stt', chi_phi: '1834.8210000000' },
        { component: 'call', chi_phi: '785.9589000000' },
        { component: 'embed', chi_phi: '305.6506000000' },
        { component: 'speaker_verify', chi_phi: '130.9934000000' },
      ],
    },
    { ngay: '2026-08-17', chi_phi: '0.0000000000', phan: [] },
    {
      ngay: '2026-08-18',
      chi_phi: '7920.1858000000',
      phan: [
        { component: 'llm', chi_phi: '3928.0821000000' },
        { component: 'tts', chi_phi: '1773.9726000000' },
        { component: 'stt', chi_phi: '1331.1446000000' },
        { component: 'call', chi_phi: '570.2054000000' },
        { component: 'embed', chi_phi: '221.7465000000' },
        { component: 'speaker_verify', chi_phi: '95.0346000000' },
      ],
    },
    {
      ngay: '2026-08-19',
      chi_phi: '6742.8609000000',
      phan: [
        { component: 'llm', chi_phi: '3344.1780000000' },
        { component: 'tts', chi_phi: '1510.2739000000' },
        { component: 'stt', chi_phi: '1133.2718000000' },
        { component: 'call', chi_phi: '485.4452000000' },
        { component: 'embed', chi_phi: '188.7842000000' },
        { component: 'speaker_verify', chi_phi: '80.9078000000' },
      ],
    },
    {
      ngay: '2026-08-20',
      chi_phi: '5886.6245000000',
      phan: [
        { component: 'llm', chi_phi: '2919.5205000000' },
        { component: 'tts', chi_phi: '1318.4931000000' },
        { component: 'stt', chi_phi: '989.3642000000' },
        { component: 'call', chi_phi: '423.8013000000' },
        { component: 'embed', chi_phi: '164.8116000000' },
        { component: 'speaker_verify', chi_phi: '70.6338000000' },
      ],
    },
  ],
  theo_component: [
    {
      component: 'llm',
      so_event: 620,
      input_tokens: 118000,
      output_tokens: 36000,
      cache_read_tokens: 50000,
      audio_sec: 0.0,
      text_units: 0,
      units: 620,
      chi_phi: '62000.0000000000',
    },
    {
      component: 'tts',
      so_event: 1117,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 1842.6,
      text_units: 184260,
      units: 1117,
      chi_phi: '28000.0000000000',
    },
    {
      component: 'stt',
      so_event: 206,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 412.8,
      text_units: 4128,
      units: 206,
      chi_phi: '21010.5000000000',
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
      chi_phi: '9000.0000000000',
    },
    {
      component: 'embed',
      so_event: 98,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 0.0,
      text_units: 61400,
      units: 98,
      chi_phi: '3500.0000000000',
    },
    {
      component: 'speaker_verify',
      so_event: 52,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 64.1,
      text_units: 0,
      units: 52,
      chi_phi: '1500.0000000000',
    },
    {
      component: 'vad',
      so_event: 240,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 529.1,
      text_units: 0,
      units: 0,
      chi_phi: '0.0000000000',
    },
  ],
  chi_phi_tong: BILLING_BY_KEY_GIA.chi_phi_tong,
  currency: 'VND',
}

/** dict tay của BE — camelCase CHỦ Ý, KHÁC mọi response khác của module (xem `kieu.ts::PreviewGia`). */
const PREVIEW_GIA_FAKE: PreviewGia = { chiPhi: '4200.0000000000', currency: 'VND' }

/**
 * 6 endpoint admin xác thực bằng header `X-Platform-Admin-Token`, KHÔNG bằng
 * phiên đăng nhập. Fake PHẢI kiểm header này và trả 401 khi thiếu — nếu không,
 * màn `/pricing` chạy dưới MSW mà không bao giờ đi qua nhánh "chưa có token",
 * và Task 8 sẽ test một nhánh chết.
 */
function thieuTokenAdmin(request: Request): HttpResponse<{ error: unknown }> | null {
  const token = request.headers.get('X-Platform-Admin-Token')
  if (token) return null
  return HttpResponse.json(
    { error: { code: 'UNAUTHORIZED', message: 'Thiếu X-Platform-Admin-Token' } },
    { status: 401 },
  )
}

export const billingHandlers = [
  http.get('/api/v1/billing/summary', () => HttpResponse.json(BILLING_SUMMARY_GIA)),
  http.get('/api/v1/billing/breakdown', () => HttpResponse.json(BILLING_BREAKDOWN_GIA)),
  http.get('/api/v1/billing/usage-by-day', () => HttpResponse.json(BILLING_USAGE_BY_DAY_GIA)),
  http.get('/api/v1/billing/by-key', () => HttpResponse.json(BILLING_BY_KEY_GIA)),
  http.get('/api/v1/billing/by-owner', () => HttpResponse.json(BILLING_BY_OWNER_GIA)),
  http.get('/api/v1/billing/sessions', () => HttpResponse.json(BILLING_SESSIONS_GIA)),
  http.get('/api/v1/billing/sessions/:sessionId', ({ params }) => {
    const ct = CHI_TIET_PHIEN_BILLING_GIA[params['sessionId'] as string]
    if (!ct) {
      return HttpResponse.json(
        { error: { code: 'PHIEN_KHONG_TON_TAI', message: 'Không tìm thấy usage của phiên này' } },
        { status: 404 },
      )
    }
    return HttpResponse.json(ct)
  }),

  http.get('/api/v1/admin/billing/price-versions', ({ request }) => {
    const chan = thieuTokenAdmin(request)
    if (chan) return chan
    return HttpResponse.json(BO_GIA_GIA)
  }),
  http.post('/api/v1/admin/billing/price-versions', ({ request }) => {
    const chan = thieuTokenAdmin(request)
    if (chan) return chan
    return HttpResponse.json({ id: 3 }, { status: 201 })
  }),
  http.post('/api/v1/admin/billing/price-versions/:pb/items', ({ request }) => {
    const chan = thieuTokenAdmin(request)
    if (chan) return chan
    return HttpResponse.json({ id: 99 }, { status: 201 })
  }),
  http.post('/api/v1/admin/billing/price-versions/:pb/activate', ({ request }) => {
    const chan = thieuTokenAdmin(request)
    if (chan) return chan
    return HttpResponse.json({ status: 'active' })
  }),
  http.get('/api/v1/admin/billing/price-versions/:pb/preview', ({ request }) => {
    const chan = thieuTokenAdmin(request)
    if (chan) return chan
    return HttpResponse.json(PREVIEW_GIA_FAKE)
  }),
  http.post('/api/v1/admin/billing/tenants/:tenantId/price-version', ({ request }) => {
    const chan = thieuTokenAdmin(request)
    if (chan) return chan
    return HttpResponse.json({ status: 'ok' })
  }),
]
