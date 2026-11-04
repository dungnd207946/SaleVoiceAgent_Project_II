# Hướng dẫn tính phí sử dụng từ `billing.usage_events` — bàn giao team Portal

> **Phân công:** agent chỉ ghi **số lượng thô** (token, giây, ký tự, lần) vào
> `billing.usage_events`. **Đơn giá là biến do Portal quản và nhập** — bảng này không có
> cột tiền, đổi giá theo hợp đồng không viết lại dữ liệu quá khứ. File này định nghĩa:
> cột nào là cơ sở tính tiền của component nào, biến giá nào Portal cần nhập, công thức
> ráp chúng lại cho cả hai path **voice** và **chat**, và các bẫy cộng-đôi phải tránh.
>
> Ngữ nghĩa ghi (DDL, RLS, idempotency, khi nào dòng được ghi):
> [`agent-postgres-billing-write-contract.md`](agent-postgres-billing-write-contract.md).
> File đó là contract GHI; file này là hướng dẫn TÍNH.
>
> Cập nhật theo layout **2026-08-20**: thêm cột `text_units` (lượng text theo ký tự — cơ sở
> tính tiền của `tts`/`embed` + vế text-ra của `stt`); `units` từ nay THỐNG NHẤT = số lần
> gọi/sự kiện cho mọi component. (Trước đó: 2026-08-19 tách `(stt, stream)`, VAD `units=0`.)
> Dòng ghi trước 2026-08-20 mang layout cũ (ký tự nằm trong `units`, `text_units=0`).

---

## 1. Bảng biến giá Portal nhập

Mỗi biến dưới đây là một tham số Portal tự đặt (theo hợp đồng vendor + biên lợi nhuận).
Tên biến chỉ là gợi ý — quan trọng là **đơn vị** của từng biến phải đúng như cột ghi chú.

### 1.1 LLM — giá theo từng cặp `(provider, model)`

| Biến | Đơn vị | Nhân với cột |
|---|---|---|
| `P_LLM_INPUT` | đ / 1M token | `input_tokens` |
| `P_LLM_OUTPUT` | đ / 1M token | `output_tokens` |
| `P_LLM_CACHE_WRITE` | đ / 1M token | `cache_write_tokens` |
| `P_LLM_CACHE_READ` | đ / 1M token | `cache_read_tokens` |

Bốn cột token **rời nhau hoàn toàn** (không cột nào là tổng của cột khác) — nhân từng cột
với giá riêng rồi cộng, không sợ trùng. Provider không có cache (vd Gemini OpenAI-compat
hiện tại) thì hai cột cache luôn 0, đặt giá bao nhiêu cũng không phát sinh tiền.

### 1.2 Embed — giá theo `(provider, model)`

| Biến | Đơn vị | Nhân với cột |
|---|---|---|
| `P_EMBED_PER_CHAR` | đ / ký tự | `text_units` |

Cơ sở tính tiền là `text_units` (ký tự text đem embed), **không phải** cột token (luôn 0 —
không provider embed nào trả token count); `units` = số lời gọi. Nhánh chạy local trên CPU
agent đặt giá 0 nhưng **vẫn phải có dòng giá** để rollup không rơi NULL:

| `provider` | `model` | Gợi ý giá |
|---|---|---|
| `gemini` | `gemini-embedding-001` | theo hợp đồng Google |
| `service` | `dense` \| `sparse` \| `visual_text` | giá vốn service nội bộ |
| `fastembed` | `Qdrant/bm25` | **0** (local) |
| `hf` | `intfloat/multilingual-e5-large` | **0** (local) |

Dòng embed có `wall_ms > 0` mà `text_units = 0` là **lời gọi thất bại** — tự động ra 0 đ,
khách không trả cho lỗi của agent. Không cần xử lý riêng.

### 1.3 Audio (chỉ path voice) — giá phẳng theo component

Dòng audio luôn có `provider = ''` — **không suy được vendor từ dòng dữ liệu**, đơn giá
lấy theo cấu hình deployment (`STT_BACKEND` / `TTS_BACKEND`, đổi ở mức deployment chứ
không mức cuộc gọi).

