"""Backfill `control.tenant_verticals` — bật `realestate` cho tenant tạo trước 2026-08-15

VÌ SAO BẮT BUỘC, KHÔNG PHẢI PHÒNG HỜ: `workspace/repo.them_vertical` mới chạy
từ 2026-08-15 (đường tạo workspace); tenant tạo trước đó (anphu, sunrise…)
KHÔNG có hàng nào. Module `linh_vuc` (cùng đợt commit này) đọc «bật = có
hàng» — thiếu backfill thì ship xong, `GET /linh-vuc` trả `bat=false` cho bds
và khối Bất động sản BIẾN KHỎI NAV của mọi workspace cũ ngay lập tức (FE
`useNavGroups` lọc khối theo công tắc).

Bật mặc định `realestate` đúng với hành vi mọi tenant đang thấy: tất cả đều
là tenant BĐS (`VERTICAL_MAC_DINH = 'realestate'` ở workspace/service,
`ConfigPayload.pham_vi.linh_vuc = Literal["realestate"]`), và fake MSW của FE
cũng seed `bds.bat = true`.

Literal `'realestate'` viết THẲNG — migration đóng băng theo thời điểm,
KHÔNG import `portal.*` (đọc sổ hiện hành nghĩa là migration cũ đổi nghĩa
mỗi lần sổ đổi).

Idempotent (`ON CONFLICT DO NOTHING`): chạy lại trên DB đã backfill hoặc
tenant đã có hàng từ `them_vertical` đều là no-op.
"""

from alembic import op

revision = "0944_backfill_tenant_verticals"
down_revision = "0943_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO control.tenant_verticals (tenant_id, vertical)
        SELECT id, 'realestate' FROM control.tenants
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # No-op CÓ CHỦ Ý: không phân biệt được hàng backfill với hàng
    # `them_vertical` ghi thật lúc tạo workspace — xoá là tắt nhầm lĩnh vực
    # người ta đang bật. Chiều xuống chấp nhận giữ hàng.
    pass
