# Responsive cho điện thoại — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portal dùng được trên điện thoại (360–430px) và tablet, trong khi ≥1024px giữ nguyên từng pixel.

**Architecture:** Shell ba tầng (`mobile <768` · `tablet 768–1023` · `desktop ≥1024`) do hook `useKhoManHinh()` quyết định; mobile/tablet mở nav trong một lớp phủ (`LopPhu`) chứa đúng `Rail` + `NavPanel` hiện có. Phần còn lại là CSS: chỉ THÊM biến thể `max-md:`/`max-lg:` lên class sẵn có. JS chỉ dùng ở chỗ đổi cấu trúc (shell, hai màn master/detail).

**Tech Stack:** React 18 · Tailwind v4 · TanStack Router · vitest + Testing Library + MSW · Playwright-core (chạy tạm, KHÔNG thêm vào `package.json`).

**Spec:** [docs/superpowers/specs/2026-09-28-responsive-mobile-design.md](../specs/2026-09-28-responsive-mobile-design.md) — đọc trước Task 1.

## Global Constraints

- **Chỉ THÊM `max-md:` / `max-lg:`, không sửa/xoá class gốc.** Ngoại lệ phải nằm trong task nói rõ (chỉ: thêm class vào chuỗi điều kiện JS, và các thay đổi cấu trúc ở Task 3/8/9).
- Breakpoint: `md` = 768px, `lg` = 1024px (mặc định Tailwind) — không khai báo thang mới.
- jsdom (không có `matchMedia`) ⇒ `desktop`. **95 test hiện có không được sửa kỳ vọng.**
- Không mã màu ngoài `theme.css`; bo góc chỉ `rounded-sm|md|lg|full`; không `rounded-[Npx]` (luật design token CLAUDE.md).
- Nav đóng ⇒ **unmount**, không `hidden`.
- Ô nhập ở mobile ≥16px (`max-md:text-base`); nút icon ở mobile ≥40px.
- Chuỗi class Tailwind viết ĐỦ, không nội suy (`md:grid-cols-${n}` không vào CSS).
- Typecheck bằng `npm run build` (`tsc -b`), KHÔNG dùng `tsc --noEmit` (pass rỗng ở repo này).
- Commit kết thúc bằng dòng `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Đổi tầng khi lớp phủ đang mở** (xoay ngang điện thoại, kéo cửa sổ từ 700→1200px): lớp phủ phải tự đóng, desktop hiện lại panel theo `panelThuGon` cũ — không kẹt nền mờ. → test ở Task 3.
2. **Mở link `/convos/$phone?phien=…` trên điện thoại**: phải vào thẳng transcript, không phải danh sách. → test ở Task 8.
3. **`/chuyen-sale` không có `?ca=` trên mobile**: phải hiện danh sách, không nhảy vào `items[0]`. → test ở Task 9.
4. **Esc khi CommandPalette đang mở bên trên lớp phủ nav**: chỉ palette đóng? — chấp nhận cả hai cùng đóng, nhưng không được ném lỗi và focus phải về lại một phần tử còn trong DOM. → test ở Task 3.
5. **Bấm mục nav ĐANG sáng (cùng route)**: route không đổi nhưng lớp phủ vẫn phải đóng (vì đóng theo cú bấm, không theo pathname). → test ở Task 3.

## Chuẩn bị chung

```bash
cd /home/dungnd/Dungnd/dev/odyssey-project/odyssey-portal-frontend
export SCRATCH=/tmp/claude-1000/-home-dungnd-Dungnd-dev-odyssey-project/c2c96737-e756-4f4a-96d4-e61ec77c3520/scratchpad/responsive
```

`make dev` chạy ở cổng **5273** với MSW bật (không cần backend; `/api/v1/me` trả user giả đủ quyền).

## File Structure

| File | Trách nhiệm |
| --- | --- |
| `src/lib/khoManHinh.ts` (mới) | `BP`, `KhoManHinh`, `useKhoManHinh()` |
| `src/components/shell/LopPhu.tsx` (mới) | lớp phủ nav: nền mờ, Esc, focus, context `DongNav` |
| `src/components/shell/NavItem.tsx` | gọi `useDongNav()` khi bấm |
| `src/components/shell/Rail.tsx`, `NavPanel.tsx` | `max-lg:h-dvh` |
| `src/components/shell/Topbar.tsx` | prop `moNav`, nút ☰, ô tìm thành nút icon ở mobile |
| `src/components/shell/CommandPalette.tsx` | lề/chiều cao/cỡ chữ mobile |
| `src/routes/_app.tsx` | rẽ ba tầng |
| `src/components/ui/Bang.tsx`, `Truong.tsx` | hằng dùng chung: `KHUNG_MAN`, `CAO_O`, `O_LOC`, `NhomTab`, `O_CHUNG` |
| `src/features/**` | lề trang, màn vận hành, sửa lẻ màn cấu hình |
| `tests/man-hinh.ts` (mới) | giả lập `matchMedia` cho test |
| `tests/kho-man-hinh.test.ts`, `tests/shell-responsive.test.tsx`, `tests/responsive-nguon.test.ts` (mới) | test |
| `$SCRATCH/kiem-responsive.mjs` (KHÔNG commit) | đo tràn ngang + chụp ảnh bằng trình duyệt thật |

---

### Task 1: Công cụ đo bằng trình duyệt + ảnh desktop BASELINE

Phải làm TRƯỚC mọi thay đổi code — baseline chụp sau khi sửa là vô nghĩa.

**Files:**
- Create (không commit): `$SCRATCH/kiem-responsive.mjs`

**Interfaces:**
- Produces: lệnh `node $SCRATCH/kiem-responsive.mjs <do|chup> <thu-muc-ra> [rong,rong]` — `do` in `TRAN`/`ok` từng route × bề rộng và exit 1 nếu có `TRAN`; `chup` chỉ chụp. Env `PW` = đường dẫn `playwright-core/index.mjs`, `GOC` = origin (mặc định `http://localhost:5273`), `MO=1` = chụp thêm trạng thái mở (Task 12).

- [ ] **Step 1: Cài playwright-core vào scratch (không đụng repo)**

```bash
mkdir -p $SCRATCH/pw && npm i --prefix $SCRATCH/pw playwright-core@1 --no-audit --no-fund
ls $SCRATCH/pw/node_modules/playwright-core/index.mjs
```
Expected: đường dẫn in ra. Chrome dùng `/usr/bin/google-chrome` (đã có trên máy).

- [ ] **Step 2: Viết script**

`$SCRATCH/kiem-responsive.mjs`:

```js
// Đo tràn ngang + chụp ảnh. KHÔNG thuộc repo (spec §8.3: không thêm dependency).
const { chromium } = await import(process.env.PW)
const GOC = process.env.GOC ?? 'http://localhost:5273'
const [cheDo = 'do', ra = './ra', rongArg] = process.argv.slice(2)
const RONG = (rongArg ?? (cheDo === 'chup' ? '1280,1440' : '360,375,430,768'))
  .split(',')
  .map(Number)

const ROUTES = [
  '/', '/login', '/dang-ky', '/invite/abc', '/tao-workspace-dau-tien', '/khong-co-man-nay',
  '/dashboard', '/convos', '/convos/0901234567', '/chuyen-sale', '/chuyen-sale?ca=1',
  '/appts', '/quality', '/gaps', '/agent', '/kb', '/projects', '/pform?code=VHOP2',
  '/uform?code=VHOP2', '/finance', '/ky-nang-bds', '/domains', '/thu-agent', '/api-keys',
  '/users', '/roles', '/audit', '/billing', '/usage', '/pricing', '/settings',
  '/workspace', '/onboarding',
]

// Trạng thái MỞ (spec §7.1). Chỉ chạy khi MO=1 và bề rộng < 768.
const MO = [
  { ten: 'drawer', route: '/dashboard', bam: ['button[aria-label="Mở menu"]'] },
  { ten: 'ws-menu', route: '/dashboard', bam: ['button[aria-label="Mở menu"]', '[aria-haspopup="menu"] >> nth=0'] },
  { ten: 'user-menu', route: '/dashboard', bam: ['button[aria-label="Mở menu"]', '[aria-haspopup="menu"] >> nth=-1'] },
  { ten: 'palette', route: '/dashboard', bam: ['button[aria-label="Tìm màn"]'] },
  { ten: 'menu-hang', route: '/users', bam: ['button[aria-label^="Thao tác với"] >> nth=0'] },
  { ten: 'status-chip', route: '/pform?code=VHOP2', bam: ['button[aria-label^="Trạng thái dự án:"] >> nth=0'] },
]

const tenFile = (w, r) => `${ra}/${w}${r.replace(/[/?=&$]/g, '_')}.png`
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome' })
let tran = 0

async function do_(page, w, nhan) {
  const m = await page.evaluate(() => {
    const main = document.querySelector('main')
    return {
      doc: document.documentElement.scrollWidth,
      vw: window.innerWidth,
      mainDu: main ? main.scrollWidth - main.clientWidth : 0,
    }
  })
  const hong = m.doc > m.vw || m.mainDu > 0
  if (hong) tran++
  console.log(`${hong ? 'TRAN' : 'ok  '} ${w} ${nhan} doc=${m.doc} vw=${m.vw} mainDu=${m.mainDu}`)
}

for (const w of RONG) {
  const ctx = await browser.newContext({
    viewport: { width: w, height: 860 },
    deviceScaleFactor: 1,
    hasTouch: w < 1024,
  })
  const page = await ctx.newPage()
  await page.clock.setFixedTime(new Date('2026-09-28T09:00:00+07:00'))
  for (const r of ROUTES) {
    await page.goto(GOC + r, { waitUntil: 'networkidle' })
    await page.waitForTimeout(500)
    if (cheDo === 'do') await do_(page, w, r)
    await page.screenshot({ path: tenFile(w, r), animations: 'disabled', caret: 'hide' })
  }
  if (process.env.MO === '1' && w < 768) {
    for (const m of MO) {
      await page.goto(GOC + m.route, { waitUntil: 'networkidle' })
      await page.waitForTimeout(500)
      for (const s of m.bam) {
        await page.locator(s).click()
        await page.waitForTimeout(250)
      }
      await do_(page, w, `[mo:${m.ten}]`)
      await page.screenshot({ path: `${ra}/${w}_mo_${m.ten}.png`, animations: 'disabled' })
    }
  }
  await ctx.close()
}
await browser.close()
process.exit(cheDo === 'do' && tran > 0 ? 1 : 0)
```

- [ ] **Step 3: Chụp baseline desktop + đo mobile hiện trạng**

Chạy `make dev` ở nền (cổng 5273), rồi:

```bash
export PW=$SCRATCH/pw/node_modules/playwright-core/index.mjs
mkdir -p $SCRATCH/truoc $SCRATCH/do-truoc
node $SCRATCH/kiem-responsive.mjs chup $SCRATCH/truoc 1280,1440
node $SCRATCH/kiem-responsive.mjs do $SCRATCH/do-truoc | tee $SCRATCH/do-truoc.txt
grep -c '^TRAN' $SCRATCH/do-truoc.txt
```
Ghi mốc để Task 13 so diff: `git rev-parse HEAD > $SCRATCH/BASE`.

Expected: `truoc/` có 66 PNG (33 route × 2). Lệnh `do` exit 1 với rất nhiều `TRAN` — đó là hiện trạng cần sửa. Lưu số dòng `TRAN` vào báo cáo.

- [ ] **Step 4: Kiểm baseline có ổn định không**

```bash
mkdir -p $SCRATCH/truoc2 && node $SCRATCH/kiem-responsive.mjs chup $SCRATCH/truoc2 1280,1440
for f in $SCRATCH/truoc/*.png; do cmp -s "$f" "$SCRATCH/truoc2/$(basename $f)" || echo "KHONG ON DINH $(basename $f)"; done
```
Expected: không dòng nào. Nếu có: ghi lại danh sách route không ổn định (animation/dữ liệu ngẫu nhiên) — Task 13 so sánh các route đó bằng mắt thay vì `cmp`.

Không commit gì ở task này.

---

### Task 2: Hook `useKhoManHinh` + giả lập `matchMedia` cho test

**Files:**
- Create: `src/lib/khoManHinh.ts`
- Create: `tests/man-hinh.ts`
- Test: `tests/kho-man-hinh.test.ts`

**Interfaces:**
- Produces: `export const BP = { md: 768, lg: 1024 } as const` · `export type KhoManHinh = 'mobile' | 'tablet' | 'desktop'` · `export function useKhoManHinh(): KhoManHinh`
- Produces (test): `giaLapManHinh(rong: number): void` · `doiRong(rong: number): void` (bắn `change`) · `boGiaLap(): void`

- [ ] **Step 1: Viết helper giả lập**

`tests/man-hinh.ts`:

```ts
/**
 * jsdom không có `window.matchMedia` ⇒ `useKhoManHinh` trả `desktop` — nhờ vậy
 * mọi test cũ dựng đúng layout cũ. Test nào cần mobile/tablet gọi
 * `giaLapManHinh(rong)` và PHẢI `boGiaLap()` trong `afterEach`, nếu không test
 * sau trong cùng file chạy ở bề rộng giả.
 *
 * Chỉ hiểu `(max-width: Npx)` — đúng dạng truy vấn `lib/khoManHinh.ts` dùng.
 */
