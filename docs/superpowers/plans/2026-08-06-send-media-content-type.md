# `send_media` content_type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho `send_media` nhận thêm param `content_type` (`image`|`video`) và biến `category` thành optional, để khách xin video dự án thì nhận được video.

**Architecture:** `content_type` là hard filter thêm vào `build_scope_filter` (một `FieldCondition` nữa trong `must`) — không sửa `search_hybrid`, nên `kb_search` không bị ảnh hưởng. Cả `category` và `content_type` optional ở schema, nhưng `support_ops.send_media` từ chối khi **rỗng cả hai** bằng `_retry_payload` sẵn có. `_map_items` nhận `max_videos` để nhánh xin-video trả tối đa 3 video thay vì 1.

**Tech Stack:** Python 3.11+, pytest (`asyncio_mode=auto`), qdrant-client (import lazy), ruff.

**Spec:** [docs/superpowers/specs/2026-08-06-send-media-content-type-design.md](../specs/2026-08-06-send-media-content-type-design.md)

## Global Constraints

- **Đang ở nhánh `develop`. CLAUDE.md cấm sửa/commit trên `develop`.** Trước Task 1 phải có nhánh feature; tạo nhánh cần user chấp thuận rõ ràng.
- **Người dùng tự chạy git.** Mọi bước "Commit" trong plan này là **đưa lệnh cho người dùng**, không tự chạy (quy ước của repo/user).
- Ruff: line-length **120**, target **py311**, rules `E,F,W,I,UP,B,SIM`. `make lint` phải sạch trên mọi file đã sửa.
- Gate test: **0 failure mới** so với baseline (`git archive HEAD` chạy cùng `.env`). Repo có sẵn một số test đỏ do thiếu optional dep ở venv local — không tính là hồi quy.
- `SEND_MEDIA_CONTENT_TYPES = ("image", "video")` là single source of truth duy nhất; không hard-code chuỗi `"video"`/`"image"` ở validation.
- Enum `SEND_MEDIA_CATEGORIES` giữ nguyên 8 giá trị, không thêm/bớt.
- `kb_search` không được đổi hành vi: nó gọi `build_scope_filter` **không** truyền `content_type`.
- Không support `.mp4` (non-goal §8 của spec). Không đụng `search_hybrid`, `thumb_url`, rendition `medium`.

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/noble_agent/data/qdrant_search.py` | dựng filter Qdrant — thêm chiều `content_type` | 1 |
| `tests/unit/unified/test_qdrant_search.py` | test filter | 1 |
| `src/noble_agent/data/media_data.py` | pipeline search media — nhận `content_type`, cache key, cap video | 2 |
| `tests/unit/unified/test_send_media.py` | test `search_media` + `_map_items` + `support_ops` | 2, 4 |
| `src/noble_agent/agent/tools/schemas.py` | hợp đồng tool cho LLM | 3 |
| `tests/unit/unified/test_tool_schemas.py` | test schema | 3 |
| `src/noble_agent/agent/tools/support_ops.py` | validation + fallback query + truyền xuống | 4 |
| `src/noble_agent/persona/RULES.md` | prompt đường **db-mode** | 5 |
| `src/noble_agent/tenants/noble/persona/RULES.md` | prompt đường **legacy** | 5 |
| `scripts/test_search_tools.py` | công cụ live-verify (`make test-search`) | 6 |

Thứ tự phụ thuộc: 1 → 2 → 4; 3 → 4; 5 và 6 sau cùng.

---

### Task 0: Nhánh feature

**Files:** không sửa file nào.

- [ ] **Step 1: Xác nhận nhánh hiện tại**

Run: `git branch --show-current`
Expected: `develop` — nếu đúng thì KHÔNG được sửa gì, phải tách nhánh.

- [ ] **Step 2: Đưa lệnh cho user tách nhánh (user tự chạy, cần chấp thuận)**

```bash
git checkout -b feat/send-media-content-type
```

- [ ] **Step 3: Xác nhận đã sang nhánh mới**

Run: `git branch --show-current`
Expected: `feat/send-media-content-type`

---

### Task 1: `build_scope_filter` nhận `content_type`

**Files:**
- Modify: `src/noble_agent/data/qdrant_search.py:112-140`
- Test: `tests/unit/unified/test_qdrant_search.py` (thêm sau `test_scope_filter_ignores_blank_category`, ~dòng 111)

**Interfaces:**
- Consumes: không có (task đầu)
- Produces: `build_scope_filter(project_codes: list[str] | None, *, category: str | None = None, content_type: str | None = None, sentinel: str = SYSTEM_ANCHOR) -> models.Filter | None`. Thứ tự condition trong `must`: `project_id`, `category`, `content_type`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/unit/unified/test_qdrant_search.py`, ngay sau `test_scope_filter_ignores_blank_category`:

```python
def test_scope_filter_content_type_only():
    flt = sq.build_scope_filter([], content_type="video")
    assert len(flt.must) == 1
    assert flt.must[0].key == "content_type"
    assert flt.must[0].match.value == "video"


def test_scope_filter_project_category_content_type_are_all_anded():
    flt = sq.build_scope_filter(["NPLB"], category="tien_do", content_type="video")
    assert [c.key for c in flt.must] == ["project_id", "category", "content_type"]


def test_scope_filter_content_type_without_category():
    """Khách xin video chung: content_type lọc, category không — đây là ca chính."""
    flt = sq.build_scope_filter(["MEL"], content_type="video")
    assert [c.key for c in flt.must] == ["project_id", "content_type"]


def test_scope_filter_ignores_blank_content_type():
    assert sq.build_scope_filter([], content_type="") is None
    assert sq.build_scope_filter([], content_type="  ") is None
```

- [ ] **Step 2: Chạy test để chắc chắn nó fail**

