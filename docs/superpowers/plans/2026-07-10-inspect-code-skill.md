# inspect-code Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill `inspect-code` that generates a self-contained interactive HTML animation visualizing a code flow (mode `flow`) or a single function/module (mode `function`).

**Architecture:** "Engine once, data per run." A static, reviewed player (`assets/player.html`) renders an embedded `FLOW_MODEL` JSON. At skill run time, Claude only traces the code and emits that JSON, injects it into the player via a marker, and writes `docs/inspect/<slug>-<mode>.html`. No CDN, no build step, no server.

**Tech Stack:** Markdown (SKILL.md + references), a single HTML file with inline CSS + vanilla JS (SVG for edges). Python 3 (stdlib `json`) for verification. Optional: Playwright MCP for the end-to-end visual check.

## Global Constraints

- Output HTML MUST be self-contained: inline CSS + JS only, **no CDN, no external assets, no network**.
- Skill is **read-only** on source code — it never edits code being inspected.
- All narration text is **Vietnamese**.
- Every `file:line` in a generated model MUST point to a real line — read the code to verify, never guess.
- Skill lives at `.claude/skills/inspect-code/` (tracked in git); generated output goes to `docs/inspect/` (git-ignored).
- Do NOT touch `develop`. Work on the current branch (`feat/refactor2`). Local commits only.
- `FLOW_MODEL` injection marker is the exact literal `/*__FLOW_MODEL__*/ null` in `assets/player.html`.

---

### Task 1: Flow model contract (schema doc + example JSON)

Defines the data contract every later task depends on. Deliverable: a schema reference and a valid example model used both as a template for Claude and as the player's test fixture.

**Files:**
- Create: `.claude/skills/inspect-code/references/flow-model-schema.md`
- Create: `.claude/skills/inspect-code/references/example-model.json`

**Interfaces:**
- Produces: the `FLOW_MODEL` JSON shape — object with keys `mode` (`"flow"|"function"`), `title` (string), `nodes` (array of `{id, label, file, line, role, snippet}`), `edges` (array of `{from, to, label}`), `steps` (array of `{focus, activateEdges, narration}`). `activateEdges` is an array of `"<from>-><to>"` strings matching entries in `edges` (e.g. `"ws->session"`).

- [ ] **Step 1: Write the example model fixture**

Create `.claude/skills/inspect-code/references/example-model.json`:

```json
{
  "mode": "flow",
  "title": "Browser voice turn: audio → STT → agent → TTS",
  "nodes": [
    {
      "id": "ws",
      "label": "ws_handler._handle_session",
      "file": "src/noble_agent/server/ws_handler.py",
      "line": 74,
      "role": "Nhận kết nối WebSocket, parse session_id, mở phiên.",
      "snippet": "async def _handle_session(ws, client_ip):\n    raw_path = ws.request.path ...\n    session = Session(...)"
    },
    {
      "id": "session",
      "label": "session.process_audio_frame",
      "file": "src/noble_agent/server/base_session.py",
      "line": 1,
      "role": "Resample 48→16kHz, chạy VAD, đẩy PCM vào STT.",
      "snippet": "def process_audio_frame(self, pcm):\n    # VAD trước, rồi gate, rồi stt.send(...)"
    },
    {
      "id": "agent",
      "label": "NobleAgent.stream_response",
      "file": "src/noble_agent/agent/facade.py",
      "line": 1,
      "role": "Điểm vào agent core: chạy TurnRunner cho một lượt.",
      "snippet": "async def stream_response(self, text):\n    return self._runner.handle_turn(...)"
    },
    {
      "id": "tts",
      "label": "VoiceAgent.tts_consumer",
      "file": "src/noble_agent/voice/voice_agent.py",
      "line": 1,
      "role": "Tách câu, synth TTS, resample 24→48kHz, phát audio.",
      "snippet": "async def tts_consumer(self):\n    async for clause in self.sentence_buffer:\n        await self._synth_ahead(clause)"
    }
  ],
  "edges": [
    { "from": "ws", "to": "session", "label": "PCM 48kHz" },
    { "from": "session", "to": "agent", "label": "text đã STT" },
    { "from": "agent", "to": "tts", "label": "token trả lời" }
  ],
  "steps": [
    { "focus": "ws", "activateEdges": [], "narration": "Client kết nối WebSocket; phiên được mở và bắt đầu nhận audio 48kHz." },
    { "focus": "session", "activateEdges": ["ws->session"], "narration": "Audio được resample xuống 16kHz, VAD phát hiện tiếng nói, PCM đẩy vào STT." },
    { "focus": "agent", "activateEdges": ["session->agent"], "narration": "STT ra text; text được đưa vào NobleAgent để chạy một lượt hội thoại." },
    { "focus": "tts", "activateEdges": ["agent->tts"], "narration": "Token trả lời được tách câu, synth thành audio 24kHz rồi resample 48kHz phát ra loa." }
  ]
}
```

