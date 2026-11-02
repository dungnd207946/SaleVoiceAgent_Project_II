# Cảnh báo mâu thuẫn dữ liệu dự án

**Ngày:** 2026-10-14
**Repo:** `odyssey-portal-backend` (dò, lưu, API), `odyssey-portal-frontend` (icon, popup)
**Trạng thái:** đã duyệt 2026-10-14
**Mockup:** bản 7 của phiên brainstorm (màn Kiến thức, popup cả workspace, màn dự án, popup một dự án, popup sau khi lưu)

## 1. Mục tiêu

1. Phát hiện chỗ dữ liệu của một dự án tự mâu thuẫn: hai tài liệu ghi khác nhau (ví dụ hai chính sách bán hàng), hoặc tài liệu ghi khác trường đã điền (ví dụ đơn vị phát triển, quy mô).
2. Báo cho người dùng bằng popup, chỉ rõ mâu thuẫn ở đâu: một dòng tóm tắt, hai nguồn, đoạn trích nguyên văn của mỗi nguồn.
3. Chi phí LLM theo kích thước phần vừa đổi, không theo kích thước dự án.

Ngoài phạm vi:

- Bảng căn (giỏ hàng). Nó chỉ là phần đang chào bán nên số căn khác quy mô dự án là bình thường.
- Ảnh, video, tour 360, và kho «Tài liệu tra cứu» cấp workspace (`kb_files`).
- Dò riêng lỗi OCR. OCR đọc sai chỉ bị bắt khi nó lệch với một nguồn khác.
- Mâu thuẫn giữa hai dự án.
- Chặn phát hành hoặc tự ẩn dữ liệu khỏi agent.
- Trung tâm thông báo dùng chung toàn portal.

## 2. Quyết định đã chốt

| # | Quyết định |
|---|---|
| Hệ quả | Chỉ cảnh báo. Dữ liệu vẫn lên agent như bình thường, không chặn phát hành |
| Khi nào dò | Tự dò mỗi lần lưu, và có nút kiểm tra một dự án hoặc tất cả dự án |
| So gì | Tài liệu với tài liệu, và tài liệu với trường đã điền của dự án, phân khu, toà, trong cùng một dự án |
| OCR | Không dò riêng |
| Cách dò | Tìm đoạn liên quan trong Qdrant, rồi để LLM phán từng nhóm; kiểm đoạn trích bằng code |
| Chi phí | Sáu chỗ cắt ở §4.3 |
| Vòng đời | Tự đóng khi một bên đổi nội dung. «Không phải mâu thuẫn» được nhớ cho tới khi một bên đổi |
| Lưu trữ | Một bảng `tenant_data.data_conflicts`; cặp phán «không mâu thuẫn» ghi cùng bảng với `status = 'none'` |
| Giao diện | Chỉ dùng popup, không thêm màn hay mục menu. Icon ở màn Kiến thức và màn dự án |

## 3. Hiện trạng

- Chưa có chỗ nào phát hiện mâu thuẫn dữ liệu.
- Van duyệt OCR (`documents.body_cho_duyet`) giữ chữ do model đọc khỏi agent tới khi người dùng duyệt, nhưng không chỉ ra chỗ nào có thể sai.
- `realestate/completeness.py` là luật cứng chặn phát hành khi thiếu trường. Đây không phải khuôn cho việc này, vì cảnh báo không chặn.
- Mọi tài liệu và khối tổng quan dự án đã được chia đoạn và nhúng trong `<tenant>_documents`. Payload có `project_id`, `doc_type`, `record_id`, `text`.
- Portal đã có client LLM (qwen flash qua DashScope, trả JSON) và ghi chi phí vào `billing.usage_events` (`kb/web/llm.py`, `kb/web/usage.py`).
- Frontend có `HopThoai`, `XacNhan` và bộ icon Lucide (`components/icons.tsx`); chưa có toast.

## 4. Luồng dò (backend)

Code đặt ở gói mới `modules/kb/conflicts/`. Job mới `kb_conflict_check`, đăng ký trong `worker/__main__.py::load_handlers()`.

### 4.1 Kích hoạt

| Nguồn | Hành vi |
|---|---|
| Lưu | `handle_index` nạp xong `projects` hoặc `documents` mà có ghi point (không phải «nội dung không đổi») thì xếp `kb_conflict_check` cho bản ghi đó. Phân khu và toà đã quy về nạp lại `projects` nên đi theo đường này. Job đang chờ cho cùng bản ghi thì gộp |
| Nút «Kiểm tra» một dự án | Xếp một job phạm vi dự án |
| Nút «Kiểm tra tất cả dự án» | Xếp một job phạm vi dự án cho mỗi dự án, chạy song song có giới hạn (`max_concurrency`) |

