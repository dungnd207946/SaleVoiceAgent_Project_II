# Thống kê dữ liệu public_web — 45 dự án aina_prod (local)

Đo ngày 01/10/2026 trên DB và Qdrant local, sau lượt dựng lại hồ sơ (bỏ hạn 24 tháng lúc nạp, khớp tên không dấu). Cột có `a → b` là trước → sau lượt dựng lại; dự án NOXH mới thêm nên chỉ có số sau.

## Kho bài (Postgres `public_data.web_pages`)

| Nguồn tìm bài | ok | không liên quan | tải lỗi | cần trình duyệt | Tổng | Tỷ lệ ok |
|---|---|---|---|---|---|---|
| Gemini grounding | 1036 | 548 | 240 | 111 | 1935 | 53% |
| Sitemap/RSS báo | 967 | 344 | 2 | 1 | 1314 | 73% |
| **Tổng** | 2003 | 892 | 242 | 112 | 3249 | 61% |

Tuổi bài ok (theo ngày đăng): ≤30 ngày 1.064 (53%) · 1–12 tháng 354 (18%) · 12–24 tháng 256 (13%) · >24 tháng 329 (16%).

Domain nhiều bài ok nhất: cafef.vn 500 · baoxaydung.vn 118 · thanhnien.vn 99 · dantri.com.vn 89 · vietnamnet.vn 72 · batdongsan.baoxaydung.vn 53 · tuoitre.vn 43 · market.vinhomes.vn 35 · cafeland.vn 35 · vneconomy.vn 35.

## Qdrant `public_web`

| Loại (`kind`) | Số point |
|---|---|
| ho_so_du_an | 445 |
| du_an_lan_can | 122 |
| ban_tin_thi_truong | 10 |

## Theo từng dự án

- **Mục**: số mục hồ sơ. **Bài**: bài khớp dự án (theo tên hoặc địa danh). **Gắn tên**: bài gắn đúng tên dự án.
- **Nguồn**: số link trích trong hồ sơ. **Báo %**: tỷ lệ link thuộc danh sách báo whitelist. **Tuổi**: tuổi trung vị nguồn (ngày).
- **Thẻ**: số thẻ dự án lân cận cùng khu vực.

