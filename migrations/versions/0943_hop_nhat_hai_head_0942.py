"""Hợp nhất hai head 0939 / 0942 — lần thứ bảy, đúng kịch bản đã ghi ở `0920`

TRIỆU CHỨNG (job `migrate` của pipeline deploy on-prem, ảnh `9c055b50`):

    FAILED: Multiple head revisions are present for given argument 'head';
    please specify a specific target revision, '<branchname>@head' …

    $ alembic heads
    0939_xoa_role_agent (head)
    0942_billing_usage_events (head)

VÌ SAO CÓ HAI HEAD: hai dãy cùng rẽ từ mergepoint `0938_hop_nhat_hai_head`, tên
tệp khác nhau nên git merge sạch — chỉ alembic thấy:

    0938_hop_nhat_hai_head
    ├── 0939_xoa_role_agent
    └── 0939_conversations_agent_key_id → 0940_agent_keys_tenant
        → 0941_bo_deployments → 0942_billing_usage_events

⚠️ Đánh số KHÔNG nói lên nhánh: có HAI tệp mang số `0939` và chúng thuộc hai
nhánh khác nhau. Đừng đọc `0939 < 0942` thành "cùng một dãy".

HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA. `0939_xoa_role_agent` tự cho mình một ngoại lệ
của luật `0920` (đổi cha thay vì thêm migration hợp nhất) và ghi rõ ĐIỀU KIỆN của
ngoại lệ đó: "migration này **chưa từng được push**". Điều kiện ấy nay đã hết —
nó đang trên `develop`. Nên ở đây áp lại luật gốc, không ngoại lệ: đổi cha của
một nhánh làm alembic coi tổ tiên mới là đã áp trên DB thật ra chưa từng chạy
qua nó, và không lệnh nào báo.

HAI NHÁNH ĐỘC LẬP THẬT — đã đối chiếu DDL từng tệp, không suy từ tên:

- nhánh `0939_xoa_role_agent` tạo ĐÚNG MỘT đối tượng: hàm
  `control.xoa_role_agent()` (SECURITY DEFINER). Không bảng, không index, không
  policy.
- nhánh kia chạm `control.agent_keys` · `control.deployments` (drop) ·
  `control.agent_heartbeats` · `tenant_data.conversations` · schema `billing`
  (`usage_events` + 2 view + 2 policy).

Giao của hai tập đối tượng là RỖNG, và không bên nào tham chiếu tên của bên kia
(`0939_xoa_role_agent` không nhắc `deployments`/`agent_keys`/`conversations`/
`billing`; nhánh kia không nhắc `xoa_role_agent`). Thứ tự áp nào cũng ra cùng
một lược đồ.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có.

Revision ID: 0943_hop_nhat_hai_head
Revises: 0939_xoa_role_agent, 0942_billing_usage_events
"""

revision = "0943_hop_nhat_hai_head"
down_revision = ("0939_xoa_role_agent", "0942_billing_usage_events")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
