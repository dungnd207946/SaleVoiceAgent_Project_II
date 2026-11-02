"""Test hai route kho tệp của M4 — `POST /realestate/uploads` · `GET /realestate/files`.

VÌ SAO FILE RIÊNG, KHÔNG GỘP `test_crud.py`: hai route này không chạm bảng nào.
Chúng chỉ nói chuyện với MinIO, và thứ chúng phải đúng là một danh sách khác hẳn
CRUD — trần dung lượng, danh sách loại tệp, tên tệp do người dùng đặt, và
**tiền tố tenant trên khoá**. Trộn vào `test_crud.py` thì cái cuối cùng nằm lẫn
giữa 100 test CRUD và không ai đọc nó như một cổng cách ly.

CỔNG QUAN TRỌNG NHẤT Ở ĐÂY là `test_khoa_cua_tenant_khac_tra_404`: RLS của
Postgres không với tới object trong S3, và access key của tiến trình API có
quyền trên cả tiền tố `tenants/`. Nếu `GET /realestate/files` không tự kiểm tiền
tố thì một request hợp lệ hoàn toàn đọc được ảnh của khách khác — và không lớp
nào phía dưới chặn được.
"""

import asyncpg
import httpx
import pytest

from tests.modules.realestate.conftest import MAT_KHAU

pytestmark = pytest.mark.integration

PNG_NHO = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
"""PNG 1×1 thật (không phải bytes ngẫu nhiên): route không parse ảnh, nhưng một
tệp thật làm test đọc được như thứ nó mô phỏng, và nếu sau này thêm bước đọc
kích thước ảnh thì test này không phải viết lại."""


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _len(client: httpx.AsyncClient, ten: str, noi_dung: bytes = PNG_NHO) -> httpx.Response:
    return await client.post(_url("/realestate/uploads"), files={"file": (ten, noi_dung, "image/png")})


# ─── Tải lên ────────────────────────────────────────────────────────────────


async def test_tai_anh_len_tra_khoa_trong_tien_to_tenant(client_re: httpx.AsyncClient, workspace_re: str) -> None:
    r = await _len(client_re, "cover.png")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"].startswith(f"tenants/{workspace_re}/kb-bds/")
    assert body["key"].endswith("/cover.png")
    assert body["contentType"] == "image/png"
    assert len(body["contentHash"]) == 64


async def test_cung_noi_dung_ra_cung_khoa(client_re: httpx.AsyncClient) -> None:
    """Content-addressed: tải lại sau khi mất mạng không sinh bản sao."""
    a = await _len(client_re, "cover.png")
    b = await _len(client_re, "cover.png")
    assert a.json()["key"] == b.json()["key"]


async def test_noi_dung_khac_ra_khoa_khac(client_re: httpx.AsyncClient) -> None:
    a = await _len(client_re, "cover.png", PNG_NHO)
    b = await _len(client_re, "cover.png", PNG_NHO + b"\x00")
    assert a.json()["key"] != b.json()["key"]


async def test_loai_tep_khong_ho_tro_tra_422(client_re: httpx.AsyncClient) -> None:
    r = await _len(client_re, "virus.exe", b"MZ")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_TYPE"


async def test_tep_khong_co_duoi_tra_422(client_re: httpx.AsyncClient) -> None:
    """Tên không có dấu chấm: `rsplit('.', 1)[-1]` trả lại CẢ tên, nên nếu route
    không kiểm `'.' in ten` thì một tệp tên `pdf` lọt qua như tệp `.pdf`."""
    r = await _len(client_re, "pdf", b"%PDF-1.4")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_TYPE"


async def test_anh_qua_dung_luong_tra_422(client_re: httpx.AsyncClient) -> None:
    from portal.modules.realestate.router import GIOI_HAN_ANH_BYTE

    r = await _len(client_re, "to.png", b"\x00" * (GIOI_HAN_ANH_BYTE + 1))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_tai_lieu_duoc_tran_cao_hon_anh(client_re: httpx.AsyncClient) -> None:
    """Ảnh trần 10 MB, tài liệu trần 25 MB — một tệp 12 MB phải BỊ chặn khi là
    ảnh và ĐƯỢC nhận khi là pdf. Hai trần khác nhau là chủ ý, không phải sót."""
    to = b"%PDF" + b"\x00" * (12 * 1024 * 1024)
    assert (await _len(client_re, "to.png", to)).status_code == 422
    assert (await _len(client_re, "hopdong.pdf", to)).status_code == 201


