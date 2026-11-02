"""Phân khu (§3.1), enrich khi thay tệp (D6), và `sync-kb?mode=`.

Phân khu là trường hợp riêng: sổ `kb_index_state` mang `project_code` nhưng không
mang `zone_code`, nên danh sách media của phân khu phải chụp TRƯỚC khi
`ON DELETE CASCADE` xoá chúng.
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


async def _tao_phan_khu(client, project_code: str, zone_code: str) -> int:
    r = await client.post(
        f"/api/v1/projects/{project_code}/zones",
        json={"zoneCode": zone_code, "name": f"Khu {zone_code}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _tao_media(client, project_code: str, url: str, **kw) -> int:
    body = {"contentType": "image", "category": "tong_quan", "mediaUrl": url, **kw}
    r = await client.post(f"/api/v1/projects/{project_code}/media", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_xoa_phan_khu_nap_lai_du_an_va_purge_media_cua_zone(client_re, workspace_re, pool):
    """Phân khu không còn point riêng (spec 2026-08-19) ⇒ xoá nó là NẠP LẠI dự án.
    Media neo vào zone vẫn phải purge từng cái: worker chỉ cascade theo `anchor_code`.

    VẪN xếp purge cho chính `zones`: bài này từng ghim điều ngược lại, và đó là một giả
    định sai — workspace chưa chạy `portal.cli.drop_zone_points` CÒN point `phan_khu`
    (đo trên dev 2026-08-19: 66 point ở 3 workspace), mà nạp lại dự án không chạm chúng.
    Purge là vô hại khi không còn point: worker tra `kb_index_state`, không dòng thì
    không xoá gì. Xem `test_xoa_phan_khu_purge_point_cu.py`."""
    await _tao_du_an(client_re, "pk1")
    await _tao_phan_khu(client_re, "pk1", "z1")
    mid = await _tao_media(client_re, "pk1", "pk1/z1.jpg", zoneCode="z1")
    mid_ngoai = await _tao_media(client_re, "pk1", "pk1/khac.jpg")

    r = await client_re.delete("/api/v1/projects/pk1/zones/z1")
    assert r.status_code == 204

    js = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert any(j.get("entity") == "zones" for j in js), "point phan_khu cũ của chính phân khu này phải được purge"
    assert any(j.get("entity") == "media" and j.get("record_id") == mid for j in js)
    nap = await _payload_jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "projects" for j in nap), "xoá phân khu phải nạp lại dự án cha"
    assert not any(j.get("entity") == "media" and j.get("record_id") == mid_ngoai for j in js), (
        "media không thuộc phân khu bị kéo theo"
    )


async def test_xoa_phan_khu_khong_dung_nhanh_anchor(client_re, workspace_re, pool):
    """Nhánh `anchor_code` xoá point của CẢ dự án — dùng nó ở đây là mất sạch dữ liệu
    của các phân khu còn lại."""
    await _tao_du_an(client_re, "pk2")
    await _tao_phan_khu(client_re, "pk2", "z1")

    await client_re.delete("/api/v1/projects/pk2/zones/z1")

    js = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert not any(j.get("anchor_code") for j in js)


async def test_an_phan_khu_nap_lai_chu_khong_xoa_point(client_re, workspace_re, pool):
    """D08 — trạng thái phân khu đi vào payload point qua đường nạp, không qua xoá."""
    await _tao_du_an(client_re, "pk3")
    zid = await _tao_phan_khu(client_re, "pk3", "z1")
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE tenant_data.zones SET status = 'published' WHERE tenant_id = portal.current_tenant() AND id = $1",
            zid,
        )
    truoc = await _payload_jobs(pool, workspace_re, "kb_delete")

    r = await client_re.patch("/api/v1/projects/pk3/zones/z1", json={"status": "draft"})
    assert r.status_code == 200, r.text

    sau = await _payload_jobs(pool, workspace_re, "kb_delete")
    assert len(sau) == len(truoc), "ẩn phân khu vẫn xếp job xoá point"

    nap = await _payload_jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "projects" for j in nap), "ẩn phân khu phải nạp lại dự án cha"


async def test_thay_anh_thi_sinh_lai_thumb_chu_khong_goi_model(client_re, workspace_re, pool):
    """D11 — thumb là dẫn xuất máy móc của tệp nên sinh lại; mô tả là nội dung có người
    chịu trách nhiệm nên KHÔNG. Trước 2026-08-15 nhánh này gọi VLM với `force=True`."""
    await _tao_du_an(client_re, "ta1")
    mid = await _tao_media(client_re, "ta1", "ta1/cu.jpg", caption="mô tả của ảnh cũ")
    enrich_truoc = await _payload_jobs(pool, workspace_re, "kb_enrich")

    r = await client_re.patch(f"/api/v1/projects/ta1/media/{mid}", json={"mediaUrl": "ta1/moi.jpg"})
    assert r.status_code == 200, r.text

    thumb = await _payload_jobs(pool, workspace_re, "kb_thumb")
    assert any(j.get("record_id") == mid and j.get("ghi_de") is True for j in thumb)

    enrich_sau = await _payload_jobs(pool, workspace_re, "kb_enrich")
    assert len(enrich_sau) == len(enrich_truoc), "đổi ảnh vẫn gọi model tả lại"


async def test_sua_rieng_caption_khong_xep_job_nao(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "ca1")
    mid = await _tao_media(client_re, "ca1", "ca1/a.jpg")
    truoc = await _payload_jobs(pool, workspace_re, "kb_enrich")

    r = await client_re.patch(f"/api/v1/projects/ca1/media/{mid}", json={"caption": "tôi tự viết"})
    assert r.status_code == 200, r.text

    sau = await _payload_jobs(pool, workspace_re, "kb_enrich")
    assert len(sau) == len(truoc), "sửa chú thích tay không được kích hoạt VLM"

    thumb = await _payload_jobs(pool, workspace_re, "kb_thumb")
    assert any(j.get("record_id") == mid and not j.get("ghi_de") for j in thumb), "sửa mô tả phải nạp lại"


async def test_gui_dung_url_cu_khong_xep_job(client_re, workspace_re, pool):
    """Form gửi lại nguyên vẹn mọi field là chuyện thường — không được coi là thay ảnh."""
    await _tao_du_an(client_re, "ca2")
    mid = await _tao_media(client_re, "ca2", "ca2/a.jpg")
    truoc = await _payload_jobs(pool, workspace_re, "kb_enrich")

    r = await client_re.patch(f"/api/v1/projects/ca2/media/{mid}", json={"mediaUrl": "ca2/a.jpg"})
    assert r.status_code == 200, r.text

    sau = await _payload_jobs(pool, workspace_re, "kb_enrich")
    assert len(sau) == len(truoc)


async def test_thay_tep_tai_lieu_thi_boc_lai_noi_dung(client_re, workspace_re, pool):
    """Chuỗi mở đầu bằng thumb (`ghi_de`) rồi mới bóc chữ — cả hai đều mang `force`."""
    await _tao_du_an(client_re, "tf1")
    r = await client_re.post(
        "/api/v1/projects/tf1/documents",
        json={"title": "Bảng giá", "loai": "csbh", "fileUrl": "tf1/cu.pdf"},
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    r = await client_re.patch(f"/api/v1/projects/tf1/documents/{did}", json={"fileUrl": "tf1/moi.pdf"})
    assert r.status_code == 200, r.text

    js = await _payload_jobs(pool, workspace_re, "kb_thumb")
    khop = [j for j in js if j.get("record_id") == did and j.get("ghi_de") is True]
    assert khop, "thay tệp mà giữ ảnh thu nhỏ và nội dung bóc từ tệp cũ"


async def test_sync_kb_nhan_mode_full(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "sy1")
    r = await client_re.post("/api/v1/projects/sy1/sync-kb?mode=full")
    assert r.status_code == 202, r.text

    js = await _payload_jobs(pool, workspace_re, "kb_sync_project")
    assert js and js[-1]["mode"] == "full"


async def test_sync_kb_mac_dinh_delta(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "sy2")
    r = await client_re.post("/api/v1/projects/sy2/sync-kb")
    assert r.status_code == 202, r.text

    js = await _payload_jobs(pool, workspace_re, "kb_sync_project")
    assert js and js[-1]["mode"] == "delta"


async def test_mode_la_khong_hop_le_thi_422(client_re, workspace_re):
    await _tao_du_an(client_re, "sy3")
    r = await client_re.post("/api/v1/projects/sy3/sync-kb?mode=xyz")
    assert r.status_code == 422


async def test_nhat_ky_ghi_ca_mode(client_re, workspace_re, pool):
    """Nạp lại toàn bộ là việc tốn tiền — phải lần được ai bấm và bấm chế độ nào."""
    await _tao_du_an(client_re, "sy4")
    await client_re.post("/api/v1/projects/sy4/sync-kb?mode=full")

    async with pool.acquire() as conn:
        chi_tiet = await conn.fetchval(
            "SELECT chi_tiet FROM control.audit_log "
            "WHERE tenant_id = $1 AND hanh_dong = 'realestate.knowledge.sync' ORDER BY id DESC LIMIT 1",
            workspace_re,
        )
    d = json.loads(chi_tiet) if isinstance(chi_tiet, str) else dict(chi_tiet)
    assert d["mode"] == "full"
