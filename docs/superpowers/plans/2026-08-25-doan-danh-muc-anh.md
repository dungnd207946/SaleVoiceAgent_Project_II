# Đoán danh mục ảnh + agent tìm hai lượt — kế hoạch thi công

> **For agentic workers:** REQUIRED SUB-SKILL: dùng superpowers:subagent-driven-development hoặc superpowers:executing-plans để thi công từng task. Các bước dùng checkbox (`- [ ]`).

**Goal:** Ảnh khách đổ hết vào `tong_quan` vẫn tìm được theo loại — VLM gắn nhãn danh mục vào caption, và agent tìm hai lượt để nhãn sai hay thiếu không làm khách trắng tay.

**Architecture:** VLM trả nhãn ở dòng cuối của chính lời gọi sinh caption; portal ghi cả cụm vào `media.caption_auto` nên `content_hash` đổi và re-index tự chạy. Nhãn chỉ vào text embed, không vào filter — đoán sai chỉ đổi thứ hạng. Hai chỗ người đọc (portal UI, payload agent) strip nhãn đi. Bên agent, `search_media` embed một lần rồi search hai lượt, lượt lọc rỗng thì rơi về lượt không lọc.

**Tech Stack:** Python 3.13 · asyncio · httpx · pytest · DashScope qwen-vl-max · Qdrant

**Spec:** `docs/superpowers/specs/2026-08-25-doan-danh-muc-anh-design.md`
**Nhánh:** `feat/kb-ingest-speedup` (backend) · nhánh cùng tên ở `odyssey-agent` (chưa tạo, Task 5 tạo)

## Global Constraints

- **Định danh tiếng Anh** — hàm, biến, hằng, tham số. Tiếng Việt chỉ ở comment, docstring, tên test.
- **Comment ít**: tối đa 1 dòng `#` cho một quyết định.
- **KHÔNG sửa `CLAUDE.md`** — soạn đoạn Change Log rồi báo người dùng.
- Nhãn **≤ 2**, cho phép **0**. Nhãn lạ ngoài sổ bị loại.
- Nhãn chỉ đoán khi `media.category = 'tong_quan'`.
- Không migration, không cột mới.

---

### Task 1: Sổ nhãn và hàm tách caption

**Files:**
- Modify: `src/portal/modules/kb/contracts.py` (thêm `CATEGORY_TONG_QUAN`, `NHAN_DANH_MUC`, `DONG_DANH_MUC`, `split_caption`, `normalize_caption`)
- Test: `tests/unit/test_caption_nhan_danh_muc.py` (tạo mới)

**Interfaces:**
- Produces: `NHAN_DANH_MUC: dict[str, str]` (mã → nhãn tiếng Việt) · `split_caption(text: str) -> tuple[str, list[str]]` · `normalize_caption(text: str) -> str` · `CATEGORY_TONG_QUAN = "tong_quan"`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_caption_nhan_danh_muc.py`:

```python
"""Nhãn danh mục nằm ở DÒNG CUỐI của caption. Nó vào text embed, không vào filter —
nên đoán sai chỉ đổi thứ hạng, không giấu mất ảnh."""

import pytest

from portal.modules.kb.contracts import NHAN_DANH_MUC, normalize_caption, split_caption


def test_khong_co_dong_nhan_thi_giu_nguyen():
    assert split_caption("Phòng ngủ hiện đại.") == ("Phòng ngủ hiện đại.", [])


def test_mot_nhan():
    mo_ta, nhan = split_caption("Phòng ngủ hiện đại.\nDanh mục: nội thất")
    assert mo_ta == "Phòng ngủ hiện đại."
    assert nhan == ["nội thất"]


def test_hai_nhan():
    _, nhan = split_caption("Bể bơi ngoài trời.\nDanh mục: tiện ích, ngoại thất")
    assert nhan == ["tiện ích", "ngoại thất"]


