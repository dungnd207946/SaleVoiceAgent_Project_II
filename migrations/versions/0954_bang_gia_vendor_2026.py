"""bảng giá VND mới theo giá vendor thực (thay bảng seed `0949`)

VÌ SAO LÀ MIGRATION MỚI CHỨ KHÔNG SỬA `0949`: ba lý do độc lập, mỗi lý do đủ
để loại phương án "sửa file cũ".
  1. `0949` đã nằm trong `alembic_version` của mọi DB đã deploy. Sửa nội dung
     nó KHÔNG làm gì cả trên các DB đó — alembic không chạy lại một revision
     đã áp. Giá mới sẽ chỉ xuất hiện trên DB dựng-từ-đầu, tức là môi trường
     deploy im lặng giữ giá cũ. Đây là lý do quyết định.
  2. Trigger `price_item_bat_bien` (`0943`) bắt `BEFORE UPDATE OR DELETE` và
     RAISE nếu `price_version` đó đã có dòng nào trong `rated_usage`. Một
     migration đi UPDATE thẳng `price_item` của bảng giá seed sẽ chạy XANH ở
     dev (nơi `rated_usage` rỗng) và VỠ ở môi trường đã tính tiền — dạng lỗi
     tệ nhất: chỉ vỡ ở nơi có dữ liệu thật.
  3. Doctrine của chính schema (`0943` mục 3d): "thứ gì đã được viện dẫn thì
     bất biến; muốn đổi giá thì tạo phiên bản MỚI". Giữ bản cũ nguyên vẹn là
     cách duy nhất để `rated_usage` của kỳ đã chốt còn giải thích được — mỗi
     dòng tiền cũ vẫn trỏ về đúng đơn giá đã dùng để sinh ra nó.

CƠ CHẾ PHỦ TENANT LÀ `is_default`, KHÔNG PHẢI `tenant_price_version`: đo trên
DB dev tại thời điểm viết, `billing.tenant_price_version` có 0 dòng, nên
`resolve_price_version(tenant, at)` rơi về `(SELECT id FROM price_version WHERE
is_default)` cho MỌI tenant. Vì vậy migration này phải CHUYỂN cờ mặc định, chứ
không chỉ thêm một bảng giá — thêm mà không chuyển cờ thì giá mới không áp cho
ai. Index `price_version_single_default` là UNIQUE trên `((true)) WHERE
is_default` nên phải HẠ cờ cũ TRƯỚC rồi mới DỰNG cờ mới; hai câu lệnh riêng
trong cùng transaction, không gộp được thành một UPDATE.

TIỀN KỲ ĐÃ CHỐT KHÔNG ĐỔI, nhưng TÍNH LẠI thì đổi: `rated_usage` snapshot cả
`unit_price`/`per_units`/`amount` nên số cũ đứng yên. Ngược lại, chạy lại
`rate_usage()` cho một kỳ QUÁ KHỨ sau migration này sẽ dùng bảng giá MỚI —
`resolve_price_version` fallback về `is_default` không có chiều thời gian.
Chấp nhận được ở đây vì `rated_usage` đang rỗng trên dev và bảng giá `0949`
là giá quy đổi ước lệ, không phải giá đã phát hành cho khách. Ngày nào có kỳ
đã xuất hoá đơn thật, cách đúng là ghim tenant vào bản giá cũ bằng một hàng
`tenant_price_version (tenant, <id bản 0949>, effective_from, effective_to =
mốc cắt)` TRƯỚC khi chuyển cờ — không phải sửa migration này.

TỈ GIÁ 26.000 ₫/USD, KHÔNG MARKUP — cùng tỉ giá `0949` đã dùng, giữ nguyên để
hai bảng giá còn so sánh được với nhau. Mọi con số dưới đây chia hết đúng, không
có làm tròn: chỗ nào USD/1M thì `per_units = 1000000`, và vế `wall_ms` khai theo
GIỜ (`per_units = 3600000` ms) thay vì quy về giây, để 0,12 USD/giờ ra đúng
3.120 ₫ thay vì 0,8666… ₫/giây bị cắt ở numeric(20,10).

⚠️ ĐỔI CƠ SỞ TÍNH TIỀN STT: `0949` thu theo `audio_sec` (giây khách nói) và ghim
`wall_ms = 0`. Bản này ĐẢO LẠI — thu theo `wall_ms` (thời gian stream mở) và
ghim `audio_sec = 0`. Index `price_item_stt_single_basis` (bản `0948`) chỉ cho
nhiều nhất MỘT trong hai vế thời lượng có giá > 0, nên cấu hình này hợp lệ; vế
`text_units` của STT nằm ngoài index đó và CỘNG THÊM, không thay thế.
`test_stt_chi_mot_ve_thoi_luong_co_gia` đã được sửa theo ý định mới — index vẫn
xanh khi đảo vế, nên bài test đó là chỗ duy nhất nói ra ý định này.

Revision ID: 0954_bang_gia_vendor
Revises: 0953_bu_invites_role_id
"""

from alembic import op

revision = "0954_bang_gia_vendor"
down_revision = "0953_bu_invites_role_id"
branch_labels = None
depends_on = None

