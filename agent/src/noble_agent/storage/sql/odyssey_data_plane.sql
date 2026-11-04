-- SP-E Odyssey data plane (contract C4). Applied ONCE by `noble-tenant pg-apply-schema`
-- (admin DSN). Shared schema + per-row tenant isolation via RLS — DB-enforced (BR08/BR09).
-- Two PERMISSIVE policies per table: `tenant_isolation` (keyed on the connecting ROLE
-- name = tenant_id, for Portal/admin per-tenant login roles — current_user cannot be
-- spoofed in-session) and `agent_runtime` (keyed on the per-transaction GUC
-- `app.current_tenant`, for the shared runtime app role used under Option C pooling).
-- Idempotent: safe to re-run. Per-tenant ROLE + GRANTs are created by provisioning, not here.

CREATE SCHEMA IF NOT EXISTS tenant_data;

-- ── conversations ──────────────────────────────────────────────────────────
-- Flattened call record (self-carries customer/project/handoff so the list view
-- needs no join) + skill-call log (name/params/result) + the config version the
-- agent served (BR: running_version pointer). Carries phone for NĐ13 delete-by-phone.
CREATE TABLE IF NOT EXISTS tenant_data.conversations (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id           text        NOT NULL,
    session_id          text        NOT NULL,
    phone               text,
    customer_name       text,
    project             text,
    transferred_to_sales boolean     NOT NULL DEFAULT false,
    running_version     integer,
    summary             text,
    skill_calls         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    source              text,
    started_at          timestamptz,
    ended_at            timestamptz,
    agent_key_id        bigint,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, session_id)
);
-- Transport the conversation came in on: 'voice' | 'chat'. Added later; idempotent.
ALTER TABLE tenant_data.conversations ADD COLUMN IF NOT EXISTS source text;
-- Portal API key the gateway authenticated the connection with (runtime-credentials
-- response field, 2026-08-19). BIGINT to match the live column Portal already created
-- (numeric id of control.agent_keys). NULL = did not come through the gateway. Idempotent.
ALTER TABLE tenant_data.conversations ADD COLUMN IF NOT EXISTS agent_key_id bigint;
CREATE INDEX IF NOT EXISTS conversations_tenant_phone_idx ON tenant_data.conversations (tenant_id, phone);
CREATE INDEX IF NOT EXISTS conversations_tenant_created_idx ON tenant_data.conversations (tenant_id, created_at DESC);

-- ── appointments ───────────────────────────────────────────────────────────
-- Agent-booked AND human-edited viewings share ONE table (C4.2). `appointment_id`
-- is the agent-minted business key (APTxxxxx) — the idempotency key so a re-book
-- (modify) upserts the same row instead of duplicating it; UNIQUE per tenant.
CREATE TABLE IF NOT EXISTS tenant_data.appointments (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id       text        NOT NULL,
    appointment_id  text,
    session_id      text,
    customer_name   text,
    phone           text,
    project_code    text,
    preferred_date  text,
    preferred_time  text,
    status          text        NOT NULL DEFAULT 'scheduled',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, appointment_id)
);
CREATE INDEX IF NOT EXISTS appointments_tenant_phone_idx ON tenant_data.appointments (tenant_id, phone);
-- Back-compat for an already-applied schema (idempotent add of the business key).
ALTER TABLE tenant_data.appointments ADD COLUMN IF NOT EXISTS appointment_id text;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'appointments_tenant_id_appointment_id_key'
    ) THEN
        ALTER TABLE tenant_data.appointments
            ADD CONSTRAINT appointments_tenant_id_appointment_id_key UNIQUE (tenant_id, appointment_id);
    END IF;
END $$;

-- ── contacts ───────────────────────────────────────────────────────────────
-- One row per phone. Carries both the cumulative free-text ``snapshot`` (the old
-- "user snapshot") AND the structured ``profile`` jsonb (the old ``customers``
-- collection: name/gender/project_interest/budget/…). The two are upserted
-- independently (snapshot vs profile column) so neither clobbers the other.
CREATE TABLE IF NOT EXISTS tenant_data.contacts (
    tenant_id   text        NOT NULL,
    phone       text        NOT NULL,
    snapshot    text        NOT NULL DEFAULT '',
    profile     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, phone)
);
-- Back-compat for an already-applied schema (idempotent add).
ALTER TABLE tenant_data.contacts ADD COLUMN IF NOT EXISTS profile jsonb NOT NULL DEFAULT '{}'::jsonb;

