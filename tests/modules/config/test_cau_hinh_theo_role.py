"""`GET`/`PUT /config` — cấu hình agent theo ROLE, không bản nháp (`0966`), role là dữ liệu (`0967`).

Canh, theo thứ tự "hỏng thì đau tới đâu":

  1. MỖI ROLE MỘT HÀNG RIÊNG. Lưu giá trị khác nhau cho các role thì đọc lại đúng từng
     role — không role nào đè role kia.
  2. VERSION TĂNG MỖI LẦN LƯU, mọi hàng cùng số. Không tăng ⇒ agent không dựng lại runner.
  3. LƯU NGUYÊN TỬ. Một role sai ⇒ không role nào được ghi. Tập role trong body phải trùng
     đúng tập role đang có — lệch là màn đã cũ ⇒ 409, không ghi gì.
  4. HÀNG CŨ HỎNG ⇒ 409 khi đọc, KHÔNG trả mặc định (mời ghi đè dữ liệu thật) — nhưng Lưu
     vẫn được, vì Lưu chính là cách sửa nó.
  5. Nhật ký ghi trường đã đổi THEO ROLE.
"""

import copy
import json

import asyncpg
import httpx
import pytest

from tests.modules.config.conftest import PAYLOAD_HOP_LE

pytestmark = pytest.mark.integration

URL = "/api/v1/config"


