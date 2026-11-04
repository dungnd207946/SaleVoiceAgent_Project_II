# Vòng 2 — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Màn dự án `/pform` từ mười tab thành chín, tab Media thành folder hai mức không giới hạn ảnh, ô Trạng thái biến mất và `status` thành giá trị suy ra, bảng có phân trang số trang, tài liệu có badge màu, quỹ căn có cột Hướng.

**Architecture:** `TAB_DU_AN` vẫn là nguồn duy nhất của hàng tab. `status` thôi là một ô người dùng chọn và thành giá trị **tính từ `completeness.ts`** ngay trước khi gửi — nhãn "còn thiếu" đã có nay là thứ duy nhất cho người dùng biết agent chưa đọc bản ghi. Phân trang tách thành hook thứ hai (`useTrangSo`) đứng cạnh `useTrangCuon`, không thay thế nó: bảng đi bằng số trang, media đi bằng nạp-một-lần-rồi-lọc.

**Tech Stack:** React 18 · TanStack Router (search param) · TanStack Query · Tailwind · vitest + @testing-library/react + MSW

## Global Constraints

- **Bộ tab chín, đúng thứ tự:** `tong-quan` · `vi-tri` · `anh-360` · `mat-bang` · `phan-khu` · `quy-can` · `tien-do` · `media` · `tai-lieu`.
- **Không thêm file route** — `tests/nav-registry.test.ts` khoá `src/routes/_app`; tab đi bằng search param `?tab=`.
- **`src/features/realestate/completeness.ts` KHÔNG được sửa.** Nó chép nguyên văn luật của `completeness.py`; sửa nó là làm FE nghiêm hơn backend, đúng cái header của nó cấm. Task 2 chỉ **đọc** nó.
- **Không đổi lược đồ, không bỏ `nextCursor`** khỏi kiểu `Trang<T>`.
- **Comment thưa** — chỉ giải thích *vì sao*, không mô tả *cái gì*. Codebase hiện có comment rất dày; đừng nối theo mật độ đó.
- Repo này đặt tên component/hook/helper bằng **tiếng Việt** (`DuAnForm`, `useTrangCuon`, `NhomTruong`, `nhanCua`, `locLoai`) — theo đúng nếp đó, đừng dịch sang tiếng Anh. Tên `it(...)`/`describe(...)` viết tiếng Việt.
- **Không thêm màu thô vào component** — thêm token vào `src/styles/theme.css` rồi dùng qua class.
- **`npm run typecheck` NAY DÙNG ĐƯỢC** và là một cổng, cùng `npm test` và `npm run lint`. (Trước 2026-08-10 script này là `tsc -b --noEmit false --emitDeclarationOnly false` — nó **bắt buộc emit** nên vừa đỏ TS5055 vừa rải 196 file `.js`/`.d.ts` khắp `src/`, và ràng buộc «đừng chạy typecheck» của vòng 1 thực chất đang che một script hỏng. Đã vá thành `tsc --noEmit`, chạy sạch exit 0.) Nếu bạn thấy nó rải file thì **dừng lại và báo** — nghĩa là script bị đổi lại.
- **6 test `it.skip`** ở `tests/realestate-media.test.tsx` (dòng 76, 102, 185, 254, 292, 326) là chủ ý từ 2026-08-04 (jsdom không gắn file vào input được) — **đừng bật lại**.
- Commit: message **một dòng ngắn (≤60 ký tự)**, **KHÔNG** trailer `Co-Authored-By: Claude`. Không `git push`.
- **Mốc trước plan này:** 31 file / 425 passed / 6 skipped / 0 failed, lint sạch.
- **Bài học đã trả giá 5 lần trên vòng 1:** mã đúng mà tháo cơ chế ra thì toàn suite vẫn xanh. Mỗi task có bước **nghiệm thu tháo-bản-vá**; nếu suite không đỏ thì test đó là test luôn-xanh và phải viết lại.
- **Bài học đã trả giá 4 lần:** dời/đổi trường ở `TongQuanTab` mà quên `TomTatDuAn.tsx` (chế độ XEM). `GiaTri` render giá trị rỗng thành chữ **«Chưa đặt»**, nên màn *khẳng định một điều sai*. Cổng canh so tập nhãn ô hai chế độ đã có ở `tests/realestate-pform.test.tsx` — **đừng nới allowlist của nó để cho qua**.

**Spec:** [odyssey-portal-backend/docs/superpowers/specs/2026-08-10-man-du-an-vong-2-design.md](../../../../odyssey-portal-backend/docs/superpowers/specs/2026-08-10-man-du-an-vong-2-design.md)

**Backend phải xong trước Task 7–8:** plan `2026-08-10-vong-2-backend.md` Task 1 (bỏ trần) và Task 2–3 (`offset`/`total`).

## Cấu trúc file

| File | Trách nhiệm sau plan này |
|---|---|
`tabDuAn.ts` | 9 tab, `TAB_CU` thêm `csbh` |
`components/MediaTab.tsx` | folder hai mức, 4 danh mục |
`components/VungMedia.tsx` | một vùng ảnh, không trần |
`components/MatBangTab.tsx` | chỉ một `VungMedia`, không state |
`components/TongQuanTab.tsx` | 3 nhóm, `status` suy ra, không ô Trạng thái |
`components/TomTatDuAn.tsx` | 3 nhóm khớp chế độ sửa |
`components/TaiLieuTab.tsx` | badge màu, phân trang, không `loaiKhoa`, không Trạng thái |
`components/CanTab.tsx` · `PhanKhuTab.tsx` · `DuAnList.tsx` | phân trang, không Trạng thái |
`components/CanForm.tsx` | `status` suy ra, không trần ảnh |
`components/useTrangSo.ts` | **mới** — hook phân trang có số |
`components/ThanhTrang.tsx` | **mới** — thanh `‹ 1 2 3 › ` + chọn số hàng |
`trangThai.ts` | **mới** — hàm suy `status` từ completeness |
`enums.ts` | bỏ `TRAN_ANH`, thêm `MAU_LOAI_TAI_LIEU` |
`api.ts` | `Trang<T>` thêm `total`; hàm danh sách nhận `limit`/`offset` |
`styles/theme.css` | 3 cặp token badge loại tài liệu |

---

### Task 1: Bộ tab chín — bỏ tab CSBH, đổi thứ tự

**Files:**
- Modify: `src/features/realestate/tabDuAn.ts`
- Modify: `src/features/realestate/components/DuAnForm.tsx` (bỏ nhánh `csbh`)
- Modify: `src/features/realestate/components/TaiLieuTab.tsx` (bỏ prop `loaiKhoa` và mọi thứ chỉ nó dùng)
- Test: `tests/realestate-tai-lieu-loai.test.tsx`, `tests/tab-du-an.test.ts`, `tests/realestate-uform.test.tsx`

**Interfaces:**
- Consumes: —
- Produces: `TenTabDuAn` gồm đúng 9 id; `TAB_DU_AN` đúng thứ tự trên; `TaiLieuTab({ projectCode, cao }: { projectCode: string; cao?: string | undefined })` — **không còn** `loaiKhoa`.

- [ ] **Step 1: Viết test đỏ**

Trong `tests/realestate-tai-lieu-loai.test.tsx`, **thay** `describe('tab CSBH', …)` bằng:

```tsx
describe('bộ tab chín', () => {
  it('chín tab, đúng thứ tự, không còn CSBH', async () => {
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
      'Mặt bằng',
      'Phân khu',
      'Quỹ căn',
      'Tiến độ',
      'Media',
      'Tài liệu',
    ])
  })

  it('link cũ ?tab=csbh mở tab Tài liệu, không rơi về Tổng quan', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    boot('/pform?code=VHOP2&tab=csbh')

    expect(await screen.findByRole('tab', { name: 'Tài liệu' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    // Và nó hiện TOÀN BỘ tài liệu, không lọc sẵn theo csbh: tab CSBH đã bỏ,
    // nên không còn khái niệm "mở sẵn ở một loại".
    expect(await screen.findByRole('group', { name: 'Lọc theo loại' })).toBeInTheDocument()
  })
})
```

Trong `tests/tab-du-an.test.ts`, thêm vào `describe('tabHopLe')`:

```ts
  it('id csbh đã bỏ vẫn ánh xạ sang tai-lieu', () => {
    expect(tabHopLe('csbh')).toBe('tai-lieu')
  })
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/tab-du-an.test.ts tests/realestate-tai-lieu-loai.test.tsx`
Expected: FAIL — mảng tên tab còn 10 phần tử và có `'CSBH'`; `tabHopLe('csbh')` trả `'csbh'`.

- [ ] **Step 3: Sửa `tabDuAn.ts`**

```ts
export type TenTabDuAn =
  | 'tong-quan'
  | 'vi-tri'
  | 'anh-360'
  | 'mat-bang'
  | 'phan-khu'
  | 'quy-can'
  | 'tien-do'
  | 'media'
  | 'tai-lieu'

export const TAB_DU_AN: readonly { id: TenTabDuAn; nhan: string }[] = [
  { id: 'tong-quan', nhan: 'Tổng quan' },
  { id: 'vi-tri', nhan: 'Vị trí' },
  { id: 'anh-360', nhan: 'Ảnh 360' },
  // MẶT BẰNG ĐỨNG TRƯỚC PHÂN KHU: người mở mặt bằng là để chọn phân khu, nên
  // đọc mặt bằng rồi mới vào phân khu, không phải ngược lại.
  { id: 'mat-bang', nhan: 'Mặt bằng' },
  { id: 'phan-khu', nhan: 'Phân khu' },
  { id: 'quy-can', nhan: 'Quỹ căn' },
  { id: 'tien-do', nhan: 'Tiến độ' },
  // MEDIA ĐỨNG SAU TIẾN ĐỘ: nó là kho tổng của bốn danh mục còn lại, thứ mở sau
  // cùng — ba danh mục có tab riêng đã rời khỏi nó (spec vòng 2 §3).
  { id: 'media', nhan: 'Media' },
  // «Tài liệu» TRẦN, cố ý — không phải «Tài liệu gửi khách». Cái phân biệt tab
  // này với tab ở `/projects` là PHẠM VI, và ở đây phạm vi đã do ngữ cảnh nói.
  { id: 'tai-lieu', nhan: 'Tài liệu' },
]

/** Id cũ → id mới. Link đã gửi cho đồng nghiệp và bookmark vẫn phải mở đúng tab. */
const TAB_CU: Record<string, TenTabDuAn> = {
  'thong-tin': 'tong-quan',
  can: 'quy-can',
  // Tab CSBH bỏ ở vòng 2: nó chỉ là một loại trong tab Tài liệu, không phải kho
  // thứ hai. Link cũ mở tab Tài liệu (không lọc sẵn — bộ lọc là việc người dùng).
  csbh: 'tai-lieu',
}
```

