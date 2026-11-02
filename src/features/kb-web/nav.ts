/**
 * Nav màn «Dữ liệu ngoài» (2026-10-05) — nguồn báo, chủ đề, lịch thu thập và hồ sơ dự án từ
 * web công khai, của riêng workspace. Nằm trong khối Bất động sản (dưới Kiến thức) vì hồ sơ viết
 * cho từng dự án bất động sản — tắt lĩnh vực là mục ẩn theo.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const duLieuNgoaiNav: NavLeaf = {
  kind: 'leaf',
  key: 'du-lieu-ngoai',
  path: '/du-lieu-ngoai',
  label: { vi: 'Dữ liệu ngoài', en: 'External data' },
  icon: 'duLieuNgoai',
  requiredActions: [ACTIONS.KB_WEB_READ],
}
