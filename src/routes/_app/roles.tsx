import { createFileRoute, redirect } from '@tanstack/react-router'

// Gộp vào `/users` 2026-08-06, rồi tab «Vai trò» đó tự rời giao diện 2026-08-09
// (xem docs/superpowers/sdd/2026-08-09-gon-thanh-vien-va-phan-quyen/) — không
// còn tab nào để trỏ tới. GIỮ file này (không xoá): `tests/nav-registry.test.ts`
// đối chiếu 1:1 route file ↔ `lib/screens.ts`, và `roles` vẫn là một `Screen`
// hợp lệ ở đó (chỉ `inNav: false`). Redirect, không xoá route, để link/bookmark
// cũ không gặp 404 — cùng khuôn `routes/_app/index.tsx` (`/` → `/dashboard`).
export const Route = createFileRoute('/_app/roles')({
  beforeLoad: () => {
    throw redirect({ to: '/users' })
  },
})
