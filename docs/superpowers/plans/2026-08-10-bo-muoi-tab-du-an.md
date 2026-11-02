# Bộ mười tab màn dự án — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chia màn chi tiết dự án (`/pform`, `/uform`) từ năm tab thành mười tab bám bộ tab ngành BĐS, và cho tab Tài liệu phân loại được theo `loai` mà backend vừa thêm.

**Architecture:** `TAB_DU_AN` trong `features/realestate/tabDuAn.ts` là nguồn duy nhất của hàng tab; `DuAnForm` rẽ nhánh render theo `tab`. Mỗi tab chứa trường của `projects` là **một `<form>` độc lập** với state và mutation riêng, `PATCH` đúng phần của nó — backend dùng `exclude_unset` nên gửi thiếu trường không xoá trường khác. `VungMedia` (hiện nằm trong `MediaTab.tsx`) tách ra file riêng để năm tab dùng chung, tất cả giữ **cùng** query key `['re', code, 'media']` nên tách tab không sinh thêm request.

**Tech Stack:** React 19 · TanStack Router (search param) · TanStack Query · Tailwind · vitest + @testing-library/react + MSW

## Global Constraints

- **Định danh tiếng Anh** cho hàm/biến/hằng/tham số, **kể cả biến cục bộ**. Tiếng Việt chỉ ở comment, docstring, và tên `it(...)` của test. Đây là luật của cả hai repo.
- **Comment thưa.** Chỉ viết khi giải thích *vì sao*, không mô tả *cái gì*. Codebase hiện có comment rất dày — đừng nối theo mật độ đó.
- **Không thêm file route.** `tests/nav-registry.test.ts` khoá thư mục `src/routes/_app`; tab đi bằng search param `?tab=`, không phải path.
- **Thứ tự mười tab, đúng như spec §5:** `tong-quan` · `vi-tri` · `anh-360` · `phan-khu` · `mat-bang` · `quy-can` · `csbh` · `media` · `tien-do` · `tai-lieu`.
- **Tab là lăng kính, không phải ngăn chứa (spec §3).** Một row `media`/`documents` nằm ở đúng một chỗ; nhiều tab cùng nhìn vào nó. Tab `Media` hiện **đủ bảy vùng** gồm cả `vi_tri`/`mat_bang`/`tien_do`; tab `Tài liệu` hiện **toàn bộ** `documents`. Xoá ở một chỗ là mất ở mọi chỗ — UI phải nói ra.
- **Trần ảnh đếm theo `(project, zone, unit, category)`**, hằng `TRAN_ANH = 6`. Chỉ ảnh bị đếm, video không.
- Chạy test: `npm test` (vitest run). Một file: `npx vitest run tests/<file>`.
- Lint: `npm run lint`. Cổng trước MR: `npm run check` nếu có, nếu không thì `npm run lint && npm test`.

**Spec:** `odyssey-portal-backend/docs/superpowers/specs/2026-08-10-tab-kien-thuc-bds-design.md` — đọc §3 (nguyên tắc lăng kính), §5 (bộ tab), §5.2 (tab Tài liệu).

**Backend đã sẵn sàng** (nhánh `feat/kb-tab`, 14 commit): `GET/POST/PATCH /projects/{code}/documents` nhận và trả thêm `loai: "csbh" | "phap_ly" | "huong_dan" | "khac"`, và `title` là **phần đuôi** — tiền tố ghép/tách ở biên HTTP nên frontend không bao giờ thấy nó. Không có `?loai=` trên API: tab lọc client-side trên danh sách dùng chung.

---

### Task 1: Đổi tên hai tab và bắt link cũ

Chưa thêm tab mới. Sau task này bộ tab vẫn năm cái nhưng `thong-tin` → `tong-quan` (nhãn *Tổng quan*) và `can` → `quy-can` (nhãn *Quỹ căn*), link cũ vẫn mở đúng.

**Files:**
- Modify: `src/features/realestate/tabDuAn.ts`
- Rename: `src/features/realestate/components/ThongTinTab.tsx` → `TongQuanTab.tsx` (đổi luôn tên hàm export)
- Modify: `src/features/realestate/components/DuAnForm.tsx`
- Modify: `src/features/realestate/components/KhungDuAn.tsx:88` (điều kiện khoá tab)
- Modify: `tests/realestate-pform.test.tsx` (2 chỗ), `tests/realestate-uform.test.tsx` (7 chỗ)

**Interfaces:**
- Consumes: —
- Produces: `TenTabDuAn = 'tong-quan' | 'phan-khu' | 'quy-can' | 'tai-lieu' | 'media'`; `tabHopLe(tho: unknown): TenTabDuAn` nhận thêm id cũ và trả id mới; `TongQuanTab` (đổi tên từ `ThongTinTab`, prop không đổi).

- [ ] **Step 1: Viết test đỏ cho phép ánh xạ id cũ**

Tạo `tests/tab-du-an.test.ts`:

```ts
/**
 * `tabHopLe()` là hàm thuần duy nhất trong `tabDuAn.ts` — test nó trực tiếp,
 * không qua router: nó chạy lúc `validateSearch`, trước khi có gì để render.
 */
import { describe, expect, it } from 'vitest'
import { TAB_DU_AN, tabHopLe } from '../src/features/realestate/tabDuAn'

describe('tabHopLe', () => {
  it('id hợp lệ đi qua nguyên vẹn', () => {
    for (const t of TAB_DU_AN) expect(tabHopLe(t.id)).toBe(t.id)
  })

  it('id cũ trong link đã gửi cho đồng nghiệp vẫn mở đúng tab', () => {
    expect(tabHopLe('thong-tin')).toBe('tong-quan')
    expect(tabHopLe('can')).toBe('quy-can')
  })

  it('giá trị lạ về tab đầu chứ không ném lỗi', () => {
    expect(tabHopLe('xyz')).toBe('tong-quan')
    expect(tabHopLe(undefined)).toBe('tong-quan')
    expect(tabHopLe(['can'])).toBe('tong-quan')
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/tab-du-an.test.ts`
Expected: FAIL — `expected 'thong-tin' to be 'tong-quan'`.

- [ ] **Step 3: Sửa `tabDuAn.ts`**

Thay toàn bộ phần khai báo (giữ nguyên docstring đầu file, chỉ sửa câu "Năm tab" thành "Mười tab" khi Task 10 xong — ở task này vẫn là năm):

```ts
export type TenTabDuAn = 'tong-quan' | 'phan-khu' | 'quy-can' | 'tai-lieu' | 'media'

export const TAB_DU_AN: readonly { id: TenTabDuAn; nhan: string }[] = [
  { id: 'tong-quan', nhan: 'Tổng quan' },
  { id: 'phan-khu', nhan: 'Phân khu' },
  { id: 'quy-can', nhan: 'Quỹ căn' },
  // «Tài liệu» TRẦN, cố ý — không phải «Tài liệu gửi khách».
  //
  // Đây và tab ở `/projects` là CÙNG một kho, chỉ khác `project_code`, nên thoạt
  // nhìn chúng nên cùng tên. Thử rồi, sai: sản phẩm khi đó có HAI tab đọc y hệt
  // nhau, và người dùng gặp cả hai trong cùng một luồng.
  //
  // Cái phân biệt hai chỗ này là PHẠM VI, và ở đây phạm vi đã do ngữ cảnh nói.
  { id: 'tai-lieu', nhan: 'Tài liệu' },
  { id: 'media', nhan: 'Media' },
]

/** Id cũ → id mới. Link đã gửi cho đồng nghiệp và bookmark vẫn phải mở đúng tab. */
const TAB_CU: Record<string, TenTabDuAn> = { 'thong-tin': 'tong-quan', can: 'quy-can' }

export const VI_SAO_KHOA_TAB =
  'Tạo dự án trước — phân khu, quỹ căn, tài liệu và media đều thuộc về một dự án'
```

Và `tabHopLe`:

```ts
export function tabHopLe(tho: unknown): TenTabDuAn {
  if (TAB_DU_AN.some((t) => t.id === tho)) return tho as TenTabDuAn
  return (typeof tho === 'string' && TAB_CU[tho]) || 'tong-quan'
}
```

- [ ] **Step 4: Đổi tên component**

```bash
git mv src/features/realestate/components/ThongTinTab.tsx src/features/realestate/components/TongQuanTab.tsx
```

Trong file vừa đổi tên, sửa `export function ThongTinTab(` thành `export function TongQuanTab(`, và sửa dòng đầu docstring `Tab Thông tin của form dự án` thành `Tab Tổng quan của form dự án`.

- [ ] **Step 5: Sửa `DuAnForm.tsx`**

Đổi import và nhánh render:

```tsx
import { TongQuanTab } from './TongQuanTab'
```

```tsx
      {tab === 'tong-quan' && (
        <TongQuanTab
          key={duAn?.projectCode ?? 'moi'}
          duAn={duAn}
          daTao={(ma) => void nav({ to: '/pform', search: { code: ma, tab: 'tong-quan' } })}
        />
      )}
      {tab === 'phan-khu' && code && <PhanKhuTab projectCode={code} />}
      {tab === 'quy-can' && code && <CanTab projectCode={code} />}
      {tab === 'tai-lieu' && code && <TaiLieuTab projectCode={code} cao={CAO_TAB} />}
      {tab === 'media' && code && <MediaTab projectCode={code} />}
```

- [ ] **Step 6: Sửa điều kiện khoá tab trong `KhungDuAn.tsx`**

Dòng `const khoa = !code && t.id !== 'thong-tin'` thành:

```tsx
    const khoa = !code && t.id !== 'tong-quan'
```

- [ ] **Step 7: Sửa `/uform` — nó điều hướng về tab `can`**

Grep `'can'` trong `src/features/realestate/` và `src/routes/_app/uform.tsx`; mọi chỗ truyền `tab: 'can'` (mẩu đường dẫn «Quỹ căn» ở màn một căn dùng `LinkVe`) đổi thành `tab: 'quy-can'`.

```bash
grep -rn "'can'\|\"can\"" src/features/realestate src/routes/_app/uform.tsx
```

- [ ] **Step 8: Sửa test hiện có**

