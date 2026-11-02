"""Ba đường HTTP của cửa Google.

Google được thay bằng `MockTransport` tiêm qua `monkeypatch` vào hàm module —
đây là chỗ DUY NHẤT trong bộ test dùng monkeypatch cho việc này, vì router
không có tham số `transport` để tiêm qua (và không nên có: một tham số chỉ
dành cho test nằm trên đường production là một cửa).
"""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from portal.core.auth import oauth_google as og

CLIENT_ID = "abc.apps.googleusercontent.com"

# Đích redirect của callback là một CHUỖI, không phải một route được type-check —
# xem cảnh báo ở `router.py`. Assert chuỗi-với-chuỗi (`== "/tao-workspace"`) chỉ
# so code với chính nó nên vẫn xanh khi FE không hề có route đó; đúng như vậy đã
# xảy ra một lần. Nên hằng dưới được đối chiếu với CÂY ROUTE THẬT của FE khi thư
# mục đó có mặt.
_ROUTE_TAO_WORKSPACE = "/tao-workspace-dau-tien"

# FE là repo riêng (xem SETUP-SAU-KHI-TACH-REPO.md) nên có thể vắng mặt trên CI
# của backend — khi vắng thì bỏ qua phép đối chiếu, KHÔNG làm đỏ bộ test.
_ROUTES_FE = Path(__file__).parents[3] / ".." / "frontend" / "src" / "routes"


@pytest.mark.skipif(not _ROUTES_FE.is_dir(), reason="repo FE không có mặt cạnh repo BE")
def test_route_tao_workspace_ton_tai_o_fe():
    """Chốt chặn ranh giới hai repo: đổi tên file route bên FE mà quên chuỗi ở
    `router.py` thì test này đỏ, thay vì người dùng nhận màn 404."""
    ten_file = _ROUTE_TAO_WORKSPACE.lstrip("/") + ".tsx"
    assert (_ROUTES_FE / ten_file).is_file(), (
        f"`router.py` redirect tới {_ROUTE_TAO_WORKSPACE} nhưng FE không có "
        f"`src/routes/{ten_file}` — người đăng nhập Google lần đầu sẽ rơi vào 404"
    )


@pytest.fixture(autouse=True)
def bat_google(monkeypatch):
    """`get_settings()` dựng một `Settings()` MỚI mỗi lần gọi (KHÔNG lru_cache),
    nên `monkeypatch.setenv` là đủ — không có `cache_clear()` nào để gọi. Cũng
    chính là lý do router đọc cấu hình mỗi lần thay vì giữ một biến module."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.thu.vn")


@pytest.fixture
async def don_sach(pool):
    yield
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.users WHERE email LIKE '%@cong.vn'")


def _claims_gia(monkeypatch, **ghi_de):
    """Thay `doi_code_lay_claims` — bước ⑦⑧ là lượt duy nhất đi ra ngoài."""
    m = {"sub": "104287", "email": "ai.do@cong.vn", "email_verified": True, "name": "Ai Đó"}
    m.update(ghi_de)

    async def gia(**_kw):
        return og.ClaimsGoogle(**m)

    monkeypatch.setattr("portal.modules.auth.router.oauth_google.doi_code_lay_claims", gia)


def _khang_dinh_cookie_state_da_xoa(r: httpx.Response) -> None:
    """Khẳng định `_thoat()` đã xoá cookie `odyssey_oauth_state` trên response.

    `_xoa_cookie_state` gọi `Response.delete_cookie(...)`, mà Starlette dựng
    thành `set_cookie(..., max_age=0, expires=0, ...)` — kiểm THẬT phát ra
    (đo bằng `starlette.responses.Response.delete_cookie` trực tiếp): header
    `Set-Cookie` cho cookie này luôn mang `Max-Age=0`. Bất biến "`_thoat()` chạy
    ở MỌI đường ra" trước đây chỉ được kiểm bằng mắt — đây là chỗ đo lại nó.

    Dùng `get_list` vì đường thành công đặt HAI `Set-Cookie` khác nhau
    (`odyssey_session` + `odyssey_oauth_state`) — `r.headers.get("set-cookie")`
    chỉ trả header ĐẦU, có thể bỏ sót cookie ta cần soi.
    """
    cac_cookie = [c for c in r.headers.get_list("set-cookie") if c.startswith("odyssey_oauth_state=")]
    assert cac_cookie, f"không thấy Set-Cookie nào cho odyssey_oauth_state trong: {r.headers.get_list('set-cookie')}"
    assert "Max-Age=0" in cac_cookie[0], f"cookie state không bị đánh dấu hết hạn: {cac_cookie[0]!r}"


async def test_providers_bao_google_dang_bat(app_client: httpx.AsyncClient):
    r = await app_client.get("/api/v1/auth/providers")
    assert r.status_code == 200
    assert r.json() == {"google": True}


async def test_providers_bao_tat_khi_thieu_cau_hinh(app_client: httpx.AsyncClient, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    r = await app_client.get("/api/v1/auth/providers")
    assert r.json() == {"google": False}


async def test_providers_khong_lo_client_id(app_client: httpx.AsyncClient):
    """Đường công khai CHỈ trả tên nhà cung cấp. Mỗi trường thêm vào là một thứ
    nói cho người chưa đăng nhập biết về hệ thống."""
    r = await app_client.get("/api/v1/auth/providers")
    assert set(r.json()) == {"google"}
    assert CLIENT_ID not in r.text


async def test_start_307_sang_google_va_cat_state(app_client: httpx.AsyncClient, redis_client):
    r = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 307
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == [CLIENT_ID]
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["https://portal.thu.vn/api/v1/auth/google/callback"]
    assert await redis_client.get(f"oauth:state:{q['state'][0]}") is not None


async def test_start_404_khi_tinh_nang_tat(app_client: httpx.AsyncClient, monkeypatch):
    """PHÉP CHẶN nằm ở đây, không ở /auth/providers — cái kia chỉ để FE khỏi vẽ
    một nút chết."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    r = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 403, "FEATURE_DISABLED — xem api/loi.py::tinh_nang_dang_tat"


