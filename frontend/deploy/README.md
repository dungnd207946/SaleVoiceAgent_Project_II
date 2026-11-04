# Deploy — `odyssey-portal-frontend`

Repo này sinh ra **một** image, đẩy lên ECR của NobleX:

```
418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/odyssey-portal-frontend:<tag>
```

Repository trên ECR (`aidc/odyssey-portal-frontend`) **phải tồn tại trước** — ECR
không tự tạo repository lúc `push`, lỗi trả về là `repository does not exist`.

Bên trong là bundle tĩnh của SPA cộng nginx phục vụ nó. Không có node ở runtime,
không có tiến trình nào gọi database — service này không có state.

Tag lấy ở log job build trên CI (`$CI_COMMIT_SHORT_SHA`). **Đừng deploy bằng
`dev-latest` / `prod-latest`**: chúng trỏ chỗ khác sau mỗi lần merge, nên một lần
restart tưởng là vô hại có thể lặng lẽ đổi phiên bản đang chạy.

## Chạy

```sh
# đăng nhập ECR trước, nếu không lỗi là "no basic auth credentials"
aws ecr get-login-password --region ap-southeast-1 \
  | docker login --username AWS --password-stdin 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com

docker run -d --name odyssey-portal-frontend \
  --network odyssey-network \
  -p 80:80 \
  -e ODYSSEY_PORTAL_API_UPSTREAM=http://odyssey-portal-backend:8100 \
  -e ODYSSEY_PORTAL_MODELS_TOKEN=<ODYSSEY_MODELS_TOKEN của odyssey-models> \
  418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/odyssey-portal-frontend:<tag>
```

`--network odyssey-network` không phải tuỳ chọn: thiếu nó thì nginx không phân
giải nổi `odyssey-portal-backend` và container **từ chối khởi động** (`[emerg]`,
xem mục dưới). Network này tạo bằng tay — xem mục **Network**.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ODYSSEY_PORTAL_API_UPSTREAM` | `http://odyssey-portal-backend:8100` | Địa chỉ service backend mà nginx chuyển tiếp `/api/` tới |
| `ODYSSEY_PORTAL_LIPSYNC_UPSTREAM` | `http://lipsync-musetalk:8020` | Service lip sync (odyssey-models) mà nginx chuyển tiếp `/lipsync/` (WebSocket) tới |
| `ODYSSEY_PORTAL_MODELS_TOKEN` | *(không có — PHẢI khai, dù rỗng)* | Token nginx GẮN khi chuyển tiếp `/lipsync/` — cùng giá trị `ODYSSEY_MODELS_TOKEN` của odyssey-models. Compose lấy từ `ODYSSEY_MODELS_TOKEN` trong `.env` (`ODYSSEY_SECRET_FRONTEND_ENV`). Rỗng/sai ⇒ portal chạy bình thường, chỉ không có lip sync. **Không khai biến** ⇒ nginx không khởi động (envsubst để nguyên `${…}`). |

Đều là biến **runtime** — nginx thay nó vào cấu hình lúc khởi
động container. Nghĩa là **một image chạy được mọi môi trường**; đổi staging
sang production không phải build lại.

⚠️ **Không có dấu `/` ở cuối.** `http://odyssey-portal-backend:8100` đúng;
`http://odyssey-portal-backend:8100/` sai. Dấu `/` làm nginx cắt mất tiền tố
`/api/` và mọi lời gọi API thành 404. Chi tiết ở chú thích `proxy_pass` trong
`deploy/odyssey-portal-frontend.conf.template`.

⚠️ Biến này **không** phải `VITE_*`. Biến `VITE_*` được nhúng cứng vào bundle
lúc build, nên chúng không đổi được sau khi image đã đóng. Frontend gọi API
bằng đường tương đối (`fetch('/api/v1/me')`) đúng là để tránh chuyện đó.

## Định tuyến

Cả SPA và API đứng sau **cùng một origin**:

```
người dùng → odyssey-portal-frontend :80
                ├── /api/*   → proxy → odyssey-portal-backend :8100
                ├── /healthz → nginx trả "ok"
                └── còn lại  → file tĩnh, không khớp thì index.html (SPA fallback)
```

Cùng origin nên **không cần cấu hình CORS**, và cookie phiên đăng nhập đi theo
request một cách tự nhiên. Nếu sau này tách thành hai domain thì phải thêm CORS
ở backend **và** xử lý cookie cross-site — không phải chỉ đổi một biến.

Điều kiện: `odyssey-portal-backend` phải resolve được bằng tên DNS từ trong
mạng của container frontend. Trên docker compose thì đặt hai service chung một
network là đủ; nền tảng khác thì thay bằng tên service tương ứng.

## Health check

`GET /healthz` → `200 ok`. Image đã khai sẵn `HEALTHCHECK` của Docker; load
balancer riêng thì trỏ probe vào đúng đường đó.

⚠️ Đường này chỉ nói *"nginx còn sống và còn phục vụ được file"*. Nó **không**
gọi tới backend, nên nó xanh cả khi `odyssey-portal-backend` đã chết. Probe của
backend là `GET /healthz` trên chính service đó — xem
`odyssey-portal-backend/deploy/README.md` §8.3.

## Thứ tự khi deploy cả hai service

**Không còn thứ tự bắt buộc** kể từ 2026-08-04. Deploy frontend trước backend
được; `/api/` trả 502 tới khi backend lên, phần SPA phục vụ bình thường,
`/healthz` xanh.

Trước đó thì có, và cái giá phải trả cho việc ấy đủ lớn để phải sửa: nginx phân
giải hostname trong `proxy_pass` **lúc khởi động** khi nó là một chuỗi cố định.
Tên chưa có trong DNS thì nginx **từ chối khởi động**:

```
[emerg] 1#1: host not found in upstream "odyssey-portal-backend" in
             /etc/nginx/conf.d/default.conf:38
```

Container `Exited(1)` → `restart: unless-stopped` cho nó lặp → `docker compose up
--wait` báo `container odyssey-portal-frontend is unhealthy` và **job deploy đỏ**,
trong khi frontend hoàn toàn lành. Đúng triệu chứng đã gặp trên CI.

Và một hệ quả thứ hai, tệ hơn vì im lặng: chuỗi cố định làm nginx **cache IP vĩnh
viễn**. Mỗi lần recreate container backend là nó đổi IP, nginx vẫn gõ IP cũ và
**mọi** `/api/` thành 502 cho tới khi ai đó restart frontend — tức mỗi lần deploy
backend là một lần frontend hỏng mà không ai được báo.

Cả hai đã sửa trong `deploy/odyssey-portal-frontend.conf.template`: `proxy_pass`
đi qua **biến** kèm `resolver 127.0.0.11 valid=10s` + `resolver_timeout 5s`, nên
nginx phân giải theo request (TTL 10s) và bắt kịp IP mới trong ~10s mà không cần
restart. Đã dựng lại cả hai kịch bản bằng container thật để chứng minh, và so
sánh trực tiếp với cấu hình cũ (cũ: request không tới backend mới; mới: tới).

Ba điều đi kèm, đừng gỡ:

* `$request_uri` trong `proxy_pass $upstream_api$request_uri` là **bắt buộc** —
  ở dạng biến nginx không tự nối URI gốc, thiếu nó thì mọi request tới backend
  thành `/`. Đã kiểm: `/api/v1/me` tới backend vẫn là `/api/v1/me`.
* `resolver_timeout 5s` — mặc định 30s, tức backend chưa lên thì mỗi lời gọi API
  treo 30s rồi mới 502; người dùng thấy màn hình đứng chứ không thấy lỗi.
* `resolver` **không đọc `/etc/hosts`**, nên `host.docker.internal` (do
  `extra_hosts` sinh ra) không dùng được cho upstream nữa. Ở máy dev muốn trỏ
  backend chạy trên host thì dùng IP gateway:
  `docker network inspect odyssey-network -f '{{(index .IPAM.Config 0).Gateway}}'`.

