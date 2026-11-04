# Màn «Tổng quan» (`/dashboard`) — thiết kế

**Ngày:** 2026-08-13 · **Màn:** `dashboard` (M7, `features/ops`) · **Quyền:** `ACTIONS.OVERVIEW_READ`
**Phạm vi:** `odyssey-portal-frontend` (màn + primitive biểu đồ) + `odyssey-portal-backend` (một endpoint mới trong `modules/ops`).
**Demo đã duyệt hình:** `public/demo-tong-quan.html` — xoá sau khi chốt.

> **Bản 6.** Bản 1 có 9 ô trên 5 dải và phải cuộn. Người dùng chốt: **mọi thứ trong một màn hình, không cuộn**, và bỏ những ô không phục vụ câu hỏi hằng ngày. Qua sáu vòng, bản này còn **5 ô**. Mọi thứ đã cắt nằm ở §6 kèm lý do — để lần sau không ai thêm lại mà tưởng là sót.

---

## 1. Dữ liệu có thật — cột nào đỡ con số nào

Mọi số trên màn phải truy được về một dòng dưới đây. Không có dòng nào đỡ ⇒ **không lên màn**.

| Ô | Cột nguồn |
|---|---|
| Hội thoại | `conversations` — đếm theo `COALESCE(started_at, created_at)`; chia kênh theo `source` |
| Chuyển sale | `conversations.transferred_to_sales` |
| Khách đánh giá | `agent_feedback.rating` (1–5), `created_at` |
| Kiến thức | `projects` · `zones` · `units` · `documents` — tổng vs `status='published'` |
| Usage & Billing | **chưa có cột nào** — ô giữ chỗ, không gọi API |

### ⚠️ Ba thứ KHÔNG có — cố ý không đưa lên màn

1. **Không có bảng `appointments`.** Nav có «Lịch hẹn» nhưng backend chưa có bảng. Không có KPI lịch hẹn.
2. **Không có cột chi phí/token.** `/usage` · `/billing` đang `mvp: 'deferred'`. Ô ⑥ là **chỗ đã chừa**, hiện đúng như thế — không bịa số.
3. **`conversations.source` NULLABLE, không CHECK** (`0916`) — tập kênh chưa chốt. Biểu đồ kênh **tự sinh chuỗi từ dữ liệu trả về**, không viết cứng danh sách; `NULL` gom vào «Chưa rõ» màu xám, không vứt đi.

---

## 2. Bố cục — 5 ô, khoá trong một màn hình

```
┌ Tổng quan · An Phú Land · 7 ngày        Cập nhật 14:32  [7d|4 tuần|Tất cả] ┐

┌──── Hội thoại ────────5/12┐┌ Chuyển sale ─3/12┐┌ Khách đánh giá ────4/12┐
│ 338 phiên        ▲13,4%   ││                  ││ 4,33 /5      ▼0,08     │
│ ●Chat 166  ●Voice 127     ││      ╭─────╮     ││ ★★★★☆  (sao tô lẻ)     │
│ 40┼──┼──┼──┼──┼──┼──┼──   ││     ╱ 21,6% ╲    ││ 190 lượt đánh giá      │
│ 30│ ╱‾╲__╱‾‾╲__╱‾╲ ▓      ││    ╱  cần    ╲   ││ ─────────────────────  │
│ 20┼╳──┼──┼──┼──┼──┼─▓─    ││   │ người thật│  ││ 5★ ███████████    110  │
│ 10│╱  ‾‾╲__      ╲ ▓      ││                  ││ 4★ ████            48  │
│  0└──┴──┴──┴──┴──┴─▓─     ││ ● Chuyển sale 73 ││ 3★ ██              20  │
│  T6 T7 CN T2 T3 T4 [Hôm  ]││ ○ Tự xử lý   265 ││ 2★ ▌                8  │
│                    [nay  ]││                  ││ 1★ ▏                4  │
└───────────────────────────┘└──────────────────┘└────────────────────────┘

┌──── Kiến thức ──────────────────────────8/12┐┌ Usage & Billing ────4/12┐
│ ┌ DỰ ÁN   67%┐┌ PHÂN KHU 66%┐┌ CĂN   80%┐   ││ ┌─────────────────────┐ │
│ │ 8 / 12     ││ 31 / 47     ││964/1.203 │   ││ │ ▨ Lượng dùng  Chưa  │ │
│ │ ▓▓▓▓▓▓░░░  ││ ▓▓▓▓▓▓░░░   ││▓▓▓▓▓▓▓▓░ │   ││ └─────────────────────┘ │
│ │ ⚠ 4 còn nháp││⚠ 16 chưa PH ││⚠ 239 …   │   ││ ┌─────────────────────┐ │
│ └────────────┘└─────────────┘└──────────┘   ││ │ ▤ Gói cước    Chưa  │ │
│ ┌ TÀI LIỆU 88%┐┌ TỆP KB  95%┐┌ HỒ SƠ 83%┐   ││ └─────────────────────┘ │
│ │ 189 / 214  ││ 36 / 38     ││ 10 / 12  │   ││ Hai màn hoãn ngoài MVP  │
│ └────────────┘└─────────────┘└──────────┘   ││                         │
└─────────────────────────────────────────────┘└─────────────────────────┘
```