def test_nhan_la_ngoai_so_bi_loai():
    mo_ta, nhan = split_caption("Ảnh sảnh.\nDanh mục: bể bơi, nội thất")
    assert nhan == ["nội thất"]
    assert mo_ta == "Ảnh sảnh."


def test_nhan_giua_cau_khong_tinh():
    """Chỉ dòng CUỐI mới là nhãn — không thì một câu tả có chữ đó bị cắt mất."""
    goc = "Danh mục: đây là một câu tả bình thường."
    assert split_caption(goc) == (goc, [])


def test_caption_rong():
    assert split_caption("") == ("", [])


def test_normalize_cat_nhan_thu_ba():
    ra = normalize_caption("Ảnh.\nDanh mục: nội thất, tiện ích, ngoại thất")
    assert ra == "Ảnh.\nDanh mục: nội thất, tiện ích"


def test_normalize_bo_dong_khi_khong_nhan_nao_hop_le():
    assert normalize_caption("Ảnh.\nDanh mục: bể bơi") == "Ảnh."


def test_so_nhan_phu_tron_bay_danh_muc():
    from portal.modules.kb.contracts import MEDIA_VISUAL_REAL_ESTATE

    assert set(NHAN_DANH_MUC) == set(MEDIA_VISUAL_REAL_ESTATE)
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/unit/test_caption_nhan_danh_muc.py -q`
Expected: FAIL — `ImportError: cannot import name 'normalize_caption'`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/kb/contracts.py`, thêm dưới `MEDIA_VISUAL_REAL_ESTATE`:

```python
CATEGORY_TONG_QUAN = "tong_quan"

# Nhãn tiếng Việt CÓ DẤU: chuỗi này đi vào text embed, mà model dense là
# multilingual-e5-large còn truy vấn của agent là tiếng Việt — `noi_that` embed kém hẳn.
NHAN_DANH_MUC: dict[str, str] = {
    "tong_quan": "tổng quan",
    "ngoai_that": "ngoại thất",
    "noi_that": "nội thất",
    "tien_ich": "tiện ích",
    "mat_bang": "mặt bằng",
    "vi_tri": "vị trí",
    "tien_do": "tiến độ",
}

DONG_DANH_MUC = "Danh mục:"
MAX_NHAN = 2


def split_caption(text: str) -> tuple[str, list[str]]:
    """Tách mô tả khỏi dòng nhãn ở CUỐI. Nhãn lạ ngoài sổ bị loại."""
    dong = (text or "").rstrip().split("\n")
    if len(dong) < 2 or not dong[-1].lstrip().startswith(DONG_DANH_MUC):
        return text, []
    hop_le = set(NHAN_DANH_MUC.values())
    nhan = [t.strip() for t in dong[-1].split(DONG_DANH_MUC, 1)[1].split(",")]
    return "\n".join(dong[:-1]).rstrip(), [t for t in nhan if t in hop_le]


def normalize_caption(text: str) -> str:
    """Dựng lại caption với tối đa `MAX_NHAN` nhãn hợp lệ; không nhãn nào thì bỏ cả dòng."""
    mo_ta, nhan = split_caption(text)
    if not nhan:
        return mo_ta
    return f"{mo_ta}\n{DONG_DANH_MUC} {', '.join(nhan[:MAX_NHAN])}"
```

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/unit/test_caption_nhan_danh_muc.py -q`
Expected: PASS 9 test

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/contracts.py tests/unit/test_caption_nhan_danh_muc.py
git commit -m "feat(kb): vocabulary and parser for the category hint inside a caption"
```

---

### Task 2: VLM trả nhãn cho ảnh tổng quan

**Files:**
- Modify: `src/portal/modules/kb/prompts.yaml` (thêm profile `caption_danh_muc`), `src/portal/modules/kb/jobs.py` (`handle_caption`)
- Test: `tests/modules/kb/test_caption_danh_muc.py` (tạo mới)

**Interfaces:**
- Consumes: `normalize_caption`, `CATEGORY_TONG_QUAN`, `NHAN_DANH_MUC` (Task 1)
- Produces: profile prompt tên `caption_danh_muc`

