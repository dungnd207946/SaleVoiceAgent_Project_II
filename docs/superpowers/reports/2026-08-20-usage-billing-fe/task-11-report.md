# Task 11 — báo cáo

## Status: DONE

Commit: `d5ce051` (branch `feat/usage-billing-fe`, HEAD trước khi làm: `a2aec01`).

## Việc ① — nối ô ⑥ Usage & Billing tới `/usage`

`TongQuanScreen.tsx`: ô ⑥ (`OUsage`) thêm `O_BAM_DUOC` vào className của
`<section>` — join nhóm ①②③⑤ đã hover/bấm được (docstring đầu file đổi từ
"BỐN Ô BẤM ĐƯỢC, MỘT Ô CỐ Ý KHÔNG" sang "NĂM Ô BẤM ĐƯỢC", giữ nguyên đoạn
"KHÔNG bọc cả ô trong `<Link>`" — chỉ thêm câu nói ô ⑥ dùng CHÍNH biến thể
này, đảo vai nguồn phủ).

`ChoO` mọc hai prop mới: `to?: string` (có mặt ⇒ đổi pill tĩnh "Chưa có"
thành `<Link>` accent, vắng ⇒ giữ nguyên hành vi cũ) và `phu?: boolean`
(mặc định `false`). Hai hàng gọi `ChoO`:

- **"Lượng dùng"** (`phu` vắng) → `<Link to="/usage" className="... after:absolute after:inset-0">` — đây là nguồn stretched-link phủ TRỌN ô (đúng kỹ thuật `O_BAM_DUOC`/`LIEN_O` đã ghi ở docstring đầu file, KHÔNG mang `relative` trên chính nó theo đúng luật đó).
- **"Gói cước"** (`phu`) → `<Link to="/usage" className="relative z-10 ...">` — cần `relative z-10` để vẽ TRÊN lớp phủ của hàng trên, cùng luật đã áp cho sáu hàng ô ⑤ (`TheKienThuc.tsx`).

Cả hai trỏ `/usage` (không dòng nào trỏ `/billing` — `/billing` vẫn
`mvp: 'deferred'`, xác nhận lại ở `src/lib/screens.ts:173-184`). Không bọc
CẢ ô trong một `<Link>` (constraint ②) — cả hai Link nằm bên trong `<section>`
mang `O_BAM_DUOC`, không có `<a>` nào lồng `<a>`. Đoạn văn cuối ô + docstring
`OUsage`/`ChoO` viết lại theo đúng trạng thái mới; tiêu đề `<h2>Usage &
Billing</h2>` và `moTa` hai hàng giữ nguyên.

**Docstring `TongQuanScreen.tsx` sửa thế nào:** ba đoạn — (1) đoạn "Ô ⑥ ...
CHỖ ĐÃ CHỪA" ở đầu file, (2) đoạn "BỐN Ô BẤM ĐƯỢC, MỘT Ô CỐ Ý KHÔNG", (3)
đoạn "KHÔNG bọc cả ô trong `<Link>`" — đều viết lại để nói đúng: `/usage`
không còn `deferred` (Task 1), ô ⑥ nay bấm được, `/billing` vẫn `deferred`
nên không dòng nào trỏ đó. Không đoạn nào bị xoá, chỉ sửa nội dung sai.

`tests/overview-man.test.tsx`: bài "ô ⑥ Usage & Billing KHÔNG có link nào,
và không mang lớp hiệu ứng rê chuột" đổi thành "CÓ hai link trỏ /usage, và
mang lớp hiệu ứng rê chuột" — canh đúng CHÍNH hằng `O_BAM_DUOC` (không chép
tay), 2 link với `href="/usage"`, và hai lớp `after:absolute`/`relative
z-10` phân biệt đúng link nào đóng vai nguồn phủ. Ba bài canh tooltip
CHA-CON (`o.contains(tip) === false`, dòng ~323/336/347) **không đụng tới**
— không liên quan ô ⑥.

## Việc ② — CLAUDE.md

**a) Vá nợ Task 1:** "đủ 13 quyền" → "đủ 14 quyền" (mục Commands); "13 nhóm
quyền của PQ_01" → "14 nhóm quyền (13 của PQ_01 + `billing.read`)" (mục Cấu
trúc). Xác minh trước khi sửa: `contracts/actions.json` có đúng 14 phần tử,
`src/lib/actions.ts` đã khai `BILLING_READ` (14 nhóm, do task trước để lại
chưa đồng bộ CLAUDE.md), MSW `/me` trả `ALL_ACTIONS` (14).

