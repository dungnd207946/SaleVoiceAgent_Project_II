"""bỏ hẳn control.deployments — nhịp tim khoá theo tenant

PHA 2 của việc gỡ khái niệm "deployment". `0940` đã cắt `agent_keys` khỏi bảng này;
còn lại đúng hai người dùng, đợt này dọn cả hai:

  · `control.agent_heartbeats` — FK + nửa khoá chính `(tenant_id, deployment_id)`
  · màn liệt kê của admin nền tảng — `GET /admin/deployments`, nay là `GET /admin/tenants`

VÌ SAO BỎ ĐƯỢC BÂY GIỜ: sau `0919` (bỏ cột `kind`) bảng chỉ còn `id · tenant_id ·
endpoint · provisioned_at`, trong đó `endpoint` mặc định `''` và KHÔNG đường code nào
ghi vào. Một hàng deployment không mang thông tin nào mà `control.tenants` chưa có.

⚠️ NHỊP TIM ĐÃ CHẾT SẴN TỪ `0919`, KHÔNG PHẢI DO MIGRATION NÀY. Đo được ở repo agent:
`tenant/pg_heartbeat.py::beat()` chỉ dùng pool tenant khi `cred.kind == self._kind`, mà
`kind` được parse từ response `/runtime-credentials` — trường `0919` đã bỏ. Nên
`cred.kind` luôn `''`, không bao giờ khớp `'chat'`/`'voice'`, và mọi lượt beat rơi xuống
nhánh fallback `SELECT control.deployments` bằng role `agent_<tenant>` — role chưa bao
giờ có SELECT trên bảng đó. Migration này KHÔI PHỤC nhịp tim chứ không phá nó.

ĐỔI NGỮ NGHĨA, KHÔNG PHẢI DỌN DẸP THUẦN: trước đây hai pod (`chat`/`voice`) của cùng một
tenant có hai `deployment_id` ⇒ HAI hàng nhịp tim. Giờ chúng ĐÈ lên nhau ⇒ MỘT hàng. Với
người đọc thì không đổi — `config/repo.lay_heartbeat` vốn đã bỏ qua `deployment_id` và
lấy `last_seen_at` mới nhất — nhưng bảng mất khả năng phân biệt pod. Chấp nhận: phân biệt
từng pod là việc của màn Vận hành (M7), và nó chưa từng dùng cột này.

KHÔNG ĐỤNG RLS: `control.agent_heartbeats` đang TẮT RLS hoàn toàn (policy `hb_agent_own_tenant`
/`hb_portal_all` của `0007` bị `0909_bo_rls_toan_bo` xoá, `0913` cố ý không bật lại) — đo
trên DB dev 2026-08-19: `relrowsecurity = f`, 0 policy. Đó là món nợ CLAUDE.md đã ghi và là
nguyên nhân hai bài đỏ ở `tests/modules/test_heartbeat.py`. Bật lại là một quyết định AN NINH
với phạm vi riêng, cần migration + spec riêng — chôn nó trong một đợt dọn dẹp là làm cả hai
việc mờ đi. Cố ý để nguyên.

⚠️ `downgrade` CÓ MẤT MÁT, KHÔNG TRÁNH ĐƯỢC: hai hàng nhịp tim đã gộp thành một thì không
tách lại được (số hiệu pod đã mất cùng cột). Nó dựng lại `deployments` với ĐÚNG MỘT hàng
mỗi tenant và trỏ nhịp tim vào đó — cấu trúc đúng, dữ liệu không đầy như trước.

Revision ID: 0941_bo_deployments
Revises: 0940_agent_keys_tenant
"""

from alembic import op

