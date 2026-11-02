# Config shape v3 — agent tự render prompt

> **Ngày:** 2026-08-05 · **Trạng thái:** design, chờ plan
> **Phạm vi:** ba repo — `odyssey-portal-backend`, `odyssey-agent`, `odyssey-portal-frontend`
> **Trả lời câu treo ở:** [`docs/contracts/agent-postgres-read-contract.REVIEW.md`](../../contracts/agent-postgres-read-contract.REVIEW.md) dòng 46–48

---

## 1. Vấn đề

Ở `AGENT_CONFIG_SOURCE=db`, agent đọc cấu hình tenant qua view
`agent_api.agent_published_config`, hôm nay lộ `SELECT v.payload AS config` — tức **payload nội bộ
của form Portal**, khoá tiếng Việt. Agent (`agent/agent_config.py::parse_config`) đọc khoá tiếng
Anh theo `odyssey-agent/docs/handoff/spec.md §4`. Hai hình dạng không giao nhau ngoài `tools.enabled`.

Đo trên hệ đang chạy (publish thật cho tenant `anphu`, rồi cho `parse_config` ăn đúng bytes đó):
**9/9 trường cấu hình bị mất**, không exception nào.

| Tenant đặt | Agent nhận |
|---|---|
| `ten_agent` = "Mai" | `identity.agent_name` = `"Trợ lý"` |
| `ten_thuong_hieu` = "An Phú Land" | `identity.brand` = `""` |
| `loi_chao`, `lam_gi`, `khong_lam_gi`, `cau_tu_choi` | `""` cả bốn |
| `phong_ban` = "Phòng kinh doanh" | `handoff_department` = `"CSKH"` |
| `giong_dieu`, `do_dai` | không có trường nào để nhận |

Prompt thật mà LLM nhận có khe trống lủng lẳng: `Bạn là Trợ lý — chuyên viên .` và mục Phạm vi
rỗng hai đầu (`Trợ lý LÀM:` · `Trợ lý KHÔNG làm:`). Một agent không có biên từ chối.

**Vì sao im lặng:** `parse_config` toàn phần theo chủ ý — mọi trường qua `_str(d, key, default)`,
không nhánh nào `raise`. Lý lẽ ở `spec.md §4.3` là giữ `escalate` sống kể cả khi config hỏng. Đúng
cho tầng tool, nhưng nó kéo theo fail-silent ở tầng danh tính và phạm vi, nơi đúng ra phải fail-loud.

**Vì sao không cổng nào bắt được:** Portal có seam test đi trọn đường publish → view, nhưng nó tự
`json.loads` rồi đọc theo tên tiếng Việt của chính mình (`tests/modules/agent_seam/
test_bam_ap_dung_agent_doc_duoc.py:80`) — không import một dòng nào của repo agent. Phía agent,
fixture tự gõ đúng hình dạng agent tự đặt. Hai bộ test tự-nhất-quán, xanh vĩnh viễn.

## 2. Quyết định

| # | Quyết định | Lý do |
|---|---|---|
| Đ1 | **Agent tự render** prompt từ config có cấu trúc + skeleton trên disk (phương án 2) | Agent-team sửa câu chữ prompt không cần deploy Portal |
| Đ2 | **Mở rộng §4**, không hạ cấp: thêm `scope.handoff_departments` (list) và `voice` | `pham_vi.phong_ban` (list, có `khi_nao`) giàu hơn `handoff_department` (1 chuỗi); §4 thiếu hẳn chỗ cho giọng điệu/độ dài |
| Đ3 | **Tách ô xưng hô thành hai** trường có nhãn hỏi thẳng | Một ô `"em ↔ anh/chị"` bắt người dùng học cú pháp của ta |
| Đ4 | **Skeleton là code**, định danh bằng `sha256`, agent báo trong nhịp tim | Skeleton là tài sản platform, đổi theo deploy và áp cho mọi tenant cùng lúc — giống một lần deploy code, không ai quay lui nó bằng config của một tenant |
| Đ5 | **Agent từ chối** `schema_version ≠ 3` (fail-loud) | Không có nhánh đọc thứ hai nào tồn tại. `control.config_live` trên Aurora dev đang rỗng (`docs/support_agent_system_connect_db/tra-loi-portal-control-plane.md` §4) nên giá gần bằng không |
| Đ6 | **Lớp dịch là hàm thuần lúc publish**, kết quả **đóng băng vào DB** | Suy lại lúc đọc thì sửa hàm dịch sẽ làm một hàng `config_versions` **bất biến** đổi nghĩa |

