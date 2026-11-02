# Spec thiết kế FE — Usage & Billing

> **Bản vẽ:** `public/demo-usage-billing.html` — mở bằng `npm run dev` rồi vào
> `/demo-usage-billing.html`. Đó là bản dựng theo đúng spec này, dùng đúng token
> `styles/theme.css` và font tự host trong `public/fonts/`.
>
> Đối tác BE: `odyssey-portal-backend/docs/superpowers/plans/2026-08-19-usage-billing.md`
> (Task 5 → 11) và `docs/build_module_usage&billing/THIET-KE-CHOT.md`.
> Bản demo cũ (`usage-billing-demo.html`, dark theme, 8 hue, 4 tab) đã **bỏ** —
> §2 và §5 nói rõ nó sai ở đâu và luật nào thay nó.
>
> Tài liệu này chốt: đường đi (§1), luật hình thức (§2–§4), từng băng (§5–§8),
> ba điều BE bắt FE phải làm đúng (§9), trạng thái rỗng/lỗi (§10), thứ tự làm (§12).
> Mọi con số về màu/khoảng cách lấy từ `src/styles/theme.css` — spec này KHÔNG
> đặt thêm token mới nào.

---

## 0. Điều màn này phải trả lời

Người dùng mở `/usage` vì đúng ba câu hỏi, theo thứ tự tần suất:

1. «Tháng này tốn bao nhiêu, và có gì bất thường không?» → Tổng quan
2. «Ai/khoá nào tốn?» → Theo khoá / Theo người tạo
3. «Sao phiên này đắt thế?» → Phiên → chi tiết theo lượt

Màn không phải dashboard trưng bày. Nó là **công cụ đối soát tiền**: mỗi con số
trên màn phải truy được xuống tới dòng event sinh ra nó. Mọi quyết định hình thức
dưới đây phục vụ đúng điều đó — không có ô nào chỉ để cho đẹp.

---

## 1. Đường đi & khai báo (3 việc + 1)

Theo luật `src/lib/nav-registry.ts`: thêm màn = 3 việc, không có việc thứ 4.

Ba mục nằm trong **một khối nav có tên «Chi phí»** (`khoi()` của `nav-types.ts`,
trong mảng `Quản trị`), không phải ba mục rời rạc:

| Route | File | Nav | Ghi chú |
|---|---|---|---|
| `/usage` | `src/routes/_app/usage.tsx` | «Lượt dùng» | Một trang cuộn, 3 mục đồng cấp |
| `/usage?phien=<session_id>` | cùng file | — | Chi tiết phiên: **slide-over**, không route riêng |
| `/billing` | `src/routes/_app/billing.tsx` | «Hoá đơn» | Bản vẽ có, endpoint chưa — §11 |
| `/pricing` | `src/routes/_app/pricing.tsx` | «Bảng giá» + badge số lỗ giá | §8 |

**Vì sao «Bảng giá» phải có mặt trong nav** (đảo lại quyết định `inNav: false`
của vòng 1): dải cảnh báo đỏ trên `/usage` nói «3 tổ hợp chưa có giá» rồi trỏ
tới `/pricing`. Một đường dẫn trỏ tới màn **không có đường vào từ giao diện** là
đường cụt: người dùng bấm một lần rồi không bao giờ tìm lại được. Badge trên mục
nav = số dòng `price_coverage_gap`, để việc phải làm nhìn thấy được từ nav.

Ràng buộc còn nguyên: 6 endpoint admin gác bằng `X-Platform-Admin-Token`, không
bằng session portal — nên mục này chỉ hiện cho người có token nền tảng, và §8
vẫn là công cụ vận hành, không phải màn sản phẩm của tenant.

**Việc thứ 4 (bắt buộc, không phải tuỳ chọn):** `src/lib/actions.ts` thêm
`BILLING_READ: 'billing.read'`, rồi sửa `usageNav.requiredActions` từ
`[ACTIONS.WORKSPACE_ADMIN]` → `[ACTIONS.BILLING_READ]`.

**VÌ SAO:** BE gác 5 endpoint tenant bằng `require(ACTIONS.BILLING_READ)`
(Task 6, migration `0944`). Nav đang gác bằng `workspace_admin` — hai bộ điều
kiện khác nhau cho cùng một màn. Hệ quả có thật: một role được cấp `billing.read`
nhưng không phải workspace admin **không thấy mục nav**, dù API trả 200; và
ngược lại một workspace admin không có `billing.read` **thấy mục nav rồi ăn 403**.
Cả hai chiều đều là lỗi im lặng.

**Chuyển `usage` khỏi `mvp: 'deferred'`** trong `src/lib/screens.ts` → `'full'`.
Kéo theo: ô ⑥ «Usage & Billing» của `TongQuanScreen.tsx` đang cố tình chết
(hai badge "Chưa có", không bấm được — xem docstring file đó) nay **được phép
sáng và link tới `/usage`**. Đây là chỗ đã chừa sẵn (span 4, hàng 2), thay tại
chỗ, không xếp lại lưới.

**VÌ SAO chi tiết phiên là slide-over chứ không route riêng:** người dùng tới đó
từ một danh sách đã lọc (kỳ + sắp xếp + trang). Một route mới là mất ngữ cảnh đó
và cần một đường "quay lại" giả. `?phien=` giữ được cả deep-link (dán link cho
đồng nghiệp khi khiếu nại hoá đơn — đây là ca dùng thật) lẫn danh sách phía sau.

---

## 2. Bản demo sai ở đâu — và luật thay nó

Ba lỗi trong `usage-billing-demo.html`, mỗi lỗi một luật cứng.

### 2.1 Chữ số không có nhà — luật «SỐ LÀ MONO»

Demo trộn số vào font sans, cỡ tuỳ ô, canh trái. Bảng số canh trái với font
tỷ lệ (proportional) là **không đọc so sánh được**: `1.204.500` và `987.300`
lệch cột hàng nghìn, mắt phải đọc từng chữ số thay vì so chiều dài.

`theme.css:226` đã ghi thẳng chủ ý: `--font-mono … /* MỌI con số dùng font này */`.

| Loại | Luật |
|---|---|
| Mọi số trong bảng, KPI, chart axis | `font-mono tabular-nums` |
| Cột số trong `<table>` | `text-right`; header cột cũng `text-right` |
| Nhãn, tên khoá, tên khách, chữ mô tả | `font-sans` (mặc định) |
| `session_id`, `key_prefix`, `model`, `provider` | `font-mono`, `text-[12.5px]` |

Không có ngoại lệ "cho đẹp". Một cột số canh trái là một cột hỏng.

### 2.2 Không có thang cỡ chữ — luật «6 BẬC, HẾT»

Demo có ~11 cỡ chữ khác nhau. Thang chốt, chỉ dùng đúng sáu:

