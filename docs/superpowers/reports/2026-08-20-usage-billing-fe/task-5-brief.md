### Task 5: Explorer — một bảng, ba chiều gộp

**Files:**
- Create: `src/features/billing/components/BangLuotDung.tsx`
- Modify: `src/features/billing/components/UsageScreen.tsx`
- Test: `tests/billing-usage.test.tsx` (thêm)

**Interfaces:**
- Consumes: `useTheoKey`/`useTheoOwner`/`usePhien` (Task 3), `NhomTab`/`TheBang`/`TD` (`components/ui/Bang.tsx`)
- Produces: `<BangLuotDung gop={...} ky={...} onMoPhien={...} />`

**Làm chiều «Khoá» TRƯỚC** — nó có luật khắt khe nhất (§9.1), hai chiều còn lại là biến thể.

- [ ] **Step 1: Viết test — bài quan trọng nhất là hàng «Chưa phân loại»**

```tsx
it('③ hàng «Chưa phân loại» GHIM CUỐI và không có cách nào ẩn nó', async () => {
  boot('/usage')
  const hang = await screen.findAllByRole('row')
  const nhan = hang.map((r) => r.textContent ?? '')
  const i = nhan.findIndex((t) => t.includes('Chưa phân loại'))
  expect(i).toBeGreaterThan(-1)
  // ghim cuối: chỉ còn hàng Tổng sau nó
  expect(nhan.slice(i + 1).filter((t) => !t.includes('Tổng kỳ'))).toHaveLength(0)
  // không có control nào lọc bỏ nó
  expect(screen.queryByRole('checkbox', { name: /chưa phân loại|ẩn/i })).toBeNull()
})

it('hàng Tổng dùng chi_phi_tong của API, KHÔNG tự cộng', async () => {
  // fake trả chi_phi_tong LỆCH cố ý so với tổng các hàng
  datApi({ by_key_tong_lech: true })
  boot('/usage')
  // phải hiện số của API (999.999), không phải tổng tự cộng
  expect(await screen.findByText('999.999')).toBeInTheDocument()
})

it('đổi chiều gộp KHÔNG đổi kỳ, và ghi vào URL', async () => {
  const r = boot('/usage')
  await screen.findByText('K-prod-web')
  await userEvent.click(screen.getByRole('tab', { name: /Người tạo/ }))
  expect(await screen.findByText('quan.tm@greenpark.vn')).toBeInTheDocument()
  expect(r.state.location.search).toMatchObject({ gop: 'nguoi', ky: 'thang-nay' })
})

it('cột voice_sec KHÔNG có ở bảng chính (không cộng chéo component)', async () => {
  boot('/usage')
  await screen.findByText('K-prod-web')
  expect(screen.queryByRole('columnheader', { name: /voice|thời lượng/i })).toBeNull()
})

it('exact=true KHÔNG có badge; chỉ false mới có', async () => {
  boot('/usage', { gop: 'phien' })
  await screen.findByText('ph_8f3c1a7e94b2')
  expect(screen.getAllByText('Đo thiếu')).toHaveLength(2) // fixture có 2 phiên exact=false
})
```

- [ ] **Step 2: Chạy để chắc đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-usage.test.tsx`
Expected: FAIL 5 bài mới.

- [ ] **Step 3: Chiều «Khoá»**

Cột: `Khoá` (`label` + `key_prefix` mono; `da_thu_hoi` → pill «Đã thu hồi») · `Người tạo` (`nguoi_tao_ten ?? nguoi_tao`, rỗng → `—`) · `Phiên` · `Token in` · `Token out` · `Cache read` (0 → `—` mờ) · **`Chi phí`** (`font-semibold`, sắp giảm mặc định).

Hàng `agent_key_id === null`: nhãn **`NHAN_CHUA_PHAN_LOAI`** = `'Chưa phân loại (không có khoá)'` — chuỗi này BE cũng khai làm hằng, giữ y nguyên. `bg-fill`, `text-muted`, ghim CUỐI bằng cách sort đưa `null` xuống đáy **sau mọi lần đổi sắp xếp**. `title` = «Usage được ghi trước khi phiên có hàng conversations — chưa quy được về khoá nào.»

Hàng chân: **`chi_phi_tong` của API**. Nếu `Σ items.chi_phi !== chi_phi_tong` (so bằng chuỗi sau khi chuẩn hoá) thì hiện thêm một dải cảnh báo — đó là tín hiệu lỗi, không phải chuyện làm tròn.

**Không có cột `voice_sec`** — §9.2.

- [ ] **Step 4: Chiều «Người tạo» + «Phiên»**

«Người tạo»: `Người` · `Email` (sans, KHÔNG mono — email là chữ của người) · `Số khoá` · `Phiên` · `Chi phí`.

«Phiên»: `Phiên` (`session_id` mono, cắt 12 ký tự + `title` đủ) · `Khách` (`customer_name ?? phone ?? —`) · `Kênh` (`<ChipKenh/>` từ `components/ui/ChipKenh.tsx` — **không tự nhuộm**) · `Bắt đầu` (`dd/MM HH:mm` mono) · `Lượt` · `Token in` · `Token out` · `Chi phí` + pill «Đo thiếu» khi `exact === false`.

Phân trang server-side: `limit = 50`, `offset = (trang-1)*50`, `total` từ API. Nút «Trang sau →» **push** (Back = trang trước); đổi chiều gộp thì `replace` và reset `trang = 1`.

- [ ] **Step 5: Bộ chuyển «Gộp theo»**

Dùng **`NhomTab`** của `components/ui/Bang.tsx`. Ba mục: `Khoá` · `Người tạo` · `Phiên`. Ghi vào search param `gop`.

- [ ] **Step 6: Chạy test**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-usage.test.tsx`
Expected: PASS toàn bộ.

- [ ] **Step 7: Commit**

```bash
git add src/features/billing/ tests/billing-usage.test.tsx
git commit -m "feat(billing): explorer 3 chiều gộp + hàng «Chưa phân loại» ghim cuối"
```

---

