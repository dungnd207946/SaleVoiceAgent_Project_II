"""Project media search — Qdrant search over `<tenant>_media`.

Embeds the phrase as dense text (see data/embed_client) and, when an embed service
is configured, also through the SigLIP2 text tower to search image space; both
branches fuse server-side in Qdrant. Each hit maps to a client-renderable item
(image URL, YouTube video id, or a video link with embed/thumb). No byte transfer — `media_url` is the S3 link.

Two gotchas:
  - `threshold` is on the RRF scale (rank0 = 0.5, rank1 = 0.333…), not cosine, and it
    shifts with the number of branches fused — text-only ranks lower than text+visual
    for the same item. It both filters and caps how many hits survive, so changing it
    changes how many images the customer receives.
  - the result cache is not invalidated by an ingest — new media appears after at most
    `cache_ttl` seconds.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse

from noble_agent.data import embed_client
from noble_agent.data import qdrant_search as qdrant_client

logger = logging.getLogger("noble_agent.data.media_data")

# Named vectors on the `<tenant>_media` collection (KB collection schema).
CONTENT_TYPE_TOUR = "tour_360"

TEXT_VECTOR = "text"
VISUAL_VECTOR = "visual"

KHOA_REF = "_ref"
"""Point id của hit, gắn vào item để LLM chọn được ở lượt gửi.