| Bậc | Cỡ / weight | Dùng ở |
|---|---|---|
| `t-kpi` | `text-[28px] font-mono font-medium tracking-[-0.01em]` | Số lớn của thẻ KPI |
| `t-kpi-vnd` | `text-[34px] font-mono font-semibold` | **Chỉ** ô «Chi phí kỳ» |
| `t-muc` | `text-[15px] font-semibold` | Tiêu đề thẻ / section |
| `t-than` | `text-[13.5px]` | Thân bảng, nội dung — **cỡ nền của màn** |
| `t-phu` | `text-[12.5px] text-muted` | Đơn vị, phụ đề, meta hàng |
| `t-nhan` | `text-[10.5px] font-semibold uppercase tracking-[0.06em] text-muted-2` | Nhãn cột KPI, nhãn nhóm |

`13.5px` không phải số lạ — nó là cỡ đã chốt của `O_LOC`/`NUT_CHINH`/`NUT_PHU`
trong `components/ui/Bang.tsx`. Màn này ăn theo, không đặt cỡ riêng.

### 2.3 Bố cục trôi theo nội dung — luật «LƯỚI 12 CỘT, KHOẢNG 6px»

Demo để các thẻ tự phình. Luật:

- Lưới ngoài `grid-cols-12 gap-4`. Mọi thẻ ăn theo bội số cột, không `width` tay.
- Khoảng cách chỉ dùng bội số của `4px`: `gap-2` (8) · `gap-3` (12) · `gap-4` (16)
  · `gap-6` (24). Không `gap-[13px]`.
- Padding trong thẻ: `p-4` (thẻ KPI) · `p-5` (thẻ nội dung). Hai giá trị, hết.
- Bảng dùng `TheBang` + `TD`/`TD_PHU` của `Bang.tsx` — **không tự viết `<table>`
  với padding riêng**. Đây là chỗ demo lệch xa nhất so với phần còn lại của portal.
- Bo góc: thẻ/section `rounded-lg` (12px) · chip/pill `rounded` (6px). Không
  `rounded-2xl`, không `rounded-full` cho pill (dùng `PILL` sẵn có).
- Viền: `border border-border` trên nền `bg-surface`. **Không dùng shadow để
  tách thẻ** — hệ "Instrument" là hệ viền; `--shadow-noi` chỉ dành cho lớp nổi
  (dialog, slide-over, dropdown).

---

## 3. Bảng màu — dùng token, không mã hex

Không thêm token mới. Ánh xạ:

| Ý nghĩa | Token |
|---|---|
| Nền trang / mặt thẻ | `bg-bg` / `bg-surface` |
| Đầu bảng, hàng rê vào | `bg-fill` |
| Máng tab pill | `bg-fill-strong` |
| Kẻ giữa hàng bảng | `border-rule` |
| Số tiền, nhấn mạnh chính | `text-fg` |
| Đơn vị, meta | `text-muted` / `text-muted-2` |
| Accent (link, tab đang chọn, cột chart chủ đạo) | `text-ac` / `bg-ac` |
| Cảnh báo **mất doanh thu** (`thieu_gia > 0`) | `bg-badge-alert-bg` `text-badge-alert-fg` |
| Cảnh báo cần biết (`llm_khong_chinh_xac`) | `bg-badge-warn-bg` `text-badge-warn-fg` |
| Trung tính ("Chưa phân loại", "Đã thu hồi") | `bg-badge-neutral-bg` `text-badge-neutral-fg` |
| Chip kênh chat / voice | dùng `<ChipKenh/>` sẵn có — **không tự nhuộm** |

### Màu cho component (dùng ở chart & chi tiết phiên)

Sáu component xuất hiện thật: `llm` · `stt` · `tts` · `embed` · `vad` ·
`speaker_verify` (+ `call`). Không có thang màu categorical trong `theme.css`,
nên **không bịa 7 màu mới**. Cách làm:

- `llm` = `--color-ac` (đậm nhất — nó là phần tiền lớn nhất).
- Các component còn lại: cùng sắc accent, **giảm alpha theo bậc**
  `0.72 / 0.56 / 0.42 / 0.30 / 0.20 / 0.12`, thứ tự cố định theo bảng dưới.
- Component không tính tiền (`vad` khi `units=0`, `call` nếu chốt giá 0) vẽ bằng
  `--color-n5` gạch chéo (`pattern`), **không** dùng sắc accent — mắt phải phân
  biệt được "tốn tiền" và "chỉ đo".

Thứ tự cố định (dùng chung mọi nơi, để màu một component không đổi giữa hai màn):
`llm` → `tts` → `stt` → `embed` → `speaker_verify` → `vad` → `call`.

---

## 4. Định dạng số — một chỗ duy nhất

Tạo `src/features/billing/dinh-dang.ts`. **Mọi** màn gọi qua đây, không format
tại chỗ. Đây là chỗ demo hỏng nhất: cùng một số tiền hiện ba kiểu ở ba ô.

| Hàm | Vào | Ra | Luật |
|---|---|---|---|
| `tien(x)` | `"1204500.4821"` (string từ API) | `"1.204.500"` | VND **0 chữ số thập phân**, `.` phân nghìn. BE không làm tròn ở `rated_usage` (`numeric(20,10)`) — FE làm tròn **để hiện**, và chỉ để hiện |
| `tienDay(x)` | idem | `"1.204.500,4821 ₫"` | Chỉ dùng trong tooltip / chi tiết event |
| `token(n)` | `1204500` | `"1,20 M"` | `< 10 000` hiện nguyên; `≥ 10 000` → `k`; `≥ 1 000 000` → `M`, 2 số lẻ |
| `giay(s)` | `4821.5` | `"1h 20m 21s"` | `< 60` → `"48,2 s"` |
| `phanTram(a, b)` | | `"3,4%"` | 1 số lẻ; `b = 0` → `"—"` |
| `rong(v)` | `''` hoặc `null` | `"—"` | **Bắt buộc** — `provider`/`model` của component audio là `''` (không NULL) |

⚠️ **Tiền đến từ API là `string`, không phải `number`.** `chi_phi` là
`Decimal(20,10)` phía BE. `JSON.parse` vào `number` là mất chính xác trên tổng
lớn. Kiểu FE: `type Tien = string`; mọi phép cộng dùng số nguyên "đồng ×10⁴"
hoặc **không cộng ở FE** (ưu tiên: BE đã trả `chi_phi_tong`, dùng nó).

⚠️ **Không tự cộng `items[].chi_phi` để ra tổng.** BE trả `chi_phi_tong` riêng ở
`DanhSachKeyOut` — dùng nó. Nếu tổng tự cộng ≠ `chi_phi_tong` thì đó là **tín hiệu
lỗi**, không phải chuyện làm tròn: hiện dải cảnh báo, đừng âm thầm lấy số nào.

---

## 5. Cấu trúc màn

