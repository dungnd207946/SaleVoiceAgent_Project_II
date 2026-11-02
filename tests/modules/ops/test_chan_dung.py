"""Chân dung khách — `GET /convos/khach/{phone}/chan-dung`.

Nguồn là thứ AGENT ghi: `tenant_data.contacts` (profile jsonb + snapshot, một hàng mỗi
số) và `escalations.lead_signals` của ĐÚNG hàng lead mà ô «Lead hiện tại» đang hiện.
"""

import json

import pytest

from portal.modules.ops import repo

from .conftest import TENANT, TENANT_KHAC, luc, them_ca, them_phien

pytestmark = pytest.mark.asyncio

A = "0911000001"
HO_SO = {"name": "Hải", "budget": "3 tỷ", "bedroom_count": "2PN", "is_buyer": True}


async def them_lien_he(conn, phone, *, tenant=TENANT, profile=None, snapshot=""):
    await conn.execute(
        """
        INSERT INTO tenant_data.contacts (tenant_id, phone, snapshot, profile, updated_at)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        """,
        tenant,
        phone,
        snapshot,
        json.dumps(profile or {}),
        luc(28),
    )


def _json(v):
    return json.loads(v) if isinstance(v, str) else v


async def test_doc_ho_so_ghi_nho_va_tin_hieu(conn_ops):
    await them_lien_he(conn_ops, A, profile=HO_SO, snapshot="Chị quan tâm căn 2PN.")
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_ca(conn_ops, "s1", phone=A, lead_stage="mql", lead_signals=["co_ngan_sach", "co_phong"])

    r = await repo.doc_chan_dung(conn_ops, phone=A)

    assert _json(r["profile"]) == HO_SO
    assert r["snapshot"] == "Chị quan tâm căn 2PN."
    assert r["updated_at"] == luc(28)
    assert _json(r["lead_signals"]) == ["co_ngan_sach", "co_phong"]


async def test_tin_hieu_la_cua_cung_hang_lead_hien_tai(conn_ops):
    """Phiên mới nhất CÓ lead thắng — cùng luật `_LEAD_KHACH`, không phải hàng ca mới nhất."""
    await them_phien(conn_ops, "s1", phone=A, bat_dau=luc(20))
    await them_phien(conn_ops, "s2", phone=A, bat_dau=luc(25))
    await them_ca(conn_ops, "s2", phone=A, lead_stage="lead", lead_signals=["co_du_an"], tao_luc=luc(25))
    # Hàng ca tạo SAU nhưng thuộc phiên CŨ hơn — không được thắng.
    await them_ca(conn_ops, "s1", phone=A, lead_stage="sql", lead_signals=["hoi_tien"], tao_luc=luc(26))

    r = await repo.doc_chan_dung(conn_ops, phone=A)

    assert _json(r["lead_signals"]) == ["co_du_an"]


async def test_chua_co_lien_he_van_tra_mot_hang_rong(conn_ops):
    r = await repo.doc_chan_dung(conn_ops, phone=A)

    assert (r["profile"], r["snapshot"], r["updated_at"], r["lead_signals"]) == (None, None, None, None)


async def test_lien_he_tenant_khac_khong_lot_sang(conn_ops):
    await them_lien_he(conn_ops, A, tenant=TENANT_KHAC, profile=HO_SO, snapshot="bí mật")

    r = await repo.doc_chan_dung(conn_ops, phone=A)

    assert r["profile"] is None and r["snapshot"] is None


async def test_api_tra_camelcase(client_ops, pool):
    # Seed bằng `pool` + COMMIT — request chạy trên kết nối khác (khuôn `test_lead.py`).
    async with pool.acquire() as conn, conn.transaction():
        await them_lien_he(conn, A, profile=HO_SO, snapshot="Chị quan tâm căn 2PN.")
        await them_phien(conn, "s1", phone=A, bat_dau=luc(20))
        await them_ca(conn, "s1", phone=A, lead_stage="mql", lead_signals=["co_ngan_sach"])

    r = await client_ops.get(f"/api/v1/convos/khach/{A}/chan-dung")

    assert r.status_code == 200
    j = r.json()
    assert j["hoSo"] == HO_SO
    assert j["ghiNho"] == "Chị quan tâm căn 2PN."
    assert j["tinHieu"] == ["co_ngan_sach"]
    assert j["capNhatLuc"].startswith("2026-07-28")


async def test_api_khach_chua_co_gi_tra_rong_khong_404(client_ops):
    r = await client_ops.get(f"/api/v1/convos/khach/{A}/chan-dung")

    assert r.status_code == 200
    assert r.json() == {"hoSo": {}, "ghiNho": None, "tinHieu": [], "capNhatLuc": None}


async def test_api_snapshot_rong_la_null(client_ops, pool):
    async with pool.acquire() as conn, conn.transaction():
        await them_lien_he(conn, A, profile=HO_SO, snapshot="")

    r = await client_ops.get(f"/api/v1/convos/khach/{A}/chan-dung")

    assert r.json()["ghiNho"] is None


async def test_api_nhom_chua_co_so_tra_rong(client_ops):
    """«Chưa có số» là nhiều người ẩn danh — không có một chân dung nào cho cả nhóm."""
    r = await client_ops.get("/api/v1/convos/khach/_/chan-dung")

    assert r.status_code == 200
    assert r.json() == {"hoSo": {}, "ghiNho": None, "tinHieu": [], "capNhatLuc": None}
