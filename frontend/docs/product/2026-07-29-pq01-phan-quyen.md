# PQ_01 — Phân quyền

| Phiên bản | Ngày | Người viết | Thay đổi |
|---|---|---|---|
| v1.0 | 2026-07-29 | BA | Bản đầu. Giải quyết **N4**. Hai mặt phẳng quyền, 4 vai trò song song, 13 nhóm hành động, quyền đọc bản ghi thoại tách riêng, cấp quyền hỗ trợ có hạn. |

**Giải quyết:** N4 (chặn gói A và gói F) · câu hỏi *"vai trò nào đọc được bản ghi thoại"* từ quyết định P8.

---

## I. Tổng quan

### 1. Mô tả

Hệ thống có **hai mặt phẳng quyền hoàn toàn tách rời**. Gộp chúng là sai lầm đắt nhất có thể
phạm ở đây, vì nó phá thẳng lời hứa bán hàng.

| Mặt phẳng | Ai | Trả lời câu hỏi |
|---|---|---|
| **Nền tảng** | Nhân sự NobleX | Ai được tạo workspace, đình chỉ, xem tình trạng vận hành, xem số liệu tính tiền |
| **Workspace** | Người dùng của khách hàng | Trong **một** workspace, ai được làm gì |

**Quản trị viên nền tảng KHÔNG tự động là quản trị của mọi workspace.** Đó chính là điều
quyết định P5 / A10 cấm. Muốn vào trong một workspace, nhân sự NobleX phải đi qua **cấp quyền
hỗ trợ có hạn** (§II.2.5) — cùng một cửa như mọi người khác, chỉ khác là tấm vé có hạn.

### 2. Yêu cầu chức năng

| # | Yêu cầu |
|---|---|
| YC01 | Một người dùng thuộc được **nhiều workspace**, mỗi nơi một vai trò khác nhau |
| YC02 | Quản trị workspace mời người, đổi vai trò, gỡ người — không cần NobleX can thiệp |
| YC03 | **Gỡ quyền có hiệu lực ngay**, không chờ phiên đăng nhập hết hạn |
| YC04 | Workspace **luôn có ít nhất một quản trị** — hệ thống chặn thao tác làm mất người cuối cùng |
| YC05 | **Đọc bản ghi thoại là một quyền riêng**, không nằm trong quyền xem hội thoại |
| YC06 | Mỗi lần đọc bản ghi thoại **được ghi vào nhật ký**, quản trị workspace xem được |
| YC07 | Nhân sự NobleX vào được dữ liệu workspace **chỉ khi khách bấm đồng ý**, có hạn, có ghi vết |
| YC08 | Quyền hỗ trợ **tự hết hạn**, không ai phải nhớ đi thu hồi |
| YC09 | Nhật ký hoạt động **không ai sửa hay xoá được**, kể cả quản trị workspace |

### 3. Yêu cầu phi chức năng

**Bảo mật.** Ba tầng cưỡng chế, mỗi tầng trả lời **một** câu khác nhau — §II.2.1. Nguyên tắc
xuyên suốt: **giao diện ẩn nút không phải là bảo vệ.** Mọi quyền phải được kiểm ở tầng API;
ẩn nút chỉ để đỡ rối mắt.

**Hiệu suất.** Vai trò đọc từ cơ sở dữ liệu **mỗi request**, không lấy từ phiếu đăng nhập
(§II.2.3). Nghe như thêm một truy vấn, nhưng mọi request đã buộc phải nằm trong một giao dịch
rồi (ràng buộc cách ly), nên chi phí gần bằng không.

**Khả dụng.** Mất kết nối tới cơ sở dữ liệu ⇒ **từ chối**, không cho qua. Quyền là thứ duy
nhất trong hệ này hỏng theo chiều đóng, không phải chiều mở.

**Giao diện UX.** Người dùng thấy **lý do** bị chặn, không phải một nút xám vô nghĩa: *"Việc
này cần vai trò Quản trị. Người quản trị workspace: Trần Hải Đăng."* Nút xám không giải thích
là nguồn của mọi ticket hỗ trợ.

**Khả năng mở rộng.** Bốn vai trò **cố định**, không cho tự định nghĩa (§III). Danh sách hành
động mở rộng được mà không đụng vai trò.

---

## II. Mô tả tính năng

### 1. Luồng nghiệp vụ

