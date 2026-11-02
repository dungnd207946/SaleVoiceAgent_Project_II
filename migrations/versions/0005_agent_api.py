"""schema agent_api — view DEFINER là hợp đồng đọc DUY NHẤT của agent

VÌ SAO KHÔNG DÙNG security_invoker (sửa lỗi C1 — spec gốc §5.4 ghi SAI):
  security_invoker=true bắt Postgres kiểm quyền của NGƯỜI GỌI trên bảng gốc,
  nghĩa là agent role phải được GRANT SELECT ON tenant_data.units. Có quyền đó
  là agent query THẲNG bảng gốc và bỏ qua toàn bộ gate cột. Cơ chế "view lo cột"
  bị vô hiệu hoàn toàn.

  Nên view ở đây là DEFINER (mặc định): agent có ZERO quyền trên tenant_data,
  chỉ SELECT được trên view. "Không vào được cửa" mạnh hơn "được vào nhưng bị
  lọc hàng".

HAI HỆ QUẢ CỦA DEFINER, cả hai phải xử lý tường minh:
  1. View chạy bằng quyền owner nên RLS của owner KHÔNG áp -> view PHẢI tự lọc
     tenant trong WHERE. Thiếu WHERE là rò hết, không có lỗi nào.
  2. Tenant phải suy từ session_user, KHÔNG phải current_user: trong view
     definer current_user trả về OWNER của view, không phải agent.

VÌ SAO pol() VÀ gated_extras() LÀ SECURITY DEFINER:
  Agent KHÔNG có SELECT trên control.field_policy_live. Nếu để hàm SQL thường
  thì việc nó đọc được bảng đó phụ thuộc vào Postgres có inline hàm vào câu
  query của view hay không — tức phụ thuộc một chi tiết TỐI ƯU HOÁ. Khai
  SECURITY DEFINER làm nó tường minh và không đổi theo phiên bản.
  session_user KHÔNG bị SECURITY DEFINER đổi, nên current_tenant() vẫn đúng.
  SET search_path cố định để chặn search_path injection.

Revision ID: 0005_agent_api
Revises: 0004_tenant_data
"""

from alembic import op