type Nghe = (e: MediaQueryListEvent) => void

let rongHienTai = 1440
const dsTruyVan: { q: string; nghe: Set<Nghe>; khop: boolean }[] = []

function khop(q: string, rong: number): boolean {
  const m = /max-width:\s*([\d.]+)px/.exec(q)
  return m ? rong <= Number(m[1]) : false
}

export function giaLapManHinh(rong: number): void {
  rongHienTai = rong
  dsTruyVan.length = 0
  window.matchMedia = (q: string): MediaQueryList => {
    const muc = { q, nghe: new Set<Nghe>(), khop: khop(q, rongHienTai) }
    dsTruyVan.push(muc)
    return {
      get matches() {
        return khop(q, rongHienTai)
      },
      media: q,
      onchange: null,
      addEventListener: (_: string, f: Nghe) => muc.nghe.add(f),
      removeEventListener: (_: string, f: Nghe) => muc.nghe.delete(f),
      addListener: (f: Nghe) => muc.nghe.add(f),
      removeListener: (f: Nghe) => muc.nghe.delete(f),
      dispatchEvent: () => false,
    } as unknown as MediaQueryList
  }
}

export function doiRong(rong: number): void {
  rongHienTai = rong
  for (const muc of dsTruyVan) {
    const moi = khop(muc.q, rong)
    if (moi === muc.khop) continue
    muc.khop = moi
    for (const f of muc.nghe) f({ matches: moi, media: muc.q } as MediaQueryListEvent)
  }
}

