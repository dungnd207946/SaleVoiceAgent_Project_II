# Đặc tả bộ câu TTS — shop điện thoại

Tài liệu này là "đề bài" khi nhờ Claude sinh `texts.jsonl`. Sửa ở đây trước, sinh text sau.

## 1. Mục tiêu
- Một giọng nữ tư vấn viên shop điện thoại, xưng "em", gọi khách "anh/chị/mình".
- Quy mô đề xuất: **~4.000–4.500 câu ≈ 10–12 giờ** (bằng bộ santa đã FT OmniVoice ổn).
  Ước tính ~650–750 nghìn ký tự → kiểm tra quota gói ElevenLabs trước.
- Độ dài: trung vị ~30 từ, trải từ 3 đến 70 từ (≤ 70 từ để audio < 20 giây).
  **~8% câu ngắn 3–8 từ** ("Dạ vâng ạ, anh chờ em một chút nhé."). Agent voice nói rất nhiều
  câu đệm/xác nhận ngắn; không có mẫu thì model đọc câu ngắn sai nhịp hoặc ngân dài.
- Văn phong hội thoại có "dạ", "ạ", "nhé", "nha"; ~20% câu hỏi, ~10% câu cảm thán.
- ~15% câu có **liệt kê** (thông số, màu, quà, giấy tờ) cách nhau bằng dấu phẩy, để model học
  nhịp ngắt khi đọc danh sách — đây là dạng câu agent sinh nhiều nhất khi đọc kết quả tool.

## 2. Phân bố nội dung (category)
| category | tỷ lệ | ví dụ nội dung |
|---|---|---|
| chao_hoi_nhu_cau | 6% | chào, hỏi nhu cầu, ngân sách, hãng ưa thích, mua cho ai (bố mẹ, con đi học) |
| tu_van_chon_may | 11% | gợi ý máy theo nhu cầu: chụp ảnh, quay phim, chơi game, pin trâu, livestream, học sinh, người lớn tuổi (cả điện thoại phổ thông), gập/màn hình lớn, nhỏ gọn |
| so_sanh_may | 8% | so sánh hai/ba mẫu hoặc hai phiên bản cùng dòng (thường / Plus / Pro / Pro Max), đời cũ với đời mới |
| cau_hinh_thong_so | 11% | chip, RAM, bộ nhớ, thẻ nhớ; màn hình (công nghệ, kích thước, độ phân giải, tần số quét, độ sáng, kính); camera (số chấm, ống kính, zoom, quay video); pin, sạc có dây/không dây, củ sạc kèm hộp; kháng nước; trọng lượng, độ dày, chất liệu |
| phan_mem_tinh_nang | 4% | hệ điều hành và phiên bản, số năm cập nhật, tính năng AI, eSIM/hai SIM, NFC thanh toán, Face ID/vân tay, chuyển dữ liệu máy cũ |
| gia_ton_kho | 8% | giá từng phiên bản, chênh giá giữa dung lượng, màu còn hàng, chi nhánh còn máy, hàng sắp về, đặt trước máy mới ra mắt |
| khuyen_mai | 6% | giảm giá, quà "chọn một trong các quà", voucher, combo phụ kiện, ưu đãi thanh toán qua ngân hàng/ví, thời hạn khuyến mãi |
| tra_gop | 7% | trả góp không phần trăm, trả trước bao nhiêu, kỳ hạn, góp mỗi tháng, thẻ tín dụng, công ty tài chính, giấy tờ (căn cước), duyệt hồ sơ |
| thu_cu_doi_moi | 4% | định giá máy cũ, điều kiện máy cũ, trợ giá lên đời |
| may_cu_trung_bay | 3% | máy cũ, hàng trưng bày, tình trạng máy, phần trăm pin, bảo hành máy cũ, chênh giá với máy mới |
| bao_hanh_doi_tra | 7% | bảo hành chính hãng, một đổi một, hư gì đổi nấy, điều kiện đổi trả, gói bảo hành mở rộng, bảo hiểm rơi vỡ, trung tâm bảo hành |
| giao_hang_thanh_toan | 5% | giao nhanh, phí giao, kiểm tra hàng khi nhận, nhận tại cửa hàng, chuyển khoản, quẹt thẻ, ví điện tử, xuất hoá đơn |
| cua_hang_giu_hang | 4% | địa chỉ cửa hàng, giờ mở cửa, cửa hàng gần nhất, giữ máy, mã giữ hàng, hạn giữ, hẹn qua lấy |
| phu_kien_dich_vu | 3% | ốp, cường lực, sạc, cáp, tai nghe, đồng hồ, dán màn, chuyển dữ liệu, cài đặt |
| sua_chua_ky_thuat | 3% | thay pin, thay màn, lỗi thường gặp (nóng máy, hao pin, không sạc được) |
| danh_gia_hoi_dap | 2% | số sao, nhận xét khách đã mua, câu hỏi thường gặp |
| xu_ly_tu_choi | 3% | chê đắt, còn phân vân, so với chỗ khác, hàng xách tay |
| dieu_huong_hoi_thoai | 3% | chờ tra cứu, nghe chưa rõ xin nói lại, xác nhận lại thông tin, chưa có thông tin, ngoài phạm vi |
| chuyen_nguoi_ket_thuc | 2% | chuyển nhân viên, hẹn ra cửa hàng, xin/đọc lại số điện thoại, chào kết thúc |

