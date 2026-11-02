# Knowledge Base BĐS — viết lại theo `docs/build_module_knowledgebase/`

> **Cho agentic worker:** BẮT BUỘC dùng `superpowers:subagent-driven-development`. Các bước dùng
> checkbox (`- [ ]`).

**Goal:** Thay schema M4a cũ bằng đúng 5 bảng KB của template `real_estate`, bỏ ba cơ chế tài liệu
nói xoá, để tenant nhập được dự án thật và agent đọc được.

**Nguồn sự thật — đọc trước khi code, plan này KHÔNG lặp lại field:**

| File | Dùng cho |
|---|---|
| `docs/build_module_knowledgebase/02-knowledge-base.md` | nguyên tắc chung: anchor · `status` · freshness · cách ly · bộ cột chung |
| `docs/build_module_knowledgebase/02a-real-estate-template.md` | **§3 enum · §4 field từng bảng · §7 template** — đây là đặc tả schema |
| `docs/build_module_knowledgebase/mau-form-cms.html` | đặc tả form (6 tab) + luồng cover/map media |
| `docs/build_module_knowledgebase/00-overview.md` | quyết định nền |

**Architecture:** 5 bảng ở `tenant_data`, anchor `projects`, con trỏ về bằng `project_code`
(FK tổ hợp mang `tenant_id`). Visibility = `status` một cột, cascade theo anchor. Không gate đọc.
Không import. Nhập tay.

## Global Constraints

- **Không lưu trường nội bộ nhạy cảm** (hoa hồng · giá net · chiết khấu). `02 §1` — không lưu thì
  không cần che. Nếu thấy mình đang viết một cơ chế che field, dừng lại: sai hướng.
- **Không `custom_fields`** — template khai đủ cột thật (`02 §6`).
- **Bộ cột chung mọi bảng KB:** `id` · `tenant_id` · `status` · `created_at` · `updated_at`.
  Phase nhập tay: **không** `source`/`external_id`/`synced_at`/`verified_at`.
- **`status` ∈ `draft·published·archived`** trên **mọi** bảng KB. Trạng thái nghiệp vụ là cột
  RIÊNG (`projects.sale_phase`, `units.sale_status`) — đừng gộp.
- **FK tổ hợp `(tenant_id, project_code)`** — Postgres chặn tham chiếu chéo tenant, lưới thứ 2 sau RLS.
- **Mọi bảng `tenant_data` gọi `control.enforce_tenant_isolation()`** — thiếu là cổng 6 của M1 đỏ.
- **Số về đúng kiểu** `numeric`/`bigint`. Giá nhập thẳng VND trên form (`price_vnd · numeric`).
- Mọi route khai `require(action)`; chỉ `catalog.read` · `catalog.write` · `catalog.delete`.
- Truy vấn `tenant_data` qua `tenant_conn(pool, tenant_id)`. Module raise `loi.LoiPortal`.
- Comment/docstring **tiếng Việt**, giải thích *vì sao*. Ruff line-length 120, không `noqa: E402`.

## Ngoài phạm vi — ghi ra để không ai tự ý làm

`organizations`/tenancy 2 tầng (sửa schema `control`, thuộc M2a) · Qdrant 2 collection (M6) ·
**pipeline RAG** (`02b-rag-service.md` **không có** trong repo — embed/chunk/caption chưa có đặc tả) ·
VisionExtractor auto-caption · pdf2text/OCR cho `documents.body` (nhập tay ở phase này).
`media` có bảng + CRUD + upload file; **chưa** embed.

## Cấu trúc file

```
migrations/versions/0400_kb_real_estate.py    ← VIẾT LẠI TẠI CHỖ (chưa release)
migrations/versions/0401_agent_doc_kb.py      ← VIẾT LẠI: bỏ gate
src/portal/modules/realestate/
  contracts.py   viết lại — 5 thực thể
  repo.py        viết lại — 5 bảng
  router.py      viết lại — CRUD 5 thực thể
  completeness.py  🆕 hàm thuần — luật "đủ dữ liệu" của template
  XOÁ: service.py · nhap_lieu.py · chinh_sach.py · gia.py
scripts/seed_bds.py                           ← viết lại: __ALL__ + dữ liệu mẫu
tests/modules/realestate/                     ← viết lại
```

