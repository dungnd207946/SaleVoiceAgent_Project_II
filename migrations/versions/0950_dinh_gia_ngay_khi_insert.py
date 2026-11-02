"""billing: định giá NGAY khi `usage_events` được insert — trigger, thôi chờ cron

YÊU CẦU (người dùng chốt 2026-08-21): «khi có 1 dòng `usage_events` thì có 1 hoặc
nhiều dòng `rated_usage` được tạo ra để lưu giá tiền của usage đó». Trước bản này
việc đó CHỈ xảy ra khi ai gọi `billing.rate_usage()` — tức một cron, tức tiền trên
portal luôn trễ bằng chu kỳ cron. Nay nó xảy ra trong cùng câu INSERT.

«1 HOẶC NHIỀU» là đúng và số N do công thức quyết: `rate_usage()` CROSS JOIN
`billing.metric` (8 metric) rồi giữ lại những metric có `qty > 0` VÀ khớp được một
dòng giá. Nên một event LLM có in+out ⇒ 2 dòng; có thêm cache read/write ⇒ 4 dòng;
một event STT thu cả giây lẫn ký tự ⇒ 2 dòng; một event `vad` ⇒ 1 dòng. Khoá của
`rated_usage` là `(event_id, metric)`, đó chính là cái làm N > 1 hợp lệ.

════════════════════════════════════════════════════════════════════════════
VÌ SAO TÁCH `dinh_gia_events(bigint[])` RA THAY VÌ VIẾT CÔNG THỨC LẦN NỮA
════════════════════════════════════════════════════════════════════════════
Công thức khớp giá đã bị LẶP BA CHỖ (`rate_usage` · `preview_price_version` ·
`price_coverage_gap`) — `0948` ghi rõ đó là điểm mù mà `test_moi_metric_dinh_gia_duoc`
tồn tại để canh. Viết bản thứ TƯ cho trigger là làm điểm mù đó rộng thêm 33%.

Nên: công thức chuyển vào `billing.dinh_gia_events(p_event_ids bigint[])`, khoá theo
event_id. `rate_usage(p_from, p_to, p_tenant)` GIỮ NGUYÊN CHỮ KÝ và thành vỏ mỏng —
nó chọn event_id trong khoảng rồi uỷ thác. Hai đường (cron và trigger) từ nay chạy
CÙNG MỘT dòng code, nên chúng không thể lệch nhau về số tiền. Cổng chứng minh không
đổi hành vi: `test_doi_chieu_cong_thuc_agent.py` khoá cứng tổng `4025.26` theo đúng
công thức bên agent bàn giao.

VÌ SAO KHOÁ THEO `event_id`, KHÔNG THEO KHOẢNG THỜI GIAN: `usage_events.occurred_at`
mặc định `now()` = giờ GIAO DỊCH, nên một lô 500 event insert trong một transaction
mang CÙNG một mốc. Một trigger row-level gọi `rate_usage(occurred_at, occurred_at+1µs)`
sẽ định giá cả 500 event ở MỖI lượt trong 500 lượt — 250.000 phép cho một lô. Khoá
theo mảng event_id thì mỗi câu INSERT tốn đúng một lượt.

VÌ SAO `FOR EACH STATEMENT` + `REFERENCING NEW TABLE`, KHÔNG `FOR EACH ROW`: cùng lý
lẽ trên nhìn từ phía khác — agent ghi theo LÔ, nên một lượt cho cả lô là đúng hình
dạng của tải thật. Row-level sẽ gọi hàm 500 lần cho một lô 500 dòng.

════════════════════════════════════════════════════════════════════════════
⚠️ TRIGGER TUYỆT ĐỐI KHÔNG ĐƯỢC LÀM VỠ CÂU INSERT
════════════════════════════════════════════════════════════════════════════
`usage_events` là SỔ GỐC: mất một hàng ở đó là mất vĩnh viễn, không dựng lại được
từ đâu. `rated_usage` thì tính lại bao nhiêu lần cũng được (`ON CONFLICT DO UPDATE`).
Nên khối định giá nằm trong `BEGIN … EXCEPTION WHEN OTHERS` và chỉ `RAISE WARNING`:
định giá hỏng (thiếu dòng giá, metric mới chưa khai, bảng giá chưa seed) thì usage
vẫn được ghi, và lượt cron nguội hằng đêm sẽ vá phần tiền còn thiếu.

Đổi chiều đánh đổi này là đổi một lỗi «thiếu tiền, vá được» thành «mất số đo, không
vá được». Đừng gỡ khối EXCEPTION đó để «cho lỗi nổ sớm».

⚠️ `SECURITY DEFINER` là BẮT BUỘC, không phải cho tiện: trigger chạy dưới role của
người INSERT, tức `agent_<tenant>` — role có ZERO quyền trên `price_version`/
`price_item` (cấp cho `agent_all` là mở bảng giá cho mọi pod, xem `0943`) và không
có quyền ghi `rated_usage` (chỉ `portal_api` được SELECT). Không DEFINER thì mọi
lượt định giá ném `InsufficientPrivilege`, bị khối EXCEPTION nuốt, và hệ thống trở
lại đúng trạng thái trước migration này — im lặng.

⚠️ KHÔNG BỎ `rate_usage()`. Nó còn hai việc trigger KHÔNG làm được:
① usage tới TRƯỚC khi có dòng giá phủ nó (bảng giá thêm sau) — trigger đã chạy một
   lần rồi thôi, chỉ một lượt quét lùi mới vá được;
② backfill / tính lại một kỳ sau khi sửa dữ liệu hoặc thêm metric.
Vì thế timer NGUỘI hằng đêm (48h) GIỮ LẠI làm lưới. Timer NÓNG 2 phút thì bỏ —
trigger đã làm việc của nó, xem `deploy/systemd/`.

Revision ID: 0950_dinh_gia_ngay_khi_insert
Revises: 0949_seed_bang_gia_mac_dinh
"""