Sửa câu đầu docstring: `Mười tab của một dự án` → `Chín tab của một dự án`.

- [ ] **Step 4: Bỏ nhánh `csbh` khỏi `DuAnForm.tsx`**

Xoá cả khối:

```tsx
      {tab === 'csbh' && code && (
        <div className="space-y-3">
          <p className="text-[13px] text-muted">…</p>
          <TaiLieuTab projectCode={code} cao={CAO_TAB} loaiKhoa="csbh" />
        </div>
      )}
```

Và ở nhánh `tai-lieu`, bỏ prop `loaiKhoa` nếu có. Sửa docstring của `DuAnForm`: `khung 10 tab` → `khung 9 tab`, và `CHÍN TAB CON BỊ KHOÁ` → `TÁM TAB CON BỊ KHOÁ` (chín tab, trừ `tong-quan`).

- [ ] **Step 5: Bỏ prop `loaiKhoa` khỏi `TaiLieuTab.tsx`**

Sau Step 4 không consumer nào truyền `loaiKhoa`. Giữ một prop không ai truyền là YAGNI, và **ba cổng canh của nó thành ba test canh code chết**. Bỏ:

- prop `loaiKhoa` khỏi `interface Props` và khỏi destructure
- `locHieuLuc` — mọi chỗ đọc nó đổi về `locLoai`
- nhánh câu rỗng theo `loaiKhoa` (câu «Chưa có tài liệu … nào — bấm Thêm tài liệu để nạp»)
- điều kiện `!loaiKhoa &&` quanh thanh lọc và quanh dòng cảnh báo «Số đếm chỉ tính phần đã tải» — thanh lọc nay **luôn** hiện khi có dữ liệu
- `loai: loaiKhoa ?? MOI.loai` ở nút «Thêm tài liệu» → về `{ ...MOI }`
- `goiY="Tab CSBH chỉ hiện tài liệu thuộc loại Chính sách bán hàng"` ở ô Loại → đổi thành câu không nhắc tab đã bỏ, ví dụ `goiY="Loại quyết định tài liệu nằm ở nhóm nào khi lọc"`

Rồi **bỏ các test chỉ canh `loaiKhoa`** trong `tests/realestate-tai-lieu-loai.test.tsx`: bài `loaiKhoa khoá bộ lọc`, bài `rerender cùng instance với loaiKhoa khác`, và bài câu rỗng khi `loaiKhoa`. Chúng canh một prop không còn tồn tại.

⚠️ **Đừng bỏ** ba test khác trong file đó (cột Loại, thanh lọc, form gửi `loai`) — chúng vẫn đúng.

- [ ] **Step 6: Sửa các chỗ đếm/liệt kê tên tab**

```bash
grep -rn "csbh\|CSBH" src/ tests/ | grep -v node_modules
grep -rn "mười tab\|10 tab\|chín tab" src/ tests/
```

Sửa mọi chỗ còn nói mười tab hoặc liệt kê `CSBH`. `tests/realestate-uform.test.tsx` có một test liệt kê tên tab — sửa mảng cho đủ chín, đúng thứ tự.

- [ ] **Step 7: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS, lint sạch.

- [ ] **Step 8: Nghiệm thu — tháo bản vá**

```bash
# (a) bỏ dòng `csbh: 'tai-lieu'` khỏi TAB_CU → test `link cũ ?tab=csbh` phải ĐỎ
# (b) đổi chỗ 'mat-bang' và 'phan-khu' trong TAB_DU_AN → test `chín tab, đúng
#     thứ tự` phải ĐỎ
```

`git checkout -- <file>` sau mỗi lần. Dán output thật.

- [ ] **Step 9: Commit**

```bash
git add src/features/realestate/tabDuAn.ts \
        src/features/realestate/components/DuAnForm.tsx \
        src/features/realestate/components/TaiLieuTab.tsx \
        tests/
git commit -m "feat(re): bộ tab chín, bỏ tab CSBH"
```

---

### Task 2: `status` thành giá trị suy ra — hàm suy + hai form

`status` là công tắc quyết định agent có đọc bản ghi hay không (`agent_api.projects` lọc `WHERE status='published'`). Task này bỏ ô chọn và thay bằng phép suy; Task 3 dọn các chỗ chỉ *hiển thị* nó.

**Files:**
- Create: `src/features/realestate/trangThai.ts`
- Modify: `src/features/realestate/components/TongQuanTab.tsx`
- Modify: `src/features/realestate/components/CanForm.tsx`
- Test: `tests/realestate-trang-thai-suy-ra.test.tsx` (**mới**)

**Interfaces:**
- Consumes: `thieuTruongDuAn`, `thieuTruongCan` từ `completeness.ts` (**không sửa file đó**)
- Produces:
  - `trangThaiDuAn(d: Parameters<typeof thieuTruongDuAn>[0]): TrangThai`
  - `trangThaiCan(c: Parameters<typeof thieuTruongCan>[0]): TrangThai`

⚠️ **Không** thêm hằng cho ba entity `zones`/`documents`/`media`. Chúng không có luật completeness nên luôn `'published'`, và `VungMedia.tsx:40` cùng `CanForm.tsx:511` **đã** hardcode đúng như vậy từ trước — một hằng mới chỉ để viết `status: TRANG_THAI_LUON_PHAT_HANH` thay cho `status: 'published'` là một tầng gián tiếp không mua gì.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/realestate-trang-thai-suy-ra.test.tsx`:

```tsx
/**
 * `status` là giá trị SUY RA, không phải ô người dùng chọn (spec vòng 2 §4.4).
 *
 * Vì sao canh ở tầng HTTP chứ không unit-test hàm suy: cái sai đắt nhất không
 * phải phép suy tính lệch, mà là form GỬI THIẾU `status` — lúc đó DB dùng
 * DEFAULT 'draft' và agent im lặng không đọc dự án nào. Chỉ thân request nói
 * được điều đó.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, boot, datApiDoc, moSuaDuAn } from './re-fixture'

function batThanPatch() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(DU_AN)
    }),
  )
  return than
}

describe('status suy ra ở form dự án', () => {
  it('đủ ba trường bắt buộc thì gửi published', async () => {
    datApiDoc()
    const than = batThanPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.status).toBe('published')
  })

  it('thiếu Tổng quan thì gửi draft — KHÔNG bỏ trống status', async () => {
    datApiDoc()
    const than = batThanPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.clear(screen.getByRole('textbox', { name: /Tổng quan/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))

    await waitFor(() => expect(than).toHaveLength(1))
    // 'draft', không phải undefined: gửi thiếu `status` thì DB dùng DEFAULT
    // 'draft' — cùng kết quả nhưng do tình cờ, và một lần backend đổi default là
    // một lần dữ liệu đi sai chỗ mà không ai thấy.
    expect(than[0]!.status).toBe('draft')
  })

  it('không còn ô Trạng thái nào để chọn', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    expect(screen.queryByRole('combobox', { name: /Trạng thái hiển thị/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Đã phát hành')).not.toBeInTheDocument()
    expect(screen.queryByText('Bản nháp')).not.toBeInTheDocument()
  })

  it('nhãn còn-thiếu nói agent chưa đọc, không nói không phát hành được', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.clear(screen.getByRole('textbox', { name: /Tổng quan/ }))

    expect(await screen.findByText(/agent chưa đọc/i)).toBeInTheDocument()
    expect(screen.queryByText(/không phát hành được/i)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-trang-thai-suy-ra.test.tsx`
Expected: FAIL — ô Trạng thái vẫn còn; `than[0].status` là giá trị người dùng chọn (`'published'` từ fixture) nên bài `draft` đỏ.

- [ ] **Step 3: Tạo `src/features/realestate/trangThai.ts`**

```ts
/**
 * `status` là giá trị SUY RA từ completeness, không phải ô người dùng chọn
 * (spec vòng 2 §4.4).
 *
 * VÌ SAO SUY RA CHỨ KHÔNG CỨNG `'published'`: cổng `_chan_tao_moi_thieu` của
 * backend từ chối 422 khi một bản ghi THÀNH `published` mà thiếu trường bắt
 * buộc, nên gửi cứng `published` làm lần Lưu đầu của một dự án mới luôn bị
 * chặn — không tạo được dự án nữa.
 *
 * VÌ SAO KHÔNG BỎ TRỐNG: gửi thiếu `status` thì DB dùng `DEFAULT 'draft'` —
 * cùng kết quả cho bản ghi thiếu, nhưng do tình cờ, và bản ghi ĐỦ trường cũng
 * thành `draft`, tức agent không đọc dự án nào.
 *
 * `archived` KHÔNG còn đường tạo từ UI sau vòng 2 (spec §4.4). Bản ghi đang
 * `archived` giữ nguyên trong DB; hàm này không bao giờ sinh ra nó.
 */
import { thieuTruongCan, thieuTruongDuAn } from './completeness'
import type { TrangThai } from './api'

export function trangThaiDuAn(d: Parameters<typeof thieuTruongDuAn>[0]): TrangThai {
  return thieuTruongDuAn(d).length === 0 ? 'published' : 'draft'
}

export function trangThaiCan(c: Parameters<typeof thieuTruongCan>[0]): TrangThai {
  return thieuTruongCan(c).length === 0 ? 'published' : 'draft'
}
```

- [ ] **Step 4: Sửa `TongQuanTab.tsx`**

Ba việc:

1. **Bỏ ô Trạng thái** — xoá khối `<OChon ... muc={TRANG_THAI} ... />` (quanh dòng 184) và bỏ `TRANG_THAI` khỏi dòng import từ `'../enums'`.

