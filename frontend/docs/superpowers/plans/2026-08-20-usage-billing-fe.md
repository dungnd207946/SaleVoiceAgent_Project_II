# Usage & Billing FE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng màn `/usage` (Lượt dùng) và `/pricing` (Bảng giá) trên 11 endpoint module `billing` đã ship, theo đúng spec thiết kế đã chốt.

**Architecture:** Module mới `src/features/billing/` theo khuôn `features/<module>/` của repo (`api.ts` · `contracts.ts` mặt tiền · `nav.ts` · `components/`). `/usage` là MỘT trang cuộn ba mục đồng cấp, chi tiết phiên là slide-over qua search param. `/pricing` là danh-sách-chính + đào-sâu-vào-panel. Mọi trạng thái màn nằm trong URL search params (TanStack Router `validateSearch`).

**Tech Stack:** React 18 · TanStack Router (file-based) · TanStack Query · Tailwind v4 + `styles/theme.css` · MSW · Vitest + Testing Library.

**Spec:** `docs/product/2026-08-20-usage-billing-fe-spec.md` (đọc CẢ hai — plan lập luận từ spec đó)

**Hợp đồng BE:** `odyssey-portal-backend/docs/contracts/usage-billing.md` — **nguồn sự thật duy nhất về field/route.** BE tự viết nó từ code đã ship ngày 2026-08-20. Đừng suy từ file plan của BE (`docs/superpowers/plans/2026-08-19-usage-billing.md`): brief đó lệch ở nhiều điểm và chính hợp đồng ghi «code thắng».

---

## Global Constraints

- **Node 22**, hoặc Node ≥24 thì `NODE_OPTIONS="--no-experimental-webstorage"` — không có cờ này thì ~210 test đỏ với lỗi trỏ nhầm vào `i18n` (global `localStorage` của Node đè `window.localStorage` của jsdom). Repo KHÔNG có `.nvmrc`.
- **Cổng dev `5273`**, không phải 5173.
- `make check` = `make lint` + `make test`; **`make lint` là BA lệnh** (eslint + prettier + `tsc -b`). **`tsc --noEmit` là cổng RỖNG** ở repo này (tsconfig solution-style, `--listFiles` → 0 file, thoát 0) — typecheck thật là `tsc -b`.
- **Baseline đã đỏ sẵn, KHÔNG phải hồi quy của bạn:** `tests/convos-phien.test.tsx` (1 bài) và `src/routeTree.gen.ts` lệch prettier (tệp SINH, bẩn lại sau mỗi `make routes`). **Chụp `npx vitest run` TRƯỚC khi sửa để có mốc so.**
- **Luật ranh giới module:** `features/billing` chỉ được import `features/billing/…` · `lib/…` · `components/…` · `i18n/…`. Cần thứ của module khác ⇒ import `features/<b>/contracts`. Vi phạm ⇒ `tests/module-boundaries.test.ts` đỏ.
- **Không mã màu nào ngoài `styles/theme.css`.** Không `bg-[#...]`, không `text-[#...]`.
- **Bo góc khoá 3 bậc:** `rounded-sm` 6px (nút nhỏ trong hàng) · `rounded-md` 8px (ô nhập/nút/tab) · `rounded-lg` 12px (thẻ/bảng/hộp thoại). **Không `rounded-[Npx]`.**
- **Mọi `<select>` mang class `o-chon`** — `appearance:none` + mũi tên tự vẽ. WebKit bỏ qua `padding` và ép metric riêng ⇒ màn chỉ hỏng trên Safari của người dùng. Cổng `tests/o-chon.test.ts` quét văn bản `src/`.
- **Hàng nút: hằng `HANG_NUT`** (`components/ui/Bang.tsx`) — căn PHẢI, nút chính CUỐI. Không khai lại `flex … gap-*`.
- **Đường về: hằng `DUONG_VE`** — 13px, sắc `muted`, KHÔNG accent.
- **Hàng tab/segmented: `NhomTab`** (`components/ui/Bang.tsx`). Đừng dựng bộ tab thứ hai.
- **Bảng: `TheBang` + `TD`/`TD_PHU`.** Không tự viết `<table>` với padding riêng.
- **Rỗng/lỗi: `KhoRong` / `LoiTai`** (`components/ui/TrangThai.tsx`).
- **Số dùng `font-mono tabular-nums`, cột số `text-right`** (`theme.css:226`: «MỌI con số dùng font này»).
- **Thang chữ 9 bậc — §0.9.** Không `font-size` inline, không bậc thứ 10. Chạy phép đo ở §0.9 trước mỗi PR.
- **HOÁ ĐƠN (`/billing`) NGOÀI PHẠM VI đợt này** — §0.8. Chỉ giữ `ScreenStub` + `note`.
- **`render(<Component/>)` trần KHÔNG chạy** — thiếu provider. Dùng khuôn `datApi()`/`boot()` có sẵn trong từng file test.
- **`lib/msw/handlers.ts` là bản sao viết tay, KHÔNG có cổng parity.** Đừng lấy hành vi fake làm sự thật về backend.

---

## §0. SÁU SAI LỆCH giữa spec và BE đã ship — đọc trước mọi task

Spec được viết từ **brief lúc lập plan** của BE. Code ship khác ở sáu chỗ. Mỗi chỗ là một lớp lỗi im lặng nếu làm theo spec.

### 0.1 Response là `snake_case`, KHÔNG phải camelCase — nguy hiểm nhất

`_Base` của `modules/billing` chỉ khai `ConfigDict(extra="forbid")`, **không có `alias_generator`**. Trong khi `modules/ops/contracts.py` (màn `/convos`, `/dashboard`) **có** khai alias camelCase.

Hai module hàng xóm, hai quy ước. Copy pattern `res.chiPhiTong` từ màn ops sang đây ra **`undefined`, không phải lỗi** — số biến thành `NaN` rồi hiện `—`, và không có gì đỏ.

