# M4a — còn treo sau khi thi công xong

> **Ngày:** 2026-08-03 · Ghi lại từ sổ tiến độ của phiên thi công (12 task, 20 commit).
> Spec: `2026-08-02-m4a-du-lieu-bds-design.md` · Plan: `plans/2026-08-02-m4a-du-lieu-bds.md`
>
> Mọi mục dưới đây **đã được một reviewer nhìn qua và cố ý hoãn**. Không mục nào chặn gộp nhánh.

---

## 1. Lệch giữa spec và code — cần BA/chủ sản phẩm biết

| # | Việc | Ghi chú |
|---|---|---|
| 1 | **Danh sách dự án/căn nay xếp "mới tạo trước", không phải "mới sửa trước"** | Phân trang cursor cần khoá keyset **bất biến**; `updated_at` đổi mỗi lần sửa nên một hàng vừa sửa sẽ nhảy lên đầu và bị lật qua giữa hai trang. `DL_01` đòi **hiện** cột *cập nhật lúc* (vẫn còn trong `DuAnOut`/`CanOut`), **không** đòi sắp xếp theo nó — nên đây là thay đổi hợp lệ, nhưng người dùng nhìn thấy được. |
| 2 | **`GET /projects` và `GET /units` trả `{items, nextCursor}`**, không còn trả mảng trần | Spec §7 hứa phân trang cursor nhưng không chốt hình dạng. Lúc quyết, repo FE mới có `nav.ts` + 4 route rỗng, chưa có `api.ts`, và `contracts/` sinh tự động không chứa hai endpoint này — nên không hợp đồng nào bị phá. **Nếu FE đã bắt đầu thì kiểm lại.** |
| 3 | **Bốn mã lỗi không có trong bảng §7 của spec** | `NOT_FOUND` · `FILTER_KHONG_CHO_PHEP` · `FILE_TOO_LARGE` · `CAN_XAC_NHAN_XOA`. Quy ước cho phép, nhưng hợp đồng FE chưa liệt kê. |
| 4 | **`GET /field-policy?entity=` thay vì `/field-policy/{entity}`** như spec §7 vẽ | Chỉ khác hình dạng đường dẫn. |
| 5 | **`project_progress` không có cột ảnh lẫn cột link** | Spec §2.4 ghi *"mốc tiến độ, ảnh + link"*. Ảnh sang M4b là hợp lý; **link thì chưa ai quyết** — hiện chỉ có `tieu_de` · `moc_ngay` · `ghi_chu`. |
| 6 | **`make dev-seed` không gọi `seed_bds`** | Spec §10 ghi vậy. Thực tế có target `seed-bds` riêng, nối vào `make up`. Kết quả tương đương khi dựng từ số 0. |

## 2. Nợ kỹ thuật — sửa được bất cứ lúc nào

| # | Việc | Chỗ |
|---|---|---|
| 7 | `dem_thieu` nhận **chuỗi SQL thô** trên chữ ký công khai; an toàn hiện dựa vào quy ước *"phải đến từ `menh_de_thieu()`"*. Nên đổi sang nhận `list[str]` và gọi `menh_de_thieu` bên trong — đưa danh sách trắng vào trong kiểu | `repo.py` |
| 8 | `menh_de_thieu` không khử trùng lặp `truong` ⇒ `(direction = '' OR direction = '')` nếu caller truyền danh sách chưa dedupe | `chinh_sach.py` |
| 9 | `_them_gia` chạy **trước** kiểm trùng mã ⇒ mã trùng + giá hỏng trả `ER_02` thay vì `ER_06` | `router.py` |
| 10 | `r = await repo.ghi_overview(...)` là **dead store** — bị gán đè ngay bằng `doc_du_an` | `router.py` |
| 11 | `_KHOA_MUC_CON_JSON_SANG_COT` nhận cả 5 khoá cho cả 3 `loai`; khoá không hợp bị bỏ **im lặng** (`link` trên `progress`, `noiDung` trên `documents`) | `router.py` |
| 12 | Hai lối lọc tenant cạnh nhau: `doc_chinh_sach` dùng `portal.current_tenant()`, `ghi_chinh_sach` dùng `$1` do caller truyền | `repo.py` |
| 13 | `matchOp: null` **không xoá được** cột — PATCH lọc theo `is not None` | `router.py` |
| 14 | `service.ap_dung_import` chạy N round-trip mỗi dòng; 5.000 dòng = 5.000 UPSERT | `service.py` |
| 15 | `kho.ghi` chạy **trong** giao dịch DB ⇒ tệp mồ côi trong kho nếu `tao_job` hỏng | `service.py` |
| 16 | `apply` nhận `than: dict` không kiểu; `soDongSeXoa` gửi dạng `"1"` trượt phép `!=` (fail-closed nên an toàn) | `router.py` |
| 17 | `int(ty * MOT_TY)` **cắt** thay vì làm tròn — lệch dưới 1 VND, rủi ro thực tế thấp | `gia.py` |
| 18 | `"4.7"` cho cột số nguyên vẫn **âm thầm cụt** thành `4` (khác boolean, đã fail-closed) | `nhap_lieu.py` |
| 19 | `job` import quá hạn **không được dọn** — tệp ở lại kho, hàng ở lại DB. Cần quyết retention trước, và retention là việc của **M8** | `import_jobs` |
| 20 | `sale_email` chưa nối `control.users` — lưu chuỗi, chưa kiểm người đó còn là thành viên workspace | `units` |

## 3. Chặn bởi việc của module khác

| # | Việc | Chặn bởi |
|---|---|---|
| 21 | **Không mở được cổng ranh giới module ra cả `scripts/`.** Hai script của module khác đang vi phạm: `gen_contracts.py:17` → `modules.config.tools`, `agent_gia.py:26` → `modules.config.bundle` | Cần `modules/config/contracts.py` re-export trước — **việc của M3/M5** |
| 22 | **N2 — định nghĩa *"đủ dữ liệu cho agent"*** chưa chốt. Cơ chế đã xong và có cổng test chứng minh đổi được bằng API mà không deploy; chỉ thiếu con số | **BA** cùng sales |
| 23 | **Ba cờ cho từng trường** — `seed_bds.py` đặt một bộ mặc định của platform; BA đè lên bằng `PATCH /field-policy` | **BA** |
| 24 | **Ngưỡng độ tươi BR06** (giờ / ngày / tháng) chưa chốt — và nó thuộc phía agent, không phải portal | Gói G |

## 4. Hai mục cho hợp đồng Gói G

Đã ghi vào `specs/2026-08-02-m10-dau-noi-agent-ngoai-design.md §7` (commit `c44fc88`):

- **G-11** — `_serialize.py` bỏ hẳn khoá `NULL`/rỗng trước khi đưa vào ngữ cảnh LLM. Đây là **điều kiện** để `floor`/`building`/`zone` được lên view.
- **G-12** — gỡ hai filter `floor` và `tower` khỏi `schemas.py` của kỹ năng tra căn.

## 5. Ngoài phạm vi, đã có chủ

- **M4b — media dự án** (13 ô ảnh/video của prototype). Spec chưa viết.
- **Giao diện** — hợp đồng ở spec M4a §8; code ở repo `odyssey-portal-frontend`.
- **Ba chỗ prototype lệch spec** (§8.4): cột *Agent dùng* phải là công tắc không phải chip trạng thái · thiếu hai nhãn *Agent dùng trường này* / *Không chia sẻ với khách* · bỏ nhóm SEO.
