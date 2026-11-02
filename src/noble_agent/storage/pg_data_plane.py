"""SP-E2 Postgres data-plane DAOs — the Odyssey agent WRITE path (contract C4.2).

Writes the 3 agent-owned tables (``conversations`` / ``appointments`` / ``contacts``)
in schema ``tenant_data``. Every row carries ``tenant_id``; the runtime connection is
the per-tenant role when the worker holds a runtime credential from the gateway
(``pool_for_tenant``), the shared ``agent_runtime`` app role as fallback otherwise —
either way pooled and scoped per-transaction via ``tenant_conn``
(``set_config('app.current_tenant', ..., true)``), so RLS
``(tenant_id = current_setting('app.current_tenant', true))`` both filters reads and
rejects a write tagged for another tenant — cross-tenant leakage is DB-impossible
(BR08/BR09), not something these DAOs have to remember to filter.

``db`` is anything with asyncpg's ``execute``/``fetchrow`` coroutine surface — a pool
(acquires per call) or a single connection (tests). The best-effort wrappers below pass
a connection already scoped by ``tenant_conn(pool, tenant_id)`` (never the raw pool) so
every query runs inside the ``set_config``d transaction the RLS policy depends on.
These raise on query error; call sites keep the best-effort/fire-and-forget contract
(Redis is the conversation source of truth; E05 = read paths degrade, never fabricate).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from noble_agent.storage.postgres_client import tenant_conn

logger = logging.getLogger("noble_agent.storage.pg_data_plane")

# Internal history role → transcript role used by the memory renderer.
# Absent key = skip the message (``tool`` rows are plumbing, not dialog).
_TRANSCRIPT_ROLE = {"user": "caller", "assistant": "agent"}


async def _pool_or_none(tenant_id: str):
    """Pool theo tenant (per-tenant role khi có credential), hoặc None khi Postgres
    chưa cấu hình/unreachable — wrapper best-effort no-op thay vì nổ trên hot path.
    Lưu ý: pool per-tenant dựng FAIL (password sai) cũng rơi vào None ở đây — wrapper
    là best-effort; đường đọc bắt buộc (config) thì KHÔNG nuốt kiểu này."""
    try:
        from noble_agent.storage.postgres_client import pool_for_tenant

        return await pool_for_tenant(tenant_id)
    except Exception:
        return None


async def upsert_contact(db, *, tenant_id: str, phone: str, snapshot: str) -> None:
    """Cumulative per-phone profile (the old user snapshot). Upsert by (tenant, phone)."""
    await db.execute(
        "INSERT INTO tenant_data.contacts (tenant_id, phone, snapshot, updated_at) "
        "VALUES ($1, $2, $3, now()) "
        "ON CONFLICT (tenant_id, phone) DO UPDATE SET snapshot = EXCLUDED.snapshot, updated_at = now()",
        tenant_id,
        phone,
        snapshot,
    )


async def get_contact(db, *, tenant_id: str, phone: str) -> dict | None:
    """Read a contact's snapshot + structured profile (bootstrap). None if absent."""
    row = await db.fetchrow(
        "SELECT tenant_id, phone, snapshot, profile, updated_at FROM tenant_data.contacts "
        "WHERE tenant_id = $1 AND phone = $2",
        tenant_id,
        phone,
    )
    return dict(row) if row is not None else None


async def upsert_contact_profile(db, *, tenant_id: str, phone: str, profile: dict, insert_default: dict) -> None:
    """Merge the structured per-phone profile (old ``customers`` collection).

    Shallow jsonb merge (``profile || incoming`` — incoming keys win) so a partial
    call never wipes fields it omits. ``insert_default`` (e.g. ``{"name":"No Name"}``)
    applies ONLY on the first insert, underneath the incoming values — never on an
    update — mirroring the old Mongo ``$setOnInsert``. Leaves ``snapshot`` alone."""
    await db.execute(
        "INSERT INTO tenant_data.contacts (tenant_id, phone, snapshot, profile, updated_at) "
        "VALUES ($1, $2, '', ($4::jsonb || $3::jsonb), now()) "
        "ON CONFLICT (tenant_id, phone) DO UPDATE SET "
        "  profile = tenant_data.contacts.profile || $3::jsonb, updated_at = now()",
        tenant_id,
        phone,
        json.dumps(profile),
        json.dumps(insert_default),
    )


