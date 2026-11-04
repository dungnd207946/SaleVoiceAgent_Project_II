# Recommend Units + Feng Shui — Design

**Date:** 2026-07-14
**Branch:** `feat/refactor2`
**Status:** Approved (brainstorm) → pending spec review

## Problem

The current `match_projects` tool has two weaknesses:

1. **It doesn't actually match.** `projects_info.match_projects` calls
   `list_projects_data`, dumps the whole project list plus the raw criteria back
   to the LLM, and asks the LLM to pick (`projects_info.py:32-60`). `budget_max`
   / `bedrooms` are echoed, never used to filter. So it recommends *projects*,
   not the *specific unit* a salesperson actually sells.
2. **No feng shui.** Asian buyers care whether a home suits their age / birth
   year / destiny (mệnh). The tool has no notion of favorable direction (hướng
   hợp mệnh), even though the unit inventory already carries a `huong` field.

Feng-shui data (direction, `huong`) lives at the **unit** level
(`project_can_ho`), not the project level (`project_du_an` has no direction).
So serving feng shui *forces* the tool down to unit granularity — which happens
to be exactly what the sales goal wants.

## Goals

- Rename `match_projects` → **`recommend_units`**: a *consultative* tool that
  recommends **specific units across multiple projects**, ranked, with an
  optional feng-shui overlay.
- Compute feng shui **deterministically in code** (never let the LLM fabricate
  directions/mệnh), via Bát trạch (Eight Mansions) with graceful degradation to
  a ngũ-hành method when the customer gives less information.
- Feng shui is a **soft ranking + label**, never a hard exclusion filter: a
  customer never gets zero results merely because no unit faces their lucky
  direction.
