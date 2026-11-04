# Làm lại layout màn Agent + chuyển Thử agent sang màn API Keys — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Màn Agent thành form + tabs (Cấu hình chung · Bất động sản · Tài chính khoá), gộp xem trước vào dialog Lưu, chuyển panel Thử agent sang màn API Keys với chọn khoá theo tên.

**Architecture:** FE-only (spec `docs/superpowers/specs/2026-08-07-lam-lai-layout-agent-va-thu-agent-design.md`). Payload backend giữ nguyên — chia kỹ năng ra tab chỉ ở tầng hiển thị bằng hằng `KY_NANG_CHUNG`. Endpoint thử `POST /api/v1/agent/try` do FE định hợp đồng, MSW fake, backend làm sau. Trạng thái agent đi xuyên module qua `features/agent/contracts.ts` mới.

**Tech Stack:** React 19 + TanStack Router/Query + Tailwind (token trong `theme.css`) + vitest + MSW.

## Global Constraints

- Repo: `odyssey-portal-frontend`, branch từ `develop`. **Working tree đang có sẵn thay đổi dở của việc khác** (CLAUDE.md, `src/components/shell/*`, …) — **CẤM `git add -A` / `git add .`**; mỗi commit chỉ add đúng các file của task đó.
- Commit message: `<type>: <description>` (feat/fix/refactor/test/docs/chore), tiếng Việt như log hiện có, **KHÔNG** footer Co-Authored-By (attribution đã tắt trong `~/.claude/settings.json`).
- **Không mã màu ngoài `theme.css`** — chỉ dùng class token (`bg-panel`, `text-muted`, `border-border`, …). Bo góc đúng 3 bậc: `rounded-sm|md|lg` + `rounded-full`; **cấm `rounded-[Npx]`**.
- Typecheck thật là `npx tsc -b --force` (hoặc `make lint`). **`tsc --noEmit` là cổng rỗng** — thoát 0 mà không kiểm file nào.
- `prettier` chấm theo file: đã sửa file nào thì `npx prettier --write` trọn file đó.
- Test chạy `npx vitest run <file>` cho từng file, `make check` toàn bộ. **Mốc trước khi sửa (đo 2026-08-07): 269 pass · 1 fail · 6 skip — bài đỏ CÓ SẴN là `tests/convos-phien.test.tsx:53`, KHÔNG được sửa nó, KHÔNG nhận nó là của mình.** `src/routeTree.gen.ts` có nợ định dạng do bộ sinh — kệ nó.
- Ranh giới module: `features/<a>` chỉ import `features/<a>/…` · `lib/…` · `components/…` · `i18n/…`; thứ của module khác chỉ qua `features/<b>/contracts`.
- Chuỗi giao diện: màn Agent (AgentStudio + tabs + dialog) **thuần tiếng Việt** như hiện tại (không dùng `t()`); màn API Keys dùng `t({vi, en})` như phần còn lại của file đó.
- **Tên tool (`kb_search`, `find_project`, …) không bao giờ lộ ra giao diện** (AG_01 §II.3) — chỉ hiện `nhan` nghiệp vụ.

---

### Task 1: Nhánh làm việc + mốc baseline

**Files:** không sửa file nào.

- [ ] **Step 1: Tạo nhánh từ develop**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/odyssey-portal-frontend
git checkout -b feat/agent-layout-tabs develop
```

(Working tree bẩn sẵn — các file dở của việc khác cứ để nguyên, không stash, không add.)

- [ ] **Step 2: Chụp mốc test**

Run: `npx vitest run 2>&1 | tail -5`
Expected: `269 passed | 1 failed | 6 skipped` (con số pass có thể lệch ±vài bài nếu develop đã tiến — ghi lại con số THẬT vào ghi chú task; bài fail phải là `convos-phien`). Nếu fail bài khác ⇒ DỪNG, báo lại, không tiếp tục trên nền đỏ lạ.

---

### Task 2: Hằng chia kỹ năng ra tab — `kyNang.ts`

**Files:**
- Create: `src/features/agent/kyNang.ts`
- Test: `tests/ky-nang-tab.test.ts`

**Interfaces:**
- Consumes: `MUOI_HAI_KY_NANG`, type `KyNang` từ `@/lib/tools` (đã có).
- Produces: `KY_NANG_CHUNG: readonly string[]` · `KY_NANG_TAB_CHUNG: readonly KyNang[]` · `KY_NANG_TAB_BDS: readonly KyNang[]` — Task 5 dùng hai mảng TAB để render toggle.

- [ ] **Step 1: Viết test đỏ**

```ts
// tests/ky-nang-tab.test.ts
/**
 * Chia 12 kỹ năng ra hai tab là tầng HIỂN THỊ (spec 2026-08-07 §3.2). Hai bài
 * này canh hai cách nó mục ruỗng: (1) một tên trong KY_NANG_CHUNG bị backend đổi
 * mà không ai hay — hằng số trỏ vào hư không, kỹ năng đó lặng lẽ rơi sang tab
 * BĐS; (2) hai tab không chia trọn sổ — một kỹ năng biến mất khỏi giao diện.
 */
import { describe, expect, it } from 'vitest'
import { KY_NANG_CHUNG, KY_NANG_TAB_BDS, KY_NANG_TAB_CHUNG } from '../src/features/agent/kyNang'
import { MUOI_HAI_KY_NANG } from '../src/lib/tools'

describe('chia kỹ năng ra tab', () => {
  it('mỗi tên trong KY_NANG_CHUNG tồn tại trong sổ kỹ năng', () => {
    const ten = new Set(MUOI_HAI_KY_NANG.map((k) => k.ten))
    for (const t of KY_NANG_CHUNG) expect(ten.has(t), `'${t}' không có trong sổ`).toBe(true)
  })

  it('hai tab chia trọn sổ, không sót không trùng', () => {
    expect(KY_NANG_TAB_CHUNG.length + KY_NANG_TAB_BDS.length).toBe(MUOI_HAI_KY_NANG.length)
    const tenBds = new Set(KY_NANG_TAB_BDS.map((k) => k.ten))
    expect(KY_NANG_TAB_CHUNG.filter((k) => tenBds.has(k.ten))).toEqual([])
  })

  it('3 kỹ năng chung đúng như spec đã chốt', () => {
    expect([...KY_NANG_CHUNG].sort()).toEqual(['escalate', 'kb_search', 'update_customer'])
  })
})
```

- [ ] **Step 2: Chạy — phải đỏ**

Run: `npx vitest run tests/ky-nang-tab.test.ts`
Expected: FAIL — `Cannot find module '../src/features/agent/kyNang'`

- [ ] **Step 3: Viết `kyNang.ts`**

```ts
// src/features/agent/kyNang.ts
/**
 * Chia 12 kỹ năng ra hai tab: chung của agent vs riêng lĩnh vực BĐS.
 *
 * CHỈ là tầng hiển thị (spec 2026-08-07 §3.2): payload gửi backend vẫn là một
 * mảng `tools.enabled` gộp. KHÔNG sửa `lib/tools.ts` — nó là bản sao hợp đồng
 * backend có cổng parity canh, thêm trường vào đó là thêm thứ parity không so.
 *
 * Kỹ năng backend thêm sau này không có tên ở đây sẽ tự rơi vào tab BĐS —
 * mặc định đúng cho vertical #1; muốn nó thành kỹ năng chung thì thêm tên vào
 * `KY_NANG_CHUNG`. `tests/ky-nang-tab.test.ts` canh tên trỏ vào sổ thật.
 */
import { MUOI_HAI_KY_NANG, type KyNang } from '@/lib/tools'

export const KY_NANG_CHUNG: readonly string[] = ['kb_search', 'update_customer', 'escalate']

export const KY_NANG_TAB_CHUNG: readonly KyNang[] = MUOI_HAI_KY_NANG.filter((k) =>
  KY_NANG_CHUNG.includes(k.ten),
)

