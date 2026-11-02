"""Khoá kho tệp → URL khách mở được."""

PUBLIC_PATH = "/api/v1/public/files/"

_NOI_BO = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal", "[::1]")


def la_noi_bo(base: str) -> bool:
    """Base có phải địa chỉ chỉ mở được từ trong nhà."""
    return bool(base) and any(x in base for x in _NOI_BO)


def kiem_base(base: str) -> str:
    """Ném nếu base là địa chỉ nội bộ. Dùng ở đường GHI, KHÔNG ở đường đọc.

    URL này đi vào payload Qdrant và cột `media.public_url`, rồi agent gửi cho khách.
    Một `localhost` lọt vào đó là ảnh vỡ phía khách và không lỗi nào phía ta — nên
    script backfill (`backfill_public_url.py`) phải
    DỪNG HẲN chứ không ghi. Nó là người gọi duy nhất còn lại.

    ⚠ `public_url_of()` cố ý KHÔNG gọi hàm này nữa (2026-08-17, xem docstring dưới).
    """
    if la_noi_bo(base):
        raise ValueError(f"PUBLIC_BASE_URL={base!r} là địa chỉ nội bộ — khách không mở được")
    return base


def public_url_of(key_or_url: str) -> str:
    """Rỗng → rỗng. Đã là URL → nguyên văn. Khoá → nối base.

    Chưa cấu hình `PUBLIC_BASE_URL` thì trả rỗng: agent coi là "không có ảnh", còn
    hơn nhận một link không mở được.

    ⚠ Base NỘI BỘ (`localhost`…) cũng trả rỗng, KHÔNG ném (đổi 2026-08-17, cùng lúc
    `PORTAL_BASE_URL` gộp vào `PUBLIC_BASE_URL`). Từ đó biến này còn mang link mời
    trong thư, và ở dev `http://localhost:5273` là giá trị ĐÚNG cho việc đó — ném ở
    đây sẽ biến mọi đường ĐỌC media ở dev thành 500. Rỗng cũng đúng theo chính lệ
    của module: «thà không có link còn hơn một link không mở được», và nó là ĐÚNG
    HÀNH VI dev đang có hôm nay (biến để rỗng ⇒ không link ảnh).

    Đổi này KHÔNG nới phía GHI: script backfill vẫn qua `kiem_base()` và vẫn
    dừng hẳn — chỗ ghi vào DB thì ồn ào mới đúng.
    """
    from portal.core.config import get_settings

    if not key_or_url:
        return ""
    if key_or_url.startswith(("http://", "https://")):
        return key_or_url
    base = get_settings().public_base_url.rstrip("/")
    if not base or la_noi_bo(base):
        return ""
    return f"{base}{PUBLIC_PATH}{key_or_url}"