async def test_callback_tinh_nang_tat_giua_luong_thi_302_khong_403(app_client: httpx.AsyncClient, monkeypatch):
    """Khác `/start`: tính-năng-tắt ở CALLBACK phải là `302 /login?loi=`, không
    phải 403 JSON — đây là điều hướng top-level từ Google giữa một luồng người
    dùng đã bắt đầu (gọi `/start` rồi Google mới tắt), không phải một lời gọi
    có chủ đích tới một đường không tồn tại. Cookie state cũng phải bị xoá.
    """
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")

    r = await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login?loi=DANG_KY_DANG_TAT"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")
    _khang_dinh_cookie_state_da_xoa(r)


async def test_callback_dat_cookie_va_ve_tao_workspace(
    app_client: httpx.AsyncClient, redis_client, monkeypatch, don_sach
):
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    r = await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == _ROUTE_TAO_WORKSPACE, "user mới có 0 workspace"
    assert "odyssey_session=" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"]
    # Đường THÀNH CÔNG cũng đi qua `_thoat()` — cookie state phải bị xoá NGAY
    # cả khi phiên vừa được tạo, không chỉ ở các nhánh lỗi.
    _khang_dinh_cookie_state_da_xoa(r)

    me = await app_client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ai.do@cong.vn"


async def test_callback_state_dung_lai_lan_hai_thi_hong(app_client: httpx.AsyncClient, monkeypatch, don_sach):
    """Chứng minh hàng Redis DÙNG-MỘT-LẦN: gọi lại callback với CÙNG `state` sau
    khi đã tiêu thì bị từ chối ở lượt thứ hai.

    ⚠ `_thoat()` ở router xoá cookie `odyssey_oauth_state` ở MỌI đường ra —
    kể cả đường THÀNH CÔNG của lượt gọi thứ nhất. Nên trước lượt gọi thứ hai,
    ta phải TỰ đặt lại cookie đó bằng tay (`app_client.cookies.set(...)`).
    Đây là CỐ Ý, không phải rác cần dọn: nó mô phỏng một kẻ tấn công đã có
    CẢ HAI mảnh (cookie lẫn `state`, ví dụ chặn được cả URL callback và giữ
    được cookie từ lượt trước) để chứng minh lớp phòng thủ THỨ HAI — hàng Redis
    dùng-một-lần — vẫn chặn được dù lớp thứ nhất (buộc cookie, canh ở
    `test_CSRF_*`) đã bị vượt qua. Không đặt lại cookie thì lượt gọi thứ hai bị
    chặn ngay ở phép kiểm cookie (thiếu cookie ⇒ `STATE_HET_HAN`) và KHÔNG BAO
    GIỜ chạm tới `r.getdel(...)` — test vẫn xanh nhưng không còn canh cái tên
    nó nói: đã tự đo được điều này (đổi `getdel` → `get` mà 13 test đều xanh,
    tức `state` dùng lại được suốt TTL, cho tới khi thêm dòng `cookies.set` này).

    KHÔNG chứng minh `GETDEL` atomic — hai lời gọi TUẦN TỰ như ở đây cũng đi
    qua được nếu đổi `GETDEL` thành `GET` rồi `DEL` hai lệnh rời nhau; bắt được
    cửa sổ đua thật giữa hai lệnh đó cần một test đua (hai coroutine cùng gọi
    callback đồng thời), cố ý KHÔNG viết ở đây — dễ flaky, và giá trị chứng
    minh thêm không lớn hơn việc đọc code (`r.getdel(...)` là MỘT lệnh Redis).
    """
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)

    # Cookie đã bị `_thoat()` xoá ở lượt trên (thành công). Đặt lại THỦ CÔNG để
    # lượt gọi thứ hai qua được phép kiểm cookie và thật sự chạm tới Redis —
    # xem đoạn "CỐ Ý" ở docstring trên.
    app_client.cookies.set("odyssey_oauth_state", state)

    r2 = await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"] == "/login?loi=STATE_HET_HAN"


