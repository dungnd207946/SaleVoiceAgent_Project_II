"""billing: seed BẢNG GIÁ MẶC ĐỊNH (VND) — portal thôi quản giá trên UI

VÌ SAO SEED CHỨ KHÔNG NHẬP TAY QUA `/pricing`: quyết định 2026-08-21 — portal
này là hệ thống cho user ngoài dùng, họ KHÔNG được đặt giá. Mục nav «Bảng giá»
đã bị ẩn ở FE (`screens.ts` `inNav: false` + `OFF_NAV`), route thì giữ để admin
nền tảng có `X-Platform-Admin-Token` vẫn vào sửa được khi cần. Nghĩa là trên một
DB mới (deploy production lần đầu) sẽ KHÔNG có ai bấm «Tạo bộ giá» nữa —
`alembic upgrade head` phải tự để lại một bảng giá dùng được, nếu không:
`resolve_price_version()` trả NULL → `rate_usage()` không JOIN được
`price_version` → `rated_usage` rỗng → portal hiện `0 ₫` ở KHẮP NƠI mà không
một lỗi nào phát ra. Đó chính là trạng thái của repo trước migration này (đo
2026-08-21: không migration/script/seed nào INSERT `price_version`).

VÌ SAO `is_default` LÀ CƠ CHẾ, KHÔNG PHẢI `tenant_price_version`:
`resolve_price_version(tenant, at)` fallback về `(SELECT id FROM price_version
WHERE is_default)` khi tenant không có hàng nào trong `tenant_price_version`.
Một dòng `is_default` do đó phủ MỌI tenant hiện có VÀ mọi tenant tạo về sau,
không cần gán gì thêm — đúng thứ ta muốn khi không còn ai vận hành màn giá.

⚠️ `is_default` KHÔNG tính cứng `true`: index `price_version_single_default`
(`UNIQUE ((true)) WHERE is_default`) cho nhiều nhất MỘT bảng mặc định toàn hệ.
DB dev nào đã có một bảng mặc định nhập tay thì `INSERT ... is_default = true`
sẽ VỠ migration giữa đường. Nên vế đó là `NOT EXISTS (... WHERE is_default)`:
DB sạch → bảng này thành mặc định; DB đã có mặc định → bảng này vào dạng thường,
migration vẫn xanh, và bảng đang chạy KHÔNG bị tranh chỗ. Kiểm chứng bằng
`test_seed_bang_gia.py::test_ton_trong_mac_dinh_da_co`.

IDEMPOTENT cả hai tầng (`ON CONFLICT DO NOTHING` theo `code`, và theo UNIQUE
`(price_version_id, component, purpose, provider, model, metric)`), nên chạy
lại `upgrade` trên DB đã seed là no-op. An toàn vì trigger `price_item_bat_bien`
chỉ bắt `BEFORE UPDATE OR DELETE`, KHÔNG bắt INSERT — `ON CONFLICT DO NOTHING`
không kích nó dù bảng giá đã sinh ra tiền.

GIÁ: VND, quy đổi từ giá vendor hiện hành ở ~26.000 đ/USD, **KHÔNG markup**
(quyết định 2026-08-21) — portal hiện đúng giá vốn. Đây là giá BLENDED cho
`provider=''`/`model=''` (wildcard): `rate_usage()` xếp theo
`price_item_specificity()` nên ngày nào cần giá riêng cho một model thì INSERT
một dòng hẹp hơn, nó tự thắng, KHÔNG phải sửa file này.

⚠️ ĐẶT `0` TƯỜNG MINH, TUYỆT ĐỐI KHÔNG BỎ TRỐNG DÒNG NÀO. Bỏ trống một cơ sở
= `rate_usage()` không khớp giá = âm thầm miễn phí + `canh_bao.thieu_gia` của
tenant KÊU MÃI (`price_coverage_gap`). 12 dòng dưới đây phủ TRỌN 12 hàng
`billing.pricing_basis` sau `0948` — `test_phu_tron_pricing_basis` canh đúng
điều đó, nên ngày BE thêm một cơ sở tính tiền thì test đỏ, không phải người phát
hiện qua một hoá đơn lệch.

⚠️ `stt`/`stream`/`wall_ms` BUỘC PHẢI LÀ 0: index `price_item_stt_single_basis`
(bản `0948`) chỉ cho nhiều nhất MỘT dòng `stt` có `unit_price > 0` trong nhóm
metric THỜI LƯỢNG (`audio_sec`, `wall_ms`) — hai cách đo cùng một quãng, đặt giá
cả hai là tính tiền STT hai lần. Ta chọn `audio_sec` (giây khách thực nói) vì đó
là cách mọi vendor STT hiện nay ra giá. `stt`/`conversation`/`text_units` nằm
NGOÀI luật đó (vế độc lập, cộng thêm — vendor kiểu Soniox thu hai đồng hồ) nên
được phép > 0; ta vẫn đặt 0 vì vendor đang dùng không thu theo ký tự.

`vad` và `speaker_verify` = 0 vì cả hai đang chạy self-host (Silero VAD /
embedding giọng nội bộ) — chi phí biên vendor thực sự bằng không. Đây là khai
MIỄN PHÍ TƯỜNG MINH, khác hẳn với bỏ trống.

⚠️ SEED GIÁ KHÔNG TỰ SINH RA TIỀN. `rated_usage` chỉ được ghi khi
`python -m portal.cli.dinh_gia_usage` chạy. Xem `deploy/systemd/` (thêm cùng
lần này) — không có timer đó thì portal vẫn hiện 0 ₫ dù bảng giá đã có.

`downgrade()` CỐ Ý không tự gỡ chốt an toàn: DELETE `price_version` cascade
xuống `price_item`, kích trigger `price_item_bat_bien`, và nó RAISE nếu bảng giá
này đã sinh ra hàng nào trong `rated_usage`. Đó là hành vi ĐÚNG (thứ đã được
viện dẫn thì bất biến — lệ của `control.config_versions`), không phải lỗi cần
vá: muốn đổi giá thì tạo `price_version` MỚI.

Revision ID: 0949_seed_bang_gia_mac_dinh
Revises: 0948_billing_text_units
"""

