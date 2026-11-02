"""Tài liệu Swagger của gateway. KHÔNG cần Postgres/Redis.

Cùng lý lẽ `tests/api/test_app.py`: hai route khai `require(None)` và spec sinh
từ một file JSON, nên ASGITransport không chạy lifespan là đủ.
"""

import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

from portal.api.app import create_app
from portal.modules.enrollment import gateway_docs
from tests.conftest import liet_ke_route

WS = "wss://vd.example.com"

DUONG_TRANG = "/api/v1/agent/gateway/docs"
DUONG_SPEC = "/api/v1/agent/gateway/openapi.json"


@pytest.fixture
def cat():
    return gateway_docs._catalog()


@pytest.fixture
def spec():
    return gateway_docs.spec(WS)


# ─── Artifact phải ĐI THEO app khi đóng gói ──────────────────────────────────
#
# Nhóm này tồn tại vì 15 bài còn lại của file đều XANH trong khi UAT trả 500.
# Bản đầu đặt artifact ở `contracts/` và đọc bằng `Path(__file__).parents[4]`:
# đúng trong repo, không tồn tại trong image — `Dockerfile` build bằng
# `uv sync --no-editable` rồi runtime stage chỉ copy `.venv`, `alembic.ini` và
# `migrations`. Không bài nào ở đây chạm tới việc đóng gói nên không bài nào đỏ.


def test_artifact_nam_trong_package_khong_o_contracts():
    """Rẻ và bắt đúng lớp lỗi: ra ngoài `src/portal` là ra ngoài wheel."""
    duong = Path(str(gateway_docs.resources.files(gateway_docs._GOI_TAI_NGUYEN)))

    assert "src/portal/modules/enrollment/tai_nguyen" in duong.as_posix()


@pytest.mark.skipif(shutil.which("uv") is None, reason="cần uv để dựng wheel")
def test_artifact_thuc_su_co_trong_wheel(tmp_path):
    """Dựng wheel thật rồi soi — thứ duy nhất chứng minh nó tới được production.

    Bài trên kiểm vị trí trong cây nguồn, bài này kiểm KẾT QUẢ đóng gói: một
    thay đổi cấu hình build (exclude, packages, force-include) làm rơi tệp khỏi
    wheel mà không dịch chuyển nó trong repo, và chỉ bài này thấy.
    """
    goc = Path(__file__).resolve().parents[3]
    r = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(tmp_path)],
        cwd=goc,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stderr

    whl = next(tmp_path.glob("*.whl"))
    trong_wheel = zipfile.ZipFile(whl).namelist()

    assert f"portal/modules/enrollment/tai_nguyen/{gateway_docs._TEN_ARTIFACT}" in trong_wheel


# ─── Route ───────────────────────────────────────────────────────────────────


def test_hai_route_dang_ky_va_an_khoi_docs_cua_portal():
    """`include_in_schema=False`: spec chung của portal là bề mặt nội bộ, tài
    liệu gateway không thuộc đó — nó có spec riêng."""
    duong = {r.path: r for _, r in liet_ke_route(create_app())}

    assert "/agent/gateway/docs" in duong
    assert "/agent/gateway/openapi.json" in duong
    assert duong["/agent/gateway/docs"].include_in_schema is False
    assert duong["/agent/gateway/openapi.json"].include_in_schema is False


async def test_hai_route_tra_200_khong_can_phien():
    """Người đọc là dev bên khách — họ có API key, không có phiên portal."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        trang = await c.get(DUONG_TRANG)
        spec = await c.get(DUONG_SPEC)

    assert trang.status_code == 200
    assert trang.headers["content-type"].startswith("text/html")
    assert spec.status_code == 200
    assert spec.json()["openapi"] == "3.1.0"


async def test_spec_khai_charset_utf8():
    """Thiếu `charset` là mojibake trên trình duyệt, đã bị báo lỗi thật trên UAT.

    Starlette chỉ tự thêm charset cho media type `text/*`, nên `JSONResponse`
    gửi `application/json` trần; `Content-Disposition: inline` đẩy trình duyệt
    sang chế độ hiển thị-tệp và ở đó nó sniff theo locale. Byte vẫn đúng UTF-8 —
    chỉ khai báo thiếu — nên mọi bài đọc `.json()` đều xanh (httpx và JS đều
    decode UTF-8 theo spec bất kể header). Chỉ bài này thấy.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        r = await c.get(DUONG_SPEC)

    assert "charset=utf-8" in r.headers["content-type"].lower()


