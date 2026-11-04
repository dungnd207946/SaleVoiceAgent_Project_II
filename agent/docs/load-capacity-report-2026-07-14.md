# Báo cáo Tải / Khả năng chịu tải — santa-hotline-agent

**Ngày:** 2026-07-14 · **Mục tiêu:** `10.50.12.70` (thebc-server) · **Phương pháp:** ép tải tới điểm gãy (stress-to-break), bơm tải từ một máy client trong LAN (Mac), lấy mẫu tài nguyên trên server. Bộ công cụ: `scripts/load_test/v2/`. Spec/plan: `docs/superpowers/{specs,plans}/2026-07-14-load-capacity-stress-test*`.

## Tóm tắt nhanh (TL;DR)

- **GPU đơn (TTS) là trần cứng cho thoại.** TTS tổng hợp âm thanh hoàn toàn **tuần tự** và cho ra tốc độ ~**8× thời gian thực** tính gộp. Sức chứa cuộc gọi thoại đồng thời thực tế ≈ **8–12 cuộc** (lý thuyết ~20), bất kể CPU còn dư bao nhiêu.
- **STT và embed nghẽn ở CPU nhưng nhanh** — chúng scale trên 20 luồng, đạt ~32 lượt phiên âm/s và ~40–53 lượt embed/s, cao hơn nhiều so với trần thoại.
- **Đường chat/WS bị chặn bởi giới hạn kết nối (admission cap), không phải nghẽn tính toán:** `max_ws_per_ip = 5`, `max_ws_connections = 100` (toàn cục). Bộ điều phối xử lý 5 phiên đồng thời ở mức phẳng ~1.14 s/lượt, không hề căng.
- **Không có gì crash.** Mọi service suy giảm một cách mượt (độ trễ tăng dần); không có lỗi dưới tải ngoại trừ giới hạn kết nối WS vốn có chủ đích.

## Cập nhật 2026-07-15 — Gỡ nút thắt TTS + đo trần thoại E2E thật (Phase C)

**Nút thắt TTS hóa ra là LOCK phần mềm, không phải GPU.** Service TTS (`santa-models/tts/tts_server.py`, engine lmdeploy turbomind) có một `threading.Lock` toàn cục serialize toàn bộ mỗi lượt tổng hợp → turbomind (vốn continuous-batching) không bao giờ batch được. Thay bằng `Semaphore(TTS_MAX_CONCURRENT)` + `memory_util` env-tunable → đo được **1.3 → 6.2 synth/s (~4.8×) trên CÙNG GPU**, 0 lỗi, độ dài audio giữ nguyên. Branch `perf/tts-concurrent-generation` (repo `santa-models`); config chạy `conc=6, mem=0.7`.

**Phase C — đo E2E trực tiếp qua đường production (LiveKit Cloud → worker), LLM stub để cô lập infra:**

| Cuộc gọi đồng thời | ttfr p95 | total p95 | Lỗi |
|---:|---:|---:|---:|
| 8–16 | ~6.7–6.9 s | ~18.7 s | 0 |
| 24 | 8.3 s | 19.7 s | 0 |
| 32 | **21.7 s** 💥 | 38.3 s | 0 (chỉ latency) |

- **Trần thoại thật ≈ 24 cuộc gọi đồng thời** (thoải mái, latency phẳng, 0 lỗi); vỡ ở ~32 (latency phồng ~3×, vẫn 0 lỗi).
- **Nút thắt giờ là CPU server, KHÔNG phải GPU.** Tại c=32: CPU tổng **95.6% (idle 1.7%, load 13.6/20)** — chủ yếu do worker **agent-lk 546% CPU / 7.2 GB** (32 job-subprocess: Silero VAD + audio I/O realtime mỗi cuộc) + **STT sherpa 285%**; GPU/TTS chỉ 94% util (bận nhưng không bão hòa bền). Máy client (Mac) chỉ ~18% CPU → không phải nút thắt.
- **So với ước lượng cũ 8–12** (khi TTS còn serial): trần tăng ~2–3×. Để tăng tiếp: giảm CPU/cuộc (VAD nhẹ hơn / STT lên GPU / thêm core / CPU-pin) hoặc scale ngang nhiều worker box.
- Đường **aiortc `:8766` là đường chết** (không client nào dùng); đo qua **LiveKit = đúng đường production**. Tooling: `scripts/load_test/v2/phase_c_livekit.py`.

## Môi trường

