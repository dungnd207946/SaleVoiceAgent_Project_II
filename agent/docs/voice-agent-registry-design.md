# Voice Agent Registry Architecture — Early Output + Agent/Tool Registry

> Nguồn: Chat-planning CSVs, GoClaw loop.go + skills/, agentskills spec, Ref/skills, PLAN-AGENTSCOPE-GOCLAW-CSV.md
> Scope: Voice channel — latency-first, single LLM instance, prompt-swap routing
> Updated: 2026-03-31 — Skill design pattern analysis from GoClaw + agentskills spec

---

## 1. Insight cốt lõi: Text + Tool Call song song = Early Output

### OpenAI API trả về cả text VÀ tool_calls trong cùng 1 response

```
LLM streaming response:
  delta.content = "Dạ em đang kiểm tra lịch trống cho dự án..."   ← TEXT (nói ngay)
  delta.tool_calls = [{ name: "check_available_slots", args: {...} }]  ← TOOL (chạy ngầm)
```

Hiện tại voice agent xử lý:
- Có text → stream qua SentenceBuffer → TTS → user nghe
- Có tool_calls → execute → inject result → LLM call tiếp

**Nhưng khi cả hai xuất hiện cùng lúc** (LLM trả text + tool_call), text đi TTS ngay trong khi tool chạy ngầm. User nghe "Dạ em đang kiểm tra..." thay vì im lặng.

### Áp dụng cho agent switching

"Chuyển agent" = 1 tool call. LLM có thể output:
```
TEXT:  "Dạ em hiểu Quý Khách muốn đặt lịch tham quan ạ, em xử lý ngay ạ."
TOOL:  switch_agent(agent_id="booking", query="đặt lịch xem Crystal Long Biên thứ 7")
```

User nghe câu text NGAY LẬP TỨC. Tool `switch_agent` chạy: swap prompt → LLM call tiếp với booking persona.

### Áp dụng cho tool call thông thường

Booking agent cần check lịch trống:
```
TEXT:  "Dạ em đang kiểm tra lịch tham quan trống cho dự án Crystal Long Biên ạ."
TOOL:  check_available_slots(project="NCLB", date="05/04/2026")
```

User nghe "đang kiểm tra" trong khi API check slots. Khi result về → LLM sinh câu tiếp: "Dạ ngày năm tháng tư có lịch trống lúc chín giờ sáng và hai giờ chiều ạ."

**Đây chính là pattern "output while continuing" của GoClaw** — nhưng tận dụng native streaming API thay vì WebSocket events.

---

## 2. GoClaw Loop Behavior — Max Iterations

### Loop cơ chế (từ `internal/agent/loop.go`)

```go
for rs.iteration < maxIter {
    rs.iteration++

    // Soft nudge tại 70% budget
    if iterPct >= 0.70 → inject "[System] You're nearing your iteration limit.
                                  Start wrapping up your response."

    // Stronger nudge tại 90% budget
    if iterPct >= 0.90 → inject "[System] Final iteration approaching.
                                  Conclude your response now."

    // LLM call → stream text + tool calls
    resp = LLM(messages)

    if tool_calls:
        execute tools → append results → continue
    else:
        break  // no tools = final response
}
```

### Khi max_iter hết mà chưa xong

GoClaw **KHÔNG route tiếp** sang agent khác. Thay vào đó:
1. **70% budget** → nudge nhẹ: "Start wrapping up"
2. **90% budget** → nudge mạnh: "Conclude now"
3. **Tool budget exceeded** → inject: "Do NOT call any more tools. Summarize results so far."
4. **Loop tự thoát** khi LLM không gọi tool nữa (trả text thuần)

Nếu LLM vẫn gọi tool ở iteration cuối → tool result được append nhưng loop exit → response cuối = tool result text (không lý tưởng nhưng an toàn).

### Áp dụng cho voice

Voice cần max_iter thấp hơn chat (latency):
- **Router**: max_iter = 1 (classify + early output text + switch_agent tool)
- **Advisor**: max_iter = 3 (search → synthesize → gợi mở)
- **Booking**: max_iter = 3 (check state → validate → confirm)
- **Transfer/Aftersale**: max_iter = 2 (xin lỗi/ghi nhận → handoff)

Soft nudge tại iteration cuối: inject "[System] Đây là iteration cuối, trả lời KH với thông tin hiện có."

---

## 3. Agent Registry Design

### 3.1. Registry Structure

