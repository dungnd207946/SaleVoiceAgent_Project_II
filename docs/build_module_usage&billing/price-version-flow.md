# `billing.price_version` — lưu gì và luồng đặt giá chạy thế nào

Đã đổi tên `price_book` → `price_version`. `status` chỉ còn **`active` | `inactive`**,
mặc định `inactive`. Đã kiểm chứng lại trên DB: tổng vẫn **4.030,30 đ**.

## 1. Ba bảng, ba câu hỏi khác nhau

| Bảng | Trả lời câu | Một dòng nghĩa là |
|---|---|---|
| `price_version` | **Có những bộ giá nào?** | "Bộ giá tháng 8/2026, đơn vị VND" |
| `price_item` | **Trong bộ đó, mỗi thứ giá bao nhiêu?** | "input token của gemini-2.5-flash: 2.500 đ / 1M" |
| `tenant_price_version` | **Khách nào dùng bộ nào, từ khi nào?** | "green_park dùng bộ v2 từ 01/09/2026" |

`price_version` **không chứa một con số giá nào** — nó chỉ là cái tên và cái vỏ.
Giá nằm ở `price_item`, mỗi dòng một loại đơn vị.

## 2. Dữ liệu thật trông thế nào

**`price_version`** — mỗi dòng là một bộ giá:

| id | code | name | currency | status | is_default |
|---|---|---|---|---|---|
| 1 | `pv_2026_08` | Bộ giá 08/2026 | VND | `inactive` | false |
| 2 | `pv_2026_09` | Bộ giá 09/2026 (tăng TTS) | VND | `active` | true |

**`price_item`** — 11 dòng cho mỗi bộ (đúng số ô `pricing_basis` khai):

| price_version_id | component | purpose | provider | model | metric | unit_price | per_units |
|---|---|---|---|---|---|---|---|
| 2 | llm | | gemini | gemini-2.5-flash | input_tokens | 2500 | 1000000 |
| 2 | llm | | gemini | gemini-2.5-flash | output_tokens | 10000 | 1000000 |
| 2 | llm | | gemini | gemini-2.5-flash | cache_read_tokens | 625 | 1000000 |
| 2 | llm | | gemini | gemini-2.5-flash | cache_write_tokens | 0 | 1000000 |
| 2 | stt | conversation | | | audio_sec | 10 | 1 |
| 2 | stt | stream | | | wall_ms | **0** | 60000 |
| 2 | tts | | | | units | 2 | 1 |
| 2 | vad | | | | audio_sec | 1 | 1 |
| 2 | speaker_verify | | | | audio_sec | 5 | 1 |
| 2 | call | | | | audio_sec | 500 | 60 |
| 2 | embed | | gemini | gemini-embedding-001 | units | 5 | 1 |

Ô trống = `''` = "áp cho mọi giá trị". Đọc dòng `call` là: *"500 đ cho mỗi 60 giây
`audio_sec`, bất kể purpose/provider/model nào"*.

**`tenant_price_version`** — lịch sử, đây là **nguồn sự thật khi tính tiền**:

| tenant_id | price_version_id | effective_from | effective_to |
|---|---|---|---|
| green_park | 1 | 2026-08-01 | 2026-09-01 |
| green_park | 2 | 2026-09-01 | `NULL` ← còn hiệu lực |
| du_test | 2 | 2026-08-01 | `NULL` |

`effective_to = NULL` nghĩa là đang chạy. Hai khoảng của cùng một tenant **không
chồng nhau được** — có `EXCLUDE USING gist` chặn ở DB, vì chồng nhau thì hai bộ giá
cùng hiệu lực và số tiền ra tuỳ Postgres chọn dòng nào trước.

## 3. Luồng đặt giá — 5 bước

```
① TẠO          POST /admin/billing/price-versions
               → status = 'inactive'. Chưa ai bị ảnh hưởng.

② NHẬP GIÁ     POST /admin/billing/price-versions/{id}/items   (11 lần)
               Form sinh từ pricing_basis nên không nhập thiếu ô nào.
               Miễn phí thì điền 0, ĐỪNG để trống.

③ PREVIEW      GET  /admin/billing/price-versions/{id}/preview?tenant=green_park
               Áp bộ giá lên usage 30 ngày qua trong một transaction rồi ROLLBACK.
               Trả về "1.284.600 đ, hiện tại 1.085.100 đ, +18,4%".
               KHÔNG ghi một dòng nào.

④ KÍCH HOẠT    POST /admin/billing/price-versions/{id}/activate
               Cửa chặn: nếu còn cặp (component, metric) nào trong pricing_basis
               chưa có dòng giá → 409 BANG_GIA_CON_LO, KHÔNG cho active.
               Không có cửa này thì một bộ giá thiếu ô = âm thầm miễn phí.
               → status = 'active'

⑤ GÁN CHO KHÁCH POST /admin/billing/tenants/{tenant}/price-version
               Đóng khoảng cũ (effective_to = mốc mới) và mở khoảng mới cùng
               một mốc — không hở, không chồng. Bộ giá cũ → status 'inactive'.
```