from alembic import op

revision = "0950_dinh_gia_ngay_khi_insert"
down_revision = "0949_seed_bang_gia_mac_dinh"
branch_labels = None
depends_on = None


# Công thức khớp giá — BẢN DUY NHẤT của đường GHI. Sao y `_RATE_USAGE` của `0948`,
# đổi ĐÚNG một chỗ: vế `WHERE` thôi lọc theo `occurred_at`/`tenant`, lọc theo
# `event_id = ANY(...)`. Mọi thứ khác (CROSS JOIN metric, CASE source_expr, LATERAL
# theo specificity, `qty > 0`, `coalesce(pu.billable, true)`, ON CONFLICT) giữ
# nguyên từng ký tự — đó là điều kiện để `test_doi_chieu_cong_thuc_agent` còn ra
# đúng `4025.26`.
_DINH_GIA_EVENTS = r"""
CREATE OR REPLACE FUNCTION billing.dinh_gia_events(p_event_ids bigint[])
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE n bigint;
BEGIN
  INSERT INTO billing.rated_usage (
    event_id, metric, tenant_id, agent_key_id, occurred_at,
    component, purpose, provider, model,
    price_version_id, price_item_id, quantity, unit_price, per_units, amount, currency)
  SELECT e.event_id, m.code, e.tenant_id, c.agent_key_id, e.occurred_at,
         e.component, e.purpose, e.provider, e.model,
         pb.id, pi.id, q.qty, pi.unit_price, pi.per_units,
         q.qty * pi.unit_price / pi.per_units, pb.currency
  FROM billing.usage_events e
  LEFT JOIN tenant_data.conversations c
         ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
  LEFT JOIN billing.purpose pu ON pu.code = e.purpose
  JOIN billing.price_version pb ON pb.id = billing.resolve_price_version(e.tenant_id, e.occurred_at)
  CROSS JOIN billing.metric m
  CROSS JOIN LATERAL (SELECT CASE m.source_expr
      WHEN 'input_tokens'       THEN e.input_tokens::numeric
      WHEN 'output_tokens'      THEN e.output_tokens::numeric
      WHEN 'cache_read_tokens'  THEN e.cache_read_tokens::numeric
      WHEN 'cache_write_tokens' THEN e.cache_write_tokens::numeric
      WHEN 'audio_sec'          THEN e.audio_sec::numeric
      WHEN 'units'              THEN e.units::numeric
      WHEN 'text_units'::text   THEN e.text_units::numeric
      WHEN 'wall_ms'            THEN e.wall_ms::numeric
      WHEN '1'                  THEN 1::numeric
    END AS qty) q
  JOIN LATERAL (
    SELECT pi.* FROM billing.price_item pi
     WHERE pi.price_version_id = pb.id
       AND pi.component = e.component
       AND pi.metric    = m.code
       AND (pi.purpose  = '' OR pi.purpose  = e.purpose)
       AND (pi.provider = '' OR pi.provider = e.provider)
       AND (pi.model    = '' OR pi.model    = e.model)
     ORDER BY billing.price_item_specificity(pi.purpose, pi.provider, pi.model) DESC
     LIMIT 1
  ) pi ON true
  WHERE e.event_id = ANY(p_event_ids)
    AND q.qty > 0
    AND coalesce(pu.billable, true)   -- nhãn chưa khai ⇒ vẫn tính, xem view unclassified
  ON CONFLICT (event_id, metric) DO UPDATE SET
    agent_key_id  = EXCLUDED.agent_key_id,
    price_version_id = EXCLUDED.price_version_id,
    price_item_id = EXCLUDED.price_item_id,
    quantity      = EXCLUDED.quantity,
    unit_price    = EXCLUDED.unit_price,
    per_units     = EXCLUDED.per_units,
    amount        = EXCLUDED.amount,
    currency      = EXCLUDED.currency,
    rated_at      = now();
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $function$;
"""