async def test_callback_state_bia_dat_thi_hong(app_client: httpx.AsyncClient):
    r = await app_client.get("/api/v1/auth/google/callback?code=c&state=toi-tu-bia-ra", follow_redirects=False)
    assert r.headers["location"] == "/login?loi=STATE_HET_HAN"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")


async def test_CSRF_state_cua_ke_khac_khong_dung_duoc(app_client: httpx.AsyncClient, monkeypatch, don_sach):
    """Login-CSRF: `state` hợp lệ nhưng ĐẾN TỪ TRÌNH DUYỆT KHÁC phải bị từ chối.

    Kẻ tấn công gọi /start, đăng nhập Google bằng tài khoản của họ, rồi đưa nạn
    nhân URL callback kèm code+state của mình. Không có phép buộc cookie thì nạn
    nhân nhận cookie phiên của tài khoản kẻ tấn công.
    """
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    # Mô phỏng MỘT TRÌNH DUYỆT KHÁC: `state` còn hợp lệ trong Redis (kẻ tấn
    # công gọi /start thật), nhưng cookie đối chiếu KHÔNG có mặt ở trình duyệt
    # đang gọi callback — đúng cảnh nạn nhân bấm vào URL do kẻ tấn công đưa.
    app_client.cookies.delete("odyssey_oauth_state")

    r = await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login?loi=STATE_HET_HAN"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")


async def test_CSRF_state_cookie_lech_query_khong_dung_duoc(app_client: httpx.AsyncClient, monkeypatch, don_sach):
    """Biến thể khác của cùng lỗ: cookie CÓ mặt nhưng KHÔNG khớp `state` trên
    query — không chỉ ca thiếu cookie hoàn toàn mới bị chặn."""
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    # Xoá TRƯỚC khi đặt lại: `app_client.cookies.set(...)` một mình gửi CẢ HAI
    # cookie cùng tên (giá trị thật của `/start` + giá trị lệch này) — test vẫn
    # xanh nhờ Starlette lấy giá trị CUỐI, nhưng đó không phải kịch bản sạch
    # (một trình duyệt không gửi hai cookie cùng tên).
    app_client.cookies.delete("odyssey_oauth_state")
    app_client.cookies.set("odyssey_oauth_state", "state-cua-mot-luot-khac")

    r = await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login?loi=STATE_HET_HAN"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")


