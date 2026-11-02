# Bench TTS — Soniox tts-rt-v2 vs ElevenLabs

Đo Soniox TTS v2 đối với ElevenLabs trên **câu thoại tiếng Việt của hotline**, cùng
định dạng mp3 44.1 kHz 128 kbps để so được. Dựng lần đầu 18/08/2026 khi Soniox ra
`tts-rt-v2`; kết luận lượt đó: **giữ ElevenLabs cho luồng gọi trực tiếp, dùng Soniox
cho audio dựng trước** (chi tiết ở cuối file).

## Khoá API

Hai biến, đọc từ môi trường — script **ném ngay** nếu thiếu chứ không bỏ qua im lặng
(bỏ qua thì báo cáo cuối chỉ có một bên mà không ai nhận ra):

```bash
export SONIOX_API_KEY=...      # console.soniox.com -> project -> API Keys
export ELEVENLABS_API_KEY=...  # elevenlabs.io/app/settings/api-keys
```

⚠️ `SONIOX_API_KEY` trong `.env` của repo **đã bị thu hồi** (401 cả STT lẫn TTS, đo
18/08/2026) — đừng `source .env` rồi tưởng là có khoá. Khoá ElevenLabs trong `.env`
còn dùng được nhưng thiếu scope `user_read`, nên `/v1/user` trả 401 trong khi
`/v1/text-to-speech` vẫn chạy: **401 ở endpoint user không có nghĩa là khoá chết.**

Cần `ffprobe` (đo thời lượng audio): `brew install ffmpeg`.

## Chạy

```bash
cd scripts/tts_bench

# 1. REST — chất lượng + latency tổng. Sinh audio vào out/, ~7 phút cho 6 cấu hình.
REPEATS=3 uv run python bench_rest.py                    # tất cả câu thử
REPEATS=1 uv run python bench_rest.py greet,alnum        # chỉ vài câu

# 2. Streaming — TTFB và biên phát lại. Đây là số liệu quyết định cho voice agent.
ITERS=5 CASE=greet RESULTS_FILE=results_stream_greet.json uv run python bench_stream.py
ITERS=3 CASE=long  RESULTS_FILE=results_stream_long.json  uv run python bench_stream.py
uv run python analyze_stream.py                          # tính RTF + biên phát lại

# 3. Chấm điểm khách quan — phiên âm lại audio TTS bằng Soniox STT, tính CER/WER.
uv run python score_stt.py                               # ~6 phút cho 37 tệp
uv run python rescore.py                                 # loại nhiễu chữ-số, xem bên dưới

# 4. Kiểm chứng đọc số — sinh lại N lần, kiểm từng con số.
N=5 uv run python verify_digits.py

# 5. Chi phí thực trên mỗi giờ audio (quy đổi theo ký tự/giây đo được).
uv run python cost.py

# 6. Dựng trang so sánh có nghe A/B (nhúng audio base64, ~4 MB).
uv run python build_report.py                            # -> report.html
```

`build_report.py` đọc kết quả của **mọi** bước trên (`results_rest.json`,
`results_rs.json`, `results_emotion.json`, `results_stream_greet.json`,
`results_stream_long.json`, `results_stt_rescored.json`, `results_cost.json`,
`results_verify_digits.json`) nên phải chạy đủ bước 1–5 trước; thiếu tệp nào nó
báo `FileNotFoundError` kèm đúng tên tệp đó.

Biến môi trường phụ: `CASES_FILE`, `CONFIGS_FILE`, `RESULTS_FILE` (đổi đầu vào/ra để
chạy bộ emotion hoặc một cấu hình lẻ), `STT_MODEL`, `BENCH_DATE`.

Ví dụ chạy bộ emotion tags:

```bash
REPEATS=1 CASES_FILE=cases_emotion.json CONFIGS_FILE=configs_emotion.json \
  RESULTS_FILE=results_emotion.json uv run python bench_rest.py
```

## Tệp

| Tệp | Việc |
|---|---|
| `_common.py` | SSL context, User-Agent, đọc khoá, đo thời lượng audio |
| `bench_rest.py` | REST hai nhà cung cấp, đo TTFB + tổng, ghi mp3 vào `out/` |
| `bench_stream.py` | Soniox WebSocket vs ElevenLabs `/stream`, đo TTFB thực |
| `analyze_stream.py` | RTF và **biên phát lại** từ kết quả streaming |
| `score_stt.py` | Phiên âm lại bằng `stt-async-v5`, tính CER/WER thô |
| `rescore.py` | Tính lại CER sau khi loại chênh lệch chữ-số vs chữ-viết |
| `verify_digits.py` | Sinh lại N lần, kiểm từng con số (mã đơn, ngày, tiền, hotline) |
| `cost.py` | USD mỗi giờ audio, quy đổi theo ký tự/giây đo được |
| `build_report.py` + `report_template.html` | Trang so sánh có nghe A/B |
| `cases*.json`, `configs*.json` | Câu thử và cấu hình nhà cung cấp |

