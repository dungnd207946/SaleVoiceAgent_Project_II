/**
 * Nav của M2a — Auth · Workspace · App shell. Sở hữu: users.
 * Spec tổng §2, §4⑤.
 *
 * Màn `users`: một bảng thành viên của workspace đang mở, đổi vai trò + mời qua
 * hộp thoại (PQ_01 §3.2). Tab «Vai trò» và đường tự-tạo-vai-trò rời giao diện
 * 2026-08-09 — xem docs/superpowers/sdd/2026-08-09-gon-thanh-vien-va-phan-quyen/.
 * `rolesNav` (nav item riêng cho `/roles`) đã BỎ trước đó — không còn export ở đây.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

/**
 * NHÃN LÀ «Thành viên» (2026-08-09, lần đổi thứ hai trong ngày).
 *
 * Sáng 09/08 nó đổi «Thành viên & Phân quyền» → «Người dùng», với lý do *gọi tên
 * màn theo BẢNG PHỤ — bảng chính là người dùng toàn tổ chức*. Lý do đó gắn liền
 * với TRỤC CŨ. Chiều 09/08 trục đổi sang workspace (spec «gọn thành viên và phân
 * quyền» §2.2), nên bảng chính GIỜ LÀ thành viên workspace và nhãn đi theo.
 *
 * Không phải đảo quyết định sáng — là hệ quả của việc đổi trục. Vế «& Phân
 * quyền» thì KHÔNG quay lại: luật «nhãn nav là tên một CHỖ, không phải mục lục»
 * vẫn đứng.
 *
 * ⚠ Nhãn dài nhất của panel Quản trị KHÔNG còn là mục này. Bề rộng panel 240px đo
 * theo «Thành viên & Phân quyền» (167px ở 13.5px); nhãn mới ngắn hơn hẳn nên
 * panel còn dư chỗ — ĐỪNG bóp panel theo nó, số đo 240px phục vụ cả ba mảng.
 */
export const usersNav: NavLeaf = {
  kind: 'leaf',
  key: 'users',
  path: '/users',
  label: { vi: 'Thành viên', en: 'Members' },
  icon: 'users',
  // Nhóm 13 — Thành viên nằm cùng Khoá API · Cài đặt workspace.
  // PQ_01 Q06: không đọc được bảng thành viên thì TỪ CHỐI, không trả rỗng.
  requiredActions: [ACTIONS.WORKSPACE_ADMIN],
}
