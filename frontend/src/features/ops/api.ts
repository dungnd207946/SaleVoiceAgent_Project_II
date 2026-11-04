/**
 * Client HTTP của M7 — màn Hội thoại.
 *
 * Kiểu ở đây là bản chép tay của `modules/ops/contracts.py`. Nguồn là bên Python.
 * Lệch tên field thì màn hiện `undefined` chứ không nổ — nên đổi thì đổi cùng commit.
 */
import { goi as goiApi } from '@/lib/http'
import type { LocStage } from './lead'

const GOC = '/api/v1'

/**
 * Cỡ trang của `/convos` — ô «Mỗi trang» và mặc định (người dùng chốt
 * 2026-09-24: 10). KHÔNG còn khớp `TRANG_MAC_DINH = 50` của `contracts.py`,
 * và không cần khớp: `danhSachKhach` luôn gửi `limit` TƯỜNG MINH, mặc định
 * phía backend chỉ áp cho ai gọi không kèm `limit`. Mọi cỡ ở đây phải ≤
 * `GIOI_HAN_TRANG = 200` của backend, không thì 422.
 *
 * Bộ cỡ riêng, không dùng `SO_HANG_CHON` (20/50/100) của `components/ui/
 * ThanhTrang` — thêm 10 vào đó là đổi ô chọn của bốn bảng realestate.
 */
export const SO_HANG_KHACH = [10, 20, 50, 100] as const
export const SO_HANG_KHACH_MAC_DINH = 10

function goi<T>(duong: string, than?: { method: string; body: unknown }): Promise<T> {
  return goiApi<T>(
    `${GOC}${duong}`,
    than && { method: than.method, body: JSON.stringify(than.body) },
    `${than?.method ?? 'GET'} ${duong}`,
  )
}

/** `''` = nhóm «Chưa có số». Trên đường dẫn nó đi bằng `'_'` — xem `duongDanKhach`. */
export interface Khach {
  readonly phone: string
  readonly ten: string | null
  /** Data URI SVG DiceBear backend vẫn trả — FE THÔI ĐỌC từ 2026-08-25 (lịch sử
   *  hội thoại vẽ chữ cái mặc định như bảng Thành viên, xem `avatar.tsx`). Giữ
   *  trường vì hợp đồng backend không đổi, chỉ không còn ai đọc. */
  readonly avatar?: string | null
  readonly soPhien: number
  readonly ganNhat: string
  readonly dauTien: string
  readonly daChuyen: boolean
  readonly summaryCuoi: string | null
  readonly duAn: string | null
  readonly tenDuAn: string | null
  /** Lead MỚI NHẤT của khách — lead của phiên mới nhất có lead (spec §2). `null` = chưa
   *  phân loại. TUỲ CHỌN: backend cũ chưa trả khoá ⇒ `undefined`, xử như `null`. */
  readonly leadStage?: string | null
  readonly leadScore?: number | null
  readonly audience?: string | null
}

export interface TrangKhach {
  readonly items: readonly Khach[]
  readonly tongKhach: number
  readonly tongPhien: number
}

export interface Phien {
  readonly sessionId: string
  /** `customer_name` của CHÍNH phiên này — header lấy của phiên mới nhất. */
  readonly ten: string | null
  /** Data URI SVG DiceBear backend vẫn trả — FE THÔI ĐỌC từ 2026-08-25 (lịch sử
   *  hội thoại vẽ chữ cái mặc định như bảng Thành viên, xem `avatar.tsx`). Giữ
   *  trường vì hợp đồng backend không đổi, chỉ không còn ai đọc. */
  readonly avatar?: string | null
  readonly batDau: string | null
  readonly ketThuc: string | null
  readonly soLuot: number
  /** Nội dung lượt đầu tiên (`seq = 0`). `null` khi `soLuot === 0`. */
  readonly tinNhanDau: string | null
  readonly summary: string | null
  readonly duAn: string | null
  readonly tenDuAn: string | null
  readonly daChuyen: boolean
  readonly runningVersion: number | null
  /** Kênh phiên đến từ đâu (`'chat'`/`'voice'`...). `null` = chưa biết — KHÔNG suy đoán hộ. */
  readonly source: string | null
  /** Số điện thoại của khách — `null` = nhóm «Chưa có số». */
  readonly phone: string | null
  /** Lead của CHÍNH phiên này. `null` = phiên không chuyển sale. Tuỳ chọn như `Khach`. */
  readonly leadStage?: string | null
  readonly leadScore?: number | null
  readonly audience?: string | null
}

/** `role` KHÔNG phải union: DB cố ý không có CHECK, giá trị lạ vẫn tới được đây. */
export interface Luot {
  readonly seq: number
  readonly role: string
  readonly content: string
  readonly taoLuc: string
  readonly meta: Record<string, unknown>
}

