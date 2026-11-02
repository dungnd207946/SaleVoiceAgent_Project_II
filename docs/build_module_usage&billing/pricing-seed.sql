-- Bảng giá thật — CHỈ CẦN ĐIỀN SỐ vào các chỗ <...>
-- Đơn vị tiền: VND. STT đã chốt thu theo GIÂY.
-- Chạy sau khi đã áp pricing-schema.sql.

INSERT INTO billing.price_version (code, name, currency, status, is_default)
VALUES ('pv_2026_08', 'Bảng giá 08/2026', 'VND', 'active', true);

-- ---------------------------------------------------------------- LLM
-- Một khối cho MỖI (provider, model). Khai TƯỜNG MINH từng model, đừng
-- dùng wildcard: có wildcard thì model mới agent thêm vào sẽ được tính
-- giá cũ một cách âm thầm, và price_coverage_gap không bao giờ báo.
INSERT INTO billing.price_item (price_version_id, component, provider, model, metric, unit_price, per_units)
SELECT b.id, 'llm', 'gemini', 'gemini-2.5-flash', m.metric, m.gia, 1000000
FROM billing.price_version b, (VALUES
  ('input_tokens',       <giá đ/1M input>::numeric),
  ('output_tokens',      <giá đ/1M output>),
  ('cache_read_tokens',  <giá đ/1M cache read>),   -- KHÁC 0 trên data thật, đừng bỏ
  ('cache_write_tokens', <giá đ/1M cache write>)
) m(metric, gia) WHERE b.code = 'pv_2026_08';

-- -------------------------------------------------------------- EMBED
-- Chưa có data (bên agent ghi: chỉ từ 2026-08-19). Nhánh local = 0.
INSERT INTO billing.price_item (price_version_id, component, provider, model, metric, unit_price, per_units)
SELECT b.id, 'embed', m.provider, m.model, 'text_units', m.gia, 1
FROM billing.price_version b, (VALUES
  ('gemini',    'gemini-embedding-001',           <giá đ/ký tự>::numeric),
  ('service',   'dense',                          <giá vốn service>),
  ('service',   'sparse',                         <giá vốn service>),
  ('service',   'visual_text',                    <giá vốn service>),
  ('fastembed', 'Qdrant/bm25',                    0),
  ('hf',        'intfloat/multilingual-e5-large', 0)
) m(provider, model, gia) WHERE b.code = 'pv_2026_08';

-- -------------------------------------------------------------- AUDIO
-- provider luôn rỗng ở dòng audio ⇒ giá phẳng theo component.
INSERT INTO billing.price_item (price_version_id, component, purpose, metric, unit_price, per_units, note)
SELECT b.id, m.component, m.purpose, m.metric, m.gia, m.per_units, m.note
FROM billing.price_version b, (VALUES
  ('stt',            'conversation', 'audio_sec', <giá đ/giây>::numeric,  1::bigint, 'CƠ SỞ ĐÃ CHỌN: thu theo giây'),
  ('stt',            'stream',       'wall_ms',   0,                      60000,     'KHÔNG dùng — DB chặn đặt giá >0 khi dòng trên đã có giá'),
  ('tts',            '',             'text_units','<giá đ/ký tự>'::numeric, 1,      'ký tự VÀO TTS'),
  ('stt',            'conversation', 'text_units','<giá đ/ký tự transcript>'::numeric, 1, 'vế text-ra, ĐỘC LẬP — 0 nếu vendor không thu theo text'),
  ('vad',            '',             'audio_sec', <giá đ/giây>,           1,         ''),
  ('speaker_verify', '',             'audio_sec', <giá đ/giây>,           1,         ''),
  ('call',           '',             'audio_sec', <giá đ/phút>,           60,        'phí nền tảng theo phút')
) m(component, purpose, metric, gia, per_units, note) WHERE b.code = 'pv_2026_08';

-- ------------------------------------------------------------ KIỂM TRA
-- Cả ba câu dưới PHẢI rỗng trước khi phát hành hoá đơn đầu tiên.
SELECT * FROM billing.price_coverage_gap;        -- thiếu giá ⇒ âm thầm miễn phí
SELECT * FROM billing.purpose_unclassified;    -- nhãn mới chưa ai phân loại
SELECT * FROM billing.unbillable_event;          -- event không có số đo nào
