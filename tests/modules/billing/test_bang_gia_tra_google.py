"""`0975`: bảng giá mặc định mới chép nguyên bản `0954`, chỉ tra Google của dữ liệu ngoài còn 364 đ/lượt."""

import asyncpg
import pytest

pytestmark = pytest.mark.integration

_GIA = """SELECT pi.component, pi.purpose, pi.provider, pi.model, pi.metric, pi.unit_price, pi.per_units
            FROM billing.price_item pi JOIN billing.price_version pv ON pv.id = pi.price_version_id
           WHERE pv.code = $1"""


async def test_ban_moi_la_mac_dinh_va_chi_khac_gia_tra_google(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        mac_dinh = await conn.fetchval("SELECT code FROM billing.price_version WHERE is_default")
        cu = {tuple(r)[:5]: tuple(r)[5:] for r in await conn.fetch(_GIA, "vendor-vnd-2026-08")}
        moi = {tuple(r)[:5]: tuple(r)[5:] for r in await conn.fetch(_GIA, "vendor-vnd-2026-10")}
    assert mac_dinh == "vendor-vnd-2026-10"
    assert moi.keys() == cu.keys()
    khac = {k for k in moi if moi[k] != cu[k]}
    assert khac == {("search", "kb_web", "google", "gemini-2.5-flash", "units")}
    assert moi[("search", "kb_web", "google", "gemini-2.5-flash", "units")][0] == 364
