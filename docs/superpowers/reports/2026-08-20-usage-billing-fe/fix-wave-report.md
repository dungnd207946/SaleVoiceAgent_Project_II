# Fix wave — báo cáo

## Status

XONG. Tất cả bốn cổng xanh. Đã tự kiểm ngược cổng ①.

## Commit hash

`3f2c30f` (branch `feat/usage-billing-fe`, worktree `.wt-usage-billing-fe`)

## Test summary

| | Trước | Sau |
|---|---|---|
| vitest | 804 passed · 0 failed · 6 skipped | **805 passed · 0 failed · 6 skipped** |
| tsc -b --force | sạch | sạch |

Bài mới: `tests/billing-usage.test.tsx` → `③ Explorer … > chiều «Người tạo»: hàng «Chưa phân loại» GHIM CUỐI và không có cách nào ẩn nó`.

## Output bốn cổng

**1) `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run`**
```
Test Files  60 passed (60)
     Tests  805 passed | 6 skipped (811)
```

**2) `npx tsc -b --force`**
```
(không output — sạch)
```

**3) `npx prettier --check` (mọi file đã sửa: 14 file trong `src/features/billing/`, `tests/billing-gia.test.tsx`, `tests/billing-usage.test.tsx`)**
```
Checking formatting...
All matched files use Prettier code style!
```

**4) `git status --porcelain`**
```
 M src/features/platform/components/TichHopApiScreen.tsx
 M tests/khoa-dau-noi.test.tsx
?? node_modules
```
Chỉ hai file vùng cấm — không đụng, không add.

## Kết quả kiểm ngược ①

`BangLuotDung.tsx` chiều «Người tạo» — đổi dòng
`ghimCuoiVaSap(items, (d) => d.user_id === null, sapXep, SAP_OWNER)`
thành lọc bỏ hẳn hàng `user_id === null` trước khi gọi `ghimCuoiVaSap`:

- **ĐỎ**: đúng 1 bài thất bại — bài mới (`chiều «Người tạo»: hàng «Chưa phân loại» GHIM CUỐI…`), lỗi `expected -1 to be greater than -1` (không còn tìm thấy hàng «Chưa phân loại» trong bảng).
- Hoàn nguyên dòng gốc → **XANH**: `tests/billing-usage.test.tsx` 23/23 passed, suite đầy đủ 805/805.

Cổng không rỗng.

## PanelKhung — gộp được BAO NHIÊU slide-over

**Cả BA** (`PanelBoGia`, `PanelGanWorkspace`, `ChiTietPhien`). `ChiTietPhien.tsx` trước đó tự viết inline đúng cùng JSX (focus-lúc-mở qua `useEffect`+ref, Escape qua listener `document`, cùng class dialog/nút ×/svg) — không phải một biến thể khác, nên rút gọn được luôn, không chỉ hai chỗ đã copy tường minh.

## Concerns

- `ChiTietPhien.tsx` vẫn tự dựng `<div className="fixed inset-0 z-70 flex justify-end">` + backdrop `<button>` NGOÀI `PanelKhung` (giống hai panel kia) — cố ý không rút luôn phần này vào `PanelKhung` vì backdrop/khung ngoài có thể khác nhau ở nơi khác trong tương lai (vd panel không `justify-end`); nếu review muốn gộp cả lớp backdrop thì cần xác nhận không có biến thể nào cần layout khác.
- Không chạm `TichHopApiScreen.tsx` / `tests/khoa-dau-noi.test.tsx` — việc dở của người dùng, xác nhận `git status` chỉ có đúng hai file đó ở trạng thái `M` trước và sau fix wave.
