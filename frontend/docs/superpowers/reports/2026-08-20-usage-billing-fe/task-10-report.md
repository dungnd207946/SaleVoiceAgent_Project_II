# Task 10 — báo cáo

## Status: DONE

Commit: `a2aec01` (branch `feat/usage-billing-fe`, HEAD trước khi làm: `855ea88`).

⚠️ **`task-10-brief.md` KHÔNG TỒN TẠI** trong worktree lẫn trong lịch sử git (`find`
+ `git log --all -- '*task-10*'` đều rỗng — chỉ có brief của Task 1–9). Đã làm
dựa hoàn toàn vào mô tả trong tin nhắn giao việc (đủ chi tiết để tự đứng làm
brief) cộng với đọc trực tiếp `PanelBoGia.tsx`/`BangGiaScreen.tsx`/`api.ts`/
`kieu.ts`/`session.tsx`/`Bang.tsx`/`Truong.tsx` và mã nguồn backend
(`odyssey-portal-backend/src/portal/modules/billing/{service,repo,router}.py`).

## Việc ① — PanelGanWorkspace.tsx

File mới `src/features/billing/components/PanelGanWorkspace.tsx`, mở từ nút
«Gán workspace» (cạnh «Bộ giá mới», dải công cụ mục ② `BangGiaScreen.tsx`,
trong nhánh `coToken`). Cùng khuôn `PanelBoGia.tsx` (Task 9): `z-70`, backdrop
`<button>` phủ `absolute inset-0`, đóng qua CẢ BA đường (nút ×, lớp phủ,
Escape), trả focus qua `oMoGanRef` (ref RIÊNG với `oMoRef` của `PanelBoGia` —
hai panel khác nhau, hai điểm neo focus khác nhau).

**Sai lệch so với mô tả giao việc, đã tự quyết và ghi rõ trong docstring đầu
file:** brief nói "bảng 4 cột" nhưng đoạn ngay sau lại đòi một cột hiện `—`
kèm `title` cho "bộ giá đang áp"/"hiệu lực từ hiện hành" — hai câu chỏi nhau.
Đã chọn thêm **cột thứ năm «Đang áp»** (không gộp vào cột «Bộ giá» mới, vì gộp
sẽ đọc nhầm `—` thành placeholder rỗng của chính ô `<select>` thay vì một sự
thật riêng về workspace) hiện `—` + `title` giải thích: không có endpoint đọc
`tenant_price_version` nên **không biết**, khác hẳn "chưa gán".

Bốn cột còn lại đúng như giao việc: Workspace (tên + slug, từ
`useSession().workspaces`) · Bộ giá (`<select class="o-chon">`, lọc
`status === 'active'`) · Hiệu lực từ (`<input type="datetime-local">`) · nút
«Gán». Mỗi hàng một `useGanChoWorkspace(ws.id)` + state cục bộ riêng.

`effectiveFrom` gửi qua `new Date(local).toISOString()` (chuỗi `datetime-local`
là NAIVE, không tz — quy về UTC có hậu tố `Z` trước khi rời FE). Body gửi lên
`priceVersionId`/`effectiveFrom` cả hai camelCase, đúng `GanBoGiaIn` (đã có sẵn
trong `kieu.ts`/`api.ts`/`msw.ts` từ trước — không phải việc Task 10 tạo mới,
chỉ dùng lại).

Lỗi `409 MOC_QUA_KHU_DA_DINH_GIA` / `409 MOC_TRUOC_KHOANG_DANG_MO` hiện
**nguyên văn** `err.message` qua `DongTrangThai` — đã đối chiếu đúng message
thật trong `service.py::gan_cho_tenant`.

## Việc ② — vá lỗ mã lỗi Task 9

