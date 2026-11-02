"""Hợp nhất hai head 0931 — lần thứ tư, đúng kịch bản đã ghi ở `0920`

TRIỆU CHỨNG (sau khi merge develop vào `feat/tai-cau-truc-loi-ingest`):

    $ alembic heads
    0930_nap_lai_tai_lieu_chua_boc
    0931_cho_cha

VÌ SAO CÓ HAI HEAD: nhánh kb-tab viết `0927_tu_dong_nap_kien_thuc` →
`0928_thumb_tai_lieu` → `0929_media_tour_360` → `0930_nap_lai_tai_lieu_chua_boc`
trên một checkout CHƯA có chuỗi cổng nạp (`0927_cong_nap_ngoai` →
`0928_doi_soat` → `0929_ban_ke_lan_cuoi` → `0930_bo_last_used_at` →
`0931_cho_cha`) — cả hai chuỗi cùng nhận `0926_escalation_notes` làm gốc, tên
tệp khác nhau nên git merge sạch, chỉ alembic thấy:

    0926_escalation_notes
    ├── 0927_cong_nap_ngoai … 0931_cho_cha            (cổng nạp dữ liệu ngoài)
    └── 0927_tu_dong_nap_kien_thuc … 0930_nap_lai_…   (kb-tab: tự động nạp KB)

⚠️ Ở thời điểm viết, CHÍNH develop cũng đang hai head (`0930_bo_last_used_at` +
`0930_nap_lai_tai_lieu_chua_boc` — merge `feat/canh-bao-tenant-im-lang` rồi merge
kb-tab, không ai chạy `test_alembic_mot_head` giữa hai lần): node này về tới
develop là lành cho cả develop.

HỢP NHẤT CHỨ KHÔNG NỐI LẠI CHA — lý do đầy đủ ở docstring `0920`: đổi cha của
một nhánh làm alembic coi tổ tiên mới là đã áp trên DB thật ra chưa từng chạy
qua nó.

HAI NHÁNH ĐỘC LẬP THẬT: cổng nạp đụng `ingest_*` + cột `external_id` trên 5 bảng
KB; kb-tab đụng `kb_index_state`/thumb/tour_360/CHECK `media.content_type`.
Đối tượng DUY NHẤT cả hai cùng chạm là bảng `tenant_data.media` — một bên thêm
cột `external_id` (0927_cong_nap), một bên đổi CHECK `content_type` (0929_media_
tour_360): hai ALTER trực giao, thứ tự áp nào cũng ra cùng lược đồ.

KHÔNG CÓ DDL. Thân hàm rỗng là chủ ý — thêm bất cứ gì vào đây là giấu một thay
đổi lược đồ trong một tệp mà tên nó nói rằng không có.

Revision ID: 0932_hop_nhat_hai_head
Revises: 0931_cho_cha, 0930_nap_lai_tai_lieu_chua_boc
"""

revision = "0932_hop_nhat_hai_head"
down_revision = ("0931_cho_cha", "0930_nap_lai_tai_lieu_chua_boc")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Không làm gì — xem docstring."""


def downgrade() -> None:
    """Không làm gì. Lùi qua đây tách lại thành hai nhánh, đúng như trước."""