⚠️ Profile RIÊNG, không sửa prompt `caption` đang có: `handle_caption_preview` dùng chung nó và trả chữ thẳng vào ô mô tả của form upload — thêm dòng nhãn vào đó là người dùng thấy nhãn trong ô nhập.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_caption_danh_muc.py`:

```python
"""Ảnh khách để `tong_quan` thì VLM đoán thêm danh mục; ảnh khách đã phân loại thì tin họ."""

import pytest

from portal.modules.kb import jobs as kb_jobs


class FakeVlm:
    def __init__(self, tra: str) -> None:
        self.tra = tra
        self.profiles: list[str] = []

    async def caption(self, image_url, *, profile):
        self.profiles.append(profile)
        return self.tra

    async def caption_bytes(self, data, *, mime, profile):
        self.profiles.append(profile)
        return self.tra

    async def aclose(self):
        return None


def test_prompt_danh_muc_ton_tai_va_liet_ke_du_bay_nhan():
    from portal.modules.kb import prompts
    from portal.modules.kb.contracts import NHAN_DANH_MUC

    spec = prompts.get("caption_danh_muc")
    for nhan in NHAN_DANH_MUC.values():
        assert nhan in spec.prompt, f"prompt thiếu nhãn {nhan}"


def test_anh_tong_quan_dung_profile_danh_muc(monkeypatch):
    v = FakeVlm("Phòng ngủ.\nDanh mục: nội thất")
    monkeypatch.setattr(kb_jobs, "_vlm", lambda: v)
    profile = kb_jobs._profile_caption("real_estate", "tong_quan")
    assert profile == "caption_danh_muc"


def test_anh_da_phan_loai_giu_profile_cu():
    assert kb_jobs._profile_caption("real_estate", "mat_bang") == "caption"
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_caption_danh_muc.py -q`
Expected: FAIL — `prompts.get("caption_danh_muc")` ném KeyError và `_profile_caption` chưa có

- [ ] **Step 3: Thêm prompt**

Trong `src/portal/modules/kb/prompts.yaml`, thêm sau khối `caption:`:

```yaml
caption_danh_muc:
  model: qwen-vl-max
  max_tokens: 200
  temperature: 0.2
  prompt: |
    Mô tả ngắn gọn hình này của một dự án bất động sản bằng tiếng Việt, 1-2 câu.
    Ảnh chụp thì tả cảnh; sơ đồ, bản đồ vị trí hay ảnh tiến độ thì nói nó thể hiện cái gì.
    Viết tự nhiên như đang giới thiệu cho khách, vào thẳng nội dung.
    Chỉ tả thứ nhìn thấy. Không suy đoán tên dự án, giá hay vị trí.
    Không đọc hay liệt kê chữ, nhãn, số hiệu trên hình.
    Không nhắc tới bản thân bức ảnh: đừng viết "ảnh này", "hình cho thấy", "chủ thể chính".

    Sau phần mô tả, xuống dòng và ghi đúng một dòng cuối:
    Danh mục: <tối đa hai nhãn, cách nhau bằng dấu phẩy>
    Chọn trong: tổng quan, ngoại thất, nội thất, tiện ích, mặt bằng, vị trí, tiến độ.
    Không chắc thì bỏ hẳn dòng đó, đừng đoán bừa.
```

- [ ] **Step 4: Nối vào handler**

Trong `src/portal/modules/kb/jobs.py`, thêm hàm chọn profile cạnh `_caption_anh`:

```python
def _profile_caption(vertical_key: str, category: str) -> str:
    """Ảnh khách để tổng quan thì hỏi VLM thêm danh mục; ảnh đã phân loại thì tin khách."""
    if category == CATEGORY_TONG_QUAN:
        return PROFILE_CAPTION_CATEGORY
    return profiles.caption_profile(registry.get(vertical_key), category)