async def test_CSRF_hai_cookie_state_trung_ten_khong_dung_duoc(app_client: httpx.AsyncClient, monkeypatch, don_sach):
    """Cookie shadowing: HAI cookie `odyssey_oauth_state` cùng tên (một subdomain
    anh em bị chiếm đặt thêm một cookie `Domain=.…`) phải bị từ chối, không được
    để `request.cookies` (đã gộp trùng lặp) âm thầm chọn một cái tuỳ ý.

    Header `Cookie` đặt TRỰC TIẾP để mô phỏng đúng thứ trình duyệt gửi khi có
    hai cookie cùng tên (`request.cookies.get()`/`app_client.cookies.set()` đều
    không dựng được cảnh này — cả hai đi qua một dict đã gộp).

    ⚠ Giá trị THẬT (`state`, khớp query) cố ý đặt Ở CUỐI: Starlette gộp cookie
    trùng tên bằng "giá trị cuối thắng", nên nếu chỉ kiểm khớp/lệch (không đếm
    số lần xuất hiện) thì `request.cookies.get()` vẫn ra ĐÚNG `state` — phép so
    khớp/lệch coi đây là hợp lệ và ĐI QUA, dù có một cookie lạ đứng trước nó.
    Đặt giá trị thật ở cuối là để chứng minh đúng cái phép so khớp/lệch KHÔNG
    bắt được: chỉ phép ĐẾM (`_dem_cookie_state`) mới thấy có hai cookie và chặn.
    """
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    # Xoá cookie thật của jar: header `Cookie` bên dưới tự khai đủ cả hai giá
    # trị, jar không cần (và không nên) chèn thêm một bản thứ ba.
    app_client.cookies.delete("odyssey_oauth_state")

    r = await app_client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}",
        follow_redirects=False,
        headers={"Cookie": f"odyssey_oauth_state=cua-ke-tan-cong; odyssey_oauth_state={state}"},
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/login?loi=STATE_HET_HAN"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")


async def test_CSRF_hai_cookie_state_khoang_trang_truoc_dau_bang_khong_dung_duoc(
    app_client: httpx.AsyncClient, monkeypatch, don_sach
):
    """`_dem_cookie_state` phải đếm ĐÚNG thứ Starlette đếm — không chỉ đếm cái
    trông giống.

    Starlette (`cookie_parser`) tách tên bằng `chunk.split("=", 1)[0]` RỒI
    `.strip()`, nên header `odyssey_oauth_state ={state}` (khoảng trắng TRƯỚC
    dấu `=`) vẫn được NÓ tính là cookie `odyssey_oauth_state` — và vì dict
    ghi đè theo thứ tự, `request.cookies.get()` ra ĐÚNG `state` (chunk này đặt
    Ở CUỐI). Một phép đếm dùng `startswith(f"{TEN}=")` (không có khoảng trắng)
    sẽ KHÔNG đếm chunk này — chuỗi sau `.strip()` là `"odyssey_oauth_state ..."`
    (còn dấu cách), không phải `"odyssey_oauth_state=..."` — nên đếm ra 1, phép
    kiểm trùng lặp bỏ qua, và phép so khớp/lệch cũng qua vì giá trị khớp `state`.
    Không khai thác được qua trình duyệt thật (RFC 6265 §5.2 buộc trình duyệt
    cắt khoảng trắng quanh tên) nhưng một phép đếm phòng thủ phải đếm đúng thứ
    parser đếm.
    """
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    app_client.cookies.delete("odyssey_oauth_state")

    r = await app_client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}",
        follow_redirects=False,
        headers={"Cookie": f"odyssey_oauth_state=cua-ke-tan-cong; odyssey_oauth_state ={state}"},
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/login?loi=STATE_HET_HAN"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")


