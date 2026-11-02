"""Client VLM — MockTransport. Canh việc prompt lấy đúng từ prompts.yaml."""

import json

import httpx
import pytest

from portal.modules.kb.clients.vlm import VlmClient


def _client(handler) -> VlmClient:
    c = VlmClient(base_url="https://vlm.test/v1", api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def _ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


async def test_caption_dung_prompt_cua_profile():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        ghi["body"] = json.loads(req.content)
        return _ok("Toà chung cư cao tầng bên hồ.")

    ra = await _client(handler).caption("https://cdn.test/a.jpg", profile="caption")
    assert ra == "Toà chung cư cao tầng bên hồ."
    assert ghi["body"]["model"] == "qwen-vl-max"
    noi_dung = str(ghi["body"]["messages"])
    assert "1-2 câu" in noi_dung, "không dùng prompt của profile caption"
    assert "https://cdn.test/a.jpg" in noi_dung


async def test_caption_profile_khong_ton_tai_thi_raise():
    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng khi profile sai")

    with pytest.raises(KeyError):
        await _client(handler).caption("https://cdn.test/a.jpg", profile="khong_co")


async def test_api_key_rong_thi_raise_luc_dung():
    with pytest.raises(ValueError, match="KB_VLM_API_KEY"):
        VlmClient(base_url="https://vlm.test/v1", api_key="")


async def test_ocr_page_gui_anh_dang_data_uri():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        ghi["body"] = json.loads(req.content)
        return _ok("## Chương 1")

    ra = await _client(handler).ocr_page(b"\x89PNG_gia_lap")
    assert ra == "## Chương 1"
    assert "data:image/png;base64," in str(ghi["body"]["messages"])


async def test_thieu_choices_thi_raise_ro_rang():
    """`choices` vắng mặt không được lặng lẽ trở thành chuỗi rỗng — caption rỗng ghi
    vào DB trông y hệt "mô hình chưa chạy", không ai phân biệt được."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"khong_co_choices": True})

    with pytest.raises(ValueError, match="choices"):
        await _client(handler).caption("https://cdn.test/a.jpg", profile="caption")


async def test_content_rong_thi_raise_ro_rang():
    def handler(req: httpx.Request) -> httpx.Response:
        return _ok("   ")

    with pytest.raises(ValueError, match="rỗng"):
        await _client(handler).caption("https://cdn.test/a.jpg", profile="caption")
