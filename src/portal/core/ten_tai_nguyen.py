"""BỐN VAI CỦA `control.tenants.id` — mọi tên tài nguyên suy từ nó, ở một chỗ.

Spec tổng §5.4 nói `tenants.id` là **một khoá dùng cho bốn việc cùng lúc**:

| Vai | Chỗ dùng |
|---|---|
| Khoá cách ly hàng | policy RLS trên mọi bảng `tenant_data` |
| Danh tính runtime | biến `TENANT_ID` của container agent, và role `agent_<id>` |
| Tiền tố kho tệp | `tenants/<id>/` |
| Phạm vi knowledge | tên collection Qdrant |

VÌ SAO GOM VÀO MỘT FILE Ở `core/`, KHÔNG ĐỂ MỖI MODULE TỰ SUY:
  · Đây là những cái tên mà **cách ly dựa vào**. Qdrant không có RLS, kho tệp
    không có RLS — với hai kho đó, tên CHÍNH LÀ cơ chế cách ly. Một module tự
    viết bản thứ hai của quy tắc đặt tên là một cơ hội để hai bản lệch, và lệch
    ở đây nghĩa là một tenant đọc kho của tenant khác.
  · Cổng ranh giới module (Luật 3) cấm module này import ruột module kia. Trước
    bản này `ten_collection` sống trong ruột module config, và M6 phải
    import ruột M3 để dùng nó — CI đỏ, đúng như thiết kế. Chỗ đúng của một quy
    tắc mà hai module cùng cần là `core/`.
  · Đổi mô hình "1 khách = 1 workspace" sang "1 khách = N workspace" là đổi CẢ
    BỐN cùng lúc (spec §5.4 gọi đây là chỗ đắt nhất toàn thiết kế). Gom một chỗ
    làm phạm vi của thay đổi đó nhìn thấy được.

LUẬT: mọi hàm ở đây nhận ĐÚNG `tenant_id` và không tham số nào khác. Thêm tham
số là mở một đường để tên đến từ chỗ khác — và lúc đó cách ly do cấu trúc không
còn là do cấu trúc. Có cổng test canh chữ ký này.
"""


def ten_collection(tenant_id: str) -> str:
    """Kho tri thức Qdrant của một tenant (quyết định #13).

    `/runtime-credentials` trả tên này để agent biết đọc kho nào; M6 dùng nó để
    tạo và truy vấn. Hai bên PHẢI ra cùng một chuỗi, nếu không thì portal nạp tài
    liệu vào một kho mà agent không bao giờ đọc — và không có lỗi nào cả.
    """
    return f"kb_{tenant_id}"


def ten_khoa_truy_cap(tenant_id: str) -> str:
    """Access key của pod trên kho tệp. Policy gắn vào nó chỉ mở `tenants/<id>/*`."""
    return f"agent-{tenant_id}"


def ten_role_agent(tenant_id: str) -> str:
    """Role Postgres của pod. `control.create_agent_role()` tạo đúng tên này, và
    `portal.current_tenant()` suy tenant NGƯỢC LẠI từ nó — nên tiền tố `agent_`
    là hợp đồng với migration 0003, không phải quy ước đặt tên."""
    return f"agent_{tenant_id}"


def ten_kho_web(tenant_id: str) -> str:
    """Collection Qdrant chứa dữ liệu web công khai (hồ sơ dự án, thẻ lân cận, bản tin) của
    một tenant — gói `kb/web` ghi, agent đọc qua JWT scope của `/runtime-credentials`."""
    return f"{tenant_id}_public_web"
