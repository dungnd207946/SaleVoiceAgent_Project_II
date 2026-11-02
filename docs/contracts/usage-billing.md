# Hợp đồng Usage & Billing — bàn giao FE

> **Đối tượng:** frontend team, đọc trước khi ghép màn Usage/Billing.
> **Sở hữu:** module `billing` (backend). Đổi field/route ở `src/portal/modules/billing/*` mà không sửa
> tài liệu này là để tài liệu nói dối.
> **Nguồn:** đọc trực tiếp từ code lúc viết tài liệu này (2026-08-20) — `router.py`, `contracts.py`,
> `service.py`, `repo.py`, và các migration `0943`–`0947`. Không suy từ brief lúc lập plan; brief lệch
> ở vài điểm, ghi rõ ở cuối file.

Xác thực:
- **Endpoint tenant** (tiền tố `/billing/*`, không có prefix `/api/v1` viết cứng trong router —
  `api/app.py` gắn) — qua phiên đăng nhập, action `ACTIONS.BILLING_READ` = `"billing.read"`. Tách khỏi
  `WORKSPACE_ADMIN` có chủ ý: kế toán xem hoá đơn không cần quyền mời/gỡ thành viên.
  ⚠️ Danh sách THẬT là bảng §1 — dòng này cố ý KHÔNG đếm nữa: nó từng ghi «5 endpoint»
  và lệch ngay lần thêm route kế tiếp (`usage-by-day`, 2026-08-24), mà không cổng nào đỏ.
- **6 endpoint admin nền tảng** (tiền tố `/admin/billing/*`) — xác thực bằng header
  `X-Platform-Admin-Token`, KHÔNG bằng phiên. Đây là màn của NobleX quản trị bảng giá, không phải màn
  của khách. ⚠️ Brief lúc lập plan ghi "5 endpoint admin" — code có **6** (liệt kê ở bảng dưới); code
  thắng.

Bảng trường sinh từ OpenAPI thật — mở `/docs` (Swagger UI) của backend đang chạy để xem schema đầy đủ
kèm mô tả. Tài liệu này chỉ nhắc lại phần dễ hiểu sai.

---

## 0. Quy ước JSON — khác `modules/ops`, đọc trước khi map field

**Mọi response của module `billing` là `snake_case`.** `TongQuanOut`, `DongKeyOut`, `PhienUsageOut`,
`EventOut`, `ChiTietPhienOut`, `DanhSachKeyOut`, `DanhSachPhienOut`, `DongOwnerOut`, `CanhBaoOut` —
không model nào khai `alias_generator`. So sánh: `modules/ops/contracts.py` khai alias camelCase tường
minh cho đúng lý do "đây là hợp đồng với FE" — `billing` **không làm vậy**. Hai module hàng xóm, hai
quy ước — đây là chỗ dev FE dễ trượt nhất (copy pattern đọc `res.data.chiPhiTong` từ màn ops sang màn
billing sẽ ra `undefined`, đúng field là `chi_phi_tong`).

**Ngoại lệ ngược lại, ở đúng 2 body admin gửi LÊN (không phải response):** `DongGiaIn`
(`POST /admin/billing/price-versions/{pb}/items`) khai alias camelCase cho hai field —
`unitPrice`/`perUnits` — còn `component`/`purpose`/`provider`/`model`/`metric`/`note` giữ nguyên tên
thường. `GanBoGiaIn` (`POST /admin/billing/tenants/{tenant_id}/price-version`) khai alias camelCase
cho **cả hai** field của nó: `priceVersionId`/`effectiveFrom`. Model không có
`populate_by_name`, nên phải gửi ĐÚNG tên alias cho các field đó — gửi `unit_price` sẽ bị Pydantic coi
là field lạ (`extra="forbid"` ở mọi model của module này) và ném `422 VALIDATION_ERROR`. Ba model admin
khác (`PhienBanGiaIn`, response của `liet_ke_bang_gia`/`preview_bang_gia`/`kich_hoat_bang_gia`/
`tao_bang_gia`/`gan_bo_gia` — đều dict thô hoặc model không alias) giữ snake_case, TRỪ
`preview_bang_gia` trả `{"chiPhi": "...", "currency": "..."}` — một dict tay, camelCase cho đúng một
key. Tức: **màn admin là hỗn hợp**, không có quy tắc chung — tra đúng model/response từng route ở bảng
dưới, đừng suy loại theo màn tenant.

Hình dạng lỗi CHUNG toàn API (không riêng module này): `{"error": {"code": "...", "message": "..."}}`.
Lỗi 422 do Pydantic validate body/query thêm field `error.fields` = `[{"field", "reason"}, ...]`.

---

## 1. Endpoint tenant (`billing.read`)