```
agent_registry/
  config.json                     # Agent definitions (id, persona files, tools, max_iter)
  agents/
    router/
      SOUL.md                     # Tâm hồn, giá trị cốt lõi
      IDENTITY.md                 # Tên, vai trò, giọng điệu
      TOOLS.md                    # Hướng dẫn sử dụng tools (có ví dụ)
    advisor/
      SOUL.md
      IDENTITY.md
      SKILLS.md                   # info_inquiry + price_policy merged
      TOOLS.md
    booking/
      SOUL.md
      IDENTITY.md
      SKILLS.md                   # booking flow
      TOOLS.md
    transfer/
      SOUL.md
      IDENTITY.md
      SKILLS.md                   # after_sales + escalation
      TOOLS.md
  shared/
    RULES.md                      # Quy tắc chung (xưng hô, số bằng chữ, không viết tắt...)
    PROJECTS.md                   # Thông tin 7 DA
    MEMORY.md                     # Dynamic: customer context (inject runtime)
  tools/
    noble_search.md               # Mô tả + ví dụ sử dụng tool
    schedule_viewing.md
    transfer_to_human.md
    update_customer.md
    list_projects.md
    get_project_overview.md
    list_bookings.md
    modify_booking.md
    switch_agent.md               # MỚI: tool chuyển agent
```

### 3.2. config.json

```json
{
  "agents": {
    "router": {
      "id": "router",
      "display_name": "Luna Router",
      "files": ["SOUL.md", "IDENTITY.md", "TOOLS.md"],
      "shared_files": ["RULES.md", "PROJECTS.md"],
      "tools": ["switch_agent", "update_customer"],
      "max_iterations": 1,
      "temperature": 0.3
    },
    "advisor": {
      "id": "advisor",
      "display_name": "Luna Advisor",
      "files": ["SOUL.md", "IDENTITY.md", "SKILLS.md", "TOOLS.md"],
      "shared_files": ["RULES.md", "PROJECTS.md"],
      "tools": ["noble_search", "list_projects", "get_project_overview", "update_customer", "switch_agent"],
      "max_iterations": 3,
      "temperature": 0.7
    },
    "booking": {
      "id": "booking",
      "display_name": "Luna Booking",
      "files": ["SOUL.md", "IDENTITY.md", "SKILLS.md", "TOOLS.md"],
      "shared_files": ["RULES.md", "PROJECTS.md"],
      "tools": ["schedule_viewing", "list_bookings", "modify_booking", "update_customer", "noble_search", "switch_agent"],
      "max_iterations": 3,
      "temperature": 0.3
    },
    "transfer": {
      "id": "transfer",
      "display_name": "Luna Transfer",
      "files": ["SOUL.md", "IDENTITY.md", "SKILLS.md", "TOOLS.md"],
      "shared_files": ["RULES.md", "PROJECTS.md"],
      "tools": ["transfer_to_human", "noble_search", "update_customer", "switch_agent"],
      "max_iterations": 2,
      "temperature": 0.5
    }
  },
  "default_agent": "router",
  "tool_docs_dir": "tools/"
}
```

### 3.3. Prompt Assembly (runtime)

```python
def build_agent_prompt(agent_id: str, session_id: str) -> str:
    """Assemble system prompt for a specific agent."""
    config = load_agent_config(agent_id)
    parts = []

    # 1. Customer context (dynamic, đầu prompt — giống GoClaw USER.md)
    customer_ctx = session_store.format_customer_context(session_id)
    if customer_ctx:
        parts.append(customer_ctx)

    # 2. Agent-specific files (SOUL → IDENTITY → SKILLS)
    for f in config["files"]:
        parts.append(load_file(f"agents/{agent_id}/{f}"))

    # 3. Shared files (RULES → PROJECTS)
    for f in config["shared_files"]:
        parts.append(load_file(f"shared/{f}"))

    # 4. Tool documentation (chỉ tools agent được phép dùng)
    for tool_name in config["tools"]:
        tool_doc = f"tools/{tool_name}.md"
        if exists(tool_doc):
            parts.append(load_file(tool_doc))

    # 5. Memory (conversation summary nếu dài)
    memory = session_store.load_memory(session_id)
    if memory:
        parts.append(memory)

    # 6. Date
    parts.append(f"\nHôm nay là {date.today().strftime('%d/%m/%Y')}.")

    # 7. Persona reminder (cuối prompt, giống GoClaw recency reinforcement)
    soul_snippet = load_file(f"agents/{agent_id}/SOUL.md")[:200]
    parts.append(f"\n[Nhắc lại] {soul_snippet}")

    return "\n\n".join(parts)
```

---

## 4. Bốn Agent — SOUL + IDENTITY từ Chat-planning

### 4.1. Router (Luna)

CSV source: Nhóm 5 (SYS_*), Clarification Layer, Tone T5

**`agents/router/SOUL.md`**
```
Bạn là tuyến đầu tiếp đón khách hàng. Giá trị cốt lõi:
- Nhẹ nhàng, thân thiện, không tạo áp lực.
- Xác định nhu cầu KH nhanh nhất có thể.
- Nếu hiểu được intent → chuyển ngay, KHÔNG giữ KH.
- Nếu chưa hiểu → clarify tối đa 2 lần, rồi chuyển chuyên viên.
- LUÔN output text khi chuyển agent để KH không nghe im lặng.

Giới hạn:
- KHÔNG tư vấn chuyên sâu về dự án, giá, pháp lý.
- KHÔNG đặt lịch, KHÔNG xử lý khiếu nại.
- Chỉ: chào hỏi, clarify, phân luồng, off-topic, farewell.
```