- [ ] **Step 2: Verify the example JSON parses**

Run: `python3 -m json.tool .claude/skills/inspect-code/references/example-model.json > /dev/null && echo OK`
Expected: prints `OK` (no JSON error).

- [ ] **Step 3: Write the schema reference doc**

Create `.claude/skills/inspect-code/references/flow-model-schema.md`:

````markdown
# FLOW_MODEL schema

The player (`assets/player.html`) renders one `FLOW_MODEL` object. Claude
generates this object each run and injects it into the player.

## Top level

| Key | Type | Notes |
|---|---|---|
| `mode` | `"flow"` \| `"function"` | `flow` = a flow from an entrypoint; `function` = one function's internals + callers/callees. |
| `title` | string | Tiêu đề hiển thị ở header. |
| `nodes` | array | Các hộp trong sơ đồ. |
| `edges` | array | Mũi tên giữa các node. |
| `steps` | array | Kịch bản animation tuần tự. |

## `nodes[]`

| Key | Type | Notes |
|---|---|---|
| `id` | string | Duy nhất, không dấu cách. Dùng để tham chiếu trong edges/steps. |
| `label` | string | Tên hàm/module hiển thị trên hộp. |
| `file` | string | Đường dẫn repo-relative. |
| `line` | number | Dòng THẬT (đọc code để lấy đúng, không đoán). |
| `role` | string | Một câu tiếng Việt: node này làm gì. |
| `snippet` | string | Vài dòng code tiêu biểu (giữ ngắn). `\n` cho xuống dòng. |

## `edges[]`

`{ "from": "<node id>", "to": "<node id>", "label": "dữ liệu đi qua" }`

## `steps[]`

| Key | Type | Notes |
|---|---|---|
| `focus` | string | `id` của node được tô sáng ở step này. |
| `activateEdges` | string[] | Danh sách `"<from>-><to>"` khớp với `edges`, sáng lên ở step này. Có thể rỗng. |
| `narration` | string | Lời giảng tiếng Việt cho step. |

## Ngữ nghĩa theo mode

- `flow`: `nodes` = các function/module trên đường đi; `edges` = gọi/truyền dữ liệu; `steps` đi theo thứ tự thời gian input→output.
- `function`: `nodes` = các block/nhánh nội bộ của hàm + callers (ai gọi) + callees (gọi ai); `edges` = call/return/data; `steps` đi qua control flow rồi làm rõ quan hệ ngoài.

## Ràng buộc