**Cơ chế không-cuộn** (không phải ước lượng chiều cao):
`.shell{height:100dvh;overflow:hidden}` → `main` flex column → `.luoi{flex:1;min-height:0;grid-template-rows:1fr 1fr}` → mỗi ô `min-height:0;overflow:hidden` → biểu đồ `position:absolute;inset:0` trong khung `flex:1`.
Ô ① đo **pixel thật** + `ResizeObserver` (lý do ở mục dưới); các hình còn lại là SVG cỡ cố định căn giữa, không cần đo.
`dvh` chứ không `vh` — trên trình duyệt di động `100vh` cao hơn vùng thật sự thấy, và màn "không cuộn" vẫn cuộn được vài chục pixel.
Dưới 1240px: lưới về 2 cột × 3 hàng (vẫn `1fr`, vẫn không cuộn).

### Ô ① Hội thoại — năm vòng, và lý lẽ của vòng cuối

| Vòng | Hình | Vì sao bỏ |
|---|---|---|
| 1 | 30 cột × 4 mảng chồng + đường CSAT trục phải | **120 mark**; ép *hai* câu hỏi vào *một* hình; trục y thứ hai là lỗi biểu đồ phổ biến nhất |
| 2 | Một đường nối 30 điểm | Nối liền biến dao động cuối tuần thành **răng cưa** — mắt đọc răng cưa là "hỗn loạn", không phải "xu hướng" |
| 3 | 30 cột ngày + đường TB động 7 ngày + thanh 4 màu chia kênh | 30 mark quá dày; phải **thêm** đường TB động để cứu — mark thứ hai chữa hậu quả của mark thứ nhất. Và thanh kênh là thống kê **thứ hai** trong ô của thống kê thứ nhất |
| 4 | 4 cột tuần, nhãn số trên đầu cột | Gộp về tuần thì mất hẳn số Chat/Voice riêng — đúng thứ người dùng cần |
| **5** | **Hai đường Chat · Voice trên 7 ngày, dải crosshair, nghỉ ở HÔM NAY** | ✅ |

**HAI đường chứ không một đường tổng.** Người dùng cần Chat và Voice **riêng**; chồng chúng thành tổng rồi bắt tra tooltip là giấu đi đúng thứ được hỏi. Tổng vẫn còn — nó là con số lớn ngay đầu ô, và chú giải mang tổng kỳ của từng kênh.

Zalo OA và «Chưa rõ» **không lên đường thứ ba và thứ tư**: bốn đường trên một khung 7 điểm là một búi chỉ. Chúng đứng ở dòng phụ của chú giải và ở chân tooltip — có mặt, đọc được, không tranh chỗ.

**Dải crosshair, trạng thái nghỉ là HÔM NAY.** Rê chuột bất kỳ đâu trong khung thì bám vào ngày gần nhất (vùng chạm là cả ô — điểm bán kính 4px là mục tiêu quá nhỏ). Rời chuột thì dải **trả về hôm nay**, không đứng lại ở ngày cuối cùng con chuột vô tình đi qua. Nhãn ngày bên dưới là **`<button>` thật**, nên dải với tới được bằng bàn phím và bằng ngón tay.

Ngày đang xem: điểm bán kính 4.5 + vòng nền 2px. Ngày khác: 2.5 và `opacity .35` — đúng yêu cầu «hôm nay đậm, còn lại nhạt».

