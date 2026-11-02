"""Bốn endpoint đồng bộ tri thức + enqueue `kb_enrich` sau upload (Task 12).

Quyền dùng lại `catalog.*` — không thêm action nào (luật 4 + PQ_01). Test 403-thiếu-quyền
KHÔNG lặp lại ở đây: `tests/unit/test_loi_thieu_quyen.py` đã canh cổng đó, và fixture
`client_khong_quyen` mà brief gốc giả định không tồn tại trong repo.
"""

from datetime import timedelta

from portal.core.db.session import tenant_conn


async def _insert_project(conn, tenant_id: str, project_code: str, name: str = "Dự án test"):
    return await conn.fetchrow(
        "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
        "VALUES ($1, $2, $3, 'published') RETURNING id, updated_at",
        tenant_id,
        project_code,
        name,
    )


async def test_post_media_xep_job_thumb_khong_goi_model(client_cfg, workspace_cfg, pool):
    async with tenant_conn(pool, workspace_cfg) as conn:
        await _insert_project(conn, workspace_cfg, "nplb")

    r = await client_cfg.post(
        "/api/v1/projects/nplb/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://cdn.test/a.jpg"},
    )
    assert r.status_code == 201, r.text
    async with tenant_conn(pool, workspace_cfg) as conn:
        thumb = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_thumb'", workspace_cfg
        )
        enrich = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_enrich'", workspace_cfg
        )
    assert thumb == 1, "thêm ảnh mà không xếp job thumb thì ảnh không có bản nhỏ và không được nạp"
    # D11 — mô tả đã do người dùng đọc/sửa trong form trước khi bấm Thêm.
    assert enrich == 0, "thêm ảnh vẫn gọi model tả lại sau khi lưu"


async def test_post_tai_lieu_co_file_url_xep_job_thumb_mo_dau_chuoi(client_cfg, workspace_cfg, pool):
    """Có `fileUrl` ⇒ chuỗi thumb → bóc chữ → nạp. Việc đầu chuỗi là thumb (ảnh preview
    trang 1), và mỗi việc tự đặt việc kế — nối tuần tự thay vì đặt song song."""
    async with tenant_conn(pool, workspace_cfg) as conn:
        await _insert_project(conn, workspace_cfg, "nplb")

    r = await client_cfg.post(
        "/api/v1/projects/nplb/documents",
        json={"title": "CSBH quý 3", "fileUrl": "tenants/cf_anphu/kb-bds/abc/csbh.pdf"},
    )
    assert r.status_code == 201, r.text
    async with tenant_conn(pool, workspace_cfg) as conn:
        thumb = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_thumb'", workspace_cfg
        )
        enrich = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_enrich'", workspace_cfg
        )
    assert thumb == 1, "tài liệu có tệp mà không mở chuỗi bằng việc thumb"
    assert enrich == 0, "bóc chữ phải do việc thumb nối sang, không đặt song song"


async def test_post_tai_lieu_nhap_tay_khong_xep_job_enrich(client_cfg, workspace_cfg, pool):
    """Không `fileUrl` — tài liệu nhập tay không có gì để bóc (điều 8 của đề bài)."""
    async with tenant_conn(pool, workspace_cfg) as conn:
        await _insert_project(conn, workspace_cfg, "nplb")

    r = await client_cfg.post(
        "/api/v1/projects/nplb/documents", json={"title": "Ghi chú nội bộ", "body": "nội dung nhập tay"}
    )
    assert r.status_code == 201, r.text
    async with tenant_conn(pool, workspace_cfg) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_enrich'", workspace_cfg
        )
    assert n == 0, "tài liệu nhập tay không có file để Docling bóc — enqueue là vô ích"


async def test_post_sync_kb_tra_202_va_mot_job(client_cfg, workspace_cfg, pool):
    r = await client_cfg.post("/api/v1/projects/nplb/sync-kb")
    assert r.status_code == 202
    assert "jobId" in r.json()
    async with tenant_conn(pool, workspace_cfg) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_sync_project'", workspace_cfg
        )
    assert n == 1, "router phải xếp ĐÚNG MỘT job mở màn, không xếp N job con"


