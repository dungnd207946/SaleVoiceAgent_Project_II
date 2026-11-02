-- Billing pricing + rating schema (v1)
-- Alembic head hiện tại: 0942_billing_usage_events  →  migration mới: 0943_billing_pricing
-- Không sửa gì trong billing.usage_events.

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- =====================================================================
-- 1. Sổ đăng ký metric — map "loại đơn vị tính tiền" → cột trong usage_events
--    Thêm metric mới = INSERT 1 dòng, KHÔNG phải sửa schema.
-- =====================================================================
CREATE TABLE billing.metric (
  code        text PRIMARY KEY,
  label       text NOT NULL,
  source_expr text NOT NULL,          -- cột nguồn trong usage_events
  unit_kind   text NOT NULL,          -- token | second | character | request
  sort_order  int  NOT NULL DEFAULT 0,
  CONSTRAINT metric_source_expr_whitelist CHECK (source_expr IN (
    'input_tokens','output_tokens','cache_read_tokens','cache_write_tokens',
    'audio_sec','units','wall_ms','text_units','1'
  ))
);

INSERT INTO billing.metric (code, label, source_expr, unit_kind, sort_order) VALUES
  ('input_tokens',       'Input token',        'input_tokens',       'token',   10),
  ('output_tokens',      'Output token',       'output_tokens',      'token',   20),
  ('cache_read_tokens',  'Cache read token',   'cache_read_tokens',  'token',   30),
  ('cache_write_tokens', 'Cache write token',  'cache_write_tokens', 'token',   40),
  ('audio_sec',          'Thời lượng audio',   'audio_sec',          'second',  50),
  ('units',              'Số lần gọi',         'units',              'request', 60),
  ('text_units',         'Ký tự text',         'text_units',         'character', 55),
  ('wall_ms',            'Thời gian kết nối',  'wall_ms',            'ms',      65),
  ('event_count',        'Số lần gọi',         '1',                  'request', 70);

-- =====================================================================
-- 2. Phiên bản bảng giá
-- =====================================================================
-- `status` chỉ là NHÃN VẬN HÀNH cho giao diện: 'active' = đang được áp cho ít
-- nhất một tenant tại thời điểm này. Nó KHÔNG phải nguồn sự thật khi định giá —
-- xem chú thích của billing.resolve_price_version() và mục 4 dưới đây.
CREATE TABLE billing.price_version (
  id         bigserial PRIMARY KEY,
  code       text NOT NULL UNIQUE,
  name       text NOT NULL DEFAULT '',
  currency   char(3) NOT NULL,
  status     text NOT NULL DEFAULT 'inactive'
             CHECK (status IN ('active','inactive')),
  is_default boolean NOT NULL DEFAULT false,
  note       text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by text NOT NULL DEFAULT ''
);

-- nhiều nhất 1 bảng giá mặc định
CREATE UNIQUE INDEX price_version_single_default ON billing.price_version ((true)) WHERE is_default;

-- =====================================================================
-- 3. Dòng giá — long form: 1 dòng cho 1 metric
--    provider/model/purpose = '' nghĩa là "áp cho mọi giá trị" (wildcard).
--    Để MIỄN PHÍ một loại: tạo dòng với unit_price = 0. ĐỪNG bỏ trống
--    (bỏ trống = không khớp giá = âm thầm free, không ai biết).
-- =====================================================================
CREATE TABLE billing.price_item (
  id            bigserial PRIMARY KEY,
  price_version_id bigint NOT NULL REFERENCES billing.price_version(id) ON DELETE CASCADE,
  component     text   NOT NULL,                 -- llm|stt|tts|vad|speaker_verify|call
  purpose       text   NOT NULL DEFAULT '',
  provider      text   NOT NULL DEFAULT '',
  model         text   NOT NULL DEFAULT '',
  metric        text   NOT NULL REFERENCES billing.metric(code),
  unit_price    numeric(20,10) NOT NULL CHECK (unit_price >= 0),
  per_units     bigint NOT NULL DEFAULT 1 CHECK (per_units > 0),
  note          text   NOT NULL DEFAULT '',
  UNIQUE (price_version_id, component, purpose, provider, model, metric)
);

