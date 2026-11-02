# Merge structured-data tools (6→3) — Portal catch-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catch Portal (backend + frontend) up with the agent-side tool merge — `get_project_overview`/`recommend_units`/`check_inventory` retire into `discover_projects`/`search_units`/`analyze_projects` — so the skills catalog, its labels, its defaults, and existing tenant rows all agree.

**Architecture:** `modules/config/tools.py` (backend) is the single source of truth for the skills catalog; `contracts/tools.json` is generated from it (`make contracts`) and hand-copied into the frontend, which mirrors it in `src/lib/tools.ts`. The backend's `Tools._kiem_ky_nang` Pydantic validator already whitelists `skills` against `TEN_KY_NANG` at save time — updating the catalog is what makes it reject the three retiring names, no new validation code is needed. A data-only Alembic migration renames the three old names inside existing `tenant_data.agent_config.skills` rows and bumps `version` (required — the agent pins its runtime per `(tenant, version)`).

**Tech Stack:** Python/FastAPI/Pydantic/Alembic (backend), TypeScript/Vitest (frontend), raw SQL migration.

**Spec:** `odyssey-portal-frontend/docs/product/2026-09-07-tool-merge-portal-handoff.md` (handoff from the agent team — read first, especially §2 catalog table, §4 migration SQL, §5 per-tenant decision).

## Global Constraints

- Do not change `ConfigPayload`'s field *shape* — only the allowed *values* inside `tools.enabled` change. No `schema_version` bump (per backend CLAUDE.md: bump is for renamed/deleted fields, not enum-value changes).
- `contracts/*.json` are generated artefacts — never hand-edit `contracts/tools.json` in either repo; regenerate via `make contracts` (backend) and copy the file over.
- Migration data must be frozen inline in the migration file (no `from portal.modules.config.tools import ...`) per backend CLAUDE.md's migration rules.
- Decisions already made by the user (do not re-litigate):
  - Widen `check_inventory` → `analyze_projects` for tenants currently on the old name, exactly per the handoff's default SQL (§4) — user explicitly accepted the risk noted in the frontend Change Log (2026-09-07: `analyze_projects` sandbox isn't tenant-isolated yet).
  - Prepare the migration file only — do **not** run it against staging (`10.50.13.208`) or any live DB. The user runs it themselves.
- **Open question NOT resolved by this plan, flagged for the agent team / user**: whether `discover_projects`/`search_units`/`analyze_projects` now need new `PHU_THUOC` (dependency) entries now that they've absorbed tools that previously depended on `find_project`/`search_units`. Neither portal repo has visibility into the actual new tool parameter schemas (that lives in `odyssey-agent`). This plan makes the conservative choice: drop the retiring keys from `PHU_THUOC`, add no new ones. If the merged tools now accept `project_code` optionally, a follow-up should add `discover_projects`/`search_units`/`analyze_projects` → `("find_project",)` — but that's a guess this plan does not make.
- **Deliberate deviation from the literal migration default for new-workspace defaults**: `KY_NANG_MAC_DINH` currently defaults `check_inventory` on for every new workspace. This plan does **not** replace it with `analyze_projects` in the default set, because `tools.py`'s own existing comment (added 2026-09-07, same day as the handoff) explicitly says "đừng publish 'skills' có tên này cho tenant thật trước đó" for `analyze_projects`. The user's migration-widening decision was about the DB migration for tenants that already opted into inventory-checking, not about handing the SQL tool to every brand-new workspace by default. `check_inventory` is simply dropped from the default set (workspaces lose the default "check inventory" capability until someone deliberately enables `analyze_projects` per-tenant later). Flag this to the user if they disagree.

---

## Task 1: Backend catalog — `modules/config/tools.py`

**Files:**
- Modify: `src/portal/modules/config/tools.py`

**Interfaces:**
- Produces: `MUOI_HAI_KY_NANG` (10 entries, was 13), `TEN_KY_NANG` (derived frozenset, 10 names), `PHU_THUOC` (3 keys, was 6) — all consumed by `contracts.py::Tools._kiem_ky_nang`, `scripts/gen_contracts.py`, and every test in Task 3.