Mỗi category phủ đủ các trục dưới đây; tên riêng và số phải lặp đủ nhiều lần thì model mới học được.

### 2.1. Hãng và dòng máy (mỗi dòng ≥ 15 câu, rải nhiều category)
Danh sách dưới đây ghi ở dạng viết. Khi đưa vào `text` thì đổi theo mục 3, ví dụ "Galaxy S" thành "Galaxy ét".
Đúng 15 hãng đang bán trên thegioididong.com/dtdd (đọc ngày 2026-11-02). Không dùng hãng ngoài danh sách này.
- **Apple**: iPhone 15, 16, 16 Plus, 16e, 17, 17e, 17 Pro, 17 Pro Max, Air, Duo, 18 Pro, 18 Pro Max.
- **Samsung**: Galaxy S25, S25 Ultra, S25 FE, S26, S26 FE, S26 Ultra; Z Fold7, Z Fold8, Z Fold8 Ultra, Z Flip7, Z Flip7 FE, Z Flip8; A07, A07s, A08, A17, A18, A26, A27, A37, A57.
- **Xiaomi**: Xiaomi 15T, 17, 17T, 17T Pro; Redmi Note 15, 15 Pro, 15 Pro+, 17, 17 Pro, 17 Pro Max; Redmi 15, 15C, 17, A7, A7 Pro; Poco C71, X8 Pro.
- **OPPO**: Find X10, X10 Pro Max, X9 Ultra, X9s, N6, N3 Flip; Reno13, Reno14 F, Reno15, Reno15 Pro, Reno15 F, Reno16, Reno16 F, Reno16 Pro; A6, A6 Pro, A6c, A6t, A6t Pro, A6x, A7 Pro.
- **vivo**: X300 Pro, X300 Ultra, X500, X500 Pro Max; V60, V60 Lite, V70, V70 FE, V80 Lite; Y05, Y05e, Y11d, Y21d, Y31d, Y39.
- **realme**: 15, 15 Pro, 15T, 16, 16 Pro, 16T; C01, C85, C85 Pro, C100, C100i, C100x; Note 80; P4 Power.
- **HONOR**: 400, 600, 600 Lite, 600 Pro, 600s, Play 10, X5c Plus, X6c, X7d, X8d, X9d.
- **TECNO**: Spark 50, Spark 50 Pro, Spark Go 3, Pova Curve 2.
- **Motorola**: Edge 60 Fusion, Edge 70, Edge 70 Fusion, Signature, Razr 60, Razr Fold, Moto G35, G37, G86, G06 Power, G57 Power.
- **nubia**: A36, A56, Air, V80 Design, V80 Max. **Nothing**: Phone 4a, 4a Pro, 4b.
- **Phổ thông**: Nokia 105 4G Pro, 110 4G Pro, 220 4G, HMD 105 4G; Masstel Fami 50, Fami 60s, Izi 10, Izi 10s, Izi T6; Mobell F209, F309, M179, M239, M331, M539, Rock 7; XPhone Hera S9.

