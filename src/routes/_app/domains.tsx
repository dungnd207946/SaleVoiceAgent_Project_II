import { createFileRoute } from '@tanstack/react-router'
import { QuanLyLinhVuc } from '@/features/agent/components/QuanLyLinhVuc'

// Màn `domains` — bật/tắt lĩnh vực của agent (2026-08-08).
//
// Sở hữu chuyển từ M4 sang M5: sổ lĩnh vực quyết định agent làm được gì, không
// phải quyết định dữ liệu BĐS trông thế nào. Hai endpoint `/api/v1/linh-vuc`
// do FE định hợp đồng trước, MSW fake — backend chưa có (features/agent/linhVuc.ts).
export const Route = createFileRoute('/_app/domains')({
  component: QuanLyLinhVuc,
})