Trong `tests/realestate-pform.test.tsx`, hai chỗ `findByRole('tab', { name: 'Thông tin' })` (dòng 36 và 465) đổi thành `name: 'Tổng quan'`.

Trong `tests/realestate-uform.test.tsx`, sáu chỗ `{ name: 'Căn' }` đổi thành `{ name: 'Quỹ căn' }`, và mảng ở dòng 276:

```ts
    for (const ten of ['Tổng quan', 'Phân khu', 'Quỹ căn', 'Tài liệu', 'Media']) {
```

cùng dòng 278:

```ts
    expect(screen.getByRole('tab', { name: 'Quỹ căn' })).toHaveAttribute('aria-selected', 'true')
```

- [ ] **Step 9: Chạy toàn bộ test**

Run: `npm test`
Expected: PASS. Sáu test `it.skip` trong `tests/realestate-media.test.tsx` vẫn skip (đã skip từ 2026-08-04, không liên quan).

- [ ] **Step 10: Commit**

```bash
git add src/features/realestate/tabDuAn.ts \
        src/features/realestate/components/TongQuanTab.tsx \
        src/features/realestate/components/DuAnForm.tsx \
        src/features/realestate/components/KhungDuAn.tsx \
        tests/tab-du-an.test.ts \
        tests/realestate-pform.test.tsx \
        tests/realestate-uform.test.tsx
git commit -m "refactor(re): đổi tên tab Tổng quan và Quỹ căn"
```

---

### Task 2: Tách `VungMedia` ra file riêng

Refactor thuần — hành vi không đổi, test hiện có phải xanh mà không sửa một dòng. Năm tab sau sẽ import file này.

**Files:**
- Create: `src/features/realestate/components/VungMedia.tsx`
- Modify: `src/features/realestate/components/MediaTab.tsx`

**Interfaces:**
- Consumes: —
- Produces: `VungMedia({ projectCode, category, nhan, anh, lamMoi }: { projectCode: string; category: string; nhan: string; anh: readonly Media[]; lamMoi: () => void })` — một `<section>` chứa `<h3>{nhan}</h3>`, đếm `n/6 ảnh`, danh sách ảnh, và nút thêm.

- [ ] **Step 1: Tạo file mới bằng cách cắt nguyên khối**

Tạo `src/features/realestate/components/VungMedia.tsx` — chuyển **nguyên văn** `interface VungProps` và `function VungMedia` từ `MediaTab.tsx` sang, thêm `export`, và mang theo đúng những import chúng cần:

```tsx
/**
 * MỘT vùng media theo `category` — dùng ở tab Media (bảy vùng) và ở bốn tab
 * chuyên đề (Vị trí · Mặt bằng · Tiến độ, mỗi tab một vùng).
 *
 * TÁCH RA KHỎI `MediaTab.tsx` (2026-08-10) vì năm tab dùng chung. Cả năm phải
 * giữ CÙNG query key `['re', code, 'media']`: trần của backend đếm theo
 * `(project, zone, unit, category)`, nên năm query rời nhau sẽ lệch số đếm sau
 * mỗi lần upload cho tới khi cả năm invalidate.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { nguonAnh, taoMedia, xoaMedia, type Media, type MediaKem } from '../api'
import { CONTENT_TYPE, TRAN_ANH, nhanCua } from '../enums'
import { cauLoi } from '../thongDiep'
import { OMedia } from './OMedia'

const NUT = 'rounded border border-border-field px-2 py-1 text-[13px]'

interface VungProps {
  projectCode: string
  category: string
  nhan: string
  anh: readonly Media[]
  lamMoi: () => void
}

export function VungMedia({ projectCode, category, nhan, anh, lamMoi }: VungProps) {
```

Phần thân hàm giữ **y nguyên** những gì đang có trong `MediaTab.tsx` — từ `const [them, setThem] = useState<MediaKem | null>(null)` tới hết `</section>`. Không sửa một ký tự nào trong đó.

- [ ] **Step 2: Gỡ khỏi `MediaTab.tsx`**

Xoá `interface VungProps`, `function VungMedia`, hằng `NUT`, và các import nay không còn dùng (`useState`, `useMutation`, `nguonAnh`, `taoMedia`, `xoaMedia`, `MediaKem`, `CONTENT_TYPE`, `nhanCua`, `cauLoi`, `OMedia`). Thêm import mới. Đầu file còn lại:

```tsx
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, type Media } from '../api'
import { MEDIA_CATEGORY, TRAN_ANH } from '../enums'
import { LoiTai } from './TrangCuon'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'
```

- [ ] **Step 3: Chạy test — phải xanh mà không sửa test nào**

Run: `npx vitest run tests/realestate-media.test.tsx`
Expected: PASS. Nếu đỏ thì việc cắt đã làm đổi hành vi — so lại `git diff` của `VungMedia` với bản cũ, khối thân hàm phải giống từng dòng.

- [ ] **Step 4: Kiểm lint bắt hết import chết**

Run: `npm run lint`
Expected: sạch. Một import không dùng còn sót sẽ bị `@typescript-eslint/no-unused-vars` bắt ở đây.

- [ ] **Step 5: Commit**

```bash
git add src/features/realestate/components/VungMedia.tsx \
        src/features/realestate/components/MediaTab.tsx
git commit -m "refactor(re): tách VungMedia ra file riêng"
```

---

### Task 3: Tab Vị trí

Thêm tab thứ hai. `region` và `address` rời khỏi `TongQuanTab` sang đây, cùng vùng media `vi_tri`.

**Files:**
- Create: `src/features/realestate/components/ViTriTab.tsx`
- Modify: `src/features/realestate/tabDuAn.ts`
- Modify: `src/features/realestate/components/TongQuanTab.tsx` (bỏ hai ô)
- Modify: `src/features/realestate/components/DuAnForm.tsx`
- Test: `tests/realestate-tab-chuyen-de.test.tsx` (tạo mới)

**Interfaces:**
- Consumes: `VungMedia` (Task 2)
- Produces: `ViTriTab({ duAn, projectCode }: { duAn: DuAn; projectCode: string })`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/realestate-tab-chuyen-de.test.tsx`:

```tsx
/**
 * Bốn tab chuyên đề của màn dự án — Vị trí · Ảnh 360 · Mặt bằng · Tiến độ.
 *
 * Mỗi tab là một `<form>` RIÊNG ghi vào cùng row `projects`, nên thứ phải canh
 * là: nó PATCH ĐÚNG phần của mình. Gửi kèm trường của tab khác là ghi đè thứ
 * người dùng không mở ra xem.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, boot, datApiDoc, trang } from './re-fixture'

/** Thu mọi thân PATCH `/projects/:code` để assert nó chỉ chứa phần của tab. */
function batPatch() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(DU_AN)
    }),
  )
  return than
}

