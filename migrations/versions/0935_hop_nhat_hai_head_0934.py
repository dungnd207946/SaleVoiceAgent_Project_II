"""Hợp nhất hai head 0934 — lần thứ năm, đúng kịch bản đã ghi ở `0920`

TRIỆU CHỨNG (sau khi merge `develop` vào nhánh `dungnd`):

    $ alembic heads
    0107_invites_tenant_id
    0934_tour_360_tu_link

VÌ SAO CÓ HAI HEAD: nhánh `dungnd` viết `0105_roles_thoat_org` →
`0106_bo_organizations` → `0107_invites_tenant_id` (bỏ tầng tổ chức, rồi đăng ký
tự phục vụ) trên một checkout CHƯA có chuỗi cổng nạp / kb-tab của develop
(`0927_cong_nap_ngoai` … `0934_tour_360_tu_link`, đã gồm mergepoint `0932`) —
cả hai chuỗi cùng nhận `0926_escalation_notes` làm gốc, tên tệp khác nhau nên
git merge sạch, chỉ alembic thấy:

    0926_escalation_notes
    ├── 0105_roles_thoat_org … 0107_invites_tenant_id   (bỏ tổ chức + đăng ký)
    └── 0927_cong_nap_ngoai  … 0934_tour_360_tu_link    (cổng nạp + kb-tab)

⚠️ Đánh số KHÔNG nói lên thứ tự thời gian ở đây: `0105`–`0107` là số của dãy
control-plane (`0100_users` …), viết SAU `0926`, không phải trước. Đừng đọc
`0107 < 0934` thành "cũ hơn" — cả hai đều rẽ từ `0926`.

HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA — lý do đầy đủ ở docstring `0920`: đổi cha của
một nhánh làm alembic coi tổ tiên mới là đã áp trên DB thật ra chưa từng chạy
qua nó.

HAI NHÁNH ĐỘC LẬP THẬT (đã đối chiếu DDL từng tệp, không suy từ tên):

- nhánh này đụng `control.{users,memberships,roles,invites,organizations}` và
  hai cột của `control.tenants` (`org_id` bỏ, `created_by` thêm) + `audit_log`
  (`org_id` + CHECK `audit_log_co_pham_vi_check`);
- nhánh kia đụng `control.{ingest_tokens,agent_keys,jobs}` và `tenant_data.*`
  (`ingest_*`, `kb_index_state`, thumb/tour_360, cột `external_id` trên 5 bảng KB).

Hai đối tượng cùng tên xuất hiện ở cả hai bên nhưng KHÔNG chồng chéo: nhánh kia
chỉ dùng `control.tenants(id)` làm ĐÍCH khoá ngoại (`REFERENCES … ON DELETE
CASCADE`) — cột `id` thì nhánh này không chạm, nó chỉ bỏ `org_id`/`tenants_org_idx`
/`tenants_org_id_key` và thêm `created_by`; còn `control.audit_log` bên kia chỉ
nằm trong một docstring (`0930`), không có DDL nào. Thứ tự áp nào cũng ra cùng
một lược đồ.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có.

Revision ID: 0935_hop_nhat_hai_head
Revises: 0107_invites_tenant_id, 0934_tour_360_tu_link
"""

revision = "0935_hop_nhat_hai_head"
down_revision = ("0107_invites_tenant_id", "0934_tour_360_tu_link")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