2. **Gửi `status` suy ra.** Trong thân mutation, ngay trước khi gọi `suaDuAn`/`taoDuAn`, đặt `status`:

```tsx
import { trangThaiDuAn } from '../trangThai'
```

```tsx
  // `status` suy từ completeness, không phải ô người dùng chọn — xem `trangThai.ts`.
  // Tính trên `v` (state form) chứ không trên `duAn` (bản server): người dùng vừa
  // gõ xong `overview` thì lần Lưu này phải là lần chuyển sang `published`.
  const thanGui = { ...v, status: trangThaiDuAn({ ...v, region: duAn?.region ?? '' }) }
```

⚠️ `region` **đã dời sang tab Vị trí** (vòng 1 Task 3) nên không có trong `v` — phải lấy từ `duAn`, đúng cách `thieuTruongDuAn` đang được gọi ở chỗ tính nhãn. Bỏ phần `region:` đi làm mọi dự án thành `draft` vĩnh viễn.

3. **Đổi câu nhãn còn-thiếu.** Câu hiện tại nói về phát hành; nay nó là thứ duy nhất cho người dùng biết agent chưa đọc:

```tsx
        <DongTrangThai mau="warn">
          Agent chưa đọc dữ liệu này — còn thiếu {nhanThieu(thieu)}.
        </DongTrangThai>
```

- [ ] **Step 5: Sửa `CanForm.tsx`**

Cùng ba việc, cho căn:

- bỏ ô Trạng thái và `TRANG_THAI` khỏi import
- `status: trangThaiCan(gia_tri)` trong thân gửi
- `chanPublish` (dòng ~168) và ba câu quanh nó (~421, 429, 433, 437) viết lại: bỏ khái niệm "không phát hành được" (người dùng không còn chọn phát hành), giữ **một** câu nói agent chưa đọc khi còn thiếu và **một** câu xác nhận khi đủ. Bỏ luôn `status: 'published'` cứng ở dòng ~511 nếu nó thuộc đường lưu căn (giữ nếu nó thuộc đường tạo **media** của căn — media luôn `published`).

⚠️ Đọc cả bốn chỗ trước khi sửa; có chỗ nói về `saleStatus` (trạng thái **bán**) chứ không phải `status` (trạng thái **hiển thị**) — `saleStatus` **giữ nguyên**, nó là dữ liệu nghiệp vụ thật.

- [ ] **Step 6: Chạy test**

Run: `npx vitest run tests/realestate-trang-thai-suy-ra.test.tsx && npm test && npm run lint`
Expected: PASS. Một số test cũ sẽ đỏ vì chúng chọn ô Trạng thái hoặc assert nó — sửa chúng (bỏ bước chọn ô), **đừng** đưa ô về.

- [ ] **Step 7: Nghiệm thu — tháo bản vá**

```bash
# (a) đổi `trangThaiDuAn(...)` thành cứng `'published'`
#     → bài `thiếu Tổng quan thì gửi draft` phải ĐỎ
# (b) bỏ hẳn `status` khỏi thân gửi
#     → bài `đủ ba trường thì gửi published` phải ĐỎ (undefined ≠ 'published')
# (c) bỏ phần `region: duAn?.region ?? ''` khỏi lời gọi
#     → bài `đủ ba trường thì gửi published` phải ĐỎ (thành 'draft')
```

`git checkout --` sau mỗi lần. Dán output thật cả ba. Mục (c) là cổng canh cho đúng cái bẫy `region` đã dời tab.

- [ ] **Step 8: Commit**

```bash
git add src/features/realestate/trangThai.ts \
        src/features/realestate/components/TongQuanTab.tsx \
        src/features/realestate/components/CanForm.tsx \
        tests/
git commit -m "feat(re): status suy ra từ completeness, bỏ ô chọn"
```

---

### Task 3: Dọn mọi chỗ còn *hiển thị* trạng thái

**Files:**
- Modify: `components/TomTatDuAn.tsx`, `TomTatCan.tsx`, `TaiLieuTab.tsx`, `CanTab.tsx`, `PhanKhuTab.tsx`, `DuAnList.tsx`
- Modify: `src/features/realestate/enums.ts`
- Test: `tests/realestate-trang-thai-suy-ra.test.tsx`, `tests/realestate-list.test.tsx`

