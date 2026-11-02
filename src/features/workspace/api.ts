/**
 * Client HTTP của seam workspace — tạo workspace mới.
 */
import { goi } from '@/lib/http'

/** `POST /api/v1/workspaces` trả về đúng hình dạng này. */
export interface WorkspaceMoi {
  readonly id: string
  readonly name: string
  readonly lifecycle: string
  readonly status: string
  readonly createdAt: string
}

export function taoWorkspace(name: string): Promise<WorkspaceMoi> {
  return goi<WorkspaceMoi>('/api/v1/workspaces', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

const DAI_ID_TOI_DA = 31
const DAI_ID_TOI_THIEU = 2

export function slugDuKien(ten: string): string {
  const khongDau = ten
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .normalize('NFD')
    .replace(/\p{Mn}/gu, '')

  let goc = khongDau
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')

  if (!goc) goc = 'workspace'
  if (!/^[a-z]/.test(goc)) goc = `w_${goc}`

  goc = goc.slice(0, DAI_ID_TOI_DA).replace(/_+$/, '') || 'workspace'
  if (goc.length < DAI_ID_TOI_THIEU) goc = `${goc}_ws`
  return goc
}

/** `PATCH /api/v1/workspaces/{id}` trả về đúng hai trường này. */
export interface WorkspaceDaSua {
  readonly id: string
  readonly name: string
}

/**
 * Đổi tên workspace. Chỉ đổi được workspace ĐANG MỞ — backend đối chiếu `id`
 * trong đường dẫn với workspace của phiên và trả 403 nếu lệch.
 *
 * MÃ WORKSPACE KHÔNG ĐỔI THEO TÊN, và `id` trong response là bằng chứng của
 * điều đó: nó là khoá cách ly dùng cho bốn việc (policy RLS · role
 * `agent_<id>` · `tenants/<id>/` trên kho tệp · collection `kb_<id>`). Màn cài
 * đặt phải nói ra điều này TRƯỚC khi người dùng bấm Lưu — thấy mã cũ trong log
 * sau khi đổi tên mà không được báo trước thì nó đọc như một lỗi.
 *
 * 409 `WORKSPACE_TRUNG_TEN` khi người TẠO ra workspace này đã có một workspace
 * khác cùng tên. Phạm vi là NGƯỜI TẠO, không phải người sửa và không toàn cục —
 * nên thông điệp của backend đã nói đúng chuyện đó và màn hình hiện nguyên văn.
 */
export function suaWorkspace(id: string, name: string): Promise<WorkspaceDaSua> {
  return goi<WorkspaceDaSua>(`/api/v1/workspaces/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })
}

/**
 * Xoá workspace. 204, không thân.
 *
 * XOÁ CỨNG, NGAY LẬP TỨC — không kỳ chờ, không thùng rác, không job dọn về sau.
 * Backend chạy `DELETE FROM control.tenants`, và mọi bảng mang `tenant_id` đều
 * `ON DELETE CASCADE` nên một câu lệnh cuốn theo 31 bảng; ba kho ngoài Postgres
 * (collection Qdrant · tệp · role Postgres của pod) được dọn ngay sau đó trong
 * cùng request. Không có đường lùi nào, kể cả cho ops.
 *
 * Vì thế giao diện KHÔNG được hứa hẹn gì về khôi phục, và hộp thoại phải bắt gõ
 * lại mã workspace — xem `XoaWorkspaceDialog`.
 *
 * 409 `WORKSPACE_CUOI_CUNG` khi đây là workspace duy nhất còn lại — một người
 * luôn phải thuộc ít nhất một workspace.
 */
export function xoaWorkspace(id: string): Promise<void> {
  return goi<void>(`/api/v1/workspaces/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
