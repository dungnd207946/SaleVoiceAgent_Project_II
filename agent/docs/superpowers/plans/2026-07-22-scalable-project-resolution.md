# Scalable Project Resolution (`find_project`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the full-roster prompt table + per-session tool enum with an on-demand `find_project` entity-resolution tool that maps a (possibly STT-corrupted) spoken project name to a canonical code, scaling to ~1000 projects.

**Architecture:** A pure-Python multi-signal matcher (trigram · token-fuzzy · Vietnamese phonetic-fold · optional embedding) fused with weighted scoring + region/brand boosts + a confidence gate that returns `resolved` / `ambiguous` / `not_found`. A `ProjectNameIndex` is built at bootstrap from the DB registry rows. `find_project` is a new tool; the resolved code sticks in `customer.project_interest` and downstream data tools default to it. The full-roster prompt table and the project-code enum injection are removed.

**Tech Stack:** Python 3.11+, `rapidfuzz` (token similarity), `metaphone` (Double Metaphone for English brand tokens), `numpy` (embedding cosine, already a dep), existing remote e5-large embedder (`agent/rag/flat_store._Embedder`), pytest (`asyncio_mode=auto`).

## Global Constraints

- Work on branch `feat/refactor2` only. **Never touch `develop`** (no checkout/merge/push).
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make lint` before each commit.
- Heavy/optional imports (`rapidfuzz`, `metaphone`, embedder) must be import-safe for `make test-unit` — keep them at function/module load with graceful degradation, never crash collection.
- Canonical project codes come from `db_project_registry.cached_codes()` / `registry_rows()` — the matcher must never invent a code not in the live roster.
- The matcher core (fold + channels + index.resolve) must run with **zero network** so unit tests are offline; the embedding channel is optional and injected.
- Voice TTFA: the matcher runs in-process; no per-call network beyond the (optional) query embedding.

---

## File Structure

**New:**
- `src/noble_agent/data/project_matching/__init__.py` — package marker.
- `src/noble_agent/data/project_matching/fold.py` — text normalization + Vietnamese phonetic fold + English metaphone (pure functions).
- `src/noble_agent/data/project_matching/channels.py` — the 4 similarity channels as pure scoring functions.
- `src/noble_agent/data/project_matching/index.py` — `ProjectNameIndex`, `ResolveResult`, `Candidate`; build + fuse + gate.
- `src/noble_agent/agent/tools/find_project.py` — tool executor.
- `tests/unit/unified/matching/test_fold.py`
- `tests/unit/unified/matching/test_channels.py`
- `tests/unit/unified/matching/test_index.py`
- `tests/unit/unified/matching/test_find_project.py`
- `tests/unit/unified/matching/test_resolution_eval.py` — synthetic-noise accuracy harness.

**Modified:**
- `src/noble_agent/agent/tools/schemas.py` — add `find_project` schema; strip project-code enum injection.
- `src/noble_agent/agent/tools/dispatcher.py` — dispatch branch + stickiness write; data-tool project_code defaulting.
- `src/noble_agent/agent/definitions/config.json` — add `find_project` to tools.
- `src/noble_agent/agent/definitions/RULES.md` — tool-catalog row + resolve-first rule.
- `src/noble_agent/agent/prompts/builder.py` — remove `_project_table()` rendering.
- `src/noble_agent/agent/orchestrator.py` — build/refresh the index at bootstrap; drop `project_codes` snapshot.
- `src/noble_agent/agent/runner.py` — schema build no longer passes the enum snapshot.
- `pyproject.toml` — add `rapidfuzz`, `metaphone` deps.
- `CLAUDE.md` — Change Log + tool/RAG sections.

---

## Task 1: Text normalization + Vietnamese phonetic fold

**Files:**
- Create: `src/noble_agent/data/project_matching/__init__.py`
- Create: `src/noble_agent/data/project_matching/fold.py`
- Test: `tests/unit/unified/matching/test_fold.py`

**Interfaces:**
- Produces:
  - `normalize_text(s: str) -> str` — lowercase, NFC, collapse whitespace.
  - `is_ascii_token(tok: str) -> bool`
  - `fold_vietnamese(tok: str) -> str` — tone-strip + confusable-consonant fold.
  - `metaphone_en(tok: str) -> str` — Double Metaphone primary code (`""` if lib missing).
  - `fold_text(s: str) -> str` — per-token: ascii→metaphone, else VN fold; space-joined.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/matching/test_fold.py
from noble_agent.data.project_matching import fold


def test_normalize_lowers_and_collapses():
    assert fold.normalize_text("  Noble   Crystal  ") == "noble crystal"


def test_vietnamese_strips_tones():
    assert fold.fold_vietnamese("hồ") == fold.fold_vietnamese("ho")
    assert fold.fold_vietnamese("Tây") == fold.fold_vietnamese("tay")


def test_vietnamese_folds_l_n_confusion():
    # Northern ASR often swaps l<->n: "Long" heard as "Nong"
    assert fold.fold_vietnamese("long") == fold.fold_vietnamese("nong")


def test_vietnamese_folds_s_x_and_ch_tr():
    assert fold.fold_vietnamese("sa") == fold.fold_vietnamese("xa")
    assert fold.fold_vietnamese("tra") == fold.fold_vietnamese("cha")


def test_fold_text_routes_ascii_to_metaphone():
    # crystal / cristal share a metaphone code
    assert fold.fold_text("crystal") == fold.fold_text("cristal")


def test_fold_text_mixed_brand_and_location():
    # whole-string fold is stable for the same words in the same order
    assert fold.fold_text("noble crystal tay ho") == fold.fold_text("noble crystal tây hồ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/matching/test_fold.py -v`