-- STT có HAI cách đo cùng một dịch vụ: (stt,'conversation')/audio_sec theo audio khách nói,
-- và (stt,'stream')/wall_ms theo thời gian kết nối. Đặt giá cả hai = TÍNH TIỀN STT HAI LẦN.
-- Index này chỉ cho phép nhiều nhất MỘT dòng stt có giá > 0 trong một bảng giá.
-- Dòng giá 0 không bị chặn (khai tường minh "cơ sở này không dùng").
CREATE UNIQUE INDEX price_item_stt_single_basis
  ON billing.price_item (price_version_id, component)
  WHERE component = 'stt' AND unit_price > 0
    AND metric IN ('audio_sec', 'wall_ms');   -- text_units NGOÀI luật chọn-một

COMMENT ON COLUMN billing.price_item.per_units IS
  'Giá cho mỗi per_units đơn vị. VD 0.30 USD / 1 triệu token → unit_price=0.30, per_units=1000000';

-- độ ưu tiên khi 1 event khớp nhiều dòng giá: model > provider > purpose
CREATE OR REPLACE FUNCTION billing.price_item_specificity(
  p_purpose text, p_provider text, p_model text
) RETURNS int LANGUAGE sql IMMUTABLE AS $$
  SELECT (p_model <> '')::int * 4 + (p_provider <> '')::int * 2 + (p_purpose <> '')::int;
$$;


-- =====================================================================
-- 3b. billing.pricing_basis — component nào tính tiền bằng metric nào
--     Bảng §2 trong hướng dẫn của bên agent, đưa về dạng dữ liệu.
--     Hai người đọc: (a) view cảnh báo thiếu giá chỉ soi đúng các cặp này,
--     (b) form Pricing sinh đúng số ô cần nhập, không thừa không thiếu.
--     Không khai ở đây = metric phụ, chỉ để phân tích, không ai tính tiền.
-- =====================================================================
CREATE TABLE billing.pricing_basis (
  component text NOT NULL,
  purpose   text NOT NULL DEFAULT '',     -- '' = mọi purpose
  metric    text NOT NULL REFERENCES billing.metric(code),
  note      text NOT NULL DEFAULT '',
  PRIMARY KEY (component, purpose, metric)
);

INSERT INTO billing.pricing_basis (component, purpose, metric, note) VALUES
  ('llm',            '',             'input_tokens',       'giá theo (provider, model)'),
  ('llm',            '',             'output_tokens',      'giá theo (provider, model)'),
  ('llm',            '',             'cache_write_tokens', 'provider không cache thì luôn 0'),
  ('llm',            '',             'cache_read_tokens',  'provider không cache thì luôn 0'),
  ('embed',          '',             'text_units',         'ký tự đem embed; nhánh local đặt giá 0'),
  ('stt',            'conversation', 'audio_sec',          'giây khách thực nói — CHỌN MỘT với dòng wall_ms'),
  ('stt',            'conversation', 'text_units',         'ký tự transcript — vế ĐỘC LẬP, CỘNG THÊM, không thuộc luật chọn-một'),
  ('stt',            'stream',       'wall_ms',            'thời gian stream mở — CHỌN MỘT với dòng trên'),
  ('tts',            '',             'text_units',         'ký tự đưa vào TTS; units = số clause synth'),
  ('vad',            '',             'audio_sec',          'giây audio đã quét'),
  ('speaker_verify', '',             'audio_sec',          'giây audio đem embed giọng'),
  ('call',           '',             'audio_sec',          'thời lượng cuộc gọi — phí nền tảng/phút');


-- =====================================================================
-- 3c. Nhãn purpose nào TÍNH KHÁCH
--     Đây là một phép LỌC, độc lập với việc khớp giá — không gộp được vào
--     price_item. Lý do cụ thể: dòng giá cụ-thể-theo-model có độ ưu tiên
--     CAO HƠN dòng giá cụ-thể-theo-purpose (model 4 + provider 2 > purpose 1),
--     nên một dòng "warm_cache giá 0" sẽ THUA dòng "gemini-2.5-flash giá 2500"
--     và vẫn bị tính tiền. Cờ ở đây lọc TRƯỚC khi khớp giá nên không có xung đột.
--     Nhãn KHÔNG khai ở đây ⇒ mặc định TÍNH TIỀN (không im lặng mất doanh thu),
--     và hiện trong view billing.purpose_unclassified để admin phân loại.
-- =====================================================================
CREATE TABLE billing.purpose (
  code     text PRIMARY KEY,
  billable boolean NOT NULL,
  note     text NOT NULL DEFAULT ''
);