- Mọi `file`/`line` phải có thật.
- `focus` và mỗi id trong `activateEdges` phải tồn tại trong `nodes`/`edges`.
- Không để field rỗng/placeholder.
````

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/inspect-code/references/
git commit -m "feat(inspect-code): flow-model schema + example fixture"
```

---

### Task 2: Player template (`assets/player.html`)

The static, reviewed animation engine. Renders `FLOW_MODEL`, draws nodes + SVG edges, and animates step-by-step with Play/Step/speed controls and a Vietnamese narration panel.

**Files:**
- Create: `.claude/skills/inspect-code/assets/player.html`
- Test (temporary, not committed): `/tmp/claude-1000/-home-dutn-Documents-Hotline-Agent-santa-hotline-agent/20d7adf5-1a7a-48e0-b8c9-7ae0711d3bd4/scratchpad/inspect-test.html`

**Interfaces:**
- Consumes: the `FLOW_MODEL` shape from Task 1, injected by replacing the literal `/*__FLOW_MODEL__*/ null`.
- Produces: a working player. Skill code (Task 3) relies on the injection marker string being exactly `/*__FLOW_MODEL__*/ null`.

- [ ] **Step 1: Write the player file**

Create `.claude/skills/inspect-code/assets/player.html` with this exact content:

```html
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>inspect-code</title>
<style>
  :root { --bg:#0f1420; --panel:#1a2233; --line:#2c3752; --fg:#e6ecf7; --muted:#8b97b0;
          --accent:#4da3ff; --hot:#ffcc66; }
  * { box-sizing: border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--fg);
              font:14px/1.5 system-ui, "Segoe UI", sans-serif; }
  header { padding:12px 18px; border-bottom:1px solid var(--line); display:flex;
           align-items:center; gap:12px; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  #mode-badge { font-size:11px; padding:2px 8px; border:1px solid var(--line);
                border-radius:10px; color:var(--muted); text-transform:uppercase; }
  main { display:grid; grid-template-columns: 1.3fr 1fr; gap:0; height:calc(100% - 132px); }
  #graph-pane { position:relative; overflow:auto; padding:24px; }
  #edges { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
  #nodes { position:relative; display:flex; flex-direction:column; gap:28px; align-items:center; }
  .node { position:relative; z-index:1; width:min(420px,90%); background:var(--panel);
          border:1px solid var(--line); border-radius:10px; padding:10px 14px;
          transition:all .25s; }
  .node .label { font-weight:600; }
  .node .loc { font-size:11px; color:var(--muted); }
  .node.active { border-color:var(--hot); box-shadow:0 0 0 2px var(--hot),0 0 22px rgba(255,204,102,.35); }
  .edge { stroke:var(--line); stroke-width:2; fill:none; marker-end:url(#arrow); }
  .edge.active { stroke:var(--hot); stroke-width:3; stroke-dasharray:8 6;
                 animation:flow 1s linear infinite; }
  @keyframes flow { to { stroke-dashoffset:-28; } }
  #code-pane { border-left:1px solid var(--line); padding:18px; overflow:auto; background:#0c111b; }
  #code-loc { font-size:12px; color:var(--accent); margin-bottom:8px; word-break:break-all; }
  #code-snippet { white-space:pre-wrap; font:12px/1.55 "JetBrains Mono", ui-monospace, monospace;
                  color:#cdd8ee; }
  #node-role { margin-top:12px; color:var(--muted); font-size:12px; }
  footer { border-top:1px solid var(--line); padding:10px 18px; height:132px; }
  #controls { display:flex; align-items:center; gap:10px; margin-bottom:8px; flex-wrap:wrap; }
  button { background:var(--panel); color:var(--fg); border:1px solid var(--line);
           border-radius:6px; padding:6px 12px; cursor:pointer; }
  button:hover { border-color:var(--accent); }
  #step-counter { color:var(--muted); font-size:12px; }
  #narration { background:var(--panel); border:1px solid var(--line); border-radius:8px;
               padding:10px 14px; min-height:40px; }
  .empty { padding:40px; color:var(--muted); }
</style>
</head>
<body>
<header><h1 id="title">inspect-code</h1><span id="mode-badge"></span></header>
<main>
  <section id="graph-pane"><svg id="edges"><defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="var(--line)"></path>
    </marker></defs></svg><div id="nodes"></div></section>
  <aside id="code-pane">
    <div id="code-loc"></div>
    <pre><code id="code-snippet"></code></pre>
    <div id="node-role"></div>
  </aside>
</main>
<footer>
  <div id="controls">
    <button id="prev">◀ Prev</button>
    <button id="play">▶ Play</button>
    <button id="next">Next ▶</button>
    <label>Tốc độ <input id="speed" type="range" min="400" max="3000" step="200" value="1500"></label>
    <span id="step-counter"></span>
  </div>
  <div id="narration"></div>
</footer>
<script>
const FLOW_MODEL = /*__FLOW_MODEL__*/ null;

const $ = (id) => document.getElementById(id);

function render(model) {
  if (!model || !Array.isArray(model.nodes) || !Array.isArray(model.steps)) {
    document.body.innerHTML = '<div class="empty">Chưa nhúng FLOW_MODEL hợp lệ.</div>';
    return;
  }
  $("title").textContent = model.title || "inspect-code";
  $("mode-badge").textContent = model.mode || "";

  const nodesEl = $("nodes");
  const nodeById = {};
  model.nodes.forEach(n => {
    nodeById[n.id] = n;
    const div = document.createElement("div");
    div.className = "node";
    div.dataset.id = n.id;
    div.innerHTML =
      '<div class="label"></div><div class="loc"></div>';
    div.querySelector(".label").textContent = n.label || n.id;
    div.querySelector(".loc").textContent = (n.file || "") + (n.line ? ":" + n.line : "");
    nodesEl.appendChild(div);
  });

  const svg = $("edges");
  const edgeEls = {};
  (model.edges || []).forEach(e => {
    const key = e.from + "->" + e.to;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("class", "edge");
    path.dataset.key = key;
    svg.appendChild(path);
    edgeEls[key] = path;
  });

  function layoutEdges() {
    const pane = $("graph-pane").getBoundingClientRect();
    (model.edges || []).forEach(e => {
      const a = nodesEl.querySelector('[data-id="' + e.from + '"]');
      const b = nodesEl.querySelector('[data-id="' + e.to + '"]');
      const path = edgeEls[e.from + "->" + e.to];
      if (!a || !b || !path) return;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const x1 = ra.left + ra.width/2 - pane.left + $("graph-pane").scrollLeft;
      const y1 = ra.bottom - pane.top + $("graph-pane").scrollTop;
      const x2 = rb.left + rb.width/2 - pane.left + $("graph-pane").scrollLeft;
      const y2 = rb.top - pane.top + $("graph-pane").scrollTop;
      const my = (y1 + y2) / 2;
      path.setAttribute("d", `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`);
    });
  }

  let i = 0, timer = null;
  function applyStep(idx) {
    i = Math.max(0, Math.min(idx, model.steps.length - 1));
    const step = model.steps[i];
    nodesEl.querySelectorAll(".node").forEach(el =>
      el.classList.toggle("active", el.dataset.id === step.focus));
    Object.values(edgeEls).forEach(p => p.classList.remove("active"));
    (step.activateEdges || []).forEach(k => edgeEls[k] && edgeEls[k].classList.add("active"));
    const n = nodeById[step.focus] || {};
    $("code-loc").textContent = (n.file || "") + (n.line ? ":" + n.line : "");
    $("code-snippet").textContent = n.snippet || "";
    $("node-role").textContent = n.role || "";
    $("narration").textContent = step.narration || "";
    $("step-counter").textContent = (i + 1) + " / " + model.steps.length;
    const el = nodesEl.querySelector('[data-id="' + step.focus + '"]');
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } $("play").textContent = "▶ Play"; }
  function play() {
    if (timer) { stop(); return; }
    $("play").textContent = "⏸ Pause";
    timer = setInterval(() => {
      if (i >= model.steps.length - 1) { stop(); return; }
      applyStep(i + 1);
    }, Number($("speed").value));
  }
  $("prev").onclick = () => { stop(); applyStep(i - 1); };
  $("next").onclick = () => { stop(); applyStep(i + 1); };
  $("play").onclick = play;
  $("speed").oninput = () => { if (timer) { stop(); play(); } };

  requestAnimationFrame(() => { layoutEdges(); applyStep(0); });
  window.addEventListener("resize", layoutEdges);
  $("graph-pane").addEventListener("scroll", layoutEdges);
}
render(FLOW_MODEL);
</script>
</body>
</html>
```

- [ ] **Step 2: Verify the marker exists exactly once**

Run: `grep -c '/\*__FLOW_MODEL__\*/ null' .claude/skills/inspect-code/assets/player.html`
Expected: `1`

- [ ] **Step 3: Build a test HTML by injecting the example model**

Run:
```bash
python3 - <<'PY'
import json, pathlib
base = pathlib.Path(".claude/skills/inspect-code")
tpl = (base/"assets/player.html").read_text()
model = (base/"references/example-model.json").read_text().strip()
out = tpl.replace("/*__FLOW_MODEL__*/ null", model, 1)
assert out != tpl, "marker not replaced"
dest = pathlib.Path("/tmp/claude-1000/-home-dutn-Documents-Hotline-Agent-santa-hotline-agent/20d7adf5-1a7a-48e0-b8c9-7ae0711d3bd4/scratchpad/inspect-test.html")
dest.write_text(out)
print("wrote", dest)
PY
```
Expected: prints `wrote .../inspect-test.html`, no assertion error.

- [ ] **Step 4: Drive the test HTML with Playwright MCP and assert it renders**

Use the Playwright MCP tools (load their schemas via ToolSearch `select:mcp__plugin_playwright_playwright__browser_navigate,mcp__plugin_playwright_playwright__browser_evaluate` first):
1. `browser_navigate` to `file:///tmp/claude-1000/-home-dutn-Documents-Hotline-Agent-santa-hotline-agent/20d7adf5-1a7a-48e0-b8c9-7ae0711d3bd4/scratchpad/inspect-test.html`
2. `browser_evaluate` with:
   `() => ({ nodes: document.querySelectorAll('.node').length, edges: document.querySelectorAll('path.edge').length, active: document.querySelector('.node.active')?.dataset.id, narration: document.getElementById('narration').textContent.length })`

