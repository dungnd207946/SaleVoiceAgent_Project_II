"""`tenant_data.project_hot_words` được đồng bộ khi tạo/đổi tên dự án (migration
`0963`, `repo.dong_bo_hot_word`, gọi từ `router.tao_du_an`/`sua_du_an`).

Thuật toán tách hot word tự nó canh ở `tests/unit/test_hot_words.py` — các test
dưới đây chỉ canh PHẦN GHI DB: đồng bộ đúng lúc, xoá-rồi-ghi khi đổi tên, và
unique theo tenant (project tạo/đổi tên trước giữ quyền sở hữu từ trùng).
"""

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _hot_words_cua(conn: asyncpg.Connection, project_code: str) -> set[str]:
    return {
        r["hot_word"]
        for r in await conn.fetch(
            """
            SELECT hw.hot_word FROM tenant_data.project_hot_words hw
            JOIN tenant_data.projects p ON p.id = hw.project_id
            WHERE p.project_code = $1
            """,
            project_code,
        )
    }


async def test_tao_du_an_sinh_dung_hot_word(client_re: httpx.AsyncClient, conn_re: asyncpg.Connection) -> None:
    r = await client_re.post(_url("/projects"), json={"projectCode": "HW1", "name": "THE MAGNOLIA - KHAI SƠN"})
    assert r.status_code == 201, r.text
    assert await _hot_words_cua(conn_re, "HW1") == {"THE", "MAGNOLIA"}


async def test_doi_ten_dong_bo_lai_hot_word(client_re: httpx.AsyncClient, conn_re: asyncpg.Connection) -> None:
    await client_re.post(_url("/projects"), json={"projectCode": "HW2", "name": "THE MAGNOLIA"})
    assert await _hot_words_cua(conn_re, "HW2") == {"THE", "MAGNOLIA"}

    r = await client_re.patch(_url("/projects/HW2"), json={"name": "Sun Central"})
    assert r.status_code == 200, r.text
    assert await _hot_words_cua(conn_re, "HW2") == {"SUN", "CENTRAL"}


async def test_sua_truong_khac_khong_dong_bo_lai_hot_word(
    client_re: httpx.AsyncClient, conn_re: asyncpg.Connection
) -> None:
    """PATCH không đụng `name` thì không xoá/ghi lại — tránh việc thừa không cần thiết."""
    await client_re.post(_url("/projects"), json={"projectCode": "HW3", "name": "The Sun"})
    truoc = await conn_re.fetchval(
        "SELECT hw.created_at FROM tenant_data.project_hot_words hw "
        "JOIN tenant_data.projects p ON p.id = hw.project_id "
        "WHERE p.project_code = 'HW3' AND hw.hot_word = 'THE'"
    )

    r = await client_re.patch(_url("/projects/HW3"), json={"region": "Hà Nội"})
    assert r.status_code == 200, r.text

    sau = await conn_re.fetchval(
        "SELECT hw.created_at FROM tenant_data.project_hot_words hw "
        "JOIN tenant_data.projects p ON p.id = hw.project_id "
        "WHERE p.project_code = 'HW3' AND hw.hot_word = 'THE'"
    )
    assert truoc == sau


async def test_trung_hot_word_cung_tenant_giu_project_tao_truoc(
    client_re: httpx.AsyncClient, conn_re: asyncpg.Connection
) -> None:
    """`UNIQUE (tenant_id, hot_word)` — project tạo SAU không giành được hot word
    đã thuộc về project tạo TRƯỚC trong cùng tenant (quyết định người dùng chốt)."""
    await client_re.post(_url("/projects"), json={"projectCode": "HW4A", "name": "Sun Riverside"})
    r = await client_re.post(_url("/projects"), json={"projectCode": "HW4B", "name": "Sun Central"})
    assert r.status_code == 201, r.text

    assert await _hot_words_cua(conn_re, "HW4A") == {"SUN", "RIVERSIDE"}
    assert await _hot_words_cua(conn_re, "HW4B") == {"CENTRAL"}


async def test_xoa_du_an_cascade_xoa_hot_word(client_re: httpx.AsyncClient, conn_re: asyncpg.Connection) -> None:
    """`ON DELETE CASCADE` (migration `0963`) — xoá project là hot word của nó biến
    mất theo, không cần code ứng dụng dọn tay."""
    await client_re.post(_url("/projects"), json={"projectCode": "HW5", "name": "Sun Riverside Premier"})
    assert await _hot_words_cua(conn_re, "HW5") == {"SUN", "RIVERSIDE", "PREMIER"}

    id_ = await conn_re.fetchval("SELECT id FROM tenant_data.projects WHERE project_code = 'HW5'")
    r = await client_re.delete(_url("/projects/HW5"))
    assert r.status_code == 204, r.text

    con_lai = await conn_re.fetchval("SELECT count(*) FROM tenant_data.project_hot_words WHERE project_id = $1", id_)
    assert con_lai == 0
