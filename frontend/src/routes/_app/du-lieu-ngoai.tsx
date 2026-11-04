import { createFileRoute } from '@tanstack/react-router'
import { DuLieuNgoaiScreen, type TabDuLieuNgoai } from '@/features/kb-web/components/DuLieuNgoaiScreen'

// Màn «Dữ liệu ngoài» (2026-10-05) — nguồn báo, chủ đề, lịch thu thập và hồ sơ dự án từ web
// công khai. Tab đang mở nằm ở `?tab=` để F5/link giữ đúng chỗ.
const TAB: readonly TabDuLieuNgoai[] = ['tong-quan', 'nguon', 'chu-de', 'lich', 'du-an']

export const Route = createFileRoute('/_app/du-lieu-ngoai')({
  validateSearch: (s: Record<string, unknown>): { tab?: TabDuLieuNgoai | undefined; duAn?: string | undefined } => ({
    tab: TAB.includes(s.tab as TabDuLieuNgoai) ? (s.tab as TabDuLieuNgoai) : undefined,
    // Mở thẳng hồ sơ một dự án (link từ màn dự án ở Kiến thức).
    duAn: typeof s.duAn === 'string' && s.duAn ? s.duAn : undefined,
  }),
  component: DuLieuNgoaiScreen,
})
