# tests/modules/playbook/test_repo.py
import json
from datetime import UTC, datetime, timedelta

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.playbook import nut, repo

from .conftest import TENANT, TENANT_KHAC, nhan, them_nhan, them_phien

H = {n["id"]: n["hash"] for n in nut.doc()["nodes"]}

# `conn_pb` = tenant_conn giữ transaction suốt test (như `conn_ops`) — repo đọc trong cùng transaction nên thấy seed.


def test_doc_nut():
    d = nut.doc()
    assert d["promptVersion"].startswith("v") and any(n["id"] == "che_dat" for n in d["nodes"])


async def test_dem_va_ti_le(conn_pb):
    await them_phien(conn_pb, "s1", phone="0900000001", ten="A", chuyen=False)
    await them_nhan(conn_pb, "s1", 1, nhan(dat=True, jev_nut="che_dat"))
    await them_nhan(conn_pb, "s1", 3, nhan(dat=False, thieu=["kết nối lợi ích"], vi_pham_cam=["tự giảm giá"]))
    await them_nhan(conn_pb, "s1", 5, nhan(dat=None, loi="timeout"))  # chưa chấm
    await them_nhan(conn_pb, "s1", 7, nhan(dat=True, loi="parse"))  # có loi ⇒ không tính đạt
    await them_nhan(conn_pb, "s1", 9, nhan(dat=False, thieu_du_lieu=True, jev_nut="che_xa"))
    r = await repo.so_do(conn_pb, ngay=7, nguon=None, v="v3", hash_nut=H)
    t = r["theo_nut"]["che_dat"]
    assert (t["so_luot"], t["da_cham"], t["dat"], t["thieu_du_lieu"]) == (5, 3, 1, 1)
    assert (t["jev_so"], t["jev_khop"]) == (2, 1)
    assert r["hay_thieu"]["che_dat"] == [("kết nối lợi ích", 1)]
    assert r["hay_pham"]["che_dat"] == [("tự giảm giá", 1)]
    assert r["co_du_lieu"] is True


async def test_top3_thieu(conn_pb):
    for i, muc in enumerate(["a", "a", "a", "b", "b", "c", "d"]):
        await them_nhan(conn_pb, "s2", 2 * i + 1, nhan(dat=False, thieu=[muc]))
    r = await repo.so_do(conn_pb, ngay=7, nguon=None, v="v3", hash_nut=H)
    assert r["hay_thieu"]["che_dat"] == [("a", 3), ("b", 2), ("c", 1)]  # hoà số lần → theo tên (ORDER BY 3 DESC, 2)


async def test_loc_ngay_nguon_va_phien_ban(conn_pb):
    cu = datetime.now(UTC) - timedelta(days=10)
    await them_phien(conn_pb, "web1", phone=None, ten=None, chuyen=False, source="web")
    await them_phien(conn_pb, "zalo1", phone=None, ten=None, chuyen=False, source="zalo")
    await them_nhan(conn_pb, "web1", 1, nhan())
    await them_nhan(conn_pb, "zalo1", 1, nhan())
    await them_nhan(conn_pb, "zalo1", 3, nhan(), created_at=cu)  # ngoài 7 ngày
    await them_nhan(conn_pb, "khong_phien", 1, nhan())  # không có hàng conversations
    await them_nhan(conn_pb, "web1", 3, nhan(v="v2"))  # phiên bản cũ
    r7 = await repo.so_do(conn_pb, ngay=7, nguon=None, v="v3", hash_nut=H)
    assert r7["theo_nut"]["che_dat"]["so_luot"] == 3 and r7["phien_ban_cu"] == 1
    assert sorted(r7["nguon"]) == ["web", "zalo"]
    assert (await repo.so_do(conn_pb, ngay=30, nguon=None, v="v3", hash_nut=H))["theo_nut"]["che_dat"]["so_luot"] == 4
    assert (await repo.so_do(conn_pb, ngay=7, nguon="web", v="v3", hash_nut=H))["theo_nut"]["che_dat"]["so_luot"] == 1


async def test_meta_hong_bi_bo_qua(conn_pb):
    await them_nhan(conn_pb, "s3", 1, '{"playbook": "chuoi"}')
    await them_nhan(
        conn_pb,
        "s3",
        3,
        json.dumps({"playbook": {"nut": "che_dat", "v": "v3", "h": H["che_dat"], "dat": "co", "thieu": "x"}}),
    )
    await them_nhan(conn_pb, "s3", 5, '{"playbook": {"v": "v3"}}')
    r = await repo.so_do(conn_pb, ngay=7, nguon=None, v="v3", hash_nut=H)  # không ném lỗi
    t = r["theo_nut"]["che_dat"]
    assert t["so_luot"] == 1 and t["da_cham"] == 0 and r["hay_thieu"].get("che_dat", []) == []


async def test_khong_du_lieu(conn_pb):
    r = await repo.so_do(conn_pb, ngay=7, nguon=None, v="v3", hash_nut=H)
    assert r["co_du_lieu"] is False and r["theo_nut"] == {}


