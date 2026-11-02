# Lượt định giá hằng đêm — LƯỚI AN TOÀN, không phải đường chính

Từ migration `0950`, tiền được tính **trong chính câu `INSERT`** vào
`billing.usage_events`: trigger `usage_events_dinh_gia` sinh 1..N dòng
`billing.rated_usage` cho mỗi event. Portal đọc `rated_usage`, nên số tiền trên
giao diện **không còn phụ thuộc vào lịch chạy nào**.

Timer trong thư mục này KHÔNG phải đường chính. Nó vá ba lỗ mà trigger không
với tới:

1. **Usage tới trước khi có giá.** Trigger chạy một lần lúc insert; nếu lúc đó
   chưa có dòng giá phủ component/metric đó thì event nằm lại không tiền. Thêm
   dòng giá xong, chỉ một lượt quét lùi mới vá được.
2. **Trigger hỏng mà không làm vỡ INSERT.** `dinh_gia_sau_insert()` bọc phần
   định giá trong `EXCEPTION WHEN OTHERS` và chỉ `RAISE WARNING` — cố ý, vì
   `usage_events` là sổ gốc không dựng lại được, còn `rated_usage` thì tính lại
   được. Cái giá của lựa chọn đó là phải có ai đi tính lại; đây là chỗ đó.
3. **Dữ liệu ghi trước `0950`.** Event có từ trước khi trigger tồn tại chưa
   từng được định giá.

Bỏ timer này thì hệ thống vẫn chạy đúng ở đường thường, nhưng ba lỗ trên trở
thành **thiếu tiền vĩnh viễn và im lặng**.

> **Timer NÓNG 2 phút đã bị bỏ** (2026-08-21, cùng lần thêm `0950`). Nó tồn tại
> để rút ngắn độ trễ giữa hai lượt định giá — trigger làm độ trễ đó bằng không,
> nên giữ lại một nhịp 2 phút chỉ là quét lại 720 lần/ngày thứ đã đúng sẵn.

## Cài

```sh
cd /srv/odyssey-portal-backend            # nơi checkout thật của môi trường này
ĐƯỜNG=$(systemd-escape -p "$PWD")

sudo cp deploy/systemd/odyssey-dinh-gia-nguoi@.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "odyssey-dinh-gia-nguoi@$ĐƯỜNG.timer"
```

Unit là **template** (`@`): `%i` là đường dẫn checkout đã escape, `%f` là đường
dẫn thật. Không viết cứng đường dẫn vì máy dev và prod đặt repo ở hai chỗ, và
một unit viết cứng sẽ bị sửa tay trên máy — lúc đó bản trong git thôi là bản
đang chạy.

## Kiểm

```sh
systemctl list-timers 'odyssey-dinh-gia-*'
journalctl -u "odyssey-dinh-gia-nguoi@$ĐƯỜNG.service" -n 20   # "đã định giá N dòng"

# Diễn tập: tính rồi rollback. Chạy được trên production.
docker compose -f docker-compose.dev.yml run --rm dinh-gia dinh-gia --thu-kho
```

Ở một hệ chạy bình thường, lượt đêm nên báo con số **nhỏ** — trigger đã làm hết
phần việc, nên `ON CONFLICT DO UPDATE` chỉ ghi lại đúng giá trị cũ. Một con số
**lớn** đột ngột là dấu hiệu trigger đang ném (xem `RAISE WARNING` trong log
Postgres), không phải dấu hiệu job đang hữu ích.

## Đổi giá thì làm thế nào

Giá nằm trong DB (`billing.price_item`), seed bởi migration `0949`. Nhưng
trigger `price_item_bat_bien` (`0943`) **chặn sửa/xoá một dòng giá sau khi nó đã
sinh ra tiền** — và với `0950` thì điều đó xảy ra ngay event đầu tiên. Đó là chủ
đích: sửa đơn giá tại chỗ sẽ viết lại hoá đơn của những kỳ đã chốt.

Nên hai đường:

- **Đổi giá từ nay về sau** — tạo một `price_version` mới rồi gán nó (màn
  `/pricing`, hoặc SQL tay). Đường không phá gì.