**`agents/router/IDENTITY.md`**
```
Tên: Luna
Vai trò: Chuyên viên tư vấn Noble Real Estate (NobleX)
Tone: T5 — Nhẹ nhàng, Sẵn sàng
Giọng: thân thiện, câu ngắn gọn, mời gọi tự nhiên
Từ nên dùng: cảm ơn, rất hân hạnh, em có thể giúp gì, có cần hỗ trợ thêm không
Từ TRÁNH: phải, cần, bắt buộc (khi không cần thiết)
```

**`agents/router/TOOLS.md`**
```
Tools có sẵn: switch_agent, update_customer

switch_agent: Chuyển xử lý sang agent chuyên biệt.
  LUÔN output text trước khi gọi switch_agent:
    → Advisor: "Dạ em sẽ tìm hiểu thông tin cho Quý Khách ạ."
    → Booking: "Dạ em sẽ hỗ trợ Quý Khách đặt lịch ạ."
    → Transfer: "Dạ em xin phép chuyển Quý Khách tới chuyên viên ạ."
  Truyền query = câu hỏi gốc của KH (nguyên văn).

update_customer: Gọi khi KH nói tên, giới tính, SĐT.
  Có thể gọi song song với switch_agent.
```

### 4.2. Advisor

CSV source: Nhóm 1 (INQ_* 8 intents), Nhóm 2 (PRC_* 7 intents), Tone T1 + T2

**`agents/advisor/SOUL.md`**
```
Bạn là chuyên gia tư vấn bất động sản. Giá trị cốt lõi:
- Nhiệt tình giới thiệu, tự tin khi nói về giá và chính sách.
- LUÔN search knowledge base TRƯỚC khi trả lời. Không bao giờ trả lời "em chưa có thông tin" mà chưa gọi noble_search.
- Tổng hợp kết quả tự nhiên bằng lời nói, KHÔNG đọc nguyên văn.
- So sánh dự án → LUÔN kết thúc bằng gợi ý phù hợp nhu cầu KH.
- Sau mỗi câu trả lời → gợi mở bước tiếp theo.

Giới hạn:
- KHÔNG cam kết lợi nhuận đầu tư.
- KHÔNG cam kết giá cụ thể nếu chưa có bảng giá chính thức.
- Pháp lý: CHỈ từ search result, KHÔNG suy luận. Phức tạp → chuyển chuyên viên.
- Giá realtime từng căn → chuyển chuyên viên.
```

**`agents/advisor/IDENTITY.md`**
```
Tên: Luna
Vai trò: Chuyên viên tư vấn dự án Noble Real Estate
Tone chuyển theo nội dung:
  T1 (Nhiệt tình) — khi giới thiệu dự án, tiện ích, vị trí:
    Giọng sáng, năng động, chủ động gợi mở.
    Từ dùng: đặc biệt, nổi bật, ấn tượng, tiện nghi, đẳng cấp
    Từ TRÁNH: bình thường, cũng được, không có gì đặc biệt
  T2 (Tự tin) — khi tư vấn giá, chính sách, pháp lý, đầu tư:
    Giọng chắc chắn, thuyết phục, dùng số liệu cụ thể.
    Từ dùng: chắc chắn, giá trị vượt trội, lợi thế, chỉ từ, tiết kiệm
    Từ TRÁNH: có lẽ, hình như, em nghĩ là, cũng tầm, đại khái
```

### 4.3. Booking

CSV source: Nhóm 3 (BKG_* 4 intents), Tone T3

**`agents/booking/SOUL.md`**
```
Bạn chuyên xử lý đặt lịch tham quan và các yêu cầu booking. Giá trị cốt lõi:
- Dẫn dắt KH từng bước, xác nhận thông tin liên tục.
- Nếu đã biết thông tin KH (tên, SĐT từ THÔNG TIN KHÁCH HÀNG) → KHÔNG hỏi lại.
- Đọc lại toàn bộ để xác nhận trước khi đặt.
- Tạo urgency nhẹ nhàng (không ép): "Dạ lịch cuối tuần thường kín nhanh ạ."

Giới hạn:
- Booking giữ chỗ / đặt cọc (cần CCCD, mã căn) → chuyển chuyên viên.
- KH yêu cầu tư vấn trực tiếp → thu thập nhu cầu chi tiết rồi chuyển.
- Validate SĐT (10 chữ số, 03/05/07/08/09). Ngày quá khứ → nhắc chọn lại.
```

**`agents/booking/IDENTITY.md`**
```
Tên: Luna
Vai trò: Chuyên viên hỗ trợ đặt lịch Noble Real Estate
Tone: T3 — Chuyên nghiệp, Dẫn dắt
  Giọng rõ ràng, có cấu trúc, dẫn dắt từng bước, xác nhận liên tục.
  Từ dùng: em xin phép, bước tiếp theo, xác nhận giúp em, em ghi nhận, em đã đặt lịch
  Từ TRÁNH: chắc là được, để xem, đợi tí
```

