### Task 8: `/pricing` — ba ô + danh sách bộ giá

**Files:**
- Create: `src/features/billing/components/BangGiaScreen.tsx`
- Modify: `src/features/billing/contracts.ts`
- Test: `tests/billing-gia.test.tsx` (thêm)

**Interfaces:**
- Consumes: `useBoGia`/`useTaoBoGia`/`docToken`/`luuToken` (Task 3)
- Produces: `<BangGiaScreen/>`

**Ba ô đã cắt so với bản vẽ** — §0.7. Ô «Doanh thu kỳ này» toàn nền tảng **không có endpoint** (`/billing/summary` là per-tenant qua RLS). Ba ô v1:

| Ô | Nguồn | Ghi chú |
|---|---|---|
| Bộ giá mặc định | `useBoGia()` → `is_default` | tên + `code` |
| Bộ đang áp | `useBoGia()` → đếm `status==='active'` | |
| Tổ hợp chưa có giá | `/billing/summary` → `canh_bao.thieu_gia` | **chỉ số đếm**, không có dòng chi tiết |

- [ ] **Step 1: Viết test**

```tsx
it('thiếu token → màn nói rõ, KHÔNG gọi API admin', async () => {
  sessionStorage.clear()
  const goi = theoDoi('/api/v1/admin/billing/price-versions')
  bootPricing()
  expect(await screen.findByLabelText(/token quản trị nền tảng/i)).toBeInTheDocument()
  expect(goi).not.toHaveBeenCalled()
})

it('có token → danh sách bộ giá, 5 cột, pill Mặc định', async () => {
  luuToken('test-admin-token')
  bootPricing()
  expect(await screen.findByText('Chuẩn Q3/2026')).toBeInTheDocument()
  expect(screen.getByText('Mặc định')).toBeInTheDocument()
})

it('ô «Tổ hợp chưa có giá» là SỐ ĐẾM, không hứa danh sách', async () => {
  luuToken('test-admin-token')
  bootPricing()
  await screen.findByText('Chuẩn Q3/2026')
  // không có nút mở panel lỗ giá — chưa có endpoint trả dòng
  expect(screen.queryByRole('button', { name: /xem lỗ giá|chi tiết lỗ giá/i })).toBeNull()
})
```

- [ ] **Step 2: Chạy để chắc đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx`
Expected: FAIL 3 bài mới.

- [ ] **Step 3: Viết màn**

Dải token đầu màn: một dòng (`text-[12.5px] text-muted`) + `<input type="password" class="o-loc">` + pill trạng thái. **Thiếu token thì KHÔNG gọi API admin** (`enabled: Boolean(docToken())` ở hook).

Mục ①: ba ô, mỗi ô là nút mở panel (ô «Tổ hợp chưa có giá» **không** phải nút — không có gì để mở).
Mục ②: bảng 5 cột `Bộ giá` (name 14px + code 12.5px mono) · `Trạng thái` (pill + pill «Mặc định») · `Tiền tệ` · `Tạo lúc` · mũi tên. Hàng cao `py-3.5`, bấm → panel Task 9.

⚠️ **KHÔNG có cột «Dòng giá» và «Workspace»** — `liet_ke_bang_gia` trả đúng `id, code, name, currency, status, is_default, created_at`. Bản vẽ có hai cột đó; không có nguồn.

Nút «Bộ giá mới» → hộp thoại 3 ô (`code`/`name`/`currency`), hàng nút theo `HANG_NUT`.

- [ ] **Step 4: Chạy test + commit**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx
git add src/features/billing/ tests/billing-gia.test.tsx
git commit -m "feat(billing): màn /pricing — token nền tảng + danh sách bộ giá"
```

---

