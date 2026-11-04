# Phản biện prototype & định hướng sản phẩm — Tenant Portal

> **Ngày:** 2026-07-28 · **Người đọc:** leader / PM / BA
> **Mục đích:** đối chiếu từng màn của prototype với **agent thực tế đang chạy production**, để biết cái gì bán được ngay, cái gì phải xây, cái gì là hư cấu — trước khi phân việc cho dev.
>
> **Nguồn đối chiếu:**
> `reference/santa-hotline-agent` (agent voice+chat, persona Luna, production) ·
> `reference/santa-agent-cms` (CMS đơn-tenant, production) · prototype `Tenant Portal.dc.html`
>
> **Ký hiệu:** ✓ agent làm được ngay · ⚠ cần xây thêm · ✗ hư cấu / chưa tồn tại

---

## 0. Điều cần biết trước khi đọc

**Agent hiện tại làm được gì (tóm gọn):** một agent duy nhất (Luna), phục vụ **pre-sale** — tư vấn dự án + đặt lịch tham quan. Hậu mãi (hợp đồng, thanh toán, sổ hồng, bảo hành) và giá riêng thì **chuyển người thật**. 12 tool: tìm dự án, khám phá dự án theo tiêu chí, kiểm tra còn hàng, tìm căn, gợi ý căn (có phong thuỷ), tổng quan dự án, tài chính dự án, tra tài liệu (RAG), đặt lịch, gửi ảnh/video, cập nhật thông tin khách, chuyển người thật. Kênh: web WebRTC, tổng đài PSTN, LiveKit, chat text, app NobleX.

**Ba điều prototype giả định sai một cách hệ thống:**

1. **Prototype coi "lĩnh vực" là công tắc.** Bật Tài chính là có tool tài chính. Thực tế: mỗi lĩnh vực = tool mới + persona mới + corpus RAG mới + kiến thức nghiệp vụ. Tài chính hiện **không tồn tại một dòng nào**.
2. **Prototype coi việc đo lường là có sẵn.** Hạn mức phút, CSAT, tỉ lệ đến hẹn, độ phủ chủ đề — đều chưa có cơ chế thu. Không phải "query ra", mà là "phải xây chỗ ghi vào trước".
3. **Prototype coi "Tiếp quản" là một cái nút.** Thực tế nó là live-chat: tạm dừng agent, định tuyến tin người↔khách, nối lại. Là subsystem, không phải button.

---

## 1. Tổng quan (Dashboard)

**Mục đích:** người quản lý mở buổi sáng, biết agent đêm qua làm được gì và có gì cần can thiệp.
**Người dùng:** trưởng phòng kinh doanh / chủ sàn.

