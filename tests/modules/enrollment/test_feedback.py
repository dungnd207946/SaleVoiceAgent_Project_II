"""`POST /agent/feedback` (Bearer api_key) + `GET /agent/feedback` (session) qua app THẬT.

Điều bộ test này bảo vệ, theo thứ tự quan trọng:

  1. TENANT SUY TỪ KHOÁ, KHÔNG TỪ CLIENT. `FeedbackIn` không có trường `tenant_id`
     (`extra="forbid"`) — gửi thêm trường đó phải bị TỪ CHỐI (422), không bị làm
     ngơ, đúng lý lẽ đã chốt lúc thiết kế: tin `tenant_id` client gửi là lỗ hổng.
  2. KHOÁ ĐÃ THU HỒI KHÔNG GHI ĐƯỢC NỮA — cùng cổng `tra_khoa()` mà
     `/runtime-credentials` dùng, không phải một đường xác thực riêng dễ quên
     kiểm thu hồi.
  3. CÁCH LY TENANT ở chiều ĐỌC (`GET /agent/feedback`, session): feedback của
     workspace A không được lộ sang workspace B, và cổng quyền là
     `ACTIONS.CONVOS_READ`, không phải "đã đăng nhập là được".

Fixture `client`/`client_admin`/`nguoi_dung`/`vai_tro_hep` dùng chung với
`test_router_tenant.py`, sống ở `conftest.py` (pytest tự nạp cho cả cây test
dưới thư mục này) — không import chéo giữa hai file test.
"""

import httpx
import pytest

from portal.core.auth.actions import ACTIONS
from portal.modules.enrollment import service
from tests.modules.enrollment.conftest import EMAIL_ADMIN, EMAIL_THUONG, TENANT_A, TENANT_B, _vao

GOC = "/api/v1/agent"


async def _tao_khoa(client_admin: httpx.AsyncClient) -> str:
    r = await client_admin.post(f"{GOC}/keys", json={"label": "pod feedback"})
    assert r.status_code == 201, r.text
    return r.json()["api_key"]


# ─── Ghi feedback (Bearer api_key) ─────────────────────────────────────────────


async def test_ghi_feedback_thanh_cong_204(client_admin, pool):
    khoa = await _tao_khoa(client_admin)

    r = await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_1", "rating": 5, "comment": "Trả lời nhanh"},
    )
    assert r.status_code == 204, r.text

    hang = await pool.fetchrow(
        "SELECT tenant_id, session_id, rating, comment FROM tenant_data.agent_feedback WHERE tenant_id = $1",
        TENANT_A,
    )
    assert hang["tenant_id"] == TENANT_A
    assert hang["session_id"] == "sess_1"
    assert hang["rating"] == 5
    assert hang["comment"] == "Trả lời nhanh"


async def test_ghi_feedback_comment_rong_hop_le(client_admin, pool):
    """`comment` mặc định rỗng — không phải ai cho sao cũng viết thêm."""
    khoa = await _tao_khoa(client_admin)

    r = await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_2", "rating": 3},
    )
    assert r.status_code == 204, r.text

    comment = await pool.fetchval(
        "SELECT comment FROM tenant_data.agent_feedback WHERE tenant_id = $1 AND session_id = 'sess_2'", TENANT_A
    )
    assert comment == ""


async def test_ghi_feedback_khoa_khong_hop_le_thi_401(client_admin):
    r = await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": "Bearer ody_ag_khong_ton_tai"},
        json={"session_id": "sess_x", "rating": 5},
    )
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "INVALID_AGENT_KEY"


async def test_ghi_feedback_thieu_bearer_thi_401(client_admin):
    r = await client_admin.post(f"{GOC}/feedback", json={"session_id": "sess_x", "rating": 5})
    assert r.status_code == 401


