"""Thumbnail WebP cho ảnh đã kéo về kho — giao diện chat tải bản nhỏ thay vì ảnh gốc nhiều MB."""

import hashlib
import threading
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from io import BytesIO
from typing import TYPE_CHECKING

from portal.modules.kb import settings

if TYPE_CHECKING:
    from portal.modules.kb.contracts import ObjectStore

_THU_MUC_THUM_NGOAI = "kb/anh/thumb"

# Trần RIÊNG của ta, thay trần 178M của Pillow. 250M pixel ở 1/8 mẫu là ~4M pixel, an
# toàn về RAM; vượt mức này thì ảnh gốc đã sai chứ không phải ta thiếu năng lực.
_TRAN_PIXEL = 250_000_000
_NGUONG_KHOA = 60_000_000
_KHOA_ANH_LON = threading.Semaphore(1)


def thumb_key(media_key: str) -> str:
    """`.../mb.jpg` → `.../mb.thumb.webp` — cùng thư mục với ảnh gốc, cùng luật phát công khai."""
    tail = media_key.rsplit("/", 1)[-1]
    base = media_key.rsplit(".", 1)[0] if "." in tail else media_key
    return f"{base}{settings.THUMB_SUFFIX}"


def thumb_key_cho_media(*, media_url: str, content_hash: str) -> str:
    """Khoá thumb cho MỘT hàng `media`, kể cả khi ảnh gốc không nằm trong kho ta.

    `thumb_key()` một mình chỉ đúng với khoá nội bộ: đưa `https://cdn.x/a__intro.jpg`
    vào nó cho ra `https://cdn.x/a__intro.thumb.webp` — một chuỗi trông như khoá nhưng
    không phải, và `put()` sẽ tạo object ở một đường dẫn vô nghĩa mà không ai báo.

    Với URL ngoài, khoá suy từ `content_hash` (cùng nếp "sha nằm trong đường dẫn" của
    đường upload). Hash rỗng thì suy từ chính URL — cần một khoá ỔN ĐỊNH giữa các lần
    chạy, nếu không mỗi lần backfill lại sinh thêm một object mồ côi.
    """
    from portal.modules.kb.storage.object_store import is_internal_key

    if is_internal_key(media_url):
        return thumb_key(media_url)
    ten = content_hash or hashlib.sha256(media_url.encode()).hexdigest()
    return f"{_THU_MUC_THUM_NGOAI}/{ten}{settings.THUMB_SUFFIX}"


async def sinh_va_luu(
    store: "ObjectStore",
    *,
    media_url: str,
    content_hash: str,
    tai_ve: "Callable[[], bytes | Awaitable[bytes]]",
) -> str:
    """Tải ảnh → WebP → ghi kho. Trả **KHOÁ**, không phải URL.

    Khoá thì bền; URL (presigned) chết sau vài phút — `public_url_of()` biến khoá thành link.

    `tai_ve` là hàm chứ không phải byte: chỗ gọi có thể lấy ảnh bằng httpx async,
    còn test lấy từ bộ nhớ — tiêm vào đây giữ hàm này không biết gì về mạng.

    `to_webp` chạy TRƯỚC `put`: byte không phải ảnh thì ném ở bước đổi định dạng và
    kho không có object rác nào, thay vì một khoá trỏ tới một tệp vỡ.

    `to_webp` PHẢI qua `to_thread`: Pillow resize LANCZOS + WebP `method=6` là CPU thuần,
    chạy trong event loop là cả worker đứng.
    """
    import asyncio
    import inspect

    goc = tai_ve()
    if inspect.isawaitable(goc):
        goc = await goc
    webp = await asyncio.to_thread(to_webp, goc)
    khoa = store.key(path=thumb_key_cho_media(media_url=media_url, content_hash=content_hash))
    await store.put(key=khoa, data=webp, content_type="image/webp")
    return khoa


def to_webp(data: bytes, *, width: int = settings.THUMB_WIDTH) -> bytes:
    """Ảnh bất kỳ → WebP rộng tối đa `width`, GIỮ tỉ lệ.

    KHÔNG PHÓNG TO ảnh nhỏ hơn `width`: nội suy lên chỉ cho ra ảnh mờ mà nặng hơn
    bản gốc, tức thumbnail phản tác dụng đúng ở chỗ nó tồn tại để giúp.

    `Image.thumbnail()` chứ không `resize()`: nó tự tính chiều còn lại theo tỉ lệ và
    tự bỏ qua khi ảnh đã nhỏ hơn — hai hành vi trên đúng bằng một lời gọi. Ảnh
    sản phẩm méo tỉ lệ là ảnh sai hình.

    Ném `ValueError` cho byte không phải ảnh: Pillow ném `UnidentifiedImageError`
    (con của `OSError`), lẫn vào cùng nhóm với lỗi mạng/đĩa ở tầng gọi.
    """
    from PIL import Image, UnidentifiedImageError

    # Trần chống bom giải nén của Pillow (178M pixel) chặn cả ảnh thật cỡ vài trăm M pixel.
    # Ta tự chặn bằng `_TRAN_PIXEL` + `draft()` bên dưới, nên tắt trần của Pillow.
    Image.MAX_IMAGE_PIXELS = None

    try:
        im = Image.open(BytesIO(data))
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"không đọc được dữ liệu ảnh: {e}") from e

    goc = im.size

    # `draft()` để decoder JPEG giảm mẫu 1/2…1/8 NGAY KHI giải mã: ảnh 477M pixel giải ở
    # 1/8 còn 7,5M pixel (~22 MB RAM) thay vì 1,4 GB. Không có tác dụng với PNG.
    im.draft("RGB", (width, width))

    # Trần kiểm SAU khi giảm mẫu: JPEG khổng lồ được `draft()` đưa về vài triệu pixel —
    # chặn trước là chặn oan đúng những tấm đọc được. Trần còn tác dụng với PNG khổng lồ, nơi
    # `draft()` không làm gì và RAM là thật.
    pixel = im.size[0] * im.size[1]
    if pixel > _TRAN_PIXEL:
        raise ValueError(
            f"ảnh {goc[0]}×{goc[1]} = {goc[0] * goc[1] / 1e6:.0f}M pixel (định dạng "
            f"{im.format} không giảm mẫu được), vượt trần {_TRAN_PIXEL / 1e6:.0f}M — gửi bản nhỏ hơn"
        )

    # Ảnh lớn giải nối tiếp: 8 làn thumb × 750 MB là OOM, và OOM giết cả worker.
    khoa = _KHOA_ANH_LON if im.size[0] * im.size[1] > _NGUONG_KHOA else nullcontext()
    with khoa:
        try:
            im.load()
        except OSError as e:
            raise ValueError(f"không đọc được dữ liệu ảnh: {e}") from e
        im.thumbnail((width, width * 100), Image.Resampling.LANCZOS)
        ra = BytesIO()
        im.save(ra, format="WEBP", quality=settings.THUMB_QUALITY, method=6)
    return ra.getvalue()
