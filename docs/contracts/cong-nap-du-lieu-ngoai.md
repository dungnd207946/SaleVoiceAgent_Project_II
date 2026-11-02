# Cổng nạp dữ liệu ngoài — tài liệu bàn giao cho đội kỹ thuật bên khách

> Seam: hệ thống CRM/ERP của **khách hàng** → NobleX Agent Platform. Adapter do đội kỹ
> thuật bên khách viết và vận hành; tài liệu này là thứ đưa cho họ kèm điểm nạp
> và token. Bản mềm tiếng Việt; mọi tên trường là tiếng Anh.

## Những gì được bàn giao

| Thứ | Lấy ở đâu |
|---|---|
| Điểm nạp (`POST …/ingest/realestate/v1/events`) | Màn **Nguồn dữ liệu** của portal, khối Endpoint |
| Token nạp (`ody_in_…`) | Cùng màn đó — quản trị workspace tự phát, xem lại được bất cứ lúc nào |
| Tham chiếu trường theo thực thể + ví dụ | **Swagger** — nút «Tài liệu» cạnh điểm nạp. SINH từ sổ hợp đồng nên luôn đúng với server đang chạy; tài liệu này cố ý KHÔNG chép lại bảng trường |
| Adapter mẫu chạy được | `scripts/demo_cong_nap_e2e.py` (repo backend) — phủ trọn mọi ngữ nghĩa bên dưới, đọc nó trước khi viết adapter thật |

Xác thực: `Authorization: Bearer <token>`. Token gắn với MỘT workspace và MỘT
lĩnh vực — `401` nghĩa là token sai/đã xoá; `429` nghĩa là token ĐÚNG nhưng gọi
quá nhịp, kèm header `Retry-After` (số giây) — **đừng phát lại token khi gặp 429**.

## Token đổ vào đâu — `GET …/whoami`

Token **ghim workspace tại lúc tạo**. Muốn đẩy sang workspace khác thì tạo token
MỚI *trong workspace đó* (kiểm tra bộ chuyển workspace của portal đang đứng đúng
chỗ trước khi bấm phát) rồi thay vào adapter — giữ token cũ là dữ liệu tiếp tục
về chỗ cũ, và vì dữ liệu ở đó đã y hệt nên mọi lượt đẩy trả `stale` toàn bộ:
adapter báo XANH mà workspace mới trống trơn.

`GET …/whoami` (cùng Bearer) trả `{"workspaceId", "workspaceName"}` — adapter
nên gọi mỗi lượt chạy và hiện tên workspace cho người vận hành, để nhầm đích là
thấy ngay thay vì đi lần theo «sync xanh mà không có dữ liệu». Nhịp tính chung
cửa `/events`.

## Đường đẩy — `POST …/events`

Lô tối đa **500 bản ghi**, mỗi bản ghi có VỎ cố định
(`entity` · `externalId` · `op` · `occurredAt` · `data`) và `data` theo thực thể
(5 thực thể: `project` · `zone` · `unit` · `document` · `media` — bảng trường ở Swagger).

Ngữ nghĩa quan trọng, theo thứ tự hay vấp:

1. **Kết quả TỪNG bản ghi, HTTP luôn 200.** Đọc `results[]`: `accepted` /
   `rejected` (kèm `field` + `reason` tự sửa được) / `stale`. Một bản hỏng không
   làm rớt phần còn lại.
2. **`occurredAt` bắt buộc có múi giờ** và là trọng tài thứ tự — sự kiện cũ hơn
   bản đang có trả `stale` (không phải lỗi; retry vô hại).
3. **Bản mới hơn thay TRỌN bản ghi** — trường vắng mặt về rỗng. Luôn gửi đủ
   trường bạn có, đừng gửi diff.
4. **Con tới trước cha là hợp lệ** — không cần sắp thứ tự; bản ghi con tự hiện
   khi cha tới. Khoá cha (`projectExternalId`…) dùng **mã của chính bạn**.
5. **`op: "delete"`** chỉ cần `externalId` (`data` bỏ trống) — xoá MỀM phía
   nền tảng: `status` → `archived`, agent không thấy nữa; `upsert` lại là sống lại.
6. **`?dryRun=true`** — kiểm cả lô, không ghi gì. Dùng suốt giai đoạn dev.
7. Trường lạ trong `data` bị bỏ qua im lặng (hệ thống của bạn mọc cột mới không
   sao); gõ sai VỎ (`externalID`, thiếu múi giờ…) là `422` cho cả request.
8. Bản ghi bị từ chối hiện ở màn **Nguồn dữ liệu → Lỗi gần đây** của portal —
   quản trị workspace của bạn tự xem được, không cần hỏi NobleX.
