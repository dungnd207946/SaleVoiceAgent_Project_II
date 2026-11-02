# e2e_scenarios — kịch bản test hành vi agent (nhanh, deterministic, không judge)

Bộ test hội thoại chạy qua **đúng não agent production** (LLM + tools + RAG + Redis,
qua `NobleAgent.stream_response`) rồi **assert hành vi cứng** — không dùng LLM judge,
không audio. Mục đích: chạy 1 lệnh trước mỗi lần commit/deploy để bắt regression.

Khác với hai hệ có sẵn:
- `tests/bench_estate/` — chấm *chất lượng* trả lời bằng LLM judge (mờ, tốn tiền). Giữ nguyên.
- `src/synthetic/` — sinh data hội thoại, không pass/fail.

## Chạy

```bash
docker compose up -d redis            # Redis là bắt buộc (đã có trong .env của môi trường này)
make e2e                              # chạy tất cả scenario
python -m tests.e2e_scenarios --scenario coldcall_nclb -v   # 1 scenario, in reply + tool calls
python -m tests.e2e_scenarios --model gemini-2.5-flash      # pin model cho cả run
```

Điều kiện chạy giống hệt khi chạy agent thật: ≥1 LLM key, Redis, và RAG backend
hoạt động (`.env`). Exit code ≠ 0 nếu có scenario fail → cắm CI được ngay.

Test thuần của chính harness (loader + assertions, **không cần LLM**) chạy cùng suite unit:

```bash
pytest tests/e2e_scenarios/tests/ -q
```

## Viết một scenario

Tạo `scenarios/<tên>.yaml`:

```yaml
name: coldcall_nclb
description: mô tả ngắn
customer: { name: "Anh Minh" }        # optional: seed customer trước turn 1
turns:
  - user: "câu khách nói"
    expect:
      tool_called: kb_search
      reply_contains_any: ["Long Biên", "Noble Crystal"]
      customer_field: { field: project_interest, equals: NCLB }
  - user: "câu tiếp theo"
    expect:
      reply_not_matches: '\d+\s*(tỷ|triệu)'
```

### Bảng assertion (`expect`)

| key | ý nghĩa | dạng value |
|---|---|---|
| `tool_called` | tool được gọi trong turn | str \| list (tất cả phải có) |
| `reply_contains` | substring bắt buộc (mọi phần tử) | str \| list |
| `reply_contains_any` | ít nhất 1 phần tử | list |
| `reply_not_contains` | substring cấm | str \| list |
| `reply_matches` | regex phải khớp | regex |
| `reply_not_matches` | regex cấm khớp (vd chặn phun giá) | regex |
| `customer_field` | state sau turn | `{field, equals}` / `{field, contains}` (hoặc list) |
| `escalated` | escalate có/không | bool |

Key lạ trong `expect` → **lỗi ngay lúc load** (fail fast). So khớp substring
(`reply_contains*`) không phân biệt hoa/thường.

`tool_not_called` và `tool_arg` đã **XOÁ 2026-08-25** — không scenario nào dùng, và
harness `evals/` (schema case v2) vốn đã cấm chúng, thay bằng `golden.banned_tools`
và `golden.tools[].args`. Cần chặn một tool hoặc kiểm tham số thì viết case bên
`evals/quality/data/cases/`, đừng thêm lại key ở đây.

## Lưu ý về độ ổn định (đọc trước khi trách harness)

Agent là LLM → câu chữ đổi mỗi lần. Vì vậy hãy assert vào **hành vi** (`tool_called`,
`customer_field`, `escalated`) và **pattern cấm** (`reply_not_matches`), chỉ dùng
`reply_contains*` cho token ổn định (tên dự án…). Đặt `temperature=0` + model cố
định trong `.env` (hoặc `--model`) để bớt dao động.

Scenario mẫu (`coldcall_nclb`, `postsale_escalate`) mã hoá **hành vi kỳ vọng theo
thiết kế**. FAIL nghĩa là: (a) agent regress, hoặc (b) assertion quá chặt cần chỉnh —
đọc dòng `✗` để biết cái nào.
