# Từ điển cách đọc TTS theo tenant — thiết kế

Ngày: 2026-08-24 · Repo chính: `odyssey-portal-backend` · Kèm sửa: `odyssey-portal-frontend`, `odyssey-agent`

## 1. Vấn đề

Agent chuẩn hoá văn bản trước khi gửi sang TTS bằng `normalize_for_voice()`
(`odyssey-agent/src/noble_agent/voice/tts/_normalize.py`). Hàm này chạy **trước** mọi
backend TTS, nên nó không phụ thuộc việc dùng API hay tự host model.

Ngoài ~40 pass regex (số · tiền · ngày/giờ · điện thoại · mã · đơn vị · đánh vần
ALL-CAPS), nó nạp **hai từ điển** từ `data/tts_normalize_vi.json`:

- `reading` (44 mục) — cách phát âm: `Vietcombank → việt com bank`
- `abbrev` (61 mục) — bung viết tắt: `NCLB → Noble Crystal Long Biên`

Ba khiếm khuyết:

1. Từ điển là **file trong repo agent**, nạp một lần lúc khởi động. Sửa cách đọc một mã
   dự án = sửa file + deploy lại agent.
2. Nó **không theo tenant**. Mã dự án của một khách bung ra ở agent của mọi khách.
3. Khách không có đường nào tự sửa. Portal là control-plane cho khách tự cấu hình agent,
   nhưng đúng thứ họ nghe sai hằng ngày lại không nằm trong tầm tay họ.

## 2. Phạm vi

**Làm**: thêm một khu trên màn `/agent` cho phép tenant thêm/xoá từng mục của **một** từ
điển cách đọc, đi theo nhịp «Lưu và áp dụng» như mọi ô khác của màn đó.

**Không làm** — nêu tường minh để lần sau không ai đọc thành thiếu sót:

- Không dọn file nền. Mọi mục ở đó ở lại và **không hiện trên UI**, kể cả các mã dự án
  riêng của NobleX. Hệ quả nhận trước: mã đó vẫn bung ở agent của khách khác. Rủi ro thấp
  (khách của họ không nói "NCLB"), và dọn nền là một quyết định có phạm vi riêng cần biết
  chính xác tenant nào để seed.
- Không có ô thử normalization tại chỗ.
- Không có công tắc bật/tắt nhóm luật regex.
- Không quản từ điển phoneme riêng theo backend (tầng 2 của `_normalize.py`:
  `load_normalize_map`/`apply_normalize` dùng bởi ElevenLabs/VieNeu).
- Không có cơ chế «ẩn một mục của nền». Chồng cùng khoá thì tenant thắng.

## 3. Hai tầng

Nền do platform giữ, lớp riêng do tenant giữ:

| | Nền | Lớp tenant |
|---|---|---|
| Ở đâu | `odyssey-agent/data/tts_normalize_vi.json` | `ConfigPayload.tts_normalization` → `tenant_data.agent_config` |
| Ai sửa | dev platform, qua deploy | khách, qua `/agent` |
| Có trên UI | không | có |
| Nội dung | ngân hàng · `2PN` · đơn vị · viết tắt phổ thông | mã dự án · tên thương hiệu · từ địa phương |

Trùng khoá thì **tenant thắng**.

### 3.1 Một từ điển, không phải hai

Nền có hai map vì `strict_upper` — khoá viết HOA toàn bộ khớp có phân biệt hoa/thường —
tồn tại để bảo vệ những viết tắt phổ thông đụng từ tiếng Việt thật: `vs`, `vat`, `hd`.
Lớp tenant gần như toàn danh từ riêng và mã dự án, không có va chạm đó.

Một bảng **không mất năng lực nào**, vì nó ghi đè được cả hai map nền:

- ghi đè mục `reading` — pass tenant chạy trước, văn bản không còn khoá đó khi pass
  `reading` tới;
- ghi đè mục `abbrev` — cùng cơ chế, nó **ăn token trước**.

