# tests/modules/playbook/test_api.py
import pytest

from portal.core.db.session import tenant_conn
from portal.modules.playbook import nut

from .conftest import nhan, them_nhan, them_phien

# Nhãn đo khớp phiên bản classifier của bộ nút đang chép (router lọc theo promptVersion).
V = nut.doc()["promptVersion"]

pytestmark = pytest.mark.asyncio

# Seed phải COMMIT trước khi gọi API (API mở kết nối riêng) — mỗi khối `tenant_conn` một transaction,
# thoát khối là commit. KHÔNG dùng fixture `conn_pb` ở file này (nó giữ transaction tới teardown).


async def test_playbook_so_do(client_pb, pool, workspace_pb):
    async with tenant_conn(pool, workspace_pb) as c:
        await them_phien(c, "s1", phone="0900000001", ten="A", chuyen=False)
        await them_nhan(c, "s1", 1, nhan(dat=True, jev_nut="che_dat", v=V))
        await them_nhan(c, "s1", 3, nhan(dat=False, thieu=["x"], v=V))
        await them_nhan(c, "s1", 5, nhan("nut_da_bo", dat=True, v=V))
    r = await client_pb.get("/api/v1/playbook?ngay=7")
    assert r.status_code == 200
    d = r.json()
    assert d["promptVersion"].startswith("v") and any(n["id"] == "che_dat" for n in d["nodes"])
    s = d["soDo"]["che_dat"]
    assert (s["soLuot"], s["daCham"], s["dat"], s["tiLeDat"], s["jevKhop"]) == (2, 2, 1, 0.5, 1.0)
    assert s["hayThieu"] == [{"ten": "x", "so": 1}]
    assert d["nutCu"] == {"nut_da_bo": 1} and "nut_da_bo" not in d["soDo"] and d["coDuLieu"] is True


async def test_ngay_khong_hop_le(client_pb):
    assert (await client_pb.get("/api/v1/playbook?ngay=5")).status_code == 422


async def test_luot(client_pb, pool, workspace_pb):
    async with tenant_conn(pool, workspace_pb) as c:
        await them_phien(c, "s2", phone="0900000002", ten="B", chuyen=False)
        await them_nhan(c, "s2", 1, nhan(dat=False, thieu=["y"], buoc="b1", v=V), user="đắt quá")
    r = await client_pb.get("/api/v1/playbook/che_dat/luot?dat=false")
    assert r.status_code == 200
    (it,) = r.json()["luot"]
    assert (it["sessionId"], it["seq"], it["khach"], it["dat"], it["thieu"], it["buoc"]) == (
        "s2",
        1,
        "đắt quá",
        False,
        ["y"],
        "b1",
    )
    assert (await client_pb.get("/api/v1/playbook/khong_co/luot")).json() == {"luot": []}
    assert (await client_pb.get("/api/v1/playbook/che_dat/luot?limit=51")).status_code == 422


async def test_json_hong_500(client_pb, monkeypatch):
    def hong():
        raise RuntimeError("playbook.json hỏng: x")

    monkeypatch.setattr(nut, "doc", hong)
    assert (await client_pb.get("/api/v1/playbook")).status_code == 500


async def test_thieu_quyen_403(client_pb, pool, workspace_pb):
    # Route khai `require(AGENT_CONFIG_READ)` — cổng tests/api/test_moi_route_khai_action.py quét mọi route;
    # ở đây kiểm hành vi: thành viên mất quyền → 403.
    async with pool.acquire() as c:
        await c.execute("INSERT INTO control.roles (id, name) VALUES ('r_pb_rong', 'Rỗng PB')")
        await c.execute("UPDATE control.memberships SET role_id = 'r_pb_rong' WHERE user_id = 'u_pb'")
    assert (await client_pb.get("/api/v1/playbook")).status_code == 403
    assert (await client_pb.get("/api/v1/playbook/che_dat/luot")).status_code == 403
    async with pool.acquire() as c:  # dọn: xoá membership qua teardown tenant, rồi role
        await c.execute("DELETE FROM control.memberships WHERE user_id = 'u_pb'")
        await c.execute("DELETE FROM control.roles WHERE id = 'r_pb_rong'")


async def test_luot_bo_phan_tu_khong_phai_chuoi(client_pb, pool, workspace_pb):
    async with tenant_conn(pool, workspace_pb) as c:
        await them_nhan(c, "nl", 1, nhan(dat=False, thieu=[None, "x"], vi_pham_cam=[3, "y"], v=V))
    r = (await client_pb.get("/api/v1/playbook/che_dat/luot")).json()["luot"][0]
    assert r["thieu"] == ["x"] and r["viPhamCam"] == ["y"]
