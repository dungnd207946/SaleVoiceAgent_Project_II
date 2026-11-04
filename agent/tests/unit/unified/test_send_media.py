"""send_media Qdrant search (dense text + optional visual) — media_data + support_ops.

``media_data.search_media`` embeds the phrase as dense text (plus the visual tower
when ``with_visual``), runs ONE Qdrant query over ``<tenant>_media``, and maps
``hits`` → client items. Both clients are faked (no network); ``support_ops`` is
tested by stubbing
``media_data.search_media`` so the tool contract / payload / degraded path are
verified independently of retrieval.
"""

from __future__ import annotations

import json

import httpx
import pytest

from noble_agent.agent.tools import support_ops
from noble_agent.data import db_project_registry
from noble_agent.data import media_data as md
from noble_agent.storage.models import Customer


@pytest.fixture(autouse=True)
def _clear_media_cache():
    """The result cache is module-level — without this, a cached result leaks into
    the next test and makes the file order-dependent."""
    md.reset_result_cache_for_tests()
    yield
    md.reset_result_cache_for_tests()


# ── pure helpers ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://x/a.jpg",
        "https://x/a.JPEG",
        "https://x/a.png",
        "https://x/a.webp",
        "https://x/a.gif",
        "https://x/a.PNG?w=100&h=200",
    ],
)
def test_is_image_url_true(url):
    assert md._is_image_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://x/a.pdf",
        "https://x/a.mp4",
        "https://x/nopath",
        "https://youtu.be/abc",
        "",
    ],
)
def test_is_image_url_false(url):
    assert md._is_image_url(url) is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
        # /live/<id> — Portal caption/index dạng này (regex bên đó lỏng hơn),
        # agent phải render được thay vì rơi im lặng ở khâu lọc media.
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/abc", None),  # id ngắn — giữ độ chặt 11 ký tự
        ("https://vimeo.com/12345", None),
        ("", None),
        # host-anchored: non-YouTube URL carrying an 11-char v= param → NOT a video
        ("https://cdn.example.com/render.jpg?v=abcABC12345", None),
    ],
)
def test_parse_youtube_id(url, expected):
    assert md._parse_youtube_id(url) == expected


# ── hit → item mapping (§7-8) ────────────────────────────────────────────────


def _hit(media_url, *, content_type="image", thumb_url="", caption="", hid="h"):
    return {
        "id": hid,
        "media_url": media_url,
        "thumb_url": thumb_url,
        "content_type": content_type,
        "caption": caption,
    }


def test_hit_to_item_drops_thumb_by_default():
    # thumb_url có sẵn nhưng cờ off → item chỉ mang media_url (client tự fallback).
    item = md._hit_to_item(_hit("https://s3/a.webp", thumb_url="https://s3/a_t.webp", caption="bể bơi"))
    assert item == {"kind": "image", "url": "https://s3/a.webp", "label": "bể bơi"}


def test_hit_to_item_image_with_thumb_when_enabled():
    item = md._hit_to_item(
        _hit("https://s3/a.webp", thumb_url="https://s3/a_t.webp", caption="bể bơi"), include_thumb=True
    )
    assert item == {"kind": "image", "url": "https://s3/a.webp", "label": "bể bơi", "thumb": "https://s3/a_t.webp"}


def test_hit_to_item_image_no_thumb():
    item = md._hit_to_item(_hit("https://s3/a.webp", caption="mặt bằng"))
    assert item == {"kind": "image", "url": "https://s3/a.webp", "label": "mặt bằng"}
    assert "thumb" not in item


def test_hit_to_item_content_type_image_without_ext():
    # S3 URL with no image extension but content_type=image → still an image item.
    item = md._hit_to_item(_hit("https://s3/render", content_type="image", caption="phối cảnh"))
    assert item == {"kind": "image", "url": "https://s3/render", "label": "phối cảnh"}


def test_hit_to_item_youtube_video():
    item = md._hit_to_item(_hit("https://youtu.be/dQw4w9WgXcQ", content_type="video", caption="clip dự án"))
    assert item == {"kind": "video", "video_id": "dQw4w9WgXcQ", "title": "clip dự án"}


def test_hit_to_item_non_youtube_video_is_url_variant():
    """ĐẢO CHIỀU 2026-08-25. Bản trước bỏ mọi video không nhúng được, và cái giá đo
    được trên prod là 38/93 video của một tenant biến mất im lặng (link Google Drive).
    Chiều: thẻ `file` (không đổi client); tối: biến thể `url` của `video` — host không
    nhúng được thì chỉ `url` + `title`, client vẽ thẻ ▶ mở tab mới."""
    item = md._hit_to_item(_hit("https://s3/clip.mp4", content_type="video"))
    assert item == {"kind": "video", "url": "https://s3/clip.mp4", "title": ""}


def test_hit_to_item_non_drive_video_thumb_follows_flag():
    # Thumb của ingest (MinIO nội bộ) vẫn gác sau include_thumb như ảnh; chỉ thumb Drive là không.
    hit = _hit("https://s3/clip.mp4", content_type="video", thumb_url="https://cdn/clip_t.jpg")
    assert "thumb" not in md._hit_to_item(hit)
    assert md._hit_to_item(hit, include_thumb=True)["thumb"] == "https://cdn/clip_t.jpg"