**Vì sao xoá `gia.py`:** form nhập thẳng VND (`price_vnd · numeric`), không còn biên đổi tỷ→VND.
**Vì sao xoá `chinh_sach.py`:** nó phục vụ gate đọc + `field_policy_live`, cả hai bị bỏ.

---

## Task 1: Migration `0400` — 5 bảng KB

**Files:** viết lại `migrations/versions/0400_bds_full_fields.py` → đổi tên file thành
`0400_kb_real_estate.py` (giữ `revision = "0400_bds_full"` để `0401` không phải sửa `down_revision`;
nếu đổi revision id thì phải sửa cả `0401`). Test: viết lại `tests/modules/realestate/test_schema.py`.

**Interfaces — Produces:** 5 bảng `tenant_data.projects` · `zones` · `units` · `documents` · `media`.

- [ ] **Step 1: Đọc đặc tả**

Đọc `docs/build_module_knowledgebase/02a-real-estate-template.md` **§3 (enum) và §4 (field từng
bảng)**. Field list ở đó là đặc tả — chép đúng tên, đúng kiểu, đúng nullable. Đọc thêm `02 §6`
(bộ cột chung) và `02 §2` (anchor + `__ALL__`).

- [ ] **Step 2: Viết test thất bại**

`tests/modules/realestate/test_schema.py` — **thay toàn bộ nội dung cũ**. Test phải phủ:

```python
"""Schema KB BĐS theo template `real_estate` (02a §4).

Đây là bản VIẾT LẠI: schema M4a cũ (gate đọc · agent_enabled · import_jobs · 3 bảng con hẹp)
đã bị thay. Tài liệu `build_module_knowledgebase/` là nguồn sự thật.
"""
import asyncpg, pytest
pytestmark = pytest.mark.integration

BANG_KB = ("projects", "zones", "units", "documents", "media")

# — bộ cột chung (02 §6), mọi bảng KB
@pytest.mark.parametrize("bang", BANG_KB)
async def test_bo_cot_chung(pool, bang):
    for cot in ("id", "tenant_id", "status", "created_at", "updated_at"):
        assert await _co_cot(pool, bang, cot), f"{bang} thiếu {cot}"

# — status 3 giá trị, KHÔNG phải 2 (bỏ agent_enabled, gộp về status — 02 §3)
@pytest.mark.parametrize("bang", BANG_KB)
async def test_status_ba_gia_tri(pool, bang):
    for v in ("draft", "published", "archived"):
        assert await _nhan_duoc_status(pool, bang, v)

# — RLS + FORCE (02 §5)
@pytest.mark.parametrize("bang", BANG_KB)
async def test_rls_force(pool, bang): ...

# — trường nội bộ nhạy cảm KHÔNG được tồn tại (02 §1) — QUÉT ĐỘNG
async def test_khong_co_truong_noi_bo_nhay_cam(pool):
    """Đây là bất biến trung tâm của bản viết lại. Không lưu thì không cần che.
    Cột nào tên gợi hoa hồng/giá net/chiết khấu là sai hướng thiết kế."""
    xau = await pool.fetch(
        """SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema='tenant_data'
              AND (column_name LIKE '%commission%' OR column_name LIKE '%hoa_hong%'
                OR column_name LIKE '%chiet_khau%' OR column_name LIKE '%discount%'
                OR column_name LIKE '%gia_net%' OR column_name LIKE '%net_price%'
                OR column_name LIKE '%bank_support%' OR column_name LIKE '%csbh_full%')""")
    assert not xau, f"trường nội bộ nhạy cảm lọt vào KB: {[dict(r) for r in xau]}"

# — cột hệ cũ phải BIẾN MẤT (02a §2 BỎ)
async def test_cot_he_cu_da_bo(pool):
    for bang, cot in [("projects","slug"),("projects","lat"),("projects","lng"),
                      ("projects","is_featured"),("projects","is_hot"),("projects","sort_hot"),
                      ("projects","sort_order"),("projects","agent_enabled"),
                      ("projects","parent_code"),("units","unit_type"),("units","fund_type"),
                      ("units","check_time"),("units","sale_email"),("units","axis")]:
        assert not await _co_cot(pool, bang, cot), f"{bang}.{cot} lẽ ra đã bị bỏ"

# — bảng hệ cũ phải BIẾN MẤT
async def test_bang_he_cu_da_bo(pool):
    for b in ("project_highlights","project_progress","project_documents","import_jobs"):
        assert await pool.fetchval("SELECT to_regclass($1)", f"tenant_data.{b}") is None

# — FK tổ hợp chặn tham chiếu chéo tenant (02 §2)
async def test_fk_to_hop_chan_tham_chieu_cheo_tenant(pool):
    """Tenant A tạo zone trỏ tới project_code của tenant B ⇒ Postgres từ chối.
    Đây là lưới an toàn THỨ HAI, sau RLS — RLS lọc đọc, FK chặn ghi bậy."""
    ...

# — số về đúng kiểu (02a §1) — FIX nợ hệ cũ lưu chuỗi
async def test_so_dung_kieu(pool):
    for bang, cot, kieu in [("units","price_vnd","numeric"),
                            ("units","area_built_m2","numeric"),
                            ("projects","total_land_area_m2","numeric"),
                            ("projects","total_investment_vnd","bigint"),
                            ("projects","category","ARRAY")]:
        ...
```

