"""Bảng giá mới: tra Google của dữ liệu ngoài 364 đ/lượt thay vì 910 đ.

910 đ là giá niêm yết của tra Google trên Gemini 2.5 Flash ($35/1.000 lượt). Tiền thật hiện
gần như 0 (1.500 lượt miễn phí mỗi ngày), nên tính theo giá theo truy vấn của dòng Gemini 3
($14/1.000 truy vấn, 26.000 đ/USD) — mức có căn cứ, gần chi phí thật hơn.

Bảng giá đã sinh tiền thì bất biến (`price_item_bat_bien`), nên đổi giá = bảng giá mới:
chép mọi dòng của bảng đang mặc định, riêng `search` đổi giá, rồi chuyển cờ mặc định.
Các lượt tra đã ghi sổ được định giá lại theo bảng mới — mới có từ `0973`, chưa kỳ nào chốt.

Revision ID: 0975_bang_gia_tra_google
Revises: 0974_kbweb_chu_de_moi
"""

from alembic import op

revision = "0975_bang_gia_tra_google"
down_revision = "0974_kbweb_chu_de_moi"
branch_labels = None
depends_on = None

CODE = "vendor-vnd-2026-10"
CODE_CU = "vendor-vnd-2026-08"

_UP = f"""
INSERT INTO billing.price_version (code, name, currency, status, is_default, note, created_by)
VALUES ('{CODE}', 'Bảng giá vendor (VND)', 'VND', 'active', false,
        'Migration 0975 — như {CODE_CU}, tra Google của dữ liệu ngoài 364 đ/lượt ($14/1.000).',
        'migration:0975')
ON CONFLICT (code) DO NOTHING;

INSERT INTO billing.price_item
       (price_version_id, component, purpose, provider, model, metric, unit_price, per_units, note)
SELECT moi.id, pi.component, pi.purpose, pi.provider, pi.model, pi.metric,
       CASE WHEN pi.component = 'search' THEN 364 ELSE pi.unit_price END,
       pi.per_units,
       CASE WHEN pi.component = 'search' THEN '$14/1.000 truy vấn tra Google' ELSE pi.note END
  FROM billing.price_item pi
  JOIN billing.price_version cu ON cu.id = pi.price_version_id AND cu.code = '{CODE_CU}'
 CROSS JOIN billing.price_version moi
 WHERE moi.code = '{CODE}'
ON CONFLICT (price_version_id, component, purpose, provider, model, metric) DO NOTHING;

UPDATE billing.price_version SET is_default = false WHERE is_default AND code <> '{CODE}';
UPDATE billing.price_version SET is_default = true WHERE code = '{CODE}';
UPDATE billing.price_version SET status = 'inactive' WHERE code = '{CODE_CU}';

SELECT billing.dinh_gia_events(coalesce(array_agg(event_id), '{{}}'))
  FROM billing.usage_events WHERE component = 'search' AND purpose = 'kb_web';
"""

_DOWN = f"""
UPDATE billing.price_version SET is_default = false WHERE code = '{CODE}';
UPDATE billing.price_version SET status = 'active', is_default = true WHERE code = '{CODE_CU}';
SELECT billing.dinh_gia_events(coalesce(array_agg(event_id), '{{}}'))
  FROM billing.usage_events WHERE component = 'search' AND purpose = 'kb_web';
DELETE FROM billing.price_version WHERE code = '{CODE}';
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
