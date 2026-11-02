"""Test `router.py` — CRUD 5 thực thể qua HTTP thật (Task 4).

Khác `test_repo.py` (kiểm SQL của Task 3): file này kiểm HÌNH DẠNG API — đường
dẫn, mã lỗi HTTP, cascade path→id, hai luật UX (`project_code` kế thừa từ path,
luồng cover/map media một-giao-dịch), phân trang cursor (router tự dựng
`nextCursor` — repo không sinh), và cổng BR13 (mọi route ghi vào nhật ký).

Dùng `client_re`/`workspace_re` của `conftest.py` (Task 3) — MỘT workspace
(`rew`) thật, KHÔNG mock `tenant_conn()`.
"""

import asyncio

import asyncpg
import httpx
import pytest

from portal.core.db.session import tenant_conn
from portal.modules.realestate import repo

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _tao_du_an(client: httpx.AsyncClient, project_code: str, **kw) -> httpx.Response:
    body = {"projectCode": project_code, "name": kw.pop("name", f"Dự án {project_code}"), **kw}
    return await client.post(_url("/projects"), json=body)


async def _seed_sentinel(pool: asyncpg.Pool, tenant: str) -> None:
    """Dựng row `__ALL__` bằng SQL thô — KHÔNG qua `POST /projects`.

    Bản trước của các test dưới đây tạo sentinel bằng `POST /projects
    {"projectCode":"__ALL__"}`; đường đó giờ trả 409 (`SENTINEL_PROTECTED`, xem
    `router._sentinel_duoc_bao_ve` — chiếm được row hệ thống là Critical A của
    review vòng cuối). Đây LÀ cách provisioning thật tạo nó: `scripts/seed_bds.py`
    ghi thẳng SQL, không đi qua HTTP. `ON CONFLICT DO NOTHING` để gọi hai lần
    trong cùng một test không vỡ.
    """
    async with pool.acquire() as conn, conn.transaction():
        # FORCE RLS áp cả cho owner (migration `0003`) — cùng nếp `kb_tenant`
        # của `test_schema.py`: phải SET LOCAL trước khi ghi `tenant_data.*`.
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
        await conn.execute(
            """INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
               VALUES ($1, '__ALL__', 'Chung / toàn tenant', 'published')
               ON CONFLICT (tenant_id, project_code) DO NOTHING""",
            tenant,
        )


# ─── Dự án (`projects`) ─────────────────────────────────────────────────────


async def test_du_an_crud_qua_http(client_re: httpx.AsyncClient):
    tao = await _tao_du_an(client_re, "CRUD1", region="Hà Nội")
    assert tao.status_code == 201, tao.text
    than = tao.json()
    assert than["projectCode"] == "CRUD1"
    assert than["region"] == "Hà Nội"
    assert than["status"] == "draft"  # DEFAULT của DB, không gửi ở body
    assert "id" in than

    doc = await client_re.get(_url("/projects/CRUD1"))
    assert doc.status_code == 200, doc.text
    assert doc.json()["name"] == "Dự án CRUD1"

    sua = await client_re.patch(_url("/projects/CRUD1"), json={"region": "Hưng Yên"})
    assert sua.status_code == 200, sua.text
    assert sua.json()["region"] == "Hưng Yên"

    xoa = await client_re.delete(_url("/projects/CRUD1"))
    assert xoa.status_code == 204, xoa.text
    sau_xoa = await client_re.get(_url("/projects/CRUD1"))
    assert sau_xoa.status_code == 404


async def test_du_an_post_trung_ma_tra_409(client_re: httpx.AsyncClient):
    dau = await _tao_du_an(client_re, "DUP1")
    assert dau.status_code == 201, dau.text
    trung = await _tao_du_an(client_re, "DUP1", name="Bản khác")
    assert trung.status_code == 409, trung.text
    assert trung.json()["error"]["code"] == "DUPLICATE_CODE"


async def test_du_an_post_trung_ma_dua_that_dong_thoi(pool: asyncpg.Pool, workspace_re: str):
    """Finding của review vòng 2: `test_du_an_post_trung_ma_tra_409` ở trên gọi
    hai POST TUẦN TỰ — không canh được race THẬT giữa hai request cùng lúc.
    Dựng lại đúng probe của reviewer: hai `tenant_conn` SONG SONG, đồng bộ bằng
    `asyncio.Barrier(2)` để cả hai cùng chạm `INSERT` gần như đồng thời — xác
    nhận `ON CONFLICT DO NOTHING` (repo.py, Task 3) an toàn dưới tải đồng thời
    thật, không chỉ đúng khi gọi tuần tự (SELECT-rồi-UPSERT sẽ FAIL ở đúng bài
    test này: cả hai đều thấy "chưa có", cả hai đều ghi, một trong hai âm thầm
    ghi đè cái kia)."""
    rao = asyncio.Barrier(2)

    async def _thu(ten: str) -> str:
        async with tenant_conn(pool, workspace_re) as conn:
            await rao.wait()
            row = await repo.chen_du_an(conn, workspace_re, {"project_code": "RACE1", "name": ten})
            return "WIN" if row is not None else "LOSE"

    ket_qua = await asyncio.gather(_thu("A"), _thu("B"))
    assert sorted(ket_qua) == ["LOSE", "WIN"]

    hang = await pool.fetch(
        "SELECT name FROM tenant_data.projects WHERE tenant_id = $1 AND project_code = 'RACE1'", workspace_re
    )
    assert len(hang) == 1  # đúng 1 hàng — không ghi đè, không tạo trùng


async def test_du_an_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.get(_url("/projects/KHONG-CO"))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_du_an_patch_partial_khong_xoa_truong_khac(client_re: httpx.AsyncClient):
    """3 việc dễ sai (task-4-brief.md) — PATCH chỉ sửa field được gửi."""
    await _tao_du_an(client_re, "PATCH1", region="HN", investor="Chủ đầu tư A")
    sua = await client_re.patch(_url("/projects/PATCH1"), json={"region": "HCM"})
    assert sua.status_code == 200, sua.text
    than = sua.json()
    assert than["region"] == "HCM"
    assert than["investor"] == "Chủ đầu tư A"  # KHÔNG bị patch rỗng xoá mất