- **Thật sự muốn tính lại một kỳ đã qua** — `DELETE FROM billing.rated_usage`
  cho kỳ đó trước, rồi sửa giá, rồi `dinh-gia --tu … --den …`. Đây là **viết lại
  hoá đơn**; chính câu lỗi `MOC_QUA_KHU_DA_DINH_GIA` đang chỉ dẫn nó.

## Vai `dinh-gia` dùng file env của MIGRATE

`rate_usage()` định giá cho **mọi** tenant (`p_tenant = NULL`) — thao tác cấp nền
tảng, không thuộc phạm vi cách ly của một request. Xem docstring
`src/portal/cli/dinh_gia_usage.py` và `deploy/README.md` §1–§2. Entrypoint từ
chối vai này nếu thiếu `MIGRATOR_URL`.

## kb/web — thu thập dữ liệu công khai

**Không còn timer.** Từ 2026-10-05 lịch chạy (đêm / tuần / viết lại) là DỮ LIỆU của từng
workspace (`tenant_data.kbweb_schedules`, người dùng chỉnh trên màn «Dữ liệu ngoài») và được
`crawl-worker` tự đọc mỗi phút (`src/portal/modules/kb/web/scheduler.py`) rồi xếp job
`kbweb_run` cho đúng tenant. Ba unit `odyssey-kb-web-{night,weekly,quarterly}@` đã xoá — host nào
còn cài thì gỡ:

```sh
ĐƯỜNG=$(systemd-escape -p "$PWD")
sudo systemctl disable --now "odyssey-kb-web-night@$ĐƯỜNG.timer" \
  "odyssey-kb-web-weekly@$ĐƯỜNG.timer" "odyssey-kb-web-quarterly@$ĐƯỜNG.timer"
sudo rm /etc/systemd/system/odyssey-kb-web-*@.{service,timer}; sudo systemctl daemon-reload
```

`crawl-worker` (`src/portal/cli/kb_web_worker.py`) chạy LIÊN TỤC: lịch + job `kbweb_run`
(chuỗi đêm của một tenant) + job `kbweb_project` (hồ sơ một dự án). Dùng role runtime
`portal_api` (`deploy/odyssey-portal-crawl.env`), KHÔNG `MIGRATOR_URL`. Hai replica cùng chạy
cũng không xếp trùng: scheduler giữ `pg_advisory_lock`. Nó đứng sau `profiles: ["crawl"]`, phải
OPT-IN tường minh:

```sh
docker compose -f docker-compose.dev.yml --profile crawl up -d crawl-worker
```

⚠️ Lý do đứng sau profile chứ không mặc định: `env_file:` của nó trỏ
`deploy/odyssey-portal-crawl.env`, và thiếu FILE đó (khác thiếu một BIẾN trong
file, vốn chỉ rỗng) là lỗi CỨNG — `docker compose up -d` (không cờ profile) sẽ
hỏng cho **mọi** service trong file, kể cả những service không liên quan gì tới
kb/web, trên bất kỳ host nào chưa tạo file env đó.

Vai `crawl` (`src/portal/cli/kb_web_night.py`) chỉ còn cho vận hành tay, luôn kèm `--tenant`:

```sh
# nạp ngược kho bài theo sitemap lưu trữ cho một workspace (chỉ crawl + gắn nhãn, chưa viết hồ sơ)
docker compose -f docker-compose.dev.yml run --rm crawl crawl --tenant anphu --backfill 2024-10-01 2026-09-28
# xếp MỘT lượt dựng lại cho mọi dự án published của workspace (crawl-worker phải đang chạy)
docker compose -f docker-compose.dev.yml run --rm crawl crawl --tenant anphu --rebuild
```

⚠️ `run --rm crawl crawl --tenant …` lặp `crawl` hai lần: token đầu là TÊN SERVICE compose, token
thứ hai là VAI truyền cho entrypoint. Cả hai bước tốn tiền LLM: `--backfill` gắn nhãn từng bài bằng
qwen, `--rebuild` viết tới 5 lượt hồ sơ mỗi dự án kèm Gemini grounding dưới trần tháng của tenant.
Trên màn «Dữ liệu ngoài» người dùng tự bấm «Chạy ngay» / «Viết lại hồ sơ» — không cần vào host.

### Kiểm

```sh
docker compose -f docker-compose.dev.yml logs -f crawl-worker      # "lịch kb/web: xếp N lượt"
```