Điền đủ helper `_co_cot`/`_nhan_duoc_status` và thân ba test còn để `...`.

- [ ] **Step 3: Chạy test, xác nhận đỏ**

`uv run pytest tests/modules/realestate/test_schema.py -v` → FAIL.

- [ ] **Step 4: Viết migration**

Xoá nội dung `0400_bds_full_fields.py`, đổi tên file thành `0400_kb_real_estate.py`, viết lại.
Header phải nói **vì sao viết lại** (tài liệu mới đảo ba quyết định). Nội dung:

```python
def upgrade() -> None:
    # Bản M4a cũ tạo cột trên projects/units và 4 bảng con. Tài liệu mới đảo
    # thiết kế, và bản cũ CHƯA release — nên xoá sạch rồi dựng lại đúng, thay vì
    # chồng một migration tháo gỡ. Dev DB dựng lại bằng `make reset && make up`.
    op.execute("DROP TABLE IF EXISTS tenant_data.import_jobs")
    op.execute("DROP TABLE IF EXISTS tenant_data.project_documents")
    op.execute("DROP TABLE IF EXISTS tenant_data.project_progress")
    op.execute("DROP TABLE IF EXISTS tenant_data.project_highlights")
    op.execute("DROP VIEW IF EXISTS agent_api.units")       # 0401 dựng lại
    op.execute("DROP VIEW IF EXISTS agent_api.projects")
    op.execute("DROP TABLE IF EXISTS tenant_data.units")
    op.execute("DROP TABLE IF EXISTS tenant_data.projects")

    # 0004 của M1 tạo hai bảng lõi để CHỨNG MINH cách ly. Tài liệu mới đổi hẳn
    # hình dạng chúng, nên dựng lại từ đầu ở đây. `enforce_tenant_isolation()`
    # gọi lại cho từng bảng — cổng 6 của M1 quét mọi bảng tenant_data.
    ...  # 5 CREATE TABLE theo 02a §4
```

**Điểm phải đúng, đọc `02a §4` để lấy field:**

| Bảng | Ghi chú bắt buộc |
|---|---|
| `projects` | `project_code` `UNIQUE(tenant_id, project_code)` · `category text[]` **[N]** · `overview` **text** (không jsonb) · `cover_media_id`/`map_media_id` FK→`media` (nullable, tạo sau bằng `ALTER` vì `media` tham chiếu ngược `projects`) |
| `zones` | `UNIQUE(tenant_id, project_code, zone_code)` · FK `(tenant_id, project_code)` |
| `units` | `unit_code` **index, KHÔNG unique** (02a §4.3) · `sale_status` tách khỏi `status` · `floor` = căn ở tầng mấy, `num_floors` = số tầng CỦA căn — hai thứ khác nhau |
| `documents` | `title` + `body` + `file_url?` · **không `category`** (02a §4.4) |
| `media` | `content_type` ∈ image·video · `category` 7 giá trị · `zone_code?`/`unit_code?` nullable |

**Vòng FK:** `projects.cover_media_id → media.id` và `media.project_code → projects`. Tạo
`projects` trước (chưa có hai cột đó), rồi `media`, rồi `ALTER TABLE projects ADD COLUMN
cover_media_id ... REFERENCES`. Ghi lý do vào comment.

