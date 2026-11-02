# Gọn màn Thành viên & Phân quyền — Kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biến `/users` từ hai-tab-hai-trục-tám-khái-niệm thành **một bảng thành viên của workspace đang mở**, với vai trò dựng sẵn và luồng mời một bước.

**Architecture:** Trục dữ liệu đổi từ `GET /users` (tổ chức) sang `GET /members` (workspace). `features/auth/thanhVien.ts` lên làm seam chính và mọc thêm 4 hàm ghi. `UserAdmin.tsx` bỏ vai trò container-2-tab, trở thành một bảng phẳng. Ba đường ghi (đổi vai trò · gỡ · mời) đi qua menu `⋯` và một hộp thoại. Tab «Vai trò» cùng toàn bộ cây tạo-vai-trò bị xoá; 13 action ở lại backend.

**Tech Stack:** React 19 · TanStack Router (file-based) + Query v5 · Tailwind v4 · MSW v2 · Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-09-gon-thanh-vien-va-phan-quyen-design.md`

## Global Constraints

- **Cưỡng chế KHÔNG đổi.** Không thêm action vào `lib/actions.ts`, không đụng `contracts/actions.json`. `tests/actions-parity.test.ts` phải xanh mà không sửa gì.
- **Không mã màu ngoài `styles/theme.css`.** Không `bg-[#...]`, không `text-[#...]`.
- **Bo góc khoá 3 bậc.** `rounded-sm` · `rounded-md` · `rounded-lg` (+ `rounded-full`). **Không `rounded-[Npx]`.**
- **Hàng nút dùng hằng `HANG_NUT`** (`components/ui/Bang.tsx`) — căn phải, nút chính đứng cuối. Không khai lại `flex … gap-*`.
- **Đường về dùng hằng `DUONG_VE`.**
- **Không sửa `src/components/shell/*`.** `tests/module-boundaries.test.ts` quét cả thư mục đó tìm tên màn viết cứng.
- **`features/auth` chỉ được import:** `features/auth/…` · `lib/…` · `components/…` · `i18n/…`.
- **Chạy test bằng `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`** nếu máy đang Node ≥ 24. Không có cờ đó thì ~210 bài đỏ với lỗi trỏ nhầm vào `i18n`. Kiểm `node --version` trước khi kết luận nhánh hỏng.
- **`npx tsc --noEmit` là cổng RỖNG ở repo này** (tsconfig solution-style, thoát 0 mà không đọc file nào). Typecheck thật: **`npx tsc -b --force`**.
- **`prettier` chấm theo file** — sửa file nào thì `npx prettier --write` trọn file đó.
- **Mốc đỏ có sẵn:** chạy `vitest run` **TRƯỚC** khi sửa gì để có ảnh chụp. Đừng nhận cái đỏ có sẵn là của mình.
- ⚠ **KHÔNG `git add -A` và KHÔNG `git add .`.** Cây làm việc có một tệp untracked không thuộc việc này (`public/_mau-landing.html`); `-A` sẽ nuốt nó vào commit của bạn. Luôn `git add src/ tests/ docs/` hoặc liệt kê đường dẫn.

### Dữ liệu fake — số liệu THẬT, đừng đoán

Đã đọc `src/lib/msw/handlers.ts` 2026-08-09. Test nào chạm tới chúng phải dùng đúng chuỗi này:

| `VAI_TRO_GIA` | id               | name        |
| ------------- | ---------------- | ----------- |
| ①             | `role_gia_qt`    | `Quản trị`  |
| ②             | `role_gia_xem`   | `Người xem` |
| ③             | `role_gia_trong` | `Trống`     |

**Không có vai trò nào tên «CSKH» hay «Biên tập» trong fake.** Bốn vai trò của PQ_01 §2.2 là chuyện của backend seed, không phải của fake này.

| `USERS_GIA` | id                     | tên               | workspace               | vai trò        | lifecycle |
| ----------- | ---------------------- | ----------------- | ----------------------- | -------------- | --------- |
| owner       | `FAKE_SESSION.user.id` | Trần Hải Đăng     | _(không có membership)_ | —              | `active`  |
|             | `u_fake_lan`           | Nguyễn Thị Lan    | `WS_GIA_1`              | `role_gia_qt`  | `active`  |
|             | `u_fake_minh`          | Phạm Văn Minh     | `WS_GIA_2`              | `role_gia_qt`  | `active`  |
|             | `u_fake_cho`           | **Người Chờ Mời** | `WS_GIA_2`              | `role_gia_xem` | `pending` |

⚠ **Ba user nằm ở HAI workspace khác nhau**, và `GET /members` chỉ trả người của `WS_DANG_MO`. Nên **test giao diện phải tự đặt fixture bằng `server.use(http.get('/api/v1/members', …))`** thay vì dựa vào ai tình cờ ở trong workspace mặc định — dựa vào đó là buộc bài test vào một chi tiết của fake sẽ đổi.

### Chủ tổ chức KHÔNG có vai trò workspace — `roleId` là `null`

Backend cưỡng chế `memberships` **rỗng** khi `orgRole === 'owner'` (422 nếu không). Nên hàng của chủ tổ chức trong `GET /members` mang `roleId: null` · `role: null`, và menu `⋯` của hàng đó **không có** mục «Đổi vai trò…» — không có gì để đổi.

Đây KHÔNG phải chi tiết cài đặt: `tests/membership-shape-parity.test.ts` có một bài khẳng định _mọi_ `roleId` phải nằm trong `GET /roles`. Trả `''` cho owner làm bài đó đỏ, và trả một `roleId` bịa ra là nói dối rằng owner đang giữ một vai trò họ không giữ.

---

## File Structure

| File                                                  | Trách nhiệm sau khi xong                                             |
| ----------------------------------------------------- | -------------------------------------------------------------------- |
| `src/features/auth/thanhVien.ts`                      | **Seam chính.** `MemberOut` + `taiThanhVien` + 4 hàm ghi + `KHOA_TV` |
| `src/features/auth/components/UserAdmin.tsx`          | Một bảng thành viên. Không tab, không hai nhánh owner/non-owner      |
| `src/features/auth/components/MenuHang.tsx`           | **MỚI** — menu `⋯` dùng chung, đóng khi bấm ngoài / Esc              |
| `src/features/auth/components/MoiThanhVienDialog.tsx` | **MỚI** — hộp thoại mời + panel link kết quả                         |
| `src/features/auth/components/DoiVaiTroDialog.tsx`    | **MỚI** — chọn 1 trong N vai trò, gọi `PATCH /members/{id}`          |
| `src/features/auth/components/UserForm.tsx`           | Thu còn form hồ sơ 2 ô (tên + điện thoại)                            |
| `src/lib/msw/handlers.ts`                             | 4 handler mới; `GET /members` trả thêm 2 trường                      |
| `src/features/auth/nav.ts`                            | Nhãn «Thành viên»                                                    |
| `src/routes/_app/users.tsx`                           | Bỏ `validateSearch`                                                  |
| `tests/thanh-vien.test.tsx`                           | **MỚI** — thay `user-admin.test.tsx` + `members.test.tsx`            |

**Xoá hẳn:** `DanhSachVaiTro.tsx` · `FormVaiTro.tsx` · `TomTatVaiTro.tsx` · `TomTatUser.tsx` · `MemberList.tsx` · `tabUsers.ts` · `tests/vai-tro.test.tsx` · `tests/members.test.tsx` · `tests/user-admin.test.tsx`.

---

## Task 0: Chụp mốc trước khi sửa

- [ ] **Step 1: Chạy toàn bộ suite, GHI LẠI con số**

```bash
node --version
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -20
```

Ghi con số `N passed | M failed | K skipped` vào ghi chú của bạn. CLAUDE.md nói `tests/convos-phien.test.tsx` từng đỏ sẵn — nếu nó đỏ ở đây thì **không phải việc của bạn**, đừng sửa, đừng nhận.

- [ ] **Step 2: Chụp mốc typecheck + format**

```bash
npx tsc -b --force 2>&1 | tail -5
npx prettier --check 'src/**/*.{ts,tsx}' 'tests/**/*.{ts,tsx}' 2>&1 | tail -5
```

Không commit gì ở task này.

---

## Task 1: Seam `/members` — 2 trường mới + 4 hàm ghi

**Files:**

- Modify: `src/features/auth/thanhVien.ts`
- Modify: `src/lib/msw/handlers.ts:857-874` (handler `GET /api/v1/members`)
- Test: `tests/thanh-vien-seam.test.ts` (mới)

**Interfaces:**

- Produces:
  - `interface MemberOut { userId, name, email, roleId: string | null, role: string | null, lifecycle, isOrgOwner }`
  - `type Lifecycle = 'pending' | 'active' | 'suspended'` (nhập lại từ `./api`)
  - `interface KetQuaMoi { email: string; userId: string; invitePath: string | null; daCo: boolean }`
  - `taiThanhVien(): Promise<MemberOut[]>`
  - `moiThanhVien(emails: string[], roleId: string): Promise<{ invites: KetQuaMoi[] }>`
  - `doiVaiTroThanhVien(userId: string, roleId: string): Promise<MemberOut>`
  - `goThanhVien(userId: string): Promise<void>`
  - `moiLaiThanhVien(userId: string): Promise<{ invitePath: string | null }>`
  - `const KHOA_TV = ['members'] as const`

- [ ] **Step 1: Viết test đỏ cho seam**

Tạo `tests/thanh-vien-seam.test.ts`:

```ts
/**
 * Seam `/api/v1/members` — hợp đồng FE ĐỊNH TRƯỚC, backend chưa có 4 đường ghi.
 *
 * Test ở tầng seam (không qua giao diện) vì đây là chỗ hình dạng request được
 * chốt: sai `roleId` thành `role` ở đây là leo thang quyền, và không màn nào
 * bắt được vì cả hai đều là chuỗi.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import {
  doiVaiTroThanhVien,
  goThanhVien,
  moiLaiThanhVien,
  moiThanhVien,
  taiThanhVien,
} from '../src/features/auth/thanhVien'
import { RESET_USERS_GIA, RESET_WS_DANG_MO } from '../src/lib/msw/handlers'
import { server } from '../vitest.setup'

beforeEach(() => {
  RESET_USERS_GIA()
  RESET_WS_DANG_MO()
})

describe('seam /api/v1/members', () => {
  it('① GET mang lifecycle và isOrgOwner', async () => {
    const ds = await taiThanhVien()
    expect(ds.length).toBeGreaterThan(0)
    for (const m of ds) {
      expect(['pending', 'active', 'suspended']).toContain(m.lifecycle)
      expect(typeof m.isOrgOwner).toBe('boolean')
      // Chủ tổ chức KHÔNG có vai trò workspace (backend cưỡng chế `memberships`
      // rỗng, 422 nếu không) — `null`, không phải chuỗi rỗng.
      if (m.isOrgOwner) expect(m.roleId).toBeNull()
      else expect(m.roleId).toBeTruthy()
    }
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
          isOrgOwner: false,
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
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien-seam.test.ts
```

Kỳ vọng: FAIL — `moiThanhVien is not exported`, và bài ① đỏ vì fake chưa có `lifecycle`/`isOrgOwner`.

- [ ] **Step 3: Viết seam**

Thay **toàn bộ** `src/features/auth/thanhVien.ts`:

```ts
/**
 * Seam `/api/v1/members` — thành viên của WORKSPACE đang mở. SEAM CHÍNH của màn
 * `/users` từ 2026-08-09.
 *
 * Khai CỤC BỘ ở `features/auth` (không nhập từ `../api`) vì mọi đường ở đây thuộc
 * phạm vi WORKSPACE, còn `api.ts` gom seam cấp TỔ CHỨC.
 *
 * ⚠ BỐN ĐƯỜNG GHI DƯỚI ĐÂY LÀ HỢP ĐỒNG FE ĐỊNH TRƯỚC — backend CHƯA CÓ (2026-08-09).
 * Cùng lối `POST /agent/try` và `GET/PATCH /linh-vuc` đã đi. Fake ở
 * `lib/msw/handlers.ts`. Đừng lấy hành vi fake làm sự thật về backend.
 *
 * Spec: docs/superpowers/specs/2026-08-09-gon-thanh-vien-va-phan-quyen-design.md §4
 */
import { LoiApi, type Lifecycle } from './api'

/**
 * Hàng của `GET /api/v1/members`.
 *
 * `tests/membership-shape-parity.test.ts` neo cổng hình dạng vào ĐÚNG khai báo
 * này — thêm/bớt trường ở đây là phải sửa fake MSW cho khớp, cùng commit.
 */
export interface MemberOut {
  readonly userId: string
  readonly name: string
  readonly email: string
  /**
   * ID vai trò (`control.roles.id`) — handle ỔN ĐỊNH mà mọi đường ghi neo vào.
   *
   * ĐỐI CHIẾU NGƯỢC TÊN -> id ĐÃ BỊ XOÁ 2026-08-07 — ĐỪNG DỰNG LẠI. Tên vai trò
   * là khoá ĐỔI ĐƯỢC: hai vai trò trùng tên, hoặc một tên vừa dời sang vai trò
   * khác, là đủ để phép dò khớp SANG một tập quyền không ai cấp. Đó là lỗi leo
   * thang quyền xuyên workspace ĐÃ ĐO ĐƯỢC, không phải rủi ro lý thuyết.
   *
   * ⚠ `null` KHI VÀ CHỈ KHI `isOrgOwner` — backend cưỡng chế `memberships` PHẢI
   * rỗng với chủ tổ chức (422 nếu không), nên họ không có vai trò workspace nào
   * để trả. `null` chứ không `''`: chuỗi rỗng đi lọt qua mọi phép kiểm truthy rồi
   * chết ở `<select value="">` (hiện OPTION ĐẦU, tức nói người này giữ một vai
   * trò họ không giữ), và nó làm bài «mọi roleId phải có trong /roles» của
   * `tests/membership-shape-parity.test.ts` đỏ.
   */
  readonly roleId: string | null
  /** TÊN vai trò — để HIỆN, KHÔNG để khớp. `null` cùng lúc với `roleId`. */
  readonly role: string | null
  /**
   * MỚI 2026-08-09. Trạng thái tài khoản cấp TỔ CHỨC (`users.lifecycle`), trả kèm
   * ở đây vì sau khi `/users` đổi trục thì FE KHÔNG còn đọc `GET /api/v1/users`
   * nữa — không có chỗ nào khác biết người này đã đặt mật khẩu chưa.
   */
  readonly lifecycle: Lifecycle
  /**
   * MỚI 2026-08-09. Trường PHÁI SINH ở server (`users.org_role === 'owner'`),
   * không phải cột mới. Cùng lý do với `lifecycle`: FE không còn nguồn nào khác.
   *
   * Dùng để: hiện pill «Chủ tổ chức», và ẨN mục «Gỡ khỏi workspace» (gỡ chủ tổ
   * chức là tự khoá cửa tổ chức).
   */
  readonly isOrgOwner: boolean
}

/** Kết quả mời MỘT email. `invitePath === null` = backend đã gửi email hộ. */
export interface KetQuaMoi {
  readonly email: string
  readonly userId: string
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
  /** `true` = email đã có tài khoản trong tổ chức, chỉ thêm membership. */
  readonly daCo: boolean
}

/** Khoá React Query — MỘT chỗ. Hai khoá cho một endpoint là lỗi đã sửa ở `features/platform`. */
export const KHOA_TV = ['members'] as const

async function goi<T>(duong: string, init?: RequestInit): Promise<T> {
  const res = await fetch(duong, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (res.status === 204) return undefined as T
  const body = (await res.json().catch(() => null)) as {
    error?: { code?: string; message?: string }
  } | null
  if (!res.ok) {
    const e = body?.error
    throw new LoiApi(e?.code ?? 'UNKNOWN', e?.message ?? `${duong} → ${res.status}`)
  }
  return body as T
}

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
): Promise<{ invites: KetQuaMoi[] }> {
  return goi<{ invites: KetQuaMoi[] }>('/api/v1/members', {
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
```

- [ ] **Step 4: Sửa fake MSW — `GET /members` trả 2 trường mới**

Trong `src/lib/msw/handlers.ts`, thay handler `http.get('/api/v1/members', …)` (khoảng dòng 857):

```ts
  http.get('/api/v1/members', () => {
    const hienTai = WS_DANG_MO
    return HttpResponse.json(
      USERS_GIA.flatMap((u) => {
        const m = u.memberships.find((mm) => mm.workspaceId === hienTai && conHieuLuc(mm))
        // Chủ tổ chức KHÔNG có dòng membership (backend cưỡng chế `memberships`
        // rỗng khi `orgRole === 'owner'`) nhưng họ CÓ mặt ở mọi workspace — nên
        // họ phải hiện trong bảng này, với vai trò rỗng.
        if (!m && u.orgRole !== 'owner') return []
        return [
          {
            userId: u.id,
            name: u.name,
            email: u.email,
            // `null` cho owner, KHÔNG `''` — xem docstring `MemberOut.roleId`.
            roleId: m ? m.roleId : null,
            role: m ? tenVaiTroGia(m.roleId) : null,
            lifecycle: u.lifecycle,
            isOrgOwner: u.orgRole === 'owner',
          },
        ]
      }),
    )
  }),
```

- [ ] **Step 5: Thêm 4 handler ghi**

Chèn NGAY SAU handler `GET /api/v1/members` vừa sửa:

```ts
  // ── Hợp đồng FE ĐỊNH TRƯỚC (2026-08-09) — backend CHƯA CÓ 4 đường này ──────
  //
  // Fake CÓ TRẠNG THÁI (ghi vào `USERS_GIA`), hiếm ở tệp này — cần thế vì màn
  // mời rồi đọc lại bảng ngay trong một nhịp. Cùng lối fake của `/linh-vuc`.
  //
  // ⚠ ĐỪNG lấy hành vi ở đây làm sự thật về backend. Tệp này là bản sao viết tay
  // KHÔNG có cổng parity nào canh (xem CLAUDE.md, vụ `soNguoiDungVaiTro`).
  http.post('/api/v1/members', async ({ request }) => {
    const { emails, roleId } = (await request.json()) as { emails: string[]; roleId: string }
    if (!VAI_TRO_GIA.some((r) => r.id === roleId))
      return loiGia(422, 'ROLE_NOT_IN_ORG', 'Vai trò được chọn không thuộc tổ chức của bạn')

    const invites = emails.map((raw) => {
      const email = raw.trim().toLowerCase()
      const co = USERS_GIA.find((u) => u.email === email)
      if (co) {
        const daTrongWs = co.memberships.some((m) => m.workspaceId === WS_DANG_MO)
        if (!daTrongWs)
          co.memberships.push({ workspaceId: WS_DANG_MO, roleId, expiresAt: null } as never)
        return { email, userId: co.id, invitePath: null, daCo: true }
      }
      const moi = {
        id: `u_${email.split('@')[0]?.replace(/[^a-z0-9]+/gi, '_') ?? 'user'}`,
        email,
        name: email.split('@')[0] ?? email,
        phone: null,
        jobTitle: null,
        orgRole: 'member' as const,
        lifecycle: 'pending' as const,
        createdAt: new Date().toISOString(),
        memberships: [{ workspaceId: WS_DANG_MO, roleId, expiresAt: null }],
      }
      USERS_GIA.push(moi as never)
      // Token khác nhau mỗi lần: token cố định làm bài "mời lại sinh link mới" xanh sai.
      return {
        email,
        userId: moi.id,
        invitePath: `/invite/tok_gia_${USERS_GIA.length}_${Date.now()}`,
        daCo: false,
      }
    })
    return HttpResponse.json({ invites }, { status: 201 })
  }),

  http.patch('/api/v1/members/:id', async ({ params, request }) => {
    const { roleId } = (await request.json()) as { roleId: string }
    const u = USERS_GIA.find((x) => x.id === params.id)
    if (!u) return loiGia(404, 'MEMBER_NOT_FOUND', 'Không tìm thấy thành viên này')
    if (!VAI_TRO_GIA.some((r) => r.id === roleId))
      return loiGia(422, 'ROLE_NOT_IN_ORG', 'Vai trò được chọn không thuộc tổ chức của bạn')
    const m = u.memberships.find((mm) => mm.workspaceId === WS_DANG_MO)
    if (!m) return loiGia(404, 'MEMBER_NOT_FOUND', 'Người này không còn ở workspace đang mở')
    m.roleId = roleId
    return HttpResponse.json({
      userId: u.id,
      name: u.name,
      email: u.email,
      roleId,
      role: tenVaiTroGia(roleId),
      lifecycle: u.lifecycle,
      isOrgOwner: u.orgRole === 'owner',
    })
  }),

  http.delete('/api/v1/members/:id', ({ params }) => {
    const u = USERS_GIA.find((x) => x.id === params.id)
    if (!u) return loiGia(404, 'MEMBER_NOT_FOUND', 'Không tìm thấy thành viên này')
    if (u.orgRole === 'owner')
      return loiGia(409, 'CANNOT_REMOVE_OWNER', 'Không gỡ được chủ tổ chức khỏi workspace')
    const i = u.memberships.findIndex((mm) => mm.workspaceId === WS_DANG_MO)
    if (i >= 0) u.memberships.splice(i, 1)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/v1/members/:id/invite', ({ params }) => {
    const u = USERS_GIA.find((x) => x.id === params.id)
    if (!u) return loiGia(404, 'MEMBER_NOT_FOUND', 'Không tìm thấy thành viên này')
    if (u.lifecycle !== 'pending')
      return loiGia(409, 'USER_NOT_PENDING', 'Người này đã đặt mật khẩu — không cần mời lại')
    return HttpResponse.json({ invitePath: `/invite/tok_gia_lai_${Date.now()}` })
  }),
```

- [ ] **Step 6: Chạy test seam — phải XANH**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien-seam.test.ts
```

Kỳ vọng: 6 passed.

- [ ] **Step 7: Cập nhật cổng hình dạng — HAI chỗ**

`tests/membership-shape-parity.test.ts` sẽ đỏ ở cả hai lớp: `tsc` báo `MAU_MEMBER_OUT` thiếu khoá, `vitest` báo bài roleId đỏ vì owner trả `null`. Sửa đúng hai chỗ:

**① Bảng khoá** — thêm 2 dòng:

```ts
/** `GET /members` → mỗi hàng. */
const MAU_MEMBER_OUT: Record<keyof MemberOut, true> = {
  userId: true,
  name: true,
  email: true,
  roleId: true,
  role: true,
  lifecycle: true,
  isOrgOwner: true,
}
```

**② Bài «roleId là id thật»** — bỏ qua hàng chủ tổ chức:

```ts
it('roleId của fake là id thật trong /api/v1/roles, không phải tên rơi qua', async () => {
  // `tenVaiTroGia` rơi về CHÍNH id khi không tra được tên, nên hai trường có thể
  // bằng nhau và cổng khoá ở trên vẫn xanh. Kiểm giá trị mới thấy.
  //
  // BỎ QUA hàng chủ tổ chức (2026-08-09): backend cưỡng chế `memberships` rỗng
  // với owner nên `roleId` của họ là `null` — không phải một id tra được, và
  // cũng không phải một lỗi. Lọc `!== null` chứ KHÔNG lọc theo `isOrgOwner`:
  // vị từ phải nói về thứ đang kiểm (có id hay không), không nói về lý do.
  const roles = (await lay('/api/v1/roles')) as { id: string }[]
  const ds = (await lay('/api/v1/members')) as { roleId: string | null }[]
  const coVaiTro = ds.filter((m) => m.roleId !== null)

  // Đếm TRƯỚC khi so: `[].every(...)` là true, nên thiếu dòng này thì một fake
  // trả toàn `null` làm cổng xanh vĩnh viễn.
  expect(coVaiTro.length).toBeGreaterThan(0)
  for (const m of coVaiTro) expect(roles.map((r) => r.id)).toContain(m.roleId)
})
```

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/membership-shape-parity.test.ts
```

Kỳ vọng: 3 passed. **Đừng nới lỏng phép so tập khoá** — lớp đó tồn tại chính để bắt lệch fake ↔ kiểu.

- [ ] **Step 8: Typecheck + format + commit**

```bash
npx tsc -b --force
npx prettier --write src/features/auth/thanhVien.ts src/lib/msw/handlers.ts tests/thanh-vien-seam.test.ts
git add src/features/auth/thanhVien.ts src/lib/msw/handlers.ts tests/thanh-vien-seam.test.ts tests/membership-shape-parity.test.ts
git commit -m "feat(auth): seam /members mọc lifecycle + isOrgOwner và 4 đường ghi

Hợp đồng FE định trước, backend chưa có — cùng lối /agent/try và /linh-vuc.
DELETE /members/{id} giải lỗ đang có: DELETE /users/{id} chỉ chạy khi user còn
pending, nên trước đây không có đường gỡ người đang hoạt động khỏi workspace.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Bảng thành viên — một bảng, không tab

**Files:**

- Modify: `src/features/auth/components/UserAdmin.tsx` (viết lại phần danh sách)
- Test: `tests/thanh-vien.test.tsx` (mới)

**Interfaces:**

- Consumes: `taiThanhVien`, `MemberOut`, `KHOA_TV` (Task 1)
- Produces: `export function UserAdmin()` — **không còn prop `tab`**

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/thanh-vien.test.tsx`:

```tsx
/**
 * Màn `/users` — bảng thành viên của WORKSPACE đang mở (2026-08-09).
 *
 * Thay `tests/user-admin.test.tsx` (trục tổ chức) và `tests/members.test.tsx`
 * (bảng chỉ-đọc). Cả hai xoá ở Task 6.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import {
  FAKE_SESSION,
  RESET_USERS_GIA,
  RESET_VAI_TRO_GIA,
  RESET_WS_DANG_MO,
} from '../src/lib/msw/handlers'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

function boot(duong = '/users') {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duong] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

/**
 * Hàng của một người — tìm TRONG `<main>`.
 *
 * Khoanh vùng là BẮT BUỘC: menu danh tính ở đáy panel luôn hiện tên người đang
 * đăng nhập, nên `screen.findByText(ten)` trần khớp hai chỗ — và chỗ ngoài bảng
 * không nằm trong `<tr>` nào, nên `.closest('tr')` trả `null` và bài đỏ ở một
 * dòng cách xa nguyên nhân.
 */
async function hangCua(ten: string): Promise<HTMLElement> {
  const main = within(await screen.findByRole('main'))
  const tr = (await main.findByText(ten)).closest('tr')
  expect(tr, `không thấy hàng của ${ten}`).not.toBeNull()
  return tr as HTMLElement
}

/**
 * Fixture bảng thành viên — ĐẶT TƯỜNG MINH, không dựa vào fake mặc định.
 *
 * `USERS_GIA` rải ba người qua HAI workspace và `GET /members` chỉ trả người của
 * `WS_DANG_MO`, nên "ai có mặt trong bảng" là một chi tiết của fake sẽ đổi. Buộc
 * bài test vào đó là buộc nó vào thứ không phải hợp đồng.
 */
const CHU = {
  // CHÍNH MÌNH luôn — hàng này gánh cả hai điều kiện ẩn mục gỡ (là owner, và là
  // người đang đăng nhập). Cần `FAKE_SESSION` để `laChinhMinh` đúng.
  userId: FAKE_SESSION.user.id,
  name: 'Trần Hải Đăng',
  email: 'dang@anphuland.vn',
  roleId: null,
  role: null,
  lifecycle: 'active',
  isOrgOwner: true,
}
const LAN = {
  userId: 'u_fake_lan',
  name: 'Nguyễn Thị Lan',
  email: 'lan@anphuland.vn',
  roleId: 'role_gia_qt',
  role: 'Quản trị',
  lifecycle: 'active',
  isOrgOwner: false,
}
const CHO = {
  userId: 'u_fake_cho',
  name: 'Người Chờ Mời',
  email: 'cho@anphuland.vn',
  roleId: 'role_gia_xem',
  role: 'Người xem',
  lifecycle: 'pending',
  isOrgOwner: false,
}

function datBang(hang: readonly unknown[] = [CHU, LAN, CHO]) {
  server.use(http.get('/api/v1/members', () => HttpResponse.json(hang)))
}

beforeEach(() => {
  RESET_USERS_GIA()
  RESET_VAI_TRO_GIA()
  RESET_WS_DANG_MO()
  datBang()
})

describe('màn /users — bảng thành viên workspace', () => {
  it('① một bảng, KHÔNG có hàng tab', async () => {
    boot()
    await screen.findByRole('main')
    await waitFor(() => expect(screen.getAllByRole('table')).toHaveLength(1))
    // Tab «Vai trò» đã rời màn 2026-08-09 — 13 action ở lại backend.
    expect(screen.queryByRole('tab', { name: 'Vai trò' })).toBeNull()
    expect(screen.queryByRole('tablist')).toBeNull()
  })

  it('② hàng hiện tên · email · vai trò · trạng thái', async () => {
    boot()
    const hang = await hangCua('Nguyễn Thị Lan')
    expect(within(hang).getByText('lan@anphuland.vn')).toBeTruthy()
    expect(within(hang).getByText('Quản trị')).toBeTruthy()
    expect(within(hang).getByText('Đang hoạt động')).toBeTruthy()
  })

  it('②b chủ tổ chức có pill riêng và KHÔNG có vai trò workspace', async () => {
    // Backend cưỡng chế `memberships` rỗng với owner — ô vai trò phải nói «—»,
    // không được để trống (một `<td>` rỗng trông y hệt một `<td>` chưa nạp xong).
    boot()
    const hang = await hangCua('Trần Hải Đăng')
    expect(within(hang).getByText('Chủ tổ chức')).toBeTruthy()
    expect(within(hang).getByText('—')).toBeTruthy()
  })

  it('③ KHÔNG có <select> nào ở chế độ nghỉ — quyền không sửa được bằng một cú lỡ tay', async () => {
    // Luật «xem trước, sửa sau» (CLAUDE.md): một ô chọn QUYỀN luôn sống trong
    // bảng mời gõ nhầm vào dữ liệu đang phát hành. Đổi vai trò đi qua menu ⋯.
    boot()
    const main = within(await screen.findByRole('main'))
    await waitFor(() => expect(main.getAllByRole('row').length).toBeGreaterThan(1))
    // Ô lọc trạng thái là `<select>` HỢP LỆ — nó không ghi gì.
    for (const s of main.queryAllByRole('combobox'))
      expect(s.getAttribute('aria-label')).toMatch(/Lọc/)
  })

  it('④ lọc «Chờ nhận lời mời» chỉ còn hàng pending', async () => {
    boot()
    const main = within(await screen.findByRole('main'))
    await main.findByText('Nguyễn Thị Lan')
    await userEvent.selectOptions(main.getByLabelText(/Lọc theo trạng thái/), 'pending')
    await waitFor(() => expect(main.queryByText('Nguyễn Thị Lan')).toBeNull())
    expect(main.getByText('Người Chờ Mời')).toBeTruthy()
  })

  it('⑤ không tải được thì nói RÕ hai nguyên nhân khác nhau', async () => {
    server.use(
      http.get('/api/v1/members', () =>
        HttpResponse.json({ error: { code: 'FORBIDDEN', message: 'x' } }, { status: 403 }),
      ),
    )
    boot()
    expect(await screen.findByRole('alert')).toHaveTextContent(/không có quyền/i)
  })
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx
```

Kỳ vọng: FAIL ở ① (còn `tablist`) và ③ (còn `<select>` vai trò).

- [ ] **Step 3: Viết lại `UserAdmin.tsx`**

Thay **toàn bộ** file. Đây là bản Task 2 — menu `⋯` và nút Mời là vỏ rỗng, Task 3/4 gắn ruột.

```tsx
/**
 * Màn `/users` — THÀNH VIÊN CỦA WORKSPACE ĐANG MỞ.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 *  TRỤC LÀ WORKSPACE, KHÔNG PHẢI TỔ CHỨC (đổi 2026-08-09)
 * ═══════════════════════════════════════════════════════════════════════════
 * Trước đó bảng liệt kê người dùng TOÀN TỔ CHỨC với một cột động «Vai trò tại
 * <workspace>». Một người mang vai trò khác nhau ở nhiều workspace, nên cột đó
 * hoặc phải là hàng lồng, hoặc phải kèm một dòng giải thích. Theo trục workspace
 * thì MỖI HÀNG ĐÚNG MỘT VAI TRÒ — bảng phẳng, không giải thích. Muốn xem
 * workspace khác thì đổi switcher (lối Linear, Slack).
 *
 * KHÔNG CÒN HAI NHÁNH owner / non-owner. Mọi người thấy CÙNG một bảng; ai được
 * làm gì thì backend nói bằng 403, và các mục ghi trong menu ⋯ ẩn theo `session.
 * orgRole`. ⚠ Ẩn nút là cho ĐỠ RỐI MẮT (PQ_01 §BR-Q03), KHÔNG phải bảo vệ.
 *
 * KHÔNG CÒN TAB «Vai trò». 13 action ở lại backend làm ĐỊNH NGHĨA của 4 vai trò
 * dựng sẵn; đường TỰ TẠO vai trò rời giao diện. Endpoint `POST/PATCH/DELETE
 * /roles` và `GET /actions` vẫn sống ở backend — đây là cắt bề mặt, không xoá
 * năng lực. Spec 2026-08-09 §2.1.
 *
 * KHÔNG CÓ `<h1>` Ở ĐÂY — `components/shell/Topbar.tsx` đã render nó từ nav label.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSession } from '@/lib/session'
import {
  Bang,
  ChanBang,
  DauBang,
  Hang,
  NUT_CHINH,
  NUT_PHU,
  O_LOC,
  PILL,
  TD,
  TD_PHU,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { DauMuc } from '@/components/ui/DauMuc'
import { KhoRong } from '@/components/ui/TrangThai'
import { LoiApi, type Lifecycle } from '../api'
import { MAU_LIFECYCLE, NHAN_LIFECYCLE } from '../nhan'
import { KHOA_TV, taiThanhVien, type MemberOut } from '../thanhVien'

const CAO_BANG = 'max-h-[560px]'

const COT: readonly Cot[] = [
  { nhan: 'Thành viên' },
  { nhan: 'Vai trò' },
  { nhan: 'Trạng thái' },
  { nhan: '', phai: true },
]

const LOC_TRANG_THAI: readonly { readonly value: Lifecycle; readonly nhan: string }[] = [
  { value: 'active', nhan: NHAN_LIFECYCLE.active },
  { value: 'pending', nhan: NHAN_LIFECYCLE.pending },
  { value: 'suspended', nhan: NHAN_LIFECYCLE.suspended },
]

export function UserAdmin() {
  const { session } = useSession()
  const { data, error, isPending } = useQuery({ queryKey: KHOA_TV, queryFn: taiThanhVien })
  const [tim, setTim] = useState('')
  const [locTrangThai, setLocTrangThai] = useState('')

  const tenWorkspace =
    session.workspaces.find((w) => w.id === session.currentWorkspaceId)?.name ?? 'workspace này'

  if (isPending)
    return (
      <div className="px-7 py-6">
        <p className="mb-3.5 text-[14px] text-muted">Đang tải…</p>
        <KhungCho dong={5} />
      </div>
    )

  if (error) {
    // Hai nguyên nhân, hai câu: backend chết mà UI báo "không có quyền" thì
    // người dùng đi xin quyền và không ai báo sự cố.
    const khongCoQuyen = error instanceof LoiApi && error.code === 'FORBIDDEN'
    return (
      <div className="px-7 py-6">
        <p role="alert" className="text-[14px] text-muted">
          {khongCoQuyen
            ? 'Bạn không có quyền xem danh sách thành viên của workspace này.'
            : `Không tải được danh sách thành viên: ${error.message}`}
        </p>
      </div>
    )
  }

  const chuoi = tim.trim().toLowerCase()
  const hien = data.filter(
    (m) =>
      (chuoi === '' ||
        m.name.toLowerCase().includes(chuoi) ||
        m.email.toLowerCase().includes(chuoi)) &&
      (locTrangThai === '' || m.lifecycle === locTrangThai),
  )
  const daLoc = chuoi !== '' || locTrangThai !== ''

  return (
    <div className="px-7 py-6">
      <DauMuc
        tieuDe="Thành viên"
        phai={
          <span className="text-[13.5px] text-muted">
            Workspace <span className="font-semibold text-fg">{tenWorkspace}</span>
          </span>
        }
      />

      <TheBang cao={CAO_BANG}>
        <ThanhCong>
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5">
            <input
              type="search"
              aria-label="Tìm theo họ tên hoặc địa chỉ đăng nhập"
              placeholder="Tìm theo tên hoặc email…"
              value={tim}
              onChange={(e) => setTim(e.target.value)}
              className={`${O_LOC} min-w-[190px] max-w-[300px] flex-1`}
            />
            <select
              aria-label="Lọc theo trạng thái"
              value={locTrangThai}
              onChange={(e) => setLocTrangThai(e.target.value)}
              className={`${O_LOC} text-muted`}
            >
              <option value="">Tất cả</option>
              {LOC_TRANG_THAI.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.nhan}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className={`${NUT_CHINH} flex-none`}>
            Mời thành viên
          </button>
        </ThanhCong>

        {/* ⚠ BA NHÁNH BỌC ĐÚNG VÙNG BẢNG, KHÔNG `return` sớm cả component — nếu
            không, gõ vào ô tìm sẽ unmount cả dải lọc và ô mất focus giữa lúc
            đang gõ. Cùng cái bẫy `DuAnList` đã ghi lại. */}
        <VungCuon>
          {data.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe="Workspace này chưa có thành viên nào."
                huongDan="Mời người đầu tiên để họ vào được workspace."
              />
            </div>
          ) : hien.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe="Không có thành viên nào khớp bộ lọc."
                huongDan="Xoá bộ lọc để xem lại toàn bộ workspace."
                viec={
                  <button
                    type="button"
                    className={NUT_PHU}
                    onClick={() => {
                      setTim('')
                      setLocTrangThai('')
                    }}
                  >
                    Xoá bộ lọc
                  </button>
                }
              />
            </div>
          ) : (
            <Bang>
              <DauBang cot={COT} />
              <tbody>
                {hien.map((m) => (
                  <HangThanhVien key={m.userId} m={m} />
                ))}
              </tbody>
            </Bang>
          )}
        </VungCuon>

        {daLoc && hien.length > 0 && (
          <ChanBang>
            <p className="text-[12.5px] text-muted-2">
              Hiện {hien.length} / {data.length} thành viên
            </p>
          </ChanBang>
        )}
      </TheBang>
    </div>
  )
}

/** Chữ cái đầu của tên — Trần Hải Đăng → TĐ. Chỉ để trang trí ô định danh. */
function chuCaiDau(ten: string): string {
  const tu = ten.trim().split(/\s+/).filter(Boolean)
  if (tu.length === 0) return '?'
  const dau = tu[0]?.[0] ?? ''
  const cuoi = tu.length > 1 ? (tu[tu.length - 1]?.[0] ?? '') : ''
  return (dau + cuoi).toUpperCase()
}

function HangThanhVien({ m }: { m: MemberOut }) {
  const { session } = useSession()
  const laChinhMinh = m.userId === session.user.id

  return (
    <Hang>
      <td className={TD}>
        <div className="flex items-start gap-2.5">
          {/* `aria-hidden`: avatar chữ KHÔNG mang thông tin nào mà cái tên ngay
              bên cạnh chưa nói. Để trình đọc màn hình đọc TĐ rồi Trần Hải Đăng
              là đọc một thứ hai lần. */}
          <span
            aria-hidden="true"
            className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full bg-acs text-[12px] font-semibold text-ac"
          >
            {chuCaiDau(m.name)}
          </span>
          <div className="min-w-0">
            <div className="font-semibold text-fg">
              {m.name}
              {laChinhMinh && (
                <span className="ml-1.5 text-[12px] font-normal text-muted">(bạn)</span>
              )}
            </div>
            <div className="truncate font-mono text-[12px] text-muted-2">{m.email}</div>
          </div>
        </div>
      </td>
      <td className={TD_PHU}>
        {/* Chủ tổ chức không có vai trò workspace (`memberships` rỗng, backend
            cưỡng chế). «—» chứ không để trống: một `<td>` rỗng trông y hệt một
            `<td>` chưa nạp xong — cùng lý lẽ chữ «Chưa đặt» của `GiaTri`. */}
        {m.role === null ? (
          <span className="text-muted-3">—</span>
        ) : (
          <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg`}>{m.role}</span>
        )}
      </td>
      <td className={TD}>
        <span className={`${PILL} ${MAU_LIFECYCLE[m.lifecycle]}`}>
          {NHAN_LIFECYCLE[m.lifecycle]}
        </span>
        {/* Chủ tổ chức lấy cặp accent — đây là quyền duy nhất tạo được workspace
            mới và sở hữu gói cước, nên nó phải đọc ra khác ngay từ cái nhìn đầu. */}
        {m.isOrgOwner && <span className={`${PILL} ml-1.5 bg-acs text-ac`}>Chủ tổ chức</span>}
      </td>
      <td className={`${TD} text-right`} />
    </Hang>
  )
}