Run: `pytest tests/unit/unified/test_qdrant_search.py -k content_type -v`
Expected: FAIL — `TypeError: build_scope_filter() got an unexpected keyword argument 'content_type'`

- [ ] **Step 3: Sửa `build_scope_filter`**

Trong `src/noble_agent/data/qdrant_search.py`, thay cả hàm:

```python
def build_scope_filter(
    project_codes: list[str] | None,
    *,
    category: str | None = None,
    content_type: str | None = None,
    sentinel: str = SYSTEM_ANCHOR,
):
    """Qdrant filter cho ``project_id`` (+ optional ``category``/``content_type``), hoặc None.

    No project codes → no project condition, i.e. search the whole tenant. With
    codes → ``project_id IN sorted({*codes, sentinel})``: the sentinel union is
    what keeps tenant-level content (a shared brochure, a tenant-wide policy doc)
    visible when the customer asked about one project. ``category`` và
    ``content_type`` là exact match ANDed in — chỉ send_media truyền, kb_search
    không bao giờ truyền. Mỗi param rỗng/blank → không thêm điều kiện, tức là
    không lọc theo chiều đó.
    """
    from qdrant_client import models

    must = []
    codes = [c.strip() for c in (project_codes or []) if (c or "").strip()]
    if codes:
        must.append(
            models.FieldCondition(
                key="project_id",
                match=models.MatchAny(any=sorted({*codes, sentinel})),
            )
        )
    cat = (category or "").strip()
    if cat:
        must.append(models.FieldCondition(key="category", match=models.MatchValue(value=cat)))
    ctype = (content_type or "").strip()
    if ctype:
        must.append(models.FieldCondition(key="content_type", match=models.MatchValue(value=ctype)))
    return models.Filter(must=must) if must else None
```

- [ ] **Step 4: Chạy test — cả file, để chắc `kb_search` không hồi quy**

Run: `pytest tests/unit/unified/test_qdrant_search.py -v`
Expected: PASS toàn bộ (các test `build_scope_filter` cũ vẫn xanh — thêm param có default không đổi hành vi cũ)

- [ ] **Step 5: Lint**

Run: `ruff check src/noble_agent/data/qdrant_search.py tests/unit/unified/test_qdrant_search.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit (đưa lệnh cho user)**

```bash
git add src/noble_agent/data/qdrant_search.py tests/unit/unified/test_qdrant_search.py
git commit -m "feat(search): build_scope_filter nhận content_type"
```

---

### Task 2: `search_media` nhận `content_type`, cache key, cap video

**Files:**
- Modify: `src/noble_agent/data/media_data.py` (hằng ~dòng 34, `_map_items` 103-116, `search_media` 166-234)
- Test: `tests/unit/unified/test_send_media.py` (thêm sau `test_map_items_caps_images_and_single_video` ~dòng 130, và trong khối `search_media` ~dòng 244+)

**Interfaces:**
- Consumes: `qdrant_search.build_scope_filter(..., content_type=...)` từ Task 1
- Produces:
  - `MAX_VIDEOS_WHEN_REQUESTED = 3` (module-level, `media_data`)
  - `_map_items(hits: list[dict], *, max_videos: int = 1) -> list[dict]`
  - `search_media(query, project_code, category, *, tenant_id, qdrant_url, qdrant_api_key="", content_type="", top_k=10, threshold=0.0, qdrant_timeout=10.0, cache_ttl=300.0, with_visual=False) -> list[dict]`

- [ ] **Step 1: Viết test thất bại cho `_map_items`**

Thêm vào `tests/unit/unified/test_send_media.py` ngay sau `test_map_items_caps_images_and_single_video`:

```python
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
```

- [ ] **Step 2: Chạy test để chắc chắn fail**

Run: `pytest tests/unit/unified/test_send_media.py -k map_items -v`
Expected: FAIL — `test_map_items_respects_max_videos` báo `TypeError: _map_items() got an unexpected keyword argument 'max_videos'`

- [ ] **Step 3: Thêm hằng + sửa `_map_items`**

Trong `src/noble_agent/data/media_data.py`, cạnh `MAX_IMAGES = 6`:

```python
MAX_IMAGES = 6
# Khách xin đích danh video (`content_type="video"`) thì nhận cả bộ video của dự án;
# nhánh chủ động giới thiệu vẫn giữ ≤1 để không lấn ảnh.
MAX_VIDEOS_WHEN_REQUESTED = 3
```

Thay cả `_map_items`:

```python
def _map_items(hits: list[dict], *, max_videos: int = 1) -> list[dict]:
    """Map score-sorted hits → items: ≤MAX_IMAGES images then ≤max_videos videos."""
    images: list[dict] = []
    videos: list[dict] = []
    for hit in hits:
        item = _hit_to_item(hit)
        if item is None:
            continue
        if item["kind"] == "image":
            if len(images) < MAX_IMAGES:
                images.append(item)
        elif item["kind"] == "video" and len(videos) < max_videos:
            videos.append(item)
    return images + videos
```

- [ ] **Step 4: Chạy test `_map_items`**

Run: `pytest tests/unit/unified/test_send_media.py -k map_items -v`
Expected: PASS (kể cả `test_map_items_caps_images_and_single_video` cũ — default `max_videos=1` giữ nguyên hành vi)

- [ ] **Step 5: Viết test thất bại cho `search_media`**

Thêm vào `tests/unit/unified/test_send_media.py`, trong khối `search_media` (sau `test_search_media_filters_project_with_sentinel_and_category`):

```python
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
    assert cap["search_calls"] == 2


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
```

- [ ] **Step 6: Chạy test để chắc chắn fail**

Run: `pytest tests/unit/unified/test_send_media.py -k "content_type or up_to_three or single_video_cap" -v`
Expected: FAIL — `TypeError: search_media() got an unexpected keyword argument 'content_type'`

- [ ] **Step 7: Sửa `search_media`**

Trong `src/noble_agent/data/media_data.py`, sửa signature — thêm `content_type` ngay trước `top_k`:

```python
async def search_media(
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
) -> list[dict]:
```

Bổ sung 2 dòng vào docstring, ngay sau đoạn nói về `with_visual`:

```
    ``content_type`` (``"image"``|``"video"``, rỗng = cả hai) là hard filter trên
    payload. Khi bằng ``"video"``, cap video nới từ 1 lên ``MAX_VIDEOS_WHEN_REQUESTED``.