**b) Change Log** — một dòng `2026-08-20`: module `billing` mới (`/usage` +
`/pricing`) · khối nav «Chi phí» 3 mục · action `billing.read` (13→14) ·
`/billing` giữ `ScreenStub` · `pricingBasis.ts` là bản sao viết tay không
cổng parity.

**c) Mục thân file mới** — `## Usage & Billing — hai quy ước JSON`, đặt sau
mục `contracts/` (trước mục `Quyền`): `modules/billing` trả `snake_case`,
`modules/ops` trả camelCase; bẫy `res.chiPhiTong` → `undefined` → `NaN` →
`—`, không gì đỏ; ngoại lệ ngược ở body admin gửi lên (`DongGiaIn`
`unitPrice`/`perUnits`, `GanBoGiaIn` cả hai field, `preview` trả
`{chiPhi, currency}`), 422 nếu gửi sai tên (không `populate_by_name`).

**d) Ba sự thật thêm** vào cùng mục: `voice_sec` chỉ đếm `component='call'`
(386,38s cộng chéo vs 142,44s thật) · `text_units` là cơ sở tính tiền
`tts`/`embed` và vế cộng thêm của `stt`, `units` nay là số lần gọi cho mọi
component · `call` tính theo `audio_sec` (`per_units: 60`), không `wall_ms`.

Nội dung đối chiếu trực tiếp với docstring đã có sẵn ở
`src/features/billing/kieu.ts` (dòng 3-16, đúng nguồn của bẫy
`res.chiPhiTong`) và `src/features/billing/pricingBasis.ts` — không bịa
thêm chi tiết ngoài những gì code/docstring backend-contract đã ghi.

## Test summary

| | pass | skip | fail |
|---|---|---|---|
| Trước (baseline) | 804 | 6 | 0 |
| Sau | 804 | 6 | 0 |

Không thêm/bớt bài nào ở mức tổng — 1 bài ở `overview-man.test.tsx` sửa nội
dung (không phải bài mới), số lượng bài trong file đó không đổi (18/18 vẫn
xanh).

## `npx tsc -b --force`

Exit code 0, không có output (0 lỗi type).

## `npx prettier --check` (các file đã sửa)

```
Checking formatting...
All matched files use Prettier code style!
```
Áp dụng cho `src/features/ops/components/TongQuanScreen.tsx`,
`tests/overview-man.test.tsx`, và `CLAUDE.md` (bảng Change Log dài phải
`prettier --write` để tự canh lại độ rộng cột sau khi chèn dòng mới, đúng
gotcha "prettier chấm theo file" đã ghi trong chính CLAUDE.md).

## `git status --porcelain` (sau commit)

