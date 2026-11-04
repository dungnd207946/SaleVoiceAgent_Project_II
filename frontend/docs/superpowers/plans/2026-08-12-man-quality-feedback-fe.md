# Màn `/quality` (CSAT) — feedback agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng màn `/quality` (phần CSAT — un-defer) hiển thị feedback agent gửi lên (rating 1-5 sao + comment), và deep-link đúng phiên từ đó vào `/convos/$phone`.

**Architecture:** Feature folder mới `src/features/quality/` theo đúng khuôn `features/ops/` (api.ts phẳng, msw.ts riêng, components/). Route `/quality` đã có sẵn (đang là `ScreenStub`) — chỉ thay nội dung, không cần 4 bước "thêm màn mới". Deep-link tới phiên cụ thể cần sửa `convos.$phone.tsx` + `PhienKhach.tsx` nhận thêm search param `session`.

**Tech Stack:** React + TanStack Router (file-based, `validateSearch`) + TanStack Query v5, Tailwind v4 (token trong `styles/theme.css`, KHÔNG mã màu ngoài file đó), `lucide-react` qua `<Icon name="...">`, MSW cho dev/test, Vitest + Testing Library.

**⚠️ Phụ thuộc plan khác:** Plan này CẦN 4 thay đổi backend đã xong trước (`docs/superpowers/plans/2026-08-12-feedback-api-mo-rong.md`, repo `odyssey-portal-backend`): `PhienOut.phone`, filter `rating`/`session_id` cho `GET /agent/feedback`, `FeedbackOut.customer_name`/`phone`, `DanhSachFeedbackOut.theo_sao`/`diem_trung_binh`. MSW fake ở đây tự đứng được không cần backend chạy (đúng tinh thần "mọi module ship kèm fake"), nhưng khi nối backend thật phải đã có 4 thay đổi đó.

## Global Constraints

