import { createFileRoute } from '@tanstack/react-router'
import { KyNangBds } from '@/features/agent/components/KyNangBds'

// Kỹ năng riêng của lĩnh vực Bất động sản. Tách khỏi `/agent` 2026-08-07: cấu
// hình agent có hai phạm vi khác nhau (chung mọi lĩnh vực ↔ riêng một lĩnh
// vực), và tab trong màn giấu mất đúng ranh giới đó. Cùng bản nháp với
// `/agent`, cùng một nút Lưu và áp dụng — xem features/agent/useBanNhap.ts.
export const Route = createFileRoute('/_app/ky-nang-bds')({
  component: KyNangBds,
})