**Đo bằng PIXEL THẬT, không `preserveAspectRatio="none"`.** Hình này có **điểm tròn**; kéo giãn SVG phi tỉ lệ biến mọi vòng tròn thành bầu dục, và `vector-effect` chỉ cứu được nét chứ không cứu được hình. Component tự đo bề rộng rồi vẽ theo px, vẽ lại qua `ResizeObserver` — ở React là `useRef` + `ResizeObserver`.

#### THANG BĂNG, không phải thang mép-tới-mép — đây là quyết định gốc

Bản đầu đặt `X[i] = PL + i·iw/(N−1)`, tức điểm **đầu và cuối nằm đúng trên biên lưới**. Ba lỗi sinh ra từ đúng một chỗ đó, và người dùng đã chỉ ra cả ba:

| Triệu chứng | Nguyên nhân |
|---|---|
| «Dải xanh thừa ra phía dưới» | Dải vẽ cao `ih + 10` để "thoáng", nhưng lưới chỉ cao `ih` |
| «Cột đầu tiên lệch ra ngoài lưới» | Dải căn giữa quanh điểm biên phải thò một nửa ra ngoài ⇒ phải kẹp; kẹp xong thì nó không còn nằm giữa chính điểm nó đánh dấu |
| «Nút giao không thẳng hàng với nhãn» | Điểm dùng thang mép-tới-mép, nhãn ngày lại là 7 ô **đều nhau** — hai thang khác nhau thì không đời nào khớp |

**Thang băng** chia vùng vẽ thành đúng `N` ô bằng nhau và đặt điểm ở **tâm ô**: `buoc = iw/N`, `X[i] = PL + (i+0.5)·buoc`. Hệ quả:

- dải = **trọn một ô**, luôn nằm trong lưới, **không cần kẹp** nữa
- vạch lưới dọc vẽ tại tâm ô ⇒ đi **xuyên đúng điểm dữ liệu**
- dải và đường dọc cao đúng `PT → PT+ih`, khít đường nền
- hàng nhãn chỉ cần **cùng lề trái/phải** với vùng vẽ (`padding: 0 PR 0 PL`) rồi chia 7 ô đều — tâm ô tự trùng `X[i]`. **Không có con số magic nào**: hai bên cùng suy ra từ một lề.
- bám chuột đổi từ `round` theo điểm sang **`floor` theo ô** — mỗi ngày sở hữu trọn một ô, con trỏ ở đâu trong ô cũng thuộc ngày đó

#### Gradient — ba chỗ, mỗi chỗ một lý do

| Chỗ | Gradient | Vì sao |
|---|---|---|
| Vùng dưới đường | dọc, màu → trong suốt | cho khối lượng, và tách hai chuỗi khi chúng chạy sát nhau |
| Nét đường | **ngang**, 45% → 100% | mã hoá chiều đọc: quá khứ nhạt, hôm nay đậm nhất. Không phải trang trí |
| Dải ngày đang xem | dọc, 16% → 2% | vùng chọn không được nặng bằng dữ liệu nó phủ lên |

Cộng thêm **quầng sáng** `r=9, opacity .15` sau điểm đang xem — vừa là hiệu ứng nổi, vừa giữ cho điểm không chìm vào vùng gradient bên dưới.

⚠️ `stop-color` đặt qua thuộc tính **`style`**, KHÔNG qua presentation attribute: `var()` không được phân giải trong presentation attribute — **cùng lớp bẫy với `rx="var(--…)"`** đã gặp ở vòng trước.

**Lưới DỌC dưới mỗi ngày, và 5 mốc trục y thay vì 3.** Không có vạch dọc, mắt phải tự dóng từ điểm trên đường xuống nhãn ngày qua một khoảng trắng — sai số của phép dóng ấy đọc thành «điểm không thẳng cột» (người dùng báo đúng hiện tượng này). Vạch dọc mảnh hơn lưới ngang (`border-soft` vs `border`) để không tranh chấp với dữ liệu. Trục y 5 mốc cho phép đọc giá trị một điểm mà không cần rê chuột; trần làm tròn lên bội của 20 để 5 mốc luôn rơi vào số nguyên tròn — một trục ghi `0 · 8,75 · 17,5` là trục không ai đọc.

