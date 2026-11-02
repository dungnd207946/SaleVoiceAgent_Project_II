"""billing: cột `text_units` — layout 2026-08-20 của bên agent

BÊN AGENT ĐỔI NGỮ NGHĨA HAI CỘT, đây là migration theo:
· `text_units bigint NOT NULL DEFAULT 0` — **cột MỚI**, lượng text theo KÝ TỰ.
· `units` từ nay THỐNG NHẤT = **số lần gọi/sự kiện** cho MỌI component. Trước đó mỗi
  component một nghĩa (tts giữ ký tự, embed giữ "số đoạn text"), tức cột không tự mô tả.

⚠️ ALTER ĐÃ CHẠY TAY TRÊN DB DEV bởi bên agent, nhưng KHÔNG có trong migration nào ⇒
database sạch (CI, testcontainer) không có cột này ⇒ mọi truy vấn của module billing vỡ.
Đây là migration đưa nó vào cây. `ADD COLUMN IF NOT EXISTS` nên chạy được cả hai phía.

ĐỔI CƠ SỞ TÍNH TIỀN (bảng §2.1 của contract mới):
· `tts`   : `units` → `text_units`  (ký tự ĐƯA VÀO TTS; `units` nay = số clause synth)
· `embed` : `units` → `text_units`  (ký tự đem embed;  `units` nay = số lời gọi)
· `stt` + `conversation`: THÊM `text_units` = ký tự transcript final — **vế ĐỘC LẬP,
  CỘNG THÊM** vào vế thời lượng, không phải thay thế. Vendor kiểu Soniox thu hai đồng hồ
  (input-audio theo stream + output-text theo transcript); vendor không thu text thì đặt 0.

⚠️ VÌ VẾ TEXT CỦA STT LÀ ĐỘC LẬP, INDEX `price_item_stt_single_basis` PHẢI NỚI.
Bản cũ cho nhiều nhất MỘT dòng `stt` có `unit_price > 0` mỗi bộ giá — nay sẽ CHẶN OAN
vế text hợp lệ. Luật "chọn một" chỉ áp cho cặp THỜI LƯỢNG (`audio_sec` vs `wall_ms`,
hai cách đo cùng một quãng); `text_units` nằm ngoài luật đó.

⚠️ DÒNG GHI TRƯỚC 2026-08-20 mang layout cũ (ký tự TTS nằm trong `units`,
`text_units = 0`). Sau migration này chúng KHÔNG được tính tiền cho phần ký tự —
`price_coverage_gap` cũng không kêu vì `text_units = 0` nghĩa là không có lượng nào để
tính. Bên agent xác nhận toàn bộ là dữ liệu dev/test nên không backfill. Nếu về sau cần
tính lại dữ liệu cũ thì phải chuyển `units` → `text_units` cho `tts`/`embed` trước.

Ba khối `CASE source_expr` (rate_usage, preview_price_version, price_coverage_gap) đều
phải mọc nhánh `text_units` — đúng cái điểm mù mà `test_moi_metric_dinh_gia_duoc` canh.

Revision ID: 0948_billing_text_units
Revises: 0947_billing_preview
"""

from alembic import op

revision = "0948_billing_text_units"
down_revision = "0947_billing_preview"
branch_labels = None
depends_on = None


_UP = r"""
-- 1. Cột mới (bên agent đã ALTER tay trên dev; idempotent để chạy được cả hai phía)
ALTER TABLE billing.usage_events
  ADD COLUMN IF NOT EXISTS text_units bigint NOT NULL DEFAULT 0;

-- 2. Metric mới + nới whitelist của source_expr
ALTER TABLE billing.metric DROP CONSTRAINT IF EXISTS metric_source_expr_whitelist;
ALTER TABLE billing.metric ADD CONSTRAINT metric_source_expr_whitelist CHECK (source_expr IN (
  'input_tokens','output_tokens','cache_read_tokens','cache_write_tokens',
  'audio_sec','units','wall_ms','text_units','1'
));

INSERT INTO billing.metric (code, label, source_expr, unit_kind, sort_order)
VALUES ('text_units', 'Ký tự text', 'text_units', 'character', 55)
ON CONFLICT (code) DO NOTHING;

-- 3. Đổi cơ sở tính tiền theo bảng §2.1 mới
UPDATE billing.pricing_basis
   SET metric = 'text_units',
       note = 'ký tự đưa vào TTS; `units` nay là số clause synth'
 WHERE component = 'tts' AND metric = 'units';

UPDATE billing.pricing_basis
   SET metric = 'text_units',
       note = 'ký tự đem embed; nhánh local (fastembed, hf) đặt giá 0'
 WHERE component = 'embed' AND metric = 'units';

INSERT INTO billing.pricing_basis (component, purpose, metric, note) VALUES
  ('stt', 'conversation', 'text_units',
   'ký tự transcript final — vế ĐỘC LẬP, CỘNG THÊM vào vế thời lượng, không thay thế')
ON CONFLICT (component, purpose, metric) DO NOTHING;

-- 4. Nới luật "STT chỉ một cơ sở" xuống đúng cặp THỜI LƯỢNG
DROP INDEX IF EXISTS billing.price_item_stt_single_basis;
CREATE UNIQUE INDEX price_item_stt_single_basis
  ON billing.price_item (price_version_id, component)
  WHERE component = 'stt' AND unit_price > 0
    AND metric IN ('audio_sec', 'wall_ms');
"""

