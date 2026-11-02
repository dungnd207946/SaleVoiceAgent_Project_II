# Vận hành — ràng buộc không kiểm được bằng test

Các việc dưới đây **không test được trong testcontainers** (ở đó `POSTGRES_USER`
chính là bootstrap superuser — tức `portal_migrator` chạy với quyền superuser
suốt bộ test, điều mà production tuyệt đối không được để xảy ra). Chúng là
ràng buộc của runbook deploy, và nếu sai thì cách ly vỡ **âm thầm** — app chạy
bình thường, chỉ dữ liệu là rò.

## 1. `portal_migrator` phải là non-superuser

```sql
CREATE ROLE portal_migrator LOGIN PASSWORD '<bí mật>' CREATEROLE;
-- KHÔNG: SUPERUSER, KHÔNG: BYPASSRLS
ALTER SCHEMA portal      OWNER TO portal_migrator;
ALTER SCHEMA control     OWNER TO portal_migrator;
ALTER SCHEMA tenant_data OWNER TO portal_migrator;
-- KHÔNG còn `agent_api` — migration `0917` đã DROP SCHEMA hẳn (agent đọc thẳng
-- tenant_data từ đó). Dòng ALTER SCHEMA cho nó sẽ lỗi "schema does not exist"
-- nếu chạy trên DB đã ở HEAD `0917` trở lên.
```

**Vì sao:** superuser bỏ qua RLS **bất kể `FORCE`**. Nếu `portal_migrator` là
superuser thì `FORCE ROW LEVEL SECURITY` không bảo vệ gì, và cổng test 3 ở môi
trường thật là vô nghĩa.

`CREATEROLE` là cần: `control.create_agent_role()` chạy `CREATE ROLE`.

## 2. `portal_migrator` chỉ chạy migration, không phục vụ

Tiến trình API và worker nối bằng **`portal_api`**. Không tiến trình nào nối
bằng `portal_migrator`.

**Vì sao:** `portal_migrator` là owner của bảng. RLS + `FORCE` áp cho owner
nhưng không có lý do gì để chạy runtime bằng role có toàn quyền DDL. Ở container
dev/test nó còn là bootstrap superuser — và superuser đi xuyên RLS **bất kể
`FORCE`**, nên runtime nối bằng nó là runtime không có cách ly.

**Hai biến, hai role — không gộp:**

| Biến | Role | Ai đọc |
|---|---|---|
| `DATABASE_URL` | `portal_api` | API · worker (`Settings.database_url`) |
| `MIGRATOR_URL` | `portal_migrator` | **chỉ** `alembic` (`Settings.alembic_url` suy từ đây) |

Trước bản này chỉ có `DATABASE_URL`, `alembic_url` là chính nó đổi driver, và
default trỏ `portal_migrator` — tức cấu hình duy nhất chạy được cả hai lệnh là
cấu hình **không an toàn**. Phần default của repo giờ có test canh
(`tests/unit/test_config.py::test_default_runtime_khong_bao_gio_la_portal_migrator`);
phần môi trường thật vẫn là luật của runbook này.

## 3. Mật khẩu `portal_api` — migration KHÔNG đặt, và đó là chủ ý

Migration `0003` tạo `portal_api` ở dạng **`NOLOGIN`, không mật khẩu**. Không có
mật khẩu nào của role runtime nằm trong git.

**Vì sao đổi:** bản trước ghi `CREATE ROLE portal_api LOGIN PASSWORD 'apidev'`.
`portal_api` được phép `SET app.tenant_id` sang giá trị nào cũng được, nên mật
khẩu đó là quyền đọc-ghi đầy đủ trên **mọi** tenant cho bất kỳ ai với tới được
cổng Postgres. Runbook có ghi "nhớ đổi placeholder" thì cũng chỉ là nhờ vào việc
ai đó nhớ — mà cả module này tồn tại để không phải nhờ vào điều đó.

**Hệ quả: hệ FAIL CLOSED.** Sau khi migration chạy, bắt buộc:

```sql
ALTER ROLE portal_api LOGIN PASSWORD '<bí mật>';
```

và đặt `DATABASE_URL` cho khớp. **Quên bước này thì app không nối được chút nào**
— lỗi to, thấy ngay lúc deploy — thay vì nối được bằng một mật khẩu đã công bố
trong repo. Đó chính là điểm của thiết kế: chế độ hỏng khi quên là "dừng", không
phải "chạy mà hở".

`tests/conftest.py` làm đúng bước đó sau `alembic upgrade head` (nó nối bằng
bootstrap superuser của container nên `ALTER ROLE` được), với `API_PASSWORD` là
nguồn duy nhất của mật khẩu test.

Mật khẩu của `agent_<tenant>` **không** đến từ migration — `control.create_agent_role(tenant, password)`
nhận mật khẩu làm tham số. Quy trình cấp workspace (M9) phải:

1. sinh mật khẩu ngẫu nhiên (đủ entropy, không tái dùng) cho mỗi `agent_<slug>`;
2. gọi `control.create_agent_role(slug, <mật khẩu ngẫu nhiên>)`;
3. **đẩy mật khẩu đó vào đúng nơi pod của agent workspace đó đọc được** — secret
   của CI/K8s (hoặc tương đương ở môi trường deploy thật), gắn với đúng `slug`.

