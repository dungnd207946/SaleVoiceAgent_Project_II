# Task 5 — báo cáo triển khai

## Phạm vi thực hiện

Đúng theo `task-5-brief.md`: một bảng Explorer (`BangLuotDung.tsx`) với ba
chiều gộp Khoá/Người tạo/Phiên, cắm vào `UsageScreen.tsx` cùng hai nhãn mục
«① Kỳ này» / «③ Lượt dùng chi tiết» mà Task 4 cố ý để trống.

**Lệch brief một chỗ, có chủ ý:** không dựng ô tìm `[tìm…]` mà bản vẽ §7 phác
cạnh `NhomTab` — `task-5-brief.md` (nguồn giao việc trực tiếp) chỉ liệt kê
NhomTab + cột + phân trang, không giao ô lọc/tìm; ghi lại làm việc còn treo,
không phải sót.

### Files tạo mới

- `src/features/billing/components/BangLuotDung.tsx` — bảng Explorer. Ba
  subcomponent (`BangTheoKhoa`/`BangTheoNguoiTao`/`BangTheoPhien`), mỗi cái
  tự gọi hook riêng (`useTheoKey`/`useTheoOwner`/`usePhien`) nên đổi tab không
  đụng data hai chiều còn lại.
  - **Ghim cuối** (`ghimCuoiVaSap`): lọc hàng `null` RA trước khi sort phần
    còn lại rồi nối lại ở cuối — nên nó không bao giờ trôi vào giữa danh sách
    dù đang sắp theo cột nào. Áp cho cả hai chiều Khoá (`agent_key_id`) và
    Người tạo (`user_id`), cùng hằng `NHAN_CHUA_PHAN_LOAI` (export).
  - **Hàng Tổng chiều Khoá** dùng thẳng `chi_phi_tong` API; `Σ items[].
    chi_phi` (qua `congTien`, BigInt) chỉ để SO SÁNH (`soSanhTien`) — lệch
    thì bật dải `role="status"` đỏ nói rõ đây là tín hiệu lỗi. Chiều Người
    tạo không có `chi_phi_tong` riêng từ API (`DongOwner[]` trần) nên Tổng ở
    đó là tổng tự cộng, không có gì để đối chiếu.
  - Không cột `voice_sec`/thời lượng nào ở bảng chính (luật ③ hợp đồng BE).
  - Chiều Phiên: `exact === false` mới có pill «Đo thiếu»; `true` không vẽ
    gì. Phân trang `limit=50`, nút «Trang sau →» disable khi hết trang.
  - Sắp xếp (cột `Cot.sap` của `DauBang`) là CLIENT-SIDE cho hai chiều Khoá/
    Người tạo (API không phân trang hai chiều này, dữ liệu về trọn một lần).
    Chiều Phiên không có cột sắp — chỉ phân trang server-side.
  - Phiên KHÔNG bấm được ở Task 5 (không `mo` trên `Hang`) — slide-over là
    việc Task 6, ghi rõ trong docstring để không ai tưởng là thiếu sót.

### Files sửa

- `src/features/billing/components/UsageScreen.tsx` — thêm `TieuDeMuc`
  (`16px sans 600` + dòng phụ `12,5px`, NGOÀI thẻ) đặt trước `<TheKpi>` (①) và
  trước `<BangLuotDung>` (③); render `<BangLuotDung tim={tim} datTim={datTim}
  from={from} to={to} />`. Docstring đầu file viết lại: giải thích ĐÁNH SỐ
  ①③ (không ①②) — mục ② («Tiền đi đâu») bị cắt vì không endpoint nào tách
  theo component/ngày, giữ số ③ để ngày có endpoint thì ② chèn đúng chỗ mà
  không phải đánh số lại toàn bộ.
- `src/routes/_app/usage.tsx` — `datTim` giờ chọn `replace`/`push`: đổi
  **một mình** `trang` (nút Trang sau) ⇒ push (Back = trang trước); mọi thay
  đổi khác (kỳ, đổi `gop` — luôn kèm reset `trang: 1`) ⇒ replace. Cùng lối
  `routes/_app/quality.tsx` (`replace: l.beforeId === undefined`).
- `src/features/billing/dinh-dang.ts` — thêm `congTien()`/`soSanhTien()`,
  cả hai qua `BigInt` (không `Number`) để cộng/so `Tien` chính xác trên số
  vượt `Number.MAX_SAFE_INTEGER`. `congTien` KHÔNG dùng để HIỆN tổng thay
  `chi_phi_tong` — chỉ để đối chiếu, đúng luật "không tự cộng ở FE".