export function boGiaLap(): void {
  // @ts-expect-error — trả jsdom về đúng trạng thái gốc: KHÔNG có matchMedia
  delete window.matchMedia
  dsTruyVan.length = 0
}
```

- [ ] **Step 2: Viết test thất bại**

`tests/kho-man-hinh.test.ts`:

```ts
import { afterEach, describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { BP, useKhoManHinh } from '../src/lib/khoManHinh'
import { boGiaLap, doiRong, giaLapManHinh } from './man-hinh'

afterEach(boGiaLap)

describe('useKhoManHinh', () => {
  it('không có matchMedia (jsdom trần) ⇒ desktop — giữ nguyên mọi test cũ', () => {
    expect(window.matchMedia).toBeUndefined()
    expect(renderHook(() => useKhoManHinh()).result.current).toBe('desktop')
  })

  it.each([
    [360, 'mobile'],
    [BP.md - 1, 'mobile'],
    [BP.md, 'tablet'],
    [BP.lg - 1, 'tablet'],
    [BP.lg, 'desktop'],
    [1440, 'desktop'],
  ] as const)('%ipx ⇒ %s', (rong, mong) => {
    giaLapManHinh(rong)
    expect(renderHook(() => useKhoManHinh()).result.current).toBe(mong)
  })

  it('đổi bề rộng ⇒ render lại với tầng mới', () => {
    giaLapManHinh(1440)
    const { result } = renderHook(() => useKhoManHinh())
    act(() => doiRong(375))
    expect(result.current).toBe('mobile')
    act(() => doiRong(900))
    expect(result.current).toBe('tablet')
  })
})
```

- [ ] **Step 3: Chạy — phải FAIL**

Run: `npx vitest run tests/kho-man-hinh.test.ts`
Expected: FAIL — `Failed to resolve import "../src/lib/khoManHinh"`.

- [ ] **Step 4: Viết hook**

`src/lib/khoManHinh.ts`:

```ts
import { useSyncExternalStore } from 'react'

/**
 * Ba tầng màn hình của portal (spec 2026-09-28-responsive-mobile).
 *
 * `BP` PHẢI khớp breakpoint mặc định của Tailwind (`md` = 48rem, `lg` = 64rem):
 * class `max-md:`/`max-lg:` và hook này phải đổi tầng ở CÙNG một pixel, nếu
 * không sẽ có dải vài px mà CSS nói mobile còn JS nói tablet.
 *
 * `.02` trừ đi = cách Tailwind v4 viết `width < 48rem` bằng `max-width`.
 *
 * Không có `window.matchMedia` (jsdom) ⇒ `desktop`: test cũ dựng đúng layout cũ.
 */
export const BP = { md: 768, lg: 1024 } as const

export type KhoManHinh = 'mobile' | 'tablet' | 'desktop'

const Q_MOBILE = `(max-width: ${BP.md - 0.02}px)`
const Q_TABLET = `(max-width: ${BP.lg - 0.02}px)`

const coMatchMedia = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'

function doc(): KhoManHinh {
  if (!coMatchMedia()) return 'desktop'
  if (window.matchMedia(Q_MOBILE).matches) return 'mobile'
  if (window.matchMedia(Q_TABLET).matches) return 'tablet'
  return 'desktop'
}

function dangKy(bao: () => void): () => void {
  if (!coMatchMedia()) return () => {}
  const ds = [Q_MOBILE, Q_TABLET].map((q) => window.matchMedia(q))
  for (const m of ds) m.addEventListener('change', bao)
  return () => {
    for (const m of ds) m.removeEventListener('change', bao)
  }
}

export function useKhoManHinh(): KhoManHinh {
  return useSyncExternalStore(dangKy, doc, () => 'desktop')
}
```

- [ ] **Step 5: Chạy — phải PASS**

Run: `npx vitest run tests/kho-man-hinh.test.ts`
Expected: PASS (8 test).

- [ ] **Step 6: Commit**

```bash
git add src/lib/khoManHinh.ts tests/man-hinh.ts tests/kho-man-hinh.test.ts
git commit -m "feat(shell): hook useKhoManHinh — ba tầng mobile/tablet/desktop

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Shell ba tầng — `LopPhu`, `_app.tsx`, Topbar ☰, `NavItem` đóng lớp phủ

**Files:**
- Create: `src/components/shell/LopPhu.tsx`
- Modify: `src/components/shell/NavItem.tsx` (hàm `NavItem`)
- Modify: `src/components/shell/Topbar.tsx` (toàn bộ `<header>`)
- Modify: `src/components/shell/Rail.tsx:139` · `src/components/shell/NavPanel.tsx` (div gốc `sticky top-0 z-40 … h-screen w-[240px]`)
- Modify: `src/components/shell/CommandPalette.tsx:119,130,144`
- Modify: `src/routes/_app.tsx` (`AppLayout`)
- Modify: `CLAUDE.md` (mục mới dưới «Shell — rail + panel»)
- Test: `tests/shell-responsive.test.tsx`

**Interfaces:**
- Consumes: `useKhoManHinh`, `KhoManHinh` (Task 2); `giaLapManHinh`, `doiRong`, `boGiaLap` (Task 2)
- Produces: `LopPhu({ dong, nhan, children, lech }: { dong: () => void; nhan: string; children: ReactNode; lech?: 'trai' | 'sauRail' })` · `useDongNav(): (() => void) | null` · Topbar prop `moNav?: () => void` · nút ☰ có `aria-label="Mở menu"`, ô tìm có accessible name «Tìm màn» ở MỌI tầng.

- [ ] **Step 1: Viết test thất bại**

`tests/shell-responsive.test.tsx` — boot cả app qua `routeTree` thật (cùng kiểu `tests/ops-chuyen-sale.test.tsx`), để thử đúng `_app.tsx`:

```tsx
import { afterEach, describe, expect, it } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { boGiaLap, doiRong, giaLapManHinh } from './man-hinh'

afterEach(boGiaLap)

function boot(path = '/dashboard') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }) })
  render(
    <QueryClientProvider client={qc}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
  return router
}

const lopPhu = () => screen.queryByRole('dialog', { name: 'Điều hướng' })
const navMang = () => screen.queryByRole('navigation', { name: 'Mảng' })

describe('shell — mobile', () => {
  it('mặc định KHÔNG có rail/panel trong DOM; ☰ mở lớp phủ chứa cả hai', async () => {
    giaLapManHinh(375)
    boot()
    const nut = await screen.findByRole('button', { name: 'Mở menu' })
    expect(navMang()).not.toBeInTheDocument()
    await userEvent.click(nut)
    const phu = lopPhu()!
    expect(within(phu).getByRole('navigation', { name: 'Mảng' })).toBeInTheDocument()
    expect(phu.querySelector('[data-nav]')).not.toBeNull()
  })

  it('bấm mục RAIL: điều hướng nhưng lớp phủ VẪN mở', async () => {
    giaLapManHinh(375)
    const router = boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    const rail = within(lopPhu()!).getByRole('navigation', { name: 'Mảng' })
    const links = within(rail).getAllByRole('link')
    await userEvent.click(links[links.length - 1]!)
    await waitFor(() => expect(router.state.location.pathname).not.toBe('/dashboard'))
    expect(lopPhu()).toBeInTheDocument()
  })

  it('bấm mục PANEL ⇒ đóng và UNMOUNT (không hidden)', async () => {
    giaLapManHinh(375)
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    const muc = lopPhu()!.querySelector<HTMLAnchorElement>('[data-nav]:not([data-nav="dashboard"])')!
    await userEvent.click(muc)
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
    expect(document.querySelector('[data-nav]')).toBeNull()
  })

  it('bấm mục panel ĐANG SÁNG (cùng route) vẫn đóng', async () => {
    giaLapManHinh(375)
    boot('/dashboard')
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    await userEvent.click(lopPhu()!.querySelector<HTMLAnchorElement>('[data-nav="dashboard"]')!)
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
  })

  it('Esc đóng và trả focus về ☰; bấm nền mờ cũng đóng', async () => {
    giaLapManHinh(375)
    boot()
    const nut = await screen.findByRole('button', { name: 'Mở menu' })
    await userEvent.click(nut)
    await userEvent.keyboard('{Escape}')
    expect(lopPhu()).not.toBeInTheDocument()
    expect(nut).toHaveFocus()
    await userEvent.click(nut)
    await userEvent.click(screen.getByRole('button', { name: 'Đóng menu' }))
    expect(lopPhu()).not.toBeInTheDocument()
  })

  it('Esc khi palette mở bên trên lớp phủ: không lỗi, focus nằm trên phần tử còn trong DOM', async () => {
    giaLapManHinh(375)
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    await userEvent.keyboard('{Meta>}k{/Meta}')
    await userEvent.keyboard('{Escape}')
    expect(document.body.contains(document.activeElement)).toBe(true)
  })

  it('ô tìm vẫn có tên «Tìm màn» ở mobile (chữ chỉ ẩn bằng sr-only)', async () => {
    giaLapManHinh(375)
    boot()
    expect(await screen.findByRole('button', { name: 'Tìm màn' })).toBeInTheDocument()
  })
})

describe('shell — tablet', () => {
  it('rail có sẵn, panel mặc định THU GỌN; mở ra là lớp phủ, bấm mục thì đóng', async () => {
    giaLapManHinh(900)
    boot()
    expect(await screen.findByRole('navigation', { name: 'Mảng' })).toBeInTheDocument()
    expect(document.querySelector('[data-nav]')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Mở menu' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Mở thanh bên' }))
    const muc = lopPhu()!.querySelector<HTMLAnchorElement>('[data-nav]:not([data-nav="dashboard"])')!
    await userEvent.click(muc)
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
  })
})

describe('shell — đổi tầng khi lớp phủ đang mở', () => {
  it('mobile → desktop: lớp phủ đóng, panel hiện lại trong luồng', async () => {
    giaLapManHinh(375)
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    act(() => doiRong(1440))
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
    expect(document.querySelector('[data-nav]')).not.toBeNull()
    expect(screen.queryByRole('button', { name: 'Mở menu' })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy — phải FAIL**

Run: `npx vitest run tests/shell-responsive.test.tsx`
Expected: FAIL — không tìm thấy nút «Mở menu».

- [ ] **Step 3: Viết `LopPhu`**

`src/components/shell/LopPhu.tsx`:

```tsx
import { createContext, type ReactNode, useContext, useEffect, useRef } from 'react'

/**
 * Lớp phủ nav cho tablet/mobile (spec 2026-09-28-responsive-mobile §4).
 *
 * Chứa ĐÚNG `<Rail/>`/`<NavPanel/>` của desktop — không dựng nav thứ hai (hai nav
 * trông giống nhau sẽ lệch ở lần sửa sau, như bộ tab của Thử agent từng lệch).
 *
 * Đóng theo CÚ BẤM mục màn (context `DongNav`), KHÔNG theo đổi pathname: bấm rail
 * cũng đổi pathname (tới màn đầu của mảng) mà lớp phủ phải ở lại để người dùng
 * thấy các màn khác trong mảng; và bấm mục đang sáng không đổi pathname mà vẫn
 * phải đóng.
 *
 * Unmount khi đóng là việc của nơi gọi (`_app.tsx` render có điều kiện).
 */
const DongNav = createContext<(() => void) | null>(null)

/** `null` ngoài lớp phủ ⇒ `NavItem` trên desktop không đổi hành vi. */
export function useDongNav() {
  return useContext(DongNav)
}

export function LopPhu({
  dong,
  nhan,
  lech = 'trai',
  children,
}: {
  dong: () => void
  nhan: string
  /** `sauRail`: tablet — rail đã nằm trong luồng, lớp phủ mở ngay bên phải nó. */
  lech?: 'trai' | 'sauRail'
  children: ReactNode
}) {
  const khung = useRef<HTMLDivElement>(null)
  // `dong` đổi danh tính mỗi lần layout render; neo vào ref để effect chỉ chạy
  // lúc mount/unmount — nếu không mỗi lần render lại là focus bị giật về khung.
  const dongRef = useRef(dong)
  dongRef.current = dong

  useEffect(() => {
    const truoc = document.activeElement instanceof HTMLElement ? document.activeElement : null
    khung.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dongRef.current()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (truoc && document.body.contains(truoc)) truoc.focus()
    }
  }, [])

  return (
    <div className={`fixed inset-y-0 right-0 z-60 flex ${lech === 'sauRail' ? 'left-[68px]' : 'left-0'}`}>
      <button
        type="button"
        aria-label="Đóng menu"
        onClick={dong}
        className="absolute inset-0 cursor-default bg-fg/25"
      />
      <div
        ref={khung}
        role="dialog"
        aria-modal="true"
        aria-label={nhan}
        tabIndex={-1}
        className="relative flex h-dvh overscroll-contain shadow-noi outline-none"
      >
        <DongNav.Provider value={dong}>{children}</DongNav.Provider>
      </div>
    </div>
  )
}
```

Kiểm `z-60` có trong thang `@theme` chưa: `grep -n 'z-60\|--z' src/styles/theme.css`. Tailwind v4 sinh `z-60` từ số nguyên sẵn, không cần khai báo — nhưng nó phải NẰM DƯỚI `z-70` (palette/hộp thoại) và TRÊN `z-40` (rail/panel sticky). Kiểm `shadow-noi` đã là token (có dùng ở `Tip.tsx:84`).

- [ ] **Step 4: `NavItem` gọi đóng lớp phủ**

Trong `src/components/shell/NavItem.tsx`, thêm import và `onClick`:

```tsx
import { useDongNav } from './LopPhu'
```

```tsx
export function NavItem({ item, nested = false }: Props) {
  const { t } = useLang()
  const dongNav = useDongNav()
  // ...giữ nguyên các dòng hiện có...
  return (
    <Link
      to={item.path}
      data-nav={item.key}
      className={lop}
      activeProps={{ className: `${lop} ${ACTIVE}` }}
      onClick={() => dongNav?.()}
    >
```

- [ ] **Step 5: Rail/NavPanel cao theo `dvh` dưới 1024**

- `src/components/shell/Rail.tsx:139`: chuỗi class `<aside>` thêm `max-lg:h-dvh` ngay sau `h-screen`.
- `src/components/shell/NavPanel.tsx`: div gốc (`sticky top-0 z-40 flex h-screen w-[240px] …`) thêm `max-lg:h-dvh` sau `h-screen`.

- [ ] **Step 6: Topbar — ☰ + ô tìm thu thành nút icon**

`src/components/shell/Topbar.tsx`: đổi chữ ký và `<header>`; giữ mọi chú thích hiện có.

```tsx
export function Topbar({ moNav }: { moNav?: () => void } = {}) {
```

```tsx
    <header className="sticky top-0 z-30 flex h-[72px] items-center gap-3.5 border-b border-border bg-bg/86 px-7 backdrop-blur-[10px] max-md:h-14 max-md:gap-2 max-md:px-4">
      {/* ☰ CHỈ khi layout truyền `moNav` (mobile). Desktop giữ quyết định
          2026-08-24: nút thu gọn ở đáy rail, không lấn tiêu đề. Ở mobile không
          còn rail nên đây là chỗ duy nhất. */}
      {moNav && (
        <button
          type="button"
          aria-label="Mở menu"
          onClick={moNav}
          className="-ml-2 flex size-10 flex-none cursor-pointer items-center justify-center rounded-md text-nav hover:bg-fill-strong"
        >
          <Icon name="moPanel" className="size-5" />
        </button>
      )}
      <h1 className="min-w-0 flex-1 truncate text-[22px] font-bold tracking-[-0.02em] text-fg max-md:text-[18px]">
```

Nút tìm — thêm class, KHÔNG xoá class nào:

```tsx
        className={`${CAO_O} flex w-[248px] flex-none items-center gap-2.5 rounded-md border border-border-field bg-surface px-3 text-[13.5px] transition-colors hover:border-border-strong max-md:w-10 max-md:justify-center max-md:px-0`}
      >
        <Icon name="search" className="size-4 flex-none text-muted-2" />
        <span className="text-muted-2 max-md:sr-only">{t({ vi: 'Tìm màn', en: 'Find a screen' })}</span>
        <kbd className="ml-auto flex-none rounded-sm border border-border-field bg-fill px-1.5 py-[1px] font-mono text-[11px] text-muted-2 max-md:hidden">
```

`CAO_O` sẽ thành `h-9 max-md:h-10` ở Task 4 — nút 40px tự đến từ đó.

- [ ] **Step 7: CommandPalette ở mobile**

`src/components/shell/CommandPalette.tsx`:
- dòng 119: thêm `max-md:pt-4` vào cuối chuỗi.
- dòng 130: thêm `max-md:max-h-[calc(100dvh-2rem)]`.
- dòng 144 (ô nhập): thêm `max-md:text-base`.

- [ ] **Step 8: `_app.tsx` rẽ ba tầng**

Thay thân `AppLayout` (giữ nguyên hai khối chú thích lớn hiện có, đặt lại đúng chỗ):

```tsx
import { useEffect, useState } from 'react'
import { LopPhu } from '@/components/shell/LopPhu'
import { useKhoManHinh } from '@/lib/khoManHinh'
```

```tsx
function AppLayout() {
  /* (giữ chú thích `panelThuGon` 2026-08-24 ở đây) */
  const [panelThuGon, setPanelThuGon] = useState(false)
  /**
   * Tablet/mobile (2026-09-28): nav mở trong LỚP PHỦ thay vì đẩy nội dung. State
   * riêng, không dùng lại `panelThuGon`: desktop nhớ lựa chọn thu/mở của nó, còn
   * lớp phủ luôn bắt đầu ĐÓNG — đổi tầng (xoay máy, kéo cửa sổ) là đóng, để
   * không bao giờ kẹt một nền mờ trên desktop.
   */
  const kho = useKhoManHinh()
  const [phuMo, setPhuMo] = useState(false)
  useEffect(() => setPhuMo(false), [kho])
  const dong = () => setPhuMo(false)

  return (
    <SessionProvider>
      <div className="flex min-h-screen">
        {kho === 'desktop' && (
          <>
            <Rail panelThuGon={panelThuGon} onDoiThuGon={() => setPanelThuGon((v) => !v)} />
            {!panelThuGon && <NavPanel />}
          </>
        )}
        {kho === 'tablet' && (
          <>
            <Rail panelThuGon={!phuMo} onDoiThuGon={() => setPhuMo((v) => !v)} />
            {phuMo && (
              <LopPhu dong={dong} nhan="Điều hướng" lech="sauRail">
                <NavPanel />
              </LopPhu>
            )}
          </>
        )}
        {kho === 'mobile' && phuMo && (
          <LopPhu dong={dong} nhan="Điều hướng">
            <Rail />
            <NavPanel />
          </LopPhu>
        )}
        {/* (giữ chú thích `relative` dài ở đây) */}
        <main
          className={`relative h-screen min-w-0 flex-1 overflow-auto max-md:h-dvh ${phuMo ? 'max-lg:overflow-hidden' : ''}`}
        >
          <Topbar {...(kho === 'mobile' ? { moNav: () => setPhuMo(true) } : {})} />
          <ManTheoWorkspace />
        </main>
        {/* (giữ chú thích palette ở đây) */}
        <CommandPalette />
      </div>
    </SessionProvider>
  )
}
```

Ghi chú cho người thực thi: `Topbar {...}` trải có điều kiện vì `exactOptionalPropertyTypes` cấm truyền tường minh `undefined` (tiền lệ ở `tests/convos-phien.test.tsx`).

- [ ] **Step 9: Chạy test mới — phải PASS**

Run: `npx vitest run tests/shell-responsive.test.tsx`
Expected: PASS (9 test). Nếu test «Esc khi palette mở» thất bại vì palette không mở bằng `{Meta>}k` trong jsdom, kiểm cách `tests/command-palette.test.tsx` mở palette và dùng đúng cách đó.

- [ ] **Step 10: Chạy toàn suite — không test cũ nào đổi**

Run: `npx vitest run`
Expected: toàn bộ PASS. Đặc biệt `shell.test.tsx`, `module-boundaries.test.ts`, `command-palette.test.tsx`, `boot.test.tsx`. Nếu suite có test đỏ SẴN trước khi sửa: `git stash && npx vitest run > $SCRATCH/suite-truoc.txt; git stash pop` rồi so danh sách — chỉ được đỏ đúng các test đó.

- [ ] **Step 11: Cập nhật CLAUDE.md**

Thêm ngay sau đoạn «240px là số đo trên trình duyệt…» của mục «Shell — rail + panel»:

```markdown
## Shell responsive (2026-09-28)

Ba tầng do `useKhoManHinh()` (`lib/khoManHinh.ts`) quyết: **mobile <768** · **tablet 768–1023** · **desktop ≥1024** — hai con số khớp `md`/`lg` của Tailwind, đổi là đổi cả hai.

- **Desktop không đổi một class.** Mọi responsive là biến thể `max-md:`/`max-lg:` THÊM vào; class gốc là class desktop. Review: dòng nào sửa class không có tiền tố `max-*` phải có lý do.
- **Tablet**: rail ở lại, panel mặc định thu gọn, mở ra là **lớp phủ** (`LopPhu`, `lech="sauRail"`).
- **Mobile**: rail + panel rời luồng; ☰ ở Topbar (CHỈ mobile — desktop giữ nút ở đáy rail, quyết định 2026-08-24) mở `LopPhu` chứa **đúng** `<Rail/>` + `<NavPanel/>`. Không dựng nav thứ hai.
- **Lớp phủ đóng theo cú bấm mục màn** (`useDongNav()` trong `NavItem`), KHÔNG theo pathname: bấm rail đổi pathname mà phải ở lại; bấm mục đang sáng không đổi pathname mà phải đóng. Đóng = unmount.
- **jsdom = desktop** (không có `matchMedia`). Test mobile/tablet dùng `tests/man-hinh.ts` và PHẢI `boGiaLap()` trong `afterEach`.
- Luật «không sửa shell để thêm màn» **vẫn nguyên** — lần này sửa hành vi khung, không đặc-biệt-hoá màn nào.
```

- [ ] **Step 12: Commit**

```bash
git add src/components/shell src/routes/_app.tsx tests/shell-responsive.test.tsx CLAUDE.md
git commit -m "feat(shell): drawer cho mobile, panel phủ cho tablet; desktop giữ nguyên

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Primitive dùng chung + cổng văn bản

**Files:**
- Modify: `src/components/ui/Bang.tsx` — `CAO_O` (dòng 112), `O_LOC` (121), `KHUNG_MAN` (317), `NhomTab` (div gốc, ~dòng 596)
- Modify: `src/components/ui/Truong.tsx:49-50` — `O_CHUNG`
- Test: `tests/responsive-nguon.test.ts`

**Interfaces:**
- Produces: `CAO_O = 'h-9 max-md:h-10'` · `O_LOC`/`O_CHUNG` chứa `max-md:text-base` · `KHUNG_MAN` có bản `max-md:` theo topbar 56px.

- [ ] **Step 1: Viết test thất bại**

`tests/responsive-nguon.test.ts`:

```ts
/**
 * Cổng VĂN BẢN cho các lớp lỗi responsive mà jsdom không vẽ nên không bài render
 * nào bắt được (cùng lối `o-chon.test.ts`).
 *
 * 1. iOS Safari tự zoom khi focus một ô có chữ < 16px — màn nhảy phóng to và
 *    không tự thu lại. Mọi hằng ô nhập dùng chung phải có `max-md:text-base`.
 * 2. Chiều cao khung màn trừ 72px (topbar desktop) — ở mobile topbar là 56px.
 */
import { describe, expect, it } from 'vitest'
import { CAO_O, KHUNG_MAN, O_LOC } from '../src/components/ui/Bang'
import { O_CHUNG } from '../src/components/ui/Truong'

describe('primitive responsive', () => {
  it.each([
    ['O_CHUNG', O_CHUNG],
    ['O_LOC', O_LOC],
  ])('%s: chữ 16px ở mobile (chống iOS zoom)', (_, lop) => {
    expect(lop).toContain('max-md:text-base')
  })

  it('CAO_O: 40px ở mobile, 36px giữ nguyên ở desktop', () => {
    expect(CAO_O.split(' ')).toEqual(['h-9', 'max-md:h-10'])
  })

  it('KHUNG_MAN: bản mobile trừ đúng topbar 56px', () => {
    expect(KHUNG_MAN).toContain('h-[calc(100dvh-72px)]')
    expect(KHUNG_MAN).toContain('max-md:h-[calc(100dvh-56px)]')
    expect(KHUNG_MAN).toContain('max-md:px-4')
  })
})
```

- [ ] **Step 2: Chạy — phải FAIL**

Run: `npx vitest run tests/responsive-nguon.test.ts`
Expected: FAIL ở cả 4 test.

- [ ] **Step 3: Sửa hằng**

`src/components/ui/Bang.tsx`:

```ts
export const CAO_O = 'h-9 max-md:h-10'
```
```ts
export const O_LOC = `${CAO_O} rounded-md border border-border-strong px-3 text-[13.5px] focus:border-fg max-md:text-base`
```
```ts
export const KHUNG_MAN =
  'flex h-[calc(100dvh-72px)] flex-col overflow-hidden px-7 pb-6 max-md:h-[calc(100dvh-56px)] max-md:px-4 max-md:pb-4'
```

`NhomTab` — div gốc:

```tsx
      className={`${NEN_PILL} inline-flex gap-1 rounded-md p-1 max-md:max-w-full max-md:overflow-x-auto`}
```
và `TAB_CHUNG` (dòng ~560, gốc chung của `TAB`/`TAB_CHON`/`TAB_KHOA`) thêm `max-md:flex-none max-md:whitespace-nowrap` vào cuối chuỗi — một chỗ, ba hằng tự hưởng.

`src/components/ui/Truong.tsx` — `O_CHUNG`: thêm ` max-md:text-base` vào cuối chuỗi.

`grep -rn "CAO_O" src | grep -v "\${CAO_O}"` — nếu có chỗ nào so sánh chuỗi `CAO_O` hoặc tách nó ra, sửa theo.

- [ ] **Step 4: Chạy — PASS + toàn suite**

Run: `npx vitest run tests/responsive-nguon.test.ts && npx vitest run`
Expected: PASS tất cả.

- [ ] **Step 5: Commit**

```bash
git add src/components/ui/Bang.tsx src/components/ui/Truong.tsx tests/responsive-nguon.test.ts
git commit -m "feat(ui): primitive responsive — ô 16px, nút 40px, khung màn theo topbar mobile

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Lề trang và chiều cao khung ở mobile (quét cơ học)

**Files (Modify):** mỗi file dưới đây, ở class **lề trang ngoài cùng** chứa `px-7`, thêm `max-md:px-4` (và `max-md:py-4` nếu có `py-6`):

`src/features/agent/components/KhungSuaAgent.tsx` · `QuanLyLinhVuc.tsx` · `src/features/auth/components/HoSoScreen.tsx` · `UserAdmin.tsx` · `src/features/billing/components/UsageLuongDungScreen.tsx` · `src/features/kb/components/TaiLieuList.tsx` · `src/features/ops/components/HopThuSale.tsx` (hàm `Khung`) · `KhachList.tsx` · `PhienKhach.tsx` (3 chỗ `px-7 py-6`) · `TongQuanScreen.tsx` (hàm `Khung`) · `src/features/platform/components/NhatKyScreen.tsx` · `ThuAgentScreen.tsx` · `TichHopApiScreen.tsx` · `src/features/quality/components/FeedbackList.tsx` (`px-6` ⇒ `max-md:px-4`) · `src/features/realestate/components/CanForm.tsx` · `DuAnForm.tsx` · `DuAnList.tsx` · `src/features/workspace/components/CaiDatWorkspace.tsx` · `src/components/ScreenStub.tsx` (`p-7` ⇒ `max-md:p-4`).

Chiều cao khung (topbar mobile 56px, và `vh` ⇒ `dvh`):
- `PhienKhach.tsx:57` và `HopThuSale.tsx:23`: `const CAO_KHUNG = 'h-[calc(100vh-120px)] max-md:h-[calc(100dvh-88px)]'` (120 = 72 topbar + 48 lề dọc; mobile: 56 + 32).
- `DuAnList.tsx:76`: thêm `max-md:h-[calc(100dvh-56px)]`.
- `TongQuanScreen.tsx` `Khung`: xử lý ở Task 6.

**Interfaces:** không có.

- [ ] **Step 1: Liệt kê chính xác từng chỗ**

Run: `grep -rnE '\bpx-7\b|\bp-7\b' src --include=*.tsx | grep -v components/shell`
Mỗi dòng in ra: quyết định nó là lề trang (sửa) hay đệm bên trong một thẻ (để yên — ví dụ `px-7` trong một hộp thoại). Ghi quyết định vào mô tả commit.

- [ ] **Step 2: Sửa theo danh sách trên** — chỉ thêm class.

- [ ] **Step 3: Kiểm không có class gốc nào bị xoá**

Run: `git diff -U0 src | grep '^-' | grep -v '^---' | wc -l` và `git diff -U0 src | grep '^+' | grep -v '^+++' | wc -l`
Expected: số dòng `-` bằng số dòng `+` (mỗi dòng sửa là một dòng thay thế), và `git diff --word-diff src | grep -o '\[-[^]]*-\]'` không in ra token class nào (chỉ có `{+…+}` thêm vào).

- [ ] **Step 4: Toàn suite + đo**

Run: `npx vitest run` → PASS.
Run (dev server đang chạy): `node $SCRATCH/kiem-responsive.mjs do $SCRATCH/do-t5 375 | grep -c '^TRAN'` — ghi số, phải NHỎ HƠN số ở Task 1.

- [ ] **Step 5: Commit**

```bash
git add src
git commit -m "feat(ui): lề trang 16px và khung cao theo dvh ở mobile

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `/dashboard` một cột ở mobile

**Files:**
- Modify: `src/features/ops/components/TongQuanScreen.tsx` — `SPAN` (~180), `LUOI` (~198), `Khung` (~202)
- Test: `tests/overview-man.test.tsx` (thêm 1 test)

- [ ] **Step 1: Test thất bại** — thêm vào cuối `tests/overview-man.test.tsx` (dùng helper render sẵn có của file đó; tên `dung()`/`boot()` — đọc đầu file để lấy đúng tên):

```tsx
it('lưới có tầng mobile: một cột, không ép cao một viewport', async () => {
  // Kiểm CLASS vì jsdom không vẽ layout — hình học thật do kiem-responsive đo.
  const { container } = veRoi()
  await screen.findByTestId('o-hoi-thoai')
  const luoi = container.querySelector('[class*="grid-cols-[repeat(24"]')!
  expect(luoi.className).toContain('max-md:grid-cols-1')
  expect(luoi.className).toContain('max-md:grid-rows-none')
  for (const id of ['o-hoi-thoai', 'o-chuyen-sale', 'o-danh-gia', 'o-kien-thuc', 'o-usage']) {
    expect((await screen.findByTestId(id)).className).toContain('max-md:col-span-full')
  }
})
```

`veRoi()` là helper sẵn có ở đầu `tests/overview-man.test.tsx` (dòng ~45); nếu `datOverview(...)` là bắt buộc để các ô hiện ra, gọi nó trước như các test khác trong file.

- [ ] **Step 2: Chạy — FAIL**: `npx vitest run tests/overview-man.test.tsx` → test mới FAIL.

- [ ] **Step 3: Sửa**

```ts
const SPAN = {
  hoiThoai: 'col-span-[10] max-[1240px]:col-span-[12] max-md:col-span-full',
  chuyenSale: 'col-span-[7] max-[1240px]:col-span-[12] max-md:col-span-full',
  danhGia: 'col-span-[7] max-[1240px]:col-span-[12] max-md:col-span-full',
  kienThuc: 'col-span-[17] max-[1240px]:col-span-[12] max-md:col-span-full',
  usage: 'col-span-[7] max-[1240px]:col-span-[12] max-md:col-span-full',
} as const

const LUOI =
  'grid min-h-0 flex-1 grid-cols-[repeat(24,minmax(0,1fr))] grid-rows-[1fr_1fr] gap-3.5 max-[1240px]:grid-rows-[repeat(3,1fr)] max-md:flex-none max-md:grid-cols-1 max-md:grid-rows-none max-md:auto-rows-auto'

function Khung({ children }: { readonly children: ReactNode }) {
  return (
    <div className="flex h-[calc(100dvh-72px)] flex-col overflow-hidden px-7 py-6 max-md:h-auto max-md:overflow-visible max-md:px-4 max-md:py-4">
      {children}
    </div>
  )
}
```

(Nếu Task 5 đã thêm `max-md:px-4 max-md:py-4` vào `Khung`, chỉ thêm phần còn thiếu — không lặp class.)

Thẻ có chiều cao tối thiểu để biểu đồ còn chỗ vẽ: nếu ảnh chụp 375px (Step 5) cho thấy `BieuDoNgay` hoặc gauge bẹp về 0, thêm `max-md:min-h-[260px]` vào `SPAN.hoiThoai` và `SPAN.danhGia`.

- [ ] **Step 4: Chạy — PASS**: `npx vitest run tests/overview-man.test.tsx` → PASS.

- [ ] **Step 5: Xem ảnh thật**

`node $SCRATCH/kiem-responsive.mjs do $SCRATCH/do-t6 375` rồi mở `$SCRATCH/do-t6/375_dashboard.png` bằng công cụ Read (nó hiển thị ảnh). Kiểm: năm thẻ xếp dọc, nhãn trục biểu đồ không chồng nhau, không `TRAN` ở `/dashboard`. Nhãn trục chồng ⇒ trong `BieuDoNgay` giảm số mốc khi `useKhoManHinh() === 'mobile'` (chỉ mốc chẵn), kèm test ở `tests/overview-bieu-do.test.tsx` dùng `giaLapManHinh(375)`.

- [ ] **Step 6: Commit**

```bash
git add src/features/ops/components tests/overview-man.test.tsx
git commit -m "feat(ops): dashboard một cột, cuộn dọc ở mobile

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `/convos` — hàng khách hai dòng ở mobile

**Files:**
- Modify: `src/features/ops/components/KhachRow.tsx`
- Modify: `src/features/ops/components/KhachList.tsx` (ô lọc bề rộng cố định, nếu có)
- Test: `tests/convos-list.test.tsx` (thêm 1 test)

Bố cục mobile: hàng `flex-wrap`; avatar + cột tên chiếm dòng 1 cùng cột giờ (đẩy phải); cột tóm tắt xuống dòng 2 full-width, bỏ viền trái.

- [ ] **Step 1: Test thất bại** — thêm vào `tests/convos-list.test.tsx`, dựng như test hiện có trong file:

```tsx
it('hàng khách có tầng mobile: xuống dòng, cột tên không cố định 186px', async () => {
  dung() // helper sẵn có ở đầu file (dòng ~34)
  const hang = (await screen.findAllByRole('link')).find((a) => a.getAttribute('href')?.startsWith('/convos/'))!
  expect(hang.className).toContain('max-md:flex-wrap')
  expect(hang.querySelector('.w-\\[186px\\]')!.className).toContain('max-md:w-auto')
})
```

- [ ] **Step 2: Chạy — FAIL.** `npx vitest run tests/convos-list.test.tsx`

- [ ] **Step 3: Sửa `KhachRow.tsx`** (chỉ thêm class):

- `<Link>`: thêm `max-md:flex-wrap max-md:gap-x-3 max-md:gap-y-2 max-md:px-4`.
- cột tên `w-[186px] shrink-0`: thêm `max-md:w-auto max-md:min-w-0 max-md:flex-1`.
- cột tóm tắt `min-w-0 flex-1 self-stretch border-l … pl-4 pr-1.5`: thêm `max-md:order-last max-md:basis-full max-md:border-l-0 max-md:pl-0`.
- cột giờ `w-[132px] shrink-0 …`: thêm `max-md:w-auto max-md:border-l-0 max-md:pl-0`.
- chevron `›`: thêm `max-md:hidden` (hàng đã là link bấm được cả hàng; ở mobile chevron ăn chỗ của giờ).

`KhachList.tsx`: `grep -nE 'w-\[|min-w-\[' src/features/ops/components/KhachList.tsx` — mỗi ô lọc/ô tìm có bề rộng cố định thêm `max-md:w-full` (hoặc `max-md:min-w-0 max-md:flex-1` nếu nó nằm cạnh ô khác trong một hàng `flex-wrap`).

- [ ] **Step 4: Chạy — PASS** + `npx vitest run tests/convos-list.test.tsx tests/convos-thoigian.test.ts`.

- [ ] **Step 5: Xem ảnh** `375_convos.png` (chạy lại `do` 375). Kiểm: tên, SĐT, giờ, số phiên, tóm tắt, chip dự án đều đọc được; không `TRAN`.

- [ ] **Step 6: Commit** — `feat(ops): danh sách khách xếp hai dòng ở mobile`.

---

### Task 8: `/convos/$phone` — master/detail ở mobile

**Files:**
- Modify: `src/features/ops/components/PhienKhach.tsx`
- Test: `tests/convos-phien.test.tsx` (thêm `describe`)

**Interfaces:**
- Consumes: `useKhoManHinh` (Task 2); `giaLapManHinh`, `boGiaLap` (Task 2); hằng `DUONG_VE` (`components/ui/Bang.tsx`).

- [ ] **Step 1: Test thất bại** — thêm vào `tests/convos-phien.test.tsx` (dùng `dung(phone, phienMoDau)` sẵn có):

```tsx
import { afterEach } from 'vitest'
import { boGiaLap, giaLapManHinh } from './man-hinh'

describe('PhienKhach — mobile', () => {
  afterEach(boGiaLap)

  it('mặc định CHỈ danh sách phiên; chọn phiên ⇒ CHỈ transcript; «‹ Các phiên» quay về', async () => {
    giaLapManHinh(375)
    dung()
    const nutPhien = await screen.findAllByRole('button', { name: /lượt/ })
    expect(screen.queryByTestId('dong-phien')).not.toBeInTheDocument()
    await userEvent.click(nutPhien[0]!)
    expect(await screen.findByTestId('dong-phien')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /lượt/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '‹ Các phiên' }))
    expect(screen.queryByTestId('dong-phien')).not.toBeInTheDocument()
    expect((await screen.findAllByRole('button', { name: /lượt/ })).length).toBeGreaterThan(0)
  })

  it('mở link có phienMoDau ⇒ vào thẳng transcript của đúng phiên đó', async () => {
    giaLapManHinh(375)
    // 's-anh-2' = phiên thứ hai của 0912448111 trong fake — cùng giá trị test
    // phienMoDau sẵn có (dòng ~373) dùng; KHÔNG phải phiên đầu, nên chứng minh
    // được là mở đúng phiên được hỏi chứ không rơi về mặc định.
    dung('0912448111', 's-anh-2')
    await choPhien('s-anh-2')
    expect(screen.queryByRole('button', { name: /lượt/ })).not.toBeInTheDocument()
  })

  it('desktop (jsdom trần) vẫn hiện cả hai cột như cũ', async () => {
    dung()
    expect(await screen.findByTestId('dong-phien')).toBeInTheDocument()
    expect((await screen.findAllByRole('button', { name: /lượt/ })).length).toBeGreaterThan(0)
  })
})
```

Nút phiên có accessible name = toàn bộ chữ bên trong, luôn chứa «N lượt» (xem `PhienKhach.tsx` ~dòng 225) — nên `name: /lượt/` bắt đúng các hàng phiên. `choPhien(id)` là helper sẵn có (dòng ~48).

- [ ] **Step 2: Chạy — FAIL.** `npx vitest run tests/convos-phien.test.tsx`

- [ ] **Step 3: Sửa `PhienKhach.tsx`**

Thêm state và rẽ nhánh (sau `const [chon, setChon] = …`):

```tsx
  const mobile = useKhoManHinh() === 'mobile'
  /**
   * Mobile: một cột một lúc (spec §6.3). State RIÊNG, không suy từ `chon`: `sid`
   * luôn rơi về phiên đầu khi chưa chọn, nên suy từ đó thì mobile luôn nhảy
   * thẳng vào transcript. Mở link có `phienMoDau` là ý muốn xem phiên đó ⇒ true.
   * Nằm NGOÀI nhánh mobile/desktop: xoay máy giữa chừng không mất phiên đang xem.
   */
  const [dangXemPhien, setDangXemPhien] = useState(phienMoDau !== undefined)
  const hienDs = !mobile || !dangXemPhien
  const hienCt = !mobile || dangXemPhien
```

Nút phiên: `onClick={() => { setChon(p.sessionId); setDangXemPhien(true) }}`.

Cột danh sách — bọc `{hienDs && ( … )}` quanh `<div className="flex w-[300px] shrink-0 flex-col border-r border-border-soft">…</div>` và thêm `max-md:w-full max-md:border-r-0` vào class đó.

Cột chi tiết — bọc `{hienCt && ( … )}` quanh `<div className="flex min-w-0 flex-1 flex-col">…</div>`; phần tử đầu tiên bên trong:

```tsx
              {mobile && (
                <button
                  type="button"
                  onClick={() => setDangXemPhien(false)}
                  className={`${DUONG_VE} shrink-0 border-b border-border-soft px-4 py-2.5 text-left`}
                >
                  ‹ Các phiên
                </button>
              )}
```

Dòng thông tin phiên (`data-testid="dong-phien"`, `flex … gap-4`): thêm `max-md:flex-wrap max-md:gap-x-3 max-md:gap-y-1`.

Import: `import { useKhoManHinh } from '@/lib/khoManHinh'` và thêm `DUONG_VE` vào import sẵn có từ `@/components/ui/Bang` (hoặc thêm dòng import nếu file chưa import từ đó).

- [ ] **Step 4: Chạy — PASS** + toàn file `tests/convos-phien.test.tsx` (test desktop cũ không đổi).

- [ ] **Step 5: Xem ảnh** `375_convos_0901234567.png`. Không `TRAN`; transcript chưa hiện (đúng: mặc định danh sách).

- [ ] **Step 6: Commit** — `feat(ops): phiên khách dạng danh sách → chi tiết ở mobile`.

---

### Task 9: `/chuyen-sale` — master/detail theo URL ở mobile

**Files:**
- Modify: `src/features/ops/components/HopThuSale.tsx`
- Test: `tests/ops-chuyen-sale.test.tsx` (thêm `describe`; sửa `boot()` nhận path tuỳ chọn)

- [ ] **Step 1: Test thất bại**

Trong `tests/ops-chuyen-sale.test.tsx`, đổi `function boot()` thành `function boot(path = '/chuyen-sale')` và `initialEntries: [path]` (test cũ gọi `boot()` không đổi). Thêm:

```tsx
import { afterEach } from 'vitest'
import { boGiaLap, giaLapManHinh } from './man-hinh'

describe('Chuyển sale — mobile', () => {
  afterEach(boGiaLap)

  it('không có ?ca= ⇒ CHỈ danh sách (không nhảy vào ca đầu)', async () => {
    giaLapManHinh(375)
    boot()
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '‹ Danh sách' })).not.toBeInTheDocument()
    expect(screen.getByText('Ca cần gọi lại')).toBeInTheDocument()
  })

  it('có ?ca= ⇒ CHỈ chi tiết; «‹ Danh sách» về lại danh sách', async () => {
    giaLapManHinh(375)
    boot('/chuyen-sale?ca=1')
    await userEvent.click(await screen.findByRole('button', { name: '‹ Danh sách' }))
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '‹ Danh sách' })).not.toBeInTheDocument()
  })
})
```

Kiểm `ca=1` tồn tại trong fake: `grep -nE "id: 1\b" src/lib/msw/handlers.ts` ở khối escalation; không có thì dùng id đầu tiên của khối đó.

- [ ] **Step 2: Chạy — FAIL.**

- [ ] **Step 3: Sửa `HopThuSale.tsx`**

Sau `const dangMo = items.find(...) ?? items[0]` (dòng ~86):

```tsx
  const mobile = useKhoManHinh() === 'mobile'
  // Rẽ theo PARAM THÔ `caDangMo`, không theo `dangMo` — `dangMo` rơi về
  // `items[0]` khi URL không có ca, suy từ nó thì mobile luôn nhảy vào ca đầu.
  const hienDs = !mobile || caDangMo === undefined
  const hienCt = !mobile || caDangMo !== undefined
