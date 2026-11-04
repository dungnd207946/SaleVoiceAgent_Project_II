/**
 * Nav của seam workspace — MỘT mục: «Cài đặt workspace» ở mảng Quản trị.
 *
 * VÌ SAO KHÔNG DÙNG `/settings` ĐANG CÓ SẴN: màn đó là HỒ SƠ CÁ NHÂN (vào từ
 * avatar ở chân sidebar, nhãn «Hồ sơ & tuỳ chọn» — xem `OFF_NAV`). Nó trả lời
 * «tôi là ai, tôi thích gì»; màn này trả lời «workspace này là gì, và tôi muốn
 * nó biến mất». Gộp hai câu đó vào một màn là đặt cái nút nguy hiểm nhất của
 * portal vào đúng chỗ người dùng ít cảnh giác nhất — họ vào đó để đổi ngôn ngữ.
 *
 * VÌ SAO Ở MẢNG QUẢN TRỊ chứ không mảng Agent: câu hỏi mà mảng Quản trị trả lời
 * là «ai được vào, ai đã làm gì, tốn bao nhiêu» (xem đầu `lib/nav-registry.ts`)
 * — vòng đời của chính workspace thuộc cùng nhóm câu hỏi đó.
 *
 * ICON `settings` — BÁNH RĂNG THẬT, và nó vừa được sửa cho đúng như thế: bản
 * trong `PATHS` là một hình MẶT TRỜI (vòng tròn + tám tia rời), nay trỏ về
 * `Settings` của Lucide. Xem docstring của nó ở `components/icons.tsx`.
 *
 * `UserMenu` («Hồ sơ & tuỳ chọn») dùng CHUNG mark này. Phá lệ «một mark một
 * nghĩa» có chủ ý: hai chỗ nói cùng nghĩa «cài đặt», chỉ khác phạm vi, và phạm
 * vi thì nhãn ngay cạnh đã nói. `settings2` đã thuộc «Quản lý lĩnh vực», và
 * `secAdmin` là mark của chính mảng chứa mục này — dùng lại nó thì rail và
 * panel đọc thành một.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const caiDatWorkspaceNav: NavLeaf = {
  kind: 'leaf',
  key: 'workspace',
  path: '/workspace',
  label: { vi: 'Cài đặt workspace', en: 'Workspace settings' },
  icon: 'settings',
  // ⚠ Ẩn mục nav KHÔNG phải bảo vệ (PQ_01 §BR-Q03) — cửa thật là
  // `require(WORKSPACE_ADMIN)` ở cả `PATCH` lẫn `DELETE /workspaces/{id}`.
  requiredActions: [ACTIONS.WORKSPACE_ADMIN],
}