async def test_ghi_feedback_khoa_da_thu_hoi_thi_401(client_admin):
    r = await client_admin.post(f"{GOC}/keys", json={"label": "sap thu hoi"})
    tao = r.json()
    khoa = tao["api_key"]

    await client_admin.post(f"{GOC}/keys/{tao['id']}", json={"status": "inactive"})

    r = await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_thu_hoi", "rating": 1},
    )
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "INVALID_AGENT_KEY"


async def test_ghi_feedback_rating_ngoai_khoang_thi_422(client_admin):
    khoa = await _tao_khoa(client_admin)
    for rating in (0, 6, -1):
        r = await client_admin.post(
            f"{GOC}/feedback",
            headers={"Authorization": f"Bearer {khoa}"},
            json={"session_id": "sess_x", "rating": rating},
        )
        assert r.status_code == 422, (rating, r.text)


async def test_ghi_feedback_session_id_rong_thi_422(client_admin):
    khoa = await _tao_khoa(client_admin)
    r = await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "", "rating": 5},
    )
    assert r.status_code == 422


async def test_ghi_feedback_gui_them_tenant_id_thi_422(client_admin):
    """`extra="forbid"`: `tenant_id` không phải trường client được gửi — tenant
    suy từ khoá. Làm ngơ trường này là mời client tưởng mình chọn được tenant."""
    khoa = await _tao_khoa(client_admin)
    r = await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_x", "rating": 5, "tenant_id": TENANT_B},
    )
    assert r.status_code == 422


async def test_ghi_feedback_khoa_cua_tenant_nao_ghi_dung_tenant_do(client, client_admin, pool):
    """Khoá của B ghi feedback thì phải vào đúng hàng tenant_id = B, dù request
    này được gửi qua cùng một client HTTP đang đăng nhập ở workspace A — vì
    tenant ở đây suy từ KHOÁ, không phải từ phiên đang mở của client gọi."""
    await _vao(client, EMAIL_ADMIN, TENANT_B)
    khoa_b = (await client.post(f"{GOC}/keys", json={"label": "cua B"})).json()["api_key"]

    r = await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa_b}"},
        json={"session_id": "sess_b", "rating": 4},
    )
    assert r.status_code == 204, r.text

    tenant_ghi = await pool.fetchval("SELECT tenant_id FROM tenant_data.agent_feedback WHERE session_id = 'sess_b'")
    assert tenant_ghi == TENANT_B


# ─── Liệt kê (session, ACTIONS.CONVOS_READ) ────────────────────────────────────


async def test_liet_ke_feedback_tra_dung_workspace_hien_tai(client_admin):
    khoa = await _tao_khoa(client_admin)
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_1", "rating": 5, "comment": "tốt"},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["session_id"] == "sess_1"
    assert body["items"][0]["rating"] == 5
    assert body["next_before_id"] is None


async def test_liet_ke_feedback_khong_lo_sang_tenant_khac(client, client_admin):
    khoa_a = await _tao_khoa(client_admin)
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa_a}"},
        json={"session_id": "sess_a", "rating": 5},
    )

    await _vao(client, EMAIL_ADMIN, TENANT_B)
    r = await client.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    assert r.json()["total"] == 0


async def test_liet_ke_feedback_phan_trang_keyset(client_admin):
    khoa = await _tao_khoa(client_admin)
    for i in range(3):
        r = await client_admin.post(
            f"{GOC}/feedback",
            headers={"Authorization": f"Bearer {khoa}"},
            json={"session_id": f"sess_{i}", "rating": 5},
        )
        assert r.status_code == 204

    trang_1 = (await client_admin.get(f"{GOC}/feedback", params={"limit": 2})).json()
    assert len(trang_1["items"]) == 2
    assert trang_1["total"] == 3
    assert trang_1["next_before_id"] is not None
    # Mới nhất trước: hàng cuối cùng ghi (sess_2) phải đứng đầu.
    assert trang_1["items"][0]["session_id"] == "sess_2"

    trang_2 = (
        await client_admin.get(f"{GOC}/feedback", params={"limit": 2, "before_id": trang_1["next_before_id"]})
    ).json()
    assert len(trang_2["items"]) == 1
    assert trang_2["next_before_id"] is None
    assert trang_2["items"][0]["session_id"] == "sess_0"


