# Tên agent cấu hình qua env — design

**Date:** 2026-07-14
**Branch:** develop (working tree — chưa commit; branch mới chờ user duyệt)
**Status:** approved-pending-review

## Vấn đề

Tên agent **"Luna"** đang bị hardcode rải rác trong code + prompt. Muốn đổi tên
(vd triển khai cho brand khác, hoặc A/B tên) phải sửa nhiều file. Yêu cầu: **đặt
tên agent qua một env var duy nhất**, mặc định vẫn `Luna` để hành vi không đổi.

Đáng chú ý: `agent/definitions/config.json` có field `"name": "luna"` nhưng
**không hề được inject vào system prompt** — tên trong prompt là chữ "Luna" cứng
trong `SOUL.md`/`RULES.md`. Nên chỉ đổi config.json là vô nghĩa.

## Ràng buộc

- **Một nguồn tên duy nhất** — mọi nơi prompt-facing đọc cùng một giá trị.
- **Mặc định = "Luna"** — không set env → output byte-identical như hiện tại.
- **Surgical** — không refactor ngoài phạm vi; `builder.py` không đổi nếu tránh được.
- **Không tự chạy git** (đưa lệnh cho user); tôn trọng quy tắc branch của CLAUDE.md.

## Phạm vi

**Trong phạm vi** (5 nơi prompt-facing — đã chốt với user "toàn bộ prompt-facing"):
persona (`SOUL.md`/`RULES.md`), câu chào voice, prompt gợi ý (suggestions), nhãn
người nói + prompt trong summary + snapshot.

**Ngoài phạm vi (giữ nguyên):**
- Tên *giọng* TTS `vieneu_voice_id` / `"luna"` (`voice/tts/http_vieneu.py`) — đây là
  preset giọng đã fine-tune, KHÁI NIỆM KHÁC với tên hiển thị của agent.
- Email `email_default_from = "luna@noblex.vn"` (`config.py`).
- Comment / docstring nhắc "Luna" (thuần mô tả, không ảnh hưởng runtime).
- Code eval/synthetic (`src/eval/*`, `src/synthetic/*`, `prompts/critic_multiturn_luna.txt`).
- Tên công ty **"NobleX"** — user chỉ yêu cầu đổi tên *agent*.

## Quyết định

1. **Đòn bẩy duy nhất:** `UnifiedSettings.agent_name: str = "Luna"` (env
   `NOBLE_AGENT_NAME`). Non-empty default → downstream dùng thẳng `settings.agent_name`,
   không cần `or "Luna"` rải rác.
2. **Persona render một lần lúc load**, không đổi `builder.py`. `SOUL.md`/`RULES.md`
   không chứa ký tự `{`/`}` nào khác (đã verify) → render jinja với biến `agent_name`
   an toàn.
3. **Threading param có default "Luna"** cho các helper thuần (suggestions/summary/
   snapshot) → test cũ gọi không truyền tên vẫn xanh.

## Thiết kế

### 1. `src/noble_agent/config.py` — nguồn tên

Thêm field vào `UnifiedSettings` (đặt cạnh `agent_model`/`summary_model`, dùng đúng
style positional `Field(<default>, alias=...)` như các field khác trong file):

```python
agent_name: str = Field("Luna", alias="NOBLE_AGENT_NAME")
```

### 2. `src/noble_agent/agent/definitions/` — persona

- `SOUL.md` dòng 1: `Bạn là Luna — chuyên viên NobleX.` → `Bạn là {{ agent_name }} — chuyên viên NobleX.`
- `RULES.md`: thay **cả 5** chỗ literal `Luna` → `{{ agent_name }}` (dòng ~21, ~73,
  ~130, ~138, ~167 — đều là "phạm vi của Luna" / "Luna KHÔNG tự xử lý"). Giữ nguyên
  "NobleX".
- `config.json`: `"name": "luna"` → `"Luna"` (default chuẩn khi load trực tiếp).

### 3. `src/noble_agent/agent/base.py` — render persona lúc load

`load_agent_def(definitions_dir, *, agent_name: str | None = None)`:

- `name = agent_name or config["name"]`.
- Render `SOUL.md` + `RULES.md` qua một jinja `Environment` (giống env đang có trong
  file) với biến `agent_name=name`, lưu **text đã thay** vào `sections["soul"]` /
  `sections["rules"]`.
- `AgentDef.name = name`.
- `CUSTOMER_PROFILE.md` không đụng (không chứa tên agent).

`builder.py` **không đổi** — nó chỉ chèn `agent.sections["soul"/"rules"]` (đã có tên)
vào `PROMPT_TEMPLATE.md`.

### 4. `src/noble_agent/agent/facade.py` — bơm tên vào

`_build_runner()` (đã có `settings = get_settings()`):

```python
agent_def = load_agent_def(defs_dir, agent_name=settings.agent_name)
```

### 5. `src/noble_agent/voice/voice_agent.py` — câu chào

Hai f-string trong `build_greeting` (đã có `settings` import module-level):

- `em là Luna, chuyên viên tư vấn NobleX ạ.` → `em là {settings.agent_name}, chuyên viên tư vấn NobleX ạ.`
- `Dạ em chào Quý Khách, em là Luna bên NobleX ạ.` → `... em là {settings.agent_name} bên NobleX ạ.`