9. **`project.data.code` (tuỳ chọn, nên gửi):** mã dự án người-đọc-được — gửi
   slug của chính bạn (`sunshine-city-hanoi` → mã `SUNSHINE_CITY_HANOI`). Không
   gửi thì mã suy từ `externalId`; nếu `externalId` là UUID thì mã thành chuỗi
   hex 36 ký tự — vẫn chạy đúng, nhưng agent tốn token chép nó vào mọi tool call
   và báo cáo đối soát khó đọc. **Chỉ có tác dụng lúc TẠO** — update mang `code`
   khác bị bỏ qua (mã là khoá neo của căn/media/phiên agent đang sống).
10. **Tour 360 gửi qua `project.link360`**, không gửi media `contentType: tour_360`
    — nền tảng tự sinh một hàng media mỗi dự án và tự cập nhật/xoá theo link.
11. **`document.fileUrl`** (PDF · DOCX · XLSX · ảnh, URL công khai): nền tảng tải về,
    **bóc chữ** và nối sau `body` — `body` chỉ cần tóm tắt/siêu dữ liệu (markdown
    được). PDF scan / ảnh đọc bằng OCR cần quản trị workspace **duyệt** trong portal
    trước khi agent thấy.
12. **Ảnh/video tiến độ** (`category: tien_do`): `caption` theo khuôn
    **`Tiến độ dd/mm/yyyy — <tên mốc>[ — <chú thích riêng>]`** — timeline tiến độ
    trên portal nhóm theo tiền tố này; caption khác khuôn rơi về ngày nhận.
13. **`video`**: `mediaUrl` là URL **trang** video (YouTube, Google Drive…), không
    phải tệp mp4 — YouTube và Google Drive nhúng được trong app, host khác chỉ mở
    link. `fileName` là tên hiển thị của media (đứng trước `caption`); video bỏ trống.

## Đường đối soát — `POST …/manifest`, chạy hằng đêm

Gửi ảnh chụp `{externalId, updatedAt}` của **toàn bộ những gì đang tồn tại** bên
bạn cho một thực thể. Response là hành động luôn:

- `externalIdLech` — bạn mới hơn: **đẩy lại các mã này qua `/events`** (không có
  webhook gọi ngược; response này chính là yêu cầu).
- `externalIdNghiMatTich` — nền tảng có mà bản kê không có: chỉ GẮN CỜ để người
  vận hành xem, không tự xoá.

⚠️ **Ba chỗ dễ sai nhất — sai là gắn cờ NHẦM hàng loạt:**

1. Sắp `externalId` theo **thứ tự byte** (`sorted()` của Python). Không dùng thứ
   tự có ngôn ngữ hay không phân biệt hoa thường.
2. `afterExternalId` = mã lớn nhất **đã GỬI** ở trang trước (không phải «đã
   quét»). `null` = trang đầu.
3. Phân trang thì trang giữa PHẢI khai `isLastPage: false` — quên là trang đó tự
   nhận phủ tới +∞ và mọi bản ghi sau nó bị nghi mất tích. Bản kê MỘT trang thì
   không phải khai gì (mặc định `true` đúng sẵn).

Trần 20.000 mục/trang; mã trùng trong một trang trả `422`. Nhịp mặc định 30
request/giờ. **`?dryRun=true` diễn tập an toàn** — so như thật, không cờ nào bị
gắn/gỡ; dùng nó cho tới khi adapter chạy đúng.

⚠️ Nền tảng có cảnh báo «tenant im lặng»: ngừng gửi bản kê vài ngày là người vận
hành hai bên được báo. Đối soát là một phần của hợp đồng vận hành, không phải
tính năng tuỳ chọn.

## Nhịp (mặc định — con số đang áp nằm trong câu lỗi 429 và header `Retry-After`)

| Cửa | Nhịp | Vì sao |
|---|---|---|
| `/events` | 120 request/phút | Đếm REQUEST, không đếm bản ghi — gộp lô đi (tối đa 500/lô) |
| `/manifest` | 30 request/giờ | Phép so trên toàn bộ dữ liệu; nhịp nghiệp vụ là hằng đêm |

---

*Phía nền tảng (nội bộ): bảng trường sinh từ `modules/ingest/hop_dong.py` (có cổng parity
với DB — `test_hop_dong_khop_schema.py`), văn bản Swagger sinh ở
`modules/ingest/tai_lieu.py` (cổng `test_tai_lieu.py`). Đổi hợp đồng: chỉ THÊM,
không đổi tên, không bỏ — xem `contracts.PHIEN_BAN`.*
