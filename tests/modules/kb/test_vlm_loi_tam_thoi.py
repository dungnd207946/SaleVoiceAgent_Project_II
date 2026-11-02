"""429 và 5xx là «thử lại đi», ảnh vỡ là «thôi bỏ». Gộp hai thứ đó làm một là hoặc
mất mô tả vì một cơn nghẽn thoáng qua, hoặc retry vô ích một ảnh hỏng vĩnh viễn."""

import httpx
import pytest

from portal.modules.kb.clients.vlm import VlmClient
from portal.modules.kb.contracts import TemporaryError


def _client(handler) -> VlmClient:
    c = VlmClient(base_url="https://vlm.test", api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


@pytest.mark.parametrize("ma", [429, 500, 503])
async def test_ma_tam_thoi_nem_TemporaryError(ma):
    c = _client(lambda req: httpx.Response(ma, json={"error": "busy"}))
    with pytest.raises(TemporaryError):
        await c.caption("https://x/a.jpg", profile="caption")


async def test_400_van_la_loi_thuong():
    c = _client(lambda req: httpx.Response(400, json={"error": "file too large"}))
    with pytest.raises(httpx.HTTPStatusError):
        await c.caption("https://x/a.jpg", profile="caption")


async def test_timeout_cung_la_tam_thoi():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("quá hạn", request=req)

    c = _client(handler)
    with pytest.raises(TemporaryError):
        await c.caption("https://x/a.jpg", profile="caption")


def test_bo_fence_model_tu_boc():
    """qwen-vl-max bọc mỗi trang OCR trong ```markdown … ``` — 4 dòng rác mỗi tài liệu
    2 trang, đo trên dữ liệu thật 2026-08-25."""
    from portal.modules.kb.clients.vlm import _bo_fence

    assert _bo_fence("```markdown\n# Tiêu đề\nnội dung\n```") == "# Tiêu đề\nnội dung"
    assert _bo_fence("# Không có fence\nnội dung") == "# Không có fence\nnội dung"
    assert _bo_fence("```\n| a | b |\n```") == "| a | b |"
    assert _bo_fence("") == ""
