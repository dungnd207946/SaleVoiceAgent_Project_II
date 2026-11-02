import json

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.playbook import nut

from .conftest import TENANT

pytestmark = pytest.mark.asyncio
TV = nut.doc()["templateVersion"]
RIENG = {
    "id": "rieng_mau_son",
    "ten": "Chê màu sơn",
    "nhom": "phan_doi",
    "dau_hieu": ["khách chê màu sơn"],
    "lam": ["gửi ảnh mẫu màu thật"],
}


def _mau():
    return [nut.chuan_hoa(j) for j in nut.template_sale()]


def _xoa_duoc() -> str:
    mau = _mau()
    dich = {d["lan_2"] for d in mau + nut.he_thong() if d["lan_2"]}
    return next(
        d["id"] for d in mau if d["id"] not in nut.gioi_han()["khoaXoa"] and d["id"] not in dich and not d["lan_2"]
    )


async def _nhat_ky(pool, ma):
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT chi_tiet FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = $2", TENANT, ma
        )
    return [json.loads(r["chi_tiet"]) if isinstance(r["chi_tiet"], str) else r["chi_tiet"] for r in rows]


async def _agent_version(pool):
    async with tenant_conn(pool, TENANT) as c:
        return await c.fetchval(
            "SELECT version FROM tenant_data.agent_config WHERE tenant_id = $1 AND role = 'customer'", TENANT
        )


@pytest.fixture
async def co_agent_config(pool, workspace_pb):
    async with tenant_conn(pool, TENANT) as c:
        await c.execute(
            "INSERT INTO tenant_data.agent_config (tenant_id, role, name, brand_name, tone, reply_length, version)"
            " VALUES ($1, 'customer', 'Mai', 'An Phú', 'lich_su', 'ngan', 1)",
            TENANT,
        )


async def test_mac_dinh_chay_mau(client_pb):
    d = (await client_pb.get("/api/v1/playbook")).json()
    assert d["kichBan"] == {
        "trangThai": "mau",
        "version": 0,
        "tuTemplate": None,
        "templateVersion": TV,
        "coTemplateMoi": False,
        "roleDung": ["customer"],
        "capNhatLuc": None,
        "capNhatBoi": None,
    }
    assert {n["id"] for n in d["nodes"]} == {n["id"] for n in nut.doc()["nodes"]}


async def test_template(client_pb):
    d = (await client_pb.get("/api/v1/playbook/template")).json()
    assert d["templateVersion"] == TV and {n["lop"] for n in d["nodes"]} == {"sale"}


async def test_ap_dung_roi_luu(client_pb, pool, co_agent_config):
    r = await client_pb.post("/api/v1/playbook/ap-dung", json={"version": 0})
    assert r.status_code == 200, r.text
    kb = r.json()
    assert (kb["trangThai"], kb["version"], kb["tuTemplate"], kb["coTemplateMoi"]) == ("rieng", 1, TV, False)
    assert await _agent_version(pool) == 2
    xoa = _xoa_duoc()
    bo = [{**d, "lam": ["mời khách xem bảng tính vay"]} if d["id"] == "che_dat" else d for d in _mau()]
    bo = [d for d in bo if d["id"] != xoa] + [RIENG]
    r = await client_pb.put("/api/v1/playbook", json={"version": 1, "nut": bo})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2 and await _agent_version(pool) == 3
    by = {n["id"]: n for n in (await client_pb.get("/api/v1/playbook")).json()["nodes"]}
    assert by["che_dat"]["lam"] == ["mời khách xem bảng tính vay"] and by["rieng_mau_son"]["lop"] == "sale"
    assert by["rieng_mau_son"]["trang_thai"] == "dung" and "khac" in by and xoa not in by
    (ct,) = await _nhat_ky(pool, "playbook.luu")
    assert (ct["version"], ct["them"], ct["sua"], ct["xoa"]) == (2, ["rieng_mau_son"], ["che_dat"], [xoa])
    (ad,) = await _nhat_ky(pool, "playbook.ap_dung")
    assert ad == {"version": 1, "tuTemplate": TV, "apLai": False}


async def test_luu_khi_chua_ap_dung(client_pb):
    r = await client_pb.put("/api/v1/playbook", json={"version": 0, "nut": _mau()})
    assert r.status_code == 200, r.text
    assert (r.json()["trangThai"], r.json()["tuTemplate"]) == ("rieng", TV)