async def test_tep_rong_tra_422(client_re: httpx.AsyncClient) -> None:
    r = await _len(client_re, "rong.png", b"")
    assert r.status_code == 422


async def test_ten_tep_co_duong_dan_khong_treo_ra_khoi_tien_to(client_re: httpx.AsyncClient, workspace_re: str) -> None:
    """`../../` trong TÊN TỆP không được biến thành `../../` trong KHOÁ.

    Client đặt được `filename` thành bất kỳ chuỗi nào. Nếu tên đi thẳng vào khoá
    thì `../../../other/x.png` ghi ra ngoài tiền tố tenant — và policy chỉ bảo
    vệ thứ nằm trong tiền tố nó biết.
    """
    r = await _len(client_re, "../../../etc/passwd.png")
    assert r.status_code == 201, r.text
    khoa = r.json()["key"]
    assert khoa.startswith(f"tenants/{workspace_re}/kb-bds/")
    assert ".." not in khoa
    # 4 đoạn: tenants / <tenant> / kb-bds / <sha> / <ten>
    assert khoa.count("/") == 4


async def test_ten_tep_tieng_viet_van_ra_khoa_hop_le(client_re: httpx.AsyncClient) -> None:
    r = await _len(client_re, "mặt bằng tổng.png")
    assert r.status_code == 201, r.text
    khoa = r.json()["key"]
    assert khoa.isascii()
    assert khoa.rsplit("/", 1)[-1] != ""


async def test_tai_len_vao_nhat_ky(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str) -> None:
    """BR13. Tệp mồ côi (tải lên rồi không bấm Lưu) không có hàng `media` nào —
    dòng này là dấu vết DUY NHẤT của nó."""
    khoa = (await _len(client_re, "cover.png")).json()["key"]
    hang = await pool.fetchrow(
        "SELECT hanh_dong, actor, chi_tiet FROM control.audit_log"
        " WHERE tenant_id = $1 AND hanh_dong = 'realestate.upload' ORDER BY id DESC LIMIT 1",
        workspace_re,
    )
    assert hang is not None, "upload không để lại dấu vết nào"
    assert hang["actor"] == "u_re"
    import json

    chi_tiet = hang["chi_tiet"] if isinstance(hang["chi_tiet"], dict) else json.loads(hang["chi_tiet"])
    assert chi_tiet["key"] == khoa
    assert chi_tiet["ten_file"] == "cover.png"


async def test_tai_len_can_quyen_ghi(app_client: httpx.AsyncClient) -> None:
    """Chưa đăng nhập ⇒ không có `catalog.write` ⇒ không tới được kho tệp."""
    r = await app_client.post(_url("/realestate/uploads"), files={"file": ("a.png", PNG_NHO, "image/png")})
    assert r.status_code in (401, 403)


# ─── Đọc lại ────────────────────────────────────────────────────────────────


async def test_doc_lai_tep_vua_ghi(client_re: httpx.AsyncClient) -> None:
    khoa = (await _len(client_re, "cover.png")).json()["key"]
    r = await client_re.get(_url("/realestate/files"), params={"key": khoa})
    assert r.status_code == 200, r.text
    assert r.content == PNG_NHO
    assert r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"]


async def test_content_type_theo_duoi_khong_theo_client(client_re: httpx.AsyncClient) -> None:
    """Client khai `image/png` cho một tệp `.pdf` — đường đọc phải trả
    `application/pdf` theo ĐUÔI. Tin client ở đây là mở đường phát lại một
    `text/html` từ cùng origin với portal, tức XSS."""
    r = await client_re.post(
        _url("/realestate/uploads"),
        files={"file": ("hopdong.pdf", b"%PDF-1.4 noi dung", "image/png")},
    )
    khoa = r.json()["key"]
    assert r.json()["contentType"] == "application/pdf"
    doc = await client_re.get(_url("/realestate/files"), params={"key": khoa})
    assert doc.headers["content-type"] == "application/pdf"