```
MỜI NGƯỜI
  Quản trị nhập email + chọn vai trò
    → gửi thư mời (hạn 7 ngày)
    → người nhận đặt mật khẩu → thành viên
    → ghi nhật ký: ai mời ai, vai trò gì

ĐỔI VAI TRÒ / GỠ NGƯỜI
  Quản trị đổi → CÓ HIỆU LỰC NGAY ở request kế tiếp của người đó
    → chặn nếu đây là quản trị cuối cùng
    → ghi nhật ký

MỖI REQUEST
  phiếu đăng nhập → xác định NGƯỜI (chỉ vậy, không mang vai trò)
    → mở giao dịch, đặt phạm vi workspace
    → đọc vai trò từ bảng thành viên  ← nguồn sự thật, không phải phiếu
    → kiểm hành động có nằm trong vai trò không
    → không có vai trò trong workspace này ⇒ TỪ CHỐI

NOBLEX CẦN VÀO HỖ TRỢ
  Nhân sự NobleX gửi yêu cầu, ghi lý do
    → Quản trị workspace nhận thông báo, BẤM ĐỒNG Ý
    → hệ thống tạo một hàng thành viên TẠM, có hạn (mặc định 24 giờ)
    → mọi thao tác vào nhật ký, khách xem được
    → hết hạn tự mất, không ai phải thu hồi
```

### 2. Diễn giải

#### 2.1 Ba tầng cưỡng chế — mỗi tầng một câu hỏi khác nhau

Đây là chỗ hay bị gộp nhầm nhất, và gộp nhầm thì tưởng an toàn mà không phải.

| Tầng | Trả lời | Cưỡng chế bởi |
|---|---|---|
| **Cách ly workspace** | *"hàng này thuộc workspace nào"* | Cơ sở dữ liệu, tự động theo danh tính kết nối |
| **Quyền vai trò** | *"người này có được làm hành động này không"* | Portal API, kiểm ở mọi endpoint |
| **Giao diện** | *"có nên hiện nút này không"* | Ẩn/khoá — **không phải bảo vệ** |

> **Tầng 1 không thay được tầng 2.** Cách ly ở cơ sở dữ liệu trả lời *"hàng của workspace
> nào"*, nó **không** trả lời *"người này có được xoá không"*. Một Viewer đọc đúng workspace
> của mình vẫn đi qua tầng 1 sạch sẽ — chỉ tầng 2 mới chặn được việc họ xoá dự án. Đây là
> nhầm lẫn kinh điển và hậu quả là một lỗ hổng không ai thấy khi đọc code.

#### 2.2 Bốn vai trò — song song, không phải bậc thang

CMS hiện dùng bậc thang tuyến tính (`viewer < sales < manager < admin`): vai trò cao gồm trọn
quyền của vai trò thấp. Đơn giản, nhưng **sai với nghiệp vụ ở đây**.

Chăm sóc khách hàng và nhập liệu dự án là **hai nghề khác nhau**, không phải hai cấp bậc. Một
CSKH không "cao hơn" nhân viên nhập liệu; họ làm việc khác. Ép vào bậc thang thì hoặc CSKH
được sửa quỹ căn (không ai muốn), hoặc nhân viên nhập liệu đọc được hội thoại khách (càng
không muốn — đó là dữ liệu cá nhân).

Prototype đã dùng mô hình song song. **Giữ.**

| Vai trò | Người thật là ai | Việc chính |
|---|---|---|
| **Quản trị** | Chủ sàn · trưởng phòng kinh doanh | Toàn quyền: cấu hình agent, xuất bản, mời người, cài đặt |
| **CSKH** | Telesales · chăm sóc khách hàng | Đọc hội thoại, nhận chuyển tiếp, quản lịch hẹn |
| **Biên tập** | Trợ lý kinh doanh · nhân viên nhập liệu | Dự án, quỹ căn, tài liệu, media |
| **Người xem** | Giám đốc · kế toán | Chỉ đọc số liệu và tóm tắt |

**Đặt tên phải nhất quán — hiện đang không.** Prototype ghi `Tenant Admin` / `Data Editor` ở
danh sách thành viên nhưng `Admin` / `Editor` ở ma trận. Thêm nữa, `Tenant Admin` **vi phạm
quyết định #12** (UI không dùng từ `tenant`). Chốt tên tiếng Việt cho giao diện, tên kỹ thuật
cho code:

| Giao diện (VI) | Giao diện (EN) | Trong code |
|---|---|---|
| Quản trị | Admin | `admin` |
| CSKH | Customer care | `care` |
| Biên tập | Editor | `editor` |
| Người xem | Viewer | `viewer` |

#### 2.3 Vai trò đọc từ cơ sở dữ liệu, không lấy từ phiếu đăng nhập

CMS nhét vai trò vào phiếu đăng nhập (hạn 15 phút). Hệ quả: **sa thải một người xong, 15 phút
nữa họ vẫn sửa được dữ liệu.** Với một công cụ nội bộ thì chấp nhận được. Với sản phẩm bán
cho nhiều khách hàng thì không — YC03 nói rõ.

Cách sửa rẻ hơn người ta tưởng: **phiếu đăng nhập chỉ định danh NGƯỜI; vai trò đọc từ bảng
thành viên mỗi request.** Nghe như thêm một truy vấn, nhưng ràng buộc cách ly **đã buộc mọi
request phải nằm trong một giao dịch** — nên việc đọc thêm một hàng đi cùng chuyến, gần như
miễn phí. Đổi lại: gỡ quyền có hiệu lực **ngay**, không có cửa sổ 15 phút.

#### 2.4 Đọc bản ghi thoại là quyền riêng — đây là câu P8 để lại

Bản ghi thoại chứa nguyên văn khách hàng cuối nói: tên, số điện thoại, ngân sách, hoàn cảnh
gia đình. Đó là thứ nhạy cảm nhất trong hệ thống.

**Tách khỏi quyền "xem hội thoại".** Lý do bằng nghiệp vụ:

- **Giám đốc** cần biết *bao nhiêu cuộc, bao nhiêu ra lịch hẹn* — không cần đọc khách kể
  chuyện gia đình
- **CSKH** cần đọc nguyên văn để tiếp tục chăm sóc — có nhu cầu thật
- **Biên tập** không có lý do gì để đọc

Mặc định: **Quản trị + CSKH đọc được. Biên tập + Người xem không.**

> **Mỗi lần đọc đều vào nhật ký** — không phải "ai đăng nhập", mà **"ai đã đọc hội thoại nào,
> lúc nào"**. Đây là thứ biến lời hứa riêng tư thành cái kiểm chứng được, và nó gần như không
> tốn gì. Không có nó thì khi khách hỏi *"ai trong công ty tôi đã xem cuộc gọi này"*, câu trả
> lời là im lặng.

#### 2.5 Cấp quyền hỗ trợ — một cửa, một tấm vé có hạn

NobleX sẽ có lúc cần vào workspace để gỡ lỗi. Vấn đề: BR10 nói NobleX **không đọc được** dữ
liệu workspace. Hai điều này chỉ dung hoà được bằng một thiết kế cụ thể.

**Nguyên tắc: không có cửa sau, chỉ có một cửa với một tấm vé có hạn.**

Cụ thể: quyền hỗ trợ **không phải một cờ bỏ qua kiểm tra**, mà là **một hàng thành viên tạm
thời có ngày hết hạn**. Khác biệt này quyết định:

| Nếu làm bằng cờ bỏ qua | Nếu làm bằng thành viên tạm |
|---|---|
| Tồn tại một nhánh code mà BR10 **không áp dụng** | Chỉ có **một** đường kiểm tra quyền, không có ngoại lệ |
| Nhánh đó sớm muộn cũng bị chạm nhầm | Không có gì để chạm nhầm |
| Ghi vết phải nhớ cài riêng | Đi chung đường ghi vết với mọi thao tác |

Điều kiện bắt buộc:

1. **Khách bấm đồng ý** — quản trị workspace, không phải NobleX tự cấp
2. **Có hạn** — mặc định 24 giờ, tối đa 7 ngày, tự hết
3. **Có lý do** ghi rõ, khách đọc được
4. **Mọi thao tác vào nhật ký**, khách xem được và **xuất được**
5. **Thu hồi bất cứ lúc nào** bằng một nút

#### 2.6 Sửa bản nháp và Xuất bản là hai quyền khác nhau

Ở MVP chỉ Quản trị chạm Agent Studio nên chưa thấy khác biệt. Vẫn **tách ngay từ đầu**, vì
xuất bản đổi thứ **mọi khách hàng cuối** nghe thấy, còn sửa bản nháp thì không ai thấy. Hai
mức rủi ro cách nhau rất xa, và khi có vai trò thứ năm (một người viết nội dung chẳng hạn)
thì thiết kế đã đúng sẵn, không phải sửa.

