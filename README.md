# Odyssey Portal — Backend

Control plane cho SaaS agent chăm sóc khách hàng của NobleX. Nơi khách hàng doanh nghiệp tự cấu hình
agent, nạp dữ liệu, và xem vận hành.

> **Repo này là backend.** Frontend ở
> [odyssey-portal-frontend](https://gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/odyssey-project/odyssey-portal-frontend). Hai repo tách từ
> `odyssey-portal-fullstack` ngày 2026-07-30 — history 29 commit thời monorepo còn ở đó (đã archive).

**Trạng thái:**

| | |
|---|---|
| **M1** — nền cách ly đa-tenant | ✅ xong · 96 test xanh · 6 cổng cách ly xanh |
| **M2a-FE** — app shell (menu · route · design token · phiên giả) | ✅ xong · 46 test xanh · [README của repo frontend](https://gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/odyssey-project/odyssey-portal-frontend) |
| **M2a-BE** — auth · workspace · `require(action)` | ⏭ tiếp theo |
| M3 · M4 · M5 · M6 · M7 · M8 · M9 | chưa bắt đầu — **dựng màn được ngay** trên app shell + MSW |

**Nhận một màn thì đọc README của [repo frontend](https://gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/odyssey-project/odyssey-portal-frontend)** — nó nói rõ sửa file
nào, không sửa file nào.

## Chạy local

```bash
make dev                      # postgres 5433 · redis 6380 · minio 9000 (dev; production: Aurora + S3)
uv sync
make migrate
make test                     # tất cả (96 test)
make test-unit                # không cần Docker
make test-isolation           # 6 cổng cách ly
make test-module M=m4         # test của một module (khi module đó tồn tại)
make lint
make check                    # lint + test — chạy trước khi mở merge request
```

Sau `make migrate` lần đầu, chạy một lần để `portal_api` đăng nhập được ở máy dev:

```sql
ALTER ROLE portal_api LOGIN PASSWORD 'apidev';
```

Vì sao phải bước này: migration 0003 tạo `portal_api` ở dạng NOLOGIN không mật khẩu — fail-closed,
để không ship mật khẩu nào trong git. Chi tiết ở [.env.example](.env.example).

Frontend chạy độc lập, **không cần backend** (MSW trả dữ liệu giả) — xem
[repo frontend](https://gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/odyssey-project/odyssey-portal-frontend).

Ràng buộc production (không test được bằng testcontainers): [deploy/README.md](deploy/README.md).

## Đọc theo thứ tự này

| # | Tài liệu | Trả lời |
|---|---|---|
| 1 | [Kiến trúc & bản đồ module](docs/superpowers/specs/2026-07-29-odyssey-portal-kien-truc-va-ban-do-module.md) | Kiến trúc · **bản đồ 9 module** · đối chiếu 18 màn hình · cấu trúc repo · tech stack |
| 2 | [Hợp đồng cách ly đa-tenant](docs/contracts/isolation.md) | Đọc **trước khi viết dòng query đầu tiên** |
| 3 | [M1 — Nền cách ly đa-tenant](docs/superpowers/specs/2026-07-29-m1-nen-cach-ly-da-tenant.md) | Module đầu tiên |

Tài liệu nghiệp vụ đã chốt (copy từ `odyssey-dashboard-prototype` — **nguồn sự thật**):

| Tài liệu | Nội dung |
|---|---|
| [phan-bien-prototype](docs/product/2026-07-28-phan-bien-prototype-va-dinh-huong-san-pham.md) | 18 màn đối chiếu thực tế · phạm vi MVP · 7 quyết định sản phẩm |
| [work-packages-mvp](docs/product/2026-07-28-work-packages-mvp.md) | 8 gói việc A→H · phụ thuộc · nợ kỹ thuật |
| [PQ_01 phân quyền](docs/product/2026-07-29-pq01-phan-quyen.md) | 4 vai trò · 13 nhóm hành động · quyền hỗ trợ có hạn |
| [HT_01 quan hệ 3 lớp](docs/product/2026-07-29-ht01-quan-he-dashboard-backend-agent.md) | Dashboard · Backend · Agent · business rule |
| [control-plane-design (ref)](docs/product/2026-07-28-tenant-portal-control-plane-design.ref.md) | 22 quyết định kỹ thuật · schema · publish · tech stack |
| [slice-1a (ref)](docs/product/2026-07-28-slice-1a.ref.md) | Plan chi tiết nền cách ly · 3 sửa lỗi C1/C2/C3 |

Thiết kế gốc: `../odyssey-dashboard-prototype/design/Tenant Portal.dc.html` — **chỉ đọc**. Nó là
brainstorm, không phải yêu cầu (quyết định W1): lấy layout · state model · design token từ nó, lấy
**hành vi** từ tài liệu nghiệp vụ.

## Bản đồ module

```
M1 ──> M2a ─┬──> M3  (giao được cho người khác — spec tổng §3.3)
            ├──> M4  (2 người — nó là một CMS, không phải hai cái form)
            ├──> M5  (dev với FakePublisher; nút «Áp dụng» khoá tới khi M3 xong)
            ├──> M6 · M7 · M8
            ├──> M9  (làm cuối, xâu chuỗi M4·M5·M6)
            └──> M2b (hoãn — chờ chốt ranh giới quyền admin)
```

| M | Tên | Màn hình |
|---|---|---|
| M1 | Nền cách ly đa-tenant + hạ tầng dùng chung (`jobs` · worker · heartbeat) | *(không có UI)* |
| M2a-FE | App shell · nav registry · design token · phiên giả (MSW) | *(18 route rỗng)* |
| M2a-BE | Auth · Workspace · `require(action)` | Đăng nhập · Users (danh sách) |
| M2b | Phân quyền đầy đủ — **hoãn** | Users (đổi vai trò · mời) |
| M3 | Kho tệp · Config store · Publish | *(job/version panel)* |
| M4 | Dữ liệu BĐS | Dự án · Form Dự án · Quỹ căn · Form Quỹ căn · Lĩnh vực |
| M5 | Agent Studio | Agent & Kênh |
| M6 | Tài liệu KB | Tài liệu |
| M7 | Vận hành | Tổng quan · Hội thoại · Lịch hẹn · Cần bổ sung |
| M8 | Kết nối · Nhật ký · Lưu trữ | Tích hợp & API · Nhật ký & Dữ liệu · Cài đặt |
| M9 | Onboarding | Onboarding |

**M1 và M2a tuần tự; phần còn lại song song.** Sáu cơ chế làm việc đó chạy được: spec tổng §4.

> **M2a tách FE/BE (chốt 2026-07-30).** Spec §3.1 nói "M2a trước mọi module có UI" vì hai lý do:
> mọi màn đều sau đăng nhập, **và** M2a ship app shell mà 7 module kia treo màn lên. Lý do thứ hai
> đã xong (M2a-FE). Lý do thứ nhất **không chặn dev FE**: mỗi module ship kèm fake + MSW handler
> (spec §4②), nên dựng màn được trên phiên giả. Nên bảy module có UI **bắt đầu được ngay**, không
> chờ M2a-BE. Cái vẫn phải chờ M2a-BE là *ghép vào API thật*.

**Ba quyết định hoãn có chủ đích** (chốt 2026-07-29): agent nhận cấu hình bằng image riêng hay bundle
+ con trỏ · ai bấm được "Tạo workspace" · admin nền tảng có đọc được `tenant_data` không. Điều kiện
của từng cái ở spec tổng §3.4 — quan trọng nhất: **mặc định làm bản chặt**, vì *chặt → nới* là một
migration còn *nới → chặt* là viết lại.

## Bốn luật không được phá

Ba luật đầu **đang được CI canh hôm nay**. Luật 4 chưa — xem ghi chú của nó.

1. **Mọi truy vấn `tenant_data` đi qua `tenant_conn()`**, trong một giao dịch. Không có đường đọc
   ngoài giao dịch — nếu không thì với connection pool, request sau kế thừa workspace của request
   trước.
2. **Bảng mới trong `tenant_data` phải gọi `control.enforce_tenant_isolation()`.** Quên ⇒ CI đỏ
   (cổng 6, `tests/isolation/test_isolation_catalog.py`).
3. **Module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`.** Import ruột module
   khác ⇒ CI đỏ (`tests/test_module_boundaries.py`).
4. **Mọi endpoint khai `action` của nó** qua `require(action)` từ ngày đầu, kể cả khi phân quyền chưa
   xây (M2b hoãn). Nếu không thì lúc làm M2b sẽ phải rà lại toàn bộ endpoint, và bỏ sót một cái là
   một lỗ hổng không ai thấy.
   > **Luật này đến cùng M2a, chưa có hiệu lực ở M1.** M1 không có tầng API, không có `require()`, và
   > **không có check CI nào cho nó** — bản trước của file này viết "Route không khai `action` ⇒ CI
   > đỏ", điều đó SAI. Một luật được quảng cáo là đã tự động canh mà thực ra không, còn tệ hơn là
   > không có luật: người ta thôi kiểm bằng mắt vì tin rằng máy đang kiểm. Ghi ở đây để M2a dựng
   > `require()` **cùng** với check CI của nó, trong cùng một PR.

Và một luật quy trình: **viết contract sớm, thi công muộn.** Module giao cho người khác (như M3) phải
có `docs/contracts/<seam>.md` + spec **trước khi** module phụ thuộc nó bắt đầu — nếu không thì không
có gì để `fake` mà code.

## Tech stack

FastAPI · Pydantic v2 · uvicorn · **asyncpg thô (không ORM)** · **Aurora PostgreSQL** ở production (devops chuyển lúc deploy; dev: container Postgres bản mới nhất — [khoảng hở version](deploy/README.md)) · Redis · **Amazon S3** (dev: MinIO — chuẩn
S3) · React 18 · Vite · TypeScript strict · Tailwind 4 · shadcn/ui · TanStack Router + Query v5 ·
pytest + testcontainers.

**Không dùng:** ORM · Celery/RabbitMQ · Next.js · K8s operator. Lý do ở
[control-plane-design](docs/product/2026-07-28-tenant-portal-control-plane-design.ref.md) §10.3–§10.6.