describe('tab Vị trí', () => {
  it('hiện khu vực, vị trí chính xác và vùng ảnh Vị trí', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    expect(await screen.findByText('Hà Nội')).toBeInTheDocument()
    expect(screen.getByText('Gia Lâm')).toBeInTheDocument()
    // `findBy`, KHÔNG `getBy`: vùng ảnh chờ một fetch riêng nên nó tới sau hai ô
    // trên một tick. Một `getByRole` ở đây đỏ tất định, và cách chữa sai là bỏ
    // cổng `isPending` của component — bộ đếm khi đó nói `0/6 ảnh` lúc đang tải.
    expect(await screen.findByRole('heading', { name: 'Vị trí', level: 3 })).toBeInTheDocument()
  })

  it('PATCH chỉ gửi region và address — không kèm trường của tab khác', async () => {
    datApiDoc({ media: trang([]) })
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')

    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const o = screen.getByRole('textbox', { name: /Khu vực/ })
    await userEvent.clear(o)
    await userEvent.type(o, 'Hưng Yên')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ region: 'Hưng Yên', address: 'Gia Lâm' })
  })

  it('tab Tổng quan không còn hai ô đã dời sang đây', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    expect(screen.queryByRole('textbox', { name: /Khu vực/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Vị trí chính xác/ })).not.toBeInTheDocument()
  })

  it('vùng ảnh Vị trí nói rõ ảnh cũng nằm ở tab Media', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    const vung = (await screen.findByRole('heading', { name: 'Vị trí', level: 3 })).closest(
      'section',
    )!
    expect(within(vung.parentElement!).getByText(/cũng nằm trong tab Media/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tab-chuyen-de.test.tsx`
Expected: FAIL — `?tab=vi-tri` bị `tabHopLe` đưa về `tong-quan` nên không tìm được heading `Vị trí`.

- [ ] **Step 3: Thêm tab vào `tabDuAn.ts`**

Thêm `'vi-tri'` vào union và chèn mục vào `TAB_DU_AN` **ngay sau** `tong-quan`:

```ts
export type TenTabDuAn = 'tong-quan' | 'vi-tri' | 'phan-khu' | 'quy-can' | 'tai-lieu' | 'media'
```

```ts
  { id: 'tong-quan', nhan: 'Tổng quan' },
  { id: 'vi-tri', nhan: 'Vị trí' },
  { id: 'phan-khu', nhan: 'Phân khu' },
```

- [ ] **Step 4: Tạo `ViTriTab.tsx`**

```tsx
/**
 * Tab Vị trí — hai ô của `projects` và vùng ảnh `vi_tri`.
 *
 * FORM RIÊNG, KHÔNG DÙNG CHUNG STATE VỚI TAB TỔNG QUAN: nó `PATCH` đúng
 * `{region, address}`, và backend dùng `exclude_unset` nên hai ô này không đụng
 * tới 14 ô còn lại. Đổi lại, đang sửa mà nhảy tab thì mất phần đang gõ — Task 8
 * dựng hộp xác nhận cho chuyện đó.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { suaDuAn, type DuAn, type Media } from '../api'
import { danhSachMedia } from '../api'
import { cauLoi, loiO } from '../thongDiep'
import { DongTrangThai, DongXem, GiaTri, NhomTruong, OChu } from './OTruong'
import { LoiTai } from './TrangCuon'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from './Bang'

/** Nội dung của tab chỉ có hai ô nên không tách nhóm thứ hai. */
interface ViTri {
  region: string
  address: string
}

export function ViTriTab({ duAn, projectCode }: { duAn: DuAn; projectCode: string }) {
  const qc = useQueryClient()
  const [value, setValue] = useState<ViTri>({ region: duAn.region, address: duAn.address })
  const [editing, setEditing] = useState(false)

  const save = useMutation({
    mutationFn: (body: ViTri) => suaDuAn(projectCode, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['re', projectCode] })
      setEditing(false)
    },
  })

  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  return (
    <div className="space-y-4">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate(value)
        }}
      >
        {editing ? (
          <NhomTruong tieuDe="Vị trí dự án">
            <OChu
              ten="region"
              nhan="Khu vực"
              batBuoc
              giaTri={value.region}
              doi={(x) => setValue({ ...value, region: x })}
              loi={loiO(save.error, 'region')}
              goiYTrongO="VD: Hà Nội · Gia Lâm"
            />
            <OChu
              ten="address"
              nhan="Vị trí chính xác"
              giaTri={value.address}
              doi={(x) => setValue({ ...value, address: x })}
              loi={loiO(save.error, 'address')}
              goiYTrongO="Số nhà, đường, phường/xã, quận/huyện"
            />
          </NhomTruong>
        ) : (
          <NhomTruong tieuDe="Vị trí dự án">
            <DongXem nhan="Khu vực">
              <GiaTri>{duAn.region}</GiaTri>
            </DongXem>
            <DongXem nhan="Vị trí chính xác">
              <GiaTri>{duAn.address}</GiaTri>
            </DongXem>
          </NhomTruong>
        )}

        {save.error && <DongTrangThai mau="alert">{cauLoi(save.error, 'lưu vị trí')}</DongTrangThai>}

        <div className={HANG_NUT}>
          {!editing ? (
            <button type="button" className={NUT_CHINH} onClick={() => setEditing(true)}>
              Sửa
            </button>
          ) : (
            <>
              <button
                type="button"
                className={NUT_PHU}
                onClick={() => {
                  setValue({ region: duAn.region, address: duAn.address })
                  save.reset()
                  setEditing(false)
                }}
              >
                Huỷ
              </button>
              <button type="submit" className={NUT_CHINH} disabled={save.isPending}>
                {save.isPending ? 'Đang lưu…' : 'Lưu thay đổi'}
              </button>
            </>
          )}
        </div>
      </form>

      {/* Spec §3: người dùng thấy cùng một ảnh ở hai tab sẽ tưởng đây là bản sao
          và bấm xoá «bản thừa». Nói ra thì không ai phải đoán. */}
      <p className="text-[13px] text-muted">
        Ảnh trong vùng này cũng nằm trong tab Media, danh mục Vị trí — cùng một ảnh, không phải
        bản sao. Xoá ở đây là xoá khỏi dự án.
      </p>

      {media.isPending ? (
        <p className="text-[14px] text-muted">Đang tải…</p>
      ) : media.error ? (
        <LoiTai viec="ảnh vị trí" thuLai={() => void media.refetch()} />
      ) : (
        <VungMedia
          projectCode={projectCode}
          category="vi_tri"
          nhan="Vị trí"
          anh={media.items.filter((m) => !m.zoneCode && !m.unitCode && m.category === 'vi_tri')}
          lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 5: Bỏ hai ô khỏi `TongQuanTab.tsx`**

Xoá hai khối `<OChu ten="region" …>` và `<OChu ten="address" …>` trong `NhomTruong tieuDe="Định danh & vị trí"`, đổi tiêu đề nhóm đó thành `"Định danh & phân loại"`, và bỏ `region`/`address` khỏi `DU_AN_MOI` cùng `tuDuAn()`.

⚠️ `completeness.ts` tính `region` là trường bắt buộc để publish. **Không** sửa nó: thanh "còn thiếu để phát hành" ở tab Tổng quan vẫn phải nói `Khu vực` khi thiếu, vì nó nói về cả dự án. Nhưng `thieuTruongDuAn(v)` nay nhận một `v` không có `region` — sửa lời gọi ở `TongQuanTab` để truyền `{ ...v, region: duAn?.region ?? '' }`:

```tsx
  const thieu = thieuTruongDuAn({ ...v, region: duAn?.region ?? '' })
```

Với dự án mới (`duAn === null`) thì `region` rỗng nên thanh cảnh báo hiện đúng, và người dùng sang tab Vị trí điền — tab đó mở được ngay sau khi `Tạo dự án` xong.

- [ ] **Step 6: Nối vào `DuAnForm.tsx`**

Thêm import và nhánh render **sau** `tong-quan`:

```tsx
import { ViTriTab } from './ViTriTab'
```

```tsx
      {tab === 'vi-tri' && code && duAn && <ViTriTab duAn={duAn} projectCode={code} />}
```

- [ ] **Step 7: Chạy test**

Run: `npx vitest run tests/realestate-tab-chuyen-de.test.tsx tests/realestate-pform.test.tsx`
Expected: PASS. Nếu `realestate-pform.test.tsx` đỏ ở một test tìm ô `Khu vực` trên tab Tổng quan thì sửa test đó sang tab `vi-tri` — ô đã dời chỗ, đó là thay đổi có chủ ý.

- [ ] **Step 8: Chạy toàn bộ**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 9: Commit**

```bash
git add src/features/realestate/tabDuAn.ts \
        src/features/realestate/components/ViTriTab.tsx \
        src/features/realestate/components/TongQuanTab.tsx \
        src/features/realestate/components/DuAnForm.tsx \
        tests/realestate-tab-chuyen-de.test.tsx \
        tests/realestate-pform.test.tsx
git commit -m "feat(re): tab Vị trí"
```

---

### Task 4: Tab Ảnh 360

`link360` rời khỏi `TongQuanTab`. Tab này chỉ có một ô nhập — nó tồn tại vì bộ tab ngành có, và vì một link tham quan ảo là thứ sale mở ra cho khách xem chứ không phải một dòng trong form dài.

**Files:**
- Create: `src/features/realestate/components/Anh360Tab.tsx`
- Modify: `src/features/realestate/tabDuAn.ts`
- Modify: `src/features/realestate/components/TongQuanTab.tsx`
- Modify: `src/features/realestate/components/DuAnForm.tsx`
- Test: `tests/realestate-tab-chuyen-de.test.tsx`

**Interfaces:**
- Consumes: —
- Produces: `Anh360Tab({ duAn, projectCode }: { duAn: DuAn; projectCode: string })`

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-tab-chuyen-de.test.tsx`:

```tsx
describe('tab Ảnh 360', () => {
  it('hiện link hiện có và mở được ra tab mới', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=anh-360')

    const link = await screen.findByRole('link', { name: 'https://kuula.co/share/x' })
    expect(link).toHaveAttribute('href', 'https://kuula.co/share/x')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('PATCH chỉ gửi link360', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=anh-360')

    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const o = screen.getByRole('textbox', { name: /Link tham quan 360/ })
    await userEvent.clear(o)
    await userEvent.type(o, 'https://kuula.co/share/moi')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ link360: 'https://kuula.co/share/moi' })
  })

  it('chưa có link thì nói rõ chưa có, không hiện link rỗng', async () => {
    datApiDoc({ project: { ...DU_AN, link360: '' } })
    boot('/pform?code=VHOP2&tab=anh-360')

    expect(await screen.findByText(/Chưa có link tham quan 360/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /kuula/ })).not.toBeInTheDocument()
  })

  it('tab Tổng quan không còn ô link360', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    expect(
      screen.queryByRole('textbox', { name: /Link tham quan 360/ }),
    ).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tab-chuyen-de.test.tsx -t 'tab Ảnh 360'`
Expected: FAIL — không tìm được link vì `?tab=anh-360` rơi về `tong-quan`.

- [ ] **Step 3: Thêm tab vào `tabDuAn.ts`**

```ts
export type TenTabDuAn =
  | 'tong-quan'
  | 'vi-tri'
  | 'anh-360'
  | 'phan-khu'
  | 'quy-can'
  | 'tai-lieu'
  | 'media'
```

```ts
  { id: 'vi-tri', nhan: 'Vị trí' },
  { id: 'anh-360', nhan: 'Ảnh 360' },
  { id: 'phan-khu', nhan: 'Phân khu' },
```

- [ ] **Step 4: Tạo `Anh360Tab.tsx`**

```tsx
/**
 * Tab Ảnh 360 — một ô `link360`.
 *
 * MỘT Ô CHO CẢ MỘT TAB, cố ý: bộ tab ngành có mục này, và người dùng tới đây để
 * MỞ link cho khách xem chứ không để nhập. Nên phần chính của tab là chính cái
 * link bấm được, ô nhập chỉ hiện khi bấm Sửa.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { suaDuAn, type DuAn } from '../api'
import { cauLoi, loiO } from '../thongDiep'
import { DongTrangThai, NhomTruong, OChu } from './OTruong'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from './Bang'

export function Anh360Tab({ duAn, projectCode }: { duAn: DuAn; projectCode: string }) {
  const qc = useQueryClient()
  const [value, setValue] = useState(duAn.link360)
  const [editing, setEditing] = useState(false)

  const save = useMutation({
    mutationFn: (link360: string) => suaDuAn(projectCode, { link360 }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['re', projectCode] })
      setEditing(false)
    },
  })

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate(value)
      }}
    >
      <NhomTruong tieuDe="Tham quan 360">
        {editing ? (
          <OChu
            ten="link360"
            nhan="Link tham quan 360"
            giaTri={value}
            doi={setValue}
            loi={loiO(save.error, 'link360')}
            goiY="Kuula, Matterport, hoặc bất cứ dịch vụ nào cho một link xem được"
            goiYTrongO="https://kuula.co/share/collection/…"
          />
        ) : duAn.link360 ? (
          <a
            href={duAn.link360}
            target="_blank"
            rel="noreferrer"
            className="text-[14px] text-ac underline"
          >
            {duAn.link360}
          </a>
        ) : (
          <p className="text-[14px] text-muted">
            Chưa có link tham quan 360. Bấm Sửa để thêm.
          </p>
        )}
      </NhomTruong>

      {save.error && <DongTrangThai mau="alert">{cauLoi(save.error, 'lưu link 360')}</DongTrangThai>}

      <div className={HANG_NUT}>
        {!editing ? (
          <button type="button" className={NUT_CHINH} onClick={() => setEditing(true)}>
            Sửa
          </button>
        ) : (
          <>
            <button
              type="button"
              className={NUT_PHU}
              onClick={() => {
                setValue(duAn.link360)
                save.reset()
                setEditing(false)
              }}
            >
              Huỷ
            </button>
            <button type="submit" className={NUT_CHINH} disabled={save.isPending}>
              {save.isPending ? 'Đang lưu…' : 'Lưu thay đổi'}
            </button>
          </>
        )}
      </div>
    </form>
  )
}
```

- [ ] **Step 5: Bỏ ô khỏi `TongQuanTab.tsx`**

Xoá khối `<OChu ten="link360" …>` trong `NhomTruong tieuDe="Mô tả & liên kết"`, đổi tiêu đề nhóm đó thành `"Mô tả"`, và bỏ `link360` khỏi `DU_AN_MOI` cùng `tuDuAn()`.

- [ ] **Step 6: Nối vào `DuAnForm.tsx`**

```tsx
import { Anh360Tab } from './Anh360Tab'
```

```tsx
      {tab === 'anh-360' && code && duAn && (
        // `key` buộc form dựng lại state khi đổi sang dự án khác. `useState` khởi
        // tạo MỘT lần, nên thiếu key thì ô nhập giữ giá trị của dự án vừa xem và
        // lần Lưu sau ghi nó lên dự án đang mở. `TongQuanTab` có cùng khoá này.
        <Anh360Tab key={duAn.projectCode} duAn={duAn} projectCode={code} />
      )}
```

- [ ] **Step 7: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 8: Commit**

```bash
git add src/features/realestate/tabDuAn.ts \
        src/features/realestate/components/Anh360Tab.tsx \
        src/features/realestate/components/TongQuanTab.tsx \
        src/features/realestate/components/DuAnForm.tsx \
        tests/realestate-tab-chuyen-de.test.tsx
git commit -m "feat(re): tab Ảnh 360"
```

---

### Task 5: Tab Mặt bằng

Vùng media `mat_bang` cộng ô ảnh mặt bằng tổng (`mapMedia`), cả hai rời khỏi `TongQuanTab`.

**Files:**
- Create: `src/features/realestate/components/MatBangTab.tsx`
- Modify: `src/features/realestate/tabDuAn.ts`
- Modify: `src/features/realestate/components/TongQuanTab.tsx`
- Modify: `src/features/realestate/components/DuAnForm.tsx`
- Test: `tests/realestate-tab-chuyen-de.test.tsx`

**Interfaces:**
- Consumes: `VungMedia` (Task 2)
- Produces: `MatBangTab({ duAn, projectCode }: { duAn: DuAn; projectCode: string })`

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-tab-chuyen-de.test.tsx`:

```tsx
describe('tab Mặt bằng', () => {
  it('hiện vùng ảnh Mặt bằng và ô ảnh mặt bằng tổng', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=mat-bang')

    expect(await screen.findByRole('heading', { name: 'Mặt bằng', level: 3 })).toBeInTheDocument()
    expect(screen.getByText('Ảnh mặt bằng tổng')).toBeInTheDocument()
  })

  it('ảnh mat_bang của phân khu KHÔNG lẫn vào vùng cấp dự án', async () => {
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 95, category: 'mat_bang', caption: 'Mặt bằng dự án' },
        { ...MEDIA, id: 96, category: 'mat_bang', zoneCode: 'ZURICH', caption: 'Mặt bằng phân khu' },
      ]),
    })
    boot('/pform?code=VHOP2&tab=mat-bang')

    const vung = (await screen.findByRole('heading', { name: 'Mặt bằng', level: 3 })).closest(
      'section',
    )!
    expect(within(vung).getByText('1/6 ảnh')).toBeInTheDocument()
    expect(screen.queryByText('Mặt bằng phân khu')).not.toBeInTheDocument()
  })

  it('tab Tổng quan không còn ô ảnh mặt bằng tổng', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    expect(screen.queryByText('Ảnh mặt bằng tổng')).not.toBeInTheDocument()
  })
})
```

Thêm `MEDIA` vào dòng import từ `./re-fixture` ở đầu file:

```tsx
import { DU_AN, MEDIA, boot, datApiDoc, trang } from './re-fixture'
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tab-chuyen-de.test.tsx -t 'tab Mặt bằng'`
Expected: FAIL — không tìm được heading `Mặt bằng`.

- [ ] **Step 3: Thêm tab vào `tabDuAn.ts`**

Thêm `'mat-bang'` vào union, và chèn **sau** `phan-khu`:

```ts
  { id: 'phan-khu', nhan: 'Phân khu' },
  { id: 'mat-bang', nhan: 'Mặt bằng' },
  { id: 'quy-can', nhan: 'Quỹ căn' },
```

- [ ] **Step 4: Tạo `MatBangTab.tsx`**

```tsx
/**
 * Tab Mặt bằng — vùng ảnh `mat_bang` và ô ảnh mặt bằng tổng của dự án.
 *
 * ĐỨNG NGAY TRƯỚC TAB QUỸ CĂN, đúng thứ tự bộ tab ngành: người mở mặt bằng là
 * để chọn căn. Mặt bằng của PHÂN KHU nằm trong form phân khu, không ở đây —
 * cùng luật với `MediaTab` (lọc `zoneCode`/`unitCode` rỗng).
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, suaDuAn, type DuAn, type Media, type MediaKem } from '../api'
import { cauLoi } from '../thongDiep'
import { DongTrangThai, NhomTruong } from './OTruong'
import { OMedia } from './OMedia'
import { LoiTai } from './TrangCuon'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'
import { HANG_NUT, NUT_CHINH } from './Bang'

export function MatBangTab({ duAn, projectCode }: { duAn: DuAn; projectCode: string }) {
  const qc = useQueryClient()
  const [mapMedia, setMapMedia] = useState<MediaKem | null>(null)

  const save = useMutation({
    mutationFn: (body: MediaKem) => suaDuAn(projectCode, { mapMedia: body }),
    onSuccess: () => {
      setMapMedia(null)
      void qc.invalidateQueries({ queryKey: ['re', projectCode] })
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })
    },
  })

  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  return (
    <div className="space-y-4">
      <NhomTruong tieuDe="Mặt bằng tổng thể">
        <OMedia
          nhan="Ảnh mặt bằng tổng"
          giaTri={mapMedia}
          doi={setMapMedia}
          goiY="Lưu vào danh mục Mặt bằng và gán làm mặt bằng tổng của dự án"
        />
      </NhomTruong>

      {save.error && (
        <DongTrangThai mau="alert">{cauLoi(save.error, 'lưu mặt bằng tổng')}</DongTrangThai>
      )}

      <div className={HANG_NUT}>
        <button
          type="button"
          className={NUT_CHINH}
          disabled={save.isPending || !mapMedia?.mediaUrl}
          onClick={() => mapMedia && save.mutate(mapMedia)}
        >
          {save.isPending ? 'Đang lưu…' : 'Lưu mặt bằng tổng'}
        </button>
      </div>

      <p className="text-[13px] text-muted">
        Ảnh trong vùng này cũng nằm trong tab Media, danh mục Mặt bằng — cùng một ảnh, không phải
        bản sao. Mặt bằng của phân khu nằm trong form phân khu.
      </p>

      {media.isPending ? (
        <p className="text-[14px] text-muted">Đang tải…</p>
      ) : media.error ? (
        <LoiTai viec="ảnh mặt bằng" thuLai={() => void media.refetch()} />
      ) : (
        <VungMedia
          projectCode={projectCode}
          category="mat_bang"
          nhan="Mặt bằng"
          anh={media.items.filter((m) => !m.zoneCode && !m.unitCode && m.category === 'mat_bang')}
          lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })}
        />
      )}
    </div>
  )
}
```

⚠️ `duAn` nhận vào nhưng chỉ dùng để giữ chữ ký nhất quán với ba tab kia — nếu lint báo `duAn` không dùng thì bỏ nó khỏi prop và bỏ luôn ở `DuAnForm`, đừng thêm `void duAn` cho im lặng.

- [ ] **Step 5: Bỏ ô khỏi `TongQuanTab.tsx`**

Trong khối `<CaHang><div className="grid gap-4 md:grid-cols-2">…`, xoá `<OMedia nhan="Ảnh mặt bằng tổng" …>` và bỏ `grid md:grid-cols-2` (chỉ còn một ô cover):

```tsx
            <CaHang>
              <OMedia
                nhan="Ảnh cover"
                giaTri={v.coverMedia ?? null}
                doi={(x) => setV({ ...v, coverMedia: x })}
                goiY="Lưu vào danh mục Tổng quan và gán làm ảnh đại diện dự án"
              />
            </CaHang>
```

Bỏ `mapMedia` khỏi `DU_AN_MOI` nếu có, và khỏi `tuDuAn()`.

⚠️ **Và phải sửa `TomTatDuAn.tsx` cùng lúc** — nó là chế độ XEM của tab Tổng quan.
Dòng 119 đọc `v.mapMedia?.mediaUrl`; sau khi `tuDuAn()` thôi copy trường đó, `v.mapMedia`
luôn `undefined` nên ô ảnh ở chế độ xem thành rỗng cho một dự án có mặt bằng thật. Task 3
và Task 4 đều đã sập đúng hố này (`region`/`address`, rồi `link360`): `GiaTri` render giá
trị rỗng thành chữ **"Chưa đặt"**, nên màn *khẳng định* một điều sai chứ không chỉ để trống.
Bỏ dòng `<Anh nhan="Ảnh mặt bằng tổng" …>` khỏi `TomTatDuAn.tsx`, và kiểm luôn tiêu đề
nhóm ở chế độ xem có khớp tiêu đề ở chế độ sửa không.

**Thêm một test** cho chế độ xem: mở `/pform?code=VHOP2` (không bấm Sửa) và assert màn
KHÔNG còn nhắc `Ảnh mặt bằng tổng`. Không có test này thì hai lần trước đã không ai bắt được.

- [ ] **Step 6: Nối vào `DuAnForm.tsx`**

```tsx
import { MatBangTab } from './MatBangTab'
```

```tsx
      {tab === 'mat-bang' && code && duAn && (
        // `key`: xem lý do ở nhánh `anh-360`.
        <MatBangTab key={duAn.projectCode} duAn={duAn} projectCode={code} />
      )}
```

- [ ] **Step 7: Thêm test canh `key`**

`key={duAn.projectCode}` là lưới chống "state dự án cũ ghi lên dự án mới", nhưng nó **không tự có cổng canh** — Task 4 có `key` đúng mà bỏ nó ra thì toàn bộ suite vẫn xanh. Bản test hiển nhiên không bắt được: điều hướng sang một dự án chưa nằm trong cache đưa `DuAnForm` vào nhánh `q.isPending`, nó unmount và state reset. Phải **hâm cache** dự án thứ hai trước.

Thêm vào `tests/realestate-tab-chuyen-de.test.tsx`, theo đúng khuôn test `key` mà Task 3 đã viết (đọc nó trước — `tests/realestate-tab-chuyen-de.test.tsx`, test "đổi sang dự án khác"): dùng `const router = boot(…)` rồi `router.navigate(…)`, khai một handler `http.get('/api/v1/projects/:code', …)` trả hai dự án khác nhau theo `params.code`, và assert ô của tab mang giá trị của dự án **thứ hai**.

Chạy: bỏ `key` ra khỏi nhánh `mat-bang` trong `DuAnForm`, chạy test đó, xác nhận nó **đỏ**, rồi trả `key` lại.

- [ ] **Step 8: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 9: Commit**

```bash
git add src/features/realestate/tabDuAn.ts \
        src/features/realestate/components/MatBangTab.tsx \
        src/features/realestate/components/TongQuanTab.tsx \
        src/features/realestate/components/DuAnForm.tsx \
        src/features/realestate/components/TomTatDuAn.tsx \
        tests/realestate-tab-chuyen-de.test.tsx
git commit -m "feat(re): tab Mặt bằng"
```

---

### Task 6: Tab Tiến độ

Một vùng media `tien_do`. Không có trường nào của `projects` ở đây.

**Files:**
- Create: `src/features/realestate/components/TienDoTab.tsx`
- Modify: `src/features/realestate/tabDuAn.ts`
- Modify: `src/features/realestate/components/DuAnForm.tsx`
- Test: `tests/realestate-tab-chuyen-de.test.tsx`

**Interfaces:**
- Consumes: `VungMedia` (Task 2)
- Produces: `TienDoTab({ projectCode }: { projectCode: string })`

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-tab-chuyen-de.test.tsx`:

```tsx
describe('tab Tiến độ', () => {
  it('hiện vùng ảnh Tiến độ, và video tiến độ ở lại đây chứ không có tab Video riêng', async () => {
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 97, category: 'tien_do', caption: 'Móng tháng 7' },
        {
          ...MEDIA,
          id: 98,
          category: 'tien_do',
          contentType: 'video',
          caption: 'Bay drone tháng 8',
        },
      ]),
    })
    boot('/pform?code=VHOP2&tab=tien-do')

    const vung = (await screen.findByRole('heading', { name: 'Tiến độ', level: 3 })).closest(
      'section',
    )!
    // Chỉ ảnh bị đếm vào trần; video đếm riêng — nếu không thì hai con số lệch nhau.
    expect(within(vung).getByText(/1\/6 ảnh/)).toBeInTheDocument()
    expect(within(vung).getByText(/1 video/)).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Video' })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tab-chuyen-de.test.tsx -t 'tab Tiến độ'`
Expected: FAIL — không tìm được heading `Tiến độ`.

- [ ] **Step 3: Thêm tab vào `tabDuAn.ts`**

Thêm `'tien-do'` vào union, và chèn **sau** `media`:

```ts
  { id: 'media', nhan: 'Media' },
  { id: 'tien-do', nhan: 'Tiến độ' },
  { id: 'tai-lieu', nhan: 'Tài liệu' },
```

- [ ] **Step 4: Tạo `TienDoTab.tsx`**

```tsx
/**
 * Tab Tiến độ — một vùng media `tien_do`.
 *
 * KHÔNG CÓ TAB VIDEO RIÊNG, và đây là chỗ thấy rõ vì sao: `media` phân biệt bằng
 * HAI trục — `category` và `content_type`. Một tab Video cắt ngang trục
 * `category`, nên video tiến độ sẽ xuất hiện ở cả hai tab; xoá ở một chỗ thì
 * chỗ kia biến mất mà người dùng không hiểu vì sao. Video ở lại tab chủ đề.
 */
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, type Media } from '../api'
import { LoiTai } from './TrangCuon'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'

export function TienDoTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  if (media.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (media.error) return <LoiTai viec="ảnh tiến độ" thuLai={() => void media.refetch()} />

  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted">
        Ảnh và video tiến độ thi công. Nội dung ở đây cũng nằm trong tab Media, danh mục Tiến độ —
        cùng một bản ghi, không phải bản sao.
      </p>
      <VungMedia
        projectCode={projectCode}
        category="tien_do"
        nhan="Tiến độ"
        anh={media.items.filter((m) => !m.zoneCode && !m.unitCode && m.category === 'tien_do')}
        lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })}
      />
    </div>
  )
}
```

- [ ] **Step 5: Nối vào `DuAnForm.tsx`**

```tsx
import { TienDoTab } from './TienDoTab'
```

```tsx
      {tab === 'tien-do' && code && <TienDoTab projectCode={code} />}