def test_hit_to_item_video_without_content_type_still_dropped():
    # mp4 mà ingest không gắn content_type video → vẫn bỏ (không đoán theo đuôi tệp).
    assert md._hit_to_item(_hit("https://s3/clip.mp4", content_type="")) is None


def test_hit_to_item_file_dropped():
    assert md._hit_to_item(_hit("https://s3/brochure.pdf", content_type="file")) is None


def test_hit_to_item_empty_media_url_dropped():
    assert md._hit_to_item(_hit("", content_type="image")) is None


def test_map_items_caps_images_and_single_video():
    hits = [_hit(f"https://s3/{i}.webp", caption=f"img{i}") for i in range(8)]  # 8 images
    hits.append(_hit("https://youtu.be/dQw4w9WgXcQ", content_type="video", caption="v1"))
    hits.append(_hit("https://youtu.be/AAAAAAAAAAA", content_type="video", caption="v2"))
    items = md._map_items(hits)
    kinds = [it["kind"] for it in items]
    assert kinds.count("image") == md.MAX_IMAGES == 6
    assert kinds.count("video") == 1
    assert kinds[:6] == ["image"] * 6 and kinds[6] == "video"


def test_map_items_default_caps_videos_at_one():
    hits = [_point(f"https://www.youtube.com/watch?v=vid{i:08d}", content_type="video") for i in range(3)]
    assert len(md._map_items(hits)) == 1


def test_map_items_respects_max_videos():
    hits = [_point(f"https://www.youtube.com/watch?v=vid{i:08d}", content_type="video") for i in range(5)]
    items = md._map_items(hits, max_videos=3)
    assert len(items) == 3
    assert all(i["kind"] == "video" for i in items)


def test_map_items_images_still_come_before_videos():
    hits = [
        _point("https://www.youtube.com/watch?v=vid00000001", content_type="video"),
        _point("https://s3/a.webp"),
    ]
    items = md._map_items(hits, max_videos=3)
    assert [i["kind"] for i in items] == ["image", "video"]


# ── search_media: Qdrant hybrid + embed (both clients faked) ─────────────────

_TENANT = "noble-homes_k3n7_retail"


def _wire(monkeypatch, *, points=None, exists=True, capture=None):
    """Point media_data at fake embed + Qdrant clients."""
    cap = capture if capture is not None else {}
    cap.setdefault("embed_calls", 0)

    async def fake_dense(texts, **kw):
        cap["embed_calls"] += 1
        cap["dense"] = (texts, kw)
        return [[0.1, 0.2]]

    async def fake_visual(texts, **kw):
        cap["embed_calls"] += 1
        cap["visual"] = (texts, kw)
        return [[0.3, 0.4, 0.5]]

    async def fake_exists(base_url, api_key, collection):
        cap["exists"] = (base_url, api_key, collection)
        return exists

    async def fake_search(**kw):
        cap["search"] = kw
        cap.setdefault("searches", []).append(kw)
        cap["search_calls"] = cap.get("search_calls", 0) + 1
        return list(points if points is not None else [])

    monkeypatch.setattr(md.embed_client, "embed_dense", fake_dense)
    monkeypatch.setattr(md.embed_client, "embed_visual_text", fake_visual)
    monkeypatch.setattr(md.qdrant_client, "collection_exists", fake_exists)
    monkeypatch.setattr(md.qdrant_client, "search_hybrid", fake_search)
    return cap


# Một lượt tìm CÓ category = 2 lời gọi Qdrant: lượt lọc, và lượt không lọc để rơi về
# khi lượt lọc rỗng (khách hay đổ mọi ảnh vào một danh mục). `_search` mặc định truyền
# category nên mọi bài dưới đây đếm theo bội số này.
GOI_MOI_LUOT = 2


def _point(media_url, *, content_type="image", thumb_url="", caption="", pid="p", project_id="NPLB"):
    """A Qdrant row as qdrant_search returns it (payload + id/score merged)."""
    return {
        "id": pid,
        "score": 0.5,
        "media_url": media_url,
        "thumb_url": thumb_url,
        "content_type": content_type,
        "caption": caption,
        "project_id": project_id,
        "category": "tien_ich",
    }


async def _search(**over):
    kwargs = {
        "tenant_id": _TENANT,
        "qdrant_url": "http://qdrant:6333",
        "qdrant_api_key": "qkey",
        "top_k": 5,
        "threshold": 0.3,
    }
    kwargs.update(over)
    query = kwargs.pop("query", "phối cảnh hồ bơi")
    code = kwargs.pop("project_code", "NPLB")
    category = kwargs.pop("category", "tien_ich")
    return await md.search_media(query, code, category, **kwargs)


