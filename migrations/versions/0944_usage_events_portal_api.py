"""billing.usage_events — GRANT SELECT + policy đọc cho portal_api

VẤN ĐỀ NÓ GIẢI: `0942_billing_usage_events` tạo bảng, bật RLS ENABLE và cấp
SELECT/INSERT cho `agent_all`, nhưng CỐ Ý không cấp gì cho `portal_api` — chính
docstring của nó ghi rõ: "Portal khi làm sẽ cần một migration cấp
`GRANT SELECT ... TO portal_api` riêng." Đây là migration đó, viết cùng lúc với
`modules/billing/repo.py` (task 5) vì đó là chỗ đầu tiên Portal thực sự ĐỌC
bảng này bằng role `portal_api` — không có GRANT + policy này thì mọi câu SQL
của `repo.py` (chạy qua `tenant_conn()`, tức luôn bằng `portal_api`) ném thẳng
`InsufficientPrivilegeError`, không phải trả 0 hàng.

Hai việc, cả hai đều cần:
1. `GRANT SELECT` — thiếu nó là `permission denied for table usage_events`,
   NGAY CẢ khi có policy đúng (RLS lọc HÀNG, không thay được cho quyền BẢNG).
2. Một policy SELECT khớp role `portal_api` — bảng đã `ENABLE` (không `FORCE`)
   RLS với đúng HAI policy, cả hai đều `TO agent_all`, không `TO portal_api`.

   ⚠️ SỬA LẦN 2 (review): bản đầu của đoạn này viết sai LÝ DO — từng ghi rằng
   "RLS không đi theo cây kế thừa role" (đại ý: `portal_api` dù là thành viên
   `agent_all` cũng không tự động khớp policy `TO agent_all`). Đo trực tiếp
   trên DB dev: SAI. Postgres `INHERIT` là mặc định, và một policy khai
   `TO parent_role` ÁP DỤNG cho mọi thành viên kế thừa — nếu `portal_api` thật
   sự là thành viên `agent_all`, nó đã khớp `agent_read`/`agent_insert` của
   `0942` mà không cần policy riêng nào ở đây.

   LÝ DO THẬT: **không migration nào từng làm `portal_api` thành thành viên
   của `agent_all`.** `0003_role_and_isolation_helper.py:62` tạo nó trần
   (`CREATE ROLE portal_api NOLOGIN`, không `IN ROLE agent_all`), và
   `GRANT agent_all TO odyssey_agent`/`GRANT agent_all TO %I` (roles agent
   runtime, `0901`/`0005`/`0911`) không bao giờ nhắc tới `portal_api`. Trên một
   DB migrate-từ-đầu (đúng cảnh testcontainers của test suite), `portal_api`
   KHÔNG PHẢI thành viên `agent_all` — đo được: SELECT trên bảng này ném
   `permission denied` (thiếu GRANT ở tầng bảng), không phải "0 hàng" (thiếu
   policy ở tầng RLS). DB dev có thể TRÔNG như hai role liên quan vì ai đó đã
   `GRANT agent_all TO portal_api` bằng tay ngoài migration — đó là DRIFT, và
   là đúng lý do hai môi trường ứng xử khác nhau, không phải bằng chứng cho
   giả thuyết "RLS bỏ qua kế thừa". `test_schema_billing.py` từng lặp lại
   đúng khẳng định sai này — đã sửa cùng đợt.

   Vì vậy migration này CẦN CẢ HAI thứ độc lập: GRANT (bảng) lẫn policy
   `tenant_read TO portal_api` (hàng) — không thứ nào suy ra được từ thứ kia,
   và không thứ nào suy ra được từ tư cách thành viên `agent_all` (vì tư cách
   đó không tồn tại trên DB sạch). Thiếu policy này, đọc NGOÀI giao dịch
   (`current_tenant() = NULL`) và TRONG giao dịch đều ra 0 hàng như nhau —
   không phân biệt được hai ca, đúng cái mà `test_doc_ngoai_giao_dich_tra_0_hang`
   phải phân biệt (0 hàng vì thiếu `tenant_conn()`, KHÔNG PHẢI vì thiếu quyền).

Tên policy `tenant_read`, khớp đúng quy ước `0943_billing_pricing` đã dùng cho
`billing.rated_usage` (SELECT-only, cùng biểu thức `tenant_id =
portal.current_tenant()`).

IDEMPOTENT (`DROP POLICY IF EXISTS` trước `CREATE`, `GRANT` tự idempotent) —
cùng khuôn `0942`/`0943`, an toàn chạy lại trên DB đã có sẵn quyền này.

Revision ID: 0944_usage_events_portal_api
Revises: 0943_billing_pricing
"""

from alembic import op

revision = "0944_usage_events_portal_api"
down_revision = "0943_billing_pricing"
branch_labels = None
depends_on = None

_QUYEN = """
GRANT SELECT ON billing.usage_events TO portal_api;

DROP POLICY IF EXISTS tenant_read ON billing.usage_events;
CREATE POLICY tenant_read ON billing.usage_events FOR SELECT TO portal_api
  USING (tenant_id = portal.current_tenant());
"""


def upgrade() -> None:
    op.execute(_QUYEN)


def downgrade() -> None:
    op.execute("""
        DROP POLICY IF EXISTS tenant_read ON billing.usage_events;
        REVOKE SELECT ON billing.usage_events FROM portal_api;
    """)
