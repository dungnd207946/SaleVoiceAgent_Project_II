### Task 1: Khai báo màn — 4 việc, cổng `nav-registry` canh

**Files:**
- Modify: `src/lib/actions.ts`
- Modify: `src/lib/screens.ts`
- Create: `src/features/billing/nav.ts`
- Modify: `src/lib/nav-registry.ts`
- Create: `src/routes/_app/pricing.tsx`
- Modify: `src/routes/_app/usage.tsx`
- Modify: `src/features/deferred/nav.ts` (bỏ `usageNav`/`billingNav`)
- Test: `tests/nav-registry.test.ts` (sửa hằng)

**Interfaces:**
- Produces: `ACTIONS.BILLING_READ = 'billing.read'` · `usageNav`/`billingNav`/`pricingNav` từ `features/billing/nav.ts`

- [ ] **Step 1: Chạy suite để có mốc baseline**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -5`
Expected: ghi lại con số (dự kiến 1 fail ở `convos-phien.test.tsx`). **Đây là mốc so — mọi con số sau task này phải đối chiếu vào đây.**

- [ ] **Step 2: Thêm action**

Trong `src/lib/actions.ts`, thêm vào object `ACTIONS`:

```ts
  BILLING_READ: 'billing.read',
```

⚠️ `tests/actions-parity.test.ts` so `lib/actions.ts` với `contracts/actions.json`. Nếu cổng đỏ vì thiếu `billing.read` trong JSON: **copy lại `contracts/actions.json` từ backend** (`make contracts` bên đó rồi copy tay). ĐỪNG sửa `contracts/actions.json` bằng tay.

- [ ] **Step 3: Viết `features/billing/nav.ts`**

```ts
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

/**
 * Ba màn của khối «Chi phí». Tách khỏi `features/deferred/nav.ts`: hai màn
 * `usage`/`billing` từng nằm ở đó với `requiredActions: [WORKSPACE_ADMIN]` —
 * SAI so với backend, vốn gác 5 endpoint bằng `billing.read`. Hai bộ điều kiện
 * khác nhau cho cùng một màn là lỗi im lặng theo CẢ HAI chiều: role có
 * `billing.read` mà không phải workspace admin thì không thấy nav dù API trả
 * 200; workspace admin không có `billing.read` thì thấy nav rồi ăn 403.
 */
export const usageNav: NavLeaf = {
  kind: 'leaf',
  key: 'usage',
  path: '/usage',
  label: { vi: 'Lượt dùng', en: 'Usage' },
  icon: 'usage',
  requiredActions: [ACTIONS.BILLING_READ],
}

export const billingNav: NavLeaf = {
  kind: 'leaf',
  key: 'billing',
  path: '/billing',
  label: { vi: 'Hoá đơn', en: 'Invoices' },
  icon: 'billing',
  requiredActions: [ACTIONS.BILLING_READ],
}

/**
 * `/pricing` gác bằng `BILLING_READ` ở tầng nav, nhưng 6 endpoint admin của nó
 * xác thực bằng header `X-Platform-Admin-Token`, KHÔNG bằng phiên. Nghĩa là mục
 * này hiện cho người có `billing.read` nhưng chỉ DÙNG ĐƯỢC nếu có token nền
 * tảng — màn tự nói điều đó ở dải đầu trang (Task 8), không giấu.
 */
export const pricingNav: NavLeaf = {
  kind: 'leaf',
  key: 'pricing',
  path: '/pricing',
  label: { vi: 'Bảng giá', en: 'Pricing' },
  icon: 'pricing',
  requiredActions: [ACTIONS.BILLING_READ],
}
```

⚠️ Đọc `src/lib/nav-types.ts` để lấy ĐÚNG hình dạng `NavLeaf` (trường `kind`, tên trường icon) trước khi copy khối trên — đừng tin nguyên văn nếu kiểu đã đổi.

- [ ] **Step 4: Thêm icon**

`src/components/icons.tsx` — thêm 3 khoá vào `LUCIDE`: `usage` → `Activity`, `billing` → `ReceiptText`, `pricing` → `Tags`. Dùng nhánh `LUCIDE` chứ không vẽ tay: repo đã chốt 2026-08-08 rằng vẽ tay theo ảnh chụp ra icon *gần giống*, và gần giống là lựa chọn tệ nhất. `Icon` tự ép `strokeWidth 1.92`.

- [ ] **Step 5: Nối vào nav-registry**

Trong `src/lib/nav-registry.ts`: đổi import `billingNav, usageNav` từ `@/features/deferred/nav` sang `@/features/billing/nav`, thêm `pricingNav`, và thêm một `khoi()` có nhãn «Chi phí» vào `segments` của nhóm `Quản trị`:

```ts
      khoi(usageNav, billingNav, pricingNav),
```

⚠️ Đọc chữ ký `khoi()` trong `nav-types.ts` — khối CÓ NHÃN dùng dạng khác khối không nhãn. Nhãn khối: `{ vi: 'Chi phí', en: 'Cost' }`.

- [ ] **Step 6: `screens.ts`**

`usage`: `mvp: 'deferred'` → `'full'`, xoá `note`.
`billing`: giữ `mvp: 'deferred'`, đổi `note` thành `'Hoá đơn — bản vẽ đã duyệt, chờ endpoint GET /billing/invoices. Số chi phí đã có ở /usage.'`
Thêm dòng mới: `{ key: 'pricing', path: '/pricing', owner: 'M9', mvp: 'full', inNav: true }` — đọc `MODULES` để chọn `owner` đúng, đừng bịa mã module.

- [ ] **Step 7: Route `/pricing`**

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { BangGiaScreen } from '@/features/billing/contracts'

export const Route = createFileRoute('/_app/pricing')({
  component: BangGiaScreen,
})
```

Tạm để `BangGiaScreen` là một component rỗng trong `contracts.ts` để route biên dịch được; Task 8 thay nội dung.

- [ ] **Step 8: `make routes` + chạy cổng nav**

Run: `npx tsr generate && NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/nav-registry.test.ts`
Expected: đỏ ở `RAIL_ORDER`/`PROTOTYPE_SCREENS`/danh sách hoãn. Sửa các hằng trong CHÍNH file test đó cho khớp (mảng `Quản trị` nay có 3 mục mới; danh sách hoãn bớt `usage`).

- [ ] **Step 9: Xanh lại + kiểm không hồi quy**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -5`
Expected: cùng con số fail như Step 1, không thêm. `routeTree.gen.ts` bẩn prettier là **bình thường** (tệp sinh).

- [ ] **Step 10: Commit**

```bash
git add src/lib/actions.ts src/lib/screens.ts src/lib/nav-registry.ts \
        src/features/billing/nav.ts src/features/billing/contracts.ts \
        src/features/deferred/nav.ts src/components/icons.tsx \
        src/routes/_app/pricing.tsx src/routeTree.gen.ts tests/nav-registry.test.ts
git commit -m "feat(billing): khối nav «Chi phí» + action billing.read"
```

---

