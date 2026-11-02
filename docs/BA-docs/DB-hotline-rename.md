# Spec cho team Hotline-agent: thay đổi DB `noble_agent`

**Ngày:** 2026-07-08
**Bối cảnh:** Chat-agent (Luna) nay dùng chung DB `noble_agent` trên `10.50.12.70`. Để tách namespace, đã thao tác một số collection. Doc này **chỉ nêu phần ảnh hưởng tới hotline-agent** — cần team hotline xử lý.

---

## 1. 3 collection đã ĐỔI TÊN (thêm prefix `hotline_`)

Đã chạy `renameCollection` trong Mongo, **giữ nguyên data + index**:

| Tên cũ | Tên mới | Docs |
|---|---|---|
| `bookings_flat` | `hotline_bookings_flat` | 48 |
| `call_events` | `hotline_call_events` | ~250 |
| `call_summaries` | `hotline_call_summaries` | ~93 |

### ‼️ Hotline-agent PHẢI làm gì
Hotline-agent hiện **hardcode tên cũ** (`db.bookings_flat`, `db.call_events`, `db.call_summaries`) trong nhiều file (DAO `storage/*`, `storage/connection.py`, `agent/tools/schedule_viewing.py`, `agent/summary/generator.py`, `server/http.py`, các `scripts/mongo_migrate_*.py`).

**Nếu không sửa + restart:** hotline vẫn đọc/ghi tên cũ → **tự tạo lại** `bookings_flat`/`call_events`/`call_summaries` **rỗng** và ghi data mới vào đó. Data lịch sử nằm ở `hotline_*`, data mới ở tên cũ → **phân mảnh**, dashboard thiếu lịch sử. (Ghi nhận: hotline đang chạy & ghi liên tục lúc rename, nên phân mảnh xảy ra ngay.)

**Cần làm:**
1. Đổi mọi chỗ truy cập collection: `bookings_flat` → `hotline_bookings_flat`, `call_events` → `hotline_call_events`, `call_summaries` → `hotline_call_summaries`.
   - Chỉ đổi **truy cập collection** (`db.<tên>` / `self._mongo_db.<tên>`). **KHÔNG** đổi import path/logger như `storage.bookings_flat`, `logging.getLogger("storage.call_events")`.
2. Redeploy + restart hotline-agent.
3. Nếu trong lúc chờ đã lỡ ghi vào tên cũ → merge phần đó vào `hotline_*` rồi drop collection tên cũ.

> Gợi ý: nên gom tên collection vào **một chỗ cấu hình** (constant/config) thay vì hardcode rải rác, để lần sau đổi tên chỉ sửa 1 nơi.

---

## 2. Startup/script tự tạo lại collection KHÔNG dùng (rỗng)

Trong lúc dọn DB, đã xoá vài collection **rỗng** nhưng chúng **hiện lại** sau đó. Nguyên nhân: hotline-agent tự tạo lại.

**Nguồn tạo:**
- `src/noble_agent_unified/storage/connection.py` → hàm `initialize()` (chạy **mỗi lần hotline khởi động**) gọi `create_index(...)` trên loạt collection → **tạo index = tự sinh collection rỗng** nếu chưa có.
- Các script migration: `scripts/mongo_migrate_noble_profile.py`, `scripts/mongo_migrate_outbound.py`.

**Các collection bị tái tạo dù đang rỗng / không dùng:**
`conversations`, `noble_profiles`, `outbound_calls`, `outbound_briefs`, `bookings`

**Đề nghị team hotline xác nhận & xử lý:**
- Nếu **thật sự không dùng** → gỡ các dòng `create_index` tương ứng trong `connection.py` (và bỏ khỏi migration scripts) để chúng ngừng tái sinh.
- Nếu **có dùng nhưng chưa có data** → giữ nguyên, đây là hành vi đúng (tạo sẵn + index chờ data).
- Riêng `bookings` (khác `bookings_flat`): rỗng, không thấy service nào ghi — nghi legacy, nên xác nhận có thể bỏ.

---

## 3. Collection KHÔNG đụng tới (an tâm)

- **Dùng chung, giữ nguyên:** `project_du_an`, `project_can_ho`, `project_hoi_dap`, `project_media`, `project_ho_so_phap_ly`, `project_chinh_sach_ban_hang`, `project_danh_muc_hoan_thien`, `project_danh_muc_vat_lieu`, `booking_slots`, `booking_config`, `customers`, `session_metrics`.
- **Chưa rõ chủ, chưa đụng (cần team xác nhận):** `agent_messages` (838), `audit_log` (3864), `users` (6).
- Chat-agent chỉ thêm collection prefix `chat_*` của riêng nó — không ảnh hưởng hotline.

---

## 4. Rollback (nếu cần hoàn tác rename)

`renameCollection` ngược: `hotline_bookings_flat` → `bookings_flat`, `hotline_call_events` → `call_events`, `hotline_call_summaries` → `call_summaries` — đồng bộ với trạng thái code hotline-agent (đừng rollback Mongo mà quên rollback code, hoặc ngược lại).