```

Sửa cache key (thêm `content_type` giữa `category` và `with_visual`):

```python
    key = f"{collection}|{query}|{top_k}|{threshold}|{project_code}|{category}|{content_type}|{with_visual}"
```

Truyền xuống filter:

```python
        filter_=qdrant_client.build_scope_filter(
            [project_code] if project_code else [],
            category=category,
            content_type=content_type,
        ),
```

Và đổi 2 dòng cuối (chỗ map + cache):

```python
    hits = [{**p, "project_code": p.get("project_id", "")} for p in points]
    max_videos = MAX_VIDEOS_WHEN_REQUESTED if content_type == "video" else 1
    items = _map_items(hits, max_videos=max_videos)
    _cache.set(key, items, cache_ttl)
    return items
```

- [ ] **Step 8: Chạy cả file test**

Run: `pytest tests/unit/unified/test_send_media.py -v`
Expected: PASS hết trừ các test `support_ops` neo `missing_category` (chưa sửa — Task 4). Nếu có test `support_ops` đỏ ở bước này thì đúng như dự kiến, ghi lại tên và đi tiếp.

- [ ] **Step 9: Lint**

Run: `ruff check src/noble_agent/data/media_data.py tests/unit/unified/test_send_media.py`
Expected: `All checks passed!`

- [ ] **Step 10: Commit (đưa lệnh cho user)**

```bash
git add src/noble_agent/data/media_data.py tests/unit/unified/test_send_media.py
git commit -m "feat(media): search_media nhận content_type + cap video riêng"
```

---

### Task 3: Schema — thêm `content_type`, `category` optional

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py` (hằng ~dòng 17, block `send_media` 566-601)
- Test: `tests/unit/unified/test_tool_schemas.py` (thêm cuối file)

**Interfaces:**
- Consumes: không có
- Produces: `SEND_MEDIA_CONTENT_TYPES: tuple[str, str] = ("image", "video")` export từ `noble_agent.agent.tools.schemas`. Schema `send_media` có `required == ["query"]` và 4 property: `query`, `project_code`, `category`, `content_type`.

- [ ] **Step 1: Viết test thất bại**

Sửa dòng import đầu `tests/unit/unified/test_tool_schemas.py`:

```python
from noble_agent.agent.tools.schemas import SCHEMAS, SEND_MEDIA_CONTENT_TYPES, schemas_for
```

Thêm vào cuối file:

```python
def test_send_media_requires_only_query():
    params = SCHEMAS["send_media"]["function"]["parameters"]
    assert params["required"] == ["query"]
    assert set(params["properties"]) == {"query", "project_code", "category", "content_type"}


def test_send_media_content_type_enum_matches_source_of_truth():
    props = SCHEMAS["send_media"]["function"]["parameters"]["properties"]
    assert SEND_MEDIA_CONTENT_TYPES == ("image", "video")
    assert props["content_type"]["enum"] == list(SEND_MEDIA_CONTENT_TYPES)


def test_send_media_category_copy_no_longer_says_mandatory():
    """category giờ optional — mô tả không được còn ép LLM luôn điền."""
    props = SCHEMAS["send_media"]["function"]["parameters"]["properties"]
    assert "BẮT BUỘC" not in props["category"]["description"]


def test_send_media_description_tells_llm_to_pass_at_least_one():
    desc = SCHEMAS["send_media"]["function"]["description"]
    assert "ÍT NHẤT MỘT" in desc
    assert "content_type=video" in desc
```

- [ ] **Step 2: Chạy test để chắc chắn fail**

Run: `pytest tests/unit/unified/test_tool_schemas.py -k send_media -v`
Expected: FAIL — `ImportError: cannot import name 'SEND_MEDIA_CONTENT_TYPES'`

- [ ] **Step 3: Thêm hằng**

Trong `src/noble_agent/agent/tools/schemas.py`, ngay sau khối `SEND_MEDIA_CATEGORIES`:

```python
# Valid `send_media.content_type` values (single source of truth — reused by the
# schema enum and by support_ops validation).
SEND_MEDIA_CONTENT_TYPES = ("image", "video")
```

- [ ] **Step 4: Thay block `send_media` trong `SCHEMAS`**

```python
    "send_media": {
        "type": "function",
        "function": {
            "name": "send_media",
            "description": (
                "Gửi hình ảnh/video dự án cho khách qua ứng dụng {{ brand.app_name }}: mặt bằng, phối cảnh, "
                "tiện ích, vị trí — những nội dung khó diễn đạt bằng lời nói. Ảnh và video hiện "
                "ngay trong app. Phải truyền ÍT NHẤT MỘT trong category / content_type: chủ động giới "
                "thiệu tổng quan dự án → category=tong_quan; khách xin video → content_type=video. "
                "Gọi ÂM THẦM: TUYỆT ĐỐI KHÔNG nói câu thông "
                "báo/filler nào về việc gửi ('em gửi qua app', 'chờ em một chút'...) — ảnh tự "
                "hiện trong app, cứ tiếp tục tư vấn bình thường."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Câu hỏi/yêu cầu nguyên văn của khách (tiếng Việt)."},
                    "project_code": {
                        "type": "string",
                        "description": (
                            "Mã dự án canonical do find_project trả về; bỏ trống để dùng dự án đang quan tâm."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": list(SEND_MEDIA_CATEGORIES),
                        "description": (
                            "Loại media: tong_quan (tổng quan), ngoai_that (ngoại thất), "
                            "noi_that (nội thất), tien_ich (tiện ích), mat_bang (mặt bằng), "
                            "vi_tri (vị trí), phap_ly (pháp lý), tien_do (tiến độ). "
                            "Chủ động giới thiệu tổng quan dự án → dùng tong_quan. "
                            "Khách xin video chung mà không nói rõ loại → BỎ TRỐNG."
                        ),
                    },
                    "content_type": {
                        "type": "string",
                        "enum": list(SEND_MEDIA_CONTENT_TYPES),
                        "description": (
                            "video khi khách xin video/clip/quay dự án; image khi khách xin ảnh/hình. "
                            "Bỏ trống = cả hai loại."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
```