Một máy duy nhất: **Intel i5-14600KF (20 luồng), 30 GiB RAM, 1× RTX 5060 Ti 16 GB.** Dùng chung với `santa-chat-agent`, CMS, Grafana/Loki/Alloy, Phoenix, Caddy, và các model service. GPU dùng chung (hotline-TTS thường trú ~4.8 GB + một model đồng cư ~2.3 GB). RTT trong LAN ~0.6 ms. Không có traffic hotline thật trong lúc test.

Topology: thoại = LiveKit Cloud → worker `agent-lk` → **STT** từ xa (sherpa CPU, `:8012`), **TTS** từ xa (tiến trình GPU native, `:8011`); chat/WebRTC = `agent` aiortc (`:8766`); LLM = gemini-2.5-flash; kho lưu trữ = Mongo/Redis/Qdrant; embed = e5-large CPU (`:8013`).

## Phase A — trần từng service (cô lập, không có LLM)

Mỗi bậc giữ 60 s; ramp đầy đủ `1→128` (TTS `1→16`); điểm gãy (knee) = bậc cuối cùng mà thông lượng vẫn còn scale ≥15%.

### TTS `:8011` — GPU, **tuần tự**, ràng buộc quyết định

| mức đồng thời | p50 ms | p95 ms | req/s |
|---:|---:|---:|---:|
| 1 | 772 | 823 | 1.3 |
| 2 | 1548 | 1634 | 1.3 |
| 4 | 3136 | 3222 | 1.3 |
| 8 | 6186 | 6289 | 1.3 |
| 16 | 12351 | 12498 | 1.3 |

**GPU util 99% suốt quá trình.** Độ trễ nhân đôi mỗi khi tăng gấp đôi mức đồng thời; thông lượng phẳng lì ở **1.3 lượt tổng hợp/giây**. Không có song song hóa — GPU xử lý từng lượt tổng hợp một. Một lượt tổng hợp câu ~110 ký tự = ~**6.5 s âm thanh sinh ra trong ~0.77 s thời gian tường** (TTFB ~0.2 s) → **~8× thời gian thực**. Trần gộp ≈ **8.4 giây âm thanh trên mỗi giây tường, chia sẻ cho tất cả cuộc gọi.**

### STT `:8012` — CPU, có scale

| mức đồng thời | p95 ms | req/s |
|---:|---:|---:|
| 1 | 189 | 5.8 |
| 8 | 418 | 23.5 |
| 16 | 540 | **32.4** |
| 32 | 1201 | 29.5 |
| 128 | 5415 | 25.4 |

Đỉnh ở **~32 lượt phiên âm/s tại c=16**, sau đó CPU bão hòa (`models-stt` CPU **1981%** ≈ 19.8/20 luồng; GPU 0%). Không lỗi ngay cả ở c=128 (chỉ độ trễ cao). Mỗi câu 3.4 s giải mã trong ~170 ms khi đã ấm (~20× thời gian thực).

### embed `:8013` — CPU, chững lại (plateau)

| mức đồng thời | p95 ms | req/s |
|---:|---:|---:|
| 1 | 42 | 24.9 |
| 8 | 253 | 43.2 |
| 16 | 407 | 53.5 |
| 128 | 3632 | 44.5 |

Chững ở **~40–53 lượt embed/s** (`models-embed` CPU **1985%** ≈ 20 luồng; GPU 0% — embed chạy trên CPU). Không lỗi.

## Phase B — chat WS đầu-cuối (`:8766`, LLM đã stub)

LLM được thay bằng một stub tương thích OpenAI chạy trên Mac (~50 tok/s) để cô lập infra; đã hoàn nguyên sau đó. **Kết quả: tải chạm giới hạn kết nối theo IP, chứ không phải trần điều phối.** Từ một IP nguồn duy nhất, đúng **5 phiên kết nối được; phần còn lại bị từ chối** (`ConnectionClosedError`) — xác nhận bằng một probe chỉ-kết-nối độc lập với LLM (5 ok ở 16/32/64/128).

- **`max_ws_per_ip = 5`** (ws_handler.py:33), **`max_ws_connections = 100`** toàn cục (ws_handler.py:30). Cả hai đều không bị override trong `.env`.
- Ở ≤5 phiên đồng thời: **phẳng ~1.14 s/lượt, 0 lỗi** (stub) — điều phối + Redis + Mongo không hề bị căng ở mức đó. (Độ trễ mỗi lượt chính là câu trả lời stub ~52 token ở 50 tok/s; gemini thật thêm độ trễ riêng của nó, thấy ở lượt warm-up: p95 ~4.3 s.)
- **Trần điều phối thực sự (lên tới giới hạn toàn cục 100) chưa được đo** — cần hoặc nâng `max_ws_per_ip` hoặc bơm tải đa-IP. Đã hoãn theo quyết định.