### Ô ⑤ Kiến thức — khổ rộng 8/12, sáu HÀNG với thước khắc vạch

Bản trước in **tổng** làm số chính (`12` dự án), số đã phát hành nằm ở dòng chữ nhỏ. Nhưng agent **không đọc được bản nháp** — view `agent_api` lọc `published` — nên «12 dự án» là con số làm người xem yên tâm sai. Số chính giờ là **`8 / 12`**: phần agent thật sự dùng được đứng trước, tổng đứng sau và mờ.

**Sáu ô lưới 3×2 → sáu hàng.** Người dùng chốt 2026-08-13: bản 3×2 *"trùng với phần Khách đánh giá"* và *"rất xấu và lỗi thời"*. Chẩn đoán: mỗi ô dùng một **thanh bo tròn đặc** — đúng cái hình mà ô ③ đang dùng cho phân bố sao, hai ô lại nằm cùng một màn. Cùng hình thì mắt đọc ra *cùng một loại số*, trong khi một bên là phân bố phiếu còn bên kia là độ phủ kho.

| Đổi | Vì sao |
|---|---|
| Ô → **hàng** | Sáu con số % xếp thành một cột thẳng: so sáu dòng là quét mắt xuống, không phải nhảy qua sáu khối rời. |
| Thanh đặc → **thước 14 nấc rời** | Khác hình, khác nhịp với ô ③ — đó là điểm chính. Nấc rời còn đọc được giá trị thô («11 trên 14 vạch») khi in đen trắng, thứ thanh đặc không cho. |
| Thêm **cột điều kiện** | «đã phát hành» · «còn mở bán» · «đã nhúng vector» — mỗi hàng lọc một kiểu khác nhau; không ghi ra thì sáu tỉ lệ trông như cùng một phép đo. Nó cũng lấp đúng khoảng trống mà một hàng rộng ~840px sinh ra (bản đầu để trống giữa tên và số, đọc ra rời rạc). |
| Dòng chân → **viên nhãn có chấm** | «4 còn nháp» / «Agent đọc đủ» — trạng thái đi kèm chữ, không bao giờ chỉ có màu. |

**Thước tô MỘT sắc (`ac`) mờ dần về đầu, không xanh/vàng/đỏ.** Độ phủ là đại lượng liên tục, mà thang liên tục thì một sắc chuyển đậm nhạt (quy tắc *sequential = one hue* của skill `dataviz`). Màu trạng thái để dành cho viên nhãn, nơi nó có chữ đi kèm. Chiều mờ→đậm cùng ngôn ngữ với nét đường ở ô ①.

**Chỉ tô đủ 14 nấc khi thật sự 100%** (`du ? 14 : min(13, round(ti·14))`). Làm tròn lên ở 13,6/14 sẽ vẽ ra một thước đầy cho một kho còn thiếu — đúng kiểu nói dối mà cả ô này sinh ra để tránh.

**Dòng chú thích cộng gộp theo MỤC, không lấy trung bình sáu tỉ lệ** (`1.240 / 1.526 mục · 81%`): trung bình tỉ lệ cho «dự án» (12 mục) cùng trọng số với «căn» (1.203 mục).

Sáu hàng: Dự án · Phân khu · Căn / sản phẩm · Tài liệu dự án · Tệp tra cứu · Hồ sơ đủ trường.

**Delta so 3 ngày cuối với 3 ngày đầu**, không so ngày cuối với ngày kề nó: một ngày lẻ dao động tới ±30%, và con số delta nhảy theo nhiễu thì mỗi sáng lại kể một câu chuyện khác.

### Ô ② Chuyển sale — donut → gauge nửa cung

Donut bỏ vì hai lý do:

1. **Vòng tròn kín nói "đây là cơ cấu chia phần"** — hai mảng ngang hàng nhau. Nhưng ô này không hỏi cơ cấu, nó hỏi **một tỉ lệ**: bao nhiêu phần trăm phải nhờ người thật. Nửa cung có điểm đầu và điểm cuối, nên đọc là *một mức trên thang 0→100*.
2. **Lỗ donut là chỗ đặt số, và số luôn phải nhỏ đi để lọt vào** — đã phải nới lỗ một lần vì chữ `23,9%` chạm vành. Miệng nửa cung rộng hơn.

