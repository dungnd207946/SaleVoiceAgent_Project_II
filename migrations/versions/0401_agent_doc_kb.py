"""agent_api — lớp đọc DUY NHẤT của agent trên 5 bảng KB BĐS (Task 6)

FILE NÀY THAY `0401_agent_api_bds.py` (stub chỉ `DROP VIEW IF EXISTS`, xem header
cũ của nó): `0400_kb_real_estate.py` đã dựng lại 5 bảng KB theo tài liệu mới
(`docs/build_module_knowledgebase/`), và đây là migration dựng LẠI lớp đọc của
agent cho đúng schema đó. `revision`/`down_revision` GIỮ NGUYÊN "0401_agent_api_bds"
— chỉ đổi TÊN FILE — vì `0102_organizations.py` (session M2a, đang chạy song song)
đã chèn `down_revision = "0401_agent_api_bds"` vào chuỗi; đổi revision id ở đây là
làm gãy migration của họ. Alembic quét mọi file trong `migrations/versions/` theo
`revision`/`down_revision` bên trong, không theo tên file, nên đổi tên file không
ảnh hưởng gì tới việc discover.

QUYẾT ĐỊNH ĐÃ CHỐT — VIẾT LÝ DO VÀO ĐÂY (spec kế hoạch bắt buộc):

`00-overview.md §2.1` nói *"⚠️ không dùng VIEW agent_*"* — ý đồ thật của câu đó
(`02-knowledge-base.md §1`) là "bỏ GATE ĐỌC": không còn `CASE WHEN portal.pol(...)`
che cột theo `field_policy_live`, vì KB giờ không lưu trường nội bộ nhạy cảm nữa
(`commission`/`bank_support`/`csbh_full`/... đã bị `0400` xoá khỏi schema, không
phải chỉ che ở tầng đọc). Nhưng đọc chữ theo nghĩa đen — bỏ VIEW, `GRANT SELECT`
thẳng `tenant_data.*` cho `agent_all` — sẽ NỚI quyền của agent so với hiện trạng:
`0005_agent_api.py` (M1, không thuộc phạm vi task này) đã cho agent **zero
privilege** trên `tenant_data`, chỉ `SELECT` được trên `agent_api.*`. Tính chất đó
MẠNH HƠN cái tài liệu đòi ("không vào được cửa" mạnh hơn "vào được nhưng bị lọc
hàng") — hạ nó xuống để khớp câu chữ là làm cách ly YẾU đi, ngược với tinh thần
toàn bộ tài liệu `02 §5`.

CHỌN: (a) GIỮ VIEW, BỎ GATE CỘT. Mỗi view dưới đây `SELECT` **mọi** cột nghiệp vụ
của bảng gốc (không có `CASE WHEN pol(...)` nào nữa — không còn cột nhạy cảm nào
để gate, vì `0400` không tạo ra chúng), cộng `WHERE` lọc tenant + cascade
`status = 'published'`. Cách này đạt ĐÚNG điều tài liệu muốn bỏ (che cột theo
policy) mà KHÔNG nới quyền agent trên bảng gốc, và không phải sửa `0003`/`0005`
của M1 (việc đó, nếu chọn nhánh (b) theo chữ, là của M1 — ngoài phạm vi Task 6).

`portal.pol()`/`portal.gated_extras()` (0005) VẪN CÒN trong DB — không hàm nào ở
đây gọi chúng nữa vì không còn cột nào cần gate, nhưng XOÁ chúng là quyết định của
CHỦ M1 (chúng thuộc file `0005_agent_api.py`), không phải của Task 6. Bản thân
`0005` cũng không bị đụng vào ở đây.

HAI HỆ QUẢ CỦA VIEW DEFINER (nhắc lại từ `0005`, vẫn đúng ở đây — mỗi view mới vẫn
DEFINER mặc định, không khai `security_invoker`):
  1. View chạy bằng quyền OWNER nên RLS của owner KHÔNG áp bên trong nó — mỗi view
     PHẢI tự lọc tenant bằng `WHERE <bảng>.tenant_id = portal.current_tenant()`.
     Thiếu vị từ đó là rò hết, không một lỗi nào báo (test
     `test_moi_view_agent_api_tu_loc_tenant` canh việc này bằng cách quét
     `pg_get_viewdef` tìm "current_tenant").
  2. `portal.current_tenant()` suy tenant từ `session_user` (tên role `agent_<x>`),
     KHÔNG phải GUC `app.tenant_id` — agent không tự đổi được tenant của mình dù
     có SET.

CASCADE — MỆNH ĐỀ TENANT THỨ HAI, DỄ QUÊN NHẤT: 4 bảng con (`zones`/`units`/
`documents`/`media`) đều JOIN vào `tenant_data.projects` để lọc `status`
('published' của anchor), và JOIN đó CŨNG phải mang `p.tenant_id =
portal.current_tenant()` — không chỉ `p.tenant_id = <bảng con>.tenant_id`. Thiếu
đúng vị từ đó thì (vì view là DEFINER, RLS không áp cho owner) `projects` bị đọc
XUYÊN TENANT bên trong JOIN: một agent của tenant A có thể join trúng một dự án
`published` của tenant B miễn `project_code` trùng, và bảng con của A "cascade" qua
cửa dự án của B. Test `tests/modules/realestate/test_agent_doc_duoc.py` khoá cả
việc này bằng cách bơm hai tenant có CÙNG `project_code`.

`documents`/`media` gộp thêm `__ALL__` (`02 §2`) NHỜ CHÍNH JOIN trên, không cần
nhánh SQL riêng: `"__ALL__"` là một row `tenant_data.projects` hệ thống
(`status = 'published'`, seed ở Task 5/`scripts/seed_bds.py`), nên JOIN thường đã
cho nó đi qua cascade như một dự án bình thường.

CỘT `tenant_id` KHÔNG LÊN VIEW — nếp cũ của `0005`: agent chỉ phục vụ đúng MỘT
tenant (chính nó), biết lại id của mình là dư và là một cách rò không cần thiết
nếu view join sai. `id` (surrogate PK) THÌ CÓ mặt trên cả 5 view — khác `0005` cũ
(view `projects`/`units` không có `id`, chỉ có `code` làm định danh): `units`/
`documents`/`media` ở schema mới KHÔNG có khoá nghiệp vụ nào unique
(`unit_code` cố ý không unique — `02a §4.3`), nên `id` là cách DUY NHẤT agent
tham chiếu một hàng cụ thể (vd trả lời "căn #123").

DANH SÁCH CỘT khớp Y HỆT `_COT_RA` trong `src/portal/modules/realestate/repo.py`
(trừ `tenant_id`) — đó là "tham chiếu đúng" brief chỉ định, và các hàm
`*_cho_agent` ở đó (chạy qua `portal_api` dưới RLS) cùng logic cascade + `__ALL__`
với các view DEFINER ở đây; hai đường đọc song song, một cho CMS (qua RLS), một
cho agent (qua view), CÙNG một tập dữ liệu hiển thị.

GRANT: `ALTER DEFAULT PRIVILEGES IN SCHEMA agent_api GRANT SELECT ON TABLES TO
agent_all` (đặt ở `0005`, chạy bởi CÙNG role migrator thực thi migration này) tự
động cấp SELECT cho `agent_all` trên 5 view mới — không cần GRANT lại. Nhưng GRANT
tường minh vẫn được ghi ở đây (không có hại — chỉ củng cố ý định), và `portal_api`
CHỈ được cấp một lần cho các view TỒN TẠI LÚC `0005` CHẠY (`GRANT SELECT ON ALL
TABLES IN SCHEMA agent_api TO portal_api` không phải ALTER DEFAULT PRIVILEGES) nên
5 view MỚI này cần GRANT tường minh cho `portal_api`, không tự động.

Revision ID: 0401_agent_api_bds
Revises: 0400_bds_full
"""

