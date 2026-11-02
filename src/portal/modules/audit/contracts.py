"""Hợp đồng HTTP của `GET /audit` — màn «Nhật ký» đọc `control.audit_log`.

Spec: docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md §4. Tài liệu
bàn giao FE: docs/contracts/audit.md. Đổi field ở đây mà không sửa hai chỗ đó là
để tài liệu nói dối.

CON TRỎ MÃ HOÁ CẢ `(luc, id)`, không chỉ `id` như realestate: `luc` là `now()` =
thời điểm BẮT ĐẦU giao dịch, nên hai giao dịch chồng nhau có thể cho `id` lớn
hơn mà `luc` nhỏ hơn. Sắp `(luc DESC, id DESC)` và keyset trên cả cặp thì trang
sau vẫn xác định; keyset theo `id` một mình thì sót hàng ở biên.

Viết helper riêng thay vì import từ `realestate/contracts.py`: cursor ở đây mã hoá
CẢ `(luc, id)` chứ không chỉ `id`, nên `ma_con_tro`/`doc_con_tro` là hàm khác
chứ không phải bản sao; và audit không có lý do nghiệp vụ nào để phụ thuộc
realestate — chỉ để dùng chung một class lỗi ba dòng thì mối phụ thuộc đắt hơn
ba dòng đó.
"""

import base64
import binascii
from datetime import datetime
from typing import Any

from pydantic import BaseModel

TRANG_MAC_DINH = 50
GIOI_HAN_TRANG = 200
"""Trần `limit`. Cũng là số hàng tối đa router xin repo — xem `_xin_du_phong`."""

SO_NHOM_TOI_DA = 10
"""`?nhom=a,b,c` — tối đa 10 tiền tố. Sổ hiện có 12 tiền tố; FE gộp thành 9 nhóm
lọc, nhóm lớn nhất 4 tiền tố. 10 đủ rộng và chặn một chuỗi 10 KB đi vào `ANY()`."""

MA_ACTOR_MAY = "agent"
"""`actor` mà `enrollment/service.py` ghi cho HAI hành động: `agent.runtime_credentials`
(agent bootstrap lấy credential, :185) VÀ `agent.feedback` (khách hàng chấm điểm
hội thoại qua gateway, :265) — cùng giá trị actor nên công tắc `?may=false` ẩn CẢ
HAI cùng lúc, không tách được theo hành động. Là hành động MÁY, chiếm ~38% số
dòng trên dev — màn ẩn mặc định.

⚠️ Hệ quả CHẤP NHẬN ở đợt 1 (quyết định 2026-08-25 sau review): phản hồi/đánh
giá của KHÁCH HÀNG cuối cũng bị ẩn theo mặc định cùng với hành động máy thật sự
— feedback vẫn xem được đầy đủ ở màn `/quality` (nguồn riêng, không qua `/audit`),
và bật `?may=true` vẫn thấy. Nếu đợt 2 cần tách hai hành động này ra khỏi nhau ở
màn Nhật ký thì phải sửa TẠI ĐIỂM GHI (ghi actor khác nhau cho từng hành động),
không sửa được chỉ bằng cách đổi công tắc này.

`''` là ca THIẾU `created_by` ở `ingest.token_tao`/`ingest.token_xoa` (không xác
định được người thao tác), và `platform_admin` là NobleX qua token quản trị —
CẢ HAI KHÔNG thuộc nhóm bị `may=false` ẩn: chúng là việc cho người đọc, không
phải hành động máy."""


class LoiConTro(ValueError):
    """Cursor không đúng dạng — router dịch thành 400 `CURSOR_KHONG_HOP_LE`."""


def ma_con_tro(luc: datetime, id_: int) -> str:
    """`(luc, id)` của hàng CUỐI trang → chuỗi đục (base64url, bỏ đệm).

    Đục vì cursor là chi tiết cài đặt: để đọc được là mời FE tự chế, và ngày
    khoá sắp xếp đổi thì cách dùng đó gãy âm thầm. `isoformat()` giữ microsecond
    + múi giờ — cả hai đều cần cho phép so `(luc, id) <` ở repo."""
    tho = f"{luc.isoformat()}|{id_}"
    return base64.urlsafe_b64encode(tho.encode()).decode().rstrip("=")


def doc_con_tro(con_tro: str) -> tuple[datetime, int]:
    """Ngược của `ma_con_tro`. MỌI thứ không đúng dạng → `LoiConTro` — kể cả cursor
    dạng cũ chỉ có id, hay `luc` thiếu múi giờ (so với timestamptz sẽ lấy múi giờ
    phiên DB, tức kết quả tuỳ máy)."""
    try:
        tho = base64.urlsafe_b64decode(con_tro + "==").decode()
        luc_s, id_s = tho.rsplit("|", 1)
        luc = datetime.fromisoformat(luc_s)
        if luc.tzinfo is None:
            raise ValueError("luc thiếu múi giờ")
        return luc, int(id_s)
    except (ValueError, binascii.Error, UnicodeDecodeError) as e:
        raise LoiConTro("Con trỏ phân trang không hợp lệ") from e


class DongNhatKyOut(BaseModel):
    id: int
    luc: datetime
    hanhDong: str
    actorId: str
    """`control.audit_log.actor` NGUYÊN VĂN: `u_<id>`, `'agent'`, `'platform_admin'`
    hoặc `''`. FE dịch ba giá trị đặc biệt (spec §4)."""
    actorTen: str | None
    actorEmail: str | None
    """`None` khi `actor` không khớp `control.users` — người đã bị gỡ (0201 cố ý
    không FK), hoặc actor máy/hệ thống."""
    chiTiet: dict[str, Any]
    """jsonb NGUYÊN VĂN. Nhật ký là bằng chứng — đường đọc không «làm đẹp» nó."""


class TrangNhatKyOut(BaseModel):
    items: list[DongNhatKyOut]
    nextCursor: str | None = None