| Method | Path | Query | Response model |
|---|---|---|---|
| GET | `/billing/summary` | `from`, `to` (date, tuỳ chọn) | `TongQuanOut` |
| GET | `/billing/breakdown` | `from`, `to` | `PhanTichOut` |
| GET | `/billing/usage-by-day` | `from`, `to` | `UsageTheoNgayOut` |
| GET | `/billing/by-key` | `from`, `to` | `DanhSachKeyOut` |
| GET | `/billing/by-owner` | `from`, `to` | `list[DongOwnerOut]` |
| GET | `/billing/sessions` | `from`, `to`, `limit` (mặc định 50, tối đa 200), `offset` (mặc định 0) | `DanhSachPhienOut` |
| GET | `/billing/sessions/{session_id}` | — | `ChiTietPhienOut` |

`from`/`to` mặc định 30 ngày gần nhất khi bỏ trống (`to` là cận trên **mở**, `< to` không `<= to`).
Thiếu `from < to` ⇒ `422 KHOANG_KHONG_HOP_LE`. `sessions/{session_id}` không tồn tại usage cho phiên đó
⇒ `404 PHIEN_KHONG_TON_TAI`.

⚠️ **Mới (2026-08-20): `409 NHIEU_DON_VI_TIEN`** trên `summary` VÀ `by-key` — khoảng `[from, to)` đang hỏi
có usage được định giá bằng **nhiều hơn một đơn vị tiền** (vd tenant đổi bảng giá VND → USD giữa kỳ qua
`POST /admin/billing/tenants/{tenant_id}/price-version`). Trước đây hai endpoint này cộng bất kể đơn vị
và gắn một nhãn `currency` chọn NGẪU NHIÊN (alphabet) lên tổng đó — sai mà không báo. Giờ chúng NÉM lỗi
rõ ràng thay vì trả một số vô nghĩa. FE nên hiện thông điệp lỗi (đã liệt kê các đơn vị xung đột) và gợi
người dùng chọn khoảng hẹp hơn, nằm trọn trong một bảng giá.

### `/billing/usage-by-day` (mới 2026-08-24) — biểu đồ màn `/usage`

**Song sinh của `/billing/breakdown`, đổi CÂU HỎI: ở đó là TIỀN, ở đây là LƯỢNG.**
`/usage` là màn số ĐO, `/billing` là màn số TIỀN — nên endpoint này **không trả một
trường tiền nào** (`chi_phi`/`currency`/`amount`), và có một bài test canh chiều đó.

```
UsageTheoNgayOut = {
  theo_ngay: [ { ngay: date, so_phien: int,
                 phan: [ { component, so_event, input_tokens, output_tokens,
                           cache_read_tokens, audio_sec, text_units, units,
                           wall_ms_stream, text_units_hoi_thoai } ] } ],
}
```

Năm điều PHẢI biết trước khi map:

1. **Đây là nguồn DUY NHẤT của cả thẻ biểu đồ** — tổng kỳ · đỉnh · số ngày hoạt động
   đều SUY từ chính chuỗi ngày này (tổng theo ngày = tổng cả kỳ). **Đừng lấy tổng kỳ
   từ `breakdown.theo_component`** dù nó có đúng bộ số đo: hai câu SQL khác nhau cho
   một con số là hai chỗ để lệch nhau âm thầm — rail nói một số, biểu đồ vẽ một số
   khác, không cổng nào đỏ.

2. **`theo_ngay` có ĐỦ mọi ngày của kỳ**, `phan` rỗng cho ngày không phát sinh — cùng
   bất biến và cùng lý do với `breakdown.theo_ngay` (§dưới, điều 1).

3. **`so_phien` là thuộc tính của NGÀY**, không của component: `count(DISTINCT
   session_id)` có usage trong ngày, CÙNG định nghĩa với `TongQuanOut.so_phien` (chỉ
   khác cửa sổ). Nhờ vậy tooltip biểu đồ và dải KPI không nói hai số khác nhau về
   cùng một thứ. **Không cộng `so_phien` qua các ngày** — một phiên bắc qua nửa đêm
   được đếm ở cả hai ngày.

4. **ĐƠN VỊ THEO COMPONENT, đọc từ `billing.pricing_basis`** — đừng tự chọn:

   | component | số đo | đơn vị |
   |---|---|---|
   | `llm` | `input_tokens` + `output_tokens` + `cache_read_tokens` | token |
   | `call` · `vad` · `speaker_verify` | `audio_sec` | giây |
   | `stt` | `wall_ms_stream` **và** `text_units_hoi_thoai` (xem điều 5) | giây + ký tự (HAI vế độc lập, cộng thêm) |
   | `tts` · `embed` | `text_units` | **ký tự** |

   ⚠️ Cột «đơn vị» ở trên là sự thật về DỮ LIỆU. Màn `/usage` bày nhãn **«token»**
   cho cả ba chỗ đo `text_units` (`tts` · `embed` · đường 2 của `stt`) — quyết định
   HIỂN THỊ của FE 2026-08-25, KHÔNG đổi ngữ nghĩa cột.

   ⚠️ `tts` và `embed` tính theo **KÝ TỰ** từ migration `0948`, KHÔNG theo giây/token —
   và công thức đối chiếu của bên agent không có vế `audio_sec` nào cho `tts`, nên vẽ
   TTS theo giây sẽ ra một đường phẳng bằng 0. `speaker_verify` là mã thật, không phải `sv`.
   ⚠️ Dữ liệu ghi **trước** `0948` có `text_units = 0` — hai tab đó phẳng trên dữ liệu
   cũ. Đó là sự thật của dữ liệu; **đừng suy ký tự từ `units`** (nay là số lần gọi).