Tiền tố `_` là quy ước NỘI BỘ: `support_ops` gỡ mọi khoá dạng này trước khi
payload rời tool, nên client không bao giờ thấy. Dùng point id chứ không dùng vị
trí trong mảng — vị trí buộc lượt gửi phải tin rằng thứ tự không đổi giữa hai
lời gọi, còn point id thì không cần tin gì.
"""


class MediaResult(NamedTuple):
    """Kết quả tìm media, kèm việc lọc category có bị gỡ hay không.

    `category_fallback` là thứ `send_media` cần để phân biệt "đây là ảnh nội thất
    thật" với "không có ảnh nội thất, đây là ảnh gì cũng được" — hai cảnh mà hôm
    nay trông giống hệt nhau ở phía nó.
    """

    items: list[dict]
    category_fallback: bool


MAX_IMAGES = 6
# Khách xin đích danh video (`content_type="video"`) thì nhận cả bộ video của dự án;
# nhánh chủ động giới thiệu vẫn giữ ≤1 để không lấn ảnh.
MAX_VIDEOS_WHEN_REQUESTED = 3

# Một dự án có ĐÚNG một tour 360 (Portal ghi 1 point/dự án từ `projects.link_360`), nên
# trần 1 là đủ và nó có rổ riêng để không cạnh tranh slot với ảnh.
MAX_TOURS = 1

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# YouTube id: exactly 11 chars, [A-Za-z0-9_-].
_YT_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"})
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# /live/ đi cùng embed|shorts: Portal caption/index cả dạng đó (regex bên đó
# lỏng hơn) — thiếu ở đây là video live rơi im lặng ở khâu lọc media.
_YT_EMBED_SHORTS = re.compile(r"^/(?:embed|shorts|live)/([A-Za-z0-9_-]{11})")

# Google Drive: 38/93 video của tenant thật (`aina_test`, đo 2026-08-25) là link Drive,
# không phải YouTube — xem `_hit_to_item`.
_DRIVE_HOST = "drive.google.com"
_DRIVE_FILE_ID = re.compile(r"^/file/d/([A-Za-z0-9_-]+)")
_DRIVE_THUMB_W = 400


def _is_image_url(url: str) -> bool:
    """True when the URL path (ignoring any query string) ends in an image ext."""
    if not url:
        return False
    path = (url or "").split("?", 1)[0].lower()
    return path.endswith(_IMAGE_EXTS)


def _parse_drive_id(url: str) -> str | None:
    """Id tệp của một link Google Drive dạng `/file/d/<id>/…`, ngược lại None.

    Neo theo HOST như `_parse_youtube_id`: một URL khác mang đoạn `/file/d/…` không
    được đọc thành tệp Drive. Link THƯ MỤC (`/drive/folders/<id>`) cố ý KHÔNG khớp —
    nó không có thumbnail và không phải một video.
    """
    if not url:
        return None
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != _DRIVE_HOST:
        return None
    m = _DRIVE_FILE_ID.match(parsed.path)
    return m.group(1) if m else None


def _drive_thumb(file_id: str) -> str:
    """Ảnh đại diện công khai của một tệp Drive. Đo trên hai tệp thật của
    `ALLUVIA_CITY`: trả `200 image/jpeg` (34 KB và 8 KB)."""
    return f"https://{_DRIVE_HOST}/thumbnail?id={file_id}&sz=w{_DRIVE_THUMB_W}"


def _drive_embed(file_id: str) -> str:
    """Trang player nhúng được (iframe) của một tệp Drive chia sẻ công khai — đo
    trên tệp thật của tenant: `/preview` trả 200 text/html, `/view` thì X-Frame-Options
    chặn. Client có lightbox dùng nó; client chỉ có thẻ link thì mở `url`."""
    return f"https://{_DRIVE_HOST}/file/d/{file_id}/preview"


def _parse_youtube_id(url: str) -> str | None:
    """Extract the 11-char video id from a YouTube URL. Host-anchored: returns an
    id ONLY when the URL host is a YouTube host, so a non-YouTube URL carrying a
    ``?v=<11 chars>`` param is NOT misread as a video → None."""
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _YT_HOSTS:
        return None
    if host == "youtu.be":  # youtu.be/<id>
        candidate = parsed.path.lstrip("/").split("/", 1)[0]
        return candidate if _YT_ID.match(candidate) else None
    m = _YT_EMBED_SHORTS.match(parsed.path)  # youtube.com/embed|shorts|live/<id>
    if m:
        return m.group(1)
    v = parse_qs(parsed.query).get("v", [""])[0]  # youtube.com/watch?v=<id>
    return v if _YT_ID.match(v) else None


def _hit_to_item(hit: dict, *, include_thumb: bool = False) -> dict | None:
    """Map one service hit → a client item; unrenderable → None+log.

    - ``media_url`` that parses as a YouTube URL → ``video`` item (client embeds
      via ``video_id``).
    - otherwise an image (``content_type == 'image'`` OR an image-extension URL)
      → ``image`` item (S3 ``media_url`` shown directly; ``thumb_url`` only when
      ``include_thumb`` — the clients already fall back to ``url`` without it).
    - ``content_type == 'video'`` không phải YouTube (Google Drive, Vimeo, mp4…) →
      ``video`` item BIẾN THỂ ``url`` (không ``video_id``): Drive đọc được id thì kèm
      ``embed_url`` (player nhúng) + ``thumb`` (Google host); còn lại chỉ ``url``.
    - anything else (PDF / generic file the client can't render) → dropped.
    """
    media_url = (hit.get("media_url") or "").strip()
    if not media_url:
        return None
    caption = (hit.get("caption") or "").strip().replace("chủ thể:", "").replace("điểm nhấn:", "\n")
    thumb_url = (hit.get("thumb_url") or "").strip()
    content_type = (hit.get("content_type") or "").strip().lower()

    # TOUR 360 — loại thẻ thứ ba, thêm 2026-08-14.
    #
    # Trước đó tour 360 nằm ở collection `_documents` với link ĐẶT TRONG TEXT, nên để trả
    # link cho khách thì LLM phải CHÉP LẠI một chuỗi kiểu
    # `https://kuula.co/share/collection/7l8Rt?logo=…&info=…&fs=1&vr=0&…` — dài, nhiều tham
    # số, và chép sai là chuyện SẼ xảy ra. Ở đây link đi trong payload và client tự render,
    # nên LLM không bao giờ chạm vào chuỗi.
    #
    # Phải nhận theo `content_type` chứ KHÔNG theo hình dạng URL: link kuula không có đuôi
    # ảnh và không phải host YouTube, nên hai nhánh dưới đều trả None và hit bị loại IM
    # LẶNG — đúng lý do thiết kế cũ đã loại đường media cho tour 360.
    if content_type == CONTENT_TYPE_TOUR:
        item: dict = {"kind": "tour", "url": media_url, "label": caption}
        if include_thumb and thumb_url:
            item["thumb"] = thumb_url
        return item

    yt = _parse_youtube_id(media_url)
    if yt:
        return {"kind": "video", "video_id": yt, "title": caption}

    # VIDEO KHÔNG PHẢI YOUTUBE — bug thật, đo trên prod 2026-08-25.
    #
    # Khách xin video dự án ALLUVIA CITY, agent trả "không có". Postgres có 2 video
    # published, Qdrant có đúng 2 point kèm caption, và search TRẢ VỀ chúng — rồi hàm
    # này bỏ cả hai vì `media_url` là link Google Drive: không phải host YouTube nên
    # `_parse_youtube_id` trả None, không có đuôi ảnh nên nhánh dưới cũng trượt. Log
    # prod có đúng ba dòng "cannot render" của ca đó.
    #
    # ⚠️ LẶP LẠI LẦN THỨ HAI cùng một lớp lỗi: docstring của nhánh tour 360 ngay trên
    # đã ghi "link kuula không có đuôi ảnh và không phải host YouTube, nên hai nhánh
    # dưới đều trả None và hit bị loại IM LẶNG". Bài học chưa được rút rộng ra, nên
    # 38/93 video của tenant tiếp tục vô hình.
    #
    # Bản vá chiều 25/08 (56a058f) phát `kind: "file"` để KHÔNG đổi client. Tối cùng
    # ngày đổi sang BIẾN THỂ `url` của `video` (quyết định sản phẩm, đã chốt với user):
    # đúng nghĩa video (noun "Video", ▶, tiêu slot video), và client có lightbox nhúng
    # được player Drive qua `embed_url` thay vì chỉ mở link. Kiến thức Drive nằm MỘT chỗ
    # ở đây — cùng lệ `_parse_youtube_id` — client không cần biết luật Drive. Client
    # chưa cập nhật hợp đồng (đòi `video_id`) bỏ phần tử này im lặng, như trước bản vá;
    # portal FE + AINA cập nhật cùng đợt.
    if content_type == "video":
        item = {"kind": "video", "url": media_url, "title": caption}
        drive = _parse_drive_id(media_url)
        if drive:
            item["embed_url"] = _drive_embed(drive)
            # KHÔNG gác sau `include_thumb`: cờ đó nói "client rơi về `url` được rồi"
            # — đúng với ảnh, sai ở đây, vì một link Drive `/view` không hiện được
            # trong `<img>`. Thumbnail này là hình duy nhất của thẻ, không phải bản
            # đẹp hơn của một hình đã có.
            item["thumb"] = _drive_thumb(drive)
        elif include_thumb and thumb_url:
            item["thumb"] = thumb_url
        return item

    if content_type == "image" or _is_image_url(media_url):
        item = {"kind": "image", "url": media_url, "label": caption}
        if include_thumb and thumb_url:
            item["thumb"] = thumb_url
        return item

    logger.info("media_data: skip hit id=%s content_type=%s (client cannot render)", hit.get("id"), content_type)
    return None


def _map_items(hits: list[dict], *, max_videos: int = 1, include_thumb: bool = False) -> list[dict]:
    """Map score-sorted hits → items: tour trước, rồi ≤MAX_IMAGES ảnh, rồi ≤max_videos video.

    TOUR ĐỨNG ĐẦU và có trần RIÊNG: một dự án chỉ có MỘT tour, nên nó không cạnh tranh slot
    với ảnh. Nhồi nó vào rổ ảnh (`MAX_IMAGES = 6`) thì một dự án nhiều ảnh sẽ đẩy tour ra
    khỏi kết quả đúng lúc khách hỏi "cho em xem tour 360".
    """
    tours: list[dict] = []
    images: list[dict] = []
    videos: list[dict] = []
    for hit in hits:
        item = _hit_to_item(hit, include_thumb=include_thumb)
        if item is None:
            continue
        # Gắn ở ĐÂY, không trong `_hit_to_item`: hàm đó có bốn điểm return và hơn
        # hai chục test gọi thẳng nó với phép so dict chính xác. Chỗ này có cả
        # `hit` lẫn `item` trong tay nên một dòng là đủ.
        item[KHOA_REF] = str(hit.get("id") or "")
        if item["kind"] == "tour":
            if len(tours) < MAX_TOURS:
                tours.append(item)
        elif item["kind"] == "image":
            if len(images) < MAX_IMAGES:
                images.append(item)
        elif item["kind"] == "video" and len(videos) < max_videos:
            # Cả hai biến thể (`video_id` YouTube / `url` Drive…) tiêu slot VIDEO — cho
            # vào rổ ảnh thì một dự án có 2 video Drive sẽ đẩy 2 ảnh ra khỏi kết quả
            # đúng lúc khách xin ảnh.
            videos.append(item)
    return tours + images + videos


class _ResultCache:
    """Tiny TTL cache of already-mapped items, keyed by the full query shape.

    Ported from the retired service. Caches the MAPPED items rather than raw hits:
    one function now owns both steps here, and mapping is pure + cheap, so there is
    no reason to keep two cached shapes.

    GIỮ CẢ `category_fallback`, không chỉ items: cache một `list` thì lượt gọi thứ
    hai trong cửa sổ TTL trả items kèm cờ `False` mặc định, tức đúng bug mà cờ này
    sinh ra để chống — chỉ khó thấy hơn vì nó cần hai lần gọi mới hiện.

    Bản copy vẫn là NÔNG (`list(...)` copy mảng, không copy từng dict). Bên đọc
    phải dựng dict mới thay vì sửa tại chỗ, nếu không nó ghi vào chính bản cache —
    `send_media` gỡ khoá `_*` theo đúng lối đó.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, MediaResult]] = {}

    def get(self, key: str, ttl: float) -> MediaResult | None:
        if ttl <= 0:
            return None
        entry = self._data.get(key)
        if entry is None:
            return None
        stamped, kq = entry
        if time.monotonic() - stamped > ttl:
            del self._data[key]
            return None
        return MediaResult(list(kq.items), kq.category_fallback)

    def set(self, key: str, kq: MediaResult, ttl: float) -> None:
        if ttl <= 0:
            return
        self._data[key] = (time.monotonic(), MediaResult(list(kq.items), kq.category_fallback))

    def clear(self) -> None:
        self._data.clear()


