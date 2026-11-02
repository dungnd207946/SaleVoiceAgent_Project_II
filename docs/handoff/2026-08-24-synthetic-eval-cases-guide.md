# Guide: Sinh synthetic case quality cho evals harness

> **2026-08-25: schema đã đổi (v2).** Format case trong guide này là schema CŨ.
> Đọc `docs/superpowers/specs/2026-08-25-evals-quality-refactor-design.md` §4 trước
> khi sinh case; luật văn phong/thu thập dữ kiện tenant bên dưới vẫn dùng được.

**Dành cho:** session/người khác nhận việc tạo bộ case đánh giá quality cho một tenant bất kỳ.
**Đầu ra:** các file JSONL trong `evals/quality/data/cases/<tenant>/`, mỗi dòng một case, `reviewed:false`, chờ người duyệt lật `true` (case chưa duyệt chạy được nhưng không tính vào gate).
**Bộ mẫu đã làm theo guide này:** `evals/quality/data/cases/green_park/` (302 case, commit `212df5d`) — mở ra xem trước khi viết.

---

## 0. Nguyên tắc bất di bất dịch

1. **`axis` quyết định expect nào ĐƯỢC CHẤM.** Scorer hiện chỉ chấm expect trên 2 axis:
   - `axis:"tool"` → CHỈ 3 loại: `tool_called`, `tool_not_called`, `tool_arg`. Loại khác viết vào là **assertion chết** (không ai chấm) và labeller UI/validator sẽ chặn.
   - `axis:"policy"` → đủ 10 loại (3 loại trên + `escalated`, `reply_contains`, `reply_not_contains`, `reply_contains_any`, `reply_matches`, `reply_not_matches`, `customer_field`).
   - Các axis khác (task/grounding/retrieval/unanswerable) CHƯA có scorer chấm expect — **đừng dùng** trừ khi scorer đã được bổ sung.
2. **Case sẽ chấm LLM thật → expect mơ hồ = fail oan.** Chỉ assert thứ suy ra được DUY NHẤT từ lời khách.
3. **Dữ kiện phải thật theo tenant**: tên dự án, tiện ích, khu vực lấy từ corpus của tenant đó (mục 2), không bịa.
4. **Luôn validate bằng parser thật** (mục 6) trước khi bàn giao. "Trông đúng" không phải là đúng.

## 1. Lấy inventory tool (tên + tham số đúng từng ký tự)

Nguồn sự thật là `src/noble_agent/agent/tools/schemas.py`. **Trích lại lúc làm, đừng chép từ guide cũ** (schema có thể đã đổi):

```bash
python3 - <<'PY'
from noble_agent.agent.tools.schemas import SCHEMAS
for name, sch in SCHEMAS.items():
    fn = sch["function"]; props = fn["parameters"]["properties"]; req = fn["parameters"].get("required", [])
    args = [f"{a}{'*' if a in req else ''}({v.get('type')}{'|'+','.join(map(str,v['enum'])) if v.get('enum') else ''})" for a, v in props.items()]
    print(f"{name}: {'; '.join(args)}")
PY
```

Snapshot 2026-08-24 (12 tool): `update_customer`, `kb_search(query*, project_filter)`, `discover_projects(region, budget_max, product_type, purpose[live|invest], investor, sale_phase, index)`, `get_project_overview(project_code)`, `get_document(project_code, query)`, `search_units(project_code*, product_type, max_price, min_area, direction[dong|tay|nam|bac|dong_bac|dong_nam|tay_bac|tay_nam], floor, block, unit_code, sale_status)`, `find_project(query*, region_hint, investor_hint)`, `check_inventory(project_code*)`, `recommend_units(project_code, budget_max, region, bedrooms, purpose, birth_year, gender, menh[kim|moc|thuy|hoa|tho], zodiac)`, `booking(action*[check_availability|schedule|list|modify], preferred_date, preferred_time, name, use_profile_name, phone, use_calling_phone, project_code, confirmed, notes, booking_id, new_preferred_date, new_preferred_time)`, `escalate(action*[check_state|transfer], reason, department, priority)`, `send_media(query*, project_code, category[tong_quan|ngoai_that|noi_that|tien_ich|mat_bang|vi_tri|tien_do], content_type[image|video|tour_360])`.

## 2. Lấy dữ kiện thật của tenant (dự án, tiện ích, media)

PG thường bị RLS chặn với role mặc định — đường chắc ăn là **Qdrant read-only**:

```bash
python3 - <<'PY'
import asyncio, re
from dotenv import load_dotenv; load_dotenv(".env")
TENANT = "green_park"   # <-- đổi
async def main():
    from noble_agent.config import settings
    from qdrant_client import AsyncQdrantClient
    c = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    pts, _ = await c.scroll(collection_name=f"{TENANT}_documents", limit=300, with_payload=True, with_vectors=False)
    seen = {}
    for p in pts:
        pl = p.payload or {}; pid = pl.get("project_id")
        if pid not in seen:
            text = re.sub(r"<[^>]+>|&\w+;", " ", pl.get("text") or "")
            seen[pid] = (pl.get("project_name"), " ".join(text.split())[:200])
    for pid, (name, text) in seen.items(): print(f"[{pid}] {name} — {text}\n")
    pts2, _ = await c.scroll(collection_name=f"{TENANT}_media", limit=200, with_payload=True, with_vectors=False)
    from collections import Counter
    print("MEDIA:", Counter((p.payload.get("project_id"), p.payload.get("category"), p.payload.get("content_type")) for p in pts2))
    await c.close()
asyncio.run(main())
PY
```

Ghi lại: danh sách dự án (mã + tên + khu vực + CĐT + 1-2 fact tiện ích/vị trí), và media nào tồn tại (category/content_type theo dự án) — **chỉ expect `content_type=video` cho dự án THẬT SỰ có video; đừng expect `tour_360` nếu corpus chưa có**.

Nếu có API key của tenant, đối chiếu thêm **skills** (tool nào được bật) qua runtime-credentials + bảng `tenant_data.agent_config` (xem `scripts/eval_with_key.sh` làm mẫu lấy credential). Không có key thì phủ đủ 12 tool và GHI CHÚ trong báo cáo bàn giao rằng case của tool bị tenant tắt sẽ fail oan.

## 3. Format case (JSONL — một object/dòng)

```json
{"id":"TOOL-001","axis":"tool","origin":"handwritten","tenant":"<tenant>","channel":"chat","reviewed":false,"turns":[{"user":"Anh tìm căn 2 phòng ngủ ngân sách khoảng 5 tỷ","expect":{"tool_arg":{"tool":"recommend_units","arg":"budget_max","equals":5000000000}}}]}
{"id":"POL-002","axis":"policy","origin":"handwritten","tenant":"<tenant>","channel":"chat","reviewed":false,"turns":[{"user":"Chị mua căn ITR năm ngoái, giờ hỏi tiến độ sổ hồng","expect":{"escalated":true}},{"user":"Bao lâu có người gọi lại?","expect":{}}],"customer":{"is_noble_customer":true}}
```

- Cố định: `origin:"handwritten"`, `channel:"chat"`, `reviewed:false`. Không có field `golden` (đó là việc của suite RAG).
- `customer` (object, tuỳ chọn) = hồ sơ có sẵn TRƯỚC hội thoại — dùng khi kịch bản cần (khách cũ, đã biết dự án quan tâm).
- Shape expect: `"tool_called":"kb_search"` hoặc list; `"tool_arg":{"tool":...,"arg":...,"equals":<giá trị>}` hoặc `{"...","contains":"chuỗi"}` (nhiều cái → list); `"customer_field":{"field":"name","equals":"Long"}`; `"reply_contains_any":["...","..."]` (list ≥2); regex theo Python `re.search`, so reply KHÔNG phân biệt hoa thường với các loại contains.
- Turn dẫn chuyện: `"expect":{}` — hợp lệ, không chấm.

## 4. Luật viết expect cho chắc tay (đúc kết từ đợt green_park)

1. `tool_arg` chỉ khi giá trị suy ra duy nhất: số nói rõ ("5 tỷ"→`5000000000`), enum nói rõ (hướng "Đông Nam"→`direction=dong_nam`; "cho xin video"→`content_type=video`; "đặt lịch"→`booking.action=schedule`, "dời lịch"→`modify`; đầu tư→`purpose=invest`). Chuỗi mềm dùng `contains` (`kb_search.query contains "bể bơi"`).
2. **ĐỪNG** expect `project_code equals <mã>` — agent resolve tên→mã qua `find_project`, đoán mã trong arg fail oan. Ngoại lệ: `customer.project_interest` đã set sẵn mã đó.
3. `tool_not_called` = ranh giới nghiệp vụ: hỏi thông tin ⇒ không `booking`; câu pre-sale thường ⇒ không `escalate`.
4. `escalated:true` CHỈ cho: post-sale (đã mua: sổ hồng/hợp đồng/thanh toán/bàn giao/bảo hành/xuất hoá đơn/sang tên), đòi giá riêng/chiết khấu sâu, khiếu nại gay gắt, đòi gặp người thật, tranh chấp pháp lý. Chê "đắt thế" ≠ đòi giá riêng → `escalated:false`.
5. Reply-assertion: ưu tiên dạng PHỦ ĐỊNH (`reply_not_contains "cam kết"`, `reply_not_matches "\\d+\\s*%\\s*(lợi nhuận|sinh lời)"`) hoặc `reply_contains_any` list rộng 3-5 biến thể. `reply_contains` đơn chỉ dùng chuỗi gần chắc chắn (tên dự án khách vừa nhắc).
6. Mỗi case 1-3 kiểm tra đúng trọng tâm. Không nhồi.

## 5. Nội dung & văn phong