5. **`wall_ms_stream` và `text_units_hoi_thoai` LỌC THEO `purpose`** (mới 2026-08-25),
   mọi trường khác gộp cả component:

   | trường | = | `pricing_basis` |
   |---|---|---|
   | `wall_ms_stream` | `wall_ms` của riêng `purpose='stream'` | (`stt`, `stream`, `wall_ms`) |
   | `text_units_hoi_thoai` | `text_units` của riêng `purpose='conversation'` | (`stt`, `conversation`, `text_units`) |

   ⚠️ **`wall_ms_stream` ≠ tổng `wall_ms` của component.** Bên agent ghi `wall_ms`
   cho **mọi** event như một độ trễ xử lý; chỉ vế `stream` mới là "thời gian stream
   mở" mà bảng giá đem tính. Đo trên DB dev 2026-08-25: `stt` có 177.564,9 ms ở
   `stream` và 10.380,0 ms ở `conversation` — cộng cả hai rồi gắn nhãn `stream` là
   sai 6% ngay hôm nay và sai không giới hạn về sau.

   ⚠️ **`text_units_hoi_thoai` không thay `text_units`.** `text_units` là số đo chính
   của `tts`/`embed`; trường lọc này là vế ký tự **độc lập** của `stt` (`0948`). Với
   `tts` hai trường bằng nhau (mọi dòng `tts` đều `purpose='conversation'`) — đừng
   suy từ đó rằng chúng luôn thay thế được cho nhau.

   Component không có purpose tương ứng ⇒ **`0`, không `null`** (`COALESCE` ở SQL).

   ⚠️ **Màn `/usage` vẽ tab STT bằng hai trường này, KHÔNG bằng `audio_sec`** (đổi
   2026-08-25). `pricing_basis` khai cả `stt/conversation/audio_sec` lẫn
   `stt/stream/wall_ms` và ghi «CHỌN MỘT» — chúng là hai cách đo cùng một quãng, nên
   **đừng cộng chúng lại**. `audio_sec` của `stt` vẫn về trong response và vẫn là vế
   THU TIỀN theo bảng giá mặc định (`stt/stream/wall_ms` có `unit_price = 0`; xem
   `billing.purpose`: «stream … giá 0 vì STT thu theo giây»); nó chỉ không được màn
   `/usage` vẽ nữa. Cần chi phí STT thì hỏi `/billing`, đừng suy từ tab này.

### `/billing/breakdown` (mới 2026-08-21) — mục ② «Tiền đi đâu»

Hai chiều gộp trong MỘT response, cùng kỳ và cùng tổng với `/billing/summary`:

```
PhanTichOut = {
  theo_ngay:      [ { ngay: date, chi_phi: Decimal,
                      phan: [ { component, chi_phi } ] } ],
  theo_component: [ { component, so_event, input_tokens, output_tokens,
                      cache_read_tokens, audio_sec, text_units, units, chi_phi } ],
  chi_phi_tong: Decimal,
  currency: str,
}
```

Ba điều PHẢI biết trước khi map:

1. **`theo_ngay` có ĐỦ mọi ngày của kỳ, kể cả ngày `chi_phi = 0`.** Ngày 0 đồng là ngày THẬT
   không phát sinh, không phải ngày thiếu dữ liệu. Đừng lọc bỏ nó trước khi vẽ: bỏ đi thì đường
   biểu đồ nối thẳng qua chỗ trũng, tức vẽ ra một mức tiền dương cho ngày agent không chạy.
   Số hàng = số ngày của `[from, to)` — bốn kỳ dựng sẵn của `/usage` tối đa 31 hàng.

2. **`chi_phi = 0` ở `theo_component` KHÔNG có nghĩa "không dùng".** Nó nghĩa là chưa dòng giá
   nào khớp component đó (đang nằm trong `canh_bao.thieu_gia` — **đang mất doanh thu**), hoặc
   purpose của nó `billable = false`. Hàng vẫn có số đo. UI phải nói ra sự khác biệt đó, đừng
   hiện `0 ₫` trơn — người đọc sẽ hiểu thành "dùng mà không tốn".

3. **`phan` là tách theo component của CHÍNH ngày đó** (đã xếp theo tiền giảm dần) — nguồn của
   tooltip biểu đồ. Rỗng ở ngày không phát sinh. `chi_phi` của ngày = tổng `phan` (cộng ở router
   từ cùng những hàng ấy, nên không có đường nào lệch). Hàng `chi_phi = 0` VẪN xuất hiện ở đây
   nếu component đó có event được định giá 0 — client nên lọc bỏ khi trình bày.