```

Lưới: `grid-cols-[minmax(300px,380px)_1fr]` thêm `max-md:grid-cols-1`.
Cột trái (`flex min-h-0 flex-col border-r border-border-soft`) bọc `{hienDs && (…)}`, thêm `max-md:border-r-0`.
Cột phải (`min-h-0 overflow-y-auto`) bọc `{hienCt && (…)}`; đầu cột:

```tsx
            {mobile && (
              <button
                type="button"
                onClick={() => moCa?.(undefined)}
                className={`${DUONG_VE} block w-full border-b border-border-soft px-4 py-2.5 text-left`}
              >
                ‹ Danh sách
              </button>
            )}
```

Ô tìm dòng ~146 `w-[240px]`: thêm `max-md:w-full max-md:text-base`. Hộp `GhiChuModal` (dòng ~267 lớp phủ `p-6`): thêm `max-md:p-4`; hộp (~274 `max-w-[460px]`): thêm `max-md:max-h-[calc(100dvh-2rem)] max-md:overflow-y-auto`.

Import `useKhoManHinh` và `DUONG_VE`.

- [ ] **Step 4: Chạy — PASS** cả file (test cũ desktop không đổi).

- [ ] **Step 5: Xem ảnh** `375_chuyen-sale.png` và `375_chuyen-sale_ca_1.png`.

- [ ] **Step 6: Commit** — `feat(ops): chuyển sale dạng danh sách → chi tiết theo URL ở mobile`.

---

### Task 10: `/quality` ở mobile

**Files:**
- Modify: `src/features/quality/components/FeedbackTongQuan.tsx:25-26,36`
- Modify: `src/features/quality/components/FeedbackList.tsx:99`
- Modify: `src/features/quality/components/FeedbackReviewCard.tsx:53`
- Test: `tests/quality-tong-quan.test.tsx` (thêm 1 test)

- [ ] **Step 1: Test thất bại** (dựng như test sẵn có trong file):

```tsx
it('khối tổng quan xếp dọc ở mobile', async () => {
  render(
    <FeedbackTongQuan
      total={5}
      theoSao={{ '1': 0, '2': 0, '3': 0, '4': 0, '5': 5 }}
      diemTrungBinh={5}
    />,
  )
  const diem = await screen.findByText(/Người dùng đánh giá/)
  const cotTrai = diem.parentElement!
  expect(cotTrai.className).toContain('max-md:w-full')
  expect(cotTrai.parentElement!.className).toContain('max-md:flex-col')
})
```

(Regex vì chữ trong JSX có dấu cách cuối: `Người dùng đánh giá `.)

- [ ] **Step 2: Chạy — FAIL.**

- [ ] **Step 3: Sửa** (chỉ thêm):
- `FeedbackTongQuan.tsx:25` `flex border-b …` + `max-md:flex-col`.
- `:26` cột `w-[220px] shrink-0 … border-r … px-6 py-5` + `max-md:w-full max-md:border-r-0 max-md:border-b max-md:px-4`.
- `:36` `flex flex-1 … px-6 py-4` + `max-md:px-4`.
- `FeedbackList.tsx:99` `… px-6 py-3` + `max-md:px-4`.
- `FeedbackReviewCard.tsx:53` `ml-[44px] …` + `max-md:ml-0 max-md:flex-wrap`.

- [ ] **Step 4: Chạy — PASS** + `npx vitest run tests/quality-list.test.tsx tests/quality-review-card.test.tsx tests/quality-tong-quan.test.tsx`.

- [ ] **Step 5: Xem ảnh** `375_quality.png`.

- [ ] **Step 6: Commit** — `feat(quality): tổng quan và thẻ đánh giá xếp dọc ở mobile`.

---

### Task 11: Màn cấu hình + màn công khai — «dùng được, không vỡ»

Việc này do phép đo dẫn đường, không đoán trước từng chỗ. Chỉ sửa chỗ gây `TRAN` hoặc che/không bấm được — **không** đổi thứ tự ô hay luồng xem/sửa.

**Files:** các file trong `src/features/{agent,kb,realestate,platform,auth,billing,workspace}/components/`, `src/components/landing/`, `src/routes/{login,dang-ky,invite.$token,tao-workspace-dau-tien}.tsx` — đúng file nào do Step 1 chỉ ra.

- [ ] **Step 1: Đo**

```bash
node $SCRATCH/kiem-responsive.mjs do $SCRATCH/do-t11 360,375,430,768 | grep '^TRAN' | tee $SCRATCH/t11-tran.txt
```

- [ ] **Step 2: Với mỗi route còn `TRAN`, tìm phần tử gây tràn**

Chạy trong Playwright (thêm tạm vào script hoặc dùng một script một lần trong `$SCRATCH`):

```js
await page.evaluate(() => {
  const vw = innerWidth
  return [...document.querySelectorAll('main *')]
    .filter((el) => el.getBoundingClientRect().right > vw + 1)
    .filter((el) => ![...el.children].some((c) => c.getBoundingClientRect().right > vw + 1))
    .slice(0, 10)
    .map((el) => `${el.tagName}.${String(el.className).slice(0, 120)}`)
})
```
In ra phần tử LÁ tràn mép phải — tìm class đó bằng `grep -rn` trong `src`.

- [ ] **Step 3: Sửa theo bảng quy tắc** (chỉ thêm class):

| Nguyên nhân | Sửa |
| --- | --- |
| ô/khối `w-[Npx]` hoặc `min-w-[Npx]` cố định (vd `DuAnList.tsx:132` `min-w-[190px] max-w-[300px]`, `:140` `w-[130px]`) | `max-md:w-full` / `max-md:min-w-0 max-md:max-w-none` |
| lưới `grid-cols-N` (N≥3) không tiền tố (vd `DoiAvatarDialog.tsx`), lưới KPI billing | `max-md:grid-cols-2` (ô nhỏ) hoặc `max-md:grid-cols-1` (ô có chữ dài) |
| lưới cố định `grid-cols-[274px_minmax(0,1fr)]`, `grid-cols-[1fr_1.18fr]`, `grid-cols-[1.25fr_1fr]`, `grid-cols-[1fr_1.05fr]` | `max-md:grid-cols-1` |
| `<table>` không nằm trong vùng `overflow-auto` (`UserAdmin.tsx`, `TaiLieuList.tsx`, `NormalizationDialog.tsx`, các chỗ dùng `Bang`) | bọc `<div className="overflow-x-auto">…</div>` — thêm phần tử bọc là ngoại lệ được phép; kiểm ảnh desktop ở Task 13 |
| hàng `flex` nhiều nút/chip không xuống dòng | `max-md:flex-wrap` |
| hộp thoại cao hơn màn | hộp: `max-md:max-h-[calc(100dvh-2rem)] max-md:overflow-y-auto` |
| side panel billing (`PanelKhung.tsx:47` đã `max-w-[min(760px,94vw)]`) | để yên nếu đo không tràn |
| `/thu-agent` khung hội thoại cao theo `vh` | `max-md:h-[calc(100dvh-…)]` theo topbar 56px |

- [ ] **Step 4: Lặp Step 1–3 tới khi `t11-tran.txt` rỗng.** Mỗi lượt chạy `npx vitest run` để chắc không test nào đỏ.

- [ ] **Step 5: Xem ảnh** 375px của: `/login`, `/dang-ky`, `/`, `/agent`, `/pform?code=VHOP2`, `/users`, `/usage`, `/pricing`, `/thu-agent`, `/api-keys`. Kiểm bằng mắt: không có nút bị che, không có chữ bị cắt mất nghĩa.

- [ ] **Step 6: Commit** — chia commit theo module (`feat(realestate): …`, `feat(billing): …` …), mỗi commit liệt kê route nó làm hết `TRAN`.

---

### Task 12: Lớp UI không phải route (menu, tooltip, lightbox, màn trạng thái)

**Files:** `src/components/shell/{WorkspaceSwitcher,UserMenu,LangToggle}.tsx`, `src/features/auth/components/MenuHang.tsx`, `src/features/realestate/components/{StatusChip,AnhLon}.tsx`, `src/components/ui/Truong.tsx` (dropdown `OChonNhieu`), `src/features/ops/components/Tip.tsx` — đúng file nào do Step 1 chỉ ra.

- [ ] **Step 1: Đo trạng thái MỞ**

```bash
MO=1 node $SCRATCH/kiem-responsive.mjs do $SCRATCH/do-t12 375 | grep 'mo:'
```
Expected hiện tại: có thể có `TRAN` ở `[mo:…]`. Mở các ảnh `$SCRATCH/do-t12/375_mo_*.png` bằng Read.

- [ ] **Step 2: Sửa**

| Chỗ | Sửa |
| --- | --- |
| menu thả `absolute right-0`/`left-0` tràn mép | `max-md:max-w-[calc(100vw-2rem)]`; nếu neo sai phía, đổi phía neo bằng `max-md:right-0 max-md:left-auto` (hoặc ngược lại) |
| menu trong lớp phủ nav bị cắt | lớp phủ `LopPhu` KHÔNG có `overflow-hidden` (đã thiết kế vậy ở Task 3); nếu `NavPanel` cắt, kiểm `overflow-auto` ở `<nav>` — menu phải render ngoài vùng cuộn đó hoặc mở lên trên |
| `AnhLon` | ảnh `max-md:max-h-[calc(100dvh-6rem)] max-md:max-w-full`; lớp phủ `p-6` + `max-md:p-3`; nút đóng ≥40px (`max-md:size-10`) |
| `Tip` (`max-w-[240px]`, `fixed`) | vị trí `trai` đã được kẹp trong code — chỉ kiểm bằng ảnh; nếu tràn, kẹp `trai` vào `[8, innerWidth - 248]` |
| dropdown `OChonNhieu` | `max-md:max-w-[calc(100vw-2rem)]` |

- [ ] **Step 3: Màn trạng thái** — mở ảnh `375_khong-co-man-nay.png` (404) và `375_invite_abc.png` (lời mời không hợp lệ). Chỉ sửa nếu chữ tràn (`break-words`).

- [ ] **Step 4: Lặp tới khi không còn `TRAN` ở `[mo:…]`.** `npx vitest run` → PASS.

- [ ] **Step 5: Commit** — `feat(ui): menu thả, lightbox, tooltip vừa màn điện thoại`.

---

### Task 13: Nghiệm thu toàn bộ

- [ ] **Step 1: Mobile không còn tràn**

```bash
MO=1 node $SCRATCH/kiem-responsive.mjs do $SCRATCH/sau-do 360,375,430,768; echo "exit=$?"
```
Expected: `exit=0`, không dòng `TRAN`.

- [ ] **Step 2: Desktop trùng pixel với baseline**

```bash
mkdir -p $SCRATCH/sau && node $SCRATCH/kiem-responsive.mjs chup $SCRATCH/sau 1280,1440
for f in $SCRATCH/truoc/*.png; do cmp -s "$f" "$SCRATCH/sau/$(basename $f)" || echo "KHAC $(basename $f)"; done
```
Expected: không dòng `KHAC` (trừ route đã ghi «không ổn định» ở Task 1 Step 4 — so các ảnh đó bằng mắt, đặt cạnh nhau bằng Read). Có `KHAC` thật ⇒ tìm class gốc đã bị đụng bằng `git diff $(cat $SCRATCH/BASE) -- <file của màn đó>` và sửa, KHÔNG cập nhật baseline.

- [ ] **Step 3: Kiểm luật «chỉ thêm»**

```bash
git diff $(cat $SCRATCH/BASE) --word-diff=plain -- src | grep -oE '\[-[^]]*-\]' | sort | uniq -c
```
Mỗi token bị xoá phải thuộc một trong: chữ ký hàm/JSX bọc có điều kiện (Task 3/8/9), `CAO_O`/`KHUNG_MAN`/`O_LOC` (Task 4, nhưng giá trị cũ vẫn nằm trong chuỗi mới). Token class Tailwind gốc bị xoá ⇒ lỗi, sửa.

- [ ] **Step 4: Cổng dự án**

```bash
make check && make build
```
Expected: cả hai xanh (`make build` chạy `tsc -b` — đây mới là typecheck thật).

- [ ] **Step 5: Kiểm trên điện thoại thật (người dùng)** — báo người dùng mở `http://<IP máy dev>:5273` trên điện thoại cùng mạng (cần `vite --host`; kiểm `vite.config.ts` có `server.host` chưa — không có thì chạy `npx vite --host --port 5273`) và thử: ☰ → đổi màn · `/convos` → mở một khách → mở một phiên → «‹ Các phiên» · `/chuyen-sale` → mở ca → «‹ Danh sách» · bấm vào một ô nhập (không bị zoom trên iPhone).

- [ ] **Step 6: Báo cáo** — số `TRAN` trước (Task 1) và sau (0), danh sách route đã so bằng mắt thay vì `cmp`, và những gì người dùng cần tự thử ở Step 5.