**Một sắc + một máng trung tính, KHÔNG hai sắc.** Phần còn lại («agent tự xử lý») không phải chuỗi đối lập cần màu riêng — nó là phần *chưa tới* của cùng một thang. Tô nó thành màu thứ hai là bịa ra một sự đối đầu.

Hai mốc `0%`/`100%` từng có ở bản đầu đã bỏ: chúng nằm sát hai đầu vành nên chạm vào đúng thứ chúng chú thích, và với thang chỉ có **một** mức thì hai đầu mút là hiển nhiên.

**Không có biểu đồ hai trục y ở bất kỳ đâu.** Bản 1 định vẽ đường CSAT chồng lên cột lưu lượng — hai thang khác nhau chung một khung làm mắt đọc ra quan hệ không có thật, và đổi thang là đổi luôn "kết luận". CSAT về hẳn ô ③.

---

## 3. Backend — `GET /api/v1/overview`

**Một endpoint, một round-trip.** Màn luôn tải cả 5 mảnh cùng lúc; tách ra chỉ đổi 1 request thành 5 và mở đường cho 5 trạng thái loading lệch nhau.

- **Vị trí:** `modules/ops/` — `contracts.py` · `repo.py` · `router.py`
- **Cổng quyền:** `p: Principal = require(ACTIONS.OVERVIEW_READ)` — action đã có sẵn
- **Tham số:** `?tu_ngay=7|30|all`, dùng lại **ánh xạ đóng** `_KHOANG` của `repo.py`. Không nhận số tuỳ ý — cùng lý do đã ghi ở đó: một `tu_ngay` lạ lọt thẳng vào chuỗi SQL.
- **Cách ly tenant:** mọi câu mang `tenant_id = portal.current_tenant()`

```
OverviewOut
├─ moc         { tuNgay, tinhDen }
├─ hoiThoai    { tong, truoc, theoNgay[{ngay, n}], theoKenh[{kenh|null, n}] }
├─ chuyenSale  { chuyen, tuXuLy }
├─ danhGia     { trungBinh, truoc, tong, theoSao{1..5} }
└─ kienThuc    { duAn{tong,phatHanh}, phanKhu{…}, can{…}, taiLieu{…}, doDayDu }
```

### Ba chỗ SQL dễ sai

1. **`skill_calls` là jsonb hình dạng chưa chốt.** `jsonb_array_elements` phải **có phòng vệ**: hàng nào không phải array thì bỏ qua, đừng để một hàng méo làm đổ cả endpoint. Cùng tinh thần `_json(gia_tri, khi_hong)` đã có ở `router.py`.
2. **Chuỗi ngày phải `generate_series` rồi LEFT JOIN.** `GROUP BY ngày` trần làm ngày không có phiên **biến mất** thay vì ra `0` — biểu đồ nén khoảng trống lại và vẽ ra một xu hướng không có thật.
3. **`theoKenh` phải cộng đúng bằng `hoiThoai.tong`.** Hai con số này đứng cạnh nhau trên cùng một ô; lệch nhau là màn tự mâu thuẫn. (Đã xảy ra thật trong demo: đường tổng ra 1.160 trong khi 4 kênh cộng ra 1.284.)

---

## 4. Frontend

### 4.1 Primitive biểu đồ — `components/ui/chart/`

Tự vẽ SVG, **không thêm dependency**: luật «không mã màu nào ngoài `theme.css`» — mọi thư viện chart đều mang bảng màu riêng, và cấu hình lại nó qua prop là dựng một bảng màu thứ hai nằm rải trong component.

| File | Việc |
|---|---|
| `DuongNgay.tsx` | N đường theo ngày + dải crosshair + điểm nhấn ngày đang xem (ô ①). Tự đo px qua `useRef` + `ResizeObserver` |
| `GaugeCung.tsx` | nửa cung + máng, số trong miệng cung (ô ②) |
| `HangThanh.tsx` | hàng có máng + phần tô làm nền (ô ③ ④) |
| `thang.ts` | hàm thang đo thuần — test không cần DOM |

**Hợp đồng `DuongNgay`** — nhận `chuoi: {ngay, [khoa]: number}[]` + `veChuoi: {khoa, ten, mau}[]`, giữ `dangXem` là state trong, mặc định `chuoi.length - 1`. Không tự gọi API.

