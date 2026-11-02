# voices/omnivoice — giọng cố định của sản phẩm

Mỗi file `<voice_id>.pt` ở đây là một giọng đã clone sẵn cho `tts-omnivoice`.
Tên file chính là giá trị đặt vào `VIENEU_VOICE_ID` của agent (hoặc trường
`voice` trong message `synthesize`).

Thư mục này được bind-mount vào container tại `/app/voices`:

| | mount | `enroll_voice` qua WS |
|---|---|---|
| `docker-compose.yml` (dev) | rw | được — ghi thẳng ra đây, commit luôn |
| `docker-compose.onprem.yml` (prod) | **ro** | trả lỗi, **có chủ ý** |

Prod không được tự tạo giọng: mọi giọng phải đi qua repo để có review và có
phiên bản. Đây là giọng cố định của sản phẩm, không phải chức năng cho khách
tự clone — nếu sau này cần thế thì nơi lưu là object storage/DB có phân quyền
và backup, không phải thư mục này.

## Tạo một giọng mới

```bash
# service chạy ở dev (docker hoặc bare-metal, miễn là CUSTOM_VOICES_DIR trỏ về đây)
python scripts/enroll_voice.py --service omnivoice \
  --ref-audio ~/duong/dan/giong_mau.wav \
  --voice-id khach_a \
  --ref-text "Đúng nguyên văn những gì clip nói"

git add voices/omnivoice/khach_a.pt && git commit
```

## KHÔNG commit file audio mẫu

`.gitignore` đã chặn `*.wav`/`*.mp3`/`*.flac` trong thư mục này. Clip giọng là
dữ liệu sinh trắc của người thật, vào lịch sử git là ở đó vĩnh viễn, mà
production không cần tới nó. Giữ clip ở máy bạn hoặc storage nội bộ có kiểm
soát.

File `.pt` thì an toàn để commit — nó chỉ chứa `ref_audio_tokens` (token của
codec, 8×T int64), `ref_text` và `ref_rms`. Không tái tạo lại được audio gốc.

Lưu ý `ref_text` nằm trong file dưới dạng plaintext: chọn câu mẫu trung tính,
đừng dùng câu có thông tin nhạy cảm.

## Hai cái bẫy

**`voice_id` sai không báo lỗi.** Service lặng lẽ dùng giọng built-in. Gõ nhầm
`VIENEU_VOICE_ID` thì agent vẫn chạy ngon lành bằng giọng mặc định — kiểm tra
log lúc boot (`📢 Loaded N previously-enrolled custom voice(s)`) để biết giọng
nào thật sự được nạp.

**`ref_text` phải khớp clip.** Service không nạp ASR nên không tự kiểm tra
được. Sai lời thì giọng clone lệch, và cũng không có gì báo.
