/**
 * Seam `/api/v1/members` — thành viên của WORKSPACE đang mở. SEAM CHÍNH của màn
 * `/users` từ 2026-08-09.
 *
 * Kiểu (`MemberOut`, `KetQuaMoi`) khai CỤC BỘ ở đây, không nhập từ `../api`: mọi
 * đường ở tệp này thuộc phạm vi WORKSPACE, còn `api.ts` gom seam cấp TỔ CHỨC.
 * `goi()` — client fetch dùng chung, đọc envelope lỗi — nhập TỪ `api.ts` (export
 * 2026-08-09): cùng thư mục, giữ hai bản là chờ ngày một bản sửa mà bản kia không.
 *
 * ⚠ BỐN ĐƯỜNG GHI DƯỚI ĐÂY LÀ HỢP ĐỒNG FE ĐỊNH TRƯỚC — backend CHƯA CÓ (2026-08-09).
 * Cùng lối `POST /agent/try` và `GET/PATCH /linh-vuc` đã đi. Fake ở
 * `lib/msw/handlers.ts`. Đừng lấy hành vi fake làm sự thật về backend.
 *
 * Spec: docs/superpowers/specs/2026-08-09-gon-thanh-vien-va-phan-quyen-design.md §4
 */
import { goi } from '@/lib/http'
import type { Lifecycle } from './api'

/**
 * Hàng của `GET /api/v1/members` — MỘT TRONG HAI LOẠI HÀNG từ 2026-08-22.
 *
 * Trước đó mọi hàng là một membership. Nay bảng còn liệt kê LỜI MỜI ĐANG TREO, vì
 * một email chưa có tài khoản không còn hàng `users` nào để xuất hiện — mà nó vẫn
 * phải xuất hiện ở đâu đó, nếu không thì mời 10 người xong bảng không đổi gì và
 * không có chỗ nào bấm «gửi lại».
 *
 * `tests/membership-shape-parity.test.ts` neo cổng hình dạng vào ĐÚNG khai báo này.
 */
export interface MemberOut {
  /**
   * ĐỌC TRƯỜNG NÀY TRƯỚC MỌI TRƯỜNG KHÁC. Nó quyết định ba trường dưới có giá trị
   * hay không, và quyết định hàng đó dùng đường ghi nào.
   */
  readonly kind: 'member' | 'invite'
  /**
   * `null` ⇔ `kind === 'invite'` cho một email chưa có tài khoản.
   *
   * ⚠ TRƯỜNG DỄ GÂY LỖI NHẤT Ở ĐÂY. Nó từng là `string` và được dùng làm React key
   * lẫn path param của `PATCH`/`DELETE /members/{id}`. Một `null` chạy lọt sẽ dựng
   * `/api/v1/members/null` và trả 404 mà không ai hiểu vì sao. Dùng `khoaHang()`
   * cho key, và rẽ theo `kind` trước mọi đường ghi.
   */
  readonly userId: string | null
  /** `null` cùng lúc với `userId` — chưa có hàng `users` nào mang một cái tên. */
  readonly name: string | null
  /** Trường DUY NHẤT luôn có ở cả hai loại hàng ⇒ định danh của hàng lời mời. */
  readonly email: string
  /**
   * ID vai trò (`control.roles.id`) — handle ỔN ĐỊNH mà mọi đường ghi neo vào.
   *
   * ĐỐI CHIẾU NGƯỢC TÊN -> id ĐÃ BỊ XOÁ 2026-08-07 — ĐỪNG DỰNG LẠI. Tên vai trò
   * là khoá ĐỔI ĐƯỢC: hai vai trò trùng tên, hoặc một tên vừa dời sang vai trò
   * khác, là đủ để phép dò khớp SANG một tập quyền không ai cấp. Đó là lỗi leo
   * thang quyền xuyên workspace ĐÃ ĐO ĐƯỢC, không phải rủi ro lý thuyết.
   *
   * ⚠ GIỮ `| null` dù backend hiện khai `str` (không nullable). Lý lẽ cũ («null
   * khi và chỉ khi chủ tổ chức») đã chết cùng `isOrgOwner` — nhưng `null` chứ
   * không `''` vẫn đúng: chuỗi rỗng đi lọt mọi phép kiểm truthy rồi chết ở
   * `<select value="">` (hiện OPTION ĐẦU, tức nói người này giữ một vai trò họ
   * không giữ). Dung thứ `null` ở đây là lưới, không phải hợp đồng.
   *
   * (giữ nguyên docstring cũ) Với hàng `invite` đây là vai trò ĐÃ HỨA.
   */
  readonly roleId: string | null
  /** TÊN vai trò — để HIỆN, KHÔNG để khớp. */
  readonly role: string | null
  /**
   * `users.lifecycle`, `null` cùng lúc với `userId`.
   *
   * ⚠ KHÔNG PHẢI trạng thái hiển thị của hàng. Hàng `invite` hiện «Chờ xác nhận lời
   * mời» BẤT KỂ giá trị này — trạng thái đó suy từ `kind`. Trộn hai thứ vào một cột
   * là lý do nhãn `pending` phải đổi tên (xem `nhan.ts`).
   *
   * ⚠ Trường này FE khai từ 2026-08-09 nhưng backend CHƯA BAO GIỜ trả, cho tới
   * 2026-08-17. Tám ngày cột «Trạng thái» hiện pill trống, bộ lọc trạng thái trả
   * bảng rỗng, và mục «Gửi lại lời mời» không bao giờ hiện — mà không một cổng nào
   * đỏ, vì fake MSW CÓ trường này còn backend thật thì không. Nay có cổng ở
   * `odyssey-portal-backend/tests/api/test_hop_dong_member_out.py` đóng băng tập
   * trường phía BE; thêm/bớt trường ở interface này thì sửa cổng đó CÙNG commit.
   */
  readonly lifecycle: Lifecycle | null
  /** ISO 8601, chỉ hàng `invite`. */
  readonly invitedAt: string | null
  /** ISO 8601, chỉ hàng `invite` — còn bao lâu trước khi phải mời lại. */
  readonly expiresAt: string | null
  /**
   * Data URI SVG DiceBear — CÙNG công thức với `/me` (`avatar_seed or name`),
   * nên bảng hiện đúng avatar người đó đã set ở «Hồ sơ & tuỳ chọn» (2026-08-25;
   * trước đó bảng tự vẽ chữ cái nên LỆCH với avatar chân sidebar).
   *
   * TUỲ CHỌN là khiên trường-mới: `taiThanhVien()` là `goi<MemberOut[]>()` trần
   * không chuẩn hoá, backend cũ chưa trả thì `undefined` chạy thẳng vào UI —
   * `HangThanhVien` rơi về chữ cái như cũ. `null` cho hàng `kind='invite'`
   * (hiện phong bì, không có gì để vẽ).
   */
  readonly avatar?: string | null
}