### 2.2. Thuật ngữ bắt buộc phủ (mỗi mục ≥ 20 lần, ở nhiều vị trí trong câu)
- **Chip**: Apple a mười sáu đến a mười chín (Bionic, Pro), Snapdragon (tám Elite, tám Gen ba, bảy ét Gen ba…), Dimensity, Helio, Exynos, Tensor, Unisoc. Thêm nhân, xung nhịp, tiến trình na nô mét, gờ pê u.
- **Màn hình**: OLED, AMOLED, Dynamic AMOLED, Super Retina ích đê rờ, lờ tê pê o, lờ xê đê, i pê ét, tần số quét, độ sáng tối đa, hát đê rờ, độ phân giải (hát đê Plus, Full hát đê Plus, hai ca, Quad hát đê Plus), Dynamic Island, kính Ceramic Shield, Gorilla Glass, viền mỏng, đục lỗ, màn hình phụ (máy gập).
- **Camera**: chấm (mê ga pixel), góc rộng, góc siêu rộng, tele, tiềm vọng, macro, zoom quang học, zoom số, chống rung quang học, chống rung điện tử, chụp đêm, chân dung, xoá phông, quay bốn K, khung hình trên giây, camera selfie.
- **Pin, sạc**: mi li am pe giờ, sạc nhanh oát, sạc không dây, MagSafe, Qi hai, sạc ngược, củ sạc theo hộp, số giờ dùng, phần trăm sau bao nhiêu phút.
- **Bộ nhớ**: RAM, RAM ảo/mở rộng, bộ nhớ trong, thẻ nhớ micro ét đê, u ép ét, lờ pê đê đê rờ.
- **Kết nối**: năm gờ, bốn gờ, Wi-Fi, Bluetooth, en ép xê, gờ pê ét, eSIM, hai SIM, Nano SIM, cổng Type xê/Lightning, jack tai nghe ba phẩy năm, hồng ngoại.
- **Thiết kế, độ bền**: kháng nước bụi i pê sáu mươi tám/sáu mươi bảy/năm mươi bốn, khung titan, khung nhôm, mặt lưng kính, trọng lượng gam, độ dày mi li mét.
- **Phần mềm**: iOS, Android, One u i, HyperOS, ColorOS, Funtouch o ét, Realme u i, MagicOS, số năm cập nhật, Galaxy a i, Apple Intelligence, Gemini, khoanh tròn để tìm kiếm, ét Pen, Face i đê, vân tay dưới màn hình/cạnh viền.
- **Bán hàng**: chính hãng vê en a, hàng xách tay, máy cũ, trưng bày, kích hoạt bảo hành điện tử, i em e i, nguyên seal, hộp có những gì.
- **Tài chính, thanh toán**: Visa, Mastercard, gi xê bê, công ty tài chính (Home Credit, ép e Credit, hát đê Saison, Shinhan Finance, Mirae Asset, Samsung Finance Plus), mua trước trả sau (Kredivo, Home PayLater), ví (MoMo, ZaloPay, vê en Pay, Apple Pay, Samsung Pay), mã quy rờ, tên các ngân hàng (đọc theo `tts_normalize_vi.json`).

### 2.3. Phân bố số
- Giá: phủ đủ các mức từ dưới một triệu (máy phổ thông, phụ kiện) đến trên năm mươi triệu (máy gập). Có các đuôi chín trăm chín mươi nghìn, năm trăm nghìn, chẵn triệu, rưỡi.
- Tất cả số từ không đến chín mươi chín, mỗi số ≥ 10 lần. Có "mốt", "lăm", "lẻ", "không trăm", "nghìn", "triệu", "tỷ" và số thập phân với "phẩy".
- Số điện thoại, hotline, mã giữ hàng: mỗi loại ≥ 40 câu.
- Ngày, giờ, khoảng giờ: ≥ 60 câu.
- Địa chỉ có số nhà, đường, phường, quận, tỉnh: ≥ 40 câu.

## 3. Luật viết ở DẠNG ĐỌC (bắt buộc)
TTS chỉ học được cách đọc mà nó đã thấy. Lúc chạy, agent đưa text qua `normalize_for_voice()`
(`agent/src/noble_agent/voice/tts/_normalize.py` + `agent/data/tts_normalize_vi.json`) rồi mới
gửi TTS. Vì vậy phải giữ **bất biến**: `normalize_for_voice(raw_text) == text` cho mọi câu.
Lệch là model gặp chữ lạ lúc chạy.