async def test_search_media_queries_tenant_media_collection(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://s3/pool.webp", caption="hồ bơi")])
    items = await _search()
    assert cap["search"]["collection"] == f"{_TENANT}_media"
    assert cap["search"]["limit"] == 5
    # `_ref` CÓ ở đây là đúng: nó là khoá nội bộ để lượt gửi chọn được point, và
    # tầng này còn ở trong ranh giới tool. `send_media` mới là chỗ gỡ nó trước khi
    # payload rời tool — xem `test_media_bao_fallback.py` và `_bo_khoa_noi_bo`.
    assert items == [{"kind": "image", "url": "https://s3/pool.webp", "label": "hồ bơi", md.KHOA_REF: "p"}]


async def test_search_media_embeds_text_and_visual_branches(monkeypatch):
    cap = _wire(monkeypatch)
    await _search(query="hồ bơi vô cực", with_visual=True)
    assert cap["dense"][0] == ["hồ bơi vô cực"]
    assert cap["dense"][1]["side"] == "query"
    assert cap["visual"][0] == ["hồ bơi vô cực"]  # visual_text hardcodes side=query
    branches = cap["search"]["prefetches"]
    assert [b.using for b in branches] == ["text", "visual"]
    assert branches[0].vector == [0.1, 0.2]
    assert branches[1].vector == [0.3, 0.4, 0.5]


async def test_search_media_text_only_when_visual_off(monkeypatch):
    """Visual needs an embed service; without one media must still search on text."""
    cap = _wire(monkeypatch)
    items = await _search(query="hồ bơi")
    assert [b.using for b in cap["search"]["prefetches"]] == ["text"]
    assert "visual" not in cap  # no visual embed attempted at all
    assert cap["embed_calls"] == 1
    assert items == []


async def test_search_media_cache_keyed_on_visual_flag(monkeypatch):
    """Text-only and text+visual rank differently — they must not share a cache slot."""
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    await _search(cache_ttl=300.0, with_visual=False)
    await _search(cache_ttl=300.0, with_visual=True)
    assert cap["search_calls"] == 2 * GOI_MOI_LUOT


async def test_search_media_filters_project_with_sentinel_and_category(monkeypatch):
    cap = _wire(monkeypatch)
    await _search(project_code="NPLB", category="tien_ich")
    from noble_agent.data import qdrant_search as sq

    flt = cap["searches"][0]["filter_"]  # lượt ĐẦU là lượt có lọc
    conds = {c.key: c for c in flt.must}
    # Mệnh đề trạng thái LUÔN có mặt — đó là thứ duy nhất ngăn nội dung nháp tới khách.
    assert conds[sq.CHI_HIEN_KHI].match.value == sq.TRANG_THAI_HIEN
    assert conds["project_id"].match.any == ["NPLB", "__ALL__"]  # tenant-wide media stays visible
    assert conds["category"].match.value == "tien_ich"


async def test_search_media_filters_content_type(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://youtu.be/abcdefghijk", content_type="video")])
    await _search(content_type="video")
    conds = {c.key: c for c in cap["search"]["filter_"].must}
    assert conds["content_type"].match.value == "video"


async def test_search_media_no_content_type_condition_when_blank(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    await _search()
    assert "content_type" not in [c.key for c in cap["search"]["filter_"].must]


async def test_search_media_cache_keyed_on_content_type(monkeypatch):
    """Cùng query/project nhưng khác content_type → KHÔNG được dùng lẫn cache."""
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    await _search(cache_ttl=300.0, content_type="image")
    await _search(cache_ttl=300.0, content_type="video")
    assert cap["search_calls"] == 2 * GOI_MOI_LUOT


async def test_search_media_video_request_returns_up_to_three(monkeypatch):
    pts = [_point(f"https://www.youtube.com/watch?v=vid{i:08d}", content_type="video") for i in range(5)]
    _wire(monkeypatch, points=pts)
    items = await _search(content_type="video")
    assert len(items) == 3
    assert all(i["kind"] == "video" for i in items)


async def test_search_media_keeps_single_video_cap_when_not_asking_for_video(monkeypatch):
    pts = [_point(f"https://www.youtube.com/watch?v=vid{i:08d}", content_type="video") for i in range(3)]
    _wire(monkeypatch, points=pts)
    assert len(await _search()) == 1


async def test_search_media_threshold_applied_after_fuse(monkeypatch):
    cap = _wire(monkeypatch)
    await _search(threshold=0.4)
    assert cap["search"]["score_threshold"] == 0.4

    cap2 = _wire(monkeypatch)
    await _search(threshold=0.0)
    assert cap2["search"]["score_threshold"] is None


async def test_search_media_maps_project_id_to_project_code(monkeypatch):
    """Payload key is project_id; the tool layer speaks project_code."""
    captured: list[dict] = []
    monkeypatch.setattr(md, "_map_items", lambda hits, **kw: captured.extend(hits) or [])
    _wire(monkeypatch, points=[_point("https://s3/a.webp", project_id="SGR")])
    await _search()
    assert captured[0]["project_code"] == "SGR"


async def test_search_media_maps_images_and_video(monkeypatch):
    _wire(
        monkeypatch,
        points=[
            _point("https://s3/pool.webp", caption="hồ bơi"),
            _point("https://youtu.be/dQw4w9WgXcQ", content_type="video", caption="clip", pid="p2"),
        ],
    )
    items = await _search()
    assert [it["kind"] for it in items] == ["image", "video"]


async def test_search_media_empty_hits_returns_empty(monkeypatch):
    _wire(monkeypatch, points=[])
    assert await _search() == []


async def test_search_media_missing_collection_fails_closed(monkeypatch):
    """An unprovisioned tenant costs no embed round-trip and is never an error."""
    cap = _wire(monkeypatch, exists=False)
    assert await _search() == []
    assert cap["exists"][2] == f"{_TENANT}_media"
    assert cap["embed_calls"] == 0
    assert "search" not in cap


async def test_search_media_raises_on_backend_error(monkeypatch):
    _wire(monkeypatch)

    async def boom(texts, **kw):
        raise httpx.ConnectError("embed down")

    monkeypatch.setattr(md.embed_client, "embed_dense", boom)
    with pytest.raises(httpx.HTTPError):
        await _search()


# ── result cache ─────────────────────────────────────────────────────────────


async def test_cache_hit_skips_embed_and_qdrant(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp", caption="x")])
    first = await _search(cache_ttl=300.0, with_visual=True)
    assert cap["embed_calls"] == 2 and cap["search_calls"] == GOI_MOI_LUOT
    second = await _search(cache_ttl=300.0, with_visual=True)
    assert second == first
    assert cap["embed_calls"] == 2  # unchanged → served from cache
    assert cap["search_calls"] == GOI_MOI_LUOT


async def test_cache_key_varies_by_query_project_and_category(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    await _search(cache_ttl=300.0)
    await _search(query="khác", cache_ttl=300.0)
    await _search(project_code="SGR", cache_ttl=300.0)
    await _search(category="mat_bang", cache_ttl=300.0)
    assert cap["search_calls"] == 4 * GOI_MOI_LUOT  # no key collisions


async def test_cache_expires_after_ttl(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    clock = {"t": 1000.0}
    monkeypatch.setattr(md.time, "monotonic", lambda: clock["t"])
    await _search(cache_ttl=300.0)
    assert cap["search_calls"] == GOI_MOI_LUOT
    clock["t"] = 1000.0 + 299.0
    await _search(cache_ttl=300.0)
    assert cap["search_calls"] == GOI_MOI_LUOT  # still fresh
    clock["t"] = 1000.0 + 301.0
    await _search(cache_ttl=300.0)
    assert cap["search_calls"] == 2 * GOI_MOI_LUOT  # expired → re-queried


async def test_cache_disabled_when_ttl_zero(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    await _search(cache_ttl=0.0)
    await _search(cache_ttl=0.0)
    assert cap["search_calls"] == 2 * GOI_MOI_LUOT


async def test_cache_is_isolated_per_tenant(monkeypatch):
    cap = _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    await _search(cache_ttl=300.0)
    await _search(tenant_id="an-phu-land_q8w2_retail", cache_ttl=300.0)
    assert cap["search_calls"] == 2 * GOI_MOI_LUOT  # collection name is part of the key


async def test_cache_returns_a_copy(monkeypatch):
    """A caller mutating the returned list must not corrupt the cached entry."""
    _wire(monkeypatch, points=[_point("https://s3/a.webp")])
    first = await _search(cache_ttl=300.0)
    first.append({"kind": "image", "url": "injected"})
    second = await _search(cache_ttl=300.0)
    assert len(second) == 1


# ── send_media rewire (payload + degraded) ───────────────────────────────────

_DEGRADED_MSG = "Hình ảnh phần này bên em chưa có sẵn, để em mô tả cho anh/chị nhé"


@pytest.fixture(autouse=True)
def _registry_cache():
    db_project_registry.set_cache_for_tests({"NCR": {"code": "NCR", "name": "Noble Crystal"}})
    yield
    db_project_registry.set_cache_for_tests(None)


@pytest.fixture(autouse=True)
def _search_infra_configured(monkeypatch):
    """send_media pre-flights on these being set; tests here exercise the tool
    layer, not the config gate (which has its own test below)."""
    from noble_agent.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "qdrant_url", "http://qdrant:6333", raising=False)


def _stub_search(monkeypatch, items=None, exc=None, fallback=False):
    """Stub `search_media_detailed` — ĐÚNG hàm `send_media` gọi.

    Trước đây stub `search_media`; khi `send_media` chuyển sang hàm chi tiết (để
    biết lọc category có bị gỡ không), stub cũ thôi chặn và 23 bài đi ra mạng
    thật, đỏ với "Temporary failure in name resolution". Stub phải đi theo hàm mà
    code gọi, không theo hàm cùng tên.
    """

    async def fake_search(query, project_code, category, **kw):
        fake_search.calls.append((query, project_code, category, kw))
        if exc is not None:
            raise exc
        return md.MediaResult(list(items or []), fallback)

    fake_search.calls = []
    monkeypatch.setattr(support_ops.media_data, "search_media_detailed", fake_search)
    return fake_search


async def test_send_media_success_payload(monkeypatch):
    items = [
        {"kind": "image", "url": "https://s3/a.webp", "label": "mặt bằng"},
        {"kind": "video", "video_id": "dQw4w9WgXcQ", "title": "clip"},
    ]
    fake = _stub_search(monkeypatch, items=items)
    cust = Customer()
    out = json.loads(
        await support_ops.send_media(
            cust, {"query": "gửi hình", "project_code": "NCR", "category": "tong_quan"}, "sid-1"
        )
    )
    assert out["ok"] is True
    assert out["project_name"] == "Noble Crystal"
    assert out["caption"] == "Hình ảnh dự án Noble Crystal"
    assert out["items"] == items
    assert out["count"] == 2
    assert out["message"]  # Vietnamese ack
    for dead in ("channel", "phone", "status", "project_codes"):
        assert dead not in out
    assert fake.calls[0][1] == "NCR"
    assert fake.calls[0][2] == "tong_quan"


async def test_send_media_caption_video_only(monkeypatch):
    """items toàn video (dù content_type rỗng vẫn có thể ra toàn video) → caption/message
    phải nói 'Video', không phải 'Hình ảnh' — tránh khách xin video mà thấy chữ 'Hình ảnh'
    khiến LLM tưởng gửi thất bại rồi gọi lại send_media."""
    items = [
        {"kind": "video", "video_id": "aaaaaaaaaaa", "title": "clip 1"},
        {"kind": "video", "video_id": "bbbbbbbbbbb", "title": "clip 2"},
    ]
    _stub_search(monkeypatch, items=items)
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "cho xem video", "project_code": "NCR", "content_type": "video"}, "sid-vid"
        )
    )
    assert out["caption"].startswith("Video dự án")
    assert "gửi video" in out["message"]


async def test_send_media_caption_mixed_images_and_video(monkeypatch):
    items = [
        {"kind": "image", "url": "https://s3/a.webp", "label": "mặt bằng"},
        {"kind": "video", "video_id": "dQw4w9WgXcQ", "title": "clip"},
    ]
    _stub_search(monkeypatch, items=items)
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "gửi hình", "project_code": "NCR", "category": "tong_quan"}, "sid-mix"
        )
    )
    assert out["caption"].startswith("Hình ảnh dự án")


