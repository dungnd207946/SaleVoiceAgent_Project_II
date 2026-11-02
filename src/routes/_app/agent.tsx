import { createFileRoute } from '@tanstack/react-router'
import { AgentStudio } from '@/features/agent/components/AgentStudio'

// «Cấu hình chung» — phần agent áp cho MỌI lĩnh vực. Kỹ năng riêng từng lĩnh
// vực ở `/ky-nang-bds` (spec 2026-08-07, khu «Lĩnh vực» có tab đã bỏ). Chat thử
// ĐÃ SANG màn API Keys — đi qua đúng kênh khách dùng (HT01 BR03).
export const Route = createFileRoute('/_app/agent')({
  component: AgentStudio,
})
