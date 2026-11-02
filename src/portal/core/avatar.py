"""Avatar DiceBear — SVG tất định theo seed, sinh local.

Ở `core/` vì HAI module đọc nó (`auth` cho user portal, `ops` cho khách) mà
Luật 3 cấm module import ruột nhau.

Giao dưới dạng data URI nhúng trong response sẵn có, KHÔNG mở endpoint ảnh
riêng — lý do đầy đủ ở docstring `tests/unit/test_avatar.py`.

HAI TẦNG STYLE (người dùng chốt 2026-08-22, sau một vòng thử thumbs làm mặc
định và bị chê «cợt nhả»):

- **Seed TRẦN** (tên user/khách, `avatar_seed` chưa chọn) → `initials` — chữ
  cái đầu trên nền màu, nghiêm túc, và trùng đúng luật `suy_initials` của auth
  (từ ĐẦU + từ CUỐI: "Trần Hải Đăng" → "TĐ").
- **Seed CÓ TIỀN TỐ** `style:seed` → style đó, NẾU nằm trong `_STYLES`. Chuỗi
  này chỉ do `GET /me/avatar-goi-y` phát ra và được lưu NGUYÊN VĂN vào
  `control.users.avatar_seed` — một cột, không cần cột style riêng. Tiền tố lạ
  rơi về initials với TRỌN chuỗi làm seed: một cái tên chứa `:` không được nổ
  và không được mất nửa đầu.

`_STYLES` chỉ nhận style CC0 / free-for-commercial (đã soi license trong
`dicebear_styles`): thêm một style CC BY vào đây là gánh nghĩa vụ ghi công
tác giả trong sản phẩm — đừng thêm mà không đi qua quyết định đó.

Màu nền dùng bảng MẶC ĐỊNH của DiceBear, không chép hex `av1..av4` của FE sang
đây: một bảng màu chép tay giữa hai repo là bản sao sẽ lệch, cùng lớp lỗi
`contracts/*.json` đã phải dựng cổng parity để canh.

`lru_cache` không trần: seed là tên người/khách — tập giá trị nhỏ, avatar tất
định nên cache không bao giờ ôi; sinh lại mỗi hàng danh sách khách mới là phí.
"""

from functools import lru_cache
from importlib.resources import files

from dicebear import Avatar, Style


def _nap(ten: str) -> Style:
    return Style.from_json(files("dicebear_styles").joinpath(f"{ten}.json").read_text("utf-8"))


_MAC_DINH = _nap("initials")

_STYLES: dict[str, Style] = {
    "thumbs": _nap("thumbs"),
    "pixel-art": _nap("pixel-art"),
    "bottts": _nap("bottts"),
    "avataaars": _nap("avataaars"),
    "lorelei": _nap("lorelei"),
    "notionists": _nap("notionists"),
}
"""Sáu style của lưới «Đổi avatar» — `router.avatar_goi_y` đọc danh sách này."""

TEN_STYLES_GOI_Y = tuple(_STYLES)


def chu_cai_dau(ten: str) -> str:
    """Chữ trên avatar initials — MỘT nguồn cho cả `UserOut.initials` lẫn seed
    DiceBear (`auth.service.suy_initials` uỷ quyền về đây).

    Từ ĐẦU + từ CUỐI ("Trần Hải Đăng" → "TĐ"); tên MỘT TỪ lấy ĐÚNG MỘT chữ
    ("Hùng" → "H", không phải "HÙ" — DiceBear tự suy sẽ lấy 2 ký tự đầu, người
    dùng bắt được trên màn thật 2026-08-22).
    """
    tu = [t for t in ten.split() if t]
    if not tu:
        return "?"
    if len(tu) == 1:
        return tu[0][0].upper()
    return (tu[0][0] + tu[-1][0]).upper()


def _tach(seed: str) -> tuple[Style, str]:
    """Seed `style:seed` → style đó; seed TRẦN → initials với seed là CHỮ CÁI
    đã suy (không đưa nguyên tên cho DiceBear tự suy — xem `chu_cai_dau`).
    Giá phải trả có ý thức: màu nền suy từ chuỗi chữ cái, hai người trùng
    initials trùng màu — chấp nhận được, bảng màu vốn chỉ vài sắc."""
    truoc, hai_cham, sau = seed.partition(":")
    if hai_cham and truoc in _STYLES:
        return _STYLES[truoc], sau
    return _MAC_DINH, chu_cai_dau(seed)


def sinh_avatar_data_uri(seed: str) -> str:
    """Sinh KHÔNG cache — cho seed dùng-một-lần (`GET /me/avatar-goi-y` sinh
    hàng chục seed ngẫu nhiên mỗi lượt; đi qua `lru_cache` là flood cache của
    seed thật)."""
    style, seed_tho = _tach(seed)
    return Avatar(style, {"seed": seed_tho}).to_data_uri()


@lru_cache(maxsize=4096)
def avatar_data_uri(seed: str) -> str:
    """Data URI `data:image/svg+xml;charset=utf-8,…` — có cache, dùng cho seed
    SỐNG LÂU (tên user/khách, `avatar_seed` đã lưu)."""
    return sinh_avatar_data_uri(seed)