```

- [ ] **Step 6: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 7: Commit**

```bash
git add src/features/realestate/tabDuAn.ts \
        src/features/realestate/components/TienDoTab.tsx \
        src/features/realestate/components/DuAnForm.tsx \
        tests/realestate-tab-chuyen-de.test.tsx
git commit -m "feat(re): tab Tiến độ"
```

---

### Task 7: `MediaTab` nói ra quan hệ tổng — bộ phận

Tab `Media` giữ **cả bảy vùng**, gồm ba vùng nay đã có tab chuyên đề. Đây là chủ ý của spec §3, nhưng nó chỉ đúng nếu UI nói ra.

**Files:**
- Modify: `src/features/realestate/components/MediaTab.tsx`
- Test: `tests/realestate-media.test.tsx`

**Interfaces:**
- Consumes: `VungMedia` (Task 2)
- Produces: —

- [ ] **Step 1: Viết test đỏ**

Thêm vào `describe('tab Media — 7 vùng, trần theo danh mục', …)` trong `tests/realestate-media.test.tsx`:

```tsx
  it('nói rõ ba vùng cũng có tab chuyên đề riêng — cùng một ảnh, không phải bản sao', async () => {
    datApiDoc({ media: trang([MEDIA]) })
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Media' }))

    expect(
      await screen.findByText(/Vị trí, Mặt bằng và Tiến độ còn có tab riêng/),
    ).toBeInTheDocument()
  })
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-media.test.tsx -t 'tab chuyên đề riêng'`
Expected: FAIL — không tìm thấy câu đó.

- [ ] **Step 3: Sửa `MediaTab.tsx`**

Thay đoạn `<p className="text-[13px] text-muted">` ở đầu bằng:

```tsx
      <p className="text-[13px] text-muted">
        Toàn bộ ảnh và video cấp dự án, đủ bảy danh mục. Vị trí, Mặt bằng và Tiến độ còn có tab
        riêng — đó là cùng những ảnh này, không phải bản sao, nên xoá ở đây là xoá khỏi dự án. Ảnh
        của phân khu nằm trong form phân khu, ảnh của căn nằm trong form căn. Mỗi danh mục nhận tối
        đa {TRAN_ANH} ảnh; video (link YouTube/kuula) không tính vào giới hạn đó.
      </p>
