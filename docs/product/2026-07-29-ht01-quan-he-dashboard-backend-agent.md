# HT_01 — Quan hệ Dashboard · Backend · Agent

| Phiên bản | Ngày | Người viết | Thay đổi |
|---|---|---|---|
| v1.0 | 2026-07-29 | BA | Bản đầu. Định nghĩa ba lớp, bốn luồng, ba bậc độ trễ hiệu lực, 14 business rule. Nêu 3 khoảng trống thiết kế (N5 · N6 · N7). |
| v1.3 | 2026-07-29 | BA | **Odyssey không dùng Mongo** (quyết định #20). Còn đúng ba kho; chỉ số kỹ thuật vào schema `platform` trong Postgres, ngoài vùng cách ly. |
| v1.2 | 2026-07-29 | BA | **Đính chính**: bản ghi thoại ĐANG được lưu (kho `agent_messages`), không phải không lưu ở đâu cả. P8 không đổi, việc nhỏ hơn, nhưng 3 khiếm khuyết là thật. Thêm N8 — Odyssey có cần Mongo không. |
| v1.1 | 2026-07-29 | BA | **N5 đã chốt** — dữ liệu vận hành của tenant về Postgres + RLS (quyết định #18). Thêm BR15 (ranh giới dữ liệu của ai). Màn Hội thoại có kho. Còn mở: có lưu bản ghi thoại không. |

---

## I. Tổng quan

### 1. Mô tả

Sản phẩm có **ba lớp**. Ai cũng nói được tên chúng, nhưng ranh giới trách nhiệm thì chưa
ai viết ra — nên mỗi lần bàn một tính năng lại phải bàn lại. Tài liệu này chốt ranh giới.

| Lớp | Là gì | Chịu trách nhiệm | KHÔNG chịu trách nhiệm |
|---|---|---|---|
| **Dashboard** | Trang web tenant tự phục vụ | Trình bày · thu thập ý định người dùng · nói thật về trạng thái | Giữ dữ liệu · quyết định ai đọc được gì · tính toán nghiệp vụ |
| **Backend** | Portal API + Postgres + kho tệp | **Nguồn sự thật duy nhất** về cấu hình và dữ liệu · cưỡng chế cách ly · đóng gói cấu hình thành bản phát hành | Phục vụ khách hàng cuối · giữ hội thoại đang chạy |
| **Agent** | Bản chạy phục vụ khách hàng cuối, **mỗi workspace một bản riêng** | Hội thoại · gọi kỹ năng · ghi lại kết quả | Là nguồn sự thật · quyết định cấu hình · phục vụ dashboard |

Một câu để nhớ: **ba lớp, hai chiều, một nguồn sự thật.**

Cấu hình và dữ liệu đi **xuống** (dashboard → backend → agent). Kết quả đi **lên**
(agent → backend → dashboard). Không có đường chéo — trừ đúng một ngoại lệ có chủ đích
(BR03).

**Nói rõ điều dễ hiểu nhầm nhất:** hôm nay ở hệ Santa, **backend và agent là cùng một
tiến trình**. Dashboard gọi thẳng `/api/v1/sales/*` nằm trên chính agent
(`server/http.py:110`). Odyssey **tách** hai thứ đó. Việc tách này không phải dọn dẹp
kiến trúc cho đẹp — nó là điều kiện để có nhiều tenant, vì đường hiện tại xác thực bằng
**một API key tĩnh dùng chung, không có phạm vi tenant nào**.

### 2. Yêu cầu chức năng

| # | Yêu cầu |
|---|---|
| YC01 | Người dùng sửa cấu hình trên dashboard → thay đổi được lưu thành **bản nháp**, chưa ai thấy |
| YC02 | Người dùng **Xuất bản** → hệ thống tạo một **phiên bản** bất biến, đánh số tăng dần, không bao giờ ghi đè |
| YC03 | Agent tự nhận bản mới trong vòng **20 giây** mà không cần ai bấm gì, không cần khởi động lại |
| YC04 | Cuộc hội thoại **đang chạy** giữ nguyên phiên bản nó khởi tạo cho tới khi kết thúc |
| YC05 | Người dùng thấy được **agent đang thực sự chạy phiên bản nào**, không phải phiên bản dashboard nghĩ là đang chạy |
| YC06 | Người dùng quay lại **bất kỳ phiên bản cũ nào** bằng một thao tác |
| YC07 | Dữ liệu nghiệp vụ (dự án, căn, tài liệu) sửa xong **có hiệu lực ngay lượt hỏi kế tiếp**, không cần xuất bản |
| YC08 | Kết quả hội thoại (lịch hẹn, khách quan tâm, nội dung trao đổi) tự hiện lên dashboard |
| YC09 | Agent của workspace A **không thể** đọc dữ liệu của workspace B, kể cả khi code agent viết sai |
| YC10 | Backend chết → agent **vẫn phục vụ khách hàng cuối** bằng bản cấu hình đã lưu |
| YC11 | Agent chết → dashboard **nói thật là mất kết nối**, không hiện màn hình giả vờ đang chạy |

### 3. Yêu cầu phi chức năng

**Bảo mật.** Cách ly giữa các workspace do **Postgres cưỡng chế** (RLS + role riêng cho
từng tenant), không do agent tự nhớ lọc. Đây là khác biệt bản chất: một lỗi lập trình
trong agent không được phép trở thành rò rỉ dữ liệu giữa hai khách hàng. Agent chỉ có
quyền ghi trên **đúng những bảng nó cần**, không đụng được bảng cấu hình. Quản trị viên
NobleX có quyền trên control plane nhưng **không đọc được `tenant_data`** — đây là lời hứa
bán hàng, phải kiểm chứng được bằng test, không phải bằng nội quy.

**Hiệu suất.** Agent đọc dữ liệu **trong tiến trình, một chặng** tới Postgres — không qua
Portal API. Lý do là độ trễ giọng nói: mỗi chặng mạng thêm vào đều nằm trên đường tới câu
trả lời đầu tiên. Chu kỳ dò cấu hình 20 giây là nền, không nằm trên đường hội thoại.
Đổi phiên bản giữa cuộc gọi **bị cấm** một phần vì lý do hiệu suất: system prompt nằm đầu
mọi request, đổi giữa chừng làm hỏng bộ nhớ đệm prompt của nhà cung cấp LLM và tạo một cú
giật độ trễ cho **toàn bộ** khách đang gọi.

**Khả dụng & Tương thích.** Backend chết không được kéo agent chết theo — agent giữ bản
cấu hình trong đệm đĩa và phục vụ tiếp. Ngược lại, agent chết không được làm dashboard
trắng màn hình. Hai lớp phải suy biến độc lập. Trạng thái workspace **suy ra** từ nhịp
tim agent gửi lên, nên hệ thống **tự lành**: pod chết → mất kết nối; pod lên lại → tự về
sẵn sàng. Không có trạng thái nào phải sửa tay.

**Giao diện UX.** Dashboard **phải nói đúng bậc độ trễ** của thứ vừa sửa (§II.2). Nói
"Đã lưu" cho một thay đổi persona chưa xuất bản là nói dối người dùng — họ sẽ đi gọi thử
và không thấy gì đổi, rồi mất niềm tin vào cả sản phẩm. Ba trạng thái tối thiểu phải phân
biệt được trên giao diện: *Bản nháp · Đang áp dụng · Đang phục vụ*.

**Khả năng mở rộng.** Thêm một tenant = thêm một hàng `tenants` + một pod. Không sửa code,
không sửa schema. Thêm một lĩnh vực (vertical) = thêm một bộ template + bảng dữ liệu, ba
lớp không đổi quan hệ.

---

## II. Mô tả tính năng

### 1. Luồng nghiệp vụ

Bốn luồng, không hơn. Mọi tương tác giữa ba lớp đều thuộc một trong bốn.

```
┌─────────────┐                    ┌──────────────────────┐              ┌───────────┐
│  DASHBOARD  │                    │       BACKEND        │              │   AGENT   │
└──────┬──────┘                    └──────────┬───────────┘              └─────┬─────┘
       │                                      │                                │
   ────┼─── A. CẤU HÌNH ĐI XUỐNG ─────────────┼────────────────────────────────┼────
       │  sửa persona/kỹ năng/rào chắn        │                                │
       ├─────────────────────────────────────>│ lưu BẢN NHÁP                   │
       │  bấm Xuất bản                      │                                │
       ├─────────────────────────────────────>│ kiểm tra → đóng gói →          │
       │                                      │ tạo PHIÊN BẢN v(n+1)           │
       │                                      │ ghi con trỏ LIVE               │
       │                                      │<───────────────────────────────┤ dò 20s
       │                                      │        tải gói, kiểm tổng      │
       │                                      │                                │ nạp
       │                                      │                                │
   ────┼─── B. DỮ LIỆU ĐI NGANG ──────────────┼────────────────────────────────┼────
       │  thêm/sửa dự án · căn · tài liệu     │                                │
       ├─────────────────────────────────────>│ ghi thẳng vào kho              │
       │                                      │<───────────────────────────────┤ đọc khi
       │                                      │   ĐỌC LÚC KHÁCH HỎI            │ có câu hỏi
       │                                      │                                │
   ────┼─── C. KẾT QUẢ ĐI LÊN ────────────────┼────────────────────────────────┼────
       │                                      │<───────────────────────────────┤ ghi lịch hẹn
       │                                      │       lịch hẹn · khách quan tâm│ khách quan tâm
       │  màn Hội thoại · Lịch hẹn            │       nội dung hội thoại ⚠️N5   │ hội thoại
       │<─────────────────────────────────────┤                                │
       │                                      │                                │
   ────┼─── D. SỨC KHOẺ ĐI LÊN ───────────────┼────────────────────────────────┼────
       │                                      │<───────────────────────────────┤ nhịp tim
       │  Sẵn sàng / Đang áp dụng         │  phiên bản đang chạy, lỗi cuối │ mỗi chu kỳ
       │<─────────────────────────────────────┤  → SUY RA trạng thái           │
       │                                      │                                │
       └──── E. NGOẠI LỆ DUY NHẤT: Thử ngay ─ dashboard nói thẳng với agent ─┘
                                              qua đúng kênh khách hàng cuối dùng (BR03)
```

**Điều quan trọng nhất trong sơ đồ này:** mũi tên từ agent về backend luôn là agent **chủ
động** — agent đọc, agent ghi, agent gửi nhịp tim. Backend **không bao giờ gọi ngược
xuống agent**, và agent **không bao giờ gọi Portal API** (BR01, BR02). Đó là thứ làm cho
"backend chết mà khách hàng cuối không bị ảnh hưởng" thành sự thật chứ không phải khẩu
hiệu.

### 2. Diễn giải

#### 2.1 Ba bậc độ trễ hiệu lực — phần quan trọng nhất tài liệu

Câu hỏi mà mọi người trong nhóm sẽ hỏi, và giao diện buộc phải trả lời đúng:
**"tôi vừa sửa xong, bao giờ agent thấy?"**

Không có một câu trả lời. Có **ba**, và chúng khác nhau về bản chất chứ không phải về
tốc độ.

| Bậc | Người dùng sửa gì | Agent thấy khi nào | Vì sao | Dashboard phải nói |
|---|---|---|---|---|
| **1 — Tức thì** | Giá · diện tích · tình trạng căn · nội dung dự án · tài liệu | **Ngay lượt hỏi kế tiếp**, kể cả giữa cuộc gọi đang chạy | Agent đọc kho dữ liệu **mỗi lần** khách hỏi, không có bộ đệm | Đã lưu |
| **2 — Đầu cuộc** | Thêm/xoá/đổi tên **dự án** | Đầu **cuộc hội thoại mới**, gộp tối đa 1 lần/120 giây | Bảng tên dự án được dựng lại ở lượt đầu mỗi cuộc, có chống dội | Đã lưu · áp dụng từ cuộc gọi kế tiếp |
| **3 — Phải xuất bản** | Persona · bật/tắt kỹ năng · rào chắn · thương hiệu · cột nào agent được đọc | Sau khi **Xuất bản**, ≤20 giây, và **chỉ cho phiên MỚI** | Đây là "tính cách" — phải đóng gói, đánh số, kiểm tra được, quay lui được | Bản nháp — chưa ai thấy → Đang áp dụng → Đang phục vụ v12 |

**Bậc 1 và bậc 3 khác nhau ở đâu, nói bằng nghiệp vụ:** giá một căn hộ sai thì sửa xong
phải đúng ngay, không ai chấp nhận "chờ xuất bản". Nhưng câu chữ agent nói với khách thì
**phải** qua một cửa có kiểm tra và có nút quay lui — vì sửa sai một dòng rào chắn có thể
làm agent hứa những thứ nó không làm được, với **mọi** khách hàng, trong **mọi** cuộc gọi,
cho tới khi ai đó phát hiện.

**Bậc 2 tồn tại vì một lý do kỹ thuật có hệ quả nghiệp vụ thật:** agent nhận ra tên dự án
khách **nói** (chịu được nói sai, nói tắt, phiên âm lệch) bằng một bảng tra dựng sẵn.
Bảng đó dựng lại ở đầu mỗi cuộc hội thoại. Nên vừa thêm dự án mới xong mà gọi thử **ngay
trong cuộc đang mở**, agent sẽ không nhận ra tên đó — không phải lỗi, là bậc 2. Giao diện
phải nói câu này, nếu không người dùng sẽ báo bug.

> **Không có `áp dụng ngay lập tức`.** Đánh đổi đã biết và chấp nhận: sửa một rào chắn
> đang nói sai thì cuộc gọi 20 phút đang chạy vẫn dùng bản cũ tới khi kết thúc. Lý do là
> §I.3 Hiệu suất — đổi giữa phiên làm giật độ trễ toàn bộ khách đang gọi. Nếu sau này cần
> một nút "cắt phiên đang chạy", đó là tính năng riêng phải thiết kế riêng, không phải
> nới lỏng quy tắc này.

#### 2.2 Vì sao phải xuất bản chứ không lưu thẳng

Ba lý do, xếp theo mức quan trọng nghiệp vụ:

1. **Quay lui được.** Persona sai không có triệu chứng ngay — nó biểu hiện thành "khách
   phàn nàn agent nói lạ" sau vài giờ. Lúc đó cần quay về bản trước trong một thao tác,
   không phải nhớ mình đã sửa gì.
2. **Biết ai đổi gì lúc nào.** Nhiều người cùng sửa một workspace là chuyện bình thường.
3. **Kiểm tra trước khi phát.** Cửa xuất bản là chỗ duy nhất chặn được cấu hình hỏng
   (thiếu biến, kỹ năng không tồn tại, rào chắn rỗng) trước khi nó tới khách hàng cuối.

**Ranh giới với kiểm thử hành vi:** kiểm tra ở cửa xuất bản là kiểm tra **cấu trúc** — rẻ,
đồng bộ, chạy trong vài trăm mili-giây. Bộ "chạy 24 kiểm thử" là kiểm tra **hành vi** —
tốn LLM call, chạy hàng phút. Hai thứ này **không được** gộp: nếu xuất bản phụ thuộc bộ
kiểm thử hành vi thì dịch vụ kiểm thử chết là **không ai xuất bản được gì**. Quan hệ đúng:
kiểm thử hành vi là **khuyến nghị trên giao diện**, không phải cổng chặn kỹ thuật.

#### 2.3 Vì sao mỗi workspace một agent riêng

Đây là câu hỏi tiền bạc, nên phải trả lời thẳng.

Một agent phục vụ nhiều tenant nghe rẻ hơn, nhưng nó đòi hỏi mọi đường đọc dữ liệu trong
agent đều nhớ lọc theo tenant — và **một chỗ quên là một vụ rò rỉ giữa hai khách hàng**.
Với mô hình một-pod-một-tenant, cách ly do hạ tầng cưỡng chế: pod đó chỉ có thông tin đăng
nhập của đúng một tenant, đọc sai là Postgres từ chối.

**Hệ quả phải chấp nhận và đưa vào giá:** một tenant có chi phí **cố định** kể cả khi
không có cuộc gọi nào. Con số này phải là đầu vào của bảng giá — nếu gói rẻ nhất bán dưới
chi phí pod thì càng nhiều khách càng lỗ.

**"Nuôi sẵn một bể pod trống rồi gán tenant khi cần" là phương án ảo** — đã kiểm trong
code: `TENANT_ID` bị đóng băng qua **ba** singleton tầng tiến trình, nên một container đã
khởi động **không thể** nhận tenant mới; muốn nhận phải khởi động lại, tức không nhanh hơn
tạo mới. Ghi lại ở đây để không ai đề xuất lại.

#### 2.4 Cách ly — ba kho, ba cơ chế

Cách ly không phải một cơ chế duy nhất. Có ba kho, và mỗi kho có cách bảo vệ riêng.

| Kho | Chứa gì | Cách ly bằng gì | Ai ghi | Ai đọc |
|---|---|---|---|---|
| **Postgres** `tenant_data` | Dự án · căn · lịch hẹn · khách quan tâm · **hội thoại** | **RLS + role riêng từng tenant** — Postgres cưỡng chế theo hàng; `VIEW agent_*` gate theo cột | Backend (nhập liệu) + Agent (3 bảng) | Agent (chỉ qua VIEW) + Backend |
| **Kho tệp** | Gói cấu hình đã đóng · **bản ghi thoại** (nếu chốt lưu) | Đường dẫn theo tenant + thông tin đăng nhập theo tenant | Backend (xuất bản) + Agent (thoại) | Agent (chỉ đọc gói) + Backend |
| **Qdrant** | Tài liệu đã lập chỉ mục (knowledge) | **Một collection riêng mỗi tenant** (quyết định #13) | Backend (lúc tải tài liệu lên) | Agent |

**Ba kho là có chủ đích, không phải nợ kỹ thuật.** Postgres cho dữ liệu quan hệ cần RLS.
Kho tệp cho gói bất biến — để agent boot được kể cả khi Postgres chết — và cho khối
chỉ-ghi-thêm như bản ghi thoại. Qdrant cho tìm kiếm ngữ nghĩa. Nhưng phải nói rõ hệ quả:
**thêm một tenant nghĩa là tạo tài nguyên ở cả ba nơi** — kèm một role Postgres và mật khẩu
riêng cho pod — và quy trình cấp phát phải làm hết hoặc không làm gì cả; cấp nửa vời tạo ra
một workspace hỏng khó chẩn đoán.

**Đúng ba kho — Odyssey không dùng Mongo** (chốt 2026-07-29). Kiểm kê cho thấy sau hai
quyết định trước đó, Mongo chỉ còn giữ **chỉ số kỹ thuật**: độ trễ, thời gian tới câu trả
lời đầu tiên, thời gian gọi từng kỹ năng. Một cơ sở dữ liệu phải vận hành, sao lưu, giám
sát — đổi lấy đúng một bảng. Nên nó vào một **schema riêng trong Postgres, không bật cách
ly**.

Chỉ số kỹ thuật **không nằm sau ranh giới cách ly** và không hiện trên dashboard của khách:
nó là telemetry của NobleX, không phải dữ liệu của tenant. Nó đổi chỗ nhưng **không đổi
phía** — vẫn là bằng chứng cho **BR15**: ranh giới nằm ở *dữ liệu của ai*, không phải ở công
nghệ nào.

> **Odyssey không dùng khác gỡ Mongo khỏi agent.** Cùng một mã nguồn agent đang phục vụ
> hai bản chạy: Santa chạy thật trên Mongo, Odyssey xây trên Postgres. Quyết định này nói
> Odyssey không dùng — **không** nói Santa phải tắt. Kéo theo một việc phải chốt trước khi
> code: đường ghi của agent chọn kho theo cấu hình (như đường đọc đã làm), hay đóng băng
> Santa ở một nhánh riêng.

#### 2.5 Cấp phát chạy song song với onboarding

Quan hệ ba lớp có một điểm gãy về thời gian: bước "chat thử ngay" của wizard **cần agent
đã chạy**, nhưng agent chỉ chạy sau khi có người cấp pod.

Cách giải: **portal kích hoạt cấp pod ngay ở bước 1**, rồi khách làm bước 2–3 (15–40 phút
người thật) trong lúc pod đang lên. Không cần thêm hạ tầng gì — vẫn đúng một job CI, chỉ
đổi **ai bấm**.

| Trạng thái | Điều kiện | Ô Thử ngay |
|---|---|---|
| `Đang cấp` | chưa có nhịp tim nào | khoá · hiện tiến trình · cho đi tiếp rồi quay lại |
| `Đang áp dụng` | nhịp tim tươi nhưng phiên bản chạy < phiên bản đã xuất bản | khoá · ≤20 giây |
| `Sẵn sàng` | nhịp tim tươi + phiên bản khớp | mở |
| `Mất kết nối` | nhịp tim cũ | khoá + **báo lỗi thật**, không giả vờ đang chạy |

Bốn trạng thái này **suy ra** từ nhịp tim, không ai bấm, nên tự lành.

### 3. Mô tả màn hình

Bảng này để trả lời một câu duy nhất cho mỗi màn: **màn này là cửa sổ nhìn vào quan hệ
nào?**

| Màn | Đọc từ | Ghi vào | Bậc độ trễ | Lời hứa phải giữ |
|---|---|---|---|---|
| Tổng quan | Backend (tổng hợp) + nhịp tim | — | — | Số liệu là của **workspace này**, không phải toàn nền tảng |
| Agent Studio (persona · kỹ năng · rào chắn) | Bản nháp | Bản nháp → Xuất bản | **3** | Phân biệt rõ *Bản nháp* vs *Đang phục vụ*. Hiện được **diff** trước khi xuất bản |
| Phiên bản & quay lui | `config_versions` | Quay lui = tạo con trỏ mới, **không** tạo phiên bản mới | **3** | Mọi phiên bản cũ vẫn xuất bản lại được |
| Dự án · Quỹ căn | `tenant_data` | `tenant_data` | **1** (nội dung) / **2** (tên dự án) | Đã lưu là đúng cho giá; tên dự án phải nói thêm từ cuộc gọi kế tiếp |
| Tài liệu (knowledge) | Qdrant + siêu dữ liệu | Qdrant | **1**, sau khi lập chỉ mục xong | Phải hiện *Đang lập chỉ mục* → *Sẵn sàng*. Nói Đã lưu khi chưa index xong là nói dối |
| Media | Kho tệp + danh mục | Kho tệp | **1** | Danh mục thuần (quyết định #15) — không có tìm ngữ nghĩa |
| **Hội thoại** | `tenant_data.conversations` | Agent ghi lúc kết thúc cuộc | **1** | Danh sách đọc được **không cần nối bảng** — bản ghi tự mang tên khách, dự án, đã chuyển sales chưa |
| Lịch hẹn | `tenant_data.appointments` | Agent ghi · người sửa | **1** | Lịch agent đặt và lịch người sửa là **cùng một bảng** |
| Người dùng & quyền | `control` | `control` | Tức thì | Đổi quyền có hiệu lực ở phiên đăng nhập kế tiếp |

### 4. Mã lỗi

Đây không phải mã lỗi kỹ thuật — là **trạng thái suy biến người dùng nhìn thấy**. Mỗi
dòng là một màn hình phải thiết kế.

| Mã | Tình huống | Khách hàng cuối | Người dùng dashboard thấy gì |
|---|---|---|---|
| **E01** | Backend chết, agent sống | **Không ảnh hưởng** — agent phục vụ tiếp bằng gói trong đệm đĩa | Dashboard không vào được. Đây là suy biến **đúng** và là lời hứa bán hàng |
| **E02** | Agent chết, backend sống | Cuộc gọi tới workspace này **thất bại** | Mất kết nối + thời điểm nhịp tim cuối. **Không** hiện màn hình giả vờ đang chạy |
| **E03** | Xuất bản xong nhưng agent chưa nạp | Đang dùng bản **cũ** | Đang áp dụng. Quá 20 giây → cảnh báo. Quá 2 phút → coi là lỗi, hiện lý do từ nhịp tim |
| **E04** | Agent tải gói về nhưng kiểm tổng sai | Đang dùng bản **cũ** — agent **giữ nguyên**, không nạp nửa vời | Xuất bản thất bại ở phía agent + lỗi cụ thể. Nút xuất bản lại |
| **E05** | Postgres chết, agent sống | Agent **không trả lời được câu hỏi về dữ liệu** — phải nói thật là chưa tra được và mời chuyển người thật | Cảnh báo hạ tầng |
| **E06** | Qdrant chết | Agent trả lời được câu chung, **không dẫn được tài liệu** | Cảnh báo trên màn Tài liệu |
| **E07** | Cấp pod chậm/lỗi ở onboarding | — | Đang cấp · khách **vẫn đi tiếp được** · onboarding thành hai pha (trường hợp xấu nhất, không phải mặc định) |
| **E08** | Nhập liệu tệp sai định dạng | — | Báo lỗi **theo từng dòng** ở bước chạy thử, **trước** khi ghi. Không bao giờ ghi một phần |

**Nguyên tắc xuyên suốt bảng này:** hệ thống được phép hỏng, **không được phép nói dối**.
E02 hiện Sẵn sàng tệ hơn E02 hiện Mất kết nối — vì người dùng sẽ đi hứa với khách của
họ dựa trên một màn hình sai.

### 5. Business rule

| Mã | Luật | Vì sao — hỏng thì mất gì |
|---|---|---|
| **BR01** | Agent **không bao giờ** gọi Portal API. Agent chỉ nói với kho dữ liệu và kho tệp | Nếu gọi, backend chết là agent chết. Mất chính lời hứa E01 |
| **BR02** | Backend **không bao giờ** gọi xuống agent. Mọi thứ đi lên đều do agent chủ động đẩy | Backend không biết địa chỉ pod (cấp phát là việc của ops). Gọi xuống là tự thêm một phụ thuộc phải quản |
| **BR03** | Ngoại lệ duy nhất cho BR01/BR02: **Thử ngay** — và nó phải đi qua **đúng kênh khách hàng cuối dùng** | Thử qua một đường tắt riêng thì bài thử **không chứng minh gì cả** |
| **BR04** | Mọi thay đổi cấu hình phải qua **Xuất bản**. Không có đường sửa thẳng bản đang chạy | Không có đường sửa thẳng thì không bao giờ có trạng thái "không ai biết đang chạy gì" |
| **BR05** | Một phiên hội thoại giữ **một** phiên bản cấu hình từ đầu tới cuối | Persona không được đổi giữa câu chuyện. Và đổi giữa phiên làm giật độ trễ toàn hệ (§I.3) |
| **BR06** | Phiên bản **bất biến**, đánh số **tăng dần**, không bao giờ ghi đè. Quay lui = trỏ lại bản cũ, **không** tạo bản mới | Ghi đè là mất khả năng quay lui, tức mất giá trị chính của việc đánh phiên bản |
| **BR07** | Xuất bản: **ghi cơ sở dữ liệu trước, ghi con trỏ sau**. Cùng một giao dịch cho cấu hình và chính sách trường dữ liệu | Ngược lại → agent chạy prompt v12 với gate v11: **prompt mới, rào cũ, sai âm thầm** |
| **BR08** | Cách ly do **Postgres cưỡng chế**, không do agent tự nhớ lọc | Một lỗi lập trình trong agent không được phép thành rò rỉ giữa hai khách hàng |
| **BR09** | Agent chỉ ghi được **đúng những bảng nghiệp vụ nó cần**, không đụng bảng cấu hình | Agent bị chiếm quyền cũng không sửa được cấu hình của chính nó |
| **BR10** | Quản trị viên NobleX có quyền control plane nhưng **không đọc `tenant_data`**. Truy cập hỗ trợ phải: có hạn, có ghi vết, **khách đồng ý** | Đây là lời hứa bán hàng NobleX không đọc được dữ liệu của workspace |
| **BR11** | Trạng thái workspace **suy ra** từ nhịp tim, không ai bấm tay | Trạng thái bấm tay luôn lệch thực tế và phải có người đi sửa |
| **BR12** | Cấp phát tenant phải tạo tài nguyên ở **cả ba kho** hoặc không tạo gì | Cấp nửa vời tạo workspace hỏng khó chẩn đoán hơn workspace chưa cấp |
| **BR13** | Nhập liệu tệp luôn qua **chạy thử** trước khi ghi. Chế độ *Thay thế toàn bộ* phải hiện **số hàng sẽ xoá** trước khi áp | Xoá nhầm quỹ căn của một khách là sự cố không sửa được bằng lời xin lỗi |
| **BR14** | Dashboard phải nói **đúng bậc độ trễ** của thứ vừa sửa (§II.2.1) | Nói Đã lưu cho thay đổi bậc 3 là nói dối; người dùng gọi thử không thấy đổi → mất niềm tin vào cả sản phẩm |
| **BR15** | Ranh giới kho là **dữ liệu của ai**, không phải công nghệ nào. Mọi thứ thuộc tenant nằm sau **một** cơ chế cách ly duy nhất; telemetry của NobleX ở ngoài | Hai cơ chế cách ly = lời hứa chỉ mạnh bằng mắt xích yếu nhất, và không kiểm chứng được bằng một bài test. Đây là lý do quyết định #18, không phải vì công nghệ nào hơn |

---

## III. Kết quả đạt được

Sau tài liệu này, nhóm có thể trả lời không cần họp:

- **"Sửa cái này bao giờ agent thấy?"** → tra bảng ba bậc §II.2.1
- **"Màn này lấy dữ liệu từ đâu, ghi vào đâu?"** → bảng §II.3
- **"Backend chết thì khách hàng cuối có sao không?"** → E01: không
- **"Vì sao không cho một agent chạy nhiều tenant cho rẻ?"** → §II.2.3, kèm hệ quả phải đưa vào giá
- **"Agent có được gọi API của portal không?"** → BR01: không, và biết vì sao

Và quan trọng hơn: **ba khoảng trống thiết kế đã lộ ra** trước khi ai kịp code sai.

---

## Câu hỏi cần chốt

### ✅ N5 — ĐÃ CHỐT 2026-07-29: Postgres + RLS

Dữ liệu vận hành **của tenant** về `tenant_data`, cách ly bằng RLS như phần còn lại
(quyết định #18). Bốn thứ agent đang ghi được tách theo bản chất, không gộp làm một:

| Nguồn cũ | Về đâu | Vì sao |
|---|---|---|
| Tóm tắt cuộc gọi | bảng `conversations` | Bản ghi vận hành — thứ tenant lọc, sắp xếp, xuất báo cáo |
| Sự kiện cuộc gọi | cột `events` trong cùng hàng | ≤1 KB, tự xoá sau 30 ngày, chỉ để gỡ lỗi. Không đáng một bảng |
| Hồ sơ tích luỹ theo SĐT | gộp vào `contacts` | **Trùng khái niệm** — cùng là thông tin tích luỹ về một người. Hai chỗ là tự tạo câu hỏi cái nào đúng |
| Chỉ số phiên (độ trễ, TTFA) | **ở lại Mongo** | Telemetry của NobleX, **không phải dữ liệu tenant** — xem BR15 |

**Lý do không phải Mongo kém.** Mongo cách ly thật được: collection riêng mỗi tenant +
role trỏ đúng collection đó là ranh giới do máy chủ cưỡng chế. Cái bị loại là **hai kho
cho cùng một loại dữ liệu** — vì hồ sơ tích luỹ và `contacts` là một khái niệm, và vì xoá
theo số điện thoại (NĐ 13) ở hai kho là hai lệnh không chung giao dịch, hỏng giữa chừng thì
đã xoá nửa vời mà không chứng minh được.

**Một lập luận của tôi đã bị hạ xuống, ghi lại để không ai dựng lại:** ban đầu tôi lấy màn
Hội thoại cần nối bảng làm lý do chính. Sai — bản ghi tóm tắt **đã được cố ý làm phẳng**,
tự mang tên khách, dự án, trạng thái chuyển sales. Màn danh sách không cần nối gì. Việc nối
chỉ cần ở màn chi tiết, khách hàng 360 và số liệu tổng quan.

**Dung lượng:** ~3 KB một cuộc gọi ⇒ 50 tenant × 100 cuộc/ngày ≈ **5,5 GB/năm**. Mối lo ban
đầu là không có thật.

### ✅ N5b — ĐÃ CHỐT 2026-07-29: có lưu, giữ 6 tháng

Nội dung ở kho tệp, hàng `conversations` giữ con trỏ (~30 KB/cuộc, ≈8 GB nén cho 50
workspace). Hạn 6 tháng khớp quyết định retention đã có, tenant tự đặt được. Prototype đang
hứa màn Hội thoại xem lại được đoạn chat — lời hứa đó **giữ được**, không phải sửa.

**⚠️ Đây là chữ, không phải tiếng.** Quyết định retention cũ có nhắc ghi âm, nhưng hệ
thống **không ghi âm ở bất kỳ đâu** — đường web và tổng đài đều truyền tiếng rồi bỏ. Muốn
tenant **nghe lại** cuộc gọi là một quyết định riêng, đắt hơn một bậc lớn: ~1 MB mỗi phút so
với ~30 KB mỗi cuộc, cộng phơi nhiễm pháp lý khác vì giọng nói là dữ liệu sinh trắc. Chưa ai
yêu cầu — ghi ra để không ai tưởng đã có.

**✏️ Đính chính (29/7, sau khi rà lại code).** Lúc trình bày N5b tôi nói *"nội dung hội thoại
không được lưu bền vững ở đâu cả"* — **sai**. Có một kho đang lưu bản ghi thoại theo từng
lượt, và màn chi tiết của CMS đọc từ đó. Quyết định **không đổi**, phần việc **nhỏ hơn** đã
nói, nhưng ba khiếm khuyết sau là thật:

| # | Khiếm khuyết | Hệ quả |
|---|---|---|
| 1 | **Bỏ hẳn lời gọi kỹ năng và kết quả** — chỉ giữ lời khách và lời agent | Không trả lời được *vì sao agent nói thế* — **đúng lý do chính đã quyết lưu**. Đối chất được lời nói, không đối chất được hành vi |
| 2 | **Không có chỉ mục nào** | Mở màn chi tiết là **quét toàn bộ kho**. Càng nhiều cuộc gọi càng chậm, không có điểm dừng |
| 3 | **Không có hạn lưu, và bản ghi không mang số điện thoại** | Lớn vô hạn, và **xoá theo số điện thoại chưa làm được** — tức nghĩa vụ NĐ 13 đang hở |

Nên việc thật là **chuyển + vá**, không phải xây mới.

**Lưu gì:** lượt khách nói · lượt agent trả lời · **tên kỹ năng được gọi kèm tham số và kết
quả** · **con trỏ tới phiên bản cấu hình**.

Hai chi tiết đáng giải thích:

- **Kết quả kỹ năng phải lưu**, vì nó mới là thứ trả lời *vì sao agent nói thế*. Thiếu nó
  thì không đối chất được, cũng không kiểm được rào chắn — tức mất đúng hai lý do đã quyết lưu.
- **Không lưu bản persona đã render.** Persona đã được đánh phiên bản và giữ bất biến rồi;
  muốn biết agent lúc đó chạy luật nào thì tra số phiên bản. Lưu lại mỗi cuộc gọi là nhân đôi
  dữ liệu cho **không thêm thông tin nào**.

**Hai việc mới sinh ra:**

1. **Job xoá quá hạn phải có giám sát.** 6 tháng giờ nằm trong hợp đồng với khách. Hứa mà
   không dọn còn tệ hơn không hứa — vì đã nói với khách rồi.
2. **Ai được đọc — chưa có câu trả lời, gắn vào N4.** Bản ghi thoại là thứ nhạy cảm nhất
   trong hệ: tên, số điện thoại, ngân sách, hoàn cảnh gia đình của khách hàng cuối. Ma trận
   vai trò phải nói rõ vai trò *Viewer* có đọc được không. Kèm ràng buộc hạ tầng: **BR10 phải
   áp cả cho kho tệp**, không chỉ Postgres — nếu không thì lời hứa NobleX không đọc được dữ
   liệu workspace thủng ở đúng chỗ nhạy nhất.

### N6 — Đường `/api/v1/sales/*` hiện tại xử lý thế nào?

`santa-agent-cms` đang chạy được phần lớn màn vận hành **qua đường này**. Thiết kế ghi
"rủi ro thấp vì đã có bản chạy được" — nhưng bản chạy được đó gắn vào một đường **không có
phạm vi tenant**. Phải chốt: viết lại theo N5, hay giữ tạm cho Noble rồi thay ở sub-project
#4? Nếu giữ tạm thì **phải có ngày tắt**, nếu không nó sẽ thành vĩnh viễn.

### N7 — Nhịp tim bao lâu thì coi là "cũ"?

Bảng trạng thái §II.2.5 và E02/E03 đều dựa vào chữ "tươi"/"cũ" mà chưa có con số. Cần
chốt hai ngưỡng: bao lâu không có nhịp tim thì hiện Mất kết nối, và Đang áp dụng quá
bao lâu thì đổi thành lỗi. Đề xuất: **60 giây** và **2 phút** (gấp 3 và gấp 6 chu kỳ dò
20 giây). Người quyết: kỹ thuật.

---

## TODO

- [x] ~~Chốt **N5**~~ — xong 2026-07-29, Postgres + RLS (quyết định #18)
- [x] ~~Ước lượng **dung lượng Postgres cho hội thoại**~~ — ~3 KB/cuộc, ≈5,5 GB/năm cho 50 tenant
- [x] ~~Chốt **N5b**~~ — xong 2026-07-29: có lưu, giữ 6 tháng
- [x] ~~Chốt **N8**~~ — xong 2026-07-29: bỏ Mongo khỏi Odyssey (quyết định #20)
- [ ] Chốt **N9** — đường ghi của agent chọn kho theo cấu hình, hay đóng băng Santa ở nhánh riêng. **Phải chốt trước lát 1e**
- [ ] **Vá 3 khiếm khuyết bản ghi thoại**: thiếu lời gọi kỹ năng · không chỉ mục · không xoá được theo SĐT
- [ ] Chốt **N6** — có ngày tắt cho đường `/api/v1/sales/*` nếu giữ tạm
- [ ] Chốt **N7** — hai ngưỡng nhịp tim
- [ ] **N4 nay có thêm một câu bắt buộc:** vai trò nào đọc được bản ghi thoại. N4 vẫn chưa có người nhận
- [ ] **Có cần nghe lại cuộc gọi không** (tiếng, không phải chữ) — nếu có thì là quyết định riêng, đắt hơn một bậc
- [ ] Ước lượng **chi phí cố định một pod/tháng** → đầu vào bảng giá (§II.2.3)
- [ ] Wireframe cho **trạng thái Bản nháp / Đang áp dụng / Đang phục vụ** — BR14 không thực thi được nếu không có thiết kế
- [ ] Wireframe cho **E02 · E03 · E04** — ba màn suy biến chưa ai vẽ