`downgrade()`: drop 5 bảng theo thứ tự ngược phụ thuộc.

- [ ] **Step 5: Dựng lại DB và chạy**

```bash
uv run alembic downgrade 0300_kb_files && uv run alembic upgrade head
uv run pytest tests/modules/realestate/test_schema.py -v
```
⚠️ **CẤM `make reset`** — một session khác đang dùng chung Postgres dev này; xoá volume là xoá
dữ liệu của họ giữa chừng. Dựng lại schema bằng `alembic downgrade <rev> && alembic upgrade head`.

- [ ] **Step 6: Cổng cách ly của M1**

`make test-isolation` → PASS. Đỏ ở đây nghĩa là một trong 5 bảng thiếu `enforce_tenant_isolation()`.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check migrations tests/modules/realestate && uv run ruff format migrations tests/modules/realestate
git add migrations/versions tests/modules/realestate/test_schema.py
git commit -m "feat(kb): migration 0400 viết lại — 5 bảng KB theo template real_estate (T1)"
```

---

## Task 2: Dọn — xoá ba hệ con tài liệu nói bỏ

**Files:** xoá `service.py` · `nhap_lieu.py` · `chinh_sach.py` · `gia.py` và test của chúng;
gỡ mọi tham chiếu trong `router.py`/`repo.py`/`contracts.py` (chúng sẽ được viết lại ở T3/T4 nhưng
suite phải xanh sau task này).

- [ ] **Step 1: Liệt kê chính xác thứ phải xoá**

```bash
cd src/portal/modules/realestate && ls
grep -rn "chinh_sach\|nhap_lieu\|field_policy\|import_jobs\|agent_enabled\|doi_don_vi_gia" \
  src/ tests/ scripts/ | grep -v "\.pyc"
