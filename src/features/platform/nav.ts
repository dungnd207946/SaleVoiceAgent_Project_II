/**
 * Nav của M8 — Nền tảng. Sở hữu: api · audit · settings.
 * Spec tổng §2, §4⑤. `settings` không có trong sidebar (vào từ avatar).
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

/**
 * «Thử agent» — tách khỏi màn API Keys thành màn riêng 2026-08-08.
 *
 * Ở `features/platform` chứ không `features/agent` dù nav xếp nó vào mảng
 * Agent: màn này sống bằng DANH SÁCH KHOÁ (`taiKhoa`), và khoá là của M8. Nó
 * đọc trạng thái agent qua `features/agent/contracts` — mặt tiền công khai,
 * đúng Luật 3. Chỗ đứng trong nav và chủ sở hữu module là hai chuyện rời nhau.
 */
export const thuAgentNav: NavLeaf = {
  kind: 'leaf',
  key: 'thu-agent',
  path: '/thu-agent',
  label: { vi: 'Thử agent', en: 'Try the agent' },
  icon: 'convos',
  // Cùng quyền với đọc cấu hình: thử là một cách ĐỌC xem agent đang làm gì.
  requiredActions: [ACTIONS.AGENT_CONFIG_READ],
}

export const apiNav: NavLeaf = {
  kind: 'leaf',
  key: 'api',
  path: '/api-keys',
  label: { vi: 'API Keys', en: 'API keys' },
  icon: 'api',
  requiredActions: [ACTIONS.WORKSPACE_ADMIN],
}

export const auditNav: NavLeaf = {
  kind: 'leaf',
  key: 'audit',
  path: '/audit',
  // «Nhật ký», bỏ vế «& Dữ liệu» (2026-08-09): vế đó hứa một phần màn chưa có.
  // Màn thật dựng 2026-08-25 (`components/NhatKyScreen.tsx`); ngày có phần dữ
  // liệu thì nó là một tab, y như `/users` đã làm với Vai trò.
  label: { vi: 'Nhật ký', en: 'Audit log' },
  icon: 'audit',
  // `audit.read` (action 15, BE `0956_audit_action`, cấp mặc định cho Quản trị).
  // Trước 2026-08-25 là `OVERVIEW_READ` vì PQ_01 §3.1 nói «mọi vai trò xem việc
  // của chính mình» — phần đó là ĐỢT 2 (spec BE §2 #6); đợt 1 endpoint chỉ trả
  // toàn workspace cho ai có action này, nên nav khoá theo đúng action đó.
  requiredActions: [ACTIONS.AUDIT_READ],
}
