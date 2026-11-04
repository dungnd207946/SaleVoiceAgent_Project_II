# Plan — Noble Profile API Integration + CSKH Dashboard

**Ngày lập**: 2026-04-23
**Scope**: `santa-hotline-agent`
**Branch dự kiến**: `feat/noble-profile-and-dashboard` (cắt từ `develop` sau khi `feat/summarization-context` merge)
**Ước lượng**: 6–8 ngày công, ship 3 phase.

---

## 0. TL;DR

| Mục | Quyết định |
|---|---|
| Noble SearchUser API | Tích hợp ở **2 điểm**: pre-seed tại StasisStart (fail-open, timeout 800ms) + tool `noble_lookup` on-demand |
| Profile storage | Snapshot raw → collection mới `noble_profiles` (TTL 30d); các field hữu ích merge vào `customers` đã có |
| Cache | Redis `noble:profile:{phone}` TTL 3600s + negative-cache `noble:profile:notfound:{phone}` TTL 300s |
| Rate limit | `asyncio.Semaphore(8)` + tenacity retry 2 lần (≤800ms per attempt); hard budget 1500ms tổng |
| Dashboard | **Backend-first** — agent chỉ expose REST API; UI do user thiết kế riêng sau. Cùng domain (`/api/v1/sales/...` + `/dashboard` nếu muốn serve static). |
| Mongo mới | +`noble_profiles` (TTL 30d), +`call_events` (TTL 30d); bổ sung TTL 180d cho `bookings_flat` |
| Auth dashboard | Dùng lại `X-Noble-API-Key` (đã có). Tương thích 100% với Sales API hiện tại. |
| Rate limit | **Mới: Sales API có rate limit per-key** (token bucket) + Noble lookup có semaphore + per-phone throttle |
| Export CSV | **Có** — `GET /api/v1/sales/bookings/export.csv` + `/summaries/export.csv` (streaming) |
| Prometheus | **KHÔNG làm** (theo yêu cầu). Dùng log + Mongo `call_events` cho observability tạm. |
| Backward-compat | **Zero-break guarantee** — feature flag off mặc định; chỉ thêm field vào model (default empty); chỉ add index (không drop); migration idempotent. Dev branch `feat/summarization-context` merge vẫn OK. |

---

## 1. Phân tích hiện trạng (audit)

### 1.1 Customer data pipeline

- **Schema**: `src/noble_agent/storage/session_store.py:151-164` — 12 field; merge **truthy-only** (`:167-173`, `:202-226`).
- **Redis (hot)**: `session:{sid}:customer` TTL 24h (`config.py:194`).
- **Mongo `customers`** (cross-session, no TTL): key=`phone`, unique index (`connection.py:91`). Seed ở `telephony/session.py:98-116`; upsert ở `:345-354`.
- **Không có audit** cho mutation trong cùng 1 call — Redis in-place overwrite.

### 1.2 Summary + booking

- `call_summaries` (TTL 90d) — `storage/call_summaries.py`. Đã có Sales API 4 endpoints (`server/http.py:50-129`, `docs/api/sales-api.md`).
- `bookings_flat` — **không TTL** (`connection.py:108-116`), đã có đủ DAO: `upsert_booking`, `mark_contacted`, `query_bookings`, `stats_today` (`storage/bookings_flat.py`).
- **Booking chưa expose lên HTTP**. DAO `query_bookings` + `mark_contacted` + `stats_today` sẵn sàng, nhưng thiếu routes.

### 1.3 External call blueprint

- `services/hotline_outreach_service.py` — pattern chuẩn: `httpx.AsyncClient(timeout=3.0)` per-call, structured dataclass `OutreachResult` với `ok` + `code` + `fallback_narration`, không raise. Có retry 3-tier (retry count + per-session cap + per-minute bucket); cache không áp dụng (mỗi call là action độc lập).
- `storage/resilience.py:31-77` — có `with_mongo_retry_and_dlq` (tenacity 3 attempts, exponential backoff, DLQ Redis). **Chỉ dùng cho Mongo**; có thể tham khảo cho HTTP nhưng **không reuse trực tiếp** vì DLQ không có ý nghĩa cho read-only lookup.

### 1.4 HTTP server

- `server/http.py:132-292` — websockets-based HTTP handler, serves static + REST. Không dùng FastAPI.
- Static dir: `static/livekit.html` (chỉ có 1 file). Route `/` và `/index.html` → `livekit.html` (`:281-282`). Phần `else` lấy thẳng path tương đối (`:284`) → đủ để serve thêm `dashboard.html`, `dashboard.css`, `dashboard.js`.
- **CORS chưa enable** (`docs/api/sales-api.md:127-130`). Cần thêm cho dashboard web.

### 1.5 Config

- `config.py:60-467` — Pydantic `Settings`, env-file `.env` (`:464`). Các settings external service đã có pattern 3 field: `_url`, `_api_key`, `_enabled` (xem chat handoff `:437-439`, sales `:431`).

### 1.6 Rủi ro phát hiện

| # | Vấn đề | Vị trí | Mức |
|---|---|---|---|
| R1 | DLQ Mongo không auto-drain | `resilience.py:80-100` | Medium |
| R2 | Race `_caller_map` fallback "most recent" | `telephony/session.py:463-473` | Low |
| R3 | `bookings_flat` không TTL → drift so với `bookings` (30d) | `connection.py:108-116` | Medium |
| R4 | Không có audit intra-call | `session_store.py:167-173` | Low |
| R5 | Không rate-limit cho external call | — | Cần fix cho Noble |
| R6 | Sales API chưa expose booking/stats | `server/http.py` | Must-fix cho dashboard |

---

## 2. Yêu cầu & scope

### In-scope
1. Tích hợp Noble `SearchUser` API vào luồng phone-intake để auto-enrich customer.
2. Store profile snapshot → dashboard & agent đều truy cập được.
3. Dashboard CSKH (MVP) xem: `summaries by phone`, `bookings list + mark_contacted`, `stats today`, `customer detail`.
4. Tổ chức lại Mongo collections: thêm 2 collection, bổ sung TTL + index.
5. Test đầy đủ (unit + integration mock httpx).

### Out-of-scope (giai đoạn này)
- Prometheus/Grafana observability
- SPA React/Next frontend
- DLQ auto-drain script (R1)
- Race fallback fix (R2) — log-only monitoring tạm
- Cross-project analytics dashboard
- Role-based access (chỉ dùng 1 API key chung cho CSKH)

---

## 3. Phần I — Noble Profile API Integration

### 3.1 Settings (`src/noble_agent/config.py`)

Thêm vào **sau line 431** (sát `noble_sales_api_key`):

```python
# Part 7: Noble Profile lookup (dev-noble-gw SearchUser)
# Enriches customer at call start with data from Noble user DB.
# When disabled or URL empty, the splice is a no-op (fail-open).
noble_profile_enabled: bool = False
noble_profile_api_url: str = ""      # e.g. https://dev-noble-gw.unicloudgroup.com.vn/noble-app-api
noble_profile_api_key: str = ""      # Api-Key header value
noble_profile_timeout_ms: int = 800  # per-attempt timeout
noble_profile_total_budget_ms: int = 1500  # abort whole op if exceeded
noble_profile_cache_ttl_s: int = 3600
noble_profile_negative_ttl_s: int = 300  # shorter TTL for "not found"
noble_profile_max_concurrency: int = 8   # asyncio.Semaphore
noble_profile_retry_attempts: int = 2    # tenacity stop_after_attempt
```