- Fix the base case too: with no feng-shui signal the tool becomes a real
  budget / bedroom / region cross-project unit recommender (fixing weakness #1).

## Non-goals

- No change to `search_units` (stays: explicit-criteria search within **one**
  project the customer named). `recommend_units` is the *consultative* sibling.
- No màu sắc / chọn tầng theo số / tử vi / giờ sinh advice. Output is **directions
  only**. Birth hour is ignored (only relevant to tử vi, out of scope).
- No new `Customer` field. `birth_year` is a per-call tool param, not persisted.
- Tool count stays **10**.

## Component 1 — `agent/feng_shui.py` (new, pure module, no I/O)

Separated from Mongo so it is trivially unit-testable. Single public entry
`compute(...)` implements a **degradation ladder** — code picks the strongest
method the supplied data allows:

| Priority | Customer gave | Engine | Direction source |
|---|---|---|---|
| 1 | `birth_year` + gender | **Bát trạch** | Cung phi (Kua) → Đông/Tây Tứ Mệnh → 4 hướng cát |
| 2 | `birth_year`, no gender | Nạp âm → ngũ hành | Mệnh → hướng tương sinh/hợp |
| 3 | `menh` stated directly | ngũ hành | Mệnh → hướng hợp |
| 4 | only `zodiac` (after guard exhausts) | địa chi ngũ hành **estimate** | + warning label |
| — | no signal | — | feng shui absent |

### Public API

```python
@dataclass(frozen=True)
class FengShuiResult:
    applied: bool
    method: str | None            # "bat_trach" | "ngu_hanh" | "dia_chi" | None
    menh: str | None              # "Mộc", "Thổ", ...
    cung_phi: str | None          # "Chấn" (bat_trach only)
    group: str | None             # "Đông Tứ Mệnh" | "Tây Tứ Mệnh" (bat_trach only)
    good_directions: frozenset[str]
    note: str | None              # warning label, e.g. "ước lượng từ con giáp"

def compute(*, birth_year=None, gender=None, menh=None, zodiac=None) -> FengShuiResult: ...
def direction_matches(unit_huong: str, good: frozenset[str]) -> bool: ...
```

### Fixed tables (deterministic source of truth)

**8 canonical directions:** `Bắc, Nam, Đông, Tây, Đông Bắc, Đông Nam, Tây Bắc,
Tây Nam`.

**Bát trạch groups:**
- Đông Tứ Mệnh = {Bắc, Nam, Đông, Đông Nam}; cung Khảm(1), Ly(9), Chấn(3), Tốn(4).
- Tây Tứ Mệnh = {Tây, Tây Bắc, Tây Nam, Đông Bắc}; cung Càn(6), Khôn(2), Cấn(8), Đoài(7).

**Kua (cung phi) algorithm — year + gender:**
```
d = digit_root(birth_year % 100)          # sum the two last digits, reduce to 1 digit
male:   k = (9 - d) if year >= 2000 else (10 - d)
female: k = (d + 6) if year >= 2000 else (d + 5)
k = digit_root(k)
if k == 5: k = 2 (Khôn) if male else 8 (Cấn)
if k == 0: k = 9
```
Validation anchors (must hold in tests):
- 1990 male → d=9 → 10−9=1 → Kua 1 (Khảm, Đông Tứ Mệnh).
- 1990 female → 9+5=14 → digit_root=5 → female special → 8 (Cấn, Tây Tứ Mệnh).

**Nạp âm (year → ngũ hành):** 60-year cycle, `(year-4) % 60` indexes the cycle
where year 4 AD = Giáp Tý (index 0). Pair index = `((year-4) % 60) // 2` (each
element spans 2 consecutive years). The 30-element sequence (Giáp Tý → Quý Hợi):

```
Kim, Hỏa, Mộc, Thổ, Kim, Hỏa, Thủy, Thổ, Kim, Mộc,
Thủy, Thổ, Hỏa, Mộc, Thủy, Kim, Hỏa, Mộc, Thổ, Kim,
Hỏa, Thủy, Thổ, Kim, Mộc, Thủy, Thổ, Hỏa, Mộc, Thủy
```
Validation anchors: 1984 (Giáp Tý) → pair 0 → **Kim**; 1990 (Canh Ngọ) →
pair 3 → **Thổ**; 1988 (Mậu Thìn) → pair 2 → **Mộc**.

**Ngũ hành → favorable directions** (bản mệnh + the element that generates it,
tương sinh):
```
Kim  → {Tây, Tây Bắc, Tây Nam, Đông Bắc}   # Kim(Tây,TB) + Thổ(TN,ĐB) sinh Kim
Mộc  → {Đông, Bắc}                          # Mộc(Đông) + Thủy(Bắc) sinh Mộc
Thủy → {Bắc, Tây, Tây Bắc}                  # Thủy(Bắc) + Kim(Tây,TB) sinh Thủy
Hỏa  → {Nam, Đông, Đông Nam}                # Hỏa(Nam) + Mộc(Đông,ĐN) sinh Hỏa
Thổ  → {Tây Nam, Đông Bắc, Nam}             # Thổ(TN,ĐB) + Hỏa(Nam) sinh Thổ
```

**Địa chi ngũ hành (con-giáp fallback):**
```
Tý=Thủy, Sửu=Thổ, Dần=Mộc, Mão=Mộc, Thìn=Thổ, Tị=Hỏa,
Ngọ=Hỏa, Mùi=Thổ, Thân=Kim, Dậu=Kim, Tuất=Thổ, Hợi=Thủy
```

**Direction normalization** (`direction_matches`): normalize a unit's free-text
`huong` (accents, case, abbreviations like "ĐN" / "đông nam" / "Đông-Nam") to one
of the 8 canonical directions, then test membership in `good`. A compound/unknown
value that doesn't normalize → no match (never crash).

### `compute` flow

```python
def compute(*, birth_year=None, gender=None, menh=None, zodiac=None):
    if birth_year:
        element = _nap_am(birth_year)                     # always derivable from year
        if gender in ("M", "F"):
            k = _kua(birth_year, gender); cung, dirs = _KUA[k]
            grp = "Đông Tứ Mệnh" if dirs is EAST else "Tây Tứ Mệnh"
            return FengShuiResult(True, "bat_trach", element, cung, grp, dirs, None)
        return FengShuiResult(True, "ngu_hanh", element, None, None, _MENH_DIRS[element], None)
    if menh:
        e = _canon_menh(menh)                             # "moc" -> "Mộc"
        return FengShuiResult(True, "ngu_hanh", e, None, None, _MENH_DIRS[e], None)
    if zodiac:                                            # reached only AFTER the tool's guard exhausts
        e = _CHI_MENH[zodiac]
        return FengShuiResult(True, "dia_chi", e, None, None, _MENH_DIRS[e],
                              "ước lượng từ con giáp, nên xác nhận năm sinh")
    return FengShuiResult(False, None, None, None, None, frozenset(), None)
```

The con-giáp guard (below) lives in the **tool executor**, not the module, so
`compute`'s `zodiac` branch is only hit after the guard has asked for a birth
year and been refused.

## Component 2 — Con-giáp guard (tool executor, mirrors booking guard)

Pattern copied from `schedule_viewing` (`state.scratchpad` counter, cap 2,
`{"ok": False, "needs_info": True, "message": ...}` return). Trigger: `zodiac`
present but **both** `birth_year` and `menh` absent — prefer a real birth year
before falling back to the weaker địa-chi estimate.

```python
_FS_GUARD_KEY = "fengshui_guard_attempts"
_FS_GUARD_MAX = 2
```
- attempts < 2 → return `needs_info` asking Luna to get the solar birth year
  (e.g. "anh tuổi Tị là sinh năm nào ạ?"), increment counter.
- attempts >= 2 → fall through; `compute(zodiac=...)` uses the địa-chi estimate
  (labelled).
- If a real `birth_year` or `menh` arrives → reset the counter to 0.

The guard fires **only** for the zodiac-only case. If the customer volunteers no
feng-shui signal at all, the tool never asks for a birth year (RULES tells Luna
to ask conversationally before calling the tool if a bare "xem phong thủy" comes
in).

## Component 3 — `structured_data.recommend_units_data(...)` (new data fn)

Cross-project inventory scan. Returns `None` **only** when Mongo is down or
`project_du_an` is empty (a true system gap → the tool surfaces `ESCALATE_SIGNAL`).
A region that matches no project, or filters that exclude every unit, returns
`{"units": []}` (NOT `None`) — so a mere filter miss asks Luna to broaden, it
does not transfer the caller to a human.

```python
async def recommend_units_data(*, region="", budget_max=0, bedrooms=0,
                               good_directions=frozenset(), limit=6) -> dict | None:
    db = await get_db()
    if db is None: return None
    proj = [d async for d in db.project_du_an.find({})]
    if not proj: return None
    if region:
        proj = [d for d in proj if _region_matches(d.get("khu_vuc",""), region)]
    if not proj:
        return {"units": []}                               # region miss -> broaden, not escalate
    id2name = {str(d["_id"]): (d.get("ten_thuong_mai") or "").strip() for d in proj}
    id2code = {str(d["_id"]): (d.get("ma_du_an") or "").strip() for d in proj}
    units = [u async for u in db.project_can_ho.find({"du_an_id": {"$in": list(id2name)}})]

    budget_vnd = budget_max * 1e9 if budget_max else 0
    out = []
    for u in units:
        if not _is_available(u.get("trang_thai","")): continue
        if bedrooms and u.get("so_phong_ngu") != bedrooms: continue
        price = _to_int(u.get("gia_vnd"))
        if budget_vnd and (price is None or price > budget_vnd): continue
        fs_match = bool(good_directions) and feng_shui.direction_matches(u.get("huong",""), good_directions)
        did = u.get("du_an_id","")
        out.append({"unit_code": u.get("ma_can") or "", "type": _unit_type_label(u),
                    "bedroom_count": u.get("so_phong_ngu"),
                    "clear_area_m2": _to_float(u.get("dien_tich_thong_thuy_m2")),
                    "direction": (u.get("huong") or "").strip(),
                    "view": (u.get("tam_nhin") or "").strip(),
                    "price_vnd": price, "price_per_m2_vnd": _to_int(u.get("gia_m2_vnd")),
                    "project_code": id2code.get(did,""), "project_name": id2name.get(did,""),
                    "feng_shui_match": fs_match,
                    "direction_label": "hợp hướng" if fs_match else ""})
    out.sort(key=lambda x: (not x["feng_shui_match"], x["price_vnd"] or 10**18))
    return {"units": out[:limit]}
```

Budget conversion: schema takes `budget_max` in **tỷ VNĐ** (matching the old
`match_projects`), converted `× 1e9` here against the unit's `gia_vnd`. Ranking:
feng-shui matches first, then price ascending. Cap 6 units (payload gọn for
voice/chat). `purpose` is not filtered (no source field) — echoed for Luna's
framing only.

## Component 4 — Executor `projects_info.recommend_units(args, *, state, customer)`

```python
async def recommend_units(args, *, state, customer) -> str:
    birth_year = args.get("birth_year")
    gender = args.get("gender") or customer.gender
    menh, zodiac = args.get("menh"), args.get("zodiac")

    if zodiac and not birth_year and not menh:               # guard
        attempts = int(state.scratchpad.get(_FS_GUARD_KEY, 0))
        if attempts < _FS_GUARD_MAX:
            state.scratchpad[_FS_GUARD_KEY] = attempts + 1
            return json.dumps({"ok": False, "needs_info": True, "message":
                "Khách mới cho con giáp, chưa có năm sinh. Hãy hỏi năm sinh dương lịch "
                "để tư vấn hướng hợp mệnh chính xác (vd 'anh tuổi Tị là sinh năm nào ạ?'). "
                "Nếu khách không nhớ, cứ tư vấn theo tiêu chí khác."}, ensure_ascii=False)

    fs = None
    if birth_year or menh or zodiac:
        fs = feng_shui.compute(birth_year=birth_year, gender=gender, menh=menh, zodiac=zodiac)
        if birth_year or menh:
            state.scratchpad[_FS_GUARD_KEY] = 0

    good = fs.good_directions if (fs and fs.applied) else frozenset()
    data = await sd.recommend_units_data(
        region=args.get("region","") or "", budget_max=args.get("budget_max") or 0,
        bedrooms=args.get("bedrooms") or 0, good_directions=good, limit=6)
    if data is None:
        return sd.ESCALATE_SIGNAL

    units = data["units"]
    fs_match = sum(1 for u in units if u.get("feng_shui_match"))
    payload = {"units": units,
               "counts": {"total": len(units), "feng_shui_match": fs_match},
               "criteria": {"budget_max": args.get("budget_max"), "region": args.get("region",""),
                            "bedrooms": args.get("bedrooms"), "purpose": args.get("purpose","")},
               "instruction": "Giới thiệu 2-3 căn nổi bật (dự án + hướng + giá), dẫn dắt khách."}
    if fs and fs.applied:
        payload["feng_shui"] = _fs_block(fs)                 # ONLY when feng shui actually applies
        # _fs_block(fs) -> {"applied": True, "method": fs.method, "menh": fs.menh,
        #   "cung_phi": fs.cung_phi, "group": fs.group,
        #   "good_directions": sorted(fs.good_directions), "note": fs.note}
        # (keys with None value may be dropped to keep the payload lean)
    if not units:
        payload["instruction"] = ("Không có căn khớp tiêu chí. Hãy gợi ý khách nới ngân sách "
                                   "hoặc đổi khu vực, đừng bịa căn.")
    elif fs and fs.applied and fs_match == 0:
        payload["note"] = ("Không có căn nào hợp hướng mệnh của khách. Hãy nói rõ điều này, "
                           "gợi ý vài căn hợp ngân sách để tham khảo, và mời khách chuyển "
                           "chuyên viên tư vấn chuyên sâu nếu muốn.")
    return json.dumps(payload, ensure_ascii=False)
```

Key behaviors:
- **No feng-shui signal** → `fs is None` → `good = frozenset()` → every
  `feng_shui_match` is False → units rank purely by price; the `feng_shui`
  block is **omitted** from the payload (so a weak LLM never sees an empty
  feng-shui block and drifts into mệnh talk unprompted). Base case = a plain
  budget/bedroom/region unit recommender.
- **Feng shui applied, 0 matches** → include `note` (the exact
  no-match-but-here-are-budget-units + optional handoff message).
- **gender fallback**: `args.gender or customer.gender`. If neither is known, the
  birth-year path degrades to `ngu_hanh` (nạp âm) instead of `bat_trach` — no
  gender guard (accepted; nạp âm still yields directions).

## Component 5 — Schema (`schemas.py`)

Replace the `match_projects` entry with `recommend_units`. No `project_code`
param → **not** added to `_PROJECT_CODE_TOOLS` / `_ENUM_TOOLS` (no enum
injection). All params optional (no feng-shui signal = base recommender).

Params: `budget_max` (number, tỷ VNĐ, hard filter), `region` (string),
`bedrooms` (integer), `purpose` (string, echo only), `birth_year` (integer,
solar), `gender` (enum M/F, else profile), `menh` (enum kim/moc/thuy/hoa/tho),
`zodiac` (enum of the 12 con giáp). Full text in the plan.

## Component 6 — Wiring + RULES

- `dispatcher.py`: rename the `match_projects` branch to `recommend_units` and
  pass `state=self.state, customer=self.customer`.
- `config.json`: `"match_projects"` → `"recommend_units"` in `tools[]`.
- `RULES.md`: rewrite the tool-catalog row; add a **feng-shui protocol** rule —
  when a customer asks by mệnh/tuổi/năm sinh call `recommend_units` with the
  feng-shui signal; con giáp with no birth year → ask the birth year (max 2×,
  the tool enforces this); never fabricate hướng/mệnh; birth hour is irrelevant.

## Testing

`tests/unit/unified/`:
- **`test_feng_shui.py`** — pure module: Kua for the validation anchors
  (1990 M→Khảm/East, 1990 F→Cấn/West) + a spread of years incl. ≥2000; nạp âm
  anchors (1984→Kim, 1988→Mộc, 1990→Thổ); địa-chi fallback; each ngũ-hành →
  direction set; `direction_matches` across accent/case/abbrev variants and a
  garbage value; the full degradation ladder (each priority branch + no-signal).
- **`test_recommend_units.py`** — in-memory fake db: budget (tỷ→VNĐ) + bedroom
  hard filters; ranking (feng-shui matches ahead of price order); guard asks
  twice then falls back to địa chi; `note` present iff feng shui applied and
  0 matches; `feng_shui` block omitted on the no-signal path; region-miss and
  empty-filter return `units: []` (not escalate); Mongo-down / empty projects →
  `ESCALATE_SIGNAL`.

## Files touched

- `src/noble_agent/agent/feng_shui.py` (new)
- `src/noble_agent/data/structured_data.py` (+`recommend_units_data`)
- `src/noble_agent/agent/tools/projects_info.py` (`match_projects` → `recommend_units`)
- `src/noble_agent/agent/tools/schemas.py` (schema entry)
- `src/noble_agent/agent/tools/dispatcher.py` (branch rename + pass state/customer)
- `src/noble_agent/agent/definitions/config.json` (tool name)
- `src/noble_agent/agent/definitions/RULES.md` (catalog row + feng-shui rule)
- `tests/unit/unified/test_feng_shui.py`, `tests/unit/unified/test_recommend_units.py` (new)

## Risks / caveats

- **Lập Xuân boundary:** Kua/nạp âm use the solar *year* only; a caller born in
  Jan / early-Feb technically belongs to the previous năm can-chi. Accepted
  approximation (we don't collect birth month); the RULES note lets Luna ask the
  month if a customer wants precision. Documented, not handled in code.
- **`huong` data quality:** matching depends on the unit's free-text `huong`.
  `direction_matches` normalizes common forms; anything unrecognized simply
  doesn't match (soft-rank means it still appears, just lower) — never a crash,
  never a false feng-shui claim.
- **Con-giáp estimate is coarse** (địa chi ngũ hành ≠ nạp âm). Always labelled so
  Luna frames it as an estimate and nudges for the birth year.
```