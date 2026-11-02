# CSKH Sales Dashboard API

**Base URL**: `https://<agent-host>:8766` (or custom prod domain)
**Auth**: `X-Noble-API-Key: <secret>` header on every request
**Feature flag**: API returns 503 unless `NOBLE_SALES_API_KEY` is set in agent `.env`.
**CORS**: All responses include `Access-Control-Allow-Origin` (configurable via `NOBLE_DASHBOARD_ORIGIN`, default `*`). Preflight `OPTIONS` returns 204.
**Rate limit** (opt-in via `SALES_API_RATE_LIMIT_ENABLED=true`, Redis token bucket, per-key × tier, per-minute): list=120, write=30, export=5, search=60 (with 2× burst). On 429, response includes `Retry-After` seconds and `X-RateLimit-*` headers.

---

## Endpoints

### POST `/api/v1/sales/handoff`

Realtime handoff from voice agent to CSKH (triggered by `escalate` tool).

**Request**:
```json
{
  "phone": "0912345678",
  "summary": "Anh Minh quan tâm NCLB 3PN, ngân sách 3 tỷ, đã xem mẫu 02/04. Hiện cần tư vấn ngân hàng.",
  "reason": "customer requested human consultant",
  "priority": "normal",
  "project_code": "NCLB",
  "session_id": "tel-f47ac10b-58cc-4372"
}
```

**Response 200**:
```json
{
  "status": "ok",
  "handoff_id": "64a1b2c3d4e5f6a7b8c9d0e1"
}
```

**Errors**:
- `400 {error: "phone and summary required"}` — missing fields
- `401 {error: "unauthorized"}` — invalid API key
- `503 {error: "sales_api_disabled"}` — feature flag off

---

### GET `/api/v1/sales/summaries?phone=0912345678&limit=10`

List call summaries for a specific phone, newest first.

**Query params**:
- `phone` (required) — customer phone in canonical `0xxxxxxxxx` format
- `limit` (optional, default 10, max 50) — number of summaries

**Response 200**:
```json
{
  "phone": "0912345678",
  "total": 3,
  "summaries": [
    {
      "_id": "64a1b2c3...",
      "session_id": "tel-f47ac10b-...",
      "started_at": "2026-04-22T10:15:00Z",
      "ended_at": "2026-04-22T10:19:24Z",
      "duration_seconds": 264,
      "summary": "Anh Minh hỏi về lịch mở bán NCLB. Luna gửi thông tin, hẹn gọi lại thứ 3.",
      "key_facts": {
        "customer_name": "Minh",
        "project_interest": "NCLB",
        "budget": "3 tỷ",
        "bedroom_count": "2",
        "purpose": "mua để ở"
      },
      "open_actions": ["gửi brochure NCLB qua Zalo", "gọi lại 9h thứ 3"],
      "agent_path": ["router", "consultant"],
      "transferred_to_sales": false,
      "sales_followed_up": false
    }
  ]
}
```

**Errors**:
- `400 {error: "phone query param required"}`
- `401 {error: "unauthorized"}`

---

### GET `/api/v1/sales/summaries/{summary_id}`

Full detail of one summary.

**Response 200**: Same shape as a single object in the list endpoint, plus
any `follow_up_notes` if CSKH has marked it handled.

**Errors**:
- `404 {error: "not_found"}`
- `401 {error: "unauthorized"}`

---

### POST `/api/v1/sales/summaries/{summary_id}/mark_followed_up`

CSKH marks a summary as handled.

**Request**:
```json
{
  "by": "agent_name_or_id",
  "notes": "Đã gọi khách xác nhận lịch xem 02/04, agreed"
}
```

**Response 200**: `{status: "ok"}`

**Errors**:
- `404 {error: "not_found"}` — summary_id invalid
- `401 {error: "unauthorized"}`

---

## Data retention

- Call summaries TTL = 90 days (via MongoDB index on `ended_at`)
- Customers collection: no TTL (persistent by phone)

## Rate limits

Not implemented in v1. If needed, add at reverse proxy (nginx `limit_req`).

## CORS

Not enabled — API is server-to-server only. If CSKH dashboard runs in
browser, add CORS headers to the server.

## Client example (Python)

```python
import httpx

API_KEY = "sk-noble-sales-..."
BASE = "https://agent.noble.vn"

async def list_customer_calls(phone: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE}/api/v1/sales/summaries",
            params={"phone": phone, "limit": 20},
            headers={"X-Noble-API-Key": API_KEY},
        )
    resp.raise_for_status()
    return resp.json()

async def mark_handled(summary_id: str, by: str, notes: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE}/api/v1/sales/summaries/{summary_id}/mark_followed_up",
            json={"by": by, "notes": notes},
            headers={"X-Noble-API-Key": API_KEY},
        )
    return resp.status_code == 200
```

## Enabling in prod

Add to agent `.env`:
```bash
NOBLE_SALES_API_KEY=sk-noble-sales-<random-32-char>
```

Restart agent. Health endpoint does not report this; verify with:
```bash
curl -H "X-Noble-API-Key: <key>" https://agent.noble.vn/api/v1/sales/summaries?phone=0912345678
# expect 200 with empty summaries list for unknown phone
```

---

# Part 7 — Bookings, Stats, Customer 360, Export, Noble Snapshot

All new endpoints live under the same `/api/v1/sales/` prefix, use the same
auth header (`X-Noble-API-Key`), and share the CORS + rate-limit middleware
documented at the top.

## Bookings

### GET `/api/v1/sales/bookings`

List flat bookings with filter + pagination.

