# Ingest lên Qdrant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nối đường ghi Qdrant còn thiếu trong `modules/kb`, và thêm chặng làm giàu nội dung (caption ảnh · mô tả video · bóc chữ tệp) mà người dùng duyệt được trước khi nội dung tới tay agent.

**Architecture:** Hai chặng tách rời. Chặng `kb_enrich` chạy tự động sau upload, ghi vào đúng cột người dùng sửa (`media.caption`, `documents.body`) — Aurora là nguồn sự thật. Chặng `kb_index` chạy khi người dùng bấm "Đồng bộ tri thức", đọc dữ liệu đã duyệt rồi chunk → embed → Qdrant. Interface `IndexClient` giữ nguyên; chỉ thay cài đặt đứng sau nó, nên `service.py` không đổi một dòng.

**Tech Stack:** Python 3.13 · asyncpg thô · httpx.AsyncClient · Docling (torch bản CPU) · AsyncQdrantClient · DashScope qwen-vl-max · Gemini 2.5 Flash · pytest + testcontainers

> ⚠️ **Đính chính sau Task 1 (2026-08-10), áp cho mọi task còn lại.** Task 1 và §5.3 của
> spec từng khẳng định bộ extras Docling tối thiểu tránh được torch. **Sai, đã kiểm chứng
> bằng thực nghiệm:** `docling.document_converter` import `StandardPdfPipeline` ở top-level
> bất kể định dạng tệp, pipeline đó import `docling_ibm_models`, và gói ấy khai
> `torch`/`torchvision`/`accelerate` là **core deps** chứ không phải extra. Không tổ hợp
> extras nào tránh được, kể cả khi chỉ bóc DOCX.
>
> Chủ dự án đã chốt: **chấp nhận torch, pin `[[tool.uv.index]] pytorch-cpu`** để không kéo
> chuỗi `nvidia-*` (~2.5 GB) vào một image chạy CPU thuần. Hệ quả: Docling **có** layout
> model, nên nhánh rơi sang VLM ở Task 8 chỉ còn dành cho PDF thật sự không có lớp chữ —
> không còn là cách bù cho việc thiếu model. Mọi câu trong plan này viết "không kéo torch"
> đọc theo đính chính này.

Spec: [docs/superpowers/specs/2026-08-10-ingest-qdrant-design.md](../specs/2026-08-10-ingest-qdrant-design.md)

## Global Constraints

- **Bốn luật của repo áp cho mọi task.** (1) Truy vấn `tenant_data` đi qua `tenant_conn()` trong một giao dịch, và **mọi câu phải tự mang vị từ `tenant_id = portal.current_tenant()`** — RLS đã dỡ ở `0909`. (2) Bảng mới trong `tenant_data` gọi `control.enforce_tenant_isolation()` — task này không tạo bảng nào. (3) Module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`. (4) Mọi endpoint khai `action` qua `require(action)`.
- **Không migration nào.** Không thêm cột, không thêm bảng.
- **Không đổi `core/auth/actions.py`** — dùng lại `CATALOG_READ`/`CATALOG_WRITE`, nên không phải chạy `make contracts`.
- **Không đổi hình dạng collection Qdrant** — `_documents`: dense 1024 Cosine + sparse `bm25` IDF; `_media`: `text` 1024 + `visual` 768. Không đổi tên khoá payload, kể cả `project_id`.
- **Định danh tiếng Anh; comment và tên test tiếng Việt.**
- **Không có lệnh blocking trong coroutine.** Docling, `pypdfium2` render, `sha256` trên tệp lớn → `asyncio.to_thread`. Qdrant → `AsyncQdrantClient`, không `QdrantClient`.
- **Chạy MỘT worker.** Ràng buộc vận hành, xem spec §14.
- Chạy test: `make test-module M=kb` hoặc `uv run pytest <path> -v`. Trước khi mở MR: `make check`.

---

## Cấu trúc tệp

| Tệp | Trách nhiệm |
|---|---|
`kb/prompts.yaml` | 🆕 Prompt + tham số model cho 4 profile |
`kb/prompts.py` | 🆕 Loader `importlib.resources` + `validate()` |
`kb/index/chunker.py` | 🆕 4 strategy text → list chunk. Hàm thuần, không I/O |
`kb/index/store.py` | 🆕 `AsyncQdrantClient`: upsert · delete · scroll · collection |
`kb/clients/embed.py` | 🆕 Gọi `EMBED_SERVICE_URL`, 4 kind, `Semaphore(4)` |
`kb/clients/vlm.py` | 🆕 DashScope: caption ảnh · OCR trang PDF scan |
`kb/clients/video.py` | 🆕 Gemini: mô tả video, chuẩn hoá URL YouTube |
`kb/clients/extract.py` | 🆕 Docling → Markdown, trong `to_thread`; rỗng thì gọi VLM |
`kb/clients/base.py` | ✏️ Thay 5 `NotImplementedError` bằng cài đặt thật |
`kb/clients/rag.py` · `media.py` | ✏️ Ráp embedder + store thành `IndexClient` |
`kb/jobs.py` | ✏️ + 4 handler mới, `dependencies()` nối dây thật |
`kb/ops/sync.py` | 🆕 Cascade theo `project_code` |
`kb/state/repo.py` | ✏️ Thêm nhánh `force` cho `cache_caption`/`cache_extracted_text` |
`kb/contracts.py` | ✏️ + `KIND_ENRICH` |
`kb/settings.py` | ✏️ + `OCR_MAX_PAGES`, endpoint DashScope/Gemini |
`kb/directive/verticals/profiles.py` | ✏️ `PROFILE_NAMES` đọc từ `prompts.yaml` |
`kb/__init__.py` | ✏️ Viết lại tuyên bố đã hết đúng |
`modules/realestate/router.py` | ✏️ + 4 endpoint, enqueue `kb_enrich` |
`pyproject.toml` | ✏️ + docling-slim · pyyaml · httpx; − pypdf |

**Ngoài phạm vi plan này:** frontend (repo `odyssey-portal-frontend`) — ô trạng thái "Đang tạo mô tả…", nút "Tạo lại mô tả", chỉ báo đồng bộ + nút "Đồng bộ tri thức". Repo riêng, plan riêng. Backend expose đủ endpoint sau Task 11.

---

### Task 1: Dependency và kiểm chứng Docling

Spec §15 ghi rõ: bộ extras dựng từ metadata PyPI, **chưa cài thử**. Task này biến giả định đó thành sự thật đo được, trước khi bất kỳ task nào phụ thuộc vào nó.

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/unit/test_docling_kha_dung.py`
- Fixture: `tests/fixtures/` (dùng `scripts/gen_fixtures.py` đã có)

**Interfaces:**
- Produces: gói `docling` import được; `pyyaml`, `httpx` có trong dependencies production.

- [ ] **Step 1: Thêm dependency vào `pyproject.toml`**

Trong `[project].dependencies`, xoá dòng `"pypdf>=5.1",` và thêm:

```toml
    # Bóc chữ tệp → Markdown có cấu trúc, khớp chunk="structured_md" của documents.
    # BỘ EXTRAS TỐI THIỂU, CỐ Ý: gói `docling` trần là `docling-slim[standard]` và kéo
    # theo torch · torchvision · accelerate · docling-ibm-models (~2–3 GB). API và worker
    # dùng CHUNG một image (docker-compose.dev.yml, "một image hai vai"), nên torch sẽ
    # phình cả image của API — nơi không bao giờ bóc một tệp nào.
    # Đổi lại: không có layout model, PDF nhiều cột ra Markdown kém hơn. PDF không có
    # lớp chữ thì đẩy sang VLM (clients/extract.py), không thêm onnxruntime/rapidocr.
    "docling-slim[convert-core,format-pdf-pypdfium2,format-docx,format-xlsx,feat-chunking]>=2.119",
    # prompts.yaml. KHÔNG dựa vào dep bắc cầu của nhóm dev: `uv sync --no-dev` cho image
    # production sẽ thiếu, và vì loader chạy lúc import module thì app KHÔNG khởi động
    # được — không phải hỏng một endpoint. Đúng cách `minio` từng hỏng.
    "pyyaml>=6.0",
    # Đường ra duy nhất của repo: embed service, DashScope, Gemini. Trước bản này httpx
    # chỉ có ở nhóm dev, nên clients/base.py phải để NotImplementedError("cần dep httpx").
    "httpx>=0.28",
```

- [ ] **Step 2: Đồng bộ môi trường**

Run: `uv sync`
Expected: cài xong, không lỗi resolve. Ghi lại kích thước: `du -sh .venv`

- [ ] **Step 3: Viết test kiểm chứng — chạy Docling trên PDF thật**

Create `tests/unit/test_docling_kha_dung.py`:

```python
"""Cổng dependency: Docling bộ extras tối thiểu có bóc được PDF không.

Spec §15 ghi bộ extras dựng từ metadata PyPI chứ chưa cài thử. Test này là chỗ
giả định đó thành sự thật đo được — nếu pipeline đòi thêm gói, nó đỏ ở đây chứ
không đỏ lúc worker chạy job đầu tiên trên production.
"""

from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tai_lieu_mau.pdf"


def test_docling_import_duoc():
    from docling.document_converter import DocumentConverter

    assert DocumentConverter is not None


def test_docling_khong_keo_torch():
    """torch trong image nghĩa là bộ extras đã sai — xem comment ở pyproject.toml."""
    import importlib.util

    assert importlib.util.find_spec("torch") is None


@pytest.mark.skipif(not FIXTURE.exists(), reason="chưa sinh fixture: uv run python scripts/gen_fixtures.py")
def test_docling_boc_duoc_pdf_co_lop_chu():
    from docling.document_converter import DocumentConverter

    doc = DocumentConverter().convert(str(FIXTURE)).document
    md = doc.export_to_markdown()
    assert md.strip(), "Docling trả rỗng cho PDF có lớp chữ"
```

- [ ] **Step 4: Sinh fixture và chạy test**

Run:
```bash
uv run python scripts/gen_fixtures.py
uv run pytest tests/unit/test_docling_kha_dung.py -v
```
Expected: 3 PASS.

**Nếu `test_docling_boc_duoc_pdf_co_lop_chu` đỏ vì thiếu gói:** đọc thông điệp lỗi, thêm đúng extra còn thiếu vào `pyproject.toml`, ghi lý do vào comment cạnh nó, chạy lại. **Không** rơi về `docling` trần — nó kéo torch.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/unit/test_docling_kha_dung.py
git commit -m "build(kb): docling-slim không torch, pyyaml, httpx production; gỡ pypdf"
```

---

### Task 2: `prompts.yaml` và loader

**Files:**
- Create: `src/portal/modules/kb/prompts.yaml`
- Create: `src/portal/modules/kb/prompts.py`
- Modify: `src/portal/modules/kb/directive/verticals/profiles.py`
- Test: `tests/modules/kb/test_prompts.py`

**Interfaces:**
- Produces:
  - `prompts.load() -> dict[str, PromptSpec]` — nạp một lần, cache module-level
  - `PromptSpec` dataclass: `name: str`, `model: str`, `prompt: str`, `max_tokens: int`, `temperature: float`
  - `prompts.get(name: str) -> PromptSpec` — raise `KeyError` nếu không có
  - `profiles.PROFILE_NAMES: frozenset[str]` — đọc từ YAML, không còn hằng chép tay

- [ ] **Step 1: Viết test cổng trước**

Create `tests/modules/kb/test_prompts.py`:

```python
"""Cổng prompt: vertical tham chiếu profile nào thì profile đó phải có thật.

Gõ sai tên profile phải đỏ ở CI, không phải lúc worker gọi VLM lần đầu trên production.
"""

import pytest

from portal.modules.kb import prompts
from portal.modules.kb.directive.verticals import profiles
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE


def test_nap_duoc_tu_wheel():
    """Đọc bằng importlib.resources — Path(__file__).parent gãy khi chạy từ wheel."""
    assert prompts.load(), "prompts.yaml rỗng hoặc không nạp được"