| Sai (spec cũ) | Đúng (code ship) |
|---|---|
| `chiPhiTong` | `chi_phi_tong` |
| `agentKeyId` | `agent_key_id` |
| `voiceSec` | `voice_sec` |
| `ghiChuTurn` | `ghi_chu_turn` |
| `canhBao.thieuGia` | `canh_bao.thieu_gia` |
| `nguoiTaoTen` | `nguoi_tao_ten` |

**Ngoại lệ, ở body GỬI LÊN của admin** (không phải response): `DongGiaIn` khai alias camelCase cho **đúng hai** field `unitPrice`/`perUnits` (còn `component`/`purpose`/`provider`/`model`/`metric`/`note` giữ tên thường); `GanBoGiaIn` khai camelCase cho **cả hai** field `priceVersionId`/`effectiveFrom`. **Không có `populate_by_name`** ⇒ gửi `unit_price` bị coi là field lạ và ném `422`.

Và `GET .../preview` trả `{"chiPhi": "...", "currency": "..."}` — camelCase cho đúng một key, vì nó là dict viết tay. **Màn admin là HỖN HỢP, không có quy tắc chung.**

### 0.2 Query param là `from`/`to`, không phải `tu`/`den`

`tu: date | None = Query(None, alias="from")`. Định dạng `YYYY-MM-DD` (kiểu `date`, không phải datetime).

### 0.3 `voice_sec` ĐÃ SỬA ở BE — thẻ KPI voice được phép quay lại

Commit `9d78d04` đổi `voice_sec` ở 4 chỗ trong `repo.py` từ `sum(audio_sec)` mọi component sang `FILTER (WHERE component='call')`. Đo trên fixture: **386,38 cộng chéo vs 142,44 thời lượng gọi thật**.

⇒ Lo ngại §9.2/§13.2 của spec **hết đúng**: `voice_sec` giờ là thời lượng cuộc gọi, không cộng chồng lấn. **Thẻ KPI «Thời lượng gọi» quay lại**, thành thẻ thứ 5. Nhãn phải là **«Thời lượng gọi»** chứ không phải «Thời lượng voice» — nó chỉ đếm `component='call'`.

Luật «không cộng `voice_sec` chéo component» **vẫn còn nguyên** cho phía FE: đừng tự cộng `audio_sec` của các event trong `ChiTietPhienOut`.

### 0.4 `text_units` là cơ sở tính tiền MỚI (migration 0948, 2026-08-20)

Bên agent thêm cột `text_units` (ký tự) và chuẩn hoá `units` = **số lần gọi** cho mọi component. Đổi cơ sở tính tiền:

- `tts`: `units` → **`text_units`** (ký tự vào TTS; `units` nay = số clause synth)
- `embed`: `units` → **`text_units`** (đ/ký tự, không còn đ/đoạn)
- `stt` + `conversation`: **THÊM** vế `text_units` — **ĐỘC LẬP, cộng thêm** vào vế thời lượng (vendor kiểu Soniox thu hai đồng hồ)

⇒ **Luật «STT chỉ MỘT cơ sở» nay HẸP HƠN:** chỉ còn áp cho cặp **thời lượng** (`audio_sec` vs `wall_ms`). `audio_sec + text_units` **ĐƯỢC PHÉP**. Bản vẽ demo và spec §8.2 nói sai điều này — sửa khi làm Task 9.

`EventOut` có `text_units`. Event TTS điển hình: `units=7, text_units=1115`.

### 0.5 `preview` cần `tenant` và chỉ trả MỘT con số

`GET /admin/billing/price-versions/{pb}/preview?tenant=<id>` → `{"chiPhi": "...", "currency": "..."}`.

Hai hệ quả:
1. **Preview là PER-TENANT.** Panel phải có bộ chọn workspace, không preview «toàn nền tảng» như bản vẽ.
2. **Không có tách theo component** ⇒ bảng diff 4 cột theo component trong bản vẽ **không có dữ liệu**. Chỉ hiện được: tổng bộ đang chạy (từ `/billing/summary` của tenant đó) → tổng bộ này → Δ.

Nó là **thuần SELECT** qua `billing.preview_price_version()` (migration `0947`), không nạp/rollback — nên gọi nhiều lần vô hại.

### 0.6 KHÔNG có `POST /admin/billing/rate`

Định giá chạy bằng **CLI** `src/portal/cli/dinh_gia_usage.py` (cron), không phải endpoint. Bỏ nút «Chạy định giá» khỏi màn.

### 0.7 Ba nguồn dữ liệu KHÔNG tồn tại — cắt khỏi v1

| Bản vẽ có | Nguồn thật | Kết luận |
|---|---|---|
| Mục ② «Tiền đi đâu»: chart theo ngày | không có endpoint | **cắt** |
| Mục ② bảng «Theo component» | `TongQuanOut` không tách component | **cắt** |
| Panel «Lỗ giá» 3 dòng + cột «Đang mất/kỳ» | chỉ có `canh_bao.thieu_gia` = **một số đếm** | **chỉ hiện số đếm** |
| Form dòng giá sinh từ `pricing_basis` | bảng DB, không có endpoint | **hardcode + cờ nợ** |
| Thẻ «Nhãn purpose» 12 nhãn + switch | `billing.purpose` không có endpoint | **cắt** |
| `/billing` Hoá đơn | `invoice`/`invoice_line` không có endpoint | **giữ `ScreenStub`** |

Xem §13 để biết đã yêu cầu BE những gì.

**Phạm vi v1 sau khi cắt:** `/usage` mục ① (5 KPI + dải cảnh báo) và mục ③ (explorer 3 chiều + slide-over) — **đầy đủ**. `/pricing`: danh sách bộ giá · tạo bộ · thêm dòng giá · kích hoạt · preview · gán workspace — **đủ để vận hành**, thiếu phần chẩn đoán.

### 0.8 HOÁ ĐƠN NGOÀI PHẠM VI — quyết định của người dùng, không phải hệ quả kỹ thuật

`/billing` (Hoá đơn) **KHÔNG làm trong đợt này.** Người dùng chốt 2026-08-20: để làm sau.