```

Và sửa docstring đầu file, thêm sau đoạn về bảy vùng:

```
 * GIỮ CẢ BẢY VÙNG dù `vi_tri`/`mat_bang`/`tien_do` đã có tab chuyên đề riêng
 * (spec §3): tab chuyên đề là lối tắt, tab này là màn tổng. Cả năm tab dùng CÙNG
 * query key nên số đếm không lệch nhau.
```

- [ ] **Step 4: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 5: Commit**

```bash
git add src/features/realestate/components/MediaTab.tsx tests/realestate-media.test.tsx
git commit -m "feat(re): tab Media nói rõ quan hệ với ba tab chuyên đề"
```

---

### Task 8: Chặn mất dữ liệu khi nhảy tab

Bốn tab mới mỗi tab một form riêng, nên nhảy tab lúc đang sửa sẽ unmount và mất phần đang gõ. Task này dựng một hộp xác nhận.

**Files:**
- Create: `src/features/realestate/components/useChanRoiTab.ts`
- Modify: `src/features/realestate/components/DuAnForm.tsx`
- Modify: `src/features/realestate/components/ViTriTab.tsx`, `Anh360Tab.tsx`
- Test: `tests/realestate-tab-chuyen-de.test.tsx`

**Interfaces:**
- Consumes: —
- Produces: hook `useChanRoiTab()` trả `{ dirty: boolean, setDirty: (v: boolean) => void, xacNhanRoi: () => boolean }`, cung cấp qua React context `NgatTabContext` để tab con báo trạng thái lên `DuAnForm`.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-tab-chuyen-de.test.tsx`:

```tsx
describe('nhảy tab khi đang sửa', () => {
  it('hỏi trước khi bỏ thay đổi chưa lưu', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Khu vực/ }), ' thêm chữ')
    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))

    expect(await screen.findByRole('alertdialog')).toHaveTextContent(/chưa lưu/)
    // Vẫn ở tab Vị trí cho tới khi người dùng chọn.
    expect(screen.getByRole('tab', { name: 'Vị trí' })).toHaveAttribute('aria-selected', 'true')
  })

  it('chọn bỏ thì sang tab mới, chọn ở lại thì giữ nguyên phần đang gõ', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Khu vực/ }), 'X')
    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Ở lại' }))

    expect(screen.getByRole('textbox', { name: /Khu vực/ })).toHaveValue('Hà NộiX')

    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Bỏ thay đổi' }))

    expect(await screen.findByRole('tab', { name: 'Ảnh 360' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('không sửa gì thì nhảy tab không hỏi', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    await screen.findByText('Hà Nội')
    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(await screen.findByRole('tab', { name: 'Ảnh 360' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tab-chuyen-de.test.tsx -t 'nhảy tab'`
