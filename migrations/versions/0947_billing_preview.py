"""billing.preview_price_version — SELECT thuần cho màn admin preview bảng giá

Task 9 (task-9-brief.md) đề xuất preview bằng cách INSERT một dòng
`tenant_price_version` NHÁP, xoá `rated_usage` của cửa sổ 30 ngày, gọi lại
`billing.rate_usage()`, đọc tổng, rồi ROLLBACK. Đo được: `portal_api` chỉ có
`GRANT SELECT` trên `billing.rated_usage` (xem `0943_billing_pricing._QUYEN`)
— đường ghi DUY NHẤT là `billing.rate_usage()`, chạy dưới `SECURITY DEFINER`.
Vế `DELETE FROM billing.rated_usage` của bản nháp đó ném
`InsufficientPrivilegeError` ngay từ câu đầu tiên; endpoint không bao giờ chạy
được. KHÔNG cấp `DELETE` cho `portal_api` để né việc này — làm vậy xoá bỏ đúng
bất biến "chỉ `rate_usage()` được ghi tiền" mà `0943` cố ý dựng lên.

Hàm này làm preview THẬT SỰ read-only: mirror đúng khuôn khớp giá của
`billing.rate_usage()` (CROSS JOIN `billing.metric` lấy số lượng theo
`source_expr`, JOIN LATERAL chọn dòng giá cụ thể nhất qua
`billing.price_item_specificity()`, lọc `billing.purpose.billable`) nhưng chỉ
SELECT tổng tiền — không INSERT, không ROLLBACK, không đụng trigger bất biến
`price_item_bat_bien`, không đụng vấn đề quyền ghi RLS nào.

⚠️ DUY NHẤT một khác biệt có chủ ý so với `rate_usage()`: hàm đó tự suy bảng
giá đang hiệu lực qua `billing.resolve_price_version(tenant, occurred_at)`; hàm
này nhận THẲNG `p_version_id` — đúng việc "xem trước MỘT bảng giá cụ thể, kể cả
còn NHÁP (`status='inactive'`)" áp lên usage thật sẽ ra bao nhiêu tiền, bất kể
bảng giá đó có đang hiệu lực cho tenant này hay không.

KHÔNG `SECURITY DEFINER`: mọi bảng hàm này chạm (`usage_events`, `price_item`,
`metric`, `purpose`, `price_version`) `portal_api` đã có `SELECT` sẵn từ
`0943_billing_pricing`/`0944_usage_events_portal_api`. Gọi hàm này phải qua
`tenant_conn(pool, tenant)` — `usage_events` có RLS theo `portal.current_tenant()`,
gọi ngoài giao dịch đã `SET LOCAL app.tenant_id` sẽ lặng lẽ trả 0 hàng.

Test canh: bảng giá ĐANG hiệu lực (`bang_gia_vi_du`) phải cho
`preview_price_version(...)` == `SELECT sum(amount) FROM billing.rated_usage`
sau khi `rate_usage()` chạy, cùng tenant/cửa sổ — hai cách tính khớp giá
KHÔNG được phép trôi nhau (`tests/modules/billing/test_admin_pricing.py`).

⚠️ SỬA (review cuối đợt billing): bản đầu của hàm này `sum()` biểu thức
`q.qty * pi.unit_price / pi.per_units` ở ĐỘ CHÍNH XÁC ĐẦY ĐỦ của kiểu
`numeric`, còn `billing.rate_usage()` (`0943`) lưu TỪNG dòng vào cột
`amount numeric(20,10)` (làm tròn từng event) TRƯỚC KHI cộng ở tầng view/SQL
khác. Hai cách chỉ ra cùng số khi mọi thương số của fixture chia hết gọn
trong 10 chữ số thập phân — một `per_units` không chia hết (vd quantity 100
qua `per_units` 60 của `call`, ra 833.333...) làm hai bên lệch nhau ở chữ số
thứ 11 trở đi, và cổng đối chiếu `test_preview_khop_rated_usage_khi_dang_hieu_luc`
đỏ vì lý do KHÔNG liên quan gì tới giá — hoặc tệ hơn, che một drift thật bằng
một phép so đã sai lệch sẵn ở cả hai vế theo cùng một hướng. Sửa: `round(...,
10)` TỪNG dòng trước khi `sum()`, đúng khuôn làm tròn của `rate_usage()`.

Revision ID: 0947_billing_preview
Revises: 0946_conversations_agent_key_fk
"""

from alembic import op

revision = "0947_billing_preview"
down_revision = "0946_conversations_agent_key_fk"
branch_labels = None
depends_on = None

_DDL = r"""
CREATE OR REPLACE FUNCTION billing.preview_price_version(
  p_version_id bigint, p_tenant text, p_from timestamptz, p_to timestamptz
) RETURNS numeric LANGUAGE sql STABLE AS $$
  SELECT coalesce(sum(round(q.qty * pi.unit_price / pi.per_units, 10)), 0)
  FROM billing.usage_events e
  LEFT JOIN billing.purpose pu ON pu.code = e.purpose
  CROSS JOIN billing.metric m
  CROSS JOIN LATERAL (SELECT CASE m.source_expr
      WHEN 'input_tokens'       THEN e.input_tokens::numeric
      WHEN 'output_tokens'      THEN e.output_tokens::numeric
      WHEN 'cache_read_tokens'  THEN e.cache_read_tokens::numeric
      WHEN 'cache_write_tokens' THEN e.cache_write_tokens::numeric
      WHEN 'audio_sec'          THEN e.audio_sec::numeric
      WHEN 'units'              THEN e.units::numeric
      WHEN 'wall_ms'            THEN e.wall_ms::numeric
      WHEN '1'                  THEN 1::numeric
    END AS qty) q
  JOIN LATERAL (
    SELECT pi.* FROM billing.price_item pi
     WHERE pi.price_version_id = p_version_id
       AND pi.component = e.component
       AND pi.metric    = m.code
       AND (pi.purpose  = '' OR pi.purpose  = e.purpose)
       AND (pi.provider = '' OR pi.provider = e.provider)
       AND (pi.model    = '' OR pi.model    = e.model)
     ORDER BY billing.price_item_specificity(pi.purpose, pi.provider, pi.model) DESC
     LIMIT 1
  ) pi ON true
  WHERE e.tenant_id = p_tenant
    AND e.occurred_at >= p_from AND e.occurred_at < p_to
    AND q.qty > 0
    AND coalesce(pu.billable, true);
$$;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS billing.preview_price_version(bigint, text, timestamptz, timestamptz);")
