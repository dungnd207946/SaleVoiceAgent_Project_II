# Hợp đồng Nhật ký hoạt động — bàn giao FE

> **Đối tượng:** frontend team, ghép màn `/audit` («Nhật ký», `features/platform`).
> **Sở hữu:** module `audit` (backend). Đổi field/route ở `src/portal/modules/audit/*` mà không sửa
> tài liệu này là để tài liệu nói dối.
> **Spec:** `docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md`.

Xác thực: phiên đăng nhập, action **`audit.read`** (`ACTIONS.AUDIT_READ`, migration `0956`, cấp mặc
định cho «Quản trị»). Không có action ⇒ 403 với message «… Xem Nhật ký hoạt động …». Mục nav
`auditNav.requiredActions = ['audit.read']`.

## `GET /api/v1/audit`

| Tham số | Kiểu | Mặc định | Nghĩa |
|---|---|---|---|
| `limit` | int 1..200 | 50 | Số hàng một trang |
| `cursor` | string | — | `nextCursor` của trang trước, gửi NGUYÊN VĂN. Sai dạng → **400 `CURSOR_KHONG_HOP_LE`** |
| `nhom` | string | — | Tiền tố (phần trước dấu chấm đầu của `hanhDong`), nhiều tiền tố cách nhau dấu phẩy, mỗi tiền tố `[a-z_]{1,32}`, tối đa 10. Sai → **422 `NHOM_KHONG_HOP_LE`** |
| `from` | `YYYY-MM-DD` | — | Cận dưới ĐÓNG, ngày theo giờ Việt Nam |
| `to` | `YYYY-MM-DD` | — | Cận trên **MỞ** (`< to`), giờ Việt Nam. Ô «đến hết ngày D» ⇒ gửi `to = D + 1 ngày`. `from >= to` → **422 `KHOANG_KHONG_HOP_LE`** |
| `may` | bool | `false` | `false` ẩn hàng `actorId = "agent"` (agent bootstrap lấy credential VÀ phản hồi của khách gửi qua gateway `agent.feedback`, ~38% số dòng). `true` gộp lại |

Không có khoảng ngày mặc định. Thứ tự luôn **mới nhất trước** (`luc DESC, id DESC`).

Ở `limit=200`, trang cuối đầy đủ vẫn có `nextCursor`; lần «Tải thêm» kế có thể về `items: []` — không phải lỗi.

**200**

```json
{
  "items": [
    {
      "id": 412,
      "luc": "2026-08-25T03:12:44.120931+00:00",
      "hanhDong": "realestate.project.update",
      "actorId": "u_haidt",
      "actorTen": "Hải Đỗ",
      "actorEmail": "hai@noblex.vn",
      "chiTiet": { "project_code": "NT2", "truong": ["name", "price"] }
    }
  ],
  "nextCursor": "MjAyNi0wOC0yNVQwMzoxMjo0NC4xMjA5MzErMDA6MDB8NDEy"
}
```

- `actorId` nguyên văn cột `actor`. Các dạng THẬT trong code (kiểm code + DB dev 2026-08-25): `u_<id>` (người dùng) · `"agent"` (máy — agent bootstrap lấy credential VÀ phản hồi của khách gửi qua gateway `agent.feedback`, ẩn mặc định qua `may`) · `"platform_admin"` (NobleX qua token quản trị) · `"cron"` (job định kỳ, ví dụ `ingest.tenant_im_lang` — `ingest/jobs.py`) · `"ingest"` và `"ingest_token:<id>"` (cổng nạp, ví dụ `ingest.nghi_mat_tich` — `ingest/service.py`) · `"token:<id>"` (importer cũ, `realestate.import.push` — đã bỏ ~15/08/2026, còn 5 hàng trong lịch sử) · `""` (không ghi được người, ví dụ `ingest.token_tao`/`ingest.token_xoa` khi thiếu `created_by`). Chỉ `"agent"` bị `may=false` ẩn; mọi dạng khác luôn trả về. FE hiện: tên người nếu `actorTen` có; `"agent"` → «Agent»; `"platform_admin"` → «NobleX»; `"cron"` và `""` → «Hệ thống»; `"ingest"`/`"ingest_token:*"`/`"token:*"` → «Cổng nạp»; dạng khác → hiện nguyên chuỗi. Danh sách này có thể mọc thêm — FE **không được lọc bỏ** hàng có actor lạ.
- `actorTen`/`actorEmail` là `null` khi `actor` không còn trong `control.users` (người đã bị gỡ — cố
  ý không FK) hoặc là giá trị đặc biệt ở trên. **Đừng lọc bỏ** hàng có tên null.
- `actorTen`/`actorEmail` là giá trị HIỆN TẠI trong `control.users` — người đã rời workspace rồi đổi tên vẫn hiện tên mới, không phải tên lúc hành động xảy ra. Đúng với nhật ký (nó ghi lại AI đang đứng sau `actor` đó, không phải một bản chụp), đừng «sửa».
- `chiTiet` là jsonb nguyên văn, hình dạng KHÁC NHAU theo `hanhDong`; FE tóm tắt `khoá: giá trị`.
- `nextCursor: null` = hết.

## Sổ mã `hanhDong`

Nguồn: `src/portal/core/nhat_ky_ma.py` → artefact `contracts/audit-actions.json` (copy sang repo FE,
cổng `tests/audit-actions-parity.test.ts`). Dạng `<nhóm>.<việc>[.<việc>]`; `nhom` lọc theo `<nhóm>`.

Artefact gồm CẢ mã đang ghi (`MA_HANH_DONG`) LẪN mã đã nghỉ hưu còn trong lịch sử
(`MA_DA_NGHI_HUU` — điểm ghi đã bỏ nhưng `control.audit_log` chỉ ghi thêm nên
hàng cũ vẫn còn). Danh sách mã nghỉ hưu đo trên DB dev 2026-08-25; DB của môi
trường khác có thể mang mã ngoài cả hai tập (di sản trước khi có sổ này) — FE
vẫn giữ fallback hiện nguyên mã thô cho trường hợp đó, đừng coi artefact là đủ
để bỏ fallback.

Lỗi chung: 401 không phiên · 403 thiếu action · 422 validate — envelope `{"error": {"code", "message"}}`.
