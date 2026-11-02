/**
 * Danh tính KHÁCH GIẢ LẬP cho màn Thử agent — các trường gửi trong bắt tay
 * `{identity, call_id}`.
 *
 * VÌ SAO CẦN. Thử mà không có danh tính là thử một nửa: agent chào theo tên,
 * tra hồ sơ theo số điện thoại, đổi cách xưng hô theo giới tính. Không có mấy
 * trường này thì mọi câu trả lời đều là đường mặc định, còn đúng những nhánh dễ
 * sai nhất thì không bao giờ chạy tới.
 *
 * BA TRƯỜNG, KHÔNG PHẢI BẢY (người dùng chốt 2026-08-08) — thêm `role` lần
 * thứ tư (2026-10-01), lựa chọn đổ từ các role trong cấu hình chung. `buildIdentity()` của
 * `odyssey-tester/web/chat.html` gửi tới bảy trường (thêm `email`, `birthday`,
 * `is_noble_customer`, `noble_info`) — gateway vẫn nhận chúng, chỉ là màn này
 * không hỏi nữa. Cần lại thì thêm một dòng vào `O_DANH_TINH` và một khoá vào
 * `DanhTinhKhach`; phần còn lại của tệp và cả form đều chạy theo bảng, không
 * phải sửa.
 *
 * VÌ SAO KHÔNG LÀM Ô KEY/VALUE TỰ DO. Một ô "thêm trường bất kỳ" cho phép gõ
 * `fone` rồi gửi đi im lặng — gateway bỏ qua, người dùng ngồi đoán vì sao agent
 * không nhận ra khách. Danh sách đóng thì gõ sai là không gõ được.
 *
 * KHÔNG GỬI TRƯỜNG RỖNG. `{full_name: ''}` khác hẳn `{}`: cái đầu nói "khách
 * này tên là chuỗi rỗng", cái sau nói "không biết tên". Gateway có thể ghi đè
 * hồ sơ thật bằng chuỗi rỗng — xem `locTrong()`.
 */

/** Đúng tên khoá gateway đọc. `snake_case` vì đó là hợp đồng, không phải style FE. */
export interface DanhTinhKhach {
  readonly full_name?: string
  readonly phone?: string
  readonly gender?: string
  /** `key` của role người dùng agent (`VaiTroMeta.key`, `/config`) — cho agent
   *  biết khách đang thử thuộc role nào. Danh sách là DỮ LIỆU workspace, nên ô này không có
   *  `chon` tĩnh: màn tự đổ lựa chọn từ `/config` (xem `kieu: 'vaiTro'`). */
  readonly role?: string
}

/** Giá trị trong form — tất cả là chuỗi, kể cả ô chọn. */
export type FormDanhTinh = Readonly<Record<string, string>>

export type KieuO = 'text' | 'dienThoai' | 'chon' | 'vaiTro'

export interface LuaChon {
  readonly gt: string
  readonly nhan: { readonly vi: string; readonly en: string }
}

export interface ODanhTinh {
  readonly ma: keyof DanhTinhKhach
  readonly nhan: { readonly vi: string; readonly en: string }
  readonly kieu: KieuO
  readonly goiY?: string
  /** Chỉ cho `kieu: 'chon'`. */
  readonly chon?: readonly LuaChon[]
}

/**
 * ⚠ GIÁ TRỊ GIỚI TÍNH LÀ MỘT PHỎNG ĐOÁN, không phải hợp đồng đã chốt.
 * `odyssey-tester` để ô này là TEXT TỰ DO với gợi ý `nam`, nên không có enum
 * nào được khai ở đâu cả. Ta gửi đúng hai chuỗi `nam`/`nữ` theo gợi ý đó. Ngày
 * backend/gateway khai enum thật mà lệch thì sửa Ở ĐÂY, một chỗ.
 */
const GIOI_TINH: readonly LuaChon[] = [
  { gt: 'nam', nhan: { vi: 'Nam', en: 'Male' } },
  { gt: 'nữ', nhan: { vi: 'Nữ', en: 'Female' } },
]