async def record_conversation(
    db,
    *,
    tenant_id: str,
    session_id: str,
    phone: str | None = None,
    customer_name: str | None = None,
    project: str | None = None,
    transferred_to_sales: bool = False,
    running_version: int | None = None,
    summary: str | None = None,
    skill_calls: list | None = None,
    source: str | None = None,
    started_at=None,
    ended_at=None,
    agent_key_id: int | None = None,
) -> int | None:
    """Flattened call record + skill-call log + config version.

    Upsert by (tenant, session). ``source`` is the transport the conversation
    came in on (``voice`` | ``chat``); ``agent_key_id`` is the Portal API key
    the gateway authenticated the connection with (NULL when the conversation
    did not come through the gateway). The per-message transcript lives in
    ``conversation_messages`` (persist_turn_messages) — no call-end
    transcript snapshot is written here.
    """
    row = await db.fetchrow(
        "INSERT INTO tenant_data.conversations "
        "(tenant_id, session_id, phone, customer_name, project, transferred_to_sales, "
        " running_version, summary, skill_calls, source, started_at, ended_at, agent_key_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13) "
        # Merge-upsert: a partial write (call-end summary, then a separate handoff
        # update) must NOT null out fields it omits. NULL/empty incoming preserves
        # the existing value; transferred_to_sales is sticky-true (never un-flag a
        # handoff); skill_calls preserved when incoming is empty.
        "ON CONFLICT (tenant_id, session_id) DO UPDATE SET "
        "  phone = COALESCE(EXCLUDED.phone, conversations.phone), "
        "  customer_name = COALESCE(EXCLUDED.customer_name, conversations.customer_name), "
        "  project = COALESCE(EXCLUDED.project, conversations.project), "
        "  transferred_to_sales = (conversations.transferred_to_sales OR EXCLUDED.transferred_to_sales), "
        "  running_version = COALESCE(EXCLUDED.running_version, conversations.running_version), "
        "  summary = COALESCE(EXCLUDED.summary, conversations.summary), "
        "  skill_calls = CASE WHEN EXCLUDED.skill_calls = '[]'::jsonb "
        "                THEN conversations.skill_calls ELSE EXCLUDED.skill_calls END, "
        "  source = COALESCE(EXCLUDED.source, conversations.source), "
        "  started_at = COALESCE(EXCLUDED.started_at, conversations.started_at), "
        "  ended_at = COALESCE(EXCLUDED.ended_at, conversations.ended_at), "
        "  agent_key_id = COALESCE(EXCLUDED.agent_key_id, conversations.agent_key_id) "
        "RETURNING id",
        tenant_id,
        session_id,
        phone,
        customer_name,
        project,
        transferred_to_sales,
        running_version,
        summary,
        json.dumps(skill_calls or []),
        source or None,
        started_at,
        ended_at,
        agent_key_id,
    )
    return row["id"] if row is not None else None


