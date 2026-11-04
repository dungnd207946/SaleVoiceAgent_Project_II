# tts-data — sinh dataset TTS (shop điện thoại) bằng ElevenLabs

Không phụ thuộc thư viện ngoài (Python ≥ 3.10, chỉ dùng thư viện chuẩn).

| File | Vai trò |
|---|---|
| `TEXT_SPEC.md` | Đề bài để sinh câu: phân bố chủ đề, luật viết dạng đọc |
| `texts.jsonl` | Câu cần đọc (Claude sinh theo TEXT_SPEC) — mẫu: `texts.example.jsonl` |
| `check_texts.py` | Kiểm câu: còn số/ký hiệu, trùng, quá dài, từ Latin ngoài lexicon, sai luật đọc; `--latin-stats` đếm độ phủ |
| `lexicon_latin.txt` | Danh sách đóng các từ Latin được phép trong `text` |
| `parts/*.jsonl` + `merge_parts.py` | Câu sinh theo nhóm category → ghép thành `texts.jsonl` (`--append` giữ id đã có audio) |
| `gen_audio.py` | Gọi ElevenLabs → wav 24 kHz mono, đóng gói metadata + JSONL OmniVoice |
| `.env.example` | Mẫu khai báo API key và voice id |

## Các bước

```bash
cd /home/dungnd/Dungnd/dev/project_II/tts-data
cp .env.example .env          # điền ELEVENLABS_API_KEY và ELEVENLABS_VOICE_ID

# 1. Kiểm câu (phải ĐẠT, 0 lỗi)
python3 check_texts.py texts.jsonl

# 2. Xem tốn bao nhiêu ký tự, quota còn bao nhiêu (không tốn credit)
python3 gen_audio.py --dry-run

# 3. Sinh thử 20 câu, NGHE kỹ: giọng, dấu, cách đọc tên máy và số
python3 gen_audio.py --limit 20 --out out_thu --speaker <ten_giong>

# 4. Sinh toàn bộ. Bị ngắt / lỗi mạng / hết quota → chạy lại đúng lệnh này, nó làm tiếp
python3 gen_audio.py --speaker <ten_giong>

# 5. Nghe các câu trong dataset/suspicious.csv, xoá wav hỏng, rồi đóng gói lại
python3 gen_audio.py --finalize-only --speaker <ten_giong>
```

Tuỳ chọn hay dùng: `--model eleven_v4|eleven_v3|eleven_flash_v2_5`, `--workers 3`
(tăng nếu gói cho phép nhiều request đồng thời), `--stability/--similarity/--style/--speed`
(bỏ trống = dùng thiết lập đã lưu của voice), `--seed` (giữ cố định cho giọng đồng đều).

Giữ **một model, một voice, một bộ thiết lập** cho cả dataset. Đổi giữa chừng thì xoá
`dataset/` và sinh lại, nếu không model TTS sẽ học một giọng lẫn lộn.

## Đầu ra (`dataset/`)
- `raw_audio/<id>.wav` + `metadata.csv` (`file_name|text|speaker`) — cùng định dạng bộ santa.
- `omnivoice_train.jsonl`, `omnivoice_dev.jsonl` — dùng thẳng cho bước tokenize của OmniVoice.
- `progress.jsonl` (request_id từng câu), `errors.jsonl`, `suspicious.csv` (tốc độ đọc lệch
  khỏi trung vị: thường là audio bị cụt, đọc lặp hoặc tự thêm chữ).

## Fine-tune OmniVoice
Làm theo `odyssey-project/OmniVoice/examples/README_SANTA_FT.md`, chỉ đổi đường dẫn:
bỏ qua `prepare_santa_jsonl.py` (đã có JSONL ở trên), trỏ bước `extract_audio_tokens`
vào `dataset/omnivoice_{train,dev}.jsonl`, và đặt thư mục token/exp mới để không đè bản santa.
