# Contract — Bề mặt Postgres agent GHI: billing usage (Portal ship)

> **Đối tượng:** team Admin Portal / Backend (Odyssey).
> **Mục tiêu:** agent hội thoại ghi **số liệu tiêu thụ thô** (token LLM + thời lượng
> STT/TTS/VAD/speaker-verification + thời lượng cuộc gọi) vào một bảng **do Portal sở hữu**,
> để backend quy đổi ra tiền và hiển thị. **Agent chỉ thống kê — không biết giá, không quy đổi,
> không đọc lại.**
> **Đối xứng với:** `docs/handoff/agent-postgres-read-contract.md` (bề mặt ĐỌC). Tài liệu này
> đặc tả bề mặt **GHI** thứ hai của agent, sau `control.agent_heartbeats`.
> **Cách QUY ĐỔI RA TIỀN** (biến giá, công thức voice/chat, SQL rollup mẫu, bẫy cộng-đôi):
> [`portal-billing-pricing-guide.md`](portal-billing-pricing-guide.md).
> Ngày: 2026-08-18 · cập nhật 2026-08-20 (thêm cột `text_units`, chuẩn nhất `units` = số lần gọi).

---

## 0. Nguyên tắc

- **Agent chỉ ghi thêm, không sửa.** Không `UPDATE`, không `DELETE`, không `TRUNCATE`. Tính chất
  **append-only phải được cưỡng chế bằng GRANT**, không bằng quy ước code — một bug trong
  agent, hay một role tenant tò mò, đều không được sửa dòng đã ghi.
  **Có `SELECT`, và nó là bắt buộc về mặt kỹ thuật** — Postgres đòi quyền `SELECT` cho
  `INSERT … ON CONFLICT ON CONSTRAINT … DO NOTHING`, tức chính cơ chế idempotency ở §4.
  Đã đo thật, xem §5. `SELECT` bị policy RLS giới hạn trong tenant của transaction hiện tại
  nên nó **không** phá cách ly, và không cho phép sửa gì.
- **Portal sở hữu toàn bộ:** sở hữu schema/bảng/policy, cấp quyền, quyết định lưu trữ bao lâu.
  Repo agent không có role admin ở đây; DDL ở §1 do `portal_migrator` chạy (lần đầu đã chạy
  2026-08-18 — xem §14).
- **Cách ly tenant dùng `portal.current_tenant()`** — đúng khuôn các bề mặt đọc. Agent set
  `app.tenant_id` (và `app.current_tenant`) bằng `SET LOCAL` **mỗi transaction**; điều này đã
  đúng sẵn trong code (`storage/postgres_client.py::tenant_conn`), không cần agent đổi gì.
  Nhờ vậy contract hoạt động **không phụ thuộc agent kết nối bằng role dùng chung
  `odyssey_agent` hay role per-tenant lấy từ runtime-credentials API**.
- **Không có cột tiền.** Không `price`, không `cost`, không `currency`. Agent ghi *số lượng* +
  *đơn vị*; bảng giá và phép nhân thuộc về Portal. Lý do: đơn giá đổi theo hợp đồng và theo
  thời điểm, còn số lượng đã tiêu thụ thì bất biến — trộn hai thứ vào một bảng làm hoá đơn
  quá khứ bị viết lại mỗi lần đổi bảng giá.
- **Không chứa PII.** Bảng này chỉ có `session_id`; không số điện thoại, không tên, không nội
  dung hội thoại. Cần chi tiết thì Portal tự join sang bản ghi hội thoại của mình.

---

## 1. Bảng `billing.usage_events`

**Tên đầy đủ agent sẽ ghi vào: `billing.usage_events`** (agent qualify schema tường minh, KHÔNG
dựa vào `search_path`). Nếu Portal muốn đặt tên khác (vd `control.agent_usage_events`), **báo
trước khi agent implement** — đây là hằng số biên dịch phía agent, không phải config.

DDL **tham khảo** (Portal được hiện thực khác, miễn giữ đúng tên cột / kiểu / ràng buộc):

```sql
CREATE SCHEMA IF NOT EXISTS billing;

CREATE TABLE IF NOT EXISTS billing.usage_events (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     text        NOT NULL,
    session_id    text        NOT NULL,
    channel       text        NOT NULL,                    -- 'voice' | 'chat'
    seq           integer     NOT NULL,                    -- thứ tự lần flush trong phiên, từ 0
    turn_idx      integer,                                 -- NULL = meter mức phiên
    component     text        NOT NULL,                    -- xem §2.1
    purpose       text        NOT NULL DEFAULT 'conversation',  -- xem §2.2
    provider      text        NOT NULL DEFAULT '',         -- 'anthropic' | 'openai' | ... (xem lưu ý dưới)
    model         text        NOT NULL DEFAULT '',

    input_tokens       bigint NOT NULL DEFAULT 0,
    output_tokens      bigint NOT NULL DEFAULT 0,
    cache_write_tokens bigint NOT NULL DEFAULT 0,
    cache_read_tokens  bigint NOT NULL DEFAULT 0,

    audio_sec     double precision NOT NULL DEFAULT 0,     -- đơn vị ĐI VÀO HOÁ ĐƠN
    wall_ms       double precision NOT NULL DEFAULT 0,     -- giá vốn nội bộ, KHÔNG tính cho khách
    units         bigint      NOT NULL DEFAULT 0,          -- SỐ LẦN GỌI/sự kiện gộp trong dòng, xem §2.1
    text_units    bigint      NOT NULL DEFAULT 0,          -- LƯỢNG TEXT theo ký tự (thêm 2026-08-20), xem §2.1

    exact         boolean     NOT NULL DEFAULT true,       -- false = provider không trả usage
    occurred_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT usage_events_idem
        UNIQUE (tenant_id, session_id, seq, component, purpose, provider, model)
);

CREATE INDEX IF NOT EXISTS usage_events_tenant_time
    ON billing.usage_events (tenant_id, occurred_at);
CREATE INDEX IF NOT EXISTS usage_events_session
    ON billing.usage_events (tenant_id, session_id);
```