Hai lý do độc lập cùng chỉ một hướng — nên đừng «làm luôn cho gọn» khi thấy endpoint xuất hiện:
1. **Quyết định phạm vi của người dùng.** Đây là lý do chính.
2. Không có endpoint nào (`invoice`/`invoice_line` có ở migration `0943` nhưng 11 route không đọc chúng).

Việc phải làm với `/billing` trong đợt này, **hết:** giữ `ScreenStub`, đặt `mvp: 'deferred'`, đặt `note` (Task 1 Step 6). Mục nav «Hoá đơn» **vẫn khai** (Task 1 Step 3) để khối «Chi phí» đủ ba mục — nhưng nó dẫn tới `ScreenStub`, và đó là đúng: stub nói thật «chưa có», còn một mục nav thiếu thì người dùng không biết nó sẽ có.

Bản vẽ tab Hoá đơn trong `public/demo-usage-billing.html` **giữ lại** làm tài liệu đối chiếu cho đợt sau — cùng lối `public/demo-tong-quan.html` đã đi. Đừng xoá.

### 0.9 LUẬT ĐỒNG CẤP — thang chữ 9 bậc, đo được, không cảm tính

Người dùng phản hồi 2026-08-20: *«các text đồng cấp thì phải có cỡ chữ, style như nhau»*. Đúng, và bản vẽ đã vi phạm — đo được **14 bậc cỡ chữ**, trong đó 9 chỗ là **cùng cấp mà khác cỡ**. Đã sửa về **9 bậc**; đây là thang chốt, và nó là thang của CẢ portal chứ không riêng màn này.

| Bậc | Font / weight | Vai — và CHỈ vai này |
|---|---|---|
| `32px` | mono 600 | Tiền chính của màn (KPI «Chi phí kỳ», tổng hoá đơn) |
| `26px` | mono 500 | KPI khác · ô số ở `/pricing` |
| `20px` | mono 600 / sans 600 | Số nổi bật trong panel · tên bộ giá ở ô số |
| `16px` | sans 600 | Tiêu đề **mục** (ngoài thẻ) VÀ tiêu đề **panel** |
| `15px` | sans 600 | Tiêu đề **thẻ** (`t-muc`) |
| `13.5px` | sans 400 | **CỠ NỀN**: thân bảng · nút · ô nhập · nội dung |
| `12.5px` | sans/mono 400 | Meta · mã định danh · phụ đề · chú thích |
| `11px` | mono 400 | Meta mono nhỏ nhất (tooltip, nhãn nhóm dòng) |
| `10.5px` | sans 600 uppercase | Nhãn cột/nhóm · nhãn trục chart |

`19px` của `.topbar h1` **nằm ngoài** thang này: `components/shell/*` bị cấm sửa (CLAUDE.md), nên đó là con số của người khác.

**Chín chỗ đã sửa — dùng làm danh sách kiểm khi review UI:**

| Lệch | Trước | Sau | Vì sao là lệch |
|---|---|---|---|
| Cỡ nền | `13px` × 13 selector | `13.5px` | `O_LOC`/`NUT_CHINH`/`NUT_PHU` của `Bang.tsx` **là** 13.5 — dùng 13 là lệch khỏi cả portal, không chỉ khỏi màn |
| Tiêu đề mục | `15.5px` | `16px` | Cùng cấp với tiêu đề panel (`16px`); 15.5 chỉ là gõ khác nhau ở hai chỗ |
| Tên hàng bảng | `14px` ở `/pricing` | `13.5px` | Cùng cấp tên khoá ở `/usage`; hai bảng hai cỡ |
| Mã dưới tên hàng | `11.5` vs `12.5` | `12.5px` | Chính xác cùng vai ở hai bảng |
| Số trong panel | `23` / `19` | `20px` | Cùng vai «số nổi bật trong panel» |
| Tổng hoá đơn | `30px` | `32px` | Cùng vai «tiền chính của màn» với `t-kpi-vnd` |
| Chân thẻ KPI | `12px` | `12.5px` | Cùng cấp `t-phu` |
| Hai cột trong hàng event | `11.5` vs `12.5` | `12.5px` | Hai cột cạnh nhau, cùng cấp |
| Nhãn nhóm nav | `11` vs `10.5` | `10.5px` | Cùng vai nhãn viết hoa |

**Ba luật rút ra, áp cho MỌI component của Task 4–10:**

1. **KHÔNG `font-size` inline, không `text-[Npx]` tuỳ ý.** Chỉ 9 lớp trên. Bản vẽ có 3 chỗ inline — đã bỏ hết. Một `font-size` inline là bậc thứ 10 lẻn vào.
2. **Nút nhỏ trong hàng bảng dùng hằng `NUT_HANG`** (`components/ui/Bang.tsx`), không tự đặt `height`/`padding`/`font-size`. Bản vẽ có 2 chỗ inline — đã gom thành một class.
3. **Trước khi mở PR: chạy phép đo, không nhìn bằng mắt.** Mắt không thấy 0,5px, mà 0,5px × 20 chỗ là một màn trông «hơi lộn xộn» mà không ai chỉ được tại sao:

```bash
# Mọi cỡ chữ trong các file vừa viết, gom theo bậc.
# Bậc nào không có trong 9 bậc trên ⇒ hoặc sửa, hoặc thêm vào bảng KÈM lý do.
grep -rhoE 'text-\[[0-9.]+px\]' src/features/billing/ | sort | uniq -c | sort -rn
# Phải RỖNG: không font-size inline nào
grep -rn 'style={{[^}]*fontSize' src/features/billing/ || echo 'OK — không inline'
```

Cùng luật cho **weight**: đậm thật (`600`) chỉ ở bốn chỗ — tiêu đề · cột `Chi phí` · hàng `Tổng` · một cụm trong dải đỏ. Nhấn mạnh trong câu dùng `500` + màu `n10`. Chữ nhỏ viết hoa giữ `600` vì ở 10,5px thì 400 mỏng đến mức khó đọc — đó là **độ đọc**, không phải nhấn mạnh.

---

## File Structure

