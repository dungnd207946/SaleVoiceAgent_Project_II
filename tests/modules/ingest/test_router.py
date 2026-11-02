"""Đường HTTP của cổng nạp — thứ `test_nap.py` cố ý KHÔNG phủ.

Review MR !55 chỉ ra: docstring của `test_nap.py` viện dẫn file này để biện minh
cho việc gọi thẳng `service.*`, nhưng file này KHÔNG TỒN TẠI. Nghĩa là toàn bộ
tầng router chưa từng được canh — trong khi tài liệu khiến người đọc tưởng đã có.

Ở đây KHÔNG lặp lại nghiệp vụ (`test_nap.py` đã phủ). Chỉ canh đúng những thứ chỉ
tầng HTTP mới sai được, và tất cả đều là chế độ hỏng ÂM THẦM:

  · `ROUTER.include_router(ROUTER_TENANT)` — `api/app.py::ROUTERS` chỉ gắn biến
    `ROUTER` của `router.py`, nên bốn endpoint quản trị sống nhờ đúng một dòng đó.
    Xoá nó ⇒ 404, KHÔNG có lỗi nào lúc khởi động.
  · Mã lỗi xác thực — một `require(None, ly_do=…)` bị đổi làm lộ endpoint ghi vào
    `tenant_data` cho request không xác thực.
  · Parse query `dryRun` — sai kiểu ⇒ một lượt thử GHI THẬT vào dữ liệu khách.
  · `response_model` — trường bị rơi khỏi response thì FE trắng màn lúc chạy
    trong khi cả hai repo đều xanh.
"""

import pytest

from portal.modules.ingest import contracts, service

pytestmark = pytest.mark.integration

NEN = f"/api/v1/ingest/{contracts.LINH_VUC}/{contracts.PHIEN_BAN}"

LO_HOP_LE = {
    "records": [
        {
            "entity": "project",
            "externalId": "HTTP-P1",
            "op": "upsert",
            "occurredAt": "2026-08-15T09:00:00Z",
            "data": {"name": "Dự án qua HTTP"},
        }
    ]
}


@pytest.fixture
async def token(api_pool, hai_tenant):
    a, _ = hai_tenant
    moi = await service.tao_token(api_pool, a, "http-test", "u1")
    return a, moi.token


# ─── Xác thực: một mã cho mọi dạng sai ──────────────────────────────────────


@pytest.mark.parametrize(
    "header",
    [
        pytest.param({}, id="khong-co-header"),
        pytest.param({"Authorization": "Bearer sai-hoan-toan"}, id="token-bia"),
        pytest.param({"Authorization": "ody_in_khong_co_tien_to_Bearer"}, id="thieu-Bearer"),
        pytest.param({"Authorization": "Basic ody_in_gi_do"}, id="sai-scheme"),
    ],
)
async def test_events_tu_choi_moi_dang_xac_thuc_sai(app_client, hai_tenant, header):
    """CÙNG một mã cho cả bốn — phân biệt chúng là cho không một máy dò biết
    chuỗi nào tồn tại. Và phải là 401, không phải 422/500."""
    r = await app_client.post(f"{NEN}/events", json=LO_HOP_LE, headers=header)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "INVALID_INGEST_TOKEN"


def test_hai_endpoint_nap_khong_nhan_phien_nguoi_dung():
    """⚠️ Đường nạp KHÔNG được nhận phiên portal — kiểm ở CHỮ KÝ HÀM.

    Trộn hai đường xác thực là mở một lối GHI vào `tenant_data` bằng phiên của
    người đang mở portal ở tab khác — đúng lớp lỗi CSRF mà `SameSite` chỉ chặn
    được một phần.

    Kiểm bằng chữ ký chứ không bằng một request có cookie: một request không
    cookie trả 401 KHÔNG chứng minh được gì (nó 401 vì thiếu Bearer). Thứ phải
    canh là «không có đường phiên nào TỒN TẠI», và điều đó đọc được ở tham số:
    có `Principal` nghĩa là `require(action)` đang cấp tenant từ cookie.
    """
    import inspect

    from portal.core.auth.principal import Principal
    from portal.modules.ingest import router as r

    for ham in (r.nap, r.doi_soat):
        chu_thich = [p.annotation for p in inspect.signature(ham).parameters.values()]
        assert Principal not in chu_thich, (
            f"{ham.__name__} nhận Principal — nghĩa là nó xác thực được bằng cookie phiên. "
            "Xem docstring đầu `router.py`."
        )


# ─── Đường sống + hình dạng response ────────────────────────────────────────


async def test_events_token_hop_le_tra_ket_qua_tung_ban_ghi(app_client, token):
    _, tho = token
    r = await app_client.post(f"{NEN}/events", json=LO_HOP_LE, headers={"Authorization": f"Bearer {tho}"})
    assert r.status_code == 200, r.text
    than = r.json()
    assert than["accepted"] == 1 and than["rejected"] == 0
    assert than["results"][0]["externalId"] == "HTTP-P1"
    assert than["dryRun"] is False


