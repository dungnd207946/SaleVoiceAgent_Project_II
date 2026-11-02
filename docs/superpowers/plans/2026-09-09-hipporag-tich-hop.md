# HippoRAG Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portal build được graph HippoRAG per-tenant từ chính chunk nó đã ghi vào Qdrant, agent đọc graph đó qua một backend mới; cả hai tắt mặc định và không đổi hành vi nào của pipeline RAG hiện tại.

**Architecture:** Hai nửa tách bạch. Nửa GHI ở `odyssey-portal-backend`: một job riêng (`kb_hippo_build`) gọi LLM bóc triple từ chunk đã có trong Qdrant, dựng graph, ghi `graph.json` + `triple_emb.npz` lên kho tệp dưới `tenants/<id>/hipporag/`. Nửa ĐỌC ở `odyssey-agent`: backend mới `hipporag_kb` lấy seed từ đúng đường `kb_service` đang chạy, chạy Personalized PageRank trên graph tải từ kho tệp, RRF-fuse rồi render bằng chính formatter của `kb_service`.

**Tech Stack:** Python 3.12+, FastAPI/asyncpg (portal), pydantic-settings, httpx, numpy, qdrant-client, boto3 (agent), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-09-09-hipporag-tich-hop-design.md`

## Global Constraints

- **KHÔNG migration, KHÔNG đổi lược đồ DB.** `control.jobs.kind` là `text NOT NULL CHECK (kind <> '')` nên một job kind mới không cần migration.
- **KHÔNG chạy build, KHÔNG bật cờ ở bất kỳ môi trường nào.** Không gọi LLM thật, không ghi kho tệp thật, không `make up`.
- **Frontend không đụng tới.** `odyssey-portal-frontend` không có commit nào trong đợt này.
- **Mọi test phải thuần**: không Docker, không Postgres, không Qdrant, không HTTP ra ngoài. Không dùng fixture `pool`/`api_pool`/`seed_kb`.
- **Không sửa file legacy của package hipporag bên agent**: `adapter.py`, `builder.py`, `expander.py`, `graph.py`, `openie.py`, `triple_index.py` giữ byte-identical. Chỉ THÊM file mới cạnh chúng.
- **Không sửa `CLAUDE.md`** của repo nào — nhiều người cùng sửa, dễ conflict. Nội dung Change Log đề xuất giao lại cho người dùng ở Task 10.
- Định danh trong code là **tiếng Anh**; tiếng Việt chỉ ở comment/docstring và tên test.
- Comment thưa: chỉ viết khi giải thích một quyết định không đọc ra từ code.
- Commit message **tiếng Anh, một dòng**, không `Co-Authored-By`. **Không push** — người dùng tự push.
- Branch: `feat/hippo-rag` ở cả hai repo, đã tạo từ `origin/develop`.
- Cờ mặc định: `KB_HIPPO_ENABLED=false` (portal), `NOBLE_RAG_BACKEND` giữ giá trị đang chạy (agent).

## Bối cảnh bắt buộc đọc trước khi code

**Hợp đồng `graph.json` đến từ repo agent, không phải từ portal.** Người đọc duy nhất là `HippoGraph.from_json()` ở `odyssey-agent/src/noble_agent/agent/rag/hipporag/graph.py`. Hình dạng:

```json
{
  "version": 1,
  "nodes": {
    "passage::<qdrant point id>": {"type": "passage", "label": "<project>", "project": "<project>",
                                   "text": "<chunk text>", "content_hash": "<hash>", "point_id": "<qdrant point id>"},
    "phrase::<tên thực thể đã hạ chữ và gộp khoảng trắng>": {"type": "phrase", "label": "<tên gốc>",
                                   "project": "", "text": "", "content_hash": "", "point_id": ""}
  },
  "edges": [["<khoá a>", "<khoá b>", 1.0]],
  "processed_hashes": ["<hash>"],
  "triples": [{"s": "phrase::…", "o": "phrase::…", "rel": "<quan hệ>",
               "text": "<chủ thể> <quan hệ> <đối tượng>", "passage": "<point id>"}]
}
```

Ba điều `from_json` đòi, sai là im lặng: mỗi cạnh phải là mảng **đúng 3 phần tử** và **cả hai đầu phải có trong `nodes`** (nếu không cạnh bị bỏ); node `passage` phải mang `point_id` (không có thì `passage_key_for_id` trả `None` và seed không vào được graph); khoá `phrase` phải là `"phrase::" + " ".join(name.lower().split())` (lệch một ly là triple seed trỏ vào node không tồn tại).

**Sidecar npz** đọc bởi `triple_index.load_triple_index(graph_path)`, đường dẫn suy từ graph path bằng `os.path.splitext(graph_path)[0] + ".triple_emb.npz"`, và nó đọc đúng ba khoá `s_keys`, `o_keys`, `emb`. Tên khoá lệch → `load` ném → hàm nuốt và trả `None` → sparse seed tắt im lặng.

**CHỈ chunk `status == 'published'` được vào graph — đây là ràng buộc AN NINH, không phải tối ưu.** `build_scope_filter` của agent luôn ép `status == 'published'` và comment ở đó ghi rõ nó là thứ DUY NHẤT còn ngăn nội dung nháp tới khách (Portal ghi point cho cả hàng nháp từ 2026-08-14). Nhưng đường graph trả `text` **lấy từ node graph**, không đi qua Qdrant, nên mệnh đề đó không nhìn thấy nó. Một passage nháp lọt vào graph là nội dung nháp đọc thẳng cho khách.

**Khoá incremental là `(point_id, content_hash)`, KHÔNG phải `content_hash` trần.** `clients/rag.py:132` tính `content_hash = _hash_of(chunks)` — hash của TOÀN BỘ chunk của một record. Builder legacy bên agent dùng `content_hash` làm skip-set nên nối thẳng hai cái là một tài liệu 30 chunk chỉ vào graph 1 chunk, im lặng.

---

### Task 1: Portal — cấu trúc graph (thuần, không I/O)

**Files:**
- Create: `src/portal/modules/kb/hippo/__init__.py`
- Create: `src/portal/modules/kb/hippo/contracts.py`
- Create: `src/portal/modules/kb/hippo/graph.py`
- Test: `tests/modules/kb/test_hippo_graph.py`

**Interfaces:**
- Consumes: không gì (task đầu tiên).
- Produces:
  - `contracts.KIND_HIPPO_BUILD: str = "kb_hippo_build"`
  - `contracts.GRAPH_VERSION: int = 1`
  - `contracts.DUONG_DAN_GRAPH: str = "hipporag/graph.json"`
  - `contracts.DUONG_DAN_TRIPLE: str = "hipporag/triple_emb.npz"`
  - `contracts.TRAN_CHUNK_MOI: int = 500`
  - `contracts.Chunk(point_id: str, project: str, text: str, content_hash: str)` — frozen dataclass
  - `contracts.Triple(s: str, rel: str, o: str)` — frozen dataclass
  - `graph.khoa_phrase(name: str) -> str`
  - `graph.khoa_passage(point_id: str) -> str`
  - `graph.Graph` với `can_boc(chunk) -> bool`, `them_passage(chunk, triples: list[Triple]) -> None`, `xoa_passage(point_id: str) -> None`, `so_passage() -> int`, `so_phrase() -> int`, `point_ids() -> list[str]`, `to_json() -> dict`, `Graph.from_json(d: dict) -> Graph`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_hippo_graph.py`:

```python
"""Graph HippoRAG là cấu trúc thuần — test không cần Docker, DB hay LLM.

Bài quan trọng nhất là `test_ba_chunk_cung_record_ra_ba_passage`: portal băm
`content_hash` theo RECORD, nên một skip-set theo hash sẽ bỏ qua mọi chunk từ thứ
hai của cùng một tài liệu, im lặng. Bài đó đỏ ngay nếu ai đổi khoá incremental.
"""

from portal.modules.kb.hippo.contracts import Chunk, Triple
from portal.modules.kb.hippo.graph import Graph, khoa_passage, khoa_phrase


def _chunk(pid: str, text: str = "noi dung", project: str = "nplb", chash: str = "h1") -> Chunk:
    return Chunk(point_id=pid, project=project, text=text, content_hash=chash)


def test_khoa_phrase_ha_chu_va_gop_khoang_trang():
    assert khoa_phrase("  Noble   Crystal ") == "phrase::noble crystal"
    assert khoa_phrase("NOBLE crystal") == khoa_phrase("noble Crystal")


def test_khoa_passage_mang_nguyen_point_id():
    assert khoa_passage("abc-123") == "passage::abc-123"


def test_ba_chunk_cung_record_ra_ba_passage():
    """Ba chunk của MỘT record mang CÙNG content_hash — cả ba phải vào graph."""
    g = Graph()
    for pid in ("p0", "p1", "p2"):
        c = _chunk(pid, chash="hash-cua-ca-record")
        assert g.can_boc(c), f"{pid} bị coi là đã bóc dù chưa vào graph"
        g.them_passage(c, [Triple(s="Noble Crystal", rel="có", o="bể bơi")])
    assert g.so_passage() == 3
    assert sorted(g.point_ids()) == ["p0", "p1", "p2"]


def test_can_boc_false_khi_point_va_hash_khong_doi():
    g = Graph()
    c = _chunk("p1", chash="h1")
    g.them_passage(c, [])
    assert g.can_boc(c) is False


def test_can_boc_true_khi_hash_doi():
    g = Graph()
    g.them_passage(_chunk("p1", text="cũ", chash="h1"), [])
    assert g.can_boc(_chunk("p1", text="mới", chash="h2")) is True


def test_them_lai_chunk_doi_noi_dung_khong_de_lai_node_cu():
    g = Graph()
    g.them_passage(_chunk("p1", text="cũ", chash="h1"), [Triple(s="A", rel="ở", o="B")])
    g.them_passage(_chunk("p1", text="mới", chash="h2"), [Triple(s="C", rel="ở", o="D")])
    assert g.so_passage() == 1
    assert g.nodes[khoa_passage("p1")]["text"] == "mới"
    assert khoa_phrase("A") not in g.nodes, "phrase của bản cũ còn sót"
    assert khoa_phrase("C") in g.nodes
    assert [t["passage"] for t in g.triples] == ["p1"]


def test_xoa_passage_don_phrase_mo_coi():
    g = Graph()
    g.them_passage(_chunk("p1"), [Triple(s="A", rel="ở", o="B")])
    g.xoa_passage("p1")
    assert g.so_passage() == 0
    assert g.so_phrase() == 0
    assert g.triples == []


def test_phrase_dung_chung_khong_bi_don_khi_con_passage_khac():
    g = Graph()
    g.them_passage(_chunk("p1"), [Triple(s="A", rel="ở", o="B")])
    g.them_passage(_chunk("p2"), [Triple(s="A", rel="có", o="C")])
    g.xoa_passage("p1")
    assert khoa_phrase("A") in g.nodes
    assert khoa_phrase("B") not in g.nodes


def test_to_json_dung_khoa_ma_agent_doc():
    g = Graph()
    g.them_passage(_chunk("p1"), [Triple(s="Noble Crystal", rel="ở", o="Tây Hồ")])
    d = g.to_json()
    assert set(d) == {"version", "nodes", "edges", "processed_hashes", "triples"}
    assert d["version"] == 1
    node = d["nodes"][khoa_passage("p1")]
    assert node["type"] == "passage" and node["point_id"] == "p1"
    assert node["project"] == "nplb" and node["text"] == "noi dung"
    assert all(len(e) == 3 for e in d["edges"]), "from_json bỏ cạnh không đủ 3 phần tử"
    khoa = set(d["nodes"])
    assert all(e[0] in khoa and e[1] in khoa for e in d["edges"]), "from_json bỏ cạnh có đầu lạ"
    tr = d["triples"][0]
    assert set(tr) == {"s", "o", "rel", "text", "passage"}
    assert tr["s"] == khoa_phrase("Noble Crystal") and tr["o"] == khoa_phrase("Tây Hồ")
    assert tr["text"] == "Noble Crystal ở Tây Hồ"


def test_moi_canh_xuat_hien_dung_mot_lan():
    g = Graph()
    g.them_passage(_chunk("p1"), [Triple(s="A", rel="ở", o="B")])
    cap = [tuple(sorted(e[:2])) for e in g.to_json()["edges"]]
    assert len(cap) == len(set(cap))


def test_round_trip_json():
    g = Graph()
    g.them_passage(_chunk("p1"), [Triple(s="A", rel="ở", o="B")])
    g.them_passage(_chunk("p2", chash="h2"), [Triple(s="A", rel="có", o="C")])
    lai = Graph.from_json(g.to_json())
    assert lai.to_json() == g.to_json()


def test_triple_thieu_chu_the_hoac_doi_tuong_khong_sinh_quan_he():
    g = Graph()
    g.them_passage(_chunk("p1"), [Triple(s="A", rel="ở", o="  ")])
    assert g.triples == []
    assert khoa_phrase("A") in g.nodes, "vẫn phải có phrase của phần không rỗng"
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `cd /home/thanhhai/Desktop/odyssey-portal-backend && uv run pytest tests/modules/kb/test_hippo_graph.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.kb.hippo'`

- [ ] **Step 3: Viết `contracts.py`**

Tạo `src/portal/modules/kb/hippo/__init__.py` rỗng và `src/portal/modules/kb/hippo/contracts.py`:

```python
"""Hợp đồng của cổng HippoRAG: job kind, hình dạng chunk/triple, tên artefact.

Format `graph.json` và `triple_emb.npz` là hợp đồng với repo `odyssey-agent` —
xem `docs/contracts/hipporag-graph.md`.
"""

from dataclasses import dataclass

KIND_HIPPO_BUILD = "kb_hippo_build"

GRAPH_VERSION = 1

DUONG_DAN_GRAPH = "hipporag/graph.json"
DUONG_DAN_TRIPLE = "hipporag/triple_emb.npz"

TRAN_CHUNK_MOI = 500
"""Trần chunk đi qua LLM mỗi lượt job. Vượt trần thì phần còn lại để lượt sau —
handler tự xếp tiếp, và mỗi lượt chắc chắn tiến (chunk đã bóc không bóc lại), nên
một tenant 20.000 chunk không giữ một lane worker suốt đêm."""


@dataclass(frozen=True, slots=True)
class Chunk:
    """Một chunk đã nằm trong Qdrant. `point_id` là danh tính; `content_hash` là
    hash theo RECORD nên nhiều chunk chia sẻ cùng giá trị."""

    point_id: str
    project: str
    text: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class Triple:
    s: str
    rel: str
    o: str
```

- [ ] **Step 4: Viết `graph.py`**

Tạo `src/portal/modules/kb/hippo/graph.py`:

```python
"""Graph HippoRAG — cấu trúc thuần, không I/O, không LLM.

Emit ĐÚNG hình dạng `HippoGraph.to_json()` của repo agent; `from_json` bên đó là
người đọc duy nhất. Xem `docs/contracts/hipporag-graph.md`.

Khoá incremental là `(point_id, content_hash)` của CHÍNH chunk đó. Skip-set theo
`content_hash` trần (như builder legacy bên agent) là sai ở portal: hash tính theo
RECORD nên mọi chunk của một tài liệu mang cùng giá trị, và chunk từ thứ hai sẽ bị
bỏ qua im lặng.
"""

from portal.modules.kb.hippo.contracts import GRAPH_VERSION, Chunk, Triple


def khoa_phrase(name: str) -> str:
    return "phrase::" + " ".join((name or "").lower().split())


def khoa_passage(point_id: str) -> str:
    return "passage::" + str(point_id)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.adj: dict[str, dict[str, float]] = {}
        self.processed_hashes: set[str] = set()
        self.triples: list[dict] = []

    def can_boc(self, chunk: Chunk) -> bool:
        """Chunk này cần một lượt gọi LLM: chưa có node, hoặc nội dung đã đổi."""
        node = self.nodes.get(khoa_passage(chunk.point_id))
        if node is None:
            return True
        return str(node.get("content_hash", "")) != chunk.content_hash

    def so_passage(self) -> int:
        return sum(1 for a in self.nodes.values() if a.get("type") == "passage")

    def so_phrase(self) -> int:
        return sum(1 for a in self.nodes.values() if a.get("type") == "phrase")

    def point_ids(self) -> list[str]:
        return [str(a.get("point_id", "")) for a in self.nodes.values() if a.get("type") == "passage"]

    def them_passage(self, chunk: Chunk, triples: list[Triple]) -> None:
        self.xoa_passage(chunk.point_id)
        pkey = khoa_passage(chunk.point_id)
        self._node(
            pkey,
            type="passage",
            label=chunk.project,
            project=chunk.project,
            text=chunk.text,
            content_hash=chunk.content_hash,
            point_id=str(chunk.point_id),
        )
        for tr in triples:
            s, rel, o = tr.s.strip(), tr.rel.strip(), tr.o.strip()
            for ent in (s, o):
                if not ent:
                    continue
                ekey = khoa_phrase(ent)
                self._node(ekey, type="phrase", label=ent, project="", text="", content_hash="", point_id="")
                self._canh(pkey, ekey)
            if s and o:
                self._canh(khoa_phrase(s), khoa_phrase(o))
                self.triples.append(
                    {
                        "s": khoa_phrase(s),
                        "o": khoa_phrase(o),
                        "rel": rel,
                        "text": " ".join(x for x in (s, rel, o) if x),
                        "passage": str(chunk.point_id),
                    }
                )
        if chunk.content_hash:
            self.processed_hashes.add(chunk.content_hash)

    def xoa_passage(self, point_id: str) -> None:
        pkey = khoa_passage(point_id)
        if pkey not in self.nodes:
            return
        self._drop(pkey)
        self.triples = [t for t in self.triples if t.get("passage") != str(point_id)]
        self._don_phrase_mo_coi()

    def to_json(self) -> dict:
        edges: list[list] = []
        da_co: set[tuple[str, str]] = set()
        for a, nbrs in self.adj.items():
            for b, w in nbrs.items():
                cap = (a, b) if a < b else (b, a)
                if cap in da_co:
                    continue
                da_co.add(cap)
                edges.append([cap[0], cap[1], w])
        return {
            "version": GRAPH_VERSION,
            "nodes": {k: dict(v) for k, v in self.nodes.items()},
            "edges": edges,
            "processed_hashes": sorted(self.processed_hashes),
            "triples": list(self.triples),
        }

    @classmethod
    def from_json(cls, d: dict) -> "Graph":
        g = cls()
        for key, attrs in (d.get("nodes") or {}).items():
            g.nodes[key] = dict(attrs)
            g.adj[key] = {}
        for edge in d.get("edges") or []:
            if len(edge) < 3:
                continue
            a, b, w = edge[0], edge[1], float(edge[2])
            if a in g.adj and b in g.adj:
                g.adj[a][b] = w
                g.adj[b][a] = w
        g.processed_hashes = set(d.get("processed_hashes") or [])
        g.triples = list(d.get("triples") or [])
        return g

    def _node(self, key: str, **attrs) -> None:
        if key not in self.nodes:
            self.nodes[key] = attrs
            self.adj[key] = {}

    def _canh(self, a: str, b: str, w: float = 1.0) -> None:
        if a == b:
            return
        self.adj[a][b] = self.adj[a].get(b, 0.0) + w
        self.adj[b][a] = self.adj[b].get(a, 0.0) + w

    def _drop(self, key: str) -> None:
        for nb in list(self.adj.get(key, {})):
            self.adj.get(nb, {}).pop(key, None)
        self.adj.pop(key, None)
        self.nodes.pop(key, None)

    def _don_phrase_mo_coi(self) -> None:
        """Phrase không còn passage nào đỡ thì bỏ. Lặp tới khi ổn định: gỡ một
        phrase có thể làm phrase khác thành chỉ-còn-cạnh-quan-hệ."""
        doi = True
        while doi:
            doi = False
            for key in [k for k, a in self.nodes.items() if a.get("type") == "phrase"]:
                if not any(self.nodes.get(nb, {}).get("type") == "passage" for nb in self.adj.get(key, {})):
                    self._drop(key)
                    doi = True
```

Ghi chú: `processed_hashes` được emit CHỈ để khớp format của agent; portal không dùng nó làm khoá skip (xem docstring). Vì thế `xoa_passage` không `discard` — hai chunk cùng record chia sẻ hash, gỡ hash khi xoá một chunk là nói dối về chunk còn lại.

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/kb/test_hippo_graph.py -q`
Expected: PASS — 12 passed

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/portal/modules/kb/hippo tests/modules/kb/test_hippo_graph.py && uv run ruff format --check src/portal/modules/kb/hippo tests/modules/kb/test_hippo_graph.py`
Expected: không lỗi. `make lint` là HAI lệnh (`ruff check` + `ruff format --check`) — chạy thiếu một cái là báo cáo sai.

- [ ] **Step 7: Commit**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend
git add src/portal/modules/kb/hippo/__init__.py src/portal/modules/kb/hippo/contracts.py src/portal/modules/kb/hippo/graph.py tests/modules/kb/test_hippo_graph.py
git -c user.name="haidt" commit -m "feat(kb): HippoRAG graph structure keyed by chunk point id, not per-record hash"
```

---

### Task 2: Portal — bóc triple bằng LLM

**Files:**
- Create: `src/portal/modules/kb/hippo/openie.py`
- Modify: `src/portal/modules/kb/prompts.yaml` (thêm một profile ở cuối file)
- Test: `tests/modules/kb/test_hippo_openie.py`

**Interfaces:**
- Consumes: `contracts.Triple` (Task 1).
- Produces:
  - `openie.PROFILE: str = "openie_triple"`
  - `openie.TemporaryOpenIEError` (con của `portal.modules.kb.contracts.TemporaryError`)
  - `openie.phan_tich(raw: str) -> list[Triple]`
  - `openie.OpenIEClient(base_url: str, api_key: str)` với `boc(text: str) -> list[Triple]` và `aclose() -> None`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_hippo_openie.py`:

```python
"""Bóc triple: phân tích đầu ra của LLM (hàm thuần) + phân loại lỗi tạm thời.

Không gọi mạng: `OpenIEClient` được tiêm một `httpx.MockTransport`.
"""

import httpx
import pytest

from portal.modules.kb import prompts
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.hippo import openie


def test_profile_openie_ton_tai_va_du_truong():
    spec = prompts.get(openie.PROFILE)
    assert spec.model and spec.prompt
    assert spec.temperature == 0.0, "bóc triple phải tất định"


def test_phan_tich_mang_json():
    ra = openie.phan_tich('[["Noble Crystal", "ở", "Tây Hồ"], ["Noble Crystal", "có", "bể bơi"]]')
    assert [(t.s, t.rel, t.o) for t in ra] == [
        ("Noble Crystal", "ở", "Tây Hồ"),
        ("Noble Crystal", "có", "bể bơi"),
    ]


def test_phan_tich_bo_code_fence():
    raw = '```json\n[["A", "ở", "B"]]\n```'
    assert [(t.s, t.rel, t.o) for t in openie.phan_tich(raw)] == [("A", "ở", "B")]


def test_phan_tich_dang_dict():
    ra = openie.phan_tich('[{"s": "A", "rel": "ở", "o": "B"}]')
    assert [(t.s, t.rel, t.o) for t in ra] == [("A", "ở", "B")]


def test_phan_tich_rac_ra_rong():
    """LLM trả văn xuôi thì ra [] chứ không ném — một chunk không bóc được triple
    vẫn là passage node hợp lệ, và ném ở đây là để một câu trả lời xấu giết cả lượt build."""
    assert openie.phan_tich("Tôi không tìm thấy quan hệ nào.") == []
    assert openie.phan_tich("") == []
    assert openie.phan_tich('{"khong": "phai mang"}') == []


def test_phan_tich_bo_muc_thieu_chu_the_hoac_doi_tuong():
    assert openie.phan_tich('[["", "ở", "B"], ["A", "ở", ""], ["A", "ở", "B"]]') == [
        openie.Triple(s="A", rel="ở", o="B")
    ]


def _client(handler) -> openie.OpenIEClient:
    c = openie.OpenIEClient(base_url="http://vlm.test", api_key="k")
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


async def test_boc_tra_triple():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '[["A", "ở", "B"]]'}}]},
        )

    c = _client(handler)
    try:
        assert [(t.s, t.rel, t.o) for t in await c.boc("đoạn văn")] == [("A", "ở", "B")]
    finally:
        await c.aclose()


async def test_boc_text_rong_khong_goi_mang():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng cho text rỗng")

    c = _client(handler)
    try:
        assert await c.boc("   ") == []
    finally:
        await c.aclose()


@pytest.mark.parametrize("code", [429, 500, 503])
async def test_429_va_5xx_nem_temporary(code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, text="nghẽn")

    c = _client(handler)
    try:
        with pytest.raises(TemporaryError):
            await c.boc("đoạn văn")
    finally:
        await c.aclose()


async def test_timeout_nem_temporary():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("quá lâu")

    c = _client(handler)
    try:
        with pytest.raises(TemporaryError):
            await c.boc("đoạn văn")
    finally:
        await c.aclose()


async def test_400_nem_ngay_khong_phai_temporary():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="model sai")

    c = _client(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await c.boc("đoạn văn")
    finally:
        await c.aclose()


async def test_response_thieu_choices_nem_value_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"khong": "co choices"})

    c = _client(handler)
    try:
        with pytest.raises(ValueError):
            await c.boc("đoạn văn")
    finally:
        await c.aclose()
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/kb/test_hippo_openie.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.kb.hippo.openie'`

- [ ] **Step 3: Thêm profile vào `prompts.yaml`**

Thêm vào CUỐI `src/portal/modules/kb/prompts.yaml`:

```yaml

openie_triple:
  model: qwen-plus
  max_tokens: 1024
  temperature: 0.0
  prompt: |
    Bóc các quan hệ trong đoạn văn dưới đây thành danh sách triple.
    Mỗi triple là ["chủ thể", "quan hệ", "đối tượng"]: chủ thể và đối tượng là thực thể có
    tên (dự án, phân khu, địa danh, tiện ích, loại sản phẩm, chính sách, mốc thời gian),
    quan hệ là một cụm động từ ngắn.
    Chỉ bóc quan hệ nói THẲNG trong đoạn. Không suy diễn, không thêm kiến thức ngoài đoạn.
    Giữ nguyên dấu tiếng Việt và cách viết tên riêng đúng như trong đoạn.
    Trả về DUY NHẤT một mảng JSON. Không giải thích, không bọc code fence.
    Không có quan hệ nào thì trả về [].
```

`model: qwen-plus` là model CHỮ của DashScope, khác `qwen-vl-max` mà `caption`/`ocr_markdown` dùng — OpenIE không có ảnh. Tên model này phải được đối chiếu với tài khoản DashScope thật trước lần đầu bật cờ; nó đã nằm trong bảng nợ của spec.

- [ ] **Step 4: Viết `openie.py`**

Tạo `src/portal/modules/kb/hippo/openie.py`:

```python
"""Bóc triple bằng LLM — BUILD-TIME, không nằm trên đường người dùng chờ.

Cùng giao thức OpenAI-compatible `/chat/completions` mà `clients/vlm.py` dùng;
khác ở chỗ payload chỉ có chữ.
"""

import json
import logging

import httpx

from portal.modules.kb import prompts, settings
from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.hippo.contracts import Triple

log = logging.getLogger(__name__)

PROFILE = "openie_triple"


class TemporaryOpenIEError(TemporaryError):
    """429/5xx/timeout — job phải thử lại. Nuốt nghĩa là ghi ra một graph thiếu
    chunk mà không ai biết là nó thiếu."""


def _bo_fence(text: str) -> str:
    dong = text.strip().split("\n")
    if dong and dong[0].lstrip().startswith("```"):
        dong = dong[1:]
    if dong and dong[-1].strip().startswith("```"):
        dong = dong[:-1]
    return "\n".join(dong).strip()


def phan_tich(raw: str) -> list[Triple]:
    """Đầu ra LLM -> list[Triple]. Rác thì ra `[]` chứ không ném: một chunk không
    bóc được triple vẫn vào graph như một passage node hợp lệ, chỉ là không có
    phrase nào; ném ở đây là để một câu trả lời xấu của LLM giết cả lượt build."""
    text = _bo_fence(raw or "")
    if not text:
        return []
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    ra: list[Triple] = []
    for muc in data:
        if isinstance(muc, list | tuple) and len(muc) >= 3:
            s, rel, o = str(muc[0]).strip(), str(muc[1]).strip(), str(muc[2]).strip()
        elif isinstance(muc, dict):
            s = str(muc.get("s", "")).strip()
            rel = str(muc.get("rel", "")).strip()
            o = str(muc.get("o", "")).strip()
        else:
            continue
        if s and o:
            ra.append(Triple(s=s, rel=rel, o=o))
    return ra


class OpenIEClient:
    def __init__(self, *, base_url: str, api_key: str) -> None:
        if not api_key:
            raise ValueError("thiếu KB_VLM_API_KEY — không gửi request không auth")
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def boc(self, text: str) -> list[Triple]:
        text = (text or "").strip()
        if not text:
            return []
        spec = prompts.get(PROFILE)
        try:
            r = await self._http.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": spec.model,
                    "max_tokens": spec.max_tokens,
                    "temperature": spec.temperature,
                    "messages": [{"role": "user", "content": f"{spec.prompt}\n\n---\n{text}"}],
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TemporaryOpenIEError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise TemporaryOpenIEError(f"OpenIE {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        try:
            content = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"response OpenIE thiếu choices/message/content: {r.text[:200]}") from exc
        return phan_tich(str(content))
```

Thêm re-export để test dùng `openie.Triple`: thêm dòng `Triple = Triple` là dư — thay vào đó test import `Triple` từ `openie` nhờ chính câu `from ... import Triple` ở đầu file, đã có.

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/kb/test_hippo_openie.py tests/modules/kb/test_prompts.py -q`
Expected: PASS. Chạy kèm `test_prompts.py` vì profile mới phải qua được cổng `test_moi_profile_co_du_truong` của file đó.

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/portal/modules/kb/hippo tests/modules/kb/test_hippo_openie.py && uv run ruff format --check src/portal/modules/kb/hippo tests/modules/kb/test_hippo_openie.py`
Expected: không lỗi

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/kb/hippo/openie.py src/portal/modules/kb/prompts.yaml tests/modules/kb/test_hippo_openie.py
git -c user.name="haidt" commit -m "feat(kb): OpenIE triple extraction over the existing chat-completions surface"
```

---

### Task 3: Portal — artefact trên kho tệp + hợp đồng cho repo agent

**Files:**
- Create: `src/portal/modules/kb/hippo/artefact.py`
- Create: `docs/contracts/hipporag-graph.md`
- Test: `tests/modules/kb/test_hippo_artefact.py`

**Interfaces:**
- Consumes: `contracts.DUONG_DAN_GRAPH`, `contracts.DUONG_DAN_TRIPLE` (Task 1); `graph.Graph` (Task 1).
- Produces:
  - `artefact.graph_bytes(g: Graph) -> bytes`
  - `artefact.triple_npz_bytes(s_keys: list[str], o_keys: list[str], emb: list[list[float]]) -> bytes`
  - `artefact.doc_graph(store, *, tenant_id: str) -> Graph`
  - `artefact.ghi(store, *, tenant_id: str, graph: Graph, s_keys: list[str], o_keys: list[str], emb: list[list[float]]) -> None`
  - `store` là bất kỳ đối tượng có `key(*, tenant_id, path) -> str`, `put(*, key, data, content_type)`, `doc(*, key) -> bytes` — tức `kb.storage.object_store.S3Store`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_hippo_artefact.py`:

```python
"""Artefact HippoRAG: serialize + đọc lại. Kho tệp là một fake trong bộ nhớ —
không S3, không MinIO, không mạng.
"""

import io
import json

import numpy as np
import pytest

from portal.core.storage import KhongTimThay
from portal.modules.kb.hippo import artefact
from portal.modules.kb.hippo.contracts import DUONG_DAN_GRAPH, DUONG_DAN_TRIPLE, Chunk, Triple
from portal.modules.kb.hippo.graph import Graph, khoa_phrase


class KhoGia:
    def __init__(self) -> None:
        self.doi_tuong: dict[str, bytes] = {}
        self.thu_tu_ghi: list[str] = []

    def key(self, *, tenant_id: str, path: str) -> str:
        return f"tenants/{tenant_id}/{path}"

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.doi_tuong[key] = data
        self.thu_tu_ghi.append(key)
        return f"https://kho.test/{key}"

    async def doc(self, *, key: str) -> bytes:
        if key not in self.doi_tuong:
            raise KhongTimThay(key)
        return self.doi_tuong[key]


def _graph() -> Graph:
    g = Graph()
    g.them_passage(
        Chunk(point_id="p1", project="nplb", text="Noble Crystal ở Tây Hồ", content_hash="h1"),
        [Triple(s="Noble Crystal", rel="ở", o="Tây Hồ")],
    )
    return g