Expected: `nodes` = 4, `edges` = 3, `active` = `"ws"`, `narration` > 0.
(Fallback if Playwright unavailable: open the file with `xdg-open` and visually confirm 4 boxes, arrows, Play advances steps, narration + code update.)

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/inspect-code/assets/player.html
git commit -m "feat(inspect-code): static animation player template"
```

---

### Task 3: SKILL.md + git-ignore for output

Wires the pieces into an invokable skill: trigger description, mode selection, the run workflow (trace → emit JSON → inject → write → open), and the anti-hallucination verification rules. Also ignores the generated output directory.

**Files:**
- Create: `.claude/skills/inspect-code/SKILL.md`
- Modify: `.gitignore` (append `docs/inspect/`)

**Interfaces:**
- Consumes: `assets/player.html` (marker `/*__FLOW_MODEL__*/ null`), `references/flow-model-schema.md`, `references/example-model.json` from Tasks 1–2.
- Produces: the `inspect-code` skill, discoverable via its `description` frontmatter.

- [ ] **Step 1: Write SKILL.md**

Create `.claude/skills/inspect-code/SKILL.md`:

````markdown
---
name: inspect-code
description: Use when the user wants a visual, animated diagram of how code flows — trace an entrypoint end-to-end, or inspect one function/module's internal control flow + callers/callees. Produces a self-contained interactive HTML animation. Triggers on "/inspect", "trực quan hoá luồng", "vẽ animation flow", "inspect function", "animate flow", "visualize this flow".
---

# inspect-code

Sinh **animation HTML tương tác** trực quan hoá luồng code. Read-only — KHÔNG sửa
code. Narration bằng **tiếng Việt**. Khác `learn-codebase`/`walkthrough-*` (ra văn
bản): skill này ra **hình ảnh động**.

## Chọn mode

- Người dùng muốn xem một luồng từ đầu vào tới kết quả, hoặc gõ `/inspect` không nói rõ → **mode `flow`**.
- Người dùng chỉ một function/module cụ thể ("inspect function X", "hàm này làm gì") → **mode `function`**.
- Mơ hồ → hỏi đúng một câu: "Bạn muốn xem một luồng end-to-end (flow) hay mổ xẻ một function (function)?"

## Quy trình

1. **Xác định target.**
   - `flow`: nếu chưa rõ entrypoint, Grep tìm các entrypoint (ví dụ `server/ws_handler.py`, `server/text_chat.py`, `telephony/`, `transport/livekit/`) và đề xuất cho user chọn.
   - `function`: Grep định vị đúng file:line của function/module.
2. **Thu thập dữ liệu — ưu tiên tài liệu sẵn có.**
   - Nếu có `docs/walkthrough/<seam>.md` khớp target → đọc làm nguồn chính, map các bước file:line thành nodes/steps.
   - Nếu không → trace code trực tiếp bằng Grep/Read từ target. Codebase lớn: có thể dispatch vài Explore subagent song song theo từng hop.
   - LUÔN đọc code thật để lấy `file:line` ĐÚNG. Không đoán.
3. **Sinh FLOW_MODEL (JSON).** Theo đúng `references/flow-model-schema.md`. Bắt chước `references/example-model.json`. Narration tiếng Việt. Với `function`: nodes gồm cả block nội bộ + callers/callees.
4. **Ghép & ghi file.** Đọc `assets/player.html`, thay chuỗi `/*__FLOW_MODEL__*/ null` (đúng 1 lần) bằng JSON, ghi ra `docs/inspect/<slug>-<mode>.html` (`<slug>` = tên target không dấu, kebab-case). Dùng script ở dưới.
5. **Xác minh.** Chạy lại bước kiểm tra (JSON parse, marker đã thay, không placeholder rỗng). Nếu có Playwright MCP: mở file, assert số node > 0 và narration không rỗng.
6. **Báo.** In đường dẫn file + `xdg-open <path>` để mở; tóm tắt ngắn luồng bằng text tiếng Việt.

## Script ghép & ghi (dùng ở bước 4)

Ghi JSON model ra file tạm `model.json` trong scratchpad rồi:

```bash
python3 - "$MODEL_JSON_PATH" "$OUT_HTML_PATH" <<'PY'
import json, pathlib, sys
skill = pathlib.Path(".claude/skills/inspect-code")
model = pathlib.Path(sys.argv[1]).read_text().strip()
json.loads(model)  # fail sớm nếu JSON hỏng
tpl = (skill/"assets/player.html").read_text()
out = tpl.replace("/*__FLOW_MODEL__*/ null", model, 1)
assert out != tpl, "marker not found — không thay được model"
dest = pathlib.Path(sys.argv[2]); dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(out); print("wrote", dest)
PY
```

## Ràng buộc (bắt buộc)

- Read-only trên code nguồn.
- Mọi `file:line` phải trỏ dòng có thật — verify bằng cách đọc code.
- Output self-contained, không CDN. Ghi vào `docs/inspect/` (đã git-ignore).
- Không để field rỗng/placeholder trong model.
````

- [ ] **Step 2: Append output dir to .gitignore**

Run:
```bash
printf '\n# inspect-code generated animations\ndocs/inspect/\n' >> .gitignore
grep -n 'docs/inspect/' .gitignore
```
Expected: prints the line `docs/inspect/`.

- [ ] **Step 3: Verify frontmatter parses and paths referenced exist**

Run:
```bash
head -4 .claude/skills/inspect-code/SKILL.md
ls .claude/skills/inspect-code/assets/player.html .claude/skills/inspect-code/references/flow-model-schema.md .claude/skills/inspect-code/references/example-model.json
```
Expected: frontmatter shows `name: inspect-code` + a `description:` line; all three files listed (no "No such file").

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/inspect-code/SKILL.md .gitignore
git commit -m "feat(inspect-code): SKILL.md workflow + ignore generated output"
```