- **Không mã màu ngoài `styles/theme.css`** (luật Design token #1) — mọi màu dùng class Tailwind trỏ token (`text-ac`, `bg-badge-alert-bg`, ...), không `text-[#...]`.
- **Bo góc khoá 3 bậc** (luật #2): thẻ/bảng `rounded-lg`/`rounded-xl` (12px), ô nhập/nút/tab `rounded-md` (8px), badge/pill `rounded-full`. Không `rounded-[Npx]`.
- **Cỡ chữ theo đúng số đã chốt trong spec**: tên `15px`, thân/nhận xét `14px`, chữ phụ/ngày `12-13px`, nhãn uppercase `11px`.
- **Tên/số điện thoại hiện ĐẦY ĐỦ, không che** (spec §6).
- **Hàng nút dùng `HANG_NUT`** (`components/ui/Bang.tsx`) nếu có form/hộp thoại — màn này chỉ có nút "Xem thêm" căn giữa cuối danh sách, không phải hàng hành động nên KHÔNG dùng `HANG_NUT`.
- Chạy `make lint` (= `eslint` + `prettier` + `tsc -b`) xanh trước khi commit mỗi task — nhớ gotcha `tsc --noEmit` là cổng RỖNG, luôn dùng `npx tsc -b --force` nếu kiểm tay.
- `make routes` sau khi thêm/đổi file trong `src/routes/` (sinh lại `routeTree.gen.ts`).

---

### Task 1: Icon `star` vào `components/icons.tsx`

**Files:**
- Modify: `src/components/icons.tsx`

**Interfaces:**
- Produces: `IconName` union thêm `'star'` (tự động qua `keyof typeof LUCIDE`) — dùng bởi Task 2.

- [ ] **Step 1: Thêm import `Star` từ `lucide-react`**

Tìm dòng import `lucide-react` hiện có (cạnh `KeyRound`, `Shield`) và thêm `Star` vào cùng import đó.

- [ ] **Step 2: Đăng ký vào `LUCIDE`**

Tìm khối `const LUCIDE = { api: KeyRound, ..., shield: Shield, ... }` (dòng ~203-245) và thêm:

```ts
  star: Star,
```

- [ ] **Step 3: Kiểm type-check**

Run: `npx tsc -b --force`
Expected: 0 lỗi liên quan `icons.tsx`.

- [ ] **Step 4: Commit**

```bash
git add src/components/icons.tsx
git commit -m "feat: đăng ký icon star (lucide) cho hiển thị rating"
```

---

### Task 2: `components/ui/Sao.tsx` — component sao dùng chung

**Files:**
- Create: `src/components/ui/Sao.tsx`
- Test: `tests/sao.test.tsx`

**Interfaces:**
- Consumes: `Icon` từ `@/components/icons` (Task 1: `name="star"` hợp lệ).
- Produces: `export function Sao({ gia, kichThuoc }: { gia: number; kichThuoc?: number }): JSX.Element` — dùng bởi Task 6, 7, 12.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/sao.test.tsx`:

```tsx
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Sao } from '@/components/ui/Sao'

describe('Sao', () => {
  it('tô đủ 5 sao, đúng số lượng tô theo gia', () => {
    const { container } = render(<Sao gia={3} />)
    const sao = container.querySelectorAll('[data-sao]')
    expect(sao).toHaveLength(5)
    expect(container.querySelectorAll('[data-sao="on"]')).toHaveLength(3)
    expect(container.querySelectorAll('[data-sao="off"]')).toHaveLength(2)
  })

  it('gia=5 tô hết, gia=0 không tô cái nào', () => {
    const { container: c5 } = render(<Sao gia={5} />)
    expect(c5.querySelectorAll('[data-sao="on"]')).toHaveLength(5)

    const { container: c0 } = render(<Sao gia={0} />)
    expect(c0.querySelectorAll('[data-sao="on"]')).toHaveLength(0)
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `npx vitest run tests/sao.test.tsx`
Expected: FAIL — không tìm thấy module `@/components/ui/Sao`.

- [ ] **Step 3: Viết component**

Tạo `src/components/ui/Sao.tsx`:

```tsx
/**
 * Hiển thị rating 1-5 sao (chỉ đọc — không phải input chọn sao). Dùng ở
 * `/quality` (danh sách + tổng quan) và `PhienKhach.tsx` (feedback một phiên).
 *
 * `data-sao="on"/"off"` — móc test, không phải class hiển thị.
 */
import { Icon } from '@/components/icons'

const NAM_SAO = [1, 2, 3, 4, 5] as const

export function Sao({ gia, kichThuoc = 14 }: { gia: number; kichThuoc?: number }) {
  return (
    <span className="inline-flex items-center gap-0.5 text-ac">
      {NAM_SAO.map((n) => (
        <span key={n} data-sao={n <= gia ? 'on' : 'off'}>
          <Icon
            name="star"
            className={n <= gia ? 'fill-current text-ac' : 'text-border-strong'}
            style={{ width: kichThuoc, height: kichThuoc }}
          />
        </span>
      ))}
    </span>
  )
}
```

⚠️ Nếu `Icon` không nhận prop `className`/`style` trực tiếp (kiểm chữ ký hiện có trong `icons.tsx` — dòng có `interface` khai props của `Icon`), bọc icon trong `<span className={...} style={...}>` thay vì truyền thẳng vào `Icon`. Xác nhận bằng cách đọc `icons.tsx` phần khai props trước khi viết dòng này nếu bản trên không compile.

- [ ] **Step 4: Chạy lại test, xác nhận qua**

Run: `npx vitest run tests/sao.test.tsx`
Expected: PASS.

- [ ] **Step 5: Type-check + lint**

Run: `npx tsc -b --force && npx eslint src/components/ui/Sao.tsx`
Expected: sạch.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/Sao.tsx tests/sao.test.tsx
git commit -m "feat: component Sao — hiển thị rating 1-5 sao dùng chung"
```

---

### Task 3: `features/ops` — thêm `phone` vào `Phien` (mirror backend Task 1)

**Files:**
- Modify: `src/features/ops/api.ts` (`interface Phien`)
- Modify: `src/features/ops/msw.ts` (`PHIEN_ANH_1`, `PHIEN_ANH_2`, `PHIEN_GIA['_'][0]`)
- Test: `tests/convos-phien.test.tsx` (mở rộng)

**Interfaces:**
- Produces: `Phien.phone: string | null` — dùng bởi Task 11 (deep-link nhận `session_id`, không trực tiếp cần `phone` ở FE vì FE chỉ ĐỌC field này nếu cần hiện, nhưng contract phải khớp backend để `tsc` không lệch kiểu khi field thật xuất hiện trong response JSON runtime).

⚠️ Đây là bản chép tay của `ops.contracts.PhienOut` (Python) — lệch tên/thiếu trường không nổ lúc build, chỉ ra `undefined` lúc chạy (đúng cảnh báo đầu file `api.ts`). Bắt buộc làm task này TRƯỚC khi dùng `phone` ở bất kỳ đâu khác.

- [ ] **Step 1: Thêm `phone` vào interface `Phien`**

Sửa `src/features/ops/api.ts`, trong `interface Phien`, thêm sau `readonly source: string | null`:

```ts
  /** Số điện thoại của khách — `null` = nhóm «Chưa có số». */
  readonly phone: string | null
```

- [ ] **Step 2: Chạy type-check, xác nhận lỗi tại `msw.ts`**

Run: `npx tsc -b --force`
Expected: FAIL — `PHIEN_ANH_1`/`PHIEN_ANH_2`/phần tử `PHIEN_GIA['_']` thiếu thuộc tính `phone` bắt buộc (lỗi biên dịch, không phải test runtime — đây là "test thất bại" của task thuần-kiểu-dữ-liệu này).

- [ ] **Step 3: Thêm `phone` vào 3 fixture trong `msw.ts`**

Sửa `src/features/ops/msw.ts`:
- `PHIEN_ANH_1`: thêm `phone: '0912448111',` (khớp `KHACH_GIA.items[0].phone`).
- `PHIEN_ANH_2`: thêm `phone: '0912448111',` (cùng khách với `PHIEN_ANH_1`).
- Phần tử trong `PHIEN_GIA['_']` (nhóm «Chưa có số»): thêm `phone: null,`.

- [ ] **Step 4: Chạy lại type-check**

Run: `npx tsc -b --force`
Expected: PASS.

- [ ] **Step 5: Thêm test canh field mới không bị bỏ sót**

Thêm vào `tests/convos-phien.test.tsx` (cuối `describe` khối chính):

```tsx
it('phien mang đúng phone của khách đang xem', async () => {
  dung()
  // `PHIEN_ANH_1`/`PHIEN_ANH_2` (msw.ts) đều `phone: '0912448111'`, khớp
  // `dung()` mặc định mở khách này — không có gì trên màn HIỆN trực tiếp
  // `phone` (đã hiện sẵn ở header), test này chỉ canh KIỂU DỮ LIỆU không vỡ
  // khi component render (nếu `Phien.phone` bị đọc sai tên field, React sẽ
  // KHÔNG throw — nên đây là cổng type-level, xem Step 2, test này chỉ xác
  // nhận component vẫn render bình thường sau khi field mới thêm vào).
  expect(await screen.findByText(/27\/07\/2026/)).toBeInTheDocument()
})
```

- [ ] **Step 6: Chạy test**

Run: `npx vitest run tests/convos-phien.test.tsx`
Expected: PASS toàn bộ (test cũ + mới).

- [ ] **Step 7: Commit**

```bash
git add src/features/ops/api.ts src/features/ops/msw.ts tests/convos-phien.test.tsx
git commit -m "feat(ops): Phien mirror phone từ backend PhienOut"
```

---

### Task 4: `features/quality/api.ts` — types + fetch

**Files:**
- Create: `src/features/quality/api.ts`

**Interfaces:**
- Produces:
  - `interface Feedback { id: number; sessionId: string; rating: number; comment: string; createdAt: string; customerName: string | null; phone: string | null }`
  - `interface DanhSachFeedback { items: readonly Feedback[]; nextBeforeId: number | null; total: number; theoSao: Readonly<Record<'1'|'2'|'3'|'4'|'5', number>>; diemTrungBinh: number }`
  - `interface LocFeedback { ratings?: readonly number[]; beforeId?: number }`
  - `export const TRANG_MAC_DINH_FEEDBACK = 50`
  - `export async function danhSachFeedback(loc?: LocFeedback): Promise<DanhSachFeedback>`
  - `export async function feedbackCuaPhien(sessionId: string): Promise<Feedback | null>` — gọi cùng endpoint với `session_id` + `limit=1`, trả `null` nếu `items` rỗng (dùng ở Task 12).

- [ ] **Step 1: Viết file**

Tạo `src/features/quality/api.ts`:

```ts
/**
 * Client HTTP của màn `/quality` (CSAT) — feedback agent.
 *
 * Kiểu ở đây là bản chép tay của `modules/enrollment/contracts.py`
 * (`FeedbackOut`/`DanhSachFeedbackOut`). Lệch tên field thì màn hiện
 * `undefined` chứ không nổ — đổi thì đổi cùng commit.
 */

const GOC = '/api/v1/agent'

export const TRANG_MAC_DINH_FEEDBACK = 50

export class LoiApi extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

async function goi<T>(duong: string): Promise<T> {
  const res = await fetch(`${GOC}${duong}`)
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as {
      error?: { code?: string; message?: string }
    } | null
    throw new LoiApi(
      body?.error?.code ?? 'UNKNOWN',
      body?.error?.message ?? `${duong} → ${res.status}`,
    )
  }
  return (await res.json()) as T
}

export interface Feedback {
  readonly id: number
  readonly sessionId: string
  readonly rating: number
  readonly comment: string
  readonly createdAt: string
  readonly customerName: string | null
  readonly phone: string | null
}

export interface DanhSachFeedback {
  readonly items: readonly Feedback[]
  readonly nextBeforeId: number | null
  readonly total: number
  readonly theoSao: Readonly<Record<'1' | '2' | '3' | '4' | '5', number>>
  readonly diemTrungBinh: number
}

export interface LocFeedback {
  readonly ratings?: readonly number[]
  readonly beforeId?: number
}

/** Hình dạng RAW từ backend (snake_case) — `goi()` trả thẳng JSON, chuyển đổi ở đây. */
interface FeedbackOutTho {
  readonly id: number
  readonly session_id: string
  readonly rating: number
  readonly comment: string
  readonly created_at: string
  readonly customer_name: string | null
  readonly phone: string | null
}

interface DanhSachFeedbackOutTho {
  readonly items: readonly FeedbackOutTho[]
  readonly next_before_id: number | null
  readonly total: number
  readonly theo_sao: Readonly<Record<string, number>>
  readonly diem_trung_binh: number
}

function chuanHoaFeedback(r: FeedbackOutTho): Feedback {
  return {
    id: r.id,
    sessionId: r.session_id,
    rating: r.rating,
    comment: r.comment,
    createdAt: r.created_at,
    customerName: r.customer_name,
    phone: r.phone,
  }
}

export async function danhSachFeedback(loc: LocFeedback = {}): Promise<DanhSachFeedback> {
  const p = new URLSearchParams()
  p.set('limit', String(TRANG_MAC_DINH_FEEDBACK))
  for (const r of loc.ratings ?? []) p.append('rating', String(r))
  if (loc.beforeId !== undefined) p.set('before_id', String(loc.beforeId))

  const tho = await goi<DanhSachFeedbackOutTho>(`/feedback?${p.toString()}`)
  return {
    items: tho.items.map(chuanHoaFeedback),
    nextBeforeId: tho.next_before_id,
    total: tho.total,
    theoSao: {
      '1': tho.theo_sao['1'] ?? 0,
      '2': tho.theo_sao['2'] ?? 0,
      '3': tho.theo_sao['3'] ?? 0,
      '4': tho.theo_sao['4'] ?? 0,
      '5': tho.theo_sao['5'] ?? 0,
    },
    diemTrungBinh: tho.diem_trung_binh,
  }
}

export async function feedbackCuaPhien(sessionId: string): Promise<Feedback | null> {
  const p = new URLSearchParams()
  p.set('session_id', sessionId)
  p.set('limit', '1')
  const tho = await goi<DanhSachFeedbackOutTho>(`/feedback?${p.toString()}`)
  return tho.items[0] ? chuanHoaFeedback(tho.items[0]) : null
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc -b --force`
Expected: PASS (không có test runtime ở task này — thuần types + fetch, kiểm bằng cách dùng thật ở Task 5-8).

- [ ] **Step 3: Commit**

```bash
git add src/features/quality/api.ts
git commit -m "feat(quality): api.ts — client HTTP cho GET /agent/feedback"
```

---

### Task 5: `features/quality/msw.ts` — fake handlers

**Files:**
- Create: `src/features/quality/msw.ts`
- Modify: `src/lib/msw/handlers.ts` (import + spread `qualityHandlers`)

**Interfaces:**
- Consumes: `Feedback`/`DanhSachFeedback`-shaped raw JSON (snake_case — MSW trả nguyên hình dạng backend, KHÔNG qua `chuanHoaFeedback`, vì handler giả lập chính backend, không phải client).
- Produces: `export const qualityHandlers` — spread vào `HANDLERS` (`lib/msw/handlers.ts`).

- [ ] **Step 1: Viết file fixture + handler**

Tạo `src/features/quality/msw.ts`:

```ts
/**
 * Fake của màn `/quality` — 5 feedback mẫu, đủ ca biên: có/không comment,
 * có/không tên+sđt (khách ẩn danh), rating trải đều 1-5 để dải phân bố có
 * hình dạng thật khi dev không cần backend.
 */
import { http, HttpResponse } from 'msw'

interface FeedbackGia {
  id: number
  session_id: string
  rating: number
  comment: string
  created_at: string
  customer_name: string | null
  phone: string | null
}

const FEEDBACK_GIA: FeedbackGia[] = [
  {
    id: 5,
    session_id: 's-anh-1',
    rating: 5,
    comment: 'Trả lời nhanh, đúng ý.',
    created_at: '2026-08-12T09:00:00+07:00',
    customer_name: 'Nguyễn Minh Anh',
    phone: '0912448111',
  },
  {
    id: 4,
    session_id: 's-quang',
    rating: 2,
    comment: 'Agent trả lời chậm, hỏi 2 lần mới ra đúng thông tin căn hộ.',
    created_at: '2026-08-11T15:30:00+07:00',
    customer_name: 'Trần Quang',
    phone: '0987112222',
  },
  {
    id: 3,
    session_id: 's-an-1',
    rating: 4,
    comment: '',
    created_at: '2026-08-11T10:15:00+07:00',
    customer_name: null,
    phone: null,
  },
  {
    id: 2,
    session_id: 's-hoa',
    rating: 5,
    comment: 'Rất hài lòng.',
    created_at: '2026-08-10T14:00:00+07:00',
    customer_name: 'Lê Thị Hoa',
    phone: '0909000111',
  },
  {
    id: 1,
    session_id: 's-nam',
    rating: 1,
    comment: 'Không tìm được dự án tôi hỏi.',
    created_at: '2026-08-09T08:45:00+07:00',
    customer_name: 'Phạm Văn Nam',
    phone: '0933444555',
  },
]

function theoSao(danh_sach: FeedbackGia[]) {
  const dem: Record<string, number> = { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 }
  for (const f of danh_sach) dem[String(f.rating)] = (dem[String(f.rating)] ?? 0) + 1
  return dem
}

function diemTrungBinh(danh_sach: FeedbackGia[]) {
  if (danh_sach.length === 0) return 0
  return Math.round((danh_sach.reduce((s, f) => s + f.rating, 0) / danh_sach.length) * 100) / 100
}

export const qualityHandlers = [
  http.get('/api/v1/agent/feedback', ({ request }) => {
    const url = new URL(request.url)
    const ratings = url.searchParams.getAll('rating').map(Number)
    const sessionId = url.searchParams.get('session_id')

    let loc = FEEDBACK_GIA
    if (ratings.length > 0) loc = loc.filter((f) => ratings.includes(f.rating))
    if (sessionId) loc = loc.filter((f) => f.session_id === sessionId)

    return HttpResponse.json({
      items: loc,
      next_before_id: null,
      total: FEEDBACK_GIA.length,
      theo_sao: theoSao(FEEDBACK_GIA),
      diem_trung_binh: diemTrungBinh(FEEDBACK_GIA),
    })
  }),
]
```

⚠️ `theo_sao`/`diem_trung_binh`/`total` tính trên `FEEDBACK_GIA` TRỌN VẸN (không phải `loc` đã lọc) — mirror đúng bất biến backend (Task 4 của plan backend): thống kê không đổi theo filter.

- [ ] **Step 2: Ghép vào `HANDLERS`**

Sửa `src/lib/msw/handlers.ts`: thêm import `import { qualityHandlers } from '@/features/quality/msw'` cạnh `import { opsHandlers } from '@/features/ops/msw'`, và thêm `...qualityHandlers,` ngay sau dòng `...opsHandlers,` trong mảng `HANDLERS`.

- [ ] **Step 3: Type-check**

Run: `npx tsc -b --force`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/features/quality/msw.ts src/lib/msw/handlers.ts
git commit -m "feat(quality): msw.ts — fake GET /agent/feedback, 5 ca biên"
```

---

### Task 6: `FeedbackTongQuan.tsx` — dải thống kê

**Files:**
- Create: `src/features/quality/components/FeedbackTongQuan.tsx`
- Test: `tests/quality-tong-quan.test.tsx`

**Interfaces:**
- Consumes: `DanhSachFeedback` (Task 4) — chỉ đọc `total`, `theoSao`, `diemTrungBinh`.
- Produces: `export function FeedbackTongQuan({ total, theoSao, diemTrungBinh }: { total: number; theoSao: DanhSachFeedback['theoSao']; diemTrungBinh: number }): JSX.Element` — dùng bởi Task 8.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/quality-tong-quan.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FeedbackTongQuan } from '@/features/quality/components/FeedbackTongQuan'

describe('FeedbackTongQuan', () => {
  it('hiện điểm trung bình và tổng lượt', () => {
    render(
      <FeedbackTongQuan
        total={128}
        theoSao={{ '1': 4, '2': 5, '3': 10, '4': 30, '5': 79 }}
        diemTrungBinh={4.3}
      />,
    )
    expect(screen.getByText('4.3')).toBeInTheDocument()
    expect(screen.getByText(/128/)).toBeInTheDocument()
  })

  it('hiện đủ 5 dòng phân bố, kể cả sao có đếm 0', () => {
    render(
      <FeedbackTongQuan
        total={5}
        theoSao={{ '1': 0, '2': 0, '3': 0, '4': 0, '5': 5 }}
        diemTrungBinh={5}
      />,
    )
    // Mỗi dòng phân bố có `data-sao-hang="N"` — móc test, xem component.
    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.getByTestId(`phan-bo-${n}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('phan-bo-1')).toHaveTextContent('0')
    expect(screen.getByTestId('phan-bo-5')).toHaveTextContent('5')
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `npx vitest run tests/quality-tong-quan.test.tsx`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Viết component**

Tạo `src/features/quality/components/FeedbackTongQuan.tsx`:

```tsx
import { Sao } from '@/components/ui/Sao'
import type { DanhSachFeedback } from '../api'

const THU_TU_SAO = [5, 4, 3, 2, 1] as const

export function FeedbackTongQuan({
  total,
  theoSao,
  diemTrungBinh,
}: {
  total: number
  theoSao: DanhSachFeedback['theoSao']
  diemTrungBinh: number
}) {
  return (
    <div className="flex border-b border-border-soft">
      <div className="flex w-[220px] shrink-0 flex-col justify-center border-r border-border-soft px-6 py-5">
        <p className="text-[11px] uppercase tracking-wide text-muted-2">Điểm trung bình</p>
        <p className="text-[28px] font-semibold leading-none">{diemTrungBinh}</p>
        <div className="mt-1.5">
          <Sao gia={Math.round(diemTrungBinh)} kichThuoc={16} />
        </div>
        <p className="mt-2 text-[13px] text-muted">{total} lượt đánh giá</p>
      </div>
      <div className="flex flex-1 flex-col justify-center gap-1.5 px-6 py-4">
        {THU_TU_SAO.map((n) => {
          const dem = theoSao[String(n) as keyof DanhSachFeedback['theoSao']]
          const ty_le = total > 0 ? (dem / total) * 100 : 0
          return (
            <div key={n} data-testid={`phan-bo-${n}`} className="flex items-center gap-2 text-[13px]">
              <span className="w-[30px] text-right text-muted-2">{n}★</span>
              <div className="h-[7px] max-w-[280px] flex-1 rounded-full bg-fill">
                <div className="h-full rounded-full bg-ac" style={{ width: `${ty_le}%` }} />
              </div>
              <span className="w-8 text-muted-2 tabular-nums">{dem}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Chạy lại test, xác nhận qua**

Run: `npx vitest run tests/quality-tong-quan.test.tsx`
Expected: PASS.

- [ ] **Step 5: Type-check + lint**

Run: `npx tsc -b --force && npx eslint src/features/quality/components/FeedbackTongQuan.tsx`

- [ ] **Step 6: Commit**

```bash
git add src/features/quality/components/FeedbackTongQuan.tsx tests/quality-tong-quan.test.tsx
git commit -m "feat(quality): FeedbackTongQuan — dải thống kê điểm TB + phân bố sao"
```

---

### Task 7: `FeedbackReviewCard.tsx` — một khối feedback

**Files:**
- Create: `src/features/quality/components/FeedbackReviewCard.tsx`
- Test: `tests/quality-review-card.test.tsx`

**Interfaces:**
- Consumes: `Feedback` (Task 4), `Sao` (Task 2).
- Produces: `export function FeedbackReviewCard({ feedback }: { feedback: Feedback }): JSX.Element` — dùng bởi Task 8. Render `<Link to="/convos/$phone" params={{ phone }} search={{ session: feedback.sessionId }}>` CHỈ khi `feedback.phone !== null` (không có phone thì không link được tới `/convos/$phone`).

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/quality-review-card.test.tsx` — dùng harness router tối giản (cùng khuôn `convos-phien.test.tsx`):

```tsx
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FeedbackReviewCard } from '@/features/quality/components/FeedbackReviewCard'
import type { Feedback } from '@/features/quality/api'

function dung(feedback: Feedback) {
  const rootRoute = createRootRoute({
    component: () => <FeedbackReviewCard feedback={feedback} />,
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

const CO_DU: Feedback = {
  id: 1,
  sessionId: 'sess_1',
  rating: 2,
  comment: 'Trả lời chậm.',
  createdAt: '2026-08-12T09:00:00+07:00',
  customerName: 'Trần Văn A',
  phone: '0912345678',
}

describe('FeedbackReviewCard', () => {
  it('hiện đầy đủ tên + sđt, KHÔNG che', () => {
    dung(CO_DU)
    expect(screen.getByText('Trần Văn A')).toBeInTheDocument()
    expect(screen.getByText('0912345678')).toBeInTheDocument()
  })

  it('rating <= 2 hiện badge "Cần chú ý", rating > 2 thì không', () => {
    dung(CO_DU)
    expect(screen.getByText('Cần chú ý')).toBeInTheDocument()

    dung({ ...CO_DU, rating: 5 })
    expect(screen.queryByText('Cần chú ý')).not.toBeInTheDocument()
  })

  it('không có tên/sđt hiện "Khách ẩn danh", không link sang Hội thoại', () => {
    dung({ ...CO_DU, customerName: null, phone: null })
    expect(screen.getByText('Khách ẩn danh')).toBeInTheDocument()
    expect(screen.queryByText(/Xem phiên trò chuyện/i)).not.toBeInTheDocument()
  })

  it('comment rỗng hiện chữ thay thế', () => {
    dung({ ...CO_DU, comment: '' })
    expect(screen.getByText('(không để lại nhận xét)')).toBeInTheDocument()
  })

  it('có phone thì link kèm đúng session_id qua search param', () => {
    dung(CO_DU)
    const link = screen.getByText(/Xem phiên trò chuyện/i).closest('a')
    expect(link).toHaveAttribute('href', expect.stringContaining('session=sess_1'))
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `npx vitest run tests/quality-review-card.test.tsx`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Viết component**

Tạo `src/features/quality/components/FeedbackReviewCard.tsx`:

```tsx
import { Link } from '@tanstack/react-router'
import { Sao } from '@/components/ui/Sao'
import type { Feedback } from '../api'

function ngayGio(iso: string): string {
  const d = new Date(iso)
  const hai = (n: number) => String(n).padStart(2, '0')
  return `${hai(d.getDate())}/${hai(d.getMonth() + 1)} · ${hai(d.getHours())}:${hai(d.getMinutes())}`
}

function chuCaiDau(ten: string | null): string {
  return ten ? ten.trim().charAt(0).toUpperCase() : '?'
}

export function FeedbackReviewCard({ feedback }: { feedback: Feedback }) {
  const canChuY = feedback.rating <= 2

  return (
    <div className="border-b border-border-soft px-6 py-4 last:border-b-0">
      <div className="flex items-center gap-2.5">
        <span className="flex size-[34px] shrink-0 items-center justify-center rounded-full bg-acs text-[14px] font-semibold text-acd">
          {chuCaiDau(feedback.customerName)}
        </span>
        <div className="flex flex-col gap-px">
          <p className="text-[15px] font-medium">{feedback.customerName ?? 'Khách ẩn danh'}</p>
          <p className="text-[13px] text-muted">{feedback.phone ?? '— không có số —'}</p>
        </div>
        <div className="ml-auto text-right">
          <Sao gia={feedback.rating} />
          <p className="mt-0.5 text-[12px] text-muted-2">{ngayGio(feedback.createdAt)}</p>
        </div>
      </div>
      <p className={`ml-[44px] mt-2 text-[14px] leading-[1.55] ${feedback.comment ? 'text-fg' : 'italic text-muted'}`}>
        {feedback.comment || '(không để lại nhận xét)'}
      </p>
      <div className="ml-[44px] mt-2 flex items-center gap-2.5">
        {canChuY && (
          <span className="rounded-full bg-badge-alert-bg px-2 py-0.5 text-[12px] text-badge-alert-fg">
            Cần chú ý
          </span>
        )}
        {feedback.phone !== null && (
          <Link
            to="/convos/$phone"
            params={{ phone: feedback.phone }}
            search={{ session: feedback.sessionId }}
            className="text-[13px] text-acd underline decoration-acs"
          >
            Xem phiên trò chuyện →
          </Link>
        )}
      </div>
    </div>
  )
}
```

⚠️ `<Link to="/convos/$phone" search={{ session: ... }}>` yêu cầu route `/convos/$phone` đã khai `validateSearch` chấp nhận `session` (Task 11) để `tsc -b` không báo lỗi kiểu — nếu Task 11 CHƯA làm, bước type-check ở đây sẽ đỏ. Thứ tự khuyến nghị: làm Task 11 trước Task 7 nếu triển khai tuần tự một luồng; nếu triển khai song song hai nhánh, tạm thời có thể compile độc lập vì TanStack Router suy kiểu `search` từ route registry sinh bởi `make routes` — chạy `make routes` sau khi Task 11 xong rồi mới type-check lại Task 7.

- [ ] **Step 4: Chạy lại test, xác nhận qua**

Run: `npx vitest run tests/quality-review-card.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/features/quality/components/FeedbackReviewCard.tsx tests/quality-review-card.test.tsx
git commit -m "feat(quality): FeedbackReviewCard — khối feedback dạng review, không che tên/sđt"
```

---

### Task 8: `FeedbackList.tsx` — chip lọc + danh sách + Xem thêm

**Files:**
- Create: `src/features/quality/components/FeedbackList.tsx`
- Test: `tests/quality-list.test.tsx`

**Interfaces:**
- Consumes: `danhSachFeedback` (Task 4), `FeedbackTongQuan` (Task 6), `FeedbackReviewCard` (Task 7).
- Produces: `export function FeedbackList({ loc, datLoc }: { loc: LocFeedback; datLoc: (l: LocFeedback) => void }): JSX.Element` — dùng bởi Task 10 (route `quality.tsx`), cùng khuôn `KhachList({ loc, datLoc })`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/quality-list.test.tsx` (dùng `QueryClientProvider` + router tối giản, cùng khuôn `convos-phien.test.tsx`):

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FeedbackList } from '@/features/quality/components/FeedbackList'
import type { LocFeedback } from '@/features/quality/api'

function dung(loc: LocFeedback = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const datLoc = vi.fn()
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        <FeedbackList loc={loc} datLoc={datLoc} />
      </QueryClientProvider>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  const utils = render(<RouterProvider router={router} />)
  return { ...utils, datLoc }
}

describe('FeedbackList', () => {
  it('hiện dải thống kê và danh sách từ fake MSW', async () => {
    dung()
    expect(await screen.findByText('Nguyễn Minh Anh')).toBeInTheDocument()
    // 5 feedback fake (msw.ts) — total = 5.
    expect(screen.getByText(/5 lượt đánh giá/)).toBeInTheDocument()
  })

  it('bấm chip sao gọi datLoc với rating tương ứng', async () => {
    const { datLoc } = dung()
    await screen.findByText('Nguyễn Minh Anh')
    await userEvent.click(screen.getByRole('button', { name: '★ 5' }))
    expect(datLoc).toHaveBeenCalledWith(expect.objectContaining({ ratings: [5] }))
  })
})
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `npx vitest run tests/quality-list.test.tsx`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Viết component**

Tạo `src/features/quality/components/FeedbackList.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'
import { danhSachFeedback, type LocFeedback } from '../api'
import { FeedbackReviewCard } from './FeedbackReviewCard'
import { FeedbackTongQuan } from './FeedbackTongQuan'

const NAM_SAO = [5, 4, 3, 2, 1] as const

function Khung({ children }: { children: React.ReactNode }) {
  return (
    <div className="p-6">
      <div className="overflow-hidden rounded-xl border bg-surface">{children}</div>
    </div>
  )
}

export function FeedbackList({
  loc,
  datLoc,
}: {
  loc: LocFeedback
  datLoc: (l: LocFeedback) => void
}) {
  const ds = useQuery({
    queryKey: ['quality', 'feedback', loc],
    queryFn: () => danhSachFeedback(loc),
  })

  const toggleSao = (n: number) => {
    const dang_chon = loc.ratings ?? []
    const moi = dang_chon.includes(n) ? dang_chon.filter((r) => r !== n) : [...dang_chon, n]
    datLoc({ ...loc, ratings: moi.length > 0 ? moi : undefined })
  }

  if (ds.isPending)
    return (
      <Khung>
        <p className="p-6 text-[14px] text-muted">Đang tải…</p>
      </Khung>
    )
  if (ds.error)
    return (
      <Khung>
        <p className="p-6 text-[14px]">Không tải được feedback.</p>
      </Khung>
    )

  const dangChon = loc.ratings ?? []

  return (
    <Khung>
      <FeedbackTongQuan
        total={ds.data.total}
        theoSao={ds.data.theoSao}
        diemTrungBinh={ds.data.diemTrungBinh}
      />
      <div className="flex flex-wrap items-center gap-2 border-b border-border-soft px-6 py-3">
        <span className="mr-1 text-[13px] text-muted">Lọc theo sao:</span>
        <button
          type="button"
          onClick={() => datLoc({ ...loc, ratings: undefined })}
          className={`rounded-full border px-3 py-1 text-[13px] ${
            dangChon.length === 0 ? 'border-ac bg-acs text-acd font-medium' : 'border-border-field'
          }`}
        >
          Tất cả
        </button>
        {NAM_SAO.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => toggleSao(n)}
            className={`rounded-full border px-3 py-1 text-[13px] ${
              dangChon.includes(n) ? 'border-ac bg-acs text-acd font-medium' : 'border-border-field'
            }`}
          >
            ★ {n}
          </button>
        ))}
      </div>

      {ds.data.items.length === 0 ? (
        <p className="px-6 py-12 text-center text-[14px] text-muted">Chưa có feedback nào.</p>
      ) : (
        ds.data.items.map((f) => <FeedbackReviewCard key={f.id} feedback={f} />)
      )}

      {ds.data.nextBeforeId !== null && (
        <div className="p-4 text-center">
          <button
            type="button"
            onClick={() => datLoc({ ...loc, beforeId: ds.data.nextBeforeId ?? undefined })}
            className="rounded-md border border-border-field px-5 py-2 text-[13px]"
          >
            Xem thêm
          </button>
        </div>
      )}
    </Khung>
  )
}
```

- [ ] **Step 4: Chạy lại test, xác nhận qua**

Run: `npx vitest run tests/quality-list.test.tsx`
Expected: PASS.

- [ ] **Step 5: Type-check + lint toàn bộ `features/quality`**

Run: `npx tsc -b --force && npx eslint src/features/quality/`

- [ ] **Step 6: Commit**

```bash
git add src/features/quality/components/FeedbackList.tsx tests/quality-list.test.tsx
git commit -m "feat(quality): FeedbackList — chip lọc sao + danh sách + Xem thêm"
```

---

### Task 9: Nav — di chuyển `qualityNav` khỏi `deferred`, cập nhật `screens.ts`

**Files:**
- Create: `src/features/quality/nav.ts`
- Modify: `src/features/deferred/nav.ts` (xoá `qualityNav`)
- Modify: `src/lib/nav-registry.ts` (đổi nguồn import)
- Modify: `src/lib/screens.ts` (entry `quality`)
- Modify: `tests/nav-registry.test.ts` (bỏ `'quality'` khỏi danh sách hoãn)

**Interfaces:**
- Produces: `export const qualityNav: NavLeaf` (giữ nguyên `key`/`path`/`icon`, ĐỔI `requiredActions` từ `[ACTIONS.OVERVIEW_READ]` sang `[ACTIONS.CONVOS_READ]` — khớp đúng cổng quyền thật của `GET /agent/feedback`).

⚠️ Đây chính là quy trình mà comment gốc ở `features/deferred/nav.ts` đã viết sẵn: *"Khi nào có module nhận thì đổi `owner` ở `lib/screens.ts` và chuyển file này sang `features/<module>/nav.ts`."*

- [ ] **Step 1: Viết test thất bại — canh `requiredActions` mới**

Sửa `tests/nav-registry.test.ts`, đổi assertion ở dòng ~127-129:

```ts
it('màn hoãn ngoài MVP là finance · usage · billing (spec §2)', () => {
  const deferred = SCREENS.filter((s) => s.mvp === 'deferred').map((s) => s.key)
  expect(deferred.sort()).toEqual(['billing', 'finance', 'usage'])
})
```

Thêm test mới ngay dưới (cần `import { qualityNav } from '@/features/quality/nav'` ở đầu file):

```ts
it('quality dùng đúng quyền convos.read (khớp GET /agent/feedback)', () => {
  expect(qualityNav.requiredActions).toEqual(['convos.read'])
})
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `npx vitest run tests/nav-registry.test.ts`
Expected: FAIL — assertion đầu fail vì `deferred` vẫn còn `'quality'`; assertion sau fail vì import `@/features/quality/nav` chưa tồn tại.

- [ ] **Step 3: Tạo `features/quality/nav.ts`**

```ts
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

export const qualityNav: NavLeaf = {
  kind: 'leaf',
  key: 'quality',
  path: '/quality',
  label: { vi: 'Chất lượng', en: 'Quality' },
  icon: 'quality',
  requiredActions: [ACTIONS.CONVOS_READ],
}
```

- [ ] **Step 4: Xoá `qualityNav` khỏi `features/deferred/nav.ts`**

Xoá khối `export const qualityNav = {...}` (giữ nguyên `financeNav`/`usageNav`/`billingNav`). Cập nhật docstring đầu file — đổi "Ba màn HOÃN" thành "Hai màn HOÃN" (nay chỉ còn finance + usage/billing — kiểm lại đúng 3 hay 2 tuỳ `usageNav`/`billingNav` có tính là hai màn riêng, theo comment sẵn có trong file đó phần "HAI MỤC, KHÔNG PHẢI MỘT").

- [ ] **Step 5: Cập nhật `nav-registry.ts`**

Đổi dòng import từ:
```ts
import { billingNav, financeNav, qualityNav, usageNav } from '@/features/deferred/nav'
```
thành:
```ts
import { billingNav, financeNav, usageNav } from '@/features/deferred/nav'
import { qualityNav } from '@/features/quality/nav'
```
Vị trí dùng `qualityNav` trong `khoi(dashboardNav, convosNav, apptsNav, qualityNav)` giữ nguyên.

- [ ] **Step 6: Cập nhật `screens.ts`**

Sửa entry `quality` (dòng 40-47):

```ts
{
  key: 'quality',
  path: '/quality',
  owner: 'M7',
  mvp: 'full',
  inNav: true,
  note: 'Feedback agent (CSAT). Eval (bộ kiểm thử hồi quy) vẫn ngoài phạm vi.',
},
```

(`owner: 'M7'` — cùng nhóm nav "Vận hành" với `dashboard`/`convos`/`appts`, và dùng chung quyền `ACTIONS.CONVOS_READ`. `'M10'` KHÔNG hợp lệ — `ModuleId` chỉ nhận `M2a`-`M9`.)

- [ ] **Step 7: Chạy lại test, xác nhận qua**

Run: `npx vitest run tests/nav-registry.test.ts`
Expected: PASS toàn bộ.

- [ ] **Step 8: Type-check toàn bộ (bắt import chết nếu sót chỗ nào còn trỏ `deferred/nav`)**

Run: `npx tsc -b --force`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/features/quality/nav.ts src/features/deferred/nav.ts src/lib/nav-registry.ts src/lib/screens.ts tests/nav-registry.test.ts
git commit -m "feat(quality): un-defer /quality — nav.ts riêng, quyền convos.read, mvp: full"
```

---

### Task 10: Route `quality.tsx` — thay `ScreenStub`

**Files:**
- Modify: `src/routes/_app/quality.tsx`

**Interfaces:**
- Consumes: `FeedbackList` (Task 8), `LocFeedback` (Task 4).

- [ ] **Step 1: Viết route**

Thay toàn bộ nội dung `src/routes/_app/quality.tsx`:

```tsx
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import type { LocFeedback } from '@/features/quality/api'
import { FeedbackList } from '@/features/quality/components/FeedbackList'

/**
 * Màn `/quality` (phần CSAT) — bộ lọc nằm ở SEARCH PARAM, cùng lý do
 * `convos.index.tsx`: F5 hoặc gửi link cho đồng nghiệp vẫn ra đúng bộ lọc
 * đang xem.
 */
interface TimKiem {
  rating?: readonly number[] | undefined
  beforeId?: number | undefined
}

export const Route = createFileRoute('/_app/quality')({
  validateSearch: (s: Record<string, unknown>): TimKiem => ({
    rating: Array.isArray(s.rating) ? s.rating.map(Number) : undefined,
    beforeId: typeof s.beforeId === 'number' ? s.beforeId : undefined,
  }),
  component: ManChatLuong,
})

function ManChatLuong() {
  const s = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  const loc: LocFeedback = {
    ...(s.rating !== undefined ? { ratings: s.rating } : {}),
    ...(s.beforeId !== undefined ? { beforeId: s.beforeId } : {}),
  }

  return (
    <FeedbackList
      loc={loc}
      datLoc={(l) =>
        void navigate({
          search: { rating: l.ratings, beforeId: l.beforeId },
        })
      }
    />
  )
}
```

- [ ] **Step 2: Sinh lại route tree**

Run: `make routes`
Expected: `src/routeTree.gen.ts` cập nhật, không lỗi.

- [ ] **Step 3: Type-check**

Run: `npx tsc -b --force`
Expected: PASS.

- [ ] **Step 4: Kiểm tay bằng dev server (không phải test tự động — xác nhận màn render thật)**

Run: `make dev` (MSW mặc định bật), mở `http://localhost:5273/quality`, xác nhận: dải thống kê hiện số, 5 review card hiện, chip lọc bấm được, "Xem thêm" KHÔNG hiện (fake chỉ có 1 trang).

- [ ] **Step 5: Commit**

```bash
git add src/routes/_app/quality.tsx src/routeTree.gen.ts
git commit -m "feat(quality): route /quality render FeedbackList thay ScreenStub"
```

---

### Task 11: Deep-link đúng phiên — `convos.$phone.tsx` + `PhienKhach.tsx`

**Files:**
- Modify: `src/routes/_app/convos.$phone.tsx`
- Modify: `src/features/ops/components/PhienKhach.tsx`
- Test: `tests/convos-phien.test.tsx` (mở rộng)

**Interfaces:**
- Produces: `PhienKhach` nhận thêm prop tuỳ chọn `phienMoDau?: string` — khởi tạo `chon` từ đó thay vì hardcode `null`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/convos-phien.test.tsx` — cần sửa `dung()` để nhận thêm `phienMoDau`:

```tsx
function dung(phone = '0912448111', phienMoDau?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        <PhienKhach phone={phone} phienMoDau={phienMoDau} />
      </QueryClientProvider>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}
```

Thêm test mới:

```tsx
it('truyền phienMoDau thì chọn ĐÚNG phiên đó, không phải phiên mới nhất', async () => {
  // PHIEN_GIA['0912448111'] (msw.ts) = [PHIEN_ANH_1 (27/07), PHIEN_ANH_2 (21/07)]
  // — mặc định (không phienMoDau) chọn PHIEN_ANH_1 (mới nhất). Truyền sessionId
  // của PHIEN_ANH_2 phải chọn đúng nó, dù nó KHÔNG phải phiên đầu danh sách.
  dung('0912448111', 's-anh-2')
  await screen.findByText(/21\/07\/2026/)
  // PHIEN_ANH_2 có `soLuot: 0` — transcript rỗng, khác PHIEN_ANH_1 (có 6 lượt).
  expect(screen.queryAllByTestId('bong-bong')).toHaveLength(0)
})

it('phienMoDau không thuộc danh sách của khách này thì rơi về phiên mới nhất, không lỗi', async () => {
  dung('0912448111', 'sess-khong-ton-tai')
  expect(await screen.findByText(/27\/07\/2026/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `npx vitest run tests/convos-phien.test.tsx -t "phienMoDau"`
Expected: FAIL — `PhienKhach` chưa nhận prop này (TypeScript sẽ báo lỗi prop lạ, hoặc runtime bỏ qua nếu không strict — xác nhận bằng: cả hai test case đều thấy `27/07/2026` vì `chon` luôn `null`).

- [ ] **Step 3: Sửa `PhienKhach.tsx` nhận prop `phienMoDau`**

Sửa chữ ký hàm:

```tsx
export function PhienKhach({ phone, phienMoDau }: { phone: string; phienMoDau?: string }) {
  const an = phone === PHONE_TRONG
  const ds = useQuery({ queryKey: ['convos', 'phien', phone], queryFn: () => phienCuaKhach(phone) })
  const [tab, setTab] = useState<TabNguon>('tat-ca')
  const [chon, setChon] = useState<string | null>(phienMoDau ?? null)
```

(Chỉ đổi dòng khai `useState<string | null>(null)` thành `useState<string | null>(phienMoDau ?? null)` — không đổi gì khác. Logic fallback `dsLoc.some(...) ? chon : dsLoc[0]` giữ nguyên, tự xử lý ca "không tìm thấy".)

- [ ] **Step 4: Chạy lại test, xác nhận qua**

Run: `npx vitest run tests/convos-phien.test.tsx`
Expected: PASS toàn bộ.

- [ ] **Step 5: Sửa route `convos.$phone.tsx` truyền `session` search param**

Thay nội dung `src/routes/_app/convos.$phone.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { PhienKhach } from '@/features/ops/components/PhienKhach'

interface TimKiemPhien {
  session?: string | undefined
}

export const Route = createFileRoute('/_app/convos/$phone')({
  validateSearch: (s: Record<string, unknown>): TimKiemPhien => ({
    session: typeof s.session === 'string' ? s.session : undefined,
  }),
  component: ManChiTietKhach,
})

function ManChiTietKhach() {
  const { phone } = Route.useParams()
  const { session } = Route.useSearch()
  return <PhienKhach key={phone} phone={phone} phienMoDau={session} />
}
```

(Giữ nguyên `key={phone}` — vẫn cần để reset `chon` khi đổi KHÁCH; `phienMoDau` chỉ ảnh hưởng giá trị KHỞI TẠO của `chon` trong lần mount đó.)

- [ ] **Step 6: Sinh lại route tree + type-check**

Run: `make routes && npx tsc -b --force`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/routes/_app/convos.\$phone.tsx src/features/ops/components/PhienKhach.tsx tests/convos-phien.test.tsx src/routeTree.gen.ts
git commit -m "feat(ops): convos/\$phone nhận search param session — deep-link đúng phiên từ feedback"
```

---

### Task 12: Feedback inline trong `PhienKhach.tsx`

**Files:**
- Modify: `src/features/ops/components/PhienKhach.tsx`
- Test: `tests/convos-phien.test.tsx` (mở rộng)

**Interfaces:**
- Consumes: `feedbackCuaPhien` (Task 4), `Sao` (Task 2).

⚠️ Import `@/features/quality/api` TỪ TRONG `features/ops/` — kiểm tra `tests/module-boundaries.test.ts` có chặn import chéo giữa hai feature không (luật: `features/<a>` chỉ import `features/<a>/…` · `lib/…` · `components/…` · `i18n/…` · KHÔNG import `features/<b>` trừ qua `features/<b>/contracts`). `features/quality` KHÔNG có `contracts.ts` (Task 4 gộp types vào `api.ts`, theo đúng khuôn `features/ops` không tách contracts.ts) — nên import trực tiếp `@/features/quality/api` từ `features/ops/components/PhienKhach.tsx` sẽ BỊ CHẶN bởi cổng CI. Cách đúng: đảo hướng phụ thuộc — feedback badge phải sống ở `features/quality/` (module SỞ HỮU khái niệm feedback) dưới dạng một component riêng nhận `sessionId` làm prop, rồi `PhienKhach.tsx` import nó qua... vẫn cùng vấn đề (ops import quality). Giải pháp đúng theo luật ranh giới: **tạo `features/quality/contracts.ts`** chỉ export type `Feedback` + hàm `feedbackCuaPhien` (mặt tiền công khai), và `PhienKhach.tsx` import từ `@/features/quality/contracts`, KHÔNG từ `@/features/quality/api`.

- [ ] **Step 1: Tạo `features/quality/contracts.ts` — mặt tiền công khai**

```ts
/**
 * Mặt tiền công khai của `features/quality` — module KHÁC (`ops`) chỉ được
 * import từ đây, không import ruột `api.ts`/`components/*` (luật ranh giới
 * module, `tests/module-boundaries.test.ts`).
 */
export type { Feedback } from './api'
export { feedbackCuaPhien } from './api'
```

- [ ] **Step 2: Viết test thất bại**

Thêm vào `tests/convos-phien.test.tsx`:

```tsx
import { http, HttpResponse } from 'msw'
// (import server đã có sẵn ở đầu file)

it('phiên có feedback thì hiện sao + comment cạnh header', async () => {
  server.use(
    http.get('/api/v1/agent/feedback', () =>
      HttpResponse.json({
        items: [
          {
            id: 1,
            session_id: 's-anh-1',
            rating: 4,
            comment: 'Khá ổn',
            created_at: '2026-08-12T09:00:00+07:00',
            customer_name: 'Nguyễn Minh Anh',
            phone: '0912448111',
          },
        ],
        next_before_id: null,
        total: 1,
        theo_sao: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 0 },
        diem_trung_binh: 4,
      }),
    ),
  )
  dung()
  await screen.findByText(/27\/07\/2026/)
  expect(await screen.findByText('Khá ổn')).toBeInTheDocument()
})

it('phiên KHÔNG có feedback thì không hiện gì thêm, không lỗi', async () => {
  server.use(
    http.get('/api/v1/agent/feedback', () =>
      HttpResponse.json({
        items: [],
        next_before_id: null,
        total: 0,
        theo_sao: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
        diem_trung_binh: 0,
      }),
    ),
  )
  dung()
  await screen.findByText(/27\/07\/2026/)
  expect(screen.queryByText('Khá ổn')).not.toBeInTheDocument()
})
```

- [ ] **Step 3: Chạy test, xác nhận thất bại**

Run: `npx vitest run tests/convos-phien.test.tsx -t "feedback"`
Expected: FAIL — `PhienKhach` chưa gọi `feedbackCuaPhien`.

- [ ] **Step 4: Sửa `PhienKhach.tsx`**

Thêm import ở đầu file:

```tsx
import { feedbackCuaPhien } from '@/features/quality/contracts'
```

Trong component, ngay dưới khai báo `ct` (query chi tiết phiên), thêm:

```tsx
  const fb = useQuery({
    queryKey: ['agent-feedback', sid],
    queryFn: () => feedbackCuaPhien(sid!),
    enabled: sid !== null,
  })
```

Trong khối render header phiên (`{ct.data.phien.sessionId}` ... `runningVersion`), thêm SAU thẻ `<span>` cuối cùng của hàng đó (trước `</div>` đóng hàng header):

```tsx
                    {fb.data && (
                      <span className="ml-auto flex items-center gap-1.5">
                        <Sao gia={fb.data.rating} kichThuoc={13} />
                        {fb.data.comment && <span className="italic">"{fb.data.comment}"</span>}
                      </span>
                    )}
```

⚠️ Nếu hàng header đã có `<span className="ml-auto ...">config v{...}</span>` (cho `runningVersion`), badge feedback phải đứng CẠNH nó chứ không đè `ml-auto` thứ hai — bọc cả hai trong MỘT `<span className="ml-auto flex items-center gap-3">` chứa cả `config vN` (nếu có) và feedback (nếu có), thay vì mỗi cái tự xưng `ml-auto` riêng. Đọc lại đúng JSX hiện tại của hàng đó trước khi ráp để không có hai `ml-auto` tranh nhau.

Thêm import `Sao`:

```tsx
import { Sao } from '@/components/ui/Sao'
```

- [ ] **Step 5: Chạy lại test, xác nhận qua**

Run: `npx vitest run tests/convos-phien.test.tsx`
Expected: PASS toàn bộ (test cũ + Task 11 + Task 12).

- [ ] **Step 6: Kiểm cổng ranh giới module**

Run: `npx vitest run tests/module-boundaries.test.ts`
Expected: PASS — `PhienKhach.tsx` chỉ import `@/features/quality/contracts` (mặt tiền), không import `@/features/quality/api` hay `components/*` trực tiếp.

- [ ] **Step 7: Type-check + lint toàn repo**

Run: `npx tsc -b --force && make lint`
Expected: sạch.

- [ ] **Step 8: Commit**

```bash
git add src/features/quality/contracts.ts src/features/ops/components/PhienKhach.tsx tests/convos-phien.test.tsx
git commit -m "feat(quality): feedback hiện inline trong PhienKhach.tsx qua mặt tiền contracts.ts"
```

---

### Task 13: Hồi quy toàn repo

**Files:** không tạo/sửa file — chỉ chạy cổng.

- [ ] **Step 1: Chạy toàn bộ `make check`**

Run: `make check`
Expected: PASS. Nếu đỏ ở `tests/isolation`-tương-đương phía FE hoặc bài đã biết trước ĐỎ SẴN trước khi bắt đầu plan này (xem gotcha CLAUDE.md — `tests/convos-phien.test.tsx:53` từng đỏ có sẵn, đo lại TRƯỚC khi bắt đầu để biết mốc so sánh), KHÔNG coi đó là lỗi của plan này — đối chiếu với mốc đã đo, không tự nhận cái đỏ có sẵn.

- [ ] **Step 2: `make build` (đảm bảo MSW không lọt vào bundle production)**

Run: `make build`
Expected: build thành công, không cảnh báo nào nhắc `msw` trong output.

- [ ] **Step 3: Kiểm tay dev server lần cuối — luồng đầy đủ**

Run: `make dev`, thao tác: mở `/quality` → thấy 5 review card + thống kê → bấm chip "★ 2" → chỉ còn feedback rating 2 → bấm "Xem phiên trò chuyện →" trên card đó → điều hướng đúng `/convos/0987112222?session=s-quang` (hoặc session tương ứng trong fake) → `PhienKhach` mở đúng phiên đó (không phải phiên mới nhất của khách, nếu khách có nhiều phiên trong fake — có thể cần thêm một phiên thứ hai vào `PHIEN_GIA` cho khách này để kiểm tra thấy rõ, hoặc chấp nhận kiểm bằng test tự động ở Task 11 là đủ nếu fake hiện tại mỗi khách feedback chỉ có 1 phiên).

- [ ] **Step 4: Không cần commit — task này chỉ xác nhận, không sinh diff.**
