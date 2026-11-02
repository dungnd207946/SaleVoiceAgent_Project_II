import { createFileRoute } from '@tanstack/react-router'
import { BangGiaScreen } from '@/features/billing/contracts'

// Màn `pricing` — dải token quản trị nền tảng + ba ô + bảng bộ giá (Task 8).
export const Route = createFileRoute('/_app/pricing')({
  component: BangGiaScreen,
})