4. **KHÔNG cộng các cột số đo qua nhiều component** — cùng luật §3 dưới đây. Chỉ `chi_phi` cộng
   được, và tổng đó đã là `chi_phi_tong` (lấy từ cùng nguồn với `/by-key`, nên hai màn không bao
   giờ lệch). `409 NHIEU_DON_VI_TIEN` áp cho endpoint này y như `summary`/`by-key`.

### Field đáng chú ý

- `TongQuanOut.canh_bao`: xem mục 5.
- `TongQuanOut.voice_sec` / `DongKeyOut.voice_sec` / `PhienUsageOut.voice_sec`: **thời lượng CUỘC GỌI**
  (`audio_sec` của riêng `component = 'call'`) trong kỳ/khoá/phiên đó — KHÔNG PHẢI tổng `audio_sec` mọi
  component. ⚠️ **Đổi ngữ nghĩa 2026-08-20**: trước đó ba field này CỘNG CHÉO cả `vad`+`call`+`stt`+`tts`+
  `speaker_verify`, đúng thứ mục 3 cảnh báo "đừng làm" — mà tầng API lại tự làm. Đo được trên dữ liệu
  thật: bản cộng chéo ra 466.22s trong khi thời lượng cuộc gọi thật (`call`) chỉ 176.85s, gấp **2.64×**.
  Tiền không sai (mỗi component tính theo đơn giá riêng, chỉ *tiền* mới được cộng — xem mục 3), nhưng
  KPI thì vô nghĩa và khách đối chiếu với hoá đơn viễn thông của họ sẽ kết luận hệ thống tính sai. Phiên
  KHÔNG có hàng `component='call'` (ví dụ phiên chat) trả `0`, không phải `null`. Vẫn KHÔNG có bản tách
  theo component ở ba tầng này — muốn breakdown, xem `EventOut.audio_sec` ngay dưới.
- `DongKeyOut.agent_key_id: int | None`: `None` = nhóm chưa phân loại — xem mục 2.
- ⚠️ **`DongKeyOut` mọc BẢY trường `chi_phi_<component>` (2026-08-25)** —
  `chi_phi_llm` · `chi_phi_tts` · `chi_phi_stt` · `chi_phi_embed` · `chi_phi_call` ·
  `chi_phi_vad` · `chi_phi_speaker_verify`. Đây là bản TÁCH của `chi_phi` (chính hàng đó)
  theo dịch vụ, thay ba cột `input_tokens`/`output_tokens`/`cache_read_tokens` ở bảng
  «Lượt dùng theo khoá» phía FE (ba field đó vẫn còn trong response, chỉ không còn cột
  nào hiện chúng). Trong một hàng, **tổng bảy trường này THƯỜNG bằng `chi_phi`** — trừ
  khi hàng có usage của một component ngoài bảy mã đã biết (`usage_events.component` là
  `text` không CHECK), khi đó phần tiền đó vẫn nằm trong `chi_phi`/`chi_phi_tong` nhưng
  không lộ ra ở cột nào trong bảy cột (xem `canh_bao.thieu_gia`). ⚠️ **`DongOwnerOut`
  cũng mọc ĐÚNG bảy trường này (2026-08-27)** — bảng «theo người tạo» phía FE nay tách
  theo dịch vụ giống hệt bảng «theo khoá», cùng công thức/cùng bảy mã, xem mục 2.
  ⚠️ **`PhienUsageOut` cũng mọc ĐÚNG bảy trường này (2026-08-27)** — bảng «theo phiên»
  (và hàng `phien` của `ChiTietPhienOut`) nay tách theo dịch vụ giống hệt hai bảng
  kia. Ở hạt phiên, `repo.liet_ke_phien()`/`repo.doc_phien()` KHÔNG cần tầng gộp
  thứ hai như `theo_owner()` — CTE `tien` đã sẵn ở hạt `session_id`.
- `ChiTietPhienOut.ghi_chu_turn`: xem mục 4.
- `EventOut.audio_sec`: giây audio của **một** component, tại một event — đây là chỗ DUY NHẤT trong
  toàn module trả `audio_sec` đã tách theo component (`EventOut.component` đi kèm). Muốn hiểu cấu
  thành thật của `voice_sec` tổng, FE phải gọi `sessions/{session_id}` và tự group `events` theo
  `component` ở phía mình — API không làm sẵn việc này.
- `EventOut`/`PhienUsageOut` không có field `cache_write_tokens` dù DB (`billing.usage_events`,
  `billing.rated_usage`) có cột đó và công thức tính tiền LLM dùng nó — module chỉ chưa expose nó ra
  JSON. Đừng suy luận nó luôn 0 từ việc thiếu field.

---

## 8. Dữ liệu ngoài (purpose `kb_web`, mới 2026-10-05)