- [ ] **Step 1: Edit `MUOI_HAI_KY_NANG`** — remove the `get_project_overview`, `check_inventory`, `recommend_units` entries; update the label (`nhan`) and description (`mo_ta`) of `discover_projects`, `search_units`, `analyze_projects` per the handoff's §2.1 table. Keep every other entry (`find_project`, `get_document`, `kb_search`, `booking`, `update_customer`, `send_media`, `escalate`) and the existing safety comment above `analyze_projects` untouched. Result must be exactly 10 entries in this order:

```python
MUOI_HAI_KY_NANG: tuple[KyNang, ...] = (
    KyNang(
        "find_project", "Nhận diện tên dự án", "Tra mã dự án từ tên khách nói, chịu được nói tắt hoặc sai chính tả."
    ),
    KyNang(
        "discover_projects",
        "Khám phá & giới thiệu dự án",
        "Danh sách dự án theo tiêu chí (khu vực/ngân sách/loại hình/CĐT) và tổng quan chi tiết một dự án.",
    ),
    KyNang(
        "get_document",
        "Gửi tài liệu của dự án",
        "Lấy file CSBH, pháp lý, brochure của một dự án khi khách xin file.",
    ),
    KyNang(
        "search_units",
        "Tìm & gợi ý căn",
        "Tra căn trong một dự án hoặc gợi ý xuyên dự án theo ngân sách; kèm tư vấn phong thuỷ "
        "khi khách hỏi hướng hợp mệnh.",
    ),
    KyNang(
        "kb_search", "Tra tài liệu của workspace", "Tìm trong tài liệu khách đã nạp: chính sách, quy trình, phí, FAQ."
    ),
    KyNang("booking", "Đặt lịch tham quan", "Chốt lịch xem nhà. Theo giao thức ba bước, có code guard đi kèm."),
    KyNang("update_customer", "Ghi nhận thông tin khách", "Lưu nhu cầu và thông tin liên hệ khách vừa cung cấp."),
    KyNang("send_media", "Gửi ảnh và video dự án", "Gửi hình ảnh minh hoạ qua kênh khách đang dùng."),
    KyNang("escalate", "Chuyển người thật", "Bàn giao cho nhân viên khi ngoài phạm vi hoặc khách yêu cầu."),
    # ⚠️ CHƯA AN TOÀN ĐỂ BẬT CHO TENANT THẬT (2026-09-07) — xem
    # docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md §0:
    # role sandbox `agent_sql_ro` phía Postgres không chặn được contacts/conversations/
    # dữ liệu chưa published do GRANT SELECT ... TO PUBLIC trên tenant_data (0909).
    # Entry catalog này để sẵn cho lúc lỗ hổng đóng — đừng publish "skills" có tên
    # này cho tenant thật trước đó.
    KyNang(
        "analyze_projects",
        "Thống kê & tồn kho",
        "Đếm/so sánh/xếp hạng/min-max-trung bình trên toàn bộ dự án và quỹ căn, kiêm câu hỏi tồn kho "
        "(còn bao nhiêu căn, loại nào, hướng nào) — sinh một câu SQL SELECT read-only trên 2 view "
        "published-only.",
    ),
)
```

- [ ] **Step 2: Edit `PHU_THUOC`** — remove the `check_inventory`, `get_project_overview`, `recommend_units` keys (confirmed by prior research: none of the surviving tools depend on these three as *values*, so removing the keys is safe on its own):

```python
PHU_THUOC: dict[str, tuple[str, ...]] = {
    "booking": ("find_project",),
    "get_document": ("find_project",),
    "send_media": ("find_project",),
}
```

- [ ] **Step 3: Update the module docstring counts** — line 1 `"""Sổ 13 kỹ năng...` → `"""Sổ 10 kỹ năng...`, and line 4 `SCHEMAS trong repo agent có 14 tool` → `SCHEMAS trong repo agent có 11 tool` (10 catalogued + `no_lookup_needed`). Leave the rest of the docstring (source pointer, three-column rationale, `nhan` disclaimer) unchanged.