| Dự án | Mục | Bài | Gắn tên | Nguồn | Báo % | Tuổi | Mục giá | Thẻ |
|---|---|---|---|---|---|---|---|---|
| ALLUVIA CITY | 6 → 9 | 51 → 72 | 12 → 12 | 5 → 14 | 14 | 256 | có | 8 |
| ALUMI | 9 → 10 | 50 → 71 | 3 → 3 | 8 → 8 | 0 | 391 | có | 8 |
| Chung cư thu nhập thấp Đại Địa Bảo – Block C | 7 | 24 | 0 | 14 | 43 | 177 | có | 4 |
| IMPERIA THE REGENT | 7 → 6 | 11 → 14 | 2 → 3 | 8 → 7 | 86 | 9 | có | 1 |
| Khu NOXH Tân Lập | 11 | 20 | 6 | 18 | 22 | 136 | có | 1 |
| LUMIERE OCEAN CREST | 10 → 6 | 39 → 56 | 0 → 0 | 11 → 12 | 0 | 268 | có | 4 |
| LUMIÈRE ESSENCE PEAK | 5 → 5 | 36 → 53 | 0 → 0 | 2 → 9 | 0 | 97 | có | 4 |
| LUMIÈRE HANOI SEASONS GARDEN | 10 → 11 | 19 → 32 | 4 → 6 | 10 → 15 | 33 | 122 | có | 2 |
| LUMIÈRE ORIENT PEARL | 8 → 7 | 25 → 60 | 4 → 5 | 7 → 12 | 8 | 703 | có | 3 |
| LUMIÈRE SPRINGBAY | 8 → 7 | 38 → 57 | 2 → 4 | 16 → 14 | 14 | 395 | có | 4 |
| MASTERI ERA LANDMARK | 7 → 11 | 39 → 56 | 4 → 4 | 8 → 11 | 0 | 315 | có | 4 |
| MASTERI GRAND COAST | 8 → 7 | 39 → 56 | 2 → 2 | 19 → 8 | 0 | 342 | có | 4 |
| MASTERI SKY QUARTER | 12 → 11 | 46 → 59 | 6 → 6 | 9 → 18 | 11 | 386 | có | 7 |
| MASTERI TRINITY SQUARE | 11 → 10 | 37 → 54 | 0 → 0 | 15 → 10 | 0 | 325 | có | 4 |
| NOBLE CRYSTAL LONG BIÊN | 7 → 8 | 35 → 75 | 3 → 4 | 5 → 8 | 0 | 564 | có | 4 |
| NOBLE CRYSTAL RIVERSIDE | 6 → 7 | 18 → 29 | 13 → 17 | 11 → 15 | 27 | 369 | có | 2 |
| NOBLE CRYSTAL TÂY HỒ | 8 → 10 | 21 → 63 | 9 → 20 | 12 → 13 | 15 | 838 | có | 5 |
| NOBLE PALACE HẠ LONG | 8 → 8 | 12 → 21 | 1 → 1 | 9 → 14 | 64 | 86 | có | 3 |
| NOBLE PALACE LONG BIÊN | 5 → 12 | 40 → 80 | 0 → 2 | 3 → 8 | 25 | 453 | có | 6 |
| NOBLE PALACE TÂY HỒ | 8 → 7 | 28 → 67 | 5 → 13 | 15 → 8 | 50 | 422 | có | 6 |
| NOBLE PALACE TÂY THĂNG LONG | 8 → 3 | 49 → 68 | 4 → 9 | 12 → 12 | 8 | 589 | không | 7 |
| NOXH Bcons City Life | 10 | 23 | 0 | 7 | 86 | 52 | có | 0 |
| NOXH CT3 Kim Chung | 8 | 16 | 1 | 12 | 42 | 343 | có | 1 |
| NOXH Lý Thường Kiệt (Phú Thọ DMC) | 5 | 23 | 9 | 11 | 36 | 181 | không | 0 |
| NOXH Sunrise Home Ngọc Hồi | 11 | 34 | 0 | 12 | 33 | 102 | có | 2 |
| NOXH Thượng Thanh (Him Lam Thượng Thanh) | 12 | 20 | 11 | 15 | 13 | 376 | có | 0 |
| NOXH Uy Nỗ – Calyx Residence | 8 | 93 | 0 | 16 | 19 | 595 | có | 3 |
| NOXH Việt Hương Lakeside (Nam cầu Cẩm Lệ) | 8 | 14 | 0 | 9 | 22 | 195 | có | 1 |
| NOXH VSIP Bắc Ninh | 5 | 32 | 1 | 17 | 47 | 242 | có | 7 |
| SUNSHINE BAY RETREAT VUNG TAU | 8 → 24 | 7 → 15 | 2 → 2 | 7 → 14 | 43 | 259 | có | 2 |
| SUNSHINE LEGEND CITY | 8 → 5 | 39 → 56 | 5 → 5 | 15 → 7 | 0 | 358 | có | 3 |
| SUNSHINE RIVER PARK | 12 → 15 | 20 → 48 | 9 → 12 | 16 → 16 | 56 | 124 | có | 5 |
| SUNSHINE SKY CITY | 4 → 7 | 17 → 30 | 6 → 9 | 11 → 18 | 22 | 381 | có | 3 |
| THE FULLTON | 5 → 5 | 49 → 70 | 1 → 1 | 4 → 5 | 0 | 324 | có | 8 |
| THE HARBOR SKYLINE | 6 → 15 | 32 → 55 | 2 → 6 | 14 → 19 | 21 | 245 | có | 5 |
| THE PARKLAND | 6 → 8 | 43 → 60 | 5 → 5 | 6 → 4 | 0 | 201 | có | 4 |
| VINHOMES GLOBAL GATE | 9 → 12 | 61 → 104 | 18 → 29 | 24 → 20 | 5 | 728 | có | 4 |
| VINHOMES GLOBAL GATE HẠ LONG | 10 → 12 | 44 → 50 | 33 → 34 | 4 → 10 | 0 | 263 | không | 0 |
| VINHOMES GOLDEN CITY | 8 → 10 | 25 → 36 | 15 → 20 | 17 → 20 | 0 | 378 | có | 2 |
| VINHOMES GREEN PARADISE | 12 → 24 | 27 → 36 | 16 → 20 | 21 → 22 | 59 | 11 | có | 0 |
| VINHOMES HẢI VÂN BAY | 15 → 9 | 25 → 38 | 13 → 15 | 19 → 6 | 17 | 609 | có | 1 |
| VINHOMES OCEAN PARK 2 | 10 → 24 | 49 → 86 | 29 → 60 | 19 → 32 | 0 | 361 | có | 3 |
| VINHOMES OCEAN PARK 3 | 12 → 5 | 53 → 82 | 26 → 44 | 19 → 9 | 0 | 210 | có | 3 |
| VINHOMES ROYAL ISLAND | 10 → 21 | 43 → 70 | 34 → 55 | 14 → 16 | 25 | 367 | có | 5 |
| VINHOMES WONDER CITY | 8 → 9 | 46 → 60 | 30 → 36 | 26 → 21 | 5 | 575 | không | 6 |

## Search (giống agent: chỉ theo text, top 5 mỗi `kind`)

| Câu hỏi | Kết quả |
|---|---|
| Hỏi về một dự án (3 câu/dự án, 135 câu) — top 1 đúng dự án | 119/135 (88%) |
| Hỏi về một dự án — có đúng dự án trong top 5 | 135/135 (100%) |
| "Dự án nào gần X" — top 5 thẻ có thẻ cùng khu vực | 27/45 (60%) |
| "Dự án nào gần X" — top 5 thẻ có thẻ của chính X | 20/45 |
| "Dự án nào gần X" — mục "Dự án lân cận" của X trong top 5 hồ sơ | 25/45 (55%) |
| Hồ sơ có mục "Dự án lân cận" | 38/45 |

## Vấn đề còn lại

1. Lượt viết cuối làm rơi mục: Noble Palace Tây Thăng Long 8 → 3 (mất mục giá), Vinhomes Ocean Park 3 12 → 5, Vinhomes Hải Vân Bay 15 → 9, Sunshine Legend City 8 → 5.
2. "Dự án nào gần X" thiếu chính xác: thẻ không nhắc tên dự án ở gần; địa danh thẻ sai dạng (tiếng Anh, cả địa chỉ, rỗng); thẻ không phải dự án nhà ở (grand world, bến thành - cần giờ, vincom imperia, sunshine center).
3. Dự án gần như không có bài riêng (hồ sơ chủ yếu nói về khu vực): Lumière Ocean Crest, Lumière Essence Peak, Masteri Trinity Square, NOXH Bcons City Life, NOXH Sunrise Home Ngọc Hồi, NOXH Việt Hương Lakeside, NOXH Uy Nỗ – Calyx Residence, Chung cư Đại Địa Bảo.
4. Bản tin có cả tin tiêu cực (vd thanh tra dự án Nam Long) — chưa chốt giữ hay bỏ.
5. 354 trang tải lỗi hoặc cần trình duyệt (facebook, baomoi, laodong, moovitapp…) — fetch trình duyệt đang tắt.
