"""Sinh hàng `media` tour_360 cho mọi dự án đã có `link_360`

`0929` mở CHECK cho `content_type='tour_360'` và `sync_tour_360` biết dựng hàng, nhưng chỉ
HAI route giao diện (tạo/sửa dự án) gọi nó. Dữ liệu thật về bằng cổng nạp API — đường đó ghi
`link_360` thẳng vào bảng `projects` (`ingest/hop_dong.py`: `link360` → `link_360`) và không
gọi sync. Đo trên dev 2026-08-17: **25 dự án có `link_360`, KHÔNG tenant nào có một hàng
`media` tour_360 nào** ⇒ khách hỏi tour 360 thì `send_media` không tìm ra gì (D16 coi như
chưa chạy). Nửa code đã vá ở `ingest/chieu.py`; đây là nửa dữ liệu.

Idempotent: chỉ chèn cho dự án CHƯA có hàng tour. Chạy lại không sinh bản trùng.

`status='published'` cứng, đúng như `sync_tour_360` — không phải sao chép trạng thái dự án:
cờ hiệu lực trong payload Qdrant do tầng nạp suy ra từ trạng thái CHA, nên một dự án nháp
vẫn ra point `draft` dù hàng media ghi published.

Revision ID: 0934_tour_360_tu_link
Revises: 0933_nap_lai_project_code
"""

from alembic import op

revision = "0934_tour_360_tu_link"
down_revision = "0933_nap_lai_project_code"
branch_labels = None
depends_on = None

_BANG = ("tenant_data.projects", "tenant_data.media")


def _force_rls(bat: bool) -> None:
    for bang in _BANG:
        op.execute(f"ALTER TABLE {bang} {'FORCE' if bat else 'NO FORCE'} ROW LEVEL SECURITY")


def upgrade() -> None:
    _force_rls(False)
    op.execute(
        """
        INSERT INTO tenant_data.media
               (tenant_id, project_code, content_type, category, caption, media_url, public_url, status)
        SELECT p.tenant_id,
               p.project_code,
               'tour_360',
               'tong_quan',
               'Tour tham quan thực tế ảo 360 độ — ' || p.name,
               p.link_360,
               p.link_360,
               'published'
          FROM tenant_data.projects p
         WHERE coalesce(p.link_360, '') <> ''
           AND NOT EXISTS (
               SELECT 1 FROM tenant_data.media m
                WHERE m.tenant_id = p.tenant_id
                  AND m.project_code = p.project_code
                  AND m.content_type = 'tour_360'
           )
        """
    )
    # Xếp việc nạp cho từng hàng vừa sinh: không có nó thì tour chỉ tới Qdrant khi có người
    # bấm đồng bộ cả dự án. `public_url` = link nguyên văn vì `public_url_of` cho đi thẳng
    # mọi giá trị đã là http(s) — link kuula không phải khoá kho.
    op.execute(
        """
        INSERT INTO control.jobs (tenant_id, kind, actor, payload)
        SELECT m.tenant_id,
               'kb_index',
               'migration:0934',
               jsonb_build_object(
                   'vertical', 'real_estate',
                   'entity', 'media',
                   'record_id', m.id,
                   'project_code', m.project_code,
                   'doc_type', '',
                   'op', 'upsert',
                   'mode', 'full'
               )
          FROM tenant_data.media m
         WHERE m.content_type = 'tour_360'
        """
    )
    _force_rls(True)


def downgrade() -> None:
    op.execute("DELETE FROM control.jobs WHERE actor = 'migration:0934' AND state = 'queued'")
    _force_rls(False)
    op.execute("DELETE FROM tenant_data.media WHERE content_type = 'tour_360'")
    _force_rls(True)
