"""`GET /projects/kb-status` — nguồn duy nhất của chỉ báo trên trang danh sách.

HAI CỜ + HAI SỐ (2026-08-25). Quyết định "không có số" viết cho thời nhập tay vài bản
ghi; nay cổng nạp đổ vào hàng trăm ảnh một lượt và một dòng chữ không phân biệt được
"chậm" với "kẹt". `total = 0` nghĩa là dự án chưa có gì để nạp.

Lệch chỉ thành LỖI khi KHÔNG còn việc nào đang chờ — lúc đó nó là dấu hiệu một việc bị
mất, chứ không phải khoảnh khắc bình thường giữa lúc Lưu và lúc worker chạy tới.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.contracts import IndexResult
from portal.modules.kb.state import repo as kb_repo
from portal.modules.realestate import repo

pytestmark = pytest.mark.integration


def _cua(ds: list[dict], code: str) -> dict | None:
    return next((m for m in ds if m["projectCode"] == code), None)


async def _tao_du_an(client, code: str, *, status: str = "published", pool=None, tenant=None) -> None:
    """Tạo dự án rồi bật `published` bằng SQL — PATCH lên published đòi đủ completeness."""
    r = await client.post("/api/v1/projects", json={"projectCode": code, "name": f"Dự án {code}"})
    assert r.status_code == 201, r.text
    if status == "published":
        assert pool is not None and tenant is not None, "cần pool+tenant để bật published"
        async with tenant_conn(pool, tenant) as conn:
            await conn.execute(
                "UPDATE tenant_data.projects SET status = 'published' "
                "WHERE tenant_id = portal.current_tenant() AND project_code = $1",
                code,
            )


async def _don_viec(pool, tenant: str) -> None:
    """Tạo dự án qua API đã tự đặt việc nạp — xoá đi để đo riêng nhánh muốn đo."""
    async with tenant_conn(pool, tenant) as conn:
        await conn.execute("DELETE FROM control.jobs WHERE tenant_id = portal.current_tenant()")


async def _ghi_so(pool, tenant: str, code: str, **kw) -> int:
    async with tenant_conn(pool, tenant) as conn:
        pid = await conn.fetchval(
            "SELECT id FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = $1",
            code,
        )
        await kb_repo.save_state(conn, entity="projects", record_id=pid, doc_type="tong_quan", project_code=code, **kw)
    return int(pid)


async def test_du_an_vua_tao_thi_dang_nap(client_re, workspace_re, pool):
    """Tạo dự án tự đặt việc nạp (D01) ⇒ chỉ báo phải quay ngay, không đợi ai bấm."""
    await _tao_du_an(client_re, "kbs1", status="draft")
    r = await client_re.get("/api/v1/projects/kb-status")
    assert r.status_code == 200

    m = _cua(r.json(), "kbs1")
    assert m is not None
    assert m["indexing"] is True
    assert m["hasError"] is False, "việc đang chờ mà đã báo lỗi"


async def test_nap_xong_thi_im_lang(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "kbs3", pool=pool, tenant=workspace_re)
    await _ghi_so(
        pool,
        workspace_re,
        "kbs3",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    await _don_viec(pool, workspace_re)

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs3")
    assert (m["indexing"], m["hasError"]) == (False, False)


async def test_lech_ma_khong_con_viec_nao_thi_bao_loi(client_re, workspace_re, pool):
    """Đây là ca "một việc bị mất": nội dung đổi sau lần nạp cuối mà hàng đợi rỗng."""
    await _tao_du_an(client_re, "kbs4", pool=pool, tenant=workspace_re)
    await _ghi_so(
        pool,
        workspace_re,
        "kbs4",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE tenant_data.projects SET overview = 'nội dung mới', updated_at = now() "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'kbs4'"
        )
    await _don_viec(pool, workspace_re)

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs4")
    assert m["hasError"] is True


async def test_lech_ma_viec_dang_cho_thi_KHONG_bao_loi(client_re, workspace_re, pool):
    """Khoảnh khắc giữa lúc Lưu và lúc worker chạy tới là bình thường, không phải lỗi.
    Không có mệnh đề này thì mọi cú Lưu nháy đỏ một nhịp trước khi về im lặng."""
    await _tao_du_an(client_re, "kbs9", pool=pool, tenant=workspace_re)
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE tenant_data.projects SET overview = 'x', updated_at = now() "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'kbs9'"
        )

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs9")
    assert (m["indexing"], m["hasError"]) == (True, False)


async def test_skipped_van_tinh_la_da_nap(client_re, workspace_re, pool):
    """Điều kiện để chỉ báo tắt sau lần nạp đầu — xem repo.mark_skipped."""
    await _tao_du_an(client_re, "kbs5", pool=pool, tenant=workspace_re)
    pid = await _ghi_so(
        pool,
        workspace_re,
        "kbs5",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    async with tenant_conn(pool, workspace_re) as conn:
        await kb_repo.mark_skipped(conn, entity="projects", record_id=pid, doc_type="tong_quan")
    await _don_viec(pool, workspace_re)

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs5")
    assert (m["indexing"], m["hasError"]) == (False, False)


async def test_moi_danh_muc_anh_nhan_duoc_deu_nam_trong_pham_vi_nap(client_re, workspace_re, pool):
    """Đếm một ảnh KHÔNG BAO GIỜ được nạp là lệch thì chỉ báo lỗi VĨNH VIỄN — đo trên dev
    2026-08-14: 34/38 mục vàng là `csbh`. Sau `0927` CHECK khớp đúng `media_visual`."""
    from portal.modules.kb.contracts import MEDIA_VISUAL_REAL_ESTATE

    async with tenant_conn(pool, workspace_re) as conn:
        dinh_nghia = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'media_category_hop_le'"
        )
    for cat in MEDIA_VISUAL_REAL_ESTATE:
        assert f"'{cat}'" in dinh_nghia, f"{cat} được nạp nhưng CHECK không cho phép"
    assert dinh_nghia.count("'") // 2 == len(MEDIA_VISUAL_REAL_ESTATE), (
        f"CHECK cho phép danh mục ngoài phạm vi nạp: {dinh_nghia}"
    )


async def test_dong_loi_trong_so_thi_bao_loi(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "kbs6", pool=pool, tenant=workspace_re)
    await _ghi_so(pool, workspace_re, "kbs6", target="documents", state="error", error="embed 500")

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs6")
    assert m["hasError"] is True


async def test_viec_that_bai_thi_bao_loi(client_re, workspace_re, pool):
    """Việc hết lượt thử lại có thể chết TRƯỚC khi ghi được dòng sổ nào — nhìn mỗi sổ
    thì ca đó im lặng."""
    await _tao_du_an(client_re, "kbs10", pool=pool, tenant=workspace_re)
    await _don_viec(pool, workspace_re)
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload, state) "
            "VALUES (portal.current_tenant(), 'kb_thumb', 'test', $1::jsonb, 'failed')",
            '{"project_code": "kbs10", "entity": "media", "record_id": 1}',
        )

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs10")
    assert m["hasError"] is True


async def test_viec_dang_cho_thi_dang_nap(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "kbs7", pool=pool, tenant=workspace_re)
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload) "
            "VALUES (portal.current_tenant(), 'kb_index', 'test', $1::jsonb)",
            '{"project_code": "kbs7", "entity": "projects", "record_id": 1}',
        )

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs7")
    assert m["indexing"] is True


async def test_hinh_dang_response_dung_bon_truong(client_re, workspace_re):
    """Cổng cũ cấm mọi con số. Đợt 2026-08-25 đảo đúng quyết định đó, nên cổng nay chốt
    tập trường: thêm nữa là bắt người dùng diễn giải, bớt đi là FE không vẽ được thanh."""
    await _tao_du_an(client_re, "kbs8", status="draft")
    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs8")
    assert set(m) == {"projectCode", "indexing", "hasError", "total", "done"}


async def test_tong_dem_moi_muc_cua_du_an(client_re, workspace_re, pool):
    """Dự án trần đã là MỘT mục: hàng `projects` chính là doc tổng quan của agent."""
    await _tao_du_an(client_re, "kbs9", status="draft")
    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs9")
    assert m["total"] == 1
    assert m["done"] == 0, "chưa nạp gì mà đã tính là xong"


async def test_nap_xong_thi_done_bang_tong(client_re, workspace_re, pool):
    await _tao_du_an(client_re, "kbs10", pool=pool, tenant=workspace_re)
    await _ghi_so(
        pool,
        workspace_re,
        "kbs10",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    await _don_viec(pool, workspace_re)

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs10")
    assert m["done"] == m["total"] and m["total"] > 0


async def test_done_khong_bao_gio_am(client_re, workspace_re, pool):
    """`lech` đếm cả mục chưa có dòng sổ, nên trên dữ liệu drift nó vượt được `tong` —
    số âm ở đây làm FE vẽ thanh ngược."""
    await _tao_du_an(client_re, "kbs11", status="draft")
    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs11")
    assert m["done"] >= 0


async def test_khong_bi_route_doc_du_an_an_mat(client_re, workspace_re):
    """`GET /projects/{project_code}` khớp mọi chuỗi — kb-status phải đăng ký TRƯỚC nó."""
    r = await client_re.get("/api/v1/projects/kb-status")
    assert r.status_code == 200, "rơi vào doc_du_an nghĩa là thứ tự route sai"
    assert isinstance(r.json(), list)


async def test_khong_thay_du_an_cua_tenant_khac(client_re, workspace_re, pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('kbs_khac', 'Khác', 'u_seed_test')"
        )
    try:
        async with tenant_conn(pool, "kbs_khac") as conn:
            await conn.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
                "VALUES (portal.current_tenant(),'bimat','Dự án tenant khác','published')"
            )
        r = await client_re.get("/api/v1/projects/kb-status")
        assert _cua(r.json(), "bimat") is None
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM control.tenants WHERE id = 'kbs_khac'")


async def test_repo_project_status_mang_vi_tu_tenant(conn_re):
    """Gọi trực tiếp repo: câu SQL phải chạy được trong tenant_conn và chỉ trả tenant đó."""
    rows = await repo.project_status(conn_re)
    assert isinstance(rows, list)


async def test_viec_that_bai_HET_tinh_khi_lan_sau_cua_dung_ban_ghi_do_da_xong(client_re, workspace_re, pool):
    """Không có luật này thì badge đỏ VĨNH VIỄN: không gì dọn hàng `failed`, nên một dự án
    từng hỏng (embed chết) vẫn đỏ sau khi nạp lại thành công, và nút Thử lại không bao giờ
    làm nó xanh được (đo trên dev 2026-08-17)."""
    await _tao_du_an(client_re, "kbs11", pool=pool, tenant=workspace_re)
    await _ghi_so(
        pool,
        workspace_re,
        "kbs11",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    await _don_viec(pool, workspace_re)
    hong = '{"project_code": "kbs11", "entity": "media", "record_id": 7}'
    cau = (
        "INSERT INTO control.jobs (tenant_id, kind, actor, payload, state) "
        "VALUES (portal.current_tenant(), 'kb_index', 'test', $1::jsonb, $2)"
    )
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(cau, hong, "failed")

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs11")
    assert m["hasError"] is True, "vừa hỏng thì phải đỏ"

    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(cau, hong, "success")

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs11")
    assert m["hasError"] is False, "lượt sau của đúng bản ghi đó đã xong ⇒ lỗi cũ hết hiệu lực"


async def test_lan_sau_cua_BAN_GHI_KHAC_khong_xoa_duoc_loi(client_re, workspace_re, pool):
    """Một ảnh nạp xong không nói gì về tài liệu đang hỏng — nếu không ghim theo bản ghi
    thì job `kb_sync_project` thành công sẽ che mọi lỗi con của chính nó."""
    await _tao_du_an(client_re, "kbs12", pool=pool, tenant=workspace_re)
    await _don_viec(pool, workspace_re)
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload, state) "
            "VALUES (portal.current_tenant(), 'kb_index', 'test', $1::jsonb, 'failed')",
            '{"project_code": "kbs12", "entity": "documents", "record_id": 3}',
        )
        await conn.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload, state) "
            "VALUES (portal.current_tenant(), 'kb_index', 'test', $1::jsonb, 'success')",
            '{"project_code": "kbs12", "entity": "media", "record_id": 9}',
        )

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbs12")
    assert m["hasError"] is True


async def _tao_phan_khu(pool, tenant: str, code: str, zone_code: str = "PK1") -> None:
    async with tenant_conn(pool, tenant) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.zones (tenant_id, project_code, zone_code, name, status) "
            "VALUES (portal.current_tenant(), $1, $2, 'Phân khu 1', 'published')",
            code,
            zone_code,
        )


async def test_phan_khu_khong_co_dong_so_rieng_van_im_lang(client_re, workspace_re, pool):
    """Từ 2026-08-19 phân khu không còn doc riêng nên KHÔNG có dòng sổ `zones` nào.

    Đo trên dev: đòi nó có dòng riêng làm 13/13 dự án của `aina_test` đỏ vĩnh viễn, và
    nút Thử lại không sửa được vì nạp lại cũng chẳng sinh ra dòng đó.
    """
    await _tao_du_an(client_re, "kbz1", pool=pool, tenant=workspace_re)
    await _tao_phan_khu(pool, workspace_re, "kbz1")
    await _ghi_so(
        pool,
        workspace_re,
        "kbz1",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    await _don_viec(pool, workspace_re)

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbz1")
    assert (m["indexing"], m["hasError"]) == (False, False)


async def test_phan_khu_sua_sau_lan_nap_thi_bao_loi(client_re, workspace_re, pool):
    """Nội dung phân khu nằm TRONG doc dự án, nên mốc so của nó là lần nạp của dự án."""
    await _tao_du_an(client_re, "kbz2", pool=pool, tenant=workspace_re)
    await _tao_phan_khu(pool, workspace_re, "kbz2")
    await _ghi_so(
        pool,
        workspace_re,
        "kbz2",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "UPDATE tenant_data.zones SET overview = 'sửa sau', updated_at = now() "
            "WHERE tenant_id = portal.current_tenant() AND project_code = 'kbz2'"
        )
    await _don_viec(pool, workspace_re)

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbz2")
    assert m["hasError"] is True


@pytest.mark.parametrize("state", ["queued", "running", "failed"])
async def test_viec_ho_so_web_khong_bat_chi_bao_nap(client_re, workspace_re, pool, state):
    """Hồ sơ web công khai (kb/web) không phải việc nạp tri thức của tenant — kind của nó không được
    lọt vào bộ lọc `kb\\_%` của chỉ báo, không thì mỗi lần publish dự án quay "đang nạp" hàng giờ."""
    from portal.modules.kb.web.contracts import KIND_PROJECT, MODE_INIT

    await _tao_du_an(client_re, "kbw1", pool=pool, tenant=workspace_re)
    await _ghi_so(
        pool,
        workspace_re,
        "kbw1",
        target="documents",
        state="indexed",
        result=IndexResult(points_upserted=1, content_hash="h"),
    )
    await _don_viec(pool, workspace_re)
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO control.jobs (tenant_id, kind, actor, payload, state) "
            "VALUES (portal.current_tenant(), $1, 'test', $2::jsonb, $3)",
            KIND_PROJECT,
            f'{{"project_code": "kbw1", "mode": "{MODE_INIT}"}}',
            state,
        )

    m = _cua((await client_re.get("/api/v1/projects/kb-status")).json(), "kbw1")
    assert (m["indexing"], m["hasError"]) == (False, False)