| Biến | Đơn vị | Nhân với | Ghi chú |
|---|---|---|---|
| `P_STT_PER_SEC` | đ / giây | `audio_sec` của `(stt, 'conversation')` | giây audio **khách thực nói** (đã lọc im lặng) |
| `P_STT_PER_STREAM_MIN` | đ / phút | `wall_ms / 60000` của `(stt, 'stream')` | thời gian stream STT **mở** (≈ thời lượng cuộc gọi) |
| `P_STT_PER_CHAR_OUT` | đ / ký tự | `text_units` của `(stt, 'conversation')` | vế **text transcript ra** — CỘNG THÊM khi vendor thu cả hai đồng hồ (Soniox: input-audio-token theo stream + output-text-token theo transcript); vendor không thu theo text thì để 0 |
| `P_TTS_PER_CHAR` | đ / ký tự | `text_units` của `tts` | cơ sở tính tiền TTS đã chốt là **ký tự**; `audio_sec` (giây audio sinh ra) vẫn có sẵn nếu sau này muốn đổi cơ sở; `units` = số clause synth |
| `P_VAD_PER_SEC` | đ / giây | `audio_sec` của `vad` | giây audio đã quét (≈ toàn bộ audio vào, kể cả im lặng) |
| `P_SV_PER_SEC` | đ / giây | `audio_sec` của `speaker_verify` | giây audio đem đi embed giọng; muốn tính theo **lần** thì dùng `units` (số lần verify) |
| `P_CALL_PER_MIN` | đ / phút | `audio_sec / 60` của `call` | thời lượng cuộc gọi — phí nền tảng/phút, mỗi phiên voice đúng 1 dòng |

**QUY TẮC BẮT BUỘC cho STT: hai biến THỜI LƯỢNG chọn ĐÚNG MỘT, biến kia đặt 0.**
`P_STT_PER_SEC` và `P_STT_PER_STREAM_MIN` là **hai cách đo cùng một quãng dịch vụ**
(theo audio thật gửi vs theo thời gian kết nối — tuỳ hợp đồng vendor thu kiểu nào).
Đặt giá cả hai là **tính tiền STT hai lần**. Riêng `P_STT_PER_CHAR_OUT` là vế ĐỘC LẬP
(đồng hồ text-ra), được phép cộng thêm cùng MỘT trong hai biến thời lượng — đúng mô hình
Soniox thu song song hai đồng hồ.

### 1.4 Cờ bật/tắt theo `purpose` — Portal quyết nhãn nào tính khách

Mỗi dòng LLM mang nhãn `purpose` (danh sách **đóng**, xem contract §2.2). Portal giữ một
cờ `billable` cho từng nhãn:

| `purpose` | Phát sinh khi | Khuyến nghị |
|---|---|---|
| `conversation` | lượt hội thoại chính (kể cả vòng tool) | **tính** — chiếm gần hết tiêu thụ |
| `summary` | nén lịch sử + tóm tắt cuối phiên | **tính** — tăng theo độ dài hội thoại |
| `suggestions` | gợi ý câu hỏi tiếp theo (chỉ chat) | tuỳ gói sản phẩm |
| `memory` | trộn hồ sơ khách cuối phiên | tuỳ — dòng này **có thể vắng** (fire-and-forget, xem contract §2.2), đừng dựng invariant trên nó |
| `warm_cache` | hâm nóng prompt cache sau summary | khuyến nghị **giá vốn** (tối ưu nội bộ, khách không yêu cầu) |
| `addressee_gate` | phân loại "nói với agent hay nói leo" (voice, tần suất cao) | khuyến nghị **giá vốn** hoặc gộp vào đơn giá phút |
| `semcache` | dự đoán lượt kế (mặc định TẮT) | giá vốn; thường bằng 0 |
| `embed` | đi cùng `component='embed'` | tính theo §1.2 |
| `stream` | đi cùng `component='stt'` | theo quy tắc chọn-một §1.3 |
| `session` | đi cùng `component='call'` | tính theo `P_CALL_PER_MIN` |

---

## 2. Cột nào tính tiền, cột nào KHÔNG

| Cột | Vai trò |
|---|---|
| 4 cột token | cơ sở tính tiền của `llm` |
| `audio_sec` | cơ sở tính tiền của `stt`(conversation)/`vad`/`speaker_verify`/`call` — **mỗi component một đơn giá riêng, KHÔNG BAO GIỜ SUM chéo component** (xem §5.1) |
| `units` | **số lần gọi/sự kiện** gộp trong dòng — thống nhất mọi component (lời gọi LLM, clause synth, lần mở stream, lần verify, lời gọi embed); chỉ dùng làm giá-theo-lần nếu muốn |
| `text_units` | **lượng text theo ký tự** — cơ sở tính tiền của `tts` (ký tự vào) và `embed` (ký tự embed), + vế text-ra của `(stt,'conversation')` khi vendor thu theo transcript (Soniox) |
| `wall_ms` | **giá vốn nội bộ, KHÔNG tính khách** — ngoại lệ duy nhất: `(stt,'stream')` khi hợp đồng STT theo connect-time (§1.3) |
| `exact` | `false` = cột token đo **thiếu một phần** (provider cắt stream giữa chừng) — chỉ có ở `llm`. Hoá đơn cứ tính trên số đã ghi (không bao giờ đếm THỪA); tỷ lệ `exact=false` cao là tín hiệu doanh thu đang rơi, dựng cảnh báo trên nó |
| `occurred_at` | mốc **quy kỳ hoá đơn** (dòng đến muộn vẫn mang giờ phát sinh) — không phải trình tự sự kiện trong lượt |
| `turn_idx` | gợi ý quy-về-lượt, **xấp xỉ với dòng audio** (TTS lệch một lô — contract §2.5). Đừng lập hoá đơn theo lượt; hoá đơn theo phiên/tháng luôn đúng |
| `channel` | `voice` \| `chat` — tách hai path trên hoá đơn |