- [ ] **Step 4: Run the unit test for this file in isolation to see it fail before Task 3 fixes it**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/config/test_tools_catalogue.py -v`
Expected: FAIL — `test_dung_13_ten_va_khop_agent` asserts `len(MUOI_HAI_KY_NANG) == 13` and a stale `TUY_CHON` set.

## Task 2: Backend defaults — `modules/config/contracts.py`

**Files:**
- Modify: `src/portal/modules/config/contracts.py:186-199` (`KY_NANG_MAC_DINH`)

**Interfaces:**
- Consumes: nothing new (list of literal tool names).
- Produces: `KY_NANG_MAC_DINH`, read by `payload_mac_dinh()` for new-workspace defaults.

- [ ] **Step 1: Drop the three retiring names from the default list, add nothing in their place** (see Global Constraints for why `check_inventory` isn't replaced by `analyze_projects` here):

```python
KY_NANG_MAC_DINH = [
    "find_project",
    "discover_projects",
    "get_document",
    "search_units",
    "kb_search",
    "booking",
    "update_customer",
    "send_media",
    "escalate",
]
"""Chín kỹ năng an toàn, bật sẵn cho một workspace mới — KHÔNG gồm analyze_projects
(chưa an toàn cho tenant thật, xem cảnh báo ở tools.py) và không còn ba tên đã
merge (get_project_overview/recommend_units/check_inventory — discover_projects/
search_units đã có trong danh sách, thay thế đủ vai trò cũ). Người dùng chốt: bật
full để agent dùng được ngay mọi năng lực còn lại thay vì phải vào `/agent`/
`/ky-nang-bds` bật tay từng cái; workspace nào cần tắt bớt thì tự tắt ở màn cấu
hình."""
```

- [ ] **Step 2: Check `payload_mac_dinh()` and any other reference to `KY_NANG_MAC_DINH` for hardcoded counts**

Run: `cd odyssey-portal-backend && grep -rn "KY_NANG_MAC_DINH\|payload_mac_dinh" src/ tests/`
Expected: only the definition + `payload_mac_dinh()` consuming it, plus test(s) in `tests/modules/config/` — read any hits before moving on, fix hardcoded lengths if any assert count `== 12`.

## Task 3: Backend tests — update fixtures to the new catalog

**Files:**
- Modify: `tests/modules/config/test_tools_catalogue.py`
- Modify: `tests/modules/config/test_publish.py:141-166`
- Modify: `tests/modules/linh_vuc/test_so.py:36-41`

**Interfaces:**
- Consumes: `TEN_KY_NANG`, `MUOI_HAI_KY_NANG`, `PHU_THUOC` from Task 1; `so.SO_LINH_VUC`/`so.so_ky_nang`/`so.KY_NANG_CHUNG` (unrelated to this change, already exist).

- [ ] **Step 1: Rewrite `test_tools_catalogue.py`'s `LOI`/`TUY_CHON` sets and count assertion**

```python
"""Sổ kỹ năng phải khớp tập tool agent THỰC SỰ có schema.

`get_project_financial` từng nằm ở đây nhưng agent không có schema nào cho nó —
bật nó là dạy LLM gọi một tool không tồn tại. `get_document` thì ngược lại.
"""

from portal.modules.config.tools import MUOI_HAI_KY_NANG, PHU_THUOC, TEN_KY_NANG

LOI = frozenset({"update_customer", "kb_search", "find_project", "escalate"})
TUY_CHON = frozenset(
    {
        "discover_projects",
        "get_document",
        "search_units",
        "booking",
        "send_media",
        "analyze_projects",
    }
)


def test_dung_10_ten_va_khop_agent():
    assert TEN_KY_NANG == LOI | TUY_CHON
    assert len(MUOI_HAI_KY_NANG) == 10


def test_get_project_financial_da_bi_bo():
    assert "get_project_financial" not in TEN_KY_NANG
    assert "get_project_financial" not in PHU_THUOC


def test_get_document_phu_thuoc_find_project():
    # schema của nó nhận `project_code` — luật ở docstring PHU_THUOC.
    assert PHU_THUOC["get_document"] == ("find_project",)
```

- [ ] **Step 2: Fix `test_publish.py`'s `da_don` fixture** (lines 145-160) — it currently lists three retiring names as part of a "valid payload" example; replace with only currently-valid names, keeping the test's intent (a payload that publishes successfully):

```python
    da_don = {
        **PAYLOAD_HOP_LE,
        "tools": {
            "enabled": [
                "find_project",
                "discover_projects",
                "search_units",
                "booking",
                "kb_search",
                "escalate",
            ]
        },
    }
