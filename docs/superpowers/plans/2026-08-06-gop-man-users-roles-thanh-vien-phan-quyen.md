# Gộp màn Users + Roles → "Thành viên & Phân quyền" — Implementation Plan

> ## ⚠ NHẬT KÝ KẾ HOẠCH — KHÔNG PHẢI MÔ TẢ HIỆN TRẠNG. ĐỪNG CHÉP CODE TỪ FILE NÀY.
>
> File này là bản DỰ KIẾN viết trước khi thi công (2026-08-06). Nó được giữ lại
> làm nhật ký, không được cập nhật theo code.
>
> **Cụ thể: khối cài đặt `OVaiTroThanhVien` ở Task 3 mang BỐN khuyết tật đã được
> đo là bug thật và đã bị thay thế** — (1) `roleId: … ?? ''` bịa giá trị khi khớp
> ngược tên→id hụt ⇒ ghi đè mất membership ở workspace khác; (2) `hienTai = … ?? ''`
> làm `<select>` hiện OPTION ĐẦU ⇒ ô nói người dùng đang giữ một vai trò họ không
> giữ, dẫn tới leo thang quyền im lặng; (3) `onSuccess` chỉ invalidate `['members']`
> ⇒ mở lại form Sửa rồi bấm Lưu là lật ngược thay đổi vừa làm; (4) đọc hai vế của
> phép khớp tên↔id TUẦN TỰ thay vì cùng một nhịp. Mẫu `?? ''` xuất hiện ở nhiều
> chỗ khác trong file này cũng vậy.
>
> Docstring bên trong các mẫu đó viết y hệt code đã ship, nên chúng **đọc ra như
> thẩm quyền**. Đừng tin. Nguồn sự thật là code thật
> (`src/features/auth/components/MemberList.tsx`, `UserForm.tsx`) và spec §7 · §11.
>
> **Thêm 2026-08-07:** khoảng cách còn rộng hơn thế. Toàn bộ phép **đối chiếu
> ngược tên → id** trong file này — không chỉ mẫu `?? ''` — đã bị xoá khỏi code:
> server trả thẳng `roleId` ở `MembershipOut` và `MemberOut`. Đọc **spec §12**
> trước, nó là mục mô tả hiện trạng; §11 nay cũng là khảo cổ như file này.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gộp `/users` và `/roles` thành một màn `/users` với 2 tab ("Thành viên" · "Vai trò"), sửa nhãn/icon nav bị nhập nhằng, thêm sửa vai trò inline AN TOÀN ở bảng thành viên workspace, và xoá enum vai trò chết.

**Architecture:** `UserAdmin` (export mới) làm container tab đọc `tab` từ search-param của route `/users` (cùng khuôn `?tab=` của `/pform`), render lại đúng nội dung hiện có (`NoiDungThanhVien` — đổi tên từ `UserAdmin` cũ; `DanhSachVaiTro` — không đổi) theo tab. `/roles` trở thành route redirect. Vai trò VẪN là 2 bảng riêng (không gộp 1 dòng/người — xem spec §5), chỉ thêm dropdown sửa vai trò tại dòng ở bảng thành viên workspace, dùng fetch-toàn-bộ-rồi-ghép-lại để không xoá mất membership ở workspace khác.

**Tech Stack:** React 18 + TypeScript, TanStack Router (file-based, search-param cho tab — không path param), TanStack Query, Tailwind v4, Vitest + Testing Library + MSW.

**Spec:** [`docs/superpowers/specs/2026-08-06-gop-man-users-roles-thanh-vien-phan-quyen-design.md`](../specs/2026-08-06-gop-man-users-roles-thanh-vien-phan-quyen-design.md)

## Global Constraints

- Không đổi API/data model/`ACTIONS.WORKSPACE_ADMIN`. Không thêm màn Permissions độc lập. (spec §3)
- `suaUser` PATCH thay TOÀN BỘ `memberships`, không cộng dồn — mọi mutation sửa vai trò PHẢI tải chi tiết đầy đủ trước, ghép lại, rồi mới gửi. Không bao giờ PATCH với `memberships` chỉ chứa 1 dòng. (spec §5)
- Không xoá `src/routes/_app/roles.tsx` hay dòng `roles` trong `src/lib/screens.ts` — `tests/nav-registry.test.ts` đối chiếu 1:1 route file ↔ `screens.ts`. (spec §2①)
- `src/lib/nav-registry.ts` chỉ nên đổi nhãn theo quy tắc thường của repo; xoá hẳn entry `rolesNav` là ngoại lệ có chủ đích của chính task này, không phải việc tiện tay. (spec §2②)
- Sau mỗi task: `make test` (hoặc target test file cụ thể) phải xanh trước khi qua task kế.
- Giữ đúng style/docstring hiện có (tiếng Việt, giải thích "vì sao") khi sửa file cũ — không viết lại toàn bộ file, chỉ đổi đúng phần liên quan.

---

### Task 1: Vá `GET /api/v1/members` — nối với `USERS_GIA` thay vì fake tĩnh rời

**Vì sao task này đứng đầu:** `MemberList` hiện tại dùng fake `/api/v1/members` HOÀN TOÀN TĨNH (2 dòng viết cứng), không liên quan gì tới `USERS_GIA` — người dùng `u_fake_dang` trong đó chính là `FAKE_SESSION.user` (chủ tổ chức), nhưng `USERS_GIA` của chủ tổ chức có `memberships: []` (owner không có membership, đúng luật nghiệp vụ). Nếu không vá, Task 3 (sửa vai trò inline) không có dữ liệu thật để test/dev — mọi `taiChiTietUser()` gọi cho một dòng trong `MemberList` sẽ 404.

**Files:**
- Modify: `src/lib/msw/handlers.ts` (khối `http.get('/api/v1/members', ...)`, dòng ~644-658)
- Test: `tests/vai-tro.test.tsx`, `tests/user-admin.test.tsx`, `tests/boot.test.tsx` (chạy lại để xác nhận không đỏ — không sửa nội dung ba file này ở task này)

**Interfaces:**
- Consumes: `USERS_GIA` (module-level, đã có), `VAI_TRO_GIA` (module-level, đã có), `conHieuLuc()` (đã có), `FAKE_SESSION.currentWorkspaceId` (đã có, = `'ws_anphu'`)
- Produces: `GET /api/v1/members` trả `{userId, name, email, role}[]` — CHỈ những user có membership CÒN HIỆU LỰC ở `FAKE_SESSION.currentWorkspaceId`, `role` là tên thật từ `VAI_TRO_GIA` (không phải chuỗi viết cứng)