INSERT INTO billing.purpose (code, billable, note) VALUES
  ('conversation',   true,  'lượt hội thoại chính, kể cả vòng tool'),
  ('summary',        true,  'nén lịch sử + tóm tắt cuối phiên'),
  ('suggestions',    true,  'gợi ý câu hỏi tiếp theo (chỉ chat)'),
  ('embed',          true,  'đi cùng component=embed'),
  ('stream',         true,  'đi cùng component=stt; giá 0 vì STT thu theo giây'),
  ('session',        true,  'đi cùng component=call, phí nền tảng/phút'),
  ('memory',         false, 'trộn hồ sơ khách cuối phiên — giá vốn'),
  ('warm_cache',     false, 'hâm nóng prompt cache — tối ưu nội bộ'),
  ('addressee_gate', false, 'phân loại nói-với-agent hay nói-leo — giá vốn'),
  ('semcache',       false, 'dự đoán lượt kế, mặc định TẮT — giá vốn');


-- =====================================================================
-- 3d. Phiên bản giá ĐÃ SINH RA TIỀN thì KHÔNG được sửa nữa
--     Cùng lệ với `control.config_versions` (migration 0200 REVOKE UPDATE,
--     DELETE): thứ gì đã được viện dẫn thì bất biến.
--     Không có chốt này thì sửa một đơn giá rồi chạy lại rate_usage sẽ VIẾT LẠI
--     hoá đơn của những tháng đã chốt — và ra số mới trông hoàn toàn hợp lý.
--     Muốn đổi giá thì tạo phiên bản MỚI, đó là lý do bảng này có version.
-- =====================================================================
CREATE OR REPLACE FUNCTION billing.chan_sua_gia_da_dung() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_id bigint;
BEGIN
  v_id := COALESCE(OLD.price_version_id, NEW.price_version_id);
  IF EXISTS (SELECT 1 FROM billing.rated_usage WHERE price_version_id = v_id) THEN
    RAISE EXCEPTION
      'phien ban gia % da sinh ra tien trong rated_usage — khong sua duoc. '
      'Tao mot price_version moi roi gan cho tenant tu mot moc effective_from.',
      v_id
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER price_item_bat_bien
  BEFORE UPDATE OR DELETE ON billing.price_item
  FOR EACH ROW EXECUTE FUNCTION billing.chan_sua_gia_da_dung();

-- =====================================================================
-- 4. Gán phiên bản giá cho tenant theo thời gian
-- =====================================================================
CREATE TABLE billing.tenant_price_version (
  id             bigserial PRIMARY KEY,
  tenant_id      text   NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
  price_version_id  bigint NOT NULL REFERENCES billing.price_version(id),
  effective_from timestamptz NOT NULL,
  effective_to   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (effective_to IS NULL OR effective_to > effective_from)
);

-- chặn 2 bảng giá cùng hiệu lực cho 1 tenant (nếu không sẽ rate nhập nhằng)
ALTER TABLE billing.tenant_price_version
  ADD CONSTRAINT tenant_price_version_no_overlap
  EXCLUDE USING gist (tenant_id WITH =, tstzrange(effective_from, effective_to) WITH &&);

-- Phiên bản giá áp dụng cho 1 tenant tại 1 THỜI ĐIỂM (fallback về is_default).
--
-- ⚠️ HÀM NÀY CỐ Ý KHÔNG ĐỌC `status`. Nghe có vẻ sai nhưng đọc status là một BUG
-- tính tiền: một phiên bản đã hết hiệu lực mang status 'inactive', mà lịch sử
-- `rated_usage` của những tháng nó từng áp vẫn trỏ về nó. Nếu hàm này đòi
-- status='active' thì mọi lần TÍNH LẠI một kỳ quá khứ (re-run 48h, hay tính lại
-- sau khi sửa dữ liệu) sẽ không tìm thấy phiên bản cũ, rơi về is_default, và ra
-- MỘT SỐ TIỀN KHÁC cho một kỳ đã chốt — im lặng, không lỗi nào phát ra.
--
-- Nguồn sự thật khi định giá là KHOẢNG HIỆU LỰC trong tenant_price_version.
-- `status` chỉ trả lời câu "phiên bản nào đang dùng" cho giao diện.
CREATE OR REPLACE FUNCTION billing.resolve_price_version(p_tenant text, p_at timestamptz)
RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    (SELECT price_version_id FROM billing.tenant_price_version
      WHERE tenant_id = p_tenant
        AND effective_from <= p_at
        AND (effective_to IS NULL OR effective_to > p_at)
      LIMIT 1),
    (SELECT id FROM billing.price_version WHERE is_default LIMIT 1)
  );