Sau đó job `billing.rate_usage()` chạy hằng ngày, mỗi event tự tìm bộ giá đúng
theo `occurred_at` của nó và **chốt đơn giá vào `rated_usage`**.

## 4. Vì sao `active`/`inactive` là đủ — và MỘT cái bẫy nó tạo ra

Bạn đúng: `draft` và `archived` không thêm thông tin gì.
- `draft` ≡ `inactive` (chưa áp)
- `archived` ≡ `inactive` (không còn áp)

Thứ mà `archived` tưởng như giữ được — "bộ này từng được dùng" — **đã nằm ở
`tenant_price_version`** (có khoảng hiệu lực đã đóng) và ở `rated_usage.price_version_id`.
Suy ra được, nên không cần một status riêng. Đã bỏ.

### ⚠️ Nhưng nó tạo một cái bẫy tính tiền, và tôi đã đóng

Tháng 8 dùng bộ v1. Sang tháng 9 chuyển v2, v1 thành `inactive`. Giờ có người tính
lại tháng 8 (re-run cửa sổ 48h, hoặc sửa dữ liệu rồi tính lại):

- Nếu `resolve_price_version()` đòi `status = 'active'` → **không tìm thấy v1**, rơi
  về `is_default` (đang là v2) → **tháng 8 ra một số tiền khác**. Một kỳ đã chốt bị
  viết lại, không lỗi nào phát ra, và số mới trông hoàn toàn hợp lý.

Nên `resolve_price_version()` **cố ý không đọc `status`**. Nó chỉ đọc khoảng hiệu lực
trong `tenant_price_version`. Đã kiểm chứng: đặt v1 thành `inactive` rồi tính lại
toàn bộ → vẫn ra đúng **4.030,30 đ**.

Chốt lại phân vai:

| | Dùng để làm gì | KHÔNG dùng để |
|---|---|---|
| `status` | nhãn cho giao diện: "bộ nào đang dùng" | tính tiền |
| `effective_from`/`to` | tính tiền: bộ nào áp cho thời điểm nào | — |

## 5. Chốt thứ hai: bộ giá đã sinh ra tiền thì KHÔNG sửa được

Có version rồi mà vẫn sửa được `price_item` của bộ đang dùng thì version thành vô
nghĩa: sửa 2.500 → 3.000 rồi chạy lại `rate_usage` là **viết lại hoá đơn mọi tháng
đã chốt**.

Đã thêm trigger `price_item_bat_bien`: `UPDATE`/`DELETE` trên `price_item` bị chặn
ngay khi bộ giá đó đã có dòng trong `rated_usage`.

```
UPDATE billing.price_item SET unit_price = 9999 WHERE component = 'tts';
ERROR: phien ban gia 1 da sinh ra tien trong rated_usage — khong sua duoc.
       Tao mot price_version moi roi gan cho tenant tu mot moc effective_from.
```

Bộ giá chưa dùng thì sửa tự do. **Đã thử cả hai chiều: chặn đúng, và bộ mới sửa được
bình thường.**

Đây cùng một lệ với `control.config_versions` của repo (migration `0200` `REVOKE
UPDATE, DELETE`): thứ gì đã được viện dẫn thì bất biến. Khác ở chỗ điều kiện ở đây là
động ("đã sinh ra tiền chưa") nên dùng trigger thay vì REVOKE.

## 6. Đổi giá thì làm gì

**Không sửa bộ đang chạy.** Tạo bộ mới:

```
① tạo pv_2026_10 (inactive)
② nhập 11 dòng giá — copy từ bộ cũ rồi sửa dòng cần đổi
③ preview trên 30 ngày qua → thấy chênh lệch
④ activate
⑤ gán cho tenant từ 01/10/2026
```

Tháng 8 và 9 vẫn giữ nguyên số tiền vì `rated_usage` của chúng trỏ về bộ cũ và đã
snapshot đơn giá. Đó là toàn bộ lý do bảng này có chữ *version*.

## 7. Đã kiểm chứng những gì

| Phép thử | Kết quả |
|---|---|
| Định giá phiên voice thật | **4.030,30 đ** — khớp công thức bên agent |
| Sửa giá của bộ đã sinh ra tiền | **CHẶN** (`restrict_violation`) |
| Xoá dòng giá của bộ đã sinh ra tiền | **CHẶN** |
| Sửa giá của bộ mới (chưa dùng) | cho phép |
| Tính lại kỳ cũ khi bộ giá đã `inactive` | **vẫn 4.030,30 đ** |
| CHECK của `status` | chỉ `active`, `inactive`; default `inactive` |
| Đặt giá cả hai cơ sở STT | **CHẶN** (unique index) |

## 8. Một chỗ tôi KHÔNG đổi

`billing.invoice.status` vẫn là `draft | issued | paid | void`. Đó là vòng đời **hoá
đơn**, không phải version giá — bốn trạng thái này thật sự khác nhau về hành vi
(`draft` tính lại được, `issued` thì không, `paid` đã thu tiền, `void` đã huỷ). Gộp
chúng lại là mất khả năng biết đã thu tiền hay chưa. Nếu bạn muốn siết cả chỗ này thì
nói, nhưng nó là chuyện khác với chuyện version giá.