/**
 * React key an toàn cho cả hai loại hàng.
 *
 * `m.userId` một mình KHÔNG dùng được: nó `null` cho mọi lời mời của email chưa có
 * tài khoản, và React coi `key={null}` là không có key — hai hàng như thế sẽ tráo
 * state cho nhau khi bảng lọc lại. Tiền tố `kind` vì một người vừa là thành viên
 * vừa có lời mời treo sẽ cho hai hàng cùng email (xem docstring
 * `repo.liet_ke_thanh_vien` phía backend về vì sao ca đó không bị khử).
 */
export function khoaHang(m: MemberOut): string {
  return `${m.kind}:${m.userId ?? m.email}`
}

/**
 * Một email KHÔNG mời được, ghi TỪNG DÒNG (2026-08-17) — mời 40 người mà một
 * người hỏng thì 39 người kia vẫn phải vào được, không phải cả lô rớt theo.
 *
 * Mã `ma` hiện có: `USER_PENDING_SIGNUP` (người đó đang tự đăng ký dở — chưa
 * đặt mật khẩu xong, nên chưa thêm vào workspace được lúc này), `USER_SUSPENDED`
 * (tài khoản đang bị đình chỉ — thêm vào workspace mới sẽ hoàn tác chính việc
 * đình chỉ đó), và `USER_ALREADY_MEMBER` (người đó đã là thành viên của
 * workspace đang mở — mời lại qua đường này sẽ không làm gì, đổi vai trò là
 * việc của `PATCH /members/{id}`, không phải của lời mời).
 */
export interface LoiMoiTungDong {
  readonly email: string
  readonly ma: string
}

/** Kết quả mời MỘT email. `invitePath === null` = backend đã gửi email hộ. */
export interface KetQuaMoi {
  readonly email: string
  /**
   * `null` ⇔ email này CHƯA có tài khoản (`daCo === false`).
   *
   * ⚠ ĐỔI KIỂU 2026-08-22 — trước đó khai `string` (không nullable), SAI: mời
   * một email chưa có tài khoản không còn tạo `users` ngay lúc mời (đúng lý do
   * `daCo` đổi nghĩa ở dưới) — hàng `users` chỉ sinh ra khi người nhận bấm xác
   * nhận trong thư và tự đặt mật khẩu. Tại thời điểm `POST /members` trả về,
   * chưa có `userId` nào để cho. Type cũ hứa một giá trị mà API không đảm bảo;
   * lọt qua một lượt review vì không component nào TRẢI (`!`) giá trị này ra
   * lỗi lúc build hay lúc chạy — nó chỉ đứng im trong response, không ai đọc.
   *
   * Cùng NGHĨA NULLABLE với `MemberOut.userId` ở trên, và cùng LÝ DO: cả hai
   * đều `null` đúng lúc một email chưa có hàng `users` nào đứng tên.
   */
  readonly userId: string | null
  /**
   * Đường dẫn tương đối (`/invite/<token>`), hoặc `null`.
   *
   * `string | null` NGAY TỪ HỢP ĐỒNG là có chủ ý: backend hôm nay không có bộ
   * gửi mail (`grep -rEi 'smtp|sendgrid|mailgun|send_email' src` → rỗng,
   * 2026-08-09) nên admin phải tự copy link đi gửi. Ngày dựng mailer, backend
   * đổi GIÁ TRỊ chứ không đổi HÌNH DẠNG, và chỉ panel kết quả trong
   * `MoiThanhVienDialog` phải sửa.
   */
  readonly invitePath: string | null
  /**
   * `true` = email này ĐÃ CÓ tài khoản trong hệ thống.
   *
   * ⚠ ĐỔI NGHĨA 2026-08-22, GIỮ NGUYÊN HÌNH DẠNG. Nghĩa CŨ: «đã thêm thẳng vào
   * workspace, không cần lời mời». Nay KHÔNG còn nhánh nào thêm thẳng — cả hai
   * nhánh đều gửi thư xin xác nhận. Dùng nó để chọn CÂU, không để chọn có hiện
   * link hay không.
   */
  readonly daCo: boolean
}