$$;

-- =====================================================================
-- 5. Kết quả định giá — 1 dòng / (event_id, metric)
--    Snapshot cả chiều lẫn giá → tiền quá khứ KHÔNG đổi khi sửa giá,
--    đổi key, hay xoá conversation.
-- =====================================================================
CREATE TABLE billing.rated_usage (
  event_id      bigint NOT NULL REFERENCES billing.usage_events(event_id) ON DELETE CASCADE,
  metric        text   NOT NULL REFERENCES billing.metric(code),

  -- snapshot chiều
  tenant_id     text        NOT NULL,
  agent_key_id  bigint,
  occurred_at   timestamptz NOT NULL,
  component     text        NOT NULL,
  purpose       text        NOT NULL,
  provider      text        NOT NULL,
  model         text        NOT NULL,

  -- snapshot giá
  price_version_id bigint NOT NULL REFERENCES billing.price_version(id),
  price_item_id bigint,
  quantity      numeric(20,4)  NOT NULL,
  unit_price    numeric(20,10) NOT NULL,
  per_units     bigint         NOT NULL,
  amount        numeric(20,10) NOT NULL,   -- KHÔNG làm tròn ở tầng này
  currency      char(3)        NOT NULL,

  rated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, metric)
);

CREATE INDEX rated_usage_tenant_time ON billing.rated_usage (tenant_id, occurred_at);
CREATE INDEX rated_usage_key_time    ON billing.rated_usage (agent_key_id, occurred_at)
  WHERE agent_key_id IS NOT NULL;
CREATE INDEX rated_usage_component   ON billing.rated_usage (tenant_id, component, occurred_at);