async def test_du_an_cover_map_media_mot_giao_dich(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    """Luật UX #2: upload cover/map → 1 row `media` mỗi ô + gán id ngược, trong
    CÙNG một request/giao dịch với việc ghi `projects`."""
    tao = await _tao_du_an(
        client_re,
        "COVER1",
        coverMedia={"mediaUrl": "https://x/cover.webp", "caption": "Ảnh cover"},
        mapMedia={"mediaUrl": "https://x/map.webp"},
    )
    assert tao.status_code == 201, tao.text
    than = tao.json()
    assert than["coverMediaId"] is not None
    assert than["mapMediaId"] is not None
    assert than["coverMediaId"] != than["mapMediaId"]

    hang = await pool.fetch(
        "SELECT id, category, media_url, caption, content_type FROM tenant_data.media "
        "WHERE tenant_id = $1 AND project_code = 'COVER1' ORDER BY id",
        workspace_re,
    )
    assert len(hang) == 2
    theo_id = {r["id"]: r for r in hang}
    cover_row = theo_id[than["coverMediaId"]]
    map_row = theo_id[than["mapMediaId"]]
    assert cover_row["category"] == "tong_quan"
    assert cover_row["media_url"] == "https://x/cover.webp"
    assert cover_row["caption"] == "Ảnh cover"
    assert cover_row["content_type"] == "image"  # default MediaUploadIn, không NULL vi phạm NOT NULL
    assert map_row["category"] == "mat_bang"
    assert map_row["media_url"] == "https://x/map.webp"


# ─── Phân khu (`zones`) ─────────────────────────────────────────────────────


async def test_phan_khu_crud_qua_http(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PZ1")
    tao = await client_re.post(_url("/projects/PZ1/zones"), json={"zoneCode": "Z1", "name": "Zone 1"})
    assert tao.status_code == 201, tao.text
    than = tao.json()
    assert than["projectCode"] == "PZ1"
    assert than["zoneCode"] == "Z1"

    doc = await client_re.get(_url("/projects/PZ1/zones/Z1"))
    assert doc.status_code == 200, doc.text

    sua = await client_re.patch(_url("/projects/PZ1/zones/Z1"), json={"name": "Zone 1 (sửa)"})
    assert sua.status_code == 200, sua.text
    assert sua.json()["name"] == "Zone 1 (sửa)"

    xoa = await client_re.delete(_url("/projects/PZ1/zones/Z1"))
    assert xoa.status_code == 204
    assert (await client_re.get(_url("/projects/PZ1/zones/Z1"))).status_code == 404


async def test_phan_khu_post_trung_ma_tra_409(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PZ2")
    dau = await client_re.post(_url("/projects/PZ2/zones"), json={"zoneCode": "Z1"})
    assert dau.status_code == 201, dau.text
    trung = await client_re.post(_url("/projects/PZ2/zones"), json={"zoneCode": "Z1"})
    assert trung.status_code == 409, trung.text


async def test_phan_khu_du_an_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.post(_url("/projects/KHONG-CO-PROJ/zones"), json={"zoneCode": "Z1"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_phan_khu_cover_map_gan_zone_code(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    await _tao_du_an(client_re, "PZ3")
    tao = await client_re.post(
        _url("/projects/PZ3/zones"),
        json={"zoneCode": "ZC", "coverMedia": {"mediaUrl": "https://x/z-cover.webp"}},
    )
    assert tao.status_code == 201, tao.text
    id_media = tao.json()["coverMediaId"]
    assert id_media is not None
    hang = await pool.fetchrow(
        "SELECT zone_code, category FROM tenant_data.media WHERE tenant_id = $1 AND id = $2", workspace_re, id_media
    )
    assert hang["zone_code"] == "ZC"
    assert hang["category"] == "tong_quan"


# ─── Căn (`units`) ──────────────────────────────────────────────────────────


async def test_can_crud_qua_http(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PU1")
    await client_re.post(_url("/projects/PU1/zones"), json={"zoneCode": "ZU1"})
    tao = await client_re.post(
        _url("/projects/PU1/units"),
        json={"zoneCode": "ZU1", "unitCode": "U1", "productType": "chung_cu", "priceVnd": 5620000000},
    )
    assert tao.status_code == 201, tao.text
    than = tao.json()
    id_ = than["id"]
    assert than["unitCode"] == "U1"

    doc = await client_re.get(_url(f"/projects/PU1/units/{id_}"))
    assert doc.status_code == 200, doc.text

    sua = await client_re.patch(_url(f"/projects/PU1/units/{id_}"), json={"floor": 6})
    assert sua.status_code == 200, sua.text
    assert sua.json()["floor"] == 6
    assert sua.json()["unitCode"] == "U1"  # PATCH partial — mã căn không bị đổi

    xoa = await client_re.delete(_url(f"/projects/PU1/units/{id_}"))
    assert xoa.status_code == 204
    assert (await client_re.get(_url(f"/projects/PU1/units/{id_}"))).status_code == 404


async def test_can_trung_ma_khong_phai_409_tao_hai_hang(client_re: httpx.AsyncClient):
    """`units.unit_code` KHÔNG unique (`02a §4.3`) — double-POST cùng mã tạo 2
    hàng khác `id`, không phải 409 (quyết định của repo.py, Task 3)."""
    await _tao_du_an(client_re, "PU2")
    await client_re.post(_url("/projects/PU2/zones"), json={"zoneCode": "ZU2"})
    body = {"zoneCode": "ZU2", "unitCode": "TRUNGMA", "productType": "chung_cu"}
    r1 = await client_re.post(_url("/projects/PU2/units"), json=body)
    r2 = await client_re.post(_url("/projects/PU2/units"), json=body)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


async def test_can_du_an_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.post(
        _url("/projects/KHONG-CO-PROJ/units"),
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_can_zone_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PU3")
    r = await client_re.post(
        _url("/projects/PU3/units"),
        json={"zoneCode": "KHONG-CO-ZONE", "unitCode": "U1", "productType": "chung_cu"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ZONE_NOT_FOUND"


# ─── Tài liệu (`documents`) ─────────────────────────────────────────────────


async def test_tai_lieu_crud_qua_http(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PD1")
    tao = await client_re.post(_url("/projects/PD1/documents"), json={"title": "CSBH Q3", "body": "nội dung"})
    assert tao.status_code == 201, tao.text
    id_ = tao.json()["id"]

    doc = await client_re.get(_url(f"/projects/PD1/documents/{id_}"))
    assert doc.status_code == 200 and doc.json()["body"] == "nội dung"

    sua = await client_re.patch(_url(f"/projects/PD1/documents/{id_}"), json={"body": "nội dung mới"})
    assert sua.status_code == 200 and sua.json()["body"] == "nội dung mới"
    assert sua.json()["title"] == "CSBH Q3"  # partial — title giữ nguyên

    xoa = await client_re.delete(_url(f"/projects/PD1/documents/{id_}"))
    assert xoa.status_code == 204
    assert (await client_re.get(_url(f"/projects/PD1/documents/{id_}"))).status_code == 404


async def test_tai_lieu_gop_ALL_di_qua_cung_route(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    """Tab `doc-shared` của form tới tài liệu chung tenant bằng CHÍNH route
    `/projects/{project_code}/documents`, `project_code = "__ALL__"` — không có
    route riêng."""
    # `__ALL__` là 1 row `projects` hệ thống do provisioning seed (`seed_bds.py`)
    # — KHÔNG tạo được qua HTTP nữa, xem `_seed_sentinel`.
    await _seed_sentinel(pool, workspace_re)

    tao = await client_re.post(_url("/projects/__ALL__/documents"), json={"title": "Giới thiệu công ty"})
    assert tao.status_code == 201, tao.text
    assert tao.json()["projectCode"] == "__ALL__"

    liet_ke = await client_re.get(_url("/projects/__ALL__/documents"))
    assert liet_ke.status_code == 200
    assert any(d["title"] == "Giới thiệu công ty" for d in liet_ke.json()["items"])


async def test_tai_lieu_du_an_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.post(_url("/projects/KHONG-CO-PROJ/documents"), json={"title": "X"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


# ─── Media (`media`) ────────────────────────────────────────────────────────


async def test_media_crud_qua_http(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PM1")
    tao = await client_re.post(
        _url("/projects/PM1/media"),
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/m1.webp"},
    )
    assert tao.status_code == 201, tao.text
    id_ = tao.json()["id"]

    doc = await client_re.get(_url(f"/projects/PM1/media/{id_}"))
    assert doc.status_code == 200 and doc.json()["mediaUrl"] == "https://x/m1.webp"

    sua = await client_re.patch(_url(f"/projects/PM1/media/{id_}"), json={"caption": "Ảnh mới"})
    assert sua.status_code == 200 and sua.json()["caption"] == "Ảnh mới"
    assert sua.json()["category"] == "tong_quan"  # partial — category giữ nguyên

    xoa = await client_re.delete(_url(f"/projects/PM1/media/{id_}"))
    assert xoa.status_code == 204
    assert (await client_re.get(_url(f"/projects/PM1/media/{id_}"))).status_code == 404


async def test_media_gop_ALL_di_qua_cung_route(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    await _seed_sentinel(pool, workspace_re)
    tao = await client_re.post(
        _url("/projects/__ALL__/media"),
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/chung.webp"},
    )
    assert tao.status_code == 201, tao.text
    assert tao.json()["projectCode"] == "__ALL__"


async def test_media_du_an_khong_ton_tai_tra_404(client_re: httpx.AsyncClient):
    r = await client_re.post(
        _url("/projects/KHONG-CO-PROJ/media"),
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/m.webp"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


# ─── Phân trang — router tự dựng `nextCursor` (repo KHÔNG sinh) ────────────


async def test_phan_trang_co_ban_khong_trung_khong_sot(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PP1")
    for i in range(5):
        r = await client_re.post(_url("/projects/PP1/zones"), json={"zoneCode": f"Z{i}"})
        assert r.status_code == 201, r.text

    trang1 = await client_re.get(_url("/projects/PP1/zones"), params={"limit": 2})
    d1 = trang1.json()
    assert len(d1["items"]) == 2
    assert d1["nextCursor"] is not None

    trang2 = await client_re.get(_url("/projects/PP1/zones"), params={"limit": 2, "cursor": d1["nextCursor"]})
    d2 = trang2.json()
    assert len(d2["items"]) == 2
    assert d2["nextCursor"] is not None

    trang3 = await client_re.get(_url("/projects/PP1/zones"), params={"limit": 2, "cursor": d2["nextCursor"]})
    d3 = trang3.json()
    assert len(d3["items"]) == 1
    assert d3["nextCursor"] is None

    ma = {it["id"] for it in (*d1["items"], *d2["items"], *d3["items"])}
    assert len(ma) == 5  # không trùng, không sót


async def test_phan_trang_con_tro_hong_tra_422(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "PP2")
    r = await client_re.get(_url("/projects/PP2/zones"), params={"cursor": "***khong-hop-le***"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def test_phan_trang_bien_limit_200(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    """task-4-brief.md mục (b), sửa lại theo review vòng 2 (Finding 3): `limit`
    giờ khai `Query(ge=1, le=GIOI_HAN_TRANG)` — `limit=200` được PHÉP trả ĐỦ
    200 hàng (khác bản trước, kẹp xuống 199 im lặng). Router vẫn tránh đúng
    bẫy kẹp-kép cũ (`repo._gioi_han` kẹp cứng ở 200) bằng cách xin `min(limit+1,
    GIOI_HAN_TRANG)` rồi suy "còn trang sau" từ `len(hang) >= xin` (bảo thủ ở
    đúng biên `limit==200`, xem docstring `_trang()` trong router.py).

    Test dựng ĐÚNG 201 hàng (nhiều hơn 200 đúng 1) và xin `limit=200`: trang
    đầu phải đủ 200 hàng (không phải 199) VÀ `nextCursor` phải khác None (còn
    1 hàng thật ở trang sau) — nếu router có lỗi kẹp-kép, trang đầu vẫn đủ 200
    hàng NHƯNG `nextCursor=None` SAI (mất đúng 1 hàng, không lỗi, không cảnh báo).
    """
    await _tao_du_an(client_re, "PP200")
    # Seed thẳng qua repo (bỏ qua HTTP) cho nhanh — 201 lần POST tuần tự sẽ chậm
    # không cần thiết; đối tượng đang test là GET phân trang, không phải POST.
    async with tenant_conn(pool, workspace_re) as conn:
        for i in range(201):
            z = await repo.chen_phan_khu(conn, workspace_re, {"project_code": "PP200", "zone_code": f"ZB{i:04d}"})
            assert z is not None

    trang1 = await client_re.get(_url("/projects/PP200/zones"), params={"limit": 200})
    d1 = trang1.json()
    assert len(d1["items"]) == 200, "limit=200 giờ phải trả ĐỦ 200 hàng (Finding 3 — không còn kẹp xuống 199)"
    assert d1["nextCursor"] is not None, "201 hàng, xin 200 — PHẢI còn trang sau (bẫy kẹp-kép limit=200)"

    trang2 = await client_re.get(_url("/projects/PP200/zones"), params={"limit": 200, "cursor": d1["nextCursor"]})
    d2 = trang2.json()
    assert len(d2["items"]) == 1  # 201 - 200 hàng còn lại
    assert d2["nextCursor"] is None

    ma = {it["id"] for it in (*d1["items"], *d2["items"])}
    assert len(ma) == 201


async def test_phan_trang_dung_boi_so_200_ton_mot_luot_goi_thua_khong_mat_du_lieu(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """Biên "không chắc" của `_trang()` (review vòng 2): khi tổng số hàng ĐÚNG
    BẰNG `GIOI_HAN_TRANG` (200, không hơn không kém), router KHÔNG THỂ phân
    biệt "vừa hết" với "còn nữa" (không xin dư được 1 hàng nữa ở đúng trần) —
    xử lý BẢO THỦ: coi như còn trang sau. Hệ quả CHẤP NHẬN ĐƯỢC: một lượt gọi
    thừa (trang 2 rỗng), KHÔNG BAO GIỜ mất dữ liệu — khoá lại bằng test để
    quyết định này không bị "tối ưu nhầm" thành sai ở lần sửa sau."""
    await _tao_du_an(client_re, "PP200B")
    async with tenant_conn(pool, workspace_re) as conn:
        for i in range(200):
            z = await repo.chen_phan_khu(conn, workspace_re, {"project_code": "PP200B", "zone_code": f"ZC{i:04d}"})
            assert z is not None

    trang1 = await client_re.get(_url("/projects/PP200B/zones"), params={"limit": 200})
    d1 = trang1.json()
    assert len(d1["items"]) == 200
    assert d1["nextCursor"] is not None, "bảo thủ ở đúng biên — coi như còn trang sau dù thật ra đã hết"

    trang2 = await client_re.get(_url("/projects/PP200B/zones"), params={"limit": 200, "cursor": d1["nextCursor"]})
    d2 = trang2.json()
    assert d2["items"] == []
    assert d2["nextCursor"] is None


async def test_phan_trang_limit_ngoai_bien_tra_422(client_re: httpx.AsyncClient):
    """Finding 3: `limit` vô lý (0, âm, > GIOI_HAN_TRANG) giờ 422 THẬT thay vì
    bị bóp lặng về biên hợp lệ."""
    await _tao_du_an(client_re, "PPLIM")
    for lim in (0, -5, 201, 99999):
        r = await client_re.get(_url("/projects/PPLIM/zones"), params={"limit": lim})
        assert r.status_code == 422, f"limit={lim} phải 422, được {r.status_code}: {r.text}"
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# ─── Nhật ký (BR13) — ghi thật SAU thao tác, không chỉ cổng quét AST tĩnh ──


async def test_moi_thao_tac_ghi_ghi_vao_nhat_ky(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    truoc = await pool.fetchval("SELECT count(*) FROM control.audit_log WHERE tenant_id = $1", workspace_re)

    tao = await _tao_du_an(client_re, "LOG1")
    assert tao.status_code == 201
    await client_re.patch(_url("/projects/LOG1"), json={"region": "HN"})
    await client_re.delete(_url("/projects/LOG1"))

    hang = await pool.fetch("SELECT hanh_dong FROM control.audit_log WHERE tenant_id = $1 ORDER BY id", workspace_re)
    sau = await pool.fetchval("SELECT count(*) FROM control.audit_log WHERE tenant_id = $1", workspace_re)
    assert sau == truoc + 3
    hanh_dong_moi = [r["hanh_dong"] for r in hang[-3:]]
    assert hanh_dong_moi == ["realestate.project.create", "realestate.project.update", "realestate.project.delete"]


# ─── Validate ở biên HTTP (Finding 1, review vòng 2) ───────────────────────
# Trước bản sửa này, sáu input dưới đây đều vỡ ở Postgres (`CheckViolationError`/
# `NotNullViolationError`/`DataError`) — 500 KHÔNG có `error.code`, dù cả sáu ô
# đều CÓ THẬT trên form (`mau-form-cms.html`: dropdown status/productType, vùng
# category, input số tầng). Giờ `Literal[...]`/bỏ `| None` ở field NOT NULL/
# `Field(ge=, le=)` chặn NGAY ở Pydantic — 422 qua `RequestValidationError`,
# dịch sang khuôn lỗi chung ở `api/loi.py` (`VALIDATION_ERROR`).


async def _kiem_422(r: httpx.Response) -> None:
    assert r.status_code == 422, f"kỳ vọng 422, được {r.status_code}: {r.text}"
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_status_bogus_tra_422_khong_phai_500(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "VAL1")
    await _kiem_422(await client_re.patch(_url("/projects/VAL1"), json={"status": "BOGUS"}))


async def test_patch_field_not_null_gui_null_tra_422_khong_phai_500(client_re: httpx.AsyncClient):
    """`investor` là NOT NULL DEFAULT '' ở DB — gửi `null` tường minh phải 422,
    không phải `NotNullViolationError` (500). Đây là repro nặng nhất: DTO cũ
    khai `investor: str | None` QUẢNG CÁO với FE rằng `null` hợp lệ."""
    await _tao_du_an(client_re, "VAL2", investor="Chủ đầu tư gốc")
    await _kiem_422(await client_re.patch(_url("/projects/VAL2"), json={"investor": None}))
    # Dữ liệu KHÔNG bị hỏng bởi request 422 — vẫn còn giá trị gốc
    doc = await client_re.get(_url("/projects/VAL2"))
    assert doc.json()["investor"] == "Chủ đầu tư gốc"


async def test_bedrooms_qua_lon_tra_422_khong_phai_500(client_re: httpx.AsyncClient):
    """`bedrooms` là `smallint` ở DB (`DataError` nếu tràn biên) — `999999`
    phải 422 ở Pydantic, không chạm tới Postgres."""
    await _tao_du_an(client_re, "VAL3")
    await client_re.post(_url("/projects/VAL3/zones"), json={"zoneCode": "Z1"})
    await _kiem_422(
        await client_re.post(
            _url("/projects/VAL3/units"),
            json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu", "bedrooms": 999999},
        )
    )


async def test_product_type_bogus_tra_422_khong_phai_500(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "VAL4")
    await client_re.post(_url("/projects/VAL4/zones"), json={"zoneCode": "Z1"})
    await _kiem_422(
        await client_re.post(
            _url("/projects/VAL4/units"),
            json={"zoneCode": "Z1", "unitCode": "U1", "productType": "BOGUS"},
        )
    )


async def test_media_category_bogus_tra_422_khong_phai_500(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "VAL5")
    await _kiem_422(
        await client_re.post(
            _url("/projects/VAL5/media"),
            json={"contentType": "image", "category": "BOGUS", "mediaUrl": "https://x/a.webp"},
        )
    )


async def test_media_url_rong_tra_422_khong_phai_500(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "VAL6")
    await _kiem_422(
        await client_re.post(
            _url("/projects/VAL6/media"),
            json={"contentType": "image", "category": "tong_quan", "mediaUrl": ""},
        )
    )


async def test_cover_media_url_rong_tra_422(client_re: httpx.AsyncClient):
    """Cùng ràng buộc `min_length=1` áp cho `MediaUploadIn` (luồng cover/map) —
    không chỉ `/media` trực tiếp."""
    await _kiem_422(await _tao_du_an(client_re, "VAL7", coverMedia={"mediaUrl": ""}))


# ─── `extra="forbid"` (Finding 2, review vòng 2) ───────────────────────────


async def test_field_la_tra_422_khong_bi_bo_qua_am_tham(client_re: httpx.AsyncClient):
    """Trước bản sửa: field lạ (`commissionPct`) bị Pydantic ÂM THẦM BỎ QUA,
    request vẫn 201 — vô hiệu hoá đúng nguyên tắc `repo._kiem_payload` tự khai
    ("RAISE chứ không lọc-bỏ-âm-thầm... im lặng bỏ một trường họ tưởng đã lưu
    là mất dữ liệu không ai biết"), vì Pydantic ăn mất field đó TRƯỚC KHI tới
    được `repo`. Giờ `extra="forbid"` chặn ngay ở Pydantic — 422, không 201."""
    r = await _tao_du_an(client_re, "VAL8", commissionPct=3.5)
    await _kiem_422(r)


async def test_field_go_sai_hoa_thuong_tra_422(client_re: httpx.AsyncClient):
    """`coverMediaID` (gõ sai so với `coverMediaId`) — trước đây bị bỏ qua âm
    thầm, biên tập viên tưởng đã lưu ảnh. Giờ 422."""
    r = await _tao_du_an(client_re, "VAL9", coverMediaID=123)
    await _kiem_422(r)


# ─── Completeness — chặn publish khi thiếu dữ liệu (Task 5, `02 §3`/`02a §7`) ─
# `completeness.py` là hàm thuần (test riêng ở `test_completeness.py`); đây kiểm
# ĐƯỜNG GỌI nó ở router — PATCH đưa `status` thành `published`.


async def test_publish_du_an_thieu_du_lieu_tra_422_kem_ten_truong(client_re: httpx.AsyncClient):
    """`project` cần BỐN trường (`product_scale` rời cổng 2026-08-25). Dự án mới
    tạo chỉ có `name` — PATCH publish phải 422 kèm ĐÚNG tên trường còn thiếu,
    không phải "không được" mù mờ."""
    await _tao_du_an(client_re, "COMP1")  # region/overview/... để trống (DEFAULT '')
    r = await client_re.patch(_url("/projects/COMP1"), json={"status": "published"})
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "INCOMPLETE_DATA"
    for truong in ("region", "overview", "investor"):
        assert truong in body["error"]["message"]
    assert "amenities" not in body["error"]["message"], "tiện ích CỐ Ý ngoài cổng (§3.5.1)"
    assert "product_scale" not in body["error"]["message"], "quy mô rời cổng 2026-08-25"
    # KHÔNG bị publish — vẫn draft (kiểm request 422 không âm thầm ghi status)
    doc = await client_re.get(_url("/projects/COMP1"))
    assert doc.json()["status"] == "draft"


async def test_publish_du_an_du_du_lieu_tra_200(client_re: httpx.AsyncClient):
    await _tao_du_an(
        client_re,
        "COMP2",
        region="Hà Nội",
        overview="Mô tả tổng quan",
        investor="CĐT",
        productScale="3 toà",
    )
    r = await client_re.patch(_url("/projects/COMP2"), json={"status": "published"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"


async def test_publish_du_an_du_du_lieu_tu_hai_patch_rieng_tra_200(client_re: httpx.AsyncClient):
    """Completeness kiểm trên bản ghi ĐÃ GỘP — trường bắt buộc được điền ở một
    PATCH TRƯỚC, publish ở một PATCH SAU (không gửi lại field đã có) vẫn phải
    200, không chỉ trường hợp gửi đủ field CÙNG lúc với `status`."""
    await _tao_du_an(client_re, "COMP3")
    await client_re.patch(
        _url("/projects/COMP3"),
        json={"region": "HCM", "overview": "Mô tả", "investor": "CĐT", "productScale": "2 toà"},
    )
    r = await client_re.patch(_url("/projects/COMP3"), json={"status": "published"})
    assert r.status_code == 200, r.text


async def test_publish_du_an_khong_ap_completeness_neu_khong_doi_status(client_re: httpx.AsyncClient):
    """Draft thiếu dữ liệu KHÔNG bị chặn khi PATCH không đụng `status` — luật chỉ
    áp khi bản ghi SẮP thành `published` (`02a §7` chỉ định nghĩa "đủ để publish",
    không phải "đủ để sửa draft")."""
    await _tao_du_an(client_re, "COMP4")
    r = await client_re.patch(_url("/projects/COMP4"), json={"investor": "CĐT mới"})
    assert r.status_code == 200, r.text
    assert r.json()["investor"] == "CĐT mới"


async def test_publish_can_thieu_du_lieu_tra_422_kem_ten_truong(client_re: httpx.AsyncClient):
    """`unit` cần `price_vnd+area_built_m2+sale_status` (`02a §7`). `sale_status`
    luôn có DEFAULT `'available'` (NOT NULL) nên chỉ `price_vnd`/`area_built_m2`
    thiếu thật khi không gửi lúc tạo."""
    await _tao_du_an(client_re, "COMP5")
    await client_re.post(_url("/projects/COMP5/zones"), json={"zoneCode": "Z1"})
    tao = await client_re.post(
        _url("/projects/COMP5/units"),
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu"},
    )
    id_ = tao.json()["id"]
    r = await client_re.patch(_url(f"/projects/COMP5/units/{id_}"), json={"status": "published"})
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "INCOMPLETE_DATA"
    assert "price_vnd" in body["error"]["message"]
    assert "area_built_m2" in body["error"]["message"]


async def test_publish_can_du_du_lieu_tra_200(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "COMP6")
    await client_re.post(_url("/projects/COMP6/zones"), json={"zoneCode": "Z1"})
    tao = await client_re.post(
        _url("/projects/COMP6/units"),
        json={
            "zoneCode": "Z1",
            "unitCode": "U1",
            "productType": "chung_cu",
            "priceVnd": 5_000_000_000,
            "areaBuiltM2": 78.4,
        },
    )
    id_ = tao.json()["id"]
    r = await client_re.patch(_url(f"/projects/COMP6/units/{id_}"), json={"status": "published"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"


async def test_publish_ALL_khong_bi_chan_boi_completeness(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """`__ALL__` (`SENTINEL_TENANT`) là row hệ thống — không `region`/`overview`
    thật, LUÔN `published`. Nếu áp completeness như dự án thường thì MỌI PATCH
    sau đó lên nó (kể cả không đụng `status`, vì `status` cũ đã là `published`)
    sẽ 422 vĩnh viễn — test này khoá lại rằng nó được MIỄN."""
    await _seed_sentinel(pool, workspace_re)

    # PATCH không đụng field completeness nào, không đụng cả status — vẫn phải
    # 200: nếu gate không miễn trừ __ALL__, request này sẽ 422 vì region/overview
    # rỗng trong khi status hiện tại (đã published) được coi là "đích".
    r = await client_re.patch(_url("/projects/__ALL__"), json={"investor": "Không liên quan"})
    assert r.status_code == 200, r.text
    assert r.json()["investor"] == "Không liên quan"
    assert r.json()["status"] == "published"


# ─── Completeness ở ĐƯỜNG POST (review vòng 3, Finding Important) ───────────
# Reviewer tái hiện: `POST /projects {"projectCode":"REVBYPASS1","name":"...",
# "status":"published"}` → 201, `region`/`overview` rỗng — gate cũ chỉ áp PATCH,
# bỏ lọt đúng đường tạo phổ biến nhất. `02 §3` "chặn publish" không kèm điều
# kiện đường vào — POST cũng phải qua CÙNG MỘT hàm (`_kiem_completeness`) PATCH
# đang dùng, không phải một bản luật thứ hai.


async def test_publish_post_du_an_thieu_du_lieu_tra_422_kem_ten_truong(client_re: httpx.AsyncClient):
    """Đúng repro của reviewer — `POST /projects` với `status=published` ngay
    từ đầu mà thiếu trường bắt buộc phải 422, không phải 201."""
    r = await client_re.post(
        _url("/projects"),
        json={"projectCode": "REVBYPASS1", "name": "Chi co ten", "status": "published"},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "INCOMPLETE_DATA"
    assert "region" in body["error"]["message"]
    assert "overview" in body["error"]["message"]
    doc = await client_re.get(_url("/projects/REVBYPASS1"))
    assert doc.status_code == 404


async def test_publish_post_du_an_du_du_lieu_tra_201(client_re: httpx.AsyncClient):
    r = await client_re.post(
        _url("/projects"),
        json={
            "projectCode": "COMP7",
            "name": "Dự án COMP7",
            "region": "Hà Nội",
            "overview": "Mô tả tổng quan",
            "investor": "CĐT",
            "productScale": "3 toà",
            "status": "published",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "published"


async def test_post_du_an_draft_thieu_du_lieu_van_201(client_re: httpx.AsyncClient):
    """Draft thiếu dữ liệu là chuyện BÌNH THƯỜNG — gate chỉ áp khi bản ghi mới
    ngay từ đầu đã `published`, không áp cho `status` mặc định/`draft`."""
    r = await client_re.post(_url("/projects"), json={"projectCode": "COMP8", "name": "Chỉ có tên"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"
    assert r.json()["region"] == ""


async def test_publish_post_can_thieu_du_lieu_tra_422_kem_ten_truong(client_re: httpx.AsyncClient):
    """`POST .../units` với `status=published` mà thiếu `price_vnd`/
    `area_built_m2` phải 422, cùng mã lỗi/cùng tên trường như PATCH."""
    await _tao_du_an(client_re, "COMP9")
    await client_re.post(_url("/projects/COMP9/zones"), json={"zoneCode": "Z1"})
    r = await client_re.post(
        _url("/projects/COMP9/units"),
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu", "status": "published"},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "INCOMPLETE_DATA"
    assert "price_vnd" in body["error"]["message"]
    assert "area_built_m2" in body["error"]["message"]


async def test_publish_post_can_du_du_lieu_tra_201(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "COMP10")
    await client_re.post(_url("/projects/COMP10/zones"), json={"zoneCode": "Z1"})
    r = await client_re.post(
        _url("/projects/COMP10/units"),
        json={
            "zoneCode": "Z1",
            "unitCode": "U1",
            "productType": "chung_cu",
            "priceVnd": 5_000_000_000,
            "areaBuiltM2": 78.4,
            "status": "published",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "published"


async def test_post_can_draft_thieu_du_lieu_van_201(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "COMP11")
    await client_re.post(_url("/projects/COMP11/zones"), json={"zoneCode": "Z1"})
    r = await client_re.post(
        _url("/projects/COMP11/units"),
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu"},  # status mặc định "draft"
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"


async def test_post_ALL_bi_tu_choi_truoc_ca_completeness(client_re: httpx.AsyncClient):
    """Bản trước của test này kỳ vọng 201 ("`__ALL__` được MIỄN completeness ở cả
    đường POST"). Review vòng cuối (Critical A) đảo kỳ vọng đó: `POST /projects
    {"projectCode":"__ALL__"}` phải bị TỪ CHỐI hẳn — miễn completeness cho một
    request mà bản thân request đó không được phép tồn tại là bảo vệ sai lớp.
    Row hệ thống chỉ do provisioning tạo (`scripts/seed_bds.py`).

    Kỳ vọng 409 chứ không 422: nếu gate sentinel bị xoá mà gate completeness còn,
    test này sẽ đỏ với 422 (chứ không âm thầm xanh) — hai lớp phân biệt được nhau
    bằng mã lỗi."""
    r = await _tao_du_an(client_re, "__ALL__", name="Chung toàn tenant", status="published")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SENTINEL_PROTECTED"


# ─── Sentinel `__ALL__` được BẢO VỆ (review vòng cuối, Critical A) ──────────


async def _so_tai_lieu_agent_thay(pool: asyncpg.Pool, tenant: str, project_code: str) -> int:
    """Số tài liệu agent đọc được khi đang tư vấn `project_code` — đi qua CHÍNH
    `repo.liet_ke_tai_lieu_cho_agent` (đường đọc gộp `__ALL__`), vì "1 → 0" ở
    đường đọc của AGENT là thiệt hại thật của Critical A, không phải mã HTTP."""
    async with tenant_conn(pool, tenant) as conn:
        return len(await repo.liet_ke_tai_lieu_cho_agent(conn, project_code))


async def test_patch_sentinel_doi_status_bi_tu_choi(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """`PATCH /projects/__ALL__ {"status":"draft"}` — cascade `status` (`02 §3`)
    sẽ ẩn SẠCH tài liệu/media cấp tenant khỏi mọi câu trả lời của agent."""
    await _seed_sentinel(pool, workspace_re)
    await _tao_du_an(client_re, "SEN1", region="HN", overview="x", status="published")
    tao = await client_re.post(_url("/projects/__ALL__/documents"), json={"title": "Giới thiệu", "status": "published"})
    assert tao.status_code == 201, tao.text
    assert await _so_tai_lieu_agent_thay(pool, workspace_re, "SEN1") == 1

    r = await client_re.patch(_url("/projects/__ALL__"), json={"status": "draft"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SENTINEL_PROTECTED"
    # Thiệt hại KHÔNG xảy ra: sentinel còn published, agent còn thấy tài liệu chung.
    assert (await client_re.get(_url("/projects/__ALL__"))).json()["status"] == "published"
    assert await _so_tai_lieu_agent_thay(pool, workspace_re, "SEN1") == 1


async def test_patch_sentinel_status_published_cung_bi_tu_choi(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """Chặn cả khi gửi ĐÚNG giá trị hiện tại (`published`): luật "chỉ chặn khi
    khác giá trị cũ" là một suy luận về trạng thái DB, và nó sẽ mở lại đúng lỗ
    này ở lần sửa sau (xem `router.sua_du_an`)."""
    await _seed_sentinel(pool, workspace_re)
    r = await client_re.patch(_url("/projects/__ALL__"), json={"status": "published"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SENTINEL_PROTECTED"


async def test_delete_sentinel_bi_tu_choi_tai_lieu_chung_con_nguyen(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """`DELETE /projects/__ALL__` — `ON DELETE CASCADE` xoá HẲN tài liệu chung,
    và anchor mất nên `POST /projects/__ALL__/documents` 404 vĩnh viễn tới khi ai
    đó chạy lại `make seed-bds`."""
    await _seed_sentinel(pool, workspace_re)
    tao = await client_re.post(_url("/projects/__ALL__/documents"), json={"title": "Quy trình mua nhà"})
    assert tao.status_code == 201, tao.text

    r = await client_re.delete(_url("/projects/__ALL__"))
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SENTINEL_PROTECTED"

    con = await client_re.get(_url("/projects/__ALL__/documents"))
    assert [d["title"] for d in con.json()["items"]] == ["Quy trình mua nhà"]
    # Anchor còn ⇒ đường ghi tài liệu chung còn sống (đây là hệ quả nặng nhất).
    lai = await client_re.post(_url("/projects/__ALL__/documents"), json={"title": "Tài liệu thứ hai"})
    assert lai.status_code == 201, lai.text


async def test_liet_ke_du_an_khong_hien_sentinel_nhung_van_doc_duoc_theo_ma(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """Chặn ba đường ghi là chưa đủ: chúng chỉ bị VỚI TỚI vì `GET /projects` bày
    sentinel ra như một dự án bình thường ("Chung / toàn tenant", có nút Xoá).
    Ẩn khỏi DANH SÁCH, nhưng GIỮ đường đọc theo ĐÚNG mã — tab "Tài liệu chung"
    của CMS cần nó."""
    await _seed_sentinel(pool, workspace_re)
    await _tao_du_an(client_re, "SEN2")

    ds = await client_re.get(_url("/projects"), params={"limit": 200})
    ma = [d["projectCode"] for d in ds.json()["items"]]
    assert "__ALL__" not in ma, "sentinel vẫn hiện trong danh sách dự án của CMS"
    assert "SEN2" in ma, "ẩn quá tay — dự án thật cũng mất khỏi danh sách"
    # Tìm kiếm cũng không được lôi nó ra (ô search dùng ILIKE trên project_code).
    tim = await client_re.get(_url("/projects"), params={"search": "ALL"})
    assert "__ALL__" not in [d["projectCode"] for d in tim.json()["items"]]

    theo_ma = await client_re.get(_url("/projects/__ALL__"))
    assert theo_ma.status_code == 200, theo_ma.text
    assert theo_ma.json()["projectCode"] == "__ALL__"


# ─── Trần ≤6 ảnh / danh mục — BỎ ở vòng 2 (spec §4.3) ───────────────────────
# `02a §4.5` từng cưỡng chế ≤6 ảnh/entity ở **app**. Vòng 2 bỏ trần này (không
# ràng buộc DB nào chống lưng, nên bỏ chỉ là bỏ nhánh kiểm). Các test dưới đây
# ĐẢO NGHĨA so với bản trước: ảnh thứ 7 (và xa hơn) giờ phải được NHẬN, không
# còn bị 422 `MEDIA_LIMIT` — cổng canh việc trần đã thật sự biến mất.


async def _post_anh(client: httpx.AsyncClient, project_code: str, i: int, **kw) -> httpx.Response:
    than = {
        "contentType": "image",
        "category": "tong_quan",
        "mediaUrl": f"https://x/{project_code}-{i}.webp",
        **kw,
    }
    return await client.post(_url(f"/projects/{project_code}/media"), json=than)


async def test_anh_thu_bay_cung_danh_muc_duoc_nhan(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    """Trần 6 ảnh/danh mục đã bỏ — chín ảnh cùng danh mục phải vào đủ chín.
    Cổng canh: một nhánh kiểm trần sót lại ở router sẽ làm test này đỏ ở ảnh
    thứ bảy."""
    await _tao_du_an(client_re, "LIM1")
    for i in range(9):
        r = await _post_anh(client_re, "LIM1", i)
        assert r.status_code == 201, f"ảnh thứ {i + 1} bị từ chối: {r.text}"

    so = await pool.fetchval(
        "SELECT count(*) FROM tenant_data.media WHERE tenant_id = $1 AND project_code = 'LIM1'", workspace_re
    )
    assert so == 9, f"thiếu hàng trong DB: {so}"


async def test_tran_anh_dem_rieng_tung_danh_muc(client_re: httpx.AsyncClient):
    """7 vùng upload của form là 7 `category` ĐỘC LẬP — đầy `tong_quan` không
    được khoá `ngoai_that` (đơn vị đếm rộng hơn sẽ khoá form ngay sau hai vùng)."""
    await _tao_du_an(client_re, "LIM2")
    for i in range(6):
        assert (await _post_anh(client_re, "LIM2", i)).status_code == 201
    khac = await _post_anh(client_re, "LIM2", 99, category="ngoai_that")
    assert khac.status_code == 201, khac.text


async def test_tran_anh_dem_rieng_theo_phan_khu_va_can(client_re: httpx.AsyncClient):
    """Cùng `category` nhưng khác cấp (dự án / phân khu / căn) là khác ô đếm —
    `02a §4.5` nói trần áp cho "(project|zone|unit)"."""
    await _tao_du_an(client_re, "LIM3")
    assert (await client_re.post(_url("/projects/LIM3/zones"), json={"zoneCode": "Z1"})).status_code == 201
    for i in range(6):
        assert (await _post_anh(client_re, "LIM3", i)).status_code == 201
    theo_zone = await _post_anh(client_re, "LIM3", 100, zoneCode="Z1")
    assert theo_zone.status_code == 201, theo_zone.text
    theo_can = await _post_anh(client_re, "LIM3", 101, unitCode="U-1")
    assert theo_can.status_code == 201, theo_can.text


async def test_tran_khong_ap_cho_video(client_re: httpx.AsyncClient):
    """Tài liệu viết "≤6 **ảnh**", và `02a §4.5` tách `content_type` thành
    image·video — link YouTube/kuula không nằm trong trần này."""
    await _tao_du_an(client_re, "LIM4")
    for i in range(6):
        assert (await _post_anh(client_re, "LIM4", i)).status_code == 201
    video = await _post_anh(client_re, "LIM4", 200, contentType="video")
    assert video.status_code == 201, video.text


async def test_anh_cover_khong_con_bi_chan_sau_sau_anh(client_re: httpx.AsyncClient):
    """Ô cover cũng tạo row `media` thật (`category=tong_quan`) — trần đã bỏ nên
    đổi cover sau khi đã có 6 ảnh cùng danh mục vẫn phải 200, không còn 422."""
    await _tao_du_an(client_re, "LIM5")
    for i in range(6):
        assert (await _post_anh(client_re, "LIM5", i)).status_code == 201
    r = await client_re.patch(_url("/projects/LIM5"), json={"coverMedia": {"mediaUrl": "https://x/cover.webp"}})
    assert r.status_code == 200, r.text
    assert r.json()["coverMediaId"] is not None


async def test_nap_chin_anh_cung_danh_muc_deu_duoc_nhan(client_re: httpx.AsyncClient):
    """Trần 6 ảnh/danh mục đã bỏ (spec vòng 2 §4.3) — chín ảnh cùng danh mục
    phải vào đủ chín và hiện đủ chín ở đường đọc danh sách."""
    await _tao_du_an(client_re, "LIM6")
    for i in range(9):
        r = await _post_anh(client_re, "LIM6", i, category="ngoai_that")
        assert r.status_code == 201, f"ảnh thứ {i + 1} bị từ chối: {r.text}"

    ds = await client_re.get(_url("/projects/LIM6/media"), params={"category": "ngoai_that"})
    assert len(ds.json()["items"]) == 9


# ─── Bộ lọc danh sách dùng CÙNG enum với đường ghi (Important E) ────────────
# Trước bản sửa: `GET /projects/P/units?product_type=BOGUS` → 200 + danh sách
# RỖNG (repo so `product_type = 'BOGUS'`), tức một lỗi gõ ở bộ lọc FE đọc thành
# "hết hàng". Đường ghi đã 422 sạch từ review vòng 2 — hai đường phải cùng nếp.


async def test_bo_loc_enum_sai_tra_422_khong_phai_200_rong(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "FLT1")
    for duong, tham_so in (
        ("/projects/FLT1/units", {"product_type": "BOGUS"}),
        ("/projects/FLT1/units", {"sale_status": "BOGUS"}),
        ("/projects/FLT1/media", {"category": "BOGUS"}),
        ("/projects/FLT1/media", {"content_type": "BOGUS"}),
    ):
        r = await client_re.get(_url(duong), params=tham_so)
        assert r.status_code == 422, f"{duong}?{tham_so} phải 422, được {r.status_code}: {r.text}"
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_bo_loc_enum_rong_hoac_dung_van_200(client_re: httpx.AsyncClient):
    """`?product_type=` (người dùng xoá lựa chọn trong dropdown) và giá trị ĐÚNG
    đều phải 200 — `Literal` mới KHÔNG được biến hai request hợp lệ thành 422."""
    await _tao_du_an(client_re, "FLT2")
    assert (await client_re.post(_url("/projects/FLT2/zones"), json={"zoneCode": "Z1"})).status_code == 201
    tao = await client_re.post(
        _url("/projects/FLT2/units"),
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu"},
    )
    assert tao.status_code == 201, tao.text

    rong = await client_re.get(_url("/projects/FLT2/units"), params={"product_type": "", "sale_status": ""})
    assert rong.status_code == 200, rong.text
    assert len(rong.json()["items"]) == 1

    dung = await client_re.get(_url("/projects/FLT2/units"), params={"product_type": "chung_cu"})
    assert dung.status_code == 200, dung.text
    assert len(dung.json()["items"]) == 1
    khac = await client_re.get(_url("/projects/FLT2/units"), params={"product_type": "biet_thu"})
    assert khac.status_code == 200 and khac.json()["items"] == []  # lọc vẫn LỌC, không phải bỏ qua


# ─── Id chéo dự án — nhánh `hang["project_code"] != project_code` (Minor F2) ─
# Nhánh đó xuất hiện 12 lần (units/documents/media × GET/PATCH/DELETE) và là thứ
# DUY NHẤT chặn `GET /projects/A/units/{id_của_B}` TRONG CÙNG một tenant — RLS
# không giúp gì ở đây (cùng tenant), mà trước bản sửa này không test nào phủ.


async def _dung_hai_du_an_va_con(client: httpx.AsyncClient) -> dict[str, int]:
    """Dự án `XA` + `XB`; unit/document/media đều thuộc `XB`. Trả id các con."""
    await _tao_du_an(client, "XA")
    await _tao_du_an(client, "XB")
    assert (await client.post(_url("/projects/XB/zones"), json={"zoneCode": "Z1"})).status_code == 201
    can = await client.post(
        _url("/projects/XB/units"), json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu"}
    )
    tai_lieu = await client.post(_url("/projects/XB/documents"), json={"title": "Của XB"})
    media = await client.post(
        _url("/projects/XB/media"),
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/xb.webp"},
    )
    for r in (can, tai_lieu, media):
        assert r.status_code == 201, r.text
    return {"unit": can.json()["id"], "document": tai_lieu.json()["id"], "media": media.json()["id"]}


@pytest.mark.parametrize(
    ("duong", "khoa", "ma_loi"),
    [
        ("units", "unit", "UNIT_NOT_FOUND"),
        ("documents", "document", "DOCUMENT_NOT_FOUND"),
        ("media", "media", "MEDIA_NOT_FOUND"),
    ],
)
async def test_id_cua_du_an_khac_tra_404_tren_ca_ba_dong_tu(
    client_re: httpx.AsyncClient, duong: str, khoa: str, ma_loi: str
):
    id_con = (await _dung_hai_du_an_va_con(client_re))[khoa]
    lac = _url(f"/projects/XA/{duong}/{id_con}")  # id của XB, đường dẫn nói XA

    doc = await client_re.get(lac)
    assert doc.status_code == 404, doc.text
    assert doc.json()["error"]["code"] == ma_loi

    sua = await client_re.patch(lac, json={"status": "archived"})
    assert sua.status_code == 404, sua.text
    assert sua.json()["error"]["code"] == ma_loi

    xoa = await client_re.delete(lac)
    assert xoa.status_code == 404, xoa.text
    assert xoa.json()["error"]["code"] == ma_loi

    # Hàng của XB KHÔNG bị PATCH/DELETE lạc đường chạm tới.
    that = await client_re.get(_url(f"/projects/XB/{duong}/{id_con}"))
    assert that.status_code == 200, that.text
    assert that.json()["status"] == "draft"


# ─── Thân lỗi 422 có CẤU TRÚC (Minor F3, `api/loi.py` — file DÙNG CHUNG) ────
# Trước bản sửa: `message = str(RequestValidationError)`, tức repr dict Python
# ("1 validation error:\n  {'type': 'string_too_short', 'loc': ('body',
# 'mediaUrl'), ...}"). Đó là hình dạng 422 của CẢ 25 route realestate LẪN mọi
# route M2a — FE không map được về field nào mà không parse repr bằng regex.


async def test_than_loi_422_liet_ke_field_va_ly_do(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "ERR1")
    r = await client_re.post(
        _url("/projects/ERR1/media"),
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": ""},
    )
    assert r.status_code == 422, r.text
    than = r.json()["error"]
    assert than["code"] == "VALIDATION_ERROR"  # mã lỗi là hợp đồng cũ, KHÔNG đổi
    assert than["fields"] == [{"field": "body.mediaUrl", "reason": "String should have at least 1 character"}]
    # KHÔNG còn repr dict Python trong `message`
    assert "'type':" not in than["message"]
    assert "mediaUrl" in than["message"]


async def test_than_loi_422_bao_dung_nhieu_field_va_nguon_query(client_re: httpx.AsyncClient):
    """Nhiều lỗi ⇒ nhiều phần tử; và tiền tố `query`/`body` giữ lại để FE biết
    field sai ở query string hay ở thân request."""
    # `POST {}` KHÔNG còn là lỗi field-level: `projectCode` nay tuỳ chọn (§3.1) nên
    # thân rỗng trả `PROJECT_NAME_REQUIRED` chứ không phải `VALIDATION_ERROR`. Lấy
    # một lỗi enum để vẫn canh được hình dạng `fields[]`.
    sai_enum = await client_re.post(_url("/projects"), json={"projectCode": "VALID1", "status": "khong_ton_tai"})
    assert sai_enum.status_code == 422, sai_enum.text
    assert [t["field"] for t in sai_enum.json()["error"]["fields"]] == ["body.status"]

    r = await client_re.get(_url("/projects"), params={"limit": 0})
    assert r.status_code == 422, r.text
    assert [t["field"] for t in r.json()["error"]["fields"]] == ["query.limit"]


# ─── Thứ tự 404-trước-422 ở POST units (Minor F6) ──────────────────────────


async def test_post_can_du_an_khong_ton_tai_tra_404_khong_phai_422(client_re: httpx.AsyncClient):
    """Bản trước áp completeness TRƯỚC khi mở giao dịch, nên request này trả 422
    ("thiếu price_vnd/area_built_m2") cho một dự án KHÔNG TỒN TẠI: FE thêm field,
    gửi lại, rồi mới nhận 404 — một vòng debug oan."""
    r = await client_re.post(
        _url("/projects/KHONG-CO-BAO-GIO/units"),
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu", "status": "published"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_422_completeness_sau_insert_khong_de_lai_hang(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    """Hệ quả của việc dời gate xuống SAU INSERT: 422 phải rollback hàng vừa
    chèn (`tenant_conn` mở transaction cho cả khối) và KHÔNG ghi nhật ký "đã tạo
    căn" cho một căn không tồn tại."""
    await _tao_du_an(client_re, "ORD1")
    assert (await client_re.post(_url("/projects/ORD1/zones"), json={"zoneCode": "Z1"})).status_code == 201
    truoc = await pool.fetchval(
        "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'realestate.unit.create'",
        workspace_re,
    )

    r = await client_re.post(
        _url("/projects/ORD1/units"),
        json={"zoneCode": "Z1", "unitCode": "U1", "productType": "chung_cu", "status": "published"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INCOMPLETE_DATA"

    so = await pool.fetchval(
        "SELECT count(*) FROM tenant_data.units WHERE tenant_id = $1 AND project_code = 'ORD1'", workspace_re
    )
    assert so == 0, f"422 để lại {so} hàng — giao dịch không rollback"
    sau = await pool.fetchval(
        "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'realestate.unit.create'",
        workspace_re,
    )
    assert sau == truoc, "ghi nhật ký cho một căn chưa bao giờ tồn tại"


# ─── Bộ lọc theo `status` (2026-08-25) ───────────────────────────────────────
#
# Dashboard nói «N căn chưa đọc được» rồi dẫn sang bảng quỹ căn — mà bảng đó
# không có cách nào lọc ra đúng N căn ấy. Trên tenant thật `aina_prod` là 944
# căn trong 5.609, tức lật trang bằng mắt là bất khả.


async def test_loc_theo_status_tra_dung_nhom(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "ST1")
    assert (await client_re.post(_url("/projects/ST1/zones"), json={"zoneCode": "Z1"})).status_code == 201
    # Thiếu giá + cả hai diện tích ⇒ không phát hành được ⇒ nằm ở draft.
    nhap = await client_re.post(
        _url("/projects/ST1/units"),
        json={"zoneCode": "Z1", "unitCode": "NHAP", "productType": "chung_cu"},
    )
    assert nhap.status_code == 201, nhap.text
    # Đủ giá + DT đất ⇒ phát hành được (luật «một trong hai diện tích»).
    phat = await client_re.post(
        _url("/projects/ST1/units"),
        json={
            "zoneCode": "Z1",
            "unitCode": "PHAT",
            "productType": "biet_thu",
            "priceVnd": 21_000_000_000,
            "areaLandM2": 180,
            "saleStatus": "sold",
            "status": "published",
        },
    )
    assert phat.status_code == 201, phat.text

    r = await client_re.get(_url("/projects/ST1/units"), params={"status": "draft"})
    assert r.status_code == 200, r.text
    assert [c["unitCode"] for c in r.json()["items"]] == ["NHAP"]
    assert r.json()["total"] == 1

    r = await client_re.get(_url("/projects/ST1/units"), params={"status": "published"})
    assert [c["unitCode"] for c in r.json()["items"]] == ["PHAT"]
    assert r.json()["total"] == 1

    # Không lọc ⇒ cả hai. `total` phải theo bộ lọc, không phải tổng cứng.
    r = await client_re.get(_url("/projects/ST1/units"))
    assert r.json()["total"] == 2


async def test_loc_status_sai_gia_tri_tra_422(client_re: httpx.AsyncClient):
    await _tao_du_an(client_re, "ST2")
    r = await client_re.get(_url("/projects/ST2/units"), params={"status": "BOGUS"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