### 5.0 Hai tầng điều hướng, và KHÔNG có tầng thứ ba

| Tầng | Chia theo | Cụ thể |
|---|---|---|
| **Nav** (khối «Chi phí») | ba **màn** ngang hàng | `Lượt dùng` · `Hoá đơn` · `Bảng giá` |
| **Bộ chuyển trong trang** | **chiều gộp** của cùng một bảng | `Khoá` · `Người tạo` · `Phiên` |

**Không có tab bar trong trang.** Vòng 3 từng có, và nó là một lỗi thật: nav
hiện 3 mục còn tab bar hiện 2 mục — **hai bộ điều hướng cho cùng một việc**, và
mục thứ ba (`Bảng giá`) không có chỗ nào trong tab bar để bấm. Một tab bar chỉ
lặp lại 2 trong 3 mục nav thì luôn thiếu một chỗ.

Chọn nav, vì:
- Ba màn là **ba route** — deep-link được, `requiredActions` khai riêng từng
  `NavLeaf`, và mục `Bảng giá` chỉ hiện cho người có token nền tảng. Tab trong
  trang không làm được cả ba việc đó.
- Đúng khuôn `nav-registry.ts`: một `khoi()` với ba `NavLeaf` — không phải sửa
  `components/shell/*`.

**4 tab của bản nháp đầu vẫn bị bỏ**, và không quay lại: chúng chẻ **một** câu
hỏi («kỳ này tốn ở đâu») thành bốn chỗ. Ba mục nav ở đây là ba **loại tài liệu**
khác nhau — số đo đang chạy · chứng từ đã chốt · cấu hình giá — người dùng tới
vì ba lý do khác nhau, và gần như không bao giờ cần hai cái cùng lúc.

Trong màn «Lượt dùng» **không có tab con nào**: ba mục xếp dọc trên một trang.

### 5.1 `/usage` — một trang cuộn, ba mục ĐỒNG CẤP

**Tiêu đề mục nằm NGOÀI thẻ.** Vòng 2 để tiêu đề bên trong thẻ, và trang đọc
như «một dàn thẻ rồi hết» — không ai kéo xuống thấy bảng ③. Nay mỗi mục có
nhãn số + tiêu đề `16px` + một dòng phụ, cùng một cấp, nên trang đọc như một
**danh sách còn tiếp**. Thêm: mục ② khống chế chiều cao (`min-height:230px` cho
vùng chart) để mép bảng ③ nhô lên trên nếp gấp ở 1080p.

```
┌ nav ────────┬────────────────────────────────────────────────────────────┐
│ QUẢN TRỊ    │ Chi phí                              [Green Park]         │ topbar
│  Người dùng ├────────────────────────────────────────────────────────────┤
│  Tích hợp   │ ‹Lượt dùng›  Hoá đơn ³                                     │ tab trang
│  Nhật ký    ├────────────────────────────────────────────────────────────┤
│ ─ CHI PHÍ ─ │ Kỳ:(Tháng này)(Tháng trước)(7n)(30n) 01/08–20/08     [CSV] │
│  ▸Lượt dùng │ ⚠ 3 tổ hợp chưa có giá — đang tính 0 đồng.  [Bảng giá →]   │ dải đỏ
│   Hoá đơn   │ [148 LLM đo thiếu][12 không số đo][2 nhãn chưa phân loại]  │ dải vàng
│   Bảng giá ³│                                                            │
│             │ ① Kỳ này  ← tiêu đề NGOÀI thẻ, cấp 16px                    │
│             │ ┌CHI PHÍ KỲ─┐┌TOKEN────┐┌PHIÊN────┐┌KHOÁ HOẠT ĐỘNG┐        │
│             │ │1.204.516 ₫││ 12,04 M ││   482   ││  7 / 9 khoá  │        │
│             │ └───────────┘└─────────┘└─────────┘└──────────────┘        │
│             │                                                            │
│             │ ② Tiền đi đâu — trái: khi nào · phải: cái gì               │
│             │ ┌ Chi phí theo ngày ─────────────┐┌ Theo component ──────┐ │
│             │ │      ╱‾╲    ╱‾‾╲    ╱‾╲        ││ LLM     742.200 61,6%│ │
│             │ │  ╱‾╲╱   ╲__╱    ╲__╱   ╲   ─TB ││ TTS     231.418 19,2%│ │
│             │ │ ▁▁▁▁▁▁▁▁▁ vùng tô ▁▁▁▁▁▁▁▁▁▁▁▁ ││ STT     154.303 12,8%│ │
│             │ │ 01    05    10    15    20     ││ …  VAD 0 ₫ không tính│ │
│             │ └────────────────────────────────┘└──────────────────────┘ │
│             │                                                            │
│             │ ③ Lượt dùng chi tiết   [tìm…] (Khoá)(Người tạo)(Phiên)    │
│             │ ┌────────────────────────────────────────────────────────┐ │
│             │ │ KHOÁ       NGƯỜI TẠO  PHIÊN  IN  OUT CACHE  CHI PHÍ ▾  │ │
│             │ │ K-prod-web Trần M.Quân  187 2,81M …        400.491     │ │
│             │ │ Chưa phân loại (không có khoá) ← ghim cuối, không ẩn   │ │
│             │ │ Tổng kỳ                              1.204.516 ₫      │ │
│             │ └────────────────────────────────────────────────────────┘ │
└─────────────┴────────────────────────────────────────────────────────────┘
              bấm một hàng phiên → slide-over chi tiết (?phien=…)
```

**Bộ chuyển «Gộp theo» KHÔNG phải tab.** Nó đổi **chiều gộp** của cùng một
bảng, cùng một kỳ, cùng một tổng — không đổi trang, không đổi ngữ cảnh, không
có nội dung nào bị ẩn đi mất. Đây là khác biệt thật, không phải cách gọi khác:
tab hứa «có thứ khác ở đằng sau», bộ chuyển hứa «cùng thứ đó, xếp lại».
Số lần bấm để thấy 90% màn: **0**.

- **KHÔNG có `<h1>` «Usage»** trong màn. `Topbar` đã render tiêu đề từ
  `usageNav.label` — một `<h1>` thứ hai là chữ trùng (lỗi `/convos` đã sửa
  2026-08-09, và `TongQuanScreen.tsx` ghi lại nguyên si bài học này).
- **Màn này CUỘN** — khác `/dashboard` (khoá trong một khung). Đây là màn bảng,
  và bảng có nhiều hàng. Đừng bắt chước `100dvh - 72px` của `TongQuanScreen`.
- **4 thẻ KPI, không 5.** Demo có 5 và ở 1280px chúng bóp còn ~200px mỗi thẻ,
  số `34px` tràn dòng. Thẻ bị cắt là **«Thời lượng voice»** — vì §9.2: `voice_sec`
  tổng là con số cộng chéo component, và bỏ nó là cách duy nhất không nói dối.