Ba chi tiết trong DDL trên **không phải tuỳ chọn**, mong Portal giữ nguyên:

1. **`GENERATED ALWAYS AS IDENTITY`, không phải `bigserial`.** Với identity column, sequence
   thuộc sở hữu của cột và quyền dùng nó **được ngụ ý bởi `INSERT` trên bảng**. Dùng
   `bigserial` thì phải `GRANT USAGE ON SEQUENCE …` **riêng**, và nếu quên thì mọi INSERT của
   agent fail — mà vì đường ghi là best-effort ngoài luồng nóng, nó sẽ fail **im lặng** và chỉ
   lộ ra lúc cuối tháng không có số liệu. Identity xoá hẳn cái bẫy đó.
2. **`provider` / `model` là `NOT NULL DEFAULT ''`, không nullable.** Chúng nằm trong khoá
   UNIQUE, mà trong Postgres `NULL` không so sánh bằng `NULL` — để nullable thì ràng buộc
   idempotency âm thầm mất tác dụng đúng vào lúc cần nhất là khi retry.
3. **Ràng buộc `usage_events_idem`.** Xem §4 — thiếu nó thì retry sau lỗi mạng sẽ **nhân đôi
   hoá đơn**.

**Lưu ý về `provider` trên dòng audio (giới hạn đã biết của bản đầu):** chỉ dòng
`component='llm'` và `component='embed'` có `provider`/`model`. Các dòng `stt` / `tts` / `vad` /
`speaker_verify` / `call` hiện luôn có `provider=''` — meter mức audio khoá theo
`(component, purpose)` chứ không mang provider. Hệ quả cho Portal: **không suy ra được đơn giá
STT/TTS từ dòng dữ liệu**, phải lấy từ cấu hình deployment (`STT_BACKEND`/`TTS_BACKEND`, thay
đổi ở mức deployment chứ không mức cuộc gọi). Nếu Portal cần giá theo provider ngay trên dòng,
báo lại — phía agent thêm được nhưng phải sửa cả 5 điểm đo, không phải một chỗ.

---

## 2. Ngữ nghĩa từng cột

### 2.1 `component` — thành phần tiêu thụ, ý nghĩa của `units` và `text_units`

**Quy ước thống nhất (2026-08-20):** `units` = **số lần gọi/sự kiện** gộp trong dòng, MỌI
component; `text_units` = **lượng text theo ký tự** — cơ sở tính tiền của các vendor đếm
chữ (ElevenLabs theo ký tự vào TTS, Soniox thu thêm theo text transcript ra, provider
embed theo lượng text vào).

| `component` (+`purpose` nếu cần phân biệt) | `audio_sec` | `wall_ms` | `units` | `text_units` | Cột token |
|---|---|---|---|---|---|
| `llm` | 0 | tổng thời gian stream LLM | số lời gọi LLM | 0 | **có nghĩa** (4 cột) |
| `stt` + `conversation` | số **giây audio đã gửi** lên STT (cơ sở tính tiền) | 0 | 0 | **ký tự transcript final** (đo TRƯỚC mọi filter — vendor đã transcribe là đã tốn) | 0 |
| `stt` + `stream` | 0 | thời gian stream STT mở (≈ cả phiên) | số lần mở stream | 0 | 0 |
| `tts` | số **giây audio sinh ra** | thời gian tổng hợp | số clause đã synth | **ký tự đưa vào TTS** (cơ sở tính tiền) | 0 |
| `vad` | số **giây audio đã quét** (cơ sở tính tiền) | thời gian CPU xử lý | 0 | 0 | 0 |
| `speaker_verify` | số **giây audio đem đi embed** | thời gian embed | số lần embed | 0 | 0 |
| `embed` | 0 | thời gian gọi | số lời gọi | **ký tự text đem embed** (cơ sở tính tiền) | luôn 0 — xem dưới |
| `call` | **thời lượng cuộc gọi (giây)** | 0 | 1 | 0 | 0 |

**`stt` tách hai dòng theo `purpose` (đổi 2026-08-19).** Trước đó cả hai phép đo đi chung
`(stt, conversation)` và sinh **dòng lai**: giây-khách-nói của một lượt trộn với thời-gian-stream-mở
của cả cuộc gọi trong cùng một dòng, mang `turn_idx` của lượt nhưng `wall_ms` của cả phiên
(đã thấy trên bảng thật: `turn_idx=1, audio_sec=0, wall_ms=112748` trên cuộc gọi 112s). Nay:
`(stt, conversation)` per-turn chỉ mang `audio_sec` (+ `text_units` từ 2026-08-20);
`(stt, stream)` session-scoped (`turn_idx IS NULL`) mang `wall_ms` + `units`, ghi lúc đóng
phiên. Cùng đợt đó `vad.units` về 0 — số chunk 32ms không quy ra đơn giá nào.