export interface ChiTietPhien {
  readonly phien: Phien
  readonly luot: readonly Luot[]
  /** Nguồn DỰ PHÒNG — chỉ dùng khi không lượt nào mang `meta.tool_calls`. */
  readonly skillCalls: readonly unknown[]
}

export interface LocKhach {
  readonly q?: string
  readonly tuNgay?: '7' | '30' | 'all'
  readonly daChuyen?: boolean
  /** Lọc theo lead mới nhất; `'none'` = khách chưa có lead. Vắng = mọi stage. */
  readonly stage?: LocStage
  /** Trang hiện tại, đếm từ 1. Vắng = trang 1. */
  readonly trang?: number
  /** Số khách mỗi trang. Vắng = `SO_HANG_KHACH_MAC_DINH`. */
  readonly soHang?: number
}

/** Sentinel của nhóm «Chưa có số» — phải khớp `contracts.PHONE_TRONG` bên Python. */
export const PHONE_TRONG = '_'

export function duongDanKhach(phone: string): string {
  return phone === '' ? PHONE_TRONG : phone
}

export async function danhSachKhach(loc: LocKhach = {}): Promise<TrangKhach> {
  const p = new URLSearchParams()
  if (loc.q) p.set('q', loc.q)
  p.set('tu_ngay', loc.tuNgay ?? '30')
  if (loc.stage) p.set('lead_stage', loc.stage)
  if (loc.daChuyen) p.set('da_chuyen', 'true')
  const soHang = loc.soHang ?? SO_HANG_KHACH_MAC_DINH
  p.set('limit', String(soHang))
  p.set('offset', String(((loc.trang ?? 1) - 1) * soHang))
  return goi<TrangKhach>(`/convos/khach?${p.toString()}`)
}

export async function phienCuaKhach(phone: string): Promise<Phien[]> {
  return goi<Phien[]>(`/convos/khach/${encodeURIComponent(phone)}/phien`)
}

/**
 * Chân dung khách — những gì AGENT đã khai thác về một số, gộp qua mọi phiên.
 *
 * `hoSo` là `contacts.profile` NGUYÊN VĂN (khoá snake_case do agent `update_customer`
 * đặt) — `chanDung.ts` chọn khoá nào hiện. Giá trị có thể là chuỗi hoặc bool.
 */
export interface ChanDung {
  readonly hoSo: Readonly<Record<string, unknown>>
  readonly ghiNho: string | null
  /** Mã tín hiệu chấm điểm lead (`co_ngan_sach`…) của lead hiện tại. */
  readonly tinHieu: readonly string[]
  readonly capNhatLuc: string | null
}

export async function chanDungKhach(phone: string): Promise<ChanDung> {
  return goi<ChanDung>(`/convos/khach/${encodeURIComponent(phone)}/chan-dung`)
}

export async function chiTietPhien(sessionId: string): Promise<ChiTietPhien> {
  return goi<ChiTietPhien>(`/convos/phien/${encodeURIComponent(sessionId)}`)
}

// ── Overview — màn /dashboard ───────────────────────────────────────────────

export const KHOA_OVERVIEW = ['overview'] as const

/** Hàng «Dữ liệu ngoài» của ô Kiến thức — đọc `/kb-web/overview` (quyền `kb_web.read`; thiếu quyền ⇒ 403 ⇒ không hiện hàng). */
export const KHOA_HO_SO_NGOAI = ['overview', 'du-lieu-ngoai'] as const

export async function hoSoNgoai(): Promise<MucKienThuc> {
  const t = await goi<{ soDuAn?: number; soDuAnCoHoSo?: number }>('/kb-web/overview')
  return { khoa: 'duLieuNgoai', thay: t.soDuAnCoHoSo ?? 0, tong: t.soDuAn ?? 0 }
}

export interface NgayHoiThoai {
  /** ISO `YYYY-MM-DD`. */
  readonly ngay: string
  readonly chat: number
  readonly voice: number
  readonly khac: number
  readonly tong: number
}

export interface KenhHoiThoai {
  /** Nguyên văn `conversations.source`. `null` = agent bản cũ chưa gửi. */
  readonly kenh: string | null
  readonly n: number
}

export type SaoKey = '1' | '2' | '3' | '4' | '5'

export interface MucKienThuc {
  readonly khoa: string
  readonly thay: number
  readonly tong: number
}

