# URL công khai cho media — thiết kế

**Ngày:** 2026-08-12 · **Trạng thái:** đã duyệt, chờ thi công

## 1. Vấn đề

Agent gửi ảnh cho khách bằng URL trực tiếp trong card chat
(`docs/build_test_agent/2026-08-10-frontend-chat-gateway-handoff.md` §177 — `items[].url`,
`items[].thumb`). Trình duyệt khách render nó, và khách cuộn lại lịch sử chat sau nhiều
ngày vẫn phải thấy ảnh.

Nhưng `tenant_data.media.media_url` lưu **khoá S3**, không phải URL, và bucket
`noblex-dev-odyssey-s3-071732232185` chặn công khai hoàn toàn (bốn cờ
`BlockPublicAcls`/`IgnorePublicAcls`/`BlockPublicPolicy`/`RestrictPublicBuckets` đều
`true`, không có bucket policy). Hai đường đọc hiện có đều không dùng được cho agent:

| Đường | Vì sao không dùng được |
|---|---|
`GET /realestate/files?key=` | cần cookie phiên của Portal — agent không có |
presigned URL | sống 300 giây; ảnh trong lịch sử chat sẽ vỡ |

Hệ quả đang có: **ảnh upload qua Portal, agent gửi đi là khách không xem được.** Chưa nổ
vì dữ liệu thật gần như toàn URL ngoài — S3 dev có 258 thumbnail nhưng đúng **1** ảnh
upload. Ngay khi biên tập viên chuyển sang upload thay vì dán link, mọi ảnh agent gửi
đều hỏng.

## 2. Phương án đã chọn

**Một route công khai của chính Portal**, không dựng hạ tầng mới.

Đã cân nhắc và loại:

- **CloudFront + OAC** — đúng về kỹ thuật nhưng cần dựng distribution, sửa bucket policy,
  và tách tiền tố ảnh/tài liệu (hôm nay chúng chung `kb-bds/`). Người yêu cầu chọn không
  đụng hạ tầng.
- **Presigned URL TTL dài** — S3 trần 7 ngày; ảnh lịch sử chat vẫn vỡ, chỉ vỡ muộn hơn.
- **URL ký HMAC có hạn** — cùng vấn đề, cộng thêm một job gia hạn.

Chọn route Portal **không đóng cửa CloudFront**: sau này gắn CDN với origin là Portal
(không phải S3) thì không cần OAC, không cần sửa bucket policy, và **không một dòng code
nào đổi** — URL trong lịch sử chat cũ vẫn sống nếu giữ nguyên path.

## 3. Route

```
GET /api/v1/public/files/{key:path}      không auth
```

- Khai `require(None, ly_do=…)` — repo đã có cơ chế này cho route công khai có chủ ý
  (`tests/api/test_moi_route_khai_action.py`), nên cổng "mọi route phải khai quyền" vẫn
  đo được và không thành trang trí.
- Chỉ nhận `key` khớp `tenants/<slug>/kb-bds/…`. Mọi thứ khác — `bundles/`, `LIVE`, `..`,
  `//` — rơi vào **cùng một nhánh 404**, nên không phải liệt kê từng dạng tấn công.
  `bundles/` (persona · prompt · config agent) nằm ngoài tiền tố này nên không lộ.
- `Cache-Control: public, max-age=31536000, immutable` — khoá chứa sha256 của nội dung
  nên một khoá không bao giờ đổi nội dung. `public` chứ không `private` như route CMS:
  đây là thứ CDN được phép cache.
- Content-Type tra theo đuôi trong bảng `_MIME`, không tin client.

**Phạm vi:** phát mọi thứ dưới `kb-bds/`, **không lọc theo `status`** — quyết định tường
minh của người yêu cầu. Nghĩa là hàng `draft` cũng phát được nếu ai đó có link, và link
không thu hồi được trừ khi xoá object. Cái chắn duy nhất là sha256 trong đường dẫn:
không liệt kê được, không đoán được (capability URL).

## 4. Hai cột dẫn xuất

`tenant_data.media` thêm `public_url` và `public_thumb_url`, `text NOT NULL DEFAULT ''`.

