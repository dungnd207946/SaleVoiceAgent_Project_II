"""RE-REVIEW verification — temporary file, deleted after the run.

Independent reproduction of the reviewer scenarios A/D/E/F6/F3 over real HTTP
through the full app stack. Does NOT reuse the implementer's helpers.
"""

import asyncpg
import httpx
import pytest

from portal.core.db.session import tenant_conn
from portal.modules.realestate import repo

V = "/api/v1"


async def _seed_all(pool: asyncpg.Pool, tenant: str) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
        await conn.execute(
            """INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
               VALUES ($1, '__ALL__', 'Chung / toan tenant', 'published')
               ON CONFLICT (tenant_id, project_code) DO NOTHING""",
            tenant,
        )


# ═══ A — sentinel protected, each scenario re-run over HTTP ═══════════════════


async def test_A1_patch_sentinel_status_rejected_and_agent_docs_survive(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    await _seed_all(pool, workspace_re)
    r = await client_re.post(f"{V}/projects", json={"projectCode": "RA1", "region": "HN", "overview": "o"})
    assert r.status_code == 201, r.text
    d = await client_re.post(f"{V}/projects/__ALL__/documents", json={"title": "Chung", "status": "published"})
    assert d.status_code == 201, d.text

    async with tenant_conn(pool, workspace_re) as c:
        truoc = len(await repo.liet_ke_tai_lieu_cho_agent(c, "RA1"))
    assert truoc == 1

    r = await client_re.patch(f"{V}/projects/__ALL__", json={"status": "draft"})
    assert r.status_code != 200, f"REGRESSION: PATCH status on sentinel returned 200: {r.text}"
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SENTINEL_PROTECTED"

    async with tenant_conn(pool, workspace_re) as c:
        sau = len(await repo.liet_ke_tai_lieu_cho_agent(c, "RA1"))
    assert sau == 1, f"agent shared-doc count dropped {truoc} -> {sau}"
    st = await pool.fetchval(
        "SELECT status FROM tenant_data.projects WHERE tenant_id=$1 AND project_code='__ALL__'", workspace_re
    )
    assert st == "published"


async def test_A2_delete_sentinel_rejected_no_cascade(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    await _seed_all(pool, workspace_re)
    for t in ("d1", "d2", "d3"):
        assert (await client_re.post(f"{V}/projects/__ALL__/documents", json={"title": t})).status_code == 201
    truoc = await pool.fetchval(
        "SELECT count(*) FROM tenant_data.documents WHERE tenant_id=$1 AND project_code='__ALL__'", workspace_re
    )
    assert truoc == 3

    r = await client_re.delete(f"{V}/projects/__ALL__")
    assert r.status_code != 204, "REGRESSION: DELETE sentinel succeeded, cascade wiped shared docs"
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SENTINEL_PROTECTED"

    sau = await pool.fetchval(
        "SELECT count(*) FROM tenant_data.documents WHERE tenant_id=$1 AND project_code='__ALL__'", workspace_re
    )
    assert sau == 3, f"cascade deleted rows: {truoc} -> {sau}"


async def test_A3_post_sentinel_rejected(client_re: httpx.AsyncClient):
    r = await client_re.post(f"{V}/projects", json={"projectCode": "__ALL__", "name": "chiem"})
    assert r.status_code != 201, "REGRESSION: anyone with CATALOG_WRITE can claim the sentinel"
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SENTINEL_PROTECTED"


async def test_A4_not_closed_too_tight(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    """POST documents under sentinel must still work; GET by exact code must work;
    PATCH of non-status fields must still work."""
    await _seed_all(pool, workspace_re)
    doc = await client_re.post(f"{V}/projects/__ALL__/documents", json={"title": "van chay"})
    assert doc.status_code == 201, doc.text
    med = await client_re.post(
        f"{V}/projects/__ALL__/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/a.webp"},
    )
    assert med.status_code == 201, med.text
    g = await client_re.get(f"{V}/projects/__ALL__")
    assert g.status_code == 200, g.text
    assert g.json()["projectCode"] == "__ALL__"
    p = await client_re.patch(f"{V}/projects/__ALL__", json={"name": "Ten moi"})
    assert p.status_code == 200, f"over-tight: PATCH of a non-status field blocked: {p.text}"
    assert p.json()["name"] == "Ten moi"


async def test_A5_sentinel_hidden_by_sql_predicate_not_post_filter(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """Sentinel absent from list; and the keyset walk must not lose or short-change
    pages. Post-fetch filtering would make a page return lim-1 rows and skew
    `_trang`'s next-page inference."""
    await _seed_all(pool, workspace_re)
    ma_that = [f"PG{i}" for i in range(7)]
    for m in ma_that:
        assert (await client_re.post(f"{V}/projects", json={"projectCode": m})).status_code == 201

    ds = await client_re.get(f"{V}/projects", params={"limit": 200})
    got = [x["projectCode"] for x in ds.json()["items"]]
    assert "__ALL__" not in got, "sentinel still listed"
    assert set(ma_that) <= set(got), "over-filtered: real projects lost"

    # Keyset walk, limit=2. Sentinel sits in the id ordering among the real rows.
    thay: list[str] = []
    cursor = None
    for _ in range(20):
        params: dict = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        r = await client_re.get(f"{V}/projects", params=params)
        assert r.status_code == 200, r.text
        body = r.json()
        page = [x["projectCode"] for x in body["items"]]
        assert "__ALL__" not in page
        # Every non-terminal page must be FULL. A post-fetch filter would yield a
        # short page here while nextCursor is still set.
        if body["nextCursor"]:
            assert len(page) == 2, f"short page {page} with nextCursor set — pagination skewed"
        thay += page
        cursor = body["nextCursor"]
        if not cursor:
            break
    assert set(ma_that) <= set(thay), f"keyset walk lost rows: missing {set(ma_that) - set(thay)}"
    assert len(thay) == len(set(thay)), f"keyset walk duplicated rows: {thay}"

    tim = await client_re.get(f"{V}/projects", params={"search": "ALL"})
    assert "__ALL__" not in [x["projectCode"] for x in tim.json()["items"]]


# ═══ D — ceiling <=6 images per counting cell — REMOVED in round 2 ══════════
# The ≤6-per-category ceiling (`02a §4.5`) was dropped from the app (no DB
# constraint backed it). Tests below are INVERTED from the original scenario:
# the 7th+ image must now be ACCEPTED, not rejected.


async def test_D_nine_posts_all_accepted(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    assert (await client_re.post(f"{V}/projects", json={"projectCode": "RD1"})).status_code == 201
    ma = []
    for i in range(9):
        r = await client_re.post(
            f"{V}/projects/RD1/media",
            json={"contentType": "image", "category": "tong_quan", "mediaUrl": f"https://x/{i}.webp"},
        )
        ma.append(r.status_code)
    assert ma == [201] * 9, f"all nine must be accepted: {ma}"
    so = await pool.fetchval(
        "SELECT count(*) FROM tenant_data.media WHERE tenant_id=$1 AND project_code='RD1'", workspace_re
    )
    assert so == 9, f"DB holds {so} rows, expected 9"


async def test_D_counting_cell_is_project_zone_unit_category(client_re: httpx.AsyncClient):
    assert (await client_re.post(f"{V}/projects", json={"projectCode": "RD2"})).status_code == 201
    assert (await client_re.post(f"{V}/projects/RD2/zones", json={"zoneCode": "Z1"})).status_code == 201
    for i in range(6):
        r = await client_re.post(
            f"{V}/projects/RD2/media",
            json={"contentType": "image", "category": "tong_quan", "mediaUrl": f"https://x/f{i}.webp"},
        )
        assert r.status_code == 201
    # different category -> different cell
    assert (
        await client_re.post(
            f"{V}/projects/RD2/media",
            json={"contentType": "image", "category": "ngoai_that", "mediaUrl": "https://x/c.webp"},
        )
    ).status_code == 201
    # different zone -> different cell
    assert (
        await client_re.post(
            f"{V}/projects/RD2/media",
            json={"contentType": "image", "category": "tong_quan", "zoneCode": "Z1", "mediaUrl": "https://x/z.webp"},
        )
    ).status_code == 201
    # different unit -> different cell
    assert (
        await client_re.post(
            f"{V}/projects/RD2/media",
            json={"contentType": "image", "category": "tong_quan", "unitCode": "U1", "mediaUrl": "https://x/u.webp"},
        )
    ).status_code == 201
    # video does not count
    assert (
        await client_re.post(
            f"{V}/projects/RD2/media",
            json={"contentType": "video", "category": "tong_quan", "mediaUrl": "https://x/v.mp4"},
        )
    ).status_code == 201


async def test_D_project_level_seventh_image_accepted(client_re: httpx.AsyncClient):
    """Ceiling removed — the project-level (NULL zone/unit) cell no longer
    blocks a 7th image."""
    assert (await client_re.post(f"{V}/projects", json={"projectCode": "RD3"})).status_code == 201
    for i in range(6):
        assert (
            await client_re.post(
                f"{V}/projects/RD3/media",
                json={"contentType": "image", "category": "vi_tri", "mediaUrl": f"https://x/n{i}.webp"},
            )
        ).status_code == 201
    r = await client_re.post(
        f"{V}/projects/RD3/media",
        json={"contentType": "image", "category": "vi_tri", "mediaUrl": "https://x/n7.webp"},
    )
    assert r.status_code == 201, f"ceiling removed but still blocks: {r.text}"


# ═══ E — enum filters on the READ path ══════════════════════════════════════


@pytest.mark.parametrize(
    ("duong", "tham_so"),
    [
        ("units", {"product_type": "BOGUS"}),
        ("units", {"sale_status": "BOGUS"}),
        ("media", {"category": "BOGUS"}),
        ("media", {"content_type": "BOGUS"}),
    ],
)
async def test_E_bad_enum_is_422(client_re: httpx.AsyncClient, duong: str, tham_so: dict):
    assert (await client_re.post(f"{V}/projects", json={"projectCode": "RE1"})).status_code in (201, 409)
    r = await client_re.get(f"{V}/projects/RE1/{duong}", params=tham_so)
    assert r.status_code == 422, f"{duong}?{tham_so} -> {r.status_code} (200-empty is the bug): {r.text}"
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_E_no_filter_path_intact(client_re: httpx.AsyncClient):
    """Empty AND absent params must both still return the full list."""
    assert (await client_re.post(f"{V}/projects", json={"projectCode": "RE2"})).status_code == 201
    assert (await client_re.post(f"{V}/projects/RE2/zones", json={"zoneCode": "Z1"})).status_code == 201
    for u in ("U1", "U2"):
        assert (
            await client_re.post(
                f"{V}/projects/RE2/units",
                json={"zoneCode": "Z1", "unitCode": u, "productType": "chung_cu"},
            )
        ).status_code == 201
    assert (
        await client_re.post(
            f"{V}/projects/RE2/media",
            json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/m.webp"},
        )
    ).status_code == 201

    vang = await client_re.get(f"{V}/projects/RE2/units")
    assert vang.status_code == 200 and len(vang.json()["items"]) == 2, vang.text
    rong = await client_re.get(f"{V}/projects/RE2/units", params={"product_type": "", "sale_status": ""})
    assert rong.status_code == 200 and len(rong.json()["items"]) == 2, rong.text
    mv = await client_re.get(f"{V}/projects/RE2/media", params={"category": "", "content_type": ""})
    assert mv.status_code == 200 and len(mv.json()["items"]) == 1, mv.text
    # filtering still filters
    f = await client_re.get(f"{V}/projects/RE2/units", params={"product_type": "biet_thu"})
    assert f.status_code == 200 and f.json()["items"] == []


# ═══ F6 — 404 before 422, rollback, no audit ═════════════════════════════════


async def test_F6_404_before_422(client_re: httpx.AsyncClient):
    r = await client_re.post(
        f"{V}/projects/NO-SUCH-PROJECT/units",
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu", "status": "published"},
    )
    assert r.status_code == 404, f"expected 404 before 422, got {r.status_code}: {r.text}"
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_F6_422_rolls_back_and_writes_no_audit(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    assert (await client_re.post(f"{V}/projects", json={"projectCode": "RF6"})).status_code == 201
    assert (await client_re.post(f"{V}/projects/RF6/zones", json={"zoneCode": "Z1"})).status_code == 201
    truoc = await pool.fetchval(
        "SELECT count(*) FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong='realestate.unit.create'",
        workspace_re,
    )
    r = await client_re.post(
        f"{V}/projects/RF6/units",
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu", "status": "published"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INCOMPLETE_DATA"
    so = await pool.fetchval(
        "SELECT count(*) FROM tenant_data.units WHERE tenant_id=$1 AND project_code='RF6'", workspace_re
    )
    assert so == 0, f"422 left {so} rows behind — no rollback"
    sau = await pool.fetchval(
        "SELECT count(*) FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong='realestate.unit.create'",
        workspace_re,
    )
    assert sau == truoc, "audit row written for a unit that never existed"


# ═══ F3 — validation body shape, and handler must not blow up on odd ctx ═════


async def test_F3_fields_shape(client_re: httpx.AsyncClient):
    assert (await client_re.post(f"{V}/projects", json={"projectCode": "RF3"})).status_code == 201
    r = await client_re.post(
        f"{V}/projects/RF3/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": ""},
    )
    assert r.status_code == 422, r.text
    e = r.json()["error"]
    assert e["code"] == "VALIDATION_ERROR"
    assert isinstance(e["fields"], list)
    assert e["fields"] == [{"field": "body.mediaUrl", "reason": "String should have at least 1 character"}]
    assert "'type':" not in e["message"]


async def test_F3_handler_survives_nonserialisable_ctx(client_re: httpx.AsyncClient):
    """A validation error whose `ctx` holds a Python object (`ValueError`) must
    still yield a clean 422, not a 500 inside the error handler."""
    # `category` is a list[Literal] -> a wrong member yields ctx with expected
    # values; `limit` non-int yields ctx with an int-parse error object.
    r = await client_re.get(f"{V}/projects", params={"limit": "abc"})
    assert r.status_code == 422, f"handler blew up: {r.status_code} {r.text}"
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert [t["field"] for t in r.json()["error"]["fields"]] == ["query.limit"]

    r2 = await client_re.post(f"{V}/projects", json={"projectCode": "X", "category": ["khong_co_loai_nay"]})
    assert r2.status_code == 422, f"handler blew up: {r2.status_code} {r2.text}"
    assert r2.json()["error"]["code"] == "VALIDATION_ERROR"
    assert [t["field"] for t in r2.json()["error"]["fields"]] == ["body.category[0]"]


async def test_F3_deep_nested_and_body_prefix(client_re: httpx.AsyncClient):
    """Nested model error keeps the full dotted path."""
    r = await client_re.post(f"{V}/projects", json={"projectCode": "RF3B", "coverMedia": {"mediaUrl": ""}})
    assert r.status_code == 422, r.text
    assert [t["field"] for t in r.json()["error"]["fields"]] == ["body.coverMedia.mediaUrl"]
