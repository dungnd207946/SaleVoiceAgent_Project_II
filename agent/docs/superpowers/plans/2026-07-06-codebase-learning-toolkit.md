# Codebase Learning Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trang bị cho repo `santa-hotline-agent` bộ công cụ học sâu codebase: skill `learn-codebase` (teach + explain-diff), lệnh `/walkthrough-init` và `/walkthrough-sync`, cùng hook đánh dấu walkthrough lỗi thời sau khi sửa code.

**Architecture:** 4 thành phần project-local trong `.claude/`. Một hook bash rẻ (không gọi LLM) ghi file `src/` đã sửa vào stale log ở PostToolUse và nhắc ở Stop. Hai slash command markdown điều khiển việc sinh/cập nhật `docs/walkthrough/*`. Một skill markdown hai mode dùng walkthrough làm nguồn giảng dạy + ép kỷ luật giải thích-trước-khi-merge.

**Tech Stack:** Bash (hook + test), JSON (settings.json), Markdown với YAML frontmatter (skill + commands), Python 3 (chỉ để parse JSON trong hook, đã có sẵn).

## Global Constraints

- Tất cả artifact nằm trong `santa-hotline-agent/.claude/` và `docs/`, commit vào git repo (KHÔNG cài global `~/.claude`).
- Làm việc trên branch hiện tại (`feat/refactor2`); KHÔNG đụng `develop`, KHÔNG tạo branch mới, KHÔNG push/merge/PR.
- Mỗi commit CHỈ add đúng các file của task đó (working tree đang có nhiều WIP không liên quan — không được `git add -A`/`git add .`).
- Hook KHÔNG BAO GIỜ chặn công việc: mọi nhánh phải `exit 0`.
- Hook KHÔNG gọi LLM (chi phí ~0 token).
- Skill + command phản hồi bằng tiếng Việt; mọi giải thích luồng BẮT BUỘC kèm `file:line` dạng markdown link click được.
- Stale log là state tạm: `.claude/walkthrough-stale.log`, phải được gitignore.
- Filter file kích hoạt stale: đường dẫn chứa `/src/`, loại trừ `/tests/`, `/docs/`, `/.claude/`.

---

### Task 1: Hook đánh dấu stale + bash test

**Files:**
- Create: `.claude/hooks/walkthrough-stale.sh`
- Test: `.claude/hooks/test-walkthrough-stale.sh`

**Interfaces:**
- Produces: script `walkthrough-stale.sh` nhận 1 arg (`post` | `stop`).
  - `post`: đọc JSON PostToolUse trên stdin, lấy `tool_input.file_path`; nếu path chứa `/src/` và KHÔNG chứa `/tests/`, `/docs/`, `/.claude/` → append (dedupe) vào `$CLAUDE_PROJECT_DIR/.claude/walkthrough-stale.log`. Luôn `exit 0`.
  - `stop`: nếu log tồn tại và khác rỗng → in nhắc ra stderr, `exit 0`.
  - Log path resolve qua `${CLAUDE_PROJECT_DIR:-$(pwd)}`.

- [ ] **Step 1: Viết test thất bại**

Tạo `.claude/hooks/test-walkthrough-stale.sh`:

```bash
#!/usr/bin/env bash
# Test harness cho walkthrough-stale.sh. Chạy: bash .claude/hooks/test-walkthrough-stale.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/walkthrough-stale.sh"
pass=0; fail=0
check() { # desc, expected, actual
  if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass+1));
  else echo "FAIL - $1 (expected [$2] got [$3])"; fail=$((fail+1)); fi
}

run_post() { # json -> feeds stdin, returns exit code; log in $TMP/.claude/walkthrough-stale.log
  printf '%s' "$1" | CLAUDE_PROJECT_DIR="$TMP" bash "$SCRIPT" post
}

TMP="$(mktemp -d)"; mkdir -p "$TMP/.claude"
LOG="$TMP/.claude/walkthrough-stale.log"

# 1. Edit trong src/ -> ghi log
run_post '{"tool_name":"Edit","tool_input":{"file_path":"'"$TMP"'/src/noble_agent/agent/facade.py"}}'
check "src file logged" "$TMP/src/noble_agent/agent/facade.py" "$(cat "$LOG" 2>/dev/null)"

# 2. Edit trong tests/ -> không ghi (log không đổi)
run_post '{"tool_name":"Edit","tool_input":{"file_path":"'"$TMP"'/tests/unit/test_x.py"}}'
check "tests file ignored" "1" "$(wc -l < "$LOG" | tr -d ' ')"

# 3. Edit trong docs/ -> không ghi
run_post '{"tool_name":"Write","tool_input":{"file_path":"'"$TMP"'/docs/walkthrough/turn.md"}}'
check "docs file ignored" "1" "$(wc -l < "$LOG" | tr -d ' ')"

# 4. Dedupe: cùng path 2 lần -> 1 dòng
run_post '{"tool_name":"Edit","tool_input":{"file_path":"'"$TMP"'/src/noble_agent/agent/facade.py"}}'
check "dedupe" "1" "$(wc -l < "$LOG" | tr -d ' ')"

# 5. JSON hỏng -> exit 0, log không đổi
run_post 'not-json'; rc=$?
check "malformed json exit0" "0" "$rc"
check "malformed json no write" "1" "$(wc -l < "$LOG" | tr -d ' ')"

# 6. Stop với log không rỗng -> in nhắc ra stderr
msg="$(CLAUDE_PROJECT_DIR="$TMP" bash "$SCRIPT" stop 2>&1 >/dev/null)"
case "$msg" in *walkthrough-sync*) check "stop reminds" "yes" "yes";; *) check "stop reminds" "yes" "no";; esac

# 7. Stop với log rỗng -> không in gì
: > "$LOG"
msg="$(CLAUDE_PROJECT_DIR="$TMP" bash "$SCRIPT" stop 2>&1 >/dev/null)"
check "stop silent when empty" "" "$msg"

rm -rf "$TMP"
echo "---"; echo "PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `bash .claude/hooks/test-walkthrough-stale.sh`
Expected: FAIL — script chưa tồn tại (`walkthrough-stale.sh: No such file or directory`), dòng cuối `PASS=0 FAIL=...` hoặc lỗi không tìm thấy file.

- [ ] **Step 3: Viết script tối thiểu**

Tạo `.claude/hooks/walkthrough-stale.sh`:

```bash
#!/usr/bin/env bash
# walkthrough-stale.sh — đánh dấu walkthrough lỗi thời sau khi sửa code (rẻ, không gọi LLM).
# Dùng:
#   walkthrough-stale.sh post   # PostToolUse: append file src/ đã sửa vào stale log
#   walkthrough-stale.sh stop   # Stop: nhắc nếu stale log khác rỗng
# Không bao giờ chặn: luôn exit 0.
set -u
mode="${1:-post}"
root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
log="$root/.claude/walkthrough-stale.log"

if [ "$mode" = "stop" ]; then
  if [ -s "$log" ]; then
    n=$(wc -l < "$log" | tr -d ' ')
    echo "⚠ $n file code đã đổi từ lần sync walkthrough gần nhất — chạy /walkthrough-sync" >&2
  fi
  exit 0
fi