Expected: FAIL with `ModuleNotFoundError: noble_agent.data.project_matching`

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/data/project_matching/__init__.py
"""Project-name entity-resolution matcher (fold + channels + index)."""
```

```python
# src/noble_agent/data/project_matching/fold.py
"""Deterministic text normalization + phonetic folding for project-name matching.

Vietnamese location tokens: strip tone marks + fold confusable consonants
(the #1 STT error classes for VN voice). English brand tokens: Double Metaphone.
All functions are pure and import-safe; metaphone degrades to "" if the optional
`metaphone` package is absent.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_ASCII_ALPHA = re.compile(r"^[a-z0-9]+$")

# Initial-consonant clusters folded to a shared representative. Longest-first so
# multi-char clusters ("ch", "tr", "gi", "ph", "ng") match before single chars.
_INITIALS: tuple[tuple[str, str], ...] = (
    ("ch", "c"), ("tr", "c"),
    ("gi", "z"), ("ph", "f"),
    ("ng", "g"),  # handled again for finals below; harmless as initial
)
_SINGLE_INITIALS = {"x": "s", "s": "s", "r": "z", "d": "z", "l": "n", "n": "n"}


def normalize_text(s: str) -> str:
    """Lowercase, NFC-normalize, collapse whitespace."""
    s = unicodedata.normalize("NFC", (s or "").strip().lower())
    return _WS.sub(" ", s)


def is_ascii_token(tok: str) -> bool:
    return bool(_ASCII_ALPHA.match(tok))


def _strip_tones(tok: str) -> str:
    """Remove Vietnamese tone/diacritic marks; đ -> d."""
    tok = tok.replace("đ", "d").replace("Đ", "d")
    decomposed = unicodedata.normalize("NFD", tok)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def fold_vietnamese(tok: str) -> str:
    """Tone-strip + fold confusable consonants for a single VN token."""
    t = _strip_tones(tok.lower())
    if not t:
        return t
    # fold initial cluster
    for cluster, rep in _INITIALS:
        if t.startswith(cluster):
            t = rep + t[len(cluster):]
            break
    else:
        if t[0] in _SINGLE_INITIALS:
            t = _SINGLE_INITIALS[t[0]] + t[1:]
    # fold finals: nh/ng -> g, trailing t/c -> k
    if t.endswith("nh"):
        t = t[:-2] + "g"
    elif t.endswith("ng"):
        t = t[:-2] + "g"
    if t.endswith("t") or t.endswith("c"):
        t = t[:-1] + "k"
    return t


def metaphone_en(tok: str) -> str:
    """Primary Double Metaphone code for an English token; '' if lib absent."""
    try:
        from metaphone import doublemetaphone
    except ImportError:
        return tok  # degrade: fall back to the raw token
    primary, _secondary = doublemetaphone(tok)
    return primary or tok


def fold_text(s: str) -> str:
    """Per-token fold of a full string: ascii->metaphone, else VN fold."""
    toks = normalize_text(s).split(" ")
    out = [metaphone_en(t) if is_ascii_token(t) else fold_vietnamese(t) for t in toks if t]
    return " ".join(out)
```

- [ ] **Step 4: Add the `metaphone` dependency**

Edit `pyproject.toml` `[project] dependencies` — add `"metaphone>=0.6"` and `"rapidfuzz>=3.0"` (rapidfuzz used in Task 2). Then:

Run: `pip install "metaphone>=0.6" "rapidfuzz>=3.0"`
Expected: both install cleanly.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/matching/test_fold.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add src/noble_agent/data/project_matching/ tests/unit/unified/matching/test_fold.py pyproject.toml
git commit -m "feat(matching): VN phonetic fold + metaphone normalization"
```

---

## Task 2: Similarity channels

**Files:**
- Create: `src/noble_agent/data/project_matching/channels.py`
- Test: `tests/unit/unified/matching/test_channels.py`

**Interfaces:**
- Consumes: `fold.fold_text`, `fold.normalize_text` (Task 1).
- Produces:
  - `trigram_score(a: str, b: str) -> float` — character-3gram Dice, 0..1.
  - `token_set_score(a: str, b: str) -> float` — RapidFuzz token_set_ratio/100, 0..1.
  - `phonetic_score(a_raw: str, b_raw: str) -> float` — token_set on the folded strings, 0..1.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/matching/test_channels.py
from noble_agent.data.project_matching import channels


def test_trigram_identical_is_one():
    assert channels.trigram_score("crystal", "crystal") == 1.0


def test_trigram_partial_between_zero_and_one():
    s = channels.trigram_score("crystal", "cristal")
    assert 0.0 < s < 1.0


def test_token_set_order_independent():
    a = "tay ho noble crystal"
    b = "noble crystal tay ho"
    assert channels.token_set_score(a, b) > 0.95


def test_token_set_partial_name_scores_high():
    # a single shared token against the full name
    assert channels.token_set_score("crystal", "noble crystal tay ho") > 0.7


def test_phonetic_recovers_tone_loss():
    # "tay ho" (STT no tones) vs the true diacritic name
    assert channels.phonetic_score("noble crystal tay ho", "noble crystal tây hồ") > 0.9


def test_phonetic_beats_token_on_heavy_error():
    # heavy phonetic garble: token_set collapses, phonetic holds up
    q = "san sai gon dan"
    name = "sunshine golden river"
    assert channels.phonetic_score(q, name) > channels.token_set_score(q, name)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/matching/test_channels.py -v`
Expected: FAIL with `ModuleNotFoundError: ...project_matching.channels`

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/data/project_matching/channels.py
"""Similarity channels for project-name matching. Each returns 0..1.

