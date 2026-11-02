"""schema `billing` + `usage_events` + 2 view tổng hợp — đưa sổ ghi usage vào migration

VẤN ĐỀ NÓ GIẢI: schema `billing` ĐÃ TỒN TẠI trên DB dev (đo 2026-08-19: 65 hàng
trong `billing.usage_events`) nhưng KHÔNG có migration nào tạo ra nó — nó được
dựng tay bằng SQL rời theo `docs/build_module_usage&billing/agent-postgres-billing-write-contract.md`.
Hệ quả: DB test/CI (dựng từ `alembic upgrade head`) KHÔNG có schema này, nên mọi
bài test chạm bề mặt usage đều vỡ, và không ai đọc được cấu trúc bảng từ repo.
Migration này chép nguyên trạng DDL đang chạy vào cây migration.

⚠️ TOÀN BỘ DDL Ở ĐÂY LÀ IDEMPOTENT — CỐ Ý, KHÔNG PHẢI THÓI QUEN.
Trên DB dev bảng đã có kèm dữ liệu thật. `CREATE TABLE` trần sẽ vỡ ở đó, còn
`DROP` rồi tạo lại thì mất 65 hàng. Nên: `IF NOT EXISTS` cho schema/bảng/index,
`OR REPLACE` cho view, `DROP POLICY IF EXISTS` trước `CREATE POLICY`. Trên DB
trắng (CI, test) nó dựng đủ; trên DB dev nó là no-op và không đụng dữ liệu.
ĐIỀU KIỆN ĐỂ AN TOÀN: DDL dưới đây được chép từ `pg_dump -n billing` của chính
DB dev, đã đối chiếu từng cột / default / tên constraint — không có drift để
`IF NOT EXISTS` che giấu.

`tenant_id text NOT NULL` KHÔNG FK VỀ `control.tenants` — chép đúng bản đang
chạy, không phải bỏ sót. Đây là sổ ghi (ledger) tính tiền: xoá một workspace
không được phép xoá theo lịch sử usage của nó, mà `ON DELETE CASCADE` (khuôn của
`tenant_data.*`) thì làm đúng việc đó. Cách ly tenant ở đây do RLS lo, không do FK.

VÌ SAO KHÔNG DÙNG `control.enforce_tenant_isolation()` NHƯ `tenant_data.*`: hàm
đó bật RLS **FORCE** + policy `tenant_isolation` + `GRANT` cho `portal_api`, tức
khuôn "Portal ghi hộ". Ở đây người ghi là AGENT, tự INSERT bằng role kế thừa
`agent_all`, và RLS phải là ENABLE (không FORCE) để `portal_migrator` — chủ bảng
— còn đọc được toàn bộ cho việc đối soát. Hai policy keyed on
`portal.current_tenant()` (`0001`) làm đúng phần cách ly.

`agent_all` ĐƯỢC CẢ `SELECT` LẪN `INSERT` — lệch với §5 của contract (chỉ INSERT).
Chép theo DB đang chạy vì policy `agent_read` (§6 của chính contract đó) vô nghĩa
nếu không có GRANT SELECT đi kèm; agent cần đọc lại usage của chính nó. Policy
chặn nó nhìn sang tenant khác.

KHÔNG `GRANT USAGE ON SEQUENCE`: `event_id` là identity column, quyền ghi đã ngụ
ý qua `INSERT` trên bảng — khác `bigserial` (xem `0905`).

HAI VIEW KHÔNG CÓ GRANT NÀO — chép đúng bản đang chạy. Nghĩa là hôm nay chỉ
`portal_migrator` đọc được; `portal_api` và `agent_all` KHÔNG. Màn hình usage của
Portal khi làm sẽ cần một migration cấp `GRANT SELECT ... TO portal_api` riêng.
Cố ý không cấp trước ở đây: cấp quyền là quyết định an ninh, không phải phần của
việc chép nguyên trạng.

Revision ID: 0942_billing_usage_events
Revises: 0941_bo_deployments
"""

from alembic import op