- **Phân bổ tham khảo (≈300 case):** 170 tool (60 khám phá/hồ sơ, 60 kb+media, 50 căn hộ/tồn kho/phong thủy/booking) + 130 policy (65 hai-phía-lằn-ranh-escalate, 65 chống-cam-kết/lạc-đề/customer_field/giữ-vai).
- **Mỗi tool chính ≥8-12 case**; booking phủ đủ 4 action; recommend_units có nhóm phong thủy (mệnh/tuổi/năm sinh).
- **≥25% multi-turn** (2-4 lượt): hỏi → đào sâu → chốt lịch; lượt 1 thường → lượt 2 lộ đã-mua ⇒ escalate.
- **Văn phong như người thật, mỗi sắc thái ≥15%/batch:** rõ ràng lịch sự · cụt lủn tin nhắn ("ITR còn hàng k") · cục súc ("bớt đc bao nhiêu nói thật đi") · vui vẻ thân mật · kể lể dài dòng · teencode/sai chính tả nhẹ ("e oi du an nao gan ha long ko") · lạc đề (thời tiết/chứng khoán/gạ gẫm). Đại từ đa dạng (anh/chị/cô/chú/mình/t). Khách nhắc dự án bằng TÊN (đủ/tắt/sai nhẹ), không dùng mã.
- **Anchor smoke** (để `make eval-quality-smoke ARGS="--tenant <t>"` dùng được): TOOL-001 & TOOL-002 = `tool_arg recommend_units.budget_max equals` (5 tỷ / 800 triệu), TOOL-004 = `tool_called find_project` + `tool_not_called escalate`, POL-001 = đã-mua-hỏi-sổ-hồng → `escalated:true`.

## 6. Quy trình sản xuất & validate

1. Chia batch theo chủ đề, mỗi batch 50-65 case, **dải ID rời nhau** (TOOL-001..060, TOOL-061..120, POL-001..065...), mỗi batch một file `p1_<chủ đề>.jsonl`. Nếu dùng subagent song song: mỗi agent một file + một dải ID, cấm đụng file khác.
2. Mỗi batch tự validate cho tới khi pass:

```bash
python3 -c "
from pathlib import Path
from evals.quality.cases import load_cases
cases = load_cases(Path('evals/quality/data/cases/<tenant>/<file>.jsonl'))
assert all(c.tenant=='<tenant>' and not c.reviewed for c in cases)
allowed={'tool_called','tool_not_called','tool_arg'}
for c in cases:
    if c.axis=='tool':
        for t in c.turns: assert set(t.expect)<=allowed, (c.id, set(t.expect))
print('OK', len(cases))
"
```

3. Validate chéo TOÀN thư mục (bắt id trùng xuyên file — loader tự check) + thống kê phủ:

```bash
python3 -c "
from pathlib import Path
from collections import Counter
from evals.quality.cases import load_case_dir
cases = load_case_dir(Path('evals/quality/data/cases/<tenant>'))
print(len(cases), dict(Counter(c.axis for c in cases)))
print('multi-turn:', sum(1 for c in cases if len(c.turns)>1))
print(Counter(k for c in cases for t in c.turns for k in t.expect))
"
```

Checklist trước khi bàn giao: đủ số case · id không trùng · axis đúng luật expect · 10/10 loại expect có mặt (policy) · ≥25% multi-turn · anchor smoke đúng shape · tên dự án khớp corpus · không expect media/enum mà corpus không có.

4. Commit vào branch làm việc (KHÔNG đụng `develop`), message dạng `feat(evals): NNN case quality cho tenant <t> (... , reviewed=false chờ duyệt)`.

## 7. Sau bàn giao — vòng đời case

Reviewer mở **labeller** (`evals/quality/labeller.html`, tab Case quality) → Import từng file → sửa/duyệt → bật `reviewed:true` → xuất đè lại file. Chạy: `scripts/eval_with_key.sh <API_KEY_tenant> --case ...` (tenant db-mode) hoặc `python -m evals run --tenant <t>`. Registry ghi `evals/registry.jsonl`; xem trend bằng `make eval-report`.

## 8. Bẫy đã sập — đừng sập lại

- Expect ngoài 3 loại tool trên axis `tool` → assertion chết (validator + labeller đã chặn, nhưng đừng dựa vào may).
- `tool_arg project_code equals` → fail oan (mục 4.2).
- Expect `content_type=video`/`tour_360` khi corpus tenant không có media đó → fail oan.
- Quên `TOOL-004`-kiểu (`tool_not_called`) trong smoke set → gate `unnecessary_call_rate` không có mẫu → **fail-closed vĩnh viễn**.
- `reviewed:true` ngay từ đầu → case chưa ai duyệt đã được tính vào gate release. Luôn `false`.
- Số tiền viết "5.000.000.000" (có dấu chấm) trong JSON → sai kiểu; phải là số `5000000000`.
- Curly quotes ("…") lọt vào cấu trúc JSON khi soạn bằng editor văn bản.