Việc thứ 3 trước đây không ai ghi ra — nếu bỏ qua, agent có role hợp lệ trong
Postgres nhưng không có gì để dùng nó, hoặc tệ hơn, ai đó tạm gán một mật khẩu
dùng chung cho nhiều workspace.

### 3.1 `odyssey_agent` — cùng luật, và rủi ro cao hơn một bậc

Migration `0901` tạo `odyssey_agent` (role dùng chung của agent hội thoại — hợp đồng
`docs/contracts/agent-postgres-read-contract.md` §0) cũng ở dạng **`NOLOGIN`, không
mật khẩu**, cùng lý lẽ với §3. Sau migration, bắt buộc:

```sql
ALTER ROLE odyssey_agent LOGIN PASSWORD '<bí mật>';
```

**Vì sao mật khẩu này phải được giữ chặt hơn mọi mật khẩu agent khác:** khác với
`agent_<slug>` — chỉ mở được đúng một workspace vì tenant suy từ *tên role* —
`odyssey_agent` suy tenant từ lời khai `app.tenant_id` mà chính agent đặt. Nên một
mật khẩu `odyssey_agent` bị lộ là quyền đọc **mọi** workspace, không phải một. Ba
hệ quả cho vận hành:

1. Không đặt nó cạnh mật khẩu per-tenant trong cùng một secret — bán kính thiệt hại
   khác nhau thì chỗ lưu và quyền xem cũng phải khác nhau.
2. Phải xoay được, và phải có người biết cách xoay trước khi nó cần được xoay.
3. Hạn chế đường mạng tới cổng Postgres cho đúng host chạy agent, nếu môi trường
   deploy cho phép. Đây là lớp bù duy nhất còn lại sau khi bỏ cách ly theo role.

Quên bước `ALTER ROLE` thì agent **không nối được** — fail-closed, cùng tinh thần §3.

Nghĩa vụ phía agent (Portal không kiểm được từ DB, phải có trong hợp đồng bàn giao):
khai tenant bằng `SET LOCAL` / `set_config(..., true)` **trong một giao dịch tường
minh**, không bao giờ `SET` trần. Vì sao `SET` trần là lỗ hổng thật:
`tests/isolation/test_pool_leak.py::test_set_tran_song_qua_ranh_gioi_giao_dich_tren_cung_ket_noi`.
Cái Portal cưỡng chế được và đã có cổng canh: không khai tenant thì đọc ra 0 hàng
(`tests/isolation/test_role_agent_dung_chung.py`).

## 4. Migration có backfill dữ liệu

`FORCE ROW LEVEL SECURITY` áp cho owner, nên migration **backfill** (không chỉ
DDL) sẽ bị lọc và thấy 0 hàng. Hai cách đúng:

```python
# Cách 1: đặt phạm vi cho từng tenant
op.execute("SET LOCAL app.tenant_id = 'anphu'")
op.execute("UPDATE tenant_data.units SET ... WHERE ...")

# Cách 2: tắt FORCE trong CÙNG migration, bật lại ngay
op.execute("ALTER TABLE tenant_data.units NO FORCE ROW LEVEL SECURITY")
op.execute("UPDATE tenant_data.units SET ...")
op.execute("ALTER TABLE tenant_data.units FORCE ROW LEVEL SECURITY")
```

Cách 2 phải bật lại **trong cùng migration** — để lại `NO FORCE` là cổng test 6
đỏ ở PR tiếp theo, nhưng trong khoảng đó cách ly đã hở.

## 5. Cấp một workspace — bốn việc, cả-bốn-hoặc-không

M1 chỉ ship việc thứ hai. Ghép lại là M3/M9.

| # | Việc | Ở module |
|---|---|---|
| 1 | `INSERT` hàng `control.tenants` | M1 (schema) · M9 (luồng) |
| 2 | `control.create_agent_role(slug, <mật khẩu ngẫu nhiên>)` + đẩy mật khẩu vào secret | **M1** |
| 3 | Tạo collection Qdrant `kb_<slug>` | M6 |
| 4 | Tạo tiền tố `tenants/<slug>/` trên kho tệp + credential giới hạn đúng tiền tố đó — **S3 + IAM policy** ở production, MinIO + access key ở dev (§7) | M3 |

> Mọi quyền của agent đến từ role nhóm `agent_all`. Thêm bảng agent ghi được thì
> gọi `control.grant_agent_write('tenant_data.<bảng>')` **một lần** trong migration
> của module đó — không phải quét danh sách role đang tồn tại, và role tạo về sau
> cũng có ngay.

## 6. Aurora PostgreSQL — ba điều đổi so với Postgres tự dựng

Chốt 2026-07-30: production dùng **Aurora PostgreSQL**; dev/test giữ container.

### 6.1 Major version dev KHÔNG khớp Aurora — khoảng hở đã biết, không phải đã đóng