**Ô ③ dùng lại `components/ui/Sao.tsx` — KHÔNG viết lại.** Component đó đã tô sao lẻ đúng (`4,32` ⇒ bốn sao đầy + ngôi thứ năm tô 32%) và đang phục vụ `/quality` + `PhienKhach.tsx`. Thêm bản thứ ba là ba chỗ phải sửa mỗi lần đổi hình ngôi sao. Nó nằm ở `components/ui/` nên module `ops` import được, không phạm ranh giới.

### 4.2 Token mới cần thêm vào `theme.css`

```css
--ds1:#4361ee;      /* indigo  — chuỗi chính · cột hội thoại · Chat */
--ds2:#ef4d5a;      /* san hô  — Chuyển sale · Voice */
--ds3:#0ea5a4;      /* teal    — Zalo OA */
--ds4:#8b5cf6;      /* tím oải — slot 4 */
--ds1-nhat:#a3b4f5; /* bậc nhạt của ds1 — cột tuần chưa-phải-tuần-này (ORDINAL) */
--ds-khac: var(--n6);   /* «Chưa rõ» — xám, không chiếm slot màu */
--acs-manh:#dcece6;     /* acs đậm một nấc — hover hàng kỹ năng */
--radius-mark:3px;      /* bo góc MARK biểu đồ */
```

**Đã chạy validator** (skill `dataviz`) trên đúng nền `surface` `#fffefc`:

| Bộ | Chế độ | Kết quả |
|---|---|---|
| ds1–ds4 | adjacent | ✅ 5 cổng, **không cảnh báo nào** — cặp kề xấu nhất ΔE 12.0 deutan |
| ds1 + ds2 | **all-pairs** | ✅ sạch — ΔE 24.4 protan · 35.2 mắt thường |
| ds1-nhat → ds1 | **ordinal** | ✅ đơn sắc · độ sáng đơn điệu · ΔL ≥ .06 · đầu nhạt 2.15:1 |

Đây là bộ **đầu tiên không rơi vào dải cảnh báo CVD** (mọi vòng trước đều ở 6–8), nên không còn ràng buộc "màu không được đứng một mình".

⚠️ `--ds1-nhat` **không được nhạt hơn nữa**: `#a9bcf9` đo ra 1.85:1, dưới sàn 2:1 của thang ordinal — cột nhạt sẽ chìm vào nền thẻ.

#### Ba vòng màu đã BỎ — đừng thử lại

1. **Neo vào `ChipKenh`** (chat `#1f5aa8` + voice `#5b45a8`): **ΔE 0.6 deutan** — gần như một màu.
2. **`#1f5aa8` lam + `#a05a00` hổ phách**: người dùng chốt "chưa đẹp", đo lại thì đúng — `#a05a00` chroma sát sàn, trên nền giấy ấm ra nâu bùn chứ không phải một sắc.
3. **`#3a5fa8` chàm + `#c2593f` đất nung**: đạt cổng, nhưng vẫn là bộ "cổ điển" — hai sắc trầm, bão hoà thấp, đọc ra cũ. Người dùng yêu cầu hiện đại hơn.

`--radius-mark` **không phải bậc thứ tư của UI**: thang 6/8/12 đo cho nút · ô nhập · thẻ; một mảng thanh cao 10px bo 6px thì thành viên thuốc. Khai có tên để không ai viết `rounded-[3px]` rải trong component.

### 4.3 Component — `features/ops/components/`

```
TongQuanScreen.tsx   điều phối: 1 useQuery → truyền xuống
OHoiThoai.tsx  OChuyenSale.tsx  ODanhGia.tsx
OKienThuc.tsx  OUsageBilling.tsx
```

Năm ô. Mọi `O*` là **component trình bày thuần** — nhận data qua prop, không gọi API. Đúng nếp `FeedbackTongQuan.tsx`.

### 4.4 Trạng thái

- **Đang tải:** skeleton đúng khuôn 5 ô — lưới không nhảy khi data về.
- **Lỗi:** `LoiTai` từ `components/ui/TrangThai`.
- **Tenant mới, 0 phiên:** KHÔNG hiện lưới số 0. Một thẻ dẫn hướng «Chưa có hội thoại nào. Thử agent →».
- **Rỗng một phần:** chưa có feedback ⇒ ô ③ nói «Chưa có đánh giá», **không** hiện `0/5` — 0 sao và chưa ai chấm là hai sự thật khác nhau.

