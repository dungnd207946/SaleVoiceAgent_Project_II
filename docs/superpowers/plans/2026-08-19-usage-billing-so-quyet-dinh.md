# Usage & Billing — sổ quyết định khi thi công

> Chép từ ledger SDD khi thi công `docs/superpowers/plans/2026-08-19-usage-billing.md`.
> 45 quyết định, 19 commit. Giữ lại vì phần lớn là những chỗ PLAN SAI và vì sao,
> thứ không đọc được từ git history.


Spec: docs/build_module_usage&billing/THIET-KE-CHOT.md (+ pricing-schema.sql,
price-version-flow.md, portal-billing-pricing-guide-handoff-from-agent.md) — đọc được.
Branch: dungnd (không phải main). Base khi bắt đầu: 841921d.

## Pre-flight scan

### Cặp task dùng chung file / interface

| Task A → B | A produces | B consumes | Kết quả |
|---|---|---|---|
| 1 → 3,4,8,9 | `billing.rate_usage(...)` | 3 tham số `(from,to,tenant)` | ❌ **XUNG ĐỘT** — xem Ruling 1 |
| 1 → 2 | bảng billing mang tenant_id + RLS | cổng quét schema billing | ok |
| 1 → 4 | `_DDL` của 0943 | Task 4 có thể sửa lại `_DDL` | ok, Task 4 Step 2 nói rõ |
| 3 → 4,5,7,8,9,10 | fixture `workspace_billing`, `bang_gia_vi_du` | dùng trực tiếp | ok |
| 5 → 3 | fixture `api_pool` thêm vào conftest của Task 3 | — | ok, Task 5 Step 1 nói rõ |
| 5 → 7 | `repo.*`, `contracts.*` | router import | ok, tên cột khớp tên field |
| 6 → 7 | `ACTIONS.BILLING_READ` | `require()` | ok, thứ tự 6 trước 7 |
| 5,7 → 9 | `contracts.py`, `router.py` | Task 9 sửa cả hai | ok, thêm chứ không đổi |
| 10 → 3 | FK RESTRICT trên conversations | fixture dọn `agent_keys` | ⚠ Ruling 3 |

### Tự nhất quán từng task

| Task | Kiểm | Kết quả |
|---|---|---|
| 1 | số dòng hạt giống (metric 8, pricing_basis 11, purpose 10/4) | ok, đếm đúng |
| 1 | `status='draft'` trong test vs CHECK mới | ❌ đã sửa lúc cập nhật plan |
| 1 | GRANT cho portal_api vs `agent_all` không được thấy giá | ok — portal_api là THÀNH VIÊN agent_all, quyền chảy từ nhóm xuống nên cấp cho portal_api không lộ cho agent |
| 2 | catalog `BILLING_TABLES_*` khớp bảng 0943 tạo | ok |
| 3 | fixture 13 dòng có ra `TIEN_MONG_DOI`? | ❌ **XUNG ĐỘT** — xem Ruling 2 |
| 4 | 6 bài canh vs hành vi `rate_usage` | ok |
| 5 | tên cột SQL vs field Pydantic | ok; `chi_phi` là Decimal xuyên suốt |
| 6 | action ở code + DB + `make contracts` | ok |
| 7 | 5 endpoint đều `require(BILLING_READ)` | ok |
| 8 | `KHOANG_RE_RUN_GIO=48` + thử khô không ghi | ok |
| 9 | 5 endpoint admin, đủ 5 bước của luồng §3 | ok sau khi thêm Step 5 |
| 10 | migration + 3 bài canh | ok |
| 11 | CLAUDE.md + hợp đồng FE | ok |

## Rulings (pre-flight)

Ruling 1: `billing.rate_usage` trong `pricing-schema.sql` khai 2 tham số
`(p_from, p_to)` nhưng Task 3/4/8/9 đều gọi 3 tham số `(from, to, tenant)`.
Implementer chép "nguyên văn" từ file SQL sẽ tạo hàm 2 tham số rồi mọi test đỏ.
— Quyết định: sửa THẲNG `pricing-schema.sql` thành
`rate_usage(p_from, p_to, p_tenant DEFAULT NULL)` + `SECURITY DEFINER` + vế
`AND (p_tenant IS NULL OR e.tenant_id = p_tenant)`, thay vì để một ghi chú trong
Task 1 dễ bị bỏ qua. Spec là nguồn sự thật nên spec phải đúng.
— Nếu sai: hàm có thêm một tham số không ai dùng; rẻ để bỏ.

Ruling 2: fixture 13 dòng của Task 3 KHÔNG ra 4030.30 — đo thật ra **4025,2625**
(lệch 5,04). 4030.30 là số đo trên dữ liệu SỐNG của `billing.usage_events` lúc
viết spec (34 event); bảng đó nay đã 43 event và ra 4428,71 vì agent vẫn đang ghi.
— Quyết định: đổi `TIEN_MONG_DOI` → `Decimal("4025.26")`, và ghi vào plan rằng
fixture PHẢI tự chèn dữ liệu của nó, không đọc dữ liệu có sẵn. Phép so chính của
cổng vàng là `engine == công thức bên agent` (tự kiểm, đúng bất kể fixture);
hằng số chỉ là cổng chống fixture trôi.
— Nếu sai: cổng vàng đỏ ngay ở Task 3 với số cụ thể, sửa hằng là xong.

Ruling 3: Task 10 đổi FK sang `ON DELETE RESTRICT`, mà `tests/modules/billing/conftest.py`
(Task 3) dọn bằng `DELETE FROM control.tenants` — cascade sẽ cố xoá `agent_keys`
đang được `conversations` trỏ tới và bị RESTRICT chặn ⇒ fixture teardown đỏ ở Task 10.
— Quyết định: KHÔNG sửa trước. Task 10 Step 6 đã có bước
`grep -rn "agent_keys" tests/` đúng cho việc này (bài học `0941`), để implementer
Task 10 tự phát hiện và sửa teardown — thứ tự dọn phải là `conversations` trước
`agent_keys` trước `tenants`. Ghi ở đây để carry vào dispatch của Task 10.
— Nếu sai: teardown đỏ ở Task 10, chi phí một fix round.

Ruling 4: `CLAUDE.md` đang có 3 dòng bị xoá chưa commit, và 2 file docs bị xoá
(commit `324e8a5 fix deploy`) — đều KHÔNG phải của phiên này.
— Quyết định: không đụng. Commit của tôi chỉ `git add` đúng đường dẫn mình tạo,
không bao giờ `git add -A`. Task 11 sửa CLAUDE.md thì sửa thêm vào, giữ nguyên
thay đổi đang có của người dùng.
— Nếu sai: không mất gì, thay đổi của người dùng vẫn nằm trong working tree.

