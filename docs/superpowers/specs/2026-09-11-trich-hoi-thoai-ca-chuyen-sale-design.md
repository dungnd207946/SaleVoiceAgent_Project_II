# Trích hội thoại trên ca chuyển sale

Ngày 2026-09-11 · nhánh `feat/escalation` (cả ba repo odyssey) · màn `/chuyen-sale`

## 1. Vấn đề

Panel chi tiết của một ca chuyển sale hôm nay cho sale hai thứ: **tóm tắt nhu cầu**
do LLM viết, và một link **sang transcript đầy đủ**. Giữa hai thứ đó thiếu một bậc —
vài lượt thoại thật quanh lúc agent bấm chuyển.

Tóm tắt là bản diễn giải; nó có thể hụt hoặc lệch, và khi nó còn là chuỗi cơ học
(`summary_at IS NULL`) thì nó chỉ là «Khách: X, SĐT: Y, Dự án: Z». Transcript đầy đủ
thì đúng nhưng bắt sale rời màn và tự đi tìm. Cái còn thiếu là **nguyên văn, ngắn,
tại chỗ**.

## 2. Điều làm cho việc này rẻ

`escalations.message_seq` và `conversation_messages.seq` **dùng chung một hệ đánh số**
— cả hai là chỉ số tuyệt đối trong `state.history` phía agent:

- `noble_agent/storage/pg_data_plane.py::persist_turn_messages` nhận `base_seq` là con
  trỏ trước lượt, nên `seq` là chỉ số tuyệt đối của message trong `state.history`.
- `noble_agent/agent/tools/support_ops.py::escalate` ghi `message_seq = len(state.history)`.

Và transcript được ghi **realtime từng lượt** (fire-and-forget sau `save_all`), không
phải dồn lúc kết thúc cuộc gọi.

Hệ quả: Portal **cắt được đoạn quanh lúc chuyển bằng một câu SQL trên bảng đã có**.
Không migration, không đụng repo `odyssey-agent`.

## 3. Luật cắt đoạn

```
seq < message_seq
  AND role IN ('user','assistant')
  AND content <> ''
ORDER BY seq DESC
LIMIT 6          -- rồi đảo lại cho đúng thứ tự đọc
```

Ba mệnh đề, mỗi cái chống một lỗi cụ thể:

**`role IN ('user','assistant')` + `content <> ''` — bắt buộc.** `conversation_messages`
giữ cả hàng `role='tool'` (kết quả tool, thường là JSON) và hàng assistant rỗng chỉ
mang `tool_calls` trong `meta`. Không lọc thì sale đọc phải tham số của `search_units`.

**`seq < message_seq` chứ không phải `<=`, và đoạn trích KHÔNG chứa lời hứa của agent.**
Đây là chỗ dễ vẽ sai. `message_seq` được chụp lúc tool `escalate` đang chạy — câu trả
lời cuối của agent («Em chuyển thông tin cho chuyên viên ngay…») **chưa được ghép vào
`state.history`**, và hàng ngay trước nó là assistant message rỗng chỉ mang `tool_calls`
(đã bị lọc ở trên). Nên lượt cuối cùng đọc được luôn là **câu hỏi chưa được trả lời của
khách**.

Đó là kết quả đúng, không phải hạn chế: trích đoạn kết thúc đúng ở chỗ hệ thống bí.
Nhưng nó quyết định vị trí của lằn ranh ở §5 — «Agent chuyển ở đây» nằm **sau câu hỏi
của khách**, không phải sau một lời hứa.

**`LIMIT 6`** = một hằng, một chỗ. Sáu message ≈ ba lượt trao đổi, đủ dựng lại bối cảnh
mà không biến panel thành transcript.

### `message_seq IS NULL`

Cột nullable, và ca ghi trước khi agent gửi trường này thì không có mốc neo. Khi đó bỏ
vế `seq < message_seq`, lấy 6 lượt cuối của phiên. Có dữ liệu còn hơn một khối rỗng —
và với một ca đã chuyển thì «6 lượt cuối» gần như luôn là đoạn quanh lúc chuyển.

## 4. Hợp đồng API