| File | Trách nhiệm |
|---|---|
| `src/lib/actions.ts` | **Sửa:** thêm `BILLING_READ` |
| `src/lib/screens.ts` | **Sửa:** `usage` → `mvp:'full'`; thêm `pricing`; `billing` giữ `deferred` |
| `src/lib/nav-registry.ts` | **Sửa:** thêm khối «Chi phí» vào mảng `Quản trị` |
| `src/features/billing/nav.ts` | 3 `NavLeaf`: `usageNav` · `billingNav` · `pricingNav` |
| `src/features/billing/dinh-dang.ts` | Định dạng số/tiền/thời lượng — MỘT chỗ duy nhất |
| `src/features/billing/kieu.ts` | Kiểu TS của 11 response, **snake_case**, `Tien = string` |
| `src/features/billing/api.ts` | `goi()` + hook React Query. Không biết JSX |
| `src/features/billing/contracts.ts` | Mặt tiền — module khác chỉ import file này |
| `src/features/billing/components/UsageScreen.tsx` | Khung `/usage`: hàng kỳ + dải + mục ①③ |
| `src/features/billing/components/DaiCanhBao.tsx` | Dải đỏ + dòng chất lượng đo |
| `src/features/billing/components/TheKpi.tsx` | 5 thẻ KPI |
| `src/features/billing/components/BangLuotDung.tsx` | Explorer: 1 bảng, 3 chiều gộp |
| `src/features/billing/components/ChiTietPhien.tsx` | Slide-over `?phien=` |
| `src/features/billing/components/BangGiaScreen.tsx` | `/pricing`: 3 ô + danh sách bộ giá |
| `src/features/billing/components/PanelBoGia.tsx` | Panel: dòng giá + form + preview + kích hoạt |
| `src/features/billing/components/PanelGanWorkspace.tsx` | Panel gán bộ giá cho workspace |
| `src/features/billing/pricingBasis.ts` | 11 dòng `pricing_basis` **hardcode** + cờ nợ |
| `src/routes/_app/usage.tsx` | Route + `validateSearch` |
| `src/routes/_app/pricing.tsx` | Route |
| `src/lib/msw/handlers.ts` | **Sửa:** fake 11 endpoint |
| `tests/billing-dinh-dang.test.ts` | Đơn vị: định dạng |
| `tests/billing-usage.test.tsx` | `/usage`: 3 chiều gộp · «Chưa phân loại» · 403 · rỗng |
| `tests/billing-phien.test.tsx` | Slide-over: `ghi_chu_turn` · `text_units` · `exact` |
| `tests/billing-gia.test.tsx` | `/pricing`: danh sách · form alias camelCase · preview · 409 |

**Không sửa `components/shell/*`.** Không sửa route của người khác.

---

### Task 1: Khai báo màn — 4 việc, cổng `nav-registry` canh

**Files:**
- Modify: `src/lib/actions.ts`
- Modify: `src/lib/screens.ts`
- Create: `src/features/billing/nav.ts`
- Modify: `src/lib/nav-registry.ts`
- Create: `src/routes/_app/pricing.tsx`
- Modify: `src/routes/_app/usage.tsx`
- Modify: `src/features/deferred/nav.ts` (bỏ `usageNav`/`billingNav`)
- Test: `tests/nav-registry.test.ts` (sửa hằng)

**Interfaces:**
- Produces: `ACTIONS.BILLING_READ = 'billing.read'` · `usageNav`/`billingNav`/`pricingNav` từ `features/billing/nav.ts`

- [ ] **Step 1: Chạy suite để có mốc baseline**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -5`
Expected: ghi lại con số (dự kiến 1 fail ở `convos-phien.test.tsx`). **Đây là mốc so — mọi con số sau task này phải đối chiếu vào đây.**

- [ ] **Step 2: Thêm action**

Trong `src/lib/actions.ts`, thêm vào object `ACTIONS`:

```ts
  BILLING_READ: 'billing.read',
```

⚠️ `tests/actions-parity.test.ts` so `lib/actions.ts` với `contracts/actions.json`. Nếu cổng đỏ vì thiếu `billing.read` trong JSON: **copy lại `contracts/actions.json` từ backend** (`make contracts` bên đó rồi copy tay). ĐỪNG sửa `contracts/actions.json` bằng tay.

- [ ] **Step 3: Viết `features/billing/nav.ts`**

```ts
import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

/**
 * Ba màn của khối «Chi phí». Tách khỏi `features/deferred/nav.ts`: hai màn
 * `usage`/`billing` từng nằm ở đó với `requiredActions: [WORKSPACE_ADMIN]` —
 * SAI so với backend, vốn gác 5 endpoint bằng `billing.read`. Hai bộ điều kiện
 * khác nhau cho cùng một màn là lỗi im lặng theo CẢ HAI chiều: role có
 * `billing.read` mà không phải workspace admin thì không thấy nav dù API trả
 * 200; workspace admin không có `billing.read` thì thấy nav rồi ăn 403.
 */
export const usageNav: NavLeaf = {
  kind: 'leaf',
  key: 'usage',
  path: '/usage',
  label: { vi: 'Lượt dùng', en: 'Usage' },
  icon: 'usage',
  requiredActions: [ACTIONS.BILLING_READ],
}

export const billingNav: NavLeaf = {
  kind: 'leaf',
  key: 'billing',
  path: '/billing',
  label: { vi: 'Hoá đơn', en: 'Invoices' },
  icon: 'billing',
  requiredActions: [ACTIONS.BILLING_READ],
}

/**
 * `/pricing` gác bằng `BILLING_READ` ở tầng nav, nhưng 6 endpoint admin của nó
 * xác thực bằng header `X-Platform-Admin-Token`, KHÔNG bằng phiên. Nghĩa là mục
 * này hiện cho người có `billing.read` nhưng chỉ DÙNG ĐƯỢC nếu có token nền
 * tảng — màn tự nói điều đó ở dải đầu trang (Task 8), không giấu.
 */
