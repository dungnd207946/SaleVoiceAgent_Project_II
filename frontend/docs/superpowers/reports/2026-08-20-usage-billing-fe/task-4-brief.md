### Task 4: Khung `/usage` — hàng kỳ, dải cảnh báo, 5 KPI

**Files:**
- Create: `src/features/billing/components/UsageScreen.tsx`
- Create: `src/features/billing/components/DaiCanhBao.tsx`
- Create: `src/features/billing/components/TheKpi.tsx`
- Create: `src/features/billing/ky.ts`
- Modify: `src/routes/_app/usage.tsx`
- Test: `tests/billing-usage.test.tsx`

**Interfaces:**
- Consumes: `useTongQuan` (Task 3), `tien`/`token`/`giay`/`phanTram` (Task 2)
- Produces: `giaiMaKy(ky: TenKy): { from: string; to: string; dangChay: boolean }` · `type TenKy = 'thang-nay' | 'thang-truoc' | '7-ngay' | '30-ngay'`

- [ ] **Step 1: Viết test khung màn (sẽ đỏ)**

```tsx
// tests/billing-usage.test.tsx — phần khung
it('① năm thẻ KPI, và «Thời lượng gọi» đọc voice_sec', async () => {
  boot('/usage')
  expect(await screen.findByText('Chi phí kỳ')).toBeInTheDocument()
  expect(screen.getByText('Thời lượng gọi')).toBeInTheDocument()
  // fixture MSW: voice_sec = 142.44
  expect(screen.getByText('2m 22s')).toBeInTheDocument()
})

it('dải đỏ hiện khi thieu_gia > 0, và KHÔNG đóng được', async () => {
  boot('/usage')
  expect(await screen.findByRole('status')).toHaveTextContent('chưa có giá')
  expect(screen.queryByRole('button', { name: /đóng|bỏ qua/i })).toBeNull()
})

it('dải BIẾN MẤT khi cả bốn con số canh_bao = 0', async () => {
  datApi({ canh_bao: { thieu_gia: 0, nhan_chua_phan_loai: 0, event_khong_so_do: 0, llm_khong_chinh_xac: 0 } })
  boot('/usage')
  await screen.findByText('Chi phí kỳ')
  expect(screen.queryByRole('status')).toBeNull()
})

it('kỳ mặc định là Tháng này, và hiện khoảng ngày THẬT', async () => {
  boot('/usage')
  expect(await screen.findByRole('button', { name: 'Tháng này', pressed: true })).toBeInTheDocument()
  expect(screen.getByText(/\d{2}\/\d{2} – \d{2}\/\d{2}\/\d{4}/)).toBeInTheDocument()
})

it('403 KHÔNG hiện LoiTai — không có nút Thử lại cho một lỗi quyền', async () => {
  datApi403()
  boot('/usage')
  expect(await screen.findByText(/không có quyền xem chi phí/i)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /thử lại/i })).toBeNull()
})
```

Dựng `boot()`/`datApi()` theo khuôn của `tests/quality-list.test.tsx` (file gần nhất về hình dạng: query + router + provider).

- [ ] **Step 2: Chạy để chắc đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-usage.test.tsx`
Expected: FAIL — chưa có `UsageScreen`.

- [ ] **Step 3: `ky.ts`**

```ts
export type TenKy = 'thang-nay' | 'thang-truoc' | '7-ngay' | '30-ngay'

const iso = (d: Date) => d.toISOString().slice(0, 10)

/**
 * Kỳ → khoảng `from`/`to` dạng `YYYY-MM-DD` (BE khai `date`, không datetime).
 * `to` là mốc NỬA MỞ: BE lọc `occurred_at < to`, nên «tháng này» phải trả ngày
 * đầu tháng SAU, không phải hôm nay — trả hôm nay là cắt mất usage của hôm nay.
 */