async def test_send_media_caption_images_only(monkeypatch):
    items = [{"kind": "image", "url": "https://s3/a.webp", "label": "mặt bằng"}]
    _stub_search(monkeypatch, items=items)
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "gửi hình", "project_code": "NCR", "category": "tong_quan"}, "sid-img"
        )
    )
    assert out["caption"].startswith("Hình ảnh dự án")


async def test_send_media_category_as_list_does_not_raise(monkeypatch):
    """Đã gặp thật với project_code — phòng vệ tương tự cho category/content_type."""
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "x", "project_code": "NCR", "category": ["tien_do"]}, "sid-catlist"
        )
    )
    assert out["ok"] is True
    assert fake.calls[0][2] == "tien_do"


async def test_send_media_content_type_as_list_does_not_raise(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "video", "video_id": "aaaaaaaaaaa", "title": "c"}])
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "x", "project_code": "NCR", "content_type": ["video"]}, "sid-ctlist"
        )
    )
    assert out["ok"] is True
    assert fake.calls[0][3]["content_type"] == "video"


async def test_send_media_missing_both_filters_returns_retry(monkeypatch):
    """Rỗng CẢ category và content_type → chặn trước khi gọi search."""
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(await support_ops.send_media(Customer(), {"query": "x", "project_code": "NCR"}, "sid-c"))
    assert out["ok"] is False
    assert out["error"] == "missing_filter"
    assert out["retry"] is True
    assert "category" in out["message"]
    assert "content_type" in out["message"]
    assert "tong_quan" in out["message"]  # message liệt kê giá trị hợp lệ
    assert "video" in out["message"]
    assert fake.calls == []  # rejected BEFORE hitting the backend


