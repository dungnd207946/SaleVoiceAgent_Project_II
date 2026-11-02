/**
 * Fake của màn Kịch bản — CÓ TRẠNG THÁI từ đợt 3 (sửa được). Mô phỏng hành vi BE `modules/playbook/router.py`:
 * chưa áp dụng ⇒ `GET /playbook` trả NGUYÊN bộ nút mẫu (như BE trả `playbook.json`); có bản riêng ⇒ dựng lại
 * trường tương thích + `hash` từ khuôn lưu (`tuongThich`, bản sao của `nut.tuong_thich`). KHÔNG kiểm luật nút
 * (BE `kiem.py`) — test ép lỗi bằng `epLoiGhiKichBanGia`. Test đổi trạng thái thì `datLaiKichBanGia()` ở `beforeEach`.
 */
import { http, HttpResponse } from 'msw'
import type { DuLieuKichBan, GioiHan, KichBan, LuotNut, NutKichBan, NutVao } from './api'
import { veKhuon } from './khuon'

/** Hash GIẢ — chỉ cần «cùng nội dung ⇒ cùng hash», như `nut.bam_nut` (bỏ `nguon`). */
export function hashGia(n: NutVao): string {
  const s = JSON.stringify([
    n.id,
    n.ten,
    n.nhom,
    n.bat,
    n.kenh,
    n.dau_hieu,
    n.lam,
    n.tool,
    n.cam,
    n.khi_thieu,
    n.cau_ket,
    n.lan_2,
    n.chi_lan_2,
    n.buoc.map((b) => [b.id, b.lam]),
  ])
  let h = 5381
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 33) ^ s.charCodeAt(i)) >>> 0
  return h.toString(16).padStart(12, '0')
}

export const GIOI_HAN_GIA: GioiHan = {
  nhom: [
    'chot',
    'chuyen_nguoi',
    'dat_lich',
    'ket_thuc',
    'kham_pha',
    'mo_dau',
    'phan_doi',
    'tai_lieu',
    'tim_can',
  ],
  kenh: ['chat', 'voice'],
  tool: [
    'analyze_projects',
    'booking',
    'discover_projects',
    'escalate',
    'find_project',
    'get_document',
    'kb_search',
    'no_lookup_needed',
    'search_units',
    'send_media',
    'update_customer',
  ],
  // Bản thật khoá thêm `doi_gia_rieng`; fake không có nút đó nên chỉ khoá hai nút có mặt.
  khoaXoa: ['che_dat', 'che_dat_downsell'],
  khuonId: '^[a-z][a-z0-9_]{0,39}$',
  khuonIdRieng: '^rieng_[a-z0-9_]{1,33}$',
  maxNut: 40,
  maxTen: 60,
  maxTool: 4,
  maxDong: { dau_hieu: 6, lam: 6, cam: 5 },
  maxBuoc: 6,
  maxKyTu: 200,
  maxDauHieuTong: 360,
  maxCamTong: 320,
  maxCau: 160,
}

type Goc = Partial<NutKichBan> & Pick<NutKichBan, 'id' | 'loai' | 'nhom'>
const nut = (n: Goc): NutKichBan => {
  const d: NutKichBan = {
    trang_thai: 'dung',
    kenh: [],
    dau_hieu: [],
    lam: [],
    cam: [],
    tool: [],
    can_du_lieu: [],
    khi_thieu: '',
    tiep: {},
    dieu_kien: {},
    buoc: [],
    nguon: 'RULES.md',
    lop: 'sale',
    hash: '',
    khoaXoa: false,
    bat: n.trang_thai !== 'nhap',
    lan_2: '',
    chi_lan_2: false,
    cau_ket: '',
    ...n,
  }
  return { ...d, hash: hashGia(veKhuon(d)) }
}