### 4.4. Transfer / Aftersale

CSV source: Nhóm 4 (AFT_* 5 intents), Escalation Rules (13 rules), Tone T4

**`agents/transfer/SOUL.md`**
```
Bạn xử lý khiếu nại, hỗ trợ sau mua, và chuyển chuyên viên. Giá trị cốt lõi:
- Đồng cảm + xin lỗi TRƯỚC, giải pháp/chuyển tiếp SAU.
- KHÔNG BAO GIỜ đổ lỗi, tranh cãi, hoặc né tránh.
- Thu thập đủ thông tin trước khi chuyển: nội dung vấn đề, mã căn/HĐ, tên, SĐT.
- Sự cố khẩn cấp (ngập, cháy, an ninh) → transfer NGAY, không delay.
- Đe dọa kiện/truyền thông → xin lỗi, KHÔNG tranh luận, transfer NGAY.
- Search knowledge base trước khi transfer (FAQ có thể có câu trả lời).

Giới hạn:
- KHÔNG truy cập CRM/HĐ. Cần xác thực → chuyển chuyên viên.
- KHÔNG hứa thời gian cụ thể nếu không có data.
- Ngoài giờ làm việc → ghi nhận + hẹn gọi lại giờ hành chính.
```

**`agents/transfer/IDENTITY.md`**
```
Tên: Luna
Vai trò: Chuyên viên chăm sóc khách hàng Noble Real Estate
Tone: T4 — Đồng cảm, Giải quyết
  Giọng thấu hiểu, ấm áp. Xin lỗi trước, giải pháp sau.
  Từ dùng: em rất xin lỗi, em hiểu sự bất tiện, em ghi nhận, em cam kết, trong vòng, em sẽ cập nhật
  Từ TRÁNH: đó không phải lỗi của chúng em, cần bình tĩnh, em không biết
```

---

## 5. Luồng xử lý Voice — Chi tiết

### 5.1. Full Flow

```
User nói "Tôi muốn đặt lịch xem Crystal Long Biên"
  ↓
STT → text
  ↓
[Router Agent - iteration 1]
  System prompt = SOUL + IDENTITY + TOOLS (router) + RULES + PROJECTS + MEMORY
  Tools available: switch_agent, update_customer
  ↓
  LLM trả về:
    TEXT: "Dạ em sẽ hỗ trợ Quý Khách đặt lịch tham quan ạ."    ← TTS NGAY
    TOOL: switch_agent(agent_id="booking",
            query="đặt lịch xem Crystal Long Biên")              ← chạy ngầm
  ↓
[switch_agent executes]
  1. Lưu agent_id="booking" vào session state
  2. Rebuild system prompt = SOUL + IDENTITY + SKILLS (booking) + TOOLS + RULES + PROJECTS + MEMORY
  3. Inject query vào messages: {"role": "user", "content": "đặt lịch xem Crystal Long Biên"}
  4. Tool returns: "Đã chuyển sang booking agent."
  ↓
[Booking Agent - iteration 1]
  System prompt = booking persona
  Tools available: schedule_viewing, list_bookings, modify_booking, update_customer, noble_search, switch_agent
  History: có customer context (tên, SĐT nếu đã biết)
  ↓
  LLM đọc THÔNG TIN KHÁCH HÀNG → thấy đã có tên "Hùng", SĐT "0912345678"
  LLM trả về:
    TEXT: "Dạ em đặt lịch cho anh Hùng xem Crystal Long Biên ạ. Anh muốn đi vào ngày nào ạ?"
    (không gọi tool → iteration end, chờ user)
  ↓
User: "Thứ 7 tuần này, 9 giờ sáng"
  ↓
[Booking Agent - iteration 1 (turn mới)]
  LLM trả về:
    TEXT: "Dạ em xác nhận: anh Hùng, số không chín một hai ba bốn năm sáu bảy tám,
           xem dự án Crystal Long Biên lúc chín giờ sáng thứ Bảy ngày năm tháng tư.
           Thông tin đúng chưa ạ?"
    (không gọi tool → chờ confirm)
  ↓
User: "Được rồi"
  ↓
[Booking Agent - iteration 1]
  LLM trả về:
    TEXT: "Dạ em đang đặt lịch cho anh ạ."                        ← TTS NGAY
    TOOL: schedule_viewing(name="Hùng", phone="0912345678",        ← chạy ngầm
           project="Noble Crystal Long Biên",
           preferred_date="05/04/2026", preferred_time="09:00",
           confirmed=true)
  ↓
[Tool result về]
  ↓
[Booking Agent - iteration 2]
  LLM đọc tool result → trả về:
    TEXT: "Dạ em đã đặt lịch thành công ạ. Mã lịch hẹn A P T năm bốn ba hai một.
           Bộ phận tư vấn sẽ liên hệ anh trước một ngày ạ.
           Anh còn cần em hỗ trợ thêm gì không ạ?"
    (không tool → end)
```