Bản ghi đến từ cổng nạp cũng đi qua `handle_index` nên cũng được dò; cảnh báo được lưu, chỉ không có ai ngồi chờ popup.

### 4.2 Hai loại nguồn

- **Đoạn tài liệu:** point của `documents` (`doc_type` `csbh`, `phap_ly`, `huong_dan`, `khac`) trong `<tenant>_documents`. Dấu tay là băm chữ của đoạn.
- **Khối trường:** các trường của `projects`, `zones`, `buildings` mà khối tổng quan đưa cho agent, đọc thẳng từ Postgres, mỗi trường có tên hiển thị. Trường văn xuôi dài (ví dụ `overview`) cắt ở 3.000 ký tự. Phía trường có hai loại dấu tay:
  - `fields:` + băm cả khối: dùng để nhớ «đoạn này đã được so với khối trường hiện tại». Đổi bất kỳ trường nào thì khối mới phải được so lại.
  - `field:` + băm `bảng.id.tên_trường=giá_trị`: dùng cho cảnh báo. Một đoạn lệch với hai trường thì ra hai cảnh báo, và sửa một trường chỉ đóng cảnh báo của đúng trường đó.

Point `tong_quan` trong Qdrant chỉ dùng làm **mỏ neo tìm kiếm** cho khối trường; LLM luôn nhận khối trường từ Postgres, không nhận chữ của point `tong_quan`. Nhờ vậy đoạn trích phía trường luôn gắn đúng một trường.

### 4.3 Các bước của một lượt dò

Cho bản ghi X trong dự án P:

1. **Dọn:** cảnh báo `open` của P có một dấu tay không còn khớp nguồn hiện tại thì chuyển `resolved`. Lượt quét cả dự án còn xoá các hàng `none` mồ côi.
2. **Lấy đoạn cần dò:**
   - X là tài liệu: các đoạn của X.
   - X là dự án (trường đổi): dùng các point `tong_quan` của P để tìm đoạn tài liệu liên quan (bước 4), phía bên kia là khối trường.
3. **Lọc dữ kiện:** chỉ giữ đoạn có con số, %, ngày, tiền, diện tích, tên công ty hoặc số văn bản (regex).
4. **Tìm ứng viên:** với mỗi đoạn, tìm tối đa 3 point của nguồn khác cùng P (lọc `project_id`, bỏ `record_id` của chính nó, bỏ `kb_file`) có độ tương đồng từ ngưỡng trở lên. Hit là đoạn tài liệu thì thành ứng viên; hit là point `tong_quan` thì đoạn đó cần so với khối trường. Không có hit nào thì bỏ đoạn.
5. **Bỏ cặp đã phán:** cặp (dấu tay đoạn, dấu tay ứng viên) đã có hàng trong `data_conflicts` (mọi `status`) thì bỏ. Với phía trường, cặp để tra là (dấu tay đoạn, `fields:` của khối hiện tại).
6. **Gọi LLM:** gộp 6–8 đoạn mỗi lượt; ứng viên trùng giữa các đoạn chỉ gửi một lần. Đầu prompt cố định: hướng dẫn, rồi khối trường của P. Đầu ra theo §4.4.
7. **Kiểm trích dẫn:** sau khi chuẩn hoá khoảng trắng và chữ hoa, đoạn trích phải nằm trong chữ của nguồn (với trường: trong giá trị trường). Không khớp thì bỏ mục đó và đếm vào log.
8. **Ghi:** trong một giao dịch:
   - đoạn với đoạn: mỗi cặp đã gửi LLM thành một hàng, có mâu thuẫn hợp lệ thì `open`, ngược lại `none`;
   - đoạn với khối trường: một hàng `none` cho cặp (đoạn, `fields:`) để đánh dấu đã phán, cộng một hàng `open` cho mỗi trường có mâu thuẫn hợp lệ, với cặp (đoạn, `field:`).

   Cặp đã có hàng thì không ghi đè (`ON CONFLICT DO NOTHING`), nên `dismissed` không bao giờ bị mở lại.

Sáu chỗ cắt chi phí nằm ở: chỉ dò khi nội dung đổi và gộp lần lưu liên tiếp (§4.1), chỉ dò đoạn của bản ghi vừa đổi (bước 2), nhớ cặp đã phán (bước 5), lọc dữ kiện và lọc theo ngưỡng (bước 3, 4), gộp nhóm (bước 6), và phần đầu prompt cố định để tận dụng cache tiền tố nếu nhà cung cấp hỗ trợ (bước 6).