-- =====================================================================
-- 6. Job định giá — idempotent, chạy lại bao nhiêu lần cũng ra 1 kết quả
--
-- SECURITY DEFINER: portal_api KHÔNG có INSERT trên rated_usage (đường ghi duy
-- nhất là hàm này). Nhưng DEFINER bỏ qua RLS, nên `p_tenant` là vế BẮT BUỘC để
-- chặn: thiếu nó thì một lời gọi cho tenant A định giá luôn usage của B bằng bảng
-- giá của A — sai tiền của cả hai, không lỗi nào phát ra.
-- p_tenant = NULL chỉ dành cho job cron cấp nền tảng (mọi tenant).
-- =====================================================================
CREATE OR REPLACE FUNCTION billing.rate_usage(
  p_from timestamptz, p_to timestamptz, p_tenant text DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER AS $$
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
      WHEN 'text_units'         THEN e.text_units::numeric
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
END $$;

-- =====================================================================
-- 7. View cho UI
-- =====================================================================

-- 7a. Thiếu giá = âm thầm miễn phí. View này phải LUÔN rỗng.
--     Chỉ soi các cặp đã khai ở billing.pricing_basis → không báo nhiễu
--     về metric phụ (vd llm.wall_ms, tts.audio_sec) vốn không ai tính tiền.
CREATE OR REPLACE VIEW billing.price_coverage_gap AS
SELECT e.tenant_id, e.component, e.purpose, e.provider, e.model, cs.metric,
       count(*) AS events, sum(q.qty) AS quantity
FROM billing.usage_events e
LEFT JOIN billing.purpose pu ON pu.code = e.purpose
JOIN billing.pricing_basis cs
      ON cs.component = e.component
     AND (cs.purpose = '' OR cs.purpose = e.purpose)
JOIN billing.metric m ON m.code = cs.metric
CROSS JOIN LATERAL (SELECT CASE m.source_expr
      WHEN 'input_tokens'       THEN e.input_tokens::numeric
      WHEN 'output_tokens'      THEN e.output_tokens::numeric
      WHEN 'cache_read_tokens'  THEN e.cache_read_tokens::numeric
      WHEN 'cache_write_tokens' THEN e.cache_write_tokens::numeric
      WHEN 'audio_sec'          THEN e.audio_sec::numeric
      WHEN 'units'              THEN e.units::numeric
      WHEN 'text_units'         THEN e.text_units::numeric
      WHEN 'wall_ms'            THEN e.wall_ms::numeric
      WHEN '1'                  THEN 1::numeric
    END AS qty) q
LEFT JOIN billing.rated_usage r ON r.event_id = e.event_id AND r.metric = cs.metric
WHERE r.event_id IS NULL AND q.qty > 0 AND coalesce(pu.billable, true)
GROUP BY 1,2,3,4,5,6;

-- 7a-bis. Nhãn purpose agent gửi lên mà chưa ai phân loại tính-khách hay không.
--         Đang được TÍNH TIỀN theo mặc định — admin phải xác nhận.
CREATE OR REPLACE VIEW billing.purpose_unclassified AS
SELECT e.purpose, e.component, count(*) AS events, min(e.occurred_at) AS lan_dau
FROM billing.usage_events e
LEFT JOIN billing.purpose pu ON pu.code = e.purpose
WHERE pu.code IS NULL
GROUP BY 1,2;

-- 7b. Tiền theo key theo ngày — nền cho màn "Usage by Key"
CREATE OR REPLACE VIEW billing.cost_by_key_day AS
SELECT tenant_id, agent_key_id, date_trunc('day', occurred_at) AS day, currency,
       sum(amount) AS amount, count(DISTINCT event_id) AS events
FROM billing.rated_usage
GROUP BY 1,2,3,4;

-- 7c. Tiền theo component/metric — nền cho màn "Overview" và dòng hoá đơn
CREATE OR REPLACE VIEW billing.cost_by_component_day AS
SELECT tenant_id, date_trunc('day', occurred_at) AS day,
       component, purpose, provider, model, metric, currency,
       sum(quantity) AS quantity, sum(amount) AS amount, count(*) AS lines
FROM billing.rated_usage
GROUP BY 1,2,3,4,5,6,7,8;

-- 7d. Event không thu được tiền (không có số đo nào) — cần theo dõi vận hành
CREATE OR REPLACE VIEW billing.unbillable_event AS
SELECT tenant_id, session_id, event_id, component, purpose, occurred_at, exact
FROM billing.usage_events
WHERE input_tokens = 0 AND output_tokens = 0
  AND cache_read_tokens = 0 AND cache_write_tokens = 0
  AND audio_sec = 0 AND units = 0 AND wall_ms = 0 AND text_units = 0;

-- =====================================================================
-- 8. Hoá đơn (giai đoạn 2) — chốt kỳ, LÀM TRÒN ở tầng này
-- =====================================================================
CREATE TABLE billing.invoice (
  id           bigserial PRIMARY KEY,
  tenant_id    text NOT NULL REFERENCES control.tenants(id) ON DELETE RESTRICT,
  period_start date NOT NULL,
  period_end   date NOT NULL,
  currency     char(3) NOT NULL,
  status       text NOT NULL DEFAULT 'draft'
               CHECK (status IN ('draft','issued','paid','void')),
  subtotal     numeric(20,4) NOT NULL DEFAULT 0,
  total        numeric(20,4) NOT NULL DEFAULT 0,
  issued_at    timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, period_start, period_end),
  CHECK (period_end > period_start)
);

CREATE TABLE billing.invoice_line (
  id          bigserial PRIMARY KEY,
  invoice_id  bigint NOT NULL REFERENCES billing.invoice(id) ON DELETE CASCADE,
  component   text NOT NULL,
  purpose     text NOT NULL DEFAULT '',
  provider    text NOT NULL DEFAULT '',
  model       text NOT NULL DEFAULT '',
  metric      text NOT NULL,
  quantity    numeric(20,4)  NOT NULL,
  unit_price  numeric(20,10) NOT NULL,
  per_units   bigint         NOT NULL,
  amount      numeric(20,4)  NOT NULL,   -- đã làm tròn
  sort_order  int NOT NULL DEFAULT 0
);
CREATE INDEX invoice_line_invoice_idx ON billing.invoice_line (invoice_id);