Worker dữ liệu ngoài ghi usage vào cùng sổ: `purpose = channel = 'kb_web'`, `session_id = 'kbweb:<job id>'`.
Tính tiền khách (`billable = true`), giá vendor không markup (migration `0973_kbweb_billing`): Qwen theo bậc
token vào mỗi lượt (`qwen3.7-flash`, `qwen3.7-flash>32k`, `qwen3.7-flash>256k`), Gemini 2.5 Flash, và
component mới **`search`** (tra Google, `units` = số lượt, 910 đ/lượt). Bảng giá mới phải có dòng `search`
mới kích hoạt được.

- **Không phải phiên:** `so_phien` (summary, usage-by-day) và `/billing/sessions` bỏ qua `kb_web`.
- `TongQuanOut.chi_phi_du_lieu_ngoai` — phần của `chi_phi` do dữ liệu ngoài. Token trong summary vẫn cộng cả.
- `DongComponentOut.chi_phi_du_lieu_ngoai` — phần của `chi_phi` từng dịch vụ.
- `PhanUsageNgayOut.token_du_lieu_ngoai` (in+out+cache_read) · `text_units_du_lieu_ngoai`.
- `DongKeyOut`/`DongOwnerOut.du_lieu_ngoai: bool` — hàng hệ thống «Dữ liệu ngoài» (`agent_key_id`/`user_id`
  null, `so_phien = 0`), TÁCH khỏi hàng «chưa phân loại». Tổng `chi_phi` các hàng vẫn = `chi_phi_tong`.
- `chi_phi_search` có mặt ở `DongKeyOut` · `DongOwnerOut` · `PhienUsageOut`.

---

## 2. Nhóm `agent_key_id: null` — KHÔNG được ẩn

`DongKeyOut.agent_key_id` là `int | None`. `None` là usage KHÔNG gắn được với khoá nào — phiên có
usage nhưng chưa có hàng `tenant_data.conversations` tương ứng (agent ghi usage trước khi tạo phiên),
hoặc conversation có `agent_key_id IS NULL`. `repo.theo_key` dùng LEFT JOIN đúng để giữ nhóm này lại
trong kết quả — INNER JOIN sẽ làm mất nó.

⚠️ **Backend KHÔNG gửi nhãn hiển thị trong JSON.** Khi `agent_key_id` là `None`, các field còn lại của
dòng đó là `label: ""`, `key_prefix: ""`, `nguoi_tao: ""`, `da_thu_hoi: false` (COALESCE về rỗng, không
phải `null`). Module có khai một hằng số cho đúng tình huống này —
`portal.modules.billing.contracts.NHAN_CHUA_PHAN_LOAI = "Chưa phân loại (không có khoá)"` — nhưng nó
**không đi vào API response nào**, chỉ tồn tại phía backend làm tài liệu ý định. FE phải tự phát hiện
`agent_key_id === null` và tự hiện nhãn này (hoặc bản dịch riêng) ở màn "theo khoá" — đừng chờ backend
gửi label.

**Ẩn nhóm này khỏi UI/khỏi tổng = tổng các dòng lệch tổng hoá đơn thật, và lệch theo hướng THIẾU** — vì
usage của nhóm này vẫn được tính tiền và cộng vào `chi_phi_tong` của `DanhSachKeyOut` (đọc từ
`repo.tien_tenant`, tính trên TOÀN BỘ `rated_usage` của tenant/khoảng, tức CÓ gồm nhóm `null`); nếu FE
lọc bỏ dòng `null` trước khi hiển thị mà vẫn hiện `chi_phi_tong` của backend, khách sẽ thấy tổng dòng <
tổng hiển thị mà không hiểu vì sao. Không có cảnh báo nào tự bật khi việc này xảy ra — bug hoàn toàn
phía UI.

⚠️ **`DongOwnerOut` mọc SÁU cột lượng (2026-08-24)** — `so_phien` · `input_tokens` ·
`output_tokens` · `cache_read_tokens` · `voice_sec` · `so_event`, khớp ĐÚNG bộ cột của
`DongKeyOut` để bảng «Lượt dùng chi tiết» đổi chiều gộp mà không đổi bộ cột. Hai điều đi
kèm: (a) **tổng theo owner PHẢI khớp tổng theo key** — có test canh chéo, và phép so đó
bắt cả hai chiều lệch (nhân bản số đo, và mất hàng); (b) `chi_phi = 0` nay có nghĩa
«chưa có giá» chứ không phải «không tồn tại» — bảng dẫn của `repo.theo_owner()` đã đổi
từ `rated_usage` sang `usage_events`, nên owner có số đo mà chưa được định giá **không
còn biến khỏi bảng**. Đừng gộp theo `nguoi_tao` ở client: bảng khoá có phân trang, nên
cộng trên trang hiện tại ra tổng của một TRANG, và nó sai âm thầm.

