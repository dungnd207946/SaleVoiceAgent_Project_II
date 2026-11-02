"""Usage của dữ liệu ngoài (purpose `kb_web`) trên các màn billing/usage.

Tiền tính bằng bảng giá mặc định thật (`vendor-vnd-2026-10`: dòng `kb_web` của 0973, tra Google 364 đ/lượt từ 0975).
"""

from decimal import Decimal

import asyncpg
import pytest

from tests.modules.billing.conftest import MAT_KHAU, MOC, SESSION, TENANT

pytestmark = pytest.mark.integration

BASE = "/api/v1/billing"
KY = {"from": "2026-08-01", "to": "2026-09-01"}
JOB = "kbweb:901"
SO_LUOT_TRA = 10
TIEN_TRA = Decimal(364 * SO_LUOT_TRA)
TIEN_QWEN = Decimal(780)  # 1M token vào ở bậc ≤32K


async def _dang_nhap(client) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": "bil@noblex.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r2 = await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT})
    assert r2.status_code == 200, r2.text


@pytest.fixture
async def co_du_lieu_ngoai(pool: asyncpg.Pool, workspace_billing):
    async with pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO billing.usage_events
                   (tenant_id, session_id, channel, seq, component, purpose, provider, model,
                    input_tokens, units, text_units, occurred_at)
               VALUES ($1, $2, 'kb_web', 0, $3, 'kb_web', $4, $5, $6, $7, $8, $9)""",
            [
                (TENANT, JOB, "search", "google", "gemini-2.5-flash", 0, SO_LUOT_TRA, 0, MOC),
                (TENANT, JOB, "llm", "dashscope", "qwen3.7-flash", 1_000_000, 0, 0, MOC),
                (TENANT, JOB, "embed", "santa-models", "multilingual-e5-large", 0, 0, 2_000, MOC),
            ],
        )
    return workspace_billing


async def test_summary_khong_dem_job_la_phien_va_tach_tien(app_client, co_du_lieu_ngoai) -> None:
    await _dang_nhap(app_client)
    d = (await app_client.get(f"{BASE}/summary", params=KY)).json()
    assert d["so_phien"] == 1
    tien = Decimal(d["chi_phi_du_lieu_ngoai"])
    assert tien >= TIEN_TRA + TIEN_QWEN
    assert Decimal(d["chi_phi"]) > tien


async def test_by_key_co_hang_du_lieu_ngoai_rieng(app_client, co_du_lieu_ngoai) -> None:
    await _dang_nhap(app_client)
    d = (await app_client.get(f"{BASE}/by-key", params=KY)).json()
    hang = [x for x in d["items"] if x["du_lieu_ngoai"]]
    assert len(hang) == 1
    dln = hang[0]
    assert dln["agent_key_id"] is None and dln["so_phien"] == 0
    assert Decimal(dln["chi_phi_search"]) == TIEN_TRA
    assert Decimal(dln["chi_phi_llm"]) == TIEN_QWEN
    assert all(Decimal(x["chi_phi_search"]) == 0 for x in d["items"] if not x["du_lieu_ngoai"])
    assert sum(Decimal(x["chi_phi"]) for x in d["items"]) == Decimal(d["chi_phi_tong"])


async def test_by_owner_co_hang_du_lieu_ngoai_rieng(app_client, co_du_lieu_ngoai) -> None:
    await _dang_nhap(app_client)
    d = (await app_client.get(f"{BASE}/by-owner", params=KY)).json()
    hang = [x for x in d if x["du_lieu_ngoai"]]
    assert len(hang) == 1
    assert hang[0]["user_id"] is None and hang[0]["so_key"] == 0 and hang[0]["so_phien"] == 0
    assert Decimal(hang[0]["chi_phi_search"]) == TIEN_TRA


async def test_sessions_khong_liet_ke_job(app_client, co_du_lieu_ngoai) -> None:
    await _dang_nhap(app_client)
    d = (await app_client.get(f"{BASE}/sessions", params=KY)).json()
    assert [x["session_id"] for x in d["items"]] == [SESSION]


async def test_breakdown_tach_phan_du_lieu_ngoai_theo_dich_vu(app_client, co_du_lieu_ngoai) -> None:
    await _dang_nhap(app_client)
    d = (await app_client.get(f"{BASE}/breakdown", params=KY)).json()
    comp = {x["component"]: x for x in d["theo_component"]}
    assert Decimal(comp["search"]["chi_phi"]) == TIEN_TRA
    assert Decimal(comp["search"]["chi_phi_du_lieu_ngoai"]) == TIEN_TRA
    assert Decimal(comp["llm"]["chi_phi_du_lieu_ngoai"]) == TIEN_QWEN
    assert Decimal(comp["llm"]["chi_phi"]) > TIEN_QWEN
    assert Decimal(comp["tts"]["chi_phi_du_lieu_ngoai"]) == 0


async def test_usage_by_day_co_so_do_du_lieu_ngoai(app_client, co_du_lieu_ngoai) -> None:
    await _dang_nhap(app_client)
    d = (await app_client.get(f"{BASE}/usage-by-day", params=KY)).json()
    ngay = next(x for x in d["theo_ngay"] if x["ngay"] == MOC.date().isoformat())
    assert ngay["so_phien"] == 1
    phan = {x["component"]: x for x in ngay["phan"]}
    assert phan["llm"]["token_du_lieu_ngoai"] == 1_000_000
    assert phan["llm"]["input_tokens"] > 1_000_000
    assert phan["embed"]["text_units_du_lieu_ngoai"] == 2_000
    assert phan["search"]["units"] == SO_LUOT_TRA