Đ6 giữ `ConfigPayload` làm hợp đồng form (tên tiếng Việt, lý lẽ ở `modules/config/contracts.py:10-15`)
và đặt phép dịch cạnh `bundle.render()` — cùng khuôn: hàm thuần, không I/O, test được không cần
Postgres/MinIO/worker.

## 3. Hình dạng `config` v3

```json
{
  "schema_version": 3,
  "identity": {
    "agent_name": "Mai",
    "brand": "An Phú Land",
    "honorific_self": "em",
    "honorific_customer": "anh/chị",
    "greeting": "Dạ em Mai bên An Phú Land ạ."
  },
  "scope": {
    "does": "Tư vấn dự án, quỹ căn và đặt lịch tham quan.",
    "does_not": "Hậu mãi và giá riêng — chuyển người thật.",
    "refusal": "Việc này em xin phép chuyển bộ phận phụ trách ạ.",
    "handoff_departments": [
      { "name": "Phòng kinh doanh", "when": "Khách hỏi giá riêng" }
    ]
  },
  "voice": { "tone": "lich_su", "length": "chi_tiet" },
  "tools": { "enabled": ["discover_projects", "…"], "feng_shui": false, "media_channel": "noblex_app" },
  "data_source": "pg_kb"
}
```

Ánh xạ từ `ConfigPayload`:

| §4 v3 | Nguồn | Ghi chú |
|---|---|---|
| `identity.agent_name` · `brand` · `greeting` | `danh_tinh.ten_agent` · `ten_thuong_hieu` · `loi_chao` | thẳng |
| `identity.honorific_self` | `danh_tinh.tu_xung` | **trường mới** (Đ3) |
| `identity.honorific_customer` | `danh_tinh.goi_khach` | **trường mới** (Đ3) |
| `scope.does` · `does_not` | `pham_vi.lam_gi` · `khong_lam_gi` | thẳng |
| `scope.refusal` | **gọi lại `bundle.cau_tu_choi(cfg)`** | một nguồn — đường bundle và đường db nói cùng một câu từ chối, kể cả khi ô để rỗng |
| `scope.handoff_departments` | `pham_vi.phong_ban` trọn list | giữ cả `khi_nao` → `when` |
| `voice.tone` · `length` | `giong.giong_dieu` · `do_dai` | gửi **khoá preset**, không gửi câu chữ |
| `tools.enabled` | `tools.enabled` **trừ 4 tool lõi** | `spec.md §4.3`: agent luôn tự union lõi |
| `tools.feng_shui` · `media_channel` | hằng `false` · `"noblex_app"` | form chưa có ô — xem §8 |
| `data_source` | hằng `"pg_kb"` | `spec.md §4.4` |

**`voice` gửi khoá, không gửi câu chữ.** Dưới Đ1, câu chữ prompt thuộc agent. Portal giữ
`GIONG_DIEU_TEXT`/`DO_DAI_TEXT` chỉ cho đường bundle. Tập giá trị là danh sách đóng ba×ba, và cổng
§6.2–6.3 ghim nó để hai bên không lệch enum.

## 4. Portal — thay đổi

| File | Việc |
|---|---|
| `src/portal/modules/config/contracts.py` | `SCHEMA_VERSION_HIEN_TAI = 3`. `DanhTinh`: bỏ `xung_ho`, thêm `tu_xung` (mặc định `"em"`, `max_length=20`) và `goi_khach` (mặc định `"anh/chị"`, `max_length=20`) |
| **`src/portal/modules/config/config_agent.py`** (mới) | `sang_config_agent(cfg: ConfigPayload) -> dict` — **hàm thuần, không I/O**. `SCHEMA_VERSION_AGENT = 3` |
| `src/portal/modules/config/bundle.py` | `_soul()` mục "Xưng hô" ghép từ hai trường mới |
| `src/portal/modules/config/repo.py` | `them_version(...)` nhận thêm `config_agent: dict` |
| `src/portal/modules/config/service.py` | `publish()` tính `config_agent` rồi lưu **trong cùng transaction** với version + con trỏ. `dung_ban_xem_truoc()` trả hai trường xưng hô |
| `src/portal/modules/config/router.py` | `XemTruocOut.xungHo` → `tuXung` + `goiKhach`. `TrangThaiOut` thêm `schemaVersionLive: int \| None`. `publish` trả **409 `DRAFT_SCHEMA_CU`** khi bản nháp không validate được theo v3 |
| **`migrations/versions/0908_config_agent_va_skeleton_sha.py`** (mới) | xem §4.1 |
| `scripts/gen_contracts.py` | sinh `contracts/agent-config.json` (mẫu vàng) |