**Chốt 2026-07-30 (devops):** dev/test dùng Postgres bản mới nhất như bình thường
(`postgres:18-alpine`); devops chuyển sang Aurora lúc deploy. Version pin ở **hai**
file — `docker-compose.dev.yml` và `tests/conftest.py` — mỗi file có comment trỏ
sang file kia.

**Ghi ra đây vì nó không được kiểm bởi bất cứ thứ gì tự động.** Aurora PostgreSQL
luôn chậm hơn community Postgres vài major, nên dev gần như chắc chắn **cao hơn**
production. Việc devops đổi connection string lúc deploy **không** kiểm rằng SQL
của dự án chạy được trên major của Aurora — nó chỉ đổi chỗ kết nối.

Rủi ro **hôm nay thấp**: mọi thứ migration đang dùng — RLS, `FORCE ROW LEVEL
SECURITY`, `CREATE POLICY`, `CREATE ROLE`, plpgsql — là tính năng từ Postgres 9.5,
chạy trên mọi major Aurora đang có. **Nhưng nó không có chặn trên:** không gì ngăn
một migration về sau dùng cú pháp chỉ có ở major của dev. Test xanh, CI xanh, và
chỉ Aurora biết — đúng loại hỏng âm thầm mà cả module cách ly này tồn tại để tránh.

**Khi devops chuyển sang Aurora, ba việc phải làm một lần:**

1. Lấy major thật: `SELECT current_setting('server_version_num'), aurora_version();`
   (`aurora_version()` không tồn tại nghĩa là **không** phải Aurora — quan trọng hơn con số.)
2. Chạy `alembic upgrade head` trên một cluster Aurora **dùng thử** trước khi chạy
   trên cluster thật. Đây là chỗ duy nhất bắt được cú pháp không tương thích, vì
   testcontainers không bao giờ chạy trên Aurora.
3. Đối chiếu major đó với §6.3 — cảnh báo ở đó **chỉ áp dụng từ PG16**.

### 6.2 Aurora KHÔNG có superuser thật — điều đó đổi lý lẽ của §1, không xoá nó

Master user của Aurora chỉ là thành viên `rds_superuser`, **không** có thuộc tính
`rolsuper`. RLS chỉ bị đi xuyên bởi `rolsuper` hoặc `BYPASSRLS`, nên:

- Sự cố mà §1 cảnh báo — *lỡ tạo `portal_migrator` thành superuser* — ở Aurora là
  **bất khả thi về mặt cấu trúc**. `CREATE ROLE ... SUPERUSER` bị từ chối.
- Nhưng **phần còn lại của §1 vẫn nguyên giá trị**: `portal_migrator` là **chủ
  bảng**, và chủ bảng đi xuyên RLS **trừ khi có `FORCE`**. `FORCE` là thứ đang
  giữ, không phải việc thiếu superuser. Đừng đọc mục này thành "Aurora nên §1 hết
  cần".
- `BYPASSRLS` thì Aurora **cho** cấp. Test `test_khong_co_role_nao_co_bypassrls`
  canh đúng chuyện đó và nó chạy ở mọi merge request.

Hệ quả ngược chiều đáng biết: **testcontainers chạy ở môi trường LỎNG HƠN
production** (ở đó `POSTGRES_USER` là bootstrap superuser thật). Nghĩa là cổng
test 3 chứng minh được ít hơn ở dev so với thực tế Aurora — an toàn theo chiều
đúng, nhưng đừng suy ra "test xanh nên Aurora chắc chắn ổn".

### 6.3 `create_agent_role()` — rủi ro ADMIN OPTION, chỉ nổ ở production

`control.create_agent_role()` chạy đúng hai lệnh:

```sql
CREATE ROLE agent_<slug> LOGIN PASSWORD '<...>';
GRANT agent_all TO agent_<slug>;
```

Từ **Postgres 16**, một role `CREATEROLE` non-superuser cần **ADMIN OPTION** trên
`agent_all` mới `GRANT` được nó. **Mục này chỉ áp dụng nếu Aurora là major ≥ 16** —
trên 15 thì `CREATEROLE` grant được mọi role và cả mục 6.3 không liên quan. Kiểm
major trước khi đi kiểm cái này, đừng đi tìm một vấn đề không tồn tại. `portal_migrator` có ADMIN OPTION **ngầm** vì
chính nó tạo `agent_all` ở migration `0003` — nên chuỗi này đúng, **với điều kiện
`agent_all` do `portal_migrator` tạo qua migration**.

⚠️ **Nếu ai tạo `agent_all` bằng tay với master user của Aurora** (ví dụ khi dựng
cluster, để "chuẩn bị sẵn"), thì `portal_migrator` **không** có ADMIN OPTION, và
`create_agent_role()` vỡ ở bước `GRANT` — **lúc cấp workspace, ở production**.
Testcontainers không bắt được: ở đó user là superuser thật nên `GRANT` luôn chạy.

**Luật: `agent_all` chỉ được tạo bởi migration `0003`.** Đừng tạo tay. Kiểm sau
khi dựng cluster:

```sql
SELECT r.rolname, m.admin_option
FROM pg_auth_members m
JOIN pg_roles r ON r.oid = m.member
JOIN pg_roles g ON g.oid = m.roleid
WHERE g.rolname = 'agent_all' AND r.rolname = 'portal_migrator';
-- phải có một hàng với admin_option = true
```