- [ ] **Step 1: Viết test xác nhận hành vi mới (thêm vào `tests/vai-tro.test.tsx`, cuối describe `'Màn Vai trò'`)**

```ts
it('⑩ GET /api/v1/members chỉ trả người CÓ membership còn hiệu lực ở workspace hiện tại, role lấy tên thật', async () => {
  // `u_fake_lan` (seed sẵn trong USERS_GIA) ở đúng workspace hiện tại
  // (WS_GIA_1 === FAKE_SESSION.currentWorkspaceId), vai trò role_gia_qt =
  // Quản trị. `u_fake_minh`/`u_fake_cho` ở WS_GIA_2 — không thuộc workspace
  // hiện tại nên KHÔNG được trả. Chủ tổ chức (`u_fake_dang`) không có
  // membership nào — cũng không được trả, dù bản fake cũ viết cứng nó vào.
  const res = await fetch('/api/v1/members')
  const body = (await res.json()) as { userId: string; name: string; role: string }[]
  expect(body.map((m) => m.userId).sort()).toEqual(['u_fake_lan'])
  expect(body[0]?.role).toBe('Quản trị')
})
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `npx vitest run tests/vai-tro.test.tsx -t "⑩"`
Expected: FAIL — body vẫn là 2 dòng viết cứng (`u_fake_dang`/`u_fake_lan`, role `'Quản trị'`/`'CSKH'`), không khớp assertion.

- [ ] **Step 3: Sửa handler**

Thay khối hiện tại (dòng ~644-658 của `src/lib/msw/handlers.ts`):

```ts
  // `role` là TÊN vai trò tổ chức trả thẳng từ backend (migration 0104 xoá bốn
  // mã cố định `admin`/`care`/`editor`/`viewer` — xem `MemberOut` ở MemberList.tsx),
  // không phải một trong bốn mã đó. 'Quản trị'/'CSKH' ở đây là tên hai vai trò
  // mẫu, gõ nguyên văn — KHÔNG qua bảng nhãn nào.
  http.get('/api/v1/members', () =>
    HttpResponse.json([
      {
        userId: 'u_fake_dang',
        name: 'Trần Hải Đăng',
        email: 'dang@anphuland.vn',
        role: 'Quản trị',
      },
      { userId: 'u_fake_lan', name: 'Nguyễn Thị Lan', email: 'lan@anphuland.vn', role: 'CSKH' },
    ]),
  ),
```

thành:

```ts
  // NỐI THẬT với `USERS_GIA`/`VAI_TRO_GIA` (Task gộp Users+Roles, 2026-08-06) —
  // bản trước là 2 dòng viết cứng, đứng NGOÀI hai bàn giả đó. `u_fake_dang`
  // (chủ tổ chức) từng bị gán cứng Quản trị ở đây dù `USERS_GIA` của owner
  // luôn `memberships: []` (owner không cần membership — bỏ qua mọi workspace
  // riêng, xem `UserForm.tsx laOwner ? [] : ...`). Giờ tính đúng: chỉ user có
  // membership CÒN HIỆU LỰC (`conHieuLuc`) ở đúng workspace đang mở mới xuất
  // hiện, và `role` đọc TÊN THẬT từ `VAI_TRO_GIA` — cùng cách `raMembershipOut`
  // đã làm cho `GET /users/:id`, MỘT nguồn cho phép dịch roleId -> tên.
  http.get('/api/v1/members', () => {
    const hienTai = FAKE_SESSION.currentWorkspaceId
    return HttpResponse.json(
      USERS_GIA.flatMap((u) => {
        const m = u.memberships.find((mm) => mm.workspaceId === hienTai && conHieuLuc(mm))
        if (!m) return []
        return [
          {
            userId: u.id,
            name: u.name,
            email: u.email,
            role: VAI_TRO_GIA.find((r) => r.id === m.roleId)?.name ?? m.roleId,
          },
        ]
      }),
    )
  }),