async def test_send_media_content_type_only_runs_search(monkeypatch):
    """Khách xin video chung: chỉ content_type, KHÔNG category → vẫn chạy."""
    fake = _stub_search(monkeypatch, items=[{"kind": "video", "video_id": "dQw4w9WgXcQ", "title": "clip"}])
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "cho xem video", "project_code": "NCR", "content_type": "video"}, "sid-v"
        )
    )
    assert out["ok"] is True
    assert len(fake.calls) == 1
    assert fake.calls[0][2] == ""  # category rỗng
    assert fake.calls[0][3]["content_type"] == "video"


async def test_send_media_invalid_content_type_returns_retry(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(
        await support_ops.send_media(Customer(), {"query": "x", "project_code": "NCR", "content_type": "gif"}, "sid-ct")
    )
    assert out["ok"] is False
    assert out["error"] == "invalid_content_type"
    assert out["retry"] is True
    assert "gif" in out["message"]
    assert fake.calls == []


async def test_send_media_content_type_normalized(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "video", "video_id": "dQw4w9WgXcQ", "title": "c"}])
    await support_ops.send_media(Customer(), {"query": "x", "project_code": "NCR", "content_type": " VIDEO "}, "sid-n")
    assert fake.calls[0][3]["content_type"] == "video"


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"content_type": "video", "category": "tien_do"}, "video tien_do dự án"),
        ({"content_type": "video"}, "video dự án"),
        ({"category": "tong_quan"}, "hình ảnh tong_quan dự án"),
        ({"content_type": "image", "category": "mat_bang"}, "hình ảnh mat_bang dự án"),
    ],
)
async def test_send_media_search_query_fallback(monkeypatch, args, expected):
    """query rỗng → tự dựng câu tìm; không được sinh hai khoảng trắng."""
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    await support_ops.send_media(Customer(), {"query": "", "project_code": "NCR", **args}, "sid-f")
    assert fake.calls[0][0] == expected
    assert "  " not in fake.calls[0][0]