### 5.2. Max Iterations theo CSV scenarios

| Agent | max_iter | Lý do | Khi hết iter |
|-------|----------|-------|-------------|
| Router | 1 | Chỉ classify + switch. 1 LLM call duy nhất. | Trả text trực tiếp (self-respond Luna) |
| Advisor | 3 | Iter 1: search. Iter 2: search thêm nếu cần. Iter 3: tổng hợp + gợi mở. | Nudge 90%: "Trả lời KH với thông tin hiện có" |
| Booking | 3 | Iter 1: check state. Iter 2: validate. Iter 3: save booking. | Nudge 90%: "Xác nhận với KH và lưu" |
| Transfer | 2 | Iter 1: search FAQ (nếu cần). Iter 2: ghi nhận + transfer. | Nudge 90%: "Chuyển chuyên viên ngay" |

### 5.3. switch_agent — không phải agent mới, là prompt swap

```
Voice "chuyển agent" KHÔNG tạo process mới. Flow:
1. session.current_agent = "booking"
2. Rebuild system_prompt = build_agent_prompt("booking", session_id)
3. self._history[0] = {"role": "system", "content": new_prompt}
4. Append user query vào history
5. Tiếp tục LLM streaming loop bình thường

Conversation history GIỮ NGUYÊN — booking agent thấy toàn bộ context trước đó.
Customer info GIỮ NGUYÊN — shared MEMORY.md inject vào mọi agent.
Chỉ có system prompt (persona + skills + tools) thay đổi.
```

---

## 6. Tool Documentation Files

### 6.1. Ví dụ `tools/noble_search.md`

```markdown
# noble_search

Tìm kiếm thông tin từ knowledge base Noble Real Estate.

## Khi nào dùng
- KH hỏi BẤT KỲ thông tin cụ thể về dự án: tiện ích, giá, diện tích, thiết kế, vật liệu,
  pháp lý, tiến độ, so sánh, thanh toán, vay, thuế phí, bảo hành, v.v.
- LUÔN gọi TRƯỚC khi nói "em chưa có thông tin".

## Cách dùng
- query: GIỮA NGUYÊN câu hỏi gốc KH. KHÔNG thêm tên dự án, KHÔNG paraphrase.
- project_filter: mã DA đã chốt (NCLB, NPLB, NCTH...). Để trống nếu chưa chốt.

## Ví dụ
KH hỏi: "vỉa hè có đỗ xe không?"
→ noble_search(query="vỉa hè có đỗ xe không?", project_filter="NPLB")
KHÔNG: noble_search(query="vỉa hè đỗ xe dự án Noble Palace Long Biên")

## Sau khi nhận kết quả
- Tổng hợp tự nhiên bằng lời nói, KHÔNG đọc nguyên văn.
- Không tìm thấy → đề xuất chuyển chuyên viên.
```

### 6.2. Ví dụ `tools/switch_agent.md`

```markdown
# switch_agent

Chuyển xử lý sang agent chuyên biệt khác.

## Khi nào dùng
Chỉ Router agent gọi tool này. Specialists có thể gọi để chuyển lại router
hoặc sang specialist khác khi topic thay đổi.

## QUAN TRỌNG: Early Output
LUÔN output text trước/cùng lúc gọi switch_agent:
- → Advisor: "Dạ em sẽ tìm hiểu thông tin cho Quý Khách ạ."
- → Booking: "Dạ em sẽ hỗ trợ Quý Khách đặt lịch ạ."
- → Transfer: "Dạ em xin phép chuyển Quý Khách tới bộ phận hỗ trợ ạ."

## Cách dùng
- agent_id: "advisor" | "booking" | "transfer" | "router"
- query: câu hỏi gốc KH (nguyên văn)

## Ví dụ
KH: "Cho tôi đặt lịch xem Crystal Long Biên"
→ Text: "Dạ em sẽ hỗ trợ Quý Khách đặt lịch ạ."
→ switch_agent(agent_id="booking", query="đặt lịch xem Crystal Long Biên")
```

---

## 7. Skill Design — Pattern Analysis từ GoClaw + agentskills

### 7.1. Ba nguồn reference và pattern chung

| Nguồn | Pattern | Scripts? | Frontmatter? | Progressive disclosure? |
|--------|---------|----------|-------------|----------------------|
| **GoClaw** (`skills/`) | SKILL.md + `scripts/` folder | Python scripts (fill_pdf, unpack.py, validate.py) | YAML (`name`, `description`, `license`) | Không — inject full SKILL.md luôn (hoặc `skill_search` nếu >40 tools) |
| **agentskills** (Anthropic spec) | SKILL.md + `scripts/` + `references/` + `assets/` | Có, với `--help` interface | YAML (`name`, `description`, `license`, `allowed-tools`, `metadata`) | Có 3 bước: Discovery → Activation → Execution |
| **Ref/skills** (Claude Skills) | SKILL.md + subfolders (language-specific docs, templates, fonts) | Có (webapp-testing scripts, etc.) | YAML (`name`, `description`, `license`) | Có — load SKILL.md khi match, đọc thêm file khi cần |

