# Nạp Markdown có ảnh ngoài — kế hoạch thi công

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tải một tệp `.md` có ảnh trỏ S3 ngoài lên KB, hỏi agent, và thấy ảnh đúng chỗ đúng thứ tự trong câu trả lời.

**Architecture:** Portal kéo ảnh ngoài về kho mình rồi viết lại link ngay trong `directive.text`, trước khi băm nội dung và trước khi nhúng. Agent thay URL trong ngữ cảnh bằng mốc `[ảnh N — mô tả]` và gửi ảnh qua `items`, nên mô hình không bao giờ chạm chuỗi link. Số ảnh cấp theo cả cuộc hội thoại, giữ trong `state.scratchpad`.

**Tech Stack:** Python 3.12 · FastAPI · asyncpg · httpx · Pillow · Qdrant · TypeScript/React

Spec: [`docs/superpowers/specs/2026-08-28-nap-md-anh-ngoai-design.md`](../specs/2026-08-28-nap-md-anh-ngoai-design.md)

## Global Constraints

- Ba repo, cùng tên nhánh `feat/kb-md-anh-ngoai`, đều đã cắt từ `origin/develop`.
- **Không migration.** Không đụng Postgres schema.
- **Định danh TIẾNG ANH** ở cả ba repo (chủ dự án chốt 2026-08-28). Đây là quy tắc hiện hành
  của repo — một vòng review ở plan trước đã bắt đổi `split_title`/`join_title`/`doc_type_of`
  sang tiếng Anh trong chính module `kb` này. Hàng xóm còn tiếng Việt (`sinh_va_luu`,
  `thumb_key_cho_media`, `_tach_khoi`) là di sản — **không đổi tên chúng trong đợt này**.
  Comment và tên test vẫn tiếng Việt.
- Trường trên dây tên **`index`** (1-based, duy nhất trong cả cuộc trò chuyện). Nó là hợp đồng
  ba bên: `gateway-protocol.json` · agent `items[]` · FE `MedItemAnh`. Lệch một chỗ là số biến
  mất im lặng vì `chuanHoaMedia` bỏ mọi trường lạ.
- **Comment và docstring THƯA.** Chỉ viết khi nó nói một điều mã không tự nói: một quyết định,
  một cái bẫy đã đo được, một lý do trái trực giác. Không mô tả lại thứ dòng bên dưới đã rõ.
  Docstring dài hơn thân hàm là dấu hiệu viết thừa. (Yêu cầu thường trực của chủ dự án — repo
  hiện có comment rất dày, đó là di sản, đừng lấy làm chuẩn.)
- Trần: **100 ảnh mỗi tệp · 10 MB mỗi ảnh · timeout 15 giây · chỉ `Content-Type: image/*`**.
- Ảnh hỏng **không được** làm hỏng cả tệp — giữ URL gốc, ghi cảnh báo.
- Mọi truy vấn `tenant_data` đi qua `tenant_conn()` trong một giao dịch (luật 1 của repo).
- Chạy test backend: `uv run pytest <path> -v`. Lint: `make lint` (**hai lệnh**: `ruff check` và `ruff format --check`).

---

## Task 1: Portal nhận tệp `.md`

**Files:**
- Modify: `src/portal/modules/kb/contracts.py:222`
- Modify: `src/portal/modules/kb/clients/extract.py:25,129-156`
- Test: `tests/modules/kb/test_extract.py`

**Interfaces:**
- Produces: `LOAI_HO_TRO` gồm `"md"`; `TextExtractor.extract(data, filename="x.md")` trả `ExtractResult(text=<nguyên văn utf-8>)`.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/modules/kb/test_extract.py`:

```python
import pytest

from portal.modules.kb.clients.extract import TextExtractor
from portal.modules.kb.contracts import LOAI_HO_TRO


def test_md_nam_trong_loai_ho_tro():
    assert "md" in LOAI_HO_TRO


@pytest.mark.asyncio
async def test_boc_md_tra_nguyen_van():
    raw = "# Tiêu đề\n\nMột dòng có dấu tiếng Việt.\n\n![alt](https://s3.khach.vn/a.png)\n"
    out = await TextExtractor(vlm=None).extract(raw.encode("utf-8"), filename="sotay.md")
    assert out.text == raw
    assert out.da_ocr is False


@pytest.mark.asyncio
async def test_md_rong_khong_muon_thong_diep_lop_chu():
    """`.md` rỗng KHÔNG được rơi vào câu «không có lớp chữ» — câu đó nói về PDF scan."""
    from portal.modules.kb.contracts import MD_EMPTY_MESSAGE

    out = await TextExtractor(vlm=None).extract(b"   \n\n  ", filename="rong.md")
    assert out.text == ""
    assert "lớp chữ" not in MD_EMPTY_MESSAGE
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_extract.py -k "md" -v`
Expected: FAIL — `assert "md" in LOAI_HO_TRO` và `ImportError: cannot import name 'MD_EMPTY_MESSAGE'`

- [ ] **Step 3: Sửa `contracts.py`**

Thay dòng 222:

```python
LOAI_HO_TRO = ("pdf", "docx", "xlsx", "md")
"""KB_01 §I.2 — khớp CHECK `kb_files_loai_check` của migration 0300.
Không hỗ trợ: ảnh scan không lớp chữ · file đặt mật khẩu.

`md` thêm 2026-08-28: sổ tay khách soạn sẵn dạng Markdown, ảnh là URL tuyệt đối.
⚠️ CHECK `kb_files_loai_check` của `0300` phải đã nhận `md` — kiểm trước khi ship,
nếu không upload trả 500 ở câu INSERT chứ không phải 400 ở route."""
```

Thêm cạnh `THONG_DIEP_KHONG_CO_CHU`:

```python
MD_EMPTY_MESSAGE = "Tệp Markdown không có nội dung nào — kiểm lại tệp rồi tải lên lại."
"""Markdown rỗng KHÔNG dùng chung câu với PDF scan: câu kia nói về «lớp chữ», một khái
niệm của tệp quét, và người tải lên một tệp .md sẽ không hiểu mình phải sửa gì."""
```

- [ ] **Step 4: Sửa `extract.py`**

Dòng 25:

```python
DUOI_HO_TRO = frozenset({"pdf", "docx", "xlsx", "md"}) | DUOI_ANH
```

Thêm nhánh trong `extract()`, ngay trước nhánh `docx` (sau khối `DUOI_ANH`):

```python
        if ext == "md":
            # Markdown KHÔNG bóc gì — nó đã là định dạng `chunker.structured_md` chờ đợi.
            # `errors="replace"` chứ không ném: một byte hỏng giữa tệp không đáng đánh đổi
            # bằng việc mất cả tài liệu, và chỗ hỏng sẽ hiện ra dưới dạng ký tự thay thế.
            return ExtractResult(text=data.decode("utf-8", errors="replace").strip())
```

- [ ] **Step 5: Chạy test**

Run: `uv run pytest tests/modules/kb/test_extract.py -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Kiểm CHECK của DB nhận `md`**

Run:
```bash
docker compose -f docker-compose.local.yml exec -T postgres \
  psql -U portal_migrator -d portal -c \
  "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'kb_files_loai_check';"
```
Expected: định nghĩa CHECK **có chứa** `'md'`.
Nếu KHÔNG có: dừng lại và báo — cần một migration nới CHECK, và đó là việc ngoài kế hoạch này.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/kb/contracts.py src/portal/modules/kb/clients/extract.py tests/modules/kb/test_extract.py
git commit -m "feat(kb): accept .md uploads and pass them through untouched

Markdown is already the shape the structured_md chunker expects, so the
extractor has nothing to do but decode. An empty .md gets its own message
instead of borrowing the PDF-scan one, which talks about a text layer -- a
notion that means nothing to someone who uploaded a Markdown file."
```

---

## Task 2: Phân tích ảnh ngoài trong Markdown (hàm thuần)

**Files:**
- Create: `src/portal/modules/kb/clients/external_images.py`
- Test: `tests/modules/kb/test_external_images.py`

**Interfaces:**
- Produces:
  - `find_external_images(text: str, *, own_prefix: str) -> list[str]` — URL ảnh không thuộc kho mình, theo thứ tự xuất hiện, đã bỏ trùng.
  - `rewrite_urls(text: str, bang: dict[str, str]) -> str` — thay URL theo bảng; URL vắng trong bảng giữ nguyên.
  - Hằng `MAX_IMAGES = 100`, `MAX_BYTES = 10 * 1024 * 1024`, `TIMEOUT_SEC = 15.0`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_external_images.py`:

```python
from portal.modules.kb.clients import external_images

MINH = "https://portal.noble.vn/api/v1/public/files/"


def test_tim_dung_thu_tu_va_bo_trung():
    text = (
        "Câu dẫn A.\n\n![a](https://s3.khach.vn/1.png)\n\n"
        "Câu dẫn B.\n\n![b](https://s3.khach.vn/2.png)\n\n"
        "Nhắc lại.\n\n![a lần hai](https://s3.khach.vn/1.png)\n"
    )
    assert external_images.find_external_images(text, own_prefix=MINH) == [
        "https://s3.khach.vn/1.png",
        "https://s3.khach.vn/2.png",
    ]


def test_bo_qua_anh_da_thuoc_kho_minh():
    text = f"![x]({MINH}tenants/t1/kb/anh/abc.png)"
    assert external_images.find_external_images(text, own_prefix=MINH) == []


def test_tien_to_rong_thi_KHONG_coi_moi_url_la_cua_minh():
    """`url.startswith("")` luôn True — không chặn thì chưa cấu hình base là không
    ảnh nào được kéo về, và không dấu hiệu nào."""
    text = "![x](https://s3.khach.vn/1.png)"
    assert external_images.find_external_images(text, own_prefix="") == ["https://s3.khach.vn/1.png"]


def test_bo_qua_link_khong_phai_anh():
    text = "[tài liệu](https://s3.khach.vn/a.pdf) và ![ảnh](https://s3.khach.vn/b.png)"
    assert external_images.find_external_images(text, own_prefix=MINH) == ["https://s3.khach.vn/b.png"]


def test_thay_dung_cho_giu_nguyen_alt():
    text = "Trước.\n\n![Màn đăng nhập](https://s3.khach.vn/1.png)\n\nSau."
    out = external_images.rewrite_urls(text, {"https://s3.khach.vn/1.png": f"{MINH}k/abc.png"})
    assert out == f"Trước.\n\n![Màn đăng nhập]({MINH}k/abc.png)\n\nSau."


def test_url_vang_trong_bang_giu_nguyen():
    text = "![a](https://s3.khach.vn/1.png)![b](https://s3.khach.vn/2.png)"
    out = external_images.rewrite_urls(text, {"https://s3.khach.vn/1.png": "X"})
    assert out == "![a](X)![b](https://s3.khach.vn/2.png)"


def test_text_khong_anh_tra_nguyen_van():
    text = "Chỉ có chữ, không ảnh nào."
    assert external_images.find_external_images(text, own_prefix=MINH) == []
    assert external_images.rewrite_urls(text, {}) == text
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_external_images.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.kb.clients.anh_ngoai`

- [ ] **Step 3: Viết phần thuần của module**

Tạo `src/portal/modules/kb/clients/external_images.py`:

```python
"""Ảnh ngoài trong Markdown → kho của mình.

Khách gửi sổ tay Markdown mà ảnh nằm trên S3 của họ. Ba lý do phải kéo về:
· kho khách đổi quyền hoặc xoá tệp là ảnh vỡ phía người dùng cuối, không lỗi nào phía ta;
· URL của họ đi thẳng vào vector làm nhiễu phép tìm (đo được: hạng 1 từ 7/10 lên 8/10 khi
  bỏ URL khỏi chuỗi nhúng, và URL S3 thật dài gấp đôi URL trong bài đo);
· không cầm byte trong tay thì không sinh được thumbnail.

Phần PHÂN TÍCH là hàm thuần — không mạng, không kho, test được không cần Docker. Phần
KÉO VỀ (`mirror_images`) mới chạm mạng và kho.
"""

import hashlib
import re

_ANH = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")

_EXT_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

MAX_IMAGES = 100
MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_SEC = 15.0


def find_external_images(text: str, *, own_prefix: str) -> list[str]:
    """URL ảnh KHÔNG thuộc kho mình, theo thứ tự xuất hiện, đã bỏ trùng.

    ⚠️ `own_prefix` rỗng phải nghĩa là «chưa biết kho mình ở đâu», KHÔNG phải «mọi thứ
    là của mình»: `url.startswith("")` luôn True, nên thiếu vế `bool(own_prefix)` thì
    một môi trường chưa cấu hình `PUBLIC_BASE_URL` sẽ lặng lẽ không kéo ảnh nào về.
    """
    out: list[str] = []
    for _, url in _ANH.findall(text):
        la_cua_minh = bool(own_prefix) and url.startswith(own_prefix)
        if not la_cua_minh and url not in out:
            out.append(url)
    return out


def rewrite_urls(text: str, table: dict[str, str]) -> str:
    """Thay URL theo `table`, GIỮ NGUYÊN alt và vị trí. URL vắng trong bảng giữ nguyên.

    Giữ nguyên vị trí là cả mục đích: thứ tự ảnh trong văn bản chính là thứ tự người đọc
    cần, và nó là thứ `chunker` rồi agent dựa vào.
    """
    return _ANH.sub(lambda m: f"![{m.group(1)}]({table.get(m.group(2), m.group(2))})", text)
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_external_images.py -v`
Expected: PASS 7/7

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/external_images.py tests/modules/kb/test_external_images.py
git commit -m "feat(kb): find and rewrite external image links in Markdown

Pure functions, no network and no store, so they are testable without Docker.
The empty-prefix case gets its own test: url.startswith('') is always true, so
without the guard an environment with no PUBLIC_BASE_URL would quietly mirror
nothing at all."
```

---

## Task 3: Kéo ảnh về kho mình + sinh thumb

**Files:**
- Modify: `src/portal/modules/kb/clients/external_images.py`
- Test: `tests/modules/kb/test_external_images_fetch.py`

**Interfaces:**
- Consumes: `find_external_images`, `rewrite_urls`, `MAX_IMAGES`, `MAX_BYTES`, `TIMEOUT_SEC` (Task 2); `ObjectStore.key/put` (`kb/contracts.py:120`); `thumbnail.sinh_va_luu` (`kb/storage/thumbnail.py:54`).
- Produces: `async mirror_images(text: str, *, tenant_id: str, store: ObjectStore) -> tuple[str, list[str]]` — trả `(text đã viết lại, danh sách cảnh báo)`. **Không bao giờ ném** vì một ảnh hỏng.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_external_images_fetch.py`:

```python
import pytest

from portal.modules.kb.clients import external_images

MINH = "https://portal.noble.vn/api/v1/public/files/"
# PNG 1×1 hợp lệ — Pillow đọc được, nên nhánh thumb chạy thật chứ không giả.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


class KhoGia:
    """Kho trong bộ nhớ. `key` idempotent đúng như `object_store.build_key`."""

    def __init__(self):
        self.doi_tuong: dict[str, bytes] = {}

    def key(self, *, tenant_id: str, path: str) -> str:
        tien_to = f"tenants/{tenant_id}/"
        return path if path.startswith(tien_to) else f"{tien_to}{path}"

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.doi_tuong[key] = data
        return f"presigned://{key}"


@pytest.fixture
def base_cong_khai(monkeypatch):
    """`get_settings()` KHÔNG cache (xem CLAUDE.md), nên đặt env là đủ."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.noble.vn")


def _http_gia(monkeypatch, tra_loi):
    """`tra_loi(url)` → (status, content_type, body) hoặc ném."""

    class R:
        def __init__(self, url):
            self.status, self.headers_ct, self._body = tra_loi(url)
            self.headers = {"content-type": self.headers_ct}

        def raise_for_status(self):
            if self.status >= 400:
                # Không dựng httpx.HTTPStatusError: nó đòi request/response thật.
                # `mirror_images` bắt rộng nên kiểu ngoại lệ không quan trọng.
                raise RuntimeError(f"HTTP {self.status}")

        async def aiter_bytes(self):
            yield self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, _method, url):
            return R(url)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)


@pytest.mark.asyncio
async def test_keo_ve_va_viet_lai_link(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    text = "Câu dẫn.\n\n![Màn đăng nhập](https://s3.khach.vn/1.png)\n"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert warnings == []
    assert "s3.khach.vn" not in new_url
    assert MINH in new_url
    assert "![Màn đăng nhập](" in new_url  # alt giữ nguyên
    raw = [k for k in kho.doi_tuong if "/kb/anh/" in k and not k.endswith(".thumb.webp")]
    thumb = [k for k in kho.doi_tuong if k.endswith(".thumb.webp")]
    assert len(raw) == 1 and len(thumb) == 1


@pytest.mark.asyncio
async def test_hai_tai_lieu_dung_chung_anh_chi_ton_mot_ban(monkeypatch, base_cong_khai):
    """Khoá băm theo NỘI DUNG ảnh, không theo URL — nên cùng byte ra cùng khoá."""
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    a, _ = await external_images.mirror_images("![x](https://s3.khach.vn/1.png)", tenant_id="t1", store=kho)
    b, _ = await external_images.mirror_images("![y](https://cdn.khac.vn/2.png)", tenant_id="t1", store=kho)
    assert a.split("(")[1] == b.split("(")[1]


@pytest.mark.asyncio
async def test_anh_404_giu_url_goc_va_ghi_canh_bao(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (404, "text/html", b"no"))
    kho = KhoGia()
    text = "![x](https://s3.khach.vn/1.png)"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert new_url == text          # giữ nguyên, KHÔNG ra `![x]()`
    assert len(warnings) == 1
    assert "s3.khach.vn/1.png" in warnings[0]


@pytest.mark.asyncio
async def test_khong_phai_anh_thi_tu_choi(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (200, "text/html", b"<html>"))
    kho = KhoGia()
    new_url, warnings = await external_images.mirror_images("![x](https://s3.khach.vn/a)", tenant_id="t1", store=kho)
    assert kho.doi_tuong == {}
    assert "content-type" in warnings[0]
    assert new_url == "![x](https://s3.khach.vn/a)"


@pytest.mark.asyncio
async def test_vuot_tran_byte_thi_bo_qua(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (200, "image/png", b"x" * (external_images.MAX_BYTES + 1)))
    kho = KhoGia()
    _, warnings = await external_images.mirror_images("![x](https://s3.khach.vn/1.png)", tenant_id="t1", store=kho)
    assert kho.doi_tuong == {}
    assert "vượt trần" in warnings[0]


@pytest.mark.asyncio
async def test_vuot_tran_image_numbers_thi_keo_100_dau(monkeypatch, base_cong_khai):
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    text = "\n\n".join(f"![a{i}](https://s3.khach.vn/{i}.png)" for i in range(external_images.MAX_IMAGES + 5))

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert any("vượt trần" in c for c in warnings)
    # 5 ảnh cuối GIỮ URL gốc, không mất
    assert f"https://s3.khach.vn/{external_images.MAX_IMAGES + 4}.png" in new_url


@pytest.mark.asyncio
async def test_base_chua_cau_hinh_thi_giu_url_goc(monkeypatch):
    """`public_url_of` trả rỗng khi PUBLIC_BASE_URL trống — viết rỗng vào link là
    `![x]()`, một ảnh mất mà không lỗi nào. Phải giữ URL gốc."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    _http_gia(monkeypatch, lambda u: (200, "image/png", PNG))
    kho = KhoGia()
    text = "![x](https://s3.khach.vn/1.png)"

    new_url, warnings = await external_images.mirror_images(text, tenant_id="t1", store=kho)

    assert new_url == text
    assert any("PUBLIC_BASE_URL" in c for c in warnings)


@pytest.mark.asyncio
async def test_text_khong_anh_khong_cham_mang(monkeypatch, base_cong_khai):
    def no(_u):
        raise AssertionError("không được gọi mạng khi text không có ảnh")

    _http_gia(monkeypatch, no)
    new_url, warnings = await external_images.mirror_images("Chỉ có chữ.", tenant_id="t1", store=KhoGia())
    assert new_url == "Chỉ có chữ." and warnings == []
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_external_images_fetch.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'mirror_images'`

