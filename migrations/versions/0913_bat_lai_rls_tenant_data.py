"""Bật lại RLS cho tenant_data — lưới thứ hai sau khi 0909 dỡ toàn bộ

VÌ SAO ĐẢO LẠI MỘT QUYẾT ĐỊNH CÓ CHỦ ĐÍCH: `0909_bo_rls_toan_bo` dỡ RLS để một hệ thống
agent bên ngoài đọc được `control` và tự lọc tenant. Docstring của nó tự cảnh báo rằng
việc đó cũng dỡ luôn lưới an toàn của `tenant_data` cho CHÍNH app Portal. Cảnh báo ấy đã
thành sự thật, đo được, không phải giả định:

    Agent phục vụ tenant `anphu` gọi `discover_projects` và nhận về "total": 6.
    anphu có ĐÚNG 2 dự án published. 6 là tổng của cả ba tenant.
    Cùng lúc: units 60 (thật 20), documents 18 (thật 6).

Nguyên nhân không phải "ai đó quên WHERE" như 0909 hình dung. `data/providers/postgres_kb.py`
phía agent CỐ Ý uỷ thác việc lọc cho RLS — docstring của nó ghi thẳng "scoped by tenant_conn
+ the RLS agent_runtime policy" và không câu SQL nào có `WHERE tenant_id`. 0909 rút sàn, code
không đổi một dòng, và không có gì để grep ra.

MIGRATION NÀY KHÔNG PHẢI BẢN VÁ DUY NHẤT, VÀ CỐ Ý NHƯ VẬY. Phía agent đã sửa riêng: mọi câu
SQL nay tự ghim `tenant_id = $n`, không phụ thuộc RLS nữa. Đây là lớp THỨ HAI. Hai lớp độc
lập: agent quên ghim ở một câu mới thì RLS chặn; RLS bị dỡ lần nữa thì SQL vẫn lọc. Một lớp
là một điểm chết.

PHẠM VI HẸP — CHỈ `tenant_data`:
  · KHÔNG đụng `control` (0908 mở SELECT cho PUBLIC — đó là thứ hệ thống agent ngoài cần đọc,
    migration này không lấy lại).
  · KHÔNG bật lại RLS trên `control.agent_heartbeats`. Agent GHI vào đó; bật lại là thêm một
    đường có thể chặn nhịp tim, và không có bằng chứng rò rỉ nào ở bảng ấy. Ai cần thì làm
    riêng, có phép đo riêng.

DÙNG `control.enforce_tenant_isolation()` — chính hàm mà 0909 CỐ Ý giữ lại đúng cho việc này
("cách 'thêm lại RLS cho một bảng' nhanh nhất nếu sau này cần khôi phục"). Hàm tạo policy
`tenant_isolation` USING/WITH CHECK `tenant_id = portal.current_tenant()`.

VÌ SAO MỘT POLICY LÀ ĐỦ cho cả Portal lẫn agent: `portal.current_tenant()` đọc GUC
`app.tenant_id`, và `tenant_conn` của CẢ HAI phía đều set nó (agent set thêm
`app.current_tenant` cho policy `agent_runtime` cũ — không dựng lại policy đó, thừa).

DÒ ĐỘNG THAY VÌ LIỆT KÊ TÊN BẢNG: cùng lý lẽ 0909 — danh sách bảng `tenant_data` đã qua tay
nhiều migration và còn tăng. Liệt kê tay là kiểu danh sách sẽ lệch với DB ngay migration sau.

Revision ID: 0913_bat_lai_rls_tenant_data
Revises: 0912_config_agent
"""

from alembic import op

revision = "0913_bat_lai_rls_tenant_data"
down_revision = "0912_config_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bỏ qua bảng ĐÃ có RLS (idempotent) và bảng thiếu cột `tenant_id` — hàm sẽ RAISE cho
    # bảng thiếu cột, và một migration vỡ vì một bảng phụ không đáng.
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT n.nspname || '.' || c.relname AS bang
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'tenant_data'
                   AND c.relkind = 'r'
                   AND NOT c.relrowsecurity
                   AND EXISTS (
                       SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                          AND a.attnum > 0 AND NOT a.attisdropped
                   )
                 ORDER BY 1
            LOOP
                -- Policy có thể còn sót từ lần bật trước (0909 chỉ DISABLE, không DROP
                -- policy ở mọi đường). Dọn trước để hàm CREATE POLICY không vỡ.
                EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %s', r.bang);
                PERFORM control.enforce_tenant_isolation(r.bang);
                RAISE NOTICE 'RLS bật lại: %', r.bang;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """Về đúng trạng thái 0909 để lại: không bảng nào trong `tenant_data` còn RLS."""
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT n.nspname || '.' || c.relname AS bang
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'tenant_data' AND c.relkind = 'r' AND c.relrowsecurity
                 ORDER BY 1
            LOOP
                EXECUTE format('ALTER TABLE %s NO FORCE ROW LEVEL SECURITY', r.bang);
                EXECUTE format('ALTER TABLE %s DISABLE ROW LEVEL SECURITY', r.bang);
                EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %s', r.bang);
            END LOOP;
        END $$;
        """
    )
