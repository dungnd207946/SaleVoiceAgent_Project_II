"""`/config/roles` — thêm · đổi tên · xoá role người dùng agent (`0967`).

Canh:
  1. `customer` KHÔNG XOÁ ĐƯỢC — cả qua API (409) lẫn thẳng ở DB (trigger).
  2. Thêm role: `key` sinh từ tên, bất biến; chép cấu hình từ role nguồn nếu xin; tên trùng
     (không phân biệt hoa/thường) ⇒ 409; quá trần ⇒ 409.
  3. Xoá role ⇒ hàng cấu hình của nó đi theo, và `version` các hàng còn lại TĂNG (agent
     phải biết danh sách role đã đổi).
  4. Đổi tên không chạm hàng cấu hình, `key` giữ nguyên.
  5. Mỗi thao tác ghi một dòng nhật ký.
"""

import copy
import json

import asyncpg
import httpx
import pytest

from tests.modules.config.conftest import PAYLOAD_HOP_LE

pytestmark = pytest.mark.integration

URL = "/api/v1/config"


async def _vai_tro(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()["vaiTro"]


async def _tao(client: httpx.AsyncClient, ten: str, **them) -> httpx.Response:
    return await client.post(f"{URL}/roles", json={"ten": ten, **them})


async def _nhat_ky(pool: asyncpg.Pool, tenant_id: str, ma: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT chi_tiet FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = $2 ORDER BY id",
            tenant_id,
            ma,
        )
    return [json.loads(r["chi_tiet"]) for r in rows]


# ─── Tạo ─────────────────────────────────────────────────────────────────────


async def test_tao_role_sinh_key_tu_ten_va_noi_cuoi(client_cfg, pool, workspace_cfg):
    r = await _tao(client_cfg, "  Đối tác môi giới  ")
    assert r.status_code == 201, r.text
    assert r.json() == {"key": "doi_tac_moi_gioi", "ten": "Đối tác môi giới", "icon": None, "macDinh": False}

    ds = await _vai_tro(client_cfg)
    assert [v["key"] for v in ds] == ["customer", "doi_tac_moi_gioi"]
    assert ds[1]["laMacDinh"] is True, "không chép từ đâu ⇒ role mới dùng bộ mặc định"

    assert await _nhat_ky(pool, workspace_cfg, "role_config.tao") == [
        {"key": "doi_tac_moi_gioi", "ten": "Đối tác môi giới", "icon": None, "sao_chep_tu": None, "version": None}
    ]


async def test_tao_role_chep_cau_hinh_tu_role_nguon(client_cfg, pool, workspace_cfg):
    nguon = copy.deepcopy(PAYLOAD_HOP_LE)
    nguon["danh_tinh"]["ten_agent"] = "Mai"
    assert (await client_cfg.put(URL, json={"cauHinh": {"customer": nguon}})).status_code == 200

    r = await _tao(client_cfg, "Sale", saoChepTu="customer")
    assert r.status_code == 201, r.text

    ds = {v["key"]: v for v in await _vai_tro(client_cfg)}
    assert ds["sale"]["laMacDinh"] is False
    assert ds["sale"]["cauHinh"] == ds["customer"]["cauHinh"]

    async with pool.acquire() as conn:
        so = await conn.fetch(
            "SELECT role, version FROM tenant_data.agent_config WHERE tenant_id = $1 ORDER BY role", workspace_cfg
        )
    assert [(r["role"], r["version"]) for r in so] == [("customer", 2), ("sale", 2)], (
        "thêm role phải tăng version MỌI hàng — agent cache theo (tenant, version)"
    )


async def test_trung_key_thi_them_hau_to(client_cfg):
    assert (await _tao(client_cfg, "Sale")).json()["key"] == "sale"
    assert (await _tao(client_cfg, "Sale!")).json()["key"] == "sale_2"


async def test_ten_trung_khong_phan_biet_hoa_thuong_thi_409(client_cfg):
    assert (await _tao(client_cfg, "Sale")).status_code == 201
    r = await _tao(client_cfg, "  sALE ")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_TEN_DA_DUNG"
    assert (await _tao(client_cfg, "khách HÀNG")).status_code == 409


async def test_ten_rong_hoac_qua_dai_thi_422(client_cfg):
    assert (await _tao(client_cfg, "   ")).status_code == 422
    assert (await _tao(client_cfg, "x" * 41)).status_code == 422


async def test_chep_tu_role_khong_co_thi_404(client_cfg):
    r = await _tao(client_cfg, "Sale", saoChepTu="khong_co")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ROLE_KHONG_TON_TAI"
    assert [v["key"] for v in await _vai_tro(client_cfg)] == ["customer"]


async def test_qua_tran_thi_409(client_cfg):
    for i in range(9):
        assert (await _tao(client_cfg, f"Role {i}")).status_code == 201
    r = await _tao(client_cfg, "Thứ mười một")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_QUA_GIOI_HAN"
    assert len(await _vai_tro(client_cfg)) == 10


# ─── Đổi tên ─────────────────────────────────────────────────────────────────


async def test_doi_ten_giu_key_va_cau_hinh(client_cfg, pool, workspace_cfg):
    await _tao(client_cfg, "Sale")
    await client_cfg.put(URL, json={"cauHinh": {"customer": PAYLOAD_HOP_LE, "sale": PAYLOAD_HOP_LE}})

    r = await client_cfg.patch(f"{URL}/roles/sale", json={"ten": "Nhân viên kinh doanh"})
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "sale", "ten": "Nhân viên kinh doanh", "icon": None, "macDinh": False}

    ds = {v["key"]: v for v in await _vai_tro(client_cfg)}
    assert ds["sale"]["ten"] == "Nhân viên kinh doanh"
    assert ds["sale"]["laMacDinh"] is False
    nk = await _nhat_ky(pool, workspace_cfg, "role_config.sua")
    assert nk == [{"key": "sale", "ten": ["Sale", "Nhân viên kinh doanh"], "icon": [None, None], "version": 2}]