```

Thêm hằng cạnh `KIND_DELETE`:

```python
PROFILE_CAPTION_CATEGORY = "caption_danh_muc"
```

Trong `handle_caption`, thay hai dòng chọn profile và bọc kết quả:

```python
                profile = _profile_caption(str(payload.get("vertical", "real_estate")), str(row["category"] or ""))
                caption, _ = await _caption_anh(
                    tenant_id=tenant_id,
                    media_url=str(row["media_url"]),
                    profile=profile,
                    thumb_url=str(row["thumb_url"] or ""),
                )
                caption = normalize_caption(caption)
```

Import thêm `CATEGORY_TONG_QUAN`, `normalize_caption` từ `portal.modules.kb.contracts`.

- [ ] **Step 5: Chạy lại**

Run: `uv run pytest tests/modules/kb/test_caption_danh_muc.py tests/modules/kb/test_caption_nguon_anh.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/prompts.yaml src/portal/modules/kb/jobs.py tests/modules/kb/test_caption_danh_muc.py
git commit -m "feat(kb): ask the VLM for a category hint when the customer left the image in tong_quan"
```

---

### Task 3: Nhãn vào vector, payload giữ sạch

**Files:**
- Modify: `src/portal/modules/kb/clients/media.py:24-27` (`_text_and_hash`) và `index()` payload
- Test: `tests/modules/kb/test_media_nhan_vao_vector.py` (tạo mới)

**Interfaces:**
- Consumes: `split_caption`, `NHAN_DANH_MUC` (Task 1)

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_media_nhan_vao_vector.py`:

```python
"""Nhãn đi vào TEXT được embed, không đi vào caption khách nhìn thấy."""

from portal.modules.kb.clients.media import MediaClient, _text_and_hash
from portal.modules.kb.contracts import MediaDirective


class FakeEmbed:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def dense(self, texts):
        self.texts.extend(texts)
        return [[0.1] * 1024]

    async def visual_image(self, urls):
        return [[0.2] * 768]


class FakeVectorStore:
    def __init__(self) -> None:
        self.points: list = []

    async def delete_by_record(self, *a, **kw):
        return 0

    async def upsert(self, name, points):
        self.points.extend(points)
        return len(points)


def _directive(caption: str) -> MediaDirective:
    return MediaDirective(
        workspace_slug="ws",
        record_id=1,
        anchor_code="P1",
        content_type="image",
        category="tong_quan",
        media_url="https://cdn.example.com/a.jpg",
        file_url=None,
        caption=caption,
        thumb_url="tenants/t1/kb-bds/thumb/a.webp",
        anchor_name="Dự án 1",
        status="published",
        anchor_status="published",
    )


def test_text_embed_mang_nhan_tieng_viet_cua_danh_muc():
    text, _ = _text_and_hash(_directive("Phòng ngủ.\nDanh mục: nội thất"))
    assert "tổng quan" in text
    assert "tong_quan" not in text, "mã thô embed kém hơn từ tiếng Việt"
    assert "nội thất" in text


async def test_payload_caption_khong_mang_nhan():
    store = FakeVectorStore()
    await MediaClient(embed=FakeEmbed(), store=store).index(_directive("Phòng ngủ.\nDanh mục: nội thất"))
    assert store.points[0].payload["caption"] == "Phòng ngủ."


def test_hash_doi_khi_nhan_doi():
    """Nhãn nằm trong caption nên hash đổi ⇒ delta tự nạp lại. Đây là cơ chế, không phải
    tình cờ: nhãn để ngoài caption thì hash không đổi và nó không bao giờ lên Qdrant."""
    _, h1 = _text_and_hash(_directive("Phòng ngủ."))
    _, h2 = _text_and_hash(_directive("Phòng ngủ.\nDanh mục: nội thất"))
    assert h1 != h2
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_media_nhan_vao_vector.py -q`
Expected: FAIL — `assert 'tổng quan' in text` (text đang là `"tong_quan Phòng ngủ…"`)

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/kb/clients/media.py`:

```python
def _text_and_hash(directive: MediaDirective) -> tuple[str, str]:
    caption = directive.caption or ""
    nhan_danh_muc = NHAN_DANH_MUC.get(directive.category, directive.category)
    text = f"{nhan_danh_muc} {caption}".strip()
    return text, hashlib.sha256(f"{directive.media_url}␟{caption}".encode()).hexdigest()