```
GET /api/v1/ops/escalations/{ca_id}/trich  →  list[LuotOut]
```

- `require(ACTIONS.CONVOS_READ)` — cùng quyền với `lich_su_ghi_chu`.
- Ca thuộc tenant khác ⇒ **404**, kiểm qua `repo.doc_ca` trước khi đọc, đúng khuôn
  `lich_su_ghi_chu` đang làm.
- Trả **mảng rỗng**, không 404, khi phiên không có lượt nào — một ca có thật mà chưa
  có transcript là chuyện bình thường (xem §6), không phải lỗi.

**Dùng lại `LuotOut`, không đẻ contract mới.** Nó đã là hình dạng
`GET /convos/phien/{session_id}` trả về (`seq · role · content · taoLuc · meta`). Một
`TrichOut` gọn hơn sẽ tiết kiệm được trường `meta` không ai đọc ở màn này, nhưng đổi lại
là một loại thứ hai mô tả cùng một thứ, và hai loại như vậy sẽ lệch nhau.

### Vì sao endpoint riêng, không gộp vào payload danh sách

`CaOut.trich[]` kèm sẵn mọi hàng thì mở màn một request, nhưng **mỗi lượt lọc hay đổi
trang kéo về 50 × 6 lượt thoại** trong khi sale chỉ mở một ca. Endpoint riêng tải lười
khi mở ca — đúng khuôn `lichSuGhiChu` đã có sẵn trong `CaChiTiet`. Đảo lại sau rẻ nếu
đo được là sai.

**Thẻ trong danh sách không đổi.** Có cân nhắc thêm một dòng trích câu hỏi cuối lên thẻ
để quét dọc nhanh hơn; bỏ vì nó buộc `liet_ke_ca` (vốn đã 4 JOIN) gánh thêm một truy vấn
cho mỗi hàng, đổi lấy một tiện ích chưa ai xin.

## 5. Frontend

Khối trích đặt **dưới «Tóm tắt nhu cầu», trên «Ghi chú của sale»** — đọc từ khái quát
xuống cụ thể.

**Dùng lại `components/Transcript.tsx`, KHÔNG viết bộ render thứ hai.** Nó đã nhận đúng
`readonly Luot[]` — cùng kiểu endpoint ở §4 trả về — và mang sẵn ~300 dòng phòng thủ cho
dữ liệu do một hệ khác ghi (`0915` cố ý không CHECK `role`; hàng `tool` mồ côi; `meta`
jsonb có thể là bất cứ gì; `Invalid Date`). Hai lý do, theo thứ tự quan trọng:

1. **Hai bộ render cho cùng một dữ liệu là hai bộ sẽ lệch nhau.** Bản viết mới hoặc phải
   chép lại đống phòng thủ đó, hoặc bỏ sót nó.
2. Sale đọc trích đoạn rồi bấm sang transcript đầy đủ thấy **cùng một cách render**, không
   phải hai kiểu chat khác nhau cho cùng một cuộc gọi.

Hệ quả: trích đoạn là **bong bóng chat** (khách phải, agent trái), không phải hàng có nhãn
vai. Bộ máy khối tool của `Transcript` sẽ không bao giờ kích hoạt vì §3 đã lọc sạch hàng
`tool` và assistant rỗng ở tầng SQL — đó là quan hệ đúng chiều: backend quyết định *cái gì*
được đọc, `Transcript` quyết định *nó trông thế nào*.

Lằn ranh **«Agent chuyển ở đây»** nằm **dưới** khối (xem §3 — nó theo sau câu hỏi của
khách, không theo sau một lời hứa của agent).

Dưới cùng: `n / N lượt` và link **Mở transcript đầy đủ** (giữ nguyên link đang có).

Tải lười bằng `useQuery` khoá theo `ca.id`, đúng khuôn `LichSuGhiChu`.

## 6. Ca suy biến

Transcript ghi **fire-and-forget**: nếu `save_all` hỏng ở lượt cuối thì các hàng đó
không bao giờ xuống Postgres. Khối phải **nói thật** — «Phiên này chưa có lượt thoại nào
trong kho» — chứ không hiện khung trống như thể cuộc gọi không có nội dung. Link sang
transcript đầy đủ vẫn giữ.

