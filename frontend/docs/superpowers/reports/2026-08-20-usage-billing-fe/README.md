# Usage & Billing FE — sổ thi công

Hồ sơ thực thi của [plan](../../plans/2026-08-20-usage-billing-fe.md)
(spec: [`docs/product/2026-08-20-usage-billing-fe-spec.md`](../../../product/2026-08-20-usage-billing-fe-spec.md)),
chạy theo lối subagent-driven: mỗi task một implementer mới, một review, rồi một
review toàn nhánh ở cuối.

**Phạm vi:** 17 commit `3722fe3..3f2c30f`. Suite 712 → 805 pass · 6 skip · 0 fail.

Đây là thư mục **duy nhất** ghi *vì sao* mỗi quyết định được chốt như thế.
`git log` có thay đổi; nó không có lý lẽ, không có phương án bị loại, và không có
sáu lỗi trong plan mà implementer bắt được lúc thi công.

## Đọc gì

| Tệp | Nội dung |
| --- | --- |
| `progress.md` | Sổ cái. 35 dòng `Ruling:` — mỗi dòng là một quyết định + lý do + giá phải trả nếu sai. Đọc trước. |
| `task-N-brief.md` | Yêu cầu **đúng như đã giao** cho implementer task N — trích từ plan, kèm phần tôi giải toả mơ hồ. |
| `task-N-report.md` | Implementer báo lại: đã làm gì, lệch khỏi brief ở đâu và vì sao, phần còn ngờ. |
| `fix-wave-report.md` | Đợt sửa sau review toàn nhánh (chạy trên opus), gồm ba bug thật + một cổng rỗng. |

## Hai khoảng hở, biết trước

- **Không có `task-10-brief.md`.** Lỗi quy trình của tôi: task 10 tôi quên sinh
  brief, implementer làm từ dispatch message. Nó đủ chi tiết nên task chạy được —
  nhưng đó là may, không phải quy trình. Yêu cầu của task 10 chỉ còn ở plan.
- **15 tệp `review-<range>.diff` KHÔNG copy vào đây** (~480K). Chúng là output
  của `git diff` trên các khoảng commit giờ đã nằm trong nhánh, tái tạo được:

  ```bash
  git diff 3722fe3..73ef36a      # khoảng đầu, tương tự cho các khoảng còn lại
  git log --oneline 3722fe3..3f2c30f    # danh sách mốc
  ```

## Ngoài phạm vi đợt này

Màn hoá đơn (`/billing`) giữ `ScreenStub` — người dùng chốt hoãn.
Plan §13 liệt kê **10 endpoint** cần backend làm trước khi dựng tiếp; bốn khối
giao diện đã cắt khỏi đợt này vì chưa có endpoint tương ứng.
