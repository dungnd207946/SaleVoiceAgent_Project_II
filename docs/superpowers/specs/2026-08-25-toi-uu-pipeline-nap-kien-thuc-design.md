# Tối ưu pipeline nạp kiến thức + thanh tiến độ theo dự án

**Ngày:** 2026-08-25 · **Trạng thái:** thiết kế, chờ duyệt
**Đo trên:** prod on-prem `10.50.99.104`, tenant `aina_prod` (35 dự án · 659 ảnh · 5.609 unit)

## 1. Vấn đề

Một đợt nạp 659 ảnh mất **~2 giờ 20 phút**, và giao diện chỉ nói được một câu
«Đang nạp kiến thức cho agent…» suốt thời gian đó — không phân biệt được chậm với kẹt.

Ba nguyên nhân, cả ba đo được:

| | Số đo |
|---|---|
Worker chạy **một job một lúc** | `while True: run_once(pool)`, 1 container |
Ảnh gốc bị tải qua Internet **hai lần** | `kb_thumb` tải để resize, `kb_index` tải lại để embed visual |
**24% ảnh không có caption** | Ảnh > 10 MB bị DashScope từ chối `400 Multimodal file size is too large`; handler nuốt lỗi, job vẫn xanh |

Bộ ảnh `aina_prod` nặng **4,4 GB** (trung vị 2,2 MB · p90 19,5 MB · lớn nhất 47,1 MB),
nên hai lượt tải là ~8,8 GB mỗi đợt.

Số đo tham chiếu (prod, 2026-08-24/25):

- Băng thông tới S3 AWS: **5,55 MB/s** ở 4 luồng · **8,47 MB/s** ở 12 luồng
- Caption DashScope `qwen-vl-max`: **~2,3 giây/ảnh**; 4 lượt song song không nghẽn (3,32s cho 4 ảnh)
- Embed visual từ ảnh gốc **4,16s** vs từ thumb **0,26s** (ảnh 11,5 MB)
- Máy prod: 20 nhân, load 0,16 — rảnh

## 2. Ngân sách luồng chung, trần theo loại việc

Thay vòng lặp một-job-một-lúc bằng nhiều task asyncio trong **một** worker.

```
KB_WORKER_BUDGET = 12          # tổng luồng đồng thời
  KB_LANE_THUMB   = 8
  KB_LANE_CAPTION = 6
  KB_LANE_INDEX   = 4
  (kind khác)     = 1
```

Tổng các trần **cố ý lớn hơn** ngân sách: loại nào có việc thì lấp chỗ trống, không
loại nào giữ chỗ mà bỏ trống. Đầu đợt chưa ảnh nào có thumb thì thumb chiếm gần hết;
cuối đợt hết thumb thì caption chiếm gần hết.

Thay đổi trong code:

1. `core/jobs.py` — `_CAU_NHAT_JOB` thêm `AND kind = ANY($1)`. Không có vế này, hàng đợi
   đầy `kb_caption` ở đầu sẽ chặn làn index dù làn đó rỗng.
2. `worker/__main__.py` — mỗi làn một task chạy vòng lặp riêng, claim trong tập kind của
   mình. `FOR UPDATE SKIP LOCKED` vốn viết cho nhiều worker nên nhiều task cùng tiến trình
   không cần gì thêm.
3. **`thu_hoi_viec_ket` thành task định kỳ 60 giây.** Hôm nay nó chỉ chạy khi hàng đợi rỗng
   (`tu_thu_hoi` chỉ cộng khi `run_once` trả `None`), nghĩa là trong đúng một đợt backfill thì
   cơ chế cứu job kẹt **không bao giờ chạy**. Bug có sẵn, song song làm nó dễ gặp hơn.
4. `create_pool` của worker: `max_size` 10 → 16. Mỗi job đang chạy giữ một kết nối suốt
   thời gian gọi VLM.

**Không gom theo chặng.** Mỗi mục tự đi hết chuỗi (`thumb → caption → index`), ba làn chạy
đồng thời. Gom chặng cho tổng thời gian tương đương nhưng cần một khái niệm «đợt» để đặt
rào — trong khi hàng đợi dùng chung mọi tenant và cổng nạp đẩy việc mới vào bất cứ lúc nào —
và làm thanh tiến độ đứng ở 0% cho tới pha cuối.