def test_moi_profile_co_du_truong():
    for spec in prompts.load().values():
        assert spec.model, f"{spec.name} thiếu model"
        assert spec.max_tokens > 0, f"{spec.name} max_tokens phải dương"


def test_bon_profile_bat_buoc_ton_tai():
    ten = set(prompts.load())
    assert {"caption_full", "caption_subject", "video_describe", "ocr_markdown"} <= ten


def test_vertical_khong_tham_chieu_profile_ma():
    """PROFILE_NAMES nay đọc từ prompts.yaml, nên đây là phép so thật chứ không phải
    so với một danh sách chép tay ở file khác."""
    assert profiles.validate(REAL_ESTATE) == []


def test_profile_khong_ton_tai_thi_bao_loi():
    with pytest.raises(KeyError):
        prompts.get("khong_he_ton_tai")
```

- [ ] **Step 2: Chạy để thấy nó đỏ**

Run: `uv run pytest tests/modules/kb/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.kb.prompts'`

- [ ] **Step 3: Viết `prompts.yaml`**

Create `src/portal/modules/kb/prompts.yaml`:

```yaml
# Prompt của Portal. TRƯỚC BẢN NÀY chúng thuộc santa-models và Portal chỉ giữ TÊN
# profile — xem docstring cũ của directive/verticals/profiles.py. Portal nay tự chạy
# VLM nên quyền sở hữu prompt chuyển về đây.
#
# Thêm profile: thêm một khoá ở đây rồi tham chiếu từ verticals/*.py. Cổng
# tests/modules/kb/test_prompts.py bắt tên gõ sai.

caption_full:
  model: qwen-vl-max
  max_tokens: 300
  temperature: 0.2
  prompt: |
    Mô tả bức ảnh bất động sản này bằng tiếng Việt, trong 2-4 câu.
    Nêu: loại công trình, bố cục tổng thể, cảnh quan xung quanh, và mọi chữ đọc được trên ảnh.
    Chỉ mô tả thứ nhìn thấy được. Không suy đoán tên dự án, giá, hay vị trí nếu ảnh không ghi.
    Không mở đầu bằng "Bức ảnh này" hay "Hình ảnh cho thấy".

caption_subject:
  model: qwen-vl-max
  max_tokens: 250
  temperature: 0.2
  prompt: |
    Mô tả bằng tiếng Việt CHỦ THỂ CHÍNH của ảnh bất động sản này, trong 2-3 câu.
    Đây là ảnh sơ đồ, bản đồ vị trí, hoặc ảnh tiến độ — hãy đọc và thuật lại thông tin
    trên đó: nhãn, số hiệu, chú thích, mốc thời gian, hướng, tỷ lệ.
    Bỏ qua phần trang trí và nền không mang thông tin.
    Không mở đầu bằng "Bức ảnh này" hay "Hình ảnh cho thấy".

video_describe:
  model: gemini-2.5-flash
  max_tokens: 500
  temperature: 0.2
  prompt: |
    Mô tả nội dung video bất động sản này bằng tiếng Việt, trong 3-6 câu.
    Nêu: công trình hoặc khu vực được quay, trạng thái xây dựng nếu thấy được,
    và mọi chữ hoặc lời thuyết minh mang thông tin (tên phân khu, mốc tiến độ, tiện ích).
    Chỉ mô tả thứ có trong video.

ocr_markdown:
  model: qwen-vl-max
  max_tokens: 2000
  temperature: 0.0
  prompt: |
    Đọc toàn bộ chữ trong trang tài liệu này và trả về dưới dạng Markdown.
    Giữ đúng cấu trúc: tiêu đề thành heading, bảng thành bảng Markdown, danh sách thành list.
    Giữ nguyên số liệu và dấu tiếng Việt. Không tóm tắt, không thêm lời bình.
    Nếu trang trống hoặc không có chữ, trả về chuỗi rỗng.
```

- [ ] **Step 4: Viết loader**

Create `src/portal/modules/kb/prompts.py`:

```python
"""Nạp prompts.yaml. Một lần, cache module-level.

`importlib.resources` chứ không `Path(__file__).parent`: đường thứ hai gãy khi chạy
từ wheel — tức ở production, không phải ở máy người viết.
"""

from dataclasses import dataclass
from functools import cache

import yaml


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: str
    model: str
    prompt: str
    max_tokens: int
    temperature: float


@cache
def load() -> dict[str, PromptSpec]:
    from importlib.resources import files

    raw = yaml.safe_load(files("portal.modules.kb").joinpath("prompts.yaml").read_text(encoding="utf-8"))
    return {
        name: PromptSpec(
            name=name,
            model=str(cfg["model"]),
            prompt=str(cfg.get("prompt", "")),
            max_tokens=int(cfg.get("max_tokens", 300)),
            temperature=float(cfg.get("temperature", 0.2)),
        )
        for name, cfg in (raw or {}).items()
    }


def get(name: str) -> PromptSpec:
    """KeyError chứ không rơi về mặc định: một profile gõ sai rơi về `caption_full`
    nghĩa là ảnh sơ đồ được mô tả bằng prompt của ảnh phối cảnh, và không ai thấy."""
    try:
        return load()[name]
    except KeyError:
        raise KeyError(f"profile {name!r} không có trong prompts.yaml — có: {sorted(load())}") from None
```

- [ ] **Step 5: Sửa `profiles.py` đọc từ YAML**

Modify `src/portal/modules/kb/directive/verticals/profiles.py` — thay toàn bộ nội dung:

```python
"""Đối chiếu profile mà vertical tham chiếu với prompts.yaml của Portal.

TRƯỚC 2026-08-10 file này giữ một danh sách chép tay "bốn profile santa-models cài",
và docstring ghi "prompt do service own". Cả hai hết đúng: Portal tự chạy VLM nên
prompt về đây, và `PROFILE_NAMES` nay ĐỌC TỪ prompts.yaml — hết một bản sao phải
đồng bộ tay.
"""

from portal.modules.kb import prompts
from portal.modules.kb.contracts import VerticalSpec

DEFAULT_CAPTION = "caption_full"


def profile_names() -> frozenset[str]:
    return frozenset(prompts.load())


# Giữ tên cũ cho chỗ đang import. Gọi hàm chứ không đóng băng lúc import: prompts.load()
# đã cache, và một hằng đóng băng ở đây làm test không thay được nội dung YAML.
PROFILE_NAMES = profile_names()


def validate(vertical: VerticalSpec) -> list[str]:
    """Trả danh sách profile được tham chiếu nhưng không tồn tại."""
    referenced = set(vertical.caption_profiles.values()) | set(vertical.document_extract.values())
    return sorted(referenced - profile_names())
```

- [ ] **Step 6: Sửa `document_extract` — `pdf2text` không còn là profile**

Modify `src/portal/modules/kb/directive/verticals/real_estate.py`, dòng cuối:

```python
    # Docling bóc chữ cục bộ (clients/extract.py), không còn là profile của service nào.
    # Chỉ `ocr_markdown` còn là profile VLM — dùng cho PDF không có lớp chữ.
    document_extract={"pdf_scan": "ocr_markdown"},
```

- [ ] **Step 7: Chạy test**

Run: `uv run pytest tests/modules/kb/test_prompts.py tests/modules/kb/test_schema_contract.py -v`
Expected: tất cả PASS.

Nếu `test_schema_contract.py` đỏ vì `extract_profile` đọc khoá `pdf_text`: sửa `directive/profiles.py::extract_profile` trả `vertical.document_extract.get("pdf_scan")` và cập nhật docstring của nó — Docling xử lý nhánh có lớp chữ, VLM chỉ nhận nhánh scan.

- [ ] **Step 8: Commit**

```bash
git add src/portal/modules/kb/prompts.yaml src/portal/modules/kb/prompts.py \
        src/portal/modules/kb/directive/verticals/ tests/modules/kb/test_prompts.py
git commit -m "feat(kb): prompts.yaml — prompt về Portal sở hữu, PROFILE_NAMES đọc từ YAML"
```

---

### Task 3: `chunker.py` — 4 strategy

**Files:**
- Create: `src/portal/modules/kb/index/__init__.py`
- Create: `src/portal/modules/kb/index/chunker.py`
- Test: `tests/modules/kb/test_chunker.py`

**Interfaces:**
- Consumes: `contracts.ChunkSpec(strategy, max_chars, overlap)`
- Produces: `chunker.split(text: str, spec: ChunkSpec) -> list[str]` — luôn trả list; text rỗng trả `[]`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_chunker.py`:

```python
"""Chunker là hàm thuần — test không cần Docker, không cần DB.

Biên quan trọng hơn đường thường: `overlap >= max_chars` là vòng lặp vô hạn nếu
cài ẩu, và text rỗng phải trả [] chứ không phải [''] (một chunk rỗng vẫn tốn một
lần embed và một point).
"""

import pytest

from portal.modules.kb.contracts import ChunkSpec
from portal.modules.kb.index import chunker


def test_text_rong_tra_list_rong():
    assert chunker.split("", ChunkSpec(strategy="markdown")) == []
    assert chunker.split("   \n  ", ChunkSpec(strategy="markdown")) == []


def test_facts_gop_thanh_mot_chunk():
    """`facts` dùng cho quick-fact của projects: 9 trường ngắn, tách ra là mất ngữ cảnh."""
    text = "Khu vực: Long Biên\nChủ đầu tư: Noble\nDiện tích: 12000"
    assert chunker.split(text, ChunkSpec(strategy="facts")) == [text]


def test_atomic_mot_ban_ghi_mot_chunk():
    text = "Hỏi: Bao giờ bàn giao?\nĐáp: Quý 4/2026."
    assert chunker.split(text, ChunkSpec(strategy="atomic")) == [text]


def test_markdown_cat_theo_max_chars():
    text = "a" * 2000
    ra = chunker.split(text, ChunkSpec(strategy="markdown", max_chars=800, overlap=150))
    assert len(ra) > 1
    assert all(len(c) <= 800 for c in ra)


def test_markdown_co_overlap_that():
    text = "".join(f"câu số {i}. " for i in range(300))
    ra = chunker.split(text, ChunkSpec(strategy="markdown", max_chars=400, overlap=100))
    assert ra[0][-50:] in ra[1], "chunk sau không mang đuôi của chunk trước"


def test_structured_md_khong_cat_giua_bang():
    """Docling xuất bảng Markdown; cắt giữa bảng làm nửa dưới mất hàng tiêu đề."""
    bang = "| Đợt | % |\n| --- | --- |\n" + "".join(f"| {i} | 10 |\n" for i in range(40))
    ra = chunker.split(f"## Tiến độ\n{bang}", ChunkSpec(strategy="structured_md", max_chars=300))
    co_bang = [c for c in ra if "| ---" in c or "| Đợt" in c]
    assert len(co_bang) == 1, "bảng bị cắt thành nhiều chunk"


def test_overlap_lon_hon_max_chars_khong_treo():
    """Cấu hình sai không được thành vòng lặp vô hạn — nó phải kết thúc, kể cả xấu."""
    ra = chunker.split("x" * 1000, ChunkSpec(strategy="markdown", max_chars=100, overlap=500))
    assert 0 < len(ra) < 100


def test_strategy_la_bao_loi():
    with pytest.raises(ValueError, match="chunk strategy"):
        chunker.split("abc", ChunkSpec(strategy="khong_ton_tai"))
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.kb.index`

- [ ] **Step 3: Cài đặt**

Create `src/portal/modules/kb/index/__init__.py`:

```python
"""Chunk và ghi Qdrant — phần trước đây thuộc rag_service."""
```

Create `src/portal/modules/kb/index/chunker.py`:

```python
"""Text → list chunk. Hàm thuần: không I/O, không DB, không mạng.

Bốn strategy khai trong verticals/*.py. Thêm strategy = thêm một nhánh ở đây và một
test biên — đừng để `_markdown` thành cái sọt cho mọi thứ chưa phân loại.
"""

import re

from portal.modules.kb.contracts import ChunkSpec

