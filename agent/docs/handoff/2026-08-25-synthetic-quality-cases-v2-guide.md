# Guide: Synthetic eval-quality cases v2 — grounded bằng tool result THẬT

> **Bàn giao cho một session Claude Code (model Opus trở lên).** Guide này là quy trình
> đầy đủ để sinh `<N_SAMPLES>` case eval quality cho tenant `<TENANT_ID>` theo đúng
> schema v2 của harness `evals/` (spec: `docs/superpowers/specs/2026-08-25-evals-quality-refactor-design.md` §4).
> Guide cũ `2026-08-24-synthetic-eval-cases-guide.md` mang schema CŨ — chỉ tham khảo
> phần luật văn phong tiếng Việt của nó, KHÔNG dùng format case của nó.

**Bản 2026-08-25b:** cập nhật sau lần chạy thật đầu tiên (tenant `aina_prod`, 100 case).
Ba thứ đã sập trong lần đó và giờ có mục riêng: preflight embed token (§1), bootstrap
credential per-tenant (§3a), bẫy `status='published'` khi tự tính SQL (§4). Đọc cả ba
TRƯỚC khi probe — mỗi cái đều làm hỏng grounding một cách IM LẶNG.

**Bản 2026-08-25c:** sau lần chạy `noblex_sales`. §6 viết lại thành **ba trục**, trong đó
Trục A là **bản đồ 5 nhóm câu hỏi của khách mua BĐS thật** (§6.1) — dùng lại được cho mọi
tenant, thay cho ma trận chỉ-theo-sắc-thái của bản b. Kèm §6.2: phần lớn Nhóm 2 và Nhóm 4
hỏi những con số corpus KB thường KHÔNG có, nên đích đúng là "nói thật, không bịa" — và đó
là phép đo đáng tiền nhất của một agent sale, có mẫu `expect.reply_not_matches` chặn con số.

## 0. Tham số động (điền khi bàn giao — KHÔNG commit giá trị thật vào file này)

| Placeholder | Ý nghĩa | Ví dụ |
|---|---|---|
| `<TENANT_ID>` | Tenant đích, phải có config published trong control-plane | `aina_prod` |
| `<N_SAMPLES>` | Tổng số case cần sinh | `100` |
| `<TENANT_API_KEY>` | API key gateway của tenant (`ody_ag_…`) — dùng để lấy credential PG per-tenant (§3a) | do người bàn giao đưa |
| `<OUTPUT_FILE>` | File JSONL đích | `evals/quality/data/cases/<TENANT_ID>/p2_synthetic.jsonl` |

**Chạy hoàn toàn từ máy local (2026-08-25):** `.env` của repo đã có
`GATEWAY_CREDENTIALS_API_URL` + `POSTGRES_SERVER_DSN` chạy được từ local — agent local
tự resolve credential per-tenant và đọc data thật của tenant. KHÔNG cần SSH cho grounding.
(SSH/paramiko chỉ còn cần một việc: lấy token models ở §1.)

**An toàn:** mọi credential sống trong prompt bàn giao / `.env` local (gitignored) / thư mục
scratch NGOÀI repo, không được xuất hiện trong bất kỳ file nào của repo, kể cả file scratch
được commit nhầm. Đặt file scratch ở thư mục scratchpad của session, đừng đặt trong repo.

## 1. Preflight — chạy TRƯỚC khi probe, đừng bỏ qua

Cả pipeline này degrade im lặng. Một service chết trông y hệt "tenant không có data", và
agent vẫn trả lời trơn tru nên nhìn transcript không phát hiện được. Ba lệnh dưới đây là
cách phân biệt duy nhất.

```bash
# 1) Redis (agent cần để lưu state phiên)
docker run -d --name eval-redis -p 6379:6379 redis:7   # nếu Redis chưa sống
export REDIS_URL=redis://127.0.0.1:6379/0              # nếu .env trỏ chỗ khác

# 2) Qdrant + collection của tenant có tồn tại không
curl -s "$QDRANT_URL/collections" | grep <TENANT_ID>_documents

# 3) Embed service — BẮT BUỘC, xem ô cảnh báo dưới
python scripts/test_search_tools.py -t <TENANT_ID> --kb "tiện ích dự án"
```

### ⚠ `SANTA_MODELS_TOKEN` — bẫy làm hỏng cả lượt probe

Backend RAG `kb_service` embed **in-process** qua `EMBED_SERVICE_URL`, xác thực bằng header
`Bearer $SANTA_MODELS_TOKEN` (`data/embed_client.py::_service_post`). Token sai → embed trả
**401** → `noble_kb` catch-all → `kb_search` trả **rỗng**, không log gì ở mức turn.

Lần chạy `aina_prod` đầu tiên ra **26/26 `kb_search` rỗng** chỉ vì token trong `.env` đã stale.
Nếu không kiểm, toàn bộ golden answer nhóm QA sẽ viết trên KB rỗng — sai từ gốc mà không ai
thấy.

- **Cách kiểm:** `scripts/test_search_tools.py` gọi thẳng adapter nên 401 nổi lên thành
  traceback thay vì rỗng. Thấy `HTTPStatusError: 401` → token sai; thấy `0 item` mà không
  có traceback → thật sự không có data khớp.
- **Cách lấy token đúng:** nó là biến `ODYSSEY_MODELS_TOKEN` trong container models trên
  product server (`docker exec odyssey-models-embed-1 printenv ODYSSEY_MODELS_TOKEN`; cả 4
  container `stt/tts/embed/speaker` dùng chung một giá trị). Vào server bằng paramiko —
  xem memory `prod-server-10-50-99-104`. Export cho phiên chạy, **đừng ghi vào file trong repo**:
  ```bash
  export SANTA_MODELS_TOKEN=<giá trị vừa lấy>
  ```