async def test_khoa_khong_ton_tai_tra_404(client_re: httpx.AsyncClient, workspace_re: str) -> None:
    r = await client_re.get(
        _url("/realestate/files"),
        params={"key": f"tenants/{workspace_re}/kb-bds/{'0' * 64}/khong-co.png"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NO_FILE"


@pytest.mark.parametrize(
    "khoa",
    [
        "tenants/tenant-khac/kb-bds/abc/x.png",
        "tenants/rew2/kb-bds/abc/x.png",
        "../../../etc/passwd",
        "tenants/rew/../rew2/kb-bds/abc/x.png",
        "",
        "kb-bds/abc/x.png",
    ],
)
async def test_khoa_ngoai_tien_to_tenant_tra_404(client_re: httpx.AsyncClient, khoa: str) -> None:
    """404 chứ không 403: 403 xác nhận khoá TỒN TẠI, và tên khoá mang tên dự án
    của người khác."""
    r = await client_re.get(_url("/realestate/files"), params={"key": khoa})
    assert r.status_code == 404, f"khoá {khoa!r} lọt qua cổng tiền tố"


async def test_khoa_cua_tenant_khac_tra_404(
    app_client: httpx.AsyncClient, client_re: httpx.AsyncClient, pool: asyncpg.Pool, kho_tep
) -> None:
    """CỔNG CÁCH LY. Tenant A upload; tenant B biết chính xác khoá đó và xin đọc.

    Khoá A ĐANG TỒN TẠI trong kho và access key của tiến trình API đọc được nó —
    thứ duy nhất chặn là phép kiểm tiền tố trong `doc_tep`. Test dựng đúng tình
    huống đó chứ không dùng khoá bịa: một khoá bịa cũng 404 khi cổng tiền tố bị
    xoá (vì tệp không có thật), nên nó không chứng minh được gì.
    """
    from portal.core.auth.password import bam

    khoa_a = (await _len(client_re, "cover.png")).json()["key"]
    # Xác nhận tiền đề: tệp có thật, A đọc được.
    assert (await client_re.get(_url("/realestate/files"), params={"key": khoa_a})).status_code == 200

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('rex', 'X', 'u_seed_test')")
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ('u_rex', 'X', 'x@re.vn', $1)",
            bam(MAT_KHAU),
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_rex', 'rex', $1)",
            r_admin,
        )
    try:
        dn = await app_client.post("/api/v1/auth/login", json={"email": "x@re.vn", "password": MAT_KHAU})
        assert dn.status_code == 200, dn.text
        r = await app_client.get(_url("/realestate/files"), params={"key": khoa_a})
        assert r.status_code == 404, "RÒ TENANT: B đọc được tệp của A"
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM control.tenants WHERE id = 'rex'")
            await conn.execute("DELETE FROM control.users WHERE id = 'u_rex'")


async def test_doc_can_quyen_doc(app_client: httpx.AsyncClient) -> None:
    r = await app_client.get(_url("/realestate/files"), params={"key": "tenants/rew/kb-bds/a/b.png"})
    assert r.status_code in (401, 403)


# ─── Ảnh cover phải tới được agent ──────────────────────────────────────────


async def test_anh_cover_cua_du_an_published_thi_agent_thay_duoc(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
) -> None:
    """LỖ ĐÃ TỪNG CÓ THẬT (smoke test đầu-cuối 2026-08-03), không phải giả thuyết —
    trước `0917`, view `agent_api.media` lọc `m.status='published' AND
    p.status='published'`, và ảnh cover (status mặc định `'draft'`, `MediaUploadIn`
    không có field để client đặt khác) vô hình với agent vĩnh viễn dù dự án đã
    published.

    Từ `0917`: agent đọc thẳng `tenant_data.media`, không còn filter `status` nào ở
    tầng Postgres — lỗ cụ thể này không còn CÁCH nào tái diễn qua đường DB (lọc
    published giờ là việc agent tự làm). Giữ lại test này ở dạng rút gọn: xác nhận
    đường upload → PATCH `coverMedia` → agent đọc được bằng role thật vẫn chạy
    thông suốt.
    """
    khoa = (await _len(client_re, "cover.png")).json()["key"]
    r = await client_re.post(_url("/projects"), json={"projectCode": "COVER1", "name": "Có cover"})
    assert r.status_code == 201, r.text

    r = await client_re.patch(
        _url("/projects/COVER1"),
        json={
            "region": "Đà Nẵng",
            "overview": "Đủ dữ liệu để publish.",
            "investor": "CĐT",
            "productScale": "1 toà",
            "status": "published",
            "coverMedia": {"mediaUrl": khoa, "caption": "Toàn cảnh"},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["coverMediaId"] is not None

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL ROLE agent_all")
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", workspace_re)
        hang = await conn.fetch(
            "SELECT category, caption, media_url FROM tenant_data.media WHERE project_code = 'COVER1'"
        )

    assert len(hang) == 1, "agent KHÔNG thấy ảnh cover của một dự án đã published"
    assert hang[0]["category"] == "tong_quan"
    assert hang[0]["media_url"] == khoa


# ─── Đường công khai (agent gửi ảnh cho khách) ──────────────────────────────


def _url_cong_khai(khoa: str) -> str:
    return f"/api/v1/public/files/{khoa}"


async def test_doc_duoc_khi_chua_dang_nhap(app_client: httpx.AsyncClient, client_re: httpx.AsyncClient) -> None:
    """Khách cuối mở link trong cửa sổ chat — họ không có phiên Portal."""
    khoa = (await _len(client_re, "cover.png")).json()["key"]
    r = await app_client.get(_url_cong_khai(khoa))
    assert r.status_code == 200, r.text
    assert r.content == PNG_NHO
    assert r.headers["content-type"] == "image/png"
    assert "public" in r.headers["cache-control"]


@pytest.mark.parametrize(
    "khoa",
    [
        "tenants/anphu/bundles/abc/manifest.toml",
        "tenants/anphu/LIVE",
        "tenants/anphu/kb-bds/../../other/x.png",
        "../../../etc/passwd",
        "kb-bds/abc/x.png",
        "tenants//kb-bds/x.png",
        "tenants/anphu/kb/anh/../../other/x.png",
        f"tenants/anphu/kb/{'0' * 64}/ban-ve.md",
    ],
)
async def test_chi_phat_tien_to_kb_bds(app_client: httpx.AsyncClient, khoa: str) -> None:
    """`bundles/` là persona + prompt của agent. Lọt ra là lộ bí mật kinh doanh."""
    r = await app_client.get(_url_cong_khai(khoa))
    assert r.status_code == 404, f"khoá {khoa!r} lọt qua cổng tiền tố công khai"


async def test_khoa_khong_ton_tai_tra_404_cong_khai(app_client: httpx.AsyncClient) -> None:
    r = await app_client.get(_url_cong_khai(f"tenants/anphu/kb-bds/{'0' * 64}/khong-co.png"))
    assert r.status_code == 404


# ─── Ảnh Markdown đã mirror (`kb/anh/`, xem external_images.py) ─────────────


async def test_anh_mirror_duoc_phat_qua_cong_khai(app_client: httpx.AsyncClient, kho_tep, workspace_re: str) -> None:
    """Ảnh Markdown kéo về từ kho khách, agent nhúng link vào tin nhắn chat."""
    sha = "1" * 64
    khoa = f"tenants/{workspace_re}/kb/anh/{sha}.png"
    await kho_tep.ghi(khoa, PNG_NHO, content_type="image/png")
    r = await app_client.get(_url_cong_khai(khoa))
    assert r.status_code == 200, r.text
    assert r.content == PNG_NHO


async def test_thumb_cua_anh_mirror_duoc_phat_qua_cong_khai(
    app_client: httpx.AsyncClient, kho_tep, workspace_re: str
) -> None:
    """Thumb là khoá anh em cùng thư mục (`thumbnail.thumb_key`) — cùng cần công khai."""
    sha = "2" * 64
    khoa = f"tenants/{workspace_re}/kb/anh/{sha}.thumb.webp"
    await kho_tep.ghi(khoa, PNG_NHO, content_type="image/webp")
    r = await app_client.get(_url_cong_khai(khoa))
    assert r.status_code == 200, r.text
    assert r.content == PNG_NHO


async def test_tai_lieu_tho_khong_duoc_phat_qua_cong_khai(
    app_client: httpx.AsyncClient, kho_tep, workspace_re: str
) -> None:
    """`kb/<sha>/<ten>` là tài liệu THÔ khách tải lên (M6) — riêng tư, khác `kb/anh/`."""
    sha = "3" * 64
    khoa = f"tenants/{workspace_re}/kb/{sha}/so-tay-noi-bo.md"
    await kho_tep.ghi(khoa, b"# Bi mat noi bo", content_type="text/markdown")
    r = await app_client.get(_url_cong_khai(khoa))
    assert r.status_code == 404, "tài liệu thô lọt qua cổng công khai — lộ dữ liệu riêng của khách"


# ─── 307 tới URL kho có hạn (D21) ───────────────────────────────────────────


@pytest.fixture
def bat_307(monkeypatch):
    """Bật cờ qua BIẾN MÔI TRƯỜNG: `get_settings()` dựng `Settings` MỚI mỗi lời gọi, nên
    gán thuộc tính lên một instance không tới được route."""
    from portal.core import storage

    storage.kho_tep_dung_chung.cache_clear()
    monkeypatch.setenv("S3_REDIRECT_ENABLED", "true")
    yield
    storage.kho_tep_dung_chung.cache_clear()


async def test_mac_dinh_van_tra_byte(client_re, workspace_re):
    """Cờ mặc định TẮT: kho không mở được từ Internet thì 307 làm ảnh vỡ phía khách mà
    không có lỗi nào phía ta. Bật là quyết định vận hành, không phải mặc định."""
    from portal.core.config import get_settings

    assert get_settings().s3_redirect_enabled is False


async def test_bat_co_thi_tra_307_khong_tra_byte(client_re, workspace_re, bat_307, monkeypatch):
    from portal.core import storage

    async def _presign(self, khoa, *, ttl_sec=300):
        return f"https://kho.noi-bo/{khoa}?X-Amz-Expires={ttl_sec}"

    monkeypatch.setattr(storage.KhoTep, "presign_get", _presign)

    khoa = f"tenants/{workspace_re}/kb-bds/abc/a.jpg"
    r = await client_re.get("/api/v1/realestate/files", params={"key": khoa}, follow_redirects=False)
    assert r.status_code == 307, r.text
    assert r.headers["location"].startswith("https://kho.noi-bo/")
    assert not r.content, "307 mà vẫn kèm byte thì không tiết kiệm được gì"


async def test_307_giu_nguyen_hinh_dang_duong_dan(client_re, workspace_re, bat_307, monkeypatch):
    """Đường dẫn `public_url_of()` sinh ra ĐÃ nằm trong payload Qdrant, trong cột
    `media.public_url`, và trong link đã gửi cho khách — đổi nó là làm chết hết chúng."""
    from portal.core import storage
    from portal.core.public_url import public_url_of

    async def _presign(self, khoa, *, ttl_sec=300):
        return f"https://kho.noi-bo/{khoa}"

    monkeypatch.setattr(storage.KhoTep, "presign_get", _presign)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.test")

    khoa = f"tenants/{workspace_re}/kb-bds/abc/a.jpg"
    duong_dan = public_url_of(khoa)
    assert duong_dan.endswith(f"/api/v1/public/files/{khoa}"), duong_dan

    r = await client_re.get(f"/api/v1/public/files/{khoa}", follow_redirects=False)
    assert r.status_code == 307


async def test_307_sinh_url_moi_moi_luot(client_re, workspace_re, bat_307, monkeypatch):
    """URL có hạn không được lưu ở đâu cả — sinh mới mỗi lượt xem, nên hết hạn không làm
    chết link nào."""
    from portal.core import storage

    dem = {"n": 0}

    async def _presign(self, khoa, *, ttl_sec=300):
        dem["n"] += 1
        return f"https://kho.noi-bo/{khoa}?sig={dem['n']}"

    monkeypatch.setattr(storage.KhoTep, "presign_get", _presign)

    khoa = f"tenants/{workspace_re}/kb-bds/abc/a.jpg"
    a = await client_re.get("/api/v1/realestate/files", params={"key": khoa}, follow_redirects=False)
    b = await client_re.get("/api/v1/realestate/files", params={"key": khoa}, follow_redirects=False)
    assert a.headers["location"] != b.headers["location"]


async def test_307_van_chan_khoa_cua_tenant_khac(client_re, workspace_re, bat_307):
    """Phép kiểm tiền tố là dòng quan trọng nhất của route — nó phải chạy TRƯỚC nhánh 307,
    không thì bật cờ là mở đường đọc tệp của khách khác."""
    r = await client_re.get(
        "/api/v1/realestate/files", params={"key": "tenants/tenant-khac/kb-bds/a.jpg"}, follow_redirects=False
    )
    assert r.status_code == 404


async def test_mot_doi_tuong_kho_cho_ca_tien_trinh(monkeypatch):
    """Tab Media nạp tới 42 ảnh mỗi lần mở — dựng client mới mỗi request là 42 lần bắt tay."""
    from portal.core import storage

    storage.kho_tep_dung_chung.cache_clear()
    try:
        assert storage.kho_tep_dung_chung() is storage.kho_tep_dung_chung()
    finally:
        storage.kho_tep_dung_chung.cache_clear()
