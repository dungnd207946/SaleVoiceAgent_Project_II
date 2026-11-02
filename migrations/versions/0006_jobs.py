"""control.jobs — hàng đợi job dùng chung

VÌ SAO Ở M1 CHỨ KHÔNG Ở M3: bốn module cần nó — M4 (import file), M6 (build
index), M8 (job xoá quá hạn), M3 (publish). Để nó ở M3 là buộc ba module đợi
một module.

VÌ SAO KHÔNG DÙNG BackgroundTasks CỦA FASTAPI: nó chết cùng tiến trình và không
để lại dấu vết nào. Một bảng job là cách rẻ nhất để lời hứa "job xoá quá hạn
phải có giám sát" (quyết định #19 — 6 tháng nằm trong hợp đồng với khách) thành
thật thay vì khẩu hiệu: job không chạy thì bảng này cho thấy ngay.

VÌ SAO kind LÀ text TỰ DO, KHÔNG PHẢI enum/CHECK: module sau thêm loại job mà
không cần migration. Danh sách đã biết: publish (M3) · import (M4) ·
rag_build (M6) · retention_delete (M8).

VÌ SAO CÓ CỘT payload: handler tự định nghĩa hình dạng đầu vào của mình. M1
không cần biết M4 truyền gì.

Revision ID: 0006_jobs
Revises: 0005_agent_api
"""

from alembic import op

revision = "0006_jobs"
down_revision = "0005_agent_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.jobs (
            id          bigserial PRIMARY KEY,
            tenant_id   text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            kind        text NOT NULL CHECK (kind <> ''),
            state       text NOT NULL DEFAULT 'queued'
                        CONSTRAINT jobs_state_check
                        CHECK (state IN ('queued', 'running', 'success', 'failed')),
            actor       text NOT NULL DEFAULT '',
            payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at  timestamptz NOT NULL DEFAULT now(),
            started_at  timestamptz,
            finished_at timestamptz,
            count       integer NOT NULL DEFAULT 0,
            message     text NOT NULL DEFAULT '',
            force       boolean NOT NULL DEFAULT false
        )
        """
    )
    # Index riêng cho vòng lặp FOR UPDATE SKIP LOCKED — chỉ hàng queued.
    op.execute("CREATE INDEX jobs_queued_idx ON control.jobs (id) WHERE state = 'queued'")
    # Index cho màn danh sách job của một workspace.
    op.execute("CREATE INDEX jobs_tenant_created_idx ON control.jobs (tenant_id, created_at DESC)")
    # Giám sát: job running quá lâu là bất thường, người xử lý chứ không phải
    # máy đoán. Worker chết giữa lúc chạy để lại đúng trạng thái này.
    op.execute(
        """
        CREATE VIEW control.jobs_stuck AS
        SELECT id, tenant_id, kind, actor, started_at, now() - started_at AS stuck_for
          FROM control.jobs
         WHERE state = 'running' AND started_at < now() - interval '15 minutes'
        """
    )
    op.execute("GRANT SELECT ON control.jobs_stuck TO portal_api")


def downgrade() -> None:
    op.execute("DROP VIEW control.jobs_stuck")
    op.execute("DROP TABLE control.jobs")
