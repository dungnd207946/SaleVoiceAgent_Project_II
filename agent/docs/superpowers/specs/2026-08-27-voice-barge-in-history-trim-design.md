# Voice barge-in: cắt history về phần khách đã nghe (bước 4) — 2026-08-27

**Phạm vi:** `agent/interrupt_trim.py` (mới, thuần), `agent/facade.py::NobleAgent.note_interrupted`,
`voice/voice_agent.py::handle_utterance` + `_trim_if_interrupted`. Không đổi transport, không đổi
schema.

## Vấn đề (review 27/08 mục 2.4)

LLM stream xong — và orchestrator `save_all` toàn bộ câu trả lời — sớm hơn nhiều so với TTS
phát (synth-ahead). Khách ngắt lời giữa chừng: `VoiceAgent.spoken_text_this_turn` biết đúng
các clause đã phát, nhưng không có đường nào cắt `assistant.content` trong `state.history`
về phần đó. Lượt sau model tin rằng mình đã nói những câu khách chưa hề nghe (đã giới thiệu
căn X, đã hỏi Y…) và tiếp tục từ đó.

## Quyết định

- `interrupt_trim.trim_last_assistant(history, spoken_text)` (thuần): tìm assistant CÓ content
  sau user message cuối; thay content bằng `<phần đã nghe> (bị khách ngắt lời ở đây)` — hoặc
  `(bị khách ngắt lời trước khi kịp nói)` khi chưa phát clause nào; bỏ marker hiển thị
  `[ack]`; khách đã nghe trọn → không sửa. Trả history MỚI, giữ `tool_calls`.
- `NobleAgent.note_interrupted(spoken_text)`: load → trim → `save_all`; ghi đè cùng `seq`
  vào `conversation_messages` (fire-and-forget, best-effort). Không bao giờ raise.
- `VoiceAgent.handle_utterance`: mọi transport ngắt lời bằng `agent.interrupt()` rồi
  **cancel task** `handle_utterance` (base_session / telephony), nên hook đặt ở
  `except asyncio.CancelledError` quanh `gather(llm_producer, _pacer)` (rồi ném tiếp) VÀ ở
  đường pacer tự thoát vì cờ. Chỉ gọi khi `stream_response` đã trả về (`_llm_persisted`) —
  ngắt khi LLM còn đang stream thì lượt vốn không được persist (hành vi cũ, giữ nguyên).
  Chịu được `_llm` không có hook (test dựng bằng MagicMock).

## Hệ quả / giới hạn

- Summary nền có thể đã snapshot bản đầy đủ trước khi cắt — sẽ được ghi đè ở lần summary
  sau (K user-turn). Chấp nhận.
- Phần "đã nghe" là display-text của clause (sau `_TAG_RE`), không phải prefix ký tự chính xác
  của content LLM — cố ý: đó là thứ khách nghe.
- Chưa chạy được SMOKE voice trên máy này (không có tenant config local); cần một lần nghe
  thật: nói dài → ngắt giữa câu → hỏi "em vừa nói tới đâu" và xem transcript `conversation_messages`.

## Kiểm chứng

`tests/unit/unified/test_interrupt_trim.py` (helper thuần + facade với repo mock, 9 test) và
`tests/unit/test_voice_agent_interrupt_trim.py` (đường cancel, đường cờ, LLM chưa xong, lượt
không bị ngắt, `_llm` không có hook — 5 test).