Bắt người dùng chọn "Cách đọc" hay "Viết tắt" ở từng dòng là bắt họ hiểu thứ tự pass
trong pipeline để trả lời một câu mà đa số trường hợp cho cùng kết quả.

## 4. Hợp đồng (portal)

`src/portal/modules/config/contracts.py`:

```python
class NormalizationEntry(_Nghiem):
    term: str    = Field(min_length=1, max_length=60)
    read_as: str = Field(min_length=1, max_length=200)

# trong ConfigPayload, cạnh `giong`:
tts_normalization: list[NormalizationEntry] = Field(default_factory=list, max_length=200)
```

Khoá tiếng Anh nằm cạnh các khoá tiếng Việt đã có (`danh_tinh`, `pham_vi`, `giong`) —
`tools` cũng đã tiếng Anh. Payload là hợp đồng HTTP mà FE và `contracts/agent-config.json`
cùng đọc, nên đổi các khoá cũ không thuộc phạm vi việc này.

### 4.1 `SCHEMA_VERSION_HIEN_TAI` giữ nguyên `3`

Trường có `default` nên mọi hàng v3 trong `config_drafts`/`config_versions` vẫn validate,
không cần adapter đọc ngược. Nâng lên 4 làm `SCHEMA_VERSION_AGENT` lệch, và **agent từ
chối khởi động khi lệch** — portal deploy trước là mọi pod chết.

### 4.2 Danh sách ở payload, object ở bảng phẳng

- **Danh sách** ở payload: khoá trùng thành 422 tường minh thay vì bị JSON âm thầm lấy
  giá trị cuối, và giữ thứ tự người dùng nhập để bảng hiện đúng thứ tự họ thấy lúc gõ.
- **Object** `{"NCLB": "…"}` ở `tenant_data.agent_config`: đó đúng hình dạng agent đang
  parse từ file nền, nên phép trộn bên agent là một dòng, không phải một tầng dịch nữa.

Chỗ chuyển là `agent_config.hang_phang()`, đã có tiền lệ (`departments` giữ khoá tiếng
Việt, `skills` không sort).

### 4.3 Bốn phép validate

| Phép | Vì sao |
|---|---|
| khoá trùng, so **không** phân biệt hoa/thường ⇒ 422 | nghiêm hơn agent thật (`VS` và `vs` là hai mục hợp lệ về kỹ thuật), nhưng hai dòng trông giống nhau với hai kết quả khác nhau là bẫy không đáng bán cho người dùng này |
| `term.strip() != term` ⇒ 422 | khoá có khoảng trắng ở mép thì `\b` không bao giờ khớp — sai **im lặng** |
| `term == read_as` ⇒ 422 | dòng vô nghĩa, chỉ tốn một pass regex |
| ký tự điều khiển ở một trong hai ⇒ 422 | |

### 4.4 Trần

200 mục, `read_as` ≤ 200 ký tự. Mỗi lần publish đóng băng một bản copy vào
`config_versions` — bảng **bất biến** — nên đây là trần phình của bảng đó. Nền hiện có
44 + 61 mục; một sàn 30 dự án cần tầm 60 mục.

## 5. Đường đi tới agent

```
form → PUT /config/draft (config_drafts)
     → «Lưu và áp dụng» → config_versions (bất biến)
                        → UPSERT tenant_data.agent_config   ← agent đọc thẳng chỗ này
                        → bundle lên kho tệp (đường legacy)
```

⚠️ CLAUDE.md ghi rằng đường duy nhất agent nhận cấu hình đã publish là poll object `LIVE`
trên kho tệp. Đọc code agent thì không phải vậy:
`odyssey-agent/src/noble_agent/storage/agent_config_store.py` đọc **thẳng bảng phẳng
`tenant_data.agent_config`** qua Postgres (`_COLUMNS`, lọc tenant tường minh, cache
last-good trên đĩa). Bundle là đường `legacy` (`Settings.agent_config_source`).

