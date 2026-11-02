"""Cổng cho ROLE AGENT DÙNG CHUNG `odyssey_agent` — hợp đồng agent-postgres-read §0.

VÌ SAO LÀ MỘT FILE RIÊNG: năm cổng cách ly hiện có đều đứng trên cùng một giả định —
tenant suy TỪ TÊN ROLE (`agent_<slug>`), tức Postgres cưỡng chế phạm vi bằng chính
credential, nên một pod KHÔNG THỂ đọc tenant khác dù code có bug. `odyssey_agent` bỏ
giả định đó: MỘT credential cho MỌI tenant, phạm vi đến từ lời khai `app.tenant_id`
mà chính agent đặt. Rào chắn chuyển từ ổ khoá sang kỷ luật.

Đánh đổi đó là quyết định của người vận hành, không phải của file này. Việc của cổng
này là canh đúng hai thứ còn lại sau khi đã đánh đổi:

  1. KHÔNG KHAI TENANT ⇒ 0 DÒNG (fail-closed). Sau khi bỏ ổ khoá, đây là thứ DUY NHẤT
     còn đứng giữa một bug "quên set tenant" và một lần rò chéo tenant. Nó không phải
     may mắn: `current_setting('app.tenant_id', true)` trả NULL, `nullif` biến ''
     thành NULL, và `WHERE tenant_id = NULL` không khớp hàng nào. Ba mắt xích, cái nào
     đổi cũng làm cổng này đỏ — kể cả một `ALTER ROLE ... SET app.tenant_id = '...'`
     lỡ tay, thứ sẽ biến "quên khai" thành "đọc tenant mặc định".

  2. QUYỀN CỦA `odyssey_agent` KHÔNG RỘNG HƠN `agent_all`. Nó là role LOGIN, nên một
     mật khẩu lộ = mọi tenant. Không sửa được bằng kỷ luật, chỉ hạn được thiệt hại
     bằng cách giữ bề mặt hẹp — và bề mặt chỉ hẹp nếu có người canh nó không nở ra.

PHẦN KHÔNG KIỂM ĐƯỢC TỪ ĐÂY (bên agent cam kết): `SET LOCAL` trong một giao dịch
tường minh, không bao giờ `SET` trần. Vì sao `SET` trần là lỗ hổng thật:
test_pool_leak.py::test_set_tran_song_qua_ranh_gioi_giao_dich_tren_cung_ket_noi.
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from tests.conftest import ODYSSEY_AGENT_PASSWORD, dsn_as

pytestmark = pytest.mark.integration

ROLE = "odyssey_agent"


@pytest.fixture
async def odyssey_pool(seeded, pg_dsn: str) -> AsyncIterator[asyncpg.Pool]:
    """Pool nối bằng `odyssey_agent`.

    max_size=1 BUỘC mọi truy vấn dùng đúng một kết nối vật lý — điều kiện tái hiện
    của lỗi kế thừa tenant, không phải chi tiết ngẫu nhiên (cùng lý lẽ với
    `one_conn_pool` của cổng 4).
    """
    p = await create_pool(dsn_as(pg_dsn, ROLE, ODYSSEY_AGENT_PASSWORD), min_size=1, max_size=1)
    yield p
    await p.close()


async def test_role_dung_chung_la_thanh_vien_cua_agent_all(pool):
    """Toàn bộ quyền của role này đến từ nhóm `agent_all`, không từ GRANT riêng.

    Kiểm bằng pg_auth_members chứ không bằng "nó đọc được view": đọc được view chỉ
    nói hôm nay có quyền, không nói quyền đến TỪ ĐÂU. Nếu ai đó cấp thẳng
    `GRANT SELECT ON agent_api.units TO odyssey_agent` rồi bỏ tư cách thành viên,
    một phép kiểm theo hành vi vẫn xanh trong khi bề mặt đã thoát khỏi chỗ canh.
    """
    async with pool.acquire() as conn:
        thanh_vien = await conn.fetchval(
            """SELECT EXISTS (
                   SELECT 1 FROM pg_auth_members m
                     JOIN pg_roles r ON r.oid = m.roleid
                     JOIN pg_roles g ON g.oid = m.member
                    WHERE r.rolname = 'agent_all' AND g.rolname = $1
               )""",
            ROLE,
        )
    assert thanh_vien is True, f"{ROLE} không phải thành viên agent_all — GRANT agent_all TO {ROLE} chưa chạy"


async def test_khong_khai_tenant_thi_doc_khong_ra_hang_nao(odyssey_pool):
    """FAIL-CLOSED — tính chất quan trọng nhất của cả file này.

    Đây là mô phỏng đúng cái bug sẽ xảy ra ngoài thực tế: agent lấy kết nối và
    truy vấn mà quên khai tenant. Phải ra 0 hàng. Ra hàng của bất kỳ tenant nào
    là cách ly đã vỡ, và vỡ ÂM THẦM — không có lỗi nào phát ra.
    """
    async with odyssey_pool.acquire() as conn, conn.transaction():
        assert await conn.fetchval("SELECT portal.current_tenant()") is None
        rows = await conn.fetch("SELECT unit_code FROM tenant_data.units")
    assert [r["unit_code"] for r in rows] == [], (
        "đọc được dữ liệu khi CHƯA khai tenant — sau khi bỏ cách ly theo tên role, "
        "fail-closed là lớp bảo vệ duy nhất còn lại"
    )


async def test_khai_tenant_nao_chi_thay_tenant_do(odyssey_pool):
    """Khai t1 thấy đúng t1, khai t2 thấy đúng t2 — cùng một credential."""
    async with tenant_conn(odyssey_pool, "t1") as conn:
        assert [r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units")] == ["A-01"]
    async with tenant_conn(odyssey_pool, "t2") as conn:
        assert [r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units")] == ["B-01"]


async def test_hai_tenant_xen_ke_khong_lan_nhau(odyssey_pool):
    """Xen kẽ trên ĐÚNG MỘT kết nối vật lý — hình dạng thật của agent share process.

    Cổng 4 đã canh điều này cho `portal_api`. Lặp lại ở đây KHÔNG phải dư: cổng 4
    chạy trên role mà `portal.current_tenant()` cũng rơi về GUC, nhưng nó không chứng
    minh gì cho một role LOGIN mà agent thật sẽ dùng — và role đó là thứ vừa được
    thêm vào. Một `ALTER ROLE odyssey_agent SET app.tenant_id` làm cổng 4 vẫn xanh
    còn cổng này đỏ.
    """
    thay = []
    for t in ("t1", "t2", "t1", "t2", "t1"):
        async with tenant_conn(odyssey_pool, t) as conn:
            thay.append([r["unit_code"] for r in await conn.fetch("SELECT unit_code FROM tenant_data.units")])
    assert thay == [["A-01"], ["B-01"], ["A-01"], ["B-01"], ["A-01"]]


async def test_quyen_khong_rong_hon_agent_all(pool):
    """Bề mặt của `odyssey_agent` = bề mặt của `agent_all`, từng bảng từng quyền.

    So SÁNH với `agent_all` thay vì liệt kê một allow-list tên bảng: allow-list phải
    có người nhớ cập nhật khi module sau thêm bảng, còn phép so sánh này tự đúng mãi —
    thêm bảng `tenant_data` mới mà agent cần đọc thì phải GRANT tường minh cho
    `agent_all` (`0917` bỏ default privileges tự động của `agent_api` cũ, chính vì lý
    do này), nên cả hai role vẫn bằng nhau. Nó chỉ đỏ đúng lúc cần đỏ: khi ai đó GRANT
    thẳng một quyền cho `odyssey_agent` mà không đi qua nhóm — tức là mở một bề mặt
    không ai canh.
    """
    async with pool.acquire() as conn:
        bang = await conn.fetch(
            """SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('control', 'tenant_data', 'portal')
                  AND c.relkind IN ('r', 'v', 'm', 'p')
                ORDER BY n.nspname, c.relname"""
        )
        assert bang, "không có bảng nào trong bốn schema — migration chưa chạy?"

        lech = []
        for r in bang:
            ten = f"{r['nspname']}.{r['relname']}"
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                cua_role = await conn.fetchval("SELECT has_table_privilege($1, $2, $3)", ROLE, ten, priv)
                cua_nhom = await conn.fetchval("SELECT has_table_privilege('agent_all', $1, $2)", ten, priv)
                if cua_role is not cua_nhom:
                    lech.append(f"{ten}:{priv} — {ROLE}={cua_role}, agent_all={cua_nhom}")
    assert lech == [], (
        f"quyền của {ROLE} lệch khỏi agent_all:\n  "
        + "\n  ".join(lech)
        + f"\nMọi quyền của {ROLE} phải đến từ tư cách thành viên `agent_all`. Một GRANT thẳng "
        "cho role này mở bề mặt mà không cổng nào canh — và nó là role LOGIN, nên một mật khẩu "
        "lộ là mọi tenant."
    )