```

- [ ] **Step 4: Chạy lại test mới, xác nhận PASS**

Run: `npx vitest run tests/vai-tro.test.tsx -t "⑩"`
Expected: PASS

- [ ] **Step 5: Chạy toàn bộ 3 file test liên quan, xác nhận không đỏ**

Run: `npx vitest run tests/vai-tro.test.tsx tests/user-admin.test.tsx tests/boot.test.tsx tests/members.test.tsx`
Expected: PASS toàn bộ — `members.test.tsx` và các test trong `user-admin.test.tsx` dùng `chiCoDanhSachUser()` đều tự override `/api/v1/members` riêng, không phụ thuộc handler mặc định vừa sửa.

- [ ] **Step 6: Commit**

```bash
git add src/lib/msw/handlers.ts tests/vai-tro.test.tsx
git commit -m "fix: nối GET /api/v1/members với USERS_GIA thay vì fake tĩnh rời"
```

---

### Task 2: Tab plumbing — `tabUsers.ts`, container `UserAdmin`, route `/users` + `/roles`

**Files:**
- Create: `src/features/auth/tabUsers.ts`
- Modify: `src/features/auth/components/UserAdmin.tsx` (đổi tên hàm export cũ, thêm hàm export mới)
- Modify: `src/routes/_app/users.tsx`
- Modify: `src/routes/_app/roles.tsx`
- Test: `tests/user-admin.test.tsx`

**Interfaces:**
- Produces: `TenTabUsers = 'thanh-vien' | 'vai-tro'`, `TAB_USERS: readonly MucTab<TenTabUsers>[]`, `tabHopLe(tho: unknown): TenTabUsers` (từ `tabUsers.ts`)
- Produces: `UserAdmin({ tab }: { tab: TenTabUsers })` — export mới, tab container
- Consumes (không đổi): `NoiDungThanhVien()` (không props, đổi tên từ `UserAdmin()` cũ), `DanhSachVaiTro` (từ `./DanhSachVaiTro`, không đổi)

- [ ] **Step 1: Viết test cho tab bar + redirect (thêm vào `tests/user-admin.test.tsx`, sau `describe('màn /users...')`)**

```ts
describe('gộp Users + Roles — tab Thành viên & Phân quyền', () => {
  it('mặc định mở tab Thành viên, owner thấy bảng tổ chức ngay', async () => {
    chiCoDanhSachUser([OWNER_HANG])
    boot('/users')

    expect(await screen.findByRole('tab', { name: 'Thành viên', selected: true })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vai trò', selected: false })).toBeInTheDocument()
    expect(await screen.findByText('Người dùng của tổ chức')).toBeInTheDocument()
  })

  it('bấm tab Vai trò thì đổi sang màn vai trò, giữ đúng khuôn ?tab=', async () => {
    chiCoDanhSachUser([OWNER_HANG])
    boot('/users')

    await userEvent.click(await screen.findByRole('tab', { name: 'Vai trò' }))

    expect(await screen.findByText('Vai trò của tổ chức')).toBeInTheDocument()
    expect(screen.queryByText('Người dùng của tổ chức')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vai trò', selected: true })).toBeInTheDocument()
  })

  it('/roles redirect sang /users và mở sẵn tab Vai trò', async () => {
    boot('/roles')

    expect(await screen.findByText('Vai trò của tổ chức')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vai trò', selected: true })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `npx vitest run tests/user-admin.test.tsx -t "gộp Users"`
Expected: FAIL — chưa có `role="tab"` nào (chưa có `NhomTab`), `/roles` còn render `DanhSachVaiTro` trực tiếp không qua `/users`.

- [ ] **Step 3: Tạo `src/features/auth/tabUsers.ts`**

```ts
/**
 * Hai tab của màn `/users` — Thành viên · Vai trò (gộp từ `/users` + `/roles`
 * cũ, 2026-08-06). FILE RIÊNG, không nằm cạnh `UserAdmin.tsx`: `routes/_app/
 * users.tsx` cần `tabHopLe()` lúc `validateSearch`, TRƯỚC khi render bất cứ gì —
 * cùng lý lẽ `features/realestate/tabDuAn.ts` (import một module có JSX chỉ để
 * lấy một hàm thuần thì Vite nạp lại cả trang mỗi lần sửa, eslint
 * `react-refresh/only-export-components` cảnh báo đúng).
 */
import type { MucTab } from '@/components/ui/Bang'

export type TenTabUsers = 'thanh-vien' | 'vai-tro'

export const TAB_USERS: readonly MucTab<TenTabUsers>[] = [
  { id: 'thanh-vien', nhan: 'Thành viên' },
  { id: 'vai-tro', nhan: 'Vai trò' },
]

/**
 * `?tab=xyz` → tab hợp lệ. Về ĐẦU (Thành viên) chứ không ném lỗi — `?tab=`
 * rỗng hoặc `?tab=xyz` lạ đến từ URL người dùng sửa tay hoặc link cũ, và ném
 * lỗi ở `validateSearch` làm cả màn không render.
 */
export function tabHopLe(tho: unknown): TenTabUsers {
  return TAB_USERS.some((t) => t.id === tho) ? (tho as TenTabUsers) : 'thanh-vien'
}
```

- [ ] **Step 4: Sửa `src/features/auth/components/UserAdmin.tsx`**

Đổi import (thêm `useNavigate`, `NhomTab`, `DanhSachVaiTro`, `TAB_USERS`/`TenTabUsers`):

```tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useSession } from '@/lib/session'
import {
  Bang,
  ChanBang,
  DauBang,
  Hang,
  NEN_PILL,
  NUT_CHINH,
  NUT_HANG,
  NUT_HANG_XOA,
  NUT_PHU,
  NhomTab,
  O_LOC,
  PILL,
  TD,
  TD_PHU,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { KhoRong } from '@/components/ui/TrangThai'
import { DongTrangThai } from '@/components/ui/Truong'
import {
  LoiApi,
  moiLai,
  taiChiTietUser,
  taiDanhSachUser,
  urlMoiTuyetDoi,
  xoaUser,
  type Lifecycle,
  type OrgRole,
  type UserListItem,
} from '../api'
import { MAU_LIFECYCLE, NHAN_LIFECYCLE, NHAN_ORG_ROLE } from '../nhan'
import { TAB_USERS, type TenTabUsers } from '../tabUsers'
import { DanhSachVaiTro } from './DanhSachVaiTro'
import { MemberList } from './MemberList'
import { UserForm } from './UserForm'
```

Đổi dòng khai báo hàm export cũ — TỪ:

```tsx
export function UserAdmin() {
```

THÀNH (bỏ `export`, đổi tên; phần THÂN HÀM giữ nguyên y hệt phía dưới, không đổi gì khác trong thân):

```tsx
function NoiDungThanhVien() {
```

Ngay TRƯỚC dòng đó (trước `function NoiDungThanhVien() {`), thêm hàm export mới:

```tsx
/**
 * Container 2 tab của `/users` — Thành viên (`NoiDungThanhVien`, đổi tên từ
 * `UserAdmin` cũ) · Vai trò (`DanhSachVaiTro`, gộp từ route `/roles` cũ).
 *
 * TAB Ở SEARCH PARAM, không `useState` — cùng lý lẽ `DuAnForm`/`routes/_app/
 * pform.tsx`: URL là nguồn sự thật duy nhất, deep-link/back-forward/refresh
 * đều mở đúng tab. Xem `../tabUsers.ts`.
 *
 * `NhomTab` render KHÔNG PHỤ THUỘC trạng thái con (`man` bên trong
 * `NoiDungThanhVien` hay bên trong `DanhSachVaiTro`) — đang giữa lúc tạo/sửa
 * vẫn nhảy tab được, và bản nháp mất đi. Đó KHÔNG phải hồi quy: trước khi gộp,
 * cùng thao tác đó là bấm sang mục nav `/roles` — cũng mất y hệt.
 *
 * CHỈ `pt-6`, không `py-6`: `NoiDungThanhVien` và `DanhSachVaiTro` đều tự mở
 * đầu bằng `px-7 py-6`. Thêm `pb` ở đây là cộng dồn hai lần khoảng trắng dưới
 * hàng tab.
 */
export function UserAdmin({ tab }: { tab: TenTabUsers }) {
  const nav = useNavigate()
  // `replace: true` — đổi tab KHÔNG để lại một mục lịch sử, cùng lý lẽ
  // `DuAnForm.doiTab` (`features/realestate/components/DuAnForm.tsx`).
  const doiTab = (id: TenTabUsers) =>
    void nav({ to: '/users', search: id === 'thanh-vien' ? {} : { tab: id }, replace: true })

  return (
    <>
      <div className="px-7 pt-6">
        <NhomTab muc={TAB_USERS} dangMo={tab} doi={doiTab} />
      </div>
      {tab === 'thanh-vien' ? <NoiDungThanhVien /> : <DanhSachVaiTro />}
    </>
  )
}

```

Sửa docstring đầu file (dòng 1-29) — đoạn nói về `<h1>`/nhãn nav (dòng 25-28 hiện tại: *"KHÔNG CÓ `<h1>` Ở ĐÂY... `<h1>Users & Phân quyền</h1>`..."*) đang trỏ tới nhãn CŨ. Sửa lại:

```
 * KHÔNG CÓ `<h1>` Ở ĐÂY. `components/shell/Topbar.tsx` đã render
 * `<h1>Thành viên & Phân quyền</h1>` lấy từ nav label (MỘT nav item cho cả hai
 * tab — xem `../nav.ts`). Bản trước có thêm `<h1>Người dùng & phân quyền</h1>`
 * ở đây, tức HAI tiêu đề cấp một cho một màn; đã bỏ.
```

- [ ] **Step 5: Sửa `src/routes/_app/users.tsx`**

Thay toàn bộ file:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { UserAdmin } from '@/features/auth/components/UserAdmin'
import { tabHopLe, type TenTabUsers } from '@/features/auth/tabUsers'

// M2a render `MemberList` (chỉ-đọc, phạm vi workspace). M2b thay bằng `UserAdmin`
// — phạm vi TỔ CHỨC, có tạo/sửa/mời — và `UserAdmin` nhúng lại `MemberList` bên
// dưới nó. Hai bảng trả lời hai câu hỏi khác nhau; xem docstring của cả hai.
//
// Gộp Users+Roles (2026-08-06): `UserAdmin` giờ là container 2 tab. `?tab=
// vai-tro` mở tab Vai trò — cùng khuôn `?tab=` của `/pform`, xem `tabUsers.ts`.
// Tab mặc định (Thành viên) KHÔNG xuất hiện trong URL.
export const Route = createFileRoute('/_app/users')({
  validateSearch: (search: Record<string, unknown>): { tab?: TenTabUsers | undefined } => {
    const tab = tabHopLe(search.tab)
    return tab === 'thanh-vien' ? {} : { tab }
  },
  component: ManUsers,
})

function ManUsers() {
  const { tab } = Route.useSearch()
  return <UserAdmin tab={tab ?? 'thanh-vien'} />
}
```

- [ ] **Step 6: Sửa `src/routes/_app/roles.tsx`**

Thay toàn bộ file:

```tsx
import { createFileRoute, redirect } from '@tanstack/react-router'

// Gộp vào `/users` (tab Vai trò, 2026-08-06) — xem
// docs/superpowers/specs/2026-08-06-gop-man-users-roles-thanh-vien-phan-quyen-design.md
// §4. GIỮ file này (không xoá): `tests/nav-registry.test.ts` đối chiếu 1:1
// route file ↔ `lib/screens.ts`, và `roles` vẫn là một `Screen` hợp lệ ở đó
// (chỉ `inNav: false`). Redirect, không xoá route, để link/bookmark cũ không
// gặp 404 — cùng khuôn `routes/_app/index.tsx` (`/` → `/dashboard`).
export const Route = createFileRoute('/_app/roles')({
  beforeLoad: () => {
    throw redirect({ to: '/users', search: { tab: 'vai-tro' } })
  },
})
```

- [ ] **Step 7: Chạy lại test, xác nhận PASS**

Run: `npx vitest run tests/user-admin.test.tsx`
Expected: PASS toàn bộ (test cũ + 3 test mới ở Step 1)

- [ ] **Step 8: Chạy toàn bộ suite liên quan tới `/users`/`/roles`, xác nhận không hồi quy**

Run: `npx vitest run tests/vai-tro.test.tsx tests/boot.test.tsx tests/shell.test.tsx tests/nav-registry.test.ts`
Expected: PASS TOÀN BỘ. Ba điều đáng nghi nhưng vẫn xanh, kiểm lại nếu đỏ:
- `vai-tro.test.tsx` boot ở `/roles` (`renderManVaiTro`) → giờ redirect sang `/users?tab=vai-tro`, vẫn render `DanhSachVaiTro` nên mọi assertion cũ còn đúng.
- `boot.test.tsx` với `roles` mong đợi `'Vai trò của tổ chức'` — redirect vẫn cho ra đúng chuỗi đó.
- `shell.test.tsx` dựng router RIÊNG từ `screens.ts` với `ScreenStub`, không dùng file route thật → không bị ảnh hưởng.
`nav-registry.test.ts` cũng phải xanh: task này chưa động tới `nav-registry.ts`/`screens.ts` (Task 6 mới đụng).

- [ ] **Step 9: Commit**

```bash
git add src/features/auth/tabUsers.ts src/features/auth/components/UserAdmin.tsx src/routes/_app/users.tsx src/routes/_app/roles.tsx tests/user-admin.test.tsx
git commit -m "feat: gộp /users + /roles thành 2 tab trong cùng route /users"
```

---

### Task 3: Sửa vai trò inline an toàn ở bảng thành viên workspace

**Files:**
- Modify: `src/features/auth/components/MemberList.tsx`
- Modify: `src/features/auth/components/UserAdmin.tsx` (1 dòng — truyền prop mới cho `MemberList`)
- Test: `tests/user-admin.test.tsx`

**Interfaces:**
- Consumes: `taiChiTietUser`, `layDanhSachVaiTro`, `suaUser`, `khoaVaiTro`, `type MembershipIn` (đã có ở `../api`)
- Produces: `MemberList({ suaDuocVaiTro }: { suaDuocVaiTro?: boolean } = {})` — prop mới, mặc định `false` (giữ nguyên hành vi chỉ-đọc cho nhánh non-owner và cho `tests/members.test.tsx`)

- [ ] **Step 1: Viết test — happy path + test AN TOÀN (bug mất dữ liệu) (thêm vào `tests/user-admin.test.tsx`, trong describe `'gộp Users + Roles...'` ở Task 2)**

Sửa import từ `../src/features/auth/api` — file đã có sẵn dòng `import { layDanhSachVaiTro } from '../src/features/auth/api'` (dùng ở test ⑤/⑥). Thêm hai tên vào CÙNG dòng đó, không tạo dòng import trùng:

```ts
import { layDanhSachVaiTro, taiChiTietUser, taoUser } from '../src/features/auth/api'
```

Sửa import từ handlers — file đã có `import { FAKE_SESSION } from '../src/lib/msw/handlers'`. Thêm hai hàm reset vào CÙNG dòng:

```ts
import { FAKE_SESSION, RESET_USERS_GIA, RESET_VAI_TRO_GIA } from '../src/lib/msw/handlers'
```

Thêm `beforeEach` vào import vitest ở đầu file (`import { beforeEach, describe, expect, it } from 'vitest'`), rồi thêm hai test dưới đây vào describe `'gộp Users + Roles...'`, kèm `beforeEach` reset ĐẶT NGAY ĐẦU describe đó:

```ts
  // ⚠ HAI TEST DƯỚI ĐÂY DÙNG HẠ TẦNG MSW TOÀN CỤC (`USERS_GIA`/`VAI_TRO_GIA`),
  // KHÔNG dùng `chiCoDanhSachUser()` như các test ở describe trên — hàm đó
  // override `/api/v1/members` về `[]`, tức xoá sạch đúng cái bảng mà tính
  // năng sửa-vai-trò-inline sống trong đó. Hạ tầng toàn cục có trạng thái và
  // `taoUser` dưới đây ghi vào nó, nên phải reset để không rò sang test sau —
  // cùng khuôn `beforeEach` của `tests/vai-tro.test.tsx`.
  beforeEach(() => {
    RESET_USERS_GIA()
    RESET_VAI_TRO_GIA()
  })

it('sửa vai trò inline ở bảng thành viên workspace: đổi ĐÚNG người, ĐÚNG workspace', async () => {
  boot('/users')

  // `u_fake_lan` (seed toàn cục, xem handlers.ts) đang ở workspace hiện tại với
  // vai trò Quản trị — Task 1 đã nối `/api/v1/members` với đúng dữ liệu này.
  const oVaiTro = await screen.findByLabelText(/Vai trò của Nguyễn Thị Lan/)
  expect(oVaiTro).toHaveValue((await layDanhSachVaiTro()).find((v) => v.name === 'Quản trị')?.id)

  await userEvent.selectOptions(oVaiTro, 'Người xem')

  await waitFor(async () =>
    expect(oVaiTro).toHaveValue((await layDanhSachVaiTro()).find((v) => v.name === 'Người xem')?.id),
  )
})

it('sửa vai trò inline KHÔNG xoá mất vai trò của user đó ở workspace KHÁC', async () => {
  // Đây là bài test cho đúng bug đã phát hiện lúc review thiết kế: `suaUser`
  // PATCH thay TOÀN BỘ `memberships`. Một user ở 2 workspace, đổi vai trò ở
  // workspace hiện tại — workspace còn lại PHẢI giữ nguyên vai trò cũ.
  const vaiTro = await layDanhSachVaiTro()
  const vtQuanTri = vaiTro.find((v) => v.name === 'Quản trị')!
  const vtNguoiXem = vaiTro.find((v) => v.name === 'Người xem')!
  const vtTrong = vaiTro.find((v) => v.name === 'Trống')!
  const ws1 = FAKE_SESSION.workspaces[0]!.id // = currentWorkspaceId
  const ws2 = FAKE_SESSION.workspaces[1]!.id

  const { user } = await taoUser({
    email: '2ws@anphuland.vn',
    name: 'Hai Workspace',
    phone: null,
    jobTitle: null,
    orgRole: 'member',
    memberships: [
      { workspaceId: ws1, roleId: vtQuanTri.id, expiresAt: null },
      { workspaceId: ws2, roleId: vtNguoiXem.id, expiresAt: null },
    ],
  })

  boot('/users')
  const oVaiTro = await screen.findByLabelText(/Vai trò của Hai Workspace/)
  expect(oVaiTro).toHaveValue(vtQuanTri.id)

  await userEvent.selectOptions(oVaiTro, 'Trống')
  await waitFor(() => expect(oVaiTro).toHaveValue(vtTrong.id))

  const chiTiet = await taiChiTietUser(user.id)
  const ws1Sau = chiTiet.memberships.find((m) => m.workspaceId === ws1)
  const ws2Sau = chiTiet.memberships.find((m) => m.workspaceId === ws2)
  expect(ws1Sau?.role, 'workspace hiện tại phải đổi sang Trống').toBe('Trống')
  expect(ws2Sau?.role, 'workspace KHÁC không được đổi/mất — đây là bug đã phát hiện').toBe(
    'Người xem',
  )
})
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `npx vitest run tests/user-admin.test.tsx -t "sửa vai trò inline"`
Expected: FAIL — `findByLabelText(/Vai trò của .../)` không tìm thấy gì, `MemberList` chưa render dropdown.

- [ ] **Step 3: Sửa `src/features/auth/components/MemberList.tsx`**

Đổi import (thêm các hàm/kiểu cần cho mutation):

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bang,
  DauBang,
  Hang,
  O_LOC,
  PILL,
  TD,
  TD_PHU,
  TheBang,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { KhoRong } from '@/components/ui/TrangThai'
import { useSession } from '@/lib/session'
import {
  khoaVaiTro,
  layDanhSachVaiTro,
  LoiApi,
  suaUser,
  taiChiTietUser,
  type MembershipIn,
} from '../api'
```

Đổi dòng khai báo hàm export — TỪ:

```tsx
export function MemberList() {
```

THÀNH:

```tsx
export function MemberList({ suaDuocVaiTro = false }: { suaDuocVaiTro?: boolean } = {}) {
```

Trong khối render bảng (đoạn `<tbody>{data.map(...)}</tbody>`), đổi ô "Vai trò" — TỪ:

```tsx
                  <td className={TD_PHU}>
                    <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg`}>{m.role}</span>
                  </td>
```

THÀNH:

```tsx
                  <td className={TD_PHU}>
                    {suaDuocVaiTro ? (
                      <OVaiTroThanhVien m={m} />
                    ) : (
                      <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg`}>{m.role}</span>
                    )}
                  </td>
```

Thêm hàm mới ở CUỐI file (sau hàm `MemberList`, trước dòng đóng file):

```tsx
/**
 * Dropdown sửa vai trò NGAY TẠI DÒNG — chỉ hiện khi `MemberList` được nhúng ở
 * nhánh owner (`suaDuocVaiTro`, xem `UserAdmin.tsx`). Nhánh non-owner (đọc-only)
 * không truyền prop này, giữ nguyên hành vi cũ.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 *  AN TOÀN VỚI USER NHIỀU WORKSPACE — đây là điều kiện bắt buộc, không phải
 *  chi tiết cài đặt
 * ═══════════════════════════════════════════════════════════════════════════
 * `suaUser` PATCH thay TOÀN BỘ `ThanUser.memberships`, không cộng dồn (xem
 * docstring trường đó ở `api.ts`). Gọi nó với CHỈ một dòng (workspace hiện tại)
 * sẽ xoá sạch vai trò của user đó ở MỌI workspace khác — bug mất dữ liệu thật,
 * phát hiện lúc review thiết kế 2026-08-06. Nên: PHẢI `taiChiTietUser` lấy toàn
 * bộ `memberships` hiện có, chỉ thay ĐÚNG entry của workspace đang mở, giữ
 * nguyên mọi entry còn lại (khớp tên → id qua `vaiTroList`, cùng cách
 * `UserForm.tsx` đối chiếu ngược), rồi mới PATCH.
 */
function OVaiTroThanhVien({ m }: { m: MemberOut }) {
  const { session } = useSession()
  const queryClient = useQueryClient()
  const workspaceId = session.currentWorkspaceId

  const { data: vaiTroList } = useQuery({ queryKey: khoaVaiTro.tatCa, queryFn: layDanhSachVaiTro })

  const doi = useMutation({
    mutationFn: async (roleIdMoi: string) => {
      const chiTiet = await taiChiTietUser(m.userId)
      const list = vaiTroList ?? (await layDanhSachVaiTro())
      const memberships: MembershipIn[] = chiTiet.memberships.map((mm) =>
        mm.workspaceId === workspaceId
          ? { workspaceId, roleId: roleIdMoi, expiresAt: mm.expiresAt }
          : {
              workspaceId: mm.workspaceId,
              roleId: list.find((v) => v.name === mm.role)?.id ?? '',
              expiresAt: mm.expiresAt,
            },
      )
      return suaUser(m.userId, {
        name: chiTiet.name,
        phone: chiTiet.phone,
        jobTitle: chiTiet.jobTitle,
        orgRole: chiTiet.orgRole,
        memberships,
      })
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['members'] }),
  })

  if (!vaiTroList)
    return <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg`}>{m.role}</span>

  const hienTai = vaiTroList.find((v) => v.name === m.role)?.id ?? ''

  return (
    <div>
      <label className="sr-only" htmlFor={`vt-tv-${m.userId}`}>
        Vai trò của {m.name} tại workspace hiện tại
      </label>
      <select
        id={`vt-tv-${m.userId}`}
        value={hienTai}
        disabled={doi.isPending}
        onChange={(e) => doi.mutate(e.target.value)}
        className={`${O_LOC} disabled:opacity-60`}
      >
        {vaiTroList.map((v) => (
          <option key={v.id} value={v.id}>
            {v.name}
          </option>
        ))}
      </select>
      {doi.error && (
        <span role="alert" className="mt-1 block text-[11px] text-badge-alert-fg">
          {doi.error instanceof LoiApi ? doi.error.message : 'Không lưu được vai trò'}
        </span>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Sửa `src/features/auth/components/UserAdmin.tsx` — truyền prop mới**

Trong `NoiDungThanhVien` (hàm đổi tên ở Task 2), tìm dòng cuối cùng của phần "HAI BẢNG" — TỪ:

```tsx
        <MemberList />
```

THÀNH:

```tsx
        <MemberList suaDuocVaiTro />
```

- [ ] **Step 5: Chạy lại test, xác nhận PASS**

Run: `npx vitest run tests/user-admin.test.tsx tests/members.test.tsx`
Expected: PASS toàn bộ — `tests/members.test.tsx` vẫn xanh vì gọi `<MemberList />` không props (mặc định `suaDuocVaiTro=false`, giữ nguyên `<span>` chỉ-đọc).

- [ ] **Step 6: Commit**

```bash
git add src/features/auth/components/MemberList.tsx src/features/auth/components/UserAdmin.tsx tests/user-admin.test.tsx
git commit -m "feat: sửa vai trò inline an toàn ở bảng thành viên workspace"
```

---

### Task 4: Sửa chú thích lệch trong `DanhSachVaiTro.tsx`

**Files:**
- Modify: `src/features/auth/components/DanhSachVaiTro.tsx`

- [ ] **Step 1: Sửa dòng chú thích**

TỪ (dòng ~166):

```tsx
      <p className="mb-[18px] text-[13px] text-muted">
        Mỗi vai trò là một tập hành động — gán cho người dùng ở màn Users & Phân quyền.
      </p>
```

THÀNH:

```tsx
      <p className="mb-[18px] text-[13px] text-muted">
        Mỗi vai trò là một tập hành động — gán ngay tại bảng ở tab Thành viên.
      </p>
```

- [ ] **Step 2: Chạy test liên quan, xác nhận không đỏ**

Run: `npx vitest run tests/vai-tro.test.tsx`
Expected: PASS (không có test nào assert đúng chuỗi cũ, xác nhận bằng grep trước khi sửa nếu còn nghi ngờ: `grep -n "Users & Phân quyền" tests/`)

- [ ] **Step 3: Commit**

```bash
git add src/features/auth/components/DanhSachVaiTro.tsx
git commit -m "docs: sửa chú thích gán vai trò trỏ đúng chỗ sau khi gộp tab"
```

---

### Task 5: Xoá enum vai trò chết (`VaiTro`/`NHAN_VAI_TRO`/`VAI_TRO_THEO_THU_TU`)

**Files:**
- Modify: `src/features/auth/api.ts`
- Modify: `src/features/auth/nhan.ts`

- [ ] **Step 1: Xác nhận không còn nơi nào dùng (đã kiểm lúc lên plan, kiểm lại cho chắc)**

Run: `grep -rnE "\bVaiTro\b" src tests | grep -Ev "VaiTroToChuc|VaiTroChiTiet|FormVaiTro|DanhSachVaiTro|khoaVaiTro|renderManVaiTro|xoaVaiTro|taoVaiTro|suaVaiTro|layVaiTro|layDanhSachVaiTro|RESET_VAI_TRO_GIA|VAI_TRO_GIA|VAI_TRO_THEO_THU_TU|ACTIONS_GIA"`
Expected: chỉ còn các dòng COMMENT (không phải code sống) trong `api.ts`/`MemberList.tsx` nhắc tới `VaiTro` như bối cảnh lịch sử — không sửa các comment đó, chỉ xoá phần khai báo type/const thật.

- [ ] **Step 2: Xoá trong `src/features/auth/api.ts`**

Xoá NGUYÊN đoạn (dòng 66-81, cả docstring và khai báo type — docstring này chỉ tồn tại để giải thích "vì sao đừng dùng lại", nên xoá cùng với type):

```ts
/**
 * `memberships.role` — quyền TRONG một workspace. KHÔNG có `owner` ở đây.
 *
 * ⚠ CHẾT Ở MIGRATION 0104 (spec 2026-08-04 phan-quyen-dong §4.0). Bốn mã cố
 * định này từng là 1-trong-4, nhưng vai trò trong một workspace giờ neo vào
 * `control.roles` của tổ chức (cùng bảng mà màn `/roles` quản — xem
 * `VaiTroToChuc` dưới) — mỗi tổ chức tự định nghĩa vai trò của mình, không còn
 * đúng bốn cái cho mọi tổ chức. `GET /api/v1/members` (M2a, `MemberList.tsx`)
 * cũng đã đổi theo: nó JOIN qua `role_id` và trả TÊN vai trò (`r.name AS role`,
 * `repo.py liet_ke_thanh_vien`) — một chuỗi tự do, không còn `VaiTro` bốn-mã.
 * Kiểu này (và `NHAN_VAI_TRO`/`VAI_TRO_THEO_THU_TU` ở `nhan.ts` dịch nó) giờ
 * không còn nơi nào tiêu thụ — ĐỪNG dùng lại nó cho membership của
 * `UserForm`/`MembershipIn` bên dưới, và đừng gán nó cho bất cứ trường trả về
 * từ API nào nữa: mọi vai trò trả từ backend giờ là tên tự do.
 */
export type VaiTro = 'admin' | 'care' | 'editor' | 'viewer'

```

(Giữ nguyên dòng blank sau đó và `export type OrgRole = 'owner' | 'member'` đứng ngay sau.)

- [ ] **Step 3: Xoá trong `src/features/auth/nhan.ts`**

Đổi dòng import — TỪ:

```ts
import type { ActionInfo, Lifecycle, OrgRole, VaiTro } from './api'
```

THÀNH:

```ts
import type { ActionInfo, Lifecycle, OrgRole } from './api'
```

Xoá đoạn (dòng 14-22):

```ts
/** PQ_01 §2.4 — bốn vai trò TRONG một workspace. */
export const NHAN_VAI_TRO: Record<VaiTro, string> = {
  admin: 'Quản trị',
  care: 'CSKH',
  editor: 'Biên tập',
  viewer: 'Người xem',
}

export const VAI_TRO_THEO_THU_TU: readonly VaiTro[] = ['admin', 'care', 'editor', 'viewer']

```

- [ ] **Step 4: Chạy typecheck + toàn bộ test**

Run: `npx tsc --noEmit && npx vitest run`
Expected: PASS — không còn tham chiếu nào tới ba tên vừa xoá.

- [ ] **Step 5: Commit**

```bash
git add src/features/auth/api.ts src/features/auth/nhan.ts
git commit -m "chore: xoá enum vai trò chết VaiTro/NHAN_VAI_TRO/VAI_TRO_THEO_THU_TU"
```

---

### Task 6: Gộp nav — `nav.ts`, `nav-registry.ts`, `screens.ts` + test

**Files:**
- Modify: `src/features/auth/nav.ts`
- Modify: `src/lib/nav-registry.ts`
- Modify: `src/lib/screens.ts`
- Modify: `tests/nav-registry.test.ts`
- Modify: `tests/shell.test.tsx`

**Interfaces:**
- Produces: `usersNav: NavLeaf` (label đổi, `rolesNav` bị xoá khỏi export)

- [ ] **Step 1: Sửa test TRƯỚC (nav-registry.test.ts) — xác nhận chúng phản ánh đúng thiết kế mới**

Trong `tests/nav-registry.test.ts`:

Xoá `'roles'` khỏi `PROTOTYPE_SIDEBAR_ORDER` (dòng 21-37) — TỪ:

```ts
const PROTOTYPE_SIDEBAR_ORDER = [
  'dashboard',
  'convos',
  'appts',
  'quality',
  'projects',
  'finance',
  'domains',
  'kb',
  'gaps',
  'agent',
  'api',
  'users',
  'roles',
  'audit',
  'billing',
] as const
```

THÀNH:

```ts
const PROTOTYPE_SIDEBAR_ORDER = [
  'dashboard',
  'convos',
  'appts',
  'quality',
  'projects',
  'finance',
  'domains',
  'kb',
  'gaps',
  'agent',
  'api',
  'users',
  'audit',
  'billing',
] as const
```

Sửa test "4 màn ngoài sidebar" (dòng 110-113) — TỪ:

```ts
  it('4 màn ngoài sidebar vẫn có route: pform · uform · settings · onboarding', async () => {
    const notInNav = SCREENS.filter((s) => !s.inNav).map((s) => s.key)
    expect(notInNav.sort()).toEqual(['onboarding', 'pform', 'settings', 'uform'])
  })
```

THÀNH:

```ts
  it('5 màn ngoài sidebar vẫn có route: pform · roles · settings · uform · onboarding', async () => {
    // `roles` gộp vào `/users` (tab Vai trò, 2026-08-06) — route vẫn tồn tại
    // (redirect), chỉ không còn là mục sidebar riêng. Xem spec
    // docs/superpowers/specs/2026-08-06-gop-man-users-roles-thanh-vien-phan-quyen-design.md §4.
    const notInNav = SCREENS.filter((s) => !s.inNav).map((s) => s.key)
    expect(notInNav.sort()).toEqual(['onboarding', 'pform', 'roles', 'settings', 'uform'])
  })
```

XOÁ HOÀN TOÀN test (dòng 115-126, premise của nó — `roles` là một NAV entry — không còn đúng):

```ts
  it('`roles` nằm trong nhóm Cấu hình, ngay sau `users`, và đòi WORKSPACE_ADMIN', () => {
    const nhomCauHinh = NAV.find((g) => g.label.vi === 'Cấu hình')
    expect(nhomCauHinh).toBeDefined()
    const keys = nhomCauHinh?.entries.map((e) => e.key) ?? []
    const iUsers = keys.indexOf('users')
    const iRoles = keys.indexOf('roles')
    expect(iRoles, 'roles phải có trong nhóm Cấu hình').toBeGreaterThan(-1)
    expect(iRoles).toBe(iUsers + 1)

    const roles = nhomCauHinh?.entries.find((e) => e.key === 'roles')
    expect(roles?.requiredActions).toContain(ACTIONS.WORKSPACE_ADMIN)
  })
```

Trong `tests/shell.test.tsx` dòng 143 — TỪ:

```ts
    expect(nav.queryByText('Users & Phân quyền')).not.toBeInTheDocument()
```

THÀNH:

```ts
    expect(nav.queryByText('Thành viên & Phân quyền')).not.toBeInTheDocument()
```

- [ ] **Step 2: Chạy test, xác nhận FAIL đúng chỗ**

Run: `npx vitest run tests/nav-registry.test.ts tests/shell.test.tsx`
Expected: FAIL — `NAV` vẫn còn `rolesNav`, `usersNav.label.vi` vẫn `'Users & Phân quyền'`, `screens.ts` vẫn `roles.inNav: true`.

- [ ] **Step 3: Sửa `src/features/auth/nav.ts`**

Thay toàn bộ file:

```ts
/**
 * Nav của M2a — Auth · Workspace · App shell. Sở hữu: users.
 * Spec tổng §2, §4⑤.
 *
 * Màn `users`: M2a làm danh sách, M2b làm đổi vai trò + mời (PQ_01 §3.2). Gộp
 * với `/roles` cũ thành 2 tab trong cùng route (2026-08-06) — xem
 * docs/superpowers/specs/2026-08-06-gop-man-users-roles-thanh-vien-phan-quyen-design.md.
 * `rolesNav` (nav item riêng cho `/roles`) đã BỎ — không còn export ở đây.
 */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const usersNav: NavLeaf = {
  kind: 'leaf',
  key: 'users',
  path: '/users',
  label: { vi: 'Thành viên & Phân quyền', en: 'Members & permissions' },
  icon: 'users',
  // Nhóm 13 — Thành viên nằm cùng Khoá API · Cài đặt workspace.
  // PQ_01 Q06: không đọc được bảng thành viên thì TỪ CHỐI, không trả rỗng.
  requiredActions: [ACTIONS.WORKSPACE_ADMIN],
}
```

- [ ] **Step 4: Sửa `src/lib/nav-registry.ts`**

Đổi import — TỪ:

```ts
import { rolesNav, usersNav } from '@/features/auth/nav'
```

THÀNH:

```ts
import { usersNav } from '@/features/auth/nav'
```

Đổi dòng entries của nhóm "Cấu hình" — TỪ:

```ts
    entries: [agentNav, apiNav, usersNav, rolesNav, auditNav, billingNav],
```

THÀNH:

```ts
    entries: [agentNav, apiNav, usersNav, auditNav, billingNav],
```

- [ ] **Step 5: Sửa `src/lib/screens.ts`**

Đổi dòng `roles` (dòng 105) — TỪ:

```ts
  { key: 'roles', path: '/roles', owner: 'M2b', mvp: 'full', inNav: true },
```

THÀNH:

```ts
  {
    key: 'roles',
    path: '/roles',
    owner: 'M2b',
    mvp: 'full',
    inNav: false,
    note: 'Gộp vào /users (tab Vai trò, 2026-08-06) — route giữ lại làm redirect',
  },
```

- [ ] **Step 6: Chạy lại toàn bộ test, xác nhận PASS**

Run: `npx vitest run`
Expected: PASS TOÀN BỘ suite.

- [ ] **Step 7: Commit**

```bash
git add src/features/auth/nav.ts src/lib/nav-registry.ts src/lib/screens.ts tests/nav-registry.test.ts tests/shell.test.tsx
git commit -m "feat: bỏ mục nav riêng cho Roles, gộp vào Thành viên & Phân quyền"
```

**Ghi chú — thứ CỐ Ý không đổi ở task này:** `UserForm.tsx` dòng ~440 còn
`<Link to="/roles">Tạo vai trò</Link>` (nhánh "chưa có vai trò nào"), và
`tests/vai-tro.test.tsx` test ⑧ assert `href === '/roles'`. Giữ nguyên: route
`/roles` vẫn tồn tại và redirect đúng chỗ, nên link hoạt động; đổi nó thành
`/users?tab=vai-tro` là đổi thêm một file + một test cho không thêm hành vi
nào. Spec §6 cũng ghi `UserForm` không đổi.

---

### Task 7: Xác nhận cuối — `make check` + rà lại diff

- [ ] **Step 1: Chạy cổng CI đầy đủ**

Run: `make check`
Expected: PASS (lint + test). Nếu `make lint` đỏ ở đúng 5 file nợ định dạng đã biết trước (`MemberList.tsx` · `TaoKhoaDialog.tsx` · `TichHopApiScreen.tsx` · `khoa-dau-noi.test.tsx` · `vai-tro.test.tsx` — xem CLAUDE.md gotcha) — với `MemberList.tsx` và `vai-tro.test.tsx` CỤ THỂ (2 trong 5 file này bị task này sửa nội dung thật), chạy `npx prettier --write` đúng hai file đó (không chạm 3 file còn lại, chúng không liên quan tới task này).

- [ ] **Step 2: `git status` — không còn thay đổi chưa commit**

Run: `git status --short`
Expected: rỗng (mọi thay đổi đã commit ở 6 task trước).

- [ ] **Step 3: Rà lại toàn bộ diff một lượt cho khớp spec**

Run: `git log --oneline -7` rồi `git diff origin/<branch-gốc>...HEAD --stat` (hoặc nhánh chính của repo) để xem tổng số file đổi — đối chiếu với bảng §6 của spec, xác nhận không thiếu/thừa file nào.

