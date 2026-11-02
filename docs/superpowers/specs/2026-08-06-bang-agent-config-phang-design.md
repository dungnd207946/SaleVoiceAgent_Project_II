# `tenant_data.agent_config` — bản phẳng của cấu hình agent

Ngày: 2026-08-06 · Trạng thái: đã thi công (migration `0910_agent_config`)

## Vấn đề

Cấu hình tab Agent & Kênh chỉ tồn tại dưới dạng `jsonb` lồng ba tầng ở
`control.config_drafts.payload` (nháp) và `control.config_versions.payload` (đã xuất bản).
Đọc bằng máy được, đọc bằng mắt và query bằng SQL thường thì không. Cần một bảng PHẲNG để
dùng nhanh, KHÔNG thay thế hai bảng kia.

## Quyết định

| Điểm | Chốt | Vì sao |
|---|---|---|
| Schema · tên | `tenant_data.agent_config` | Dữ liệu nghiệp vụ của tenant, không phải control-plane. Tên chưa bị dùng ở đâu (đã quét). |
| Số hàng | 1 hàng/tenant, `UNIQUE (tenant_id)`, UPSERT | Lịch sử đã có ở `config_versions` (bất biến + `bundle_sha`). Hai nơi giữ lịch sử ⇒ ngày chúng lệch không ai biết bên nào đúng. |
| Cột | Đúng 12 input trên form + `version`/`created_at`/`updated_at` | `pham_vi.linh_vuc` KHÔNG có cột: không phải input (MVP khoá `realestate`). |
| Kỹ năng | `skills jsonb` = mảng mã ĐANG BẬT, + index GIN | Catalogue còn tăng (nay 12); dạng object 12 khoá true/false làm mọi hàng cũ thiếu khoá khi thêm kỹ năng thứ 13. Query: `skills @> '["booking"]'`. |
| Thời điểm ghi | CHỈ `POST /config/publish` (Lưu và áp dụng) | Bảng mang cấu hình ĐANG PHỤC VỤ KHÁCH. Ghi lúc nháp ⇒ người đọc không phân biệt được nháp với bản đang chạy. |
| Vị trí ghi | Trong cùng `conn.transaction()` với `them_version()` + `dat_con_tro()`, sau khi có số version | Hàng phẳng lệch `config_live` là lỗi IM LẶNG. Đánh đổi đã nhận: lỗi UPSERT làm cả lần publish vỡ (bản nháp còn nguyên, không có bản nào ra khách). |
| RLS | KHÔNG gọi `enforce_tenant_isolation()` | 0909 đã dỡ RLS toàn `tenant_data`. Bật lại cho một bảng ⇒ `FORCE RLS` chặn chính đường publish (connection control-plane không set `app.tenant_id`), và một bảng có RLS giữa 12 bảng không có là bảo vệ giả. Cách ly do tầng API giữ: `tenant_id` luôn từ `Principal`. |
| GRANT | Viết tay `portal_api` (DML) + sequence | `tenant_data` không có default privileges cho `portal_api`; grant vốn nằm trong `enforce_tenant_isolation()`. `PUBLIC SELECT` thừa hưởng từ 0909. |

## Ánh xạ trường

| Ô trên form | Cột | Nguồn trong `ConfigPayload` |
|---|---|---|
| Tên agent | `name` | `danh_tinh.ten_agent` |
| Tên thương hiệu | `brand_name` | `danh_tinh.ten_thuong_hieu` |
| Agent tự xưng | `self_pronoun` | `danh_tinh.tu_xung` |
| Gọi khách là | `customer_pronoun` | `danh_tinh.goi_khach` |
| Lời chào | `greeting` | `danh_tinh.loi_chao` |
| Agent làm gì | `scope_does` | `pham_vi.lam_gi` |
| Agent không làm gì | `scope_does_not` | `pham_vi.khong_lam_gi` |
| Câu từ chối ngoài phạm vi | `refusal_line` | `pham_vi.cau_tu_choi` |
| Phòng ban (≤8 dòng) | `departments jsonb` | `pham_vi.phong_ban` (giữ khoá `ten`/`khi_nao`) |
| Giọng điệu | `tone` | `giong.giong_dieu` (CHECK 3 preset) |
| Độ dài trả lời | `reply_length` | `giong.do_dai` (CHECK 3 mức) |
| 12 nút kỹ năng | `skills jsonb` | `tools.enabled` (giữ nguyên thứ tự) |

## Tệp

- `migrations/versions/0910_bang_agent_config.py` — DDL + index + GRANT.
- `src/portal/modules/config/agent_config.py` — `hang_phang()` (ánh xạ thuần) + `luu()` (UPSERT).
  Cả đường ghi gói trong một file: xoá nó + một lời gọi + một `DROP TABLE` là gỡ sạch tính năng.
- `src/portal/modules/config/service.py` — thêm 1 lời gọi trong `publish()`.
- `tests/modules/config/test_agent_config.py` — 4 test ánh xạ (không cần Postgres, gồm cổng
  khớp `contracts.GIONG_DIEU`/`DO_DAI` với CHECK trong migration) + 4 test đầu-cuối.

## Không làm

Không sửa FE: Lưu và áp dụng đã là `ghiBanNhap(form)` → `xuatBan()`, nên bảng phẳng nhận
đúng thứ đang hiện trên form. Không thêm cột `role`: form không có ô nào tên vai trò.

## Bổ sung 2026-08-06 — tách `xung_ho`

Payload lên **schema v3**: `danh_tinh.xung_ho` (một ô, `"em ↔ anh/chị"`) tách thành
`tu_xung` (`"em"`) + `goi_khach` (`"anh/chị"`), tối đa 20 ký tự mỗi ô. Bảng phẳng đổi theo:
`addressing` → `self_pronoun` + `customer_pronoun` (sửa tại chỗ trong 0910, chưa deploy đâu).
`bundle._soul()` giờ DỰNG câu *"Bạn tự xưng là «…», và gọi khách là «…»."* thay vì đưa nguyên
văn ô người dùng gõ vào persona — chính là rào BR02 mà một ô tự do đã hở.

Hàng v2 cũ: KHÔNG adapter, KHÔNG sửa hàng cũ. Ba đường đọc hàng cũ đi qua
`service.doc_payload_cu()` (trả `None` khi không validate được): `GET /draft` trả bộ mặc định,
`POST /preview` coi như chưa có bản cũ, `publish` diễn biến trống. Cổng:
`tests/modules/config/test_payload_v2_cu.py`.

## Nợ đã biết

Cổng 6 (`test_isolation_catalog::test_moi_bang_tenant_data_da_bat_cach_ly`) liệt kê bảng này
cùng 12 bảng `tenant_data` còn lại — cổng đó đỏ cho cả schema từ 0909, không phải vì 0910.
Khôi phục RLS thì khôi phục cho cả schema, một lần.
