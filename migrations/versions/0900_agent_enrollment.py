"""control.agent_keys + control.agent_credentials — đấu nối pod agent ngoài

VẤN ĐỀ NÓ GIẢI: M1/M3/M6 đã xây xong ba lớp cách ly cho agent (role + RLS +
view agent_api · policy tiền tố kho tệp · collection Qdrant riêng), nhưng KHÔNG
module nào cấp phát và giao credential cho pod. M3 §0 ghi thẳng "deployments ghi
bằng tay hoặc seed". Không có bảng nào ghi "pod này thuộc tenant nào", không có
đường thu hồi, không có đường xoay khoá.

VÌ SAO HAI BẢNG HẸP CHỨ KHÔNG THÊM CỘT VÀO deployments: cùng lý do
0007_agent_heartbeats.py viết ra. `agent_keys.last_used_at` bị ghi mỗi lần
bootstrap; `deployments` là hồ sơ triển khai và có FK từ agent_heartbeats trỏ
vào. Một bảng bị ghi thường xuyên không nên là neo danh tính của thứ khác.

VÌ SAO agent_credentials CHỈ CÓ MỘT SỐ NGUYÊN: bí mật được SUY DẪN từ
AGENT_MASTER_KEY (modules/enrollment/bi_mat.py), không lưu. Bảng này giữ đúng
`secret_version` để biết đang ở thế hệ nào. Một SELECT trên toàn schema control
KHÔNG lộ được mật khẩu nào — đó là tính chất, không phải may mắn.

VÌ SAO PHẢI SUY DẪN CHỨ KHÔNG SINH NGẪU NHIÊN RỒI LƯU: portal.current_tenant()
(0001:41) parse tenant TỪ TÊN ROLE. Nên mỗi tenant có ĐÚNG MỘT role
`agent_<slug>`, dùng chung cho pod chat lẫn pod voice. Hai pod phải suy ra CÙNG
một mật khẩu, nếu không pod voice khởi động lại sẽ đá văng pod chat.

VÌ SAO KHÔNG CẤP QUYỀN CHO agent_all: pod đã nhận credential của nó qua
bootstrap. Cho nó SELECT bảng này là cho một pod đọc dữ liệu vận hành của tenant
khác — không có lý do gì.

VÌ SAO KHÔNG RLS: cả hai bảng là control plane, chỉ `portal_api` đọc. Ngoại lệ
RLS duy nhất trong schema control vẫn là agent_heartbeats (0007), vì đó là bảng
control DUY NHẤT mà agent được ghi.

Revision ID: 0900_enrollment
Revises: 0402_an_sentinel
"""

from alembic import op

revision = "0900_enrollment"
down_revision = "0402_an_sentinel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.agent_keys (
            id            bigserial PRIMARY KEY,
            deployment_id bigint      NOT NULL REFERENCES control.deployments(id) ON DELETE CASCADE,
            key_sha256    text        NOT NULL UNIQUE,
            key_prefix    text        NOT NULL,
            label         text        NOT NULL DEFAULT '',
            created_at    timestamptz NOT NULL DEFAULT now(),
            created_by    text        NOT NULL DEFAULT '',
            revoked_at    timestamptz,
            last_used_at  timestamptz
        )
        """
    )
    # UNIQUE trên key_sha256 đã sinh index cho đường tra nóng nhất (bootstrap).
    # Index này cho đường "liệt kê khoá của một deployment".
    op.execute("CREATE INDEX agent_keys_deployment_idx ON control.agent_keys (deployment_id)")

    op.execute(
        """
        CREATE TABLE control.agent_credentials (
            tenant_id      text        PRIMARY KEY REFERENCES control.tenants(id) ON DELETE CASCADE,
            secret_version integer     NOT NULL DEFAULT 1 CHECK (secret_version >= 1),
            rotated_at     timestamptz NOT NULL DEFAULT now(),
            rotated_by     text        NOT NULL DEFAULT ''
        )
        """
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON control.agent_keys TO portal_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.agent_credentials TO portal_api")
    op.execute("GRANT USAGE ON SEQUENCE control.agent_keys_id_seq TO portal_api")

    # ── Helper SECURITY DEFINER: đặt mật khẩu role agent ─────────────────────
    #
    # VÌ SAO PHẢI CÓ: `portal_api` KHÔNG có CREATEROLE (cố ý — xem 0003), và
    # `control.create_agent_role()` của M1 KHÔNG phải SECURITY DEFINER. Nên API
    # runtime không tạo được role, cũng không ALTER PASSWORD được. Nhưng cấp phát
    # và xoay khoá là việc của runtime.
    #
    # Hai đường sai mà dễ nghĩ ra trước:
    #   - GRANT CREATEROLE TO portal_api  ⇒ runtime tạo được role BẤT KỲ, kể cả
    #     role có quyền cao hơn. Mở quá rộng cho một nhu cầu rất hẹp.
    #   - Sửa create_agent_role() của M1 thành SECURITY DEFINER ⇒ sửa hợp đồng của
    #     module khác, và đổi ngữ nghĩa một hàm mà migration khác đang gọi.
    #
    # Đường này hẹp đúng nhu cầu: hàm chạy bằng quyền owner nhưng CHỈ làm được một
    # việc, trên MỘT tên role suy từ tenant_id đã kiểm regex + đã kiểm tồn tại.
    # `portal_api` không đặt được tên role, không chọn được quyền cấp kèm.
    op.execute(
        r"""
        CREATE FUNCTION control.dat_mat_khau_agent(p_tenant text, p_password text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, control AS $$
        DECLARE r text := 'agent_' || p_tenant;
        BEGIN
            -- Cùng biểu thức với create_agent_role() của M1. Không nới lỏng: tên
            -- role đi thẳng vào format(%I), và tenant_id lạ là một lỗ.
            IF p_tenant !~ '^[a-z][a-z0-9_]{1,30}$' THEN
                RAISE EXCEPTION 'tenant id không hợp lệ cho tên role: %', p_tenant;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM control.tenants WHERE id = p_tenant) THEN
                RAISE EXCEPTION 'tenant chưa tồn tại: %', p_tenant;
            END IF;
            IF length(p_password) < 20 THEN
                RAISE EXCEPTION 'mật khẩu agent quá ngắn';
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('ALTER ROLE %I PASSWORD %L', r, p_password);
            ELSE
                -- Gọi lại hàm của M1 thay vì chép logic: toàn bộ quyền đến từ
                -- nhóm `agent_all`, và M1 sở hữu định nghĩa đó.
                PERFORM control.create_agent_role(p_tenant, p_password);
            END IF;
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION control.dat_mat_khau_agent(text, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION control.dat_mat_khau_agent(text, text) TO portal_api")


def downgrade() -> None:
    # IF EXISTS trên function: bản 0900 đầu tiên chưa có helper này, nên một DB đã
    # nạp bản đó rồi mới pull bản mới sẽ vỡ ở downgrade nếu thiếu. Bảng thì không
    # cần — chúng có từ dòng đầu của migration này.
    op.execute("DROP FUNCTION IF EXISTS control.dat_mat_khau_agent(text, text)")
    op.execute("DROP TABLE control.agent_credentials")
    op.execute("DROP TABLE control.agent_keys")
