# Odyssey Portal — Frontend

Giao diện của Odyssey Portal, control plane cho SaaS agent chăm sóc khách hàng của NobleX.

> **Repo này là frontend.** Backend ở
> [odyssey-portal-backend](https://gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/odyssey-project/odyssey-portal-backend) — nơi có **bản đồ 9 module**, **bốn luật
> không được phá**, và tech stack. Hai repo tách từ `odyssey-portal-fullstack` ngày 2026-07-30;
> history 29 commit thời monorepo còn ở đó (đã archive).

**Tài liệu đọc trước:** [kiến trúc & bản đồ module](docs/superpowers/specs/2026-07-29-odyssey-portal-kien-truc-va-ban-do-module.md)
· [18 màn đối chiếu](docs/product/2026-07-28-phan-bien-prototype-va-dinh-huong-san-pham.md)
· [PQ_01 phân quyền](docs/product/2026-07-29-pq01-phan-quyen.md)

---

## App shell (M2a-FE)

App shell của Odyssey Portal: **menu · route · design token · phiên giả**. 18 màn đã có route, cả
18 đều **trống** — nội dung do module sở hữu dựng.

Đây là base chung. Đọc hết file này một lần (5 phút) trước khi viết dòng đầu tiên.

## Chạy

```bash
make install     # npm ci
make dev         # http://localhost:5173
```

**Không cần backend chạy.** MSW trả `GET /api/v1/me` bằng một user giả + 3 workspace giả + đủ 13
quyền, nên mọi mục menu hiện ra. Tắt MSW để dùng backend thật: `VITE_MSW=0`.

```bash
make lint        # eslint + prettier + tsc
make test        # vitest
make build       # build production (MSW bị loại khỏi bundle)
```

**Không sửa** `components/shell/*`. Không sửa route của người khác. Không đổi
`lib/nav-registry.ts` trừ khi đổi nhãn menu.

## Thêm một màn MỚI vào sidebar

Ba việc, không có việc thứ tư:

| # | File | Làm gì |
|---|---|---|
| 1 | `src/features/<module>/nav.ts` | khai `NavLeaf` — **phải có `requiredActions`** |
| 2 | `src/lib/nav-registry.ts` | thêm một dòng vào đúng nhóm (hoặc `OFF_NAV` nếu không có mục nav) |
| 3 | `src/routes/_app/<path>.tsx` | route mới, rồi `make routes` |

Quên bước nào ⇒ `tests/nav-registry.test.ts` đỏ. Đó là chủ ý: "sidebar khớp thiết kế" phải là thứ
CI kiểm được, không phải lời hứa.

Nếu bạn thấy mình đang sửa `Sidebar.tsx` để thêm một màn — dừng lại. Nghĩa là `NavLeaf` thiếu một
trường. Thêm trường vào `lib/nav-types.ts`, đừng đặc-biệt-hoá trong Sidebar.

## Ranh giới module

`features/<a>` chỉ được import: `features/<a>/…` · `lib/…` · `components/…` · `i18n/…`.

Cần thứ của module khác ⇒ import `features/<b>/contracts` — mặt tiền công khai của nó. Import ruột
module khác ⇒ **CI đỏ** (`tests/module-boundaries.test.ts`). Đây là bản FE của Luật 3 ở [README repo backend](https://gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/odyssey-project/odyssey-portal-backend).

Ngoại lệ duy nhất: `lib/nav-registry.ts` — chỗ được thiết kế để gom nav của mọi module.

## Quyền

`requiredActions` trên mỗi nav item dùng hằng ở `lib/actions.ts` (13 nhóm của PQ_01 §3.1).

> ⚠️ **Ẩn nút KHÔNG phải bảo vệ** (PQ_01 §BR-Q03). Sidebar ẩn mục người dùng không có quyền chỉ để
> đỡ rối mắt. Mọi quyền **phải** kiểm ở tầng API bằng `require(action)`. Ai bỏ check ở API vì "nav
> đã ẩn rồi" là đang tạo lỗ hổng.

Tên action ở `lib/actions.ts` là **đề xuất, chưa chốt** — M2b chốt tên thật, cùng lúc với
`require()` ở backend. Vì mọi chỗ tham chiếu `ACTIONS.*` nên lúc đổi chỉ sửa một file.

Thử giao diện của vai trò hẹp hơn: sửa `actions` trong `lib/msw/handlers.ts`, hoặc `server.use(...)`
trong test (xem `tests/shell.test.tsx`).

## Cấu trúc

```
src/
├─ routes/               TanStack Router file-based
│  ├─ __root.tsx         mỏng — provider ở main.tsx
│  ├─ _app.tsx           layout: Sidebar + Topbar  ← M2a-BE cắm chặn-chưa-đăng-nhập vào beforeLoad
│  └─ _app/*.tsx         18 màn, mỗi file 6 dòng
├─ components/
│  ├─ shell/             Sidebar · NavItem · WorkspaceSwitcher · LangToggle · Topbar
│  └─ icons.tsx          15 icon copy đúng path SVG từ prototype
├─ features/<module>/    nav.ts hôm nay; code màn về sau
├─ lib/
│  ├─ nav-registry.ts    chỗ DUY NHẤT gom nav
│  ├─ nav-types.ts       NavLeaf · NavParent · NavGroup
│  ├─ actions.ts         13 nhóm quyền của PQ_01
│  ├─ session.ts         seam phiên — M2a-BE thay ruột
│  └─ msw/               fake data
├─ i18n/                 VI mặc định, EN thứ hai
└─ styles/theme.css      design token (spec §6.3) + font tự host
```

## Ba chỗ M2a-BE phải làm tiếp

| Chỗ | Việc |
|---|---|
| `routes/_app.tsx` `beforeLoad` | chặn chưa-đăng-nhập — **một** chỗ, không phải 18 chỗ |
| `lib/session.tsx` | thay MSW bằng `GET /api/v1/me` thật; giữ nguyên hình dạng `Session` |
| `WorkspaceSwitcher` | đổi workspace phải là request thật **và** phải xoá cache query của workspace cũ — không thì người dùng thấy dữ liệu workspace trước trong workspace sau, đúng thứ hợp đồng cách ly tồn tại để chặn |

Và: dựng `require(action)` **cùng** check CI của nó, trong cùng một PR (Luật 4 ở [README repo backend](https://gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/odyssey-project/odyssey-portal-backend)).

## Prototype

Thiết kế gốc: `../odyssey-dashboard-prototype/design/Tenant Portal.dc.html` — **chỉ đọc**.

Nó là **brainstorm, không phải yêu cầu** (quyết định W1). Lấy layout · design token · state model từ
nó; lấy **hành vi** từ tài liệu nghiệp vụ trong `docs/product/`. Ba màn `audit`/`settings`/
`onboarding` không có markup trong bản tải về — dựng từ nghiệp vụ, **không đợi ảnh thiết kế**.

## Cái CHƯA có (đừng tưởng là thiếu sót)

Đăng nhập thật · shadcn/ui (cài khi màn đầu tiên cần) · TanStack Query provider cho dữ liệu màn
(module tự thêm) · Playwright · dark mode · responsive mobile.

Và một thứ **đã bỏ, không phải chưa làm**: `packages/contracts` — package workspace sinh type từ
OpenAPI của backend. Tách FE/BE thành hai repo git làm nó bất khả thi. Cách FE lấy type của backend
là quyết định treo thuộc **M2a-BE**; ba hướng để cân ghi ở
[spec kiến trúc §4①](docs/superpowers/specs/2026-07-29-odyssey-portal-kien-truc-va-ban-do-module.md).
