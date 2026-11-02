"""Bỏ `control.ingest_tokens.last_used_at` — cột chưa bao giờ được ghi

Revision ID: 0930_bo_last_used_at
Revises: 0929_ban_ke_lan_cuoi

Thiết kế: `docs/.../2026-08-14-cong-nap-du-lieu-ngoai-design.md` §8 mục 5.

── VÌ SAO BỎ CHỨ KHÔNG GHI ─────────────────────────────────────────────────
`repo.cham_da_dung()` tồn tại từ `0927` nhưng KHÔNG NƠI NÀO GỌI, nên cột luôn
`NULL`. Ai mở bảng ra sẽ đọc `NULL` thành «token này chưa ai dùng» — một kết luận
sai, và sai theo hướng nguy hiểm: nó mời người ta xoá một token đang chạy.

Hai đường ra, và đường «ghi nó» đã bị loại vì cả hai vế đều không đứng được:

  · **Giá:** `xac_thuc()` chạy trước MỌI request nạp. Ghi ở đó biến một bảng
    đọc-nhiều thành ghi-nhiều. Có cách rẻ (chỉ ghi ở request đầu mỗi cửa sổ nhịp,
    tận dụng bộ đếm Redis đã có) nên giá KHÔNG phải lý do quyết định.
  · **Không ai đọc:** đây mới là lý do. `TokenOut` có đúng BA trường
    (`id`·`label`·`token`) — người dùng chốt 2026-08-14 sau NĂM vòng cắt, và cắt
    đúng «Dùng cuối» kèm lý do: câu hỏi đó đã được «Nhận cuối» ở khối Endpoint trả
    lời cho cả workspace. Một cột được ghi trung thực mà không giao diện nào bày
    ra vẫn là cùng một lời nói dối, chỉ đổi chiều.

Luật của `TokenOut` nói thẳng: *siêu dữ liệu kiểm toán là việc của Nhật ký, không
phải của bảng này.* Migration này làm cho câu đó thành thật.

⚠️ **CÙNG COMMIT** với việc `service.tao_token`/`xoa_token` bắt đầu ghi
`control.audit_log` (`ingest.token_tao` · `ingest.token_xoa`). Trước đó docstring
của `TokenOut` VÀ của `router_tenant.xoa_token` đều viện dẫn Nhật ký, mà Nhật ký
chưa từng có một dòng nào cho module này — tức lời hứa thứ hai cũng rỗng. Bỏ cột
mà không trả lời hứa đó là xoá dấu vết duy nhất còn lại, kể cả khi nó luôn NULL.

── KHÔNG PHỤC HỒI ĐƯỢC ─────────────────────────────────────────────────────
`downgrade()` dựng lại cột, nhưng mọi hàng sẽ mang `NULL` — đúng bằng thứ chúng
đang mang hôm nay. Không mất dữ liệu nào vì chưa từng có dữ liệu nào.
"""

from alembic import op

revision = "0930_bo_last_used_at"
down_revision = "0929_ban_ke_lan_cuoi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.ingest_tokens DROP COLUMN last_used_at")


def downgrade() -> None:
    op.execute("ALTER TABLE control.ingest_tokens ADD COLUMN last_used_at timestamptz")