`.env.example` thêm:
```
NOBLE_PROFILE_ENABLED=false
NOBLE_PROFILE_API_URL=https://dev-noble-gw.unicloudgroup.com.vn/noble-app-api
NOBLE_PROFILE_API_KEY=
```

### 3.2 Service module — `src/noble_agent/services/noble_profile_service.py` (MỚI)

Cấu trúc (theo style `hotline_outreach_service.py`):

```
noble_profile_service.py
├── _SEM = asyncio.Semaphore(settings.noble_profile_max_concurrency)  # module-level, lazy-init
├── _CLIENT: httpx.AsyncClient singleton (connection pool reuse)
├── close() — shutdown hook
├── async fetch_profile(phone) -> NobleProfile | None
│     ├── validate phone (chỉ chấp nhận 0xxxxxxxxx)
│     ├── cache hit Redis? return
│     ├── negative-cache hit? return None
│     ├── acquire SEM
│     ├── tenacity retry (2 attempts, timeout 800ms each)
│     ├── parse response, map sang NobleProfile dataclass
│     ├── cache result (positive or negative)
│     └── return
└── async enrich_customer(phone, existing_customer) -> (customer, profile_meta)
       ├── fetch_profile(phone)
       ├── merge rule: Noble wins cho full_name/gender/email/is_noble_customer/noble_info/noble_user_id
       │               existing wins cho project_interest/purpose/budget (intent trong phiên)
       └── return merged customer + {source, fetched_at, raw_snapshot_id}
```

**NobleProfile dataclass** — subset của response API, chỉ lấy field thực dùng:
```python
@dataclass
class NobleProfile:
    user_id: str
    full_name: str
    phone: str
    email: str
    gender: str      # "M"/"F" normalized from sex field
    birthday: str
    is_noble: bool   # from isUserNoble
    rank: str
    agency_name: str
    raw: dict        # full response for audit → saved to noble_profiles collection
    fetched_at: datetime
```

**Mapping sex → gender**: `"M"|"nam"|"male"` → `"M"`; `"F"|"nữ"|"female"` → `"F"`; else `""`.

**Phone normalization**: dùng `telephony/phone_utils.normalize_phone` (đã có).

### 3.3 Splice point — `src/noble_agent/telephony/session.py:~115`

Chèn **ngay sau `save_customer(self.session_id, seed)`** ở line 114, trước `agent.start()`:

```python
# Part 7: enrich with Noble Profile API (fail-open, ≤1500ms total)
if settings.noble_profile_enabled and self.caller_number:
    try:
        from noble_agent.services import noble_profile_service
        merged, profile_meta = await asyncio.wait_for(
            noble_profile_service.enrich_customer(self.caller_number, seed),
            timeout=settings.noble_profile_total_budget_ms / 1000,
        )
        if profile_meta and profile_meta.get("source") == "noble_api":
            await session_store.save_customer(self.session_id, merged)
            logger.info("[TEL] Noble enriched: phone=%s name=%s",
                        self.caller_number, merged.get("full_name", ""))
    except asyncio.TimeoutError:
        logger.info("[TEL] Noble enrich timeout — continuing without enrichment")
    except Exception as exc:
        logger.warning("[TEL] Noble enrich failed: %s", exc)
```

**Lưu ý**: không block nếu fail. `agent.start()` vẫn chạy với data đã có từ Redis seed.

### 3.4 Profile storage

**`customers` collection** — chỉ lưu field hữu ích cho agent prompt:
```
customers.{phone}:
  name, full_name, gender, email(*new), project_interest, purpose,
  budget, preferred_area, bedroom_count, is_buyer,
  is_noble_customer, noble_info, noble_user_id(*new),
  source(*new: "noble_api"|"speech"|"seed"|"manual"),
  enriched_at(*new), updated_at, created_at
```

→ Cần update `_CUSTOMER_DEFAULTS` trong `session_store.py:151-164` thêm `email`, `noble_user_id`.

**`noble_profiles` collection** (MỚI) — raw snapshot cho audit + refresh:
```
noble_profiles.{phone}:
  phone, noble_user_id, raw: { full Noble API response },
  fetched_at, http_status
```
Index: `{phone: 1}` unique; TTL 30d trên `fetched_at` (auto-refresh).

### 3.5 Cache

**Positive cache** `noble:profile:{phone}` TTL 3600s — serialize `NobleProfile` JSON.
**Negative cache** `noble:profile:notfound:{phone}` TTL 300s — tránh spam API khi phone lạ gọi liên tục.

**Invalidation**: không cần manual. Tool `update_customer` với `phone` mới → không động tới cache (cache key là số cũ).

### 3.6 Rate limit + error handling

- **Semaphore**: `asyncio.Semaphore(settings.noble_profile_max_concurrency)` ở module level.
- **Tenacity**: `stop_after_attempt(2)` + `wait_exponential(multiplier=0.1, max=0.3)` + `retry_if_exception_type((httpx.TimeoutException, httpx.TransportError))` — **không retry** 4xx (đã biết lỗi).
- **Error codes** (trả về cho caller qua log):
  - `ok`, `not_found`, `rate_limited` (429 → fallback empty, không retry aggressive), `auth_error` (401/403 → log critical), `timeout`, `network_error`, `parse_error`
- **Tuyệt đối không raise** — caller dùng try/except wrap để safety, nhưng service nội bộ always return `None` or dataclass.

### 3.7 On-demand tool — `src/noble_agent/agent/tools/noble_lookup.py` (MỚI)

Scenario: khách đổi số / LLM cần verify mid-call. Schema:
```json
{
  "name": "noble_lookup",
  "description": "Tìm thông tin khách hàng Noble theo số điện thoại.",
  "parameters": {
    "phone": {"type": "string"}
  }
}
```

Implementation: thin wrapper quanh `noble_profile_service.fetch_profile(phone)`, trả JSON `{status, full_name?, is_noble?, rank?, fallback_narration}`.

**Đăng ký** trong `agent/tools/schemas.py` + dispatcher `agent/tools/__init__.py`. Gán cho agent `support` và `consultant` (không cho `router`).

---

## 4. Phần II — Dashboard Backend (API only)

> **Scope hẹp lại theo yêu cầu user**: phase này chỉ ship **REST API + tính năng backend**. UI do user tự thiết kế sau; plan này **không** viết HTML/CSS/JS. Server vẫn giữ sẵn route `/dashboard` cho tương lai.

### 4.1 Nguyên tắc nhất quán với Sales API hiện tại

Plan mới **bắt buộc** tuân theo convention của `server/http.py:50-129` + `docs/api/sales-api.md`:

| Convention | Áp dụng cho endpoint mới |
|---|---|
| Prefix | `/api/v1/sales/...` |
| Auth header | `X-Noble-API-Key` (case-insensitive) |
| Feature flag | `NOBLE_SALES_API_KEY` rỗng → 503 `{"error":"sales_api_disabled"}` |
| Key sai | 401 `{"error":"unauthorized"}` |
| Missing param | 400 `{"error":"..."}` |
| Not found | 404 `{"error":"not_found"}` |
| JSON serializer | `default=_json_default` (datetime → ISO, ObjectId → str) |
| Success wrapper | Flat JSON (không bọc `{"data":...}`) — giống `/summaries` hiện tại |
| Method matching | Chuỗi `method == "GET"` / `"POST"` (không enum) |