/** Khoá React Query — MỘT chỗ. Hai khoá cho một endpoint là lỗi đã sửa ở `features/platform`. */
export const KHOA_TV = ['members'] as const

export function taiThanhVien(): Promise<MemberOut[]> {
  return goi<MemberOut[]>('/api/v1/members')
}

/**
 * Mời NHIỀU email cùng MỘT vai trò, một lượt.
 *
 * Một vai trò cho cả lô là có chủ ý (lối ElevenLabs · Linear · Vercel): muốn hai
 * vai trò thì mời hai lượt. Cho phép mỗi email một vai trò biến hộp thoại thành
 * một bảng con, và đó là thứ vừa bị cắt khỏi màn này.
 *
 * KHÔNG có `expiresAt` trong thân — hạn membership đã rời giao diện 2026-08-09;
 * server đặt `NULL`.
 */
export function moiThanhVien(
  emails: readonly string[],
  roleId: string,
): Promise<{ invites: KetQuaMoi[]; loi: LoiMoiTungDong[] }> {
  return goi<{ invites: KetQuaMoi[]; loi: LoiMoiTungDong[] }>('/api/v1/members', {
    method: 'POST',
    body: JSON.stringify({ emails, roleId }),
  })
}

/**
 * Đổi vai trò TẠI WORKSPACE ĐANG MỞ.
 *
 * ⚠ ĐỪNG THAY BẰNG `PATCH /users/{id}` — đường cũ nhận TOÀN BỘ `memberships` và
 * THAY THẾ, không cộng dồn, nên gọi nó với một dòng là xoá sạch vai trò của
 * người đó ở mọi workspace khác (bug mất dữ liệu thật, 2026-08-06). Endpoint này
 * chỉ chạm đúng một dòng, nên cả lớp lỗi đó không tồn tại.
 */
export function doiVaiTroThanhVien(userId: string, roleId: string): Promise<MemberOut> {
  return goi<MemberOut>(`/api/v1/members/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ roleId }),
  })
}

/**
 * Gỡ khỏi WORKSPACE — KHÔNG xoá tài khoản khỏi tổ chức.
 *
 * Đường này giải một lỗ đang có: `DELETE /users/{id}` chỉ chạy khi user còn
 * `pending`, ngoài ra 409 `USER_NOT_PENDING` — tức trước 2026-08-09 KHÔNG có
 * đường gỡ một người đang hoạt động khỏi workspace.
 */
export function goThanhVien(userId: string): Promise<void> {
  return goi<void>(`/api/v1/members/${encodeURIComponent(userId)}`, { method: 'DELETE' })
}

/**
 * Cấp token MỚI cho một lời mời đang treo. Token cũ chết ngay khi hàm này trả về.
 *
 * ĐỊNH DANH LÀ EMAIL, không phải `userId`: hàng lời mời của một email chưa có tài
 * khoản không có `userId` nào. KHÁC `moiLaiThanhVien(userId)` ngay dưới — đường kia
 * phục vụ hàng THÀNH VIÊN còn `pending` (di sản) và nó đặt lại mật khẩu.
 */
export function guiLaiLoiMoi(email: string): Promise<{ invitePath: string | null }> {
  return goi<{ invitePath: string | null }>(
    `/api/v1/members/invites/${encodeURIComponent(email)}/resend`,
    { method: 'POST' },
  )
}

/** Thu hồi — XOÁ lời mời. 404 `INVITE_NOT_FOUND` khi không còn gì để thu hồi. */
export function thuHoiLoiMoi(email: string): Promise<void> {
  return goi<void>(`/api/v1/members/invites/${encodeURIComponent(email)}`, { method: 'DELETE' })
}

/** Sinh lời mời MỚI. Token cũ chết ngay khi hàm này trả về. */
export function moiLaiThanhVien(userId: string): Promise<{ invitePath: string | null }> {
  return goi<{ invitePath: string | null }>(
    `/api/v1/members/${encodeURIComponent(userId)}/invite`,
    { method: 'POST' },
  )
}

/** `/invite/<token>` -> URL đầy đủ để copy. `null` đi qua nguyên vẹn. */
export function urlMoi(invitePath: string | null): string | null {
  return invitePath === null ? null : `${window.location.origin}${invitePath}`
}
