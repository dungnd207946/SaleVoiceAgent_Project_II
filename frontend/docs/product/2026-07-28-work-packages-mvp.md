# MVP — Work packages để phân việc

> **Ngày:** 2026-07-28 · **Người dùng tài liệu:** leader / PM khi phân việc
> **Dựa trên:** `2026-07-28-phan-bien-prototype-va-dinh-huong-san-pham.md` (§20 phạm vi MVP, §21 bảy quyết định)
> **Kỹ thuật:** `docs/superpowers/specs/2026-07-28-tenant-portal-control-plane-design.md` — **đọc kèm §2.1 dưới**, spec đó viết trước khi định hướng sản phẩm nên có phần cần xem lại.

---

## 1. Trước khi phân việc — bốn việc không phải của dev

Bốn việc này **chặn** hoặc **làm hỏng** công việc của dev nếu chưa có. Không ai trong đội dev tự làm được. **N4 đã đóng 29/7** — còn ba, và cả ba vẫn chưa có tên người và ngày.

| # | Việc | Ai làm | Chặn gói nào |
|---|---|---|---|
| **N1** | **Bảng phân loại *Kết quả* hội thoại** — chốt danh sách và định nghĩa từng loại | BA | E (Tổng quan) |
| **N2** | **Định nghĩa "đủ dữ liệu cho agent"** — trường nào bắt buộc trên Dự án / Quỹ căn | BA + sales | B (Dữ liệu BĐS) |
| **N3** | **Viết 3 biến thể persona** cho preset Giọng điệu + rào chắn hedge theo độ tươi | người sở hữu nội dung | C (Agent Studio) |
| ~~**N4**~~ | ~~**Chốt nhóm quyền** ứng với vai trò nào~~ · **✅ XONG 29/7 — đặc tả `PQ_01`** | — | ~~A · F~~ hết chặn |

**N3 là việc bị đánh giá thấp nhất.** Nó không phải code — là viết và tinh chỉnh prompt rồi kiểm thử cả 3 biến thể. Nếu để dev tự viết, kết quả sẽ đúng như prototype tự tố: *"Giọng ngắn gọn khiến câu trả lời cụt, thiếu điều kiện đi kèm"*.

---

## 2. Bản đồ gói việc & phụ thuộc

```
        ┌──────────────────────────────────────────────┐
        │  A · NỀN TẢNG                                │
        │  DB đa-tenant · auth · workspace · quyền     │
        │  admin nền tảng KHÔNG đọc tenant_data (#5)   │
        └───┬──────────┬──────────┬──────────┬─────────┘
            │          │          │          │
    ┌───────▼──┐  ┌────▼─────┐  ┌─▼───────┐ ┌▼──────────┐
    │ B · DỮ   │  │ C · AGENT│  │ D · TÀI │ │ F · KẾT   │
    │ LIỆU BĐS │  │  STUDIO  │  │ LIỆU KB │ │ NỐI + LƯU │
    │ CRUD+    │  │ persona  │  │ upload  │ │ khoá API  │
    │ import   │  │ tool·rào │  │ →RAG    │ │ ghi âm·6th│
    │ mốc thời │  │ chat thử │  │         │ │ token log │
    └───┬──────┘  └────┬─────┘  └────┬────┘ └───────────┘
        │              │             │
        │        ┌─────▼─────────────▼──┐
        │        │  G · AGENT SIDE      │
        │        │  đọc DB portal       │
        │        │  rào chắn hedge (#4) │
        │        │  ghi nhận token (#7) │
        │        └─────┬────────────────┘
        │              │
    ┌───▼──────────────▼──────┐   ┌──────────────────┐
    │ E · VẬN HÀNH            │   │ H · ONBOARDING   │
    │ Tổng quan · Hội thoại   │   │ wizard 4 bước    │
    │ Lịch hẹn · Cần bổ sung  │   │ (làm SAU B,C,D)  │
    └─────────────────────────┘   └──────────────────┘
```

**Đường găng: A → C → G.** Cho tới khi agent đọc được dữ liệu từ portal và cấu hình được persona, không có gì để demo. B và D chạy song song được sau A.

### 2.1 Spec kỹ thuật — ba chỗ phải xem lại

