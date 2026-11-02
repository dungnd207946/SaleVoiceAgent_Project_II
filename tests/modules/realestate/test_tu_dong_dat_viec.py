"""Mỗi route ghi phải tự đặt việc nạp — không còn nút nào để người dùng bấm.

Đây là cổng của cả tính năng: hạ tầng (loại việc, gộp, retry, đổi cờ/nhãn) có đủ mà
route không gọi thì mọi thứ vẫn xanh trong khi tab kiến thức đứng im.
"""

import json

import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


async def _jobs(pool, tenant: str, kind: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id", tenant, kind
        )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def _tao_du_an(client, code: str, **kw) -> int:
    r = await client.post("/api/v1/projects", json={"projectCode": code, "name": f"Dự án {code}", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─── dự án ───────────────────────────────────────────────────────────────────


async def test_tao_du_an_dat_viec_nap(client_re, workspace_re, pool):
    pid = await _tao_du_an(client_re, "tv1")
    js = await _jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "projects" and j.get("record_id") == pid for j in js)


async def test_tao_du_an_kem_anh_bia_dat_viec_cho_CA_HAI(client_re, workspace_re, pool):
    """Ảnh bìa/bản đồ tạo BÊN TRONG route dự án — loại duy nhất do route của loại khác
    tạo, và trước 2026-08-15 không route nào đặt việc cho chúng."""
    pid = await _tao_du_an(
        client_re,
        "tv2",
        coverMedia={"mediaUrl": "tv2/bia.jpg"},
        mapMedia={"mediaUrl": "tv2/mb.jpg"},
    )
    nap = await _jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "projects" and j.get("record_id") == pid for j in nap)

    thumb = await _jobs(pool, workspace_re, "kb_thumb")
    assert len(thumb) == 2, f"ảnh bìa/bản đồ không được đặt việc: {thumb}"
    assert all(j.get("entity") == "media" for j in thumb)


async def test_sua_noi_dung_du_an_dat_viec_nap(client_re, workspace_re, pool):
    pid = await _tao_du_an(client_re, "tv3")
    r = await client_re.patch("/api/v1/projects/tv3", json={"overview": "nội dung mới"})
    assert r.status_code == 200, r.text

    js = await _jobs(pool, workspace_re, "kb_index")
    assert sum(1 for j in js if j.get("record_id") == pid) >= 1


async def test_doi_ten_du_an_chi_doi_nhan_KHONG_nap_lai(client_re, workspace_re, pool):
    """Dấu tay băm trên nội dung thuần nên đổi tên không đổi nội dung chunk nào —
    nạp lại cả cây ở đây là tiền embed tiêu vô ích (116 record cho một dự án)."""
    await _tao_du_an(client_re, "tv4")
    nap_truoc = await _jobs(pool, workspace_re, "kb_index")

    r = await client_re.patch("/api/v1/projects/tv4", json={"name": "Tên hoàn toàn mới"})
    assert r.status_code == 200, r.text

    nhan = await _jobs(pool, workspace_re, "kb_doi_nhan")
    assert any(j.get("project_code") == "tv4" for j in nhan)

    nap_sau = await _jobs(pool, workspace_re, "kb_index")
    assert len(nap_sau) == len(nap_truoc), "đổi tên vẫn xếp việc nạp"


async def test_doi_rieng_trang_thai_chi_doi_co_KHONG_nap_lai(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tv5")
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE tenant_data.projects SET status = 'published' "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'tv5'"
        )
    nap_truoc = await _jobs(pool, workspace_re, "kb_index")

    r = await client_re.patch("/api/v1/projects/tv5", json={"status": "archived"})
    assert r.status_code == 200, r.text

    co = await _jobs(pool, workspace_re, "kb_doi_co")
    assert any(j.get("project_code") == "tv5" for j in co)

    nap_sau = await _jobs(pool, workspace_re, "kb_index")
    assert len(nap_sau) == len(nap_truoc), "đổi trạng thái vẫn xếp việc nạp"


# ─── phân khu ────────────────────────────────────────────────────────────────


async def test_tao_phan_khu_dat_viec_nap_cho_du_an_cha(client_re, workspace_re, pool):
    """Phân khu là khối con của doc dự án (spec 2026-08-19) ⇒ việc nạp thuộc về dự án."""
    await _tao_du_an(client_re, "tv6")
    r = await client_re.post("/api/v1/projects/tv6/zones", json={"zoneCode": "z1", "name": "Khu A"})
    assert r.status_code == 201, r.text

    js = await _jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "projects" for j in js)
    assert not any(j.get("entity") == "zones" for j in js)