```

Trong `index()`, đổi đúng hai dòng — `caption` cho payload phải sạch, `text` giữ nguyên cả cụm:

```python
        text, content_hash = _text_and_hash(directive)
        caption_sach, _ = split_caption(directive.caption or "")
```

và trong `payload=`: `"caption": caption_sach,`

Import `NHAN_DANH_MUC`, `split_caption` từ `portal.modules.kb.contracts`.

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/kb/test_media_nhan_vao_vector.py tests/modules/kb -q`
Expected: PASS (trừ `test_index_client_that.py::test_payload_mang_URL_CONG_KHAI_cua_tep_va_thumb` — đỏ sẵn từ baseline)

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/media.py tests/modules/kb/test_media_nhan_vao_vector.py
git commit -m "feat(kb): embed the category hint, keep the customer-facing caption clean"
```

---

### Task 4: Portal UI không thấy nhãn

**Files:**
- Modify: `src/portal/modules/realestate/router.py:583`
- Test: `tests/modules/realestate/test_media_caption_sach.py` (tạo mới)

**Interfaces:**
- Consumes: `split_caption` (Task 1)

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/realestate/test_media_caption_sach.py`:

```python
"""Nhãn danh mục là chuyện của vector, không phải chuyện của người dùng portal."""

import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


async def test_caption_auto_co_nhan_thi_api_tra_ban_sach(client_re, workspace_re, pool):
    r = await client_re.post("/api/v1/projects", json={"projectCode": "capt1", "name": "Dự án capt1"})
    assert r.status_code == 201, r.text
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.media (tenant_id, project_code, content_type, category, media_url, caption_auto) "
            "VALUES (portal.current_tenant(), 'capt1', 'image', 'tong_quan', 'https://x/a.jpg', $1)",
            "Phòng ngủ hiện đại.\nDanh mục: nội thất",
        )

    ds = (await client_re.get("/api/v1/projects/capt1/media")).json()["items"]
    assert ds[0]["caption"] == "Phòng ngủ hiện đại."


async def test_khong_cat_mo_ta_nguoi_go_tay(client_re, workspace_re, pool):
    """Khách gõ đúng chữ đó trong mô tả tay thì KHÔNG được cắt — strip chỉ áp cho caption_auto."""
    await client_re.post("/api/v1/projects", json={"projectCode": "capt2", "name": "Dự án capt2"})
    goc = "Ảnh.\nDanh mục: nội thất"
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.media (tenant_id, project_code, content_type, category, media_url, caption) "
            "VALUES (portal.current_tenant(), 'capt2', 'image', 'tong_quan', 'https://x/b.jpg', $1)",
            goc,
        )

    ds = (await client_re.get("/api/v1/projects/capt2/media")).json()["items"]
    assert ds[0]["caption"] == goc
```

Đã đối chiếu: fixture `client_re`/`workspace_re`/`pool` có trong `tests/modules/realestate/conftest.py`, và `GET /projects/{project_code}/media` là `router.py:1624`.

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/realestate/test_media_caption_sach.py -q`
Expected: FAIL — caption trả về còn dòng `Danh mục: nội thất`

- [ ] **Step 3: Cài đặt**

Trong `src/portal/modules/realestate/router.py:583`:

```python
        caption=r["caption"] or split_caption(r["caption_auto"] or "")[0],
```

Import: `from portal.modules.kb.contracts import split_caption` (mặt tiền module khác — hợp Luật 3).

- [ ] **Step 4: Chạy lại**

Run: `uv run pytest tests/modules/realestate/test_media_caption_sach.py -q`
Expected: PASS 2 test

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/realestate/router.py tests/modules/realestate/test_media_caption_sach.py
git commit -m "feat(realestate): strip the category hint before the media list reaches the UI"
```