Tham số ban đầu, chỉnh sau khi đo trên dữ liệu thật: top-k 3, ngưỡng tương đồng 0,75, nhóm 8 đoạn.

### 4.4 Đầu ra LLM

Prompt gắn nhãn `D1…Dn` cho đoạn cần dò, `C1…Cm` cho ứng viên, `field:<tên>` cho trường. LLM trả:

```json
{"conflicts": [
  {"summary": "Đơn vị phát triển khác nhau",
   "left":  {"ref": "D2", "quote": "phát triển bởi Công ty CP ĐT PT hạ tầng Thủ Đức"},
   "right": {"ref": "field:developer", "quote": "Công ty Cổ phần Kinh doanh Bất động sản Noble"}}
]}
```

Prompt yêu cầu:
- chỉ báo hai thông tin cùng nói về một đối tượng mà không thể cùng đúng;
- khác cách viết của cùng một giá trị (4,3 ha và 43.000 m²) không phải mâu thuẫn;
- đoạn trích phải chép nguyên văn;
- giữa hai đoạn, tối đa một mục: nhiều điểm lệch thì gộp vào một dòng tóm tắt (ví dụ «chồng thời hạn, khác mức chiết khấu»). Giữa một đoạn và khối trường, tối đa một mục cho mỗi trường.

## 5. Dữ liệu

Migration mới (số theo head lúc thi công) tạo `tenant_data.data_conflicts` và gọi `control.enforce_tenant_isolation()`. Agent không đọc bảng này nên không cấp quyền gì thêm.

| Cột | Ý nghĩa |
|---|---|
| `id` bigserial, `tenant_id`, `project_code` | |
| `left_hash`, `right_hash` | Dấu tay hai bên, xếp thứ tự để (A, B) và (B, A) là một cặp |
| `status` | `open`, `dismissed`, `resolved`, `none`. CHECK |
| `summary` | Một dòng; rỗng khi `none` |
| `left_entity`, `left_record_id`, `left_field`, `left_label`, `left_quote` | Nguồn trái. `left_field` khác NULL khi nguồn là trường |
| `right_entity`, `right_record_id`, `right_field`, `right_label`, `right_quote` | Nguồn phải |
| `created_at`, `resolved_at`, `dismissed_at`, `dismissed_by` | |

- `UNIQUE (tenant_id, left_hash, right_hash)`: mỗi cặp một hàng.
- Index `(tenant_id, project_code, status)`.
- Mọi câu đọc cảnh báo phải lọc `status`. Hàng `none` chỉ phục vụ bước 5.
- Bước 1 so dấu tay với nguồn hiện tại: dấu tay đoạn tính lại từ chữ của point trong Qdrant, dấu tay `field:` tính lại từ Postgres. Hàng `none` có `fields:` cũ thì bị xoá ở lượt quét cả dự án.

Vòng đời: `open` tự sang `resolved` ở bước 1 khi một bên đổi hoặc mất. `open` sang `dismissed` khi người dùng bấm «Không phải mâu thuẫn». Nội dung đổi sinh dấu tay mới, tức một cặp mới.

## 6. API

Đặt trong `modules/kb/conflicts/router.py`, thêm vào `api/app.py::ROUTERS`. Đọc cần `catalog.read`, quét và bỏ qua cần `catalog.write`; không thêm action.

| Endpoint | Việc |
|---|---|
| `GET /conflicts/summary` | Mọi dự án trừ `__ALL__`: `{projectCode, name, open, checking, failed, checkedAt}`. `checkedAt` là giờ kết thúc của lượt dò gần nhất đã xong (thành công hoặc hỏng), `failed` cho biết lượt đó hỏng; chưa có lượt nào thì `null`. Nuôi số trên icon màn Kiến thức, chữ «N mâu thuẫn» ở từng dòng, và ba nhóm của popup cả workspace |
| `GET /projects/{code}/conflicts` | Cảnh báo `open` của một dự án. Popup cả workspace gọi khi người dùng mở một hàng ra; popup một dự án dùng lại |
| `GET /projects/{code}/conflicts/check?since=` | `{checking, failed, checkedAt, conflicts}`: còn job nạp hoặc dò nào của dự án chưa xong, lượt dò gần nhất đã xong có hỏng không và xong lúc nào, và cảnh báo `open` tạo sau `since` |
| `POST /projects/{code}/conflicts/scan` | Kiểm tra một dự án, trả `202` |
| `POST /conflicts/scan` | Kiểm tra tất cả dự án, trả `202` |
| `POST /conflicts/{id}/dismiss` | Chuyển `open` sang `dismissed` |