async def test_luot_cua_nut(conn_pb):
    await them_phien(conn_pb, "s4", phone="0900000004", ten="B", chuyen=False)
    await them_nhan(conn_pb, "s4", 1, nhan(dat=True), user="câu 1")
    await them_nhan(conn_pb, "s4", 3, nhan(dat=False, thieu=["x"]), user="câu 2")
    await them_nhan(conn_pb, "s4", 5, nhan("nut_da_bo", dat=False), user="câu 3")
    tat_ca = await repo.luot_cua_nut(
        conn_pb, nut="che_dat", ngay=7, nguon=None, v="v3", h=H.get("che_dat", ""), chi_khong_dat=False, limit=20
    )
    assert [r["seq"] for r in tat_ca] == [3, 1] and tat_ca[0]["khach"] == "câu 2" and tat_ca[0]["phone"] == "0900000004"
    kd = await repo.luot_cua_nut(
        conn_pb, nut="che_dat", ngay=7, nguon=None, v="v3", h=H.get("che_dat", ""), chi_khong_dat=True, limit=20
    )
    assert [r["seq"] for r in kd] == [3]
    cu = await repo.luot_cua_nut(
        conn_pb, nut="nut_da_bo", ngay=7, nguon=None, v="v3", h=H.get("nut_da_bo", ""), chi_khong_dat=False, limit=20
    )
    assert len(cu) == 1
    assert (
        len(
            await repo.luot_cua_nut(
                conn_pb, nut="che_dat", ngay=7, nguon=None, v="v3", h=H.get("che_dat", ""), chi_khong_dat=False, limit=1
            )
        )
        == 1
    )


async def test_cach_ly_tenant(pool, workspace_pb):
    async with tenant_conn(pool, TENANT_KHAC) as ck:  # commit trước khi đọc bằng kết nối tenant chính
        await them_phien(ck, "kx", tenant=TENANT_KHAC)
        await them_nhan(ck, "kx", 1, nhan(dat=True), tenant=TENANT_KHAC)
    async with tenant_conn(pool, TENANT) as c:
        await them_phien(c, "cx")
        await them_nhan(c, "cx", 1, nhan(dat=True))
        r = await repo.so_do(c, ngay=7, nguon=None, v="v3", hash_nut=H)
        assert r["theo_nut"]["che_dat"]["so_luot"] == 1
        luot = await repo.luot_cua_nut(
            c, nut="che_dat", ngay=7, nguon=None, v="v3", h=H.get("che_dat", ""), chi_khong_dat=False, limit=20
        )
        assert [x["session_id"] for x in luot] == ["cx"]
    async with tenant_conn(pool, TENANT_KHAC) as ck:  # dữ liệu tenant khác vẫn còn (không bị xoá nhầm)
        assert (await repo.so_do(ck, ngay=7, nguon=None, v="v3", hash_nut=H))["theo_nut"]["che_dat"]["so_luot"] == 1


async def test_nguon_khong_thu_hep_danh_sach(conn_pb):
    await them_phien(conn_pb, "w", phone=None, ten=None, chuyen=False, source="web")
    await them_phien(conn_pb, "z", phone=None, ten=None, chuyen=False, source="zalo")
    await them_nhan(conn_pb, "w", 1, nhan())
    await them_nhan(conn_pb, "z", 1, nhan())
    r = await repo.so_do(conn_pb, ngay=7, nguon="web", v="v3", hash_nut=H)
    assert r["nguon"] == ["web", "zalo"] and r["co_du_lieu"] is True
    r = await repo.so_do(
        conn_pb, ngay=7, nguon="khac", v="v3", hash_nut=H
    )  # nguồn không có nhãn: rỗng nhưng vẫn có dữ liệu
    assert r["theo_nut"] == {} and r["co_du_lieu"] is True and r["nguon"] == ["web", "zalo"]


async def test_phan_tu_null_trong_thieu_bi_bo_qua(conn_pb):
    await them_nhan(conn_pb, "n1", 1, nhan(dat=False, thieu=[None, "x"], vi_pham_cam=[None]))
    r = await repo.so_do(conn_pb, ngay=7, nguon=None, v="v3", hash_nut=H)
    assert r["hay_thieu"]["che_dat"] == [("x", 1)] and r["hay_pham"]["che_dat"] == []


@pytest.mark.parametrize(
    "noi_dung",
    [
        {"promptVersion": "v3", "nodes": [{"id": "a"}]},  # thiếu version
        {"version": "1", "promptVersion": "v3", "nodes": [{"ten": "không id"}]},
        {"version": "1", "promptVersion": "v3", "nodes": ["chuỗi"]},
        # thiếu gioiHan
        {
            "version": "1",
            "promptVersion": "v4",
            "templateVersion": "t",
            "nodes": [{"id": "a", "lop": "sale", "hash": "h"}],
        },
    ],
)
def test_doc_nut_hong(tmp_path, monkeypatch, noi_dung):
    f = tmp_path / "playbook.json"
    f.write_text(json.dumps(noi_dung), encoding="utf-8")
    monkeypatch.setattr(nut, "_FILE", f)
    with pytest.raises(RuntimeError):
        nut.doc.__wrapped__()


async def test_dem_theo_hash_nut(conn_pb):
    await them_nhan(conn_pb, "h1", 1, nhan(h="moi"))
    await them_nhan(conn_pb, "h1", 3, nhan(h="cu"))
    await them_nhan(conn_pb, "h1", 5, nhan(h=None))  # nhãn trước đợt 2
    await them_nhan(conn_pb, "h1", 7, nhan("nut_da_bo", h="z"))
    r = await repo.so_do(conn_pb, ngay=7, nguon=None, v="v3", hash_nut={"che_dat": "moi"})
    assert r["theo_nut"]["che_dat"]["so_luot"] == 1 and r["phien_ban_cu"] == 2
    assert r["theo_nut"]["nut_da_bo"]["so_luot"] == 1  # nút không còn trong bộ → router đưa vào nutCu


async def test_luot_loc_theo_hash(conn_pb):
    await them_nhan(conn_pb, "h2", 1, nhan(h="moi"))
    await them_nhan(conn_pb, "h2", 3, nhan(h="cu"))
    rows = await repo.luot_cua_nut(
        conn_pb, nut="che_dat", ngay=7, nguon=None, v="v3", h="moi", chi_khong_dat=False, limit=20
    )
    assert [r["seq"] for r in rows] == [1]