# `rate_usage` thành VỎ MỎNG. Chữ ký + ngữ nghĩa trả về (số dòng đã ghi/cập nhật)
# không đổi một ly, nên `cli/dinh_gia_usage.py` và mọi test gọi nó không phải sửa gì.
#
# `p_event_ids` rỗng ⇒ `dinh_gia_events` trả 0, đúng như bản cũ khi khoảng rỗng.
_RATE_USAGE_VO = r"""
CREATE OR REPLACE FUNCTION billing.rate_usage(
    p_from timestamp with time zone,
    p_to timestamp with time zone,
    p_tenant text DEFAULT NULL::text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE ids bigint[];
BEGIN
  SELECT coalesce(array_agg(e.event_id), '{}')
    INTO ids
    FROM billing.usage_events e
   WHERE e.occurred_at >= p_from AND e.occurred_at < p_to
     AND (p_tenant IS NULL OR e.tenant_id = p_tenant);
  RETURN billing.dinh_gia_events(ids);
END $function$;
"""

_TRIGGER = r"""
CREATE OR REPLACE FUNCTION billing.dinh_gia_sau_insert() RETURNS trigger
LANGUAGE plpgsql AS $function$
DECLARE ids bigint[];
BEGIN
  SELECT coalesce(array_agg(event_id), '{}') INTO ids FROM moi;
  IF array_length(ids, 1) IS NULL THEN
    RETURN NULL;
  END IF;

  -- Khối bảo vệ SỔ GỐC — xem docstring module. Định giá hỏng thì usage VẪN ĐƯỢC
  -- GHI; lượt cron nguội hằng đêm vá phần tiền. Đừng gỡ.
  BEGIN
    PERFORM billing.dinh_gia_events(ids);
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'dinh_gia_sau_insert: % event khong dinh gia duoc (%): %. '
                  'Usage van duoc ghi; lươt cron nguoi se va lai.',
                  array_length(ids, 1), SQLSTATE, SQLERRM;
  END;
  RETURN NULL;
END $function$;

DROP TRIGGER IF EXISTS usage_events_dinh_gia ON billing.usage_events;
CREATE TRIGGER usage_events_dinh_gia
  AFTER INSERT ON billing.usage_events
  REFERENCING NEW TABLE AS moi
  FOR EACH STATEMENT EXECUTE FUNCTION billing.dinh_gia_sau_insert();
"""