```
Ghi kết quả vào báo cáo trước khi xoá — nó là danh sách việc.

- [ ] **Step 2: Xoá file**

```bash
git rm src/portal/modules/realestate/{service,nhap_lieu,chinh_sach,gia}.py
git rm tests/modules/realestate/{test_import,test_nhap_lieu,test_chinh_sach,test_chinh_sach_api,test_gia,test_bo_loc_co_du_lieu,test_seed_bds,test_overview_va_bang_con,test_phan_trang,test_crud,test_repo,test_agent_doc_duoc}.py
git rm -r tests/fixtures/import
```
`test_nhat_ky_day_du.py` **GIỮ** — cổng quét động nhật ký vẫn đúng, T4 sẽ làm nó xanh lại.

- [ ] **Step 3: Rút hai cột khỏi `control.field_policy_live`**

Bản M4a cũ thêm `form_visible` + `required_for_agent` vào bảng của M1 cho gate đọc. Tài liệu bỏ
gate, và `01 §6` ghi `field_definitions` **không dùng cho real_estate**. Rút hai cột đó trong
`0400` (`ALTER TABLE control.field_policy_live DROP COLUMN ...`), và ghi lý do.

- [ ] **Step 4: Làm suite xanh**

`router.py`/`repo.py`/`contracts.py` tạm rút về mức tối thiểu import được (T3/T4 viết lại đầy đủ).
Mục tiêu của bước này: `make test` xanh, `make lint` sạch, `tests/api` xanh (registry vẫn quét được
router), `tests/test_module_boundaries.py` xanh (`contracts.py` còn tồn tại).

- [ ] **Step 5: Chạy + commit**

```bash
make test && make lint
git commit -m "chore(kb): xoá gate đọc · import hai bước · field-policy — tài liệu mới bỏ cả ba (T2)"
```

---

## Task 3: `contracts.py` + `repo.py` cho 5 bảng

**Files:** viết lại cả hai. Test: `tests/modules/realestate/test_repo.py` (mới).

**Interfaces — Produces:** với mỗi thực thể `project`·`zone`·`unit`·`document`·`media`:
`repo.liet_ke_<x>(conn, *, ..., limit, cursor)` · `doc_<x>(conn, ...)` · `chen_<x>` · `sua_<x>` ·
`xoa_<x>`. Contracts: `DuAnOut`·`PhanKhuOut`·`CanOut`·`TaiLieuOut`·`MediaOut` (camelCase HTTP).

- [ ] **Step 1: Đọc lại `02a §4`** để lấy field, và `mau-form-cms.html` để biết field nào bắt buộc
  trên form (dấu `*`): `project_code`·`name`·`category`·`region` · `zone_code` · `unit_code`·
  `product_type` · `title`+file cho document.

- [ ] **Step 2: Viết test thất bại** — phủ: ghi/đọc từng thực thể · cascade `status` (anchor
  `draft` ⇒ con không lên kết quả agent) · phân trang cursor giữ nguyên như bản cũ ·
  **cross-tenant qua `portal_api`** (KHÔNG dùng fixture `pool` — nó là `portal_migrator`,
  `rolsuper=t rolbypassrls=t`, test cách ly chạy qua nó xanh cả khi RLS tắt hẳn).

- [ ] **Step 3–5:** viết `contracts.py` rồi `repo.py`, chạy test tới xanh.

Giữ từ bản cũ: `_upsert` một đường cho thêm+sửa · `clock_timestamp()` **cả nhánh INSERT lẫn UPDATE** ·
danh sách trắng tên cột trước khi ghép SQL · `xoa_theo_ma([])` xoá 0 hàng · phân trang keyset.

- [ ] **Step 6: Lint + commit**

---

## Task 4: `router.py` — CRUD 5 thực thể

**Files:** viết lại `router.py`. Test: `tests/modules/realestate/test_crud.py` (mới).

- [ ] **Step 1: Đọc `mau-form-cms.html`** — 6 tab, và hai luật UX:
  1. **Con kế thừa `project_code`** từ dự án đang mở, không nhập lại. *"Phải lưu dự án trước rồi
     mới thêm dữ liệu con."* ⇒ API con nhận `project_code` trên **đường dẫn**, không trong thân.
  2. **Ảnh cover/mặt bằng:** upload → hệ tạo **1 row `media`** đúng `category` → gán
     `cover_media_id`/`map_media_id`. Một thao tác của người dùng, hai lần ghi, **một giao dịch**.

- [ ] **Step 2: Viết test thất bại** — CRUD 5 thực thể · cascade `status` · `POST` trùng mã ⇒ 409
  (dùng `ON CONFLICT DO NOTHING` rồi phát hiện không chèn được, **không** SELECT-rồi-UPSERT: hai
  POST đồng thời sẽ ghi đè nhau) · con của dự án không tồn tại ⇒ 404 · mọi route ghi vào nhật ký.

- [ ] **Step 3: Viết router.** Đường dẫn theo cây anchor:

```
GET  POST         /projects
GET  PATCH DELETE /projects/{project_code}
GET  POST         /projects/{project_code}/zones
GET  PATCH DELETE /projects/{project_code}/zones/{zone_code}
GET  POST         /projects/{project_code}/units
GET  PATCH DELETE /projects/{project_code}/units/{unit_code}
GET  POST         /projects/{project_code}/documents        ← "__ALL__" = tài liệu chung tenant
GET  PATCH DELETE /projects/{project_code}/documents/{id}
GET  POST         /projects/{project_code}/media
GET  PATCH DELETE /projects/{project_code}/media/{id}
```

- [ ] **Step 4–6:** chạy test tới xanh, `test_nhat_ky_day_du.py` phải xanh lại, lint, commit.

---

## Task 5: Completeness + seed

**Files:** `completeness.py` (mới, hàm thuần) · viết lại `scripts/seed_bds.py` ·
`tests/modules/realestate/test_completeness.py` · `test_seed.py`.

- [ ] **Step 1: `completeness.py` — hằng số template, không phải bảng cấu hình**

`02a §7` đã chốt (đây là N2, tài liệu trả lời rồi):

```python
BAT_BUOC = {
    "project": ("name", "region", "overview"),
    "unit": ("price_vnd", "area_built_m2", "sale_status"),
}

def thieu_truong(entity: str, ban_ghi: Mapping) -> list[str]:
    """Trả danh sách trường còn thiếu. Rỗng = đủ dữ liệu cho agent.

    HÀM THUẦN, và luật là HẰNG SỐ của template — `02 §3`: completeness "tính lúc
    publish/đọc, KHÔNG lưu cột". Bản M4a cũ dựng một bảng cấu hình cho việc này;
    tài liệu đã chốt sẵn nên bảng đó là công thừa.
    """