async def test_doc_graph_chua_tung_build_ra_graph_rong():
    """Lượt build đầu của một tenant là đường THƯỜNG, không phải lỗi."""
    g = await artefact.doc_graph(KhoGia(), tenant_id="t1")
    assert g.so_passage() == 0


async def test_doc_graph_json_hong_ra_graph_rong():
    kho = KhoGia()
    kho.doi_tuong[kho.key(tenant_id="t1", path=DUONG_DAN_GRAPH)] = b"{ khong phai json"
    g = await artefact.doc_graph(kho, tenant_id="t1")
    assert g.so_passage() == 0


async def test_round_trip_ghi_roi_doc():
    kho = KhoGia()
    g = _graph()
    await artefact.ghi(kho, tenant_id="t1", graph=g, s_keys=[], o_keys=[], emb=[])
    lai = await artefact.doc_graph(kho, tenant_id="t1")
    assert lai.to_json() == g.to_json()


async def test_ghi_dung_hai_khoa_duoi_tien_to_tenant():
    kho = KhoGia()
    await artefact.ghi(kho, tenant_id="t1", graph=_graph(), s_keys=[], o_keys=[], emb=[])
    assert set(kho.doi_tuong) == {
        "tenants/t1/hipporag/graph.json",
        "tenants/t1/hipporag/triple_emb.npz",
    }


async def test_ghi_npz_truoc_graph_sau():
    """Nửa-hỏng theo chiều này để lại graph CŨ + npz MỚI: triple trỏ vào phrase key
    có thể không còn, và `expander.expand` bên agent lọc `k in graph.nodes` nên nó
    chỉ mất seed. Chiều ngược lại để lại graph MỚI + npz CŨ: mọi khoá cũ đều tồn tại
    trong graph mới nên seed vào ĐÚNG node nhưng SAI ngữ nghĩa — hỏng im lặng.
    """
    kho = KhoGia()
    await artefact.ghi(kho, tenant_id="t1", graph=_graph(), s_keys=["a"], o_keys=["b"], emb=[[1.0, 0.0]])
    assert kho.thu_tu_ghi == [
        "tenants/t1/hipporag/triple_emb.npz",
        "tenants/t1/hipporag/graph.json",
    ]


def test_npz_dung_ba_khoa_agent_doc():
    """`triple_index.load_triple_index()` bên agent đọc đúng `s_keys`/`o_keys`/`emb`.
    Tên khoá lệch → nó ném → nuốt → sparse seed tắt im lặng."""
    raw = artefact.triple_npz_bytes(
        [khoa_phrase("Noble Crystal")], [khoa_phrase("Tây Hồ")], [[1.0, 0.0, 0.0]]
    )
    d = np.load(io.BytesIO(raw), allow_pickle=True)
    assert set(d.files) == {"s_keys", "o_keys", "emb"}
    assert [str(k) for k in d["s_keys"]] == ["phrase::noble crystal"]
    assert [str(k) for k in d["o_keys"]] == ["phrase::tây hồ"]
    assert d["emb"].dtype == np.float32 and d["emb"].shape == (1, 3)


def test_graph_bytes_la_utf8_khong_escape():
    """`ensure_ascii=False` — tên tiếng Việt escape ra `\\u1ea1` thì graph phình lên
    và mọi lượt debug bằng mắt trở nên vô dụng."""
    raw = artefact.graph_bytes(_graph())
    assert "Tây Hồ" in raw.decode("utf-8")
    assert json.loads(raw.decode("utf-8"))["version"] == 1


@pytest.mark.parametrize("emb", [[], [[]]])
def test_npz_emb_rong_khong_ne(emb):
    artefact.triple_npz_bytes([], [], emb)
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/kb/test_hippo_artefact.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.kb.hippo.artefact'`

- [ ] **Step 3: Viết `artefact.py`**

Tạo `src/portal/modules/kb/hippo/artefact.py`:

```python
"""Đọc/ghi artefact HippoRAG trên kho tệp: `tenants/<id>/hipporag/`.

`graph.json` là hợp đồng với repo agent; `triple_emb.npz` là sidecar embedding
triple, khớp THỨ TỰ của `graph["triples"]`. Xem `docs/contracts/hipporag-graph.md`.
"""

import io
import json
import logging

import numpy as np

from portal.core.storage import KhongTimThay
from portal.modules.kb.hippo.contracts import DUONG_DAN_GRAPH, DUONG_DAN_TRIPLE
from portal.modules.kb.hippo.graph import Graph

log = logging.getLogger(__name__)


def graph_bytes(g: Graph) -> bytes:
    return json.dumps(g.to_json(), ensure_ascii=False).encode("utf-8")


def triple_npz_bytes(s_keys: list[str], o_keys: list[str], emb: list[list[float]]) -> bytes:
    """Ba mảng mà `triple_index.load_triple_index()` bên agent đọc. Tên khoá lệch là
    sidecar bị bỏ qua im lặng (hàm bên đó nuốt exception và trả None)."""
    buf = io.BytesIO()
    np.savez(
        buf,
        s_keys=np.array(s_keys, dtype=object),
        o_keys=np.array(o_keys, dtype=object),
        emb=np.asarray(emb, dtype=np.float32),
    )
    return buf.getvalue()


async def doc_graph(store, *, tenant_id: str) -> Graph:
    """Graph hiện có, hoặc một graph RỖNG khi chưa từng build."""
    key = store.key(tenant_id=tenant_id, path=DUONG_DAN_GRAPH)
    try:
        raw = await store.doc(key=key)
    except KhongTimThay:
        return Graph()
    try:
        return Graph.from_json(json.loads(raw.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("hippo: graph của %s không đọc được (%s) — build lại từ đầu", tenant_id, exc)
        return Graph()


async def ghi(
    store,
    *,
    tenant_id: str,
    graph: Graph,
    s_keys: list[str],
    o_keys: list[str],
    emb: list[list[float]],
) -> None:
    """npz TRƯỚC, graph SAU — chiều nửa-hỏng ít hại hơn. Xem
    `test_ghi_npz_truoc_graph_sau` để biết vì sao chiều ngược lại hỏng im lặng."""
    await store.put(
        key=store.key(tenant_id=tenant_id, path=DUONG_DAN_TRIPLE),
        data=triple_npz_bytes(s_keys, o_keys, emb),
        content_type="application/octet-stream",
    )
    await store.put(
        key=store.key(tenant_id=tenant_id, path=DUONG_DAN_GRAPH),
        data=graph_bytes(graph),
        content_type="application/json",
    )
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/kb/test_hippo_artefact.py -q`
Expected: PASS — 9 passed

- [ ] **Step 5: Viết hợp đồng cho repo agent**

Tạo `docs/contracts/hipporag-graph.md`:

```markdown
# Artefact HippoRAG — hợp đồng portal ghi / agent đọc

Portal (`modules/kb/hippo/`) GHI; `odyssey-agent` (`agent/rag/hipporag/`) ĐỌC.
Chép tay như mọi thứ trong `contracts/` — không job CI nào so hai bên.

## Vị trí

Kho tệp của portal, dưới tiền tố tenant:

- `tenants/<tenant_id>/hipporag/graph.json`
- `tenants/<tenant_id>/hipporag/triple_emb.npz`

Agent tải hai object này về cache cục bộ. Tên tệp cục bộ PHẢI để npz là
`<stem của graph>.triple_emb.npz` — `triple_index.triple_emb_path()` suy đường dẫn
sidecar từ đường dẫn graph, nên đặt tên khác là sidecar không bao giờ được tìm thấy.

## `graph.json`

```json
{
  "version": 1,
  "nodes": {
    "passage::<qdrant point id>": {
      "type": "passage", "label": "<mã dự án>", "project": "<mã dự án>",
      "text": "<chữ của chunk>", "content_hash": "<hash theo record>",
      "point_id": "<qdrant point id>"
    },
    "phrase::<tên thực thể, hạ chữ, gộp khoảng trắng>": {
      "type": "phrase", "label": "<tên như trong văn bản>",
      "project": "", "text": "", "content_hash": "", "point_id": ""
    }
  },
  "edges": [["<khoá a>", "<khoá b>", 1.0]],
  "processed_hashes": ["<hash>"],
  "triples": [
    {"s": "phrase::…", "o": "phrase::…", "rel": "<quan hệ>",
     "text": "<chủ thể> <quan hệ> <đối tượng>", "passage": "<point id>"}
  ]
}
```

Bốn ràng buộc, sai là hỏng im lặng:

1. Mỗi cạnh là mảng **ít nhất 3 phần tử** `[a, b, weight]`, và **cả hai đầu phải có
   trong `nodes`** — `from_json` bỏ cạnh không thoả, không báo gì.
2. Node `passage` phải mang `point_id`. Thiếu thì `passage_key_for_id()` trả `None`,
   seed không vào được graph, và backend degrade về hybrid mà không lỗi nào.
3. Khoá `phrase` phải là `"phrase::" + " ".join(name.lower().split())`. Lệch một ly
   là triple seed trỏ vào node không tồn tại và bị lọc bỏ.
4. Cạnh lưu **một lần** mỗi cặp (a < b). Trọng số là số lần đồng xuất hiện.

`processed_hashes` được emit chỉ để khớp format; portal KHÔNG dùng nó làm khoá
incremental (hash tính theo record nên mọi chunk của một tài liệu chia sẻ giá trị).
Khoá thật của portal là `(point_id, content_hash)` đọc từ chính node passage.

**Chỉ chunk `status == 'published'` vào graph.** Đây là ràng buộc AN NINH: filter
`status == 'published'` của `build_scope_filter` là thứ duy nhất ngăn nội dung nháp
tới khách, nhưng đường graph trả `text` từ node graph nên nó không đi qua filter đó.

## `triple_emb.npz`

Ba mảng, `np.savez`:

- `s_keys`: `object`, khoá phrase của chủ thể, một phần tử mỗi triple.
- `o_keys`: `object`, khoá phrase của đối tượng, cùng thứ tự.
- `emb`: `float32`, `(số triple, số chiều)`, embedding của `triples[i]["text"]`.

Thứ tự ba mảng khớp **thứ tự `graph["triples"]`**.

**Embedding phải cùng vector space với thứ agent embed câu hỏi bằng.** Portal embed
`side="index"` qua `KB_EMBED_URL`; agent embed câu hỏi `side="query"`. Khác model là
Qdrant/cosine trả nhiễu không lỗi nào (đo được bên agent: E5 query trên collection
E5 ~0.82, Gemini query trên cùng collection ~0.03).

## Chế độ degrade

| Tình huống | Hành vi mong đợi bên agent |
|---|---|
Không có `graph.json` | Trả đúng kết quả `kb_service`
Có graph, không có npz | PPR chạy với seed passage; sparse triple-seed tắt
Graph cũ hơn Qdrant | Passage có trong hybrid hit dùng chữ MỚI từ Qdrant; passage chỉ có trong graph dùng chữ SNAPSHOT
`emb` rỗng | Sparse triple-seed tắt
```

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/portal/modules/kb/hippo tests/modules/kb/test_hippo_artefact.py && uv run ruff format --check src/portal/modules/kb/hippo tests/modules/kb/test_hippo_artefact.py`
Expected: không lỗi

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/kb/hippo/artefact.py docs/contracts/hipporag-graph.md tests/modules/kb/test_hippo_artefact.py
git -c user.name="haidt" commit -m "feat(kb): persist the HippoRAG artefacts under the tenant prefix and write the cross-repo contract"
```

---

### Task 4: Portal — một lượt build (đọc chunk, bóc, gộp, ghi)

**Files:**
- Create: `src/portal/modules/kb/hippo/build.py`
- Modify: `src/portal/modules/kb/index/store.py` (THÊM một method, không sửa method nào)
- Test: `tests/modules/kb/test_hippo_build.py`

**Interfaces:**
- Consumes: `contracts.{Chunk, Triple, TRAN_CHUNK_MOI}`, `graph.Graph`, `openie.OpenIEClient.boc`, `artefact.{doc_graph, ghi}` (Task 1-3).
- Produces:
  - `build.chunks_tu_payload(rows: list[tuple[str, dict]]) -> list[Chunk]`
  - `build.KetQua(passage: int, phrase: int, triple: int, boc: int, con_lai: int)` — frozen dataclass
  - `build.chay_mot_luot(*, tenant_id: str, collection: str, store, kho, openie, embed, renew: bool = False) -> KetQua`
    - `store` = `QdrantStore` (cần `scroll_payloads`), `kho` = `S3Store`, `openie` cần `boc(text) -> list[Triple]`, `embed` cần `dense(texts) -> list[list[float]]`
  - `QdrantStore.scroll_payloads(name: str, *, anchor_code: str = "") -> list[tuple[str, dict]]`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_hippo_build.py`:

```python
"""Một lượt build: chọn chunk, bóc, gộp, ghi. Mọi phụ thuộc là fake — không
Qdrant, không LLM, không S3.

Bài `test_chunk_khong_published_khong_vao_graph` là bài AN NINH của module: filter
`status == 'published'` của agent nằm ở Qdrant, còn đường graph trả chữ từ node
graph nên nó không đi qua filter đó. Một passage nháp trong graph là nội dung nháp
đọc thẳng cho khách.
"""

import numpy as np
import pytest

from portal.core.storage import KhongTimThay
from portal.modules.kb.hippo import build
from portal.modules.kb.hippo.contracts import DUONG_DAN_GRAPH, TRAN_CHUNK_MOI, Triple
from portal.modules.kb.hippo.graph import Graph, khoa_passage


def _row(pid: str, *, text: str = "Noble Crystal ở Tây Hồ", status: str = "published",
         project: str = "nplb", chash: str = "h1") -> tuple[str, dict]:
    return pid, {"text": text, "status": status, "project_id": project, "content_hash": chash}


class StoreGia:
    def __init__(self, rows: list[tuple[str, dict]]) -> None:
        self._rows = rows
        self.so_lan_scroll = 0

    async def scroll_payloads(self, name: str, *, anchor_code: str = "") -> list[tuple[str, dict]]:
        self.so_lan_scroll += 1
        return list(self._rows)


class KhoGia:
    def __init__(self) -> None:
        self.doi_tuong: dict[str, bytes] = {}

    def key(self, *, tenant_id: str, path: str) -> str:
        return f"tenants/{tenant_id}/{path}"

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        self.doi_tuong[key] = data
        return ""

    async def doc(self, *, key: str) -> bytes:
        if key not in self.doi_tuong:
            raise KhongTimThay(key)
        return self.doi_tuong[key]


class OpenIEGia:
    def __init__(self, triples: list[Triple] | None = None) -> None:
        self.triples = triples if triples is not None else [Triple(s="Noble Crystal", rel="ở", o="Tây Hồ")]
        self.da_goi: list[str] = []

    async def boc(self, text: str) -> list[Triple]:
        self.da_goi.append(text)
        return list(self.triples)


class EmbedGia:
    def __init__(self, chieu: int = 4) -> None:
        self.chieu = chieu
        self.da_goi: list[list[str]] = []

    async def dense(self, texts: list[str]) -> list[list[float]]:
        self.da_goi.append(list(texts))
        return [[float(i + 1)] * self.chieu for i in range(len(texts))]


async def _chay(rows, *, kho=None, openie=None, embed=None, renew=False):
    kho = kho or KhoGia()
    openie = openie or OpenIEGia()
    embed = embed or EmbedGia()
    kq = await build.chay_mot_luot(
        tenant_id="t1",
        collection="t1_documents",
        store=StoreGia(rows),
        kho=kho,
        openie=openie,
        embed=embed,
        renew=renew,
    )
    return kq, kho, openie, embed


def _graph_da_ghi(kho: KhoGia) -> Graph:
    import json

    raw = kho.doi_tuong[kho.key(tenant_id="t1", path=DUONG_DAN_GRAPH)]
    return Graph.from_json(json.loads(raw.decode("utf-8")))


def test_chunks_tu_payload_bo_chunk_khong_published():
    rows = [_row("p1"), _row("p2", status="draft"), _row("p3", status="archived")]
    assert [c.point_id for c in build.chunks_tu_payload(rows)] == ["p1"]


def test_chunks_tu_payload_bo_chunk_rong_chu():
    assert build.chunks_tu_payload([_row("p1", text="   ")]) == []


def test_chunks_tu_payload_thieu_status_bi_bo():
    """Fail-closed, cùng chiều với `build_scope_filter` bên agent: point thiếu khoá
    `status` không khớp `== 'published'` nên nó bị ẩn ở đường Qdrant. Graph phải
    ẩn nó theo, không thì graph rộng hơn Qdrant."""
    assert build.chunks_tu_payload([("p1", {"text": "abc", "project_id": "nplb"})]) == []


