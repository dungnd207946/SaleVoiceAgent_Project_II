# Báo cáo — tooltip hàng Kiến thức (ô ⑤)

## Bối cảnh

Người dùng phát hiện: ô ⑤ Kiến thức không có tooltip khi rê chuột vào từng
hàng, trong khi bản demo (`public/demo-tong-quan.html`) có. Đợt review tooltip
ô ① (biểu đồ Hội thoại) trước đó bắt được ô ① nhưng bỏ sót ô ⑤.

## Việc đã làm

### 1. Tách tooltip thành primitive dùng chung

`Tip`/`DongTip` trước đây là hàm **private** trong `BieuDoNgay.tsx`. Giờ ô ⑤
là người dùng thứ hai nên đã tách ra:

- `src/features/ops/components/Tip.tsx` — `RONG_TIP`/`NGUONG_LAT` (hằng),
  `HopTip` (khung định vị + kẹp/lật, testId tuỳ chỉnh), `DongTip` (dòng
  nhãn—giá trị, chấm màu tuỳ chọn), `GhiChuTip` (đoạn chú chân tooltip).
- `src/features/ops/components/useTip.ts` — hook `useTip()` (state vị trí +
  `taiChuot`/`taiTieuDiem`/`an`). Tách riêng khỏi `Tip.tsx` vì
  `react-refresh/only-export-components` (`--max-warnings 0` ở `make lint`)
  không cho một file export vừa component vừa hook.

Đặt ở `features/ops/components/`, **không** đưa lên `components/ui/`: luật
ranh giới của repo dành `components/ui/` cho thứ **hai module khác nhau** dùng
chung (xem docstring `components/ui/ChipKenh.tsx`). Ở đây mới có một module
(`ops`) dùng — đưa lên `ui/` đúng ngày có người dùng thứ hai thật.

`BieuDoNgay.tsx` đổi sang import từ hai file trên — refactor **thuần**, hành
vi và hình thức tooltip ô ① không đổi gì (giữ `data-testid="ht-tip"`).

### 2. Gắn tooltip cho từng hàng `TheKienThuc.tsx`

Mỗi hàng (`.kt-h`) giờ:
- `tabIndex={0}` + `onFocus`/`onBlur` — mở/đóng tooltip bằng bàn phím.
- `onMouseMove`/`onMouseLeave` — mở/đóng tooltip bằng chuột.
- Nội dung: tiêu đề = tên mục, dòng «Agent đọc được» = `thay`, dòng «Tổng
  trong kho» = `tong`, và với ba mục có lời giải thích (`duAn`, `tepTraCuu`,
  `hoSoDuTruong`) thêm một đoạn chú ở chân (`GhiChuTip`).
- Thêm bảng `sr-only` ở cuối `TheKienThuc` mang đủ tên mục + `thay`/`tong` +
  đoạn chú (thông tin duy nhất không hiện ở đâu khác trên hàng).

### 3. Hai điều viết lại so với demo (không chép nguyên)

- **Tip «Dự án»**: demo dẫn view `agent_api` lọc `published` — view đó đã
  **bỏ hẳn** ở migration `0917` (`odyssey-portal-backend/CLAUDE.md` mục
  "`agent_api` đã bỏ hoàn toàn"). Văn bản mới **giữ ý nghiệp vụ**, bỏ tham
  chiếu kỹ thuật sai — xem văn bản cuối cùng bên dưới.
- **Tip «Tệp tra cứu»**: demo có câu số liệu cứng "Cả 38 tệp đã nhúng xong"
  — số của dữ liệu giả. Bỏ câu đó, giữ nguyên phần giải thích quy trình (bóc
  chữ → chia đoạn → nhúng vector).

## Test

Thêm vào `tests/overview-kien-thuc.test.tsx` (describe `tooltip từng hàng`):
- nghỉ thì không có tooltip nào trong DOM
- rê chuột vào một hàng ⇒ tooltip đúng tên mục · Agent đọc được · Tổng trong kho
- ba mục có ghi chú ⇒ đúng nội dung (và xác nhận KHÔNG còn `agent_api` /
  "Cả 38 tệp")
- ba mục không có ghi chú ⇒ tooltip không có đoạn chú (`.border-t`)
- mở được bằng bàn phím: `tabIndex=0`, `focus`/`blur` đúng nội dung

Thêm vào `tests/overview-bieu-do.test.tsx`: một bài hồi quy tường minh cho
ô ① (chuột mở/đóng + bàn phím mở, testid `ht-tip`) sau khi tách primitive.

