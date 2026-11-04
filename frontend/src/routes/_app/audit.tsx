import { createFileRoute } from '@tanstack/react-router'
import { NhatKyScreen } from '@/features/platform/components/NhatKyScreen'

// Màn `audit` của M8 — «Nhật ký» (2026-08-25, thay ScreenStub). Đọc GET /api/v1/audit,
// quyền `audit.read`. Không search param: bộ lọc là state cục bộ của màn.
export const Route = createFileRoute('/_app/audit')({
  component: NhatKyScreen,
})
