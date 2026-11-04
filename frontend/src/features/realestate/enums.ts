/**
 * 8 enum của KB BĐS ↔ nhãn tiếng Việt.
 *
 * VÌ SAO FILE RIÊNG: mỗi enum được dùng ở BA nơi — dropdown trong form, nhãn
 * hiển thị trong bảng danh sách, và dropdown bộ lọc. Để danh sách trong
 * component nghĩa là ba bản sao, và bản sao thứ ba luôn là bản thiếu giá trị mới.
 *
 * GIÁ TRỊ phải khớp ĐÚNG `Literal[...]` trong `modules/realestate/router.py` —
 * chúng khớp CHECK constraint ở `migrations/versions/0400_kb_real_estate.py`. Gõ
 * sai một giá trị ở đây thì form gửi lên nhận 422 `VALIDATION_ERROR` với một
 * `reason` nói về enum, không nói về lỗi chính tả — nên đây là chỗ phải chép,
 * không phải chỗ để sáng tạo.
 */

export interface MucChon {
  readonly value: string
  readonly nhan: string
}

function chon<const T extends readonly { value: string; nhan: string }[]>(muc: T): T {
  return muc
}

export const TRANG_THAI = chon([
  { value: 'draft', nhan: 'Bản nháp' },
  { value: 'published', nhan: 'Đã phát hành' },
  { value: 'archived', nhan: 'Lưu trữ' },
])

export const SALE_PHASE = chon([
  { value: 'sap_mo_ban', nhan: 'Sắp mở bán' },
  { value: 'dang_ban', nhan: 'Đang bán' },
  { value: 'ban_giao', nhan: 'Bàn giao' },
  { value: 'dong_gio_hang', nhan: 'Đóng giỏ hàng' },
])

export const LOAI_HINH = chon([
  { value: 'chung_cu', nhan: 'Chung cư' },
  { value: 'biet_thu', nhan: 'Biệt thự' },
  { value: 'lien_ke', nhan: 'Liền kề' },
  { value: 'shophouse', nhan: 'Shophouse' },
  { value: 'dat_nen', nhan: 'Đất nền' },
  { value: 'van_phong', nhan: 'Văn phòng' },
])

export const PRODUCT_TYPE = chon([
  { value: 'chung_cu', nhan: 'Chung cư' },
  { value: 'studio', nhan: 'Studio' },
  { value: 'duplex', nhan: 'Duplex' },
  { value: 'penthouse', nhan: 'Penthouse' },
  { value: 'officetel', nhan: 'Officetel' },
  { value: 'condotel', nhan: 'Condotel' },
  { value: 'biet_thu', nhan: 'Biệt thự' },
  { value: 'lien_ke', nhan: 'Liền kề' },
  { value: 'shophouse', nhan: 'Shophouse' },
  { value: 'nha_pho', nhan: 'Nhà phố' },
  { value: 'dat_nen', nhan: 'Đất nền' },
  { value: 'van_phong', nhan: 'Văn phòng' },
])

export const HUONG = chon([
  { value: 'dong', nhan: 'Đông' },
  { value: 'tay', nhan: 'Tây' },
  { value: 'nam', nhan: 'Nam' },
  { value: 'bac', nhan: 'Bắc' },
  { value: 'dong_bac', nhan: 'Đông Bắc' },
  { value: 'dong_nam', nhan: 'Đông Nam' },
  { value: 'tay_bac', nhan: 'Tây Bắc' },
  { value: 'tay_nam', nhan: 'Tây Nam' },
])

export const SALE_STATUS = chon([
  { value: 'available', nhan: 'Còn hàng' },
  { value: 'booked', nhan: 'Đã cọc' },
  { value: 'sold', nhan: 'Đã bán' },
])

export const KHU_VUC = chon([
  { value: 'mien_bac', nhan: 'Miền Bắc' },
  { value: 'mien_trung', nhan: 'Miền Trung' },
  { value: 'mien_nam', nhan: 'Miền Nam' },
])

export const CONTENT_TYPE = chon([
  { value: 'image', nhan: 'Ảnh' },
  { value: 'video', nhan: 'Video' },
])

export const MEDIA_CATEGORY = chon([
  { value: 'tong_quan', nhan: 'Tổng quan' },
  { value: 'ngoai_that', nhan: 'Ngoại thất' },
  { value: 'noi_that', nhan: 'Nội thất' },
  { value: 'tien_ich', nhan: 'Tiện ích' },
  { value: 'csbh', nhan: 'Chính sách bán hàng' },
  { value: 'mat_bang', nhan: 'Mặt bằng' },
  { value: 'vi_tri', nhan: 'Vị trí' },
  { value: 'tien_do', nhan: 'Tiến độ' },
])

export const MEDIA_CATEGORY_TAB_RIENG: readonly string[] = ['vi_tri', 'mat_bang', 'tien_do']

export const LOAI_TAI_LIEU = chon([
  { value: 'csbh', nhan: 'Chính sách bán hàng' },
  { value: 'phap_ly', nhan: 'Pháp lý' },
  { value: 'huong_dan', nhan: 'Hướng dẫn' },
  { value: 'khac', nhan: 'Khác' },
])

export const VIEW = chon([
  { value: 'song', nhan: 'Sông' },
  { value: 'ho', nhan: 'Hồ' },
  { value: 'bien', nhan: 'Biển' },
  { value: 'cong_vien', nhan: 'Công viên' },
  { value: 'san_golf', nhan: 'Sân golf' },
  { value: 'noi_khu', nhan: 'Nội khu' },
  { value: 'be_boi', nhan: 'Bể bơi' },
  { value: 'duong', nhan: 'Đường' },
  { value: 'thanh_pho', nhan: 'Thành phố' },
  { value: 'toa_doi_dien', nhan: 'Toà đối diện' },
])

export const BAN_GIAO_CAN = chon([
  { value: 'tho', nhan: 'Thô' },
  { value: 'co_ban', nhan: 'Hoàn thiện cơ bản' },
  { value: 'hoan_thien', nhan: 'Hoàn thiện' },
  { value: 'full_noi_that', nhan: 'Full nội thất' },
])

export const CO_KHONG = chon([
  { value: 'co', nhan: 'Có' },
  { value: 'khong', nhan: 'Không' },
])

/** Loại sản phẩm cao tầng — có toà, tầng, ban công; còn lại là thấp tầng (đất, mặt tiền). */
const CAO_TANG = new Set([
  'chung_cu',
  'studio',
  'duplex',
  'penthouse',
  'officetel',
  'condotel',
  'van_phong',
])

export function laCaoTang(productType: string | null | undefined): boolean {
  return CAO_TANG.has(productType ?? '')
}

const MAU_MAC_DINH = 'bg-badge-neutral-bg text-badge-neutral-fg'

export function mauLoaiTaiLieu(loai: string): string {
  return (
    {
      csbh: 'bg-badge-doc-csbh-bg text-badge-doc-csbh-fg',
      phap_ly: 'bg-badge-doc-phaply-bg text-badge-doc-phaply-fg',
      huong_dan: 'bg-badge-doc-huongdan-bg text-badge-doc-huongdan-fg',
      khac: MAU_MAC_DINH,
    }[loai] ?? MAU_MAC_DINH
  )
}

export function nhanCua(muc: readonly MucChon[], value: string | null | undefined): string {
  if (!value) return ''
  return muc.find((m) => m.value === value)?.nhan ?? value
}
