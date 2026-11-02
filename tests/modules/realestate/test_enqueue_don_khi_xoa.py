"""CHỈ `DELETE` mới xoá point. Ẩn/lưu trữ thì đổi cờ.

Thiếu một đường xoá là point mồ côi im lặng: agent tiếp tục gửi tài liệu/ảnh đã xoá
cho khách, không lỗi, không log. Ngược lại, xoá point khi chỉ ẩn (hành vi trước
2026-08-15) làm việc công bố lại phải nhúng lại cả cây.
"""

import json

import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


async def _payload_jobs(pool, tenant_id: str, kind: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id",
            tenant_id,
            kind,
        )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def _tao_du_an(client, code: str) -> None:
    r = await client.post("/api/v1/projects", json={"projectCode": code, "name": f"Dự án {code}"})
    assert r.status_code == 201, r.text


async def _bat_published(pool, tenant: str, code: str) -> None:
    async with tenant_conn(pool, tenant) as conn:
        await conn.execute(
            "UPDATE tenant_data.projects SET status = 'published' "
            "WHERE tenant_id = portal.current_tenant() AND project_code = $1",
            code,
        )


async def test_xoa_du_an_xep_job_cascade(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "xoa1")

    r = await client_re.delete("/api/v1/projects/xoa1")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert any(j.get("anchor_code") == "xoa1" for j in js), "xoá dự án không xếp job cascade"


async def test_an_du_an_doi_co_chu_khong_xoa_point(client_re, workspace_re, pool):
    """D08 — ẩn dự án KHÔNG xoá point nữa, chỉ đổi `status` trong payload."""
    await _tao_du_an(client_re, "an1")
    await _bat_published(pool, workspace_re, "an1")
    truoc = await _payload_jobs(pool, workspace_re, "kb_delete")

    r = await client_re.patch("/api/v1/projects/an1", json={"status": "draft"})
    assert r.status_code == 200, r.text

    sau = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert len(sau) == len(truoc), "ẩn dự án vẫn xếp job xoá point"

    co = await _payload_jobs(pool, workspace_re, "kb_doi_co")
    assert any(j.get("project_code") == "an1" for j in co), "ẩn dự án không xếp job đổi cờ"


async def test_cong_bo_du_an_xep_job_doi_co(client_re, workspace_re, pool):
    """Chiều published←draft là chiều hay bị bỏ sót: nội dung không đổi nên dấu tay
    giống nhau và đường nạp thoát sớm — không có job đổi cờ thì công bố xong agent
    vẫn không thấy gì, mà mọi thứ báo thành công."""
    await _tao_du_an(client_re, "cb1")

    r = await client_re.patch("/api/v1/projects/cb1", json={"status": "published"})
    assert r.status_code in (200, 422), r.text
    if r.status_code == 422:
        pytest.skip("dự án thiếu trường bắt buộc để publish — ca này do completeness chặn")

    co = await _payload_jobs(pool, workspace_re, "kb_doi_co")
    assert any(j.get("project_code") == "cb1" for j in co)


async def test_du_an_van_published_thi_khong_xep_job_xoa(client_re, workspace_re, pool):
    """Sửa nội dung một dự án đang published KHÔNG được xoá point của nó."""
    await _tao_du_an(client_re, "gn1")
    await _bat_published(pool, workspace_re, "gn1")
    truoc = await _payload_jobs(pool, workspace_re, "kb_delete")

    r = await client_re.patch("/api/v1/projects/gn1", json={"investor": "Chủ đầu tư mới"})
    assert r.status_code in (200, 422)

    sau = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert len(sau) == len(truoc)


async def test_xoa_media_xep_job_theo_record(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "md1")
    r = await client_re.post(
        "/api/v1/projects/md1/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "md1/a.jpg"},
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    r = await client_re.delete(f"/api/v1/projects/md1/media/{mid}")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert any(j.get("entity") == "media" and j.get("record_id") == mid for j in js)


async def test_xoa_tai_lieu_xep_job_theo_record(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tl1")
    r = await client_re.post(
        "/api/v1/projects/tl1/documents",
        json={"title": "Bảng giá", "loai": "csbh", "body": "nội dung"},
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    r = await client_re.delete(f"/api/v1/projects/tl1/documents/{did}")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert any(j.get("entity") == "documents" and j.get("record_id") == did for j in js)


async def test_job_xoa_tai_lieu_khong_khai_doc_type(client_re, workspace_re, pool):
    """Row đã xoá nên không suy được loại từ nội dung — worker tra sổ và xoá đúng
    những loại đang tồn tại. Khai một loại đoán được ở đây là xoá trượt."""
    await _tao_du_an(client_re, "tl2")
    r = await client_re.post(
        "/api/v1/projects/tl2/documents",
        json={"title": "Hợp đồng", "loai": "phap_ly", "body": "x"},
    )
    did = r.json()["id"]
    await client_re.delete(f"/api/v1/projects/tl2/documents/{did}")

    js = await _payload_jobs(pool, workspace_re, "kb_delete")
    cua_no = [j for j in js if j.get("record_id") == did and j.get("entity") == "documents"]
    assert cua_no and not cua_no[0].get("doc_type")


async def test_doi_loai_tai_lieu_xep_ca_job_xoa_va_job_nap(client_re, workspace_re, pool):
    """Đổi loại sinh point id mới, nên phải xoá point loại cũ VÀ nạp theo loại mới.

    Trước 2026-08-15 nhánh này cố ý chỉ xoá, vì nạp là việc người dùng bấm. Nút đó đã
    bỏ, nên chỉ-xoá nghĩa là tài liệu biến mất khỏi agent cho tới lần sửa sau.
    """
    await _tao_du_an(client_re, "dl1")
    r = await client_re.post(
        "/api/v1/projects/dl1/documents",
        json={"title": "Bảng giá", "loai": "csbh", "body": "x"},
    )
    did = r.json()["id"]

    r = await client_re.patch(f"/api/v1/projects/dl1/documents/{did}", json={"loai": "phap_ly"})
    assert r.status_code == 200, r.text

    nap = await _payload_jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "documents" and j.get("record_id") == did for j in nap)

    xoa = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert any(j.get("record_id") == did and j.get("doc_type") == "csbh" for j in xoa)
