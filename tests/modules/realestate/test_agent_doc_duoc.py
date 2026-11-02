"""Test lớp đọc của agent trên `tenant_data` (Task 6) — role `agent_<tenant>` THẬT.

Khác `test_repo.py` (đọc CHO PORTAL, role `portal_api`/`portal_migrator`, dưới RLS
trên `tenant_data`): ở đây kết nối bằng ĐÚNG role provisioning cấp cho agent
(`control.create_agent_role`).

TỪ `0917`: bỏ hẳn view `agent_api.*` — agent đọc THẲNG `tenant_data.{projects,
zones, units, documents, media}`, cách ly hoàn toàn dựa vào RLS FORCE (`0913`).
Đánh đổi có chủ ý: các tính chất mà view từng làm — lọc `status='published'`,
cascade ẩn con của dự án cha chưa published, loại sentinel `__ALL__` khỏi danh sách
dự án — KHÔNG còn ai ở tầng Postgres cưỡng chế nữa; đó là việc code phía agent tự
làm trong câu query của họ. File này chỉ còn giữ lại đúng phần Postgres còn cưỡng
chế được: cách ly THEO TENANT, và không lộ tên cột nhạy cảm.
"""

import uuid

import asyncpg
import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.modules.realestate import repo
from tests.conftest import dsn_as

pytestmark = pytest.mark.integration

# Cùng nếp `test_repo.py`: id ngẫu nhiên để chạy song song không đụng tenant/role
# của một lượt test khác, và AGENT_PASSWORD chỉ dùng nội bộ test (không phải bí
# mật thật — role bị DROP ở teardown mỗi test).
_ORG = "noble"
AGENT_PASSWORD = "agentdev"

# Quét động (việc 4 của brief): không cột nào của agent_api được mang tên gợi
# trường nội bộ nhạy cảm mà `0400_kb_real_estate.py` đã cố tình KHÔNG tạo ra.
_TU_KHOA_NHAY_CAM = (
    "commission",
    "hoa_hong",
    "chiet_khau",
    "discount",
    "gia_net",
    "net_price",
    "bank_support",
    "csbh_full",
)


def _tenant_moi() -> str:
    # Tiền tố CHỮ (CHECK id ~ '^[a-z][a-z0-9_]{1,30}$' của control.tenants VÀ
    # control.create_agent_role) + hex ngẫu nhiên.
    return f"kbag{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def hai_tenant(pool: asyncpg.Pool):
    """Hai tenant, mỗi tenant dựng cây KB qua CHÍNH `repo.chen_*` (không viết SQL
    seed riêng — cùng nếp `test_repo.py`, các hàm đó đã được `test_repo.py` kiểm
    riêng nên dùng lại ở đây là an toàn).

    Cây mỗi tenant:
      - `__ALL__` (anchor hệ thống, published) + 1 document + 1 media trên đó.
      - `P1` (published): 1 zone `Z1`, unit `U1` published, `U-DRAFT` draft,
        `U-ARCHIVED` archived, 1 document + 1 media published, 1 document draft.
      - `P2` (published): chỉ 1 document — dùng để kiểm `__ALL__` gộp khi lọc
        theo một dự án KHÁC (`02 §2`).
      - `SHARED` — CÙNG mã ở CẢ HAI tenant nhưng KHÁC `status`
        (t1 = draft, t2 = published), có zone `ZS` + unit `U-SHARED` published.
        Đây là test sắc nhất cho "mệnh đề tenant thứ hai" (header migration): nếu
        JOIN cascade quên khớp `tenant_id` của `projects`, agent của t1 có thể
        "mượn" trạng thái published của SHARED bên t2 vì project_code trùng.
    """
    t1, t2 = _tenant_moi(), _tenant_moi()
    trang_thai_shared = {t1: "draft", t2: "published"}

    async with pool.acquire() as conn, conn.transaction():
        for t in (t1, t2):
            await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", t)

    for t in (t1, t2):
        async with tenant_conn(pool, t) as conn:
            await repo.chen_du_an(conn, t, {"project_code": "__ALL__", "name": "ALL", "status": "published"})
            await repo.chen_du_an(conn, t, {"project_code": "P1", "name": "Du an 1", "status": "published"})
            await repo.chen_du_an(conn, t, {"project_code": "P2", "name": "Du an 2", "status": "published"})
            await repo.chen_du_an(conn, t, {"project_code": "SHARED", "name": "Shared", "status": trang_thai_shared[t]})

            await repo.chen_phan_khu(
                conn, t, {"project_code": "P1", "zone_code": "Z1", "name": "Zone 1", "status": "published"}
            )
            await repo.chen_phan_khu(
                conn, t, {"project_code": "SHARED", "zone_code": "ZS", "name": "Zone Shared", "status": "published"}
            )

            await repo.chen_can(
                conn,
                t,
                {
                    "project_code": "P1",
                    "zone_code": "Z1",
                    "unit_code": "U1",
                    "product_type": "chung_cu",
                    "status": "published",
                },
            )
            await repo.chen_can(
                conn,
                t,
                {
                    "project_code": "P1",
                    "zone_code": "Z1",
                    "unit_code": "U-DRAFT",
                    "product_type": "chung_cu",
                    "status": "draft",
                },
            )
            await repo.chen_can(
                conn,
                t,
                {
                    "project_code": "P1",
                    "zone_code": "Z1",
                    "unit_code": "U-ARCHIVED",
                    "product_type": "chung_cu",
                    "status": "archived",
                },
            )
            await repo.chen_can(
                conn,
                t,
                {
                    "project_code": "SHARED",
                    "zone_code": "ZS",
                    "unit_code": "U-SHARED",
                    "product_type": "chung_cu",
                    "status": "published",
                },
            )

            await repo.chen_tai_lieu(conn, t, {"project_code": "P1", "title": f"Doc P1 {t}", "status": "published"})
            await repo.chen_tai_lieu(conn, t, {"project_code": "P1", "title": f"Doc P1 draft {t}", "status": "draft"})
            await repo.chen_tai_lieu(conn, t, {"project_code": "P2", "title": f"Doc P2 {t}", "status": "published"})
            await repo.chen_tai_lieu(
                conn, t, {"project_code": "__ALL__", "title": f"Doc ALL {t}", "status": "published"}
            )

            await repo.chen_media(
                conn,
                t,
                {
                    "project_code": "P1",
                    "content_type": "image",
                    "category": "tong_quan",
                    "media_url": f"http://x/{t}/p1.png",
                    "status": "published",
                },
            )
            await repo.chen_media(
                conn,
                t,
                {
                    "project_code": "P1",
                    "content_type": "image",
                    "category": "tong_quan",
                    "media_url": f"http://x/{t}/p1-draft.png",
                    "status": "draft",
                },
            )

    yield t1, t2

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [t1, t2])


