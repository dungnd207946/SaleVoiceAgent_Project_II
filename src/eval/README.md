# eval — Đánh giá agent bằng teacher forcing trên dữ liệu SFT tổng hợp

Bộ eval này chấm điểm agent Noble (Luna) trên file tham chiếu
`data/synthetic_sft/eval_sft.jsonl`: với **mỗi lượt assistant** trong hội thoại gốc,
nó phát lại đúng phần hội thoại đứng trước (prefix) rồi hỏi **chính model của agent**
(chuỗi provider cấu hình trong `.env`) "tới đây trả lời/gọi tool gì?" — **chỉ gọi LLM
một lần, KHÔNG chạy vòng lặp tool**. Sau đó so output dự đoán với câu gốc để chấm
chất lượng gọi tool và câu trả lời.

Ý tưởng và cấu trúc bám sát bộ eval của `santa-post-training` (2 pha `run` → `score`).

---

## 1. Yêu cầu trước khi chạy

1. **Cài môi trường** (Python 3.11+, đã cài repo):
   ```bash
   source .venv/bin/activate        # hoặc tạo mới: python3 -m venv .venv && pip install -e ".[dev]"
   ```

2. **Có ít nhất 1 LLM provider trong `.env`** — đây là model BỊ ĐÁNH GIÁ. Pha `run`
   dùng chuỗi provider y hệt agent thật:
   - `NOBLE_AGENT_MODEL` = provider chạy trước (primary). Ví dụ hiện tại: `claude-sonnet-4-6`.
   - Fallback: `ANTHROPIC_*` → `OPENAI_*` → `GEMINI_*`.
   Nói cách khác: bạn đánh giá đúng model mà agent dùng khi sinh synthetic data.

3. **Critic cho LLM judge** (chỉ cần khi `--response-eval llm|both`):
   - Mặc định: dùng lại provider **Anthropic** trong `.env` (`claude-sonnet-4-6` qua
     proxy Meridian — mạnh, không tốn phí token).
   - Muốn đổi: đặt `EVAL_CRITIC_MODEL` (kèm `EVAL_CRITIC_BASE_URL` / `EVAL_CRITIC_API_KEY`
     nếu cần) trong `.env`, hoặc truyền `--critic-model` ở CLI.

4. **Luôn chạy với `PYTHONPATH=src`** (package nằm trong layout `src/`):
   ```bash
   PYTHONPATH=src python -m eval ...
   ```

> Lưu ý: bộ eval phụ thuộc vào `primary_for` / `provider_model_map` (trong
> `noble_agent/config.py`) và `build_llm_providers` (trong `agent/facade.py`).
> Đảm bảo nhánh refactor unified-agent của bạn đang có các hàm này.

---

## 2. File tham chiếu là gì (`eval_sft.jsonl`)

Mỗi dòng là một hội thoại, định dạng OpenAI:

```jsonc
{
  "conversation_id": "synth-01f9c4b19e",
  "prompt_variant": "general",
  "messages": [
    {"role": "system",    "content": "Bạn là Luna — chuyên viên Noble..."},
    {"role": "user",      "content": "Chào, tôi gọi về dự án..."},
    {"role": "assistant", "content": "...", "tool_calls": [ {"function": {"name": "...", "arguments": "{...}"}} ]},
    {"role": "tool",      "tool_call_id": "...", "name": "...", "content": "{...}"},
    {"role": "assistant", "content": "Dạ em đã kiểm tra..."}
  ],
  "tools": [ /* 13 schema tool của Luna */ ],
  "persona": "...", "ended_naturally": true, "turns": 3
}
```

Bộ eval đọc `messages` (để dựng prefix + lấy câu gốc) và `tools` (để chấm schema tool
call). Nó **không** dựng lại system prompt — dùng nguyên `messages[0]` trong file để
trung thực với tham chiếu.

---

## 3. Chạy đánh giá — quy trình 2 pha

### Pha 1 — `run`: sinh prediction (teacher forcing)

```bash
PYTHONPATH=src python -m eval run \
  --slug demo \
  --eval-file data/synthetic_sft/eval_sft.jsonl
```