async def _them_sale(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{URL}/roles", json={"ten": "Sale"})
    assert r.status_code == 201, r.text
    assert r.json()["key"] == "sale"


def _body(**theo_role: dict) -> dict:
    return {"cauHinh": {k: v or copy.deepcopy(PAYLOAD_HOP_LE) for k, v in theo_role.items()}}


def _hai_role(sale: dict | None = None, customer: dict | None = None) -> dict:
    return _body(sale=sale, customer=customer)


def _ten(payload: dict, ten: str) -> dict:
    p = copy.deepcopy(payload)
    p["danh_tinh"]["ten_agent"] = ten
    return p


def _theo_key(d: dict) -> dict[str, dict]:
    return {r["key"]: r for r in d["vaiTro"]}


async def _hang(pool: asyncpg.Pool, tenant_id: str) -> dict[str, asyncpg.Record]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM tenant_data.agent_config WHERE tenant_id = $1", tenant_id)
    return {r["role"]: r for r in rows}


# ─── Đọc khi chưa cấu hình ───────────────────────────────────────────────────


async def test_tenant_moi_chi_co_role_mac_dinh_va_bo_mac_dinh(client_cfg: httpx.AsyncClient):
    r = await client_cfg.get(URL)
    assert r.status_code == 200, r.text
    d = r.json()

    assert [(v["key"], v["ten"], v["icon"], v["macDinh"], v["laMacDinh"]) for v in d["vaiTro"]] == [
        ("customer", "Khách hàng", "khach", True, True)
    ]
    assert d["version"] is None
    assert d["soRoleToiDa"] == 10
    cfg = d["vaiTro"][0]["cauHinh"]
    # Mặc định sinh từ tên workspace (`payload_mac_dinh`), dùng được ngay.
    assert cfg["danh_tinh"]["ten_thuong_hieu"] == "An Phú Land"
    assert cfg["tools"]["enabled"]


# ─── Lưu rồi đọc lại ─────────────────────────────────────────────────────────


async def test_luu_hai_role_khac_nhau_doc_lai_dung_tung_role(client_cfg, pool, workspace_cfg):
    await _them_sale(client_cfg)
    body = _hai_role(sale=_ten(PAYLOAD_HOP_LE, "Sale Bot"), customer=_ten(PAYLOAD_HOP_LE, "CSKH Bot"))
    r = await client_cfg.put(URL, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1

    d = _theo_key((await client_cfg.get(URL)).json())
    assert d["sale"]["cauHinh"]["danh_tinh"]["ten_agent"] == "Sale Bot"
    assert d["customer"]["cauHinh"]["danh_tinh"]["ten_agent"] == "CSKH Bot"
    assert not d["sale"]["laMacDinh"] and not d["customer"]["laMacDinh"]

    hang = await _hang(pool, workspace_cfg)
    assert set(hang) == {"sale", "customer"}
    assert hang["sale"]["name"] == "Sale Bot"
    assert hang["customer"]["name"] == "CSKH Bot"


async def test_doc_lai_giu_du_moi_truong_cua_payload(client_cfg):
    """Không còn `config_drafts`: GET dựng payload NGƯỢC từ hàng phẳng. Trường nào ánh xạ
    ngược sai là form mở ra khác thứ người dùng vừa lưu."""
    day_du = {
        "schema_version": 3,
        "danh_tinh": {
            "ten_agent": "Mai",
            "ten_thuong_hieu": "An Phú Land",
            "tu_xung": "con",
            "goi_khach": "cô chú",
            "loi_chao": "Dạ con chào cô chú.",
        },
        "pham_vi": {
            "linh_vuc": "realestate",
            "lam_gi": "Tư vấn dự án.",
            "khong_lam_gi": "Hậu mãi.",
            "phong_ban": [{"ten": "CSKH", "khi_nao": "khách hỏi hợp đồng"}],
            "cau_tu_choi": "Phần này con xin chuyển phòng kinh doanh.",
        },
        "giong": {"giong_dieu": "lich_su", "do_dai": "chi_tiet"},
        "tools": {"enabled": ["kb_search", "find_project", "booking"]},
        "tts_normalization": [{"term": "NCLB", "read_as": "Noble Crystal Long Biên"}],
    }
    await client_cfg.put(URL, json=_body(customer=day_du))

    d = _theo_key((await client_cfg.get(URL)).json())
    assert d["customer"]["cauHinh"] == day_du


async def test_luu_lan_hai_tang_version_va_giu_id(client_cfg, pool, workspace_cfg):
    await _them_sale(client_cfg)
    await client_cfg.put(URL, json=_hai_role())
    truoc = await _hang(pool, workspace_cfg)

    r = await client_cfg.put(URL, json=_hai_role(sale=_ten(PAYLOAD_HOP_LE, "Lan")))
    assert r.json()["version"] == 2

    sau = await _hang(pool, workspace_cfg)
    assert len(sau) == 2, "UPSERT theo (tenant, role) — không append"
    for role in ("sale", "customer"):
        assert sau[role]["version"] == 2, "mọi role phải cùng số — agent so số này"
        assert sau[role]["id"] == truoc[role]["id"]
        assert sau[role]["created_at"] == truoc[role]["created_at"]


async def test_truong_da_doi_theo_role(client_cfg):
    await _them_sale(client_cfg)
    await client_cfg.put(URL, json=_hai_role())
    r = await client_cfg.put(URL, json=_hai_role(sale=_ten(PAYLOAD_HOP_LE, "Lan")))

    assert r.json()["truongDaDoi"] == {"sale": ["danh_tinh.ten_agent"], "customer": []}


# ─── Từ chối ─────────────────────────────────────────────────────────────────


async def test_thieu_mot_role_thi_409_va_khong_ghi(client_cfg, pool, workspace_cfg):
    await _them_sale(client_cfg)
    r = await client_cfg.put(URL, json=_body(customer=None))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFIG_ROLE_DA_DOI"
    assert await _hang(pool, workspace_cfg) == {}


async def test_role_khong_ton_tai_thi_409(client_cfg, pool, workspace_cfg):
    """Tab đã mở từ trước khi role bị xoá ở nơi khác — Lưu không được hồi sinh nó."""
    r = await client_cfg.put(URL, json=_body(customer=None, admin=None))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFIG_ROLE_DA_DOI"
    assert await _hang(pool, workspace_cfg) == {}


async def test_mot_role_sai_thi_khong_role_nao_duoc_ghi(client_cfg, pool, workspace_cfg):
    await _them_sale(client_cfg)
    xau = copy.deepcopy(PAYLOAD_HOP_LE)
    xau["tools"]["enabled"] = ["khong_ton_tai"]
    r = await client_cfg.put(URL, json=_hai_role(sale=xau))
    assert r.status_code == 422
    assert await _hang(pool, workspace_cfg) == {}


async def test_schema_version_cu_thi_409_va_khong_ghi(client_cfg, pool, workspace_cfg):
    cu = {**copy.deepcopy(PAYLOAD_HOP_LE), "schema_version": 2}
    r = await client_cfg.put(URL, json=_body(customer=cu))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFIG_SCHEMA_CU"
    assert await _hang(pool, workspace_cfg) == {}


# ─── Hàng đã lưu không còn hợp lệ ────────────────────────────────────────────


async def _lam_hong_skills(pool: asyncpg.Pool, tenant_id: str, role: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenant_data.agent_config SET skills = $3::jsonb WHERE tenant_id = $1 AND role = $2",
            tenant_id,
            role,
            json.dumps(["find_project", "get_project_overview"]),  # đã gỡ khỏi sổ 2026-09-09
        )


async def test_hang_da_luu_hong_thi_get_409_khong_tra_mac_dinh(client_cfg, pool, workspace_cfg):
    await client_cfg.put(URL, json=_body(customer=None))
    await _lam_hong_skills(pool, workspace_cfg, "customer")

    r = await client_cfg.get(URL)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFIG_DA_LUU_KHONG_HOP_LE"


async def test_hang_da_luu_hong_van_luu_de_sua_duoc(client_cfg, pool, workspace_cfg):
    await client_cfg.put(URL, json=_body(customer=None))
    await _lam_hong_skills(pool, workspace_cfg, "customer")

    r = await client_cfg.put(URL, json=_body(customer=None))
    assert r.status_code == 200, r.text
    assert (await client_cfg.get(URL)).status_code == 200


# ─── Nhật ký · trạng thái ────────────────────────────────────────────────────


async def test_luu_ghi_mot_hang_nhat_ky(client_cfg, pool, workspace_cfg):
    await _them_sale(client_cfg)
    await client_cfg.put(URL, json=_hai_role())
    await client_cfg.put(URL, json=_hai_role(customer=_ten(PAYLOAD_HOP_LE, "Lan")))

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT chi_tiet FROM control.audit_log"
            " WHERE tenant_id = $1 AND hanh_dong = 'agent_config.luu' ORDER BY id",
            workspace_cfg,
        )
    assert len(rows) == 2
    cuoi = json.loads(rows[-1]["chi_tiet"])
    assert cuoi == {"version": 2, "truong_da_doi": {"sale": [], "customer": ["danh_tinh.ten_agent"]}}


async def test_status_tra_version_hien_tai(client_cfg):
    assert (await client_cfg.get(f"{URL}/status")).json() == {"trangThaiAgent": "dang_cap", "version": None}

    await client_cfg.put(URL, json=_body(customer=None))
    d = (await client_cfg.get(f"{URL}/status")).json()
    assert d["version"] == 1


async def test_route_cu_khong_con(client_cfg):
    """Không còn bản nháp/xuất bản — một FE cũ gọi vào phải thấy 404/405, không phải một
    đường ghi bí mật vẫn sống."""
    assert (await client_cfg.get(f"{URL}/draft")).status_code == 404
    assert (await client_cfg.post(f"{URL}/publish", json={})).status_code == 404
    assert (await client_cfg.get(f"{URL}/versions")).status_code == 404


# ─── Cách ly tenant ──────────────────────────────────────────────────────────


async def test_khong_doc_hang_cua_tenant_khac(client_cfg, pool, workspace_cfg):
    """Hai tenant cùng có hàng: đọc/đếm version/liệt kê role không được lấn sang tenant kia."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('cf_khac', 'Khác', 'u_seed_test')"
        )
        await conn.execute(
            "INSERT INTO tenant_data.role_config (tenant_id, key, ten) VALUES ('cf_khac', 'sale', 'Sale')"
        )
        for role in ("sale", "customer"):
            await conn.execute(
                "INSERT INTO tenant_data.agent_config (tenant_id, role, name, brand_name, tone, reply_length, version)"
                " VALUES ('cf_khac', $1, 'Của tenant khác', 'Khác', 'lich_su', 'ngan', 7)",
                role,
            )

    d = (await client_cfg.get(URL)).json()
    assert d["version"] is None
    assert [v["key"] for v in d["vaiTro"]] == ["customer"]
    assert d["vaiTro"][0]["laMacDinh"] is True

    r = await client_cfg.put(URL, json=_body(customer=None))
    assert r.json()["version"] == 1, "version đếm theo tenant — không lấy MAX của tenant khác"