- `tests/billing-usage.test.tsx` — thêm describe `③ Explorer` (10 bài, fixture
  `datApiKey`/`datApiOwner`/`datApiPhien` RIÊNG của test này, không tái dùng
  `features/billing/msw.ts`, cùng lý do đã ghi ở đầu file). Sửa 1 bài Task 4
  đã có (`① năm thẻ KPI`): `getByText('Phiên')` đổi sang `getByRole('heading',
  { name: 'Phiên' })` vì từ Task 5, bảng ③ (chiều Khoá mặc định) cũng có một
  cột tên «Phiên» — hai phần tử cùng text, phải phân biệt bằng role.
- `tests/billing-dinh-dang.test.ts` — 6 bài đơn vị cho `congTien`/`soSanhTien`
  (mảng rỗng, số lẻ khác độ dài, số vượt an toàn của `Number`, số âm).

## Test summary

- **Trước** (baseline đề bài): 748 passed · 6 skipped · 0 failed.
- **Sau**: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run` →
  **763 passed · 6 skipped · 0 failed**, 58 file test, không có bài nào đỏ.
  (+15 bài mới: 10 ở `billing-usage.test.tsx`, 6 ở `billing-dinh-dang.test.ts`,
  trừ 1 bài Task 4 sửa lại câu query chứ không phải bài mới.)

## `npx tsc -b --force`

Output rỗng (thoát mã 0) — không lỗi kiểu nào trên toàn repo.

## Hai lệnh grep bắt buộc

```
$ grep -rhoE 'text-\[[0-9.]+px\]' src/features/billing/ | sort | uniq -c | sort -rn
      9 text-[12.5px]
      3 text-[13.5px]
      1 text-[32px]
      1 text-[26px]
      1 text-[16px]
      1 text-[11px]
      1 text-[10.5px]

