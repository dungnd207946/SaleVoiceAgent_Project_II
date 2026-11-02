# Configurable Agent Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent's display name configurable via one env var (`NOBLE_AGENT_NAME`, default `Luna`) instead of hardcoding "Luna" across prompt + code.

**Architecture:** Add a single `UnifiedSettings.agent_name` field. It flows into every prompt-facing spot: the persona (`SOUL.md`/`RULES.md` are jinja-rendered once at `load_agent_def`), the voice greeting, the suggestions prompt, and the summary + snapshot speaker labels. Pure helpers get an `agent_name` param defaulting to `"Luna"` so existing callers/tests stay green.

**Tech Stack:** Python 3.11+, pydantic-settings, jinja2, pytest (`asyncio_mode=auto`).

## Global Constraints

- **Single source of truth:** every prompt-facing consumer reads `settings.agent_name` (or receives it via param). Default `"Luna"` everywhere → no-env behavior is byte-identical to today.
- **Do NOT change** `builder.py`, `PROMPT_TEMPLATE.md`, the TTS voice preset (`vieneu_voice_id` / `"luna"`), the email `luna@noblex.vn`, comments/docstrings, `src/eval/*`, `src/synthetic/*`, or the company name `"NobleX"`.
- **Branch:** work on `feat/configurable-agent-name`. Local commits only — do NOT push, merge, or touch `develop`.
- **Commit message style:** `<type>: <description>` (feat/refactor/test). No attribution footer.
- Ruff: line-length 120, target py311. Run `make lint` (or `ruff check`) on touched files before each commit.

---

### Task 1: Add `NOBLE_AGENT_NAME` config setting

**Files:**
- Modify: `src/noble_agent/config.py` (after `suggestions_model`, ~line 79)
- Modify: `.env.example` (near `NOBLE_AGENT_MODEL`, ~line 142)
- Test: `tests/unit/unified/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `UnifiedSettings.agent_name: str` (default `"Luna"`, env alias `NOBLE_AGENT_NAME`). Every later task reads this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/unified/test_config.py`:

```python
def test_agent_name_default_luna():
    # `_env_file=None` bypasses the repo `.env` so this exercises the code default.
    assert UnifiedSettings(_env_file=None).agent_name == "Luna"


def test_agent_name_reads_env(monkeypatch):
    monkeypatch.setenv("NOBLE_AGENT_NAME", "Aria")
    assert UnifiedSettings().agent_name == "Aria"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_config.py::test_agent_name_default_luna tests/unit/unified/test_config.py::test_agent_name_reads_env -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'agent_name'`.

- [ ] **Step 3: Add the field**

In `src/noble_agent/config.py`, immediately after the line:

```python
    suggestions_model: str = Field("", alias="NOBLE_SUGGESTIONS_MODEL")
```

add:

```python
    # Agent display name used in the system prompt, greeting, and prompt labels.
    agent_name: str = Field("Luna", alias="NOBLE_AGENT_NAME")
```

- [ ] **Step 4: Document it in `.env.example`**

In `.env.example`, directly after the line `NOBLE_AGENT_MODEL=gemini-2.5-flash`, add:

```
# Tên hiển thị của agent trong prompt + câu chào (mặc định Luna).
NOBLE_AGENT_NAME=Luna
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_config.py -v`
Expected: PASS (new tests + existing config tests).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py .env.example tests/unit/unified/test_config.py
git commit -m "feat: add NOBLE_AGENT_NAME setting (default Luna)"
```

---

### Task 2: Inject the name into the persona (system prompt)

**Files:**
- Modify: `src/noble_agent/agent/definitions/SOUL.md` (line 1)
- Modify: `src/noble_agent/agent/definitions/RULES.md` (lines 21, 73, 130, 138, 167)
- Modify: `src/noble_agent/agent/definitions/config.json` (`"name"`)
- Modify: `src/noble_agent/agent/base.py` (`load_agent_def`)
- Modify: `src/noble_agent/agent/facade.py` (line 195)
- Test: `tests/unit/unified/test_agent_def.py`

**Interfaces:**
- Consumes: `settings.agent_name` (Task 1) — passed by facade.
- Produces: `load_agent_def(definitions_dir, *, agent_name: str | None = None) -> AgentDef`. `AgentDef.sections["soul"]` and `["rules"]` come out with the name already substituted; `AgentDef.name` == resolved name. `builder.py` unchanged.

- [ ] **Step 1: Write / update the failing tests**

In `tests/unit/unified/test_agent_def.py`, change line 11 from:

```python
    assert agent.name == "luna"
