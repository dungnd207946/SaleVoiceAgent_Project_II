"""Mốc nhận bản kê đối soát — nhịp tim của adapter bên khách

Revision ID: 0929_ban_ke_lan_cuoi
Revises: 0928_doi_soat

Thiết kế: `docs/superpowers/specs/2026-08-14-cong-nap-du-lieu-ngoai-design.md` §7.5.

── VÌ SAO CẦN BẢNG NÀY ─────────────────────────────────────────────────────
Đối soát (§7) là thứ DUY NHẤT bắt được một sự kiện `delete` bị rơi. Nhưng bản kê
do BÊN KHÁCH gửi lên — mình đứng chờ, không gọi sang. Nên khi job của họ ngừng
chạy (server đổi, cron bị xoá, credential hết hạn), phía mình **không có gì xảy
ra cả**: không lỗi, không request thất bại, không dòng nhật ký.

Và im lặng đó trông y hệt lúc mọi thứ chạy tốt.

Đó là chế độ hỏng tệ hơn «chưa có đối soát»: không có thì ai cũng biết là không
có; có mà chết âm thầm thì người vận hành TIN là đang được bảo vệ. Cơ chế dựng ra
để chống hỏng-im-lặng, mà bản thân nó hỏng đúng theo kiểu đó.

── VÌ SAO KHÔNG DÙNG LẠI DẤU VẾT SẴN CÓ ────────────────────────────────────
Đo trước khi dựng bảng, cả ba đều không trả lời được câu hỏi:

  · `nhat_ky` chỉ ghi khi có cờ nghi-mất-tích MỚI (cố ý — ghi mỗi đêm là dạy
    người trực bỏ qua chính dòng đó). Nên một lượt đối soát KHỚP HOÀN TOÀN để lại
    đúng KHÔNG GÌ, và «khách chạy mỗi đêm, luôn khớp» trông giống hệt «khách
    ngừng chạy ba tuần trước».
  · `ingest_records.received_at` nói về `/events`, không về bản kê.
  · `ingest_tokens.last_used_at` chưa bao giờ được ghi (`repo.cham_da_dung` là
    code chết) — và kể cả có, nó gộp cả hai đường, không tách được.

── VÌ SAO BẢN KÊ LÀ NHỊP TIM, CÒN `/events` THÌ KHÔNG ──────────────────────
Hai loại im lặng khác hẳn nhau:

  · **Không có `/events`** — MƠ HỒ. Tuần này khách có thể không sửa dự án nào.
  · **Không có bản kê** — KHÔNG mơ hồ. Bản kê gửi BẤT KỂ có thay đổi hay không;
    đó là bản chất của nó. Vắng mặt là bằng chứng job chết.

Nên mỗi lượt đối soát vốn ĐÃ LÀ một nhịp tim — bảng này chỉ ghi lại rằng nó đập,
không dựng thêm cơ chế heartbeat nào.

── VÌ SAO `tenant_data` CHỨ KHÔNG `control` ────────────────────────────────
Đã cân nhắc `control` (một câu quét mọi tenant, cùng hạng `agent_heartbeats`) và
BỎ: job quét chạy theo khuôn `kb/ops/fanout_tenant.py` — một job MỖI tenant, mỗi
job trong `tenant_conn()`, nên cách ly do RLS gánh chứ không do người viết nhớ.
Cảnh báo cũng vào `audit_log` của chính tenant đó, không cần bảng trung gian nào.
"""

from alembic import op

revision = "0929_ban_ke_lan_cuoi"
down_revision = "0928_doi_soat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_data.ingest_manifest_runs (
            tenant_id   text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            -- THEO THỰC THỂ, không chỉ theo tenant: khách có thể đối soát `project`
            -- mà quên `unit`, và đó cũng là một kiểu chết một nửa. Cảnh báo hiện
            -- tại chỉ đọc mốc MỚI NHẤT (xem `jobs.py`), nhưng dữ liệu để phân biệt
            -- thì có sẵn từ đầu — thêm cột sau vào một bảng đã chạy thì mọi hàng cũ
            -- mang NULL và không ai biết NULL đó nghĩa là gì.
            entity      text NOT NULL CONSTRAINT ingest_manifest_runs_entity_hop_le
                        CHECK (entity IN ('project', 'zone', 'unit', 'document', 'media')),
            -- Lúc MÌNH NHẬN, không phải lúc khách gửi. Đây là câu hỏi «adapter của
            -- họ còn sống không», và giờ trên máy họ thì không trả lời được câu đó
            -- — đồng hồ lệch hay múi giờ sai sẽ thành một tenant im lặng giả.
            nhan_luc    timestamptz NOT NULL DEFAULT now(),
            so_muc      integer NOT NULL DEFAULT 0,
            CONSTRAINT ingest_manifest_runs_pk PRIMARY KEY (tenant_id, entity)
        )
        """
    )
    op.execute("SELECT control.enforce_tenant_isolation('tenant_data.ingest_manifest_runs')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_data.ingest_manifest_runs")
