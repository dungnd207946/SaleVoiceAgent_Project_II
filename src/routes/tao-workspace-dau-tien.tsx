import { createFileRoute } from '@tanstack/react-router'
import { TaoWorkspaceDauTien } from '@/features/workspace/components/TaoWorkspaceDauTien'

// NGOÀI `_app`: người chưa có workspace không có gì để điều hướng tới, nên màn
// này không được bọc bởi shell (rail + panel + topbar). Xem docstring component.
export const Route = createFileRoute('/tao-workspace-dau-tien')({
  component: TaoWorkspaceDauTien,
})
