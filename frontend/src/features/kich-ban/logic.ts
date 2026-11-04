import { MUOI_HAI_KY_NANG } from '@/lib/tools'
import type { NutKichBan, SoDoNut } from './api'

export type Mau = 'xanh' | 'vang' | 'do' | 'xam'

export function mauTiLe(s: SoDoNut | undefined, nhap: boolean): Mau {
  if (nhap || !s || s.tiLeDat === null || s.daCham < 5) return 'xam'
  if (s.tiLeDat >= 0.8) return 'xanh'
  if (s.tiLeDat >= 0.6) return 'vang'
  return 'do'
}

// Thứ tự hành trình khách (loader agent: NHOM). Nhóm lạ xuống cuối.
export const THU_TU_NHOM = [
  'mo_dau',
  'kham_pha',
  'tim_can',
  'tai_lieu',
  'phan_doi',
  'chot',
  'dat_lich',
  'chuyen_nguoi',
  'ket_thuc',
  'khac',
] as const

export const TEN_NHOM: Record<string, string> = {
  mo_dau: 'Mở đầu',
  kham_pha: 'Khám phá',
  tim_can: 'Tìm căn',
  tai_lieu: 'Tài liệu',
  phan_doi: 'Phản đối',
  chot: 'Chốt',
  dat_lich: 'Đặt lịch',
  chuyen_nguoi: 'Chuyển người',
  ket_thuc: 'Kết thúc',
  khac: 'Khác',
}

export const TEN_LOAI: Record<string, string> = {
  phan_xa: 'Xử lý trong một lượt',
  luong: 'Nhiều bước',
}

/** Tên nghiệp vụ của nút — agent xuất `ten`; JSON cũ chưa có thì rơi về mã. */
export const tenNut = (n: Pick<NutKichBan, 'id'> & { ten?: string | undefined }) => n.ten || n.id

/** Tỷ lệ đạt bằng CHỮ — chấm màu không được là nơi duy nhất nói con số (WCAG 1.4.1). */
/** «71%» khi đã đủ lượt chấm, `null` khi chưa — bản ngắn của `pct` cho nhãn trên sơ đồ. */
export const pctNgan = (s: SoDoNut | undefined) =>
  s && s.tiLeDat !== null && s.daCham >= 5 ? `${Math.round(s.tiLeDat * 100)}%` : null

export const pct = (s: SoDoNut | undefined) =>
  s && s.tiLeDat !== null && s.daCham >= 5
    ? `đạt ${Math.round(s.tiLeDat * 100)}%`
    : 'chưa đủ lượt chấm'

/** Ô «Tìm tình huống»: khớp tên, mã hoặc một dấu hiệu, không phân biệt hoa thường. */
export function khop(n: NutKichBan, q: string): boolean {
  const k = q.trim().toLowerCase()
  if (!k) return true
  return [tenNut(n), n.id, ...n.dau_hieu].some((s) => s.toLowerCase().includes(k))
}

// Khoá `tiep` (điều kiện chuyển nút) do agent đặt — chưa có ở đây thì đọc thô bỏ gạch dưới.
const TEN_CANH: Record<string, string> = {
  lan_2: 'gặp lần 2',
  dong_y_xem: 'khách đồng ý đi xem',
  san_sang_coc: 'khách sẵn sàng cọc',
  san_sang_giu_cho: 'khách sẵn sàng giữ chỗ',
  khach_ung: 'khách ưng căn',
  khong_ra_can: 'không ra căn nào',
  vuot_ngan_sach: 'căn vượt ngân sách',
  lai_khong_co_dinh: 'lo lãi suất thả nổi',
  tra_nhieu: 'chê trả nhiều',
}

export function nhanCanh(khoa: string): string {
  return TEN_CANH[khoa] ?? khoa.replaceAll('_', ' ')
}