async def test_get_kb_status_tra_du_khoa(client_cfg):
    r = await client_cfg.get("/api/v1/projects/kb-status")
    assert r.status_code == 200
    ds = r.json()
    khoa = {"projectCode", "state", "pending", "total", "staleCount", "errorCount", "lastSyncedAt"}
    assert all(khoa == set(x) for x in ds)


async def test_kb_status_phan_biet_theo_du_an(client_cfg, workspace_cfg, pool):
    """Bản trước JOIN `kb_index_state` chỉ bằng `tenant_id` (không theo dự án) — mọi dự
    án nhận cùng `max(indexed_at)` của cả tenant nên hai dự án lệch khác nhau vẫn báo
    giống nhau. Test này chứng minh hai dự án cho `state` KHÁC NHAU."""
    async with tenant_conn(pool, workspace_cfg) as conn:
        da_nap = await _insert_project(conn, workspace_cfg, "sync-ok", "Đã nạp")
        await conn.execute(
            "INSERT INTO tenant_data.kb_index_state "
            "       (tenant_id, entity, record_id, target, state, indexed_at, project_code) "
            "VALUES ($1, 'projects', $2, 'documents', 'indexed', $3, 'sync-ok')",
            workspace_cfg,
            da_nap["id"],
            da_nap["updated_at"] + timedelta(seconds=5),
        )
        # Dự án thứ hai CHƯA từng nạp — không hàng `kb_index_state` nào.
        await _insert_project(conn, workspace_cfg, "sync-lech", "Chưa nạp")

    r = await client_cfg.get("/api/v1/projects/kb-status")
    assert r.status_code == 200
    theo_ma = {x["projectCode"]: (x["indexing"], x["hasError"]) for x in r.json()}
    assert theo_ma["sync-ok"] == (False, False), "dự án đã nạp xong phải im lặng"
    assert theo_ma["sync-lech"] == (False, True), "dự án chưa nạp lần nào mà không có việc chờ là lỗi"


async def test_get_enrich_status_tra_trang_thai_job(client_cfg, workspace_cfg, pool):
    async with tenant_conn(pool, workspace_cfg) as conn:
        await _insert_project(conn, workspace_cfg, "nplb")

    r = await client_cfg.get("/api/v1/projects/nplb/enrich-status")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_get_enrich_status_khong_lan_job_cua_du_an_khac(client_cfg, workspace_cfg, pool):
    """Cổng cũ chỉ assert `isinstance(r.json(), list)` trên một list RỖNG.

    Mutation-test đã chứng minh nó không đo gì: thay hai mệnh đề `EXISTS` lọc theo dự án
    bằng `$3::text IS NOT NULL` thì cả 7 test của file vẫn xanh. Test này assert nội
    dung thật — job của dự án khác không được xuất hiện.
    """
    from portal.core.jobs import enqueue

    ids = {}
    async with tenant_conn(pool, workspace_cfg) as conn:
        for code in ("nplb", "du-an-khac"):
            await _insert_project(conn, workspace_cfg, code)
            ids[code] = await conn.fetchval(
                "INSERT INTO tenant_data.media "
                "       (tenant_id, project_code, content_type, category, media_url, status) "
                "VALUES ($1, $2, 'image', 'tong_quan', 'https://cdn.test/a.jpg', 'published') RETURNING id",
                workspace_cfg,
                code,
            )
            await enqueue(
                conn,
                tenant_id=workspace_cfg,
                kind="kb_enrich",
                actor="test",
                payload={"entity": "media", "record_id": ids[code]},
            )

    r = await client_cfg.get("/api/v1/projects/nplb/enrich-status")

    assert r.status_code == 200
    assert [x["recordId"] for x in r.json()] == [ids["nplb"]], "job của dự án khác lọt vào enrich-status"