### 7.2. Cấu trúc chuẩn của 1 Skill (tổng hợp)

```
skill-name/
├── SKILL.md              # BẮT BUỘC: frontmatter + instructions
├── scripts/              # TÙY CHỌN: executable code agent có thể chạy
│   ├── check_slots.py    #   Script có --help interface
│   └── validate_phone.py
├── references/           # TÙY CHỌN: docs bổ sung (agent đọc khi cần)
│   └── detailed-flow.md
└── assets/               # TÙY CHỌN: templates, configs
    └── greeting-templates.json
```

### 7.3. SKILL.md Frontmatter — Chuẩn agentskills

```yaml
---
name: noble-advisor           # kebab-case, unique
description: >
  Tư vấn thông tin dự án và giá cả Noble Real Estate.
  Kích hoạt khi KH hỏi về dự án, tiện ích, giá, chính sách,
  pháp lý, tiến độ, chủ đầu tư, so sánh, hoặc đầu tư.
allowed-tools: noble_search, list_projects, get_project_overview, update_customer
metadata:
  tone: "T1,T2"
  intents: "INQ_*,PRC_*"
  max_iterations: "3"
---

# Tư vấn thông tin dự án & giá cả

[Markdown body — instructions cho LLM]
```

**Ý nghĩa mỗi field:**
- `name`: ID duy nhất, dùng trong config.json để map skill → agent
- `description`: LLM đọc field này để biết KHI NÀO skill được dùng. Phải đủ cụ thể để phân biệt giữa advisor vs booking vs transfer.
- `allowed-tools`: Danh sách tools skill này cần. Agent registry đọc field này để filter tool definitions khi build prompt.
- `metadata`: Key-value tùy ý. Voice agent dùng để store tone code, intent IDs, max_iter.

### 7.4. Progressive Disclosure — 3 cấp độ

agentskills spec định nghĩa 3 cấp load:

**Cấp 1 — Discovery (luôn có trong prompt):**
Chỉ `name` + `description`, dạng XML:
```xml
<available_skills>
<skill>
<name>noble-advisor</name>
<description>Tư vấn thông tin dự án và giá cả...</description>
</skill>
<skill>
<name>noble-booking</name>
<description>Đặt lịch tham quan và booking...</description>
</skill>
</available_skills>
```
~100 tokens cho 4 skills. Agent biết có gì available nhưng chưa load chi tiết.

**Cấp 2 — Activation (khi match):**
Load full SKILL.md body vào context. Đây là lúc LLM nhận instructions chi tiết.

**Cấp 3 — Execution (khi cần thêm):**
Agent đọc `references/` hoặc chạy `scripts/` khi SKILL.md hướng dẫn.

### 7.5. Áp dụng cho Voice Agent — 2 strategy

**Strategy A: Pre-loaded (hiện tại — cho 4 skills)**
- Router luôn load full SKILL.md vào prompt (vì chỉ có 4 skills, tổng ~3K tokens).
- Không cần progressive disclosure — prompt đủ nhỏ.
- Ưu: 0 latency, LLM biết tất cả ngay.

**Strategy B: Discovery → Activation (khi scale >8 skills)**
- Router prompt chỉ có discovery XML (~100 tokens).
- `switch_agent` tool = activation: load SKILL.md vào prompt.
- Ưu: prompt router rất gọn, LLM focus classify.
- Nhược: switch_agent phải rebuild prompt (thêm ~50ms, không đáng kể).

**Đề xuất cho v1: Dùng Strategy A nhưng cấu trúc files theo agentskills spec** — sẵn sàng migrate sang Strategy B khi cần.

### 7.6. Scripts trong Skill — Khi nào cần?

GoClaw dùng scripts cho operations phức tạp (XML manipulation, PDF form filling). Cho voice BĐS NobleX:

| Skill | Scripts cần? | Nếu có, làm gì? |
|-------|-------------|-----------------|
| noble-advisor | Không | RAG search đã là tool (`noble_search`) |
| noble-booking | Có thể sau này | `scripts/validate_booking.py` — validate SĐT, conflict check, date parse |
| noble-transfer | Không | Transfer = tool call đơn giản |
| noble-router | Không | Chỉ classify + switch |

**Nguyên tắc từ agentskills best practices:**
> "Always run scripts with `--help` first. Scripts exist to be called as black-box, not ingested into context."

Nếu thêm scripts, SKILL.md chỉ cần nói:
```markdown
## Validate SĐT
Chạy: `python scripts/validate_phone.py --phone "0912345678"`
Kết quả: {"valid": true} hoặc {"valid": false, "reason": "..."}
```
Agent gọi script qua Bash tool, không cần đọc source code.