**Thứ tự bốn bước của `publish()` KHÔNG đổi** — nó là cổng 2 của M3: render → upload bundle →
`[transaction: them_version + dat_con_tro]` → ghi object `LIVE` phái sinh. `config_agent` được tính
**trước** transaction (hàm thuần, không thể hỏng vì mạng) và ghi **trong** transaction cùng version.

### 4.1. Migration `0908`

```sql
ALTER TABLE control.config_versions ADD COLUMN config_agent jsonb;   -- NULL được
ALTER TABLE control.agent_heartbeats ADD COLUMN skeleton_sha text;

CREATE OR REPLACE VIEW agent_api.agent_published_config AS
    SELECT v.tenant_id,
           v.version,
           v.config_agent                      AS config,           -- ĐỔI: không còn v.payload
           (v.payload->>'schema_version')::int AS schema_version    -- MỚI, phải ở CUỐI
      FROM control.config_versions v
      JOIN control.config_live    l ON l.tenant_id = v.tenant_id AND l.version = v.version
     WHERE v.tenant_id = portal.current_tenant();
```

⚠️ **`schema_version` PHẢI là cột cuối, và `downgrade()` KHÔNG dùng được `CREATE OR REPLACE`.** Đo trên Postgres thật ngày 2026-08-05:

- Chèn cột mới vào GIỮA làm Postgres coi đó là **đổi tên** cột thứ 3 (`config` → `schema_version`) và từ chối: `cannot change name of view column "config" to "schema_version"`. `CREATE OR REPLACE VIEW` chỉ cho **thêm cột ở cuối**.
- `downgrade()` rút 4 cột về 3 ⇒ `cannot drop columns from view`. Phải `DROP VIEW` + `CREATE VIEW` + `GRANT SELECT ... TO agent_all` tường minh, vì `DROP` xoá luôn ACL.

Không consumer nào bị ảnh hưởng bởi thứ tự cột: cả phía agent lẫn test đều `SELECT` theo tên.

`config_agent` **nullable** có chủ ý: các hàng `config_versions` là bất biến
(`REVOKE UPDATE, DELETE`, migration 0200), nên không backfill. Hàng v2 cũ giữ `NULL`, và view lộ
`schema_version` để agent báo được lỗi chính xác thay vì `no published config` chung chung.

`schema_version` đọc từ `payload` chứ không thêm cột: nó đã nằm trong payload từ hàng đầu tiên
(`contracts.py:113-115`), thêm cột là bản sao thứ hai của một sự thật.

## 5. Agent — thay đổi

| File | Việc |
|---|---|
| `src/noble_agent/agent/agent_config.py` | thêm dataclass `Department(name, when)` và `Voice(tone, length)`; `Scope.handoff_department: str` → `handoff_departments: tuple[Department, ...]`. `parse_config` **fail-loud**: `raise ConfigShapeError` khi `schema_version != 3`, hoặc thiếu `identity`/`scope`. `OPTIONAL_TOOLS` **không đổi** — sau §8.1 thì sổ hai bên đã bằng nhau |
| `src/noble_agent/agent/persona_compose.py` | `ctx` thêm `"voice": asdict(config.voice)` — hiện nó chỉ truyền `identity` + `scope` |
| `src/noble_agent/persona/SOUL.md` · `RULES.md` | `persona_compose` render bằng **jinja2** và skeleton đã dùng `{% if identity.greeting %}`. Nên: giọng/độ dài dùng `{% if voice.tone == 'lich_su' %}…{% endif %}`, list phòng ban dùng `{% for d in scope.handoff_departments %}`. **Không** thêm marker region mới, **không** pre-format chuỗi ở `base.py` — engine vòng lặp đã có sẵn |
| `src/noble_agent/storage/agent_config_store.py` | `SELECT version, schema_version, config FROM agent_api.agent_published_config` — lỗi chính xác khi lệch schema, và **không** ghi last-good cho một hàng lệch schema |
| `src/noble_agent/tenant/pg_heartbeat.py` | tính `skeleton_sha` một lần lúc khởi động (sha256 theo đường dẫn + nội dung đã sắp — đúng công thức `bundle.tinh_sha`), upsert kèm nhịp tim |
| `.gitlab-ci.yml` | thêm một job test **hẹp**, xem §6.3 |

