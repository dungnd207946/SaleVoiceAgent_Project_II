/**
 * Nav của M6 — kho tệp KB. Sở hữu: kb. Spec tổng §2, §4⑤.
 *
 * NHÃN ĐỔI THÀNH «TÀI LIỆU CHUNG» (2026-08-28, chủ dự án chốt) — trước đó là
 * «Tài liệu tra cứu» (2026-08-08), đặt tên theo VIỆC AGENT LÀM (tra vs gửi) để
 * phân biệt với kho kia (`/projects` → tab «Tài liệu gửi khách», M4: người
 * dùng GÕ TAY `title`+`body`, agent đọc bằng `get_document` để GỬI NGUYÊN VĂN).
 * Lý lẽ phân biệt đó VẪN ĐÚNG — hai kho vẫn khác nhau y hệt — chỉ là tên hiển
 * thị đổi, không đổi việc agent làm: ĐÂY (`/kb`, M6) người dùng TẢI TỆP lên
 * (.pdf/.docx/.xlsx/.md), hệ thống bóc chữ → chia đoạn → nhúng vector, agent đọc
 * bằng `kb_search` («Tra tài liệu của workspace») để TRA khi soạn câu trả lời.
 *
 * ⚠️ Đây là đổi tên MỘT MÌNH, không đổi cặp: nhãn tab bên `features/realestate`
 * (`DuAnList.tsx`/`tabDuAn.ts`) GIỮ NGUYÊN «Tài liệu gửi khách» — chủ dự án chỉ
 * yêu cầu đổi tab này.
 *
 * Khoá hợp đồng `taiLieuTraCuu` (trong `overview.kienThuc` do backend trả) GIỮ
 * NGUYÊN dù nhãn hiển thị đã đổi — xem `features/ops/components/TheKienThuc.tsx`.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const kbNav: NavLeaf = {
  kind: 'leaf',
  key: 'kb',
  path: '/kb',
  label: { vi: 'Tài liệu chung', en: 'General docs' },
  icon: 'kb',
  requiredActions: [ACTIONS.CATALOG_READ],
}