Spec control plane viết **trước** khi định hướng sản phẩm. Phần lớn vẫn đúng, ba chỗ cần xem lại trước khi dev theo:

| Chỗ | Vấn đề |
|---|---|
| Quyết định #4 spec (portal là system of record duy nhất) | Chốt lúc chưa đọc `santa-agent-cms`. CMS thật **sync từ NBX Sales API**, không sở hữu dữ liệu. Với MVP (nhập tay + import file) thì portal-là-nguồn là đúng — nhưng phải ghi rõ đây là quyết định cho **tenant mới**, không phải cho Noble |
| Không có mốc thời gian trên bản ghi | Quyết định #4 sản phẩm cần `cập nhật lúc` mỗi bản ghi để agent hedge. Spec chưa có |
| Không có ghi nhận token | Quyết định #7 cần từ ngày đầu. Spec chưa có |

---

## 3. Gói việc

### Gói A — Nền tảng đa-tenant  ·  *đường găng, làm trước*

**Năng lực:** backend + Postgres (RLS là phần khó)
**Chặn bởi:** ~~N4~~ · ~~N10~~ — **hết chặn 29/7**, kho tệp chốt MinIO tự dựng (A21)

| Việc | Ghi chú |
|---|---|
| Schema `control` + `tenant_data`, isolation theo tenant | Đã có plan chi tiết + code chạy: branch `feat/slice-1a-postgres-schema`, commit `6b9ccb5..d3c4498` (scaffold + harness test đã PASS). Plan: `docs/superpowers/plans/2026-07-28-slice-1a-...md` |
| Cách ly đọc: agent chỉ đọc qua view, zero quyền trên bảng gốc | **Điểm dễ sai nhất toàn dự án.** **7** cổng test bắt buộc (spec §9), không được skip |
| **Cổng test thứ 7 — cách ly ở kho tệp** (spec §9, mới 29/7) | Sáu cổng kia canh Postgres. Cổng này canh **kho tệp** — nơi giữ bản ghi hội thoại, chỗ nhạy cảm nhất trong hệ. Postgres **từ chối câu truy vấn** sai workspace; kho tệp chỉ kiểm được *"khoá này có quyền vào tiền tố đường dẫn này không"* — một lỗi ghép đường dẫn là workspace A đọc được hội thoại của workspace B. Cơ chế phải kiểm: **policy theo tiền tố `tenants/<id>/*` gắn cho từng access key** — dựng MinIO thật trong container |
| **Sao lưu kho tệp + một lần diễn tập phục hồi** (A21, mới 29/7) | Tự dựng nghĩa là sao lưu là việc của NobleX. Kho tệp mang **hai** lời hứa: retention 6 tháng nằm trong hợp đồng, và khả năng agent chạy tiếp khi cơ sở dữ liệu chết. **Mất nó là vỡ cả hai cùng lúc.** Sao lưu phải ra **một nơi khác**, và phải phục hồi thử một lần thật — bật snapshot rồi tin là đủ thì không tính |
| Cấp phát workspace nay gồm **tiền tố + khoá truy cập MinIO** | BR12: tạo ở cả ba kho hoặc không tạo gì. Nay là hàng `tenants` + role Postgres + kho tri thức + **tiền tố `tenants/<id>/` và một khoá giới hạn đúng tiền tố đó** |
| **Mô hình kết nối & vai trò** (spec §5.8, mới 29/7) | Bốn điều kiện phải cùng đúng, **cả bốn hỏng âm thầm**: (1) chủ sở hữu bảng phải bị ép áp cách ly — mặc định nó được miễn; (2) role chạy migration ≠ role phục vụ; (3) view phải khai chạy-bằng-quyền-người-gọi, mặc định là quyền người tạo → cách ly biến mất; (4) đặt phạm vi workspace phải **trong giao dịch**, nếu không thì với connection pool request sau **kế thừa workspace của request trước** |
| Bảng `conversations` + gộp hồ sơ tích luỹ vào `contacts` (A18) | Xem spec §5.2. Kèm cột con trỏ bản ghi thoại **để sẵn nullable** — bật sau không cần chuyển đổi dữ liệu |
| Auth + workspace + phân quyền | **Đặc tả đầy đủ: `PQ_01`** (N4 đã đóng 29/7). Dùng lại khuôn `santa-agent-cms` cho đăng nhập + `audit_log`, **nhưng KHÔNG dùng lại hai chỗ**: (1) mô hình bậc thang → đổi sang **4 vai trò song song**; (2) vai trò nhét trong phiếu đăng nhập → **đọc từ DB mỗi request** (nếu không thì gỡ quyền chậm 15 phút) |
| Quyền hỗ trợ NobleX = **hàng thành viên tạm có hạn** | **Không** làm bằng cờ bỏ qua kiểm tra — cờ tạo một nhánh code mà lời hứa NobleX không đọc được không áp dụng, và nhánh đó sớm muộn bị chạm nhầm |
| **Admin nền tảng không đọc được `tenant_data`** (#5) | Thiết kế từ đầu. Hỗ trợ khách qua cấp quyền tạm thời có ghi log — phần cấp quyền để sau, nhưng **chỗ chặn phải đúng từ bây giờ** |

> Phần scaffold + harness đã có sẵn từ lần chạy trước. **Chưa qua review.** Người nhận gói A đọc plan, review lại 2 commit đó rồi làm tiếp — đừng viết lại từ đầu.

---

### Gói B — Dữ liệu BĐS  ·  *khối lượng lớn nhất, dễ bị đánh giá thấp*

**Năng lực:** fullstack (form nhiều trường + validate + import)
**Chặn bởi:** A, N2

| Việc | Ghi chú |
|---|---|
| **Ba cờ trên mỗi trường: hiện trên form · agent đọc · agent lọc** | **Form đang bám theo form nhập liệu của sales, nhưng agent không cần phần lớn trường đó.** Ba cờ này không bằng nhau. Cơ chế đã có trong spec §5.3 (`field_policy_live`) — chỉ cần dùng đúng. Đặc tả: DL_01 |
| **SỬA LỖI: `unit_json` gửi 7/18 khoá luôn rỗng** | ⚠ Trên provider `nbx` (đang là default) các trường sau **luôn `None`**: `price_per_m2_vnd` · `price_progress_vnd` · `price_loan_vnd` · `floor` · `view` · `max_discount_pct`, cộng `tower` hardcode `""` trong `_serialize.py`. Gần 40% payload là null, nhân với số căn mỗi lượt. Bỏ khoá không có giá trị |
| **GỠ filter `floor`/`tower` khỏi `search_units`** (#17) | ⚠ `schemas.py` khai 2 filter đó cho LLM; `nbx_mongo.search_units` **không đọc `query.floor`/`query.tower`** — chỉ lọc `unit_type`/`max_price`/`min_area`/`direction`/`unit_code`/`status`. Khách hỏi "căn tầng 14" → trả căn tầng bất kỳ, agent đọc như thể đúng tầng. **Sai âm thầm, tệ hơn trả rỗng.** **Chốt: gỡ 2 filter, không bổ sung dữ liệu.** Kèm luật hành vi: khách hỏi tầng → agent nói thật là chưa có thông tin tầng, đưa căn theo tiêu chí khác, mời chuyển chuyên viên (DL_01 BR15) |
| CRUD Dự án (~40 trường, 6 nhóm) | Trường khớp `nbx_projects`. Prototype đã vẽ đúng schema |
| CRUD Quỹ căn (~45 trường, 7 nhóm) | Trường khớp `nbx_units` |
| **Gate trường `GATED`** (`commission`, `bank_support`, `csbh_full`) | **Yêu cầu bảo mật thương mại, không phải tính năng phụ.** Hoa hồng lộ ra cho khách là sự cố thật |
| Import CSV/XLSX có **xem trước + xác nhận** | Prototype hứa *"sửa hàng loạt ghi đè toàn bộ danh sách"* — không được apply mà không hiện số dòng sẽ xoá |
| Đổi đơn vị giá tỷ → VND **ở biên nhập** | Agent đã từng phải sửa đúng bug này. Lưu VND, không lưu tỷ |
| Cảnh báo "N căn chưa đủ dữ liệu cho agent" | Cần N2 |
| **Mốc `cập nhật lúc`** mỗi bản ghi (#4) | Tiền đề cho rào chắn hedge ở gói G |

> **Đây không phải "hai cái form" — là một CMS đầy đủ.** Ước lượng ~1/4 công sức MVP. Nếu chia người, đây là gói nên có 2 người.

#### B2 — Media dự án (ảnh/video agent gửi cho khách) · **hạng mục chưa ai tính**

| Việc | Ghi chú |
|---|---|
| **Màn nạp media theo dự án + gán danh mục** | ⚠ **Prototype không vẽ màn này, work packages trước đây không có.** Hệ cũ ảnh do CMS nội bộ Noble đẩy lên; sang SaaS thì tenant phải tự nạp. Không có nó thì tính năng gửi ảnh **chỉ chạy được cho Noble**, mọi khách khác là kho rỗng |
| **Cách ly media theo workspace** | ⚠ Grep toàn bộ đường media: **không một chữ `tenant` nào**. Payload gửi dịch vụ tìm kiếm chỉ có `query`/`project_code`/`category`/`top_k`/`threshold`. Khách của A có thể thấy ảnh dự án của B — **rò dữ liệu nhìn thấy bằng mắt, chụp màn hình được**. Cùng hạng ưu tiên với quyết định #13 |
| **DANH MỤC THUẦN — bỏ tìm ngữ nghĩa khỏi MVP** (#15) | Media đã đổi kiến trúc: từ đọc thẳng kho theo thư mục `danh_muc` (santa cũ, xác định) sang **dịch vụ tìm ngữ nghĩa** (E5 + SigLIP2, `threshold=0.4`). Tenant mất quyền quyết định ảnh nào được gửi. **Chốt: quay về danh mục thuần.** Agent truyền dự án + danh mục, hệ thống trả ảnh trong đúng danh mục theo thứ tự tenant sắp. **Bỏ tham số câu hỏi tự do khỏi kỹ năng gửi media** |
| Ảnh đại diện mỗi danh mục + xem trước như khách thấy | Tenant phải biết chắc ảnh nào khách thấy đầu tiên, trước khi có khách thật |
| **MVP nhận video tự upload** (#16) | ⚠ Hiện **chỉ video của nền tảng chia sẻ mới hiện được**; mp4 tự upload bị loại lúc gửi. Việc mới cho **client**: phát video theo địa chỉ trực tiếp + hiện ảnh bìa. Kèm ngưỡng dung lượng riêng và chi phí băng thông |
| **Định dạng không render được phải báo lúc upload** | ⚠ Hiện PDF bị **drop âm thầm lúc gửi**, chỉ ghi log. Tenant không bao giờ biết file của mình chưa từng đến tay khách |
| Bản nhẹ cho ảnh gốc nặng | Khách xem trên di động |

> Chi tiết: **DL_02** trên Notion.
>
> **Quyết định #15 gỡ được kha khá việc:** bỏ tìm ngữ nghĩa nghĩa là bỏ luôn một dịch vụ phải vận hành và trả tiền, bỏ GPU cho embedding ảnh, lấy media nhanh hơn vì chỉ còn một lượt đọc, và **cách ly theo workspace trở thành chuyện tầm thường** thay vì phải sửa một dịch vụ bên ngoài. Đánh đổi: khách hỏi tự do *"có ảnh hồ bơi không"* thì agent quy về danh mục gần nhất và gửi cả danh mục — thô hơn, nhưng đúng và đoán trước được.
>
> Một điểm nhỏ còn lại: chú thích ảnh bị cắt bằng hai chuỗi cố định theo định dạng pipeline của Noble.

---

### Gói C — Agent Studio  ·  *đường găng*

**Năng lực:** fullstack + hiểu prompt của agent
**Chặn bởi:** A, N3

| Việc | Ghi chú |
|---|---|
| **Persona = template của platform + biến của tenant** (#14) | **Tenant KHÔNG thấy file markdown.** Portal hiện form, render ra `SOUL.md`/`RULES.md`/`config.json` lúc publish. Đọc `RULES.md` thật: **135/184 dòng là cơ chế**, nhiều chỗ có code guard đi kèm. Tenant chỉ điền 8 ô, cả 8 có mặc định. Đặc tả: AG_01 trên Notion |
| **SỬA LỖI: Tool catalog phải sinh từ `[tools].enabled`** | ⚠ `RULES.md` có bảng Tool catalog **15 dòng text tĩnh**; grep toàn bộ `src/` không có code nào lọc theo tool đang bật. Tắt `booking` → agent mất schema nhưng prompt vẫn dạy gọi → **agent hứa đặt lịch rồi không tạo lịch nào**. Khối phong thuỷ cũng vậy (schema bị strip theo `rankers`, text thì không). **Không sửa thì không ship được tính năng bật/tắt kỹ năng** |
| **SỬA LỖI: 4 chỗ hardcode brand trong `RULES.md`** | ⚠ `load_agent_def` đã truyền `brand` vào jinja, nhưng `RULES.md` chỉ có `{{ agent_name }}` ×5, **không một `{{ brand.* }}` nào**. Còn hardcode ở dòng 172 (`"Em là chuyên viên NobleX"`), 179 (`"bất động sản NobleX"`), 173 + 176 (mã `NCLB`/`SLC`, tên `Noble Crystal Long Biên`). **Agent của An Phú Land sẽ tự xưng nhân viên NobleX** |
| **Render đúng một chỗ: portal** | Hiện `load_agent_def` render jinja lần nữa lúc agent boot. Hai chỗ cùng render một template là cách chắc chắn nhất để portal và agent hiểu khác nhau. Bundle nên chứa markdown đã render xong |
| **Bỏ `NOBLE_AGENT_NAME` đè tên** | Biến môi trường này hiện đè `config.json`. Với tenant thì portal phải là chủ tên agent, nếu không sửa tên xong agent vẫn xưng tên cũ |
| Chọn preset Giọng điệu (3 lựa chọn) | Nội dung do N3 cung cấp. Dev chỉ làm cơ chế chọn |
| Bật/tắt kỹ năng | Ánh xạ `[tools].enabled`. **Vẽ đủ 12 tool**, không phải 4 như prototype, đặt tên nghiệp vụ + cảnh báo phụ thuộc cho mỗi cái |
| Rào chắn: **6 cái, khoá, chỉ để xem** | Prototype vẽ 4; agent có thật 6 (thêm: không tiết lộ là AI, không nói mã dự án nội bộ). **Không cho tắt** — 4 trong 6 là điều kiện đúng đắn hoặc nghĩa vụ pháp lý. ⚠ Riêng không tiết lộ là AI là quyết định pháp lý, chưa chốt |
| Chat thử ngay trong portal | `/chat` đã có, nhúng vào |
| **Lưu → áp dụng** (chưa versioning) | Có bước xác nhận. Versioning/publish/diff/rollback: **sau MVP** |
| Bỏ khỏi UI: tốc độ nói · "Tính khoản vay" | Chưa tồn tại. Dropdown Giọng đọc chỉ có 1 giọng thật — hoặc bỏ, hoặc ghi rõ |

---

### Gói D — Tài liệu (KB)

**Năng lực:** backend + xử lý tài liệu
**Chặn bởi:** A

| Việc | Ghi chú |
|---|---|
| **Một collection Qdrant cho mỗi tenant** (#13) | **Cách ly do cấu trúc, không do filter.** Tạo lúc tạo tenant, tên sinh từ `tenant_id` trong code. Xoá tenant = drop collection (Nghị định 13). Đặc tả: KB_01 trên Notion, spec §5.6 |
| **Cổng test cross-tenant cho RAG** | Truy vấn của tenant A phải trả 0 chunk của tenant B. **Không được skip** — ngang hàng với 4 cổng test RLS ở gói A |
| Upload PDF / DOCX / XLSX → parse → chunk → embed → index | **Chức năng quyết định tenant có tự chủ được hay không.** Thiếu nó thì mỗi khách mới lại cần dev |
| Danh sách tài liệu + trạng thái xử lý từng file + xoá | Trạng thái phải hiện rõ — không để khách tưởng upload xong là agent biết ngay. Xoá là gỡ khỏi collection ngay, không thùng rác |
| "Agent đã trích dẫn" — tài liệu nào đang thực sự trả lời khách | `kb_search` trả hit có id chunk → log + tổng hợp. Cho biết tài liệu nào vô dụng |
| Bỏ khỏi MVP: crawl web · duyệt tài liệu · độ phủ theo chủ đề | |

> Đường build index Qdrant **đã có** ở `santa-agent-cms` (`services/rag/nbx_rag_build.py`, `qdrant_core.py`). Nhấc sang, đừng viết lại. Phần mới là parser + chunker cho file người dùng upload.

---

### Gói E — Vận hành

**Năng lực:** fullstack, nặng phần đọc/hiển thị
**Chặn bởi:** A, G, N1

| Việc | Ghi chú |
|---|---|
| **Tổng quan**: hội thoại · tỉ lệ agent tự xử lý · thời lượng gọi TB · khối lượng theo kênh | `Tỉ lệ agent tự xử lý = (tổng − chuyển người)/tổng` (#2). **Không có** KPI lead (#1), **không có** widget hạn mức |
| Hội thoại gần đây + cột Kết quả | Cần N1 |
| **Hội thoại**: chat log + call log, hợp nhất theo khách | ⚠ Cầu nối yếu — `chat_conversations` **không có SĐT**. Xem "Nợ kỹ thuật" dưới |
| Chuyển người thật: thông báo + hiện SĐT khách | **Không** làm live-chat ở MVP. Nhân viên xử lý ngoài hệ thống |
| **Lịch hẹn**: danh sách 2 kênh, xác nhận, đổi lịch, **phân công** | `assignee` là trường mới. Tỉ lệ đến hẹn: chỉ đưa lên khi đã chốt ai cập nhật |
| **Cần bổ sung**: gom nhóm câu hỏi, phân 3 loại, dạy agent, thử lại | **Gói giá trị/công sức cao nhất.** Phân 3 loại theo *chỗ phải sửa* — giữ nguyên thiết kế prototype |

---

### Gói F — Kết nối + Lưu trữ

**Năng lực:** backend
**Chặn bởi:** A

| Việc | Ghi chú |
|---|---|
| Khoá API theo tenant: tạo · thu hồi · giới hạn tốc độ | Hiện là **một khoá tĩnh toàn hệ thống**. Khuôn có sẵn: `server/app_session.py` |
| Tài liệu API cho tenant tích hợp | Có sẵn: `docs/api/noblex-app-dev-guide.md` — cập nhật lại |
| ~~Công tắc ghi âm cuộc gọi~~ | **Bỏ khỏi MVP.** Hệ thống **không ghi âm ở bất kỳ đâu** — công tắc cho một thứ không tồn tại là hứa suông. Muốn nghe lại cuộc gọi là quyết định riêng (§5.2.1): ~1 MB/phút so với ~30 KB/cuộc, kèm phơi nhiễm pháp lý khác vì giọng nói là dữ liệu sinh trắc |
| **Thời gian lưu, mặc định 6 tháng, tenant đặt được** + job xoá quá hạn | (#6, #19) Áp cho **bản ghi thoại (chữ)** · hồ sơ khách tích luỹ. **Job phải có giám sát và cảnh báo khi không chạy** — 6 tháng giờ nằm trong hợp đồng với khách; hứa mà không dọn còn tệ hơn không hứa |
| **Xoá theo SĐT phải nguyên tử ở phía chỉ số** | Một giao dịch xoá hàng + hồ sơ tích luỹ, **rồi mới** dọn tệp (job chạy lại được). Ngược lại để lại hàng trỏ vào tệp không còn → dashboard hiện lỗi cho một cuộc gọi lẽ ra không tồn tại |
| Nhật ký hoạt động | `audit_log` đã có ở CMS, nhấc sang |
| Bỏ khỏi MVP: Zalo OA · CRM · webhook · Sales Cloud · báo cáo tự động | (#3) |

> **Thiết kế chỗ lưu sao cho xoá được theo SĐT.** Tab "Yêu cầu của khách" (xuất/xoá dữ liệu) để sau MVP, nhưng nếu dữ liệu rải rác không truy được theo SĐT thì sau này **không xoá nổi** — và đó là nghĩa vụ pháp lý, không phải tính năng.

---

### Gói G — Phía agent  ·  *đường găng*

**Năng lực:** Python + hiểu `santa-hotline-agent`. **Người thạo agent nhất nên nhận gói này.**
**Chặn bởi:** A

| Việc | Ghi chú |
|---|---|
| Agent đọc dữ liệu từ portal (thay nguồn hiện tại) | Provider mới. Agent đã có sẵn lớp trừu tượng provider — đây là việc agent **đã lường trước** |
| Nhận cấu hình persona từ portal | Agent đã có cơ chế tenant bundle (`TENANT_ID` → manifest + persona dir) |
| **Rào chắn hedge theo độ tươi dữ liệu** (#4, §21.1) | Trạng thái căn quá ngưỡng → **cấm khẳng định còn hàng**, nói *"cần xác nhận lại"*. Đây là chỗ trả nợ cho quyết định 6 tháng |
| Ghi `appointments` / `contacts` về portal | Để gói E thấy được |
| **Ghi hội thoại về portal** (quyết định A18, chốt 29/7) | Tóm tắt cuộc gọi → bảng `conversations`; sự kiện vòng đời gộp vào **cùng lượt ghi** dạng một cột, không insert rời từng sự kiện |
| **Gộp hồ sơ tích luỹ vào `contacts`** (A18) | Kèm **đổi khoá**: từ số điện thoại **toàn cục** sang **(workspace, số điện thoại)**. Cùng một số gọi hai khách hàng là **hai** hồ sơ. Đây chính là chỗ đơn-khách-hàng của hệ cũ lộ ra — không phải đổi cơ học |
| **Chỉ số kỹ thuật** (độ trễ · TTFA · thời gian gọi kỹ năng) → schema `platform` | Vào Postgres nhưng **KHÔNG vào vùng cách ly** — telemetry của NobleX, không phải dữ liệu của khách. Kèm quyết định về hàng đợi thư chết trên Redis: nó viết riêng cho kho cũ, hoặc chuyển theo hoặc bỏ (bỏ chấp nhận được — đây là số đo) |
| ⚠️ **Chốt trước khi code: đường ghi chọn kho thế nào** | Cùng một mã nguồn agent phục vụ **cả Santa đang chạy lẫn Odyssey**. Mọi dòng ghi X **thay vì** Y ở gói này, đọc nguyên văn, **làm Santa hỏng ngay khi merge**. Hoặc đường ghi chọn kho theo cấu hình (như đường đọc đã làm), hoặc đóng băng Santa ở nhánh riêng |
| **Ghi bản ghi thoại lên kho tệp** (quyết định #19, chốt 29/7) | Đường dẫn theo workspace, **thông tin đăng nhập theo workspace** — nếu không thì lời hứa NobleX không đọc được thủng ở đúng chỗ nhạy nhất. Lưu: lượt nói + **tên kỹ năng kèm tham số và kết quả** + **con trỏ phiên bản cấu hình**. **KHÔNG** lưu persona đã render (đã có bản đánh phiên bản rồi) và **KHÔNG** tái dùng định dạng huấn luyện hiện tại |
| **Ghi nhận token** theo tenant / hội thoại / mục đích gọi (#7) | Rẻ — `StreamingClient` đã thấy usage. Phải phân biệt: trả lời khách · tóm tắt · gợi ý nhanh · embedding |
| Log đủ chi tiết để gói E phân 3 loại lỗ hổng | `kb_search` rỗng · `ESCALATE_SIGNAL` từ tool nào · chạm rào chắn nào |

> Nguyên tắc giữ: **agent không cần biết portal tồn tại.** Nó chỉ biết "cấu hình đến từ đâu" và "provider tên là gì". Turn loop, prompt builder, RAG, semcache, voice pipeline, transport: **không đụng**.

---

### Gói H — Onboarding  ·  *làm cuối, nhưng đừng cắt*

**Năng lực:** frontend
**Chặn bởi:** B, C, D (nó xâu chuỗi các gói kia)

```
Bước 1  Tạo workspace + chọn lĩnh vực (MVP: chỉ Bất động sản)
        └─ kích hoạt cấp agent NGAY, chạy song song bước 2–3
Bước 2  Nạp dữ liệu — import file, hoặc nhập 1 dự án mẫu
Bước 3  Cấu hình agent → CHAT THỬ NGAY          ← bước "aha"
Bước 4  Bật kênh + mời thành viên
```

Bước 3 là chỗ khách lần đầu thấy agent nói bằng dữ liệu **của chính họ**. Mọi bước trước nó là chi phí, mọi bước sau là mở rộng. **Nếu phải cắt, cắt bước 4 — đừng đẩy bước 3 xuống sau.**

### Bước 3 cần agent đã được cấp — đây là ràng buộc dễ bị bỏ sót nhất của gói H

`TENANT_ID` bị đóng băng lúc process boot (ba singleton trong code agent), nên **chat thử cần một container đã chạy cho đúng workspace đó**. Không có container thì bước "aha" không tồn tại.

Cách giải: **bước 1 kích hoạt CI job cấp pod ngay**, không đợi khách xong wizard. Cấp pod không cần tức thì — chỉ cần nhanh hơn một người nạp dữ liệu + sửa persona (15–40 phút). Bình thường tới bước 3 là đã xong.

Bước 3 đọc trạng thái suy ra từ `agent_heartbeats`, **không thêm state mới**:

| Trạng thái | Ô Thử ngay |
|---|---|
| `Đang cấp` | khoá, hiện tiến trình, cho đi tiếp bước 4 rồi quay lại |
| `Đang áp dụng` | khoá, ≤20s (chu kỳ poll bundle) |
| `Sẵn sàng` | mở |
| `Mất kết nối` | khoá + báo lỗi thật, **không giả vờ đang chạy** |

Chi tiết: spec §6.5. Việc kèm theo cho **gói A**: portal gọi pipeline trigger khi tạo workspace.

> **Phương án pool pod cấp trước đã bị loại vì nó không hoạt động**, không phải vì đắt: không gán được tenant cho container đã boot, pool muốn nhận tenant phải restart → không nhanh hơn tạo mới.

---

## 4. Nợ kỹ thuật phải xử lý trong MVP

| # | Nợ | Ảnh hưởng | Xử ở gói |
|---|---|---|---|
| 1 | **`chat_conversations` không có SĐT** | Khách chỉ chat mà chưa đặt lịch → **không hiện trong hồ sơ khách**. Đã ghi thành văn trong `cms_db_state.md`. Phải sửa ở **agent chat**, không phải ở portal | G |
| 2 | Quỹ căn có thể cũ tới 6 tháng (#4) | Agent nói sai tình trạng còn hàng | G (hedge) + B (mốc thời gian) |
| 3 | TTS chỉ có 1 giọng | Dropdown "Giọng đọc" là dropdown giả | C (bỏ hoặc ghi rõ) |
| 4 | Gợi ý nhanh chỉ có ở chat, voice chưa có | UI phải nói rõ phạm vi | C |

---

## 5. Việc KHÔNG làm ở MVP — ghi ra để không ai tự ý làm

Tài chính (vertical thứ 2) · Gói cước & thanh toán · versioning/publish/rollback persona · bộ kiểm thử hồi quy · CSAT · tiếp quản (live-chat) · Zalo OA · CRM 2 chiều · webhook · crawl web · tự định nghĩa lĩnh vực · 2FA · SSO · quản lý thiết bị · vai trò tùy chỉnh · yêu cầu xuất/xoá dữ liệu của khách.

Thứ tự làm sau MVP: xem §20 của tài liệu định hướng.

---

## 6. Điều tôi chưa biết để phân người cụ thể

Tài liệu này chia theo **năng lực**, chưa gán tên. Để gán được cần biết: đội có bao nhiêu người, ai thạo Postgres/RLS, ai thạo `santa-hotline-agent`, ai làm frontend, và ai sở hữu nội dung persona (N3).

Ba gợi ý bất kể đội hình:

1. **Gói G cho người thạo agent nhất.** Nó ở đường găng và cần hiểu cả agent lẫn portal.
2. **Gói B nên 2 người.** Nó là một CMS, không phải hai cái form.
3. **Gói A làm trước và làm chắc.** Phần cách ly dữ liệu giữa các tenant sai thì không phải bug — là sự cố rò dữ liệu giữa các khách hàng.