- Tự gắn timestamp vào slug → thư mục kết quả: `data/eval_results/<YYYYMMDD_HHMMSS>_demo/`.
- Ghi `predictions.jsonl` (mỗi dòng = 1 lượt assistant + câu model dự đoán) và `eval_manifest.json`.
- **Resume an toàn**: chạy lại cùng slug sẽ bỏ qua các lượt đã có
  (khóa `conversation_id/turn_idx/step_idx_in_turn`). Nếu đã đủ → in "nothing to do".

Các cờ của `run`:

| Cờ | Mặc định | Ý nghĩa |
|---|---|---|
| `--slug` (bắt buộc) | — | Tên định danh lần chạy (sẽ được thêm timestamp đằng trước) |
| `--eval-file` | `data/synthetic_sft/eval_sft.jsonl` | File tham chiếu JSONL |
| `--temperature` | `0.2` | Nhiệt độ khi sinh prediction (thấp = ổn định) |
| `--workers` | `8` | Số lượt chạy song song |
| `--limit` | (không) | Chỉ chạy N lượt đầu — tiện để smoke test nhanh |

> Pha `run` GỌI MODEL THẬT (tốn token / cần mạng). Muốn thử nhanh thì thêm
> `--limit 4 --workers 1`.

### Pha 2 — `score`: chấm điểm + tổng hợp

Lấy đúng **slug đầy đủ** (có timestamp) mà pha `run` đã in ra:

```bash
PYTHONPATH=src python -m eval score \
  --slug 20260604_153012_demo \
  --response-eval both
```

- Đọc `predictions.jsonl`, ghi `details.jsonl` (điểm từng lượt) + `report.json` (tổng hợp).
- `--response-eval`:
  - `rule`  → chỉ rule-based (tool-call + 6 trục câu trả lời), **không gọi LLM**, rẻ & nhanh.
  - `llm`   → tool-call rule-based + LLM judge.
  - `both`  → cả hai (mặc định).

Các cờ của `score`:

| Cờ | Mặc định | Ý nghĩa |
|---|---|---|
| `--slug` (bắt buộc) | — | Slug đầy đủ (có timestamp) của thư mục kết quả |
| `--response-eval` | `both` | `rule` \| `llm` \| `both` |
| `--critic-model` | (theo `.env`) | Ghi đè model critic cho LLM judge |
| `--tfidf-threshold` | `0.7` | Ngưỡng giống nhau của giá trị tham số tool (0–1). Dưới ngưỡng = `wrong_argument_value` |
| `--workers` | `8` | Số lượt judge song song |
| `--limit` | (không) | Chỉ chấm N dòng đầu |

---

## 4. Ví dụ chạy đầy đủ trên `eval_sft.jsonl`

```bash
cd /home/dutn/Documents/Hotline-Agent/santa-hotline-agent
source .venv/bin/activate

# (A) Smoke nhanh, KHÔNG tốn tiền judge: 4 lượt, chỉ rule-based
PYTHONPATH=src python -m eval run   --slug smoke --limit 4 --workers 1
#  → in ra ví dụ: [run] done slug=20260604_153012_smoke ok=4 ...
PYTHONPATH=src python -m eval score --slug 20260604_153012_smoke --response-eval rule

# (B) Chạy đầy đủ toàn bộ file + LLM judge
PYTHONPATH=src python -m eval run   --slug full
PYTHONPATH=src python -m eval score --slug 20260604_153530_full --response-eval both

# Xem báo cáo
cat data/eval_results/20260604_153530_full/report.json | python -m json.tool | less
```

Mẹo lấy slug mới nhất tự động:
```bash
SLUG=$(ls -t data/eval_results | head -1)
PYTHONPATH=src python -m eval score --slug "$SLUG" --response-eval both
```

---

## 5. Đọc kết quả

Thư mục `data/eval_results/<slug>/`:

| File | Nội dung |
|---|---|
| `predictions.jsonl` | Mỗi dòng: prefix + `reference_response` (gốc) + `predicted_response` (model) |
| `details.jsonl` | Mỗi dòng: điểm chi tiết 1 lượt (`fc`, `response_rule`, `response_llm`) |
| `eval_manifest.json` | Metadata lần chạy (model, primary provider, số hội thoại, temperature...) |
| `report.json` | **Tổng hợp**: `summary` toàn cục + `per_turn` theo từng lượt |

