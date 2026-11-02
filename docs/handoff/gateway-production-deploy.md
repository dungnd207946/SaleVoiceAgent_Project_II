# Spec bàn giao DevOps — Deploy Ingress Gateway cho `*.agents.noblex.vn`

**Ngày:** 2026-08-05
**Người yêu cầu:** tuyennvt@noblex.vn
**Mức độ:** Blocker — provider client không kết nối được vào agent qua gateway.
**Phạm vi:** Hạ tầng deploy (server `118.71.98.17`) — KHÔNG đổi source code agent.

---

## 1. Triệu chứng

Client WebSocket kết nối tới gateway production báo lỗi:

```
websockets.exceptions.InvalidStatus: server rejected WebSocket connection: HTTP 200
```

Lệnh chạy:
```bash
python scripts/e2e_dbmode/chat_via_gateway.py "Dự án nào đang mở bán ạ?"
# → ws://du_fake.agents.noblex.vn/v1/chat
```

## 2. Nguyên nhân gốc (đã xác minh)

**Gateway ĐÃ được deploy** (container `odyssey-agent-gateway-1`, image tag `73b1d13a`) trên host AWS `ip-10-110-43-147`, publish `0.0.0.0:9200->9200`. **NHƯNG request không bao giờ tới được nó** vì DNS trỏ sang một MÁY KHÁC chưa cấu hình forward.

**Đây là bài toán 2 máy:**

| | Gateway thật | Máy DNS trỏ tới |
|---|---|---|
| Host | AWS `ip-10-110-43-147` (private `10.110.43.147`) | edge `118.71.98.17` (IP dải VN, KHÁC AWS) |
| Vai trò | chạy `noble-gateway` :9200 | nginx edge — CHƯA cấu hình |

Probe trực tiếp tại `118.71.98.17` (nơi `*.agents.noblex.vn` trỏ tới):

| Kiểm tra | Kết quả |
|---|---|
| DNS `du_fake.agents.noblex.vn` / apex / `acme.*` | đều → `118.71.98.17` |
| `http://…/` (80) và `https://…/` (443) | **nginx/1.30.3** trả `<title>Coming Soon</title>`, HTTP **200 text/html** |
| `https://…/v1/chat` + WS upgrade + Bearer (443) | Vẫn trả **200 + trang "Coming Soon"** — KHÔNG `101 Switching Protocols` |
| Port `9200` trên `118.71.98.17` | **đóng** — gateway KHÔNG nằm ở máy này |
| TLS cert (443) | `subject=CN=default`, `issuer=CN=default` — **self-signed mặc định**, KHÔNG phải cert `*.agents.noblex.vn` |

**Kết luận:** nginx trên máy edge `118.71.98.17` vẫn là bản cài mặc định phục vụ trang placeholder cho MỌI path, cert self-signed `CN=default`. **Nó KHÔNG có location nào forward `/v1/chat` (+ `/v1/voice`) sang gateway AWS `10.110.43.147:9200`.** Vì thế WS client nhận HTTP 200 (trang HTML) thay vì upgrade → `InvalidStatus`. Deploy container gateway mới xong một nửa — **nửa còn thiếu là cấu hình edge proxy nơi DNS trỏ tới + đường mạng edge→gateway.**

> Đã xác minh: cùng codebase chạy local (gateway :9200 + agent :8766 + Postgres control-plane) trả lời end-to-end bình thường. Bug KHÔNG nằm ở code — chỉ là edge/DNS chưa wire đúng vào gateway đã deploy.

### 2b. Hai việc phải làm ở máy edge `118.71.98.17`
1. **Cấu hình nginx** — thêm vhost `*.agents.noblex.vn` proxy `/v1/chat`+`/v1/voice` → gateway `:9200` (mục 4.4), thay cert `CN=default` bằng cert wildcard thật.
2. **Đường mạng edge → gateway** — gateway nghe ở `10.110.43.147` (**private** AWS IP), máy edge VN không route thẳng vào private IP AWS được. Phải chọn 1:
   - (a) DNS `*.agents.noblex.vn` trỏ THẲNG vào public endpoint của AWS box (Elastic IP / ALB / NLB) đứng trước gateway `:9200`, bỏ edge VN; **hoặc**
   - (b) Giữ edge VN làm public, dựng VPN/peering để edge route tới `10.110.43.147:9200` (hoặc AWS expose gateway qua một IP mà edge chạm được), rồi `proxy_pass` vào đó.
   - ⚠️ Quyết định (a) vs (b) là của DevOps/Network — cần chốt trước khi viết `proxy_pass`.

