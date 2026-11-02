import { createFileRoute } from '@tanstack/react-router'
import { ThuAgentScreen } from '@/features/platform/components/ThuAgentScreen'

// Thử agent — Chat hoặc Voice. Tách khỏi màn API Keys 2026-08-08: thử là
// việc làm đi làm lại và có hội thoại kéo dài, không phải một panel nhét dưới
// chân bảng khoá. Vẫn bắt buộc qua một khoá API (HT01 BR03).
export const Route = createFileRoute('/_app/thu-agent')({
  component: ThuAgentScreen,
})