async def test_CSRF_hai_dong_header_cookie_khong_dung_duoc(app_client: httpx.AsyncClient, monkeypatch, don_sach):
    """`_dem_cookie_state` phải gộp MỌI dòng header `Cookie`, không chỉ dòng đầu.

    `request.cookies` (Starlette) dùng `headers.getlist("cookie")` rồi gộp toàn
    bộ theo thứ tự, last-wins. Phép đếm mà chỉ đọc `headers.get("cookie")` (một
    dòng) sẽ đếm ra 1 trên một request mang HAI DÒNG `Cookie` riêng biệt (khác
    với hai cookie trên CÙNG một dòng, đã canh ở test phía trên) — trong khi
    `request.cookies` đã gộp cả hai dòng đó.

    ⚠ Giá trị THẬT (`state`, khớp query) cố ý đặt ở DÒNG SAU: đã kiểm bằng mắt
    (và bằng script) TRƯỚC khi viết assertion — với `Request(scope)` giả có hai
    dòng `Cookie` [giả trước, thật sau], `request.cookies` trả về giá trị THẬT
    (last-wins đúng như dự đoán), còn `headers.get("cookie")` (một dòng) chỉ
    thấy dòng ĐẦU (giá trị giả). Nên nếu chỉ đọc một dòng: đếm ra 1 (qua cửa
    trùng lặp) VÀ phép so khớp/lệch cũng qua (vì `request.cookies` thật vẫn
    khớp `state`) — request đi lọt hoàn toàn. Đặt ngược lại (thật trước, giả
    sau) sẽ khiến phép so khớp/lệch tự bắt được nó vì lý do SAI, đúng cái bẫy
    đã vấp ở test phía trên.

    Không tới được qua trình duyệt HTTP/1.1 hôm nay (RFC 6265 buộc gộp một
    dòng), nhưng RFC 9113 §8.2.3 (HTTP/2) cho phép nhiều dòng — xem docstring
    `_dem_cookie_state`.
    """
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    app_client.cookies.delete("odyssey_oauth_state")

    r = await app_client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}",
        follow_redirects=False,
        headers=[
            ("Cookie", "odyssey_oauth_state=cua-ke-tan-cong"),
            ("Cookie", f"odyssey_oauth_state={state}"),
        ],
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/login?loi=STATE_HET_HAN"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")


async def test_callback_google_tu_choi_thi_ve_login_co_ma(app_client: httpx.AsyncClient, monkeypatch):
    async def no(**_kw):
        raise og.LoiGoogle("GOOGLE_TU_CHOI")

    monkeypatch.setattr("portal.modules.auth.router.oauth_google.doi_code_lay_claims", no)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]
    r = await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/login?loi=GOOGLE_TU_CHOI"


async def test_CUA_HAU_user_dinh_chi_khong_vao_duoc_bang_google(
    app_client: httpx.AsyncClient, pool, monkeypatch, don_sach
):
    """CỔNG QUAN TRỌNG NHẤT. Xem `dang_nhap_google._kiem_vao_duoc`."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_cg_dc', 'dc@cong.vn', 'argon2-gia', 'Đình Chỉ', 'suspended')"
        )
    _claims_gia(monkeypatch, email="dc@cong.vn")
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]
    r = await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/login?loi=TAI_KHOAN_DINH_CHI"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")
    # Nhánh `LoiGoogle` (khác nhánh feature-tắt/thành-công) cũng phải đi qua
    # `_thoat()` — đây là đường ra thứ ba được đo, không chỉ nhìn bằng mắt.
    _khang_dinh_cookie_state_da_xoa(r)
    assert (await app_client.get("/api/v1/me")).status_code == 401


async def test_callback_that_bai_khong_de_lai_hang_nao(app_client: httpx.AsyncClient, pool, monkeypatch, don_sach):
    """Phép kiểm giao dịch: bỏ `conn.transaction()` ở router thì test này đỏ."""
    _claims_gia(monkeypatch, email="ro.ri@cong.vn")

    # Nổ ở `ghi_identity`, tức SAU khi `tao_user_tu_google` đã chèn hàng users.
    # Đó là điều kiện để test này có nghĩa: nổ TRƯỚC khi tạo gì thì bảng rỗng dù
    # có giao dịch hay không, và test xanh mà chẳng chứng minh điều gì.
    async def no_sau_khi_tao_user(*a, **kw):
        raise RuntimeError("vỡ giữa chừng")

    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]
    monkeypatch.setattr("portal.modules.auth.dang_nhap_google.repo.ghi_identity", no_sau_khi_tao_user)
    with pytest.raises(RuntimeError):
        await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email = 'ro.ri@cong.vn'") == 0