async def insert_conversation_messages(db, *, tenant_id: str, session_id: str, messages: list[dict]) -> None:
    """Per-message realtime transcript rows — one INSERT batch per turn.

    ``messages`` are pre-shaped rows ``{seq, role, content, created_at, meta}``.
    Idempotent on (tenant, session, seq) via ON CONFLICT DO UPDATE (not DO
    NOTHING): a retried batch rewrites the same rows, and a reset session that
    reuses its session_id overwrites from seq 0 instead of silently dropping
    the new conversation."""
    if not messages:
        return
    await db.executemany(
        "INSERT INTO tenant_data.conversation_messages "
        "(tenant_id, session_id, seq, role, content, created_at, meta) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) "
        "ON CONFLICT (tenant_id, session_id, seq) DO UPDATE SET "
        "  role = EXCLUDED.role, content = EXCLUDED.content, "
        "  created_at = EXCLUDED.created_at, meta = EXCLUDED.meta",
        [
            (
                tenant_id,
                session_id,
                m["seq"],
                m["role"],
                m.get("content") or "",
                m["created_at"],
                json.dumps(m.get("meta") or {}, ensure_ascii=False),
            )
            for m in messages
        ],
    )


async def list_conversation_messages(db, *, tenant_id: str, session_id: str) -> list[dict]:
    """One session's transcript rows ordered by ``seq`` (its index in ``state.history``)."""
    rows = await db.fetch(
        "SELECT role, content FROM tenant_data.conversation_messages "
        "WHERE tenant_id = $1 AND session_id = $2 ORDER BY seq",
        tenant_id,
        session_id,
    )
    return [dict(r) for r in rows]


async def list_conversations_by_phone(db, *, tenant_id: str, phone: str, limit: int = 5) -> list[dict]:
    """Recent conversations for a phone (memory bootstrap), newest first."""
    rows = await db.fetch(
        "SELECT session_id, ended_at FROM tenant_data.conversations "
        "WHERE tenant_id = $1 AND phone = $2 ORDER BY ended_at DESC NULLS LAST, created_at DESC LIMIT $3",
        tenant_id,
        phone,
        limit,
    )
    return [dict(r) for r in rows]


async def upsert_appointment(
    db,
    *,
    tenant_id: str,
    appointment_id: str,
    session_id: str | None = None,
    customer_name: str | None = None,
    phone: str | None = None,
    project_code: str | None = None,
    preferred_date: str | None = None,
    preferred_time: str | None = None,
    status: str = "scheduled",
) -> int | None:
    """Agent-booked viewing, keyed on the agent-minted ``appointment_id`` (APTxxxxx).

    Upsert by (tenant, appointment_id) so a re-book (``modify``) updates the same
    row instead of inserting a duplicate — mirrors the old Mongo
    ``upsert_booking`` idempotency. Returns the row id.
    """
    row = await db.fetchrow(
        "INSERT INTO tenant_data.appointments "
        "(tenant_id, appointment_id, session_id, customer_name, phone, "
        " project_code, preferred_date, preferred_time, status) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        "ON CONFLICT (tenant_id, appointment_id) DO UPDATE SET "
        "  session_id = COALESCE(EXCLUDED.session_id, appointments.session_id), "
        "  customer_name = COALESCE(EXCLUDED.customer_name, appointments.customer_name), "
        "  phone = COALESCE(EXCLUDED.phone, appointments.phone), "
        "  project_code = COALESCE(EXCLUDED.project_code, appointments.project_code), "
        "  preferred_date = COALESCE(EXCLUDED.preferred_date, appointments.preferred_date), "
        "  preferred_time = COALESCE(EXCLUDED.preferred_time, appointments.preferred_time), "
        "  status = EXCLUDED.status, "
        "  updated_at = now() "
        "RETURNING id",
        tenant_id,
        appointment_id,
        session_id,
        customer_name,
        phone,
        project_code,
        preferred_date,
        preferred_time,
        status,
    )
    return row["id"] if row is not None else None


async def get_latest_appointment_by_phone(db, *, tenant_id: str, phone: str) -> dict | None:
    """Most-recent appointment for a phone (call-start profile hint). None if absent."""
    row = await db.fetchrow(
        "SELECT customer_name, project_code FROM tenant_data.appointments "
        "WHERE tenant_id = $1 AND phone = $2 ORDER BY updated_at DESC LIMIT 1",
        tenant_id,
        phone,
    )
    return dict(row) if row is not None else None