- Bộ chọn kỳ, chiều gộp, trang, phiên đang xem: **tất cả nằm trong URL search
  params** (`?ky=thang-nay&gop=khoa&trang=2&phien=abc`). TanStack Router
  `validateSearch`. Trạng thái không ở URL là trạng thái không dán được cho
  đồng nghiệp — mà đối soát hoá đơn là việc hai người làm cùng nhau.

### Bộ chọn kỳ

Preset: `Tháng này` · `Tháng trước` · `7 ngày` · `30 ngày` · `Tuỳ chọn…`
Mặc định **`Tháng này`** (không phải 7 ngày) — đơn vị của tiền là kỳ hoá đơn.
Cạnh preset hiện luôn khoảng ngày thật đã giải ra, `font-mono t-phu`: người đọc
phải thấy `01/08 – 20/08` chứ không chỉ chữ "Tháng này", vì hôm nay là 20 và
kỳ **chưa đóng**. Kỳ chưa đóng thì thêm chip `Đang chạy` (`badge-neutral`).

### Dải cảnh báo (`canh_bao`)

| Trường | Ngưỡng | Hiện thế nào |
|---|---|---|
| `thieu_gia` | `> 0` | **Đỏ, luôn hiện, không đóng được.** «Thiếu giá: N tổ hợp — đang không tính tiền» + link `/pricing` |
| `event_khong_so_do` | `> 0` | Vàng. «N event không có số đo» |
| `llm_khong_chinh_xac` | `> 0` | Vàng, dạng tỷ lệ. «N event LLM đo thiếu token (x,y%)» |
| `nhan_chua_phan_loai` | `> 0` | Vàng. «N nhãn `purpose` chưa phân loại tính/không tính» |

`thieu_gia` là **đang mất doanh thu**, không phải thông tin nền (hợp đồng BE
Task 11 nói thẳng câu này). Nó là dải đỏ full-width trên KPI, không phải một
badge nhỏ trong góc thẻ như demo đang làm.

`llm_khong_chinh_xac` hiện đúng con số đo được. **Không "bù" bằng ước lượng** và
không có chữ nào gợi ý con số đã được bù.

---

## 6. Băng B — «Tiền đi đâu»

Hai thẻ **cạnh nhau, cùng nhìn thấy** (`7fr / 3fr`): chuỗi theo thời gian bên
trái, phân rã theo component bên phải. Đây là chỗ bản nháp cũ tách thành hai tab
— sai, vì hai câu «tốn vào ngày nào» và «tốn vào cái gì» luôn được hỏi cùng lúc.

### 6.1 Chart: ĐƯỜNG + VÙNG TÔ, không phải cột chồng

**Đảo lại vòng 2 (cột chồng theo component).** Lý do không phải gu: cột chồng mã
hoá `component` **lần thứ hai**, trong khi thẻ «Theo component» ngay bên cạnh đã
làm việc đó và làm tốt hơn — có số, có %, sắp được thứ tự. Hai lần mã hoá cùng
một chiều là hai lần người đọc phải đối chiếu.

Phân công lại cho rõ: **chart trả lời «khi nào», thẻ phải trả lời «cái gì».**
Nhờ vậy chart về đúng một sắc, và chỗ trống thừa ra đủ cho đường trung bình +
mốc cuối tuần mà không rối. Tách component vẫn còn — trong tooltip.

Luật vẽ (đã dựng trong `public/demo-usage-billing.html`):

- **SVG viết tay, không thư viện.** Precedent: `features/ops/components/BieuDoNgay.tsx`
  và `GaugeNuaCung.tsx`. `recharts` ~90 KB gzip cho một chart đường, và nó mang
  theo bảng màu riêng phá §3.
- **⚠️ ĐO container rồi vẽ theo pixel thật, `ResizeObserver` để vẽ lại.**
  KHÔNG `viewBox` cố định. Đây là lỗi bố cục của vòng 2:
  `<svg viewBox="0 0 720 236">` + `height:auto` là **tỷ lệ khoá**; hai thẻ cùng
  hàng grid luôn cao bằng nhau, thẻ «Theo component» cao hơn ⇒ hàng bị kéo cao ⇒
  chart giữ tỷ lệ nên không giãn theo ⇒ **hở một khoảng dưới chart**.
  `height:100%` cũng không cứu: `preserveAspectRatio` sẽ letterbox.
  Vùng vẽ là `flex:1` trong một thẻ `flex-direction:column`.
- **Một sắc accent**: đường `1.75px`, vùng tô gradient `.22 → .02` xuống đáy.
- **Đường trung bình** kẻ đứt `n6` + nhãn `TB`. Mốc so sánh rẻ nhất, và cột
  chồng không có chỗ cho nó.
- **4 vạch ngang mờ** (`border`) + trục đáy (`border-strong`). Không lưới ô vuông.
- **Nhãn ngày chỉ ở mốc 1 · 5 · 10 · 15 · 20.** 20 nhãn liền nhau là trục rối.
- **Cuối tuần nền mờ** (`n3` @55%) — nhìn ra nhịp tuần mà không cần chú thích.
- **Không có hộp legend** trên chart (một sắc thì không cần chú giải).
- **Hover theo CẢ CỘT** (vùng bắt chia đều theo trung điểm): crosshair đứt +
  điểm tròn + tooltip gồm tổng ngày **và** tách component.
- Bàn phím: mỗi vùng cột `tabindex=0`, focus hiện đúng như hover.
- Khi tab bị `hidden` thì `clientWidth = 0` → **vẽ lại lúc tab được mở**, nếu
  không chart ra rỗng.

⚠️ **Chưa có endpoint.** View `billing.cost_by_component_day` có sẵn nhưng 5
endpoint tenant **không có** cái nào trả chuỗi theo ngày. Cần BE thêm
`GET /billing/by-day?tu=&den=` → `[{ ngay, component, chi_phi, so_event }]`.
Đến khi có: thẻ này render `<KhoRong/>` với đúng lý do, **không** vẽ chart từ dữ
liệu suy diễn. Xem §13.1.

### 6.2 Bảng component

6 hàng: `component` · số đo (đơn vị riêng) · `Chi phí` · `%` + thanh tỷ lệ.
Sắp theo chi phí giảm.

**Cột số đo KHÔNG có hàng tổng**, và có chú thích tường minh nói vì sao — §9.2.
Hàng `vad` hiện `0 ₫` + nhãn «không tính tiền», không phải bỏ khỏi bảng: người
dùng thấy `52.910 giây` VAD trong log agent mà không thấy nó ở đây sẽ đi hỏi.

---

## 7. Băng C — Explorer: MỘT bảng, ba chiều gộp

