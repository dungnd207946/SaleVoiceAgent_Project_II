# Task 4 — báo cáo triển khai

## Phạm vi thực hiện

Đúng theo brief Task 4, ĐÈ bởi hai chỗ lệch mà điều phối viên đã ruling trước
khi giao việc: `ky.ts` không tạo lại (Task 2 đã làm), và mục ② («tiền đi
đâu») không dựng — không endpoint nào của module trả tách theo component hay
theo ngày.

### Files tạo mới

- `src/features/billing/components/TheKpi.tsx` — năm thẻ KPI, trình bày
  thuần (nhận `TongQuan`, không tự gọi API). Chỉ số của «Chi phí kỳ» ở bậc
  `32px` mono 600 (thẻ nhấn); bốn thẻ còn lại `26px` mono 500. Thẻ «Thời
  lượng gọi» mang nhãn đúng chữ (không phải "voice") + `title` giải thích vì
  sao không cộng gộp được các quãng audio.
- `src/features/billing/components/DaiCanhBao.tsx` — dải cảnh báo. HAI loại
  đỏ loại trừ nhau (`role="status"`, không nút đóng): toàn bộ `chi_phi` = 0
  (mọi dòng đang tính 0, kể cả khi `thieu_gia` = 0 — ca dễ bỏ sót nhất) hoặc
  `thieu_gia > 0` (một phần tổ hợp thiếu giá) kèm link `/pricing`. Ba con số
  chất lượng đo gộp một dòng mờ, chỉ hiện khi ít nhất một khác 0, số tuyệt
  đối (không bịa mẫu số cho `llm_khong_chinh_xac`). Trả `null` khi cả bốn
  con số = 0 và giá không toàn-0.
- `src/features/billing/components/UsageScreen.tsx` — khung màn: hàng chọn
  kỳ (4 nút `aria-pressed`, luôn bấm được kể cả lúc tải/lỗi) + khoảng ngày
  THẬT (mốc cuối lùi một ngày so với `to` nửa-mở của `giaiMaKy()`) + bốn
  nhánh trạng thái (skeleton 5 thẻ / 403 → thông báo quyền không có nút Thử
  lại / lỗi khác → `LoiTai` / `so_phien===0` → `KhoRong`) + dải cảnh báo +
  năm thẻ KPI.
- `tests/billing-usage.test.tsx` — 12 bài, boot qua `routeTree.gen.ts` thật
  (khuôn `tests/re-fixture.tsx`/`realestate-nguon.test.tsx`, không phải khuôn
  `quality-list.test.tsx` render trần — xem mục "Lệch brief" bên dưới).

### Files sửa

- `src/features/billing/contracts.ts` — thêm `export { type TenKy, giaiMaKy }
  from './ky'` và `export { UsageScreen, type UsageTim } from
  './components/UsageScreen'`.
- `src/routes/_app/usage.tsx` — bỏ `ScreenStub`, khai `validateSearch` trả
  ĐỦ bốn khoá (`ky`/`gop`/`trang`/`phien`) dù Task 4 chỉ dùng `ky`, và một
  hàm cầu nối mỏng `ManUsage()` (đọc `Route.useSearch()`/`useNavigate()`,
  truyền xuống `UsageScreen` qua props `tim`/`datTim`).
- `tests/boot.test.tsx` — thêm dấu hiệu màn thật cho `usage` (tiêu đề thẻ
  «Chi phí kỳ»); route này không còn là `ScreenStub` nên cổng 18-màn của
  Task 4 trở nên đỏ nếu không cập nhật — đã kiểm ngược (bỏ dòng này ⇒ đỏ).

## Lệch brief — và vì sao

1. **`UsageScreen` KHÔNG tự đọc `Route.useSearch()` của chính nó** như ví dụ
   Step 4 gợi ý (`component: UsageScreen` trực tiếp). Làm vậy tạo một vòng
   phụ thuộc hai chiều thật: `routes/_app/usage.tsx` import `UsageScreen` từ
   `contracts.ts`, còn `UsageScreen` phải import ngược `Route` từ chính
   `routes/_app/usage.tsx`. ESM live-binding khiến nó CHẠY ĐƯỢC (chỉ dùng
   trong thân hàm, không ở top-level), nhưng không có tiền lệ nào trong repo
   dùng dạng này — mọi màn có search param hiện có (`FeedbackList`/
   `ManChatLuong` ở `quality.tsx`, `KhachList`/`convos.index.tsx`) đều tách:
   component nhận `tim`/`datTim` (hay `loc`/`datLoc`) làm props thuần, route
   file giữ một hàm cầu nối mỏng gọi `Route.useSearch()`. Tôi theo đúng
   khuôn đã có thay vì mở một khuôn mới cho riêng màn này.
