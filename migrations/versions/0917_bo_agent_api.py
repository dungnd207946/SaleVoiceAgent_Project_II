"""Bỏ schema agent_api, agent đọc thẳng bảng gốc — đơn giản hoá đường đọc

QUYẾT ĐỊNH CÓ CHỦ Ý, ĐI NGƯỢC LẠI LÝ LẼ GỐC CỦA `0005_agent_api`: docstring của
`0005` từ chối đúng phương án này ("`security_invoker=true` bắt agent role phải
được `GRANT SELECT ON tenant_data.units` ... 'Không vào được cửa' mạnh hơn
'được vào nhưng bị lọc hàng'"). Migration này chọn ngược lại — người yêu cầu đã
được cảnh báo, kể cả nhắc lại sự cố `0909` (RLS tắt ⇒ rò xuyên tenant thật), và
chọn đơn giản hơn thay vì lớp phòng thủ "role không có quyền gì trên bảng gốc".

Hai lý do phần "gate cột" của `0005` không còn áp dụng: `field_policy_live` đã
rỗng (0 hàng) từ khi KB viết lại theo `real_estate`, và cả 9 view `agent_api.*`
hiện hành (`pg_get_viewdef`, đo 2026-08-10) không còn gọi `portal.pol()` /
`portal.gated_extras()` — hai hàm đó vẫn còn trong `portal.*` nhưng mồ côi, MIGRATION
NÀY KHÔNG ĐỤNG TỚI (ngoài phạm vi được yêu cầu; dọn riêng nếu cần sau).

HAI NHÓM VIEW BỊ BỎ, LÝ DO KHÁC NHAU:
  · `documents · media · projects · units · zones` (đọc `tenant_data`, đã RLS FORCE từ
    `0913`): agent tự lọc `status='published'` bằng câu SQL của mình từ nay — view
    trước đây làm việc đó bằng JOIN sang `projects.status`, không việc nào còn nếu
    không viết lại tay ở phía agent.
  · `tenant_status · tenant_keys · deployments · agent_published_config` (đọc
    `control`): trùng lặp với `/runtime-credentials` đã ship (xem
    `docs/contracts/agent-postgres-read-contract.REVIEW.md` §D — khuyến nghị không
    build ba cái đầu, nhưng `0907` đã lỡ build). `agent_published_config` là đường
    đọc live-config qua Postgres song song với poll object `LIVE` trên kho tệp
    (`bundle.md`) — sau migration này, poll `LIVE` là đường DUY NHẤT.

REVOKE PUBLIC TRÊN `control` (đảo `0908`): `0908` cấp SELECT cho PUBLIC vì một hệ
thống thứ ba (không phải `agent_<tenant>`) cần đọc mọi tenant trong một kết nối —
hệ thống đó không còn tồn tại/không còn cần (xác nhận với người yêu cầu, không suy
từ code). Đo trước khi revoke: `portal_api` có GRANT riêng trên cả 20 bảng/view của
`control`, độc lập hoàn toàn với PUBLIC — revoke không ảnh hưởng nó. `agent_all` chỉ
có grant riêng trên `agent_heartbeats` (SELECT/INSERT/UPDATE, từ `0007`/`0905`) —
grant đó KHÔNG đụng, agent vẫn ghi được nhịp tim. 18 bảng còn lại của `control` mà
`agent_all` đọc được hôm nay đều CHỈ nhờ PUBLIC — sau migration này, `agent_all`
không còn đọc được gì trong `control` ngoài `agent_heartbeats`.

KHÔNG CẦN GRANT RIÊNG CHO `agent_all` TRÊN 5 BẢNG `tenant_data`: đo trước khi viết
migration này phát hiện `tenant_data` đã có `SELECT` cho `PUBLIC` trên **cả 12 bảng**
(không riêng 5 bảng agent_api từng lộ) — di sản của `0909_bo_rls_toan_bo` (`GRANT
SELECT ON ALL TABLES IN SCHEMA tenant_data TO PUBLIC` + default privileges cho bảng
tạo sau), mà `0913` bật lại RLS không hề revoke. Người yêu cầu migration này xác nhận
CỐ Ý giữ nguyên PUBLIC đó cho `tenant_data` (khác quyết định với `control` ở trên) —
nghĩa là mọi role, kể cả role tạo sau này, đều SELECT được mọi bảng `tenant_data`,
cách ly hoàn toàn dựa vào RLS FORCE. Vì vậy, agent đã đọc được 5 bảng đó (documents/
media/projects/units/zones) ngay cả không có migration này — nó KHÔNG cấp thêm quyền
đọc nào, chỉ bỏ view.

Revision ID: 0917_bo_agent_api
Revises: 0916_conversations_source
"""