### 7.7. File Structure cập nhật (theo chuẩn)

```
agent_registry/
  config.json

  agents/
    router/
      SOUL.md                       # Giá trị cốt lõi, giới hạn hành vi
      IDENTITY.md                   # Tên, tone T5, từ dùng/tránh

    advisor/
      SOUL.md
      IDENTITY.md
      skills/
        noble-advisor/
          SKILL.md                  # Frontmatter + instructions (info + price)
          references/
            project-details.md      # Chi tiết 7 DA (nếu cần load thêm)

    booking/
      SOUL.md
      IDENTITY.md
      skills/
        noble-booking/
          SKILL.md                  # Frontmatter + booking flow instructions
          scripts/                  # (future) validate_phone.py, parse_date.py

    transfer/
      SOUL.md
      IDENTITY.md
      skills/
        noble-transfer/
          SKILL.md                  # Frontmatter + after-sales + escalation

  shared/
    RULES.md                        # Quy tắc chung (xưng hô, số bằng chữ...)
    PROJECTS.md                     # Thông tin 7 DA snapshot
    MEMORY.md                       # Dynamic template (inject runtime)

  tools/
    noble_search/
      TOOL.md                       # Mô tả + ví dụ + khi nào dùng
    schedule_viewing/
      TOOL.md
    transfer_to_human/
      TOOL.md
    update_customer/
      TOOL.md
    list_projects/
      TOOL.md
    get_project_overview/
      TOOL.md
    list_bookings/
      TOOL.md
    modify_booking/
      TOOL.md
    switch_agent/
      TOOL.md
```

### 7.8. Prompt Assembly Order (cập nhật theo GoClaw pattern)

GoClaw inject theo thứ tự: SOUL → IDENTITY → Safety → TOOLS → AGENTS → USER → MEMORY → Persona Reminder.

Áp dụng cho voice:

```
1. [THÔNG TIN KHÁCH HÀNG]   ← dynamic customer context (= GoClaw USER.md)
2. [SOUL.md]                  ← giá trị cốt lõi, giới hạn (ưu tiên cao nhất)
3. [IDENTITY.md]              ← tên, tone, từ dùng/tránh
4. [RULES.md]                 ← shared: xưng hô, số bằng chữ, không viết tắt
5. [PROJECTS.md]              ← shared: thông tin 7 DA
6. [SKILL.md]                 ← skill instructions (advisor/booking/transfer)
7. [TOOL.md × N]              ← tool docs (chỉ tools agent được phép dùng)
8. [MEMORY.md]                ← session state + topics discussed
9. [Date]                     ← "Hôm nay là DD/MM/YYYY"
10. [Persona Reminder]         ← nhắc lại 2-3 dòng từ SOUL (recency reinforcement)
```

**Recency Reinforcement** (pattern GoClaw): Ở cuối prompt, nhắc lại persona ngắn gọn (~30 tokens) để LLM không "quên" vai giữa conversation dài:
```
[Nhắc lại] Bạn là Luna — CVTV Noble. Xưng "em", bắt đầu "Dạ", kết thúc "ạ".
Tone hiện tại: T1 (nhiệt tình). LUÔN search trước khi trả lời.
```

### 7.9. So sánh: Prompt files hiện tại vs Skill-based design

| Hiện tại (prompts/) | Skill-based (agent_registry/) | Khác biệt |
|---------------------|------------------------------|-----------|
| `core/persona.txt` (5.6K chars, mọi thứ) | `SOUL.md` (~500) + `IDENTITY.md` (~300) + `RULES.md` (~600) + `PROJECTS.md` (~800) | Tách nhỏ, per-agent SOUL/IDENTITY |
| `core/tone_guidelines.txt` | Encode vào mỗi agent IDENTITY.md | Tone per-agent thay vì global |
| `core/clarification.txt` | Router SKILL.md (chỉ router cần) | Không inject vào advisor/booking |
| `core/escalation.txt` | Transfer SKILL.md (chỉ transfer cần) | Không inject vào advisor/booking |
| `skills/info_inquiry.txt` + `price_policy.txt` | `advisor/skills/noble-advisor/SKILL.md` | 1 SKILL.md thay vì 2 files |
| `skills/booking.txt` | `booking/skills/noble-booking/SKILL.md` | Thêm frontmatter + future scripts/ |
| `skills/after_sales.txt` | `transfer/skills/noble-transfer/SKILL.md` | Merge escalation vào |
| `skills/system_nav.txt` | Router SOUL.md + IDENTITY.md | Router self-respond |
| Không có tool docs | `tools/*/TOOL.md` per tool | LLM có ví dụ sử dụng rõ ràng |
| Không có progressive disclosure | Discovery XML → Activation load | Sẵn sàng scale |

---

## 8. Shared Memory

### 7.1. Cấu trúc

