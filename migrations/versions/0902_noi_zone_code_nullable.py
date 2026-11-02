"""tenant_data.units.zone_code — nới NOT NULL

VẤN ĐỀ NÓ GIẢI: DB dùng chung với team agent (`docs/contracts/danh-gia-dung-chung-db.md`)
có 3015/3015 hàng `units` với `zone_code IS NULL`, và bảng `zones` RỖNG. Với
`zone_code text NOT NULL`, số hàng nạp được là **0**. Đây không phải dữ liệu bẩn: phân khu
là một tầng phân loại mà nguồn của họ không có, không phải một trường họ quên điền.

VÌ SAO NỚI CHỨ KHÔNG BỊA ZONE: đường kia là sinh một `zones` giả (mỗi project một zone
`__DEFAULT__`) để giữ được NOT NULL. Nó tạo ra 41 hàng không tương ứng với bất cứ gì ngoài
đời, và mọi câu "liệt kê phân khu của dự án" từ đó về sau trả về một phân khu không tồn tại.
Một cột NULL nói đúng sự thật "chưa biết"; một hàng bịa thì nói sai.

VÌ SAO ĐÂY KHÔNG PHẢI PHÁ LỆ: `media.zone_code` (cùng migration 0400, dòng 205) ĐÃ nullable
với ĐÚNG cùng FK tổ hợp `(tenant_id, project_code, zone_code)`. Nên hình dạng này đã có tiền
lệ trong chính schema, không phải một ngoại lệ mới cho một lần nhập dữ liệu.

FK KHÔNG YẾU ĐI. Postgres mặc định MATCH SIMPLE: FK tổ hợp chỉ được kiểm khi MỌI cột của nó
non-NULL. Nên `(t, P1, NULL)` đi qua, còn `(t, P1, 'ZONE_BIA')` vẫn bị từ chối như trước.
Cổng `test_fk_zone_van_chan_zone_code_bia` canh đúng nửa sau đó — nếu không có nó thì
"nới NOT NULL" và "bỏ FK" trông giống nhau trong mắt người đọc sau.

Không ảnh hưởng `agent_api.units`: view đó JOIN `projects`, KHÔNG JOIN `zones` (0401), nên
hàng thiếu zone_code vẫn đến được agent.

Revision ID: 0902_zone_nullable
Revises: 0901_role_chung
"""

from alembic import op

revision = "0902_zone_nullable"
down_revision = "0901_role_chung"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.units ALTER COLUMN zone_code DROP NOT NULL")


def downgrade() -> None:
    # KHÔNG tự xoá/sửa hàng để đặt lại được NOT NULL. Nếu đã có hàng zone_code NULL thì
    # câu này VỠ, và vỡ là đúng: quay lui một lần nới ràng buộc nghĩa là dữ liệu đang có
    # không còn hợp lệ, và chỉ người vận hành mới quyết được nên xoá hàng nào.
    op.execute("ALTER TABLE tenant_data.units ALTER COLUMN zone_code SET NOT NULL")
