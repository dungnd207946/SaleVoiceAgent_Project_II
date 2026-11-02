"""SQL trên tenant_data.web_pages — gọi trong `tenant_conn()`; mọi câu mang vị từ `portal.current_tenant()`."""

from datetime import datetime

import asyncpg

from portal.modules.kb.web.contracts import Page
from portal.modules.kb.web.locate import place_labels
from portal.modules.kb.web.normalize import project_labels, same_project, strip_accents, tag_projects

KEEP_DAYS = 730
"""Hạn giữ bài `ok` (theo ngày đăng) — cũng là ngưỡng bỏ bài quá cũ trước khi gắn nhãn."""

MIN_NEIGHBOR_PAGES = 2

# Cùng luật với `normalize.project_matches`: đúng tên, hoặc tên + đuôi không mở đầu bằng chữ số.
# `starts_with` thay cho LIKE nên `%`/`_` trong tên là ký tự thường.
_VARIANT = "({p} = {q} OR (starts_with({p}, {q} || ' ') AND substr({p}, length({q}) + 2, 1) !~ '[0-9]'))"


def match_names(values) -> list[str]:
    """Tên dự án dạng so khớp của SQL `_MATCHES_PROJECT`: chuẩn hoá rồi bỏ dấu."""
    return list(dict.fromkeys(strip_accents(n) for n in project_labels(values)))


_ACCENTED = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
# nhãn khớp tên (hoặc biến thể có đuôi), trừ khi nó thuộc một dự án CỤ THỂ HƠN trong `others`; so KHÔNG dấu
# ở cả hai phía (`names`/`others` truyền vào đã qua `match_names`)
_MATCHES_PROJECT = (
    f"EXISTS (SELECT 1 FROM (SELECT translate(x, '{_ACCENTED}', '{strip_accents(_ACCENTED)}') AS p"
    " FROM unnest(projects) AS x) AS t, unnest({names}::text[]) AS q WHERE "
    + _VARIANT.format(p="p", q="q")
    + " AND NOT EXISTS (SELECT 1 FROM unnest({others}::text[]) AS o WHERE "
    + _VARIANT.format(p="p", q="o")
    + "))"
)

_COLS = "url, domain, title, published_at, fetched_at, coalesce(content_text, '') AS content_text, projects, location"


def _page(r: asyncpg.Record) -> Page:
    return Page(
        url=r["url"],
        domain=r["domain"],
        title=r["title"],
        published_at=r["published_at"],
        fetched_at=r["fetched_at"],
        content_text=r["content_text"],
        projects=tuple(r["projects"]),
        location=tuple(r["location"]),
    )


async def known_urls(conn: asyncpg.Connection, urls: list[str]) -> set[str]:
    if not urls:
        return set()
    # fetch_failed không tính là "đã biết": lỗi mạng thoáng qua không được làm mất bài vĩnh viễn
    rows = await conn.fetch(
        """SELECT url FROM tenant_data.web_pages
            WHERE tenant_id = portal.current_tenant() AND url = ANY($1::text[]) AND status <> 'fetch_failed'""",
        urls,
    )
    return {r["url"] for r in rows}


async def stored_hashes(conn: asyncpg.Connection, urls: list[str]) -> dict[str, str]:
    if not urls:
        return {}
    rows = await conn.fetch(
        """SELECT url, content_hash FROM tenant_data.web_pages
            WHERE tenant_id = portal.current_tenant() AND url = ANY($1::text[])""",
        urls,
    )
    return {r["url"]: r["content_hash"] for r in rows}


async def mark_checked(conn: asyncpg.Connection, url: str) -> None:
    await conn.execute(
        """UPDATE tenant_data.web_pages SET last_checked_at = clock_timestamp()
            WHERE tenant_id = portal.current_tenant() AND url = $1""",
        url,
    )


async def hash_taken(conn: asyncpg.Connection, content_hash: str, url: str) -> bool:
    if not content_hash:
        return False
    return bool(
        await conn.fetchval(
            """SELECT 1 FROM tenant_data.web_pages
                WHERE tenant_id = portal.current_tenant()
                  AND content_hash = $1 AND url <> $2 AND status = 'ok' LIMIT 1""",
            content_hash,
            url,
        )
    )


