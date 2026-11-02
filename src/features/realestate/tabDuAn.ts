/**
 * Mười tab của một dự án — danh sách + phép làm sạch giá trị từ URL.
 *
 * FILE RIÊNG, KHÔNG NẰM CẠNH COMPONENT: `routes/_app/pform.tsx` cần `tabHopLe()`
 * lúc `validateSearch`, tức TRƯỚC khi render bất cứ gì. Để nó trong
 * `components/KhungDuAn.tsx` thì file route phải import một module có JSX chỉ để
 * lấy một hàm thuần, và eslint `react-refresh/only-export-components` cảnh báo
 * đúng: một module vừa export component vừa export hằng số thì Vite không nhận
 * ra nó là module component và nạp lại cả trang mỗi lần sửa.
 *
 * MỘT NGUỒN cho cả `/pform` lẫn `/uform`: hai màn phải hiện CÙNG một hàng tab.
 * Khai hai lần là hai danh sách, và cái thứ hai sẽ thiếu tab mà lần sau ai đó thêm.
 */

export type TenTabDuAn =
  | 'tong-quan'
  | 'vi-tri'
  | 'anh-360'
  | 'mat-bang'
  | 'phan-khu'
  | 'toa'
  | 'quy-can'
  | 'tien-do'
  | 'media'
  | 'tai-lieu'

export const TAB_DU_AN: readonly { id: TenTabDuAn; nhan: string }[] = [
  { id: 'tong-quan', nhan: 'Tổng quan' },
  { id: 'vi-tri', nhan: 'Vị trí' },
  { id: 'anh-360', nhan: 'Ảnh 360' },
  { id: 'mat-bang', nhan: 'Mặt bằng' },
  { id: 'phan-khu', nhan: 'Phân khu' },
  { id: 'toa', nhan: 'Toà' },
  { id: 'quy-can', nhan: 'Quỹ căn' },
  { id: 'tien-do', nhan: 'Tiến độ' },
  { id: 'media', nhan: 'Media' },
  { id: 'tai-lieu', nhan: 'Tài liệu' },
]

/** Id cũ → id mới. Link đã gửi cho đồng nghiệp và bookmark vẫn phải mở đúng tab. */
const TAB_CU: Record<string, TenTabDuAn> = {
  'thong-tin': 'tong-quan',
  can: 'quy-can',
  csbh: 'tai-lieu',
}

export function tabHopLe(tho: unknown): TenTabDuAn {
  if (TAB_DU_AN.some((t) => t.id === tho)) return tho as TenTabDuAn
  return (typeof tho === 'string' && TAB_CU[tho]) || 'tong-quan'
}

/** id vùng nội dung của hàng tab dự án (`/pform` + `/uform`) — xem `panelTab`. */
export const ID_TAB_DU_AN = 'tab-du-an'