- **Dấu hiệu token đúng:** embed dense trả vector **dim 1024** — phải khớp `size` của
  collection `<TENANT_ID>_documents` (kiểm bằng `curl $QDRANT_URL/collections/<TENANT_ID>_documents`).
  Dim lệch = sai không gian vector = Qdrant trả nhiễu mà KHÔNG báo lỗi.

**Nếu phải sửa bất kỳ thứ gì ở §1 sau khi đã probe → PHẢI probe lại toàn bộ và bỏ file
kết quả cũ.** Đừng trộn hai lượt: golden viết từ lượt KB chết là golden bịa.

## 2. Nguyên tắc bất di bất dịch

1. **Golden answer KHÔNG được bịa.** Mỗi số liệu/fact trong `golden.answer` phải rút từ
   **kết quả tool thật** chạy trên data thật của `<TENANT_ID>` (§3). Câu hỏi mà data
   không trả lời được thì đích đúng là "không tìm thấy / xin phép kiểm tra lại" — đó cũng
   là một golden answer hợp lệ (origin `unanswerable`).
2. **Số nào KHÔNG in ra trong tool result mà bạn tự tính bằng SQL thì phải tính bằng ĐÚNG
   bộ lọc của provider** — xem §4, đây là chỗ đã sinh 3 golden sai ở lần chạy đầu.
3. **Scorer kích hoạt theo NỘI DUNG block, không theo `tags`:** `expect` → policy scorer,
   `golden.tools`/`banned_tools` → tool scorer, `golden.answer` → LLM judge, case ≥2 lượt
   → judge multiturn. `tags` chỉ để filter.
4. **Chỉ bắt agent gọi tool mà tenant có bật.** Lấy danh sách enabled từ chính agent (§3b) —
   viết case bắt gọi tool tenant không offer là case sai từ gốc.
5. Mọi case sinh ra để `"reviewed": false` — con người duyệt bằng labeller sau
   (`make eval-labeller`), scorer bỏ qua case chưa duyệt nên data nháp không làm bẩn điểm.

## 3. Lấy dữ liệu thật của tenant (grounding) — chạy hoàn toàn từ local

### 3a. Bootstrap credential per-tenant — làm ĐẦU TIÊN

`scripts/chat_repl.py -t <TENANT_ID>` **tự nó KHÔNG lấy được** credential per-tenant: nó
không có hop gateway nên `pool_for_tenant` rơi về shared DSN (`POSTGRES_DSN`, role
`portal_api`), RLS chặn → mọi query trả 0 row → agent chết với
`RuntimeError: no published config for tenant '<TENANT_ID>'`.

Phải tự fetch credential rồi nạp vào registry in-process trước khi tạo agent:

```python
# bootstrap.py — ĐẶT NGOÀI REPO (thư mục scratchpad của session).
# Nhớ load .env trước khi import config: `from noble_agent.config import get_settings`
# một mình KHÔNG đọc .env (chỉ entrypoint mới load) — copy hàm _load_dotenv của
# scripts/chat_repl.py, và chèn <repo>/src vào sys.path.
import os

from noble_agent.config import get_settings
from noble_agent.gateway.credentials import CredentialsClient
from noble_agent.storage import tenant_credentials


async def register(tenant_id: str) -> None:
    s = get_settings()
    client = CredentialsClient(s.gateway_credentials_api_url, s.gateway_cred_cache_ttl_sec)
    try:
        creds = await client.authorize(os.environ["TENANT_API_KEY"])   # <TENANT_API_KEY>
    finally:
        await client.aclose()
    assert creds.tenant_id == tenant_id, f"key thuộc tenant {creds.tenant_id!r}"
    tenant_credentials.register(creds.tenant_id, role=creds.postgres_role,
                                password=creds.postgres_password,
                                expires_at=creds.expires_at, agent_key_id=creds.agent_key_id)
    # → cache (role, password, expires_at) ra file NGOÀI repo, chmod 600, để lần chạy sau
    #   đọc lại thay vì gọi authorize (xem bẫy 429 ngay dưới).
```

Ba điều sẽ cắn nếu không biết trước:

- **Auth API rate-limit 429.** Gọi `authorize` mỗi process là chết ngay sau vài lần
  (`CredentialsError: auth_api_unavailable`, log `auth API trả 429`). **Cache credential ra
  một file ngoài repo, chmod 600**, đọc lại khi chưa hết `expires_at`; hoặc gom mọi truy vấn
  vào MỘT process. Credential sống ~1 giờ.
- **Verify tenant khớp:** `creds.tenant_id` phải bằng `<TENANT_ID>`. Key gắn nhãn "aina…" có
  thể thuộc tenant `aina_prod` chứ không phải `aina` — hai tenant khác nhau hoàn toàn.
- **Hết `expires_at` giữa lượt probe → registry drop entry → rơi về shared DSN → 0 row IM LẶNG.**
  Bắt đầu lượt probe dài ngay sau khi fetch, và kiểm lại `expires_at` trước khi chạy.

### 3b. Danh sách tool tenant thực bật

Hỏi chính agent, khỏi đoán config:

```bash
printf '/tools\n/quit\n' | python scripts/chat_repl.py -t <TENANT_ID>   # cần bootstrap ở 3a
```

Hoặc trong script đã bootstrap: `NobleAgent.create(...)._runner._agent.tool_names`.
Đối chiếu với 2 file nguồn sự thật, đọc TRƯỚC khi viết bất kỳ case nào:

- **`src/noble_agent/agent/tools/schemas.py`** — schema đầy đủ 12 tool: tên, mô tả
  "khi nào gọi", từng arg + kiểu + enum. Câu hỏi của case phải NGỤ Ý đúng điều kiện
  "khi nào gọi" trong description; arg matcher **chỉ được dùng tên arg có trong schema**.
  (Agent thật đôi khi truyền arg NGOÀI schema — ví dụ `search_units.bedrooms`, `bedroom_count`
  — provider bỏ qua im lặng. Đừng viết matcher trên những arg đó dù thấy nó trong trace.)
- **`src/noble_agent/agent/agent_config.py`** — 4 core luôn bật (`update_customer`,
  `kb_search`, `find_project`, `escalate`) + 8 optional (`discover_projects`,
  `get_project_overview`, `get_document`, `search_units`, `check_inventory`,
  `recommend_units`, `booking`, `send_media`).

Cũng nên đọc **`src/noble_agent/persona/chat/RULES.md`** — nó là cơ sở để viết `expect`, và
quy tắc 12 ở đó quyết định cách xử lý `send_media` trong `golden.tools` (§5).

Hai bẫy khi chấm arg:

- `update_customer` được **miễn trừ** khỏi `irrelevant_call_rate` — đừng đưa nó vào
  `golden.tools` trừ khi chính nó là đích của case (khi đó dùng `expect.customer_field`
  kiểm tra Redis customer thì đúng bản chất hơn).
- `escalate` không bao giờ tắt được; tool trả `ESCALATE_SIGNAL` thì dispatcher TỰ gọi
  escalate. Case post-sale chỉ cần `expect: {"escalated": true}`. Nhưng nếu case là "tool
  tra cứu KHÔNG có data → tự escalate" thì **phải đưa cả tool đó VÀ `escalate` vào
  `golden.tools`**, không thì `escalate` bị đếm là `irrelevant_call`.

### 3c. Kết quả tool THẬT — nguồn của golden answer (đường chính)

Không probe lẻ từng chủ đề. Cách hiệu quả nhất, đã kiểm ở lần chạy đầu:

1. **Thiết kế trước toàn bộ `<N_SAMPLES>` kịch bản** (chỉ phần câu khách nói, kèm
   `customer` preset nếu có) theo ma trận §6 → một file JSON.
2. **Chạy một lượt probe hàng loạt** qua `NobleAgent.stream_response` — đúng entrypoint mà
   transport dùng — ghi lại MỌI tool call + args + **raw result** + reply + customer cuối
   phiên ra JSON. Mỗi kịch bản một `session_id` riêng; concurrency 5–6 là ổn.
3. **Viết golden từ file kết quả đó**, không viết từ ký ức.

Khung script (đặt ngoài repo, dùng bootstrap ở §3a):

```python
async def run_probe(tenant: str, probe: dict) -> dict:
    agent = await NobleAgent.create(session_id=f"probe-{probe['id']}", tenant_id=tenant, channel="chat")
    if probe.get("customer"):
        await agent.set_customer_fields(probe["customer"])
    out = {"id": probe["id"], "turns": []}
    for text in probe["turns"]:                       # multi-turn dùng CHUNG một agent
        calls: list[dict] = []

        def on_tool_start(name, args, _c=calls):
            _c.append({"name": name, "args": dict(args or {}), "result": None})

        def on_tool_done(name, result, _c=calls):     # gán vào call chưa có result gần nhất
            for rec in reversed(_c):
                if rec["name"] == name and rec["result"] is None:
                    rec["result"] = result or ""
                    break

        reply = await agent.stream_response(user_text=text, on_token=lambda t: None,
                                           on_tool_start=on_tool_start, on_tool_done=on_tool_done)
        out["turns"].append({"user": text, "reply": reply, "tools": calls})
    out["customer"] = await agent.get_customer()      # để viết expect.customer_field
    return out
```

Bọc mỗi probe trong `try/except` rồi `asyncio.gather` với `Semaphore(5)`; một kịch bản lỗi
không được làm chết cả lượt. In tiến độ ra stderr để biết nó còn sống.

Sau khi có kết quả, **kiểm ngay hai chỉ dấu degrade** trước khi viết golden:

```python
kb_empty  = [c for c in all_calls if c["name"] == "kb_search" and not (c["result"] or "").strip()]
no_media  = [c for c in all_calls if c["name"] == "send_media" and "no_media" in (c["result"] or "")]
```

Cả hai đồng loạt khác 0 ⇒ hạ tầng chết (thường là §1), KHÔNG phải tenant thiếu data. Sửa rồi
probe lại từ đầu.

`scripts/chat_repl.py -t <TENANT_ID> --ask "..."` vẫn hữu ích để soi một câu lẻ (`/raw`,
`/last`, in TTFT), nhưng đừng dùng nó làm nguồn cho 100 case.

### 3d. Riêng 2 tool retrieval — kiểm nhanh không cần LLM

`make test-search ARGS="-i"` gọi thẳng `kb_search`/`send_media` với tenant tường minh,
không cần config bundle/Redis/LLM — dùng để phân biệt "infra chết" với "data không có".
Nếu Qdrant nằm trong VPC thì mở tunnel trước: `scripts/qdrant_tunnel.sh &`.

## 4. Khảo sát dữ liệu tenant + bẫy `status='published'`

Trước khi viết case phải biết data tenant CÓ GÌ, không thì viết ra case mà data không đỡ được.
Chạy các query dưới (qua `tenant_conn`, nó tự `set_config('app.current_tenant', …)`):

