# Handoff Portal — merge tool 6→3: bề mặt bật/tắt skills (UI + DB)

**Cho:** đội Portal backend/frontend (chủ `tenant_data.agent_config` + UI cấu hình agent)
**Từ:** đội agent (nhánh `feat/merge-tool-agent`, commit `de186d7`, hiệu lực 2026-09-07)
**Spec gốc phía agent:** `docs/superpowers/specs/2026-09-07-merge-structured-data-tools-design.md`
**Contract cột phẳng:** `docs/handoff/agent-config-bang-phang.md` (không đổi shape — chỉ đổi TẬP GIÁ TRỊ của `skills`)
**Cập nhật:** 2026-09-09 — bản đầy đủ cho UI + migration DB (thay bản tóm tắt 2026-09-07).

---

## 1. TL;DR

Agent đã gộp 6 tool dữ liệu cấu trúc còn 3. Cột `tenant_data.agent_config.skills`
(jsonb array tên tool) từ nay chỉ còn **6 giá trị hợp lệ**; 3 tên cũ bị nuốt.
Portal cần: (a) sửa UI bật/tắt theo catalog mới, (b) chạy MỘT câu UPDATE migrate
row đã publish, (c) **BẮT BUỘC tăng `version` trong cùng UPDATE** — agent cache
runner theo `(tenant, version)`, đổi `skills` mà giữ nguyên `version` thì phiên
mới vẫn chạy catalog cũ, im lặng.

Không phải phối hợp thứ tự deploy: agent đang chạy bảng alias tên-cũ→tên-mới
(log warning mỗi lần gặp), config chưa migrate vẫn hoạt động đúng. Migrate xong
toàn bộ thì báo lại để agent gỡ alias.

## 2. Catalog mới — tập giá trị hợp lệ của `skills`

### 2.1 Bật/tắt được (optional — 6, trước là 9)

| Giá trị `skills` | Nuốt tên cũ | Nhãn UI gợi ý | Mô tả tooltip gợi ý |
|---|---|---|---|
| `discover_projects` | `get_project_overview` | Khám phá & giới thiệu dự án | Danh sách dự án theo tiêu chí (khu vực / ngân sách / loại hình / CĐT) **và** tổng quan chi tiết một dự án |
| `search_units` | `recommend_units` | Tìm & gợi ý căn | Tra căn trong một dự án **lẫn** gợi ý xuyên dự án theo ngân sách; kèm tư vấn phong thủy (xem §2.3) và nhóm chèo kéo vượt-ngân-sách |
| `analyze_projects` | `check_inventory` | Thống kê & tồn kho (SQL) | Đếm / so sánh / xếp hạng / min-max-trung bình trên toàn bộ dự án và quỹ căn, **kiêm câu tồn kho** ("còn bao nhiêu căn, loại nào, hướng nào") — LLM sinh SQL SELECT read-only trên 2 view published-only |
| `get_document` | — | Gửi tài liệu | Danh sách bản CSBH / pháp lý / brochure + link file |
| `booking` | — | Đặt lịch tham quan | Đặt / đổi / xem lịch xem nhà |
| `send_media` | — | Gửi ảnh & video | Ảnh / video / tour 360 qua app |

### 2.2 Không bật/tắt được (core — hiển thị "luôn bật" hoặc ẩn khỏi UI)

`update_customer`, `kb_search`, `find_project`, `escalate` — agent tự thêm, giá
trị trong `skills` bị bỏ qua (không lỗi nếu có). `escalate` vĩnh viễn không tắt
được (van an toàn). `no_lookup_needed` là van nội bộ của agent, **không bao giờ**
xuất hiện trong `skills`.

### 2.3 Hệ quả ràng buộc UI

- **Phong thủy KHÔNG có toggle riêng**: agent derive `feng_shui` từ việc
  `search_units` được bật (trước đây derive từ `recommend_units`). UI nào đang mô
  tả phong thủy ở toggle "gợi ý căn" thì chuyển mô tả đó sang toggle
  `search_units`.
- **Tên lạ bị agent bỏ qua im lặng** (không lỗi, không hiển thị) — nên backend
  Portal vẫn phải validate allowed-list ở API save để user không lưu rác.
- DB **không** có CHECK allowed-list trên `skills` (chỉ CHECK jsonb array — đã
  soi trực tiếp `pg_constraint` trên staging 10.50.13.208): việc chặn tên cũ
  trên save mới nằm hoàn toàn ở code backend Portal.

## 3. Việc UI (frontend + API validate)

1. Gỡ 3 toggle: `get_project_overview`, `recommend_units`, `check_inventory`.
2. Cập nhật nhãn + tooltip của `discover_projects` / `search_units` /
   `analyze_projects` theo bảng §2.1 (vai trò đã RỘNG hơn tên cũ).
3. Allowed-list ở API save đổi về đúng 6 giá trị §2.1; **từ chối tên cũ trên
   save MỚI** kể từ khi UI mới lên (row cũ chưa migrate thì để migration §4 xử
   lý, đừng bắt user tự sửa).
4. Tenant nào đang bật ít nhất một trong 3 tên cũ → UI (trước khi migrate) nên
   hiển thị như thể tool mới tương ứng đang bật, vì agent đang alias đúng như thế.

## 4. Migration DB — copy-paste