- [ ] **Step 3: Viết `mirror_images` + `_fetch_one`**

Thêm vào cuối `src/portal/modules/kb/clients/external_images.py`:

```python
async def mirror_images(text: str, *, tenant_id: str, store) -> tuple[str, list[str]]:
    """Kéo mọi ảnh ngoài về kho mình, sinh thumb, viết lại link. Trả (text mới, cảnh báo).

    KHÔNG NÉM vì một ảnh hỏng — cùng lý lẽ `jobs._thumb_neu_thieu` đã ghi: tài liệu là
    sản phẩm chính, ảnh là minh hoạ. Một tài liệu 27 ảnh mà 1 ảnh 404 vẫn phải nạp được;
    đánh dấu cả tệp `message` là bắt người dùng sửa thứ họ không gây out.

    IDEMPOTENT: sau lượt đầu, link trong `text` đã trỏ kho mình nên lượt sau không tìm
    thấy ảnh ngoài và không tải lại gì. `documents.body` được nhúng lại MỖI LẦN SỬA, nên
    tính chất này là bắt buộc chứ không phải tiện tay.
    """
    import httpx

    from portal.core.config import get_settings
    from portal.core.public_url import PUBLIC_PATH, public_url_of

    base = get_settings().public_base_url.rstrip("/")
    own_prefix = f"{base}{PUBLIC_PATH}" if base else ""
    to_fetch = find_external_images(text, own_prefix=own_prefix)
    if not to_fetch:
        return text, []

    warnings: list[str] = []
    if len(to_fetch) > MAX_IMAGES:
        extra = len(to_fetch) - MAX_IMAGES
        warnings.append(f"{len(to_fetch)} ảnh vượt trần {MAX_IMAGES} — {extra} ảnh cuối giữ URL gốc")
        to_fetch = to_fetch[:MAX_IMAGES]

    table: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC, follow_redirects=True) as http:
        for url in to_fetch:
            try:
                key = await _fetch_one(http, url, tenant_id=tenant_id, store=store)
            except Exception as e:  # noqa: BLE001 — xem docstring
                warnings.append(f"{url}: {type(e).__name__}: {e}")
                continue
            new_url = public_url_of(key)
            if not new_url:
                # `public_url_of` trả rỗng khi PUBLIC_BASE_URL trống hoặc nội bộ — mặc
                # định ở dev. Viết rỗng vào link cho ra `![alt]()`: ảnh mất, không lỗi nào.
                warnings.append(f"{url}: PUBLIC_BASE_URL chưa cấu hình — giữ URL gốc")
                continue
            table[url] = new_url
    return rewrite_urls(text, table), warnings


async def _fetch_one(http, url: str, *, tenant_id: str, store) -> str:
    """Tải một ảnh → kho mình → thumb. Trả KHOÁ của ảnh gốc.

    Tải theo DÒNG và cắt ngay khi quá trần: `r.content` tải trọn rồi mới đo, nên một
    phản hồi 2 GB đã nằm trong RAM trước khi ta kịp từ chối — đó là một điều ước, không
    phải một giới hạn.
    """
    from portal.modules.kb.storage import thumbnail

    async with http.stream("GET", url) as r:
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not ctype.startswith("image/"):
            raise ValueError(f"không phải ảnh: content-type={ctype!r}")
        buf = bytearray()
        async for part in r.aiter_bytes():
            buf.extend(part)
            if len(buf) > MAX_BYTES:
                raise ValueError(f"ảnh vượt trần {MAX_BYTES} byte")
    data = bytes(buf)

    digest = hashlib.sha256(data).hexdigest()
    key = store.key(tenant_id=tenant_id, path=f"kb/anh/{digest}.{_ext(ctype, url)}")
    await store.put(key=key, data=data, content_type=ctype)
    # `key` đã mang tiền tố tenant; `build_key` idempotent nên truyền lại là an toàn,
    # và `is_internal_key(key)` True ⇒ thumb thành `.../kb/anh/<digest>.thumb.webp`.
    await thumbnail.sinh_va_luu(
        store, tenant_id=tenant_id, media_url=key, content_hash=digest, tai_ve=lambda: data
    )
    return key


def _ext(ctype: str, url: str) -> str:
    """Đuôi tệp: theo content-type trước, rơi về đuôi trong URL, cuối cùng là `bin`."""
    if ctype in _EXT_BY_TYPE:
        return _EXT_BY_TYPE[ctype]
    name = url.split("?", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext if ext.isalnum() and len(ext) <= 5 else "bin"
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_external_images_fetch.py -v`
Expected: PASS 8/8

- [ ] **Step 5: Chạy lại cả Task 2 để chắc không vỡ**

Run: `uv run pytest tests/modules/kb/test_external_images.py tests/modules/kb/test_external_images_fetch.py -v`
Expected: PASS 15/15

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/clients/external_images.py tests/modules/kb/test_external_images_fetch.py
git commit -m "feat(kb): mirror external images into our own store, with a thumbnail

Keyed by the hash of the image bytes, so two documents sharing a picture cost
one copy and re-uploading the same file creates no orphans. Download is
streamed and aborted past the cap -- reading r.content and measuring afterwards
is a wish, not a limit.

A broken image never fails the document: it keeps its original URL and adds a
warning, the same trade jobs._thumb_neu_thieu already documents. Writing an
empty URL instead would produce ![alt]() -- a picture lost with nothing raised."
```

---

## Task 4: Nối vào cả hai đường nạp + bất biến tự canh

**Files:**
- Modify: `src/portal/modules/kb/contracts.py` (thêm field vào `TextDirective`)
- Modify: `src/portal/modules/kb/service.py:88-105` và `:315-330`
- Modify: `src/portal/modules/kb/clients/rag.py` (`RagClient.index`)
- Test: `tests/modules/kb/test_images_mirrored_every_path.py`

**Interfaces:**
- Consumes: `external_images.mirror_images` (Task 3).
- Produces: `TextDirective.images_mirrored: bool = False`; `RagClient.index` ném `ValueError` khi `images_mirrored` False và text còn ảnh ngoài.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_images_mirrored_every_path.py`:

```python
import pytest

from portal.modules.kb.contracts import ChunkSpec, TextDirective


def _directive(text: str, **kw) -> TextDirective:
    return TextDirective(
        workspace_slug="ws",
        record_id=1,
        doc_type="kb_file",
        anchor_code="__ALL__",
        anchor_name="sotay.md",
        section="",
        text=text,
        chunk=ChunkSpec(),
        **kw,
    )


def test_directive_mac_dinh_chua_soi_anh():
    assert _directive("x").images_mirrored is False


def test_cong_nem_khi_text_con_anh_ngoai_ma_chua_soi():
    """Bất biến: một đường nạp thứ ba viết sau này mà quên gọi `mirror_images` phải vỡ TO
    TIẾNG, chứ không âm thầm nhúng URL của khách vào vector."""
    from portal.modules.kb.clients.rag import _check_mirrored

    with pytest.raises(ValueError, match="chưa soi ảnh ngoài"):
        _check_mirrored(_directive("![x](https://s3.khach.vn/1.png)"))


def test_cong_im_lang_khi_da_soi():
    """Đã soi rồi mà URL gốc còn đó là ca HỢP LỆ — ảnh 404 giữ URL gốc (Task 3)."""
    from portal.modules.kb.clients.rag import _check_mirrored

    _check_mirrored(_directive("![x](https://s3.khach.vn/1.png)", images_mirrored=True))


def test_cong_im_lang_khi_text_khong_co_anh_ngoai():
    from portal.modules.kb.clients.rag import _check_mirrored

    _check_mirrored(_directive("Chỉ có chữ."))


def test_cong_im_lang_voi_link_da_tro_kho_minh():
    """Link đã viết lại vẫn là `![](https://…)` — cổng KHÔNG được bắt nó khi đã soi."""
    from portal.modules.kb.clients.rag import _check_mirrored

    _check_mirrored(_directive("![x](https://portal.vn/api/v1/public/files/a.png)", images_mirrored=True))
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_images_mirrored_every_path.py -v`
Expected: FAIL — `TypeError: TextDirective.__init__() got an unexpected keyword argument 'images_mirrored'`

- [ ] **Step 3: Thêm field vào `TextDirective`**

Trong `src/portal/modules/kb/contracts.py`, thêm sau dòng `entity: str = ""` (dòng 52):

```python
    images_mirrored: bool = False
    """Đã chạy `external_images.mirror_images` trên `text` chưa.

    Cờ CHỨ KHÔNG phải phép kiểm «text không còn URL lạ»: soi xong mà một ảnh 404 thì
    URL gốc CỐ Ý ở lại (xem `mirror_images`), nên một phép kiểm theo nội dung sẽ đánh trượt
    đúng ca hợp lệ. Cái cần canh là «đường nạp có gọi soi hay không»."""
```

- [ ] **Step 4: Thêm bất biến vào `RagClient.index`**

Trong `src/portal/modules/kb/clients/rag.py`, thêm `import re` cạnh `import hashlib` (dòng 12), rồi hằng cạnh `_PHAN_CACH_BAM`:

```python
_EXTERNAL_IMG = re.compile(r"!\[[^\]]*\]\(https?://")
```

và một hàm cạnh `_updated_at`:

```python
def _check_mirrored(directive: TextDirective) -> None:
    """Ném nếu directive chưa đi qua `external_images.mirror_images`.

    Hàm RIÊNG chứ không phải vài dòng trong `index`: cổng này phải test được mà không
    dựng cả client (embed + Qdrant + kho), và một bài test phải khẳng định ĐÚNG cái nó
    đo — bắt `AttributeError` của một instance nửa vời là đo nhầm thứ.
    """
    if not directive.images_mirrored and _EXTERNAL_IMG.search(directive.text):
        raise ValueError(
            f"directive {directive.doc_type}#{directive.record_id} chưa soi ảnh ngoài — "
            "gọi `external_images.mirror_images` trước khi băm và nhúng"
        )
```

rồi gọi ở dòng đầu `RagClient.index`, TRƯỚC `name = self.collection(...)`:

```python
        _check_mirrored(directive)
```

- [ ] **Step 5: Chạy test bất biến**

Run: `uv run pytest tests/modules/kb/test_images_mirrored_every_path.py -v`
Expected: PASS 4/4

- [ ] **Step 6: Nối vào đường 1 (`documents.body` — form dự án + cổng nạp API)**

Trong `src/portal/modules/kb/service.py`, ngay SAU khối `directive = resolve.resolve_text(...)` (kết thúc dòng ~95) và TRƯỚC `old_hash = await _can_skip(`:

```python
    # SOI ẢNH TRƯỚC KHI BĂM. `_can_skip` so `content_hash_of(directive)` với dấu tay đã
    # lưu, mà dấu tay lưu lần trước tính trên text ĐÃ soi — soi sau phép so là hai lần
    # băm hai chuỗi khác nhau, và tài liệu được nhúng lại ở MỌI lượt mà không ai thấy.
    new_text, image_warnings = await external_images.mirror_images(directive.text, tenant_id=tenant_id, store=store)
    for c in image_warnings:
        log.warning("soi ảnh %s#%s: %s", entity, record_id, c)
    directive = dataclasses.replace(directive, text=new_text, images_mirrored=True)
```

Thêm import ở đầu tệp:

```python
import dataclasses

from portal.modules.kb.clients import external_images
```

- [ ] **Step 7: Nối vào đường 2 (`kb_files` — tab Tài liệu chung)**

Trong cùng tệp, trong `index_kb_file`, thay khối dựng directive (dòng ~315) thành:

```python
    new_text, image_warnings = await external_images.mirror_images(out.text, tenant_id=tenant_id, store=store)
    for c in image_warnings:
        log.warning("soi ảnh kb_files#%s: %s", record_id, c)

    directive = TextDirective(
        workspace_slug=slug,
        record_id=record_id,
        doc_type=DOC_TYPE_KB_FILE,
        anchor_code=settings.SYSTEM_ANCHOR,
        anchor_name=row.ten_file,
        section="",
        text=new_text,
        chunk=ChunkSpec(),
        status="published",
        anchor_status="published",
        updated_at=row.uploaded_at,
        file_url=row.s3_key,
        file_name=row.ten_file,
        images_mirrored=True,
    )
```

Và đổi câu trả về cuối hàm để cảnh báo tới được `JobResult.message`:

```python
    ext = f" · {len(image_warnings)} ảnh lỗi" if image_warnings else ""
    return f"kb_files#{record_id}: +{result.points_upserted} point{ext}"
```

- [ ] **Step 8: Đổi thông điệp lỗi cho `.md` rỗng**

Trong `index_kb_file`, thay nhánh `if not ra.text:`:

```python
    if not out.text:
        message = MD_EMPTY_MESSAGE if row.loai == "md" else THONG_DIEP_KHONG_CO_CHU
        await files_repo.danh_dau_loi(conn, record_id=record_id, loi_message=message)
        return f"kb_files#{record_id}: không có nội dung, đã đánh dấu lỗi"
```

Thêm `MD_EMPTY_MESSAGE` vào khối import từ `portal.modules.kb.contracts`.

- [ ] **Step 9: Chạy test module kb**

Run: `uv run pytest tests/modules/kb -v`
Expected: PASS toàn bộ. Nếu `test_kb_file_index_job.py` hoặc `test_directive.py` đỏ vì thiếu `store` trong lời gọi giả — sửa test cho khớp chữ ký mới, ĐỪNG bỏ bước soi.

- [ ] **Step 10: Commit**

```bash
git add src/portal/modules/kb/contracts.py src/portal/modules/kb/service.py \
        src/portal/modules/kb/clients/rag.py tests/modules/kb/test_images_mirrored_every_path.py
git commit -m "feat(kb): mirror images on every text path into Qdrant, not just one tab

documents.body reaches Qdrant from the project form and from the external
ingest API, so scoping this to kb_files would have left both uncovered.

The mirror runs before content_hash_of, not inside index: the skip check
compares a hash of the pre-mirror text against a stored hash of post-mirror
text, so hashing on either side of the mirror would re-embed every document on
every run with nothing to show for it.

RagClient.index now refuses a directive that never went through the mirror. The
guard is a flag rather than a scan for foreign URLs, because a 404 image
deliberately keeps its original link and a content scan would fail that valid
case."
```

---

## Task 5: Chunker giữ ảnh cạnh câu dẫn

**Files:**
- Modify: `src/portal/modules/kb/index/chunker.py` (sau `_tach_khoi`)
- Test: `tests/modules/kb/test_chunker.py`

**Interfaces:**
- Produces: `_attach_image_to_lead_in(khoi: list[_Khoi]) -> list[_Khoi]` — khối chỉ có ảnh được gộp vào khối liền trước cùng đường dẫn.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/modules/kb/test_chunker.py`:

```python
def test_anh_khong_roi_cau_dan():
    """Dòng trống giữa câu dẫn và ảnh làm `_tach_khoi` xả thành hai khối; khi mép gói
    rơi đúng đó thì chunk sau MỞ ĐẦU bằng ảnh và mất câu giải thích nó là ảnh gì.
    Đo trên sổ tay CTV: 2/33 chunk dính lỗi này."""
    from portal.modules.kb.contracts import ChunkSpec
    from portal.modules.kb.index import chunker

    text = (
        "## Đăng nhập\n\n"
        "Ở màn đăng nhập, bấm **Quên mật khẩu**.\n\n"
        "![Màn đăng nhập AINA](https://portal.vn/api/v1/public/files/a.png)\n\n"
        "Nhập số điện thoại đã đăng ký.\n"
    )
    parts = chunker.split(text, ChunkSpec(max_chars=1000, overlap=100, min_chars=300))
    for m in parts:
        assert not m.text.lstrip().startswith("!["), f"chunk mở đầu bằng ảnh: {m.text[:60]!r}"


def test_anh_dau_tai_lieu_khong_co_cau_dan_van_chay():
    """Không có khối nào trước thì ảnh đứng một mình — không được nổ."""
    from portal.modules.kb.contracts import ChunkSpec
    from portal.modules.kb.index import chunker

    text = "![chỉ có ảnh](https://portal.vn/api/v1/public/files/a.png)\n\nSau đó là chữ.\n"
    parts = chunker.split(text, ChunkSpec(max_chars=1000, overlap=100, min_chars=300))
    assert parts and "chỉ có ảnh" in parts[0].text


def test_anh_khong_gop_xuyen_section():
    """Ảnh mở đầu một section KHÔNG được kéo ngược vào section trước — hai section nói
    hai chuyện khác nhau, đúng luật `_goi_cung_cha` đã có."""
    from portal.modules.kb.contracts import ChunkSpec
    from portal.modules.kb.index import chunker

    text = (
        "## A\n\nChữ của A.\n\n"
        "## B\n\n![ảnh của B](https://portal.vn/api/v1/public/files/b.png)\n\nChữ của B.\n"
    )
    parts = chunker.split(text, ChunkSpec(max_chars=1000, overlap=100, min_chars=300))
    cua_a = [m for m in parts if m.section_path and m.section_path[-1] == "A"]
    assert all("ảnh của B" not in m.text for m in cua_a)
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_chunker.py -k "anh" -v`
Expected: FAIL ở `test_anh_khong_roi_cau_dan` — có chunk mở đầu bằng `![`

- [ ] **Step 3: Viết hàm gộp**

Thêm vào `src/portal/modules/kb/index/chunker.py`, ngay sau `_tach_khoi`:

```python
_IMAGE_ONLY = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")


def _attach_image_to_lead_in(blocks: list[_Khoi]) -> list[_Khoi]:
    """Khối chỉ có ảnh gộp vào khối liền trước CÙNG ĐƯỜNG DẪN.

    Markdown viết câu dẫn, một dòng trống, rồi ảnh — mà dòng trống chính là điểm xả của
    `_tach_khoi`. Hai khối rời nhau thường được `_goi_cung_cha` gói lại, nhưng khi mép
    gói rơi đúng chỗ đó thì chunk sau MỞ ĐẦU bằng một tấm ảnh, không còn câu nào nói nó
    là ảnh gì — và với ảnh thì URL không mang nghĩa gì cho phép tìm.

    KHÔNG gộp xuyên đường dẫn: ảnh mở đầu section B không thuộc về section A. Không gộp
    khi khối trước là bảng: `la_bang` điều khiển `_cat_bang` (lặp hàng tiêu đề ở mỗi
    mảnh), và một khối lẫn bảng với ảnh sẽ đi sai nhánh cắt.
    """
    out: list[_Khoi] = []
    for k in blocks:
        image_only = all(_IMAGE_ONLY.match(d) for d in k.text.splitlines() if d.strip())
        if out and image_only and not k.la_bang and not out[-1].la_bang and out[-1].path == k.path:
            prev = out[-1]
            out[-1] = _Khoi(f"{prev.text}\n\n{k.text}", prev.path, prev.la_bang)
            continue
        out.append(k)
    return out
```

- [ ] **Step 4: Nối vào `split`**

Sửa dòng 73-76 của `chunker.py`:

```python
    blocks = _attach_image_to_lead_in(_tach_khoi(text, root))
    if not blocks:
        return []
    return _goi_cung_cha(blocks, spec)
```

- [ ] **Step 5: Chạy test**

Run: `uv run pytest tests/modules/kb/test_chunker.py -v`
Expected: PASS toàn bộ — cả ba bài mới lẫn các bài cũ

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/index/chunker.py tests/modules/kb/test_chunker.py
git commit -m "fix(kb): keep an image in the same block as the sentence introducing it

Markdown puts a blank line between the lead-in and the picture, and that blank
line is exactly where _tach_khoi flushes. Usually _goi_cung_cha packs the two
back together, but when the packing boundary lands there the next chunk opens
with an image and no sentence saying what it shows -- measured at 2 of 33
chunks on the CTV manual. A URL carries no meaning for retrieval, so that chunk
loses the picture entirely as far as search is concerned.

Never merges across a section path or into a table block: the first would pull
section B's image into section A, the second would send a mixed block down the
table-splitting branch that repeats header rows."
```

---

## Task 6: Chuỗi nhúng bỏ URL + sửa hợp đồng payload

**Files:**
- Modify: `src/portal/modules/kb/clients/rag.py` (`_text_de_nhung`)
- Modify: `docs/contracts/payload-qdrant.md` §3
- Test: `tests/modules/kb/test_payload_khoa.py`

**Interfaces:**
- Consumes: `TextDirective`, `chunker.Chunk`.
- Produces: `_text_de_nhung` trả chuỗi đã thay `![alt](url)` → `alt`; `payload["text"]` **không đổi**, vẫn giữ markdown đầy đủ.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/modules/kb/test_payload_khoa.py`:

```python
def test_chuoi_nhung_bo_url_giu_alt():
    from portal.modules.kb.clients.rag import _text_de_nhung
    from portal.modules.kb.contracts import ChunkSpec, TextDirective
    from portal.modules.kb.index.chunker import Chunk

    d = TextDirective(
        workspace_slug="ws", record_id=1, doc_type="kb_file", anchor_code="__ALL__",
        anchor_name="Sổ tay", section="", text="", chunk=ChunkSpec(),
    )
    c = Chunk("Bấm Quên mật khẩu.\n\n![Màn đăng nhập AINA](https://portal.vn/x/a.png)", ())

    out = _text_de_nhung(d, c)

    assert "https://" not in out
    assert "Màn đăng nhập AINA" in out   # alt là thứ DUY NHẤT mang nghĩa của ảnh
    assert "Bấm Quên mật khẩu." in out


def test_chunk_text_van_giu_markdown_day_du():
    """`payload["text"]` lấy từ `chunk.text`, KHÔNG từ chuỗi nhúng — agent đọc nó để
    dựng `items`, bỏ URL ở đó là mất luôn ảnh. Bài này canh hai chuỗi ĐÃ TÁCH ĐÔI."""
    from portal.modules.kb.clients.rag import _text_de_nhung
    from portal.modules.kb.contracts import ChunkSpec, TextDirective
    from portal.modules.kb.index.chunker import Chunk

    d = TextDirective(
        workspace_slug="ws", record_id=1, doc_type="kb_file", anchor_code="__ALL__",
        anchor_name="", section="", text="", chunk=ChunkSpec(),
    )
    c = Chunk("![Màn đăng nhập](https://portal.vn/x/a.png)", ())

    assert "![" in c.text and "https://" in c.text     # nguồn của payload: nguyên vẹn
    assert "![" not in _text_de_nhung(d, c)            # chuỗi nhúng: đã bỏ
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/kb/test_payload_khoa.py -k "nhung" -v`
Expected: FAIL — `assert "https://" not in ra`

- [ ] **Step 3: Sửa `_text_de_nhung`**

Trong `src/portal/modules/kb/clients/rag.py`, thay hàm (dòng 44-46):

`import re` đã thêm ở Task 4 — chỉ thêm hằng:

```python
_IMG_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


def _text_de_nhung(directive: TextDirective, c: chunker.Chunk) -> str:
    """Chuỗi ĐEM NHÚNG — khác `payload["text"]`, và khác có chủ ý.

    URL ảnh bị thay bằng chính `alt` của nó: một URL S3 dài ~130 ký tự không mang nghĩa
    nào cho phép tìm ngữ nghĩa, nó chỉ ăn chỗ trong vector. Đo trên sổ tay CTV: bỏ URL
    khỏi chuỗi nhúng nhấc ảnh mong đợi từ hạng 1 **7/10 lên 8/10**, và URL trong bài đo
    chỉ dài 67 ký tự — nhiễu thật gấp đôi.

    ⚠️ `payload["text"]` VẪN giữ markdown đầy đủ: đó là thứ agent đọc để dựng `items`,
    bỏ URL ở đó là mất luôn ảnh. Nên từ bản này `text` KHÔNG còn bằng chuỗi đã nhúng —
    `docs/contracts/payload-qdrant.md` §3 đã sửa theo.
    """
    prefix = _tien_to(directive, c)
    than = _IMG_MD.sub(lambda m: m.group(1), c.text)
    return f"{prefix}\n\n{than}" if prefix else than
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_payload_khoa.py tests/modules/kb/test_content_hash_of.py -v`
Expected: PASS. `content_hash` băm `c.text` (không phải chuỗi nhúng) nên **không** đổi — nếu `test_content_hash_of.py` đỏ thì bạn đã sửa nhầm chỗ.

- [ ] **Step 5: Sửa hợp đồng**

Trong `docs/contracts/payload-qdrant.md` §3, thay mô tả `text`:

```markdown
| `text` | Nội dung chunk, **markdown nguyên vẹn** (kể cả `![alt](url)`).
  ⚠️ KHÔNG bằng chuỗi đã nhúng: chuỗi nhúng thay `![alt](url)` bằng `alt` vì URL không
  mang nghĩa cho phép tìm ngữ nghĩa. Agent đọc `text` để dựng `items`, nên ảnh phải còn
  nguyên ở đây. Đổi 2026-08-28. |
```

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/clients/rag.py docs/contracts/payload-qdrant.md tests/modules/kb/test_payload_khoa.py
git commit -m "perf(kb): drop image URLs from the embedded string, keep them in the payload

A 130-character S3 URL carries no meaning for semantic search; it only takes up
room in the vector. Measured on the CTV manual: dropping URLs lifts the expected
image from rank 1 in 7 of 10 questions to 8 of 10, and the URLs in that
measurement were 67 characters -- half the length of the real ones.

payload[text] keeps the markdown intact, because that is what the agent reads to
build items. So text is no longer the string that was embedded, and the payload
contract now says so instead of claiming otherwise."
```

---

## Task 7: Hợp đồng gateway khai `kb_search` và `index`

**Files:**
- Modify: `src/portal/modules/enrollment/tai_nguyen/gateway-protocol.json`
- Test: `tests/modules/enrollment/test_gateway_docs.py`

**Interfaces:**
- Produces: `tool_results.kb_search` trong artefact; `MediaItem` biến thể `image` có thuộc tính `index`.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/modules/enrollment/test_gateway_docs.py`:

```python
def test_tool_results_co_kb_search():
    """kb_search trả `items` khi câu trả lời lấy từ một tài liệu có ảnh. Không khai ở
    đây thì dev bên thứ ba đọc đúng hợp đồng vẫn không render ảnh nào."""
    import json
    from importlib import resources

    d = json.loads(
        resources.files("portal.modules.enrollment.tai_nguyen")
        .joinpath("gateway-protocol.json")
        .read_text(encoding="utf-8")
    )
    assert "kb_search" in d["tool_results"]


def test_media_item_anh_co_truong_index():
    import json
    from importlib import resources

    d = json.loads(
        resources.files("portal.modules.enrollment.tai_nguyen")
        .joinpath("gateway-protocol.json")
        .read_text(encoding="utf-8")
    )
    assert "index" in json.dumps(d["tool_results"]["kb_search"], ensure_ascii=False)
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `uv run pytest tests/modules/enrollment/test_gateway_docs.py -k "kb_search or truong_so" -v`
Expected: FAIL — `KeyError: 'kb_search'`

- [ ] **Step 3: Thêm mục vào artefact**

Trong `gateway-protocol.json`, thêm vào object `tool_results`:

```json
"kb_search": {
  "title": "ToolResult_kb_search",
  "description": "Hai hình dạng. Không có ảnh nguồn ⇒ result là CHUỖI TRẦN (ngữ cảnh). Có ảnh ⇒ JSON `{context, items}`. Bắt card theo sự hiện diện của `items`, đừng bắt theo tên tool.\n\n`items[].index` là số tấm ảnh, và câu trả lời của agent trỏ tới nó bằng chữ — «(xem ảnh 3)». Số DUY NHẤT trong cả cuộc trò chuyện, không phải trong một lượt: ảnh 3 ở lượt trước vẫn là ảnh 3 bây giờ. Client nên hiện số đó cạnh ảnh, nếu không người đọc không biết «ảnh 3» là tấm nào.",
  "type": "object",
  "properties": {
    "context": { "type": "string", "description": "Ngữ cảnh đã ghép từ các đoạn khớp." },
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "kind": { "const": "image" },
          "url": { "type": "string" },
          "label": { "type": "string" },
          "thumb": { "type": "string" },
          "index": { "type": "integer", "minimum": 1, "description": "Số tấm ảnh, duy nhất trong cả cuộc trò chuyện." }
        },
        "required": ["kind", "url", "index"]
      }
    }
  },
  "required": ["context", "items"]
}
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/enrollment/test_gateway_docs.py -v`
Expected: PASS toàn bộ — gồm cả bài canh `$ref` không đích sẵn có

- [ ] **Step 5: Xem thử trang docs render được**

Run: `make api` ở một terminal, rồi:
```bash
curl -s localhost:8100/api/v1/agent/gateway/openapi.json | python3 -c "import json,sys; json.load(sys.stdin); print('spec hợp lệ')"
```
Expected: `spec hợp lệ`

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/enrollment/tai_nguyen/gateway-protocol.json tests/modules/enrollment/test_gateway_docs.py
git commit -m "docs(gateway): document the kb_search tool result and its image numbers

kb_search can return items, and nothing in the artefact said so -- a third-party
client written against the contract would render no pictures at all.

The number matters as much as the URL: the answer points at a picture in prose,
'(xem ảnh 3)', and a client that drops the number leaves the reader with no way
to tell which image that is. Numbers are unique across the conversation, not
within a turn."
```