## Bốn cạnh sắc — đọc trước khi sửa

1. **`output_format` của ElevenLabs là QUERY param, không phải body field.** Đặt trong
   JSON body thì bị bỏ qua **âm thầm** và trả `mp3_44100_128` mặc định — tệp `.pcm` hoá
   ra là mp3 có ID3 header. Kiểm bằng magic bytes (`49443304` = `ID3`).

2. **Cloudflare trước `tts-rt.soniox.com` chặn User-Agent mặc định của urllib** → 403
   `error code: 1010`. `_common.UA` tồn tại vì việc này. `api.soniox.com` (STT, list
   model) thì không chặn.

3. **Docs REST của Soniox ghi sai `audio_format`.** Thực tế API nhận `pcm_f32le,
   pcm_s16le, pcm_mulaw, pcm_alaw, wav, flac, mp3, opus, aac`. Docs ghi `pcm_s16be` —
   format đó không tồn tại; và docs **không nêu** `pcm_mulaw`/`pcm_alaw`/`opus` dù có
   (quan trọng cho telephony). Lấy danh sách thật bằng cách gửi format sai rồi đọc
   `error_message`.

4. **CER thô của câu dài KHÔNG đo chất lượng TTS.** STT xuất chữ số (`"3 000"`) trong
   khi văn bản gốc viết chữ (`"ba nghìn"`), nên mọi cấu hình ra **cùng một** con số —
   dấu hiệu nhận biết: các dòng CER giống hệt nhau. `rescore.py` loại chữ số + từ chỉ
   số ở cả hai phía rồi tính lại; sau đó câu trộn Anh–Việt về 0% và đoạn dài về 1,25%
   đồng đều ở mọi cấu hình, tức **không bên nào phát âm sai**. Chỉ câu `alnum` là dùng
   được CER thô, vì văn bản gốc ở đó vốn đã viết bằng chữ số.

Thêm: `score_stt.py` dùng STT **của chính Soniox** để chấm cả hai bên nên thiên vị nhẹ
về phía Soniox. Nó đo **độ rõ**, không đo độ tự nhiên — nghe A/B mới trả lời được.

## Kết quả lượt 18/08/2026

Đo từ máy làm việc (RTT tới Soniox 53 ms, tới ElevenLabs 19–25 ms — chênh lệch mạng
~30 ms không giải thích được khoảng cách TTFB 276 ms).

| | Soniox `tts-rt-v2` | ElevenLabs `eleven_flash_v2_5` |
|---|---|---|
| TTFB streaming | 0,44 s | **0,21 s** |
| RTF (tốc độ sinh) | 0,87–1,19 | **0,03–0,10** |
| Biên phát lại, câu ngắn | −0,09 s (mp3), −0,27 s (µ-law) | **+3,15 s** |
| Biên phát lại, đoạn dài | +3,26 s | **+23,26 s** |
| Chi phí/giờ audio | **$0,70** | $3,14 |
| Đọc đúng số tiền (5 lần) | **5/5** | 4/5 |

**Điểm chặn là RTF, không phải TTFB.** Soniox sinh audio ở gần đúng nhịp thoại, nên ở
câu ngắn — loại chiếm phần lớn một cuộc gọi — audio sinh ra chậm hơn nhịp phát và phát
ngay sẽ hụt. Cấu hình Soniox tốt nhất tìm được: `speed 1.15` + `reduce_silence=true`
(mặc định dài hơn ElevenLabs ~15%; bật hai tham số này thì gọn hơn).

**Chưa trả lời được:** giọng nào tự nhiên hơn với người Việt. Giọng đang chạy là
"Ánh Viên" — giọng Việt chuyên nghiệp đã clone; 70 giọng built-in của Soniox không có
giọng Việt bản địa nào. Muốn so đúng phải dùng voice cloning của Soniox trước.

Ngoài ra: ElevenLabs Flash v2.5 **phát âm luôn tên audio tag** — bản phiên âm ra đúng
chữ "excited". Audio tag chỉ chạy trên `tts-rt-v2` (Soniox) và `eleven_v3`.