revision = "0005_agent_api"
down_revision = "0004_tenant_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pol(): field này agent đọc được không. KHÔNG có hàng policy -> false (chặn mặc định).
    op.execute(
        """
        CREATE FUNCTION portal.pol(p_entity text, p_field text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(
                (SELECT agent_readable FROM control.field_policy_live
                  WHERE tenant_id = portal.current_tenant()
                    AND entity = p_entity AND field = p_field),
                false)
        $$
        """
    )

    # gated_extras(): chỉ giữ key đã khai agent_readable VÀ is_core = false.
    # is_core = true nghĩa là cột thật, gate bằng CASE WHEN — không phải key extras.
    op.execute(
        """
        CREATE FUNCTION portal.gated_extras(p_entity text, p_extras jsonb) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(jsonb_object_agg(e.key, e.value), '{}'::jsonb)
              FROM jsonb_each(coalesce(p_extras, '{}'::jsonb)) AS e
             WHERE EXISTS (
                   SELECT 1 FROM control.field_policy_live f
                    WHERE f.tenant_id = portal.current_tenant()
                      AND f.entity = p_entity
                      AND f.field = e.key
                      AND f.is_core = false
                      AND f.agent_readable
             )
        $$
        """
    )

    op.execute("CREATE SCHEMA agent_api")

    # View KHÔNG lộ tenant_id: agent chỉ có một tenant, biết id của mình là dư.
    op.execute(
        """
        CREATE VIEW agent_api.units AS
        SELECT u.code, u.project_code, u.unit_type, u.status, u.direction,
               u.price_vnd, u.price_tts_vnd, u.area_m2, u.area_build_m2,
               u.bedrooms, u.fund_type, u.csbh_brief, u.gift, u.legal,
               CASE WHEN portal.pol('unit', 'commission')   THEN u.commission   END AS commission,
               CASE WHEN portal.pol('unit', 'bank_support') THEN u.bank_support END AS bank_support,
               CASE WHEN portal.pol('unit', 'csbh_full')    THEN u.csbh_full    END AS csbh_full,
               portal.gated_extras('unit', u.extras) AS extras,
               u.updated_at
          FROM tenant_data.units u
         WHERE u.tenant_id = portal.current_tenant()
        """
    )

    # floor CÓ trong bảng nhưng KHÔNG lên view: quyết định #17 — dữ liệu tầng
    # không tin được, và agent đọc một giá trị không tin được như thể đúng thì
    # sai âm thầm, tệ hơn trả rỗng. M4 quyết định lại khi có dữ liệu thật.
    op.execute(
        """
        CREATE VIEW agent_api.projects AS
        SELECT p.code, p.name, p.slug, p.type, p.region, p.location, p.investor,
               p.status, p.is_hot, p.sort_hot, p.overview, p.lat, p.lng,
               portal.gated_extras('project', p.extras) AS extras,
               p.updated_at
          FROM tenant_data.projects p
         WHERE p.tenant_id = portal.current_tenant()
        """
    )

    op.execute("GRANT USAGE ON SCHEMA agent_api TO portal_api")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA agent_api TO portal_api")

    # QUYỀN ĐỌC CỦA AGENT CẤP CHO ROLE NHÓM, MỘT LẦN.
    # Nhờ vậy create_agent_role() chỉ còn CREATE ROLE + GRANT agent_all — không
    # có danh sách grant nào phải nhớ cập nhật khi thêm view.
    op.execute("GRANT USAGE ON SCHEMA agent_api, portal TO agent_all")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA agent_api TO agent_all")
    op.execute("GRANT EXECUTE ON FUNCTION portal.current_tenant() TO agent_all")
    # Cấp EXECUTE tường minh cho pol()/gated_extras(), không dựa vào quyền EXECUTE
    # mặc định mà Postgres cấp cho PUBLIC trên hàm mới tạo. Quyền của agent với
    # view chạy qua đúng hai hàm này — một đợt hardening REVOKE EXECUTE ... FROM
    # PUBLIC theo thói quen (ví dụ chặn PUBLIC thấy nội bộ schema portal) sẽ âm
    # thầm làm mọi view agent_api trả lỗi permission denied nếu không có dòng này.
    op.execute("GRANT EXECUTE ON FUNCTION portal.pol(text, text) TO agent_all")
    op.execute("GRANT EXECUTE ON FUNCTION portal.gated_extras(text, jsonb) TO agent_all")
    # View thêm về sau (M3/M4/M7) tự động được cấp — không ai phải nhớ.
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api GRANT SELECT ON TABLES TO agent_all")

    # Hàm module sau gọi trong migration của mình để mở đường GHI cho agent.
    # Cấp cho NHÓM nên không phải quét danh sách role đang tồn tại, và role tạo
    # về sau cũng có ngay.
    #
    # CHỈ dùng cho bảng tenant_data mà một agent thật sự cần GHI — ví dụ
    # appointments/contacts/conversations mà M7 sẽ đăng ký bằng hàm này trong
    # migration của chính nó. control.agent_heartbeats KHÔNG đi qua đây dù cùng
    # là bảng agent ghi được: nó nằm ở schema control (control-plane, theo dõi
    # tiến trình agent), không phải tenant_data (dữ liệu nghiệp vụ của tenant),
    # nên bị guard bên dưới từ chối — ĐÚNG NHƯ THIẾT KẾ. Task 8 cấp quyền ghi
    # cho agent_heartbeats bằng GRANT thẳng trong migration của nó, không qua
    # grant_agent_write(). Hàm này KHÔNG được migration nào gọi cho tới khi một
    # module thật sự cần — vậy là đúng, không phải sót.
    op.execute(
        """
        CREATE FUNCTION control.grant_agent_write(p_qualified_table text)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE v_schema text;
        BEGIN
            SELECT n.nspname INTO v_schema
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.oid = p_qualified_table::regclass;
            IF v_schema <> 'tenant_data' THEN
                RAISE EXCEPTION 'agent chỉ được ghi bảng trong tenant_data, không phải %', v_schema;
            END IF;
            EXECUTE format('GRANT USAGE ON SCHEMA tenant_data TO agent_all');
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %s TO agent_all', p_qualified_table);
        END $$
        """
    )

    # Cấp role cho một tenant. Gọi lúc provisioning.
    # Đặt tên agent_<tenant> là HỢP ĐỒNG: portal.current_tenant() parse chính tên này.
    op.execute(
        r"""
        CREATE FUNCTION control.create_agent_role(p_tenant text, p_password text)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE r text := 'agent_' || p_tenant;
        BEGIN
            IF p_tenant !~ '^[a-z][a-z0-9_]{1,30}$' THEN
                RAISE EXCEPTION 'tenant id không hợp lệ cho tên role: %', p_tenant;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM control.tenants WHERE id = p_tenant) THEN
                RAISE EXCEPTION 'tenant chưa tồn tại: %', p_tenant;
            END IF;

            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', r, p_password);
            -- Toàn bộ quyền đến từ nhóm. Hàm này KHÔNG có danh sách grant riêng
            -- nào — thêm view hay bảng mới thì grant cho agent_all, không sửa đây.
            EXECUTE format('GRANT agent_all TO %I', r);
        END $$
        """
    )


def downgrade() -> None:
    """Thu hồi ĐÚNG những gì upgrade() đã cấp, theo thứ tự ngược.

    VÌ SAO PHẢI ĐỦ: quyền cấp cho `agent_all` trên các đối tượng của migration KHÁC
    (schema `portal` và `portal.current_tenant()`, cả hai do 0001 tạo) KHÔNG tự mất
    khi 0005 hạ. Chúng sống sót và làm `DROP ROLE agent_all` ở downgrade của 0003 vỡ:

        role "agent_all" cannot be dropped because some objects depend on it
        DETAIL:  privileges for schema portal

    Quyền trên schema `agent_api` và trên hai view thì KHÔNG cần revoke — chúng biến
    mất cùng `DROP SCHEMA agent_api CASCADE`. Nhưng ALTER DEFAULT PRIVILEGES phải
    revoke TRƯỚC khi drop schema, vì sau đó không còn schema để trỏ tới nữa.
    """
    op.execute("DROP FUNCTION control.create_agent_role(text, text)")
    op.execute("DROP FUNCTION control.grant_agent_write(text)")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api REVOKE SELECT ON TABLES FROM agent_all")
    op.execute("DROP SCHEMA agent_api CASCADE")
    op.execute("DROP FUNCTION portal.gated_extras(text, jsonb)")
    op.execute("DROP FUNCTION portal.pol(text, text)")
    # portal.current_tenant() và schema portal thuộc 0001 — grant cho agent_all ở
    # đây thì revoke ở đây, không thì 0003 không drop được role.
    op.execute("REVOKE EXECUTE ON FUNCTION portal.current_tenant() FROM agent_all")
    op.execute("REVOKE ALL ON SCHEMA portal FROM agent_all")