**Query**:
- `phone` (exact match, canonical 0xxxxxxxxx)
- `project` (e.g. `NCLB`)
- `status` (`confirmed|cancelled|completed|no_show`)
- `contacted` (`true|false`; omit for both)
- `date_from`, `date_to` (`YYYY-MM-DD`)
- `sort` (default `preferred_date_dt:asc`; whitelisted fields)
- `limit` (default 50, max 200)
- `offset` (default 0)

**Response 200**:
```json
{
  "total": 123, "limit": 50, "offset": 0,
  "items": [ { /* booking_flat doc */ } ]
}
```

### GET `/api/v1/sales/bookings/{appointment_id}`
→ `200 booking_flat doc` or `404 {"error":"not_found"}`

### POST `/api/v1/sales/bookings/{appointment_id}/mark_contacted`
**Body**:
```json
{ "by": "agent@noble.vn", "notes": "confirmed by phone",
  "outcome": "confirmed" }
```
`outcome` ∈ `confirmed | no_answer | rescheduled | cancelled`.
→ `200 {"status":"ok"}` | `400 invalid outcome` | `404 not_found`.

### GET `/api/v1/sales/bookings/export.csv`

Same query params as `/bookings` + optional `max_rows` (cap at 10000).

Response is `text/csv; charset=utf-8` with UTF-8 BOM (Excel VN friendly).
Filename: `bookings_<YYYYMMDD-HHMMSS>.csv`. `X-Row-Count` header shows actual rows.

Columns: `appointment_id, created_at, preferred_date, preferred_time, customer_name, phone, project, status, notes, contacted_by_sales, contacted_at, contacted_by, contact_outcome, follow_up_notes`.

## Summaries — export

### GET `/api/v1/sales/summaries/export.csv`
Query: `phone` (optional, empty = cross-phone), `max_rows` (cap 10000).

Columns: `session_id, phone, started_at, ended_at, duration_seconds, customer_name, project_interest, budget, purpose, summary, open_actions, agent_path, sales_followed_up, followed_up_by, followed_up_at, follow_up_notes`.

## Stats

### GET `/api/v1/sales/stats/today`
```json
{
  "bookings":  { "total": 7, "by_project": {...}, "by_status": {...}, "contacted": 3 },
  "summaries": { "total_today": 42, "open_handoffs": 5, "completed_handoffs": 2 },
  "calls":     { "total_today": 58, "enriched_today": 31 }
}
```

### GET `/api/v1/sales/stats/range?from=<YYYY-MM-DD>&to=<YYYY-MM-DD>`
Max span 90 days. Returns per-day bucket for bookings + summaries.
```json
{
  "range": { "from": "2026-04-01T00:00:00+00:00", "to": "2026-04-23T00:00:00+00:00" },
  "bookings_by_day":  [ {"date":"2026-04-01","total":3}, ... ],
  "summaries_by_day": [ {"date":"2026-04-01","total":8}, ... ]
}
```

## Customer 360

### GET `/api/v1/sales/customers?phone=<phone>`
```json
{
  "phone": "0857312811",
  "profile": { /* customers doc, minus _id */ } | null,
  "noble":   { /* noble_profiles doc, PII-stripped, minus noble_user_id */ } | null,
  "stats": {
    "total_summaries": 3, "total_bookings": 2,
    "last_call_ended_at": "2026-04-22T10:19:24Z",
    "upcoming_bookings_count": 1
  }
}
```

### GET `/api/v1/sales/customers/{phone}/history?limit=20`
Newest-first history merging summaries + bookings for one phone.

### GET `/api/v1/sales/customers/search?q=<query>&field=<name|phone>&limit=20`
- `q` ≥ 2 chars.
- `field=name`: case-insensitive substring search on `name`+`full_name`.
- `field=phone`: prefix match.
- `limit` max 100.

## Noble profile snapshot

### GET `/api/v1/sales/noble/profile?phone=<phone>`
Returns cached Noble SearchUser snapshot (PII-stripped).
→ `200 { <snapshot doc> }` | `200 {"phone":"...","not_cached":true}` | `503 noble_profile_disabled` if `NOBLE_PROFILE_ENABLED=false`.

---

## Rate limit details

When `SALES_API_RATE_LIMIT_ENABLED=true`, all `/api/v1/sales/*` routes are
gated by a Redis token bucket keyed by (API key, tier). If Redis is down,
the middleware fails open so dashboards keep working.

Tier mapping:
| Tier    | Default / min | Applies to                                                    |
|---------|---------------|---------------------------------------------------------------|
| list    | 120           | `GET /bookings`, `/summaries`, `/stats/*`, `/customers`, `/noble/profile` |
| write   | 30            | `POST /handoff`, `POST /*/mark_*`                             |
| export  | 5             | `GET /*/export.csv`                                           |
| search  | 60            | `GET /customers/search`                                       |

Burst: 2× the above for short spikes. Overflow → 429 with:
```json
{"error":"rate_limited","retry_after_seconds":42,"tier":"export"}
```
plus headers: `Retry-After`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

## Noble profile enrichment (how it works)

When `NOBLE_PROFILE_ENABLED=true` and `NOBLE_PROFILE_API_URL/KEY` are set,
each incoming call (telephony) triggers a Noble `SearchUser` lookup right
after ARI StasisStart (fail-open, budget 1500 ms). The agent merges
`full_name, name, gender, email, is_noble_customer, noble_info,
noble_user_id` into the session customer and saves a raw snapshot to
`noble_profiles` (TTL 30d). Subsequent calls from the same phone hit Redis
cache (TTL 3600s; negative cache 300s). On-demand tool `noble_lookup`
(registered for `support`/`consultant` agents) lets the LLM re-fetch
mid-call when the caller provides a new number.