# Hàng bảng Markdown: `| ... |`. Bảng bị cắt đôi làm nửa dưới mất hàng tiêu đề, nên
# `structured_md` giữ nguyên khối bảng dù nó vượt max_chars.
_HANG_BANG = re.compile(r"^\s*\|.*\|\s*$")


def split(text: str, spec: ChunkSpec) -> list[str]:
    if not text.strip():
        return []
    if spec.strategy in ("facts", "atomic", "per_row"):
        return [text]
    if spec.strategy == "markdown":
        return _cat_theo_do_dai(text, spec)
    if spec.strategy == "structured_md":
        return _cat_giu_khoi(text, spec)
    raise ValueError(f"chunk strategy không hỗ trợ: {spec.strategy!r}")


def _buoc(spec: ChunkSpec) -> int:
    """Bước tiến mỗi vòng. Overlap >= max_chars là cấu hình sai; ép bước >= 1 để nó
    kết thúc xấu thay vì treo worker."""
    return max(1, spec.max_chars - spec.overlap)


def _cat_theo_do_dai(text: str, spec: ChunkSpec) -> list[str]:
    ra: list[str] = []
    i, buoc = 0, _buoc(spec)
    while i < len(text):
        ra.append(text[i : i + spec.max_chars])
        i += buoc
    return ra


def _cat_giu_khoi(text: str, spec: ChunkSpec) -> list[str]:
    """Gom theo khối: bảng Markdown liền mạch là một khối không cắt được."""
    khoi: list[str] = []
    dem: list[str] = []
    trong_bang = False
    for dong in text.splitlines():
        la_bang = bool(_HANG_BANG.match(dong))
        if la_bang != trong_bang and dem:
            khoi.append("\n".join(dem))
            dem = []
        trong_bang = la_bang
        dem.append(dong)
    if dem:
        khoi.append("\n".join(dem))

    ra: list[str] = []
    hien_tai = ""
    for k in khoi:
        if _HANG_BANG.search(k):
            if hien_tai:
                ra.append(hien_tai)
                hien_tai = ""
            ra.append(k)
        elif len(hien_tai) + len(k) + 1 <= spec.max_chars:
            hien_tai = f"{hien_tai}\n{k}" if hien_tai else k
        else:
            if hien_tai:
                ra.append(hien_tai)
            hien_tai = ""
            ra.extend(_cat_theo_do_dai(k, spec))
    if hien_tai:
        ra.append(hien_tai)
    return [c for c in ra if c.strip()]
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_chunker.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/index/ tests/modules/kb/test_chunker.py
git commit -m "feat(kb): chunker 4 strategy, structured_md giữ nguyên khối bảng"
```

---

### Task 4: `clients/embed.py`

**Files:**
- Create: `src/portal/modules/kb/clients/embed.py`
- Modify: `src/portal/modules/kb/settings.py`
- Test: `tests/modules/kb/test_embed_client.py`

**Interfaces:**
- Produces:
  - `EmbedClient(base_url: str, token: str)`
  - `async dense(texts: list[str]) -> list[list[float]]` — 1024 chiều, `side="passage"`
  - `async sparse(texts: list[str]) -> list[dict]` — `{"indices": [...], "values": [...]}`
  - `async visual_image(urls: list[str]) -> list[list[float]]` — 768 chiều

- [ ] **Step 1: Thêm hằng vào `settings.py`**

Modify `src/portal/modules/kb/settings.py`, sau khối `# ─── santa-models ───`:

```python
# Đường ra DUY NHẤT của repo. `/embed` nhận {side, texts[], images[], kind}; `side` là
# "passage" khi index và "query" khi tìm — e5 huấn luyện với hai prefix khác nhau, dùng
# nhầm làm điểm cosine lệch mà không có lỗi nào.
PATH_EMBED = "/embed"
SIDE_PASSAGE = "passage"

KIND_DENSE = "dense"
KIND_SPARSE = "sparse"
KIND_VISUAL_IMAGE = "visual_image"

# Trần số trang PDF scan gửi VLM. Một PDF 300 trang không được thành 300 lời gọi API.
# ⚠️ CON SỐ TẠM: chưa có tài liệu scan nào trong dữ liệu thật để đo phân bố số trang.
OCR_MAX_PAGES = 20
```

Trong `class KbEnv`, thêm:

```python
    # DashScope (caption ảnh, OCR trang) và Gemini (mô tả video). Rỗng = client raise
    # lúc dựng, không gửi request không auth.
    vlm_api_key: str = ""
    vlm_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    gemini_api_key: str = ""
```

- [ ] **Step 2: Viết test trước**

Create `tests/modules/kb/test_embed_client.py`:

```python
"""Client embed — MockTransport, không gọi mạng thật trong CI.

Hai thứ được canh ở đây vì sai chúng thì không có lỗi nào, chỉ có kết quả tìm kiếm tệ:
`side="passage"` khi index, và bearer token có mặt.
"""

import httpx
import pytest

from portal.modules.kb.clients.embed import EmbedClient


def _client(handler) -> EmbedClient:
    c = EmbedClient(base_url="https://embed.test", token="tok")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


async def test_dense_gui_side_passage_va_token():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        ghi["body"] = json.loads(req.content)
        ghi["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"embeddings": [[0.1] * 1024]})

    ra = await _client(handler).dense(["xin chào"])
    assert ghi["body"]["side"] == "passage"
    assert ghi["body"]["kind"] == "dense"
    assert ghi["auth"] == "Bearer tok"
    assert len(ra[0]) == 1024


async def test_sparse_tra_indices_va_values():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"indices": [3, 9], "values": [0.5, 0.2]}]})

    ra = await _client(handler).sparse(["căn hộ 2 phòng ngủ"])
    assert ra[0]["indices"] == [3, 9]


async def test_visual_image_gui_images_khong_gui_texts():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        ghi["body"] = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[0.2] * 768]})

    ra = await _client(handler).visual_image(["https://cdn.test/a.jpg"])
    assert ghi["body"]["images"] == ["https://cdn.test/a.jpg"]
    assert ghi["body"].get("texts") in (None, [])
    assert len(ra[0]) == 768


async def test_token_rong_thi_raise_ngay_luc_dung():
    """Fail-closed: gửi request không auth chỉ để nhận 401 là tốn một vòng mạng và
    một dòng log khó đọc."""
    with pytest.raises(ValueError, match="KB_SANTA_MODELS_TOKEN"):
        EmbedClient(base_url="https://embed.test", token="")


async def test_danh_sach_rong_khong_goi_mang():
    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng cho danh sách rỗng")

    assert await _client(handler).dense([]) == []
```

- [ ] **Step 3: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_embed_client.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.kb.clients.embed`

- [ ] **Step 4: Cài đặt**

Create `src/portal/modules/kb/clients/embed.py`:

```python
"""Gọi embed service — đường ra DUY NHẤT của repo này.

Semaphore chứ không đẩy hết một lúc: service chạy trên `device: cpu` (kiểm qua
/health), nên 100 request song song chỉ làm nó xếp hàng, không nhanh hơn.
"""

import asyncio
from typing import Any

import httpx

from portal.modules.kb import settings