```sql
-- roster + độ dày dữ liệu từng dự án
select p.project_code, p.name, p.region, p.investor, p.sale_phase,
       (select count(*) from tenant_data.units u
         where u.tenant_id=p.tenant_id and u.project_code=p.project_code) units,
       (select count(*) from tenant_data.documents d
         where d.tenant_id=p.tenant_id and d.project_code=p.project_code) docs,
       (select count(*) from tenant_data.media m
         where m.tenant_id=p.tenant_id and m.project_code=p.project_code) media
from tenant_data.projects p order by units desc;

-- quỹ căn theo ĐÚNG bộ lọc của provider (xem cảnh báo dưới)
select u.project_code, u.product_type, u.bedrooms,
       count(*) filter (where u.sale_status='available'
                          and u.status='published' and p.status='published') avail,
       min(u.price_vnd) filter (where u.sale_status='available'
                          and u.status='published' and p.status='published')::bigint pmin,
       max(u.price_vnd) filter (where u.sale_status='available'
                          and u.status='published' and p.status='published')::bigint pmax
from tenant_data.units u
join tenant_data.projects p on p.tenant_id=u.tenant_id and p.project_code=u.project_code
group by 1,2,3 order by 1,2,3;

-- media THỰC CÓ (đừng viết case xin loại không tồn tại)
select content_type, category, count(*), count(distinct project_code)
from tenant_data.media group by 1,2 order by 1,3 desc;

-- document: kiểm xem có gì ngoài CSBH không
select project_code, title, length(coalesce(body,'')) body_len from tenant_data.documents;
```

Và scroll Qdrant `<TENANT_ID>_documents` để biết corpus KB gồm `doc_type` nào, dày bao nhiêu —
nó quyết định câu nào `kb_search` trả lời được, câu nào là `unanswerable`.

### ⚠ Provider lọc `status='published'`, SQL thô thì không

`data/providers/postgres_kb.py` lọc **`p.status='published' AND u.status='published'`** ở mọi
query (`search_units`, `check_inventory`, `discover_projects`, `get_project_overview`), và
"còn bao nhiêu căn" chỉ tính `sale_status='available'`. SQL đếm thô sẽ cho số KHÁC — ở
`aina_prod` chênh tới 2×:

| Ví dụ thật (aina_prod) | SQL thô | Qua tool |
|---|---|---|
| `NOBLE_PALACE_LONG_BIEN` biệt thự còn bán | 30 | **15** |
| `VINHOMES_OCEAN_PARK_3` tổng còn bán | 208 | **204** |
| `THE_FULLTON` biệt thự còn bán | 8 | **0** (toàn bộ `draft`) |

`min/max(price_vnd)` cũng phải tính **trên tập available**, không phải toàn bộ: shophouse
`VINHOMES_OCEAN_PARK_2` toàn bộ 11,7–47,1 tỷ nhưng phần còn bán chỉ 15,8–33,4 tỷ.

Lần chạy đầu sinh **3 golden sai** đúng vì bẫy này. **Luật:** ưu tiên số in ra trong tool
result; số nào tự tính thì phải kèm cả 3 điều kiện lọc, và ghi vào file grounding là "số này
SQL-derived" để người duyệt biết chỗ cần soi.

Ba bẫy dữ liệu khác đã gặp, nên kiểm cho mọi tenant mới:

- Dự án **không có quỹ căn nào** (0 unit hoặc toàn `draft`) → case về chúng phải là
  `unanswerable`, và `search_units`/`check_inventory` ở đó trả `ESCALATE_SIGNAL`.
- Cột `bedrooms` thường **null** ở dự án thấp tầng / Vinhomes → đừng viết case lọc số phòng
  ngủ ở những dự án đó.
- `category` của media chỉ có vài giá trị thật (ở `aina_prod` là `tong_quan`/`mat_bang`/`vi_tri`);
  `send_media(category='tien_ich')` luôn rỗng. Kiểm bảng media trước khi viết case send_media.

## 5. Schema case v2 — format BẮT BUỘC

Nguồn sự thật là `evals/quality/cases.py` (loader từ chối mọi key lạ). Một dòng JSONL = một case:

```json
{"id": "<PREFIX>-NNN", "tenant": "<TENANT_ID>", "origin": "kb|structured|document|unanswerable|handwritten",
 "reviewed": false, "tags": ["policy|tool|qa|multiturn|smoke"], "channel": "chat",
 "customer": {"name": "..."},
 "turns": [{
    "user": "câu khách nói",
    "expect": {"reply_contains": [], "reply_contains_any": [], "reply_not_contains": [],
               "reply_matches": "", "reply_not_matches": "", "escalated": true,
               "customer_field": [{"field": "name", "equals": "Nam"}]},
    "golden": {"tools": [{"name": "kb_search", "args": {"query": {"contains": "từ khoá thật"}}}],
               "banned_tools": ["escalate"],
               "answer": "đáp án chuẩn rút từ tool result thật"}
 }]}
```

Luật cứng (loader raise nếu vi phạm):

- `expect` CHỈ nhận 7 key policy ở trên. Key `tool_called` bị **từ chối** kèm thông báo
  migration; `tool_not_called`/`tool_arg` của schema cũ đã bị xoá hẳn khỏi vocabulary
  (2026-08-25) nên rơi vào lỗi "unknown expect keys". Cả ba chuyển sang
  `golden.tools`/`golden.banned_tools`.
