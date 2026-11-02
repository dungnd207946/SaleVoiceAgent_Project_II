### Task 7: `pricingBasis.ts` — bản sao viết tay, có cờ nợ

**Files:**
- Create: `src/features/billing/pricingBasis.ts`
- Test: `tests/billing-gia.test.tsx` (một bài canh)

**Interfaces:**
- Produces: `PRICING_BASIS: readonly Basis[]` · `basisCua(component, metric)` · `metricCua(component)`

**VÌ SAO có file này:** form nhập giá phải sinh từ `billing.pricing_basis` (11 dòng), nhưng **không có endpoint** nào lộ bảng đó ra. Không có lựa chọn khác ngoài hardcode — nên phải hardcode **có cờ**, đúng hạng `lib/tools.ts`/`contracts/*.json`.

- [ ] **Step 1: Viết file**

```ts
/**
 * ⚠️ BẢN SAO VIẾT TAY của `billing.pricing_basis` — 11 dòng hạt giống của
 * migration `0943`, cập nhật theo `0948_billing_text_units` (2026-08-20).
 * KHÔNG có endpoint nào lộ bảng này, nên KHÔNG có cổng parity nào canh nó.
 * Ngày BE thêm một cơ sở tính tiền, file này nói sai mà không gì đỏ, và người
 * vận hành nhập giá vào một metric không tồn tại → dòng giá không bao giờ khớp.
 *
 * ĐÃ YÊU CẦU BE: `GET /admin/billing/pricing-basis`. Xem spec §13.
 * Nguồn khi viết: `docs/build_module_usage&billing/pricing-schema.sql` +
 * commit `f48fc69`.
 */
export interface Basis {
  readonly component: string
  readonly metric: string
  readonly per_units: number
  readonly dvi: string
  /** Một số cơ sở chỉ áp cho một `purpose` cụ thể. */
  readonly purpose?: string
}

export const PRICING_BASIS: readonly Basis[] = [
  { component: 'llm', metric: 'input_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'llm', metric: 'output_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'llm', metric: 'cache_write_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'llm', metric: 'cache_read_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'embed', metric: 'text_units', per_units: 1, dvi: 'đ /ký tự' },
  { component: 'tts', metric: 'text_units', per_units: 1, dvi: 'đ /ký tự' },
  { component: 'stt', metric: 'audio_sec', per_units: 1, dvi: 'đ /giây', purpose: 'conversation' },
  { component: 'stt', metric: 'text_units', per_units: 1, dvi: 'đ /ký tự', purpose: 'conversation' },
  { component: 'stt', metric: 'wall_ms', per_units: 60_000, dvi: 'đ /phút', purpose: 'stream' },
  { component: 'vad', metric: 'audio_sec', per_units: 1, dvi: 'đ /giây' },
  { component: 'speaker_verify', metric: 'audio_sec', per_units: 1, dvi: 'đ /giây' },
  { component: 'call', metric: 'wall_ms', per_units: 60_000, dvi: 'đ /phút' },
]

/**
 * Luật «STT chỉ MỘT cơ sở» — HẸP HƠN so với bản 0943. Từ `0948`, vế `text_units`
 * của STT là ĐỘC LẬP và CỘNG THÊM (vendor kiểu Soniox thu hai đồng hồ), nên chỉ
 * còn cặp THỜI LƯỢNG loại trừ nhau. Index `price_item_stt_single_basis` đã nới
 * theo. Đã kiểm cả hai chiều ở BE: `audio_sec + text_units` ĐƯỢC PHÉP,
 * `audio_sec + wall_ms` BỊ CHẶN.
 */
export const STT_THOI_LUONG = ['audio_sec', 'wall_ms'] as const

export const basisCua = (component: string, metric: string) =>
  PRICING_BASIS.find((b) => b.component === component && b.metric === metric)

export const metricCua = (component: string) =>
  PRICING_BASIS.filter((b) => b.component === component)
```

- [ ] **Step 2: Bài canh luật STT**

```ts
it('STT: audio_sec + text_units ĐƯỢC, audio_sec + wall_ms BỊ CHẶN', () => {
  // luật hẹp hơn từ migration 0948 — không phải "STT chỉ một metric"
  expect(STT_THOI_LUONG).toEqual(['audio_sec', 'wall_ms'])
  expect(metricCua('stt').map((b) => b.metric)).toContain('text_units')
})

it('tts và embed tính theo text_units, KHÔNG theo units', () => {
  expect(metricCua('tts').map((b) => b.metric)).toEqual(['text_units'])
  expect(metricCua('embed').map((b) => b.metric)).toEqual(['text_units'])
})

it('đúng 12 dòng cơ sở', () => expect(PRICING_BASIS).toHaveLength(12))
```

⚠️ **12, không phải 11** — `0943` có 11, `0948` thêm vế `stt/text_units`. Nếu bài này đỏ, mở `pricing-schema.sql` đếm lại, đừng sửa hằng theo cảm giác.

- [ ] **Step 3: Chạy + commit**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx
git add src/features/billing/pricingBasis.ts tests/billing-gia.test.tsx
git commit -m "feat(billing): pricing_basis bản sao viết tay + luật STT hẹp theo 0948"
```

---