from alembic import op

revision = "0917_bo_agent_api"
down_revision = "0916_conversations_source"
branch_labels = None
depends_on = None

_VIEWS_TENANT_DATA = {
    "documents": """
        SELECT d.id, d.project_code, d.title, d.body, d.file_url, d.status, d.created_at, d.updated_at
          FROM tenant_data.documents d
          JOIN tenant_data.projects p ON p.tenant_id = d.tenant_id AND p.project_code = d.project_code
         WHERE d.tenant_id = portal.current_tenant() AND d.status = 'published'
           AND p.tenant_id = portal.current_tenant() AND p.status = 'published'
    """,
    "media": """
        SELECT m.id, m.project_code, m.zone_code, m.unit_code, m.content_type, m.category, m.caption,
               m.media_url, m.thumb_url, m.content_hash, m.uploaded_by, m.status, m.created_at, m.updated_at
          FROM tenant_data.media m
          JOIN tenant_data.projects p ON p.tenant_id = m.tenant_id AND p.project_code = m.project_code
         WHERE m.tenant_id = portal.current_tenant() AND m.status = 'published'
           AND p.tenant_id = portal.current_tenant() AND p.status = 'published'
    """,
    "projects": """
        SELECT id, project_code, name, category, region, address, investor, developer,
               total_land_area_m2, floor_area_m2, build_density_pct, product_scale, amenities,
               ownership_form, handover_standard, total_investment_vnd, sale_phase, overview,
               link_360, cover_media_id, map_media_id, status, created_at, updated_at
          FROM tenant_data.projects
         WHERE tenant_id = portal.current_tenant() AND status = 'published' AND project_code <> '__ALL__'
    """,
    "units": """
        SELECT u.id, u.project_code, u.zone_code, u.unit_code, u.product_type, u.bedrooms, u.block,
               u.floor, u.num_floors, u.direction, u.area_built_m2, u.area_wall_m2, u.area_land_m2,
               u.price_vnd, u.price_per_m2_vnd, u.sale_status, u.image_url, u.status, u.created_at, u.updated_at
          FROM tenant_data.units u
          JOIN tenant_data.projects p ON p.tenant_id = u.tenant_id AND p.project_code = u.project_code
         WHERE u.tenant_id = portal.current_tenant() AND u.status = 'published'
           AND p.tenant_id = portal.current_tenant() AND p.status = 'published'
    """,
    "zones": """
        SELECT z.id, z.project_code, z.zone_code, z.name, z.category, z.product_scale, z.overview,
               z.cover_media_id, z.map_media_id, z.status, z.created_at, z.updated_at
          FROM tenant_data.zones z
          JOIN tenant_data.projects p ON p.tenant_id = z.tenant_id AND p.project_code = z.project_code
         WHERE z.tenant_id = portal.current_tenant() AND z.status = 'published'
           AND p.tenant_id = portal.current_tenant() AND p.status = 'published'
    """,
}

