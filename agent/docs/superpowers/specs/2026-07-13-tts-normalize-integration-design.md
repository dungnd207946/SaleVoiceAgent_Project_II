# TTS normalize integration — design

**Date:** 2026-07-13
**Branch:** `feat/tts-normalize`
**Status:** approved-pending-review

## Vấn đề

Text tiếng Việt gửi sang TTS service hiện **không được normalize**. Hàm
`normalize_for_voice()` trong `voice/tts/_normalize.py` đã bị vô hiệu hóa bằng
`return text` ở dòng đầu (dòng 421) — trước đây TTS service tự normalize. Theo
định hướng mới (README của `experiments/tts/normalize`), việc normalize chuyển về
phía **hotline agent**, chạy **trước khi** gửi text sang TTS service (service nhận
text đã chuẩn hóa và synth as-is).

Call site đã đúng sẵn: `normalize_for_voice()` được gọi trước `tts.stream()` tại
`voice/voice_agent.py:276`, `voice/voice_agent.py:343`, `server/text_chat.py:144`.
Chỉ cần bật lại + thay logic bằng bản module mới.

## Ràng buộc

- **Self-contained trong hotline** — không `import` gì từ `experiments/tts/normalize`
  hay bên ngoài repo hotline.
- **Giữ `apply_normalize` + `load_normalize_map` (flat)** trong `_normalize.py` —
  `voice/tts/vieneu.py` và `voice/tts/elevenlabs.py` phụ thuộc vào chúng.
- Không tự chạy server/GPU; không tự chạy git (đưa lệnh cho user).

## Quyết định

1. **Chỉ dùng logic module mới** (không hợp nhất với bản normalize cũ). Chấp nhận
   mất: đọc ngày `15/7`, giờ `9:00`, phòng ghép `2PN1WC`, `/tháng`, khoảng số `-`.
2. **Gộp thẳng vào `_normalize.py`** — thay thân `normalize_for_voice`, không tạo
   sub-package.
3. **Giữ `"m"→"mét"`** trong `_UNIT_MAP` (data), kèm port lại guard chống đọc nhầm.

## Thiết kế

### 1. `src/noble_agent/voice/tts/_normalize.py`

**Giữ nguyên (dòng 1–71):** imports, `load_normalize_map(json_path)->dict[str,str]`
(flat), `apply_normalize(text, nmap, word_boundary)`. Cập nhật docstring đầu file
cho khớp hành vi mới.

**Thay (dòng 74–497):** xóa toàn bộ helper/regex chỉ phục vụ `normalize_for_voice`
cũ (đã orphan sau thay):
- `_number_to_vi`, `_expand_date`, `_expand_time`, `_expand_thousands`
- `_ROOM_ABBR`/`_ROOM_RE`, `_DATE_RE`, `_TIME_RANGE_RE`/`_TIME_RE`,
  `_PER_UNIT_SPOKEN`/`_PER_UNIT_RE`, `_NUM_RANGE_RE`, `_WORD_SLASH_RE`
- `_get_vi_map`/`_vi_map_cache`/`_expand_abbreviation`/`_ABBREV_RE`,
  `_VI_NORMALIZE_FILE`/`_PROJECT_ROOT` (cũ), `_PRICE_RE`/`_THOUSANDS_RE` cũ

Dán logic module mới (`experiments/tts/normalize/normalize.py`), điều chỉnh:
- `_int_to_vi` bản mới (đọc được ≥ tỷ + colloquial "rưỡi").
- `_format_amount`, `_expand_price`, `_expand_range`, `_expand_decimal`,
  `_expand_currency`, `_degroup_thousands`, `_expand_plain_number`.
- Đọc SĐT từng số (`_PHONE_RE`/`_read_phone`), mã căn `L11-2509`
  (`_CODE_RE`/`_read_code`), số La Mã sau keyword `quý I/2026`
  (`_ROMAN_RE`/`_expand_roman`), `TP.`→"thành phố" (`_TP_RE`).
- `normalize_for_voice()` mới với đúng thứ tự 16 bước của module mới.