> ⚠️ Bộ chuẩn hoá hiện tại là bản của domain BĐS. Nó **chưa** cho ra các dạng đọc dưới đây
> (xem mục 5). Bảng dưới là **chuẩn đích**: sửa bộ chuẩn hoá theo bảng, không sửa bảng theo
> bộ chuẩn hoá.

### 3.1. Số
| Luật | Viết | Không viết |
|---|---|---|
| Số đếm đọc đủ | hai mươi lăm, một trăm hai mươi tám, hai nghìn không trăm hai mươi lăm | hai lăm, trăm hai tám |
| Đơn vị 1 / 5 / 4 sau hàng chục | hai mươi mốt, hai mươi lăm, hai mươi bốn | hai mươi một, hai mươi năm, hai mươi tư |
| Hàng chục bằng 0 | một trăm lẻ năm, hai nghìn không trăm năm mươi | một trăm linh năm |
| Nghìn | nghìn | ngàn |
| Thập phân | sáu phẩy chín, tám phẩy hai mươi lăm | sáu chấm chín |
| Phiên bản (dấu chấm) | Bluetooth năm phẩy ba, UFS bốn | năm chấm ba |
| Khoảng | từ sáu đến tám triệu, tám giờ đến hai mươi hai giờ | 6-8 triệu |
| Số một chữ số cũng viết chữ | hai SIM, một đổi một, Pixel chín a | 2 SIM, 1 đổi 1 |

### 3.2. Tiền
| Luật | Viết | Không viết |
|---|---|---|
| Giá đầy đủ | hai mươi tám triệu chín trăm chín mươi nghìn đồng | 28.990.000đ, 28,99tr |
| Nửa đơn vị | một triệu rưỡi, hai tỷ rưỡi | một triệu năm trăm nghìn (khi raw là 1,5 triệu) |
| k | năm trăm nghìn | 500k |
| Theo tháng | một triệu năm trăm bảy mươi chín nghìn năm trăm đồng một tháng | /tháng |
| Giảm | giảm bảy phần trăm, rẻ hơn hai triệu | -7%, -2tr |

### 3.3. Đơn vị và thông số
| Loại | Viết | Không viết |
|---|---|---|
| Phần trăm | không phần trăm, mười lăm phần trăm | 0%, 15% |
| Dung lượng | một trăm hai mươi tám gi ga bai, một tê ra bai | 128GB, 1TB |
| RAM | tám gi ga bai RAM | 8GB RAM, tám gi ram |
| Cặp RAM/bộ nhớ | tám gi ga bai RAM, hai trăm năm mươi sáu gi ga bai bộ nhớ | 8GB/256GB |
| Pin | năm nghìn mi li am pe giờ | 5000mAh |
| Sạc | sáu mươi lăm oát | 65W |
| Màn hình | sáu phẩy bảy inch, một trăm hai mươi héc | 6.7", 120Hz |
| Độ sáng | hai nghìn nit | 2000 nits |
| Độ phân giải | một nghìn ba trăm hai mươi nhân hai nghìn tám trăm sáu mươi tám pixel; hai ca; bốn ca | 1320 x 2868, 2K |
| Camera | bốn mươi tám mê ga pixel | 48MP, 48 MP |
| Zoom | zoom quang học năm lần, zoom số một trăm lần | 5x, 100X |
| Video | quay bốn ca sáu mươi khung hình trên giây | 4K 60fps |
| Xung nhịp | ba phẩy hai gi ga héc | 3.2GHz |
| Tiến trình | ba na nô mét | 3nm |
| Kích thước | tám phẩy hai mươi lăm mi li mét, hai trăm hai mươi bảy gam | 8.25mm, 227g |
| Nhiệt độ | bốn mươi độ xê | 40°C |
| Thời lượng | ba mươi ba giờ xem video, sạc năm mươi phần trăm trong ba mươi phút | 33h, 50%/30p |

### 3.4. Bảng chữ cái — một cách đọc duy nhất cho mỗi chữ
Mọi chữ cái **đứng riêng** (viết tắt, chữ cái đơn trong tên máy/chip, mã) đều viết bằng tên
đọc dưới đây, **không để chữ Latin trần**. Lý do: ElevenLabs tự chọn đọc kiểu Anh hay Việt
(S → "ét xì", A → "ây", Y → "oai"), và model sẽ học đúng sự lẫn lộn đó.

