"""Tiền tố loại ghép/tách ở biên HTTP — spec 2026-08-10 §4.2, §6.

Frontend KHÔNG được thấy tiền tố: nếu nó tự ghép thì bảng tiền tố có bản sao ở
repo kia, không cổng nào so hai bên, và một chữ lệch làm mọi tài liệu mới rơi về
`khac` — im lặng.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _tao_du_an(client: httpx.AsyncClient, project_code: str) -> None:
    r = await client.post(_url("/projects"), json={"projectCode": project_code, "name": f"Dự án {project_code}"})
    assert r.status_code == 201, r.text


async def test_tao_tai_lieu_ghep_tien_to_vao_title(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "DOC1")
    r = await client_re.post(
        _url("/projects/DOC1/documents"),
        json={"title": "Bảng giá đợt 3", "loai": "csbh", "status": "published"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["loai"] == "csbh"
    assert r.json()["title"] == "Bảng giá đợt 3", "API trả phần đuôi, không trả tiền tố"


async def test_title_trong_db_mang_tien_to(client_re: httpx.AsyncClient, conn_re):
    await _tao_du_an(client_re, "DOC2")
    tao = await client_re.post(_url("/projects/DOC2/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    title = await conn_re.fetchval("SELECT title FROM tenant_data.documents WHERE id = $1", doc_id)
    assert title == "Pháp lý — Sổ đỏ", "loại phải nằm trong title vì documents không có cột phân loại"


async def test_doc_lai_thi_tach_dung_loai(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "DOC3")
    tao = await client_re.post(_url("/projects/DOC3/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    r = await client_re.get(_url(f"/projects/DOC3/documents/{doc_id}"))
    assert (r.json()["loai"], r.json()["title"]) == ("phap_ly", "Sổ đỏ")


async def test_khong_gui_loai_thi_la_khac_va_title_giu_nguyen(client_re: httpx.AsyncClient):
    """`Quy trình — bước 2` có dấu ngăn cách nhưng tiền tố lạ: cắt nó đi là âm thầm
    đổi tên tài liệu của người dùng."""
    await _tao_du_an(client_re, "DOC4")
    r = await client_re.post(_url("/projects/DOC4/documents"), json={"title": "Quy trình — bước 2"})
    assert r.status_code == 201, r.text
    assert (r.json()["loai"], r.json()["title"]) == ("khac", "Quy trình — bước 2")


async def test_loai_ngoai_bon_gia_tri_bi_chan_o_bien(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "DOC5")
    r = await client_re.post(_url("/projects/DOC5/documents"), json={"title": "x", "loai": "tong_quan"})
    assert r.status_code == 422, "tong_quan trùng doc_type của projects — phải chặn ở biên"


async def test_patch_gui_ca_hai_thi_ca_hai_doi_dung(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "DOC6")
    tao = await client_re.post(_url("/projects/DOC6/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    r = await client_re.patch(_url(f"/projects/DOC6/documents/{doc_id}"), json={"title": "Sổ đỏ 2", "loai": "csbh"})
    assert r.status_code == 200, r.text
    assert (r.json()["loai"], r.json()["title"]) == ("csbh", "Sổ đỏ 2")


async def test_patch_gui_moi_title_thi_giu_nguyen_loai_cu(client_re: httpx.AsyncClient, conn_re):
    """Phát hiện Critical: PATCH chỉ gửi `title` từng làm `loai` tụt về `khac`."""
    await _tao_du_an(client_re, "DOC7")
    tao = await client_re.post(_url("/projects/DOC7/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    r = await client_re.patch(_url(f"/projects/DOC7/documents/{doc_id}"), json={"title": "Sổ đỏ 2"})
    assert r.status_code == 200, r.text
    assert (r.json()["loai"], r.json()["title"]) == ("phap_ly", "Sổ đỏ 2")
    title = await conn_re.fetchval("SELECT title FROM tenant_data.documents WHERE id = $1", doc_id)
    assert title == "Pháp lý — Sổ đỏ 2", "title trong DB phải còn tiền tố phân loại"


async def test_patch_gui_moi_loai_thi_giu_nguyen_phan_duoi_title(client_re: httpx.AsyncClient, conn_re):
    await _tao_du_an(client_re, "DOC8")
    tao = await client_re.post(_url("/projects/DOC8/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    r = await client_re.patch(_url(f"/projects/DOC8/documents/{doc_id}"), json={"loai": "csbh"})
    assert r.status_code == 200, r.text
    assert (r.json()["loai"], r.json()["title"]) == ("csbh", "Sổ đỏ")
    title = await conn_re.fetchval("SELECT title FROM tenant_data.documents WHERE id = $1", doc_id)
    assert title == "CSBH — Sổ đỏ"


async def test_doi_loai_thi_enqueue_xoa_point_loai_cu(client_re: httpx.AsyncClient, conn_re, workspace_re):
    """Point id đổi theo doc_type, mà reconcile so theo record_id nên nó KHÔNG bắt
    được point mồ côi này — phải xoá tường minh (§4.4)."""
    import json

    await _tao_du_an(client_re, "DOC10")
    tao = await client_re.post(_url("/projects/DOC10/documents"), json={"title": "Bảng giá", "loai": "csbh"})
    doc_id = tao.json()["id"]

    r = await client_re.patch(
        _url(f"/projects/DOC10/documents/{doc_id}"),
        json={"title": "Bảng giá", "loai": "phap_ly"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["loai"] == "phap_ly"

    rows = await conn_re.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete' ORDER BY id DESC",
        workspace_re,
    )
    assert rows, "đổi loại phải để lại một job kb_delete"
    # core/jobs.enqueue lưu payload bằng json.dumps nên đọc ra là chuỗi.
    payload = json.loads(rows[0]["payload"])
    assert payload["entity"] == "documents"
    assert payload["record_id"] == doc_id
    assert payload["doc_type"] == "csbh", "phải là loại CŨ — loại mới vẫn đang cần point"


async def test_doi_loai_CHI_xoa_point_cu_khong_tu_nap_lai(client_re: httpx.AsyncClient, conn_re, workspace_re):
    """Đổi loại sinh point-id MỚI (`uuid5(doc_type:record_id:idx)`) nên point cũ phải bị
    xoá. Nhưng KHÔNG tự nạp lại: nạp là việc người dùng bấm (nút "Nạp kiến thức cho
    agent"), và badge sẽ báo dự án này lệch cho tới lúc đó.

    Bản trước của route tự xếp cả job nạp — đường tự lan duy nhất còn lại — và nó đã bỏ
    khi bỏ mọi luồng auto ghi Qdrant.
    """
    import json

    await _tao_du_an(client_re, "DOC12")
    tao = await client_re.post(_url("/projects/DOC12/documents"), json={"title": "Bảng giá", "loai": "khac"})
    doc_id = tao.json()["id"]
    truoc_nap = await conn_re.fetchval(
        "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", workspace_re
    )

    r = await client_re.patch(_url(f"/projects/DOC12/documents/{doc_id}"), json={"loai": "csbh"})
    assert r.status_code == 200, r.text

    sau_nap = await conn_re.fetchval(
        "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", workspace_re
    )
    assert sau_nap == truoc_nap, "đổi loại vẫn tự xếp job nạp — luồng auto phải bỏ"

    rows = await conn_re.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete' ORDER BY id DESC",
        workspace_re,
    )
    assert rows, "đổi loại phải xoá point của loại CŨ"
    payload = json.loads(rows[0]["payload"])
    assert payload["entity"] == "documents"
    assert payload["record_id"] == doc_id
    assert payload["doc_type"] == "khac", "job xoá phải mang loại CŨ, không phải loại mới"


async def test_sua_duoi_tieu_de_KHONG_enqueue_xoa(client_re: httpx.AsyncClient, conn_re, workspace_re):
    """Đổi tên tài liệu mà giữ loại thì point id không đổi — xoá là mất point đang đúng."""
    await _tao_du_an(client_re, "DOC11")
    tao = await client_re.post(_url("/projects/DOC11/documents"), json={"title": "Bảng giá", "loai": "csbh"})
    doc_id = tao.json()["id"]
    truoc = await conn_re.fetchval(
        "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete'", workspace_re
    )

    await client_re.patch(
        _url(f"/projects/DOC11/documents/{doc_id}"),
        json={"title": "Bảng giá đợt 4", "loai": "csbh"},
    )

    sau = await conn_re.fetchval(
        "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_delete'", workspace_re
    )
    assert sau == truoc


async def test_patch_khong_gui_ca_hai_thi_khong_doi_gi(client_re: httpx.AsyncClient):
    """Phát hiện Important: PATCH thiếu cả `title` lẫn `loai` từng là no-op câm lặng
    (payload rỗng, 200 OK nhưng cũng không nên đổi loại/title — kiểm bằng cách
    PATCH trường khác và xác nhận loại/title vẫn nguyên)."""
    await _tao_du_an(client_re, "DOC9")
    tao = await client_re.post(_url("/projects/DOC9/documents"), json={"title": "Sổ đỏ", "loai": "phap_ly"})
    doc_id = tao.json()["id"]
    r = await client_re.patch(_url(f"/projects/DOC9/documents/{doc_id}"), json={"body": "Nội dung mới"})
    assert r.status_code == 200, r.text
    assert (r.json()["loai"], r.json()["title"]) == ("phap_ly", "Sổ đỏ")