⚠️ **`DongOwnerOut` mọc thêm BẢY trường `chi_phi_<component>` (2026-08-27)** — cùng bảy
mã/cùng thứ tự với `DongKeyOut` (mục 1), tính bằng `repo.theo_owner()` mở rộng CTE `tien`
với cùng mệnh đề `FILTER (WHERE component = …)` rồi `sum()` từng cột đó theo owner CẠNH
`sum(t.chi_phi)` đã có — `tien` vẫn ở hạt KHOÁ trước khi gộp nên `sum()` qua nhiều khoá
của một owner không nhân bản, giữ nguyên bất biến gộp-hai-tầng ở trên. Trong một hàng,
tổng bảy trường này THƯỜNG bằng `chi_phi`, cùng ngoại lệ (component ngoài bảy mã đã biết)
đã ghi ở mục 1.

⚠️ **Cùng nhóm `null`, giờ cũng được giữ ở `GET /billing/by-owner`** (`DongOwnerOut.user_id: str | None`,
sửa 2026-08-20) — trước đó `theo_owner` JOIN `control.agent_keys` bằng INNER, và `NULL = NULL` không
khớp trong SQL nên nhóm usage chưa gán được khoá bị loại thẳng khỏi màn "theo owner" (tổng theo owner
nhỏ hơn tổng theo key/tổng tenant, không lỗi nào phát ra). Giờ một dòng `user_id: null, ten: null, email:
null` xuất hiện thay cho việc biến mất — FE hiện nhãn tương tự mục "chưa phân loại" ở trên cho dòng này.

---

## Layout `units` / `text_units` (đổi 2026-08-20, bên agent)

Bên agent đổi ngữ nghĩa hai cột. Migration `0948_billing_text_units` theo đúng thay đổi đó.

| Cột | Nghĩa MỚI | Trước 2026-08-20 |
|---|---|---|
| `units` | **số lần gọi / sự kiện**, thống nhất cho MỌI component (lời gọi LLM, clause synth, lần mở stream, lần verify, lời gọi embed) | mỗi component một nghĩa — `tts` giữ số ký tự, `embed` giữ "số đoạn text" |
| `text_units` | **lượng text theo ký tự** — cột MỚI | không tồn tại |

Cơ sở tính tiền đổi theo:

- `tts` → `text_units` (ký tự ĐƯA VÀO TTS). `units` nay chỉ là số clause đã synth, **không phải tiền**.
- `embed` → `text_units` (ký tự đem embed), đơn giá là **đ/ký tự**, không còn đ/đoạn.
- `stt` + `conversation` → có **HAI** cơ sở, **CỘNG NHAU**: `audio_sec` (giây audio gửi lên) **và**
  `text_units` (ký tự transcript trả về). Vendor kiểu Soniox thu hai đồng hồ; vendor không thu theo
  text thì đặt đơn giá `text_units` = 0.

⚠️ **Luật "STT chỉ một cơ sở" chỉ áp cho cặp THỜI LƯỢNG** (`audio_sec` vs `wall_ms` — hai cách đo
cùng một quãng, đặt giá cả hai là tính tiền hai lần). `text_units` **nằm ngoài** luật đó và được
phép có giá đồng thời. DB cưỡng chế đúng như vậy (`price_item_stt_single_basis`).

⚠️ **FE đừng dùng `EventOut.units` để giải thích tiền TTS.** Nó là số clause. Số tiền TTS đến từ
`EventOut.text_units`. Đây là chỗ dễ nhìn nhầm nhất sau đợt đổi này — một event TTS điển hình có
`units = 7` và `text_units = 1115`.

⚠️ **Dòng ghi TRƯỚC 2026-08-20 mang layout cũ** (ký tự TTS nằm trong `units`, `text_units = 0`) và
sau migration **không được tính tiền cho phần ký tự**. `price_coverage_gap` cũng không kêu, vì
`text_units = 0` nghĩa là không có lượng nào để tính. Bên agent xác nhận toàn bộ là dữ liệu
dev/test nên không backfill.

## 3. Đừng cộng `audio_sec` chéo component — kể cả khi tự tính từ `events`

`vad`, `call`, `stt`, `tts`, `speaker_verify` là các bước xử lý **cùng một đoạn audio nói chồng lên
nhau theo thời gian thực** (VAD quét, STT nghe, TTS phát, speaker-verify đối chiếu giọng, `call` đo cả
cuộc) — không phải các đoạn audio tách biệt nối tiếp. Cộng `audio_sec` của nhiều component lại nghĩa là
tính một giây vật lý 3–4 lần. Đây là đúng cái lỗi mà bản trước 2026-08-20 của `voice_sec` mắc phải ở
tầng API — xem mục 1.

Hệ quả cho FE:
- Từ 2026-08-20, field `voice_sec` cấp tổng (mục 1) **KHÔNG còn cộng chéo** — nó là `audio_sec` của
  riêng `call` (thời lượng cuộc gọi), nên dùng an toàn để hiển thị "bao nhiêu giây gọi thực".