from alembic import op

revision = "0949_seed_bang_gia_mac_dinh"
down_revision = "0948_billing_text_units"
branch_labels = None
depends_on = None

CODE = "mac-dinh-vnd-2026"
"""Khoá tự nhiên của bảng giá seed. `test_seed_bang_gia.py` import hằng này —
đừng đổi chuỗi mà không sửa test, và đừng đổi trên DB đã chạy migration (khoá
này là cách DUY NHẤT để nhận lại đúng bảng giá seed)."""

_UP = f"""
INSERT INTO billing.price_version (code, name, currency, status, is_default, note, created_by)
SELECT '{CODE}',
       'Bảng giá mặc định (VND)',
       'VND',
       'active',
       -- xem docstring: cứng `true` sẽ vỡ index price_version_single_default
       NOT EXISTS (SELECT 1 FROM billing.price_version WHERE is_default),
       'Seed 0949 — giá vendor quy đổi ~26.000 đ/USD, không markup. '
       'Portal không cho user đặt giá; sửa giá = tạo price_version mới.',
       'migration:0949'
ON CONFLICT (code) DO NOTHING;

INSERT INTO billing.price_item
       (price_version_id, component, purpose, metric, unit_price, per_units, note)
SELECT pv.id, x.component, x.purpose, x.metric, x.unit_price, x.per_units, x.note
  FROM billing.price_version pv
 CROSS JOIN (VALUES
   -- ── LLM: blended theo lớp Sonnet ($3 / $15 / $3,75 / $0,30 mỗi 1M token) ──
   ('llm', '', 'input_tokens',
    78000::numeric, 1000000::bigint,        '78.000 đ/1M token  (~$3/1M)'),
   ('llm', '', 'output_tokens',
    390000::numeric, 1000000::bigint,       '390.000 đ/1M token (~$15/1M)'),
   ('llm', '', 'cache_write_tokens',
    97500::numeric, 1000000::bigint,        '97.500 đ/1M token  (~$3,75/1M)'),
   ('llm', '', 'cache_read_tokens',
    7800::numeric, 1000000::bigint,         '7.800 đ/1M token   (~$0,30/1M)'),

   -- ── Text: metric là KÝ TỰ (text_units), không phải token ─────────────────
   ('embed', '', 'text_units',
    0.00013::numeric, 1::bigint,            '130 đ/1M ký tự (~$0,02/1M token embed)'),
   ('tts', '', 'text_units',
    0.39::numeric, 1::bigint,               '390.000 đ/1M ký tự (~$15/1M chars)'),

   -- ── STT: CHỌN audio_sec, hai vế thời lượng còn lại phải là 0 ─────────────
   ('stt', 'conversation', 'audio_sec',
    2.6::numeric, 1::bigint,                '2,6 đ/giây (~$0,006/phút)'),
   ('stt', 'conversation', 'text_units',
    0::numeric, 1::bigint,                  'vendor hiện dùng KHÔNG thu theo ký tự — khai 0 tường minh'),
   ('stt', 'stream', 'wall_ms',
    0::numeric, 60000::bigint,              'BUỘC 0: price_item_stt_single_basis cấm cùng >0 với audio_sec'),

   -- ── Self-host: chi phí biên vendor = 0, khai MIỄN PHÍ tường minh ─────────
   ('vad', '', 'audio_sec',
    0::numeric, 1::bigint,                  'Silero VAD self-host'),
   ('speaker_verify', '', 'audio_sec',
    0::numeric, 1::bigint,                  'embedding giọng nội bộ'),

   -- ── Telephony: per_units = 60 vì đơn vị nguồn là GIÂY, giá ra theo PHÚT ──
   ('call', '', 'audio_sec',
    600::numeric, 60::bigint,               '600 đ/phút — phí nền tảng thoại VN')
 ) AS x(component, purpose, metric, unit_price, per_units, note)
 WHERE pv.code = '{CODE}'
ON CONFLICT (price_version_id, component, purpose, provider, model, metric) DO NOTHING;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    # Cascade xuống price_item kích `price_item_bat_bien` và RAISE nếu bảng giá
    # đã sinh ra tiền — cố ý, xem docstring. Không thêm guard riêng: thông điệp
    # của trigger đã nói đúng việc phải làm (tạo price_version mới).
    op.execute(f"DELETE FROM billing.price_version WHERE code = '{CODE}';")