## 3. Hai path khác nhau thế nào

| | `channel='chat'` | `channel='voice'` |
|---|---|---|
| Component xuất hiện | `llm`, `embed` | `llm`, `embed`, `stt`×2 purpose, `tts`, `vad`, `speaker_verify`, `call` |
| Công thức | chỉ token + embed | token + embed + toàn bộ §1.3 |
| Dòng `call` | **không có** | đúng 1 dòng / phiên |

Công thức tổng một phiên (hay một tháng — cùng công thức, khác `WHERE`):

```
TIỀN = Σ llm    : (in×P_IN + out×P_OUT + cw×P_CW + cr×P_CR) / 1.000.000   [theo (provider,model), lọc purpose billable]
     + Σ embed  : text_units × P_EMBED_PER_CHAR                            [theo (provider,model)]
     + (voice)  : stt_conv.audio_sec × P_STT_PER_SEC
                  HOẶC stt_stream.wall_ms/60000 × P_STT_PER_STREAM_MIN     [chọn MỘT]
     + (voice)  : stt_conv.text_units × P_STT_PER_CHAR_OUT                 [vế text-ra, cộng thêm nếu vendor thu]
     + (voice)  : tts.text_units × P_TTS_PER_CHAR
     + (voice)  : vad.audio_sec × P_VAD_PER_SEC
     + (voice)  : sv.audio_sec × P_SV_PER_SEC
     + (voice)  : call.audio_sec / 60 × P_CALL_PER_MIN
```

---

## 4. SQL mẫu — copy-paste chạy được, thay số trong các CTE giá

Giá trong `VALUES` dưới đây là **VÍ DỤ chữ số tròn để minh hoạ công thức** — Portal thay
bằng bảng giá thật (khuyến nghị vật chất hoá thành bảng `billing.price_*` do Portal sở
hữu, thêm cột `effective_from` nếu cần giá theo thời kỳ).

```sql
WITH gia_llm(provider, model, in_1m, out_1m, cw_1m, cr_1m) AS (VALUES
    ('gemini',    'gemini-2.5-flash', 2500::numeric, 10000::numeric, 0::numeric, 625::numeric),
    ('anthropic', 'claude-sonnet-5',  75000,          375000,         93750,      7500)
),
gia_embed(provider, model, per_char) AS (VALUES
    ('gemini',    'gemini-embedding-001',            0.1::numeric),
    ('service',   'dense',                           0.05),
    ('service',   'sparse',                          0.02),
    ('service',   'visual_text',                     0.05),
    ('fastembed', 'Qdrant/bm25',                     0),
    ('hf',        'intfloat/multilingual-e5-large',  0)
),
gia_audio AS (SELECT
    10::numeric   AS stt_per_sec,          -- CHỌN MỘT trong hai biến THỜI LƯỢNG STT:
    0::numeric    AS stt_per_stream_min,   --   biến không dùng PHẢI = 0
    0.5::numeric  AS stt_per_char_out,     -- vế text-ra (độc lập, cộng thêm nếu vendor thu)
    2::numeric    AS tts_per_char,
    1::numeric    AS vad_per_sec,
    5::numeric    AS sv_per_sec,
    500::numeric  AS call_per_min
),
nhan_tinh(purpose) AS (VALUES        -- nhãn purpose TÍNH KHÁCH (Portal thêm/bớt)
    ('conversation'), ('summary'), ('suggestions'), ('embed'), ('stream'), ('session')
)
SELECT u.tenant_id,
       u.channel,
       date_trunc('month', u.occurred_at) AS ky,
       round(sum(CASE u.component
           WHEN 'llm' THEN (u.input_tokens       * l.in_1m
                          + u.output_tokens      * l.out_1m
                          + u.cache_write_tokens * l.cw_1m
                          + u.cache_read_tokens  * l.cr_1m) / 1e6
           WHEN 'embed'          THEN u.text_units * e.per_char
           WHEN 'stt'  THEN CASE u.purpose
                                WHEN 'conversation' THEN u.audio_sec * a.stt_per_sec
                                                       + u.text_units * a.stt_per_char_out
                                WHEN 'stream'       THEN u.wall_ms / 60000.0 * a.stt_per_stream_min
                            END
           WHEN 'tts'            THEN u.text_units * a.tts_per_char
           WHEN 'vad'            THEN u.audio_sec * a.vad_per_sec
           WHEN 'speaker_verify' THEN u.audio_sec * a.sv_per_sec
           WHEN 'call'           THEN u.audio_sec / 60.0 * a.call_per_min
       END)::numeric, 0) AS tien,
       bool_and(u.exact) AS exact
FROM billing.usage_events u
CROSS JOIN gia_audio a
LEFT JOIN gia_llm   l ON u.component = 'llm'   AND l.provider = u.provider AND l.model = u.model
LEFT JOIN gia_embed e ON u.component = 'embed' AND e.provider = u.provider AND e.model = u.model
WHERE u.purpose IN (SELECT purpose FROM nhan_tinh)
  AND u.occurred_at >= date_trunc('month', now())          -- kỳ cần tính
GROUP BY 1, 2, 3
ORDER BY 1, 2;
```