const NUT_GIA: NutKichBan[] = [
  nut({
    id: 'che_dat',
    ten: 'Khách chê đắt',
    loai: 'phan_xa',
    nhom: 'phan_doi',
    khoaXoa: true,
    dau_hieu: ["khách chê giá cao, 'đắt quá', 'giá ngáo'", 'chê đắt LẦN ĐẦU trong phiên'],
    lam: [
      'ghi nhận thật lòng, không mở đầu bằng "nhưng"',
      'tra NGAY kb_search chính sách vay / tiến độ thanh toán',
    ],
    cam: ['giảm giá', 'escalate', 'tự nhẩm lãi / trả góp'],
    tool: ['kb_search', 'update_customer', 'search_units'],
    can_du_lieu: ['kb:vay_von', 'kb:tien_do_thanh_toan'],
    khi_thieu: 'nói thật chưa có tài liệu vay, chào căn vừa tầm',
    cau_ket: 'một lời mời mà khách chỉ cần trả lời có hoặc không',
    lan_2: 'che_dat_downsell',
    tiep: { lan_2: 'che_dat_downsell' },
    hien: {
      dau_hieu: [
        'Khách chê giá cao, kiểu “đắt quá”, “giá ngáo”',
        'Khách chê đắt lần đầu tiên trong phiên',
      ],
      lam: [
        'Ghi nhận thật lòng, không mở đầu bằng chữ “nhưng”',
        'Tra ngay tài liệu về chính sách vay và tiến độ thanh toán',
      ],
      cam: ['Giảm giá', 'Chuyển cho chuyên viên', 'Tự nhẩm tiền lãi hoặc số tiền trả góp'],
      khi_thieu: 'Nói thật là chưa có tài liệu vay và chào căn vừa tầm',
    },
  }),
  nut({
    id: 'che_dat_downsell',
    ten: 'Chê đắt lần hai',
    loai: 'phan_xa',
    nhom: 'phan_doi',
    khoaXoa: true,
    chi_lan_2: true,
    dau_hieu: ['chê đắt LẦN HAI trong phiên', 'vẫn đắt quá'],
    lam: ['down-sell: một căn rẻ hơn kèm đánh đổi nói rõ, rồi dừng hẳn'],
    cam: ['tự giảm giá', 'áp lực giả'],
    tool: ['search_units'],
    dieu_kien: { lan: 2 },
  }),
  nut({
    id: 'chot',
    ten: 'Chốt căn',
    loai: 'luong',
    nhom: 'chot',
    dau_hieu: ['đã ưng một căn cụ thể, hỏi bước tiếp theo'],
    lam: ['chốt khách đủ 4 bước, thông tin cọc chỉ từ kb'],
    cam: ['bịa mức cọc / chính sách', 'áp lực giả'],
    tool: ['kb_search', 'search_units', 'escalate'],
    lan_2: 'chuyen_that',
    tiep: { lan_2: 'chuyen_that' },
    buoc: [
      { id: 'xac_nhan_nhu_cau', lam: 'hỏi xác nhận nhu cầu dạng đóng sau khi đã tư vấn', tool: [] },
      { id: 'chon_mot_can', lam: 'chọn MỘT căn phù hợp và báo giá từ kết quả tool', tool: [] },
      { id: 'dong_tien_coc', lam: 'nêu tiến độ thanh toán và chính sách, chỉ từ kb', tool: [] },
    ],
  }),
  nut({
    id: 'chuyen_that',
    ten: 'Chuyển cho chuyên viên',
    loai: 'phan_xa',
    nhom: 'chuyen_nguoi',
    lop: 'he_thong',
    dau_hieu: ['muốn gặp người thật', 'khách nói đã sẵn sàng cọc / giữ chỗ ngay'],
    lam: ["gọi escalate(action='transfer', ...) NGAY"],
    cam: ['hứa trước khi gọi escalate'],
    tool: ['escalate'],
  }),
  nut({
    id: 'goi_dien_ra',
    ten: 'Gọi điện cho khách',
    loai: 'luong',
    nhom: 'mo_dau',
    trang_thai: 'nhap',
    kenh: ['voice'],
    dau_hieu: ['cuộc gọi chủ động ra cho khách'],
    lam: ['gọi điện ra ngắn gọn, không quá 3 phút, mục tiêu là xin được cuộc hẹn'],
    tool: ['booking', 'update_customer', 'discover_projects'],
  }),
]