`media_url`/`thumb_url` **giữ nguyên là khoá** — chúng là thứ dùng để xoá object khi xoá
hàng và để dedup theo sha256; biến chúng thành URL là mất cả hai.

```
media_url         tenants/anphu/kb-bds/9f3c…/mb.jpg
public_url        https://portal.noblex.vn/api/v1/public/files/tenants/anphu/kb-bds/9f3c…/mb.jpg

media_url         https://cdn.khach.vn/a.jpg          ← ảnh dán URL ngoài
public_url        https://cdn.khach.vn/a.jpg          ← chính nó, agent không phải phân biệt
```

Quy tắc, một hàm dùng chung ở `portal/core/public_url.py`:

```python
def public_url_of(key_or_url: str) -> str:
    """Rỗng → rỗng. Bắt đầu bằng http → nguyên văn. Còn lại là khoá → nối base."""
```

Base từ biến env mới **`PUBLIC_BASE_URL`** (mặc định `http://localhost:8100` cho dev).
**Không nhúng domain vào migration** — dev và prod khác domain, và một migration mang
domain nghĩa là hai môi trường cần hai migration khác nhau. Migration chỉ thêm cột rỗng;
backfill là script vận hành đọc env.

Ba chỗ ghi phải gọi helper: `repo.chen_media`, `repo.sua_media` (cả hai ở
`modules/realestate`), và `kb.state.repo.save_thumb`/`save_thumb_and_hash` (chặng enrich
sinh thumbnail). Lưới an toàn là một test đo bất biến "hàng nào có `media_url` thì
`public_url` không rỗng" sau khi đi qua các đường ghi thật — quên một chỗ thì test đỏ,
không phải phát hiện trên dữ liệu thật.

## 5. Hợp đồng agent

`docs/contracts/mat-bang-agent.md` đổi câu SELECT:

```sql
SELECT id, public_url, public_thumb_url, caption
  FROM tenant_data.media
 WHERE project_code = $1 AND category = 'mat_bang' AND status = 'published'
 ORDER BY created_at
```

Agent đặt thẳng `public_url` vào `items[].url` và `public_thumb_url` vào `items[].thumb`.
Không ghép chuỗi, không biết base URL của Portal, không ký gì. Copy tay sang repo
`odyssey-agent` như mọi hợp đồng khác — không có job CI nào so hai bên.

`media_url`/`thumb_url` vẫn còn nguyên trong bảng; agent **thôi đọc chúng** để gửi cho
khách. Một dự án cũ chưa backfill sẽ có `public_url = ''` — agent phải coi đó là "không
có ảnh", không phải gửi chuỗi rỗng vào `items[].url`.

## 6. Backfill

`scripts/backfill_public_url.py` — đọc `PUBLIC_BASE_URL`, chạy hai câu UPDATE cho mọi
tenant. Idempotent: chạy lại chỉ ghi đè bằng đúng giá trị cũ. Chạy tay sau mỗi lần deploy
có đổi domain.

## 7. Test

| Đo gì | Ở đâu |
|---|---|
Route trả 404 cho `bundles/`, `LIVE`, `..`, tenant khác | `tests/modules/realestate/` |
Route không cần cookie mà vẫn 200 cho khoá `kb-bds/` hợp lệ | nt |
Cổng "mọi route khai quyền" vẫn xanh với route mới | `tests/api/test_moi_route_khai_action.py` (có sẵn) |
`public_url_of` — rỗng · URL ngoài · khoá | `tests/unit/` |
Bất biến "có `media_url` ⇒ có `public_url`" qua đường ghi thật | `tests/modules/realestate/` |
Thumbnail do enrich sinh cũng điền `public_thumb_url` | `tests/modules/kb/` |

## 8. Không làm

- Không lọc `status` ở route (§3).
- Không đụng `media_url`/`thumb_url` (§4).
- Không dựng CloudFront (§2) — để lại như bước sau, không cần đổi code.
- Không mở đường upload video: endpoint vẫn chỉ nhận ảnh + tài liệu, video vào hệ thống
  bằng URL YouTube như trước.