| A | B | C | D | Đ | E | F | G | H | I | J | K | L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a | bê | xê | đê | đê | e | ép | gờ | hát | i | gi | ca | lờ |

| M | N | O | P | Q | R | S | T | U | V | W | X | Y | Z |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| em | en | o | pê | quy | rờ | **ét** | tê | u | vê | vê kép | ích | i dài | dét |

S **luôn** là "ét", không bao giờ "ét xì".

### 3.5. Viết tắt, tên riêng, ký hiệu
| Loại | Viết | Không viết |
|---|---|---|
| Viết tắt đánh vần (theo 3.4) | u ét bê, en ép xê, năm gờ, bốn gờ, i pê sáu mươi tám, gờ pê ét, lờ xê đê, a i, hát đê Plus, i em e i | USB, NFC, 5G, IP68, GPS, LCD, AI, HD+, IMEI |
| Viết tắt đọc như từ (danh sách đóng) | RAM, ROM, SIM, eSIM, OLED, AMOLED, Wi-Fi, iOS | — |
| Tên hãng, dòng, công nghệ | giữ chữ Latin, viết **Hoa đầu, không viết HOA toàn bộ**: Oppo, Vivo, Realme, Honor, Tecno, Poco, iPhone, Galaxy, Pro Max, Ultra, Snapdragon, Dimensity | OPPO, HONOR, POCO (HOA toàn bộ bị đánh vần) |
| Số trong tên máy | iPhone mười sáu Pro Max, Galaxy ét hai mươi lăm Ultra, Redmi Note mười bốn Pro Plus | iPhone 16, S25, Note 14 Pro+ |
| Chữ dính số trong tên máy | tách ra, chữ theo 3.4: Galaxy a năm mươi sáu, Galaxy dét Fold bảy, Reno mười ba ép, Vivo i dài mười chín ét, Pixel chín a, Find ích tám, Redmi mười bốn xê | A56, Z Fold7, Reno13 F, Y19s, 9a, X8, 14C |
| Chip | Apple a mười tám Pro, Snapdragon tám Gen ba, Snapdragon bảy ét Gen ba, Dimensity chín nghìn bốn trăm, Helio gờ chín mươi chín, Exynos hai nghìn năm trăm, Tensor gờ bốn | A18 Pro, 8 Gen 3, 7s Gen 3, G99 |
| Phiên bản hệ điều hành | iOS mười tám, Android mười lăm, One u i bảy, HyperOS hai | iOS 18, One UI 7 |
| Cổng | cổng Type xê, u ét bê Type xê | USB-C, Type-C |
| Dấu + trong tên | Plus: Pro Plus, Full hát đê Plus, hát đê rờ mười Plus | Pro+, FHD+, HDR10+ |
| Ký hiệu | và, trên, cộng (chỉ khi là phép cộng) | &, /, + |
| Số điện thoại, hotline | đọc từng chữ số: không chín không một hai ba bốn năm sáu bảy; một chín không không… | 0901234567, 1900 xxx |
| Mã giữ hàng, IMEI | đọc từng ký tự, chữ cái theo tên tiếng Việt (a, bê, xê, đê…) | mã viết liền |
| Ngày, giờ | hai mươi ba giờ năm mươi chín phút ngày ba mươi tháng mười một | 23:59 30/11 |
| Địa chỉ | số một trăm hai mươi ba xẹt bốn đường Nguyễn Trãi, phường…, quận một, thành phố Hồ Chí Minh | 123/4, P., Q.1, TP.HCM |

- Tên tiếng Anh thông dụng (camera, selfie, zoom, chip, flagship, gaming, voucher, combo,
  online) viết Latin như thường. Mỗi từ Latin xuất hiện phải luôn được viết một cách duy nhất.
- Không dùng dấu `|` (làm hỏng metadata.csv), không xuống dòng trong một câu.
- Kết thúc câu bằng `.` `?` `!`.
- `raw_text` ghi câu gốc **dạng agent sẽ thật sự sinh ra** (giống dữ liệu DB/LLM: `128GB`,
  `S25 Ultra`, `28.990.000đ`, `5000mAh`, `IP68`, `8GB/256GB`) — đó chính là test case cho bộ chuẩn hoá.

