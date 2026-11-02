"""Đồng bộ lại RLS `tenant_data` — dọn policy legacy tiền-`0913` còn sót trên 9 bảng

PHÁT HIỆN: người dùng báo `/projects` hiện rỗng dù DB có dữ liệu thật. Đo trực
tiếp trên DB dev bằng `psql`, role `portal_api` (role runtime thật của app),
`SET app.tenant_id = 'anphu'` (đúng như `tenant_conn()` làm cho mỗi giao dịch):

    -- bằng portal_migrator (superuser, bypass RLS) --> 2 dòng (NPLB, SRC)
    -- bằng portal_api (RLS áp dụng)                --> 0 dòng

`tenant_id = portal.current_tenant()` trong câu SQL của `repo.liet_ke_du_an`
ĐÚNG — `portal.current_tenant()` trả `'anphu'` chính xác. Vấn đề nằm ở RLS:
`pg_policy` cho thấy bảng `tenant_data.projects` (và 8 bảng khác cùng
"nhóm dữ liệu agent ghi/đọc": `units`, `zones`, `contacts`, `conversations`,
`conversation_messages`, `escalations`, `media`, `documents`, `appointments`)
đang mang MỘT CẶP POLICY KHÁC — không phải bản mà `control.enforce_tenant_isolation()`
tạo ra hôm nay:

    agent_runtime    USING (tenant_id = current_setting('app.current_tenant', true))
    tenant_isolation USING (tenant_id = CURRENT_USER)

Cả hai đều SAI so với những gì code backend thực sự set. `tenant_conn()`
(`core/db/session.py`) chỉ `SELECT set_config('app.tenant_id', $1, true)` —
không hề có `app.current_tenant`. Và `CURRENT_USER` của kết nối `portal_api`
luôn là chuỗi `'portal_api'`, không bao giờ bằng một `tenant_id` thật. Vì cả
hai policy permissive đều sai, Postgres lọc sạch MỌI hàng cho kết nối
`portal_api` — không ném lỗi, chỉ trả rỗng, giống hệt triệu chứng "tenant
không có dữ liệu".

`agent_runtime` chính là "policy cũ" mà docstring `0913_bat_lai_rls_tenant_data`
đã nhắc tới và CỐ Ý không dựng lại ("thuộc về phía agent... không dựng lại
policy đó, thừa") — tức nó là di sản THẬT SỰ tồn tại trước `0913`, không phải
suy đoán. Bản `tenant_isolation` kiểu `CURRENT_USER` cũng là một quy ước còn
CŨ HƠN — trước khi `portal.current_tenant()` được viết để đọc `app.tenant_id`
(hàm này tự nó KHÔNG đổi, xem `0001_schemas_and_functions.py`).

VÌ SAO `0913` KHÔNG DỌN ĐƯỢC 9 BẢNG NÀY: vòng lặp của `0913` chỉ xét bảng
`NOT c.relrowsecurity` (RLS đang TẮT). Chín bảng này đã có `relrowsecurity =
true` từ trước (mang policy legacy nói trên), nên `0913` bỏ qua chúng và chỉ
dựng policy chuẩn cho các bảng RLS đang tắt tại thời điểm nó chạy (`agent_config`,
`kb_files`, `escalation_notes`, các bảng `ingest_*`...) — khớp CHÍNH XÁC với
những gì đo được: các bảng đó có policy đúng, chín bảng kia thì không.

SỬA: dò động TOÀN BỘ bảng `tenant_data` có cột `tenant_id` (cùng lối `0913`,
không liệt kê tên tay — danh sách bảng của schema này còn tăng), DROP cả hai
tên policy có thể tồn tại (tên chuẩn lẫn `agent_runtime` legacy) rồi gọi lại
`control.enforce_tenant_isolation()`. An toàn khi chạy lại: bảng đã đúng thì
DROP+CREATE ra lại đúng policy y hệt, không đổi hành vi.

Revision ID: 0956_dong_bo_lai_rls_tenant_data
Revises: 0955_hop_nhat_hai_head
"""

from alembic import op

revision = "0956_dong_bo_lai_rls_tenant_data"
down_revision = "0955_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
                   AND EXISTS (
                       SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'
                          AND a.attnum > 0 AND NOT a.attisdropped
                   )
                 ORDER BY 1
            LOOP
                -- Dọn CẢ HAI tên policy có thể còn sót — bản chuẩn hiện hành
                -- (để CREATE POLICY không vỡ vì trùng tên) và bản legacy
                -- `agent_runtime` (`app.current_tenant` không ai set nữa).
                EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %s', r.bang);
                EXECUTE format('DROP POLICY IF EXISTS agent_runtime ON %s', r.bang);
                PERFORM control.enforce_tenant_isolation(r.bang);
                RAISE NOTICE 'RLS đồng bộ lại: %', r.bang;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    """Không làm gì.

    Trạng thái trước migration này không phải một trạng thái mà migration nào
    khác cố ý tạo ra — nó là drift (chín bảng còn sót policy tiền-`0913`).
    Lùi về đó là khôi phục lại đúng cái lỗi vừa sửa, không phải "hoàn tác một
    thay đổi lược đồ". `enforce_tenant_isolation()` idempotent nên chạy lại
    `upgrade()` ở lần `alembic upgrade head` kế tiếp vẫn cho đúng kết quả.
    """
