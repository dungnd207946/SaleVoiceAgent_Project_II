# M5 — Agent Studio (thiết kế)

> **Ngày:** 2026-07-31 · **Trạng thái:** chờ duyệt · **Repo:** `odyssey-portal-backend` + `odyssey-portal-frontend`
> **Chặn bởi:** M3 (hình dạng `payload` + bundle) · **Màn:** `agent` — "Agent & Kênh"
> **Nguồn nghiệp vụ:** **AG_01 v1.0 (2026-07-29, thebc)** — 16 business rule, 7 mã lỗi, bảng thành phần màn hình. Đã đọc và hợp nhất vào spec này.
> **Nguồn kỹ thuật:** spec tổng §3 (M5) · `control-plane-design.ref.md` §5.7 quyết định #14 · work-packages Gói C

---

## 0. Spec này làm gì

Nơi workspace dạy agent nói theo cách của mình: đặt tên, khai phạm vi, chọn giọng điệu, bật tắt kỹ
năng, xem rào chắn đang bảo vệ mình, và **chat thử ngay** sau khi áp dụng.

**Nguyên tắc gốc (AG_01 §I):** phần lớn người dùng platform **không có kiến thức chuyên sâu về
agent**. Nên platform viết sẵn toàn bộ template; workspace chỉ điền vài thông tin riêng hoặc dùng
mặc định. **Workspace không bao giờ nhìn thấy file markdown.**

**Trong phạm vi:** 9 ô điền + 2 preset · 12 tool toggle · 6 rào chắn chỉ-đọc · **bước Xem trước
bắt buộc** · Lưu và áp dụng có xác nhận · 4 trạng thái agent · chat thử · nhật ký hoạt động ·
**sửa hai lỗi đang có trong code** (§6).

**Ngoài phạm vi (AG_01 §I.2):** versioning UI · so sánh bản · khôi phục · connector kênh mới (M8).

> **Mâu thuẫn tài liệu — cách đọc đúng.** AG_01 ghi *"Versioning, so sánh bản, khôi phục: ngoài
> MVP"*; bản đồ module giao `config_versions` cho M3. **Cả hai đúng, ở hai tầng khác nhau:**
> M3 giữ version ở **tầng dữ liệu** (cần cho bất biến, nhật ký, và đường rollback của ops);
> M5 **không có UI** cho lịch sử/diff/khôi phục, chỉ hiện `vN`. Không có nút Khôi phục trên màn này.

---

## 1. Ba tầng quyền sửa (BR01)

Đọc `RULES.md` thật — 184 dòng, **~135 dòng là cơ chế**:

| Tầng | ~dòng | Nội dung | M5 làm gì |
|---|---|---|---|
| **(a) Khoá** | 110 | Bắt buộc gọi tool trước khi trả lời · booking 3 bước · giải mã tên dự án · `ESCALATE_SIGNAL` · `send_media` · cấm markdown vì TTS | Không hiện, không cho sửa |
| **(b) Sinh tự động** | 25 | Danh mục kỹ năng · khối chuyên biệt theo lĩnh vực | Sinh từ `tools.enabled` + lĩnh vực |
| **(c) Workspace điền/chọn** | ~49 | **9 ô** + **2 preset**, tất cả có mặc định dùng được ngay | Form §2 |

**Vì sao 110 dòng nằm ngoài tầm tay workspace:** giao thức booking 3 bước được **cưỡng chế bằng code
guard** trong `schedule_viewing`. Sửa prompt mà không sửa guard là vỡ. Ràng buộc kỹ thuật có thật,
không phải sự thận trọng thừa.

**BR02 — không chạm markdown.** API **không nhận nội dung prompt thô từ client**. Phần cơ chế không
phục vụ ra bất kỳ endpoint nào; gọi thẳng API cũng không sửa được.

---

## 2. Chín ô + hai preset

| Nhóm | Control | Giới hạn | Bắt buộc | Mặc định |
|---|---|---|---|---|
| **Danh tính** | Tên agent | 40 ký tự | ✅ | gợi ý lúc onboarding |
| | Tên thương hiệu | 80 ký tự | ✅ | tên workspace |
| | Xưng hô (dropdown) | | ✅ | em ↔ anh/chị |
| | Lời chào (textarea) | 200 | | sinh theo giọng điệu |
| **Phạm vi** | Lĩnh vực phụ trách (dropdown) | | ✅ | MVP chỉ Bất động sản |
| | Agent làm gì (textarea) | 300 | | tư vấn dự án + đặt lịch tham quan |
| | Agent không làm gì (textarea) | 300 | | hậu mãi, giá riêng |
| | Phòng ban chuyển tiếp (list) | ≤ 8 mục | ✅ | một mục CSKH · **phải còn ≥1** |
| | Câu từ chối ngoài phạm vi | 200 | | sinh từ lĩnh vực + thương hiệu |
| **Preset** | Giọng điệu (radio ×3) | | ✅ | Lịch sự · Thân thiện · Ngắn gọn |
| | Độ dài trả lời (radio ×3) | | ✅ | Ngắn · **Trung bình** · Chi tiết |