Một thẻ, một `<table>`, một bộ chuyển `Gộp theo: (Khoá) (Người tạo) (Phiên)` ở
góc phải đầu thẻ, cạnh ô tìm. Đổi chiều gộp = đổi `thead` + `tbody`, giữ nguyên
kỳ, ô tìm, và thẻ KPI phía trên.

Bộ chuyển dùng `role="tablist"` cho screen reader (đó là ngữ nghĩa ARIA đúng cho
một bộ chọn kiểu này), nhưng **nhìn** phải là segmented control trong máng
`bg-fill-strong` — không phải hàng tab gạch chân. Tab gạch chân đọc như «đây là
bốn trang», và đó chính là ấn tượng cần tránh.

### Chiều 1 — «Khoá» (mặc định)

`GET /billing/by-key` → `DanhSachKeyOut`

| Cột | Canh | Định dạng |
|---|---|---|
| Khoá | trái | `label` (`t-than`) + `key_prefix` (`font-mono t-phu`) xuống dòng dưới. `revoked` → pill `Đã thu hồi` (`badge-neutral`) |
| Người tạo | trái | `nguoi_tao_ten` ?? `nguoi_tao` ?? `—` |
| Phiên | phải | `số` |
| Token in / out | phải | hai cột riêng, `token()` |
| Cache read | phải | `token()`; `0` hiện `—` (mờ), không hiện `0` |
| Chi phí | phải | `tien()`, **`font-semibold`** — cột này là lý do cả bảng tồn tại |

Sắp xếp mặc định `chi_phi` giảm. Hàng chân bảng: **Tổng** = `chi_phi_tong` từ API.

**Hàng «Chưa phân loại (không có khoá)»**: xem §9.1 — luật cứng.

### Chiều 2 — «Người tạo»

`GET /billing/by-owner` → `Người` · `Email` · `Số khoá` · `Phiên` · `Chi phí`.
Cùng luật canh & định dạng. Cũng có hàng «Chưa phân loại» ghim cuối + hàng Tổng.

### Chiều 3 — «Phiên»

`GET /billing/sessions?limit=&offset=` → `DanhSachPhienOut`

| Cột | Ghi chú |
|---|---|
| Phiên | `session_id` `font-mono t-phu`, cắt còn 12 ký tự + tooltip đủ |
| Khách | `customer_name` ?? `phone` ?? `—` |
| Kênh | `<ChipKenh/>` |
| Bắt đầu | `dd/MM HH:mm`, `font-mono` |
| Turn · Token · Chi phí | phải |
| `exact` | `false` → pill vàng `Đo thiếu` + tooltip. `true` → **không hiện gì** |

**VÌ SAO `exact=true` không có badge:** đúng là mặc định. Một pill xanh trên
mọi hàng là nhiễu, và nó làm hàng `false` khó thấy hơn — đúng ngược mục đích.

Phân trang server-side (`total` từ API), 50 hàng/trang. Bấm hàng → slide-over.

### Slide-over chi tiết phiên (`?phien=`)

Lớp nổi phải, rộng `min(720px, 92vw)`, `bg-surface`, `shadow-noi`. Nội dung:

1. **Đầu**: `session_id` (mono, có nút copy) · khách · kênh · khoá · tổng chi phí.
2. **`ghi_chu_turn` — dải chú thích, luôn hiện.** Xem §9.3. Vị trí: ngay dưới đầu,
   TRÊN timeline, `bg-badge-warn-bg`, `t-phu`. Không phải tooltip, không collapse.
3. **Timeline theo `seq`**: mỗi event một hàng —
   `seq` · `turn_idx` · `component` (chip màu §3) · `purpose` · `provider/model`
   (`—` nếu rỗng) · số đo · `chi_phi` (`tienDay`) · `occurred_at`.
   Nhóm theo `turn_idx` bằng **đường kẻ + nhãn nhóm** (`t-nhan`: «Lượt 3»), không
   phải accordion — người đối soát cần thấy hết cùng lúc.
   Hàng `chi_phi = 0`: chữ `text-muted` + pill `Không tính tiền`.

---

## 8. `/pricing` — «Bảng giá»

Mục nav thứ ba của khối «Chi phí», **chỉ hiện cho người có token nền tảng**:
6 endpoint admin gác bằng header `X-Platform-Admin-Token`, không bằng session
portal — phiên của một tenant user không mang được header đó và sẽ ăn 401.

Ô nhập token ở đầu màn, lưu **`sessionStorage`** (KHÔNG `localStorage` — token
quản trị nền tảng không được sống qua phiên trình duyệt).

### 8.0 DANH SÁCH CHÍNH + ĐÀO SÂU — đảo lại vòng 4

Vòng 4 ném cả bốn việc lên một trang: bảng lỗ giá 8 cột · danh sách bộ giá ·
bảng dòng giá 6 cột · form 5 ô · bảng diff 5 cột · bảng gán workspace · 12 nhãn
purpose — cộng **bốn đoạn chú thích 12,5px** ở chân bảng. Không màn nào đọc
được như thế. **Bỏ.**

Trang chính chỉ giữ **hai** thứ: **① Đang áp** (ba ô) và **② Bộ giá** (một bảng
5 cột). Bốn thứ còn lại là **đào sâu, vào panel**: chi tiết bộ giá · lỗ giá ·
gán workspace · nhãn purpose · doanh thu theo workspace.

**Mỗi ô ở băng ① là MỘT ĐƯỜNG VÀO panel** — con số vừa trả lời câu hỏi vừa là
chỗ bấm để xử lý nó, không có bảng nào phải cuộn qua trước khi tới được việc.

### 8.0b PHÉP THỬ CHO MỘT Ô Ở MÀN CHÍNH — đảo lại vòng 5

Vòng 5 đặt hai **chỉ báo ngoại lệ** vào hai trong ba ô: «Đang mất mỗi kỳ» và
«Nhãn chưa phân loại». **Sai hai lần**, và người dùng chỉ ra đúng:

1. Lúc mọi thứ ổn, chúng chiếm **2/3 chỗ đắt nhất của màn để nói «không có gì»**.
   Đúng thứ luật repo đã cấm ở `/agent`: *«hiện nó thường trực là dạy người dùng
   bỏ qua chỗ đó, để rồi lúc nó thành bất thường thì không ai còn nhìn»*. Tôi
   trích chính câu đó khi thiết kế dòng chất-lượng-đo ở màn Lượt dùng (§5.1), rồi
   vi phạm nó ở đây.
2. `thieu_gia` **đã có dải đỏ riêng ở màn Lượt dùng** ⇒ ô này là bản sao.

**Phép thử đúng: ô này có nói thứ KHÔNG lấy được ở đâu khác?**

