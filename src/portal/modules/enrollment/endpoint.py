"""Công thức `ENDPOINT_URL` của một tenant — HÀM THUẦN, không I/O, không config.

VÌ SAO KHÔNG ĐẶT VÀO `core/ten_tai_nguyen.py` (chỗ trông có vẻ đúng nhất):

  1. File đó có luật ở dòng 25-27 — "mọi hàm ở đây nhận ĐÚNG `tenant_id` và không
     tham số nào khác". Hàm này cần thêm `base_domain`.

  2. Và đây mới là lý do thật: `ENDPOINT_URL` KHÔNG phải cơ chế cách ly. Lý lẽ của
     `ten_tai_nguyen.py` là với Qdrant và kho tệp — hai kho không có RLS — *tên
     chính là cơ chế cách ly*, nên bốn cái tên đó phải ở một chỗ để không lệch.
     Còn cái này là hostname công khai để gateway định tuyến; đoán đúng nó không
     mở được gì. Nó không thuộc họ ấy.

Có tiền lệ: `modules/workspace/service.py:10` gặp đúng tình huống này với
`slug_tenant()` và ghi lại vì sao nó không vào `core/ten_tai_nguyen.py`.

VÌ SAO NHẬN `base_domain` LÀM THAM SỐ chứ không đọc `get_settings()`: cùng nếp
`bi_mat.dan_xuat(loai, tenant_id, version, master)` — master truyền vào, không tự
đọc. Giữ file thuần thì test được không cần dựng config, và đây là chỗ một lỗi
chính tả biến thành "bàn giao URL sai cho đối tác" mà không có gì đỏ.
"""

from typing import Final

KIND_CHAT: Final = "chat"
"""Chỉ dùng để suy `ENDPOINT_CHAT_URL` — không còn gắn với cột nào trong
`control.deployments` (cột `kind` đã bỏ, một khoá dùng chung cho cả hai)."""

KIND_VOICE: Final = "voice"
"""Chưa có deployment/tính năng nào phát ra `kind` này. Tồn tại vì
`ENDPOINT_VOICE_URL` là một công thức thuần suy từ tenant_id + domain — tính
được kể cả khi chưa có gì dùng tới, giống `ENDPOINT_CHAT_URL` trước khi M10 có
khoá đầu tiên."""


def url_endpoint_agent(tenant_id: str, base_domain: str, kind: str = KIND_CHAT) -> str:
    """`wss://<tenant_id>.<base_domain>/v1/<kind>` — đường client nối vào pod agent.

    `wss://` KHÔNG PHẢI `ws://`: gateway đứng sau TLS termination. Bản trước dùng
    `ws://` và ghi rằng đó là cố ý vì tầng đó chưa có TLS — điều đó không còn
    đúng. Đây là ĐÚNG MỘT CHỖ quyết định scheme; nếu nó đổi lần nữa thì sửa ở
    đây, không rải tiền tố ra các chỗ dùng.

    KHÔNG đổi hoa/thường và KHÔNG url-encode `tenant_id`: CHECK
    `tenants_id_check` là `^[a-z][a-z0-9_-]{1,30}$` (migration 0002, nới cho `-` ở
    0911), nên nó đã thường sẵn và không có ký tự cần encode. Gọi `.lower()` cho
    chắc là che mất trường hợp tenant_id sai định dạng — thà để nó hiện ra.

    ⚠️ KHÔNG PHẢI "nhãn subdomain hợp lệ sẵn" — bản trước của docstring này nói
    vậy và nói SAI: charset của CHECK cho phép `_`, mà `_` KHÔNG hợp chuẩn nhãn
    hostname (RFC 1123 cho `[a-z0-9-]`). Mọi tenant hiện có đều dùng `_`, nên đây
    là một khoảng hở CÓ TỪ ĐẦU, không do 0911 gây ra — 0911 chỉ thêm `-`, ký tự
    duy nhất trong charset này thực sự hợp chuẩn DNS. Resolver và gateway đang
    chấp nhận trên thực tế; nếu chỗ nào đó về sau cưỡng chế RFC 1123 chặt thì đây
    là hàm phải sửa, và bài toán là toàn bộ tenant có `_`, không phải tenant có `-`.

    `base_domain` KHÔNG được có dấu `.` ở đầu hay `/` ở cuối; hàm không tự gọt vì
    gọt im lặng là cách một giá trị cấu hình sai đi qua mà không ai biết.
    """
    return f"wss://{tenant_id}.{base_domain}/v1/{kind}"
