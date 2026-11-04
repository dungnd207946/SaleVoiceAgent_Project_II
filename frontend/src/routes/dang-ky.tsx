import { createFileRoute } from '@tanstack/react-router'
import { DangKyForm } from '@/features/auth/components/DangKyForm'

// NGOÀI `_app` — cùng lý do với `/login`: `_app` bọc <SessionProvider>, mà màn
// này phải render được khi chưa có phiên.
export const Route = createFileRoute('/dang-ky')({
  component: DangKyForm,
})