export const pricingNav: NavLeaf = {
  kind: 'leaf',
  key: 'pricing',
  path: '/pricing',
  label: { vi: 'Bảng giá', en: 'Pricing' },
  icon: 'pricing',
  requiredActions: [ACTIONS.BILLING_READ],
}
```

⚠️ Đọc `src/lib/nav-types.ts` để lấy ĐÚNG hình dạng `NavLeaf` (trường `kind`, tên trường icon) trước khi copy khối trên — đừng tin nguyên văn nếu kiểu đã đổi.

- [ ] **Step 4: Thêm icon**

`src/components/icons.tsx` — thêm 3 khoá vào `LUCIDE`: `usage` → `Activity`, `billing` → `ReceiptText`, `pricing` → `Tags`. Dùng nhánh `LUCIDE` chứ không vẽ tay: repo đã chốt 2026-08-08 rằng vẽ tay theo ảnh chụp ra icon *gần giống*, và gần giống là lựa chọn tệ nhất. `Icon` tự ép `strokeWidth 1.92`.

- [ ] **Step 5: Nối vào nav-registry**

Trong `src/lib/nav-registry.ts`: đổi import `billingNav, usageNav` từ `@/features/deferred/nav` sang `@/features/billing/nav`, thêm `pricingNav`, và thêm một `khoi()` có nhãn «Chi phí» vào `segments` của nhóm `Quản trị`:

```ts
      khoi(usageNav, billingNav, pricingNav),
```

⚠️ Đọc chữ ký `khoi()` trong `nav-types.ts` — khối CÓ NHÃN dùng dạng khác khối không nhãn. Nhãn khối: `{ vi: 'Chi phí', en: 'Cost' }`.

- [ ] **Step 6: `screens.ts`**

`usage`: `mvp: 'deferred'` → `'full'`, xoá `note`.
`billing`: giữ `mvp: 'deferred'`, đổi `note` thành `'Hoá đơn — bản vẽ đã duyệt, chờ endpoint GET /billing/invoices. Số chi phí đã có ở /usage.'`
Thêm dòng mới: `{ key: 'pricing', path: '/pricing', owner: 'M9', mvp: 'full', inNav: true }` — đọc `MODULES` để chọn `owner` đúng, đừng bịa mã module.

- [ ] **Step 7: Route `/pricing`**

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { BangGiaScreen } from '@/features/billing/contracts'

export const Route = createFileRoute('/_app/pricing')({
  component: BangGiaScreen,
})
```

Tạm để `BangGiaScreen` là một component rỗng trong `contracts.ts` để route biên dịch được; Task 8 thay nội dung.

- [ ] **Step 8: `make routes` + chạy cổng nav**

Run: `npx tsr generate && NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/nav-registry.test.ts`
Expected: đỏ ở `RAIL_ORDER`/`PROTOTYPE_SCREENS`/danh sách hoãn. Sửa các hằng trong CHÍNH file test đó cho khớp (mảng `Quản trị` nay có 3 mục mới; danh sách hoãn bớt `usage`).

- [ ] **Step 9: Xanh lại + kiểm không hồi quy**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -5`
Expected: cùng con số fail như Step 1, không thêm. `routeTree.gen.ts` bẩn prettier là **bình thường** (tệp sinh).

- [ ] **Step 10: Commit**

```bash
git add src/lib/actions.ts src/lib/screens.ts src/lib/nav-registry.ts \
        src/features/billing/nav.ts src/features/billing/contracts.ts \
        src/features/deferred/nav.ts src/components/icons.tsx \
        src/routes/_app/pricing.tsx src/routeTree.gen.ts tests/nav-registry.test.ts
git commit -m "feat(billing): khối nav «Chi phí» + action billing.read"
```

---

### Task 2: `dinh-dang.ts` — một chỗ định dạng, có test

**Files:**
- Create: `src/features/billing/dinh-dang.ts`
- Test: `tests/billing-dinh-dang.test.ts`

**Interfaces:**
- Produces: `tien(x: Tien): string` · `tienDay(x: Tien): string` · `token(n: number): string` · `giay(s: number): string` · `phanTram(a: number, b: number): string` · `rong(v: string | null | undefined): string` · `type Tien = string`

**VÌ SAO làm trước mọi màn:** đây là thứ bản demo cũ hỏng nặng nhất (cùng một số tiền hiện ba kiểu ở ba ô) và là thứ rẻ nhất để chốt. Ba màn đều gọi qua đây, không format tại chỗ.

- [ ] **Step 1: Viết test (sẽ đỏ)**

```ts
// tests/billing-dinh-dang.test.ts
import { describe, expect, it } from 'vitest'
import { giay, phanTram, rong, tien, tienDay, token } from '@/features/billing/dinh-dang'

describe('tien', () => {
  it('VND không chữ số thập phân, dấu . phân nghìn', () => {
    expect(tien('1204500.4821')).toBe('1.204.500')
  })
  it('nhận string chứ không number — Decimal(20,10) mất chính xác khi qua number', () => {
    // 9007199254740993 > Number.MAX_SAFE_INTEGER: qua number sẽ thành …992
    expect(tien('9007199254740993')).toBe('9.007.199.254.740.993')
  })
  it('0 vẫn là 0, không phải chuỗi rỗng', () => {
    expect(tien('0')).toBe('0')
  })
})

describe('tienDay', () => {
  it('giữ 4 chữ số thập phân cho tooltip đối soát', () => {
    expect(tienDay('1204500.4821')).toBe('1.204.500,4821 ₫')
  })
})

describe('token', () => {
  it('< 10 000 hiện nguyên', () => expect(token(9999)).toBe('9.999'))
  it('≥ 10 000 rút về k', () => expect(token(48250)).toBe('48 k'))
  it('≥ 1 000 000 rút về M, 2 số lẻ', () => expect(token(1204500)).toBe('1,20 M'))
})

describe('giay', () => {
  it('< 60 hiện giây một số lẻ', () => expect(giay(48.24)).toBe('48,2 s'))
  it('≥ 60 tách giờ/phút/giây', () => expect(giay(4821)).toBe('1h 20m 21s'))
  it('142.44 của fixture BE', () => expect(giay(142.44)).toBe('2m 22s'))
})

describe('phanTram', () => {
  it('một số lẻ', () => expect(phanTram(148, 4352)).toBe('3,4%'))
  it('mẫu 0 ra — chứ không NaN%', () => expect(phanTram(5, 0)).toBe('—'))
})

