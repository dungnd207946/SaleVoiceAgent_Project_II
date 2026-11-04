# Thiết kế: Chuyển 3 tool dự án sang MongoDB + canonical hoá mã dự án theo DB

**Ngày:** 2026-07-02
**Branch:** `feat/connect-db`
**Trạng thái:** Đã duyệt thiết kế, chờ viết plan.

## 1. Bối cảnh & vấn đề

Ba tool `list_projects` / `get_project_overview` / `match_projects`
([projects_info.py](../../../src/noble_agent/agent/tools/projects_info.py)) hiện đọc từ
dict tĩnh `data/project_registry.py` (355 dòng, hardcode 15 dự án). Yêu cầu: chuyển sang
đọc dữ liệu thực từ MongoDB.

Hai collection nguồn (host `10.50.12.70`, DB `noble_agent`):

- **`project_du_an`** — tổng quan dự án (15 doc). Khóa: `_id` (ObjectId), `ma_du_an` (mã dự án).
- **`project_can_ho`** — tồn kho căn hộ (mở-list). FK `du_an_id` = `str(project_du_an._id)`.
  Hiện chỉ 2 dự án (`SLC`, `NTTL`) có căn hộ.

> Lưu ý: 2 file schema BA ban đầu được tham chiếu (`docs/BA-docs/project_du_an_schema.md`,
> `project_data_can_ho.md`) **không tồn tại** trong repo. Tên trường dưới đây lấy trực tiếp
> từ DB live + từ bản đã chạy trên branch `feat/seperate-service`.

### Phát hiện then chốt: mã DB ≠ mã app, và corpus RAG đã theo mã DB

`ma_du_an` trong DB khác mã canonical của app ở 4 dự án:

| Mã app (catalog hiện tại) | `ma_du_an` DB |
|---|---|
| `NCRS` | `NCR` |
| `SSLC` | `SLC` |
| `ASM` | `ALLUVIA` |
| `ALUMI` | `Alumi` (lệch cả hoa/thường) |
| 11 mã còn lại | trùng |

Kiểm tra Qdrant live (root `document_v3`, clone `noble_kb_hybrid`): payload `project_id`
**đã dùng mã DB** (`NCR`, `SLC`, `ALLUVIA`, `Alumi`, ...), `project_name` = `ten_thuong_mai`.

Hệ quả — **bug retrieval tiềm ẩn hiện tại**: `noble_search` gọi `catalog.normalize()` →
trả mã app (`ASM`/`SSLC`/`NCRS`/`ALUMI`) → lọc Qdrant `project_id == "ASM"` trong khi corpus
chỉ có `"ALLUVIA"` → **0 hit cho 4 dự án lệch mã** dù corpus có 5–35 chunk mỗi dự án.

### Nguyên tắc gốc của thiết kế

**Canonical hoá toàn app theo mã `ma_du_an` của DB** (đúng giá trị corpus đang dùng).
Không build lại corpus — chỉ kéo tầng app (`catalog` + enum) về khớp DB. Việc này vừa đáp
ứng yêu cầu ("mã lấy từ DB"), vừa vá bug retrieval 4 dự án.

## 2. Kiến trúc & thành phần

### 2.1. Module mới `data/db_project_registry.py` — nguồn mã dự án động từ DB

Đây là "dict dự án lấy từ DB" mà yêu cầu nhắc tới, dùng để bơm động vào các chỗ hardcode.

- **Cache singleton** in-memory: `{code: {"code","name","region","type"}}` với `code` =
  `ma_du_an` **giữ nguyên hoa/thường** của DB.
- **API:**
  - `async warm() -> None` — load từ `project_du_an`, populate cache. Gọi 1 lần lúc startup.
    Bọc try/except, thất bại thì giữ cache rỗng (rơi về fallback).
  - `cached_codes() -> list[str]` — **sync, không I/O**: trả code trong cache, hoặc
    `_FALLBACK_CODES` nếu cache rỗng. Dùng cho `schemas_for` (đồng bộ).
  - `code_to_name() -> dict[str,str]` — sync, cache-or-fallback.
  - `resolve(raw) -> str` — mã/tên → code DB (hoặc `""`). Dùng khi cần phân giải động.