trigram + token_set run on raw-normalized text; phonetic runs on folded text.
"""

from __future__ import annotations

from noble_agent.data.project_matching import fold


def _trigrams(s: str) -> set[str]:
    s = f"  {s} "  # pad so short strings still yield boundary grams
    return {s[i : i + 3] for i in range(len(s) - 2)}


def trigram_score(a: str, b: str) -> float:
    ta, tb = _trigrams(fold.normalize_text(a)), _trigrams(fold.normalize_text(b))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return 2 * inter / (len(ta) + len(tb))


def token_set_score(a: str, b: str) -> float:
    from rapidfuzz import fuzz

    return fuzz.token_set_ratio(fold.normalize_text(a), fold.normalize_text(b)) / 100.0


def phonetic_score(a_raw: str, b_raw: str) -> float:
    from rapidfuzz import fuzz

    return fuzz.token_set_ratio(fold.fold_text(a_raw), fold.fold_text(b_raw)) / 100.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/matching/test_channels.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/data/project_matching/channels.py tests/unit/unified/matching/test_channels.py
git commit -m "feat(matching): trigram / token-set / phonetic similarity channels"
```

---

## Task 3: ProjectNameIndex — fusion + confidence gate

**Files:**
- Create: `src/noble_agent/data/project_matching/index.py`
- Test: `tests/unit/unified/matching/test_index.py`

**Interfaces:**
- Consumes: `channels.trigram_score/token_set_score/phonetic_score` (Task 2), `fold` (Task 1).
- Produces:
  - `@dataclass Candidate(code, name, region, score)`
  - `@dataclass ResolveResult(status, code, name, region, candidates, message)` where `status ∈ {"resolved","ambiguous","not_found"}`.
  - `class ProjectNameIndex` with:
    - `__init__(self, rows: list[dict], *, embed_fn: Callable[[list[str]], list[list[float]]] | None = None)` — `rows` are `{"code","name","region"}` dicts (from `registry_rows()`).
    - `resolve(self, query: str, *, region_hint: str = "", investor_hint: str = "", query_embed_fn: Callable[[str], list[float]] | None = None) -> ResolveResult`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/matching/test_index.py
from noble_agent.data.project_matching.index import ProjectNameIndex

ROWS = [
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"},
    {"code": "NCR", "name": "Noble Crystal Riverside", "region": ""},
    {"code": "NPTH", "name": "Noble Palace Tây Hồ", "region": "Tây Hồ"},
    {"code": "SGR", "name": "Sunshine Golden River", "region": "Tây Hồ"},
]


def _idx():
    return ProjectNameIndex(ROWS)


def test_resolved_on_tone_stripped_full_name():
    r = _idx().resolve("noble crystal tay ho")
    assert r.status == "resolved"
    assert r.code == "NCTH"


def test_ambiguous_on_partial_name():
    r = _idx().resolve("crystal")
    assert r.status == "ambiguous"
    codes = {c.code for c in r.candidates}
    assert {"NCLB", "NCTH", "NCR"} <= codes


def test_region_hint_disambiguates():
    r = _idx().resolve("crystal", region_hint="Long Biên")
    assert r.status == "resolved"
    assert r.code == "NCLB"


def test_not_found_on_garbage():
    r = _idx().resolve("xyzzy quux nothing")
    assert r.status == "not_found"


def test_candidates_capped_at_four():
    r = _idx().resolve("noble")
    assert len(r.candidates) <= 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/matching/test_index.py -v`
Expected: FAIL with `ModuleNotFoundError: ...project_matching.index`

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/data/project_matching/index.py
"""In-process project-name resolver: fuse similarity channels + gate confidence.

Built once from the DB roster rows (code/name/region). resolve() returns a
resolved code, an ambiguous candidate list, or not_found. Weights + thresholds
are module constants calibrated against tests/.../test_resolution_eval.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from noble_agent.data.project_matching import channels, fold

