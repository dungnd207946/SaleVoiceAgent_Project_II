# mockdb — truy cập từ máy khác

Bản sao cục bộ của DB dev `10.50.13.209`, chạy trong container `odyssey-mockdb` trên máy
haidt. Dùng để thử tay, không phải môi trường chung — dữ liệu có thể biến mất bất cứ lúc nào.

## Kết nối

|           |                                                          |
| --------- | -------------------------------------------------------- |
| Host      | `10.50.12.62` (LAN, DHCP — có thể đổi sau reboot) |
| Port      | `5432`                                                 |
| Database  | `odyssey`                                              |
| Role app  | `odyssey_agent` / `odyssey_agent_pw`                 |
| Superuser | `sp_admin` / `sp_admin_pw`                           |

```
postgresql://odyssey_agent:odyssey_agent_pw@10.50.12.62:5432/odyssey
```

Postgres 16. Chỉ truy cập được trong LAN `10.50.12.0/23`; ngoài mạng thì cần VPN.
Không connect được → kiểm tra IP máy chủ trước (`ip -4 addr show eno1`), rồi `nc -zv 10.50.12.62 5432`.


## Schema `tenant_data` — 8 bảng

| Bảng             | Số hàng |
| ----------------- | --------- |
| `projects`      | 41        |
| `zones`         | 56        |
| `units`         | 603       |
| `media`         | 270       |
| `documents`     | 5         |
| `appointments`  | 138       |
| `contacts`      | 4         |
| `conversations` | 9         |

Mọi bảng có cột `tenant_id text`; `projects`/`zones`/`units`/`media`/`documents` neo theo
`project_code` (**không phải `code`** như migration repo đặt).

Không có schema `control` (tenants/users/memberships) và không có `kb_index_state` — org chỉ
tồn tại như quy ước trong chuỗi `tenant_id`, không join được.

## 4 tenant · 3 org · 2 tên org

Định dạng `<org>_<rand>_<tenant>`: `-` bên trong mỗi phần, `_` giữa các phần → `split('_')` ra
đúng 3 phần. Random thuộc **org**, nên `<org>_<rand>` mới là định danh org.

| `tenant_id`                  | Org          | Nhóm dự án        | Số dự án |
| ------------------------------ | ------------ | -------------------- | ----------- |
| `noble-homes_k3n7_retail`    | Noble Homes  | Vinhomes miền Bắc  | 7           |
| `noble-homes_k3n7_wholesale` | Noble Homes  | Vinhomes Nam + Trung | 6           |
| `an-phu-land_q8w2_retail`    | An Phú Land | Masterise / Lumière | 14          |
| `an-phu-land_z5r1_retail`    | An Phú Land | MIK + Sun + khác    | 14          |
