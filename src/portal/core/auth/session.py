"""Bản ghi phiên đăng nhập ở Redis.

═══════════════════════════════════════════════════════════════════════════════
 REDIS GIỮ PHIÊN, POSTGRES GIỮ QUYỀN — ĐỪNG TRỘN HAI VIỆC
═══════════════════════════════════════════════════════════════════════════════
Bản ghi này CHỈ trả lời "ai đang đăng nhập và đang ở workspace nào". Nó KHÔNG
chứa `role`, KHÔNG chứa `actions`. Quyền đọc từ control.memberships MỖI request —
PQ_01 §BR-Q04, và YC03: "sa thải một người xong, 15 phút nữa họ vẫn sửa được dữ
liệu" là đúng cái phải tránh.

Nhét quyền vào đây thì gỡ membership không có hiệu lực tới khi phiên hết hạn, và
lời hứa đó thành sai một cách không ai nhìn thấy. `test_ban_ghi_khong_chua_quyen`
canh đúng điều này.

VÌ SAO COOKIE ĐỐI XỨNG CHỨ KHÔNG JWT (spec §2.4): JWT đáng giá khi nó cho bạn
KHÔNG phải tra store. Ta đã phải tra store mỗi request (workspace hiện tại nằm
đây, và thu hồi phiên phải có hiệu lực ngay), nên JWT chỉ còn là chi phí cộng ba
hố: alg confusion, hạn dài không thu hồi được, token phải nằm chỗ JS đọc được.
"""

import json
import secrets
from dataclasses import dataclass
from typing import Final

from redis.asyncio import Redis

TEN_COOKIE: Final = "odyssey_session"
TTL_GIAY: Final = 12 * 3600
_TIEN_TO: Final = "sess:"


@dataclass(frozen=True, slots=True)
class BanGhiPhien:
    user_id: str
    tenant_id: str | None
    """None = user chưa thuộc workspace nào (vừa tự đăng ký).

    Trạng thái HỢP LỆ từ 2026-08-15 (spec bo-organization §5.0), đảo ngược PQ_01
    Q01. Trước đó mọi user đều ra đời qua lời mời VÀO một workspace nên None là
    không thể xảy ra, và `loi.khong_co_workspace()` (409) canh điều đó. Với tự
    đăng ký thì 409 là ngõ cụt: người vừa đăng ký có 0 workspace và không có
    đường nào tới màn tạo workspace đầu tiên.

    ⚠ Mọi chỗ đọc trường này phải xử lý None. `require()` chặn sớm bằng 403;
    `dung_session_out` trả `workspaces=[]`.
    """


def _khoa(session_id: str) -> str:
    return f"{_TIEN_TO}{session_id}"


async def tao(r: Redis, *, user_id: str, tenant_id: str | None) -> str:
    """Tạo phiên mới, trả session_id để đặt vào cookie.

    32 byte từ `secrets` — không phải `random` (đoán được từ vài mẫu), không phải
    uuid4 (uuid là định danh, không phải khoá bí mật; v4 có 122 bit entropy nhưng
    dùng nó ở đây làm người sau tưởng một uuid bất kỳ cũng thay thế được).
    """
    session_id = secrets.token_urlsafe(32)
    await r.set(_khoa(session_id), json.dumps({"user_id": user_id, "tenant_id": tenant_id}), ex=TTL_GIAY)
    return session_id


async def doc(r: Redis, session_id: str) -> BanGhiPhien | None:
    """Đọc phiên và GIA HẠN TTL (sliding). None = không có / đã hết hạn.

    Chặn `session_id` rỗng ngay: cookie vắng mặt tới đây là chuỗi rỗng, và không
    chặn thì nó thành một lượt GET khoá `sess:` — một khoá mà bất kỳ ai ghi được
    vào Redis cũng đặt được.
    """
    if not session_id:
        return None
    tho = await r.get(_khoa(session_id))
    if tho is None:
        return None
    await r.expire(_khoa(session_id), TTL_GIAY)
    d = json.loads(tho)
    # `.get` chứ không `[...]`: bản ghi phiên tạo TRƯỚC 2026-08-15 luôn có khoá
    # `tenant_id`, nhưng phiên tạo sau có thể mang `null` — và một phiên cũ còn
    # sống trong Redis lúc deploy không được biến thành 500.
    return BanGhiPhien(user_id=d["user_id"], tenant_id=d.get("tenant_id"))


async def xoa(r: Redis, session_id: str) -> None:
    await r.delete(_khoa(session_id))


async def doi_workspace(r: Redis, session_id: str, tenant_id: str | None) -> None:
    """Đổi workspace hiện tại của phiên. GIỮ NGUYÊN TTL đang có.

    Giữ TTL chứ không gia hạn: nếu đổi workspace cũng đẩy hạn ra xa thì bấm qua
    lại giữa hai workspace là một phiên không bao giờ hết hạn. Việc gia hạn thuộc
    về `doc()` — nó chạy trên MỌI request, nên hạn vẫn trượt theo hoạt động thật.

    Raise KeyError nếu phiên không tồn tại: im lặng bỏ qua nghĩa là người dùng bấm
    đổi workspace, không có gì xảy ra, và không ai biết vì sao.

    Đọc-rồi-ghi chứ không ghi đè cả bản ghi: đổi workspace là đổi ĐÚNG MỘT trường,
    và dựng lại bản ghi từ tham số là cách dễ nhất để một phiên tự nhiên đổi chủ.

    `tenant_id=None` LÀ HỢP LỆ — cùng nghĩa với `BanGhiPhien.tenant_id` (xem
    docstring của nó): phiên không trỏ vào workspace nào. Đường đi tới đó là
    `GET /me` tự chữa cho một phiên trỏ vào workspace vừa bị xoá, khi người dùng
    không còn workspace nào khác.
    """
    khoa = _khoa(session_id)
    tho = await r.get(khoa)
    if tho is None:
        raise KeyError(f"phiên {session_id[:8]}… không tồn tại")
    ttl = await r.ttl(khoa)
    d = json.loads(tho)
    d["tenant_id"] = tenant_id
    await r.set(khoa, json.dumps(d), ex=ttl if ttl > 0 else TTL_GIAY)