export function canh(
  nodes: NutKichBan[],
): { id: string; source: string; target: string; label: string }[] {
  const ids = new Set(nodes.map((n) => n.id))
  return nodes.flatMap((n) =>
    Object.entries(n.tiep)
      .filter(([, dich]) => ids.has(dich))
      .map(([k, dich]) => ({
        id: `${n.id}->${k}->${dich}`,
        source: n.id,
        target: dich,
        label: nhanCanh(k),
      })),
  )
}

// ---- Sơ đồ cây trái → phải: gốc → nhóm → tình huống, mỗi tình huống một hàng.

export const CAY = {
  gocRong: 170, // hộp gốc chiếm x 0 → gocRong
  xNhom: 400, // chấm nhóm; tên nhóm nằm trên đoạn thẳng ngay trước nó
  xNut: 560, // chấm tình huống; nhãn bắt đầu từ xNut + 12
  hang: 26,
  kheNhom: 14, // thêm giữa hai nhóm
  lan: 120, // chừa bên phải nhãn dài nhất cho đường chuyển tiếp
} as const
// ponytail: ước bề ngang nhãn theo số ký tự (15px ≈ 8,5px/ký tự, dư một chút) — đường chuyển tiếp nối
// vào cuối nhãn có thể hở vài px; đo thật bằng getComputedTextLength nếu thấy lệch.
const PX_KY_TU = 8.5
/** Chỗ cho « · 71%» in sau tên (12,5px ≈ 5 ký tự 15px) — %đạt bằng CHỮ, không chỉ màu chấm. */
const CHU_PCT = 5

const thuTu = (nhom: string) => {
  const i = (THU_TU_NHOM as readonly string[]).indexOf(nhom)
  return i === -1 ? THU_TU_NHOM.length : i
}

export interface BoCucCay {
  gocY: number
  nhom: { nhom: string; y: number; so: number }[]
  /** `cuoi` = x cuối nhãn (ước lượng). */
  nut: Record<string, { y: number; cuoi: number }>
  rong: number
  cao: number
}

/** `duoi`: chữ in thêm sau tên theo id (« · khác mẫu») — tính vào bề ngang để mũi tên chuyển tiếp không đè lên. */
export function boCucCay(nodes: NutKichBan[], duoi: Record<string, string> = {}): BoCucCay {
  const theoNhom = new Map<string, NutKichBan[]>()
  for (const n of [...nodes].sort(
    (a, b) => thuTu(a.nhom) - thuTu(b.nhom) || a.id.localeCompare(b.id),
  ))
    theoNhom.set(n.nhom, [...(theoNhom.get(n.nhom) ?? []), n])
  const out: BoCucCay = { gocY: 0, nhom: [], nut: {}, rong: 0, cao: 0 }
  let y = 0
  for (const [nhom, ds] of theoNhom) {
    ds.forEach((n, i) => {
      const chu =
        tenNut(n).length + (n.loai === 'luong' ? 2 : 0) + CHU_PCT + (duoi[n.id]?.length ?? 0)
      out.nut[n.id] = { y: y + i * CAY.hang, cuoi: CAY.xNut + 12 + chu * PX_KY_TU }
    })
    out.nhom.push({ nhom, y: y + ((ds.length - 1) * CAY.hang) / 2, so: ds.length })
    y += ds.length * CAY.hang + CAY.kheNhom
  }
  const ys = Object.values(out.nut).map((p) => p.y)
  out.cao = ys.length ? Math.max(...ys) : 0
  out.gocY = out.cao / 2
  out.rong = Math.max(CAY.xNut, ...Object.values(out.nut).map((p) => p.cuoi)) + CAY.lan
  return out
}

// ---- Đọc dễ: chữ nút viết cho LLM (tên tool, mã nút, từ kỹ thuật) → chữ nghiệp vụ cho người xem.

const NHAN_KY_NANG: Record<string, string> = Object.fromEntries(
  MUOI_HAI_KY_NANG.map((k) => [k.ten, k.nhan]),
)