revision = "0942_billing_usage_events"
down_revision = "0941_bo_deployments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Schema ────────────────────────────────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS billing")

    # ── 2. Bảng sổ ghi ───────────────────────────────────────────────────────
    # UNIQUE `usage_events_idem` khai INLINE (không `ALTER TABLE ADD CONSTRAINT`
    # rời) để nó đi kèm `IF NOT EXISTS` của CREATE TABLE — `ADD CONSTRAINT`
    # không có dạng `IF NOT EXISTS` và sẽ vỡ trên DB dev.
    #
    # Bộ khoá chống ghi trùng = (tenant, session, seq, component, purpose,
    # provider, model): agent retry một lượt gửi thì INSERT thứ hai đụng
    # constraint này thay vì cộng đôi tiền.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS billing.usage_events (
            event_id           bigint GENERATED ALWAYS AS IDENTITY,
            tenant_id          text NOT NULL,
            session_id         text NOT NULL,
            channel            text NOT NULL,
            seq                integer NOT NULL,
            turn_idx           integer,
            component          text NOT NULL,
            purpose            text NOT NULL DEFAULT 'conversation',
            provider           text NOT NULL DEFAULT '',
            model              text NOT NULL DEFAULT '',
            input_tokens       bigint NOT NULL DEFAULT 0,
            output_tokens      bigint NOT NULL DEFAULT 0,
            cache_write_tokens bigint NOT NULL DEFAULT 0,
            cache_read_tokens  bigint NOT NULL DEFAULT 0,
            audio_sec          double precision NOT NULL DEFAULT 0,
            wall_ms            double precision NOT NULL DEFAULT 0,
            units              bigint NOT NULL DEFAULT 0,
            exact              boolean NOT NULL DEFAULT true,
            occurred_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT usage_events_pkey PRIMARY KEY (event_id),
            CONSTRAINT usage_events_idem UNIQUE
                (tenant_id, session_id, seq, component, purpose, provider, model)
        )
        """
    )

    # ── 3. Chỉ mục ───────────────────────────────────────────────────────────
    # `tenant_time` phục vụ tổng hợp theo tháng (view §5); `session` phục vụ tra
    # một phiên cụ thể. Cả hai dẫn đầu bằng `tenant_id` để RLS lọc trên index.
    op.execute("CREATE INDEX IF NOT EXISTS usage_events_tenant_time ON billing.usage_events (tenant_id, occurred_at)")
    op.execute("CREATE INDEX IF NOT EXISTS usage_events_session ON billing.usage_events (tenant_id, session_id)")

    # ── 4. RLS: ENABLE (KHÔNG force) + 2 policy ──────────────────────────────
    # `DROP ... IF EXISTS` trước `CREATE` = idempotent mà vẫn tất định: chạy lại
    # thì policy được ghi đè bằng đúng định nghĩa dưới đây, không phải bỏ qua âm
    # thầm một policy đã lệch.
    op.execute("ALTER TABLE billing.usage_events ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS agent_insert ON billing.usage_events")
    op.execute(
        """
        CREATE POLICY agent_insert ON billing.usage_events
            FOR INSERT TO agent_all
            WITH CHECK (tenant_id = portal.current_tenant())
        """
    )
    op.execute("DROP POLICY IF EXISTS agent_read ON billing.usage_events")
    op.execute(
        """
        CREATE POLICY agent_read ON billing.usage_events
            FOR SELECT TO agent_all
            USING (tenant_id = portal.current_tenant())
        """
    )

    # ── 5. Quyền cho vai agent dùng chung (`0901`) ───────────────────────────
    op.execute("GRANT USAGE ON SCHEMA billing TO agent_all")
    op.execute("GRANT SELECT, INSERT ON billing.usage_events TO agent_all")

    # ── 6. Hai view tổng hợp ────────────────────────────────────────────────
    # ⚠️ VIEW KHÔNG CÓ `security_invoker` ⇒ chúng chạy bằng quyền CHỦ SỞ HỮU
    # (`portal_migrator`) và BỎ QUA RLS của bảng dưới. Đó là lý do §5 ở trên cố ý
    # không cấp SELECT trên view cho ai: cấp cho `agent_all` là phơi sổ của MỌI
    # tenant. Ai cần đọc view phải kèm quyết định về cách ly, ở migration riêng.
    op.execute(
        """
        CREATE OR REPLACE VIEW billing.usage_by_session AS
        SELECT tenant_id,
               session_id,
               channel,
               min(occurred_at)                                          AS started_at,
               max(occurred_at)                                          AS last_event_at,
               sum(input_tokens)                                         AS input_tokens,
               sum(output_tokens)                                        AS output_tokens,
               sum(cache_write_tokens)                                   AS cache_write_tokens,
               sum(cache_read_tokens)                                    AS cache_read_tokens,
               sum(audio_sec) FILTER (WHERE component = 'stt')           AS stt_sec,
               sum(audio_sec) FILTER (WHERE component = 'tts')           AS tts_sec,
               sum(audio_sec) FILTER (WHERE component = 'vad')           AS vad_sec,
               sum(audio_sec) FILTER (WHERE component = 'speaker_verify') AS speaker_sec,
               sum(audio_sec) FILTER (WHERE component = 'call')          AS call_sec,
               bool_and(exact)                                           AS exact
          FROM billing.usage_events
         GROUP BY tenant_id, session_id, channel
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW billing.usage_by_tenant_month AS
        SELECT tenant_id,
               date_trunc('month', occurred_at) AS month,
               component,
               purpose,
               provider,
               model,
               sum(input_tokens)       AS input_tokens,
               sum(output_tokens)      AS output_tokens,
               sum(cache_write_tokens) AS cache_write_tokens,
               sum(cache_read_tokens)  AS cache_read_tokens,
               sum(audio_sec)          AS audio_sec,
               sum(units)              AS units,
               count(*)                AS events,
               bool_and(exact)         AS exact
          FROM billing.usage_events
         GROUP BY tenant_id, date_trunc('month', occurred_at),
                  component, purpose, provider, model
        """
    )


def downgrade() -> None:
    # ⚠️ MẤT DỮ LIỆU: sổ ghi usage đi cùng schema. Không có đường giữ lại — bảng
    # này không có bản sao ở schema khác. `CASCADE` cuốn theo 2 view + sequence
    # identity + 2 policy.
    op.execute("DROP SCHEMA IF EXISTS billing CASCADE")
