"""Cổng phát hành chặn HÀNH ĐỘNG publish, không chặn mọi lần sửa (spec §3.5.2).

Bản trước tính `trang_thai_moi = payload.get("status", hang["status"])`, nên với
một dự án ĐÃ `published` thì **mọi** PATCH đi qua cổng — kể cả PATCH chỉ sửa một
ô không liên quan. Cổng cũ nhẹ (`name`+`region`) nên chuyện đó chưa nổ; siết lên
năm trường thì 20/94 dự án published trên Aurora dev trả 422 ở mọi lần sửa,
không còn đường chữa từ giao diện.

Đây đúng chế độ hỏng mà `_bo_qua_completeness_du_an` đã ghi cho `__ALL__`:
*"MỌI PATCH sau đó… kể cả chỉ sửa một field không liên quan, sẽ bị 422 vĩnh viễn"*.

Bài quan trọng nhất của file là `test_sua_o_khong_lien_quan_cua_du_an_published_thieu_truong`
— nó đỏ ngay nếu ai đó hoàn nguyên §3.5.2.
"""

import asyncpg
import httpx
import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


DU_TRUONG = {
    "name": "Vinhomes Ocean Park 2",
    "region": "Hà Nội",
    "overview": "Đại đô thị biển hồ phía đông.",
    "investor": "Vinhomes",
    "productScale": "3 toà · 1.240 căn",
}


async def _dat_status_thang_db(pool: asyncpg.Pool, tenant: str, code: str, status: str) -> None:
    """Đặt `status` bằng SQL, KHÔNG qua API.

    Cần đường này vì API mới không cho tạo một dự án `published` mà thiếu trường
    — mà đó chính là trạng thái của 20 hàng trên Aurora, sinh ra dưới luật cũ.
    Dựng nó bằng API là dựng một tình huống khác với tình huống cần canh.
    """
    async with tenant_conn(pool, tenant) as conn:
        await conn.execute(
            "UPDATE tenant_data.projects SET status = $1 "
            "WHERE tenant_id = portal.current_tenant() AND project_code = $2",
            status,
            code,
        )


async def test_publish_moi_ma_thieu_truong_thi_chan(client_re: httpx.AsyncClient) -> None:
    r = await client_re.post(
        _url("/projects"),
        json={"projectCode": "GATE1", "name": "Có tên", "region": "Hà Nội", "status": "published"},
    )
    assert r.status_code == 422, r.text
    than = r.json()["error"]
    assert than["code"] == "INCOMPLETE_DATA"
    assert "overview" in than["message"]


async def test_chuyen_draft_sang_published_ma_thieu_truong_thi_chan(
    client_re: httpx.AsyncClient,
) -> None:
    await client_re.post(_url("/projects"), json={"projectCode": "GATE2", "name": "Nháp"})
    r = await client_re.patch(_url("/projects/GATE2"), json={"status": "published"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INCOMPLETE_DATA"


async def test_publish_du_nam_truong_thi_qua(client_re: httpx.AsyncClient) -> None:
    r = await client_re.post(_url("/projects"), json={"projectCode": "GATE3", **DU_TRUONG, "status": "published"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "published"


async def test_sua_o_khong_lien_quan_cua_du_an_published_thieu_truong(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
) -> None:
    """20 hàng Aurora: `published` từ trước, thiếu `overview`. Sửa một ô không
    thuộc cổng phải ĐI QUA — nếu không, người biên tập bị khoá ngoài chính dự án
    họ cần điền nốt."""
    await client_re.post(_url("/projects"), json={"projectCode": "GATE4", "name": "Đã phát hành", "region": "Hà Nội"})
    await _dat_status_thang_db(pool, workspace_re, "GATE4", "published")

    r = await client_re.patch(_url("/projects/GATE4"), json={"developer": "Ai đó"})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
    assert r.json()["developer"] == "Ai đó"


async def test_xoa_trang_mot_truong_cua_cong_tren_du_an_published_thi_chan(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
) -> None:
    """Vế thứ hai của luật. Không có nó, cổng chỉ gác lúc vào cửa và một PATCH
    xoá trắng `overview` của dự án đang published đi lọt."""
    await client_re.post(_url("/projects"), json={"projectCode": "GATE5", **DU_TRUONG, "status": "published"})

    r = await client_re.patch(_url("/projects/GATE5"), json={"overview": ""})

    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INCOMPLETE_DATA"


async def test_sua_du_an_draft_thieu_truong_van_qua(client_re: httpx.AsyncClient) -> None:
    """Nháp không bị ràng buộc completeness — nó đang được soạn dở."""
    await client_re.post(_url("/projects"), json={"projectCode": "GATE6", "name": "Nháp"})
    r = await client_re.patch(_url("/projects/GATE6"), json={"investor": "Chỉ có chủ đầu tư"})
    assert r.status_code == 200, r.text


async def test_du_an_archived_khong_bi_cong_chan(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
) -> None:
    await client_re.post(_url("/projects"), json={"projectCode": "GATE7", "name": "Lưu trữ"})
    await _dat_status_thang_db(pool, workspace_re, "GATE7", "archived")
    r = await client_re.patch(_url("/projects/GATE7"), json={"developer": "X"})
    assert r.status_code == 200, r.text
