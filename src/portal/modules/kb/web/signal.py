"""Đọc dự án published của tenant + tín hiệu "có người hỏi" từ conversation_messages.

`asked_codes` là bộ lọc cho lượt crawl theo dự án: không log nào trong cửa sổ
`days` thì coi MỌI dự án là đáng crawl (tenant mới/agent chưa chạy không nên bị
bỏ đói); có log thì chỉ dự án nào thực sự xuất hiện — trong tham số tool gọi
`ASK_TOOLS`, hoặc trong câu chữ của khách — mới được coi là "đang được hỏi".
"""

from dataclasses import dataclass, replace

import asyncpg

from portal.modules.kb.web.normalize import contains_word, fold, norm_project, project_matches

ASK_TOOLS = ("find_project", "discover_projects", "search_units", "kb_search")
MIN_HOT_WORD = 5
MAX_USER_MESSAGES = 5000

_FACT_COLUMNS = (
    ("Địa chỉ", "address"),
    ("Khu vực", "region"),
    ("Chủ đầu tư", "investor"),
    ("Đơn vị phát triển", "developer"),
    ("Quy mô", "product_scale"),
    ("Tiện ích", "amenities"),
    ("Giai đoạn bán", "sale_phase"),
    ("Tổng quan", "overview"),
)


@dataclass(frozen=True, slots=True)
class ProjectRow:
    id: int
    code: str
    name: str
    region: str
    address: str
    facts: str
    hot_words: tuple[str, ...]
    # tên dự án cùng tenant là biến thể CỤ THỂ HƠN của tên này ("vinhomes global gate hạ long" với
    # "vinhomes global gate") — nhãn khớp chúng thuộc về dự án kia, không thuộc dự án này
    more_specific: tuple[str, ...] = ()


async def load_projects(conn: asyncpg.Connection) -> list[ProjectRow]:
    """Dự án published của tenant hiện tại, bỏ sentinel `__ALL__` (hàng hệ thống, không phải dự án thật)."""
    rows = await conn.fetch(
        """SELECT p.id, p.project_code, p.name, p.region, p.address, p.investor, p.developer,
                  p.product_scale, p.amenities, p.sale_phase, p.overview,
                  coalesce(array_agg(h.hot_word) FILTER (WHERE h.hot_word IS NOT NULL), '{}') AS hot_words
             FROM tenant_data.projects p
             LEFT JOIN tenant_data.project_hot_words h ON h.project_id = p.id AND h.tenant_id = p.tenant_id
            WHERE p.tenant_id = portal.current_tenant() AND p.status = 'published' AND p.project_code <> '__ALL__'
            GROUP BY p.id
            ORDER BY p.project_code"""
    )
    projects = [
        ProjectRow(
            id=int(r["id"]),
            code=r["project_code"],
            name=r["name"],
            region=r["region"],
            address=r["address"],
            facts="\n".join(f"{label}: {r[col]}" for label, col in _FACT_COLUMNS if r[col]),
            hot_words=tuple(r["hot_words"]),
        )
        for r in rows
    ]
    return [with_more_specific(p, projects) for p in projects]


def with_more_specific(project: ProjectRow, siblings: list[ProjectRow]) -> ProjectRow:
    own = norm_project(project.name)
    longer = tuple(
        sorted(
            {
                norm_project(s.name)
                for s in siblings
                if norm_project(s.name) != own and project_matches(norm_project(s.name), project.name)
            }
        )
    )
    return replace(project, more_specific=longer)


def _mentioned(p: ProjectRow, hay: str) -> bool:
    """Khớp theo mã, tên, hoặc hot word đủ dài (>=`MIN_HOT_WORD`) — tránh hot word 1-2 ký tự khớp bừa."""
    needles = [p.code, p.name, *(w for w in p.hot_words if len(w) >= MIN_HOT_WORD)]
    return any(contains_word(hay, n) for n in needles if len(n) >= 3)


async def asked_codes(conn: asyncpg.Connection, projects: list[ProjectRow], *, days: int = 28) -> set[str]:
    """Mã dự án được nhắc tới trong `days` ngày gần nhất — qua tham số tool (`ASK_TOOLS`) hoặc câu chữ của khách.

    Không có hàng nào trong cửa sổ (tenant chưa có log, hoặc agent chưa chạy) thì
    coi MỌI dự án là đáng crawl — im lặng không nên đọc thành "không ai hỏi gì".
    """
    total = await conn.fetchval(
        """SELECT count(*) FROM tenant_data.conversation_messages
            WHERE tenant_id = portal.current_tenant() AND created_at >= now() - make_interval(days => $1)""",
        days,
    )
    if not total:
        return {p.code for p in projects}
    args = await conn.fetch(
        """SELECT tc->'function'->>'arguments' AS a
             FROM tenant_data.conversation_messages m
             CROSS JOIN LATERAL jsonb_array_elements(
                 CASE WHEN jsonb_typeof(m.meta->'tool_calls') = 'array' THEN m.meta->'tool_calls' ELSE '[]'::jsonb END
             ) AS tc
            WHERE m.tenant_id = portal.current_tenant()
              AND m.created_at >= now() - make_interval(days => $1)
              AND tc->'function'->>'name' = ANY($2::text[])""",
        days,
        list(ASK_TOOLS),
    )
    said = await conn.fetch(
        """SELECT content FROM tenant_data.conversation_messages
            WHERE tenant_id = portal.current_tenant() AND role = 'user'
              AND created_at >= now() - make_interval(days => $1)
            ORDER BY created_at DESC
            LIMIT $2""",
        days,
        MAX_USER_MESSAGES,
    )
    hay = fold("\n".join([r["a"] or "" for r in args] + [r["content"] or "" for r in said]))
    return {p.code for p in projects if _mentioned(p, hay)}
