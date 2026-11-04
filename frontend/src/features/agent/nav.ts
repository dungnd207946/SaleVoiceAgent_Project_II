/**
 * Nav của M5 — Agent Studio. Sở hữu: agent · ky-nang-bds. Spec tổng §2, §4⑤.
 *
 * HAI MỤC, vì cấu hình agent có hai loại phạm vi khác nhau (spec 2026-08-07
 * «lĩnh vực thành khối»):
 *   · `agent`      — CHUNG cho mọi lĩnh vực: danh tính, rào chắn, kỹ năng chung
 *   · `ky-nang-bds` — RIÊNG lĩnh vực Bất động sản: 9 kỹ năng của vertical #1
 *
 * Cả hai sửa cùng MỘT `ConfigPayload` và cùng một bản nháp phía server; tách là
 * tách ở tầng màn, không tách ở tầng hợp đồng. Xem `useBanNhap.ts`.
 *
 * Nhãn «Agent» thành «Cấu hình chung»: khi mục này đứng cạnh «Kỹ năng» của một
 * lĩnh vực, chữ «Agent» không còn nói được nó khác cái kia ở chỗ nào.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const agentNav: NavLeaf = {
  kind: 'leaf',
  key: 'agent',
  path: '/agent',
  label: { vi: 'Cấu hình chung', en: 'Shared config' },
  // Thẻ danh tính, KHÔNG phải bánh răng: màn này khai agent LÀ AI (tên, xưng
  // hô, giọng, rào chắn). Một vòng trước nó dùng chung `settings2` với «Quản lý
  // lĩnh vực» và hai mục trùng icon nằm cùng panel — xem chú thích ở
  // `components/icons.tsx`.
  icon: 'danhTinh',
  // Đọc cấu hình là nhóm 10; sửa (nhóm 11) và xuất bản (nhóm 12) kiểm trong màn.
  requiredActions: [ACTIONS.AGENT_CONFIG_READ],
}

export const kyNangBdsNav: NavLeaf = {
  kind: 'leaf',
  key: 'ky-nang-bds',
  path: '/ky-nang-bds',
  // Nhãn trần «Kỹ năng» — nó đã nằm dưới nhãn khối «Bất động sản», nhắc lại
  // tên lĩnh vực trong chính mục là thừa.
  label: { vi: 'Kỹ năng', en: 'Skills' },
  icon: 'agent',
  requiredActions: [ACTIONS.AGENT_CONFIG_READ],
}