# mode = post: đọc file_path từ JSON stdin (dùng python3, không phụ thuộc jq)
fp=$(python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
print(d.get("tool_input",{}).get("file_path","") or "")' 2>/dev/null)

[ -z "$fp" ] && exit 0

# chỉ code trong src/; loại trừ tests/docs/.claude
case "$fp" in
  */src/*) : ;;
  *) exit 0 ;;
esac
case "$fp" in
  */tests/*|*/docs/*|*/.claude/*) exit 0 ;;
esac

mkdir -p "$root/.claude"
if [ -f "$log" ] && grep -qxF "$fp" "$log" 2>/dev/null; then
  exit 0
fi
echo "$fp" >> "$log"
exit 0
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `chmod +x .claude/hooks/walkthrough-stale.sh .claude/hooks/test-walkthrough-stale.sh && bash .claude/hooks/test-walkthrough-stale.sh`
Expected: mọi dòng `ok   - ...`, dòng cuối `PASS=7 FAIL=0`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/walkthrough-stale.sh .claude/hooks/test-walkthrough-stale.sh
git commit -m "feat(hooks): walkthrough stale-marking hook + bash tests"
```

---

### Task 2: Wire hook vào settings.json + gitignore

**Files:**
- Modify: `.claude/settings.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `.claude/hooks/walkthrough-stale.sh` từ Task 1.
- Produces: hook `PostToolUse` (matcher `Edit|Write|MultiEdit`) và `Stop` chạy script; `.claude/walkthrough-stale.log` được gitignore.

- [ ] **Step 1: Cập nhật `.claude/settings.json`**

File hiện tại chỉ có `enabledPlugins`. Thay toàn bộ nội dung thành:

```json
{
  "enabledPlugins": {
    "harness@harness-marketplace": true
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/walkthrough-stale.sh\" post"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/walkthrough-stale.sh\" stop"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Xác nhận JSON hợp lệ**

Run: `python3 -c 'import json;json.load(open(".claude/settings.json"));print("valid")'`
Expected: `valid`

- [ ] **Step 3: Thêm stale log vào `.gitignore`**

Append dòng sau vào `.gitignore` (giữ nguyên nội dung cũ):

```
.claude/walkthrough-stale.log
```

- [ ] **Step 4: Xác nhận gitignore có hiệu lực**

Run: `touch .claude/walkthrough-stale.log && git check-ignore .claude/walkthrough-stale.log; rm -f .claude/walkthrough-stale.log`
Expected: in ra `.claude/walkthrough-stale.log` (nghĩa là đã bị ignore).

- [ ] **Step 5: Commit**

```bash
git add .claude/settings.json .gitignore
git commit -m "chore(hooks): wire walkthrough stale hook (PostToolUse+Stop), gitignore stale log"
```

---

### Task 3: Lệnh `/walkthrough-init`

**Files:**
- Create: `.claude/commands/walkthrough-init.md`

**Interfaces:**
- Produces: slash command `/walkthrough-init` sinh `docs/walkthrough/README.md` + một file `<seam>.md` cho mỗi seam.

- [ ] **Step 1: Tạo file lệnh**

Tạo `.claude/commands/walkthrough-init.md`:

```markdown
---
description: Sinh tài liệu walkthrough (README index + file theo seam) giải thích luồng codebase, mỗi bước kèm file:line.
---

Bạn đang tạo tài liệu walkthrough cho codebase này để phục vụ học sâu + onboarding. Trả lời bằng tiếng Việt.

## Bước 1 — Kiểm tra tồn tại
Nếu thư mục `docs/walkthrough/` đã có file, HỎI người dùng có ghi đè không trước khi tiếp tục.

## Bước 2 — Nắm kiến trúc
Đọc `CLAUDE.md` phần "Architecture" và cấu trúc `src/noble_agent/` để xác định các seam (luồng nghiệp vụ chính). Seam mặc định của dự án này:
- `turn-lifecycle`: facade.py → orchestrator.py → runner.py (LLM + tool loop, invariant history)
- `audio-pipeline`: mic → VAD → STT → LLM → sentence buffer → TTS → speaker
- `storage`: 3 Redis key (meta/customer/state), Mongo, summary/WATCH
- `transports`: 4 transport (WebRTC/text/telephony/livekit) hội tụ về NobleAgent

Nếu phát hiện seam quan trọng khác (RAG stack, semcache, tools/dispatcher), đề xuất và HỎI người dùng có thêm không.

## Bước 3 — Sinh file
Tạo:
- `docs/walkthrough/README.md`: bản đồ tổng — bảng liệt kê seam + mô tả 1 dòng + link tới từng file.
- `docs/walkthrough/<seam>.md` cho mỗi seam:
  - Sơ đồ ASCII của luồng.
  - Giải thích TỪNG BƯỚC, mỗi bước BẮT BUỘC kèm markdown link `file:line` (ví dụ `[facade.py:42](src/noble_agent/agent/facade.py#L42)`).
  - Viết cho kỹ sư mới: nói rõ "cái gì gọi cái gì", "vì sao", invariant cần giữ.
  - PHẢI đọc code thật để lấy số dòng chính xác — KHÔNG bịa line number.

## Bước 4 — Xác nhận
Liệt kê các file đã tạo và gợi ý người dùng dùng `/learn` để học từng seam.
```

- [ ] **Step 2: Xác nhận frontmatter hợp lệ + file có mặt**

Run:
```bash
test -f .claude/commands/walkthrough-init.md && \
python3 -c 'import sys,io; t=open(".claude/commands/walkthrough-init.md").read(); assert t.startswith("---"); fm=t.split("---",2)[1]; assert "description:" in fm; print("ok")'
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/walkthrough-init.md
git commit -m "feat(commands): /walkthrough-init — generate per-seam walkthrough docs"
```

---

### Task 4: Lệnh `/walkthrough-sync`

**Files:**
- Create: `.claude/commands/walkthrough-sync.md`

**Interfaces:**
- Consumes: `.claude/walkthrough-stale.log` (Task 1 ghi), `docs/walkthrough/*` (Task 3 sinh).
- Produces: slash command `/walkthrough-sync` cập nhật seam bị ảnh hưởng rồi truncate log.

- [ ] **Step 1: Tạo file lệnh**

Tạo `.claude/commands/walkthrough-sync.md`:

```markdown
---
description: Cập nhật các file walkthrough lỗi thời dựa trên code đã đổi (đọc .claude/walkthrough-stale.log), chỉ đụng seam bị ảnh hưởng rồi xoá log.
---

Bạn đang đồng bộ tài liệu walkthrough với code đã thay đổi. Trả lời bằng tiếng Việt.

## Bước 1 — Đọc stale log
Đọc `.claude/walkthrough-stale.log`. Nếu KHÔNG tồn tại hoặc RỖNG → báo "Không có gì để sync" và DỪNG.

## Bước 2 — Map file → seam
Với mỗi đường dẫn code trong log, xác định seam bị ảnh hưởng dựa trên `docs/walkthrough/README.md` (index) và vị trí file. Một file có thể thuộc >1 seam.
Nếu một file không khớp seam nào: liệt kê ra, HỎI người dùng muốn tạo seam mới hay bỏ qua.

## Bước 3 — Cập nhật CÓ MỤC TIÊU
Chỉ đọc + sửa những file `docs/walkthrough/<seam>.md` bị ảnh hưởng. KHÔNG viết lại toàn bộ tài liệu.
- Đọc lại code đã đổi để cập nhật mô tả + line number cho đúng.
- Giữ nguyên các phần không liên quan.

## Bước 4 — Xoá log
Sau khi cập nhật xong, làm rỗng stale log bằng: `: > .claude/walkthrough-stale.log`
Báo cáo danh sách file walkthrough đã cập nhật.
```

- [ ] **Step 2: Xác nhận frontmatter hợp lệ + file có mặt**

Run:
```bash
test -f .claude/commands/walkthrough-sync.md && \
python3 -c 't=open(".claude/commands/walkthrough-sync.md").read(); assert t.startswith("---"); assert "description:" in t.split("---",2)[1]; print("ok")'
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/walkthrough-sync.md
git commit -m "feat(commands): /walkthrough-sync — targeted update of stale walkthrough seams"
```

---

### Task 5: Skill `learn-codebase` (teach + explain-diff)

**Files:**
- Create: `.claude/skills/learn-codebase/SKILL.md`

**Interfaces:**
- Consumes: `docs/walkthrough/*` (Task 3) làm nguồn cho mode teach.
- Produces: skill `learn-codebase` hai mode, kích hoạt bằng `/learn` hoặc ngôn ngữ tự nhiên.

- [ ] **Step 1: Tạo file skill**

Tạo `.claude/skills/learn-codebase/SKILL.md`:

```markdown
---
name: learn-codebase
description: Use when the user wants to understand this codebase deeply — learn how a module or flow works, be quizzed on it, or have a git diff explained before merging. Triggers on "/learn", "dạy tôi", "giải thích module", "quiz tôi", "giải thích diff", "explain this diff before I merge".
---

# Learn Codebase

Mục tiêu: biến mỗi lần dùng Claude thành một buổi học. Luôn trả lời bằng tiếng Việt. KHÔNG tự sửa code trong skill này — chỉ giảng, hỏi, đối chiếu.

Chọn mode theo yêu cầu người dùng:
- Muốn học/hiểu một phần, hoặc gõ `/learn` → **mode teach**.
- Muốn review/hiểu thay đổi trước khi merge ("giải thích diff", "trước khi merge") → **mode explain-diff**.
- Nếu không rõ, hỏi đúng một câu: "Bạn muốn học một module (teach) hay giải thích diff hiện tại (explain-diff)?"

## Mode: teach

1. Xác định seam/module mục tiêu. Nếu người dùng chưa nói rõ, hỏi.
2. Nguồn tài liệu:
   - Nếu `docs/walkthrough/<seam>.md` tồn tại → đọc nó làm nguồn chính.
   - Nếu không → đọc code trực tiếp, và gợi ý người dùng chạy `/walkthrough-init` để có tài liệu bền vững.
3. Giải thích luồng theo TỪNG BƯỚC. MỖI bước BẮT BUỘC kèm markdown link `file:line` để click được. Đọc code thật để lấy số dòng đúng — không bịa.
4. Sau khi giảng, QUIZ người dùng 3–5 câu (hỏi TỪNG câu một, chờ trả lời rồi mới hỏi tiếp). Câu hỏi kiểm tra hiểu bản chất ("vì sao", "điều gì xảy ra nếu bỏ bước này"), không hỏi vặt.
5. Chấm từng câu trả lời: đúng/sai ở đâu, vì sao, chỉ về đúng `file:line`.

## Mode: explain-diff

1. Lấy diff: chạy `git diff` (gồm cả staged + unstaged) hoặc diff người dùng chỉ định.
2. TRƯỚC KHI giải thích, YÊU CẦU người dùng tự tóm tắt 1 câu: "thay đổi này làm gì và đụng tới ai?". CHỜ họ trả lời.
3. Sau khi người dùng trả lời:
   - Giải thích đầy đủ diff, kèm `file:line`.
   - Đối chiếu với câu tóm tắt của người dùng: chỉ ra chỗ đúng, chỗ thiếu, tác động/rủi ro bị bỏ sót (ví dụ đụng invariant, đụng caller khác, đổi schema).
4. Kết luận rõ ràng: người dùng đã đủ hiểu để merge chưa. Nếu chưa, nêu chính xác còn thiếu gì. Nguyên tắc: không merge cái gì chưa tự giải thích được.
```

- [ ] **Step 2: Xác nhận cấu trúc skill hợp lệ**

Run:
```bash
test -f .claude/skills/learn-codebase/SKILL.md && \
python3 -c 't=open(".claude/skills/learn-codebase/SKILL.md").read(); fm=t.split("---",2)[1]; assert "name: learn-codebase" in fm; assert "description:" in fm; print("ok")'
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/learn-codebase/SKILL.md
git commit -m "feat(skills): learn-codebase — teach+quiz and explain-diff modes"
```

---

### Task 6: Smoke test end-to-end

**Files:** (không tạo file mới — kiểm thử tích hợp)

**Interfaces:**
- Consumes: tất cả artifact từ Task 1–5.

- [ ] **Step 1: Mô phỏng hook post ghi log**

Run:
```bash
printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":"'"$PWD"'/src/noble_agent/agent/facade.py"}}' | CLAUDE_PROJECT_DIR="$PWD" bash .claude/hooks/walkthrough-stale.sh post && cat .claude/walkthrough-stale.log
```
Expected: in ra đường dẫn `.../src/noble_agent/agent/facade.py`.

- [ ] **Step 2: Mô phỏng hook stop nhắc**

Run: `CLAUDE_PROJECT_DIR="$PWD" bash .claude/hooks/walkthrough-stale.sh stop 2>&1`
Expected: `⚠ 1 file code đã đổi từ lần sync walkthrough gần nhất — chạy /walkthrough-sync`

- [ ] **Step 3: Dọn log tạm (đảm bảo không lọt vào git)**

Run: `rm -f .claude/walkthrough-stale.log && git status --porcelain .claude/walkthrough-stale.log`
Expected: không có output (file đã bị gitignore, không xuất hiện trong status).

- [ ] **Step 4: Xác nhận không có file rác bị track**

Run: `git status --porcelain`
Expected: chỉ còn WIP có sẵn trước đó của người dùng; KHÔNG có `.claude/walkthrough-stale.log`. (Không commit gì ở task này.)

---

## Self-Review

**1. Spec coverage:**
- Component A (skill 2 mode) → Task 5. ✓
- Component B (`/walkthrough-init`) → Task 3. ✓
- Component C (hook post + stop) → Task 1 (script+test) + Task 2 (wire). ✓
- Component D (`/walkthrough-sync`) → Task 4. ✓
- Data/state (gitignore stale log) → Task 2. ✓
- Testing/verification (bash test hook, smoke) → Task 1 + Task 6. ✓
- Error handling (hook exit 0, sync no-op, init overwrite prompt, teach degrade) → mã hoá trong nội dung script/command/skill của Task 1/3/4/5. ✓

**2. Placeholder scan:** Không có TBD/TODO; mọi step có nội dung file hoặc lệnh cụ thể. ✓

**3. Type/naming consistency:** tên artifact nhất quán xuyên suốt — `walkthrough-stale.sh` (arg `post`/`stop`), `.claude/walkthrough-stale.log`, `docs/walkthrough/README.md` + `<seam>.md`, skill `learn-codebase`, lệnh `/walkthrough-init` + `/walkthrough-sync`. ✓