from alembic import op

revision = "0401_agent_api_bds"
down_revision = "0400_bds_full"
branch_labels = None
depends_on = None

# Khớp _COT_RA["project"] trong repo.py, TRỪ tenant_id (xem header — agent chỉ có
# một tenant, biết id của mình là dư).
_COT_DU_AN = (
    "id, project_code, name, category, region, address, investor, developer, "
    "total_land_area_m2, floor_area_m2, build_density_pct, product_scale, amenities, "
    "ownership_form, handover_standard, total_investment_vnd, sale_phase, overview, "
    "link_360, cover_media_id, map_media_id, status, created_at, updated_at"
)
_COT_PHAN_KHU = (
    "id, project_code, zone_code, name, category, product_scale, overview, "
    "cover_media_id, map_media_id, status, created_at, updated_at"
)
_COT_CAN = (
    "id, project_code, zone_code, unit_code, product_type, bedrooms, block, floor, "
    "num_floors, direction, area_built_m2, area_wall_m2, area_land_m2, price_vnd, "
    "price_per_m2_vnd, sale_status, image_url, status, created_at, updated_at"
)
_COT_TAI_LIEU = "id, project_code, title, body, file_url, status, created_at, updated_at"
_COT_MEDIA = (
    "id, project_code, zone_code, unit_code, content_type, category, caption, "
    "media_url, thumb_url, content_hash, uploaded_by, status, created_at, updated_at"
)


