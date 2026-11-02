"""SQL của màn «Dữ liệu ngoài»: kbweb_sources · kbweb_topics · kbweb_schedules · kbweb_limits · hidden/exclusions
+ vài câu đếm trên web_pages và control.jobs. Gọi trong `tenant_conn()`; mọi câu mang `portal.current_tenant()`."""

from datetime import datetime, time

import asyncpg

from portal.modules.kb.web.contracts import JOB_SESSION_PREFIX, KIND_PROBE, KIND_PROJECT, KIND_RUN

_SOURCE_COLS = """id, domain, name, enabled, origin, fetch_mode, kind, rss, sitemap_index, child_hint, news_sitemaps,
    category_pages, article_pattern, category_paths, probe_at, probe_status, probe_note"""
_TOPIC_COLS = "id, code, label, heading, description, keywords, queries, dossier, enabled, origin, position"
_JOB_COLS = f"""id, kind, state, actor, payload, created_at, started_at, finished_at, count, message,
    (SELECT sum(r.amount) FROM billing.rated_usage r JOIN billing.usage_events e ON e.event_id = r.event_id
      WHERE e.tenant_id = portal.current_tenant()
        AND e.session_id = '{JOB_SESSION_PREFIX}' || control.jobs.id) AS cost,
    (SELECT u.name FROM control.users u WHERE u.id = control.jobs.actor) AS actor_name,
    (SELECT p.name FROM tenant_data.projects p
      WHERE p.tenant_id = portal.current_tenant() AND p.project_code = control.jobs.payload->>'project_code'
      ORDER BY p.id LIMIT 1) AS project_name"""


# ─── nguồn ───────────────────────────────────────────────────────────────────


async def list_sources(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""SELECT {_SOURCE_COLS},
                   (SELECT count(*) FROM tenant_data.web_pages w
                     WHERE w.tenant_id = portal.current_tenant() AND w.domain = s.domain AND w.status = 'ok'
                       AND w.fetched_at >= now() - interval '7 days') AS pages_7d
              FROM tenant_data.kbweb_sources s
             WHERE tenant_id = portal.current_tenant()
             ORDER BY origin DESC, id"""
    )


async def get_source(conn: asyncpg.Connection, source_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_SOURCE_COLS} FROM tenant_data.kbweb_sources WHERE tenant_id = portal.current_tenant() AND id = $1",
        source_id,
    )


async def source_by_domain(conn: asyncpg.Connection, domain: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""SELECT {_SOURCE_COLS} FROM tenant_data.kbweb_sources
             WHERE tenant_id = portal.current_tenant() AND domain = $1""",
        domain,
    )


async def insert_source(conn: asyncpg.Connection, *, created_by: str, **f) -> int:
    return await conn.fetchval(
        """INSERT INTO tenant_data.kbweb_sources
               (tenant_id, domain, name, origin, fetch_mode, kind, rss, sitemap_index, news_sitemaps, category_pages,
                article_pattern, probe_at, probe_status, probe_note, created_by)
           VALUES (portal.current_tenant(), $1, $2, 'custom', $3, $4, $5::text[], $6, $7::text[], $8::text[], $9,
                   now(), $10, $11, $12)
           RETURNING id""",
        f["domain"],
        f["name"],
        f["fetch_mode"],
        f["kind"],
        f["rss"],
        f["sitemap_index"],
        f["news_sitemaps"],
        f["category_pages"],
        f["article_pattern"],
        f["probe_status"],
        f["probe_note"],
        created_by,
    )


async def update_source(conn: asyncpg.Connection, source_id: int, *, enabled: bool | None, name: str | None) -> None:
    await conn.execute(
        """UPDATE tenant_data.kbweb_sources
              SET enabled = coalesce($2, enabled), name = coalesce($3, name), updated_at = now()
            WHERE tenant_id = portal.current_tenant() AND id = $1""",
        source_id,
        enabled,
        name,
    )


async def update_probe(conn: asyncpg.Connection, source_id: int, *, fetch_mode: str, status: str, note: str) -> None:
    await conn.execute(
        """UPDATE tenant_data.kbweb_sources
              SET fetch_mode = $2, probe_status = $3, probe_note = $4, probe_at = now(), updated_at = now()
            WHERE tenant_id = portal.current_tenant() AND id = $1""",
        source_id,
        fetch_mode,
        status,
        note,
    )