async def test_lech_version_409_khong_doi_gi(client_pb, pool, co_agent_config):
    await client_pb.post("/api/v1/playbook/ap-dung", json={"version": 0})
    v = await _agent_version(pool)
    r = await client_pb.put("/api/v1/playbook", json={"version": 0, "nut": _mau()})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PLAYBOOK_DA_DOI"
    assert await _agent_version(pool) == v and await _nhat_ky(pool, "playbook.luu") == []


async def test_role_dung_roi_ap_dung(client_pb, pool):
    r = await client_pb.put("/api/v1/playbook/role-dung", json={"version": 0, "roles": []})
    assert r.status_code == 200, r.text
    assert (r.json()["roleDung"], r.json()["trangThai"], r.json()["version"]) == ([], "mau", 1)
    assert (await client_pb.post("/api/v1/playbook/ap-dung", json={"version": 0})).status_code == 409
    r = await client_pb.post("/api/v1/playbook/ap-dung", json={"version": 1})
    assert (r.json()["trangThai"], r.json()["roleDung"]) == ("rieng", [])
    assert await _nhat_ky(pool, "playbook.role_dung") == [{"version": 1, "roles": []}]


async def test_role_la_422(client_pb):
    r = await client_pb.put("/api/v1/playbook/role-dung", json={"version": 0, "roles": ["sale"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "PLAYBOOK_ROLE_KHONG_CO"


async def test_422_chi_dung_nut_va_truong(client_pb):
    bo = _mau() + [{**RIENG, "lam": ["x"] * 7}]
    r = await client_pb.put("/api/v1/playbook", json={"version": 0, "nut": bo})
    assert r.status_code == 422
    assert {"field": f"body.nut[{len(bo) - 1}].lam", "reason": "tối đa 6 dòng"} in r.json()["error"]["fields"]


async def test_422_truong_la(client_pb):
    r = await client_pb.put("/api/v1/playbook", json={"version": 0, "nut": [{**RIENG, "hien": "x"}]})
    assert r.status_code == 422


async def test_co_template_moi(client_pb, pool):
    await client_pb.post("/api/v1/playbook/ap-dung", json={"version": 0})
    async with tenant_conn(pool, TENANT) as c:
        await c.execute("UPDATE tenant_data.kich_ban SET tu_template = 'cu' WHERE tenant_id = $1", TENANT)
    assert (await client_pb.get("/api/v1/playbook")).json()["kichBan"]["coTemplateMoi"] is True


async def test_nguoi_xem_doc_duoc_khong_ghi_duoc(client_pb, pool):
    async with pool.acquire() as c:
        await c.execute(
            "UPDATE control.memberships SET role_id = (SELECT id FROM control.roles WHERE name = 'Người xem')"
            " WHERE user_id = 'u_pb'"
        )
    assert (await client_pb.get("/api/v1/playbook")).status_code == 200
    assert (await client_pb.post("/api/v1/playbook/ap-dung", json={"version": 0})).status_code == 403
    assert (await client_pb.put("/api/v1/playbook", json={"version": 0, "nut": []})).status_code == 403
    assert (await client_pb.put("/api/v1/playbook/role-dung", json={"version": 0, "roles": []})).status_code == 403


async def test_sua_nut_chi_nut_do_dem_lai(client_pb, pool):
    from .conftest import nhan, them_nhan, them_phien

    v = nut.doc()["promptVersion"]
    async with tenant_conn(pool, TENANT) as c:
        await them_phien(c, "d1")
        await them_nhan(c, "d1", 1, nhan(v=v))
        await them_nhan(c, "d1", 3, nhan("dat_lich", v=v))
    await client_pb.post("/api/v1/playbook/ap-dung", json={"version": 0})
    d = (await client_pb.get("/api/v1/playbook")).json()
    assert d["soDo"]["che_dat"]["soLuot"] == 1 and d["soDo"]["dat_lich"]["soLuot"] == 1  # áp dụng không sửa: giữ số
    bo = [{**x, "lam": ["chữ mới"]} if x["id"] == "che_dat" else x for x in _mau()]
    assert (await client_pb.put("/api/v1/playbook", json={"version": 1, "nut": bo})).status_code == 200
    d = (await client_pb.get("/api/v1/playbook")).json()
    assert "che_dat" not in d["soDo"] and d["soDo"]["dat_lich"]["soLuot"] == 1 and d["phienBanCu"] == 1
    assert (await client_pb.get("/api/v1/playbook/che_dat/luot")).json() == {"luot": []}


async def test_template_tra_gioi_han(client_pb):
    d = (await client_pb.get("/api/v1/playbook/template")).json()
    assert d["gioiHan"] == nut.gioi_han()
