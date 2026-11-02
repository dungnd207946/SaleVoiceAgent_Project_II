// src/features/agent/contracts.ts
/**
 * MẶT TIỀN công khai của module agent — module khác CHỈ được import file này
 * (`tests/module-boundaries.test.ts`, Luật 3). Có mặt vì panel Thử agent ở màn
 * API Keys (module platform) cần biết agent đã Sẵn sàng chưa (HT01 §2.5).
 */
export { docTrangThai } from './api'
export type { TrangThaiAgent, TrangThaiOut } from './api'

/**
 * Danh sách role người dùng agent (cấu hình chung, backend `0967`) — công khai vì
 * màn Thử agent (module platform) cho chọn role của khách giả lập trong bắt tay
 * `identity.role`. Cùng `queryKey` với `useBanNhap` để hai màn dùng chung cache.
 */
export { docCauHinh, KEY_ROLE_MAC_DINH } from './api'
export type { CauHinhOut, VaiTroMeta } from './api'
export const CAU_HINH_QUERY = ['config', 'hien-tai'] as const

/**
 * Sổ lĩnh vực — công khai vì SHELL cần nó: khối lĩnh vực trong panel Agent
 * sống chết theo công tắc này (`components/shell/useNavGroups.ts`).
 */
export { docLinhVuc } from './linhVuc'
export type { LinhVuc } from './linhVuc'

/**
 * Hai nhóm kỹ năng của màn Agent — công khai vì trang giới thiệu `/`
 * (`components/landing`) in lại đúng hai nhóm đó. Trước 2026-10-05 trang đó giữ
 * hai danh sách chép tay, lệch sổ sau đợt gộp tool 09/2026 («12 việc», tên đã nghỉ).
 */
export { KY_NANG_TAB_BDS, KY_NANG_TAB_CHUNG } from './kyNang'