- Khi hiện breakdown theo component (từ `events` của `sessions/{session_id}`), hiện **từng component
  riêng một dòng/một thanh** — **ĐỪNG tự cộng** các `audio_sec` đó lại thành một "tổng giây audio" của
  riêng mình. Đó chính là phép cộng chéo mà `voice_sec` cấp tổng đã sửa để tránh; tự làm lại ở tầng FE
  là tái tạo đúng con số sai đã bị gỡ.
- Chỉ có **tiền** (`chi_phi`, đơn vị tiền tệ, `Decimal` trong toàn bộ contract — không field tiền nào là
  `float`) được phép cộng chéo component một cách an toàn, vì mỗi (event, metric) chỉ sinh ra đúng một
  dòng `rated_usage` — không có phép đo trùng lặp ở tầng tiền như ở tầng giây.

---

## 4. `turn_idx` xấp xỉ — hiện `ghi_chu_turn`, đừng để người dùng đối chiếu theo lượt

`EventOut.turn_idx: int | None` — TTS của lượt hội thoại N có thể nằm trong lô ghi nhận của lượt
`N + 1` (agent ghi nhận theo lô, không đồng bộ tuyệt đối với lượt). Vì vậy số liệu **theo từng lượt**
trong timeline của một phiên chỉ để đọc lướt, không chính xác để đối chiếu.

Số liệu **theo phiên** (`ChiTietPhienOut.phien`, tức `PhienUsageOut`) và **theo tháng/theo khoảng ngày**
(`TongQuanOut`, `DanhSachKeyOut`, ...) đều đúng — sai lệch chỉ nằm ở việc gán một dòng audio cho ĐÚNG
lượt nào trong danh sách `events`, không ảnh hưởng tổng.

`ChiTietPhienOut.ghi_chu_turn` là field string do chính backend soạn sẵn (mặc định: *"turn_idx của dòng
audio là xấp xỉ (TTS của lượt N nằm ở lô N+1). Tổng theo phiên luôn đúng; đừng dùng số theo từng lượt để
đối chiếu tiền."*). **Màn chi tiết phiên PHẢI hiện nguyên văn field này** (banner/tooltip, không cần dịch
lại) — không hiện nó thì người dùng đối chiếu tiền theo từng lượt, thấy lệch, và báo "hệ thống tính
sai" trong khi hệ thống đúng.

---

## 5. Dải cảnh báo Overview (`TongQuanOut.canh_bao` = `CanhBaoOut`) — không phải chip trang trí

| Field | Kiểu | Ý nghĩa thật |
|---|---|---|
| `thieu_gia` | `int` | Số cặp (component, metric) đang có usage mà **chưa có dòng giá nào khớp** (đếm từ view `billing.price_coverage_gap`, lọc theo tenant hiện tại) |
| `nhan_chua_phan_loai` | `int` | Số nhãn `purpose` agent gửi lên mà NobleX chưa xác nhận tính tiền hay không (view `billing.purpose_unclassified` — **không lọc theo tenant**, đây là danh mục dùng chung) |
| `event_khong_so_do` | `int` | Số event không có số đo nào (mọi cột lượng đều 0) ⇒ không tính được tiền cho event đó |
| `llm_khong_chinh_xac` | `int` | **Số lượng** event `component='llm'` có `exact=false` — đo THIẾU token. ⚠️ Đây là một con số đếm (COUNT), **không phải tỷ lệ/phần trăm** — brief lúc lập plan gọi nó là "tỷ lệ token đo thiếu", code trả một số đếm event; hiện nó như một con số, đừng tự chia ra phần trăm rồi trình bày như thể backend đã tính tỷ lệ đó. |

**`thieu_gia > 0` nghĩa là đang mất doanh thu NGAY LÚC NÀY** — có usage thật đang chạy qua hệ thống mà
không được tính tiền, và sẽ không tự sửa (usage mới vẫn tiếp tục không được định giá cho tới khi ai đó
thêm dòng giá thiếu). **Phải hiện như lỗi (đỏ, cần hành động), không phải info chip** — đây không phải
tuỳ chọn thiết kế, nó phản ánh đúng mức độ nghiêm trọng của dữ liệu.

`llm_khong_chinh_xac` hiện để NobleX biết mức độ dữ liệu thiếu, nhưng **đừng "bù" nó bằng ước lượng** ở
bất kỳ đâu (không suy ra token trung bình rồi cộng thêm vào tổng hiển thị) — nguyên tắc của module này
là hoá đơn không bao giờ được **vượt** mức tiêu thụ thật; ước lượng thêm có thể làm khách bị tính nhiều
hơn thực tế đã dùng, đúng chiều nguy hiểm ngược với "mất doanh thu".

---

## 6. `price_coverage_gap` là báo động SAU-THỰC-TẾ — gán bảng giá không được kiểm tra trước

Hai endpoint admin dễ hiểu nhầm là "an toàn vì có kiểm tra":