| Ô | Qua? | Vì sao |
|---|---|---|
| ① Doanh thu kỳ này (toàn nền tảng) | ✅ | `/usage` chỉ thấy **một** workspace |
| ② Bộ giá mặc định | ✅ | Bảng ② nói bộ nào `active`, không nói bộ nào là **đích rơi về** của phần còn lại |
| ③ Workspace giá riêng | ✅ | Số hợp đồng riêng, không suy được từ đâu |
| ~~Đang mất mỗi kỳ~~ | ❌ | trùng dải đỏ `/usage`, và là ngoại lệ |
| ~~Nhãn chưa phân loại~~ | ❌ | vệ sinh danh mục, không dẫn tới quyết định |

**Ba ô mới:**

| Ô | Giá trị | Mở panel |
|---|---|---|
| Doanh thu kỳ này | `2.231.336 ₫` · `+12,2%` so kỳ trước | Doanh thu theo workspace |
| Bộ giá mặc định | «Chuẩn Q3/2026» + `pv_2026q3_std` | Chi tiết bộ đó |
| Workspace giá riêng | `1 / 4` · 3 dùng bộ mặc định | Gán workspace |

Ô ② mang **TÊN**, nên dùng `font-sans 19px`, không mono: ép tên vào mono chỉ vì
hai ô kia là số thì tên đọc như một mã máy.

Ô ③ đếm «bao nhiêu workspace có **giá riêng**», không phải «bao nhiêu **chưa
gán**». Chưa gán KHÔNG phải lỗi — `resolve_price_version` rơi về `is_default`,
đó là đường đi bình thường; vòng 5 gắn pill cảnh báo vào một trạng thái bình
thường.

### 8.0c Ngoại lệ → DẢI, và dải BIẾN MẤT khi sạch

Lỗ giá + nhãn chưa phân loại chuyển thành **một dải trên băng ①**, cùng khuôn
dải đỏ của màn Lượt dùng (§5): dải đỏ cho `thieu_gia`, một dòng chữ mờ cho nhãn.
**`LO_GIA` rỗng và không nhãn `null` ⇒ cả khối `hidden`** — đó là điều kiện để
nó còn nghĩa lúc xuất hiện.

⚠️ **Lỗ giá KHÔNG phải «quên set giá trước khi cho dùng».** Portal đặt giá, còn
`usage_events` do **agent** ghi. Bên agent thêm một model mới là usage xuất hiện
với cặp `(provider, model)` chưa có dòng giá, `rate_usage()` không khớp được và
trả 0 — **không ai chặn**. Đó là **trôi lệch giữa hai hệ thống**, nên nó phải ồn
ào khi có và im hẳn khi không. Câu trên dải nói thẳng nguyên nhân đó («agent đang
dùng model chưa đặt giá»), không nói «bạn chưa đặt giá».

**Trang chính KHÔNG còn đoạn chữ nhỏ nào.** Chú thích dài chuyển vào panel —
nơi nó đúng ngữ cảnh, đọc lúc đang làm việc đó chứ không phải lúc đang tìm đường.

### 8.0d Ràng buộc nhất quán hai màn

Hàng **Green Park** trong panel doanh thu **bằng đúng** tổng kỳ của màn Lượt
dùng (`1.204.516 ₫`). Cùng một workspace thì hai màn không được nói hai số — ở
màn thật cả hai đọc từ `billing.rated_usage`, nên đây là ràng buộc phải giữ khi
lắp API, không phải mẹo cho khớp bản vẽ.

### 8.1 Băng ② — danh sách bộ giá

`GET /admin/billing/price-versions`. **5 cột, hàng cao `14px`, chữ tên `14px`,
không dòng phụ nào:** `Bộ giá` (tên + `code` mono) · `Trạng thái` (pill, + pill
«Mặc định») · `Dòng giá` · `Workspace` · mũi tên.

Bấm một hàng → panel chi tiết. Nút **«Bộ giá mới»** ở đầu mục.

### 8.2 Panel — chi tiết một bộ giá

Đầu panel: tên · `code` · pill trạng thái · số workspace · hai nút
**«Preview 30 ngày»** và **«Kích hoạt»**.

Thân panel, ba khối có nhãn:

1. **Dải cảnh báo** (chỉ khi bộ đã sinh ra `rated_usage`): «Bộ này đã sinh ra
   tiền — không sửa được. Đổi giá = tạo bộ mới.» Trigger `price_item_bat_bien`
   chặn mọi `UPDATE`; nói trước ở UI, đừng để người dùng phát hiện bằng lỗi 500.
2. **Dòng giá** — bảng **4 cột**, **nhóm theo `component`** bằng hàng nhãn nhóm
   (`Metric` · `Provider/Model` · `Đơn giá` · `Đơn vị`). Nhóm theo component đọc
   được hơn hẳn một bảng 6 cột phẳng: `component` lặp lại ở mọi hàng là một cột
   chỉ để nhìn chứ không để so. Dòng `unit_price · alias `unitPrice` khi GỬI = 0` hiện «không tính tiền».
3. **Thêm dòng giá** — form **chỉ hiện khi bộ CHƯA sinh tiền**. Bày một form
   không gửi được là mời gõ rồi ăn lỗi.

Form **sinh từ `pricing_basis`** (11 dòng): chọn `component` → `metric` tự thu
hẹp, **đơn vị của `unit_price · alias `unitPrice` khi GỬI` hiện thành chữ ngay trong ô nhập** (`đ /1M token`,
`đ /giây`, `đ /ký tự`, `đ /phút`). Nhập giá mà không thấy đơn vị là cách tạo ra
lỗi ×1.000.000.

Hai ràng buộc nói ở UI **trước** khi bấm, không phải sau khi ăn lỗi:
- **STT chỉ MỘT cơ sở.** Đã có `(stt,conversation)/audio_sec` thì
  `(stt,stream)/wall_ms` phải **`disabled`** kèm lý do — DB có unique
  `price_item_stt_single_basis`; đặt giá cả hai là thu tiền STT hai lần.
- Để trống `provider`/`model` = áp cho **mọi** provider; dòng cụ thể hơn thắng
  dòng chung (`price_item_specificity`).

`purpose` không tính khách **không xuất hiện** trong danh sách chọn.
Hàng nút của form **căn phải, nút chính cuối** — `HANG_NUT`, luật 5 Design token.

### 8.3 Preview → kích hoạt

`GET …/{id}/preview` — chạy trong transaction rồi `ROLLBACK`, không ghi dòng nào.
Kết quả chèn vào **đầu thân panel**: tổng bộ đang chạy → tổng bộ này → `Δ` (±%),
kèm bảng chênh lệch **4 cột theo component**.

⚠️ **Tỷ lệ giá phải so KHỚP TỪNG CẶP `(metric, provider, model)`**, không lấy
trung bình đơn giá cả component. Lấy trung bình là: bộ nháp thêm mấy dòng model
rẻ (Gemini) sẽ kéo trung bình xuống và màn báo «LLM **giảm** 16%» trong khi mọi
dòng Anthropic đều **tăng** 9%. Bug đã xảy ra ở bản vẽ, đã sửa.