async def update_appointment_status(db, *, tenant_id: str, appointment_id: int, status: str) -> bool:
    """Update a viewing's status (human edit / follow-up). True if a row changed."""
    result = await db.execute(
        "UPDATE tenant_data.appointments SET status = $3, updated_at = now() "
        "WHERE tenant_id = $1 AND id = $2",
        tenant_id,
        appointment_id,
        status,
    )
    # asyncpg returns e.g. "UPDATE 1"
    return result.rsplit(" ", 1)[-1] != "0"


async def insert_escalation(
    db,
    *,
    tenant_id: str,
    session_id: str,
    phone: str | None = None,
    customer_name: str | None = None,
    project: str | None = None,
    missing_data_tool: str | None = None,
    summary: str | None = None,
    message_seq: int | None = None,
) -> int | None:
    """One row per `escalate` fire. `status`/`handled_*`/`summary_at` are left to
    their defaults — Portal owns the first three, the summary task owns the last."""
    row = await db.fetchrow(
        "INSERT INTO tenant_data.escalations "
        "(tenant_id, session_id, phone, customer_name, project, missing_data_tool, summary, message_seq) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
        tenant_id,
        session_id,
        phone,
        customer_name,
        project,
        missing_data_tool,
        summary,
        message_seq,
    )
    return row["id"] if row is not None else None


async def update_escalation_summary(db, *, tenant_id: str, escalation_id: int, summary: str) -> None:
    """Replace the INSERT-time placeholder with the LLM text. `summary_at` is
    stamped in the same statement — it is what tells the dashboard the two apart."""
    await db.execute(
        "UPDATE tenant_data.escalations SET summary = $3, summary_at = now() "
        "WHERE tenant_id = $1 AND id = $2",
        tenant_id,
        escalation_id,
        summary,
    )


async def has_escalation(db, *, tenant_id: str, session_id: str) -> bool:
    """True if this session handed off at least once."""
    return bool(
        await db.fetchval(
            "SELECT EXISTS (SELECT 1 FROM tenant_data.escalations WHERE tenant_id = $1 AND session_id = $2)",
            tenant_id,
            session_id,
        )
    )


# ── best-effort call-site wrappers (SP-E2 cutover; Option C pooling) ─────────
# These are what the turn/call-end paths call. They resolve the shared runtime
# pool + the per-request tenant (Plan 1's current_tenant(), NOT settings.tenant_id),
# run the DAO inside a tenant_conn (a txn scoped via set_config so the RLS
# agent_runtime policy binds it), and swallow on any failure (Redis is the
# conversation source of truth; a missing pool = no-op). Mirrors the Mongo
# sink's best-effort contract.


def _tenant_id() -> str:
    from noble_agent.tenant.current import current_tenant

    return current_tenant()


def _agent_key_id() -> int | None:
    """agent_key_id per-connection (gateway auth) — None khi không qua gateway.

    Contextvar giữ string (giá trị đi qua header/stash), nhưng cột
    ``conversations.agent_key_id`` là BIGINT (Portal tạo — id số của
    ``control.agent_keys``) nên convert tại đây, biên ghi PG duy nhất. Giá trị
    không phải số → None + warning, KHÔNG được để lọt string xuống asyncpg:
    DataError sẽ giết cả INSERT và mất luôn row conversations (bug 2026-08-19).
    """
    from noble_agent.tenant.current import current_agent_key_id

    raw = current_agent_key_id()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("agent_key_id không phải số (%r) — ghi NULL", raw)
        return None


async def persist_contact(phone: str, snapshot: str) -> None:
    if not phone:
        return
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return
    try:
        async with tenant_conn(pool, tid) as conn:
            await upsert_contact(conn, tenant_id=tid, phone=phone, snapshot=snapshot)
    except Exception:
        logger.warning("pg persist_contact failed", exc_info=True)