revision = "0941_bo_deployments"
down_revision = "0940_agent_keys_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Gộp nhịp tim về một hàng mỗi tenant ───────────────────────────────
    # PHẢI chạy TRƯỚC khi bỏ cột: sau khi bỏ, hai hàng của cùng tenant là hai hàng
    # trùng lặp không phân biệt được, và `ADD PRIMARY KEY` vỡ mà không nói được
    # hàng nào đáng giữ.
    #
    # Giữ hàng `last_seen_at` MỚI NHẤT — cùng vị từ mà `config/repo.lay_heartbeat`
    # dùng để chọn hàng hiển thị, nên trạng thái trên màn hình không đổi sau migration.
    # `deployment_id` là tie-break tất định cho ca hai pod cùng mốc (mốc đến từ
    # `now()` của transaction, nên trùng mốc là chuyện có thật).
    op.execute(
        """
        DELETE FROM control.agent_heartbeats a
              USING control.agent_heartbeats b
              WHERE a.tenant_id = b.tenant_id
                AND (a.last_seen_at, a.deployment_id) < (b.last_seen_at, b.deployment_id)
        """
    )

    # ── 2. Khoá lại theo tenant ──────────────────────────────────────────────
    # DROP COLUMN kéo theo CẢ khoá chính ghép LẪN `agent_heartbeats_deployment_fkey`
    # (`0200`) — Postgres bỏ mọi ràng buộc có dính cột bị xoá. Không cần hai câu
    # DROP CONSTRAINT riêng, và viết chúng ra sẽ vỡ vì tên đã biến mất.
    op.execute("ALTER TABLE control.agent_heartbeats DROP COLUMN deployment_id")
    op.execute("ALTER TABLE control.agent_heartbeats ADD PRIMARY KEY (tenant_id)")

    # ── 3. Bảng đi ───────────────────────────────────────────────────────────
    # `deployments_tenant_idx` (`0200`) rơi theo bảng.
    op.execute("DROP TABLE control.deployments")


def downgrade() -> None:
    # DDL của `0200` TRỪ cột `kind` — `0919` đã bỏ nó, dựng lại ở đây là hồi sinh một
    # cột mà không code nào còn đọc và một CHECK constraint đã bị gỡ có chủ ý.
    op.execute(
        """
        CREATE TABLE control.deployments (
            id             bigserial PRIMARY KEY,
            tenant_id      text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            endpoint       text NOT NULL DEFAULT '',
            provisioned_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX deployments_tenant_idx ON control.deployments (tenant_id)")
    # `ALTER DEFAULT PRIVILEGES` của `0003` chỉ áp cho bảng tạo SAU nó bởi cùng role —
    # `portal_migrator` chạy migration này nên bảng mới nhận DML cho `portal_api` như
    # bảng gốc. Khai lại tường minh vẫn rẻ hơn một downgrade để lại bảng không ai ghi được.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON control.deployments TO portal_api")
    op.execute("GRANT USAGE ON SEQUENCE control.deployments_id_seq TO portal_api")

    # Một hàng cho mỗi tenant có nhịp tim. Không thể khôi phục số pod thật —
    # xem cảnh báo mất mát ở header.
    op.execute(
        """
        INSERT INTO control.deployments (tenant_id)
        SELECT DISTINCT tenant_id FROM control.agent_heartbeats
        """
    )

    op.execute("ALTER TABLE control.agent_heartbeats DROP CONSTRAINT agent_heartbeats_pkey")
    op.execute("ALTER TABLE control.agent_heartbeats ADD COLUMN deployment_id bigint")
    op.execute(
        """
        UPDATE control.agent_heartbeats h
           SET deployment_id = d.id
          FROM control.deployments d
         WHERE d.tenant_id = h.tenant_id
        """
    )
    op.execute("ALTER TABLE control.agent_heartbeats ALTER COLUMN deployment_id SET NOT NULL")
    op.execute("ALTER TABLE control.agent_heartbeats ADD PRIMARY KEY (tenant_id, deployment_id)")
    op.execute(
        """
        ALTER TABLE control.agent_heartbeats
            ADD CONSTRAINT agent_heartbeats_deployment_fkey
            FOREIGN KEY (deployment_id) REFERENCES control.deployments(id) ON DELETE CASCADE
        """
    )