**`text_units` thêm 2026-08-20 (ALTER đã chạy trên DB portal).** Trước đó ký tự TTS nằm
trong `units` và embed đếm "số đoạn text" — dòng ghi TRƯỚC mốc này mang layout cũ
(`text_units=0`, ký tự trong `units`); dữ liệu dev/test, Portal đối chiếu theo
`occurred_at` nếu còn giữ. Lý do thêm: Soniox tính tiền STT bằng HAI đồng hồ
(input-audio-token ∝ thời gian stream + output-text-token ∝ transcript ra) — thiếu vế
text là bill thiếu; và `units` trước đó mỗi component một nghĩa, không tự mô tả.

Bốn lưu ý quan trọng khi Portal dựng bảng giá:

- **Cơ sở tính tiền của `component='embed'` là `text_units` (ký tự), KHÔNG phải cột token.**
  Không provider embed nào trả token count (Gemini `batchEmbedContents` chỉ trả vector), nên bốn
  cột token của dòng embed luôn bằng 0; provider bill tỷ lệ theo lượng text vào nên đếm ký tự
  (câu 500 ký tự tốn hơn câu 10 ký tự — "số đoạn text" của layout cũ không phản ánh được).
  Kèm theo đó: **cờ `exact` chỉ nói về độ tin của cột token**, nên dòng embed luôn `exact=true`
  dù không đo được token — nếu Portal dựng cảnh báo "doanh thu đang rơi" trên tỷ lệ `exact=false`
  thì hãy giới hạn nó ở `component='llm'`, chỗ duy nhất token là cơ sở tính tiền.
  Một dòng embed có `wall_ms > 0` mà `text_units = 0` nghĩa là **lời gọi đã thất bại**: giá vốn
  (thời gian, kết nối) là thật và hiện ở `wall_ms`, nhưng khách không phải trả cho lỗi của agent.
  Cặp `(provider, model)` phân biệt từng nhánh — và chúng có **thang giá rất khác nhau**:

  | `provider` | `model` | Bản chất |
  |---|---|---|
  | `gemini` | `gemini-embedding-001` | API trả phí |
  | `service` | `dense` \| `sparse` \| `visual_text` | service nội bộ (SigLIP2 / BM25 / dense) |
  | `fastembed` | `Qdrant/bm25` | chạy local trên CPU agent — **không tốn phí provider** |
  | `hf` | `intfloat/multilingual-e5-large` | chạy local trên CPU agent |

  Đo thật 2026-08-19 trên cùng một truy vấn: nhánh `gemini` mất 472 ms, nhánh `fastembed` mất
  5,2 ms. Gộp chúng vào một dòng là mất khả năng tách giá — nên đừng rollup embed mà bỏ
  `provider`/`model` khỏi `GROUP BY`.

- **`audio_sec` là con số đi vào hoá đơn; `wall_ms` thì không.** `audio_sec` chỉ phụ thuộc nội
  dung cuộc gọi nên cùng một cuộc gọi luôn ra cùng con số — hoá đơn tái lập được và giải trình
  được với khách. `wall_ms` phụ thuộc tải máy chủ tại thời điểm đó; nó có mặt ở đây **chỉ để
  theo dõi giá vốn nội bộ**, đặc biệt với `vad` và `speaker_verify` là hai thứ chạy local nên
  chi phí thật là CPU chứ không phải giây audio. Tính tiền khách theo `wall_ms` nghĩa là khách
  trả nhiều hơn khi server đang bận — không nên.
- **`stt.audio_sec` ≠ `call.audio_sec`.** STT chỉ nhận audio khi cổng vào mở (đã lọc im lặng),
  nên tổng giây STT luôn nhỏ hơn thời lượng cuộc gọi. Nếu hợp đồng với nhà cung cấp STT tính
  theo **thời gian kết nối stream** chứ không theo audio thực gửi, hãy dùng `wall_ms` của dòng
  `(stt, purpose='stream')`.
- **`component='call'` xuất hiện đúng một dòng cho mỗi phiên voice**, ghi lúc đóng phiên, với
  `turn_idx IS NULL`. Phiên `chat` **không** có dòng này.

### 2.2 `purpose` — lời gọi phục vụ mục đích gì

Agent gọi LLM ở nhiều đường, không chỉ lượt hội thoại chính. Tất cả đều được đo và gắn nhãn;
**Portal quyết định nhãn nào tính tiền cho khách, nhãn nào chỉ để theo dõi giá vốn.**

| `purpose` | Khi nào phát sinh | Gợi ý |
|---|---|---|
| `conversation` | lượt hội thoại chính (kể cả các vòng gọi tool) | tính tiền |
| `summary` | nén lịch sử khi hội thoại dài + sinh tóm tắt cuộc gọi lúc kết thúc | **tăng theo độ dài hội thoại** — cân nhắc tính |
| `warm_cache` | hâm nóng prompt cache của provider sau khi summary | tốn input token thật |
| `suggestions` | sinh gợi ý câu hỏi tiếp theo cho giao diện chat | mỗi lượt chat |
| `memory` | trộn hồ sơ khách qua các phiên | mỗi phiên, 1 lần — **có thể VẮNG**: xem caveat dưới bảng |
| `addressee_gate` | phân loại "khách nói với agent hay nói với người bên cạnh" | tần suất cao ở voice |
| `semcache` | dự đoán lượt kế để cache trước (mặc định TẮT) | thường bằng 0 |
| `rag_build` | dựng đồ thị tri thức (offline, ngoài phiên) | **thực tế không bao giờ xuất hiện**: builder chạy ngoài phiên nên không có meter |
| `embed` | vector hoá câu hỏi khi tìm kiếm tri thức (`kb_search`, `send_media`) | luôn đi cùng `component='embed'`; tính theo `text_units` (ký tự), xem §2.1 |
| `stream` | đi kèm `component='stt'`, ghi lúc đóng phiên | thời gian stream STT mở + số lần mở — giá vốn cả phiên, `turn_idx IS NULL`, xem §2.1 |
| `session` | đi kèm `component='call'` | thời lượng cuộc gọi |

