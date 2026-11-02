"""Sinh khoá, băm khoá, suy dẫn bí mật — HÀM THUẦN, không I/O.

VÌ SAO SUY DẪN CHỨ KHÔNG LƯU: portal.current_tenant() (0001:41) parse tenant TỪ
TÊN ROLE bằng regex '^agent_(.+)$'. Nên mỗi tenant có ĐÚNG MỘT role
`agent_<slug>`, dùng chung cho pod chat lẫn pod voice — không tách role theo
deployment được, vì `agent_anphu_chat` sẽ parse ra tenant `anphu_chat` không tồn
tại.

Hệ quả: đổi mật khẩu mỗi lần gọi `/runtime-credentials` là pod voice đá văng pod chat. Nên hai pod
phải suy ra CÙNG một mật khẩu. Suy dẫn tất định làm được điều đó mà không cần lưu
bí mật nào trong DB — portal chỉ lưu `secret_version`, một int.

Xoay khoá = tăng version + ALTER ROLE + MinioAdmin.user_add. Kết nối đang mở
KHÔNG đứt: Postgres chỉ hỏi mật khẩu lúc nối mới.

Cả file là hàm thuần, cùng lý do `bundle.render()` của M3 và `parse.py` của M6:
đây là phần dễ sai nhất và nó phải test được không cần Postgres/MinIO/Qdrant.
"""

import base64
import hashlib
import hmac
import secrets
from typing import Final

LOAI_PG: Final = "pg"
LOAI_S3: Final = "s3"
_LOAI_HOP_LE: Final = frozenset({LOAI_PG, LOAI_S3})

DO_DAI_MASTER_TOI_THIEU: Final = 32
"""256 bit. Khoá gốc ngắn hơn là hạ toàn bộ hệ xuống mức đó."""

TIEN_TO_KHOA: Final = "ody_ag"
DO_DAI_KHOA_BYTE: Final = 32


def dan_xuat(loai: str, tenant_id: str, version: int, master: bytes) -> str:
    """Mật khẩu Postgres (`loai="pg"`) hoặc secret key S3 (`loai="s3"`).

    Trả base64url 43 ký tự — an toàn trong DSN, trong policy JSON, trong shell.

    Thông điệp HMAC dùng ĐỘ DÀI CÓ TIỀN TỐ chứ không nối bằng dấu hai chấm:
    f"{loai}:{tenant}:{ver}" cho ('pg','a:b') và ('pg:a','b') ra CÙNG chuỗi, tức
    hai tenant khác nhau suy ra cùng mật khẩu. Hôm nay regex của
    create_agent_role() chặn tenant_id có dấu hai chấm — nhưng hàm thuần không
    được dựa vào một ràng buộc nằm ở file khác.
    """
    if loai not in _LOAI_HOP_LE:
        raise ValueError(f"loai phải thuộc {sorted(_LOAI_HOP_LE)}, nhận {loai!r}")
    if len(master) < DO_DAI_MASTER_TOI_THIEU:
        raise ValueError(f"khoá gốc phải từ {DO_DAI_MASTER_TOI_THIEU} byte, nhận {len(master)}")

    phan = [loai.encode(), tenant_id.encode(), str(version).encode()]
    thong_diep = b"".join(len(p).to_bytes(4, "big") + p for p in phan)
    return _b64(hmac.new(master, thong_diep, hashlib.sha256).digest())


def bam_khoa(khoa_tho: str) -> str:
    """sha256 hex của api_key. Đây là thứ DUY NHẤT được lưu vào DB.

    Không salt, không bcrypt: khoá đã là 256 bit ngẫu nhiên đều, không phải mật
    khẩu người chọn. Bảng cầu vồng vô nghĩa với không gian đó, còn bcrypt thì
    biến một phép tra index thành một phép quét toàn bảng.
    """
    return hashlib.sha256(khoa_tho.encode()).hexdigest()


def sinh_khoa() -> tuple[str, str, str]:
    """Trả `(khoa_tho, sha256_hex, tien_to_hien_thi)`.

    `khoa_tho` tồn tại ĐÚNG MỘT LẦN — trong response tạo khoá. Không đường nào
    đọc lại được, kể cả admin.

    `tien_to_hien_thi` là 12 ký tự đầu, đủ để admin nhận ra khoá nào trên màn
    hình mà không đủ để dùng. Nó KHÔNG phải bí mật; lưu thẳng vào DB được.
    """
    khoa_tho = f"{TIEN_TO_KHOA}_{secrets.token_urlsafe(DO_DAI_KHOA_BYTE)}"
    return khoa_tho, bam_khoa(khoa_tho), khoa_tho[:12]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
