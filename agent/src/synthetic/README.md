# Synthetic SFT Data Generator

Sinh data multi-turn cho training/eval Noble Voice Agent bằng cách cho một **Customer Agent (CA)** đóng vai khách hàng gọi vào Noble Agent thật, ghi lại toàn bộ thread (system prompt + user + tool_calls + tool results + assistant text) theo đúng format `data/eval_processed/eval_sft.json`.

## Kiến trúc

```
┌──────────┐  user text   ┌─────────────────────────────┐
│  CA LLM  │ ───────────► │ NobleAgent.stream_response  │ ──► Redis state
│ (persona)│              │ (cùng entrypoint production)│     (history + tool_calls
│          │ ◄─────────── │  → LLM → tools → final text │      + tool results)
└──────────┘  final text  └─────────────────────────────┘
                                                            │
                                                            ▼
                                     state.history ──► JSONL record (eval_sft shape)
```

CA chỉ thấy `user → final_text` (không nhìn tool internals). Sau khi conversation kết thúc, runner đọc `state.history` từ Redis để có đủ tool_calls + tool results, dump ra JSONL.

## Cài đặt

```bash
# 1. Copy env template
cp src/synthetic/.env.example src/synthetic/.env

# 2. Điền key cho CA — chọn 1 trong 3 provider giống Noble Agent
#    CA_PROVIDER=openai | anthropic | gemini
#    CA_MODEL=...
#    CA_<PROVIDER>_API_KEY=...
nano src/synthetic/.env

# 3. Đảm bảo Noble Agent dependencies sẵn sàng (cùng môi trường .venv)
#    - Redis chạy ở localhost:6379
#    - Main .env có ít nhất 1 LLM key cho Noble (ANTHROPIC/OPENAI/GEMINI)
docker compose up -d redis      # nếu chưa chạy
```

CA có thể dùng provider khác hoàn toàn với Noble. Ví dụ: Noble dùng vLLM local serve fine-tune, CA dùng Claude/GPT cloud để mô phỏng khách.

## Chạy

```bash
source .venv/bin/activate
PYTHONPATH=src python -m synthetic [flags]
```

### Flag

| Flag | Default | Mô tả |
|---|---|---|
| `-n, --num-conversations` | 10 | Số conversation sinh ra |
| `-t, --max-turns` | 8 | Trần số user-turn / conversation. Số này cũng được **inject vào system prompt của CA** để CA tự pace cuộc gọi (giới thiệu vấn đề → hỏi điểm thiếu → chốt/chào) và có thể tự `[END_CALL]` sớm hơn |
| `-c, --concurrency` | 4 | Số conversation chạy song song. Tăng để bù latency LLM; giảm nếu CA/Noble provider bị rate-limit |
| `--progress-interval` | 5 | Khoảng cách (giây) giữa các dòng heartbeat `[progress]`. Đặt `0` để tắt |
| `-o, --output` | `data/synthetic_sft/{timestamp}.jsonl` | File JSONL output (append mode) |
| `--persona LABEL` | random | Pin 1 persona cụ thể (xem `personas.py` → `PERSONAS`) |
| `--seed N` | random | Seed cho persona sampling — tái lập được |
| `-v, --verbose` | off | Bật INFO log từ Noble Agent pipeline |

### Ví dụ

```bash
# Default: 10 convo × ≤8 turns, 4 song song
PYTHONPATH=src python -m synthetic

# Bulk: 100 convo, max 10 turn, 8 song song, seed cố định
PYTHONPATH=src python -m synthetic -n 100 -t 6 -c 8 --seed 42

# Debug 1 persona — chạy tuần tự để log dễ đọc
PYTHONPATH=src python -m synthetic -n 3 -c 1 --persona angry_postsale_paperwork -v

# Append vào file tích lũy thay vì tạo file mới mỗi run
PYTHONPATH=src python -m synthetic -n 20 -o data/synthetic_sft/combined.jsonl

# Tắt heartbeat (chỉ giữ log per-conversation)
PYTHONPATH=src python -m synthetic -n 50 --progress-interval 0
```

### Progress logs

Trong lúc chạy, terminal có 2 loại dòng đan xen:

```
[progress] 12/50 (24%) | running=4 ok=10 fail=2 | elapsed=1m23s eta=4m11s | rate=8.7/min
[synthetic] [13/50] persona=investor_rushed ok turns=6 msgs=14 ended_naturally=True (13/50)
[progress] 18/50 (36%) | running=4 ok=15 fail=3 | elapsed=2m05s eta=3m38s | rate=8.6/min
...
[synthetic] done — succeeded=47 failed=3 elapsed=5m42s → data/synthetic_sft/20260604-152030.jsonl
```

- `[progress]` — heartbeat định kỳ (mặc định 5s), giúp biết job vẫn còn sống ngay cả khi không có convo nào hoàn thành trong khoảng đó.
  - `running` = số worker đang xử lý (≤ concurrency)
  - `ok` / `fail` = thành công vs thất bại (skip 0-turn cũng tính fail)
  - `rate` tính trên `completed/elapsed`, dùng để dự báo `eta`.
- `[synthetic]` — log per-conversation khi 1 convo kết thúc (ok / FAIL / skip).
- Dòng `done` cuối in tổng wall-time + file output.

## Output

### Vị trí