async def test_chunk_khong_published_khong_vao_graph():
    _kq, kho, _oie, _emb = await _chay([_row("p1"), _row("p2", status="draft", text="NỘI DUNG NHÁP")])
    g = _graph_da_ghi(kho)
    assert g.point_ids() == ["p1"]
    assert "NỘI DUNG NHÁP" not in str(g.to_json())


async def test_ba_chunk_cung_content_hash_deu_duoc_boc():
    rows = [_row(pid, chash="hash-record") for pid in ("p0", "p1", "p2")]
    kq, kho, oie, _emb = await _chay(rows)
    assert len(oie.da_goi) == 3
    assert kq.passage == 3
    assert sorted(_graph_da_ghi(kho).point_ids()) == ["p0", "p1", "p2"]


async def test_luot_hai_khong_goi_lai_llm():
    rows = [_row("p1")]
    _kq, kho, _oie, _emb = await _chay(rows)
    kq2, _kho2, oie2, _emb2 = await _chay(rows, kho=kho)
    assert oie2.da_goi == []
    assert kq2.boc == 0 and kq2.passage == 1


async def test_chunk_doi_noi_dung_duoc_boc_lai():
    _kq, kho, _oie, _emb = await _chay([_row("p1", text="cũ", chash="h1")])
    kq2, kho2, oie2, _emb2 = await _chay([_row("p1", text="mới", chash="h2")], kho=kho)
    assert oie2.da_goi == ["mới"]
    assert kq2.boc == 1
    assert _graph_da_ghi(kho2).nodes[khoa_passage("p1")]["text"] == "mới"


async def test_chunk_bien_mat_bi_go_khoi_graph():
    """Gỡ khi rời published là bắt buộc: không gỡ thì một tài liệu bị chuyển về nháp
    vẫn nằm trong graph và PPR vẫn đọc chữ của nó cho khách."""
    _kq, kho, _oie, _emb = await _chay([_row("p1"), _row("p2")])
    kq2, kho2, _oie2, _emb2 = await _chay([_row("p1")], kho=kho)
    assert _graph_da_ghi(kho2).point_ids() == ["p1"]
    assert kq2.passage == 1


async def test_chunk_chuyen_sang_nhap_bi_go():
    _kq, kho, _oie, _emb = await _chay([_row("p1"), _row("p2")])
    _kq2, kho2, _oie2, _emb2 = await _chay([_row("p1"), _row("p2", status="draft")], kho=kho)
    assert _graph_da_ghi(kho2).point_ids() == ["p1"]


async def test_renew_boc_lai_tat_ca():
    rows = [_row("p1")]
    _kq, kho, _oie, _emb = await _chay(rows)
    kq2, _kho2, oie2, _emb2 = await _chay(rows, kho=kho, renew=True)
    assert oie2.da_goi == ["Noble Crystal ở Tây Hồ"]
    assert kq2.boc == 1


async def test_tran_chunk_moi_va_con_lai():
    rows = [_row(f"p{i}", chash=f"h{i}") for i in range(TRAN_CHUNK_MOI + 3)]
    kq, _kho, oie, _emb = await _chay(rows)
    assert len(oie.da_goi) == TRAN_CHUNK_MOI
    assert kq.boc == TRAN_CHUNK_MOI
    assert kq.con_lai == 3


async def test_embed_dung_thu_tu_triple_cua_graph():
    rows = [_row("p1"), _row("p2", chash="h2")]
    _kq, kho, _oie, emb = await _chay(rows)
    g = _graph_da_ghi(kho)
    assert emb.da_goi == [[t["text"] for t in g.triples]]


async def test_npz_ghi_dung_so_triple():
    import io

    rows = [_row("p1")]
    _kq, kho, _oie, _emb = await _chay(rows)
    from portal.modules.kb.hippo.contracts import DUONG_DAN_TRIPLE

    raw = kho.doi_tuong[kho.key(tenant_id="t1", path=DUONG_DAN_TRIPLE)]
    d = np.load(io.BytesIO(raw), allow_pickle=True)
    g = _graph_da_ghi(kho)
    assert d["emb"].shape[0] == len(g.triples) == 1
    assert [str(k) for k in d["s_keys"]] == [t["s"] for t in g.triples]


async def test_khong_co_triple_thi_khong_goi_embed():
    rows = [_row("p1")]
    _kq, _kho, _oie, emb = await _chay(rows, openie=OpenIEGia(triples=[]))
    assert emb.da_goi == []


async def test_collection_rong_van_ghi_graph_rong():
    """Tenant chưa nạp gì: vẫn ghi artefact rỗng thay vì không ghi gì. Không ghi
    nghĩa là agent tiếp tục đọc graph CŨ của một tenant vừa bị xoá sạch dữ liệu."""
    kq, kho, _oie, _emb = await _chay([])
    assert kq.passage == 0
    assert kho.key(tenant_id="t1", path=DUONG_DAN_GRAPH) in kho.doi_tuong


async def test_openie_nem_thi_lan_ra():
    class OpenIENem:
        async def boc(self, text: str):
            raise RuntimeError("LLM chết")

    with pytest.raises(RuntimeError):
        await _chay([_row("p1")], openie=OpenIENem())
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/kb/test_hippo_build.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.kb.hippo.build'`

- [ ] **Step 3: Thêm `scroll_payloads` vào `QdrantStore`**

Trong `src/portal/modules/kb/index/store.py`, thêm method này NGAY SAU `scroll_points` (kết thúc quanh dòng 263). Không sửa `scroll_points` — đường reconcile đang dựa vào đúng hình dạng hẹp của nó.

```python
    async def scroll_payloads(self, name: str, *, anchor_code: str = "") -> list[tuple[str, dict]]:
        """`(point_id, payload)` với payload ĐẦY ĐỦ. `anchor_code=""` = cả collection.

        Khác `scroll_points`: hàm đó rút payload xuống bốn trường cho reconcile, nên
        `text`/`project_id`/`status` mất — cổng nạp HippoRAG cần cả ba.
        """
        if not await self._c.collection_exists(name):
            return []
        loc = (
            models.Filter(must=[models.FieldCondition(key="project_id", match=models.MatchValue(value=anchor_code))])
            if anchor_code
            else None
        )
        ra: list[tuple[str, dict]] = []
        offset = None
        while True:
            batch, offset = await self._c.scroll(
                name, scroll_filter=loc, limit=256, offset=offset, with_payload=True, with_vectors=False
            )
            ra.extend((str(p.id), dict(p.payload or {})) for p in batch)
            if offset is None:
                return ra
```

- [ ] **Step 4: Viết `build.py`**

Tạo `src/portal/modules/kb/hippo/build.py`:

```python
"""Một lượt build graph cho một tenant. Phụ thuộc TIÊM VÀO — test không cần
Qdrant, LLM hay S3.

Nguồn chunk là chính collection Qdrant mà pipeline hiện tại đã ghi: HippoRAG dùng
lại nguyên chunk đó, không chunk lại.
"""

import logging
from dataclasses import dataclass

from portal.modules.kb.hippo import artefact
from portal.modules.kb.hippo.contracts import TRAN_CHUNK_MOI, Chunk
from portal.modules.kb.hippo.graph import Graph

log = logging.getLogger(__name__)

TRANG_THAI_VAO_GRAPH = "published"


@dataclass(frozen=True, slots=True)
class KetQua:
    passage: int
    phrase: int
    triple: int
    boc: int
    con_lai: int


def chunks_tu_payload(rows: list[tuple[str, dict]]) -> list[Chunk]:
    """Chỉ chunk `status == 'published'` có chữ.

    ⚠️ RÀNG BUỘC AN NINH, không phải tối ưu. `build_scope_filter` bên agent luôn ép
    `status == 'published'` và comment ở đó ghi rõ nó là thứ DUY NHẤT còn ngăn nội
    dung nháp tới khách. Nhưng đường graph trả `text` lấy từ NODE GRAPH, không qua
    Qdrant, nên mệnh đề đó không nhìn thấy nó. So `==` chứ không `!=` để point thiếu
    khoá `status` cũng bị ẩn — cùng chiều fail-closed với bên agent.
    """
    ra: list[Chunk] = []
    for point_id, pl in rows:
        if str(pl.get("status", "")) != TRANG_THAI_VAO_GRAPH:
            continue
        text = str(pl.get("text") or "").strip()
        if not text:
            continue
        ra.append(
            Chunk(
                point_id=str(point_id),
                project=str(pl.get("project_id") or ""),
                text=text,
                content_hash=str(pl.get("content_hash") or ""),
            )
        )
    return ra


async def chay_mot_luot(
    *,
    tenant_id: str,
    collection: str,
    store,
    kho,
    openie,
    embed,
    renew: bool = False,
) -> KetQua:
    rows = await store.scroll_payloads(collection)
    published = chunks_tu_payload(rows)
    graph = Graph() if renew else await artefact.doc_graph(kho, tenant_id=tenant_id)

    con_song = {c.point_id for c in published}
    for pid in [p for p in graph.point_ids() if p not in con_song]:
        graph.xoa_passage(pid)

    can_boc = [c for c in published if graph.can_boc(c)]
    lo = can_boc[:TRAN_CHUNK_MOI]
    for c in lo:
        graph.them_passage(c, await openie.boc(c.text))

    texts = [t["text"] for t in graph.triples]
    emb = await embed.dense(texts) if texts else []

    await artefact.ghi(
        kho,
        tenant_id=tenant_id,
        graph=graph,
        s_keys=[t["s"] for t in graph.triples],
        o_keys=[t["o"] for t in graph.triples],
        emb=emb,
    )
    kq = KetQua(
        passage=graph.so_passage(),
        phrase=graph.so_phrase(),
        triple=len(graph.triples),
        boc=len(lo),
        con_lai=len(can_boc) - len(lo),
    )
    log.info("hippo build %s: %s", tenant_id, kq)
    return kq
```

Ghi chú về chi phí đã chấp nhận: `embed.dense` chạy trên TOÀN BỘ triple mỗi lượt, không chỉ triple mới. Đổi lại là thứ tự ba mảng npz luôn khớp `graph["triples"]` bằng cấu trúc chứ không bằng một phép đối chiếu. Embed rẻ hơn LLM một bậc, và số lượt build hiếm.

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/kb/test_hippo_build.py -q`
Expected: PASS — 16 passed

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/portal/modules/kb tests/modules/kb/test_hippo_build.py && uv run ruff format --check src/portal/modules/kb tests/modules/kb/test_hippo_build.py`
Expected: không lỗi

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/kb/hippo/build.py src/portal/modules/kb/index/store.py tests/modules/kb/test_hippo_build.py
git -c user.name="haidt" commit -m "feat(kb): one HippoRAG build pass over published chunks, incremental by point id"
```

---

### Task 5: Portal — job, cờ, và móc vào đường nạp

**Files:**
- Create: `src/portal/modules/kb/hippo/jobs.py`
- Modify: `src/portal/modules/kb/settings.py` (thêm một field vào `KbEnv`)
- Modify: `src/portal/modules/kb/jobs.py` (thêm import + wrapper + đổi 2 dòng `register`)
- Modify: `.env.example` (thêm một khối comment)
- Test: `tests/modules/kb/test_hippo_jobs.py`

**Interfaces:**
- Consumes: `build.chay_mot_luot`, `contracts.KIND_HIPPO_BUILD` (Task 1, 4).
- Produces:
  - `KbEnv.hippo_enabled: bool = False` (env `KB_HIPPO_ENABLED`)
  - `hippo.jobs.xep_build(conn, *, tenant_id: str) -> int` — trả `0` khi đã có job queued
  - `hippo.jobs.handle_hippo_build(conn, payload: dict) -> JobResult`
  - `kb.jobs._kem_hippo(handler)` — wrapper

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/kb/test_hippo_jobs.py`:

```python
"""Cờ và móc nối. Bài quan trọng nhất là `test_co_tat_khong_xep_gi` — nó biến câu
hứa "không phá workflow hiện tại" thành một cổng thay vì một dòng trong spec.

Kết nối là fake: không Postgres.
"""

import pytest

from portal.core.jobs import JobResult
from portal.modules.kb import jobs as kb_jobs
from portal.modules.kb import settings as kb_settings
from portal.modules.kb.hippo import jobs as hippo_jobs
from portal.modules.kb.hippo.contracts import KIND_HIPPO_BUILD


class ConnGia:
    """Đủ cho `xep_build`: `fetchval` cho tenant hiện tại và cho phép kiểm trùng."""

    def __init__(self, *, tenant: str = "t1", da_co_queued: bool = False) -> None:
        self.tenant = tenant
        self.da_co_queued = da_co_queued
        self.cau_lenh: list[str] = []

    async def fetchval(self, sql: str, *args):
        self.cau_lenh.append(sql)
        if "current_tenant" in sql:
            return self.tenant
        if "kb_hippo_build" in sql or KIND_HIPPO_BUILD in str(args):
            return 1 if self.da_co_queued else None
        return None


class ConnXepGia(ConnGia):
    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.da_xep: list[dict] = []


@pytest.fixture
def tat_co(monkeypatch):
    monkeypatch.setattr(kb_settings, "get_env", lambda: kb_settings.KbEnv(hippo_enabled=False))


@pytest.fixture
def bat_co(monkeypatch):
    monkeypatch.setattr(kb_settings, "get_env", lambda: kb_settings.KbEnv(hippo_enabled=True))


def test_mac_dinh_cua_co_la_tat():
    """`_env_file=None` — không có nó thì bài này đo `.env` của máy người viết và
    xanh trên CI trong khi mù ở đúng chỗ cần đỏ."""
    assert kb_settings.KbEnv(_env_file=None).hippo_enabled is False


def test_kind_khong_trung_kind_nao_cua_kb():
    ten = {
        v
        for k, v in vars(__import__("portal.modules.kb.contracts", fromlist=["x"])).items()
        if k.startswith("KIND_") and isinstance(v, str)
    }
    assert KIND_HIPPO_BUILD not in ten


async def test_co_tat_khong_xep_gi(tat_co, monkeypatch):
    goi: list[str] = []

    async def handler(conn, payload):
        return JobResult(count=1, message="xong")

    async def xep(conn, *, tenant_id):
        goi.append(tenant_id)
        return 1

    monkeypatch.setattr(hippo_jobs, "xep_build", xep)
    ra = await kb_jobs._kem_hippo(handler)(ConnGia(), {})
    assert ra.count == 1 and ra.message == "xong"
    assert goi == [], "cờ tắt mà vẫn xếp job build"


async def test_co_bat_thi_xep(bat_co, monkeypatch):
    goi: list[str] = []

    async def handler(conn, payload):
        return JobResult(count=1, message="xong")

    async def xep(conn, *, tenant_id):
        goi.append(tenant_id)
        return 1

    monkeypatch.setattr(hippo_jobs, "xep_build", xep)
    ra = await kb_jobs._kem_hippo(handler)(ConnGia(tenant="t9"), {})
    assert ra.count == 1
    assert goi == ["t9"]


async def test_wrapper_khong_doi_ket_qua_cua_handler(bat_co, monkeypatch):
    async def handler(conn, payload):
        return JobResult(count=7, message="bảy point")

    monkeypatch.setattr(hippo_jobs, "xep_build", lambda conn, *, tenant_id: _ok())
    ra = await kb_jobs._kem_hippo(handler)(ConnGia(), {})
    assert (ra.count, ra.message) == (7, "bảy point")


async def _ok():
    return 1


async def test_handler_nem_thi_wrapper_khong_xep(bat_co, monkeypatch):
    goi: list[str] = []

    async def handler(conn, payload):
        raise RuntimeError("nạp hỏng")

    async def xep(conn, *, tenant_id):
        goi.append(tenant_id)
        return 1

    monkeypatch.setattr(hippo_jobs, "xep_build", xep)
    with pytest.raises(RuntimeError):
        await kb_jobs._kem_hippo(handler)(ConnGia(), {})
    assert goi == []


async def test_xep_build_bo_qua_khi_da_co_job_queued(monkeypatch):
    """Một lượt upload 50 tệp không được sinh 50 job build của cùng tenant."""
    conn = ConnGia(da_co_queued=True)
    assert await hippo_jobs.xep_build(conn, tenant_id="t1") == 0


async def test_hai_handler_nap_da_duoc_boc():
    """Nếu ai đó thêm một handler nạp thứ ba mà quên bọc, bài này không bắt được —
    nhưng nó bắt được việc ai đó GỠ wrapper khỏi hai handler đang có."""
    import inspect

    src = inspect.getsource(kb_jobs)
    assert "_kem_hippo(handle_index)" in src
    assert "_kem_hippo(handle_kb_file_index)" in src


async def test_handle_hippo_build_goi_chay_mot_luot(monkeypatch):
    from portal.modules.kb.hippo import build as hippo_build

    da_goi: dict = {}

    async def chay(**kw):
        da_goi.update(kw)
        return hippo_build.KetQua(passage=3, phrase=5, triple=7, boc=3, con_lai=0)

    monkeypatch.setattr(hippo_build, "chay_mot_luot", chay)
    monkeypatch.setattr(hippo_jobs, "_phu_thuoc", _phu_thuoc_gia)
    ra = await hippo_jobs.handle_hippo_build(ConnGia(tenant="t1"), {})
    assert ra.count == 3
    assert "3 passage" in ra.message and "7 triple" in ra.message
    assert da_goi["tenant_id"] == "t1"


async def test_con_lai_duong_thi_xep_tiep(monkeypatch):
    from portal.modules.kb.hippo import build as hippo_build

    goi: list[str] = []

    async def chay(**kw):
        return hippo_build.KetQua(passage=500, phrase=1, triple=1, boc=500, con_lai=120)

    async def xep(conn, *, tenant_id, bo_qua_trung=False):
        goi.append(tenant_id)
        return 1

    monkeypatch.setattr(hippo_build, "chay_mot_luot", chay)
    monkeypatch.setattr(hippo_jobs, "xep_build", xep)
    monkeypatch.setattr(hippo_jobs, "_phu_thuoc", _phu_thuoc_gia)
    ra = await hippo_jobs.handle_hippo_build(ConnGia(tenant="t1"), {})
    assert goi == ["t1"], "còn 120 chunk chưa bóc mà không xếp lượt tiếp"
    assert "còn 120" in ra.message


class _KhoRong:
    def key(self, *, tenant_id: str, path: str) -> str:
        return f"tenants/{tenant_id}/{path}"

    async def put(self, **kw):
        return ""

    async def doc(self, **kw):
        raise AssertionError("không nên gọi")


class _Rong:
    async def scroll_payloads(self, name, *, anchor_code=""):
        return []

    async def boc(self, text):
        return []

    async def dense(self, texts):
        return []

    async def aclose(self):
        return None


import contextlib


@contextlib.asynccontextmanager
async def _phu_thuoc_gia():
    r = _Rong()
    yield r, _KhoRong(), r, r
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/modules/kb/test_hippo_jobs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.kb.hippo.jobs'`