export const TEMPLATE_VERSION_GIA = 'tv-mau-1'
/** Lớp sale của mẫu, khuôn lưu — thứ tự `che_dat, che_dat_downsell, chot, goi_dien_ra`. */
export const MAU_GIA: NutVao[] = NUT_GIA.filter((n) => n.lop === 'sale').map(veKhuon)

interface TrangThaiGia {
  nut: NutVao[] | null
  roleDung: string[]
  version: number
  tuTemplate: string | null
}
const DAU: TrangThaiGia = { nut: null, roleDung: ['customer'], version: 0, tuTemplate: null }
let tt: TrangThaiGia = { ...DAU }
let loiKe: { status: number; body: Record<string, unknown> } | null = null
/** Thân mọi lần ghi theo thứ tự (kể cả lần bị từ chối) — test đọc để kiểm payload. */
export const GHI_GIA: { duong: string; body: unknown }[] = []

export function datLaiKichBanGia(p: Partial<TrangThaiGia> = {}): void {
  tt = { ...DAU, ...p }
  loiKe = null
  GHI_GIA.length = 0
}

/** Lần ghi KẾ TIẾP trả đúng lỗi này (một lần). */
export function epLoiGhiKichBanGia(status: number, body: Record<string, unknown>): void {
  loiKe = { status, body }
}

function kichBanGia(): KichBan {
  const rieng = tt.nut !== null
  return {
    trangThai: rieng ? 'rieng' : 'mau',
    version: tt.version,
    tuTemplate: tt.tuTemplate,
    templateVersion: TEMPLATE_VERSION_GIA,
    coTemplateMoi: rieng && tt.tuTemplate !== TEMPLATE_VERSION_GIA,
    roleDung: tt.roleDung,
    capNhatLuc: tt.version > 0 ? '2026-10-06T07:32:00Z' : null,
    capNhatBoi: null,
  }
}

/** Bản sao `nut.tuong_thich` của BE: tool lạ bị bỏ TRƯỚC khi băm. */
function tuongThich(d: NutVao): NutKichBan {
  const x = { ...d, tool: d.tool.filter((t) => GIOI_HAN_GIA.tool.includes(t)) }
  return {
    ...x,
    lop: 'sale',
    loai: x.buoc.length ? 'luong' : 'phan_xa',
    trang_thai: x.bat ? 'dung' : 'nhap',
    dieu_kien: x.chi_lan_2 ? { lan: 2 } : {},
    tiep: x.lan_2 ? { lan_2: x.lan_2 } : {},
    can_du_lieu: [],
    buoc: x.buoc.map((b) => ({ ...b, tool: [] })),
    khoaXoa: GIOI_HAN_GIA.khoaXoa.includes(x.id),
    hash: hashGia(x),
  }
}

const dem = (ten: string, so: number) => ({ ten, so })
const so = (soLuot: number, daCham: number, dat: number, tiLeDat: number | null) => ({
  soLuot,
  daCham,
  dat,
  tiLeDat,
  thieuDuLieu: 0,
  hayThieu: [],
  hayPham: [],
  jevSo: 0,
  jevKhop: null,
})

export const FAKE_KICH_BAN: DuLieuKichBan = {
  version: 'abc1234567890def',
  promptVersion: 'v3',
  nodes: NUT_GIA,
  soDo: {
    che_dat: {
      ...so(90, 80, 57, 0.71),
      hayThieu: [dem('kết nối lợi ích', 12)],
      hayPham: [dem('tự nhẩm lãi / trả góp', 3)],
    },
    chot: so(12, 10, 5, 0.5),
    chuyen_that: so(3, 3, 3, null),
  },
  nutCu: {},
  phienBanCu: 0,
  nguon: ['web', 'zalo'],
  coDuLieu: true,
  kichBan: kichBanGia(),
}

function duLieuGia(): DuLieuKichBan {
  const nodes =
    tt.nut === null
      ? NUT_GIA
      : [...tt.nut.map(tuongThich), ...NUT_GIA.filter((n) => n.lop === 'he_thong')]
  return { ...FAKE_KICH_BAN, nodes, kichBan: kichBanGia() }
}

