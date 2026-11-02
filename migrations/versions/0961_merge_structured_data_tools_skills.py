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

UPDATE này chạm MỌI tenant trong một câu (không lọc theo `app.tenant_id`), nên
phải tắt `FORCE ROW LEVEL SECURITY` quanh nó (luật ở header `0003`, cùng khuôn
`0930_nap_lai_tai_lieu_chua_boc.py`) — bỏ qua thì trên môi trường mà
`portal_migrator` không có `BYPASSRLS` câu này xếp 0 hàng và BÁO THÀNH CÔNG,
im lặng hỏng đúng lớp lỗi `tests/unit/test_migration_backfill_rls.py` canh.
"""

from alembic import op

revision = "0961_merge_tools_skills"
down_revision = "0960_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.agent_config NO FORCE ROW LEVEL SECURITY")
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
    op.execute("ALTER TABLE tenant_data.agent_config FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Không thể phục hồi — xem docstring module ở trên.
    pass
