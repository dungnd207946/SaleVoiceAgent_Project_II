# `tenant_data.agent_config` — cấu trúc bảng cấu hình agent

> **Đối tượng:** team agent (Odyssey).
> **Ngày:** 2026-08-06 · **Migration:** `0910_agent_config`.

**Từ nay đọc bảng này để lấy cấu hình agent của một workspace, thay cho
`agent_api.agent_published_config`.** Mỗi ô người dùng điền trên Portal là một cột — không còn
phải bung `jsonb` lồng nhiều tầng.


Hai điều phải biết khi query:

- **Bảng không tự lọc tenant** — luôn viết `WHERE tenant_id = …`. Khác `agent_api.*`, ở đây
  không có vị từ `portal.current_tenant()` và không có RLS.
- **Một tenant đúng một hàng.** Không có hàng = workspace đó chưa áp dụng cấu hình lần nào.

---

## DDL

```sql
CREATE TABLE tenant_data.agent_config (
    id               bigserial PRIMARY KEY,
    tenant_id        text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,

    name             text NOT NULL CHECK (name <> ''),
    brand_name       text NOT NULL CHECK (brand_name <> ''),
    self_pronoun     text NOT NULL DEFAULT '',
    customer_pronoun text NOT NULL DEFAULT '',
    greeting         text NOT NULL DEFAULT '',

    scope_does       text NOT NULL DEFAULT '',
    scope_does_not   text NOT NULL DEFAULT '',
    refusal_line     text NOT NULL DEFAULT '',
    departments      jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(departments) = 'array'),

    tone             text NOT NULL CHECK (tone IN ('lich_su', 'than_thien', 'ngan_gon')),
    reply_length     text NOT NULL CHECK (reply_length IN ('ngan', 'trung_binh', 'chi_tiet')),

    skills           jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(skills) = 'array'),

    version          integer NOT NULL CHECK (version > 0),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT agent_config_tenant_key UNIQUE (tenant_id)
);
CREATE INDEX agent_config_skills_idx ON tenant_data.agent_config USING gin (skills);
```

## Các cột

| Cột | Kiểu | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `id` | bigint | Khoá kỹ thuật, bền theo tenant. | `1` |
| `tenant_id` | text | Workspace sở hữu cấu hình. **Luôn có trong WHERE.** | `noble` |
| `name` | text | Tên agent tự xưng với khách. Không rỗng. | `Mai` |
| `brand_name` | text | Thương hiệu agent đại diện. Không rỗng. | `An Phú Land` |
| `self_pronoun` | text | Agent **tự gọi mình** là gì. | `em` |
| `customer_pronoun` | text | Agent **gọi khách** là gì. | `anh/chị` |
| `greeting` | text | Câu chào mở đầu. Rỗng = không cấu hình. | `Dạ em Mai bên An Phú Land ạ.` |
| `scope_does` | text | Việc agent làm. | `Tư vấn dự án và đặt lịch tham quan.` |
| `scope_does_not` | text | Việc agent KHÔNG làm. | `Hậu mãi và giá riêng — chuyển người thật.` |
| `refusal_line` | text | Câu từ chối khi khách hỏi ngoài phạm vi. Rỗng = workspace không đặt câu riêng. | `Việc này em xin phép chuyển…` |
| `departments` | jsonb | Đầu mối chuyển tiếp, mảng 1–8 object. | xem dưới |
| `tone` | text | Giọng điệu, 1 trong 3 mã đóng. | `than_thien` |
| `reply_length` | text | Độ dài trả lời, 1 trong 3 mã đóng. | `trung_binh` |
| `skills` | jsonb | Mảng mã kỹ năng **đang bật**. | xem dưới |
| `version` | integer | Số version cấu hình, tăng dần trong phạm vi một tenant. Đổi ⇒ cấu hình đã đổi. | `7` |
| `created_at` | timestamptz | Lần đầu workspace áp dụng cấu hình. | |
| `updated_at` | timestamptz | Lần áp dụng gần nhất. | |

