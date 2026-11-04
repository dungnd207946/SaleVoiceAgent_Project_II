import { createFileRoute } from '@tanstack/react-router'
import { UserAdmin } from '@/features/auth/components/UserAdmin'

// Màn này KHÔNG còn tab (2026-08-09), nên không còn `validateSearch`. `?tab=
// vai-tro` của link cũ rơi vào search param không khai báo — TanStack bỏ qua,
// màn vẫn mở đúng. Đó là hành vi mong muốn: link cũ không được vỡ.
export const Route = createFileRoute('/_app/users')({
  component: UserAdmin,
})