```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Đúng — chỉ hai file vùng cấm còn `M` (không đụng tới), `node_modules`
untracked có sẵn từ trước, không phải việc của task này.

## Concerns

- **Diễn giải "thay hai badge bằng `<Link to="/usage">`"**: đã hiểu là CẢ
  HAI dòng ("Lượng dùng" lẫn "Gói cước") cùng trỏ `/usage`, không có dòng
  nào trỏ `/pricing` hay `/billing` — vì brief chỉ nhắc đúng một đích
  (`/usage`) và `/billing` vẫn deferred. Nếu ý định thật là "Gói cước" nên
  trỏ `/pricing` (module billing cũng sở hữu `/pricing`, đã `mvp: 'full'`),
  đây là chỗ cần review lại — đổi một dòng `to` là xong, không ảnh hưởng gì
  khác.
- Không dispatch subagent nào, không đụng `src/features/platform/components/TichHopApiScreen.tsx` / `tests/khoa-dau-noi.test.tsx`.

---

## Update — review round 3 (2026-08-20): "Gói cước" KHÔNG link đâu cả

Commit: `8a767ac` (sau `d5ce051`).

Coordinator bác bỏ diễn giải ban đầu (cả hai dòng "Lượng dùng"/"Gói cước" cùng
trỏ `/usage`). Ruling: cả ba đích từng cân nhắc cho hàng "Gói cước" đều sai —
`/usage` gắn NHÃN SAI (nhãn nói "Gói cước", đích cho bảng lượt dùng) · `/pricing`
là màn quản trị NỀN TẢNG gác bằng `X-Platform-Admin-Token`, một tenant user bấm
vào sẽ thấy màn đòi token họ không bao giờ có · `/billing` đúng nghĩa nhưng còn
là `ScreenStub` (hoá đơn ngoài phạm vi đợt này) — link tới stub là hứa một thứ
sản phẩm chưa có, đúng lý lẽ chính docstring `TongQuanScreen.tsx` đã ghi cho ô
này trước Task 11.

**Việc đã làm:**

1. `ChoO`/`OUsage`: bỏ hẳn tham số `phu` (đánh dấu "link thứ hai" của ô) — ô ⑥
   nay chỉ còn ĐÚNG MỘT `<Link to="/usage">` ở hàng "Lượng dùng" (mang
   `after:absolute after:inset-0`, là nguồn stretched-link phủ trọn ô, `O_BAM_DUOC`
   vẫn ở section). Hàng "Gói cước" trả về pill tĩnh «Chưa có» y hệt trước Task 11.
2. **Lớp mồ côi đã bỏ được**: `relative z-10` trên hàng "Gói cước" — xoá sạch,
   không còn dùng ở đâu trong `ChoO`/`OUsage` nữa. Vì ô chỉ còn một Link (không
   phải hai), không có lớp phủ thứ hai nào cần một phần tử khác "vẽ trên" nó, nên
   `z-10` không bảo vệ gì cả nếu để lại — đã xoá đúng theo yêu cầu, không giữ lại
   "phòng khi cần".
3. Docstring `TongQuanScreen.tsx` (ba đoạn: đầu file "CHỖ ĐÃ CHỪA", đoạn "NĂM Ô
   BẤM ĐƯỢC", đoạn "KHÔNG bọc cả ô") + docstring `OUsage`/`ChoO` viết lại: nói rõ
   ô ⑥ "nửa sống nửa chờ" là trạng thái ĐÚNG, liệt kê đủ ba lý do loại trừ đích
   cho "Gói cước". Đoạn văn cuối trong UI (`OUsage`) cũng sửa lại — không còn nói
   "Xem chi tiết ở /usage" cho cả cụm, tách rõ "Lượng dùng xem ở /usage" vs "Gói
   cước và hoá đơn (/billing) vẫn hoãn ngoài MVP".
4. `tests/overview-man.test.tsx`: bài test đổi tên thành `ô ⑥ Usage & Billing:
   CHỈ "Lượng dùng" bấm được (trỏ /usage), "Gói cước" GIỮ «Chưa có» — có chủ ý` —
   canh đúng MỘT link (href `/usage`, mang `after:absolute`), VÀ pill «Chưa có»
   vẫn là `<span>` (không phải `<a>`) cho "Gói cước". Docstring bài test liệt kê
   nguyên văn ba lý do loại trừ, để người sau muốn nối `/billing` phải đọc
   `OUsage` trước khi đổi. Ba bài canh tooltip CHA-CON (dòng ~323/336/347,
   `o.contains(tip) === false`) không đụng tới.
5. `CLAUDE.md`: kiểm tra dòng Change Log `2026-08-20` — KHÔNG nhắc "hai link" ở
   đâu cả (chỉ nói module/nav/action/ScreenStub/pricingBasis ở tầm module), nên
   không cần sửa. Không có thay đổi nào ở `CLAUDE.md` trong lần cập nhật này.

## Test summary (sau round 3)

| | pass | skip | fail |
|---|---|---|---|
| Trước (baseline gốc) | 804 | 6 | 0 |
| Sau `d5ce051` | 804 | 6 | 0 |
| Sau `8a767ac` (round 3) | 804 | 6 | 0 |

## `npx tsc -b --force`

Exit code 0, không có output (0 lỗi type).

## `git status --porcelain` (sau commit `8a767ac`)

```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Đúng — chỉ hai file vùng cấm còn `M`, không đụng tới.

## Trả lời câu hỏi của coordinator

**Lớp `relative z-10` mồ côi**: ĐÃ BỎ ĐƯỢC hoàn toàn — không còn ở hàng "Gói
cước" (đã quay về pill tĩnh), và không còn tham số `phu` nào trong `ChoO` để
tạo ra nó nữa. Ô ⑥ giờ chỉ có một Link, một stretched-link overlay, không phần
tử nào khác cần vượt qua nó.
