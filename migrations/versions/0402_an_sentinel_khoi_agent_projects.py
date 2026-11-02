"""agent_api.projects — loại sentinel `__ALL__` khỏi danh sách dự án của agent

VẤN ĐỀ (review vòng cuối, Important C): `0401_agent_doc_kb.py` cho
`agent_api.projects` lọc DUY NHẤT `status = 'published'`, nên row hệ thống
`__ALL__` (`02 §2`/`02a §4b` — điểm neo FK cho tài liệu/media cấp tenant, seed
`published` bởi `scripts/seed_bds.py`) NẰM TRONG đó như một dự án bình thường.
Kiểm trên DB dev: ba dự án "published mà thiếu dữ liệu" duy nhất chính là ba row
`__ALL__` của ba tenant (rỗng cả `region` lẫn `overview`). Hệ quả thực tế: agent
liệt kê dự án sẽ chào khách một dự án tên *"Chung / toàn tenant"*. Nó cũng phá
`02 §7` theo chữ — *"agent chỉ thấy bản published **+ đủ dữ liệu**"* — vì
`__ALL__` không bao giờ đủ dữ liệu và không bao giờ nên đủ (nó không phải dự án).

SỬA: thêm ĐÚNG một vị từ `AND project_code <> '__ALL__'` vào `agent_api.projects`.

BỐN VIEW CON KHÔNG ĐỔI — đây là phần dễ sửa sai nhất, nên viết rõ:
  - `zones`/`units`: `__ALL__` KHÔNG có zone/unit con nào (`02a §4b`), nên vị từ
    thêm vào đó không lọc được gì — chỉ là một dòng SQL chết.
  - `documents`/`media`: hai view này **PHẢI** tiếp tục JOIN QUA `__ALL__`. Đó
    chính là cơ chế đưa tài liệu/media dùng chung toàn tenant tới agent (`02 §2`,
    và `repo.liet_ke_tai_lieu_cho_agent` làm y hệt ở đường đọc CMS). Thêm
    `p.project_code <> '__ALL__'` vào chúng sẽ XOÁ tài liệu chung khỏi mọi câu
    trả lời của agent — đúng thiệt hại mà Critical A của cùng vòng review này
    đang chặn ở tầng HTTP.
Nói cách khác: `__ALL__` phải TỒN TẠI và `published` cho cascade của con, nhưng
KHÔNG được xuất hiện như một dự án. Hai điều đó chỉ tách được ở view `projects`.

VÌ SAO MIGRATION MỚI, KHÔNG SỬA `0401`: `0401` ĐÃ ÁP lên DB dev (và DB của
session M2a chạy song song có thể đã stamp) — sửa nội dung một migration đã chạy
là một thay đổi KHÔNG BAO GIỜ được áp lại ở đâu cả, chỉ tạo lệch giữa file và DB.

VÌ SAO `down_revision = "0102_organizations"`, KHÔNG PHẢI `"0401_agent_api_bds"`:
`0102_organizations.py` (session M2a) đã nhận `0401_agent_api_bds` làm cha, nên
`0401` KHÔNG còn là head. Nối 0402 vào `0401` sẽ tạo NHÁNH THỨ HAI và `alembic
upgrade head` chết ngay với "Multiple head revisions" cho MỌI người, kể cả
session kia. Nối vào head thật (`0102_organizations`) giữ chuỗi thẳng. File
`0102_organizations.py` KHÔNG bị đụng vào ở đây — chỉ được trỏ TỚI.

`CREATE OR REPLACE VIEW` (không `DROP` + `CREATE`): danh sách cột không đổi nên
REPLACE hợp lệ, và nó GIỮ NGUYÊN quyền đã cấp — `DROP VIEW` sẽ mất `GRANT SELECT
... TO agent_all, portal_api` mà `0401` cấp và biến cả hai đường đọc thành
"permission denied" cho tới lần grant sau.

Revision ID: 0402_an_sentinel
Revises: 0102_organizations
"""

from alembic import op

revision = "0402_an_sentinel"
down_revision = "0102_organizations"
branch_labels = None
depends_on = None

# Sao y `_COT_DU_AN` của `0401_agent_doc_kb.py` (bản thân nó khớp
# `repo._COT_RA["project"]` trừ `tenant_id`). CREATE OR REPLACE VIEW đòi danh
# sách cột Y HỆT view đang tồn tại — lệch một cột là lỗi ngay lúc migrate, không
# phải âm thầm; và `tests/modules/realestate/test_agent_doc_duoc.py::
# test_view_agent_khop_cot_repo` (thêm ở cùng vòng review này) canh việc danh
# sách này không lệch khỏi `repo._COT_RA`.
_COT_DU_AN = (
    "id, project_code, name, category, region, address, investor, developer, "
    "total_land_area_m2, floor_area_m2, build_density_pct, product_scale, amenities, "
    "ownership_form, handover_standard, total_investment_vnd, sale_phase, overview, "
    "link_360, cover_media_id, map_media_id, status, created_at, updated_at"
)

# Chuỗi sentinel viết CỨNG, không import `contracts.SENTINEL_TENANT`: migration
# phải tự đứng độc lập (cùng lý do `0401` tự viết lại `_voi_tien_to`) — nó là
# một bản ghi lịch sử chạy được dù code ứng dụng sau này đổi khác.
_SENTINEL = "__ALL__"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW agent_api.projects AS
        SELECT {_COT_DU_AN}
          FROM tenant_data.projects
         WHERE tenant_id = portal.current_tenant()
           AND status = 'published'
           AND project_code <> '{_SENTINEL}'
        """
    )


def downgrade() -> None:
    """Trả `agent_api.projects` về đúng định nghĩa của `0401` (có sentinel)."""
    op.execute(
        f"""
        CREATE OR REPLACE VIEW agent_api.projects AS
        SELECT {_COT_DU_AN}
          FROM tenant_data.projects
         WHERE tenant_id = portal.current_tenant()
           AND status = 'published'
        """
    )