---

## Task 8: Agent — mốc `[ảnh N]`, sổ theo phiên, items có `index`

**Repo:** `odyssey-agent`

**Files:**
- Modify: `src/noble_agent/agent/rag/kb_service_adapter.py`
- Modify: `src/noble_agent/agent/tools/noble_search.py`
- Test: `tests/unit/test_kb_image_numbers.py`

**Interfaces:**
- Consumes: payload `text` chứa `![alt](url)` (Task 6 giữ nguyên).
- Produces: `_format_kb_hits(hits, numbers)` thay ảnh bằng `[ảnh N — alt]`; `_dinh_kem(hits, numbers)` trả item `kind:"image"` kèm `index`; sổ `dict[str, int]` sống ở `state.scratchpad["image_numbers"]`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_kb_image_numbers.py`:

```python
from noble_agent.agent.rag import kb_service_adapter as kb

U1 = "https://portal.vn/api/v1/public/files/tenants/t/kb/anh/aaa.png"
U2 = "https://portal.vn/api/v1/public/files/tenants/t/kb/anh/bbb.png"


def _hit(text):
    return {"text": text, "project_name": "", "section_path": [], "updated_at": ""}


def test_url_khong_bao_gio_vao_ngu_canh():
    numbers = {}
    out = kb._format_kb_hits([_hit(f"Bấm Quên mật khẩu.\n\n![Màn đăng nhập]({U1})")], numbers)
    assert "https://" not in out
    assert "[ảnh 1 — Màn đăng nhập]" in out