**Hệ quả kiến trúc:** nếu NobleX app định tuyến chat WS qua một IP backend duy nhất, toàn bộ app bị giới hạn ở **5 chat đồng thời**; nếu thiết bị người dùng cuối kết nối trực tiếp, mỗi IP thiết bị được 5 (toàn cục 100). Cần xác nhận app kết nối theo cách nào.

> Lưu ý: stub chỉ sinh text (không gọi tool), nên Phase B chưa chạy qua đường `noble_search`→Qdrant/embed — phần đó đã được Phase A phủ bằng bài test embed.

## Sức chứa cuộc gọi thoại đồng thời (suy ra)

Bị chặn bởi TTS/GPU (gộp ~8.4 s-âm-thanh/s, tuần tự):

- **Lý thuyết ≈ 20 cuộc** — nếu Luna nói ~40% thời gian tường của cuộc gọi, mỗi cuộc cần ~0.4 s-âm-thanh/s → 8.4 / 0.4 ≈ 21.
- **Thực tế ≈ 8–12 cuộc** — tổng hợp là tuần tự, nên khi vài cuộc gọi cùng chạm ranh giới câu một lúc, chúng xếp hàng ~0.77 s mỗi lượt; vượt quá ~1 lượt tổng hợp bị xếp hàng thì đệm đầu ra 800 ms (`NOBLE_TTS_OUTPUT_QUEUE_MS`) bị vượt → có khoảng lặng nghe thấy được và câu trả lời bị trễ. TTFA mỗi lượt suy giảm tuyến tính theo số lượt tổng hợp đang chạy đồng thời.
- Con số chính xác phụ thuộc vào thống kê chồng-lấn lượt nói giữa các cuộc gọi thật — **Phase C (cuộc gọi LiveKit/WebRTC tổng hợp) sẽ đo trực tiếp; đang hoãn.**

Ở khoảng ~8–20 cuộc này, STT (~32/s) và embed (~40–53/s) còn dư địa dồi dào — nhưng cả hai đều bão hòa toàn bộ 20 luồng CPU tại điểm gãy của *chính chúng*, nên một workload thật hỗn hợp sẽ tranh chấp CPU (STT + embed + điều phối agent + chat-agent đồng cư), và GPU thì dùng chung với một model đồng cư.

## Khuyến nghị

1. **Thoại nghẽn ở GPU — tăng thông lượng TTS để nâng trần cuộc gọi.** Các lựa chọn, xếp đại khái theo công sức: (a) bật đường serving **`vieneu_vllm`** đã có sẵn (codebase đã có; vLLM đo được độ trễ mỗi token thấp hơn và tổng thời gian tốt hơn đường transformers local); (b) micro-batch các lượt tổng hợp đồng thời trên GPU; (c) thêm/nâng cấp GPU thứ hai hoặc codec+backbone lượng tử hóa nhanh hơn; (d) nếu không có gì, **giới hạn số phiên âm thanh đồng thời bằng một hàng đợi tường minh** để người gọi được chờ mượt thay vì nghe tiếng ngắt quãng.
2. **Chat: xem lại `max_ws_per_ip = 5`.** Ổn nếu người dùng cuối kết nối từ các IP khác nhau; là nút thắt nghiêm trọng nếu app proxy qua một IP backend. Nâng nó (và/hoặc trần toàn cục 100) cho khớp mức đồng thời kỳ vọng của app, rồi đo trần điều phối thật với cap đã nâng hoặc tải đa-IP.
3. **Đồng cư (co-tenancy):** tải hotline nặng chia sẻ 20 luồng CPU + GPU với `santa-chat-agent` và các service khác. Để đạt mức thoại đồng thời gần trần trong production, cân nhắc cô lập GPU cho TTS và/hoặc ghim CPU (CPU-pin) cho các model service.
4. **Dư địa suy giảm mượt:** không quan sát thấy crash hay lỗi lan truyền; các service suy giảm bằng độ trễ, đây là kiểu hỏng mong muốn.

## Tái lập (Reproduce)

Bộ công cụ + công thức chạy: `scripts/load_test/v2/README.md`. Bảng kết quả thô: `scripts/load_test/v2/out/phaseA/*_RESULTS.md`, `out/phaseB/chat_RESULTS.md`. Bằng chứng lấy mẫu (gitignore, theo từng lần chạy): `out/phaseA/{gpu,container}_samples.txt`.