async def test_sua_phan_khu_dat_viec_nap(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tv7")
    await client_re.post("/api/v1/projects/tv7/zones", json={"zoneCode": "z1", "name": "Khu A"})

    r = await client_re.patch("/api/v1/projects/tv7/zones/z1", json={"overview": "mô tả phân khu"})
    assert r.status_code == 200, r.text

    js = await _jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "projects" for j in js)
    assert not any(j.get("entity") == "zones" for j in js)


# ─── căn hộ: KHÔNG việc nào ─────────────────────────────────────────────────


async def test_can_ho_khong_dat_viec_nao(client_re, workspace_re, pool):
    """Căn không nhúng vector — agent lọc căn bằng SQL trên cột thật. Đặt việc cho
    chúng là hàng nghìn job vô ích mỗi lần nhập quỹ căn."""
    await _tao_du_an(client_re, "tv8")
    r = await client_re.post("/api/v1/projects/tv8/zones", json={"zoneCode": "z1", "name": "Khu A"})
    assert r.status_code == 201, r.text
    truoc = {k: len(await _jobs(pool, workspace_re, k)) for k in ("kb_index", "kb_thumb", "kb_enrich")}

    r = await client_re.post(
        "/api/v1/projects/tv8/units", json={"zoneCode": "z1", "unitCode": "A-01", "productType": "chung_cu"}
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = await client_re.patch(f"/api/v1/projects/tv8/units/{uid}", json={"priceVnd": 5_000_000_000})
    assert r.status_code == 200, r.text

    sau = {k: len(await _jobs(pool, workspace_re, k)) for k in ("kb_index", "kb_thumb", "kb_enrich")}
    assert sau == truoc, f"căn hộ sinh việc: {truoc} → {sau}"


# ─── tài liệu ────────────────────────────────────────────────────────────────


async def test_tai_lieu_khong_tep_nap_thang(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tv9")
    r = await client_re.post(
        "/api/v1/projects/tv9/documents", json={"title": "Ghi chú", "loai": "khac", "body": "nội dung gõ tay"}
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    nap = await _jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "documents" and j.get("record_id") == did for j in nap)
    boc = await _jobs(pool, workspace_re, "kb_enrich")
    assert not any(j.get("record_id") == did for j in boc), "tài liệu gõ tay không có gì để bóc"


async def test_tai_lieu_co_tep_mo_chuoi_bang_thumb(client_re, workspace_re, pool):
    """thumb → bóc chữ → nạp, nối tuần tự. Đặt song song thì nạp có thể chạy trước và
    point mang cả khoá thumb rỗng lẫn nội dung rỗng."""
    await _tao_du_an(client_re, "tv10")
    r = await client_re.post(
        "/api/v1/projects/tv10/documents", json={"title": "CSBH", "loai": "csbh", "fileUrl": "tv10/a.pdf"}
    )
    did = r.json()["id"]

    thumb = await _jobs(pool, workspace_re, "kb_thumb")
    khop = [j for j in thumb if j.get("record_id") == did and j.get("entity") == "documents"]
    assert khop, "tài liệu có tệp mà không mở chuỗi"
    assert khop[0].get("project_code") == "tv10", "thiếu mã dự án thì việc nối sau không biết dự án nào"
    assert not await _jobs(pool, workspace_re, "kb_enrich"), "bóc chữ phải do việc thumb nối sang"


async def test_autoApprove_di_vao_payload_viec(client_re, workspace_re, pool):
    """D22 — cờ tường minh, không suy từ danh tính người gọi."""
    await _tao_du_an(client_re, "tv11")
    r = await client_re.post(
        "/api/v1/projects/tv11/documents",
        json={"title": "CSBH", "loai": "csbh", "fileUrl": "tv11/a.pdf", "autoApprove": True},
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    thumb = await _jobs(pool, workspace_re, "kb_thumb")
    khop = [j for j in thumb if j.get("record_id") == did]
    assert khop and khop[0].get("tu_duyet") is True, "cờ phải đi hết chuỗi tới chặng bóc chữ"


async def test_autoApprove_mac_dinh_tat(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tv12")
    r = await client_re.post(
        "/api/v1/projects/tv12/documents", json={"title": "CSBH", "loai": "csbh", "fileUrl": "tv12/a.pdf"}
    )
    did = r.json()["id"]

    thumb = await _jobs(pool, workspace_re, "kb_thumb")
    khop = [j for j in thumb if j.get("record_id") == did]
    assert khop and not khop[0].get("tu_duyet")


async def test_autoApprove_khong_di_xuong_DB(client_re, workspace_re):
    """Nó là ý định của lời gọi, không phải cột — lọt xuống `_upsert` là 500."""
    await _tao_du_an(client_re, "tv13")
    r = await client_re.post(
        "/api/v1/projects/tv13/documents", json={"title": "X", "loai": "khac", "body": "y", "autoApprove": True}
    )
    assert r.status_code == 201, r.text
    assert "autoApprove" not in r.json()


# ─── duyệt ───────────────────────────────────────────────────────────────────


async def test_duyet_tat_co_va_dat_viec_nap(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tv14")
    r = await client_re.post("/api/v1/projects/tv14/documents", json={"title": "X", "loai": "csbh", "body": "y"})
    did = r.json()["id"]
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET body_cho_duyet = true "
            "WHERE tenant_id = portal.current_tenant() AND id = $1",
            did,
        )

    r = await client_re.post(f"/api/v1/projects/tv14/documents/{did}/approve")
    assert r.status_code == 202, r.text
    assert r.json() == {"approved": True}

    r = await client_re.get(f"/api/v1/projects/tv14/documents/{did}")
    assert r.json()["bodyChoDuyet"] is False

    nap = await _jobs(pool, workspace_re, "kb_index")
    assert any(j.get("record_id") == did and j.get("entity") == "documents" for j in nap)


async def test_duyet_hang_khong_mang_co_thi_khong_dat_viec(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tv15")
    r = await client_re.post("/api/v1/projects/tv15/documents", json={"title": "X", "loai": "csbh", "body": "y"})
    did = r.json()["id"]
    truoc = len(await _jobs(pool, workspace_re, "kb_index"))

    r = await client_re.post(f"/api/v1/projects/tv15/documents/{did}/approve")
    assert r.status_code == 202
    assert r.json() == {"approved": False}
    assert len(await _jobs(pool, workspace_re, "kb_index")) == truoc


async def test_sua_tay_noi_dung_cung_la_duyet(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "tv16")
    r = await client_re.post("/api/v1/projects/tv16/documents", json={"title": "X", "loai": "csbh", "body": "y"})
    did = r.json()["id"]
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE tenant_data.documents SET body_cho_duyet = true "
            "WHERE tenant_id = portal.current_tenant() AND id = $1",
            did,
        )

    r = await client_re.patch(f"/api/v1/projects/tv16/documents/{did}", json={"body": "tôi sửa lại"})
    assert r.status_code == 200, r.text
    assert r.json()["bodyChoDuyet"] is False


async def test_duyet_tai_lieu_cua_du_an_khac_thi_404(client_re, workspace_re):
    await _tao_du_an(client_re, "tv17")
    await _tao_du_an(client_re, "tv18")
    r = await client_re.post("/api/v1/projects/tv17/documents", json={"title": "X", "loai": "khac", "body": "y"})
    did = r.json()["id"]

    r = await client_re.post(f"/api/v1/projects/tv18/documents/{did}/approve")
    assert r.status_code == 404


# ─── gộp ─────────────────────────────────────────────────────────────────────


async def test_luu_hai_lan_lien_tiep_chi_mot_viec_cho(client_re, workspace_re, pool):
    """Worker chạy một việc một lúc nên hàng đợi thường có tồn — không gộp thì mỗi cú
    gõ trong form là một lượt embed."""
    await _tao_du_an(client_re, "tv19")
    truoc = len(await _jobs(pool, workspace_re, "kb_index"))

    for i in range(3):
        r = await client_re.patch("/api/v1/projects/tv19", json={"overview": f"lần {i}"})
        assert r.status_code == 200, r.text

    sau = len(await _jobs(pool, workspace_re, "kb_index"))
    assert sau == truoc, f"ba lần Lưu liên tiếp xếp {sau - truoc} việc, phải gộp hết vào việc đang chờ"


async def test_luu_sau_khi_viec_da_chay_thi_xep_viec_moi(client_re, workspace_re, pool):
    """Việc `running` đọc bản CŨ, nên lần Lưu này phải có việc riêng."""
    await _tao_du_an(client_re, "tv20")
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE control.jobs SET state = 'running' WHERE tenant_id = portal.current_tenant() AND kind = 'kb_index'"
        )
    truoc = len(await _jobs(pool, workspace_re, "kb_index"))

    r = await client_re.patch("/api/v1/projects/tv20", json={"overview": "sửa sau khi worker đã nhặt"})
    assert r.status_code == 200, r.text

    assert len(await _jobs(pool, workspace_re, "kb_index")) == truoc + 1