## 3. Kiến trúc đích

Nguồn tham chiếu: `docker-compose.deploy.yml` (trong repo). Một process share phục vụ N tenant, tenant suy từ **subdomain** của Host.

```
Provider client
   │  wss://<tenant>.agents.noblex.vn/v1/chat   (chat)
   │  wss://<tenant>.agents.noblex.vn/v1/voice (voice)
   ▼
[ nginx/Caddy :443 ]  ── TLS terminate, GIỮ NGUYÊN Host header, WS upgrade
   │  ws://127.0.0.1:9200
   ▼
[ noble-gateway :9200 ]  ── resolve tenant = subdomain; verify Bearer;
   │                        /v1/chat  → reverse-proxy sang worker /chat
   │                        /v1/voice→ bridge audio vào LiveKit room
   ▼
[ agent (aiortc) :8766 ]  ── ws://agent:8766/chat   (X-Tenant-Id header)
[ agent-lk (livekit worker) ]  ── join room được dispatch
```

Điểm public DUY NHẤT là gateway (qua reverse-proxy 443). Agent `:8766` và LiveKit worker KHÔNG cần public.

## 4. Công việc DevOps cần làm

### 4.1. DNS
- [ ] Xác nhận wildcard `*.agents.noblex.vn` → `118.71.98.17` (đã có). Cần cả bản ghi để cấp cert wildcard (DNS-01) — xem 4.4.

### 4.2. Deploy stack gateway trên `118.71.98.17`
- [ ] Build image + chạy `docker-compose.deploy.yml` (services: `agent`, `agent-lk`, `gateway`, và `postgres` nếu dùng PG cục bộ).
- [ ] Gateway lắng nghe `:9200` (đã map trong compose). Chỉ bind loopback/private — KHÔNG expose 9200 ra Internet; chỉ reverse-proxy nội bộ chạm tới.
- [ ] Kiểm tra tiến trình sống: `ss -ltnp | grep 9200` phải thấy `noble-gateway`.

### 4.3. Cấu hình `.env` trên server production
Các key BẮT BUỘC đúng (khác với `.env` môi trường dev/local):

- [ ] **(Đã đổi kiến trúc — single-domain)** `GATEWAY_BASE_DOMAIN` KHÔNG còn tồn tại — gateway không còn suy tenant từ subdomain của Host. Tenant giờ đến từ Bearer API key, resolve qua Portal runtime-credentials API. **Không set biến này** (đặt vào .env sẽ không có tác dụng gì, không phải lỗi nhưng cũng không giúp gì).
- [ ] `GATEWAY_CREDENTIALS_API_URL=<URL Portal runtime-credentials API>` **BẮT BUỘC**. Rỗng ⇒ gateway fail-closed: từ chối MỌI kết nối với reason `auth_api_unavailable` (không phân biệt được khoá sai hay hạ tầng down, nên coi rỗng-config là hạ tầng chưa sẵn sàng).
- [ ] `GATEWAY_HOST=0.0.0.0` / `GATEWAY_PORT=9200` (khớp reverse-proxy).
- [ ] `WORKER_CHAT_INTERNAL_URL_TEMPLATE=ws://agent:8766/chat`
      (đúng tên service trong bridge network; nếu không dùng Docker DNS thì trỏ IP/host nội bộ của agent).
- [ ] `GATEWAY_WORKER_SECRET=<secret dùng chung gateway↔worker>` — **BẮT BUỘC set** nếu muốn worker forward per-tenant PG credential (`X-PG-Role`/`X-PG-Password`/`X-PG-Expires`). Rỗng ⇒ worker coi hop gateway→worker là chưa xác thực và **bỏ qua** các header `X-PG-*` kể cả khi gateway có gửi (worker fallback shared DSN, không phải lỗi nhưng mất isolation credential per-tenant).
- [ ] Nguồn credential tenant: Portal runtime-credentials API (theo `GATEWAY_CREDENTIALS_API_URL` ở trên) là nguồn DUY NHẤT — trả tenant_id + PG role/password/expires_at cho mỗi API key hợp lệ.
- [ ] (Voice) `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` / `LIVEKIT_AGENT_NAME` hợp lệ nếu bật `/v1/voice`.