async def test_send_media_invalid_category_returns_retry(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(
        await support_ops.send_media(Customer(), {"query": "x", "project_code": "NCR", "category": "bogus"}, "sid-i")
    )
    assert out["ok"] is False
    assert out["error"] == "invalid_category"
    assert out["retry"] is True
    assert "bogus" in out["message"]
    assert fake.calls == []


async def test_send_media_missing_project_code_returns_retry(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(await support_ops.send_media(Customer(), {"query": "x", "category": "mat_bang"}, "sid-p"))
    assert out["ok"] is False
    assert out["error"] == "missing_project_code"
    assert out["retry"] is True
    assert "project_code" in out["message"]
    assert fake.calls == []


async def test_send_media_passes_category_and_query(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    cust = Customer()
    await support_ops.send_media(
        cust, {"query": "cho xem mặt bằng", "project_code": "NCR", "category": "mat_bang"}, "sid-x"
    )
    assert fake.calls[0][0] == "cho xem mặt bằng"
    assert fake.calls[0][2] == "mat_bang"
    # tenant isolation: send_media forwards the current tenant → collection name
    from noble_agent.tenant.current import current_tenant

    assert fake.calls[0][3]["tenant_id"] == current_tenant()


async def test_send_media_forwards_search_infra_settings(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    await support_ops.send_media(Customer(), {"query": "x", "project_code": "NCR", "category": "tong_quan"}, "sid-inf")
    kw = fake.calls[0][3]
    assert kw["qdrant_url"] == "http://qdrant:6333"
    assert "cache_ttl" in kw and "qdrant_timeout" in kw
    assert "embed_url" not in kw  # embed config lives in data/embed_client


async def test_send_media_unconfigured_qdrant_degrades(monkeypatch):
    """Unset QDRANT_URL is how ops disables media — degrade, never crash, never dial."""
    from noble_agent.config import get_settings

    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    monkeypatch.setattr(get_settings(), "qdrant_url", "", raising=False)
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "x", "project_code": "NCR", "category": "tong_quan"}, "sid-cfg"
        )
    )
    assert out["ok"] is False
    assert out["note"] == "no_media"
    assert fake.calls == []  # never reached retrieval


async def test_send_media_uses_project_interest_when_no_code(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    cust = Customer(project_interest="NCR")
    out = json.loads(await support_ops.send_media(cust, {"query": "gửi hình", "category": "tong_quan"}, "sid-2"))
    assert out["ok"] is True
    assert out["project_name"] == "Noble Crystal"
    assert fake.calls[0][1] == "NCR"


async def test_send_media_category_uppercase_normalized(monkeypatch):
    # A model may echo the enum in caps; we lowercase before validating.
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(
        await support_ops.send_media(Customer(), {"query": "x", "project_code": "NCR", "category": "MAT_BANG"}, "sid-u")
    )
    assert out["ok"] is True
    assert fake.calls[0][2] == "mat_bang"


async def test_send_media_accepts_array_project_code(monkeypatch):
    # Defensive: a model may still send an array; first element is used.
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(
        await support_ops.send_media(Customer(), {"query": "x", "project_code": ["NCR"], "category": "vi_tri"}, "sid-a")
    )
    assert out["ok"] is True
    assert fake.calls[0][1] == "NCR"


async def test_send_media_no_media_degraded(monkeypatch):
    _stub_search(monkeypatch, items=[])
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "x", "project_code": "NCR", "category": "tong_quan"}, "sid-4"
        )
    )
    assert out["ok"] is False
    assert out["note"] == "no_media"
    assert out["message"] == _DEGRADED_MSG


async def test_send_media_service_error_degraded(monkeypatch, caplog):
    _stub_search(monkeypatch, exc=httpx.ConnectError("down"))
    with caplog.at_level("WARNING"):
        out = json.loads(
            await support_ops.send_media(
                Customer(), {"query": "x", "project_code": "NCR", "category": "tong_quan"}, "sid-5"
            )
        )
    assert out["ok"] is False
    assert out["note"] == "no_media"
    assert any(r.levelname == "WARNING" for r in caplog.records)