Một cảnh báo:

```json
{"id": 41, "summary": "Đơn vị phát triển khác nhau", "createdAt": "2026-10-14T09:12:00Z",
 "left":  {"entity": "documents", "recordId": 286, "field": null,
           "label": "Brochure Noble Palace Long Bien.pdf", "quote": "…"},
 "right": {"entity": "projects", "recordId": 223, "field": "developer",
           "label": "Đơn vị phát triển", "quote": "…"}}
```

Nhật ký: `conflict.scan` (kèm phạm vi) và `conflict.dismiss` vào `core/nhat_ky_ma.py`, rồi chạy `make contracts` và copy `contracts/audit-actions.json` sang frontend.

## 7. Frontend

- **Icon** `mauThuan` (Lucide `TriangleAlert`) trong `components/icons.tsx`, dạng nút chỉ có icon, dùng chung lớp kích thước với nút cạnh nó:
  - màn Kiến thức (`/projects`): trên thanh công cụ, cạnh «Nạp qua API». Số trên icon là tổng `open` của workspace;
  - màn dự án: cạnh chip trạng thái, góc phải trên. Có số khi có cảnh báo; không số khi không có.
  - Đang kiểm tra (cả hai nơi): tam giác giữ nguyên, viền ô nhấp nháy màu nhấn.
- **Dòng dự án** ở màn Kiến thức có chữ nhỏ «N mâu thuẫn» cạnh tên.
- **Một popup dùng chung, ba cách mở:**
  - icon màn Kiến thức: cả workspace, chia ba nhóm theo thứ tự: «Có mâu thuẫn» (mở sẵn; mỗi dự án là một hàng thu gọn — tên, số mâu thuẫn, «Kiểm tra»; mở ra thì tải danh sách), «Chưa kiểm tra (n)» (đóng sẵn; tên kèm «Kiểm tra»), «Không mâu thuẫn (n)» (đóng sẵn; tên kèm giờ kiểm tra lần cuối). Lượt gần nhất hỏng: còn cảnh báo mở thì ở nhóm đầu, không thì ở «Chưa kiểm tra», kèm dòng đỏ «Lần kiểm tra trước bị lỗi». Đầu popup có «Kiểm tra tất cả dự án», qua `XacNhan` trước khi chạy;
  - icon màn dự án: một dự án, nút «Kiểm tra» ở đầu popup; dưới tiêu đề một dòng «Kiểm tra lần cuối 14:32 hôm nay · Không có mâu thuẫn | N mâu thuẫn», hoặc «Chưa kiểm tra lần nào», hoặc «Lần kiểm tra lúc 14:32 bị lỗi»;
  - tự bật ở màn dự án khi có cảnh báo mới (xem «Chờ kết quả»).
- **Một mục:** dòng tóm tắt; hai dòng nguồn (chỗ lấy, link «Mở», đoạn trích, giá trị lệch tô vàng); link «Không phải mâu thuẫn».
- **«Mở»** đóng popup và đưa tới đúng tab của màn dự án (`/pform?code=…&tab=…`): tài liệu → «Tài liệu», trường dự án → «Tổng quan», phân khu → «Phân khu», toà → «Toà». Mở thẳng một tài liệu hoặc trỏ vào đúng ô trường cần thêm tham số mới cho màn dự án; để lần sau.
- Khối trường chỉ gồm các trường `kb/directive/verticals/real_estate.py` khai (ví dụ «Chủ đầu tư», «Quy mô sản phẩm»). Ví dụ «Đơn vị phát triển» ở mockup và §6 chỉ để minh hoạ: `developer` không nằm trong khối trường agent đọc.
- **Chờ kết quả (đổi lúc thi công):** trong lúc màn dự án đang mở, icon gọi `check` định kỳ — 3 giây khi còn job nạp/dò chưa xong, 15 giây khi rảnh; React Query tự dừng khi tab bị ẩn. Có cảnh báo `open` tạo sau mốc đang theo dõi thì popup tự bật với tiêu đề «Có N mâu thuẫn mới», rồi mốc dời lên cảnh báo mới nhất. Lý do đổi: phần lớn tab của màn dự án tự lưu bằng lời gọi API trực tiếp, không qua `useMutation`, nên không có chỗ chung nào để móc «sau khi lưu» mà không sửa từng form. Cách này còn bắt được mâu thuẫn do người khác hoặc cổng nạp tạo ra. Đánh đổi: một truy vấn nhẹ mỗi 15 giây khi màn dự án đang mở.
- **Đang kiểm tra trong popup:** chip nền màu nhấn nhạt có chấm nhấp nháy «Đang kiểm tra» đứng vào chỗ nút «Kiểm tra».
- **Giờ** viết tuyệt đối: «14:32 hôm nay», «09:10 hôm qua», «08/10 16:05».
- **Tự làm mới:** icon màn Kiến thức và cả hai popup hỏi lại `summary` 3 giây một lần khi có dự án đang kiểm tra, 15 giây khi rảnh; popup đang mở tải lại danh sách cảnh báo khi dự án vừa chạy xong.