### 6.4 Endpoint: dùng writer cho cả hai DSN

`DATABASE_URL` và `MIGRATOR_URL` đều trỏ **writer endpoint** (`.cluster-`). Reader
endpoint (`.cluster-ro-`) không dùng được cho đường hiện tại: mọi truy vấn
`tenant_data` nằm trong giao dịch có `SET LOCAL app.tenant_id`, và migration thì
ghi. Nếu về sau thêm đường đọc thuần thì đó là **một biến mới**, không phải sửa
hai biến này.

### 6.5 Còn treo — M9 phải quyết

`create_agent_role()` là **SECURITY INVOKER** (không có `SECURITY DEFINER`), nên
`portal_api` gọi không được — nó không có `CREATEROLE`. Luồng cấp workspace vì thế
buộc chạy bằng `portal_migrator`, hơi căng với §2 (*"`portal_migrator` chỉ chạy
migration, không phục vụ"*). Hai hướng cho M9: một tiến trình provisioning riêng
dùng `MIGRATOR_URL` (không nằm trên đường request), hoặc đổi hàm thành
`SECURITY DEFINER` với owner là `portal_migrator`. **Chưa chốt** — ghi ra để M9
không phát hiện muộn.

## 7. Kho tệp: S3 ở production, MinIO ở dev

Chốt 2026-07-30, **thay quyết định #22** (kho tệp = MinIO tự dựng trong nước).

> **Quyết định #22 bị thay, và lý do gốc của nó là pháp lý — không phải kỹ thuật.**
> #22 chọn MinIO tự dựng vì #19 đưa nội dung hội thoại (tên, số điện thoại) vào
> kho tệp, và đặt ngoài Việt Nam là **chuyển dữ liệu cá nhân ra nước ngoài (NĐ 13
> Điều 25)**. Tự dựng trong nước *làm câu hỏi đó biến mất thay vì phải trả lời*.
> Cột "bị loại" của #22 ghi đúng phương án nay được chọn: *"S3/mây"*.
>
> **Chuyển sang S3 nghĩa là câu hỏi đó quay lại và phải được trả lời** — đã có
> **sign-off pháp lý (chốt 2026-07-30)**. Cùng lúc, `contacts`/`appointments`/
> `conversations` (M7) nằm trong `tenant_data`, nên **Aurora cũng nằm trong phạm
> vi cùng nghĩa vụ**, không chỉ kho tệp. Ai đọc mục này về sau: hai thứ cần giữ
> cùng nhau là *hồ sơ NĐ 13* và *vùng đặt dữ liệu của cả Aurora lẫn S3*.
>
> `docs/product/*` là bản copy từ `odyssey-dashboard-prototype` (nguồn sự thật) nên
> **không sửa ở repo này** — #22 vẫn nguyên văn ở đó. Cập nhật repo prototype là
> việc riêng.

### 7.1 Cơ chế cách ly không đổi, chỉ đổi cách khai

Cổng test 7 kiểm: *credential của workspace A `GET` một đường dẫn dưới
`tenants/B/` phải bị **từ chối***. Cơ chế vẫn là **policy theo tiền tố**:

| | Khai bằng | Gắn cho |
|---|---|---|
| Production | IAM policy (`Condition` trên `s3:prefix` / `Resource` `arn:aws:s3:::<bucket>/tenants/<slug>/*`) | IAM role hoặc user của workspace |
| Dev · test | MinIO policy theo tiền tố | access key của workspace |

Vì cả hai đều là S3 protocol, **client `aioboto3` y hệt** — chỉ `S3_ENDPOINT_URL`
khác. Đó là lý do dev giữ MinIO: cổng 7 chạy thật, offline, không tốn tiền.

⚠️ **Cổng 7 ở dev chỉ chứng minh cơ chế, không chứng minh IAM policy production
viết đúng.** MinIO policy và IAM policy là hai cú pháp khác nhau. M3 phải kèm một
lần kiểm tay trên bucket thật, hoặc một test chạy được với credential AWS thật.

### 7.2 Xác thực: IAM role, không key trong env

Production **không có** `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` trong env.
Tiến trình nhận quyền qua IAM role gắn vào task/instance. Env chỉ cần
`AWS_REGION` + `S3_BUCKET` — xem `.env.example`.

Cùng tinh thần với §3 (`portal_api` NOLOGIN, không mật khẩu trong git): **không
secret nào trong cấu hình thì không có secret nào rò.**

### 7.3 Hệ quả của #22 giờ thuộc về AWS

#22 nhận một hệ quả: *"sao lưu/phục hồi là việc của NobleX"* — kho tệp mang cả
retention 6 tháng (#19) lẫn khả năng agent boot khi Postgres chết (E01). Với S3,
phần đó chuyển sang AWS (versioning + lifecycle + cross-region replication nếu
cần). **Nhưng nghĩa vụ thì không chuyển:** retention 6 tháng và xoá-theo-số-điện-
thoại (NĐ 13) vẫn phải cấu hình tường minh. Lifecycle rule xoá sớm hơn 6 tháng là
vỡ hợp đồng; không có đường xoá theo prefix là vỡ nghĩa vụ NĐ 13.

## 8. Deploy — một image, bảy vai

Vai `dinh-gia` **không nằm trong pipeline deploy** — nó là job hằng đêm, xem
[`systemd/README.md`](systemd/README.md). Tiền thì KHÔNG phụ thuộc nó: từ
migration `0950`, `billing.rated_usage` được ghi trong chính câu `INSERT` vào
`billing.usage_events`. Job đêm là lưới an toàn cho ba ca trigger không với tới.

Repo này sinh ra **một** image, đẩy lên ECR của NobleX:

```
418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/odyssey-portal-backend:<tag>
```

Repository trên ECR (`aidc/odyssey-portal-backend`) **phải tồn tại trước** — ECR
không tự tạo repository lúc `push`, và lỗi trả về là `repository does not exist`.

Mọi lệnh `pull`/`push` cần đăng nhập trước, nếu không lỗi là *"no basic auth
credentials"* chứ không phải *"image không tồn tại"*:

```sh
aws ecr get-login-password --region ap-southeast-1 \
  | docker login --username AWS --password-stdin 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com
```

Image đó chạy được bảy vai, chọn bằng đối số (`deploy/entrypoint.sh`): ba vai dưới đây, `worker` (§8.4),
`dinh-gia`, `crawl` và `crawl-worker` (xem [`systemd/README.md`](systemd/README.md)). Không có vai nào khác.
`crawl-worker` chạy từ image tag `<tag>-crawl` (Dockerfile tầng `crawl`, có Chromium) và từ 2026-10-05 nằm
trong `docker-compose.onprem.yaml` như một service thường — tự đọc lịch của từng workspace từ DB.

| Vai | Lệnh | Hình dạng | Credential |
|---|---|---|---|
| `serve` *(mặc định)* | `… odyssey-portal-backend:<tag>` | service chạy mãi, cổng **8100** | `DATABASE_URL` — role `portal_api` |
| `migrate` | `… odyssey-portal-backend:<tag> migrate` | chạy một lần rồi thoát | `MIGRATOR_URL` — role `portal_migrator` |
| `seed-owner` | `… odyssey-portal-backend:<tag> seed-owner` | chạy một lần rồi thoát, **một lần MỖI MÔI TRƯỜNG** | `DATABASE_URL` — role `portal_api` |

`seed-owner` dùng `DATABASE_URL`, **không** `MIGRATOR_URL`: việc của nó là DML trên
schema `control`, mà §1 đã GRANT đủ cho role runtime. Entrypoint từ chối nó nếu
thấy `MIGRATOR_URL`, cùng lý lẽ với vai `serve` — xem §8.5.

**Một image chứ không hai** vì migration và runtime phải là cùng một bản code.
Hai image build riêng là hai thứ trôi ra khỏi nhau, và cái trôi lệch chỉ lộ ra
lúc migration tạo cột mà code chưa biết — trên production.

**Hai file env chứ không một** vì §1–§2. `deploy/entrypoint.sh` **từ chối khởi
động** vai `serve` nếu thấy `MIGRATOR_URL` trong môi trường. Đó không phải khó
tính: cách hỏng thường gặp nhất là dùng chung một file env cho cả hai vai —
hoàn toàn hợp lý nếu không ai nói, và **không có gì báo sai**. Container vẫn
xanh, request vẫn 200, chỉ là RLS không còn hiệu lực. Xem
`deploy/odyssey-portal-backend.env.example` và
`deploy/odyssey-portal-migrate.env.example`.

### 8.1 Thứ tự một lần deploy

Bằng compose — đây là đường đi mà job `deploy:dev` / `deploy:prod` của
`.gitlab-ci.yml` chạy, và `docker-compose.dev.yml` là **file deploy** (xem §8.6):

```sh
export IMAGE_TAG=<sha ngắn của commit, lấy ở log job build>

docker network create odyssey-network      # một lần mỗi máy, §8.5
aws ecr get-login-password --region ap-southeast-1 \
  | docker login --username AWS --password-stdin 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com

docker compose -f docker-compose.dev.yml pull

# 1. Migration TRƯỚC. `run --rm` chứ không `up -d migrate`: nó chạy đồng bộ và
#    trả đúng exit code, nên migration đỏ dừng được cả lần deploy.
docker compose -f docker-compose.dev.yml run --rm migrate

# 2. Rồi mới thay phiên bản của service.
docker compose -f docker-compose.dev.yml up -d --no-build --wait
```

Bằng `docker run`, nếu cần soi từng bước:

```sh
IMG=418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/odyssey-portal-backend:$IMAGE_TAG

docker run --rm --network odyssey-network \
  --env-file deploy/odyssey-portal-migrate.env "$IMG" migrate

docker run -d --name odyssey-portal-backend \
  --network odyssey-network \
  --env-file deploy/odyssey-portal-backend.env \
  -p 8100:8100 "$IMG"
```

`--network odyssey-network` ở **cả hai** lệnh: thiếu ở bước 1 thì migration không
phân giải nổi host trong `MIGRATOR_URL`; thiếu ở bước 2 thì API chạy bình thường
nhưng nginx của frontend không thấy tên `odyssey-portal-backend` và **từ chối khởi
động** (`[emerg] host not found in upstream`).

Migration đi trước vì code mới có thể cần cột mới. Ngược lại — code mới lên
trước migration — là 500 hàng loạt trong khoảng giữa.

⚠️ **Chạy `migrate` đúng một lần cho mỗi lần deploy, không phải một lần cho mỗi
replica.** Alembic có bảng `alembic_version` nên lần thứ hai là no-op, nhưng hai
tiến trình chạy **cùng lúc** trên một migration chưa áp thì tranh nhau khoá DDL.

### 8.2 Lần deploy đầu tiên có thêm một bước

Migration `0003` tạo `portal_api` ở dạng `NOLOGIN` **không mật khẩu** — §3. Nên
sau `migrate` lần đầu, `DATABASE_URL` chưa nối được. Đặt mật khẩu thật một lần
(`ALTER ROLE portal_api LOGIN PASSWORD '<bí mật>'`, xem §3) rồi mới sang bước 2.

Quên bước này thì service **không khởi động nổi** — lỗi to, thấy ngay. Đó là chủ
ý, không phải thiếu sót.

Cùng bước đó cho `odyssey_agent` nếu môi trường này phục vụ agent hội thoại — §3.1.
Nó không chặn service của Portal khởi động (chỉ agent không nối được), nên đây là
bước dễ bỏ sót nhất trong cả trang: hệ trông như xanh hoàn toàn.

Và **sau khi service lên xanh, vẫn còn một bước nữa** — §8.2.1. Hệ có thể xanh
hoàn toàn mà không một ai đăng nhập được.

### 8.2.1 Không ai đăng nhập được — vai `seed-owner`

> Đánh số `8.2.1` chứ không `8.5`: `8.5`–`8.7` đã có chủ (network · hai file
> compose · mật khẩu Redis), và đây đúng là bước thứ hai của §8.2.

**Migration không seed người dùng nào, và không có route đăng ký công khai.** Nên
một môi trường vừa `migrate` xong là một môi trường mà `/healthz` trả 200 và
không ai vào được. Đó không phải lỗi cấu hình; đó là bước này chưa chạy.

Vì sao không có đường nào khác: `POST /users` đòi một owner **đang đăng nhập**
(`_lay_owner()`), và `dang_nhap()` còn raise `khong_co_workspace()` nếu người đó
chưa thấy workspace nào. Quả trứng-và-gà hai lớp. `scripts/dev_seed.py` không
thay được: `kiem_localhost()` chặn nó ngoài máy dev, đúng như vậy — nó ghi mật
khẩu nằm trong repo vào `control.users`.

Chạy một lần, sau `migrate`, trước khi bàn giao:

```bash
cd /home/gitlab-runner/odyssey/odyssey-portal-backend
SEED_OWNER_EMAIL=dang@noblex.vn \
SEED_ORG_ID=noble \
SEED_ORG_NAME='NobleX' \
SEED_PORTAL_URL=https://portal.noblex.vn \
  docker compose -f docker-compose.dev.yml run --rm seed-owner
```

Nó in ra **một link mời**. Gửi link đó cho owner; họ tự đặt mật khẩu ở
`/invite/<token>`, hạn 7 ngày. **Không ai — kể cả người chạy lệnh — biết mật khẩu
đó**, vì vai này không bao giờ ghi `password_hash`. Link chỉ ra stdout của lệnh,
không ghi xuống file nào trên máy deploy.

Nó tạo đủ bốn thứ trong **một** giao dịch: tổ chức (trigger `0104` tự seed 4 vai
trò) · owner `lifecycle='pending'` · một workspace (không có nó thì đăng nhập
raise `khong_co_workspace()`) · hàng `control.invites` chỉ chứa `sha256(token)`.

Ba điều về việc chạy lại:

- **Đã có tài khoản `active` → nó TỪ CHỐI.** Từ đó trở đi `POST /users` là công cụ
  đúng, và đường đó có phép kiểm `org_role='owner'`; đường này thì không.
- **Owner còn `pending` → nó mời lại**, và token cũ **chết** (`ghi_loi_moi` UPSERT
  theo `user_id`). Dùng khi log bị cuộn mất link, hoặc lời mời hết hạn.
- **Không sinh thêm workspace** ở lần chạy thứ hai.

Mất mật khẩu owner duy nhất và không còn ai mời lại được: `UPDATE control.users SET
lifecycle='pending', password_hash=NULL WHERE email='…'` rồi chạy lại lệnh trên.

**KHÔNG cắm vai này vào pipeline deploy.** Nó phát một link dùng một lần; một job
tự chạy mỗi lần deploy sẽ hoặc bị chính nó từ chối (đã có user `active`), hoặc
chôn link trong log của lần deploy thứ 40 mà không ai đọc.

### 8.3 Health check

`GET /healthz` → `200 {"status":"ok"}`. Không cần xác thực. Image đã khai sẵn
`HEALTHCHECK` của Docker; nếu devops dùng load balancer riêng thì trỏ probe vào
đúng đường đó.

⚠️ Endpoint này chỉ trả lời *"tiến trình còn sống"*. Nó **không** kiểm tra
Postgres hay Redis, nên nó xanh cả khi database đã chết. Đừng dùng nó làm căn cứ
"hệ thống khoẻ".

### 8.4 Worker — vai `worker`, service `worker` (thêm 2026-08-05)

Bản trước của mục này nói *"chưa deploy, có chủ đích"* và đặt điều kiện: thêm
**cùng lúc với `jobs.py` đầu tiên**. Điều kiện đó đã tới và đã làm — vai `worker`
trong `deploy/entrypoint.sh`, service `worker` trong cả hai file compose.

**Ai cần nó.** `src/portal/modules/kb/jobs.py` — `kb_index` · `kb_delete` ·
`kb_reconcile`. `POST /api/v1/kb/{entity}/{id}/reindex` trả 202 vì việc thật là
embedding qua Qwen-VL, khoảng 30 giây; không nhét được vào một HTTP request.
**Không có worker thì reindex trả 202 rồi im lặng vĩnh viễn** — RAG không có dữ
liệu mới, và không một dòng log nào nói vì sao.

`modules/config/jobs.py` cũng còn `register()` `publish`/`rollback`, nhưng hai
đường đó **không còn đi qua worker**: chúng chạy đồng bộ trong request từ
2026-08-05 (§8.4.1). Handler chỉ còn để tiêu hoá những hàng `queued` tồn từ trước.

**Cấu hình.** Chung image, chung file env `deploy/odyssey-portal-backend.env` với
vai `serve` — cũng nối bằng `portal_api`, cũng bị entrypoint **chặn**
`MIGRATOR_URL`, và vì lý do mạnh hơn: một job handler quên `WHERE` chạy trên mọi
tenant mà không một request nào ghi lại và không người dùng nào nhìn thấy. Nó nằm
trong `odyssey-network` như hai vai kia (§8.5) và không mở cổng nào.

**Chạy nhiều bản là an toàn.** `run_once()` nhặt job bằng `FOR UPDATE SKIP LOCKED`
(`portal/core/jobs.py`), nên hai worker không nhặt trùng và không xếp hàng sau
nhau. Vì vậy service này **không** đặt `container_name`.

**Kiểm nó có sống.** Worker không có endpoint health. Dùng hàng đợi:

```sql
SELECT state, kind, count(*), min(created_at) FROM control.jobs GROUP BY 1,2;
```

Có hàng `queued` cũ hơn vài phút = worker không chạy hoặc đang tắc.

### 8.4.1 Publish agent config KHÔNG đi qua worker

`POST /api/v1/config/publish` và `POST /api/v1/config/versions/{v}/rollback` trả
**200 và làm việc ngay trong request** (trước 2026-08-05: 202 + `jobId`).

Vì sao đổi: hai endpoint đó chỉ ghi một hàng `config_versions` và dịch con trỏ
`config_live` — vài trăm ms. Còn 202 thì cần worker, và trong suốt thời gian worker
chưa deploy thì **mọi lần người dùng bấm «Lưu và áp dụng» đều trả 202 rồi không có
gì xảy ra**: không log, không lỗi, chỉ một hàng `queued` không ai nhìn. Một API nói
"đã nhận" khi không có ai nhận thì tệ hơn một API chờ 300ms.

Đua `MAX(version)+1` giữa hai publish song song — trước đây do worker retry đỡ — giờ
do `pg_advisory_xact_lock` theo `tenant_id` chặn, xem `modules/config/service.py`.
Khoá mang tenant trong khoá nên publish của tenant khác không chờ.

Việc **bất đồng bộ thật** vẫn còn và vẫn không hứa qua HTTP: pod agent nạp cấu hình
mới cho phiên tiếp theo (≤20s, bậc 3 của HT01). Nó suy từ nhịp tim qua
`GET /api/v1/config/status`, không qua status code của lần publish.

### 8.5 Network `odyssey-network` — external, tạo bằng tay

Cả hai repo của portal (`odyssey-portal-backend`, `odyssey-portal-frontend`) nằm
trên **một** network tên cố định, khai `external: true` ở cả hai file compose:

```sh
docker network create odyssey-network   # MỘT LẦN trên mỗi máy, trước mọi `up`
```

**Compose không tạo nó, và pipeline CI cũng không.** Chủ ý: nếu mỗi bên được phép
tự tạo thì ta có hai network cùng ý nghĩa, frontend nối vào cái không có backend,
và mọi lời gọi `/api/` thành 502 — một lỗi không nói ra nguyên nhân. Thiếu network
thì `up` gãy ngay với `network odyssey-network not found`, một câu đọc là hiểu.

Hệ quả cần biết:

* **Cả ba file compose** dùng nó, kể cả `docker-compose.local.yml` ở máy dev. Chưa
  tạo network thì `make dev` gãy ngay ở lệnh đầu với `network odyssey-network not
  found`.
* **Testcontainers (`pytest`) không bị ảnh hưởng** — nó tự dựng network riêng cho
  từng lần chạy test, nên test vẫn xanh trên máy chưa tạo network.
* Network dùng chung nghĩa là **DNS dùng chung**, và các service hạ tầng mang tên
  trần (`postgres`, `redis`, `qdrant`, `minio`). Nếu sau này có project khác cùng
  vào `odyssey-network` với một service trùng tên thì tên đó phân giải sang container
  của họ — và cách hỏng đó **không báo lỗi**, nó chỉ nối vào sai kho. Hai service có
  tên riêng là `odyssey-portal-backend` và `odyssey-portal-frontend`, đặt bằng
  `container_name` — tên đầu là thứ nginx của repo frontend trỏ tới, đổi nó là đổi
  cả `ODYSSEY_PORTAL_API_UPSTREAM`.

### 8.6 Hai file compose, và đừng lẫn chúng

| File | Dùng ở | Có gì |
|---|---|---|
| `docker-compose.local.yml` | **máy dev** | đủ hạ tầng bằng container: postgres, redis, qdrant, minio + hai vai app (build tại chỗ). Chạy offline, không cần AWS credential. `make dev` / `make up` dùng file này. Không volume nào — `make reset` phải xoá được sạch. |
| `docker-compose.dev.yml` | **deploy** (dev-server và prod) | chỉ `redis`, `qdrant` và hai vai app. **Không** postgres, **không** minio. Image kéo từ ECR, endpoint vào qua hai file env, `redis` và `qdrant` có volume. |

Cả hai đều nối vào `odyssey-network` external (§8.5).

Không có service `postgres` và `minio` trong file deploy là **có chủ đích** (chốt
2026-08-04): ở đó là Aurora PostgreSQL (§6) và Amazon S3 (§7). Dựng lại hai thứ
đó bằng container bên cạnh dịch vụ thật thì service vẫn xanh, request vẫn 200 —
chỉ là đang đọc **sai database**. Đó là lý do `up` file `local` trên máy deploy là
một lỗi khó thấy, chứ không phải một lựa chọn thừa.

`redis` và `qdrant` **vẫn** là container ở deploy: Redis chưa chốt có chuyển
ElastiCache hay không (§6 lề), còn Qdrant thì AWS không có bản managed nào. Muốn
chuyển Redis sang ElastiCache thì xoá service `redis` khỏi `docker-compose.dev.yml`
và trỏ `REDIS_URL` ra endpoint mới — không cần sửa gì khác.

**Tên image chỉ có TAG là biến.** Cả hai file compose viết cứng đường dẫn ECR và
đọc `${IMAGE_TAG:-dev-latest}` — cùng quy ước với các repo khác của NobleX (vd
`nbx-hub-frontend`). Nên một lần deploy là `IMAGE_TAG=<sha> docker compose …`,
không có biến nào chứa cả tên image.

### 8.7 Mật khẩu Redis

Redis chạy `--requirepass`. Cả service `redis` và service `backend` đọc **cùng một
file** `deploy/odyssey-portal-backend.env`, nên mật khẩu chỉ có một chỗ để đổi —
nhưng nó xuất hiện dưới **hai biến phải khớp nhau**:

| Biến | Ai đọc | Dùng làm gì |
|---|---|---|
| `REDIS_PASSWORD` | container `redis` | `redis-server --requirepass "$REDIS_PASSWORD"` |
| `REDIS_URL` | backend | `redis://:<mật-khẩu>@redis:6379/0` |

Dạng DSN là `redis://:<mật-khẩu>@host:port/db` — **user rỗng**, dấu `:` đứng trước
mật khẩu. Ký tự đặc biệt (`@ : / ?`) phải percent-encode, nếu không DSN bị parse sai
host và lỗi hiện ra dưới dạng "không nối được", không phải "sai mật khẩu".

`command` của service `redis` mở biến bằng shell trong container (`$$` để compose
không nội suy — compose **không** đọc được biến từ `env_file` khi nội suy `command`),
và có `:?` phía trước nên **container chết ngay nếu `REDIS_PASSWORD` rỗng hoặc
thiếu**. Chủ ý: `--requirepass ""` khởi động im lặng thành một Redis không mật khẩu,
và trên network dùng chung thì phiên đăng nhập của mọi người đọc được bởi bất cứ
container nào tới được network đó.

Lệch giữa hai biến → `WRONGPASS`. Thiếu mật khẩu trong `REDIS_URL` → `NOAUTH
Authentication required`.

⚠️ Hệ quả của việc dùng chung file env: container `redis` thấy cả `DATABASE_URL` và
`S3_*` trong môi trường của nó, dù không cần. Nếu sau này muốn thu hẹp lại thì tách
`REDIS_PASSWORD` ra một file env riêng cho service `redis`.

Ở máy dev (`docker-compose.local.yml`) mật khẩu là `devredis`, viết cứng trong
compose và trong `.env.example`. **Ai đã có `.env` từ trước phải sửa `REDIS_URL`
thêm `:devredis@`**, nếu không `make api` chết với `NOAUTH`. Testcontainers không
bị ảnh hưởng — nó dựng Redis riêng, không mật khẩu.
