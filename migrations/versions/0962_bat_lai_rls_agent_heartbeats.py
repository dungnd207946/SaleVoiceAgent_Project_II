"""bật lại RLS cho control.agent_heartbeats — món nợ ghi từ 0917

`0909_bo_rls_toan_bo` từng tắt RLS trên MỌI bảng, kể cả `control.agent_heartbeats`.
`0913_bat_lai_rls_tenant_data` chỉ bật lại cho schema `tenant_data`, và CỐ Ý bỏ qua
bảng này vì lúc đó "không có bằng chứng rò rỉ". Phát hiện lại lúc làm `0917`, ghi
thành nợ trong CLAUDE.md, và `0941_bo_deployments` xác nhận vẫn chưa đụng tới
(`relrowsecurity = f`, 0 policy tính tới lúc đó).

Bằng chứng rò rỉ nay CÓ THẬT: `tests/modules/test_heartbeat.py` đo được agent của
tenant `hb1` vừa ĐỌC vừa GHI ĐÈ heartbeat của tenant `hb2` — role `agent_hb1` không
hề bị chặn bởi CHECK/USING nào vì RLS đang tắt hoàn toàn trên bảng.

Bảng đã đổi khoá chính từ `(tenant_id, deployment_id)` sang `(tenant_id)` ở `0941`,
nhưng vị từ RLS chỉ so `tenant_id` nên không đổi. Chép lại NGUYÊN VĂN 2 policy gốc
của `0007_agent_heartbeats.py:65-80` (không suy luận lại) — đúng như `0909.downgrade()`
đã làm cho đúng bảng này khi cần khôi phục.

KHÔNG FORCE: giữ đúng quyết định gốc của `0007` — `control` là dữ liệu control
plane, owner (`portal_migrator`) cần sửa/khôi phục bằng tay, và cổng catalog (test
isolation) chỉ quét `tenant_data` nên không đòi FORCE ở bảng này.

GRANT không cần lặp lại: `agent_all` đã có SELECT/INSERT/UPDATE từ `0007` (0909
không đụng GRANT, chỉ đụng RLS/policy); `portal_api` đã có SELECT qua
`GRANT ... TO PUBLIC` của `0908_readonly_control`.

Revision ID: 0962_rls_agent_heartbeats
Revises: 0961_merge_tools_skills
"""

from alembic import op

revision = "0962_rls_agent_heartbeats"
down_revision = "0961_merge_tools_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.agent_heartbeats ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY hb_agent_own_tenant ON control.agent_heartbeats
            TO agent_all
            USING (tenant_id = portal.current_tenant())
            WITH CHECK (tenant_id = portal.current_tenant())
        """
    )
    op.execute(
        """
        CREATE POLICY hb_portal_all ON control.agent_heartbeats
            TO portal_api
            USING (true) WITH CHECK (true)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY hb_agent_own_tenant ON control.agent_heartbeats")
    op.execute("DROP POLICY hb_portal_all ON control.agent_heartbeats")
    op.execute("ALTER TABLE control.agent_heartbeats DISABLE ROW LEVEL SECURITY")