_RATE_USAGE = r"""
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
            WHEN 'text_units'::text THEN e.text_units::numeric
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

_PREVIEW = r"""
CREATE OR REPLACE FUNCTION billing.preview_price_version(
    p_version_id bigint,
    p_tenant text,
    p_from timestamp with time zone,
    p_to timestamp with time zone)
 RETURNS numeric
 LANGUAGE sql
 STABLE
AS $function$
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
            WHEN 'text_units'::text THEN e.text_units::numeric
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
$function$;
"""

_VIEWS = r"""
CREATE OR REPLACE VIEW billing.price_coverage_gap AS  SELECT e.tenant_id,
    e.component,
    e.purpose,
    e.provider,
    e.model,
    cs.metric,
    count(*) AS events,
    sum(q.qty) AS quantity
   FROM billing.usage_events e
     LEFT JOIN billing.purpose pu ON pu.code = e.purpose
     JOIN billing.pricing_basis cs ON cs.component = e.component AND (cs.purpose = ''::text OR cs.purpose = e.purpose)
     JOIN billing.metric m ON m.code = cs.metric
     CROSS JOIN LATERAL ( SELECT
                CASE m.source_expr
                    WHEN 'input_tokens'::text THEN e.input_tokens::numeric
                    WHEN 'output_tokens'::text THEN e.output_tokens::numeric
                    WHEN 'cache_read_tokens'::text THEN e.cache_read_tokens::numeric
                    WHEN 'cache_write_tokens'::text THEN e.cache_write_tokens::numeric
                    WHEN 'audio_sec'::text THEN e.audio_sec::numeric
                    WHEN 'units'::text THEN e.units::numeric
            WHEN 'text_units'::text THEN e.text_units::numeric
                    WHEN 'wall_ms'::text THEN e.wall_ms::numeric
                    WHEN '1'::text THEN 1::numeric
                    ELSE NULL::numeric
                END AS qty) q
     LEFT JOIN billing.rated_usage r ON r.event_id = e.event_id AND r.metric = cs.metric
  WHERE r.event_id IS NULL AND q.qty > 0::numeric AND COALESCE(pu.billable, true)
  GROUP BY e.tenant_id, e.component, e.purpose, e.provider, e.model, cs.metric;;

CREATE OR REPLACE VIEW billing.unbillable_event AS  SELECT tenant_id,
    session_id,
    event_id,
    component,
    purpose,
    occurred_at,
    exact
   FROM billing.usage_events
  WHERE input_tokens = 0 AND output_tokens = 0
    AND cache_read_tokens = 0 AND cache_write_tokens = 0
    AND audio_sec = 0::double precision AND units = 0 AND text_units = 0 AND wall_ms = 0::double precision;;
"""


def upgrade() -> None:
    op.execute(_UP)
    op.execute(_RATE_USAGE)
    op.execute(_PREVIEW)
    op.execute(_VIEWS)


def downgrade() -> None:
    # Cột KHÔNG bị bỏ: bên agent đang ghi vào nó, drop là mất dữ liệu đang chảy vào.
    op.execute("""
        DROP INDEX IF EXISTS billing.price_item_stt_single_basis;
        CREATE UNIQUE INDEX price_item_stt_single_basis
          ON billing.price_item (price_version_id, component)
          WHERE component = 'stt' AND unit_price > 0;

        DELETE FROM billing.pricing_basis
         WHERE component = 'stt' AND purpose = 'conversation' AND metric = 'text_units';
        UPDATE billing.pricing_basis SET metric = 'units' WHERE component = 'tts'   AND metric = 'text_units';
        UPDATE billing.pricing_basis SET metric = 'units' WHERE component = 'embed' AND metric = 'text_units';
        DELETE FROM billing.metric WHERE code = 'text_units';

        ALTER TABLE billing.metric DROP CONSTRAINT IF EXISTS metric_source_expr_whitelist;
        ALTER TABLE billing.metric ADD CONSTRAINT metric_source_expr_whitelist CHECK (source_expr IN (
          'input_tokens','output_tokens','cache_read_tokens','cache_write_tokens',
          'audio_sec','units','wall_ms','1'
        ));
    """)