export interface Overview {
  readonly moc: { readonly tuNgay: string; readonly tinhDen: string }
  readonly hoiThoai: {
    readonly tong: number
    readonly truoc: number
    readonly theoNgay: readonly NgayHoiThoai[]
    readonly theoKenh: readonly KenhHoiThoai[]
  }
  readonly chuyenSale: { readonly chuyen: number; readonly tuXuLy: number }
  readonly danhGia: {
    readonly trungBinh: number
    /** `null` = kỳ trước chưa có lượt nào ⇒ KHÔNG vẽ mũi tên delta. */
    readonly truoc: number | null
    readonly tong: number
    readonly theoSao: Readonly<Record<SaoKey, number>>
  }
  readonly kienThuc: { readonly muc: readonly MucKienThuc[] }
}

/**
 * Chuẩn hoá MỘT phần tử của `theoNgay`.
 *
 * Khiên phải xuống tới PHẦN TỬ, không dừng ở mảng: `theoNgay ?? []` chỉ cứu ca
 * backend bỏ hẳn mảng. Ca backend cũ gửi mảng đủ hàng nhưng THIẾU một khoá
 * trong hàng (`khac` chẳng hạn — nó là khoá MỚI NHẤT của `NgayOut`, tức khoá
 * đầu tiên vắng mặt khi API chưa deploy) lọt thẳng vào `Y(undefined)` = `NaN`,
 * và một `<path d="M NaN NaN …">` bị trình duyệt bỏ qua LẶNG LẼ — đường biến
 * mất, không lỗi nào nổ.
 *
 * `tong` là ngoại lệ DUY NHẤT không rơi về `0`: hợp đồng định nghĩa nó bằng
 * đúng tổng ba thành phần, nên dựng lại từ chúng là ĐỌC hợp đồng chứ không
 * phải bịa số (khác `moc.tuNgay` — ở đó không có gì trong payload tái tạo
 * được giá trị thiếu, nên nó rơi về chuỗi rỗng và màn không vẽ gì). Để `?? 0`
 * ở đây thì tooltip in ra «Chat 27 · Voice 17 · Khác 16 · Tổng 0».
 */
function chuanHoaNgay(n: Partial<NgayHoiThoai> | undefined): NgayHoiThoai {
  const chat = n?.chat ?? 0
  const voice = n?.voice ?? 0
  const khac = n?.khac ?? 0
  return { ngay: n?.ngay ?? '', chat, voice, khac, tong: n?.tong ?? chat + voice + khac }
}

/**
 * MỘT lượt gọi cho cả màn.
 *
 * Mọi mảng/bậc đều qua khiên `?? []` / `?? 0` — cùng lý lẽ `chuanHoaFeedback`
 * ở `features/quality/api.ts`: backend chưa deploy bản mới bỏ HẲN khoá khỏi
 * JSON, và `undefined` lọt mọi guard `!== null` ở component. Ở đây nó còn nặng
 * hơn: `theoNgay` là thứ biểu đồ `.map()` thẳng.
 *
 * «Mọi mảng/bậc» tính CẢ phần tử BÊN TRONG ba mảng (`theoNgay` · `theoKenh` ·
 * `kienThuc.muc`) — trước round fix 2026-08-13 câu trên là một lời hứa quá
 * tay: ba mảng được thay bằng `[]` khi vắng, còn ruột từng phần tử thì không
 * ai chạm. Nay đúng như đã hứa.
 */
export async function overview(): Promise<Overview> {
  const t = await goi<Overview>('/overview')
  const sao = (t.danhGia?.theoSao ?? {}) as Partial<Record<SaoKey, number>>
  return {
    // Chuỗi RỖNG, không phải `new Date()` bịa ra: mốc thời gian trống thì hiện
    // ra trống — người xem thấy ngay là thiếu. Bịa một ngày vào đó là màn nói
    // dối về khoảng thời gian nó đang tóm tắt.
    moc: { tuNgay: t.moc?.tuNgay ?? '', tinhDen: t.moc?.tinhDen ?? '' },
    hoiThoai: {
      tong: t.hoiThoai?.tong ?? 0,
      truoc: t.hoiThoai?.truoc ?? 0,
      theoNgay: (t.hoiThoai?.theoNgay ?? []).map(chuanHoaNgay),
      // `kenh` để `?? null` chứ không `?? ''`: `null` ĐÃ là một giá trị hợp lệ
      // và có nghĩa của trường này («agent bản cũ chưa gửi `source`» ⇒ hiện
      // «Chưa rõ»), nên khoá vắng gộp vào đúng nhánh đó là đọc đúng nghĩa.
      theoKenh: (t.hoiThoai?.theoKenh ?? []).map((k) => ({ kenh: k?.kenh ?? null, n: k?.n ?? 0 })),
    },
    chuyenSale: { chuyen: t.chuyenSale?.chuyen ?? 0, tuXuLy: t.chuyenSale?.tuXuLy ?? 0 },
    danhGia: {
      trungBinh: t.danhGia?.trungBinh ?? 0,
      truoc: t.danhGia?.truoc ?? null,
      tong: t.danhGia?.tong ?? 0,
      theoSao: {
        '1': sao['1'] ?? 0,
        '2': sao['2'] ?? 0,
        '3': sao['3'] ?? 0,
        '4': sao['4'] ?? 0,
        '5': sao['5'] ?? 0,
      },
    },
    kienThuc: {
      // `khoa` rỗng thì `TheKienThuc` rơi về nhãn dự phòng (`NHAN[m.khoa] ??
      // …`) — một hàng vô danh nhưng vẽ được, thay vì một hàng `undefined`.
      muc: (t.kienThuc?.muc ?? []).map((m) => ({
        khoa: m?.khoa ?? '',
        thay: m?.thay ?? 0,
        tong: m?.tong ?? 0,
      })),
    },
  }
}