```

- [ ] **Step 3: Fix `test_so.py`'s hardcoded BDS-tab count** (lines 36-41) — total catalog drops from 13 to 10, so `10 - len(KY_NANG_CHUNG)` (3) is now 7, not 10:

```python
def test_so_ky_nang_hom_nay():
    """bds = 10 − 3 = 7 (mọi kỹ năng không-chung đều là BĐS hôm nay, kể cả
    `analyze_projects` — xem cảnh báo tương lai trong docstring so_ky_nang)."""
    bds, taichinh = so.SO_LINH_VUC
    assert so.so_ky_nang(bds) == len(TEN_KY_NANG) - len(so.KY_NANG_CHUNG) == 7
    assert so.so_ky_nang(taichinh) == 0
```

- [ ] **Step 4: Search for any other hardcoded references to the three retiring names or to counts 13/12/9 in the config/linh_vuc test trees**

Run: `cd odyssey-portal-backend && grep -rln "get_project_overview\|recommend_units\|check_inventory" tests/`
Expected: only the two files just fixed should show up (plus possibly `test_config_agent.py`, already confirmed unaffected — verify it has no hit). Fix any other hit the same way (drop the retiring names, don't invent replacements unless the surrounding assertion clearly needs one).

- [ ] **Step 5: Run the full config + linh_vuc test modules**

Run: `cd odyssey-portal-backend && uv run pytest tests/modules/config tests/modules/linh_vuc -v`
Expected: PASS, no reference to old tool names left failing.

## Task 4: Regenerate `contracts/tools.json` (backend) and copy to frontend

**Files:**
- Regenerate: `odyssey-portal-backend/contracts/tools.json` (via `make contracts`)
- Copy to: `odyssey-portal-frontend/contracts/tools.json`

- [ ] **Step 1: Regenerate**

Run: `cd odyssey-portal-backend && make contracts`
Expected: `contracts/tools.json` rewritten with 10 tools (order matches `MUOI_HAI_KY_NANG`) and a 3-key `phuThuoc` map.

- [ ] **Step 2: Run the backend's own contract test**

Run: `cd odyssey-portal-backend && uv run pytest tests/api/test_contracts.py -v`
Expected: PASS.

- [ ] **Step 3: Copy the regenerated file across the repo boundary**

Run: `cp odyssey-portal-backend/contracts/tools.json odyssey-portal-frontend/contracts/tools.json`

## Task 5: Backend data migration — rename skills in existing `tenant_data.agent_config` rows

**Files:**
- Create: `migrations/versions/0961_merge_structured_data_tools_skills.py`

**Interfaces:**
- `down_revision = "0960_hop_nhat_hai_head_0959"` (current head, confirmed via `ls migrations/versions/ | sort | tail`).

- [ ] **Step 1: Write the migration** — idempotent data-only UPDATE per handoff §4, with the mandatory `version` bump. No schema/DDL change (`skills` has no value-level CHECK, confirmed by prior research). Downgrade is a documented no-op — after `upgrade()` runs, rows can no longer distinguish which old name they used to carry (both `get_project_overview` and any pre-existing `discover_projects` entry now read `discover_projects` identically).

```python
"""merge structured-data tools (6→3) in tenant_data.agent_config.skills

Nguồn: odyssey-portal-frontend/docs/product/2026-09-07-tool-merge-portal-handoff.md §4.
Agent đã gộp get_project_overview→discover_projects, recommend_units→search_units,
check_inventory→analyze_projects. Idempotent — chỉ chạm row còn chở tên cũ.
version += 1 là LOAD-BEARING: agent cache runner theo (tenant, version); đổi
skills mà giữ nguyên version thì phiên chat mới vẫn chạy catalog cũ, im lặng.

⚠️ check_inventory -> analyze_projects là một lần NỚI capability (agent tự sinh
SQL). analyze_projects mang cảnh báo "CHƯA AN TOÀN CHO TENANT THẬT" trong
modules/config/tools.py (role sandbox agent_sql_ro chưa chặn được
contacts/conversations/dữ liệu chưa published, GRANT SELECT ... TO PUBLIC trên
tenant_data). Portal đã CHỦ Ý CHẤP NHẬN rủi ro này cho migration này — xem
docs/superpowers/plans/2026-09-09-merge-structured-data-tools-skills.md. Không
áp dụng widening này cho default skillset của tenant MỚI (contracts.py::
KY_NANG_MAC_DINH không gồm analyze_projects) — chỉ tenant ĐANG BẬT check_inventory
mới được nới qua migration này.

KHÔNG downgrade được: sau upgrade(), discover_projects/search_units/
analyze_projects không còn phân biệt được hàng nào từng mang tên cũ
(get_project_overview/recommend_units/check_inventory) hay vốn đã mang tên mới
từ trước.
"""