Cấu trúc `report.json`:

```jsonc
{
  "slug": "...", "eval_file": "...", "response_eval_mode": "both",
  "n_conversations": 26, "max_turns": 7, "tfidf_threshold": 0.7,
  "summary": {
    "n_total_turns": 120,
    "fc_metrics": {
      "n_turns_with_tool_calls": 70, "n_total_pairs": 95,
      "unwanted_function_call_rate": 0.04,   // gọi tool thừa
      "missing_function_call_rate": 0.10,    // bỏ sót tool cần gọi
      "incorrect_function_format_rate": 0.0, // sai schema (key lạ / enum / kiểu)
      "wrong_argument_value_rate": 0.06,     // giá trị tham số lệch
      "missing_argument_rate": 0.0,          // thiếu tham số bắt buộc
      "wrong_tool_name_rate": 0.02           // (heuristic) vừa thừa vừa thiếu trong cùng lượt
    },
    "response_rule": {
      "opening_compliance":  {"pass_rate": 0.92, "n_evaluated": 26},
      "closing_compliance":  {"pass_rate": 0.80, "n_evaluated": 26},
      "forbidden_words":     {"pass_rate": 0.98, "n_evaluated": 94},
      "conciseness_clarity": {"pass_rate": 0.88, "n_evaluated": 94},
      "politeness_markers":  {"pass_rate": 1.00, "n_evaluated": 94},
      "name_usage":          {"pass_rate": 0.85, "n_evaluated": 20},
      "aggregate": 0.90
    },
    "response_llm": {                         // chỉ khi --response-eval llm|both
      "n_evaluated": 94, "aggregate": 4.3, "factual_pass_rate": 0.97
    }
  },
  "per_turn": { "0": { ... }, "1": { ... } }  // cùng cấu trúc summary, tách theo turn_idx
}
```

### Ý nghĩa các metric

**A. Tool-call (rule-based, luôn có):** ghép cặp tool predicted ↔ gốc theo tên rồi
phân loại. Tỉ lệ càng thấp càng tốt.

**B. 6 trục câu trả lời (rule-based):** mỗi trục `pass_rate` ∈ [0,1] (None = không áp
dụng cho lượt đó, ví dụ lượt chỉ gọi tool không có chữ):
- `opening_compliance`: lượt đầu mở bằng "Dạ/Vâng" + giới thiệu Luna/tư vấn/Noble.
- `closing_compliance`: lượt cuối có "cảm ơn" + "Noble".
- `forbidden_words`: không dùng "nhé/nhá/nhỉ".
- `conciseness_clarity`: tối đa 3 câu (theo RULES.md "2–3 câu max").
- `politeness_markers`: có "dạ/vâng/vui lòng/cảm ơn/ ạ".
- `name_usage`: nếu prefix có tên khách thì câu trả lời nhắc đúng tên (khớp nguyên từ).

**C. LLM judge (tùy chọn):** chấm predicted so với gốc theo rubric (clarity,
informativeness, relevance, coherence, empathy, engagement — thang 1–5, có trọng số) →
`aggregate`; cộng `factual_pass_rate` (tỉ lệ không bịa fact / không mâu thuẫn kết quả
tool). `tool_correctness` KHÔNG chấm ở đây (đã có ở phần A).

---

## 6. Lỗi thường gặp

- **`missing predictions.jsonl — run the run phase first`**: bạn truyền sai slug cho
  `score`. Phải là slug **đầy đủ có timestamp** (xem `ls data/eval_results`).
- **`[run] FAIL ...` / all providers failed**: chưa cấu hình provider trong `.env`,
  hoặc endpoint (vLLM/Meridian) chưa bật. Pha `run` cần model thật.
- **Judge lỗi parse JSON**: critic trả về kèm chữ thừa — `parse_judge_json` đã cố bóc
  khối `{...}`; nếu vẫn lỗi, đổi `--critic-model` sang model bám JSON tốt hơn.
- **ModuleNotFoundError: noble_agent ...**: thiếu `PYTHONPATH=src`, hoặc nhánh
  refactor unified-agent (có `primary_for`/`provider_model_map`) chưa hiện diện.

---

## 7. Chạy test của bộ eval

```bash
PYTHONPATH=src python -m pytest tests/unit/eval -v
```