async def save_page(
    conn: asyncpg.Connection,
    *,
    url: str,
    source_url: str,
    domain: str,
    title: str,
    published_at: datetime | None,
    content_text: str | None,
    content_hash: str,
    found_via: str,
    status: str,
    projects: list[str],
    location: list[str],
) -> None:
    """Upsert theo `url`. Provenance (`domain`, `source_url`, `found_via`) ĐÔNG CỨNG ở lần
    ghi ĐẦU TIÊN — cố ý không nằm trong `DO UPDATE SET`, vì đó là "được tìm thấy thế nào",
    một sự kiện đã xảy ra và không đổi theo lần crawl lại. Các trường còn lại (nội dung,
    phân loại, trạng thái) bị THAY bằng giá trị mới mỗi lần gọi.

    `fetched_at` chỉ nhích khi nội dung THẬT SỰ đổi (content_hash khác) — nó là mốc
    "lần cuối nội dung thay đổi", còn `last_checked_at` là "lần cuối crawl chạm tới",
    luôn cập nhật để `living_due()` biết bài đã được kiểm gần đây. Mốc lấy `clock_timestamp()`
    (giờ thật) chứ không `now()` (giờ bắt đầu giao dịch): nhiều lượt lưu trong một `tenant_conn`
    vẫn phân biệt được trước/sau.

    `location` lưu ở dạng `place_labels`, `projects` ở dạng `tag_projects` (`project_labels` bỏ hạ
    tầng/tiện ích) — cùng dạng với payload Qdrant và với nhãn đem đi so.
    """
    await conn.execute(
        """INSERT INTO tenant_data.web_pages AS w
               (tenant_id, url, source_url, domain, title, published_at, content_text, content_hash,
                found_via, status, projects, location)
           VALUES (portal.current_tenant(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::text[], $11::text[])
           ON CONFLICT (tenant_id, url) DO UPDATE SET
               title = EXCLUDED.title,
               published_at = coalesce(EXCLUDED.published_at, w.published_at),
               fetched_at = CASE WHEN w.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                                 THEN clock_timestamp() ELSE w.fetched_at END,
               last_checked_at = clock_timestamp(),
               content_text = EXCLUDED.content_text,
               content_hash = EXCLUDED.content_hash,
               status = EXCLUDED.status,
               projects = EXCLUDED.projects,
               location = EXCLUDED.location""",
        url,
        source_url,
        domain,
        title,
        published_at,
        content_text,
        content_hash,
        found_via,
        status,
        list(tag_projects(projects)),
        list(place_labels(location)),
    )


async def pages_for(
    conn: asyncpg.Connection,
    *,
    projects: list[str],
    location: list[str],
    since: datetime | None = None,
    limit: int = 200,
    oldest_first: bool = False,
    others: tuple[str, ...] = (),
    published_since: datetime | None = None,
    published_before: datetime | None = None,
) -> list[Page]:
    """`oldest_first` = theo thứ tự NẠP (fetched_at, url) tăng dần — cho các lượt viết tăng dần
    theo watermark; mặc định = bài mới nhất trước. `published_since`/`published_before` lọc theo ngày
    đăng (thiếu ngày đăng thì lấy ngày nạp)."""
    order = "fetched_at, url" if oldest_first else "coalesce(published_at, fetched_at) DESC"
    rows = await conn.fetch(
        f"""SELECT {_COLS} FROM tenant_data.web_pages
             WHERE tenant_id = portal.current_tenant() AND status = 'ok'
               AND ({_MATCHES_PROJECT.format(names="$1", others="$5")} OR location && $2::text[])
               AND ($3::timestamptz IS NULL OR fetched_at > $3)
               AND ($6::timestamptz IS NULL OR coalesce(published_at, fetched_at) >= $6)
               AND ($7::timestamptz IS NULL OR coalesce(published_at, fetched_at) < $7)
             ORDER BY {order}
             LIMIT $4""",
        match_names(projects),
        list(place_labels(location)),
        since,
        limit,
        match_names(others),
        published_since,
        published_before,
    )
    return [_page(r) for r in rows]


async def pages_published_since(
    conn: asyncpg.Connection, since: datetime, until: datetime, *, found_via: list[str], limit: int = 60
) -> list[Page]:
    """Bài có NGÀY ĐĂNG trong `[since, until]` (bài không rõ ngày bị loại), chỉ từ các kênh `found_via`."""
    rows = await conn.fetch(
        f"""SELECT {_COLS} FROM tenant_data.web_pages
             WHERE tenant_id = portal.current_tenant() AND status = 'ok'
               AND published_at >= $1 AND published_at <= $2 AND found_via = ANY($3::text[])
             ORDER BY published_at DESC
             LIMIT $4""",
        since,
        until,
        found_via,
        limit,
    )
    return [_page(r) for r in rows]