class EmbedClient:
    def __init__(self, *, base_url: str, token: str) -> None:
        if not token:
            raise ValueError("thiếu KB_SANTA_MODELS_TOKEN — embed service từ chối request không auth")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)
        self._gate = asyncio.Semaphore(settings.WORKER_CONCURRENCY)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _goi(self, *, kind: str, texts: list[str] | None = None, images: list[str] | None = None) -> list[Any]:
        if not (texts or images):
            return []
        body: dict[str, Any] = {"side": settings.SIDE_PASSAGE, "kind": kind}
        if texts:
            body["texts"] = texts
        if images:
            body["images"] = images
        async with self._gate:
            r = await self._http.post(
                f"{self.base_url}{settings.PATH_EMBED}",
                json=body,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        r.raise_for_status()
        data = r.json()
        return data["embeddings"] if isinstance(data, dict) else data

    async def dense(self, texts: list[str]) -> list[list[float]]:
        return await self._goi(kind=settings.KIND_DENSE, texts=texts)

    async def sparse(self, texts: list[str]) -> list[dict]:
        return await self._goi(kind=settings.KIND_SPARSE, texts=texts)

    async def visual_image(self, urls: list[str]) -> list[list[float]]:
        return await self._goi(kind=settings.KIND_VISUAL_IMAGE, images=urls)
```

- [ ] **Step 5: Chạy test**

Run: `uv run pytest tests/modules/kb/test_embed_client.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/clients/embed.py src/portal/modules/kb/settings.py \
        tests/modules/kb/test_embed_client.py
git commit -m "feat(kb): client embed service — dense/sparse/visual, semaphore theo WORKER_CONCURRENCY"
```

---

### Task 5: `index/store.py` — ghi Qdrant

**Files:**
- Create: `src/portal/modules/kb/index/store.py`
- Test: `tests/modules/kb/test_store_qdrant.py`

**Interfaces:**
- Produces:
  - `QdrantStore(url: str, api_key: str = "")`
  - `async ensure_collection(name: str, *, media: bool) -> None` — `media=True` dựng `text`+`visual`; `False` dựng `dense`+sparse `bm25`
  - `async upsert(name: str, points: list[PointIn]) -> int`
  - `async delete_by_record(name: str, *, record_id: int, doc_type: str) -> int`
  - `async scroll_points(name: str, *, anchor_code: str) -> list[IndexPoint]`
  - `async drop_collection(name: str) -> None`
  - `async count(name: str) -> int` · `async payload_of(name: str, *, point_id: str) -> dict` · `async describe(name: str) -> dict`
  - `PointIn` dataclass: `point_id: str`, `vectors: dict[str, Any]`, `payload: dict`
  - `point_id_of(doc_type: str, record_id: int, idx: int) -> str` — `uuid5` theo đúng quy ước cũ

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_store_qdrant.py`:

```python
"""Ghi Qdrant thật bằng testcontainers.

Hình dạng collection là hợp đồng với repo agent: dense 1024 + sparse bm25 cho
_documents, text 1024 + visual 768 cho _media. Test này là chỗ DUY NHẤT ở repo
backend bắt được một lần đổi số chiều.
"""

import pytest

from portal.modules.kb.index.store import PointIn, QdrantStore, point_id_of


@pytest.fixture
async def store(qdrant_url):
    s = QdrantStore(url=qdrant_url)
    yield s
    await s.aclose()


def test_point_id_on_dinh_va_khac_nhau_theo_doc_type():
    """point-id = uuid5(doc_type:record_id:idx) — đổi loại tài liệu sinh point MỚI."""
    a = point_id_of("csbh", 12, 0)
    assert a == point_id_of("csbh", 12, 0)
    assert a != point_id_of("phap_ly", 12, 0)
    assert a != point_id_of("csbh", 12, 1)


async def test_dung_collection_documents_dung_hinh_dang(store):
    await store.ensure_collection("t_documents", media=False)
    info = await store.describe("t_documents")
    assert info["dense"] == 1024
    assert "bm25" in info["sparse"]


async def test_dung_collection_media_dung_hinh_dang(store):
    await store.ensure_collection("t_media", media=True)
    info = await store.describe("t_media")
    assert info["text"] == 1024
    assert info["visual"] == 768


async def test_ensure_collection_goi_hai_lan_khong_hong(store):
    """Job retry gọi lại — lần hai không được xoá dữ liệu lần một."""
    await store.ensure_collection("t_idem", media=False)
    await store.upsert("t_idem", [PointIn(point_id_of("tai_lieu", 1, 0), {"dense": [0.1] * 1024}, {"record_id": 1})])
    await store.ensure_collection("t_idem", media=False)
    assert await store.count("t_idem") == 1


async def test_upsert_cung_point_id_ghi_de_khong_nhan_doi(store):
    await store.ensure_collection("t_up", media=False)
    pid = point_id_of("tai_lieu", 7, 0)
    await store.upsert("t_up", [PointIn(pid, {"dense": [0.1] * 1024}, {"record_id": 7, "caption": "cũ"})])
    await store.upsert("t_up", [PointIn(pid, {"dense": [0.2] * 1024}, {"record_id": 7, "caption": "mới"})])
    assert await store.count("t_up") == 1


async def test_delete_by_record_chi_xoa_dung_doc_type(store):
    await store.ensure_collection("t_del", media=False)
    await store.upsert(
        "t_del",
        [
            PointIn(point_id_of("csbh", 5, 0), {"dense": [0.1] * 1024}, {"record_id": 5, "doc_type": "csbh"}),
            PointIn(point_id_of("phap_ly", 5, 0), {"dense": [0.1] * 1024}, {"record_id": 5, "doc_type": "phap_ly"}),
        ],
    )
    await store.delete_by_record("t_del", record_id=5, doc_type="csbh")
    assert await store.count("t_del") == 1


async def test_scroll_tra_record_id_va_content_hash(store):
    await store.ensure_collection("t_sc", media=False)
    await store.upsert(
        "t_sc",
        [
            PointIn(
                point_id_of("tai_lieu", 9, 0),
                {"dense": [0.1] * 1024},
                {"record_id": 9, "anchor_code": "nplb", "content_hash": "abc"},
            )
        ],
    )
    pts = await store.scroll_points("t_sc", anchor_code="nplb")
    assert [(p.record_id, p.content_hash) for p in pts] == [(9, "abc")]
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_store_qdrant.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.kb.index.store`

- [ ] **Step 3: Cài đặt**

Create `src/portal/modules/kb/index/store.py`:

```python
"""Adapter Qdrant. AsyncQdrantClient — bản đồng bộ nuốt event loop của worker.

Hình dạng collection là HỢP ĐỒNG với repo agent: 8 collection đang sống trên EC2 có
đúng hình dạng dưới đây và agent đang query chúng. Đổi số chiều hay tên vector là
breaking change mà không test nào ở repo agent bắt được.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from portal.modules.kb.contracts import IndexPoint

DENSE_SIZE = 1024
VISUAL_SIZE = 768
SPARSE_NAME = "bm25"

# Namespace cố định: point-id phải ổn định giữa các lần chạy và giữa các tiến trình,
# nếu không mỗi lần index sinh point mới và point cũ ở lại vĩnh viễn.
_NS = uuid.NAMESPACE_URL


@dataclass(frozen=True, slots=True)
class PointIn:
    point_id: str
    vectors: dict[str, Any]
    payload: dict


def point_id_of(doc_type: str, record_id: int, idx: int) -> str:
    """`uuid5(doc_type:record_id:idx)` — quy ước đã dùng cho 381 point đang sống.

    KHÔNG chứa tên bảng, nên miền giá trị doc_type phải đóng: một `tong_quan` từ
    documents sẽ ghi đè point của projects. Xem contracts.TITLE_PREFIXES.
    """
    return str(uuid.uuid5(_NS, f"{doc_type}:{record_id}:{idx}"))


class QdrantStore:
    def __init__(self, *, url: str, api_key: str = "") -> None:
        self._c = AsyncQdrantClient(url=url, api_key=api_key or None)

    async def aclose(self) -> None:
        await self._c.close()

    async def ensure_collection(self, name: str, *, media: bool) -> None:
        """Idempotent: job retry gọi lại, lần hai không được xoá dữ liệu lần một."""
        if await self._c.collection_exists(name):
            return
        if media:
            vectors = {
                "text": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE),
                "visual": models.VectorParams(size=VISUAL_SIZE, distance=models.Distance.COSINE),
            }
            sparse = None
        else:
            vectors = {"dense": models.VectorParams(size=DENSE_SIZE, distance=models.Distance.COSINE)}
            sparse = {SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)}
        await self._c.create_collection(name, vectors_config=vectors, sparse_vectors_config=sparse)

    async def drop_collection(self, name: str) -> None:
        await self._c.delete_collection(name)

    async def upsert(self, name: str, points: list[PointIn]) -> int:
        if not points:
            return 0
        await self._c.upsert(
            name,
            points=[models.PointStruct(id=p.point_id, vector=p.vectors, payload=p.payload) for p in points],
            wait=True,
        )
        return len(points)

    async def delete_by_record(self, name: str, *, record_id: int, doc_type: str) -> int:
        must = [models.FieldCondition(key="record_id", match=models.MatchValue(value=record_id))]
        if doc_type:
            must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type)))
        await self._c.delete(name, points_selector=models.Filter(must=must), wait=True)
        return 1

    async def scroll_points(self, name: str, *, anchor_code: str) -> list[IndexPoint]:
        ra: list[IndexPoint] = []
        offset = None
        while True:
            batch, offset = await self._c.scroll(
                name,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="anchor_code", match=models.MatchValue(value=anchor_code))]
                ),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            ra.extend(
                IndexPoint(
                    point_id=str(p.id),
                    record_id=int((p.payload or {}).get("record_id", 0)),
                    content_hash=str((p.payload or {}).get("content_hash", "")),
                )
                for p in batch
            )
            if offset is None:
                return ra

    async def count(self, name: str) -> int:
        return (await self._c.count(name, exact=True)).count

    async def payload_of(self, name: str, *, point_id: str) -> dict:
        """Đọc payload một point. Dùng cho job thu hồi caption và test hợp đồng payload."""
        got = await self._c.retrieve(name, ids=[point_id], with_payload=True)
        return dict(got[0].payload or {}) if got else {}

    async def describe(self, name: str) -> dict:
        """Dùng cho test hợp đồng hình dạng — không dùng ở đường chạy thật."""
        info = await self._c.get_collection(name)
        params = info.config.params
        ra: dict[str, Any] = {"sparse": dict(params.sparse_vectors or {})}
        vectors = params.vectors
        if hasattr(vectors, "size"):
            ra["dense"] = vectors.size
        else:
            ra.update({k: v.size for k, v in (vectors or {}).items()})
        return ra
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_store_qdrant.py -v`
Expected: 7 PASS. (Cần Docker — fixture `qdrant_url` ở `tests/conftest.py`.)

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/index/store.py tests/modules/kb/test_store_qdrant.py
git commit -m "feat(kb): QdrantStore async — giữ nguyên hình dạng collection agent đang đọc"
```

---

### Task 6: `clients/vlm.py` — caption ảnh và OCR trang

**Files:**
- Create: `src/portal/modules/kb/clients/vlm.py`
- Test: `tests/modules/kb/test_vlm_client.py`

**Interfaces:**
- Produces:
  - `VlmClient(base_url: str, api_key: str)`
  - `async caption(image_url: str, *, profile: str) -> str`
  - `async ocr_page(image_bytes: bytes, *, profile: str = "ocr_markdown") -> str`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_vlm_client.py`:

```python
"""Client VLM — MockTransport. Canh việc prompt lấy đúng từ prompts.yaml."""

import httpx
import pytest

from portal.modules.kb.clients.vlm import VlmClient


def _client(handler) -> VlmClient:
    c = VlmClient(base_url="https://vlm.test/v1", api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def _ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


async def test_caption_dung_prompt_cua_profile():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        ghi["body"] = json.loads(req.content)
        return _ok("Toà chung cư cao tầng bên hồ.")

    ra = await _client(handler).caption("https://cdn.test/a.jpg", profile="caption_subject")
    assert ra == "Toà chung cư cao tầng bên hồ."
    assert ghi["body"]["model"] == "qwen-vl-max"
    noi_dung = str(ghi["body"]["messages"])
    assert "CHỦ THỂ CHÍNH" in noi_dung, "không dùng prompt của caption_subject"
    assert "https://cdn.test/a.jpg" in noi_dung


async def test_caption_profile_khong_ton_tai_thi_raise():
    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng khi profile sai")

    with pytest.raises(KeyError):
        await _client(handler).caption("https://cdn.test/a.jpg", profile="khong_co")


async def test_api_key_rong_thi_raise_luc_dung():
    with pytest.raises(ValueError, match="KB_VLM_API_KEY"):
        VlmClient(base_url="https://vlm.test/v1", api_key="")


async def test_ocr_page_gui_anh_dang_data_uri():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        ghi["body"] = json.loads(req.content)
        return _ok("## Chương 1")

    ra = await _client(handler).ocr_page(b"\x89PNG_gia_lap")
    assert ra == "## Chương 1"
    assert "data:image/png;base64," in str(ghi["body"]["messages"])
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_vlm_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Cài đặt**

Create `src/portal/modules/kb/clients/vlm.py`:

```python
"""DashScope qwen-vl-max: caption ảnh và OCR một trang PDF scan.

Giao thức OpenAI-compatible (`/chat/completions`) — cùng bề mặt agent đang dùng.
Ảnh đi bằng URL khi có (100% media hiện tại là CloudFront công khai), bằng data URI
khi là trang PDF vừa render.
"""

import base64

import httpx

from portal.modules.kb import prompts, settings


class VlmClient:
    def __init__(self, *, base_url: str, api_key: str) -> None:
        if not api_key:
            raise ValueError("thiếu KB_VLM_API_KEY — không gửi request không auth")
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _chat(self, *, spec: prompts.PromptSpec, image_part: dict) -> str:
        r = await self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": spec.model,
                "max_tokens": spec.max_tokens,
                "temperature": spec.temperature,
                "messages": [
                    {"role": "user", "content": [image_part, {"type": "text", "text": spec.prompt}]}
                ],
            },
        )
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"]).strip()

    async def caption(self, image_url: str, *, profile: str) -> str:
        spec = prompts.get(profile)
        return await self._chat(spec=spec, image_part={"type": "image_url", "image_url": {"url": image_url}})

    async def ocr_page(self, image_bytes: bytes, *, profile: str = "ocr_markdown") -> str:
        spec = prompts.get(profile)
        uri = f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
        return await self._chat(spec=spec, image_part={"type": "image_url", "image_url": {"url": uri}})
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_vlm_client.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/vlm.py tests/modules/kb/test_vlm_client.py
git commit -m "feat(kb): client VLM — caption ảnh và OCR trang, prompt từ prompts.yaml"
```

---

### Task 7: `clients/video.py` — mô tả video

**Files:**
- Create: `src/portal/modules/kb/clients/video.py`
- Test: `tests/modules/kb/test_video_client.py`

**Interfaces:**
- Produces:
  - `youtube_watch_url(url: str) -> str | None` — `None` nếu không phải YouTube
  - `VideoClient(api_key: str)`
  - `async describe(media_url: str, *, profile: str = "video_describe") -> str`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_video_client.py`:

```python
"""Chuẩn hoá URL là chỗ dễ hỏng nhất: DB lưu dạng /embed/ (frontend nhúng iframe),
Gemini chỉ nhận dạng watch?v=. Gửi thẳng dạng nhúng là hỏng câm."""

import httpx
import pytest

from portal.modules.kb.clients.video import VideoClient, youtube_watch_url


@pytest.mark.parametrize(
    "vao,ra",
    [
        ("https://www.youtube.com/embed/fSVkxmsjAEw?si=Wq2tvB", "https://www.youtube.com/watch?v=fSVkxmsjAEw"),
        ("https://www.youtube.com/watch?v=fSVkxmsjAEw", "https://www.youtube.com/watch?v=fSVkxmsjAEw"),
        ("https://youtu.be/fSVkxmsjAEw", "https://www.youtube.com/watch?v=fSVkxmsjAEw"),
        ("https://cdn.test/clip.mp4", None),
        ("", None),
    ],
)
def test_chuan_hoa_url_youtube(vao, ra):
    assert youtube_watch_url(vao) == ra


async def test_describe_gui_file_uri_da_chuan_hoa():
    ghi = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        ghi["body"] = json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Video tiến độ."}]}}]})

    c = VideoClient(api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ra = await c.describe("https://www.youtube.com/embed/fSVkxmsjAEw?si=X")

    assert ra == "Video tiến độ."
    assert "watch?v=fSVkxmsjAEw" in str(ghi["body"]), "gửi dạng nhúng thay vì dạng xem"


async def test_api_key_rong_thi_raise_luc_dung():
    with pytest.raises(ValueError, match="KB_GEMINI_API_KEY"):
        VideoClient(api_key="")
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_video_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Cài đặt**

Create `src/portal/modules/kb/clients/video.py`:

```python
"""Gemini mô tả video. Hai nhánh nguồn: YouTube (file_uri) và mp4 trong kho (Files API).

CHUẨN HOÁ URL LÀ BẮT BUỘC: `tenant_data.media.media_url` lưu dạng nhúng
(`/embed/<id>?si=…`) vì frontend dùng chính nó cho iframe. Gemini chỉ nhận dạng xem
(`watch?v=<id>`). Hàm dưới chỉ đổi thứ GỬI ĐI — cột trong DB không đụng tới.
"""