---

## 5. Test

| Tầng | Kiểm gì |
|---|---|
| BE `tests/modules/ops/` | endpoint trả đủ 5 khối · `tu_ngay` lạ rơi về `30` · tenant khác không thấy số của nhau · ngày rỗng ra `0` · **`theoKenh` cộng đúng bằng `tong`** |
| FE `tests/tong-quan.test.tsx` | 5 ô hiện đúng số từ fake · chưa có feedback ra «Chưa có đánh giá» KHÔNG phải `0` · tenant 0 phiên ra thẻ dẫn hướng · đổi `tu_ngay` gọi lại query |
| FE `tests/chart-thang.test.ts` | `thang.ts` thuần — mảng rỗng · 1 điểm · mọi giá trị bằng nhau (chia 0) · giá trị âm |
| Cổng có sẵn | `module-boundaries` · `nav-registry` phải vẫn xanh |

⚠️ Chạy bằng `NODE_OPTIONS="--no-experimental-webstorage"` hoặc Node 22 — xem Gotchas của `CLAUDE.md`.

---

## 6. Đã CẮT khỏi bản 1 — và vì sao

| Thứ bị cắt | Lý do |
|---|---|
| **Heatmap giờ cao điểm** (7×24) | 168 ô cho một câu hỏi không dẫn tới hành động nào ở màn này. Thuộc về một màn phân tích riêng nếu có nhu cầu thật. |
| **Sơ đồ tầng dữ liệu** (4 tầng có mũi tên) | Ý cốt lõi của nó — *dự án còn nháp thì agent không thấy* — đã nằm gọn trong ô ⑤ dưới dạng «12 · 8 đã phát hành». Sơ đồ chiếm trọn một dải để nói thêm rất ít. |
| **Bảng «Cần chú ý»** | Danh sách phiên là việc của `/convos` và `/quality`; nhân bản nó ở đây là hai chỗ cùng phải sửa mỗi lần đổi. Link «Xem tất cả →» thay thế. |
| **4 thẻ KPI riêng** | Trùng với số chủ đạo đã nằm sẵn trong từng ô. |
| **Kỹ năng agent đã dùng** (`skill_calls`) | Người dùng chốt 2026-08-13: *"dữ liệu này không có ý nghĩa"*. Biết agent gọi `kb_search` 103 lần không dẫn tới quyết định nào của quản lý vận hành — nó là số liệu về **cơ chế nội bộ**, không về kết quả. Ô này nhường chỗ cho «Kiến thức» rộng ra 8/12. Cột `skill_calls` vẫn còn trong DB nếu sau này cần. |

Muốn thêm lại thứ nào thì đọc lại bảng này trước — chúng bị bỏ có chủ ý, không phải sót.

---

## 7. Thứ tự làm

1. BE: `contracts.py` → `repo.py` (SQL + test) → `router.py`
2. FE: `thang.ts` + 4 primitive (test thuần trước)
3. FE: `api.ts` + MSW fake
4. FE: 5 component `O*` → `TongQuanScreen`
5. Thêm token vào `theme.css`, gắn route, xoá `ScreenStub`, chạy toàn bộ cổng CI
6. **Xoá `public/demo-tong-quan.html`**

---

## 8. Tham khảo

- [Dashboard Design Best Practices — Boundev](https://www.boundev.ai/blog/dashboard-design-best-practices-guide) — 5–9 chỉ số/màn
- [Dashboard Design Guide — Improvado](https://improvado.io/blog/dashboard-design-guide) — mốc "cập nhật lúc"
- [Bento Grids for AI Dashboards — Baltech](https://baltech.in/blog/bento-grids-for-ai-dashboards/) — lưới 12 cột, gap đồng nhất
- [Measure AI Agent Performance — Rasa](https://rasa.com/blog/measure-ai-agent-performance-in-the-contact-center) · [KPIs for Voice AI Agents — Balto](https://www.balto.ai/blog/kpis-for-voice-ai-agents-in-contact-centers/) — định nghĩa tỉ lệ chuyển người thật