- [ ] **Step 5: Chạy test**

Run: `pytest tests/unit/unified/test_tool_schemas.py -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Kiểm brand-render không vỡ (description có `{{ brand.app_name }}`)**

Run: `pytest tests/unit/unified/test_brand_and_rankers.py -v`
Expected: PASS — token `{{ brand.app_name }}` vẫn render, không rò ra ngoài

- [ ] **Step 7: Lint**

Run: `ruff check src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_tool_schemas.py`
Expected: `All checks passed!`

- [ ] **Step 8: Commit (đưa lệnh cho user)**

```bash
git add src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_tool_schemas.py
git commit -m "feat(tools): schema send_media thêm content_type, category thành optional"
```

---

### Task 4: `support_ops.send_media` — validation + fallback query + truyền xuống

**Files:**
- Modify: `src/noble_agent/agent/tools/support_ops.py:170-247`
- Test: `tests/unit/unified/test_send_media.py` (sửa `test_send_media_missing_category_returns_retry` ~dòng 427; thêm test mới sau nó)

**Interfaces:**
- Consumes: `SEND_MEDIA_CONTENT_TYPES` (Task 3); `media_data.search_media(..., content_type=...)` (Task 2)
- Produces: `send_media(customer, args: dict, session_id: str) -> str`. Mã lỗi retry: `missing_filter`, `invalid_category`, `invalid_content_type`, `missing_project_code`. Mã `missing_category` **bị xoá**.

- [ ] **Step 1: Sửa test cũ + viết test mới (đều đang fail)**

Trong `tests/unit/unified/test_send_media.py`, **thay** cả `test_send_media_missing_category_returns_retry` bằng:

```python
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
        await support_ops.send_media(
            Customer(), {"query": "x", "project_code": "NCR", "content_type": "gif"}, "sid-ct"
        )
    )
    assert out["ok"] is False
    assert out["error"] == "invalid_content_type"
    assert out["retry"] is True
    assert "gif" in out["message"]
    assert fake.calls == []


async def test_send_media_content_type_normalized(monkeypatch):
    fake = _stub_search(monkeypatch, items=[{"kind": "video", "video_id": "dQw4w9WgXcQ", "title": "c"}])
    await support_ops.send_media(
        Customer(), {"query": "x", "project_code": "NCR", "content_type": " VIDEO "}, "sid-n"
    )
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
```

- [ ] **Step 2: Chạy test để chắc chắn fail**

Run: `pytest tests/unit/unified/test_send_media.py -k "missing_both or content_type_only or invalid_content_type or content_type_normalized or search_query_fallback" -v`
Expected: FAIL — `missing_both` nhận `error == "missing_category"`; các test content_type nhận `missing_category` thay vì chạy search

- [ ] **Step 3: Sửa `support_ops.send_media`**

Trong `src/noble_agent/agent/tools/support_ops.py`, thay đoạn từ dòng import trong hàm tới hết khối gọi `search_media`:

```python
    from noble_agent.agent.tools.schemas import SEND_MEDIA_CATEGORIES, SEND_MEDIA_CONTENT_TYPES

    query = (args.get("query") or "").strip()
    category = (args.get("category") or "").strip().lower()
    content_type = (args.get("content_type") or "").strip().lower()

    code_raw = args.get("project_code") or ""
    if isinstance(code_raw, list):  # defensive: a model may still send an array
        code_raw = code_raw[0] if code_raw else ""
    code = str(code_raw).strip().upper()
    if not code and customer.project_interest:
        code = customer.project_interest.strip().upper()

    # ── arg validation → actionable retry messages (LLM re-calls with fixes) ──
    # Cả category và content_type đều optional, nhưng rỗng CẢ HAI thì không rõ
    # khách muốn gì: nhánh chủ động giới thiệu cần tong_quan (ảnh phối cảnh, nhẹ),
    # bỏ trống sẽ lôi cả bản vẽ mặt bằng nhiều MB.
    cats = ", ".join(SEND_MEDIA_CATEGORIES)
    ctypes = ", ".join(SEND_MEDIA_CONTENT_TYPES)
    if not category and not content_type:
        logger.info("[send_media] sid=%s missing category and content_type", session_id)
        return _retry_payload(
            "missing_filter",
            f"Cần ít nhất một trong category ({cats}) hoặc content_type ({ctypes}). "
            "Giới thiệu tổng quan dự án → category=tong_quan; khách xin video → content_type=video.",
        )
    if category and category not in SEND_MEDIA_CATEGORIES:
        logger.info("[send_media] sid=%s invalid category=%s", session_id, category)
        return _retry_payload(
            "invalid_category",
            f"category '{category}' không hợp lệ. Hãy gọi lại send_media với category là một trong: {cats}.",
        )
    if content_type and content_type not in SEND_MEDIA_CONTENT_TYPES:
        logger.info("[send_media] sid=%s invalid content_type=%s", session_id, content_type)
        return _retry_payload(
            "invalid_content_type",
            f"content_type '{content_type}' không hợp lệ. "
            f"Hãy gọi lại send_media với content_type là một trong: {ctypes}.",
        )
    if not code:
        logger.info("[send_media] sid=%s no project code/interest", session_id)
        return _retry_payload(
            "missing_project_code",
            "Chưa xác định dự án. Hãy gọi lại send_media kèm project_code là mã dự án khách muốn xem hình.",
        )

    from noble_agent.tenant.current import current_tenant

    settings = get_settings()
    if not settings.qdrant_url:
        logger.warning("[send_media] sid=%s code=%s qdrant_url not configured", session_id, code)
        return _no_media_payload()

    # category có thể rỗng → ghép từ các phần non-rỗng để không ra hai khoảng trắng.
    noun = "video" if content_type == "video" else "hình ảnh"
    search_query = query or " ".join(p for p in (noun, category, "dự án") if p)
    try:
        items = await media_data.search_media(
            search_query,
            code,
            category,
            tenant_id=current_tenant(),
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            content_type=content_type,
            top_k=settings.media_search_top_k,
            threshold=settings.media_search_threshold,
            qdrant_timeout=settings.qdrant_timeout,
            cache_ttl=settings.media_search_cache_ttl,
            with_visual=bool(settings.embed_service_url),
        )
