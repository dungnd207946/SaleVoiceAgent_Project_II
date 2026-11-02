"""Client lipsync qua MockTransport — HTTP thật của httpx, không mạng.

Test quy trình (`tests/modules/nhan_vat`) thay CẢ lớp `LipsyncClient` bằng bản giả nên
không phủ chính cách client dựng request; bug đã gặp (e2e 2026-10-07): `gui_video` truyền
`headers` hai lần ⇒ `TypeError` ở mọi lần gửi video, mọi nhân vật kết thúc `LOI_HE_THONG`.
"""

import json

import httpx
import pytest

from portal.modules.nhan_vat import lipsync as lip_mod
from portal.modules.nhan_vat.lipsync import LipsyncClient, LoiLipsync
from portal.modules.nhan_vat.settings import NhanVatEnv


def _mock(monkeypatch, handler):
    goc = httpx.AsyncClient

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return goc(*a, **k)

    monkeypatch.setattr(lip_mod.httpx, "AsyncClient", factory)


def _client(token="T"):
    return LipsyncClient(NhanVatEnv(_env_file=None, lipsync_url="http://lip:8021/", models_token=token))


async def test_gui_video_mang_ca_token_lan_content_type(monkeypatch):
    nhan = {}

    def handler(req: httpx.Request):
        nhan.update(
            url=str(req.url),
            auth=req.headers.get("authorization"),
            ct=req.headers.get("content-type"),
            body=req.content,
        )
        return httpx.Response(200, json={"ok": True})

    _mock(monkeypatch, handler)
    await _client().gui_video("nv-abc", "tay", b"VID", "video/quicktime")
    assert nhan == {
        "url": "http://lip:8021/avatars/nv-abc/video/tay",
        "auth": "Bearer T",
        "ct": "video/quicktime",
        "body": b"VID",
    }


async def test_trang_thai_404_la_none_500_la_loi_tam(monkeypatch):
    tra = iter([httpx.Response(404, json={}), httpx.Response(500, text="x")])
    _mock(monkeypatch, lambda req: next(tra))
    c = _client(token="")
    assert await c.trang_thai("nv-abc") is None
    with pytest.raises(LoiLipsync):
        await c.trang_thai("nv-abc")


async def test_xoa_409_la_chua_xoa_duoc(monkeypatch):
    _mock(monkeypatch, lambda req: httpx.Response(409, json={}))
    assert await _client().xoa("nv-abc") is False


async def test_dung_gui_san_cat_dau(monkeypatch):
    nhan = []

    def handler(req: httpx.Request):
        nhan.append((req.url.path, json.loads(req.content)))
        return httpx.Response(202, json={})

    _mock(monkeypatch, handler)
    await _client().dung("nv-abc", 1.2)
    await _client().dung("nv-abc")
    assert nhan == [("/avatars/nv-abc/dung", {"cat_dau_s": 1.2}), ("/avatars/nv-abc/dung", {"cat_dau_s": 0.0})]


async def test_mat_ket_noi_thanh_loi_tam(monkeypatch):
    def hong(req):
        raise httpx.ConnectError("refused")

    _mock(monkeypatch, hong)
    with pytest.raises(LoiLipsync):
        await _client().dung("nv-abc")


async def test_khung_cho_tra_jpeg_404_la_chua_co_500_la_loi_tam(monkeypatch):
    nhan = []

    def handler(req: httpx.Request):
        nhan.append(str(req.url))
        return tra.pop(0)

    tra = [
        httpx.Response(200, content=b"JPG", headers={"Content-Type": "image/jpeg"}),
        httpx.Response(404, json={}),
        httpx.Response(500, text="x"),
    ]
    _mock(monkeypatch, handler)
    c = _client()
    assert await c.khung_cho("nv-abc") == b"JPG"
    assert nhan == ["http://lip:8021/avatars/nv-abc/khung_cho.jpg"]
    assert await c.khung_cho("nv-abc") is None  # service bản cũ / chưa dựng lần không-tay nào
    with pytest.raises(LoiLipsync):
        await c.khung_cho("nv-abc")