**Tránh va tên** (cả hai module cùng đặt tên):
- Nested map loader của module mới đặt tên nội bộ khác, vd
  `_load_reading_abbrev(path)->tuple[dict,dict]` + `_ensure_maps()` + cache riêng —
  **không đè** `load_normalize_map` flat đang export cho vieneu/elevenlabs.
- Dedup `_LETTER_PRONUNCIATION`, `_spell_out`, `_UNIT_MAP`, `_SPECIAL_CHARS_RE`,
  `_URL_RE`, `_MARKDOWN_RE`, `_PAREN_ABBREV_RE`, `_PLAIN_NUMBER_RE`, `_DIGITS`,
  `_expand_currency` → dùng bản module mới, xóa bản cũ trùng tên.

**"m" trần + guard:** thêm `"m": "mét"` vào `_UNIT_MAP` (bản mới), và port guard
trailing-lookahead `(?![A-Za-zÀ-ỹĐđ])` vào `_UNIT_RE` để "5 mẫu"/"metro" không bị
đọc nhầm thành "năm mét ...". (Guard này bản cũ có, bản mới bỏ vì không có "m".)

### 2. `data/tts_normalize_vi.json` → format nested `{reading, abbrev}`

Nội dung = `reference/normalize_vi.json` (module mới), **hợp nhất thêm** các abbrev
bản cũ có mà bản mới thiếu (để không regress viết tắt):
`GPXD, UBND, GCNQSDĐ, TTĐC, TTPC, VAT, NOXH, DVKH, CSBH, PN, PK, WC, VS, available`.

File này hiện chỉ được `normalize_for_voice` cũ đọc → repurpose an toàn.
`normalize_for_voice` mới trỏ path này qua `NORMALIZE_PATH`
(`data/tts_normalize_vi.json`, giữ env override `TTS_NORMALIZE_PATH`).

### 3. Test — `tests/unit/`

Port `experiments/tts/normalize/tests/normalize_cases.json` vào hotline
(vd `tests/unit/data/normalize_cases.json`) + viết `test_normalize_for_voice.py`
chạy các case qua `normalize_for_voice`, neo hành vi để bắt regression về sau. Case
liên quan tính năng đã bỏ (ngày/giờ/phòng nếu có trong bộ case) sẽ được loại bỏ
hoặc chỉnh kỳ vọng cho khớp bản mới.

## Đánh đổi

| Mất | Được thêm |
|---|---|
| phòng ghép `2PN1WC` | SĐT đọc từng số, mã căn `L11-2509`, số La Mã `quý I/2026`, tiền "rưỡi", `TP.`→"thành phố" |

"PN/WC" đứng lẻ vẫn đọc đúng nhờ có trong abbrev JSON. "m" trần giữ lại.

**Bổ sung sau tích hợp (giữ nguyên toàn bộ rule của source, chỉ THÊM + tinh chỉnh):**

- **Per-unit slash** `/m²`, `/tháng`, `/căn`… → "**một** <đơn vị>"
  (`_PER_UNIT_SPOKEN`/`_PER_UNIT_RE`). Module mới bỏ; "VNĐ/m²" bị TTS đọc "việt nam
  đồng trên mờ bình phương" nên khôi phục. Trailing-guard thay `\b` (ký tự "²" là
  non-word). `anh/chị` và phân số `3/4` không bị đụng.
- **Số La Mã** thu charset `[IVXLCDM]`→`[IVX]` (giữ nguyên danh sách keyword của
  source). `quý I/IV`, `thế kỷ XXI` vẫn chạy; `Mục C`/`Quận C` không còn bị đọc
  thành "một trăm".
- **Ngày** `dd/mm/yyyy` + `ngày/mùng dd/mm` → "ngày X tháng Y [năm Z]" (port từ bản
  cũ; source không có). Không đụng phân số `3/4`.
- **Giờ** `HH:MM`, `HHhMM`, `HHh`, dải `8:00-11:30` → "X giờ [Y phút]" / "… đến …".
- **Khoảng số** `2-3`, `5-10` → "hai đến ba" (đọc luôn 2 đầu, kể cả 1 chữ số; chạy
  SAU dải tiền/diện tích của source nên "2-3 tỷ"/"50-70m2" vẫn giữ đơn vị).