- `POST /admin/billing/price-versions/{pb}/activate` (`kich_hoat_bang_gia` → `service.kich_hoat`) —
  đây LÀ chỗ có kiểm tra thật: nó so `billing.pricing_basis` (danh mục "component nào phải có giá theo
  metric nào") với các dòng giá đã nhập trong bảng giá, và **chặn kích hoạt** (409 `BANG_GIA_CON_LO`)
  nếu còn thiếu. Kích hoạt xong, `status` đổi `'active'`.
- `POST /admin/billing/tenants/{tenant_id}/price-version` (`gan_bo_gia` → `service.gan_cho_tenant`) —
  đây **KHÔNG** kiểm tra bảng giá đó đã active hay đã đủ giá. Đọc `service.py`: hàm này CHỦ Ý không đòi
  `price_version.status == 'active'` (docstring giải thích lý do — `status` chỉ là nhãn vận hành cho
  UI, không phải nguồn sự thật lúc định giá; `billing.resolve_price_version()` không đọc `status`).
  Nó chặn hai việc: gán một mốc `effective_from` lùi vào kỳ đã có `rated_usage` (409
  `MOC_QUA_KHU_DA_DINH_GIA`), và gán một mốc TRƯỚC `effective_from` của khoảng đang mở hiện tại — vd
  khoảng đang mở bắt đầu ở tương lai (409 `MOC_TRUOC_KHOANG_DANG_MO`, sửa 2026-08-20; trước đó ca này rơi
  thẳng vào `CheckViolationError` (500) vì câu UPDATE đóng khoảng cũ không hỏi nó bắt đầu từ đâu).

Nghĩa là: **một tenant có thể bị gán một bảng giá còn lỗ** (`status='inactive'`, chưa qua `/activate`,
hoặc đã active nhưng sau đó phát sinh component/metric mới chưa có giá — ví dụ `embed` khi nó bắt đầu có
dữ liệu). Không có cổng nào chặn việc gán đó ở API. Cơ chế phát hiện DUY NHẤT là
`billing.price_coverage_gap` — và nó chỉ kêu SAU KHI job định giá (`billing.rate_usage()`) đã chạy trên
usage thật, tức SAU KHI một phần usage đã bị định giá bằng 0 (không có dòng giá khớp = không tính tiền,
không lỗi nào phát ra). **Đừng để màn admin trình bày "Gán bảng giá" như một hành động an toàn hoặc đã
được xác thực trước** — nó không được xác thực trước; `thieu_gia` trên Overview của tenant đó là cách
duy nhất để phát hiện, và tại thời điểm nó kêu, một phần doanh thu đã lọt.

---

## 7. `contracts/actions.json` — action `billing.read` chưa được copy sang FE

**Đang treo, nhớ làm ngay:** `contracts/actions.json` (sinh từ `core/auth/actions.py` bằng
`make contracts`) đã có `"billing.read"` trong danh sách `actions` ở repo backend, đã commit. File
tương ứng ở repo `odyssey-portal-frontend` (`contracts/actions.json`) **CHƯA có** — đã kiểm bằng cách
đọc trực tiếp file đó trong checkout hiện tại, 0 dòng chứa "billing". Việc copy file này qua repo kia là
**thao tác tay, không có CI nào so hai bên** (README của `contracts/` tự thừa nhận khoảng hở này) — nếu
không ai copy, FE build ra một bảng quyền không biết `billing.read` tồn tại, và bất kỳ chỗ nào FE tự suy
menu/quyền từ `actions.json` sẽ thiếu hẳn mục Usage & Billing dù backend đã mở endpoint. Đây là việc DỄ
QUÊN NHẤT trong toàn bộ đợt bàn giao này — ghi ra đây để không ai phải đoán lại.

---

## Phụ lục — sai lệch so với `task-11-brief.md` (bản sketch lúc lập plan)

Task này yêu cầu đọc code thật thay vì chép sketch. Ba điểm sketch nói khác code — code thắng:

1. Sketch: "5 endpoint admin". Code (`router.py`): **6** — `liet_ke_bang_gia`, `tao_bang_gia`,
   `tao_dong_gia`, `kich_hoat_bang_gia`, `preview_bang_gia`, `gan_bo_gia`.
2. Sketch dùng tên field camelCase (`agentKeyId`, `voiceSec`, `chiPhiTong`, `ghiChuTurn`,
   `canhBao.thieuGia`, `canhBao.llmKhongChinhXac`) — code trả **snake_case**
   (`agent_key_id`, `voice_sec`, `chi_phi_tong`, `ghi_chu_turn`, `canh_bao.thieu_gia`,
   `canh_bao.llm_khong_chinh_xac`). Tài liệu này dùng tên thật.
3. Sketch: `canhBao.llmKhongChinhXac` là "tỷ lệ token đo thiếu". Code: `llm_khong_chinh_xac` là một
   **số đếm** event (`int`), không phải tỷ lệ — xem mục 5.