_cache = _ResultCache()


async def _none() -> None:
    """Placeholder awaitable so the gather stays one shape either way."""
    return None


def reset_result_cache_for_tests() -> None:
    """Drop every cached result. Tests must call this between cases — the cache is
    module-level, so without it results leak across tests and make them
    order-dependent."""
    _cache.clear()


async def search_media_detailed(
    query: str,
    project_code: str,
    category: str,
    *,
    tenant_id: str,
    qdrant_url: str,
    qdrant_api_key: str = "",
    content_type: str = "",
    top_k: int = 10,
    threshold: float = 0.0,
    qdrant_timeout: float = 10.0,
    cache_ttl: float = 300.0,
    with_visual: bool = False,
    include_thumb: bool = False,
) -> MediaResult:
    """Qdrant search over ``<tenant_id>_media`` → client items + cờ fallback.

    `category_fallback` chỉ `True` ở ĐÚNG một cảnh: có truyền `category`, lượt lọc
    trả rỗng, lượt không lọc có kết quả. Không truyền category thì không phải
    fallback (không-lọc-từ-đầu khác bị-gỡ-lọc — gộp hai cái là bắt LLM rào đón một
    câu trả lời vốn đã đúng ý khách); cả hai lượt rỗng cũng không, vì không có gì
    để chọn thì đường đúng là `no_media` như cũ.

    ``with_visual`` adds the SigLIP2 image-space branch; it needs an embed service,
    so the caller gates it on that being configured. Off = dense text only.

    ``content_type`` (``"image"``|``"video"``, rỗng = cả hai) là hard filter trên
    payload. Khi bằng ``"video"``, cap video nới từ 1 lên ``MAX_VIDEOS_WHEN_REQUESTED``.

    ``include_thumb`` đưa ``thumb_url`` vào item ảnh. Mặc định off: client rơi về
    ``media_url``, nên một ``thumb_url`` không tới được client không thành ảnh vỡ.

    Returns ``≤MAX_IMAGES`` image items followed by video items — ``≤1`` YouTube
    video by default, or ``≤MAX_VIDEOS_WHEN_REQUESTED`` when ``content_type="video"``.
    An unprovisioned tenant (no collection) returns ``[]`` without embedding —
    fail-closed, never an error, and never another tenant's media.

    Raises on embed / Qdrant failure — the caller (``support_ops.send_media``) owns
    the tool-boundary 'never raise' guarantee.
    """
    collection = qdrant_client.collection_name(tenant_id, "media")
    if not await qdrant_client.collection_exists(qdrant_url, qdrant_api_key, collection):
        logger.info("media_data: collection %s absent → no media", collection)
        return MediaResult([], False)

    key = (
        f"{collection}|{query}|{top_k}|{threshold}|{project_code}|{category}"
        f"|{content_type}|{with_visual}|{include_thumb}"
    )
    cached = _cache.get(key, cache_ttl)
    if cached is not None:
        logger.info("media_data: cache hit (%d items) for %s", len(cached.items), key)
        return cached

    text_vecs, visual_vecs = await asyncio.gather(
        embed_client.embed_dense([query], side="query"),
        embed_client.embed_visual_text([query]) if with_visual else _none(),
    )
    if not text_vecs:
        logger.warning("media_data: embed returned no vectors → no media")
        return MediaResult([], False)

    prefetches = [qdrant_client.DensePrefetch(TEXT_VECTOR, text_vecs[0])]
    if visual_vecs:
        prefetches.append(qdrant_client.DensePrefetch(VISUAL_VECTOR, visual_vecs[0]))

    async def _tim(loc_category: str) -> list[dict]:
        return await qdrant_client.search_hybrid(
            base_url=qdrant_url,
            api_key=qdrant_api_key,
            collection=collection,
            prefetches=prefetches,
            limit=top_k,
            score_threshold=threshold if threshold > 0 else None,
            filter_=qdrant_client.build_scope_filter(
                [project_code] if project_code else [],
                category=loc_category,
                content_type=content_type,
            ),
            timeout=qdrant_timeout,
        )

    max_videos = MAX_VIDEOS_WHEN_REQUESTED if content_type == "video" else 1

    def _items(points: list[dict]) -> list[dict]:
        # `project_id` is the payload key; `_hit_to_item` and the tool layer speak
        # `project_code`. Everything else passes through under its own name.
        hits = [{**p, "project_code": p.get("project_id", "")} for p in points]
        return _map_items(hits, max_videos=max_videos, include_thumb=include_thumb)

    # HAI LƯỢT: khách hay đổ mọi ảnh vào một danh mục (đo trên prod: 96% ở `tong_quan`),
    # nên lọc theo category trả rỗng dù ảnh có thật. Vector dùng chung nên lượt hai chỉ
    # tốn một round-trip Qdrant. Xét trên `items` chứ không `points`: hit mà client không
    # render được thì khách vẫn không nhận được gì.
    fallback = False
    if category:
        loc, khong_loc = await asyncio.gather(_tim(category), _tim(""))
        items = _items(loc)
        if not items:
            items = _items(khong_loc)
            # Cờ chỉ bật khi lượt hai THẬT SỰ có gì: cả hai rỗng thì không có gì để
            # LLM chọn, và đường đúng của ca đó là `no_media` như cũ — bật cờ ở đây
            # là đẩy `send_media` vào nhánh candidates rỗng.
            fallback = bool(items)
            logger.info(
                "media_data: category=%s không có ảnh nào → rơi về tìm không lọc (%d item)",
                category,
                len(items),
            )
    else:
        items = _items(await _tim(""))
    kq = MediaResult(items, fallback)
    _cache.set(key, kq, cache_ttl)
    return kq


async def search_media(*args, **kwargs) -> list[dict]:
    """Vỏ mỏng quanh `search_media_detailed` — chỉ trả items.

    Giữ lại vì hai lý do rời nhau: hợp đồng cũ (một call site + hơn hai chục test
    đang gọi) không phải đổi, và phần lớn chỗ dùng thật sự không quan tâm cờ
    fallback. Ai cần cờ thì gọi thẳng hàm kia.
    """
    return (await search_media_detailed(*args, **kwargs)).items