- [ ] **Step 3: Thêm cờ vào `KbEnv`**

Trong `src/portal/modules/kb/settings.py`, thêm vào cuối phần khai field của `KbEnv` (ngay trước `def get_env()`):

```python
    # Cổng nạp HippoRAG. TẮT mặc định: bật là mỗi lượt nạp thêm một job gọi LLM cho
    # từng chunk mới. Tắt thì đường nạp không xếp gì và bit-identical với trước.
    hippo_enabled: bool = False
```

- [ ] **Step 4: Viết `hippo/jobs.py`**

Tạo `src/portal/modules/kb/hippo/jobs.py`:

```python
"""Job build graph HippoRAG. Đăng ký ở `kb/jobs.py`; phần việc thật ở `build.py`."""

import contextlib
import logging
from collections.abc import AsyncIterator

import asyncpg

from portal.core.jobs import JobResult, enqueue
from portal.modules.kb.hippo import build as hippo_build
from portal.modules.kb.hippo.contracts import KIND_HIPPO_BUILD

log = logging.getLogger(__name__)

_SQL_DA_CO = """SELECT 1 FROM control.jobs
WHERE tenant_id = $1 AND kind = $2 AND state IN ('queued', 'running') LIMIT 1"""


async def xep_build(conn: asyncpg.Connection, *, tenant_id: str) -> int:
    """Xếp một lượt build, TRỪ khi tenant này đã có một lượt đang chờ/đang chạy.

    Không có phép kiểm trùng thì một lượt upload 50 tệp sinh 50 job build của cùng
    tenant, mỗi job quét lại cả collection.
    """
    if await conn.fetchval(_SQL_DA_CO, tenant_id, KIND_HIPPO_BUILD):
        return 0
    return await enqueue(conn, tenant_id=tenant_id, kind=KIND_HIPPO_BUILD, actor="", payload={})


@contextlib.asynccontextmanager
async def _phu_thuoc() -> AsyncIterator[tuple]:
    """`(store, kho, openie, embed)`. Mở ở đây chứ không ở `build.py` để hàm build
    giữ được tính thuần over injected deps."""
    from portal.core.config import get_settings
    from portal.modules.kb.clients.embed import EmbedClient
    from portal.modules.kb.hippo.openie import OpenIEClient
    from portal.modules.kb.index.store import QdrantStore
    from portal.modules.kb.jobs import object_store
    from portal.modules.kb.settings import get_env

    env = get_env()
    cfg = get_settings()
    kho = object_store()
    store = QdrantStore(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)
    embed = EmbedClient(base_url=env.embed_url, token=env.santa_models_token, objects=kho)
    openie = OpenIEClient(base_url=env.vlm_base_url, api_key=env.vlm_api_key)
    try:
        yield store, kho, openie, embed
    finally:
        await openie.aclose()
        await embed.aclose()
        await store.aclose()


async def handle_hippo_build(conn: asyncpg.Connection, payload: dict) -> JobResult:
    """Một lượt build cho tenant của kết nối. `renew=true` trong payload = bóc lại tất cả."""
    from portal.modules.kb.jobs import workspace_slug

    tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
    renew = bool(payload.get("renew"))
    async with _phu_thuoc() as (store, kho, openie, embed):
        kq = await hippo_build.chay_mot_luot(
            tenant_id=tenant_id,
            collection=f"{workspace_slug(tenant_id)}_documents",
            store=store,
            kho=kho,
            openie=openie,
            embed=embed,
            renew=renew,
        )
    msg = f"hippo {tenant_id}: {kq.passage} passage · {kq.phrase} phrase · {kq.triple} triple · bóc {kq.boc}"
    if kq.con_lai > 0:
        await xep_build(conn, tenant_id=tenant_id)
        msg += f" · còn {kq.con_lai} chunk, đã xếp lượt tiếp"
    return JobResult(count=kq.boc, message=msg)
```

Lưu ý: `xep_build` ở cuối `handle_hippo_build` chạy được vì job đang chạy sẽ chuyển sang `success` SAU khi handler trả — nhưng phép kiểm trùng lọc cả `running`, nên lời gọi này sẽ trả `0` và lượt tiếp KHÔNG được xếp. Sửa bằng cách cho `xep_build` một tham số bỏ qua phép kiểm:

```python
async def xep_build(conn: asyncpg.Connection, *, tenant_id: str, bo_qua_trung: bool = False) -> int:
    if not bo_qua_trung and await conn.fetchval(_SQL_DA_CO, tenant_id, KIND_HIPPO_BUILD):
        return 0
    return await enqueue(conn, tenant_id=tenant_id, kind=KIND_HIPPO_BUILD, actor="", payload={})
```

và gọi `await xep_build(conn, tenant_id=tenant_id, bo_qua_trung=True)` ở nhánh `con_lai > 0`. Đây chính là ca mà `test_con_lai_duong_thi_xep_tiep` canh.

- [ ] **Step 5: Nối vào `kb/jobs.py`**

Thêm import ở khối import của `src/portal/modules/kb/jobs.py`:

```python
from portal.modules.kb.hippo import jobs as hippo_jobs
from portal.modules.kb.hippo.contracts import KIND_HIPPO_BUILD
```

Thêm wrapper ngay TRƯỚC khối `register(...)` ở cuối file:

```python
def _kem_hippo(handler):
    """Bọc một handler nạp: sau khi nó xong, xếp thêm một lượt build graph HippoRAG.

    Bọc ở đây chứ không thêm một dòng vào cuối thân handler: `handle_index` có BỐN
    điểm `return` và `handle_kb_file_index` có HAI (một trong khối `except`), nên một
    dòng ở cuối thân chỉ phủ một trong sáu đường ra. Cờ tắt thì đây là một lời gọi
    hàm cộng một phép so bool.
    """

    async def _bao(conn: asyncpg.Connection, payload: dict) -> JobResult:
        ra = await handler(conn, payload)
        if get_env().hippo_enabled:
            tenant_id = str(await conn.fetchval("SELECT portal.current_tenant()"))
            await hippo_jobs.xep_build(conn, tenant_id=tenant_id)
        return ra

    return _bao
```

Đổi hai dòng `register` (dòng 992-993) thành:

```python
register(KIND_KB_FILE_INDEX, _kem_hippo(handle_kb_file_index), retries=0)
register(KIND_INDEX, _kem_hippo(handle_index), retries=RETRY_VIEC_KB, max_concurrency=LANE_INDEX)
```

Thêm một dòng `register` cho job mới, cạnh các dòng khác:

```python
register(KIND_HIPPO_BUILD, hippo_jobs.handle_hippo_build, retries=RETRY_VIEC_KB)
```

- [ ] **Step 6: Khai cờ vào `.env.example`**

Thêm vào `.env.example`, dưới khối `KB_`:

```bash
# ─── HippoRAG (nửa GHI) ─────────────────────────────────────────────────────
# Bật thì mỗi lượt nạp xếp thêm một job `kb_hippo_build`: bóc triple bằng LLM cho
# từng chunk MỚI (một lượt gọi LLM mỗi chunk), dựng graph, ghi
# tenants/<id>/hipporag/{graph.json,triple_emb.npz}.
# Nửa ĐỌC nằm ở repo odyssey-agent (NOBLE_RAG_BACKEND=hipporag_kb) và độc lập với cờ này.
# Dữ liệu đã nạp trước khi bật: chạy `python -m portal.cli.hippo_build --tenant <id> --renew`.
# KB_HIPPO_ENABLED=false
```

- [ ] **Step 7: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/modules/kb/test_hippo_jobs.py -q`
Expected: PASS — 11 passed

- [ ] **Step 8: Xác nhận không hồi quy ở phần thuần của module kb**

Run: `uv run pytest tests/modules/kb -q -p no:randomly --deselect tests/modules/kb -k "hippo or chunker or prompts or content_hash or settings or directive or storage or object_store"`
Expected: PASS. Các file test khác của `tests/modules/kb` cần Docker (`pool`) nên không chạy trong đợt này — nói rõ điều đó trong báo cáo thay vì để người đọc tưởng cả thư mục đã xanh.

Run: `uv run pytest tests/unit -q`
Expected: PASS, cùng số như baseline. Đo baseline TRƯỚC bằng `git stash && uv run pytest tests/unit -q && git stash pop` nếu con số lệch.

- [ ] **Step 9: Lint**

Run: `uv run ruff check src/portal tests/modules/kb && uv run ruff format --check src/portal tests/modules/kb`
Expected: không lỗi

- [ ] **Step 10: Commit — HAI commit, không gộp**

```bash
git add src/portal/modules/kb/hippo/jobs.py src/portal/modules/kb/settings.py tests/modules/kb/test_hippo_jobs.py
git -c user.name="haidt" commit -m "feat(kb): kb_hippo_build job behind KB_HIPPO_ENABLED, off by default"

git add src/portal/modules/kb/jobs.py .env.example
git -c user.name="haidt" commit -m "feat(kb): hook the graph build onto the ingest handlers with a register-time wrapper"
```

---

### Task 6: Portal — CLI backfill

**Files:**
- Create: `src/portal/cli/hippo_build.py`
- Test: `tests/unit/test_cli_hippo_build.py`

**Interfaces:**
- Consumes: `hippo.contracts.KIND_HIPPO_BUILD` (Task 1).
- Produces: `hippo_build.doc_tham_so(argv: list[str]) -> tuple[str, bool]` trả `(tenant_id, renew)`; `hippo_build.main_async() -> int`; entry `python -m portal.cli.hippo_build`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_cli_hippo_build.py`:

```python
"""Phân tích đối số của CLI backfill — hàm thuần, không DB."""

import pytest

from portal.cli import hippo_build


def test_tenant_bat_buoc():
    with pytest.raises(SystemExit):
        hippo_build.doc_tham_so([])


def test_tenant_va_renew():
    assert hippo_build.doc_tham_so(["--tenant", "anphu"]) == ("anphu", False)
    assert hippo_build.doc_tham_so(["--tenant", "anphu", "--renew"]) == ("anphu", True)


def test_tenant_rong_bi_tu_choi():
    with pytest.raises(SystemExit):
        hippo_build.doc_tham_so(["--tenant", "  "])
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/unit/test_cli_hippo_build.py -q`
Expected: FAIL — `ImportError: cannot import name 'hippo_build'`

- [ ] **Step 3: Viết CLI**

Tạo `src/portal/cli/hippo_build.py`:

```python
"""Xếp một lượt build graph HippoRAG cho MỘT workspace.

    python -m portal.cli.hippo_build --tenant anphu [--renew]

Dùng cho dữ liệu đã nạp TRƯỚC khi `KB_HIPPO_ENABLED` được bật — với cờ tắt thì
đường nạp không xếp gì, nên graph của tenant cũ sẽ trống tới khi lệnh này chạy.

CHỈ XẾP HÀNG, không tự build: worker là chỗ duy nhất có `_phu_thuoc()`, và một lệnh
tự làm hết việc rồi thoát thì lần nó chết giữa chừng không để lại dòng `control.jobs`
nào để tra.

Một tenant mỗi lượt, không có `--all`: lượt build đầu của một tenant gọi LLM một lần
cho MỖI chunk, nên "cho mọi tenant" phải là một quyết định có người bấm, không phải
một cờ mặc định.
"""

import argparse
import asyncio
import sys

from portal.core.config import get_settings
from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from portal.modules.kb.hippo.jobs import xep_build


def doc_tham_so(argv: list[str]) -> tuple[str, bool]:
    p = argparse.ArgumentParser(prog="hippo-build")
    p.add_argument("--tenant", required=True)
    p.add_argument("--renew", action="store_true")
    ns = p.parse_args(argv)
    tenant = (ns.tenant or "").strip()
    if not tenant:
        p.error("--tenant rỗng")
    return tenant, bool(ns.renew)


async def main_async(argv: list[str] | None = None) -> int:
    tenant, renew = doc_tham_so(sys.argv[1:] if argv is None else argv)
    pool = await create_pool(get_settings().database_url, min_size=1, max_size=2)
    try:
        async with tenant_conn(pool, tenant) as conn:
            job_id = await xep_build(conn, tenant_id=tenant, bo_qua_trung=renew)
    finally:
        await pool.close()
    if job_id == 0:
        print(f"hippo-build: {tenant} đã có một lượt đang chờ/đang chạy — không xếp thêm")
        return 0
    print(f"hippo-build: đã xếp job {job_id} cho {tenant} (renew={renew})")
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
```

⚠️ `--renew` phải đi vào payload của job, không chỉ vào `bo_qua_trung`. Sửa `xep_build` để nhận payload:

```python
async def xep_build(
    conn: asyncpg.Connection, *, tenant_id: str, bo_qua_trung: bool = False, renew: bool = False
) -> int:
    if not bo_qua_trung and await conn.fetchval(_SQL_DA_CO, tenant_id, KIND_HIPPO_BUILD):
        return 0
    return await enqueue(
        conn, tenant_id=tenant_id, kind=KIND_HIPPO_BUILD, actor="", payload={"renew": renew} if renew else {}
    )
```

và CLI gọi `xep_build(conn, tenant_id=tenant, bo_qua_trung=renew, renew=renew)`.

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/unit/test_cli_hippo_build.py tests/modules/kb/test_hippo_jobs.py -q`
Expected: PASS

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/portal tests/unit/test_cli_hippo_build.py && uv run ruff format --check src/portal tests/unit/test_cli_hippo_build.py`
Expected: không lỗi

- [ ] **Step 6: Commit**

```bash
git add src/portal/cli/hippo_build.py src/portal/modules/kb/hippo/jobs.py tests/unit/test_cli_hippo_build.py
git -c user.name="haidt" commit -m "feat(cli): hippo-build enqueues one graph build for a single workspace"
```

---

### Task 7: Agent — tải artefact về cache theo tenant

**Files:**
- Create: `src/noble_agent/agent/rag/hipporag/artefact_store.py`
- Modify: `src/noble_agent/config.py` (thêm 5 field)
- Modify: `.env.example` (thêm một khối comment)
- Test: `tests/unit/unified/rag/test_hipporag_artefact_store.py`

