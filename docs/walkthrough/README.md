# Walkthrough — Noble Voice Agent (Luna)

Tài liệu học sâu + onboarding cho codebase `src/noble_agent/`. Mỗi file mô tả một **seam** (luồng nghiệp vụ chính) bằng sơ đồ ASCII + giải thích từng bước, mỗi bước kèm link `file:line` trỏ tới code thật.

**Điểm hội tụ:** mọi transport đều gọi vào `NobleAgent.stream_response` (facade) → `TurnRunner.handle_turn` → `run_turn` (LLM + tool loop). Đọc **turn-lifecycle** trước, rồi tỏa ra các seam khác.

## Bản đồ seam

| Seam | Mô tả | File |
|---|---|---|
| Turn lifecycle | Một lượt hội thoại end-to-end: facade → orchestrator → runner (LLM + tool loop), prompt builder, summary async, semcache, invariant history. | [turn-lifecycle.md](turn-lifecycle.md) |
| Audio pipeline | Full-duplex: mic → resample 48→16 → Silero VAD → STT → (Smart Turn) → LLM → sentence buffer → TTS → resample 24→48 → speaker. Kèm STT input gate + speaker floor/verify. | [audio-pipeline.md](audio-pipeline.md) |
| Storage | Redis 3-key per session (meta/customer/state), MongoDB (history/bookings/metrics/projects), summary update dùng WATCH; các model dữ liệu + lớp persist/dual-write. | [storage.md](storage.md) |
| Transports | 4 lối vào — Browser WebRTC, Text chat (`/chat`), Telephony (Asterisk/AudioSocket), LiveKit RTC — cùng hội tụ về NobleAgent; phân nhánh khởi động theo `TRANSPORT_BACKEND`. | [transports.md](transports.md) |
| Tools & DB | Dispatcher + 10 tool offered của Luna; luồng kết nối tool → MongoDB (project_du_an ↔ project_can_ho, alias mã, sentinel escalate); cách thêm tool mới. | [tools-and-db.md](tools-and-db.md) |

## Cách dùng

- Đọc theo thứ tự gợi ý: **turn-lifecycle → transports → tools-and-db → audio-pipeline → storage**.
- Dùng `/learn` để được dạy + quiz từng seam, hoặc `/learn explain-diff` để giải thích một git diff trước khi merge.
- Khi code đổi, `/walkthrough-sync` sẽ cập nhật các seam bị ảnh hưởng (đọc `.claude/walkthrough-stale.log`).

## Nguồn tham chiếu

- Kiến trúc tổng: `CLAUDE.md` phần "Architecture — Unified Single Agent".
- Design spec: `docs/superpowers/specs/2026-06-03-noble-agent-unified-design.md`.
- Smoke checklist: `src/noble_agent/SMOKE.md`.

> Line number trong các file walkthrough được lấy trực tiếp từ code tại thời điểm sinh (branch `feat/refactor2`). Nếu file nguồn dịch chuyển, chạy `/walkthrough-sync` để hiệu chỉnh.