---

### Task 4: End-to-end acceptance on a real flow

Prove the whole skill works by running it against a real entrypoint and confirming a usable animation is produced. This is the acceptance gate.

**Files:**
- Produces (git-ignored): `docs/inspect/voice-turn-flow.html`

**Interfaces:**
- Consumes: the complete skill from Tasks 1–3.

- [ ] **Step 1: Trace the browser voice-turn flow**

Read `docs/walkthrough/audio-pipeline.md` and `docs/walkthrough/turn-lifecycle.md` as the primary source; confirm each `file:line` against the real files (start at `src/noble_agent/server/ws_handler.py:74` `_handle_session`). Build a real `FLOW_MODEL` for `mode: "flow"` covering audio → STT → agent turn → TTS. Write it to the scratchpad as `voice-turn-model.json`.

- [ ] **Step 2: Verify the traced model's file:line are real**

For each node, run (example): `sed -n '<line>p' <file>` and confirm the line matches the node's `label`/`snippet`. Fix any mismatch. There must be zero fabricated locations.

- [ ] **Step 3: Generate the HTML via the skill script**

Run the "Script ghép & ghi" from SKILL.md with `voice-turn-model.json` → `docs/inspect/voice-turn-flow.html`.
Expected: prints `wrote docs/inspect/voice-turn-flow.html`.