$ grep -rn 'style={{[^}]*fontSize' src/features/billing/ || echo OK
OK
```

Mọi cỡ chữ dùng nằm ĐÚNG trong thang 9 bậc cho phép (`32·26·20·16·15·13.5·
12.5·11·10.5`) — không có bậc lạ nào mới xuất hiện trong `src/features/
billing/`. Không `style` fontSize inline. `npx eslint` trên các file đã sửa/
tạo: sạch. `npx prettier --check` trên các file đã sửa/tạo: sạch (một file
(`tests/billing-dinh-dang.test.ts`) phải `--write` lại sau khi thêm import
mới làm dòng import quá dài — đã format lại đúng chuẩn repo).

## Concerns

1. **Không có ô tìm/lọc** cho Explorer (xem "Lệch brief" ở đầu file) — bản vẽ
   §7 có phác nhưng `task-5-brief.md` không giao việc này. Nếu Task 6/7 hoặc
   review sau cần, đây là việc còn treo, không phải bug.
2. **Sắp xếp hai chiều Khoá/Người tạo là client-side** (API không hỗ trợ
   `sort=`/phân trang cho hai endpoint đó — xác nhận từ `api.ts`: `useTheoKey`/
   `useTheoOwner` chỉ nhận `from`/`to`). Đúng với dữ liệu hiện tại (BE trả
   trọn tập một lần, không phân trang), nhưng nếu BE sau này thêm phân trang
   cho hai endpoint này thì sort phải chuyển xuống server — ghi lại để không
   ai ngạc nhiên khi đọc code.
3. **Hàng Phiên chưa bấm được** (không `mo` trên `Hang`) — cố ý để dành cho
   Task 6 (slide-over `?phien=`). `datTim`/route đã sẵn `phien` trong
   `UsageTim` từ Task 4 nên Task 6 chỉ cần thêm `mo` + panel, không cần sửa
   lại tầng điều hướng.
4. **`BangLuotDung.tsx` import type `UsageTim` từ `UsageScreen.tsx`** trong
   khi `UsageScreen.tsx` import GIÁ TRỊ `BangLuotDung` từ file kia — vòng phụ
   thuộc, nhưng CHỈ Ở PHÍA TYPE (`import type`, xoá lúc build) nên không có
   vòng runtime thật. Nêu ra để review cân nhắc có muốn tách `UsageTim` sang
   một file trung lập (vd `kieu.ts`) hay chấp nhận như hiện tại — không đổi vì
   Task 4 đã đặt `UsageTim` ở `UsageScreen.tsx` và di chuyển nó không thuộc
   phạm vi Task 5.
5. Chưa chạy `make build` (không nằm trong cổng bắt buộc của brief) — chỉ xác
   nhận `tsc -b --force` xanh và suite test xanh.

## Commit

`8a26bd3` — `feat(billing): explorer 3 chiều gộp + hàng «Chưa phân loại» ghim cuối`
(6 files changed, 899 insertions, 13 deletions).

---

## Addendum — sửa theo review (Important finding)

### Finding

`TokenHoacGach` (`BangLuotDung.tsx`) tự khai «luật riêng cho cột Cache read»
nhưng đang bị gọi cho CẢ Token in/Token out ở cả hai bảng (Khoá dòng thường +
dòng «Chưa phân loại»; Phiên). Hậu quả: một khoá/phiên có `input_tokens: 0`
**thật** (lỗi gọi giữa chừng, phiên chỉ đọc cache) sẽ hiện `—` mờ y hệt
«chưa có dữ liệu» — che dữ liệu thật thành trông giống rỗng, đúng thứ luật ②
hợp đồng BE cấm. Các cột đếm khác (`so_phien`/`so_key`/`so_turn`) vẫn hiện `0`
thật qua `SO()`, nên bảng đang có hai luật khác nhau cho cùng loại dữ liệu.

### Sửa

- Đổi tên `TokenHoacGach` → `OCacheRead`, docstring viết lại nói RÕ hàm này
  CHỈ phục vụ cột Cache read (usage bình thường: provider không hỗ trợ cache
  thì luôn `0`) và cấm dùng cho cột nào khác — kèm lý do luật ② ở trên, để
  cái tên/chú thích không còn là chỗ mời dùng sai lần nữa.
- Token in / Token out (cả hai bảng, cả hai dòng thường/`agent_key_id: null`
  ở chiều Khoá, và chiều Phiên): đổi sang gọi thẳng `token(n)` — hiện `0`
  thật, cùng cách `SO()` đã hiện `0` thật cho các cột đếm khác.
- `cache_read_tokens` giữ nguyên `OCacheRead` (2 chỗ, dòng thường + dòng
  «Chưa phân loại» của chiều Khoá — chiều Người tạo/Phiên không có cột này).

### Cổng test mới — bắt CẢ HAI hướng sai trong MỘT bài

Thêm hàng fixture `K-zero-token` (`agent_key_id: 3`) vào `CO_SO_KEY`
(`tests/billing-usage.test.tsx`) với `input_tokens`/`output_tokens`/
`cache_read_tokens` ĐỀU = `0` (và `chi_phi: '10.0000000000'` — khác 0 để
không trùng chữ "0" với hai cột token trong cùng một hàng khi assert). Bài
mới:

> `Token in/out hiện «0» THẬT khi bằng 0 — KHÔNG che thành «—» như Cache read`

khẳng định Token in VÀ Token out cùng hiện `"0"` (2 lần trong hàng, qua
`within(hang).getAllByText('0')`), còn Cache read CÙNG HÀNG vẫn hiện `"—"`
(`within(hang).getByText('—')`) — một bài, so hai cột cùng giá trị đầu vào,
bắt được cả việc áp nhầm luật gạch sang token LẪN việc lỡ bỏ luật gạch khỏi
cache. **Đã kiểm ngược**: tạm gọi `OCacheRead` cho `input_tokens` (mô phỏng
đúng bug review chỉ ra) → bài đỏ đúng chỗ (`expected length 2 but got 1`);
phục hồi code đúng → xanh lại. Cập nhật `total`/`chi_phi_tong` của
`CO_SO_KEY` theo hàng mới (4 hàng, `414501.0000000000`) và hai chỗ tham chiếu
số cũ (`414491`) ở bài kiểm tra lệch `chi_phi_tong`.

Cũng thêm một hàng zero-token tương đương vào `features/billing/msw.ts`
(`BILLING_BY_KEY_GIA`, khoá `Zero-token key`) để fake dev-mode (`make dev`
dưới MSW) phản ánh đúng ca này — cập nhật `total`/`chi_phi_tong`/`so_phien`/
`so_key` của fixture đó cho khớp tổng (không có test nào gate trực tiếp file
này cho Explorer, theo đúng lý do "hai nguồn" đã ghi ở đầu
`tests/billing-usage.test.tsx`; đây là việc giữ fake trung thực, không phải
cổng CI).

### Kết quả sau sửa

- **Test**: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run` →
  **764 passed · 6 skipped · 0 failed**, 58 file (tăng đúng 1 so với báo cáo
  gốc — bài gate mới; không bài nào khác đỏ dù đổi fixture `CO_SO_KEY`).
- **`npx tsc -b --force`**: output rỗng (thoát mã 0).
- **`npx prettier --check`** trên 3 file đã sửa
  (`src/features/billing/components/BangLuotDung.tsx`,
  `src/features/billing/msw.ts`, `tests/billing-usage.test.tsx`): sạch.
  `npx eslint` trên cùng 3 file: sạch.

### Bài test mới khoá điều gì

Một hàng, hai cột cùng giá trị `0` đầu vào (Token in/out và Cache read) phải
hiện KHÁC NHAU — Token in/out `"0"` thật, Cache read `"—"` — nên hàm gạch-khi-
0 (`OCacheRead`) không thể vô tình lan sang cột Token in/out lần nữa (hoặc bị
gỡ khỏi Cache read) mà không kéo bài này đỏ theo cả hai hướng.