## 6. Ba cổng

### 6.1. Portal — hàm thuần không được rơi trường
`tests/modules/config/test_config_agent.py`. Viết bằng **phản chiếu trên model**: duyệt mọi trường
của `ConfigPayload`, khẳng định mỗi trường tới được đầu ra của `sang_config_agent`. Thêm một ô vào
form mà quên map ⇒ CI đỏ.

### 6.2. Portal — mẫu vàng khớp nguồn
`tests/api/test_contracts.py` mở rộng: `contracts/agent-config.json` phải khớp
`sang_config_agent(mẫu)`. Quên `make contracts` ⇒ đỏ. **Cùng cơ chế `contracts/actions.json`**
đang dùng cho seam Portal↔Frontend — không phát minh cơ chế mới.

### 6.3. Agent — tiêu thụ mẫu vàng
`tests/unit/unified/test_config_contract.py`: nạp `contracts/agent-config.json` (copy từ Portal, cùng
quy trình `contracts/README.md`), chạy `parse_config`, khẳng định **không trường nào rơi về mặc định**
và `enabled_tools` đúng như mong đợi. **Đây là cổng duy nhất chạm cả hai đầu.**

⚠️ CI repo agent hiện là `stages: [build, deploy]` — không có test, có chủ đích, vì ~9–11 unit test
đỏ sẵn ở baseline và *"cổng nào luôn đỏ thì sẽ bị bỏ qua bằng tay"*. Nên §6.3 chỉ có hiệu lực khi
thêm một job chạy **đúng file này**, không kéo theo baseline đỏ.

## 7. Frontend — thay đổi

| File:dòng | Việc |
|---|---|
| `src/features/agent/api.ts:44` | type payload: `xung_ho` → `tu_xung` + `goi_khach` |
| `src/features/agent/api.ts:75` | type xem trước: `xungHo` → `tuXung` + `goiKhach` |
| `src/features/agent/components/AgentStudio.tsx:218-220` | một `<Input>` → hai, nhãn **"Agent tự xưng là gì?"** / **"Agent gọi khách là gì?"** |
| `src/lib/msw/handlers.ts:47,788` | dữ liệu giả theo hình dạng mới |

Dưới hai ô, hiện câu mẫu sinh trực tiếp từ giá trị đang gõ — *Dạ **em** xin phép tư vấn cho
**anh/chị** ạ.* — để tenant thấy hệ quả thay vì phải suy. Câu mẫu là hằng số FE, **không** vào payload.

FE đọc `BanNhapOut.schemaVersion` (đã có sẵn): nhỏ hơn 3 ⇒ hiện cảnh báo *"bản nháp thuộc schema cũ
— kiểm hai ô xưng hô rồi Lưu lại"*.

## 8. Thứ tự triển khai

| # | Việc | Chặn bởi |
|---|---|---|
| 0 | **Hợp nhất sổ kỹ năng** — đã có phép giải, xem §8.1 | — |
| 1 | Portal: `DanhTinh` hai ô + `sang_config_agent` + cổng 6.1 + `SCHEMA_VERSION=3` | 0 |
| 1b | FE: hai ô + câu mẫu + MSW (song song với 1) | tên trường ở 1 |
| 2 | Portal: migration `0908` + repo/service + 409 bản nháp cũ + seam test | 1 |
| 3 | Portal: mẫu vàng + `gen_contracts` + cổng 6.2 | 1 |
| 4 | Agent: `parse_config` fail-loud + trường mới + marker giọng + `agent_config_store` | 0 |
| 5 | Agent: cổng 6.3 + job CI hẹp | 3, 4 |
| 6 | `skeleton_sha` vào nhịp tim + Portal hiện nó | 4 |