def test_so_giu_nguyen_qua_luot():
    """Sổ mang sang lượt sau: cùng ảnh phải cùng số, ảnh mới lấy số kế tiếp."""
    numbers = {}
    kb._format_kb_hits([_hit(f"![a]({U1})")], numbers)
    out = kb._format_kb_hits([_hit(f"![a]({U1})\n\n![b]({U2})")], numbers)
    assert "[ảnh 1 — a]" in out and "[ảnh 2 — b]" in out


def test_anh_moi_o_luot_sau_khong_dung_lai_so_cu():
    numbers = {}
    kb._format_kb_hits([_hit(f"![a]({U1})")], numbers)
    out = kb._format_kb_hits([_hit(f"![b]({U2})")], numbers)
    assert "[ảnh 2 — b]" in out
    assert "[ảnh 1" not in out


def test_dinh_kem_tra_item_anh_co_so():
    numbers = {}
    kb._format_kb_hits([_hit(f"![Màn đăng nhập]({U1})")], numbers)
    items = kb._dinh_kem([_hit(f"![Màn đăng nhập]({U1})")], numbers)
    assert items == [{"kind": "image", "url": U1, "label": "Màn đăng nhập", "so": 1}]


def test_cung_anh_hai_chunk_chi_mot_item():
    numbers = {}
    hits = [_hit(f"![a]({U1})"), _hit(f"Nhắc lại.\n\n![a]({U1})")]
    kb._format_kb_hits(hits, numbers)
    assert len(kb._dinh_kem(hits, numbers)) == 1


def test_so_bom_vao_prompt_chan_o_sau_muc():
    """Sổ dài kéo mô hình khỏi tài liệu — đo được: 20 mục làm tỉ lệ nhắc ảnh của chính
    lượt đó tụt còn 2/3, chặn ở 6 đưa lại 3/3."""
    numbers = {f"u{i}": i + 1 for i in range(20)}
    line = kb.earlier_image_lines(numbers, in_use=set())
    assert len(line) == 6
    assert line[0].startswith("- ảnh 15")   # sáu số LỚN NHẤT, tức gần nhất
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `cd /home/thanhhai/Desktop/odyssey-agent && uv run pytest tests/unit/test_kb_image_numbers.py -v`
Expected: FAIL — `TypeError: _format_kb_hits() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Sửa `kb_service_adapter.py`**

Thêm đầu tệp, sau `SPARSE_VECTOR`:

```python
import re

_IMG_MD = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
_REMINDER_CAP = 6
```

Thay `_format_kb_hits` và `_dinh_kem`:

```python
def _number_for(url: str, numbers: dict[str, int]) -> int:
    """Số của một ảnh, cấp mới nếu chưa có. Sổ dùng chung cho CẢ CUỘC trò chuyện.

    Đánh số lại mỗi lượt là hỏng: đo 2026-08-28, 2 trên 3 kịch bản có `ảnh 1` ở lượt sau
    là một tấm khác `ảnh 1` ở lượt trước, và câu hỏi ngược ("ảnh lúc nãy là màn hình
    nào") bị trả lời bằng "Bạn đang hỏi về ảnh nào?".
    """
    if url not in numbers:
        numbers[url] = len(numbers) + 1
    return numbers[url]


def _format_kb_hits(hits: list[dict], numbers: dict[str, int] | None = None) -> str:
    """One block per hit, separated by '\\n---\\n'.

    URL ảnh KHÔNG BAO GIỜ vào ngữ cảnh — thay bằng mốc `[ảnh N — mô tả]` đúng chỗ cũ.
    Cho mô hình chép URL thật thì 1 trên 3 lượt nó chép sai (`127.0.0.1` → `127.00.1`)
    và ảnh vỡ. Mốc là NGÔN NGỮ chứ không phải mã máy: mốc không được thay thì "xem ảnh 1"
    vẫn là câu đọc được, còn một mã băm là rác trên màn hình.
    """
    numbers = {} if numbers is None else numbers
    blocks: list[str] = []
    for h in hits:
        text = (h.get("text") or "").strip()
        if not text:
            continue
        text = _IMG_MD.sub(lambda m: f"[ảnh {_number_for(m.group(2), numbers)} — {m.group(1)}]", text)
        name = (h.get("project_name") or "").strip()
        section = _section(h)
        updated = (h.get("updated_at") or "").strip()
        parts: list[str] = []
        if name and section:
            parts.append(f"[{name} › {section}]")
        elif name:
            parts.append(f"[{name}]")
        elif section:
            parts.append(f"[{section}]")
        parts.append(text)
        if updated:
            parts.append(f"(cập nhật: {updated})")
        blocks.append("\n".join(parts))
    return "\n---\n".join(blocks)


def _dinh_kem(hits: list[dict], numbers: dict[str, int] | None = None) -> list[dict]:
    """Ảnh trong `text` → `items` cho client, kèm số đã cấp ở `_format_kb_hits`.

    VÌ SAO QUA ``items`` CHỨ KHÔNG NHÉT LINK VÀO ``text``: nhét vào text nghĩa là LLM phải
    CHÉP LẠI đường dẫn khi trả lời, và một URL dài nhiều tham số thì chép sai là chuyện sẽ
    xảy out. Đi qua ``items`` thì client tự render và LLM không bao giờ chạm vào chuỗi link.

    Trùng lặp bị loại theo URL: cùng một ảnh khớp ở ba chunk thì khách không nhận ba lần.
    """
    numbers = {} if numbers is None else numbers
    out: list[dict] = []
    da_co: set[str] = set()
    for h in hits:
        for alt, url in _IMG_MD.findall(h.get("text") or ""):
            if url in da_co:
                continue
            da_co.add(url)
            out.append({"kind": "image", "url": url, "label": alt, "index": _number_for(url, numbers)})
    return out


