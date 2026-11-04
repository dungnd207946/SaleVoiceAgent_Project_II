# Billing usage metering — đo tiêu thụ để tính tiền

> **Mục đích:** agent thống kê **số lượng thô** đã tiêu thụ mỗi phiên — token LLM
> (4 loại) và thời lượng STT / TTS / VAD / speaker-verification / cuộc gọi — rồi ghi
> vào một bảng Postgres do Portal sở hữu. **Việc quy đổi ra tiền và hiển thị hoàn toàn
> thuộc backend Portal**; agent không biết đơn giá và không đọc lại bảng.
>
> **Ràng buộc gốc (không thương lượng):** việc đo **không được làm tăng độ trễ** của
> hệ thống. Đường nóng chỉ được phép cộng số trong RAM.
>
> **Hợp đồng bảng + GRANT (Portal thực hiện):**
> [`docs/handoff/agent-postgres-billing-write-contract.md`](../../handoff/agent-postgres-billing-write-contract.md).
> **Trực quan hoá luồng:** [`docs/billing-flow-animation.html`](../../billing-flow-animation.html).
>
> Ngày: 2026-08-18. Nhánh: `feat/share-agent`.

---

## 1. Quyết định đã chốt

| # | Quyết định | Hệ quả |
|---|---|---|
| 1 | Ghi **cả hai** loại thời gian: `audio_sec` (số giây âm thanh, đi vào hoá đơn) **và** `wall_ms` (thời gian xử lý thực, theo dõi giá vốn) | Hoá đơn tái lập được vì không phụ thuộc tải máy; vẫn thấy được giá vốn của VAD/SV chạy local |
| 2 | **Một row mỗi lượt**, không phải một row mỗi phiên | Chịu được cuộc gọi rớt; truy vết được lượt nào tốn; rollup theo phiên dựng bằng VIEW |
| 3 | **Đo mọi đường gọi LLM**, gắn nhãn `purpose`; Portal quyết nhãn nào tính tiền | Nhìn thấy giá vốn của summary / warm-cache / addressee-gate — ba đường nền hiện không ai đếm |
| 4 | Bảng nằm ở **schema `billing` do Portal sở hữu**, agent chỉ có `INSERT` | Append-only được **DB cưỡng chế**, không dựa vào kỷ luật code; tenant không xoá được hoá đơn của chính mình |
| 5 | Agent ghi bằng **role per-tenant** lấy từ runtime-credentials API, qua `pool_for_tenant` | Không thêm role, không thêm env; cách ly do policy `portal.current_tenant()` lo |

Quyết định 2 và 4 khoá lẫn nhau: phương án "một row mỗi phiên, upsert cộng dồn" cần
quyền `UPDATE`, nên **không tương thích** với ràng buộc append-only ở quyết định 4.
Ghi theo lượt chỉ cần `INSERT`.

---

## 2. Kiến trúc — tách "đo" khỏi "ghi"

```
        ĐƯỜNG NÓNG (trong lượt)          — chỉ cộng số trong RAM, không I/O
  mic → VAD → STT → LLM → TTS → loa
         │     │     │     │
         └─────┴─────┴─────┴──────────►  UsageMeter  (list + counters, per session)
  ─────────────────────────────────────────────  ranh giới I/O  ─────────────────
                                          │  drain()  ← sau save_all, và lúc đóng phiên
                                          ▼  fire_and_forget
                                    INSERT … ON CONFLICT DO NOTHING
                                          ▼
                                 billing.usage_events   (Portal sở hữu)
                                          ▼
                          VIEW rollup → × bảng giá → hoá đơn   (ngoài phạm vi agent)
```

### 2.1 `billing/meter.py` — `UsageMeter`

Một instance mỗi phiên. Thuần in-memory, **không `await` nào**.

| API | Việc |
|---|---|
| `add_llm(purpose, provider, model, in_, out, cache_write, cache_read, exact)` | append một dataclass vào `list` |
| `add_audio(component, audio_sec, wall_ms, units)` | cộng vào bộ đếm tích luỹ |
| `drain()` | trả về event chưa ghi **+ delta** của bộ đếm tích luỹ kể từ lần drain thành công trước |
| `commit(seq)` | đánh dấu lô `seq` đã ghi thành công |

