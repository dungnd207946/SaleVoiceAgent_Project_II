/**
 * CỔNG 5 — hình dạng `MemberOut`: fake MSW ↔ kiểu FE khai.
 *
 * VÌ SAO CẦN: hợp đồng này được CHÉP TAY ở ba nơi — `contracts.py` của backend,
 * `api.ts`/`thanhVien.ts` của FE, và `lib/msw/handlers.ts` (fake). Hai cổng
 * parity đang có (`actions-parity`, `tools-parity`) canh danh sách action và sổ
 * kỹ năng, KHÔNG canh hình dạng DTO nào: trước file này, backend ship thêm một
 * trường mà FE không theo thì không có gì đỏ lên — fake vẫn trả hình dạng cũ, mọi
 * test màn vẫn xanh, và cái sai chỉ lộ ra khi tắt MSW. `roleId` (2026-08-07) là
 * đúng một lần như thế, và nó là trường chặn leo thang quyền.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 *  CÁCH DỰNG CỔNG — hai lớp, mỗi lớp bắt một hướng lệch
 * ═══════════════════════════════════════════════════════════════════════════
 * Kiểu TS bị xoá lúc chạy nên không so trực tiếp được. Nên tập khoá kỳ vọng khai
 * bằng `Record<keyof T, true>` chứ không phải một mảng chuỗi:
 *
 *  ① `tsc -b` đỏ khi INTERFACE đổi mà file này chưa theo. `Record` bắt CẢ hai
 *     hướng — thiếu khoá thì báo "missing property", thừa khoá thì báo object
 *     literal có thuộc tính lạ. Một `readonly string[]` chỉ bắt được hướng thừa.
 *  ② `vitest` đỏ khi FAKE đổi mà interface chưa theo (hoặc ngược lại): tập khoá
 *     chạy thật của response phải bằng ĐÚNG `Object.keys` của bản đồ trên.
 *
 * Đo qua HTTP: thứ FE thật sự đọc là THÂN RESPONSE, không phải hàm nội bộ của
 * `handlers.ts`.
 *
 * KHÔNG canh backend từ đây: repo này không chạy được `contracts.py`. Cổng này
 * canh FE tự nhất quán với chính nó; khớp với backend vẫn là việc đọc commit BE.
 */
import { describe, expect, it } from 'vitest'
import type { MemberOut } from '../src/features/auth/thanhVien'

/** `GET /members` → mỗi hàng. MƯỜI trường từ 2026-08-25 (`avatar` — xem
 *  docstring `MemberOut.avatar` ở `thanhVien.ts`). */
const MAU_MEMBER_OUT: Record<keyof MemberOut, true> = {
  kind: true,
  userId: true,
  name: true,
  email: true,
  roleId: true,
  role: true,
  lifecycle: true,
  invitedAt: true,
  expiresAt: true,
  avatar: true,
}

/** So theo TẬP, không theo thứ tự — thứ tự khoá không phải hợp đồng. */
function khoaCua(o: object): string[] {
  return Object.keys(o).sort()
}

async function lay(duong: string): Promise<unknown> {
  const res = await fetch(duong)
  expect(res.status, `${duong} phải 200`).toBe(200)
  return res.json()
}

describe('cổng 5 — hình dạng membership: fake ↔ kiểu FE', () => {
  it('GET /api/v1/members — mỗi hàng có đúng tập khoá của MemberOut', async () => {
    const ds = (await lay('/api/v1/members')) as Record<string, unknown>[]

    expect(ds.length).toBeGreaterThan(0)
    for (const m of ds) expect(khoaCua(m)).toEqual(khoaCua(MAU_MEMBER_OUT))
  })

  it('GET /api/v1/members — hàng kind="invite" (userId null) cũng đúng ĐÚNG tập khoá', async () => {
    // Hàng `invite` của fake (`LOI_MOI_GIA`) nằm ở WORKSPACE MẶC ĐỊNH của
    // `FAKE_SESSION` (chuyển về đây 2026-08-22, Task 11 — xem docstring
    // `LOI_MOI_GIA` ở `lib/msw/handlers.ts`), nên không cần chuyển workspace: nó
    // đã đi qua nhánh `raHangLoiMoi()` ngay ở lần gọi đầu tiên, cùng nhánh
    // `member`.
    const ds = (await lay('/api/v1/members')) as MemberOut[]
    for (const m of ds) expect(khoaCua(m)).toEqual(khoaCua(MAU_MEMBER_OUT))

    // Đếm TRƯỚC khi so `userId`: một fake chỉ trả hàng `member` (nói dối theo
    // hướng DỄ HƠN thật) vẫn làm `ds.some(...)` dưới đây `false` một cách im
    // lặng nếu không đếm — đúng cái bẫy CLAUDE.md đã ghi cho `lib/msw/handlers.ts`.
    //
    // ĐÚNG HAI HÀNG (finding A, review round 2): `LOI_MOI_GIA` mang cả
    // `invite_new` (`userId: null`) VÀ `invite_existing` (`userId` thật) — trước
    // đợt sửa này chỉ có hàng đầu, nên không cổng nào từng thấy hình dạng thứ
    // hai. `toHaveLength(2)` thay vì `toBeGreaterThan(0)` để một hàng biến mất
    // (hoặc thừa ra) cũng đỏ, không chỉ hàng bị quên hoàn toàn.
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

  it('roleId của fake là id thật trong /api/v1/roles, không phải tên rơi qua', async () => {
    // `tenVaiTroGia` rơi về CHÍNH id khi không tra được tên, nên hai trường có thể
    // bằng nhau và cổng khoá ở trên vẫn xanh. Kiểm giá trị mới thấy.
    //
    // BỎ QUA hàng chủ tổ chức (2026-08-09): backend cưỡng chế `memberships` rỗng
    // với owner nên `roleId` của họ là `null` — không phải một id tra được, và
    // cũng không phải một lỗi. Lọc `!== null` — trường `isOrgOwner` từng dùng cho việc này đã gỡ 2026-08-17:
    // vị từ phải nói về thứ đang kiểm (có id hay không), không nói về lý do.
    const roles = (await lay('/api/v1/roles')) as { id: string }[]
    const ds = (await lay('/api/v1/members')) as { roleId: string | null }[]
    const coVaiTro = ds.filter((m) => m.roleId !== null)

    // Đếm TRƯỚC khi so: `[].every(...)` là true, nên thiếu dòng này thì một fake
    // trả toàn `null` làm cổng xanh vĩnh viễn.
    expect(coVaiTro.length).toBeGreaterThan(0)
    for (const m of coVaiTro) expect(roles.map((r) => r.id)).toContain(m.roleId)
  })
})
