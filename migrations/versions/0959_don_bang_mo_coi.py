"""dọn 3 bảng mồ côi + 2 hàm mồ côi phụ thuộc — không code nào chạm tới

BỐI CẢNH: audit thủ công (2026-09-08) rà toàn bộ 47 bảng đang tồn tại, grep
`src/portal` xem còn ai chạm tới không. Hai nhóm dưới đây là 0 kết quả thật —
không router, không service, không repo, không view nào còn đọc/ghi.

`control.field_policy_live` (`0002`) — bảng lõi M1 cho cơ chế "gate cột" theo
policy per-tenant. Consumer DUY NHẤT là view `agent_api.*` (`0005`), và cả
schema đó đã bị DROP ở `0917_bo_agent_api` (2026-08-10). `0400_kb_real_estate`
và `0401_agent_doc_kb` đã ghi rõ quyết định sản phẩm: KB mới không lưu trường
nội bộ nhạy cảm nữa nên không cần gate cột — cơ chế "BỎ HẲN" (`0400:8-11`), chỉ
là chưa ai DROP bảng vì đó là quyết định của "chủ M1" (`0401:34-37` nói thẳng
điều này). Migration này là quyết định đó.

`portal.pol()` / `portal.gated_extras()` (`0005`) — hai hàm SECURITY DEFINER
`LANGUAGE sql` ĐỌC THẲNG `control.field_policy_live` trong thân hàm. Postgres
theo dõi phụ thuộc của hàm `LANGUAGE sql` vào bảng nó tham chiếu (khác
`plpgsql`, thân hàm ở dạng nguồn được parse lúc CREATE), nên `DROP TABLE
control.field_policy_live` một mình sẽ ném "cannot drop table ... because
other objects depend on it" — phải DROP hai hàm này TRƯỚC. Cả hai đã mồ côi từ
`0917` (ghi rõ trong docstring migration đó) và không view/hàm nào khác gọi
chúng (đã grep `src/portal`, `migrations/versions`).

`billing.invoice` + `billing.invoice_line` (`0943`) — tự nhận là "Hoá đơn
(giai đoạn 2)" ngay trong comment tạo bảng, tức schema đặt trước cho roadmap
chưa tới, không phải tính năng đã build rồi bỏ. `grep -rn "invoice"
src/portal` ra 0 kết quả (không router/service/repo nào chạm), và phía
frontend (`routes/_app/billing.tsx`, `TongQuanScreen.tsx`) tự ghi rõ "Portal
chưa thiết kế phần hoá đơn". GRANT DML đã cấp cho `portal_api` từ `0943`
nhưng không endpoint nào từng dùng.

KHÔNG đụng vào: `tenant_data.appointments`/`contacts` (agent `odyssey-agent`
đang ghi dữ liệu thật mỗi ngày qua `schedule_viewing`/`update_customer` —
UNCLEAR, không phải ORPHAN, xem báo cáo audit) và `tenant_data.kb_files`/
`documents` (cả hai ACTIVE, phục vụ hai luồng khác nhau dù tên dễ nhầm).

Revision ID: 0959_don_bang_mo_coi
Revises: 0958_analyze_projects_sql_ro
"""

from alembic import op

revision = "0959_don_bang_mo_coi"
down_revision = "0958_analyze_projects_sql_ro"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Thứ tự bắt buộc: hàm phụ thuộc bảng phải đi trước, con trước cha.
    op.execute("DROP FUNCTION IF EXISTS portal.gated_extras(text, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS portal.pol(text, text)")
    op.execute("DROP TABLE IF EXISTS control.field_policy_live")

    op.execute("DROP TABLE IF EXISTS billing.invoice_line")
    op.execute("DROP TABLE IF EXISTS billing.invoice")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.field_policy_live (
            tenant_id      text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
            entity         text NOT NULL,
            field          text NOT NULL,
            is_core        boolean NOT NULL DEFAULT false,
            agent_readable boolean NOT NULL DEFAULT false,
            filterable     boolean NOT NULL DEFAULT false,
            match_op       text
                           CONSTRAINT field_policy_live_match_op_check
                           CHECK (match_op IS NULL OR match_op IN
                                  ('eq', 'substring', 'gte', 'lte', 'exists', 'contains')),
            label_vi       text NOT NULL DEFAULT '',
            type           text NOT NULL DEFAULT 'text',
            enum_values    text[],
            PRIMARY KEY (tenant_id, entity, field),
            CONSTRAINT field_policy_live_filterable_needs_op
                CHECK (NOT filterable OR match_op IS NOT NULL),
            CONSTRAINT field_policy_live_enum_needs_type
                CHECK (enum_values IS NULL OR type = 'enum')
        )
        """
    )

    op.execute(
        """
        CREATE FUNCTION portal.pol(p_entity text, p_field text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(
                (SELECT agent_readable FROM control.field_policy_live
                  WHERE tenant_id = portal.current_tenant()
                    AND entity = p_entity AND field = p_field),
                false)
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION portal.gated_extras(p_entity text, p_extras jsonb) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
            SELECT coalesce(jsonb_object_agg(e.key, e.value), '{}'::jsonb)
              FROM jsonb_each(coalesce(p_extras, '{}'::jsonb)) AS e
             WHERE EXISTS (
                   SELECT 1 FROM control.field_policy_live f
                    WHERE f.tenant_id = portal.current_tenant()
                      AND f.entity = p_entity
                      AND f.field = e.key
                      AND f.is_core = false
                      AND f.agent_readable
             )
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION portal.pol(text, text) TO agent_all")
    op.execute("GRANT EXECUTE ON FUNCTION portal.gated_extras(text, jsonb) TO agent_all")

    op.execute(
        """
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
        )
        """
    )
    op.execute(
        """
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
          amount      numeric(20,4)  NOT NULL,
          sort_order  int NOT NULL DEFAULT 0
        )
        """
    )
    op.execute("CREATE INDEX invoice_line_invoice_idx ON billing.invoice_line (invoice_id)")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON billing.invoice, billing.invoice_line TO portal_api")

    op.execute("ALTER TABLE billing.invoice ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_all ON billing.invoice")
    op.execute(
        """
        CREATE POLICY tenant_all ON billing.invoice TO portal_api
          USING (tenant_id = portal.current_tenant())
          WITH CHECK (tenant_id = portal.current_tenant())
        """
    )
