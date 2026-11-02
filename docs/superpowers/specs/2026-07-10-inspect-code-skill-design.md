# Thiết kế skill `inspect-code`

- **Ngày:** 2026-07-10
- **Trạng thái:** Design (chờ user duyệt trước khi lập implementation plan)
- **Branch:** `feat/refactor2`

## 1. Mục tiêu & định vị

Người dùng vibe-code hiệu quả nhưng khó **đọc hiểu & nắm sâu flow** của codebase. `inspect-code` sinh ra **animation HTML tương tác** trực quan hoá luồng code, để hiểu nhanh và sâu hơn văn bản thuần.

### Khác biệt với skill sẵn có

| Skill | Output | Vai trò |
|---|---|---|
| `learn-codebase` | Văn bản: giảng theo bước + `file:line` + quiz | Học/kiểm tra hiểu biết |
| `walkthrough-init` / `walkthrough-sync` | Markdown bền vững `docs/walkthrough/<seam>.md` | Tài liệu luồng bền vững |
| **`inspect-code`** (mới) | **File HTML animation tương tác** | **Trực quan hoá bằng hình ảnh động** |

`inspect-code` **tái dùng `docs/walkthrough/<seam>.md` nếu có** làm nguồn dữ liệu (nhanh, đã được duyệt); nếu không thì trace code trực tiếp.

## 2. Phạm vi & quyết định đã chốt

- **Output:** một file HTML **self-contained** (HTML + CSS + JS inline, KHÔNG dùng CDN), ghi vào repo, mở bằng browser local. KHÔNG publish lên claude.ai (code proprietary).
- **Giảng giải:** tiếng Việt.
- **Hai mode:**
  - `flow` (mode A): chọn 1 **entrypoint** → animate end-to-end qua các function/module từ input tới output.
  - `function` (mode B): 1 function/module → animate **control flow nội bộ + quan hệ callers/callees**.
- **Kiến trúc:** "Engine một lần, data mỗi lần" — player template tĩnh viết & review một lần; mỗi lần chạy Claude chỉ sinh JSON flow model rồi nhúng vào template.

### Ngoài phạm vi (YAGNI)

- KHÔNG tự sửa code (read-only, giống `learn-codebase`).
- KHÔNG auto-sync khi code đổi (đó là việc của `walkthrough-sync`).
- KHÔNG cần server/build step — chỉ một file HTML tĩnh mở trực tiếp.
- KHÔNG dùng thư viện ngoài / CDN — mọi thứ inline trong 1 file.

## 3. Kiến trúc

Skill tách bạch **2 phần**:

### (a) Player template tĩnh — `assets/player.html`

Một file self-contained, đã review một lần. Đọc biến JS `FLOW_MODEL` được nhúng vào và render:

- **Cột trái:** sơ đồ các node (module/function) + mũi tên edges.
- **Cột phải:** panel code snippet của node đang active, kèm `file:line`.
- **Thanh điều khiển dưới:** Play / Pause / Step ◀ ▶ / chỉnh tốc độ.
- **Ô lời giảng:** narration tiếng Việt cho step hiện tại.
- **Animation:** tô sáng node + edge theo từng `step`; một "token" dữ liệu chạy dọc mũi tên đang active.

Player phải xử lý được cả hai mode bằng cùng một schema.

### (b) Flow model (JSON) — Claude sinh mỗi lần chạy

Schema:

```jsonc
{
  "mode": "flow" | "function",
  "title": "Một lượt voice turn: audio → text → agent → TTS",
  "nodes": [
    {
      "id": "ws",
      "label": "ws_handler._handle_session",
      "file": "src/noble_agent/server/ws_handler.py",
      "line": 74,
      "role": "Nhận WebSocket, mở phiên",
      "snippet": "async def _handle_session(...): ..."
    }
  ],
  "edges": [
    { "from": "ws", "to": "session", "label": "audio frames" }
  ],
  "steps": [
    {
      "focus": "ws",
      "activateEdges": [],
      "narration": "Client kết nối, mở phiên và bơm audio 48kHz vào."
    }
  ]
}
```

- `nodes`: các module/function trong luồng (mode `flow`) hoặc các block/nhánh nội bộ + callers/callees (mode `function`).
- `edges`: quan hệ giữa node (`flow`: gọi/truyền dữ liệu; `function`: call/return/data). `label` mô tả dữ liệu đi qua.
- `steps`: kịch bản animation tuần tự. Mỗi step: `focus` (node được tô sáng), `activateEdges` (danh sách edge sáng lên), `narration` (lời giảng tiếng Việt).
- Mode `function` dùng đúng schema này, chỉ khác ngữ nghĩa của node/edge.

### Engine phân tích (cách Claude sinh model)

1. Nếu có `docs/walkthrough/<seam>.md` khớp target → đọc làm nguồn chính, map các bước `file:line` sẵn có thành `nodes`/`steps`.
2. Nếu không → trace trực tiếp từ entrypoint bằng Grep/Read; **đọc code thật để lấy `file:line` đúng**.
3. Codebase lớn: có thể dispatch vài **Explore subagent** song song lần theo từng hop, giữ context chính gọn.

## 4. Quy trình chạy skill

1. **Xác định mode + mục tiêu.** "flow X" → `flow`; "function/module Y" → `function`. Mơ hồ → hỏi đúng 1 câu.
2. **Chọn entrypoint / target.** Mode `flow`: nếu chưa rõ entrypoint, đề xuất vài entrypoint tìm được (ws_handler, text_chat, telephony, livekit...) cho user chọn. Mode `function`: định vị bằng Grep.
3. **Thu thập dữ liệu.** Ưu tiên `docs/walkthrough/`; nếu không, trace code (Grep/Read hoặc Explore subagent).
4. **Sinh `FLOW_MODEL` (JSON)** đúng schema, narration tiếng Việt.
5. **Ghép & ghi file.** Nhúng JSON vào `assets/player.html` → ghi ra `docs/inspect/<slug>-<mode>.html`.
6. **Mở & báo.** In đường dẫn file + gợi ý `xdg-open <path>`; tóm tắt ngắn luồng bằng text để user nắm nhanh.

## 5. Xác minh (chống bịa)

- Mọi `file:line` trong model phải trỏ đúng dòng có thật — skill đọc lại code để verify, KHÔNG đoán.
- Sau khi ghi HTML: mở lại file kiểm tra JSON parse được và không còn placeholder rỗng.

## 6. Cấu trúc thư mục skill

```
.claude/skills/inspect-code/
  SKILL.md                    # hướng dẫn + 2 mode + quy trình + tham chiếu schema
  assets/player.html          # player tĩnh, self-contained (review 1 lần)
  references/
    flow-model-schema.md      # đặc tả JSON schema đầy đủ
    example-model.json        # 1 ví dụ mẫu để Claude bắt chước
```

Output sinh ra khi chạy: `docs/inspect/<slug>-<mode>.html` (git-ignore tuỳ chọn — quyết định ở bước implementation).

## 7. Kích hoạt (triggers)

- Slash: `/inspect`
- Ngôn ngữ tự nhiên (VI/EN): "trực quan hoá luồng X", "vẽ animation flow này", "inspect function Y", "animate flow", "visualize this flow".

## 8. Tiêu chí thành công

- Chạy trên một entrypoint có thật (ví dụ `ws_handler._handle_session`) → sinh file HTML mở được, Play/Step chạy mượt, mỗi step có narration tiếng Việt và `file:line` click-đúng.
- Chạy trên một function có thật → animation thể hiện được cả control flow nội bộ lẫn callers/callees.
- Không có `file:line` bịa; JSON parse sạch; không placeholder rỗng.
