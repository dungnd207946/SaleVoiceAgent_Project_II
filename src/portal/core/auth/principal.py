"""Principal — "ai đang gọi, ở workspace nào, được làm gì".

Đây là thứ DUY NHẤT endpoint của module khác nhận. Chúng không thấy cookie, không
thấy session id, không thấy token. Nhờ vậy đổi cách xác thực (thêm OIDC, đổi
cookie sang thứ khác) không sửa endpoint nào.

`tenant_id` ở đây đã ĐƯỢC XÁC THỰC: nó đến từ một hàng control.memberships còn
hiệu lực, không từ request. Đưa thẳng vào tenant_conn() là đúng — và đó là cách
DUY NHẤT đúng, xem core/db/session.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    tenant_id: str
    """Đã xác thực qua membership. An toàn để truyền vào tenant_conn()."""
    role: str
    """TÊN vai trò trong workspace này ('Quản trị', 'CSKH', ...).

    Giá trị rơi `'Chủ tổ chức'` đã bỏ 2026-08-15 cùng nhánh owner: `role_name` chỉ
    còn `None` khi không có membership, mà trường hợp đó đã bị `require()` chặn
    bằng 403 trước khi dựng được `Principal`.

    ⚠ CHỈ để hiển thị trong thông điệp lỗi. KHÔNG dùng để quyết định gì — so sánh
    `p.role == 'Quản trị'` là một phép kiểm quyền đi vòng qua require(), và nó sai
    âm thầm ngay khi ai đó đổi tên vai trò. Dùng `ACTIONS.X in p.actions`.
    """
    actions: frozenset[str]
    """Tập action hiệu lực, tra từ ma trận role × action mỗi request."""