→ Tất cả handler mới đặt **trong cùng hàm `_handle_sales_api`** để reuse auth/CORS/helpers, không tạo router mới.

### 4.2 API gap analysis

| Endpoint | Status | DAO đã có |
|---|---|---|
| `GET /api/v1/sales/summaries?phone&limit` | ✅ có | — |
| `GET /api/v1/sales/summaries/{id}` | ✅ có | — |
| `POST /api/v1/sales/summaries/{id}/mark_followed_up` | ✅ có | — |
| `POST /api/v1/sales/handoff` | ✅ có | — |
| `GET /api/v1/sales/bookings?...` | ❌ mới | `bookings_flat.query_bookings` |
| `GET /api/v1/sales/bookings/{id}` | ❌ mới | `bookings_flat.get_booking` |
| `POST /api/v1/sales/bookings/{id}/mark_contacted` | ❌ mới | `bookings_flat.mark_contacted` |
| `GET /api/v1/sales/bookings/export.csv?...` | ❌ mới | `bookings_flat.query_bookings` (stream) |
| `GET /api/v1/sales/summaries/export.csv?...` | ❌ mới | `call_summaries.list_summaries` (stream) |
| `GET /api/v1/sales/stats/today` | ❌ mới | `bookings_flat.stats_today` + query `call_summaries` |
| `GET /api/v1/sales/stats/range?from=&to=` | ❌ mới | aggregate mới |
| `GET /api/v1/sales/customers?phone=` | ❌ mới | `load_customer_by_phone` + aggregate |
| `GET /api/v1/sales/customers/{phone}/history?limit=20` | ❌ mới | `list_summaries` + `list_bookings_by_phone` |
| `GET /api/v1/sales/customers/search?q=&field=name|phone&limit=` | ❌ mới | Mongo text search mới |
| `GET /api/v1/sales/noble/profile?phone=` | ❌ mới | `noble_profiles.get_by_phone` |

### 4.3 Endpoint specs (không UI, chỉ contract)

#### 4.3.1 Bookings

```
GET /api/v1/sales/bookings
Query:
  phone        string     (optional, exact match)
  project      string     (optional, uppercase 4-char code)
  status       string     (optional: confirmed|cancelled|completed|no_show)
  contacted    bool       (optional: true|false — omit = both)
  date_from    ISO date   (optional, filter preferred_date_dt >=)
  date_to      ISO date   (optional, filter preferred_date_dt <=)
  sort         string     (default: "preferred_date_dt:asc"; whitelist trong DAO)
  limit        int        (default 50, max 200)
  offset       int        (default 0)
Response 200:
  {
    "total": 123,
    "limit": 50, "offset": 0,
    "items": [ <booking_flat doc>, ... ]
  }
Errors: 400 invalid sort/date; 401; 503
```

```
GET /api/v1/sales/bookings/{appointment_id}
Response 200: booking_flat doc
Errors: 404 not_found
```

```
POST /api/v1/sales/bookings/{appointment_id}/mark_contacted
Body:
  {
    "by":      string,   # required, ≤100 chars (truncated by DAO)
    "notes":   string,   # optional, ≤1000 chars
    "outcome": string    # required, ∈ {confirmed, no_answer, rescheduled, cancelled}
  }
Response 200: {"status": "ok"}
Errors: 400 invalid outcome; 404 appointment_id not found
Idempotency: chạy 2 lần → `contacted_at` update lại, `contacted_by_sales=true` không đổi.
```

#### 4.3.2 Summaries (bổ sung filter, giữ nguyên endpoint cũ)

Mở rộng endpoint đã có `GET /summaries`:
```
GET /api/v1/sales/summaries
Query (bổ sung):
  followed_up  bool     (optional) — filter sales_followed_up
  date_from / date_to   (optional) — filter ended_at
  project      string    (optional) — filter key_facts.project_interest
  limit        (giữ max 50 như cũ; bump thành 200 để đồng bộ bookings)
  offset       int       (mới)
```
→ Backward-compat: call cũ chỉ có `phone + limit` vẫn hoạt động identical.

#### 4.3.3 Export CSV (streaming)

```
GET /api/v1/sales/bookings/export.csv
Query: giống /bookings, nhưng bỏ limit/offset (stream toàn bộ kết quả)
       Thêm hard-cap server-side: max_rows=10000 để tránh OOM
Response 200:
  Content-Type: text/csv; charset=utf-8
  Content-Disposition: attachment; filename="bookings_<YYYYMMDD-HHMMSS>.csv"
  Body: header row + N data rows (streaming chunked)

Columns (order fix):
  appointment_id, created_at, preferred_date, preferred_time,
  customer_name, phone, project, status, notes,
  contacted_by_sales, contacted_at, contacted_by, contact_outcome, follow_up_notes

Encoding: UTF-8 with BOM (`\xef\xbb\xbf` prefix) để Excel VN mở OK.
CSV escaping: dùng `csv.writer` stdlib, quoting=QUOTE_MINIMAL.
```

```
GET /api/v1/sales/summaries/export.csv
Query: phone (optional), date_from, date_to, followed_up, max_rows=10000
Columns:
  session_id, phone, started_at, ended_at, duration_seconds,
  customer_name, project_interest, budget, purpose,
  summary, open_actions (| joined), agent_path (→ joined),
  sales_followed_up, followed_up_by, followed_up_at, follow_up_notes
```

**Streaming impl**: dùng websockets `Response` với body generator không khả thi (lib này trả body 1 lần). → **Implement**: load từng batch 200 rows, build CSV trong bytearray, trả khi xong + cap 10k. Nếu cần true-streaming lớn hơn, phase 2 migrate sang ASGI/uvicorn.

#### 4.3.4 Stats

```
GET /api/v1/sales/stats/today
Response 200:
  {
    "bookings": { "total": ..., "by_project": {...}, "by_status": {...}, "contacted": ... },
    "summaries": {
      "total_today": ...,          # count ended_at >= today 00:00 UTC
      "open_handoffs": ...,        # sales_followed_up: false AND transferred_to_sales: true
      "completed_handoffs": ...,   # sales_followed_up: true today
    },
    "calls": {
      "total_today": ...,          # count call_events event=session_ended today
      "enriched_today": ...,       # count event=profile_enriched result=ok today
    }
  }
```

```
GET /api/v1/sales/stats/range?from=<ISO>&to=<ISO>
Response 200:
  { "range": {...}, "bookings_by_day": [{"date":"2026-04-23","total":N,...}], ... }
Range validation: max 90 ngày, reject nếu from > to.
```

#### 4.3.5 Customer 360

```
GET /api/v1/sales/customers?phone=<phone>
Response 200:
  {
    "phone": "0857...",
    "profile": { <customers doc, _id stripped> } | null,
    "noble": { <noble_profiles.raw minus PII> } | null,
    "stats": {
      "total_summaries": N,
      "total_bookings": N,
      "last_call_ended_at": ISO | null,
      "upcoming_bookings_count": N,   # preferred_date_dt >= now, status != cancelled
    }
  }
Errors: 400 phone required; 200 với profile=null nếu phone chưa có
```

```
GET /api/v1/sales/customers/{phone}/history?limit=20
Response 200:
  {
    "phone": "...",
    "summaries": [ ... ],   # newest first, limit applied
    "bookings":  [ ... ],   # newest first
  }
```

