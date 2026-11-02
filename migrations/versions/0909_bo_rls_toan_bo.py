"""Bỏ RLS toàn bộ (tenant_data + control.agent_heartbeats) — quyết định có chủ đích, đọc trước khi downgrade

BỐI CẢNH: 0908 mở `control` cho PUBLIC để một hệ thống agent bên ngoài đọc toàn bộ tenant, tự
lọc `tenant_id` theo logic của họ. Khi rà lại, `control` không phải nơi duy nhất có tenant
isolation ở tầng DB — `tenant_data.*` (toàn bộ dữ liệu nghiệp vụ: projects, units, zones, media,
documents, contacts, conversations, appointments, kb_files, kb_index_state) có RLS
ENABLE + FORCE qua `control.enforce_tenant_isolation()` (`0003_role_and_isolation_helper.py:101-108`),
và `control.agent_heartbeats` có RLS riêng (`0007_agent_heartbeats.py:65-80`).

⚠️ ĐÃ CẢNH BÁO TRƯỚC KHI CHẠY, GHI LẠI Ở ĐÂY VÌ QUAN TRỌNG HƠN MỌI CẢNH BÁO KHÁC TRONG REPO NÀY:
RLS trên `tenant_data` KHÔNG PHẢI cơ chế riêng cho bên đọc ngoài — nó là lưới an toàn nền cho
CHÍNH APP PORTAL, chạy bằng role `portal_api`/`odyssey_app` mỗi ngày. Vì dùng `FORCE ROW LEVEL
SECURITY`, nó áp cho mọi role không chừa ai, kể cả role app production. Tác dụng thật của nó:
nếu code Portal có một chỗ quên `WHERE tenant_id = ...` (bug, không phải giả định), RLS vẫn chặn
ở tầng DB — tenant A không thấy được dữ liệu tenant B dù code sai. Migration này DỠ ĐÚNG LƯỚI ĐÓ,
cho TOÀN BỘ hệ thống, không chỉ cho 2 role đọc ngoài của 0908. Từ sau migration này, một bug quên
WHERE ở bất kỳ đâu trong `src/portal` sẽ lộ dữ liệu thật giữa các khách hàng, không có lớp nào ở
DB chặn lại nữa. Người yêu cầu migration này đã được hỏi rõ và chọn phương án này thay vì phương
án hẹp hơn (chỉ cấp BYPASSRLS cho 2 role đọc ngoài, giữ RLS cho app thật) — xem lịch sử trao đổi
trong PR/commit đi kèm migration này nếu cần đối chiếu lại quyết định.

VÌ SAO KHÔNG DROP LUÔN `control.enforce_tenant_isolation()`: hàm này là cách "thêm lại RLS cho
một bảng" nhanh nhất nếu sau này cần khôi phục cho một bảng cụ thể (`SELECT
control.enforce_tenant_isolation('tenant_data.<bảng>')`). Migration này chỉ dỡ RLS đã áp, không
xoá công cụ để áp lại.

VÌ SAO DÙNG DO-BLOCK DÒ ĐỘNG THAY VÌ LIỆT KÊ TÊN BẢNG: danh sách bảng `tenant_data.*` có RLS đã
qua tay nhiều migration (`0004`, `0300`, `0400`, `0501`, `0903`) và còn tăng thêm về sau. Liệt kê
tay là kiểu danh sách sẽ lệch với thực tế DB ngay migration tiếp theo. Dò theo
`pg_class.relrowsecurity = true` xử lý đúng TẤT CẢ bảng đang có RLS tại thời điểm chạy, không cần
biết tên trước.

Revision ID: 0909_bo_rls_toan_bo
Revises: 0908_readonly_control
"""

from alembic import op

revision = "0909_bo_rls_toan_bo"
down_revision = "0908_readonly_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Xoá mọi policy rồi tắt RLS trên MỌI bảng trong tenant_data/control đang có RLS — kể cả
    # bảng chưa biết tên (tạo ở migration sau 0007/0903 nhưng trước migration này).
    op.execute(
        """
        DO $$
        DECLARE
            r RECORD;
            p RECORD;
        BEGIN
            FOR r IN
                SELECT n.nspname, c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname IN ('tenant_data', 'control')
                   AND c.relkind = 'r'
                   AND c.relrowsecurity
            LOOP
                FOR p IN
                    SELECT policyname FROM pg_policies
                     WHERE schemaname = r.nspname AND tablename = r.relname
                LOOP
                    EXECUTE format('DROP POLICY %I ON %I.%I', p.policyname, r.nspname, r.relname);
                END LOOP;

                EXECUTE format('ALTER TABLE %I.%I NO FORCE ROW LEVEL SECURITY', r.nspname, r.relname);
                EXECUTE format('ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY', r.nspname, r.relname);
                RAISE NOTICE 'Đã tắt RLS + xoá hết policy trên %.%', r.nspname, r.relname;
            END LOOP;
        END $$
        """
    )

    # `tenant_data` trước giờ chỉ `portal_api` có GRANT (cấp trong `enforce_tenant_isolation()`
    # mỗi lần gọi) — PUBLIC chưa từng có quyền đọc bảng nào ở schema này. Tắt RLS mà không GRANT
    # thì PUBLIC vẫn không đọc được gì (permission denied) — không đạt mục tiêu "ai cũng đọc được"
    # như đã làm cho `control` ở 0908.
    op.execute("GRANT USAGE ON SCHEMA tenant_data TO PUBLIC")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA tenant_data TO PUBLIC")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_data GRANT SELECT ON TABLES TO PUBLIC")


def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_data REVOKE SELECT ON TABLES FROM PUBLIC")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA tenant_data FROM PUBLIC")
    op.execute("REVOKE USAGE ON SCHEMA tenant_data FROM PUBLIC")

    # Dựng lại đúng policy `tenant_isolation` mà `control.enforce_tenant_isolation()` tạo, cho
    # MỌI bảng tenant_data có cột tenant_id — tức trả lại đúng trạng thái trước migration này cho
    # nhánh tenant_data, không cần biết trước tên bảng.
    op.execute(
        """
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'tenant_data'
                   AND c.relkind = 'r'
                   AND EXISTS (
                       SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                          AND a.attnum > 0 AND NOT a.attisdropped
                   )
            LOOP
                EXECUTE format('ALTER TABLE tenant_data.%I ENABLE ROW LEVEL SECURITY', r.relname);
                EXECUTE format('ALTER TABLE tenant_data.%I FORCE ROW LEVEL SECURITY', r.relname);
                EXECUTE format(
                    'CREATE POLICY tenant_isolation ON tenant_data.%I '
                    'USING (tenant_id = portal.current_tenant()) '
                    'WITH CHECK (tenant_id = portal.current_tenant())',
                    r.relname
                );
            END LOOP;
        END $$
        """
    )

    # Đúng 2 policy gốc của `0007_agent_heartbeats.py:65-80` — chép lại nguyên văn, không suy ra
    # từ dữ liệu DB vì tên role/vị từ không nằm trong catalog nào tự dò lại được.
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