async def latest_fetched(
    conn: asyncpg.Connection, *, projects: list[str], location: list[str], others: tuple[str, ...] = ()
) -> datetime | None:
    return await conn.fetchval(
        f"""SELECT max(fetched_at) FROM tenant_data.web_pages
             WHERE tenant_id = portal.current_tenant() AND status = 'ok'
               AND ({_MATCHES_PROJECT.format(names="$1", others="$3")} OR location && $2::text[])""",
        match_names(projects),
        list(place_labels(location)),
        match_names(others),
    )


async def names_near(
    conn: asyncpg.Connection,
    location: list[str],
    exclude: list[str],
    limit: int = 20,
    *,
    min_pages: int = MIN_NEIGHBOR_PAGES,
) -> list[str]:
    """Tên dự án gắn trên ≥ `min_pages` bài `ok` cùng địa danh, nhiều bài trước; bỏ tên `same_project`
    với một tên trong `exclude`."""
    rows = await conn.fetch(
        """SELECT name, count(*) AS n
             FROM tenant_data.web_pages, unnest(projects) AS name
            WHERE tenant_id = portal.current_tenant() AND status = 'ok' AND location && $1::text[]
            GROUP BY name
           HAVING count(*) >= $2
            ORDER BY n DESC, name""",
        list(place_labels(location)),
        min_pages,
    )
    names = [r["name"] for r in rows if not any(same_project(r["name"], x) for x in exclude)]
    return names[:limit]


async def living_due(conn: asyncpg.Connection, domains: list[str], older_than: datetime, limit: int = 200) -> list[str]:
    rows = await conn.fetch(
        """SELECT url FROM tenant_data.web_pages
            WHERE tenant_id = portal.current_tenant() AND domain = ANY($1::text[])
              AND status = 'ok' AND last_checked_at < $2
            ORDER BY last_checked_at
            LIMIT $3""",
        domains,
        older_than,
        limit,
    )
    return [r["url"] for r in rows]


async def needs_browser_due(conn: asyncpg.Connection, since: datetime, limit: int = 100) -> list[str]:
    """URL còn dấu `needs_browser` gặp từ `since` — lượt đêm thử lại bằng trình duyệt."""
    rows = await conn.fetch(
        """SELECT url FROM tenant_data.web_pages
            WHERE tenant_id = portal.current_tenant() AND status = 'needs_browser' AND last_checked_at >= $1
            ORDER BY last_checked_at DESC
            LIMIT $2""",
        since,
        limit,
    )
    return [r["url"] for r in rows]


async def purge(conn: asyncpg.Connection, *, now: datetime, keep_days: int = KEEP_DAYS, marker_days: int = 90) -> int:
    """Xoá bài `ok` đã NẠP quá `keep_days` (bài đăng lâu mà mới nạp thì giữ — dựng hồ sơ dùng khi thiếu
    bài mới) và dấu không-ok quá `marker_days`."""
    result = await conn.execute(
        """DELETE FROM tenant_data.web_pages
            WHERE tenant_id = portal.current_tenant()
              AND ((status = 'ok' AND fetched_at < $1::timestamptz - make_interval(days => $2)
                   AND coalesce(published_at, fetched_at) < $1::timestamptz - make_interval(days => $2))
               OR (status <> 'ok' AND last_checked_at < $1::timestamptz - make_interval(days => $3)))""",
        now,
        keep_days,
        marker_days,
    )
    return int(result.split()[-1])


async def hidden_headings(conn: asyncpg.Connection, project_code: str) -> frozenset[str]:
    """Nhãn mục hồ sơ người dùng đã ẩn cho dự án — không viết vào hồ sơ dù nguồn có bài."""
    rows = await conn.fetch(
        """SELECT heading FROM tenant_data.kbweb_hidden_items
            WHERE tenant_id = portal.current_tenant() AND project_code = $1""",
        project_code,
    )
    return frozenset(r["heading"] for r in rows)


async def excluded_urls(conn: asyncpg.Connection, project_code: str) -> frozenset[str]:
    """URL người dùng đã loại khỏi nguồn dựng hồ sơ của dự án."""
    rows = await conn.fetch(
        """SELECT url FROM tenant_data.kbweb_page_exclusions
            WHERE tenant_id = portal.current_tenant() AND project_code = $1""",
        project_code,
    )
    return frozenset(r["url"] for r in rows)
