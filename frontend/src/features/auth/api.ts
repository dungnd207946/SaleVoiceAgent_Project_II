/**
 * Client HTTP của seam auth (cấp tổ chức) — `goi`/`LoiApi` ở `lib/http.ts`.
 */
import type { Session } from '@/lib/session'
import { goi } from '@/lib/http'

/**
 * Tự đăng ký. KHÔNG còn trả `Session` và KHÔNG còn đặt cookie (đổi 2026-08-17):
 * mật khẩu đặt ở `/invite/<token>` sau khi bấm link trong thư, không còn ở màn
 * đăng ký — server chỉ nhận `email`+`name`, không còn `password`.
 *
 * **201** = tài khoản mới, thư vừa gửi (`daGuiLai: false`). **200** = tài khoản
 * đang chờ hoàn tất (`pending`), thư vừa gửi LẠI (`daGuiLai: true`). **409**
 * `EMAIL_TAKEN` khi email đã có tài khoản có mật khẩu -> ném `LoiApi`. KHÔNG có
 * cookie phiên nào được đặt ở route này, trong mọi trường hợp.
 */
export function dangKy(email: string, ten: string): Promise<{ daGuiLai: boolean }> {
  return goi<{ daGuiLai: boolean }>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, name: ten }),
  })
}

/**
 * CÔNG KHAI — màn đăng nhập chưa có phiên nào để gửi.
 *
 * FE không có đường nào khác biết cửa Google bật hay tắt: cờ thật nằm ở `.env`
 * của backend. KHÔNG thay bằng một biến build-time của Vite — một bản build sẵn
 * đem sang môi trường khác sẽ nói sai.
 */
export function layNhaCungCap(): Promise<{ google: boolean }> {
  return goi<{ google: boolean }>('/api/v1/auth/providers')
}

export function dangNhap(email: string, matKhau: string): Promise<Session> {
  return goi<Session>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password: matKhau }),
  })
}

export function dangXuat(): Promise<void> {
  return goi<void>('/api/v1/auth/logout', { method: 'POST' })
}