import re

import httpx

from portal.modules.kb import prompts, settings

_API = "https://generativelanguage.googleapis.com/v1beta/models"

_YT = (
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,})"),
)


def youtube_watch_url(url: str) -> str | None:
    for pat in _YT:
        m = pat.search(url or "")
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    return None


class VideoClient:
    def __init__(self, *, api_key: str) -> None:
        if not api_key:
            raise ValueError("thiếu KB_GEMINI_API_KEY — không gửi request không auth")
        self._key = api_key
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def describe(self, media_url: str, *, profile: str = "video_describe") -> str:
        spec = prompts.get(profile)
        watch = youtube_watch_url(media_url)
        if watch is None:
            raise ValueError(f"nguồn video chưa hỗ trợ: {media_url!r} — hôm nay chỉ có nhánh YouTube")
        r = await self._http.post(
            f"{_API}/{spec.model}:generateContent",
            headers={"x-goog-api-key": self._key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"file_data": {"file_uri": watch}},
                            {"text": spec.prompt},
                        ]
                    }
                ],
                "generationConfig": {"maxOutputTokens": spec.max_tokens, "temperature": spec.temperature},
            },
        )
        r.raise_for_status()
        return str(r.json()["candidates"][0]["content"]["parts"][0]["text"]).strip()
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_video_client.py -v`
Expected: 7 PASS (5 param + 2).

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/video.py tests/modules/kb/test_video_client.py
git commit -m "feat(kb): client video Gemini — chuẩn hoá URL nhúng sang dạng xem"
```

---

### Task 8: `clients/extract.py` — Docling, PDF scan đẩy sang VLM

**Files:**
- Create: `src/portal/modules/kb/clients/extract.py`
- Test: `tests/modules/kb/test_extract.py`

**Interfaces:**
- Consumes: `VlmClient.ocr_page(image_bytes) -> str` (Task 6)
- Produces:
  - `TextExtractor(vlm: VlmClient | None = None)`
  - `async extract(data: bytes, *, filename: str) -> ExtractResult`
  - `ExtractResult` dataclass: `text: str`, `da_ocr: bool`, `da_cat: bool`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_extract.py`:

```python
"""Bóc chữ: Docling cho tệp có lớp chữ, VLM cho PDF scan.

`da_cat` phải đúng — chạm OCR_MAX_PAGES mà báo thành công là trả về một tài liệu
cụt và không ai biết.
"""

from pathlib import Path

import pytest

from portal.modules.kb.clients.extract import TextExtractor

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class VlmGia:
    def __init__(self, tra: str = "## Trang đã OCR") -> None:
        self.tra = tra
        self.so_lan = 0

    async def ocr_page(self, image_bytes: bytes, *, profile: str = "ocr_markdown") -> str:
        self.so_lan += 1
        return self.tra


@pytest.mark.skipif(not (FIXTURES / "tai_lieu_mau.pdf").exists(), reason="chưa sinh fixture")
async def test_pdf_co_lop_chu_dung_docling_khong_goi_vlm():
    vlm = VlmGia()
    ra = await TextExtractor(vlm=vlm).extract((FIXTURES / "tai_lieu_mau.pdf").read_bytes(), filename="a.pdf")
    assert ra.text.strip()
    assert ra.da_ocr is False
    assert vlm.so_lan == 0, "gọi VLM cho PDF đã có lớp chữ là đốt tiền"


async def test_pdf_khong_lop_chu_roi_sang_vlm(monkeypatch):
    from portal.modules.kb.clients import extract as mod

    async def docling_tra_rong(data, filename):
        return ""

    monkeypatch.setattr(mod, "_docling_markdown", docling_tra_rong)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"trang1", b"trang2"])

    vlm = VlmGia()
    ra = await TextExtractor(vlm=vlm).extract(b"%PDF-gia", filename="scan.pdf")
    assert ra.da_ocr is True
    assert vlm.so_lan == 2
    assert ra.text.count("## Trang đã OCR") == 2


async def test_cham_tran_so_trang_thi_bao_da_cat(monkeypatch):
    from portal.modules.kb.clients import extract as mod
    from portal.modules.kb import settings

    async def docling_tra_rong(data, filename):
        return ""

    monkeypatch.setattr(mod, "_docling_markdown", docling_tra_rong)
    monkeypatch.setattr(mod, "_dem_trang", lambda data: settings.OCR_MAX_PAGES + 5)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"t"] * gioi_han)

    ra = await TextExtractor(vlm=VlmGia()).extract(b"%PDF-gia", filename="dai.pdf")
    assert ra.da_cat is True


async def test_khong_co_vlm_thi_pdf_scan_tra_rong_khong_no(monkeypatch):
    """Enrich không được chết vì một PDF scan — ô để trống, người dùng tự dán."""
    from portal.modules.kb.clients import extract as mod

    async def docling_tra_rong(data, filename):
        return ""

    monkeypatch.setattr(mod, "_docling_markdown", docling_tra_rong)

    ra = await TextExtractor(vlm=None).extract(b"%PDF-gia", filename="scan.pdf")
    assert ra.text == ""
    assert ra.da_ocr is False


async def test_duoi_tep_la_thi_bao_loi():
    with pytest.raises(ValueError, match="không hỗ trợ"):
        await TextExtractor().extract(b"x", filename="a.exe")
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Cài đặt**

Create `src/portal/modules/kb/clients/extract.py`:

```python
"""Tệp → Markdown. Docling cho tệp có lớp chữ; PDF scan render trang rồi đẩy sang VLM.

⚠️ DOCLING ĐỒNG BỘ VÀ NGỐN CPU. Gọi thẳng trong coroutine sẽ đóng băng event loop của
worker: mọi job khác đứng im, và triệu chứng nhìn giống "Qdrant chậm" chứ không giống
"Docling đang chạy". Mọi lời gọi ở đây đi qua asyncio.to_thread.
"""

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from portal.modules.kb import settings

DUOI_HO_TRO = frozenset({"pdf", "docx", "xlsx"})


@dataclass(frozen=True, slots=True)
class ExtractResult:
    text: str
    da_ocr: bool = False
    da_cat: bool = False


def _docling_sync(data: bytes, filename: str) -> str:
    from docling.document_converter import DocumentConverter

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / filename
        p.write_bytes(data)
        return DocumentConverter().convert(str(p)).document.export_to_markdown()


async def _docling_markdown(data: bytes, filename: str) -> str:
    return await asyncio.to_thread(_docling_sync, data, filename)


def _dem_trang(data: bytes) -> int:
    import pypdfium2

    doc = pypdfium2.PdfDocument(data)
    try:
        return len(doc)
    finally:
        doc.close()


def _render_pages(data: bytes, gioi_han: int) -> list[bytes]:
    """PDF → PNG từng trang. Chỉ gọi khi Docling trả rỗng."""
    import io

    import pypdfium2

    ra: list[bytes] = []
    doc = pypdfium2.PdfDocument(data)
    try:
        for i in range(min(len(doc), gioi_han)):
            buf = io.BytesIO()
            doc[i].render(scale=2).to_pil().save(buf, format="PNG")
            ra.append(buf.getvalue())
    finally:
        doc.close()
    return ra


class TextExtractor:
    def __init__(self, *, vlm=None) -> None:
        self._vlm = vlm

    async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
        duoi = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if duoi not in DUOI_HO_TRO:
            raise ValueError(f"đuôi tệp không hỗ trợ: {duoi!r} — chỉ {sorted(DUOI_HO_TRO)}")

        md = await _docling_markdown(data, filename)
        if md.strip():
            return ExtractResult(text=md)

        # Docling trả rỗng: PDF ảnh scan, hoặc tệp rỗng thật. Không có VLM thì để trống
        # — giao diện hiện "không bóc được chữ, vui lòng dán nội dung".
        if duoi != "pdf" or self._vlm is None:
            return ExtractResult(text="")

        tong = await asyncio.to_thread(_dem_trang, data)
        gioi_han = settings.OCR_MAX_PAGES
        pages = await asyncio.to_thread(_render_pages, data, gioi_han)
        phan = [await self._vlm.ocr_page(p) for p in pages]
        return ExtractResult(
            text="\n\n".join(t for t in phan if t.strip()),
            da_ocr=True,
            da_cat=tong > gioi_han,
        )
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/modules/kb/test_extract.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/kb/clients/extract.py tests/modules/kb/test_extract.py
git commit -m "feat(kb): bóc chữ bằng Docling trong to_thread, PDF scan đẩy sang VLM"
```

---

### Task 9: Ráp `IndexClient` thật

**Files:**
- Modify: `src/portal/modules/kb/clients/base.py`
- Modify: `src/portal/modules/kb/clients/rag.py`
- Modify: `src/portal/modules/kb/clients/media.py`
- Test: `tests/modules/kb/test_index_client_that.py`

**Interfaces:**
- Consumes: `EmbedClient` (T4), `QdrantStore`/`PointIn`/`point_id_of` (T5)
- Produces: `RagClient(embed, store)` và `MediaClient(embed, store)` cài đủ `contracts.IndexClient`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_index_client_that.py`:

```python
"""IndexClient thật: directive → point trong Qdrant.

Bộ khoá payload là HỢP ĐỒNG với repo agent — 381 point đang sống có đúng bộ này.
Test cuối là chỗ duy nhất bắt được một lần đổi tên khoá.
"""

import pytest

from portal.modules.kb.clients.media import MediaClient
from portal.modules.kb.clients.rag import RagClient, collection_name
from portal.modules.kb.contracts import ChunkSpec, MediaDirective, TextDirective
from portal.modules.kb.index.store import QdrantStore

KHOA_PAYLOAD_CU = {
    "project_id", "content_type", "category", "caption",
    "media_url", "content_hash", "record_id", "thumb_url",
}


class EmbedGia:
    async def dense(self, texts): return [[0.1] * 1024 for _ in texts]
    async def sparse(self, texts): return [{"indices": [1], "values": [0.5]} for _ in texts]
    async def visual_image(self, urls): return [[0.2] * 768 for _ in urls]


@pytest.fixture
async def store(qdrant_url):
    s = QdrantStore(url=qdrant_url)
    yield s
    await s.aclose()


def _text_directive(text: str = "Nội dung tài liệu") -> TextDirective:
    return TextDirective(
        workspace_slug="ws", record_id=11, doc_type="csbh", anchor_code="nplb",
        anchor_name="Noble Palace", section="Bảng giá", text=text,
        chunk=ChunkSpec(strategy="markdown", max_chars=800, overlap=150),
    )


async def test_index_text_tao_point_va_tra_content_hash(store):
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws")
    ra = await c.index(_text_directive())
    assert ra.points_upserted >= 1
    assert len(ra.content_hash) == 64
    assert await store.count(collection_name("ws")) == ra.points_upserted


async def test_index_hai_lan_cung_noi_dung_khong_nhan_doi_point(store):
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws2")
    d = _text_directive()
    a = await c.index(d)
    b = await c.index(d)
    assert a.content_hash == b.content_hash
    assert await store.count(collection_name("ws2")) == a.points_upserted


async def test_delete_xoa_dung_point(store):
    c = RagClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws3")
    await c.index(_text_directive())
    await c.delete(workspace_slug="ws3", record_id=11, doc_type="csbh")
    assert await store.count(collection_name("ws3")) == 0