_VIEWS_CONTROL = {
    "deployments": """
        SELECT tenant_id, id, kind FROM control.deployments d WHERE tenant_id = portal.current_tenant()
    """,
    "tenant_keys": """
        SELECT d.tenant_id, k.key_sha256, k.revoked_at IS NULL AS active
          FROM control.agent_keys k JOIN control.deployments d ON d.id = k.deployment_id
         WHERE d.tenant_id = portal.current_tenant()
    """,
    "tenant_status": """
        SELECT id AS tenant_id, lifecycle = 'active' AS active
          FROM control.tenants t WHERE id = portal.current_tenant()
    """,
    "agent_published_config": """
        SELECT v.tenant_id, v.version, v.config_agent AS config,
               (v.payload ->> 'schema_version')::integer AS schema_version
          FROM control.config_versions v
          JOIN control.config_live l ON l.tenant_id = v.tenant_id AND l.version = v.version
         WHERE v.tenant_id = portal.current_tenant()
    """,
}


_BANG_LEFTOVER_TU_0907 = (
    "tenant_status_seed_agent_truoc_0907",
    "tenant_keys_seed_agent_truoc_0907",
)
"""Hai bảng data giả (`dufake`) mà `0907` đổi tên giữ lại, xem `_nhuong_cho()` ở đó.

Docstring `0907` yêu cầu dọn TAY sau khi đối chiếu — chưa từng xảy ra ở mọi DB đã chạy
"Phụ lục A" cũ, nên `DROP SCHEMA agent_api` bên dưới vỡ với `DependentObjectsStillExist`
(schema còn 2 bảng này). Dời chúng ra `public` trước khi drop, cùng lý lẽ với `0907`:
không phải data của Portal, không được `DROP TABLE` tự động — chỉ `SET SCHEMA`, giữ
nguyên từng hàng, tự chịu được cả DB đã dọn tay (bảng không còn thì không làm gì)."""


def _doi_cho_bang_leftover(ten: str) -> str:
    return f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'agent_api' AND c.relname = '{ten}'
            ) THEN
                EXECUTE 'ALTER TABLE agent_api.{ten} SET SCHEMA public';
                RAISE NOTICE 'agent_api.{ten} đã dời sang public.{ten} trước DROP SCHEMA (data giữ nguyên)';
            END IF;
        END $$
    """


def upgrade() -> None:
    for view in (*_VIEWS_TENANT_DATA, *_VIEWS_CONTROL):
        op.execute(f"DROP VIEW IF EXISTS agent_api.{view}")
    for ten in _BANG_LEFTOVER_TU_0907:
        op.execute(_doi_cho_bang_leftover(ten))
    op.execute("DROP SCHEMA IF EXISTS agent_api")

    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control REVOKE SELECT ON TABLES FROM PUBLIC")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA control FROM PUBLIC")
    op.execute("REVOKE USAGE ON SCHEMA control FROM PUBLIC")

    # `0901` đặt search_path = agent_api, public cho odyssey_agent — schema đó vừa bị
    # DROP ở trên, nên search_path giờ trỏ vào một schema không tồn tại (không lỗi ngay,
    # chỉ lặng lẽ không resolve được tên bảng không kèm schema). RESET thay vì trỏ sang
    # tenant_data: bắt buộc agent tự ghi rõ schema (`tenant_data.units`), đúng khuyến nghị
    # đã có sẵn trong agent-postgres-read-contract.REVIEW.md §E — search_path ở mức role
    # là trạng thái ẩn, dễ vỡ mỗi khi thêm schema mới.
    op.execute("ALTER ROLE odyssey_agent RESET search_path")


def downgrade() -> None:
    op.execute("ALTER ROLE odyssey_agent SET search_path = agent_api, public")

    op.execute("GRANT USAGE ON SCHEMA control TO PUBLIC")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA control TO PUBLIC")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA control GRANT SELECT ON TABLES TO PUBLIC")

    op.execute("CREATE SCHEMA agent_api")
    op.execute("GRANT USAGE ON SCHEMA agent_api TO agent_all")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api GRANT SELECT ON TABLES TO agent_all")

    for name, body in {**_VIEWS_TENANT_DATA, **_VIEWS_CONTROL}.items():
        op.execute(f"CREATE VIEW agent_api.{name} AS {body}")
        op.execute(f"GRANT SELECT ON agent_api.{name} TO agent_all")