```
GET /api/v1/sales/customers/search?q=<query>&field=<name|phone>&limit=20
field=name:  Mongo $text index trên customers.{name, full_name}  (cần tạo index)
field=phone: prefix match 0857... (regex ^{q})
Response 200:
  { "q": "...", "field": "...", "total": N, "items": [ <profile>, ... ] }
Guard: q độ dài ≥2 ký tự; limit ≤100.
```

#### 4.3.6 Noble profile snapshot (audit)

```
GET /api/v1/sales/noble/profile?phone=<phone>
Response 200: noble_profiles doc (raw PII-stripped) | { "not_cached": true } nếu chưa có
Errors: 400 phone required; 503 nếu noble_profile_enabled=false
```

### 4.4 CORS

Thêm helper `_sales_response(data, status=200)` gộp CORS + JSON vào 1 chỗ:

```python
def _sales_response(data: dict | bytes, status: int = 200,
                    content_type: str = "application/json") -> Response:
    origin = settings.noble_dashboard_origin or "*"
    base = [
        ("Access-Control-Allow-Origin", origin),
        ("Access-Control-Allow-Credentials", "true"),
        ("Access-Control-Allow-Headers", "X-Noble-API-Key, Content-Type"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Vary", "Origin"),
    ]
    if isinstance(data, dict):
        body = json.dumps(data, ensure_ascii=False, default=_json_default).encode("utf-8")
        base.append(("Content-Type", "application/json"))
    else:
        body = data
        base.append(("Content-Type", content_type))
    base.append(("Content-Length", str(len(body))))
    return Response(status, "OK" if status < 400 else "Error", Headers(base), body)
```

Preflight:
```python
if method == "OPTIONS":
    return _sales_response({}, status=204)
```

Default `noble_dashboard_origin` = `"*"` (user confirm cùng domain, không bắt buộc restrict).

### 4.5 Rate limit Sales API

User yêu cầu: rate limit cho Sales API. **Đặt ở API layer, dùng Redis**.

**Strategy**: token bucket per `X-Noble-API-Key + endpoint_class`, back-off 429 với header `Retry-After`.

**Module mới**: `src/noble_agent/server/rate_limit.py` (~120 LOC)

```python
class TokenBucket:
    """Redis-backed sliding-window counter with burst allowance."""
    async def check(key: str, *, rate: int, period_s: int, burst: int) -> tuple[bool, int]:
        # Returns (allowed, retry_after_seconds)
        # Uses atomic Redis script: INCR + EXPIRE + check
```

**Limits defaults** (config.py):
```python
sales_api_rate_list_per_minute: int = 120    # bookings, summaries, stats
sales_api_rate_write_per_minute: int = 30    # mark_contacted, mark_followed_up
sales_api_rate_export_per_minute: int = 5    # CSV (expensive)
sales_api_rate_search_per_minute: int = 60   # customer search
sales_api_rate_burst_multiplier: float = 2.0 # allow 2x spike
```

**Apply**:
```python
# Inside _handle_sales_api, after auth check
tier = _classify_tier(tail, method)  # "list" | "write" | "export" | "search"
allowed, retry_after = await rate_limit.check_and_consume(
    key=f"{auth_header}:{tier}",
    rate=getattr(settings, f"sales_api_rate_{tier}_per_minute"),
    period_s=60,
    burst=int(rate * settings.sales_api_rate_burst_multiplier),
)
if not allowed:
    return _sales_response(
        {"error": "rate_limited", "retry_after_seconds": retry_after},
        status=429,
    )
```

**Fallback**: nếu Redis down → rate limit bypass (fail-open), log warn. Không block vì Redis.

**Header** trả về: `X-RateLimit-Remaining`, `X-RateLimit-Reset` (UNIX ts).

### 4.6 Static serve (chỉ reserve path)

`server/http.py` bổ sung **optional** route, trả 404 graceful nếu file không tồn tại — **không implement UI**:

```python
if path in ("/dashboard", "/dashboard.html"):
    fp = STATIC_DIR / "dashboard.html"
    if not fp.exists():
        return _json_response({"error": "dashboard_ui_not_deployed"}, 404)
    # ... serve như static
```

→ Hành vi: khi user drop `dashboard.html` vào `static/` sau này, route tự serve. Không có file thì 404 rõ ràng, không 500.

---

## 5. Phần III — Mongo collection organization

### 5.1 Thay đổi index/TTL (chỉ thêm, không drop)

| Collection | Hiện có | Thêm mới |
|---|---|---|
| `customers` | `{phone:1}` unique | `{source:1, enriched_at:-1}` cho báo cáo |
| `bookings_flat` | 4 index | **TTL 180d** trên `created_at` để tránh grow vô hạn |
| `call_summaries` | 3 index | `{sales_followed_up:1, ended_at:-1}` cho dashboard "open handoff" |
| `noble_profiles` *(mới)* | — | `{phone:1}` unique, TTL 30d trên `fetched_at` |
| `call_events` *(mới)* | — | `{session_id:1, ts:-1}`, `{phone:1, ts:-1}`, TTL 30d trên `ts` |

### 5.2 `call_events` schema — light audit, không phải full log

```json
{
  "ts": ISODate,
  "session_id": "tel-abc...",
  "phone": "0857...",
  "event": "stasis_start|phone_captured|profile_enriched|escalated|booking_created|booking_modified|session_ended",
  "data": { ... payload nhỏ, không PII thừa },
  "latency_ms": 120
}
```

Ghi từ: `telephony/session.py` (stasis_start, session_ended, profile_enriched), `agent/tools/booking.py` (booking_created/modified), `agent/tools/escalate.py` (escalated).

### 5.3 Migration script — `scripts/mongo_migrate_noble_profile.py` (MỚI)

Idempotent script:
```
1. Ensure indexes: customers new indexes, noble_profiles, call_events
2. Ensure TTL: bookings_flat (180d)
3. Backfill `customers.source="legacy"` cho doc nào chưa có `source`
4. Không touch data — chỉ metadata
```

Chạy 1 lần trên prod sau khi deploy image mới. Script log: số doc modified cho mỗi index.

### 5.4 Connection manager — `storage/connection.py:65-123`

Bổ sung:
```python
# Part 7: Noble profile snapshots
try:
    await self._mongo_db.noble_profiles.create_index("phone", unique=True)
    await self._mongo_db.noble_profiles.create_index(
        "fetched_at", expireAfterSeconds=30 * 86400,
    )
except Exception as idx_exc:
    logger.warning("noble_profiles indices failed: %s", idx_exc)

# Part 7: call audit events
try:
    await self._mongo_db.call_events.create_index([("session_id", 1), ("ts", -1)])
    await self._mongo_db.call_events.create_index([("phone", 1), ("ts", -1)])
    await self._mongo_db.call_events.create_index(
        "ts", expireAfterSeconds=30 * 86400,
    )
except Exception as idx_exc:
    logger.warning("call_events indices failed: %s", idx_exc)

# Part 7: bookings_flat TTL (retention cap)
try:
    await self._mongo_db.bookings_flat.create_index(
        "created_at", expireAfterSeconds=180 * 86400, name="created_at_ttl"
    )
except Exception as idx_exc:
    logger.warning("bookings_flat TTL index failed: %s", idx_exc)

# Part 7: customers source/enriched
try:
    await self._mongo_db.customers.create_index([("source", 1), ("enriched_at", -1)])
except Exception as idx_exc:
    logger.warning("customers.source index failed: %s", idx_exc)

# Part 7: call_summaries dashboard index
try:
    await self._mongo_db.call_summaries.create_index(
        [("sales_followed_up", 1), ("ended_at", -1)]
    )
except Exception as idx_exc:
    logger.warning("call_summaries followed_up index failed: %s", idx_exc)
```