### 4.4. Reverse-proxy + TLS (mấu chốt của lỗi này)
Thêm **vhost mới** cho `*.agents.noblex.vn` (file hiện có `infra/nginx/hotline-agent.noble.vn.conf` là cho host KHÁC, KHÔNG cover cái này). Yêu cầu:
- [ ] `server_name *.agents.noblex.vn;`
- [ ] Terminate TLS trên **443** (cert **wildcard** `*.agents.noblex.vn` — dùng certbot DNS-01, vì HTTP-01 không cấp được wildcard).
- [ ] Proxy `/v1/chat` và `/v1/voice` → `http://127.0.0.1:9200` với **header WebSocket Upgrade**.
- [ ] **GIỮ NGUYÊN Host header gốc** (`proxy_set_header Host $host;`) — gateway cần Host để suy tenant. TUYỆT ĐỐI không rewrite Host.
- [ ] `proxy_read_timeout`/`proxy_send_timeout` dài (cuộc gọi/chat kéo dài) — vd `3600s`.

Mẫu nginx (xem thêm Phụ lục A):
```nginx
server {
    listen 443 ssl;
    server_name *.agents.noblex.vn;
    # ssl_certificate / ssl_certificate_key do certbot (DNS-01, wildcard) quản lý

    location ~ ^/v1/(chat|stream)$ {
        proxy_pass http://127.0.0.1:9200;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;                 # BẮT BUỘC giữ Host
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / { return 404; }   # không lộ trang tĩnh trên vhost gateway
}
# (tuỳ chọn) server :80 → redirect 301 sang https
```
> Lưu ý: trang "Coming Soon" hiện tại có thể đang là `default_server` port 80/443 bắt hết. Đảm bảo vhost `*.agents.noblex.vn` được ưu tiên đúng và không bị default site nuốt.
>
> **`proxy_pass` target tuỳ topology (mục 2b):** nếu nginx đặt CÙNG máy với gateway (option a — DNS trỏ thẳng AWS box) thì `http://127.0.0.1:9200`. Nếu edge VN proxy sang AWS (option b) thì thay bằng `http://<địa_chỉ_gateway_edge_chạm_được>:9200`. Gateway KHÔNG nằm ở `118.71.98.17` (9200 đóng ở đó) — không được để `127.0.0.1:9200` trên máy edge hiện tại.

### 4.5. Firewall / ports
- [ ] Mở **443** ra Internet.
- [ ] **KHÔNG** mở 9200 / 8766 / 5432 ra Internet (chỉ nội bộ).

### 4.6. Provision tenant (phối hợp team Portal/Backend)
Client trong ví dụ dùng host `du_fake.agents.noblex.vn` ⇒ tenant = `du_fake`. Để auth pass, tenant đó phải tồn tại + active + có key:
- [ ] `db` mode: Portal tạo tenant `du_fake` (`lifecycle=active`), publish config, phát key (sha256 trần của plaintext token) vào `control.agent_keys`, đăng ký deployment `chat`/`voice`.
- [ ] `legacy` mode: `noble-tenant issue-cred <tenant>` trên MinIO store.
- [ ] Client giữ **plaintext token** tương ứng để gửi `Authorization: Bearer <token>`.

> ⚠️ Lưu ý bảo mật: token `ody_ag_cV5HCnDg2RQ70-...` đang hardcode trong `scripts/e2e_dbmode/chat_via_gateway.py` là để test — cần rotate/không commit token thật.

## 5. Tiêu chí nghiệm thu (Acceptance)

1. **TLS/WS handshake trả 101:**
   ```bash
   curl -s -i --http1.1 \
     -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" \
     -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
     -H "Authorization: Bearer <token_hợp_lệ>" \
     https://du_fake.agents.noblex.vn/v1/chat | head -1
   # Kỳ vọng: HTTP/1.1 101 Switching Protocols   (KHÔNG phải 200)
   ```
   - Nếu vẫn `200 text/html` → reverse-proxy chưa forward vào gateway (còn dính trang tĩnh).
   - Nếu WS đóng ngay với close code **4001** → gateway đã nhận nhưng auth fail:
     `no_bearer` (thiếu/sai format `Authorization: Bearer `) / `bad_credential` (API key sai/đã revoke)
     / `auth_api_unavailable` (Portal runtime-credentials API down, 5xx, hoặc `GATEWAY_CREDENTIALS_API_URL` chưa cấu hình — fail-closed).
     (`bad_host`/`tenant_inactive` đã RETIRED cùng kiến trúc single-domain — gateway không còn suy tenant từ Host/subdomain nữa.)
   - Close **4004** = sai route (path không phải `/v1/chat`|`/v1/voice`).