Toàn bộ chi phí trên đường nóng = một phép append và vài phép cộng float. Không khoá
(asyncio đơn luồng), không serialize, không syscall.

**Ngữ nghĩa "đồng hồ đo" của `drain()`** là thứ giải quyết gọn vấn đề VAD và thời lượng
cuộc gọi: chúng chạy liên tục và **không thuộc lượt nào**, nên meter giữ số tích luỹ
còn mỗi lần rút chỉ ghi ra phần tăng thêm. Ghi thẳng số tích luỹ sẽ tính tiền hai lần
cho cùng một quãng âm thanh.

**Gộp trước khi ghi:** `drain()` gộp theo `(component, purpose, provider, model)`. Một
lượt có thể gọi LLM tới 5 lần (vòng tool) — gộp lại thành một dòng, `units` giữ số lời
gọi. Đây là điều kiện để khoá UNIQUE của contract không bị đụng.

**Chặn trên bộ nhớ:** danh sách chờ có cap cố định (2000 event). Vượt thì bỏ event
**cũ nhất** và log. Nếu Postgres chết suốt một cuộc gọi dài, mất số liệu vẫn tốt hơn
làm sập process đang phục vụ cuộc gọi.

### 2.2 `billing/sink.py`

Nhận output của `drain()`, INSERT một batch qua `pool_for_tenant(tenant_id)` + `tenant_conn`
(đã set `app.tenant_id` / `app.current_tenant` bằng `SET LOCAL`), gọi qua `fire_and_forget`
(`storage/persist.py`). Không `RETURNING`, không đọc lại. Không bao giờ ném ra ngoài.

### 2.3 Điểm flush

| Điểm | Vị trí |
|---|---|
| Sau mỗi lượt | `agent/orchestrator.py`, ngay sau `save_all` thành công — cạnh `seed_conversation` / `persist_turn_messages` hiện có |
| Đóng phiên | `server/base_session.py::stop` (WebRTC + LiveKit — kế thừa `BaseSession`), `telephony/session.py::TelephonySession._cleanup` (độc lập, tự flush riêng), và đường đóng phiên của `server/text_chat.py` |

**Không có timer định kỳ.** Lượt hội thoại vốn đã đủ dày; phiên câm hoàn toàn (gọi vào
rồi cúp, không nói gì) đã được lần drain cuối phủ. Thêm timer là phức tạp trả trước cho
một khoảng trống không tồn tại.

### 2.4 Nối vào `StreamingClient` — contextvar, không đổi chữ ký

Meter đi qua một `ContextVar` (đúng khuôn `tenant/current.py::current_tenant()`).
`StreamingClient` tự đọc contextvar và tự ghi usage; **không** đổi kiểu trả về
`(content, tool_calls)` của `stream_completion`, nên không có thay đổi lan xuyên 5 tầng.

`asyncio.create_task` sao chép context, nên task summary / warm-cache sinh ra trong lượt
**tự động** kế thừa đúng meter và đúng tenant.

Ngược lại, nhãn `purpose` là **tham số tường minh** của `stream_completion` /
`complete_once` / `simple_completion` (mặc định `"conversation"`), chỉ 4 call-site. Để
`purpose` ẩn trong contextvar sẽ khiến gán nhãn sai mà không ai thấy.

---

## 3. Mô hình dữ liệu

Bảng, cột, ràng buộc, GRANT, RLS, VIEW rollup: xem
[`agent-postgres-billing-write-contract.md`](../../handoff/agent-postgres-billing-write-contract.md).
Ba điểm agent phụ thuộc trực tiếp:

1. **`UNIQUE (tenant_id, session_id, seq, component, purpose, provider, model)`** — cơ chế
   retry của agent (mục 6) dựa hoàn toàn vào nó. Thiếu ràng buộc này thì mỗi lần retry
   sinh dòng mới và khách bị tính tiền hai lần.
2. **`event_id` là identity column**, không phải `bigserial` — để quyền dùng sequence
   được ngụ ý bởi `INSERT`, tránh một lỗi phân quyền fail im lặng.
