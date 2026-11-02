"""Chi phí dữ liệu ngoài vào sổ usage: purpose `kb_web`, dịch vụ `search`, giá vendor, quyền ghi cho portal_api.

Giá đóng băng ở đây (26.000 đ/USD, không markup), chèn vào bảng `vendor-vnd-2026-08`.
Dòng cụ thể theo purpose/provider/model thắng dòng wildcard nên tiền hội thoại không đổi.
Qwen tính bậc theo token vào của từng lượt gọi; bậc nằm trong tên model.

Revision ID: 0973_kbweb_billing
Revises: 0972_kb_web_actions
"""

from alembic import op

revision = "0973_kbweb_billing"
down_revision = "0972_kb_web_actions"
branch_labels = None
depends_on = None

PRICE_CODE = "vendor-vnd-2026-08"

PRICES = (
    ("llm", "dashscope", "qwen3.7-flash", "input_tokens", 780, 1_000_000, "$0,03/1M (≤32K token vào)"),
    ("llm", "dashscope", "qwen3.7-flash", "output_tokens", 3380, 1_000_000, "$0,13/1M (≤32K token vào)"),
    ("llm", "dashscope", "qwen3.7-flash>32k", "input_tokens", 2600, 1_000_000, "$0,10/1M (32K–256K)"),
    ("llm", "dashscope", "qwen3.7-flash>32k", "output_tokens", 10400, 1_000_000, "$0,40/1M (32K–256K)"),
    ("llm", "dashscope", "qwen3.7-flash>256k", "input_tokens", 5200, 1_000_000, "$0,20/1M (>256K)"),
    ("llm", "dashscope", "qwen3.7-flash>256k", "output_tokens", 20800, 1_000_000, "$0,80/1M (>256K)"),
    ("llm", "google", "gemini-2.5-flash", "input_tokens", 7800, 1_000_000, "$0,30/1M"),
    ("llm", "google", "gemini-2.5-flash", "output_tokens", 65000, 1_000_000, "$2,50/1M"),
    ("search", "google", "gemini-2.5-flash", "units", 910, 1, "$35/1.000 lượt tra Google"),
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO billing.purpose (code, billable, note) VALUES
          ('kb_web', true, 'dữ liệu ngoài: crawl, gắn thẻ, viết hồ sơ, tra Google')
        ON CONFLICT (code) DO NOTHING;
        INSERT INTO billing.pricing_basis (component, purpose, metric, note) VALUES
          ('search', 'kb_web', 'units', 'số lượt tra Google của dữ liệu ngoài')
        ON CONFLICT DO NOTHING;
        """
    )
    values = ",\n".join(
        f"('{c}', 'kb_web', '{p}', '{m}', '{metric}', {price}::numeric, {per}::bigint, '{note}')"
        for c, p, m, metric, price, per, note in PRICES
    )
    op.execute(
        f"""
        INSERT INTO billing.price_item
               (price_version_id, component, purpose, provider, model, metric, unit_price, per_units, note)
        SELECT pv.id, x.component, x.purpose, x.provider, x.model, x.metric, x.unit_price, x.per_units, x.note
          FROM billing.price_version pv
         CROSS JOIN (VALUES {values}) AS x(component, purpose, provider, model, metric, unit_price, per_units, note)
         WHERE pv.code = '{PRICE_CODE}'
        ON CONFLICT (price_version_id, component, purpose, provider, model, metric) DO NOTHING
        """
    )
    op.execute(
        """
        GRANT INSERT ON billing.usage_events TO portal_api;
        DROP POLICY IF EXISTS tenant_insert ON billing.usage_events;
        CREATE POLICY tenant_insert ON billing.usage_events FOR INSERT TO portal_api
          WITH CHECK (tenant_id = portal.current_tenant());
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS tenant_insert ON billing.usage_events;
        REVOKE INSERT ON billing.usage_events FROM portal_api;
        """
    )
    op.execute(
        f"""
        DELETE FROM billing.price_item pi
         USING billing.price_version pv
         WHERE pi.price_version_id = pv.id AND pv.code = '{PRICE_CODE}' AND pi.purpose = 'kb_web'
           AND NOT EXISTS (SELECT 1 FROM billing.rated_usage r WHERE r.price_item_id = pi.id)
        """
    )
    op.execute(
        """
        DELETE FROM billing.pricing_basis WHERE component = 'search' AND purpose = 'kb_web' AND metric = 'units';
        DELETE FROM billing.purpose WHERE code = 'kb_web';
        """
    )