/**
 * Thứ tự = thứ tự người ta nghĩ về một khách: tên → liên lạc → xưng hô.
 *
 * `goiY` mở đầu bằng «VD: » — cùng lối `O.goiYTrongO` của form agent. Không có
 * hai chữ đó thì một cái tên đủ thật và một số máy đủ thật nằm sẵn trong hai ô
 * BẮT BUỘC đọc thành dữ liệu đã điền: người dùng bấm Áp dụng, thấy nút không ăn,
 * rồi phải tự đoán ô nào còn thiếu. Sắc độ có phân biệt được (đo: gợi ý 5.19 vs
 * giá trị 17.78 trên `surface`) nhưng nó chỉ nói «chữ này nhạt hơn», không nói
 * «chữ này không phải của bạn».
 */
export const O_DANH_TINH: readonly ODanhTinh[] = [
  {
    ma: 'full_name',
    nhan: { vi: 'Họ tên', en: 'Full name' },
    kieu: 'text',
    goiY: 'VD: Nguyễn Văn Duy',
  },
  {
    ma: 'phone',
    nhan: { vi: 'Số điện thoại', en: 'Phone' },
    kieu: 'dienThoai',
    goiY: 'VD: 0912010999',
  },
  { ma: 'gender', nhan: { vi: 'Giới tính', en: 'Gender' }, kieu: 'chon', chon: GIOI_TINH },
  { ma: 'role', nhan: { vi: 'Role', en: 'Role' }, kieu: 'vaiTro' },
]

/**
 * Chỉ giữ chữ số.
 *
 * DÙNG HÀM NÀY thay vì `<input type="number">`. Ô `number` hỏng đúng ở ca của
 * ta: số điện thoại Việt Nam bắt đầu bằng `0`, mà `type="number"` coi giá trị
 * là SỐ nên `0912010999` có thể mất số 0 đầu — thành một số máy không gọi được.
 * Nó lại còn cho gõ `e`, `+`, `-`, `.` (đều hợp lệ với một số), và mọc hai nút
 * tăng/giảm vô nghĩa. `type="tel"` + lọc tay cho đúng thứ ta muốn: bàn phím số
 * trên di động, và tuyệt đối chỉ chữ số.
 */
export function chiSo(v: string): string {
  return v.replace(/\D/g, '')
}

/**
 * Form → payload gateway. Bỏ mọi ô trống.
 *
 * Lọc lúc GỬI, không lúc gõ: người dùng còn đang sửa dở một ô thì bản lọc giữa
 * chừng không có ý nghĩa gì.
 */
export function locTrong(form: FormDanhTinh): DanhTinhKhach {
  const ra: Record<string, string> = {}
  for (const o of O_DANH_TINH) {
    const v = (form[o.ma] ?? '').trim()
    if (v !== '') ra[o.ma] = v
  }
  return ra as DanhTinhKhach
}

/** Có khai được gì không — để màn nói «chưa khai» thay vì im lặng. */
export function soTruongDaKhai(form: FormDanhTinh): number {
  return Object.keys(locTrong(form)).length
}

// ─── Giá trị điền sẵn khi vào màn ────────────────────────────────────────────

/** Tên điền sẵn — chọn ngẫu nhiên một trong ba (người dùng chốt 2026-10-02). */
export const TEN_MAC_DINH = ['Dũng', 'Dự', 'Thế'] as const

/** Đầu số di động Việt Nam đang dùng — số ngẫu nhiên phải TRÔNG như số thật,
 *  agent tra hồ sơ/đọc lại số theo đúng khuôn 10 chữ số bắt đầu bằng 0. */
const DAU_SO = [
  '090',
  '091',
  '093',
  '094',
  '096',
  '097',
  '098',
  '086',
  '088',
  '032',
  '035',
  '039',
  '070',
  '077',
  '081',
  '083',
  '085',
]

/**
 * Ba trường biết được NGAY lúc vào màn: tên ngẫu nhiên · số máy ngẫu nhiên ·
 * giới tính nam. Role và API Key KHÔNG ở đây — chúng là lựa chọn ĐẦU TIÊN của
 * hai danh sách tải từ server, nên màn điền sau khi dữ liệu về.
 *
 * `rand` tiêm được để test tất định.
 */
export function danhTinhMacDinh(rand: () => number = Math.random): FormDanhTinh {
  const chon = <T>(ds: readonly T[]): T => ds[Math.floor(rand() * ds.length)] as T
  let duoi = ''
  for (let i = 0; i < 7; i++) duoi += String(Math.floor(rand() * 10))
  return { full_name: chon(TEN_MAC_DINH), phone: chon(DAU_SO) + duoi, gender: 'nam' }
}