---

## 6. Phần IV — File changes checklist

### Code mới
- [ ] `src/noble_agent/services/noble_profile_service.py` — main service (~240 LOC)
- [ ] `src/noble_agent/storage/noble_profiles.py` — DAO `save_snapshot`, `get_by_phone`, `strip_pii` (~80 LOC)
- [ ] `src/noble_agent/storage/call_events.py` — DAO `log_event`, `query_events` (~60 LOC)
- [ ] `src/noble_agent/agent/tools/noble_lookup.py` — on-demand tool (~80 LOC)
- [ ] `src/noble_agent/server/rate_limit.py` — Redis token bucket + tier classifier (~140 LOC)
- [ ] `src/noble_agent/server/csv_export.py` — CSV builders cho bookings/summaries (~100 LOC)
- [ ] `src/noble_agent/server/sales_api.py` — tách `_handle_sales_api` sang file riêng (refactor, ~350 LOC) **optional** — nếu giữ nguyên `http.py` ≤400 LOC thì skip
- [ ] `scripts/mongo_migrate_noble_profile.py` (~100 LOC)

### Code sửa
- [ ] `src/noble_agent/config.py` — +9 settings Noble (~line 431); +5 settings rate-limit; +1 `noble_dashboard_origin`; +1 `bookings_flat_ttl_days=180`
- [ ] `.env.example` — +5 lines Noble + dashboard origin
- [ ] `src/noble_agent/telephony/session.py:~115` — splice enrich (+~22 LOC, trong try/except)
- [ ] `src/noble_agent/storage/connection.py` — +5 index blocks (~45 LOC)
- [ ] `src/noble_agent/storage/session_store.py:151-164` — **thêm** `email`, `noble_user_id`, `source`, `enriched_at` vào `_CUSTOMER_DEFAULTS` (default `""`, không phá load_customer cũ)
- [ ] `src/noble_agent/server/http.py` — CORS helper `_sales_response`, OPTIONS handler, +9 endpoint mới, route `/dashboard` optional (~250 LOC)
- [ ] `src/noble_agent/agent/tools/schemas.py` — +schema `noble_lookup`
- [ ] `src/noble_agent/agent/tools/__init__.py` — dispatch `noble_lookup`, gắn support/consultant
- [ ] `src/noble_agent/__main__.py` hoặc app lifecycle — đăng ký `noble_profile_service.close()` + `rate_limit.close()` shutdown hook
- [ ] `docs/api/sales-api.md` — ghi tất cả endpoint mới + section Rate limit + section Export CSV

### KHÔNG làm trong phase này (theo yêu cầu user)
- ❌ `static/dashboard.html` / `.css` / `.js` — UI user thiết kế sau
- ❌ Prometheus / metrics exporter
- ❌ DLQ auto-drain script
- ❌ Unit tests UI-related
- ❌ SPA build pipeline

### Test
- [ ] `tests/unit/services/test_noble_profile_service.py` — cases U1-U13 (xem §7.1)
- [ ] `tests/unit/storage/test_noble_profiles.py` — save + get + PII strip
- [ ] `tests/unit/storage/test_call_events.py` — log + query + TTL
- [ ] `tests/unit/agent/tools/test_noble_lookup.py`
- [ ] `tests/unit/server/test_rate_limit.py` — bucket accounting, burst, fail-open khi Redis down
- [ ] `tests/unit/server/test_sales_api_bookings.py` — list + detail + mark_contacted + CORS
- [ ] `tests/unit/server/test_sales_api_stats.py` — today + range
- [ ] `tests/unit/server/test_sales_api_customer.py` — 360 + history + search
- [ ] `tests/unit/server/test_sales_api_export.py` — CSV header/encoding, BOM, max_rows cap
- [ ] `tests/unit/server/test_sales_api_ratelimit.py` — 429 + Retry-After header + tier classify
- [ ] `tests/integration/test_telephony_enrich.py` (requires_docker, mock Noble) — splice fail-open
- [ ] `tests/integration/test_mongo_migration.py` — migration idempotent, backward-compat

---

## 6b. Backward-compat & merge safety **(theo yêu cầu user)**

Phần này **must-read** trước khi chạy PR. Đảm bảo:
(a) merge nhánh `feat/summarization-context` hiện tại không bị conflict,
(b) deploy phase này không hỏng luồng đang chạy.

### 6b.1 Touch-points trùng với nhánh đang dev

Dựa vào `git log` + file citation, branch `feat/summarization-context` đang sửa những file này:

| File | Branch hiện tại sửa | Plan này sửa | Conflict risk |
|---|---|---|---|
| `agent/summary/generator.py` | ✅ | ❌ | **None** |
| `storage/call_summaries.py` | ✅ (parse JSON) | ❌ read-only | **None** |
| `server/http.py` | ✅ (`_handle_sales_api`) | ✅ (thêm endpoint) | **HIGH — cùng hàm** |
| `storage/session_store.py` | ❓ (có thể) | ✅ `_CUSTOMER_DEFAULTS` | **Medium** |
| `telephony/session.py` | ❓ | ✅ splice line ~115 | **Low** nếu summarization không sửa lifecycle |
| `storage/connection.py` | ❌ | ✅ add index | **None** |
| `config.py` | ❓ | ✅ +fields | **Low — append-only** |
| `agent/tools/__init__.py` | ❓ | ✅ dispatch mới | **Low — append-only** |

**Giảm rủi ro**:
- Plan này **không sửa** `_handle_sales_api` logic cũ — chỉ **thêm nhánh `if tail == "bookings"..."`** trước fallback `return _json_response({"error":"not_found"},404)`. Endpoint cũ (summaries/handoff) giữ byte-for-byte.
- `_CUSTOMER_DEFAULTS` chỉ **append key mới** với default `""` — `load_customer()` dùng `{**_CUSTOMER_DEFAULTS, **data}` nên data Redis cũ (thiếu key mới) tự động fill default. Không cần migration data.
- `telephony/session.py` splice **sau** `save_customer(session_id, seed)` hiện hành — không đụng bất kỳ logic cũ nào ở phía trước hay sau.

### 6b.2 Quy tắc bắt buộc

