"""Hợp nhất hai head 0937 — lần thứ sáu, đúng kịch bản đã ghi ở `0920`

TRIỆU CHỨNG (job `migrate` của pipeline deploy, ảnh dựng từ `4db173f1`):

    FAILED: Multiple head revisions are present for given argument 'head';
    please specify a specific target revision, '<branchname>@head' …

    $ alembic heads
    0108_dang_nhap_google (head)
    0937_documents_body_auto (head)

VÌ SAO CÓ HAI HEAD: `4db173f1` là `Merge branch 'dungnd' into 'develop'`. Cả hai
nhánh cùng rẽ từ mergepoint `0935_hop_nhat_hai_head`, mỗi bên viết tiếp một dãy
riêng; tên tệp khác nhau nên git merge sạch, chỉ alembic thấy:

    0935_hop_nhat_hai_head
    ├── 0108_dang_nhap_google                              (đăng nhập Google)
    └── 0936_media_caption_auto → 0937_documents_body_auto  (mô tả tự sinh)

⚠️ Đánh số KHÔNG nói lên thứ tự thời gian ở đây: `0108` là số của dãy
control-plane (`0100_users` …), viết SAU `0935`, không phải trước. Đừng đọc
`0108 < 0937` thành "cũ hơn" — cả hai đều rẽ từ `0935`.

HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA — lý do đầy đủ ở docstring `0920`: đổi cha của
một nhánh làm alembic coi tổ tiên mới là đã áp trên DB thật ra chưa từng chạy
qua nó.

HAI NHÁNH ĐỘC LẬP THẬT (đã đối chiếu DDL từng tệp, không suy từ tên):

- nhánh này (`0108`) tạo `control.identities` (+ index `identities_user_id_idx`)
  và đổi CHECK trên `control.users`: bỏ `users_password_theo_lifecycle_check`,
  thêm `users_co_duong_dang_nhap_check`;
- nhánh kia (`0936`, `0937`) chỉ thêm hai cột `text NOT NULL DEFAULT ''`:
  `tenant_data.media.caption_auto` và `tenant_data.documents.body_auto`.

Khác schema hoàn toàn (`control` vs `tenant_data`), không một đối tượng nào
xuất hiện ở cả hai bên. Thứ tự áp nào cũng ra cùng một lược đồ.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có.

Revision ID: 0938_hop_nhat_hai_head
Revises: 0108_dang_nhap_google, 0937_documents_body_auto
"""

revision = "0938_hop_nhat_hai_head"
down_revision = ("0108_dang_nhap_google", "0937_documents_body_auto")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