---

### Task 5: Agent tìm hai lượt (repo `odyssey-agent`)

**Files:**
- Modify: `src/noble_agent/data/media_data.py` (`search_media`)
- Test: `tests/unit/unified/test_media_hai_luot.py` (tạo mới)

**Interfaces:**
- Consumes: không phụ thuộc Task 1–4 — chạy độc lập, và tự nó cứu được dữ liệu cũ

- [ ] **Step 1: Tạo nhánh**

```bash
cd ~/Desktop/odyssey-agent
git fetch --all --prune
git checkout -b feat/kb-ingest-speedup origin/develop
```

- [ ] **Step 2: Viết test đỏ**

Tạo `tests/unit/unified/test_media_hai_luot.py`:

```python
"""Khách đổ mọi ảnh vào `tong_quan` (đo trên prod: 96%), nên lọc theo category hay trả
rỗng. Lượt hai không lọc là thứ giữ cho khách không trắng tay."""

import pytest

from noble_agent.data import media_data


class Ghi:
    def __init__(self, ket_qua: list[list[dict]]) -> None:
        self.ket_qua = list(ket_qua)
        self.categories: list[str] = []
        self.so_lan_embed = 0

    async def search_hybrid(self, **kw):
        loc = kw.get("filter_")
        self.categories.append(getattr(loc, "_category_test", ""))
        return self.ket_qua.pop(0) if self.ket_qua else []


HIT = {"media_url": "https://cdn/a.jpg", "content_type": "image", "caption": "Phòng ngủ", "project_id": "P1"}


@pytest.fixture
def gia(monkeypatch):
    g = Ghi([[HIT], [HIT]])

    async def _embed_dense(texts, side="query"):
        g.so_lan_embed += 1
        return [[0.1] * 1024]

    def _scope_filter(codes, *, category=None, content_type=None, sentinel=""):
        class F:
            pass

        f = F()
        f._category_test = category or ""
        return f

    monkeypatch.setattr(media_data.embed_client, "embed_dense", _embed_dense)
    monkeypatch.setattr(media_data.qdrant_client, "build_scope_filter", _scope_filter)
    monkeypatch.setattr(media_data.qdrant_client, "search_hybrid", g.search_hybrid)
    monkeypatch.setattr(media_data.qdrant_client, "collection_exists", lambda *a, **kw: _true())
    return g


async def _true():
    return True


async def test_loc_co_ket_qua_thi_khong_roi_ve(gia):
    items = await media_data.search_media(
        "ảnh nội thất", "P1", "noi_that", tenant_id="t1", qdrant_url="http://q", cache_ttl=0
    )
    assert len(items) == 1
    assert gia.categories[0] == "noi_that"


async def test_loc_rong_thi_lay_ket_qua_khong_loc(gia):
    gia.ket_qua = [[], [HIT]]
    items = await media_data.search_media(
        "ảnh nội thất", "P1", "noi_that", tenant_id="t1", qdrant_url="http://q", cache_ttl=0
    )
    assert len(items) == 1
    assert gia.categories == ["noi_that", ""]


async def test_khong_truyen_category_thi_chi_mot_luot(gia):
    await media_data.search_media("ảnh", "P1", "", tenant_id="t1", qdrant_url="http://q", cache_ttl=0)
    assert gia.categories == [""]


async def test_embed_chi_goi_mot_lan(gia):
    gia.ket_qua = [[], [HIT]]
    await media_data.search_media(
        "ảnh nội thất", "P1", "noi_that", tenant_id="t1", qdrant_url="http://q", cache_ttl=0
    )
    assert gia.so_lan_embed == 1, "phần đắt là embed, không phải Qdrant"
```

Đã đối chiếu: `embed_client.embed_dense(texts, *, side="query")` (`embed_client.py:83`), `embed_client.embed_visual_text` (`:215`), `qdrant_search.collection_exists(base_url, api_key, collection)` (`:172`).