## 8. Chi phí

Mỗi lượt gọi LLM ghi `billing.usage_events` với `purpose = 'conflict_check'`, **tính tiền khách**: đây là tính năng khách dùng trực tiếp, khác `playbook` là đo chất lượng nội bộ. Nhãn chưa khai vốn đã bị coi là tính tiền (`0943` §3c), nhưng migration ở §5 vẫn khai tường minh `('conflict_check', true, …)` trong `billing.purpose` (`ON CONFLICT DO NOTHING`, cùng khuôn `0969`), để nhãn không nằm trong danh sách chưa phân loại.

## 9. Xử lý lỗi

| Tình huống | Xử lý |
|---|---|
| LLM trả JSON hỏng hoặc bị cắt | Chia đôi nhóm, thử lại một lần; vẫn hỏng thì job `failed` |
| Đoạn trích không khớp nguồn | Bỏ mục, đếm vào log |
| LLM hoặc Qdrant không gọi được | Thử lại theo `RETRY_VIEC_KB`, rồi `failed` |
| Collection chưa tồn tại | Job kết thúc, không làm gì |
| Nguồn bị xoá | Bước 1 của lượt sau đóng cảnh báo; API không trả cảnh báo có nguồn đã mất |

Bước 8 nằm trong một giao dịch nên không có cảnh báo nào được ghi một nửa.

## 10. Kiểm thử

- **Unit (không Docker):** lọc dữ kiện; băm và xếp thứ tự cặp; kiểm trích dẫn; chia nhóm; đọc JSON đầu ra, kể cả JSON hỏng.
- **Module (LLM giả, Postgres và Qdrant thật):**
  - nạp có ghi point thì xếp job dò; nạp báo không đổi thì không;
  - cặp đã có hàng thì không gọi LLM (đếm số lần gọi LLM giả);
  - `dismissed` giữ nguyên sau khi quét lại;
  - sửa một bên thì cảnh báo cũ `resolved`;
  - trích dẫn bịa bị loại;
  - `tests/isolation` xanh với bảng mới.
- **API:** quyền `catalog.read`, `catalog.write`; hình dạng response; `summary` không đếm `none`.
- **Frontend:** ba nhóm và thứ tự của popup cả workspace; dòng «Kiểm tra lần cuối»; chip đang kiểm tra; popup tự làm mới khi lượt kiểm tra xong; ba trạng thái icon; hỏi lại theo chu kỳ dừng đúng điều kiện; popup tự bật sau khi lưu; `XacNhan` trước khi kiểm tra tất cả.
- **Billing:** `conflict_check` đã khai trong `billing.purpose`.

## 11. Rủi ro và đánh đổi

- **LLM báo nhầm.** Giảm bằng bước kiểm trích dẫn, và «Không phải mâu thuẫn» được nhớ. Không chặn gì nên báo nhầm không làm hỏng dữ liệu.
- **Bỏ sót.** Ngưỡng tương đồng và top-k có thể bỏ qua cặp mâu thuẫn mà hai đoạn viết rất khác nhau. Đây là cái giá của việc không so mọi cặp.
- **Trong lúc chưa ai xử lý, agent vẫn dùng cả hai phía.** Đây là quyết định đã chốt (chỉ cảnh báo).
- **Bảng có cả hàng `none`.** Đổi lại không thêm bảng; mọi câu đọc phải lọc `status`.

## 12. Đã chốt khi duyệt spec (2026-10-14)

1. `conflict_check` tính tiền khách (§8).
2. Tham số ở §4.3 (top-k 3, ngưỡng 0,75, nhóm 8) giữ nguyên khi thi công; chỉnh sau khi chạy trên dữ liệu thật.