Cùng lý do đó: **quay lui** là quyền của Quản trị, không phải của người sửa.

### 3. Mô tả màn hình

#### 3.1 Ma trận quyền đầy đủ

Prototype có 4 dòng — đó là demo. Đây là 13 nhóm thật.

| # | Nhóm hành động | Quản trị | CSKH | Biên tập | Người xem |
|---|---|:---:|:---:|:---:|:---:|
| 1 | Xem Tổng quan · số liệu | ✓ | ✓ | ✓ | ✓ |
| 2 | Xem danh sách Hội thoại + tóm tắt | ✓ | ✓ | ✓ | ✓ |
| 3 | **Đọc bản ghi thoại** (§2.4) | ✓ | ✓ | — | — |
| 4 | Nhận chuyển tiếp · đánh dấu đã xử lý | ✓ | ✓ | — | — |
| 5 | Xem Lịch hẹn | ✓ | ✓ | ✓ | ✓ |
| 6 | Sửa · huỷ Lịch hẹn | ✓ | ✓ | — | — |
| 7 | Xem Dự án · Quỹ căn · Tài liệu · Media | ✓ | ✓ | ✓ | ✓ |
| 8 | Thêm · sửa · nhập tệp Dự án · Quỹ căn · Tài liệu · Media | ✓ | — | ✓ | — |
| 9 | **Xoá** dự án · quỹ căn · tài liệu · media | ✓ | — | ✓ | — |
| 10 | Xem cấu hình agent (chỉ đọc) | ✓ | ✓ | ✓ | ✓ |
| 11 | Sửa bản nháp cấu hình agent | ✓ | — | — | — |
| 12 | **Xuất bản · Quay lui** (§2.6) | ✓ | — | — | — |
| 13 | Khoá API · Thành viên · Cài đặt workspace · Yêu cầu của khách | ✓ | — | — | — |

Nhật ký hoạt động: **mọi vai trò xem được phần việc của chính mình**; Quản trị xem toàn
workspace. Không ai sửa hay xoá được (YC09) — nhật ký sửa được thì không chứng minh được gì.

#### 3.2 Màn Thành viên

| Thành phần | Ghi chú |
|---|---|
| Danh sách thành viên | Tên · email · vai trò · hoạt động gần nhất · trạng thái lời mời |
| Nút **Mời** | Email + vai trò. Hạn lời mời 7 ngày |
| Đổi vai trò tại chỗ | **Chặn** nếu là quản trị cuối cùng (YC04), kèm câu giải thích |
| Gỡ thành viên | Xác nhận riêng. Cùng ràng buộc quản trị cuối cùng |
| **Ma trận quyền** | Hiện đủ 13 dòng §3.1, không rút gọn — người dùng chọn vai trò dựa vào bảng này |
| Khối **Quyền hỗ trợ NobleX** | Trạng thái hiện tại · lịch sử cấp · nút thu hồi. **Mặc định: không có ai** |

### 4. Mã lỗi

| Mã | Tình huống | Người dùng thấy gì |
|---|---|---|
| **Q01** | Không có vai trò trong workspace này | Bạn không có quyền truy cập workspace này — **không** tiết lộ workspace có tồn tại hay không |
| **Q02** | Có vai trò nhưng thiếu quyền cho hành động | Việc này cần vai trò Quản trị. Người quản trị: Trần Hải Đăng — **nêu tên người xin được** |
| **Q03** | Gỡ/hạ vai trò quản trị cuối cùng | Workspace phải có ít nhất một Quản trị. Bổ nhiệm người khác trước. |
| **Q04** | Vai trò bị đổi giữa lúc đang thao tác | Từ chối request đang chạy + tải lại giao diện theo vai trò mới. **Không** để giao diện cũ thao tác tiếp |
| **Q05** | Quyền hỗ trợ hết hạn giữa chừng | Phiên NobleX bị cắt ngay, ghi nhật ký. Muốn tiếp thì xin lại |
| **Q06** | Không đọc được bảng thành viên | **TỪ CHỐI** — quyền hỏng theo chiều đóng, không phải chiều mở |
| **Q07** | Lời mời hết hạn | Lời mời đã hết hạn, nhờ quản trị gửi lại |

### 5. Business rule