async def test_media_payload_giu_nguyen_bo_khoa_cu(store):
    c = MediaClient(embed=EmbedGia(), store=store)
    await c.create_collection(workspace_slug="ws4")
    await c.index(
        MediaDirective(
            workspace_slug="ws4", record_id=960, anchor_code="MPP", content_type="image",
            category="mat_bang", media_url="https://cdn.test/mb.jpg",
            caption="Bản đồ mặt bằng tầng điển hình.", thumb_url="tenants/ws4/kb-bds/x.webp",
        )
    )
    pts = await store.scroll_points("ws4_media", anchor_code="MPP")
    assert len(pts) == 1

    payload = await store.payload_of("ws4_media", point_id=pts[0].point_id)
    assert KHOA_PAYLOAD_CU <= set(payload), "thiếu khoá payload mà agent đang đọc"
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_index_client_that.py -v`
Expected: FAIL — `RagClient() takes no keyword arguments` hoặc `NotImplementedError`

- [ ] **Step 3: Viết `base.py`**

Replace `src/portal/modules/kb/clients/base.py` — giữ nguyên `index_body`, `parse_result`, `parse_scroll` (test cũ dùng), thay `HttpIndexClient` bằng:

```python
class LocalIndexClient:
    """Cài `contracts.IndexClient` bằng pipeline nội bộ: chunk → embed → Qdrant.

    THAY CHO HttpIndexClient (gọi rag_service của santa-models). Service đó chưa bao giờ
    tồn tại và chủ dự án đã chốt Portal làm độc lập — xem spec 2026-08-10 §1.

    Lớp này giữ nguyên interface để `service.py`, `fake.py` và mọi test hiện có không
    phải đổi một dòng.
    """

    target: Target = "documents"
    media_collection = False

    def __init__(self, *, embed, store) -> None:
        self._embed = embed
        self._store = store

    def collection(self, workspace_slug: str) -> str:
        raise NotImplementedError

    async def create_collection(self, *, workspace_slug: str) -> None:
        await self._store.ensure_collection(self.collection(workspace_slug), media=self.media_collection)

    async def drop_collection(self, *, workspace_slug: str) -> None:
        await self._store.drop_collection(self.collection(workspace_slug))

    async def scroll(self, *, workspace_slug: str, anchor_code: str) -> list[IndexPoint]:
        return await self._store.scroll_points(self.collection(workspace_slug), anchor_code=anchor_code)

    async def delete(self, *, workspace_slug: str, record_id: int, doc_type: str = "") -> IndexResult:
        n = await self._store.delete_by_record(
            self.collection(workspace_slug), record_id=record_id, doc_type=doc_type
        )
        return IndexResult(points_deleted=n)
```

Thêm import cần thiết ở đầu tệp: `from portal.modules.kb.contracts import IndexPoint, IndexResult, Target`.

- [ ] **Step 4: Viết `rag.py`**

Replace `src/portal/modules/kb/clients/rag.py`:

```python
"""Đường text → collection `<slug>_documents`.

Trước 2026-08-10 file này là vỏ cho một `rag_service` bên santa-models. Service đó
không tồn tại; pipeline nay chạy trong chính Portal.
"""

import hashlib

from portal.modules.kb import settings
from portal.modules.kb.clients.base import LocalIndexClient
from portal.modules.kb.contracts import IndexResult, TextDirective
from portal.modules.kb.index import chunker
from portal.modules.kb.index.store import PointIn, point_id_of


def collection_name(workspace_slug: str) -> str:
    return f"{workspace_slug}_{settings.COLLECTION_SUFFIX_DOCUMENTS}"


class RagClient(LocalIndexClient):
    target = "documents"
    media_collection = False

    def collection(self, workspace_slug: str) -> str:
        return collection_name(workspace_slug)

    async def index(self, directive: TextDirective) -> IndexResult:
        ten = self.collection(directive.workspace_slug)
        # Breadcrumb đứng đầu mỗi chunk: chunk thứ 5 của một tài liệu không mang tên
        # dự án thì agent trả lời đúng nội dung cho sai dự án.
        dau = f"{directive.anchor_name} — {directive.section}".strip(" —")
        chunks = chunker.split(directive.text, directive.chunk)
        if not chunks:
            return IndexResult(points_upserted=0, content_hash="")

        noi_dung = [f"{dau}\n\n{c}" if dau else c for c in chunks]
        content_hash = hashlib.sha256("␟".join(noi_dung).encode()).hexdigest()

        dense = await self._embed.dense(noi_dung)
        sparse = await self._embed.sparse(noi_dung)

        points = [
            PointIn(
                point_id=point_id_of(directive.doc_type, directive.record_id, i),
                vectors={"dense": dense[i], "bm25": {"indices": s["indices"], "values": s["values"]}},
                payload={
                    "project_id": directive.anchor_code,
                    "anchor_code": directive.anchor_code,
                    "doc_type": directive.doc_type,
                    "content_type": "text",
                    "section": directive.section,
                    "text": noi_dung[i],
                    "chunk_index": i,
                    "record_id": directive.record_id,
                    "content_hash": content_hash,
                },
            )
            for i, s in enumerate(sparse)
        ]
        n = await self._store.upsert(ten, points)
        return IndexResult(points_upserted=n, content_hash=content_hash)
```

- [ ] **Step 5: Viết `media.py`**

Replace `src/portal/modules/kb/clients/media.py`:

```python
"""Đường media → collection `<slug>_media`.

BỘ KHOÁ PAYLOAD LÀ HỢP ĐỒNG: 381 point đang sống trên EC2 có đúng bộ dưới đây và agent
đọc chúng. Không đổi tên khoá nào — kể cả `project_id`, vốn mang anchor_code và đặt
chưa hay. Đổi tên là việc của một đợt có kiểm chứng ở cả hai repo.
"""

import hashlib

from portal.modules.kb import settings
from portal.modules.kb.clients.base import LocalIndexClient
from portal.modules.kb.contracts import IndexResult, MediaDirective
from portal.modules.kb.index.store import PointIn, point_id_of

# Media không chia chunk: một ảnh là một point. `doc_type` rỗng giữ đúng quy ước
# point-id mà 381 point cũ đã dùng.
_DOC_TYPE = ""


def collection_name(workspace_slug: str) -> str:
    return f"{workspace_slug}_{settings.COLLECTION_SUFFIX_MEDIA}"


class MediaClient(LocalIndexClient):
    target = "media"
    media_collection = True

    def collection(self, workspace_slug: str) -> str:
        return collection_name(workspace_slug)

    async def index(self, directive: MediaDirective) -> IndexResult:
        ten = self.collection(directive.workspace_slug)
        caption = directive.caption or ""
        mo_ta = f"{directive.category} {caption}".strip()
        content_hash = hashlib.sha256(f"{directive.media_url}␟{caption}".encode()).hexdigest()

        text_vec = (await self._embed.dense([mo_ta]))[0]
        nguon_anh = directive.file_url or directive.media_url
        visual = await self._embed.visual_image([nguon_anh]) if directive.content_type == "image" else []

        vectors = {"text": text_vec}
        if visual:
            vectors["visual"] = visual[0]

        point = PointIn(
            point_id=point_id_of(_DOC_TYPE, directive.record_id, 0),
            vectors=vectors,
            payload={
                "project_id": directive.anchor_code,
                "anchor_code": directive.anchor_code,
                "content_type": directive.content_type,
                "category": directive.category,
                "caption": caption,
                "media_url": directive.media_url,
                "thumb_url": directive.thumb_url or "",
                "record_id": directive.record_id,
                "content_hash": content_hash,
            },
        )
        n = await self._store.upsert(ten, [point])
        return IndexResult(points_upserted=n, content_hash=content_hash)
```

- [ ] **Step 6: Chạy test**

Run: `uv run pytest tests/modules/kb/test_index_client_that.py tests/modules/kb/test_service_ingest.py -v`
Expected: tất cả PASS — `test_service_ingest.py` (dùng `fake.py`) phải vẫn xanh, đó là bằng chứng interface không đổi.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/kb/clients/ tests/modules/kb/test_index_client_that.py
git commit -m "feat(kb): IndexClient chạy nội bộ — chunk, embed, ghi Qdrant; bỏ NotImplementedError"
```

---

### Task 10: Job `kb_enrich` và `dependencies()`

**Files:**
- Modify: `src/portal/modules/kb/contracts.py`
- Modify: `src/portal/modules/kb/state/repo.py`
- Modify: `src/portal/modules/kb/jobs.py`
- Test: `tests/modules/kb/test_enrich_job.py`