### 5.1 Migration

```sql
ALTER TABLE tenant_data.agent_config
  ADD COLUMN tts_normalization jsonb NOT NULL DEFAULT '{}'::jsonb
  CONSTRAINT agent_config_tts_normalization_object_check
  CHECK (jsonb_typeof(tts_normalization) = 'object');
```

Theo khuôn `agent_config_departments_array_check` của `0910`. **Không cần `GRANT` mới** —
quyền là cấp bảng, cột mới thừa hưởng.

### 5.2 `config_agent`

`sang_config_agent()` thêm `voice.tts_normalization`. Kéo theo `make contracts` và **copy
tay** `contracts/agent-config.json` sang repo agent. Mục vàng phải khác mặc định phía
agent — mặc định là map rỗng, nên mọi map không rỗng đều thoả.

## 6. Giao diện

Một khu mới đặt **ngay trên `<RaoChan />`** trong **cả hai** file: `CauHinhChung.tsx`
(form sửa) và `TomTatCauHinh.tsx` (bản tóm tắt chỉ-đọc). Hai bên bắt buộc khai cùng các
khu theo cùng thứ tự; bỏ một bên là bấm «Sửa cấu hình» thì ô nhảy chỗ.

Hai component mới, dùng lại `components/ui/Bang.tsx` và khuôn dialog của
`platform/components/TaoKhoaDialog.tsx`:

- `NormalizationPreview` — trong `<The tieuDe="Cách đọc cho giọng nói">`: **3 dòng đầu** +
  `còn N mục nữa` + nút «Xem tất cả (N)». Nhận `readOnly` để dùng ở cả hai phía.
- `NormalizationDialog` — bảng đầy đủ. Chỉ-đọc ở bản tóm tắt; ở form thì mỗi hàng có nút
  xoá, cuối bảng có hàng thêm mới.

Ba chi tiết là quyết định, không phải trang trí:

**① Dialog KHÔNG lưu.** Nó sửa bản nháp trong bộ nhớ qua `sua(...)` như mọi ô khác, và
chỉ ra khách khi bấm «Lưu và áp dụng» ở ngoài. Nút đóng ghi **«Xong»**, không phải «Lưu»,
kèm một dòng chân dialog: *«Thay đổi có hiệu lực sau khi bấm Lưu và áp dụng.»* Không có
dòng đó thì một dialog có bảng và có nút được đọc là một biểu mẫu tự lưu — người dùng
đóng nó, thấy preview đã đổi, rồi rời màn mà không publish.

**② Trạng thái rỗng nói về nền mà không bày nền ra**: *«Chưa có mục nào. Agent đang dùng
bộ mặc định của nền tảng.»* Nếu chỉ ghi «Chưa có mục nào» thì người dùng kết luận agent
hiện đọc `Vietcombank` theo mặt chữ — sai, và họ sẽ đi nhập lại 44 mục đã có.

**③ Một dòng chú thích dưới bảng**: *«Từ viết HOA toàn bộ chỉ khớp khi khách cũng viết
HOA.»* Đây là chỗ duy nhất luật `strict_upper` lộ ra, và nó phải lộ ra — nếu không,
`HD → hợp đồng` sẽ viết lại cả chữ `hd` viết thường.

Kèm: mirror bốn phép validate ở client để 422 của backend không phải phản hồi đầu tiên ·
`ConfigPayload` trong `features/agent/api.ts` (bản **chép tay** của contract Python —
khoảng hở đã biết, cổng là 422) · msw handlers · `useBanNhap` phải chịu được `undefined`
khi backend chưa deploy.

## 7. Sửa ở `odyssey-agent`

### 7.1 `storage/agent_config_store.py`

`_COLUMNS` thêm `tts_normalization`.