**Interfaces:**
- Consumes: `trangThai.ts` (Task 2)
- Produces: `TRANG_THAI` **không** còn được import bởi component nào.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-trang-thai-suy-ra.test.tsx`:

```tsx
describe('không màn nào còn hiện trạng thái hiển thị', () => {
  it('bảng danh sách dự án không có cột lẫn ô lọc trạng thái', async () => {
    datApiDoc()
    boot('/projects')

    await screen.findByText('Vinhomes Ocean Park 2')
    expect(screen.queryByRole('columnheader', { name: 'Trạng thái' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /Trạng thái/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Đã phát hành')).not.toBeInTheDocument()
  })

  it('chế độ xem dự án không nhắc trạng thái', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await screen.findByText('Vinhomes Ocean Park 2')
    expect(screen.queryByText('Đã phát hành')).not.toBeInTheDocument()
  })

  it('bảng tài liệu không còn cột Trạng thái', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')

    await screen.findByText(TAI_LIEU.title)
    expect(screen.queryByRole('columnheader', { name: 'Trạng thái' })).not.toBeInTheDocument()
  })
})
```

Thêm import `TAI_LIEU`, `trang` từ `./re-fixture` nếu chưa có.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-trang-thai-suy-ra.test.tsx -t "không màn nào"`
Expected: FAIL cả ba.

- [ ] **Step 3: Dọn từng file**

| File | Bỏ gì |
|---|---|
`TomTatDuAn.tsx:48` | dòng `<DongXem nhan="Trạng thái">` |
`TomTatCan.tsx:67` | dòng xem trạng thái |
`TaiLieuTab.tsx:173` | dòng xem trạng thái |
`TaiLieuTab.tsx:355` | badge trạng thái trong hàng bảng, và mục `{ nhan: 'Trạng thái' }` khỏi `COT` |
`CanTab.tsx:222` | badge trong hàng, và mục `{ nhan: 'Trạng thái' }` khỏi `COT` |
`PhanKhuTab.tsx:384` | badge trong hàng, và mục tương ứng khỏi `COT` nếu có |
`DuAnList.tsx:146` | ô lọc theo trạng thái |
`DuAnList.tsx:220` | badge trong hàng, và mục khỏi `COT` |
`DuAnList.tsx:286-291` | hàm màu badge trạng thái (không còn ai gọi) |

⚠️ **Bỏ một mục khỏi `COT` mà quên bỏ `<td>` tương ứng (hoặc ngược lại) làm mọi cột sau nó lệch nhãn** mà không test nào đỏ — vòng 1 đã đo được đúng chuyện này. Với **mỗi** bảng: đếm số mục `COT` và số `<td>` trong một hàng, hai số phải bằng nhau.

⚠️ **`PhanKhuTab` và `TaiLieuTab` có Ô CHỌN `status`, không chỉ badge hiển thị.** Bỏ ô mà không gửi gì thay thế ⇒ phân khu/tài liệu mới vào DB với `DEFAULT 'draft'` ⇒ **agent không đọc chúng**, im lặng. Hai entity này **không có** luật completeness (`02a §7` không định nghĩa cho `zones`/`documents`), nên chúng **luôn** `'published'`:

```tsx
// `zones`/`documents` không có luật completeness nên không bao giờ thiếu gì —
// luôn published. Bỏ ô chọn mà không gửi gì thì DB dùng DEFAULT 'draft' và agent
// thôi đọc chúng, không một dấu hiệu nào.
status: 'published',
```

Đặt trong thân gửi của **cả hai** form (tạo mới và sửa). Cùng nếp `VungMedia.tsx:40` đã làm cho media từ trước.

**Kèm test thân request cho mỗi entity:** tạo một phân khu → assert thân POST có `status: 'published'`; cùng vậy cho tài liệu. **Nghiệm thu:** bỏ dòng `status` → test phải đỏ.

Rồi ở `enums.ts`: `TRANG_THAI` không còn component nào dùng. **Giữ** nó (kiểu `TrangThai` ở `api.ts` vẫn cần, và `nhanCua(TRANG_THAI, …)` có thể còn dùng ở module khác) nhưng kiểm:

```bash
grep -rn "TRANG_THAI" src/ | grep -v "enums.ts" | grep -v NHAN_TRANG_THAI | grep -v MAU_TRANG_THAI
```

Không còn hit trong `features/realestate` ⇒ xong. Còn hit ở `features/kb` hay `features/platform` ⇒ **đừng đụng**, chúng là `status` của entity khác.

- [ ] **Step 3b: Rút `status` khỏi state form và đóng ngoại lệ tạm của cổng XEM↔SỬA**

Task 2 phải để lại ba thứ tạm vì chế độ XEM còn đọc `status`; giờ chế độ XEM đã sạch nên đóng cả ba:

1. **Rút `status` khỏi state form.** `TongQuanTab.tsx`: bỏ `status: 'draft'` khỏi `DU_AN_MOI` và bỏ `status: d.status` khỏi `tuDuAn()`. `CanForm.tsx`: bỏ khỏi `MOI` và `tuCan()`. (`DuAnGhi.status`/`CanGhi.status` là optional nên kiểu vẫn hợp lệ.) Sau đó phép suy là đường **duy nhất** đặt `status` — không còn giá trị server đọng trong state để lọt qua spread.

2. **Bỏ `delete thanGui.status` ở cả hai form**, về một câu:

```tsx
const thanGui = { ...v, status: trangThaiDuAn({ ...v, region: duAn?.region ?? '' }) }
```

Và **bỏ khối comment giải thích cái `delete`** — nó nói một lý do sai (cổng canh chưa bao giờ hở; nguyên nhân là fixture của một bài test dùng dự án mà `status` vốn đã bằng đáp án mong đợi).

3. **Đóng ngoại lệ `CHI_O_XEM`** trong cổng canh XEM↔SỬA ở `tests/realestate-pform.test.tsx`: xoá `CHI_O_XEM` và phép `filter` dùng nó, đổi `expect(nhanXem.size).toBe(16)` thành `15`.

⚠️ Sau khi rút `status` khỏi `tuDuAn`, chạy lại bài test bắt thân request của Task 2 (`tests/realestate-trang-thai-suy-ra.test.tsx`): nếu một bài xanh **chỉ vì** dự án fixture vốn đã có `status` bằng đáp án, nó nay sẽ lộ ra. Sửa fixture của bài đó thành `datApiDoc({ project: { ...DU_AN, status: 'draft' } })` (vẫn đủ ba trường) để giá trị đi lọt khác đáp án.

- [ ] **Step 4: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS. Test cũ assert badge trạng thái sẽ đỏ — sửa chúng, đừng đưa badge về.

- [ ] **Step 5: Nghiệm thu — đếm cột**

Với mỗi bảng đã sửa (`TaiLieuTab`, `CanTab`, `PhanKhuTab`, `DuAnList`), thêm một assertion đếm cột vào test tương ứng:

```tsx
    // Số `<th>` phải bằng số `<td>` một hàng — bỏ một mục COT mà quên `<td>`
    // (hoặc ngược lại) làm mọi cột sau nó lệch nhãn, im lặng.
    const soTh = screen.getAllByRole('columnheader').length
    const soTd = screen.getAllByRole('row')[1]!.querySelectorAll('td').length
    expect(soTd).toBe(soTh)
```

Nghiệm thu: bỏ tạm một mục khỏi `COT` của một bảng → assertion đó phải **đỏ**. `git checkout --`.

- [ ] **Step 6: Commit**

```bash
git add src/features/realestate/ tests/
git commit -m "feat(re): bỏ mọi chỗ hiện trạng thái hiển thị"
```

---

### Task 4: Tab Mặt bằng — một vùng ảnh duy nhất

**Files:**
- Modify: `src/features/realestate/components/MatBangTab.tsx`
- Modify: `src/features/realestate/components/DuAnForm.tsx` (bỏ `key`, bỏ prop nếu đổi)
- Test: `tests/realestate-tab-chuyen-de.test.tsx`

**Interfaces:**
- Consumes: `VungMedia`
- Produces: `MatBangTab({ projectCode }: { projectCode: string })` — **không** còn nhận `duAn`, không giữ state, không tham gia cờ `dirty`.

- [ ] **Step 1: Viết test đỏ**

Trong `tests/realestate-tab-chuyen-de.test.tsx`, `describe('tab Mặt bằng', …)`:

```tsx
  it('chỉ một vùng ảnh, không còn ô ảnh mặt bằng tổng', async () => {
    datApiDoc({ media: trang([{ ...MEDIA, id: 95, category: 'mat_bang', caption: 'MB dự án' }]) })
    boot('/pform?code=VHOP2&tab=mat-bang')

    expect(await screen.findByRole('heading', { name: 'Mặt bằng', level: 3 })).toBeInTheDocument()
    expect(screen.queryByText('Ảnh mặt bằng tổng')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Lưu mặt bằng tổng/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Mặt bằng tổng thể' })).not.toBeInTheDocument()
  })

  it('nhảy tab từ Mặt bằng không hỏi gì — tab này không giữ gì chưa lưu', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=mat-bang')

    await screen.findByRole('heading', { name: 'Mặt bằng', level: 3 })
    await userEvent.click(screen.getByRole('tab', { name: 'Phân khu' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-tab-chuyen-de.test.tsx -t 'Mặt bằng'`
Expected: FAIL — ô «Ảnh mặt bằng tổng» và nút Lưu vẫn còn.

- [ ] **Step 3: Viết lại `MatBangTab.tsx`**

```tsx
/**
 * Tab Mặt bằng — một vùng ảnh `mat_bang` của dự án.
 *
 * MỘT VÙNG, KHÔNG PHẢI HAI (spec vòng 2 §4.5): «mặt bằng» và «mặt bằng tổng
 * thể» là cùng một thứ, nên `projects.map_media_id` thôi được ghi và agent trả
 * cả bộ ảnh — hợp đồng `docs/contracts/mat-bang-agent.md` của repo backend.
 *
 * Mặt bằng của PHÂN KHU nằm trong form phân khu, không ở đây (lọc `zoneCode`/
 * `unitCode` rỗng) — cùng luật với các tab media khác.
 */
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, type Media } from '../api'
import { LoiTai } from './TrangCuon'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'

export function MatBangTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  if (media.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (media.error) return <LoiTai viec="ảnh mặt bằng" thuLai={() => void media.refetch()} />

  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted">
        Mặt bằng của dự án. Mặt bằng của phân khu nằm trong form phân khu.
      </p>
      <VungMedia
        projectCode={projectCode}
        category="mat_bang"
        nhan="Mặt bằng"
        anh={media.items.filter((m) => !m.zoneCode && !m.unitCode && m.category === 'mat_bang')}
        lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })}
      />
    </div>
  )
}
```

- [ ] **Step 4: Sửa nhánh render ở `DuAnForm.tsx`**

```tsx
      {tab === 'mat-bang' && code && <MatBangTab projectCode={code} />}
```

Bỏ `key={duAn.projectCode}` **và** điều kiện `&& duAn`: component nay không giữ state nào dẫn xuất từ `duAn`, nên không có gì để reset.

- [ ] **Step 5: Bỏ các cổng canh của cơ chế đã biến mất**

Trong `tests/realestate-tab-chuyen-de.test.tsx` bỏ:
- test `key` của `MatBangTab` (dán ảnh cho dự án A → navigate sang B → assert ảnh mất)
- ba test cờ `dirty` của `MatBangTab` (lưu thành công / bỏ ảnh / hộp xác nhận)

Chúng canh một cơ chế **không còn tồn tại**. Giữ lại là giữ ba test canh code chết.

⚠️ **Đừng** bỏ test `key`/`dirty` của `ViTriTab` và `Anh360Tab` — hai tab đó vẫn giữ state.

- [ ] **Step 6: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS.

- [ ] **Step 7: Nghiệm thu**

```bash
# Bỏ mệnh đề `!m.zoneCode && !m.unitCode &&` khỏi bộ lọc → phải có test ĐỎ.
# Nếu suite vẫn xanh thì thêm một test: ảnh mat_bang của phân khu KHÔNG lẫn vào
# vùng cấp dự án (khuôn test đã có ở vòng 1 cho MediaTab).
```

- [ ] **Step 8: Commit**

```bash
git add src/features/realestate/components/MatBangTab.tsx \
        src/features/realestate/components/DuAnForm.tsx tests/
git commit -m "feat(re): tab Mặt bằng còn một vùng ảnh"
```

---

### Task 5: Bỏ trần 6 ảnh ở frontend

**Phụ thuộc:** backend plan Task 1 phải xong trước — bỏ ở FE trước thì nút Thêm mở khoá và upload thứ bảy trả 422 mà UI không còn câu nào giải thích.

**Files:**
- Modify: `src/features/realestate/enums.ts` (bỏ `TRAN_ANH`)
- Modify: `components/VungMedia.tsx`, `components/CanForm.tsx`, `components/MediaTab.tsx`
- Modify: `src/features/realestate/thongDiep.ts`
- Test: `tests/realestate-media.test.tsx`

**Interfaces:**
- Consumes: —
- Produces: `TRAN_ANH` không còn tồn tại; `VungMedia` hiện `{soAnh} ảnh · {n} video`, nút Thêm không bao giờ khoá vì số lượng.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-media.test.tsx`, trong `describe` của tab Media:

```tsx
  it('bảy ảnh cùng danh mục vẫn thêm được — trần 6 đã bỏ', async () => {
    const anh = Array.from({ length: 7 }, (_, i) => ({
      ...MEDIA,
      id: 200 + i,
      category: 'ngoai_that',
      contentHash: `sha${i}`,
      mediaUrl: `tenants/t/kb-bds/sha${i}/a.webp`,
    }))
    datApiDoc({ media: trang(anh) })
    boot('/pform?code=VHOP2&tab=media')
    await userEvent.click(await screen.findByText('Ngoại thất'))

    const vung = (await screen.findByRole('heading', { name: 'Ngoại thất' })).closest('section')!
    expect(within(vung).getByText(/7 ảnh/)).toBeInTheDocument()
    expect(within(vung).queryByText(/\/6 ảnh/)).not.toBeInTheDocument()
    expect(within(vung).queryByText(/Đã đủ 6 ảnh/)).not.toBeInTheDocument()
    expect(within(vung).getByRole('button', { name: /Thêm ảnh/ })).toBeEnabled()
  })
```

⚠️ Bước `userEvent.click(...'Ngoại thất')` chỉ đúng **sau Task 6** (folder hai mức). Nếu Task 5 chạy trước Task 6 thì bỏ dòng click đó — bảy vùng còn mở sẵn.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-media.test.tsx -t "bảy ảnh"`
Expected: FAIL — bộ đếm hiện `6/6 ảnh` và nút Thêm bị `disabled`.

- [ ] **Step 3: Bỏ `TRAN_ANH` khỏi `enums.ts`**

Xoá cả hằng và docstring của nó (dòng 119–127).

- [ ] **Step 4: Sửa `VungMedia.tsx`**

```tsx
export function VungMedia({ projectCode, category, nhan, anh, lamMoi }: VungProps) {
  const [them, setThem] = useState<MediaKem | null>(null)
  const soAnh = anh.filter((m) => m.contentType === 'image').length
```

Bỏ dòng `const day = soAnh >= TRAN_ANH`. Bộ đếm ở header:

```tsx
        <span className="text-[12px] text-muted">
          {soAnh} ảnh
          {anh.length > soAnh && ` · ${anh.length - soAnh} video`}
        </span>
```

Bỏ khối câu «Đã đủ {TRAN_ANH} ảnh — xoá một ảnh trước khi thêm.» (dòng ~96) và bỏ `day` khỏi mọi `disabled=`. Bỏ `TRAN_ANH` khỏi dòng import.

- [ ] **Step 5: Sửa `CanForm.tsx` và `MediaTab.tsx` và `thongDiep.ts`**

- `CanForm.tsx:530,537,586,592` — cùng khuôn: bỏ `day`, bộ đếm thành `{soAnh} ảnh trong danh mục đang chọn`, bỏ câu «Trần 6 ảnh…» và câu «Danh mục này đã đủ…»
- `MediaTab.tsx:49` — bỏ câu «Mỗi danh mục nhận tối đa 6 ảnh; video… không tính vào giới hạn đó» (Task 6 viết lại cả đoạn này)
- `thongDiep.ts:39-40` — bỏ nhánh dịch lỗi `MEDIA_LIMIT`. Backend không còn trả mã đó, nên nhánh này là code chết.

- [ ] **Step 6: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS. Test cũ assert `0/6 ảnh` hoặc nút Thêm bị khoá sẽ đỏ — sửa chúng.

- [ ] **Step 7: Nghiệm thu**

```bash
grep -rn "TRAN_ANH\|/6 ảnh\|Đã đủ\|MEDIA_LIMIT" src/
# Kỳ vọng: 0 hit trong src/features/realestate.
```

- [ ] **Step 8: Commit**

```bash
git add src/features/realestate/ tests/
git commit -m "feat(re): bỏ trần 6 ảnh ở frontend"
```

---

### Task 6: Tab Media — folder hai mức, bốn danh mục

**Files:**
- Modify: `src/features/realestate/components/MediaTab.tsx`
- Modify: `src/features/realestate/enums.ts` (thêm `MEDIA_CATEGORY_TAB_RIENG`)
- Test: `tests/realestate-media.test.tsx`

**Interfaces:**
- Consumes: `VungMedia` (không trần, Task 5)
- Produces: `MEDIA_CATEGORY_TAB_RIENG: readonly string[]` — ba danh mục đã có tab chuyên đề, **không** hiện ở tab Media.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/realestate-media.test.tsx`:

```tsx
describe('tab Media — folder hai mức', () => {
  it('mức 1 hiện đúng bốn folder, không có Vị trí/Mặt bằng/Tiến độ', async () => {
    datApiDoc({ media: trang([MEDIA]) })
    boot('/pform?code=VHOP2&tab=media')

    expect(await screen.findByText('Tổng quan')).toBeInTheDocument()
    expect(screen.getByText('Ngoại thất')).toBeInTheDocument()
    expect(screen.getByText('Nội thất')).toBeInTheDocument()
    expect(screen.getByText('Tiện ích')).toBeInTheDocument()
    // Ba danh mục có tab chuyên đề đã rời khỏi đây (spec vòng 2 §3).
    expect(screen.queryByText('Vị trí')).not.toBeInTheDocument()
    expect(screen.queryByText('Mặt bằng')).not.toBeInTheDocument()
    // «Tiến độ» vẫn là tên một TAB nên phải tra trong vùng nội dung, không toàn màn.
    const noiDung = screen.getByTestId('media-muc-1')
    expect(within(noiDung).queryByText('Tiến độ')).not.toBeInTheDocument()
  })

  it('mức 1 hiện số lượng của từng folder', async () => {
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 1, category: 'ngoai_that', contentHash: 'a' },
        { ...MEDIA, id: 2, category: 'ngoai_that', contentHash: 'b' },
        { ...MEDIA, id: 3, category: 'noi_that', contentType: 'video', contentHash: 'c' },
      ]),
    })
    boot('/pform?code=VHOP2&tab=media')

    const theNgoaiThat = (await screen.findByText('Ngoại thất')).closest('button')!
    expect(within(theNgoaiThat).getByText(/2 ảnh/)).toBeInTheDocument()
    const theNoiThat = screen.getByText('Nội thất').closest('button')!
    expect(within(theNoiThat).getByText(/0 ảnh/)).toBeInTheDocument()
    expect(within(theNoiThat).getByText(/1 video/)).toBeInTheDocument()
  })

  it('bấm folder mở mức 2, chỉ ảnh của danh mục đó, và quay lại được', async () => {
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 1, category: 'ngoai_that', caption: 'Ảnh ngoại thất', contentHash: 'a' },
        { ...MEDIA, id: 2, category: 'noi_that', caption: 'Ảnh nội thất', contentHash: 'b' },
      ]),
    })
    boot('/pform?code=VHOP2&tab=media')

    await userEvent.click(await screen.findByText('Ngoại thất'))

    expect(await screen.findByRole('heading', { name: 'Ngoại thất' })).toBeInTheDocument()
    expect(screen.getByText('Ảnh ngoại thất')).toBeInTheDocument()
    expect(screen.queryByText('Ảnh nội thất')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Mọi danh mục/ }))
    expect(await screen.findByText('Tiện ích')).toBeInTheDocument()
  })

  it('đổi tab rồi về Media thì quay về mức 1', async () => {
    datApiDoc({ media: trang([MEDIA]) })
    boot('/pform?code=VHOP2&tab=media')

    await userEvent.click(await screen.findByText('Ngoại thất'))
    await screen.findByRole('heading', { name: 'Ngoại thất' })

    await userEvent.click(screen.getByRole('tab', { name: 'Tiến độ' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Media' }))

    expect(await screen.findByText('Tiện ích')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Ngoại thất' })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-media.test.tsx -t 'folder hai mức'`
Expected: FAIL — bảy vùng mở sẵn, không có thẻ folder nào để bấm.

- [ ] **Step 3: Thêm hằng vào `enums.ts`**

```ts
/**
 * Ba danh mục media đã có TAB CHUYÊN ĐỀ riêng, nên KHÔNG hiện ở tab Media
 * (spec vòng 2 §3 — đổi nguyên tắc «lăng kính» của vòng 1: một danh mục một
 * chỗ). Suy từ đây chứ không liệt kê tay ở `MediaTab`: thêm một tab chuyên đề
 * mà quên bỏ danh mục khỏi tab Media là hai chỗ cùng thấy một ảnh.
 */
export const MEDIA_CATEGORY_TAB_RIENG: readonly string[] = ['vi_tri', 'mat_bang', 'tien_do']
```

- [ ] **Step 4: Viết lại `MediaTab.tsx`**

```tsx
/**
 * Tab Media — folder hai mức cho bốn danh mục không có tab chuyên đề.
 *
 * BỐN, KHÔNG PHẢI BẢY (spec vòng 2 §3): `vi_tri`/`mat_bang`/`tien_do` đã có tab
 * riêng và rời khỏi đây, nên mỗi danh mục media chỉ còn thấy được ở đúng MỘT
 * chỗ. Vòng 1 giữ cả bảy và phải viết một câu giải thích «cùng một ảnh, không
 * phải bản sao» — một danh mục một chỗ thì không cần câu nào.
 *
 * FOLDER, KHÔNG PHẢI BỐN VÙNG MỞ SẴN: sau khi bỏ trần 6 ảnh, một danh mục có
 * thể có hàng chục ảnh — bốn vùng mở sẵn thành một trang không cuộn hết.
 *
 * MỨC ĐANG XEM Ở STATE, KHÔNG Ở URL: thêm `?folder=` là thêm một nguồn sự thật
 * cho một trạng thái không ai deep-link tới. Đổi tab là remount nên về mức 1.
 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, type Media } from '../api'
import { MEDIA_CATEGORY, MEDIA_CATEGORY_TAB_RIENG } from '../enums'
import { LoiTai } from './TrangCuon'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'
import { NUT_PHU } from './Bang'

const DANH_MUC = MEDIA_CATEGORY.filter((dm) => !MEDIA_CATEGORY_TAB_RIENG.includes(dm.value))

export function MediaTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const [dangMo, setDangMo] = useState<string | null>(null)

  const ds = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  if (ds.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (ds.error) return <LoiTai viec="danh sách media" thuLai={() => void ds.refetch()} />

  // Chỉ media CẤP DỰ ÁN. Ảnh của phân khu và của căn thuộc về form của chúng —
  // hiện lẫn ở đây thì xoá một ảnh ở tab này lấy đi ảnh đại diện của một căn.
  const capDuAn = ds.items.filter((m) => !m.zoneCode && !m.unitCode)
  const lamMoi = () => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })
  const cuaDanhMuc = (v: string) => capDuAn.filter((m) => m.category === v)

  const mo = DANH_MUC.find((dm) => dm.value === dangMo)
  if (mo) {
    return (
      <div className="space-y-3">
        <button type="button" className={NUT_PHU} onClick={() => setDangMo(null)}>
          ‹ Mọi danh mục
        </button>
        <VungMedia
          projectCode={projectCode}
          category={mo.value}
          nhan={mo.nhan}
          anh={cuaDanhMuc(mo.value)}
          lamMoi={lamMoi}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4" data-testid="media-muc-1">
      <p className="text-[13px] text-muted">
        Ảnh và video cấp dự án. Vị trí, Mặt bằng và Tiến độ có tab riêng. Ảnh của phân khu nằm trong
        form phân khu, ảnh của căn nằm trong form căn.
      </p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {DANH_MUC.map((dm) => {
          const cua = cuaDanhMuc(dm.value)
          const soAnh = cua.filter((m) => m.contentType === 'image').length
          const bia = cua.find((m) => m.contentType === 'image')
          return (
            <button
              key={dm.value}
              type="button"
              className="rounded-xl border border-border bg-surface p-3 text-left hover:border-border-field"
              onClick={() => setDangMo(dm.value)}
            >
              <div className="mb-2 flex h-24 items-center justify-center rounded bg-fill-strong text-[12px] text-muted">
                {bia ? (
                  <img
                    src={nguonAnh(bia.thumbUrl ?? bia.mediaUrl)}
                    alt=""
                    className="h-24 w-full rounded object-cover"
                  />
                ) : (
                  'Chưa có ảnh'
                )}
              </div>
              <p className="text-[14px] font-medium">{dm.nhan}</p>
              <p className="text-[12px] text-muted">
                {soAnh} ảnh
                {cua.length > soAnh && ` · ${cua.length - soAnh} video`}
              </p>
            </button>
          )
        })}
      </div>
    </div>
  )
}
```

Thêm `nguonAnh` vào dòng import từ `'../api'`.

⚠️ Kiểm `NUT_PHU` và `bg-fill-strong` có thật (`grep -n "NUT_PHU\|fill-strong" src/components/ui/Bang.tsx src/styles/theme.css`). Thiếu thì dùng class có thật, **đừng** thêm màu thô.

- [ ] **Step 5: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS. Test cũ của tab Media (bảy vùng, câu chữ overlap) sẽ đỏ — sửa/bỏ chúng theo nghĩa mới. **Bỏ** test vòng 1 «nói rõ ba vùng cũng có tab chuyên đề riêng»: câu đó đã được thay.

- [ ] **Step 6: Nghiệm thu**

```bash
# (a) bỏ `.filter(...MEDIA_CATEGORY_TAB_RIENG...)` → test `đúng bốn folder` phải ĐỎ
# (b) bỏ `setDangMo(null)` khỏi nút quay lại → test `quay lại được` phải ĐỎ
```

- [ ] **Step 7: Commit**

```bash
git add src/features/realestate/components/MediaTab.tsx \
        src/features/realestate/enums.ts tests/
git commit -m "feat(re): tab Media thành folder hai mức, bốn danh mục"
```

---

### Task 7: `api.ts` — `total` và `offset`

**Phụ thuộc:** backend plan Task 2–3 phải xong.

**Files:**
- Modify: `src/features/realestate/api.ts`
- Modify: `tests/re-fixture.tsx` (`trang()` thêm `total`)
- Test: `tests/realestate-phan-trang.test.tsx` (**mới**, chỉ phần kiểu — hook ở Task 8)

**Interfaces:**
- Produces:
  - `Trang<T>` thêm `readonly total: number`
  - `danhSachDuAn(loc?: LocDuAn & { limit?: number; offset?: number })`
  - `danhSachPhanKhu(projectCode, loc?: { limit?: number; offset?: number; cursor?: string | null })` — **đổi từ tham số vị trí `cursor` sang object**
  - `danhSachTaiLieu(projectCode, loc?: { limit?: number; offset?: number; cursor?: string | null })` — cùng đổi
  - `danhSachCan`, `danhSachMedia` — `LocCan`/`LocMedia` thêm `limit`/`offset`

- [ ] **Step 1: Sửa `Trang<T>` và `trang()` của fixture**

`api.ts`:

```ts
export interface Trang<T> {
  readonly items: readonly T[]
  readonly nextCursor: string | null
  /**
   * Tổng số hàng khớp bộ lọc — KHÔNG phải `items.length`. Có để dựng thanh trang
   * có số; `nextCursor` vẫn còn cho đường keyset.
   */
  readonly total: number
}
```

`tests/re-fixture.tsx`:

```tsx
export function trang<T>(items: T[], nextCursor: string | null = null, total?: number) {
  return { items, nextCursor, total: total ?? items.length }
}
```

`total` mặc định `items.length` để **mọi** test có sẵn không phải sửa — chỉ test nào cần `total` khác mới truyền.

- [ ] **Step 2: Đổi hai hàm dùng tham số vị trí**

`danhSachPhanKhu` và `danhSachTaiLieu` hiện nhận `cursor?: string | null` **vị trí thứ hai**. Đổi sang object:

```ts
export interface LocTrang {
  readonly limit?: number
  readonly offset?: number
  readonly cursor?: string | null
}

export function danhSachPhanKhu(projectCode: string, loc: LocTrang = {}): Promise<Trang<PhanKhu>> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/zones${qs({ ...loc, cursor: loc.cursor ?? undefined })}`,
  )
}

export function danhSachTaiLieu(projectCode: string, loc: LocTrang = {}): Promise<Trang<TaiLieu>> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/documents${qs({ ...loc, cursor: loc.cursor ?? undefined })}`,
  )
}
```

⚠️ **Đây là đổi vỡ.** Tìm **mọi** chỗ gọi và sửa:

```bash
grep -rn "danhSachPhanKhu\|danhSachTaiLieu" src/ tests/
```

Lời gọi cũ `danhSachPhanKhu(code, c)` thành `danhSachPhanKhu(code, { cursor: c })`. Bỏ sót một chỗ thì `cursor` bị truyền vào chỗ `limit` — **vẫn typecheck sai kiểu nên lint sẽ bắt**, nhưng đừng dựa vào đó, sửa hết bằng grep.

- [ ] **Step 3: Thêm `limit`/`offset` vào `LocDuAn`, `LocCan`, `LocMedia`**

Ba interface này đã có; thêm hai field tuỳ chọn vào mỗi cái (nếu `limit` đã có thì chỉ thêm `offset`).

- [ ] **Step 4: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS — không đổi hành vi, chỉ đổi chữ ký. Bất kỳ đỏ nào ở đây là một lời gọi bị bỏ sót ở Step 2.

- [ ] **Step 5: Commit**

```bash
git add src/features/realestate/api.ts tests/re-fixture.tsx src/ tests/
git commit -m "feat(re): api.ts nhận offset và đọc total"
```

---

### Task 8: `useTrangSo` + thanh trang cho bốn bảng

**Files:**
- Create: `src/features/realestate/components/useTrangSo.ts`
- Create: `src/features/realestate/components/ThanhTrang.tsx`
- Modify: `components/TaiLieuTab.tsx`, `CanTab.tsx`, `PhanKhuTab.tsx`, `DuAnList.tsx`
- Test: `tests/realestate-phan-trang.test.tsx`

**Interfaces:**
- Consumes: `Trang<T>.total` (Task 7)
- Produces:
  - `useTrangSo<T>(queryKey: QueryKey, nap: (p: { limit: number; offset: number }) => Promise<Trang<T>>, soHangDau?: number)` → `{ items, total, trang, soTrang, soHang, doiTrang, doiSoHang, isPending, error, refetch }`
  - `ThanhTrang({ trang, soTrang, total, soHang, doiTrang, doiSoHang })`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/realestate-phan-trang.test.tsx`:

```tsx
/**
 * Phân trang CÓ SỐ cho bốn bảng (spec vòng 2 §4.8).
 *
 * Canh đúng thứ cursor không làm được: nhảy thẳng tới trang n. Và canh rằng số
 * trang suy từ `total` của SERVER, không từ `items.length` — suy từ `items` cho
 * đúng 1 trang mãi mãi.
 */
import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { CAN, DU_AN, boot, datApiDoc, trang } from './re-fixture'

function batTruyVan() {
  const goi: URL[] = []
  server.use(
    http.get('/api/v1/projects/:code/units', ({ request }) => {
      const u = new URL(request.url)
      goi.push(u)
      const offset = Number(u.searchParams.get('offset') ?? 0)
      return HttpResponse.json(
        trang([{ ...CAN, id: 1000 + offset, unitCode: `U-${offset}` }], null, 47),
      )
    }),
  )
  return goi
}

describe('thanh phân trang bảng quỹ căn', () => {
  it('số trang suy từ total của server, không từ số hàng đang có', async () => {
    datApiDoc()
    batTruyVan()
    boot('/pform?code=VHOP2&tab=quy-can')

    // 47 hàng, 20 hàng/trang ⇒ 3 trang.
    expect(await screen.findByText(/47/)).toBeInTheDocument()
    const thanh = screen.getByRole('navigation', { name: 'Phân trang' })
    expect(within(thanh).getByRole('button', { name: '3' })).toBeInTheDocument()
    expect(within(thanh).queryByRole('button', { name: '4' })).not.toBeInTheDocument()
  })

  it('bấm trang 3 gửi offset đúng, không đi qua trang 2', async () => {
    datApiDoc()
    const goi = batTruyVan()
    boot('/pform?code=VHOP2&tab=quy-can')

    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '3' }))

    await screen.findByText('U-40')
    expect(goi.map((u) => u.searchParams.get('offset'))).toContain('40')
    // KHÔNG có request nào cho trang 2 — đó là điểm của phân trang có số.
    expect(goi.map((u) => u.searchParams.get('offset'))).not.toContain('20')
  })

  it('đổi số hàng mỗi trang thì về trang 1', async () => {
    datApiDoc()
    const goi = batTruyVan()
    boot('/pform?code=VHOP2&tab=quy-can')

    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '3' }))
    await screen.findByText('U-40')

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Mỗi trang/ }), '50')

    // Về trang 1: ở trang 3 với 50 hàng/trang thì offset 100 > total 47 ⇒ bảng
    // rỗng, và người dùng không hiểu vì sao dữ liệu biến mất.
    const cuoi = goi[goi.length - 1]!
    expect(cuoi.searchParams.get('offset')).toBe('0')
    expect(cuoi.searchParams.get('limit')).toBe('50')
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Run: `npx vitest run tests/realestate-phan-trang.test.tsx`
Expected: FAIL — không có `navigation` nào tên `Phân trang`.