## Chạy bằng docker compose

Repo có **ba** file compose ở gốc, mỗi file một service:

| File | Dùng ở | Image |
|---|---|---|
| `docker-compose.local.yml` | máy dev | build tại chỗ (`up -d --build`) → `odyssey-portal-frontend:dev` |
| `docker-compose.onprem.yml` | deploy dev-server và prod **hiện nay** (server on-prem) — `.gitlab-ci.yml` dùng file này | kéo từ ECR theo `IMAGE_TAG`, **không** có `build:` |
| `docker-compose.dev.yml` | bản AWS cũ, giữ lại phòng khi quay về | kéo từ ECR theo `IMAGE_TAG`, **không** có `build:` |

⚠️ Hai file deploy hiện có nội dung **giống hệt nhau**, và đó là sự thật chứ không
phải sót: repo này là SPA tĩnh + nginx, không chạm Aurora/S3 nên chuyển on-prem
không đổi gì trong compose. File riêng tồn tại để hai môi trường tách nhau được về
sau, và để mọi repo odyssey cùng deploy bằng một tên file.

Cả hai nối vào `odyssey-network` external (xem mục **Network**). Lệnh deploy:

```sh
# 0. network dùng chung — MỘT LẦN, trước mọi `up` (xem mục dưới)
docker network create odyssey-network

# 1. đăng nhập ECR (image nằm ở registry riêng, `pull` không có auth thì lỗi
#    "no basic auth credentials" chứ không phải "image không tồn tại")
aws ecr get-login-password --region ap-southeast-1 \
  | docker login --username AWS --password-stdin 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com

# 2. kéo image do job build của .gitlab-ci.yml đẩy lên (KHÔNG build lại)
#    Compose viết cứng đường dẫn ECR, chỉ TAG là biến — cùng quy ước với
#    nbx-hub-frontend. Không có biến nào chứa cả tên image.
export IMAGE_TAG=<sha ngắn của commit>
export ODYSSEY_PORTAL_API_UPSTREAM=http://odyssey-portal-backend:8100
docker compose -f docker-compose.onprem.yml pull
docker compose -f docker-compose.onprem.yml up -d --no-build --wait
```

### Network

Cả hai repo của portal — frontend và backend — dùng **một** network tên cố định
`odyssey-network`, khai `external: true`, và **được tạo bằng tay**:

```sh
docker network create odyssey-network
```

Compose **không** tự tạo nó. Chủ ý: nếu compose được phép tự tạo thì mỗi repo
sinh ra một network riêng cùng ý nghĩa, frontend nối vào cái không có backend,
tên `odyssey-portal-backend` không phân giải, và ta rơi đúng vào `[emerg]` ở
trên. Thà `up` fail ngay với `network odyssey-network not found`.

Vì network không còn do repo nào tạo ra, thứ tự giữa hai repo không còn là ràng
buộc *về network* — nhưng vẫn là ràng buộc *về DNS*, vì nginx phân giải upstream
lúc khởi động (xem ngay mục trên). Đổi tên network bằng biến
`ODYSSEY_PORTAL_NETWORK` (phải đổi ở **cả hai** repo, nếu không chúng lại nằm ở
hai network khác nhau).

Cổng ra host mặc định `5274` (biến `PORTAL_FE_PORT`), cổng trong container là
`80`. 5274 chứ không 5273 vì 5273 là vite dev server ở máy dev.

## Cache

Bundle dùng tên file có hash nội dung, nên `dist/assets/*` cache một năm là an
toàn. `index.html` thì `no-cache` — nó là thứ trỏ tới bộ asset mới, cache nó là
deploy xong mà người dùng vẫn chạy bản cũ tới khi tự hard-refresh.

Nếu đặt CDN trước service này thì giữ nguyên phân biệt đó; CDN cache `index.html`
làm hỏng đúng thứ cấu hình trên tồn tại để tránh.