@pytest.fixture
async def agent_roles(hai_tenant, pool: asyncpg.Pool):
    """Tạo role `agent_<t1>`/`agent_<t2>` bằng ĐÚNG hàm provisioning dùng
    (`control.create_agent_role`) — không tự `CREATE ROLE` tay, để test canh đúng
    con đường thật."""
    t1, t2 = hai_tenant
    async with pool.acquire() as conn:
        for t in (t1, t2):
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")
            await conn.execute("SELECT control.create_agent_role($1, $2)", t, AGENT_PASSWORD)
    yield t1, t2
    async with pool.acquire() as conn:
        for t in (t1, t2):
            await conn.execute(f"REASSIGN OWNED BY agent_{t} TO portal_migrator")
            await conn.execute(f"DROP OWNED BY agent_{t}")
            await conn.execute(f"DROP ROLE IF EXISTS agent_{t}")


@pytest.fixture
async def agent_pool(agent_roles, pg_dsn: str):
    """Factory: `await agent_pool(t1)` -> pool nối bằng role `agent_<t1>`."""
    pools: list[asyncpg.Pool] = []

    async def make(tenant: str) -> asyncpg.Pool:
        p = await create_pool(dsn_as(pg_dsn, f"agent_{tenant}", AGENT_PASSWORD), min_size=1, max_size=2)
        pools.append(p)
        return p

    yield make
    for p in pools:
        await p.close()


# ─── 1. Cách ly hàng — trên CẢ 5 bảng, đọc thẳng tenant_data ────────────────
#
# Không còn view lọc `status`/cascade/sentinel, nên tập kỳ vọng ở đây là TOÀN BỘ
# hàng của đúng tenant — kể cả draft/archived/`__ALL__` — không phải tập đã qua
# lọc nghiệp vụ như trước `0917`. Vẫn dùng dữ liệu trộn nhiều trạng thái của
# `hai_tenant` vì ca sắc nhất (SHARED trùng project_code, khác trạng thái, giữa
# hai tenant) vẫn là phép thử tốt nhất cho ĐÚNG một thứ Postgres còn cưỡng chế:
# cách ly theo `tenant_id` qua RLS FORCE (`0913`).