async def delete_source(conn: asyncpg.Connection, source_id: int) -> None:
    await conn.execute(
        "DELETE FROM tenant_data.kbweb_sources WHERE tenant_id = portal.current_tenant() AND id = $1", source_id
    )


# ─── chủ đề ──────────────────────────────────────────────────────────────────


async def list_topics(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""SELECT {_TOPIC_COLS} FROM tenant_data.kbweb_topics
             WHERE tenant_id = portal.current_tenant() ORDER BY position, id"""
    )


async def get_topic(conn: asyncpg.Connection, topic_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_TOPIC_COLS} FROM tenant_data.kbweb_topics WHERE tenant_id = portal.current_tenant() AND id = $1",
        topic_id,
    )


async def topic_codes(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT code FROM tenant_data.kbweb_topics WHERE tenant_id = portal.current_tenant()")
    return {r["code"] for r in rows}


async def insert_topic(
    conn: asyncpg.Connection,
    *,
    code: str,
    label: str,
    description: str,
    keywords: list[str],
    queries: list[str],
    created_by: str,
) -> int:
    return await conn.fetchval(
        """INSERT INTO tenant_data.kbweb_topics
               (tenant_id, code, label, heading, description, keywords, queries, origin, position, created_by)
           VALUES (portal.current_tenant(), $1, $2, $2, $3, $4::text[], $5::text[], 'custom',
                   (SELECT coalesce(max(position), 0) + 1 FROM tenant_data.kbweb_topics
                     WHERE tenant_id = portal.current_tenant()), $6)
           RETURNING id""",
        code,
        label,
        description,
        keywords,
        queries,
        created_by,
    )


async def update_topic(
    conn: asyncpg.Connection,
    topic_id: int,
    *,
    enabled: bool | None,
    label: str | None,
    description: str | None,
    keywords: list[str] | None,
    queries: list[str] | None,
) -> None:
    await conn.execute(
        """UPDATE tenant_data.kbweb_topics
              SET enabled = coalesce($2, enabled),
                  label = coalesce($3, label),
                  heading = CASE WHEN $3 IS NULL OR origin = 'default' THEN heading ELSE $3 END,
                  description = coalesce($4, description),
                  keywords = coalesce($5::text[], keywords),
                  queries = coalesce($6::text[], queries),
                  updated_at = now()
            WHERE tenant_id = portal.current_tenant() AND id = $1""",
        topic_id,
        enabled,
        label,
        description,
        keywords,
        queries,
    )


async def delete_topic(conn: asyncpg.Connection, topic_id: int) -> None:
    await conn.execute(
        "DELETE FROM tenant_data.kbweb_topics WHERE tenant_id = portal.current_tenant() AND id = $1", topic_id
    )


# ─── lịch · giới hạn ─────────────────────────────────────────────────────────


async def list_schedules(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT mode, enabled, at_time, weekdays, every_months, day_rule, slices, last_run_at, next_run_at
             FROM tenant_data.kbweb_schedules
            WHERE tenant_id = portal.current_tenant()
            ORDER BY array_position(ARRAY['nightly', 'weekly', 'rebuild'], mode)"""
    )


async def upsert_schedule(
    conn: asyncpg.Connection,
    *,
    mode: str,
    enabled: bool,
    at_time: time,
    weekdays: list[int],
    every_months: int | None,
    day_rule: str | None,
    slices: int,
    next_run_at: datetime | None,
) -> None:
    await conn.execute(
        """INSERT INTO tenant_data.kbweb_schedules
               (tenant_id, mode, enabled, at_time, weekdays, every_months, day_rule, slices, next_run_at)
           VALUES (portal.current_tenant(), $1, $2, $3, $4::smallint[], $5, $6, $7, $8)
           ON CONFLICT (tenant_id, mode) DO UPDATE SET
               enabled = EXCLUDED.enabled, at_time = EXCLUDED.at_time, weekdays = EXCLUDED.weekdays,
               every_months = EXCLUDED.every_months, day_rule = EXCLUDED.day_rule, slices = EXCLUDED.slices,
               next_run_at = EXCLUDED.next_run_at, updated_at = now()""",
        mode,
        enabled,
        at_time,
        weekdays,
        every_months,
        day_rule,
        slices,
        next_run_at,
    )


async def get_limits(conn: asyncpg.Connection) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """SELECT grounding_monthly, browser_daily, asked_days FROM tenant_data.kbweb_limits
            WHERE tenant_id = portal.current_tenant()"""
    )