**Mọi ô có mặc định dùng được ngay** — không điền gì vẫn ra một agent chạy đúng. Đây là yêu cầu
UX của AG_01, và là cổng test 5.

**BR07 — nội dung 3 preset giọng điệu do platform viết**, workspace chỉ chọn. Mỗi lựa chọn có một
câu ví dụ cạnh nó. *Chưa có người nhận (N3) — xem §10.*

---

## 3. Sáu rào chắn — danh sách chốt (BR08)

Hiện để khách yên tâm, **không có công tắc tắt**:

1. Không bịa số liệu ngoài dữ liệu
2. Không nói mã nội bộ
3. Chỉ nói về dữ liệu trong workspace
4. Xin phép trước khi lưu số điện thoại
5. Dữ liệu quá hạn thì nói cần xác nhận lại
6. Không tư vấn pháp lý hay thuế

Cả sáu là điều kiện đúng đắn hoặc nghĩa vụ pháp lý — cho tắt là bán một công tắc gây sự cố. Khoá ở
**tầng render**: không có tham số nào tắt được, kể cả gọi thẳng API.

Vì cả 6 đều khoá, chúng **không nằm trong `payload`** (luật §2 của M3: payload chứa đúng thứ tenant
đổi được). Chúng là hằng số trong template; FE hiện từ danh sách tĩnh trong `features/agent/`.

> **Sửa so với bản trước của spec này:** không tiết lộ là AI **KHÔNG** nằm trong 6 rào chắn.
> AG_01 xếp nó vào TODO và **đề nghị cho tenant chọn, mặc định là CÓ tiết lộ** — ngược với hành vi
> code hiện tại (đang cấm tiết lộ). Đây là quyết định pháp lý + thương hiệu, chưa chốt. Nếu chốt
> "cho tenant chọn" thì nó thành **ô thứ 10**, không phải rào chắn thứ 7.

---

## 4. Mười hai tool toggle

Prototype vẽ 4; agent có **12**. Mỗi toggle cần **tên nghiệp vụ** (không phải tên hàm), một dòng
giải thích, và **cảnh báo phụ thuộc** — *"tắt Đặt lịch thì agent không chốt được lịch tham quan"*.

Tắt hết ⇒ **ER_03** (popup: *"Agent sẽ không làm được gì"*).