-- ── conversation_messages ──────────────────────────────────────────────────
-- Per-message realtime transcript: one row per turn message, INSERT-batch per
-- turn (fire-and-forget off the streaming path). This is THE transcript —
-- `conversations` carries no call-end transcript snapshot.
-- Core format {seq, role, content, created_at}; optional extensions
-- (tool_calls / name / tool_call_id / latency ...) live in `meta`.
-- PK (tenant, session, seq) doubles as the ordered-read index and the
-- idempotency key (writes are ON CONFLICT DO UPDATE, so a retry rewrites and
-- a reset session that reuses its session_id overwrites from seq 0).
CREATE TABLE IF NOT EXISTS tenant_data.conversation_messages (
    tenant_id   text        NOT NULL,
    session_id  text        NOT NULL,
    seq         integer     NOT NULL,
    role        text        NOT NULL,
    content     text        NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL,
    meta        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, session_id, seq)
);

-- ── escalations ────────────────────────────────────────────────────────────
-- One row per `escalate` fire (event log). Self-carries phone/name/project so
-- the sale inbox needs no join. `missing_data_tool` empty = agent handed off,
-- set = that tool had no data and the dispatcher escalated. `summary_at` NULL =
-- `summary` is still the INSERT-time placeholder. `status`/`handled_*` = Portal-owned.
CREATE TABLE IF NOT EXISTS tenant_data.escalations (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id         text        NOT NULL,
    session_id        text        NOT NULL,
    phone             text,
    customer_name     text,
    project           text,
    missing_data_tool text,
    summary           text,
    summary_at        timestamptz,
    message_seq       integer,
    status            text        NOT NULL DEFAULT 'new',
    handled_by        text,
    handled_at        timestamptz,
    handled_note      text,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS escalations_tenant_created_idx ON tenant_data.escalations (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS escalations_tenant_status_idx  ON tenant_data.escalations (tenant_id, status);
CREATE INDEX IF NOT EXISTS escalations_tenant_session_idx ON tenant_data.escalations (tenant_id, session_id);

-- ── RLS: isolation keyed on the connecting role (= tenant_id) ────────────────
-- FORCE so even a table owner is filtered. `tenant_isolation` uses current_user,
-- which a per-tenant login role cannot change to another role's name. A second
-- `agent_runtime` policy scopes the shared runtime app role via the per-transaction
-- GUC `app.current_tenant` (current_setting(..., true), fail-closed when unset).
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['conversations','appointments','contacts','conversation_messages','escalations'] LOOP
        EXECUTE format('ALTER TABLE tenant_data.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE tenant_data.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON tenant_data.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON tenant_data.%I '
            'USING (tenant_id = current_user) WITH CHECK (tenant_id = current_user)', t);
        EXECUTE format('DROP POLICY IF EXISTS agent_runtime ON tenant_data.%I', t);
        EXECUTE format(
            'CREATE POLICY agent_runtime ON tenant_data.%I '
            'USING (tenant_id = current_setting(''app.current_tenant'', true)) '
            'WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true))', t);
    END LOOP;
END $$;

-- ── Re-GRANT: `GRANT ON ALL TABLES` is a snapshot, not a standing privilege ──
-- Roles provisioned before a new table exists have no rights on it, and
-- `provision()` refuses to re-run for an existing role. Runtime connects as the
-- per-tenant role (`pool_for_tenant`) and every data-plane wrapper swallows
-- errors, so a missing GRANT loses rows silently. Re-grant every role that
-- already holds USAGE on the schema (= tenant roles + the shared app role).
DO $$
DECLARE r text;
BEGIN
    FOR r IN SELECT rolname FROM pg_roles
             WHERE rolcanlogin AND NOT rolsuper
               AND has_schema_privilege(rolname, 'tenant_data', 'USAGE')
    LOOP
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA tenant_data TO %I', r);
    END LOOP;
END $$;