```

Sửa docstring của hàm — thay câu tả param bằng:

```
    Runs a Qdrant hybrid text+visual search (``media_data.search_media``) over the
    current tenant's media collection for the given project code (else
    ``customer.project_interest``), lọc theo ``category`` và/hoặc ``content_type``
    (cả hai optional nhưng không được rỗng cả hai), và trả về ``items[]`` payload
    mà chat/voice forward nguyên văn cho client. On any failure — no project code,
    unconfigured infra, no renderable media, or a Qdrant/embed error — returns the
    degraded ``no_media`` payload and never raises.
```

- [ ] **Step 4: Chạy cả file test**

Run: `pytest tests/unit/unified/test_send_media.py -v`
Expected: PASS toàn bộ, kể cả các test cũ (`invalid_category`, `missing_project_code`, `category_uppercase_normalized`, `success_payload`)

- [ ] **Step 5: Chạy các suite liên quan để chắc không hồi quy chỗ khác**

Run: `pytest tests/unit/unified/test_qdrant_search.py tests/unit/unified/test_tool_schemas.py tests/unit/test_voice_media_forwarding.py tests/unit/unified/test_dispatch_registry.py -v`
Expected: PASS (dispatcher `_strip_display_items` + forward `items[]` không đổi)

- [ ] **Step 6: Lint**

Run: `ruff check src/noble_agent/agent/tools/support_ops.py tests/unit/unified/test_send_media.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit (đưa lệnh cho user)**

```bash
git add src/noble_agent/agent/tools/support_ops.py tests/unit/unified/test_send_media.py
git commit -m "feat(tools): send_media validate category/content_type, chặn rỗng cả hai"
```

---

### Task 5: Prompt — 2 file RULES.md, 4 chỗ

**Files:**
- Modify: `src/noble_agent/persona/RULES.md` (rule 12 ~dòng 114-133; bảng tool catalog ~dòng 183)
- Modify: `src/noble_agent/tenants/noble/persona/RULES.md` (rule 12 ~dòng 102-121; bảng tool catalog ~dòng 150)

**Interfaces:**
- Consumes: tên param từ Task 3 (`content_type`, giá trị `image`/`video`)
- Produces: không có API mới. `tenants/demo_acme` không enable `send_media` → không đụng.

- [ ] **Step 1: Sửa câu "category BẮT BUỘC" — GIỐNG NHAU ở CẢ HAI file**

Tìm (cả 2 file có chuỗi này byte-identical):

```
    ngầm. category BẮT BUỘC, chọn một trong: tong_quan, ngoai_that, noi_that,
    tien_ich, mat_bang (mặt bằng), vi_tri (vị trí), phap_ly (pháp lý),
    tien_do (tiến độ). Gọi trong HAI trường hợp:
```

Thay bằng:

```
    ngầm. Phải truyền ÍT NHẤT MỘT trong category / content_type. category chọn
    một trong: tong_quan, ngoai_that, noi_that, tien_ich, mat_bang (mặt bằng),
    vi_tri (vị trí), phap_ly (pháp lý), tien_do (tiến độ). content_type: video
    hoặc image, bỏ trống là cả hai. Gọi trong BA trường hợp:
```

- [ ] **Step 2: Thêm nhánh thứ ba vào rule 12 — CẢ HAI file**

Trong `src/noble_agent/persona/RULES.md`, tìm:

```
    - PHẢN HỒI khi khách hỏi nội dung trực quan cụ thể (ảnh, mặt bằng, vị trí,
      tiện ích, nội/ngoại thất...) → truyền category đúng loại khách hỏi.
```

Trong `src/noble_agent/tenants/noble/persona/RULES.md`, tìm (bản này ngắn hơn):

```
    - PHẢN HỒI khi khách hỏi nội dung trực quan cụ thể → truyền category đúng
      loại khách hỏi.
```

Ở **cả hai**, thêm ngay sau bullet đó:

```
    - KHÁCH XIN VIDEO ("cho xem video", "có clip nào không", "quay dự án") →
      content_type=video và BỎ TRỐNG category, trừ khi khách nói rõ loại video
      (vd "video tiến độ" → thêm category=tien_do). Video của một dự án nằm rải
      rác ở nhiều category khác nhau, nên truyền category=tong_quan theo quán
      tính sẽ KHÔNG ra video.
```

- [ ] **Step 3: Sửa dòng retry — CẢ HAI file**

Tìm (byte-identical ở cả 2):

```
    Nếu tool trả về error/retry (thiếu category, category sai, thiếu dự án) →
```

Thay bằng:

```
    Nếu tool trả về error/retry (thiếu cả category và content_type, giá trị sai,
    thiếu dự án) →
```

