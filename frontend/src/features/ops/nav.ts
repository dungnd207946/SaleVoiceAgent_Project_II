/**
 * Nav của M7 — Vận hành. Sở hữu: dashboard · convos · appts · gaps.
 * Spec tổng §2, §4⑤. M7 sửa file này, KHÔNG sửa shell.
 *
 * `gapsNav` («Cần bổ sung», `/gaps`) ĐÃ BỎ khỏi nav 2026-08-08 theo yêu cầu, và
 * `apptsNav` («Lịch hẹn», `/appts`) ĐÃ BỎ 2026-08-13 theo yêu cầu. Route giữ
 * chỗ của hai màn (chưa ai xây) đã gỡ 2026-10-06. Ngày M7 nhận màn: thêm route,
 * khai lại một `NavLeaf` ở đây, thêm vào đúng khối trong `lib/nav-registry.ts`.
 * Icon `gaps`/`appts` vẫn còn trong `components/icons.tsx` để khỏi phải vẽ lại.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const dashboardNav: NavLeaf = {
  kind: 'leaf',
  key: 'dashboard',
  path: '/dashboard',
  label: { vi: 'Tổng quan', en: 'Overview' },
  icon: 'dashboard',
  requiredActions: [ACTIONS.OVERVIEW_READ],
}

export const convosNav: NavLeaf = {
  kind: 'leaf',
  key: 'convos',
  path: '/convos',
  label: { vi: 'Hội thoại', en: 'Conversations' },
  icon: 'convos',
  requiredActions: [ACTIONS.CONVOS_READ],
}

export const chuyenSaleNav: NavLeaf = {
  kind: 'leaf',
  key: 'chuyen-sale',
  path: '/chuyen-sale',
  label: { vi: 'Chuyển sale', en: 'Sale handoffs' },
  icon: 'chuyenSale',
  requiredActions: [ACTIONS.CONVOS_READ],
}