def earlier_image_lines(numbers: dict[str, int], *, in_use: set[str]) -> list[str]:
    """Dòng nhắc cho ảnh ĐÃ cấp số nhưng không có trong tài liệu lượt này.

    ⚠️ CHẶN Ở SÁU MỤC GẦN NHẤT. Thả tự do tới 20 mục thì tỉ lệ nhắc ảnh của chính lượt
    đang trả lời tụt còn 2/3 (sổ trống: 3/3, lặp 3 lần) — một danh sách dài chen vào
    system prompt kéo mô hình khỏi tài liệu. Sổ này chỉ phục vụ câu hỏi ngược, mà "ảnh
    lúc nãy" luôn là chuyện gần; giữ đuôi cũng chặn prompt phình theo độ dài hội thoại.
    """
    earlier = sorted((n, u) for u, n in numbers.items() if u not in in_use)
    return [f"- ảnh {n}: {u.rsplit('/', 1)[-1]}" for n, u in earlier[-_REMINDER_CAP:]]
```

Trong `query_kb_service_for_noble_kb`, thêm tham số `numbers: dict[str, int] | None = None` và chuyền xuống:

```python
    if dinh_kem is not None and settings.kb_search_attach_source_files:
        dinh_kem.extend(_dinh_kem(hits, numbers))
    if du_an is not None:
        ma = _du_an_duy_nhat(hits)
        if ma:
            du_an.append(ma)
    context = _format_kb_hits(hits, numbers)
    if numbers:
        in_use = {u for h in hits for _, u in _IMG_MD.findall(h.get("text") or "")}
        lines = earlier_image_lines(numbers, in_use=in_use)
        if lines:
            context += (
                "\n---\nẢNH ĐÃ NHẮC TRƯỚC ĐÓ (không có trong tài liệu lượt này, "
                "chỉ để tra lại khi khách hỏi về nó):\n" + "\n".join(lines)
            )
    return context
```

Khối nhắc đi vào **cuối ngữ cảnh của tool**, không phải system prompt: chỗ đó nằm gọn
trong một tệp, không phải mở một seam mới sang `runner.build_system_prompt`. Tác dụng đo
được (chặn ở 6) không phụ thuộc nó nằm ở đâu — nó phụ thuộc độ dài.

- [ ] **Step 4: Nối sổ vào `noble_search.run`**

Trong `src/noble_agent/agent/tools/noble_search.py`, sửa Protocol và lời gọi:

```python
class _DispatcherCtx(Protocol):
    customer: object
    state: object

    def mark_customer_dirty(self) -> None: ...
```

và trước lời gọi `rag.search`:

```python
    # Sổ số ảnh sống theo PHIÊN, không theo lượt — `state.scratchpad` đã là chỗ cho thứ
    # như vậy (`recent_projects` dùng cùng kiểu) và nó được lưu Redis cùng state.
    #
    # ⚠️ KHÔNG viết `getattr(...) and ... or {}`: một scratchpad rỗng là falsy, nên `or`
    # sẽ trả về một dict MỚI và sổ mất liên kết với state — số lại đánh theo lượt, đúng
    # cái bản vá này tồn tại để chấm dứt, mà không lỗi nào phát out.
    state = getattr(dispatcher, "state", None)
    image_numbers: dict[str, int] = state.scratchpad.setdefault("image_numbers", {}) if state is not None else {}
```

Rồi thêm `numbers=image_numbers` vào thang hai bậc `try/except TypeError` — bậc trên cùng:

```python
    try:
        result = await rag.search(
            query=query, project_filter=project_for_search, dinh_kem=dinh_kem, du_an=du_an, numbers=image_numbers
        )
    except TypeError:
        try:
            result = await rag.search(query=query, project_filter=project_for_search, dinh_kem=dinh_kem, du_an=du_an)
        except TypeError:
            try:
                result = await rag.search(query=query, project_filter=project_for_search, dinh_kem=dinh_kem)
            except TypeError:
                result = await rag.search(query=query, project_filter=project_for_search)
```

- [ ] **Step 5: Chạy test**

Run: `cd /home/thanhhai/Desktop/odyssey-agent && uv run pytest tests/unit/test_kb_image_numbers.py -v`
Expected: PASS 6/6

- [ ] **Step 6: Chạy cả bộ unit để chắc không vỡ**

Run: `uv run pytest tests/unit -q`
Expected: không có bài nào đỏ THÊM so với `git stash` baseline. `test_tool_ack.py` vốn flaky theo thời gian — chạy riêng nếu nó đỏ.

- [ ] **Step 7: Commit**

```bash
cd /home/thanhhai/Desktop/odyssey-agent
git add src/noble_agent/agent/rag/kb_service_adapter.py src/noble_agent/agent/tools/noble_search.py tests/unit/test_kb_image_numbers.py
git commit -m "feat(kb): replace image URLs in context with numbered markers

Letting the model copy a real URL back corrupts it in one answer out of three
-- 127.0.0.1 became 127.00.1 and the picture broke, with nothing raised. A
marker is language rather than machine code: if it is never substituted,
'see image 1' still reads as a sentence, where a hash would be litter.

Numbers are assigned per conversation, not per turn. Renumbering each turn made
'image 1' mean a different picture in two of three scenarios, and a follow-up
question about an earlier picture got 'which image do you mean?' instead of an
answer.

The reminder list injected into the prompt is capped at six. Left unbounded it
reached twenty entries and dropped the rate at which the model cited images
from the current answer to two in three; capping restored it."
```

---

## Task 9: Đổi tên tab thành «Tài liệu chung»

**Repo:** `odyssey-portal-frontend`

**Files:**
- Modify: `src/features/kb/nav.ts:27`
- Modify: `src/features/ops/components/TheKienThuc.tsx:108`
- Test: `src/features/kb/nav.test.ts` (nếu chưa có thì tạo)

**Interfaces:**
- Produces: nhãn hiển thị `"Tài liệu chung"` / `"General docs"`. Khoá hợp đồng `taiLieuTraCuu` **không đổi**.

- [ ] **Step 1: Viết test đỏ**

Tạo `src/features/kb/nav.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { kbNav } from './nav'
import { NHAN as NHAN_KIEN_THUC } from '@/features/ops/components/TheKienThuc'