Nhân số container **không** nằm trong thiết kế này: nút nghẽn là chờ mạng, mà làn asyncio
giải đúng thứ đó không tốn thêm tiến trình hay pool. `--scale` vẫn dùng được nhưng nó
**nhân** mức song song với số container, và `deploy:prod` không truyền `--scale` nên lần
deploy kế tiếp tự thu về 1.

## 3. Tải ảnh gốc đúng một lần

| Chặng | Hôm nay | Sau |
|---|---|---|
`kb_thumb` | tải gốc từ S3 → resize → lưu MinIO | giữ nguyên — lần tải duy nhất |
`kb_caption` | đưa **URL gốc** cho DashScope, nó tự tải ảnh 11 MB | gửi **base64 thumb** (~25 KB) |
`kb_index` visual | **tải lại ảnh gốc** rồi base64 | đọc thumb từ MinIO cùng máy |

`MediaClient.index` đổi `image_src` từ `file_url or media_url` sang `thumb_url` khi có;
`_caption_anh` đổi nhánh URL ngoài sang đọc `media.thumb_url`.

Không mất chất lượng: model visual là `siglip2-base-patch16-256` — nó nhìn ảnh ở 256×256,
còn `THUMB_WIDTH = 512`. Caption thì prompt đã cấm đọc chữ trên hình nên không cần độ nét;
ba cặp mô tả đối chiếu (gốc vs thumb) cho kết quả tương đương.

**Đường lùi:** thumb chưa có hoặc hỏng ⇒ caption tải gốc rồi tự resize trong tiến trình,
giống nhánh ảnh nội bộ đang chạy.

Đây đồng thời là bản sửa **đúng đắn** cho 24% ảnh quá cỡ, không chỉ là tối ưu tốc độ.

## 4. Lỗi VLM: phân loại rồi mới điều tiết

Hôm nay `handle_caption` nuốt mọi lỗi VLM và vẫn nối sang `kb_index` — ảnh lên Qdrant với
caption rỗng, job báo xanh. Với 6 luồng caption thì 429 thành chuyện thường.

1. **Phân loại.** `429`, `5xx`, timeout, lỗi mạng ⇒ `TemporaryVlmError`, ném ra để job retry
   với backoff sẵn có. Lỗi khác (ảnh vỡ, 404) ⇒ giữ hành vi cũ: bỏ mô tả, vẫn nạp.
2. `RETRY_VIEC_KB` cho riêng `kb_caption` nâng 2 → 4.
3. **Điều tiết nhịp.** `VlmRateGate` trong tiến trình: gặp 429 thì giảm một nửa số giấy phép
   và nghỉ 30 giây; mỗi 50 lượt thành công thì cộng lại 1 tới trần. Thuần logic, test không
   cần mạng.

## 5. Thanh tiến độ theo dự án

**Công thức:** `% = (tổng mục − số mục lệch) / tổng mục`

Cả hai vế đã được `_PROJECT_STATUS_SQL` tính sẵn rồi vứt đi — mẫu số là CTE `muc`
(`_MUC_TRONG_TAM_MAT`), số lệch là CTE `lech`. **Không thêm truy vấn nào.**

- Mẫu số: bản ghi dự án (zones gộp làm khối con) + tài liệu chưa chờ duyệt + media thuộc
  danh mục được nạp. Không tính `units` — vertical khai `units` không embed, agent đọc thẳng Postgres.
- Mọi mục tính bằng nhau, không trọng số: con số hover ra phải khớp đúng thanh.

**Bốn trạng thái hiển thị:**

| Điều kiện | Hiện |
|---|---|
`tổng = 0` | `—` (chưa có gì để nạp) |
`đã xong < tổng` | thanh + `%`, hover ra `<đã xong>/<tổng> mục đã tới agent` |
`đã xong = tổng` | thanh đầy **100%** |
`hasError` | badge lỗi + nút Thử lại như hiện tại (lỗi thắng tiến độ) |