**Interfaces:**
- Consumes: `VlmClient` (T6), `VideoClient` (T7), `TextExtractor` (T8), `RagClient`/`MediaClient` (T9)
- Produces:
  - `contracts.KIND_ENRICH = "kb_enrich"`
  - `repo.cache_caption(conn, *, record_id, caption, force=False)`
  - `repo.cache_extracted_text(conn, *, record_id, text, force=False)`
  - `jobs.handle_enrich(conn, payload) -> JobResult`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_enrich_job.py`:

```python
"""Luật chỉ-ghi-khi-rỗng — thứ quan trọng nhất của chặng enrich.

Một job retry sau khi biên tập viên đã sửa caption sẽ im lặng xoá công sức của họ:
không lỗi, không log, và họ chỉ biết khi tình cờ đọc lại.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.state import repo

TENANT = "kb_acme"


@pytest.fixture
async def media_id(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        return await conn.fetchval(
            """INSERT INTO tenant_data.media
                      (tenant_id, project_code, content_type, category, media_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'image', 'tong_quan',
                       'https://cdn.test/a.jpg', 'published')
               RETURNING id"""
        )


async def test_ghi_caption_khi_o_dang_rong(pool, media_id):
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="do máy sinh")
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "do máy sinh"


async def test_khong_de_len_caption_user_da_sua(pool, media_id):
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="bản máy")
        await conn.execute(
            "UPDATE tenant_data.media SET caption = $2 "
            "WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
            "bản người sửa",
        )
        await repo.cache_caption(conn, record_id=media_id, caption="bản máy lần hai")
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "bản người sửa", "job retry đã xoá công sức của biên tập viên"


async def test_force_moi_de_duoc(pool, media_id):
    """Nút "Tạo lại mô tả" — người dùng chủ động, có hộp xác nhận ở giao diện."""
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="bản người sửa")
        await repo.cache_caption(conn, record_id=media_id, caption="bản tạo lại", force=True)
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "bản tạo lại"


async def test_khong_dung_toi_media_cua_tenant_khac(pool, media_id):
    """RLS đã dỡ ở 0909 — vị từ tenant nay là quy ước của code, phải có test canh."""
    async with tenant_conn(pool, "kb_other") as conn:
        await repo.cache_caption(conn, record_id=media_id, caption="xuyên tenant")
    async with tenant_conn(pool, TENANT) as conn:
        ra = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            media_id,
        )
    assert ra == "", "câu UPDATE thiếu vị từ tenant_id"
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_enrich_job.py -v`
Expected: FAIL — `cache_caption() got an unexpected keyword argument 'force'`

- [ ] **Step 3: Thêm `force` vào `repo.py`**

Modify `src/portal/modules/kb/state/repo.py` — thay hai hàm:

```python
async def cache_extracted_text(conn: asyncpg.Connection, *, record_id: int, text: str, force: bool = False) -> None:
    """`AND body = ''` là luật "user thắng". Điều kiện nằm TRONG câu SQL, không ở tầng
    Python: hai worker song song đều đọc thấy "đang rỗng" rồi cùng ghi.

    `force=True` chỉ đến từ nút "Tạo lại mô tả" — người dùng chủ động, có xác nhận.
    """
    await conn.execute(
        "UPDATE tenant_data.documents SET body = $2, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1 AND ($3 OR body = '')",
        record_id,
        text,
        force,
    )


async def cache_caption(conn: asyncpg.Connection, *, record_id: int, caption: str, force: bool = False) -> None:
    await conn.execute(
        "UPDATE tenant_data.media SET caption = $2, updated_at = now() "
        "WHERE tenant_id = portal.current_tenant() AND id = $1 AND ($3 OR caption = '')",
        record_id,
        caption,
        force,
    )
```

- [ ] **Step 4: Thêm `KIND_ENRICH` vào `contracts.py`**

Modify `src/portal/modules/kb/contracts.py`, cạnh `KIND_INDEX`:

```python
KIND_DELETE_INDEX = "kb_delete"
KIND_INDEX = "kb_index"
# `modules/realestate` enqueue sau POST /media và POST /documents, nên hằng phải ở đây:
# luật 3 chỉ cho module khác import contracts.
KIND_ENRICH = "kb_enrich"
```

- [ ] **Step 5: Viết handler và `dependencies()`**

Modify `src/portal/modules/kb/jobs.py` — thay `dependencies()` và thêm handler:

```python
def dependencies() -> tuple[IndexClient, IndexClient, ObjectStore]:
    """(rag, media, store) thật. Dựng mới mỗi job: worker chạy tuần tự một job một lúc,
    và một client sống lâu giữ kết nối HTTP qua các job là chỗ lỗi khó truy khi tunnel
    của embed service đổi URL."""
    from portal.core.config import get_settings
    from portal.modules.kb.clients.embed import EmbedClient
    from portal.modules.kb.clients.media import MediaClient
    from portal.modules.kb.clients.rag import RagClient
    from portal.modules.kb.index.store import QdrantStore
    from portal.modules.kb.storage.object_store import kho_tep_kb

    env = get_env()
    cfg = get_settings()
    embed = EmbedClient(base_url=env.rag_url, token=env.santa_models_token)
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    return RagClient(embed=embed, store=store), MediaClient(embed=embed, store=store), kho_tep_kb()


def _vlm():
    from portal.modules.kb.clients.vlm import VlmClient

    env = get_env()
    return VlmClient(base_url=env.vlm_base_url, api_key=env.vlm_api_key)


async def handle_enrich(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Ảnh → caption VLM · video → mô tả Gemini · tệp → Docling. Ghi vào cột user sửa.

    Không index gì ở đây: chặng này chỉ dựng bản nháp cho người đọc. Việc đưa nội dung
    tới agent là của `kb_index`, và nó do người bấm nút.
    """
    entity = str(payload["entity"])
    record_id = int(payload["record_id"])
    force = bool(payload.get("force", False))

    if entity == "media":
        row = await conn.fetchrow(
            "SELECT content_type, category, media_url FROM tenant_data.media "
            "WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
        if row is None:
            return JobResult(count=0, message=f"media#{record_id} không còn")
        if str(row["content_type"]) == "video":
            from portal.modules.kb.clients.video import VideoClient

            noi_dung = await VideoClient(api_key=get_env().gemini_api_key).describe(str(row["media_url"]))
        else:
            vertical = registry.get(str(payload.get("vertical", "real_estate")))
            profile = profiles.caption_profile(vertical, str(row["category"]))
            noi_dung = await _vlm().caption(str(row["media_url"]), profile=profile)
        await repo.cache_caption(conn, record_id=record_id, caption=noi_dung, force=force)
        return JobResult(count=1, message=f"media#{record_id}: {len(noi_dung)} ký tự mô tả")

    row = await conn.fetchrow(
        "SELECT file_url FROM tenant_data.documents "
        "WHERE tenant_id = portal.current_tenant() AND id = $1",
        record_id,
    )
    if row is None or not row["file_url"]:
        return JobResult(count=0, message=f"documents#{record_id} không có tệp để bóc")

    from portal.modules.kb.clients.extract import TextExtractor

    _, _, store = dependencies()
    khoa = store.key(tenant_id=str(await conn.fetchval("SELECT portal.current_tenant()")), path=str(row["file_url"]))
    data = await store.doc(key=khoa)
    ra = await TextExtractor(vlm=_vlm()).extract(data, filename=str(row["file_url"]))
    if not ra.text:
        return JobResult(count=0, message="không bóc được chữ từ tệp này, vui lòng dán nội dung")
    await repo.cache_extracted_text(conn, record_id=record_id, text=ra.text, force=force)
    cat = " (đã cắt ở trần số trang)" if ra.da_cat else ""
    return JobResult(count=1, message=f"documents#{record_id}: {len(ra.text)} ký tự{cat}")


register(KIND_ENRICH, handle_enrich)
```

Thêm import ở đầu tệp: `from portal.modules.kb.contracts import KIND_ENRICH`, `from portal.modules.kb.directive import profiles`, `from portal.modules.kb.state import repo`, `from portal.modules.kb.settings import get_env`.

- [ ] **Step 6: Thêm `doc()` vào `ObjectStore`**

`TextExtractor` cần byte của tệp. Modify `src/portal/modules/kb/contracts.py`, trong `class ObjectStore(Protocol)`:

```python
    async def doc(self, *, key: str) -> bytes:
        """Đọc byte. Cần cho bóc chữ: Docling nhận tệp, không nhận URL."""
        ...
```

Modify `src/portal/modules/kb/fake.py`, trong `FakeObjectStore`:

```python
    async def doc(self, *, key: str) -> bytes:
        return self.stored.get(key, b"")
```

Modify `src/portal/modules/kb/storage/object_store.py` — thêm `doc()` gọi `get_object` của kho thật, cùng nếp `presign_get` đang dùng.

- [ ] **Step 7: Chạy test**

Run: `uv run pytest tests/modules/kb/test_enrich_job.py tests/modules/kb/test_jobs_handler.py -v`
Expected: tất cả PASS.

- [ ] **Step 8: Commit**

```bash
git add src/portal/modules/kb/ tests/modules/kb/test_enrich_job.py
git commit -m "feat(kb): job kb_enrich + luật chỉ-ghi-khi-rỗng có nhánh force"
```

---

### Task 11: Ba job vận hành — sync, provision, reclaim

**Files:**
- Create: `src/portal/modules/kb/ops/sync.py`
- Modify: `src/portal/modules/kb/jobs.py`
- Test: `tests/modules/kb/test_sync_job.py`

**Interfaces:**
- Produces:
  - `ops.sync.enqueue_project(conn, *, tenant_id, project_code, vertical, actor) -> int`
  - Job kind: `kb_sync_project`, `kb_provision`, `kb_reclaim_caption`

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_sync_job.py`:

```python
"""Cascade theo dự án: một job mở màn xếp N job con.

Router KHÔNG được enqueue N job trực tiếp — một dự án có 20 phân khu + 96 media thì
giao dịch của request mở suốt 116 lần INSERT trong khi người dùng ngồi chờ.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.ops import sync

TENANT = "kb_acme"


async def test_enqueue_project_xep_job_cho_moi_record_published(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        n = await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test"
        )
        kinds = await conn.fetch(
            "SELECT kind, payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", TENANT
        )
    assert n == len(kinds) > 0
    assert all(p["payload"] for p in kinds)


async def test_khong_xep_job_cho_du_an_khac(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test"
        )
        rows = await conn.fetch(
            "SELECT payload->>'record_id' AS rid FROM control.jobs "
            "WHERE tenant_id = $1 AND kind = 'kb_index'",
            TENANT,
        )
        thuoc_du_an_khac = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.documents "
            "WHERE tenant_id = portal.current_tenant() AND project_code <> 'nplb' "
            "  AND id::text = ANY($1::text[])",
            [r["rid"] for r in rows],
        )
    assert thuoc_du_an_khac == 0, "cascade tràn sang dự án khác"


async def test_du_an_khong_ton_tai_tra_khong(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        n = await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="khong_co", vertical=REAL_ESTATE, actor="test"
        )
    assert n == 0
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_sync_job.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.kb.ops.sync`

- [ ] **Step 3: Viết `ops/sync.py`**

Create `src/portal/modules/kb/ops/sync.py`:

```python
"""Cascade theo một dự án. `ops/backfill.py` làm cả tenant; đây thu hẹp phạm vi.

Gọi TỪ WORKER của job `kb_sync_project`, không gọi từ router — xem test đầu tệp test.
"""

import asyncpg

from portal.core.jobs import enqueue
from portal.modules.kb.contracts import KIND_INDEX, VerticalSpec


async def enqueue_project(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    project_code: str,
    vertical: VerticalSpec,
    actor: str,
) -> int:
    count = 0
    for spec in vertical.embed_sources:
        cot_anchor = vertical.anchor_code_col if spec.is_anchor else spec.anchor_col
        rows = await conn.fetch(
            f"SELECT id FROM tenant_data.{spec.table} "  # noqa: S608 — spec.table từ khai báo, không từ request
            "WHERE tenant_id = portal.current_tenant() AND status = 'published' "
            f"  AND {cot_anchor} = $1 ORDER BY id",
            project_code,
        )
        for r in rows:
            await enqueue(
                conn,
                tenant_id=tenant_id,
                kind=KIND_INDEX,
                actor=actor,
                payload={
                    "vertical": vertical.key,
                    "entity": spec.table,
                    "doc_type": spec.doc_type,
                    "record_id": int(r["id"]),
                    "op": "upsert",
                },
            )
            count += 1

    rows = await conn.fetch(
        "SELECT id FROM tenant_data.media "
        "WHERE tenant_id = portal.current_tenant() AND status = 'published' "
        f"  AND {vertical.media_anchor_col} = $1 ORDER BY id",
        project_code,
    )
    for r in rows:
        await enqueue(
            conn,
            tenant_id=tenant_id,
            kind=KIND_INDEX,
            actor=actor,
            payload={"vertical": vertical.key, "entity": "media", "record_id": int(r["id"]), "op": "upsert"},
        )
        count += 1
    return count
```

- [ ] **Step 4: Thêm ba handler vào `jobs.py`**

```python
KIND_SYNC_PROJECT = "kb_sync_project"
KIND_PROVISION = "kb_provision"
KIND_RECLAIM_CAPTION = "kb_reclaim_caption"


async def handle_sync_project(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Nút "Đồng bộ tri thức". Một job mở màn xếp N job con."""
    from portal.modules.kb.ops import sync

    vertical = registry.get(str(payload.get("vertical", "real_estate")))
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    n = await sync.enqueue_project(
        conn,
        tenant_id=tenant_id,
        project_code=str(payload["project_code"]),
        vertical=vertical,
        actor=str(payload.get("actor", "sync")),
    )
    return JobResult(count=n, message=f"đã xếp {n} job đánh chỉ mục")


async def handle_provision(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Dựng 2 collection của một workspace. Idempotent — ensure_collection bỏ qua nếu có."""
    from portal.modules.kb.ops import collections

    _ = payload
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    rag, media, _store = dependencies()
    await collections.create(rag=rag, media=media, workspace_slug=workspace_slug(tenant_id))
    return JobResult(count=2, message=f"đã dựng 2 collection cho {tenant_id}")


async def handle_reclaim_caption(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Thu hồi caption đã sinh ở hệ cũ từ Qdrant về Aurora.

    Chạy MỘT LẦN mỗi tenant, trước lần enrich đầu tiên: sau bước này `kb_enrich` không
    gọi VLM lại cho ~269 ảnh đã có caption. Idempotent nhờ luật chỉ-ghi-khi-rỗng.
    """
    from portal.modules.kb.clients.media import collection_name
    from portal.modules.kb.index.store import QdrantStore
    from portal.core.config import get_settings

    vertical = registry.get(str(payload.get("vertical", "real_estate")))
    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    cfg = get_settings()
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    ten = collection_name(workspace_slug(tenant_id))

    anchors = [
        r["code"]
        for r in await conn.fetch(
            f"SELECT {vertical.anchor_code_col} AS code FROM tenant_data.{vertical.anchor_table} "
            "WHERE tenant_id = portal.current_tenant()"
        )
    ]
    n = 0
    for anchor in anchors:
        for p in await store.scroll_points(ten, anchor_code=str(anchor)):
            cap = str((await store.payload_of(ten, point_id=p.point_id)).get("caption", ""))
            if not cap:
                continue
            await repo.cache_caption(conn, record_id=p.record_id, caption=cap)
            n += 1
    await store.aclose()
    return JobResult(count=n, message=f"thu hồi {n} caption về Aurora")


register(KIND_SYNC_PROJECT, handle_sync_project)
register(KIND_PROVISION, handle_provision)
register(KIND_RECLAIM_CAPTION, handle_reclaim_caption)
```

Không thêm gì vào `index/store.py` — `payload_of()` đã có từ Task 5.

- [ ] **Step 5: Chạy test**

Run: `uv run pytest tests/modules/kb/ -v`
Expected: tất cả PASS.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/kb/ tests/modules/kb/test_sync_job.py
git commit -m "feat(kb): job sync theo dự án, provision collection, thu hồi caption cũ"
```

---

### Task 12: Bốn endpoint và enqueue `kb_enrich`

**Files:**
- Modify: `src/portal/modules/realestate/router.py`
- Test: `tests/modules/kb/test_endpoint_sync.py`

**Interfaces:**
- Consumes: `contracts.KIND_ENRICH`, job kinds từ T11
- Produces: 4 endpoint HTTP

- [ ] **Step 1: Viết test trước**

Create `tests/modules/kb/test_endpoint_sync.py`:

```python
"""Bốn endpoint mới. Quyền dùng lại catalog.* — không thêm action nào (luật 4 + PQ_01)."""

import pytest


async def test_post_media_xep_job_enrich(client_cfg, workspace_cfg, pool):
    from portal.core.db.session import tenant_conn

    r = await client_cfg.post(
        "/api/v1/projects/nplb/media",
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://cdn.test/a.jpg"},
    )
    assert r.status_code == 201
    async with tenant_conn(pool, workspace_cfg) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_enrich'", workspace_cfg
        )
    assert n == 1, "upload ảnh mà không xếp job enrich thì ô mô tả trống vĩnh viễn"