- **`_FALLBACK_CODES`** (hằng đóng trong code, = 15 mã DB hiện tại):
  `ALLUVIA, Alumi, NCLB, NCR, NCTH, NPLB, NPTH, NTTL, SBR, SCHN, SGI, SGR, SLC, SRP, SSC`.
  Bảo đảm enum không bao giờ rỗng khi Mongo down.
- Mapping trường: `ten_thuong_mai→name`, `khu_vuc→region`, `loai_hinh_sp→type`.

### 2.2. Port tầng Mongo `data/structured_data.py` từ `feat/seperate-service`

Thay bản mock **sync** cũ bằng bản async Mongo-backed. Vì các hàm chuyển sang `async`,
phải **đồng thời cập nhật `agent/tools/project_financial.py`** sang bản async (port từ
seperate-service: `await _sd.*` + trả `ESCALATE_SIGNAL` khi kết quả `None`) — nếu không sẽ
gọi coroutine mà không `await`. Branch hiện tại đang nhất quán ở bản sync (KHÔNG crash), nên
đây là nâng cấp cả cặp `structured_data` + `project_financial` cùng lúc.

- Giữ `ESCALATE_SIGNAL = "Thông tin đã được chuyển đến chuyên viên tư vấn"`.
- **Bỏ `_CODE_ALIASES`** (giờ mã app = mã DB → không cần dịch). Phân giải mã dùng
  `catalog.normalize` (đã đổi về mã DB) thay cho `project_registry.normalize_project`.
- Trường `project_can_ho` đã dùng: `du_an_id`, `ma_can`, `loai_san_pham`, `dai_tang`,
  `huong`, `so_phong_ngu`, `dien_tich_tim_tuong_m2`, `dien_tich_thong_thuy_m2`, `gia_vnd`,
  `gia_m2_vnd`, `trang_thai`, `tam_nhin`, `anh_url`, `chiet_khau_toi_da_pct`.
- `payment_plans`/`loan_policies`/`promotions`/`fees` không có nguồn trong 2 collection →
  trả `None` → tool trả `ESCALATE_SIGNAL`.

### 2.3. Viết lại `agent/tools/projects_info.py` (3 hàm) → Mongo

Port logic seperate-service (`list_projects_data`/`get_project_overview_data`), nhưng:

- `code` trả về = `ma_du_an` **nguyên văn** (KHÔNG `.upper()`), để khớp case corpus (`Alumi`).
- Field mapping overview: `code, name(ten_thuong_mai), region(khu_vuc), district(vi_tri),
  type(loai_hinh_sp), units(tong_so_can), management(don_vi_van_hanh), investor(chu_dau_tu),
  ownership(hinh_thuc_so_huu), handover(tien_do_ban_giao), land_area_m2(dien_tich_dat_m2),
  total_investment_vnd(tong_muc_dau_tu_vnd)`. Bỏ các trường không có trong DB (`towers`,
  `aliases`, `district`-list cũ...).
- Trường DB rỗng → `""`. Tất cả trường rỗng / không tìm thấy / Mongo down → trả
  `ESCALATE_SIGNAL` → Luna gọi `escalate`.
- `match_projects` vẫn trả danh sách + `instruction` để LLM tự chọn (giữ hành vi cũ), nguồn
  danh sách từ Mongo.

### 2.4. Sửa `agent/catalog.py` — surgical, giữ nguyên engine alias

Chỉ đổi 4 chuỗi `code` trong `_REGISTRY` về mã DB; **không đụng** alias/regex/quy tắc mơ hồ:

- `"NCRS"→"NCR"`, `"SSLC"→"SLC"`, `"ASM"→"ALLUVIA"`, `"ALUMI"→"Alumi"`.
- **Xử lý case của `Alumi`:** `normalize()` dòng 244-246 đang `up = s.upper()` rồi so
  `VALID_CODES`. Phải chỉnh để mã `Alumi` được trả **đúng case DB** (không upper cưỡng bức),
  ví dụ so khớp case-insensitive rồi map về code gốc trong `_BY_CODE`. `by_code()` cũng
  đang `.upper()` — chỉnh tương tự để tra được `Alumi`.
- Sau khi đổi: `normalize` trả mã DB → `noble_search` lọc khớp corpus (fix bug), và
  `update_customer` lưu mã DB vào Redis → nhất quán với corpus.

`catalog` được dùng ở 6 nơi (`session_store`, `schedule_viewing`, `noble_search`,
`update_customer`, `grep_search`, `noble_kb`) → sửa 1 chỗ fix đồng loạt.

### 2.5. Enum động cho `noble_search.project_filter`

- Trong `schemas.py`, khi build schema `noble_search`, gán
  `enum = [""] + db_project_registry.cached_codes()` (sync, cache-or-fallback) thay vì mảng
  hardcode. Cập nhật description các tool nhắc "canonical".
- `schemas_for` được gọi ở `agent/base.py:51` lúc load agent-def (sau startup) → cache đã ấm.

### 2.6. Startup warm

- aiortc: gọi `await db_project_registry.warm()` trong
  [`server/http.py::_run_server_async`](../../../src/noble_agent/server/http.py) (cạnh
  `_maybe_reconcile_qdrant()`), bọc try/except — boot phải sống sót nếu Mongo lỗi.
- livekit: warm trong entrypoint worker tương ứng.

### 2.7. Dọn `data/project_registry.py`

Sau khi 2.2/2.3 hết phụ thuộc, module này mồ côi trong `src/` (chỉ `projects_info` + 1 test
+ 1 comment script dùng). **Xóa** `data/project_registry.py` +
`tests/unit/test_data_project_registry.py`; sửa comment ở `scripts/gen_responses/scenarios.py`.
Nếu phát hiện consumer ẩn khi implement → giữ lại và ghi chú.

## 3. Xử lý lỗi

- `get_db()` đã trả `None` khi Mongo lỗi/thiếu config. Mọi hàm data bọc sẵn → tool trả
  `ESCALATE_SIGNAL`.
- `db_project_registry.warm()` fail → cache rỗng → `cached_codes()` rơi về `_FALLBACK_CODES`
  → enum vẫn đủ 15 mã, boot không vỡ.

## 4. Kiểm thử

- **Unit** (fake in-memory db, theo mẫu `test_project_financial_mongo.py` của seperate-service):
  - `projects_info`: mapping trường; trường rỗng→`""`; all-empty/unknown/Mongo-down→`ESCALATE_SIGNAL`;
    `code` giữ nguyên case (`Alumi`).
  - `catalog`: `normalize` trả mã DB cho 4 dự án lệch (`"alluvia sunshine marina"→"ALLUVIA"`,
    `"Alumi"→"Alumi"`, `"legend city"→"SLC"`, `"riverside"→"NCR"`); 11 mã còn lại không đổi;
    token mơ hồ vẫn `""`.
  - `db_project_registry`: `cached_codes()` fallback khi cache rỗng; `resolve` mã↔tên.
  - Port `test_project_financial_mongo.py`.
- **Verify:** `make lint`, `make test-unit`; và `make eval-estate-smoke` để xác nhận
  retrieval 4 dự án lệch mã giờ có hit.

## 5. Ngoài phạm vi

- Không build lại corpus Qdrant (đã theo mã DB).
- Không đổi schema DB, không đụng các collection khác.
- Không refactor engine alias của `catalog` (chỉ đổi 4 giá trị mã).
- `payment_plans/loan_policies/promotions/fees` vẫn escalate (không có nguồn) — giữ nguyên.

## 6. Cập nhật CLAUDE.md

Thêm 1 dòng Change Log + cập nhật mục RAG/tool catalog: 3 tool dự án giờ Mongo-backed;
mã canonical = `ma_du_an` DB; enum `noble_search` sinh động từ `db_project_registry`.
