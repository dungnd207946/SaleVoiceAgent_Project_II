"""Sinh và băm token đẩy dữ liệu. HÀM THUẦN, không I/O.

CHÉP CHỨ KHÔNG IMPORT `modules/enrollment/bi_mat.py`: file đó không phải
`contracts.py`, và `tests/test_module_boundaries.py` cấm import ruột module khác.
Luật đó đúng ở đây — hai loại khoá này có vòng đời khác hẳn nhau (khoá agent suy
dẫn tất định từ master key và xoay được; token nạp thì sinh ngẫu nhiên rồi thôi),
nên buộc chúng dùng chung một helper là buộc hai thứ không cùng bản chất phải đổi
cùng nhau.

Mười dòng.
"""

import hashlib
import secrets
from typing import Final

TIEN_TO: Final = "ody_in_"

_DO_DAI_BYTE: Final = 32


def sinh_token() -> tuple[str, str]:
    """`(token thô, sha256)`.

    Băm trả về cùng lúc chứ không để người gọi tự băm: hai chỗ băm là hai cơ hội
    dùng hai thuật toán khác nhau, và sai lệch đó chỉ lộ ra khi một token đúng bị
    từ chối.
    """
    tho = TIEN_TO + secrets.token_urlsafe(_DO_DAI_BYTE)
    return tho, bam(tho)


def bam(token_tho: str) -> str:
    """SHA-256 hex. Đây là thứ nằm trong `WHERE` lúc xác thực.

    KHÔNG dùng Argon2 như mật khẩu người dùng: token là 256 bit ngẫu nhiên, không
    có từ điển nào dò được, nên chi phí làm chậm chỉ rơi vào chính mình — và nó
    rơi vào ĐƯỜNG NÓNG, mỗi lô đẩy một lần.
    """
    return hashlib.sha256(token_tho.encode()).hexdigest()