```
data/synthetic_sft/
├── 20260604-152030.jsonl     # mỗi run mặc định tạo 1 file timestamp
├── 20260604-160521.jsonl
└── combined.jsonl            # khi truyền -o thì append vào file đó
```

Folder `data/synthetic_sft/` được tự động tạo khi chạy lần đầu.

### Format mỗi dòng

Mỗi dòng là 1 conversation JSON object — schema khớp `data/eval_processed/eval_sft.json`:

```json
{
  "conversation_id": "synth-a3f9b21c10",
  "prompt_variant": "general",
  "messages": [
    {"role": "system",    "content": "<Noble system prompt được render đúng như production>"},
    {"role": "user",      "content": "Alo cho anh hỏi..."},
    {"role": "assistant", "content": "Dạ em là Luna..."},
    {"role": "assistant", "content": "Dạ em đặt lịch...",
     "tool_calls": [{"id": "toolu_...", "type": "function",
                     "function": {"name": "booking", "arguments": "{...}"}}]},
    {"role": "tool", "tool_call_id": "toolu_...", "name": "booking", "content": "{...}"},
    {"role": "assistant", "content": "Dạ đã đặt lịch thành công..."}
  ],
  "tools": [<13 tool schemas thật của Noble Agent>],
  "persona": "terse_scheduler",
  "ended_naturally": true,
  "turns": 5
}
```

- `messages[0].content` = system prompt thật được build qua `build_system_prompt(agent_def, customer, summary)` — chính prompt mà Noble dùng inference, không hardcode.
- `tools` = tool_schemas thật của Noble (`runner._agent.tool_schemas`), khớp 1-1 với `src/noble_agent/agent/definitions/config.json`.
- `persona`, `ended_naturally`, `turns` là **metadata ngoài chuẩn eval_sft** — tiện để filter/phân tích, có thể bỏ khi feed vào trainer.

### Stop condition

Conversation dừng khi:
1. CA tự kết thúc bằng sentinel `[END_CALL]` ở cuối message (ví dụ: hài lòng, được hứa escalate, đổi ý, đã hủy lịch...). CA biết được trần `max_turns` qua system prompt nên thường tự pace để chốt trước khi chạm trần.
2. Chạm `--max-turns` (hard cap trong loop).
3. CA provider lỗi → record có `turns=0` sẽ bị **skip không ghi** (không pollute data).

## Persona

30 persona đa dạng định nghĩa trong [personas.py](personas.py) — đủ 4 trục:

- **Phase**: pre-sale (browse / pricing / financing / scheduling) vs post-sale (CRM / contract / certificate / maintenance / complaint).
- **Tone**: lịch sự / cáu gắt / rushed / chatty / cò kè / mỉa mai / chậm rãi.
- **Demographic**: Gen Z tech-savvy, vợ chồng trẻ ngân sách thấp, doanh nhân khoe, lớn tuổi, Việt kiều, miền Nam ra Bắc...
- **Edge case**: anti-chatbot skeptical, đang lái xe ngắt quãng, ngại cung cấp CCCD, hỏi giùm bố mẹ, môi giới dò info, so sánh đối thủ.

Distribution mặc định: uniform 1/30 ≈ 3.33% mỗi persona, độc lập theo từng convo. Pin 1 persona bằng `--persona <label>`.

## Cấu trúc thư mục

```
src/synthetic/
├── README.md           # file này
├── .env.example        # template config CA
├── .env                # config thật (gitignored)
├── __init__.py
├── __main__.py         # CLI entry: python -m synthetic
├── config.py           # SyntheticSettings (pydantic, prefix CA_)
├── ca_client.py        # CustomerAgentClient — gọi LLM của CA (3 provider)
├── personas.py         # PERSONAS list (30) + sample_persona / get_persona
└── runner.py           # run_conversation — orchestrate CA ↔ Noble + dump record
```

## Lưu ý vận hành

- **Không cần bật server HTTP/WebSocket** — synthetic gọi thẳng `NobleAgent` facade trong cùng Python process, bypass audio/transport.
- Mỗi convo có `session_id` riêng (`synth-<hex>`) → Redis key riêng, các convo song song không đụng state của nhau.
- Output append-mode + write-lock → các worker song song ghi an toàn vào cùng 1 file, mỗi dòng JSONL atomic. Resume sau crash OK, nhưng nếu dùng cùng `--output` qua nhiều run thì cẩn thận duplicate.
- **Concurrency tradeoff**: tăng `-c` giúp bù latency LLM (mỗi convo block chủ yếu ở `await llm.complete()`), nhưng cẩn thận:
  - Rate-limit CA provider (OpenAI/Anthropic/Gemini) → giảm `-c` hoặc dùng provider có tier cao.
  - Rate-limit Noble LLM provider (cùng `.env` chính) → cũng giới hạn tổng QPS.
  - Redis local thường không phải bottleneck ở mức `-c=16` trở xuống.
  - Mặc định `-c=4` an toàn cho gói free/tier-1.
- Để **rerun reproducible**: cần `--seed` (persona sampling) **+** CA `temperature=0` trong `.env` (mặc định 0.9 để đa dạng) **+** Noble model deterministic **+** `-c=1` (vì với `-c>1` thứ tự completion phụ thuộc network jitter) — thực tế khó đạt full deterministic do LLM cloud.
- Output file scale ~ tuyến tính theo số convo × số turn. 100 convo × 25 msg × ~500 byte ≈ 1.2MB.
