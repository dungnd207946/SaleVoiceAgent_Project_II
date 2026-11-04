"""Đo tiêu thụ embed (contract §2.1 ``component='embed'``).

Lỗ hổng đã bịt: contract khai `component='embed'` + `purpose='embed'` từ đầu
nhưng KHÔNG call site nào ghi, nên chi phí vector hoá câu hỏi (mỗi `kb_search`,
mỗi `send_media`) vô hình. Tệ hơn là im lặng: Portal dựng một dòng bảng giá cho
`embed` rồi thấy vĩnh viễn 0 và kết luận nó miễn phí.
"""

from types import SimpleNamespace

import httpx
import pytest

from noble_agent.billing import context
from noble_agent.billing.meter import UsageMeter
from noble_agent.data import embed_client


def _settings(**over):
    base = dict(
        embed_backend="gemini",
        embed_model="gemini-embedding-001",
        embed_sparse_model="Qdrant/bm25",
        embed_dim=768,
        embed_timeout=5.0,
        embed_service_url="http://embed.test/embed",
        gemini_api_key="k",
    )
    base.update(over)
    return SimpleNamespace(**base)


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


class _FakeClient:
    """Quack như httpx.AsyncClient trên đúng đường embed_client chạm."""

    def __init__(self, resp, **_kw):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, *_a, **_kw):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def _patch_http(monkeypatch, resp):
    monkeypatch.setattr(embed_client.httpx, "AsyncClient", lambda **kw: _FakeClient(resp, **kw))


def _patch_settings(monkeypatch, **over):
    monkeypatch.setattr(embed_client, "get_settings", lambda: _settings(**over))


async def test_gemini_dense_bills_chars_in_text_units():
    """`text_units` = tổng KÝ TỰ đem embed (cơ sở tính tiền — câu 500 ký tự tốn
    hơn câu 10 ký tự); `units` = số lời gọi, thống nhất với mọi component khác."""
    m = UsageMeter(session_id="s1", channel="chat")
    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp)
        _patch_http(mp, _FakeResp({"embeddings": [{"values": [0.1]}, {"values": [0.2]}]}))
        with context.use_meter(m):
            await embed_client.embed_dense(["ab", "cde"], side="query")

    _seq, rows = m.drain()
    assert len(rows) == 1
    r = rows[0]
    assert r.component == "embed"
    assert r.purpose == "embed"
    assert r.provider == "gemini"
    assert r.model == "gemini-embedding-001"
    assert r.units == 1
    assert r.text_units == 5  # "ab" + "cde"
    assert r.wall_ms > 0


async def test_paid_dense_and_local_sparse_stay_on_separate_rows():
    """Bất biến quan trọng nhất của thay đổi này.

    Nhánh dense đi API TRẢ PHÍ; nhánh sparse chạy fastembed trên CPU của ta và
    không tốn đồng nào cho provider. Khoá gộp của meter là
    `(component, purpose, provider, model)` — nếu hai nhánh dùng cùng cặp
    `(provider, model)` thì chúng cộng vào MỘT dòng và Portal không còn cách nào
    tách thang giá. Đây chính là lý do embed đi đường sự kiện chứ không dùng
    `add_audio` (vốn chỉ khoá theo `(component, purpose)`).
    """
    m = UsageMeter(session_id="s1", channel="chat")

    class _Vec:
        indices = [1, 2]
        values = [0.5, 0.5]

    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp)
        _patch_http(mp, _FakeResp({"embeddings": [{"values": [0.1]}]}))
        mp.setattr(embed_client, "_load_sparse", lambda _n: SimpleNamespace(embed=lambda ts: [_Vec()]))
        with context.use_meter(m):
            await embed_client.embed_dense(["xin chào"], side="query")
            await embed_client.embed_sparse(["xin chào"], side="query")

    _seq, rows = m.drain()
    by_provider = {r.provider: r for r in rows}
    assert set(by_provider) == {"gemini", "fastembed"}
    assert by_provider["gemini"].units == 1
    assert by_provider["gemini"].text_units == len("xin chào")
    assert by_provider["fastembed"].units == 1
    assert by_provider["fastembed"].text_units == len("xin chào")
    assert by_provider["fastembed"].model == "Qdrant/bm25"