**Đường xử lý lỗi hiện tại của `FormThemDongGia` (`PanelBoGia.tsx`) ĐÃ
GENERIC** — `thongDiep()` chỉ kiểm `err instanceof LoiApi` rồi trả
`err.message` nguyên văn, không rẽ nhánh theo `code`. Không cần sửa code để
"bắt" `DONG_GIA_TRUNG`/`STT_HAI_CO_SO` — đường đó đã tự động hiện đúng message
cho MỌI mã `LoiApi`. Đã thêm hai bài test làm cổng cho khẳng định này (không
chỉ khẳng định suông): `409 DONG_GIA_TRUNG` và `409 STT_HAI_CO_SO`, cả hai đối
chiếu message thật từ `service.py::them_dong_gia`.

**`NHIEU_DON_VI_TIEN` KHÔNG có bài test** — đã đọc trực tiếp
`router.py::tao_dong_gia` (endpoint `POST .../price-versions/{pb}/items`):
nó chỉ gọi `service.them_dong_gia()`, và mã này chỉ được `repo.py` ném cho
`summary`/`by-key` (trộn đơn vị tiền trong một khoảng thời gian truy vấn) —
không đường nào từ form thêm dòng giá có thể trả mã này thật. Giao việc liệt
kê cả ba mã cho đường này; đã xác minh và phát hiện mã thứ ba không áp dụng
được — viết test giả lập nó sẽ khoá một hành vi không tồn tại thật.

## Test summary

| | pass | skip | fail |
|---|---|---|---|
| Trước (baseline, đã chụp trước khi sửa) | 792 | 6 | 0 |
| Sau | 804 | 6 | 0 |

+12 bài mới (9 `PanelGanWorkspace` + 2 mã lỗi form thêm dòng giá +1 gộp trong
cùng nhóm — xem file test), tất cả ở `tests/billing-gia.test.tsx`.

## `npx tsc -b --force`

Exit code 0, không có output (0 lỗi type).

## `git status --porcelain` (sau commit)

```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```

Đúng — chỉ hai file vùng cấm còn `M` (không đụng), không có gì khác lạ.
`node_modules` untracked có sẵn từ trước, không phải việc của task này.

## Hai grep bắt buộc

```
$ grep -rhoE 'text-\[[0-9.]+px\]' src/features/billing/ | sort | uniq -c | sort -rn
     32 text-[12.5px]
     11 text-[13.5px]
      9 text-[11px]
      6 text-[10.5px]
      5 text-[16px]
      4 text-[26px]
      3 text-[20px]
      1 text-[32px]
```
Toàn bộ nằm trong thang 9 bậc (`32·26·20·16·15·13.5·12.5·11·10.5`) — không có
cỡ lạ.

```
$ grep -rn 'style={{[^}]*fontSize' src/features/billing/ || echo OK
OK
```

`tests/o-chon.test.ts`: PASS (1/1).

## Kiểm ngược tz-aware

Tạm sửa `PanelGanWorkspace.tsx::HangGan.guiGan()` để gửi thẳng
`effectiveFrom` (bỏ `.toISOString()`). Chạy riêng bài
`gửi Gán: body priceVersionId/effectiveFrom camelCase, effectiveFrom TZ-AWARE`:

```
× ... TZ-AWARE (có hậu tố Z)
  → expected '2026-09-01T00:00' to match /Z$/
```

ĐỎ đúng vào assertion `toMatch(/Z$/)` — xác nhận cổng bắt được lớp lỗi tz.
Đã hoàn nguyên `.toISOString()`, chạy lại `npx tsc -b --force` (exit 0) và
toàn bộ suite (804 pass) để xác nhận sạch sau khi hoàn nguyên.

## Đường xử lý lỗi form thêm dòng giá: generic hay bắt từng mã?

**GENERIC.** `thongDiep()` không rẽ nhánh theo `code` — nó đọc `err.message`
cho mọi `LoiApi`, bất kể `BANG_GIA_CON_LO`/`DONG_GIA_TRUNG`/`STT_HAI_CO_SO`
(hay bất kỳ mã 409 nào khác BE có thể trả sau này). Task 10 không cần sửa
logic, chỉ cần THÊM CỔNG canh đúng hành vi đó cho hai mã thật.