| Mã | Luật | Vì sao |
|---|---|---|
| **BR-Q01** | Hai mặt phẳng quyền **tách rời**. Quản trị nền tảng **không** tự động là quản trị workspace | Gộp là phá thẳng P5/BR10 — lời hứa bán hàng |
| **BR-Q02** | Cách ly workspace và quyền vai trò là **hai cơ chế**, không thay thế nhau (§2.1) | Cách ly ở cơ sở dữ liệu không chặn được Viewer xoá dữ liệu của chính workspace mình |
| **BR-Q03** | **Giao diện ẩn nút không phải bảo vệ.** Mọi quyền kiểm ở tầng API | Ẩn nút chỉ chặn người dùng lịch sự |
| **BR-Q04** | Vai trò đọc từ cơ sở dữ liệu **mỗi request**, không từ phiếu đăng nhập (§2.3) | Gỡ quyền phải có hiệu lực ngay, không có cửa sổ 15 phút |
| **BR-Q05** | Workspace **luôn ≥ 1 Quản trị** | Mất hết quản trị = phải nhờ NobleX vào sửa, tức phải phá BR10 |
| **BR-Q06** | **Đọc bản ghi thoại là quyền riêng**, mặc định chỉ Quản trị + CSKH | Dữ liệu cá nhân của khách hàng cuối — người xem số liệu không cần |
| **BR-Q07** | **Mỗi lần đọc bản ghi thoại vào nhật ký**, quản trị workspace xem được | Biến lời hứa riêng tư thành thứ kiểm chứng được |
| **BR-Q08** | Quyền hỗ trợ NobleX = **thành viên tạm có hạn**, không phải cờ bỏ qua (§2.5) | Cờ bỏ qua tạo một nhánh code mà BR10 không áp dụng |
| **BR-Q09** | Quyền hỗ trợ cần **khách bấm đồng ý** + có lý do + tự hết hạn | Không có cái nào trong ba, "có hạn" chỉ là chữ |
| **BR-Q10** | Nhật ký **chỉ ghi thêm** — không ai sửa hay xoá, kể cả Quản trị workspace | Nhật ký sửa được không chứng minh được gì |
| **BR-Q11** | Quyền hỏng theo **chiều đóng**: không xác định được vai trò ⇒ từ chối | Đây là thứ duy nhất trong hệ không được hỏng theo chiều mở |
| **BR-Q12** | **Sửa bản nháp ≠ Xuất bản** (§2.6) | Xuất bản đổi thứ mọi khách hàng cuối nghe thấy |
| **BR-Q13** | Không tiết lộ workspace có tồn tại hay không cho người ngoài (Q01) | Thông điệp lỗi là kênh rò rỉ hay bị quên |

---

## III. Ngoài phạm vi MVP — ghi ra để không ai tự làm

| Không làm | Vì sao |
|---|---|
| Vai trò tự định nghĩa | 4 vai trò cố định phủ hết nghiệp vụ đã biết. Vai trò tuỳ biến là một sản phẩm riêng |
| Quyền theo từng dự án | Khách MVP là một sàn với một quỹ dự án chung. Chưa có nhu cầu thật |
| Nhóm người dùng | Có ý nghĩa khi ≥ 20 người/workspace. Prototype đang giả định 8 |
| Đăng nhập một lần (SSO/SAML) | Khách doanh nghiệp lớn mới cần. Chưa có |
| Quyền theo giờ / theo IP | Chưa ai yêu cầu |

---

## Kết quả đạt được

- **N4 đóng** — gói A và gói F hết bị chặn
- Câu hỏi P8 để lại (*vai trò nào đọc được bản ghi thoại*) có câu trả lời: **Quản trị + CSKH**, và **mọi lần đọc đều được ghi vết**
- Ma trận từ 4 dòng demo lên **13 nhóm thật**, đủ để dev biết chặn ở đâu
- Tên vai trò nhất quán, bỏ `Tenant Admin` vốn vi phạm quyết định #12

## TODO

- [ ] Sửa prototype: tên vai trò nhất quán · ma trận 4 → 13 dòng · khối Quyền hỗ trợ NobleX (chưa có)
- [ ] Wireframe **màn xin/duyệt quyền hỗ trợ** — chưa ai vẽ, và nó là chỗ chứng minh BR10
- [ ] Chốt hạn mặc định của quyền hỗ trợ (đề xuất 24 giờ) và hạn tối đa (đề xuất 7 ngày)
- [ ] Chốt nhật ký giữ bao lâu — **không** nên theo hạn 6 tháng của dữ liệu khách; nhật ký nên giữ lâu hơn
