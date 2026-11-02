"""Băm và kiểm mật khẩu bằng Argon2id.

VÌ SAO CÓ `kiem_gia()`: nếu đường "email không tồn tại" trả 401 ngay mà đường
"email có thật, sai mật khẩu" phải chạy Argon2 (cố ý chậm), thì thời gian phản
hồi tự tố ra email nào có trong hệ thống. Một máy dò chỉ cần đo đồng hồ là có
danh sách khách hàng. Nên đường không-tìm-thấy cũng phải verify vào một hash mồi.
Spec §4.4: một mã 401 cho cả ba tình huống đăng nhập là cố ý — nhưng một mã
chung mà đồng hồ khác nhau thì vẫn rò.

Tham số dùng mặc định của argon2-cffi (time_cost=3, memory_cost=64MiB,
parallelism=4) — đó là bản OWASP khuyến nghị. Không tự đặt số: tự đặt nghĩa là
tự bảo trì một quyết định mật mã mà thư viện đã bảo trì hộ.
"""

from contextlib import suppress

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError

_hasher = PasswordHasher()

# Hash của một chuỗi không ai dùng làm mật khẩu. Tính MỘT LẦN lúc import — tính
# lại mỗi request thì chính việc tính đó là một khác biệt thời gian đo được.
_HASH_MOI = _hasher.hash("khong-phai-mat-khau-cua-ai")


def bam(mat_khau: str) -> str:
    return _hasher.hash(mat_khau)


def kiem(bam_luu: str, mat_khau: str) -> bool:
    try:
        return _hasher.verify(bam_luu, mat_khau)
    except (VerifyMismatchError, Argon2Error, ValueError):
        # Argon2Error phủ hash sai định dạng ở tầng thư viện; ValueError phủ chuỗi
        # rỗng và chuỗi không parse được thành hash. Một hàng DB hỏng phải thành
        # 401, không thành 500 — người dùng không đăng nhập được là đúng, còn
        # trang lỗi 500 thì vừa sai thông điệp vừa lộ có gì đó bất thường.
        return False


def kiem_gia() -> None:
    """Verify vào hash mồi để cân thời gian. Kết quả bị bỏ — mục đích là đồng hồ."""
    with suppress(VerifyMismatchError, Argon2Error):
        _hasher.verify(_HASH_MOI, "x")
