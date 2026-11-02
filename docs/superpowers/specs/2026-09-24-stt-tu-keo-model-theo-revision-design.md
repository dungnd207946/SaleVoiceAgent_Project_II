# stt tự kéo model theo revision HF mỗi lần boot

Ngày 2026-09-24. Phạm vi: `stt/stt_server.py`, `docker-compose.onprem.yml`, `tests/test_stt_provision.py`, README.

## Vấn đề

`_ensure_model_present()` chỉ tải từ HF khi `models/odyssey-stt/` chưa có encoder. Thư mục là bind mount sống qua mọi lần deploy, nên push model mới lên HF xong server vẫn chạy bản cũ cho tới khi có người SSH xoá thư mục rồi restart. `tts` cùng repo đã kéo theo `TTS_HF_REVISION` mỗi lần boot; `stt` làm khác chỉ vì viết theo khuôn `speaker`.

## Hành vi mới của `_ensure_model_present(model_dir, quantize)`

Chạy một lần lúc boot, trước khi mở cổng 8012.

1. `STT_HF_REPO` rỗng → không gọi HF. Dùng thư mục có sẵn; thiếu file thì lỗi như hiện nay. Đây là cửa thoát cho fine-tune đặt tay.
2. Hỏi HF commit hiện tại của `STT_HF_REPO@STT_HF_REVISION` (`HfApi.repo_info(...).sha`, timeout ngắn).
3. Đọc `model_dir/.revision`. Nếu bằng sha vừa lấy **và** `_discover_stem(model_dir, quantize)` tìm được stem → log "up to date", return.
4. Ngược lại (khác sha, thiếu `.revision`, hoặc thiếu file cho variant đang dùng):
   - `snapshot_download(repo, revision=<sha>, local_dir=model_dir + ".new")`, tải **cả 7 file** (không lọc int8/fp32 nữa: đổi `STT_MODEL_QUANTIZE` không phải tải lại; hơn 26MB).
   - Kiểm `_discover_stem(new_dir, quantize)` và có `tokens.txt`. Hỏng → xoá `.new`, ném lỗi; thư mục cũ không bị chạm.
   - Đổi chỗ: xoá `model_dir + ".prev"` nếu có, `model_dir` → `.prev`, `.new` → `model_dir`. Ghi `.revision` = sha vào thư mục mới.
   - Giữ đúng một `.prev` để lùi tay bằng đổi tên. `.cache/` của huggingface_hub nằm trong `.new` đi theo sang thư mục mới, không cần dọn.
5. Bước 2 ném (mạng, 401, repo sai): có model local dùng được → `logger.warning`, chạy tiếp với bản cũ. Không có → ném, container không lên, healthcheck bắt.

`_discover_stem` giữ nguyên, kể cả `ValueError` khi thư mục nhập nhằng. Với thư mục local nhập nhằng mà HF có bản mới thì bước 4 thay cả thư mục, bản cũ vẫn còn ở `.prev`.

Log: `📂 STT model up to date @<sha7>` · `📥 STT model <cũ7 hoặc "none"> → <mới7>, pulling …` · `⚠️ HF unreachable (<lỗi>) — using local @<sha7 hoặc "unknown">`.

## Cấu hình

- Cả `docker-compose.onprem.yml` và `docker-compose.yml`: `STT_HF_REVISION=${STT_HF_REVISION:-prod}` (trước là `main`), giống `TTS_HF_REVISION`. Mọi máy, dev lẫn prod, đều kéo từ HF `prod`; muốn thử bản khác thì khai `STT_HF_REVISION` trong `.env`.
- Máy đang chạy chưa có `.revision` → lần boot đầu sau deploy tự tải một lần, bản cũ nằm ở `.prev`.

## Khi nào model mới lên server

Bất kỳ lần nào container `stt` khởi động lại: deploy code lên `odyssey-models` (image tag theo commit nên compose luôn tạo lại container), `docker compose restart stt` chạy tay, máy reboot. Không có webhook, không có poll.

## Test (`tests/test_stt_provision.py`, stub `huggingface_hub`)

- Đúng sha + đủ file → không gọi `snapshot_download`.
- Khác sha → tải vào `.new`, sau đó `model_dir` có file mới + `.revision` đúng, `.prev` có file cũ.
- Thiếu `.revision` nhưng có file → tải (ca server hiện tại).
- `repo_info` ném + có local → không ném, không tải.
- `repo_info` ném + trống → ném.
- Bản tải thiếu encoder → ném, `model_dir` cũ nguyên, không còn `.new`.
- `STT_HF_REPO=""` → không gọi HF.
- `.prev` cũ bị thay khi cập nhật lần hai.

## Tài liệu

README mục Models: bỏ câu "thư mục đã có weights được để yên", thay bằng hành vi theo revision và cách lùi (`mv odyssey-stt.prev odyssey-stt` rồi restart, hoặc `STT_HF_REVISION=<sha cũ>`). `.gitlab-ci.yml` ghi chú 4: không còn phải đặt sẵn `models/odyssey-stt/`.

## Ngoài phạm vi

Không webhook HF, không job CI mới, không nạp lại nóng. Không đổi `speaker`/`tts`. Nhánh `prod` của git `odyssey-models` do người vận hành tạo và protect.