async def test_liet_ke_feedback_loc_theo_session_id(client_admin):
    khoa = await _tao_khoa(client_admin)
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_muc_tieu", "rating": 5},
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_khac", "rating": 1},
    )

    r = await client_admin.get(f"{GOC}/feedback", params={"session_id": "sess_muc_tieu"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["session_id"] for i in body["items"]] == ["sess_muc_tieu"]


async def test_liet_ke_feedback_loc_theo_rating(client_admin):
    khoa = await _tao_khoa(client_admin)
    for i, rating in enumerate((1, 3, 5)):
        await client_admin.post(
            f"{GOC}/feedback",
            headers={"Authorization": f"Bearer {khoa}"},
            json={"session_id": f"sess_r{i}", "rating": rating},
        )

    r = await client_admin.get(f"{GOC}/feedback", params=[("rating", 1), ("rating", 5)])
    assert r.status_code == 200, r.text
    ratings = sorted(i["rating"] for i in r.json()["items"])
    assert ratings == [1, 5]


async def test_liet_ke_feedback_chua_dang_nhap_thi_401(client):
    assert (await client.get(f"{GOC}/feedback")).status_code == 401


async def test_liet_ke_feedback_thieu_convos_read_thi_403(client, vai_tro_hep):
    await _vao(client, EMAIL_THUONG, TENANT_A)
    assert (await client.get(f"{GOC}/feedback")).status_code == 403


def test_action_dung_la_convos_read():
    """Neo lựa chọn action: feedback là một góc nhìn của Hội thoại (nhóm 2 PQ_01),
    không phải `workspace.admin` (nhóm 13) như ba endpoint `/agent/keys`."""
    assert ACTIONS.CONVOS_READ == "convos.read"


# ─── JOIN tenant_data.conversations (customer_name/phone) ──────────────────────


async def test_liet_ke_feedback_join_ten_va_sdt_tu_conversations(client_admin, pool):
    khoa = await _tao_khoa(client_admin)
    await pool.execute(
        """
        INSERT INTO tenant_data.conversations (tenant_id, session_id, phone, customer_name)
        VALUES ($1, $2, $3, $4)
        """,
        TENANT_A,
        "sess_co_ten",
        "0912345678",
        "Trần Văn A",
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_co_ten", "rating": 5},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["customer_name"] == "Trần Văn A"
    assert item["phone"] == "0912345678"


async def test_liet_ke_feedback_join_kenh_tu_conversations(client_admin, pool):
    """`source` = kênh phiên đến từ đâu (`voice`/`chat`, cột `conversations.source`
    do agent ghi). FE `/quality` vẽ chip Chat/Voice trên từng feedback — không có
    trường này thì màn đó phải đoán, mà không có gì để đoán từ."""
    khoa = await _tao_khoa(client_admin)
    await pool.execute(
        """
        INSERT INTO tenant_data.conversations (tenant_id, session_id, source)
        VALUES ($1, $2, $3)
        """,
        TENANT_A,
        "sess_voice",
        "voice",
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_voice", "rating": 4},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["session_id"] == "sess_voice")
    assert item["source"] == "voice"


async def test_liet_ke_feedback_kenh_null_khi_agent_chua_gui(client_admin, pool):
    """`conversations.source` là NULLABLE có chủ ý (`0916`: "chưa biết nguồn" khác
    "nguồn rỗng") — agent bản cũ chưa gửi trường này. Trả `None`, KHÔNG lấp bằng
    một giá trị mặc định nào: FE ẩn chip thay vì hiện một kênh bịa ra."""
    khoa = await _tao_khoa(client_admin)
    await pool.execute(
        """
        INSERT INTO tenant_data.conversations (tenant_id, session_id, customer_name)
        VALUES ($1, $2, $3)
        """,
        TENANT_A,
        "sess_kenh_trong",
        "Trần Văn B",
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_kenh_trong", "rating": 4},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    item = next(i for i in r.json()["items"] if i["session_id"] == "sess_kenh_trong")
    assert item["customer_name"] == "Trần Văn B"
    assert item["source"] is None


async def test_liet_ke_feedback_khong_co_conversations_thi_null(client_admin):
    """Feedback vẫn hiện được dù chưa từng có hàng `conversations` khớp —
    KHÔNG FK, đúng lý lẽ đã chốt (agent có thể gọi feedback trước/độc lập
    với việc ghi conversations)."""
    khoa = await _tao_khoa(client_admin)
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_khong_co_conv", "rating": 3},
    )

    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["session_id"] == "sess_khong_co_conv")
    assert item["customer_name"] is None
    assert item["phone"] is None


async def test_liet_ke_feedback_join_khong_lo_ten_tenant_khac(client_admin, pool):
    """Cùng session_id trùng ở hai tenant KHÔNG được lộ tên/sđt của tenant kia
    qua JOIN — vị từ JOIN phải mang CẢ tenant_id, không chỉ session_id.

    Gọi `service.liet_ke_feedback_cua_tenant` TRỰC TIẾP qua `pool` (role
    `portal_migrator`, superuser, BYPASS RLS) — KHÔNG qua `client_admin`/HTTP.
    `tenant_data.conversations` có RLS FORCE (`0913`): nếu chạy qua role
    `portal_api` (RLS áp), Postgres tự gắn `AND c.tenant_id = current_tenant()`
    vào chính table scan của `conversations` trong LEFT JOIN — tức RLS sẽ
    "cứu" test này khỏi đỏ NGAY CẢ KHI vị từ JOIN trong code thiếu điều kiện
    `tenant_id`, làm test không phân biệt được đúng/sai. Bỏ RLS ra ở đây là
    cố ý, để buộc CHÍNH điều kiện JOIN trong `service.py` tự chịu trách nhiệm
    cách ly, không phải phòng thủ-nhị-trùng kiểu "test RLS bằng superuser".
    """
    khoa = await _tao_khoa(client_admin)
    await pool.execute(
        """
        INSERT INTO tenant_data.conversations (tenant_id, session_id, phone, customer_name)
        VALUES ($1, $2, $3, $4)
        """,
        TENANT_B,
        "sess_trung_id",
        "0900000000",
        "Người của B",
    )
    await client_admin.post(
        f"{GOC}/feedback",
        headers={"Authorization": f"Bearer {khoa}"},
        json={"session_id": "sess_trung_id", "rating": 4},
    )

    ket_qua = await service.liet_ke_feedback_cua_tenant(pool, TENANT_A, limit=50, before_id=None)
    item = next(i for i in ket_qua.items if i.session_id == "sess_trung_id")
    assert item.customer_name is None
    assert item.phone is None


# ─── Thống kê (theo_sao/diem_trung_binh) — KHÔNG theo filter items ─────────────


async def test_liet_ke_feedback_thong_ke_khong_bi_anh_huong_boi_filter(client_admin):
    khoa = await _tao_khoa(client_admin)
    for i, rating in enumerate((1, 1, 5)):
        await client_admin.post(
            f"{GOC}/feedback",
            headers={"Authorization": f"Bearer {khoa}"},
            json={"session_id": f"sess_tk{i}", "rating": rating},
        )

    # Lọc chỉ 5 sao — items chỉ còn 1 hàng, nhưng thống kê vẫn phải phản ánh CẢ 3.
    r = await client_admin.get(f"{GOC}/feedback", params=[("rating", 5)])
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["theo_sao"] == {"1": 2, "2": 0, "3": 0, "4": 0, "5": 1}
    assert body["diem_trung_binh"] == pytest.approx((1 + 1 + 5) / 3, abs=0.01)


async def test_liet_ke_feedback_thong_ke_rong_khi_chua_co_gi(client_admin):
    r = await client_admin.get(f"{GOC}/feedback")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["theo_sao"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    assert body["diem_trung_binh"] == 0.0
