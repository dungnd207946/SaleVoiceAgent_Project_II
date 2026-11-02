/**
 * Luật đủ dữ liệu cho agent, bản FE — song song
 * `modules/realestate/completeness.py`.
 *
 * VÌ SAO LẶP LUẬT Ở FE trong khi backend đã chặn: backend chặn bằng 422 SAU KHI
 * người dùng bấm Phát hành. FE biết trước nên nói được điều đó ở hai chỗ 422
 * không tới được — badge thiếu dữ liệu trên bảng danh sách (thấy được mà không
 * mở form nào), và nhãn cạnh nút Lưu trong lúc đang nhập. Không có nó thì cách
 * duy nhất biết một dự án chưa đủ là bấm phát hành rồi bị từ chối.
 *
 * BACKEND VẪN LÀ NGUỒN SỰ THẬT. Bản này chỉ được phép NGHIÊM BẰNG HOẶC LỎNG HƠN,
 * không bao giờ nghiêm hơn: FE chặn một thứ backend cho phép là một tính năng bị
 * khoá mà không ai giải thích được vì sao. Hai danh sách dưới đây chép nguyên văn
 * `BAT_BUOC` của Python — thêm field vào đây mà không thêm ở đó là đúng cái sai
 * vừa nói. Không có cổng CI nào so hai bên.
 *
 * `project` = năm trường của spec 2026-08-21 §3.5, KHÁC `02a §7`. `amenities` cố
 * ý ở NGOÀI (rỗng ở 94/94 dự án published trên Aurora dev) — nó nằm trong thước
 * đo mềm `doHoanThien` bên dưới thay vì trong cổng.
 */
/**
 * Nhận CẢ kiểu đọc (`DuAn`/`Can`) LẪN kiểu ghi (`DuAnGhi`/`CanGhi`).
 *
 * Hai kiểu khác nhau ở chỗ kiểu ghi có prop tuỳ chọn (`repo` bật
 * `exactOptionalPropertyTypes`, nên `Partial<DuAn>` KHÔNG nhận `DuAnGhi`), nhưng
 * hàm này chỉ đọc ba khoá và chỉ để so với `null`/`''`/`undefined` — nên nó không
 * cần biết gì hơn "có các khoá đó, giá trị là gì cũng được". Đúng chỗ dùng để
 * cùng một luật chạy trên bản ghi server trả về (badge ở bảng danh sách) và trên
 * state form đang gõ (nhãn cạnh nút Lưu).
 */
type CoTruong<T extends readonly string[]> = { readonly [K in T[number]]?: unknown }

/** Nhãn tiếng Việt của field bắt buộc — hiện trong câu Còn thiếu: …. */
const NHAN: Record<string, string> = {
  name: 'Tên thương mại',
  region: 'Khu vực',
  overview: 'Tổng quan',
  investor: 'Chủ đầu tư',
  productScale: 'Quy mô sản phẩm',
  // Bảy trường MỀM: không ở cổng chặn nhưng `doHoanThien` gọi tên chúng, và
  // `nhanThieu` rơi về tên cột nếu thiếu nhãn — «totalLandAreaM2» trên giao diện.
  amenities: 'Tiện ích',
  totalLandAreaM2: 'Tổng DT đất',
  floorAreaM2: 'Tổng DT sàn',
  buildDensityPct: 'Mật độ xây dựng',
  ownershipForm: 'Hình thức sở hữu',
  handoverStandard: 'Tiêu chuẩn bàn giao',
  totalInvestmentVnd: 'Tổng mức đầu tư',
  priceVnd: 'Giá bán',
  areaBuiltM2: 'Diện tích thông thuỷ',
  areaLandM2: 'Diện tích đất',
  // Nhãn của NHÓM một-trong, không phải của một cột — xem `DIEN_TICH_CAN`.
  dienTich: 'Diện tích',
  saleStatus: 'Trạng thái bán',
}

/**
 * Hai cột diện tích: có MỘT là đủ (đổi 2026-08-25, khớp `completeness.py`).
 *
 * Sản phẩm ĐẤT không bao giờ có diện tích thông thuỷ — đo trên DB dev `aina_prod`:
 * biệt thự/nhà phố/shophouse có 0/5.133 căn mang `areaBuiltM2` và 5.133/5.133 mang
 * `areaLandM2`. Luật cũ bắt `areaBuiltM2` cho mọi loại hình nên badge «⚠ Thiếu» bám
 * lên cả 5.133 căn, trong đó 4.189 căn đang published và hoàn toàn bình thường.
 */
const DIEN_TICH_CAN = ['areaBuiltM2', 'areaLandM2'] as const

export const BAT_BUOC = {
  project: ['name', 'region', 'overview', 'investor'] as const,
  /**
   * Mọi cột cổng phát hành CHẠM tới — KHÔNG phải «mọi cột đều bắt buộc».
   * `areaBuiltM2`/`areaLandM2` là một-trong; luật thật nằm ở `thieuTruongCan`.
   */
  unit: ['priceVnd', 'areaBuiltM2', 'areaLandM2', 'saleStatus'] as const,
}

function thieu(gia_tri: unknown): boolean {
  return gia_tri === null || gia_tri === undefined || gia_tri === ''
}

/** Tên field còn thiếu của một dự án. Rỗng = đủ dữ liệu để phát hành. */
export function thieuTruongDuAn(d: CoTruong<typeof BAT_BUOC.project>): string[] {
  return BAT_BUOC.project.filter((t) => thieu(d[t]))
}

/** Tên field còn thiếu của một căn. `dienTich` = thiếu CẢ HAI cột diện tích. */
export function thieuTruongCan(c: CoTruong<typeof BAT_BUOC.unit>): string[] {
  const ra: string[] = []
  if (thieu(c.priceVnd)) ra.push('priceVnd')
  if (DIEN_TICH_CAN.every((t) => thieu(c[t]))) ra.push('dienTich')
  if (thieu(c.saleStatus)) ra.push('saleStatus')
  return ra
}

/** `['name','region']` → `'Tên thương mại, Khu vực'`. */
export function nhanThieu(truong: readonly string[]): string {
  return truong.map((t) => NHAN[t] ?? t).join(', ')
}
