### Task 11: Nối ô ⑥ Dashboard + cập nhật CLAUDE.md

**Files:**
- Modify: `src/features/ops/components/TongQuanScreen.tsx`
- Modify: `CLAUDE.md`
- Test: `tests/overview-man.test.tsx` (sửa)

- [ ] **Step 1: Sửa test ô ⑥**

Ô ⑥ «Usage & Billing» đang cố tình chết (hai badge «Chưa có», không bấm được) vì `/usage` là `deferred`. Nay `usage` là `'full'` ⇒ ô đó **được phép sáng và link tới `/usage`**. Sửa bài test đang khẳng định nó không bấm được.

- [ ] **Step 2: Sửa `TongQuanScreen.tsx`**

Thay hai badge «Chưa có» bằng `<Link to="/usage">`. Giữ **đúng chỗ** (span 4, hàng 2) — không xếp lại lưới. Cập nhật docstring: đoạn nói «`/usage`/`/billing` là `mvp:'deferred'`, không có API nào để gọi» **không còn đúng** cho `/usage`; `/billing` thì vẫn đúng.

⚠️ Ô đó nằm trong lưới «khoá trong một màn, không cuộn» — mọi ô có `overflow-hidden` + `min-h-0`. Thêm `<Link>` vào thì mang `relative z-10` để vẽ trên lớp phủ stretched-link.

- [ ] **Step 3: Cập nhật `CLAUDE.md`**

Thêm một dòng Change Log ngày `2026-08-20` nêu: module `billing` mới · khối nav «Chi phí» 3 mục · **`modules/billing` trả `snake_case` trong khi `modules/ops` trả camelCase — hai module hàng xóm hai quy ước** · `voice_sec` chỉ đếm `component='call'` · `text_units` là cơ sở tính tiền của `tts`/`embed` và vế cộng thêm của `stt` · `pricingBasis.ts` là bản sao viết tay không có cổng parity.

Thêm một mục ngắn «Usage & Billing — hai quy ước JSON» vào thân file: đây đúng loại bẫy mà file đó tồn tại để cảnh báo.

- [ ] **Step 4: `make check` + commit**

Run: `npx eslint . && npx prettier --check src tests && npx tsc -b && NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -5`
Expected: đỏ **đúng baseline** của Task 1 Step 1 (`convos-phien` + `routeTree.gen.ts`), không thêm gì.

```bash
git add src/features/ops/components/TongQuanScreen.tsx CLAUDE.md tests/overview-man.test.tsx
git commit -m "feat(billing): nối ô ⑥ dashboard tới /usage + Change Log"
```

---

## Việc BE còn thiếu — chặn phần nào

Ghi vào spec §13 và gửi BE. Mỗi dòng nói rõ **cắt gì** nếu không có.

| # | Cần | Chặn |
|---|---|---|
| 1 | `GET /billing/by-component?from&to` → `[{component, so_event, chi_phi, input_tokens, output_tokens, cache_read_tokens, audio_sec, text_units}]` | Mục ② bảng «Theo component» |
| 2 | `&theo_ngay=true` cho endpoint trên (hoặc `GET /billing/by-day`) | Mục ② chart theo ngày |
| 3 | `GET /billing/price-gaps` → dòng của `price_coverage_gap` + ước lượng tiền mất | Panel «Lỗ giá»; hiện chỉ có số đếm |
| 4 | `GET /admin/billing/pricing-basis` | Bỏ được `pricingBasis.ts` — bản sao viết tay không cổng parity |
| 5 | `GET /admin/billing/price-versions/{pb}/items` | Panel bộ giá không xem được dòng giá đã nhập |
| 6 | `GET /admin/billing/tenants/{id}/price-version` | Cột «bộ đang áp» của panel gán |
| 7 | `GET /admin/billing/purposes` + `PATCH .../{n}` | Thẻ «Nhãn purpose» |
| 8 | Mẫu số cho `llm_khong_chinh_xac` (tổng event llm) | Dòng chất lượng đo hiện số tuyệt đối, không hiện % |
| 9 | `GET /billing/invoices` + `/{period}` | Màn `/billing` giữ `ScreenStub` |
| 10 | Chốt VAT (`vat_rate` + `total_gom_vat`?) | Nhãn KPI «Chi phí kỳ» có phải ghi «chưa gồm VAT» |

---

## Self-Review

**1. Spec coverage** — §1 nav → Task 1 · §2–4 luật hình thức → ràng buộc toàn cục + Task 2 · §5 khung + KPI → Task 4 · §6 mục ② → **CẮT, §0.7** · §7 explorer → Task 5 · §8 `/pricing` → Task 7–10 (cắt lỗ giá/purpose/dòng giá) · §9 ba luật cứng → Task 5 Step 3 (§9.1), Task 4 Step 5 + Task 6 Step 3 (§9.2), Task 6 Step 1 (§9.3) · §10 rỗng/lỗi → Task 4 Step 7 · §11 hoá đơn → Task 1 Step 6 giữ `deferred` · §12 thứ tự → thứ tự task · §13 → bảng trên.

**2. Placeholder scan** — không còn «TBD»/«handle edge cases». Ba chỗ CỐ Ý để implementer tự tra, mỗi chỗ nói rõ tra ở đâu: hình dạng `NavLeaf` (`lib/nav-types.ts`), khuôn `goi()` (`features/platform/api.ts`), mã lỗi của `kich_hoat` (`service.py`). Đó là chống-đoán, không phải placeholder.

**3. Type consistency** — `Tien = string` xuyên suốt Task 2→10. `giaiMaKy` trả `{from, to, dangChay}` dùng nguyên ở Task 4/5. `PRICING_BASIS`/`metricCua`/`basisCua`/`STT_THOI_LUONG` (Task 7) khớp cách dùng ở Task 9. Kiểu response snake_case ở Task 3 khớp mọi test từ Task 4 trở đi. `docToken`/`luuToken` (Task 3) dùng ở Task 8/9/10. **Một lệch đã sửa:** Task 7 ban đầu ghi 11 dòng `pricing_basis` theo `0943`; `0948` thêm `stt/text_units` ⇒ **12**, bài test đã đổi theo.

---

## Execution Handoff

Plan đã lưu ở `docs/superpowers/plans/2026-08-20-usage-billing-fe.md`. Hai cách chạy:

**1. Subagent-Driven (khuyến nghị)** — mỗi task một subagent mới, review giữa các task, vòng lặp nhanh.

**2. Inline Execution** — chạy trong phiên này qua `executing-plans`, theo lô có checkpoint.