async def read_contact_snapshot(phone: str) -> str:
    """Contact snapshot text for memory bootstrap, or '' (E05: never fabricate)."""
    if not phone:
        return ""
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return ""
    try:
        async with tenant_conn(pool, tid) as conn:
            row = await get_contact(conn, tenant_id=tid, phone=phone)
        return (row or {}).get("snapshot", "") if row else ""
    except Exception:
        logger.warning("pg read_contact_snapshot failed", exc_info=True)
        return ""


async def persist_customer_profile(phone: str, data: dict) -> None:
    """Upsert the structured per-phone profile (old ``customers`` collection) at call end.

    Truthy-merge (only truthy or explicit-bool fields, minus ``_id``/``phone``) so an
    incomplete call never overwrites a name/gender with an empty value. A "No Name"
    display default is applied insert-only. Best-effort — PG absent → no-op."""
    if not phone:
        return
    clean: dict = {}
    for k, v in (data or {}).items():
        if k in ("_id", "phone"):
            continue
        if isinstance(v, bool) or v:
            clean[k] = v
    insert_default = {} if (clean.get("name") or clean.get("full_name")) else {"name": "No Name"}
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return
    try:
        async with tenant_conn(pool, tid) as conn:
            await upsert_contact_profile(
                conn, tenant_id=tid, phone=phone, profile=clean, insert_default=insert_default
            )
    except Exception:
        logger.warning("pg persist_customer_profile failed", exc_info=True)


