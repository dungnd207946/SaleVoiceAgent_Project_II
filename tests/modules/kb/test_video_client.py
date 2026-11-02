"""Chuẩn hoá URL là chỗ dễ hỏng nhất: DB lưu dạng /embed/ (frontend nhúng iframe),
Gemini chỉ nhận dạng watch?v=. Gửi thẳng dạng nhúng là hỏng câm."""

import httpx
import pytest

from portal.modules.kb.clients.video import VideoClient, youtube_watch_url


@pytest.mark.parametrize(
    "vao,ra",
    [
        ("https://www.youtube.com/embed/fSVkxmsjAEw?si=Wq2tvB", "https://www.youtube.com/watch?v=fSVkxmsjAEw"),
        ("https://www.youtube.com/watch?v=fSVkxmsjAEw", "https://www.youtube.com/watch?v=fSVkxmsjAEw"),
        ("https://youtu.be/fSVkxmsjAEw", "https://www.youtube.com/watch?v=fSVkxmsjAEw"),
        ("https://cdn.test/clip.mp4", None),
        ("", None),
    ],
)
def test_chuan_hoa_url_youtube(vao, ra):
    assert youtube_watch_url(vao) == ra


async def test_describe_gui_file_uri_da_chuan_hoa():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        ghi["body"] = json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Video tiến độ."}]}}]})

    c = VideoClient(api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ra = await c.describe("https://www.youtube.com/embed/fSVkxmsjAEw?si=X")

    assert ra == "Video tiến độ."
    assert "watch?v=fSVkxmsjAEw" in str(ghi["body"]), "gửi dạng nhúng thay vì dạng xem"


async def test_api_key_rong_thi_raise_luc_dung():
    with pytest.raises(ValueError, match="KB_GEMINI_API_KEY"):
        VideoClient(api_key="")


async def test_describe_chi_nhan_youtube_nguon_tep_phai_di_duong_khac():
    """`describe` là cửa của nhánh YouTube (gửi `file_uri`, không tải byte nào). Nguồn
    tệp mp4/mov đi qua `describe_bytes` — Files API, ba lượt gọi và một vòng chờ.

    Ném thay vì tự chuyển nhánh: `describe` không có byte trong tay, và tự đi tải là
    giấu một lượt tải hàng chục MB sau một hàm trông như chỉ gọi một API.
    """
    c = VideoClient(api_key="k")
    with pytest.raises(ValueError, match="describe_bytes"):
        await c.describe("https://cdn.test/clip.mp4")


async def test_thieu_candidates_thi_raise_ro_rang():
    """`candidates` vắng mặt không được lặng lẽ trở thành chuỗi rỗng — mô tả rỗng ghi
    vào `media.caption` trông y hệt "chưa chạy job", không ai phân biệt được."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"khong_co_candidates": True})

    c = VideoClient(api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="candidates"):
        await c.describe("https://youtu.be/fSVkxmsjAEw")


async def test_text_rong_thi_raise_ro_rang():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "   "}]}}]})

    c = VideoClient(api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="rỗng"):
        await c.describe("https://youtu.be/fSVkxmsjAEw")
