"""role portal_api + helper bật cách ly cho một bảng

VÌ SAO CÓ HELPER: cách ly đúng chỉ khi BỐN điều kiện cùng đúng, và cả bốn hỏng
ÂM THẦM nếu sai (app chạy bình thường, test một-tenant vẫn xanh, chỉ dữ liệu là
rò). Viết bốn điều kiện đó ra một lời gọi duy nhất, một lần, thay vì lặp lại ở
mỗi module — mỗi lần lặp là một cơ hội sai.

  1. ENABLE ROW LEVEL SECURITY
  2. FORCE ROW LEVEL SECURITY   <- Postgres MIỄN RLS cho chủ bảng. Thiếu dòng
                                   này thì mọi truy vấn chạy bằng owner (script
                                   backfill, phiên debug) đi xuyên cách ly.
  3. policy tenant_isolation với CẢ USING (chặn đọc) và WITH CHECK (chặn ghi
     sang tenant khác)
  4. grant chuẩn cho role runtime

Điều kiện thứ tư của cách ly — SET LOCAL trong giao dịch tường minh — không ở
đây được, nó ở tầng Python: portal.core.db.session.tenant_conn().

HỆ QUẢ CỦA `FORCE` MÀ MIGRATION SAU PHẢI BIẾT: migration nào BACKFILL dữ liệu
(không chỉ DDL) cũng bị RLS lọc, vì nó chạy bằng owner. Luật: backfill phải
SET LOCAL app.tenant_id cho từng tenant, HOẶC
    ALTER TABLE ... NO FORCE ROW LEVEL SECURITY
    -> backfill ->
    ALTER TABLE ... FORCE ROW LEVEL SECURITY
trong CÙNG một migration. Ghi vào header của migration đó.

Revision ID: 0003_role_isolation
Revises: 0002_control_core
"""

from alembic import op

revision = "0003_role_isolation"
down_revision = "0002_control_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent_all: role NHÓM (NOLOGIN) mà mọi agent_<tenant> là thành viên.
    # Nhờ nó, quyền của agent cấp MỘT LẦN cho nhóm thay vì lặp lại cho từng
    # role — nên create_agent_role() chỉ còn hai dòng, và module sau thêm bảng
    # agent ghi được thì grant một lần, không phải quét danh sách role đang có.
    # Nó cũng là chỗ để policy RLS trỏ tới (`TO agent_all`) — xem migration 0007.
    op.execute("CREATE ROLE agent_all NOLOGIN")

    # portal_api: role runtime của Portal API và của worker.
    # KHÔNG BYPASSRLS, KHÔNG superuser, KHÔNG owner bảng nào -> kể cả bug quên
    # WHERE cũng không rò chéo tenant.
    #
    # NOLOGIN VÀ KHÔNG MẬT KHẨU — CỐ Ý, ĐỪNG "SỬA" LẠI.
    # Bản trước ghi `CREATE ROLE portal_api LOGIN PASSWORD 'apidev'`. portal_api
    # được phép `SET app.tenant_id` sang GIÁ TRỊ NÀO CŨNG ĐƯỢC, nên một mật khẩu
    # nằm trong git là quyền đọc-ghi đầy đủ trên MỌI tenant cho bất kỳ ai với tới
    # được cổng Postgres. Không có runbook nào bù được cho một bí mật đã công bố.
    #
    # Để NOLOGIN làm hệ FAIL CLOSED: quên bước cấp mật khẩu ở môi trường thật thì
    # app KHÔNG NỐI ĐƯỢC (lỗi to, thấy ngay lúc deploy), thay vì nối được bằng
    # mật khẩu mà cả thế giới đọc được trong repo. Cấp quyền đăng nhập là việc của
    # người vận hành (deploy/README.md §3) và của tests/conftest.py (nó nối bằng
    # superuser trong container nên tự `ALTER ROLE ... LOGIN PASSWORD` được).
    op.execute("CREATE ROLE portal_api NOLOGIN")
    op.execute("GRANT USAGE ON SCHEMA portal, control TO portal_api")
    op.execute("GRANT EXECUTE ON FUNCTION portal.current_tenant() TO portal_api")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA control TO portal_api")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA control TO portal_api")
    # Bảng control tạo về sau (bởi M2a/M3, hoặc migration 0006/0007 của M1)
    # cũng được grant, khỏi phải nhớ.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal_api"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT USAGE ON SEQUENCES TO portal_api")

    op.execute(
        """
        CREATE FUNCTION control.enforce_tenant_isolation(p_qualified_table text)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            v_oid    oid;
            v_schema text;
        BEGIN
            v_oid := p_qualified_table::regclass;

            SELECT n.nspname INTO v_schema
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.oid = v_oid;

            IF v_schema <> 'tenant_data' THEN
                RAISE EXCEPTION
                    'enforce_tenant_isolation chỉ dùng cho bảng trong schema tenant_data, không phải %',
                    v_schema;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_attribute
                 WHERE attrelid = v_oid AND attname = 'tenant_id' AND attnum > 0 AND NOT attisdropped
            ) THEN
                RAISE EXCEPTION 'bảng % thiếu cột tenant_id — không bật được cách ly', p_qualified_table;
            END IF;

            EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', p_qualified_table);
            EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', p_qualified_table);
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %s '
                'USING (tenant_id = portal.current_tenant()) '
                'WITH CHECK (tenant_id = portal.current_tenant())',
                p_qualified_table
            );
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON %s TO portal_api', p_qualified_table
            );
        END $$
        """
    )


def downgrade() -> None:
    """Thu hồi ĐÚNG những gì upgrade() đã cấp, theo thứ tự ngược.

    VÌ SAO PHẢI ĐỦ: `DROP ROLE` thất bại nếu role còn bị bất cứ ACL nào tham chiếu.
    Bản trước sót `REVOKE EXECUTE ON FUNCTION portal.current_tenant()` nên
    `alembic downgrade base` vỡ với:

        role "portal_api" cannot be dropped because some objects depend on it
        DETAIL:  privileges for function portal.current_tenant()

    Một chuỗi downgrade vỡ nghĩa là không ai dựng lại được DB từ đầu để kiểm chứng
    migration, và cách sửa nhanh ("cứ DROP OWNED BY cho xong") sẽ xoá luôn quyền của
    role khác. Nên luật ở đây: mỗi grant trong upgrade() có đúng một revoke ở đây.
    """
    op.execute("DROP FUNCTION control.enforce_tenant_isolation(text)")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control REVOKE USAGE ON SEQUENCES FROM portal_api")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA control REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM portal_api"
    )
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA control FROM portal_api")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA control FROM portal_api")
    op.execute("REVOKE EXECUTE ON FUNCTION portal.current_tenant() FROM portal_api")
    op.execute("REVOKE ALL ON SCHEMA portal, control FROM portal_api")
    op.execute("DROP ROLE portal_api")
    op.execute("DROP ROLE agent_all")