async def test_post_sync_kb_tra_202_va_mot_job(client_cfg, workspace_cfg, pool):
    from portal.core.db.session import tenant_conn

    r = await client_cfg.post("/api/v1/projects/nplb/sync-kb")
    assert r.status_code == 202
    assert "jobId" in r.json()
    async with tenant_conn(pool, workspace_cfg) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_sync_project'", workspace_cfg
        )
    assert n == 1, "router phải xếp ĐÚNG MỘT job mở màn, không xếp N job con"


async def test_get_kb_sync_status_bao_lech_sau_khi_sua(client_cfg):
    r = await client_cfg.get("/api/v1/projects/kb-sync-status")
    assert r.status_code == 200
    ds = r.json()
    assert all({"projectCode", "inSync", "lastSyncedAt"} <= set(x) for x in ds)


async def test_get_enrich_status_tra_trang_thai_job(client_cfg):
    r = await client_cfg.get("/api/v1/projects/nplb/enrich-status")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_thieu_quyen_thi_403(client_khong_quyen):
    r = await client_khong_quyen.post("/api/v1/projects/nplb/sync-kb")
    assert r.status_code == 403
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/kb/test_endpoint_sync.py -v`
Expected: FAIL — 404 cho các route chưa có.

- [ ] **Step 3: Thêm enqueue `kb_enrich` sau `POST /media` và `POST /documents`**

Modify `src/portal/modules/realestate/router.py` — trong `tao_media`, sau `_nhat_ky`:

```python
        # Enrich chạy ngay, KHÔNG index: chặng này chỉ dựng bản nháp cho người đọc.
        # Đưa nội dung tới agent là việc của nút "Đồng bộ tri thức" (spec §4).
        await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_ENRICH,
            actor=p.user_id,
            payload={"vertical": "real_estate", "entity": "media", "record_id": media_id},
        )
```

Tương tự trong `tao_tai_lieu` với `"entity": "documents"` — **chỉ khi hàng có `file_url`**, tài liệu nhập tay không có gì để bóc.

- [ ] **Step 4: Thêm bốn endpoint**

```python
@ROUTER.post("/projects/{project_code}/sync-kb", status_code=202)
async def dong_bo_tri_thuc(
    project_code: str,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, int | str]:
    """202 + MỘT job mở màn. Worker của nó mới xếp N job con — xem kb/ops/sync.py."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        job_id = await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind="kb_sync_project",
            actor=p.user_id,
            payload={"vertical": "real_estate", "project_code": project_code, "actor": p.user_id},
        )
    return {"jobId": job_id, "state": "queued"}


@ROUTER.post("/media/{media_id}/recaption", status_code=202)
async def tao_lai_mo_ta(
    media_id: int,
    p: Principal = require(ACTIONS.CATALOG_WRITE),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> dict[str, int | str]:
    """`force: true` — đè lên caption người dùng đã sửa. Giao diện phải hỏi xác nhận."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        job_id = await enqueue(
            conn,
            tenant_id=p.tenant_id,
            kind=KIND_ENRICH,
            actor=p.user_id,
            payload={"vertical": "real_estate", "entity": "media", "record_id": media_id, "force": True},
        )
    return {"jobId": job_id, "state": "queued"}


@ROUTER.get("/projects/{project_code}/enrich-status")
async def trang_thai_enrich(
    project_code: str,
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[dict]:
    """Suy từ control.jobs — không cột mới, không bảng mới."""
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT j.payload->>'entity' AS entity,
                   (j.payload->>'record_id')::bigint AS record_id,
                   j.state, j.message
              FROM control.jobs j
             WHERE j.tenant_id = $1 AND j.kind = $2
               AND (
                    (j.payload->>'entity' = 'media' AND EXISTS (
                        SELECT 1 FROM tenant_data.media m
                         WHERE m.tenant_id = $1 AND m.id = (j.payload->>'record_id')::bigint
                           AND m.project_code = $3))
                 OR (j.payload->>'entity' = 'documents' AND EXISTS (
                        SELECT 1 FROM tenant_data.documents d
                         WHERE d.tenant_id = $1 AND d.id = (j.payload->>'record_id')::bigint
                           AND d.project_code = $3))
               )
             ORDER BY j.id DESC
            """,
            p.tenant_id,
            KIND_ENRICH,
            project_code,
        )
    return [
        {"entity": r["entity"], "recordId": r["record_id"], "state": r["state"], "message": r["message"]}
        for r in rows
    ]


@ROUTER.get("/projects/kb-sync-status")
async def trang_thai_dong_bo(
    p: Principal = require(ACTIONS.CATALOG_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[dict]:
    """Mức DỰ ÁN, không đi sâu hơn: người dùng chỉ cần biết dự án nào còn lệch.

    So updated_at của record với max(indexed_at) của chính dự án đó. BÁO THỪA CÓ CHỦ Ý —
    bấm Lưu mà không đổi gì cũng đẩy updated_at. Bù lại là bước thoát-sớm-theo-content_hash
    ở worker: chỉ báo sai lệch về phía an toàn, tiền embed thì không tiêu thừa (spec §7).
    """
    async with tenant_conn(pool, p.tenant_id) as conn:
        rows = await conn.fetch(
            """
            WITH sua AS (
                SELECT project_code, max(updated_at) AS lan_sua FROM (
                    SELECT project_code, updated_at FROM tenant_data.projects
                     WHERE tenant_id = portal.current_tenant()
                    UNION ALL
                    SELECT project_code, updated_at FROM tenant_data.zones
                     WHERE tenant_id = portal.current_tenant()
                    UNION ALL
                    SELECT project_code, updated_at FROM tenant_data.documents
                     WHERE tenant_id = portal.current_tenant()
                    UNION ALL
                    SELECT project_code, updated_at FROM tenant_data.media
                     WHERE tenant_id = portal.current_tenant()
                ) t GROUP BY project_code
            ),
            idx AS (
                SELECT p.project_code, max(s.indexed_at) AS lan_index
                  FROM tenant_data.projects p
                  JOIN tenant_data.kb_index_state s
                    ON s.tenant_id = portal.current_tenant()
                 WHERE p.tenant_id = portal.current_tenant()
                 GROUP BY p.project_code
            )
            SELECT sua.project_code, idx.lan_index,
                   (idx.lan_index IS NOT NULL AND idx.lan_index >= sua.lan_sua) AS in_sync
              FROM sua LEFT JOIN idx USING (project_code)
             ORDER BY sua.project_code
            """
        )
    return [
        {
            "projectCode": r["project_code"],
            "inSync": bool(r["in_sync"]),
            "lastSyncedAt": r["lan_index"].isoformat() if r["lan_index"] else None,
        }
        for r in rows
    ]
```

Thêm `KIND_ENRICH` vào dòng import từ `portal.modules.kb.contracts` ở đầu tệp.

- [ ] **Step 5: Chạy test**

Run: `uv run pytest tests/modules/kb/test_endpoint_sync.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Chạy toàn bộ và kiểm lint**

Run:
```bash
make check
uv run pytest tests/modules/kb/ tests/unit/ -v
```
Expected: xanh. `make test-isolation` vẫn đỏ 13 test — **đó là tình trạng có sẵn trên `develop` do `0908`/`0909`**, không phải do nhánh này.

- [ ] **Step 7: Viết lại `kb/__init__.py`**

```python
"""Ingest tri thức: làm giàu nội dung rồi đánh chỉ mục lên Qdrant.

Hai chặng. `kb_enrich` sinh caption ảnh (VLM) · mô tả video (Gemini) · bóc chữ tệp
(Docling) rồi ghi vào ĐÚNG CỘT người dùng sửa — Aurora là nguồn sự thật. `kb_index`
chạy khi người dùng bấm "Đồng bộ tri thức": chunk → embed → Qdrant.

Đường ra DUY NHẤT của module là embed service (`KB_RAG_URL`). Chunk, point-id, payload,
prompt đều nằm trong repo này — trước 2026-08-10 chúng thuộc một `rag_service` bên
santa-models chưa bao giờ tồn tại.
"""
```

- [ ] **Step 8: Commit**

```bash
git add src/portal/modules/ tests/modules/kb/test_endpoint_sync.py
git commit -m "feat(kb): 4 endpoint đồng bộ tri thức và trạng thái enrich"
```

---

## Self-review

**Spec coverage:**

| Spec | Task |
|---|---|
§5.1 job `kb_enrich` ba nhánh | T10 |
§5.2 luật chỉ-ghi-khi-rỗng + `force` | T10 |
§5.3 VLM · video · Docling · PDF scan → VLM | T6, T7, T8 |
§5.4 `enrich-status` từ `control.jobs` | T12 |
§6.1 nút → một job mở màn | T11, T12 |
§6.2 đường ống, thoát sớm theo hash | T3, T9 |
§6.3 payload giữ hình dạng cũ | T9 (test hợp đồng) |
§6.4 `kb_provision` | T11 |
§7 chỉ báo lệch mức dự án | T12 |
§8.1 `prompts.yaml` + `PROFILE_NAMES` | T2 |
§8.2 `pyyaml` tường minh · `importlib.resources` · test cổng | T1, T2 |
§8.3 quyền `catalog.*` | T12 |
§9 thu hồi caption cũ | T11 |
§10 `to_thread` · `AsyncQdrantClient` · Semaphore | T4, T5, T8 |
§15 kiểm chứng Docling trước tiên | T1 |

**Chưa có task:** `handle_reconcile` — spec §2 để ngoài phạm vi, đúng chủ ý.

**Điểm phải chú ý khi thi công:**
- T9 Step 6 sửa hai dòng rác còn sót trong test — làm đúng bước đó, đừng bỏ qua.
- T10 Step 6 thêm `doc()` vào `ObjectStore` Protocol: phải sửa cả `fake.py` và `storage/object_store.py`, nếu không `FakeObjectStore` không còn thoả Protocol và test cũ đỏ.
- T2 Step 7 có thể kéo theo sửa `directive/profiles.py::extract_profile` — đọc kỹ thông điệp lỗi trước khi sửa.