// ─── Hộp thư sale ────────────────────────────────────────────────────────────

/** Khớp `TRANG_CA` của `contracts.py`. Danh sách việc phải làm, không phải để duyệt. */
export const TRANG_CA = 10

/** `'new'` | `'contacted'` | `'done'` — nhưng KHÔNG union: agent không ký hợp đồng
 *  về tập giá trị này, một giá trị lạ vẫn phải hiện được. */
export type TrangThaiCa = string

export interface Ca {
  readonly id: number
  readonly sessionId: string
  /** `null` = chưa có số ở cả hàng ca lẫn `conversations` — sale không gọi lại được. */
  readonly phone: string | null
  readonly ten: string | null
  /** Data URI SVG DiceBear backend vẫn trả — FE THÔI ĐỌC từ 2026-08-25 (lịch sử
   *  hội thoại vẽ chữ cái mặc định như bảng Thành viên, xem `avatar.tsx`). Giữ
   *  trường vì hợp đồng backend không đổi, chỉ không còn ai đọc. */
  readonly avatar?: string | null
  readonly duAn: string | null
  readonly tenDuAn: string | null
  /** `null` = agent chủ động chuyển. Có giá trị = tên tool đã bí dữ liệu. */
  readonly toolThieuDuLieu: string | null
  readonly summary: string | null
  /** `null` ⇒ `summary` còn là bản tạm, bản LLM chưa về. */
  readonly summaryLuc: string | null
  readonly messageSeq: number | null
  readonly trangThai: TrangThaiCa
  readonly nguoiXuLy: string | null
  readonly xuLyLuc: string | null
  readonly ghiChu: string | null
  readonly kenh: string | null
  readonly soLuot: number
  readonly taoLuc: string
}

/** Một mục của ô lọc dự án: `ma` gửi lên server, `ten` là nhãn người đọc. */
export interface MucDuAn {
  readonly ma: string
  readonly ten: string | null
}

export interface TrangCa {
  readonly items: readonly Ca[]
  readonly tongCa: number
  readonly duAnCo: readonly MucDuAn[]
}

export type TabCa = 'new' | 'contacted' | 'done' | 'all'

export interface LocCa {
  readonly q?: string
  readonly trangThai?: TabCa
  readonly duAn?: string
  readonly sapXep?: 'moi' | 'cu'
  readonly trang?: number
}

export async function danhSachCa(loc: LocCa = {}): Promise<TrangCa> {
  const p = new URLSearchParams()
  if (loc.q) p.set('q', loc.q)
  p.set('trang_thai', loc.trangThai ?? 'all')
  if (loc.duAn) p.set('du_an', loc.duAn)
  if (loc.sapXep) p.set('sap_xep', loc.sapXep)
  p.set('limit', String(TRANG_CA))
  p.set('offset', String(((loc.trang ?? 1) - 1) * TRANG_CA))
  return goi<TrangCa>(`/escalations?${p.toString()}`)
}

export interface GhiChu {
  readonly id: number
  readonly noiDung: string
  readonly nguoi: string | null
  readonly luc: string
}

export async function lichSuGhiChu(id: number): Promise<GhiChu[]> {
  return goi<GhiChu[]>(`/escalations/${id}/notes`)
}

/** Mấy lượt thoại ngay TRƯỚC lúc agent chuyển ca. Mảng rỗng là ca bình thường —
 * bên agent ghi transcript fire-and-forget nên lượt cuối có thể chưa kịp lưu. */
export async function trichHoiThoai(id: number): Promise<Luot[]> {
  return goi<Luot[]>(`/escalations/${id}/trich`)
}

export async function nhanCa(
  id: number,
  than: { trangThai: 'new' | 'contacted' | 'done'; ghiChu?: string },
): Promise<Ca> {
  return goi<Ca>(`/escalations/${id}`, { method: 'PATCH', body: than })
}