export const FAKE_LUOT: LuotNut[] = [
  {
    sessionId: 's-an-1',
    seq: 3,
    phone: null,
    taoLuc: '2026-09-29T09:15:00Z',
    khach: 'Giá này cao quá em ơi',
    agent: 'Dạ em hiểu ạ, để em kiểm tra chính sách vay của dự án cho anh.',
    dat: true,
    thieu: [],
    viPhamCam: [],
    thieuDuLieu: false,
    buoc: null,
    jevNut: 'che_dat',
  },
  {
    sessionId: 's-anh-1',
    seq: 3,
    phone: '0912448111',
    taoLuc: '2026-09-29T10:02:00Z',
    khach: 'Đắt quá, anh chỉ có tầm 2 tỷ',
    agent: 'Dạ căn này 3,2 tỷ, anh cân nhắc nhé.',
    dat: false,
    thieu: ['kết nối lợi ích'],
    viPhamCam: [],
    thieuDuLieu: false,
    buoc: null,
    jevNut: null,
  },
]

const DA_DOI = {
  error: {
    code: 'PLAYBOOK_DA_DOI',
    message: 'Kịch bản vừa thay đổi ở nơi khác — tải lại rồi lưu lại',
  },
}

/** Lỗi ép trước, rồi khoá lạc quan — đúng thứ tự BE. `null` = được ghi. */
function chan(version: number): Response | null {
  if (loiKe) {
    const l = loiKe
    loiKe = null
    return HttpResponse.json(l.body, { status: l.status })
  }
  if (version !== tt.version) return HttpResponse.json(DA_DOI, { status: 409 })
  return null
}

export const kichBanHandlers = [
  http.get('/api/v1/playbook', () => HttpResponse.json(duLieuGia())),
  http.get('/api/v1/playbook/template', () =>
    HttpResponse.json({
      templateVersion: TEMPLATE_VERSION_GIA,
      nodes: NUT_GIA.filter((n) => n.lop === 'sale'),
      gioiHan: GIOI_HAN_GIA,
    }),
  ),
  http.put('/api/v1/playbook', async ({ request }) => {
    const b = (await request.json()) as { version: number; nut: NutVao[] }
    GHI_GIA.push({ duong: 'PUT /playbook', body: b })
    const tu = chan(b.version)
    if (tu) return tu
    tt = {
      ...tt,
      nut: b.nut,
      tuTemplate: tt.nut === null ? TEMPLATE_VERSION_GIA : tt.tuTemplate,
      version: tt.version + 1,
    }
    return HttpResponse.json(kichBanGia())
  }),
  http.post('/api/v1/playbook/ap-dung', async ({ request }) => {
    const b = (await request.json()) as { version: number }
    GHI_GIA.push({ duong: 'POST /playbook/ap-dung', body: b })
    const tu = chan(b.version)
    if (tu) return tu
    tt = {
      ...tt,
      nut: structuredClone(MAU_GIA),
      tuTemplate: TEMPLATE_VERSION_GIA,
      version: tt.version + 1,
    }
    return HttpResponse.json(kichBanGia())
  }),
  http.put('/api/v1/playbook/role-dung', async ({ request }) => {
    const b = (await request.json()) as { version: number; roles: string[] }
    GHI_GIA.push({ duong: 'PUT /playbook/role-dung', body: b })
    const la = b.roles.filter((r) => !['customer', 'sale'].includes(r))
    if (la.length)
      return HttpResponse.json(
        {
          error: {
            code: 'PLAYBOOK_ROLE_KHONG_CO',
            message: `Role không có trong workspace: ${la.join(', ')}`,
          },
        },
        { status: 422 },
      )
    const tu = chan(b.version)
    if (tu) return tu
    tt = { ...tt, roleDung: [...new Set(b.roles)], version: tt.version + 1 }
    return HttpResponse.json(kichBanGia())
  }),
  http.get('/api/v1/playbook/:nut/luot', ({ params, request }) => {
    const chiKhongDat = new URL(request.url).searchParams.get('dat') === 'false'
    const ds = params.nut === 'che_dat' ? FAKE_LUOT : []
    return HttpResponse.json({ luot: chiKhongDat ? ds.filter((l) => l.dat === false) : ds })
  }),
]