**Danh sách này là đóng.** Agent chỉ ghi đúng các giá trị trên; gặp giá trị lạ trong bảng
nghĩa là có phiên bản agent khác đang chạy.

**Trên đường voice, `purpose` chỉ phân biệt hai ngoại lệ.** Dòng audio thường (`stt` / `tts` /
`vad` / `speaker_verify`) mang `purpose='conversation'`; hai ngoại lệ là `(stt, 'stream')`
(giá vốn stream cả phiên) và `(call, 'session')` (thời lượng cuộc gọi). Nghĩa là
`WHERE purpose='conversation'` sẽ vơ **cả** token LLM **lẫn** toàn bộ số giây audio. Trên đường
voice hãy lọc bằng **`component`** (cộng `purpose` khi cần tách hai phép đo của `stt`), không
phải `purpose` đơn thuần.

**Caveat cho `memory`:** lời gọi trộn hồ sơ chạy **fire-and-forget lúc đóng phiên** (agent cố ý
không chờ nó để teardown không bị chậm), nên nó thường hoàn tất **sau** lần ghi cuối của phiên —
khi đó dòng `memory` **không xuất hiện**. Vì vậy đừng dùng "`memory` ≈ 1 dòng mỗi phiên" làm
health-check phiên bản agent; thiếu nhãn này là **bình thường**, không phải dấu hiệu sai phiên
bản. Nhãn `summary` cuối cuộc gọi thì luôn có (lời gọi đó được await trước lần ghi cuối).

### 2.3 Bốn cột token

Đặt tên theo mô hình tính giá của Anthropic vì đó là provider chính:

| Cột | Ý nghĩa |
|---|---|
| `input_tokens` | token đầu vào **không** được cache phục vụ |
| `output_tokens` | token sinh ra |
| `cache_write_tokens` | token **ghi vào** prompt cache (Anthropic tính **đắt hơn** input thường) |
| `cache_read_tokens` | token **đọc từ** prompt cache (tính **rẻ hơn** input thường nhiều) |

**Bốn cột này rời nhau — đừng cộng dồn.** Đơn giá của chúng khác nhau; cộng lại rồi nhân một
đơn giá duy nhất sẽ ra sai số lớn, vì hệ thống bật prompt caching nên phần lớn input mỗi lượt
rơi vào `cache_read_tokens`.

Provider không phải Anthropic không có đủ bốn khái niệm: các slot tương thích OpenAI thường chỉ
báo được `input`/`output` + phần cached đọc, và **không có khái niệm "ghi cache" tính phí**.
Khi đó `cache_write_tokens = 0` một cách hợp lệ, không phải thiếu dữ liệu.

### 2.4 `exact` — cờ trung thực của số liệu

`exact = false` nghĩa là **provider không trả usage cho lời gọi đó**, và agent **cố ý không
đoán** số token (agent thống kê, không bịa). Dòng vẫn được ghi để Portal biết lời gọi đó **đã
xảy ra**, với các cột token bằng 0.

Portal nên **theo dõi tỷ lệ `exact = false`**: bình thường nó phải xấp xỉ 0. Tỷ lệ này tăng
đột ngột là dấu hiệu một provider vừa đổi hành vi hoặc vừa bị chuyển sang nhánh dự phòng —
và nó có nghĩa là **doanh thu đang bị bỏ sót**, không phải là không có tiêu thụ.

### 2.5 `seq` và `turn_idx`

- `seq`: số thứ tự **lần flush** trong phiên, bắt đầu từ 0, tăng đơn điệu. Dùng cho idempotency
  (§4). Không phải số lượt.
- `turn_idx`: chỉ số lượt hội thoại trong phiên (từ 0). `NULL` cho các phép đo không thuộc lượt
  nào — `component='call'`, `component='vad'` (hai thứ chạy liên tục, kể cả lúc im lặng và
  lúc agent đang nói), và `(stt, purpose='stream')` (thời gian stream mở của cả phiên).
  Scoping khoá theo cặp `(component, purpose)`, không theo `component` đơn thuần.

**`turn_idx` là gợi ý quy-về-lượt, KHÔNG phải khoá join chính xác cho dòng audio.** Dòng `llm`
đóng dấu tại đúng thời điểm gọi nên chính xác. Dòng audio thì đóng dấu lúc **flush**, mà audio
là dòng chảy liên tục không thẳng hàng với mốc lượt — rõ nhất là TTS: agent bắt đầu **nói sau
khi lượt đã chốt**, nên phần audio trả lời lượt N thường được báo cáo trong kỳ của lượt N+1.

Hệ quả cụ thể: **lần flush cuối phiên** (lúc đóng) mang `turn_idx` = lượt cuối + 1 — một chỉ số
không ứng với lượt hội thoại nào. Ví dụ thật: phiên 2 lượt, dòng `tts` 17,18 s của câu trả lời
lượt 0 nằm ở dòng mang `turn_idx=1`.

Vì vậy: **tổng tiền theo phiên/tháng luôn đúng** (mọi dòng đều được cộng), nhưng nếu Portal join
dòng audio với một lượt hội thoại cụ thể thì hãy coi `turn_idx` là xấp xỉ. Muốn chính xác theo
lượt thì chỉ `component='llm'` bảo đảm được.

---

## 3. Câu lệnh agent chạy

Agent ghi **một batch nhiều dòng cho mỗi lần flush**, trong một transaction đã `SET LOCAL
app.tenant_id`:

```sql
INSERT INTO billing.usage_events
  (tenant_id, session_id, channel, seq, turn_idx, component, purpose, provider, model,
   input_tokens, output_tokens, cache_write_tokens, cache_read_tokens,
   audio_sec, wall_ms, units, text_units, exact, occurred_at)
VALUES ($1, $2, …, $19)
ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING;
```

`occurred_at` được agent gửi **tường minh** (không dựa vào `DEFAULT now()`): nó là thời điểm
**phát sinh** tiêu thụ, đóng dấu trong RAM lúc đo, chứ không phải lúc INSERT — đó là điều kiện
để lời hứa ở §8 ("dòng đến muộn, `occurred_at` vẫn đúng thời điểm phát sinh") đúng khi PG chết
vắt qua ranh giới kỳ hoá đơn. Cột vẫn giữ `DEFAULT now()` trong DDL để Portal không phải đổi gì.

Agent **không** dùng `RETURNING`, **không** đọc lại bảng. Nhưng lưu ý: vì câu lệnh **nêu tường
minh arbiter** (`ON CONSTRAINT usage_events_idem`), Postgres đòi quyền `SELECT` trên bảng —
`INSERT` một mình KHÔNG đủ. Chi tiết + số đo thật ở §5; `SELECT` đã bị RLS giới hạn theo tenant.

**Nhịp ghi:** một lần flush sau mỗi lượt hội thoại hoàn tất, cộng một lần cuối lúc đóng phiên.
Việc ghi chạy ngoài luồng xử lý (fire-and-forget) nên **không bao giờ chặn cuộc gọi**; hệ quả
là Portal **không được** trông đợi dòng xuất hiện đúng khoảnh khắc lượt kết thúc, mà chỉ trong
khoảng ngay sau đó.

---

## 4. Idempotency — điều kiện để không nhân đôi hoá đơn

Khi INSERT thất bại (mạng, credential hết hạn, PG bận), agent **giữ lại dữ liệu trong bộ nhớ và
thử lại ở lần flush sau với đúng `seq` cũ**. Nếu lần thất bại trước thực ra đã ghi được (lỗi xảy
ra lúc trả lời), lần thử lại sẽ trùng khoá và bị `DO NOTHING` bỏ qua.

**Cơ chế này phụ thuộc hoàn toàn vào ràng buộc `usage_events_idem` tồn tại.** Không có nó, mỗi
lần retry là một dòng mới và khách bị tính tiền hai lần cho cùng một lượt. Đây là điểm quan
trọng nhất trong toàn bộ tài liệu này.

---

## 5. GRANT checklist (Portal chạy 1 lần)

```sql
-- Nhóm quyền dùng chung của agent (đã tồn tại theo contract ĐỌC)
GRANT USAGE  ON SCHEMA billing          TO agent_all;
GRANT INSERT ON billing.usage_events    TO agent_all;
GRANT SELECT ON billing.usage_events    TO agent_all;   -- BẮT BUỘC, xem ngay dưới

-- KHÔNG cấp: UPDATE / DELETE / TRUNCATE cho agent_all.
-- KHÔNG cần GRANT trên sequence — identity column đã ngụ ý qua INSERT (xem §1).
```

**Vì sao `SELECT` là bắt buộc, không phải nới quyền cho tiện.** Postgres đòi quyền `SELECT` trên
bảng khi câu `INSERT` **nêu tường minh arbiter** của `ON CONFLICT` — mà đó chính là câu agent
chạy (§3, §4). Đã đo trực tiếp bằng role `portal_api`, mỗi lệnh trong transaction rồi `ROLLBACK`:

| Câu lệnh | Với `INSERT` only |
|---|---|
| `INSERT … VALUES …` | `INSERT 0 1` ✅ |
| `INSERT … ON CONFLICT DO NOTHING` (không nêu arbiter) | `INSERT 0 1` ✅ |
| `INSERT … ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING` | ❌ `42501 permission denied` |
| `INSERT … ON CONFLICT (tenant_id, session_id, seq, …) DO NOTHING` | ❌ `42501 permission denied` |

Nếu thiếu `SELECT`, **100% dòng billing bị mất và mất im lặng** — đường ghi là fire-and-forget
ngoài luồng nóng nên lỗi chỉ hiện ở log, còn triệu chứng là cuối tháng không có số liệu.

Đã cân nhắc phương án thay thế là **bỏ `ON CONSTRAINT`** để khỏi cần `SELECT`. Bác bỏ: dạng
`ON CONFLICT DO NOTHING` trần bỏ qua xung đột trên **mọi** ràng buộc unique, nên nếu
`usage_events_idem` bị đổi tên hoặc xoá thì retry **âm thầm nhân đôi hoá đơn** — đúng cái §4
tồn tại để chặn. Nêu tên constraint làm câu lệnh **nổ ngay** nếu tấm lưới idempotency biến mất.
Đổi mất tính chất đó để tiết kiệm một quyền `SELECT` đã bị RLS giới hạn theo tenant là lỗ.

**Chỉ cần cấp cho `agent_all` — không cần liệt kê từng role.** Đã kiểm chứng trực tiếp trên DB
`portal` (10.50.13.208:5442) ngày 2026-08-18: mọi role mà agent có thể kết nối bằng đều **đã là
member của `agent_all`** — 8 role LOGIN per-tenant (`agent_anphu`, `agent_eco_green`,
`agent_du_test`, …), `portal_api` (role trong `POSTGRES_DSN` hiện tại, tức đường fallback khi
không có credential per-tenant), và `odyssey_agent`. Một lệnh `GRANT … TO agent_all` phủ cả
đường per-tenant lẫn đường fallback, và tự phủ mọi tenant tạo về sau.

