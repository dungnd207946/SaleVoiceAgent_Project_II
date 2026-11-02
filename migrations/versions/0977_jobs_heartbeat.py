"""`control.jobs.heartbeat_at` — nhịp tim của việc đang chạy.

Worker ghi lúc nhận việc và mỗi 30 giây trong lúc handler chạy. Việc `running` mất nhịp tim quá vài phút là
worker đã chết (deploy giết container, OOM, máy khởi động lại), không phải việc đang treo, nên được thu hồi
ngay thay vì chờ ngưỡng kẹt của loại việc (tới 6 giờ với `kbweb_run`). NULL = nhận bởi bản worker cũ.

Spec: docs/superpowers/specs/2026-10-07-worker-tra-viec-khi-dung-design.md

Revision ID: 0977_jobs_heartbeat
Revises: 0976_kich_ban
"""

from alembic import op

revision = "0977_jobs_heartbeat"
down_revision = "0976_kich_ban"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.jobs ADD COLUMN heartbeat_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE control.jobs DROP COLUMN heartbeat_at")