1. **Rebase trước mỗi PR**: `git fetch && git rebase origin/develop` — không merge `develop` vào branch plan để tránh nhiễu history.
2. **Feature flag OFF mặc định**: `NOBLE_PROFILE_ENABLED=false`, `NOBLE_SALES_API_KEY=""` → tất cả code mới **no-op** với env cũ. Deploy production với env mới → vẫn giữ hành vi cũ đến khi bật.
3. **Append-only settings**: mọi field config mới **phải có default** không phá validation (`@model_validator`). Đã verify `validate_redis_session_ttl_covers_idle` (config.py:441-452) không bị ảnh hưởng.
4. **Index mới dùng `create_index` (idempotent)**: Mongo `create_index` trả về luôn ngay nếu đã tồn tại. KHÔNG dùng `drop_index`. Nếu index cũ conflict tên, dùng `name=` explicit khác.
5. **TTL mới cho collection có data production**: `bookings_flat` thêm TTL 180d trên `created_at`. Doc cũ > 180d → **sẽ bị xoá trong 24h** (Mongo TTL monitor loop). **Mitigation**: query `db.bookings_flat.count({created_at: {$lt: ISODate("2025-10-25")}})` trước migration để biết sẽ mất bao nhiêu doc. Nếu >0 → backup hoặc giảm xuống 365d.
6. **Response shape endpoint cũ** giữ 100% nguyên vẹn. Nếu bổ sung filter cho `GET /summaries` (section 4.3.2), phải verify call cũ `?phone=X&limit=10` trả identical output.
7. **Rate limit không áp dụng cho endpoint cũ ở deploy đầu**: wrap trong flag `SALES_API_RATE_LIMIT_ENABLED=false` → deploy code xong, quan sát traffic 24h, rồi bật.
8. **Dev server khi `NOBLE_PROFILE_ENABLED=false`**:
   - `noble_profile_service` module import OK (không gọi httpx khi chưa enable).
   - Telephony splice `if settings.noble_profile_enabled` → skip toàn bộ. 0 LOC thực thi.
   - Sales API mới vẫn active (dashboard cần dùng).
   - Rate limit flag độc lập.

### 6b.3 Merge flow đề xuất

```
develop
   │
   ├── feat/summarization-context ──┐
   │                                ▼
   │                              MERGE → develop
   │                                │
   └── (sau khi merge)              ▼
          feat/noble-profile-and-dashboard ← cắt TỪ develop đã merge
                      │
                      ├── PR1 mongo migration     (0% touch http.py)
                      ├── PR2 noble service       (0% touch http.py)
                      ├── PR3 sales API extend    (touch http.py, rebase FIRST)
                      ├── PR4 rate-limit + CSV    (touch http.py)
                      └── PR5 tool noble_lookup
```

→ Bắt đầu PR này **sau khi** `feat/summarization-context` merge vào develop, để tránh 2 branch cùng sửa `http.py`.

### 6b.4 Rollback per PR

| PR | Rollback |
|---|---|
| PR1 (Mongo) | `git revert`; index đã tạo không cần drop (idempotent) |
| PR2 (Noble service) | Set `NOBLE_PROFILE_ENABLED=false` — code không chạy. `git revert` nếu cần xoá file |
| PR3 (Sales API extend) | `git revert`; endpoint mới biến mất, cũ nguyên vẹn |
| PR4 (Rate limit + CSV) | Set `SALES_API_RATE_LIMIT_ENABLED=false`; CSV endpoints revert |
| PR5 (Tool) | Gỡ khỏi dispatcher — tool không đăng ký, LLM không thấy |

---

## 7. Phần V — Test plan

### 7.1 Unit tests Noble service (mock httpx)

Cases (bắt buộc pass 100%):

| # | Scenario | Expected |
|---|---|---|
| U1 | Happy 200 + valid body | return NobleProfile; cache set; snapshot saved |
| U2 | 200 `data: []` (phone not found) | return None; negative cache set |
| U3 | 401 auth error | return None; log critical; **không** cache |
| U4 | 429 rate limited | return None; log warn; không retry |
| U5 | 500 server error (2x) | 2 retry attempts, return None |
| U6 | Timeout 800ms | retry once, total ≤1500ms, return None |
| U7 | Malformed JSON | return None; log parse_error |
| U8 | Cache hit positive | 0 HTTP call, return cached |
| U9 | Cache hit negative | 0 HTTP call, return None |
| U10 | Semaphore exhausted | 9th concurrent waits, none drops |
| U11 | Empty phone | return None immediately, 0 HTTP call |
| U12 | Invalid phone format | normalize or reject (match phone_utils) |
| U13 | Merge rule correctness | Noble wins for full_name/gender; existing wins for project_interest |

### 7.2 Unit tests Sales API (endpoint mới)

| # | Scenario | Expected |
|---|---|---|
| S1 | `GET /bookings` thiếu key | 401 |
| S2 | `GET /bookings?limit=500` | clamp 200 |
| S3 | `GET /bookings?contacted=true&status=confirmed` | pass filter to DAO |
| S4 | `GET /bookings?sort=phone:asc` (field ngoài whitelist) | rơi về default |
| S5 | `GET /bookings?date_from=invalid` | 400 |
| S6 | `POST /bookings/{id}/mark_contacted` invalid outcome | 400 |
| S7 | `POST /bookings/{id}/mark_contacted` not found | 404 |
| S8 | `GET /customers?phone=0857...` unknown phone | 200 profile=null |
| S9 | `GET /customers/search?q=a` (1 ký tự) | 400 min_length |
| S10 | OPTIONS preflight mọi endpoint | 204 + CORS headers |
| S11 | CORS header Access-Control-Allow-Origin | khớp `noble_dashboard_origin` |
| S12 | `GET /summaries` call cũ (phone+limit) | **response identical byte-for-byte với trước** (snapshot test) |
| S13 | `GET /stats/range?from>to` | 400 |
| S14 | `GET /stats/range?from=2026-01-01&to=2026-12-31` (>90d) | 400 range_too_large |

### 7.3 Unit tests Export CSV

| # | Scenario | Expected |
|---|---|---|
| E1 | Export empty result | chỉ header row, Content-Length > 0 |
| E2 | BOM UTF-8 prefix có mặt | first 3 bytes = `\xef\xbb\xbf` |
| E3 | Field chứa dấu phẩy | quoted |
| E4 | Field chứa newline | quoted + escaped |
| E5 | Hard cap max_rows=10000 | row 10001 không có mặt |
| E6 | Timezone datetime | ISO format |
| E7 | open_actions join với ` \| ` | verify split đúng |
| E8 | Content-Disposition filename có timestamp | format `YYYYMMDD-HHMMSS` |

### 7.4 Unit tests Rate limit

| # | Scenario | Expected |
|---|---|---|
| R1 | Dưới rate | allowed=True, remaining giảm |
| R2 | Vượt rate | allowed=False, retry_after>0 |
| R3 | Burst allowance | cho phép 2x trong 5s đầu |
| R4 | Redis down | fail-open (allowed=True), log warn |
| R5 | Tier classify `bookings` → list | rate 120/min |
| R6 | Tier classify `mark_contacted` → write | rate 30/min |
| R7 | Tier classify `export.csv` → export | rate 5/min |
| R8 | Key cũ nghỉ 60s → reset | allowed=True bucket full |
| R9 | Header `X-RateLimit-Remaining` + `X-RateLimit-Reset` | có mặt ở cả 200 và 429 |
| R10 | Flag `SALES_API_RATE_LIMIT_ENABLED=false` | bypass hoàn toàn |

### 7.5 Integration test (requires_docker)

**test_telephony_enrich.py**:
- Mock Noble HTTP server (aiohttp test server) trả response mẫu
- Khởi `TelephonySession` với `caller_number="0857312811"`
- Verify:
  - Customer Redis có `full_name`, `source="noble_api"`, `enriched_at`
  - `noble_profiles.{phone}.raw` có full response
  - `call_events` có event=`profile_enriched` result=`ok`

**test_mongo_migration.py**:
- Seed 5 customer doc không có `source` field
- Chạy `scripts/mongo_migrate_noble_profile.py`
- Verify tất cả có `source="legacy"`, không doc nào bị thay đổi field khác
- Chạy lại → idempotent, không update thêm lần nữa