export const KY_NANG_TAB_BDS: readonly KyNang[] = MUOI_HAI_KY_NANG.filter(
  (k) => !KY_NANG_CHUNG.includes(k.ten),
)
```

- [ ] **Step 4: Chạy — phải xanh**

Run: `npx vitest run tests/ky-nang-tab.test.ts`
Expected: PASS (3 bài)

- [ ] **Step 5: Format + commit**

```bash
npx prettier --write src/features/agent/kyNang.ts tests/ky-nang-tab.test.ts
git add src/features/agent/kyNang.ts tests/ky-nang-tab.test.ts
git commit -m "feat: hằng chia 12 kỹ năng ra tab chung/BĐS (tầng hiển thị)"
```

---

### Task 3: Đổi nhãn nav «Agent» và «API Keys»

**Files:**
- Modify: `src/features/agent/nav.ts` (label + docstring)
- Modify: `src/features/platform/nav.ts` (label `apiNav`)
- Modify: `src/lib/screens.ts` (note màn `api`, giữ `mvp: 'partial'`)
- Modify: `src/routes/_app/api-keys.tsx` (comment lý do partial)
- Modify: `tests/shell.test.tsx` (nhãn trong bài lọc quyền)

**Interfaces:**
- Produces: nhãn nav mới `{ vi: 'Agent', en: 'Agent' }` và `{ vi: 'API Keys', en: 'API keys' }` — Topbar tự render `<h1>` từ nhãn này, không sửa shell.

- [ ] **Step 1: Sửa test trước — nhãn mới trong bài lọc quyền**

Trong `tests/shell.test.tsx` (~dòng 137-144), bài `'thiếu WORKSPACE_ADMIN thì mất Users · Tích hợp & API · Gói cước'`:

```ts
  it('thiếu WORKSPACE_ADMIN thì mất Users · API Keys · Gói cước', async () => {
    withActions([ACTIONS.OVERVIEW_READ, ACTIONS.CONVOS_READ])
    renderShell('/dashboard')

    const nav = within(await sidebar())
    expect(nav.getByText('Tổng quan')).toBeInTheDocument()
    expect(nav.queryByText('Thành viên & Phân quyền')).not.toBeInTheDocument()
    expect(nav.queryByText('API Keys')).not.toBeInTheDocument()
    expect(nav.queryByText('Gói cước & Usage')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Chạy — phải đỏ đúng kiểu**

Run: `npx vitest run tests/shell.test.tsx`
Expected: bài trên vẫn XANH (queryByText nhãn chưa tồn tại → null → pass) — nhãn cũ đã bị xoá khỏi assertion nên bài này không canh được gì cho tới khi nav đổi. Vậy cổng thật là Step 4; bước này chỉ xác nhận không vỡ bài khác.

- [ ] **Step 3: Đổi hai nhãn nav + note screens.ts + comment route**

`src/features/agent/nav.ts` — sửa docstring và label:

```ts
/** Nav của M5 — Agent Studio. Sở hữu: agent. Spec tổng §2, §4⑤.
 * Nhãn là «Agent» trần — «& Kênh» đã bỏ (2026-08-07): không có màn quản lý kênh
 * nào tồn tại, nhãn không được hứa thứ không có. */
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const agentNav: NavLeaf = {
  kind: 'leaf',
  key: 'agent',
  path: '/agent',
  label: { vi: 'Agent', en: 'Agent' },
  icon: 'agent',
  // Đọc cấu hình là nhóm 10; sửa (nhóm 11) và xuất bản (nhóm 12) kiểm trong màn.
  requiredActions: [ACTIONS.AGENT_CONFIG_READ],
}
```

`src/features/platform/nav.ts` — chỉ đổi label của `apiNav`:

```ts
  label: { vi: 'API Keys', en: 'API keys' },
```

`src/lib/screens.ts` — entry `api`: thay comment + note (giữ `mvp: 'partial'`):

```ts
  {
    key: 'api',
    path: '/api-keys',
    owner: 'M8',
    // `partial`, KHÔNG `full`: khoá đấu nối xong (phát · liệt kê · thu hồi) nhưng
    // panel Thử agent còn chờ endpoint `/agent/try` phía backend (spec 2026-08-07 §5.2).
    mvp: 'partial',
    inNav: true,
    note: 'Khoá đấu nối xong; panel Thử agent chờ endpoint backend',
  },
```

`src/routes/_app/api-keys.tsx` — comment mới:

```tsx
// Màn `api` của M8 — nhãn nav «API Keys» (2026-08-07, bỏ «Tích hợp &» vì phần đó
// chưa có gì). MVP: khoá đấu nối agent + panel Thử agent (chờ endpoint backend
// nên `screens.ts` giữ `mvp: 'partial'`).
```

- [ ] **Step 4: Chạy các cổng liên quan**

Run: `npx vitest run tests/shell.test.tsx tests/nav-registry.test.ts tests/boot.test.tsx`
Expected: PASS hết. (`boot.test.tsx` dùng dấu hiệu là CÂU MÔ TẢ trong màn, không phải nhãn nav — không việc gì.)

- [ ] **Step 5: Quét sót nhãn cũ**

Run: `grep -rn "Agent & Kênh\|Agent & channels\|Tích hợp & API" src/ tests/ --include='*.ts' --include='*.tsx'`
Expected: chỉ còn hit trong COMMENT kể chuyện cũ (nếu có, sửa nốt các comment nói nhãn hiện hành; giữ nguyên các comment thuật lại lịch sử như `tests/nav-registry.test.ts:144` nói về proxy — câu đó nói về màn, sửa thành «màn API Keys» luôn cho khỏi lạc hậu).

- [ ] **Step 6: Format + commit**

```bash
npx prettier --write src/features/agent/nav.ts src/features/platform/nav.ts src/lib/screens.ts src/routes/_app/api-keys.tsx tests/shell.test.tsx
git add src/features/agent/nav.ts src/features/platform/nav.ts src/lib/screens.ts src/routes/_app/api-keys.tsx tests/shell.test.tsx tests/nav-registry.test.ts
git commit -m "feat: đổi nhãn nav Agent & Kênh → Agent, Tích hợp & API → API Keys"
```

(`tests/nav-registry.test.ts` chỉ add nếu Step 5 có sửa comment trong đó.)

---

### Task 4: Tách form primitives của AgentStudio ra file riêng (refactor thuần)

Chuẩn bị cho tabs: `AgentStudio.tsx` đang 651 dòng, thêm tabs sẽ vượt trần 800. Task này CHỈ chuyển chỗ ở, không đổi hành vi — test hiện có phải xanh nguyên.

**Files:**
- Create: `src/features/agent/components/form.tsx` (component: `The` · `O` · `Preset` · `Canh` · `Dong` · `CongTacKyNang`)
- Create: `src/features/agent/components/lop.ts` (hằng class: `NUT_PHU` · `NUT_CHINH` · `O_LOP` · `PHONG_BAN_GOI_Y`)
- Modify: `src/features/agent/components/AgentStudio.tsx` (xoá phần đã tách, import lại)

**Interfaces:**
- Produces (Task 5, 6 dùng):
  - `form.tsx`: `The({tieuDe, phu?, children})` · `O({nhan, giaTri, toiDa, doi, goiYTrongO?})` · `Preset({nhan, cac, chon, doi})` · `Canh({mau: 'warn'|'alert', children})` · `Dong({nhan, children})` · `CongTacKyNang({danhSach: readonly KyNang[], dangBat: readonly string[], doi: (ten: string, bat: boolean) => void})`
  - `lop.ts`: `NUT_PHU: string` · `NUT_CHINH: string` · `O_LOP: string` · `PHONG_BAN_GOI_Y: readonly string[]`

- [ ] **Step 1: Tạo `lop.ts`**

Chuyển NGUYÊN VĂN 2 hằng nút (AgentStudio dòng 116-119), `O_LOP` (dòng 550-551), `PHONG_BAN_GOI_Y` (dòng 553-558) sang file mới. Tách khỏi `form.tsx` vì eslint `react-refresh/only-export-components` cảnh file component export thêm hằng — cùng lý do `features/platform/api.ts` đã ghi.

```ts
// src/features/agent/components/lop.ts
/** Hằng class dùng chung của màn Agent — tách khỏi form.tsx vì eslint
 * `react-refresh/only-export-components` không cho file component export hằng. */

export const NUT_PHU =
  'rounded-lg border border-border-strong bg-surface px-3.5 py-2 text-[12.5px] font-medium whitespace-nowrap transition-colors hover:border-fg disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-border-strong'

export const NUT_CHINH =
  'rounded-lg bg-ac px-[15px] py-2 text-[12.5px] font-semibold text-white whitespace-nowrap transition-colors hover:bg-acd disabled:cursor-not-allowed disabled:bg-border-strong disabled:text-muted'

export const O_LOP =
  'w-full rounded-md border border-border-strong bg-surface px-3 py-[10px] text-[13px] outline-none transition-colors placeholder:text-muted-3 focus:border-ac focus:ring-2 focus:ring-ac/15'

/** Gợi ý trong ô cho từng dòng Phòng ban chuyển tiếp — đầu mối của một sàn BĐS. */
export const PHONG_BAN_GOI_Y = [
  'VD: Phòng kinh doanh',
  'VD: Phòng hỗ trợ vay & tín dụng',
  'VD: Phòng chăm sóc khách hàng',
] as const
```

- [ ] **Step 2: Tạo `form.tsx`**

Chuyển NGUYÊN VĂN `The` (dòng 539-548), `O` (560-588), `Preset` (590-626), `Canh` (628-639), `Dong` (641-651) — giữ đủ docstring của từng cái. Thêm `CongTacKyNang` — chính là markup toggle đang nằm trong JSX của AgentStudio (dòng 389-418), tham số hoá danh sách:

```tsx
// src/features/agent/components/form.tsx  (đầu file)
import type { ReactNode } from 'react'
import type { KyNang } from '@/lib/tools'
import { O_LOP } from './lop'

// ... The · O · Preset · Canh · Dong chuyển nguyên văn vào đây, export từng cái ...

/** Danh sách toggle kỹ năng — cùng markup công tắc 38×21 của prototype, dùng ở
 * cả tab Cấu hình chung (3 kỹ năng) và tab Bất động sản (9 kỹ năng). Checkbox
 * thật nằm dưới `sr-only` cho bàn phím và screen reader. */
export function CongTacKyNang(props: {
  danhSach: readonly KyNang[]
  dangBat: readonly string[]
  doi: (ten: string, bat: boolean) => void
}) {
  return (
    <div className="flex flex-col">
      {props.danhSach.map((k) => (
        <label
          key={k.ten}
          className="group flex cursor-pointer items-center gap-3 border-b border-border-soft py-[11px] last:border-b-0"
        >
          <span className="flex-1 text-[13px] font-medium">{k.nhan}</span>
          <input
            type="checkbox"
            aria-label={k.nhan}
            className="peer sr-only"
            checked={props.dangBat.includes(k.ten)}
            onChange={(e) => props.doi(k.ten, e.target.checked)}
          />
          <span className="relative h-[21px] w-[38px] flex-none rounded-full bg-border-strong transition-colors peer-checked:bg-ac peer-focus-visible:ring-2 peer-focus-visible:ring-ac/40 peer-focus-visible:ring-offset-2 after:absolute after:top-[2px] after:left-[2px] after:h-[17px] after:w-[17px] after:rounded-full after:bg-surface after:transition-transform peer-checked:after:translate-x-[17px]" />
        </label>
      ))}
    </div>
  )
}
```

(`O` trong form.tsx import `O_LOP` từ `./lop` thay vì hằng cục bộ.)

- [ ] **Step 3: Cập nhật `AgentStudio.tsx`**

- Xoá 5 component + 4 hằng đã tách; import từ `./form` và `./lop`.
- Thay khối toggle 12 kỹ năng (dòng 389-418) bằng:

```tsx
<CongTacKyNang
  danhSach={MUOI_HAI_KY_NANG}
  dangBat={dangBat}
  doi={(ten, bat) =>
    sua((c) => ({
      ...c,
      tools: {
        enabled: bat ? [...c.tools.enabled, ten] : c.tools.enabled.filter((t) => t !== ten),
      },
    }))
  }
/>
```

Mọi thứ khác giữ nguyên — task này chưa có tab.

- [ ] **Step 4: Chạy — hành vi phải y nguyên**

Run: `npx vitest run tests/agent-studio.test.tsx && npx tsc -b --force`
Expected: PASS toàn bộ (bài nào xanh trước phải xanh sau), tsc sạch.

- [ ] **Step 5: Lint + commit**

```bash
npx prettier --write src/features/agent/components/form.tsx src/features/agent/components/lop.ts src/features/agent/components/AgentStudio.tsx
npx eslint src/features/agent/
git add src/features/agent/components/form.tsx src/features/agent/components/lop.ts src/features/agent/components/AgentStudio.tsx
git commit -m "refactor: tách form primitives của AgentStudio ra form.tsx/lop.ts"
```

---

### Task 5: Màn Agent thành form + tabs, bỏ panel Thử ngay

**Files:**
- Create: `src/features/agent/components/TabChung.tsx`
- Create: `src/features/agent/components/TabLinhVuc.tsx`
- Modify: `src/features/agent/components/AgentStudio.tsx`
- Modify: `src/routes/_app/agent.tsx` (comment: chat thử đã sang màn API Keys)
- Test: `tests/agent-studio.test.tsx`

**Interfaces:**
- Consumes: `KY_NANG_TAB_CHUNG`/`KY_NANG_TAB_BDS` (Task 2), primitives (Task 4).
- Produces: AgentStudio giữ state `form`/`sua`/`chuanHoa` như cũ; hàm `doiKyNang(ten, bat)` truyền xuống hai tab. **Chưa đụng luồng lưu**: cả hai nút «Xem trước thay đổi» + «Lưu và áp dụng» và khối «Bản xem trước» GIỮ NGUYÊN ở task này (chuyển xuống dưới thanh trạng thái vì cột phải không còn) — Task 6 mới thay bằng dialog. Panel «Thử ngay» bỏ hẳn.

- [ ] **Step 1: Sửa test — 3 nhóm đổi theo tabs**

Trong `tests/agent-studio.test.tsx`:

(a) Nhóm `'Agent Studio — 12 kỹ năng'` viết lại:

```tsx
describe('Agent Studio — kỹ năng chia hai tab', () => {
  it('tab Cấu hình chung có 3 toggle chung, tab Bất động sản có 9 toggle lĩnh vực', async () => {
    datApi()
    boot()
    await screen.findByDisplayValue('Mai')

    // Tab mặc định là Cấu hình chung — 3 kỹ năng chung của agent.
    expect(screen.getByLabelText('Tra tài liệu của workspace')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)

    await userEvent.click(screen.getByRole('tab', { name: 'Bất động sản' }))
    expect(await screen.findByLabelText('Đặt lịch tham quan')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(9)
    // AG_01 §II.3: tên hàm không lộ ra giao diện.
    expect(screen.queryByText('kb_search')).not.toBeInTheDocument()
    expect(screen.queryByText('search_units')).not.toBeInTheDocument()
  })

  it('tab Tài chính khoá — bấm không mở, có lời «chưa kích hoạt»', async () => {
    datApi()
    boot()
    await screen.findByDisplayValue('Mai')

    expect(screen.getByRole('tab', { name: /Tài chính/ })).toBeDisabled()
  })

  it('bật kỹ năng thiếu phụ thuộc thì cảnh báo NGAY trong tab BĐS', async () => {
    datApi()
    boot()
    await screen.findByDisplayValue('Mai')

    await userEvent.click(screen.getByRole('tab', { name: 'Bất động sản' }))
    await userEvent.click(await screen.findByLabelText('Gợi ý căn phù hợp'))

    expect(
      await screen.findByText('Gợi ý căn phù hợp cần Tìm căn theo tiêu chí mới chạy đúng.'),
    ).toBeInTheDocument()
  })

  it('tắt hết kỹ năng thì cảnh báo hiện DƯỚI HEADER, thấy được từ mọi tab (ER_03)', async () => {
    datApi()
    boot()
    await screen.findByDisplayValue('Mai')

    // PAYLOAD bật 2 kỹ năng nằm ở HAI tab khác nhau — phải tắt cả hai nơi.
    await userEvent.click(screen.getByLabelText('Tra tài liệu của workspace'))
    await userEvent.click(screen.getByRole('tab', { name: 'Bất động sản' }))
    await userEvent.click(await screen.findByLabelText('Nhận diện tên dự án'))

    expect(await screen.findByText(/không làm được gì/i)).toBeInTheDocument()
    // Cảnh báo toàn cục — quay về tab đầu vẫn thấy.
    await userEvent.click(screen.getByRole('tab', { name: 'Cấu hình chung' }))
    expect(screen.getByText(/không làm được gì/i)).toBeInTheDocument()
  })
})
```

(b) Nhóm `'Agent Studio — trạng thái và chat thử'` XOÁ CẢ NHÓM — panel không còn ở màn này; phần gate chuyển sang `tests/thu-agent.test.tsx` (Task 10). Thay bằng một bài canh việc bỏ:

```tsx
describe('Agent Studio — không còn chat thử', () => {
  it('màn Agent không có ô «Thử ngay» — nó đã sang màn API Keys', async () => {
    datApi()
    boot()
    await screen.findByDisplayValue('Mai')

    expect(screen.queryByPlaceholderText(/thử/i)).not.toBeInTheDocument()
  })
})
```

(c) Các nhóm form/xưng hô/v2/rào chắn: rào chắn giờ nằm trong tab Cấu hình chung (tab mặc định) — các bài đó giữ nguyên KHÔNG sửa. Hai bài trong nhóm «xem trước rồi mới áp dụng» và bài `'gửi lên server KHÔNG còn xung_ho'` GIỮ NGUYÊN ở task này (flow 2 nút vẫn còn tới Task 6).

- [ ] **Step 2: Chạy — phải đỏ**

Run: `npx vitest run tests/agent-studio.test.tsx`
Expected: FAIL các bài mới (`getByRole('tab')` không tìm thấy).

- [ ] **Step 3: Viết `TabChung.tsx`**

Nhận props từ AgentStudio, chứa: Danh tính (nguyên khối `The tieuDe="Danh tính"` cũ, gồm cảnh báo `nhapSchemaCu`), Giọng điệu, Phạm vi, thẻ «Kỹ năng chung của agent» (3 toggle), thẻ Rào chắn (chuyển từ cột phải cũ, giữ nguyên markup + `aria-label`):

```tsx
// src/features/agent/components/TabChung.tsx
/**
 * Tab «Cấu hình chung» — mọi thứ CHUNG của agent, bất kể lĩnh vực nào:
 * system prompt (danh tính · giọng điệu · phạm vi), 3 kỹ năng chung, 6 rào chắn.
 * Spec 2026-08-07 §3.2. Kỹ năng lĩnh vực ở TabLinhVuc.
 */
import type { ConfigPayload } from '../api'
import { KY_NANG_TAB_CHUNG } from '../kyNang'
import { Canh, CongTacKyNang, Dong, O, Preset, The } from './form'
import { O_LOP, PHONG_BAN_GOI_Y } from './lop'

export function TabChung(props: {
  form: ConfigPayload
  sua: (f: (c: ConfigPayload) => ConfigPayload) => void
  doiKyNang: (ten: string, bat: boolean) => void
  /** Bản nháp đang lưu thuộc schema cũ — cảnh báo cạnh hai ô xưng hô. */
  nhapSchemaCu: boolean
  schemaVersionNhap: number | undefined
}) {
  const { form, sua } = props
  return (
    <div className="flex flex-col gap-3.5">
      {/* … khối Danh tính · Phạm vi · Giọng điệu CHUYỂN NGUYÊN VĂN, đúng thứ tự
          cũ, từ AgentStudio (dòng 249-386). Đổi tham chiếu hằng sang import, và
          trong cảnh báo schema cũ: `nhap.data?.schemaVersion` →
          `props.schemaVersionNhap`, điều kiện hiện → `props.nhapSchemaCu` … */}

      <The tieuDe="Kỹ năng chung của agent" phu="Dùng được ở mọi lĩnh vực">
        <CongTacKyNang
          danhSach={KY_NANG_TAB_CHUNG}
          dangBat={form.tools.enabled}
          doi={props.doiKyNang}
        />
      </The>

      <The tieuDe="Rào chắn đang bảo vệ workspace">
        {/* … khối RAO_CHAN chuyển nguyên văn từ cột phải cũ (dòng 515-532),
            hằng RAO_CHAN chuyển sang file này … */}
      </The>
    </div>
  )
}
```

(Hằng `RAO_CHAN`, `GIONG_DIEU`, `DO_DAI` chuyển từ AgentStudio sang đầu file này — chúng chỉ tab này dùng. Docstring của từng hằng chuyển theo nguyên văn.)

- [ ] **Step 4: Viết `TabLinhVuc.tsx`**

```tsx
// src/features/agent/components/TabLinhVuc.tsx
/**
 * Tab «Bất động sản» — đồ nghề của lĩnh vực: 9 kỹ năng + khối knowledge.
 *
 * Khối knowledge là MÔ TẢ + hai link, KHÔNG có số đếm: đếm dự án/tài liệu là
 * API của module realestate/kb — kéo vào đây là xuyên ranh giới module chỉ để
 * hiện một con số (spec 2026-08-07 §3.2 chấp nhận tóm tắt định tính).
 *
 * Cảnh báo phụ thuộc đặt ở tab này vì mọi cặp trong PHU_THUOC hiện đều nội bộ
 * BĐS. Backend thêm phụ thuộc XUYÊN nhóm thì xem lại chỗ đặt.
 */
import { Link } from '@tanstack/react-router'
import type { ConfigPayload } from '../api'
import { nhanCua, thieuPhuThuoc } from '@/lib/tools'
import { KY_NANG_TAB_BDS } from '../kyNang'
import { Canh, CongTacKyNang, The } from './form'

export function TabLinhVuc(props: {
  form: ConfigPayload
  doiKyNang: (ten: string, bat: boolean) => void
}) {
  const thieu = thieuPhuThuoc(props.form.tools.enabled)
  return (
    <div className="flex flex-col gap-3.5">
      <The tieuDe="Kỹ năng của lĩnh vực" phu="Bật cái nào, agent làm được cái đó">
        <CongTacKyNang
          danhSach={KY_NANG_TAB_BDS}
          dangBat={props.form.tools.enabled}
          doi={props.doiKyNang}
        />
        {thieu.map(([ten, can]) => (
          <Canh key={`${ten}-${can}`} mau="warn">
            {nhanCua(ten)} cần {nhanCua(can)} mới chạy đúng.
          </Canh>
        ))}
      </The>

      <The tieuDe="Kiến thức của lĩnh vực" phu="Agent trả lời dựa trên dữ liệu này">
        <p className="text-[12.5px] leading-[1.55] text-nav">
          Dự án, quỹ căn và tài liệu của workspace là nguồn agent tra khi khách hỏi.
          Sửa dữ liệu ở đó là agent thấy ngay — không cần xuất bản lại.
        </p>
        <div className="mt-3 flex flex-wrap gap-2.5">
          <Link to="/projects" className="text-[12.5px] font-medium text-ac hover:underline">
            Dữ liệu Bất động sản →
          </Link>
          <Link to="/kb" className="text-[12.5px] font-medium text-ac hover:underline">
            Tài liệu workspace →
          </Link>
        </div>
      </The>
    </div>
  )
}
```

- [ ] **Step 5: Dựng lại `AgentStudio.tsx`**

Khung mới (giữ `chuanHoa`, queries, `sua`, `mXemTruoc`/`mApDung`, `vuaApDung`, thanh trạng thái + 2 nút y như cũ ở task này):

```tsx
const TAB = [
  { ma: 'chung', nhan: 'Cấu hình chung' },
  { ma: 'bds', nhan: 'Bất động sản' },
  { ma: 'taichinh', nhan: 'Tài chính' },
] as const
type MaTab = (typeof TAB)[number]['ma']

// trong component:
const [tab, setTab] = useState<MaTab>('chung')
const doiKyNang = (ten: string, bat: boolean) =>
  sua((c) => ({
    ...c,
    tools: { enabled: bat ? [...c.tools.enabled, ten] : c.tools.enabled.filter((t) => t !== ten) },
  }))
```

JSX sau thanh trạng thái (cột phải cũ BỎ — panel Thử ngay xoá hẳn; khối «Bản xem trước»/lỗi xem trước tạm để ngay dưới thanh trạng thái, Task 6 nuốt vào dialog):

```tsx
{/* Cảnh báo toàn cục — dưới header, trên tab, thấy từ mọi tab (ER_03). */}
{form.tools.enabled.length === 0 && (
  <Canh mau="alert">Agent sẽ không làm được gì — bật ít nhất một kỹ năng.</Canh>
)}

<div role="tablist" aria-label="Cấu hình agent" className="mt-3.5 mb-3.5 flex gap-1.5 border-b border-border">
  {TAB.map((t) => {
    const khoa = t.ma === 'taichinh' // vertical #2 đang hoãn — khoá cứng (spec §3.2)
    const chon = tab === t.ma
    return (
      <button
        key={t.ma}
        type="button"
        role="tab"
        aria-selected={chon}
        disabled={khoa}
        title={khoa ? 'Lĩnh vực chưa kích hoạt' : undefined}
        onClick={() => setTab(t.ma)}
        className={`rounded-t-md border-b-2 px-3.5 py-2 text-[12.5px] font-medium transition-colors ${
          chon ? 'border-ac text-fg' : 'border-transparent text-muted hover:text-fg'
        } disabled:cursor-not-allowed disabled:opacity-45`}
      >
        {t.nhan}
        {khoa && ' 🔒'}
      </button>
    )
  })}
</div>

{tab === 'chung' && (
  <TabChung
    form={form}
    sua={sua}
    doiKyNang={doiKyNang}
    nhapSchemaCu={nhapSchemaCu}
    schemaVersionNhap={nhap.data?.schemaVersion}
  />
)}
{tab === 'bds' && <TabLinhVuc form={form} doiKyNang={doiKyNang} />}
```

Nội dung form full-width một cột (`max-w-[860px]` cho dễ đọc trên màn rộng — cùng nhịp thẻ trắng cũ).

`src/routes/_app/agent.tsx` — comment mới:

```tsx
// Màn thứ hai có nội dung thật (sau `users`). M5: form + tabs theo lĩnh vực +
// dialog áp dụng. Chat thử ĐÃ SANG màn API Keys (spec 2026-08-07) — đi qua đúng
// kênh khách dùng (HT01 BR03).
```

- [ ] **Step 6: Chạy test màn + boot**

Run: `npx vitest run tests/agent-studio.test.tsx tests/boot.test.tsx && npx tsc -b --force`
Expected: PASS hết (boot signal `'Rào chắn đang bảo vệ workspace'` vẫn render vì tab mặc định là Cấu hình chung).

- [ ] **Step 7: Format + commit**

```bash
npx prettier --write src/features/agent/components/TabChung.tsx src/features/agent/components/TabLinhVuc.tsx src/features/agent/components/AgentStudio.tsx src/routes/_app/agent.tsx tests/agent-studio.test.tsx
git add src/features/agent/components/TabChung.tsx src/features/agent/components/TabLinhVuc.tsx src/features/agent/components/AgentStudio.tsx src/routes/_app/agent.tsx tests/agent-studio.test.tsx
git commit -m "feat: màn Agent thành form + tabs theo lĩnh vực, bỏ panel Thử ngay"
```

---

### Task 6: Dialog «Lưu và áp dụng» nuốt bước xem trước

**Files:**
- Create: `src/features/agent/components/LuuApDungDialog.tsx`
- Modify: `src/features/agent/components/AgentStudio.tsx`
- Test: `tests/agent-studio.test.tsx`

**Interfaces:**
- Consumes: `xemTruoc(form)` · type `XemTruocOut` từ `../api`; `Dong`/`Canh` từ `./form`; `NUT_PHU`/`NUT_CHINH` từ `./lop`.
- Produces: `LuuApDungDialog({ form, dangGui, loiApDung, onDong, onXacNhan })` — dialog tự gọi preview khi mở; `onXacNhan` do AgentStudio đưa vào = `mApDung.mutate()`.

- [ ] **Step 1: Sửa test — nhóm «xem trước rồi mới áp dụng» viết lại**

```tsx
describe('Agent Studio — dialog Lưu và áp dụng (xem trước nằm trong dialog)', () => {
  const RENDER_GIA = {
    tenAgent: 'Mai',
    thuongHieu: 'An Phú Land',
    tuXung: 'em',
    goiKhach: 'anh/chị',
    giongDieu: 'Thân thiện và gần gũi.',
    doDai: 'Trả lời trong 3–4 câu.',
    lamGi: 'Tư vấn dự án.',
    khongLamGi: 'Hậu mãi.',
    cauTuChoi: 'Em xin phép chuyển anh/chị.',
    phongBan: ['CSKH'],
    kyNang: ['find_project', 'kb_search'],
    raoChan: ['a', 'b', 'c', 'd', 'e', 'f'],
    truongDaDoi: ['danh_tinh.ten_agent'],
  }

  it('bấm Lưu và áp dụng → dialog hiện bản render + trường sẽ đổi, rồi mới có nút Xác nhận', async () => {
    datApi()
    server.use(http.post('/api/v1/config/preview', () => HttpResponse.json(RENDER_GIA)))
    boot()
    await screen.findByDisplayValue('Mai')

    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/Thân thiện và gần gũi/)).toBeInTheDocument()
    expect(within(dialog).getByText(/ten_agent/)).toBeInTheDocument()
    // BR10: câu này phải có trong dialog xác nhận.
    expect(within(dialog).getByText(/vẫn dùng bản cũ tới khi kết thúc/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Xác nhận áp dụng' })).toBeEnabled()
  })

  it('không có gì đổi thì dialog nói thẳng, vẫn cho áp dụng', async () => {
    datApi()
    server.use(
      http.post('/api/v1/config/preview', () =>
        HttpResponse.json({ ...RENDER_GIA, truongDaDoi: [] }),
      ),
    )
    boot()
    await screen.findByDisplayValue('Mai')

    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))

    expect(await screen.findByText(/Không có thay đổi so với bản đang chạy/)).toBeInTheDocument()
  })

  it('preview 422 thì dialog báo ER_04, KHÔNG có nút Xác nhận, và nói không có gì thay đổi', async () => {
    datApi()
    server.use(
      http.post('/api/v1/config/preview', () =>
        HttpResponse.json({ error: { code: 'UNPROCESSABLE', message: 'x' } }, { status: 422 }),
      ),
    )
    boot()
    await screen.findByDisplayValue('Mai')

    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))

    expect(await screen.findByText(/chưa áp dụng được/i)).toBeInTheDocument()
    expect(screen.getByText(/không có gì thay đổi/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Xác nhận áp dụng' })).not.toBeInTheDocument()
  })

  it('Xác nhận → PUT draft + publish, đóng dialog, header báo đã áp dụng vN', async () => {
    datApi()
    let daGui = false
    server.use(
      http.post('/api/v1/config/preview', () => HttpResponse.json(RENDER_GIA)),
      http.put('/api/v1/config/draft', async ({ request }) => {
        daGui = true
        return HttpResponse.json({
          payload: await request.json(),
          schemaVersion: 3,
          laMacDinh: false,
        })
      }),
      http.post('/api/v1/config/publish', () =>
        HttpResponse.json({ version: 4, truongDaDoi: ['danh_tinh.ten_agent'] }),
      ),
    )
    boot()
    await screen.findByDisplayValue('Mai')

    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Xác nhận áp dụng' }))

    expect(await screen.findByText(/Đã áp dụng v4/)).toBeInTheDocument()
    expect(daGui).toBe(true)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
```

Đồng thời SỬA bài v2 `'gửi lên server KHÔNG còn xung_ho…'`: thay hai click cũ

```tsx
await userEvent.click(screen.getByRole('button', { name: /xem trước/i }))
await waitFor(() => expect(screen.getByRole('button', { name: /lưu và áp dụng/i })).toBeEnabled())
await userEvent.click(screen.getByRole('button', { name: /lưu và áp dụng/i }))
```

bằng

```tsx
await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))
await userEvent.click(await screen.findByRole('button', { name: 'Xác nhận áp dụng' }))
```

(nhớ thêm `within` vào import từ `@testing-library/react`).

- [ ] **Step 2: Chạy — phải đỏ**

Run: `npx vitest run tests/agent-studio.test.tsx`
Expected: FAIL các bài dialog (chưa có `role="dialog"`).

- [ ] **Step 3: Viết `LuuApDungDialog.tsx`**

```tsx
// src/features/agent/components/LuuApDungDialog.tsx
/**
 * Dialog xác nhận trước khi phát — bước Xem trước của AG_01 §II.1 nuốt vào đây
 * (spec 2026-08-07 §3.2, quyết định #4): với người dùng là MỘT nút, nhưng bản
 * render + danh sách trường sẽ đổi vẫn đứng chắn trước nút phát. Preview gọi
 * NGAY khi dialog mở — nó là kiểm cấu trúc vài trăm ms phía backend, không đụng
 * agent, không cần API key.
 *
 * Preview hỏng (422) ⇒ KHÔNG render nút xác nhận — ER_04 hứa «không có gì thay
 * đổi», và cách chắc nhất để giữ lời là đường phát không tồn tại lúc đó.
 */
import { useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { xemTruoc, type ConfigPayload } from '../api'
import { nhanCua } from '@/lib/tools'
import { Dong } from './form'
import { NUT_CHINH, NUT_PHU } from './lop'

export function LuuApDungDialog(props: {
  form: ConfigPayload
  dangGui: boolean
  /** Lỗi của lần PUT+publish trước — dialog KHÔNG tự đóng khi lỗi. */
  loiApDung: boolean
  onDong: () => void
  onXacNhan: () => void
}) {
  const mXemTruoc = useMutation({ mutationFn: () => xemTruoc(props.form) })
  const { mutate } = mXemTruoc
  useEffect(() => mutate(), [mutate])

  const ban = mXemTruoc.data

  return (
    <div className="fixed inset-0 z-70 grid place-items-center px-4">
      <button
        type="button"
        aria-label="Đóng"
        onClick={props.onDong}
        disabled={props.dangGui}
        className="absolute inset-0 cursor-default bg-panel/45"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Xem lại trước khi áp dụng"
        className="relative max-h-[85vh] w-full max-w-[520px] overflow-y-auto rounded-2xl border border-border-field bg-surface p-5 shadow-[0_18px_50px_rgba(20,22,26,.22)]"
      >
        <h2 className="text-[15.5px] font-semibold leading-tight">Xem lại trước khi áp dụng</h2>

        {mXemTruoc.isPending && (
          <p className="mt-3 text-[12.5px] text-muted">Đang kiểm tra cấu hình…</p>
        )}

        {mXemTruoc.isError && (
          <div className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2.5">
            <p className="text-[13px] font-semibold text-badge-alert-fg">Chưa áp dụng được</p>
            <p className="mt-1 text-[12.5px] leading-[1.55] text-badge-alert-fg/90">
              Cấu hình có chỗ chưa hợp lệ. Không có gì thay đổi, agent vẫn chạy bản cũ.
            </p>
          </div>
        )}

        {ban && (
          <>
            <p className="mt-3 text-[12.5px] leading-[1.55] text-nav">
              {ban.tenAgent} — chuyên viên tư vấn của {ban.thuongHieu}. {ban.giongDieu}{' '}
              {ban.doDai}
            </p>
            <dl className="mt-3 flex flex-col gap-2.5 text-[12.5px]">
              <Dong nhan="Từ chối ngoài phạm vi">{ban.cauTuChoi}</Dong>
              <Dong nhan="Chuyển tiếp">{ban.phongBan.join(' · ')}</Dong>
              <Dong nhan="Kỹ năng">{ban.kyNang.map(nhanCua).join(' · ')}</Dong>
            </dl>
            <div className="mt-3.5 border-t border-border-soft pt-3.5">
              {ban.truongDaDoi.length > 0 ? (
                <>
                  <p className="mb-2 text-[11.5px] text-muted">Sẽ đổi</p>
                  <ul className="flex flex-wrap gap-1.5">
                    {ban.truongDaDoi.map((t) => (
                      <li
                        key={t}
                        className="rounded-md bg-badge-warn-bg px-2 py-[3px] font-mono text-[11px] font-medium text-badge-warn-fg"
                      >
                        {t}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="text-[12.5px] text-muted">Không có thay đổi so với bản đang chạy.</p>
              )}
            </div>
            {/* BR10 — thiếu câu này, người sửa một rào chắn đang nói sai sẽ tưởng chặn được ngay. */}
            <p className="mt-3.5 text-[11.5px] leading-[1.5] text-muted-2">
              Khách đang trong cuộc hội thoại vẫn dùng bản cũ tới khi kết thúc.
            </p>
          </>
        )}

        {props.loiApDung && (
          <p className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[12px] leading-[1.5] font-medium text-badge-alert-fg">
            Chưa áp dụng được — bản nháp vẫn còn nguyên, thử lại lần nữa.
          </p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button type="button" onClick={props.onDong} disabled={props.dangGui} className={NUT_PHU}>
            Huỷ
          </button>
          {ban && (
            <button
              type="button"
              onClick={props.onXacNhan}
              disabled={props.dangGui}
              className={NUT_CHINH}
            >
              {props.dangGui ? 'Đang áp dụng…' : 'Xác nhận áp dụng'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Nối vào `AgentStudio.tsx`**

- Xoá `mXemTruoc`, state `ban`/`loiXemTruoc`, khối «Bản xem trước»/khối lỗi xem trước còn sót từ Task 5, và nút «Xem trước thay đổi».
- Thêm `const [moDialog, setMoDialog] = useState(false)`.
- Nút header: `<button type="button" className={NUT_CHINH} disabled={mApDung.isPending} onClick={() => { mApDung.reset(); setMoDialog(true) }}>Lưu và áp dụng</button>`.
- `mApDung.onSuccess`: thêm `setMoDialog(false)` cạnh `setVuaApDung(kq.version)`.
- Cuối JSX:

```tsx
{moDialog && form && (
  <LuuApDungDialog
    form={form}
    dangGui={mApDung.isPending}
    loiApDung={mApDung.isError}
    onDong={() => setMoDialog(false)}
    onXacNhan={() => mApDung.mutate()}
  />
)}
```

- Câu phụ thanh trạng thái: bỏ nhánh `ban` («Đã xem trước…»); mặc định thành `'Sửa ở đây không ảnh hưởng bản đang chạy. Bấm Lưu và áp dụng để xem lại rồi phát.'`. Viền trái cố định `border-l-ac` (không còn hai màu theo bước).

- [ ] **Step 5: Chạy — phải xanh**

Run: `npx vitest run tests/agent-studio.test.tsx && npx tsc -b --force`
Expected: PASS toàn bộ file.

- [ ] **Step 6: Format + commit**

```bash
npx prettier --write src/features/agent/components/LuuApDungDialog.tsx src/features/agent/components/AgentStudio.tsx tests/agent-studio.test.tsx
git add src/features/agent/components/LuuApDungDialog.tsx src/features/agent/components/AgentStudio.tsx tests/agent-studio.test.tsx
git commit -m "feat: gộp xem trước vào dialog Lưu và áp dụng (giữ lời hứa AG_01 trong một bước)"
```

---

### Task 7: Mặt tiền `features/agent/contracts.ts`

**Files:**
- Create: `src/features/agent/contracts.ts`

**Interfaces:**
- Produces: `docTrangThai(): Promise<TrangThaiOut>` · type `TrangThaiAgent`, `TrangThaiOut` — Task 10 (module platform) import từ đây, KHÔNG từ `features/agent/api`.

- [ ] **Step 1: Viết file**

```ts
// src/features/agent/contracts.ts
/**
 * MẶT TIỀN công khai của module agent — module khác CHỈ được import file này
 * (`tests/module-boundaries.test.ts`, Luật 3). Có mặt vì panel Thử agent ở màn
 * API Keys (module platform) cần biết agent đã Sẵn sàng chưa (HT01 §2.5).
 */
export { docTrangThai } from './api'
export type { TrangThaiAgent, TrangThaiOut } from './api'
```

- [ ] **Step 2: Kiểm cổng ranh giới + tsc**

Run: `npx vitest run tests/module-boundaries.test.ts && npx tsc -b --force`
Expected: PASS.

- [ ] **Step 3: Format + commit**

```bash
npx prettier --write src/features/agent/contracts.ts
git add src/features/agent/contracts.ts
git commit -m "feat: mặt tiền contracts cho module agent (trạng thái agent cho màn API Keys)"
```

---

### Task 8: Hợp đồng thử agent — client + MSW fake

**Files:**
- Modify: `src/features/platform/api.ts` (thêm `thuAgent`)
- Modify: `src/lib/msw/handlers.ts` (thêm `POST /api/v1/agent/try`)

**Interfaces:**
- Produces: `thuAgent(keyId: number, message: string): Promise<TraLoiThu>` với `TraLoiThu = { readonly reply: string }` — Task 10 dùng. Endpoint: `POST /api/v1/agent/try`, body `{ keyId, message }`, lỗi theo khuôn `{error:{code,message}}` (spec §3.3: 409 khi agent chưa sẵn sàng · 404 khi khoá hết hiệu lực · 404/501 từ backend chưa có endpoint ⇒ FE hiện «chưa đấu nối»).

- [ ] **Step 1: Thêm client vào `features/platform/api.ts`** (dưới `thuHoiKhoa`)

```ts
/**
 * Thử agent bằng một khoá đã chọn — hợp đồng do FE ĐỊNH TRƯỚC, backend làm sau
 * (spec 2026-08-07 §3.3 + §5.2). Backend thật chưa có endpoint này: 404/501 là
 * tín hiệu «chưa đấu nối», panel phải nói thật thay vì giả vờ chat được.
 * Đường đi đúng kênh khách dùng (HT01 BR03) là bài backend phải giải — không
 * phải việc của client này.
 */
export interface TraLoiThu {
  readonly reply: string
}

export function thuAgent(keyId: number, message: string): Promise<TraLoiThu> {
  return goi<TraLoiThu>('/api/v1/agent/try', {
    method: 'POST',
    body: JSON.stringify({ keyId, message }),
  })
}
```

- [ ] **Step 2: Thêm handler MSW** — trong `src/lib/msw/handlers.ts`, ngay SAU handler `http.delete('/api/v1/agent/keys/:id', …)` để cùng cụm khoá:

```ts
  // Thử agent qua khoá — endpoint backend CHƯA có (spec 2026-08-07 §5.2); fake
  // để dev thấy panel chạy. Trả lời nhại lại câu hỏi để nhìn là biết đồ giả.
  http.post('/api/v1/agent/try', async ({ request }) => {
    const { keyId, message } = (await request.json()) as { keyId?: number; message?: string }
    if (!KHOA_GIA.some((k) => k.id === keyId)) {
      return HttpResponse.json(
        { error: { code: 'NOT_FOUND', message: `Không có khoá ${keyId}` } },
        { status: 404 },
      )
    }
    return HttpResponse.json({
      reply: `Dạ em đã nhận câu «${message ?? ''}» — đây là trả lời thử từ môi trường dev.`,
    })
  }),
```

- [ ] **Step 3: Kiểm nhanh**

Run: `npx tsc -b --force && npx vitest run tests/khoa-dau-noi.test.tsx`
Expected: PASS (chưa màn nào gọi `thuAgent` — chỉ kiểm không vỡ gì).

- [ ] **Step 4: Format + commit**

```bash
npx prettier --write src/features/platform/api.ts src/lib/msw/handlers.ts
git add src/features/platform/api.ts src/lib/msw/handlers.ts
git commit -m "feat: hợp đồng POST /agent/try (client platform + MSW fake)"
```

---

### Task 9: Tên khoá bắt buộc khi tạo

**Files:**
- Modify: `src/features/platform/components/TaoKhoaDialog.tsx`
- Modify: `CLAUDE.md` (mục Design token: xoá ghi chú nợ `TaoKhoaDialog.tsx:21`; Gotcha nợ định dạng: 2 tệp → 1 tệp)
- Test: `tests/khoa-dau-noi.test.tsx`

**Interfaces:**
- Consumes: `onTao(label)` giữ nguyên chữ ký.
- Produces: nút Tạo khoá disabled khi nhãn trống — panel Thử agent (Task 10) dựa vào việc mọi khoá mới đều có tên để dropdown không có dòng «—».

- [ ] **Step 1: Viết test đỏ** — thêm vào `tests/khoa-dau-noi.test.tsx` (dùng khuôn `datApi()`/`boot()` sẵn trong file, xem các bài tạo khoá đang có để lấy đúng cách mở dialog):

```tsx
describe('tên khoá bắt buộc (spec 2026-08-07 §3.3)', () => {
  it('nhãn trống thì nút Tạo khoá khoá; gõ tên vào là mở', async () => {
    datApi()
    boot()
    await userEvent.click(await screen.findByRole('button', { name: /tạo khoá mới/i }))

    const nutTao = await screen.findByRole('button', { name: /^tạo khoá$/i })
    expect(nutTao).toBeDisabled()

    await userEvent.type(screen.getByLabelText(/nhãn/i), 'Pod chat production')
    expect(nutTao).toBeEnabled()

    // Toàn khoảng trắng = trống — trim trước khi xét.
    await userEvent.clear(screen.getByLabelText(/nhãn/i))
    await userEvent.type(screen.getByLabelText(/nhãn/i), '   ')
    expect(nutTao).toBeDisabled()
  })
})
```

(Tên hàm fixture/cách boot lấy theo file test hiện có — nếu file dùng tên khác `datApi`/`boot` thì theo tên trong file, KHÔNG bịa mới.)

- [ ] **Step 2: Chạy — phải đỏ**

Run: `npx vitest run tests/khoa-dau-noi.test.tsx`
Expected: bài mới FAIL (`expect(nutTao).toBeDisabled()` — nút đang luôn enabled).

- [ ] **Step 3: Sửa `TaoKhoaDialog.tsx`**

- Docstring đoạn «Nhãn TUỲ CHỌN…» thay bằng:

```
 * Nhãn BẮT BUỘC (đổi 2026-08-07): panel Thử agent ở màn API Keys chọn khoá theo
 * tên — một khoá không tên là một dòng «—» trong dropdown, không chọn nổi. Lý
 * lẽ cũ (đừng chặn khoá dùng một lần để thử) hết đứng: giờ chính việc THỬ cần
 * cái tên.
```

- Nhãn field: `{t({ vi: 'Nhãn', en: 'Label' })}` (bỏ «tuỳ chọn»).
- Câu phụ dưới ô: `{t({ vi: 'Để nhận ra khoá nào là của pod nào — và để chọn khoá khi thử agent.', en: 'So you can tell keys apart when revoking — and pick one when trying the agent.' })}`
- Nút submit: `disabled={dangGui || nhan.trim() === ''}`.
- `guiForm`: thêm guard `if (nhan.trim() === '') return` (phòng Enter trong ô khi nút khoá).
- Dòng 21 `rounded-[10px]` → `rounded-md` (CLAUDE.md dặn: ai dọn file này thì dọn luôn — và task này buộc `prettier --write` trọn file, tức đang dọn nợ của nó).

- [ ] **Step 4: Chạy — phải xanh**

Run: `npx vitest run tests/khoa-dau-noi.test.tsx`
Expected: PASS cả file (các bài cũ tạo khoá có nhãn sẵn nên không vỡ; nếu có bài cũ tạo khoá với nhãn TRỐNG thì sửa bài đó điền nhãn — hành vi cũ đã chết theo spec).

- [ ] **Step 5: Cập nhật CLAUDE.md**

- Mục «Design token — hai luật»: xoá đoạn «Còn đúng một chỗ chưa vào khuôn… `TaoKhoaDialog.tsx:21`».
- Gotcha nợ định dạng: sửa «còn 2 tệp» → «còn 1 tệp: `src/routeTree.gen.ts` (tệp sinh)».
- Change Log thêm dòng (làm ở Task 11 gộp một thể cũng được — nếu gộp thì ghi chú lại đây).

- [ ] **Step 6: Format + commit**

```bash
npx prettier --write src/features/platform/components/TaoKhoaDialog.tsx tests/khoa-dau-noi.test.tsx
git add src/features/platform/components/TaoKhoaDialog.tsx tests/khoa-dau-noi.test.tsx CLAUDE.md
git commit -m "feat: tên khoá API bắt buộc khi tạo — dropdown thử agent chọn theo tên"
```

⚠️ CLAUDE.md đang có sửa đổi dở CỦA VIỆC KHÁC trong working tree — trước khi add, `git diff CLAUDE.md` xem phần dở đó là gì; chỉ commit khi phần sửa của mình tách bạch được (nếu không tách được, để CLAUDE.md sang Task 11 và ghi chú).

---

### Task 10: Panel Thử agent trên màn API Keys

**Files:**
- Create: `src/features/platform/components/ThuAgentPanel.tsx`
- Modify: `src/features/platform/components/TichHopApiScreen.tsx`
- Test: `tests/thu-agent.test.tsx` (mới)

**Interfaces:**
- Consumes: `thuAgent`/`TraLoiThu`/`LoiApi` từ `../api` (Task 8) · `docTrangThai` + `TrangThaiAgent` từ `@/features/agent/contracts` (Task 7) · type `Khoa` từ `../api` · `useLang` từ `@/i18n`.
- Produces: `ThuAgentPanel({ khoa: readonly Khoa[] })` — TichHopApiScreen truyền `data.keys` vào.

- [ ] **Step 1: Viết test đỏ — `tests/thu-agent.test.tsx`**

Khuôn boot chép từ `tests/khoa-dau-noi.test.tsx` (đổi `initialEntries` thành `['/api-keys']` nếu chưa phải):

```tsx
/**
 * Panel Thử agent trên màn API Keys (spec 2026-08-07 §3.3).
 *
 * Ba lời hứa: (1) gate hai điều kiện, mỗi điều kiện nói đúng câu của nó;
 * (2) chat đi qua khoá ĐÃ CHỌN — request mang keyId; (3) backend chưa có
 * endpoint thì nói «chưa đấu nối», không giả vờ (nguyên tắc HT01 §4: hệ thống
 * được phép hỏng, không được phép nói dối).
 */
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

const KHOA = [
  {
    id: 1,
    key_prefix: 'ody_ag_aaaa',
    label: 'Pod chat production',
    created_at: '2026-08-01T09:00:00Z',
    last_used_at: null,
  },
]

function datApi(opts: { keys?: unknown[]; trangThai?: string } = {}) {
  server.use(
    http.get('/api/v1/agent/keys', () =>
      HttpResponse.json({ endpoint_url: 'https://agent.test/anphu', keys: opts.keys ?? KHOA }),
    ),
    http.get('/api/v1/config/status', () =>
      HttpResponse.json({
        trangThaiAgent: opts.trangThai ?? 'san_sang',
        coBanNhap: false,
        version: 3,
        schemaVersionLive: 3,
      }),
    ),
  )
}

function boot() {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/api-keys'] }),
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

describe('Thử agent — gate', () => {
  it('chưa có khoá nào thì bảo tạo khoá trước, ô nhập khoá', async () => {
    datApi({ keys: [] })
    boot()

    expect(await screen.findByText(/tạo khoá api trước/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/thử/i)).toBeDisabled()
  })

  it('agent chưa sẵn sàng thì nói thật và khoá ô nhập', async () => {
    datApi({ trangThai: 'dang_cap' })
    boot()

    expect(await screen.findByText(/chưa sẵn sàng để thử/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/thử/i)).toBeDisabled()
  })
})

describe('Thử agent — chat', () => {
  it('chọn khoá, gửi câu hỏi → request mang keyId, trả lời hiện ra', async () => {
    datApi()
    let body: { keyId?: number; message?: string } | null = null
    server.use(
      http.post('/api/v1/agent/try', async ({ request }) => {
        body = (await request.json()) as { keyId?: number; message?: string }
        return HttpResponse.json({ reply: 'Dạ em nghe rõ ạ.' })
      }),
    )
    boot()

    const chon = await screen.findByLabelText(/khoá dùng để thử/i)
    await userEvent.selectOptions(chon, '1')
    await userEvent.type(screen.getByPlaceholderText(/thử/i), 'Còn căn 2PN không?')
    await userEvent.click(screen.getByRole('button', { name: /gửi/i }))

    expect(await screen.findByText('Dạ em nghe rõ ạ.')).toBeInTheDocument()
    await waitFor(() => expect(body).toEqual({ keyId: 1, message: 'Còn căn 2PN không?' }))
  })

  it('backend chưa có endpoint (404) → «chưa đấu nối», không giả vờ', async () => {
    datApi()
    server.use(
      http.post('/api/v1/agent/try', () =>
        HttpResponse.json({ error: { code: 'NOT_FOUND', message: 'x' } }, { status: 404 }),
      ),
    )
    boot()

    const chon = await screen.findByLabelText(/khoá dùng để thử/i)
    await userEvent.selectOptions(chon, '1')
    await userEvent.type(screen.getByPlaceholderText(/thử/i), 'alo')
    await userEvent.click(screen.getByRole('button', { name: /gửi/i }))

    expect(await screen.findByText(/chưa đấu nối/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy — phải đỏ**

Run: `npx vitest run tests/thu-agent.test.tsx`
Expected: FAIL (`findByText(/tạo khoá api trước/i)` không thấy).

- [ ] **Step 3: Viết `ThuAgentPanel.tsx`**

```tsx
// src/features/platform/components/ThuAgentPanel.tsx
/**
 * Panel Thử agent — chuyển từ màn Agent sang đây (spec 2026-08-07 §3.3): thử
 * phải đi qua đúng kênh khách dùng (HT01 BR03), tức qua một khoá API — nên nó
 * đứng cạnh bảng khoá, và chỉ mở khi có khoá + agent Sẵn sàng.
 *
 * Trạng thái agent đọc qua `features/agent/contracts` — mặt tiền công khai,
 * đúng Luật 3. Lịch sử chat sống trong state màn — rời màn là mất, chủ ý:
 * đây là ô thử, không phải kênh hội thoại.
 */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { docTrangThai } from '@/features/agent/contracts'
import { useLang } from '@/i18n'
import { LoiApi, thuAgent, type Khoa } from '../api'

interface TinNhan {
  readonly vai: 'ban' | 'agent'
  readonly noiDung: string
}

export function ThuAgentPanel({ khoa }: { khoa: readonly Khoa[] }) {
  const { t } = useLang()
  const trangThai = useQuery({ queryKey: ['config', 'status'], queryFn: docTrangThai })

  const [keyId, setKeyId] = useState<number | ''>('')
  const [cauHoi, setCauHoi] = useState('')
  const [tinNhan, setTinNhan] = useState<readonly TinNhan[]>([])

  const mGui = useMutation({
    mutationFn: (v: { keyId: number; message: string }) => thuAgent(v.keyId, v.message),
    onSuccess: (kq) => setTinNhan((c) => [...c, { vai: 'agent', noiDung: kq.reply }]),
  })

  const sanSang = trangThai.data?.trangThaiAgent === 'san_sang'
  const coKhoa = khoa.length > 0
  const moDuoc = coKhoa && sanSang

  function gui() {
    const message = cauHoi.trim()
    if (message === '' || keyId === '' || mGui.isPending) return
    setTinNhan((c) => [...c, { vai: 'ban', noiDung: message }])
    setCauHoi('')
    mGui.mutate({ keyId, message })
  }

  // 404/501 = backend chưa có endpoint thử (spec §5.2) — nói thật, không giả vờ.
  const chuaDauNoi =
    mGui.error instanceof LoiApi &&
    (mGui.error.code === 'NOT_FOUND' || mGui.error.code === 'NOT_IMPLEMENTED')

  return (
    <section className="rounded-xl bg-panel p-[18px] text-white">
      <div className="mb-3.5 flex items-center gap-2">
        <span
          className={`h-[7px] w-[7px] flex-none rounded-full ${moDuoc ? 'bg-live' : 'bg-panel-muted'}`}
        />
        <span className="text-[11px] font-semibold tracking-[0.07em] text-panel-muted uppercase">
          {t({ vi: 'Thử agent', en: 'Try the agent' })}
        </span>
      </div>

      <label className="mb-2.5 block">
        <span className="mb-1 block text-[11px] text-panel-muted">
          {t({ vi: 'Khoá dùng để thử', en: 'Key to try with' })}
        </span>
        <select
          aria-label={t({ vi: 'Khoá dùng để thử', en: 'Key to try with' })}
          value={keyId}
          disabled={!moDuoc}
          onChange={(e) => setKeyId(e.target.value === '' ? '' : Number(e.target.value))}
          className="w-full rounded-md border border-panel-line bg-transparent px-3 py-[9px] text-[12.5px] text-white outline-none focus:border-live/60 disabled:cursor-not-allowed"
        >
          <option value="" className="text-fg">
            {t({ vi: '— chọn khoá —', en: '— pick a key —' })}
          </option>
          {khoa.map((k) => (
            <option key={k.id} value={k.id} className="text-fg">
              {k.label}
            </option>
          ))}
        </select>
      </label>

      {tinNhan.length > 0 && (
        <ul className="mb-2.5 flex max-h-[260px] flex-col gap-2 overflow-y-auto">
          {tinNhan.map((m, i) => (
            <li
              key={i}
              className={`max-w-[85%] rounded-lg px-3 py-2 text-[12.5px] leading-[1.5] ${
                m.vai === 'ban' ? 'self-end bg-live/20' : 'self-start bg-panel-line/40'
              }`}
            >
              {m.noiDung}
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          gui()
        }}
        className="flex gap-2"
      >
        <input
          className="w-full rounded-md border border-panel-line bg-transparent px-3 py-[9px] text-[12.5px] text-white outline-none placeholder:text-muted focus:border-live/60 disabled:cursor-not-allowed"
          placeholder={t({ vi: 'Nhập câu hỏi để thử agent…', en: 'Ask something to try the agent…' })}
          value={cauHoi}
          disabled={!moDuoc}
          onChange={(e) => setCauHoi(e.target.value)}
        />
        <button
          type="submit"
          disabled={!moDuoc || keyId === '' || cauHoi.trim() === '' || mGui.isPending}
          className="rounded-md border border-panel-line px-3.5 py-[9px] text-[12.5px] font-medium text-white transition-colors hover:border-live/60 disabled:cursor-not-allowed disabled:opacity-45"
        >
          {mGui.isPending ? t({ vi: 'Đang gửi…', en: 'Sending…' }) : t({ vi: 'Gửi', en: 'Send' })}
        </button>
      </form>

      {!coKhoa && (
        <p className="mt-2.5 text-[11.5px] leading-[1.5] text-panel-muted">
          {t({
            vi: 'Tạo khoá API trước rồi mới thử được agent.',
            en: 'Create an API key first to try the agent.',
          })}
        </p>
      )}
      {coKhoa && !sanSang && (
        <p className="mt-2.5 text-[11.5px] leading-[1.5] text-panel-muted">
          {t({
            vi: 'Agent chưa sẵn sàng để thử.',
            en: 'The agent is not ready to try yet.',
          })}
        </p>
      )}
      {chuaDauNoi && (
        <p className="mt-2.5 text-[11.5px] leading-[1.5] text-panel-muted" role="alert">
          {t({
            vi: 'Chức năng thử chưa đấu nối — backend chưa có endpoint này.',
            en: 'Try-out is not wired up yet — the backend endpoint does not exist.',
          })}
        </p>
      )}
      {mGui.isError && !chuaDauNoi && (
        <p className="mt-2.5 text-[11.5px] leading-[1.5] text-badge-alert-fg" role="alert">
          {t({ vi: `Không gửi được: ${mGui.error.message}`, en: `Could not send: ${mGui.error.message}` })}
        </p>
      )}
    </section>
  )
}
```

- [ ] **Step 4: Nối vào `TichHopApiScreen.tsx`**

Bọc nội dung sau `tieuDe` vào lưới hai cột — cột trái là endpoint + bảng khoá (nguyên trạng), cột phải là panel, sticky như màn Agent cũ:

```tsx
<div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[1.6fr_1fr]">
  <div>
    {/* …section ENDPOINT_URL + section Khoá — giữ NGUYÊN VĂN… */}
  </div>
  <div className="xl:sticky xl:top-[88px]">
    <ThuAgentPanel khoa={data.keys} />
  </div>
</div>
```

(3 dialog giữ nguyên chỗ cuối JSX. Import `ThuAgentPanel` từ `./ThuAgentPanel`.)

- [ ] **Step 5: Chạy — phải xanh**

Run: `npx vitest run tests/thu-agent.test.tsx tests/khoa-dau-noi.test.tsx tests/boot.test.tsx && npx tsc -b --force`
Expected: PASS. (`boot.test.tsx` màn `api` dùng câu «Đường đấu nối giữa workspace này…» — vẫn render ngay, không chờ query.)

- [ ] **Step 6: Format + commit**

```bash
npx prettier --write src/features/platform/components/ThuAgentPanel.tsx src/features/platform/components/TichHopApiScreen.tsx tests/thu-agent.test.tsx
npx eslint src/features/platform/
git add src/features/platform/components/ThuAgentPanel.tsx src/features/platform/components/TichHopApiScreen.tsx tests/thu-agent.test.tsx
git commit -m "feat: panel Thử agent trên màn API Keys — chọn khoá theo tên, gate hai điều kiện"
```

---

### Task 11: Nghiệm thu toàn cục + CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (Change Log + mục cấu trúc nếu Task 9 chưa gộp)

- [ ] **Step 1: Chạy trọn bộ**

Run: `npx vitest run 2>&1 | tail -5`
Expected: pass = mốc Task 1 + số bài mới thêm (Task 2: +3 · Task 5: +4/−4 · Task 6: +4/−3 · Task 9: +1 · Task 10: +4 — đối chiếu con số thật); fail = **đúng 1 bài `convos-phien` có sẵn**, không hơn.

Run: `make lint`
Expected: sạch, TRỪ nợ định dạng đã ghi của `src/routeTree.gen.ts` (tệp sinh — nếu lint đỏ đúng mình tệp đó thì đạt; đỏ tệp khác là việc của mình, sửa).

- [ ] **Step 2: Soát bo góc + màu lạc**

Run: `grep -rn "rounded-\[" src/features/agent src/features/platform && grep -rn "#[0-9a-fA-F]\{3,6\}" src/features/agent src/features/platform --include='*.tsx'`
Expected: cả hai grep KHÔNG ra kết quả (exit 1).

- [ ] **Step 3: CLAUDE.md Change Log**

Thêm dòng:

```markdown
| 2026-08-07 | Màn Agent thành form + tabs theo lĩnh vực (spec 2026-08-07): kỹ năng chia tab chung/BĐS bằng `features/agent/kyNang.ts` (payload backend không đổi), xem trước gộp vào dialog Lưu và áp dụng, panel Thử ngay chuyển sang màn API Keys thành `ThuAgentPanel` (chọn khoá theo tên — nhãn khoá thành bắt buộc, hợp đồng `POST /agent/try` FE định trước + MSW fake, backend làm sau). Nhãn nav: «Agent & Kênh» → «Agent», «Tích hợp & API» → «API Keys». Nợ `rounded-[10px]` của `TaoKhoaDialog` đã dọn |
```

(Nếu Task 9 đã commit phần CLAUDE.md thì dòng Change Log này gộp chung ở đây; kiểm `git log --oneline -- CLAUDE.md` để biết.)

- [ ] **Step 4: Commit cuối**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-08-07-lam-lai-layout-agent-va-thu-agent-design.md docs/superpowers/plans/2026-08-07-lam-lai-layout-agent-va-thu-agent.md
git commit -m "docs: spec + plan làm lại layout Agent/API Keys, cập nhật CLAUDE.md"
```

(Spec + plan commit ở đây — chúng chưa từng được commit. Nhớ kiểm `git diff CLAUDE.md` tách phần sửa dở của việc khác như Task 9 đã dặn.)

- [ ] **Step 5: Báo cáo**

Ghi lại: con số vitest trước/sau, danh sách commit (`git log --oneline develop..HEAD`), và 3 open question của spec §5 (việc của backend, chưa làm).