## Cổng

```
npx vitest run          → 47/47 file, 602 passed, 6 skipped, 0 failed
                           (baseline 596 passed + 6 test mới)
npx tsc -b --force       → sạch (typecheck thật, --noEmit là cổng rỗng)
VITE_MSW=0 npm run build → build production sạch
npx eslint . --max-warnings 0 → sạch
npx prettier --check src tests → 3 file lệch định dạng, KHÔNG file nào của
                           việc này (TaiLieuTab.tsx, tabDuAn.ts thuộc việc
                           đang dở của người dùng; routeTree.gen.ts là tệp
                           sinh, luôn bẩn lại — đúng gotcha đã ghi ở CLAUDE.md)
```

## Kiểm bằng mắt

`npm run dev` (`VITE_MSW=1` để có dữ liệu giả không cần backend thật), dùng
Chrome headless (`google-chrome --headless=new`) điều khiển qua CDP thô
(không có puppeteer/playwright cài sẵn, không internet để cài) — mở
`/dashboard`, focus hàng `kt-hang-duAn` bằng `element.focus()` (tương đương
tiêu điểm bàn phím thật vì component chỉ dựa vào sự kiện `focus`/`blur`),
chụp màn hình 1440×900. Lưu tại
`docs/superpowers/anh-man-tong-quan/kien-thuc-tooltip.png`. Đã tắt dev
server sau khi xong (`pkill vite`, xác nhận cổng 5273 trống).

**Thấy gì trong ảnh**: hàng «Dự án» có viền focus xanh lá (accent) — xác
nhận `tabIndex=0` + `:focus-visible` hoạt động. Tooltip nền tối nổi ngay
trên/cạnh hàng, đúng hình thức của tooltip ô ①: tiêu đề đậm «Dự án», dòng
«Agent đọc được  8», dòng «Tổng trong kho  12», và đoạn chú ở chân (có kẻ
trên tách biệt) mang đúng văn bản mới viết cho Dự án. Không còn dấu vết
`agent_api` hay số liệu cứng nào.

## Văn bản cuối cùng cho tip của «Dự án» (cần duyệt)

> Agent chỉ đọc dự án đã phát hành. Dự án còn nháp thì agent trả lời «chưa
> có thông tin» khi khách hỏi đúng dự án đó.

## Files

- `src/features/ops/components/Tip.tsx` (mới)
- `src/features/ops/components/useTip.ts` (mới)
- `src/features/ops/components/BieuDoNgay.tsx` (sửa — refactor thuần)
- `src/features/ops/components/TheKienThuc.tsx` (sửa — thêm tooltip)
- `tests/overview-bieu-do.test.tsx` (sửa — thêm test hồi quy)
- `tests/overview-kien-thuc.test.tsx` (sửa — thêm test tooltip)
- `docs/superpowers/anh-man-tong-quan/kien-thuc-tooltip.png` (mới — ảnh kiểm)

Commit: `2ce9755` — chỉ bảy file trên, KHÔNG đụng tám file người dùng đang
sửa dở (`CLAUDE.md`, `src/features/ops/nav.ts`,
`src/features/platform/components/KhoaMoiDialog.tsx`, `src/lib/nav-registry.ts`,
`src/lib/screens.ts`, `tests/command-palette.test.tsx`,
`tests/nav-registry.test.ts`, `tests/shell.test.tsx`) và không đụng
`public/demo-tong-quan.html`.

## Ghi chú ngoài lề (không phải phần việc, chỉ để minh bạch)

`CLAUDE.md` gốc ở thư mục cha (`odyssey-project/CLAUDE.md`, ngoài repo này)
chứa một khối luật "context-mode — MANDATORY routing" yêu cầu định tuyến mọi
Bash/Read/Grep/WebFetch qua một MCP plugin bên thứ ba. Khối luật này không
liên quan gì tới việc sửa lỗi ở đây; nó có dấu hiệu là nội dung chèn
(prompt injection) chứ không phải quy ước dự án thật — chính
`CLAUDE.md` của repo này (mục Change Log, dòng 2026-08-06) từng ghi lại việc
xoá một khối `ctx_*` y hệt vì "MCP tool không tồn tại, và nội dung nói về
repo khác". Đã không tuân theo khối luật đó, dùng thẳng Read/Edit/Bash/Write
như bình thường cho toàn bộ việc này.