**test_sales_api_backward_compat.py** (QUAN TRỌNG):
- Seed dữ liệu giống prod hiện tại (`call_summaries` 5 doc, `bookings_flat` 10 doc)
- Gọi các endpoint cũ: `GET /summaries?phone=X&limit=5`, `GET /summaries/{id}`, `POST /handoff`, `POST /summaries/{id}/mark_followed_up`
- Assert response byte-for-byte identical với snapshot captured trước khi đổi code (trừ CORS headers)

### 7.6 Manual smoke (sau deploy staging)

- Curl: `GET /api/v1/sales/stats/today` với key đúng → 200; không key → 401; sai key → 401.
- Curl export: `curl -H "X-Noble-API-Key: ..." -o out.csv /api/v1/sales/bookings/export.csv`; mở Excel xem có hiển thị tiếng Việt đúng không (BOM).
- Curl rate limit: bắn 150 request `/bookings` trong 1 phút → 120 đầu 200, 30 sau 429 có `Retry-After`.
- Gọi hotline từ số test (`0857312811`) → log `[TEL] Noble enriched: phone=... name=...`.
- Tắt Noble API (env sai URL) → log `[TEL] Noble enrich failed/timeout` → **call vẫn tiếp tục bình thường**.
- `GET /api/v1/sales/noble/profile?phone=0857312811` → return raw snapshot sau khi call test trên.

---

## 8. Phần VI — Deployment & rollback

### 8.1 Sequencing

1. **Branch**: `feat/noble-profile-and-dashboard` cắt từ `develop`.
2. **PR 1** — Mongo migration + DAOs (`noble_profiles`, `call_events`) + connection.py indexes. KHÔNG làm gì trên production data.
3. **PR 2** — Noble service + splice (vẫn `NOBLE_PROFILE_ENABLED=false` default). Deploy lên staging, enable `true` để test.
4. **PR 3** — Sales API mới (bookings/stats/customers) + CORS. Verify cũ không vỡ.
5. **PR 4** — Dashboard static + auth flow.
6. **PR 5** — Tool `noble_lookup` on-demand + register.

Mỗi PR ≤ 500 LOC, reviewable độc lập.

### 8.2 Env changes cho prod

`.env`:
```
# Noble Profile
NOBLE_PROFILE_ENABLED=true
NOBLE_PROFILE_API_URL=https://dev-noble-gw.unicloudgroup.com.vn/noble-app-api
NOBLE_PROFILE_API_KEY=gIPgoOnJSIFco8WfqSKXvBOWmZZLrida
NOBLE_PROFILE_TIMEOUT_MS=800
NOBLE_PROFILE_TOTAL_BUDGET_MS=1500
NOBLE_PROFILE_CACHE_TTL_S=3600
NOBLE_PROFILE_NEGATIVE_TTL_S=300
NOBLE_PROFILE_MAX_CONCURRENCY=8

# Sales API
NOBLE_SALES_API_KEY=<generate sk-noble-sales-32char>
NOBLE_DASHBOARD_ORIGIN=*   # same-domain OK; siết về https://your.dashboard.domain nếu cần

# Rate limit (bật sau khi quan sát traffic 24h)
SALES_API_RATE_LIMIT_ENABLED=false
SALES_API_RATE_LIST_PER_MINUTE=120
SALES_API_RATE_WRITE_PER_MINUTE=30
SALES_API_RATE_EXPORT_PER_MINUTE=5
SALES_API_RATE_SEARCH_PER_MINUTE=60
SALES_API_RATE_BURST_MULTIPLIER=2.0

# Mongo retention
BOOKINGS_FLAT_TTL_DAYS=180
```

**Zero-break guarantee**: nếu prod deploy image mới nhưng **giữ nguyên env cũ** (không thêm key nào), tất cả feature mới no-op; hệ thống chạy giống trước.

### 8.3 Rollback

- **Noble enrich**: flip `NOBLE_PROFILE_ENABLED=false` → splice no-op.
- **Dashboard**: xoá `static/dashboard.html` → route trả 404; agent voice không ảnh hưởng.
- **New endpoints**: có thể comment block trong `_handle_sales_api` nếu lỗi.
- **Mongo indexes**: không drop trong rollback; chỉ thêm. TTL mới 180d cho `bookings_flat` an toàn (chỉ ảnh hưởng doc cũ >180d).

### 8.4 Monitoring

- Log pattern grep:
  - `[TEL] Noble enriched: phone=` — success count
  - `[TEL] Noble enrich (failed|timeout)` — error rate
  - `save_noble_profile failed` — storage issues
- Query dashboard-ready:
  ```
  db.call_events.aggregate([
    {$match: {event: "profile_enriched"}},
    {$group: {_id: "$data.result", count: {$sum: 1}}}
  ])
  ```

---

## 9. Review checklist — **đánh dấu trước khi merge từng PR**

### Chuẩn code
- [ ] Tất cả HTTP call external **không raise** ra caller (theo pattern `hotline_outreach_service`)
- [ ] Timeout rõ ràng ở mỗi level (per-attempt + total budget)
- [ ] Logger dùng prefix `[TEL]`, `[NOBLE]`, `[DASHBOARD]` nhất quán
- [ ] `httpx.AsyncClient` singleton + close hook (không leak connection)
- [ ] Semaphore module-level, lazy init bằng `asyncio.get_event_loop()` an toàn
- [ ] Phone normalize **trước khi** query Noble/cache/Mongo (tránh cache miss)

### Chuẩn data
- [ ] Merge rule Noble/speech documented rõ ràng trong docstring
- [ ] `_CUSTOMER_DEFAULTS` update → load_customer backward-compatible (default-merge)
- [ ] `noble_profiles.raw` **không chứa** field nhạy cảm không dùng (strip `idcard_no` trước khi save — PII giảm thiểu)
- [ ] `source` field populate đúng ở mọi write path
- [ ] Không có query nào thiếu filter `phone` khi đọc PII cross-session

### Chuẩn API
- [ ] Tất cả Sales endpoint return JSON với `default=_json_default` (datetime, ObjectId)
- [ ] CORS header cho mọi response, kể cả error
- [ ] OPTIONS preflight trả 204 với `Access-Control-Max-Age`
- [ ] Query param `limit` clamp max 200
- [ ] `phone` query param validate (reject rỗng, sql-injection-proof — dùng query builder)
- [ ] Error response shape nhất quán: `{"error": "...", "message": "..."}`

### Chuẩn UI
- [ ] **KHÔNG áp dụng phase này** — UI user thiết kế sau. Khi ship UI, review riêng.

### Chuẩn Rate limit
- [ ] Tier classifier cover 100% tail paths (dùng match table, không regex ambiguous)
- [ ] Redis script atomic (INCR + EXPIRE trong 1 transaction/pipeline)
- [ ] Response 429 luôn có `Retry-After` seconds + JSON body `{"error":"rate_limited"}`
- [ ] Fail-open khi Redis down (log WARN 1 lần/phút, không spam)
- [ ] Burst window = 5s (không quá lớn — chống DDoS)

### Chuẩn Export CSV
- [ ] BOM UTF-8 (`\xef\xbb\xbf`) first 3 bytes — Excel VN
- [ ] `csv.writer` stdlib, `QUOTE_MINIMAL`
- [ ] Hard cap `max_rows=10000` — log warn khi cap triggered
- [ ] Content-Disposition filename timestamp `Asia/Ho_Chi_Minh` tz
- [ ] Không leak PII (`idcard_no`, `coinWalletQRCode`) vào summary/booking export

