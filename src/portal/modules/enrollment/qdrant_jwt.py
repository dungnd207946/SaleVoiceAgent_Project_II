"""Ký JWT cho Qdrant — HÀM THUẦN, không I/O, không phụ thuộc ngoài.

Qdrant là kho DUY NHẤT trong hệ mà cách ly tenant chưa được cưỡng chế ở phía kho.
So ba kho cạnh nhau thì thấy ngay chỗ lệch:

    Postgres  → role riêng `agent_<id>` + mật khẩu riêng  → RLS FORCE cưỡng chế
    Kho tệp   → access/secret key riêng + policy tiền tố  → MinIO cưỡng chế
    Qdrant    → CHỈ tên collection                        → KHÔNG AI cưỡng chế

`core/ten_tai_nguyen.py` đã nói thẳng điều đó: *«Qdrant không có RLS — với kho đó,
TÊN chính là cơ chế cách ly»*. Nhưng tên là thứ pod tự gõ vào truy vấn, nên nó là
một QUY ƯỚC, không phải một bức tường: pod hỏi `kb_<tenant khác>` thì Qdrant TRẢ
DỮ LIỆU. Postgres hỏi sai tenant thì trả 0 hàng — đó là khác biệt giữa hai loại.

File này đóng khoảng lệch đó: portal ký một token chỉ mở ĐÚNG MỘT collection, chỉ
ĐỌC, và HẾT HẠN. Từ lúc Qdrant bật `jwt_rbac`, cách ly do Qdrant cưỡng chế.

── VÌ SAO TỰ KÝ, KHÔNG THÊM PyJWT ──────────────────────────────────────────
«Đừng tự viết crypto» đúng cho phần VERIFY — nơi có alg confusion, `alg: none`, và
so sánh chữ ký không hằng thời gian. Ở đây portal chỉ KÝ; Qdrant verify. Ký HS256
là đúng một lời gọi `hmac.new(...).digest()` trên `b64(header).b64(payload)`, và
`bi_mat.py` cạnh bên đã import sẵn cả bốn module stdlib cần dùng.

Đổi lại, thêm một phụ thuộc runtime cho ~20 dòng là thêm một thứ phải khai ở
`[project].dependencies` (có cổng `test_khai_bao_phu_thuoc.py`), phải vá khi có
CVE, và phải đọc khi ai đó hỏi «token này gồm gì». Bản tự ký thì mở file ra là
thấy toàn bộ payload.

── HỢP ĐỒNG VỚI QDRANT ─────────────────────────────────────────────────────
Qdrant ≥ 1.11 (dev đang chạy 1.19). Token là JWT HS256 ký bằng CHÍNH
`service.api_key` của Qdrant — không có khoá thứ hai, không có endpoint đăng ký.
Claim `access` nhận danh sách phạm vi theo collection:

    {"exp": 1234567890, "access": [{"collection": "kb_anphu", "access": "r"}]}

`"r"` = read-only. Pod agent KHÔNG được ghi: đường ghi vào Qdrant là của portal
(worker `kb`), và một pod ghi được là một pod xoá được kho tri thức của chính
tenant nó.

── HÀNH VI ĐO ĐƯỢC trên Qdrant 1.19.0, `jwt_rbac: true` (2026-08-15) ────────
Ghi lại vì hai chỗ KHÔNG như trực giác, và người sửa file này sẽ đoán sai y hệt:

| Thao tác bằng token scope `kb_anphu` | Kết quả |
|---|---|
| Đọc `kb_anphu` | `200` |
| Đọc `kb_sunrise` | `403` |
| Ghi vào `kb_anphu` | `403` — `"r"` chặn thật |
| `GET /collections` (liệt kê tất cả) | `200`, nhưng **ĐÃ LỌC**: chỉ thấy `kb_anphu` |
| Token hết hạn · token ký sai khoá | `403` (KHÔNG phải `401`) |

Hai điều đáng nhớ:
  · **Liệt kê không bị từ chối, nó bị LỌC.** Pod thấy một thế giới chỉ có kho của
    chính nó — đúng ngữ nghĩa RLS, và tốt hơn `403` vì client không phải xử lý
    một ca lỗi cho một thao tác hợp lệ. Đừng "sửa" thành 403.
  · **Mọi thất bại xác thực đều `403`**, kể cả hết hạn. Ai viết retry theo `401`
    sẽ không bao giờ làm mới credential.
"""

import hashlib
import hmac
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Final

from portal.modules.enrollment.bi_mat import _b64

THUAT_TOAN: Final = "HS256"

_TIEU_DE: Final = {"alg": THUAT_TOAN, "typ": "JWT"}

QUYEN_DOC: Final = "r"
"""Chỉ đọc. Xem docstring đầu tệp — pod không có việc gì phải ghi vào Qdrant."""


def ky_token_doc(*, collection: str, het_han: datetime, khoa_ky: str, them: Sequence[str] = ()) -> str:
    """JWT chỉ-đọc trên `collection` (+ các collection `them`, cùng quyền đọc), hết hạn tại `het_han`.

    `them` có từ 2026-10-05: kho dữ liệu web công khai theo tenant (`<tenant>_public_web`) đứng
    cạnh kho tài liệu — vẫn CHỈ những tên portal suy từ tenant_id, không nhận tên từ ngoài.

    NHẬN MỐC TUYỆT ĐỐI, không nhận TTL: người gọi đã tính `expires_at` cho cả bộ
    credential, nên truyền thẳng chính giá trị đó vào đây làm `exp` của token là
    hai mốc KHÔNG THỂ lệch nhau. Nhận `han_giay` rồi tự cộng `now()` là dựng hai
    đồng hồ cho một sự kiện, và chúng sẽ lệch đúng bằng thời gian giữa hai dòng.

    Ném `ValueError` nếu `khoa_ky` rỗng: token ký bằng chuỗi rỗng là token mà BẤT
    KỲ AI cũng ký lại được, và nó trông y hệt token thật ở mọi chỗ trừ chữ ký.
    Người gọi phải xử lý ca «chưa cấu hình khoá» tường minh — xem
    `service.lay_runtime_credentials`.
    """
    if not khoa_ky:
        raise ValueError("khoá ký rỗng — không phát được token Qdrant, xem docstring")

    than_tin = {
        "exp": int(het_han.timestamp()),
        # DANH SÁCH, không phải chuỗi. Qdrant hiểu `access: "r"` dạng chuỗi là
        # quyền đọc TOÀN INSTANCE — đúng thứ file này tồn tại để không cấp.
        "access": [{"collection": c, "access": QUYEN_DOC} for c in (collection, *them)],
    }
    than = f"{_b64(_goi(_TIEU_DE))}.{_b64(_goi(than_tin))}"
    chu_ky = hmac.new(khoa_ky.encode(), than.encode(), hashlib.sha256).digest()
    return f"{than}.{_b64(chu_ky)}"


def _goi(o: dict) -> bytes:
    """JSON tất định, không khoảng trắng thừa.

    `separators` bỏ dấu cách mặc định của `json.dumps` — dấu cách vẫn parse được
    nhưng làm token dài ra vô ích, và nó đi kèm mỗi request của mọi pod.
    `sort_keys` để hai lần ký cùng đầu vào ra cùng chuỗi: không có nó thì một bài
    canh so token bằng nhau sẽ đỏ tuỳ thứ tự dict.
    """
    return json.dumps(o, separators=(",", ":"), sort_keys=True).encode()