## 7. Trang trí tiêu đề khối

Sửa kèm, cùng màn, vì nó là thứ làm khối mới khó đọc ngay khi thêm vào.

Hôm nay `TieuMuc` (12px · HOA · tracking wide · `text-fg`) và nhãn trường của `Muc`
(11.5px · HOA · tracking wide · `text-muted-2`) chỉ khác nhau **màu và độ đậm**. Ở cỡ đó
chênh nửa pixel với một sắc xám không đủ để mắt tách hai bậc — một cái đặt tên cho cả
khối bên dưới, một cái dán nhãn cho một chữ bên cạnh.

Cách chọn: **thanh dọc accent neo đầu dòng + kẻ mảnh trung tính chạy nốt phần dòng còn
lại.** Hai thứ làm hai việc khác nhau (neo điểm bắt đầu · đóng dòng), và cộng lại thì
tiêu đề thành một **dải chạy hết chiều ngang**, còn nhãn trường vẫn là một cụm chữ ngắn
đứng lẻ — hai vật khác nhau về hình, không chỉ về kiểu chữ.

```
mt-[18px] mb-2.5 flex items-center gap-2.5 border-l-2 border-ac pl-2.5
text-[12px] font-semibold uppercase leading-tight tracking-wide text-fg
after:h-px after:flex-1 after:bg-border after:content-['']
```

⚠️ **Nhãn trường (`Muc` dt) KHÔNG đụng.** Nó phải ở lại chữ hoa li ti thì phép tách mới
chạy; đổi cả hai là quay về đúng chỗ cũ.

⚠️ `TieuMuc` mọc thêm prop `meta` (cho «lượt 12–15» ở mép phải). Đường kẻ là `::after`
nên mặc định nó là phần tử cuối và đẩy `meta` ra ngoài — `meta` phải `order:3`, kẻ
`order:2`.

Kẻ để **trung tính** (`border`), không tô accent: thanh dọc đã đủ làm dấu neo, và
`theme.css` giữ accent cho *hành động* (nút, link, hàng đang chọn). Rải accent hết chiều
ngang là làm loãng đúng thứ đang phân biệt nút bấm với chữ.

## 8. Ngoài phạm vi

- **Trùng hàng escalate trong cùng một phiên.** `dispatcher._auto_escalate` bắn mỗi lần
  một tool trả `ESCALATE_SIGNAL`, không chốt theo phiên, nên một phiên có thể sinh nhiều
  hàng và hộp thư hiện nhiều thẻ cho một khách. Có thật, đã xác định bằng đọc code, chưa
  đo được số lượng (DB dev không nối được từ máy đang làm). Việc riêng.
- **Gom ca theo `session_id` ở `liet_ke_ca`.** `0924_bang_escalations` khai «gom theo
  session_id là việc của truy vấn» nhưng chưa ai làm. Liên quan gạch đầu dòng trên, cùng
  một việc riêng.
- Tìm trong transcript, tô sáng từ khoá, trích nhiều đoạn rời nhau.

## 9. Test

**Backend** — `tests/modules/ops/`:
- cắt đúng cửa sổ quanh `message_seq`
- hàng `role='tool'` và assistant rỗng **không** lọt vào kết quả
- `message_seq IS NULL` ⇒ rơi về 6 lượt cuối, không rỗng
- phiên không có lượt nào ⇒ mảng rỗng, không 404
- ca của tenant khác ⇒ 404
- thứ tự trả về tăng dần theo `seq` (không phải thứ tự `DESC` của câu bên trong)

**Frontend** — cập nhật fake MSW của `features/ops`, và `npm run build` (không phải
`tsc --noEmit`) như lệ của repo.

## 10. Tách commit

| Repo | Commit |
|---|---|
`odyssey-portal-backend` | ① spec này · ② `repo.doc_trich` + test · ③ route `/trich` + test |
`odyssey-portal-frontend` | ① `api.ts` + kiểu + fake MSW · ② khối trích trong `CaChiTiet` · ③ `TieuMuc` |
`odyssey-agent` | không đổi (nhánh đã có sẵn 2 commit về log ca escalate mất) |