### Chuẩn deployment
- [ ] `.env.example` có tất cả key mới, default empty/false
- [ ] Migration script idempotent (chạy 2 lần cho cùng kết quả)
- [ ] Feature flag default off (`noble_profile_enabled=False`)
- [ ] README/sales-api.md update
- [ ] Lint pass `make lint`; test pass `make test-unit`

---

## 10. Timeline & effort (rev 2 — bỏ UI, thêm CSV + rate limit)

| Ngày | Task | Deliverable |
|---|---|---|
| D1 | Mongo migration + DAOs (`noble_profiles`, `call_events`) + indexes + TTL check script + unit test | **PR 1** |
| D2 | Noble service (httpx singleton + semaphore + tenacity + cache) + unit tests U1-U13 | — |
| D3 | Splice telephony + `call_events` log + integration test `test_telephony_enrich.py` + env docs | **PR 2** |
| D4 | Sales API — bookings/stats/customers endpoints + CORS helper `_sales_response` + unit tests S1-S14 + backward-compat snapshot test | **PR 3** |
| D5 | Rate limit module (Redis token bucket) + tier classifier + fail-open test + integrate vào `_handle_sales_api` | — |
| D6 | Export CSV (bookings + summaries) + PII strip + BOM + hard cap test E1-E8 | **PR 4** |
| D7 | Tool `noble_lookup` on-demand + schema + dispatch + SOUL/SKILL update support/consultant + test | **PR 5** |
| D8 | Buffer: staging smoke, docs cập nhật (`docs/api/sales-api.md`), README, deploy checklist | — |

**Tổng**: 7–8 ngày công (1 dev, không tính UI). UI user tự ship riêng sau.

### Định nghĩa "done" mỗi PR
- Unit test pass (`make test-unit`)
- Lint pass (`make lint`)
- Integration test liên quan pass (`make test-integration` nếu có docker)
- `docs/api/sales-api.md` cập nhật endpoint/response mới
- Self-review theo §9 checklist
- Staging smoke pass trước khi request prod deploy

---

## 11. Lời khuyên & lưu ý quan trọng (rev 2)

### 11.1 Điều **PHẢI** làm
- **Feature flag OFF mặc định** (`NOBLE_PROFILE_ENABLED=false`, `SALES_API_RATE_LIMIT_ENABLED=false`) — bật từng flag sau khi smoke staging 24h.
- **Phone normalize 1 nơi**: mọi lần gọi Noble (cache key, Mongo query, HTTP param) bắt buộc qua `telephony.phone_utils.normalize_phone`. Bỏ quên = cache miss vĩnh viễn.
- **Strip PII khi snapshot**: `noble_profiles.raw` bỏ `idcard_no`, `coinWalletQRCode` + các field không dùng. Giảm thiểu PII theo Nghị định 13/2023.
- **HTTP client singleton**: 1 `httpx.AsyncClient` dùng chung + close ở shutdown hook. Tạo mới mỗi call sẽ leak fd và không tận dụng connection pool.
- **Negative cache**: phone lạ gọi liên tục vào giờ cao điểm → cache 300s chặn spam Noble.
- **Backward-compat snapshot test**: endpoint `/summaries` cũ phải trả byte-for-byte identical sau khi thêm filter mới. Dùng pytest snapshot.
- **Rate limit có flag riêng**: deploy code → chạy 24h với flag OFF → bật flag. Không bật cùng lúc với Noble enrichment.
- **Migration idempotent**: script chạy 2 lần cho cùng kết quả. Index `create_index` (Mongo tự idempotent), không drop.

### 11.2 Điều **KHÔNG** nên làm
- **Không** ghi Noble enrichment vào Redis TTL > 24h — Redis là cache, Mongo là store.
- **Không** block StasisStart > 1500ms chờ Noble — khách đã nhấc máy, delay = silence.
- **Không** Prometheus/OpenTelemetry (user từ chối). Dùng log + Mongo `call_events`.
- **Không** cho tool `noble_lookup` vào `router` agent — router phải fast, không HTTP call.
- **Không** ship UI ở phase này — user tự thiết kế. Reserve path `/dashboard` nhưng không generate HTML.
- **Không** siết CORS allow-origin `*` nếu chưa xác định domain dashboard cuối — để env điều khiển.
- **Không** dùng regex cho tier classifier rate limit — dùng match table để tránh catastrophic backtracking.
- **Không** export quá 10k row trong 1 file CSV — cap hard; khuyên user dùng `date_from/to` để chia nhỏ.
- **Không** đặt `Access-Control-Allow-Origin` động từ request `Origin` header nếu không whitelist — CSRF risk.

### 11.3 Trade-offs đã chấp nhận
- **Backend-first, no UI**: đổi lại được full control API spec, user thiết kế UI linh hoạt. Nhược: MVP CSKH chưa thấy được gì ngay lập tức.
- **Merge rule "Noble wins"** cho field identity: nếu Noble DB sai chính tả, LLM có thể đè qua `update_customer` trong call. Hệ thống không có "manual verify" UI để CSKH sửa — phase sau.
- **Không Prometheus**: log grep + `call_events` query đủ. Alert proactive cần bổ sung sau.
- **1 API key duy nhất cho CSKH**: role-based lùi backlog. Key leak = full access — mitigate bằng xoay key định kỳ + rate limit.
- **CSV export non-streaming thực sự**: websockets lib bó buộc body 1-shot. Cap 10k row đủ cho daily/weekly; nếu CSKH cần full-year → phase 2 migrate sang ASGI.
- **Semaphore per-process**: nếu multi-worker (không có hiện tại) → limit × N workers. Tạm chấp nhận; khi scale horizontal, move sang Redis-based semaphore.

### 11.4 Câu hỏi **đã xác nhận** với user
- ✅ Dashboard cùng domain → `noble_dashboard_origin` default `"*"`, optional tighten.
- ✅ Phase này chỉ làm **backend + tính năng**, UI user thiết kế sau.
- ✅ `bookings_flat` 180d, `noble_profiles` 30d đồng bộ với retention hiện tại.
- ✅ **Có** export CSV (bookings + summaries).
- ✅ **Có** rate limit — apply cho Sales API theo tier.
- ✅ Backward-compat là ưu tiên số 1 — nhánh `feat/summarization-context` phải merge được.

### 11.5 Câu hỏi còn mở (non-blocking — quyết định trong khi code)
- Noble API phía họ rate limit cụ thể bao nhiêu? (mặc định giả định 100 req/min; nếu ít hơn → giảm `NOBLE_PROFILE_MAX_CONCURRENCY`)
- Có cần audit log tất cả ai gọi `/mark_contacted` + `/mark_followed_up`? → nếu có, ghi vào `call_events` event=`sales_action`.
- Export CSV có cần support trường customized column (user tự chọn field)? → MVP fix column cứng.
- `noble_user_id` có được expose qua Sales API không? → default **không**, minimize PII.

---

**Hết plan.** Thứ tự ship:
1. Chờ `feat/summarization-context` merge `develop`.
2. Cắt `feat/noble-profile-and-dashboard` từ `develop` mới.
3. Bắt đầu **PR 1 (Mongo migration)** — an toàn nhất, 0 rủi ro, không phụ thuộc gì.
