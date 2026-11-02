"""2 route /linh-vuc — khuôn module kb: gọi thẳng handler, Principal dựng sẵn.

`actions=frozenset()` vì require() là dependency của FastAPI, không chạy khi
gọi thẳng — phép kiểm «route nào khai action nào» thuộc cổng
tests/api/test_moi_route_khai_action.py, tự quét mọi APIRoute.
"""

import pytest

from portal.api.loi import LoiPortal
from portal.core.auth.principal import Principal
from portal.core.db.session import tenant_conn
from portal.modules.linh_vuc import router
from portal.modules.linh_vuc.contracts import DatLinhVucIn

from .conftest import OTHER_TENANT, TENANT

_P = Principal(user_id="u_seed_test", tenant_id=TENANT, role="Quản trị", actions=frozenset())
_P_KHAC = Principal(user_id="u_seed_test", tenant_id=OTHER_TENANT, role="Quản trị", actions=frozenset())


async def test_get_sau_backfill(api_pool, seed_lv):
    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert [(o.ma, o.bat) for o in ds] == [("bds", True), ("taichinh", False)]
    assert (ds[0].soKyNang, ds[1].soKyNang) == (8, 0)
    assert (ds[0].ten, ds[1].ten) == ("Bất động sản", "Tài chính")
    # tenant mới chỉ có sentinel — chưa tính là có dữ liệu
    assert (ds[0].coDuLieu, ds[1].coDuLieu) == (False, False)


async def test_patch_tat_roi_bat_lai(api_pool, seed_lv):
    o = await router.dat(ma="bds", body=DatLinhVucIn(bat=False), p=_P, pool=api_pool)
    assert o.bat is False and o.ma == "bds"

    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert ds[0].bat is False  # GET đọc lại đúng trạng thái vừa ghi

    o = await router.dat(ma="bds", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)
    o = await router.dat(ma="bds", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)  # idempotent
    assert o.bat is True


async def test_patch_ma_la_404(api_pool, seed_lv):
    with pytest.raises(LoiPortal) as e:
        await router.dat(ma="chungkhoan", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)
    assert e.value.ma == "LINH_VUC_KHONG_TON_TAI" and e.value.http == 404


async def test_patch_khong_lan_sang_tenant_khac(api_pool, seed_lv):
    await router.dat(ma="bds", body=DatLinhVucIn(bat=False), p=_P, pool=api_pool)
    ds = await router.liet_ke(p=_P_KHAC, pool=api_pool)
    assert ds[0].bat is True


async def test_patch_ghi_nhat_ky(api_pool, pool, seed_lv):
    await router.dat(ma="bds", body=DatLinhVucIn(bat=False), p=_P, pool=api_pool)
    await router.dat(ma="bds", body=DatLinhVucIn(bat=True), p=_P, pool=api_pool)
    async with pool.acquire() as conn:
        hd = [
            r["hanh_dong"]
            for r in await conn.fetch(
                "SELECT hanh_dong FROM control.audit_log WHERE tenant_id = $1 "
                "AND hanh_dong LIKE 'linh_vuc.%' ORDER BY id",
                TENANT,
            )
        ]
    assert hd == ["linh_vuc.tat", "linh_vuc.bat"]


async def test_co_du_lieu_doi_theo_du_an(api_pool, seed_lv):
    async with tenant_conn(api_pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
            "VALUES (portal.current_tenant(), 'nplb', 'Noble Palace', 'published')"
        )
    ds = await router.liet_ke(p=_P, pool=api_pool)
    assert ds[0].coDuLieu is True
    assert ds[1].coDuLieu is False  # taichinh là hằng False, không query


async def test_route_len_app():
    """`api/app.py::ROUTERS` gắn ROUTER của module — thiếu dòng đó là 404 không lỗi nào."""
    from portal.api.app import ROUTERS

    routers = dict(ROUTERS)
    assert "linh_vuc" in routers
    paths = {r.path for r in routers["linh_vuc"].routes}
    assert paths == {"/linh-vuc", "/linh-vuc/{ma}"}