Tính **theo phiên** (dòng chi tiết trên hoá đơn): cùng query, thay `GROUP BY` bằng
`u.tenant_id, u.session_id, u.channel` và `WHERE` theo `session_id`.

**Lưới an toàn bắt buộc — dòng LLM/embed không có giá:** chạy định kỳ query dưới; ra dòng
nào nghĩa là bảng giá thiếu một `(provider, model)` đang phát sinh tiêu thụ (agent thêm
model mới) và tiền của nó đang **rơi im lặng** khỏi hoá đơn (LEFT JOIN ra NULL → CASE ra
NULL → SUM bỏ qua). Query này dùng lại hai CTE `gia_llm`/`gia_embed` ở trên — chạy kèm
chúng trong cùng một `WITH` (hoặc thay bằng bảng giá thật của Portal):

```sql
SELECT DISTINCT u.component, u.provider, u.model
FROM billing.usage_events u
LEFT JOIN gia_llm   l ON u.component='llm'   AND l.provider=u.provider AND l.model=u.model
LEFT JOIN gia_embed e ON u.component='embed' AND e.provider=u.provider AND e.model=u.model
WHERE u.component IN ('llm','embed') AND l.provider IS NULL AND e.provider IS NULL;
```

**VIEW có sẵn:** `billing.usage_by_tenant_month` gộp sẵn theo
`(tenant, tháng, component, purpose, provider, model)` — JOIN thẳng với bảng giá là ra
hoá đơn tháng, **nhưng nó không có `wall_ms` và `channel`**: nếu tính STT theo
stream-time hoặc cần tách hoá đơn theo kênh thì query bảng gốc như mẫu trên.
`billing.usage_by_session` (các cột `stt_sec`/`tts_sec`/`vad_sec`/`speaker_sec`/`call_sec`
đã FILTER theo component) dùng cho màn hình chi tiết phiên.

---

## 5. Bẫy phải tránh khi dựng rollup

### 5.1 KHÔNG BAO GIỜ `SUM(audio_sec)` chéo component

`audio_sec` của các component **đo những quãng audio chồng lấn nhau**:
`vad.audio_sec` ≈ `call.audio_sec` (VAD quét gần như toàn bộ cuộc gọi),
`speaker_verify.audio_sec` ⊂ `stt.audio_sec` (verify lại chính đoạn khách nói).
Cộng gộp là tính một giây audio 3–4 lần. Đúng: mỗi component nhân **đơn giá riêng của nó**
rồi mới cộng **tiền** (như CASE ở §4).

### 5.2 STT: một cơ sở, không phải hai

Nhắc lại vì đây là chỗ dễ sai nhất sau refactor 2026-08-19: `(stt,'conversation')` và
`(stt,'stream')` là hai cách đo **cùng một dịch vụ**. Bảng giá chỉ được kích hoạt MỘT.

### 5.3 Đừng lập hoá đơn theo lượt cho dòng audio

`turn_idx` của dòng audio là xấp xỉ (TTS của lượt N nằm ở lô N+1; lô đóng phiên mang
`turn_idx` = lượt cuối + 1). Tổng theo **phiên/tháng luôn đúng**; join theo lượt chỉ
`component='llm'` đảm bảo. Chi tiết: contract §2.5.