```

- [ ] **Step 2: Chặn publish khi thiếu** — `PATCH status=published` mà `thieu_truong()` không rỗng
  ⇒ 422 kèm danh sách trường. `02 §3`: *"chặn publish + badge UI"*.

- [ ] **Step 3: `seed_bds.py` viết lại**
  - Seed **row anchor hệ thống** `project_code="__ALL__"`, `name="Chung / toàn tenant"`,
    `status=published` cho mỗi tenant (`02 §2`, `02a §4b`) — giữ FK hợp lệ cho tài liệu cấp tenant.
  - Seed dữ liệu mẫu: 2–3 dự án, mỗi dự án 1–2 zone và ~10 unit, vài `documents`. Giá **VND thẳng**.
  - Idempotent `ON CONFLICT DO NOTHING`, giữ rào chắn localhost.
  - **Bỏ** phần seed 56 hàng `field_policy_live` — bảng đó không dùng cho real_estate.

- [ ] **Step 4–6:** test, chạy `make seed-bds` (KHÔNG `make reset` — xem T1 Step 5), lint, commit.

---

## Task 6: Lớp đọc của agent + cổng cách ly

**Files:** viết lại `migrations/versions/0401_agent_api_bds.py` → `0401_agent_doc_kb.py`.
Test: `tests/modules/realestate/test_agent_doc_duoc.py` (mới).

- [ ] **Step 1: Đọc `00 §5b` và `02 §7`** — agent đọc **tất**, không gate; chỉ thấy bản
  `published` với anchor cha cũng `published`; kèm mốc `updated_at`.

- [ ] **Step 2: Quyết hình dạng lớp đọc và GHI LÝ DO VÀO HEADER**

`00 §2.1` nói *"không dùng `VIEW agent_*`"*. Nhưng `0005_agent_api.py` của M1 cho agent **zero
privilege** trên `tenant_data` và chỉ `SELECT` trên view — tính chất đó **mạnh hơn** cái tài liệu
đòi. Hai đường:

- **(a) Giữ view, bỏ gate** — view `SELECT` mọi cột + `WHERE tenant + status='published' + anchor
  published`. Giữ nguyên zero-privilege của M1, bỏ đúng cái tài liệu bảo bỏ (gate cột).
- **(b) Theo chữ:** `GRANT SELECT` thẳng `tenant_data` cho `agent_all`, RLS lọc.

**Đề xuất (a)** — nó thoả yêu cầu của tài liệu (không che cột) mà không nới quyền của agent, và
không phải sửa migration của M1. Chọn (b) thì phải sửa `0003`/`0005` — việc của M1, không phải
của task này. Ghi rõ lựa chọn và lý do vào header migration.

- [ ] **Step 3: Viết test thất bại** — chạy bằng **role agent thật** (`agent_<slug>`), không phải
  `portal_api`:
  - cách ly hàng: A không thấy dữ liệu B (5 bảng)
  - cascade: dự án `draft` ⇒ zones/units/documents/media của nó **biến mất hết**
  - `__ALL__`: tài liệu chung tenant **vẫn thấy** khi lọc theo một dự án khác (`02 §2`:
    truy hồi gộp `IN {dự_án_active, "__ALL__"}`)
  - **quét động:** không cột nào của lớp đọc mang tên gợi trường nội bộ nhạy cảm
  - agent **không** chạm được bảng gốc `tenant_data` (nếu chọn (a))

- [ ] **Step 4–6:** viết migration, chạy `alembic upgrade/downgrade/upgrade`, `make test-isolation`,
  lint, commit.

---

## Sau khi xong

**Cần gì nữa để tenant dùng được:** giao diện. Repo `odyssey-portal-frontend` mới có `nav.ts` và
4 route rỗng; `mau-form-cms.html` là đặc tả form (6 tab). Đó là việc kế tiếp, và nó chỉ nên bắt đầu
sau khi schema này chốt.

**Còn treo, có chủ ở nơi khác:** `organizations`/tenancy 2 tầng (M2a) · Qdrant 2 collection
`<slug>_documents` + `<slug>_media` (M6, hiện 1 collection `kb_<tenant_id>`) · pipeline RAG
(`02b-rag-service.md` chưa có trong repo) · auto-caption media · pdf2text/OCR cho `documents.body`.
