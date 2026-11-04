/**
 * Nav của M4 — Dữ liệu BĐS. Sở hữu: projects · pform · uform · domains.
 * Spec tổng §2, §4⑤.
 *
 * `domainsMenuNav` — mục cha mở/gập «Lĩnh vực» — ĐÃ BỎ (2026-08-07). Nó bọc
 * đúng ba mục, và ba mục đó giờ LÀ trọn vẹn mảng «Dữ liệu» trên rail: một cấp
 * mở/gập bọc toàn bộ mảng chứa nó chỉ thêm một cú bấm, không thêm thông tin.
 * Nó cũng trùng tên với chính màn con `domains` («Quản lý lĩnh vực»), nên
 * sidebar cũ có hai dòng đọc gần như y hệt nhau nằm lồng vào nhau.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const projectsNav: NavLeaf = {
  kind: 'leaf',
  key: 'projects',
  path: '/projects',
  label: { vi: 'Kiến thức', en: 'Knowledge' },
  icon: 'projects',
  requiredActions: [ACTIONS.CATALOG_READ],
}

export const domainsNav: NavLeaf = {
  kind: 'leaf',
  key: 'domains',
  path: '/domains',
  label: { vi: 'Quản lý lĩnh vực', en: 'Manage domains' },
  icon: 'settings2',
  requiredActions: [ACTIONS.CATALOG_WRITE],
}
