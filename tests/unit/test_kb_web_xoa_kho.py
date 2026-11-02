"""Xoá cứng workspace phải xoá cả kho dữ liệu ngoài `<tenant>_public_web` — mã workspace được tái
dùng, kho sót lại là workspace sau thừa hưởng hồ sơ của khách trước."""

from portal.modules.kb.index import store
from portal.modules.kb.ops import collections


class _Store:
    xoa: list[str] = []

    def __init__(self, **_):
        pass

    async def drop_collection(self, name):
        _Store.xoa.append(name)


async def test_xoa_workspace_xoa_ca_kho_du_lieu_ngoai(monkeypatch):
    monkeypatch.setattr(store, "QdrantStore", _Store)
    _Store.xoa = []
    ten = await collections.xoa_kho_cua_workspace("ws_x")
    assert "ws_x_public_web" in ten and "ws_x_public_web" in _Store.xoa
