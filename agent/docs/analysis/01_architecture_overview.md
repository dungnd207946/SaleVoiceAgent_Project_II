# Luna Chat DeepAgent — Tổng Quan Kiến Trúc

## Project Overview

Luna là AI chatbot bất động sản hàng hiệu cho NobleX (Noble Real Estate), xây dựng trên **Deep Agents SDK** với LangGraph. Port: **8010**. Source: `src/`. Entry point: `src/agent.py`.

## Kiến Trúc 3 Agent + 7 Micro-Skills

```
Browser / API Client
    ↓
Middleware Pipeline
  GuardrailMiddleware
  → ContextTrackingMiddleware
  → FAQInjectionMiddleware
  → HistoryInjectionMiddleware
  → ConversationPersistMiddleware
    ↓
┌─────────────────────────────────────────────────────┐
│                   LUNA (Main Agent)                  │
│          Model: openai:gpt-5.4-nano-2026-03-17      │
│          Skill: luna-general                         │
│          Tool:  set_project                          │
│          Memory: /memories/preferences.md            │
└─────────┬──────────────────────┬────────────────────┘
          │                      │
   route_to_consultant    route_to_support
          │                      │
          ▼                      ▼
┌─────────────────┐    ┌─────────────────────┐
│   CONSULTANT    │    │      SUPPORT        │
│   (Subagent)    │    │     (Subagent)      │
│                 │    │                     │
│ Skills:         │    │ Skills:             │
│ - consultant-   │    │ - support-crm       │
│   info          │    │ - support-          │
│ - consultant-   │    │   escalation        │
│   pricing       │    │                     │
│ - consultant-   │    │ Tools: 13           │
│   advisor       │    │ (1 RAG + 5 transfer │
│ - consultant-   │    │  + 7 CRM)           │
│   booking       │    └─────────────────────┘
│                 │
│ Tools: 15       │
│ (3 RAG + 7 DB   │
│  + 5 booking)   │
└─────────────────┘
```

## Tổng Số Tools: 20

| Nhóm | Số lượng | Files |
|------|----------|-------|
| RAG Tools | 3 | `src/agents/tools/rag_tools.py` |
| Structured DB Tools | 7 | `src/agents/tools/structured_data_tools.py` |
| Booking Tools | 5 | `src/agents/tools/booking_tools.py` |
| Transfer/Escalation Tools | 5 | `src/agents/tools/transfer_tools.py` |
| CRM Tools | 7 | `src/agents/tools/crm_tools.py` |
| **Tổng** | **20 + 1 (set_project)** | |

## Các File Chính

| File | Vai trò |
|------|---------|
| `src/agent.py` | Entry point, lắp ráp 3 agent |
| `src/config.py` | Tất cả settings (pydantic-settings, .env) |
| `src/agents/skills/luna-general/SKILL.md` | Routing rules, greeting templates |
| `src/agents/skills/consultant-info/SKILL.md` | INQ_ intent workflows |
| `src/agents/skills/consultant-pricing/SKILL.md` | PRC_ intent workflows |
| `src/agents/skills/consultant-advisor/SKILL.md` | Advisor workflow |
| `src/agents/skills/consultant-booking/SKILL.md` | BKG_ intent workflows |
| `src/agents/skills/support-crm/SKILL.md` | AFT_ intent workflows + security |
| `src/agents/skills/support-escalation/SKILL.md` | Escalation branches |
| `src/agents/skills/shared/LANGUAGE_RULES.md` | 10 quy tắc ngôn ngữ (toàn bộ agents) |
| `src/agents/tools/booking_tools.py` | 5 booking tools (factory pattern) |
| `src/agents/tools/crm_tools.py` | 7 CRM tools |
| `src/agents/tools/transfer_tools.py` | 5 escalation tools |
| `src/agents/tools/rag_tools.py` | search_documents, match_projects, get_region_overview |
| `src/agents/tools/structured_data_tools.py` | 7 PostgreSQL tools |
| `src/prompts/rag_prompt.py` | GENERATE_SYSTEM_PROMPT, citation rules, REWRITE_PROMPT |
| `src/prompts/fallback_prompt.py` | Tất cả fallback + transfer messages |

