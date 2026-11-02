"""Xếp việc bóc chữ cho tài liệu đã có tệp mà chưa có nội dung

`0927` chuyển 34 ảnh `csbh` từ bảng `media` sang `documents`, mang theo khoá ảnh trong
`file_url` nhưng `body` rỗng — chúng chưa từng đi qua chặng bóc chữ nào (lúc đó chặng đó
cũng chưa nhận ảnh; `clients/extract.py` vừa thêm nhánh OCR cho ảnh).

Nên chúng vẫn chưa có đường nào tới agent. Xếp một việc `kb_thumb` cho mỗi hàng như vậy:
việc đó tự nối sang bóc chữ rồi sang nạp, nên một dòng INSERT ở đây khởi động cả chuỗi.

Diện rộng hơn 34 hàng csbh có chủ ý — mọi tài liệu "có tệp mà không có chữ" đều là một
mục người dùng tưởng đã tới agent. Không có hàng nào khớp thì câu này không làm gì.

Vế SELECT đọc `tenant_data.documents` nên phải tắt `FORCE ROW LEVEL SECURITY` quanh nó
(luật ở header `0003`). Bỏ qua thì câu này xếp 0 việc và KHÔNG báo gì — hỏng im lặng, tệ
hơn ca `0927` vì ở đó ít nhất còn một CHECK nổ ra.
"""

from alembic import op

revision = "0930_nap_lai_tai_lieu_chua_boc"
down_revision = "0929_media_tour_360"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.documents NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        INSERT INTO control.jobs (tenant_id, kind, actor, payload)
        SELECT d.tenant_id,
               'kb_thumb',
               'migration:0930',
               jsonb_build_object(
                   'vertical', 'real_estate',
                   'entity', 'documents',
                   'record_id', d.id,
                   'project_code', d.project_code,
                   'ghi_de', false,
                   'tu_duyet', false
               )
          FROM tenant_data.documents d
         WHERE coalesce(d.file_url, '') <> ''
           AND coalesce(d.body, '') = ''
        """
    )
    op.execute("ALTER TABLE tenant_data.documents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DELETE FROM control.jobs WHERE actor = 'migration:0930' AND state = 'queued'")
