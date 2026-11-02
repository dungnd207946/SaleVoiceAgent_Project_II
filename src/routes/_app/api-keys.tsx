import { createFileRoute } from '@tanstack/react-router'
import { TichHopApiScreen } from '@/features/platform/components/TichHopApiScreen'

// Màn `api` của M8 — nhãn nav «API Keys» (2026-08-07, bỏ «Tích hợp &» vì phần đó
// chưa có gì). MVP: khoá đấu nối agent + panel Thử agent (chờ endpoint backend
// nên `screens.ts` giữ `mvp: 'partial'`).
export const Route = createFileRoute('/_app/api-keys')({
  component: TichHopApiScreen,
})