async def test_ban_ghi_hong_van_tra_200_kem_results(app_client, token):
    """Mã HTTP nói về REQUEST; `results` nói về từng bản ghi.

    Trả `422` cho cả lô buộc bên khách phải đoán bản nào hỏng — §3.1.
    """
    _, tho = token
    lo = {
        "records": [
            LO_HOP_LE["records"][0],
            {
                "entity": "project",
                "externalId": "HTTP-HONG",
                "op": "upsert",
                "occurredAt": "2026-08-15T09:00:00Z",
                "data": {"name": "x", "salePhase": "gia_tri_bia"},
            },
        ]
    }
    r = await app_client.post(f"{NEN}/events", json=lo, headers={"Authorization": f"Bearer {tho}"})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1 and r.json()["rejected"] == 1


@pytest.mark.parametrize("gia_tri", ["true", "1"])
async def test_dryRun_tren_query_khong_ghi_gi(app_client, api_pool, token, gia_tri):
    """Parse sai query này = một lượt THỬ ghi thật vào dữ liệu khách."""
    from portal.core.db.session import tenant_conn

    a, tho = token
    r = await app_client.post(
        f"{NEN}/events?dryRun={gia_tri}", json=LO_HOP_LE, headers={"Authorization": f"Bearer {tho}"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["dryRun"] is True

    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_records WHERE tenant_id=$1", a) == 0


# ─── Bản kê đối soát ────────────────────────────────────────────────────────


async def test_manifest_ma_trung_tra_422_co_ma_loi_rieng(app_client, token):
    _, tho = token
    r = await app_client.post(
        f"{NEN}/manifest",
        json={"entity": "project", "records": [{"externalId": "A", "updatedAt": "2026-08-15T09:00:00Z"}] * 2},
        headers={"Authorization": f"Bearer {tho}"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "BAN_KE_KHONG_HOP_LE"


async def test_manifest_can_token_nhu_events(app_client, hai_tenant):
    r = await app_client.post(f"{NEN}/manifest", json={"entity": "project", "records": []})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_INGEST_TOKEN"


# ─── GET /whoami: token nói nó thuộc workspace nào ──────────────────────────


async def test_whoami_tra_dung_workspace_cua_tung_token(app_client, api_pool, hai_tenant):
    """Token ghim workspace đích lúc TẠO. whoami là cách duy nhất bên khách kiểm
    «token này đổ dữ liệu vào đâu» mà không phải đẩy thử một bản ghi.

    Ca thật 2026-08-18 (AINA): khách tạo workspace mới nhưng token trong adapter
    vẫn của workspace cũ — mọi lượt sync XANH với accepted=0/stale=100%, và không
    gì trong hệ nói cho họ biết dữ liệu đang đổ về đâu.
    """
    a, b = hai_tenant
    token_a = await service.tao_token(api_pool, a, "whoami-a", "u1")
    token_b = await service.tao_token(api_pool, b, "whoami-b", "u1")
    for tid, ten, tho in ((a, "Ingest A", token_a.token), (b, "Ingest B", token_b.token)):
        r = await app_client.get(f"{NEN}/whoami", headers={"Authorization": f"Bearer {tho}"})
        assert r.status_code == 200, r.text
        assert r.json() == {"workspaceId": tid, "workspaceName": ten}


async def test_whoami_tu_choi_token_sai_cung_ma_401(app_client, hai_tenant):
    """Cùng `INVALID_INGEST_TOKEN` như events/manifest — whoami không được thành
    máy dò token (401 phân biệt «thiếu» với «sai» là cho không một bit)."""
    r = await app_client.get(f"{NEN}/whoami", headers={"Authorization": "Bearer ody_in_khong_ton_tai"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_INGEST_TOKEN"


# ─── Bốn endpoint quản trị: sống nhờ ĐÚNG MỘT dòng include_router ───────────


@pytest.mark.parametrize(
    ("method", "duong_dan"),
    [
        ("GET", "/tong-quan"),
        ("POST", "/keys"),
        ("DELETE", "/keys/1"),
        ("GET", "/loi"),
    ],
)
async def test_bon_endpoint_quan_tri_co_len_va_doi_phien(app_client, method, duong_dan):
    """⚠️ Bài canh chính là phân biệt **401 với 404**.

    `router_tenant.py` tự nó VÔ HÌNH với `api/app.py::ROUTERS`. Xoá dòng
    `ROUTER.include_router(ROUTER_TENANT)` thì bốn endpoint này biến mất và
    KHÔNG có lỗi nào nổ — chỉ là 404 ở chỗ không ai ngờ. Nên `!= 404` mới là
    thứ bài này đo; `== 401` chỉ là hệ quả của việc không gửi phiên.
    """
    r = await app_client.request(method, f"{NEN}{duong_dan}")
    assert r.status_code != 404, f"{method} {duong_dan} không lên — mất include_router?"
    assert r.status_code == 401, r.text


async def test_token_nap_KHONG_mo_duoc_endpoint_quan_tri(app_client, token):
    """Token nạp là quyền GHI DỮ LIỆU, không phải quyền quản trị workspace.

    Nó nằm trong hệ thống bên thứ ba; nếu nó đọc được `/tong-quan` thì nó đọc
    được chuỗi thô của MỌI token còn lại của workspace đó.
    """
    _, tho = token
    r = await app_client.get(f"{NEN}/tong-quan", headers={"Authorization": f"Bearer {tho}"})
    assert r.status_code == 401, r.text


# ─── Giới hạn nhịp nổi lên đúng ở tầng HTTP ───────────────────────────────────────────────


async def test_vuot_nhip_tra_429_khong_phai_401(app_client, token, monkeypatch):
    """⚠️ Mã HTTP là thứ adapter bên khách RẼ NHÁNH theo, nên nó phải nói đúng
    việc: `401` ⇒ đổi token, `429` ⇒ giữ token, chậm lại rồi thử lại.

    `app_client` phụ thuộc `redis_client` (chạy `flushdb` lúc dựng) nên bộ đếm
    sạch cho mỗi bài mà không phải dọn tay.
    """
    monkeypatch.setenv("INGEST_NHIP_EVENTS_MOI_PHUT", "1")
    _, tho = token
    h = {"Authorization": f"Bearer {tho}"}

    assert (await app_client.post(f"{NEN}/events", json=LO_HOP_LE, headers=h)).status_code == 200

    r = await app_client.post(f"{NEN}/events", json=LO_HOP_LE, headers=h)
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert "1" in r.json()["error"]["message"], "ngưỡng phải nằm trong câu lỗi"


async def test_nhip_events_khong_an_vao_han_muc_manifest(app_client, token, monkeypatch):
    """Hai cửa, hai bộ đếm — kiểm qua HTTP thật, không chỉ ở tầng hàm."""
    monkeypatch.setenv("INGEST_NHIP_EVENTS_MOI_PHUT", "1")
    _, tho = token
    h = {"Authorization": f"Bearer {tho}"}

    await app_client.post(f"{NEN}/events", json=LO_HOP_LE, headers=h)
    assert (await app_client.post(f"{NEN}/events", json=LO_HOP_LE, headers=h)).status_code == 429

    r = await app_client.post(f"{NEN}/manifest", json={"entity": "project", "records": []}, headers=h)
    assert r.status_code == 200, r.text


# ─── Hợp đồng vỏ: tz-aware + chặn NUL ─────────────────────────────────────


async def test_occurredAt_naive_bi_422(app_client, token):
    """asyncpg encode datetime naive theo GIỜ HOST — trọng tài thứ tự duy nhất của
    hợp đồng mà diễn giải tuỳ máy là sai theo hướng lệch lặng lẽ. Bắt tz tường minh."""
    _, tho = token
    r = await app_client.post(
        f"{NEN}/events",
        headers={"Authorization": f"Bearer {tho}"},
        json={
            "records": [
                {
                    "entity": "project",
                    "externalId": "P-NAIVE",
                    "op": "upsert",
                    "occurredAt": "2026-08-15T10:00:00",  # không offset, không Z
                    "data": {"name": "X"},
                }
            ]
        },
    )
    assert r.status_code == 422


async def test_externalId_chua_nul_bi_422(app_client, token):
    """NUL trong chuỗi làm Postgres từ chối (22P05) — chặn ở vỏ cho ra 422
    field-level thay vì một câu 500 ở giữa lô."""
    _, tho = token
    r = await app_client.post(
        f"{NEN}/events",
        headers={"Authorization": f"Bearer {tho}"},
        json={
            "records": [
                {
                    "entity": "project",
                    "externalId": "P\x00ID",
                    "op": "upsert",
                    "occurredAt": "2026-08-15T10:00:00Z",
                    "data": {"name": "X"},
                }
            ]
        },
    )
    assert r.status_code == 422


async def test_manifest_dry_run_qua_query_khong_ghi_gi(app_client, api_pool, token):
    """Parse query `dryRun` của `/manifest` — cùng lớp rủi ro với `dryRun` của
    `/events` mà file này đã canh: sai kiểu ⇒ một lượt DIỄN TẬP gắn cờ THẬT lên
    dữ liệu khách."""
    from portal.core.db.session import tenant_conn

    a, tho = token
    await app_client.post(f"{NEN}/events", json=LO_HOP_LE, headers={"Authorization": f"Bearer {tho}"})

    r = await app_client.post(
        f"{NEN}/manifest?dryRun=true",
        json={"entity": "project", "records": []},
        headers={"Authorization": f"Bearer {tho}"},
    )
    assert r.status_code == 200, r.text
    than = r.json()
    assert than["dryRun"] is True
    assert than["externalIdNghiMatTich"] == ["HTTP-P1"], "kết quả so phải thật"

    async with tenant_conn(api_pool, a) as conn:
        co = await conn.fetch(
            "SELECT 1 FROM tenant_data.ingest_records WHERE tenant_id = portal.current_tenant()"
            " AND nghi_mat_tich_tu IS NOT NULL"
        )
    assert co == [], "dryRun qua HTTP không được gắn cờ thật"