async def test_cach_ly_hang_ca_5_bang(agent_roles, agent_pool):
    t1, t2 = agent_roles
    p1 = await agent_pool(t1)
    async with p1.acquire() as conn:
        ma_du_an = {r["project_code"] for r in await conn.fetch("SELECT project_code FROM tenant_data.projects")}
        ma_zone = {r["zone_code"] for r in await conn.fetch("SELECT zone_code FROM tenant_data.zones")}
        ma_can = {r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units")}
        tieu_de = {r["title"] for r in await conn.fetch("SELECT title FROM tenant_data.documents")}
        url_media = {r["media_url"] for r in await conn.fetch("SELECT media_url FROM tenant_data.media")}

    # t1 để SHARED draft, nhưng ZS/U-SHARED tự thân vẫn published — không còn
    # cascade nào ẩn chúng, nên cả hai PHẢI xuất hiện (khác `0917` trở về trước).
    assert ma_du_an == {"P1", "P2", "SHARED", "__ALL__"}
    assert ma_zone == {"Z1", "ZS"}
    assert ma_can == {"U1", "U-DRAFT", "U-ARCHIVED", "U-SHARED"}
    assert tieu_de == {f"Doc P1 {t1}", f"Doc P1 draft {t1}", f"Doc P2 {t1}", f"Doc ALL {t1}"}
    assert url_media == {f"http://x/{t1}/p1.png", f"http://x/{t1}/p1-draft.png"}

    p2 = await agent_pool(t2)
    async with p2.acquire() as conn:
        ma_du_an = {r["project_code"] for r in await conn.fetch("SELECT project_code FROM tenant_data.projects")}
        ma_zone = {r["zone_code"] for r in await conn.fetch("SELECT zone_code FROM tenant_data.zones")}
        ma_can = {r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units")}

    # Seed giống hệt cấu trúc cho cả hai tenant (chỉ khác trạng thái SHARED) — nên
    # t2 phải thấy ĐÚNG cùng tập mã, không thấy thêm/thiếu gì so với t1: đây là
    # bằng chứng "đọc đúng của mình", không phải trùng hợp hai tập đều rỗng.
    assert ma_du_an == {"P1", "P2", "SHARED", "__ALL__"}
    assert ma_zone == {"Z1", "ZS"}
    assert ma_can == {"U1", "U-DRAFT", "U-ARCHIVED", "U-SHARED"}


async def test_khong_ro_qua_project_code_trung_giua_hai_tenant(agent_roles, agent_pool):
    """Trường hợp sắc nhất của cách ly theo tenant: CẢ HAI tenant có
    project_code = "SHARED". Nếu RLS/role của agent_t1 thiếu vị từ tenant đúng,
    agent_t1 có thể đọc lẫn `zone`/`unit` của SHARED thuộc t2.
    """
    t1, t2 = agent_roles
    p1 = await agent_pool(t1)
    async with p1.acquire() as conn:
        zones = await conn.fetch("SELECT project_code FROM tenant_data.zones WHERE zone_code = 'ZS'")
        assert [r["project_code"] for r in zones] == ["SHARED"], "phải thấy ZS của CHÍNH t1, không phải 0 hay của t2"
        units = await conn.fetch("SELECT project_code FROM tenant_data.units WHERE unit_code = 'U-SHARED'")
        assert [r["project_code"] for r in units] == ["SHARED"]

    p2 = await agent_pool(t2)
    async with p2.acquire() as conn:
        # Đếm đúng 1 hàng mỗi bên — không phải 2 (nếu rò, hai tenant sẽ cùng thấy
        # cả hai hàng SHARED khi JOIN/lọc chỉ khớp project_code suông).
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.zones WHERE zone_code = 'ZS'") == 1
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.units WHERE unit_code = 'U-SHARED'") == 1


# ─── 2. Quét động — không cột nào gợi trường nội bộ nhạy cảm ───────────────


async def test_quet_dong_khong_cot_nhay_cam(pool: asyncpg.Pool):
    """Từ `0917`: agent đọc THẲNG `tenant_data`, không qua view lọc cột nữa — nên
    quét đúng năm bảng agent thật sự đọc, không quét cả schema (bảng write-back/
    `agent_config`/`kb_*` không phải phạm vi của cổng này)."""
    bang_agent_doc = ("projects", "zones", "units", "documents", "media")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'tenant_data' AND table_name = ANY($1::text[])",
            list(bang_agent_doc),
        )
    assert rows, "không có cột nào trong năm bảng — migration 0400 chưa chạy?"

    vi_pham = [
        f"{r['table_name']}.{r['column_name']}"
        for r in rows
        if any(tu in r["column_name"].lower() for tu in _TU_KHOA_NHAY_CAM)
    ]
    assert vi_pham == [], f"cột mang tên gợi trường nội bộ nhạy cảm: {vi_pham}"