**Interfaces:**
- Consumes: `settings`, `current_tenant()`.
- Produces:
  - `settings.hipporag_artefact_endpoint/bucket/access_key/secret_key: str` (env `HIPPORAG_ARTEFACT_*`), `settings.hipporag_cache_dir: str`
  - `artefact_store.GRAPH_OBJECT: str = "hipporag/graph.json"`, `TRIPLE_OBJECT: str = "hipporag/triple_emb.npz"`
  - `artefact_store.khoa(tenant_id: str, obj: str) -> str`
  - `artefact_store.duong_dan_cache(tenant_id: str) -> tuple[str, str]` — `(graph_path, npz_path)`
  - `artefact_store.tai_ve(tenant_id: str = "") -> str | None` — trả graph path, `None` khi chưa cấu hình / không có graph

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/unified/rag/test_hipporag_artefact_store.py`:

```python
"""Tải artefact HippoRAG: khoá object, tên tệp cache, và các nhánh degrade.

boto3 được thay bằng một client giả — không mạng, không S3.
"""

from __future__ import annotations

import os

import pytest

from noble_agent.agent.rag.hipporag import artefact_store
from noble_agent.config import settings


class S3Gia:
    def __init__(self, co: set[str] | None = None) -> None:
        self.co = co if co is not None else set()
        self.da_tai: list[tuple[str, str]] = []

    def download_file(self, bucket: str, key: str, path: str) -> None:
        self.da_tai.append((bucket, key))
        if key not in self.co:
            raise FileNotFoundError(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"{}")


@pytest.fixture
def cau_hinh(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "hipporag_artefact_endpoint", "http://minio.test:9000")
    monkeypatch.setattr(settings, "hipporag_artefact_bucket", "portal")
    monkeypatch.setattr(settings, "hipporag_artefact_access_key", "ak")
    monkeypatch.setattr(settings, "hipporag_artefact_secret_key", "sk")
    monkeypatch.setattr(settings, "hipporag_cache_dir", str(tmp_path))


def test_khoa_dung_tien_to_tenant_cua_portal():
    assert artefact_store.khoa("anphu", artefact_store.GRAPH_OBJECT) == "tenants/anphu/hipporag/graph.json"
    assert artefact_store.khoa("anphu", artefact_store.TRIPLE_OBJECT) == "tenants/anphu/hipporag/triple_emb.npz"


def test_npz_cache_dung_ten_ma_triple_index_suy_ra(cau_hinh):
    """`triple_index.triple_emb_path()` suy sidecar từ đường dẫn graph bằng
    `splitext(graph)[0] + '.triple_emb.npz'`. Đặt tên khác là sidecar không bao giờ
    được tìm thấy, và sparse seed tắt im lặng."""
    from noble_agent.agent.rag.hipporag.triple_index import triple_emb_path

    graph_path, npz_path = artefact_store.duong_dan_cache("anphu")
    assert npz_path == triple_emb_path(graph_path)


def test_cache_tach_theo_tenant(cau_hinh):
    a, _ = artefact_store.duong_dan_cache("t1")
    b, _ = artefact_store.duong_dan_cache("t2")
    assert a != b and "t1" in a and "t2" in b


def test_chua_cau_hinh_thi_none(monkeypatch):
    monkeypatch.setattr(settings, "hipporag_artefact_endpoint", "")
    monkeypatch.setattr(settings, "hipporag_artefact_bucket", "")
    assert artefact_store.tai_ve("anphu") is None


def test_khong_co_graph_thi_none(cau_hinh, monkeypatch):
    s3 = S3Gia(co=set())
    monkeypatch.setattr(artefact_store, "_client", lambda: s3)
    assert artefact_store.tai_ve("anphu") is None


def test_co_graph_khong_co_npz_van_tra_graph(cau_hinh, monkeypatch):
    """Graph có, sidecar chưa — PPR vẫn chạy với seed passage; sparse seed tắt."""
    s3 = S3Gia(co={"tenants/anphu/hipporag/graph.json"})
    monkeypatch.setattr(artefact_store, "_client", lambda: s3)
    p = artefact_store.tai_ve("anphu")
    assert p is not None and os.path.isfile(p)


def test_tai_ca_hai_khi_co_du(cau_hinh, monkeypatch):
    s3 = S3Gia(co={"tenants/anphu/hipporag/graph.json", "tenants/anphu/hipporag/triple_emb.npz"})
    monkeypatch.setattr(artefact_store, "_client", lambda: s3)
    graph_path = artefact_store.tai_ve("anphu")
    _g, npz_path = artefact_store.duong_dan_cache("anphu")
    assert graph_path is not None and os.path.isfile(npz_path)
    assert [k for _b, k in s3.da_tai] == [
        "tenants/anphu/hipporag/graph.json",
        "tenants/anphu/hipporag/triple_emb.npz",
    ]


def test_tenant_rong_thi_lay_current_tenant(cau_hinh, monkeypatch):
    from noble_agent.tenant.current import use_tenant

    s3 = S3Gia(co={"tenants/tx/hipporag/graph.json"})
    monkeypatch.setattr(artefact_store, "_client", lambda: s3)
    with use_tenant("tx"):
        assert artefact_store.tai_ve() is not None
    assert s3.da_tai[0][1] == "tenants/tx/hipporag/graph.json"


def test_loi_s3_bat_ky_thi_none_khong_nem(cau_hinh, monkeypatch):
    class S3Nem:
        def download_file(self, *a, **kw):
            raise RuntimeError("mạng chết")

    monkeypatch.setattr(artefact_store, "_client", lambda: S3Nem())
    assert artefact_store.tai_ve("anphu") is None
```

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `cd /home/thanhhai/Desktop/odyssey-agent && uv run pytest tests/unit/unified/rag/test_hipporag_artefact_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.agent.rag.hipporag.artefact_store'`

- [ ] **Step 3: Thêm settings**

Trong `src/noble_agent/config.py`, thêm ngay SAU `hipporag_phrase_seed_threshold` (quanh dòng 626):

```python
    # ── HippoRAG: artefact do Portal ghi (backend `hipporag_kb`) ──────────────
    # Kho tệp của Portal, đọc `tenants/<tenant>/hipporag/{graph.json,triple_emb.npz}`.
    # Cấu hình TĨNH chứ không phải credential per-tenant: registry
    # `storage/tenant_credentials.py` chỉ mang role/password Postgres, không có trường
    # S3. Cách ly nằm ở `current_tenant()` trong đường dẫn khoá — cùng mô hình mà
    # `kb_service_adapter` đã dùng cho tên collection (nó cũng dùng khoá Qdrant TOÀN CỤC).
    # Rỗng ⇒ không tải gì ⇒ backend degrade về `kb_service`.
    hipporag_artefact_endpoint: str = Field("", alias="HIPPORAG_ARTEFACT_ENDPOINT")
    hipporag_artefact_bucket: str = Field("", alias="HIPPORAG_ARTEFACT_BUCKET")
    hipporag_artefact_access_key: str = Field("", alias="HIPPORAG_ARTEFACT_ACCESS_KEY")
    hipporag_artefact_secret_key: str = Field("", alias="HIPPORAG_ARTEFACT_SECRET_KEY")
    hipporag_cache_dir: str = Field("/var/lib/noble/hipporag", alias="HIPPORAG_CACHE_DIR")
```

- [ ] **Step 4: Viết `artefact_store.py`**

Tạo `src/noble_agent/agent/rag/hipporag/artefact_store.py`:

```python
"""Tải artefact HippoRAG mà Portal ghi ra, về cache cục bộ theo tenant.

Hợp đồng: `odyssey-portal-backend/docs/contracts/hipporag-graph.md`.

MỌI thất bại trả `None` — thiếu artefact là đường THƯỜNG (tenant chưa build), và
backend gọi hàm này degrade về `kb_service` khi nó trả `None`.
"""

from __future__ import annotations

import logging
import os

from noble_agent.config import settings
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("rag.hipporag.artefact_store")

TIEN_TO = "tenants"
GRAPH_OBJECT = "hipporag/graph.json"
TRIPLE_OBJECT = "hipporag/triple_emb.npz"


def khoa(tenant_id: str, obj: str) -> str:
    return f"{TIEN_TO}/{tenant_id}/{obj}"


def duong_dan_cache(tenant_id: str) -> tuple[str, str]:
    """`(graph_path, npz_path)`. npz PHẢI là `<stem của graph>.triple_emb.npz` —
    `triple_index.triple_emb_path()` suy nó từ graph path."""
    graph = os.path.join(settings.hipporag_cache_dir, tenant_id, "graph.json")
    return graph, os.path.splitext(graph)[0] + ".triple_emb.npz"


def _client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.hipporag_artefact_endpoint,
        aws_access_key_id=settings.hipporag_artefact_access_key or None,
        aws_secret_access_key=settings.hipporag_artefact_secret_key or None,
    )


def tai_ve(tenant_id: str = "") -> str | None:
    """Tải graph (+ sidecar nếu có) về cache; trả đường dẫn graph, hoặc `None`."""
    tenant_id = tenant_id or current_tenant()
    if not (settings.hipporag_artefact_endpoint and settings.hipporag_artefact_bucket and tenant_id):
        return None
    graph_path, npz_path = duong_dan_cache(tenant_id)
    bucket = settings.hipporag_artefact_bucket
    try:
        c = _client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.artefact] no s3 client (%s)", exc)
        return None
    try:
        os.makedirs(os.path.dirname(graph_path), exist_ok=True)
        c.download_file(bucket, khoa(tenant_id, GRAPH_OBJECT), graph_path)
    except Exception as exc:  # noqa: BLE001
        logger.info("[hipporag.artefact] no graph for %s (%s) — degrade to kb_service", tenant_id, exc)
        return None
    try:
        c.download_file(bucket, khoa(tenant_id, TRIPLE_OBJECT), npz_path)
    except Exception as exc:  # noqa: BLE001
        logger.info("[hipporag.artefact] no triple sidecar for %s (%s) — passage-only seeding", tenant_id, exc)
    return graph_path
```

- [ ] **Step 5: Khai env**

Thêm vào `.env.example` của repo agent, ngay sau khối `HIPPORAG_*` hiện có:

```bash
# HippoRAG artefact do Portal ghi (chỉ backend `hipporag_kb` đọc). Rỗng ⇒ không tải
# gì ⇒ backend degrade về đúng kết quả `kb_service`. Bucket là bucket của Portal,
# KHÔNG phải TENANT_BUCKET của kho bundle legacy.
# HIPPORAG_ARTEFACT_ENDPOINT=
# HIPPORAG_ARTEFACT_BUCKET=
# HIPPORAG_ARTEFACT_ACCESS_KEY=
# HIPPORAG_ARTEFACT_SECRET_KEY=
# HIPPORAG_CACHE_DIR=/var/lib/noble/hipporag
```

- [ ] **Step 6: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/unit/unified/rag/test_hipporag_artefact_store.py tests/unit/unified/test_search_infra_config.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /home/thanhhai/Desktop/odyssey-agent
git add src/noble_agent/agent/rag/hipporag/artefact_store.py src/noble_agent/config.py .env.example tests/unit/unified/rag/test_hipporag_artefact_store.py
git -c user.name="haidt" commit -m "feat(rag): fetch the portal-written HippoRAG artefacts into a per-tenant cache"
```

---

### Task 8: Agent — tách `kb_service_adapter` thành lấy-hit và render

**Files:**
- Modify: `src/noble_agent/agent/rag/kb_service_adapter.py`
- Test: `tests/unit/unified/rag/test_kb_service_adapter.py` (thêm bài, không sửa bài cũ)

**Interfaces:**
- Consumes: không gì mới.
- Produces:
  - `kb_service_adapter.hits_for(query: str, project_filter: str, limit: int) -> list[dict]` — hit thô từ Qdrant, `[{**payload, "id": str, "score": float}]`; `[]` khi query rỗng / chưa cấu hình Qdrant / collection vắng / embed rỗng.
  - `kb_service_adapter.render(hits: list[dict], dinh_kem: list[dict] | None, du_an: list[str] | None, numbers: dict[str, int] | None) -> str`
  - `query_kb_service_for_noble_kb` giữ NGUYÊN chữ ký và hành vi.

Đây là refactor extract-function trên một file đang chạy. Lưới an toàn là hai file test sẵn có: `tests/unit/unified/rag/test_kb_service_adapter.py` và `test_kb_service_dispatch.py`. Chạy chúng TRƯỚC khi sửa để có baseline.

- [ ] **Step 1: Đo baseline**

Run: `uv run pytest tests/unit/unified/rag/test_kb_service_adapter.py tests/unit/unified/rag/test_kb_service_dispatch.py tests/unit/test_kb_image_numbers.py tests/unit/unified/test_tour_360_va_dinh_kem.py -q`
Expected: PASS. Ghi lại con số — nó là baseline của step 4.

- [ ] **Step 2: Viết test đỏ cho hai hàm mới**

Thêm vào CUỐI `tests/unit/unified/rag/test_kb_service_adapter.py`:

```python
# ── tách hits_for / render (nền của backend hipporag_kb) ─────────────────────


def test_render_chi_can_text():
    from noble_agent.agent.rag import kb_service_adapter as ksa

    out = ksa.render([{"text": "Noble Crystal ở Tây Hồ"}], None, None, None)
    assert "Noble Crystal ở Tây Hồ" in out


def test_render_do_vao_bon_dinh_kem_va_du_an():
    from noble_agent.agent.rag import kb_service_adapter as ksa
    from noble_agent.config import settings

    hits = [{"text": "abc", "project_id": "nplb", "file_public_url": "https://x.test/a.pdf", "file_name": "a.pdf"}]
    dinh_kem: list[dict] = []
    du_an: list[str] = []
    if settings.kb_search_attach_source_files:
        ksa.render(hits, dinh_kem, du_an, {})
        assert dinh_kem and dinh_kem[0]["url"] == "https://x.test/a.pdf"
    else:
        ksa.render(hits, dinh_kem, du_an, {})
    assert du_an == ["nplb"]


async def test_hits_for_query_rong_ra_rong():
    from noble_agent.agent.rag import kb_service_adapter as ksa

    assert await ksa.hits_for("  ", "", 5) == []


async def test_hits_for_khong_co_qdrant_url_ra_rong(monkeypatch):
    from noble_agent.agent.rag import kb_service_adapter as ksa
    from noble_agent.config import settings

    monkeypatch.setattr(settings, "qdrant_url", "")
    assert await ksa.hits_for("bể bơi", "", 5) == []


async def test_query_kb_service_van_di_qua_hai_ham_moi(monkeypatch):
    """Hợp đồng của lần tách: đường cũ phải là `render(await hits_for(...))`."""
    from noble_agent.agent.rag import kb_service_adapter as ksa

    goi: dict = {}

    async def fake_hits(query, project_filter, limit):
        goi["hits_for"] = (query, project_filter, limit)
        return [{"text": "abc"}]

    def fake_render(hits, dinh_kem, du_an, numbers):
        goi["render"] = len(hits)
        return "DA_RENDER"

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(ksa, "render", fake_render)
    out = await ksa.query_kb_service_for_noble_kb("bể bơi", "nplb", top_k=3)
    assert out == "DA_RENDER"
    assert goi["hits_for"] == ("bể bơi", "nplb", 3)
    assert goi["render"] == 1
```

- [ ] **Step 3: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/unit/unified/rag/test_kb_service_adapter.py -q`
Expected: FAIL — `AttributeError: module 'noble_agent.agent.rag.kb_service_adapter' has no attribute 'render'`

- [ ] **Step 4: Tách hai hàm**

Trong `src/noble_agent/agent/rag/kb_service_adapter.py`, thay thân của `query_kb_service_for_noble_kb` bằng ba hàm. Giữ NGUYÊN mọi hàm `_`-prefixed hiện có.