async def test_service_kinds_are_three_distinct_rows():
    """dense / sparse / visual_text đều qua `_service_post` với cùng
    provider='service'. `kind` phải đi vào cột `model`, nếu không cả ba gộp một
    dòng và giá SigLIP2 bị trộn với giá BM25."""
    m = UsageMeter(session_id="s1", channel="chat")
    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp, embed_backend="service")
        _patch_http(mp, _FakeResp({"embeddings": [[0.1]], "sparse": [{"indices": [], "values": []}]}))
        with context.use_meter(m):
            await embed_client.embed_dense(["q"], side="query")
            await embed_client.embed_sparse(["q"], side="query")
            await embed_client.embed_visual_text(["q"])

    _seq, rows = m.drain()
    models = {r.model for r in rows if r.provider == "service"}
    assert models == {"dense", "sparse", "visual_text"}
    assert all(r.units == 1 for r in rows)


async def test_a_failed_embed_records_wall_ms_but_bills_zero_text_units():
    """Lời gọi lỗi đã tiêu giá vốn thật (thời gian, kết nối) nên `wall_ms` phải
    được ghi và `units` vẫn đếm lời gọi; nhưng khách KHÔNG trả tiền cho lỗi của
    ta, nên `text_units`=0 — cơ sở tính tiền của embed. Dấu hiệu lỗi trong bảng:
    `wall_ms > 0` mà `text_units = 0`."""
    m = UsageMeter(session_id="s1", channel="chat")
    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp)
        _patch_http(mp, httpx.ConnectError("embed service down"))
        with context.use_meter(m), pytest.raises(httpx.HTTPError):
            await embed_client.embed_dense(["a"], side="query")

    _seq, rows = m.drain()
    assert len(rows) == 1
    assert rows[0].units == 1
    assert rows[0].text_units == 0
    assert rows[0].wall_ms > 0


async def test_repeated_embeds_in_one_turn_are_summed_not_duplicated():
    m = UsageMeter(session_id="s1", channel="chat")
    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp)
        _patch_http(mp, _FakeResp({"embeddings": [{"values": [0.1]}]}))
        with context.use_meter(m):
            for _ in range(3):
                await embed_client.embed_dense(["q"], side="query")

    _seq, rows = m.drain()
    assert len(rows) == 1  # gộp theo (component, purpose, provider, model)
    assert rows[0].units == 3  # 3 lời gọi
    assert rows[0].text_units == 3  # 3 × "q"


async def test_embed_row_carries_the_turn_index():
    """embed phát sinh BÊN TRONG một lượt (qua `kb_search`), nên nó không thuộc
    `_SESSION_SCOPED` và phải mang `turn_idx` để truy được lượt nào tốn."""
    m = UsageMeter(session_id="s1", channel="chat")
    m.turn_idx = 4
    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp)
        _patch_http(mp, _FakeResp({"embeddings": [{"values": [0.1]}]}))
        with context.use_meter(m):
            await embed_client.embed_dense(["q"], side="query")

    _seq, rows = m.drain()
    assert rows[0].turn_idx == 4


async def test_no_meter_means_no_crash_and_no_row():
    """Đường ingest/offline gọi embed ngoài phiên, và cờ billing mặc định TẮT.
    Cả hai đường phải chạy y như cũ — đo lường không được là điều kiện để
    truy vấn tri thức hoạt động."""
    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp)
        _patch_http(mp, _FakeResp({"embeddings": [{"values": [0.1]}]}))
        out = await embed_client.embed_dense(["q"], side="query")
    assert out == [[0.1]]


async def test_metering_failure_never_breaks_the_query():
    """Nếu meter hỏng (bug, corruption), truy vấn tri thức vẫn phải trả kết quả."""
    m = UsageMeter(session_id="s1", channel="chat")

    def broken(*_a, **_kw):
        raise RuntimeError("meter corruption")

    m.add_embed = broken
    with pytest.MonkeyPatch.context() as mp:
        _patch_settings(mp)
        _patch_http(mp, _FakeResp({"embeddings": [{"values": [0.1]}]}))
        with context.use_meter(m):
            out = await embed_client.embed_dense(["q"], side="query")
    assert out == [[0.1]]


async def test_empty_input_costs_nothing():
    m = UsageMeter(session_id="s1", channel="chat")
    with context.use_meter(m):
        assert await embed_client.embed_dense([], side="query") == []
        assert await embed_client.embed_sparse([], side="query") == []
        assert await embed_client.embed_visual_text([]) == []
    assert m.drain() is None