**Bảng phụ thuộc là dữ liệu, không phải `if`.** Một hằng số trong `contracts.py`:
`{"schedule_viewing": ["find_project"], ...}` — FE đọc để hiện cảnh báo, BE đọc để validate. Một
nguồn, hai nơi dùng; thêm tool thứ 13 sửa đúng một chỗ (yêu cầu bảo trì của AG_01: *"thêm kỹ năng
mới chỉ cần khai thêm một mục, không sửa template cơ chế"*).

---

## 5. Luồng: Xem trước là bước BẮT BUỘC

Đây là chỗ bản trước của spec này thiếu hẳn. AG_01 §II.1 đặt một bước giữa *sửa* và *áp dụng*:

```
sửa form
  → [Xem trước thay đổi]
      BE render template + biến + sinh mục kỹ năng từ danh sách đang bật   (BR03·BR04·BR06)
      BE KIỂM TRA CẤU TRÚC — rẻ, đồng bộ, KHÔNG gọi LLM                    (BR11)
         không đạt → ER_04, KHÔNG ghi gì
      FE hiện bản xem trước dạng NGÔN NGỮ NGƯỜI ĐỌC ĐƯỢC + danh sách trường đã đổi
  → [Lưu và áp dụng] + popup xác nhận                                       (BR10)
  → Đang áp dụng → agent nhận trong ≤20s → Sẵn sàng                     (BR09)
```

**Kiểm tra cấu trúc là gì:** không còn ô trống chưa thay · mọi kỹ năng đang bật đều tồn tại · phần
bắt buộc không rỗng. **Không gọi LLM** — kiểm chất lượng trả lời là việc khác và không được chặn
việc áp dụng.

**Bản xem trước không hiện markdown thô.** Hiện bằng câu tiếng Việt + danh sách trường đã đổi. Cho
người dùng xem markdown là phá đúng nguyên tắc BR02 ở bước cuối cùng.

**Endpoint mới so với M3:** `POST /api/v1/config/preview` — render + validate, không ghi gì. Nó
dùng lại đúng `bundle.render()` của M3 rồi vứt kết quả đi; **không có đường render thứ hai**.

**Popup xác nhận phải nói rõ (BR10):** *khách đang gọi vẫn dùng bản cũ tới khi kết thúc*. Không nói
câu này thì người sửa một rào chắn đang nói sai sẽ tưởng đã chặn được ngay.

---

## 6. Hai lỗi phải sửa TRƯỚC khi màn này ship

Đã kiểm trong code, không phải suy đoán. AG_01 §6 xếp cả hai là chặn ship.

**Lỗi 1 — bật tắt kỹ năng sẽ tạo agent hứa việc nó không làm được (BR03·BR04).**
Danh mục kỹ năng trong prompt là **văn bản tĩnh 15 dòng**; `grep -rn 'Tool catalog' src/` chỉ trả
về chính `RULES.md`. Tắt `booking` ⇒ `build_schemas` bỏ schema nhưng prompt vẫn dạy gọi ⇒ LLM không
emit được tool call nên **trả lời bằng lời**: hứa đặt lịch rồi không có `appointments` nào được ghi.
Khối chuyên biệt theo lĩnh vực cùng loại — tham số bị gỡ khỏi tool nhưng đoạn prompt dạy truyền
tham số đó vẫn còn.
**Sửa:** `bundle.render()` sinh catalog từ `tools.enabled`. **Cổng test 1.**

**Lỗi 2 — agent của khách sẽ tự xưng là nhân viên NobleX (BR05).**
Cơ chế thay biến đã có và `brand` đã được truyền vào lúc nạp persona. Nhưng đếm biến trong file:
`{{ agent_name }}` ×5, `{{ brand.* }}` **×0**. Còn 4 chỗ viết cứng: dòng 172 (`"Em là chuyên viên
NobleX."`), 179 (`"bất động sản NobleX"`), 173 và 176 (mã `NCLB`/`SLC`, tên `"Noble Crystal Long
Biên"`). **Sửa rẻ — thay chuỗi bằng biến — nhưng không sửa thì không bán được cho khách thứ hai.**
**Cổng test 2.**

**BR16 — bỏ `NOBLE_AGENT_NAME`.** Biến môi trường này đang đè `config.json`, nên sửa tên trong
portal xong agent vẫn xưng tên cũ. *Việc ở repo agent — thuộc Gói G; ghi ở đây để hợp đồng bundle
nhắc tới.*

---

## 7. Chat thử

Agent đã có sẵn `/chat/ws` — khung chat text dùng lại đúng bộ não agent, không qua STT/TTS
(`santa-hotline-agent/src/noble_agent/server/text_chat.py`). M5 **nhúng**, không dựng lại. Địa chỉ
lấy từ `control.deployments.endpoint` (bảng M3 tạo).

**BR13 — chat thử dùng cấu hình vừa áp dụng và dữ liệu thật của workspace**, không phải môi trường
giả. **Chưa áp dụng xong thì khoá ô** — không cho thử bằng bản cũ rồi tưởng là bản mới.

| Chip trạng thái | Chat thử |
|---|---|
| **Sẵn sàng** | Mở |
| **Đang cấp** · **Đang áp dụng** · **Mất kết nối** | Khoá — **ER_06**: *"Agent chưa sẵn sàng để thử. Cấu hình vẫn lưu được bình thường"* |

Bốn chip này **suy ra từ agent đang chạy**, không phải cờ trong portal — nối vào
`GET /api/v1/config/status` của M3.

**Hiện Kỹ năng đã dùng** cạnh mỗi câu trả lời: agent đã gọi kỹ năng nào. Đây là cách duy nhất
người dùng **thấy** bật/tắt có tác dụng thật. *Cần agent trả về danh sách tool đã gọi trong response
của `/chat/ws` — ghi vào hợp đồng bàn giao Gói G.*

---

## 8. Bảy mã lỗi (AG_01 §II.4)

| Mã | Khi nào | Kiểu |
|---|---|---|
| ER_01 | Tên agent rỗng hoặc > 40 ký tự | Inline |
| ER_02 | Không còn phòng ban chuyển tiếp nào | Inline |
| ER_03 | Tắt hết kỹ năng | Popup |
| ER_04 | Kiểm tra cấu trúc không đạt — **không có gì thay đổi, agent vẫn chạy bản cũ** | Popup + chi tiết |
| ER_05 | Lỗi chung | Toast |
| ER_06 | Agent chưa sẵn sàng để thử | Inline trong panel |
| ER_07 | Agent chưa nhận cấu hình sau vài phút — **cấu hình đã lưu**, tự thử lại | Banner + [Thử lại] |

**BR12 — hỏng thì không gì đổi.** Kiểm tra không đạt hoặc agent nạp lỗi ⇒ agent **giữ nguyên** cấu
hình đang chạy, portal hiện lỗi thật. Không bao giờ phục vụ cấu hình nạp nửa vời. Tính chất này
M3 đã bảo đảm bằng "con trỏ `LIVE` ghi cuối cùng".

---

## 9. Cấu trúc code

```
BE  src/portal/modules/config/     ← KHÔNG module mới. M5 mở rộng của M3:
      contracts.py   9 ô + 2 preset + bảng phụ thuộc tool
      bundle.py      sinh catalog kỹ năng (§6 lỗi 1) + template trung tính (§6 lỗi 2)
      router.py      + POST /config/preview
      service.py     + kiem_tra_cau_truc()  ← hàm thuần, BR11
                     + ghi nhật ký mỗi lần áp dụng (BR15)

FE  src/features/agent/
      api.ts · components/{PersonaForm,ToolToggles,Guardrails,XemTruoc,ChatThu,TrangThai}.tsx
    src/routes/_app/agent.tsx      ← route rỗng đã có từ M2a-FE
```

**M5 không tạo module BE mới.** Payload thuộc M3; hai module cùng ghi `config_drafts` là hai chủ cho
một bảng. FE lấy type qua `contracts/openapi.json` theo nếp M2a (BE sinh, FE sao).

**BR15 — nhật ký hoạt động:** mỗi lần áp dụng ghi *ai · lúc nào · trường nào đổi từ gì sang gì*.
Hiển thị ở màn Nhật ký & Dữ liệu (M8). M5 **ghi**; M8 **đọc**. Bảng `audit_log` thuộc M8 — nếu M5
làm trước, tạm ghi vào một bảng tối thiểu rồi M8 tiếp quản, **không** bỏ qua việc ghi.

**BR14 — quyền:** chỉ vai trò có quyền *Cấu hình agent* vào được màn này; vai trò khác **không thấy
mục trong menu**. `features/agent/nav.ts` đã khai `requiredActions` từ M2a-FE — kiểm lại nó khai
đúng `agent_config.*`.

---

## 10. Bỏ khỏi UI — ghi ra để không ai vẽ lại

Tốc độ nói · "Tính khoản vay" — **chưa tồn tại trong agent**. Dropdown Giọng đọc chỉ có **1 giọng
thật**; vẽ dropdown 5 giọng là hứa hão.

---

## 11. Cổng test

| # | Cổng | Đỏ khi nào |
|---|---|---|
| 1 | Tắt một tool ⇒ tên nó **vắng mặt** trong `RULES.md` đã render | Lỗi 1 §6 quay lại |
| 2 | Render với brand khác ⇒ chuỗi `"NobleX"` vắng mặt trong **mọi** file bundle | Lỗi 2 §6 quay lại |
| 3 | 6 rào chắn hiện đủ; **không tham số API nào** tắt được chúng | Ai đó thêm đường tắt |
| 4 | Chip ≠ Sẵn sàng ⇒ chat thử **khoá** | Chat thử nói dối về bản đang chạy |
| 5 | Không điền gì ⇒ publish được, agent chạy đúng | Form bắt buộc quá tay |
| 6 | Bật `schedule_viewing` khi `find_project` tắt ⇒ **BE từ chối** | Validate chỉ có ở FE |
| 7 | `POST /preview` không ghi hàng nào vào `config_drafts`/`config_versions` | Preview có tác dụng phụ |
| 8 | API từ chối mọi payload chứa markdown thô (BR02) | Đường sửa prompt lọt qua API |

Cổng 6 và 8 quan trọng hơn vẻ ngoài: cảnh báo chỉ ở FE là cảnh báo bỏ qua được bằng một `curl`.

---

## 12. Còn treo

- **N3 — viết và kiểm thử 3 preset giọng điệu.** Chưa có người nhận, **nằm trên đường găng**.
- **Đặt tên nghiệp vụ cho đủ 12 kỹ năng** + một dòng giải thích + cảnh báo phụ thuộc mỗi cái.
- **Chốt: agent có được nói mình là trợ lý ảo không.** Code hiện **cấm** tiết lộ; AG_01 đề nghị
  **cho tenant chọn, mặc định CÓ tiết lộ**. Chốt "cho chọn" ⇒ thành ô thứ 10 (§3).
- **Wireframe màn Agent Studio** — AG_01 §3 mới có bảng thành phần, chưa có hình.
