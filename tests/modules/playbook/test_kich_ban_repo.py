import pytest

from portal.modules.config import contracts as config_contracts
from portal.modules.playbook import kich_ban

from .conftest import TENANT


async def test_chua_co_hang(conn_pb):
    assert await kich_ban.doc(conn_pb) is None
    assert await kich_ban.role_co(conn_pb) == {"customer"}


async def test_them_roi_sua(conn_pb):
    h = await kich_ban.ghi(conn_pb, TENANT, version=0, actor="u_pb", nut=[{"id": "che_dat"}], tu_template="t1")
    assert (h["version"], h["tu_template"], list(h["role_dung"]), h["updated_by"]) == (1, "t1", ["customer"], "u_pb")
    h = await kich_ban.ghi(conn_pb, TENANT, version=1, actor="u_pb", nut=[{"id": "x"}], tu_template="t2")
    assert h["version"] == 2 and h["tu_template"] == "t1"  # đã áp dụng: lưu giữ tu_template
    h = await kich_ban.ghi(
        conn_pb, TENANT, version=2, actor="u_pb", nut=[{"id": "y"}], tu_template="t3", ghi_de_template=True
    )
    assert h["tu_template"] == "t3"


async def test_chi_role_roi_luu(conn_pb):
    h = await kich_ban.ghi(conn_pb, TENANT, version=0, actor="u", role_dung=["customer", "sale"])
    assert h["nut"] is None and h["tu_template"] is None
    h = await kich_ban.ghi(conn_pb, TENANT, version=1, actor="u", nut=[{"id": "a"}], tu_template="t")
    assert h["tu_template"] == "t" and list(h["role_dung"]) == ["customer", "sale"]


async def test_lech_version(conn_pb):
    await kich_ban.ghi(conn_pb, TENANT, version=0, actor="u", role_dung=["customer"])
    with pytest.raises(kich_ban.DaDoi):
        await kich_ban.ghi(conn_pb, TENANT, version=0, actor="u", role_dung=[])
    with pytest.raises(kich_ban.DaDoi):
        await kich_ban.ghi(conn_pb, TENANT, version=5, actor="u", role_dung=[])


async def test_bao_agent_doi(conn_pb):
    assert await config_contracts.bao_agent_doi(conn_pb, TENANT) is None  # chưa có hàng agent_config
    await conn_pb.execute(
        "INSERT INTO tenant_data.agent_config (tenant_id, role, name, brand_name, tone, reply_length, version)"
        " VALUES ($1, 'customer', 'Mai', 'An Phú', 'lich_su', 'ngan', 4)",
        TENANT,
    )
    assert await config_contracts.bao_agent_doi(conn_pb, TENANT) == 5