describe('rong', () => {
  // provider/model của component audio là '' (DEFAULT '', KHÔNG phải NULL)
  it("'' ra —", () => expect(rong('')).toBe('—'))
  it('null ra —', () => expect(rong(null)).toBe('—'))
  it('có giá trị thì trả nguyên', () => expect(rong('anthropic')).toBe('anthropic'))
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-dinh-dang.test.ts`
Expected: FAIL — không import được module chưa tồn tại.

- [ ] **Step 3: Viết `dinh-dang.ts`**

```ts
/**
 * Định dạng số của module billing — MỘT chỗ duy nhất.
 *
 * ⚠️ TIỀN LÀ `string`, KHÔNG phải `number`. `chi_phi`/`chi_phi_tong` phía BE là
 * `numeric(20,10)` và Pydantic serialize `Decimal` thành chuỗi. Parse sang
 * `number` là mất chính xác trên tổng lớn, và mất im lặng — không có gì đỏ.
 * Vì thế `Tien = string` và MỌI hàm ở đây nhận chuỗi.
 *
 * ⚠️ KHÔNG cộng tiền ở FE. BE trả `chi_phi_tong` riêng — dùng nó. Nếu tổng tự
 * cộng ≠ `chi_phi_tong` thì đó là TÍN HIỆU LỖI, không phải chuyện làm tròn.
 */
export type Tien = string

const VI = 'vi-VN'

/** Làm tròn ĐỂ HIỆN, và chỉ để hiện. BE cố ý không làm tròn ở `rated_usage`. */
export function tien(x: Tien): string {
  const [nguyen, le = ''] = x.split('.')
  const lam_tron = Number(le[0] ?? '0') >= 5 ? 1n : 0n
  const n = BigInt(nguyen || '0') + (nguyen.startsWith('-') ? -lam_tron : lam_tron)
  return n.toLocaleString(VI)
}

export function tienDay(x: Tien): string {
  const [nguyen, le = ''] = x.split('.')
  const phan = BigInt(nguyen || '0').toLocaleString(VI)
  return le ? `${phan},${le.padEnd(4, '0').slice(0, 4)} ₫` : `${phan} ₫`
}

export function token(n: number): string {
  if (n >= 1e6)
    return `${(n / 1e6).toLocaleString(VI, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} M`
  if (n >= 1e4) return `${Math.round(n / 1e3).toLocaleString(VI)} k`
  return n.toLocaleString(VI)
}

export function giay(s: number): string {
  if (s < 60) return `${s.toLocaleString(VI, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`
  const t = Math.round(s)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const g = t % 60
  return h ? `${h}h ${m}m ${g}s` : `${m}m ${g}s`
}

export function phanTram(a: number, b: number): string {
  if (!b) return '—'
  return `${((a / b) * 100).toLocaleString(VI, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
}

/** `provider`/`model` của component audio là `''` (DEFAULT '', không NULL). */
export function rong(v: string | null | undefined): string {
  return v ? v : '—'
}
```

- [ ] **Step 4: Chạy test**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-dinh-dang.test.ts`
Expected: PASS 14/14. Nếu bài `9007199254740993` đỏ ⇒ ai đó đã parse qua `Number`; sửa lại dùng `BigInt`.

- [ ] **Step 5: Commit**

```bash
git add src/features/billing/dinh-dang.ts tests/billing-dinh-dang.test.ts
git commit -m "feat(billing): dinh-dang — tiền là string, BigInt không mất chính xác"
```

---

### Task 3: Kiểu + client API + fake MSW

**Files:**
- Create: `src/features/billing/kieu.ts`
- Create: `src/features/billing/api.ts`
- Modify: `src/features/billing/contracts.ts`
- Modify: `src/lib/msw/handlers.ts`

**Interfaces:**
- Consumes: `Tien` (Task 2)
- Produces: `useTongQuan(kyFrom, kyTo)` · `useTheoKey(...)` · `useTheoOwner(...)` · `usePhien(..., limit, offset)` · `useChiTietPhien(sessionId)` · `useBoGia()` · `taoBoGia` · `themDongGia` · `kichHoat` · `usePreview(pb, tenant)` · `ganChoWorkspace` · `KEY_BILLING`

- [ ] **Step 1: Viết `kieu.ts` — snake_case, sinh từ hợp đồng BE**

```ts
import type { Tien } from './dinh-dang'

/**
 * Kiểu của 11 response module `billing`.
 *
 * ⚠️ TẤT CẢ snake_case. `modules/billing` KHÔNG khai `alias_generator`, khác
 * `modules/ops` (màn /convos, /dashboard) vốn CÓ khai alias camelCase. Copy
 * pattern `res.chiPhiTong` từ màn ops sang đây ra `undefined` — không phải lỗi,
 * chỉ là `NaN` hiện thành «—» và không gì đỏ. Nguồn: hợp đồng BE
 * `odyssey-portal-backend/docs/contracts/usage-billing.md` §0.
 */
export interface CanhBao {
  thieu_gia: number
  nhan_chua_phan_loai: number
  event_khong_so_do: number
  llm_khong_chinh_xac: number
}

export interface TongQuan {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  /** Thời lượng `component='call'` — KHÔNG cộng chéo component (BE sửa 9d78d04). */
  voice_sec: number
  so_phien: number
  so_key: number
  chi_phi: Tien
  currency: string
  canh_bao: CanhBao
}

export interface DongKey {
  /** `null` = nhóm «Chưa phân loại (không có khoá)». KHÔNG được ẩn. */
  agent_key_id: number | null
  label: string
  key_prefix: string
  nguoi_tao: string
  nguoi_tao_ten: string | null
  da_thu_hoi: boolean
  so_phien: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  voice_sec: number
  so_event: number
  chi_phi: Tien
}

export interface DanhSachKey {
  items: DongKey[]
  total: number
  chi_phi_tong: Tien
  currency: string
}

export interface DongOwner {
  user_id: string | null
  ten: string | null
  email: string | null
  so_key: number
  so_phien: number
  chi_phi: Tien
}

export interface PhienUsage {
  session_id: string
  agent_key_id: number | null
  key_label: string | null
  customer_name: string | null
  phone: string | null
  channel: string
  bat_dau: string | null
  so_turn: number
  input_tokens: number
  output_tokens: number
  voice_sec: number
  chi_phi: Tien
  exact: boolean
}

export interface DanhSachPhien {
  items: PhienUsage[]
  total: number
}

export interface EventUsage {
  event_id: number
  seq: number
  turn_idx: number | null
  component: string
  purpose: string
  /** `''` ở component audio (DEFAULT '', không NULL) — hiện «—». */
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  audio_sec: number
  /** `units` nay = SỐ LẦN GỌI cho mọi component (agent chuẩn hoá 2026-08-20). */
  units: number
  /** Ký tự. Cơ sở tính tiền của `tts`/`embed`, và vế CỘNG THÊM của `stt`. */
  text_units: number
  exact: boolean
  chi_phi: Tien
  occurred_at: string
}

export interface ChiTietPhien {
  phien: PhienUsage
  events: EventUsage[]
  ghi_chu_turn: string
}

export interface BoGia {
  id: number
  code: string
  name: string
  currency: string
  status: 'active' | 'inactive'
  is_default: boolean
  created_at: string
}

/** ⚠️ camelCase — dict viết tay ở BE, KHÁC mọi response khác của module. */
export interface PreviewGia {
  chiPhi: Tien
  currency: string
}

/** ⚠️ Body GỬI LÊN: `unitPrice`/`perUnits` phải camelCase, còn lại tên thường.
 *  Không có `populate_by_name` ⇒ gửi `unit_price` sẽ ăn 422. */
export interface DongGiaIn {
  component: string
  purpose: string
  provider: string
  model: string
  metric: string
  unitPrice: string
  perUnits: number
  note: string
}

/** ⚠️ Body GỬI LÊN: CẢ HAI field camelCase. `effectiveFrom` phải tz-aware. */
export interface GanBoGiaIn {
  priceVersionId: number
  effectiveFrom: string
}
```

- [ ] **Step 2: Viết `api.ts`**

Đọc `src/features/platform/api.ts` để copy ĐÚNG khuôn `goi()` (xử lý lỗi `{error:{code,message}}`, ném `LoiApi`) — đừng viết `fetch` trần. Rồi:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type {
  BoGia, ChiTietPhien, DanhSachKey, DanhSachPhien, DongGiaIn,
  DongOwner, GanBoGiaIn, PreviewGia, TongQuan,
} from './kieu'

export const KEY_BILLING = ['billing'] as const

/** Query param của BE là `from`/`to` (alias), KHÔNG phải `tu`/`den`. Kiểu
 *  `date` ⇒ định dạng `YYYY-MM-DD`, không gửi ISO datetime. */
function ky(from: string, to: string): string {
  return new URLSearchParams({ from, to }).toString()
}

export function useTongQuan(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'summary', from, to],
    queryFn: () => goi<TongQuan>(`/billing/summary?${ky(from, to)}`),
  })
}

export function useTheoKey(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'by-key', from, to],
    queryFn: () => goi<DanhSachKey>(`/billing/by-key?${ky(from, to)}`),
  })
}

export function useTheoOwner(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'by-owner', from, to],
    queryFn: () => goi<DongOwner[]>(`/billing/by-owner?${ky(from, to)}`),
  })
}

export function usePhien(from: string, to: string, limit: number, offset: number) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'sessions', from, to, limit, offset],
    queryFn: () =>
      goi<DanhSachPhien>(
        `/billing/sessions?${ky(from, to)}&limit=${limit}&offset=${offset}`,
      ),
    /** Giữ dữ liệu cũ khi đổi trang/kỳ — về skeleton là nhảy layout, mất chỗ đang đọc. */
    placeholderData: (truoc) => truoc,
  })
}

export function useChiTietPhien(sessionId: string | undefined) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'session', sessionId],
    queryFn: () => goi<ChiTietPhien>(`/billing/sessions/${sessionId!}`),
    enabled: Boolean(sessionId),
  })
}

/* ── Admin: header `X-Platform-Admin-Token`, KHÔNG phải cookie phiên ────────
   Token lưu `sessionStorage` — token quản trị nền tảng không được sống qua
   phiên trình duyệt. Cùng lý lẽ `guiFeedbackAgent()` của module platform:
   endpoint này không nhận phiên, nên `goi()` trần không dùng được. */
const KHOA_TOKEN = 'billing.admin.token'
export const docToken = () => sessionStorage.getItem(KHOA_TOKEN) ?? ''
export const luuToken = (t: string) => sessionStorage.setItem(KHOA_TOKEN, t)

async function goiAdmin<T>(duong: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`/api/v1${duong}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Platform-Admin-Token': docToken(),
      ...(init.headers ?? {}),
    },
  })
  const d = await r.json().catch(() => null)
  if (!r.ok) throw Object.assign(new Error(d?.error?.message ?? r.statusText), {
    ma: d?.error?.code ?? String(r.status), status: r.status,
  })
  return d as T
}

