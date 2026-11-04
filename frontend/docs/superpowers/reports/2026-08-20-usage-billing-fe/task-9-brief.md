### Task 9: Panel bộ giá — dòng giá, form, preview, kích hoạt

**Files:**
- Create: `src/features/billing/components/PanelBoGia.tsx`
- Test: `tests/billing-gia.test.tsx` (thêm)

**Interfaces:**
- Consumes: `useThemDongGia`/`useKichHoat`/`usePreview` (Task 3), `PRICING_BASIS`/`metricCua`/`basisCua`/`STT_THOI_LUONG` (Task 7)

⚠️ **Không có endpoint đọc `price_item`** của một bộ giá. `liet_ke_bang_gia` chỉ trả metadata. Nên panel **không hiện được bảng dòng giá đã có** — chỉ hiện form THÊM dòng. Ghi vào §13.

- [ ] **Step 1: Viết test — hai bài quan trọng nhất là alias và STT**

```tsx
it('body POST items gửi unitPrice/perUnits camelCase, phần còn lại tên thường', async () => {
  luuToken('t'); const body = batBody('POST', '/admin/billing/price-versions/1/items')
  bootPricing(); await moPanelBoGia('Chuẩn Q3/2026')
  await userEvent.selectOptions(screen.getByLabelText('Component'), 'tts')
  await userEvent.type(screen.getByLabelText('Đơn giá'), '0.126')
  await userEvent.click(screen.getByRole('button', { name: 'Thêm dòng' }))
  // Không có populate_by_name ở BE ⇒ gửi unit_price sẽ ăn 422
  expect(await body()).toEqual({
    component: 'tts', purpose: '', provider: '', model: '',
    metric: 'text_units', unitPrice: '0.126', perUnits: 1, note: '',
  })
})

it('STT: chọn audio_sec vẫn cho chọn text_units, nhưng KHOÁ wall_ms', async () => {
  luuToken('t'); bootPricing(); await moPanelBoGia('Nháp Q4/2026')
  await userEvent.selectOptions(screen.getByLabelText('Component'), 'stt')
  const metric = screen.getByLabelText('Metric') as HTMLSelectElement
  const opt = (v: string) => [...metric.options].find((o) => o.value === v)!
  expect(opt('audio_sec').disabled).toBe(false)
  expect(opt('text_units').disabled).toBe(false) // ĐỘC LẬP từ 0948
  expect(opt('wall_ms').disabled).toBe(true) // loại trừ với audio_sec
})

it('đơn vị hiện thành CHỮ trong ô nhập, đổi theo metric', async () => {
  luuToken('t'); bootPricing(); await moPanelBoGia('Nháp Q4/2026')
  await userEvent.selectOptions(screen.getByLabelText('Component'), 'llm')
  expect(screen.getByText('đ /1M token')).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Component'), 'tts')
  expect(screen.getByText('đ /ký tự')).toBeInTheDocument()
})

it('Kích hoạt KHOÁ tới khi preview đã chạy cho ĐÚNG bộ đó', async () => {
  luuToken('t'); bootPricing(); await moPanelBoGia('Nháp Q4/2026')
  expect(screen.getByRole('button', { name: 'Kích hoạt' })).toBeDisabled()
  await userEvent.selectOptions(screen.getByLabelText('Workspace'), 'bilw')
  await userEvent.click(screen.getByRole('button', { name: /Preview/ }))
  await screen.findByText(/1.204.516/)
  expect(screen.getByRole('button', { name: 'Kích hoạt' })).toBeEnabled()
})

it('409 khi kích hoạt bộ còn lỗ giá — hiện nguyên văn message của BE', async () => {
  luuToken('t'); dat409('BO_GIA_CON_LO', 'còn tổ hợp chưa có giá')
  bootPricing(); await moPanelBoGia('Nháp Q4/2026')
  /* … preview rồi bấm kích hoạt … */
  expect(await screen.findByText(/còn tổ hợp chưa có giá/)).toBeInTheDocument()
})
```

⚠️ Mã lỗi `BO_GIA_CON_LO` là **giả định** — mở `src/portal/modules/billing/service.py::kich_hoat` đọc mã thật rồi sửa test. Đừng đoán.

- [ ] **Step 2: Chạy để chắc đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx`
Expected: FAIL 5 bài mới.

- [ ] **Step 3: Viết panel**

Đầu panel: `name` · `code` · pill trạng thái · nút «Preview» + «Kích hoạt».

**Bộ chọn Workspace** — bắt buộc, vì `preview` cần `tenant`. Lấy danh sách từ `useSession()` (`lib/session.tsx` đã có `workspaces`), `<select class="o-chon">`.

Preview: gọi `usePreview(pb, tenant)` → `{chiPhi, currency}` (⚠️ camelCase). So với **tổng hiện tại của cùng tenant** lấy từ `/billing/summary` (kỳ 30 ngày). Hiện: `cũ → mới → Δ (±%)`. **Không có bảng tách component** — không có nguồn.

Form thêm dòng: `component` → `metric` tự thu hẹp từ `metricCua()`; `wall_ms` `disabled` nếu đã chọn `audio_sec` cho STT (và ngược lại) — dùng `STT_THOI_LUONG`; đơn vị hiện thành chữ từ `basisCua().dvi`; `perUnits` lấy từ `basisCua().per_units`, người dùng không nhập tay. Hàng nút theo `HANG_NUT`.

`unitPrice` gửi lên là **chuỗi** (giữ nguyên chữ người gõ) — đừng `Number()`, đó là tiền.

- [ ] **Step 4: Chạy test + commit**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx
git add src/features/billing/components/PanelBoGia.tsx tests/billing-gia.test.tsx
git commit -m "feat(billing): panel bộ giá — form sinh từ pricing_basis + preview per-tenant"
```

---

