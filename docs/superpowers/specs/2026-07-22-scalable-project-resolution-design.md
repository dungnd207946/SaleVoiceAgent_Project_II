# Scalable Project Resolution (`find_project`) — Design

**Date:** 2026-07-22
**Branch:** `feat/refactor2`
**Status:** Approved design, pending implementation plan

## Problem

Every search/filter tool uses a canonical **project code** as its `project_id`. Today
those codes reach the LLM two ways, both of which enumerate the **entire** roster:

1. `builder._project_table()` renders **one line per project** (`CODE — name — region — type`)
   into the system prompt ([builder.py:33](../../../src/noble_agent/agent/prompts/builder.py#L33)).
2. `schemas_for(names, codes=)` injects a `["", *codes]` **enum** into every project-code
   param, frozen per session ([schemas.py:500](../../../src/noble_agent/agent/tools/schemas.py#L500)).

This works today only because the full name+code table sits in context, so the LLM can map a
slightly-wrong spoken name to the right code. At the target scale (**one tenant with up to
~1000 projects**) it breaks:

- **Prompt overflow** — ~1000 lines in the system prompt on every turn.
- **Reference accuracy collapses** — the LLM cannot reliably pick the correct code out of
  1000 near-identical names when STT introduces errors (wrong tones, confusable consonants,
  partial names). The current accuracy is an artifact of everything being in-context.

The agent is also intended to become a **provider for third parties** running real-estate
sales agents, so the solution must be general (not tied to a hand-curated 15-project alias map)
and high-accuracy under real ASR noise.

## Goal

Replace "put the whole roster in context" with **on-demand entity resolution**: a
`find_project` tool that maps a (possibly STT-corrupted) spoken project name to a canonical
code with high accuracy, degrading gracefully to a disambiguation question when the input is
genuinely ambiguous.

Scale target: **single tenant, ~1000 projects.** Per-session subset selection does not help —
any call may reference any project. Multi-tenant (one index per tenant) is a forward-compatible
extension, not the immediate target.

## Non-goals

- Rebuilding the RAG/search backends — they keep taking an exact canonical code as `project_id`.
- Multi-tenant isolation plumbing (out of scope; the design leaves room for one index/tenant).
- Offline LLM alias generation is **pluggable but OFF by default** (see §7).

## Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Where resolution happens | **Explicit `find_project` tool**, LLM-called | Within a turn, the resolved code sticks (`customer.project_interest`); one round-trip covers the whole chain of follow-up questions about that project. |
| Matching approach | **Multi-signal + weighted fusion + confidence gate** | No single signal survives real ASR noise; fusion covers complementary error modes. |
| Alias enrichment (offline LLM) | **Pluggable, default OFF** | Deterministic signals suffice for canonical names + STT errors; add only if measured colloquial-nickname recall is weak. YAGNI. |
| Context hints (region/investor) | **Both** — LLM-supplied hint + code-supplied fallback from state | Robust; cheap (reads existing state). |

## Architecture — the `find_project` matcher

Two representations of the input string are compared:
- **Raw-normalized** (lowercased, whitespace-collapsed) — used by trigram + token-fuzzy.
- **Folded** (sound-collapsed) — used by the phonetic channel.

### Tier 0 — Per-token normalization / folding

Detect each token's script and fold accordingly:

- **Vietnamese location tokens** (contain VN characters, or match a location lexicon):
  1. lowercase + Unicode-decompose, **strip all tone marks** (`á à ả ã ạ → a`) — the single
     biggest ASR-error class for VN voice (syllable right, tone wrong).
  2. `đ → d`.
  3. fold confusable **initial** consonants to a shared representative:
     `s,x→s`  · `ch,tr→c`  · `d,gi,r→z`  · `l,n→n`  · `ph,f→f`.
  4. fold **final** consonants conservatively: `nh,ng→g` · `t,c→k`.
- **English brand tokens** (ASCII-only): **Double Metaphone** phonetic code
  (`Crystal→KRSTL`, `Sunshine→SNXN`).

The fold is a deterministic function; both the query and every project name are folded once so
sound-alikes become byte-identical before similarity is measured.

### Tier 1 — Candidate generation (recall; take ~top 30; in-process, few ms)

Four parallel channels, each returning candidates + a 0–1 score:

1. **Trigram** (character 3-gram Dice) — robust to insertion/deletion & word-boundary merges;
   weak to mid-word substitution.
2. **Token-fuzzy** (`RapidFuzz token_set_ratio`) — order-independent, partial-name friendly;
   weak when whole syllables are wrong.
3. **Phonetic-fold** (token-fuzzy computed on the *folded* strings) — the primary VN
   ASR-robustness channel (tone / `l↔n` / `s↔x` / `ch↔tr`).
4. **Embedding** (existing remote e5-large) — paraphrase / roundabout phrasing.

### Tier 2 — Fusion + rerank (precision) over the candidate union

`score = Σ wᵢ · normalizedᵢ  +  context_boosts`

Context boosts:
- **Region/district** the customer mentioned → boost same-region candidates (cuts same-brand
  ambiguity hard). Sources: `region_hint` param **and** `customer.project_interest` /
  `preferred_area` from state.
- **Brand/investor** mentioned ("Sunshine…", "Noble…") → boost same family.
- **Discriminating tail token** — score similarity on the token that *differs* between
  near-identical candidates, so the shared prefix ("Noble Crystal") doesn't dominate.

Channel weights `wᵢ` and boost magnitudes are tunable constants, calibrated against the eval
set (§8). Starting point: phonetic-fold and token-fuzzy weighted highest, trigram and embedding
as supporting votes.

### Tier 3 — Confidence gate (what gets returned)

- **top-1 above floor AND clearly above top-2 (margin)** → `resolved` (single code).
- **top-1 ≈ top-2** → `ambiguous` (2–4 candidates, each with region/investor to disambiguate).
- **nothing above floor** → `not_found`.

`floor` and `margin` are tunable; calibrated on the eval set to trade top-1 accuracy against
false-confident matches.

### Worked examples

1. STT drops tones: `"noble crystal tay ho"` → phonetic-fold treats `tay ho == tây hồ` →
   NCTH scores ~0.93 vs next ~0.66 → **resolved: NCTH**.
2. Partial name: `"crystal"` → NCLB/NCTH/NCR near-tie (~0.80) → **ambiguous**, LLM asks
   "Crystal ở Long Biên, Tây Hồ hay Riverside?". Follow-up `"bên Long Biên"` →
   `find_project("crystal", region_hint="Long Biên")` → region boost → **resolved: NCLB**.
3. Heavy phonetic error: `"san sai gôn đần ri vơ"` for Sunshine Golden River → token-fuzzy
   ~0.35 (useless) but phonetic-fold ~0.82 → **ambiguous→confirm** ("Ý anh là Sunshine
   Golden River?"). Fuzzy-only would miss entirely.

## Component: `ProjectNameIndex`

New in-process index, built at `provider.warm()` / `warm_if_stale()` — the same choke point that
already warms the roster ([db_project_registry.py:30](../../../src/noble_agent/data/db_project_registry.py#L30)).

- **Inputs per project:** `code`, `name`, `region`, `investor` (all available from the provider
  DTOs / `ProjectRegistryRow`).
- **Precomputes:** raw-normalized name, folded string, Double-Metaphone codes for brand tokens,
  token set, and the name embedding (1000×1024d ≈ 4MB — negligible).
- **Refresh:** rebuilt on the same TTL cadence as the roster (`NOBLE_PROJECT_REGISTRY_REFRESH_SEC`).
- **Interface:** `resolve(query, *, region_hint=None, investor_hint=None) -> ResolveResult`
  where `ResolveResult` carries `status ∈ {resolved, ambiguous, not_found}` + payload.
- **Multi-tenant (future):** one index instance per tenant, keyed alongside the provider.

What does it depend on? Only the roster rows from the active provider + the existing remote
embedder. What can consume it without reading internals? The `find_project` tool executor and
the dispatcher (for stickiness defaulting).

## Tool contract: `find_project`

```
find_project(query: str, region_hint?: str, investor_hint?: str)
  resolved   → { status:"resolved",  code, name, region }
  ambiguous  → { status:"ambiguous", candidates:[{code,name,region,investor}, ...] }   # 2–4
  not_found  → { status:"not_found", message }
```

- Added via the standard tool-registration path (executor in `agent/tools/find_project.py`,
  schema in `schemas.py`, dispatch branch in `dispatcher.py`, name in
  `agent/definitions/config.json`, row in `RULES.md`).
- On `resolved`, the dispatcher writes `code` to `customer.project_interest` and marks customer
  dirty so the next system-prompt rebuild reflects it (stickiness).

## Integration changes

### Removed
- `{{ project_table }}` block from the system prompt; `builder._project_table()` no longer
  renders the full roster (replaced by a 1–2 line instruction to call `find_project` first).
- The `["", *codes]` enum injection on project-code params in `schemas_for` / `_with_project_enum`.
- The per-session `state.scratchpad["project_codes"]` snapshot (no longer needed for enums).

### Changed
- Project-code params (`noble_search.project_filter`, `check_inventory.project_code`,
  `booking.project_code`, `get_project_overview`, `get_project_financial`, `search_units`,
  `send_media.project_code`) become **free-text strings** documented as "the canonical code
  returned by `find_project`".
- **Stickiness defaulting:** data tools that receive an empty `project_code` fall back to
  `customer.project_interest`. If both are empty and the tool needs a project, return a
  "cần xác định dự án — gọi find_project" hint rather than guessing.
- `catalog.normalize()` keeps its role as the **final validation gate** (must match a live DB
  code, [catalog.py:264](../../../src/noble_agent/agent/catalog.py#L264)). Its job narrows to
  **rejecting hallucinated codes** (risk rises once the enum is gone). The hardcoded 15-project
  alias map becomes non-scaling legacy — the matcher supersedes it.

### Prompt (`RULES.md`)
- New rule: when the customer names a project, call `find_project` to obtain the code **before**
  any data tool; on `ambiguous`, ask the customer to pick using the returned candidates; on
  `not_found`, ask them to repeat or give the area. Reuse the resolved code for follow-ups; do
  not re-call `find_project` unless a *new* project name is mentioned.

## Pluggable alias enrichment (default OFF)

A build-time hook on `ProjectNameIndex` that, when enabled by a flag, augments each project with
LLM-generated colloquial aliases/nicknames (computed once per tenant at onboard, cached, refreshed
on roster change). Default off; the deterministic matcher runs without it. Turned on only if the
eval set shows weak recall on colloquial nicknames.

## Evaluation (accuracy is the whole point)

Build a resolution eval set to make accuracy measurable and to calibrate weights + gate thresholds:

- **Cases:** `(noisy_query → expected_code_or_ambiguous_set)`.
- **Noise synthesis:** perturb canonical names + region variants with tone-drop and
  confusable-consonant substitutions (the fold table, applied *forward* as corruption) to
  simulate STT errors, plus partial-name and word-order variants.
- **Metrics:** top-1 accuracy on unambiguous cases; ambiguous-recall (does the correct code
  appear in the returned candidate set); false-confident rate (resolved but wrong).
- Use these to tune `wᵢ`, `floor`, `margin` before wiring into the live turn loop.

## Risks / trade-offs

- **Hallucinated codes** — dropping the enum removes a guardrail. Mitigated by (a) stickiness
  defaulting so the LLM rarely types a code, (b) `catalog.normalize()` rejecting unknown codes,
  (c) the prompt rule to always resolve via `find_project`.
- **Over-aggressive folding** may collapse two distinct projects to the same phonetic form —
  it is only one weighted vote, and the discriminating-tail rerank + region boost separate them.
- **Extra round-trip latency** — accepted; paid once per project topic thanks to stickiness.
- **Weight/threshold drift across tenants** — different rosters may need different calibration;
  the eval harness is per-tenant runnable.

## Files touched (anticipated)

- New: `agent/tools/find_project.py`, `data/project_name_index.py` (matcher + index),
  resolution eval under `tests/` (+ optional `tests/bench`).
- Edited: `agent/tools/schemas.py`, `dispatcher.py`, `agent/definitions/config.json`,
  `agent/definitions/RULES.md`, `agent/prompts/builder.py`, `data/db_project_registry.py`
  (index warm hook), the data-tool executors (stickiness defaulting), `config.py` (flags:
  alias-enrichment toggle; reuse `NOBLE_PROJECT_REGISTRY_REFRESH_SEC` for index TTL).
- `CLAUDE.md` Change Log + RAG/tool sections (per self-maintenance rules).