2. **Chat end-to-end** qua script (sửa target về production, dùng token thật):
   ```python
   # scripts/e2e_dbmode/chat_via_gateway.py
   "wss://du_fake.agents.noblex.vn/v1/chat"   # wss, không port
   ```
   Kỳ vọng: nhận `session_id` → stream `token` → `[done]`, trả lời có nội dung dự án.

3. Log gateway thấy dòng `gateway: bridging voice...` (voice) hoặc proxy chat khởi tạo, không có exception auth.

## 6. Ghi chú cho client (không thuộc DevOps, để tham chiếu)
Bản đang lỗi trên máy dev trỏ sai target. Target đúng khi production sẵn sàng:
- URL: `wss://<tenant>.agents.noblex.vn/v1/chat` (dùng `wss`, KHÔNG kèm `:9200` — 9200 là nội bộ sau reverse-proxy).
- Header: `Authorization: Bearer <plaintext token của tenant>`.
- **Single-domain** (không còn per-tenant subdomain): tenant KHÔNG suy từ Host nữa — chỉ suy từ API key trong Bearer, resolve qua Portal runtime-credentials API. Miễn key hợp lệ + `GATEWAY_CREDENTIALS_API_URL` trỏ đúng Portal API là đủ, không cần khớp subdomain nào.

---

## Phụ lục A — Reference

**Đóng-kết nối (close codes) của gateway** (`src/noble_agent/gateway/server.py`, `auth.py`):
| Code | Ý nghĩa | Nguyên nhân thường gặp |
|---|---|---|
| `4001 no_bearer` | Thiếu/không đúng `Authorization: Bearer ` | client chưa gắn token (header hoặc `?key=`/`?token=`) |
| `4001 bad_credential` | API key không khớp | key chưa phát / sai / đã revoke ở Portal |
| `4001 auth_api_unavailable` | Không hỏi được credential API | `GATEWAY_CREDENTIALS_API_URL` rỗng/sai, hoặc Portal API down/5xx/response hỏng — fail-closed, KHÔNG phải lỗi của khoá |
| `4004 unknown_route` | Path != `/v1/chat`,`/v1/voice` | sai path |
| `4008 handshake_timeout` | Không gửi frame handshake trong 10s | client không gửi `{identity, call_id}` |

> `bad_host` / `tenant_inactive` (subdomain-based tenant resolution) đã RETIRED — kiến trúc hiện tại là single-domain, tenant suy từ Bearer API key qua Portal runtime-credentials API (xem `gateway/auth.py` + `gateway/credentials.py`), không còn từ Host.

**Cert wildcard (certbot DNS-01):**
```bash
sudo certbot certonly --dns-<provider> -d '*.agents.noblex.vn' -d agents.noblex.vn
```
(HTTP-01 không cấp được wildcard — bắt buộc DNS-01.)

**Kiểm chứng nhanh gateway sống (nội bộ trên server):**
```bash
ss -ltnp | grep 9200          # thấy noble-gateway
# gateway là WS thuần (websockets.serve) — không có HTTP health endpoint;
# health-check bằng TCP connect tới 9200 hoặc thử WS handshake như mục 5.
```

**File liên quan trong repo:**
- `docker-compose.deploy.yml` — định nghĩa stack 3 service + hướng dẫn TLS/DNS ở header comment.
- `src/noble_agent/gateway/server.py` — routing `/v1/chat`,`/v1/voice` + xử lý handshake.
- `src/noble_agent/gateway/auth.py` — `tenant_from_host()` + `authorize()`.
- `infra/nginx/hotline-agent.noble.vn.conf` — vhost cho host KHÁC (tham khảo mẫu WS upgrade, KHÔNG tái dùng nguyên).
- `scripts/e2e_dbmode/` — `chat_via_gateway.py` (qua gateway), `chat_worker_direct.py` (thẳng worker), `portal_sim.sql` (mẫu seed control-plane), `env_dbmode.sh`.
