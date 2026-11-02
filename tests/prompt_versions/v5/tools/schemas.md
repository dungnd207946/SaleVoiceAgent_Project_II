# tools/schemas.md — JSON schemas for `tools` API parameter

**Status:** Replacement cho `src/agent/tools/schemas.py` + 18 file `TOOL.md`.
**Format:** OpenAI function calling với `strict: true`. Anthropic format tương đương (chuyển `strict` → không cần, Anthropic auto-strict).
**Rule:** KHÔNG đưa schemas này vào system prompt. Đưa vào `tools` parameter của API call. Tool docs "khi nào dùng / khi nào không" gói gọn trong `description` field.

---

## Per-skill tool groups

Router chỉ expose 2 tool. Mỗi consultant skill expose 5-7 tool. Support expose 7 tool.
Giảm tool count mỗi request = tăng tool-calling accuracy (Anthropic benchmark: ≥80% với ≤10 tool, giảm xuống 22-52% với 30+).

### Router group (2 tools)
`["switch_agent", "update_customer"]`

### Consultant skill groups
- `consultant-info`: `["noble_search", "get_project_overview", "list_projects", "search_units", "update_customer", "switch_agent"]`
- `consultant-pricing`: `["get_project_financial", "search_units", "noble_search", "update_customer", "switch_agent"]`
- `consultant-advisor`: `["match_projects", "get_project_financial", "get_project_overview", "noble_search", "update_customer", "switch_agent"]`
- `consultant-booking`: `["check_availability", "schedule_viewing", "get_booking_state", "update_booking_info", "validate_phone", "update_customer", "switch_agent"]`

### Support group (7 tools)
`["crm_lookup", "verify_identity", "support_ticket", "get_certificate_status", "escalate", "noble_search", "update_customer", "switch_agent"]`

---

## Schemas (strict=true)

### switch_agent
```json
{
  "type": "function",
  "function": {
    "name": "switch_agent",
    "description": "Switch handling to another AI agent internally. Use when user's intent is outside current agent's scope. Do NOT use to call yourself (e.g. consultant calling switch_agent(consultant) is a self-call; skip).",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "target_agent": {
          "type": "string",
          "enum": ["router", "consultant", "support"],
          "description": "Which agent should handle the next turn."
        },
        "handoff_summary": {
          "type": "string",
          "description": "One or two Vietnamese sentences summarizing: customer name (if known), project of interest (if known), main need, any important context. Example: 'Anh Cường hỏi căn 3PN dưới 10 tỷ tại NCLB, mua để ở.'"
        },
        "suggested_skill": {
          "type": "string",
          "enum": ["info", "pricing", "advisor", "booking", "crm", "escalation", ""],
          "description": "For consultant/support: which skill fits best. Empty string if unsure."
        }
      },
      "required": ["target_agent", "handoff_summary", "suggested_skill"],
      "additionalProperties": false
    }
  }
}
```

### update_customer
```json
{
  "type": "function",
  "function": {
    "name": "update_customer",
    "description": "Persist customer info when caller provides it. Call in parallel with other tools. Only include fields actually mentioned. Do NOT call for fields you inferred — only for information the customer actually stated.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "name": {"type": "string", "description": "Customer's given name. Empty if not provided."},
        "gender": {"type": "string", "enum": ["M", "F", ""], "description": "Inferred from addressing, not asked."},
        "phone": {"type": "string", "description": "10-digit Vietnamese mobile, empty if not provided."},
        "project_interest": {
          "type": "string",
          "enum": ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC", ""],
          "description": "Project code. Required when routing to consultant."
        },
        "purpose": {"type": "string", "enum": ["to_live", "to_invest", "both", ""]},
        "budget_max_vnd": {"type": "integer", "description": "Max budget in VND, 0 if unknown."},
        "preferred_area": {"type": "string", "enum": ["long_bien", "tay_ho", "tay_thang_long", ""]},
        "bedroom_count": {"type": "integer", "description": "0 if unknown, 1-5 if stated."},
        "email": {"type": "string", "description": "Email if provided, empty otherwise."}
      },
      "required": ["name", "gender", "phone", "project_interest", "purpose", "budget_max_vnd", "preferred_area", "bedroom_count", "email"],
      "additionalProperties": false
    }
  }
}
```