### 5.4 Dòng đến muộn — chốt sổ hai lần

Đường ghi là fire-and-forget có retry theo seq: PG chập chờn thì lô của một phiên có thể
landed **muộn vài phút** (vẫn mang `occurred_at` đúng lúc phát sinh). Nếu Portal chốt hoá
đơn ngay 00:00 ngày 1, hãy re-run rollup sau 24–48h trước khi phát hành. Flush cuối phiên
thất bại hẳn thì payload nằm trong log agent mức `error` (contract §6) — đường cứu tay.

### 5.5 Những vắng mặt là bình thường

- `purpose='memory'` có thể vắng (contract §2.2) — không phải lỗi.
- `purpose='rag_build'` không bao giờ xuất hiện (builder chạy ngoài phiên).
- Phiên chat không có dòng audio nào; phiên voice không dùng `kb_search` thì không có
  dòng `embed`.
- `component='embed'` chỉ có dữ liệu từ 2026-08-19 (trước đó chưa đo).
- `text_units` chỉ có dữ liệu từ **2026-08-20**: dòng cũ hơn mang layout cũ (ký tự của
  `tts`/`embed` nằm trong `units`, `stt` không có vế text). Toàn bộ là dữ liệu dev/test —
  nếu cần sạch tuyệt đối thì xoá dòng trước mốc này thay vì viết công thức hai lớp.

### 5.6 `exact=false` — thiếu, không bao giờ thừa

Chỉ xảy ra ở `llm` (provider cắt stream giữa chừng, thường do khách ngắt lời trên voice).
Số token đã ghi là thật và tính bình thường; phần không đo được thì **mất về phía nhà** —
hoá đơn không bao giờ vượt tiêu thụ thật. Dựng metric `% dòng exact=false` làm cảnh báo
sức khoẻ, đừng "bù" bằng ước lượng.

---

## 6. Ví dụ tính tay một phiên voice thật

Phiên `du_test-c-az2oys-1787135571861-7ad5` (voice, 6 lượt, 142s), số liệu thật trong
bảng, nhân với **bảng giá VÍ DỤ** ở §4:

| Dòng | Số lượng thô | Công thức | Tiền (VÍ DỤ) |
|---|---|---|---|
| `llm` conversation (gemini-2.5-flash) | in 114.771 / out 461 / cache_read 35.548 | `(114771×2500 + 461×10000 + 35548×625)/1e6` | 314 đ |
| `llm` summary (cùng model) | in 903 / out 86 | `(903×2500 + 86×10000)/1e6` | 3 đ |
| `stt` conversation | 10,21 s nói, transcript ~240 ký tự (`text_units`) | `10.21 × 10 + 240 × 0.5` | 222 đ |
| `stt` stream | 142.777 ms, 1 lần | `stt_per_stream_min = 0` → | 0 đ |
| `tts` | 1.115 ký tự (`text_units`; 81,72 s audio) | `1115 × 2` | 2.230 đ |
| `vad` | 141,44 s | `141.44 × 1` | 141 đ |
| `speaker_verify` | 10,57 s (7 lần) | `10.57 × 5` | 53 đ |
| `call` | 142,44 s | `142.44/60 × 500` | 1.187 đ |
| **Tổng phiên** | | | **≈ 4.150 đ** |

Phiên chat tương đương chỉ có hai dòng đầu (+ `embed` nếu có tra cứu tri thức).

Lưu ý: phiên mẫu này được ghi TRƯỚC 2026-08-20 nên trong bảng thật ký tự TTS nằm ở `units`
và `stt.text_units = 0` — số transcript ~240 ký tự ở trên là minh hoạ công thức với layout
mới; phiên ghi từ 2026-08-20 sẽ mang đúng các cột như công thức.

---

## 7. Checklist tích hợp cho Portal

- [ ] Dựng bảng giá theo §1 (LLM/embed keyed `(provider, model)`; audio giá phẳng theo component; cờ `billable` theo `purpose`).
- [ ] Chọn cơ sở thời lượng STT (giây audio HOẶC phút stream) — biến còn lại = 0; vế text-ra (`P_STT_PER_CHAR_OUT`) đặt riêng nếu vendor thu theo transcript (Soniox).
- [ ] Rollup dùng công thức CASE §4; **không** `SUM(audio_sec)` chéo component.
- [ ] Chạy định kỳ query "dòng không có giá" (§4) — bắt model mới trước khi mất tiền.
- [ ] Chốt hoá đơn có cửa sổ re-run 24–48h (§5.4).
- [ ] Dashboard sức khoẻ: `% exact=false` trên `component='llm'` (§5.6).