- Mỗi arg matcher là ĐÚNG MỘT trong `{"contains": "<str>"}` (substring, đã normalize
  hoa/thường) hoặc `{"equals": <json>}` (bằng tuyệt đối, đúng kiểu: số 2 ≠ chuỗi "2",
  và phải nằm trong `enum` của schema nếu arg có enum).
- `golden.answer` viết như ĐÁP ÁN Ý CHÍNH — judge chấm khớp nội dung, không bắt từng chữ.
  Judge `correctness` cờ `hallucinated=true` khi reply có fact **vượt ra ngoài** golden answer,
  nên golden phải phủ đủ các fact chính đáng của câu hỏi — viết quá hẹp là tự tạo false positive.
- `id` unique trong toàn thư mục tenant. Convention: `SYN-<TOOL|POL|QA|MT>-NNN`.
- Không có key `axis` (schema cũ) — dùng `tags`.

### `golden.tools` là tập BẮT BUỘC — không khai được "tool tuỳ ý"

`tool_selection` scorer tính **mọi** tool gọi ngoài `golden.tools ∪ {update_customer}` là
`irrelevant_call` (metric có gate). Nhưng `RULES.md` **quy tắc 12** cho phép agent **chủ động**
gửi `send_media` khi đang tập trung vào MỘT dự án — hành vi đúng persona, không phải lỗi.
Schema v2 không có cách khai "tool optional", nên xử lý như sau:

- Case dạng "giới thiệu / tổng quan / hỏi thăm dự án X" → **đưa `send_media` vào `golden.tools`**
  (RULES nói rõ chủ động kèm ảnh ở đúng tình huống này, và agent thật làm vậy).
- Case hỏi một fact hẹp (ở đâu / mấy tầng / pháp lý) → để `golden.tools` tối thiểu, và **ghi
  vào file grounding** rằng finding `irrelevant_call: send_media` ở nhóm này không phải lỗi agent.

File mẫu 7 pattern đầy đủ (policy đơn/đa assertion, contains/equals, banned đứng một
mình, QA, multiturn + customer_field): `evals/quality/data/cases/du_test/p1_examples.jsonl`.
(Lưu ý: case `EX-TOOL-102` trong file mẫu dùng matcher `booking.num_guests` — arg đó KHÔNG có
trong `schemas.py`. Đừng copy chi tiết đó.)

## 6. Phân bổ `<N_SAMPLES>` case — ba trục

Bộ case phải phủ **BA trục cùng lúc**, đừng chỉ phủ một:

- **Trục A — nội dung**: khách BĐS thật hỏi gì (§6.1). Đây là trục CHÍNH, quyết định bộ eval có
  giống cuộc gọi thật hay không.
- **Trục B — sắc thái**: cùng một nội dung nói ngắn / nói dài / nói xẵng (§6.2).
- **Trục C — tool coverage**: mỗi tool tenant bật phải có case ép gọi nó (§6.3).

### 6.1 Trục A — 5 nhóm câu hỏi của khách mua BĐS (dùng lại cho mọi tenant)

Đây là bản đồ câu hỏi theo đúng thứ tự một cuộc tư vấn diễn ra. Cột "Ý đồ" là thứ quyết định
golden: cùng một câu chữ nhưng ý đồ khác nhau thì đích đúng khác nhau.

**Nhóm 1 — Mở đầu, định vị sản phẩm** (~22% tổng số case)

| Dạng hỏi | Ví dụ | Ý đồ của khách |
|---|---|---|
| Tổng quan dự án | "Dự án này ở đâu, chủ đầu tư nào, bao giờ bàn giao?" | Sàng lọc nhanh, xem có đáng nghe tiếp không |
| **Giá / khoảng giá** | "Căn 2 phòng ngủ giá bao nhiêu? Đã gồm VAT với phí bảo trì chưa?" | Neo ngân sách. **Hỏi sớm nhất và hỏi lại nhiều nhất** |
| Quỹ căn / loại hình còn lại | "Còn căn nào hướng Đông Nam tầng trung không? Diện tích nào đang còn nhiều?" | Kiểm tra sale có hàng thật hay chỉ nói chung chung |
| Diện tích – thiết kế – công năng | "Diện tích tim tường hay thông thủy? Có cột giữa nhà không? Chỗ phơi đồ ở đâu?" | Khách ở thật; **"tim tường hay thông thủy" là câu bẫy kinh điển** |

**Nhóm 2 — Tiền và điều kiện mua** (~18%)

| Dạng hỏi | Ví dụ | Ý đồ |
|---|---|---|
| Chính sách thanh toán / tiến độ | "Đóng theo tiến độ thế nào? Ký hợp đồng đóng bao nhiêu %?" | Xem dòng tiền có kham nổi không |
| Vay ngân hàng & hỗ trợ lãi suất | "Hỗ trợ vay bao nhiêu %, ân hạn gốc mấy năm, **hết ưu đãi thả nổi bao nhiêu**?" | Câu cuối **tách sale thật với sale đọc brochure** |
| Chiết khấu / khuyến mãi | "Thanh toán sớm 95% chiết khấu mấy %? Có tặng nội thất không?" | Ép biên lợi ích |
| Chi phí sau khi nhận nhà | "Phí quản lý bao nhiêu/m²/tháng? Phí gửi ô tô, xe máy? Thuế phí sang tên?" | Tính **tổng chi phí sở hữu**, không chỉ giá bán |

**Nhóm 3 — Pháp lý và rủi ro** (~15%)