Dòng giá **mới** (trước là lỗ giá) đi vào **một hàng riêng** «Phủ lỗ giá», không
gộp vào tỷ lệ giá — «tăng giá» và «thu được thứ trước đây cho không» là hai
chuyện, gộp lại là làm mờ cả hai.

Nút **`Kích hoạt` `disabled` cho tới khi preview đã chạy cho ĐÚNG bộ đó trong
phiên hiện tại**. Kích hoạt một bộ giá chưa preview là một phép thử trên tiền thật.

### 8.4 Panel — lỗ giá

`billing.price_coverage_gap`. **4 cột, không phải 8:** `Tổ hợp` (hai dòng:
`component · provider/model` / `metric · purpose`) · `Lượt dùng` (số event + số
đo) · **`Đang mất`** · nút «Đặt giá». Hàng tổng ở chân bảng.

Cột **`Đang mất`** = số đo × giá bộ nháp. **Đây là cột làm bảng này có tác
dụng**: không có nó thì lỗ giá là một cảnh báo kỹ thuật ai cũng bỏ qua; có nó
thì nó là một con số tiền.

### 8.5 Panel — gán workspace

`POST /admin/billing/tenants/{tenantId}/price-version`. 4 cột: `Workspace` ·
`Bộ giá` · `Hiệu lực từ` · nút «Gán». Workspace **chưa gán** hiện pill
«Chưa gán · dùng bộ mặc định», không để trống.

`effectiveFrom` **bắt buộc tz-aware**: input `datetime-local` trả chuỗi naive →
phải tự gắn offset trước khi gửi, không thì asyncpg encode theo giờ HOST (bài
học `occurred_at` của module `ingest`, Change Log 2026-08-15). Bắt và hiện nguyên
văn `message` của hai lỗi 409: `MOC_QUA_KHU_DA_DINH_GIA` · `BO_GIA_CHUA_KICH_HOAT`.

Chú thích trong panel: mốc mới **đóng đúng tại** mốc mở của khoảng cũ — hở thì
usage rơi vào khe không bộ giá nào phủ (miễn phí, âm thầm), chồng thì `EXCLUDE`
chặn (ồn ào, an toàn).

### 8.6 Panel — nhãn purpose

12 nhãn của `billing.purpose` + switch `billable`. Nhãn `null` (chưa phân loại —
agent sinh nhãn mới) hiện nền vàng, switch trạng thái `mixed`, **mặc định không
tính** cho tới khi có người chọn tường minh. Đây là chỗ xử lý cảnh báo
`canh_bao.nhan_chua_phan_loai` của màn Lượt dùng.

**Chạy định giá** — `POST /admin/billing/rate`, nút có xác nhận.

## 9. Ba điều BE bắt FE phải làm đúng — luật cứng

Nguồn: hợp đồng `docs/contracts/usage-billing.md` (Task 11). Không phải gợi ý.

### 9.1 `agent_key_id: null` KHÔNG được ẩn

Hàng nhãn **«Chưa phân loại (không có khoá)»**, ghim **cuối** bảng (sau cả khi
đổi sắp xếp), `bg-fill`, `text-muted`. Tooltip: «Usage được ghi trước khi phiên
có hàng conversations — chưa quy được về khoá nào».

Ẩn nó làm tổng các hàng **thiếu** so với `chi_phi_tong`. Lệch theo hướng thiếu là
hướng tệ: người dùng tin bảng, rồi hoá đơn ra số cao hơn.

Không có nút lọc bỏ nó. Không có `Ẩn hàng rỗng` áp lên nó.

### 9.2 KHÔNG cộng `voice_sec` chéo component

`vad` / `call` / `stt` đo những quãng audio **chồng lấn nhau**. Cộng gộp là tính
một giây 3–4 lần.

Hệ quả cụ thể trong màn này:
- **Không có thẻ KPI «Thời lượng voice»** (§5).
- Bảng «Chi phí theo component» (§6.1) **không có hàng tổng ở cột `Số đo`**.
- Bảng theo khoá: cột `voice_sec` **bỏ hẳn** khỏi bảng chính. Muốn xem thời lượng
  thì mở phiên ra, ở đó nó tách theo component.

⚠️ **Xung đột cần BE xác nhận:** `repo.tong_quan` trả
`voice_sec = sum(ev.audio_sec)` — đó **chính là** một tổng cộng chéo component,
tức endpoint `summary` đang phát ra đúng con số mà hợp đồng cấm hiện. FE **không
render trường này** cho tới khi BE hoặc (a) tách nó theo component, hoặc (b) xác
nhận nó chỉ là số nội bộ. Xem §13.

### 9.3 `ghi_chu_turn` phải hiện

Chuỗi BE trả sẵn trong `ChiTietPhienOut`. Render **nguyên văn**, không rút gọn,
không nhét vào tooltip, không cho collapse.

`turn_idx` của dòng audio là **xấp xỉ** (TTS của lượt N nằm ở lô N+1). Người dùng
đối soát tiền theo từng lượt sẽ thấy lệch, và nếu không có câu này họ kết luận
**hệ thống tính sai** — rồi mở ticket, rồi mất một ngày của cả hai bên.

---

## 10. Trạng thái rỗng · đang tải · lỗi

Dùng component có sẵn, không tự vẽ.

| Tình huống | Làm gì |
|---|---|
| Đang tải lần đầu | Skeleton **đúng hình bảng thật** (4 thẻ KPI + 6 hàng), `bg-fill`, `animate-pulse`. Không spinner giữa màn |
| Đang tải khi đổi kỳ | Giữ dữ liệu cũ + `opacity-60` + `pointer-events-none`. Không về skeleton — nhảy layout khi đổi bộ lọc là mất chỗ đang đọc |
| Kỳ không có usage | `<KhoRong/>` (`ui/TrangThai.tsx`): «Kỳ này chưa có lượt dùng nào» + gợi ý đổi kỳ |
| Lỗi tải | `<LoiTai viec="…" thuLai={refetch}/>` |
| 403 (thiếu `billing.read`) | **Không** hiện `LoiTai`. Hiện thẻ «Bạn không có quyền xem chi phí» + gợi ý liên hệ workspace admin. 403 không phải lỗi mạng, «Thử lại» là nút vô nghĩa |
| Có usage, `chi_phi = 0` toàn bộ | Hiện bảng bình thường **+ dải đỏ**: «Chưa có bộ giá nào áp cho workspace này — mọi dòng đang tính 0». Đây gần như luôn là `thieu_gia`, không phải "dùng miễn phí" |

Ô cuối là ca dễ bỏ sót nhất và tốn nhất: một bảng đầy `0 ₫` trông y như "tháng
này không tốn gì".

---

## 11. Tab «Hoá đơn» — bản vẽ có, endpoint chưa