- [ ] **Step 4: Sửa dòng signature ở đầu rule 12 — CẢ HAI file**

Tìm:

```
    project_code=<MÃ>, category=<loại>). Gọi ÂM THẦM: TUYỆT ĐỐI KHÔNG nói bất
```

Thay bằng:

```
    project_code=<MÃ>, category=<loại>, content_type=<video|image>). Gọi ÂM
    THẦM: TUYỆT ĐỐI KHÔNG nói bất
```

- [ ] **Step 5: Sửa dòng bảng tool catalog trong `src/noble_agent/persona/RULES.md`**

Thay cả dòng bắt đầu bằng `| Giới thiệu/tổng quan MỘT dự án` (trong khối `<!-- TOOL:send_media:START -->` thứ hai, ~dòng 183) bằng:

```
| Giới thiệu/tổng quan MỘT dự án (chủ động kèm ảnh) HOẶC khách hỏi ảnh/mặt bằng/vị trí/tiện ích/nội-ngoại thất HOẶC khách xin video | send_media(query, project_code=<MÃ>, category=<tong_quan/ngoai_that/noi_that/tien_ich/mat_bang/vi_tri/phap_ly/tien_do>, content_type=<video/image>) — truyền ÍT NHẤT MỘT trong category/content_type; chủ động giới thiệu → category=tong_quan; khách xin video → content_type=video, bỏ trống category; gọi ÂM THẦM, KHÔNG nói câu thông báo/filler; mỗi dự án gửi 1 lần; ảnh/video hiện ngay trong app (quy tắc 12) |
```

- [ ] **Step 6: Sửa dòng bảng tool catalog trong `src/noble_agent/tenants/noble/persona/RULES.md`**

Dòng 150 của file legacy KHÔNG có đuôi `(quy tắc 12)` (khác bản db-mode). Thay cả dòng đó bằng:

```
| Giới thiệu/tổng quan MỘT dự án (chủ động kèm ảnh) HOẶC khách hỏi ảnh/mặt bằng/vị trí/tiện ích/nội-ngoại thất HOẶC khách xin video | send_media(query, project_code=<MÃ>, category=<tong_quan/ngoai_that/noi_that/tien_ich/mat_bang/vi_tri/phap_ly/tien_do>, content_type=<video/image>) — truyền ÍT NHẤT MỘT trong category/content_type; chủ động giới thiệu → category=tong_quan; khách xin video → content_type=video, bỏ trống category; gọi ÂM THẦM, KHÔNG nói câu thông báo/filler; mỗi dự án gửi 1 lần; ảnh/video hiện ngay trong app |
```

- [ ] **Step 7: Verify — không còn chỗ nào ép category bắt buộc**

Run: `grep -n "category BẮT BUỘC" src/noble_agent/persona/RULES.md src/noble_agent/tenants/noble/persona/RULES.md`
Expected: không có output (exit 1)

Run: `grep -c "content_type" src/noble_agent/persona/RULES.md src/noble_agent/tenants/noble/persona/RULES.md`
Expected: mỗi file ≥ 4

- [ ] **Step 8: Verify prompt vẫn build được ở CẢ HAI đường config**

Run:
```bash
python -c "
from noble_agent.tenant.loader import get_tenant_context
from noble_agent.agent.base import load_agent_def
ctx = get_tenant_context()
d = load_agent_def(ctx.persona_dir, tool_names=list(ctx.enabled_tools), brand=dict(ctx.brand))
assert 'send_media' in d.tool_names
print('legacy OK — tools:', len(d.tool_names))
print('content_type in RULES:', 'content_type' in d.rules)
"
```
Expected: `legacy OK — tools: 12` (đã xác nhận `manifest.toml` enable đúng 12 tool) và `content_type in RULES: True`

- [ ] **Step 9: Chạy các test neo prompt**

Run: `pytest tests/unit/unified/test_agent_def.py tests/unit/unified/test_persona_compose.py tests/unit/unified/test_prompt_builder.py -v`
Expected: PASS, hoặc chỉ còn các failure đã có trong baseline (ghi rõ tên nếu có)

- [ ] **Step 10: Commit (đưa lệnh cho user)**

```bash
git add src/noble_agent/persona/RULES.md src/noble_agent/tenants/noble/persona/RULES.md
git commit -m "docs(prompt): dạy Luna dùng content_type khi khách xin video"
```

---

### Task 6: `scripts/test_search_tools.py` — live-verify được `content_type`

**Files:**
- Modify: `scripts/test_search_tools.py` (`DEFAULT_MEDIA` ~dòng 61, `_HELP` 187-197, `run_media` 141-172, `interactive` 200-264, `main` 267-300)

**Interfaces:**
- Consumes: `media_data.search_media(..., content_type=...)` (Task 2)
- Produces: `run_media(tenant: str, cases: list[tuple[str, str, str]], project: str, s) -> int` — cases là `(query, category, content_type)`. CLI thêm `--content-type`; interactive thêm `/ct`.

- [ ] **Step 1: Đổi `DEFAULT_MEDIA` sang 3-tuple + thêm case video**

```python
DEFAULT_MEDIA = [
    ("phối cảnh tổng thể dự án", "tong_quan", ""),
    ("tiện ích hồ bơi", "tien_ich", ""),
    ("video dự án", "", "video"),  # ca hồi quy: video nằm rải rác category
]
```

- [ ] **Step 2: Sửa `run_media`**