# Bản `0948` của `rate_usage` — để `downgrade()` trả lại nguyên văn công thức
# thay vì để lại một cái vỏ trỏ tới hàm vừa bị DROP.
_RATE_USAGE_0948 = r"""
CREATE OR REPLACE FUNCTION billing.rate_usage(
    p_from timestamp with time zone,
    p_to timestamp with time zone,
    p_tenant text DEFAULT NULL::text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE n bigint;
BEGIN
  INSERT INTO billing.rated_usage (
    event_id, metric, tenant_id, agent_key_id, occurred_at,
    component, purpose, provider, model,
    price_version_id, price_item_id, quantity, unit_price, per_units, amount, currency)
  SELECT e.event_id, m.code, e.tenant_id, c.agent_key_id, e.occurred_at,
         e.component, e.purpose, e.provider, e.model,
         pb.id, pi.id, q.qty, pi.unit_price, pi.per_units,
         q.qty * pi.unit_price / pi.per_units, pb.currency
  FROM billing.usage_events e
  LEFT JOIN tenant_data.conversations c
         ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
  LEFT JOIN billing.purpose pu ON pu.code = e.purpose
  JOIN billing.price_version pb ON pb.id = billing.resolve_price_version(e.tenant_id, e.occurred_at)
  CROSS JOIN billing.metric m
  CROSS JOIN LATERAL (SELECT CASE m.source_expr
      WHEN 'input_tokens'       THEN e.input_tokens::numeric
      WHEN 'output_tokens'      THEN e.output_tokens::numeric
      WHEN 'cache_read_tokens'  THEN e.cache_read_tokens::numeric
      WHEN 'cache_write_tokens' THEN e.cache_write_tokens::numeric
      WHEN 'audio_sec'          THEN e.audio_sec::numeric
      WHEN 'units'              THEN e.units::numeric
      WHEN 'text_units'::text   THEN e.text_units::numeric
      WHEN 'wall_ms'            THEN e.wall_ms::numeric
      WHEN '1'                  THEN 1::numeric
    END AS qty) q
  JOIN LATERAL (
    SELECT pi.* FROM billing.price_item pi
     WHERE pi.price_version_id = pb.id
       AND pi.component = e.component
       AND pi.metric    = m.code
       AND (pi.purpose  = '' OR pi.purpose  = e.purpose)
       AND (pi.provider = '' OR pi.provider = e.provider)
       AND (pi.model    = '' OR pi.model    = e.model)
     ORDER BY billing.price_item_specificity(pi.purpose, pi.provider, pi.model) DESC
     LIMIT 1
  ) pi ON true
  WHERE e.occurred_at >= p_from AND e.occurred_at < p_to
    AND (p_tenant IS NULL OR e.tenant_id = p_tenant)
    AND q.qty > 0
    AND coalesce(pu.billable, true)
  ON CONFLICT (event_id, metric) DO UPDATE SET
    agent_key_id  = EXCLUDED.agent_key_id,
    price_version_id = EXCLUDED.price_version_id,
    price_item_id = EXCLUDED.price_item_id,
    quantity      = EXCLUDED.quantity,
    unit_price    = EXCLUDED.unit_price,
    per_units     = EXCLUDED.per_units,
    amount        = EXCLUDED.amount,
    currency      = EXCLUDED.currency,
    rated_at      = now();
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $function$;
"""


def upgrade() -> None:
    op.execute(_DINH_GIA_EVENTS)
    op.execute(_RATE_USAGE_VO)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS usage_events_dinh_gia ON billing.usage_events;")
    op.execute("DROP FUNCTION IF EXISTS billing.dinh_gia_sau_insert();")
    # Trả công thức về THÂN của `rate_usage` TRƯỚC khi drop hàm nó đang uỷ thác —
    # đảo thứ tự là để lại một `rate_usage` trỏ vào hàm không còn tồn tại.
    op.execute(_RATE_USAGE_0948)
    op.execute("DROP FUNCTION IF EXISTS billing.dinh_gia_events(bigint[]);")