## 5 Dự Án Noble

| Code | Tên đầy đủ | Khu vực | Phân khúc | Khoảng giá |
|------|-----------|---------|-----------|-----------|
| NCTH | Noble Crystal Tây Hồ | Tây Hồ | Siêu sang | 5.2 - 25.0 tỷ, 2-4PN |
| NCLB | Noble Crystal Long Biên | Long Biên | Cao cấp | 4.5 - 18.0 tỷ, 2-4PN |
| NPLB | Noble Palace Long Biên | Long Biên | Cao cấp | 2.8 - 15.0 tỷ, 1-4PN |
| NTTL | Noble Palace Tây Thăng Long | Tây Thăng Long | Trung-Cao cấp | 1.8 - 8.0 tỷ, 1-3PN |
| SSLC | Sunshine Legend City | Legend City | Cao cấp | 3.5 - 16.0 tỷ, 1-4PN |

## Cấu Hình Chính (`src/config.py`)

| Setting | Default | Mô tả |
|---------|---------|-------|
| `LLM_MODEL` | `openai:gpt-5.4-nano-2026-03-17` | Model chính |
| `LLM_TEMPERATURE` | `0.3` | |
| `APP_PORT` | `8010` | |
| `ROUTER_MAX_ITERS` | `2` | Max iterations cho Luna router |
| `CONSULTANT_MAX_ITERS` | `3` | Max iterations cho Consultant |
| `SUPPORT_MAX_ITERS` | `3` | Max iterations cho Support |
| `INJECT_PROJECT_FAQ` | `True` | Bật/tắt FAQ injection |
| `NOBLE_HOTLINE` | `18006298` | |
| `NOBLE_EMAIL` | `support247@noblex.vn` | |
| `NOBLE_WORKING_HOURS` | `8:00 - 21:00` | |
| `QDRANT_COSINE_THRESHOLD` | `0.5` | RAG min score |
| `LIGHTRAG_TOP_K` | `10` | |
| `SUMMARIZATION_TRIGGER_TOKENS` | `80000` | Ngưỡng kích hoạt tóm tắt history |
| `SUMMARIZATION_KEEP_RECENT` | `6` | Số messages giữ lại sau summarization |

## NobleContext Schema

```python
class NobleContext:
    user_id: str
    full_name: str
    phone: str
    sex: str                # "male" | "female"
    is_user_noble: bool     # Khách đã mua của Noble
    noble_info: dict        # Thông tin KH Noble (nếu có)
    is_saler: bool
    is_employee: bool
    project_code: list[str] # Dự án đang quan tâm (set bởi set_project)
    conversation_id: str
```

## Middleware Pipeline

**Áp dụng cho main agent (Luna):** GuardrailMiddleware → ContextTrackingMiddleware → FAQInjectionMiddleware → HistoryInjectionMiddleware → ConversationPersistMiddleware

**Áp dụng cho subagents:** HistoryInjectionMiddleware only

### GuardrailMiddleware (`src/middleware/guardrail.py`)

- Từ chối tin nhắn rỗng → `"Vui lòng gửi lại câu hỏi ạ."`
- Từ chối tin nhắn > 5000 ký tự → `"Nội dung quá dài. Vui lòng gửi ngắn gọn hơn ạ."`

### FAQInjectionMiddleware (`src/middleware/faq_injection.py`)

Khi đã biết dự án (`project_code` trong context), tải FAQ markdown từ `data/faq/{PROJECT_CODE}.md` và append vào system prompt.

**Rules được inject cùng FAQ:**
- SỐ LIỆU (giá, phí, lãi suất, ưu đãi, thanh toán, ngân hàng) → BẮT BUỘC gọi tool DB trước. FAQ có thể outdated.
- MÔ TẢ (tiện ích, thiết kế, kỹ thuật, quy trình, thang máy, PCCC, smart home...) → Trả lời từ FAQ.
- Conflict: tool DB là authoritative.

## Memory System

Luna sử dụng **MongoStore** để lưu preferences per-user tại `/memories/preferences.md`. Đây là persistent memory qua các phiên hội thoại.