⚠️ **KHÔNG thêm vào `_JSON_COLUMNS` như hai cột kia.** Dòng giải mã hiện tại là
`config[col] = _decode(config.get(col)) or []`, và `{}` là **falsy** trong Python — một từ
điển rỗng biến thành `[]`, rồi `parse_config` nhận list ở chỗ nó chờ dict. Hai cột jsonb
hiện có (`departments`, `skills`) đều là mảng nên dòng đó chưa từng sai. Cần một tập
riêng `_JSON_OBJECT_COLUMNS` với `or {}`.

### 7.2 Thứ tự deploy — một chiều, và hỏng theo kiểu im lặng

**Migration portal TRƯỚC, agent SAU.**

Đảo lại thì agent **không chết**: `read_published_config` bắt `except Exception`, log một
`warning`, rồi phục vụ cache last-good trên đĩa. Hệ quả thật nặng hơn một lần crash —
agent **đóng băng ở bản cache cũ**, và **mọi lần publish sau đó của portal bị bỏ qua**
không dấu hiệu nào ở phía người dùng. Pod mới chưa có cache thì `_read_last_good` trả
`None` — không có cấu hình nào.

### 7.3 `agent/agent_config.py`

`AgentConfig` thêm `tts_normalization: dict[str, str]`; `parse_config` giải mã.

### 7.4 `voice/tts/_normalize.py`

Lớp tenant là **một pass RIÊNG với `strict_upper=True`**, không phải phép trộn dict vào
`reading` — pass `reading` gọi không có cờ đó, nên trộn dict là mất luật ALL-CAPS.

Pod là **đơn-tenant** (`TenantContext` giải một lần lúc boot từ `TENANT_ID`), nên một
biến module-level `set_tenant_overrides()` là đủ; không phải luồn map qua từng lời gọi.

Chỗ gọi: nơi `AgentConfig` đã giải xong và `TenantContext` được dựng —
`tenant/db_context.py::context_from_config()` là ứng viên, cần xác nhận lúc thi công rằng
nó chạy trước lượt TTS đầu tiên và chạy lại khi config được nạp mới. Nếu không, `_normalize`
sẽ dùng nền trần ở những lượt đầu và không có triệu chứng nào ngoài việc agent đọc sai.

**Vị trí chèn: sớm — ngay sau bước strip URL/markdown/paren/email, TRƯỚC `_ROMAN_RE` và
`_CODE_RE`.** Hai lẽ:

- `_CODE_RE` đọc mọi thứ trông giống mã **theo từng chữ**. Đặt muộn thì tenant **không
  thể** dạy agent đọc `NPTTL-A12`; nó đã bị đánh vần xong trước khi map của họ được xem
  tới.
- Văn bản **thay ra** vẫn chảy qua toàn bộ pass phía sau, nên số/ngày/tiền trong đó vẫn
  được đọc đúng. Đặt sớm không mất gì.

Đổi lại, lớp tenant thắng **tuyệt đối**, kể cả thắng những pass platform viết ra để bảo
vệ. Với chủ đích «tôi muốn từ này đọc thế này» thì đó đúng là thứ cần.

`server/text_chat.py` gọi cùng hàm — không phải sửa.

### 7.5 `bundle._config_json` (đường legacy)

Thêm khoá tương ứng để hai đường không lệch. `sort_keys=True` sẵn có nên tính tất định
của sha bundle giữ nguyên.

## 8. Test

**Portal**: bốn phép validate của §4.3 · `hang_phang()` ánh xạ list → object ·
`sang_config_agent()` · migration round-trip · `truong_da_doi()` nêu được trường.

**Agent**: tenant thắng mục `reading` của nền · tenant thắng mục `abbrev` của nền · khoá
viết HOA phân biệt hoa/thường · khoá trông giống mã vẫn khớp (chứng minh vị trí pass) ·
văn bản thay ra vẫn được đọc số · cột object rỗng không biến thành `[]`.

## 9. Hạn chế nhận trước

`truong_da_doi()` so danh sách bằng `!=`, nên popup xác nhận nói `tts_normalization` đã
đổi mà không nói đổi mục nào. Chấp nhận ở v1.
