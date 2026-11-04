import { createFileRoute } from '@tanstack/react-router'
import { TongQuanScreen } from '@/features/ops/components/TongQuanScreen'

// Màn `dashboard` — Tổng quan (M7 Task 11).
export const Route = createFileRoute('/_app/dashboard')({
  component: TongQuanScreen,
})
