"""Lead (stage · điểm · đối tượng) trên /convos — mỗi test neo một luật của spec §2."""

import pytest

from portal.modules.ops import repo

from .conftest import TENANT_KHAC, luc, them_ca, them_phien

pytestmark = pytest.mark.asyncio

MOI = {"tu_ngay": "all"}
A = "0911000001"
B = "0911000002"
C = "0911000003"


async def _mot(conn, phone):
    hang = await repo.liet_ke_khach(conn, tu_ngay="all")
    return next(r for r in hang if r["phone"] == phone)


async def test_lead_khach_la_cua_phien_moi_nhat_co_lead(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_phien(conn_ops, "s2", phone=A, bat_dau=luc(25))
    await them_phien(conn_ops, "s3", phone=A, bat_dau=luc(27))  # phiên mới nhất KHÔNG chuyển sale
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql", lead_score=80, tao_luc=luc(20))
    await them_ca(conn_ops, "s2", phone=A, lead_stage="lead", lead_score=40, tao_luc=luc(25))

    r = await _mot(conn_ops, A)

    assert (r["lead_stage"], r["lead_score"]) == ("lead", 40)


async def test_trong_phien_hang_null_moi_hon_bi_bo_qua(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="mql", lead_score=65, tao_luc=luc(20, 10))
    await them_ca(conn_ops, "s1", phone=A, tao_luc=luc(20, 11))  # hàng mới hơn, không có lead

    r = await _mot(conn_ops, A)

    assert r["lead_stage"] == "mql"


async def test_ba_truong_lay_tu_cung_mot_hang(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql", lead_score=70, audience="broker", tao_luc=luc(20, 10))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="lead", lead_score=30, audience=None, tao_luc=luc(20, 11))

    r = await _mot(conn_ops, A)

    assert (r["lead_stage"], r["lead_score"], r["audience"]) == ("lead", 30, None)


async def test_khach_khong_co_lead_ra_null(conn_ops):
    await them_phien(conn_ops, "s1", phone=C, bat_dau=luc(20))

    r = await _mot(conn_ops, C)

    assert (r["lead_stage"], r["lead_score"], r["audience"]) == (None, None, None)


async def _ba_khach(conn):
    # A: từng SQL, nay Lead · B: SQL · C: chưa có lead
    await them_phien(conn, "a1", phone=A, bat_dau=luc(20))
    await them_phien(conn, "a2", phone=A, bat_dau=luc(25))
    await them_ca(conn, "a1", phone=A, lead_stage="sql", tao_luc=luc(20))
    await them_ca(conn, "a2", phone=A, lead_stage="lead", tao_luc=luc(25))
    await them_phien(conn, "b1", phone=B, bat_dau=luc(22))
    await them_ca(conn, "b1", phone=B, lead_stage="sql", tao_luc=luc(22))
    await them_phien(conn, "c1", phone=C, bat_dau=luc(23))
    await them_phien(conn, "c2", phone=C, bat_dau=luc(24))


async def test_loc_sql_theo_lead_moi_nhat_khong_theo_lich_su(conn_ops):
    await _ba_khach(conn_ops)

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all", lead_stage="sql")

    assert [r["phone"] for r in hang] == [B]


async def test_loc_none_la_khach_khong_co_lead(conn_ops):
    await _ba_khach(conn_ops)

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all", lead_stage="none")

    assert [r["phone"] for r in hang] == [C]


async def test_dem_tong_theo_dung_bo_loc(conn_ops):
    await _ba_khach(conn_ops)

    assert await repo.dem_tong(conn_ops, tu_ngay="all", lead_stage="none") == (1, 2)
    assert await repo.dem_tong(conn_ops, tu_ngay="all", lead_stage="sql") == (1, 1)
    assert await repo.dem_tong(conn_ops, tu_ngay="all") == (3, 5)


async def test_loc_ap_truoc_phan_trang(conn_ops):
    await _ba_khach(conn_ops)

    hang = await repo.liet_ke_khach(conn_ops, tu_ngay="all", lead_stage="none", limit=1, offset=0)

    assert [r["phone"] for r in hang] == [C]


async def test_lead_tenant_khac_khong_lot_sang(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20), tenant=TENANT_KHAC)
    await them_ca(conn_ops, "s1", phone=A, lead_stage="hen_gap", tenant=TENANT_KHAC)

    r = await _mot(conn_ops, A)

    assert r["lead_stage"] is None


async def test_api_tra_camelcase(client_ops, pool):
    # Seed bằng `pool` + COMMIT — `conn_ops` là một giao dịch chưa commit, request API
    # chạy trên kết nối khác không thấy nó (cùng khuôn `test_ten_du_an.py`).
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s1", phone=A, bat_dau=luc(20))
        await them_ca(conn, "s1", phone=A, lead_stage="hen_gap", lead_score=90, audience="end_user")

    r = await client_ops.get("/api/v1/convos/khach", params=MOI)

    k = next(i for i in r.json()["items"] if i["phone"] == A)
    assert (k["leadStage"], k["leadScore"], k["audience"]) == ("hen_gap", 90, "end_user")


async def test_api_loc_theo_lead_stage(client_ops, pool):
    async with pool.acquire() as conn, conn.transaction():
        await _ba_khach(conn)

    r = await client_ops.get("/api/v1/convos/khach", params={**MOI, "lead_stage": "sql"})

    assert r.status_code == 200
    assert [i["phone"] for i in r.json()["items"]] == [B]
    assert r.json()["tongKhach"] == 1


async def test_api_lead_stage_la_thi_422(client_ops):
    r = await client_ops.get("/api/v1/convos/khach", params={**MOI, "lead_stage": "xyz"})

    assert r.status_code == 422


async def test_lead_tung_phien(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_phien(conn_ops, "s2", phone=A, bat_dau=luc(25))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="lead", lead_score=30, tao_luc=luc(20, 10))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="mql", lead_score=65, audience="broker", tao_luc=luc(20, 11))

    hang = await repo.liet_ke_phien(conn_ops, phone=A)

    theo = {r["session_id"]: (r["lead_stage"], r["lead_score"], r["audience"]) for r in hang}
    assert theo == {"s1": ("mql", 65, "broker"), "s2": (None, None, None)}