export function useBoGia() {
  return useQuery({
    queryKey: [...KEY_BILLING, 'price-versions'],
    queryFn: () => goiAdmin<BoGia[]>('/admin/billing/price-versions'),
  })
}

export function useTaoBoGia() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { code: string; name: string; currency: string }) =>
      goiAdmin<{ id: number }>('/admin/billing/price-versions', {
        method: 'POST', body: JSON.stringify(b),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

export function useThemDongGia(pb: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: DongGiaIn) =>
      goiAdmin<{ id: number }>(`/admin/billing/price-versions/${pb}/items`, {
        method: 'POST', body: JSON.stringify(b),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

export function useKichHoat(pb: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      goiAdmin<{ status: string }>(`/admin/billing/price-versions/${pb}/activate`, {
        method: 'POST',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

/** ⚠️ Preview là PER-TENANT (`tenant` bắt buộc) và trả MỘT tổng, không tách
 *  component. Cửa sổ 30 ngày do BE quyết, FE không truyền được. */
export function usePreview(pb: number | null, tenant: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'preview', pb, tenant],
    queryFn: () =>
      goiAdmin<PreviewGia>(
        `/admin/billing/price-versions/${pb!}/preview?tenant=${encodeURIComponent(tenant)}`,
      ),
    enabled: Boolean(pb && tenant),
    staleTime: 0,
  })
}

export function useGanChoWorkspace(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: GanBoGiaIn) =>
      goiAdmin<{ status: string }>(
        `/admin/billing/tenants/${encodeURIComponent(tenantId)}/price-version`,
        { method: 'POST', body: JSON.stringify(b) },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY_BILLING }),
  })
}
```

⚠️ Import `goi` từ đúng chỗ của repo (đọc một `features/*/api.ts` có sẵn). Nếu repo chưa có helper dùng chung thì copy khuôn của `features/platform/api.ts`, đừng tạo helper thứ hai.

- [ ] **Step 3: Fake MSW cho 11 endpoint**

Thêm vào `src/lib/msw/handlers.ts`. **Fake phải dùng ĐÚNG snake_case** — fake camelCase là mã hoá một hợp đồng SAI, và repo đã có một vòng thiết kế tin ngược vào fake (gotcha `userCount`, sửa ở `f03da45`). Fake `/billing/by-key` phải có **hàng `agent_key_id: null`** và `chi_phi_tong` = tổng đúng các hàng (kể cả hàng null) — không có nó thì bài test §9.1 xanh vô nghĩa.

Fake admin phải **kiểm header** `X-Platform-Admin-Token`, trả `401` khi thiếu — nếu không thì màn `/pricing` chạy dưới MSW mà không bao giờ đi qua nhánh «chưa có token».

- [ ] **Step 4: `contracts.ts` — mặt tiền**

```ts
export type {
  BoGia, CanhBao, ChiTietPhien, DanhSachKey, DanhSachPhien, DongKey,
  DongOwner, EventUsage, PhienUsage, PreviewGia, TongQuan,
} from './kieu'
export { type Tien, tien } from './dinh-dang'
export { UsageScreen } from './components/UsageScreen'
export { BangGiaScreen } from './components/BangGiaScreen'
```

- [ ] **Step 5: Typecheck + suite**

Run: `npx tsc -b && NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -5`
Expected: `tsc -b` sạch; suite cùng con số fail như Task 1 Step 1.

- [ ] **Step 6: Commit**

```bash
git add src/features/billing/ src/lib/msw/handlers.ts
git commit -m "feat(billing): kiểu snake_case + client + fake MSW 11 endpoint"
```

---

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

### Task 10: Panel gán workspace

**Files:**
- Create: `src/features/billing/components/PanelGanWorkspace.tsx`
- Test: `tests/billing-gia.test.tsx` (thêm)

- [ ] **Step 1: Viết test**

```tsx
it('effectiveFrom gửi lên PHẢI tz-aware — datetime-local trả chuỗi naive', async () => {
  luuToken('t'); const body = batBody('POST', '/admin/billing/tenants/bilw/price-version')
  bootPricing(); await moPanelGan()
  await userEvent.type(screen.getByLabelText(/Hiệu lực từ/), '2026-09-01T00:00')
  await userEvent.click(screen.getByRole('button', { name: 'Gán' }))
  const b = await body()
  // BE có field_validator ném 422 nếu tzinfo is None
  expect(b.effectiveFrom).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
  expect(b).toHaveProperty('priceVersionId')
})

it('409 MOC_QUA_KHU_DA_DINH_GIA hiện nguyên văn message', async () => {
  luuToken('t'); dat409('MOC_QUA_KHU_DA_DINH_GIA', 'đã có usage được định giá từ 01/08/2026 trở đi')
  bootPricing(); await moPanelGan()
  /* … gán mốc quá khứ … */
  expect(await screen.findByText(/đã có usage được định giá/)).toBeInTheDocument()
})