// Thứ tự có nghĩa: cụm dài trước từ đơn.
const TU_KY_THUAT: [RegExp, string][] = [
  [/kết quả tool/g, 'kết quả tra cứu'],
  [/\btool\b/g, 'công cụ'],
  [/\bkb\b/g, 'tài liệu'],
  [/\b(?:not_found|not-found)\b/g, 'không tìm thấy'],
  [/\bresolved\b/g, 'đã nhận ra'],
  [/\bambiguous\b/g, 'còn mơ hồ'],
  [/\bfilter_sql\b/g, 'bộ lọc'],
  [/\border_sql\b/g, 'cách sắp xếp'],
  [/\bupsell_units\b/g, 'căn vượt ngân sách'],
  [/\ball_projects\b/g, 'mọi dự án'],
  [/\bproject_code\b/g, 'mã dự án'],
  [/\bcriteria\b/g, 'tiêu chí'],
  [/\bindex\b/g, 'trang'],
  [/\bcounts\b/g, 'số lượng'],
  [/\brelaxed\b/g, 'đã nới tiêu chí'],
  [/\binstruction\b/g, 'chỉ dẫn'],
  [/\bfield\b/g, 'phần'],
  [/\bmessage\b/g, 'lời nhắn'],
  [/\b(?:data|DATA)\b/g, 'dữ liệu'],
  [/\becho\b/g, 'nhắc lại'],
]

export function docDe(text: string, ten: Record<string, string>): string {
  const tools = Object.keys(NHAN_KY_NANG).join('|')
  const ids = Object.keys(ten)
    .sort((a, b) => b.length - a.length)
    .join('|')
  let s = text.replace(
    new RegExp(`\\b(${tools})\\b(\\([^)]*\\))?`, 'g'),
    (_, t: string) => `«${NHAN_KY_NANG[t]}»`,
  )
  if (ids) s = s.replace(new RegExp(`\\b(${ids})\\b`, 'g'), (_, id: string) => `«${ten[id]}»`)
  for (const [re, thay] of TU_KY_THUAT) s = s.replace(re, thay)
  return s
}

// Tool nội bộ agent dùng làm «không cần tra» — không nằm trong sổ 12 kỹ năng của portal (`lib/tools.ts`).
const NHAN_THEM: Record<string, string> = { no_lookup_needed: 'Không cần tra cứu' }
export const nhanKyNang = (t: string) => NHAN_KY_NANG[t] ?? NHAN_THEM[t] ?? t

/** Chữ của một nút cho người đọc: `hien` agent viết sẵn; mục nào vắng hoặc lệch số dòng thì dịch chữ gốc bằng `docDe`.
 *  `dich` tra ngược chữ gốc → chữ người đọc: classifier chép nguyên văn dòng `lam`/`cam` vào số đo «hay thiếu / hay phạm»,
 *  nên số đo nói cùng một câu với mục ngay dưới nó. Dòng classifier tự viết thì vẫn qua `docDe`. */
export function banDoc(n: NutKichBan, ten: Record<string, string>) {
  const h = n.hien ?? {}
  const ds = (goc: string[], moi: string[] | undefined) =>
    moi?.length === goc.length ? moi : goc.map((s) => docDe(s, ten))
  const buocGoc = n.buoc.map((b) => b.lam)
  const lam = ds(n.lam, h.lam)
  const cam = ds(n.cam, h.cam)
  const buoc = ds(buocGoc, h.buoc)
  const cap = (goc: string[], moi: string[]) => goc.map((s, i) => [s, moi[i]!] as const)
  const theoGoc = new Map([...cap(n.lam, lam), ...cap(n.cam, cam), ...cap(buocGoc, buoc)])
  return {
    dauHieu: ds(n.dau_hieu, h.dau_hieu),
    lam,
    cam,
    buoc,
    khiThieu: n.khi_thieu ? (h.khi_thieu ?? docDe(n.khi_thieu, ten)) : '',
    dich: (s: string) => theoGoc.get(s) ?? docDe(s, ten),
  }
}

/** «dd/mm hh:mm» — giờ máy người xem. */
export const gio = (iso: string) =>
  new Date(iso).toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