Hai điều chỉnh so với bản trước của tài liệu này, phát hiện khi kiểm DB thật:

- **`odyssey_agent` là `NOLOGIN`** trên DB này, nên agent không bao giờ kết nối trực tiếp bằng
  nó. Đường fallback thật là `portal_api`. Cấp cho `agent_all` là đủ cho cả hai.
- Khuôn này khớp đúng cách `tenant_data.conversations` đang cấp: `agent_all` có
  `INSERT/SELECT/UPDATE`, **không** có `DELETE`. Bảng billing chỉ cần `INSERT`.

**Role tenant tuyệt đối không được có `UPDATE`/`DELETE` trên bảng này** — đó chính là thứ khiến
tenant không thể xoá hoá đơn của chính mình.

---

## 6. RLS

```sql
ALTER TABLE billing.usage_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY agent_insert ON billing.usage_events
    FOR INSERT TO agent_all
    WITH CHECK (tenant_id = portal.current_tenant());

CREATE POLICY agent_read ON billing.usage_events
    FOR SELECT TO agent_all
    USING (tenant_id = portal.current_tenant());
```

- **`WITH CHECK` khiến DB cưỡng chế gán đúng tenant lúc ghi** — một bug phía agent không thể
  ghi tiêu thụ của tenant A vào sổ của tenant B.
- **`ENABLE` nhưng KHÔNG `FORCE`** — cố ý. Nhờ đó chủ bảng (role báo cáo của Portal) đọc xuyên
  tenant để tổng hợp doanh thu, trong khi agent vẫn bị policy chặn trong phạm vi tenant của
  transaction hiện tại.
- **Policy `agent_read` là load-bearing, không phải phòng ngừa** (đổi so với bản đầu của tài liệu
  này). Vì `SELECT` buộc phải cấp cho `agent_all` (§5), chính policy này là thứ giữ cho quyền đó
  không phơi sổ cái của tenant khác. Thiếu nó — hoặc xoá nó vì tưởng là dư — thì mọi role agent
  đọc được toàn bộ billing của mọi tenant. Đã đo: với GUC `app.tenant_id='eco_green'`, một
  `SELECT … WHERE tenant_id='noble'` trả **0 dòng**.
- **`UPDATE`/`DELETE` bị chặn ở tầng GRANT, không phải tầng policy.** Đã đo: sau khi cấp `SELECT`,
  `UPDATE`/`DELETE`/`TRUNCATE` vẫn `42501 permission denied`. Tính bất biến của dòng đã ghi
  không bị `SELECT` làm suy yếu.

---

## 7. VIEW tổng hợp (Portal tự do quyết định)

Agent không dùng, nhưng nên có một định nghĩa **duy nhất** cho "một phiên tốn bao nhiêu" để
Portal và mọi báo cáo không lệch nhau:

```sql
CREATE OR REPLACE VIEW billing.usage_by_session AS
SELECT tenant_id, session_id, channel,
       min(occurred_at) AS started_at,
       max(occurred_at) AS last_event_at,
       sum(input_tokens)       AS input_tokens,
       sum(output_tokens)      AS output_tokens,
       sum(cache_write_tokens) AS cache_write_tokens,
       sum(cache_read_tokens)  AS cache_read_tokens,
       sum(audio_sec) FILTER (WHERE component = 'stt')            AS stt_sec,
       sum(audio_sec) FILTER (WHERE component = 'tts')            AS tts_sec,
       sum(audio_sec) FILTER (WHERE component = 'vad')            AS vad_sec,
       sum(audio_sec) FILTER (WHERE component = 'speaker_verify') AS speaker_sec,
       sum(audio_sec) FILTER (WHERE component = 'call')           AS call_sec,
       bool_and(exact)                                            AS exact
FROM billing.usage_events
GROUP BY tenant_id, session_id, channel;
```

Tương tự cho `billing.usage_by_tenant_month` gộp theo
`(tenant_id, date_trunc('month', occurred_at))`.

**Hai VIEW hiện KHÔNG expose `text_units`** (tạo trước 2026-08-20). Muốn tính tiền `tts`/`embed`
(theo ký tự) hoặc vế text-ra của `stt` thì query bảng gốc, hoặc Portal tự ALTER VIEW thêm
`sum(text_units) FILTER (WHERE …)` — VIEW thuộc Portal, agent không phụ thuộc.

---

## 8. Bất biến & hành vi lỗi

| Tình huống | Agent làm gì | Hệ quả cho Portal |
|---|---|---|
| Chưa cấp `INSERT` | log `error` (kèm `current_user` + SQLSTATE), giữ dữ liệu trong RAM, thử lại lượt sau | **Không có dòng nào** cho tới khi grant xong. Dữ liệu trước đó đã mất theo phiên. |
| Credential hết hạn giữa phiên | như trên; tự khỏi khi credential được làm mới | Có thể thấy khoảng trống rồi liền lại |
| PG không tới được | như trên | Dòng đến muộn, `occurred_at` vẫn đúng thời điểm phát sinh |
| Process agent chết giữa phiên | mất phần tiêu thụ kể từ lượt hoàn tất gần nhất | **Thiếu vĩnh viễn.** Đánh đổi có chủ đích: đường nóng không được có I/O |
| Provider không trả usage | ghi dòng với `exact = false`, token = 0 | Theo dõi tỷ lệ này (§2.4) |
| Cùng một `(session, seq)` ghi hai lần | `ON CONFLICT DO NOTHING` | Không nhân đôi — **nếu** ràng buộc §4 tồn tại |