- [ ] **Step 3: Tạo `useTrangSo.ts`**

```ts
/**
 * Phân trang CÓ SỐ TRANG cho các BẢNG — đứng cạnh `useTrangCuon`, không thay nó.
 *
 * HAI HOOK CHO HAI KIỂU NẠP, cố ý: bảng cần nhảy tới trang n (người dùng biết
 * mình đang ở đâu trong 237 hàng), còn media cần nạp một lần rồi lọc client-side
 * cho bốn folder không lệch số đếm nhau. Gộp thành một hook nhận cờ là một hook
 * làm hai việc và không rõ việc nào đang chạy.
 *
 * `useQuery` chứ `useInfiniteQuery`: mỗi trang là một truy vấn ĐỘC LẬP, không
 * nối dồn — `queryKey` mang `trang`/`soHang` nên react-query cache từng trang
 * riêng và bấm lại trang cũ là tức thời.
 */
import { useState } from 'react'
import { useQuery, type QueryKey } from '@tanstack/react-query'
import type { Trang } from '../api'

export const SO_HANG_CHON = [20, 50, 100] as const
const SO_HANG_DAU = 20

export function useTrangSo<T>(
  queryKey: QueryKey,
  nap: (p: { limit: number; offset: number }) => Promise<Trang<T>>,
  soHangDau: number = SO_HANG_DAU,
) {
  const [trang, setTrang] = useState(1)
  const [soHang, setSoHang] = useState(soHangDau)

  const q = useQuery({
    queryKey: [...queryKey, 'trang', trang, soHang],
    queryFn: () => nap({ limit: soHang, offset: (trang - 1) * soHang }),
  })

  const total = q.data?.total ?? 0
  return {
    items: (q.data?.items ?? []) as readonly T[],
    total,
    trang,
    soHang,
    soTrang: Math.max(1, Math.ceil(total / soHang)),
    doiTrang: setTrang,
    // Đổi số hàng PHẢI về trang 1: đang ở trang 3 với 20 hàng rồi đổi sang 100
    // thì offset 200 có thể vượt `total` ⇒ bảng rỗng, và người dùng đọc thành
    // "dữ liệu biến mất".
    doiSoHang: (n: number) => {
      setSoHang(n)
      setTrang(1)
    },
    isPending: q.isPending,
    error: q.error,
    refetch: q.refetch,
  }
}
```

