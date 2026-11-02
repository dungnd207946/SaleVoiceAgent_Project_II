"""csbh thành danh mục media thứ 8

`0400_kb_real_estate` khai 7 giá trị. DB dev đo 2026-08-11 đã có 8 — ai đó ALTER
tay, không qua alembic, nên hai môi trường có hai CHECK khác nhau mà không lệnh
nào báo. Migration này đưa cả hai về cùng một định nghĩa.

DROP ... IF EXISTS rồi ADD, không phải ALTER: constraint có thể đang là bản 7 giá
trị (DB dựng từ migration) hoặc bản 8 (DB dev đã sửa tay), và chỉ một câu chịu
được cả hai.

`csbh` = chính sách bán hàng, cùng nghĩa với `LOAI_TAI_LIEU.csbh` ở tài liệu. Ở
nguồn nạp về nó là danh mục lớn thứ ba (34 ảnh), lâu nay rơi hết vì API từ chối.

DOWNGRADE NỔ NẾU CÒN HÀNG `csbh` — cố ý. Hạ về 7 giá trị mà lặng lẽ xoá 34 hàng
ảnh là mất dữ liệu không dấu vết; để Postgres từ chối và người vận hành tự quyết.
"""

from alembic import op

revision = "0918_media_category_csbh"
down_revision = "0917_bo_agent_api"
branch_labels = None
depends_on = None

_BAY = "'tong_quan', 'ngoai_that', 'noi_that', 'tien_ich', 'mat_bang', 'vi_tri', 'tien_do'"
_TAM = f"{_BAY}, 'csbh'"


def _dat_check(gia_tri: str) -> None:
    op.execute("ALTER TABLE tenant_data.media DROP CONSTRAINT IF EXISTS media_category_hop_le")
    op.execute(f"ALTER TABLE tenant_data.media ADD CONSTRAINT media_category_hop_le CHECK (category IN ({gia_tri}))")


def upgrade() -> None:
    _dat_check(_TAM)


def downgrade() -> None:
    _dat_check(_BAY)