### noble_search
```json
{
  "type": "function",
  "function": {
    "name": "noble_search",
    "description": "Search Noble knowledge base for specific project facts (amenities, legal, progress, floor plans). Use when: customer asks factual question a FAQ block cannot answer. Do NOT use for: customer profile updates (use update_customer), price queries (use get_project_financial), scheduling (use schedule_viewing).",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Customer's question verbatim in Vietnamese, 5-80 characters."},
        "project_filter": {
          "type": "string",
          "enum": ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC", ""],
          "description": "Project code if already known, empty otherwise."
        }
      },
      "required": ["query", "project_filter"],
      "additionalProperties": false
    }
  }
}
```

### get_project_overview
```json
{
  "type": "function",
  "function": {
    "name": "get_project_overview",
    "description": "Get structured overview of a Noble project: location, developer, unit types, phases, legal status. Use as primary source for project meta info. Do NOT use for pricing details (use get_project_financial) or available units (use search_units).",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "project_code": {"type": "string", "enum": ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC"]}
      },
      "required": ["project_code"],
      "additionalProperties": false
    }
  }
}
```

### get_project_financial
```json
{
  "type": "function",
  "function": {
    "name": "get_project_financial",
    "description": "Get financial info for a project. info_type selects the slice: 'pricing' for price range, 'payment_plans' for installments, 'loan_policies' for bank partnerships, 'promotions' for current offers, 'fees' for VAT/maintenance/deposit. Do NOT use for per-unit prices (use search_units).",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "project_code": {"type": "string", "enum": ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC"]},
        "info_type": {"type": "string", "enum": ["pricing", "payment_plans", "loan_policies", "promotions", "fees"]}
      },
      "required": ["project_code", "info_type"],
      "additionalProperties": false
    }
  }
}
```

### search_units
```json
{
  "type": "function",
  "function": {
    "name": "search_units",
    "description": "Find available units in a project matching filters. Use when customer specifies criteria (budget, area, bedrooms). Returns list of unit IDs with specs.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "project_code": {"type": "string", "enum": ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC"]},
        "unit_type": {"type": "string", "enum": ["apartment", "duplex", "villa", "shophouse", "any"]},
        "max_price_vnd": {"type": "integer", "description": "Max price in VND, 0 if no limit."},
        "min_area_m2": {"type": "integer", "description": "Min area in m², 0 if no limit."},
        "bedroom_count": {"type": "integer", "description": "0 for any."}
      },
      "required": ["project_code", "unit_type", "max_price_vnd", "min_area_m2", "bedroom_count"],
      "additionalProperties": false
    }
  }
}
```

### match_projects
```json
{
  "type": "function",
  "function": {
    "name": "match_projects",
    "description": "Rank Noble projects by fit for customer needs. Use only in consultant-advisor after collecting ≥2 entities (purpose + budget). Returns top 3 project codes with fit scores.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "budget_max_vnd": {"type": "integer"},
        "purpose": {"type": "string", "enum": ["to_live", "to_invest", "both"]},
        "preferred_area": {"type": "string", "enum": ["long_bien", "tay_ho", "tay_thang_long", ""]},
        "bedroom_count": {"type": "integer"}
      },
      "required": ["budget_max_vnd", "purpose", "preferred_area", "bedroom_count"],
      "additionalProperties": false
    }
  }
}
```

### list_projects
```json
{
  "type": "function",
  "function": {
    "name": "list_projects",
    "description": "List Noble projects filtered by region. Empty region returns all 5.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "region": {"type": "string", "enum": ["long_bien", "tay_ho", "tay_thang_long", ""]}
      },
      "required": ["region"],
      "additionalProperties": false
    }
  }
}
```

### check_availability
```json
{
  "type": "function",
  "function": {
    "name": "check_availability",
    "description": "Get available dates and time slots for viewing a project in the next 14 days.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "project_code": {"type": "string", "enum": ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC"]}
      },
      "required": ["project_code"],
      "additionalProperties": false
    }
  }
}
```

### schedule_viewing
```json
{
  "type": "function",
  "function": {
    "name": "schedule_viewing",
    "description": "Create a viewing appointment. Call ONLY after all 5 required fields collected and customer confirmed. Returns booking_id.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "customer_name": {"type": "string"},
        "phone": {"type": "string", "description": "10-digit Vietnamese mobile, regex ^(0[35789])\\d{8}$"},
        "project_code": {"type": "string", "enum": ["NCTH", "NCLB", "NPLB", "NTTL", "SSLC"]},
        "preferred_date": {"type": "string", "description": "YYYY-MM-DD, must be future."},
        "preferred_time": {"type": "string", "description": "HH:MM - HH:MM slot."},
        "confirmed": {"type": "boolean", "description": "Must be true."}
      },
      "required": ["customer_name", "phone", "project_code", "preferred_date", "preferred_time", "confirmed"],
      "additionalProperties": false
    }
  }
}
```