```python
async def run_media(tenant: str, cases: list[tuple[str, str, str]], project: str, s) -> int:
    hr(f"send_media  ·  {tenant}_media")
    empty = 0
    for query, category, content_type in cases:
        items = await media_data.search_media(
            query, project, category,
            tenant_id=tenant,
            qdrant_url=s.qdrant_url,
            qdrant_api_key=s.qdrant_api_key,
            content_type=content_type,
            top_k=s.media_search_top_k,
            threshold=s.media_search_threshold,
            qdrant_timeout=s.qdrant_timeout,
            cache_ttl=0.0,  # bypass the cache so each run really hits the backends
        )
        scope = f"project={project}, " if project else ""
        ct = f", content_type={content_type}" if content_type else ""
        mark = BAD if not items else OK
        print(f"\n  {mark} {query!r} ({scope}category={category or '-'}{ct}) → {len(items)} item")
        if not items:
            empty += 1
        for it in items:
            if it["kind"] == "image":
                print(f"       [image] {it['url'][:88]}")
                if it.get("label"):
                    print(f"               {it['label'].splitlines()[0][:80]!r}")
            else:
                print(f"       [video] youtube={it['video_id']}  {it['title'][:60]!r}")
    return empty
```

- [ ] **Step 3: Thêm `/ct` vào `_HELP`**

Thêm một dòng ngay sau dòng `/cat <category>`:

```
  /ct [image|video]   lọc theo content_type; không tham số = bỏ lọc
```

- [ ] **Step 4: Thêm state + lệnh `/ct` vào `interactive`**

Đổi dòng khởi tạo state:

```python
    mode, category, project, top_k = "kb", "tong_quan", "", s.kb_search_top_k
    ctype = ""
```

Trong `prompt()`, sau `bits.append(category)`:

```python
        if mode == "media":
            bits.append(category or "-")
            if ctype:
                bits.append(ctype)
```

Thêm nhánh lệnh ngay sau nhánh `elif cmd == "cat":`:

```python
            elif cmd == "ct":
                ctype = rest.strip().lower()
                print(f"  content_type = {ctype or '(cả hai)'}")
```

Đổi nhánh `/cat` để cho phép xoá category (giờ nó optional):

```python
            elif cmd == "cat":
                category = rest
                print(f"  category = {category or '(không lọc)'}")
```

Đổi 3 chỗ gọi `run_media` trong `interactive` (nhánh `/both` và nhánh cuối) sang 3-tuple:

```python
                    await run_media(tenant, [(rest, category, ctype)], project, s)
```

```python
            await run_media(tenant, [(line, category, ctype)], project, s)
```

- [ ] **Step 5: Thêm `--content-type` vào `main`**

Sau dòng `p.add_argument("--category", ...)`:

```python
    p.add_argument("--content-type", default="", choices=["", "image", "video"], help="lọc image/video cho --media")
```

Và đổi dòng dựng `media_cases`:

```python
    media_cases = (
        [(q, args.category, args.content_type) for q in args.media] if args.media else DEFAULT_MEDIA
    )
```

- [ ] **Step 6: Lint + smoke import**

Run: `ruff check scripts/test_search_tools.py && python -c "import ast,sys; ast.parse(open('scripts/test_search_tools.py').read()); print('parse OK')"`
Expected: `All checks passed!` rồi `parse OK`

- [ ] **Step 7: Live-verify tầng dữ liệu (cần SSM tunnel mở)**

Run: `scripts/qdrant_tunnel.sh &` rồi `make test-search ARGS="-t an-phu-land_q8w2_retail --media 'video dự án' --content-type video"`
Expected: trả về **video** (MEL/LEP, category `tien_do`) — trước khi có feature này thì ca đó ra 0 item hoặc ra ảnh.

Run: `make test-search ARGS="-t noble-homes_k3n7_retail --project VRI --media 'video' --content-type video"`
Expected: tối đa 3 video (VRI có 3 video, 1 trong đó là `.mp4` bị drop theo non-goal → kỳ vọng 2 video YouTube)

Run: `make test-search ARGS="-t an-phu-land_q8w2_retail"`
Expected: 2 case ảnh đầu vẫn có kết quả như trước (không hồi quy), case video thứ 3 có kết quả

- [ ] **Step 8: Commit (đưa lệnh cho user)**

```bash
git add scripts/test_search_tools.py
git commit -m "chore(scripts): test-search hỗ trợ content_type"
```

---

### Task 7: Gate cuối + cập nhật CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (bảng tool catalog trong `agent/tools/` row; mục "Media search (`send_media`)"; Change Log)

**Interfaces:**
- Consumes: kết quả của Task 1-6
- Produces: không có API mới

- [ ] **Step 1: Baseline để so failure**

Run:
```bash
mkdir -p /tmp/baseline-sm && git archive HEAD | tar -x -C /tmp/baseline-sm
cd /tmp/baseline-sm && cp /home/thanhhai/Desktop/odyssey-agent/.env . && python -m pytest tests/unit -q 2>&1 | tail -3
```
Expected: ghi lại con số `N failed, M passed` làm baseline

- [ ] **Step 2: Chạy gate trên nhánh feature**

Run: `make test-unit 2>&1 | tail -3`
Expected: số `failed` **không lớn hơn** baseline; `passed` tăng đúng bằng số test mới thêm

- [ ] **Step 3: Lint toàn bộ file đã sửa**

Run:
```bash
ruff check src/noble_agent/data/qdrant_search.py src/noble_agent/data/media_data.py \
  src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/support_ops.py \
  scripts/test_search_tools.py tests/unit/unified/test_send_media.py \
  tests/unit/unified/test_qdrant_search.py tests/unit/unified/test_tool_schemas.py
```
Expected: `All checks passed!`

- [ ] **Step 4: Live-verify tầng agent (cần Redis + LLM key + tunnel)**

Run: `python scripts/chat_repl.py -t <tenant db-mode>` rồi lần lượt:
1. `"cho xem video dự án MEL"` → kỳ vọng tool call `send_media` với `content_type=video`, `category` rỗng, và trả video `tien_do`
2. `"giới thiệu dự án <X>"` → kỳ vọng `category=tong_quan`, **không** có `content_type`, vẫn ra ảnh phối cảnh (không hồi quy)
3. `"cho xem mặt bằng <X>"` → kỳ vọng `category=mat_bang`, không đổi so với trước

