/**
 * Chân dung khách — chọn khoá nào của `contacts.profile` hiện, dưới nhãn gì. Hàm THUẦN.
 *
 * Nguồn khoá: `CUSTOMER_FIELDS` của tool `update_customer` bên `odyssey-agent`
 * (`agent/tools/schemas.py`) + `interest_level` do Jev ghi. Bản chép tay, không cổng
 * parity: agent thêm khoá mới thì nó KHÔNG hiện cho tới khi thêm vào `NHOM` — cố ý,
 * một khoá lạ in nguyên văn snake_case lên màn sale đọc là tệ hơn vắng mặt.
 */
import { nhanDoiTuong } from './lead'

export interface DongChanDung {
  readonly nhan: string
  /** `null` = agent chưa khai thác được. */
  readonly gia: string | null
}

export interface NhomChanDung {
  readonly tieuDe: string
  readonly dong: readonly DongChanDung[]
}

interface Truong {
  readonly khoa: string
  readonly nhan: string
  /** Hiện cả khi trống («Chưa khai thác») — chỉ cho thứ sale CẦN hỏi ra. */
  readonly luonHien?: boolean
  readonly dich?: (v: string) => string | null
}

const GIOI_TINH: Record<string, string> = { M: 'Nam', F: 'Nữ' }
const MUC_QUAN_TAM: Record<string, string> = { cao: 'Cao', vua: 'Vừa', thap: 'Thấp' }

const NHOM: readonly { tieuDe: string; truong: readonly Truong[] }[] = [
  {
    tieuDe: 'Nhu cầu',
    truong: [
      { khoa: 'project_interest', nhan: 'Dự án quan tâm', luonHien: true },
      { khoa: 'purpose', nhan: 'Mục đích', luonHien: true },
      { khoa: 'budget', nhan: 'Ngân sách', luonHien: true },
      { khoa: 'bedroom_count', nhan: 'Số phòng ngủ', luonHien: true },
      { khoa: 'preferred_area', nhan: 'Khu vực muốn mua', luonHien: true },
    ],
  },
  {
    tieuDe: 'Khả năng mua',
    truong: [
      { khoa: 'audience', nhan: 'Đối tượng', luonHien: true, dich: nhanDoiTuong },
      { khoa: 'finance', nhan: 'Tài chính', luonHien: true },
      { khoa: 'timeline', nhan: 'Thời điểm mua', luonHien: true },
      { khoa: 'decision_maker', nhan: 'Người quyết định', luonHien: true },
      { khoa: 'interest_level', nhan: 'Mức quan tâm', dich: (v) => MUC_QUAN_TAM[v] ?? v },
      { khoa: 'broker_client', nhan: 'Khách của môi giới' },
    ],
  },
  {
    tieuDe: 'Cá nhân',
    truong: [
      { khoa: 'full_name', nhan: 'Họ tên' },
      // Agent ghi «No Name» làm mặc định ở lần chèn đầu khi khách chưa xưng tên.
      { khoa: 'name', nhan: 'Tên gọi', dich: (v) => (v === 'No Name' ? null : v) },
      { khoa: 'gender', nhan: 'Giới tính', dich: (v) => GIOI_TINH[v] ?? v },
      { khoa: 'birthday', nhan: 'Ngày sinh' },
      { khoa: 'email', nhan: 'Email' },
      { khoa: 'workplace', nhan: 'Nơi làm việc' },
      { khoa: 'is_buyer', nhan: 'Người mua' },
      { khoa: 'is_noble_customer', nhan: 'Khách Noble' },
      { khoa: 'noble_info', nhan: 'Thông tin Noble' },
    ],
  },
]

/** jsonb do agent ghi: chuỗi hoặc bool. Kiểu khác (object, mảng) không có cách hiện đúng ⇒ bỏ. */
function chuoiCua(v: unknown): string | null {
  if (typeof v === 'boolean') return v ? 'Có' : 'Không'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string' && v.trim() !== '') return v.trim()
  return null
}

/** `tenDuAn` = mã → tên lấy từ chính các phiên của khách (không thêm request). */
export function nhomChanDung(
  hoSo: Readonly<Record<string, unknown>>,
  tenDuAn: ReadonlyMap<string, string>,
): NhomChanDung[] {
  return NHOM.map((n) => ({
    tieuDe: n.tieuDe,
    dong: n.truong
      .map((t) => {
        const tho = chuoiCua(hoSo[t.khoa])
        const dich = t.khoa === 'project_interest' ? (v: string) => tenDuAn.get(v) ?? v : t.dich
        return { nhan: t.nhan, gia: tho !== null && dich ? dich(tho) : tho, luonHien: t.luonHien }
      })
      .filter((d) => d.gia !== null || d.luonHien)
      .map(({ nhan, gia }) => ({ nhan, gia })),
  })).filter((n) => n.dong.length > 0)
}

/** `notes` agent cộng dồn bằng `;` — tách thành từng mẩu. */
export function ghiChuCua(hoSo: Readonly<Record<string, unknown>>): string[] {
  const v = hoSo.notes
  return typeof v === 'string'
    ? v
        .split(';')
        .map((s) => s.trim())
        .filter(Boolean)
    : []
}

/** Agent chưa khai thác được gì: không một trường nào có giá trị. */
export function chuaCoGi(nhom: readonly NhomChanDung[]): boolean {
  return nhom.every((n) => n.dong.every((d) => d.gia === null))
}

/** Khoá `_WEIGHTS` của `agent/lead_score.py`. Mã lạ hiện NGUYÊN VĂN, không đoán nhãn. */
const TIN_HIEU: Record<string, string> = {
  co_doi_tuong: 'Rõ đối tượng',
  co_du_an: 'Có dự án quan tâm',
  co_muc_dich: 'Rõ mục đích',
  co_ngan_sach: 'Có ngân sách',
  co_phong: 'Rõ số phòng',
  co_tai_chinh: 'Có phương án tài chính',
  thoi_diem_gan: 'Mua trong 6 tháng',
  da_xem_can: 'Đã xem căn',
  muon_xem_nha: 'Muốn xem nhà',
  hoi_tien: 'Hỏi giá',
  quan_tam_cao: 'Quan tâm cao',
}

export function nhanTinHieu(ma: string): string {
  return TIN_HIEU[ma] ?? ma
}