- [ ] **Step 4: Tạo `ThanhTrang.tsx`**

```tsx
/**
 * Thanh phân trang — `‹ 1 2 [3] … 12 ›` + ô chọn số hàng.
 *
 * `nav[aria-label]` chứ không một `<div>`: đây là điều hướng, và test lẫn trình
 * đọc màn hình đều cần một mốc để tra thanh này thay vì mọi nút số trên trang.
 */
import { SO_HANG_CHON } from './useTrangSo'
import { NUT_PHU } from './Bang'

const NUT_TRANG = 'min-w-8 rounded px-2 py-1 text-[13px]'

interface Props {
  trang: number
  soTrang: number
  total: number
  soHang: number
  doiTrang: (n: number) => void
  doiSoHang: (n: number) => void
}

/** Dãy số trang quanh trang hiện tại, `null` = dấu `…`. */
function daySo(trang: number, soTrang: number): (number | null)[] {
  if (soTrang <= 7) return Array.from({ length: soTrang }, (_, i) => i + 1)
  const quanh = [trang - 1, trang, trang + 1].filter((n) => n > 1 && n < soTrang)
  const day: (number | null)[] = [1]
  if (quanh[0] !== undefined && quanh[0] > 2) day.push(null)
  day.push(...quanh)
  if (quanh[quanh.length - 1] !== undefined && quanh[quanh.length - 1]! < soTrang - 1) day.push(null)
  day.push(soTrang)
  return day
}

export function ThanhTrang({ trang, soTrang, total, soHang, doiTrang, doiSoHang }: Props) {
  const dau = total === 0 ? 0 : (trang - 1) * soHang + 1
  const cuoi = Math.min(trang * soHang, total)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-[13px]">
      <span className="text-muted">
        Hiện {dau}–{cuoi} / {total}
      </span>

      <nav aria-label="Phân trang" className="flex items-center gap-1">
        <button
          type="button"
          className={NUT_PHU}
          disabled={trang <= 1}
          onClick={() => doiTrang(trang - 1)}
        >
          ‹
        </button>
        {daySo(trang, soTrang).map((n, i) =>
          n === null ? (
            <span key={`x${i}`} className="px-1 text-muted">
              …
            </span>
          ) : (
            <button
              key={n}
              type="button"
              aria-current={n === trang ? 'page' : undefined}
              className={`${NUT_TRANG} ${n === trang ? 'bg-acs text-ac font-medium' : 'text-muted'}`}
              onClick={() => doiTrang(n)}
            >
              {n}
            </button>
          ),
        )}
        <button
          type="button"
          className={NUT_PHU}
          disabled={trang >= soTrang}
          onClick={() => doiTrang(trang + 1)}
        >
          ›
        </button>
      </nav>

      <label className="flex items-center gap-2">
        Mỗi trang
        <select
          className="rounded border border-border-field px-2 py-1"
          value={soHang}
          onChange={(e) => doiSoHang(Number(e.target.value))}
        >
          {SO_HANG_CHON.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
```