Expected: FAIL — không có `alertdialog` nào, tab đổi ngay.

- [ ] **Step 3: Tạo context và hook**

Tạo `src/features/realestate/components/useChanRoiTab.ts`:

```ts
/**
 * Cờ «đang có thay đổi chưa lưu» dùng chung giữa `DuAnForm` và các tab con.
 *
 * VÌ SAO CONTEXT chứ không prop: hàng tab nằm ở `DauDuAn` (component của
 * `DuAnForm`), còn cờ dirty sinh ra trong tab con. Luồn callback qua hai cấp
 * cho một cờ boolean là ba chỗ phải sửa mỗi lần thêm tab.
 *
 * Chỉ tab nào có FORM mới đặt cờ. Tab chỉ đọc (Tiến độ, Media) không cần.
 */
import { createContext, useContext } from 'react'

interface ChanRoiTab {
  dirty: boolean
  setDirty: (v: boolean) => void
}

const Ctx = createContext<ChanRoiTab>({ dirty: false, setDirty: () => {} })

export const ChanRoiTabProvider = Ctx.Provider

export function useChanRoiTab(): ChanRoiTab {
  return useContext(Ctx)
}
```

- [ ] **Step 4: Nối vào `DuAnForm.tsx`**

Thêm state, bọc provider, và chặn `doiTab`:

```tsx
import { useState } from 'react'
import { ChanRoiTabProvider } from './useChanRoiTab'
import { HopXacNhan } from './Bang'
```

```tsx
  const [dirty, setDirty] = useState(false)
  /** Tab người dùng muốn sang, đang chờ xác nhận. `null` = không có hộp nào mở. */
  const [tabChoXacNhan, setTabChoXacNhan] = useState<TenTabDuAn | null>(null)

  const diToiTab = (id: TenTabDuAn) =>
    void nav({ to: '/pform', search: code ? { code, tab: id } : {}, replace: true })

  const doiTab = (id: TenTabDuAn) => {
    if (dirty) {
      setTabChoXacNhan(id)
      return
    }
    diToiTab(id)
  }
```

Bọc phần render tab bằng provider, và thêm hộp xác nhận:

```tsx
      <ChanRoiTabProvider value={{ dirty, setDirty }}>
        {/* … các nhánh `tab === …` … */}
      </ChanRoiTabProvider>

      {tabChoXacNhan && (
        <div
          className="rounded-xl border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px]"
          role="alertdialog"
        >
          <p className="font-semibold">Bỏ thay đổi chưa lưu?</p>
          <p>Phần bạn vừa sửa ở tab này chưa được lưu. Sang tab khác là mất.</p>
          <div className={`mt-3 ${HANG_NUT}`}>
            <button type="button" className={NUT_PHU} onClick={() => setTabChoXacNhan(null)}>
              Ở lại
            </button>
            <button
              type="button"
              className={NUT_CHINH}
              onClick={() => {
                setDirty(false)
                const den = tabChoXacNhan
                setTabChoXacNhan(null)
                diToiTab(den)
              }}
            >
              Bỏ thay đổi
            </button>
          </div>
        </div>
      )}
```

Import thêm `HANG_NUT`, `NUT_CHINH`, `NUT_PHU` từ `./Bang` (`DuAnForm` đang chỉ import `NUT_PHU` và `CAO_TAB`).

**Repo KHÔNG có component hộp xác nhận dùng chung** — bốn chỗ (`TaiLieuTab:296`, `PhanKhuTab:408`, `CanTab:255`, `DuAnList:252`) đều tự dựng một `<div role="alertdialog">` inline với cùng bộ class. Khối trên là bản sao thứ năm của cùng khuôn đó, cố ý: gộp bốn chỗ kia thành một component là refactor riêng, không thuộc plan này, và làm nó ở đây sẽ khiến task này đụng bốn file không liên quan. Nếu người review muốn gộp, đó là một task độc lập sau khi mười tab đã xong.

- [ ] **Step 5: Cho `ViTriTab` và `Anh360Tab` báo cờ**

Trong cả hai, thêm:

```tsx
import { useChanRoiTab } from './useChanRoiTab'
```

Và trong thân component:

```tsx
  const { setDirty } = useChanRoiTab()
```

`ViTriTab` — mọi chỗ đổi giá trị đều đặt cờ, mọi chỗ kết thúc đều xoá cờ:

```tsx
  function suaGiaTri(next: ViTri) {
    setValue(next)
    setDirty(true)
  }
```

Dùng `suaGiaTri` ở hai `doi={…}` thay cho `setValue` trực tiếp. Trong `onSuccess` của mutation và trong nhánh Huỷ, gọi `setDirty(false)`.

`Anh360Tab` — cùng cách, với `setValue` một chuỗi:

```tsx
  function suaLink(next: string) {
    setValue(next)
    setDirty(true)
  }
```

- [ ] **Step 6: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 7: Commit**

```bash
git add src/features/realestate/components/useChanRoiTab.ts \
        src/features/realestate/components/DuAnForm.tsx \
        src/features/realestate/components/ViTriTab.tsx \
        src/features/realestate/components/Anh360Tab.tsx \
        tests/realestate-tab-chuyen-de.test.tsx
git commit -m "feat(re): hỏi trước khi bỏ thay đổi chưa lưu lúc nhảy tab"
```

---

### Task 9: Tài liệu có cột Loại và thanh lọc

Backend nay trả `loai` cùng `title` (phần đuôi). Tab Tài liệu hiện cột đó, lọc được, và form chọn được loại khi tạo/sửa.

**Files:**
- Modify: `src/features/realestate/api.ts` (`TaiLieu`, `TaiLieuGhi`)
- Modify: `src/features/realestate/enums.ts` (thêm `LOAI_TAI_LIEU`)
- Modify: `src/features/realestate/components/TaiLieuTab.tsx`
- Modify: `tests/re-fixture.tsx` (`TAI_LIEU` thêm `loai`)
- Test: `tests/realestate-tai-lieu-loai.test.tsx` (tạo mới)

**Interfaces:**
- Consumes: API trả `loai: 'csbh' | 'phap_ly' | 'huong_dan' | 'khac'`
- Produces: `TaiLieuTab({ projectCode, cao, loaiKhoa }: { projectCode: string; cao?: string | undefined; loaiKhoa?: LoaiTaiLieu | undefined })` — `loaiKhoa` khoá bộ lọc và ẩn thanh lọc (Task 10 dùng); `LOAI_TAI_LIEU: readonly MucChon[]`; type `LoaiTaiLieu`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/realestate-tai-lieu-loai.test.tsx`:

```tsx
/**
 * Phân loại tài liệu — cột Loại, thanh lọc, và ô chọn loại trong form.
 *
 * `documents` không có cột phân loại: backend mã hoá loại bằng tiền tố ở đầu
 * `title` và tách ra ở biên HTTP. Frontend KHÔNG được biết về tiền tố đó — nó
 * chỉ thấy hai trường rời nhau. Một test bắt được chữ «CSBH — » trong ô tiêu đề
 * nghĩa là tiền tố đã lọt ra ngoài.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { TAI_LIEU, boot, datApiDoc, trang } from './re-fixture'

const CSBH = { ...TAI_LIEU, id: 71, loai: 'csbh', title: 'Bảng giá đợt 3' }
const PHAP_LY = { ...TAI_LIEU, id: 72, loai: 'phap_ly', title: 'Sổ đỏ' }
const KHAC = { ...TAI_LIEU, id: 73, loai: 'khac', title: 'Brochure' }

async function moTabTaiLieu() {
  boot('/pform?code=VHOP2')
  await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
}

describe('cột Loại', () => {
  it('bảng hiện nhãn tiếng Việt của loại, không hiện mã máy', async () => {
    datApiDoc({ documents: trang([CSBH, PHAP_LY]) })
    await moTabTaiLieu()

    expect(await screen.findByText('Chính sách bán hàng')).toBeInTheDocument()
    expect(screen.getByText('Pháp lý')).toBeInTheDocument()
    expect(screen.queryByText('csbh')).not.toBeInTheDocument()
    expect(screen.queryByText('phap_ly')).not.toBeInTheDocument()
  })

  it('tiêu đề KHÔNG mang tiền tố — tiền tố là việc của backend', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    await moTabTaiLieu()

    expect(await screen.findByText('Bảng giá đợt 3')).toBeInTheDocument()
    expect(screen.queryByText(/CSBH —/)).not.toBeInTheDocument()
  })
})

describe('thanh lọc theo loại', () => {
  it('mỗi loại hiện số lượng của nó, và bấm vào thì bảng chỉ còn loại đó', async () => {
    datApiDoc({ documents: trang([CSBH, PHAP_LY, KHAC]) })
    await moTabTaiLieu()

    const thanh = await screen.findByRole('group', { name: 'Lọc theo loại' })
    expect(within(thanh).getByRole('button', { name: /Tất cả 3/ })).toBeInTheDocument()
    expect(within(thanh).getByRole('button', { name: /Chính sách bán hàng 1/ })).toBeInTheDocument()

    await userEvent.click(within(thanh).getByRole('button', { name: /Chính sách bán hàng 1/ }))

    expect(screen.getByText('Bảng giá đợt 3')).toBeInTheDocument()
    expect(screen.queryByText('Sổ đỏ')).not.toBeInTheDocument()
    expect(screen.queryByText('Brochure')).not.toBeInTheDocument()
  })

  it('lọc một loại rỗng thì nói rõ là rỗng vì bộ lọc, không phải kho rỗng', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    await moTabTaiLieu()

    const thanh = await screen.findByRole('group', { name: 'Lọc theo loại' })
    await userEvent.click(within(thanh).getByRole('button', { name: /Hướng dẫn 0/ }))

    expect(screen.getByText(/Không có tài liệu nào thuộc loại này/)).toBeInTheDocument()
  })
})

describe('form tài liệu', () => {
  it('tạo mới gửi `loai` rời khỏi `title`', async () => {
    datApiDoc({ documents: trang([]) })
    const than: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/projects/:code/documents', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CSBH, { status: 201 })
      }),
    )
    await moTabTaiLieu()

    await userEvent.click(await screen.findByRole('button', { name: 'Thêm tài liệu' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Tiêu đề/ }), 'Bảng giá đợt 3')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Loại/ }), 'csbh')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu tài liệu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.title).toBe('Bảng giá đợt 3')
    expect(than[0]!.loai).toBe('csbh')
  })

  it('không chọn loại thì mặc định là Khác', async () => {
    datApiDoc({ documents: trang([]) })
    const than: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/projects/:code/documents', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(KHAC, { status: 201 })
      }),
    )
    await moTabTaiLieu()

    await userEvent.click(await screen.findByRole('button', { name: 'Thêm tài liệu' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Tiêu đề/ }), 'Brochure')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu tài liệu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.loai).toBe('khac')
  })
})
```

Hai nhãn nút trong test là nhãn **thật** của `TaiLieuTab` hiện tại: nút mở form là `Thêm tài liệu` (dòng 214), nút lưu là `Lưu tài liệu` (dòng 407) — dùng cho cả tạo mới lẫn sửa. Đừng đổi nhãn UI để test xanh.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tai-lieu-loai.test.tsx`
Expected: FAIL — không có cột Loại, không có thanh lọc.

- [ ] **Step 3: Thêm type vào `api.ts`**

Trong `interface TaiLieu`, thêm sau `projectCode`:

```ts
  /** Suy từ tiền tố `title` ở backend — FE không bao giờ thấy tiền tố. */
  readonly loai: LoaiTaiLieu
