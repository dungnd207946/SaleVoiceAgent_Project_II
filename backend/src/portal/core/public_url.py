"""Khoá kho tệp → URL khách mở được (agent gửi link này vào cửa sổ chat).

Route phát tệp: `GET /api/v1/public/files/{key}` (modules/kb/router.py) — chỉ mở các
thư mục khai tường minh ở đó.
"""

PUBLIC_PATH = "/api/v1/public/files/"

_NOI_BO = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal", "[::1]")


def la_noi_bo(base: str) -> bool:
    """Base có phải địa chỉ chỉ mở được từ trong nhà."""
    return bool(base) and any(x in base for x in _NOI_BO)


def public_url_of(key_or_url: str) -> str:
    """Rỗng → rỗng. Đã là URL → nguyên văn. Khoá → nối base.

    Chưa cấu hình `PUBLIC_BASE_URL`, hoặc base là địa chỉ NỘI BỘ (`localhost`…) ⇒ rỗng:
    URL này đi vào payload Qdrant rồi tới tay khách, và «không có ảnh» còn hơn một link
    không mở được — vỡ phía khách mà không lỗi nào phía ta.
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