async def test_lead_phien_khong_nhan_ban_hang_theo_so_luot(conn_ops):
    """LATERAL + LEFT JOIN lượt: GROUP BY phải gồm cột lead, không được nhân số lượt."""
    from .conftest import them_luot

    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_luot(conn_ops, "s1", 1)
    await them_luot(conn_ops, "s1", 2)
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql")

    (r,) = await repo.liet_ke_phien(conn_ops, phone=A)

    assert (r["so_luot"], r["lead_stage"]) == (2, "sql")


async def test_doc_phien_co_lead(conn_ops):
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="hen_gap", lead_score=90, audience="end_user")

    r = await repo.doc_phien(conn_ops, "s1")

    assert (r["lead_stage"], r["lead_score"], r["audience"]) == ("hen_gap", 90, "end_user")


async def test_api_phien_tra_lead_camelcase(client_ops, pool):
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s1", phone=A, bat_dau=luc(20))
        await them_ca(conn, "s1", phone=A, lead_stage="sql", lead_score=70)

    ds = (await client_ops.get(f"/api/v1/convos/khach/{A}/phien")).json()
    ct = (await client_ops.get("/api/v1/convos/phien/s1")).json()

    assert (ds[0]["leadStage"], ds[0]["leadScore"], ds[0]["audience"]) == ("sql", 70, None)
    assert ct["phien"]["leadStage"] == "sql"


async def test_nhom_chua_co_so_khong_co_lead_cap_khach(conn_ops):
    """«Chưa có số» là NHIỀU người ẩn danh (header trang chi tiết ghi «KHÔNG phải một
    người») — một «lead mới nhất» cho cả nhóm là nói sai, và lọc `sql` sẽ bày nó ra như
    một khách nóng không có số để gọi. Lead TỪNG PHIÊN của nhóm vẫn giữ (Task 2)."""
    await them_phien(conn_ops, "an1", phone=None, bat_dau=luc(20))
    await them_ca(conn_ops, "an1", phone=None, lead_stage="sql", lead_score=85)

    r = await _mot(conn_ops, "")
    hang_sql = await repo.liet_ke_khach(conn_ops, tu_ngay="all", lead_stage="sql")

    assert r["lead_stage"] is None
    assert [h["phone"] for h in hang_sql] == []
    assert await repo.dem_tong(conn_ops, tu_ngay="all", lead_stage="sql") == (0, 0)