```python
async def hits_for(query: str, project_filter: str, limit: int) -> list[dict]:
    """Hit thô từ Qdrant: `[{**payload, "id": str, "score": float}]` theo thứ tự RRF.

    Tách khỏi `query_kb_service_for_noble_kb` để backend `hipporag_kb` lấy được ĐÚNG
    seed mà `kb_service` dùng, thay vì dựng bản sao của khối embed+search này —
    một bản sao là chỗ để lệch vào ngày hợp đồng payload đổi.
    """
    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return []

    qdrant_url = settings.qdrant_url
    if not qdrant_url:
        logger.warning("[kb_service_adapter] qdrant_url empty — returning no context")
        return []

    api_key = settings.qdrant_api_key
    collection = qdrant_client.collection_name(current_tenant(), "documents")
    if not await qdrant_client.collection_exists(qdrant_url, api_key, collection):
        logger.info("[kb_service_adapter] collection %s absent — returning no context", collection)
        return []

    dense_vecs, sparse_vecs = await asyncio.gather(
        embed_client.embed_dense([query], side="query"),
        embed_client.embed_sparse([query], side="query"),
    )
    if not dense_vecs or not sparse_vecs:
        logger.warning("[kb_service_adapter] embed returned no vectors — returning no context")
        return []
    sparse = sparse_vecs[0]

    project_codes = [project_filter] if project_filter else []
    min_score = settings.kb_search_min_score
    return await qdrant_client.search_hybrid(
        base_url=qdrant_url,
        api_key=api_key,
        collection=collection,
        prefetches=[
            qdrant_client.DensePrefetch(DENSE_VECTOR, dense_vecs[0]),
            qdrant_client.SparsePrefetch(
                SPARSE_VECTOR,
                sparse.get("indices", []),
                sparse.get("values", []),
            ),
        ],
        limit=limit,
        score_threshold=min_score if min_score > 0 else None,
        filter_=qdrant_client.build_scope_filter(project_codes),
        timeout=settings.qdrant_timeout,
    )


def render(
    hits: list[dict],
    dinh_kem: list[dict] | None,
    du_an: list[str] | None,
    numbers: dict[str, int] | None,
) -> str:
    """Hit -> chuỗi ngữ cảnh, cộng việc đổ `dinh_kem`/`du_an`. Tách ra để backend
    `hipporag_kb` dùng chung một formatter — hai bản formatter là hai hình dạng ngữ
    cảnh cho cùng một tool, và mô hình sẽ học đúng một trong hai."""
    attach = settings.kb_search_attach_source_files
    if dinh_kem is not None and attach:
        dinh_kem.extend(_dinh_kem(hits, numbers))
    if du_an is not None:
        ma = _du_an_duy_nhat(hits)
        if ma:
            du_an.append(ma)
    context = _format_kb_hits(hits, numbers, replace_images=attach)
    if attach and numbers:
        in_use = {u for h in hits for _, u in _IMG_MD.findall(h.get("text") or "")}
        lines = earlier_image_lines(numbers, in_use=in_use)
        if lines:
            context += (
                "\n---\nẢNH ĐÃ NHẮC TRƯỚC ĐÓ (không có trong tài liệu lượt này, "
                "chỉ để tra lại khi khách hỏi về nó):\n" + "\n".join(lines)
            )
    return context


async def query_kb_service_for_noble_kb(
    query: str,
    project_filter: str,
    top_k: int = 5,
    dinh_kem: list[dict] | None = None,
    du_an: list[str] | None = None,
    numbers: dict[str, int] | None = None,
) -> str:
    """`dinh_kem` là BỒN CHỨA, không phải giá trị trả về: caller truyền một list và hàm này
    đổ vào đó tệp/ảnh nguồn của các hit.

    Vì sao không đổi kiểu trả về thành tuple: `query_noble_kb` dispatch sáu backend, năm
    trong đó không có khái niệm tệp kèm. Đổi kiểu trả về là sửa cả sáu để phục vụ một.
    """
    hits = await hits_for(query, project_filter, top_k)
    return render(hits, dinh_kem, du_an, numbers)
```

⚠️ Một đổi hành vi nhỏ, có chủ ý và phải nói ra: bản cũ trả `""` sớm ở ba nhánh (query rỗng, `qdrant_url` rỗng, collection vắng) mà KHÔNG chạy phần render. Bản mới trả `render([])`. `_format_kb_hits([])` trả `""` (vòng lặp không chạy, `"\n---\n".join([])` = `""`), `_dinh_kem([])` trả `[]`, `_du_an_duy_nhat([])` trả `""`, và nhánh `earlier_image_lines` cần `numbers` khác rỗng — nên đầu ra vẫn `""` và hai bồn vẫn không được đổ. Bài `test_hits_for_khong_co_qdrant_url_ra_rong` cộng các bài sẵn có canh chiều này; nếu bài cũ nào đỏ thì đó là bằng chứng tương đương KHÔNG giữ được và phải giữ ba nhánh trả `""` sớm trong `query_kb_service_for_noble_kb`.

- [ ] **Step 5: Chạy toàn bộ test liên quan, so với baseline**

Run: `uv run pytest tests/unit/unified/rag/test_kb_service_adapter.py tests/unit/unified/rag/test_kb_service_dispatch.py tests/unit/test_kb_image_numbers.py tests/unit/unified/test_tour_360_va_dinh_kem.py tests/unit/unified/test_noble_kb_dispatch.py -q`
Expected: PASS — số cũ + 5 bài mới. Bất kỳ bài CŨ nào đỏ là refactor sai, không phải test sai.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/rag/kb_service_adapter.py tests/unit/unified/rag/test_kb_service_adapter.py
git -c user.name="haidt" commit -m "refactor(rag): split kb_service_adapter into hits_for and render"
```

---

### Task 9: Agent — backend `hipporag_kb`

**Files:**
- Create: `src/noble_agent/agent/rag/hipporag/kb_adapter.py`
- Modify: `src/noble_agent/agent/rag/noble_kb.py` (thêm một nhánh + một hàm)
- Modify: `.env.example` (một dòng trong khối `NOBLE_RAG_BACKEND`)
- Test: `tests/unit/unified/rag/test_hipporag_kb_adapter.py`

**Interfaces:**
- Consumes: `artefact_store.tai_ve` (Task 7); `kb_service_adapter.hits_for/render` (Task 8); `expander.expand`, `graph.load_graph`, `triple_index.load_triple_index` (legacy, không sửa).
- Produces:
  - `kb_adapter.load_graph_for_tenant(tenant_id: str) -> HippoGraph | None`
  - `kb_adapter.load_triple_for_tenant(tenant_id: str) -> TripleIndex | None`
  - `kb_adapter.reset_cache_for_tests() -> None`
  - `kb_adapter.thu_tu_rrf(hybrid_rows, ppr_rows) -> list[str]`
  - `kb_adapter.query_hipporag_kb_for_noble_kb(query, project_filter, top_k=5, dinh_kem=None, du_an=None, numbers=None) -> str`

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/unified/rag/test_hipporag_kb_adapter.py`:

```python
"""Backend `hipporag_kb`: PPR trên graph per-tenant, fuse với hybrid, render bằng
formatter của kb_service.

Bài `test_cache_graph_khong_lan_giua_hai_tenant` là bài AN NINH: agent là MỘT tiến
trình phục vụ nhiều workspace, và `expander.load()` legacy là singleton không khoá.
"""

from __future__ import annotations

import pytest

from noble_agent.agent.rag import kb_service_adapter as ksa
from noble_agent.agent.rag.hipporag import kb_adapter
from noble_agent.agent.rag.hipporag.graph import HippoGraph
from noble_agent.config import settings
from noble_agent.tenant.current import use_tenant


@pytest.fixture(autouse=True)
def _sach():
    kb_adapter.reset_cache_for_tests()
    yield
    kb_adapter.reset_cache_for_tests()


def _graph(*passages) -> HippoGraph:
    g = HippoGraph()
    for pid, text, proj, triples in passages:
        g.add_passage(pid, text, proj, f"h-{pid}", triples)
    return g


def _graph_hai_passage() -> HippoGraph:
    return _graph(
        ("p1", "Noble Crystal tổng quan", "nplb", [("Noble Crystal", "ở", "Tây Hồ")]),
        ("p2", "Noble Crystal bể bơi", "nplb", [("Noble Crystal", "có", "bể bơi")]),
    )


def _hit(pid: str, text: str, proj: str = "nplb", score: float = 0.5) -> dict:
    return {"id": pid, "text": text, "project_id": proj, "score": score}


def test_thu_tu_rrf_uu_tien_muc_co_o_ca_hai_danh_sach():
    hybrid = [("p1", "nplb", "t1", 0.9), ("p2", "nplb", "t2", 0.5)]
    ppr = [("p2", 0.8, "nplb", "t2"), ("p3", 0.4, "nplb", "t3")]
    assert kb_adapter.thu_tu_rrf(hybrid, ppr)[0] == "p2"
    assert set(kb_adapter.thu_tu_rrf(hybrid, ppr)) == {"p1", "p2", "p3"}


def test_cache_graph_khong_lan_giua_hai_tenant(monkeypatch):
    da_goi: list[str] = []

    def tai(tenant_id: str = "") -> str | None:
        da_goi.append(tenant_id)
        return f"/khong/ton/tai/{tenant_id}.json"

    graphs = {"t1": _graph(("a", "cua t1", "p", [])), "t2": _graph(("b", "cua t2", "p", []))}
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", tai)
    monkeypatch.setattr(kb_adapter, "_doc_graph", lambda path: graphs["t1" if "t1" in path else "t2"])

    g1 = kb_adapter.load_graph_for_tenant("t1")
    g2 = kb_adapter.load_graph_for_tenant("t2")
    assert g1 is not g2
    assert g1.point_ids_for_tests() if hasattr(g1, "point_ids_for_tests") else True
    assert [n.get("point_id") for n in g1.nodes.values() if n.get("type") == "passage"] == ["a"]
    assert [n.get("point_id") for n in g2.nodes.values() if n.get("type") == "passage"] == ["b"]
    assert da_goi == ["t1", "t2"]


def test_cache_goi_tai_ve_dung_mot_lan_moi_tenant(monkeypatch):
    da_goi: list[str] = []
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", lambda tenant_id="": (da_goi.append(tenant_id), None)[1])
    kb_adapter.load_graph_for_tenant("t1")
    kb_adapter.load_graph_for_tenant("t1")
    assert da_goi == ["t1"]


def test_thieu_artefact_thi_cache_none(monkeypatch):
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", lambda tenant_id="": None)
    assert kb_adapter.load_graph_for_tenant("t1") is None


async def test_thieu_graph_thi_bang_dung_kb_service(monkeypatch):
    hits = [_hit("p1", "Noble Crystal tổng quan"), _hit("p2", "Noble Crystal bể bơi")]

    async def fake_hits(query, project_filter, limit):
        return list(hits)

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", lambda tenant_id="": None)

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("bể bơi", "nplb", top_k=2)
        mong = ksa.render(hits[:2], None, None, None)
    assert ra == mong


async def test_ppr_rong_thi_bang_dung_kb_service(monkeypatch):
    hits = [_hit("khong-co-trong-graph", "abc")]

    async def fake_hits(query, project_filter, limit):
        return list(hits)

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("abc", "nplb", top_k=1)
        mong = ksa.render(hits[:1], None, None, None)
    assert ra == mong


async def test_passage_chi_co_trong_graph_van_vao_ngu_canh(monkeypatch):
    """Đây là cái LỢI của graph: p2 không có trong hybrid hit, PPR mang nó về."""

    async def fake_hits(query, project_filter, limit):
        return [_hit("p1", "Noble Crystal tổng quan")]

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("bể bơi", "nplb", top_k=5)
    assert "bể bơi" in ra


async def test_passage_co_trong_hit_dung_chu_moi_cua_qdrant(monkeypatch):
    """Graph là SNAPSHOT. Passage nào có trong hybrid hit phải dùng chữ của Qdrant,
    không dùng chữ trong node graph."""

    async def fake_hits(query, project_filter, limit):
        return [_hit("p1", "CHỮ MỚI TỪ QDRANT")]

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: _graph_hai_passage())

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("tổng quan", "nplb", top_k=5)
    assert "CHỮ MỚI TỪ QDRANT" in ra
    assert "Noble Crystal tổng quan" not in ra


async def test_khong_lot_passage_cua_du_an_khac_khi_da_ghim(monkeypatch):
    async def fake_hits(query, project_filter, limit):
        return [_hit("p1", "Noble Crystal tổng quan")]

    g = _graph(
        ("p1", "Noble Crystal tổng quan", "nplb", [("Noble Crystal", "ở", "Tây Hồ")]),
        ("px", "DỰ ÁN KHÁC", "sgr", [("Sunrise", "ở", "Tây Hồ")]),
    )
    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", lambda t: g)

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("tây hồ", "nplb", top_k=5)
    assert "DỰ ÁN KHÁC" not in ra


async def test_seed_k_it_nhat_bang_top_k(monkeypatch):
    da_goi: list[int] = []

    async def fake_hits(query, project_filter, limit):
        da_goi.append(limit)
        return []

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter.artefact_store, "tai_ve", lambda tenant_id="": None)

    with use_tenant("t1"):
        await kb_adapter.query_hipporag_kb_for_noble_kb("q", "", top_k=20)
    assert da_goi == [max(settings.hipporag_seed_k, 20)]


async def test_loi_bat_ky_trong_duong_graph_thi_degrade(monkeypatch):
    hits = [_hit("p1", "abc")]

    async def fake_hits(query, project_filter, limit):
        return list(hits)

    def no(t):
        raise RuntimeError("graph hỏng")

    monkeypatch.setattr(ksa, "hits_for", fake_hits)
    monkeypatch.setattr(kb_adapter, "load_graph_for_tenant", no)

    with use_tenant("t1"):
        ra = await kb_adapter.query_hipporag_kb_for_noble_kb("abc", "", top_k=1)
        mong = ksa.render(hits[:1], None, None, None)
    assert ra == mong


async def test_dispatch_noble_kb_vao_dung_nhanh(monkeypatch):
    from noble_agent.agent.rag import noble_kb

    goi: list[str] = []

    async def fake(query, project_filter, top_k=5, dinh_kem=None, du_an=None, numbers=None):
        goi.append(query)
        return "TU_HIPPO_KB"

    monkeypatch.setattr(settings, "noble_rag_backend", "hipporag_kb")
    monkeypatch.setattr(kb_adapter, "query_hipporag_kb_for_noble_kb", fake)
    out = await noble_kb.query_noble_kb("bể bơi", "nplb")
    assert out == "TU_HIPPO_KB" and goi == ["bể bơi"]


async def test_backend_kb_service_khong_doi_duong(monkeypatch):
    from noble_agent.agent.rag import noble_kb

    monkeypatch.setattr(settings, "noble_rag_backend", "kb_service")

    async def no(*a, **kw):
        raise AssertionError("hipporag_kb không được gọi ở backend kb_service")

    monkeypatch.setattr(kb_adapter, "query_hipporag_kb_for_noble_kb", no)

    async def fake_ks(query, project_filter, top_k=5, dinh_kem=None, du_an=None, numbers=None):
        return "TU_KB_SERVICE"

    monkeypatch.setattr(ksa, "query_kb_service_for_noble_kb", fake_ks)
    assert await noble_kb.query_noble_kb("q", "") == "TU_KB_SERVICE"
```

Bỏ dòng `assert g1.point_ids_for_tests() ...` khỏi `test_cache_graph_khong_lan_giua_hai_tenant` — `HippoGraph` legacy không có method đó và không được thêm. Bài đã có hai `assert` sau nó làm đúng việc.

- [ ] **Step 2: Chạy test, xác nhận đỏ**

Run: `uv run pytest tests/unit/unified/rag/test_hipporag_kb_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.agent.rag.hipporag.kb_adapter'`

- [ ] **Step 3: Viết `kb_adapter.py`**

Tạo `src/noble_agent/agent/rag/hipporag/kb_adapter.py`:

```python
"""Backend `hipporag_kb`: HippoRAG trên đường dữ liệu per-tenant đang sống.

Khác `adapter.py` legacy ở ba chỗ: seed lấy từ `kb_service_adapter.hits_for` (collection
`<tenant>_documents`) thay vì clone `noble_kb_hybrid`; graph tải từ artefact Portal ghi
và cache THEO TENANT; đầu ra render bằng chính formatter của `kb_service` nên `dinh_kem`,
sổ số ảnh và mốc `[ảnh N]` hoạt động y như backend mặc định.

Degrade về ĐÚNG kết quả `kb_service` khi thiếu artefact hoặc bất cứ gì trong đường graph
lỗi — bật backend này không bao giờ tệ hơn không bật.
"""

from __future__ import annotations

import asyncio
import logging

from noble_agent.agent.rag import kb_service_adapter as ksa
from noble_agent.agent.rag.hipporag import artefact_store, expander
from noble_agent.agent.rag.hipporag.graph import HippoGraph, load_graph
from noble_agent.agent.rag.hipporag.triple_index import TripleIndex, load_triple_index
from noble_agent.config import settings
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("rag.hipporag.kb_adapter")

_RRF_K = 60

# Cache THEO TENANT. `expander.load()` legacy là một singleton toàn cục — dùng nó ở đây
# nghĩa là workspace mở sau đọc graph của workspace mở trước.
_graph_cache: dict[str, HippoGraph | None] = {}
_triple_cache: dict[str, TripleIndex | None] = {}


def reset_cache_for_tests() -> None:
    _graph_cache.clear()
    _triple_cache.clear()


def _doc_graph(path: str) -> HippoGraph | None:
    return load_graph(path)


def load_graph_for_tenant(tenant_id: str) -> HippoGraph | None:
    if tenant_id in _graph_cache:
        return _graph_cache[tenant_id]
    path = artefact_store.tai_ve(tenant_id)
    g = _doc_graph(path) if path else None
    _graph_cache[tenant_id] = g
    if g is not None:
        logger.info(
            "[hipporag.kb] graph %s loaded (%d passages, %d phrases)",
            tenant_id,
            g.num_passages(),
            g.num_phrases(),
        )
    return g


def load_triple_for_tenant(tenant_id: str) -> TripleIndex | None:
    if tenant_id in _triple_cache:
        return _triple_cache[tenant_id]
    graph_path, _npz = artefact_store.duong_dan_cache(tenant_id)
    idx = load_triple_index(graph_path)
    _triple_cache[tenant_id] = idx
    return idx


def thu_tu_rrf(hybrid_rows, ppr_rows) -> list[str]:
    """RRF của hai danh sách đã xếp hạng, trả THỨ TỰ point id.

    Trả thứ tự chứ không trả hàng: hàng thật đến từ hit của Qdrant (chữ MỚI) khi
    passage có trong hybrid, và từ node graph (chữ SNAPSHOT) khi nó chỉ có trong graph.
    """
    fused: dict[str, float] = {}
    for rank, row in enumerate(hybrid_rows):
        fused[row[0]] = fused.get(row[0], 0.0) + 1.0 / (_RRF_K + rank + 1)
    for rank, row in enumerate(ppr_rows):
        fused[row[0]] = fused.get(row[0], 0.0) + 1.0 / (_RRF_K + rank + 1)
    return [pid for pid, _s in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)]


async def _sparse_seed(tenant_id: str, query: str, top_m: int) -> dict[str, float]:
    """Khớp câu hỏi với TRIPLE đã embed; top-M triple seed PPR ở CẢ hai phrase node.

    Chỉ đường npz cục bộ: `HIPPORAG_TRIPLE_STORE=qdrant` không dùng được ở đây vì JWT
    Qdrant của pod chỉ mở đúng collection `<tenant>_documents`.
    """
    from noble_agent.data import embed_client

    idx = load_triple_for_tenant(tenant_id)
    if idx is None:
        return {}
    vecs = await embed_client.embed_dense([query], side="query")
    if not vecs:
        return {}
    loop = asyncio.get_running_loop()
    triples = await loop.run_in_executor(None, idx.search, vecs[0], top_m)
    seeds: dict[str, float] = {}
    for s_key, o_key, score in triples:
        if score <= 0:
            continue
        for key in (s_key, o_key):
            if key:
                seeds[key] = max(seeds.get(key, 0.0), score)
    return seeds


async def query_hipporag_kb_for_noble_kb(
    query: str,
    project_filter: str,
    top_k: int = 5,
    dinh_kem: list[dict] | None = None,
    du_an: list[str] | None = None,
    numbers: dict[str, int] | None = None,
) -> str:
    tenant_id = current_tenant()
    seed_k = max(settings.hipporag_seed_k, top_k)
    hits = await ksa.hits_for(query, project_filter, seed_k)

    try:
        graph = load_graph_for_tenant(tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.kb] graph load failed (%s) — kb_service fallback", exc)
        graph = None
    if graph is None or not hits:
        return ksa.render(hits[:top_k], dinh_kem, du_an, numbers)

    try:
        seed_rows = [
            (str(h.get("id") or ""), str(h.get("project_id") or ""), str(h.get("text") or ""), float(h.get("score") or 0.0))
            for h in hits
        ]
        phrase_seeds = (
            await _sparse_seed(tenant_id, query, settings.hipporag_sparse_seed_top_m)
            if settings.hipporag_sparse_seed_enabled
            else {}
        )
        loop = asyncio.get_running_loop()
        ppr_rows = await loop.run_in_executor(
            None,
            lambda: expander.expand(
                graph,
                seed_rows,
                alpha=settings.hipporag_ppr_alpha,
                iters=settings.hipporag_ppr_iters,
                seed_k=settings.hipporag_seed_k,
                top_k=max(top_k * 2, top_k),
                project_filter=project_filter,
                extra_seeds=phrase_seeds,
                sparse_weight=settings.hipporag_sparse_seed_weight if phrase_seeds else 0.0,
                passage_threshold=settings.hipporag_passage_seed_threshold,
                phrase_threshold=settings.hipporag_phrase_seed_threshold,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.kb] expand failed (%s) — kb_service fallback", exc)
        return ksa.render(hits[:top_k], dinh_kem, du_an, numbers)

    if not ppr_rows:
        return ksa.render(hits[:top_k], dinh_kem, du_an, numbers)

    theo_id = {str(h.get("id") or ""): h for h in hits}
    tu_graph = {row[0]: row for row in ppr_rows}
    ra: list[dict] = []
    for pid in thu_tu_rrf(seed_rows, ppr_rows):
        h = theo_id.get(pid)
        if h is not None:
            ra.append(h)
            continue
        row = tu_graph.get(pid)
        if row is None:
            continue
        # Passage CHỈ có trong graph: chữ là SNAPSHOT lúc build, và nó không mang
        # `file_public_url`/`section_path` nên `render` bỏ những phần đó — đúng thứ
        # `_format_kb_hits` đã đỡ (chỉ `text` là bắt buộc).
        ra.append({"id": pid, "project_id": row[2], "text": row[3], "score": row[1]})
        if len(ra) >= top_k:
            break

    if project_filter:
        ra = [h for h in ra if str(h.get("project_id") or "") == project_filter]
    logger.info("[hipporag.kb] %d hybrid + %d ppr -> %d (tenant=%s)", len(hits), len(ppr_rows), len(ra[:top_k]), tenant_id)
    return ksa.render(ra[:top_k], dinh_kem, du_an, numbers)
```

⚠️ Lỗi logic phải tránh trong `break`: `if len(ra) >= top_k: break` đặt trong nhánh graph-only nghĩa là nhánh hit-của-Qdrant không bao giờ dừng sớm. Đổi thành một phép kiểm ở ĐẦU vòng lặp:

```python
    for pid in thu_tu_rrf(seed_rows, ppr_rows):
        if len(ra) >= top_k:
            break
        h = theo_id.get(pid)
        ...
```

và bỏ dòng `break` ở cuối nhánh graph-only.

⚠️ `project_filter` lọc theo `project_id`: hit của Qdrant mang cả sentinel `__ALL__` (tài liệu dùng chung toàn tenant), nên lọc `== project_filter` sẽ VỨT tài liệu dùng chung mà `build_scope_filter` cố tình union vào. Phải cho sentinel đi qua:

```python
    if project_filter:
        cho_qua = {project_filter, qdrant_client.SYSTEM_ANCHOR}
        ra = [h for h in ra if str(h.get("project_id") or "") in cho_qua]
```

với `from noble_agent.data import qdrant_search as qdrant_client` ở đầu file. Đây là chỗ `adapter.py` legacy làm sai (nó lọc `row[1] == project_filter` trần) và là lý do backend mới không dùng lại hàm đó.

- [ ] **Step 4: Thêm nhánh dispatch**

Trong `src/noble_agent/agent/rag/noble_kb.py`, thêm nhánh ngay SAU nhánh `hipporag` (quanh dòng 86):

```python
    if backend == "hipporag_kb":
        return await _query_via_hipporag_kb(query, project, dinh_kem, du_an, numbers)
```

và thêm hàm này ngay sau `_query_via_hipporag`:

```python
async def _query_via_hipporag_kb(
    query: str,
    project_filter: str,
    dinh_kem: list[dict] | None,
    du_an: list[str] | None,
    numbers: dict[str, int] | None,
) -> str:
    """HippoRAG trên collection per-tenant: seed từ `kb_service`, PPR trên graph do
    Portal ghi, RRF fuse. Degrades về đúng kết quả `kb_service`."""
    try:
        from noble_agent.agent.rag.hipporag import kb_adapter

        result = await kb_adapter.query_hipporag_kb_for_noble_kb(
            query,
            project_filter,
            top_k=settings.kb_search_top_k if settings.kb_search_top_k > 0 else 5,
            dinh_kem=dinh_kem,
            du_an=du_an,
            numbers=numbers,
        )
        if result:
            logger.info("[noble_kb] hipporag_kb returned %d chars (project=%s)", len(result), project_filter or "ALL")
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] hipporag_kb error: %s — returning empty", exc)
        return ""
```

Cập nhật docstring đầu `noble_kb.py`: thêm một dòng cho `hipporag_kb`. `settings.kb_search_top_k` đã xác minh là có thật (`config.py:461`, mặc định `5`) — dùng nó chứ không dùng `hipporag_top_k`, để `hipporag_kb` trả đúng số hit mà `kb_service` trả.

- [ ] **Step 5: Khai backend trong `.env.example`**

Sửa dòng liệt kê backend trong `.env.example` của repo agent (quanh dòng 309):

```bash
# flat_store (default) | qdrant | hipporag | hipporag_kb | grep_faq | empty
```

và thêm ngay dưới khối `HIPPORAG_ARTEFACT_*` của Task 7:

```bash
# hipporag_kb = HippoRAG trên collection PER-TENANT đang sống (`<tenant>_documents`),
# khác `hipporag` vốn đọc clone legacy `noble_kb_hybrid` không tồn tại trên deployment
# này. Seed lấy từ đúng đường `kb_service`; graph do Portal build và ghi lên kho tệp
# (KB_HIPPO_ENABLED bên đó). Thiếu artefact ⇒ trả đúng kết quả `kb_service`.
```

- [ ] **Step 6: Chạy test, xác nhận xanh**

Run: `uv run pytest tests/unit/unified/rag tests/unit/unified/test_noble_kb_dispatch.py -q`
Expected: PASS. Mọi test legacy của hipporag (`test_hipporag_*.py`, 8 file) phải xanh không đổi — chúng là bằng chứng backend cũ còn byte-identical.

- [ ] **Step 7: Xác nhận file legacy không bị sửa**

Run: `git diff --stat origin/develop -- src/noble_agent/agent/rag/hipporag/`
Expected: chỉ `artefact_store.py` và `kb_adapter.py` xuất hiện, cả hai là file MỚI. Nếu `adapter.py`/`builder.py`/`expander.py`/`graph.py`/`openie.py`/`triple_index.py` xuất hiện thì đã phá Global Constraint — hoàn nguyên chúng.

- [ ] **Step 8: Chạy toàn bộ unit của agent, so baseline**

Run: `uv run pytest tests/unit -q`
Expected: PASS, bằng baseline + số bài mới. `tests/unit/unified/test_tool_ack.py` được biết là flaky theo thời gian — nếu chỉ nó đỏ, chạy lại riêng nó để xác nhận và NÓI RA trong báo cáo, đừng ghi là hồi quy.

- [ ] **Step 9: Commit — HAI commit**

```bash
git add src/noble_agent/agent/rag/hipporag/kb_adapter.py tests/unit/unified/rag/test_hipporag_kb_adapter.py
git -c user.name="haidt" commit -m "feat(rag): hipporag_kb backend over the live per-tenant collection with a per-tenant graph cache"

git add src/noble_agent/agent/rag/noble_kb.py .env.example
git -c user.name="haidt" commit -m "feat(rag): dispatch NOBLE_RAG_BACKEND=hipporag_kb"
```

---

### Task 10: Báo cáo và bàn giao

**Files:** không tạo/sửa file nào trong repo.

- [ ] **Step 1: Xác nhận không có gì lọt vào frontend**

Run: `cd /home/thanhhai/Desktop/odyssey-portal-frontend && git log --oneline origin/develop..HEAD && git status --short`
Expected: không commit nào, working tree sạch.

- [ ] **Step 2: In trạng thái cả ba repo**

```bash
for r in odyssey-portal-backend odyssey-portal-frontend odyssey-agent; do
  echo "=== $r ==="
  git -C /home/thanhhai/Desktop/$r log --oneline origin/develop..HEAD
  git -C /home/thanhhai/Desktop/$r status --short
done
```

- [ ] **Step 3: Soạn nội dung Change Log để người dùng tự dán**

KHÔNG sửa `CLAUDE.md` — nhiều người cùng sửa file đó. Soạn một dòng cho mỗi repo và giao lại trong tin nhắn cuối:

- portal-backend: cờ `KB_HIPPO_ENABLED`, job `kb_hippo_build`, package `modules/kb/hippo/`, method `QdrantStore.scroll_payloads`, CLI `portal.cli.hippo_build`, hợp đồng `docs/contracts/hipporag-graph.md`, và ràng buộc "chỉ chunk `published` vào graph" cùng lý do an ninh của nó.
- agent: backend `NOBLE_RAG_BACKEND=hipporag_kb`, năm biến `HIPPORAG_ARTEFACT_*`/`HIPPORAG_CACHE_DIR`, việc `kb_service_adapter` tách thành `hits_for`/`render`, và việc backend `hipporag` legacy vẫn parked không đụng.

- [ ] **Step 4: In lệnh push**

```bash
cd /home/thanhhai/Desktop/odyssey-portal-backend && git push -u origin feat/hippo-rag
cd /home/thanhhai/Desktop/odyssey-agent && git push -u origin feat/hippo-rag
```

Không push. Không mở MR.

- [ ] **Step 5: Nêu rõ những gì CHƯA được chứng minh**

Báo cáo phải nói thẳng: đoạn code này chưa từng chạy trên dữ liệu thật, chưa gọi LLM thật, chưa ghi kho tệp thật, chưa bật cờ ở đâu. Cộng ba việc phải làm trước lần đầu bật cờ:

1. Đối chiếu `model: qwen-plus` của profile `openie_triple` với tài khoản DashScope thật.
2. Chạy `python -m portal.cli.hippo_build --tenant <một tenant dev> --renew` rồi kiểm artefact trên kho tệp.
3. Xác nhận embed service mà portal dùng (`KB_EMBED_URL`) và embed mà agent dùng (`EMBED_BACKEND`) là cùng một model — khác vector space là nhiễu không lỗi nào.

---

## Self-Review

**Spec coverage:**

| Mục spec | Task |
|---|---|
§5.1 `hippo/contracts.py` · `graph.py` | 1
§5.1 `openie.py` + profile prompt | 2
§5.1 `artefact.py` | 3
§5.2 handler + `scroll_payloads` | 4
§5.2 wrapper + cờ `KB_HIPPO_ENABLED` + `.env.example` | 5
§5.2 CLI backfill | 6
§5.3 ràng buộc cùng embed service | 3 (hợp đồng) + 10 (checklist trước khi bật)
§6 `artefact_store.py` + settings | 7
§6 `kb_adapter.py` + cache theo tenant | 9
§6 nhánh dispatch + `.env.example` | 9
§6 không đụng file legacy | 9 Step 7 (cổng `git diff --stat`)
§7 hợp đồng artefact | 3
§9 test portal | 1, 2, 3, 4, 5, 6
§9 test agent | 7, 8, 9
Không migration | Global Constraints + không task nào tạo file `migrations/`
Frontend không đụng | 10 Step 1
§2.3 lỗi `content_hash` | 1 (`test_ba_chunk_cung_record_ra_ba_passage`) + 4 (`test_ba_chunk_cung_content_hash_deu_duoc_boc`)

Hai việc KHÔNG có trong spec mà plan thêm, vì đọc code mới phát hiện — cả hai đã ghi lý do tại chỗ:

- **Task 8** (tách `kb_service_adapter`): spec chỉ nói backend mới "seed từ `kb_service_adapter` hybrid" mà không nói lấy bằng cách nào. Hàm cũ là một khối 80 dòng làm cả tìm lẫn render; sao chép khối embed+search là tạo một bản sao sẽ lệch.
- **Ràng buộc `status == 'published'`** (Task 4): spec không nêu. Nó là ràng buộc an ninh và có bài test riêng.

**Placeholder scan:** không có TBD/TODO; mọi step có code thật đều mang code đầy đủ; không step nào nói "tương tự Task N".

**Type consistency:** `Chunk`/`Triple` khai ở Task 1 dùng nguyên tên field ở Task 2/4. `Graph.can_boc/them_passage/xoa_passage/point_ids/to_json/from_json` khai Task 1, dùng Task 3/4. `artefact.doc_graph/ghi` khai Task 3, dùng Task 4. `build.chay_mot_luot` khai Task 4, dùng Task 5. `xep_build` mọc thêm hai keyword (`bo_qua_trung` ở Task 5, `renew` ở Task 6) — cả hai lần đều nói rõ chữ ký cuối. `hits_for/render` khai Task 8, dùng Task 9. `artefact_store.tai_ve/duong_dan_cache` khai Task 7, dùng Task 9.
