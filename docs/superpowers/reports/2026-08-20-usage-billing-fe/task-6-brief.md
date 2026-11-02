### Task 6: Slide-over chi tiết phiên

**Files:**
- Create: `src/features/billing/components/ChiTietPhien.tsx`
- Modify: `src/features/billing/components/UsageScreen.tsx`
- Test: `tests/billing-phien.test.tsx`

**Interfaces:**
- Consumes: `useChiTietPhien` (Task 3)
- Produces: `<ChiTietPhien sessionId={string} onDong={() => void} />`

- [ ] **Step 1: Viết test**

```tsx
it('ghi_chu_turn hiện NGUYÊN VĂN, không tooltip, không collapse', async () => {
  boot('/usage', { phien: 'ph_8f3c1a7e94b2' })
  const ghi = await screen.findByText(/xấp xỉ/)
  expect(ghi).toBeVisible()
  // không nằm trong title/aria-label
  expect(ghi.closest('[title]')).toBeNull()
  // không có nút bung/gập quanh nó
  expect(ghi.closest('details')).toBeNull()
})

it('event TTS hiện text_units làm cơ sở tính tiền, không phải units', async () => {
  boot('/usage', { phien: 'ph_8f3c1a7e94b2' })
  // fixture: tts units=7 text_units=1115
  expect(await screen.findByText(/1.115 ký tự/)).toBeInTheDocument()
})

it('provider/model rỗng hiện — chứ không ô trắng', async () => {
  boot('/usage', { phien: 'ph_8f3c1a7e94b2' })
  await screen.findByText(/xấp xỉ/)
  // event stt có provider='' model=''
  expect(screen.getAllByText('—').length).toBeGreaterThan(0)
})

it('mở/đóng đi qua search param — deep-link được', async () => {
  const r = boot('/usage', { gop: 'phien' })
  await userEvent.click(await screen.findByText('ph_8f3c1a7e94b2'))
  expect(r.state.location.search).toMatchObject({ phien: 'ph_8f3c1a7e94b2' })
  await userEvent.keyboard('{Escape}')
  expect(r.state.location.search.phien).toBeUndefined()
})
```

- [ ] **Step 2: Chạy để chắc đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-phien.test.tsx`
Expected: FAIL 4 bài.

- [ ] **Step 3: Viết component**

Lớp nổi phải, `min(760px, 94vw)`, `bg-surface`, `shadow-noi`. Ba khối:

1. **Đầu**: `session_id` mono + nút copy · khách · `<ChipKenh/>` · `key_label` · tổng `chi_phi`.
2. **`ghi_chu_turn`** — dải `bg-badge-warn-bg`, ngay dưới đầu, **TRÊN** timeline. Render nguyên văn.
3. **Timeline theo `seq`**, nhóm theo `turn_idx` bằng đường kẻ + nhãn «Lượt N» (KHÔNG accordion — người đối soát cần thấy hết cùng lúc).

Mỗi event: `seq` · `turn_idx` · `component` (chip màu) · `purpose` · `provider/model` (`rong()`) · **số đo theo component** · `chi_phi` (`tienDay`) · `occurred_at`.

**Số đo chọn theo cơ sở tính tiền THẬT** (§0.4):

| component | hiện |
|---|---|
| `llm`/`embed` | `input_tokens → output_tokens`, embed dùng `text_units` |
| `tts` | `text_units` ký tự (KHÔNG `units` — `units` nay là số clause) |
| `stt` | `audio_sec` giây **và** `text_units` ký tự — hai vế ĐỘC LẬP, hiện cả hai |
| `vad`/`speaker_verify`/`call` | `audio_sec` giây |

`chi_phi === '0'` → chữ `text-muted` + pill «Không tính tiền».

Đóng: nút ×, click lớp phủ, `Escape` — cả ba xoá search param `phien`.

- [ ] **Step 4: Chạy test**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-phien.test.tsx`
Expected: PASS 4/4.

- [ ] **Step 5: Commit**

```bash
git add src/features/billing/components/ChiTietPhien.tsx src/features/billing/components/UsageScreen.tsx tests/billing-phien.test.tsx
git commit -m "feat(billing): slide-over chi tiết phiên — ghi_chu_turn + cơ sở text_units"
```

---