def _voi_tien_to(cot: str, tien_to: str) -> str:
    """`"a, b"` -> `"t.a, t.b"` — cùng tiện ích với `repo.py`, viết lại tại chỗ vì
    migration KHÔNG import code ứng dụng (mỗi migration phải tự đứng độc lập, đọc
    được và chạy được dù `repo.py` sau này đổi khác)."""
    return ", ".join(f"{tien_to}{c.strip()}" for c in cot.split(","))


def upgrade() -> None:
    # ── projects — anchor, KHÔNG có cha để cascade (chỉ chính nó published) ────
    op.execute(
        f"""
        CREATE VIEW agent_api.projects AS
        SELECT {_COT_DU_AN}
          FROM tenant_data.projects
         WHERE tenant_id = portal.current_tenant()
           AND status = 'published'
        """
    )

    # ── zones — cascade qua projects. HAI vị từ tenant (z VÀ p) — xem header. ──
    op.execute(
        f"""
        CREATE VIEW agent_api.zones AS
        SELECT {_voi_tien_to(_COT_PHAN_KHU, "z.")}
          FROM tenant_data.zones z
          JOIN tenant_data.projects p
            ON p.tenant_id = z.tenant_id AND p.project_code = z.project_code
         WHERE z.tenant_id = portal.current_tenant()
           AND z.status = 'published'
           AND p.tenant_id = portal.current_tenant()
           AND p.status = 'published'
        """
    )

    # ── units — cascade qua projects, cùng hình dạng zones. ────────────────────
    op.execute(
        f"""
        CREATE VIEW agent_api.units AS
        SELECT {_voi_tien_to(_COT_CAN, "u.")}
          FROM tenant_data.units u
          JOIN tenant_data.projects p
            ON p.tenant_id = u.tenant_id AND p.project_code = u.project_code
         WHERE u.tenant_id = portal.current_tenant()
           AND u.status = 'published'
           AND p.tenant_id = portal.current_tenant()
           AND p.status = 'published'
        """
    )

    # ── documents — cascade qua projects; "__ALL__" tự đi qua vì đó LÀ một row
    # projects published (seed Task 5), không cần nhánh SQL riêng (xem header). ─
    op.execute(
        f"""
        CREATE VIEW agent_api.documents AS
        SELECT {_voi_tien_to(_COT_TAI_LIEU, "d.")}
          FROM tenant_data.documents d
          JOIN tenant_data.projects p
            ON p.tenant_id = d.tenant_id AND p.project_code = d.project_code
         WHERE d.tenant_id = portal.current_tenant()
           AND d.status = 'published'
           AND p.tenant_id = portal.current_tenant()
           AND p.status = 'published'
        """
    )

    # ── media — cùng hình dạng documents. ───────────────────────────────────────
    op.execute(
        f"""
        CREATE VIEW agent_api.media AS
        SELECT {_voi_tien_to(_COT_MEDIA, "m.")}
          FROM tenant_data.media m
          JOIN tenant_data.projects p
            ON p.tenant_id = m.tenant_id AND p.project_code = m.project_code
         WHERE m.tenant_id = portal.current_tenant()
           AND m.status = 'published'
           AND p.tenant_id = portal.current_tenant()
           AND p.status = 'published'
        """
    )

    # GRANT tường minh — xem header (ALTER DEFAULT PRIVILEGES của 0005 tự lo phần
    # agent_all; portal_api cần dòng này vì 0005 chỉ GRANT SELECT một lần cho các
    # view tồn tại lúc đó, không phải ALTER DEFAULT PRIVILEGES).
    op.execute(
        "GRANT SELECT ON agent_api.projects, agent_api.zones, agent_api.units, "
        "agent_api.documents, agent_api.media TO agent_all, portal_api"
    )


def downgrade() -> None:
    """Drop 5 view — KHÔNG dựng lại hình dạng cũ (view của `0005`/M4a chết hẳn,
    tham chiếu cột không còn tồn tại từ khi `0400` viết lại schema). Downgrade
    trả `agent_api` về đúng trạng thái "có schema, không view nào" — y hệt lúc
    `0401` (bản stub cũ) vừa chạy xong, trước khi Task 6 dựng view thật.

    Thứ tự KHÔNG quan trọng ở đây: các view này JOIN trực tiếp bảng gốc
    `tenant_data.*`, không view nào SELECT từ view khác, nên không có phụ thuộc
    chéo giữa 5 view. Liệt kê theo thứ tự tạo ngược lại chỉ để dễ đọc.
    """
    op.execute("DROP VIEW IF EXISTS agent_api.media")
    op.execute("DROP VIEW IF EXISTS agent_api.documents")
    op.execute("DROP VIEW IF EXISTS agent_api.units")
    op.execute("DROP VIEW IF EXISTS agent_api.zones")
    op.execute("DROP VIEW IF EXISTS agent_api.projects")
