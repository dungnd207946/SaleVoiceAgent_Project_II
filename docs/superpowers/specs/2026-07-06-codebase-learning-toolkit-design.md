# Codebase Learning Toolkit — Design

**Date:** 2026-07-06
**Status:** Approved (design), pending implementation plan
**Scope:** Project-local tooling committed to `santa-hotline-agent/.claude/`

## Problem

Dùng Claude Code rất hiệu quả nhưng kiến thức không "ở lại" trong đầu người dùng:
hiểu tổng quan project nhưng không hiểu sâu từng hàm/luồng. Nguyên nhân: Claude làm
phần "hiểu" thay, nên người dùng không được luyện. Cần công cụ tái sử dụng biến mỗi
lần dùng Claude thành một buổi học, gần như không tốn thêm thời gian.

## Goals

1. Một skill giúp học sâu codebase theo hai kỷ luật: (a) Claude làm giáo viên + quiz,
   (b) giải thích diff trước khi merge.
2. Một tài liệu "walkthrough" (giải thích luồng theo bước, có `file:line`) làm nguồn
   học và tài liệu onboarding.
3. Tự động phát hiện walkthrough bị lỗi thời sau khi sửa code — **không tốn token tự động**.
4. Cập nhật walkthrough theo yêu cầu, chỉ đụng phần bị ảnh hưởng.

## Non-Goals

- Không tự động viết lại walkthrough sau mỗi lần Edit (quá tốn token, chậm).
- Không cài global (`~/.claude`); chỉ project này, commit vào git.
- Không thay thế CLAUDE.md / Change Log (chúng phục vụ mục đích khác).

## Components

Bốn thành phần trong `santa-hotline-agent/.claude/`, hoạt động khép kín:

```
sửa code ──▶ [C. PostToolUse hook] ghi stale log (0 token)
                                          │
cuối lượt ─▶ [C. Stop hook] nếu log ≠ rỗng → nhắc "chạy /walkthrough-sync"
                                          │
người dùng ▶ [D. /walkthrough-sync] cập nhật seam bị ảnh hưởng, xoá log
                                          │
                             docs/walkthrough/*  ◀── nguồn cho ──┐
                                                                 │
người dùng ▶ [A. skill learn-codebase / mode teach] đọc walkthrough → giảng + quiz
người dùng ▶ [A. skill learn-codebase / mode explain-diff] giải thích git diff trước merge
[B. /walkthrough-init] sinh lần đầu docs/walkthrough/*
```

### A. Skill `learn-codebase` — `.claude/skills/learn-codebase/SKILL.md`

Một skill, hai mode. Kích hoạt bằng `/learn` hoặc ngôn ngữ tự nhiên
("dạy tôi module X", "giải thích diff này", "quiz tôi về turn loop").
Mọi phản hồi bằng tiếng Việt.

**Mode `teach`** (mặc định khi người dùng muốn học một phần):
1. Xác định seam/module mục tiêu (hỏi nếu chưa rõ).
2. Nếu `docs/walkthrough/<seam>.md` tồn tại → đọc làm nguồn chính; nếu không → đọc code trực tiếp và gợi ý chạy `/walkthrough-init`.
3. Giải thích luồng theo từng bước, **mỗi bước bắt buộc kèm `file:line`** (dạng markdown link để click được).
4. **Quiz 3–5 câu** về phần vừa giảng, hỏi từng câu một.
5. Chấm câu trả lời của người dùng, chỉ rõ chỗ hiểu sai và tại sao.

**Mode `explain-diff`** (khi người dùng chuẩn bị review/merge):
1. Đọc `git diff` (hoặc diff được chỉ định).
2. **Yêu cầu người dùng tự tóm tắt 1 câu** "thay đổi này làm gì, đụng tới ai" TRƯỚC.
3. Sau khi người dùng trả lời → Claude đối chiếu, giải thích đầy đủ kèm `file:line`, chỉ ra tác động/rủi ro mà người dùng bỏ sót.
4. Kết luận: người dùng chỉ nên merge khi tự giải thích được — nêu rõ nếu chưa đạt.

Skill KHÔNG tự sửa code. Chỉ giảng/hỏi/đối chiếu.

### B. Command `/walkthrough-init` — `.claude/commands/walkthrough-init.md`

Quét codebase (ưu tiên `CLAUDE.md` "Architecture" + `src/noble_agent/` layout) và sinh:

- `docs/walkthrough/README.md` — bản đồ tổng: liệt kê các seam chính + link tới từng file.
- Một file cho mỗi seam chính. Seam khởi tạo (theo kiến trúc hiện tại):
  - `turn-lifecycle.md` — `facade.py` → `orchestrator.py` → `runner.py`, tool loop, invariant history.
  - `audio-pipeline.md` — mic → VAD → STT → LLM → sentence buffer → TTS → speaker.
  - `storage.md` — 3 Redis key (meta/customer/state), Mongo, summary/WATCH.
  - `transports.md` — 4 transport hội tụ về `NobleAgent`.
  - (Command có thể đề xuất thêm seam nếu phát hiện, hỏi người dùng.)

Mỗi file walkthrough: sơ đồ ASCII của luồng + giải thích từng bước có `file:line`,
viết cho kỹ sư mới. Nếu `docs/walkthrough/` đã tồn tại → hỏi trước khi ghi đè.

### C. Hook đánh dấu stale — `.claude/hooks/walkthrough-stale.sh`

Một script, hai chế độ gọi (phân biệt qua tham số hoặc `hook_event_name` trên stdin JSON):

- **PostToolUse** (matcher `Edit|Write|MultiEdit`):
  - Đọc `tool_input.file_path` từ stdin JSON.
  - Chỉ ghi nếu path nằm trong `src/` (loại trừ `docs/`, `.claude/`, và `tests/` — sửa test không đổi narrative của walkthrough).
  - Append path (dedupe) vào `.claude/walkthrough-stale.log`.
  - **Không gọi LLM, exit 0 nhanh, không chặn.**
- **Stop**:
  - Nếu `.claude/walkthrough-stale.log` tồn tại và không rỗng → hiển thị một dòng nhắc:
    `⚠ N file code đã đổi từ lần sync walkthrough gần nhất — chạy /walkthrough-sync`.
    (Cơ chế hiển thị chính xác — stdout / stderr / JSON `systemMessage` của Stop hook — chốt ở bước plan.)
  - Không tự cập nhật, không tốn token.

Script phải robust không phụ thuộc `jq` (fallback sang `python3 -c` parse JSON).
`.claude/walkthrough-stale.log` được thêm vào `.gitignore` (state tạm, per-checkout).

Wiring trong `santa-hotline-agent/.claude/settings.json` (độc lập với global `~/.claude/settings.json`):
thêm `hooks.PostToolUse` (matcher `Edit|Write|MultiEdit`) và `hooks.Stop`, cùng trỏ tới script với tham số phân biệt.

### D. Command `/walkthrough-sync` — `.claude/commands/walkthrough-sync.md`

1. Đọc `.claude/walkthrough-stale.log`. Nếu rỗng/không có → báo "không có gì để sync", dừng.
2. Với mỗi file code đã đổi, map sang seam bị ảnh hưởng (dựa trên README index + đường dẫn).
3. Chỉ đọc + cập nhật những file walkthrough tương ứng (KHÔNG viết lại toàn bộ). Giữ `file:line` chính xác.
4. Nếu file đổi không khớp seam nào → gợi ý tạo seam mới hoặc bỏ qua (hỏi người dùng).
5. Xoá (truncate) `.claude/walkthrough-stale.log` sau khi cập nhật xong.

## Data / State

- `docs/walkthrough/README.md` + `docs/walkthrough/<seam>.md` — committed, tài liệu học.
- `.claude/walkthrough-stale.log` — gitignored, danh sách path code đã đổi kể từ lần sync cuối.

## Error Handling

- Hook: mọi lỗi (thiếu file, JSON hỏng, không có `jq`) → exit 0, không chặn công việc; ưu tiên "im lặng an toàn".
- `/walkthrough-sync` khi log rỗng → no-op có thông báo.
- `/walkthrough-init` khi doc đã tồn tại → hỏi trước khi ghi đè.
- Skill mode `teach` khi thiếu walkthrough → degrade sang đọc code + gợi ý init.

## Testing / Verification

- Hook: unit test bằng bash — feed JSON mẫu (Edit trong `src/`, Edit trong `docs/`, JSON hỏng), assert nội dung `walkthrough-stale.log` và exit code 0.
- Manual smoke: sửa 1 file trong `src/` → kiểm tra log có path; kết thúc lượt → thấy nhắc; chạy `/walkthrough-sync` → doc cập nhật + log rỗng.
- `/walkthrough-init` chạy thật trên repo → kiểm tra README + ≥1 seam file có `file:line` click được.

## Open Questions

Không còn (các quyết định phạm vi/cơ chế/cấu trúc/đóng gói đã chốt qua brainstorming).

## Decisions Log

- Phạm vi: chỉ project `santa-hotline-agent`, commit vào git.
- Hook: đánh dấu stale (rẻ) + nhắc ở Stop; KHÔNG auto-sync.
- Doc: index + file theo seam.
- Skill: một skill `learn-codebase` hai mode (`teach` + `explain-diff`).