/**
 * Khung chờ — nhịp của bảng thật, không phải chữ Đang tải… đứng một mình.
 *
 * `aria-hidden` + `role="presentation"`: đây là hình, không phải nội dung.
 */
function KhungCho({ dong }: { dong: number }) {
  return (
    <div
      aria-hidden="true"
      className="space-y-2.5 rounded-xl border border-border bg-surface p-4"
      role="presentation"
    >
      {Array.from({ length: dong }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-8 w-8 flex-none rounded-full bg-border-soft" />
          <div className="h-3 flex-1 rounded bg-border-soft" />
          <div className="h-3 w-24 rounded bg-border-soft" />
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Sửa route cho khớp (bỏ prop `tab`)**

`src/routes/_app/users.tsx` — thay toàn bộ:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { UserAdmin } from '@/features/auth/components/UserAdmin'

// Màn này KHÔNG còn tab (2026-08-09), nên không còn `validateSearch`. `?tab=
// vai-tro` của link cũ rơi vào search param không khai báo — TanStack bỏ qua,
// màn vẫn mở đúng. Đó là hành vi mong muốn: link cũ không được vỡ.
export const Route = createFileRoute('/_app/users')({
  component: UserAdmin,
})
```

- [ ] **Step 5: Chạy test — ① ② ③ ④ ⑤ phải XANH**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx
```

Kỳ vọng: 5 passed.

- [ ] **Step 6: Xoá NGAY ba tệp mà Task này làm chết**

⚠ **Không để tới Task 6.** `UserAdmin` mất prop `tab` và đổi hẳn hình dạng bảng, nên ba tệp dưới đây đỏ **ngay từ task này** — để chúng nằm đỏ suốt Task 3·4·5 thì mọi lần chạy suite đều lẫn tiếng ồn, và người review không phân biệt được đỏ-của-mình với đỏ-đang-nợ.

```bash
git rm src/features/auth/components/MemberList.tsx \
       src/features/auth/tabUsers.ts \
       tests/user-admin.test.tsx \
       tests/members.test.tsx
```

`MemberList.tsx` xoá chứ không gộp: nó tồn tại cho **nhánh không-phải-chủ-tổ-chức** của màn cũ, và nhánh đó không còn khi mọi người thấy cùng một bảng. Phép kiểm còn giá trị của `members.test.tsx` (đọc được danh sách thành viên) đã nằm trong bài ② của `thanh-vien.test.tsx`.

Nếu `tsc` còn báo tệp nào khác chết theo (ví dụ `TomTatUser.tsx` mồ côi), xoá luôn tại đây — đừng để nợ sang task sau.

```bash
npx tsc -b --force
```

Kỳ vọng: sạch.

- [ ] **Step 6b: Chạy TOÀN BỘ suite — so với mốc Task 0**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -6
```

Mốc Task 0 là **347 pass · 0 fail**. Sau khi xoá 2 tệp test cũ và thêm `thanh-vien.test.tsx` + `thanh-vien-seam.test.ts`, con số `pass` đổi — nhưng **`fail` phải vẫn là 0**. Một bài đỏ ở đây là của bạn.

- [ ] **Step 7: Commit**

```bash
npx prettier --write src/features/auth/components/UserAdmin.tsx src/routes/_app/users.tsx tests/thanh-vien.test.tsx
git add src/ tests/ docs/
git commit -m "feat(auth): /users thành MỘT bảng thành viên của workspace đang mở

Trục đổi từ tổ chức sang workspace ⇒ mỗi hàng đúng một vai trò, bảng phẳng,
không cột động và không dòng giải thích. Bỏ hàng tab và bỏ hai nhánh
owner/non-owner — mọi người thấy cùng một bảng.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Menu `⋯` — đổi vai trò · gỡ khỏi workspace · mời lại

**Files:**

- Create: `src/features/auth/components/MenuHang.tsx`
- Create: `src/features/auth/components/DoiVaiTroDialog.tsx`
- Modify: `src/features/auth/components/UserAdmin.tsx` (`HangThanhVien`)
- Test: `tests/thanh-vien.test.tsx` (thêm bài)

**Interfaces:**

- Consumes: `doiVaiTroThanhVien`, `goThanhVien`, `moiLaiThanhVien`, `KHOA_TV`, `MemberOut` (Task 1)
- Produces:
  - `MenuHang({ nhan, muc }: { nhan: string; muc: readonly MucMenu[] })`
  - `interface MucMenu { key: string; nhan: string; onChon: () => void; phaHuy?: boolean }`
  - `DoiVaiTroDialog({ m, onDong }: { m: MemberOut; onDong: () => void })`

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/thanh-vien.test.tsx`, trong cùng `describe`:

```tsx
it('⑥ đổi vai trò qua ⋯ gửi PATCH mang roleId, KHÔNG mang tên', async () => {
  // `role_gia_xem` -> `role_gia_qt`. Tên «Người xem»/«Quản trị» là của
  // `VAI_TRO_GIA` — fake KHÔNG có vai trò nào tên «CSKH» hay «Biên tập».
  let than: unknown = null
  let duong = ''
  server.use(
    http.patch('/api/v1/members/:id', async ({ request, params }) => {
      than = await request.json()
      duong = String(params.id)
      return HttpResponse.json({ ...CHO, roleId: 'role_gia_qt', role: 'Quản trị' })
    }),
  )
  boot()
  const hang = await hangCua('Người Chờ Mời')
  await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Đổi vai trò…' }))
  const hop = await screen.findByRole('dialog')
  await userEvent.click(within(hop).getByRole('radio', { name: 'Quản trị' }))
  await userEvent.click(within(hop).getByRole('button', { name: 'Lưu' }))
  await waitFor(() => expect(than).toEqual({ roleId: 'role_gia_qt' }))
  expect(duong).toBe('u_fake_cho')
})

it('⑦ hàng chủ tổ chức KHÔNG có mục gỡ, và KHÔNG có mục đổi vai trò', async () => {
  // Gỡ chủ tổ chức là tự khoá cửa tổ chức; hàng này còn là CHÍNH MÌNH, tức tự
  // đá mình ra khỏi màn đang đứng. Backend chặn cả hai bằng 409 — đây là phòng
  // tuyến một, cho ĐỠ RỐI MẮT (PQ_01 §BR-Q03).
  //
  // Và không có gì để đổi: owner không mang vai trò workspace nào.
  boot()
  const hang = await hangCua('Trần Hải Đăng')
  await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
  expect(screen.queryByRole('menuitem', { name: 'Gỡ khỏi workspace' })).toBeNull()
  expect(screen.queryByRole('menuitem', { name: 'Đổi vai trò…' })).toBeNull()
  // Vẫn còn ÍT NHẤT một mục — menu rỗng thì `MenuHang` không render nút nào và
  // bài này xanh vì lý do sai.
  expect(screen.getAllByRole('menuitem').length).toBeGreaterThan(0)
})

it('⑧ gỡ một thành viên thường gọi DELETE /members/{id}', async () => {
  let daGoi = ''
  server.use(
    http.delete('/api/v1/members/:id', ({ params }) => {
      daGoi = String(params.id)
      return new HttpResponse(null, { status: 204 })
    }),
  )
  boot()
  const hang = await hangCua('Người Chờ Mời')
  await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Gỡ khỏi workspace' }))
  const hop = await screen.findByRole('dialog')
  await userEvent.click(within(hop).getByRole('button', { name: 'Gỡ' }))
  await waitFor(() => expect(daGoi).toBe('u_fake_cho'))
})

it('⑨ mục mời lại CHỈ có trên hàng pending', async () => {
  boot()
  const hangChay = await hangCua('Nguyễn Thị Lan') // active
  await userEvent.click(within(hangChay).getByRole('button', { name: /Thao tác/ }))
  expect(screen.queryByRole('menuitem', { name: 'Gửi lại lời mời' })).toBeNull()
  await userEvent.keyboard('{Escape}')

  const hangCho = await hangCua('Người Chờ Mời') // pending
  await userEvent.click(within(hangCho).getByRole('button', { name: /Thao tác/ }))
  expect(await screen.findByRole('menuitem', { name: 'Gửi lại lời mời' })).toBeTruthy()
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx
```

Kỳ vọng: ⑥⑦⑧⑨ FAIL — không tìm thấy nút `Thao tác`.

- [ ] **Step 3: Viết `MenuHang.tsx`**

```tsx
/**
 * Menu `⋯` cuối hàng bảng — MỘT chỗ cho mọi bảng cần nó.
 *
 * VÌ SAO MENU CHỨ KHÔNG PHẢI NÚT RỜI TRONG HÀNG: mục nặng nhất ở đây là ĐỔI VAI
 * TRÒ. Luật «xem trước, sửa sau» (CLAUDE.md) nói *form mở sẵn nói «hãy điền»
 * trong khi việc thật là «hãy đọc», và nó mời gõ nhầm vào dữ liệu đang phát
 * hành* — một `<select>` quyền hạn luôn sống trong bảng là đúng ca đó. Bản
 * trước 2026-08-09 có `<select>` như thế; nay nó ở sau hai cú bấm. Giá: một cú
 * bấm nữa cho một việc HIẾM, đổi lấy an toàn cho một bảng ĐỌC THƯỜNG XUYÊN.
 *
 * `role="menu"` + `role="menuitem"`, KHÔNG phải `<ul>/<li>` trần: trình đọc màn
 * hình cần biết đây là danh sách hành động chứ không phải danh sách nội dung.
 */
import { useEffect, useRef, useState } from 'react'

export interface MucMenu {
  readonly key: string
  readonly nhan: string
  readonly onChon: () => void
  /** Tô sắc cảnh báo — dành cho mục không hoàn tác được. */
  readonly phaHuy?: boolean
}

export function MenuHang({ nhan, muc }: { nhan: string; muc: readonly MucMenu[] }) {
  const [mo, setMo] = useState(false)
  const boc = useRef<HTMLDivElement>(null)

  // Bấm RA NGOÀI và Esc đều đóng. Thiếu vế đầu thì mở hai menu cùng lúc trên hai
  // hàng, và người dùng không biết mục mình sắp bấm thuộc về ai.
  useEffect(() => {
    if (!mo) return
    function ngoai(e: MouseEvent) {
      if (!boc.current?.contains(e.target as Node)) setMo(false)
    }
    function phim(e: KeyboardEvent) {
      if (e.key === 'Escape') setMo(false)
    }
    document.addEventListener('mousedown', ngoai)
    document.addEventListener('keydown', phim)
    return () => {
      document.removeEventListener('mousedown', ngoai)
      document.removeEventListener('keydown', phim)
    }
  }, [mo])

  if (muc.length === 0) return null

  return (
    <div ref={boc} className="relative inline-block text-left">
      <button
        type="button"
        aria-label={`Thao tác với ${nhan}`}
        aria-haspopup="menu"
        aria-expanded={mo}
        onClick={() => setMo((v) => !v)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-sm text-muted hover:bg-fill"
      >
        <span aria-hidden="true">⋯</span>
      </button>
      {mo && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1 min-w-[196px] rounded-lg border border-border bg-surface py-1 shadow-lg"
        >
          {muc.map((m) => (
            <button
              key={m.key}
              type="button"
              role="menuitem"
              onClick={() => {
                setMo(false)
                m.onChon()
              }}
              className={`block w-full px-3.5 py-2 text-left text-[13.5px] hover:bg-fill ${
                m.phaHuy ? 'text-badge-alert-fg' : 'text-fg'
              }`}
            >
              {m.nhan}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Viết `DoiVaiTroDialog.tsx`**

```tsx
/**
 * Hộp thoại đổi vai trò của MỘT thành viên tại workspace đang mở.
 *
 * Số đo và class lấy từ `features/platform/components/TaoKhoaDialog.tsx` — các
 * hộp thoại của portal phải trông như nhau, và đó là lý do file kia được CHÉP
 * chứ không được "tham khảo".
 *
 * RADIO chứ không `<select>`: bốn vai trò là bốn NGHỀ song song (PQ_01 §2.2),
 * không phải bốn bậc — một danh sách phơi cả bốn ra cùng lúc nói đúng điều đó,
 * còn `<select>` giấu ba cái sau một cái và gợi ý thứ bậc.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { khoaVaiTro, layDanhSachVaiTro, LoiApi } from '../api'
import { doiVaiTroThanhVien, KHOA_TV, type MemberOut } from '../thanhVien'

/**
 * `m.roleId` PHẢI khác `null` ở đây — chỗ gọi (`HangThanhVien`) đã lọc, vì chủ
 * tổ chức không có vai trò workspace nào để đổi. Nhận `MemberOut` nguyên vẹn cho
 * gọn, và ép kiểu một lần ở `useState` thay vì rải `?? ''` khắp component: một
 * chuỗi rỗng lọt vào `PATCH` là 422 `ROLE_NOT_IN_ORG` với thông điệp khó hiểu.
 */
export function DoiVaiTroDialog({ m, onDong }: { m: MemberOut; onDong: () => void }) {
  const queryClient = useQueryClient()
  const [chon, setChon] = useState(m.roleId ?? '')
  const { data: vaiTro } = useQuery({ queryKey: khoaVaiTro.tatCa, queryFn: layDanhSachVaiTro })

  useEffect(() => {
    function phim(e: KeyboardEvent) {
      if (e.key === 'Escape') onDong()
    }
    document.addEventListener('keydown', phim)
    return () => document.removeEventListener('keydown', phim)
  }, [onDong])

  const luu = useMutation({
    mutationFn: () => doiVaiTroThanhVien(m.userId, chon),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KHOA_TV })
      onDong()
    },
  })

  return (
    <div className="fixed inset-0 z-70 grid place-items-center px-4">
      <button
        type="button"
        aria-label="Đóng"
        onClick={onDong}
        className="fixed inset-0 cursor-default bg-fg/25"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Đổi vai trò của ${m.name}`}
        className="relative w-full max-w-[420px] rounded-lg border border-border bg-surface p-5"
      >
        <h2 className="text-[15px] font-semibold text-fg">Đổi vai trò</h2>
        <p className="mt-1 text-[13.5px] text-muted">{m.name} — chỉ đổi ở workspace đang mở.</p>

        <div className="mt-4 space-y-1.5" role="radiogroup" aria-label="Vai trò">
          {(vaiTro ?? []).map((v) => (
            <label
              key={v.id}
              className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 hover:bg-fill"
            >
              <input
                type="radio"
                name="vai-tro"
                value={v.id}
                checked={chon === v.id}
                onChange={() => setChon(v.id)}
              />
              <span className="text-[14px] text-fg">{v.name}</span>
            </label>
          ))}
        </div>

        {luu.error && (
          <p role="alert" className="mt-3 text-[13px] text-badge-alert-fg">
            {luu.error instanceof LoiApi ? luu.error.message : 'Không lưu được vai trò'}
          </p>
        )}

        <div className={`${HANG_NUT} mt-5`}>
          <button type="button" className={NUT_PHU} onClick={onDong}>
            Huỷ
          </button>
          <button
            type="button"
            className={NUT_CHINH}
            disabled={luu.isPending || chon === m.roleId}
            onClick={() => luu.mutate()}
          >
            Lưu
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Gắn menu vào `HangThanhVien`**

Trong `UserAdmin.tsx`, thêm import và thay `HangThanhVien`:

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MenuHang, type MucMenu } from './MenuHang'
import { DoiVaiTroDialog } from './DoiVaiTroDialog'
import { goThanhVien, moiLaiThanhVien, urlMoi } from '../thanhVien'
```

```tsx
function HangThanhVien({ m }: { m: MemberOut }) {
  const { session } = useSession()
  const queryClient = useQueryClient()
  const laChinhMinh = m.userId === session.user.id
  const [hop, setHop] = useState<'doi-vai-tro' | 'go' | null>(null)
  const [linkMoi, setLinkMoi] = useState<string | null>(null)

  const go = useMutation({
    mutationFn: () => goThanhVien(m.userId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KHOA_TV })
      setHop(null)
    },
  })
  const moiLai = useMutation({
    mutationFn: () => moiLaiThanhVien(m.userId),
    onSuccess: (ra) => setLinkMoi(urlMoi(ra.invitePath)),
  })

  // Ẩn mục là cho ĐỠ RỐI MẮT (PQ_01 §BR-Q03), KHÔNG phải bảo vệ — backend chặn
  // cả hai ca này bằng 409 (`CANNOT_REMOVE_OWNER`, `CANNOT_REMOVE_SELF`).
  const goDuoc = !m.isOrgOwner && !laChinhMinh
  const muc: MucMenu[] = [
    // Chủ tổ chức KHÔNG có vai trò workspace để đổi — `roleId` là `null`.
    // Rẽ theo `roleId`, KHÔNG theo `isOrgOwner`: vị từ phải nói về thứ đang
    // quyết định (có vai trò hay không), không nói về lý do.
    ...(m.roleId !== null
      ? [{ key: 'vai-tro', nhan: 'Đổi vai trò…', onChon: () => setHop('doi-vai-tro') }]
      : []),
    ...(m.lifecycle === 'pending'
      ? [{ key: 'moi-lai', nhan: 'Gửi lại lời mời', onChon: () => moiLai.mutate() }]
      : []),
    ...(goDuoc
      ? [{ key: 'go', nhan: 'Gỡ khỏi workspace', onChon: () => setHop('go'), phaHuy: true }]
      : []),
  ]

  return (
    <>
      <Hang>
        {/* … ba <td> đầu GIỮ NGUYÊN như Task 2 … */}
        <td className={`${TD} text-right`}>
          <MenuHang nhan={m.name} muc={muc} />
          {linkMoi && (
            <span className="mt-1 block break-all text-[11.5px] text-muted-2">{linkMoi}</span>
          )}
          {(go.error ?? moiLai.error) && (
            <span role="alert" className="mt-1 block text-[12px] text-badge-alert-fg">
              {(go.error ?? moiLai.error)?.message}
            </span>
          )}
        </td>
      </Hang>
      {hop === 'doi-vai-tro' && <DoiVaiTroDialog m={m} onDong={() => setHop(null)} />}
      {hop === 'go' && (
        <XacNhanGo
          ten={m.name}
          dangGui={go.isPending}
          onDong={() => setHop(null)}
          onGo={() => go.mutate()}
        />
      )}
    </>
  )
}

/**
 * Xác nhận gỡ — hộp thoại thật, KHÔNG `window.confirm`.
 *
 * Gỡ một người đang hoạt động là hành động không hoàn tác được và câu hỏi phải
 * nói rõ nó KHÔNG xoá tài khoản. `window.confirm` không cho định dạng, không
 * cho `role="dialog"`, và jsdom không render nó.
 */
function XacNhanGo({
  ten,
  dangGui,
  onDong,
  onGo,
}: {
  ten: string
  dangGui: boolean
  onDong: () => void
  onGo: () => void
}) {
  return (
    <div className="fixed inset-0 z-70 grid place-items-center px-4">
      <button
        type="button"
        aria-label="Đóng"
        onClick={onDong}
        className="fixed inset-0 cursor-default bg-fg/25"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Gỡ ${ten} khỏi workspace`}
        className="relative w-full max-w-[420px] rounded-lg border border-border bg-surface p-5"
      >
        <h2 className="text-[15px] font-semibold text-fg">Gỡ khỏi workspace?</h2>
        <p className="mt-1.5 text-[13.5px] leading-[1.55] text-muted">
          <span className="font-semibold text-fg">{ten}</span> mất quyền ở workspace này ngay lập
          tức. Tài khoản của họ trong tổ chức vẫn còn, và quyền ở workspace khác không đổi.
        </p>
        <div className={`${HANG_NUT} mt-5`}>
          <button type="button" className={NUT_PHU} onClick={onDong}>
            Huỷ
          </button>
          <button type="button" className={NUT_CHINH} disabled={dangGui} onClick={onGo}>
            Gỡ
          </button>
        </div>
      </div>
    </div>
  )
}
```

Thêm `HANG_NUT` vào import từ `@/components/ui/Bang`.

- [ ] **Step 6: Chạy test — ⑥⑦⑧⑨ phải XANH**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx
```

Kỳ vọng: 9 passed.

- [ ] **Step 7: Typecheck + format + commit**

```bash
npx tsc -b --force
npx prettier --write src/features/auth/components/*.tsx tests/thanh-vien.test.tsx
git add src/ tests/ docs/
git commit -m "feat(auth): menu ⋯ — đổi vai trò · gỡ khỏi workspace · gửi lại lời mời

Vai trò rời <select> sống-trong-hàng, vào sau hai cú bấm: luật xem-trước-sửa-sau
nói một ô chọn QUYỀN luôn mở mời gõ nhầm vào dữ liệu đang phát hành. Mục gỡ ẩn
trên hàng chủ tổ chức và hàng chính mình (đỡ rối mắt; backend chặn bằng 409).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Hộp thoại mời — nhiều email, một vai trò, một bước

**Files:**

- Create: `src/features/auth/components/MoiThanhVienDialog.tsx`
- Modify: `src/features/auth/components/UserAdmin.tsx` (nút «Mời thành viên»)
- Test: `tests/thanh-vien.test.tsx`

**Interfaces:**

- Consumes: `moiThanhVien`, `KetQuaMoi`, `urlMoi`, `KHOA_TV` (Task 1)
- Produces: `MoiThanhVienDialog({ onDong }: { onDong: () => void })`

- [ ] **Step 1: Viết test đỏ**

```tsx
it('⑩ mời 2 email cùng lúc gửi ĐÚNG một request {emails, roleId}', async () => {
  const than: unknown[] = []
  server.use(
    http.post('/api/v1/members', async ({ request }) => {
      than.push(await request.json())
      return HttpResponse.json(
        {
          invites: [
            {
              email: 'lan@anphuland.vn',
              userId: 'u_lan',
              invitePath: '/invite/tok_a',
              daCo: false,
            },
            { email: 'minh@anphuland.vn', userId: 'u_minh', invitePath: null, daCo: true },
          ],
        },
        { status: 201 },
      )
    }),
  )
  boot()
  await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
  const hop = await screen.findByRole('dialog')
  const o = within(hop).getByLabelText(/Email/)
  await userEvent.type(o, 'lan@anphuland.vn{enter}minh@anphuland.vn{enter}')
  await userEvent.click(within(hop).getByRole('radio', { name: 'Người xem' }))
  await userEvent.click(within(hop).getByRole('button', { name: 'Gửi lời mời' }))

  await waitFor(() => expect(than).toHaveLength(1))
  // MỘT request cho cả lô, không phải một request mỗi email — đó là điểm của
  // «mời một bước». `toHaveLength(1)` là phần canh việc đó.
  expect(than[0]).toEqual({
    emails: ['lan@anphuland.vn', 'minh@anphuland.vn'],
    roleId: 'role_gia_xem',
  })
})

it('⑪ panel kết quả hiện link cho người MỚI, và nói rõ người đã có', async () => {
  server.use(
    http.post('/api/v1/members', () =>
      HttpResponse.json(
        {
          invites: [
            {
              email: 'lan@anphuland.vn',
              userId: 'u_lan',
              invitePath: '/invite/tok_a',
              daCo: false,
            },
            { email: 'minh@anphuland.vn', userId: 'u_minh', invitePath: null, daCo: true },
          ],
        },
        { status: 201 },
      ),
    ),
  )
  boot()
  await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
  const hop = await screen.findByRole('dialog')
  await userEvent.type(
    within(hop).getByLabelText(/Email/),
    'lan@anphuland.vn{enter}minh@anphuland.vn{enter}',
  )
  await userEvent.click(within(hop).getByRole('radio', { name: 'Người xem' }))
  await userEvent.click(within(hop).getByRole('button', { name: 'Gửi lời mời' }))

  // Người MỚI: có link để copy — backend chưa có mailer.
  expect(await within(hop).findByDisplayValue(/\/invite\/tok_a$/)).toBeTruthy()
  // Người ĐÃ CÓ tài khoản: không sinh lời mời, và phải nói ra.
  expect(within(hop).getByText(/minh@anphuland\.vn/)).toBeTruthy()
  expect(within(hop).getByText(/đã có tài khoản/i)).toBeTruthy()
})

it('⑫ email trùng bị bỏ, và không gửi được khi chưa có email nào', async () => {
  boot()
  await userEvent.click(await screen.findByRole('button', { name: 'Mời thành viên' }))
  const hop = await screen.findByRole('dialog')
  expect(within(hop).getByRole('button', { name: 'Gửi lời mời' })).toBeDisabled()
  await userEvent.type(within(hop).getByLabelText(/Email/), 'a@x.vn{enter}a@x.vn{enter}')
  expect(within(hop).getAllByRole('button', { name: /Bỏ a@x\.vn/ })).toHaveLength(1)
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx -t "⑩"
```

Kỳ vọng: FAIL — không mở được hộp thoại.

- [ ] **Step 3: Viết `MoiThanhVienDialog.tsx`**

```tsx
/**
 * Hộp thoại mời — NHIỀU email, MỘT vai trò, MỘT bước.
 *
 * Lối của ElevenLabs · Linear · Vercel: vai trò chọn NGAY trong bước mời, nên
 * quyền được khoanh từ cú bấm đầu tiên. Trước 2026-08-09 mình là hai bước — tạo
 * user cấp tổ chức, rồi gán membership ở một form khác.
 *
 * MỘT vai trò cho cả lô là có chủ ý: muốn hai vai trò thì mời hai lượt. Cho mỗi
 * email một vai trò biến hộp thoại thành một bảng con — đúng thứ vừa bị cắt.
 *
 * ⚠ PANEL KẾT QUẢ LÀ CHỖ DUY NHẤT LỆCH VỚI BA HỆ KIA. Backend không có bộ gửi
 * mail (`grep -rEi 'smtp|sendgrid|mailgun|send_email' src` → rỗng, 2026-08-09),
 * nên admin phải tự copy link đi gửi. Ngày có mailer, `invitePath` về `null` và
 * CHỈ panel này đổi thành một dòng «Đã gửi email tới N người» — không đụng gì
 * khác trong màn. Đừng để logic mailer rò ra ngoài file này.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { khoaVaiTro, layDanhSachVaiTro, LoiApi } from '../api'
import { KHOA_TV, moiThanhVien, urlMoi, type KetQuaMoi } from '../thanhVien'

/** Tách theo dấu phẩy, chấm phẩy, khoảng trắng, xuống dòng — dán từ Excel vẫn chạy. */
function tachEmail(tho: string): string[] {
  return tho
    .split(/[\s,;]+/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
}

export function MoiThanhVienDialog({ onDong }: { onDong: () => void }) {
  const queryClient = useQueryClient()
  const [emails, setEmails] = useState<string[]>([])
  const [dangGo, setDangGo] = useState('')
  const [roleId, setRoleId] = useState('')
  const [ketQua, setKetQua] = useState<KetQuaMoi[] | null>(null)
  const { data: vaiTro } = useQuery({ queryKey: khoaVaiTro.tatCa, queryFn: layDanhSachVaiTro })

  useEffect(() => {
    function phim(e: KeyboardEvent) {
      if (e.key === 'Escape') onDong()
    }
    document.addEventListener('keydown', phim)
    return () => document.removeEventListener('keydown', phim)
  }, [onDong])

  function nhan(tho: string) {
    // `Set` chứ không `includes`: dán 40 email từ Excel thì phép lọc O(n²) đủ
    // chậm để thấy được, và trùng lặp là chuyện thường khi dán.
    const co = new Set(emails)
    const them = tachEmail(tho).filter((e) => !co.has(e))
    if (them.length > 0) setEmails([...emails, ...them])
    setDangGo('')
  }

  const gui = useMutation({
    mutationFn: () => moiThanhVien(emails, roleId),
    onSuccess: (ra) => {
      setKetQua(ra.invites)
      void queryClient.invalidateQueries({ queryKey: KHOA_TV })
    },
  })

  return (
    <div className="fixed inset-0 z-70 grid place-items-center px-4">
      <button
        type="button"
        aria-label="Đóng"
        onClick={onDong}
        className="fixed inset-0 cursor-default bg-fg/25"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Mời thành viên"
        className="relative w-full max-w-[520px] rounded-lg border border-border bg-surface p-5"
      >
        {ketQua ? (
          <PanelKetQua ketQua={ketQua} onDong={onDong} />
        ) : (
          <>
            <h2 className="text-[15px] font-semibold text-fg">Mời thành viên</h2>

            <label htmlFor="moi-email" className="mt-4 block text-[13.5px] font-medium text-fg">
              Email
            </label>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded-md border border-border-strong px-2 py-1.5 focus-within:border-ac">
              {emails.map((e) => (
                <span
                  key={e}
                  className="inline-flex items-center gap-1 rounded-sm bg-fill px-2 py-1 text-[12.5px] text-fg"
                >
                  {e}
                  <button
                    type="button"
                    aria-label={`Bỏ ${e}`}
                    onClick={() => setEmails(emails.filter((x) => x !== e))}
                    className="text-muted"
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                id="moi-email"
                type="email"
                value={dangGo}
                placeholder={emails.length === 0 ? 'lan@anphuland.vn' : ''}
                onChange={(e) => setDangGo(e.target.value)}
                // Enter · phẩy · Tab đều chốt một chip; `blur` chốt nốt cái đang
                // gõ dở. Thiếu vế `blur` thì bấm thẳng «Gửi» sẽ bỏ rơi email cuối
                // mà không báo gì.
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ',' || e.key === 'Tab') {
                    if (dangGo.trim() === '') return
                    e.preventDefault()
                    nhan(dangGo)
                  }
                }}
                onBlur={() => dangGo.trim() !== '' && nhan(dangGo)}
                onPaste={(e) => {
                  e.preventDefault()
                  nhan(e.clipboardData.getData('text'))
                }}
                className="min-w-[160px] flex-1 bg-transparent py-1 text-[14px] outline-none"
              />
            </div>

            <p className="mt-4 text-[13.5px] font-medium text-fg">Vai trò</p>
            <div className="mt-1.5 space-y-1" role="radiogroup" aria-label="Vai trò">
              {(vaiTro ?? []).map((v) => (
                <label
                  key={v.id}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 hover:bg-fill"
                >
                  <input
                    type="radio"
                    name="moi-vai-tro"
                    value={v.id}
                    checked={roleId === v.id}
                    onChange={() => setRoleId(v.id)}
                  />
                  <span className="text-[14px] text-fg">{v.name}</span>
                </label>
              ))}
            </div>

            {gui.error && (
              <p role="alert" className="mt-3 text-[13px] text-badge-alert-fg">
                {gui.error instanceof LoiApi ? gui.error.message : 'Không gửi được lời mời'}
              </p>
            )}

            <div className={`${HANG_NUT} mt-5`}>
              <button type="button" className={NUT_PHU} onClick={onDong}>
                Huỷ
              </button>
              <button
                type="button"
                className={NUT_CHINH}
                disabled={emails.length === 0 || roleId === '' || gui.isPending}
                onClick={() => gui.mutate()}
              >
                Gửi lời mời
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function PanelKetQua({ ketQua, onDong }: { ketQua: readonly KetQuaMoi[]; onDong: () => void }) {
  const moi = ketQua.filter((k) => !k.daCo)
  const daCo = ketQua.filter((k) => k.daCo)
  // Ngày backend có mailer: mọi `invitePath` là `null`, khối link biến mất, và
  // câu dưới đây là toàn bộ panel.
  const coLink = moi.some((k) => k.invitePath !== null)

  return (
    <>
      <h2 className="text-[15px] font-semibold text-fg">Đã mời {ketQua.length} người</h2>

      {coLink && (
        <>
          <p className="mt-1.5 text-[13.5px] leading-[1.55] text-muted">
            Chưa có email tự động — gửi link này cho họ.
          </p>
          <div className="mt-3 space-y-2">
            {moi.map((k) => {
              const url = urlMoi(k.invitePath)
              if (url === null) return null
              return (
                <div key={k.email} className="flex flex-wrap items-center gap-2">
                  <span className="min-w-[150px] font-mono text-[12.5px] text-muted-2">
                    {k.email}
                  </span>
                  <label className="sr-only" htmlFor={`link-${k.userId}`}>
                    Link mời của {k.email}
                  </label>
                  <input
                    id={`link-${k.userId}`}
                    readOnly
                    value={url}
                    onFocus={(e) => e.currentTarget.select()}
                    className="min-w-[200px] flex-1 rounded-md border border-border-strong bg-surface px-3 py-2 font-mono text-[12.5px] outline-none focus:border-fg"
                  />
                  <button
                    type="button"
                    className={NUT_PHU}
                    onClick={() => void navigator.clipboard.writeText(url).catch(() => {})}
                  >
                    Sao chép
                  </button>
                </div>
              )
            })}
          </div>
        </>
      )}

      {daCo.length > 0 && (
        <p className="mt-3.5 text-[13px] leading-[1.55] text-muted">
          {daCo.map((k) => k.email).join(' · ')} — đã có tài khoản trong tổ chức, đã thêm thẳng vào
          workspace, không cần lời mời.
        </p>
      )}

      <div className={`${HANG_NUT} mt-5`}>
        <button type="button" className={NUT_CHINH} onClick={onDong}>
          Xong
        </button>
      </div>
    </>
  )
}
```

- [ ] **Step 4: Nối nút «Mời thành viên»**

Trong `UserAdmin.tsx`: thêm `const [moMoi, setMoMoi] = useState(false)`, đổi nút thành `onClick={() => setMoMoi(true)}`, và render `{moMoi && <MoiThanhVienDialog onDong={() => setMoMoi(false)} />}` ngay trước thẻ đóng của `<div className="px-7 py-6">`.

- [ ] **Step 5: Chạy test — ⑩⑪⑫ phải XANH**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx
```

Kỳ vọng: 12 passed.

- [ ] **Step 6: Typecheck + format + commit**

```bash
npx tsc -b --force
npx prettier --write src/features/auth/components/MoiThanhVienDialog.tsx src/features/auth/components/UserAdmin.tsx tests/thanh-vien.test.tsx
git add src/ tests/ docs/
git commit -m "feat(auth): hộp thoại mời — nhiều email, một vai trò, một bước

Lối ElevenLabs/Linear/Vercel: vai trò chọn ngay trong bước mời nên quyền được
khoanh từ cú bấm đầu. Panel kết quả là chỗ DUY NHẤT lệch — backend chưa có
mailer nên vẫn phải copy link; invitePath đã là string|null từ hợp đồng để ngày
có mailer chỉ panel này đổi.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Sửa hồ sơ — `UserForm` thu còn hai ô

**Files:**

- Modify: `src/features/auth/components/UserForm.tsx` (777 → ~120 dòng)
- Modify: `src/features/auth/components/UserAdmin.tsx` (thêm mục `Sửa hồ sơ…`)
- Test: `tests/thanh-vien.test.tsx`

**Interfaces:**

- Consumes: `taiChiTietUser`, `suaUser` (`../api`, đã có)
- Produces: `SuaHoSoDialog({ userId, ten, onDong }: { userId: string; ten: string; onDong: () => void })` — **xuất từ `UserForm.tsx`**

- [ ] **Step 1: Viết test đỏ**

```tsx
it('⑬ sửa hồ sơ chỉ có tên + điện thoại — KHÔNG có chức danh, KHÔNG có vai trò', async () => {
  boot()
  const hang = await hangCua('Người Chờ Mời')
  await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Sửa hồ sơ…' }))
  const hop = await screen.findByRole('dialog')
  expect(within(hop).getByLabelText(/Họ tên/)).toBeTruthy()
  expect(within(hop).getByLabelText(/Số điện thoại/)).toBeTruthy()
  // `jobTitle` rời giao diện 2026-08-09 — chữ tự do không lọc/sắp/quyết định
  // quyền gì. Cột đã bỏ trước đó; đây là vế còn lại.
  expect(within(hop).queryByLabelText(/Chức danh/)).toBeNull()
  // Vai trò có mục RIÊNG trong ⋯ — hai đường tới một thứ là hai chỗ để lệch.
  expect(within(hop).queryByRole('radiogroup')).toBeNull()
})

it('⑭ lưu hồ sơ giữ NGUYÊN memberships — không được xoá quyền ở workspace khác', async () => {
  // `PATCH /users/{id}` THAY THẾ toàn bộ `memberships`, không cộng dồn. Gửi
  // mảng rỗng ở đây là xoá sạch quyền của người đó ở MỌI workspace — bug mất
  // dữ liệu thật, đã gặp 2026-08-06.
  let than: { memberships?: unknown[] } | null = null
  server.use(
    http.patch('/api/v1/users/:id', async ({ request }) => {
      than = (await request.json()) as { memberships?: unknown[] }
      return HttpResponse.json({ id: 'u_fake_cho', memberships: [] })
    }),
  )
  boot()
  const hang = await hangCua('Người Chờ Mời')
  await userEvent.click(within(hang).getByRole('button', { name: /Thao tác/ }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Sửa hồ sơ…' }))
  const hop = await screen.findByRole('dialog')
  await userEvent.clear(within(hop).getByLabelText(/Họ tên/))
  await userEvent.type(within(hop).getByLabelText(/Họ tên/), 'Tên Mới')
  await userEvent.click(within(hop).getByRole('button', { name: 'Lưu' }))
  await waitFor(() => expect(than).not.toBeNull())
  expect(than?.memberships).toBeInstanceOf(Array)
  expect((than?.memberships ?? []).length).toBeGreaterThan(0)
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx -t "⑬"
```

- [ ] **Step 3: Thay `UserForm.tsx` bằng `SuaHoSoDialog`**

Thay **toàn bộ** `src/features/auth/components/UserForm.tsx`:

```tsx
/**
 * Sửa HỒ SƠ một thành viên — hai ô: họ tên · số điện thoại.
 *
 * Thu từ 777 dòng xuống (2026-08-09). Form cũ mang cả `email`, `jobTitle`,
 * `orgRole`, một BẢNG membership, và luồng tạo-user-mới. Từng cái rời đi:
 *   · tạo user mới  → `MoiThanhVienDialog` (một bước, chọn vai trò cùng lúc)
 *   · membership    → `DoiVaiTroDialog` (`PATCH /members/{id}`, một dòng)
 *   · `jobTitle`    → BỎ, chữ tự do không lọc/sắp/quyết định quyền gì
 *   · `email`       → không sửa được, nó là khoá đăng nhập
 *   · `orgRole`     → không sửa ở đây, chuyển chủ tổ chức là việc khác hẳn
 *
 * ⚠ ĐÃ CÂN NHẮC VÀ BỎ: dựng màn hồ sơ cá nhân để chính chủ tự sửa (lối Linear —
 * admin không sửa hộ ai). Đúng hơn về nguyên tắc nhưng là MỘT MÀN MỚI (4 bước
 * theo luật repo) cho việc chưa ai đòi. Đổi sang lối đó rẻ: bỏ một mục khỏi `⋯`.
 *
 * ⚠ `memberships` PHẢI ĐI QUA NGUYÊN VẸN. `PATCH /users/{id}` THAY THẾ toàn bộ
 * mảng đó, không cộng dồn — gửi `[]` là xoá sạch quyền của người này ở MỌI
 * workspace (bug mất dữ liệu thật, 2026-08-06). Nên: `taiChiTietUser` trước,
 * chép nguyên `roleId`/`expiresAt` server trả, chỉ đổi `name`/`phone`.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { LoiApi, suaUser, taiChiTietUser, type MembershipIn } from '../api'
import { KHOA_TV } from '../thanhVien'

const O_NHAP =
  'w-full rounded-md border border-border-strong px-3 py-2.5 text-[14px] outline-none focus:border-ac'

/** Chỉ giữ chữ số — số VN mở đầu bằng `0`, và `type="number"` ăn mất số 0 đó. */
function chiSo(tho: string): string {
  return tho.replace(/\D/g, '')
}

export function SuaHoSoDialog({
  userId,
  ten,
  onDong,
}: {
  userId: string
  ten: string
  onDong: () => void
}) {
  const queryClient = useQueryClient()
  const { data, isPending } = useQuery({
    queryKey: ['users', userId],
    queryFn: () => taiChiTietUser(userId),
  })
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [daNap, setDaNap] = useState(false)

  // Nạp ĐÚNG MỘT LẦN khi chi tiết về. `useState` initializer không dùng được vì
  // render đầu chưa có `data`; một `useEffect` không cờ sẽ ghi đè chữ người dùng
  // đang gõ mỗi lần query refetch.
  useEffect(() => {
    if (!data || daNap) return
    setName(data.name)
    setPhone(data.phone ?? '')
    setDaNap(true)
  }, [data, daNap])

  useEffect(() => {
    function phim(e: KeyboardEvent) {
      if (e.key === 'Escape') onDong()
    }
    document.addEventListener('keydown', phim)
    return () => document.removeEventListener('keydown', phim)
  }, [onDong])

  const luu = useMutation({
    mutationFn: () => {
      if (!data) throw new LoiApi('CHUA_TAI', 'Chưa tải xong hồ sơ')
      // Chép NGUYÊN mảng membership server vừa trả. `MembershipOut.roleId` CHÍNH
      // LÀ handle mà `MembershipIn.roleId` nhận vào, nên vòng đọc-ghi khép kín và
      // không có chỗ nào để bịa ra một id.
      const memberships: MembershipIn[] = data.memberships.map((m) => ({
        workspaceId: m.workspaceId,
        roleId: m.roleId,
        expiresAt: m.expiresAt,
      }))
      return suaUser(userId, {
        name: name.trim(),
        phone: phone.trim() === '' ? null : phone.trim(),
        jobTitle: data.jobTitle,
        orgRole: data.orgRole,
        memberships,
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KHOA_TV })
      void queryClient.invalidateQueries({ queryKey: ['users', userId] })
      onDong()
    },
  })

  return (
    <div className="fixed inset-0 z-70 grid place-items-center px-4">
      <button
        type="button"
        aria-label="Đóng"
        onClick={onDong}
        className="fixed inset-0 cursor-default bg-fg/25"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Sửa hồ sơ của ${ten}`}
        className="relative w-full max-w-[420px] rounded-lg border border-border bg-surface p-5"
      >
        <h2 className="text-[15px] font-semibold text-fg">Sửa hồ sơ</h2>

        {isPending ? (
          <p className="mt-4 text-[14px] text-muted">Đang tải…</p>
        ) : (
          <>
            <label htmlFor="hs-ten" className="mt-4 block text-[13.5px] font-medium text-fg">
              Họ tên
            </label>
            <input
              id="hs-ten"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={`${O_NHAP} mt-1.5`}
            />

            <label htmlFor="hs-dt" className="mt-3.5 block text-[13.5px] font-medium text-fg">
              Số điện thoại
            </label>
            <input
              id="hs-dt"
              type="tel"
              inputMode="numeric"
              value={phone}
              onChange={(e) => setPhone(chiSo(e.target.value))}
              placeholder="VD: 0901234567"
              className={`${O_NHAP} mt-1.5`}
            />

            {luu.error && (
              <p role="alert" className="mt-3 text-[13px] text-badge-alert-fg">
                {luu.error instanceof LoiApi ? luu.error.message : 'Không lưu được hồ sơ'}
              </p>
            )}

            <div className={`${HANG_NUT} mt-5`}>
              <button type="button" className={NUT_PHU} onClick={onDong}>
                Huỷ
              </button>
              <button
                type="button"
                className={NUT_CHINH}
                disabled={luu.isPending || name.trim() === ''}
                onClick={() => luu.mutate()}
              >
                Lưu
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Thêm mục vào menu `⋯`**

Trong `UserAdmin.tsx` — thêm import `SuaHoSoDialog`, mở rộng union state và thêm mục:

```tsx
const [hop, setHop] = useState<'doi-vai-tro' | 'ho-so' | 'go' | null>(null)
```

```tsx
const muc: MucMenu[] = [
  { key: 'vai-tro', nhan: 'Đổi vai trò…', onChon: () => setHop('doi-vai-tro') },
  { key: 'ho-so', nhan: 'Sửa hồ sơ…', onChon: () => setHop('ho-so') },
  ...(m.lifecycle === 'pending'
    ? [{ key: 'moi-lai', nhan: 'Gửi lại lời mời', onChon: () => moiLai.mutate() }]
    : []),
  ...(goDuoc
    ? [{ key: 'go', nhan: 'Gỡ khỏi workspace', onChon: () => setHop('go'), phaHuy: true }]
    : []),
]
```

```tsx
{
  hop === 'ho-so' && <SuaHoSoDialog userId={m.userId} ten={m.name} onDong={() => setHop(null)} />
}
```

- [ ] **Step 5: Chạy test — ⑬⑭ phải XANH**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/thanh-vien.test.tsx
```

Kỳ vọng: 14 passed.

- [ ] **Step 6: Typecheck + format + commit**

```bash
npx tsc -b --force
npx prettier --write src/features/auth/components/UserForm.tsx src/features/auth/components/UserAdmin.tsx tests/thanh-vien.test.tsx
git add src/ tests/ docs/
git commit -m "refactor(auth): UserForm thu còn hộp thoại hồ sơ hai ô (777 → ~180)

Tạo-user-mới về MoiThanhVienDialog, membership về DoiVaiTroDialog, jobTitle bỏ,
email và orgRole không sửa ở đây. memberships vẫn đi qua NGUYÊN VẸN — PATCH
/users/{id} thay thế cả mảng, gửi [] là xoá quyền ở mọi workspace.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Dọn — xoá cây vai trò, đổi nhãn nav, cập nhật cổng CI

**Files:**

- Delete: `DanhSachVaiTro.tsx` · `FormVaiTro.tsx` · `TomTatVaiTro.tsx` · `TomTatUser.tsx` · `MemberList.tsx` · `tabUsers.ts` · `tests/vai-tro.test.tsx` · `tests/members.test.tsx` · `tests/user-admin.test.tsx`
- Modify: `src/features/auth/api.ts` · `src/features/auth/nav.ts` · `src/features/auth/nhan.ts` · `src/lib/msw/handlers.ts` · `tests/nav-registry.test.ts`

- [ ] **Step 1: Xoá file**

⚠ `MemberList.tsx` · `tabUsers.ts` · `tests/user-admin.test.tsx` · `tests/members.test.tsx` **đã xoá ở Task 2 Step 6** (chúng đỏ ngay khi `UserAdmin` đổi hình dạng). Còn lại ở đây:

```bash
git rm src/features/auth/components/DanhSachVaiTro.tsx \
       src/features/auth/components/FormVaiTro.tsx \
       src/features/auth/components/TomTatVaiTro.tsx \
       src/features/auth/components/TomTatUser.tsx \
       tests/vai-tro.test.tsx
```

Nếu tệp nào trong danh sách đó đã bị xoá ở task trước thì bỏ qua, đừng coi là lỗi.

- [ ] **Step 2: Dọn `api.ts`**

Xoá: `layDanhSachAction` · `taoVaiTro` · `suaVaiTro` · `xoaVaiTro` · `layVaiTro` · `taoUser` · `xoaUser` · `moiLai` · `urlMoiTuyetDoi` · `taiDanhSachUser`, và kiểu chỉ chúng dùng: `ActionInfo` · `ThanVaiTro` · `VaiTroChiTiet` · `UserListItem`.

**GIỮ:** `layDanhSachVaiTro` + `khoaVaiTro` (hai hộp thoại dựng danh sách vai trò từ đó) · `taiChiTietUser` + `suaUser` (`SuaHoSoDialog`) · `xemLoiMoi` + `nhanLoiMoi` (màn nhận lời mời không đổi) · `dangNhap` · `dangXuat` · `doiWorkspace` · `LoiApi` · `OrgRole` · `Lifecycle` · `MembershipIn` · `MembershipOut` · `UserDetail` · `VaiTroToChuc`.

Cách chắc chắn, đừng dựa trí nhớ — xoá từng cái rồi để `tsc` chỉ chỗ:

```bash
npx tsc -b --force 2>&1 | head -30
```

Nếu `tsc` báo một hàm bạn định xoá vẫn còn chỗ gọi, **đọc chỗ đó trước**: hoặc chỗ gọi là mồ côi (xoá theo), hoặc bạn đang xoá nhầm.

Thêm ghi chú lên đầu khối vừa dọn:

```ts
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
```

- [ ] **Step 3: Dọn `nhan.ts`**

Xoá `NHAN_NHOM_ACTION` · `THU_TU_NHOM_ACTION` (chỉ `FormVaiTro` dùng) · `nhanHetHan` · `isoSangNgayInput` · `ngayInputSangIso` (`expiresAt` rời giao diện).

**GIỮ:** `NHAN_ORG_ROLE` · `NHAN_LIFECYCLE` · `MAU_LIFECYCLE`.

- [ ] **Step 4: Đổi nhãn nav**

`src/features/auth/nav.ts` — thay khối docstring + `label`:

```ts
/**
 * NHÃN LÀ «Thành viên» (2026-08-09, lần đổi thứ hai trong ngày).
 *
 * Sáng 09/08 nó đổi «Thành viên & Phân quyền» → «Người dùng», với lý do *gọi tên
 * màn theo BẢNG PHỤ — bảng chính là người dùng toàn tổ chức*. Lý do đó gắn liền
 * với TRỤC CŨ. Chiều 09/08 trục đổi sang workspace (spec «gọn thành viên và phân
 * quyền» §2.2), nên bảng chính GIỜ LÀ thành viên workspace và nhãn đi theo.
 *
 * Không phải đảo quyết định sáng — là hệ quả của việc đổi trục. Vế «& Phân
 * quyền» thì KHÔNG quay lại: luật «nhãn nav là tên một CHỖ, không phải mục lục»
 * vẫn đứng.
 *
 * ⚠ Nhãn dài nhất của panel Quản trị KHÔNG còn là mục này. Bề rộng panel 240px đo
 * theo «Thành viên & Phân quyền» (167px ở 13.5px); nhãn mới ngắn hơn hẳn nên
 * panel còn dư chỗ — ĐỪNG bóp panel theo nó, số đo 240px phục vụ cả ba mảng.
 */
export const usersNav: NavLeaf = {
  kind: 'leaf',
  key: 'users',
  path: '/users',
  label: { vi: 'Thành viên', en: 'Members' },
  icon: 'users',
  requiredActions: [ACTIONS.WORKSPACE_ADMIN],
}
```

- [ ] **Step 5: Dọn handler MSW của `/roles` ghi**

Xoá `http.post('/api/v1/roles')` · `http.patch('/api/v1/roles/:id')` · `http.delete('/api/v1/roles/:id')`.

**GIỮ** `http.get('/api/v1/roles')` · `http.get('/api/v1/roles/:id')` · `http.get('/api/v1/actions')` — backend vẫn có chúng, và luật repo là fake phải nói đúng **backend**, không nói đúng **UI**.

Nếu `RESET_VAI_TRO_GIA` / `soNguoiDungVaiTro` thành mồ côi thì để nguyên và ghi một dòng lý do; đừng xoá thứ backend vẫn có.

- [ ] **Step 6: Sửa `tests/nav-registry.test.ts`**

Bài này đối chiếu nav với `lib/screens.ts`. Đổi nhãn làm nó đỏ nếu nó khoá chuỗi.

```bash
grep -rn "Người dùng" tests/nav-registry.test.ts src/lib/screens.ts
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/nav-registry.test.ts
```

Sửa mọi chỗ `'Người dùng'` → `'Thành viên'` và `'Users'` → `'Members'` trong hai tệp đó. **Đừng nới lỏng phép so** — cổng này là thứ biến "sidebar khớp thiết kế" từ lời hứa thành thứ CI kiểm được.

- [ ] **Step 7: Sửa mọi test còn nhắc màn cũ**

```bash
grep -rn "Người dùng\|tab=vai-tro\|MemberList\|user-admin" tests/ src/ --include=*.ts --include=*.tsx
```

Ứng viên: `tests/boot.test.tsx` (dấu hiệu màn `users`), `tests/command-palette.test.tsx` (tìm theo nhãn nav), `tests/shell.test.tsx`. Sửa từng cái theo nhãn mới.

- [ ] **Step 8: Chạy TOÀN BỘ suite, so với mốc Task 0**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -20
```

Kỳ vọng: số `passed` ≥ mốc Task 0 trừ đi số bài của ba tệp vừa xoá, cộng 14 bài mới. **Số `failed` phải BẰNG mốc Task 0** — không nhiều hơn một bài nào.

Nếu nhiều hơn: dừng, tìm ra bài nào, đừng đi tiếp.

- [ ] **Step 9: Cổng cấu trúc + typecheck + format**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/nav-registry.test.ts tests/module-boundaries.test.ts tests/actions-parity.test.ts tests/tools-parity.test.ts tests/membership-shape-parity.test.ts
npx tsc -b --force
npx prettier --check 'src/**/*.{ts,tsx}' 'tests/**/*.{ts,tsx}'
```

`actions-parity` và `tools-parity` phải xanh **mà không sửa gì** — nếu chúng đỏ thì bạn đã đụng vào cưỡng chế, và đó là vi phạm Global Constraints.

- [ ] **Step 10: Commit**

```bash
git add src/ tests/ docs/
git commit -m "refactor(auth): xoá cây tự-tạo-vai-trò khỏi giao diện, nav thành «Thành viên»

Xoá 9 tệp (~1330 dòng): DanhSachVaiTro · FormVaiTro · TomTatVaiTro · TomTatUser
· MemberList · tabUsers + 3 tệp test. Endpoint /roles ghi và /actions VẪN sống ở
backend — cắt bề mặt tác giả, không cắt năng lực (PQ_01 §BR-Q03).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Cập nhật CLAUDE.md

**Files:**

- Modify: `CLAUDE.md`

- [ ] **Step 1: Sửa mục «Xem trước, sửa sau»**

Bảng 7 màn: bỏ hai dòng `/users` và `/users` tab Vai trò (`TomTatUser.tsx`, `TomTatVaiTro.tsx` không còn). Thêm một câu:

> `/users` KHÔNG còn theo khuôn này (2026-08-09): màn chỉ còn một bảng chỉ-đọc, mọi đường ghi ở sau menu `⋯` và mở ra hộp thoại — tức bản thân màn ĐÃ LÀ chế độ xem.

- [ ] **Step 2: Thêm mục mới sau «Tài liệu — hai kho…»**

```markdown
## Thành viên — một bảng, trục là WORKSPACE

`/users` liệt kê thành viên của **workspace đang mở**, không phải người dùng toàn tổ chức. Mỗi hàng đúng một vai trò ⇒ bảng phẳng, không cột động, không dòng giải thích. Xem workspace khác thì đổi switcher (lối Linear · Slack).

- **Bốn vai trò dựng sẵn, KHÔNG tự tạo được.** PQ_01 §2.2 (Quản trị · CSKH · Biên tập · Người xem) giữ nguyên; tab «Vai trò» với ma trận 13 nhóm action đã xoá. 13 action ở lại backend làm **định nghĩa** của bốn vai trò đó. `POST/PATCH/DELETE /roles` + `GET /actions` **vẫn sống ở backend** — cắt bề mặt tác giả, không cắt năng lực.
- **Mọi đường ghi ở sau menu `⋯`**, không có `<select>` quyền hạn nào sống trong bảng. Đó là luật «xem trước, sửa sau» áp cho một bảng: ô chọn quyền luôn mở mời gõ nhầm vào dữ liệu đang phát hành. `tests/thanh-vien.test.tsx` ⑬ canh việc này.
- **`GET /members` mang `lifecycle` + `isOrgOwner`** — phái sinh ở server. FE không còn đọc `GET /users` nên không có nguồn nào khác.
- ⚠ **`POST`/`PATCH`/`DELETE /members` và `POST /members/{id}/invite` là hợp đồng FE ĐỊNH TRƯỚC, backend CHƯA CÓ.** Cùng lối `/agent/try` và `/linh-vuc`.
- **`DELETE /members/{id}` gỡ khỏi WORKSPACE, không xoá tài khoản.** Nó giải một lỗ: `DELETE /users/{id}` chỉ chạy khi user còn `pending`, nên trước đó không có đường gỡ người đang hoạt động.
- **`expiresAt` và `jobTitle` rời giao diện.** Cột DB giữ nguyên; `POST /members` không nhận `expiresAt`, server đặt `NULL`. Thu hồi quyền = gỡ khỏi workspace.
- ⚠ **Backend KHÔNG có bộ gửi mail** (đo 2026-08-09). Nên panel kết quả của hộp thoại mời hiện **link để copy**. `invitePath` là `string | null` ngay từ hợp đồng: ngày có mailer, backend đổi giá trị chứ không đổi hình dạng, và **chỉ panel đó** phải sửa. Đừng để logic mailer rò ra ngoài `MoiThanhVienDialog.tsx`.
```

- [ ] **Step 3: Thêm dòng Change Log**

```markdown
| 2026-08-09 | **`/users` gọn: bỏ vai trò tuỳ chỉnh, trục đổi sang workspace, mời một bước.** Đối chiếu ElevenLabs · Linear · Vercel — không hệ nào có vai trò tuỳ chỉnh, cả ba mời bằng email + vai trò trong MỘT bước. Tab «Vai trò» + ma trận 13 nhóm action rời giao diện (endpoint vẫn ở backend); bảng đổi trục từ tổ chức sang workspace đang mở ⇒ mỗi hàng một vai trò; `MemberOut` mọc `lifecycle` + `isOrgOwner`; 4 endpoint `/members` mới do FE định hợp đồng. Cắt `expiresAt` + `jobTitle` khỏi UI. Vai trò rời `<select>` trong hàng vào menu `⋯`. Xoá 9 tệp (~1330 dòng), nhãn nav «Người dùng» → «Thành viên» (hệ quả của đổi trục, không đảo quyết định sáng cùng ngày) |
```

- [ ] **Step 4: Format + commit**

```bash
npx prettier --write CLAUDE.md
git add CLAUDE.md
git commit -m "docs: CLAUDE.md ghi mục Thành viên và luật trục-là-workspace

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Nghiệm thu cuối

- [ ] `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run` — số `failed` **bằng** mốc Task 0
- [ ] `npx tsc -b --force` — sạch
- [ ] `npx prettier --check 'src/**/*.{ts,tsx}' 'tests/**/*.{ts,tsx}'` — chỉ còn `routeTree.gen.ts` (tệp sinh, không phải nợ của bạn)
- [ ] `make dev` → mở `http://localhost:5273/users` và kiểm bằng mắt:
  - một bảng, không hàng tab
  - `⋯` mở ra 2–4 mục tuỳ hàng; hàng của chính mình **không** có «Gỡ khỏi workspace»
  - «Mời thành viên» → gõ 2 email → chọn vai trò → gửi → panel hiện link copy được
  - đổi vai trò một người → pill trong bảng đổi theo
- [ ] Nhãn nav ở panel đọc «Thành viên», Topbar đọc `<h1>Thành viên</h1>`
- [ ] `?tab=vai-tro` (link cũ) vẫn mở được màn, không vỡ