### 6. `src/noble_agent/agent/suggestions.py` + `orchestrator.py` — prompt gợi ý

- `build_suggestions_prompt(user_text, assistant_text, customer, *, agent_name: str = "Luna")`:
  thay mọi literal `Luna` trong prompt (nhãn `[Luna]:`, câu mô tả "trợ lý bán hàng
  Luna", 'gọi trợ lý là "Luna/em"', '("em" là Luna)', "việc Luna THỰC SỰ làm được"…)
  bằng `{agent_name}`. Chuyển các đoạn liên quan sang f-string, giữ nguyên phần JSON
  ví dụ.
- `orchestrator.suggest_followups`: `build_suggestions_prompt(..., agent_name=self._settings.agent_name)`.

### 7. `src/noble_agent/agent/summary/generator.py` — summary

- `_format_history(history, max_turns=20, *, agent_name: str = "Luna")`: nhãn assistant
  `"Luna"` → `agent_name`.
- `_CALL_SUMMARY_PROMPT`: thêm placeholder `{agent}` thay 3 chỗ "Luna" mô tả
  ("Luna đã làm gì", "việc Luna hứa làm tiếp").
- Caller (hàm summarize, dòng ~204/~213) **KHÔNG có `settings` trong scope** →
  lấy `name = get_settings().agent_name` (đã `import get_settings` sẵn ở dòng 45), rồi
  truyền `agent_name=name` vào `_format_history` và `agent=name` vào `.format(...)`.

### 8. `src/noble_agent/agent/memory/snapshot.py` — snapshot

- `_flatten_history(history, max_turns=40, *, agent_name: str = "Luna")`: nhãn assistant
  `"Luna"` → `agent_name`. `build_merge_prompt(old_snapshot, history, *,
  agent_name: str = "Luna")` truyền xuống. Caller `merge_snapshot` (dòng ~100)
  **KHÔNG có `settings`** → truyền `agent_name=get_settings().agent_name` (đã
  `import get_settings` sẵn ở dòng 69).
- `_render(snapshot_text, turns, *, agent_name: str = "Luna")`: nhãn agent `"Luna"`
  → `agent_name`. Caller là `build_short_term_context(settings, ...)` (dòng ~174) —
  **có `settings` param** → truyền `agent_name=settings.agent_name`.
- `_MERGE_PROMPT` **không chứa "Luna"** → không đụng.

### 9. `.env.example`

Thêm dòng tài liệu:

```
# Tên hiển thị của agent trong prompt + câu chào (mặc định Luna).
NOBLE_AGENT_NAME=Luna
```

## Luồng dữ liệu

```
NOBLE_AGENT_NAME (env)
  → UnifiedSettings.agent_name  (default "Luna")
     ├─ facade → load_agent_def(agent_name=) → render SOUL/RULES → AgentDef.sections → builder → system prompt
     ├─ voice_agent.build_greeting  (settings.agent_name)
     ├─ orchestrator.suggest_followups → build_suggestions_prompt(agent_name=)
     ├─ summary.generator  (_format_history + _CALL_SUMMARY_PROMPT)
     └─ memory.snapshot    (_flatten_history + _render)
```

## Xử lý lỗi / biên

- **Env rỗng** (`NOBLE_AGENT_NAME=`): pydantic giữ `""` → prompt "Bạn là  —". Coi là
  lỗi cấu hình của user (giống các setting non-empty khác); không thêm guard đặc biệt.
  Mặc định (không set) an toàn = "Luna".
- **`load_agent_def()` gọi trực tiếp không truyền `agent_name`**: fallback
  `config["name"]` = "Luna" (sau khi sửa config.json) → persona đúng hoa.

## Testing

Unit (mọi test offline, không cần service):

1. `load_agent_def(defs_dir, agent_name="Aria")` → `AgentDef.name == "Aria"`,
   `sections["soul"]` chứa "Aria" và KHÔNG còn "Luna"; tương tự `sections["rules"]`.
2. `load_agent_def(defs_dir)` (không param) → tên "Luna" (từ config.json).
3. `build_suggestions_prompt(..., agent_name="Aria")` → chứa "Aria", không "Luna";
   default (không param) → "Luna".
4. `_format_history([...assistant...], agent_name="Aria")` → dòng nhãn "Aria:".
5. `_flatten_history` / `_render` với `agent_name="Aria"` → nhãn "Aria".
6. Regression: `settings.agent_name` default == "Luna".

Không thêm test cho voice greeting (chỉ đổi f-string trong I/O method; giá trị đã được
bao phủ bởi test settings).

## Files chạm

`config.py`, `agent/base.py`, `agent/facade.py`, `agent/definitions/{SOUL.md,RULES.md,config.json}`,
`voice/voice_agent.py`, `agent/suggestions.py`, `agent/orchestrator.py`,
`agent/summary/generator.py`, `agent/memory/snapshot.py`, `.env.example`, + test files.

## Không làm (YAGNI)

- Không tách "agent id" vs "display name" thành 2 khái niệm — một tên là đủ.
- Không cấu hình tên công ty / honorific / giọng TTS trong lần này.
- Không đổi `builder.py` / `PROMPT_TEMPLATE.md`.