**Contract:** `KbStatusOut` thêm `total: int` và `done: int`, giữ `indexing`/`hasError`.
Docstring «HAI CỜ, KHÔNG CÓ SỐ» viết lại kèm lý do đảo quyết định: quyết định đó viết cho
thời nhập tay vài bản ghi, còn nay cổng nạp đổ vào 659 ảnh một lượt.

**FE:** `KbBadge.tsx` đổi nhánh `indexing` sang thanh; `useKbStatus` không đụng (đã poll 3s
và tự tắt theo cờ `indexing`). Bản mô phỏng giao diện: `docs/design/tien-do-nap.html`.

## 6. Kiểm chứng

**Unit** — `VlmRateGate` (giảm/hồi giấy phép, thuần logic) · phân loại lỗi tạm/vĩnh viễn ·
câu claim theo kind trả đúng job của tập kind · công thức `%` gồm ca `tổng = 0`.

**Integration** — nhiều làn chạy đồng thời không nhặt trùng job · `thu_hoi_viec_ket` chạy được
khi hàng đợi vẫn bận · caption dùng thumb khi có và rơi về gốc khi thiếu · index dùng thumb.

**Cổng hồi quy** — một bài canh `MediaClient.index` **không** đọc `media_url` cho vector visual:
đây là chỗ vừa sửa và cũng là chỗ dễ bị hoàn nguyên nhất.

**Đo lại trên prod sau khi ship:** thời gian nạp trọn `aina_prod` và số ảnh có `caption_auto`
rỗng. Kỳ vọng ~10–12 phút (trong đó ~9 phút là tải 4,4 GB — giới hạn đường truyền) và
0 ảnh thiếu caption vì quá cỡ.

## 7. Ranh giới

**Không làm trong đợt này:**

- Nhân số container worker — xem §2.
- Gom batch nhiều ảnh trong một lời gọi VLM.
- Bảng «đợt nạp» riêng để xem lịch sử từng đợt: tiến độ đếm từ dữ liệu thật nên không cần.
- Tách tiến độ văn bản và hình ảnh: người dùng chốt gộp một thanh.

**Phụ thuộc bên ngoài:** muốn nhanh hơn ~9 phút thì phải giảm số byte tải — URL của AINA là
S3 thô, không có tham số resize. Cần bên họ bật CDN resize hoặc cấp một rendition nhỏ.

**Quy ước:** định danh mới viết tiếng Anh (`VlmRateGate`, `KB_LANE_*`, `done`/`total`), tiếng
Việt chỉ ở comment và tên test.

## 8. Trạng thái thi công (2026-08-25)

Đã ship trên nhánh `feat/kb-ingest-speedup` (cả hai repo), 9 commit. Kiểm chứng ở local:

| | |
|---|---|
`tests/unit` | 275 passed (thêm 16: registry, trần làn KB, rate gate) |
`tests/modules/kb` | 640 passed |
`tests/modules/realestate` + `tests/isolation` | 398 passed, 1 skipped — cổng cách ly tenant xanh |
Frontend | 1087 passed, 6 skipped · `npm run build` sạch |
`make check` | 11 failed · 17 errors — **trùng khít từng tên với `origin/develop`** (đo bằng worktree tách riêng), không có hồi quy |

Nợ đỏ có sẵn, không thuộc đợt này: `test_worker_retry.py` (fixture còn chèn cột `org_id`
đã xoá ở `0106`) · `test_dang_ky.py` + `test_migration_invites_tenant.py` · `test_heartbeat.py`
(RLS thiếu trên `control.agent_heartbeats`) · `test_index_client_that.py` (`PUBLIC_BASE_URL`
rỗng trong `.env` máy dev).

**Chưa làm được, cần deploy trước:** đo lại thời gian nạp trọn `aina_prod` và số ảnh
thiếu caption trên prod (§6). Câu SQL để đo nằm ở Task 12 của plan.

## 9. Cần thêm vào CLAUDE.md (người dùng tự dán — nhiều người cùng sửa file đó)

