/**
 * Seam `/api/v1/members` — hợp đồng FE ĐỊNH TRƯỚC, backend chưa có 4 đường ghi.
 *
 * Test ở tầng seam (không qua giao diện) vì đây là chỗ hình dạng request được
 * chốt: sai `roleId` thành `role` ở đây là leo thang quyền, và không màn nào
 * bắt được vì cả hai đều là chuỗi.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { doiWorkspace } from '../src/features/auth/api'
import {
  doiVaiTroThanhVien,
  goThanhVien,
  guiLaiLoiMoi,
  moiLaiThanhVien,
  moiThanhVien,
  taiThanhVien,
  thuHoiLoiMoi,
} from '../src/features/auth/thanhVien'
import {
  FAKE_SESSION,
  RESET_LOI_MOI_GIA,
  RESET_USERS_GIA,
  RESET_WS_DANG_MO,
} from '../src/lib/msw/handlers'
import { server } from '../vitest.setup'

beforeEach(() => {
  RESET_USERS_GIA()
  RESET_WS_DANG_MO()
  // `LOI_MOI_GIA` là mảng module-level mà `thuHoiLoiMoi` `splice` thẳng vào
  // (xem bài ⑯) — thiếu reset ở đây thì một bài xoá lời mời giả để bàn trống
  // cho MỌI bài chạy SAU trong file này, kể cả những bài không hề nhắc tới
  // lời mời. Cùng khuôn với hai reset ngay trên.
  RESET_LOI_MOI_GIA()
})

describe('seam /api/v1/members', () => {
  it('① GET mang lifecycle', async () => {
    const ds = await taiThanhVien()
    expect(ds.length).toBeGreaterThan(0)
    // Owner phải THẬT SỰ có mặt trong tập trả về — không chỉ "nếu có mặt thì
    // đúng hình dạng". `ds.length > 0` một mình vẫn xanh khi owner biến mất
    // khỏi fake (đúng bug đã xảy ra ở Task 1: lọc owner ra khỏi `/members`) vì
    // các user khác vẫn còn trong mảng. Bài ⑧ dưới đây khoá chặt hơn — pin
    // đúng userId — còn dòng này là điều kiện TỐI THIỂU cho vòng lặp bên dưới
    // không trở thành vô nghĩa (không owner nào ⇒ nhánh `if` không bao giờ chạy).
    //
    // 2026-08-22: `ds` nay lẫn hàng `kind: 'invite'` (fake `LOI_MOI_GIA`) — hàng
    // đó KHÔNG có `lifecycle`/`userId` (`null` cả hai, đúng hợp đồng `MemberOut`),
    // nên phép kiểm dưới chỉ áp cho hàng `kind: 'member'`.
    const thanhVien = ds.filter((m) => m.kind === 'member')
    expect(thanhVien.length).toBeGreaterThan(0)
    for (const m of thanhVien) {
      expect(['pending', 'active', 'suspended']).toContain(m.lifecycle)
      // Chủ tổ chức KHÔNG có vai trò workspace (backend cưỡng chế `memberships`
      // rỗng, 422 nếu không) — `null`, không phải chuỗi rỗng.
      // Mọi hàng đều có membership thật ⇒ `roleId` luôn có giá trị.
      expect(m.roleId).toBeTruthy()
    }
    // Hàng `kind: 'invite'` của fake (`LOI_MOI_GIA`) nằm ở WORKSPACE MẶC ĐỊNH
    // (chuyển về đây 2026-08-22, Task 11 — xem docstring `LOI_MOI_GIA` ở
    // `lib/msw/handlers.ts`), nên nó có mặt NGAY ở đây, không cần chuyển
    // workspace. Đây là chỗ DUY NHẤT của seam test đi qua nhánh `raHangLoiMoi()`
    // — thiếu phép kiểm này thì hình dạng của hàng `invite` không được test seam
    // nào chạy qua cả.
    //
    // ĐÚNG HAI HÀNG, không "ít nhất một" (finding A, review round 2): fixture
    // mọc thêm một hàng `invite_existing` (`userId` không null) sau khi phát
    // hiện KHÔNG test nào từng render hình dạng đó — đếm CHÍNH XÁC 2 ở đây thay
    // vì `toBeGreaterThan(0)` để một hàng thứ ba lặng lẽ biến mất (hoặc thừa ra)
    // cũng làm bài này đỏ, không chỉ hàng đầu tiên bị quên.
    const loiMoi = ds.filter((m) => m.kind === 'invite')
    expect(loiMoi).toHaveLength(2)
    const chuaCoTaiKhoan = loiMoi.find((m) => m.userId === null)
    expect(chuaCoTaiKhoan?.name).toBeNull()
    expect(chuaCoTaiKhoan?.lifecycle).toBeNull()
    const daCoTaiKhoan = loiMoi.find((m) => m.userId !== null)
    expect(daCoTaiKhoan?.userId).toBe('u_fake_minh')
    expect(daCoTaiKhoan?.name).toBe('Phạm Văn Minh')
    expect(daCoTaiKhoan?.lifecycle).toBe('active')
  })

  it('② POST gửi ĐÚNG {emails, roleId} — không gửi role, không gửi expiresAt', async () => {
    let than: unknown = null
    server.use(
      http.post('/api/v1/members', async ({ request }) => {
        than = await request.json()
        return HttpResponse.json({ invites: [] })
      }),
    )
    await moiThanhVien(['a@x.vn', 'b@x.vn'], 'role_gia_xem')
    expect(than).toEqual({ emails: ['a@x.vn', 'b@x.vn'], roleId: 'role_gia_xem' })
  })

  it('③ PATCH gửi roleId, KHÔNG gửi tên vai trò', async () => {
    let than: unknown = null
    server.use(
      http.patch('/api/v1/members/:id', async ({ request }) => {
        than = await request.json()
        return HttpResponse.json({
          userId: 'u1',
          name: 'A',
          email: 'a@x.vn',
          roleId: 'role_gia_xem',
          role: 'Người xem',
          lifecycle: 'active',
        })
      }),
    )
    const ra = await doiVaiTroThanhVien('u1', 'role_gia_xem')
    expect(than).toEqual({ roleId: 'role_gia_xem' })
    expect(ra.role).toBe('Người xem')
  })

  it('④ DELETE trả 204 và KHÔNG ném', async () => {
    server.use(http.delete('/api/v1/members/:id', () => new HttpResponse(null, { status: 204 })))
    await expect(goThanhVien('u1')).resolves.toBeUndefined()
  })

  it('⑤ mời lại trả invitePath có thể là null (ngày backend có mailer)', async () => {
    server.use(
      http.post('/api/v1/members/:id/invite', () => HttpResponse.json({ invitePath: null })),
    )
    await expect(moiLaiThanhVien('u1')).resolves.toEqual({ invitePath: null })
  })

  it('⑥ lỗi có envelope thì ném LoiApi mang đúng code', async () => {
    server.use(
      http.post('/api/v1/members', () =>
        HttpResponse.json(
          { error: { code: 'ROLE_NOT_IN_ORG', message: 'Vai trò không thuộc tổ chức này.' } },
          { status: 422 },
        ),
      ),
    )
    await expect(moiThanhVien(['a@x.vn'], 'role_cua_to_chuc_khac')).rejects.toMatchObject({
      code: 'ROLE_NOT_IN_ORG',
    })
  })

  // ⑦ `PATCH chặn CHỦ TỔ CHỨC` XOÁ 2026-08-15: không còn `orgRole`, và mọi người
  // trong bảng thành viên đều có một hàng `memberships` thật — kể cả người tạo
  // workspace (họ mang vai trò "Quản trị").

  // ── ⑧⑨: PORTED từ `tests/vai-tro.test.tsx` (xoá ở Task 2 review round 1) ──
  //
  // Cả hai là `await fetch(...)` trần, không render gì — khác 10 bài còn lại
  // của file đó (đi qua UI đã bị xoá cùng tab «Vai trò»), nên chúng KHÔNG chết
  // theo. Đi qua ĐÚNG hạ tầng toàn cục (`USERS_GIA`/`WS_DANG_MO`), không
  // `server.use(...)` fixture riêng — nếu không thì không còn kiểm được đúng
  // điều chúng tồn tại để kiểm: hạ tầng `/members` thật của repo, không phải
  // một mảng bịa cho riêng bài test.

  it('⑧ GET /api/v1/members chỉ trả người CÓ membership còn hiệu lực ở workspace hiện tại (cộng chủ tổ chức), role lấy tên thật', async () => {
    // `u_fake_lan` (seed sẵn trong USERS_GIA) ở đúng workspace hiện tại
    // (WS_GIA_1 === FAKE_SESSION.currentWorkspaceId), vai trò role_gia_qt =
    // Quản trị. `u_fake_minh`/`u_fake_cho` ở WS_GIA_2 — không thuộc workspace
    // hiện tại nên KHÔNG được trả.
    //
    // ĐẢO NGƯỢC 2026-08-15: `u_fake_dang` (không membership) KHÔNG còn xuất hiện.
    // Bất biến cũ ("chủ tổ chức có mặt ở mọi workspace dù không có dòng nào") đi
    // cùng nhánh owner trong `doc_quyen()`, đã bỏ. Bảng thành viên giờ đúng bằng
    // tập `memberships` — và đó cũng là tập người thật sự vào được workspace này.
    const res = await fetch('/api/v1/members')
    const body = (await res.json()) as {
      kind: 'member' | 'invite'
      userId: string | null
      name: string
      role: string | null
    }[]
    // Lọc `kind: 'member'` TRƯỚC khi so — hàng `invite` của fake (`LOI_MOI_GIA`,
    // 2026-08-22) cũng đứng ở workspace hiện tại (xem docstring nó ở
    // `lib/msw/handlers.ts`), nhưng lọc theo `kind` là đúng cách đọc bảng này kể
    // từ nay, không phải một điều kiện tình cờ đúng.
    const thanhVien = body.filter((m) => m.kind === 'member')
    expect(thanhVien.map((m) => m.userId).sort()).toEqual(['u_fake_lan'])
    expect(thanhVien.find((m) => m.userId === 'u_fake_dang')).toBeUndefined()
    const lan = thanhVien.find((m) => m.userId === 'u_fake_lan')
    expect(lan?.role).toBe('Quản trị')
  })

  it('⑨ GET /api/v1/members đi theo workspace ĐANG MỞ, không ghim workspace khởi đầu', async () => {
    // Nguồn hiện hàng (`session.currentWorkspaceId`, đổi sau khi bấm switcher)
    // và nguồn fake lọc (`WS_DANG_MO`) phải là MỘT nguồn cho một sự thật — nếu
    // fake ghim workspace khởi đầu thay vì đi theo `doiWorkspace()`, hàng hiển
    // thị và hàng bị PATCH đến từ hai workspace khác nhau: đúng lớp lỗi rò dữ
    // liệu xuyên workspace mà hợp đồng cách ly tồn tại để chặn.
    const ws2 = FAKE_SESSION.workspaces[1]!.id
    await doiWorkspace(ws2)

    const res = await fetch('/api/v1/members')
    const body = (await res.json()) as {
      kind: 'member' | 'invite'
      userId: string | null
      name: string | null
      lifecycle: string | null
    }[]
    // `u_fake_minh` + `u_fake_cho` seed ở WS_GIA_2; `u_fake_lan` (WS_GIA_1) PHẢI
    // biến mất — nếu fake còn ghim workspace đầu thì tập trả về không đổi. Chủ
    // tổ chức (`u_fake_dang`) có mặt ở MỌI workspace nên vẫn còn trong tập này.
    const thanhVien = body.filter((m) => m.kind === 'member')
    expect(thanhVien.map((m) => m.userId).sort()).toEqual(['u_fake_cho', 'u_fake_minh'])

    // `LOI_MOI_GIA` (fake lời mời, 2026-08-22) đứng ở WS_GIA_1 — workspace MẶC
    // ĐỊNH, không phải WS_GIA_2 (xem docstring ở `lib/msw/handlers.ts`). Cách ly
    // xuyên workspace phải áp CẢ cho hàng lời mời, không chỉ hàng thành viên:
    // đứng ở WS_GIA_2 thì KHÔNG được thấy lời mời của workspace khác. Bài ① ở
    // trên là chỗ đi qua nhánh `raHangLoiMoi()` khi hàng đó CÓ mặt.
    const loiMoi = body.filter((m) => m.kind === 'invite')
    expect(loiMoi).toHaveLength(0)
  })

  // ── ⑩-⑯: hai seam MỚI 2026-08-22 (`guiLaiLoiMoi`/`thuHoiLoiMoi`) — review
  // round 1 chỉ ra cả hai lẫn hai handler MSW mới đứng KHÔNG một test nào canh.
  // `chuaco@anphuland.vn` là ĐÚNG email seed sẵn trong `LOI_MOI_GIA` (xem
  // `lib/msw/handlers.ts`) — dùng nó cho nhánh THÀNH CÔNG đi qua handler THẬT,
  // không phải fixture riêng.

  it('⑩ guiLaiLoiMoi — POST đúng URL (email encode), trả đúng hình dạng {invitePath}', async () => {
    let phuong: string | null = null
    let duong: string | null = null
    server.use(
      http.post('/api/v1/members/invites/:email/resend', ({ request }) => {
        phuong = request.method
        duong = new URL(request.url).pathname
        return HttpResponse.json({ invitePath: '/invite/tok_gia_lai' })
      }),
    )
    await expect(guiLaiLoiMoi('chuaco@anphuland.vn')).resolves.toEqual({
      invitePath: '/invite/tok_gia_lai',
    })
    expect(phuong).toBe('POST')
    expect(duong).toBe('/api/v1/members/invites/chuaco%40anphuland.vn/resend')
  })

  it('⑪ guiLaiLoiMoi — encode ĐÚNG một email cần encode thật (a+b@x.vn, không phải a@x.vn)', async () => {
    // `a@x.vn` không cần encode gì — một lỗi quên `encodeURIComponent` vẫn lọt
    // qua bài kiểu đó. `+` trần lọt vào một path segment là hỏng THẬT (một số
    // pipeline đọc nó thành khoảng trắng); đây là ca `encodeURIComponent` phải
    // xử lý đúng: `a+b@x.vn` → `a%2Bb%40x.vn`.
    let duong: string | null = null
    server.use(
      http.post('/api/v1/members/invites/:email/resend', ({ request }) => {
        duong = new URL(request.url).pathname
        return HttpResponse.json({ invitePath: null })
      }),
    )
    await guiLaiLoiMoi('a+b@x.vn')
    expect(duong).toBe('/api/v1/members/invites/a%2Bb%40x.vn/resend')
  })

  it('⑫ guiLaiLoiMoi — 404 INVITE_NOT_FOUND khi không có lời mời đang chờ', async () => {
    await expect(guiLaiLoiMoi('khong-co-loi-moi-nao@x.vn')).rejects.toMatchObject({
      code: 'INVITE_NOT_FOUND',
    })
  })

  it('⑬ thuHoiLoiMoi — DELETE đúng URL (email encode), 204 → resolves undefined (KHÔNG ném)', async () => {
    let phuong: string | null = null
    let duong: string | null = null
    server.use(
      http.delete('/api/v1/members/invites/:email', ({ request }) => {
        phuong = request.method
        duong = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await expect(thuHoiLoiMoi('chuaco@anphuland.vn')).resolves.toBeUndefined()
    expect(phuong).toBe('DELETE')
    expect(duong).toBe('/api/v1/members/invites/chuaco%40anphuland.vn')
  })

  it('⑭ thuHoiLoiMoi — encode ĐÚNG một email cần encode thật (a+b@x.vn)', async () => {
    let duong: string | null = null
    server.use(
      http.delete('/api/v1/members/invites/:email', ({ request }) => {
        duong = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await thuHoiLoiMoi('a+b@x.vn')
    expect(duong).toBe('/api/v1/members/invites/a%2Bb%40x.vn')
  })

  it('⑮ thuHoiLoiMoi — 404 INVITE_NOT_FOUND khi không có lời mời đang chờ', async () => {
    await expect(thuHoiLoiMoi('khong-co-loi-moi-nao@x.vn')).rejects.toMatchObject({
      code: 'INVITE_NOT_FOUND',
    })
  })

  it('⑯ thuHoiLoiMoi xoá THẬT khỏi LOI_MOI_GIA (qua handler thật) — RESET_LOI_MOI_GIA() khôi phục', async () => {
    // KHÔNG override handler ở bài này — đi qua đúng `splice()` thật trong
    // `handlers.ts`, để hai lời gọi `guiLaiLoiMoi` dưới đây thật sự phân biệt
    // được "hàng còn" và "hàng mất", không phải hai fixture giả canh nhau.
    await thuHoiLoiMoi('chuaco@anphuland.vn')
    // Hàng đã mất: gửi lại cho ĐÚNG email đó giờ phải 404 — không phải một
    // fixture khác tình cờ trùng hành vi.
    await expect(guiLaiLoiMoi('chuaco@anphuland.vn')).rejects.toMatchObject({
      code: 'INVITE_NOT_FOUND',
    })

    // `RESET_LOI_MOI_GIA()` phải khôi phục ĐÚNG hàng khởi đầu — không chỉ
    // "không ném lỗi nữa". Không gọi hàm này thì bài test SAU trong file (nếu
    // có bài mới thêm sau ⑯) sẽ thấy bàn trống mà không hiểu vì sao — đây là
    // đúng phép kiểm mà review round 1 yêu cầu cho `RESET_LOI_MOI_GIA()`.
    RESET_LOI_MOI_GIA()
    await expect(guiLaiLoiMoi('chuaco@anphuland.vn')).resolves.toEqual({ invitePath: null })
  })
})