- [ ] **Step 5: Nối vào bốn bảng**

Khuôn cho **cả bốn** file, ví dụ làm mẫu ở `CanTab.tsx`:

```tsx
// TRƯỚC
const ds = useTrangCuon<Can>(['re', projectCode, 'units'], (c) =>
  danhSachCan(projectCode, { cursor: c }),
)

// SAU
const ds = useTrangSo<Can>(['re', projectCode, 'units'], ({ limit, offset }) =>
  danhSachCan(projectCode, { limit, offset }),
)
```

Rồi ở chân bảng, **ngoài** vùng cuộn (cạnh `ChanBang` nếu file đó có):

```tsx
      <ThanhTrang
        trang={ds.trang}
        soTrang={ds.soTrang}
        total={ds.total}
        soHang={ds.soHang}
        doiTrang={ds.doiTrang}
        doiSoHang={ds.doiSoHang}
      />
```

Và bỏ nút «Tải thêm» cùng mọi thứ chỉ nó dùng (`hasNextPage`, `fetchNextPage`, `isFetchingNextPage`, component `NutTaiThem` nếu không còn ai gọi — kiểm bằng `grep -rn "NutTaiThem" src/`).

Áp cùng khuôn cho `TaiLieuTab.tsx` (`danhSachTaiLieu`), `PhanKhuTab.tsx` (`danhSachPhanKhu`), `DuAnList.tsx` (`danhSachDuAn`). ⚠️ `DuAnList` có ô tìm kiếm và ô lọc `region`: chúng phải vào `queryKey` của `useTrangSo` **và** phải gọi `doiTrang(1)` khi đổi — đang ở trang 5 rồi gõ tìm kiếm mới thì trang 5 của kết quả mới thường rỗng.

⚠️ **`TaiLieuTab` có bộ lọc loại client-side.** Sau khi phân trang, lọc chỉ áp trên **trang hiện tại** — «CSBH 4» nghĩa là 4 trong 20 hàng của trang này, không phải 4 trong 237 hàng của dự án. Câu chữ **phải nói ra**: đổi dòng cảnh báo đang có thành «Số đếm và bộ lọc chỉ tính trang đang xem.» và giữ nó **luôn** hiện (không còn điều kiện `hasNextPage`).

- [ ] **Step 6: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS. Test cũ bấm «Tải thêm» sẽ đỏ — sửa sang bấm số trang.

- [ ] **Step 7: Nghiệm thu**

```bash
# (a) đổi `soTrang` sang suy từ `items.length` → test `số trang suy từ total` ĐỎ
# (b) bỏ `setTrang(1)` khỏi `doiSoHang` → test `đổi số hàng thì về trang 1` ĐỎ
# (c) bỏ `offset` khỏi hàm nạp → test `bấm trang 3 gửi offset đúng` ĐỎ
```

- [ ] **Step 8: Commit**

```bash
git add src/features/realestate/components/ tests/
git commit -m "feat(re): phân trang có số cho bốn bảng"
```

---

### Task 9: Cột Hướng ở bảng Quỹ căn

**Files:**
- Modify: `src/features/realestate/components/CanTab.tsx`
- Test: `tests/realestate-uform.test.tsx` (hoặc file test có sẵn của tab Quỹ căn)

**Interfaces:**
- Consumes: `HUONG` (`enums.ts:67`), `Can.direction` (`api.ts:136`) — **cả hai đã có**, không cần đụng API.
- Produces: bảng Quỹ căn có `columnheader` tên `Hướng`.

- [ ] **Step 1: Viết test đỏ**

```tsx
  it('bảng quỹ căn có cột Hướng, hiện nhãn tiếng Việt', async () => {
    datApiDoc({ units: trang([{ ...CAN, direction: 'dong_nam' }]) })
    boot('/pform?code=VHOP2&tab=quy-can')

    expect(await screen.findByRole('columnheader', { name: 'Hướng' })).toBeInTheDocument()
    expect(screen.getByText('Đông Nam')).toBeInTheDocument()
    expect(screen.queryByText('dong_nam')).not.toBeInTheDocument()
  })

  it('căn chưa có hướng hiện gạch ngang, không hiện chuỗi rỗng', async () => {
    datApiDoc({ units: trang([{ ...CAN, direction: null }]) })
    boot('/pform?code=VHOP2&tab=quy-can')

    const hang = (await screen.findByText(CAN.unitCode)).closest('tr')!
    expect(within(hang).getByText('—')).toBeInTheDocument()
  })
```

⚠️ Kiểm nhãn thật của `dong_nam` trong `enums.ts:67` — nếu nó là `'Đông nam'` (n thường) thì dùng đúng chuỗi đó.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Expected: FAIL — không có `columnheader` tên `Hướng`.

- [ ] **Step 3: Thêm cột**

`COT` — chèn **sau** `DT thông thuỷ`, **trước** `Giá`: hướng là thuộc tính vật lý của căn, cùng nhóm với diện tích, không thuộc nhóm thương mại.

```tsx
const COT: readonly Cot[] = [
  { nhan: 'Căn' },
  { nhan: 'Phân khu' },
  { nhan: 'Loại' },
  { nhan: 'PN', phai: true },
  { nhan: 'DT thông thuỷ', phai: true },
  { nhan: 'Hướng' },
  { nhan: 'Giá', phai: true },
  { nhan: 'Bán' },
  { nhan: '', phai: true },
]
```

(Mục `Trạng thái` đã bỏ ở Task 3.)

Trong hàng bảng, thêm `<td>` ở **đúng vị trí tương ứng**:

```tsx
              <td className="px-3 py-2">{nhanCua(HUONG, c.direction) || '—'}</td>
```

`nhanCua` trả `''` khi `value` rỗng/null, nên `|| '—'` là chỗ biến chuỗi rỗng thành một dấu đọc được.

Thêm `HUONG` vào dòng import từ `'../enums'`.

- [ ] **Step 4: Chạy test và nghiệm thu**

Run: `npm test && npm run lint`

```bash
# Bỏ `{ nhan: 'Hướng' }` khỏi COT (giữ <td>) → assertion đếm cột của Task 3
# và test `có cột Hướng` phải ĐỎ.
```

- [ ] **Step 5: Commit**

```bash
git add src/features/realestate/components/CanTab.tsx tests/
git commit -m "feat(re): bảng quỹ căn thêm cột Hướng"
```

---

### Task 10: Badge màu cho loại tài liệu

**Files:**
- Modify: `src/styles/theme.css`
- Modify: `src/features/realestate/enums.ts`
- Modify: `src/features/realestate/components/TaiLieuTab.tsx`
- Test: `tests/realestate-tai-lieu-loai.test.tsx`

**Interfaces:**
- Produces: `mauLoaiTaiLieu(loai: string): string` — trả class Tailwind cho một `loai`, **có** nhánh mặc định. Một hàm chứ một `Record`: `Record` bắt mọi chỗ dùng tự lo ca thiếu khoá, và một trong số đó sẽ quên.