| Ngày | Thay đổi |
|---|---|
| 2026-08-25 | **Worker chạy NHIỀU LÀN, trần đồng thời khai theo loại việc.** `register()` mọc `max_concurrency=` (mặc định 1); `core/jobs.py` giữ bộ đếm in-flight theo kind và `run_once(pool, kinds=…)` lọc theo tập kind — thiếu vế lọc đó thì hàng đợi đầy `kb_caption` chặn làn index dù làn đó rỗng. Claim nằm trong `_CLAIM_LOCK` để hai làn không cùng đọc một chỗ trống. Biến env mới **`WORKER_BUDGET`** (mặc định 12); trần từng chặng ở `kb/contracts.py`: `LANE_THUMB=8` · `LANE_CAPTION=6` · `LANE_INDEX=4`. ⚠️ `--scale worker=N` **NHÂN** mức song song lên, và `deploy:prod` không truyền `--scale` nên lần deploy kế tiếp tự thu về 1 container. ⚠️ **Bug đã sửa kèm:** `thu_hoi_viec_ket` trước đây chỉ chạy khi hàng đợi RỖNG (`tu_thu_hoi` chỉ cộng khi `run_once` trả `None`), tức trong đúng một đợt backfill dài — lúc dễ có việc kẹt nhất — cơ chế cứu job kẹt không bao giờ chạy; nay là task định kỳ 60 giây. **Ảnh gốc tải ĐÚNG MỘT LẦN**: `kb_thumb` tải, còn caption và vector visual đều đọc bản thumb (`MediaClient.index` dùng `thumb_url` trước; `EmbedClient` nhận `objects=` để đọc khoá nội bộ thẳng từ kho thay vì đi vòng HTTP). ⚠️ **Đây là sửa ĐÚNG ĐẮN chứ không chỉ tối ưu**: DashScope từ chối ảnh > 10 MB với `400 Multimodal file size is too large` khi gửi bằng URL, mà `handle_caption` nuốt mọi lỗi VLM — đo trên prod 2026-08-25: **24% ảnh** của `aina_prod` (≈159/659) lên Qdrant với caption RỖNG và job vẫn xanh. Số đo nền: ảnh 11,5 MB tốn 4,16s (tải+embed) vs thumb 31 KB tốn 0,26s; model visual là `siglip2-base-patch16-256` nên nó nhìn ảnh ở 256px bất kể ta gửi gì; băng thông tới S3 8,47 MB/s ở 12 luồng. **Lỗi VLM tách hai hạng**: `TemporaryVlmError` (429/5xx/timeout) ném ra để job retry — `RETRY_CAPTION = 4` cho riêng `kb_caption`; lỗi khác giữ hành vi cũ (bỏ mô tả, vẫn nạp). Thêm `VlmRateGate` (`clients/rate_gate.py`): gặp 429 thì giảm nửa số giấy phép + nghỉ 30s, mỗi 50 lượt thành công cộng lại 1 — dùng `asyncio.Condition` chứ KHÔNG Semaphore, vì semaphore khoá cứng số slot lúc dựng nên `penalize()` sẽ chỉ đổi một con số trang trí. **`KbStatusOut` thêm `total`/`done`** (đảo quyết định «HAI CỜ, KHÔNG CÓ SỐ» của D03 — quyết định đó viết cho thời nhập tay vài bản ghi, nay cổng nạp đổ vào hàng trăm ảnh một lượt); cả hai số lấy từ CTE mà `_PROJECT_STATUS_SQL` vốn đã tính rồi vứt đi nên KHÔNG thêm truy vấn nào, và `greatest(…, 0)` là bắt buộc vì `lech` đếm cả mục chưa có dòng sổ nên vượt được `tong`. FE `KbBadge` đổi dòng chữ tĩnh thành thanh tiến độ (`total = 0` ⇒ không vẽ gì; đủ ⇒ 100%; số đầy đủ nằm ở `title`). Hai cổng bị ĐẢO CÓ CHỦ Ý và đã viết lại chứ không để đỏ: `test_hinh_dang_response_dung_hai_co` (BE) và hai bài trong `realestate-nap-kien-thuc.test.tsx` (FE). Spec: `docs/superpowers/specs/2026-08-25-toi-uu-pipeline-nap-kien-thuc-design.md`. |