- [ ] **Step 4: Drive it with Playwright and assert the animation works**

`browser_navigate` to the `file://` path, then `browser_evaluate`:
`() => { document.getElementById('next').click(); return { nodes: document.querySelectorAll('.node').length, step: document.getElementById('step-counter').textContent, active: document.querySelector('.node.active')?.dataset.id, activeEdges: document.querySelectorAll('path.edge.active').length }; }`
Expected: `nodes` ≥ 4, `step` shows `2 / N`, `active` is a real node id, `activeEdges` ≥ 1 (an edge lit after advancing).
(Fallback: `xdg-open docs/inspect/voice-turn-flow.html` and visually confirm Play animates through all steps with narration + code updating.)

- [ ] **Step 5: Confirm no accidental tracking of generated output**

Run: `git status --porcelain docs/inspect/`
Expected: empty output (the dir is git-ignored; the HTML is not staged).

- [ ] **Step 6: Final smoke summary**

State in the response: skill invoked in `flow` mode, produced `docs/inspect/voice-turn-flow.html`, Playwright (or manual) confirmed nodes render + Play/Step advances + narration/code panels update. No source files modified.

---

## Self-Review

**1. Spec coverage:**
- Định vị + khác biệt skill (spec §1) → SKILL.md header (Task 3).
- Output self-contained, local, no CDN (spec §2, Global Constraints) → Task 2 player + Global Constraints.
- Hai mode flow/function (spec §2) → SKILL.md "Chọn mode" + schema semantics (Tasks 1, 3).
- Kiến trúc engine/model tách bạch (spec §3) → Task 2 (player) + Task 1 (model) + Task 3 injection script.
- Flow model JSON schema (spec §3) → Task 1 fixture + schema doc.
- Engine phân tích: reuse walkthrough → else trace → Explore subagents (spec §3) → SKILL.md step 2.
- Quy trình 6 bước (spec §4) → SKILL.md "Quy trình".
- Xác minh chống bịa (spec §5) → Global Constraints + SKILL.md ràng buộc + Task 4 step 2.
- Cấu trúc thư mục (spec §6) → Tasks 1–3 file paths.
- Triggers (spec §7) → SKILL.md description frontmatter.
- Tiêu chí thành công (spec §8) → Task 4 acceptance.
All spec sections map to a task. No gaps.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". The one `line: 1` values in the Task 1 *example fixture* are intentional (illustrative fixture, not source of truth); the real acceptance model (Task 4) verifies every line against source. Player code, schema doc, and SKILL.md are complete.

**3. Type consistency:** Injection marker `/*__FLOW_MODEL__*/ null` is identical in Task 2 (player), Task 2 step 3 (test build), Task 3 (skill script), Task 4. `activateEdges` uses `"<from>-><to>"` strings consistently across the schema doc, example fixture, and player `edgeEls` keying. `FLOW_MODEL` keys (`mode/title/nodes/edges/steps`, node `id/label/file/line/role/snippet`, edge `from/to/label`, step `focus/activateEdges/narration`) match between Task 1 and the player's DOM code in Task 2.