```

to:

```python
    assert agent.name == "Luna"
```

Then append:

```python
def test_load_agent_def_injects_custom_name():
    agent = load_agent_def(DEFINITIONS, agent_name="Aria")
    assert agent.name == "Aria"
    assert "Aria" in agent.sections["soul"]
    assert "Luna" not in agent.sections["soul"]
    assert "Aria" in agent.sections["rules"]
    assert "Luna" not in agent.sections["rules"]


def test_load_agent_def_default_name_luna():
    agent = load_agent_def(DEFINITIONS)
    assert agent.name == "Luna"
    assert "Luna" in agent.sections["soul"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_agent_def.py -v`
Expected: FAIL — `test_load_agent_def_injects_custom_name` errors on the unexpected `agent_name` kwarg; `agent.name == "Luna"` fails (still `"luna"`).

- [ ] **Step 3: Templatize the markdown**

`SOUL.md` line 1 — change:

```
Bạn là Luna — chuyên viên NobleX. Em phụ trách toàn bộ cuộc gọi:
```

to:

```
Bạn là {{ agent_name }} — chuyên viên NobleX. Em phụ trách toàn bộ cuộc gọi:
```

`RULES.md` — replace `Luna` with `{{ agent_name }}` on each of these 5 lines (leave `NobleX` and everything else intact):

- line 21: `... → NGOÀI phạm vi của {{ agent_name }}. escalate sang chuyên viên phụ trách`
- line 73: `  {{ agent_name }} KHÔNG tự xử lý. escalate(action="transfer", department=...) sang`
- line 130: `... — {{ agent_name }} KHÔNG tự xử lý |`
- line 138: `vấn. {{ agent_name }} chỉ cần báo khách rằng chuyên viên sẽ gọi lại tư vấn trực tiếp —`
- line 167: `  hồng) KHÔNG do {{ agent_name }} xử lý — chuyển chuyên viên phụ trách (escalate).`

`config.json` — change `"name": "luna"` to `"name": "Luna"`.

- [ ] **Step 4: Render the sections in `load_agent_def`**

In `src/noble_agent/agent/base.py`, replace the `load_agent_def` function body from its signature through the `sections = {...}` block. New version:

```python
def load_agent_def(definitions_dir: Path | str, *, agent_name: str | None = None) -> AgentDef:
    from noble_agent.agent.tools.schemas import schemas_for

    d = Path(definitions_dir)
    config = json.loads(_read(d / "config.json"))
    name = agent_name or config["name"]

    env = jinja2.Environment(
        loader=jinja2.BaseLoader(),
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    template_src = _read(d / "PROMPT_TEMPLATE.md")
    tmpl = env.from_string(template_src)

    # SOUL.md / RULES.md carry the agent's display name as `{{ agent_name }}`.
    # Render them once here (name is fixed per process) so builder.py needs no
    # further substitution.
    soul = env.from_string(_read(d / "SOUL.md")).render(agent_name=name)
    rules = env.from_string(_read(d / "RULES.md")).render(agent_name=name)
    sections = {
        "soul": soul,
        "rules": rules,
        "customer_format": _read(d / "CUSTOMER_PROFILE.md"),
    }

    tool_names = list(config["tools"])
    tool_schemas = schemas_for(tool_names)

    return AgentDef(
        name=name,
        model=config["model"],
        temperature=float(config["temperature"]),
        max_tokens=int(config["max_tokens"]),
        prompt_template=tmpl,
        sections=sections,
        tool_names=tool_names,
        tool_schemas=tool_schemas,
    )
```

- [ ] **Step 5: Pass the configured name from the facade**

In `src/noble_agent/agent/facade.py`, change line 195 from:

```python
    agent_def = load_agent_def(defs_dir)
```

to:

```python
    agent_def = load_agent_def(defs_dir, agent_name=settings.agent_name)
```

(`settings = get_settings()` is already assigned at the top of `_build_runner`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_agent_def.py -v`
Expected: PASS (all 5 tests, including the two new ones).

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/agent/base.py src/noble_agent/agent/facade.py \
  src/noble_agent/agent/definitions/SOUL.md src/noble_agent/agent/definitions/RULES.md \
  src/noble_agent/agent/definitions/config.json tests/unit/unified/test_agent_def.py
git commit -m "feat: render agent name into SOUL/RULES via load_agent_def"
```

---

### Task 3: Inject the name into the suggestions prompt

**Files:**
- Modify: `src/noble_agent/agent/suggestions.py` (`build_suggestions_prompt`)
- Modify: `src/noble_agent/agent/orchestrator.py` (line ~323)
- Test: `tests/unit/unified/test_suggestions.py`

**Interfaces:**
- Consumes: `settings.agent_name` — orchestrator has `self._settings`.
- Produces: `build_suggestions_prompt(user_text, assistant_text, customer, *, agent_name: str = "Luna") -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/unified/test_suggestions.py`:

```python
def test_build_suggestions_prompt_uses_agent_name():
    from types import SimpleNamespace

    cust = SimpleNamespace(project_interest=None, purpose=None)
    p = build_suggestions_prompt("cho xem giá", "dạ giá từ 2 tỷ", cust, agent_name="Aria")
    assert "Aria" in p
    assert "Luna" not in p


def test_build_suggestions_prompt_default_name_luna():
    from types import SimpleNamespace

    cust = SimpleNamespace(project_interest=None, purpose=None)
    p = build_suggestions_prompt("cho xem giá", "dạ giá từ 2 tỷ", cust)
    assert "Luna" in p
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_suggestions.py::test_build_suggestions_prompt_uses_agent_name -v`
Expected: FAIL — unexpected keyword argument `agent_name`.

- [ ] **Step 3: Rewrite `build_suggestions_prompt`**

In `src/noble_agent/agent/suggestions.py`, replace the entire `build_suggestions_prompt` function with (signature gains `*, agent_name`; every `Luna` literal → `{agent_name}`; the return chunks that were plain strings become f-strings):

```python
def build_suggestions_prompt(user_text: str, assistant_text: str, customer, *, agent_name: str = "Luna") -> str:
    """Vietnamese prompt asking a side LLM for up to 3 follow-up chips.

    The suggestions are phrased as what the CUSTOMER could say/ask next. Each has
    a short ``label`` (<= 24 chars, shown on the button) and a full ``text`` (the
    message sent when tapped). Instructs an EMPTY array when nothing fits
    (farewell / already escalated / booking closed). JSON-only output. Light
    profile hints (project_interest, purpose) are injected when present.
    """
    profile_lines = []
    project_interest = getattr(customer, "project_interest", None)
    purpose = getattr(customer, "purpose", None)
    if project_interest:
        profile_lines.append(f"- Dự án khách quan tâm: {project_interest}")
    if purpose:
        profile_lines.append(f"- Mục đích: {purpose}")
    profile_block = ("\nHồ sơ khách (để gợi ý sát hơn):\n" + "\n".join(profile_lines)) if profile_lines else ""

    return (
        f"Bạn hỗ trợ trợ lý bán hàng {agent_name} của NobleX. Dựa vào đoạn hội thoại dưới đây giữa "
        f"khách và {agent_name}, hãy đề xuất TỐI ĐA 3 câu mà KHÁCH có thể nói/hỏi {agent_name} ở lượt tiếp theo.\n\n"
        f"[Khách]: {user_text}\n"
        f"[{agent_name}]: {assistant_text}\n"
        f"{profile_block}\n\n"
        "BƯỚC 0 — KIỂM TRA KẾT THÚC (làm trước tiên): Nếu cuộc trò chuyện đã kết thúc thì BẮT "
        "BUỘC trả về đúng mảng rỗng [] và DỪNG — KHÔNG gợi ý gì, KHÔNG tự nghĩ ra lý do để "
        'tiếp tục. Coi là đã kết thúc khi: khách chào/muốn dừng (vd "thôi", "để hôm khác", '
        f'"bận rồi", "cảm ơn nhé", "chào em", "ok vậy thôi"); HOẶC {agent_name} vừa chào tạm biệt/kết '
        'thúc (vd "hẹn gặp lại", "em chào anh", "cảm ơn anh đã quan tâm"); HOẶC khách đã được '
        "chuyển cho chuyên viên; HOẶC đã chốt xong lịch hẹn.\n\n"
        "Nếu cuộc trò chuyện VẪN đang tiếp diễn, áp dụng các quy tắc sau:\n"
        f"1. Mỗi gợi ý là LỜI CỦA KHÁCH nói với {agent_name} — KHÔNG phải lời {agent_name}. Khách tự xưng "
        f'"tôi/mình" (hoặc không xưng), gọi trợ lý là "{agent_name}/em"; khách KHÔNG tự xưng "em" '
        f'("em" là {agent_name}). Ví dụ SAI (đây là lời {agent_name}): "Anh cho em xem…", "Để em gửi anh…". '
        'Ví dụ ĐÚNG (lời khách): "Cho tôi xem vài hình ảnh dự án này với".\n'
        "2. Chỉ bám vào NỘI DUNG đã xuất hiện trong hội thoại và hồ sơ khách. TUYỆT ĐỐI KHÔNG "
        "bịa tên dự án, tên căn hộ, con số, hay tính năng chưa được nhắc tới. Chưa có dự án cụ "
        "thể thì nói chung chung, không nêu tên.\n"
        f"3. Chỉ gợi ý những việc {agent_name} THỰC SỰ làm được: hỏi thêm về dự án/căn hộ đang nói tới "
        "(vị trí, giá, tiện ích, mặt bằng, pháp lý), xin xem hình ảnh dự án/căn hộ, đặt lịch "
        "tham quan, hoặc nhờ chuyên viên tư vấn liên hệ lại. KHÔNG gợi ý gửi tài liệu/brochure "
        "qua Zalo/email/kênh ngoài — mọi thứ diễn ra ngay trong cuộc trò chuyện này.\n"
        "4. Thà trả ÍT gợi ý còn hơn bịa. Không có gợi ý phù hợp nào → trả về mảng rỗng [].\n\n"
        "Mỗi gợi ý gồm:\n"
        '- "label": nhãn ngắn (tối đa 24 ký tự) hiển thị trên nút bấm.\n'
        '- "text": câu đầy đủ khách sẽ gửi khi bấm nút (đúng vai khách).\n\n'
        'Chỉ trả JSON dạng: [{"label":"…","text":"…"}]. Không giải thích gì thêm.'
    )
```

- [ ] **Step 4: Pass the name from the orchestrator**

In `src/noble_agent/agent/orchestrator.py`, change the `build_suggestions_prompt(...)` call (line ~323) from:

```python
            prompt = build_suggestions_prompt(user_text, assistant_text, customer)
```

to:

```python
            prompt = build_suggestions_prompt(
                user_text, assistant_text, customer, agent_name=self._settings.agent_name
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_suggestions.py -v`
Expected: PASS (new tests + all existing suggestion tests).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/suggestions.py src/noble_agent/agent/orchestrator.py \
  tests/unit/unified/test_suggestions.py
git commit -m "feat: use configurable agent name in suggestions prompt"
```

---

### Task 4: Inject the name into the call-summary generator

**Files:**
- Modify: `src/noble_agent/agent/summary/generator.py` (`_format_history`, `_CALL_SUMMARY_PROMPT`, `generate_call_summary`)
- Test: `tests/unit/unified/test_summary_generator_name.py` (create)

**Interfaces:**
- Consumes: `get_settings().agent_name` (function-local import, matching the file's existing pattern).
- Produces: `_format_history(history, max_turns=20, *, agent_name: str = "Luna")`; `_CALL_SUMMARY_PROMPT` gains an `{agent}` placeholder.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/unified/test_summary_generator_name.py`:

```python
from noble_agent.agent.summary.generator import _format_history


def test_format_history_uses_agent_name():
    h = [{"role": "user", "content": "hỏi giá"}, {"role": "assistant", "content": "dạ 2 tỷ"}]
    out = _format_history(h, agent_name="Aria")
    assert "Aria: dạ 2 tỷ" in out
    assert "Luna" not in out


def test_format_history_default_luna():
    h = [{"role": "assistant", "content": "dạ 2 tỷ"}]
    assert "Luna: dạ 2 tỷ" in _format_history(h)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_summary_generator_name.py -v`
Expected: FAIL — unexpected keyword argument `agent_name`.

- [ ] **Step 3: Add the param to `_format_history`**

In `src/noble_agent/agent/summary/generator.py`, replace `_format_history` with:

```python
def _format_history(history: list[dict], max_turns: int = 20, *, agent_name: str = "Luna") -> str:
    """Flatten history into KH/<agent_name> lines, capped at max_turns × 300 chars each."""
    recent = history[-max_turns:] if len(history) > max_turns else history
    lines: list[str] = []
    for m in recent:
        role = m.get("role", "")
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        prefix = "KH" if role == "user" else agent_name if role == "assistant" else role
        snippet = content[:300]
        lines.append(f"{prefix}: {snippet}")
    return "\n".join(lines)
```

- [ ] **Step 4: Add the `{agent}` placeholder to the prompt**

In `_CALL_SUMMARY_PROMPT`, change the two lines containing `Luna`:

- `<2-3 câu tiếng Việt — KH muốn gì, Luna đã làm gì, kết quả chính>` → `<2-3 câu tiếng Việt — KH muốn gì, {agent} đã làm gì, kết quả chính>`
- `- <việc Luna hứa làm tiếp, hoặc khách cần follow up — 1 việc 1 dòng>` → `- <việc {agent} hứa làm tiếp, hoặc khách cần follow up — 1 việc 1 dòng>`

- [ ] **Step 5: Wire the name in `generate_call_summary`**

In `generate_call_summary` (line ~152), replace this block:

```python
    history_text = _format_history(history, max_turns=20)
    if not history_text:
        return _base_doc()

    try:
        customer_json = json.dumps(customer, ensure_ascii=False, default=str)
    except TypeError:
        customer_json = str(customer)

    prompt = _CALL_SUMMARY_PROMPT.format(customer=customer_json, history=history_text)
```

with:

```python
    from noble_agent.config import get_settings

    agent_name = get_settings().agent_name
    history_text = _format_history(history, max_turns=20, agent_name=agent_name)
    if not history_text:
        return _base_doc()

    try:
        customer_json = json.dumps(customer, ensure_ascii=False, default=str)
    except TypeError:
        customer_json = str(customer)

    prompt = _CALL_SUMMARY_PROMPT.format(
        customer=customer_json, history=history_text, agent=agent_name
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_summary_generator_name.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/agent/summary/generator.py tests/unit/unified/test_summary_generator_name.py
git commit -m "feat: use configurable agent name in call-summary generator"
```

---

### Task 5: Inject the name into snapshot memory labels

**Files:**
- Modify: `src/noble_agent/agent/memory/snapshot.py` (`_flatten_history`, `build_merge_prompt`, `merge_snapshot`, `_render`, `build_short_term_context`)
- Test: `tests/unit/unified/test_snapshot_agent_name.py` (create)

**Interfaces:**
- Consumes: `get_settings().agent_name` (in `merge_snapshot`, function-local import); `settings.agent_name` (in `build_short_term_context`, via its `settings` param — read defensively with `getattr`).
- Produces: `_flatten_history(..., *, agent_name="Luna")`, `build_merge_prompt(old_snapshot, history, *, agent_name="Luna")`, `_render(..., *, agent_name="Luna")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/unified/test_snapshot_agent_name.py`:

```python
from noble_agent.agent.memory import snapshot


def test_flatten_history_uses_agent_name():
    h = [{"role": "assistant", "content": "dạ em chào"}]
    out = snapshot._flatten_history(h, agent_name="Aria")
    assert "Aria: dạ em chào" in out
    assert "Luna" not in out


def test_build_merge_prompt_threads_agent_name():
    h = [{"role": "assistant", "content": "dạ em chào"}]
    p = snapshot.build_merge_prompt("cũ", h, agent_name="Aria")
    assert "Aria: dạ em chào" in p


def test_render_uses_agent_name():
    turns = [{"role": "agent", "content": "dạ em tư vấn"}]
    out = snapshot._render("", turns, agent_name="Aria")
    assert "Aria: dạ em tư vấn" in out
    assert "Luna" not in out


def test_flatten_history_default_luna():
    h = [{"role": "assistant", "content": "dạ em chào"}]
    assert "Luna: dạ em chào" in snapshot._flatten_history(h)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/unified/test_snapshot_agent_name.py -v`
Expected: FAIL — unexpected keyword argument `agent_name`.

- [ ] **Step 3: Add params to the two label helpers**

In `src/noble_agent/agent/memory/snapshot.py`, replace `_flatten_history` with:

```python
def _flatten_history(history: list[dict], max_turns: int = 40, *, agent_name: str = "Luna") -> str:
    recent = history[-max_turns:] if len(history) > max_turns else history
    lines: list[str] = []
    for m in recent:
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        role = m.get("role", "")
        prefix = "KH" if role == "user" else agent_name if role == "assistant" else role
        lines.append(f"{prefix}: {content[:300]}")
    return "\n".join(lines)
```

and replace `_render` with:

```python
def _render(snapshot_text: str, turns: list[dict], *, agent_name: str = "Luna") -> str:
    body: list[str] = []
    text = (snapshot_text or "").strip()
    if text:
        body.append(text)
    if turns:
        turn_lines = []
        for m in turns:
            role = m.get("role", "")
            who = "Khách" if role == "caller" else agent_name if role == "agent" else role
            content = (m.get("content") or "").strip()
            if content:
                turn_lines.append(f"- {who}: {content[:200]}")
        if turn_lines:
            body.append("Vài lượt gần nhất:")
            body.extend(turn_lines)
    if not body:
        return ""
    return "\n".join(["## Lịch sử trò chuyện của khách hàng", *body])
```

- [ ] **Step 4: Thread the name through the callers**

Replace `build_merge_prompt` with:

```python
def build_merge_prompt(old_snapshot: str, history: list[dict], *, agent_name: str = "Luna") -> str:
    return _MERGE_PROMPT.format(
        old_snapshot=(old_snapshot or "(chưa có)").strip(),
        history=_flatten_history(history, agent_name=agent_name),
    )
```

Replace `merge_snapshot` with:

```python
async def merge_snapshot(old_snapshot: str, history: list[dict]) -> str:
    if not history:
        return ""
    from noble_agent.config import get_settings

    prompt = build_merge_prompt(old_snapshot, history, agent_name=get_settings().agent_name)
    text = await _call_merge_llm(prompt)
    return (text or "").strip()
```

In `build_short_term_context`, change the final line from:

```python
    return _render(snapshot_text, turns)
```

to:

```python
    return _render(snapshot_text, turns, agent_name=getattr(settings, "agent_name", "Luna"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_snapshot_agent_name.py tests/unit/unified/test_snapshot_merge.py -v`
Expected: PASS (new tests + existing merge tests unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/agent/memory/snapshot.py tests/unit/unified/test_snapshot_agent_name.py
git commit -m "feat: use configurable agent name in snapshot labels"
```

---

### Task 6: Inject the name into the voice greeting + final verify

**Files:**
- Modify: `src/noble_agent/voice/voice_agent.py` (lines 307, 311 in `build_greeting`)

**Interfaces:**
- Consumes: `settings.agent_name` — `settings` is imported module-level (`from noble_agent.config import settings`).
- Produces: nothing new. This is an I/O method (no new unit test — verified by grep + lint + the affected-test rerun below).

- [ ] **Step 1: Replace the two greeting literals**

In `src/noble_agent/voice/voice_agent.py`, in `build_greeting`, change line 307 from:

```python
                f"em là Luna, chuyên viên tư vấn NobleX ạ. "
```

to:

```python
                f"em là {settings.agent_name}, chuyên viên tư vấn NobleX ạ. "
```

and change line 311 from:

```python
            f"{tag_prefix}Dạ em chào Quý Khách, em là Luna bên NobleX ạ. "
```

to:

```python
            f"{tag_prefix}Dạ em chào Quý Khách, em là {settings.agent_name} bên NobleX ạ. "
```

- [ ] **Step 2: Verify no hardcoded "Luna" remains in voice_agent.py**

Run: `grep -n "Luna" src/noble_agent/voice/voice_agent.py`
Expected: no output (exit 1). If any line prints, it was missed — fix it.

- [ ] **Step 3: Lint the touched files**

Run: `ruff check src/noble_agent/`
Expected: no errors in the files touched by this plan. (Pre-existing warnings elsewhere are out of scope.)

- [ ] **Step 4: Rerun all tests added/affected by this plan**

Run:
```bash
pytest tests/unit/unified/test_config.py tests/unit/unified/test_agent_def.py \
  tests/unit/unified/test_suggestions.py tests/unit/unified/test_summary_generator_name.py \
  tests/unit/unified/test_snapshot_agent_name.py tests/unit/unified/test_snapshot_merge.py -v
```
Expected: PASS (all).

- [ ] **Step 5: End-to-end sanity — custom name reaches the system prompt**

Run:
```bash
NOBLE_AGENT_NAME=Aria python -c "
from pathlib import Path
from noble_agent.agent.base import load_agent_def
from noble_agent.config import get_settings, reset_settings_for_tests
reset_settings_for_tests()
a = load_agent_def(Path('src/noble_agent/agent/definitions'), agent_name=get_settings().agent_name)
assert a.name == 'Aria', a.name
assert 'Aria' in a.sections['soul'] and 'Luna' not in a.sections['soul']
assert 'Aria' in a.sections['rules'] and 'Luna' not in a.sections['rules']
print('OK: name =', a.name)
"
```
Expected: prints `OK: name = Aria`.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/voice/voice_agent.py
git commit -m "feat: use configurable agent name in voice greeting"
```

---

## Notes for the implementer

- **Do not run `make test` (full suite).** The repo carries ~65 pre-existing red tests on `develop` (catalog/mongo/qdrant drift, `.env` parsing) unrelated to this change. Only the targeted `pytest` commands above are the gate.
- **Do not touch `develop`.** All commits land on `feat/configurable-agent-name`. Do not push or open a PR unless the user explicitly asks.
- If `SMOKE.md` is run (touches the prompt boundary), the greeting + first system prompt are the things to eyeball with `NOBLE_AGENT_NAME` set.