```

Trong `interface TaiLieuGhi`:

```ts
  loai?: LoaiTaiLieu | undefined
```

Và khai type cạnh các type khác của file:

```ts
export type LoaiTaiLieu = 'csbh' | 'phap_ly' | 'huong_dan' | 'khac'
```

- [ ] **Step 4: Thêm nhãn vào `enums.ts`**

Thêm cạnh `MEDIA_CATEGORY`:

```ts
/**
 * 4 loại tài liệu. GIÁ TRỊ khớp `Literal[...]` của `DocumentIn.loai` ở
 * `modules/realestate/router.py`; nhãn ở đây chỉ để hiển thị.
 *
 * ⚠️ Backend mã hoá loại bằng TIỀN TỐ trong `documents.title` (bảng không có cột
 * phân loại). Tiền tố đó KHÔNG bao giờ ra tới FE — router ghép và tách ở biên
 * HTTP. Đừng thêm tiền tố vào nhãn dưới đây và đừng tự ghép nó vào `title`.
 */
export const LOAI_TAI_LIEU = chon([
  { value: 'csbh', nhan: 'Chính sách bán hàng' },
  { value: 'phap_ly', nhan: 'Pháp lý' },
  { value: 'huong_dan', nhan: 'Hướng dẫn' },
  { value: 'khac', nhan: 'Khác' },
])
```

- [ ] **Step 5: Sửa `re-fixture.tsx`**

`TAI_LIEU` thêm `loai`:

```ts
export const TAI_LIEU = {
  id: 70,
  projectCode: 'VHOP2',
  loai: 'khac',
  title: 'Chính sách bán hàng Q3',
  body: 'Nội dung chính sách…',
  fileUrl: 'tenants/rew/kb-bds/abc/csbh.pdf',
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}
```

- [ ] **Step 6: Sửa `TaiLieuTab.tsx`**

Thêm import:

```tsx
import { LOAI_TAI_LIEU, TRANG_THAI, nhanCua } from '../enums'
import type { LoaiTaiLieu } from '../api'
```

Thêm cột vào `COT`, ngay sau `Tiêu đề`:

```tsx
const COT: readonly Cot[] = [
  { nhan: 'Tiêu đề' },
  { nhan: 'Loại' },
  { nhan: 'Nội dung' },
  { nhan: 'Tệp' },
  { nhan: 'Trạng thái' },
  { nhan: '', phai: true },
]
```

Thêm `loai` vào bản ghi rỗng:

```tsx
const MOI: TaiLieuGhi = { title: '', loai: 'khac', body: '', fileUrl: null, status: 'draft' }
```

Thêm prop và state lọc:

```tsx
interface Props {
  projectCode: string
  /** Class chiều cao của thẻ bảng — xem `TheBang`. */
  cao?: string | undefined
  /**
   * Khoá bộ lọc ở một loại và ẩn thanh lọc — tab CSBH dùng để thành một lăng
   * kính một-loại của chính danh sách này (spec §3).
   */
  loaiKhoa?: LoaiTaiLieu | undefined
}
```

```tsx
  const [locLoai, setLocLoai] = useState<LoaiTaiLieu | null>(loaiKhoa ?? null)
```

Lọc danh sách trước khi render bảng:

```tsx
  // Lọc CLIENT-SIDE trên danh sách dùng chung, không thêm tham số API: cùng lý do
  // năm tab media dùng chung một query key — hai query rời nhau sẽ lệch nhau.
  const hienThi = locLoai ? ds.items.filter((t) => t.loai === locLoai) : ds.items
```

Mọi chỗ đang render từ `ds.items` đổi sang `hienThi`. Thêm thanh lọc ngay trên bảng, chỉ khi `loaiKhoa` không có:

```tsx
      {!loaiKhoa && (
        <div role="group" aria-label="Lọc theo loại" className="flex flex-wrap gap-1">
          <button
            type="button"
            className={locLoai === null ? PILL : NUT_PHU}
            onClick={() => setLocLoai(null)}
          >
            Tất cả {ds.items.length}
          </button>
          {LOAI_TAI_LIEU.map((l) => (
            <button
              key={l.value}
              type="button"
              className={locLoai === l.value ? PILL : NUT_PHU}
              onClick={() => setLocLoai(l.value as LoaiTaiLieu)}
            >
              {l.nhan} {ds.items.filter((t) => t.loai === l.value).length}
            </button>
          ))}
        </div>
      )}
```

Thêm ô `Loại` vào form (cạnh ô Trạng thái, cùng `NhomTruong`):

```tsx
            <OChon
              ten="loai"
              nhan="Loại"
              giaTri={nhap.loai ?? 'khac'}
              doi={(x) => setNhap({ ...nhap, loai: x as LoaiTaiLieu })}
              muc={LOAI_TAI_LIEU}
              loi={loiO(mGhi.error, 'loai')}
              goiY="Tab CSBH chỉ hiện tài liệu thuộc loại Chính sách bán hàng"
            />
```

Thêm ô `Loại` vào mỗi hàng bảng và vào bản xem (`DongXem`), dùng `nhanCua(LOAI_TAI_LIEU, t.loai)`.

Và câu cho trường hợp lọc ra rỗng — đặt cạnh `KhoRong` hiện có:

```tsx
      {hienThi.length === 0 && ds.items.length > 0 && (
        <p className="text-[14px] text-muted">
          Không có tài liệu nào thuộc loại này. Bỏ bộ lọc để xem tất cả.
        </p>
      )}
```

- [ ] **Step 7: Chạy test**

Run: `npx vitest run tests/realestate-tai-lieu-loai.test.tsx`
Expected: PASS (7 test).

- [ ] **Step 8: Chạy toàn bộ**

Run: `npm test && npm run lint`
Expected: PASS. `tests/realestate-media.test.tsx` có ba test đọc tab Tài liệu — nếu chúng đỏ vì cột mới làm lệch chỉ số `td:nth-child`, sửa chúng tra theo text thay vì theo vị trí cột.

- [ ] **Step 9: Commit**

```bash
git add src/features/realestate/api.ts \
        src/features/realestate/enums.ts \
        src/features/realestate/components/TaiLieuTab.tsx \
        tests/re-fixture.tsx \
        tests/realestate-tai-lieu-loai.test.tsx \
        tests/realestate-media.test.tsx
git commit -m "feat(re): tài liệu có cột Loại và thanh lọc"
```

---

### Task 10: Tab CSBH

Tab thứ mười, và tab cuối. Nó là **cùng** component `TaiLieuTab` với bộ lọc khoá — một lăng kính, không phải một kho thứ hai.

**Files:**
- Modify: `src/features/realestate/tabDuAn.ts`
- Modify: `src/features/realestate/components/DuAnForm.tsx`
- Test: `tests/realestate-tai-lieu-loai.test.tsx`

**Interfaces:**
- Consumes: `TaiLieuTab` với prop `loaiKhoa` (Task 9)
- Produces: bộ mười tab hoàn chỉnh.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-tai-lieu-loai.test.tsx`:

```tsx
describe('tab CSBH', () => {
  it('chỉ hiện tài liệu CSBH, và không có thanh lọc', async () => {
    datApiDoc({ documents: trang([CSBH, PHAP_LY, KHAC]) })
    boot('/pform?code=VHOP2&tab=csbh')

    expect(await screen.findByText('Bảng giá đợt 3')).toBeInTheDocument()
    expect(screen.queryByText('Sổ đỏ')).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Lọc theo loại' })).not.toBeInTheDocument()
  })

  it('nói rõ đây là lát cắt của tab Tài liệu, không phải kho riêng', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    boot('/pform?code=VHOP2&tab=csbh')

    expect(await screen.findByText(/cũng nằm trong tab Tài liệu/)).toBeInTheDocument()
  })

  it('mười tab đủ và đúng thứ tự', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    const hangTab = await screen.findByRole('tablist')
    const ten = within(hangTab)
      .getAllByRole('tab')
      .map((t) => t.textContent?.trim())
    expect(ten).toEqual([
      'Tổng quan',
      'Vị trí',
      'Ảnh 360',
      'Phân khu',
      'Mặt bằng',
      'Quỹ căn',
      'CSBH',
      'Media',
      'Tiến độ',
      'Tài liệu',
    ])
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tai-lieu-loai.test.tsx -t 'tab CSBH'`
Expected: FAIL — chín tab, không có `CSBH`.