### get_booking_state / update_booking_info / modify_booking / list_bookings / validate_phone
(Follow same pattern: strict=true, enum for project_code, explicit required list. See `src/agent/tools/schemas.py` cho chi tiết business logic hiện tại; chỉ thêm strict mode + tightened enums.)

### crm_lookup
```json
{
  "type": "function",
  "function": {
    "name": "crm_lookup",
    "description": "Query CRM for customer contracts. action='lookup' finds by phone. action='contract' fetches one contract by code. action='payment_schedule' fetches installment schedule.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "action": {"type": "string", "enum": ["lookup", "contract", "payment_schedule"]},
        "phone": {"type": "string", "description": "Required for action=lookup, empty otherwise."},
        "contract_code": {"type": "string", "description": "Required for action=contract/payment_schedule."}
      },
      "required": ["action", "phone", "contract_code"],
      "additionalProperties": false
    }
  }
}
```

### verify_identity
```json
{
  "type": "function",
  "function": {
    "name": "verify_identity",
    "description": "Verify customer identity via CCCD. Call after crm_lookup returned customer_id. Max 2 attempts before escalation.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "customer_id": {"type": "string"},
        "cccd": {"type": "string", "description": "12-digit CCCD"}
      },
      "required": ["customer_id", "cccd"],
      "additionalProperties": false
    }
  }
}
```

### support_ticket
```json
{
  "type": "function",
  "function": {
    "name": "support_ticket",
    "description": "Create a maintenance/support ticket. Assign severity matching issue urgency (see support-crm SKILL).",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "action": {"type": "string", "enum": ["create", "update", "close"]},
        "ticket_type": {"type": "string", "enum": ["MAINTENANCE", "COMPLAINT", "INQUIRY"]},
        "severity": {"type": "string", "enum": ["urgent", "high", "normal"]},
        "description": {"type": "string"},
        "customer_id": {"type": "string"},
        "contract_code": {"type": "string"}
      },
      "required": ["action", "ticket_type", "severity", "description", "customer_id", "contract_code"],
      "additionalProperties": false
    }
  }
}
```

### get_certificate_status
```json
{
  "type": "function",
  "function": {
    "name": "get_certificate_status",
    "description": "Get ownership certificate (sổ hồng) status for a contract. Returns issuance date or pending reason.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "contract_code": {"type": "string"}
      },
      "required": ["contract_code"],
      "additionalProperties": false
    }
  }
}
```

### escalate
```json
{
  "type": "function",
  "function": {
    "name": "escalate",
    "description": "Transfer customer to a real human specialist. action='transfer' for immediate transfer during business hours. action='queue' for out-of-hours or when specialist will call back. Summary is mandatory.",
    "strict": true,
    "parameters": {
      "type": "object",
      "properties": {
        "action": {"type": "string", "enum": ["transfer", "queue"]},
        "reason": {"type": "string", "description": "One-sentence reason."},
        "department": {
          "type": "string",
          "enum": ["CVTV", "QLKD", "CSKH", "PHAP_LY", "KY_THUAT"],
          "description": "Target department code."
        },
        "priority": {"type": "string", "enum": ["urgent", "high", "normal"]},
        "summary": {"type": "string", "description": "2-3 sentences summarizing customer, problem, and expected outcome."}
      },
      "required": ["action", "reason", "department", "priority", "summary"],
      "additionalProperties": false
    }
  }
}
```

---

## Migration note

File `src/agent/tools/schemas.py` hiện export `TOOL_DEFINITIONS`. Registry v4 sẽ:
1. Load `TOOL_DEFINITIONS` từ source này (source of truth).
2. Filter theo `tool_groups[active_skill]` của config.
3. Pass vào `extra_body["tools"]` khi gọi OpenAI-compatible API.
4. KHÔNG còn inject TOOL.md string vào system prompt (xoá block 243-248 của registry.py).

Effect: consultant prompt giảm ~2900 tokens tool docs → 0 (moved to `tools` param, cached tier 1).