Vòng bổ sung sau audit:
- **Dải giờ dạng h** `8h-11h`, `8h30-10h` → "… đến …" (`_TIME_H_RANGE_RE`).
- **Mét khẩu ngữ** `3m5` → "ba mét rưỡi" (`_METER_COLLOQ_RE`, trừ đuôi 2/3 để không đụng m²/m³).
- **Tiền khẩu ngữ có dấu cách** `1 tỷ 2`/`3 tỷ 5`/`12 triệu 5` → giá trị thật
  (`_MONEY_COLLOQ_RE`, guard danh từ đếm nên "3 tỷ 5 căn" không bị nhầm).
- **`k` = nghìn** `500k`/`2k5` (`_K_MONEY_RE`, chỉ `k` thường để né "4K").
- **`VIP`→"víp"** (reading JSON).
- **Dãy ID dài trần** ≥10 chữ số (CCCD `012345678901`) → đọc từng chữ số
  (`_ID_RE`, chạy trước degroup nên giá có dấu chấm `15.224.565.224` không bị đụng;
  giá trần <10 số vẫn đọc như số tiền). Guard đuôi cho phép dấu chấm câu.

Vòng datetime (audit riêng):
- **Ngày dấu `-`/`.`** (`02-07-2026`, `02.07.2026`) — `_DATE_RE` nhận `[/.\-]`, năm 4
  chữ số phân biệt với giá (nhóm 3 chữ số) nên không đụng `1.200.000`/`7.038 tỷ`.
- **Ngày trần `dd/mm`** (`31/12`, `20/11`) → ngày, chỉ khi ngày 13-31 (không nhầm
  phân số `3/4`/`1/2`); loại idiom `24/7`/`24/24`.
- **Tháng/quý + năm** (`Tháng 7/2026`, `Quý 3/2026`, `7/2026`) → "… N năm YYYY".
- **Năm/năm** (`2026/2027`) → "… đến …".
- **Giờ có giây** `08:30:15` → "… mười lăm giây".
- **Dải giờ `8-9h`** (vế đầu thiếu `h`) → "tám giờ đến chín giờ".
- **Tỉ số `N:M`** còn sót (không phải giờ hợp lệ) → "N trên M" (`1:100`→"một trên một trăm").

Vòng mã căn / mã hợp đồng / đô la:
- **`_CODE_RE` mở rộng**: token có **chữ HOA + số** (kèm `. / -` tùy chọn) → đọc
  literal (đánh vần chữ, từng chữ số). Chạy **sớm** (sau roman, trước maps/num-range)
  nên mã hợp đồng `HĐMB-2026-001`/`NCLB-2026-0123`/`2026/HĐMB` không bị bung viết tắt
  hay hiểu nhầm khoảng số; mã căn bắt đầu bằng số `2A-15`, không phân cách `CT1`/`05A`/`S1`
  cũng đọc được. Roman `IV/2026` chạy TRƯỚC code nên không bị nuốt. Chỉ dính khi có
  **cả chữ HOA lẫn số** → không đụng ngày `02-07-2026`, khoảng `2-3`, giờ `8h-11h`,
  project code trần `NCLB` (→ vẫn bung tên), `TPBank`/`BIDV` (→ reading).
- **`$`/`USD` → "đô la"** (`_USD_PREFIX/SUFFIX_RE` + `USD` trong abbrev JSON); trước
  đây `$` bị strip mất.

Còn tồn (chưa yêu cầu): #6 đọc số 1-chữ-số toàn cục (`2 phòng ngủ`, `5m`, `0 đồng`,
`8 giờ`), `14g30` (biến thể "g"), `OK`→"ô kê", phòng ghép `2PN`.

## Kiểm chứng

- `make test-unit` (hoặc pytest file test mới) — chạy được, không cần GPU/server.
- Không đụng vieneu/elevenlabs path (chỉ dùng lại `apply_normalize`/`load_normalize_map`).
- Không tự commit/git — đưa lệnh cho user.

## Ngoài phạm vi

- Không đổi call site (đã gọi `normalize_for_voice` đúng chỗ).
- Không đổi giao thức TTS service / WS client (`remote.py`, `hotline_ws.py`).
- Emoji stripping ở `hotline_ws.py` giữ nguyên.