export function doiWorkspace(workspaceId: string): Promise<Session> {
  return goi<Session>('/api/v1/me/workspace', {
    method: 'POST',
    body: JSON.stringify({ workspaceId }),
  })
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  M2b — quản trị user cấp tổ chức
 *  spec backend: docs/superpowers/specs/2026-08-03-m2b-tao-sua-user-design.md
 * ═══════════════════════════════════════════════════════════════════════════ */

export type Lifecycle = 'pending' | 'active' | 'suspended'

export interface LoiMoi {
  readonly email: string
  /** `null` cho `invite_new` — chưa có hàng `users` nào. Màn đó bỏ lời chào theo tên. */
  readonly name: string | null
  /**
   * HAI → BA GIÁ TRỊ 2026-08-22. `invite` cũ tách đôi vì hai luồng khác nhau ở thứ
   * màn hình phải hỏi: `invite_new` cần một mật khẩu, `invite_existing` chỉ cần một
   * cú bấm — và gửi `password` ở ca sau là 422, không phải một trường thừa vô hại.
   */
  readonly kind: 'signup' | 'invite_new' | 'invite_existing'
  /**
   * `null` CHỈ khi `kind === 'signup'`.
   *
   * ĐẢO LẠI quyết định 2026-08-15 («không hiện tên workspace»). Lý lẽ cũ viết khi
   * màn này chỉ nói «đặt mật khẩu đi»; nay nó hỏi «có tham gia hay không», và một
   * câu hỏi không nói tham gia CÁI GÌ là câu hỏi không trả lời được.
   */
  readonly workspaceName: string | null
}

/** CÔNG KHAI — người nhận mời chưa có mật khẩu nên chưa thể có phiên. */
export function xemLoiMoi(token: string): Promise<LoiMoi> {
  return goi<LoiMoi>(`/api/v1/invites/${encodeURIComponent(token)}`)
}

/**
 * ⚠ ENDPOINT VẪN SỐNG Ở BACKEND, CHỈ FE THÔI GỌI (2026-08-09).
 *
 * `POST/PATCH/DELETE /roles` và `GET /actions` không bị xoá — màn tự-tạo-vai-trò
 * rời giao diện, không phải năng lực bị rút. Ngày có khách enterprise đòi vai trò
 * riêng thì dựng lại UI, hợp đồng còn nguyên. Xem spec 2026-08-09 §2.1.
 *
 * `GET /roles` thì VẪN GỌI: hộp thoại mời và hộp thoại đổi vai trò dựng danh sách
 * 4 vai trò dựng sẵn từ nó.
 */

/**
 * Dòng trong bảng danh sách — MỘT vai trò cấp TỔ CHỨC (13 checkbox hành động),
 * khác hẳn bốn mã cố định admin/care/editor/viewer (vai trò TRONG một workspace
 * — kiểu `VaiTro`, ĐÃ XOÁ 2026-08-06). Đặt tên `VaiTroToChuc` để tránh trùng —
 * hai khái niệm khác nhau dùng chung tên sẽ có ngày bị import lộn.
 *
 * KHÔNG mang `actions`: n vai trò × 13 dòng là thừa cho một bảng chỉ hiện tên ·
 * mô tả · số người đang gán.
 */
export interface VaiTroToChuc {
  readonly id: string
  readonly name: string
  readonly description: string | null
  /** Số người đang gán vai trò này. `> 0` ⇒ xoá ăn 409 ROLE_IN_USE. */
  readonly userCount: number
}

export function layDanhSachVaiTro(): Promise<VaiTroToChuc[]> {
  return goi<VaiTroToChuc[]>('/api/v1/roles')
}

/** Khoá React Query của seam vai trò — MỘT chỗ, cùng khuôn `['users']`/`['users', id]` ở trên. */
export const khoaVaiTro = {
  tatCa: ['roles'] as const,
}

/**
 * CÔNG KHAI. 204, KHÔNG trả phiên — người gọi phải tự đẩy về `/login`.
 *
 * Backend cố ý không tạo phiên ở đây: tiện hơn một lần bấm, nhưng nó nghĩa là ai
 * mở được link mời thì có phiên, và đường này công khai.
 */
/** `matKhau === null` cho `invite_existing` — backend 422 nếu gửi thừa. */
export function nhanLoiMoi(token: string, matKhau: string | null): Promise<void> {
  return goi<void>('/api/v1/invites/accept', {
    method: 'POST',
    body: JSON.stringify(matKhau === null ? { token } : { token, password: matKhau }),
  })
}

// ─── Màn «Hồ sơ & tuỳ chọn» (/settings) — ba đường self-service ─────────────

/** Một ô của lưới «Đổi avatar» — chọn xong gửi đúng `seed` này vào `suaHoSo`. */
export interface GoiYAvatar {
  readonly seed: string
  readonly avatar: string
}

/**
 * Body của `PATCH /me/ho-so`. VẮNG KHOÁ = không đổi (JSON.stringify tự bỏ
 * `undefined`, khớp `model_fields_set` phía backend); `avatarSeed: null`
 * TƯỜNG MINH = về avatar mặc định suy từ tên.
 */
export interface SuaHoSoBody {
  readonly name?: string
  readonly phone?: string | null
  readonly jobTitle?: string | null
  readonly avatarSeed?: string | null
}

/** Trả `Session` MỚI — người gọi ghi thẳng vào cache `['session']` (cùng lối
 *  `LoginForm`), avatar ở chân sidebar đổi ngay không chờ refetch `/me`. */
export function suaHoSo(body: SuaHoSoBody): Promise<Session> {
  return goi<Session>('/api/v1/me/ho-so', { method: 'PATCH', body: JSON.stringify(body) })
}

/** 12 gợi ý mỗi lượt — muốn bộ khác thì gọi lại, seed sinh ở server. */
export function layGoiYAvatar(): Promise<GoiYAvatar[]> {
  return goi<GoiYAvatar[]>('/api/v1/me/avatar-goi-y')
}

/** 204 khi xong. Sai mật khẩu hiện tại → `LoiApi` MAT_KHAU_HIEN_TAI_SAI (400 —
 *  backend cố ý KHÔNG dùng 401 để khỏi lẫn với «phiên chết»); tài khoản
 *  Google-only → KHONG_CO_MAT_KHAU (409), nhưng màn đã ẩn form theo `coMatKhau`. */
export function doiMatKhau(matKhauHienTai: string, matKhauMoi: string): Promise<void> {
  return goi<void>('/api/v1/me/mat-khau', {
    method: 'POST',
    body: JSON.stringify({ matKhauHienTai, matKhauMoi }),
  })
}