async def test_spec_giu_dau_tieng_viet_khi_doc_bang_utf8():
    """Vế còn lại: header đúng mà thân bị escape hoặc encode sai thì vẫn hỏng."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        r = await c.get(DUONG_SPEC)

    assert "Giao thức WebSocket" in r.content.decode("utf-8")


async def test_spec_mang_ten_tep_khi_tai_ve():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        r = await c.get(DUONG_SPEC)

    assert gateway_docs.ten_tep_spec() in r.headers["content-disposition"]


# ─── Spec toàn vẹn ───────────────────────────────────────────────────────────


def _moi_ref(node):
    if isinstance(node, dict):
        if "$ref" in node:
            yield node["$ref"]
        for v in node.values():
            yield from _moi_ref(v)
    elif isinstance(node, list):
        for v in node:
            yield from _moi_ref(v)


def test_moi_ref_co_dich(spec):
    """Một `$ref` không đích render thành lỗi đỏ giữa trang, không phải 500 —
    nên nó phải đỏ ở đây."""
    co = set(spec["components"]["schemas"])
    thieu = {r.rsplit("/", 1)[-1] for r in _moi_ref(spec)} - co

    assert thieu == set()


def test_hai_vong_lap_sinh_event_khong_lech_nhau(spec, cat):
    """Canh `spec()`, KHÔNG canh artifact.

    Bản đầu của test này khẳng định "thêm event vào artifact mà quên nhánh
    `oneOf` thì đỏ" — sai, và mutation test chứng minh: `spec()` dựng schema và
    nhánh `oneOf` từ cùng một dict nên hai vế không thể lệch, thêm event vào
    artifact là tự động có cả hai. Nó chỉ đỏ khi ai đó sửa MỘT trong hai vòng
    lặp trong `spec()` (thêm filter, đổi quy ước đặt tên) mà không sửa vòng kia.
    """
    for kenh, ten_schema in (("chat", "ChatEvent"), ("voice", "VoiceEvent")):
        mong_doi = {f"Event_{kenh}_{k}" for k in cat["events"][kenh]}
        co_schema = mong_doi & set(spec["components"]["schemas"])
        trong_oneof = {r.rsplit("/", 1)[-1] for r in _moi_ref(spec["components"]["schemas"][ten_schema])}

        assert co_schema == mong_doi, kenh
        assert trong_oneof == mong_doi, kenh


def test_moi_tool_render_duoc_co_schema_result(spec, cat):
    """`tools.rendered` là danh sách tool client phải dựng card. Tên trong đó mà
    không có `ToolResult_*` là hứa một schema không tồn tại."""
    for ten in cat["tools"]["rendered"]:
        assert f"ToolResult_{ten}" in spec["components"]["schemas"], ten


def test_moi_schema_result_nam_trong_render_duoc(cat):
    """Chiều ngược của bài trên. `_intro()` nói "Chỉ {rendered} có schema result
    để dựng card" — một tool có mặt ở `tool_results` mà vắng ở `rendered` làm
    câu đó nói dối, và bài trên (chỉ xét một chiều) không bắt được việc đó."""
    for ten in cat["tool_results"]:
        assert ten in cat["tools"]["rendered"], ten


def _nhanh_media(spec) -> list[dict]:
    return spec["components"]["schemas"]["MediaItem"]["oneOf"]


def test_media_item_co_du_ba_kind(spec):
    """Chỗ tài liệu markdown cũ lệch: nó khai `image`/`video`, thiếu `tour`.

    Từng có `kind: "file"` cho video không phải YouTube (bản vá chiều 25/08), đổi
    sang biến thể `url` của `video` tối cùng ngày — nên `file` KHÔNG được quay
    lại đây; artifact khai nó là dạy client một thẻ agent không còn phát.
    """
    kinds = {n["properties"]["kind"]["const"] for n in _nhanh_media(spec)}

    assert kinds == {"image", "video", "tour"}
    assert "file" not in kinds


def test_video_co_hai_bien_the_youtube_va_khong(spec):
    """`video` là kind DUY NHẤT có hai nhánh, phân biệt bằng `video_id` có/không.

    Client đòi `video_id` mới render sẽ bỏ im lặng biến thể kia — đó là 38/93
    video của một tenant thật đã vô hình. Nên hai nhánh phải cùng có mặt ở đây,
    và `video_id` không được là bắt buộc của cả hai.
    """
    video = [n for n in _nhanh_media(spec) if n["properties"]["kind"]["const"] == "video"]

    assert len(video) == 2
    co_id = [n for n in video if "video_id" in n["properties"]]
    khong_id = [n for n in video if "video_id" not in n["properties"]]
    assert len(co_id) == 1 and len(khong_id) == 1
    assert "url" in khong_id[0]["properties"]
    # Chỉ nhánh Drive mang player nhúng được; thiếu nó thì lightbox không dựng được.
    assert "embed_url" in khong_id[0]["properties"]


def test_caption_o_title_voi_video_o_label_voi_con_lai(spec):
    """Bất đối xứng thật trong payload, không phải lỗi chép. Client đọc `label`
    cho mọi phần tử sẽ mất caption của đúng video."""
    for n in _nhanh_media(spec):
        kind, truong = n["properties"]["kind"]["const"], set(n["properties"])
        if kind == "video":
            assert "title" in truong and "label" not in truong, n["title"]
        else:
            assert "label" in truong and "title" not in truong, kind


def test_tool_done_khai_result_la_chuoi_chua_json(spec):
    """Cái bẫy lớn nhất của kênh chat. Khai `object` cho dễ đọc là dạy client
    quên `JSON.parse`."""
    result = spec["components"]["schemas"]["Event_chat_tool_done"]["properties"]["result"]

    assert result["type"] == "string"
    assert result["contentMediaType"] == "application/json"
    assert "contentSchema" in result


def test_tool_done_cua_voice_khong_co_result(spec):
    """Khác kênh chat, và đây là chỗ một client dùng chung code parse sẽ hỏng."""
    assert "result" not in spec["components"]["schemas"]["Event_voice_tool_done"]["properties"]


# ─── kb_search ───────────────────────────────────────────────────────────────


def test_tool_results_co_kb_search():
    """kb_search trả `items` khi câu trả lời lấy từ một tài liệu có ảnh. Không khai ở
    đây thì dev bên thứ ba đọc đúng hợp đồng vẫn không render ảnh nào."""
    import json
    from importlib import resources

    d = json.loads(
        resources.files("portal.modules.enrollment.tai_nguyen")
        .joinpath("gateway-protocol.json")
        .read_text(encoding="utf-8")
    )
    assert "kb_search" in d["tool_results"]


def test_media_item_anh_co_truong_index():
    import json
    from importlib import resources

    d = json.loads(
        resources.files("portal.modules.enrollment.tai_nguyen")
        .joinpath("gateway-protocol.json")
        .read_text(encoding="utf-8")
    )
    assert "index" in json.dumps(d["tool_results"]["kb_search"], ensure_ascii=False)


def test_kb_search_co_hai_hinh_dang(spec):
    """Không có ảnh nguồn ⇒ result là CHUỖI TRẦN, không phải luôn object. Khai
    một `type: object` duy nhất dạy client parse sai chính trường hợp phổ biến
    nhất (câu trả lời không kèm ảnh) — client sẽ crash hoặc bỏ qua nó."""
    result = spec["components"]["schemas"]["ToolResult_kb_search"]
    nhanh = result["oneOf"]

    kieu = {n["type"] for n in nhanh}
    assert kieu == {"string", "object"}

    (co_anh,) = (n for n in nhanh if n["type"] == "object")
    assert set(co_anh["required"]) == {"context", "items"}


def test_kb_search_anh_bat_buoc_label_giong_media_item(spec):
    """`label` của ảnh trong `kb_search` và của `MediaItem.image` là cùng một
    caption hiển thị — hai hợp đồng khác nhau cho cùng một phần tử là bẫy cho
    client dùng chung code render. Căn cho khớp: bắt buộc ở cả hai."""
    (co_anh,) = (n for n in spec["components"]["schemas"]["ToolResult_kb_search"]["oneOf"] if n["type"] == "object")
    anh = co_anh["properties"]["items"]["items"]

    assert "label" in anh["required"]


# ─── Trình bày ───────────────────────────────────────────────────────────────


def test_ws_base_di_vao_server_va_dan_nhap(spec):
    """URL đến từ `Settings`, không hardcode trong module — đổi domain là đổi
    một biến env."""
    assert spec["servers"] == [{"url": WS}]
    assert f"{WS}/v1/chat" in spec["info"]["description"]


def test_moi_endpoint_chi_noi_ve_chinh_no(spec):
    """Bản đầu để bảng đối chiếu chat-vs-voice trong description của
    `/v1/voice`; người đọc đang ở endpoint nào thì cần sự thật của endpoint đó."""
    assert "chat" not in spec["paths"]["/v1/voice"]["get"]["description"].lower()
    assert "voice" not in spec["paths"]["/v1/chat"]["get"]["description"].lower()


def test_dan_nhap_giai_thich_vi_sao_la_get():
    """Câu hỏi đầu tiên người đọc hỏi: thấy GET thì gửi query kiểu gì. Handshake
    WS là HTTP GET, còn query đi bằng TEXT frame — thiếu vế này thì trang mời
    người ta đi tìm một request body không tồn tại."""
    mo_ta = gateway_docs.spec(WS)["info"]["description"]

    assert "RFC 6455" in mo_ta
    assert "không đi bằng HTTP" in mo_ta


def test_trang_tat_try_it_out():
    """Handshake WS không gọi được bằng nút bấm. Để nút lại là mọi operation có
    một nút trả 426, và dev bên khách kết luận endpoint chết."""
    assert "supportedSubmitMethods: []" in gateway_docs.trang()


def test_trang_doc_spec_qua_duong_tuong_doi():
    """Module không phải biết tiền tố `/api/v1` mà `create_app()` gắn."""
    assert "url: 'openapi.json'" in gateway_docs.trang()