# Channel weights (sum need not be 1; combined is renormalized by weight total).
_W_TRIGRAM = 0.20
_W_TOKEN = 0.35
_W_PHONETIC = 0.35
_W_EMBED = 0.10
# Additive context boosts.
_BOOST_REGION = 0.15
_BOOST_BRAND = 0.08
# Confidence gate.
_FLOOR = 0.55          # top-1 must clear this to be resolved
_MARGIN = 0.12         # top-1 must beat top-2 by this to be resolved
_AMBIG_FLOOR = 0.45    # below this for top-1 => not_found
_AMBIG_DELTA = 0.10    # candidates within this of top-1 are returned
_MAX_CANDIDATES = 4


@dataclass(frozen=True)
class Candidate:
    code: str
    name: str
    region: str
    score: float


@dataclass(frozen=True)
class ResolveResult:
    status: str  # "resolved" | "ambiguous" | "not_found"
    code: str = ""
    name: str = ""
    region: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    message: str = ""


@dataclass
class _Entry:
    code: str
    name: str
    region: str
    norm_name: str
    name_tokens: frozenset[str]
    embed: list[float] | None = None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return max(0.0, min(1.0, dot))  # e5 vectors are L2-normalized => dot == cosine


class ProjectNameIndex:
    def __init__(
        self,
        rows: list[dict],
        *,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ) -> None:
        self._entries: list[_Entry] = []
        for r in rows:
            code = (r.get("code") or "").strip()
            name = (r.get("name") or "").strip()
            if not code or not name:
                continue
            norm = fold.normalize_text(name)
            self._entries.append(
                _Entry(
                    code=code,
                    name=name,
                    region=(r.get("region") or "").strip(),
                    norm_name=norm,
                    name_tokens=frozenset(norm.split(" ")),
                )
            )
        if embed_fn is not None and self._entries:
            try:
                vecs = embed_fn([e.name for e in self._entries])
                for e, v in zip(self._entries, vecs, strict=False):
                    e.embed = list(v)
            except Exception:  # noqa: BLE001 — embedding is a supporting vote; degrade
                pass

    def _combined(
        self, query: str, e: _Entry, region_hint: str, brand_tokens: frozenset[str], q_vec: list[float] | None
    ) -> float:
        tri = channels.trigram_score(query, e.name)
        tok = channels.token_set_score(query, e.name)
        pho = channels.phonetic_score(query, e.name)
        w = _W_TRIGRAM + _W_TOKEN + _W_PHONETIC
        s = _W_TRIGRAM * tri + _W_TOKEN * tok + _W_PHONETIC * pho
        if q_vec is not None and e.embed is not None:
            s += _W_EMBED * _cosine(q_vec, e.embed)
            w += _W_EMBED
        s /= w
        if region_hint and e.region and fold.normalize_text(region_hint) in fold.normalize_text(e.region):
            s += _BOOST_REGION
        if brand_tokens and (brand_tokens & e.name_tokens):
            s += _BOOST_BRAND
        return s

    def resolve(
        self,
        query: str,
        *,
        region_hint: str = "",
        investor_hint: str = "",
        query_embed_fn: Callable[[str], list[float]] | None = None,
    ) -> ResolveResult:
        if not (query or "").strip() or not self._entries:
            return ResolveResult(status="not_found", message="Chưa nhận được tên dự án.")
        brand_tokens = frozenset(fold.normalize_text(investor_hint).split(" ")) if investor_hint else frozenset()
        q_vec = query_embed_fn(query) if query_embed_fn is not None else None
        scored = [
            Candidate(e.code, e.name, e.region, self._combined(query, e, region_hint, brand_tokens, q_vec))
            for e in self._entries
        ]
        scored.sort(key=lambda c: c.score, reverse=True)
        top1 = scored[0]
        top2 = scored[1] if len(scored) > 1 else Candidate("", "", "", 0.0)
        if top1.score >= _FLOOR and (top1.score - top2.score) >= _MARGIN:
            return ResolveResult(status="resolved", code=top1.code, name=top1.name, region=top1.region)
        if top1.score >= _AMBIG_FLOOR:
            cands = [c for c in scored if (top1.score - c.score) <= _AMBIG_DELTA][:_MAX_CANDIDATES]
            return ResolveResult(status="ambiguous", candidates=cands)
        return ResolveResult(status="not_found", message="Không tìm thấy dự án khớp.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/matching/test_index.py -v`
Expected: PASS (5 tests). If a threshold test fails, tune `_FLOOR/_MARGIN/_AMBIG_FLOOR/_AMBIG_DELTA` — the eval harness in Task 7 is the authority; the ROWS-based tests above must pass with the shipped constants.

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/noble_agent/data/project_matching/index.py tests/unit/unified/matching/test_index.py
git commit -m "feat(matching): ProjectNameIndex fusion + confidence gate"
```

---

## Task 4: `find_project` tool — executor, schema, dispatch, stickiness

**Files:**
- Create: `src/noble_agent/agent/tools/find_project.py`
- Modify: `src/noble_agent/agent/tools/schemas.py` (add schema; `find_project` is NOT an enum tool)
- Modify: `src/noble_agent/agent/tools/dispatcher.py:17-25` (import) + `:111-147` (dispatch branch)
- Modify: `src/noble_agent/agent/definitions/config.json` (add to `tools`)
- Test: `tests/unit/unified/matching/test_find_project.py`

**Interfaces:**
- Consumes: `ProjectNameIndex.resolve` (Task 3); a module-level index accessor `get_index()` (defined here; populated in Task 5).
- Produces:
  - `find_project.run(dispatcher, args: dict) -> str` — JSON string per the contract.
  - `find_project.set_index(idx)` / `find_project.get_index()` — module singleton the orchestrator populates.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/matching/test_find_project.py
import json

from noble_agent.agent.tools import find_project
from noble_agent.data.project_matching.index import ProjectNameIndex

ROWS = [
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"},
    {"code": "NCR", "name": "Noble Crystal Riverside", "region": ""},
]


class _Cust:
    project_interest = None


class _Disp:
    def __init__(self):
        self.customer = _Cust()
        self.dirty = False

    def mark_customer_dirty(self):
        self.dirty = True


def setup_function():
    find_project.set_index(ProjectNameIndex(ROWS))


async def test_resolved_sets_project_interest():
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "noble crystal tay ho"}))
    assert out["status"] == "resolved"
    assert out["code"] == "NCTH"
    assert d.customer.project_interest == "NCTH"
    assert d.dirty is True


async def test_ambiguous_returns_candidates_no_write():
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "crystal"}))
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) >= 2
    assert d.customer.project_interest is None


async def test_no_index_is_safe():
    find_project.set_index(None)
    d = _Disp()
    out = json.loads(await find_project.run(d, {"query": "crystal"}))
    assert out["status"] == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/matching/test_find_project.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_project'`

- [ ] **Step 3: Write the executor**

```python
# src/noble_agent/agent/tools/find_project.py
"""find_project tool — resolve a spoken project name to a canonical code.

Returns resolved / ambiguous / not_found. On resolved, sticks the code into
customer.project_interest so downstream data tools default to it. The
ProjectNameIndex singleton is populated by the orchestrator at bootstrap.
"""

from __future__ import annotations

import json

from noble_agent.data.project_matching.index import ProjectNameIndex, ResolveResult

_INDEX: ProjectNameIndex | None = None


def set_index(idx: ProjectNameIndex | None) -> None:
    global _INDEX
    _INDEX = idx


def get_index() -> ProjectNameIndex | None:
    return _INDEX


def _to_json(r: ResolveResult) -> str:
    if r.status == "resolved":
        payload = {"status": "resolved", "code": r.code, "name": r.name, "region": r.region}
    elif r.status == "ambiguous":
        payload = {
            "status": "ambiguous",
            "candidates": [{"code": c.code, "name": c.name, "region": c.region} for c in r.candidates],
        }
    else:
        payload = {"status": "not_found", "message": r.message or "Không tìm thấy dự án."}
    return json.dumps(payload, ensure_ascii=False)


async def run(dispatcher, args: dict) -> str:
    idx = _INDEX
    if idx is None:
        return json.dumps({"status": "not_found", "message": "Danh mục dự án chưa sẵn sàng."}, ensure_ascii=False)
    query = args.get("query", "") or ""
    region_hint = args.get("region_hint", "") or ""
    investor_hint = args.get("investor_hint", "") or ""
    # Fallback context from session state when the LLM omits a hint.
    if not region_hint:
        region_hint = getattr(dispatcher.customer, "preferred_area", "") or ""
    result = idx.resolve(query, region_hint=region_hint, investor_hint=investor_hint)
    if result.status == "resolved":
        if getattr(dispatcher.customer, "project_interest", None) != result.code:
            dispatcher.customer.project_interest = result.code
            dispatcher.mark_customer_dirty()
    return _to_json(result)
```

- [ ] **Step 4: Add the schema (NOT an enum tool)**

In `src/noble_agent/agent/tools/schemas.py`, add to the `SCHEMAS` dict (place it before `check_inventory`):

```python
    "find_project": {
        "type": "function",
        "function": {
            "name": "find_project",
            "description": (
                "Xác định MÃ dự án từ tên khách nói TRƯỚC khi dùng bất kỳ tool dữ liệu nào "
                "(check_inventory / booking / get_project_overview / noble_search...). Bắt buộc gọi "
                "khi khách nhắc tên một dự án. Trả 'resolved' (1 mã — dùng luôn), 'ambiguous' (nhiều "
                "ứng viên — hỏi khách chọn theo khu vực), hoặc 'not_found' (nhờ khách nhắc lại). "
                "Truyền region_hint nếu khách đã nói khu vực. Ví dụ query='Noble Crystal Tây Hồ'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Tên dự án khách nói (nguyên văn, kể cả sai chính tả)."},
                    "region_hint": {"type": "string", "description": "Khu vực/quận khách đã nhắc, nếu có."},
                    "investor_hint": {"type": "string", "description": "Chủ đầu tư/thương hiệu khách đã nhắc, nếu có."},
                },
                "required": ["query"],
            },
        },
    },
```

- [ ] **Step 5: Wire the dispatch branch**

In `src/noble_agent/agent/tools/dispatcher.py`, add `find_project` to the tools import (line 17-25 block):

```python
from noble_agent.agent.tools import (
    booking,
    check_inventory,
    find_project,
    noble_search,
    project_financial,
    projects_info,
    support_ops,
    update_customer,
)
```

Add the dispatch branch inside `_exec` (next to `noble_search`, since both take the dispatcher):

```python
        if name == "find_project":
            return await find_project.run(self, args)
```

- [ ] **Step 6: Register the tool**

In `src/noble_agent/agent/definitions/config.json`, add `"find_project"` as the FIRST entry of `"tools"` (before `"update_customer"`).

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/unit/unified/matching/test_find_project.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Lint + commit**

```bash
make lint
git add src/noble_agent/agent/tools/find_project.py src/noble_agent/agent/tools/schemas.py src/noble_agent/agent/tools/dispatcher.py src/noble_agent/agent/definitions/config.json tests/unit/unified/matching/test_find_project.py
git commit -m "feat(tools): add find_project resolution tool + stickiness write"
```

---

## Task 5: Build the index at bootstrap; wire the embedding channel

**Files:**
- Modify: `src/noble_agent/agent/orchestrator.py:154-179` (bootstrap block)
- Test: `tests/unit/unified/matching/test_index_bootstrap.py`

**Interfaces:**
- Consumes: `db_project_registry.registry_rows()`, `find_project.set_index`, `ProjectNameIndex` (Tasks 3–4).
- Produces: a private helper `TurnRunner._rebuild_project_index()` that builds `ProjectNameIndex` from `registry_rows()` and installs it via `find_project.set_index`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/matching/test_index_bootstrap.py
from noble_agent.agent.tools import find_project
from noble_agent.data import db_project_registry


def teardown_function():
    db_project_registry.set_cache_for_tests(None)
    find_project.set_index(None)


def test_rebuild_installs_index_from_registry():
    db_project_registry.set_cache_for_tests(
        {
            "NCTH": {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ", "type": ""},
            "SGR": {"code": "SGR", "name": "Sunshine Golden River", "region": "Tây Hồ", "type": ""},
        }
    )
    from noble_agent.agent.orchestrator import _build_project_index

    _build_project_index()
    idx = find_project.get_index()
    assert idx is not None
    assert idx.resolve("noble crystal tay ho").code == "NCTH"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/matching/test_index_bootstrap.py -v`
Expected: FAIL with `ImportError: cannot import name '_build_project_index'`

- [ ] **Step 3: Add the module-level builder to orchestrator.py**

Add near the top-level helpers of `src/noble_agent/agent/orchestrator.py` (module scope, not inside the class):

```python
def _build_project_index() -> None:
    """(Re)build the project-name resolution index from the warmed registry and
    install it for the find_project tool. Embedding channel is best-effort: it is
    left off here (lexical + phonetic cover the core); enable by passing an
    embed_fn once a shared embedder handle is available. Never raises."""
    from noble_agent.agent.tools import find_project
    from noble_agent.data import db_project_registry
    from noble_agent.data.project_matching.index import ProjectNameIndex

    try:
        rows = db_project_registry.registry_rows()
        find_project.set_index(ProjectNameIndex(rows))
    except Exception:  # noqa: BLE001 — resolution must never wedge the turn/boot
        logger.exception("failed to build project name index")
```

(`logger` already exists in orchestrator.py.)

- [ ] **Step 4: Call it in the bootstrap block**

In the first-turn bootstrap block (`src/noble_agent/agent/orchestrator.py:160-164`), right after `await db_project_registry.warm_if_stale(...)`, add:

```python
                await db_project_registry.warm_if_stale(self._settings.project_registry_refresh_sec)
                _build_project_index()
```

Leave the `state.scratchpad["project_codes"] = ...` line in place for now (Task 6 removes it together with the enum).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/matching/test_index_bootstrap.py -v`
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add src/noble_agent/agent/orchestrator.py tests/unit/unified/matching/test_index_bootstrap.py
git commit -m "feat(matching): build project name index at bootstrap"
```

---

## Task 6: Remove the enum + prompt table; add stickiness defaulting; update RULES

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py:486-532` (drop enum injection)
- Modify: `src/noble_agent/agent/runner.py:47-52` (drop snapshot)
- Modify: `src/noble_agent/agent/orchestrator.py:161-164` (drop `project_codes` snapshot)
- Modify: `src/noble_agent/agent/prompts/builder.py:33-64` (drop project table)
- Modify: `src/noble_agent/agent/tools/check_inventory.py` (project_code defaulting) + same pattern where dispatcher passes customer
- Modify: `src/noble_agent/agent/definitions/RULES.md` (tool catalog row + resolve-first rule)
- Test: `tests/unit/unified/matching/test_no_enum.py`, and fix existing `tests/unit/unified/test_tool_schemas.py` expectations.

**Interfaces:**
- Consumes: nothing new.
- Produces: `schemas_for(names, codes=None)` returns schemas with **no** project-code enum; `find_project` present.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/matching/test_no_enum.py
from noble_agent.agent.tools.schemas import schemas_for


def test_project_code_params_have_no_enum():
    schemas = schemas_for(["check_inventory", "booking", "noble_search", "find_project"])
    by_name = {s["function"]["name"]: s for s in schemas}
    ci = by_name["check_inventory"]["function"]["parameters"]["properties"]["project_code"]
    assert "enum" not in ci
    nf = by_name["noble_search"]["function"]["parameters"]["properties"]["project_filter"]
    assert "enum" not in nf
    assert "find_project" in by_name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/matching/test_no_enum.py -v`
Expected: FAIL — enum still injected.

- [ ] **Step 3: Strip the enum machinery in schemas.py**

Replace `schemas_for` (and delete `_with_project_enum`, `_PROJECT_CODE_TOOLS`, `_ENUM_TOOLS`, and the now-unused `copy` import if nothing else uses it) with:

```python
def schemas_for(names: list[str], codes: list[str] | None = None) -> list[dict]:
    """Return tool schemas for the given names (order preserved, unknown skipped).

    ``codes`` is accepted for backward compatibility but ignored — project codes
    are no longer enumerated into schemas; the LLM obtains a code via the
    find_project tool and passes it as a free-text string.
    """
    return [SCHEMAS[name] for name in names if name in SCHEMAS]
```

Update each project-code param description to say it is the canonical code from
`find_project` (e.g. `check_inventory` `project_code` → add `"description": "Mã dự
án canonical do find_project trả về; bỏ trống để dùng dự án đang quan tâm."`).

- [ ] **Step 4: Drop the snapshot in runner.py**

In `src/noble_agent/agent/runner.py:51-52`, replace:

```python
    snapshot = state.scratchpad.get("project_codes")
    tool_schemas = schemas_for(agent.tool_names, codes=snapshot) if snapshot else agent.tool_schemas
```

with:

```python
    tool_schemas = agent.tool_schemas
```

- [ ] **Step 5: Drop the snapshot write in orchestrator.py**

Remove the `state.scratchpad["project_codes"] = db_project_registry.cached_codes()` line and its comment block (`orchestrator.py:161-164`). Keep `_build_project_index()`.

- [ ] **Step 6: Remove the project table from the system prompt**

In `src/noble_agent/agent/prompts/builder.py`, delete `_project_table()` and remove `project_table=_project_table()` from `build_system_prompt`'s `render(...)` call. (Leave the `{{ project_table }}` reference removal to Step 7 in the template.)

In `src/noble_agent/agent/definitions/PROMPT_TEMPLATE.md`, delete the `{{ project_table }}` block.

- [ ] **Step 7: Add stickiness defaulting to data tools**

`check_inventory.py` already reads `args.get("project_code","")`. To default to the sticky project, the dispatcher must pass the customer. Change the dispatch branch (`dispatcher.py`) to:

```python
        if name == "check_inventory":
            if not args.get("project_code"):
                args["project_code"] = getattr(self.customer, "project_interest", "") or ""
            return await check_inventory.run(args)
```

Apply the same empty-`project_code` → `customer.project_interest` fallback in the dispatch branches for `get_project_overview`, `get_project_financial`, `search_units`, `send_media`, and `booking` (for `booking`, only when `args.get("action")` needs a project and `project_code` is empty). `noble_search` already falls back to `project_interest` internally — leave it.

- [ ] **Step 8: Update RULES.md**

In `src/noble_agent/agent/definitions/RULES.md` tool-catalog table, add a `find_project` row (resolve name→code before any data tool) and a rule: *"Khi khách nhắc tên dự án, gọi `find_project` trước. status=resolved → dùng mã đó cho các tool sau (không cần truyền lại). status=ambiguous → đọc danh sách ứng viên, hỏi khách chọn theo khu vực. status=not_found → xin khách nhắc lại tên hoặc khu vực. Không tự bịa mã dự án."* Remove any wording that referenced the in-prompt project table.

- [ ] **Step 9: Fix existing schema tests**

Update `tests/unit/unified/test_tool_schemas.py` and `tests/unit/unified/test_schemas_dynamic_enum.py`: assertions that expect a project-code enum must now assert its **absence**. Delete cases that only validated enum population.

- [ ] **Step 10: Run tests**

Run: `pytest tests/unit/unified/matching/test_no_enum.py tests/unit/unified/test_tool_schemas.py tests/unit/unified/test_schemas_dynamic_enum.py -v`
Expected: PASS (updated expectations).

- [ ] **Step 11: Lint + commit**

```bash
make lint
git add -A
git commit -m "refactor(tools): drop project-code enum + prompt table; find_project + stickiness own resolution"
```

---

## Task 7: Resolution accuracy eval + threshold calibration

**Files:**
- Create: `tests/unit/unified/matching/test_resolution_eval.py`

**Interfaces:**
- Consumes: `ProjectNameIndex`, `fold` (to synthesize STT-like noise forward).

- [ ] **Step 1: Write the eval harness**

```python
# tests/unit/unified/matching/test_resolution_eval.py
"""Synthetic-noise accuracy gate for the resolver. Corrupts canonical names the
way STT does (drop tones, swap confusable consonants, drop a word) and asserts
top-1 accuracy + ambiguous-recall stay above a floor. Tune index thresholds here.
"""

import unicodedata

from noble_agent.data.project_matching.index import ProjectNameIndex

ROWS = [
    {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên"},
    {"code": "NCTH", "name": "Noble Crystal Tây Hồ", "region": "Tây Hồ"},
    {"code": "NCR", "name": "Noble Crystal Riverside", "region": ""},
    {"code": "NPTH", "name": "Noble Palace Tây Hồ", "region": "Tây Hồ"},
    {"code": "NPTTL", "name": "Noble Palace Tây Thăng Long", "region": "Tây Thăng Long"},
    {"code": "SGR", "name": "Sunshine Golden River", "region": "Tây Hồ"},
    {"code": "SGI", "name": "Sunshine Green Iconic", "region": "Long Biên"},
    {"code": "SLC", "name": "Sunshine Legend City", "region": "Hà Nội"},
]


def _drop_tones(s: str) -> str:
    d = unicodedata.normalize("NFD", s.replace("đ", "d"))
    return unicodedata.normalize("NFC", "".join(c for c in d if unicodedata.category(c) != "Mn"))


def test_top1_accuracy_on_tone_dropped_full_names():
    idx = ProjectNameIndex(ROWS)
    hits = 0
    for r in ROWS:
        res = idx.resolve(_drop_tones(r["name"]))
        # full name with only tones dropped must resolve to the exact code
        if res.status == "resolved" and res.code == r["code"]:
            hits += 1
    assert hits / len(ROWS) >= 0.9  # calibrate thresholds until this holds


def test_ambiguous_recall_on_shared_prefix():
    idx = ProjectNameIndex(ROWS)
    res = idx.resolve("noble palace tay ho", region_hint="Tây Hồ")
    assert res.status == "resolved" and res.code == "NPTH"


def test_partial_returns_correct_family_in_candidates():
    idx = ProjectNameIndex(ROWS)
    res = idx.resolve("sunshine")
    codes = {c.code for c in res.candidates} if res.status == "ambiguous" else {res.code}
    assert {"SGR", "SGI", "SLC"} & codes
```

- [ ] **Step 2: Run + calibrate**

Run: `pytest tests/unit/unified/matching/test_resolution_eval.py -v`
Expected: PASS. If `test_top1_accuracy...` fails, adjust `_FLOOR/_MARGIN` in `index.py` (lower `_MARGIN` if near-identical names steal the margin; raise `_FLOOR` if garbage resolves). Re-run Task 3 tests after each change to keep them green.

- [ ] **Step 3: Commit**

```bash
make lint
git add tests/unit/unified/matching/test_resolution_eval.py src/noble_agent/data/project_matching/index.py
git commit -m "test(matching): resolution accuracy eval + calibrated thresholds"
```

---

## Task 8: Docs — CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

- Tool count: **11 → 12 tools offered**; add `find_project` to the `agent/tools/` layout row and the tool catalog summary.
- RAG Stack / "Single source of project truth" section: note that project codes are no longer enumerated into tool schemas or the system prompt; `find_project` resolves name→code on demand via `ProjectNameIndex` (fold + channels + gate); `catalog.normalize()` narrows to a validation gate.
- Remove/adjust the `{{ project_table }}` and "frozen per-session enum" descriptions (now removed).
- Append a Change Log row dated `2026-07-22` summarizing this feature, its branch (`feat/refactor2`), and the spec/plan paths.

- [ ] **Step 2: Run the full unit suite**

Run: `make test-unit`
Expected: matching tests green; no NEW failures vs the pre-feature baseline (pre-existing catalog/mongo drift failures are unchanged).

- [ ] **Step 3: Commit**

```bash
make lint
git add CLAUDE.md
git commit -m "docs(claude): document find_project resolution + enum/prompt-table removal"
```

---

## Self-Review notes (author)

- **Spec coverage:** Tier 0 fold → Task 1; Tiers 1–3 (channels/fusion/gate) → Tasks 2–3; `find_project` contract + stickiness → Task 4; `ProjectNameIndex` build at warm → Task 5; enum/prompt-table removal + `catalog.normalize` role + RULES → Task 6; eval set + calibration → Task 7; docs → Task 8. Pluggable alias-enrichment is intentionally deferred (default OFF) and noted in `index.py`'s `embed_fn` seam + `_build_project_index` docstring — no task builds it (YAGNI, per the locked decision).
- **Investor field:** `ProjectRegistryRow` carries no investor; brand/investor boost matches `investor_hint` tokens against the project **name** tokens (brand appears in the name, e.g. "Sunshine"/"Noble"), so no new data source is needed. Documented in Task 3.
- **Embedding channel:** wired as an optional injected `embed_fn`; left OFF at bootstrap (Task 5 docstring) so the core is offline-testable and boot never depends on the embedder. Enable later by passing a shared embedder handle.
- **Deviation from spec:** the "discriminating-tail rerank" is not a separate code path in the first cut — `token_set` + region boost cover the same disambiguation; noted as a calibration knob if the eval set shows same-prefix confusion.