describe('nhãn tab tài liệu', () => {
  it('gọi là «Tài liệu chung»', () => {
    expect(kbNav.label.vi).toBe('Tài liệu chung')
  })

  // Ô Dashboard và mục nav phải KHỚP NGUYÊN — comment ở TheKienThuc.tsx đã ghi lý do:
  // một lần lẫn hai kho làm ô đó hiện 6/6 trong lúc /kb trống trơn (2026-08-14).
  it('ô Dashboard mang đúng chữ đó', () => {
    expect(NHAN_KIEN_THUC.taiLieuTraCuu.ten).toBe(kbNav.label.vi)
  })
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `cd /home/thanhhai/Desktop/odyssey-portal-frontend && npx vitest run src/features/kb/nav.test.ts`
Expected: FAIL — nhận `'Tài liệu tra cứu'`, và có thể `NHAN_KIEN_THUC` chưa export

- [ ] **Step 3: Sửa nhãn nav**

`src/features/kb/nav.ts:27`:

```ts
  label: { vi: 'Tài liệu chung', en: 'General docs' },
```

- [ ] **Step 4: Sửa nhãn Dashboard và export hằng**

`src/features/ops/components/TheKienThuc.tsx:108`:

```tsx
  taiLieuTraCuu: { ten: 'Tài liệu chung', dk: 'đã nhúng vector', icon: 'kb' },
```

Hằng đó tên **`NHAN`** (dòng 90) và đang nội bộ — thêm `export` vào trước `const NHAN`,
giữ nguyên tên. Đổi tên nó là một diff to hơn hẳn phần việc thật.

⚠️ **KHOÁ `taiLieuTraCuu` GIỮ NGUYÊN** — nó là khoá trong `overview.kienThuc` do backend trả về. Đổi nó là đổi một API đang chạy để đổi lấy lợi ích bằng không.

- [ ] **Step 5: Chạy test + build**

Run:
```bash
npx vitest run src/features/kb/nav.test.ts
npm run build
```
Expected: test PASS; build sạch (`tsc -b` bắt lỗi kiểu mà `tsc --noEmit` bỏ sót)

- [ ] **Step 6: Commit**

```bash
git add src/features/kb/nav.ts src/features/ops/components/TheKienThuc.tsx src/features/kb/nav.test.ts
git commit -m "refactor(kb): rename the tab to «Tài liệu chung»

The contract key taiLieuTraCuu stays as it is -- renaming it would change a
live API for no gain. A test now pins the nav label and the dashboard card to
the same string, which the card's own comment has asked for since the day one
of them drifted and showed 6/6 while /kb was empty."
```

---

## Task 10: Frontend nhận `index` và hiện số trên ô ảnh

**Repo:** `odyssey-portal-frontend`

**Files:**
- Modify: `src/features/platform/chatGateway.ts:52-57,92-98`
- Modify: `src/features/platform/components/ThuAgentScreen.tsx` (`TheMedia`, ~1109-1140)
- Test: `src/features/platform/chatGateway.test.ts`

**Interfaces:**
- Consumes: `items[]` từ `tool_done.result` của `kb_search` (Task 8).
- Produces: `MedItemAnh.index?: number`, hiện dưới ô ảnh dạng «Ảnh N».

- [ ] **Step 1: Viết test đỏ**

Thêm vào `src/features/platform/chatGateway.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { chuanHoaMedia } from './chatGateway'

describe('chuanHoaMedia giữ số ảnh', () => {
  it('giữ `index` của item ảnh', () => {
    // chuanHoaMedia dựng lại từng item bằng danh sách trường CỨNG và bỏ mọi trường lạ;
    // không khai `index` ở đó thì số bị nuốt im lặng — không lỗi, không cảnh báo.
    const ra = chuanHoaMedia({
      items: [{ kind: 'image', url: 'https://x/a.png', label: 'Màn đăng nhập', index: 3 }],
    })
    expect(ra.items[0]).toMatchObject({ kind: 'image', index: 3 })
  })

  it('ảnh không có `index` vẫn nhận được', () => {
    const ra = chuanHoaMedia({ items: [{ kind: 'image', url: 'https://x/a.png' }] })
    expect(ra.items).toHaveLength(1)
    expect((ra.items[0] as { index?: number }).so).toBeUndefined()
  })
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `npx vitest run src/features/platform/chatGateway.test.ts -t "số ảnh"`
Expected: FAIL — `index` không có trong item trả về

- [ ] **Step 3: Khai `index` trong kiểu và chuẩn hoá**

`chatGateway.ts`, sửa `MedItemAnh`:

```ts
export interface MedItemAnh {
  readonly kind: 'image'
  readonly url: string
  readonly label?: string
  readonly thumb?: string
  /** Số tấm ảnh, DUY NHẤT trong cả cuộc trò chuyện. Câu trả lời trỏ tới nó bằng chữ
   *  — «(xem ảnh 3)» — nên không hiện số ra thì người đọc không biết đó là tấm nào. */
  readonly index?: number
}
```

và trong nhánh `image` của `chuanHoaMedia`:

```ts
    if (g['kind'] === 'image' && typeof g['url'] === 'string') {
      items.push({
        kind: 'image',
        url: g['url'],
        ...(typeof g['label'] === 'string' ? { label: g['label'] } : {}),
        ...(typeof g['thumb'] === 'string' ? { thumb: g['thumb'] } : {}),
        ...(typeof g['index'] === 'number' && g['index'] > 0 ? { so: g['index'] } : {}),
      })
    }
```

- [ ] **Step 4: Hiện số trên ô ảnh**

Trong `ThuAgentScreen.tsx`, nhánh `it.kind === 'image'` của `TheMedia`, bọc nút trong `<figure>`:

```tsx
          it.kind === 'image' ? (
            <figure key={i} className="m-0">
              <button
                type="button"
                onClick={(e) => {
                  oKichHoatRef.current = e.currentTarget
                  setAnhMo(anhs.indexOf(it))
                }}
                aria-label={`${t({ vi: 'Xem ảnh', en: 'View image' })}${it.label ? `: ${it.label}` : ''}`}
                className="block w-full overflow-hidden rounded-md bg-fill-strong"
              >
                <AnhLuoi it={it} />
              </button>
              {it.index !== undefined && (
                <figcaption className="mt-1 text-[11px] text-muted-2">
                  <span className="font-semibold text-ac">
                    {t({ vi: 'Ảnh', en: 'Image' })} {it.index}
                  </span>
                  {it.label ? ` — ${it.label}` : ''}
                </figcaption>
              )}
            </figure>
          ) : it.kind === 'tour' ? (
```

- [ ] **Step 5: Chạy test + build**

Run:
```bash
npx vitest run src/features/platform/chatGateway.test.ts
npm run build
```
Expected: PASS; build sạch

- [ ] **Step 6: Commit**

```bash
git add src/features/platform/chatGateway.ts src/features/platform/components/ThuAgentScreen.tsx src/features/platform/chatGateway.test.ts
git commit -m "feat(chat): carry the image number through and show it on the card

chuanHoaMedia rebuilds every item from a fixed field list and drops anything it
does not know, so an unlisted `index` would vanish with nothing raised. The answer
refers to a picture in prose -- '(xem ảnh 3)' -- and a grid with no numbers
leaves the reader guessing which tile that is."
```

---

## Task 11: Tệp thử + chạy đầu–cuối

**Files:**
- Create: `/home/thanhhai/Desktop/exp/extract/out/hdsd-s3-ngoai.md`
- Modify: `docs/superpowers/specs/2026-08-28-nap-md-anh-ngoai-design.md` (ghi kết quả đo)

**Interfaces:**
- Consumes: toàn bộ Task 1–10.

- [ ] **Step 1: Dựng bản thử trỏ MinIO dev**

`exp/extract/out/hdsd-s3.md` đã có sẵn (27 ảnh, link `http://127.0.0.1:9012/...`). Kiểm nó còn đủ ảnh:

```bash
grep -c '!\[' /home/thanhhai/Desktop/exp/extract/out/hdsd-s3.md
```
Expected: `27`

- [ ] **Step 2: Dựng bản thử trỏ host ngoài**

```bash
cd /home/thanhhai/Desktop/exp/extract
sed 's|http://127.0.0.1:9012/odyssey|https://s3.khach-gia.vn/kho|g' \
  out/hdsd-s3.md > out/hdsd-s3-ngoai.md
grep -c 's3.khach-gia.vn' out/hdsd-s3-ngoai.md
```
Expected: `27`

⚠️ Bản này chỉ dùng để xem **nhánh lỗi**: host không tồn tại nên cả 27 ảnh phải rơi vào «giữ URL gốc + cảnh báo», và tài liệu vẫn phải nạp thành công. Đó chính là bài kiểm quan trọng của §7 spec.

- [ ] **Step 3: Dựng hạ tầng và chạy**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend
make up
make api      # terminal 1
make worker   # terminal 2
```

- [ ] **Step 4: Tải bản MinIO lên tab Tài liệu chung**

Mở `http://localhost:5273/kb`, đăng nhập `dang@anphuland.vn` / `odyssey-dev`, tải `out/hdsd-s3.md`.

Expected: hàng chuyển `đang xử lý` → `sẵn sàng`. Xem log worker:
```
kb_files#<id>: +<n> point
```
KHÔNG có dòng `soi ảnh kb_files#…` nào (mọi ảnh kéo về được).

- [ ] **Step 5: Kiểm ảnh đã nằm trong kho mình**

```bash
docker compose -f docker-compose.local.yml exec -T minio \
  find /data -path '*/kb/anh/*' -type f | wc -l
```
Expected: `54` — 27 ảnh gốc + 27 thumb.
(`find` chứ không `mc ls`: `mc` cần alias đã cấu hình sẵn trong container, `find` thì không.)

- [ ] **Step 6: Kiểm payload không còn URL khách**

```bash
curl -s "http://localhost:6343/collections/anphu_documents/points/scroll" \
  -H 'Content-Type: application/json' \
  -d '{"limit":50,"with_payload":true}' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)['result']['points']
xau=[p for p in d if '127.0.0.1:9012' in (p['payload'].get('text') or '')]
print('point còn URL nguồn:', len(xau))
print('point có ảnh:', sum(1 for p in d if '![' in (p['payload'].get('text') or '')))"
```
Expected: `point còn URL nguồn: 0` và `point có ảnh:` lớn hơn 0

- [ ] **Step 7: Tải bản host ngoài lên, xem nhánh lỗi**

Tải `out/hdsd-s3-ngoai.md`.

Expected: hàng vẫn về `sẵn sàng` (**không** phải `lỗi`), và log worker có:
```
kb_files#<id>: +<n> point · 27 ảnh lỗi
```
cùng 27 dòng `soi ảnh kb_files#<id>: https://s3.khach-gia.vn/... ConnectError: ...`

- [ ] **Step 8: Bật cờ agent rồi hỏi thật**

Trong `.env` của `odyssey-agent`:
```
NOBLE_KB_SEARCH_ATTACH_SOURCE_FILES=true
```

Khởi động agent, mở `/thu-agent` trên portal, hỏi **"đổi mật khẩu thế nào"**.

Expected: câu trả lời có `(xem ảnh N)`, và card media dưới bong bóng hiện đúng tấm đó kèm chữ **«Ảnh N»**.

- [ ] **Step 9: Hỏi lượt hai để kiểm số giữ nguyên**

Hỏi tiếp **"thế còn quên mật khẩu thì sao"**, rồi **"ảnh lúc nãy là màn hình nào"**.

Expected: số ở lượt hai **không** trùng số lượt một cho hai tấm khác nhau; câu hỏi ngược được trả lời chứ không hỏi lại.

- [ ] **Step 10: Ghi kết quả đo vào spec**

Thêm mục `## 12. Kết quả đo đầu–cuối` vào spec với các con số THẬT quan sát được ở Step 4–9. Không chép số từ bài thử `exp` — đó là bài khác.

- [ ] **Step 11: Commit**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend
git add docs/superpowers/specs/2026-08-28-nap-md-anh-ngoai-design.md
git commit -m "docs(kb): record the end-to-end measurement for Markdown image ingestion"
```

---

## Kiểm cuối trước khi mở MR

- [ ] `cd odyssey-portal-backend && make check` — lint **và** test. Nhớ `make lint` là HAI lệnh (`ruff check` + `ruff format --check`).
- [ ] `cd odyssey-portal-backend && make test-isolation` — phải 52/52. Module `kb` không thêm SQL nào nên không cần vị từ mới; nếu đỏ thì đọc §RLS trong CLAUDE.md, ĐỪNG thêm allowlist.
- [ ] `cd odyssey-portal-frontend && npm run build` — `tsc -b`, không phải `tsc --noEmit`.
- [ ] `cd odyssey-agent && uv run pytest tests/unit -q` — so với baseline, không đỏ thêm.
- [ ] `cd odyssey-portal-backend && uv run python -c "import alembic"` và `alembic heads` — phải đúng MỘT head. Kế hoạch này không thêm migration, nên hai head nghĩa là bạn đã nhặt nhầm gì đó từ nhánh khác.
