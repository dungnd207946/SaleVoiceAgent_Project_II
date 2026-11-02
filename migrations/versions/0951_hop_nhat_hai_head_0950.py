"""Hợp nhất hai head 0950 / 0944 — lần thứ tám, đúng kịch bản đã ghi ở `0920`

SINH RA TỪ ĐÂU: merge `develop` vào nhánh `usage` (2026-08-21). Hai dãy cùng rẽ
từ mergepoint `0943_hop_nhat_hai_head`, tên tệp khác nhau nên git merge sạch —
chỉ `alembic heads` thấy:

    0943_hop_nhat_hai_head
    ├── 0944_backfill_tenant_verticals            (develop — màn «Quản lý lĩnh vực»)
    └── 0943_billing_pricing → 0944_usage_events_portal_api → 0945_billing_action
        → 0946_conversations_agent_key_fk → 0947_billing_preview
        → 0948_billing_text_units → 0949_seed_bang_gia_mac_dinh
        → 0950_dinh_gia_ngay_khi_insert           (nhánh `usage` — module billing)

⚠️ Đánh số KHÔNG nói lên nhánh: có HAI tệp mang số `0944` và chúng thuộc hai
nhánh khác nhau. Đừng đọc `0944 < 0950` thành "cùng một dãy".

HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA (luật `0920`, cũng đã ghi ở CLAUDE.md mục
Migration): đổi `down_revision` của một nhánh làm alembic coi tổ tiên mới là đã
áp trên DB thật ra chưa từng chạy qua nó, và không lệnh nào báo. Cả hai dãy đây
đều đã ở trên remote nên không nhánh nào được hưởng ngoại lệ "chưa từng push".

HAI NHÁNH ĐỘC LẬP THẬT — đã đối chiếu DDL từng tệp, không suy từ tên:

- `0944_backfill_tenant_verticals` làm ĐÚNG MỘT việc: `INSERT … ON CONFLICT DO
  NOTHING` vào `control.tenant_verticals` (bảng do `0002_control_core` tạo, tổ
  tiên chung của cả hai nhánh). Không tạo/xoá/đổi đối tượng nào.
- dãy billing chạm schema `billing` (`metric` · `price_version` · `price_item` ·
  `rated_usage` · `invoice`/`invoice_line` · 5 view · các function
  `resolve_price_version`/`rate_usage`/`dinh_gia_events` + trigger
  `dinh_gia_sau_insert`), cộng `control.actions`/`role_actions`/`roles`
  (`billing.read`), `control.agent_keys` và `tenant_data.conversations`.

Giao của hai tập đối tượng là RỖNG: `control.tenant_verticals` không xuất hiện ở
bất kỳ tệp nào của dãy billing, và `0944_backfill_tenant_verticals` không nhắc
`billing`/`agent_keys`/`conversations`. Thứ tự áp nào cũng ra cùng một lược đồ.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có.

Revision ID: 0951_hop_nhat_hai_head
Revises: 0950_dinh_gia_ngay_khi_insert, 0944_backfill_tenant_verticals
"""

revision = "0951_hop_nhat_hai_head"
down_revision = ("0950_dinh_gia_ngay_khi_insert", "0944_backfill_tenant_verticals")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