**Bất biến agent bảo đảm:** một dòng đã INSERT **không bao giờ** được agent sửa hay xoá. Mọi
điều chỉnh (huỷ, hoàn tiền, miễn phí) là nghiệp vụ của Portal và nên nằm ở bảng khác — sửa trực
tiếp bảng này sẽ phá tính đối chiếu được của sổ cái.

---

## 9. Ước lượng khối lượng (để Portal tính lưu trữ)

| Loại phiên | Dòng / lượt | Ví dụ |
|---|---|---|
| `voice` | ≈ 4–6 (llm, stt, tts, vad, ± speaker_verify, ± embed) | cuộc gọi 5 phút ~20 lượt → **~100–130 dòng** + 2 dòng phiên (`call` + `(stt,'stream')`) |
| `chat` | ≈ 1–2 (llm, ± embed) | phiên chat 20 lượt → **~25 dòng** |

Agent **không xoá** dòng nào. Chính sách lưu trữ / partition theo tháng do Portal quyết; gợi ý
giữ ít nhất trọn chu kỳ đối soát + thời hạn khiếu nại hoá đơn.

---

## 10. Điều Portal KHÔNG cần làm

- Không gọi API nào của agent — agent tự ghi, không có chiều ngược lại.
- Không cấp quyền DDL hay admin cho role của agent trên DB này.
- Không cần đẩy bảng giá xuống agent — agent không biết và không cần biết giá.
- Không cần chặn/hạn mức phía agent: **contract này không bao gồm cưỡng chế quota.** Agent
  không đọc bảng này nên không tự dừng khi tenant hết hạn mức. Nếu cần chặn, cơ chế phải nằm ở
  gateway/Portal và là một hạng mục riêng.

---

## 11. Checklist bàn giao (Portal tick)

Phần hạ tầng đã chạy và đã đo trên DB thật ngày 2026-08-18 (§14) — Portal chỉ cần **soát lại**,
không cần chạy lại:

- [x] `billing.usage_events` tồn tại, đúng tên cột / kiểu như §1.
- [x] Cột `text_units` (ALTER 2026-08-20, `bigint NOT NULL DEFAULT 0`) — §1, §2.1.
- [x] `event_id` dùng `GENERATED ALWAYS AS IDENTITY` (không phải `bigserial`) — §1.
- [x] `provider` / `model` là `NOT NULL DEFAULT ''` — §1.
- [x] Ràng buộc `usage_events_idem` tồn tại đúng 7 cột — §4. **Quan trọng nhất.**
- [x] `GRANT USAGE ON SCHEMA billing` + `GRANT INSERT` + `GRANT SELECT` cho `agent_all` — §5.
- [x] Xác nhận **không** cấp `UPDATE`/`DELETE`/`TRUNCATE` cho bất kỳ role agent nào — §5, §6.
- [x] RLS `ENABLE` (không `FORCE`) + 2 policy keyed on `portal.current_tenant()` — §6.
- [x] Xác nhận `portal.current_tenant()` đọc được GUC `app.tenant_id`.

Còn lại thuộc quyết định của Portal:

- [ ] Xác nhận giữ tên `billing.usage_events` (đã tạo theo tên này) hay muốn đổi — §1, §12 q1.
- [ ] Quyết định chính sách lưu trữ / partition — §9.
- [ ] Xác nhận role nào của Portal đọc báo cáo xuyên tenant (chủ bảng hoặc role có `BYPASSRLS`).
- [ ] Xác nhận có cần `provider` trên dòng audio hay không — §1 lưu ý cuối.

---

## 12. Điểm cần Portal phản hồi trước khi agent implement

1. **Tên schema/bảng**: chấp nhận `billing.usage_events`, hay đổi sang `control.agent_usage_events`?
2. **Role**: ~~xác nhận cấp cho cả hai~~ — **đã tự trả lời bằng cách kiểm DB thật**: chỉ cần
   `GRANT … TO agent_all`, vì mọi role agent (8 role per-tenant + `portal_api` + `odyssey_agent`)
   đều đã là member. Xem §5. Không cần Portal quyết gì thêm ở mục này.
3. **`vad` và `speaker_verify` có tính tiền khách không?** ~~Portal quyết~~ — **đã chốt
   2026-08-19: CÓ tính**, mỗi component một đơn giá riêng trên `audio_sec` của nó (xem
   `portal-billing-pricing-guide.md` §1.3; tuyệt đối không SUM `audio_sec` chéo component).
4. **`purpose` nào tính tiền khách** (§2.2) — đặc biệt `summary` và `addressee_gate`, hai đường
   nền hiện chưa ai đếm và tăng theo độ dài / mức độ ồn của cuộc gọi.

---

## 13. Ai chạy được DDL — đã kiểm, KHÔNG phải phía agent

Đo trực tiếp trên `postgresql://portal_api@10.50.13.208:5442/portal` ngày 2026-08-18. Role
`portal_api` (role trong `POSTGRES_DSN` của agent) **không tạo được bảng ở đâu cả**. Thử thật,
mỗi lệnh trong một transaction rồi `ROLLBACK` nên không để lại gì:

| Lệnh | Kết quả |
|---|---|
| `CREATE SCHEMA billing` | `42501 permission denied for database portal` |
| `CREATE TABLE control.<x>` | `42501 permission denied for schema control` |
| `CREATE TABLE tenant_data.<x>` | `42501 permission denied for schema tenant_data` |
| `CREATE TABLE public.<x>` | `42501 permission denied for schema public` |