- [ ] **Step 3: Thêm tab vào `tabDuAn.ts`**

Union đủ mười, và `TAB_DU_AN` đúng thứ tự spec §5:

```ts
export type TenTabDuAn =
  | 'tong-quan'
  | 'vi-tri'
  | 'anh-360'
  | 'phan-khu'
  | 'mat-bang'
  | 'quy-can'
  | 'csbh'
  | 'media'
  | 'tien-do'
  | 'tai-lieu'

export const TAB_DU_AN: readonly { id: TenTabDuAn; nhan: string }[] = [
  { id: 'tong-quan', nhan: 'Tổng quan' },
  { id: 'vi-tri', nhan: 'Vị trí' },
  { id: 'anh-360', nhan: 'Ảnh 360' },
  { id: 'phan-khu', nhan: 'Phân khu' },
  { id: 'mat-bang', nhan: 'Mặt bằng' },
  { id: 'quy-can', nhan: 'Quỹ căn' },
  // CSBH là LĂNG KÍNH của một loại trong tab Tài liệu, không phải kho thứ hai
  // (spec §3). Nó có hàng tab riêng vì sale mở nó nhiều lần trong ngày, còn ba
  // loại kia mở theo tuần.
  { id: 'csbh', nhan: 'CSBH' },
  { id: 'media', nhan: 'Media' },
  { id: 'tien-do', nhan: 'Tiến độ' },
  { id: 'tai-lieu', nhan: 'Tài liệu' },
]
```

Sửa câu đầu docstring file: `Năm tab của một dự án` → `Mười tab của một dự án`.

- [ ] **Step 4: Nối vào `DuAnForm.tsx`**

```tsx
      {tab === 'csbh' && code && (
        <div className="space-y-3">
          <p className="text-[13px] text-muted">
            Chính sách bán hàng của dự án. Những tài liệu này cũng nằm trong tab Tài liệu, loại
            Chính sách bán hàng — cùng một bản ghi, không phải kho riêng.
          </p>
          <TaiLieuTab projectCode={code} cao={CAO_TAB} loaiKhoa="csbh" />
        </div>
      )}
```

Sửa docstring của `DuAnForm`: `khung 5 tab` → `khung 10 tab`, và câu `BỐN TAB CON BỊ KHOÁ` → `CHÍN TAB CON BỊ KHOÁ`.

- [ ] **Step 5: Sửa lời `VI_SAO_KHOA_TAB` cho khớp số tab**

Trong `tabDuAn.ts`:

```ts
export const VI_SAO_KHOA_TAB =
  'Tạo dự án trước — mọi tab còn lại đều thuộc về một dự án đã tồn tại'
```

- [ ] **Step 6: Chạy toàn bộ**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch. `tests/realestate-uform.test.tsx` có một test liệt kê năm tên tab (dòng ~276) — nay phải là mười; sửa mảng đó cho đủ và đúng thứ tự.

- [ ] **Step 7: Commit**

```bash
git add src/features/realestate/tabDuAn.ts \
        src/features/realestate/components/DuAnForm.tsx \
        tests/realestate-tai-lieu-loai.test.tsx \
        tests/realestate-uform.test.tsx
git commit -m "feat(re): tab CSBH, đủ mười tab"
```

---

### Task 11: `TongQuanTab` chia năm section

Spec §5.1 chốt năm section cho 16 trường còn lại; sau bốn lần dời trường (Task 3–5) tab này còn ba nhóm cũ, hai trong đó đã sai tên so với nội dung. Đây là vế còn lại của mục tiêu "một tab quá dài" ở §1 — chia tab đã xong, chia section thì chưa.

Chạy được ngay sau Task 5; đặt cuối vì nó không chặn tab nào.

**Files:**
- Modify: `src/features/realestate/components/TongQuanTab.tsx`
- Test: `tests/realestate-pform.test.tsx`

**Interfaces:**
- Consumes: `NhomTruong` (đã có)
- Produces: —

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-pform.test.tsx`:

```tsx
  it('tab Tổng quan chia năm nhóm, đúng thứ tự hồ sơ giấy', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))

    for (const ten of [
      'Định danh & phân loại',
      'Chủ đầu tư',
      'Quy mô & mật độ',
      'Sở hữu & bàn giao',
      'Mô tả',
    ]) {
      expect(screen.getByRole('group', { name: ten })).toBeInTheDocument()
    }
    // Hai tên cũ phải mất hẳn — còn lại nghĩa là đã thêm nhóm mới mà không xếp lại ô.
    expect(screen.queryByRole('group', { name: 'Quy mô' })).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Định danh & vị trí' })).not.toBeInTheDocument()
  })
```

Tra bằng `role="group"`, **không** bằng `heading`: `NhomTruong` render `<section role="group" aria-labelledby>` với tiêu đề là `<h2>` ([Truong.tsx:591](../../../src/components/ui/Truong.tsx#L591)) — cùng cấp với `<h2>` tiêu đề dự án trong `DauDuAn`, nên `getAllByRole('heading', { level: 2 })` sẽ bắt lẫn cả tiêu đề đó. `role="group"` là thứ chính `NhomTruong` khai ra để làm định danh nhóm, và tên khả truy cập của nó chính là chuỗi tiêu đề.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-pform.test.tsx -t 'chia năm nhóm'`
Expected: FAIL — `Unable to find an accessible element with the role "group" and name "Chủ đầu tư"`.

- [ ] **Step 3: Chia lại năm nhóm**

Trong `TongQuanTab.tsx`, xếp lại các ô đã có vào năm `NhomTruong` — không thêm, không bớt ô nào:

1. `NhomTruong tieuDe="Định danh & phân loại"` — `projectCode` · `name` · `salePhase` · `status` · `category` (trong `CaHang`)
2. `NhomTruong tieuDe="Chủ đầu tư"` — `investor` · `developer`
3. `NhomTruong tieuDe="Quy mô & mật độ"` — `totalLandAreaM2` · `floorAreaM2` · `buildDensityPct` · `productScale` · `totalInvestmentVnd`
4. `NhomTruong tieuDe="Sở hữu & bàn giao"` — `ownershipForm` · `handoverStandard`
5. `NhomTruong tieuDe="Mô tả"` — `amenities` (trong `CaHang`) · `overview` (trong `CaHang`) · ô `Ảnh cover` (trong `CaHang`)

`investor`/`developer` tách thành nhóm riêng chứ không nằm trong nhóm số liệu — chủ đầu tư là thứ sale nói ở câu thứ hai, không phải con số tra cứu (spec §5.1).

- [ ] **Step 3b: Nối cờ `dirty` cho `TongQuanTab`** (thêm sau Task 8)

Task 8 dựng cơ chế hỏi trước khi bỏ thay đổi chưa lưu lúc nhảy tab, nhưng **cố ý** để `TongQuanTab` ngoài phạm vi vì task này sẽ viết lại chính file đó. Kết quả đo được: `TongQuanTab` là form **dài nhất** của cả màn (16 ô) và nó nằm **trong** `ChanRoiTabProvider` mà không hề gọi `setDirty` — điền nửa form rồi nhảy tab vẫn mất trắng, im lặng. Cơ chế Task 8 hiện không che đúng chỗ dễ mất nhất.

Theo đúng khuôn `ViTriTab` (đọc nó trước):

```tsx
import { useChanRoiTab } from './useChanRoiTab'
```

```tsx
  const { setDirty } = useChanRoiTab()
```

Mọi chỗ đổi giá trị đặt cờ, mọi chỗ kết thúc xoá cờ:

- một helper đặt `setV(next)` **và** `setDirty(true)`, dùng ở mọi `doi={…}`/`onChange` thay cho `setV` trực tiếp
- `setDirty(false)` trong `onSuccess` của mutation **và** trong nhánh Huỷ

⚠️ **Ba đường xoá cờ phải có test canh** — đây là chỗ Task 8 sập hai vòng review. Thêm ba test vào `describe('nhảy tab khi đang sửa')` ở `tests/realestate-tab-chuyen-de.test.tsx`, bản sao đúng khuôn ba test đã có cho `ViTriTab` ở đó (PATCH 200 → nhảy tab → `queryByRole('alertdialog')` rỗng; bấm Huỷ → rỗng; PATCH 422 qua helper `loi422()` → `findByRole('alertdialog')` **có**).

**Nghiệm thu bắt buộc:** tạm xoá từng `setDirty(false)`, chạy `npm test`, xác nhận **có test đỏ** cho từng cái, rồi trả lại. Tháo được mà suite vẫn xanh nghĩa là test luôn-xanh — đã xảy ra ba lần trên nhánh này.

Chế độ tạo mới (`duAn` null, nút «Tạo dự án») cũng đi qua cùng form: kiểm rằng cờ không làm hộp xác nhận hiện lúc `code` chưa có — lúc đó sáu tab kia đang khoá nên không có tab nào nhảy sang, nhưng đừng để cờ mắc lại sau khi `daTao()` đổi search param.

- [ ] **Step 4: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 5: Commit**

```bash
git add src/features/realestate/components/TongQuanTab.tsx tests/realestate-pform.test.tsx \
        tests/realestate-tab-chuyen-de.test.tsx
git commit -m "refactor(re): tab Tổng quan chia năm section"
```

---

## Sau khi xong

Bộ mười tab đủ. Ba điều spec ghi mà plan này **không** làm:

- **Không có tab Tin tức** — chưa có bảng nào ở backend (spec §2).
- **Không có tab Video** — `media` phân biệt bằng hai trục nên một tab Video cắt ngang `category` sẽ làm video tiến độ xuất hiện ở hai chỗ (spec §5.1). `TienDoTab` mang docstring giải thích.
- **Overlap giữa các tab chưa có test đo trực tiếp** — spec §7 đã ghi. Việc "xoá ảnh ở tab Vị trí thì tab Media cũng mất" chỉ được đảm bảo bởi việc năm tab dùng chung query key `['re', code, 'media']`; một người refactor sau có thể tách key mà mọi test vẫn xanh. Nếu muốn bịt, thêm một test dựng hai tab liên tiếp và assert số đếm của tab Media giảm sau khi xoá ở tab Vị trí.