async def read_customer_profile(phone: str) -> dict:
    """Structured profile dict for call-start bootstrap, or {} (E05: never fabricate).

    asyncpg returns ``jsonb`` as text, so parse it here (tolerating an already-decoded
    dict in case a codec is ever registered)."""
    if not phone:
        return {}
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return {}
    try:
        async with tenant_conn(pool, tid) as conn:
            row = await get_contact(conn, tenant_id=tid, phone=phone)
        if not row:
            return {}
        raw = row.get("profile")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                return {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        logger.warning("pg read_customer_profile failed", exc_info=True)
        return {}


async def persist_appointment(booking: dict, session_id: str) -> None:
    """Write one agent booking to PG (schedule/modify). Best-effort, idempotent
    on ``appointment_id``. Maps the booking dict's ``project`` → PG ``project_code``."""
    appointment_id = booking.get("appointment_id") or ""
    if not appointment_id:
        return
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return
    try:
        async with tenant_conn(pool, tid) as conn:
            await upsert_appointment(
                conn,
                tenant_id=tid,
                appointment_id=appointment_id,
                session_id=session_id or booking.get("session_id") or None,
                customer_name=booking.get("customer_name") or None,
                phone=booking.get("phone") or None,
                project_code=booking.get("project") or None,
                preferred_date=booking.get("preferred_date") or None,
                preferred_time=booking.get("preferred_time") or None,
                status=booking.get("status") or "scheduled",
            )
    except Exception:
        logger.warning("pg persist_appointment failed", exc_info=True)


async def read_latest_booking_hint(phone: str) -> dict:
    """Latest-booking name/project hint for call-start profile bootstrap, or {}.

    Returns ``{"customer_name", "project"}`` (PG ``project_code`` → ``project``)
    to match the shape ``customer_bootstrap`` already consumes."""
    if not phone:
        return {}
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return {}
    try:
        async with tenant_conn(pool, tid) as conn:
            row = await get_latest_appointment_by_phone(conn, tenant_id=tid, phone=phone)
        if not row:
            return {}
        return {"customer_name": row.get("customer_name", ""), "project": row.get("project_code", "")}
    except Exception:
        logger.warning("pg read_latest_booking_hint failed", exc_info=True)
        return {}


def _message_meta(m) -> dict:
    """Optional per-message extensions for the ``meta`` jsonb (agreed format).

    Only non-empty fields are emitted — an absent key means "not applicable"."""
    meta: dict = {}
    if getattr(m, "tool_calls", None):
        meta["tool_calls"] = m.tool_calls
    if getattr(m, "name", None):
        meta["name"] = m.name
    if getattr(m, "tool_call_id", None):
        meta["tool_call_id"] = m.tool_call_id
    return meta


async def persist_turn_messages(session_id: str, *, base_seq: int, messages: list) -> None:
    """Insert one turn's NEW history messages as conversation_messages rows.

    ``messages`` are the ThreadMessages appended this turn (``history[prev:]``);
    ``base_seq`` is the pre-turn cursor, so ``seq`` is the message's absolute
    index in ``state.history`` — stable across turns and idempotent on retry.
    Fired fire-and-forget from the orchestrator AFTER a successful save_all;
    never awaited on the streaming path. Best-effort: PG absent → no-op,
    any error → log + swallow (Redis stays the conversation source of truth)."""
    if not session_id or not messages:
        return
    rows: list[dict] = []
    for i, m in enumerate(messages):
        role = getattr(m, "role", "")
        if role == "system":  # prompt plumbing, not dialog
            continue
        rows.append(
            {
                "seq": base_seq + i,
                "role": role,
                "content": getattr(m, "content", "") or "",
                "created_at": getattr(m, "created_at", None) or datetime.now(UTC),
                "meta": _message_meta(m),
            }
        )
    if not rows:
        return
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return
    try:
        async with tenant_conn(pool, tid) as conn:
            await insert_conversation_messages(conn, tenant_id=tid, session_id=session_id, messages=rows)
    except Exception:
        logger.warning("pg persist_turn_messages failed", exc_info=True)


async def read_session_messages(session_id: str) -> list[dict]:
    """Prior-session transcript for memory bootstrap, as ``[{"role", "content"}]``.

    Roles are mapped to the caller/agent domain the renderer expects
    (``user`` -> ``caller``, ``assistant`` -> ``agent``); ``tool`` rows are skipped
    (plumbing, not dialog -- ``system`` is never written). Best-effort: PG absent
    or any read error -> ``[]`` (E05: degrade, never fabricate).
    """
    if not session_id:
        return []
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return []
    try:
        async with tenant_conn(pool, tid) as conn:
            rows = await list_conversation_messages(conn, tenant_id=tid, session_id=session_id)
    except Exception:
        logger.warning("pg read_session_messages failed", exc_info=True)
        return []
    out: list[dict] = []
    for r in rows:
        mapped = _TRANSCRIPT_ROLE.get(r.get("role", ""))
        if mapped is None:
            continue
        out.append({"role": mapped, "content": r.get("content") or ""})
    return out


async def seed_conversation(
    session_id: str,
    *,
    phone: str | None = None,
    customer_name: str | None = None,
    project: str | None = None,
    source: str | None = None,
    started_at=None,
    running_version: int | None = None,
) -> None:
    """Upsert the PARTIAL flat call record while the conversation is still live.

    Fired fire-and-forget from the orchestrator after every successful turn so the
    ``conversations`` row exists from turn 1 on BOTH transports. Before this, the
    row was only written at session end (voice: ``base_session.stop``; chat: the
    ``/chat`` WS close) — a chat tab left open had no row until it was refreshed.

    Deliberately writes NO ``summary``/``ended_at``: those are call-end fields, and
    ``record_conversation``'s COALESCE merge would let a seeded value shadow the
    real one. Unlike ``persist_conversation`` this does NOT require a phone — a
    phoneless chat still has a conversation worth showing, and phone lands on the
    row via the merge as soon as the agent collects it. Best-effort: PG absent →
    no-op, any error → log + swallow.
    """
    if not session_id:
        return
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return
    try:
        async with tenant_conn(pool, tid) as conn:
            await record_conversation(
                conn,
                tenant_id=tid,
                session_id=session_id,
                phone=phone,
                customer_name=customer_name,
                project=project,
                running_version=running_version,
                source=source,
                started_at=started_at,
                agent_key_id=_agent_key_id(),
            )
    except Exception:
        logger.warning("pg seed_conversation failed", exc_info=True)


async def persist_conversation(
    summary_doc: dict,
    *,
    phone: str,
    session_id: str,
    running_version: int | None = None,
    source: str | None = None,
) -> int | None:
    """Write a call record to PG at call end (merge-upsert by session). Best-effort.

    Maps the generator's summary doc onto the flat ``conversations`` row
    (``project_code`` → ``project``). ``source`` = transport the conversation
    came in on (``voice`` | ``chat``). The transcript is NOT written here — the
    per-message ``conversation_messages`` rows (persist_turn_messages) are the
    transcript. ``skill_calls`` has no live producer today (the old
    ``agent_path`` was always empty), so it is left to the DAO default.
    """
    if not phone or not session_id:
        return None
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return None
    try:
        async with tenant_conn(pool, tid) as conn:
            # The generator hardcodes transferred_to_sales=False, so escalations is
            # the only truthful source.
            da_escalate = await has_escalation(conn, tenant_id=tid, session_id=session_id)
            return await record_conversation(
                conn,
                tenant_id=tid,
                session_id=session_id,
                phone=phone,
                customer_name=summary_doc.get("customer_name") or None,
                project=summary_doc.get("project_code") or None,
                transferred_to_sales=bool(summary_doc.get("transferred_to_sales", False)) or da_escalate,
                running_version=running_version,
                summary=summary_doc.get("summary") or None,
                source=source,
                started_at=summary_doc.get("started_at"),
                ended_at=summary_doc.get("ended_at"),
                agent_key_id=_agent_key_id(),
            )
    except Exception:
        logger.warning("pg persist_conversation failed", exc_info=True)
        return None


async def record_escalation(
    *,
    session_id: str,
    phone: str = "",
    customer_name: str = "",
    project: str = "",
    missing_data_tool: str = "",
    summary: str = "",
    message_seq: int | None = None,
) -> int | None:
    """Write the escalation row, return its id (needed to update the summary later).

    Awaited on the turn path rather than fired-and-forgotten: the row must exist
    before the background summary task can update it, and a caller who hangs up
    right after must not lose the case."""
    if not session_id:
        return None
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return None
    try:
        async with tenant_conn(pool, tid) as conn:
            return await insert_escalation(
                conn,
                tenant_id=tid,
                session_id=session_id,
                phone=phone or None,
                customer_name=customer_name or None,
                project=project or None,
                missing_data_tool=missing_data_tool or None,
                summary=summary or None,
                message_seq=message_seq,
            )
    except Exception:
        logger.warning("pg record_escalation failed", exc_info=True)
        return None


async def save_escalation_summary(escalation_id: int, summary: str) -> None:
    """Called from the background summary task. Empty summary → leave the
    placeholder alone."""
    if not escalation_id or not summary:
        return
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return
    try:
        async with tenant_conn(pool, tid) as conn:
            await update_escalation_summary(conn, tenant_id=tid, escalation_id=escalation_id, summary=summary)
    except Exception:
        logger.warning("pg save_escalation_summary failed", exc_info=True)


async def list_conversation_hints(phone: str, limit: int = 5) -> list[dict]:
    """Recent conversation rows ({session_id, ended_at}) for memory bootstrap, or []."""
    if not phone:
        return []
    tid = _tenant_id()
    pool = await _pool_or_none(tid)
    if pool is None:
        return []
    try:
        async with tenant_conn(pool, tid) as conn:
            return await list_conversations_by_phone(conn, tenant_id=tid, phone=phone, limit=limit)
    except Exception:
        logger.warning("pg list_conversation_hints failed", exc_info=True)
        return []