- [ ] **Step 3: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/unit/unified/test_media_hai_luot.py -q`
Expected: FAIL — hiện chỉ có một lượt search, `gia.categories == ["noi_that"]` ở ca thứ hai

- [ ] **Step 4: Cài đặt**

Trong `src/noble_agent/data/media_data.py`, thay khối gọi `search_hybrid` bằng:

```python
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

    def _items(points: list[dict]) -> list[dict]:
        hits = [{**p, "project_code": p.get("project_id", "")} for p in points]
        return _map_items(hits, max_videos=max_videos, include_thumb=include_thumb)

    max_videos = MAX_VIDEOS_WHEN_REQUESTED if content_type == "video" else 1
    if category:
        loc, khong_loc = await asyncio.gather(_tim(category), _tim(""))
        items = _items(loc)
        if not items:
            items = _items(khong_loc)
            logger.info(
                "media_data: category=%s không có ảnh nào → rơi về tìm không lọc (%d item)",
                category,
                len(items),
            )
    else:
        items = _items(await _tim(""))

    _cache.set(key, items, cache_ttl)
    return items
```

Bỏ khối `points = await qdrant_client.search_hybrid(...)`, dòng `hits = [...]`, dòng `max_videos = ...` và `items = _map_items(...)` cũ — chúng đã nằm trong hai hàm trên.

- [ ] **Step 5: Chạy lại**

Run: `uv run pytest tests/unit/unified/test_media_hai_luot.py tests/unit/unified/test_send_media.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/data/media_data.py tests/unit/unified/test_media_hai_luot.py
git commit -m "feat(media): fall back to an unfiltered search when the category filter finds nothing"
```

---

### Task 6: Kiểm chứng và bàn giao

- [ ] **Step 1: Toàn bộ cổng backend**

Run: `cd ~/Desktop/odyssey-portal-backend && make check`
Expected: danh sách đỏ TRÙNG KHÍT baseline `origin/develop` (28 dòng: `test_worker_retry.py` · `test_dang_ky.py` · `test_migration_invites_tenant.py` · `test_heartbeat.py` · `test_index_client_that.py`). Lệch một dòng nào là hồi quy — dừng lại truy, đừng ghi vào phần nợ.

- [ ] **Step 2: Toàn bộ test agent**

Run: `cd ~/Desktop/odyssey-agent && uv run pytest tests/unit -q`
Expected: khớp baseline của repo đó (`test_tool_ack.py` flaky theo thời gian, xem Change Log 2026-08-19).

- [ ] **Step 3: Thử một lượt caption thật trên prod (không ghi)**

Chạy một ảnh `tong_quan` của `aina_prod` qua prompt `caption_danh_muc` bằng khoá thật, in ra caption + nhãn parse được. Không UPDATE gì. Mục đích: xem model có tuân đúng format dòng cuối không — nếu nó trả nhãn giữa câu thì `split_caption` trả 0 nhãn và cả tính năng thành vô hiệu trong im lặng.

- [ ] **Step 4: Soạn Change Log cho `CLAUDE.md`**

Ghi ra đoạn để người dùng tự dán (KHÔNG sửa file): profile `caption_danh_muc` · nhãn nằm ở dòng cuối `caption_auto` và là cơ chế làm `content_hash` đổi · `split_caption` phải gọi ở hai chỗ người đọc · text embed đổi từ mã thô sang nhãn tiếng Việt · agent tìm hai lượt.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-25-doan-danh-muc-anh-design.md
git commit -m "docs(kb): record verification for the category-hint work"
```

## Thứ tự

Task 1 → 2 → 3 → 4 (portal, nối tiếp) · Task 5 độc lập hoàn toàn, chạy lúc nào cũng được · Task 6 cuối.

Không có thứ tự deploy bắt buộc giữa hai repo: portal chỉ thêm chữ vào một cột và vào text embed; agent bản cũ đọc `payload.caption` vẫn sạch như trước.