3. **`provider` / `model` `NOT NULL DEFAULT ''`** — chúng nằm trong khoá UNIQUE, mà
   `NULL != NULL`.

---

## 4. Bắt token — 5 điểm

| Vị trí | Việc |
|---|---|
| `agent/llm/anthropic_provider.py::_adapt_stream` | Gom `usage` từ `message_start` (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`) và `message_delta` (`output_tokens`), gắn vào chunk phát ra ở `message_stop`. Hiện hai event này bị bỏ qua hoàn toàn. |
| `agent/llm/client.py::_stream_once` | Đọc `chunk.usage` nếu có; kết thúc stream thì ghi vào meter |
| `agent/llm/client.py::_apply_provider_shaping` | Thêm `stream_options={"include_usage": True}` cho slot tương thích OpenAI, **theo allowlist tường minh** |
| `complete_once` / `simple_completion` | Non-stream, `usage` nằm thẳng trên response. Đây là đường **addressee gate** dùng (`voice/addressee_gate.py::_classify_llm` gọi `complete_once`) — bỏ sót là mất nguyên nhãn `addressee_gate` |
| 4 call-site | Truyền `purpose=` tường minh |

**Rủi ro của `stream_options`:** provider không hỗ trợ sẽ trả **400**, mà 400 là lỗi
non-transient → `stream_completion` nhảy sang provider kế trong chain. Bật ẩu một cờ đo
lường có thể **làm hỏng cuộc gọi**. Vì vậy allowlist theo từng slot đã kiểm chứng, mặc
định **tắt** cho slot chưa biết — thà thiếu số liệu (`exact=false`) còn hơn rớt cuộc gọi.

**Độ chính xác của output token khi bị ngắt lời.** `client.py::_stream_once` `break`
khỏi vòng stream và đóng stream ngay khi `interrupt_check()` true, nghĩa là
`message_delta` — nơi chứa `output_tokens` — **chưa từng về**. Input/cache token vẫn
chính xác vì đến từ `message_start`. Agent ghi `exact=false` + output = 0, **không ước
lượng**. Hệ quả thẳng thắn: với voice bật barge-in, output token bị đếm thiếu một cách
**có hệ thống**, mức thiếu tỉ lệ với tần suất khách ngắt lời. Cột `exact` tồn tại chính
để đo mức thiếu đó.

---

## 5. Đo thời lượng — 5 điểm

Browser WebRTC (`server/session.py::Session`) và LiveKit (`transport/livekit/room_session.py::RoomSession`)
đều kế thừa `BaseSession`/dùng chung `VoiceAgent` nên 5 điểm dưới đây cắm một lần là
phủ cả hai. **`telephony/session.py::TelephonySession` KHÔNG kế thừa `BaseSession`** —
nó là một class độc lập tự dựng VAD/STT/`VoiceAgent` riêng — nên được đo bằng một bộ
điểm móc tương đương wired thủ công trong chính file đó (fix round 1, 2026-08-18).

| Thành phần | Điểm móc | Cách đo |
|---|---|---|
| **VAD** | `server/base_session.py::process_audio_frame`, vòng cắt chunk | `audio_sec += vad_chunk_ms/1000` mỗi vòng; `wall_ms` bằng `perf_counter` quanh `process_chunk` |
| **STT** | cùng hàm, nhánh `await self.stt.send(chunk)` | `audio_sec += len(chunk)/(rate*2)` trên **chunk thật**; `wall_ms` = thời gian stream STT mở |
| **TTS** | `voice/voice_agent.py`, quanh `synth_t0` / `_iter_clause_audio` | cộng byte frame → `audio_sec`; `len(sc.text)` → `units` (ký tự) |
| **Speaker verify** | `server/base_session.py::_embed_current_utterance` | `audio_sec` = độ dài `_utterance_pcm`; `wall_ms` quanh lời gọi; `units += 1` |
| **Cuộc gọi** | `server/base_session.py::stop` | `session_duration` đã tính sẵn tại đó |

**Im lặng tổng hợp của STT không tính cho khách.** Khi cổng vào đóng, agent tự bơm im
lặng vào STT để endpoint kích đúng nhịp (`_input_gate.keepalive`). Im lặng đó vẫn được
gửi lên provider nên **vẫn nằm trong hoá đơn nhà cung cấp**, nhưng nó do agent tạo ra
chứ không phải khách nói. Vì vậy: `audio_sec` chỉ đếm audio thật của khách (cái tính cho
khách), phần im lặng phản ánh trong `wall_ms` = thời gian stream mở (cái phản ánh giá vốn).

**Speaker verify móc ở call-site async, không móc trong `SpeakerEmbedder.embed()`** — dù
`embed()` là phễu duy nhất — vì nó là singleton dùng chung cho mọi phiên, và móc ở đó thì
việc quy đúng phiên phải dựa vào contextvar xuyên `to_thread`, tức là một cơ chế ngầm cho
một thứ đáng ra tường minh.

---

## 6. Xử lý lỗi & suy giảm

- **Sink không bao giờ ném ra ngoài.** Hỏng thì cuộc gọi vẫn chạy bình thường.
- **`drain()` chỉ đánh dấu đã-ghi khi INSERT thành công** → thất bại là tự động thử lại
  ở lượt sau **với đúng `seq` cũ**, không cần hạ tầng retry riêng. Nếu lần trước thực ra
  đã ghi được (lỗi xảy ra lúc trả lời), lần thử lại trùng khoá và bị `DO NOTHING` bỏ qua.
- **Log `error` lần thất bại đầu tiên mỗi phiên**, kèm `current_user` + SQLSTATE, để phân
  biệt ba nguyên nhân nhìn giống hệt nhau: chưa cấp `INSERT` (`42501`), credential hết hạn
  (`28P01`), Postgres không tới được.
- **Lần drain cuối lúc đóng phiên**: nếu vẫn hỏng, dump payload JSON ra log mức `error`
  để còn cứu lại được.

| Tình huống | Mất gì |
|---|---|
| Chưa cấp `INSERT` / credential hết hạn / PG không tới được | Không mất — giữ trong RAM, thử lại; tự khỏi khi điều kiện phục hồi |
| Process agent chết giữa phiên | **Mất vĩnh viễn** phần tiêu thụ kể từ lượt hoàn tất gần nhất |
| Vượt cap 2000 event | Mất event cũ nhất, có log |

Cơ chế này phủ lỗi thoáng qua nhưng **không** phủ được process chết hoặc credential sai
suốt cả phiên. Muốn mất-mát-bằng-0 thì cần DLQ bền (Redis, replay sau — repo đã có khuôn
`with_mongo_retry_and_dlq`). **Ngoài phạm vi lần này** (mục 10).

---

## 7. Cấu hình

| Env | Mặc định | Vai trò |
|---|---|---|
| `BILLING_METERING_ENABLED` | `false` | Bật/tắt toàn bộ. Mặc định tắt vì contract phụ thuộc Portal ship bảng trước; bật sẵn thì mọi phiên log error cho tới khi họ xong. Bật sau khi Portal tick xong §11 của contract. |

Không thêm env nào khác. Đường ghi tái dùng `POSTGRES_*` và cơ chế credential per-tenant
sẵn có.

---

## 8. Bất biến phải giữ

1. **Đường nóng không có I/O.** Trong lúc lượt đang chạy, không có lời gọi mạng/đĩa nào
   phục vụ billing. Có test giữ điều này (mục 9).
2. **Một dòng đã INSERT không bao giờ được agent sửa hay xoá.** Agent không có quyền, và
   cũng không có code đường ghi nào làm việc đó.
3. **Không ước lượng số liệu.** Thiếu usage thì ghi `exact=false`, không đoán.
4. **Không có giá trong agent.** Không cột tiền, không bảng giá, không đọc lại bảng.
5. **`seq` đơn điệu tăng trong phiên** và không đổi khi retry.

---

## 9. Kế hoạch test (TDD — test trước)

**Unit — `UsageMeter`**
- Bộ đếm tích luỹ: drain hai lần liên tiếp → lần hai chỉ trả **phần tăng thêm**.
- Gộp theo `(component, purpose, provider, model)`: 5 vòng tool trong một lượt → **một**
  dòng `llm` với `units=5`.
- INSERT thất bại → event **vẫn còn** trong meter; drain sau trả lại đúng `seq` cũ.
- Vượt cap → bỏ event cũ nhất, không ném.

**Unit — bắt token**
- Stream Anthropic giả lập → 4 cột token map đúng, `exact=true`.
- Stream bị ngắt giữa chừng (không có `message_delta`) → `exact=false`, input token vẫn đúng.
- Provider không trả usage → `exact=false`, token = 0, **không đoán**.
- `complete_once` (đường addressee gate) ghi được usage với `purpose="addressee_gate"`.

**Unit — bất biến latency**
- Chạy một lượt giả với sink là spy: khẳng định **sink không được gọi** trong lúc lượt
  đang chạy, chỉ sau `save_all`. Đây là test giữ cho yêu cầu gốc không bị bào mòn bởi
  các thay đổi về sau.

**Integration (`needs_postgres`)**
- INSERT thành công với grant đúng; `UPDATE` bị từ chối.
- Ghi `tenant_id` sai bị `WITH CHECK` chặn.
- INSERT lại cùng `seq` → `DO NOTHING`, không nhân dòng.

**Thủ công** — thêm mục vào `src/noble_agent/SMOKE.md`: thay đổi này chạm turn loop nên
bắt buộc theo quy tắc trong CLAUDE.md.

---

## 10. Ngoài phạm vi

- **Cưỡng chế quota / chặn khi tenant hết hạn mức.** Agent không đọc bảng này nên không
  tự dừng được. Nếu cần, cơ chế phải nằm ở gateway/Portal và là một hạng mục riêng.
- **DLQ bền cho billing** (mục 6). Chỉ retry-trong-phiên lần này.
- **Bảng giá, quy đổi, hiển thị, đối soát.** Thuộc Portal.
- **Đo embedding của `send_media`** — thang giá riêng, để sau nếu cần.

---

## 11. Điểm chưa quyết — cần trả lời trước khi code

Bốn câu ở §12 của contract cần Portal + chủ sản phẩm trả lời:

1. Tên schema/bảng: `billing.usage_events` hay `control.agent_usage_events`?
2. Portal cấp `GRANT` cho **role nào**? Agent đi qua `pool_for_tenant`, tức là dùng role
   per-tenant khi có credential và **rơi về role dùng chung `odyssey_agent`** khi không
   có (dev/REPL, stash lỗi). Nếu chỉ cấp cho role per-tenant thì đường fallback sẽ bị
   policy chặn và mất số liệu; cấp cho cả hai thì không.
3. `vad` và `speaker_verify` có tính tiền khách không? Chúng chạy local nên `audio_sec`
   của chúng phản ánh khối lượng chứ không ứng với hoá đơn nhà cung cấp nào.
4. `purpose` nào tính tiền khách — đặc biệt `summary` và `addressee_gate`.

Hai câu thuộc phía agent:

5. Im lặng tổng hợp của STT: giữ cách tính ở mục 5 (không tính cho khách) hay tính cả?
6. Output token thiếu khi ngắt lời (mục 4): chấp nhận `exact=false`, hay cần một cơ chế
   khác?

Câu 1–2 chặn phần sink; câu 3–6 **không chặn** vì agent vẫn đo hết như đã chốt — chúng
chỉ ảnh hưởng công thức quy đổi phía Portal.

---

## 12. Việc kèm theo khi implement

Subsystem mới + env var mới + bề mặt ghi Postgres mới → theo quy tắc tự bảo trì trong
CLAUDE.md, cùng commit với code phải cập nhật:

- CLAUDE.md: mục **Layout** (thêm `billing/`), bảng **Key configuration** (thêm
  `BILLING_METERING_ENABLED`), mục **Storage** (bề mặt ghi thứ hai ngoài `tenant_data`).
- `docs/CHANGELOG-agent.md` (entry đầy đủ, lên đầu bảng) + bảng `## Change Log` cuối
  CLAUDE.md (bản 1–2 câu, xoá entry thứ 11).
- `src/noble_agent/SMOKE.md`.
