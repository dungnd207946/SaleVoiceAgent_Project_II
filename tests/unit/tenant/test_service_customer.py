import json
import types

from noble_agent.data import media_data
from noble_agent.data.providers.base import ESCALATE_SIGNAL


class _FakePoint:
    def __init__(self, payload):
        self.payload = payload


def _load_tool():
    # import module → decorator self-registers; return the executor fn
    import importlib
    mod = importlib.import_module("noble_agent.tenants.noble.tools.service_customer")
    return importlib.reload(mod)


def _fake_customer(project_interest=""):
    return types.SimpleNamespace(project_interest=project_interest)


def _patch_scroll(monkeypatch, points, *, raise_exc=None):
    """Patch qdrant_store._get_client with a fake that CAPTURES scroll() kwargs
    on `.calls` (list of kwargs dicts), so tests can pin collection/filter."""
    from noble_agent.agent.rag import qdrant_store

    class _Client:
        def __init__(self):
            self.calls = []

        async def scroll(self, **kwargs):
            self.calls.append(kwargs)
            if raise_exc:
                raise raise_exc
            return list(points), None

    client = _Client()
    monkeypatch.setattr(qdrant_store, "_get_client", lambda: client)
    return client


_CSBH_PAYLOAD = {
    "project_id": "VGRC",
    "category": "csbh",
    "content_type": "image",
    "caption": "Chính sách ưu đãi: thanh toán sớm 7.5%.",
    "media_url": "https://nbx-sales-dev.noble.vn/img/real/proj/qc__csbh.jpg",
    "thumb_url": "https://s3/thumb.webp",
    "content_hash": "abc",
}


async def test_csbh_present_returns_context_and_items(monkeypatch):
    _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is True
    assert "thanh toán sớm 7.5%" in out["context"]
    assert out["count"] == 1
    assert out["items"][0]["kind"] == "image"
    assert out["items"][0]["url"] == _CSBH_PAYLOAD["media_url"]
    # caption must NOT ride along on the media item — it lives only in context
    assert "label" not in out["items"][0]
    assert "title" not in out["items"][0]
    assert _CSBH_PAYLOAD["caption"] not in json.dumps(out["items"], ensure_ascii=False)


async def test_no_csbh_returns_handoff_with_escalate_signal(monkeypatch):
    _patch_scroll(monkeypatch, [])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is False
    assert out["message"] == "Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ"
    assert ESCALATE_SIGNAL in json.dumps(out, ensure_ascii=False)


async def test_qdrant_error_degrades_to_handoff(monkeypatch):
    _patch_scroll(monkeypatch, [], raise_exc=RuntimeError("qdrant down"))
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is False
    assert ESCALATE_SIGNAL in json.dumps(out, ensure_ascii=False)


async def test_missing_code_and_no_interest_is_handoff(monkeypatch):
    _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({}, customer=_fake_customer(project_interest=""), session_id="s1"))
    assert out["ok"] is False


async def test_defaults_to_customer_project_interest(monkeypatch):
    _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({}, customer=_fake_customer(project_interest="VGRC"), session_id="s1"))
    assert out["ok"] is True


async def test_caption_present_but_no_renderable_media(monkeypatch):
    payload = dict(_CSBH_PAYLOAD, media_url="", thumb_url="", content_type="pdf")
    _patch_scroll(monkeypatch, [_FakePoint(payload)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is True
    assert out["items"] == []
    assert "Chính sách ưu đãi" in out["context"]


async def test_scroll_uses_expected_collection_and_filter(monkeypatch):
    client = _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is True

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["collection_name"] == "media_v3"

    filt = call["scroll_filter"]
    pairs = {(cond.key, cond.match.value) for cond in filt.must}
    assert ("project_id", "VGRC") in pairs
    assert ("category", "csbh") in pairs


async def test_map_items_failure_degrades_gracefully(monkeypatch):
    _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()

    def _raise(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(media_data, "_map_items", _raise)
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is True
    assert out["items"] == []
    assert "thanh toán sớm 7.5%" in out["context"]