### 8.1. Hợp nhất sổ kỹ năng — phép giải

Đối chiếu `agent/tools/schemas.py` (nguồn sự thật của agent: **15** tool có schema) với
`modules/config/tools.py::MUOI_HAI_KY_NANG` của Portal:

| Lệch | Dữ kiện | Xử lý |
|---|---|---|
| `get_project_financial` | Portal cho bật, **agent KHÔNG có schema nào** cho nó | **Portal bỏ khỏi sổ.** Bật nó hôm nay là dạy LLM gọi một tool không tồn tại |
| `get_document` | Agent **có schema thật** + `agent/tools/get_document.py`; Portal không cho bật | **Portal thêm vào sổ** |
| `crm_lookup` · `verify_identity` · `support_ticket` | có schema ở agent, cố ý không chào | giữ nguyên — 3 tool dự trữ |

Sổ sau hợp nhất vẫn **12 tool**: 4 lõi (`update_customer` · `kb_search` · `find_project` ·
`escalate`) + 8 tùy chọn (`discover_projects` · `get_project_overview` · `get_document` ·
`search_units` · `check_inventory` · `recommend_units` · `booking` · `send_media`) — đúng bằng
`CORE_TOOLS + OPTIONAL_TOOLS` hiện có của agent. Nên **agent không phải đổi danh sách**; chỉ Portal
đổi: bỏ một, thêm một.

> **Phát hiện kèm, ngoài phạm vi thiết kế này:** `get_project_financial` có trong sổ Portal nghĩa là
> `bundle._rules()` đang sinh dòng danh mục kỹ năng cho một tool không tồn tại — tức lỗi này có **cả
> trên đường bundle**, không chỉ đường db, và có từ trước thay đổi này. Cần một issue riêng để kiểm
> `data/tenants/noble/manifest.toml` xem tenant thật nào đang bật nó.

**Nghiệm thu:** chạy lại kịch bản đã dùng để phát hiện lỗi (publish thật → đọc view → `parse_config`
thật). Chín dòng đối chiếu phải chuyển từ ❌ sang ✅; `get_project_financial` không còn trong "bị rơi";
`tu_xung`/`goi_khach` tới được `identity.honorific_*`.

## 9. Ngoài phạm vi, có chủ đích

- **Không bỏ `bundle.render()`.** Đường MinIO vẫn là mặc định (`AGENT_CONFIG_SOURCE=legacy`) và khai
  tử nó có handoff riêng (`odyssey-agent/docs/handoff/2026-08-04-retire-minio-handoff.md`).
- **Không thêm ô `feng_shui`/`media_channel` vào form.** Portal chưa từng có hai ô này nên phát mặc
  định không phải hồi quy. Thêm ô là việc riêng của M5.
- **Không backfill hàng `config_versions` v2.** Bất biến. Đ5 xử lý bằng fail-loud.
- **Không đánh version cho skeleton.** Đ4 chọn ghi vết bằng `skeleton_sha`, không snapshot.

## 10. Hệ quả phải nói rõ

`service.py::tro_lai()` hiện viết *"quay lui trỏ vào ĐÚNG NHỮNG BYTE đã phục vụ"*. Với Đ1 + Đ4 câu
đó chỉ còn đúng cho **đường bundle**. Ở db-mode, rollback trả đúng **config**; prompt thực tế phụ
thuộc skeleton của bản agent đang deploy. Docstring đó phải được sửa trong bước 2, không để lại một
lời hứa mà kiến trúc mới không giữ — đúng lỗi mà chính tài liệu này ghi nhận ở §1 (`contracts.py:10-15`
vẫn khẳng định "đây KHÔNG phải hợp đồng với agent" sau khi `0904` phá tiền đề đó).

`skeleton_sha` là thứ trả lời được *"prompt nào đã chạy cho khách hôm 12/8"*: cặp
`(config version, skeleton_sha)`. Nó không dựng lại được byte cũ nếu skeleton đó không còn trong image
nào — đó là cái giá đã chấp nhận ở Đ4.
