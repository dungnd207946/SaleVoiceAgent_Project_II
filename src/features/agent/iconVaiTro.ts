/**
 * Bảng MÃ ↔ icon cho role người dùng agent (`role_config.icon`, backend `0967`).
 *
 * Backend chỉ lưu MÃ và chỉ kiểm hình dạng chuỗi (`^[a-z0-9_]{1,32}$`) — danh sách hình là
 * của FE, nên thêm một hình là thêm một dòng ở đây, không phải một migration. Mã tiếng
 * Việt không dấu (không phải tên icon Lucide): đổi thư viện icon thì dữ liệu không đổi.
 *
 * ⚠ ĐỪNG ĐỔI hay XOÁ một `ma` đã phát hành — hàng trong DB đang mang nó. Mã lạ không làm
 * vỡ màn (rơi về `iconTheoKey`), nhưng role đó sẽ lặng lẽ đổi hình.
 */
import type { IconName } from '@/components/icons'
import { KEY_ROLE_MAC_DINH, type VaiTro, type VaiTroMeta } from './api'

export interface IconVaiTro {
  ma: string
  icon: IconName
  /** Nhãn đọc cho trình đọc màn hình ở bộ chọn icon — không hiện trên tab. */
  nhan: string
}

export const ICON_VAI_TRO: readonly IconVaiTro[] = [
  { ma: 'khach', icon: 'vaiTroKhach', nhan: 'Khách hàng' },
  { ma: 'sale', icon: 'vaiTroSale', nhan: 'Kinh doanh' },
  { ma: 'vuong_mien', icon: 'vtVuongMien', nhan: 'VIP' },
  { ma: 'dau_tu', icon: 'vtDauTu', nhan: 'Nhà đầu tư' },
  { ma: 'doi_tac', icon: 'vtDoiTac', nhan: 'Đối tác' },
  { ma: 'doanh_nghiep', icon: 'vtDoanhNghiep', nhan: 'Doanh nghiệp' },
  { ma: 'chu_nha', icon: 'vtChuNha', nhan: 'Chủ nhà' },
  { ma: 'ho_tro', icon: 'vtHoTro', nhan: 'Hỗ trợ' },
  { ma: 'nha_thau', icon: 'vtNhaThau', nhan: 'Nhà thầu' },
  { ma: 'dai_ly', icon: 'vtDaiLy', nhan: 'Đại lý' },
  { ma: 'ngan_hang', icon: 'vtNganHang', nhan: 'Ngân hàng' },
  { ma: 'cao_cap', icon: 'vtCaoCap', nhan: 'Cao cấp' },
  { ma: 'marketing', icon: 'vtMarketing', nhan: 'Marketing' },
  { ma: 'khach_moi', icon: 'vtKhachMoi', nhan: 'Khách mới' },
  { ma: 'nhom', icon: 'vtNhom', nhan: 'Nhóm' },
  { ma: 'dao_tao', icon: 'vtDaoTao', nhan: 'Đào tạo' },
  { ma: 'phap_ly', icon: 'vtPhapLy', nhan: 'Pháp lý' },
]

const THEO_MA = new Map(ICON_VAI_TRO.map((i) => [i.ma, i]))

/** Icon cho role chưa có mã (hàng tạo trước khi có cột) hoặc mang mã lạ: chọn TẤT ĐỊNH
 *  theo `key` — cùng role luôn cùng hình, qua mọi lần tải và mọi máy. */
function iconTheoKey(key: VaiTro): IconName {
  if (key === KEY_ROLE_MAC_DINH) return 'vaiTroKhach'
  if (key === 'sale') return 'vaiTroSale'
  const tuChon = ICON_VAI_TRO.slice(2)
  let h = 0
  for (const c of key) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return (tuChon[h % tuChon.length] as IconVaiTro).icon
}

export function iconCua(v: Pick<VaiTroMeta, 'key' | 'icon'>): IconName {
  return (v.icon && THEO_MA.get(v.icon)?.icon) || iconTheoKey(v.key)
}

/** Gợi ý cho role MỚI: hình đầu tiên chưa role nào dùng — mười role mười hình, tới khi
 *  hết bảng thì mới lặp. Bỏ qua hai hình của Khách hàng/Sale: chúng mang nghĩa riêng. */
export function iconGoiY(vaiTro: readonly Pick<VaiTroMeta, 'icon'>[]): string {
  const daDung = new Set(vaiTro.map((v) => v.icon))
  const tuChon = ICON_VAI_TRO.slice(2)
  return (tuChon.find((i) => !daDung.has(i.ma)) ?? tuChon[0])!.ma
}