async def test_doi_ten_role_mac_dinh_duoc(client_cfg):
    r = await client_cfg.patch(f"{URL}/roles/customer", json={"ten": "Khách mua"})
    assert r.status_code == 200
    assert r.json()["macDinh"] is True


async def test_doi_ten_trung_hoac_khong_co(client_cfg):
    await _tao(client_cfg, "Sale")
    r = await client_cfg.patch(f"{URL}/roles/sale", json={"ten": "Khách hàng"})
    assert r.status_code == 409
    assert (await client_cfg.patch(f"{URL}/roles/khong_co", json={"ten": "X"})).status_code == 404


# ─── Xoá ─────────────────────────────────────────────────────────────────────


async def test_xoa_role_mang_theo_hang_cau_hinh(client_cfg, pool, workspace_cfg):
    await _tao(client_cfg, "Sale")
    await client_cfg.put(URL, json={"cauHinh": {"customer": PAYLOAD_HOP_LE, "sale": PAYLOAD_HOP_LE}})

    r = await client_cfg.delete(f"{URL}/roles/sale")
    assert r.status_code == 204

    assert [v["key"] for v in await _vai_tro(client_cfg)] == ["customer"]
    async with pool.acquire() as conn:
        so = await conn.fetch("SELECT role, version FROM tenant_data.agent_config WHERE tenant_id = $1", workspace_cfg)
    assert [(r["role"], r["version"]) for r in so] == [("customer", 2)]
    assert await _nhat_ky(pool, workspace_cfg, "role_config.xoa") == [{"key": "sale", "ten": "Sale", "version": 2}]


async def test_khong_xoa_duoc_role_mac_dinh(client_cfg):
    r = await client_cfg.delete(f"{URL}/roles/customer")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_MAC_DINH"
    assert [v["key"] for v in await _vai_tro(client_cfg)] == ["customer"]


async def test_xoa_role_khong_co_thi_404(client_cfg):
    assert (await client_cfg.delete(f"{URL}/roles/khong_co")).status_code == 404


# ─── Cách ly ─────────────────────────────────────────────────────────────────


async def test_khong_dong_duoc_role_cua_tenant_khac(client_cfg, pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cf_khac', 'Khác', 'u_seed_test')"
        )
        await conn.execute("INSERT INTO tenant_data.role_config (tenant_id, key, ten) VALUES ('cf_khac', 'vip', 'VIP')")

    assert (await client_cfg.patch(f"{URL}/roles/vip", json={"ten": "Đổi"})).status_code == 404
    assert (await client_cfg.delete(f"{URL}/roles/vip")).status_code == 404
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT ten FROM tenant_data.role_config WHERE tenant_id = 'cf_khac' AND key = 'vip'")
            == "VIP"
        )


# ─── Icon ────────────────────────────────────────────────────────────────────


async def test_role_mac_dinh_co_icon_san(client_cfg):
    ds = await _vai_tro(client_cfg)
    assert ds[0]["icon"] == "khach"


async def test_tao_va_doi_icon(client_cfg, pool, workspace_cfg):
    r = await _tao(client_cfg, "VIP", icon="vuong_mien")
    assert r.status_code == 201, r.text
    assert r.json()["icon"] == "vuong_mien"

    # Chỉ đổi icon: tên giữ nguyên, KHÔNG tăng version (icon không phải thứ agent đọc).
    r = await client_cfg.patch(f"{URL}/roles/vip", json={"icon": "kim_cuong"})
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "vip", "ten": "VIP", "icon": "kim_cuong", "macDinh": False}
    assert {v["key"]: v["icon"] for v in await _vai_tro(client_cfg)}["vip"] == "kim_cuong"
    nk = await _nhat_ky(pool, workspace_cfg, "role_config.sua")
    assert nk == [{"key": "vip", "ten": ["VIP", "VIP"], "icon": ["vuong_mien", "kim_cuong"], "version": None}]


async def test_icon_sai_hinh_dang_hoac_patch_rong_thi_422(client_cfg):
    assert (await _tao(client_cfg, "VIP", icon="Vương Miện")).status_code == 422
    await _tao(client_cfg, "VIP")
    assert (await client_cfg.patch(f"{URL}/roles/vip", json={})).status_code == 422