from alembic import op

revision = "0961_merge_structured_data_tools_skills"
down_revision = "0960_hop_nhat_hai_head_0959"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tenant_data.agent_config
        SET skills = (
              SELECT COALESCE(jsonb_agg(DISTINCT nn), '[]'::jsonb)
              FROM (
                SELECT CASE s
                         WHEN 'recommend_units'      THEN 'search_units'
                         WHEN 'get_project_overview' THEN 'discover_projects'
                         WHEN 'check_inventory'      THEN 'analyze_projects'
                         ELSE s
                       END AS nn
                FROM jsonb_array_elements_text(skills) AS t(s)
              ) m
            ),
            version    = version + 1,
            updated_at = now()
        WHERE skills ?| ARRAY['recommend_units','get_project_overview','check_inventory'];
        """
    )


def downgrade() -> None:
    # Không thể phục hồi — xem docstring module ở trên.
    pass
```

- [ ] **Step 2: Verify against the local/dev DB only (never staging/prod)**

Run: `cd odyssey-portal-backend && make migrate`
Expected: migration applies cleanly on the dev container. Then spot-check:

```sql
SELECT tenant_id, version, skills FROM tenant_data.agent_config
WHERE skills ?| ARRAY['recommend_units','get_project_overview','check_inventory'];
```
Expected: 0 rows (dev seed data doesn't carry the old names, so this is mostly a syntax/idempotency smoke test — the actual affected tenants are on staging, which the user runs themselves per their explicit choice).

- [ ] **Step 3: Confirm single-head**

Run: `cd odyssey-portal-backend && uv run pytest tests/unit/test_alembic_mot_head.py -v`
Expected: PASS (only one head after adding `0961`).

## Task 6: Frontend catalog — `src/lib/tools.ts`

**Files:**
- Modify: `src/lib/tools.ts`

- [ ] **Step 1: Mirror the new backend catalog** (labels only — no `moTa` per this file's own documented design: "Không mang `moTa`: nó là câu dạy LLM, không hiện ra giao diện"):

```ts
export const MUOI_HAI_KY_NANG: readonly KyNang[] = [
  { ten: 'find_project', nhan: 'Nhận diện tên dự án' },
  { ten: 'discover_projects', nhan: 'Khám phá & giới thiệu dự án' },
  { ten: 'get_document', nhan: 'Gửi tài liệu của dự án' },
  { ten: 'search_units', nhan: 'Tìm & gợi ý căn' },
  { ten: 'kb_search', nhan: 'Tra tài liệu của workspace' },
  { ten: 'booking', nhan: 'Đặt lịch tham quan' },
  { ten: 'update_customer', nhan: 'Ghi nhận thông tin khách' },
  { ten: 'send_media', nhan: 'Gửi ảnh và video dự án' },
  { ten: 'escalate', nhan: 'Chuyển người thật' },
  // ⚠ CHƯA AN TOÀN ĐỂ BẬT CHO TENANT THẬT (2026-09-07) — xem
  // odyssey-portal-backend/docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md §0:
  // role sandbox Postgres phía agent không chặn được contacts/conversations/dữ liệu
  // chưa published do GRANT SELECT ... TO PUBLIC trên tenant_data. Entry này để sẵn
  // cho lúc lỗ hổng đóng — đừng bật nó cho workspace thật trước đó.
  { ten: 'analyze_projects', nhan: 'Thống kê & tồn kho' },
]

export const PHU_THUOC: Readonly<Record<string, readonly string[]>> = {
  booking: ['find_project'],
  get_document: ['find_project'],
  send_media: ['find_project'],
}
```

- [ ] **Step 2: Update the file's top docstring count** ("13 kỹ năng" → "10 kỹ năng" in the header comment).

## Task 7: Frontend tests + fixtures

**Files:**
- Modify: `tests/tools-parity.test.ts:34,38`
- Modify: `src/lib/msw/handlers.ts:76-88`
- Modify: `src/features/ops/msw.ts:339`

**Interfaces:**
- Consumes: `MUOI_HAI_KY_NANG`/`PHU_THUOC` from Task 6, `contracts/tools.json` from Task 4.

- [ ] **Step 1: Fix the two hardcoded counts in `tools-parity.test.ts`**

```ts
  it('artefact có đúng 10 kỹ năng', () => {
    expect(docArtefact().tools).toHaveLength(10)
  })

  it('tools.ts có đúng 10 kỹ năng', () => {
    expect(MUOI_HAI_KY_NANG).toHaveLength(10)
  })
```
(Leave the two other `it(...)` blocks — name/order and label parity — untouched; they already compare against the live artefact/array.)

- [ ] **Step 2: Run the parity test**

Run: `cd odyssey-portal-frontend && npx vitest run tests/tools-parity.test.ts`
Expected: PASS (4/4).

- [ ] **Step 3: Fix the default MSW fixture's `tools.enabled` array** (`src/lib/msw/handlers.ts:76-88`) — drop the three retiring names, keep the rest (this fixture has no parity gate, per this repo's own CLAUDE.md — must be hand-verified):

```ts
    enabled: [
      'find_project',
      'discover_projects',
      'get_document',
      'search_units',
      'kb_search',
      'booking',
      'update_customer',
      'send_media',
      'escalate',
    ],
```

- [ ] **Step 4: Fix the cosmetic reference in `src/features/ops/msw.ts:339`** — `toolThieuDuLieu: 'check_inventory'` (a demo "tool missing data" label on a fake `/convos` conversation row) should reference a tool that still exists post-merge:

```ts
    toolThieuDuLieu: 'analyze_projects',
```

- [ ] **Step 5: Run the full frontend suite**

Run: `cd odyssey-portal-frontend && npx tsc -b --force && npx vitest run`
Expected: PASS, 0 new failures versus the last known baseline in this repo's CLAUDE.md (check the Gotchas section for the current known-red count before concluding — don't mistake a pre-existing red test for a regression, and don't take an old baseline number on faith either; count it yourself first).

## Task 8: Change Log entries (both repos)

**Files:**
- Modify: `odyssey-portal-backend/CLAUDE.md` (Change Log table, top row)
- Modify: `odyssey-portal-frontend/CLAUDE.md` (Change Log table, top row)

- [ ] **Step 1: Add one row to each file's Change Log**, per each repo's own "Tự bảo trì file này" rule (contract-with-other-repo changes must be logged). Summarize: catalog 13→10, three names merged, `KY_NANG_MAC_DINH` dropped `check_inventory` without replacing it with `analyze_projects`, migration `0961` prepared but not run by the agent (handed to the user), and flag the open `PHU_THUOC` question from Global Constraints.

## Self-Review Notes

- **Spec coverage**: §2 (catalog) → Tasks 1/4/6; §3 (UI + API-save validation) → Task 1 (validator already exists, catalog update is what activates it) + Task 6; §4 (migration) → Task 5; §5 (per-tenant decision) → resolved by user via AskUserQuestion, reflected in Task 5's docstring and Global Constraints; §6/§7 (rollout sequencing, verify) → out of scope for this plan (belongs to whoever runs the migration and coordinates with the agent team, per the user's choice not to have me touch the DB).
- **Not covered by this plan, deliberately**: `src/components/landing/duLieuMau.ts` (marketing copy on the public landing page — `KY_NANG_BDS` list and a "Gợi ý căn hợp mệnh" demo chip) has no parity test and is cosmetic; flag it to the user as optional cleanup rather than bundling it into this change.