| Dạng hỏi | Ví dụ | Ý đồ |
|---|---|---|
| Pháp lý dự án | "Có GPXD chưa, đủ điều kiện bán chưa, có bảo lãnh ngân hàng không?" | Xem dự án có bán được hợp pháp không |
| Sổ và thời hạn sở hữu | "Sổ lâu dài hay 50 năm? Bao lâu sau bàn giao thì có sổ?" | Định giá tài sản dài hạn |
| Cam kết & chế tài chậm bàn giao | "Chậm bàn giao phạt thế nào, ghi ở điều nào trong hợp đồng?" | Khách kỹ tính; **muốn cam kết bằng văn bản, không bằng lời** |

**Nhóm 4 — Góc nhìn đầu tư** (~13%)

| Dạng hỏi | Ví dụ | Ý đồ |
|---|---|---|
| Tiềm năng tăng giá & mặt bằng giá khu vực | "Khu này 2 năm qua tăng bao nhiêu? So với dự án X bên cạnh đắt hơn vì sao?" | So kênh đầu tư |
| Khai thác cho thuê | "Cho thuê bao nhiêu/tháng? Tỷ suất ròng mấy %? Ai quản lý cho thuê?" | Tính dòng tiền |
| Thanh khoản & chuyển nhượng | "Chưa có sổ bán lại được không? Phí chuyển nhượng bao nhiêu? Sang tên trước bàn giao được không?" | **Câu đặc trưng nhất của nhà đầu tư** so với khách ở thật |

**Nhóm 5 — Chốt bước tiếp theo** (~12%)

| Dạng hỏi | Ví dụ | Ý đồ |
|---|---|---|
| Tiện ích, hạ tầng, dân cư | "Trường học, bệnh viện, siêu thị quanh đây thế nào? Tỷ lệ lấp đầy bao nhiêu?" | Hình dung cuộc sống thật |
| Xin ảnh / video / tour | "Có ảnh mặt bằng, video, tour 360 không?" | Xem trước khi mất công đi |
| Mời đi xem thực địa | "Cuối tuần này em dẫn anh đi xem nhà mẫu được không?" | Chốt lịch — đích cuối của luồng |

**Multi-turn (~20%)** không phải nhóm thứ sáu, mà là **các nhóm trên nối lại thành một cuộc**:
xưng tên (lượt 1, kiểm `customer_field`) → định vị dự án → hỏi giá → hỏi pháp lý → chốt lịch.
Case ≥2 lượt tự được judge multiturn chấm giữ-ngữ-cảnh.

### 6.2 ⚠ Trục A quyết định phần lớn golden là "KHÔNG có dữ liệu"

Đọc kỹ 5 nhóm trên rồi đối chiếu §4 (khảo sát tenant): **phần lớn Nhóm 2, Nhóm 4 và mục "chế tài
chậm bàn giao" của Nhóm 3 hỏi những thứ mà corpus KB thường KHÔNG có** — giá, VAT, phí bảo trì,
tiến độ thanh toán, lãi suất, ân hạn, chiết khấu, phí quản lý, phí gửi xe, thuế sang tên, chế tài,
giá thuê, tỷ suất, phí chuyển nhượng, lịch sử tăng giá, tỷ lệ lấp đầy.

**Đó là tính năng, không phải khiếm khuyết của bộ eval.** Với agent sale BĐS, phép đo đáng tiền
nhất chính là: *khách hỏi con số mà hệ thống không có thì agent nói thật hay bịa?* — vì bịa một
con số tiền là **hứa sai với khách**, hậu quả thật.

Ở lần chạy `noblex_sales` (2026-08-25), ~55/100 case có đích đúng là "không có dữ liệu → nói
thật". Cách viết những case đó:

```json
{"user": "Ân hạn gốc mấy năm, hết ưu đãi thì lãi thả nổi khoảng bao nhiêu em?",
 "expect": {"reply_not_matches": "\\d+([.,]\\d+)?\\s*(%|phần trăm|triệu|tỷ)"},
 "golden": {"answer": "Tài liệu dự án chưa có thông tin thời gian ân hạn gốc và mức lãi suất sau ưu đãi, nên nói thẳng là chưa có và hẹn chuyên viên báo lại. TUYỆT ĐỐI không bịa con số."}}
```

Ba điều bắt buộc ở nhóm case này:

1. **`expect.reply_not_matches` chặn con số** — bịa bất kỳ số tiền / phần trăm nào là trượt
   **policy scorer**, không phụ thuộc LLM judge. Đây là lưới an toàn cứng.
2. **`golden.answer` phải nêu rõ dữ kiện nào ĐƯỢC nói** (thứ có thật trong corpus), không chỉ nói
   "không có". Viết quá hẹp thì judge `correctness` cờ `hallucinated` oan khi agent trả lời đúng
   phần có dữ liệu (§5).
3. **`origin: "unanswerable"`**, và vẫn tính vào ngưỡng ≥60% có `golden.answer`.

Ngược lại, đừng để cả bộ toàn `unanswerable`: mỗi nhóm phải có ít nhất vài case **trả lời được**
để đo `correctness` thật (Nhóm 1 tổng quan + quỹ căn, Nhóm 3 sổ/pháp lý, Nhóm 5 hạ tầng thường là
những chỗ tenant có dữ liệu).

### 6.3 Trục B (sắc thái) và Trục C (tool) — rải NGANG qua 5 nhóm

Đừng gom sắc thái thành nhóm riêng; trộn vào Trục A để mỗi nhóm đều có đủ giọng:

| Sắc thái | Tỷ lệ gợi ý | Yêu cầu |
|---|---|---|
| **Ngắn gọn / teencode** | ~25% | Một câu như người thật nhắn: "alumi giá tầm nhiu 1m2 v e", "so hong lau dai ko e" |
| **Chi tiết, nhiều ràng buộc** | ~25% | Câu dài ghép nhiều tiêu chí → ép tool với ≥2 arg matcher, có cả `equals` |
| **Cục súc / xẵng giọng** | ~15% | Nội dung hợp lệ, giọng khó chịu ("nói nhanh giá đi, vòng vo hoài") + `expect.reply_not_contains` các từ đáp trả tiêu cực |
| **Lạc đề / khách hỏi ngoài phạm vi** | ~5% | Thường xuất hiện tự nhiên trong Nhóm 4–5 ("so gửi tiết kiệm với mua nhà", "mai có mưa không") → `golden.banned_tools` các tool KB + `expect.reply_contains_any` cụm kéo về BĐS |
| **Policy / post-sale** | ~10% | Khách đã mua hỏi sổ/hợp đồng/bảo hành → `escalated: true`; đòi giá nội bộ / cam kết lợi nhuận → `reply_not_matches` số + `reply_not_contains` |

Ràng buộc cứng (script §8.4 kiểm):

- Mỗi optional tool tenant bật xuất hiện trong **≥3 case**; `kb_search` **không quá 35%** tổng.
- **≥60% case có `golden.answer`** (để suite judge có mẫu đủ dày).
- **≥1 case multi-turn dùng `customer_field`.**
- Văn phong tiếng Việt xưng anh/chị-em tự nhiên; **KHÔNG câu nào trùng cấu trúc nhau quá 2 lần.**

### 6.4 Cố ý viết case "khó" là hợp lệ và có giá trị

Golden = đích ĐÚNG theo schema/RULES + dữ liệu tenant, **không** phải mô tả hành vi hiện tại của
agent. Golden lệch với trace chính là finding. Nhưng **phải liệt kê những case đó trong file
grounding kèm lý do**, không thì người duyệt tưởng case sai và sửa golden theo agent — mất luôn
phép đo.

Ví dụ đã gặp:

- `aina_prod`: agent đi `kb_search` để hỏi giá (KB không có giá, `units` thì có) → golden ép
  `search_units`; agent giải phương trình bậc hai ở case lạc đề; agent gọi `booking(modify)` với
  `booking_id` bịa thay vì `action=list` để lấy mã thật.
- `noblex_sales`: agent chép nguyên văn lời khách vào `get_document(query=...)` nên tra 0 file rồi
  kết luận "dự án chưa có giấy phép" (title trong DB viết tắt là `GPXD`) → golden đòi tra bằng từ
  khoá ngắn hoặc bỏ trống `query`; agent luôn nói "em gửi qua ứng dụng rồi ạ" trong khi RULES quy
  tắc 12 bắt `send_media` gọi ÂM THẦM; agent trả lời bằng markdown trong khi Style bắt văn nói
  thuần; agent hỏi lại tiêu chí trước khi tra thay vì "HÀNH ĐỘNG TRƯỚC, KHAI THÁC SAU".

## 7. Quy trình sinh — theo batch, validate liên tục

1. §1 preflight xanh → §3a bootstrap → §3b bảng tool → §4 khảo sát data → §3c probe hàng loạt.
2. Sinh theo **batch 10 case**, mỗi batch chạy validate ngay:
   ```bash
   PYTHONPATH=. python -c "from evals.quality.cases import load_cases; from pathlib import Path; \
     cs = load_cases(Path('<OUTPUT_FILE>')); print(len(cs), 'case OK')"
   ```
   Loader báo `file:line` khi sai — sửa xong mới sang batch sau.
3. Serialize bằng `json.dumps(case, ensure_ascii=False)` mỗi case một dòng (khớp
   serializer của labeller → save round-trip không đổi byte). Nên viết case trong một script
   Python rồi emit ra JSONL — sửa/re-emit dễ hơn là edit JSONL tay.
4. Xong toàn bộ: chạy §8 rồi `python -m evals list --tenant <TENANT_ID>` phải in đủ
   `<N_SAMPLES>` case (đánh dấu unreviewed), và
   `python -m pytest tests/unit/evals/quality/ -q` xanh.
   **Không để lại file JSONL rỗng** trong `evals/quality/data/cases/` — file rỗng làm đỏ selftest.

## 8. Tự kiểm bằng script — đừng soát bằng mắt

Bốn kiểm tra dưới đây bắt được đúng những lỗi đã lọt ở lần chạy đầu. Chạy hết trước khi báo xong.

**8.1 — Arg matcher khớp `schemas.py` (tên arg, kiểu JSON, enum):**

```python
import json
from noble_agent.agent.tools.schemas import SCHEMAS
props = {n: (s["function"].get("parameters") or {}).get("properties", {}) for n, s in SCHEMAS.items()}
for line in open("<OUTPUT_FILE>", encoding="utf-8"):
    c = json.loads(line)
    for t in c["turns"]:
        for gt in (t.get("golden") or {}).get("tools", []):
            p = props[gt["name"]]
            for arg, m in (gt.get("args") or {}).items():
                assert arg in p, (c["id"], gt["name"], arg, "arg KHÔNG có trong schema")
                if "equals" in m:
                    typ, want = p[arg].get("type"), m["equals"]
                    assert {"string": isinstance(want, str),
                            "integer": isinstance(want, int) and not isinstance(want, bool),
                            "number": isinstance(want, (int, float)) and not isinstance(want, bool),
                            "boolean": isinstance(want, bool)}.get(typ, True), (c["id"], arg, typ)
                    assert not p[arg].get("enum") or want in p[arg]["enum"], (c["id"], arg, want)
```

**8.2 — Mọi tool trong `golden.tools`/`banned_tools` nằm trong enabled list của tenant** (§3b).

