# Image của `odyssey-portal-frontend`. Build tĩnh rồi phục vụ bằng nginx —
# portal là SPA, không có SSR (spec §6.1 đã loại Next.js). Multi-stage để image
# cuối không mang node_modules.
#
#   docker run -d -p 80:80 \
#     -e ODYSSEY_PORTAL_API_UPSTREAM=http://odyssey-portal-backend:8100 \
#     <registry>/odyssey-portal-frontend:<tag>
#
# Xem deploy/README.md.

# ─── Tầng build ───────────────────────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app

# Chỉ hai file này trước: cài dependency là tầng nặng nhất, và nó chỉ nên vỡ
# cache khi package-lock.json đổi — không phải mỗi lần sửa một dòng trong src/.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# MSW phải TẮT ở production — nếu không, dữ liệu giả hiện cho khách hàng thật.
ENV VITE_MSW=0
# Lip sync qua nginx CÙNG ORIGIN (khối /lipsync/ ở deploy/*.conf.template) — giá trị
# giống nhau ở mọi môi trường nên đặt cứng ở đây, không qua env server (biến VITE_*
# nhúng vào bundle lúc build, đặt lúc chạy không có tác dụng).
ENV VITE_AVATAR_WS_URL=/lipsync/avatar
RUN npm run build

# Cùng cổng MSW mà job `build` trên CI canh, lặp lại ở đây có chủ đích: image
# build được cả bằng tay trên máy dev, ngoài đường đi của CI. Cổng chỉ sống ở CI
# là cổng vắng mặt đúng lúc ai đó vội.
RUN test -d dist/assets || { echo "LỖI: dist/assets/ không tồn tại — gate MSW không kiểm được gì"; exit 1; } \
 && if grep -rlE 'mockServiceWorker|setupWorker|onUnhandledRequest' dist/assets/; then \
      echo "LỖI: dấu vết msw trong bundle production"; exit 1; \
    fi

# `public/demo-*.html` là BẢN VẼ thiết kế cho dev (mở ở localhost:5273), không
# phải trang của sản phẩm — mà Vite chép nguyên `public/` vào `dist/`. Không gỡ
# thì môi trường thật phục vụ ~324 KB bản nháp với số liệu giả cho ai gõ đúng URL.
RUN rm -f dist/demo-*.html

# ─── Tầng runtime ─────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

# /etc/nginx/templates/ là cơ chế có sẵn của image nginx: lúc khởi động nó chạy
# envsubst trên mọi *.template ở đây rồi ghi kết quả sang /etc/nginx/conf.d/.
# Không cần entrypoint tự viết.
COPY deploy/odyssey-portal-frontend.conf.template /etc/nginx/templates/default.conf.template

# Giới hạn envsubst chỉ đụng vào biến có tiền tố ODYSSEY_PORTAL_. Không có dòng
# này thì $uri, $host, $scheme trong file template cũng bị thay — đó là biến của
# nginx, thay đi là nginx không khởi động được.
ENV NGINX_ENVSUBST_FILTER=^ODYSSEY_PORTAL_
# Mặc định cho upstream của khối /lipsync/: envsubst KHÔNG thay biến chưa khai, để lại
# `${...}` nguyên văn và nginx không khởi động. Token (ODYSSEY_PORTAL_MODELS_TOKEN) cố ý
# KHÔNG đặt ở đây (không bao giờ để bí mật trong image) — compose luôn khai nó (rỗng
# nếu thiếu); `docker run` tay thì phải `-e` nó (deploy/README.md).
ENV ODYSSEY_PORTAL_LIPSYNC_UPSTREAM=http://lipsync-musetalk:8020

# Giá trị mặc định trỏ tới service backend theo tên DNS nội bộ, cổng 8100 (khớp
# EXPOSE của repo odyssey-portal-backend). Devops ghi đè bằng -e khi tên/cổng
# khác. KHÔNG có dấu / ở cuối — xem chú thích proxy_pass trong file template.
ENV ODYSSEY_PORTAL_API_UPSTREAM=http://odyssey-portal-backend:8100
# Gateway agent cho `/v1/` (WS chat/voice) — container của odyssey-agent trên cùng odyssey-network.
ENV ODYSSEY_PORTAL_AGENT_GATEWAY_UPSTREAM=http://odyssey-agent-gateway-1:9200

EXPOSE 80

# wget có sẵn trong busybox của alpine, không phải cài thêm gì.
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1/healthz || exit 1