Nguyên nhân: `portal_api` không superuser, không `CREATEROLE`/`CREATEDB`, `CREATE` trên database
= false, và `CREATE` trên cả 4 schema (`control`/`portal`/`public`/`tenant_data`) = false — cả 4
schema thuộc **`portal_migrator`**.

⇒ **Toàn bộ §1 + §6 + §5 phải do `portal_migrator` (hoặc superuser) chạy.** Nếu Portal muốn phía
agent tự tạo, cần một trong hai:

```sql
-- cách A: cho phép agent tạo schema riêng của mình
GRANT CREATE ON DATABASE portal TO portal_api;

-- cách B (hẹp hơn, khuyến nghị): Portal tạo sẵn schema rỗng rồi mở quyền trong đó
CREATE SCHEMA billing;
GRANT CREATE, USAGE ON SCHEMA billing TO portal_api;
```

Lưu ý một cái bẫy đã tránh được: DDL tham khảo dùng cho DB **test** có
`CREATE OR REPLACE FUNCTION portal.current_tenant()`. Trên DB thật hàm này **đã tồn tại và thuộc
`portal_migrator`** — chạy nguyên bản DDL test lên DB thật sẽ ghi đè hàm control-plane của Portal.
Bản DDL ở §1 không chứa dòng đó; đừng thêm vào.

---

## 14. Trạng thái: DDL ĐÃ ÁP DỤNG trên DB `portal` (2026-08-18)

Team Portal đã cấp DSN của `portal_migrator` cho phía agent chạy DDL. Toàn bộ §1 + §5 + §6 + §7
đã áp dụng lên `postgresql://…@10.50.13.208:5442/portal` (PostgreSQL 18.4), trong **một
transaction**, bằng `portal_migrator`. Vì vậy §13 dưới đây chỉ còn giá trị lịch sử.

**Đã tạo:** schema `billing`; bảng `billing.usage_events` (19 cột lúc tạo, chủ sở hữu
`portal_migrator`); 2 index `usage_events_tenant_time` / `usage_events_session`; ràng buộc
`usage_events_idem`; RLS `ENABLE` (`relforcerowsecurity=false`) + 2 policy `agent_insert` /
`agent_read`; GRANT `USAGE`/`INSERT`/`SELECT` cho `agent_all`; 2 VIEW `billing.usage_by_session`
và `billing.usage_by_tenant_month`.

**2026-08-20:** `ALTER TABLE … ADD COLUMN text_units bigint NOT NULL DEFAULT 0` (cũng bằng
`portal_migrator`) → bảng 20 cột. Không đổi khoá idem, không đổi VIEW. Smoke lại bằng chính
`billing/sink.py` (phiên voice giả lập 3 lô, 11 dòng): layout mới đúng — `(stt, conversation)`
mang `audio_sec` + `text_units` transcript, `tts` `units`=2 clause / `text_units`=115 ký tự,
`embed` `units`=1 / `text_units`=38, `(stt,'stream')`/`call` `turn_idx IS NULL`; retry không
nhân dòng; **dữ liệu smoke đã xoá** (`DELETE 11`).

**KHÔNG chạm vào `portal.current_tenant()`** — hàm của Portal, giữ nguyên (xem bẫy ở §13).

### Kết quả kiểm nghiệm hành vi (role `portal_api`, mọi lệnh ghi đều `ROLLBACK`)

| Kiểm | Kỳ vọng | Kết quả |
|---|---|---|
| `INSERT` với GUC `app.tenant_id` khớp `tenant_id` | OK | `INSERT 0 1` ✅ |
| `INSERT` với `tenant_id` khác GUC | bị chặn | `new row violates row-level security policy` ✅ |
| `INSERT` **không** set GUC | bị chặn (fail-closed) | `new row violates row-level security policy` ✅ |
| `UPDATE` / `DELETE` / `TRUNCATE` | bị chặn | `42501 permission denied` ✅ |
| Retry đúng 7 cột khoá | không sinh dòng mới | `INSERT 0 0` ✅ |
| Cùng `seq`, khác `model` | dòng riêng | `INSERT 0 1` ✅ |
| `SELECT` khi GUC = tenant khác | 0 dòng | 0 dòng ✅ |

### End-to-end bằng chính `src/noble_agent/billing/sink.py`

Chạy `UsageMeter` thật + `billing_sink.flush()` thật, 2 lượt + 1 retry, tenant `noble`:
10 dòng đúng như thiết kế — `llm` tách theo `purpose` (`conversation`/`summary`) và theo
`provider`/`model`; `stt`/`tts`/`speaker_verify` mang `turn_idx`; `vad`/`call` có
`turn_idx IS NULL`; `flush` lặp lại lô cũ không sinh dòng nào. VIEW `usage_by_session` gộp đúng.
(Kiểm trước đợt tách `(stt, 'stream')` 2026-08-19 — nay dòng stream cũng `turn_idx IS NULL`.)
**Dữ liệu smoke đã xoá sau khi kiểm** (`DELETE 10`, bảng trở về 0 dòng).

### Đối chiếu tên role ↔ tenant

`portal.current_tenant()` ưu tiên `substring(session_user from '^agent_(.+)$')` **trước** GUC.
Đã kiểm: **mọi** tenant trong `control.tenants` đều có role `agent_<id>` khớp chính xác `id`, nên
đường per-tenant trả đúng tenant. (Có 6 role `agent_*` mồ côi của tenant đã xoá — vô hại.)
Điểm cần Portal giữ khi provisioning tenant mới: **tên role phải là `agent_<tenant_id>` chính
xác**; lệch một ký tự thì `WITH CHECK` chặn sạch billing của tenant đó, im lặng.