CODE = "vendor-vnd-2026-08"
"""Khoá tự nhiên của bảng giá này. `test_seed_bang_gia.py` import lại hằng này —
đừng đổi chuỗi mà không sửa test, và đừng đổi trên DB đã chạy migration."""

CODE_CU = "mac-dinh-vnd-2026"
"""Bảng giá seed của `0949` — bị hạ cờ mặc định ở đây, KHÔNG bị xoá và KHÔNG bị
sửa một dòng giá nào (xem docstring: bất biến sau khi đã viện dẫn)."""

_UP = f"""
INSERT INTO billing.price_version (code, name, currency, status, is_default, note, created_by)
VALUES ('{CODE}',
        'Bảng giá vendor (VND)',
        'VND',
        'active',
        false,                      -- cờ mặc định dựng ở bước riêng bên dưới
        'Migration 0954 — giá vendor thực quy đổi 26.000 đ/USD, không markup. '
        'Thay bảng seed 0949. Sửa giá = tạo price_version mới.',
        'migration:0954')
ON CONFLICT (code) DO NOTHING;

INSERT INTO billing.price_item
       (price_version_id, component, purpose, metric, unit_price, per_units, note)
SELECT pv.id, x.component, x.purpose, x.metric, x.unit_price, x.per_units, x.note
  FROM billing.price_version pv
 CROSS JOIN (VALUES
   -- ── LLM: $0,75 / $3,75 / $0,075 / $0,075 mỗi 1M token ───────────────────
   ('llm', '', 'input_tokens',
    19500::numeric, 1000000::bigint,        '19.500 đ/1M token  ($0,75/1M)'),
   ('llm', '', 'output_tokens',
    97500::numeric, 1000000::bigint,        '97.500 đ/1M token  ($3,75/1M)'),
   ('llm', '', 'cache_read_tokens',
    1950::numeric, 1000000::bigint,         '1.950 đ/1M token   ($0,075/1M)'),
   ('llm', '', 'cache_write_tokens',
    1950::numeric, 1000000::bigint,         '1.950 đ/1M token   ($0,075/1M)'),

   -- ── Text: metric là text_units (KÝ TỰ), không phải token ────────────────
   ('embed', '', 'text_units',
    3900::numeric, 1000000::bigint,         '3.900 đ/1M text_units ($0,15/1M)'),
   ('tts', '', 'text_units',
    1300000::numeric, 1000000::bigint,      '1.300.000 đ/1M text_units ($50/1M)'),

   -- ── STT: thu theo wall_ms; audio_sec ghim 0 (đảo so với 0949) ───────────
   ('stt', 'stream', 'wall_ms',
    3120::numeric, 3600000::bigint,         '3.120 đ/giờ stream ($0,12/giờ) — per_units = 1 giờ tính bằng ms'),
   ('stt', 'conversation', 'text_units',
    104000::numeric, 1000000::bigint,       '104.000 đ/1M text_units ($4/1M)'),
   ('stt', 'conversation', 'audio_sec',
    0::numeric, 1::bigint,                  'BUỘC 0: price_item_stt_single_basis cấm cùng >0 với wall_ms'),

   -- ── Self-host / không thu: khai 0 TƯỜNG MINH, không bỏ trống ────────────
   ('vad', '', 'audio_sec',
    0::numeric, 1::bigint,                  'Silero VAD self-host'),
   ('speaker_verify', '', 'audio_sec',
    0::numeric, 1::bigint,                  'embedding giọng nội bộ'),
   ('call', '', 'audio_sec',
    0::numeric, 60::bigint,                 'không thu phí nền tảng thoại ở bản giá này')
 ) AS x(component, purpose, metric, unit_price, per_units, note)
 WHERE pv.code = '{CODE}'
ON CONFLICT (price_version_id, component, purpose, provider, model, metric) DO NOTHING;

-- Chuyển cờ mặc định: HẠ trước, DỰNG sau — index price_version_single_default
-- là UNIQUE nên hai câu lệnh không gộp được.
UPDATE billing.price_version SET is_default = false WHERE is_default AND code <> '{CODE}';
UPDATE billing.price_version SET is_default = true  WHERE code = '{CODE}';

-- `status` chỉ là nhãn vận hành cho UI (xem 0943 mục 2): bản cũ không còn áp
-- cho ai nên hạ về 'inactive'. KHÔNG xoá, KHÔNG sửa dòng giá của nó.
UPDATE billing.price_version SET status = 'inactive' WHERE code = '{CODE_CU}';
"""

_DOWN = f"""
UPDATE billing.price_version SET is_default = false WHERE code = '{CODE}';
UPDATE billing.price_version SET status = 'active', is_default = true WHERE code = '{CODE_CU}';
DELETE FROM billing.price_version WHERE code = '{CODE}';
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    """Trả cờ mặc định về bảng giá `0949` rồi xoá bảng giá này.

    DELETE cascade xuống `price_item` và KÍCH `price_item_bat_bien`, nên nếu bảng
    giá này đã sinh ra tiền trong `rated_usage` thì downgrade RAISE thay vì âm
    thầm bỏ số tiền đã tính mất chỗ dựa. Đó là hành vi ĐÚNG — muốn quay lại giá
    cũ trên một DB đã tính tiền thì chuyển cờ mặc định bằng tay, đừng downgrade.
    """
    op.execute(_DOWN)