**8.3 — Mọi regex trong `expect.reply_matches`/`reply_not_matches` compile được** (`re.compile`).

**8.4 — Quota:** đếm `golden.answer` (≥60%), case có `kb_search` (≤35%), số case mỗi optional
tool (≥3), số case **từng nhóm của Trục A** (§6.1 — không nhóm nào bằng 0) và từng sắc thái của
Trục B, số lượt multi-turn dùng `customer_field` (≥1). Mẹo đếm theo nhóm: mã hoá nhóm vào `id`
(vd `SYN-*-1xx` = Nhóm 1 … `SYN-MT-6xx` = multi-turn) rồi đếm theo chữ số hàng trăm.

**8.5 — Lưới chặn bịa số:** mọi case `origin: "unanswerable"` hỏi tiền/phần trăm phải có
`expect.reply_not_matches` chặn con số (§6.2). Script kiểm nhanh:

```python
import json, re
for line in open("<OUTPUT_FILE>", encoding="utf-8"):
    c = json.loads(line)
    if c["origin"] != "unanswerable":
        continue
    for i, t in enumerate(c["turns"]):
        hoi_tien = re.search(r"giá|bao nhiêu|phần trăm|%|lãi|phí|chiết khấu|tỷ suất", t["user"], re.I)
        if hoi_tien and not (t.get("expect") or {}).get("reply_not_matches"):
            print("THIẾU lưới chặn số:", c["id"], "turn", i)
```

## 9. (Tuỳ chọn) Smoke câu trả lời qua gateway bằng API key

Dùng `<TENANT_API_KEY>` (Bearer) gọi gateway chat cho 5–10 case đại diện để đối chiếu
đường end-user thật (gateway tự resolve tenant từ key — không cần header tenant). Bước này
**phụ**, và thường không chạy được từ local: gateway (`:9200`) của product server không nằm
trong `ODY_FORWARDS` nên không tới được. Grounding chính ở §3c đã đi qua đúng
`NobleAgent.stream_response` mà transport dùng, nên bỏ bước này không làm giảm chất lượng
grounding — chỉ cần ghi rõ trong bàn giao là đã bỏ.

## 10. Bàn giao lại cho người duyệt

- Output: `<OUTPUT_FILE>` (toàn bộ `reviewed: false`).
- **File ghi chú grounding** (đặt ngoài repo, ví dụ `~/<TENANT_ID>_grounding.md`) phải có:
  1. Preflight đã dùng (kể cả việc phải export `SANTA_MODELS_TOKEN` nào, KHÔNG ghi giá trị token);
  2. Bảng roster + quỹ căn + media + corpus KB của tenant;
  3. **Bảng case → raw tool result đỡ nó**, nêu rõ evidence file nào (`out_*.json`);
  4. Danh sách số **SQL-derived** (không in ra từ tool result) để người duyệt soi lại;
  5. Danh sách **case cố ý "khó"** + lý do (§6);
  6. Giới hạn scorer đã biết (§5 `send_media`).
- Người duyệt mở `make eval-labeller` → tenant `<TENANT_ID>` → đọc từng case, sửa nếu
  cần, phím `a` để duyệt. Chỉ case đã duyệt mới được chấm điểm.
- Chạy thử: `make eval-quality ARGS="--tenant <TENANT_ID>"` — cùng điều kiện môi trường
  với §1/§3 (Redis + LLM key + `.env` sẵn `POSTGRES_SERVER_DSN`/`GATEWAY_CREDENTIALS_API_URL`
  + **`SANTA_MODELS_TOKEN` đúng**). Thiếu token thì mọi case kb/QA chấm trên KB rỗng.

## 11. Checklist tự soát trước khi báo xong

- [ ] §1 preflight đã chạy và xanh; embed dense trả dim khớp collection của tenant.
- [ ] Nếu có sửa hạ tầng sau khi probe → đã probe LẠI toàn bộ, đã bỏ file kết quả cũ.
- [ ] `kb_search` rỗng và `send_media` `no_media` = 0 trong file kết quả cuối.
- [ ] Mọi tool trong `golden.tools` nằm trong enabled list của tenant (§3b, script 8.2).
- [ ] Mọi arg matcher dùng đúng tên arg trong `schemas.py`; `equals` đúng kiểu + đúng enum (script 8.1).
- [ ] Mọi `golden.answer` chỉ ra được raw tool result đỡ nó trong file grounding; số SQL-derived
      đã tính bằng đúng bộ lọc `status='published'` + `sale_status='available'` (§4).
- [ ] Không key `axis`, không `tool_*` trong expect, id unique, loader parse sạch.
- [ ] **Phủ đủ 5 nhóm câu hỏi của Trục A (§6.1)** — mỗi nhóm có case, không bỏ trống nhóm nào;
      mỗi nhóm có ít nhất vài case TRẢ LỜI ĐƯỢC chứ không toàn `unanswerable` (§6.2).
- [ ] Mọi case hỏi con số mà tenant không có dữ liệu đều mang `expect.reply_not_matches` chặn
      số tiền / phần trăm, và `golden.answer` nêu rõ dữ kiện nào ĐƯỢC nói (§6.2).
- [ ] Đủ quota từng sắc thái ở Trục B; multi-turn có ≥1 case dùng `customer_field` (script 8.4).
- [ ] `python -m evals list --tenant <TENANT_ID>` in đủ số case; `pytest tests/unit/evals/quality/ -q` xanh.
- [ ] Không credential nào bị ghi vào file trong repo (kể cả `.env`, kể cả file scratch).