export function giaiMaKy(ky: TenKy, homNay = new Date()): { from: string; to: string; dangChay: boolean } {
  const y = homNay.getUTCFullYear()
  const m = homNay.getUTCMonth()
  switch (ky) {
    case 'thang-nay':
      return { from: iso(new Date(Date.UTC(y, m, 1))), to: iso(new Date(Date.UTC(y, m + 1, 1))), dangChay: true }
    case 'thang-truoc':
      return { from: iso(new Date(Date.UTC(y, m - 1, 1))), to: iso(new Date(Date.UTC(y, m, 1))), dangChay: false }
    case '7-ngay':
    case '30-ngay': {
      const n = ky === '7-ngay' ? 7 : 30
      const den = new Date(Date.UTC(y, m, homNay.getUTCDate() + 1))
      const tu = new Date(Date.UTC(y, m, homNay.getUTCDate() + 1 - n))
      return { from: iso(tu), to: iso(den), dangChay: true }
    }
  }
}
```

Thêm bài test cho `giaiMaKy` vào `tests/billing-dinh-dang.test.ts`: `giaiMaKy('thang-nay', new Date('2026-08-20T00:00:00Z'))` phải ra `{from:'2026-08-01', to:'2026-09-01'}` — **`to` là 09-01, không phải 08-20**.

- [ ] **Step 4: `route usage.tsx` với `validateSearch`**

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { UsageScreen } from '@/features/billing/contracts'

type Gop = 'khoa' | 'nguoi' | 'phien'
const KY = ['thang-nay', 'thang-truoc', '7-ngay', '30-ngay'] as const

export const Route = createFileRoute('/_app/usage')({
  /**
   * ⚠️ Router TRỘN kết quả validate lên search thô chứ không THAY. Nên phải
   * LUÔN trả cả ba khoá — trả `{}` cho giá trị mặc định thì `?gop=xyz` tới
   * thẳng component nguyên văn và KHÔNG chiều nào mở (bẫy đã sập ở `/projects`,
   * Change Log 2026-08-14).
   */
  validateSearch: (s: Record<string, unknown>) => ({
    ky: (KY as readonly string[]).includes(String(s.ky)) ? (String(s.ky) as (typeof KY)[number]) : ('thang-nay' as const),
    gop: (['khoa', 'nguoi', 'phien'] as string[]).includes(String(s.gop)) ? (String(s.gop) as Gop) : ('khoa' as Gop),
    trang: Number.isFinite(Number(s.trang)) && Number(s.trang) > 0 ? Math.floor(Number(s.trang)) : 1,
    phien: typeof s.phien === 'string' && s.phien ? s.phien : undefined,
  }),
  component: UsageScreen,
})
```

- [ ] **Step 5: `TheKpi.tsx` — NĂM thẻ**

Năm thẻ: `Chi phí kỳ` (t-kpi-vnd, thẻ nhấn) · `Token` (in/out/cache ở dòng chân) · `Phiên` · `Thời lượng gọi` · `Khoá hoạt động`.

⚠️ **Nhãn là «Thời lượng gọi», không phải «Thời lượng voice»** — `voice_sec` chỉ đếm `component='call'` (BE sửa `9d78d04`). Tooltip: «Chỉ thời lượng cuộc gọi. `vad`/`stt`/`tts` đo những quãng audio chồng lấn nên không cộng gộp được.»

Lưới `grid-cols-2 lg:grid-cols-5 gap-3`.

- [ ] **Step 6: `DaiCanhBao.tsx`**

Dải đỏ khi `canh_bao.thieu_gia > 0`: «N tổ hợp chưa có giá — lượt dùng khớp vào đó đang tính 0 đồng» + `<Link to="/pricing">Bảng giá →</Link>`. `role="status"`, không nút đóng.

Ba con số còn lại thành **MỘT dòng chữ mờ** (`text-[12.5px] text-muted`), không hộp, không đậm: «Chất lượng đo: N event LLM đo thiếu token (x,y%) · N event không có số đo · N nhãn purpose chưa phân loại».

Tỷ lệ `llm_khong_chinh_xac` cần mẫu số — **không có** trong `TongQuanOut`. Hiện số tuyệt đối, **đừng bịa mẫu số**; ghi vào §13 là còn thiếu.

Cả khối trả `null` khi bốn con số đều 0.

- [ ] **Step 7: `UsageScreen.tsx` — khung + 3 nhánh trạng thái**

Nhánh: đang tải lần đầu → skeleton đúng hình (5 thẻ + 6 hàng); lỗi 403 → thẻ «Bạn không có quyền xem chi phí» **không có nút Thử lại**; lỗi khác → `<LoiTai/>`; `so_phien === 0` → `<KhoRong/>`.

⚠️ Ca dễ bỏ sót nhất: có usage nhưng `chi_phi === '0'` toàn bộ ⇒ hiện bảng bình thường **+ dải đỏ** «Chưa có bộ giá nào áp cho workspace này — mọi dòng đang tính 0». Một bảng đầy `0 ₫` trông y hệt «tháng này không tốn gì».

Tiêu đề mục ngoài thẻ, cùng cấp (`①` `②` `③` — v1 chỉ có ① và ③, xem §0.7).

- [ ] **Step 8: Chạy test khung**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-usage.test.tsx`
Expected: PASS 5 bài khung + 1 bài `giaiMaKy`.

- [ ] **Step 9: Commit**

```bash
git add src/features/billing/ src/routes/_app/usage.tsx tests/billing-usage.test.tsx tests/billing-dinh-dang.test.ts
git commit -m "feat(billing): khung /usage — 5 KPI + dải cảnh báo + kỳ trong URL"
```

---