REPL in ra tool call + args nên xem trực tiếp được LLM có tuân prompt không. Nếu bước 2 ra `mat_bang` hoặc bước 1 vẫn ra ảnh → prompt chưa đủ mạnh, phải siết `description` (spec §3 đã ghi lý do đặt hướng dẫn vào param description).

- [ ] **Step 5: Cập nhật CLAUDE.md**

Ở mục **Media search (`send_media`)**, sửa dòng mô tả filter:

```
- ONE Qdrant query: `text` (+ `visual` when on) branches → RRF → `MEDIA_SEARCH_TOP_K`,
  filtered by `project_id` (unioned with `__ALL__`) AND `category` (exact match, optional)
  AND `content_type` (exact match, optional — `image`|`video`).
- `category` và `content_type` đều optional ở schema nhưng **không được rỗng cả hai**
  (`support_ops` trả retry `missing_filter`). `content_type=video` nới cap video từ 1
  lên `MAX_VIDEOS_WHEN_REQUESTED=3`.
```

Sửa dòng cache key cho khớp (thêm `content_type` vào danh sách thành phần key).

Thêm một dòng vào **Change Log** (đầu bảng):

```
| 2026-08-06 | **`send_media` thêm param `content_type` (`image`\|`video`), `category` thành optional.** Khách xin video gần như không bao giờ nhận được video: không có cách diễn đạt "tôi muốn video" (`content_type` chỉ là payload field, chưa bao giờ là filter), và `category` bắt buộc + hard-AND nên LLM điền `tong_quan` theo quán tính → chặn sạch video (đo trên Qdrant thật: MEL *có* video nhưng ở `tien_do`). Fix: `build_scope_filter(..., content_type=)` thêm một `FieldCondition` (không đụng `search_hybrid` → `kb_search` không ảnh hưởng); `search_media` nhận `content_type`, **đưa vào cache key** (thiếu là bug: "xin ảnh" và "xin video" dùng lẫn kết quả trong 300s), và nới cap video 1→`MAX_VIDEOS_WHEN_REQUESTED=3` khi `content_type=video`; `required` của schema còn `["query"]`; `support_ops` đổi retry `missing_category` → `missing_filter` (chặn rỗng CẢ HAI) + thêm `invalid_content_type`; `search_query` fallback ghép từ phần non-rỗng theo `content_type`. Prompt sửa 4 chỗ ở 2 file RULES.md (db-mode + legacy) — thêm nhánh thứ ba "KHÁCH XIN VIDEO → content_type=video, bỏ trống category". Hướng dẫn đặt trong `description` của param, không chỉ RULES.md (bài học 2026-07-11 với gemini-flash). `scripts/test_search_tools.py` thêm `--content-type` + `/ct` để live-verify. **Non-goal:** `.mp4` vẫn drop (client chỉ có iframe YouTube, bản mp4 duy nhất là seed trên host không resolve); 2-branch RRF soft-boost cho `category` (đã verify khả thi, để dành); `thumb_url` trỏ IP private + thiếu rendition `medium`. Spec `docs/superpowers/specs/2026-08-06-send-media-content-type-design.md`, plan `docs/superpowers/plans/2026-08-06-send-media-content-type.md`. | Khách xin video là yêu cầu thật và thường gặp, nhưng tool không có cách nào biểu diễn ý đó; và chính việc `category` bắt buộc là thứ giết recall — cho optional thì LLM không điền bừa nữa, nên hard filter đơn giản là đủ, không cần soft-boost. |
```

- [ ] **Step 6: Commit (đưa lệnh cho user)**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md ghi nhận send_media content_type"
```

- [ ] **Step 7: Đưa lệnh push + MR cho user (user tự chạy)**

```bash
git push -u origin feat/send-media-content-type
```
Rồi tạo MR `feat/send-media-content-type` → `develop` trên GitLab.

---

## Self-Review

**Spec coverage:**

| Spec § | Task |
|---|---|
| §4 hợp đồng tool (`required: ["query"]`, enum, description) | 3 |
| §5 validation 4 nhánh + `search_query` fallback | 4 |
| §6 filter + cache key | 1, 2 |
| §7 cap `max_videos` | 2 |
| §8 non-goals | ghi trong Global Constraints; không có task nào chạm |
| §9 phạm vi file (7 file) | 1-6 (đủ 7/7) |
| §10 test | test steps trong 1-4 |
| §11 verify (4 bước + SMOKE) | 6 Step 7 (test-search), 7 Step 1-4 |

**Placeholder scan:** sạch. Vòng review đầu phát hiện Task 5 Step 6 chỉ mô tả "giống Step 5 nhưng bỏ đuôi" — đã đọc nguyên văn dòng 150 của file legacy (xác nhận không có `(quy tắc 12)`) và thay bằng chuỗi đầy đủ. Không còn "TBD"/"handle edge cases"/"tương tự Task N"/bước nào tả việc mà không đưa code.

**Type consistency:** `content_type: str` (rỗng = không lọc) xuyên suốt Task 1→2→4→6; `build_scope_filter` nhận `str | None` (nới hơn, khớp `category` đang có). `_map_items(hits, *, max_videos)` khai ở Task 2 và chỉ dùng trong `media_data`. `MAX_VIDEOS_WHEN_REQUESTED` đặt tên giống nhau ở Task 2, 7 và spec §7. Mã lỗi `missing_filter` / `invalid_content_type` khớp giữa Task 4 code, Task 4 test và spec §5. `run_media` 3-tuple khai ở Task 6 và mọi call-site đều được sửa (3 chỗ trong `interactive` + 1 trong `main`; `run_isolation` gọi `search_media` trực tiếp với default nên không cần sửa).