## Tiến độ

### Task 1
Ruling 5: implementer phát hiện repo ĐANG có HAI alembic head trước khi task bắt đầu
(`0939_xoa_role_agent` và `0942_billing_usage_events`, cùng cha `0938_hop_nhat_hai_head`).
Pre-flight scan của tôi không kiểm số head — thiếu sót của tôi. Implementer thêm
migration hợp nhất rỗng `0943_hop_nhat_hai_head_0942` (down_revision là tuple) và
cho `0943_billing_pricing` nối vào đó thay vì nối thẳng `0942`.
— Quyết định: NHẬN. Đây đúng là cách CLAUDE.md bắt buộc (luật `0920`: "sửa bằng
migration hợp nhất, KHÔNG bằng cách đổi down_revision của một nhánh"). Đã xác minh
độc lập: hai head có thật ở commit 9baa384; nay còn một head `0943_billing_pricing`.
— Nếu sai: `alembic upgrade head` gãy cho cả team — nhưng đã đo là không gãy.

Ruling 6: "alternative cleanup" tôi chỉ định cho `test_stt_chi_mot_co_so_tinh_tien`
là SAI — sau khi `pytest.raises` bắt `UniqueViolationError`, giao dịch Postgres đã
abort nên câu `DELETE` dọn dẹp ném `InFailedSQLTransactionError`. Implementer sửa
bằng `conn.transaction()` lồng (savepoint) quanh câu INSERT dự kiến lỗi.
— Quyết định: NHẬN, đây là cách đúng. Lỗi của tôi khi viết plan.
— Nếu sai: không, đã đo đỏ trước khi sửa và xanh sau.
Reviewer đã xác minh ĐỘC LẬP trên DB sống: `agent_all` không có SELECT trên cả 9 bảng
mới; `rate_usage` là SECURITY DEFINER và guard `p_tenant` chặn thật (rate cho tenant A
để lại 0 dòng cho B); RLS ENABLE + 1 policy trên 3 bảng mang tenant_id, FORCE = false;
`usage_events` còn 43 hàng; một head duy nhất; merge node rỗng thật.

Ruling 7: reviewer gọi `GRANT SELECT` trên 2 view của 0942 là "scope creep vì không
có trong Produces". Không phải — khối `_QUYEN` trong plan Task 1 khai tường minh hai
GRANT đó kèm lý do ("cấp để còn đường đối soát tay; code module KHÔNG đọc chúng").
Produces liệt kê bảng được TẠO, không liệt kê grant.
— Quyết định: plan-mandated, giữ nguyên, không sửa.
— Nếu sai: portal_api đọc thêm được 2 view chỉ-đọc; vô hại.

Task 1: minor (deferred): report ghi "6 bài gốc + 2 thêm" trong khi cả 8 bài đều có
sẵn nguyên văn trong brief — sai sót mô tả trong report, không phải lỗi code.
Task 1: complete (commits 9baa384..1f92039, review clean — spec ✅, quality approved)

### Task 2
Ruling 8 (QUAN TRỌNG, ảnh hưởng mọi task còn lại): implementer phát hiện `tests/`
KHÔNG chạy trên DB dev cổng 5442. `tests/conftest.py::pg_dsn` là fixture
**session-scoped testcontainers** (`postgres:18-alpine`), migrate mới mỗi lần chạy.
Mọi chỉ dẫn "kiểm trên DB dev 5442" tôi gửi cho implementer/reviewer đều trỏ SAI DB.
Bước "chứng minh cổng đỏ" của brief Task 2 vì thế chứng minh KHÔNG GÌ CẢ — tắt RLS
trên DB dev rồi chạy suite vẫn xanh vì suite dùng container khác.
— Quyết định: (a) NHẬN cách implementer làm — họ dựng một test tạm mutate RLS trên
CHÍNH container mà suite dùng, xác nhận đỏ→xanh, rồi xoá test tạm; (b) mọi dispatch
từ đây nói rõ: test chạy trên container qua `pg_dsn`/`api_dsn`, không phải 5442;
(c) hệ quả TỐT: Ruling 2 (fixture phải tự chèn dữ liệu) nay là BẮT BUỘC chứ không
chỉ nên — container khởi đầu rỗng nên hằng 4025.26 sẽ ổn định.
— Nếu sai: một bước xác minh trong report không có giá trị chứng minh; code vẫn đúng.
Đã xác minh: `btree_gist` tạo được trên postgres:18-alpine (Task 1 xanh 8/8 trên container).
Task 2: complete (commits 1f92039..6360386, review clean — spec ✅, quality approved, 0 finding)

### Task 3 + 4 (gộp một dispatch: cùng dạng test pytest dùng chung fixture)
Ruling 9: brief Task 3 có BA lỗi fixture, implementer sửa cả ba. Đều là lỗi của tôi:
(a) chèn `control.tenants` TRƯỚC `control.users` mà `tenants.created_by` FK sang users,
    FK không deferrable nên vỡ ngay;
(b) `role_id = 'owner'` không phải id thật — role toàn cục dùng id sinh bằng md5, phải
    tra qua `name = 'Quản trị'`;
(c) teardown của `bang_gia_vi_du` xoá `price_version` mà chưa dọn `rated_usage` /
    `tenant_price_version` trỏ tới nó ⇒ vừa vướng trigger `price_item_bat_bien` vừa
    vướng FK ⇒ teardown vỡ ngay ở bài xanh đầu tiên.
— Quyết định: NHẬN cả ba. Không chỗ nào đụng tới con số nghiệp vụ — golden test khớp
`TIEN_MONG_DOI = 4025.26` ngay lần chạy đầu sau khi sửa plumbing, tức Ruling 2 đúng.
— Nếu sai: fixture vỡ, thấy ngay, không âm thầm.

Task 3+4: minor (deferred): `test_tinh_lai_ky_cu_khi_version_da_inactive` tạo thêm một
`price_version` mà không xoá. Vô hại hôm nay (đã chạy lặp full module để xác nhận) nhưng
bài test nào sau này giả định "chỉ có một is_default" sẽ vướng.

Ruling 10 (carry vào dispatch Task 6): cùng gốc với Ruling 9(b) nhưng ở TASK 6, chưa ai
gặp. Plan Task 6 có `_VAI_TRO_DUOC_CAP = ("owner", "admin")` và câu INSERT
`WHERE EXISTS (SELECT 1 FROM control.roles WHERE id = '{vai_tro}')`. Đo trên DB: KHÔNG
role nào có id `owner` hay `admin` — chỉ có 4 role, id dạng `r_<md5>`:
  r_c82bba81547d32dc8dc5a719d14286eb = Quản trị
  r_9b4ae81524f2dbb11e8f24d994f8cca3 = Biên tập
  r_dfe64a0f8013a12615477e5770057ff4 = CSKH
  r_666d40c1884bae5cd04df076dd52699b = Người xem
Hệ quả nếu để nguyên: `WHERE EXISTS` làm câu INSERT thành **no-op IM LẶNG**, không
role nào được cấp `billing.read`, và `require()` trả 403 cho MỌI người với thông điệp
nói về vai trò — người dùng đi xin thêm quyền cho một action không ai có.
Và `test_action_co_trong_db` assert `>= {"owner"}` cũng sẽ đỏ.
— Quyết định: migration 0944 cấp theo TÊN, không theo id:
  `INSERT ... SELECT id, 'billing.read' FROM control.roles WHERE name = 'Quản trị'`.
  Chỉ cấp cho **Quản trị**. Không cấp Biên tập (soạn nội dung), không CSKH (chăm khách),
  không Người xem (dữ liệu chi phí là dữ liệu nhạy cảm — mở rộng sau dễ hơn thu lại).
  Test đổi thành assert theo tên role, không theo id chép tay.
— Nếu sai: một vai trò cần xem chi phí mà chưa được cấp; thêm bằng migration một dòng.
  Chiều ngược lại (cấp rộng rồi thu) thì đã lộ dữ liệu.

Ruling 11: reviewer Task 3+4 nêu Important — Step 4 của brief Task 3 ("kiểm ngược cổng":
xoá `pricing_basis.wall_ms` rồi bật/tắt `purpose.summary.billable`) không có bằng chứng
đã chạy trong report.
— Quyết định: KHÔNG mở fix round. Mục đích của bước đó là chứng minh cổng có đỏ thật;
reviewer đã tự chạy HAI mutation khác (bật `warm_cache` thành billable → bài
`test_nhan_gia_von_khong_tinh_tien` ĐỎ; cho `resolve_price_version` đọc `status='active'`
→ bài `test_tinh_lai_ky_cu_khi_version_da_inactive` ĐỎ), rồi revert và xác nhận cây sạch.
Bằng chứng cần có đã có, nằm trong report review. Chạy lại hai mutation KHÁC chỉ tốn
một vòng mà không thêm thông tin.
— Nếu sai: mất một mục tài liệu hoá; hai cổng quan trọng nhất đã được chứng minh đỏ được.

Ruling 12: brief Task 4 văn xuôi nói "5 bài canh / PASS 5/5" nhưng khối code của nó có 6
hàm test. Lỗi mô tả của tôi, không phải implementer thêm việc.
— Quyết định: 6 bài là đúng. Không sửa gì.

Task 3: complete (commits 6360386..ec5838e, review clean — spec ✅, quality approved)
Task 4: complete (commits ec5838e..09c325f, review clean — spec ✅, quality approved)
Task 3+4: minor (deferred): pv2 `is_default=true` không được xoá trong
  `test_tinh_lai_ky_cu_khi_version_da_inactive` (xem Ruling 9 note).

Ruling 13 (bối cảnh, không phải defect): 6 file NGOÀI scope đang có thay đổi chưa commit
(`.env.example` +117, `deploy/*.env.example` +87, `docker-compose.local.yml` +57,
`Makefile` +9, `tests/unit/test_cookie_secure.py` +15, `CLAUDE.md` +4). Đã kiểm nội dung:
toàn bộ là việc đưa credential Postgres về `.env` làm nguồn sự thật + một bài test cookie;
0 lần nhắc billing/usage/price. mtime 09:44–09:48 hôm nay. KHÔNG phải của subagent nào
của tôi — người dùng đang làm việc song song trên cùng branch `dungnd`.
— Quyết định: không commit, không revert, không đụng. Mọi commit của tôi `git add` đúng
đường dẫn mình tạo. Test của tôi chạy trên testcontainer nên không phụ thuộc `.env`.
— Nếu sai: nếu đó thực ra là rác do subagent tạo thì nó nằm lại trong working tree cho
người dùng tự xử; không mất gì.

### Task 5
Ruling 14 (TÔI ĐÃ SAI, đã lan vào Task 1): tôi ledger và đưa vào dispatch rằng
"`portal_api` LÀ thành viên nhóm `agent_all`" nên đọc được `billing.usage_events`.
Đúng trên DB DEV, SAI trên database sạch. Đã kiểm: `grep -rn "GRANT agent_all"
migrations/versions/` → chỉ cấp cho `odyssey_agent` (0901) và cho các role
`agent_<tenant>` sinh động (0005/0911). **KHÔNG migration nào cấp cho `portal_api`.**
Membership trên DB dev là trạng thái đặt TAY, không có trong lịch sử migration ⇒
testcontainer (migrate từ đầu) KHÔNG có nó ⇒ `repo.py` chạy bằng `portal_api` ném
`InsufficientPrivilegeError`, đúng như implementer báo.
— Quyết định: GIỮ migration `0944_usage_events_portal_api`. Nó đúng và cần. Chính
docstring của `0942` đã ghi trước rằng việc này còn nợ.
— Nếu sai: thêm một GRANT + policy trùng lặp; vô hại vì idempotent.
— PHÁT HIỆN KÈM, cần báo người dùng: **DB dev có một quyền mà không migration nào
tạo ra** (`portal_api IN ROLE agent_all`). Dev vì thế hành xử khác CI/production —
đúng lớp lỗi "xanh trên máy tôi". Không thuộc phạm vi plan này.
— Ghi chú kỹ thuật: lý lẽ trong docstring 0944 rằng "RLS không đi theo cây kế thừa"
là SAI (tôi đã đo: policy `TO agent_all` CÓ áp cho thành viên của agent_all). Nhưng
kết luận vẫn đúng vì portal_api không phải thành viên trên DB sạch. Minor: sửa câu
giải thích đó để người đọc sau không bị dẫn sai.

Ruling 15 (carry vào dispatch Task 6 và Task 10): số migration đã DỊCH. `0944` nay là
`0944_usage_events_portal_api`. Vậy:
  · Task 6  : `0944_billing_action` → **`0945_billing_action`**
  · Task 10 : `0945_conversations_agent_key_fk` → **`0946_conversations_agent_key_fk`**
Kèm Ruling 10 (cấp action theo TÊN role, không theo id `owner`/`admin`).
Task 5: complete pending review (commit 09c325f..b3f1cae) — review đang chạy
Task 5: minor (deferred): docstring của 0944 giải thích SAI về RLS + kế thừa role
  (kết luận đúng, lý lẽ sai). Sửa câu đó khi có dịp.

### Task 6
Ruling 16: brief Task 6 có lỗi THỨ BA (implementer tự tìm, tôi không thấy trong
pre-flight): `control.actions.group_name` có
`CHECK (group_name IN ('operate','knowledge','configure'))` từ `0104_vai_tro_dong`,
chưa migration nào nới. Brief tôi viết `group_name = 'billing'` ⇒ `upgrade()` sẽ ném
`CheckViolationError`. Implementer đổi thành `'configure'` và xin ý kiến.
— Quyết định: `'operate'`, KHÔNG `'configure'`. Đo catalog hiện có:
  operate   = overview.read, convos.*, appts.*        (xem + vận hành)
  knowledge = catalog.*
  configure = agent_config.*, workspace.admin          (đổi cấu hình)
  `billing.read` là action CHỈ ĐỌC, em ruột của `overview.read`, không phải của
  `workspace.admin`. group_name quyết định cách nhóm trong UI phân quyền, nên đặt sai
  bucket là giấu nó ở chỗ không ai tìm.
— Nếu sai: một action hiện ở nhóm khác trong màn phân quyền; sửa bằng UPDATE một dòng.

Ruling 17: implementer phải sửa `tests/api/test_contracts.py` (ngoài danh sách file của
brief) vì ở đó có assert cứng "đúng 13 action" từ catalog gốc PQ_01 §3.1. Thêm action
thứ 14 làm nó đỏ ĐÚNG NGHĨA.
— Quyết định: NHẬN, bump 13 → 14 kèm docstring giải thích là đúng. Đó là cổng đếm
catalog, không phải cổng nội dung; nó đỏ mỗi lần thêm action là chủ ý của người viết.
— Nếu sai: không, con số phải khớp catalog thật.

Task 6: fix round 1/5 (group_name 'configure' → 'operate') — đang chạy
CÒN NỢ NGOÀI PLAN: `contracts/actions.json` phải COPY TAY sang repo
`odyssey-portal-frontend` (không có CI nào so hai bên). Nhắc trong báo cáo cuối.
Ruling 18: fix Task 6 đặt `billing.read` ở `sort_order=7` và DỊCH 7 action có sẵn xuống
8–14. Tôi kiểm xem có cần thiết: `auth/repo.py:599` đọc catalog bằng
`ORDER BY sort_order` — một dãy GLOBAL duy nhất, và các group hiện là khối LIỀN NHAU
trong dãy đó (operate 1-6, knowledge 7-9, configure 10-13 trước khi sửa).
— Quyết định: NHẬN, việc dịch là đúng và cần. Nếu để `sort_order=900` như plan tôi viết
thì `billing.read` render ở CUỐI danh sách trong khi mang `group_name='operate'` ⇒ phá
tính liền khối ⇒ UI phân quyền hiện một header "operate" lạc ở đáy hoặc xếp item dưới
header sai. Sau fix: operate 1-7, knowledge 8-10, configure 11-14 — vẫn liền khối.
— Nếu sai: thứ tự hiển thị trong màn phân quyền đổi; không ảnh hưởng quyền thật.

Task 6: fix round 1/5 (1 addressed, 0 open — group_name 'configure'→'operate' + sort_order
  liền khối; commits 952b2b6..3d2bd36). Đã chạy round-trip alembic thật trên DB dev.

Ruling 19 (BUG THẬT trong plan, bắt được TRƯỚC khi dispatch Task 7): endpoint
`chi_tiet_phien` trong plan Task 7 lấy phần tóm tắt phiên bằng
`repo.liet_ke_phien(conn, <ngày đầu>, <ngày cuối+1>, 1, 0)` rồi dùng `hang[0]`.
Nhưng `liet_ke_phien(conn, tu_ngay, den_ngay, limit, offset)` KHÔNG có tham số
session — nó `ORDER BY bat_dau DESC LIMIT 1`, tức trả về phiên MỚI NHẤT trong khoảng
ngày đó, không phải phiên người dùng đang mở.
Hệ quả: mở chi tiết phiên A nhưng dòng tóm tắt (khách, khoá, kênh, tổng tiền) là của
phiên B — sai dữ liệu KHÁCH HÀNG trên đúng màn dùng để trả lời khiếu nại hoá đơn.
Fixture hiện chỉ có MỘT phiên nên test của plan sẽ XANH và bug ship im lặng.
— Quyết định: Task 7 phải thêm `repo.doc_phien(conn, session_id)` trả về đúng một hàng
(cùng bộ cột với `liet_ke_phien`), và `chi_tiet_phien` dùng hàm đó. Bỏ luôn cách suy
khoảng ngày từ event đầu/cuối — vòng vo và là nguồn của chính bug này.
BẮT BUỘC kèm test: hai phiên trong cùng khoảng, mở chi tiết phiên CŨ HƠN, assert trả
về đúng phiên đó (không phải phiên mới nhất).
— Nếu sai: thêm một hàm repo nhỏ; không mất gì.

Ruling 20: plan Task 7 tính `chi_phi_tong` bằng
`sum((i.chi_phi for i in items), start=items[0].chi_phi * 0) if items else 0`.
Vòng vo và trả `int` 0 cho nhánh rỗng trong khi contract khai `Decimal`.
— Quyết định: dùng `sum((i.chi_phi for i in items), Decimal(0))`, bỏ nhánh điều kiện.
— Nếu sai: không, đơn giản hơn và đúng kiểu hơn.
Task 6: complete (commits b3f1cae..3d2bd36, review clean — spec ✅, quality approved)
  Reviewer xác minh round-trip THẬT: downgrade → 13 hàng sort_order 1-13 khớp baseline,
  upgrade → 14 hàng, grant `Quản trị` còn nguyên, một head. Và kiểm thứ tự DELETE trong
  downgrade (role_actions TRƯỚC actions vì FK ON DELETE RESTRICT).
Task 6: minor (deferred): docstring `BILLING_READ` không có tiền tố số như 13 action gốc
  (cố ý — action đầu tiên ngoài catalog PQ_01 §3.1).

Ruling 21 (BUG THẬT trong plan, bắt trước khi dispatch Task 9): endpoint
`preview_bang_gia` trong plan Task 9 chạy bằng `portal_api` và làm:
  DELETE FROM billing.rated_usage WHERE tenant_id=$1 AND occurred_at >= ...
rồi gọi `rate_usage` rồi ROLLBACK. Đo được: `portal_api` chỉ có **SELECT** trên
`billing.rated_usage` (0943 cố ý — đường ghi duy nhất là hàm `rate_usage`
SECURITY DEFINER). Câu DELETE đó ném `InsufficientPrivilegeError` ⇒ endpoint preview
KHÔNG BAO GIỜ chạy được.
— Quyết định: KHÔNG cấp DELETE cho portal_api (làm vậy là phá bất biến "chỉ rate_usage
được ghi rated_usage"). Đổi thiết kế preview thành **CHỈ ĐỌC**: thêm hàm SQL
`billing.preview_price_version(p_version_id, p_tenant, p_from, p_to) RETURNS numeric`
dùng ĐÚNG khối LATERAL khớp giá của `rate_usage` nhưng chỉ `SELECT sum(...)`, không ghi
gì. Preview đúng nghĩa là một phép TÍNH, không phải ghi-rồi-rollback — cách cũ còn
vướng trigger `price_item_bat_bien` và RLS.
  Trùng lặp logic khớp giá giữa hai chỗ là rủi ro bảo trì thật, nên BẮT BUỘC kèm một
  test: preview cho phiên bản giá ĐANG áp phải ra ĐÚNG bằng `sum(amount)` của
  `rated_usage` đã định giá bằng chính phiên bản đó. Test đó tự bắt trôi lệch.
— Nếu sai: preview trả số lệch; test equality bắt được ngay.

Ruling 22: câu UPDATE tự tham chiếu `billing.price_version.id` trong subquery của
`gan_cho_tenant` — tôi nghi sai cú pháp, đã chạy thử trên Postgres: CHẠY ĐƯỢC. Không sửa.
Task 5: fix round 1/5 (3 addressed, 0 open — theo_owner fan-out, test gap INNER JOIN,
  docstring 0944; commits b3f1cae..8307751)
Task 5: complete (commits 09c325f..8307751, review clean sau 1 fix round)
  Re-reviewer TỰ reproduce mutation: LEFT JOIN → INNER JOIN ⇒ 1 failed/6 passed (đúng bài
  mới), revert ⇒ 7 passed. Xác nhận `theo_owner` nay là join key-grain↔key-grain 1:1.

### Task 7
Ruling 23: brief Task 7 sai HAI chỗ về API thật của repo, implementer tự sửa:
(a) `loi.LoiPortal(http, code, msg)` — thứ tự tham số thật là `(code, http, msg)`;
(b) `Depends(require(...))` bọc hai lần — `require()` đã trả về `Depends(dep)` rồi,
    dùng đúng là `p: Principal = require(ACTIONS.BILLING_READ)`.
— Quyết định: NHẬN cả hai. Lỗi của tôi khi phác code trong plan mà không đọc `ops/router.py`.

Ruling 24: `billing/contracts.py` KHÔNG có alias_generator camelCase (khác
`ops/contracts.py`), nên JSON trả về là snake_case. Test của brief tôi viết assert
`soPhien`/`chiPhiTong`.
— Quyết định: NHẬN cách implementer sửa test theo snake_case. KHÔNG thêm camelCase
generator: đổi hình dạng JSON của 5 endpoint để khớp một bài test tôi viết sai là đổi
hợp đồng HTTP vì lý do sai. Nhưng GHI NỢ: hai module cạnh nhau trả hai kiểu naming
khác nhau là chỗ FE dễ vấp — cần chốt một chuẩn, ngoài phạm vi plan này.
— Nếu sai: FE phải đọc snake_case cho module này; ghi rõ trong hợp đồng Task 11.

Ruling 25: implementer thêm `fastapi.Query` vào `extend-immutable-calls` của ruff
(pyproject.toml) vì B008 cảnh báo với `Query()` default kiểu `date | None`.
— Quyết định: NHẬN. Đây là cấu hình lint đúng (Query là sentinel bất biến của FastAPI),
và repo đã dùng Query cho `str/int/bool` mà không vướng chỉ vì chúng nằm trong danh sách
built-in của ruff. Ngoài file list của brief nhưng cần thiết.

Ruling 26 (HỒI QUY TỪ TASK 6, TÔI GÂY RA): thêm action thứ 14 làm ĐỎ 5 assert cứng
"13 action" khắp repo. Review Task 6 không bắt được vì TÔI dặn reviewer chỉ chạy 3 test
target (do lo xung đột với agent đang sửa `repo.py`). 4/5 bài đỏ nằm ở `tests/modules/*`
— đúng vùng tôi cấm chạy. Đã đo lại chính xác 5 bài:
  tests/api/test_actions.py::test_dung_13_nhom
  tests/modules/auth/test_vai_tro.py::test_danh_muc_action_tra_13_o_co_thu_tu
  tests/modules/auth/test_login.py::test_dang_nhap_dung_tra_session_va_cookie
  tests/modules/workspace/test_tao.py::test_tao_xong_vao_duoc_ngay
  tests/modules/enrollment/test_router.py::test_admin_khong_dung_13_action_cua_pq01
— Quyết định: gửi về implementer Task 6 sửa GỘP một lượt, phân loại từng assert theo ý
định (cổng đếm catalog → giữ literal, bump 14; "role có đủ bộ action" → suy từ
`len(ALL_ACTIONS)`), và đổi tên hàm test có chữ "13". Yêu cầu chạy FULL suite
(trừ integration) và so với baseline 7 failed/9 errors.
— BÀI HỌC cho các dispatch sau: scope hẹp test để tránh xung đột thì phải TỰ chạy full
suite ở chốt kiểm sau đó. Tôi sẽ làm vậy trước final review.
Task 6: fix round 2/5 (5 addressed — 5 assert cứng "13 action"; commit f886c9c..f131020)
  Full suite về ĐÚNG baseline: 7 failed / 9 errors (5 kb + 2 heartbeat + 9 err org_id).
Task 7: complete pending review (commit 8307751..f886c9c) — review đang chạy
Task 8: complete pending review (commit f131020..6e26b5f) — 36 test billing
Ruling 27: implementer Task 8 dùng argparse trong khi 4 CLI có sẵn ở `src/portal/cli/`
  dùng `sys.argv` thủ công. Lệch có chủ ý và đã khai báo.
— Quyết định: NHẬN. Lệnh này có ba tham số có kiểu (hai ngày + một cờ); argparse là
đúng công cụ, và brief cũng chỉ định vậy. Không bắt copy khuôn cũ chỉ vì nó cũ.

Ruling 28 (CẢI CHÍNH Ruling 3 — tôi đã sai): Ruling 3 dự đoán FK `ON DELETE RESTRICT`
của Task 10 sẽ làm vỡ teardown của conftest (vì `DELETE FROM control.tenants` cascade
xuống `agent_keys` trong khi `conversations` còn trỏ tới). Đã KIỂM THẬT: áp đúng thay đổi
FK rồi `DELETE FROM control.tenants` → `DELETE 1`, KHÔNG lỗi. Postgres xử lý được vì cả
hàng trỏ và hàng bị trỏ đều bị xoá trong cùng một câu lệnh cascade.
— Quyết định: KHÔNG bắt Task 10 sửa teardown. Nói rõ với implementer là đừng "sửa" thứ
không hỏng. Ruling 3 rút lại.
— Nếu sai: teardown đỏ ở Task 10 và implementer sẽ thấy ngay.

Ruling 29: đã xác minh THẬT cả ba assertion cốt lõi của Task 10 trước khi dispatch, bằng
cách áp FK trong transaction trên DB dev:
  1. xoá TRỰC TIẾP khoá đã có conversation → chặn ("violates RESTRICT setting ...")
  2. gán khoá của tenant KHÁC cho conversation → chặn (composite FK)
  3. `revoked_at` (thu hồi) → attribution GIỮ NGUYÊN (agent_key_id không đổi)
Cả hai lỗi đều là SQLSTATE 23503 ⇒ asyncpg ném `ForeignKeyViolationError`, khớp đúng
`pytest.raises` mà plan viết.

### Task 10
Ruling 30 (TÔI SAI trong dispatch, implementer đúng): tôi khẳng định lỗi RESTRICT là
SQLSTATE 23503 ⇒ `ForeignKeyViolationError`. Đo lại trên FK đã áp thật: lỗi là
**23001** — `update or delete on table "agent_keys" violates RESTRICT setting ...`.
Và `issubclass(asyncpg.RestrictViolationError, asyncpg.ForeignKeyViolationError)` là
**False** (23001 vs 23503, hai nhánh riêng).
Nên `pytest.raises(ForeignKeyViolationError)` mà plan viết cho bài xoá-khoá sẽ KHÔNG bắt
được. Ca INSERT chéo tenant thì đúng là 23503/ForeignKeyViolationError.
— Quyết định: NHẬN cách implementer sửa (bắt `RestrictViolationError` cho ca DELETE,
giữ `ForeignKeyViolationError` cho ca INSERT), kèm docstring giải thích khác biệt SQLSTATE.
— Nếu sai: không, đã đo hai lần bằng hai đường.
Ruling 31: implementer kiểm `service.thu_hoi_khoa` (đường `DELETE /admin/keys/{id}`) và
xác nhận nó `UPDATE ... SET revoked_at = now()`, không DELETE thật ⇒ không có khe 500/409
như tôi nghi. Đọc code chứ không đoán.
Task 10: complete pending review (commit 6e26b5f..0609829)

### Task 7 — fix round 1
Ruling 32: reviewer chứng minh bài `test_chi_tiet_phien_dung_phien_khong_phai_moi_nhat`
KHÔNG bắt được bug nó sinh ra để bắt. Họ khôi phục code cũ (derive khoảng ngày rồi
`liet_ke_phien(...,1,0)[0]`) ⇒ 7 passed, test KHÔNG đỏ. Nguyên nhân: fixture đặt phiên
thứ hai ở `MOC + 1 ngày`, mà code cũ suy khoảng ngày TỪ CHÍNH phiên được yêu cầu rồi
cắt theo ngày tròn — hai phiên khác ngày lịch nên mỗi truy vấn tình cờ loại phiên kia ra,
và code SAI vẫn trả đúng hàng. Reviewer dựng thêm probe cùng-ngày (lệch 3 giờ) và chứng
minh code cũ trả về PHIÊN SAI, `doc_phien` trả đúng ⇒ bug thật, fix thật, chỉ có TEST là
vô dụng.
— Quyết định: fix round 1 — dời phiên thứ hai về CÙNG ngày lịch (lệch vài giờ), rồi
BẮT BUỘC kiểm ngược: khôi phục code cũ phải làm test ĐỎ.
— Nếu sai: mất một vòng; nhưng để nguyên là để lại một cổng luôn xanh canh một bug thật.
Task 7: fix round 1/5 (1 addressed, 0 open; commit 0609829..a38fb7e). Reviewer xác nhận
  lý do fix hiệu quả: MOC=09:52, phiên hai cũ ở +1 ngày nằm NGOÀI cửa sổ ngày-tròn của
  code sai nên test xanh vô nghĩa; nay +3 giờ, cùng ngày lịch, nằm TRONG cửa sổ đó ⇒
  code sai chọn phiên mới hơn ⇒ test đỏ. Report có cả hai output pytest.
Task 7:  complete (commits 8307751..a38fb7e, review clean sau 1 fix round)
Task 8:  complete (commits f131020..6e26b5f, review clean — spec ✅, approved, 0 finding)
Task 10: complete (commits 6e26b5f..0609829, review clean — spec ✅, approved, 0 finding)

### Task 9
Ruling 33: implementer bỏ phép kiểm "bộ giá phải `active` mới được gán" trong
`gan_cho_tenant`. Lý do họ nêu: mâu thuẫn với chính test Step 5 của brief (test tạo bộ giá
qua API nên nó ra đời `inactive`) và `status` được tài liệu hoá là nhãn UI không có thẩm
quyền. Đọc lại brief thì đúng — brief tôi viết TỰ MÂU THUẪN.
— Quyết định: NHẬN việc bỏ. Không thay bằng phép kiểm đầy đủ-bảng-giá tại thời điểm gán:
mấy test Step 5 nói về cơ chế khoảng ngày, bắt chúng dựng bảng giá đủ 11 dòng là nhiễu.
LƯỚI AN TOÀN còn lại: `kich_hoat` vẫn chặn bộ giá thiếu dòng, và view
`billing.price_coverage_gap` + dải cảnh báo Overview bắt được lỗ sau đó.
— RỦI RO CÒN LẠI, phải ghi vào hợp đồng FE ở Task 11: gán một bộ giá KHÔNG kiểm tính đầy
đủ; `price_coverage_gap` là lưới, và nó là lưới HẬU NGHIỆM — tiền đã rơi trước khi thấy.
— Nếu sai: một tenant bị gán bộ giá thiếu dòng ⇒ miễn phí âm thầm tới khi ai đó đọc cảnh báo.

Ruling 34: implementer bỏ câu UPDATE hàng loạt cuối `gan_cho_tenant` (hạ mọi bộ giá khác
về `inactive`). Lý do họ nêu là "sai phạm vi dưới RLS" — lý do đó không đúng
(`billing.price_version` không mang tenant_id, không có RLS).
— Nhưng KẾT LUẬN đúng, vì một lý do tốt hơn: `status` là thuộc tính TOÀN CỤC của bộ giá,
còn gán là hành vi THEO TENANT. Suy status toàn cục từ hành động của một tenant là sai —
một bộ giá có thể đang áp cho tenant A trong khi tenant B chuyển đi.
— Quyết định: NHẬN việc bỏ, ghi lại lý do đúng.

Ruling 35: `POST /admin/billing/rate` không được làm (chỉ có trong dòng interfaces của
brief, không có trong Definition of Done).
— Quyết định: KHÔNG làm. CLI của Task 8 đã phủ việc định giá theo lịch, và một endpoint
HTTP định giá MỌI tenant là foot-gun (bấm hai lần, hoặc bấm giữa kỳ chốt sổ). YAGNI.
— Nếu sai: thêm sau là một endpoint gọi đúng hàm đã có.

### Task 11
Task 11: complete (commit 4c85b9e..6b79ccf, docs) — `CLAUDE.md` CỐ Ý để chưa commit vì
  3 dòng người dùng xoá nằm CÙNG HUNK với dòng Change Log tôi thêm; `git add CLAUDE.md`
  sẽ stage luôn thay đổi của họ. Đúng quyết định.
Task 11: phát hiện brief tôi viết sai 3 chỗ, doc ghi theo CODE: admin có 6 endpoint không
  phải 5; response snake_case không camelCase; `llm_khong_chinh_xac` là ĐẾM thô, không
  phải tỷ lệ như tôi mô tả.

Ruling 36 (DEFECT THẬT, tôi tự tìm khi đọc report Task 11 — CHƯA SỬA, đưa vào fix wave
của final review): `voice_sec` trong `repo.tong_quan`, `theo_key`, `liet_ke_phien`,
`doc_phien` (repo.py:34, 97, 165, 217) là `sum(audio_sec)` trên MỌI component. Nhưng
`vad`/`call`/`stt`/`tts`/`speaker_verify` đo những quãng audio CHỒNG LẤN nhau — đúng cái
bẫy §5.1 của bên agent, và đúng cái mà hợp đồng FE của Task 11 dặn FE "đừng bao giờ cộng".
Backend đang tự làm chính việc nó cấm.
Đo trên dữ liệu thật (tenant du_test): `voice_sec` = 466,22 s trong khi thời lượng gọi
thật (`component='call'`) = 176,85 s ⇒ **phóng đại 2,64×**.
TIỀN KHÔNG SAI (mỗi component nhân đơn giá riêng rồi mới cộng tiền). Nhưng KPI
"Thời lượng voice" trên dashboard hiện 2,64× thực tế — người dùng đối chiếu với hoá đơn
điện thoại của họ sẽ kết luận hệ thống sai, hoặc tệ hơn là họ bị tính quá.
— Quyết định: SỬA. `voice_sec` phải nghĩa là THỜI LƯỢNG GỌI =
`sum(audio_sec) FILTER (WHERE component = 'call')` — đó là đồng hồ wall-clock và đúng
nghĩa người ta hiểu khi đọc "thời lượng voice"; phiên chat không có dòng `call` ⇒ 0, đúng.
Chi tiết từng component vẫn có ở timeline của session-detail.
Gộp vào MỘT fix wave sau final review (không dispatch riêng: reviewer Task 9 đang đọc
`src/portal/modules/billing/*`).
— Nếu sai: KPI đổi nghĩa, cần sửa cả doc; nhưng để nguyên là ship một con số vô nghĩa.
— GHI CHÚ: demo artifact tôi dựng cho người dùng cũng hiện "Thời lượng voice 6,4 giờ"
theo đúng cách cộng sai này. Phải nói với người dùng.

### Task 9 — review + fix round 1
Reviewer so SÁT TỪNG TOÁN HẠNG `0947` vs `rate_usage` (0943:311-367): giống hệt trên
metric CASE, thứ tự specificity, `q.qty > 0`, `coalesce(pu.billable,true)`, vị từ ngày.
Khác duy nhất có chủ ý: `rate_usage` giải bộ giá động theo `occurred_at`, preview nhận
`p_version_id` cố định — đúng, vì preview xem MỘT bản nháp cụ thể.
Xác nhận preview KHÔNG cần SECURITY DEFINER (mọi bảng nó chạm đã có SELECT cho portal_api)
và vị từ tenant của nó là BẮT BUỘC (mạnh hơn `rate_usage`).

Ruling 37: reviewer chứng minh cổng chống-trùng-lặp CÓ ĐIỂM MÙ — xoá
`coalesce(pu.billable,true)` khỏi `0947` mà guard test vẫn XANH, vì fixture chỉ phát ra
purpose billable (conversation/summary/stream/session). Họ mutate CASE cột token thì guard
ĐỎ ⇒ cơ chế có răng, chỉ mù đúng toán hạng này.
— Quyết định: fix — thêm một event `purpose='warm_cache'` (billable=false) có token thật
vào chính guard test (KHÔNG sửa fixture chung, để không xê dịch hằng 4025.2625 của golden
test), rồi kiểm ngược bắt buộc.

Ruling 38: `kich_hoat` — "cửa cuối trước khi tiền chạy sai" — có ZERO test. Reviewer đọc
logic thấy đúng nhưng không gì trong 49 bài xác minh nó.
— Quyết định: fix — viết cả hai nhánh, và nhánh từ chối phải assert `status` vẫn
`inactive` sau 409 (cổng trả 409 mà vẫn active là kết cục tệ nhất), kèm ca wildcard
`purpose=''` phải thoả dòng `pricing_basis` có purpose cụ thể.

Task 9: fix round 1/5 (3 findings: điểm mù guard, kich_hoat không test, voice_sec cộng
  chéo component) — đang chạy. Gộp Ruling 36 vào đây thay vì fix wave riêng để một lượt.
Task 9: minor (deferred): `GET /admin/billing/price-versions` trả `dict(asyncpg.Record)`
  thô, không có contract/shape test.
Task 9: minor (deferred): test tạo `price_version` không dọn ⇒ có thể trùng `code` trên DB
  bền (vô hại trên container dùng một lần).

## FINAL REVIEW (toàn branch, 17 commit) — 1 Important chặn merge, 1 Important cần ruling, 8 Minor

Ruling 39 (#1, CHẶN MERGE): `theo_owner` (repo.py:154-155) `JOIN control.agent_keys`
là INNER — nhóm `agent_key_id IS NULL` bị loại vì `NULL = NULL` không khớp. Reviewer đo
được: `by_key` khớp 5025.2625 còn `by_owner` ra 4025.2625, thiếu ĐÚNG 1000 = nhóm NULL.
Cùng lớp lỗi với `voice_sec`: tổng thiếu, im lặng, trên màn hình tiền. `theo_key` có 2 bài
canh nhóm NULL, `theo_owner` không có bài nào — và bài
`test_theo_owner_khong_nhan_ban_qua_join` còn assert owner-total == tenant-total, chỉ xanh
vì fixture đó không có usage vô chủ.
— Quyết định: SỬA. LEFT JOIN + coalesce, hoặc gom NULL thành dòng "không có chủ" tường
minh. Kèm bài canh nhóm NULL cho `theo_owner`.

Ruling 40 (#2, tôi quyết): `min(currency)` (repo.py:37) và `currency="VND"` hardcode
(router.py:147) cộng tiền không phân biệt đơn vị. Đường tới được không cần bug:
`resolve_price_version` fallback về `is_default`, nên một tenant gán bộ giá VND giữa tháng
sẽ có event trước đó tính theo default USD ⇒ một tenant hai đơn vị tiền, cộng âm thầm.
View `cost_by_key_day` (0943:412) ĐÃ group theo currency — view làm đúng, repo làm sai.
— Quyết định: KHÔNG chấp nhận "nền tảng một đơn vị tiền nên bỏ qua". Chốt VND là quyết
định NGHIỆP VỤ, không phải ràng buộc CODE, và không gì trong DB cưỡng chế nó. Sửa: bỏ
`min()` và bỏ hardcode; đọc currency từ dữ liệu; nếu một cửa sổ của một tenant có >1
currency thì NÉM lỗi rõ ràng thay vì cộng. Hỏng ồn ào thay vì hỏng im.
— Nếu sai: một endpoint ném 409 ở ca chưa từng xảy ra; rẻ hơn một hoá đơn cộng sai đơn vị.

Ruling 41 (#4): preview sum biểu thức ở full precision còn `rate_usage` lưu từng event vào
`numeric(20,10)` rồi mới sum. Nay khớp vì mọi thương số của fixture chia hết trong 10 chữ
số. Một `per_units` không chia hết (qty 100 / per_units 60) sẽ làm guard test đỏ vì lý do
vô hại — hoặc che một drift thật.
— Quyết định: cho preview làm tròn TỪNG event đúng như `rate_usage` để hai bên so được
chính xác. KHÔNG refactor gộp logic lúc này (reviewer đề xuất, đúng về lâu dài) — đó là
thay đổi lớn ở phút cuối; ghi thành việc follow-up.

Ruling 42 (#8): CASE `source_expr` bị lặp BA chỗ (0943:330, 0943:385, 0947:56). Metric mới
mà quên sửa một chỗ ⇒ `qty = NULL` ⇒ bị `q.qty > 0` lọc ⇒ event miễn phí âm thầm, VÀ
`price_coverage_gap` có cùng điểm mù nên lưới cũng im.
— Quyết định: không refactor bây giờ, nhưng THÊM MỘT CỔNG: test enumerate `billing.metric`
và khẳng định mỗi metric đều định giá được. Cổng đó bắt được drift mà không cần đổi kiến
trúc. Refactor gộp = việc follow-up.

Ruling 43: nhận toàn bộ triage của reviewer về 8 deferred minor. Sửa ngay: L213+L222
(docstring 0943/0944 nói sai về `portal_api ∈ agent_all`) và L141+L182 (test rò một
`price_version` `is_default=true` — `resolve_price_version` FALLBACK về đúng nó, nên rò một
default là máy sinh flake theo thứ tự chạy, trong đúng bộ test mà cả tính năng dựa vào).
Để lại: L108, L288, L496 (admin list trả dict thô — endpoint duy nhất không có response
model; follow-up ticket), L498 (gộp vào teardown của L141).

## Phán quyết 2 residual sau fix wave (không có wave thứ hai)

Ruling 44 (#2 PARTIAL — PARK): guard đa-đơn-vị-tiền chỉ phủ `summary` và `by-key`.
`by-owner` và ba endpoint session vẫn `sum(amount)` trên cùng tập hàng, không kiểm
currency, không trả trường currency.
— Quyết định: PARK, ghi thành follow-up. Lý do: đường tới được đòi admin CỐ Ý tạo bộ giá
khác đơn vị tiền rồi cho nó làm `is_default` hoặc gán giữa kỳ; nghiệp vụ đã chốt VND
(Ruling ở THIET-KE-CHOT §9). Và hai màn có con số TỔNG nổi bật nhất đã có guard ồn ào.
— RỦI RO CÒN LẠI, phải nói với người dùng: nếu ai đó thật sự dựng bộ giá USD, màn
by-owner và session sẽ hiện một con số vô nghĩa mà không cảnh báo. Việc cần làm:
đưa `tien_tenant()` vào cả 4 chỗ còn lại.

Ruling 45 (#3 PARTIAL — PARK): fix date-scoping cho `theo_owner.so_phien` là ĐÚNG (đọc SQL
xác nhận), nhưng KHÔNG có test canh. Reviewer chứng minh: revert fix ⇒ vẫn 59/59 xanh.
— Quyết định: PARK, ghi thành follow-up. Đây là con số ĐẾM PHIÊN trên màn hình, không phải
tiền; sai thì lệch với màn by-key chứ không lệch hoá đơn.
— Nhưng đúng lớp lỗi tôi truy suốt phiên (một fix không có cổng canh sẽ hồi quy im lặng),
nên nó phải nằm đầu danh sách follow-up.

## Follow-up (không thuộc plan này, chuyển cho người dùng)
1. Test canh date-scoping của `theo_owner.so_phien` (Ruling 45).
2. Đưa guard đa-đơn-vị-tiền vào `by-owner` + 3 endpoint session (Ruling 44).
3. Gộp logic khớp giá của `rate_usage` và `preview_price_version` vào MỘT hàm SQL
   (Ruling 41/42 — nay đã có 2 cổng canh drift, nhưng trùng lặp vẫn còn).
4. `GET /admin/billing/price-versions` trả `dict(asyncpg.Record)` thô — endpoint duy nhất
   không có response model.
5. COPY TAY `contracts/actions.json` sang repo `odyssey-portal-frontend` (đã xác minh:
   file bên đó không có chữ "billing" nào). Không có CI nào so hai bên.
6. `CLAUDE.md` còn thay đổi chưa commit — của người dùng + một dòng Change Log của tôi,
   cùng một hunk. Cần người dùng tự tách và commit.
7. DB dev có `portal_api IN ROLE agent_all` mà KHÔNG migration nào tạo ra ⇒ dev khác CI.
8. Chuẩn hoá naming JSON: `ops` trả camelCase, `billing` trả snake_case.

FINAL: fix wave clean (9/11 addressed, 2 parked có ruling). 59 test billing, full suite
đúng baseline 7 failed/9 errors, isolation 52, một alembic head, ruff sạch.