Một câu UPDATE, idempotent (chỉ chạm row còn chở tên cũ), rename + dedupe +
**bump version** + updated_at. Chạy bằng role có quyền UPDATE
`tenant_data.agent_config` (thường `portal_api`/`portal_migrator`):

```sql
BEGIN;

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
    version    = version + 1,   -- BẮT BUỘC: agent pin runner theo (tenant, version)
    updated_at = now()
WHERE skills ?| ARRAY['recommend_units','get_project_overview','check_inventory'];

COMMIT;
```

Ghi chú:

- `jsonb_agg(DISTINCT ...)` không giữ thứ tự phần tử — **vô hại**: agent luôn
  sắp lại theo thứ tự canonical của nó (`OPTIONAL_TOOLS`), thứ tự trong DB không
  có ý nghĩa.
- **`version = version + 1` là load-bearing.** Agent cache runner theo
  `(tenant, version, channel)`; phiên đang chạy giữ version đã pin (đúng thiết
  kế BR05), phiên MỚI đọc version mới trong ~`NOBLE_CONFIG_POLL_SEC`. Nếu Portal
  có flow publish riêng (bảng lịch sử / audit) thì đi qua flow đó thay vì UPDATE
  tay — yêu cầu duy nhất của agent là **số version phải đổi** cùng lúc với skills.
- Liệt kê tenant bị ảnh hưởng trước khi chạy:

```sql
SELECT tenant_id, version, skills
FROM tenant_data.agent_config
WHERE skills ?| ARRAY['recommend_units','get_project_overview','check_inventory'];
```

(Trên staging 10.50.13.208:5442, ngày 2026-09-09 câu này trả về ít nhất
`du_test` — config v1 chở cả 3 tên cũ; dùng nó làm tenant migrate thử đầu tiên.)

## 5. Quyết định per-tenant TRƯỚC khi migrate: `check_inventory`

`check_inventory` → `analyze_projects` là một lần **nới capability**: tenant
trước đây chỉ có "đếm tồn kho" (tham số cố định), sau merge sẽ có tool SQL tự do.
An toàn vẫn do 3 khoá DB giữ (SELECT-only trên 2 view published-only
`agent_projects_v`/`agent_units_v`, transaction READ ONLY, role `agent_sql_ro`,
RLS — chi tiết `agent-analyze-projects-sql-ro-contract.md`), nhưng về mặt sản
phẩm đây là quyết định của Portal:

- **Chấp nhận nới** (mặc định của câu SQL §4): đổi tên như trên.
- **Không muốn tenant đó có SQL**: sửa câu CASE bỏ nhánh `check_inventory` và
  thay bằng loại phần tử đó ra — tenant mất khả năng trả lời câu tồn kho.

**Điều kiện hạ tầng:** `analyze_projects` cần role `agent_sql_ro` +
`agent_kb_view_owner` + 2 view đã provision trên DB serving (CLI phía agent:
`noble-tenant pg-ensure-sql-ro`). Đã có sẵn trên staging 10.50.13.208 (kiểm
2026-09-09). Deployment nào thiếu → tool degrade mềm ("nguồn thống kê tạm không
khả dụng", không vỡ cuộc gọi) nhưng tenant mất câu tồn kho — chạy provisioning
trước khi migrate các tenant có `check_inventory`.

## 6. Trình tự & giai đoạn alias

```
[đã xong] agent deploy merge + alias tên cũ (feat/merge-tool-agent)
   ↓ (không phụ thuộc thứ tự)
[Portal]  UI mới + validate allowed-list 6 giá trị
[Portal]  migration §4 (sau khi chốt §5 per-tenant)
   ↓
[Portal → agent] báo "config sạch tên cũ"
[agent]   gỡ TOOL_ALIASES (agent/agent_config.py) — hết giai đoạn chuyển tiếp
```

Trong giai đoạn chuyển tiếp, mỗi lần agent gặp tên cũ nó log:

```
tool 'recommend_units' đã gộp vào 'search_units' (merge 2026-09-07) — dọn config để hết cảnh báo
```

Log này biến mất hoàn toàn = migration đã phủ hết đường serving.

## 7. Verify sau migration

1. **DB sạch tên cũ** — câu SELECT ở §4 trả 0 row.
2. **Agent hết warning alias** — grep log serving không còn chuỗi `đã gộp vào`.
3. **Smoke một tenant vừa migrate** (phía agent hỗ trợ chạy):
   `python scripts/chat_repl.py -t <tenant>` — "có 5 tỷ mua căn nào" →
   `search_units(scope='all_projects')`; "giới thiệu dự án X" →
   `discover_projects(project_code=...)`; "dự án X còn loại căn nào" →
   `analyze_projects` (SQL GROUP BY).
4. **Version nhảy đúng**: phiên chat MỚI sau migrate log `pinned_version` = số mới.

## 8. Không đổi

- Shape bảng `tenant_data.agent_config` (cột, kiểu, CHECK, FK) — chỉ đổi tập giá
  trị bên trong `skills`.
- DB serving: schema `tenant_data`, view `agent_*_v`, role, GRANT, RLS — merge
  này thuần tầng tool của agent, không kèm DDL nào.
- Các tool `kb_search`, `get_document`, `booking`, `send_media`, `escalate`,
  `find_project`, `update_customer`: tên và hành vi giữ nguyên.
- Đường đọc config của agent (`read_published_config` — SELECT theo tenant_id)
  không đổi.