`billing.invoice` / `invoice_line` có trong migration `0943`, nhưng **không có
endpoint nào** trong 11 endpoint của module. Không có `GET /billing/invoices`,
không có đường phát hành, không có PDF.

Vòng 2 vì thế giữ `/billing` là `ScreenStub`. Vòng 3 **vẽ ra** (theo yêu cầu duyệt
hình thức trước), nhưng có dải vàng nói thẳng «Bản vẽ — chưa có endpoint» ngay
đầu tab. Ranh giới giữ nguyên: **không ship màn này khi chưa có API.** Vẽ trước
để chốt hình thức là hợp lý; ship một màn đọc dữ liệu không tồn tại thì không.

Nội dung đã vẽ (dựng theo đúng schema `0943`):

- **Hoá đơn kỳ hiện tại** — `status` pill (`draft`/`issued`/`paid`/`void`), tổng
  cộng, meta (kỳ · bộ giá áp dụng · đơn vị tiền · lần định giá cuối · số dòng).
- **Bảng dòng hoá đơn** — `(component, provider/model, metric)` →
  `quantity × unit_price · alias `unitPrice` khi GỬI = amount`. Đơn giá `/1M` hiện tường minh cho metric token.
- **Nút `Tính lại` chỉ mở cho kỳ `draft`**, nói ngay trong màn tại sao.
- **Làm tròn VND một lần ở dòng hoá đơn**, ghi ở chân bảng —
  `rated_usage` giữ `numeric(20,10)`, không tròn ở đó.
- **Các kỳ trước** — danh sách gọn: kỳ · trạng thái · bộ giá · tổng · «Xem».
- **«chưa gồm VAT»** cạnh tổng cộng, link tới câu hỏi §13.5. Chưa chốt VAT thì
  câu này phải hiện, không được im.

`src/lib/screens.ts`: giữ `mvp: 'deferred'`, sửa `note` thành «Hoá đơn — bản vẽ
đã duyệt, chờ endpoint `GET /billing/invoices`. Số chi phí đã có ở /usage.»

---

## 12. Thứ tự làm

1. `lib/actions.ts` + `features/deferred/nav.ts` + `lib/screens.ts` — §1. Chạy
   `tests/nav-registry.test.ts`, phải xanh.
2. `features/billing/dinh-dang.ts` + test đơn vị. **Làm trước mọi màn** — đây là
   thứ demo hỏng nặng nhất và là thứ rẻ nhất để chốt.
3. `features/billing/api.ts` — kiểu TS sinh từ `/docs` OpenAPI (đối chiếu tên
   trường thật, spec này chép từ plan BE nên có thể lệch), hook React Query,
   `Tien = string`.
4. MSW handlers cho 5 endpoint tenant (`src/lib/msw/handlers.ts`) — dựng màn
   không cần chờ BE deploy.
5. Khung `/usage`: hàng kỳ + dải cảnh báo + 4 KPI (băng A).
6. Băng C chiều «Khoá» — **làm trước băng B**. Nó là bảng có luật khắt khe nhất
   (§9.1), và làm đúng nó thì hai chiều còn lại chỉ là biến thể của cùng bảng.
7. Băng C chiều «Người tạo» + chiều «Phiên» + slide-over chi tiết (kèm §9.3).
8. Băng B: bảng component (6.2) trước, chart (6.1) sau — chart phụ thuộc
   endpoint §13.1 chưa có.
9. `/pricing` — theo thứ tự ① lỗ giá → ② bộ giá → ③ form → ④ preview → ⑤ gán.
   Làm ① và ② trước: chỉ hai mục đó đã đủ để người vận hành **thấy** vấn đề,
   dù chưa sửa được từ UI.
10. Chart theo ngày — **chỉ khi** endpoint §13.1 có thật.
11. `/billing` (Hoá đơn) — **chỉ khi** có `GET /billing/invoices` (§11).

Bước 2–8 làm được ngay với MSW, không chờ BE.

---

## 13. Cần BE / cần bạn quyết

1. **Endpoint chuỗi theo ngày** — `GET /billing/by-day?tu=&den=` →
   `[{ ngay, component, chi_phi, so_event }]`. Không có nó thì mục ② không có dữ
   liệu (§6.1). Lưu ý FE **lệch có chủ ý** khỏi `THIET-KE-CHOT.md §7a`: bản đó
   yêu cầu «cột chồng theo `component`», FE vẽ **đường tổng**, tách component
   để trong tooltip — lý do ở §6.1 (tránh mã hoá `component` hai lần trên cùng
   một băng). Payload cần vẫn y nguyên: chia theo `component` từng ngày.
2. **`summary.voice_sec` là tổng cộng chéo component** (§9.2) — trái chính hợp
   đồng của BE. Tách theo component, hay xác nhận là số nội bộ không hiện?
3. **Tên query param của kỳ** — plan dùng `tu_ngay`/`den_ngay` ở tầng repo;
   tầng HTTP là `tu`/`den`, `from`/`to`, hay khác? Chốt từ `/docs`.
4. **`canh_bao` nằm trong `/billing/summary` hay endpoint riêng?** `CanhBaoOut` là
   contract riêng, nhưng dải cảnh báo phải render cùng nhịp với KPI — nếu là
   endpoint riêng thì FE gọi song song, không nối tiếp.
5. **VAT** — `THIET-KE-CHOT.md §10` để hở. Nếu `invoice` thêm `vatRate` +
   `totalGomVat` thì `/usage` có phải hiện «chưa gồm VAT» cạnh mọi số tiền
   không? Ảnh hưởng nhãn của KPI «Chi phí kỳ».
6. **`/pricing` có nên nằm ở portal này không?** Nó là màn của nền tảng, không
   của tenant (§8). Phương án khác: tách sang một console nội bộ riêng và bỏ
   route này khỏi portal hẳn. **Đang giả định là để lại** (bản vẽ đã dựng theo
   giả định đó) — nếu tách ra thì §8 chuyển nguyên sang repo console, phần còn
   lại của spec không đổi.
8. **Preview cần BE trả gì?** Bản vẽ đang **ước lượng ở FE** (tỷ lệ đơn giá ×
   chi phí đã đo) vì `GET …/preview` chưa có hình dạng chốt. Đề nghị BE trả
   thẳng: `{ cu: {tong, theoComponent[]}, moi: {tong, theoComponent[]},
   phuLoGia: tong }` — FE **không nên** tự nhân tỷ lệ để ra một số tiền, vì
   phép khớp giá thật (`price_item_specificity`) phức tạp hơn bất kỳ ước lượng
   nào ở FE, và ở đây sai số là sai số tiền.
7. **Xuất CSV** — client-side (chỉ trang hiện tại) hay cần endpoint export
   server-side (cả kỳ)? Đối soát tiền thường cần cả kỳ.