async def test_send_media_gates_visual_on_embed_service(monkeypatch):
    """The visual branch is the one thing still needing the embed service, so the
    tool must decide per-config instead of failing when there is none."""
    from noble_agent.config import get_settings

    s = get_settings()
    args = {"query": "x", "project_code": "NCR", "category": "tong_quan"}

    monkeypatch.setattr(s, "embed_service_url", "", raising=False)
    off = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    await support_ops.send_media(Customer(), args, "sid-v1")
    assert off.calls[0][3]["with_visual"] is False

    monkeypatch.setattr(s, "embed_service_url", "http://embed:8013/embed", raising=False)
    on = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    await support_ops.send_media(Customer(), args, "sid-v2")
    assert on.calls[0][3]["with_visual"] is True


async def test_send_media_unknown_code_uses_code_as_name(monkeypatch):
    # project resolves via search but code not in registry → project_name = code.
    _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "x", "project_code": "ZZZ", "category": "tong_quan"}, "sid-6"
        )
    )
    assert out["ok"] is True
    assert out["project_name"] == "ZZZ"


# ── config (§10) ─────────────────────────────────────────────────────────────


def test_config_media_search_defaults():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings(_env_file=None)  # code defaults, not the dev .env
    assert s.media_search_top_k == 10
    # 0 = no filter: the RRF scale shifts with branch count, so a fixed cutoff
    # would silently cap image count differently with/without the visual branch.
    assert s.media_search_threshold == 0.0
    assert s.media_search_cache_ttl == 300.0


def test_retired_service_settings_are_gone():
    """query_media:8015 is retired — its URL/timeout and the old CMS redirect base
    must not linger, or a stale .env value reads like live config."""
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings()
    for gone in ("media_search_url", "media_search_timeout", "cms_media_base_url"):
        assert not hasattr(s, gone), f"{gone} should have been removed with the service"


# ── schema seam ──────────────────────────────────────────────────────────────


def test_schema_project_code_is_free_string_category_enum_fixed():
    from noble_agent.agent.tools.schemas import schemas_for

    schema = schemas_for(["send_media"])[0]
    props = schema["function"]["parameters"]["properties"]
    # project_code: free-text string resolved via find_project — no enum
    assert props["project_code"]["type"] == "string"
    assert "enum" not in props["project_code"]
    # category: đúng 7 giá trị, khớp `MEDIA_VISUAL_REAL_ESTATE` của Portal — đó là tập
    # danh mục DUY NHẤT được nạp vào `_media`. Chào một giá trị ngoài tập đó là chào một
    # bộ lọc không point nào khớp: luôn rỗng, không lỗi.
    assert props["category"]["enum"] == [
        "tong_quan",
        "ngoai_that",
        "noi_that",
        "tien_ich",
        "mat_bang",
        "vi_tri",
        "tien_do",
    ]
    assert "phap_ly" not in props["category"]["enum"], "pháp lý là TÀI LIỆU (kb_search), không phải ảnh"
    assert schema["function"]["parameters"]["required"] == ["query"]


async def test_send_media_caption_tour_360(monkeypatch):
    """Tour 360 KHÔNG được gọi là "hình ảnh".

    `_map_items` đặt tour LÊN ĐẦU, nên đó là thứ khách thấy trước. Nói "hình ảnh" thì LLM
    tưởng gửi trượt rồi gọi lại send_media — đúng lỗi mà nhánh "video" đã được thêm để tránh.
    """
    items = [{"kind": "tour", "url": "https://kuula.co/share/collection/7l8Rt?fs=1", "label": "tour"}]
    _stub_search(monkeypatch, items=items)
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "cho xem tour 360", "project_code": "NCR", "content_type": "tour_360"}, "sid-tour"
        )
    )
    assert out["caption"].startswith("Tour 360 dự án")
    assert "tour 360" in out["message"].lower()
    # Link đi trong payload, KHÔNG trong chuỗi LLM đọc — cả mục đích của đường tour.
    assert "kuula.co" not in out["caption"] and "kuula.co" not in out["message"]


async def test_send_media_caption_tour_kem_anh_van_noi_tour(monkeypatch):
    """Tour đứng đầu danh sách nên nó là thứ dẫn câu, dù có ảnh đi kèm."""
    items = [
        {"kind": "tour", "url": "https://kuula.co/share/collection/7l8Rt", "label": "tour"},
        {"kind": "image", "url": "https://s3/a.webp", "label": "mặt bằng"},
    ]
    _stub_search(monkeypatch, items=items)
    out = json.loads(
        await support_ops.send_media(
            Customer(), {"query": "xem dự án", "project_code": "NCR", "category": "tong_quan"}, "sid-tour-mix"
        )
    )
    assert out["caption"].startswith("Tour 360 dự án")


async def test_send_media_tour_tim_dung_danh_tu(monkeypatch):
    """Câu truy vấn nhúng phải nói "tour", không phải "hình ảnh".

    Caption của point tour là "Tour tham quan thực tế ảo 360 độ — <tên dự án>", nên hỏi
    "hình ảnh dự án" là tìm sai thứ — hit tour có thể không lọt top-k và khách xin tour thì
    nhận về ảnh mặt bằng.
    """
    fake = _stub_search(monkeypatch, items=[{"kind": "tour", "url": "u", "label": "t"}])
    await support_ops.send_media(Customer(), {"project_code": "NCR", "content_type": "tour_360"}, "sid-q")
    cau = fake.calls[0][0]
    assert "tour" in cau.lower(), f"truy vấn không nói tour: {cau!r}"
    assert "hình ảnh" not in cau.lower()