| Prototype hứa | Thực tế |
|---|---|
| Số hội thoại (30 ngày) | ✓ `chat_conversations` + `hotline_call_summaries`; CMS `StatsPage` đã làm cross-channel |
| Thời lượng gọi TB | ✓ `session_metrics` (Mongo) |
| Tỉ lệ tự xử lý | ✓ **CHỐT (#2):** MVP hiện `Tỉ lệ agent tự xử lý = (tổng − chuyển người) / tổng` — đo được ngay. Chỉ số đầy đủ `Tỉ lệ khách được phục vụ tốt = (NV take care + khách hài lòng) / tổng` để sau, khi có CSAT + tiếp quản trong hệ thống. |
| ~~Lead đủ điều kiện~~ | ✅ **BỎ (#1).** Agent không có khái niệm "lead"; prototype cũng đã bỏ dở một màn Leads (`scraps/leads.png`). Gỡ luôn "Đã tạo lead" ở màn Hội thoại. |
| Khối lượng theo kênh (chart) | ✓ |
| "Agent chưa trả lời được" | ✓ Nguồn thật: `ESCALATE_SIGNAL` + lý do escalate |
| Hội thoại gần đây + cột **Kết quả** | ⚠ Agent không phân loại kết quả. Suy được từ tool đã gọi: `booking.schedule`→Hẹn xem nhà · `send_media`→Gửi tài liệu · `escalate`→Chuyển người thật · không tool nào→Đã giải đáp. Mapping này hợp lý và nên làm — nhưng phải **định nghĩa bảng phân loại** rồi mới code. |
| **"Phút voice đã dùng 98% hạn mức · vượt tính 1.400₫/phút"** | ✗ **Không có metering, không có hạn mức, không có gói.** `session_metrics` là số liệu thô, không phải công-tơ. Widget này là mặt tiền của một subsystem chưa tồn tại. |

**→ GIỮ, bỏ widget hạn mức khỏi MVP.** *Tỉ lệ tự xử lý* và *Lead đủ điều kiện* đã chốt ở §21 (#2, #1). **Còn một định nghĩa chưa chốt: bảng phân loại *Kết quả*** — việc của BA, không phải của dev, và làm sai thì cột đó vô nghĩa. Đề xuất khởi điểm: `Hẹn xem nhà` (`booking.schedule`) · `Gửi tài liệu` (`send_media`) · `Chuyển người thật` (`escalate`) · `Đã giải đáp` (không gọi tool ghi nào) · `Bỏ giữa cuộc` (khách rời trước khi agent trả lời xong).

---

## 2. Agent & Kênh — *màn quan trọng nhất*

**Mục đích:** tenant tự dạy agent nói theo cách của mình, không cần gọi dev.
**Người dùng:** người vận hành CSKH của tenant.

Câu prototype viết ở đầu màn — *"Một agent duy nhất — Chat và Voice chỉ là kênh triển khai, dùng chung persona và knowledge"* — **mô tả chính xác kiến trúc thật**. Người viết prototype hiểu agent.

| Prototype hứa | Thực tế |
|---|---|
| Tên hiển thị | ✓ đã có (`configurable-agent-name`) |
| Vai trò · Lời chào · Độ dài trả lời | ✓ là nội dung `SOUL.md` / `RULES.md` / `config.json` — sửa được |
| **Giọng điệu: 3 preset** (Lịch sự / Thân thiện / Ngắn gọn) | ⚠ Hiện là **sửa markdown tự do**, không có preset. Biến thành 3 lựa chọn = phải **viết và tinh chỉnh 3 biến thể persona**, rồi kiểm thử cả 3. Đây là việc viết prompt, không phải việc code. Và prototype tự tố hệ quả ở màn Chất lượng: *"Giọng ngắn gọn khiến câu trả lời cụt, thiếu điều kiện đi kèm"*. |
| Gợi ý nhanh, tối đa 3 | ✓ **có thật** — `agent/suggestions.py`, tối đa 3 chip. Nhưng **chỉ chat, voice chưa có.** |
| Giọng đọc "Nữ miền Bắc" | ⚠ TTS hiện có **đúng một giọng** (fine-tune `santa-tts`, voice `luna`). Dropdown 1 lựa chọn là dropdown giả. Thêm giọng = thu âm + fine-tune. |
| Tốc độ nói | ⚠ TTS chưa expose tham số speed |
| Ngắt lời | ✓ có thật (VAD barge-in, `SPEAKER_MODE`, floor control đa người nói) |
| "Chuyển người thật sau 2 lần bí" | ⚠ Cap 2 lần **có** trong booking guard, nhưng nằm trong prompt/code, chưa phải tham số cấu hình được |
| **Kỹ năng & hành động** (4 mục) | ✓ **Khớp hoàn hảo** với `[tools].enabled`. Nhưng prototype chỉ vẽ 4, agent có **12 tool đang bật + 3 tool hậu mãi đã viết mà chưa bật**. Cần vẽ lại đủ và đặt tên nghiệp vụ cho từng tool. |
| "Tính khoản vay" | ✗ **Không tồn tại.** Là ví dụ inert trong `tenants/demo_acme/tools/loan.py`. |
| Thử ngay (chat test) | ✓ `/chat` đã có |
| **Rào chắn** (4 mục) | ✓ Cả 4 đều đã có thật: không cam kết giá ngoài dữ liệu (sentinel) · không tư vấn pháp lý/thuế (escalate) · chỉ nói dự án trong workspace (`find_project` + gate `normalize`) · xin phép trước khi lưu SĐT (booking guard). **Đây là phần prototype đúng nhất toàn bộ file.** |
| **Bản nháp v3.3 · 3 thay đổi chưa xuất bản · Xem khác biệt · Xuất bản · Khôi phục** | ✗ **Chưa có gì.** Persona là file `.md` trên đĩa, đọc lúc khởi động. Không draft, không version, không so sánh, không rollback, không nạp lại nóng. |
| "Chạy 24 kiểm thử" trên nháp, so với bản live | ⚠ Bộ eval **có** (`src/eval/`, `make eval-estate`, có LLM judge) nhưng là CLI offline. Không có khái niệm "chạy trên bản nháp", không so nháp↔live. |

**→ Khuyến nghị: GIỮ, tách làm 3 phần và đừng làm cùng lúc.**

1. **Cấu hình nội dung** (tên, vai trò, lời chào, rào chắn, bật/tắt tool) — làm được ngay, giá trị cao nhất. **Vào MVP.**
2. **Versioning + publish + diff + rollback** — phải xây từ đầu. **Sau MVP.** Ở MVP chỉ cần *Lưu → áp dụng*, có xác nhận.
3. **Preset giọng điệu** — là việc viết prompt + kiểm thử, không phải việc dev. Cần người sở hữu nội dung.

---

## 3. Chất lượng

**Mục đích:** trả lời câu "agent có đang tốt lên không, và bản sắp xuất bản có làm tệ đi không".

| Prototype hứa | Thực tế |
|---|---|
| Bộ kiểm thử hồi quy 24 câu | ⚠ Có nền: `src/eval/` (runner, data, report, LLM judge). Cần: chạy như service, chạy trên bản nháp, so nháp↔live. **Đây là hạng mục giá trị cao nhất của màn này.** |
| Lý do chuyển người thật (795 lượt, 4 lý do) | ✓ `escalate` có tham số `department` + `ESCALATE_SIGNAL`. 4 lý do prototype map được. |
| **CSAT 1.204 lượt đánh giá / 6.412 hội thoại** | ✗ **Agent không thu feedback.** Không có cơ chế đánh giá sau hội thoại. Chat thì thêm chip 👍👎 được; **voice thì khó** (hỏi cuối cuộc gọi làm tăng thời lượng, khách cúp máy). |
| "Hội thoại bị đánh giá xấu (18)" | ✗ Phụ thuộc CSAT chưa có |
| "Thêm vào bộ kiểm thử" từ một hội thoại lỗi | ✓ Làm được — data eval là file. **Ý tưởng rất tốt**, nó biến lỗi thành lưới an toàn. |
| "Sửa dữ liệu quỹ căn" / "Bổ sung kiến thức" từ lỗi | ✓ Làm được |

**Chú ý một chi tiết prototype tự viết ra:**

> *"Agent báo căn NT2-1408 còn trống, thực tế đã đặt cọc từ hôm trước — **dữ liệu quỹ căn cập nhật trễ**."*

Đây là ví dụ lỗi hay nhất trong toàn bộ prototype, vì nó chỉ đúng vào rủi ro kiến trúc thật: nếu dữ liệu quỹ căn là **bản sao có độ trễ** thì agent sẽ bán căn đã bán. Bất kỳ thiết kế nào cũng phải trả lời: quỹ căn tươi đến mức nào, và ai chịu trách nhiệm khi agent nói sai.

**→ Khuyến nghị: GIỮ bộ kiểm thử hồi quy (ưu tiên cao). HOÃN phần CSAT** — nó là tiền đề chưa có, và cách thu feedback qua voice cần thiết kế riêng.

---

## 4. Tài liệu (Knowledge Base)

**Mục đích:** nạp kiến thức không nhét vừa bảng — chính sách, quy trình, FAQ.

| Prototype hứa | Thực tế |
|---|---|
| RAG trả lời từ tài liệu | ✓ **Mảng đầu tư mạnh nhất.** Qdrant hybrid (dense e5-large + BM25 sparse, RRF phía server), CMS đã có đường build index (`nbx_rag_build`, `qdrant_core`), có fallback BM25 trên đĩa khi Qdrant lỗi. |
| **Kéo thả PDF, DOCX, XLSX** | ⚠ Corpus hiện là markdown dựng sẵn + `nbx_articles`. **Chưa có pipeline nhận file người dùng upload** → cần parser (PDF/DOCX/XLSX) + chunker + embed + index. Đây là **chức năng cốt lõi để tenant tự vận hành** — không có nó, mỗi khách mới lại cần dev. |
| Crawl web hàng tuần | ✗ Chưa có |
| Chờ duyệt (kiểm duyệt trước khi agent dùng) | ⚠ Chưa có, nhưng nên có — tài liệu sai vào KB là agent nói sai |
| "Agent đã trích dẫn — tài liệu nào đang thực sự trả lời khách" | ✓ `kb_search` trả hit có id chunk → log + tổng hợp được. **Ý tưởng tốt**: nó cho biết tài liệu nào vô dụng. |
| "Không tìm được tài liệu" | ✓ kb_search rỗng → log |
| Độ phủ theo 5 chủ đề (%) | ⚠ Cần **bảng phân loại chủ đề** — chưa có. Việc của BA. |

**→ Khuyến nghị: GIỮ. Upload file là hạng mục ưu tiên cao nhất sau cấu hình agent** — nó quyết định tenant có tự chủ được hay không. Crawl web: hoãn.

---

## 5. Cần bổ sung (Knowledge Gaps) — *tỉ lệ giá trị/công sức cao nhất*

**Mục đích:** biến câu hỏi agent trả lời không được thành việc cụ thể phải làm.

Prototype phân 12 lỗ hổng thành **3 loại theo chỗ phải sửa**:

```
Thiếu tài liệu       → nạp PDF/DOCX ở màn Tài liệu
Thiếu trường dữ liệu → bổ sung giá/hướng cho 48 căn ở màn Bất động sản
Ngoài phạm vi        → theo rào chắn, luôn chuyển người thật
```

**Đây là insight đúng và tôi đề nghị giữ nguyên.** Nó không phân loại theo chủ đề (vô dụng cho hành động) mà theo **ai phải làm gì ở đâu**.

| Prototype hứa | Thực tế |
|---|---|
| Nguồn dữ liệu lỗ hổng | ✓ Thật: `ESCALATE_SIGNAL` + `kb_search` rỗng + lý do escalate |
| Gom 41 lần hỏi thành 12 câu hỏi | ⚠ Cần gom nhóm theo ngữ nghĩa — làm được (đã có embedder), không khó |
| Tự phân 3 loại | ⚠ Heuristic được: `kb_search` rỗng→thiếu tài liệu · `ESCALATE_SIGNAL` từ tool dữ liệu→thiếu trường · chạm rào chắn→ngoài phạm vi. Cần **log đủ chi tiết** để phân được. |
| "32 qua chat, 9 qua voice" | ✓ Có kênh trong session |
| "Dạy agent" — nhập câu trả lời, lưu vào KB | ✓ Làm được |
| "Thử lại" | ✓ Làm được (dùng lại kiểu sandbox của semcache) |
| "Đóng 10 lỗ hổng đầu → tự xử lý +?%" | ⚠ Con số dự báo — cần cẩn thận, hứa sai thì mất tin |

**→ Khuyến nghị: GIỮ NGUYÊN, vào MVP.** Đây là màn khách hàng cảm nhận được giá trị rõ nhất: tuần này agent kém, làm 5 việc, tuần sau agent tốt lên. Nó cũng là vòng phản hồi giữ khách.

---

## 6. Hội thoại

**Mục đích:** xem lại agent đã nói gì, và can thiệp khi cần.

| Prototype hứa | Thực tế |
|---|---|
| Chat log + call log cùng dòng thời gian | ✓ Có cả hai nguồn; CMS đã merge 2 kênh ở vài tab |
| Hợp nhất theo **khách** | ⚠ **Cầu nối yếu, đã ghi thành văn trong `cms_db_state.md`:** `chat_conversations` **không có số điện thoại**, phải nối qua `chat_bookings.phone_number`. Khách **chỉ chat mà chưa đặt lịch → không nối được, không xuất hiện trong hồ sơ 360°.** Muốn chuẩn thì chat agent phải ghi phone vào conversation. Đây là việc phải sửa ở agent, không phải ở portal. |
| **"Tiếp quản" — nhắn trực tiếp cho khách** | ✗ **Chưa có gì, và bị đánh giá thấp nhất trong prototype.** Agent `escalate` = gọi tool, ghi record — nhưng không có kênh để người thật nhắn tiếp *vào cùng cuộc hội thoại*. Cần: tạm dừng agent cho session đó, định tuyến tin nhắn người→khách và khách→người, nối lại hoặc đóng. Đây là **live-chat**, một hạng mục riêng cỡ vài tuần, không phải một cái nút. |
| "12 hội thoại đang chờ người thật" | ✓ escalate record đếm được |
| "Đã tạo lead" | ⚠ Lại là khái niệm lead chưa định nghĩa (xem màn 1) |

**→ Khuyến nghị: GIỮ phần xem log vào MVP. TÁCH "Tiếp quản" thành hạng mục riêng, sau MVP.** Ở MVP: khi agent chuyển người thật thì thông báo + hiện SĐT khách, để nhân viên gọi/nhắn **ngoài hệ thống**. Không đẹp, nhưng dùng được ngay và không tốn vài tuần.

---

## 7. Lịch hẹn

| Prototype hứa | Thực tế |
|---|---|
| Lịch do agent đặt | ✓ tool `booking` 4 hành động → `hotline_bookings_flat` + `chat_bookings`; CMS đã merge 2 kênh, có badge kênh + filter |
| Đổi lịch | ✓ `booking(action=modify)` — đã sửa bug xoá trắng ngày/giờ khi chỉ đổi tên |
| Xác nhận | ⚠ Cần trạng thái xác nhận — chưa có |
| **Phân công phụ trách** | ⚠ Chưa có `assignee`. Phải thêm. |
| **Tỉ lệ đến hẹn** | ⚠ Cần trạng thái "đã đến / không đến" — **phải người cập nhật tay**, agent không biết. Nếu không ai cập nhật thì chỉ số này luôn rỗng. |

Ghi chú nhỏ nhưng có ý nghĩa: prototype ghi tool là `create_appointment`, agent gọi là `booking(action=schedule)`. Prototype được vẽ **trước khi xem agent**.

**→ Khuyến nghị: GIỮ, vào MVP.** Bổ sung `assignee` + trạng thái. Chỉ số *tỉ lệ đến hẹn* chỉ đưa lên khi đã chốt ai cập nhật nó.

---

## 8. Lĩnh vực (Domains)

| Prototype hứa | Thực tế |
|---|---|
| Bất động sản — 2 bộ dữ liệu, 681 bản ghi | ✓ Thật |
| Tài chính — 3 bộ dữ liệu, "mới bật, chưa có dữ liệu" | ✗ **Không tồn tại.** Không tool, không provider, không persona, không corpus. |
| Bán lẻ · Ô tô — "Bật lĩnh vực" | ✗ Không tồn tại |
| **"Tự định nghĩa — tự khai trường"** | ✗ Là một subsystem riêng (sinh schema + form + tool tự động). Đã quyết định **bỏ khỏi MVP**. |

Điều prototype nói **đúng**: *"Bật một lĩnh vực là có sẵn schema, form nhập và tool tương ứng"* — đó chính là mô hình agent đã xây (tenant bundle + provider + tool riêng theo tenant). Sai ở chỗ nó vẽ 4 lĩnh vực như thể đã có sẵn.

**→ Khuyến nghị: SỬA.** MVP chỉ có **Bất động sản**. Bỏ hẳn "Tự định nghĩa". Bán lẻ/Ô tô: xoá hoặc để dạng "liên hệ chúng tôi". **Tài chính phải được coi là một dự án riêng**, không phải một cái công tắc — xem màn 12.

---

## 9. Dự án / Quỹ căn

| Prototype hứa | Thực tế |
|---|---|
| Danh sách dự án + quỹ căn, filter | ✓ Dữ liệu khớp `nbx_projects` / `nbx_units` |
| Cột **"Agent dùng"** (bật/tắt từng dự án) | ⚠ Làm được, nhưng agent hiện **không có cơ chế tắt dự án** — `discover_projects` trả tất cả. Cần thêm filter ở tầng tool. |
| **"48 căn chưa đủ dữ liệu cho agent"** | ✓ Làm được, **giá trị cao**: nó trả lời câu "tại sao agent trả lời kém" bằng một việc cụ thể. Cần định nghĩa "đủ dữ liệu" = những trường nào bắt buộc. |

**→ Khuyến nghị: GIỮ, vào MVP.** Cảnh báo thiếu dữ liệu là chi tiết nhỏ nhưng đúng tinh thần sản phẩm.

---

## 10–11. Form Dự án / Form Quỹ căn

Hai màn này **1:1 với schema thật** (`name`/`slug`/`type`/`area_region`/`is_hot`/`sort_hot`/`overview`; `code`/`price`/`price_tts`/`area`/`area_build`/`fund_type`…). Người vẽ prototype đã đọc database.

| Điểm | Nhận xét |
|---|---|
| Trường khớp DB | ✓ |
| **Trường `GATED`** (`commission`, `bank_support`, `csbh_full`) | ⚠ Nhu cầu **thật và quan trọng**: có trường không được để agent nói ra (hoa hồng!). Agent hiện chưa có khái niệm này, nhưng cơ chế extras spec đã gần. **Đây là yêu cầu bảo mật thương mại, không phải tính năng phụ.** |
| "sửa hàng loạt tại đây **ghi đè toàn bộ danh sách**" | ⚠ **Nguy hiểm.** Phải có xem trước + xác nhận + hiện số dòng sẽ xoá. Không thì một lần import sai là mất quỹ căn. |
| Đơn vị giá "tỷ" | ⚠ Đổi đơn vị phải làm ở **biên nhập**, lưu VND. Agent đã từng phải sửa đúng bug này. |

**→ Khuyến nghị: GIỮ, vào MVP — nhưng đừng đánh giá thấp.** Đây là **một CMS đầy đủ**, không phải hai cái form. Riêng hai màn này có thể chiếm 1/4 công sức MVP.

---

## 12. Tài chính

| Prototype hứa | Thực tế |
|---|---|
| 3 bộ dữ liệu: Sản phẩm vay · Biểu lãi suất · Gói bảo hiểm | ✗ Không tồn tại |
| "Nhập tay, tải CSV, hoặc nối API core banking" | ✗ Không tồn tại |
| Agent trả lời câu hỏi tài chính | ✗ **Không có tool, không có persona, không có corpus.** |

Câu prototype viết **đúng và nên giữ làm nguyên tắc**:

> *"Trước khi có bản ghi, agent sẽ **từ chối trả lời** câu hỏi thuộc lĩnh vực này **thay vì suy đoán**."*

**→ Khuyến nghị: HOÃN KHỎI MVP.** Đây là vertical thứ hai: cần tool mới, persona mới, corpus mới, và **kiến thức nghiệp vụ tài chính** (lãi suất thay đổi theo thời gian, điều kiện vay, quy định) mà đội hiện tại chưa có. Rủi ro lớn nhất không phải kỹ thuật — là **bán nó trước khi có nó**. Nếu câu chuyện "SaaS đa lĩnh vực" cần thiết cho việc gọi vốn/bán hàng, hãy nói dưới dạng lộ trình, đừng để nó thành công tắc trong UI.

---

## 13. Tích hợp & API

| Prototype hứa | Thực tế |
|---|---|
| CRM đồng bộ 2 chiều + cấu hình ánh xạ trường | ✗ Chưa có. Ánh xạ trường tuỳ biến là hạng mục riêng. |
| **Kênh chat Zalo OA** (2.841 hội thoại, "OA đã xác thực") | ✗ **Chưa có kênh Zalo.** Agent có WebRTC / tổng đài / LiveKit / chat text / app NobleX. |
| Lịch hẹn → lịch 4 nhân viên | ✗ Chưa có, nhưng dễ |
| Đẩy lead sang Sales Cloud | ✗ Chưa có |
| Báo cáo → sheet mỗi giờ | ✗ Chưa có |
| Khoá API (120 lượt/phút) | ✗ Hiện là **một khoá tĩnh** (`NOBLE_APP_API_KEY`), không quản lý được, không giới hạn tốc độ theo khoá |
| Webhook (thử lại 5 lần, gửi lại) | ✗ Chưa có |

**→ CHỐT (#3): MVP chỉ có khoá API + tích hợp qua API, đúng như `santa-hotline-agent` đang làm.**

Tenant tự tích hợp frontend của họ. Dùng lại khuôn đã có sẵn — `server/app_session.py`: `POST /api/v1/app/session` xác thực bằng header khoá, cấp `session_id` + connect-token, client nối WebSocket. Việc cần thêm: **quản lý nhiều khoá theo tenant** (hiện là một khoá tĩnh toàn hệ thống), thu hồi khoá, giới hạn tốc độ theo khoá.

**Zalo OA ra khỏi MVP.** CRM 2 chiều, Sales Cloud, báo cáo tự động, webhook: sau. Ghi lại để không mất: nếu về sau xác định Zalo là kênh bán chính ở VN thì nó là **kênh thứ nhất**, không phải mục tích hợp phụ — lúc đó phải xếp lại ưu tiên, không nhét vào cuối danh sách.

---

## 14. Users & Phân quyền

| Prototype hứa | Thực tế |
|---|---|
| Đăng nhập, thành viên, vai trò | ✓ CMS đã có JWT + refresh token luân chuyển + RBAC + `audit_log` (giữ 365 ngày) |
| **5 vai trò × 5 quyền** | ⚠ CMS có **4 vai trò** (`viewer < sales < manager < admin`). Cần map lại — và 5 quyền của prototype (xem dashboard / sửa dự án / tiếp quản / cấu hình agent / gói cước) là **cách chia đúng hơn** so với 4 vai trò tuyến tính hiện tại. |
| Tạo vai trò tùy chỉnh | ✗ Chưa có |
| 2FA bắt buộc | ✗ Chưa có |
| SSO ("Nâng gói để bật") | ✗ Chưa có |
| Quản lý phiên / 11 thiết bị / đăng xuất tất cả | ✗ Chưa có |
| Tên miền được mời | ✗ Chưa có |
| *"NobleX không truy cập được dữ liệu tenant"* | ⚠ **Lời hứa quan trọng nhất trên màn này.** Nếu định giữ, phải thiết kế từ đầu: admin nền tảng có quyền vận hành nhưng **không** đọc dữ liệu tenant; hỗ trợ khách phải qua cấp quyền tạm thời có ghi log. Nới "cho tiện" bây giờ thì sau sửa rất đau. |

**→ Khuyến nghị: MVP dùng lại mô hình CMS** (JWT + vai trò), nhưng **chia quyền theo 5 nhóm của prototype** thay vì 4 vai trò tuyến tính. Bỏ 2FA / SSO / vai trò tùy chỉnh / quản lý thiết bị / domain allowlist khỏi MVP.

---

## 15. Gói cước & Usage

| Prototype hứa | Thực tế |
|---|---|
| Gói Growth 12.000.000₫/tháng, chu kỳ, tự gia hạn | ✗ Chưa có |
| Thanh usage (4.108/7.000 hội thoại…) | ✗ **Chưa có công-tơ** |
| Vượt hạn mức tính thêm | ✗ Chưa có |
| Chuyển trả năm −15%, huỷ gia hạn | ✗ Chưa có |
| Tải báo cáo usage | ✗ Chưa có |

**→ CHỐT (#7): bán theo token. MVP *ghi nhận* token, *chưa bán*.**

Giao diện gói cước, hạn mức, chặn khi vượt, cổng thanh toán: **hoãn**. Vài khách đầu tiên xử lý bằng hợp đồng ngoài hệ thống + hoá đơn tay.

Nhưng **một việc phải vào MVP**: ghi nhận token theo tenant / theo hội thoại / theo mục đích gọi (trả lời khách · tóm tắt · gợi ý nhanh · embedding). Rẻ — `StreamingClient` đã thấy usage trả về từ provider. Thiếu nó thì sau này không có dữ liệu quá khứ để đối chiếu hoá đơn, và retrofit số liệu đã mất là không thể.

Cảnh báo về việc dùng token làm đơn vị bán ra — nhất là chỗ voice bị tính thiếu: xem §21.2.

---

## 16–18. Ba màn định nghĩa lại từ nghiệp vụ

Bản tải về của file thiết kế không có markup ba màn này (CSS thì còn, nên state model đầy đủ). Ba màn dưới đây được **định nghĩa lại từ nghiệp vụ** — và đó là cách đúng: file thiết kế là brainstorm, không phải yêu cầu (quyết định W1). Không đợi thiết kế để dựng ba màn này.

### 16. Nhật ký & Dữ liệu (audit) — CSS cho thấy 3 tab: `log · privacy · requests`

**Đề xuất — và đây không phải nice-to-have ở Việt Nam:**

- **Nhật ký:** ai làm gì lúc nào (sửa persona, xuất bản, xoá quỹ căn, xuất dữ liệu). ✓ CMS đã có `audit_log` giữ 365 ngày — dùng lại được.
- **Quyền riêng tư:** giữ ghi âm cuộc gọi bao lâu · có ẩn số điện thoại trong log không · giữ nội dung hội thoại bao lâu. Agent đang lưu ghi âm, transcript, và **hồ sơ khách tích luỹ theo số điện thoại** (`hotline_user_snapshots`) — tức đang xử lý dữ liệu cá nhân.
- **Yêu cầu của khách:** khách yêu cầu xem / xoá dữ liệu của mình. Cần tìm theo SĐT rồi xoá xuyên các nơi (Redis, Mongo, snapshot, transcript, ghi âm).

**→ CHỐT (#6): thời gian lưu mặc định 6 tháng, tenant tự đặt được.** Áp cho ghi âm · transcript · hồ sơ khách tích luỹ (`hotline_user_snapshots`).

Tab **Nhật ký** vào MVP (rẻ, `audit_log` đã có nền). Tab **Quyền riêng tư** vào MVP ở mức tối thiểu: đúng một thiết lập *thời gian lưu*, mặc định 6 tháng, cộng job xoá dữ liệu quá hạn. Tab **Yêu cầu của khách** (tìm theo SĐT → xuất / xoá xuyên Redis + Mongo + snapshot + transcript + ghi âm): **sau MVP**, nhưng phải thiết kế chỗ lưu ngay từ đầu sao cho xoá được — nếu dữ liệu khách rải rác không truy được theo SĐT thì sau này không xoá nổi.

### 17. Cài đặt — CSS cho thấy: công tắc ghi âm (`data-rec` on/off) + chính sách tràn (`data-ovg` auto|stop)

- **Ghi âm cuộc gọi bật/tắt:** thật và cần — ảnh hưởng cả tuân thủ lẫn chi phí lưu trữ. **MVP.**
- **Thời gian lưu dữ liệu** (mặc định 6 tháng, sửa được) — theo quyết định #6. **MVP.**
- **Chính sách khi vượt hạn mức** (tự tính thêm / dừng phục vụ): phụ thuộc metering → **hoãn cùng màn 15**.
- Thêm: múi giờ, giờ làm việc (agent đã có `working_hours` cho gọi ra), ngôn ngữ mặc định.

### 18. Onboarding — CSS cho thấy wizard 4 bước (`data-wstep` 1→4)

**Đề xuất 4 bước, xếp theo nguyên tắc "chat thử được càng sớm càng tốt":**

```
Bước 1  Tạo workspace + chọn lĩnh vực (MVP: chỉ Bất động sản)
Bước 2  Nạp dữ liệu — import file, hoặc nhập 1 dự án mẫu để chạy thử
Bước 3  Cấu hình agent (tên, giọng điệu, rào chắn) → CHAT THỬ NGAY   ← bước "aha"
Bước 4  Bật kênh + mời thành viên
```

Bước 3 là chỗ khách hàng lần đầu thấy agent nói bằng dữ liệu của **chính họ**. Mọi bước trước nó là chi phí, mọi bước sau nó là mở rộng. Nếu phải cắt, cắt bước 4 chứ đừng đẩy bước 3 xuống sau.

**→ Khuyến nghị: vào MVP.** Đây là màn quyết định khách có dùng tiếp hay không.

---

## 19. Bảng tổng hợp

| # | Màn | Agent có sẵn | Khuyến nghị | MVP? |
|---|---|---|---|---|
| 1 | Tổng quan | Phần lớn | **#1** bỏ KPI lead · **#2** đổi nhãn chỉ số · bỏ widget hạn mức | ✅ |
| 2 | Agent & Kênh | Cấu hình ✓ · versioning ✗ | Giữ, tách 3 phần | ✅ (không versioning) |
| 3 | Chất lượng | eval ⚠ · CSAT ✗ | Giữ regression, hoãn CSAT | ⏸ một phần |
| 4 | Tài liệu | RAG ✓ · upload ✗ | Giữ, ưu tiên upload file | ✅ |
| 5 | Cần bổ sung | Nguồn ✓ | **Giữ nguyên** | ✅ |
| 6 | Hội thoại | Log ✓ · tiếp quản ✗ | Giữ log, tách live-chat | ✅ (chỉ xem) |
| 7 | Lịch hẹn | ✓ | Giữ, thêm phân công | ✅ |
| 8 | Lĩnh vực | Chỉ BĐS | Sửa: chỉ BĐS, bỏ tự-định-nghĩa | ✅ (thu gọn) |
| 9 | Dự án/Quỹ căn | ✓ | Giữ | ✅ |
| 10–11 | Hai form | Schema ✓ | Giữ — **khối lượng lớn** | ✅ |
| 12 | Tài chính | ✗ hoàn toàn | **Hoãn** — vertical thứ 2 | ❌ |
| 13 | Tích hợp & API | app_session ✓ | **#3** Chỉ khoá API qua API. Zalo ra khỏi MVP | ✅ (tối thiểu) |
| 14 | Users | Auth ✓ | Dùng lại CMS, chia quyền theo 5 nhóm | ✅ (thu gọn) |
| 15 | Gói cước | ✗ hoàn toàn | **#7** Bán theo token. MVP chỉ *ghi nhận*, chưa bán | ⏸ chỉ ghi nhận |
| 16 | Nhật ký & Dữ liệu | audit_log ✓ | **#6** Nhật ký + thời gian lưu 6 tháng vào MVP; yêu cầu của khách sau | ⏸ một phần |
| 17 | Cài đặt | — | **#6** Ghi âm + thời gian lưu vào MVP; chính sách tràn hoãn | ⏸ một phần |
| 18 | Onboarding | — | **Vào MVP** — quyết định giữ khách | ✅ |

---

## 20. Đề xuất phạm vi MVP

**Nguyên tắc:** MVP là *"một sàn BĐS chưa từng có hệ thống, tự đưa agent lên chạy được trong một buổi, và tự làm agent tốt lên mỗi tuần"* — không phải "18 màn của prototype nhưng sơ sài".

### Trong MVP (sau 7 quyết định §21)

1. **Onboarding 4 bước** + workspace + Users (dùng lại auth CMS, chia quyền theo 5 nhóm). Admin nền tảng **không** đọc `tenant_data` (#5)
2. **Dữ liệu BĐS**: Dự án + Quỹ căn (CRUD + import file có xem trước) + cảnh báo thiếu dữ liệu + gate trường `GATED` + **mốc `cập nhật lúc` mỗi bản ghi** (#4)
3. **Agent & Kênh**: cấu hình persona + bật/tắt tool + rào chắn + chat thử. *Lưu → áp dụng*, chưa versioning. **Thêm rào chắn hedge theo độ tươi dữ liệu** (§21.1)
4. **Tài liệu**: upload PDF/DOCX → RAG
5. **Hội thoại + Lịch hẹn**: xem, phân công. Chuyển người thật = thông báo + SĐT, xử lý ngoài hệ thống
6. **Cần bổ sung**: vòng phản hồi 3 loại
7. **Tổng quan**: KPI cơ bản. `Tỉ lệ agent tự xử lý = (tổng − chuyển người)/tổng` (#2). **Không có** KPI lead (#1)
8. **Kết nối**: khoá API theo tenant + thu hồi + giới hạn tốc độ (#3)
9. **Nhật ký** + công tắc ghi âm + **thiết lập thời gian lưu, mặc định 6 tháng** + job xoá quá hạn (#6)
10. **Ghi nhận token** theo tenant / hội thoại / mục đích gọi — chỉ ghi, chưa bán (#7)

### Ngay sau MVP, theo thứ tự tôi đề nghị

1. **Versioning + publish + rollback** cho persona — cần ngay khi có khách thứ hai
2. **Bộ kiểm thử hồi quy** — cần ngay khi bắt đầu sửa persona thường xuyên
3. **CSAT** (chat trước, voice cần thiết kế riêng) — mở đường cho chỉ số đầy đủ ở #2
4. **Tiếp quản (live-chat)** — cần khi khách phàn nàn "chuyển người thật rồi không ai nói gì". Cùng với CSAT, nó hoàn tất công thức `Tỉ lệ khách được phục vụ tốt`
5. **Yêu cầu của khách** (xuất / xoá dữ liệu theo SĐT) — hoàn tất tuân thủ Nghị định 13
6. **Webhook + CRM** · **Zalo OA** (xếp lại ưu tiên nếu xác định là kênh bán chính)
7. **Metering + gói cước + thanh toán** — dựa trên dữ liệu token đã ghi từ MVP
8. **Vertical Tài chính** — dự án riêng
9. **Đồng bộ quỹ căn theo giờ** — trả nợ quyết định #4, gỡ rào chắn hedge

---

## 21. Bảy quyết định đã chốt (2026-07-28)

| # | Câu hỏi | Quyết định | Hệ quả |
|---|---|---|---|
| 1 | "Lead đủ điều kiện" | **BỎ hẳn** | Gỡ KPI khỏi Tổng quan · gỡ "Đã tạo lead" khỏi Hội thoại · không có màn Leads |
| 2 | Tỉ lệ tự xử lý | **MVP: chỉ số thay thế**, đổi nhãn cho đúng | MVP: `Tỉ lệ agent tự xử lý = (tổng − chuyển người) / tổng`. Sau MVP: `Tỉ lệ khách được phục vụ tốt = (NV take care + khách hài lòng) / tổng` — cần CSAT + tiếp quản trong hệ thống |
| 3 | Kênh kết nối | **Chỉ API key qua API**, như `santa-hotline-agent` hiện tại | **Zalo OA ra khỏi MVP.** Tenant tự tích hợp frontend của họ. Dùng lại khuôn `app_session.py` (`POST /api/v1/app/session` + header khoá) — đã có sẵn |
| 4 | Độ tươi quỹ căn | **Tạm 6 tháng**, có ý thức là nợ | Bắt buộc kèm rào chắn hedge (xem dưới) |
| 5 | NobleX không đọc dữ liệu tenant | **CÓ, giữ đúng** | Thiết kế từ đầu: admin nền tảng có quyền vận hành, **không** đọc `tenant_data`. Hỗ trợ khách qua cấp quyền tạm thời có ghi log |
| 6 | Lưu dữ liệu bao lâu | **Mặc định 6 tháng, tenant tự đặt được** | Áp cho: ghi âm · transcript · hồ sơ khách tích luỹ. Vào màn Cài đặt, MVP |
| 7 | Đơn vị bán | **Theo token**, như dịch vụ LLM lớn | Xem cảnh báo dưới. MVP: **ghi nhận token, chưa bán** |

### 21.1 Rào chắn bắt buộc kèm quyết định #4

6 tháng là ngưỡng chấp nhận được cho **thông tin dự án** (tiện ích, pháp lý, tổng quan). Nó **không** chấp nhận được cho **trạng thái căn** — agent sẽ nói "còn hàng" về căn đã bán, đúng bug prototype tự nêu (`NT2-1408`).

Vì đây là nợ có ý thức, phải trả bằng rào chắn ở tầng agent:

| Loại dữ liệu | Ngưỡng | Quá ngưỡng thì agent làm gì |
|---|---|---|
| **Trạng thái căn** (còn / đã bán / lock) | giờ | **CẤM khẳng định còn hàng.** Nói *"cần xác nhận lại với chuyên viên"* |
| Giá, chính sách bán hàng | ngày | Nói kèm mốc thời gian cập nhật |
| Thông tin dự án, tiện ích, pháp lý | 6 tháng | Trả lời bình thường |

Mỗi bản ghi cần mốc `cập nhật lúc`; tool trả về kèm mốc đó; rào chắn trong `RULES.md` quyết định giọng trả lời. Rẻ, và nó biến lỗi "bán căn đã bán" thành câu trả lời thận trọng.

### 21.2 Cảnh báo kèm quyết định #7

Token hợp làm **cơ sở tính giá nội bộ**, rủi ro làm **đơn vị bán ra**:

1. **Người mua không hiểu token.** Khách là trưởng phòng kinh doanh sàn BĐS; "1 triệu token" không giúp họ dự toán.
2. **Voice bị tính thiếu nghiêm trọng.** Chi phí voice nằm ở **STT + TTS GPU + phút PSTN**, không ở token LLM. Cuộc gọi 20 phút có thể ít token nhưng đắt về GPU và phút tổng đài. Agent tự chạy TTS (`santa-tts`) và STT — hai khoản đó scale theo **giây audio**.
3. **Lời gọi LLM khách không thấy mà vẫn tốn:** tóm tắt hội thoại, sinh gợi ý nhanh, embedding RAG, (nếu bật) semcache. Phải quyết có tính hay không.

**Đề xuất:** token làm cơ sở giá nội bộ; giá bán ra quy về đơn vị khách hiểu (hội thoại + phút voice). **Ghi nhận token/tenant/hội thoại từ ngày đầu** — rẻ (LLM client đã thấy usage), nhưng thiếu nó thì retrofit rất đau. Giao diện gói cước vẫn hoãn.

---

## 22. Phụ lục — vị trí của file thiết kế trong quy trình

**Quyết định W1 (chốt 2026-07-28): file thiết kế gốc là brainstorm, không phải yêu cầu.**

Nó trả lời câu *"sản phẩm nên giải quyết vấn đề gì cho ai"* — và trả lời tốt: 18 màn của nó là một bản đồ vấn đề tốt, phần rào chắn agent thì chính xác tới mức đáng ngạc nhiên. Nó **không** trả lời câu *"xây cái gì"*, vì được vẽ trước khi đọc code.

Vì vậy toàn bộ tài liệu này — đối chiếu từng màn với agent thật — **không phải danh sách nợ phải trả cho thiết kế.** Mỗi chỗ lệch là một trong hai thứ:

- **việc phải xây** → vào sổ quyết định rồi làm, hoặc
- **ý đã bỏ** → xoá khỏi prototype, ghi lý do vào `tools/build_prototype_mvp.py`.

Không có lựa chọn thứ ba là "sửa thực tế cho khớp thiết kế".

Hệ quả cho người thực thi: **không ai phải đi xin ảnh thiết kế để xác nhận một màn.** Bản tải về không có markup ba màn `audit`/`settings`/`onboarding` (CSS thì còn, nên state model đầy đủ) — ba màn đó được dựng từ nghiệp vụ, và đó là cách đúng. Yêu cầu được quyết định bằng code và thực tế triển khai, rồi ghi vào sổ quyết định.