async def upsert_limits(
    conn: asyncpg.Connection, *, grounding_monthly: int, browser_daily: int, asked_days: int
) -> None:
    await conn.execute(
        """INSERT INTO tenant_data.kbweb_limits (tenant_id, grounding_monthly, browser_daily, asked_days)
           VALUES (portal.current_tenant(), $1, $2, $3)
           ON CONFLICT (tenant_id) DO UPDATE SET grounding_monthly = EXCLUDED.grounding_monthly,
               browser_daily = EXCLUDED.browser_daily, asked_days = EXCLUDED.asked_days, updated_at = now()""",
        grounding_monthly,
        browser_daily,
        asked_days,
    )


# ─── mục ẩn · bài loại ───────────────────────────────────────────────────────


async def set_hidden(conn: asyncpg.Connection, project_code: str, heading: str, hidden: bool, by: str) -> None:
    if hidden:
        await conn.execute(
            """INSERT INTO tenant_data.kbweb_hidden_items (tenant_id, project_code, heading, hidden_by)
               VALUES (portal.current_tenant(), $1, $2, $3) ON CONFLICT DO NOTHING""",
            project_code,
            heading,
            by,
        )
    else:
        await conn.execute(
            """DELETE FROM tenant_data.kbweb_hidden_items
                WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND heading = $2""",
            project_code,
            heading,
        )


async def hidden_by_project(conn: asyncpg.Connection) -> dict[str, frozenset[str]]:
    rows = await conn.fetch(
        """SELECT project_code, heading FROM tenant_data.kbweb_hidden_items
            WHERE tenant_id = portal.current_tenant()"""
    )
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(r["project_code"], set()).add(r["heading"])
    return {k: frozenset(v) for k, v in out.items()}


async def set_excluded(conn: asyncpg.Connection, project_code: str, url: str, excluded: bool, by: str) -> None:
    if excluded:
        await conn.execute(
            """INSERT INTO tenant_data.kbweb_page_exclusions (tenant_id, project_code, url, excluded_by)
               VALUES (portal.current_tenant(), $1, $2, $3) ON CONFLICT DO NOTHING""",
            project_code,
            url,
            by,
        )
    else:
        await conn.execute(
            """DELETE FROM tenant_data.kbweb_page_exclusions
                WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND url = $2""",
            project_code,
            url,
        )


# ─── đếm · job ───────────────────────────────────────────────────────────────


async def page_counts(conn: asyncpg.Connection) -> tuple[int, int]:
    r = await conn.fetchrow(
        """SELECT count(*) FILTER (WHERE fetched_at >= now() - interval '7 days') AS d7,
                  count(*) FILTER (WHERE fetched_at >= now() - interval '30 days') AS d30
             FROM tenant_data.web_pages
            WHERE tenant_id = portal.current_tenant() AND status = 'ok'"""
    )
    return int(r["d7"]), int(r["d30"])


async def list_jobs(
    conn: asyncpg.Connection, *, states: list[str] | None = None, limit: int = 50, days: int | None = None
) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""SELECT {_JOB_COLS} FROM control.jobs
             WHERE tenant_id = portal.current_tenant() AND kind = ANY($1::text[])
               AND ($2::text[] IS NULL OR state = ANY($2::text[]))
               AND ($4::int IS NULL OR created_at >= now() - make_interval(days => $4))
             ORDER BY id DESC
             LIMIT $3""",
        [KIND_RUN, KIND_PROJECT, KIND_PROBE],
        states,
        limit,
        days,
    )


async def latest_project_jobs(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Việc hồ sơ MỚI NHẤT của từng dự án (mọi trạng thái) — một câu, không N+1."""
    return await conn.fetch(
        f"""SELECT DISTINCT ON (payload->>'project_code') {_JOB_COLS}
              FROM control.jobs
             WHERE tenant_id = portal.current_tenant() AND kind = $1
             ORDER BY payload->>'project_code', id DESC""",
        KIND_PROJECT,
    )


async def job_by_token(conn: asyncpg.Connection, kind: str, token: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"""SELECT {_JOB_COLS} FROM control.jobs
             WHERE tenant_id = portal.current_tenant() AND kind = $1 AND payload->>'token' = $2
             ORDER BY id DESC LIMIT 1""",
        kind,
        token,
    )


async def get_job(conn: asyncpg.Connection, job_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        f"SELECT {_JOB_COLS} FROM control.jobs WHERE tenant_id = portal.current_tenant() AND id = $1", job_id
    )