it('409 BO_GIA_CHUA_KICH_HOAT cũng hiện, không im', async () => {
  luuToken('t'); dat409('BO_GIA_CHUA_KICH_HOAT', 'kích hoạt bộ giá trước khi gán')
  bootPricing(); await moPanelGan()
  expect(await screen.findByText(/kích hoạt bộ giá trước khi gán/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Chạy để chắc đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx`
Expected: FAIL 3 bài mới.

- [ ] **Step 3: Viết panel**

Bảng: `Workspace` (từ `useSession().workspaces`) · `Bộ giá` (`<select class="o-chon">` các bộ `status==='active'`) · `Hiệu lực từ` (`<input type="datetime-local">`) · nút «Gán».

⚠️ **Gắn offset trước khi gửi:**

```ts
/** `datetime-local` trả `'2026-09-01T00:00'` — KHÔNG có timezone. asyncpg
 *  encode naive theo giờ HOST, và mốc này quyết định khoảng nào áp cho usage
 *  nào (bài học `occurredAt` của module ingest, Change Log 2026-08-15). BE có
 *  `field_validator` ném 422 nếu `tzinfo is None` — nên đây không phải phòng
 *  xa, nó là điều kiện để request đi qua. */
const tzAware = (local: string) => new Date(local).toISOString()
```

⚠️ **KHÔNG có endpoint đọc `tenant_price_version`** — không hiện được «bộ giá đang áp» và «hiệu lực từ» của từng workspace. Cột đó để `—` kèm `title` nói vì sao. Ghi vào §13.

Bắt lỗi: `err.ma === 'MOC_QUA_KHU_DA_DINH_GIA'` hoặc `'BO_GIA_CHUA_KICH_HOAT'` → hiện `err.message` **nguyên văn** (BE viết câu tiếng Việt có hướng xử lý sẵn, đừng viết lại).

- [ ] **Step 4: Chạy test + commit**

```bash
NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-gia.test.tsx
git add src/features/billing/components/PanelGanWorkspace.tsx tests/billing-gia.test.tsx
git commit -m "feat(billing): panel gán workspace — effectiveFrom tz-aware + hai lỗi 409"
```

---

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
