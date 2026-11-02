"""Đối soát — đánh dấu bản ghi nghi mất tích

Revision ID: 0928_doi_soat
Revises: 0927_cong_nap_ngoai

Thiết kế: `docs/superpowers/specs/2026-08-14-cong-nap-du-lieu-ngoai-design.md` §7.

«Đẩy khi có thay đổi» SẼ trôi dạt — mạng đứt, job bên khách chết, họ deploy, một
exception bị nuốt. Khi một sự kiện rơi, không ai biết; và nó rơi theo hướng nguy
hiểm nhất: căn đã bán vẫn nằm «còn hàng» ở phía mình, agent nói với khách là còn.
Đúng bug `NT2-1408`.

Đối soát là cơ chế DUY NHẤT phát hiện chuyện đó. Migration này chỉ thêm một cột —
phần so sánh nằm ở `modules/ingest/doi_soat.py`.

── VÌ SAO MỘT CỘT TRÊN `ingest_records`, KHÔNG PHẢI HÀNG TRONG `ingest_errors` ──
«Nghi mất tích» là TRẠNG THÁI của một bản ghi, không phải một sự kiện lỗi.
`ingest_errors` trả lời «bản ghi nào bị từ chối và vì sao» — dev bên khách đọc nó
để đi sửa adapter. Nghi mất tích thì không có gì để họ sửa: hoặc họ đã xoá thật
(và mình chỉ cần biết), hoặc một sự kiện `delete` bị rơi (và mình cần điều tra).
Trộn hai thứ vào một bảng làm bảng lỗi đầy những dòng không hành động được.

Cột cũng cho phép **tự gỡ dấu**: bản ghi xuất hiện lại ở bản kê sau thì `NULL` trở
lại, không cần ai dọn tay.

── VÌ SAO KHÔNG TỰ XOÁ ─────────────────────────────────────────────────────
Một sự kiện `delete` bị rơi và một bản ghi khách thật sự xoá trông GIỐNG HỆT NHAU
ở phía mình. Đoán sai theo chiều xoá là mất dữ liệu không lấy lại được; đoán sai
theo chiều giữ lại là một hàng thừa mà ai đó nhìn thấy và xử lý. Hai sai lầm
không cùng hạng.
"""

from alembic import op

revision = "0928_doi_soat"
down_revision = "0927_cong_nap_ngoai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_data.ingest_records ADD COLUMN nghi_mat_tich_tu timestamptz")
    # Index MỘT PHẦN: hàng bị nghi là thiểu số tuyệt đối, và câu duy nhất đọc cột
    # này là «liệt kê hàng đang bị nghi». Index đầy đủ sẽ trả giá cho mọi hàng để
    # phục vụ một truy vấn chạm vài hàng.
    op.execute(
        """
        CREATE INDEX ingest_records_nghi_mat_tich_idx
            ON tenant_data.ingest_records (tenant_id, entity)
         WHERE nghi_mat_tich_tu IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tenant_data.ingest_records_nghi_mat_tich_idx")
    op.execute("ALTER TABLE tenant_data.ingest_records DROP COLUMN IF EXISTS nghi_mat_tich_tu")