async def test_send_media_khong_khai_content_type_van_tim_hinh_anh(monkeypatch):
    """Đường mặc định không đổi."""
    fake = _stub_search(monkeypatch, items=[{"kind": "image", "url": "u", "label": ""}])
    await support_ops.send_media(Customer(), {"project_code": "NCR", "category": "tong_quan"}, "sid-q2")
    assert "hình ảnh" in fake.calls[0][0].lower()


# ─── Luồng hai bước khi lọc category bị gỡ ───────────────────────────────────
#
# Nhánh này tồn tại vì `dispatch()` gọi `on_tool_done` TRƯỚC khi trả kết quả cho
# LLM, nên ảnh đã ở trên màn hình khách trước khi LLM sinh token nào — và
# `_strip_display_items` gỡ `items[]` khỏi ngữ cảnh LLM nên nó không biết mình vừa
# gửi gì. Bỏ `items[]` là cách chặn việc gửi mà không phải sửa dispatcher.

_ANH_A = {"kind": "image", "url": "https://s3/a.webp", "label": "Bể bơi trong nhà", md.KHOA_REF: "pt-1"}
_ANH_B = {"kind": "image", "url": "https://s3/b.webp", "label": "Phối cảnh ban đêm", md.KHOA_REF: "pt-2"}


async def _goi(monkeypatch, *, items, fallback, ids=None):
    _stub_search(monkeypatch, items=items, fallback=fallback)
    args = {"query": "cho xem ảnh nội thất", "project_code": "NCR", "category": "noi_that"}
    if ids is not None:
        args["ids"] = ids
    return json.loads(await support_ops.send_media(Customer(), args, "sid-fb"))


async def test_fallback_tra_candidates_va_KHONG_co_items(monkeypatch):
    """Không có `items[]` thì không màn nào dựng thẻ — khách chưa thấy gì."""
    out = await _goi(monkeypatch, items=[_ANH_A, _ANH_B], fallback=True)

    assert out["note"] == "category_fallback"
    assert "items" not in out
    assert [c["ref"] for c in out["candidates"]] == ["pt-1", "pt-2"]
    assert [c["caption"] for c in out["candidates"]] == ["Bể bơi trong nhà", "Phối cảnh ban đêm"]


async def test_fallback_khong_mom_san_cau_noi(monkeypatch):
    """Cả nhánh này tồn tại vì câu mớm sẵn là thứ nói sai. Có `message` ở đây là
    mời LLM đọc nó rồi nói "đã gửi ảnh nội thất" y như cũ."""
    out = await _goi(monkeypatch, items=[_ANH_A], fallback=True)

    assert "message" not in out
    assert out["category_yeu_cau"] == "noi_that"


async def test_khong_fallback_thi_gui_ngay_khong_qua_luot_hai(monkeypatch):
    """Đường khớp category phải giữ nguyên: thêm một lượt LLM ở đây là trả độ trễ
    cho việc không cần làm."""
    out = await _goi(monkeypatch, items=[_ANH_A], fallback=False)

    assert out["ok"] is True
    assert len(out["items"]) == 1
    assert "candidates" not in out


async def test_ids_loc_dung_nhung_ref_da_chon(monkeypatch):
    out = await _goi(monkeypatch, items=[_ANH_A, _ANH_B], fallback=True, ids=["pt-2"])

    assert out["ok"] is True
    assert [i["url"] for i in out["items"]] == ["https://s3/b.webp"]
    assert out["count"] == 1


async def test_ids_khong_khop_gi_thi_gui_ca_ro(monkeypatch):
    """Ref bịa, hoặc cache hết hạn giữa hai lượt nên point id đổi. Khách đang chờ
    ảnh và media CÓ tồn tại — trả rỗng ở đây là nói dối."""
    out = await _goi(monkeypatch, items=[_ANH_A, _ANH_B], fallback=True, ids=["khong-ton-tai"])

    assert out["ok"] is True
    assert out["count"] == 2


async def test_ref_khong_bao_gio_ra_khoi_tool(monkeypatch):
    """`_ref` là quy ước nội bộ. Lọt ra là dạy client một khoá nó không được thấy."""
    out = await _goi(monkeypatch, items=[_ANH_A, _ANH_B], fallback=True, ids=["pt-1"])

    assert md.KHOA_REF not in out["items"][0]
    assert md.KHOA_REF not in json.dumps(out)


async def test_go_ref_khong_lam_ban_item_goc(monkeypatch):
    """`media_data._cache` copy NÔNG, nên `del` tại chỗ là ghi vào bản cache: lượt
    sau trong cửa sổ TTL mất `_ref` và phép lọc `ids` im lặng không khớp gì."""
    goc = [dict(_ANH_A), dict(_ANH_B)]
    await _goi(monkeypatch, items=goc, fallback=False)

    assert all(md.KHOA_REF in it for it in goc)