### 3.6. Từ Latin nguyên khối (tên hãng, dòng máy, công nghệ)
Model chỉ đọc đúng một từ Latin khi (a) ElevenLabs đọc từ đó đúng và ổn định, (b) từ đó lặp
đủ nhiều trong bộ câu, (c) lúc chạy agent viết đúng y như vậy. Vì thế:
- Mỗi từ Latin phải nằm trong **danh sách cho phép** [`lexicon_latin.txt`](lexicon_latin.txt)
  (`check_texts.py` báo lỗi từ ngoài danh sách) và xuất hiện **≥ 20 lần** (`--latin-stats`).
- Tên ngân hàng viết theo dạng đọc, chữ cái theo 3.4: việt com bank, tếch com bank, sa com bank,
  a gri bank, việt tin bank, vê pê bank, tê pê bank, em bê bank, bê i đê vê, a xê bê.
- Trước khi sinh hàng loạt, sinh một lô nghe thử chứa đủ mọi từ trong danh sách. Từ nào
  ElevenLabs đọc sai hoặc lúc đúng lúc sai thì **phiên âm hẳn ra tiếng Việt**, giống cách
  `tts_normalize_vi.json` đang làm với tên ngân hàng (Techcombank → "tếch com bank"). Phiên âm
  ghi đồng thời vào `text` và vào map đọc của bộ chuẩn hoá.
- Danh sách cần nghe kỹ: Xiaomi, Redmi, Poco, Oppo, Vivo, Realme, Honor, Tecno, Infinix,
  Nubia, Xperia, Pixel, HyperOS, ColorOS, MagicOS, Dimensity, Exynos, Helio, Unisoc, Tensor,
  AMOLED, Kredivo, Shinhan, Mirae, ZaloPay, MoMo.
- Tên máy mới chưa có trong bộ câu (ra mắt sau khi train): model sẽ đoán theo chữ cái, không
  bảo đảm đúng → thêm phiên âm vào map đọc của bộ chuẩn hoá, không cần train lại.

### 3.7. Đã chốt (2026-11-02)
1. Dung lượng: **"gi ga bai"**, **"tê ra bai"**.
2. **S luôn đọc "ét"**, không bao giờ "ét xì" → mọi chữ cái đứng riêng viết bằng tên đọc ở 3.4.
3. Đánh vần viết tắt: **"en ép xê"** (N = en, M = em).

## 4. Định dạng file
`texts.jsonl`, mỗi dòng một object:
```json
{"id": "dt_00001", "text": "<dạng đọc>", "raw_text": "<dạng viết>", "category": "tra_gop"}
```
id dạng `dt_` + 5 chữ số, tăng dần, không trùng. Kiểm bằng `python3 check_texts.py texts.jsonl`.

## 5. Việc kèm theo (ngoài bộ câu)
- **Sửa bộ chuẩn hoá của agent cho domain điện thoại** — đã chạy thử, hiện ra:
  - `256GB` → "hai năm sáu gờ bê" (đọc từng chữ số), `S25` → "ét hai năm", `A18 Pro` → "a một tám Pro".
  - `5000mAh`, `120Hz`, `60fps`, `5x`, `Y19s`, `Fold7`, `9a` giữ nguyên (không đọc).
  - Số một chữ số không đổi: "2 SIM", "1 đổi 1", "trả góp 0 phần trăm", "HyperOS 2".
  - `OPPO` → "o pê pê o", `RAM` → "rờ a mờ", `FHD+` → "ép hát đê+", `USB-C` → "u ét bê-C".
  - Map viết tắt còn toàn mục BĐS (PN, WC, HĐMB, căn hộ…), không có mục điện thoại.
  - Bảng chữ cái `_LETTER_PRONUNCIATION` lệch 3.4: M → "mờ", N → "nờ" (phải "em", "en").
    S → "ét" đã đúng. Chữ cái đơn trong tên máy ("Galaxy S", "Z Fold") hiện không được đổi.
- **Thêm vào `check_texts.py`**:
  - Kiểm `normalize_for_voice(raw_text) == text` (sau khi sửa bộ chuẩn hoá).
  - Mọi từ Latin trong `text` phải nằm trong một danh sách từ cho phép.
  - Bộ đếm phủ cho mục 2.1–2.3.
  - `MIN_WORDS` hạ xuống 3 cho khớp mục 1.