### `tone` · `reply_length` — danh sách đóng

| `tone` | Nghĩa |
|---|---|
| `lich_su` | Lịch sự, giữ khoảng cách |
| `than_thien` | Thân thiện, gần gũi (mặc định) |
| `ngan_gon` | Ngắn gọn, đi thẳng việc |

| `reply_length` | Nghĩa |
|---|---|
| `ngan` | 1–2 câu |
| `trung_binh` | 3–4 câu (mặc định) |
| `chi_tiet` | Trả lời đầy đủ |

### `departments` — đầu mối chuyển tiếp

Mảng object, khoá tiếng Việt:

```json
[
  { "ten": "CSKH",       "khi_nao": "khách hỏi hợp đồng đã ký" },
  { "ten": "Kinh doanh", "khi_nao": "khách hỏi giá riêng" }
]
```

- `ten` — tên bộ phận, không rỗng, ≤ 60 ký tự.
- `khi_nao` — khi nào chuyển cho bộ phận này, có thể rỗng, ≤ 200 ký tự.
- Luôn có ít nhất 1 phần tử, tối đa 8. Thứ tự là thứ tự người dùng nhập.

```sql
SELECT d->>'ten' AS bo_phan, d->>'khi_nao' AS khi_nao
  FROM tenant_data.agent_config, jsonb_array_elements(departments) AS d
 WHERE tenant_id = $1;
```

### `skills` — kỹ năng đang bật

Mảng mã đang bật; kỹ năng tắt thì **vắng mặt** (không phải `false`). Luôn có ít nhất 1 mã.
Mã là tên tool đúng như agent đăng ký.

```json
["find_project", "discover_projects", "get_project_overview", "kb_search", "escalate"]
```

| Mã | Việc |
|---|---|
| `find_project` | Tra mã dự án từ tên khách nói, chịu được nói tắt/sai chính tả |
| `discover_projects` | Liệt kê dự án đang bán khi khách chưa nhắm cụ thể |
| `get_project_overview` | Vị trí, tiến độ, tiện ích, pháp lý của một dự án |
| `get_project_financial` | Chính sách giá, chiết khấu, tiến độ thanh toán |
| `search_units` | Lọc quỹ căn theo diện tích, phòng ngủ, hướng, khoảng giá |
| `check_inventory` | Xác nhận tình trạng một căn cụ thể |
| `recommend_units` | Xếp hạng căn theo nhu cầu khách đã nêu |
| `kb_search` | Tìm trong tài liệu workspace đã nạp |
| `booking` | Chốt lịch xem nhà (giao thức ba bước) |
| `update_customer` | Lưu nhu cầu và thông tin liên hệ khách |
| `send_media` | Gửi ảnh/video dự án |
| `escalate` | Bàn giao cho nhân viên thật |

Thứ tự trong mảng là thứ tự người dùng bật — **không mang ý nghĩa ưu tiên**.

Phụ thuộc (Portal đã validate trước khi ghi, nên hàng trong bảng luôn thoả): `booking`,
`check_inventory`, `get_project_overview`, `get_project_financial`, `send_media` cần
`find_project`; `recommend_units` cần `search_units`.

```sql
-- Workspace này có bật đặt lịch không?
SELECT skills @> '["booking"]'::jsonb AS co_booking
  FROM tenant_data.agent_config WHERE tenant_id = $1;

-- Những workspace đang bật gửi media (đi qua index GIN)
SELECT tenant_id FROM tenant_data.agent_config WHERE skills @> '["send_media"]'::jsonb;

-- Bung mảng thành từng dòng
SELECT jsonb_array_elements_text(skills) AS ky_nang
  FROM tenant_data.agent_config WHERE tenant_id = $1;
```

## Đọc trọn cấu hình một workspace

```sql
SELECT name, brand_name, self_pronoun, customer_pronoun, greeting,
       scope_does, scope_does_not, refusal_line,
       departments, tone, reply_length, skills, version, updated_at
  FROM tenant_data.agent_config
 WHERE tenant_id = $1;
```
