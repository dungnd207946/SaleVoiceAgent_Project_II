# Agent-side `kb_search` client backend (`kb_service`) — design

> Client phía agent cho **kb_search retrieval service** do team RAG vận hành, nói
> đúng hợp đồng `docs/superpowers/specs/2026-08-03-kb-search-service-api-contract.md`.
> Thêm một RAG backend mới `kb_service`, **flag-gated, tắt mặc định** → zero behavior
> change cho đến khi bật. Mục tiêu: khi team RAG ship xong, tích hợp = bật flag +
> đổi URL + 1 lần smoke live, không phải viết mới lúc đó.
>
> Xây trước cả khi service live được vì contract đã chốt: client mock-test đầy đủ
> offline (đúng pattern `data/media_data.py` + `search_media`), và là reference
> implementation xác nhận contract khả thi — phát hiện field thiếu/thừa thì sửa
> contract sớm.

## 1. Phạm vi

**Trong phạm vi:** một backend RAG mới `kb_service` cho `kb_search`, gồm HTTP client
config-free + adapter format hits→string + nhánh dispatch trong `noble_kb` + config +
unit test (mock httpx, offline).

**Ngoài phạm vi:** service phía RAG-team (họ tự làm); `send_media` (giữ `:8015`); các
backend cũ (`flat_store`/`qdrant`/`hipporag`/`grep_faq` — không đụng); tool schema LLM
(giữ PA1 `kb_search(query, project_filter)` — **không đổi**); prompt; live smoke (làm
sau khi service có thật).

## 2. Nguyên tắc

- **Tắt mặc định:** `noble_rag_backend` mặc định **không** phải `kb_service`; chỉ khi
  đặt `NOBLE_RAG_BACKEND=kb_service` backend này mới chạy → zero behavior change.
- **Tool schema LLM không đổi** — chỉ thay phần "đằng sau" `noble_kb`. So sánh nhiều
  dự án vẫn là nhiều tool-call song song (PA1), mỗi call gửi `project_codes` 0/1 mã.
- **Degrade an toàn (contract §5):** mọi lỗi transport / non-2xx / timeout / URL rỗng
  → trả `""` (không ngữ cảnh), **không vỡ lượt hội thoại**. `hits: []` → `""`.

## 3. Module

Theo đúng pattern sẵn có (`data/media_data.py` là client config-free mock-test được;
`agent/rag/*_adapter.py` là lớp adapter cho `noble_kb`).

### 3.1 `data/kb_service.py` — HTTP client thuần
```
async def search_kb(
    query: str,
    tenant_id: str,
    project_codes: list[str],
    *,
    base_url: str,
    token: str = "",
    top_k: int = 5,
    min_score: float = 0.0,
    timeout: float = 10.0,
) -> list[dict]:
    ...
```
- POST `base_url` với body `{query, tenant_id, project_codes, top_k, min_score}`
  (bỏ `min_score` khỏi body khi `= 0.0` để giữ payload gọn — optional theo contract).
- Header `Authorization: Bearer {token}` khi `token` không rỗng, else không header.
- `resp.raise_for_status()` → raise `httpx.HTTPError` khi non-2xx (caller bắt).
- Trả `resp.json().get("hits", []) or []` (list dict raw, chưa format).
- **Config-free**: không đọc `settings`; mọi tham số do caller truyền → mock httpx test dễ.

### 3.2 `agent/rag/kb_service_adapter.py` — adapter cho noble_kb
```
async def query_kb_service_for_noble_kb(query: str, project_filter: str, top_k: int = 5) -> str:
    ...
```
- `query`/`project_filter` `.strip()`; `query` rỗng → `""`.
- `tenant_id = current_tenant()` (từ `noble_agent.tenant.current`).
- `project_codes = [project_filter] if project_filter else []`.
- Đọc `base_url`/`token`/`min_score`/`timeout` từ `settings` (`kb_search_*`); `base_url`
  rỗng → log warning + `""`.
- Gọi `kb_service.search_kb(...)` → `hits` → `_format_kb_hits(hits)`.

### 3.3 `_format_kb_hits(hits: list[dict]) -> str` (trong adapter)
Một hit / block, phân tách `"\n---\n"`. Mỗi block:
```
[{project_name} › {section}]        # section bỏ nếu vắng; project_name luôn có
{text}
(cập nhật: {updated_at})            # dòng này chỉ khi có updated_at
```
- Chỉ `text` là bắt buộc; các field tùy chọn vắng thì bỏ dòng tương ứng (không in
  `None`/rỗng). `hits` rỗng → `""`.

### 3.4 `agent/rag/noble_kb.py` — thêm nhánh dispatch
```
if backend == "kb_service":
    return await _query_via_kb_service(query, project)
```
`_query_via_kb_service` bọc `try/except Exception` → log + `""` (mirror
`_query_via_qdrant`). `top_k = settings.kb_search_top_k if > 0 else 5`.

## 4. Config (mirror block `media_search_*` trong `config.py`)

| Setting (env) | Default | Ý nghĩa |
|---|---|---|
| `KB_SEARCH_URL` (`kb_search_url`) | `""` | Endpoint `POST /v1/kb_search`. Rỗng → backend degrade `""`. |
| `KB_SEARCH_TOKEN` (`kb_search_token`) | `""` | Bearer token; rỗng → không gửi header. |
| `KB_SEARCH_TOP_K` (`kb_search_top_k`) | `5` | `top_k` gửi service. |
| `KB_SEARCH_MIN_SCORE` (`kb_search_min_score`) | `0.0` | `min_score`; `0.0` = không lọc (bỏ khỏi body). |
| `KB_SEARCH_TIMEOUT` (`kb_search_timeout`) | `10.0` | Timeout httpx (giây). |

`NOBLE_RAG_BACKEND=kb_service` để kích hoạt. `.env.example` thêm block tài liệu hoá.

## 5. Tests (offline, mock httpx — không cần service live)

- **`data/kb_service.py`:** request đúng shape (`query`/`tenant_id`/`project_codes`/
  `top_k`; `min_score` có mặt khi >0, vắng khi =0); Bearer header khi có token, không
  khi rỗng; parse `hits`; response không có `hits` → `[]`; non-2xx → raise `HTTPError`.
- **`kb_service_adapter.py`:** format có `project_name`/`section`/`updated_at`; section
  vắng → bỏ; updated_at vắng → bỏ dòng; `project_filter=""`→`project_codes=[]`,
  `"NCLB"`→`["NCLB"]`; `tenant_id` lấy từ `current_tenant()`; client lỗi → `""`;
  `base_url` rỗng → `""`; `hits: []` → `""`.
- **`noble_kb.py`:** `backend=kb_service` route tới `_query_via_kb_service`; lỗi → `""`.
- **`config.py`:** 5 key mới load đúng default.

## 6. Bất biến / không đụng

Tool schema `kb_search`, prompt, `send_media`, `media_data.py`, các backend RAG cũ,
`noble_kb` các nhánh cũ — tất cả byte-identical. Backend mới chỉ thêm, không sửa
hành vi hiện hữu.

## 7. Điểm còn mở

1. **Reuse `_format_hits` cũ vs formatter mới:** dùng formatter mới (`_format_kb_hits`)
   vì hit của contract giàu field hơn (`project_name`/`section`/`updated_at`) mà
   `_format_hits` (SearchHit/Chunk) không mang — không ép kiểu ngược.
2. **Live smoke:** hoãn tới khi service RAG có thật (bật flag + `KB_SEARCH_URL` thật).
3. Nếu khi code lộ field contract thiếu/thừa → cập nhật contract §… trước, rồi mới sửa client.