```
sessions/{session_id}/
  meta.json          # session metadata
  history.json       # conversation history (shared across all agent swaps)
  customer.json      # customer info (name, phone, purpose, budget, ...)
  bookings.json      # booking records
  state.json         # MỚI: current_agent, topics_discussed, clarify_count
```

### 7.2. state.json

```json
{
  "current_agent": "advisor",
  "previous_agent": "router",
  "active_project_filter": "NCLB",
  "topics_discussed": ["project_overview", "amenities"],
  "clarify_count": 0,
  "escalation_attempted": false
}
```

Mọi agent đọc/ghi cùng session. Khi switch_agent:
- `current_agent` cập nhật
- `history.json` giữ nguyên (agent mới thấy toàn bộ conversation)
- `customer.json` giữ nguyên (shared memory)

### 7.3. MEMORY.md (dynamic, inject runtime)

```
═══ THÔNG TIN KHÁCH HÀNG ═══
Tên: Hùng
Giới tính: nam
Xưng hô: anh Hùng
SĐT: 0912345678
Dự án quan tâm: NCLB
Mục đích: ở
Ngân sách: 5 tỷ

═══ SESSION STATE ═══
Dự án đang tư vấn: Noble Crystal Long Biên (NCLB)
Chủ đề đã trao đổi: tổng quan dự án, tiện ích
```

---

## 9. So sánh: Monolithic Prompt vs Agent Registry

| Tiêu chí | Monolithic (hiện tại) | Agent Registry (đề xuất) |
|-----------|----------------------|------------------------|
| Prompt size per turn | ~5.7K tokens (tất cả) | ~2-3K tokens (chỉ agent active) |
| Latency khi switch topic | 0 (cùng prompt) | +1 tool call (switch_agent) nhưng có early output text |
| Focus LLM | Đọc 30 intents, chọn 1 | Đọc 4-7 intents (chỉ skills của agent) |
| Tool confusion | 8 tools luôn có | 3-6 tools tùy agent (ít hơn = ít lỗi) |
| Thêm agent mới | Sửa monolith | Thêm folder + config entry |
| Tone consistency | LLM tự nhớ (có thể quên) | IDENTITY.md enforce per-agent |
| Shared state | Native | Native (cùng session files) |
| Early output | Không có design | Built-in (text + tool song song) |

---

## 10. CSV → 4 Agents: Mapping đầy đủ

| Agent | CSV Intents | Tools | Tone | max_iter |
|-------|------------|-------|------|----------|
| **Router** | SYS_GREETING, SYS_UNCLEAR_NEED, SYS_OUT_OF_SCOPE, SYS_NO_RESPONSE, SYS_REQUEST_HUMAN, SYS_END_CHAT + Clarification Layer | switch_agent, update_customer | T5 | 1 |
| **Advisor** | INQ_PROJECT_OVERVIEW, INQ_LOCATION, INQ_AMENITIES, INQ_LEGAL, INQ_PROGRESS, INQ_DEVELOPER, INQ_COMPARE, INQ_PRODUCT_TYPE, PRC_PRICE_LIST, PRC_PAYMENT, PRC_PROMOTION, PRC_LOAN, PRC_INVESTMENT, PRC_TOTAL_COST, PRC_COMPARE_PRICE | noble_search, list_projects, get_project_overview, update_customer, switch_agent | T1+T2 | 3 |
| **Booking** | BKG_VISIT, BKG_BOOKING (→transfer), BKG_DEPOSIT (→transfer), BKG_CONSULT_REQUEST (→transfer) | schedule_viewing, list_bookings, modify_booking, update_customer, noble_search, switch_agent | T3 | 3 |
| **Transfer** | AFT_DELIVERY, AFT_COMPLAINT, AFT_MAINTENANCE, AFT_PROCEDURE, AFT_CONTRACT_INFO + 13 Escalation Rules | transfer_to_human, noble_search, update_customer, switch_agent | T4 | 2 |

**Tổng: 30 intents + 13 escalation rules + clarification layer = đầy đủ theo CSV.**

---

## 11. Kết luận

| Quyết định | Lý do |
|------------|-------|
| **4 agents (prompt-swap, không phải process riêng)** | Voice cần shared history + 0 serialization overhead |
| **switch_agent là tool call** | LLM output text + tool cùng lúc → early output cho user |
| **Agent Registry config.json** | Dễ thêm/sửa agent, tool mapping rõ ràng |
| **SOUL + IDENTITY + SKILLS per agent** | Mỗi agent có persona riêng, tone riêng, skill riêng → LLM focus hơn |
| **Tool docs là .md files** | Inject vào prompt → LLM biết cách dùng + có ví dụ |
| **Shared session (history + customer + state)** | 1 user = 1 memory xuyên suốt, agent nào cũng thấy |
| **Router max_iter=1** | Classify nhanh, output text ngay, switch ngay |
| **Soft nudge 70%/90% giống GoClaw** | Agent tự kết thúc gracefully thay vì bị cắt |
