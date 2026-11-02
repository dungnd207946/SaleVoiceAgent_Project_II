"""Sáu endpoint qua app THẬT. Điều test này bảo vệ: HAI cổng xác thực tách hẳn.

Trộn chúng là mở một đường lấy credential hạ tầng bằng phiên của một người dùng
workspace bình thường.
"""

import pytest

from tests.modules.enrollment.conftest import ADMIN_TOKEN, MASTER_KEY, TENANT_A

HEADER_ADMIN = {"X-Platform-Admin-Token": ADMIN_TOKEN}
GOC = "/api/v1/agent"


@pytest.fixture
async def client(app_client, monkeypatch, hai_tenant):
    """`app_client` của conftest gốc + hai biến của M10.

    Nhận `hai_tenant` để tenant tồn tại trước khi cấp phát — `dat_mat_khau_agent()`
    ném nếu tenant chưa có, và đó là hành vi đúng (fail-closed).
    """
    monkeypatch.setenv("AGENT_MASTER_KEY", MASTER_KEY)
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", ADMIN_TOKEN)
    return app_client


async def _tao(client) -> dict:
    r = await client.post(f"{GOC}/admin/tenants/{TENANT_A}/provision", headers=HEADER_ADMIN)
    assert r.status_code == 201, r.text
    return r.json()


# ─── Cổng xác thực quản trị ────────────────────────────────────────────────


async def test_admin_thieu_token_thi_401(client):
    r = await client.post(f"{GOC}/admin/tenants/{TENANT_A}/provision")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_ADMIN_TOKEN"


async def test_admin_sai_token_va_thieu_token_cung_cau_chu(client):
    """Khác `message` là máy dò biết "đã cấu hình token" khác "token sai"."""
    thieu = (await client.get(f"{GOC}/admin/tenants")).json()["error"]
    sai = (await client.get(f"{GOC}/admin/tenants", headers={"X-Platform-Admin-Token": "sai"})).json()["error"]
    assert thieu == sai


async def test_admin_khong_dung_15_action_cua_pq01(client):
    """M10 KHÔNG được chạm danh mục action của PQ_01/M2a — M2a phát cả danh mục
    đó cho MỌI user, nên thêm một action quản trị vào đó là phát quyền nền tảng
    cho mọi người dùng.

    15 = 13 nhóm gốc PQ_01 §3.1 + billing.read (0945) + audit.read
    (0956_audit_action, 2026-08-25 — module audit, KHÔNG M10; nếu M10 từng chạm
    vào đây con số sẽ lệch khỏi 15)."""
    from portal.core.auth.actions import ALL_ACTIONS

    assert len(ALL_ACTIONS) == 17
    assert not any("platform" in a for a in ALL_ACTIONS)


# ─── Cổng xác thực agent ───────────────────────────────────────────────────


async def test_runtime_credentials_thieu_bearer_thi_401(client):
    r = await client.post(f"{GOC}/runtime-credentials")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_AGENT_KEY"


async def test_runtime_credentials_khong_nhan_token_quan_tri(client):
    """Token quản trị KHÔNG mở được đường lấy credential — hai cổng tách hẳn."""
    r = await client.post(f"{GOC}/runtime-credentials", headers=HEADER_ADMIN)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_AGENT_KEY"


async def test_runtime_credentials_bang_bearer_thi_qua(client):
    key = (await _tao(client))["api_key"]
    r = await client.post(f"{GOC}/runtime-credentials", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["tenant_id"] == TENANT_A
    assert d["kb"]["collection"] == f"kb_{TENANT_A}"
    assert d["storage"]["prefix"] == f"tenants/{TENANT_A}/"
    # Mặt còn lại của SecretStr: response PHẢI có giá trị thật, không phải '****'.
    assert d["postgres_role"] == f"agent_{TENANT_A}"
    assert d["postgres_password"] and "*" not in d["postgres_password"]
    assert "*" not in d["storage"]["secret_key"]


# ─── Khoá thô xuất hiện đúng một lần ───────────────────────────────────────


async def test_khoa_tho_khong_doc_lai_duoc(client):
    key = (await _tao(client))["api_key"]
    ds = await client.get(f"{GOC}/admin/tenants", headers=HEADER_ADMIN)
    assert ds.status_code == 200
    assert key not in ds.text, "khoá thô không được xuất hiện lần thứ hai"


async def test_liet_ke_co_khoi_chan_doan(client):
    await _tao(client)
    r = await client.get(f"{GOC}/admin/tenants", headers=HEADER_ADMIN)
    hang = next(d for d in r.json() if d["tenant_id"] == TENANT_A)
    assert set(hang["san_sang_du_lieu"]) == {"projects_published", "kb_chunks"}
    assert hang["so_khoa_con_song"] == 1
    # `0941`: ba trường của hàng deployment đi cùng bảng, khối chẩn đoán ở lại.
    assert {"id", "endpoint", "provisioned_at", "deployment_id"}.isdisjoint(hang)


# ─── Thu hồi và xoay khoá qua HTTP ─────────────────────────────────────────


async def test_thu_hoi_thi_runtime_credentials_401(client):
    tao = await _tao(client)
    r = await client.delete(f"{GOC}/admin/keys/{tao['id']}", headers=HEADER_ADMIN)
    assert r.status_code == 204

    r = await client.post(f"{GOC}/runtime-credentials", headers={"Authorization": f"Bearer {tao['api_key']}"})
    assert r.status_code == 401


async def test_phat_khoa_them_cho_cung_tenant(client):
    """Đường xoay khoá không gián đoạn: phát mới → nạp vào pod → thu hồi cũ.

    URL đổi ở `0940` (`/admin/deployments/{id}/keys` → `/admin/tenants/{id}/keys`):
    khoá treo thẳng vào tenant nên `deployment_id` không định danh được gì nữa.
    """
    tao = await _tao(client)
    r = await client.post(f"{GOC}/admin/tenants/{TENANT_A}/keys", headers=HEADER_ADMIN)
    assert r.status_code == 201
    moi = r.json()
    assert "deployment_id" not in moi
    assert moi["id"] != tao["id"]
    assert moi["api_key"] != tao["api_key"]

    # Cả hai khoá đều dùng được — đó là điều làm việc xoay không có khoảng chết.
    for k in (tao["api_key"], moi["api_key"]):
        r = await client.post(f"{GOC}/runtime-credentials", headers={"Authorization": f"Bearer {k}"})
        assert r.status_code == 200


async def test_phat_khoa_cho_workspace_khong_ton_tai_thi_404(client):
    """`khong_co_tenant` (đổi từ `khong_co_deployment` ở `0940`). Tên phải khớp
    `TENANT_ID_PATTERN`, nếu không nó dừng ở 422 của path param và bài này xanh
    vì một lý do sai."""
    r = await client.post(f"{GOC}/admin/tenants/khongcothat/keys", headers=HEADER_ADMIN)
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "NOT_FOUND"


async def test_phat_khoa_cho_tenant_id_sai_dinh_dang_thi_422(client):
    r = await client.post(f"{GOC}/admin/tenants/KHONG_HOP_LE/keys", headers=HEADER_ADMIN)
    assert r.status_code == 422


async def test_xoay_bi_mat_tang_version(client):
    await _tao(client)
    r = await client.post(f"{GOC}/admin/tenants/{TENANT_A}/rotate-secrets", headers=HEADER_ADMIN)
    assert r.status_code == 200
    assert r.json()["secret_version"] == 2