2. **Test KHÔNG dùng khuôn render trần của `quality-list.test.tsx`** (rootRoute
   giả bọc component với props tự tay) như brief chỉ định ở phần "đọc để lấy
   khuôn". Vì bài test brief đưa ra tự nó đòi hỏi hành vi ROUTER THẬT (mặc
   định `ky` do chính `validateSearch` quyết, không phải do test tự set
   props; bấm nút phải đổi được URL) — đây đúng là việc `validateSearch`
   làm, và test nó bằng props tự set sẽ bỏ qua đúng phần dễ vỡ nhất (cùng lý
   lẽ `tests/realestate-nguon.test.tsx` đã ghi cho `/projects?tab=`). Tôi
   dùng khuôn `tests/re-fixture.tsx::boot()`/`tests/boot.test.tsx` (routeTree
   thật + `LangProvider` + `QueryClientProvider`) thay vào — vẫn đúng tinh
   thần "khuôn có sẵn, đừng đoán", chỉ đổi sang khuôn PHÙ HỢP HƠN với đúng
   thứ Task 4 cần canh (route thật, không phải component cô lập).
3. **`voice_sec` fixture của test KHÔNG dùng 142.44s như ví dụ minh hoạ ở
   brief.** Fixture thật đã chốt ở `features/billing/msw.ts` (Task 3, theo
   đúng ví dụ hợp đồng BE) là `176.85`. Test dùng fixture RIÊNG (`CO_SO`,
   không phụ thuộc `msw.ts`) và tính chuỗi kỳ vọng qua chính `giay()` thay vì
   gõ tay `"2m 22s"`/`"2m 57s"` — miễn nhiễm với việc đổi số fixture sau này.
4. Dải "toàn bộ chi_phi = 0" (nhánh 4 dễ bỏ sót nhất theo mô tả nhiệm vụ) gộp
   VÀO `DaiCanhBao` thay vì tách một khối riêng trong `UsageScreen` — nó vẫn
   là "dải cảnh báo", và gộp giữ đúng luật "tối đa một dải đỏ" (không xếp
   chồng với dải `thieu_gia`) ở một chỗ duy nhất.

## Kỳ mặc định / route

`validateSearch` khai đủ bốn khoá (`ky`/`gop`/`trang`/`phien`) ngay từ Task 4
theo đúng yêu cầu — `gop`/`trang` Task 5 dùng, `phien` Task 6 dùng, chưa có gì
đọc chúng ở màn này nhưng chữ ký đã đúng để không phải sửa lại.

## Test + Typecheck + Format

- `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`:
  **736 passed · 6 skipped · 0 failed** (trước) → **748 passed · 6 skipped ·
  0 failed** (sau, +12 bài mới). Không hồi quy.
- `npx tsc -b --force` — sạch, không output:

  ```
  (không output — exit 0)
  ```

- Hai lệnh grep thang chữ, trên `src/features/billing/`:

  ```
  $ grep -rhoE 'text-\[[0-9.]+px\]' src/features/billing/ | sort | uniq -c | sort -rn
        3 text-[13.5px]
        3 text-[12.5px]
        1 text-[32px]
        1 text-[26px]
        1 text-[11px]
        1 text-[10.5px]

  $ grep -rn 'style={{[^}]*fontSize' src/features/billing/ || echo 'OK'
  OK
  ```

  Cả bảy giá trị đều thuộc đúng chín bậc. Lần chạy đầu tiên có `text-[14px]`
  (khối "Bạn không có quyền xem chi phí" copy khuôn từ `KhoRong`) — sửa về
  `13.5px` (bậc "cỡ nền") trước khi báo cáo; đã kiểm lại xanh.
- `npx prettier --check` trên toàn bộ 7 file đã đụng: sạch (2 file cần
  `--write` một lượt ở vòng đầu do dòng dài, đã sửa).

## Concerns

- Khoảng ngày hiển thị (`hienNgay`/`homTruoc` trong `UsageScreen.tsx`) tự suy
  ngày cuối = `to - 1 ngày` để bù mốc nửa-mở của `giaiMaKy()`. Đây là logic
  MỚI (brief không đặc tả công thức hiển thị, chỉ đòi "khoảng ngày THẬT") —
  đã tự kiểm bằng test regex format, chưa có test khoá đúng GIÁ TRỊ ngày (vì
  `giaiMaKy()` mặc định dùng `new Date()` thật, không truyền `homNay` cố định
  từ `UsageScreen`). Nếu cần khoá cứng ngày hiển thị, `UsageScreen` sẽ cần
  nhận `homNay` qua prop test được — chưa làm vì ngoài phạm vi Task 4.
- Nhãn nút kỳ + khoảng ngày dùng màu/viền viết tại chỗ (`NUT_KY_*` trong
  `UsageScreen.tsx`), không dùng `NhomTab`: đây là một hàng LỌC (đổi khoảng
  thời gian), không phải tab chuyển nội dung panel — cùng lý lẽ chip lọc sao
  của `FeedbackList.tsx` (cũng không dùng `NhomTab`). Ghi lại ở đây để review
  không đọc nhầm thành thiếu sót luật 4 (Design token — Hàng tab).
- `Task 5` khi thêm bảng theo khoá/người vào cùng `UsageScreen.tsx` cần biết:
  không có tiêu đề mục "①" nào đang treo sẵn — nếu muốn đánh số mục (①③) như
  brief §0.7 gợi ý, cả hai tiêu đề nên thêm cùng lúc trong đúng một commit.