- [ ] **Step 1: Viết test đỏ**

```tsx
describe('badge màu theo loại', () => {
  it('mỗi loại một class màu khác nhau, và pill thanh lọc cùng màu với badge', async () => {
    datApiDoc({ documents: trang([CSBH, PHAP_LY, KHAC]) })
    await moTabTaiLieu()

    const badgeCsbh = await screen.findByText('Chính sách bán hàng')
    const badgePhapLy = screen.getByText('Pháp lý')
    expect(badgeCsbh.className).not.toBe(badgePhapLy.className)
    expect(badgeCsbh.className).toMatch(/badge-doc-csbh/)
    expect(badgePhapLy.className).toMatch(/badge-doc-phaply/)

    const thanh = screen.getByRole('group', { name: 'Lọc theo loại' })
    const pillCsbh = within(thanh).getByRole('button', { name: /Chính sách bán hàng/ })
    expect(pillCsbh.className).toMatch(/badge-doc-csbh/)
  })

  it('loại lạ vẫn có nền, không mất class', async () => {
    datApiDoc({ documents: trang([{ ...KHAC, id: 99, loai: 'loai_thu_nam' }]) })
    await moTabTaiLieu()

    const badge = await screen.findByText('loai_thu_nam')
    expect(badge.className).toMatch(/badge-neutral/)
  })
})
```

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Expected: FAIL — `badgeCsbh.className` không khớp `/badge-doc-csbh/`.

- [ ] **Step 3: Thêm token vào `src/styles/theme.css`**

Cạnh ba cặp badge đang có (dòng 117–122):

```css
  /* Badge PHÂN LOẠI tài liệu — tách khỏi ba cặp badge TRẠNG THÁI ở trên: đỏ đọc
     thành "lỗi", hổ phách thành "đang chờ", và accent dành cho hành động chính.
     Số sau mỗi cặp là tỉ lệ tương phản WCAG của fg trên bg. */
  --color-badge-doc-csbh-bg: #e8f0fb;
  --color-badge-doc-csbh-fg: #1f5aa8; /* 5.93 */
  --color-badge-doc-phaply-bg: #f0ecfa;
  --color-badge-doc-phaply-fg: #5b45a8; /* 6.32 */
  --color-badge-doc-huongdan-bg: #e6f2f4;
  --color-badge-doc-huongdan-fg: #1f6b7a; /* 5.34 */
```

- [ ] **Step 4: Thêm map vào `enums.ts`**

```ts
/**
 * Màu badge theo loại tài liệu. Bốn loại bốn màu để phân biệt ở tầm nhìn một
 * giây; `khac` dùng cặp TRUNG TÍNH có sẵn — thùng chưa phân loại đúng là không
 * màu, và tô nó cũng khiến bốn màu không còn chỗ nào để nghỉ mắt.
 *
 * Nhánh mặc định KHÔNG được thiếu: `nhanCua()` trả chính `value` khi không tìm
 * thấy nhãn, nên một `loai` lạ (dữ liệu cũ, hoặc backend thêm loại thứ năm) sẽ
 * render mã máy — thiếu nhánh này thì class là `undefined` và badge mất nền.
 */
const MAU_MAC_DINH = 'bg-badge-neutral-bg text-badge-neutral-fg'

export function mauLoaiTaiLieu(loai: string): string {
  return (
    {
      csbh: 'bg-badge-doc-csbh-bg text-badge-doc-csbh-fg',
      phap_ly: 'bg-badge-doc-phaply-bg text-badge-doc-phaply-fg',
      huong_dan: 'bg-badge-doc-huongdan-bg text-badge-doc-huongdan-fg',
      khac: MAU_MAC_DINH,
    }[loai] ?? MAU_MAC_DINH
  )
}
```

- [ ] **Step 5: Dùng ở `TaiLieuTab.tsx`**

Cột Loại trong hàng bảng:

```tsx
                        <span className={`${PILL} ${mauLoaiTaiLieu(t.loai)}`}>
                          {nhanCua(LOAI_TAI_LIEU, t.loai)}
                        </span>
```

Pill thanh lọc — pill đang chọn dùng màu của loại đó, pill chưa chọn để trung tính:

```tsx
            <button
              key={l.value}
              type="button"
              className={
                locLoai === l.value ? `${PILL} ${mauLoaiTaiLieu(l.value)}` : NUT_PHU
              }
              onClick={() => setLocLoai(l.value as LoaiTaiLieu)}
            >
              {l.nhan} {hienThi.filter((t) => t.loai === l.value).length}
            </button>
```

⚠️ Test canh «pill cùng màu với badge» tra `className` của pill **đang chọn**; nếu bạn chọn cách khác (ví dụ luôn tô pill) thì sửa test cho khớp cách bạn chọn — nhưng phải giữ **ý**: mắt nối được pill với hàng.

Thêm `mauLoaiTaiLieu` vào import từ `'../enums'`, và `PILL` từ `'./Bang'` nếu chưa có.

- [ ] **Step 6: Chạy test và nghiệm thu**

Run: `npm test && npm run lint`

```bash
# Bỏ nhánh `?? MAU_MAC_DINH` → test `loại lạ vẫn có nền` phải ĐỎ.
# Cho csbh và phap_ly cùng một class → test `mỗi loại một class khác nhau` ĐỎ.
```

- [ ] **Step 7: Commit**

```bash
git add src/styles/theme.css src/features/realestate/ tests/
git commit -m "feat(re): badge màu theo loại tài liệu"
```

---

### Task 11: Tab Tổng quan — ba nhóm

**Files:**
- Modify: `src/features/realestate/components/TongQuanTab.tsx`
- Modify: `src/features/realestate/components/TomTatDuAn.tsx`
- Test: `tests/realestate-pform.test.tsx`

**Interfaces:**
- Consumes: `NhomTruong`
- Produces: tab Tổng quan có đúng ba `role="group"`.

- [ ] **Step 1: Viết test đỏ**

Sửa test năm nhóm đã có (`tests/realestate-pform.test.tsx`) thành ba:

```tsx
  it('tab Tổng quan chia ba nhóm', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))

    for (const ten of ['Tổng quan', 'Quy mô & mật độ', 'Sở hữu & bàn giao']) {
      expect(screen.getByRole('group', { name: ten })).toBeInTheDocument()
    }
    // Ba tên nhóm cũ phải mất hẳn — còn lại nghĩa là đã đổi tên mà không xếp lại ô.
    for (const cu of ['Định danh & phân loại', 'Chủ đầu tư', 'Mô tả']) {
      expect(screen.queryByRole('group', { name: cu })).not.toBeInTheDocument()
    }
  })
```

**Đừng sửa** test so tập nhãn ô hai chế độ (XEM ↔ SỬA) — nó phải tự đỏ nếu bạn chỉ sửa một chế độ. Đó là toàn bộ giá trị của nó.

- [ ] **Step 2: Chạy test để chắc nó đỏ**

Expected: FAIL — `Định danh & phân loại` vẫn còn.

- [ ] **Step 3: Xếp lại ba nhóm ở `TongQuanTab.tsx`**

Không thêm, không bớt ô nào (ô `status` đã bỏ ở Task 2). Ba `NhomTruong`:

| Nhóm | Ô, theo thứ tự |
|---|---|
`Tổng quan` | `projectCode` · `name` · `salePhase` · `category` (trong `CaHang`) · `investor` · `developer` · `amenities` (`CaHang`) · `overview` (`CaHang`) · Ảnh cover (`CaHang`) |
`Quy mô & mật độ` | `totalLandAreaM2` · `floorAreaM2` · `buildDensityPct` · `productScale` · `totalInvestmentVnd` |
`Sở hữu & bàn giao` | `ownershipForm` · `handoverStandard` |

Thứ tự trong nhóm Tổng quan đi từ *nhận diện* → *phân loại* → *ai làm* → *kể về nó*, đúng thứ tự một người giới thiệu dự án bằng lời.

- [ ] **Step 4: Xếp lại `TomTatDuAn.tsx` cho khớp**

Chế độ XEM phải có **cùng ba nhóm, cùng tên, cùng thứ tự, cùng bộ ô**. `GiaTri` render giá trị rỗng thành chữ «Chưa đặt», nên một ô lệch giữa hai chế độ làm chế độ XEM *khẳng định một điều sai*.

Cập nhật docstring của `TomTatDuAn` (nó tự khai «NĂM NHÓM») và số ô nếu nó nói.

- [ ] **Step 5: Chạy test**

Run: `npm test && npm run lint`
Expected: PASS — kể cả test so tập nhãn hai chế độ.

- [ ] **Step 6: Nghiệm thu**

```bash
# (a) đổi một `tieuDe` chỉ ở TomTatDuAn → test so tập nhãn phải ĐỎ
# (b) xoá một <DongXem> khỏi TomTatDuAn  → test so tập nhãn phải ĐỎ
# (c) đổi tên nhóm 'Quy mô & mật độ' ở TongQuanTab → test ba nhóm phải ĐỎ
```

- [ ] **Step 7: Dọn comment nói sai trên cả nhánh**

```bash
grep -rn "mười tab\|10 tab\|bảy vùng\|7 vùng\|năm nhóm\|16 ô\|17 ô\|trần 6\|TRAN_ANH\|loaiKhoa\|mapMedia" src/ tests/
```

Sửa mọi dòng còn nói sai. Vòng 1 phải dọn ~18 dòng ở cuối vì dồn lại — lần này mỗi task đã dọn phần của nó, bước này chỉ để bắt phần sót.

- [ ] **Step 8: Commit**

```bash
git add src/features/realestate/ tests/
git commit -m "refactor(re): tab Tổng quan chia ba nhóm"
```

---

## Sau khi xong mười một task

1. Review toàn nhánh (`superpowers:requesting-code-review`) — dùng `scripts/review-package MERGE_BASE HEAD`.
2. Bàn giao lệnh push cho người dùng — **không tự push**.
3. Nhắc người dùng **copy tay** `docs/contracts/mat-bang-agent.md` sang repo `odyssey-agent`, và rằng cho tới lúc đó agent trả lời "chưa có mặt bằng" cho dự án có ảnh (spec §6).
